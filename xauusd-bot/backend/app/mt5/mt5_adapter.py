"""Real MetaTrader 5 adapter.

Wraps the Windows-only ``MetaTrader5`` package behind the :class:`MT5Adapter`
interface. The package is imported **lazily** (inside ``connect``) so that
importing this module never fails on a machine without MT5 installed — the rest
of the system, and the whole test suite, can run against the mock adapter.

Every terminal operation is logged. Phase 1 implements read-only operations
(connection, account, symbols, market data, positions). Order execution is added
in Phase 3.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, List, Optional

from app.core.logging import get_logger, log_event
from app.core.models import (
    AccountInfo,
    Candle,
    ConnectionStatus,
    OrderSide,
    Position,
    SymbolInfo,
    Tick,
    Timeframe,
)
from app.mt5.base import MT5Adapter, MT5AdapterError

log = get_logger("mt5.adapter")


class MT5Adapter5(MT5Adapter):
    """Concrete adapter for a locally installed MetaTrader 5 terminal."""

    def __init__(
        self,
        login: Optional[int] = None,
        password: Optional[str] = None,
        server: Optional[str] = None,
        terminal_path: Optional[str] = None,
    ) -> None:
        self._login = login
        self._password = password
        self._server = server
        self._terminal_path = terminal_path
        self._mt5: Any = None  # the imported MetaTrader5 module
        self._connected = False

    # --- Lazy import ---------------------------------------------------------
    def _load_mt5(self) -> Any:
        if self._mt5 is not None:
            return self._mt5
        try:
            import MetaTrader5 as mt5  # type: ignore
        except ImportError as exc:  # pragma: no cover - platform dependent
            raise MT5AdapterError(
                "The 'MetaTrader5' package is not installed. It is required for "
                "DEMO/LIVE modes and is only available on Windows. Use PAPER/"
                "BACKTEST mode (mock adapter) elsewhere."
            ) from exc
        self._mt5 = mt5
        return mt5

    # --- Timeframe mapping ---------------------------------------------------
    def _tf(self, timeframe: Timeframe) -> Any:
        mt5 = self._load_mt5()
        mapping = {
            Timeframe.M1: mt5.TIMEFRAME_M1,
            Timeframe.M5: mt5.TIMEFRAME_M5,
            Timeframe.M15: mt5.TIMEFRAME_M15,
            Timeframe.M30: mt5.TIMEFRAME_M30,
            Timeframe.H1: mt5.TIMEFRAME_H1,
            Timeframe.H4: mt5.TIMEFRAME_H4,
            Timeframe.D1: mt5.TIMEFRAME_D1,
        }
        return mapping[timeframe]

    # --- Connection ----------------------------------------------------------
    def connect(self) -> ConnectionStatus:
        mt5 = self._load_mt5()
        init_kwargs: dict[str, Any] = {}
        if self._terminal_path:
            init_kwargs["path"] = self._terminal_path
        if self._login:
            init_kwargs["login"] = self._login
        if self._password:
            init_kwargs["password"] = self._password
        if self._server:
            init_kwargs["server"] = self._server

        ok = mt5.initialize(**init_kwargs)
        if not ok:
            code, desc = mt5.last_error()
            self._connected = False
            log_event(
                log,
                "MT5_CONNECT_FAILED",
                "terminal initialize() failed",
                level=40,
                error_code=code,
                error=desc,
            )
            return ConnectionStatus(
                connected=False, message=f"initialize failed: {code} {desc}"
            )

        self._connected = True
        account = self.get_account_info()
        log_event(
            log,
            "MT5_CONNECTED",
            "connected to terminal",
            server=account.server,
            login=account.login,
        )
        return ConnectionStatus(connected=True, message="connected", account=account)

    def disconnect(self) -> None:
        if self._mt5 is not None and self._connected:
            self._mt5.shutdown()
            log_event(log, "MT5_DISCONNECTED", "terminal shut down")
        self._connected = False

    def is_connected(self) -> bool:
        if not self._connected or self._mt5 is None:
            return False
        return self._mt5.terminal_info() is not None

    # --- Account -------------------------------------------------------------
    def get_account_info(self) -> AccountInfo:
        mt5 = self._load_mt5()
        info = mt5.account_info()
        if info is None:
            raise MT5AdapterError("account_info() returned None (not connected?)")
        return AccountInfo(
            login=info.login,
            server=info.server,
            currency=info.currency,
            balance=info.balance,
            equity=info.equity,
            margin=info.margin,
            margin_free=info.margin_free,
            leverage=info.leverage,
            name=info.name,
        )

    # --- Symbols -------------------------------------------------------------
    def list_symbols(self) -> List[str]:
        mt5 = self._load_mt5()
        symbols = mt5.symbols_get()
        return [s.name for s in symbols] if symbols else []

    def get_symbol_info(self, symbol: str) -> Optional[SymbolInfo]:
        mt5 = self._load_mt5()
        # Ensure the symbol is selected in Market Watch before querying.
        if not mt5.symbol_select(symbol, True):
            return None
        info = mt5.symbol_info(symbol)
        if info is None:
            return None
        return SymbolInfo(
            name=info.name,
            digits=info.digits,
            point=info.point,
            tick_size=info.trade_tick_size or info.point,
            tick_value=info.trade_tick_value,
            volume_min=info.volume_min,
            volume_max=info.volume_max,
            volume_step=info.volume_step,
            contract_size=info.trade_contract_size,
            currency_profit=info.currency_profit,
        )

    # --- Market data ---------------------------------------------------------
    def get_tick(self, symbol: str) -> Optional[Tick]:
        mt5 = self._load_mt5()
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return None
        return Tick(
            symbol=symbol,
            time=datetime.fromtimestamp(tick.time, tz=timezone.utc),
            bid=tick.bid,
            ask=tick.ask,
        )

    def get_candles(
        self,
        symbol: str,
        timeframe: Timeframe,
        count: int,
    ) -> List[Candle]:
        mt5 = self._load_mt5()
        # Skip index 0 (the still-forming candle) to avoid look-ahead: request
        # `count` completed bars starting at position 1.
        rates = mt5.copy_rates_from_pos(symbol, self._tf(timeframe), 1, count)
        if rates is None or len(rates) == 0:
            code, desc = mt5.last_error()
            raise MT5AdapterError(
                f"copy_rates_from_pos failed for {symbol} {timeframe.value}: "
                f"{code} {desc}"
            )
        candles: List[Candle] = []
        for r in rates:
            candles.append(
                Candle(
                    time=datetime.fromtimestamp(int(r["time"]), tz=timezone.utc),
                    open=float(r["open"]),
                    high=float(r["high"]),
                    low=float(r["low"]),
                    close=float(r["close"]),
                    tick_volume=int(r["tick_volume"]),
                    spread=int(r["spread"]),
                    real_volume=int(r["real_volume"]),
                )
            )
        return candles

    # --- Positions -----------------------------------------------------------
    def get_positions(self, symbol: Optional[str] = None) -> List[Position]:
        mt5 = self._load_mt5()
        raw = mt5.positions_get(symbol=symbol) if symbol else mt5.positions_get()
        if raw is None:
            return []
        positions: List[Position] = []
        for p in raw:
            side = OrderSide.BUY if p.type == mt5.POSITION_TYPE_BUY else OrderSide.SELL
            positions.append(
                Position(
                    ticket=p.ticket,
                    symbol=p.symbol,
                    side=side,
                    volume=p.volume,
                    price_open=p.price_open,
                    sl=p.sl,
                    tp=p.tp,
                    price_current=p.price_current,
                    profit=p.profit,
                    time=datetime.fromtimestamp(p.time, tz=timezone.utc),
                    comment=p.comment,
                    magic=p.magic,
                )
            )
        return positions


__all__ = ["MT5Adapter5"]
