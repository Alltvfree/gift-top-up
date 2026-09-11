"""Bot request/response schemas."""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Strategy(str, Enum):
    GRID = "GRID"
    DCA = "DCA"


class BotStatus(str, Enum):
    stopped = "stopped"
    running = "running"
    paused = "paused"
    error = "error"


class BotCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    strategy: Strategy
    symbol: str = Field(min_length=1, max_length=20)
    broker_account_id: uuid.UUID | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    ai_preset_used: str | None = None


class BotUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    parameters: dict[str, Any] | None = None


class BotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    strategy: str
    symbol: str
    status: str
    parameters: dict[str, Any]
    ai_preset_used: str | None = None
    total_pnl: float
    created_at: datetime
    started_at: datetime | None = None
    stopped_at: datetime | None = None


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    symbol: str
    side: str
    type: str
    price: float | None = None
    volume: float
    status: str
    created_at: datetime


class PositionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    symbol: str
    side: str
    volume: float
    open_price: float
    current_price: float | None = None
    unrealized_pnl: float
    realized_pnl: float
    opened_at: datetime
    closed_at: datetime | None = None
