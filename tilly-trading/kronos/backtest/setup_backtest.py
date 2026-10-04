"""Backtest a rule-based setup (setups/trend_pullback.py) through the SAME
realistic execution engine the ML backtester uses — historical spread,
slippage, commission, next-bar-open entry, conservative same-bar exits,
risk-based sizing — then judge it with setup_stats.py.

No model is trained and no parameter is fit here: the rules are fixed, so
the whole history is out-of-sample for them. That only stays true if you
don't edit the [setup] table after looking at the result — doing so turns
this into curve-fitting and invalidates the verdict.

Run from inside kronos/ (on the Windows VPS, with MT5 open):

    python -m backtest.setup_backtest --config config/setup_xauusd.toml
    python -m backtest.setup_backtest --config config/setup_xauusd.toml --symbol XAUUSD   # real account
    python -m backtest.setup_backtest --config config/setup_xauusd.toml --base-csv m15.csv --higher-csv h1.csv
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # kronos/ itself, for features/setups

from features import compute_features, merge_higher_timeframe  # noqa: E402
from setups.trend_pullback import TrendPullbackParams, generate_signals, load_setup_params  # noqa: E402

from . import charts  # noqa: E402
from .account import Account  # noqa: E402
from .config import BacktestConfig, config_to_dict, load_config  # noqa: E402
from .data_quality import DataQualityReport, validate_ohlc  # noqa: E402
from .leakage_audit import audit_merge, verify_higher_timeframe_alignment  # noqa: E402
from .metrics import trading_metrics  # noqa: E402
from .setup_stats import MIN_TRADES_FOR_VERDICT, add_r_multiple, build_breakdowns, edge_stats, verdict  # noqa: E402
from .simulator import run_simulation, trades_to_frame  # noqa: E402
from .symbols import SymbolSpec, from_mt5, get_symbol_spec  # noqa: E402
from .timeframes import TIMEFRAME_MINUTES, bars_per_year  # noqa: E402

# Lead-in bars dropped before simulating: EMA 50, the 100-bar ATR average and
# the higher timeframe's swings/EMA all need history before they mean anything.
WARMUP_BARS = 250


@dataclass
class SetupBacktestResult:
    trades: pd.DataFrame
    equity_curve: pd.DataFrame
    signals: pd.DataFrame
    metrics: dict
    stats: dict
    breakdowns: dict
    verdict: str
    warnings: list[str] = field(default_factory=list)


def sanitize_spread(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """MT5 can record a 0 (or missing) spread on a bar — a feed glitch, not a
    free trade. Replace those with the data's own median positive spread so
    one bad bar can't crash the run or fake a zero-cost fill. Returns the
    count repaired so it shows up in the report's warnings."""
    out = df.copy()
    if "spread" not in out.columns:
        return out, 0
    bad = ~(out["spread"] > 0)
    positive = out.loc[~bad, "spread"]
    if bad.any() and len(positive):
        out.loc[bad, "spread"] = float(positive.median())
    return out, int(bad.sum()) if len(positive) else 0


def build_signal_frame(
    base_raw: pd.DataFrame,
    higher_raw: pd.DataFrame,
    params: TrendPullbackParams,
    spec: SymbolSpec,
) -> pd.DataFrame:
    base_feats = compute_features(base_raw.reset_index(drop=True))
    higher_feats = compute_features(higher_raw.reset_index(drop=True))
    # Same hard guard the walk-forward backtester has: a corrupted
    # higher-timeframe merge must halt the run, never be swallowed.
    verify_higher_timeframe_alignment(
        audit_merge(base_feats, higher_feats, params.higher_prefix), higher_raw, params.higher_prefix
    )
    merged = merge_higher_timeframe(base_feats, higher_feats, prefix=params.higher_prefix)
    return generate_signals(merged.reset_index(drop=True), params, spec.point)


