"""MT5 historical data access for Kronos.

Windows-only, same reason as tilly-trading/mt5-bridge/bridge.py: the
official `MetaTrader5` Python package drives the terminal over local IPC,
not a network protocol, so this must run on the same Windows machine as a
logged-in MT5 terminal. Written and reviewed carefully but not executable
by Claude — no real MT5 terminal exists in this environment to test it
against. Everything downstream of this file (features.py, labels.py,
train.py's chronological split, publish_signal.py) takes plain pandas
DataFrames and has been tested against synthetic data instead.

Fixes the bug from the project notes: a single `copy_rates_from_pos` request
for 100,000 bars failed with "(-2, 'Terminal: Invalid params')" — MT5 has an
undocumented per-request bar cap that varies by broker/terminal, so instead
of guessing the exact limit, this chunks the download into
MAX_BARS_PER_REQUEST-sized windows and concatenates them.
"""
from __future__ import annotations

import pandas as pd

try:
    import MetaTrader5 as mt5
except ImportError as exc:  # pragma: no cover - Windows-only dependency
    raise SystemExit(
        "The MetaTrader5 package is Windows-only and must be installed where "
        "a real MT5 terminal runs. `pip install MetaTrader5` on that machine."
    ) from exc

TIMEFRAME_MAP = {
    "M1": mt5.TIMEFRAME_M1,
    "M5": mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "H1": mt5.TIMEFRAME_H1,
    "H4": mt5.TIMEFRAME_H4,
}

TIMEFRAME_MINUTES = {"M1": 1, "M5": 5, "M15": 15, "H1": 60, "H4": 240}


def bars_to_cover_same_span(
    base_timeframe: str, base_bars: int, target_timeframe: str, buffer: float = 1.1
) -> int:
    """How many `target_timeframe` bars are needed to cover the same
    historical wall-clock span as `base_bars` bars of `base_timeframe` —
    so a caller adding multi-timeframe context (see
    features.merge_higher_timeframe) doesn't have to do the minutes
    arithmetic by hand each time. `buffer` adds a small margin so the
    higher timeframe's earliest bar comfortably predates the base
    timeframe's earliest bar, not lands right at the edge of it.
    """
    base_minutes = TIMEFRAME_MINUTES.get(base_timeframe.upper())
    target_minutes = TIMEFRAME_MINUTES.get(target_timeframe.upper())
    if base_minutes is None or target_minutes is None:
        raise ValueError(f"Unknown timeframe in {base_timeframe!r}/{target_timeframe!r}")
    span_minutes = base_bars * base_minutes
    return int(span_minutes / target_minutes * buffer) + 10

# Conservative and well under any broker's documented or observed limit —
# chunking at this size sidesteps needing to know the exact undocumented
# cap for a given terminal/broker.
MAX_BARS_PER_REQUEST = 5000


def connect(
    login: str | int | None = None,
    password: str | None = None,
    server: str | None = None,
    path: str | None = None,
) -> None:
    """Attach to a running terminal, or log in if credentials are given —
    same optional-auto-login pattern as mt5-bridge/bridge.py."""
    kwargs: dict = {}
    if path:
        kwargs["path"] = path
    if login and password and server:
        kwargs.update(login=int(login), password=password, server=server)
    if not mt5.initialize(**kwargs):
        code, desc = mt5.last_error()
        raise RuntimeError(f"MetaTrader5.initialize() failed: [{code}] {desc}")


def disconnect() -> None:
    mt5.shutdown()


def server_time_now(symbol: str) -> pd.Timestamp:
    """The broker server's current time, from the symbol's latest tick, as a
    tz-aware UTC-labelled Timestamp — the SAME clock download_history stamps
    on bars (it labels the server's epoch seconds as UTC). Use this, not the
    PC clock, to decide whether a bar has closed (bars.closed_bars_only).
    Over a weekend the last tick is stale, which is correct: nothing new has
    closed either."""
    if not mt5.symbol_select(symbol, True):
        raise RuntimeError(f"Could not select {symbol} in Market Watch: {mt5.last_error()}")
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        raise RuntimeError(f"No tick available for {symbol}: {mt5.last_error()}")
    return pd.Timestamp(tick.time, unit="s", tz="UTC")


def download_history(symbol: str, timeframe: str, total_bars: int) -> pd.DataFrame:
    """Download the most recent `total_bars` closed bars for `symbol`,
    chunked to avoid the undocumented per-request cap. Walks backward from
    the most recent bar (`copy_rates_from_pos` position 0) in
    MAX_BARS_PER_REQUEST-sized windows, so a request for 50,000 bars
    becomes ~10 requests of 5,000 instead of one that may be rejected.

    Returns a DataFrame sorted oldest-first with columns
    [time, open, high, low, close, tick_volume, spread], `time` as
    tz-aware UTC — the shape features.py expects.
    """
    tf = TIMEFRAME_MAP.get(timeframe.upper())
    if tf is None:
        raise ValueError(f"Unknown timeframe {timeframe!r}; expected one of {sorted(TIMEFRAME_MAP)}")
    if total_bars <= 0:
        raise ValueError("total_bars must be positive.")

    chunks: list[pd.DataFrame] = []
    fetched = 0
    start_pos = 0
    while fetched < total_bars:
        n = min(MAX_BARS_PER_REQUEST, total_bars - fetched)
        rates = mt5.copy_rates_from_pos(symbol, tf, start_pos, n)
        if rates is None or len(rates) == 0:
            code, desc = mt5.last_error()
            if fetched == 0:
                raise RuntimeError(f"No data returned for {symbol}: ({code}, {desc!r})")
            break  # ran out of available history before reaching total_bars
        chunk = pd.DataFrame(rates)
        chunks.append(chunk)
        fetched += len(chunk)
        start_pos += len(chunk)
        if len(chunk) < n:
            break  # short read: this was the oldest history the terminal has

    if not chunks:
        raise RuntimeError(f"No data downloaded for {symbol}.")

    out = pd.concat(chunks, ignore_index=True)
    out = out.drop_duplicates(subset="time").sort_values("time").reset_index(drop=True)
    out["time"] = pd.to_datetime(out["time"], unit="s", utc=True)
    return out[["time", "open", "high", "low", "close", "tick_volume", "spread"]]
