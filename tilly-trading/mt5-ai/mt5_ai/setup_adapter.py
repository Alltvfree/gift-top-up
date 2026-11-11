"""Adapter to the rule-based trend+pullback setup already built and tested in
tilly-trading/kronos (setups/trend_pullback.py + setup_live.evaluate). That
code stays the single source of truth for the rules; this only calls it, so
what Claude reports is exactly what the backtest measured."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

from .broker import TIMEFRAME_MINUTES


class TrendPullbackAdapter:
    def __init__(self, kronos_dir: str, config_path: str | None = None):
        root = Path(kronos_dir)
        if not (root / "setups" / "trend_pullback.py").exists() or not (root / "setup_live.py").exists():
            raise FileNotFoundError(
                f"{kronos_dir!r} is not the tilly-trading/kronos folder (needs setups/trend_pullback.py and setup_live.py). "
                "Sync the rule-based setup update there first."
            )
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        import setup_live  # noqa: PLC0415 - from kronos_dir
        from setups.trend_pullback import load_setup_params  # noqa: PLC0415

        self._evaluate = setup_live.evaluate
        self.params = load_setup_params(config_path or str(root / "config" / "setup_xauusd.toml"))

    def status(self, base: pd.DataFrame, higher: pd.DataFrame, *, symbol: str, timeframe: str,
               higher_timeframe: str, now: pd.Timestamp, point: float) -> dict:
        p = self.params
        row = self._evaluate(base, higher, p, point, TIMEFRAME_MINUTES[timeframe.upper()],
                             TIMEFRAME_MINUTES[higher_timeframe.upper()], now)
        close = float(row["close"])
        signal = "BUY" if row["setup_buy"] else "SELL" if row["setup_sell"] else "NONE"
        bias = row.get(f"{p.higher_prefix}_structure_bias")
        out = {
            "symbol": symbol,
            "bar_time": pd.Timestamp(row["time"]).isoformat(),
            "signal": signal,
            "close": close,
            "higher_timeframe_structure": "up" if bias == 1 else "down" if bias == -1 else "neutral",
            "atr": round(float(row["atr_pct"]) * close, 4),
            "rules": (
                f"{higher_timeframe} trend (HH+HL / LH+LL and price vs EMA{p.ema_slow}) -> {timeframe} pullback tags EMA{p.ema_fast} "
                f"within {p.pullback_bars} bars -> strong confirmation candle; stop past the pullback extreme "
                f"({p.min_sl_atr:g}-{p.max_sl_atr:g} ATR), target {p.rr:g}R; trades {p.session_start_utc:02d}-{p.session_end_utc:02d} "
                "broker-server hours only."
            ),
            "note": "This is the setup's state on the last CLOSED bar. NONE is the normal answer most of the time.",
        }
        if signal != "NONE":
            sl_dist, tp_dist = float(row["signal_sl_distance"]), float(row["signal_tp_distance"])
            sign = 1 if signal == "BUY" else -1
            out.update(
                sl_distance=round(sl_dist, 5), tp_distance=round(tp_dist, 5), reward_risk=p.rr,
                sl_price_from_close=round(close - sign * sl_dist, 5), tp_price_from_close=round(close + sign * tp_dist, 5),
                backtest_warning="The setup has NOT been shown to have an edge unless a backtest with 500+ trades said so. Check that first.",
            )
        return out
