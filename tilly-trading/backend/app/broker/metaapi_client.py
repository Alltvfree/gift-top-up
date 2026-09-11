"""MetaAPI broker client (Exness / XM / Vantage via MetaTrader).

Wraps the `metaapi_cloud_sdk` RPC connection behind the BrokerClient
contract. The SDK is imported lazily so the app boots for schema/API work
without the broker package installed or credentials set.

Method names follow the metaapi-cloud-sdk RPC connection API. Broker responses
are dicts, so every access is defensive.
"""
from __future__ import annotations

from typing import Any

from app.broker.base import BrokerClient, OrderResult, Quote
from app.core.config import settings


class MetaAPIClient(BrokerClient):
    def __init__(
        self,
        account_id: str,
        token: str | None = None,
        region: str | None = None,
    ) -> None:
        self.token = token or settings.metaapi_token
        self.region = region or settings.metaapi_region
        self.account_id = account_id
        self.api = None
        self.account = None
        self.connection = None

    async def connect(self) -> None:
        from metaapi_cloud_sdk import MetaApi

        self.api = MetaApi(self.token, {"region": self.region})
        self.account = await self.api.metatrader_account_api.get_account(self.account_id)
        # Ensure it is deployed and connected to the broker.
        if getattr(self.account, "state", None) not in ("DEPLOYED",):
            try:
                await self.account.deploy()
            except Exception:  # noqa: BLE001 - already deployed is fine
                pass
        await self.account.wait_connected()
        self.connection = self.account.get_rpc_connection()
        await self.connection.connect()
        await self.connection.wait_synchronized()

    def _conn(self):
        if self.connection is None:
            raise RuntimeError("MetaAPIClient.connect() must be awaited before use")
        return self.connection

    async def get_account_information(self) -> dict[str, Any]:
        return await self._conn().get_account_information()

    async def get_balance(self) -> float:
        info = await self.get_account_information()
        return float(info.get("balance", 0.0))

    async def get_quote(self, symbol: str) -> Quote:
        data = await self._conn().get_symbol_price(symbol)
        return Quote(symbol=symbol, bid=float(data["bid"]), ask=float(data["ask"]))

    async def get_price(self, symbol: str) -> float:
        return (await self.get_quote(symbol)).mid

    async def place_market_order(self, symbol: str, side: str, volume: float) -> OrderResult:
        conn = self._conn()
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
        conn = self._conn()
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

    async def get_positions(self) -> list[dict[str, Any]]:
        return await self._conn().get_positions()

    async def get_orders(self) -> list[dict[str, Any]]:
        return await self._conn().get_orders()

    async def close_position(self, position_id: str) -> None:
        await self._conn().close_position(position_id)

    async def cancel_order(self, order_id: str) -> None:
        await self._conn().cancel_order(order_id)

    async def close(self) -> None:
        if self.connection is not None:
            try:
                await self.connection.close()
            except Exception:  # noqa: BLE001
                pass
            self.connection = None
