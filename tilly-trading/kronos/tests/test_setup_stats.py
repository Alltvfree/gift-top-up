"""setup_stats.py — R-multiples, bootstrap CI, breakdowns and the verdict
gate that refuses to call a thin sample."""
import numpy as np
import pandas as pd
import pytest

from backtest.setup_stats import (
    add_r_multiple, bootstrap_mean_ci, build_breakdowns, edge_stats, session_bucket, verdict,
)
from backtest.symbols import get_symbol_spec

spec = get_symbol_spec("XAUUSDm")  # contract_size 100


def _trades(rows):
    return pd.DataFrame(rows)


def test_r_multiple_is_pnl_over_money_risked_with_costs_inside():
    t = _trades(
        [
            {"entry_price": 100.0, "stop_loss": 98.0, "lots": 0.5, "net_pnl": 200.0},    # risk 2*100*0.5=100 -> +2R
            {"entry_price": 100.0, "stop_loss": 98.0, "lots": 0.5, "net_pnl": -100.0},   # -1R
            {"entry_price": 100.0, "stop_loss": 102.0, "lots": 0.5, "net_pnl": -110.0},  # short stopped out, costs -> -1.1R
        ]
    )
    r = add_r_multiple(t, spec)["r_multiple"].tolist()
    assert r == pytest.approx([2.0, -1.0, -1.1])


def test_bootstrap_ci_is_deterministic_brackets_the_mean_and_tightens_with_more_data():
    rng = np.random.default_rng(0)
    small = rng.normal(0.1, 1.0, 100)
    big = rng.normal(0.1, 1.0, 2000)
    lo, hi = bootstrap_mean_ci(small)
    assert (lo, hi) == bootstrap_mean_ci(small)
    assert lo < small.mean() < hi
    lo_b, hi_b = bootstrap_mean_ci(big)
    assert (hi_b - lo_b) < (hi - lo)
    assert all(np.isnan(bootstrap_mean_ci(np.array([1.0]))))


def test_edge_stats_on_a_known_sample():
    t = pd.DataFrame({"r_multiple": [2.0, 2.0, -1.0, -1.0, -1.0]})
    s = edge_stats(t)
    assert s["trades"] == 5
    assert s["expectancy_r"] == pytest.approx(0.2)
    assert s["win_rate"] == pytest.approx(0.4)
    assert s["payoff_ratio"] == pytest.approx(2.0)
    assert s["breakeven_win_rate"] == pytest.approx(1 / 3)
    assert s["total_r"] == pytest.approx(1.0)
    assert edge_stats(pd.DataFrame({"r_multiple": []})) == {"trades": 0}


@pytest.mark.parametrize(
    "hour, bucket",
    [(0, "asian (00-07 UTC)"), (6, "asian (00-07 UTC)"), (7, "london (07-12 UTC)"), (11, "london (07-12 UTC)"),
     (12, "london/new_york overlap (12-16 UTC)"), (15, "london/new_york overlap (12-16 UTC)"),
     (16, "new_york (16-21 UTC)"), (20, "new_york (16-21 UTC)"), (21, "late (21-24 UTC)"), (23, "late (21-24 UTC)")],
)
def test_session_buckets(hour, bucket):
    assert session_bucket(hour) == bucket


def test_breakdowns_partition_the_trades():
    entry = pd.to_datetime(
        ["2024-01-02 08:00", "2024-01-02 13:00", "2024-01-03 17:00", "2024-02-05 09:00"], utc=True
    )
    t = pd.DataFrame(
        {
            "entry_time": entry, "direction": ["BUY", "SELL", "BUY", "SELL"],
            "net_pnl": [200.0, -100.0, -100.0, 200.0], "r_multiple": [2.0, -1.0, -1.0, 2.0],
            "exit_reason": ["TP", "SL", "SL", "TP"],
        }
    )
    b = build_breakdowns(t)
    for name, rows in b.items():
        assert sum(r["trades"] for r in rows) == 4, name
    by_session = {r["group"]: r for r in b["by_session"]}
    assert by_session["london (07-12 UTC)"]["trades"] == 2
    assert by_session["london/new_york overlap (12-16 UTC)"]["win_rate"] == 0.0
    assert [r["group"] for r in b["by_month"]] == ["2024-01", "2024-02"]
    assert {r["group"] for r in b["by_time_half"]} == {"first half", "second half"}
    assert build_breakdowns(t.iloc[0:0]) == {}


def _stats(n, mean, lo, hi):
    return {"trades": n, "expectancy_r": mean, "expectancy_r_ci95_low": lo, "expectancy_r_ci95_high": hi}


def test_verdict_refuses_a_thin_sample_whatever_the_numbers_look_like():
    v = verdict(_stats(499, 0.9, 0.5, 1.3), net_profit=5000.0)
    assert v.startswith("NO VERDICT") and "499" in v


def test_verdict_covers_negative_no_edge_and_positive():
    assert verdict(_stats(800, -0.2, -0.35, -0.05), -3000.0).startswith("NEGATIVE EXPECTANCY")
    assert verdict(_stats(800, 0.05, -0.08, 0.18), 800.0).startswith("NO EDGE DEMONSTRATED")
    assert verdict(_stats(800, 0.15, 0.03, 0.27), 2500.0).startswith("POSITIVE EXPECTANCY SUPPORTED")
    # CI above zero but the account still lost money net: don't call it a win.
    assert verdict(_stats(800, 0.15, 0.03, 0.27), -10.0).startswith("NO EDGE DEMONSTRATED")
    assert verdict(_stats(100, 0.1, 0.0, 0.2), 1.0, min_trades=50).startswith("NO EDGE")
