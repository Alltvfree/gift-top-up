"""Three directional strategies from Hummingbot's `controllers/directional_trading`, reduced to fixed rules we can score.

Source: https://github.com/hummingbot/hummingbot (Apache License 2.0). The SIGNAL rules below are transcribed from
bollinger_v1.py, macd_bb_v1.py and supertrend_v1.py; no code is copied. Parameter defaults are Hummingbot's own.

  hb_bollinger   %B of Bollinger Bands(100, 2): BUY when %B < 0 (close under the lower band), SELL when %B > 1.
                 A mean-reversion rule: fade the stretch.
  hb_macd_bb     the Bollinger stretch above AND MACD(21, 42, 9) turning back: BUY when %B < 0, MACD histogram > 0 and
                 the MACD line is still below zero; SELL when %B > 1, histogram < 0 and the MACD line above zero.
  hb_supertrend  Supertrend(20, 4.0): BUY while the trend is up and price is within 1% of the Supertrend line, SELL
                 mirrored. A trend-following rule that waits for price to come back to the line.

What is NOT from Hummingbot, because its defaults don't fit our scoring:
  Exits. Hummingbot's triple barrier defaults to a 3% stop, 2% target and a time limit. Here every strategy gets the same
  fair test as the rest of this project: stop = 1.5 x ATR(14), target = 2 x stop (so results are in R), and the
  backtester's own max-holding setting as the time limit. Nothing is tuned.
  Repeat signals. Like the source, a signal is emitted on EVERY bar where the condition holds; the backtester's one
  position at a time and cooldown decide when a new trade can start.

These are candidates. Hummingbot ships them as examples of the framework, not as proven money-makers.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .library import _atr, _finish


@dataclass
class HbParams:
    bb_length: int = 100
    bb_std: float = 2.0
    bb_long_threshold: float = 0.0
    bb_short_threshold: float = 1.0
    macd_fast: int = 21
    macd_slow: int = 42
    macd_signal: int = 9
    st_length: int = 20
    st_multiplier: float = 4.0
    st_threshold: float = 0.01
    stop_atr: float = 1.5
    rr: float = 2.0


def bbp(close: pd.Series, length: int, std: float) -> pd.Series:
    """Bollinger %B: 0 at the lower band, 1 at the upper band (population std, as pandas_ta computes it)."""
    mid = close.rolling(length).mean()
    sd = close.rolling(length).std(ddof=0)
    lower, upper = mid - std * sd, mid + std * sd
    return (close - lower) / (upper - lower).replace(0, np.nan)


def macd_parts(close: pd.Series, fast: int, slow: int, signal: int) -> tuple[pd.Series, pd.Series]:
    macd = close.ewm(span=fast, adjust=False).mean() - close.ewm(span=slow, adjust=False).mean()
    return macd, macd - macd.ewm(span=signal, adjust=False).mean()          # (MACD line, histogram)


def supertrend(df: pd.DataFrame, length: int, multiplier: float) -> tuple[np.ndarray, np.ndarray]:
    """The pandas_ta Supertrend: returns (line, direction) with direction +1 up / -1 down."""
    hl2 = ((df["high"] + df["low"]) / 2).to_numpy(float)
    atr = _atr(df, length).to_numpy(float)
    c = df["close"].to_numpy(float)
    upper, lower = hl2 + multiplier * atr, hl2 - multiplier * atr
    n = len(c)
    direction = np.ones(n)
    line = np.full(n, np.nan)
    for i in range(1, n):
        if np.isnan(upper[i - 1]):
            direction[i] = direction[i - 1]
            continue
        if c[i] > upper[i - 1]:
            direction[i] = 1
        elif c[i] < lower[i - 1]:
            direction[i] = -1
        else:
            direction[i] = direction[i - 1]
            if direction[i] > 0 and lower[i] < lower[i - 1]:
                lower[i] = lower[i - 1]
            if direction[i] < 0 and upper[i] > upper[i - 1]:
                upper[i] = upper[i - 1]
        line[i] = lower[i] if direction[i] == 1 else upper[i]
    return line, direction


def _stop(df: pd.DataFrame, p: HbParams) -> pd.Series:
    return p.stop_atr * _atr(df)


def hb_bollinger(df: pd.DataFrame, point: float, p: HbParams | None = None) -> pd.DataFrame:
    p = p or HbParams()
    df = df.reset_index(drop=True)
    b = bbp(df["close"], p.bb_length, p.bb_std)
    buy, sell = b < p.bb_long_threshold, b > p.bb_short_threshold
    st = _stop(df, p)
    return _finish(df, buy, sell, st.where(buy), st.where(sell), p.rr)


def macd_bb_conditions(b: pd.Series, macd: pd.Series, hist: pd.Series, p: HbParams) -> tuple[pd.Series, pd.Series]:
    return (b < p.bb_long_threshold) & (hist > 0) & (macd < 0), (b > p.bb_short_threshold) & (hist < 0) & (macd > 0)


def hb_macd_bb(df: pd.DataFrame, point: float, p: HbParams | None = None) -> pd.DataFrame:
    p = p or HbParams()
    df = df.reset_index(drop=True)
    macd, hist = macd_parts(df["close"], p.macd_fast, p.macd_slow, p.macd_signal)
    buy, sell = macd_bb_conditions(bbp(df["close"], p.bb_length, p.bb_std), macd, hist, p)
    st = _stop(df, p)
    return _finish(df, buy, sell, st.where(buy), st.where(sell), p.rr)


def hb_supertrend(df: pd.DataFrame, point: float, p: HbParams | None = None) -> pd.DataFrame:
    p = p or HbParams()
    df = df.reset_index(drop=True)
    line, direction = supertrend(df, p.st_length, p.st_multiplier)
    near = pd.Series(np.abs(df["close"].to_numpy(float) - line) / df["close"].to_numpy(float) < p.st_threshold, index=df.index)
    buy, sell = near & pd.Series(direction == 1, index=df.index), near & pd.Series(direction == -1, index=df.index)
    st = _stop(df, p)
    return _finish(df, buy, sell, st.where(buy), st.where(sell), p.rr)
