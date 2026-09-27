import pandas as pd

from backtest.account import Account


def test_balance_only_changes_on_realize():
    acct = Account(10000.0)
    acct.mark(pd.Timestamp("2024-01-01", tz="UTC"), unrealized_pnl=500.0, open_positions=1)
    assert acct.balance == 10000.0, "unrealized P&L must not touch balance"
    acct.realize(-200.0)
    assert acct.balance == 9800.0


def test_equity_includes_unrealized_pnl():
    acct = Account(10000.0)
    point = acct.mark(pd.Timestamp("2024-01-01", tz="UTC"), unrealized_pnl=250.0, open_positions=1)
    assert point.equity == 10250.0
    assert point.balance == 10000.0


def test_drawdown_tracks_peak_equity():
    acct = Account(10000.0)
    t = pd.Timestamp("2024-01-01", tz="UTC")
    acct.mark(t, 1000.0, 1)  # equity 11000, new peak
    p2 = acct.mark(t + pd.Timedelta(minutes=5), -500.0, 1)  # equity 9500
    assert p2.drawdown == 11000.0 - 9500.0
    assert abs(p2.drawdown_percent - (1500.0 / 11000.0 * 100.0)) < 1e-9
    assert acct.max_drawdown == p2.drawdown


def test_to_frame_round_trips_curve():
    acct = Account(5000.0)
    for i in range(3):
        acct.mark(pd.Timestamp("2024-01-01", tz="UTC") + pd.Timedelta(minutes=i), 0.0, 0)
    frame = acct.to_frame()
    assert len(frame) == 3
    assert list(frame.columns) == ["time", "balance", "equity", "drawdown", "drawdown_percent", "open_positions"]


def test_nonpositive_initial_balance_rejected():
    try:
        Account(0.0)
        assert False, "expected ValueError"
    except ValueError:
        pass
