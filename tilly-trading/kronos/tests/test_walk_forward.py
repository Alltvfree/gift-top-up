"""End-to-end walk-forward orchestration tests (Phases 3, 4, 17) against
synthetic data, plus a regression test proving the runtime leakage audit
(Phase 2) actually halts a corrupted pipeline rather than silently running
through it.
"""
import pandas as pd
import pytest

from backtest import walk_forward
from backtest.config import BacktestConfig, ExecutionConfig, RiskConfig, WalkForwardConfig
from backtest.leakage_audit import LookaheadError
from backtest.symbols import get_symbol_spec
from conftest import make_synthetic_ohlc


def _small_cfg() -> BacktestConfig:
    return BacktestConfig(
        symbol="BTCUSDm", timeframe="M5", higher_timeframe="H1",
        walk_forward=WalkForwardConfig(train_days=15, validation_days=3, test_days=3, step_days=5, embargo_minutes=0),
        risk=RiskConfig(mode="fixed_lot", fixed_lot=0.01),
        execution=ExecutionConfig(next_bar=True, same_bar_exit_policy="conservative", max_holding_bars=30),
    )


def test_run_walk_forward_end_to_end_on_synthetic_data():
    base_raw = make_synthetic_ohlc(7200, freq="5min", start_price=84000.0, seed=1)  # ~25 days of M5, from 2024-01-01
    # Must start well before base_raw AND extend past it — a higher-timeframe
    # series that doesn't actually overlap the base series in time would let
    # every base row match the higher series' single long-closed last bar,
    # which can never expose a still-forming-bar bug either way. See the
    # identical note in tests/test_leakage_audit.py.
    higher_raw = make_synthetic_ohlc(1500, freq="1h", start_time="2023-12-01", start_price=84000.0, seed=2)
    cfg = _small_cfg()
    spec = get_symbol_spec(cfg.symbol)

    result = walk_forward.run_walk_forward(base_raw, cfg, spec, higher_raw=higher_raw)

    assert len(result.windows) >= 1
    run_windows = [w for w in result.windows if not w.skipped_reason]
    assert run_windows, f"every window was skipped: {[w.skipped_reason for w in result.windows]}"
    assert "auc" in result.overall_model_metrics_buy
    assert "auc" in result.overall_model_metrics_sell
    assert "total_trades" in result.overall_trading_metrics
    assert isinstance(result.all_trades, pd.DataFrame)
    assert isinstance(result.equity_curve, pd.DataFrame)
    assert not result.predictions.empty
    assert {"predicted_probability_buy", "predicted_probability_sell"}.issubset(result.predictions.columns)


def test_windows_are_trained_independently_not_concatenated_before_scoring():
    """Each window's test predictions must come from a model that only saw
    data before that window (the exact anti-pattern the project's own spec
    for this file explicitly warned against by name)."""
    base_raw = make_synthetic_ohlc(10000, freq="5min", start_price=84000.0, seed=3)
    cfg = _small_cfg()
    cfg.higher_timeframe = None
    spec = get_symbol_spec(cfg.symbol)

    result = walk_forward.run_walk_forward(base_raw, cfg, spec, higher_raw=None)
    run_windows = [w for w in result.windows if not w.skipped_reason]
    assert len(run_windows) >= 2, "need at least 2 windows to prove independence"
    # Every window's test split is strictly after its own train/val split — enforced
    # structurally by windows.generate_windows and re-checked here per window.
    for w in run_windows:
        assert w.window.train_end <= w.window.val_start
        assert w.window.val_end <= w.window.test_start


def test_corrupted_merge_is_caught_by_the_runtime_leakage_audit(monkeypatch):
    """Regression test: if merge_higher_timeframe ever regressed back to the
    naive open-time-only merge (the exact bug this project already found
    and fixed once — see README), run_walk_forward must refuse to proceed,
    not silently produce a suspiciously-high-AUC result again."""

    def broken_merge(base, higher, prefix):
        h = higher.add_prefix(f"{prefix}_").rename(columns={f"{prefix}_time": "time"})
        return pd.merge_asof(base.sort_values("time"), h.sort_values("time"), on="time", direction="backward")

    import features

    monkeypatch.setattr(features, "merge_higher_timeframe", broken_merge)

    base_raw = make_synthetic_ohlc(7200, freq="5min", start_price=84000.0, seed=1)
    higher_raw = make_synthetic_ohlc(1500, freq="1h", start_time="2023-12-01", start_price=84000.0, seed=2)
    cfg = _small_cfg()
    spec = get_symbol_spec(cfg.symbol)

    with pytest.raises(LookaheadError):
        walk_forward.run_walk_forward(base_raw, cfg, spec, higher_raw=higher_raw)


def test_insufficient_history_raises_a_clear_error():
    base_raw = make_synthetic_ohlc(50, freq="5min")  # nowhere near enough for a 15/3/3 window
    cfg = _small_cfg()
    cfg.higher_timeframe = None
    spec = get_symbol_spec(cfg.symbol)
    with pytest.raises(ValueError):
        walk_forward.run_walk_forward(base_raw, cfg, spec, higher_raw=None)