def run_setup_backtest(
    base_raw: pd.DataFrame,
    higher_raw: pd.DataFrame,
    cfg: BacktestConfig,
    params: TrendPullbackParams,
    spec: SymbolSpec,
    min_trades: int = MIN_TRADES_FOR_VERDICT,
    data_quality_reports: list[DataQualityReport] | None = None,
) -> SetupBacktestResult:
    warnings: list[str] = []
    if cfg.spread.mode == "historical":
        base_raw, repaired = sanitize_spread(base_raw)
        if repaired:
            warnings.append(f"{repaired} bar(s) had a zero/missing recorded spread and were set to the data's median spread.")

    frame = build_signal_frame(base_raw, higher_raw, params, spec)
    sim_df = frame.iloc[WARMUP_BARS:].reset_index(drop=True)
    if sim_df.empty:
        raise ValueError(f"Only {len(frame)} bars — need more than the {WARMUP_BARS}-bar warmup. Download more history.")

    signal_rows = sim_df[sim_df["setup_buy"] | sim_df["setup_sell"]]
    account = Account(cfg.initial_balance, cfg.currency)
    trades = run_simulation(sim_df, cfg, spec, account, window_index=0)
    trades_df = trades_to_frame(trades)
    equity = account.to_frame()

    if trades_df.empty:
        metrics = trading_metrics(trades_df, equity, cfg.initial_balance, bars_per_year(cfg.timeframe))
        stats: dict = {"trades": 0}
        breakdowns: dict = {}
    else:
        trades_df = add_r_multiple(trades_df, spec)
        metrics = trading_metrics(trades_df, equity, cfg.initial_balance, bars_per_year(cfg.timeframe))
        stats = edge_stats(trades_df, seed=cfg.random_seed)
        breakdowns = build_breakdowns(trades_df)

    n = stats.get("trades", 0)
    skipped = len(signal_rows) - n
    if skipped > 0:
        warnings.append(
            f"{len(signal_rows)} setups fired but {n} trades were taken: the rest were blocked by an open "
            "position, the cooldown, a daily limit, or a stop too tight to size at the minimum lot."
        )
    if n < min_trades:
        warnings.append(f"Sample too small: {n} trades < {min_trades}. Download more bars (--bars) — don't loosen the rules to reach the count.")
    if cfg.slippage.mode == "fixed_points":
        warnings.append("Slippage is a fixed-point estimate, not measured from real fills.")
    for dq in data_quality_reports or []:
        if not dq.is_clean:
            warnings.append(f"{dq.symbol} {dq.timeframe}: data-quality issues repaired/discarded ({dq.rows_discarded} rows) — see report.")
    warnings.append(
        "News events are not segmented: there is no historical economic calendar in this backtest, "
        "so FOMC/CPI/NFP moves are inside the totals, not separated."
    )
    warnings.append("One configuration, tested once. If you change the [setup] rules after seeing this result, the verdict no longer applies.")

    return SetupBacktestResult(
        trades=trades_df, equity_curve=equity, signals=signal_rows, metrics=metrics, stats=stats,
        breakdowns=breakdowns, verdict=verdict(stats, metrics.get("net_profit", 0.0), min_trades), warnings=warnings,
    )


def _fmt(v) -> str:
    if isinstance(v, float):
        return f"{v:,.4f}" if abs(v) < 1000 else f"{v:,.2f}"
    return str(v)


def _kv(d: dict) -> str:
    return "<table class='kv'>" + "".join(f"<tr><td>{k}</td><td>{_fmt(v)}</td></tr>" for k, v in d.items()) + "</table>"


