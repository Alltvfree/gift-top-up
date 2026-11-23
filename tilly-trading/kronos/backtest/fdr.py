"""Multiple-testing correction for the strategy comparison table.

Every extra strategy we test is another lottery ticket: test 25 ideas with no edge at all and one or two will look
'significant' by luck. Benjamini-Hochberg controls the expected share of false discoveries among the rows it
calls significant. `family_size` lets you count strategies you tried in earlier runs too (the honest way to use it:
the total number of ideas tested on this symbol, not just the rows in this table).

The p-value is two-sided from the trade-level t statistic with a normal approximation, which is reasonable from
about 30 trades and conservative in spirit only above 500; the table already refuses a verdict below that.
"""
from __future__ import annotations

import math


def normal_two_sided_p(t: float) -> float:
    if t is None or not math.isfinite(t):
        return float("nan")
    return math.erfc(abs(t) / math.sqrt(2.0))


def benjamini_hochberg(pvals: list[float], family_size: int | None = None) -> list[float]:
    """Adjusted q-values, same order as the input. NaN p-values stay NaN and don't count as tests unless family_size says so.
    family_size larger than the number of valid p-values assumes the untested remainder had p = 1."""
    valid = [(i, p) for i, p in enumerate(pvals) if p is not None and not math.isnan(p)]
    m = max(family_size or 0, len(valid))
    order = sorted(valid, key=lambda ip: ip[1])
    q = [float("nan")] * len(pvals)
    running = 1.0
    for rank in range(len(order), 0, -1):
        i, p = order[rank - 1]
        running = min(running, p * m / rank)
        q[i] = min(running, 1.0)
    return q
