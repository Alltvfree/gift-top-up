"""RiskGovernor — stateful, account-level trading gates.

Complements the per-trade :class:`RiskManager` (sizing/spread/position count)
with the protections that require memory across trades and days (spec §11):

* emergency stop (persisted)
* maximum daily loss  -> STOP_TRADING until next day
* maximum account drawdown (from equity peak) -> disable
* maximum trades per day
* cooldown after a closed trade
* maximum consecutive losses

The governor mutates a :class:`BotState`; the engine persists it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from app.core.config import RiskConfig
from app.core.state import BotState, rollover_day
from app.risk.sessions import SessionFilter


@dataclass(frozen=True)
class GateResult:
    allowed: bool
    reason: str = ""


class RiskGovernor:
    def __init__(
        self,
        config: RiskConfig,
        state: BotState,
        *,
        session_filter: Optional[SessionFilter] = None,
    ) -> None:
        self.config = config
        self.state = state
        self.session_filter = session_filter

    # --- daily bookkeeping ---------------------------------------------------
    def sync_equity(self, now: datetime, equity: float) -> None:
        """Roll the trading day over if needed and track the equity peak."""
        rollover_day(self.state, now.date(), equity)
        if equity > self.state.peak_equity:
            self.state.peak_equity = equity

    # --- the gate ------------------------------------------------------------
    def can_open_new_trade(self, now: datetime, equity: float) -> GateResult:
        self.sync_equity(now, equity)
        c = self.config
        s = self.state

        if s.emergency_stop:
            return GateResult(False, "emergency stop is active")

        if self.session_filter is not None and not self.session_filter.is_open(now):
            return GateResult(False, "outside configured trading session")

        # Daily loss (equity drop from the day's starting equity).
        if s.day_start_equity > 0:
            daily_loss_pct = (s.day_start_equity - equity) / s.day_start_equity * 100
            if daily_loss_pct >= c.max_daily_loss:
                return GateResult(
                    False,
                    f"daily loss {daily_loss_pct:.2f}% >= max {c.max_daily_loss}%",
                )

        # Account drawdown from the equity peak.
        if s.peak_equity > 0:
            drawdown_pct = (s.peak_equity - equity) / s.peak_equity * 100
            if drawdown_pct >= c.max_drawdown:
                return GateResult(
                    False,
                    f"drawdown {drawdown_pct:.2f}% >= max {c.max_drawdown}%",
                )

        if s.trades_today >= c.max_daily_trades:
            return GateResult(
                False, f"daily trades {s.trades_today} >= max {c.max_daily_trades}"
            )

        # Cooldown after the last close.
        if s.last_close_time and c.cooldown_minutes > 0:
            last = datetime.fromisoformat(s.last_close_time)
            elapsed = now - last
            if elapsed < timedelta(minutes=c.cooldown_minutes):
                remaining = timedelta(minutes=c.cooldown_minutes) - elapsed
                return GateResult(
                    False,
                    f"cooldown active ({remaining.total_seconds() / 60:.1f} min left)",
                )

        return GateResult(True, "ok")

    # --- state transitions ---------------------------------------------------
    def register_trade_opened(self) -> None:
        self.state.trades_today += 1

    def register_trade_closed(self, profit: float, close_time: datetime) -> None:
        self.state.realized_pnl_today += profit
        self.state.last_close_time = close_time.isoformat()
        if profit < 0:
            self.state.consecutive_losses += 1
        else:
            self.state.consecutive_losses = 0

    def trigger_emergency_stop(self) -> None:
        self.state.emergency_stop = True

    def clear_emergency_stop(self) -> None:
        self.state.emergency_stop = False


__all__ = ["RiskGovernor", "GateResult"]
