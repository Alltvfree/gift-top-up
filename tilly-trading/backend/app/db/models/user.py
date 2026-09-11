"""User model."""
from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


class User(UUIDMixin, TimestampMixin, Base):
    """Legacy local-auth user (SQLite dev only).

    In the deployed system authentication is handled by Supabase Auth, and
    `bots.user_id` / `broker_accounts.user_id` reference auth.users. This model
    remains only for the local SQLite dev API + tests and is standalone.
    """

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subscription_tier: Mapped[str] = mapped_column(String(50), default="free", nullable=False)
