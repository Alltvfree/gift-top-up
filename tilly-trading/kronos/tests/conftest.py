"""Test setup shared by every test in this directory.

Stubs the MetaTrader5 module before anything imports mt5_data.py — same
pattern the project's earlier synthetic-data tests used (see the scratchpad
test files referenced in kronos/README.md's testing note). No real MT5
terminal exists in CI/dev, and none of backtest/'s own logic needs one —
only mt5_data.py's actual download functions do, and those are never
called in these tests.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

KRONOS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KRONOS_DIR))

if "MetaTrader5" not in sys.modules:
    fake_mt5 = types.ModuleType("MetaTrader5")
    for name in ["TIMEFRAME_M1", "TIMEFRAME_M5", "TIMEFRAME_M15", "TIMEFRAME_H1", "TIMEFRAME_H4"]:
        setattr(fake_mt5, name, 0)
    sys.modules["MetaTrader5"] = fake_mt5

if "supabase" not in sys.modules:
    # publish_signal.py imports this at module level purely to talk to a
    # real Supabase project — infer.py imports publish_signal.py in turn.
    # No test here ever calls publish_signal(), so a stub Client is enough
    # to let infer.py import cleanly without a real `supabase` install.
    fake_supabase = types.ModuleType("supabase")

    class _FakeClient:
        def table(self, *args, **kwargs):
            raise RuntimeError("Stub supabase.Client — tests must never call this for real.")

    def _fake_create_client(*args, **kwargs):
        return _FakeClient()

    fake_supabase.Client = _FakeClient
    fake_supabase.create_client = _fake_create_client
    sys.modules["supabase"] = fake_supabase

import numpy as np
import pandas as pd


def make_synthetic_ohlc(n, freq="5min", start_price=2000.0, start_time="2024-01-01", seed=42, spread_points=20.0):
    """A random-walk OHLC frame shaped like mt5_data.download_history's
    output, including the `spread` column real MT5 history carries."""
    rng = np.random.default_rng(seed)
    times = pd.date_range(start_time, periods=n, freq=freq, tz="UTC")
    rets = rng.normal(0, 0.0004, n)
    close = start_price * np.cumprod(1 + rets)
    open_ = np.roll(close, 1)
    open_[0] = start_price
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.0002, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.0002, n)))
    tick_volume = rng.integers(10, 500, n)
    spread = np.full(n, spread_points)
    return pd.DataFrame(
        {"time": times, "open": open_, "high": high, "low": low, "close": close,
         "tick_volume": tick_volume, "spread": spread}
    )
