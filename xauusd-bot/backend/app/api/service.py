"""BotService — the stateful application core behind the API.

Owns the adapter/market/broker/engine and exposes read snapshots plus control
(start/stop the loop, emergency stop, one iteration). It keeps in-memory logs of
signals, closed trades and equity snapshots for the dashboard. Thread-safe for
the simple single-loop usage here (one lock around a tick).
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.core.config import BotConfig, Settings, load_config, load_settings
from app.core.logging import get_logger, log_event
from app.core.models import Timeframe
from app.core.state import StateStore
from app.execution.engine import EngineResult, TradingEngine
from app.execution.factory import create_broker
from app.indicators.indicators import ema
from app.mt5.factory import create_adapter
from app.mt5.market_data import MarketDataService
from app.risk.governor import RiskGovernor
from app.risk.risk_manager import RiskManager
from app.risk.sessions import SessionFilter
from app.strategies.base import StrategyInput
from app.strategies.factory import create_strategy

log = get_logger("api.service")


class BotService:
    def __init__(
        self,
        settings: Optional[Settings] = None,
        config: Optional[BotConfig] = None,
        *,
        state_path: str = "data/bot_state.json",
        adapter=None,
    ) -> None:
        self.settings = settings or load_settings()
        self.config = config or load_config()
        self.mode = self.settings.validated_mode()

        self._lock = threading.Lock()
        self.running = False

        # `adapter` may be injected (tests / custom feeds); otherwise built from
        # the trading mode.
        self.adapter = adapter or create_adapter(self.settings)
        status = self.adapter.connect()
        self.connected = status.connected

        self.market = MarketDataService(self.adapter)
        self.symbol_info = self.market.resolve_symbol(self.config.candidate_symbols)

        account = self.adapter.get_account_info()
        self.broker = create_broker(
            self.settings, self.adapter, self.symbol_info,
            starting_balance=account.balance,
        )
        self.state_store = StateStore(state_path)
        self.state = self.state_store.load()
        self.governor = RiskGovernor(
            self.config.risk, self.state,
            session_filter=SessionFilter(self.config.trading_sessions),
        )
        self.risk_manager = RiskManager(self.config.risk)
        self.strategy = create_strategy(self.config)
        self.engine = TradingEngine(
            self.config, self.market, self.strategy, self.risk_manager,
            self.governor, self.broker, self.state, self.state_store,
        )

        self.signals_log: List[dict] = []
        self.trades_log: List[dict] = []
        self.equity_log: List[dict] = []

    # --- control -------------------------------------------------------------
    def start(self) -> None:
        with self._lock:
            self.running = True
        log_event(log, "BOT_START", "bot started", mode=self.mode.value)

    def stop(self) -> None:
        with self._lock:
            self.running = False
        log_event(log, "BOT_STOP", "bot stopped")

    def emergency_stop(self, close_positions: bool = False) -> dict:
        with self._lock:
            self.running = False
            closed = self.engine.emergency_stop(close_positions=close_positions)
        return {"emergency_stop": True, "closed_positions": len(closed)}

    def resume(self) -> dict:
        with self._lock:
            self.engine.resume()
        return {"emergency_stop": False}

    def tick_once(self) -> EngineResult:
        """Run one engine iteration (only trades when running)."""
        with self._lock:
            if not self.running:
                return EngineResult(skipped_reason="bot not running")
            result = self.engine.process_once(now=datetime.now(timezone.utc))
            self._record(result)
            return result

    def _record(self, result: EngineResult) -> None:
        if result.signal is not None:
            self.signals_log.append(self._signal_dict(result.signal))
            self.signals_log[:] = self.signals_log[-200:]
        for close in result.closed:
            self.trades_log.append({
                "signal_id": close.signal_id, "ticket": close.ticket,
                "profit": close.profit, "exit": close.fill_price,
                "time": datetime.now(timezone.utc).isoformat(),
            })
        acct = self.broker.get_account()
        self.equity_log.append({
            "time": datetime.now(timezone.utc).isoformat(),
            "balance": acct.balance, "equity": acct.equity,
        })
        self.equity_log[:] = self.equity_log[-500:]

    # --- snapshots -----------------------------------------------------------
    def status(self) -> dict:
        return {
            "mode": self.mode.value,
            "running": self.running,
            "connected": self.adapter.is_connected(),
            "emergency_stop": self.state.emergency_stop,
            "symbol": self.market.symbol,
            "strategy": self.strategy.name,
            "strategy_version": self.strategy.version,
            "digits": self.symbol_info.digits,
            "trades_today": self.state.trades_today,
        }

    def account(self) -> dict:
        acct = self.broker.get_account()
        return {
            "balance": acct.balance, "equity": acct.equity,
            "margin": acct.margin, "margin_free": acct.margin_free,
            "currency": acct.currency, "server": acct.server,
        }

    def market_snapshot(self) -> dict:
        tick = self.market.get_tick()
        spread = self.market.get_spread_points()
        signal = self._read_only_signal(tick, spread)
        data: Dict[str, Any] = {
            "symbol": self.market.symbol,
            "bid": tick.bid if tick else None,
            "ask": tick.ask if tick else None,
            "spread_points": round(spread, 1) if spread is not None else None,
            "trend": signal.indicators.get("trend"),
            "signal": signal.direction.value,
            "score": signal.score,
            "reason": signal.reason,
            "entry": signal.entry, "sl": signal.stop_loss, "tp": signal.take_profit,
        }
        return data

    def positions(self) -> List[dict]:
        out = []
        for p in self.broker.get_positions(self.market.symbol):
            out.append({
                "ticket": p.ticket, "side": p.side.value, "volume": p.volume,
                "entry": p.price_open, "sl": p.sl, "tp": p.tp,
                "price": p.price_current, "profit": p.profit,
            })
        return out

    def trades(self) -> List[dict]:
        return list(reversed(self.trades_log[-100:]))

    def signals(self) -> List[dict]:
        return list(reversed(self.signals_log[-100:]))

    def equity(self) -> List[dict]:
        return list(self.equity_log)

    def performance(self) -> dict:
        profits = [t["profit"] for t in self.trades_log]
        wins = [p for p in profits if p > 0]
        losses = [p for p in profits if p <= 0]
        total = len(profits)
        return {
            "total_trades": total,
            "wins": len(wins), "losses": len(losses),
            "win_rate": round(len(wins) / total * 100, 2) if total else 0.0,
            "net_profit": round(sum(profits), 2),
            "gross_profit": round(sum(wins), 2),
            "gross_loss": round(sum(losses), 2),
            "trades_today": self.state.trades_today,
            "realized_pnl_today": round(self.state.realized_pnl_today, 2),
        }

    def chart_data(self, count: int = 150) -> dict:
        """Price + EMA overlay for the dashboard chart."""
        frame = self.market.get_ohlc_frame(Timeframe(self.config.timeframes.trend), count)
        if frame.empty:
            return {"candles": [], "ema_fast": [], "ema_slow": []}
        close = frame["close"]
        ema_fast = ema(close, self.config.strategy.ema_fast)
        ema_slow = ema(close, self.config.strategy.ema_slow)
        candles = [
            {"time": t.isoformat(), "open": float(r.open), "high": float(r.high),
             "low": float(r.low), "close": float(r.close)}
            for t, r in frame.iterrows()
        ]
        def series(s):
            return [None if v != v else round(float(v), self.symbol_info.digits)
                    for v in s]
        return {"candles": candles, "ema_fast": series(ema_fast),
                "ema_slow": series(ema_slow)}

    # --- settings ------------------------------------------------------------
    def update_settings(self, updates: dict) -> dict:
        """Update a whitelist of runtime settings (risk + strategy min_score)."""
        applied = {}
        risk = updates.get("risk", {})
        for key in ("risk_per_trade", "max_daily_loss", "max_drawdown",
                    "max_daily_trades", "max_positions", "max_spread_points",
                    "cooldown_minutes"):
            if key in risk:
                setattr(self.config.risk, key, risk[key])
                applied[f"risk.{key}"] = risk[key]
        if "min_score" in updates.get("strategy", {}):
            self.config.strategy.min_score = updates["strategy"]["min_score"]
            applied["strategy.min_score"] = self.config.strategy.min_score
        return {"applied": applied}

    # --- helpers -------------------------------------------------------------
    def _read_only_signal(self, tick, spread):
        return self.strategy.evaluate(
            StrategyInput(
                symbol_info=self.symbol_info,
                trend_df=self.market.get_ohlc_frame(
                    Timeframe(self.config.timeframes.trend), 300),
                setup_df=self.market.get_ohlc_frame(
                    Timeframe(self.config.timeframes.setup), 250),
                entry_df=self.market.get_ohlc_frame(
                    Timeframe(self.config.timeframes.entry), 250),
                tick=tick, spread_points=spread,
            )
        )

    def _signal_dict(self, signal) -> dict:
        return {
            "signal_id": signal.signal_id,
            "time": signal.timestamp.isoformat(),
            "direction": signal.direction.value, "score": signal.score,
            "entry": signal.entry, "sl": signal.stop_loss, "tp": signal.take_profit,
            "reason": signal.reason,
        }


__all__ = ["BotService"]
