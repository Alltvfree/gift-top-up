"""Grid / random search optimizer.

Runs a backtest for each parameter candidate and ranks them by an objective.
Every result is saved (spec §23). Objectives require a minimum trade count so a
2-trade fluke can't top the ranking.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.config import BotConfig
from app.core.logging import get_logger, log_event
from app.core.models import Candle, SymbolInfo, Timeframe
from app.backtesting.engine import Backtester
from app.backtesting.metrics import Metrics, compute_metrics
from app.optimization.space import (
    apply_overrides,
    grid_candidates,
    random_candidates,
    validate_grid,
)
from app.strategies.factory import create_strategy

log = get_logger("optimization.optimizer")

_OBJECTIVES = {
    "net_profit": lambda m: m.net_profit,
    "profit_factor": lambda m: m.profit_factor,
    "expectancy": lambda m: m.expectancy,
    "expectancy_r": lambda m: m.expectancy_r,
    "sharpe": lambda m: m.sharpe_ratio,
}
_LARGE = 1e9  # cap for infinite profit factor when ranking


@dataclass
class OptimizationResult:
    params: Dict[str, Any]
    score: float
    net_profit: float
    total_trades: int
    metrics: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


class Optimizer:
    def __init__(
        self,
        base_config: BotConfig,
        symbol_info: SymbolInfo,
        candles: Dict[Timeframe, List[Candle]],
        param_grid: Dict[str, List[Any]],
        *,
        objective: str = "profit_factor",
        min_trades: int = 5,
        starting_balance: float = 10_000.0,
        commission_per_lot: float = 0.0,
        slippage_points: float = 0.0,
        trade_start=None,
        trade_end=None,
    ) -> None:
        if objective not in _OBJECTIVES:
            raise ValueError(f"unknown objective '{objective}'")
        self.base_config = base_config
        self.symbol_info = symbol_info
        self.candles = candles
        self.param_grid = param_grid
        self.objective = objective
        self.min_trades = min_trades
        self.starting_balance = starting_balance
        self._commission = commission_per_lot
        self._slippage = slippage_points
        self._trade_start = trade_start
        self._trade_end = trade_end
        self.warnings = validate_grid(param_grid)
        for w in self.warnings:
            log_event(log, "OPTIMIZATION_WARNING", w, level=30)

    def score(self, metrics: Metrics) -> float:
        if metrics.total_trades < self.min_trades:
            return float("-inf")
        value = _OBJECTIVES[self.objective](metrics)
        if math.isinf(value):
            return _LARGE
        return value

    def _evaluate(self, overrides: Dict[str, Any]) -> OptimizationResult:
        config = apply_overrides(self.base_config, overrides)
        bt = Backtester(
            config, create_strategy(config), self.symbol_info, self.candles,
            starting_balance=self.starting_balance,
            commission_per_lot=self._commission, slippage_points=self._slippage,
        )
        result = bt.run(trade_start=self._trade_start, trade_end=self._trade_end)
        metrics = compute_metrics(result)
        return OptimizationResult(
            params=overrides, score=self.score(metrics),
            net_profit=result.net_profit, total_trades=metrics.total_trades,
            metrics=metrics.to_dict(),
        )

    def run(
        self, method: str = "grid", *, n_iter: int = 20, seed: int = 0
    ) -> List[OptimizationResult]:
        if method == "grid":
            candidates = grid_candidates(self.param_grid)
        elif method == "random":
            candidates = random_candidates(self.param_grid, n_iter, seed=seed)
        else:
            raise ValueError(f"unknown method '{method}'")

        results = [self._evaluate(c) for c in candidates]
        results.sort(key=lambda r: r.score, reverse=True)
        log_event(
            log, "OPTIMIZATION_DONE", f"evaluated {len(results)} candidates",
            method=method, objective=self.objective,
            best_score=results[0].score if results else None,
        )
        return results

    @property
    def best(self) -> Optional[OptimizationResult]:  # convenience after run()
        return None


def save_results(results: List[OptimizationResult], path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump([r.to_dict() for r in results], fh, indent=2, default=str)


__all__ = ["Optimizer", "OptimizationResult", "save_results"]
