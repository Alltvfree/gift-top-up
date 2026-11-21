"""The GABFX "Mastermind" ebook method, reduced to fixed, testable rules.

This is ONE reading of a marketing ebook whose wording is loose. Where it was
vague, the choice made here is written down below so you can disagree with it.
Nothing is tuned on results.

What the ebook says -> what is coded
  Zones      Support = a bearish candle followed by a bullish one; resistance =
             bullish then bearish. (Page 7-8.)  Zone range here: support =
             [lowest low of the two candles, higher of bear-close / bull-open];
             resistance = [lower of bull-close / bear-open, highest high].
  Storyline  The higher timeframe's direction (daily; weekly as a gate). Bullish
             starts when a candle CLOSES above the latest resistance zone and
             lasts until a close below the latest support zone (and the mirror).
             (Page 17.)  "Weekly and daily disagree = NO TRADE." (Page 18.)
  Entry      Buy: daily storyline bullish, weekly not bearish, price rejects
             (wick) into a daily support zone and a NEW bear->bull support
             forms on the trading timeframe inside it (confirmations 1 and 2,
             which the ebook calls "medium risk, you can enter here", page 14).
             Sell is the exact mirror.
  3rd conf.  `confirmations=3` additionally waits for a close through the
             recent swing level and then a pullback that holds it (page 14).
  Risk       NOT in the ebook in testable form. Stop = just beyond the new
             zone, target = rr x stop, so results are scored in R.

Daily/weekly bars are built from the same bars you give it (resampled), and a
daily bar is only visible from the NEXT day (a weekly bar from the next week),
so a signal on bar t uses nothing that was not complete by then.

Not used: the ebook's "hold through pullbacks", "deposit big" and sizing
advice. Those are not rules a backtest can test, and the last is dangerous.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .library import _atr, _finish


@dataclass
class GabfxParams:
    confirmations: int = 2          # 2 = rejection + new SNR; 3 adds breakout + pullback
    use_weekly_gate: bool = True
    zone_max_age_days: int = 30     # a daily zone stops counting after this long
    tolerance_atr: float = 0.25     # how far outside a zone still counts as "in" it
    swing_bars: int = 6             # bars defining the level a 3rd-confirmation breakout must clear
    breakout_window: int = 12       # bars allowed for breakout, and again for the pullback
    sl_buffer_atr: float = 0.25
    min_sl_atr: float = 0.5
    max_sl_atr: float = 3.0
    rr: float = 2.0


def two_candle_zones(o: np.ndarray, h: np.ndarray, l: np.ndarray, c: np.ndarray):
    """Per bar i (complete at its close): support zone (bear i-1, bull i) and
    resistance zone (bull i-1, bear i). Returns four arrays of zone bounds, NaN where none."""
    n = len(o)
    s_lo = np.full(n, np.nan); s_hi = np.full(n, np.nan)
    r_lo = np.full(n, np.nan); r_hi = np.full(n, np.nan)
    for i in range(1, n):
        bear_prev, bull_prev = c[i - 1] < o[i - 1], c[i - 1] > o[i - 1]
        bull, bear = c[i] > o[i], c[i] < o[i]
        if bear_prev and bull:
            s_lo[i], s_hi[i] = min(l[i - 1], l[i]), max(c[i - 1], o[i])
        if bull_prev and bear:
            r_lo[i], r_hi[i] = min(c[i - 1], o[i]), max(h[i - 1], h[i])
    return s_lo, s_hi, r_lo, r_hi


def storyline_and_zones(o, h, l, c, max_age: int):
    """Walk completed higher-timeframe bars. Returns per bar: state (+1/-1/0) and the
    latest still-valid support / resistance zone (NaN when none or expired)."""
    n = len(o)
    s_lo, s_hi, r_lo, r_hi = two_candle_zones(o, h, l, c)
    state = np.zeros(n)
    sup = np.full((n, 3), np.nan)   # lo, hi, age-start index
    res = np.full((n, 3), np.nan)
    cur_s = cur_r = None            # (lo, hi, formed_at)
    st = 0
    for i in range(n):
        if cur_s is not None and (c[i] < cur_s[0] or i - cur_s[2] > max_age):
            if c[i] < cur_s[0]:
                st = -1                     # closed through support: bearish story
            cur_s = None
        if cur_r is not None and (c[i] > cur_r[1] or i - cur_r[2] > max_age):
            if c[i] > cur_r[1]:
                st = 1                      # closed through resistance: bullish story
            cur_r = None
        if not np.isnan(s_lo[i]):
            cur_s = (s_lo[i], s_hi[i], i)
        if not np.isnan(r_lo[i]):
            cur_r = (r_lo[i], r_hi[i], i)
        state[i] = st
        if cur_s is not None:
            sup[i] = (cur_s[0], cur_s[1], cur_s[2])
        if cur_r is not None:
            res[i] = (cur_r[0], cur_r[1], cur_r[2])
    return state, sup, res


def _ohlc_resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    t = pd.DatetimeIndex(df["time"])
    x = df[["open", "high", "low", "close"]].copy()
    x.index = t
    return x.resample(rule, label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()


def _visible(df_time: pd.Series, htf: pd.DataFrame, period: pd.Timedelta, values: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """Map higher-timeframe results onto base bars, using a bar only once its period is over."""
    avail = pd.DataFrame({"avail": htf.index + period, **{k: v for k, v in values.items()}}).sort_values("avail")
    base = pd.DataFrame({"time": pd.DatetimeIndex(df_time)}).reset_index(drop=True)
    base["_ord"] = np.arange(len(base))
    tz = base["time"].dt.tz
    avail["avail"] = pd.DatetimeIndex(avail["avail"]).tz_localize(tz) if tz is not None and avail["avail"].dt.tz is None else avail["avail"]
    merged = pd.merge_asof(base.sort_values("time"), avail, left_on="time", right_on="avail", direction="backward").sort_values("_ord")
    return {k: merged[k].to_numpy(float) for k in values}


def build_context(df: pd.DataFrame, p: GabfxParams) -> dict[str, np.ndarray]:
    d = _ohlc_resample(df, "1D")
    ds, dsup, dres = storyline_and_zones(*(d[k].to_numpy(float) for k in ("open", "high", "low", "close")), p.zone_max_age_days)
    day_vals = {"d_state": ds, "ds_lo": dsup[:, 0], "ds_hi": dsup[:, 1], "dr_lo": dres[:, 0], "dr_hi": dres[:, 1]}
    ctx = _visible(df["time"], d, pd.Timedelta(days=1), day_vals)
    w = _ohlc_resample(df, "W-MON")
    ws, _, _ = storyline_and_zones(*(w[k].to_numpy(float) for k in ("open", "high", "low", "close")), 52)
    ctx.update(_visible(df["time"], w, pd.Timedelta(days=7), {"w_state": ws}))
    return ctx


def signals_from_context(df: pd.DataFrame, ctx: dict[str, np.ndarray], p: GabfxParams) -> pd.DataFrame:
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    n = len(df)
    atr = _atr(df).to_numpy(float)
    s_lo, s_hi, r_lo, r_hi = two_candle_zones(o, h, l, c)
    d_state = np.nan_to_num(ctx["d_state"])
    w_state = np.nan_to_num(ctx["w_state"])
    buy = np.zeros(n, bool); sell = np.zeros(n, bool)
    sl_buy = np.full(n, np.nan); sl_sell = np.full(n, np.nan)

    def aligned(direction: int) -> np.ndarray:
        ok = d_state == direction
        if p.use_weekly_gate:
            ok &= (w_state != -direction)       # "conflict = no trade"
        return ok

    ok_buy, ok_sell = aligned(1), aligned(-1)
    pending: list[dict] = []                    # 3-confirmation events waiting for breakout / pullback

    for t in range(2, n):
        a = atr[t]
        if not np.isfinite(a) or a <= 0:
            continue
        tol = p.tolerance_atr * a
        # ---- confirmations 1+2: rejection into a daily zone, new SNR on this timeframe
        if ok_buy[t] and not np.isnan(s_lo[t]) and not np.isnan(ctx["ds_lo"][t]):
            low_min = min(l[t - 1], l[t])      # the rejection wick: the new zone's low sits inside the daily zone
            if ctx["ds_lo"][t] - tol <= low_min <= ctx["ds_hi"][t] + tol:
                stop = min(l[t - 1], l[t]) - p.sl_buffer_atr * a
                if p.confirmations <= 2:
                    buy[t], sl_buy[t] = True, c[t] - stop
                else:
                    pending.append({"side": 1, "t0": t, "level": h[max(0, t - p.swing_bars):t + 1].max(), "stop": stop, "broke": None})
        if ok_sell[t] and not np.isnan(r_lo[t]) and not np.isnan(ctx["dr_lo"][t]):
            high_max = max(h[t - 1], h[t])
            if ctx["dr_lo"][t] - tol <= high_max <= ctx["dr_hi"][t] + tol:
                stop = max(h[t - 1], h[t]) + p.sl_buffer_atr * a
                if p.confirmations <= 2:
                    sell[t], sl_sell[t] = True, stop - c[t]
                else:
                    pending.append({"side": -1, "t0": t, "level": l[max(0, t - p.swing_bars):t + 1].min(), "stop": stop, "broke": None})
        # ---- confirmation 3: a close through the swing level, then a pullback that holds it
        keep = []
        for ev in pending:
            if t == ev["t0"]:
                keep.append(ev); continue
            s = ev["side"]
            if ev["broke"] is None:
                if t - ev["t0"] > p.breakout_window:
                    continue
                if (s == 1 and c[t] > ev["level"]) or (s == -1 and c[t] < ev["level"]):
                    ev["broke"] = t
                keep.append(ev); continue
            if t - ev["broke"] > p.breakout_window:
                continue
            if s == 1 and l[t] <= ev["level"] + tol and c[t] > ev["level"] and ok_buy[t]:
                buy[t], sl_buy[t] = True, c[t] - ev["stop"] if c[t] > ev["stop"] else np.nan
                continue
            if s == -1 and h[t] >= ev["level"] - tol and c[t] < ev["level"] and ok_sell[t]:
                sell[t], sl_sell[t] = True, ev["stop"] - c[t] if ev["stop"] > c[t] else np.nan
                continue
            keep.append(ev)
        pending = keep

    atr_s = pd.Series(atr, index=df.index)
    sl_b, sl_s = pd.Series(sl_buy, index=df.index), pd.Series(sl_sell, index=df.index)
    ok_b = (sl_b >= p.min_sl_atr * atr_s) & (sl_b <= p.max_sl_atr * atr_s)
    ok_s = (sl_s >= p.min_sl_atr * atr_s) & (sl_s <= p.max_sl_atr * atr_s)
    return _finish(df, pd.Series(buy, index=df.index) & ok_b, pd.Series(sell, index=df.index) & ok_s,
                   sl_b.where(ok_b), sl_s.where(ok_s), p.rr)


def gabfx_snr(df: pd.DataFrame, point: float, p: GabfxParams | None = None) -> pd.DataFrame:
    p = p or GabfxParams()
    df = df.reset_index(drop=True)
    return signals_from_context(df, build_context(df, p), p)


def gabfx_snr2(df: pd.DataFrame, point: float) -> pd.DataFrame:
    return gabfx_snr(df, point, GabfxParams(confirmations=2))


def gabfx_snr3(df: pd.DataFrame, point: float) -> pd.DataFrame:
    return gabfx_snr(df, point, GabfxParams(confirmations=3))
