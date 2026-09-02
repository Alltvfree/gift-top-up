"""Tests for the simulated PaperBroker."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.core.models import OrderSide, SymbolInfo, Tick
from app.execution.broker import OrderRequest
from app.execution.paper_broker import PaperBroker

XAUUSD = SymbolInfo(
    name="XAUUSD", digits=2, point=0.01, tick_size=0.01, tick_value=1.0,
    volume_min=0.01, volume_max=100.0, volume_step=0.01,
)


def tick(bid, ask, t=None):
    return Tick("XAUUSD", t or datetime(2026, 1, 1, tzinfo=timezone.utc), bid, ask)


def buy_request(signal_id="sig-1", volume=0.1, sl=1990.0, tp=2020.0, price=2000.0):
    return OrderRequest(signal_id, "XAUUSD", OrderSide.BUY, volume, sl, tp, price)


def test_submit_fills_and_tracks_position():
    b = PaperBroker(XAUUSD, starting_balance=10_000)
    b.mark_to_market(tick(1999.9, 2000.1))
    res = b.submit_order(buy_request())
    assert res.executed
    assert res.ticket is not None
    positions = b.get_positions("XAUUSD")
    assert len(positions) == 1
    assert positions[0].side is OrderSide.BUY


def test_idempotent_on_signal_id():
    b = PaperBroker(XAUUSD)
    b.mark_to_market(tick(1999.9, 2000.1))
    first = b.submit_order(buy_request("dup"))
    second = b.submit_order(buy_request("dup"))
    assert first.executed
    assert second.duplicate
    assert second.ticket == first.ticket
    assert len(b.get_positions()) == 1  # only ONE position


def test_take_profit_auto_close_with_profit():
    b = PaperBroker(XAUUSD, starting_balance=10_000)
    b.mark_to_market(tick(1999.9, 2000.1))
    b.submit_order(buy_request(sl=1990.0, tp=2010.0, price=2000.0))
    # Price rallies through TP.
    closes = b.mark_to_market(tick(2010.5, 2010.7))
    assert len(closes) == 1
    assert closes[0].profit > 0
    assert not b.get_positions()
    assert b.get_account().balance > 10_000


def test_stop_loss_auto_close_with_loss():
    b = PaperBroker(XAUUSD, starting_balance=10_000)
    b.mark_to_market(tick(1999.9, 2000.1))
    b.submit_order(buy_request(sl=1995.0, tp=2020.0, price=2000.0))
    closes = b.mark_to_market(tick(1994.5, 1994.7))
    assert len(closes) == 1
    assert closes[0].profit < 0
    assert b.get_account().balance < 10_000


def test_pnl_magnitude_is_correct():
    # 0.1 lot, 10.0 price move, tick_value 1.0, tick_size 0.01 -> $100 profit.
    b = PaperBroker(XAUUSD, starting_balance=10_000)
    b.mark_to_market(tick(1999.9, 2000.1))
    b.submit_order(buy_request(volume=0.1, sl=1980.0, tp=2010.0, price=2000.0))
    closes = b.mark_to_market(tick(2010.0, 2010.2))
    # exit at tp=2010 -> 10.0 move -> 1000 ticks * 1.0 * 0.1 = $100.
    assert closes[0].profit == pytest.approx(100.0, abs=0.5)


def test_slippage_worsens_fill():
    b = PaperBroker(XAUUSD, slippage_points=10.0)  # 10 points = 0.10 price
    b.mark_to_market(tick(1999.9, 2000.1))
    res = b.submit_order(buy_request(price=2000.0))
    assert res.fill_price == pytest.approx(2000.10)  # buy filled higher


def test_commission_reduces_balance():
    b = PaperBroker(XAUUSD, starting_balance=10_000, commission_per_lot=7.0)
    b.mark_to_market(tick(1999.9, 2000.1))
    b.submit_order(buy_request(volume=1.0))
    assert b.get_account().balance == pytest.approx(10_000 - 7.0)


def test_modify_position_updates_sl():
    b = PaperBroker(XAUUSD)
    b.mark_to_market(tick(1999.9, 2000.1))
    res = b.submit_order(buy_request())
    assert b.modify_position(res.ticket, stop_loss=1995.0)
    assert b.get_positions()[0].sl == pytest.approx(1995.0)
