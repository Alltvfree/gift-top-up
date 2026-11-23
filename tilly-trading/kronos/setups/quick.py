"""The Telegram BUY/SELL quick-ticket, as a backtest: one-minute bars, stop = max(6 x spread, recent 5-minute range),
target = 2 x stop, forced exit after ~90 seconds (2 one-minute bars), one trade at a time.

The ticket itself has no opinion about direction, so three ways of choosing it are tested side by side, with the SAME
stop, target, hold time and costs. Nothing is tuned.

  quick_trend     trade WITH the hourly trend (price vs EMA50, EMA20 vs EMA50 on hourly bars built from these bars)
  quick_counter   trade AGAINST the hourly trend
  quick_random    a coin flip for the side (a seeded random baseline)

If the geometry itself cannot beat the spread, all three lose about the same, and no choice of side will fix it. If
quick_trend clearly beats quick_counter AND the random baseline over 500+ trades, the hourly-trend filter is worth
something. Only trading hours 07:00-20:00 are used (spreads widen outside them).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .gabfx import _ohlc_resample, _visible
from .library import _finish


@dataclass
class QuickParams:
    mode: str = "trend"            # trend | counter | random
    rr: float = 2.0
    spread_mult: float = 6.0
    session_start_utc: int = 7
    session_end_utc: int = 20
    seed: int = 7


def _hourly_trend(df: pd.DataFrame) -> np.ndarray:
    h = _ohlc_resample(df, "1h")
    c = h["close"]
    e20, e50 = c.ewm(span=20, adjust=False).mean(), c.ewm(span=50, adjust=False).mean()
    trend = np.where((c > e50) & (e20 > e50), 1.0, np.where((c < e50) & (e20 < e50), -1.0, 0.0))
    trend[:55] = 0.0                                      # EMAs need warming up
    return _visible(df["time"], h, pd.Timedelta(hours=1), {"trend": trend})["trend"]


def quick_signals(df: pd.DataFrame, point: float, p: QuickParams | None = None) -> pd.DataFrame:
    p = p or QuickParams()
    df = df.reset_index(drop=True)
    spread = df["spread"].astype(float) if "spread" in df else pd.Series(np.nan, index=df.index)
    spread_price = spread.fillna(spread.median()).fillna(0.0) * point
    m5_range = (df["high"].rolling(5).max() - df["low"].rolling(5).min()).rolling(12).mean()
    stop = pd.concat([p.spread_mult * spread_price, m5_range], axis=1).max(axis=1)
    hour = pd.DatetimeIndex(df["time"]).hour
    in_session = (hour >= p.session_start_utc) & (hour < p.session_end_utc)
    trend = np.nan_to_num(_hourly_trend(df))
    if p.mode == "trend":
        side = trend
    elif p.mode == "counter":
        side = -trend
    elif p.mode == "random":
        side = np.random.default_rng(p.seed).choice([-1.0, 1.0], size=len(df))
    else:
        raise ValueError("mode must be trend, counter or random")
    ok = in_session & stop.notna().to_numpy() & (stop > 0).to_numpy()
    buy, sell = pd.Series((side > 0) & ok, index=df.index), pd.Series((side < 0) & ok, index=df.index)
    return _finish(df, buy, sell, stop.where(buy), stop.where(sell), p.rr)


def quick_trend(df, point): return quick_signals(df, point, QuickParams(mode="trend"))        # noqa: E704
def quick_counter(df, point): return quick_signals(df, point, QuickParams(mode="counter"))    # noqa: E704
def quick_random(df, point): return quick_signals(df, point, QuickParams(mode="random"))      # noqa: E704


# The bot's new defaults: stop >= 15 spreads, ~5-minute hold (use setup_xauusd_m1_slow.toml: max_holding_bars = 5).
def quick15_trend(df, point): return quick_signals(df, point, QuickParams(mode="trend", spread_mult=15.0))        # noqa: E704
def quick15_counter(df, point): return quick_signals(df, point, QuickParams(mode="counter", spread_mult=15.0))    # noqa: E704
def quick15_random(df, point): return quick_signals(df, point, QuickParams(mode="random", spread_mult=15.0))      # noqa: E704
