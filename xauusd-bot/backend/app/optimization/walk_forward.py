"""Walk-forward testing.

Splits history into consecutive **train / validation / out-of-sample** windows.
Parameters are optimized on TRAIN only, checked on VALIDATION, and then measured
on OUT-OF-SAMPLE data that was never used for selection (spec §22). Each fold is
graded for overfitting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Dict, List, Optional

from app.core.config import BotConfig
from app.core.models import Candle, SymbolInfo, Timeframe
from app.backtesting.engine import Backtester
from app.backtesting.metrics import Metrics, compute_metrics
from app.optimization.optimizer import Optimizer
from app.optimization.overfitting import OverfittingReport, assess
from app.optimization.space import apply_overrides
from app.strategies.factory import create_strategy


@dataclass
class Fold:
    index: int
    best_params: Dict[str, Any]
    train: Metrics
    validation: Metrics
    out_of_sample: Metrics
    overfitting: OverfittingReport

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "best_params": self.best_params,
            "train": self.train.to_dict(),
            "validation": self.validation.to_dict(),
            "out_of_sample": self.out_of_sample.to_dict(),
            "overfitting": self.overfitting.to_dict(),
        }


class WalkForward:
    def __init__(
        self,
        base_config: BotConfig,
        symbol_info: SymbolInfo,
        candles: Dict[Timeframe, List[Candle]],
        param_grid: Dict[str, List[Any]],
        *,
        train_bars: int,
        validation_bars: int,
        oos_bars: int,
        step_bars: Optional[int] = None,
        objective: str = "profit_factor",
        min_trades: int = 5,
        starting_balance: float = 10_000.0,
    ) -> None:
        self.base_config = base_config
        self.symbol_info = symbol_info
        self.candles = candles
        self.param_grid = param_grid
        self.train_bars = train_bars
        self.validation_bars = validation_bars
        self.oos_bars = oos_bars
        self.step_bars = step_bars or (validation_bars + oos_bars)
        self.objective = objective
        self.min_trades = min_trades
        self.starting_balance = starting_balance
        self.entry_tf = Timeframe(base_config.timeframes.entry)

    def run(self, method: str = "grid", *, n_iter: int = 20) -> List[Fold]:
        entry = self.candles[self.entry_tf]
        times = [c.time for c in entry]
        window = self.train_bars + self.validation_bars + self.oos_bars
        folds: List[Fold] = []
        fold_index = 0
        start = 0
        while start + window <= len(entry):
            t0 = times[start]
            t1 = times[start + self.train_bars]
            t2 = times[start + self.train_bars + self.validation_bars]
            t3 = times[start + window - 1]

            # Optimize on TRAIN only.
            optimizer = Optimizer(
                self.base_config, self.symbol_info, self.candles, self.param_grid,
                objective=self.objective, min_trades=self.min_trades,
                starting_balance=self.starting_balance,
                trade_start=t0, trade_end=t1,
            )
            ranked = optimizer.run(method=method, n_iter=n_iter)
            best = ranked[0] if ranked else None
            best_params = best.params if best else {}

            train_m = self._metrics(best_params, t0, t1)
            val_m = self._metrics(best_params, t1, t2)
            oos_m = self._metrics(best_params, t2, t3)
            report = assess(
                train_m, self.starting_balance, validation=val_m, oos=oos_m
            )
            folds.append(Fold(fold_index, best_params, train_m, val_m, oos_m, report))

            fold_index += 1
            start += self.step_bars
        return folds

    def _metrics(self, params: Dict[str, Any], start, end) -> Metrics:
        config = apply_overrides(self.base_config, params)
        bt = Backtester(
            config, create_strategy(config), self.symbol_info, self.candles,
            starting_balance=self.starting_balance,
        )
        result = bt.run(trade_start=start, trade_end=end)
        return compute_metrics(result)


__all__ = ["WalkForward", "Fold"]
