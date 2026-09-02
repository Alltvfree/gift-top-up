"""Integration tests for the optimizer and walk-forward (small, deterministic)."""

from __future__ import annotations

import pytest

from app.core.config import BotConfig
from app.optimization.optimizer import Optimizer, save_results
from app.optimization.walk_forward import WalkForward
from app.optimization.overfitting import Robustness

from tests.helpers import XAUUSD, build_uptrend_dataset


def opt_base():
    # Ultra-short indicators so trades appear within small windows.
    return BotConfig(
        strategy={
            "ema_fast": 3, "ema_slow": 6, "ema_short": 3, "rsi_period": 5,
            "atr_period": 5, "min_score": 70, "pullback_atr_mult": 50.0,
            "rsi_overbought": 100.0, "rsi_oversold": 0.0,
        },
        risk={"cooldown_minutes": 0, "max_daily_trades": 1000, "max_positions": 1},
        stop_loss={"atr_period": 5, "atr_multiplier": 1.5},
        break_even={"enabled": False},
        trailing_stop={"enabled": False},
        trading_sessions={"enabled": False},
    )


@pytest.fixture(scope="module")
def dataset():
    return build_uptrend_dataset(n_entry=500, start=1900, stop=2100)


def test_grid_search_ranks_results(dataset, tmp_path):
    grid = {"take_profit.risk_reward": [1.5, 2.0, 3.0]}
    opt = Optimizer(opt_base(), XAUUSD, dataset, grid,
                    objective="net_profit", min_trades=2)
    results = opt.run(method="grid")
    assert len(results) == 3
    # Sorted by score descending.
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)
    assert results[0].metrics["total_trades"] >= 0

    save_results(results, tmp_path / "opt.json")
    assert (tmp_path / "opt.json").exists()


def test_random_search_respects_n_iter(dataset):
    grid = {"take_profit.risk_reward": [1.0, 1.5, 2.0, 2.5, 3.0]}
    opt = Optimizer(opt_base(), XAUUSD, dataset, grid,
                    objective="expectancy_r", min_trades=1)
    results = opt.run(method="random", n_iter=2, seed=3)
    assert len(results) == 2


def test_min_trades_penalizes_thin_results(dataset):
    grid = {"take_profit.risk_reward": [2.0]}
    opt = Optimizer(opt_base(), XAUUSD, dataset, grid,
                    objective="net_profit", min_trades=10_000)
    results = opt.run(method="grid")
    # Impossible trade minimum -> score is -inf.
    assert results[0].score == float("-inf")


def test_walk_forward_produces_graded_folds(dataset):
    grid = {"take_profit.risk_reward": [1.5, 2.0]}
    wf = WalkForward(
        opt_base(), XAUUSD, dataset, grid,
        train_bars=200, validation_bars=100, oos_bars=100,
        objective="net_profit", min_trades=1,
    )
    folds = wf.run(method="grid")
    assert len(folds) >= 1
    fold = folds[0]
    assert set(fold.best_params) == {"take_profit.risk_reward"}
    assert fold.overfitting.rating in (
        Robustness.ROBUST, Robustness.WARNING, Robustness.HIGH_RISK
    )
    # All three windows evaluated.
    assert fold.train.total_trades >= 0
    assert fold.out_of_sample.total_trades >= 0
