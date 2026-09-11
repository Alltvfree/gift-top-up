"""Database initialization: create tables and seed built-in AI presets.

Called on app startup so local development works with zero manual steps
(SQLite by default). In production you'd rely on Alembic migrations instead,
but `create_all` is idempotent and only creates missing tables.
"""
from __future__ import annotations

from sqlalchemy import select

from app.ai.preset_generator import AIPresetGenerator
from app.core.config import settings
from app.db.base import Base
from app.db.models.ai_preset import AIPreset
from app.db.session import async_session_factory, engine

# On Postgres/Supabase the schema is managed by SQL migrations
# (supabase/migrations/*), so we never auto-create tables there — only for the
# local SQLite dev database.
_MANAGE_SCHEMA = settings.database_url.startswith("sqlite")


async def create_tables() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def seed_presets() -> None:
    async with async_session_factory() as session:
        existing = (await session.execute(select(AIPreset.name))).scalars().all()
        if existing:
            return
        for name, config in AIPresetGenerator.PRESETS.items():
            session.add(
                AIPreset(
                    name=name,
                    risk_level=config["risk_level"],
                    default_parameters={k: v for k, v in config.items() if k != "risk_level"},
                )
            )
        await session.commit()


async def init_db() -> None:
    if not _MANAGE_SCHEMA:
        # Supabase-managed schema; nothing to create or seed here.
        return
    await create_tables()
    await seed_presets()
