"""Market data endpoints.

Until the MetaAPI broker feed is connected (Task 3), these serve a small
simulated quote so the frontend can render live-looking data. Prices are
clearly flagged with `source: "simulated"`.
"""
from __future__ import annotations

import asyncio
import hashlib
import math
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


def _tf_seconds(timeframe: str) -> int:
    """Parse a chart timeframe string ('1m', '15m', '1h', '4h', '1d', or a bare
    number of minutes like Vela's '60') into a bar interval in seconds."""
    tf = (timeframe or "1m").strip().lower()
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    if tf and tf[-1] in units and tf[:-1].isdigit():
        return max(int(tf[:-1]) * units[tf[-1]], 1)
    if tf.isdigit():
        return max(int(tf) * 60, 1)
    return 60


def _bar_price(symbol: str, bar_index: int) -> float:
    """Deterministic O(1) synthetic mid-price for one bar.

    Same (symbol, bar_index) always returns the same value, so repeated/
    overlapping history requests (a charting library re-fetching just the
    newest tail) stay stable instead of jumping around on every poll. Built
    from two sine waves (a slow drift + a faster wiggle) plus a small
    hash-derived jitter — cheap per bar, no accumulated random-walk state to
    replay from the start of time.
    """
    base = SYMBOLS.get(symbol.upper(), 1.0)
    seed = int(hashlib.sha256(symbol.upper().encode()).hexdigest()[:8], 16)
    phase1 = (seed % 1000) / 1000 * math.tau
    phase2 = ((seed // 1000) % 1000) / 1000 * math.tau
    wave = (
        math.sin(bar_index * 0.015 + phase1) * 0.012
        + math.sin(bar_index * 0.004 + phase2) * 0.02
    )
    h = int(hashlib.sha256(f"{symbol}:{bar_index}".encode()).hexdigest()[:8], 16)
    noise = ((h % 2000) / 2000 - 0.5) * 0.004
    return base * (1 + wave + noise)


def _candles(symbol: str, timeframe: str, limit: int) -> list[dict]:
    interval_ms = _tf_seconds(timeframe) * 1000
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    last_index = now_ms // interval_ms

    bars: list[dict] = []
    for i in range(limit - 1, -1, -1):
        idx = last_index - i
        open_p = _bar_price(symbol, idx)
        close_p = _bar_price(symbol, idx + 1)
        if idx == last_index:
            # Forming candle: track the same live quote the rest of the app
            # shows, so the chart's edge matches the ticker.
            close_p = _simulated_quote(symbol)["mid"]
        span = abs(close_p - open_p) or open_p * 0.0005
        bars.append(
            {
                "time": idx * interval_ms,
                "open": round(open_p, 5),
                "high": round(max(open_p, close_p) + span * 0.35, 5),
                "low": round(min(open_p, close_p) - span * 0.35, 5),
                "close": round(close_p, 5),
            }
        )
    return bars


@router.get("/candles/{symbol}")
async def get_candles(symbol: str, timeframe: str = "1m", limit: int = 200) -> dict:
    """OHLC bars for the charting UI. Simulated — see module docstring — but
    deterministic per bar so a chart polling for the newest tail sees stable
    history instead of the whole series reshuffling on every request."""
    limit = max(1, min(limit, 1000))
    return {
        "symbol": symbol.upper(),
        "timeframe": timeframe,
        "source": "simulated",
        "bars": _candles(symbol, timeframe, limit),
    }


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
