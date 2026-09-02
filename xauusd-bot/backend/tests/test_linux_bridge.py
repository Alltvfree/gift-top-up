"""Tests for Ubuntu/Linux bridge configuration plumbing.

These verify the wiring only — they do NOT require Wine, MetaTrader5 or the
mt5linux bridge to be installed.
"""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.core.models import TradingMode
from app.mt5.base import MT5AdapterError
from app.mt5.factory import create_adapter
from app.mt5.mt5_adapter import MT5Adapter5


def test_factory_passes_bridge_settings(monkeypatch):
    settings = Settings(
        trading_mode=TradingMode.DEMO,
        mt5_use_linux_bridge=True,
        mt5_bridge_host="127.0.0.1",
        mt5_bridge_port=19999,
    )
    adapter = create_adapter(settings)
    assert isinstance(adapter, MT5Adapter5)
    assert adapter._use_linux_bridge is True
    assert adapter._bridge_host == "127.0.0.1"
    assert adapter._bridge_port == 19999


def test_bridge_without_package_raises_clear_error():
    # mt5linux is intentionally not installed in CI; the adapter must surface a
    # clear, actionable error rather than a raw ImportError.
    adapter = MT5Adapter5(use_linux_bridge=True)
    with pytest.raises(MT5AdapterError, match="mt5linux"):
        adapter.connect()


def test_native_without_package_raises_clear_error():
    adapter = MT5Adapter5(use_linux_bridge=False)
    with pytest.raises(MT5AdapterError, match="Windows-only"):
        adapter.connect()
