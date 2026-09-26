"""Broker account linking endpoints (Task 3).

Authenticated with the caller's Supabase access token. Provisions a MetaAPI
account from the supplied broker credentials and stores the resulting MetaAPI
account id in `broker_accounts`. The broker password is used only for
provisioning and is never written to the database.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from sqlalchemy import select

from app.broker.mt5_bridge_client import MT5BridgeClient, MT5BridgeError
from app.broker.registry import build_broker_for_account
from app.core.deps import DbSession
from app.core.supabase_auth import SupabaseUserId
from app.db.models.bot import Bot
from app.db.models.broker_account import BrokerAccount
from app.db.models.position import Position
from app.db.session import async_session_factory
from app.schemas.broker import BridgeLinkRequest, BrokerAccountOut, BrokerLinkRequest
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


@router.post("/mt5-bridge", response_model=BrokerAccountOut, status_code=status.HTTP_201_CREATED)
async def link_mt5_bridge(
    payload: BridgeLinkRequest, user_id: SupabaseUserId, db: DbSession
) -> BrokerAccount:
    """Link a self-hosted MT5 bridge (see tilly-trading/mt5-bridge/).

    Unlike MetaAPI provisioning this is a single fast HTTP round trip to a
    service the user already has running, so we verify it synchronously
    instead of a background task + polling.
    """
    client = MT5BridgeClient(base_url=payload.bridge_url, api_key=payload.bridge_api_key)
    try:
        await client.connect()
        info = await client.get_account_information()
    except MT5BridgeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - unreachable bridge, bad URL, etc.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not reach the MT5 bridge at {payload.bridge_url}: {exc}",
        ) from exc
    finally:
        await client.close()

    account = BrokerAccount(
        user_id=user_id,
        broker_name=payload.broker_name.lower(),
        account_id=payload.bridge_url,
        account_type=payload.account_type.value,
        connection_provider="self_hosted",
        bridge_url=payload.bridge_url,
        bridge_api_key=payload.bridge_api_key,
        balance=info.get("balance"),
        currency=info.get("currency", "USD"),
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


@router.get("/accounts/{account_id}/candles")
async def account_candles(
    account_id: uuid.UUID,
    user_id: SupabaseUserId,
    db: DbSession,
    symbol: str,
    timeframe: str = "1m",
    limit: int = 200,
) -> dict:
    """Real OHLC history from this account's own connection, for the price
    chart — currently only the MT5 bridge implements get_candles(); other
    providers raise NotImplementedError, surfaced here as 501 so the
    frontend can fall back to a public feed or the simulated chart rather
    than treat it as a hard failure."""
    account = await db.get(BrokerAccount, account_id)
    if account is None or account.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found.")

    try:
        broker = build_broker_for_account(account)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    try:
        await broker.connect()
        bars = await broker.get_candles(symbol, timeframe, min(max(limit, 1), 1000))
    except NotImplementedError as exc:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - bridge unreachable, symbol unknown, etc.
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    finally:
        try:
            await broker.close()
        except Exception:  # noqa: BLE001
            pass

    return {
        "symbol": symbol.upper(),
        "timeframe": timeframe,
        "source": account.connection_provider,
        "bars": bars,
    }


@router.get("/accounts/{account_id}/symbols")
async def account_symbols(account_id: uuid.UUID, user_id: SupabaseUserId, db: DbSession) -> dict:
    """This account's real broker-side symbol names, for the New Bot wizard
    to offer a picker instead of the user guessing a broker's exact naming
    (XAUUSD vs XAUUSDm etc.). Same NotImplementedError -> 501 pattern as
    candles: providers without a real symbol list just aren't offered here,
    the wizard falls back to its fixed default list."""
    account = await db.get(BrokerAccount, account_id)
    if account is None or account.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found.")

    try:
        broker = build_broker_for_account(account)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    try:
        await broker.connect()
        symbols = await broker.get_symbols()
    except NotImplementedError as exc:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - bridge unreachable, etc.
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    finally:
        try:
            await broker.close()
        except Exception:  # noqa: BLE001
            pass

    return {"symbols": symbols}


@router.post("/positions/{position_id}/close")
async def close_position(position_id: uuid.UUID, user_id: SupabaseUserId, db: DbSession) -> dict:
    """Manually close one open position — the safety valve that was missing
    when GRID positions had no way to close at all (fixed separately in
    grid_bot.py, but a manual close button should exist regardless)."""
    position = await db.get(Position, position_id)
    if position is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Position not found.")

    bot = await db.get(Bot, position.bot_id)
    if bot is None or bot.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Position not found.")
    if position.closed_at is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Position already closed.")
    if not bot.broker_account_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Bot has no broker account.")

    account = await db.get(BrokerAccount, bot.broker_account_id)
    if account is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Broker account not found.")

    try:
        broker = build_broker_for_account(account)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    try:
        await broker.connect()
        await broker.close_position(position.broker_position_id or "")
    except Exception as exc:  # noqa: BLE001 - broker/bridge failure
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    finally:
        try:
            await broker.close()
        except Exception:  # noqa: BLE001
            pass

    # Reflect the close immediately rather than waiting for the next engine
    # tick to reconcile it — realized_pnl is the last-known unrealized figure,
    # same same-tick-approximation caveat as the engine's own sync (see
    # services/engine.py::_sync_positions).
    position.closed_at = datetime.now(timezone.utc)
    position.realized_pnl = position.unrealized_pnl
    await db.commit()
    return {"ok": True}


@router.delete("/accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unlink_account(account_id: uuid.UUID, user_id: SupabaseUserId, db: DbSession):
    account = await db.get(BrokerAccount, account_id)
    if account is None or account.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found.")
    await db.delete(account)
    await db.commit()
