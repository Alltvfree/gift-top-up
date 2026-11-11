import pytest

from mt5_ai.config import Settings
from mt5_ai.rules import AccountContext, SymbolSpec, calc_lots, evaluate_order, loss_at_stop, symbol_allowed

GOLD = SymbolSpec(symbol="XAUUSD", digits=2, point=0.01, volume_min=0.01, volume_max=100.0, volume_step=0.01,
                  tick_size=0.01, tick_value_loss=1.0, contract_size=100.0, stops_level_points=0, trade_allowed=True)
ACCT = AccountContext(is_demo=True, balance=10_000.0, equity=10_000.0, realized_today=0.0,
                      trades_today_ours=0, open_positions_ours=0)
S = Settings()


def ev(**kw):
    args = dict(side="BUY", entry=5000.0, sl=4995.0, tp=5010.0, risk_pct=1.0, spread_price=0.25, spec=GOLD, account=ACCT, settings=S)
    args.update(kw)
    return evaluate_order(**args)


def failed(e):
    return {c.name for c in e.failures}


def test_sizing_risks_the_requested_money_at_the_stop():
    assert calc_lots(100.0, 5.0, GOLD) == pytest.approx(0.2)          # 100 / (5 * $100 per $1 per lot)
    assert loss_at_stop(0.2, 5.0, GOLD) == pytest.approx(100.0)


def test_sizing_rounds_down_never_up_and_skips_when_below_minimum():
    assert calc_lots(100.0, 7.0, GOLD) == pytest.approx(0.14)         # 0.1428 -> 0.14
    assert loss_at_stop(0.14, 7.0, GOLD) <= 100.0
    assert calc_lots(100.0, 500.0, GOLD) == 0.0                       # 0.002 lots < 0.01 minimum
    assert calc_lots(0, 5.0, GOLD) == 0.0 and calc_lots(100.0, 0, GOLD) == 0.0


def test_a_clean_long_passes_every_check():
    e = ev()
    assert e.passed and not e.failures
    assert e.lots == pytest.approx(0.2) and e.rr == pytest.approx(2.0) and e.risk_money == pytest.approx(100.0)


def test_a_clean_short_passes():
    e = ev(side="SELL", entry=5000.0, sl=5005.0, tp=4990.0)
    assert e.passed and e.lots == pytest.approx(0.2)


@pytest.mark.parametrize(
    "kwargs, expected",
    [
        ({"sl": None}, "stop_loss"), ({"sl": 5001.0}, "stop_loss"),            # stop on the wrong side of a BUY
        ({"tp": None}, "take_profit"), ({"tp": 4999.0}, "take_profit"),
        ({"tp": 5004.0}, "reward_risk"),                                        # 0.8R < 1.5R minimum
        ({"risk_pct": 2.0}, "risk_pct"), ({"risk_pct": 0}, "risk_pct"),
        ({"spread_price": 1.5}, "spread"),                                      # 30% of a $5 stop
        ({"sl": 4000.0, "tp": 7000.0}, "position_size"),                        # $1000 stop: minimum lot risks too much
    ],
)
def test_each_rule_blocks_on_its_own(kwargs, expected):
    e = ev(**kwargs)
    assert not e.passed and expected in failed(e)


def test_real_money_account_is_blocked_unless_the_person_enabled_it():
    real = AccountContext(False, 10_000.0, 10_000.0, 0.0, 0, 0)
    assert "demo_account" in failed(ev(account=real))
    assert ev(account=real, settings=Settings(allow_live=True)).passed


def test_symbol_allowlist_uses_patterns_case_insensitively():
    assert symbol_allowed("XAUUSDm", ("xauusd*",)) and symbol_allowed("XAUUSD", ("XAUUSD*",))
    assert not symbol_allowed("BTCUSD", ("XAUUSD*",))
    other = SymbolSpec(**{**GOLD.__dict__, "symbol": "EURUSD"})
    assert "symbol_allowed" in failed(ev(spec=other))


def test_market_closed_blocks():
    closed = SymbolSpec(**{**GOLD.__dict__, "trade_allowed": False})
    assert "symbol_tradable" in failed(ev(spec=closed))


def test_daily_loss_limit_counts_every_strategy_on_the_account():
    # Start of day 10_000; GRID bots already lost 300 = 3% -> blocked.
    hurt = AccountContext(True, 9_700.0, 9_700.0, -300.0, 0, 0)
    assert "daily_loss" in failed(ev(account=hurt))
    ok = AccountContext(True, 9_800.0, 9_800.0, -200.0, 0, 0)
    assert "daily_loss" not in failed(ev(account=ok))


def test_trade_count_and_open_position_limits():
    assert "trades_today" in failed(ev(account=AccountContext(True, 1e4, 1e4, 0.0, 3, 0)))
    assert "open_positions" in failed(ev(account=AccountContext(True, 1e4, 1e4, 0.0, 0, 1)))


def test_sizing_uses_the_lower_of_balance_and_equity_and_respects_max_lot():
    underwater = AccountContext(True, 10_000.0, 5_000.0, 0.0, 0, 0)
    assert ev(account=underwater).lots == pytest.approx(0.1)
    capped = ev(settings=Settings(max_lot=0.05))
    assert capped.lots == pytest.approx(0.05) and capped.passed


def test_minimum_stop_distance_from_the_broker():
    wide = SymbolSpec(**{**GOLD.__dict__, "stops_level_points": 1000})  # 10.00 minimum
    assert "min_stop_distance" in failed(ev(spec=wide))


def test_every_failure_is_reported_not_just_the_first():
    bad = ev(sl=None, risk_pct=5.0, account=AccountContext(False, 1e4, 1e4, 0.0, 0, 0))
    assert {"demo_account", "stop_loss"} <= failed(bad)
    assert len(bad.checks) >= 4


def test_invalid_side():
    assert "side" in failed(ev(side="HOLD"))
