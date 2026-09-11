"""Declarative base + a metadata import surface for Alembic autogenerate.

Importing `app.db.base` pulls in every model so that
`Base.metadata` is fully populated for migrations.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Uuid, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for all ORM models."""


class UUIDMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


# Import models so they register on Base.metadata (needed by Alembic).
from app.db.models import (  # noqa: E402,F401
    ai_preset,
    bot,
    broker_account,
    order,
    position,
    user,
)
