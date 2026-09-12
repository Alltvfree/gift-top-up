"""Simulated (paper-trading) broker — no external service, no cost.

Implements the same BrokerClient contract as MetaAPIClient, but fills orders
against an in-process random-walk price. Lets the full engine + strategies +
dashboard run end-to-end without MetaAPI or a real MT5 account.

State lives on the instance, which the engine keeps alive for the life of a
running bot (same background loop), so positions/PnL evolve tick to tick.
"""
from __future__ import annotations

import random
import uuid
from dataclasses import dataclass, field

from app.broker.base import BrokerClient, OrderResult, Quote

# Plausible starting prices for the simulator.
BASE_PRICES: dict[str, float] = {
    "XAUUSD": 2347.5,
    "EURUSD": 1.0850,
    "GBPUSD": 1.2720,
    "USDJPY": 157.30,
    "BTCUSD": 64200.0,
}


@dataclass
class _Position:
    id: str
    symbol: str
    side: str  # BUY / SELL
    volume: float
    open_price: float


@dataclass
class _PendingOrder:
    id: str
    symbol: str
    side: str
    price: float
    volume: float


@dataclass
class SimulatedBroker(BrokerClient):
    """Paper broker with a random-walk price feed."""

    starting_balance: float = 10000.0
    _prices: dict[str, float] = field(default_factory=dict)
    _positions: list[_Position] = field(default_factory=list)
    _pending: list[_PendingOrder] = field(default_factory=list)
    _realized: float = 0.0

    async def connect(self) -> None:  # nothing to connect
        return

    async def close(self) -> None:
        return

    # ---- pricing ----
    def _price(self, symbol: str) -> float:
        base = BASE_PRICES.get(symbol.upper(), 100.0)
        cur = self._prices.get(symbol)
        if cur is None:
            cur = base
        # Random walk ~0.05% per tick.
        cur = cur * (1 + random.uniform(-0.0005, 0.0005))
        self._prices[symbol] = cur
        self._fill_pending(symbol, cur)
        return cur

    def _fill_pending(self, symbol: str, price: float) -> None:
        still: list[_PendingOrder] = []
        for o in self._pending:
            if o.symbol != symbol:
                still.append(o)
                continue
            # BUY limit fills when price <= limit; SELL limit when price >= limit.
            hit = (o.side == "BUY" and price <= o.price) or (o.side == "SELL" and price >= o.price)
            if hit:
                self._positions.append(
                    _Position(id=o.id, symbol=o.symbol, side=o.side, volume=o.volume, open_price=o.price)
                )
            else:
                still.append(o)
        self._pending = still

    async def get_quote(self, symbol: str) -> Quote:
        mid = self._price(symbol)
        spread = mid * 0.0001
        return Quote(symbol=symbol, bid=mid - spread / 2, ask=mid + spread / 2)

    async def get_price(self, symbol: str) -> float:
        return (await self.get_quote(symbol)).mid

    async def get_balance(self) -> float:
        return self.starting_balance + self._realized

    async def get_account_information(self) -> dict:
        return {
            "balance": self.starting_balance + self._realized,
            "equity": self.starting_balance + self._realized + self._open_pnl(),
            "currency": "USD",
        }

    def _pos_pnl(self, p: _Position) -> float:
        price = self._prices.get(p.symbol, p.open_price)
        diff = (price - p.open_price) if p.side == "BUY" else (p.open_price - price)
        # Simple contract multiplier so numbers are visible.
        return round(diff * p.volume * 100, 2)

    def _open_pnl(self) -> float:
        return round(sum(self._pos_pnl(p) for p in self._positions), 2)

    # ---- orders ----
    async def place_market_order(self, symbol: str, side: str, volume: float) -> OrderResult:
        price = self._price(symbol)
        pid = str(uuid.uuid4())
        self._positions.append(
            _Position(id=pid, symbol=symbol, side=side.upper(), volume=volume, open_price=price)
        )
        return OrderResult(id=pid, symbol=symbol, side=side.upper(), volume=volume,
                           filled_price=price, status="filled")

    async def place_limit_order(self, symbol: str, side: str, price: float, volume: float) -> OrderResult:
        oid = str(uuid.uuid4())
        self._pending.append(_PendingOrder(id=oid, symbol=symbol, side=side.upper(),
                                           price=price, volume=volume))
        return OrderResult(id=oid, symbol=symbol, side=side.upper(), volume=volume,
                           filled_price=price, status="pending")

    async def get_positions(self) -> list[dict]:
        return [
            {
                "id": p.id,
                "symbol": p.symbol,
                "type": f"POSITION_TYPE_{p.side}",
                "volume": p.volume,
                "openPrice": p.open_price,
                "currentPrice": self._prices.get(p.symbol, p.open_price),
                "unrealizedProfit": self._pos_pnl(p),
            }
            for p in self._positions
        ]

    async def get_orders(self) -> list[dict]:
        return [
            {"id": o.id, "symbol": o.symbol, "type": o.side, "openPrice": o.price, "volume": o.volume}
            for o in self._pending
        ]

    async def close_position(self, position_id: str) -> None:
        for p in list(self._positions):
            if p.id == position_id:
                self._realized += self._pos_pnl(p)
                self._positions.remove(p)

    async def cancel_order(self, order_id: str) -> None:
        self._pending = [o for o in self._pending if o.id != order_id]
