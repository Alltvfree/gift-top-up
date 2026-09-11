"""GRID trading bot.

Parameters:
    - symbol: str
    - upper_price: float
    - lower_price: float
    - grid_levels: int      (e.g., 10)
    - lot_size: float       (e.g., 0.01)
    - take_profit_pips: float
"""
from __future__ import annotations

from app.bots.base import BaseBot


class GridBot(BaseBot):
    async def initialize(self) -> None:
        self.grid_spacing = (
            self.params["upper_price"] - self.params["lower_price"]
        ) / self.params["grid_levels"]
        self.pending_orders: dict[str, dict] = {}

        # Place initial grid of limit orders around the current price.
        current_price = await self.broker.get_price(self.params["symbol"])
        for i in range(self.params["grid_levels"]):
            buy_price = current_price - (i * self.grid_spacing)
            sell_price = current_price + (i * self.grid_spacing)

            buy_order = await self.broker.place_limit_order(
                symbol=self.params["symbol"],
                side="BUY",
                price=buy_price,
                volume=self.params["lot_size"],
            )
            sell_order = await self.broker.place_limit_order(
                symbol=self.params["symbol"],
                side="SELL",
                price=sell_price,
                volume=self.params["lot_size"],
            )
            self.pending_orders[buy_order.id] = {
                "type": "BUY",
                "opposite_price": buy_price + self.grid_spacing,
            }
            self.pending_orders[sell_order.id] = {
                "type": "SELL",
                "opposite_price": sell_price - self.grid_spacing,
            }

    async def on_tick(self, symbol: str, bid: float, ask: float) -> None:
        # GRID reacts to fills, not ticks; nothing to do per tick.
        return

    async def on_order_filled(self, order_id: str, fill_price: float, volume: float) -> None:
        if order_id not in self.pending_orders:
            return

        order_info = self.pending_orders.pop(order_id)

        # Place the opposite order one grid level away to bank the spread.
        if order_info["type"] == "BUY":
            opposite_price = fill_price + self.grid_spacing
            new_order = await self.broker.place_limit_order(
                symbol=self.params["symbol"],
                side="SELL",
                price=opposite_price,
                volume=volume,
            )
        else:
            opposite_price = fill_price - self.grid_spacing
            new_order = await self.broker.place_limit_order(
                symbol=self.params["symbol"],
                side="BUY",
                price=opposite_price,
                volume=volume,
            )

        self.pending_orders[new_order.id] = {
            "type": "SELL" if order_info["type"] == "BUY" else "BUY",
            "opposite_price": fill_price,
        }
