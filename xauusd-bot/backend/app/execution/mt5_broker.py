"""Real MetaTrader 5 broker (DEMO/LIVE).

Wraps an already-connected :class:`MT5Adapter5` and issues real order_send calls
through the terminal. Uses the adapter's lazily-imported ``MetaTrader5`` module
(native on Windows, or the mt5linux bridge on Ubuntu), so importing this module
never requires the package.

⚠️ Not exercised by the test suite (needs a live terminal). Kept deliberately
thin; the engine's safety logic lives above it.
"""

from __future__ import annotations

from typing import Any, List, Optional

from app.core.logging import get_logger, log_event
from app.core.models import AccountInfo, OrderSide, Position
from app.execution.broker import Broker, OrderRequest, OrderResult
from app.mt5.mt5_adapter import MT5Adapter5

log = get_logger("execution.mt5")


class MT5Broker(Broker):  # pragma: no cover - requires a live terminal
    def __init__(self, adapter: MT5Adapter5, *, magic: int = 770001,
                 deviation: int = 20) -> None:
        self._adapter = adapter
        self._magic = magic
        self._deviation = deviation

    def _mt5(self) -> Any:
        return self._adapter._load_mt5()

    def submit_order(self, request: OrderRequest) -> OrderResult:
        mt5 = self._mt5()
        # Idempotency: never open a second position for the same signal.
        for pos in self.get_positions(request.symbol):
            if pos.comment == request.signal_id:
                return OrderResult(
                    success=True, signal_id=request.signal_id, ticket=pos.ticket,
                    duplicate=True, message="duplicate signal_id — no new order",
                )
        tick = mt5.symbol_info_tick(request.symbol)
        if tick is None:
            return OrderResult(False, request.signal_id, message="no tick")
        if request.side is OrderSide.BUY:
            order_type, price = mt5.ORDER_TYPE_BUY, tick.ask
        else:
            order_type, price = mt5.ORDER_TYPE_SELL, tick.bid
        mt5_request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": request.symbol,
            "volume": float(request.volume),
            "type": order_type,
            "price": price,
            "sl": float(request.stop_loss),
            "tp": float(request.take_profit),
            "deviation": self._deviation,
            "magic": self._magic,
            "comment": request.signal_id,  # carry the idempotency key
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        res = mt5.order_send(mt5_request)
        if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
            code = getattr(res, "retcode", None)
            log_event(log, "ORDER_FAILED", "order_send rejected", level=40,
                      signal_id=request.signal_id, retcode=code)
            return OrderResult(False, request.signal_id,
                               message=f"order_send retcode={code}")
        log_event(log, "ORDER_FILLED", "live order filled",
                  signal_id=request.signal_id, ticket=res.order, volume=res.volume)
        return OrderResult(
            success=True, signal_id=request.signal_id, ticket=res.order,
            fill_price=res.price, volume=res.volume, side=request.side,
            message="filled",
        )

    def modify_position(self, ticket: int, *, stop_loss: Optional[float] = None,
                        take_profit: Optional[float] = None) -> bool:
        mt5 = self._mt5()
        pos = self._find(ticket)
        if pos is None:
            return False
        req = {
            "action": mt5.TRADE_ACTION_SLTP,
            "symbol": pos.symbol,
            "position": ticket,
            "sl": float(stop_loss if stop_loss is not None else pos.sl),
            "tp": float(take_profit if take_profit is not None else pos.tp),
        }
        res = mt5.order_send(req)
        return res is not None and res.retcode == mt5.TRADE_RETCODE_DONE

    def close_position(self, ticket: int) -> OrderResult:
        mt5 = self._mt5()
        pos = self._find(ticket)
        if pos is None:
            return OrderResult(False, "", ticket=ticket, message="unknown ticket")
        tick = mt5.symbol_info_tick(pos.symbol)
        if pos.side is OrderSide.BUY:
            order_type, price = mt5.ORDER_TYPE_SELL, tick.bid
        else:
            order_type, price = mt5.ORDER_TYPE_BUY, tick.ask
        req = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": pos.symbol,
            "volume": pos.volume,
            "type": order_type,
            "position": ticket,
            "price": price,
            "deviation": self._deviation,
            "magic": self._magic,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        res = mt5.order_send(req)
        ok = res is not None and res.retcode == mt5.TRADE_RETCODE_DONE
        return OrderResult(ok, pos.comment, ticket=ticket, profit=pos.profit,
                           side=pos.side, message="closed" if ok else "close failed")

    def get_positions(self, symbol: Optional[str] = None) -> List[Position]:
        return self._adapter.get_positions(symbol)

    def get_account(self) -> AccountInfo:
        return self._adapter.get_account_info()

    def _find(self, ticket: int) -> Optional[Position]:
        for pos in self._adapter.get_positions():
            if pos.ticket == ticket:
                return pos
        return None


__all__ = ["MT5Broker"]
