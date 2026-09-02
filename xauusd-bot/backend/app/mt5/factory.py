"""Adapter factory — selects the real or mock MT5 adapter based on mode.

BACKTEST / PAPER  -> :class:`MockMT5Adapter` (synthetic data, no terminal)
DEMO / LIVE       -> :class:`MT5Adapter5`   (real MetaTrader 5 terminal)
"""

from __future__ import annotations

from app.core.config import Settings
from app.core.models import TradingMode
from app.mt5.base import MT5Adapter
from app.mt5.mock_adapter import MockMT5Adapter


def create_adapter(settings: Settings) -> MT5Adapter:
    """Build the appropriate adapter for the configured trading mode."""
    mode = settings.validated_mode()  # enforces the LIVE safety gate
    if mode in (TradingMode.DEMO, TradingMode.LIVE):
        # Imported lazily so environments without MetaTrader5 can still import
        # this module and use the mock.
        from app.mt5.mt5_adapter import MT5Adapter5

        return MT5Adapter5(
            login=settings.mt5_login,
            password=settings.mt5_password,
            server=settings.mt5_server,
            terminal_path=settings.mt5_terminal_path,
        )
    return MockMT5Adapter()


__all__ = ["create_adapter"]
