"""Risk-based position sizing (Phase 10).

Deliberately refuses to hand back an unrealistic fixed lot size when the
config asks for risk-based sizing — if the SL distance would need a lot
size below the symbol's minimum, the trade is skipped, not force-rounded up
into risking more than asked.
"""
from __future__ import annotations

from .config import RiskConfig
from .symbols import SymbolSpec


def calculate_position_size(
    cfg: RiskConfig, spec: SymbolSpec, equity: float, sl_distance_price: float
) -> float:
    """Returns lots, respecting volume_min/volume_max/volume_step. Returns
    0.0 if the requested risk can't be expressed at or above the symbol's
    minimum lot (the caller should skip the trade, not silently take on
    more risk than configured)."""
    if cfg.mode == "fixed_lot":
        return spec.round_volume(cfg.fixed_lot)

    if cfg.mode == "fixed_money":
        risk_money = cfg.fixed_money
    elif cfg.mode == "percent_equity":
        risk_money = equity * (cfg.risk_percent / 100.0)
    else:
        raise ValueError(f"Unknown risk.mode {cfg.mode!r}")

    if sl_distance_price <= 0:
        raise ValueError("sl_distance_price must be positive to size a risk-based position.")

    sl_points = sl_distance_price / spec.point
    value_per_point_per_lot = spec.tick_value / spec.tick_size * spec.point if spec.tick_size else 0.0
    if value_per_point_per_lot <= 0:
        raise ValueError(f"SymbolSpec for {spec.symbol} has no usable tick value/size.")

    raw_lots = min(risk_money / (sl_points * value_per_point_per_lot), cfg.max_lot)
    # Round to the nearest volume_step WITHOUT flooring up to volume_min —
    # unlike SymbolSpec.round_volume() (used for fixed_lot above, where a
    # human-chosen lot size should always be nudged up to something
    # tradeable), a risk-derived size that rounds below volume_min means
    # the requested risk genuinely can't be expressed at this SL distance,
    # and forcing it up to volume_min would silently risk more than asked.
    lots = round(raw_lots / spec.volume_step) * spec.volume_step
    lots = min(lots, spec.volume_max)
    if lots < spec.volume_min:
        return 0.0
    return lots
