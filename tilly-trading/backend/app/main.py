"""FastAPI application entrypoint for Tilly Trading."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.v1.router import api_router
from app.core.config import settings
from app.db.init_db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables (if missing) and seed AI presets so local dev needs no
    # manual migration step. Production can rely on Alembic instead.
    await init_db()
    yield


app = FastAPI(
    title=settings.app_name,
    version=__version__,
    description="Cloud automated forex trading platform — GRID & DCA bots.",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_origin_regex=settings.cors_origin_regex or None,
    # No cookies are used (auth is a bearer token), so credentials stay off —
    # which lets the browser accept the explicit header list below on preflight.
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    # "Authorization" must be listed explicitly; a "*" wildcard does not cover it.
    allow_headers=["Authorization", "Content-Type", "Accept", "Origin"],
)

app.include_router(api_router, prefix=settings.api_v1_prefix)


@app.get("/", tags=["meta"])
async def root() -> dict:
    return {
        "name": settings.app_name,
        "version": __version__,
        "docs": "/docs",
    }


@app.get("/health", tags=["meta"])
async def health() -> dict:
    # `build` is bumped on deploys we need to confirm are live.
    return {"status": "ok", "environment": settings.environment, "build": "db1"}


@app.get("/dbcheck", tags=["meta"])
async def dbcheck() -> dict:
    """Test the database connection and return the real error (CORS-safe)."""
    from sqlalchemy import text

    from app.db.session import engine

    try:
        async with engine.connect() as conn:
            await conn.execute(text("select 1"))
        return {"db": "ok"}
    except Exception as exc:  # noqa: BLE001
        return {"db": "error", "type": type(exc).__name__, "detail": str(exc)[:400]}
