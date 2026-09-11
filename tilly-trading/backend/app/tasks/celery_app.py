"""Celery application — background workers + beat for the bot engine (Task 4)."""
from __future__ import annotations

from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "tilly",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.tasks.bot_tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    # Beat: run one engine cycle every N seconds.
    beat_schedule={
        "engine-tick": {
            "task": "tilly.engine_tick",
            "schedule": float(settings.engine_tick_seconds),
        }
    },
)


@celery_app.task(name="tilly.ping")
def ping() -> str:
    """Trivial health task to verify the worker/broker wiring."""
    return "pong"
