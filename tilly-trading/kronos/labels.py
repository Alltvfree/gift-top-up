"""TP-before-SL outcome labeling.

Per the project notes: instead of a weak proxy like "will price be higher
in N bars", label each bar with whether a trade entered at that bar's close
would have hit its take-profit before its stop-loss, walking forward
through the *actual* subsequent bars. This is the model's real question —
"what's the probability this trade reaches TP before SL" — not just price
direction.

This is deliberately the one place that looks at future bars — a label
needs to know the outcome. features.py must never do this; mixing the two
is how lookahead bias creeps in.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def label_tp_before_sl(
    df: pd.DataFrame,
    tp_distance: float,
    sl_distance: float,
    side: str,
    max_bars_forward: int = 50,
) -> pd.Series:
    """For each bar i, simulate a `side` trade entered at close[i] with the
    given TP/SL distances (same price units as the symbol, e.g. dollars for
    XAUUSD), and label 1.0 if TP is reached before SL within the next
    `max_bars_forward` bars, 0.0 if SL is reached first (or both are
    touched within the same bar — OHLC alone can't say which came first,
    so that case is conservatively scored a loss). If neither is reached
    within the horizon, the label is left NaN rather than guessed — the
    caller should drop those rows before training, since the trade's true
    outcome is simply unknown at that point.

    O(n * max_bars_forward) — a plain Python loop, not vectorized. That's
    fine for an offline training-time preprocessing step; it does not run
    in the live inference path.
    """
    if side.upper() not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if tp_distance <= 0 or sl_distance <= 0:
        raise ValueError("tp_distance and sl_distance must both be positive.")

    close = df["close"].to_numpy()
    high = df["high"].to_numpy()
    low = df["low"].to_numpy()
    n = len(df)
    labels = np.full(n, np.nan)
    is_buy = side.upper() == "BUY"

    for i in range(max(0, n - max_bars_forward)):
        entry = close[i]
        if is_buy:
            tp, sl = entry + tp_distance, entry - sl_distance
        else:
            tp, sl = entry - tp_distance, entry + sl_distance

        for j in range(i + 1, i + 1 + max_bars_forward):
            hit_tp = high[j] >= tp if is_buy else low[j] <= tp
            hit_sl = low[j] <= sl if is_buy else high[j] >= sl
            if hit_tp and hit_sl:
                labels[i] = 0.0
                break
            if hit_tp:
                labels[i] = 1.0
                break
            if hit_sl:
                labels[i] = 0.0
                break
        # else: neither hit within the horizon -> stays NaN.

    return pd.Series(labels, index=df.index, name="label")
