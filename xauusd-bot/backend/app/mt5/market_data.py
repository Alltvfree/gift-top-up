"""Market-data service.

Sits on top of any :class:`MT5Adapter` and provides higher-level helpers the
strategy/backtester need: symbol resolution, indicator-ready DataFrames, spread
in broker points, and completed-candle access.
"""

from __future__ import annotations

from typing import List, Optional

import pandas as pd

from app.core.logging import get_logger, log_event
from app.core.models import Candle, SymbolInfo, Tick, Timeframe
from app.indicators.indicators import candles_to_frame
from app.mt5.base import MT5Adapter, MT5AdapterError

log = get_logger("mt5.market_data")


class MarketDataService:
    """Read-only market-data access with a resolved active symbol."""

    def __init__(self, adapter: MT5Adapter) -> None:
        self._adapter = adapter
        self._symbol: Optional[str] = None
        self._symbol_info: Optional[SymbolInfo] = None

    # --- Symbol resolution ---------------------------------------------------
    def resolve_symbol(self, candidates: List[str]) -> SymbolInfo:
        """Detect the broker's actual symbol name from a candidate list.

        Raises :class:`MT5AdapterError` when none of the candidates exist so the
        bot never silently trades the wrong instrument.
        """
        resolved = self._adapter.resolve_symbol(candidates)
        if resolved is None:
            raise MT5AdapterError(
                f"none of the candidate symbols are available: {candidates}"
            )
        info = self._adapter.get_symbol_info(resolved)
        if info is None:
            raise MT5AdapterError(f"symbol info unavailable for {resolved}")
        self._symbol = resolved
        self._symbol_info = info
        log_event(
            log,
            "SYMBOL_RESOLVED",
            f"using broker symbol {resolved}",
            requested=candidates[0] if candidates else None,
            resolved=resolved,
            digits=info.digits,
        )
        return info

    @property
    def symbol(self) -> str:
        self._require_symbol()
        assert self._symbol is not None
        return self._symbol

    @property
    def symbol_info(self) -> SymbolInfo:
        self._require_symbol()
        assert self._symbol_info is not None
        return self._symbol_info

    def _require_symbol(self) -> None:
        if self._symbol is None or self._symbol_info is None:
            raise MT5AdapterError(
                "no active symbol — call resolve_symbol() first"
            )

    # --- Market data ---------------------------------------------------------
    def get_candles(self, timeframe: Timeframe, count: int) -> List[Candle]:
        """Completed candles for the active symbol, oldest first."""
        return self._adapter.get_candles(self.symbol, timeframe, count)

    def get_ohlc_frame(self, timeframe: Timeframe, count: int) -> pd.DataFrame:
        """Indicator-ready OHLCV DataFrame indexed by candle open time."""
        return candles_to_frame(self.get_candles(timeframe, count))

    def get_tick(self) -> Optional[Tick]:
        return self._adapter.get_tick(self.symbol)

    def get_spread_points(self) -> Optional[float]:
        """Current spread in broker points, or None if no tick is available."""
        tick = self.get_tick()
        if tick is None:
            return None
        return tick.spread_points(self.symbol_info)


__all__ = ["MarketDataService"]
