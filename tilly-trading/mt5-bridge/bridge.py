"""Tilly Trading — self-hosted MT5 bridge (reference implementation).

Runs on YOUR machine, next to a real MetaTrader 5 terminal, using the
official `MetaTrader5` Python package. That package only works on Windows —
it drives the terminal via local IPC, not a network protocol — so this file
must run on a Windows PC or Windows VPS with MT5 installed and logged in to
your broker. It CANNOT run in a Linux container, and it was written and
syntax-checked but NOT executed by Claude: there is no real MT5 terminal
available in that environment to test it against. Test it yourself against
your own demo account before pointing a live bot at it.

The Tilly backend (wherever it runs — Render or anywhere else) calls this
service over plain HTTPS instead of talking to MT5 directly. That's the
whole point: MT5 has no official retail REST API, and this is the one
piece of the stack that has to run somewhere MT5 itself runs.

Quick start
-----------
1. Install MetaTrader 5 and log in to your broker account (demo or live) —
   leave the terminal open and logged in.
2. pip install -r requirements.txt
3. Set MT5_BRIDGE_API_KEY (pick any long random string — this is the secret
   the backend authenticates with) and run:
       uvicorn bridge:app --host 0.0.0.0 --port 8787
4. Expose it over HTTPS so Render can reach it — a Cloudflare Tunnel is the
   easiest free option and matches the rest of this project's stack:
       cloudflared tunnel --url http://localhost:8787
   That prints a https://*.trycloudflare.com URL — use it (plus your API
   key) as the "MT5 bridge" account on the Tilly Account page.

See README.md in this folder for the full walkthrough and a systemd/Windows
service example so it survives reboots.
"""
from __future__ import annotations

import os
from typing import Any, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel

try:
    import MetaTrader5 as mt5
except ImportError as exc:  # pragma: no cover - Windows-only dependency
    raise SystemExit(
        "The MetaTrader5 package is Windows-only and must be installed where "
        "a real MT5 terminal runs. `pip install MetaTrader5` on that machine."
    ) from exc

API_KEY = os.environ.get("MT5_BRIDGE_API_KEY")
if not API_KEY:
    raise SystemExit("Set MT5_BRIDGE_API_KEY before starting the bridge.")

# Optional: auto-login on startup. Omit these and the bridge instead attaches
# to whatever account is already logged in to the running terminal.
MT5_LOGIN = os.environ.get("MT5_LOGIN")
MT5_PASSWORD = os.environ.get("MT5_PASSWORD")
MT5_SERVER = os.environ.get("MT5_SERVER")
MT5_PATH = os.environ.get("MT5_PATH")  # path to terminal64.exe, if not on PATH

DEVIATION_POINTS = 20  # max acceptable slippage for market orders
MAGIC = 20260101  # arbitrary order tag identifying Tilly-placed orders

app = FastAPI(title="Tilly MT5 Bridge")


def _init_mt5() -> None:
    kwargs: dict[str, Any] = {}
    if MT5_PATH:
        kwargs["path"] = MT5_PATH
    if MT5_LOGIN and MT5_PASSWORD and MT5_SERVER:
        kwargs.update(login=int(MT5_LOGIN), password=MT5_PASSWORD, server=MT5_SERVER)
    if not mt5.initialize(**kwargs):
        code, desc = mt5.last_error()
        raise RuntimeError(f"MetaTrader5.initialize() failed: [{code}] {desc}")


@app.on_event("startup")
def _startup() -> None:
    _init_mt5()


@app.on_event("shutdown")
def _shutdown() -> None:
    mt5.shutdown()


def require_api_key(authorization: str | None = Header(default=None)) -> None:
    expected = f"Bearer {API_KEY}"
    if authorization != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing API key.")


def _ensure_symbol(symbol: str) -> None:
    """MT5 only prices/trades symbols visible in Market Watch."""
    info = mt5.symbol_info(symbol)
    if info is None:
        raise HTTPException(status_code=404, detail=f"Unknown symbol: {symbol}")
    if not info.visible and not mt5.symbol_select(symbol, True):
        raise HTTPException(status_code=400, detail=f"Could not select symbol: {symbol}")


def _position_type(mt5_type: int) -> str:
    # mt5.POSITION_TYPE_BUY == 0, POSITION_TYPE_SELL == 1 — normalized to the
    # same "POSITION_TYPE_BUY"/"POSITION_TYPE_SELL" strings MetaAPI and the
    # paper broker already return, so the backend needs no per-provider code.
    return "POSITION_TYPE_BUY" if mt5_type == mt5.POSITION_TYPE_BUY else "POSITION_TYPE_SELL"


TIMEFRAME_MAP = {
    "1m": mt5.TIMEFRAME_M1,
    "5m": mt5.TIMEFRAME_M5,
    "15m": mt5.TIMEFRAME_M15,
    "1h": mt5.TIMEFRAME_H1,
}


# ---------------------------------------------------------------- schemas --
class MarketOrderIn(BaseModel):
    symbol: str
    side: Literal["BUY", "SELL"]
    volume: float


class LimitOrderIn(BaseModel):
    symbol: str
    side: Literal["BUY", "SELL"]
    price: float
    volume: float


# ---------------------------------------------------------------- routes ---
@app.get("/health", dependencies=[Depends(require_api_key)])
def health() -> dict:
    # Requires the API key too — this service is reachable from the open
    # internet (via whatever tunnel exposes it), and even "just health" would
    # otherwise leak the logged-in account number to anyone who finds the URL.
    info = mt5.account_info()
    return {"ok": info is not None, "logged_in": info is not None, "account": info.login if info else None}


