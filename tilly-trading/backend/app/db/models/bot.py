"""Trading bot model."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Numeric, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin


class Bot(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "bots"

    # References auth.users(id) in Supabase (plain UUID; no local FK).
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    broker_account_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("broker_accounts.id"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    strategy: Mapped[str] = mapped_column(String(20), nullable=False)  # GRID, DCA
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)  # EURUSD, XAUUSD
    status: Mapped[str] = mapped_column(String(20), default="stopped", nullable=False)
    parameters: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    ai_preset_used: Mapped[str | None] = mapped_column(String(50), nullable=True)
    total_pnl: Mapped[float] = mapped_column(Numeric(15, 2), default=0, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    broker_account = relationship("BrokerAccount", back_populates="bots")
    orders = relationship("Order", back_populates="bot", cascade="all, delete-orphan")
    positions = relationship("Position", back_populates="bot", cascade="all, delete-orphan")
