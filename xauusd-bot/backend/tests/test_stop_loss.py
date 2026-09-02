"""Tests for ATR-based SL/TP calculation."""

from __future__ import annotations

import pytest

from app.core.models import OrderSide, SymbolInfo
from app.risk.stop_loss import compute_stop_target

SYMBOL = SymbolInfo(
    name="XAUUSD", digits=2, point=0.01, tick_size=0.01, tick_value=1.0,
    volume_min=0.01, volume_max=100.0, volume_step=0.01,
)


def test_buy_sl_below_tp_above():
    t = compute_stop_target(
        OrderSide.BUY, entry=2000.0, atr_value=5.0, symbol_info=SYMBOL,
        atr_multiplier=1.5, risk_reward=2.0,
    )
    assert t.sl_distance == pytest.approx(7.5)
    assert t.stop_loss == pytest.approx(1992.5)
    assert t.take_profit == pytest.approx(2015.0)
    assert t.stop_loss < t.entry < t.take_profit


def test_sell_sl_above_tp_below():
    t = compute_stop_target(
        OrderSide.SELL, entry=2000.0, atr_value=5.0, symbol_info=SYMBOL,
        atr_multiplier=1.5, risk_reward=2.0,
    )
    assert t.stop_loss == pytest.approx(2007.5)
    assert t.take_profit == pytest.approx(1985.0)
    assert t.take_profit < t.entry < t.stop_loss


def test_risk_reward_scales_tp():
    for rr in (1.0, 1.5, 2.0, 3.0):
        t = compute_stop_target(
            OrderSide.BUY, 2000.0, 4.0, SYMBOL,
            atr_multiplier=1.0, risk_reward=rr,
        )
        assert t.tp_distance == pytest.approx(t.sl_distance * rr)


def test_rounding_to_digits():
    three_digit = SymbolInfo(
        name="XAUUSD.a", digits=3, point=0.001, tick_size=0.001, tick_value=1.0,
        volume_min=0.01, volume_max=100.0, volume_step=0.01,
    )
    t = compute_stop_target(
        OrderSide.BUY, 1955.12345, 1.23456, three_digit,
        atr_multiplier=1.0, risk_reward=2.0,
    )
    assert t.entry == round(t.entry, 3)
    assert t.stop_loss == round(t.stop_loss, 3)


def test_invalid_inputs_raise():
    with pytest.raises(ValueError):
        compute_stop_target(OrderSide.BUY, 2000, 0.0, SYMBOL,
                            atr_multiplier=1.5, risk_reward=2.0)
    with pytest.raises(ValueError):
        compute_stop_target(OrderSide.BUY, 2000, 5.0, SYMBOL,
                            atr_multiplier=0.0, risk_reward=2.0)
