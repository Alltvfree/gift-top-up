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
        # Take profit each filled leg once price has moved one grid_spacing in
        # its favor. This is the code that actually closes GRID positions —
        # on_order_filled() below never runs (the engine has no reliable way
        # to match a broker's post-fill position id back to the order id
        # that opened it: MT5 and most real brokers mint a new ticket for the
        # resulting position, not the pending order's id), so every filled
        # leg sat open forever until this existed. Deliberately doesn't
        # re-arm a replacement order on close — the ladder shrinks instead of
        # growing without bound, which is the safe direction to be wrong in.
        try:
            positions = await self.broker.get_positions()
        except Exception:  # noqa: BLE001 - a broker hiccup shouldn't crash the tick
            return

        for p in positions:
            if p.get("symbol") != symbol:
                continue
            side = str(p.get("type", "")).replace("POSITION_TYPE_", "")
            open_price = float(p.get("openPrice", 0) or 0)
            if side == "BUY":
                target = open_price + self.grid_spacing
                hit = bid >= target
            else:
                target = open_price - self.grid_spacing
                hit = ask <= target
            if hit:
                position_id = str(p.get("id", ""))
                if position_id:
                    await self.broker.close_position(position_id)

    async def on_order_filled(self, order_id: str, fill_price: float, volume: float) -> None:
        # Never called — see on_tick(), which does the real closing work.
        # Kept only because BaseBot declares it abstract.
        return
