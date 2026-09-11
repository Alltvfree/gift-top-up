"""Broker account linking endpoints (Task 3).

Authenticated with the caller's Supabase access token. Provisions a MetaAPI
account from the supplied broker credentials and stores the resulting MetaAPI
account id in `broker_accounts`. The broker password is used only for
provisioning and is never written to the database.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.core.deps import DbSession
from app.core.supabase_auth import SupabaseUserId
from app.db.models.broker_account import BrokerAccount
from app.schemas.broker import BrokerAccountOut, BrokerLinkRequest
from app.services.broker_service import provision_account

router = APIRouter()


@router.post("/ping")
async def ping(user_id: SupabaseUserId) -> dict:
    """Fast authenticated POST — isolates CORS/preflight+auth from provisioning."""
    return {"ok": True, "user_id": str(user_id)}


@router.get("/accounts", response_model=list[BrokerAccountOut])
async def list_accounts(user_id: SupabaseUserId, db: DbSession) -> list[BrokerAccount]:
    result = await db.scalars(
        select(BrokerAccount)
        .where(BrokerAccount.user_id == user_id)
        .order_by(BrokerAccount.created_at.desc())
    )
    return list(result.all())


@router.post("/link", response_model=BrokerAccountOut, status_code=status.HTTP_201_CREATED)
async def link_account(
    payload: BrokerLinkRequest, user_id: SupabaseUserId, db: DbSession
) -> BrokerAccount:
    # Persist a pending row first so the attempt is visible even if provisioning
    # fails midway.
    account = BrokerAccount(
        user_id=user_id,
        broker_name=payload.broker_name.lower(),
        account_id=payload.login,
        account_type=payload.account_type.value,
        server=payload.server,
        platform=payload.platform.value,
        status="provisioning",
        is_active=False,
    )
    db.add(account)
    await db.commit()
    await db.refresh(account)

    try:
        result = await provision_account(
            name=f"{payload.broker_name}-{payload.login}",
            login=payload.login,
            password=payload.password,
            server=payload.server,
            platform=payload.platform.value,
        )
    except Exception as exc:  # noqa: BLE001 - surface provisioning failures to the user
        account.status = "error"
        account.last_error = str(exc)[:500]
        await db.commit()
        await db.refresh(account)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Broker provisioning failed: {exc}",
        ) from exc

    account.metaapi_account_id = result.metaapi_account_id
    account.balance = result.balance
    if result.currency:
        account.currency = result.currency
    account.status = "connected"
    account.is_active = True
    account.last_error = None
    await db.commit()
    await db.refresh(account)
    return account


@router.delete("/accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unlink_account(account_id: uuid.UUID, user_id: SupabaseUserId, db: DbSession):
    account = await db.get(BrokerAccount, account_id)
    if account is None or account.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found.")
    await db.delete(account)
    await db.commit()
