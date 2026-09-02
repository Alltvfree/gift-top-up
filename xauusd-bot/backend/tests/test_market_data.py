"""Tests for the MarketDataService."""

from __future__ import annotations

import pytest

from app.core.models import Timeframe
from app.mt5.base import MT5AdapterError
from app.mt5.market_data import MarketDataService
from app.mt5.mock_adapter import MockMT5Adapter


@pytest.fixture()
def market():
    adapter = MockMT5Adapter(seed=11)
    adapter.connect()
    svc = MarketDataService(adapter)
    svc.resolve_symbol(["XAUUSD", "GOLD"])
    return svc


def test_resolve_sets_active_symbol(market):
    assert market.symbol == "XAUUSD"
    assert market.symbol_info.digits == 2


def test_requires_symbol_before_use():
    adapter = MockMT5Adapter()
    adapter.connect()
    svc = MarketDataService(adapter)
    with pytest.raises(MT5AdapterError):
        _ = svc.symbol


def test_resolve_unavailable_raises():
    adapter = MockMT5Adapter()
    adapter.connect()
    svc = MarketDataService(adapter)
    with pytest.raises(MT5AdapterError):
        svc.resolve_symbol(["NOPE"])


def test_ohlc_frame_shape(market):
    frame = market.get_ohlc_frame(Timeframe.H1, 120)
    assert len(frame) == 120
    assert list(frame.columns) == ["open", "high", "low", "close", "tick_volume"]
    assert frame.index.is_monotonic_increasing


def test_spread_points(market):
    spread = market.get_spread_points()
    assert spread is not None
    assert spread == pytest.approx(20.0, abs=1.0)
