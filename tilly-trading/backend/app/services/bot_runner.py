"""Bot runner service — maps a stored bot to a live strategy instance.

This is the seam between persisted `Bot` rows and the running strategy
engines. The lifecycle (start/stop/pause) and the Celery-backed event loop
are completed in Task 4; this scaffolding wires strategy selection so the
API layer can already reference it.
"""
from __future__ import annotations

from typing import Any

from app.bots.base import BaseBot
from app.bots.dca_bot import DCABot
from app.bots.grid_bot import GridBot
from app.broker.base import BrokerClient

STRATEGY_REGISTRY: dict[str, type[BaseBot]] = {
    "GRID": GridBot,
    "DCA": DCABot,
}


def build_bot(strategy: str, bot_id: str, broker: BrokerClient, params: dict[str, Any]) -> BaseBot:
    """Instantiate the correct strategy for a bot."""
    try:
        bot_cls = STRATEGY_REGISTRY[strategy.upper()]
    except KeyError as exc:
        raise ValueError(f"Unknown strategy: {strategy!r}") from exc
    return bot_cls(bot_id=bot_id, broker=broker, params=params)
