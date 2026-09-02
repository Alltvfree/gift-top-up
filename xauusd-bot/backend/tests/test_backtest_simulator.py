"""Tests for the bar-based backtest simulator."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import BreakEvenConfig, TrailingStopConfig
from app.core.models import Candle, OrderSide, Signal, SignalType, SymbolInfo
from app.backtesting.simulator import BarSimulator

XAUUSD = SymbolInfo(
    name="XAUUSD", digits=2, point=0.01, tick_size=0.01, tick_value=1.0,
    volume_min=0.01, volume_max=100.0, volume_step=0.01,
)
T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def bar(i, o, h, l, c):
    return Candle(time=T0 + timedelta(minutes=5 * i), open=o, high=h, low=l, close=c)


def buy_signal(entry=2000.0, sl=1990.0, tp=2020.0):
    return Signal(
        signal_id="s1", timestamp=T0, symbol="XAUUSD", direction=SignalType.BUY,
        score=90, strategy="t", strategy_version="1", entry=entry, stop_loss=sl,
        take_profit=tp, risk_reward=2.0,
    )


def new_sim(be=False, trail=False):
    return BarSimulator(
        XAUUSD, BreakEvenConfig(enabled=be, trigger_r=1.0, buffer_points=0),
        TrailingStopConfig(enabled=trail, atr_multiplier=1.0),
    )


def test_take_profit_fill():
    sim = new_sim()
    sim.open_position(buy_signal(), 0.1, bar(0, 2000, 2000, 2000, 2000))
    trade = sim.on_bar(bar(1, 2000, 2021, 1999, 2015), atr_value=5.0)
    assert trade is not None
    assert trade.close_reason == "TP"
    assert trade.profit > 0
    assert trade.r_multiple == pytest.approx(2.0, abs=0.01)


def test_stop_loss_fill():
    sim = new_sim()
    sim.open_position(buy_signal(), 0.1, bar(0, 2000, 2000, 2000, 2000))
    trade = sim.on_bar(bar(1, 2000, 2005, 1989, 1991), atr_value=5.0)
    assert trade is not None
    assert trade.close_reason == "SL"
    assert trade.profit < 0


def test_both_touched_assumes_stop_first():
    sim = new_sim()
    sim.open_position(buy_signal(), 0.1, bar(0, 2000, 2000, 2000, 2000))
    # Bar range spans both SL (1990) and TP (2020).
    trade = sim.on_bar(bar(1, 2000, 2025, 1985, 2000), atr_value=5.0)
    assert trade.close_reason == "SL"  # conservative


def test_no_exit_holds_position():
    sim = new_sim()
    sim.open_position(buy_signal(), 0.1, bar(0, 2000, 2000, 2000, 2000))
    assert sim.on_bar(bar(1, 2000, 2005, 1995, 2002), atr_value=5.0) is None
    assert sim.has_position


def test_force_close_eod():
    sim = new_sim()
    sim.open_position(buy_signal(), 0.1, bar(0, 2000, 2000, 2000, 2000))
    trade = sim.force_close(bar(5, 2010, 2010, 2010, 2010))
    assert trade.close_reason == "EOD"
    assert not sim.has_position


def test_pnl_magnitude():
    # 0.1 lot, TP at +20 (2000->2020) -> 2000 ticks * 1.0 * 0.1 = $200.
    sim = new_sim()
    sim.open_position(buy_signal(tp=2020.0), 0.1, bar(0, 2000, 2000, 2000, 2000))
    trade = sim.on_bar(bar(1, 2000, 2021, 1999, 2020), atr_value=5.0)
    assert trade.profit == pytest.approx(200.0, abs=0.5)
