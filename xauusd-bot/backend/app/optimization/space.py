"""Parameter space + candidate generation for optimization.

A parameter space maps a **dotted config path** (e.g. ``strategy.ema_fast``,
``take_profit.risk_reward``) to a list of candidate values. Overrides are applied
onto a base :class:`BotConfig` and re-validated, so every candidate is a valid,
fully-typed config.
"""

from __future__ import annotations

import itertools
import random
from typing import Any, Dict, Iterator, List

from app.core.config import BotConfig

# Parameters the spec allows optimizing (§23). Others may be added, but keep the
# active set small — optimizing dozens at once invites overfitting.
OPTIMIZABLE = {
    "strategy.ema_fast",
    "strategy.ema_slow",
    "strategy.ema_short",
    "strategy.rsi_period",
    "strategy.rsi_buy_threshold",
    "strategy.rsi_sell_threshold",
    "strategy.atr_period",
    "strategy.min_score",
    "strategy.pullback_atr_mult",
    "stop_loss.atr_multiplier",
    "take_profit.risk_reward",
    "risk.cooldown_minutes",
    "trading_sessions.preset",
}

# Above this many simultaneously-optimized parameters we warn (spec §23).
MAX_RECOMMENDED_PARAMS = 4


def apply_overrides(base: BotConfig, overrides: Dict[str, Any]) -> BotConfig:
    """Return a new BotConfig with dotted-path overrides applied + validated."""
    data = base.model_dump()
    for dotted, value in overrides.items():
        parts = dotted.split(".")
        node = data
        for part in parts[:-1]:
            node = node[part]
        node[parts[-1]] = value
    return BotConfig(**data)


def grid_candidates(param_grid: Dict[str, List[Any]]) -> Iterator[Dict[str, Any]]:
    """Full Cartesian product of the grid."""
    keys = list(param_grid)
    for combo in itertools.product(*(param_grid[k] for k in keys)):
        yield dict(zip(keys, combo))


def random_candidates(
    param_grid: Dict[str, List[Any]], n: int, *, seed: int = 0
) -> Iterator[Dict[str, Any]]:
    """`n` random (deduplicated) samples from the grid."""
    rng = random.Random(seed)
    keys = list(param_grid)
    seen = set()
    total = 1
    for k in keys:
        total *= len(param_grid[k])
    n = min(n, total)
    while len(seen) < n:
        combo = tuple(rng.choice(param_grid[k]) for k in keys)
        if combo in seen:
            continue
        seen.add(combo)
        yield dict(zip(keys, combo))


def validate_grid(param_grid: Dict[str, List[Any]]) -> List[str]:
    """Return warnings about the grid (unknown params, too many dimensions)."""
    warnings: List[str] = []
    for key in param_grid:
        if key not in OPTIMIZABLE:
            warnings.append(f"'{key}' is not in the recommended optimizable set")
    if len(param_grid) > MAX_RECOMMENDED_PARAMS:
        warnings.append(
            f"optimizing {len(param_grid)} parameters at once (> "
            f"{MAX_RECOMMENDED_PARAMS}) increases overfitting risk"
        )
    return warnings


__all__ = [
    "apply_overrides", "grid_candidates", "random_candidates", "validate_grid",
    "OPTIMIZABLE", "MAX_RECOMMENDED_PARAMS",
]
