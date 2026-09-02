"""PaperBroker — a fully simulated broker for PAPER mode.

Fills market orders at the current tick (with optional slippage and commission),
tracks open positions, marks them to market, and closes them when price hits SL
or TP. It is the source of truth for the *simulated* account in PAPER mode.

Simulation assumptions are explicit and conservative; this is NOT a claim of
real fills. Slippage/commission are configurable so paper results don't flatter
the strategy.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional

from app.core.logging import get_logger, log_event
from app.core.models import AccountInfo, OrderSide, Position, SymbolInfo, Tick
from app.execution.broker import Broker, OrderRequest, OrderResult

log = get_logger("execution.paper")


@dataclass
class _PaperPosition:
    ticket: int
    signal_id: str
    symbol: str
    side: OrderSide
    volume: float
    entry: float
    sl: float
    tp: float
    open_time: datetime
    price_current: float
    commission: float


class PaperBroker(Broker):
    def __init__(
        self,
        symbol_info: SymbolInfo,
        *,
        starting_balance: float = 10_000.0,
        commission_per_lot: float = 0.0,
        slippage_points: float = 0.0,
        magic: int = 770001,
    ) -> None:
        self._info = symbol_info
        self._balance = starting_balance
        self._commission_per_lot = commission_per_lot
        self._slippage_points = slippage_points
        self._magic = magic
        self._positions: Dict[int, _PaperPosition] = {}
        self._signal_index: Dict[str, int] = {}
        self._last_tick: Optional[Tick] = None
        self._ticket_seq = 1

    # --- pricing / marking ---------------------------------------------------
    def mark_to_market(self, tick: Tick) -> List[OrderResult]:
        """Update open positions to the tick; auto-close on SL/TP.

        Returns the results of any positions closed by this price move.
        """
        self._last_tick = tick
        closes: List[OrderResult] = []
        for ticket in list(self._positions):
            pos = self._positions[ticket]
            # Exit price is the price you could close at now.
            exit_price = tick.bid if pos.side is OrderSide.BUY else tick.ask
            pos.price_current = exit_price
            hit = self._sl_tp_hit(pos, exit_price)
            if hit is not None:
                level, kind = hit
                closes.append(self._close(pos, level, reason=kind))
        return closes

    def _sl_tp_hit(
        self, pos: _PaperPosition, exit_price: float
    ) -> Optional[tuple[float, str]]:
        if pos.side is OrderSide.BUY:
            if exit_price <= pos.sl:
                return pos.sl, "SL"
            if exit_price >= pos.tp:
                return pos.tp, "TP"
        else:
            if exit_price >= pos.sl:
                return pos.sl, "SL"
            if exit_price <= pos.tp:
                return pos.tp, "TP"
        return None

    # --- orders --------------------------------------------------------------
    def submit_order(self, request: OrderRequest) -> OrderResult:
        # Idempotency: never open a second position for the same signal.
        if request.signal_id in self._signal_index:
            existing = self._signal_index[request.signal_id]
            log_event(
                log, "ORDER_DUPLICATE_BLOCKED",
                "idempotency prevented duplicate order",
                level=30, signal_id=request.signal_id, ticket=existing,
            )
            return OrderResult(
                success=True, signal_id=request.signal_id, ticket=existing,
                duplicate=True, message="duplicate signal_id — no new order",
            )

        base = request.price
        if base is None:
            if self._last_tick is None:
                return OrderResult(
                    success=False, signal_id=request.signal_id,
                    message="no price available (no tick marked yet)",
                )
            base = (
                self._last_tick.ask if request.side is OrderSide.BUY
                else self._last_tick.bid
            )
        fill = self._apply_slippage(base, request.side)
        commission = self._commission_per_lot * request.volume
        self._balance -= commission

        ticket = self._ticket_seq
        self._ticket_seq += 1
        now = self._last_tick.time if self._last_tick else datetime.now(timezone.utc)
        pos = _PaperPosition(
            ticket=ticket, signal_id=request.signal_id, symbol=request.symbol,
            side=request.side, volume=request.volume, entry=fill,
            sl=request.stop_loss, tp=request.take_profit, open_time=now,
            price_current=fill, commission=commission,
        )
        self._positions[ticket] = pos
        self._signal_index[request.signal_id] = ticket
        log_event(
            log, "ORDER_FILLED", "paper order filled",
            signal_id=request.signal_id, ticket=ticket, side=request.side.value,
            volume=request.volume, fill=round(fill, self._info.digits),
        )
        return OrderResult(
            success=True, signal_id=request.signal_id, ticket=ticket,
            fill_price=round(fill, self._info.digits), volume=request.volume,
            side=request.side, message="filled",
        )

    def modify_position(
        self, ticket: int, *, stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
    ) -> bool:
        pos = self._positions.get(ticket)
        if pos is None:
            return False
        if stop_loss is not None:
            pos.sl = round(stop_loss, self._info.digits)
        if take_profit is not None:
            pos.tp = round(take_profit, self._info.digits)
        return True

    def close_position(self, ticket: int) -> OrderResult:
        pos = self._positions.get(ticket)
        if pos is None:
            return OrderResult(success=False, signal_id="", ticket=ticket,
                               message="unknown ticket")
        exit_price = pos.price_current
        return self._close(pos, exit_price, reason="MANUAL")

    def _close(self, pos: _PaperPosition, exit_price: float, *, reason: str) -> OrderResult:
        profit = self._pnl(pos, exit_price)
        self._balance += profit
        del self._positions[pos.ticket]
        log_event(
            log, "POSITION_CLOSED", f"paper position closed ({reason})",
            signal_id=pos.signal_id, ticket=pos.ticket,
            exit=round(exit_price, self._info.digits), profit=round(profit, 2),
        )
        return OrderResult(
            success=True, signal_id=pos.signal_id, ticket=pos.ticket,
            fill_price=round(exit_price, self._info.digits), volume=pos.volume,
            side=pos.side, profit=round(profit, 2), message=f"closed:{reason}",
        )

    # --- accounting ----------------------------------------------------------
    def _apply_slippage(self, price: float, side: OrderSide) -> float:
        slip = self._slippage_points * self._info.point
        # Slippage always works against the trader.
        return price + slip if side is OrderSide.BUY else price - slip

    def _pnl(self, pos: _PaperPosition, exit_price: float) -> float:
        diff = (exit_price - pos.entry) if pos.side is OrderSide.BUY else (
            pos.entry - exit_price
        )
        ticks = diff / self._info.tick_size
        return ticks * self._info.tick_value * pos.volume

    def _unrealized(self) -> float:
        return sum(self._pnl(p, p.price_current) for p in self._positions.values())

    def get_positions(self, symbol: Optional[str] = None) -> List[Position]:
        out: List[Position] = []
        for pos in self._positions.values():
            if symbol and pos.symbol != symbol:
                continue
            out.append(
                Position(
                    ticket=pos.ticket, symbol=pos.symbol, side=pos.side,
                    volume=pos.volume, price_open=pos.entry, sl=pos.sl, tp=pos.tp,
                    price_current=pos.price_current,
                    profit=round(self._pnl(pos, pos.price_current), 2),
                    time=pos.open_time, comment=pos.signal_id, magic=self._magic,
                )
            )
        return out

    def get_account(self) -> AccountInfo:
        equity = self._balance + self._unrealized()
        return AccountInfo(
            login=0, server="PaperBroker", currency=self._info.currency_profit,
            balance=round(self._balance, 2), equity=round(equity, 2),
            margin=0.0, margin_free=round(equity, 2), leverage=100,
            name="Paper Account (SIMULATED)",
        )


__all__ = ["PaperBroker"]
