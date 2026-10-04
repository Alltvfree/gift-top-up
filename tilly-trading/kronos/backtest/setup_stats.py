"""Statistics for judging a rule-based setup honestly (roadmap step 6):
expectancy in R (risk units, comparable across trades whose stops differ),
a bootstrap confidence interval on it, and breakdowns by session, weekday,
month and time-half — plus a verdict that refuses to call anything with too
few trades.

Pure pandas/numpy, no MT5 or lightgbm — fully unit-testable.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .symbols import SymbolSpec

MIN_TRADES_FOR_VERDICT = 500


def add_r_multiple(trades: pd.DataFrame, spec: SymbolSpec) -> pd.DataFrame:
    """R = net P&L / the money actually risked on that trade (entry-to-stop
    distance x contract size x lots). +1R is "won what I risked", -1R is a
    full stop-out; costs (spread/slippage/commission) are already inside
    net_pnl, so a stop-out that filled worse than its level reads below -1R."""
    out = trades.copy()
    risked = (out["entry_price"] - out["stop_loss"]).abs() * spec.contract_size * out["lots"]
    out["risk_money"] = risked
    out["r_multiple"] = out["net_pnl"] / risked.replace(0, np.nan)
    return out


def bootstrap_mean_ci(
    values: np.ndarray, n_boot: int = 5000, alpha: float = 0.05, seed: int = 42, block: int = 250
) -> tuple[float, float]:
    """Percentile bootstrap CI on the mean — resamples trades with
    replacement, in blocks of replicates so memory stays small."""
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    n = len(values)
    if n < 2:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    means = []
    remaining = n_boot
    while remaining > 0:
        k = min(block, remaining)
        idx = rng.integers(0, n, size=(k, n))
        means.append(values[idx].mean(axis=1))
        remaining -= k
    means = np.concatenate(means)
    return float(np.quantile(means, alpha / 2)), float(np.quantile(means, 1 - alpha / 2))


def edge_stats(trades: pd.DataFrame, seed: int = 42) -> dict:
    """Needs the r_multiple column (see add_r_multiple)."""
    r = trades["r_multiple"].dropna().to_numpy()
    n = len(r)
    if n == 0:
        return {"trades": 0}
    mean_r = float(r.mean())
    std_r = float(r.std(ddof=1)) if n > 1 else float("nan")
    lo, hi = bootstrap_mean_ci(r, seed=seed)
    wins, losses = r[r > 0], r[r <= 0]
    payoff = (
        float(wins.mean() / abs(losses.mean()))
        if len(wins) and len(losses) and losses.mean() != 0
        else float("nan")
    )
    return {
        "trades": n,
        "expectancy_r": mean_r,
        "expectancy_r_ci95_low": lo,
        "expectancy_r_ci95_high": hi,
        "t_stat": float(mean_r / (std_r / np.sqrt(n))) if n > 1 and std_r > 0 else float("nan"),
        "win_rate": float((r > 0).mean()),
        "avg_win_r": float(wins.mean()) if len(wins) else 0.0,
        "avg_loss_r": float(losses.mean()) if len(losses) else 0.0,
        "payoff_ratio": payoff,
        # Win rate this realized payoff needs to break even (net of costs, since R is net).
        "breakeven_win_rate": float(1.0 / (1.0 + payoff)) if payoff == payoff and payoff > 0 else float("nan"),
        "total_r": float(r.sum()),
    }


def session_bucket(hour: int) -> str:
    if hour < 7:
        return "asian (00-07 UTC)"
    if hour < 12:
        return "london (07-12 UTC)"
    if hour < 16:
        return "london/new_york overlap (12-16 UTC)"
    if hour < 21:
        return "new_york (16-21 UTC)"
    return "late (21-24 UTC)"


def _group_row(label, g: pd.DataFrame) -> dict:
    wins = g.loc[g["net_pnl"] > 0, "net_pnl"].sum()
    losses = g.loc[g["net_pnl"] <= 0, "net_pnl"].sum()
    return {
        "group": label,
        "trades": int(len(g)),
        "win_rate": float((g["net_pnl"] > 0).mean()),
        "avg_r": float(g["r_multiple"].mean()),
        "net_pnl": float(g["net_pnl"].sum()),
        "profit_factor": float(wins / abs(losses)) if losses != 0 else float("inf"),
    }


def breakdown(trades: pd.DataFrame, keys: pd.Series) -> list[dict]:
    """Per-group trade stats; `keys` is aligned to trades' index."""
    return [_group_row(label, g) for label, g in trades.groupby(keys, sort=True)]


def build_breakdowns(trades: pd.DataFrame) -> dict[str, list[dict]]:
    if trades.empty:
        return {}
    t = trades.copy()
    entry = pd.to_datetime(t["entry_time"], utc=True)
    midpoint = entry.min() + (entry.max() - entry.min()) / 2
    return {
        "by_direction": breakdown(t, t["direction"]),
        "by_session": breakdown(t, entry.dt.hour.map(session_bucket)),
        "by_weekday": breakdown(t, entry.dt.day_name()),
        "by_month": breakdown(t, entry.dt.strftime("%Y-%m")),
        "by_time_half": breakdown(
            t, pd.Series(np.where(entry < midpoint, "first half", "second half"), index=t.index)
        ),
        "by_exit_reason": breakdown(t, t["exit_reason"]),
    }


def verdict(stats: dict, net_profit: float, min_trades: int = MIN_TRADES_FOR_VERDICT) -> str:
    n = stats.get("trades", 0)
    if n < min_trades:
        return (
            f"NO VERDICT — only {n} trades, fewer than the {min_trades} needed before win rate / "
            "expectancy mean anything. Test on more history before trusting or rejecting this setup."
        )
    lo, hi = stats["expectancy_r_ci95_low"], stats["expectancy_r_ci95_high"]
    if hi < 0:
        return f"NEGATIVE EXPECTANCY — mean {stats['expectancy_r']:+.3f}R, 95% CI [{lo:+.3f}, {hi:+.3f}] is entirely below zero. Do not trade this."
    if lo > 0 and net_profit > 0:
        return (
            f"POSITIVE EXPECTANCY SUPPORTED — mean {stats['expectancy_r']:+.3f}R, 95% CI [{lo:+.3f}, {hi:+.3f}] "
            "is above zero after modeled costs. Next: demo-trade it; this is still one backtest, not a guarantee."
        )
    return (
        f"NO EDGE DEMONSTRATED — mean {stats['expectancy_r']:+.3f}R, but the 95% CI [{lo:+.3f}, {hi:+.3f}] "
        "includes zero: the result is indistinguishable from luck at this sample size."
    )
