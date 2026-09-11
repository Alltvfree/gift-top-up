"""Smoke tests that don't require a database or broker."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.ai.preset_generator import AIPresetGenerator
from app.main import app

client = TestClient(app)


def test_health() -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_root() -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.json()["name"] == "Tilly Trading"


def test_list_ai_presets() -> None:
    resp = client.get("/api/v1/ai-presets")
    assert resp.status_code == 200
    names = {p["name"] for p in resp.json()}
    assert names == {"conservative", "balanced", "aggressive"}


def test_generate_grid_preset() -> None:
    resp = client.post(
        "/api/v1/ai-presets/generate",
        json={
            "preset": "balanced",
            "strategy": "GRID",
            "balance": 10000,
            "symbol": "XAUUSD",
            "atr": 2.5,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["strategy"] == "GRID"
    assert body["parameters"]["grid_levels"] == 10


def test_preset_generator_dca_units() -> None:
    gen = AIPresetGenerator()
    params = gen.generate_dca_params("conservative", balance=5000, symbol="EURUSD", atr=0.0012)
    assert params["strategy"] == "DCA"
    assert params["max_orders"] == 6


def test_market_symbols() -> None:
    resp = client.get("/api/v1/market/symbols")
    assert resp.status_code == 200
    assert "XAUUSD" in resp.json()["symbols"]
