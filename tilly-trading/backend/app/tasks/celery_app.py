"""Celery application — background workers for the bot engine.

Task definitions (start/stop bot loops, price polling) are added in Task 4.
"""
from __future__ import annotations

from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "tilly",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
)


@celery_app.task(name="tilly.ping")
def ping() -> str:
    """Trivial health task to verify the worker/broker wiring."""
    return "pong"
