"""Position model (open/closed trades)."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UUIDMixin


class Position(UUIDMixin, Base):
    __tablename__ = "positions"

    bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bots.id", ondelete="CASCADE"), nullable=False
    )
    broker_position_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    side: Mapped[str] = mapped_column(String(10), nullable=False)
    volume: Mapped[float] = mapped_column(Numeric(10, 3), nullable=False)
    open_price: Mapped[float] = mapped_column(Numeric(15, 5), nullable=False)
    current_price: Mapped[float | None] = mapped_column(Numeric(15, 5), nullable=True)
    unrealized_pnl: Mapped[float] = mapped_column(Numeric(15, 2), default=0, nullable=False)
    realized_pnl: Mapped[float] = mapped_column(Numeric(15, 2), default=0, nullable=False)
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    bot = relationship("Bot", back_populates="positions")
