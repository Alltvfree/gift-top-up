"""Tests for the optimization parameter space and overfitting assessment."""

from __future__ import annotations

from app.core.config import BotConfig
from app.backtesting.metrics import Metrics
from app.optimization.overfitting import Robustness, assess
from app.optimization.space import (
    apply_overrides,
    grid_candidates,
    random_candidates,
    validate_grid,
)


def test_apply_overrides_nested():
    base = BotConfig()
    cfg = apply_overrides(base, {
        "strategy.ema_fast": 21,
        "take_profit.risk_reward": 3.0,
        "risk.cooldown_minutes": 5,
    })
    assert cfg.strategy.ema_fast == 21
    assert cfg.take_profit.risk_reward == 3.0
    assert cfg.risk.cooldown_minutes == 5
    # Base is untouched.
    assert base.strategy.ema_fast == 50


def test_grid_candidate_count():
    grid = {"a": [1, 2, 3], "b": [10, 20]}
    assert len(list(grid_candidates(grid))) == 6


def test_random_candidates_dedup_and_cap():
    grid = {"a": [1, 2], "b": [10, 20]}   # only 4 combos exist
    got = list(random_candidates(grid, n=10, seed=1))
    assert len(got) == 4
    # unique
    assert len({tuple(sorted(d.items())) for d in got}) == 4


def test_validate_grid_warnings():
    warnings = validate_grid({
        "strategy.ema_fast": [10, 20],
        "not.a.param": [1],
        "strategy.rsi_period": [7, 14],
        "stop_loss.atr_multiplier": [1.0, 2.0],
        "take_profit.risk_reward": [1.5, 2.0],
    })
    assert any("not.a.param" in w for w in warnings)
    assert any("overfitting" in w for w in warnings)  # >4 params


def _metrics(pf, net, trades=30, dd=10.0):
    m = Metrics(total_trades=trades, net_profit=net, profit_factor=pf,
                max_drawdown_pct=dd)
    return m


def test_overfitting_robust():
    train = _metrics(pf=1.8, net=500)
    val = _metrics(pf=1.6, net=400)
    oos = _metrics(pf=1.5, net=350)
    report = assess(train, 10_000, validation=val, oos=oos)
    assert report.rating is Robustness.ROBUST
    assert not report.flags


def test_overfitting_high_risk_on_oos_loss():
    train = _metrics(pf=3.0, net=800)
    val = _metrics(pf=1.4, net=200)
    oos = _metrics(pf=0.4, net=-300)
    report = assess(train, 10_000, validation=val, oos=oos)
    assert report.rating is Robustness.HIGH_RISK
    assert any("out-of-sample" in f for f in report.flags)


def test_overfitting_warning_low_trades():
    train = _metrics(pf=1.6, net=300, trades=5)
    report = assess(train, 10_000)
    assert train.total_trades < 20
    assert report.rating in (Robustness.WARNING, Robustness.HIGH_RISK)
    assert any("trade count" in f for f in report.flags)
