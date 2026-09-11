"""Engine + strategy registry tests that don't require MetaAPI."""
from __future__ import annotations

from app.services.bot_runner import build_bot
from app.bots.grid_bot import GridBot
from app.bots.dca_bot import DCABot
from app.services.engine import engine


def test_strategy_registry() -> None:
    assert isinstance(build_bot("GRID", "b1", None, {"symbol": "XAUUSD"}), GridBot)
    assert isinstance(build_bot("DCA", "b2", None, {"symbol": "EURUSD"}), DCABot)


def test_unknown_strategy_rejected() -> None:
    import pytest

    with pytest.raises(ValueError):
        build_bot("MARTINGALE", "b3", None, {})


def test_engine_idle_without_token() -> None:
    # No METAAPI_TOKEN in the test environment → engine stays idle (no loop).
    result = engine.tick()
    assert result["status"] == "idle"
