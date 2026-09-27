import numpy as np

from backtest import costs
from backtest.config import CommissionConfig, SlippageConfig, SpreadConfig
from backtest.symbols import get_symbol_spec

spec = get_symbol_spec("BTCUSDm")


def test_spread_points_historical_uses_bar_value():
    cfg = SpreadConfig(mode="historical")
    assert costs.spread_points(cfg, spec, 3000.0, 84000.0) == 3000.0


def test_spread_points_historical_without_data_raises():
    cfg = SpreadConfig(mode="historical")
    try:
        costs.spread_points(cfg, spec, None, 84000.0)
        assert False, "expected ValueError when historical spread is unavailable"
    except ValueError:
        pass


def test_spread_points_fixed_and_percentage():
    fixed = SpreadConfig(mode="fixed", points=100.0)
    assert costs.spread_points(fixed, spec, None, 84000.0) == 100.0
    pct = SpreadConfig(mode="percentage", percent=0.02)
    expected = (0.02 / 100.0) * 84000.0 / spec.point
    assert np.isclose(costs.spread_points(pct, spec, None, 84000.0), expected)


def test_slippage_fixed_and_random():
    rng = np.random.default_rng(1)
    fixed = SlippageConfig(mode="fixed_points", points=2.0)
    assert costs.slippage_points(fixed, rng) == 2.0
    random_cfg = SlippageConfig(mode="random", points=2.0, random_std_points=0.5)
    values = [costs.slippage_points(random_cfg, rng) for _ in range(200)]
    assert all(v >= 0 for v in values), "slippage must never be negative"
    assert np.isclose(np.mean(values), 2.0, atol=0.2)


def test_entry_and_exit_price_always_cost_the_trader():
    # BUY entry must be at or above the raw price (ASK side); SELL entry at or below (BID side).
    buy_entry = costs.entry_price("BUY", 100.0, spec, half_spread=0.5, slip=1.0)
    sell_entry = costs.entry_price("SELL", 100.0, spec, half_spread=0.5, slip=1.0)
    assert buy_entry > 100.0
    assert sell_entry < 100.0

    # Closing a BUY (selling) must be at or below raw; closing a SELL (buying) at or above.
    buy_exit = costs.exit_price("BUY", 100.0, spec, half_spread=0.5, slip=1.0)
    sell_exit = costs.exit_price("SELL", 100.0, spec, half_spread=0.5, slip=1.0)
    assert buy_exit < 100.0
    assert sell_exit > 100.0


def test_commission_modes():
    per_lot = CommissionConfig(type="per_lot", value=3.5)
    assert costs.commission_cost(per_lot, lots=2.0, notional=10000.0) == 7.0
    pct = CommissionConfig(type="percentage", value=0.1)
    assert np.isclose(costs.commission_cost(pct, lots=1.0, notional=10000.0), 10.0)
    fixed = CommissionConfig(type="fixed_per_trade", value=5.0)
    assert costs.commission_cost(fixed, lots=99.0, notional=1.0) == 5.0
