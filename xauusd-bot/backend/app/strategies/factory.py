"""Strategy factory — builds a strategy instance from config.

Keeps strategy selection in one place so new strategies can be registered
without touching the engine.
"""

from __future__ import annotations

from app.core.config import BotConfig
from app.strategies.base import Strategy
from app.strategies.trend_pullback import TrendPullbackStrategy

_REGISTRY = {
    "XAUUSD_TrendPullback_v1": TrendPullbackStrategy,
}


def create_strategy(config: BotConfig) -> Strategy:
    name = config.strategy.name
    if name not in _REGISTRY:
        raise ValueError(
            f"unknown strategy '{name}'. Known: {sorted(_REGISTRY)}"
        )
    cls = _REGISTRY[name]
    return cls(
        config.strategy,
        atr_multiplier=config.stop_loss.atr_multiplier,
        risk_reward=config.take_profit.risk_reward,
        max_spread_points=config.risk.max_spread_points,
    )


__all__ = ["create_strategy"]
