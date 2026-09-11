"""Broker account model (a broker login linked to a user)."""
from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin


class BrokerAccount(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "broker_accounts"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    broker_name: Mapped[str] = mapped_column(String(50), nullable=False)  # exness, xm, vantage
    account_id: Mapped[str] = mapped_column(String(100), nullable=False)  # broker-side id
    account_type: Mapped[str] = mapped_column(String(20), default="live", nullable=False)
    balance: Mapped[float | None] = mapped_column(Numeric(15, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(10), default="USD", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    metaapi_account_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    user = relationship("User", back_populates="broker_accounts")
    bots = relationship("Bot", back_populates="broker_account")
