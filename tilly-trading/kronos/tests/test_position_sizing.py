from backtest.config import RiskConfig
from backtest.position_sizing import calculate_position_size
from backtest.symbols import get_symbol_spec

spec = get_symbol_spec("XAUUSDm")  # point=0.01, contract_size=100, tick_value=1.0, tick_size=0.01


def test_fixed_lot_mode_ignores_risk_math():
    cfg = RiskConfig(mode="fixed_lot", fixed_lot=0.05)
    assert calculate_position_size(cfg, spec, equity=10000.0, sl_distance_price=2.0) == 0.05


def test_percent_equity_scales_with_equity_and_sl_distance():
    cfg = RiskConfig(mode="percent_equity", risk_percent=1.0, max_lot=100.0)
    # Risking 1% of 10,000 = $100. SL distance $2 = 200 points. value/point/lot = 1.0.
    # lots = 100 / (200 * 1.0) = 0.5
    lots = calculate_position_size(cfg, spec, equity=10000.0, sl_distance_price=2.0)
    assert abs(lots - 0.5) < 1e-6

    # Doubling equity should double the position size for the same risk %.
    lots_double_equity = calculate_position_size(cfg, spec, equity=20000.0, sl_distance_price=2.0)
    assert abs(lots_double_equity - 1.0) < 1e-6

    # Doubling SL distance (more risk per lot) should halve the lot size.
    lots_wider_sl = calculate_position_size(cfg, spec, equity=10000.0, sl_distance_price=4.0)
    assert abs(lots_wider_sl - 0.25) < 1e-6


def test_fixed_money_mode():
    cfg = RiskConfig(mode="fixed_money", fixed_money=50.0, max_lot=100.0)
    lots = calculate_position_size(cfg, spec, equity=999999.0, sl_distance_price=2.0)
    assert abs(lots - 0.25) < 1e-6  # 50 / (200 * 1.0) = 0.25, independent of equity


def test_risk_too_small_for_minimum_lot_returns_zero_not_forced_minimum():
    cfg = RiskConfig(mode="fixed_money", fixed_money=0.01, max_lot=100.0)
    lots = calculate_position_size(cfg, spec, equity=10000.0, sl_distance_price=2.0)
    assert lots == 0.0, "an unrealistically small risk-based size must be skipped, not rounded up to volume_min"


def test_max_lot_cap_is_respected():
    cfg = RiskConfig(mode="percent_equity", risk_percent=50.0, max_lot=2.0)
    lots = calculate_position_size(cfg, spec, equity=1_000_000.0, sl_distance_price=0.5)
    assert lots <= 2.0


def test_invalid_sl_distance_raises():
    cfg = RiskConfig(mode="percent_equity", risk_percent=1.0)
    try:
        calculate_position_size(cfg, spec, equity=10000.0, sl_distance_price=0.0)
        assert False, "expected ValueError for non-positive sl_distance_price"
    except ValueError:
        pass
