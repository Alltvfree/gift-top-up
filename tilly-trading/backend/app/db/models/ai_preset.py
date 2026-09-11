"""AI preset model (named risk profiles with default parameters)."""
from __future__ import annotations

from sqlalchemy import Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


class AIPreset(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "ai_presets"

    name: Mapped[str] = mapped_column(String(50), nullable=False)  # conservative, balanced, aggressive
    risk_level: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-10
    default_parameters: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
