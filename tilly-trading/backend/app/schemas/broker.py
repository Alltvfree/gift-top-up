"""Broker account schemas."""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class Platform(str, Enum):
    mt4 = "mt4"
    mt5 = "mt5"


class AccountType(str, Enum):
    demo = "demo"
    live = "live"


class BrokerLinkRequest(BaseModel):
    broker_name: str = Field(min_length=1, max_length=50)  # exness, xm, vantage
    login: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)
    server: str = Field(min_length=1, max_length=120)
    platform: Platform = Platform.mt5
    account_type: AccountType = AccountType.demo


class BridgeLinkRequest(BaseModel):
    """Link a self-hosted MT5 bridge (tilly-trading/mt5-bridge/) the user runs
    themselves, instead of provisioning through MetaAPI."""

    broker_name: str = Field(min_length=1, max_length=50)
    bridge_url: str = Field(min_length=1, max_length=255)
    bridge_api_key: str = Field(min_length=1, max_length=255)
    account_type: AccountType = AccountType.demo


class BrokerAccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    broker_name: str
    account_id: str
    account_type: str
    connection_provider: str
    balance: float | None = None
    currency: str
    is_active: bool
    status: str
    server: str | None = None
    platform: str
    metaapi_account_id: str | None = None
    bridge_url: str | None = None
    # bridge_api_key intentionally omitted — never echoed back by the API,
    # even though the owning user can read it directly from Supabase (RLS).
    last_error: str | None = None
    created_at: datetime
