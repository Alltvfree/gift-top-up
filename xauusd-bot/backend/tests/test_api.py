"""Tests for the FastAPI app (PAPER mode, background loop disabled)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.app import create_app
from app.api.service import BotService
from app.core.models import TradingMode


@pytest.fixture()
def client(tmp_path):
    service = BotService(state_path=str(tmp_path / "state.json"))
    app = create_app(service, run_loop=False)
    with TestClient(app) as c:
        c._service = service
        yield c


def test_status_defaults_paper_stopped(client):
    r = client.get("/api/status")
    assert r.status_code == 200
    data = r.json()
    assert data["mode"] == "PAPER"
    assert data["running"] is False
    assert data["symbol"] == "XAUUSD"


def test_account_shape(client):
    data = client.get("/api/account").json()
    assert data["balance"] > 0
    assert "equity" in data and "currency" in data


def test_market_snapshot(client):
    data = client.get("/api/market/xauusd").json()
    assert data["symbol"] == "XAUUSD"
    assert "signal" in data and "score" in data
    assert data["signal"] in ("BUY", "SELL", "WAIT")


def test_read_endpoints_ok(client):
    for path in ["/api/positions", "/api/trades", "/api/signals",
                 "/api/equity", "/api/performance", "/api/chart"]:
        assert client.get(path).status_code == 200


def test_start_and_stop(client):
    assert client.post("/api/bot/start", json={}).json()["running"] is True
    assert client.post("/api/bot/stop", json={}).json()["running"] is False


def test_emergency_stop(client):
    data = client.post("/api/bot/emergency-stop", json={"close_positions": False}).json()
    assert data["emergency_stop"] is True
    assert client.get("/api/status").json()["emergency_stop"] is True
    # Resume clears it.
    client.post("/api/bot/resume", json={})
    assert client.get("/api/status").json()["emergency_stop"] is False


def test_live_start_requires_confirmation(client):
    client._service.mode = TradingMode.LIVE
    # Missing confirmation -> 400.
    r = client.post("/api/bot/start", json={})
    assert r.status_code == 400
    assert r.json()["required_confirm"] == "ENABLE LIVE TRADING"
    # Correct phrase -> starts.
    r2 = client.post("/api/bot/start", json={"confirm": "ENABLE LIVE TRADING"})
    assert r2.status_code == 200


def test_settings_update(client):
    r = client.post("/api/settings", json={"risk": {"risk_per_trade": 0.5},
                                           "strategy": {"min_score": 80}})
    applied = r.json()["applied"]
    assert applied["risk.risk_per_trade"] == 0.5
    assert applied["strategy.min_score"] == 80
    assert client._service.config.risk.risk_per_trade == 0.5


def test_websocket_sends_snapshot(client):
    with client.websocket_connect("/ws") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "snapshot"
        assert "status" in msg and "account" in msg


def test_backtest_endpoint_small(client):
    r = client.post("/api/backtest", json={"bars": 300})
    assert r.status_code == 200
    report = r.json()
    assert "metrics" in report and "equity_curve" in report


def test_dashboard_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "XAUUSD" in r.text
