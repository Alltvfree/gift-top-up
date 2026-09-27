"""Report generation (Phases 16, 18, 19, 20, 26) — HTML dashboard + CSV/
JSON exports, written to a timestamped directory and mirrored to
reports/latest/ for convenience.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from . import charts
from .config import BacktestConfig, config_to_dict
from .data_quality import DataQualityReport
from .leakage_audit import LeakageAuditEntry
from .symbols import SymbolSpec
from .walk_forward import WalkForwardResult


def _git_revision() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5, check=False
        )
        return out.stdout.strip() or "unknown"
    except Exception:  # noqa: BLE001 - reproducibility metadata is best-effort, never fatal
        return "unknown"


def build_warnings(
    result: WalkForwardResult,
    cfg: BacktestConfig,
    data_quality_reports: list[DataQualityReport],
) -> list[str]:
    warnings: list[str] = []
    total_test_rows = sum(w.test_rows for w in result.windows)
    total_trades = len(result.all_trades)
    if total_test_rows < 200:
        warnings.append(f"Small total test sample ({total_test_rows} rows across all windows) — treat results as low-confidence.")
    if total_trades < 30:
        warnings.append(f"Few trades ({total_trades} total) — win rate / profit factor / Sharpe are noisy at this sample size.")
    skipped = [w for w in result.windows if w.skipped_reason]
    if skipped:
        warnings.append(f"{len(skipped)} of {len(result.windows)} walk-forward window(s) were skipped — see the Walk-Forward Windows table.")
    if cfg.spread.mode != "historical":
        warnings.append(f"Spread is {cfg.spread.mode}-modeled, not historical — real costs may differ from this estimate.")
    if cfg.slippage.mode == "fixed_points":
        warnings.append("Slippage is a fixed-point estimate, not measured from real fills.")
    if cfg.commission.type != "per_lot":
        warnings.append(f"Commission modeled as {cfg.commission.type}, not the broker's actual per-lot schedule — confirm against your account.")
    for dq in data_quality_reports:
        if not dq.is_clean:
            warnings.append(
                f"{dq.symbol} {dq.timeframe}: data-quality issues found and repaired/discarded "
                f"({dq.rows_discarded} rows discarded) — see the data-quality notes."
            )
    warnings.append(
        "Parameters (threshold/TP/SL/LightGBM params) were NOT optimized against any test-set "
        "result in this run — see the Leakage Audit section."
    )
    return warnings


def generate_report(
    result: WalkForwardResult,
    cfg: BacktestConfig,
    spec: SymbolSpec,
    leakage_entries: list[LeakageAuditEntry],
    data_quality_reports: list[DataQualityReport],
    feature_columns: list[str],
    lgb_params: dict,
    out_root: str | Path = "reports",
) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    out_dir = Path(out_root) / timestamp
    out_dir.mkdir(parents=True, exist_ok=True)

    warnings = build_warnings(result, cfg, data_quality_reports)

    result.all_trades.to_csv(out_dir / "trades.csv", index=False)
    result.equity_curve.to_csv(out_dir / "equity.csv", index=False)
    result.predictions.to_csv(out_dir / "predictions.csv", index=False)

    wf_rows = [
        {
            "window_id": w.window.index,
            "train_start": w.window.train_start, "train_end": w.window.train_end,
            "validation_start": w.window.val_start, "validation_end": w.window.val_end,
            "test_start": w.window.test_start, "test_end": w.window.test_end,
            "samples": w.test_rows, "trades": w.trading_metrics.get("total_trades", 0),
            "auc": w.model_metrics.get("auc"), "accuracy": w.model_metrics.get("accuracy"),
            "win_rate": w.trading_metrics.get("win_rate"),
            "profit_factor": w.trading_metrics.get("profit_factor"),
            "net_profit": w.trading_metrics.get("net_profit"),
            "return_percent": w.trading_metrics.get("net_profit_percent"),
            "max_drawdown": w.trading_metrics.get("max_drawdown"),
            "sharpe": w.trading_metrics.get("sharpe_ratio"),
            "sortino": w.trading_metrics.get("sortino_ratio"),
            "skipped_reason": w.skipped_reason,
        }
        for w in result.windows
    ]
    pd.DataFrame(wf_rows).to_csv(out_dir / "walk_forward.csv", index=False)

    meta = {
        "git_revision": _git_revision(),
        "generated_at_utc": timestamp,
        "config": config_to_dict(cfg),
        "lightgbm_params": lgb_params,
        "feature_columns": feature_columns,
        "target_definition": (
            f"P(TP-before-SL): entered {cfg.side} at close, TP={cfg.take_profit.value} "
            f"({cfg.take_profit.type}), SL={cfg.stop_loss.value} ({cfg.stop_loss.type}), "
            f"resolved within {cfg.execution.max_holding_bars} bars — see labels.label_tp_before_sl."
        ),
        "symbol_spec": spec.__dict__,
    }
    (out_dir / "config.json").write_text(json.dumps(meta, indent=2, default=str))
    (out_dir / "metrics.json").write_text(
        json.dumps(
            {"overall_model_metrics": result.overall_model_metrics, "overall_trading_metrics": result.overall_trading_metrics},
            indent=2, default=str,
        )
    )

    charts.equity_curve_chart(result.equity_curve, out_dir / "equity_curve.png")
    charts.drawdown_chart(result.equity_curve, out_dir / "drawdown.png")
    charts.trade_distribution_chart(result.all_trades, out_dir / "trade_distribution.png")

    html = _render_html(result, cfg, spec, leakage_entries, data_quality_reports, warnings, meta, wf_rows)
    (out_dir / "report.html").write_text(html)

    latest_dir = Path(out_root) / "latest"
    if latest_dir.exists():
        shutil.rmtree(latest_dir)
    shutil.copytree(out_dir, latest_dir)

    return out_dir


def _dict_table(d: dict) -> str:
    rows = "".join(f"<tr><td>{k}</td><td>{_fmt(v)}</td></tr>" for k, v in d.items())
    return f"<table class='kv'>{rows}</table>"


def _fmt(v) -> str:
    if isinstance(v, float):
        return f"{v:,.4f}" if abs(v) < 1000 else f"{v:,.2f}"
    return str(v)


def _records_table(records: list[dict]) -> str:
    if not records:
        return "<p><em>None.</em></p>"
    cols = list(records[0].keys())
    head = "".join(f"<th>{c}</th>" for c in cols)
    body = "".join(
        "<tr>" + "".join(f"<td>{_fmt(r.get(c))}</td>" for c in cols) + "</tr>" for r in records
    )
    return f"<table class='grid'><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _render_html(
    result: WalkForwardResult, cfg: BacktestConfig, spec: SymbolSpec,
    leakage_entries: list[LeakageAuditEntry], data_quality_reports: list[DataQualityReport],
    warnings: list[str], meta: dict, wf_rows: list[dict],
) -> str:
    tm = result.overall_trading_metrics
    mm = result.overall_model_metrics
    verdict = (
        "MODEL DOES NOT CURRENTLY SHOW POSITIVE RISK-ADJUSTED EXPECTANCY"
        if tm.get("net_profit", 0) <= 0 or tm.get("total_trades", 0) == 0
        else "Model shows positive expectancy after modeled costs in this backtest "
        "(still not a guarantee of future performance — see warnings)."
    )
    warnings_html = "".join(f"<li>{w}</li>" for w in warnings) or "<li>None.</li>"
    leakage_html = _records_table([{"category": e.category, "status": e.status, "detail": e.detail} for e in leakage_entries])
    dq_html = _records_table(
        [
            {"symbol": d.symbol, "timeframe": d.timeframe, "total_rows": d.total_rows,
             "duplicates": d.duplicate_timestamps, "out_of_order": d.out_of_order,
             "invalid_ohlc": d.invalid_ohlc, "discarded": d.rows_discarded, "notes": "; ".join(d.notes) or "none"}
            for d in data_quality_reports
        ]
    )
    trades_preview = result.all_trades.head(50).to_dict("records") if not result.all_trades.empty else []

    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Kronos Backtest Report</title>
<style>
body {{ font-family: -apple-system, Segoe UI, Arial, sans-serif; margin: 2rem; color: #1a1a1a; background:#fafafa; }}
h1 {{ margin-bottom: 0.2rem; }} h2 {{ border-bottom: 2px solid #ddd; padding-bottom: 0.3rem; margin-top: 2.5rem; }}
.verdict {{ font-size: 1.1rem; font-weight: 600; padding: 1rem; border-radius: 6px;
  background: {"#fdecea" if "DOES NOT" in verdict else "#eafaf1"}; }}
table {{ border-collapse: collapse; margin: 0.5rem 0; font-size: 0.85rem; }}
table.kv td {{ padding: 3px 10px; }} table.kv td:first-child {{ font-weight: 600; color: #555; }}
table.grid th, table.grid td {{ border: 1px solid #ddd; padding: 4px 8px; text-align: right; }}
table.grid th {{ background: #f0f0f0; text-align: center; }}
ul.warnings li {{ margin-bottom: 4px; }}
img {{ max-width: 100%; border: 1px solid #eee; margin: 0.5rem 0; }}
.section {{ background: white; padding: 1rem 1.5rem; border-radius: 8px; margin-bottom: 1rem; }}
</style></head>
<body>
<h1>Kronos Backtest Report</h1>
<p>{spec.symbol} · {cfg.timeframe}{' + ' + cfg.higher_timeframe if cfg.higher_timeframe else ''} · generated {meta['generated_at_utc']} UTC · git {meta['git_revision'][:12]}</p>

<div class="section"><h2>1. Executive Summary</h2>
<div class="verdict">{verdict}</div>
{_dict_table({k: tm.get(k) for k in ("total_trades","win_rate","net_profit","net_profit_percent","max_drawdown_percent","profit_factor","sharpe_ratio")})}
{_dict_table({k: mm.get(k) for k in ("auc","accuracy") if mm})}
</div>

<div class="section"><h2>2. Configuration</h2>{_dict_table(meta['config'])}</div>

<div class="section"><h2>3. Dataset</h2>{dq_html}</div>

<div class="section"><h2>4. Walk-Forward Configuration</h2>{_dict_table(meta['config'].get('walk_forward', {}))}</div>

<div class="section"><h2>5. Model Metrics (overall, out-of-sample)</h2>{_dict_table(mm)}</div>

<div class="section"><h2>6. Trading Metrics (overall)</h2>{_dict_table(tm)}</div>

<div class="section"><h2>7. Equity Curve</h2><img src="equity_curve.png"></div>

<div class="section"><h2>8. Drawdown</h2><img src="drawdown.png"></div>

<div class="section"><h2>9. Trade Distribution</h2><img src="trade_distribution.png"></div>

<div class="section"><h2>10. Costs</h2>{_dict_table({k: tm.get(k) for k in ("total_commission","total_spread_cost","total_slippage_cost")})}</div>

<div class="section"><h2>11. Walk-Forward Windows</h2>{_records_table(wf_rows)}</div>

<div class="section"><h2>12. Detailed Trade List (first 50; full list in trades.csv)</h2>{_records_table(trades_preview)}</div>

<div class="section"><h2>13. Leakage Audit</h2>{leakage_html}</div>

<div class="section"><h2>14. Warnings</h2><ul class="warnings">{warnings_html}</ul></div>

</body></html>"""
