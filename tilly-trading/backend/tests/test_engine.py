"""Engine, registry, and paper-broker tests (no MetaAPI / no network)."""
from __future__ import annotations

import asyncio

import pytest

from app.services.bot_runner import build_bot
from app.bots.grid_bot import GridBot
from app.bots.dca_bot import DCABot
from app.broker.simulated import SimulatedBroker


def test_strategy_registry() -> None:
    assert isinstance(build_bot("GRID", "b1", None, {"symbol": "XAUUSD"}), GridBot)
    assert isinstance(build_bot("DCA", "b2", None, {"symbol": "EURUSD"}), DCABot)


def test_unknown_strategy_rejected() -> None:
    with pytest.raises(ValueError):
        build_bot("MARTINGALE", "b3", None, {})


def test_simulated_broker_market_order_and_close() -> None:
    async def run() -> None:
        b = SimulatedBroker(starting_balance=10000)
        order = await b.place_market_order("XAUUSD", "BUY", 0.5)
        assert order.status == "filled"
        positions = await b.get_positions()
        assert len(positions) == 1 and positions[0]["symbol"] == "XAUUSD"
        info = await b.get_account_information()
        assert info["balance"] == 10000
        await b.close_position(order.id)
        assert await b.get_positions() == []

    asyncio.run(run())


def test_simulated_grid_places_pending_orders() -> None:
    async def run() -> None:
        b = SimulatedBroker()
        grid = build_bot(
            "GRID",
            "g1",
            b,
            {"symbol": "XAUUSD", "upper_price": 2400, "lower_price": 2300,
             "grid_levels": 5, "lot_size": 0.1},
        )
        await grid.initialize()
        # Grid should have placed limit orders on the paper broker.
        orders = await b.get_orders()
        positions = await b.get_positions()
        assert len(orders) + len(positions) > 0

    asyncio.run(run())
