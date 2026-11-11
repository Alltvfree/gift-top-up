"""A library of rule-based setups transcribed from the material the user
collected (a Pine RSI scalper, a Pine EMA-ribbon indicator, an SMC/liquidity
course), each reduced to fixed, testable rules.

Nothing here is a claim that these work. Each strategy is a *candidate*: it
emits the same frame the trend-pullback setup does (setup_buy / setup_sell /
signal_sl_distance / signal_tp_distance / predicted_probability_*), so the
backtester can score it on its own, and backtest/compare_setups.py ranks them
and tests combinations. Rules are fixed up front from the sources and are not
tuned on results.

Every signal on bar t uses data through bar t only; the simulator acts at bar
t+1's open.

Strategies
  mayfair_rsi     RSI(14, on OPEN) < 31 buy / > 73 sell, with a candle in the
                  signal direction after an opposite previous candle. Fixed
                  stop, 3R target (the indicator's TP3). Source: Mayfair FX
                  Scalper V15.
  dtc_ribbon      Six EMAs (30..60) newly stack in order (bull or bear) with an
                  ATR floor. Stop = a % of price, target = rr x stop. Source:
                  DTC v1.36.
  smc_sweep       Liquidity sweep (stop hunt): price pierces an unbroken swing
                  high/low (3-candle formation), an Asia-range extreme, or the
                  previous day's high/low, then closes back inside. Trade the
                  reversal; stop beyond the sweep. Optional premium/discount
                  filter. Source: Tyrone FX SMC course.

Not transcribed: order blocks, FVG and volumetric metrics from the SMC Pine
indicators. They are chart-drawing tools with many free parameters; adding
them without a rule you would trade is just more knobs to overfit.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd


def _atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    prev = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - prev).abs(), (df["low"] - prev).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def _rsi(src: pd.Series, n: int) -> pd.Series:
    d = src.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.where(dn != 0, 100.0).where(up.notna())


def _finish(df: pd.DataFrame, buy: pd.Series, sell: pd.Series, sl_buy: pd.Series, sl_sell: pd.Series, rr: float) -> pd.DataFrame:
    out = df.copy()
    buy = buy.fillna(False) & sl_buy.notna() & (sl_buy > 0)
    sell = sell.fillna(False) & sl_sell.notna() & (sl_sell > 0)
    both = buy & sell  # contradictory on one bar -> no trade
    buy, sell = buy & ~both, sell & ~both
    sl = pd.Series(np.nan, index=out.index)
    sl[buy] = sl_buy[buy]
    sl[sell] = sl_sell[sell]
    out["setup_buy"], out["setup_sell"] = buy.astype(bool), sell.astype(bool)
    out["signal_sl_distance"] = sl
    out["signal_tp_distance"] = sl * rr
    out["predicted_probability_buy"] = out["setup_buy"].astype(float)
    out["predicted_probability_sell"] = out["setup_sell"].astype(float)
    return out


# ---------------------------------------------------------------- Mayfair RSI
@dataclass
class MayfairParams:
    rsi_length: int = 14
    oversold: float = 31.0
    overbought: float = 73.0
    sl_price: float = 6.0   # the indicator's gold stop on M15: 60 "pips" x 0.1
    rr: float = 3.0         # it exits at TP3 (3:1) or the stop


def mayfair_rsi(df: pd.DataFrame, point: float, p: MayfairParams | None = None) -> pd.DataFrame:
    p = p or MayfairParams()
    rsi = _rsi(df["open"], p.rsi_length)
    bull, bear = df["close"] > df["open"], df["close"] < df["open"]
    prev_bull, prev_bear = bull.shift(1, fill_value=False), bear.shift(1, fill_value=False)
    buy = (rsi < p.oversold) & bull & ~prev_bull
    sell = (rsi > p.overbought) & bear & ~prev_bear
    sl = pd.Series(p.sl_price, index=df.index)
    return _finish(df, buy, sell, sl, sl, p.rr)


# ------------------------------------------------------------------ DTC ribbon
@dataclass
class DtcParams:
    lengths: tuple = (30, 35, 40, 45, 50, 60)
    atr_period: int = 14
    atr_min: float = 0.5     # price units (the source's default; gold-scale)
    sl_pct: float = 0.25     # stop distance, % of entry price
    rr: float = 2.0          # the source draws TP1-TP4 at 1-4x; 2x is fixed here up front


def dtc_ribbon(df: pd.DataFrame, point: float, p: DtcParams | None = None) -> pd.DataFrame:
    p = p or DtcParams()
    emas = [df["close"].ewm(span=n, adjust=False).mean() for n in p.lengths]
    bull = pd.Series(True, index=df.index)
    bear = pd.Series(True, index=df.index)
    for a, b in zip(emas, emas[1:]):
        bull &= a > b
        bear &= a < b
    atr_ok = _atr(df, p.atr_period) > p.atr_min
    buy = bull & ~bull.shift(1, fill_value=False) & atr_ok
    sell = bear & ~bear.shift(1, fill_value=False) & atr_ok
    sl = df["close"] * p.sl_pct / 100.0
    return _finish(df, buy, sell, sl, sl, p.rr)


# ------------------------------------------------------------------- SMC sweep
@dataclass
class SmcSweepParams:
    swing_lookback_bars: int = 200     # how old an unbroken swing may be and still count
    use_swings: bool = True
    use_asia: bool = True
    use_prev_day: bool = True
    asia_start_utc: int = 0
    asia_end_utc: int = 7
    session_start_utc: int = 7
    session_end_utc: int = 20
    require_premium_discount: bool = True   # sells from the upper half, buys from the lower half of the range
    range_bars: int = 96
    sl_buffer_atr: float = 0.25
    min_sl_atr: float = 0.5
    max_sl_atr: float = 3.0
    rr: float = 2.0


def _swing_levels(high: np.ndarray, low: np.ndarray, lookback: int):
    """3-candle swings, known one bar late (the middle candle is the extreme
    of the three). Yields, for every bar, the unbroken swing highs/lows that
    were confirmed BEFORE it, as sweep candidates for that bar."""
    n = len(high)
    sweep_high = np.full(n, np.nan)   # lowest pierced unbroken swing high (the level to close back below)
    sweep_low = np.full(n, np.nan)    # highest pierced unbroken swing low
    highs: list[tuple[int, float]] = []
    lows: list[tuple[int, float]] = []
    for t in range(n):
        if t >= 2:
            m = t - 1  # middle candle of (t-2, t-1, t), confirmed on t
            if high[m] > high[m - 1] and high[m] > high[t]:
                highs.append((m, high[m]))
            if low[m] < low[m - 1] and low[m] < low[t]:
                lows.append((m, low[m]))
        # the swing confirmed on bar t can't be pierced by bar t itself in a
        # way we can trade (bar t is its right-hand candle), so check the rest
        cutoff = t - lookback
        pierced_h = [lvl for (i, lvl) in highs if i < t - 1 and high[t] > lvl]
        pierced_l = [lvl for (i, lvl) in lows if i < t - 1 and low[t] < lvl]
        if pierced_h:
            sweep_high[t] = min(pierced_h)
        if pierced_l:
            sweep_low[t] = max(pierced_l)
        highs = [(i, lvl) for (i, lvl) in highs if i >= cutoff and not (i < t - 1 and high[t] > lvl)]
        lows = [(i, lvl) for (i, lvl) in lows if i >= cutoff and not (i < t - 1 and low[t] < lvl)]
    return sweep_high, sweep_low


def smc_sweep(df: pd.DataFrame, point: float, p: SmcSweepParams | None = None) -> pd.DataFrame:
    p = p or SmcSweepParams()
    high, low, close = df["high"], df["low"], df["close"]
    atr = _atr(df)
    t = df["time"]
    hour, day = t.dt.hour, t.dt.floor("D")

    # candidate "liquidity above" / "liquidity below" levels that this bar pierced
    above = pd.Series(np.nan, index=df.index)   # level a bar must pierce then close back under (-> sell)
    below = pd.Series(np.nan, index=df.index)   # level a bar must pierce then close back over (-> buy)

    def _merge(target: pd.Series, new: pd.Series, how) -> pd.Series:
        return target.combine(new, lambda a, b: b if pd.isna(a) else (a if pd.isna(b) else how(a, b)))

    if p.use_swings:
        sh, sl_ = _swing_levels(high.to_numpy(float), low.to_numpy(float), p.swing_lookback_bars)
        above = _merge(above, pd.Series(sh, index=df.index), min)
        below = _merge(below, pd.Series(sl_, index=df.index), max)
    if p.use_asia:
        in_asia = (hour >= p.asia_start_utc) & (hour < p.asia_end_utc)
        a_hi = high.where(in_asia).groupby(day).cummax()
        a_lo = low.where(in_asia).groupby(day).cummin()
        # the Asia range is "known" only once Asia is over, i.e. from asia_end onward that day
        known = hour >= p.asia_end_utc
        a_hi = a_hi.groupby(day).transform("max").where(known)
        a_lo = a_lo.groupby(day).transform("min").where(known)
        above = _merge(above, a_hi.where(high > a_hi), min)
        below = _merge(below, a_lo.where(low < a_lo), max)
    if p.use_prev_day:
        d_hi = high.groupby(day).transform("max")
        d_lo = low.groupby(day).transform("min")
        by_day = pd.DataFrame({"day": day, "hi": d_hi, "lo": d_lo}).drop_duplicates("day").set_index("day")
        pdh = day.map(by_day["hi"].shift(1))
        pdl = day.map(by_day["lo"].shift(1))
        above = _merge(above, pdh.where(high > pdh), min)
        below = _merge(below, pdl.where(low < pdl), max)

    swept_up = above.notna() & (close < above)       # stop hunt above, rejected -> SELL
    swept_down = below.notna() & (close > below)     # stop hunt below, rejected -> BUY

    rng_hi, rng_lo = high.rolling(p.range_bars).max(), low.rolling(p.range_bars).min()
    mid = (rng_hi + rng_lo) / 2
    sell_zone = (close >= mid) if p.require_premium_discount else True
    buy_zone = (close <= mid) if p.require_premium_discount else True

    in_session = (hour >= p.session_start_utc) & (hour < p.session_end_utc)
    sl_sell = (high + p.sl_buffer_atr * atr) - close
    sl_buy = close - (low - p.sl_buffer_atr * atr)
    ok_sell = (sl_sell >= p.min_sl_atr * atr) & (sl_sell <= p.max_sl_atr * atr)
    ok_buy = (sl_buy >= p.min_sl_atr * atr) & (sl_buy <= p.max_sl_atr * atr)

    sell = swept_up & sell_zone & in_session & ok_sell & rng_hi.notna()
    buy = swept_down & buy_zone & in_session & ok_buy & rng_hi.notna()
    return _finish(df, buy, sell, sl_buy.where(buy), sl_sell.where(sell), p.rr)


STRATEGIES: dict[str, Callable[[pd.DataFrame, float], pd.DataFrame]] = {
    "mayfair_rsi": mayfair_rsi,
    "dtc_ribbon": dtc_ribbon,
    "smc_sweep": smc_sweep,
}


def confluence(frames: dict[str, pd.DataFrame], min_agree: int = 2, window_bars: int = 3, rr: float = 2.0) -> pd.DataFrame:
    """Agreement ensemble: BUY when at least `min_agree` strategies produced a
    BUY within the last `window_bars` bars (and none produced a SELL in that
    window); SELL mirrored. The stop is the tightest of the agreeing
    strategies' stops (carried forward within the window); target = rr x stop.

    This exists to be TESTED, not assumed: compare_setups reports whether
    requiring agreement actually beats its best member.
    """
    names = list(frames)
    base = frames[names[0]].copy()
    buy_votes = sum(frames[n]["setup_buy"].astype(int).rolling(window_bars, min_periods=1).max() for n in names)
    sell_votes = sum(frames[n]["setup_sell"].astype(int).rolling(window_bars, min_periods=1).max() for n in names)
    # fire once, on the bar that completes the agreement
    buy = (buy_votes >= min_agree) & (sell_votes == 0)
    sell = (sell_votes >= min_agree) & (buy_votes == 0)
    buy &= ~buy.shift(1, fill_value=False)
    sell &= ~sell.shift(1, fill_value=False)

    def tightest(side: str) -> pd.Series:
        cols = []
        for n in names:
            f = frames[n]
            cols.append(f["signal_sl_distance"].where(f[f"setup_{side}"]).ffill(limit=window_bars - 1))
        return pd.concat(cols, axis=1).min(axis=1)

    return _finish(base.drop(columns=[c for c in base.columns if c.startswith(("setup_", "signal_", "predicted_"))]),
                   buy, sell, tightest("buy"), tightest("sell"), rr)
