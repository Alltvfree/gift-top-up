"""End-to-end test: a full trade lifecycle through BotService.

Injects a deterministic uptrend feed so the whole stack (market -> strategy ->
risk -> paper broker -> position management -> state) runs a real open/close and
the performance snapshot reflects it.
"""

from __future__ import annotations

from app.api.service import BotService
from app.core.config import BotConfig, Settings
from app.core.models import Tick

from tests.helpers import BASE_TIME, XAUUSD, FakeAdapter, build_uptrend_dataset


def _uptrend_adapter():
    frames = build_uptrend_dataset(n_entry=400, start=1900, stop=2000)
    tick = Tick("XAUUSD", BASE_TIME, bid=1999.90, ask=2000.10)
    adapter = FakeAdapter(XAUUSD, frames, tick, balance=10_000)
    adapter.connect()
    return adapter


def _permissive_config():
    return BotConfig(
        strategy={"ema_fast": 10, "ema_slow": 20, "ema_short": 5,
                  "min_score": 70, "pullback_atr_mult": 50.0,
                  "rsi_overbought": 100.0, "rsi_oversold": 0.0},
        risk={"cooldown_minutes": 0, "max_positions": 1, "max_daily_trades": 100},
        break_even={"enabled": False}, trailing_stop={"enabled": False},
        trading_sessions={"enabled": False},
    )


def make_service(tmp_path):
    return BotService(
        settings=Settings(), config=_permissive_config(),
        state_path=str(tmp_path / "state.json"), adapter=_uptrend_adapter(),
    )


def test_full_trade_lifecycle(tmp_path):
    svc = make_service(tmp_path)

    # Idle until started.
    assert svc.tick_once().skipped_reason == "bot not running"
    svc.start()

    # First tick opens a trade in the clean uptrend.
    result = svc.tick_once()
    assert result.opened_trade
    assert len(svc.positions()) == 1

    # Price gaps above TP -> next tick closes the position via mark-to-market.
    svc.adapter.tick = Tick("XAUUSD", BASE_TIME, bid=2100.0, ask=2100.2)
    svc.tick_once()
    assert len(svc.positions()) == 0

    perf = svc.performance()
    assert perf["total_trades"] >= 1
    assert perf["net_profit"] > 0            # TP exit is a win
    assert svc.account()["balance"] > 10_000


def test_emergency_stop_halts_trading(tmp_path):
    svc = make_service(tmp_path)
    svc.start()
    svc.emergency_stop()
    result = svc.tick_once()
    # Emergency stop also stops the loop; no trade opens.
    assert not result.opened_trade
    assert len(svc.positions()) == 0


def test_status_and_equity_track_state(tmp_path):
    svc = make_service(tmp_path)
    svc.start()
    svc.tick_once()
    status = svc.status()
    assert status["running"] is True
    assert status["mode"] == "PAPER"
    assert len(svc.equity()) >= 1
