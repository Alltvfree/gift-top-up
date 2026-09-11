"""FastAPI application entrypoint for Tilly Trading."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.v1.router import api_router
from app.core.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup / shutdown hooks (broker pools, warm caches) attach here later.
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
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
    return {"status": "ok", "environment": settings.environment}