def _grid(rows: list[dict]) -> str:
    if not rows:
        return "<p><em>None.</em></p>"
    cols = list(rows[0])
    head = "".join(f"<th>{c}</th>" for c in cols)
    body = "".join("<tr>" + "".join(f"<td>{_fmt(r[c])}</td>" for c in cols) + "</tr>" for r in rows)
    return f"<table class='grid'><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def write_report(
    result: SetupBacktestResult, cfg: BacktestConfig, params: TrendPullbackParams, spec: SymbolSpec,
    out_root: str | Path = "reports/setup",
) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    out_dir = Path(out_root) / stamp
    out_dir.mkdir(parents=True, exist_ok=True)

    result.trades.to_csv(out_dir / "trades.csv", index=False)
    result.equity_curve.to_csv(out_dir / "equity.csv", index=False)
    summary = {
        "generated_at_utc": stamp, "verdict": result.verdict, "edge_stats": result.stats,
        "trading_metrics": result.metrics, "setup_params": params.__dict__,
        "config": config_to_dict(cfg), "symbol_spec": spec.__dict__, "warnings": result.warnings,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    charts.write_charts(result.equity_curve, result.trades, out_dir)

    bad = result.verdict.startswith(("NEGATIVE", "NO EDGE", "NO VERDICT"))
    sections = "".join(
        f"<div class='section'><h2>{title}</h2>{_grid(rows)}</div>"
        for title, rows in (
            ("By direction", result.breakdowns.get("by_direction", [])),
            ("By session (signal-entry hour, UTC)", result.breakdowns.get("by_session", [])),
            ("By weekday", result.breakdowns.get("by_weekday", [])),
            ("By month", result.breakdowns.get("by_month", [])),
            ("First half vs second half of the sample", result.breakdowns.get("by_time_half", [])),
            ("By exit reason", result.breakdowns.get("by_exit_reason", [])),
        )
    )
    html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Setup Backtest</title>
<style>
body {{ font-family: -apple-system, Segoe UI, Arial, sans-serif; margin: 2rem; color:#1a1a1a; background:#fafafa; }}
h2 {{ border-bottom: 2px solid #ddd; padding-bottom: .3rem; }}
.verdict {{ font-size:1.05rem; font-weight:600; padding:1rem; border-radius:6px; background:{"#fdecea" if bad else "#eafaf1"}; }}
table {{ border-collapse: collapse; margin:.5rem 0; font-size:.85rem; }}
table.kv td {{ padding:3px 10px; }} table.kv td:first-child {{ font-weight:600; color:#555; }}
table.grid th, table.grid td {{ border:1px solid #ddd; padding:4px 8px; text-align:right; }}
table.grid th {{ background:#f0f0f0; }}
img {{ max-width:100%; border:1px solid #eee; }}
.section {{ background:#fff; padding:1rem 1.5rem; border-radius:8px; margin-bottom:1rem; }}
</style></head><body>
<h1>Trend-pullback setup — {spec.symbol} {cfg.timeframe}+{cfg.higher_timeframe}</h1>
<p>generated {stamp} UTC</p>
<div class='section'><h2>Verdict</h2><div class='verdict'>{result.verdict}</div></div>
<div class='section'><h2>Edge statistics (in R, net of costs)</h2>{_kv(result.stats)}</div>
<div class='section'><h2>Trading metrics</h2>{_kv(result.metrics)}</div>
<div class='section'><h2>Equity</h2><img src='equity_curve.svg'><img src='drawdown.svg'><img src='trade_distribution.svg'></div>
{sections}
<div class='section'><h2>Setup parameters (frozen)</h2>{_kv(params.__dict__)}</div>
<div class='section'><h2>Warnings</h2><ul>{"".join(f"<li>{w}</li>" for w in result.warnings)}</ul></div>
</body></html>"""
    (out_dir / "report.html").write_text(html)

    latest = Path(out_root) / "latest"
    if latest.exists():
        shutil.rmtree(latest)
    shutil.copytree(out_dir, latest)
    return out_dir


def _load_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    if "spread" not in df.columns:
        df["spread"] = np.nan
    return df


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default="config/setup_xauusd.toml")
    parser.add_argument("--symbol", default=None, help="Overrides the config's symbol (XAUUSDm demo, XAUUSD real account).")
    parser.add_argument("--bars", type=int, default=50000, help="Base-timeframe bars to download.")
    parser.add_argument("--initial-balance", type=float, default=None)
    parser.add_argument("--min-trades", type=int, default=MIN_TRADES_FOR_VERDICT)
    parser.add_argument("--spec-from-mt5", action="store_true", help="Use the live terminal's contract spec for the symbol.")
    parser.add_argument("--base-csv", default=None, help="Offline base-timeframe bars (time,open,high,low,close,tick_volume,spread).")
    parser.add_argument("--higher-csv", default=None, help="Offline higher-timeframe bars; required with --base-csv.")
    parser.add_argument("--out", default="reports/setup")
    args = parser.parse_args()

    cfg = load_config(args.config)
    params = load_setup_params(args.config)
    if args.symbol:
        cfg.symbol = args.symbol
    if args.initial_balance:
        cfg.initial_balance = args.initial_balance
    if not cfg.higher_timeframe:
        raise SystemExit("The setup needs a higher_timeframe in the config (its trend filter reads it).")

    spec = from_mt5(cfg.symbol) if args.spec_from_mt5 else get_symbol_spec(cfg.symbol)

    if args.base_csv:
        if not args.higher_csv:
            raise SystemExit("--base-csv needs --higher-csv too.")
        base_raw, higher_raw = _load_csv(args.base_csv), _load_csv(args.higher_csv)
    else:
        from bars import closed_bars_only  # noqa: E402
        from mt5_data import bars_to_cover_same_span, connect, disconnect, download_history, server_time_now  # noqa: E402

        connect()
        try:
            base_raw = download_history(cfg.symbol, cfg.timeframe, args.bars)
            higher_raw = download_history(
                cfg.symbol, cfg.higher_timeframe, bars_to_cover_same_span(cfg.timeframe, args.bars, cfg.higher_timeframe)
            )
            # The newest row MT5 returns is the still-forming bar — not history.
            now = server_time_now(cfg.symbol)
            base_raw = closed_bars_only(base_raw, TIMEFRAME_MINUTES[cfg.timeframe.upper()], now)
            higher_raw = closed_bars_only(higher_raw, TIMEFRAME_MINUTES[cfg.higher_timeframe.upper()], now)
        finally:
            disconnect()

    base_minutes = TIMEFRAME_MINUTES.get(cfg.timeframe.upper())
    gap = pd.Timedelta(minutes=base_minutes) if base_minutes else None
    base_raw, base_dq = validate_ohlc(base_raw, cfg.symbol, cfg.timeframe, gap)
    higher_raw, higher_dq = validate_ohlc(higher_raw, cfg.symbol, cfg.higher_timeframe)

    result = run_setup_backtest(base_raw, higher_raw, cfg, params, spec, args.min_trades, [base_dq, higher_dq])
    out_dir = write_report(result, cfg, params, spec, args.out)

    s, m = result.stats, result.metrics
    print(f"Report written to {out_dir} (mirrored to {Path(args.out) / 'latest'})")
    print(f"{spec.symbol} {cfg.timeframe}+{cfg.higher_timeframe}: {base_raw['time'].iloc[0]} -> {base_raw['time'].iloc[-1]}")
    print(f"Setups fired: {len(result.signals)}   Trades taken: {s.get('trades', 0)}")
    if s.get("trades"):
        print(
            f"Win rate {s['win_rate']:.1%} (break-even {s['breakeven_win_rate']:.1%})  "
            f"expectancy {s['expectancy_r']:+.3f}R  95% CI [{s['expectancy_r_ci95_low']:+.3f}, {s['expectancy_r_ci95_high']:+.3f}]"
        )
        print(
            f"Net profit {m['net_profit']:+,.2f} ({m['net_profit_percent']:+.2f}%)  profit factor {m['profit_factor']:.2f}  "
            f"max drawdown {m['max_drawdown_percent']:.2f}%  worst losing streak {m['consecutive_losses']}"
        )
    print(f"VERDICT: {result.verdict}")


if __name__ == "__main__":
    main()
