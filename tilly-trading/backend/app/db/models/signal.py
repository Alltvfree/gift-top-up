"""Signal model — read-only from the backend's side.

Rows are written by Kronos (tilly-trading/kronos/publish_signal.py) using
Supabase's service_role key, which bypasses this table's RLS policy — the
backend's own DB user only ever SELECTs from it. See
tilly-trading/supabase/migrations/0007_signals.sql for the schema and RLS.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDMixin


class Signal(UUIDMixin, Base):
    __tablename__ = "signals"

    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    side: Mapped[str] = mapped_column(String(10), nullable=False)  # BUY | SELL | NO_TRADE
    confidence: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(10), nullable=False)
    tp: Mapped[float | None] = mapped_column(Numeric(15, 5), nullable=True)
    sl: Mapped[float | None] = mapped_column(Numeric(15, 5), nullable=True)
    expected_move: Mapped[float | None] = mapped_column(Numeric(8, 3), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="kronos")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
