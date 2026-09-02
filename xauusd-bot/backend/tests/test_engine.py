"""Integration tests for the TradingEngine (paper mode, deterministic data)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.config import BotConfig
from app.core.state import BotState, InMemoryStateStore
from app.core.models import Timeframe
from app.execution.engine import TradingEngine
from app.execution.paper_broker import PaperBroker
from app.risk.governor import RiskGovernor
from app.risk.risk_manager import RiskManager
from app.strategies.factory import create_strategy

from tests.helpers import XAUUSD, build_uptrend_market


def make_config(**risk):
    risk_cfg = {"max_positions": 1, "cooldown_minutes": 15}
    risk_cfg.update(risk)
    return BotConfig(
        strategy={
            "min_score": 70, "pullback_atr_mult": 50.0,
            "rsi_overbought": 100.0, "rsi_oversold": 0.0,
        },
        risk=risk_cfg,
        break_even={"enabled": False},
        trailing_stop={"enabled": False},
    )


def build_engine(config=None, balance=10_000.0):
    config = config or make_config()
    market, adapter = build_uptrend_market(balance=balance)
    state = BotState()
    store = InMemoryStateStore()
    store.save(state)
    engine = TradingEngine(
        config=config,
        market=market,
        strategy=create_strategy(config),
        risk_manager=RiskManager(config.risk),
        governor=RiskGovernor(config.risk, state),
        broker=PaperBroker(XAUUSD, starting_balance=balance),
        state=state,
        state_store=store,
    )
    return engine, market, adapter, state


def test_engine_opens_a_trade():
    engine, _, adapter, state = build_engine()
    result = engine.process_once(now=adapter.tick.time)
    assert result.signal is not None
    assert result.opened_trade
    assert len(engine.broker.get_positions("XAUUSD")) == 1
    assert state.trades_today == 1


def test_candle_dedup_prevents_second_trade_same_bar():
    engine, _, adapter, _ = build_engine()
    engine.process_once(now=adapter.tick.time)
    # Second call, SAME candle -> skipped, no new order.
    result2 = engine.process_once(now=adapter.tick.time + timedelta(seconds=30))
    assert result2.skipped_reason == "candle already processed"
    assert len(engine.broker.get_positions("XAUUSD")) == 1


def test_max_positions_blocks_second_trade_new_bar():
    engine, market, adapter, _ = build_engine()
    engine.process_once(now=adapter.tick.time)
    # New completed M5 candle -> evaluation runs again, but 1 position is open.
    adapter.append_candle(Timeframe.M5, 2001.0)
    result2 = engine.process_once(now=adapter.tick.time + timedelta(minutes=5))
    assert result2.order is None or not result2.order.executed
    assert len(engine.broker.get_positions("XAUUSD")) == 1


def test_emergency_stop_blocks_trading():
    engine, _, adapter, state = build_engine()
    engine.emergency_stop()
    assert state.emergency_stop is True
    result = engine.process_once(now=adapter.tick.time)
    assert not result.opened_trade
    assert "emergency" in result.gate_reason


def test_resume_clears_emergency_stop():
    engine, _, adapter, state = build_engine()
    engine.emergency_stop()
    engine.resume()
    assert state.emergency_stop is False
    result = engine.process_once(now=adapter.tick.time)
    assert result.opened_trade


def test_take_profit_close_is_reconciled():
    engine, _, adapter, state = build_engine()
    engine.process_once(now=adapter.tick.time)
    assert len(engine.broker.get_positions("XAUUSD")) == 1
    # Price gaps well above any TP -> position auto-closes on next mark.
    adapter.tick = adapter.tick.__class__("XAUUSD", adapter.tick.time,
                                          bid=2050.0, ask=2050.2)
    result = engine.process_once(now=adapter.tick.time + timedelta(minutes=5))
    assert len(engine.broker.get_positions("XAUUSD")) == 0
    assert result.closed and result.closed[0].profit > 0
    assert state.realized_pnl_today > 0
    assert state.last_close_time is not None


def test_state_persisted_each_iteration():
    engine, _, adapter, _ = build_engine()
    engine.process_once(now=adapter.tick.time)
    reloaded = engine.state_store.load()
    assert reloaded.trades_today == 1
    assert reloaded.processed_candles  # candle marker written
