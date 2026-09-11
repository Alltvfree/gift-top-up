"""End-to-end flow: register → login → create bot → start → stop → delete.

Uses `with TestClient(app)` so the app lifespan runs and creates the tables.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def _auth_headers(client: TestClient, email: str) -> dict[str, str]:
    reg = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "supersecret123", "full_name": "Test Trader"},
    )
    assert reg.status_code == 201, reg.text
    token = reg.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_full_bot_flow() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client, "trader1@example.com")

        # /me
        me = client.get("/api/v1/auth/me", headers=headers)
        assert me.status_code == 200
        assert me.json()["email"] == "trader1@example.com"

        # login (OAuth2 form)
        login = client.post(
            "/api/v1/auth/login",
            data={"username": "trader1@example.com", "password": "supersecret123"},
        )
        assert login.status_code == 200
        assert login.json()["token_type"] == "bearer"

        # create bot
        created = client.post(
            "/api/v1/bots",
            headers=headers,
            json={
                "name": "Gold Grid",
                "strategy": "GRID",
                "symbol": "XAUUSD",
                "parameters": {"grid_levels": 10, "lot_size": 0.05},
            },
        )
        assert created.status_code == 201, created.text
        bot = created.json()
        assert bot["status"] == "stopped"
        bot_id = bot["id"]

        # list
        listing = client.get("/api/v1/bots", headers=headers)
        assert listing.status_code == 200
        assert len(listing.json()) == 1

        # start / stop
        started = client.post(f"/api/v1/bots/{bot_id}/start", headers=headers)
        assert started.status_code == 200
        assert started.json()["status"] == "running"

        stopped = client.post(f"/api/v1/bots/{bot_id}/stop", headers=headers)
        assert stopped.status_code == 200
        assert stopped.json()["status"] == "stopped"

        # orders / positions (empty for now)
        assert client.get(f"/api/v1/bots/{bot_id}/orders", headers=headers).json() == []
        assert client.get(f"/api/v1/bots/{bot_id}/positions", headers=headers).json() == []

        # delete
        assert client.delete(f"/api/v1/bots/{bot_id}", headers=headers).status_code == 204
        assert client.get("/api/v1/bots", headers=headers).json() == []


def test_bots_require_auth() -> None:
    with TestClient(app) as client:
        assert client.get("/api/v1/bots").status_code == 401


def test_duplicate_email_rejected() -> None:
    with TestClient(app) as client:
        _auth_headers(client, "dup@example.com")
        again = client.post(
            "/api/v1/auth/register",
            json={"email": "dup@example.com", "password": "supersecret123"},
        )
        assert again.status_code == 409


def test_isolation_between_users() -> None:
    with TestClient(app) as client:
        a = _auth_headers(client, "owner@example.com")
        b = _auth_headers(client, "other@example.com")
        created = client.post(
            "/api/v1/bots",
            headers=a,
            json={"name": "A bot", "strategy": "DCA", "symbol": "EURUSD"},
        )
        bot_id = created.json()["id"]
        # user B cannot see or touch user A's bot
        assert client.get(f"/api/v1/bots/{bot_id}", headers=b).status_code == 404
