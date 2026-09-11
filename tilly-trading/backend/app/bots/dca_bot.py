"""DCA (dollar-cost-averaging / martingale) trading bot.

Parameters:
    - symbol: str
    - base_lot: float           (e.g., 0.01)
    - multiplier: float         (e.g., 1.5)
    - max_orders: int           (e.g., 6)
    - deviation_pips: float     (e.g., 20)
    - take_profit_pips: float
"""
from __future__ import annotations

from app.bots.base import BaseBot


class DCABot(BaseBot):
    async def initialize(self) -> None:
        self.open_positions: list = []
        self.average_price = 0.0
        self.total_volume = 0.0
        self.order_count = 0

        # Open the first market position.
        await self._enter_position()

    async def on_tick(self, symbol: str, bid: float, ask: float) -> None:
        # Add to the position if price has moved against us far enough.
        if self.average_price > 0 and self.order_count < self.params["max_orders"]:
            deviation_pips = (self.average_price - bid) * 10000  # adjust for JPY pairs
            if deviation_pips >= self.params["deviation_pips"]:
                await self._enter_position()

        # Take profit when price recovers past the average by TP distance.
        if self.total_volume > 0:
            tp_distance = self.params["take_profit_pips"] / 10000
            if bid >= self.average_price + tp_distance:
                await self._close_all()

    async def on_order_filled(self, order_id: str, fill_price: float, volume: float) -> None:
        # DCA drives itself from ticks; order fills are recorded on entry.
        return

    async def _enter_position(self) -> None:
        lot_size = self.params["base_lot"] * (self.params["multiplier"] ** self.order_count)
        order = await self.broker.place_market_order(
            symbol=self.params["symbol"],
            side="BUY",
            volume=lot_size,
        )
        self.open_positions.append(order)
        self.order_count += 1

        fill_price = order.filled_price or await self.broker.get_price(self.params["symbol"])
        prev_volume = self.total_volume
        self.total_volume += lot_size
        # Weighted-average entry price.
        self.average_price = (
            (self.average_price * prev_volume) + (fill_price * lot_size)
        ) / self.total_volume

    async def _close_all(self) -> None:
        for pos in self.open_positions:
            await self.broker.close_position(pos.id)
        self.open_positions = []
        self.order_count = 0
        self.total_volume = 0.0
        self.average_price = 0.0
