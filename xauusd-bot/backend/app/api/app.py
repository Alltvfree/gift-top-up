"""FastAPI application: REST endpoints + WebSocket + dashboard.

Endpoints mirror spec §30. A live WebSocket pushes periodic snapshots. The bot
loop runs as a background task that ticks the engine on an interval; it only
places trades while the bot is "running" (default: stopped). LIVE start requires
an explicit confirmation phrase.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from app.api.service import BotService
from app.core.models import TradingMode

FRONTEND_DIR = Path(__file__).resolve().parents[3] / "frontend"

LIVE_CONFIRM_PHRASE = "ENABLE LIVE TRADING"


class StartRequest(BaseModel):
    confirm: Optional[str] = None


class EmergencyRequest(BaseModel):
    close_positions: bool = False


class SettingsRequest(BaseModel):
    risk: dict = {}
    strategy: dict = {}


class BacktestRequest(BaseModel):
    bars: int = 1500
    commission_per_lot: float = 3.0
    slippage_points: float = 5.0


class ConnectionManager:
    def __init__(self) -> None:
        self.active: List[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self.active:
            self.active.remove(ws)

    async def broadcast(self, message: dict) -> None:
        dead = []
        for ws in self.active:
            try:
                await ws.send_text(json.dumps(message, default=str))
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


def create_app(
    service: Optional[BotService] = None, *, loop_interval: float = 2.0,
    run_loop: bool = True,
) -> FastAPI:
    app = FastAPI(title="XAUUSD MT5 Trading Bot", version="0.6.0")
    app.state.service = service or BotService()
    app.state.manager = ConnectionManager()
    app.state.loop_task = None

    def svc() -> BotService:
        return app.state.service

    # --- read endpoints ------------------------------------------------------
    @app.get("/api/status")
    def status():
        return svc().status()

    @app.get("/api/account")
    def account():
        return svc().account()

    @app.get("/api/market/xauusd")
    def market():
        return svc().market_snapshot()

    @app.get("/api/positions")
    def positions():
        return svc().positions()

    @app.get("/api/trades")
    def trades():
        return svc().trades()

    @app.get("/api/signals")
    def signals():
        return svc().signals()

    @app.get("/api/performance")
    def performance():
        return svc().performance()

    @app.get("/api/equity")
    def equity():
        return svc().equity()

    @app.get("/api/chart")
    def chart():
        return svc().chart_data()

    # --- control endpoints ---------------------------------------------------
    @app.post("/api/bot/start")
    def start(req: StartRequest):
        if svc().mode is TradingMode.LIVE and req.confirm != LIVE_CONFIRM_PHRASE:
            return JSONResponse(
                status_code=400,
                content={
                    "error": "LIVE trading requires explicit confirmation",
                    "required_confirm": LIVE_CONFIRM_PHRASE,
                    "warning": (
                        "Automated trading can lose money. Past backtest "
                        "performance does not guarantee future results."
                    ),
                },
            )
        svc().start()
        return svc().status()

    @app.post("/api/bot/stop")
    def stop():
        svc().stop()
        return svc().status()

    @app.post("/api/bot/emergency-stop")
    def emergency(req: EmergencyRequest):
        return svc().emergency_stop(close_positions=req.close_positions)

    @app.post("/api/bot/resume")
    def resume():
        return svc().resume()

    @app.post("/api/settings")
    def settings(req: SettingsRequest):
        return svc().update_settings({"risk": req.risk, "strategy": req.strategy})

    @app.post("/api/backtest")
    async def backtest(req: BacktestRequest):
        return await run_in_threadpool(_run_backtest, svc(), req)

    @app.post("/api/optimization")
    async def optimization():
        return await run_in_threadpool(_run_optimization, svc())

    # --- websocket -----------------------------------------------------------
    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        await app.state.manager.connect(ws)
        try:
            await ws.send_text(json.dumps(_snapshot(svc()), default=str))
            while True:
                await ws.receive_text()  # keep-alive / client pings
        except WebSocketDisconnect:
            app.state.manager.disconnect(ws)

    # --- dashboard -----------------------------------------------------------
    @app.get("/")
    def dashboard():
        index = FRONTEND_DIR / "index.html"
        if index.exists():
            return FileResponse(index)
        return JSONResponse({"message": "dashboard not found"}, status_code=404)

    # --- background loop -----------------------------------------------------
    async def _loop():
        while True:
            await asyncio.sleep(loop_interval)
            try:
                await run_in_threadpool(svc().tick_once)
                await app.state.manager.broadcast(_snapshot(svc()))
            except Exception:  # never let the loop die silently
                pass

    @app.on_event("startup")
    async def _startup():
        if run_loop:
            app.state.loop_task = asyncio.create_task(_loop())

    @app.on_event("shutdown")
    async def _shutdown():
        task = app.state.loop_task
        if task is not None:
            task.cancel()

    return app


def _snapshot(service: BotService) -> dict:
    return {
        "type": "snapshot",
        "status": service.status(),
        "account": service.account(),
        "market": service.market_snapshot(),
        "positions": service.positions(),
        "performance": service.performance(),
    }


def _run_backtest(service: BotService, req: BacktestRequest) -> dict:
    from app.core.models import Timeframe
    from app.backtesting.engine import Backtester
    from app.backtesting.report import build_report
    from app.strategies.factory import create_strategy

    adapter = service.adapter
    candles = {
        Timeframe.H1: adapter.get_candles(service.market.symbol, Timeframe.H1,
                                          max(req.bars // 12, 60)),
        Timeframe.M15: adapter.get_candles(service.market.symbol, Timeframe.M15,
                                           max(req.bars // 3, 200)),
        Timeframe.M5: adapter.get_candles(service.market.symbol, Timeframe.M5,
                                          req.bars),
    }
    bt = Backtester(service.config, create_strategy(service.config),
                    service.symbol_info, candles,
                    commission_per_lot=req.commission_per_lot,
                    slippage_points=req.slippage_points)
    return build_report(bt.run())


def _run_optimization(service: BotService) -> dict:
    from app.core.models import Timeframe
    from app.optimization.optimizer import Optimizer

    adapter = service.adapter
    candles = {
        Timeframe.H1: adapter.get_candles(service.market.symbol, Timeframe.H1, 75),
        Timeframe.M15: adapter.get_candles(service.market.symbol, Timeframe.M15, 300),
        Timeframe.M5: adapter.get_candles(service.market.symbol, Timeframe.M5, 900),
    }
    grid = {"take_profit.risk_reward": [1.5, 2.0, 2.5, 3.0]}
    opt = Optimizer(service.config, service.symbol_info, candles, grid,
                    objective="expectancy_r", min_trades=3)
    results = opt.run(method="grid")
    return {"warnings": opt.warnings, "results": [r.to_dict() for r in results]}


__all__ = ["create_app", "ConnectionManager"]
