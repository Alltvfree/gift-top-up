"""Tests for the Phase 2 risk manager (per-trade gates + sizing)."""

from __future__ import annotations

from datetime import datetime, timezone

from app.core.config import RiskConfig
from app.core.models import AccountInfo, Signal, SignalType, SymbolInfo
from app.risk.risk_manager import RiskManager

XAUUSD = SymbolInfo(
    name="XAUUSD", digits=2, point=0.01, tick_size=0.01, tick_value=1.0,
    volume_min=0.01, volume_max=100.0, volume_step=0.01,
)

ACCOUNT = AccountInfo(
    login=1, server="Demo", currency="USD", balance=10_000, equity=10_000,
    margin=0.0, margin_free=10_000,
)


def make_signal(direction=SignalType.BUY, entry=2000.0, sl=1990.0, tp=2020.0):
    return Signal(
        signal_id="sig-1", timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        symbol="XAUUSD", direction=direction, score=85.0,
        strategy="test", strategy_version="1", entry=entry, stop_loss=sl,
        take_profit=tp, risk_reward=2.0,
    )


def test_approves_valid_signal():
    rm = RiskManager(RiskConfig())
    decision = rm.evaluate(make_signal(), ACCOUNT, XAUUSD,
                           spread_points=10.0, open_positions=0)
    assert decision.approved
    assert decision.lot_size == 0.10
    assert decision.risk_amount <= ACCOUNT.equity * 0.01 + 1e-9


def test_rejects_wait_signal():
    rm = RiskManager(RiskConfig())
    decision = rm.evaluate(make_signal(direction=SignalType.WAIT),
                           ACCOUNT, XAUUSD, spread_points=10.0)
    assert not decision.approved


def test_rejects_signal_without_stop_loss():
    rm = RiskManager(RiskConfig())
    sig = make_signal()
    object.__setattr__(sig, "stop_loss", None)
    decision = rm.evaluate(sig, ACCOUNT, XAUUSD, spread_points=10.0)
    assert not decision.approved
    assert "stop-loss" in decision.reason


def test_rejects_wide_spread():
    rm = RiskManager(RiskConfig(max_spread_points=20.0))
    decision = rm.evaluate(make_signal(), ACCOUNT, XAUUSD,
                           spread_points=50.0, open_positions=0)
    assert not decision.approved
    assert "spread" in decision.reason


def test_rejects_when_max_positions_reached():
    rm = RiskManager(RiskConfig(max_positions=1))
    decision = rm.evaluate(make_signal(), ACCOUNT, XAUUSD,
                           spread_points=10.0, open_positions=1)
    assert not decision.approved
    assert "positions" in decision.reason


def test_rejects_when_position_too_small_for_account():
    rm = RiskManager(RiskConfig())
    tiny = AccountInfo(login=1, server="Demo", currency="USD", balance=10,
                       equity=10, margin=0.0, margin_free=10)
    decision = rm.evaluate(make_signal(), tiny, XAUUSD,
                           spread_points=10.0, open_positions=0)
    assert not decision.approved
    assert "sizing" in decision.reason
