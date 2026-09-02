"""TradingEngine — one deterministic iteration of the trading loop.

Wires strategy → risk → execution → position management with the protections
that make automated trading safe to leave running:

* **Candle dedup** — a completed entry-timeframe candle is evaluated exactly once
  (spec §18), preventing repeat entries on the same bar.
* **Idempotent execution** — orders are keyed by ``signal_id`` end-to-end, so a
  retry never opens a second position (spec §17).
* **Stateful risk gates** — the :class:`RiskGovernor` (daily loss/drawdown/
  cooldown/max-trades/emergency-stop) plus the per-trade :class:`RiskManager`.
* **Position management** — break-even and ATR trailing applied every iteration.
* **Persistence** — state is saved each iteration so an emergency stop and the
  daily counters survive a restart.

``process_once`` is pure with respect to wall-clock time (``now`` is injected),
so the whole loop is unit-testable without sleeping.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

from app.core.config import BotConfig
from app.core.logging import get_logger, log_event
from app.core.models import Signal, SignalType, Timeframe
from app.core.state import BotState, StateStore, TradeMeta
from app.execution.broker import Broker, OrderRequest, OrderResult
from app.execution.paper_broker import PaperBroker
from app.execution.position_manager import manage_stop
from app.indicators.indicators import atr as atr_ind
from app.mt5.market_data import MarketDataService
from app.risk.governor import RiskGovernor
from app.risk.risk_manager import RiskManager
from app.strategies.base import Strategy, StrategyInput

log = get_logger("execution.engine")


@dataclass
class EngineResult:
    """Summary of one iteration (for logging / tests / dashboard)."""

    signal: Optional[Signal] = None
    order: Optional[OrderResult] = None
    closed: List[OrderResult] = field(default_factory=list)
    stop_updates: int = 0
    skipped_reason: str = ""
    gate_reason: str = ""

    @property
    def opened_trade(self) -> bool:
        return self.order is not None and self.order.executed


class TradingEngine:
    def __init__(
        self,
        config: BotConfig,
        market: MarketDataService,
        strategy: Strategy,
        risk_manager: RiskManager,
        governor: RiskGovernor,
        broker: Broker,
        state: BotState,
        state_store: StateStore,
    ) -> None:
        self.config = config
        self.market = market
        self.strategy = strategy
        self.risk_manager = risk_manager
        self.governor = governor
        self.broker = broker
        self.state = state
        self.state_store = state_store
        self._entry_tf = Timeframe(config.timeframes.entry)

    # --- emergency stop ------------------------------------------------------
    def emergency_stop(self, *, close_positions: bool = False) -> List[OrderResult]:
        """Activate the persisted emergency stop; optionally flatten positions."""
        self.governor.trigger_emergency_stop()
        closed: List[OrderResult] = []
        if close_positions:
            for pos in self.broker.get_positions(self.market.symbol):
                closed.append(self.broker.close_position(pos.ticket))
                self.state.remove_open_trade(pos.ticket)
        log_event(
            log, "EMERGENCY_STOP", "emergency stop activated",
            level=40, closed=len(closed),
        )
        self.state_store.save(self.state)
        return closed

    def resume(self) -> None:
        self.governor.clear_emergency_stop()
        log_event(log, "EMERGENCY_STOP_CLEARED", "trading resumed")
        self.state_store.save(self.state)

    # --- main iteration ------------------------------------------------------
    def process_once(self, now: Optional[datetime] = None) -> EngineResult:
        now = now or datetime.now(timezone.utc)
        result = EngineResult()
        symbol = self.market.symbol

        tick = self.market.get_tick()

        # 1) Mark simulated positions and collect SL/TP auto-closes (paper only).
        profit_by_ticket: dict[int, float] = {}
        if isinstance(self.broker, PaperBroker) and tick is not None:
            for close in self.broker.mark_to_market(tick):
                profit_by_ticket[close.ticket] = close.profit
                result.closed.append(close)

        # 2) Reconcile closes against tracked open trades (paper + real).
        self._reconcile_closes(now, profit_by_ticket)

        # 3) Account snapshot + daily bookkeeping.
        account = self.broker.get_account()
        self.governor.sync_equity(now, account.equity)

        # 4) Manage stops on remaining open positions.
        result.stop_updates = self._manage_positions()

        # 5) Candle dedup — evaluate a completed entry candle only once.
        entry_df = self.market.get_ohlc_frame(self._entry_tf, 250)
        if entry_df.empty:
            result.skipped_reason = "no candle data"
            self.state_store.save(self.state)
            return result
        candle_time = _idx_to_dt(entry_df.index[-1])
        if self.state.is_candle_processed(symbol, self._entry_tf.value, candle_time):
            result.skipped_reason = "candle already processed"
            self.state_store.save(self.state)
            return result

        # 6) Stateful gate.
        gate = self.governor.can_open_new_trade(now, account.equity)
        result.gate_reason = gate.reason
        if not gate.allowed:
            self.state.mark_candle_processed(symbol, self._entry_tf.value, candle_time)
            log_event(log, "TRADE_GATE_BLOCKED", gate.reason, level=30)
            self.state_store.save(self.state)
            return result

        # 7) Evaluate the strategy.
        spread_points = self.market.get_spread_points()
        signal = self.strategy.evaluate(
            StrategyInput(
                symbol_info=self.market.symbol_info,
                trend_df=self.market.get_ohlc_frame(
                    Timeframe(self.config.timeframes.trend), 300),
                setup_df=self.market.get_ohlc_frame(
                    Timeframe(self.config.timeframes.setup), 250),
                entry_df=entry_df,
                tick=tick,
                spread_points=spread_points,
                now=now,
            )
        )
        result.signal = signal
        log_event(
            log, "SIGNAL_GENERATED", signal.reason,
            direction=signal.direction.value, score=signal.score,
        )

        # 8) Execute if actionable and approved.
        if signal.is_actionable and signal.signal_id not in self.state.executed_signals:
            result.order = self._try_execute(signal, account, spread_points, now)

        self.state.mark_candle_processed(symbol, self._entry_tf.value, candle_time)
        self.state_store.save(self.state)
        return result

    # --- helpers -------------------------------------------------------------
    def _try_execute(
        self, signal: Signal, account, spread_points, now: datetime
    ) -> Optional[OrderResult]:
        open_positions = len(self.broker.get_positions(self.market.symbol))
        decision = self.risk_manager.evaluate(
            signal, account, self.market.symbol_info,
            spread_points=spread_points, open_positions=open_positions,
        )
        if not decision.approved:
            log_event(log, "TRADE_REJECTED", decision.reason, level=30,
                      signal_id=signal.signal_id)
            return None

        request = OrderRequest(
            signal_id=signal.signal_id, symbol=self.market.symbol,
            side=signal.direction.to_side(), volume=decision.lot_size,
            stop_loss=signal.stop_loss, take_profit=signal.take_profit,
            price=signal.entry, comment=self.strategy.name,
        )
        log_event(log, "ORDER_SENT", "submitting order",
                  signal_id=signal.signal_id, lots=decision.lot_size)
        order = self.broker.submit_order(request)
        if order.executed and order.ticket is not None:
            self.governor.register_trade_opened()
            self.state.add_open_trade(
                TradeMeta(
                    ticket=order.ticket, signal_id=signal.signal_id,
                    side=signal.direction.value,
                    entry=order.fill_price or signal.entry,
                    initial_sl=signal.stop_loss, volume=decision.lot_size,
                )
            )
        return order

    def _reconcile_closes(self, now: datetime, profit_by_ticket: dict) -> None:
        current = {p.ticket for p in self.broker.get_positions(self.market.symbol)}
        for ticket_str in list(self.state.open_trades):
            ticket = int(ticket_str)
            if ticket in current:
                continue
            profit = profit_by_ticket.get(ticket, 0.0)
            self.governor.register_trade_closed(profit, now)
            self.state.remove_open_trade(ticket)
            log_event(log, "TRADE_RECONCILED_CLOSED",
                      "tracked position no longer open", ticket=ticket,
                      profit=round(profit, 2))

    def _manage_positions(self) -> int:
        updates = 0
        setup_tf = Timeframe(self.config.timeframes.setup)
        setup_df = self.market.get_ohlc_frame(setup_tf, 250)
        if setup_df.empty:
            return 0
        atr_value = float(
            atr_ind(setup_df["high"], setup_df["low"], setup_df["close"],
                    self.config.stop_loss.atr_period).iloc[-1]
        )
        info = self.market.symbol_info
        for pos in self.broker.get_positions(self.market.symbol):
            meta = self.state.get_open_trade(pos.ticket)
            if meta is None:
                continue
            update = manage_stop(
                pos.side, meta.entry, meta.initial_sl, pos.price_current, pos.sl,
                atr_value, info, self.config.break_even, self.config.trailing_stop,
            )
            if update is not None and self.broker.modify_position(
                pos.ticket, stop_loss=update.new_sl
            ):
                updates += 1
                if update.reason == "break_even":
                    meta.break_even_done = True
                    self.state.open_trades[str(pos.ticket)] = _meta_dict(meta)
                log_event(log, "SL_MODIFIED", f"stop moved ({update.reason})",
                          ticket=pos.ticket, new_sl=update.new_sl)
        return updates


def _idx_to_dt(idx) -> datetime:
    try:
        return idx.to_pydatetime()
    except AttributeError:
        return idx


def _meta_dict(meta: TradeMeta) -> dict:
    from dataclasses import asdict
    return asdict(meta)


__all__ = ["TradingEngine", "EngineResult"]
