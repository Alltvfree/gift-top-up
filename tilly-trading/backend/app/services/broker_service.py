"""Broker account provisioning via MetaAPI.

Given a broker login/password/server, this provisions a MetaAPI account,
deploys it, waits for it to connect, and returns the MetaAPI account id plus
initial account information. The broker password is used only for this call
and is never persisted.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.config import settings


@dataclass
class ProvisionResult:
    metaapi_account_id: str
    balance: float | None
    currency: str | None
    state: str


async def provision_account(
    *,
    name: str,
    login: str,
    password: str,
    server: str,
    platform: str | None = None,
    token: str | None = None,
    region: str | None = None,
) -> ProvisionResult:
    """Provision (or reuse) a MetaAPI account for a broker login."""
    from metaapi_cloud_sdk import MetaApi

    token = token or settings.metaapi_token
    if not token:
        raise RuntimeError("METAAPI_TOKEN is not configured on the server.")
    region = region or settings.metaapi_region_safe
    platform = platform or settings.metaapi_platform

    api = MetaApi(token, {"region": region})

    account = await api.metatrader_account_api.create_account(
        {
            "name": name,
            "type": "cloud-g2",
            "login": str(login),
            "password": password,
            "server": server,
            "platform": platform,
            "magic": 0,
            "region": region,
        }
    )

    await account.deploy()
    await account.wait_connected()

    connection = account.get_rpc_connection()
    await connection.connect()
    await connection.wait_synchronized()

    info: dict[str, Any] = {}
    try:
        info = await connection.get_account_information()
    finally:
        try:
            await connection.close()
        except Exception:  # noqa: BLE001
            pass

    return ProvisionResult(
        metaapi_account_id=account.id,
        balance=float(info["balance"]) if "balance" in info else None,
        currency=info.get("currency"),
        state=getattr(account, "state", "UNKNOWN"),
    )
