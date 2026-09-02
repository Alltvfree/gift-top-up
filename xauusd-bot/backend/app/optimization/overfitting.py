"""Overfitting detection.

Flags suspicious optimization results and classifies robustness as
ROBUST / WARNING / HIGH OVERFITTING RISK (spec §24). It never auto-deploys a
strategy; it only warns. Checks:

* extremely high backtest return
* very low trade count
* large train->validation degradation
* large validation->out-of-sample degradation
* excessive drawdown
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

from app.backtesting.metrics import Metrics


class Robustness(str, Enum):
    ROBUST = "ROBUST"
    WARNING = "WARNING"
    HIGH_RISK = "HIGH OVERFITTING RISK"


@dataclass
class OverfittingThresholds:
    max_return_pct: float = 200.0       # >200% on the sample is suspicious
    min_trades: int = 20
    max_drawdown_pct: float = 40.0
    max_pf_degradation: float = 0.5     # val PF < 50% of train PF -> flag
    max_oos_degradation: float = 0.5    # oos PF < 50% of val PF -> flag


@dataclass
class OverfittingReport:
    rating: Robustness
    flags: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"rating": self.rating.value, "flags": self.flags}


def _pf(m: Metrics) -> float:
    # Treat infinite/zero-loss profit factor as a large finite number.
    return min(m.profit_factor, 1e6)


def assess(
    train: Metrics,
    starting_balance: float,
    *,
    validation: Optional[Metrics] = None,
    oos: Optional[Metrics] = None,
    thresholds: Optional[OverfittingThresholds] = None,
) -> OverfittingReport:
    t = thresholds or OverfittingThresholds()
    flags: List[str] = []

    if starting_balance > 0:
        return_pct = train.net_profit / starting_balance * 100
        if return_pct > t.max_return_pct:
            flags.append(
                f"extremely high training return ({return_pct:.0f}% > "
                f"{t.max_return_pct:.0f}%)"
            )

    if train.total_trades < t.min_trades:
        flags.append(
            f"very low trade count ({train.total_trades} < {t.min_trades})"
        )

    if train.max_drawdown_pct > t.max_drawdown_pct:
        flags.append(
            f"excessive drawdown ({train.max_drawdown_pct:.1f}% > "
            f"{t.max_drawdown_pct:.0f}%)"
        )

    severe = False
    if validation is not None:
        train_pf, val_pf = _pf(train), _pf(validation)
        if train_pf > 0 and val_pf < train_pf * t.max_pf_degradation:
            flags.append(
                f"large train->validation degradation "
                f"(PF {train_pf:.2f} -> {val_pf:.2f})"
            )
            severe = True

    if validation is not None and oos is not None:
        val_pf, oos_pf = _pf(validation), _pf(oos)
        if val_pf > 0 and oos_pf < val_pf * t.max_oos_degradation:
            flags.append(
                f"large validation->out-of-sample degradation "
                f"(PF {val_pf:.2f} -> {oos_pf:.2f})"
            )
            severe = True
        if oos.net_profit < 0 < train.net_profit:
            flags.append("profitable in training but losing out-of-sample")
            severe = True

    if not flags:
        rating = Robustness.ROBUST
    elif severe or len(flags) >= 3:
        rating = Robustness.HIGH_RISK
    else:
        rating = Robustness.WARNING
    return OverfittingReport(rating=rating, flags=flags)


__all__ = ["Robustness", "OverfittingThresholds", "OverfittingReport", "assess"]
