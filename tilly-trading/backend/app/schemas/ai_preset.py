"""AI preset schemas."""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.bot import Strategy


class PresetName(str, Enum):
    conservative = "conservative"
    balanced = "balanced"
    aggressive = "aggressive"


class PresetOut(BaseModel):
    name: str
    risk_level: int
    default_parameters: dict[str, Any]


class PresetGenerateRequest(BaseModel):
    preset: PresetName
    strategy: Strategy = Strategy.GRID
    balance: float = Field(gt=0)
    symbol: str
    atr: float = Field(gt=0, description="Average True Range for the symbol/timeframe")


class PresetGenerateResponse(BaseModel):
    preset: str
    strategy: str
    parameters: dict[str, Any]
