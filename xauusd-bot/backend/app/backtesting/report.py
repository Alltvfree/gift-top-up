"""Backtest reporting — curves, breakdowns and export.

Turns a :class:`BacktestResult` + :class:`Metrics` into the artefacts the spec
asks for (§21): equity curve, drawdown curve, monthly/daily performance and a
trade distribution — plus JSON/CSV export. Every backtest is reproducible from
its inputs; nothing here modifies the trades.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Tuple

from app.backtesting.metrics import Metrics, compute_metrics
from app.backtesting.models import BacktestResult


def drawdown_curve(equity_curve: List[Tuple]) -> List[Tuple]:
    """(timestamp, drawdown_pct_from_peak) for each equity sample."""
    out = []
    peak = float("-inf")
    for ts, equity in equity_curve:
        peak = max(peak, equity)
        dd_pct = ((peak - equity) / peak * 100) if peak > 0 else 0.0
        out.append((ts, round(dd_pct, 3)))
    return out


def monthly_performance(result: BacktestResult) -> Dict[str, float]:
    """Net profit grouped by YYYY-MM of trade exit."""
    buckets: Dict[str, float] = defaultdict(float)
    for t in result.trades:
        buckets[t.exit_time.strftime("%Y-%m")] += t.profit
    return {k: round(v, 2) for k, v in sorted(buckets.items())}


def daily_performance(result: BacktestResult) -> Dict[str, float]:
    """Net profit grouped by YYYY-MM-DD of trade exit."""
    buckets: Dict[str, float] = defaultdict(float)
    for t in result.trades:
        buckets[t.exit_time.strftime("%Y-%m-%d")] += t.profit
    return {k: round(v, 2) for k, v in sorted(buckets.items())}


def trade_distribution(result: BacktestResult, bin_size: float = 0.5) -> Dict[str, int]:
    """Histogram of trade outcomes bucketed by R-multiple."""
    buckets: Dict[str, int] = defaultdict(int)
    for t in result.trades:
        b = math_floor_bucket(t.r_multiple, bin_size)
        label = f"[{b:.1f}, {b + bin_size:.1f})R"
        buckets[label] += 1
    return dict(sorted(buckets.items(), key=lambda kv: float(kv[0].split(",")[0][1:])))


def math_floor_bucket(value: float, bin_size: float) -> float:
    import math
    return math.floor(value / bin_size) * bin_size


def build_report(result: BacktestResult) -> dict:
    """A JSON-serializable report combining metrics + curves + breakdowns."""
    metrics = compute_metrics(result)
    return {
        "symbol": result.symbol,
        "strategy": result.strategy,
        "strategy_version": result.strategy_version,
        "starting_balance": result.starting_balance,
        "ending_balance": result.ending_balance,
        "net_profit": result.net_profit,
        "bars_processed": result.bars_processed,
        "metrics": metrics.to_dict(),
        "equity_curve": [(ts.isoformat(), eq) for ts, eq in result.equity_curve],
        "drawdown_curve": [(ts.isoformat(), dd)
                           for ts, dd in drawdown_curve(result.equity_curve)],
        "monthly_performance": monthly_performance(result),
        "daily_performance": daily_performance(result),
        "trade_distribution": trade_distribution(result),
    }


def export_json(result: BacktestResult, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(build_report(result), fh, indent=2, default=str)


def export_trades_csv(result: BacktestResult, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow([
            "signal_id", "side", "entry_time", "exit_time", "entry", "exit",
            "volume", "initial_sl", "take_profit", "profit", "r_multiple",
            "close_reason", "bars_held",
        ])
        for t in result.trades:
            row = asdict(t)
            row["side"] = t.side.value
            writer.writerow([
                row["signal_id"], row["side"], t.entry_time.isoformat(),
                t.exit_time.isoformat(), row["entry"], row["exit"], row["volume"],
                row["initial_sl"], row["take_profit"], row["profit"],
                row["r_multiple"], row["close_reason"], row["bars_held"],
            ])


__all__ = [
    "drawdown_curve", "monthly_performance", "daily_performance",
    "trade_distribution", "build_report", "export_json", "export_trades_csv",
]
