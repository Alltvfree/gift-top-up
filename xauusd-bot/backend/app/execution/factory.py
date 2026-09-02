"""Broker factory — selects the paper or real broker for the trading mode."""

from __future__ import annotations

from app.core.config import Settings
from app.core.models import SymbolInfo, TradingMode
from app.execution.broker import Broker
from app.execution.paper_broker import PaperBroker
from app.mt5.base import MT5Adapter


def create_broker(
    settings: Settings,
    adapter: MT5Adapter,
    symbol_info: SymbolInfo,
    *,
    starting_balance: float,
    commission_per_lot: float = 0.0,
    slippage_points: float = 0.0,
) -> Broker:
    """BACKTEST/PAPER -> PaperBroker; DEMO/LIVE -> MT5Broker."""
    mode = settings.validated_mode()
    if mode in (TradingMode.DEMO, TradingMode.LIVE):
        from app.execution.mt5_broker import MT5Broker
        from app.mt5.mt5_adapter import MT5Adapter5

        if not isinstance(adapter, MT5Adapter5):
            raise TypeError("DEMO/LIVE requires the real MT5Adapter5")
        return MT5Broker(adapter)
    return PaperBroker(
        symbol_info,
        starting_balance=starting_balance,
        commission_per_lot=commission_per_lot,
        slippage_points=slippage_points,
    )


__all__ = ["create_broker"]
