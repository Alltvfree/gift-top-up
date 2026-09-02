"""Tests for the stateful RiskGovernor."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.core.config import RiskConfig
from app.core.state import BotState
from app.risk.governor import RiskGovernor

NOW = datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)


def make(config=None, **state_kwargs):
    state = BotState(**state_kwargs)
    return RiskGovernor(config or RiskConfig(), state), state


def test_allows_trade_on_fresh_day():
    gov, _ = make()
    assert gov.can_open_new_trade(NOW, 10_000).allowed


def test_blocks_on_emergency_stop():
    gov, _ = make(emergency_stop=True, trading_day="2026-01-05",
                  day_start_equity=10_000, peak_equity=10_000)
    result = gov.can_open_new_trade(NOW, 10_000)
    assert not result.allowed
    assert "emergency" in result.reason


def test_blocks_on_daily_loss_limit():
    gov, _ = make(RiskConfig(max_daily_loss=3.0), trading_day="2026-01-05",
                  day_start_equity=10_000, peak_equity=10_000)
    # 4% down on the day.
    result = gov.can_open_new_trade(NOW, 9_600)
    assert not result.allowed
    assert "daily loss" in result.reason


def test_blocks_on_drawdown():
    gov, _ = make(RiskConfig(max_drawdown=10.0), trading_day="2026-01-05",
                  day_start_equity=10_000, peak_equity=12_000)
    # 12k peak -> 10.5k = 12.5% drawdown.
    result = gov.can_open_new_trade(NOW, 10_500)
    assert not result.allowed
    assert "drawdown" in result.reason


def test_blocks_on_max_daily_trades():
    gov, _ = make(RiskConfig(max_daily_trades=5), trading_day="2026-01-05",
                  day_start_equity=10_000, peak_equity=10_000, trades_today=5)
    assert not gov.can_open_new_trade(NOW, 10_000).allowed


def test_cooldown_blocks_then_clears():
    cfg = RiskConfig(cooldown_minutes=15)
    last_close = (NOW - timedelta(minutes=5)).isoformat()
    gov, _ = make(cfg, trading_day="2026-01-05", day_start_equity=10_000,
                  peak_equity=10_000, last_close_time=last_close)
    # 5 min after close -> still cooling down.
    assert not gov.can_open_new_trade(NOW, 10_000).allowed
    # 20 min after close -> allowed.
    later = NOW + timedelta(minutes=15)
    assert gov.can_open_new_trade(later, 10_000).allowed


def test_register_trade_transitions():
    gov, state = make(trading_day="2026-01-05", day_start_equity=10_000,
                      peak_equity=10_000)
    gov.register_trade_opened()
    assert state.trades_today == 1
    gov.register_trade_closed(-50.0, NOW)
    assert state.consecutive_losses == 1
    assert state.realized_pnl_today == -50.0
    gov.register_trade_closed(80.0, NOW)
    assert state.consecutive_losses == 0  # reset on a win


def test_day_rollover_resets_and_allows():
    # Yesterday hit the daily loss limit; today should be fresh.
    gov, state = make(RiskConfig(max_daily_loss=3.0), trading_day="2026-01-04",
                      day_start_equity=10_000, peak_equity=10_000,
                      trades_today=5, realized_pnl_today=-400)
    assert gov.can_open_new_trade(NOW, 9_600).allowed
    assert state.trading_day == "2026-01-05"
    assert state.trades_today == 0
