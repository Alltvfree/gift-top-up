"""NewsEvent model — read-only from the backend's side.

Rows are written externally (manually, or by a future script pulling a
real economic-calendar feed) using Supabase's service_role key, which
bypasses this table's RLS policy — the backend's own DB user only ever
SELECTs from it. See
tilly-trading/supabase/migrations/0008_news_events.sql for the schema and
RLS.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDMixin


class NewsEvent(UUIDMixin, Base):
    __tablename__ = "news_events"

    currency: Mapped[str] = mapped_column(String(10), nullable=False)  # e.g. USD, EUR, ALL
    event_name: Mapped[str] = mapped_column(String(200), nullable=False)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    impact: Mapped[str] = mapped_column(String(10), nullable=False, default="high")  # low|medium|high
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="manual")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
