"""Technical indicators — EMA, RSI, ATR (+ helpers).

Pure functions over pandas Series so they are trivial to unit-test and reuse in
both live evaluation and backtesting. No look-ahead: every value at index *i* is
computed only from data at indices <= *i*.

RSI and ATR use **Wilder's smoothing** (the conventional definition used by most
charting platforms, including MT5).
"""

from __future__ import annotations

from typing import Sequence

import numpy as np
import pandas as pd

from app.core.models import Candle


# --- Moving averages ---------------------------------------------------------
def sma(values: pd.Series, period: int) -> pd.Series:
    """Simple moving average."""
    _check_period(period)
    return values.rolling(window=period, min_periods=period).mean()


def ema(values: pd.Series, period: int) -> pd.Series:
    """Exponential moving average (recursive, ``adjust=False``)."""
    _check_period(period)
    return values.ewm(span=period, adjust=False, min_periods=period).mean()


# --- RSI ---------------------------------------------------------------------
def rsi(values: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index using Wilder's smoothing.

    Returns values in [0, 100]. When average loss is zero, RSI is 100.
    """
    _check_period(period)
    delta = values.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)

    # Wilder's smoothing == EMA with alpha = 1/period.
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()

    rs = avg_gain / avg_loss
    result = 100.0 - (100.0 / (1.0 + rs))
    # avg_loss == 0 -> rs == inf -> result == 100 (no losses = maximally strong).
    result = result.where(avg_loss != 0.0, 100.0)
    # Preserve NaN during the warm-up window.
    result = result.where(avg_gain.notna(), np.nan)
    return result


# --- ATR ---------------------------------------------------------------------
def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """True Range: max of the three classic ranges."""
    prev_close = close.shift(1)
    ranges = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    )
    return ranges.max(axis=1)


def atr(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> pd.Series:
    """Average True Range using Wilder's smoothing."""
    _check_period(period)
    tr = true_range(high, low, close)
    # First TR row has no previous close; smoothing starts once we have `period`.
    return tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


# --- DataFrame convenience ---------------------------------------------------
def candles_to_frame(candles: Sequence[Candle]) -> pd.DataFrame:
    """Convert a sequence of :class:`Candle` to an OHLCV DataFrame indexed by time."""
    if not candles:
        return pd.DataFrame(
            columns=["open", "high", "low", "close", "tick_volume"]
        ).astype(float)
    rows = {
        "time": [c.time for c in candles],
        "open": [c.open for c in candles],
        "high": [c.high for c in candles],
        "low": [c.low for c in candles],
        "close": [c.close for c in candles],
        "tick_volume": [c.tick_volume for c in candles],
    }
    frame = pd.DataFrame(rows).set_index("time")
    return frame


def _check_period(period: int) -> None:
    if not isinstance(period, (int, np.integer)) or period < 1:
        raise ValueError(f"period must be a positive integer, got {period!r}")


__all__ = [
    "sma",
    "ema",
    "rsi",
    "true_range",
    "atr",
    "candles_to_frame",
]
