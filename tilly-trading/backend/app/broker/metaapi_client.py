"""MetaAPI broker client (Exness / XM / Vantage via MetaTrader).

Wraps the `metaapi_cloud_sdk` RPC connection behind the BrokerClient
contract. The SDK import is deferred so the app can boot for schema/API
work (Task 1) without the broker package installed or credentials set;
full live testing against an Exness demo account happens in Task 3.
"""
from __future__ import annotations

from app.broker.base import BrokerClient, OrderResult, Quote


class MetaAPIClient(BrokerClient):
    def __init__(self, token: str, account_id: str) -> None:
        self.token = token
        self.account_id = account_id
        self.api = None
        self.connection = None

    async def connect(self) -> None:
        # Imported lazily so the package is only required when actually trading.
        from metaapi_cloud_sdk import MetaApi

        self.api = MetaApi(self.token)
        account = await self.api.metatrader_account_api.get_account(self.account_id)
        self.connection = account.get_rpc_connection()
        await self.connection.connect()
        await self.connection.wait_synchronized()

    def _require_connection(self):
        if self.connection is None:
            raise RuntimeError("MetaAPIClient.connect() must be awaited before use")
        return self.connection

    async def get_balance(self) -> float:
        conn = self._require_connection()
        info = await conn.get_account_information()
        return float(info["balance"])

    async def get_quote(self, symbol: str) -> Quote:
        conn = self._require_connection()
        data = await conn.get_symbol_price(symbol)
        return Quote(symbol=symbol, bid=float(data["bid"]), ask=float(data["ask"]))

    async def get_price(self, symbol: str) -> float:
        return (await self.get_quote(symbol)).mid

    async def place_market_order(self, symbol: str, side: str, volume: float) -> OrderResult:
        conn = self._require_connection()
        if side.upper() == "BUY":
            result = await conn.create_market_buy_order(symbol, volume)
        else:
            result = await conn.create_market_sell_order(symbol, volume)
        return OrderResult(
            id=str(result.get("orderId") or result.get("positionId") or ""),
            symbol=symbol,
            side=side.upper(),
            volume=volume,
            status="filled",
        )

    async def place_limit_order(
        self, symbol: str, side: str, price: float, volume: float
    ) -> OrderResult:
        conn = self._require_connection()
        if side.upper() == "BUY":
            result = await conn.create_limit_buy_order(symbol, volume, price)
        else:
            result = await conn.create_limit_sell_order(symbol, volume, price)
        return OrderResult(
            id=str(result.get("orderId") or ""),
            symbol=symbol,
            side=side.upper(),
            volume=volume,
            filled_price=price,
            status="pending",
        )

    async def close_position(self, position_id: str) -> None:
        conn = self._require_connection()
        await conn.close_position(position_id)
