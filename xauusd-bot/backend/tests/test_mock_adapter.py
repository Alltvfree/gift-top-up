"""Tests for the mock MT5 adapter and symbol resolution."""

from __future__ import annotations

import pytest

from app.core.models import SymbolInfo, Timeframe
from app.mt5.base import MT5AdapterError
from app.mt5.mock_adapter import MockMT5Adapter


@pytest.fixture()
def adapter():
    a = MockMT5Adapter(seed=7)
    a.connect()
    return a


def test_connect_and_account(adapter):
    assert adapter.is_connected()
    account = adapter.get_account_info()
    assert account.balance > 0
    assert account.currency == "USD"


def test_operations_require_connection():
    a = MockMT5Adapter()
    with pytest.raises(MT5AdapterError):
        a.get_candles("XAUUSD", Timeframe.M5, 10)


def test_candles_count_and_order(adapter):
    candles = adapter.get_candles("XAUUSD", Timeframe.M15, 100)
    assert len(candles) == 100
    # Oldest first (strictly increasing open times).
    times = [c.time for c in candles]
    assert times == sorted(times)
    # OHLC invariants.
    for c in candles:
        assert c.high >= c.open and c.high >= c.close
        assert c.low <= c.open and c.low <= c.close
        assert c.high >= c.low


def test_candles_are_deterministic():
    a1 = MockMT5Adapter(seed=123)
    a1.connect()
    a2 = MockMT5Adapter(seed=123)
    a2.connect()
    c1 = a1.get_candles("XAUUSD", Timeframe.H1, 50)
    c2 = a2.get_candles("XAUUSD", Timeframe.H1, 50)
    assert [c.close for c in c1] == [c.close for c in c2]


def test_tick_spread_positive(adapter):
    tick = adapter.get_tick("XAUUSD")
    assert tick is not None
    assert tick.ask > tick.bid
    info = adapter.get_symbol_info("XAUUSD")
    assert tick.spread_points(info) == pytest.approx(20.0, abs=1.0)


def test_resolve_symbol_alias_detection():
    # Broker only offers a suffixed name; resolver must find it.
    info = SymbolInfo(
        name="XAUUSDm",
        digits=2,
        point=0.01,
        tick_size=0.01,
        tick_value=1.0,
        volume_min=0.01,
        volume_max=50.0,
        volume_step=0.01,
    )
    a = MockMT5Adapter(symbols={"XAUUSDm": info})
    a.connect()
    resolved = a.resolve_symbol(["XAUUSD", "XAUUSDm", "GOLD"])
    assert resolved == "XAUUSDm"


def test_resolve_symbol_case_insensitive_fallback():
    info = SymbolInfo(
        name="Gold",
        digits=3,
        point=0.001,
        tick_size=0.001,
        tick_value=1.0,
        volume_min=0.01,
        volume_max=50.0,
        volume_step=0.01,
    )
    a = MockMT5Adapter(symbols={"Gold": info})
    a.connect()
    assert a.resolve_symbol(["GOLD"]) == "Gold"


def test_resolve_symbol_returns_none_when_absent(adapter):
    assert adapter.resolve_symbol(["NONEXISTENT"]) is None


def test_unusual_symbol_profile_digits():
    # Some brokers quote gold with 3 digits / 0.001 point — must be honored.
    info = SymbolInfo(
        name="XAUUSD.a",
        digits=3,
        point=0.001,
        tick_size=0.001,
        tick_value=1.0,
        volume_min=0.01,
        volume_max=50.0,
        volume_step=0.01,
    )
    a = MockMT5Adapter(symbols={"XAUUSD.a": info}, start_price=1950.0)
    a.connect()
    candles = a.get_candles("XAUUSD.a", Timeframe.M5, 20)
    # Rounded to 3 digits.
    assert all(round(c.close, 3) == c.close for c in candles)


def test_unknown_symbol_candles_raises(adapter):
    with pytest.raises(MT5AdapterError):
        adapter.get_candles("EURUSD", Timeframe.M5, 10)
