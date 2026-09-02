"""Historical backtesting engine.

Replays the entry timeframe bar by bar. At each completed entry bar it rebuilds
the higher-timeframe (setup/trend) views using **only candles that had already
closed** at that moment — so the strategy never sees future data (spec §§18,37).

Costs, daily-loss limits, cooldown and trading sessions are all honored, so a
backtest mirrors what the live engine would have done.
"""

from __future__ import annotations

import bisect
from datetime import timedelta
from typing import Dict, List, Optional

from app.core.config import BotConfig
from app.core.models import Candle, SymbolInfo, Timeframe
from app.core.state import BotState
from app.indicators.indicators import atr as atr_ind, candles_to_frame
from app.risk.governor import RiskGovernor
from app.risk.position_sizing import calculate_position_size
from app.risk.sessions import SessionFilter
from app.strategies.base import Strategy, StrategyInput
from app.backtesting.models import BacktestResult, BacktestTrade
from app.backtesting.simulator import BarSimulator


class Backtester:
    def __init__(
        self,
        config: BotConfig,
        strategy: Strategy,
        symbol_info: SymbolInfo,
        candles: Dict[Timeframe, List[Candle]],
        *,
        starting_balance: float = 10_000.0,
        commission_per_lot: float = 0.0,
        slippage_points: float = 0.0,
    ) -> None:
        self.config = config
        self.strategy = strategy
        self.info = symbol_info
        self.candles = candles
        self.starting_balance = starting_balance
        self._commission = commission_per_lot
        self._slippage = slippage_points

        self.trend_tf = Timeframe(config.timeframes.trend)
        self.setup_tf = Timeframe(config.timeframes.setup)
        self.entry_tf = Timeframe(config.timeframes.entry)

    def run(self) -> BacktestResult:
        entry = self.candles[self.entry_tf]
        setup = self.candles[self.setup_tf]
        trend = self.candles[self.trend_tf]

        # Completion times for higher-tf slicing (open time + one bar duration).
        setup_done = [c.time + timedelta(minutes=self.setup_tf.minutes) for c in setup]
        trend_done = [c.time + timedelta(minutes=self.trend_tf.minutes) for c in trend]

        balance = self.starting_balance
        state = BotState()
        governor = RiskGovernor(
            self.config.risk, state,
            session_filter=SessionFilter(self.config.trading_sessions),
        )
        sim = BarSimulator(
            self.info, self.config.break_even, self.config.trailing_stop,
            commission_per_lot=self._commission, slippage_points=self._slippage,
        )

        result = BacktestResult(
            symbol=self.info.name, strategy=self.strategy.name,
            strategy_version=self.strategy.version,
            starting_balance=self.starting_balance, ending_balance=balance,
        )

        # Warm-up so every indicator has a full window on all timeframes.
        warmup = max(self.config.strategy.ema_slow, self.config.strategy.atr_period) + 5

        for i in range(warmup, len(entry)):
            bar = entry[i]
            decision_time = bar.time + timedelta(minutes=self.entry_tf.minutes)

            # Higher-tf ATR (for stop management) from completed setup candles.
            setup_slice = setup[: bisect.bisect_right(setup_done, decision_time)]
            atr_value = self._atr(setup_slice)

            # 1) Manage/close an open position on this bar.
            if sim.has_position:
                trade = sim.on_bar(bar, atr_value)
                if trade is not None:
                    balance += trade.profit
                    governor.register_trade_closed(trade.profit, bar.time)
                    result.trades.append(trade)

            # 2) Sample equity at this bar's close.
            equity = balance + sim.unrealized(bar.close)
            result.equity_curve.append((bar.time, round(equity, 2)))

            # 3) Look for a new entry when flat.
            if not sim.has_position:
                gate = governor.can_open_new_trade(decision_time, equity)
                if gate.allowed:
                    trend_slice = trend[
                        : bisect.bisect_right(trend_done, decision_time)
                    ]
                    signal = self.strategy.evaluate(
                        StrategyInput(
                            symbol_info=self.info,
                            trend_df=candles_to_frame(trend_slice),
                            setup_df=candles_to_frame(setup_slice),
                            entry_df=candles_to_frame(entry[: i + 1]),
                            tick=None, spread_points=None, now=decision_time,
                        )
                    )
                    if signal.is_actionable and signal.stop_loss is not None:
                        sizing = calculate_position_size(
                            equity, self.config.risk.risk_per_trade,
                            signal.entry, signal.stop_loss, self.info,
                        )
                        if sizing.ok:
                            sim.open_position(signal, sizing.lots, bar)
                            governor.register_trade_opened()

            result.bars_processed += 1

        # Close any residual position at the last bar.
        if sim.has_position and entry:
            trade = sim.force_close(entry[-1])
            if trade is not None:
                balance += trade.profit
                result.trades.append(trade)

        result.ending_balance = round(balance, 2)
        return result

    def _atr(self, setup_slice: List[Candle]) -> float:
        if len(setup_slice) <= self.config.stop_loss.atr_period:
            return 0.0
        frame = candles_to_frame(setup_slice)
        series = atr_ind(
            frame["high"], frame["low"], frame["close"],
            self.config.stop_loss.atr_period,
        )
        val = series.iloc[-1]
        return float(val) if val == val else 0.0  # guard NaN


__all__ = ["Backtester"]
