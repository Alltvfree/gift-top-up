"""Order model (orders placed by bots)."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin


class Order(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "orders"

    bot_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("bots.id", ondelete="CASCADE"), nullable=False
    )
    broker_order_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    side: Mapped[str] = mapped_column(String(10), nullable=False)  # BUY, SELL
    type: Mapped[str] = mapped_column(String(20), nullable=False)  # MARKET, LIMIT, STOP
    price: Mapped[float | None] = mapped_column(Numeric(15, 5), nullable=True)
    volume: Mapped[float] = mapped_column(Numeric(10, 3), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    filled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    bot = relationship("Bot", back_populates="orders")
