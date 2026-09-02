"""Strategy interface and inputs.

Strategies are modular and independent of the UI, database and execution layer.
A strategy is a pure function of its :class:`StrategyInput` — given the same
market data it returns the same :class:`Signal` — which keeps it reproducible and
fully testable (no look-ahead, no hidden state).
"""

from __future__ import annotations

import abc
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

from app.core.models import Signal, SignalType, SymbolInfo, Tick


@dataclass
class StrategyInput:
    """Everything a multi-timeframe strategy needs to evaluate one bar.

    The DataFrames contain only **completed** candles (oldest first), indexed by
    candle open time, with columns open/high/low/close/tick_volume.
    """

    symbol_info: SymbolInfo
    trend_df: pd.DataFrame      # higher timeframe (bias), e.g. H1
    setup_df: pd.DataFrame      # structure/setup timeframe, e.g. M15
    entry_df: pd.DataFrame      # entry-confirmation timeframe, e.g. M5
    tick: Optional[Tick] = None
    spread_points: Optional[float] = None
    now: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class Strategy(abc.ABC):
    """Base class for all trading strategies."""

    name: str = "base"
    version: str = "0.0.0"

    @abc.abstractmethod
    def evaluate(self, data: StrategyInput) -> Signal:
        """Return a fully-explained signal (BUY/SELL/WAIT) for the current bar."""

    # --- helpers -------------------------------------------------------------
    def _new_signal_id(self, symbol: str, bar_time: datetime, direction: str) -> str:
        """Deterministic-ish unique id.

        A UUID guarantees uniqueness for execution/idempotency; the symbol+bar
        prefix keeps it human-readable in logs. Duplicate-trade protection in
        Phase 3 keys off (symbol, timeframe, bar_time), not this id.
        """
        prefix = f"{symbol}-{bar_time:%Y%m%d%H%M}-{direction}"
        return f"{prefix}-{uuid.uuid4().hex[:8]}"

    def _wait(
        self,
        data: StrategyInput,
        score: float,
        reason: str,
        components: dict,
        indicators: dict,
    ) -> Signal:
        bar_time = _last_time(data.entry_df, data.now)
        return Signal(
            signal_id=self._new_signal_id(data.symbol_info.name, bar_time, "WAIT"),
            timestamp=data.now,
            symbol=data.symbol_info.name,
            direction=SignalType.WAIT,
            score=round(score, 2),
            strategy=self.name,
            strategy_version=self.version,
            reason=reason,
            components=components,
            indicators=indicators,
        )


def _last_time(df: pd.DataFrame, fallback: datetime) -> datetime:
    if df is not None and not df.empty:
        idx = df.index[-1]
        try:
            return idx.to_pydatetime()  # type: ignore[attr-defined]
        except AttributeError:
            return idx  # already a datetime
    return fallback


__all__ = ["Strategy", "StrategyInput"]
