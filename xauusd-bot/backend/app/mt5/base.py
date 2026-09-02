"""Abstract MT5 adapter interface.

The rest of the application depends ONLY on this interface, never on the
``MetaTrader5`` package directly. That isolation is what lets us:

* run and test everything on non-Windows machines via :class:`MockMT5Adapter`;
* swap the real terminal in for DEMO/LIVE without touching strategy/risk code.

Phase 1 covers connection, account, symbol detection and market data. Order
methods are declared here so the contract is complete, but their concrete
implementations land in Phase 3 (execution).
"""

from __future__ import annotations

import abc
from typing import List, Optional

from app.core.models import (
    AccountInfo,
    Candle,
    ConnectionStatus,
    Position,
    SymbolInfo,
    Tick,
    Timeframe,
)


class MT5AdapterError(Exception):
    """Raised for adapter-level failures (connection, symbol, data)."""


class MT5Adapter(abc.ABC):
    """Contract every MT5 backend (real or mock) must satisfy."""

    # --- Connection ----------------------------------------------------------
    @abc.abstractmethod
    def connect(self) -> ConnectionStatus:
        """Establish a connection to the terminal. Idempotent."""

    @abc.abstractmethod
    def disconnect(self) -> None:
        """Tear down the connection."""

    @abc.abstractmethod
    def is_connected(self) -> bool:
        """Return True if the terminal connection is currently healthy."""

    # --- Account -------------------------------------------------------------
    @abc.abstractmethod
    def get_account_info(self) -> AccountInfo:
        """Return current account balance/equity/margin."""

    # --- Symbols -------------------------------------------------------------
    @abc.abstractmethod
    def list_symbols(self) -> List[str]:
        """Return all symbol names available in the terminal."""

    @abc.abstractmethod
    def get_symbol_info(self, symbol: str) -> Optional[SymbolInfo]:
        """Return static/dynamic properties of a symbol, or None if unknown."""

    def resolve_symbol(self, candidates: List[str]) -> Optional[str]:
        """Return the first candidate symbol that exists in the terminal.

        Used to auto-detect broker-specific XAUUSD naming (XAUUSD, XAUUSDm,
        XAUUSD.a, GOLD, ...). Falls back to a case-insensitive match.
        """
        available = self.list_symbols()
        available_set = set(available)
        for name in candidates:
            if name in available_set:
                return name
        lowered = {s.lower(): s for s in available}
        for name in candidates:
            hit = lowered.get(name.lower())
            if hit:
                return hit
        return None

    # --- Market data ---------------------------------------------------------
    @abc.abstractmethod
    def get_tick(self, symbol: str) -> Optional[Tick]:
        """Return the latest tick (bid/ask) for a symbol."""

    @abc.abstractmethod
    def get_candles(
        self,
        symbol: str,
        timeframe: Timeframe,
        count: int,
    ) -> List[Candle]:
        """Return the most recent ``count`` COMPLETED candles, oldest first."""

    # --- Positions -----------------------------------------------------------
    @abc.abstractmethod
    def get_positions(self, symbol: Optional[str] = None) -> List[Position]:
        """Return currently open positions, optionally filtered by symbol."""


__all__ = ["MT5Adapter", "MT5AdapterError"]
