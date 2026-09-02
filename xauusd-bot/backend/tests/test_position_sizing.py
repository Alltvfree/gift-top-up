"""Tests for percentage-of-equity position sizing."""

from __future__ import annotations

import pytest

from app.core.models import SymbolInfo
from app.risk.position_sizing import calculate_position_size

XAUUSD = SymbolInfo(
    name="XAUUSD", digits=2, point=0.01, tick_size=0.01, tick_value=1.0,
    volume_min=0.01, volume_max=100.0, volume_step=0.01,
)


def test_basic_one_percent_sizing():
    # 1% of 10,000 = $100 risk; $10 stop = $1000 loss/lot -> 0.10 lots.
    result = calculate_position_size(10_000, 1.0, 2000.0, 1990.0, XAUUSD)
    assert result.ok
    assert result.lots == pytest.approx(0.10)
    assert result.risk_amount == pytest.approx(100.0)
    assert result.risk_percent_effective == pytest.approx(1.0)


def test_never_exceeds_risk_budget():
    # Odd stop distance forces rounding; effective risk must stay <= budget.
    result = calculate_position_size(10_000, 1.0, 2000.0, 1987.30, XAUUSD)
    budget = 10_000 * 0.01
    assert result.ok
    assert result.risk_amount <= budget + 1e-9


def test_rounds_down_to_step():
    # Raw lots 0.1666...; step 0.01 -> must floor to 0.16, never 0.17.
    result = calculate_position_size(10_000, 1.0, 2000.0, 1994.0, XAUUSD)
    assert result.lots == pytest.approx(0.16)


def test_rejects_when_below_broker_minimum():
    # Tiny account: required lot rounds below volume_min -> reject (lots 0).
    result = calculate_position_size(10.0, 1.0, 2000.0, 1990.0, XAUUSD)
    assert not result.ok
    assert result.lots == 0.0
    assert "minimum" in result.rejected_reason


def test_caps_at_broker_maximum():
    # Huge risk budget must be capped at volume_max.
    result = calculate_position_size(
        10_000_000, 100.0, 2000.0, 1999.99, XAUUSD
    )
    assert result.lots <= XAUUSD.volume_max


def test_respects_configured_max_lots():
    result = calculate_position_size(
        1_000_000, 100.0, 2000.0, 1990.0, XAUUSD, max_lots=0.5
    )
    assert result.lots <= 0.5


def test_invalid_inputs_rejected():
    assert not calculate_position_size(0, 1.0, 2000, 1990, XAUUSD).ok
    assert not calculate_position_size(10_000, 0, 2000, 1990, XAUUSD).ok
    # Zero stop distance.
    assert not calculate_position_size(10_000, 1.0, 2000, 2000, XAUUSD).ok
