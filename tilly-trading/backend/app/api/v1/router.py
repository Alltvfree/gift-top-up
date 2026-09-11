"""Aggregate v1 API router."""
from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import ai_presets, auth, bots, broker, market

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(bots.router, prefix="/bots", tags=["bots"])
api_router.include_router(broker.router, prefix="/broker", tags=["broker"])
api_router.include_router(ai_presets.router, prefix="/ai-presets", tags=["ai-presets"])
api_router.include_router(market.router, prefix="/market", tags=["market"])
