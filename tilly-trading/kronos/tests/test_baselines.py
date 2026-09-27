import numpy as np

from backtest.baselines import (
    always_buy_baseline, always_sell_baseline, no_trade_baseline,
    random_baseline, sma_crossover_baseline,
)
from conftest import make_synthetic_ohlc


def test_always_buy_and_sell_and_no_trade_are_constant():
    df = make_synthetic_ohlc(50)
    buy_p, sell_p = always_buy_baseline(df)
    assert (buy_p == 1.0).all() and (sell_p == 0.0).all()
    buy_p, sell_p = always_sell_baseline(df)
    assert (buy_p == 0.0).all() and (sell_p == 1.0).all()
    buy_p, sell_p = no_trade_baseline(df)
    assert (buy_p == 0.0).all() and (sell_p == 0.0).all()


def test_random_baseline_is_bounded_and_not_constant():
    df = make_synthetic_ohlc(200)
    rng = np.random.default_rng(0)
    buy_p, sell_p = random_baseline(df, rng)
    assert buy_p.between(0, 1).all() and sell_p.between(0, 1).all()
    assert buy_p.nunique() > 1 and sell_p.nunique() > 1


def test_sma_crossover_uses_only_past_bars():
    df = make_synthetic_ohlc(200)
    full_buy, full_sell = sma_crossover_baseline(df, fast=5, slow=20)
    trunc_buy, trunc_sell = sma_crossover_baseline(df.iloc[:100].copy(), fast=5, slow=20)
    row = 80
    for full, trunc in ((full_buy, trunc_buy), (full_sell, trunc_sell)):
        a, b = full.iloc[row], trunc.iloc[row]
        if not (np.isnan(a) and np.isnan(b)):
            assert a == b, "sma_crossover_baseline must not change past values when future bars are added"


def test_sma_crossover_buy_and_sell_are_mutually_exclusive():
    df = make_synthetic_ohlc(200)
    buy_p, sell_p = sma_crossover_baseline(df, fast=5, slow=20)
    both_high = (buy_p == 1.0) & (sell_p == 1.0)
    assert not both_high.any()
