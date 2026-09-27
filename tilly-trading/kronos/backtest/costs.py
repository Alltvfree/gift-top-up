"""Realistic execution costs: spread, slippage, commission (Phases 6-8).

Nothing here assumes zero cost anywhere. If historical spread data isn't
available the caller must pick a fixed/percentage mode explicitly — there
is no silent zero-spread fallback.
"""
from __future__ import annotations

import numpy as np

from .config import CommissionConfig, SlippageConfig, SpreadConfig
from .symbols import SymbolSpec


def spread_points(cfg: SpreadConfig, spec: SymbolSpec, bar_spread_points: float | None, price: float) -> float:
    """Spread in points for one bar. `bar_spread_points` is MT5's own
    historical `spread` column for that bar (real recorded data), used only
    when cfg.mode == "historical" and it's actually present."""
    if cfg.mode == "historical":
        if bar_spread_points is None or not np.isfinite(bar_spread_points) or bar_spread_points <= 0:
            raise ValueError(
                "spread.mode is 'historical' but this bar has no usable recorded spread — "
                "switch to mode 'fixed' or 'percentage', or fix the data (see data_quality.py)."
            )
        return float(bar_spread_points)
    if cfg.mode == "fixed":
        return cfg.points
    if cfg.mode == "percentage":
        return (cfg.percent / 100.0) * price / spec.point
    raise ValueError(f"Unknown spread.mode {cfg.mode!r}")


def slippage_points(cfg: SlippageConfig, rng: np.random.Generator) -> float:
    if cfg.mode == "fixed_points":
        return cfg.points
    if cfg.mode == "random":
        return max(0.0, float(rng.normal(cfg.points, cfg.random_std_points)))
    raise ValueError(f"Unknown slippage.mode {cfg.mode!r}")


def entry_price(side: str, bar_price: float, spec: SymbolSpec, half_spread: float, slip: float) -> float:
    """bar_price is the raw mid/close/open price the decision is anchored
    to. BUY fills at ASK (mid + half spread) plus adverse slippage; SELL
    fills at BID (mid - half spread) minus adverse slippage — slippage is
    always against the trader, never in their favor, by construction."""
    slip_price = slip * spec.point
    if side == "BUY":
        return bar_price + half_spread + slip_price
    if side == "SELL":
        return bar_price - half_spread - slip_price
    raise ValueError(f"side must be BUY or SELL, got {side!r}")


def exit_price(side: str, bar_price: float, spec: SymbolSpec, half_spread: float, slip: float) -> float:
    """Closing a BUY sells at BID; closing a SELL buys at ASK — the mirror
    image of entry_price, again always against the trader."""
    slip_price = slip * spec.point
    if side == "BUY":
        return bar_price - half_spread - slip_price
    if side == "SELL":
        return bar_price + half_spread + slip_price
    raise ValueError(f"side must be BUY or SELL, got {side!r}")


def commission_cost(cfg: CommissionConfig, lots: float, notional: float) -> float:
    if cfg.type == "per_lot":
        return cfg.value * lots
    if cfg.type == "percentage":
        return (cfg.value / 100.0) * notional
    if cfg.type == "fixed_per_trade":
        return cfg.value
    raise ValueError(f"Unknown commission.type {cfg.type!r}")
