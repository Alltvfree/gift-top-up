"""Plan odds by replaying the future many times — the Time Machine idea from
day-trader-skill, rebuilt for MT5 bars. Each simulated bar is drawn from the
symbol's OWN recent bars (its high/low/close relative to its open), chained so
each bar opens where the last closed, and checked against the stop and target
with the same conservative rule as the backtester (a bar that spans both
counts as the stop).

What this is and isn't: it measures the GEOMETRY of a plan — given this
symbol's real volatility, how often does price reach a target N away before a
stop M away, and how often does neither happen in time. It draws bars
independently and direction-neutral (every bar's mirror image is added to the pool, so the
sample's own trend and skew cannot favor BUY or SELL), so it contains no view on direction: it cannot
manufacture an edge, and a plan that only looks good here is just a wide
target. An edge has to come from the setup or the forecast, not from this.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def simulate_plan(
    bars: pd.DataFrame,
    *,
    side: str,
    entry: float,
    sl: float,
    tp: float,
    horizon_bars: int,
    spread_price: float = 0.0,
    simulations: int = 5000,
    seed: int = 7,
    same_hour: bool = True,
    direction_neutral: bool = True,
) -> dict:
    """bars: closed OHLC bars with a tz-aware `time` column, oldest first."""
    side = side.upper()
    if side not in ("BUY", "SELL"):
        raise ValueError("side must be BUY or SELL")
    if (side == "BUY" and not sl < entry < tp) or (side == "SELL" and not tp < entry < sl):
        raise ValueError("stop and target must straddle the entry on the correct sides")
    if horizon_bars < 1 or simulations < 100:
        raise ValueError("need horizon_bars >= 1 and simulations >= 100")
    if len(bars) < 50:
        raise ValueError(f"need at least 50 history bars, got {len(bars)}")

    o = bars["open"].to_numpy(float)
    shapes = np.column_stack(
        [bars["high"].to_numpy(float) / o - 1, bars["low"].to_numpy(float) / o - 1, bars["close"].to_numpy(float) / o - 1]
    )
    hours = bars["time"].dt.hour.to_numpy()
    if direction_neutral:
        # Resampled bars carry their own history: a gold rally would make every
        # BUY look good, and even with the mean removed a sample's skew still
        # favors one side. Adding each bar's mirror image (high<->-low, close
        # negated) makes BUY and SELL exactly symmetric, keeping every range.
        shapes = np.vstack([shapes, np.column_stack([-shapes[:, 1], -shapes[:, 0], -shapes[:, 2]])])
        hours = np.concatenate([hours, hours])
    step = bars["time"].diff().dropna().median()
    last_time = bars["time"].iloc[-1]
    bar_hours = [(last_time + step * k).hour for k in range(1, horizon_bars + 1)]

    rng = np.random.default_rng(seed)
    n = simulations
    picked = np.empty((n, horizon_bars), dtype=int)
    all_idx = np.arange(len(shapes))
    for k, hr in enumerate(bar_hours):
        pool = np.flatnonzero(hours == hr) if same_hour else all_idx
        if len(pool) < 40:  # too few same-hour bars to sample honestly
            pool = all_idx
        picked[:, k] = rng.choice(pool, size=n)
    up, dn, cl = shapes[picked, 0], shapes[picked, 1], shapes[picked, 2]

    close_factor = 1.0 + cl
    opens = entry * np.cumprod(np.concatenate([np.ones((n, 1)), close_factor[:, :-1]], axis=1), axis=1)
    highs, lows, closes = opens * (1 + up), opens * (1 + dn), opens * close_factor

    if side == "BUY":
        tp_hit, sl_hit = highs >= tp, lows <= sl
    else:
        tp_hit, sl_hit = lows <= tp, highs >= sl
    never = horizon_bars  # sentinel index
    first_tp = np.where(tp_hit.any(axis=1), tp_hit.argmax(axis=1), never)
    first_sl = np.where(sl_hit.any(axis=1), sl_hit.argmax(axis=1), never)
    sl_first = first_sl <= first_tp
    sl_first &= first_sl < never
    tp_first = (first_tp < first_sl) & (first_tp < never)
    neither = ~(sl_first | tp_first)

    risk = abs(entry - sl)
    sign = 1.0 if side == "BUY" else -1.0
    open_r = sign * (closes[:, -1] - entry) / risk
    r = np.where(tp_first, abs(tp - entry) / risk, np.where(sl_first, -1.0, open_r))
    resolved_at = np.where(tp_first, first_tp, np.where(sl_first, first_sl, never))
    cost_r = spread_price / risk
    rr = abs(tp - entry) / risk
    exp_r = float(r.mean()) - cost_r

    return {
        "simulations": n, "seed": seed, "history_bars": len(bars), "horizon_bars": horizon_bars,
        "p_target_first": float(tp_first.mean()),
        "p_stop_first": float(sl_first.mean()),
        "p_neither": float(neither.mean()),
        "reward_risk": float(rr),
        "breakeven_p_target": float(1.0 / (1.0 + rr)),
        "expected_r_before_spread": float(r.mean()),
        "expected_r_after_spread": exp_r,
        "median_bars_to_resolve": float(np.median(resolved_at[~neither])) if (~neither).any() else None,
        "verdict": _verdict(exp_r),
        "caveat": "Random-walk replay of this symbol's own recent bars: shows plan geometry and cost, "
                  "not direction. It cannot create an edge.",
    }


def _verdict(expected_r: float) -> str:
    if expected_r > 0.1:
        return "geometry looks favorable (unusual under a no-drift replay: check the inputs)"
    if expected_r < -0.1:
        return "geometry costs you: spread/time-outs eat more than the plan earns"
    return "close to a coin flip, as a no-drift replay should be: any edge has to come from the setup"
