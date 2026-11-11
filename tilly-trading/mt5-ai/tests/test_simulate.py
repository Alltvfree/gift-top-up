import numpy as np
import pandas as pd
import pytest

from mt5_ai.simulate import simulate_plan


def _bars(n=600, vol=0.002, seed=3):
    rng = np.random.default_rng(seed)
    close = 5000 * np.cumprod(1 + rng.normal(0, vol, n))
    open_ = np.roll(close, 1)
    open_[0] = 5000
    return pd.DataFrame(
        {
            "time": pd.date_range("2024-01-01", periods=n, freq="15min", tz="UTC"),
            "open": open_,
            "high": np.maximum(open_, close) * (1 + np.abs(rng.normal(0, vol / 3, n))),
            "low": np.minimum(open_, close) * (1 - np.abs(rng.normal(0, vol / 3, n))),
            "close": close,
        }
    )


def run(**kw):
    args = dict(bars=_bars(), side="BUY", entry=5000.0, sl=4990.0, tp=5020.0, horizon_bars=32, simulations=4000, seed=1)
    args.update(kw)
    return simulate_plan(**args)


def test_outcomes_partition_all_simulations():
    r = run()
    assert r["p_target_first"] + r["p_stop_first"] + r["p_neither"] == pytest.approx(1.0)
    assert r["simulations"] == 4000 and r["reward_risk"] == pytest.approx(2.0)


def test_same_seed_same_answer_different_seed_differs():
    assert run() == run()
    assert run(seed=2)["p_target_first"] != run()["p_target_first"]


def test_a_farther_target_is_reached_less_often():
    near, far = run(tp=5010.0), run(tp=5060.0)
    assert far["p_target_first"] < near["p_target_first"]


def test_a_tighter_stop_is_hit_more_often():
    assert run(sl=4996.0)["p_stop_first"] > run(sl=4975.0)["p_stop_first"]


def test_no_drift_replay_cannot_manufacture_an_edge_and_spread_makes_it_worse():
    r = run(spread_price=0.0, simulations=20000)
    assert abs(r["expected_r_before_spread"]) < 0.15, "symmetric random bars should be near zero expectancy"
    assert run(spread_price=1.0)["expected_r_after_spread"] < r["expected_r_after_spread"]


def test_short_side_mirrors_the_long_side_statistically():
    long_r = run(simulations=20000)
    short_r = run(side="SELL", entry=5000.0, sl=5010.0, tp=4980.0, simulations=20000)
    assert abs(long_r["p_target_first"] - short_r["p_target_first"]) < 0.04


def test_a_bar_spanning_both_levels_counts_as_the_stop():
    flat = pd.DataFrame(
        {"time": pd.date_range("2024-01-01", periods=100, freq="15min", tz="UTC"),
         "open": 100.0, "high": 110.0, "low": 90.0, "close": 100.0}
    )  # every bar swings +/-10%: both levels are always inside the first bar
    r = simulate_plan(flat, side="BUY", entry=100.0, sl=95.0, tp=105.0, horizon_bars=3, simulations=500, seed=1)
    assert r["p_stop_first"] == 1.0 and r["p_target_first"] == 0.0


def test_unreachable_levels_time_out():
    r = run(sl=4000.0, tp=6000.0, horizon_bars=4)
    assert r["p_neither"] == 1.0 and r["median_bars_to_resolve"] is None


def test_input_validation():
    with pytest.raises(ValueError, match="straddle"):
        run(sl=5010.0)
    with pytest.raises(ValueError, match="BUY or SELL"):
        run(side="HOLD")
    with pytest.raises(ValueError, match="50 history"):
        run(bars=_bars(n=30))
    with pytest.raises(ValueError):
        run(simulations=10)


def test_the_samples_own_trend_cannot_flatter_one_side():
    n = 600
    rising = pd.DataFrame(  # a steadily rising history: +0.05% every bar, tiny wicks
        {"time": pd.date_range("2024-01-01", periods=n, freq="15min", tz="UTC"),
         "open": 5000 * 1.0005 ** np.arange(n), "close": 5000 * 1.0005 ** (np.arange(n) + 1)}
    )
    rising["high"], rising["low"] = rising["close"] * 1.0003, rising["open"] * 0.9997
    kw = dict(entry=5000.0, horizon_bars=32, simulations=6000, seed=1)
    buy = simulate_plan(rising, side="BUY", sl=4990.0, tp=5020.0, **kw)
    sell = simulate_plan(rising, side="SELL", sl=5010.0, tp=4980.0, **kw)
    assert abs(buy["p_target_first"] - sell["p_target_first"]) < 0.05
    drifting = simulate_plan(rising, side="BUY", sl=4990.0, tp=5020.0, direction_neutral=False, **kw)
    assert drifting["p_target_first"] > buy["p_target_first"] + 0.2, "without the mirror bars the history's trend would have flattered the long"
