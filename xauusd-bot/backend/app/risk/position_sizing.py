"""Percentage-of-equity position sizing.

Lot size is derived from the money at risk and the stop distance, then clamped
to the broker's volume rules. The cardinal rule (spec §10): **never risk more
than the configured percentage** because of rounding — so we always round the
lot size DOWN to the broker's volume step, and reject the trade when even the
minimum lot would exceed the risk budget.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.core.models import SymbolInfo


@dataclass(frozen=True)
class PositionSize:
    """Result of a lot-size calculation."""

    lots: float                 # 0.0 means "cannot size within risk budget"
    risk_amount: float          # account-currency amount actually risked
    risk_percent_effective: float
    rejected_reason: str = ""

    @property
    def ok(self) -> bool:
        return self.lots > 0.0


def _round_down_to_step(value: float, step: float) -> float:
    if step <= 0:
        return value
    # Guard against floating-point overshoot (e.g. 0.29999999).
    steps = math.floor(round(value / step, 8))
    return round(steps * step, 8)


def calculate_position_size(
    equity: float,
    risk_percent: float,
    entry: float,
    stop_loss: float,
    symbol_info: SymbolInfo,
    *,
    max_lots: float | None = None,
) -> PositionSize:
    """Compute a broker-valid lot size for a given risk budget.

    Parameters
    ----------
    equity : account equity (account currency).
    risk_percent : percent of equity to risk on this trade (e.g. 1.0).
    entry, stop_loss : trade prices; the distance between them sets the risk.
    symbol_info : provides tick size/value and volume min/max/step.
    max_lots : optional hard cap layered on top of the broker maximum.
    """
    if equity <= 0:
        return PositionSize(0.0, 0.0, 0.0, "equity is non-positive")
    if risk_percent <= 0:
        return PositionSize(0.0, 0.0, 0.0, "risk_percent is non-positive")

    sl_distance = abs(entry - stop_loss)
    if sl_distance <= 0:
        return PositionSize(0.0, 0.0, 0.0, "stop distance is zero")
    if symbol_info.tick_size <= 0 or symbol_info.tick_value <= 0:
        return PositionSize(0.0, 0.0, 0.0, "invalid tick size/value")

    risk_amount = equity * (risk_percent / 100.0)

    # Loss (account currency) if a 1.0-lot position hits its stop.
    ticks_to_stop = sl_distance / symbol_info.tick_size
    loss_per_lot = ticks_to_stop * symbol_info.tick_value
    if loss_per_lot <= 0:
        return PositionSize(0.0, 0.0, 0.0, "computed zero loss-per-lot")

    raw_lots = risk_amount / loss_per_lot

    # Apply caps: broker max and optional configured max.
    upper = symbol_info.volume_max
    if max_lots is not None:
        upper = min(upper, max_lots)
    capped = min(raw_lots, upper)

    lots = _round_down_to_step(capped, symbol_info.volume_step)

    # Rounding down must never drop below the broker minimum; if it does, the
    # trade cannot be taken without breaching the risk budget.
    if lots < symbol_info.volume_min:
        return PositionSize(
            0.0,
            0.0,
            0.0,
            (
                f"required lot {raw_lots:.4f} rounds below broker minimum "
                f"{symbol_info.volume_min} within the {risk_percent}% risk budget"
            ),
        )

    effective_risk_amount = lots * loss_per_lot
    effective_pct = (effective_risk_amount / equity) * 100.0
    return PositionSize(
        lots=lots,
        risk_amount=round(effective_risk_amount, 2),
        risk_percent_effective=round(effective_pct, 4),
    )


__all__ = ["PositionSize", "calculate_position_size"]
