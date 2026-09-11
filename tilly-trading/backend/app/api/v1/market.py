"""Market data endpoints.

Until the MetaAPI broker feed is connected (Task 3), these serve a small
simulated quote so the frontend can render live-looking data. Prices are
clearly flagged with `source: "simulated"`.
"""
from __future__ import annotations

import asyncio
import random
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()

# Symbol -> a plausible base price for the simulator.
SYMBOLS: dict[str, float] = {
    "XAUUSD": 2347.5,
    "EURUSD": 1.0850,
    "GBPUSD": 1.2720,
    "USDJPY": 157.30,
    "BTCUSD": 64200.0,
}


def _simulated_quote(symbol: str) -> dict:
    base = SYMBOLS.get(symbol.upper(), 1.0)
    jitter = base * random.uniform(-0.0008, 0.0008)
    mid = base + jitter
    spread = base * 0.0001
    return {
        "symbol": symbol.upper(),
        "bid": round(mid - spread / 2, 5),
        "ask": round(mid + spread / 2, 5),
        "mid": round(mid, 5),
        "source": "simulated",
        "ts": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/symbols")
async def list_symbols() -> dict:
    return {"symbols": sorted(SYMBOLS.keys())}


@router.get("/price/{symbol}")
async def get_price(symbol: str) -> dict:
    return _simulated_quote(symbol)


@router.websocket("/ws/{symbol}")
async def price_stream(websocket: WebSocket, symbol: str) -> None:
    """Push a simulated quote roughly once per second."""
    await websocket.accept()
    try:
        while True:
            await websocket.send_json(_simulated_quote(symbol))
            await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        return
