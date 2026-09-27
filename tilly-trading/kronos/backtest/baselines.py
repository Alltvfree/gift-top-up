"""Baseline strategies (Phase 14) — to answer "does the model add value
over trivial alternatives," not to be optimized themselves. Each one
returns a `predicted_probability` series in the same [0,1] shape the real
model's predictions have, so simulator.run_simulation() can run every
baseline through the exact same execution/cost engine as the model — an
apples-to-apples comparison is the whole point.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def random_baseline(test_df: pd.DataFrame, rng: np.random.Generator) -> pd.Series:
    return pd.Series(rng.uniform(0.0, 1.0, len(test_df)), index=test_df.index)


def always_buy_baseline(test_df: pd.DataFrame) -> pd.Series:
    return pd.Series(1.0, index=test_df.index)


def always_sell_baseline(test_df: pd.DataFrame) -> pd.Series:
    return pd.Series(0.0, index=test_df.index)


def no_trade_baseline(test_df: pd.DataFrame) -> pd.Series:
    return pd.Series(0.5, index=test_df.index)


def sma_crossover_baseline(test_df: pd.DataFrame, fast: int = 10, slow: int = 50) -> pd.Series:
    """A simple moving-average crossover, not tuned: fast > slow -> a BUY-
    leaning probability (1.0), fast < slow -> SELL-leaning (0.0), flat/warm-
    up period -> NO_TRADE (0.5). Uses only past bars (rolling means), so
    it's as lookahead-safe as any real feature."""
    close = test_df["close"]
    fast_ma = close.rolling(fast, min_periods=fast).mean()
    slow_ma = close.rolling(slow, min_periods=slow).mean()
    out = pd.Series(0.5, index=test_df.index)
    out[fast_ma > slow_ma] = 1.0
    out[fast_ma < slow_ma] = 0.0
    out[fast_ma.isna() | slow_ma.isna()] = np.nan
    return out


BASELINES = {
    "random": random_baseline,
    "always_buy": always_buy_baseline,
    "always_sell": always_sell_baseline,
    "no_trade": no_trade_baseline,
    "sma_crossover": sma_crossover_baseline,
}
