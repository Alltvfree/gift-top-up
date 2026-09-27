"""CLI entrypoint (Phase 22). Run from inside kronos/:

    python -m backtest --symbol BTCUSDm --config config/backtest.yaml --quick
    python -m backtest --symbol BTCUSDm --config config/backtest.yaml --full
    python -m backtest --symbol XAUUSDm --config config/backtest.yaml --full

(Not `backtest.py` — a same-named script and package can't coexist cleanly
in one directory, and this project already uses flat per-tool scripts
(train.py, infer.py) alongside packages, so `-m` is the unambiguous way to
run a package as the entrypoint without a naming collision.)

--quick forces a small, fast smoke-test shape (~5,000 bars, short
walk-forward windows) regardless of what config/backtest.yaml says, for a
development sanity check. --full uses the config file's own walk-forward
window sizes and downloads enough history to cover them.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # kronos/ itself, for mt5_data/features/train

from mt5_data import bars_to_cover_same_span, connect, disconnect, download_history  # noqa: E402

from .config import load_config  # noqa: E402
from .data_quality import validate_ohlc  # noqa: E402
from .leakage_audit import build_audit_table  # noqa: E402
from .report import generate_report  # noqa: E402
from .symbols import from_mt5, get_symbol_spec  # noqa: E402
from .timeframes import TIMEFRAME_MINUTES  # noqa: E402
from .walk_forward import run_walk_forward  # noqa: E402

DEFAULT_LGB_PARAMS = {
    "objective": "binary", "metric": "auc", "verbosity": -1, "num_leaves": 31, "learning_rate": 0.05,
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default=None, help="Overrides the symbol in --config, if given.")
    parser.add_argument("--config", default=None, help="Path to a backtest.yaml. Omit for pure defaults.")
    parser.add_argument("--higher-timeframe", default=None, help="Overrides the config's higher_timeframe.")
    parser.add_argument("--bars", type=int, default=None, help="Override the number of base-timeframe bars to download.")
    parser.add_argument("--out", default="reports")
    parser.add_argument("--spec-from-mt5", action="store_true", help="Import the symbol's contract spec from the live MT5 terminal instead of the built-in defaults.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--quick", action="store_true", help="Small, fast smoke test.")
    mode.add_argument("--full", action="store_true", help="Full historical walk-forward test using the config's own window sizes.")
    args = parser.parse_args()

    cfg = load_config(args.config)
    if args.symbol:
        cfg.symbol = args.symbol
    if args.higher_timeframe:
        cfg.higher_timeframe = args.higher_timeframe

    if args.quick:
        cfg.walk_forward.train_days, cfg.walk_forward.validation_days = 10, 3
        cfg.walk_forward.test_days, cfg.walk_forward.step_days = 3, 3
        bars = args.bars or 6000
    else:
        bars = args.bars or 50000

    spec = from_mt5(cfg.symbol) if args.spec_from_mt5 else get_symbol_spec(cfg.symbol)

    connect()
    try:
        base_raw = download_history(cfg.symbol, cfg.timeframe, bars)
        higher_raw = None
        if cfg.higher_timeframe:
            higher_bars = bars_to_cover_same_span(cfg.timeframe, bars, cfg.higher_timeframe)
            higher_raw = download_history(cfg.symbol, cfg.higher_timeframe, higher_bars)
    finally:
        disconnect()

    expected_gap = None
    base_minutes = TIMEFRAME_MINUTES.get(cfg.timeframe.upper())
    if base_minutes:
        import pandas as pd
        expected_gap = pd.Timedelta(minutes=base_minutes)
    base_raw, base_dq = validate_ohlc(base_raw, cfg.symbol, cfg.timeframe, expected_gap)
    dq_reports = [base_dq]
    if higher_raw is not None:
        higher_raw, higher_dq = validate_ohlc(higher_raw, cfg.symbol, cfg.higher_timeframe)
        dq_reports.append(higher_dq)

    result = run_walk_forward(base_raw, cfg, spec, higher_raw=higher_raw, lgb_params=DEFAULT_LGB_PARAMS)

    from train import feature_columns_for  # noqa: E402 - after sys.path insert above

    higher_prefix = cfg.higher_timeframe.lower() if cfg.higher_timeframe else None
    leakage_entries = build_audit_table(has_higher_timeframe=bool(cfg.higher_timeframe))
    out_dir = generate_report(
        result, cfg, spec, leakage_entries, dq_reports,
        feature_columns_for(higher_prefix), DEFAULT_LGB_PARAMS, out_root=args.out,
    )

    print(f"Report written to {out_dir} (and mirrored to {Path(args.out) / 'latest'})")
    windows_run = [w for w in result.windows if not w.skipped_reason]
    windows_skipped = [w for w in result.windows if w.skipped_reason]
    print(f"Windows: {len(windows_run)} run, {len(windows_skipped)} skipped, out of {len(result.windows)} total")
    print(f"Overall model AUC: {result.overall_model_metrics.get('auc')}")
    print(f"Overall trades: {result.overall_trading_metrics.get('total_trades')}, "
          f"net profit: {result.overall_trading_metrics.get('net_profit')}, "
          f"max drawdown %: {result.overall_trading_metrics.get('max_drawdown_percent')}")


if __name__ == "__main__":
    main()
