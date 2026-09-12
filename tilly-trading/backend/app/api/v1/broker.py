"""Broker account linking endpoints (Task 3).

Authenticated with the caller's Supabase access token. Provisions a MetaAPI
account from the supplied broker credentials and stores the resulting MetaAPI
account id in `broker_accounts`. The broker password is used only for
provisioning and is never written to the database.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from sqlalchemy import select

from app.core.deps import DbSession
from app.core.supabase_auth import SupabaseUserId
from app.db.models.broker_account import BrokerAccount
from app.db.session import async_session_factory
from app.schemas.broker import BrokerAccountOut, BrokerLinkRequest
from app.services.broker_service import provision_account

router = APIRouter()


async def _provision_and_update(
    account_id: uuid.UUID, name: str, login: str, password: str, server: str, platform: str
) -> None:
    """Background job: provision via MetaAPI (slow) and update the row."""
    async with async_session_factory() as session:
        account = await session.get(BrokerAccount, account_id)
        if account is None:
            return
        try:
            result = await provision_account(
                name=name, login=login, password=password, server=server, platform=platform
            )
            account.metaapi_account_id = result.metaapi_account_id
            account.balance = result.balance
            if result.currency:
                account.currency = result.currency
            account.status = "connected"
            account.is_active = True
            account.last_error = None
        except Exception as exc:  # noqa: BLE001 - record failure on the row
            account.status = "error"
            account.last_error = str(exc)[:500]
        await session.commit()


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


@router.post("/paper", response_model=BrokerAccountOut, status_code=status.HTTP_201_CREATED)
async def create_paper_account(user_id: SupabaseUserId, db: DbSession) -> BrokerAccount:
    """Create a free simulated (paper-trading) account — no broker, no cost."""
    account = BrokerAccount(
        user_id=user_id,
        broker_name="paper",
        account_id="PAPER",
        account_type="demo",
        connection_provider="simulated",
        balance=10000,
        currency="USD",
        status="connected",
        is_active=True,
    )
    try:
        db.add(account)
        await db.commit()
        await db.refresh(account)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {type(exc).__name__}: {exc}",
        ) from exc
    return account


@router.post("/link", response_model=BrokerAccountOut, status_code=status.HTTP_201_CREATED)
async def link_account(
    payload: BrokerLinkRequest,
    user_id: SupabaseUserId,
    db: DbSession,
    background: BackgroundTasks,
) -> BrokerAccount:
    """Create a pending broker account and provision it in the background.

    MetaAPI provisioning (create + deploy + wait_connected) can take a minute or
    more, so we return immediately with status 'provisioning'; the client polls
    broker_accounts for the final 'connected' / 'error' status.
    """
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
    try:
        db.add(account)
        await db.commit()
        await db.refresh(account)
    except Exception as exc:  # noqa: BLE001 - surface DB errors with CORS headers
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {type(exc).__name__}: {exc}",
        ) from exc

    background.add_task(
        _provision_and_update,
        account.id,
        f"{payload.broker_name}-{payload.login}",
        payload.login,
        payload.password,
        payload.server,
        payload.platform.value,
    )
    return account


@router.delete("/accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unlink_account(account_id: uuid.UUID, user_id: SupabaseUserId, db: DbSession):
    account = await db.get(BrokerAccount, account_id)
    if account is None or account.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found.")
    await db.delete(account)
    await db.commit()
