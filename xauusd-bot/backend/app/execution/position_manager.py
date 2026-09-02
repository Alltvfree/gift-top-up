"""Break-even and ATR trailing-stop management.

Pure functions that compute a proposed new stop-loss for an open position. The
cardinal rule (spec §13): a stop **never moves backward** — for a BUY the SL can
only rise, for a SELL it can only fall. The engine applies the result via
``broker.modify_position``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.core.config import BreakEvenConfig, TrailingStopConfig
from app.core.models import OrderSide, SymbolInfo


@dataclass(frozen=True)
class StopUpdate:
    new_sl: float
    reason: str


def _forward_only(side: OrderSide, current_sl: float, candidate: float) -> bool:
    """True if `candidate` is a strictly tighter (protective) stop."""
    if side is OrderSide.BUY:
        return candidate > current_sl
    return candidate < current_sl


def break_even_stop(
    side: OrderSide,
    entry: float,
    initial_sl: float,
    current_price: float,
    current_sl: float,
    symbol_info: SymbolInfo,
    config: BreakEvenConfig,
) -> Optional[float]:
    """Move SL to entry (+/- buffer) once price reaches +trigger_r.

    R is the initial stop distance ``|entry - initial_sl|``.
    """
    if not config.enabled:
        return None
    r = abs(entry - initial_sl)
    if r <= 0:
        return None
    profit = (current_price - entry) if side is OrderSide.BUY else (entry - current_price)
    if profit < config.trigger_r * r:
        return None
    buffer = config.buffer_points * symbol_info.point
    candidate = entry + buffer if side is OrderSide.BUY else entry - buffer
    candidate = round(candidate, symbol_info.digits)
    if not _forward_only(side, current_sl, candidate):
        return None
    return candidate


def trailing_stop(
    side: OrderSide,
    current_price: float,
    current_sl: float,
    atr_value: float,
    symbol_info: SymbolInfo,
    config: TrailingStopConfig,
) -> Optional[float]:
    """ATR trailing stop: price -/+ ATR*multiplier, forward-only."""
    if not config.enabled or atr_value <= 0:
        return None
    distance = atr_value * config.atr_multiplier
    candidate = (
        current_price - distance if side is OrderSide.BUY
        else current_price + distance
    )
    candidate = round(candidate, symbol_info.digits)
    if not _forward_only(side, current_sl, candidate):
        return None
    return candidate


def manage_stop(
    side: OrderSide,
    entry: float,
    initial_sl: float,
    current_price: float,
    current_sl: float,
    atr_value: float,
    symbol_info: SymbolInfo,
    break_even_cfg: BreakEvenConfig,
    trailing_cfg: TrailingStopConfig,
) -> Optional[StopUpdate]:
    """Combine break-even and trailing; return the tightest protective update."""
    be = break_even_stop(
        side, entry, initial_sl, current_price, current_sl, symbol_info,
        break_even_cfg,
    )
    tr = trailing_stop(
        side, current_price, current_sl, atr_value, symbol_info, trailing_cfg
    )
    candidates = []
    if be is not None:
        candidates.append((be, "break_even"))
    if tr is not None:
        candidates.append((tr, "trailing"))
    if not candidates:
        return None
    # Pick the tightest (highest for BUY, lowest for SELL).
    if side is OrderSide.BUY:
        new_sl, reason = max(candidates, key=lambda c: c[0])
    else:
        new_sl, reason = min(candidates, key=lambda c: c[0])
    return StopUpdate(new_sl=new_sl, reason=reason)


__all__ = ["StopUpdate", "break_even_stop", "trailing_stop", "manage_stop"]
