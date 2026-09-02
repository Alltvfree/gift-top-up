"""XAUUSD_TrendPullback_v1 — modular trend-pullback strategy.

Flow (spec §§6-8): **H1 trend bias → M15 structure/pullback setup → M5 entry
confirmation**, combined into a 0-100 score. A trade is only proposed when the
higher-timeframe trend is clear, the setup and entry conditions agree with it,
the spread is acceptable, and the score meets the configured minimum.

⚠️ These conditions and thresholds are a configurable STARTING POINT, not a
proven-profitable system. The value here is a reproducible, fully-explained
signal — not a promise of returns.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from app.core.config import StrategyConfig
from app.core.models import (
    OrderSide,
    Signal,
    SignalType,
    SymbolInfo,
    TrendState,
)
from app.indicators.indicators import atr as atr_ind
from app.indicators.indicators import ema, rsi
from app.risk.stop_loss import compute_stop_target
from app.strategies.base import Strategy, StrategyInput, _last_time


@dataclass
class _Eval:
    """Intermediate scoring state for one candidate direction."""

    components: dict
    indicators: dict
    reasons: list

    @property
    def score(self) -> float:
        return float(sum(self.components.values()))


class TrendPullbackStrategy(Strategy):
    name = "XAUUSD_TrendPullback_v1"

    def __init__(self, config: StrategyConfig, *, atr_multiplier: float,
                 risk_reward: float, max_spread_points: float) -> None:
        self.config = config
        self.version = config.version
        self._atr_multiplier = atr_multiplier
        self._risk_reward = risk_reward
        self._max_spread_points = max_spread_points

    # --- public API ----------------------------------------------------------
    def evaluate(self, data: StrategyInput) -> Signal:
        cfg = self.config

        # 1) Sufficient data on every timeframe (no partial-window indicators).
        need_trend = max(cfg.ema_slow, cfg.ema_fast) + 2
        need_setup = max(cfg.ema_fast, cfg.atr_period, cfg.structure_lookback) + 2
        need_entry = max(cfg.ema_short, cfg.rsi_period) + 2
        if (
            len(data.trend_df) < need_trend
            or len(data.setup_df) < need_setup
            or len(data.entry_df) < need_entry
        ):
            return self._wait(
                data, 0.0, "insufficient candle history to evaluate",
                {}, {},
            )

        # 2) H1 trend bias.
        trend, trend_ind = self._detect_trend(data.trend_df)
        indicators = dict(trend_ind)
        if trend is TrendState.NO_TREND:
            return self._wait(
                data, 0.0, "H1 trend unclear (NO_TREND) — standing aside",
                {"trend": 0.0}, indicators,
            )

        # 3) Volatility gate on the setup timeframe.
        setup_atr = float(
            atr_ind(
                data.setup_df["high"], data.setup_df["low"],
                data.setup_df["close"], cfg.atr_period,
            ).iloc[-1]
        )
        indicators["atr"] = round(setup_atr, data.symbol_info.digits)
        if cfg.min_atr > 0 and setup_atr < cfg.min_atr:
            return self._wait(
                data, 0.0, f"ATR {setup_atr:.4f} below min_atr {cfg.min_atr}",
                {"trend": cfg.weights.trend}, indicators,
            )
        if cfg.max_atr > 0 and setup_atr > cfg.max_atr:
            return self._wait(
                data, 0.0, f"ATR {setup_atr:.4f} above max_atr {cfg.max_atr}",
                {"trend": cfg.weights.trend}, indicators,
            )

        # 4) Score the direction implied by the trend.
        side = OrderSide.BUY if trend is TrendState.BULLISH else OrderSide.SELL
        ev = self._score(data, trend, side, setup_atr, indicators)

        # 5) Spread gate (only matters if we would otherwise trade).
        spread = data.spread_points
        spread_ok = spread is None or spread <= self._max_spread_points
        ev.indicators["spread_points"] = (
            round(spread, 1) if spread is not None else None
        )

        score = ev.score
        min_score = cfg.min_score

        if score < min_score:
            return self._wait(
                data, score,
                self._explain(trend, ev, score, min_score, actionable=False),
                ev.components, ev.indicators,
            )
        if not spread_ok:
            ev.reasons.append(
                f"Spread {spread:.1f} > max {self._max_spread_points}"
            )
            return self._wait(
                data, score,
                self._explain(trend, ev, score, min_score, actionable=False,
                              extra="spread too wide"),
                ev.components, ev.indicators,
            )

        # 6) Build an actionable signal with ATR-based SL/TP.
        entry = self._entry_price(data, side)
        target = compute_stop_target(
            side, entry, setup_atr, data.symbol_info,
            atr_multiplier=self._atr_multiplier, risk_reward=self._risk_reward,
        )
        direction = SignalType.BUY if side is OrderSide.BUY else SignalType.SELL
        bar_time = _last_time(data.entry_df, data.now)
        return Signal(
            signal_id=self._new_signal_id(
                data.symbol_info.name, bar_time, direction.value
            ),
            timestamp=data.now,
            symbol=data.symbol_info.name,
            direction=direction,
            score=round(score, 2),
            strategy=self.name,
            strategy_version=self.version,
            entry=target.entry,
            stop_loss=target.stop_loss,
            take_profit=target.take_profit,
            risk_reward=self._risk_reward,
            reason=self._explain(trend, ev, score, min_score, actionable=True),
            components=ev.components,
            indicators=ev.indicators,
        )

    # --- trend ---------------------------------------------------------------
    def _detect_trend(self, df: pd.DataFrame) -> tuple[TrendState, dict]:
        cfg = self.config
        close = df["close"]
        ema_fast = float(ema(close, cfg.ema_fast).iloc[-1])
        ema_slow = float(ema(close, cfg.ema_slow).iloc[-1])
        price = float(close.iloc[-1])
        ind = {
            "ema_fast": round(ema_fast, 4),
            "ema_slow": round(ema_slow, 4),
            "trend_close": round(price, 4),
        }
        if ema_fast > ema_slow and price > ema_fast:
            state = TrendState.BULLISH
        elif ema_fast < ema_slow and price < ema_fast:
            state = TrendState.BEARISH
        else:
            state = TrendState.NO_TREND
        ind["trend"] = state.value
        return state, ind

    # --- scoring -------------------------------------------------------------
    def _score(
        self,
        data: StrategyInput,
        trend: TrendState,
        side: OrderSide,
        setup_atr: float,
        base_indicators: dict,
    ) -> _Eval:
        cfg = self.config
        w = cfg.weights
        components: dict = {"trend": w.trend}  # trend already confirmed clear
        indicators = dict(base_indicators)
        reasons = [f"H1 Trend: {trend.value}"]

        # --- Market structure (setup timeframe) ---
        structure_ok = self._structure_ok(data.setup_df, side)
        components["structure"] = w.structure if structure_ok else 0.0
        reasons.append(
            ("Higher-Low" if side is OrderSide.BUY else "Lower-High")
            + f": {'YES' if structure_ok else 'NO'}"
        )

        # --- Pullback toward EMA-fast (setup timeframe) ---
        pullback_ok, dist = self._pullback_ok(data.setup_df, side, setup_atr)
        components["pullback"] = w.pullback if pullback_ok else 0.0
        indicators["pullback_dist_atr"] = round(dist, 3)
        reasons.append(f"M15 Pullback: {'YES' if pullback_ok else 'NO'}")

        # --- Momentum (entry timeframe) ---
        momentum = self._momentum_score(data.entry_df, side, w.momentum)
        components["momentum"] = momentum
        reasons.append(f"M5 Momentum: {'YES' if momentum >= w.momentum else 'PARTIAL' if momentum > 0 else 'NO'}")

        # --- RSI (entry timeframe) ---
        rsi_val = float(rsi(data.entry_df["close"], cfg.rsi_period).iloc[-1])
        indicators["rsi"] = round(rsi_val, 2)
        rsi_ok = self._rsi_ok(rsi_val, side)
        components["rsi"] = w.rsi if rsi_ok else 0.0
        reasons.append(f"RSI: {rsi_val:.1f}")

        return _Eval(components=components, indicators=indicators, reasons=reasons)

    def _structure_ok(self, df: pd.DataFrame, side: OrderSide) -> bool:
        """Higher-low (BUY) / lower-high (SELL) over the lookback window.

        Split the recent window in two halves; a bullish structure has its
        recent swing low above the older swing low (reverse for bearish).
        """
        n = self.config.structure_lookback
        window = df.iloc[-n:]
        half = len(window) // 2
        if half < 1:
            return False
        older, recent = window.iloc[:half], window.iloc[half:]
        if side is OrderSide.BUY:
            return float(recent["low"].min()) > float(older["low"].min())
        return float(recent["high"].max()) < float(older["high"].max())

    def _pullback_ok(
        self, df: pd.DataFrame, side: OrderSide, atr_value: float
    ) -> tuple[bool, float]:
        """Price pulled back to within ``pullback_atr_mult`` ATRs of EMA-fast and
        is now resuming in the trend direction."""
        cfg = self.config
        ema_fast = ema(df["close"], cfg.ema_fast)
        ema_now = float(ema_fast.iloc[-1])
        close_now = float(df["close"].iloc[-1])
        lookback = df.iloc[-max(3, cfg.structure_lookback // 2):]
        threshold = cfg.pullback_atr_mult * atr_value if atr_value > 0 else 0.0

        if side is OrderSide.BUY:
            # A recent low came near/below EMA-fast, and price is back above it.
            near = float((lookback["low"] - ema_fast.loc[lookback.index]).min())
            touched = near <= threshold
            resuming = close_now > ema_now
            dist = abs(close_now - ema_now) / atr_value if atr_value > 0 else 0.0
            return (touched and resuming), dist
        near = float((ema_fast.loc[lookback.index] - lookback["high"]).min())
        touched = near <= threshold
        resuming = close_now < ema_now
        dist = abs(close_now - ema_now) / atr_value if atr_value > 0 else 0.0
        return (touched and resuming), dist

    def _momentum_score(
        self, df: pd.DataFrame, side: OrderSide, max_points: float
    ) -> float:
        """Bullish/bearish candle + price vs short EMA on the entry timeframe.

        Each of the two conditions is worth half the momentum weight.
        """
        cfg = self.config
        ema_short = float(ema(df["close"], cfg.ema_short).iloc[-1])
        last_open = float(df["open"].iloc[-1])
        last_close = float(df["close"].iloc[-1])
        if side is OrderSide.BUY:
            candle = last_close > last_open
            above = last_close > ema_short
        else:
            candle = last_close < last_open
            above = last_close < ema_short
        return max_points * (0.5 * candle + 0.5 * above)

    def _rsi_ok(self, rsi_val: float, side: OrderSide) -> bool:
        cfg = self.config
        if side is OrderSide.BUY:
            return cfg.rsi_buy_threshold <= rsi_val < cfg.rsi_overbought
        return cfg.rsi_oversold < rsi_val <= cfg.rsi_sell_threshold

    # --- entry price / explanation ------------------------------------------
    def _entry_price(self, data: StrategyInput, side: OrderSide) -> float:
        if data.tick is not None:
            return data.tick.ask if side is OrderSide.BUY else data.tick.bid
        return float(data.entry_df["close"].iloc[-1])

    def _explain(
        self,
        trend: TrendState,
        ev: _Eval,
        score: float,
        min_score: float,
        *,
        actionable: bool,
        extra: Optional[str] = None,
    ) -> str:
        head = (
            f"{'TRADE' if actionable else 'WAIT'} — "
            f"Signal Score: {score:.0f}/100 (min {min_score})"
        )
        body = " | ".join(ev.reasons)
        tail = f" | {extra}" if extra else ""
        if not actionable and extra is None and score < min_score:
            tail = f" | below minimum score"
        return f"{head} :: {body}{tail}"


__all__ = ["TrendPullbackStrategy"]
