"""Tests for XAUUSD_TrendPullback_v1.

Uses hand-built OHLC frames so each trend/structure case is deterministic — no
dependence on the mock adapter's random walk.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from app.core.config import StrategyConfig
from app.core.models import SignalType, SymbolInfo, Tick
from app.strategies.base import StrategyInput
from app.strategies.trend_pullback import TrendPullbackStrategy

XAUUSD = SymbolInfo(
    name="XAUUSD", digits=2, point=0.01, tick_size=0.01, tick_value=1.0,
    volume_min=0.01, volume_max=100.0, volume_step=0.01,
)


def make_frame(closes, tf_minutes=15, pad=0.5):
    """Build an OHLC frame from a close series (open = previous close)."""
    n = len(closes)
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    idx = [base + timedelta(minutes=tf_minutes * i) for i in range(n)]
    opens = [closes[0]] + list(closes[:-1])
    highs = [max(o, c) + pad for o, c in zip(opens, closes)]
    lows = [min(o, c) - pad for o, c in zip(opens, closes)]
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes,
         "tick_volume": [100] * n},
        index=pd.DatetimeIndex(idx),
    )


def rising(n, start, stop):
    return list(np.linspace(start, stop, n))


def falling(n, start, stop):
    return list(np.linspace(start, stop, n))


def flat(n, value):
    return [float(value)] * n


def permissive_config(**overrides):
    """Config tuned so a clean trend is actionable in tests."""
    base = dict(
        min_score=70,
        pullback_atr_mult=50.0,   # any recent bar counts as 'near' EMA
        rsi_overbought=100.0,     # strong-trend RSI stays in band
        rsi_oversold=0.0,
    )
    base.update(overrides)
    return StrategyConfig(**base)


def make_strategy(config=None, max_spread=50.0):
    config = config or permissive_config()
    return TrendPullbackStrategy(
        config, atr_multiplier=1.5, risk_reward=2.0, max_spread_points=max_spread,
    )


def make_input(trend_c, setup_c, entry_c, tick=None, spread=10.0):
    return StrategyInput(
        symbol_info=XAUUSD,
        trend_df=make_frame(trend_c, 60),
        setup_df=make_frame(setup_c, 15),
        entry_df=make_frame(entry_c, 5),
        tick=tick,
        spread_points=spread,
    )


def test_insufficient_data_waits():
    strat = make_strategy()
    data = make_input(rising(10, 1900, 2000), rising(10, 1900, 2000),
                      rising(10, 1900, 2000))
    signal = strat.evaluate(data)
    assert signal.direction is SignalType.WAIT
    assert "insufficient" in signal.reason.lower()


def test_flat_market_is_no_trend_wait():
    strat = make_strategy()
    data = make_input(flat(260, 2000), flat(210, 2000), flat(210, 2000))
    signal = strat.evaluate(data)
    assert signal.direction is SignalType.WAIT
    assert "NO_TREND" in signal.reason


def test_uptrend_generates_buy_with_valid_sltp():
    strat = make_strategy()
    data = make_input(
        rising(260, 1900, 2000),
        rising(210, 1950, 2000),
        rising(210, 1980, 2000),
    )
    signal = strat.evaluate(data)
    assert signal.direction is SignalType.BUY
    assert signal.score >= 70
    # SL below entry, TP above, RR respected.
    assert signal.stop_loss < signal.entry < signal.take_profit
    assert signal.components["trend"] == 30
    assert "H1 Trend: BULLISH" in signal.reason


def test_downtrend_generates_sell():
    strat = make_strategy()
    data = make_input(
        falling(260, 2000, 1900),
        falling(210, 2000, 1950),
        falling(210, 2000, 1980),
    )
    signal = strat.evaluate(data)
    assert signal.direction is SignalType.SELL
    assert signal.take_profit < signal.entry < signal.stop_loss


def test_below_min_score_waits():
    # Bullish H1 bias, but setup + entry frames disagree (falling) -> only the
    # trend component scores, which is below the minimum.
    strat = make_strategy(permissive_config(min_score=70))
    data = make_input(
        rising(260, 1900, 2000),
        falling(210, 2000, 1950),
        falling(210, 2000, 1980),
    )
    signal = strat.evaluate(data)
    assert signal.direction is SignalType.WAIT
    assert signal.score < 70


def test_spread_gate_blocks_actionable_signal():
    strat = make_strategy(max_spread=15.0)
    data = make_input(
        rising(260, 1900, 2000),
        rising(210, 1950, 2000),
        rising(210, 1980, 2000),
        spread=99.0,   # way above the 15-point max
    )
    signal = strat.evaluate(data)
    assert signal.direction is SignalType.WAIT
    assert "spread" in signal.reason.lower()


def test_entry_uses_tick_ask_for_buy():
    strat = make_strategy()
    tick = Tick("XAUUSD", datetime(2026, 1, 1, tzinfo=timezone.utc),
                bid=1999.90, ask=2000.10)
    data = make_input(
        rising(260, 1900, 2000),
        rising(210, 1950, 2000),
        rising(210, 1980, 2000),
        tick=tick,
    )
    signal = strat.evaluate(data)
    assert signal.direction is SignalType.BUY
    assert signal.entry == pytest.approx(2000.10)


def test_signal_ids_are_unique():
    strat = make_strategy()
    data = make_input(rising(260, 1900, 2000), rising(210, 1950, 2000),
                      rising(210, 1980, 2000))
    s1 = strat.evaluate(data)
    s2 = strat.evaluate(data)
    assert s1.signal_id != s2.signal_id
