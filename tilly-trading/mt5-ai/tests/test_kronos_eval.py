import numpy as np
import pytest

from mt5_ai.kronos_eval import make_windows, score, verdict, wilson_interval


def test_windows_are_chronological_and_their_truth_segments_never_overlap():
    w = make_windows(n_bars=1000, lookback=400, pred_len=8, windows=10)
    assert len(w) == 10 and w[-1][2] == 1000
    assert all(a[1] <= b[0] + 400 for a, b in zip(w, w[1:]))
    truths = [(s, e) for _, s, e in w]
    assert all(t1[1] <= t2[0] for t1, t2 in zip(truths, truths[1:]))
    assert all(split - start == 400 and end - split == 8 for start, split, end in w)


def test_windows_stop_when_history_runs_out():
    assert len(make_windows(n_bars=420, lookback=400, pred_len=8, windows=50)) == 2


def test_wilson_interval_behaves():
    lo, hi = wilson_interval(50, 100)
    assert lo < 0.5 < hi and hi - lo < 0.21
    assert wilson_interval(100, 100)[1] == pytest.approx(1.0) and wilson_interval(100, 100)[0] > 0.95
    assert np.isnan(wilson_interval(0, 0)[0])


def test_random_forecasts_show_no_skill():
    rng = np.random.default_rng(0)
    n = 400
    actual, pred = rng.normal(0, 1, n), rng.normal(0, 1, n)
    s = score(pred, actual, rng.uniform(0, 1, n))
    assert s["verdict"].startswith("NO DEMONSTRATED SKILL")
    assert s["hit_rate_ci95"][0] < 0.5 < s["hit_rate_ci95"][1]


def test_a_forecast_that_follows_the_future_is_credited():
    rng = np.random.default_rng(1)
    actual = rng.normal(0, 1, 300)
    pred = actual * 0.5 + rng.normal(0, 0.5, 300)
    s = score(pred, actual, (pred > 0).astype(float))
    assert s["verdict"].startswith("SOME DIRECTIONAL SKILL") and s["skill_vs_naive"] > 0
    assert s["strong_up_lean"]["hit_rate"] > 0.6


def test_a_forecast_that_points_the_wrong_way_is_called_out():
    rng = np.random.default_rng(2)
    actual = rng.normal(0, 1, 300)
    s = score(-actual + rng.normal(0, 0.3, 300), actual, rng.uniform(0, 1, 300))
    assert s["verdict"].startswith("WORSE THAN A COIN")


def test_too_few_windows_refuses_to_conclude():
    rng = np.random.default_rng(3)
    s = score(rng.normal(0, 1, 12), rng.normal(0, 1, 12), rng.uniform(0, 1, 12))
    assert s["verdict"].startswith("TOO FEW WINDOWS")
    assert verdict({"windows": 5, "hit_rate_ci95": [0.9, 1.0]}).startswith("TOO FEW")


def test_zero_moves_are_excluded_not_counted_as_misses():
    s = score([1.0, -1.0, 1.0], [0.0, -0.5, 0.0], [0.9, 0.1, 0.9])
    assert s["windows"] == 1 and s["directional_hit_rate"] == 1.0
    assert score([1.0], [0.0], [0.5])["verdict"] == "NO DATA"
