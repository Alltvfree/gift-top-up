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
        p = self.params
        symbol = p["symbol"]
        levels = int(p.get("grid_levels", 10) or 10)
        lot = float(p.get("lot_size", p.get("base_lot", 0.01)) or 0.01)

        current_price = await self.broker.get_price(symbol)

        # Derive grid spacing from whatever the params provide:
        # explicit spacing, an upper/lower band, an ATR-based range, or a
        # sensible 0.1%-of-price fallback. Keeps GRID working with both manual
        # params and AI-generated presets.
        if p.get("grid_spacing"):
            self.grid_spacing = float(p["grid_spacing"])
        elif p.get("upper_price") and p.get("lower_price"):
            self.grid_spacing = (float(p["upper_price"]) - float(p["lower_price"])) / max(levels, 1)
        elif p.get("grid_range"):
            self.grid_spacing = float(p["grid_range"]) / max(levels, 1)
        else:
            self.grid_spacing = current_price * 0.001

        self.pending_orders: dict[str, dict] = {}

        # Place a symmetric ladder: buys below, sells above the current price.
        half = max(levels // 2, 1)
        for i in range(1, half + 1):
            buy_price = current_price - (i * self.grid_spacing)
            sell_price = current_price + (i * self.grid_spacing)

            buy_order = await self.broker.place_limit_order(
                symbol=symbol, side="BUY", price=buy_price, volume=lot
            )
            sell_order = await self.broker.place_limit_order(
                symbol=symbol, side="SELL", price=sell_price, volume=lot
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
