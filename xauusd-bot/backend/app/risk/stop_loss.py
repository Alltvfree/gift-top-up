"""ATR-based stop-loss and risk/reward take-profit calculation.

Volatility-aware — SL distance scales with ATR, never a fixed dollar value
(spec §9). All prices are rounded to the symbol's digits so they are broker-valid.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.models import OrderSide, SymbolInfo


@dataclass(frozen=True)
class StopTarget:
    """Computed SL/TP for a prospective trade."""

    entry: float
    stop_loss: float
    take_profit: float
    sl_distance: float          # price distance entry -> SL (always > 0)
    risk_reward: float

    @property
    def tp_distance(self) -> float:
        return self.sl_distance * self.risk_reward


def compute_stop_target(
    side: OrderSide,
    entry: float,
    atr_value: float,
    symbol_info: SymbolInfo,
    *,
    atr_multiplier: float,
    risk_reward: float,
) -> StopTarget:
    """Return SL/TP from an ATR-scaled stop and a fixed risk/reward ratio.

    * BUY  : SL below entry, TP above.
    * SELL : SL above entry, TP below.
    """
    if atr_value <= 0:
        raise ValueError("atr_value must be positive")
    if atr_multiplier <= 0 or risk_reward <= 0:
        raise ValueError("atr_multiplier and risk_reward must be positive")

    sl_distance = atr_value * atr_multiplier
    tp_distance = sl_distance * risk_reward
    digits = symbol_info.digits

    if side is OrderSide.BUY:
        stop_loss = entry - sl_distance
        take_profit = entry + tp_distance
    else:
        stop_loss = entry + sl_distance
        take_profit = entry - tp_distance

    return StopTarget(
        entry=round(entry, digits),
        stop_loss=round(stop_loss, digits),
        take_profit=round(take_profit, digits),
        sl_distance=round(sl_distance, digits),
        risk_reward=risk_reward,
    )


__all__ = ["StopTarget", "compute_stop_target"]
