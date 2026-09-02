"""ASGI entrypoint for uvicorn.

    cd xauusd-bot/backend
    PYTHONPATH=. uvicorn app.api.asgi:app --host 0.0.0.0 --port 8000

Builds the app (and the BotService behind it) from environment settings +
config. The bot loop runs but is idle until you start it from the dashboard or
POST /api/bot/start (default mode: PAPER, so no real orders).
"""

from __future__ import annotations

from app.api.app import create_app

app = create_app()

__all__ = ["app"]
