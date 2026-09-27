import pandas as pd

from backtest.windows import generate_windows


def test_windows_are_strictly_chronological_and_nonoverlapping():
    start = pd.Timestamp("2024-01-01", tz="UTC")
    end = pd.Timestamp("2024-06-01", tz="UTC")
    windows = generate_windows(start, end, train_days=30, validation_days=7, test_days=7, step_days=7)
    assert len(windows) > 0
    for w in windows:
        assert w.train_start < w.train_end <= w.val_start < w.val_end <= w.test_start < w.test_end
        assert w.test_end <= end


def test_embargo_creates_a_real_gap():
    start = pd.Timestamp("2024-01-01", tz="UTC")
    end = pd.Timestamp("2024-06-01", tz="UTC")
    windows = generate_windows(
        start, end, train_days=30, validation_days=7, test_days=7, step_days=7, embargo_minutes=120
    )
    w = windows[0]
    assert w.val_start - w.train_end == pd.Timedelta(minutes=120)
    assert w.test_start - w.val_end == pd.Timedelta(minutes=120)


def test_windows_roll_forward_by_step_days():
    start = pd.Timestamp("2024-01-01", tz="UTC")
    end = pd.Timestamp("2024-12-01", tz="UTC")
    windows = generate_windows(start, end, train_days=30, validation_days=7, test_days=7, step_days=10)
    assert len(windows) >= 2
    assert windows[1].train_start - windows[0].train_start == pd.Timedelta(days=10)


def test_insufficient_history_returns_empty_list_not_error():
    start = pd.Timestamp("2024-01-01", tz="UTC")
    end = pd.Timestamp("2024-01-05", tz="UTC")  # far too short for a 30/7/7 window
    windows = generate_windows(start, end, train_days=30, validation_days=7, test_days=7, step_days=7)
    assert windows == []


def test_nonpositive_arguments_rejected():
    start = pd.Timestamp("2024-01-01", tz="UTC")
    end = pd.Timestamp("2024-06-01", tz="UTC")
    try:
        generate_windows(start, end, train_days=0, validation_days=7, test_days=7, step_days=7)
        assert False, "expected ValueError"
    except ValueError:
        pass
