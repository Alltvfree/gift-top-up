"""Self-hosted MT5 bridge client.

MT5 has no official retail REST API (that's why MetaAPI exists and charges
for it). This adapter talks instead to a small HTTP service — see
tilly-trading/mt5-bridge/ — that the user runs themselves next to a real
MetaTrader 5 terminal, using the official `MetaTrader5` Python package
(Windows-only; it drives the terminal via local IPC). Our side of the
contract is deliberately thin: plain HTTP + a bearer API key, normalized
JSON shapes that already match what MetaAPIClient/SimulatedBroker return, so
nothing downstream (engine.py, the strategies) needs to know this provider
exists.

Bridge contract (see tilly-trading/mt5-bridge/bridge.py for the reference
implementation):
    GET  /health                                  -> {"ok": bool}
    GET  /account                                  -> {"balance", "equity", "currency"}
    GET  /price/{symbol}                           -> {"bid", "ask"}
    GET  /positions                                -> [{"id","symbol","type",
                                                          "volume","openPrice",
                                                          "currentPrice","unrealizedProfit"}]
    GET  /candles/{symbol}?timeframe=&limit=       -> {"bars": [{"time","open","high","low","close"}]}
    GET  /symbols                                  -> ["EURUSD", "XAUUSDm", ...]
    POST /orders/market   {"symbol","side","volume"}        -> {"id","filled_price","status"}
    POST /orders/limit    {"symbol","side","price","volume"} -> {"id","status"}
    POST /positions/{id}/close                     -> {"ok": bool}
    POST /orders/{id}/cancel                       -> {"ok": bool}
"""
from __future__ import annotations

from typing import Any

import httpx

from app.broker.base import BrokerClient, OrderResult, Quote


class MT5BridgeError(RuntimeError):
    """The bridge responded, but with an error — surfaced verbatim to the caller."""


class MT5BridgeClient(BrokerClient):
    def __init__(self, base_url: str, api_key: str, timeout: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=self.timeout,
            )
        return self._client

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict:
        resp = await self._http().request(method, path, **kwargs)
        if resp.status_code >= 400:
            detail = resp.text[:300]
            try:
                detail = resp.json().get("detail", detail)
            except Exception:  # noqa: BLE001
                pass
            raise MT5BridgeError(f"MT5 bridge {method} {path} -> {resp.status_code}: {detail}")
        return resp.json()

    # ---- lifecycle ----
    async def connect(self) -> None:
        # No persistent connection to open — verify the bridge is actually
        # reachable and the terminal is logged in, so failures surface here
        # (at bot start) instead of on the first tick.
        health = await self._request("GET", "/health")
        if not health.get("ok"):
            raise MT5BridgeError(health.get("detail", "MT5 bridge reports not ready."))

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ---- account / pricing ----
    async def get_account_information(self) -> dict[str, Any]:
        return await self._request("GET", "/account")

    async def get_balance(self) -> float:
        info = await self.get_account_information()
        return float(info.get("balance", 0.0))

    async def get_quote(self, symbol: str) -> Quote:
        data = await self._request("GET", f"/price/{symbol}")
        return Quote(symbol=symbol, bid=float(data["bid"]), ask=float(data["ask"]))

    async def get_price(self, symbol: str) -> float:
        return (await self.get_quote(symbol)).mid

    # ---- orders ----
    async def place_market_order(self, symbol: str, side: str, volume: float) -> OrderResult:
        result = await self._request(
            "POST", "/orders/market", json={"symbol": symbol, "side": side.upper(), "volume": volume}
        )
        return OrderResult(
            id=str(result.get("id", "")),
            symbol=symbol,
            side=side.upper(),
            volume=volume,
            filled_price=result.get("filled_price"),
            status=result.get("status", "filled"),
        )

    async def place_limit_order(
        self, symbol: str, side: str, price: float, volume: float
    ) -> OrderResult:
        result = await self._request(
            "POST",
            "/orders/limit",
            json={"symbol": symbol, "side": side.upper(), "price": price, "volume": volume},
        )
        return OrderResult(
            id=str(result.get("id", "")),
            symbol=symbol,
            side=side.upper(),
            volume=volume,
            filled_price=price,
            status=result.get("status", "pending"),
        )

    async def get_positions(self) -> list[dict[str, Any]]:
        result = await self._http().get("/positions")
        if result.status_code >= 400:
            raise MT5BridgeError(f"MT5 bridge GET /positions -> {result.status_code}: {result.text[:300]}")
        return result.json()

    async def get_candles(self, symbol: str, timeframe: str, limit: int) -> list[dict]:
        result = await self._request(
            "GET", f"/candles/{symbol}", params={"timeframe": timeframe, "limit": limit}
        )
        return result.get("bars", [])

    async def get_symbols(self) -> list[str]:
        result = await self._http().get("/symbols")
        if result.status_code >= 400:
            raise MT5BridgeError(f"MT5 bridge GET /symbols -> {result.status_code}: {result.text[:300]}")
        return result.json()

    async def get_orders(self) -> list[dict[str, Any]]:
        result = await self._http().get("/orders")
        if result.status_code >= 400:
            raise MT5BridgeError(f"MT5 bridge GET /orders -> {result.status_code}: {result.text[:300]}")
        return result.json()

    async def close_position(self, position_id: str) -> None:
        await self._request("POST", f"/positions/{position_id}/close")

    async def cancel_order(self, order_id: str) -> None:
        await self._request("POST", f"/orders/{order_id}/cancel")
