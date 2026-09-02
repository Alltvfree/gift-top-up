"""Risk engine — approves or rejects a trade and sizes it.

The risk manager is the single gate every actionable signal must pass before it
can become an order. Phase 2 implements the **per-trade** checks that need no
persistent state:

* the signal is actionable and carries a stop-loss (never trade without an SL);
* spread is within the configured maximum;
* open-position count is below the configured maximum;
* a broker-valid lot size fits inside the risk budget.

The **stateful** protections — daily loss / drawdown / max-daily-trades /
cooldown / emergency-stop — are layered on in Phase 3, where trade history and
equity snapshots are tracked.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from app.core.config import RiskConfig
from app.core.logging import get_logger, log_event
from app.core.models import AccountInfo, Signal, SymbolInfo
from app.risk.position_sizing import PositionSize, calculate_position_size

log = get_logger("risk.manager")


@dataclass
class RiskDecision:
    """Outcome of a risk evaluation."""

    approved: bool
    lot_size: float = 0.0
    risk_amount: float = 0.0
    reasons: List[str] = field(default_factory=list)
    sizing: Optional[PositionSize] = None

    @property
    def reason(self) -> str:
        return "; ".join(self.reasons) if self.reasons else (
            "approved" if self.approved else "rejected"
        )


class RiskManager:
    """Stateless (Phase 2) per-trade risk checks and position sizing."""

    def __init__(self, config: RiskConfig, *, max_lots: Optional[float] = None) -> None:
        self.config = config
        self._max_lots = max_lots

    def evaluate(
        self,
        signal: Signal,
        account: AccountInfo,
        symbol_info: SymbolInfo,
        *,
        spread_points: Optional[float] = None,
        open_positions: int = 0,
    ) -> RiskDecision:
        reasons: List[str] = []

        # --- Gate 1: actionable signal with a stop-loss -----------------------
        if not signal.is_actionable:
            return self._reject(["signal is not actionable (WAIT)"])
        if signal.entry is None or signal.stop_loss is None:
            return self._reject(["signal has no entry/stop-loss — refusing"])

        # --- Gate 2: spread ---------------------------------------------------
        if spread_points is not None and spread_points > self.config.max_spread_points:
            reasons.append(
                f"spread {spread_points:.1f} > max {self.config.max_spread_points}"
            )

        # --- Gate 3: max simultaneous positions -------------------------------
        if open_positions >= self.config.max_positions:
            reasons.append(
                f"open positions {open_positions} >= max {self.config.max_positions}"
            )

        # --- Gate 4: position sizing within risk budget -----------------------
        sizing = calculate_position_size(
            equity=account.equity,
            risk_percent=self.config.risk_per_trade,
            entry=signal.entry,
            stop_loss=signal.stop_loss,
            symbol_info=symbol_info,
            max_lots=self._max_lots,
        )
        if not sizing.ok:
            reasons.append(f"position sizing failed: {sizing.rejected_reason}")

        if reasons:
            log_event(
                log, "TRADE_REJECTED", "risk gate rejected signal",
                level=30, signal_id=signal.signal_id, reasons=reasons,
            )
            return RiskDecision(approved=False, reasons=reasons, sizing=sizing)

        log_event(
            log, "TRADE_APPROVED", "risk gate approved signal",
            signal_id=signal.signal_id, lots=sizing.lots,
            risk_amount=sizing.risk_amount,
        )
        return RiskDecision(
            approved=True,
            lot_size=sizing.lots,
            risk_amount=sizing.risk_amount,
            reasons=["approved"],
            sizing=sizing,
        )

    @staticmethod
    def _reject(reasons: List[str]) -> RiskDecision:
        return RiskDecision(approved=False, reasons=reasons)


__all__ = ["RiskManager", "RiskDecision"]
