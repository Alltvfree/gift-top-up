"""labels.label_tp_before_sl against hand-constructed, known price paths —
ported from the earlier ad-hoc scratch test (never previously committed)."""
import numpy as np
import pandas as pd

from labels import label_tp_before_sl


def test_buy_labeled_win_when_tp_hit_first():
    n = 10
    times = pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC")
    close = np.array([100, 101, 104, 103, 102, 101, 100, 99, 98, 97], dtype=float)
    high = close + 0.5
    low = close - 0.5
    high[2] = 104.5  # bar 2 clearly touches TP=103 (BUY entry@100, tp=+3)
    open_ = np.roll(close, 1)
    open_[0] = 100
    df = pd.DataFrame({"time": times, "open": open_, "high": high, "low": low, "close": close})
    labels = label_tp_before_sl(df, tp_distance=3.0, sl_distance=2.0, side="BUY", max_bars_forward=5)
    assert labels.iloc[0] == 1.0


def test_sell_labeled_loss_when_sl_hit_first():
    n = 10
    times = pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC")
    close = np.array([100, 100.5, 102.5, 101, 99, 97, 96, 95, 94, 93], dtype=float)
    high = close + 0.3
    low = close - 0.3
    open_ = np.roll(close, 1)
    open_[0] = 100
    df = pd.DataFrame({"time": times, "open": open_, "high": high, "low": low, "close": close})
    labels = label_tp_before_sl(df, tp_distance=3.0, sl_distance=2.0, side="SELL", max_bars_forward=5)
    assert labels.iloc[0] == 0.0


def test_unresolved_trailing_trade_is_nan_not_guessed():
    n = 10
    times = pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC")
    close = np.array([100, 101, 104, 103, 102, 101, 100, 99, 98, 97], dtype=float)
    high = close + 0.5
    low = close - 0.5
    high[2] = 104.5
    open_ = np.roll(close, 1)
    open_[0] = 100
    df = pd.DataFrame({"time": times, "open": open_, "high": high, "low": low, "close": close})
    labels = label_tp_before_sl(df, tp_distance=3.0, sl_distance=2.0, side="BUY", max_bars_forward=5)
    assert pd.isna(labels.iloc[-1])


def test_both_tp_and_sl_touched_same_bar_scores_a_loss():
    n = 5
    times = pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC")
    close = np.array([100, 100, 100, 100, 100], dtype=float)
    high = np.array([100, 105, 100, 100, 100], dtype=float)  # bar 1 spans both TP(103) and SL(98)
    low = np.array([100, 97, 100, 100, 100], dtype=float)
    open_ = close.copy()
    df = pd.DataFrame({"time": times, "open": open_, "high": high, "low": low, "close": close})
    labels = label_tp_before_sl(df, tp_distance=3.0, sl_distance=2.0, side="BUY", max_bars_forward=4)
    assert labels.iloc[0] == 0.0, "ambiguous same-bar TP+SL must score conservatively as a loss"


def test_invalid_side_and_distances_rejected():
    df = pd.DataFrame({"time": [pd.Timestamp("2024-01-01", tz="UTC")], "open": [1], "high": [1], "low": [1], "close": [1]})
    try:
        label_tp_before_sl(df, 1.0, 1.0, side="HOLD")
        assert False
    except ValueError:
        pass
    try:
        label_tp_before_sl(df, -1.0, 1.0, side="BUY")
        assert False
    except ValueError:
        pass
