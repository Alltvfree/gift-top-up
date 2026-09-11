"""Broker account model (a broker login linked to a user)."""
from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Numeric, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin


class BrokerAccount(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "broker_accounts"

    # References auth.users(id) in Supabase; kept as a plain UUID here so the
    # backend does not need to manage the Supabase-owned users table.
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    broker_name: Mapped[str] = mapped_column(String(50), nullable=False)  # exness, xm, vantage
    account_id: Mapped[str] = mapped_column(String(100), nullable=False)  # broker-side login
    account_type: Mapped[str] = mapped_column(String(20), default="demo", nullable=False)
    balance: Mapped[float | None] = mapped_column(Numeric(15, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(10), default="USD", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    metaapi_account_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # ----- Provisioning (MetaAPI) -----
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    server: Mapped[str | None] = mapped_column(String(120), nullable=True)
    platform: Mapped[str] = mapped_column(String(10), default="mt5", nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    bots = relationship("Bot", back_populates="broker_account")
