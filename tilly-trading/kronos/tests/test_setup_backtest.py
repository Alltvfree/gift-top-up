"""setup_backtest.py end to end on synthetic bars: the engine wiring, the
execution-timing guarantees, the daily limits, the report files and the CLI."""
import sys

import numpy as np
import pandas as pd
import pytest

from backtest import setup_backtest
from backtest.config import load_config
from backtest.setup_backtest import run_setup_backtest, sanitize_spread, write_report
from backtest.symbols import get_symbol_spec
from conftest import make_synthetic_ohlc
from setups.trend_pullback import TrendPullbackParams, load_setup_params

CONFIG_PATH = "config/setup_xauusd.toml"


def _bars(n=12000, seed=7):
    base = make_synthetic_ohlc(n, freq="15min", start_price=4000.0, seed=seed, spread_points=25.0)
    higher = (
        base.set_index("time")
        .resample("1h")
        .agg({"open": "first", "high": "max", "low": "min", "close": "last", "tick_volume": "sum", "spread": "max"})
        .dropna()
        .reset_index()
    )
    return base, higher


@pytest.fixture(scope="module")
def run():
    base, higher = _bars()
    cfg = load_config(CONFIG_PATH)
    params = load_setup_params(CONFIG_PATH)
    spec = get_symbol_spec(cfg.symbol)
    return run_setup_backtest(base, higher, cfg, params, spec), cfg, params, spec, base, higher


def test_result_has_trades_with_r_multiples_and_a_verdict(run):
    result, *_ = run
    t = result.trades
    assert len(t) > 20, "synthetic data should still produce a meaningful number of trades"
    assert {"r_multiple", "risk_money", "direction", "entry_time", "signal_time"} <= set(t.columns)
    assert t["r_multiple"].notna().all()
    assert result.stats["trades"] == len(t)
    assert result.verdict.startswith("NO VERDICT"), "a few dozen trades must never earn a verdict"
    assert result.breakdowns["by_session"], "breakdowns are built"


def test_every_trade_enters_after_its_signal_bar_closes_and_exits_after_entry(run):
    t = run[0].trades
    bar = pd.Timedelta(minutes=15)
    assert ((t["entry_time"] - t["signal_time"]) >= bar).all(), "entry is the NEXT bar's open, never the signal bar's"
    assert (t["exit_time"] >= t["entry_time"]).all()


def test_trades_respect_the_session_and_the_daily_trade_cap(run):
    result, cfg, params, *_ = run
    t = result.trades
    hours = t["signal_time"].dt.hour
    assert hours.between(params.session_start_utc, params.session_end_utc - 1).all()
    assert not ((t["signal_time"].dt.dayofweek == 4) & (hours >= params.friday_cutoff_utc)).any()
    per_day = t.groupby(t["signal_time"].dt.date).size()
    assert per_day.max() <= cfg.risk.max_trades_per_day


def test_each_trade_uses_its_own_stop_and_a_2r_target_and_risks_about_one_percent(run):
    result, cfg, params, spec, *_ = run
    t = result.trades
    risk_distance = (t["entry_price"] - t["stop_loss"]).abs()
    reward_distance = (t["take_profit"] - t["entry_price"]).abs()
    assert (reward_distance / risk_distance).between(params.rr - 0.01, params.rr + 0.01).all()
    # Position sizing follows the per-trade stop: money at risk stays near risk_percent of equity, not near-constant lots.
    assert t["lots"].nunique() > 3
    assert (t["risk_money"] <= cfg.initial_balance * 2 * cfg.risk.risk_percent / 100).all()


def test_the_run_is_deterministic(run):
    result, cfg, params, spec, base, higher = run
    again = run_setup_backtest(base, higher, cfg, params, spec)
    pd.testing.assert_frame_equal(result.trades.drop(columns=["trade_id"]), again.trades.drop(columns=["trade_id"]))


def test_a_pure_random_walk_does_not_show_a_positive_edge(run):
    """Sanity check against self-deception: the pipeline must not manufacture
    profit from data with no structure in it (costs alone should drag it
    below zero)."""
    result = run[0]
    assert result.metrics["net_profit"] < 0 or result.stats["expectancy_r_ci95_low"] <= 0


def test_sanitize_spread_repairs_zero_bars_with_the_median():
    df = pd.DataFrame({"spread": [20.0, 30.0, 0.0, np.nan, 40.0]})
    fixed, n = sanitize_spread(df)
    assert n == 2 and fixed["spread"].tolist() == [20.0, 30.0, 30.0, 30.0, 40.0]
    assert sanitize_spread(pd.DataFrame({"x": [1]}))[1] == 0


def test_too_little_history_fails_loudly():
    base, higher = _bars(n=200)
    cfg = load_config(CONFIG_PATH)
    with pytest.raises(ValueError):
        run_setup_backtest(base, higher, cfg, TrendPullbackParams(), get_symbol_spec(cfg.symbol))


def test_write_report_creates_the_expected_files(run, tmp_path):
    result, cfg, params, spec, *_ = run
    out = write_report(result, cfg, params, spec, out_root=tmp_path)
    for name in ("report.html", "summary.json", "trades.csv", "equity.csv", "equity_curve.svg"):
        assert (out / name).exists(), name
    assert (tmp_path / "latest" / "report.html").exists()
    html = (out / "report.html").read_text()
    assert "NO VERDICT" in html and "Setup parameters (frozen)" in html


def test_cli_runs_offline_from_csv_files(run, tmp_path, monkeypatch, capsys):
    _, _, _, _, base, higher = run
    base.to_csv(tmp_path / "m15.csv", index=False)
    higher.to_csv(tmp_path / "h1.csv", index=False)
    monkeypatch.setattr(
        sys, "argv",
        ["setup_backtest", "--config", CONFIG_PATH, "--base-csv", str(tmp_path / "m15.csv"),
         "--higher-csv", str(tmp_path / "h1.csv"), "--out", str(tmp_path / "reports")],
    )
    setup_backtest.main()
    out = capsys.readouterr().out
    assert "VERDICT:" in out and "Trades taken:" in out
    assert (tmp_path / "reports" / "latest" / "summary.json").exists()
