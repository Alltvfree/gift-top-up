"""Persistent bot state.

Holds the stateful information the trading engine needs to survive a restart:
the emergency-stop flag, daily-risk counters, candle-dedup markers, executed
signal ids (idempotency), and per-open-trade metadata (for break-even/trailing).

Persistence is a simple JSON file so it works anywhere (no DB required for
Phase 3). The full PostgreSQL trade/equity history is a later phase; this store
is the operational state the engine reads and writes each iteration.
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Dict, Optional


@dataclass
class TradeMeta:
    """What we remember about an open trade for management + accounting."""

    ticket: int
    signal_id: str
    side: str            # "BUY" / "SELL"
    entry: float
    initial_sl: float
    volume: float
    break_even_done: bool = False


@dataclass
class BotState:
    """Operational state persisted between iterations / restarts."""

    emergency_stop: bool = False

    # Daily-risk counters (reset on trading-day rollover).
    trading_day: Optional[str] = None          # ISO date
    day_start_equity: float = 0.0
    peak_equity: float = 0.0
    realized_pnl_today: float = 0.0
    trades_today: int = 0
    consecutive_losses: int = 0
    last_close_time: Optional[str] = None       # ISO datetime

    # Candle dedup: "SYMBOL|TF" -> ISO timestamp of last processed candle.
    processed_candles: Dict[str, str] = field(default_factory=dict)

    # Idempotency: signal_id -> ticket (order already executed).
    executed_signals: Dict[str, int] = field(default_factory=dict)

    # Per-open-trade metadata keyed by str(ticket).
    open_trades: Dict[str, dict] = field(default_factory=dict)

    # --- candle dedup helpers ------------------------------------------------
    def candle_key(self, symbol: str, timeframe: str) -> str:
        return f"{symbol}|{timeframe}"

    def is_candle_processed(self, symbol: str, timeframe: str, ts: datetime) -> bool:
        return self.processed_candles.get(self.candle_key(symbol, timeframe)) == \
            ts.isoformat()

    def mark_candle_processed(self, symbol: str, timeframe: str, ts: datetime) -> None:
        self.processed_candles[self.candle_key(symbol, timeframe)] = ts.isoformat()

    # --- trade meta helpers --------------------------------------------------
    def add_open_trade(self, meta: TradeMeta) -> None:
        self.open_trades[str(meta.ticket)] = asdict(meta)
        self.executed_signals[meta.signal_id] = meta.ticket

    def remove_open_trade(self, ticket: int) -> None:
        self.open_trades.pop(str(ticket), None)

    def get_open_trade(self, ticket: int) -> Optional[TradeMeta]:
        raw = self.open_trades.get(str(ticket))
        return TradeMeta(**raw) if raw else None


class StateStore:
    """Load/save :class:`BotState` as JSON. Atomic writes."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> BotState:
        if not self.path.exists():
            return BotState()
        with open(self.path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        return BotState(**raw)

    def save(self, state: BotState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic write: temp file + replace, so a crash never truncates state.
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            with open(fd, "w", encoding="utf-8") as fh:
                json.dump(asdict(state), fh, indent=2, default=str)
            Path(tmp).replace(self.path)
        finally:
            if Path(tmp).exists():
                Path(tmp).unlink()


class InMemoryStateStore(StateStore):
    """Non-persistent store for tests / ephemeral runs."""

    def __init__(self) -> None:  # noqa: D401 - intentionally no path
        self._state = BotState()

    def load(self) -> BotState:
        return self._state

    def save(self, state: BotState) -> None:
        self._state = state


def rollover_day(state: BotState, today: date, equity: float) -> bool:
    """Reset daily counters if the trading day changed. Returns True if reset."""
    iso = today.isoformat()
    if state.trading_day == iso:
        if equity > state.peak_equity:
            state.peak_equity = equity
        return False
    state.trading_day = iso
    state.day_start_equity = equity
    state.peak_equity = max(state.peak_equity, equity) if state.peak_equity else equity
    state.realized_pnl_today = 0.0
    state.trades_today = 0
    return True


__all__ = ["BotState", "TradeMeta", "StateStore", "InMemoryStateStore", "rollover_day"]
