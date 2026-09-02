"""Tests for persistent bot state."""

from __future__ import annotations

from datetime import date, datetime, timezone

from app.core.state import BotState, StateStore, TradeMeta, rollover_day


def test_state_roundtrip_json(tmp_path):
    store = StateStore(tmp_path / "state.json")
    state = store.load()
    assert state.emergency_stop is False

    state.emergency_stop = True
    state.trades_today = 3
    state.add_open_trade(
        TradeMeta(ticket=101, signal_id="sig-1", side="BUY", entry=2000.0,
                  initial_sl=1990.0, volume=0.1)
    )
    store.save(state)

    reloaded = StateStore(tmp_path / "state.json").load()
    assert reloaded.emergency_stop is True
    assert reloaded.trades_today == 3
    assert reloaded.executed_signals["sig-1"] == 101
    meta = reloaded.get_open_trade(101)
    assert meta is not None and meta.entry == 2000.0


def test_candle_dedup_markers():
    state = BotState()
    ts = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    assert not state.is_candle_processed("XAUUSD", "M5", ts)
    state.mark_candle_processed("XAUUSD", "M5", ts)
    assert state.is_candle_processed("XAUUSD", "M5", ts)
    # A different candle time is not yet processed.
    later = datetime(2026, 1, 1, 12, 5, tzinfo=timezone.utc)
    assert not state.is_candle_processed("XAUUSD", "M5", later)


def test_rollover_resets_daily_counters():
    state = BotState(trading_day="2026-01-01", trades_today=5,
                     realized_pnl_today=-50.0, day_start_equity=10_000,
                     peak_equity=10_100)
    reset = rollover_day(state, date(2026, 1, 2), equity=9_950)
    assert reset is True
    assert state.trades_today == 0
    assert state.realized_pnl_today == 0.0
    assert state.day_start_equity == 9_950
    # Same-day call does not reset.
    assert rollover_day(state, date(2026, 1, 2), equity=9_960) is False
    assert state.trades_today == 0


def test_remove_open_trade():
    state = BotState()
    state.add_open_trade(TradeMeta(1, "s", "BUY", 2000, 1990, 0.1))
    state.remove_open_trade(1)
    assert state.get_open_trade(1) is None
