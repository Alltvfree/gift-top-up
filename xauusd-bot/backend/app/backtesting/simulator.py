"""Bar-based fill simulator for backtesting.

Models a single open position with realistic **intrabar** stop/target fills
using each bar's high/low, plus break-even and ATR trailing management. Costs
(commission, slippage) are configurable so results aren't flattered.

Conservative assumptions (documented so results are reproducible, spec §37):
* Entry fills at the signal bar's **close** (the price known when the decision is
  made — no look-ahead), adjusted for slippage.
* If a bar's range touches BOTH stop and target, the **stop is assumed hit
  first** (worst case).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from app.core.config import BreakEvenConfig, TrailingStopConfig
from app.core.models import Candle, OrderSide, Signal, SymbolInfo
from app.execution.position_manager import manage_stop
from app.backtesting.models import BacktestTrade


class _OpenPosition:
    def __init__(self, signal: Signal, volume: float, entry: float,
                 open_time: datetime) -> None:
        self.signal_id = signal.signal_id
        self.side = signal.direction.to_side()
        self.entry = entry
        self.sl = signal.stop_loss
        self.tp = signal.take_profit
        self.initial_sl = signal.stop_loss
        self.volume = volume
        self.open_time = open_time
        self.bars_held = 0


class BarSimulator:
    def __init__(
        self,
        symbol_info: SymbolInfo,
        break_even: BreakEvenConfig,
        trailing: TrailingStopConfig,
        *,
        commission_per_lot: float = 0.0,
        slippage_points: float = 0.0,
    ) -> None:
        self._info = symbol_info
        self._be = break_even
        self._trail = trailing
        self._commission_per_lot = commission_per_lot
        self._slippage_points = slippage_points
        self._pos: Optional[_OpenPosition] = None
        self.commission_paid = 0.0

    @property
    def has_position(self) -> bool:
        return self._pos is not None

    def unrealized(self, price: float) -> float:
        if self._pos is None:
            return 0.0
        return self._pnl(self._pos, price)

    # --- lifecycle -----------------------------------------------------------
    def open_position(self, signal: Signal, volume: float, bar: Candle) -> None:
        slip = self._slippage_points * self._info.point
        fill = bar.close + slip if signal.direction.to_side() is OrderSide.BUY \
            else bar.close - slip
        fill = round(fill, self._info.digits)
        self._pos = _OpenPosition(signal, volume, fill, bar.time)
        self.commission_paid += self._commission_per_lot * volume

    def on_bar(self, bar: Candle, atr_value: float) -> Optional[BacktestTrade]:
        """Advance one bar; manage the stop and check for an intrabar exit."""
        if self._pos is None:
            return None
        pos = self._pos
        pos.bars_held += 1

        # 1) Break-even / trailing using this bar's close as current price.
        update = manage_stop(
            pos.side, pos.entry, pos.initial_sl, bar.close, pos.sl,
            atr_value, self._info, self._be, self._trail,
        )
        if update is not None:
            pos.sl = update.new_sl

        # 2) Intrabar SL/TP (stop assumed first if both are touched).
        if pos.side is OrderSide.BUY:
            if bar.low <= pos.sl:
                return self._close(bar.time, pos.sl, self._stop_reason(pos))
            if bar.high >= pos.tp:
                return self._close(bar.time, pos.tp, "TP")
        else:
            if bar.high >= pos.sl:
                return self._close(bar.time, pos.sl, self._stop_reason(pos))
            if bar.low <= pos.tp:
                return self._close(bar.time, pos.tp, "TP")
        return None

    def force_close(self, bar: Candle) -> Optional[BacktestTrade]:
        if self._pos is None:
            return None
        return self._close(bar.time, bar.close, "EOD")

    # --- internals -----------------------------------------------------------
    def _stop_reason(self, pos: _OpenPosition) -> str:
        # If the stop has advanced past entry it's a protected exit.
        if pos.side is OrderSide.BUY and pos.sl > pos.initial_sl:
            return "TRAIL/BE"
        if pos.side is OrderSide.SELL and pos.sl < pos.initial_sl:
            return "TRAIL/BE"
        return "SL"

    def _close(self, exit_time: datetime, exit_price: float, reason: str) -> BacktestTrade:
        pos = self._pos
        assert pos is not None
        commission = self._commission_per_lot * pos.volume
        profit = self._pnl(pos, exit_price) - commission
        self.commission_paid += commission
        risk_price = abs(pos.entry - pos.initial_sl)
        move = (exit_price - pos.entry) if pos.side is OrderSide.BUY else (
            pos.entry - exit_price
        )
        r_multiple = (move / risk_price) if risk_price > 0 else 0.0
        trade = BacktestTrade(
            signal_id=pos.signal_id, side=pos.side, entry_time=pos.open_time,
            exit_time=exit_time, entry=pos.entry,
            exit=round(exit_price, self._info.digits), volume=pos.volume,
            initial_sl=pos.initial_sl, take_profit=pos.tp,
            profit=round(profit, 2), r_multiple=round(r_multiple, 3),
            close_reason=reason, bars_held=pos.bars_held,
        )
        self._pos = None
        return trade

    def _pnl(self, pos: _OpenPosition, exit_price: float) -> float:
        diff = (exit_price - pos.entry) if pos.side is OrderSide.BUY else (
            pos.entry - exit_price
        )
        ticks = diff / self._info.tick_size
        return ticks * self._info.tick_value * pos.volume


__all__ = ["BarSimulator"]
