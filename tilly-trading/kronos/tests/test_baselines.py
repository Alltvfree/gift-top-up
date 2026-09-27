import numpy as np

from backtest.baselines import (
    always_buy_baseline, always_sell_baseline, no_trade_baseline,
    random_baseline, sma_crossover_baseline,
)
from conftest import make_synthetic_ohlc


def test_always_buy_and_sell_and_no_trade_are_constant():
    df = make_synthetic_ohlc(50)
    assert (always_buy_baseline(df) == 1.0).all()
    assert (always_sell_baseline(df) == 0.0).all()
    assert (no_trade_baseline(df) == 0.5).all()


def test_random_baseline_is_bounded_and_not_constant():
    df = make_synthetic_ohlc(200)
    rng = np.random.default_rng(0)
    values = random_baseline(df, rng)
    assert values.between(0, 1).all()
    assert values.nunique() > 1


def test_sma_crossover_uses_only_past_bars():
    df = make_synthetic_ohlc(200)
    full = sma_crossover_baseline(df, fast=5, slow=20)
    truncated = sma_crossover_baseline(df.iloc[:100].copy(), fast=5, slow=20)
    row = 80
    a, b = full.iloc[row], truncated.iloc[row]
    if not (np.isnan(a) and np.isnan(b)):
        assert a == b, "sma_crossover_baseline must not change past values when future bars are added"
