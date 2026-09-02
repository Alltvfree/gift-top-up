"""Broker abstraction for order execution.

The trading engine talks only to this interface, so PAPER mode (a fully
simulated :class:`PaperBroker`) and DEMO/LIVE (a real MT5 broker) are
interchangeable. Order submission is **idempotent** on ``signal_id`` — a retry
or a duplicate signal never opens a second position (spec §17).
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import List, Optional

from app.core.models import AccountInfo, OrderSide, Position


@dataclass(frozen=True)
class OrderRequest:
    """A market-order request. Every order must carry an SL (spec §16)."""

    signal_id: str          # idempotency key
    symbol: str
    side: OrderSide
    volume: float
    stop_loss: float
    take_profit: float
    price: Optional[float] = None   # reference price; None = use current tick
    comment: str = ""
    magic: int = 0

    def __post_init__(self) -> None:
        if self.volume <= 0:
            raise ValueError("order volume must be positive")
        if self.stop_loss is None:
            raise ValueError("refusing to build an order without a stop-loss")


@dataclass(frozen=True)
class OrderResult:
    """Outcome of an order submission or close."""

    success: bool
    signal_id: str
    ticket: Optional[int] = None
    fill_price: Optional[float] = None
    volume: float = 0.0
    side: Optional[OrderSide] = None
    profit: float = 0.0
    message: str = ""
    duplicate: bool = False     # idempotency prevented a new order

    @property
    def executed(self) -> bool:
        return self.success and not self.duplicate


class Broker(abc.ABC):
    """Order-execution contract."""

    @abc.abstractmethod
    def submit_order(self, request: OrderRequest) -> OrderResult:
        """Open a position for the request. Idempotent on ``signal_id``."""

    @abc.abstractmethod
    def modify_position(
        self, ticket: int, *, stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
    ) -> bool:
        """Modify SL/TP of an open position. Returns True on success."""

    @abc.abstractmethod
    def close_position(self, ticket: int) -> OrderResult:
        """Close an open position at the current price."""

    @abc.abstractmethod
    def get_positions(self, symbol: Optional[str] = None) -> List[Position]:
        """Return open positions."""

    @abc.abstractmethod
    def get_account(self) -> AccountInfo:
        """Return the account snapshot (simulated for paper)."""


__all__ = ["Broker", "OrderRequest", "OrderResult"]
