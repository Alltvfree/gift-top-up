"""The adapter against the REAL rule-based setup code in tilly-trading/kronos
(not a copy): same rows in, same answer out."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from mt5_ai.setup_adapter import TrendPullbackAdapter

KRONOS_DIR = Path(__file__).resolve().parents[2] / "kronos"


def _market(n=3000, seed=5):
    t = pd.date_range("2024-01-01", periods=n, freq="15min", tz="UTC")
    rng = np.random.default_rng(seed)
    close = 4000 * np.cumprod(1 + rng.normal(0, 0.0004, n))
    open_ = np.roll(close, 1)
    open_[0] = 4000
    base = pd.DataFrame({"time": t, "open": open_, "high": np.maximum(open_, close) * 1.0002,
                         "low": np.minimum(open_, close) * 0.9998, "close": close,
                         "tick_volume": 100, "spread": 25.0})
    higher = (base.set_index("time").resample("1h")
              .agg({"open": "first", "high": "max", "low": "min", "close": "last", "tick_volume": "sum", "spread": "max"})
              .dropna().reset_index())
    return base, higher


def test_status_reports_the_last_closed_bar_in_plain_terms():
    base, higher = _market()
    a = TrendPullbackAdapter(str(KRONOS_DIR))
    now = base["time"].iloc[-1] + pd.Timedelta(minutes=15)
    s = a.status(base, higher, symbol="XAUUSD", timeframe="M15", higher_timeframe="H1", now=now, point=0.01)
    assert s["bar_time"] == base["time"].iloc[-1].isoformat()
    assert s["signal"] in ("BUY", "SELL", "NONE") and s["higher_timeframe_structure"] in ("up", "down", "neutral")
    assert s["atr"] > 0 and "EMA20" in s["rules"]


def test_a_forming_bar_is_ignored():
    base, higher = _market()
    a = TrendPullbackAdapter(str(KRONOS_DIR))
    s = a.status(base, higher, symbol="XAUUSD", timeframe="M15", higher_timeframe="H1",
                 now=base["time"].iloc[-1] + pd.Timedelta(minutes=5), point=0.01)
    assert s["bar_time"] == base["time"].iloc[-2].isoformat()


def test_signals_carry_a_stop_a_target_and_the_backtest_warning():
    base, higher = _market()
    a = TrendPullbackAdapter(str(KRONOS_DIR))
    fired = None
    for k in range(1500, len(base), 11):  # walk the history until the rules fire on some closed bar
        cut = base.iloc[:k]
        s = a.status(cut, higher[higher["time"] < cut["time"].iloc[-1]], symbol="XAUUSD", timeframe="M15",
                     higher_timeframe="H1", now=cut["time"].iloc[-1] + pd.Timedelta(minutes=15), point=0.01)
        if s["signal"] != "NONE":
            fired = s
            break
    assert fired is not None, "synthetic data should trigger the setup somewhere"
    assert fired["reward_risk"] == 2.0 and fired["tp_distance"] == pytest.approx(2 * fired["sl_distance"])
    assert "NOT been shown" in fired["backtest_warning"]
    sign = 1 if fired["signal"] == "BUY" else -1
    assert fired["sl_price_from_close"] == pytest.approx(fired["close"] - sign * fired["sl_distance"])


def test_a_wrong_folder_gives_a_clear_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="tilly-trading/kronos"):
        TrendPullbackAdapter(str(tmp_path))
