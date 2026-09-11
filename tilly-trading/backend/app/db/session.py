"""Async SQLAlchemy engine & session factory.

Works out of the box with SQLite (local dev) and PostgreSQL (Docker,
Supabase, RDS, etc.). For Supabase set DATABASE_SSL=true; if you use the
Supabase connection *pooler* (pgBouncer, port 6543) also set
DATABASE_PGBOUNCER=true so asyncpg disables server-side prepared statements.
"""
from __future__ import annotations

import ssl

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

_is_sqlite = settings.database_url.startswith("sqlite")
_is_asyncpg = "asyncpg" in settings.database_url

connect_args: dict = {}
if _is_asyncpg:
    if settings.database_ssl:
        # Encrypt the connection but do not verify the certificate chain — this
        # matches Supabase's `sslmode=require` (their pooler presents a chain
        # Python's default verifier rejects as self-signed).
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
        connect_args["ssl"] = ssl_ctx
    if settings.database_pgbouncer:
        # pgBouncer transaction pooling is incompatible with prepared-statement caching.
        connect_args["statement_cache_size"] = 0

engine = create_async_engine(
    settings.database_url,
    echo=settings.db_echo,
    # SQLite doesn't support pool_pre_ping the same way; it's harmless but skip it.
    pool_pre_ping=not _is_sqlite,
    connect_args=connect_args,
)

async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)
