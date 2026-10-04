import pandas as pd

from bars import closed_bars_only


def _bars():
    return pd.DataFrame({"time": pd.date_range("2024-01-01 10:00", periods=4, freq="15min", tz="UTC"), "close": [1, 2, 3, 4]})


def test_the_forming_bar_is_dropped():
    # 10:00, 10:15, 10:30, 10:45 bars; it is 10:50, so the 10:45 bar (closes 11:00) is still forming.
    out = closed_bars_only(_bars(), 15, pd.Timestamp("2024-01-01 10:50", tz="UTC"))
    assert out["close"].tolist() == [1, 2, 3]


def test_a_bar_counts_as_closed_the_instant_its_duration_has_elapsed():
    out = closed_bars_only(_bars(), 15, pd.Timestamp("2024-01-01 11:00", tz="UTC"))
    assert out["close"].tolist() == [1, 2, 3, 4]


def test_stale_clock_keeps_only_what_had_closed_by_then():
    out = closed_bars_only(_bars(), 15, pd.Timestamp("2024-01-01 10:15", tz="UTC"))
    assert out["close"].tolist() == [1]
    assert closed_bars_only(_bars(), 15, pd.Timestamp("2024-01-01 09:00", tz="UTC")).empty
    assert list(closed_bars_only(_bars(), 15, pd.Timestamp("2024-01-01 11:00", tz="UTC")).index) == [0, 1, 2, 3]
