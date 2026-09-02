"""Tests for break-even and trailing-stop management."""

from __future__ import annotations

import pytest

from app.core.config import BreakEvenConfig, TrailingStopConfig
from app.core.models import OrderSide, SymbolInfo
from app.execution.position_manager import (
    break_even_stop,
    manage_stop,
    trailing_stop,
)

XAUUSD = SymbolInfo(
    name="XAUUSD", digits=2, point=0.01, tick_size=0.01, tick_value=1.0,
    volume_min=0.01, volume_max=100.0, volume_step=0.01,
)


def test_break_even_triggers_at_1r():
    cfg = BreakEvenConfig(enabled=True, trigger_r=1.0, buffer_points=5)
    # entry 2000, initial SL 1990 -> R=10. At +10 price (2010) BE fires.
    new_sl = break_even_stop(
        OrderSide.BUY, entry=2000.0, initial_sl=1990.0, current_price=2010.0,
        current_sl=1990.0, symbol_info=XAUUSD, config=cfg,
    )
    assert new_sl == pytest.approx(2000.05)  # entry + 5 points buffer


def test_break_even_not_before_trigger():
    cfg = BreakEvenConfig(enabled=True, trigger_r=1.0, buffer_points=5)
    new_sl = break_even_stop(
        OrderSide.BUY, 2000.0, 1990.0, current_price=2005.0, current_sl=1990.0,
        symbol_info=XAUUSD, config=cfg,
    )
    assert new_sl is None  # only +0.5R


def test_break_even_disabled():
    cfg = BreakEvenConfig(enabled=False)
    assert break_even_stop(
        OrderSide.BUY, 2000.0, 1990.0, 2010.0, 1990.0, XAUUSD, cfg
    ) is None


def test_trailing_moves_forward_only():
    cfg = TrailingStopConfig(enabled=True, atr_multiplier=1.0)
    # BUY, price 2020, ATR 5 -> candidate 2015. Current SL 2000 -> improves.
    new_sl = trailing_stop(OrderSide.BUY, 2020.0, 2000.0, 5.0, XAUUSD, cfg)
    assert new_sl == pytest.approx(2015.0)
    # If current SL already tighter (2016), no backward move.
    assert trailing_stop(OrderSide.BUY, 2020.0, 2016.0, 5.0, XAUUSD, cfg) is None


def test_trailing_sell_side():
    cfg = TrailingStopConfig(enabled=True, atr_multiplier=1.0)
    # SELL, price 1980, ATR 5 -> candidate 1985. Current SL 2000 -> improves down.
    new_sl = trailing_stop(OrderSide.SELL, 1980.0, 2000.0, 5.0, XAUUSD, cfg)
    assert new_sl == pytest.approx(1985.0)


def test_manage_stop_picks_tightest():
    be = BreakEvenConfig(enabled=True, trigger_r=1.0, buffer_points=0)
    tr = TrailingStopConfig(enabled=True, atr_multiplier=1.0)
    # entry 2000, initial SL 1990 (R=10), price 2020, ATR 5.
    # BE candidate = 2000; trailing candidate = 2015. Tightest for BUY = 2015.
    update = manage_stop(
        OrderSide.BUY, 2000.0, 1990.0, 2020.0, 1990.0, 5.0, XAUUSD, be, tr,
    )
    assert update is not None
    assert update.new_sl == pytest.approx(2015.0)
    assert update.reason == "trailing"


def test_manage_stop_none_when_no_improvement():
    be = BreakEvenConfig(enabled=True, trigger_r=1.0, buffer_points=0)
    tr = TrailingStopConfig(enabled=True, atr_multiplier=1.0)
    # Price barely above entry, SL already high -> nothing improves.
    update = manage_stop(
        OrderSide.BUY, 2000.0, 1990.0, 2001.0, 1999.0, 5.0, XAUUSD, be, tr,
    )
    assert update is None
