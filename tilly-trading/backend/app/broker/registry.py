"""Provider registry — pick the broker adapter for a linked account.

The trading engine calls this and never references a specific provider, so new
providers (e.g. SELF_HOSTED MT5) slot in here without touching strategy code.
"""
from __future__ import annotations

from app.broker.base import BrokerClient
from app.broker.metaapi_client import MetaAPIClient
from app.broker.mt5_bridge_client import MT5BridgeClient
from app.broker.simulated import SimulatedBroker
from app.db.models.broker_account import BrokerAccount


def build_broker_for_account(account: BrokerAccount) -> BrokerClient:
    provider = (getattr(account, "connection_provider", None) or "metaapi").lower()

    if provider == "simulated":
        balance = float(account.balance) if account.balance is not None else 10000.0
        return SimulatedBroker(starting_balance=balance)

    if provider == "metaapi":
        if not account.metaapi_account_id:
            raise RuntimeError("MetaAPI account is not provisioned yet.")
        return MetaAPIClient(account_id=account.metaapi_account_id)

    if provider == "self_hosted":
        if not account.bridge_url or not account.bridge_api_key:
            raise RuntimeError("MT5 bridge URL/API key are not configured for this account.")
        return MT5BridgeClient(base_url=account.bridge_url, api_key=account.bridge_api_key)

    raise RuntimeError(f"Unsupported connection provider: {provider!r}")