@app.get("/account", dependencies=[Depends(require_api_key)])
def account() -> dict:
    info = mt5.account_info()
    if info is None:
        raise HTTPException(status_code=503, detail="MT5 terminal not connected.")
    return {"balance": info.balance, "equity": info.equity, "currency": info.currency}


@app.get("/price/{symbol}", dependencies=[Depends(require_api_key)])
def price(symbol: str) -> dict:
    _ensure_symbol(symbol)
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        raise HTTPException(status_code=502, detail=f"No tick data for {symbol}.")
    return {"bid": tick.bid, "ask": tick.ask}


@app.get("/positions", dependencies=[Depends(require_api_key)])
def positions() -> list[dict]:
    rows = mt5.positions_get() or ()
    return [
        {
            "id": str(p.ticket),
            "symbol": p.symbol,
            "type": _position_type(p.type),
            "volume": p.volume,
            "openPrice": p.price_open,
            "currentPrice": p.price_current,
            "unrealizedProfit": p.profit,
        }
        for p in rows
    ]


@app.get("/candles/{symbol}", dependencies=[Depends(require_api_key)])
def candles(symbol: str, timeframe: str = "1m", limit: int = 200) -> dict:
    """Real historical OHLC bars from the terminal — mt5.copy_rates_from_pos,
    the official history API. Returns oldest-first, matching the shape the
    Tilly backend/frontend already use for every other candle source."""
    _ensure_symbol(symbol)
    mt5_timeframe = TIMEFRAME_MAP.get(timeframe, mt5.TIMEFRAME_M1)
    limit = max(1, min(limit, 1000))
    rates = mt5.copy_rates_from_pos(symbol, mt5_timeframe, 0, limit)
    if rates is None or len(rates) == 0:
        code, desc = mt5.last_error()
        raise HTTPException(status_code=502, detail=f"No rate history for {symbol}: [{code}] {desc}")
    bars = [
        {
            "time": int(r["time"]) * 1000,  # MT5 gives unix seconds; we use ms everywhere else
            "open": float(r["open"]),
            "high": float(r["high"]),
            "low": float(r["low"]),
            "close": float(r["close"]),
        }
        for r in rates
    ]
    return {"symbol": symbol, "timeframe": timeframe, "bars": bars}


@app.get("/orders", dependencies=[Depends(require_api_key)])
def orders() -> list[dict]:
    rows = mt5.orders_get() or ()
    return [
        {
            "id": str(o.ticket),
            "symbol": o.symbol,
            "type": "BUY" if o.type % 2 == 0 else "SELL",
            "openPrice": o.price_open,
            "volume": o.volume_current,
        }
        for o in rows
    ]


@app.post("/orders/market", dependencies=[Depends(require_api_key)])
def place_market_order(body: MarketOrderIn) -> dict:
    _ensure_symbol(body.symbol)
    tick = mt5.symbol_info_tick(body.symbol)
    if tick is None:
        raise HTTPException(status_code=502, detail=f"No tick data for {body.symbol}.")
    order_type = mt5.ORDER_TYPE_BUY if body.side == "BUY" else mt5.ORDER_TYPE_SELL
    price_ = tick.ask if body.side == "BUY" else tick.bid
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": body.symbol,
        "volume": body.volume,
        "type": order_type,
        "price": price_,
        "deviation": DEVIATION_POINTS,
        "magic": MAGIC,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    result = mt5.order_send(request)
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        code = result.retcode if result else mt5.last_error()
        raise HTTPException(status_code=502, detail=f"order_send failed: {code}")
    return {"id": str(result.order or result.deal), "filled_price": result.price, "status": "filled"}


@app.post("/orders/limit", dependencies=[Depends(require_api_key)])
def place_limit_order(body: LimitOrderIn) -> dict:
    _ensure_symbol(body.symbol)
    order_type = mt5.ORDER_TYPE_BUY_LIMIT if body.side == "BUY" else mt5.ORDER_TYPE_SELL_LIMIT
    request = {
        "action": mt5.TRADE_ACTION_PENDING,
        "symbol": body.symbol,
        "volume": body.volume,
        "type": order_type,
        "price": body.price,
        "magic": MAGIC,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_RETURN,
    }
    result = mt5.order_send(request)
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        code = result.retcode if result else mt5.last_error()
        raise HTTPException(status_code=502, detail=f"order_send failed: {code}")
    return {"id": str(result.order), "status": "pending"}


@app.post("/positions/{position_id}/close", dependencies=[Depends(require_api_key)])
def close_position(position_id: str) -> dict:
    ticket = int(position_id)
    pos = next((p for p in (mt5.positions_get(ticket=ticket) or ()) if p.ticket == ticket), None)
    if pos is None:
        raise HTTPException(status_code=404, detail=f"Position {position_id} not found.")
    tick = mt5.symbol_info_tick(pos.symbol)
    closing_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
    price_ = tick.bid if closing_type == mt5.ORDER_TYPE_SELL else tick.ask
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": pos.symbol,
        "volume": pos.volume,
        "type": closing_type,
        "position": ticket,
        "price": price_,
        "deviation": DEVIATION_POINTS,
        "magic": MAGIC,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    result = mt5.order_send(request)
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        code = result.retcode if result else mt5.last_error()
        raise HTTPException(status_code=502, detail=f"order_send failed: {code}")
    return {"ok": True}


@app.post("/orders/{order_id}/cancel", dependencies=[Depends(require_api_key)])
def cancel_order(order_id: str) -> dict:
    request = {"action": mt5.TRADE_ACTION_REMOVE, "order": int(order_id)}
    result = mt5.order_send(request)
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        code = result.retcode if result else mt5.last_error()
        raise HTTPException(status_code=502, detail=f"order_send failed: {code}")
    return {"ok": True}
