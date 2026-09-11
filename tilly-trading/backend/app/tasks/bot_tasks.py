"""Celery tasks for the trading engine (Task 4)."""
from __future__ import annotations

from app.services.engine import engine
from app.tasks.celery_app import celery_app


@celery_app.task(name="tilly.engine_tick")
def engine_tick() -> dict:
    """One engine cycle: start/stop/tick all running bots. Scheduled by beat."""
    return engine.tick()
