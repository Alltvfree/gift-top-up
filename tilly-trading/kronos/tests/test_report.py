from backtest.config import BacktestConfig, ExecutionConfig, RiskConfig, WalkForwardConfig
from backtest.leakage_audit import build_audit_table
from backtest.report import generate_report
from backtest.symbols import get_symbol_spec
from backtest.walk_forward import run_walk_forward
from conftest import make_synthetic_ohlc


def test_generate_report_writes_all_expected_files(tmp_path):
    base_raw = make_synthetic_ohlc(7200, freq="5min", start_price=84000.0, seed=1)
    cfg = BacktestConfig(
        symbol="BTCUSDm", timeframe="M5", higher_timeframe=None,
        walk_forward=WalkForwardConfig(train_days=15, validation_days=3, test_days=3, step_days=5, embargo_minutes=0),
        risk=RiskConfig(mode="fixed_lot", fixed_lot=0.01),
        execution=ExecutionConfig(max_holding_bars=30),
    )
    spec = get_symbol_spec(cfg.symbol)
    result = run_walk_forward(base_raw, cfg, spec, higher_raw=None)
    leakage_entries = build_audit_table(has_higher_timeframe=False)

    out_dir = generate_report(
        result, cfg, spec, leakage_entries, data_quality_reports=[],
        feature_columns=["dummy"], lgb_params={"objective": "binary"}, out_root=str(tmp_path / "reports"),
    )

    expected = [
        "report.html", "trades.csv", "equity.csv", "predictions.csv", "walk_forward.csv",
        "config.json", "metrics.json", "equity_curve.png", "drawdown.png", "trade_distribution.png",
    ]
    for name in expected:
        assert (out_dir / name).exists(), f"missing {name}"
        assert (out_dir / name).stat().st_size > 0

    latest = tmp_path / "reports" / "latest"
    assert (latest / "report.html").exists()
    html = (latest / "report.html").read_text()
    assert "Leakage Audit" in html
    assert "Executive Summary" in html
