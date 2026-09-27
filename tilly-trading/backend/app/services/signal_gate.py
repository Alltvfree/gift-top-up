"""Optional entry gate: let a bot require an external model's (Kronos's)
agreement before opening a new position.

Strictly opt-in — a bot only calls this when its own `require_signal`
parameter is set. Every existing bot with that parameter unset keeps
behaving exactly as it did before this file existed; nothing here runs
unless a bot asks for it.

This is *whether to open*, not *what to trade*: bots keep their own
mechanical logic (GRID's ladder spacing, DCA's martingale sizing) — this
only says yes/no to the timing of a specific entry, matching the project's
own design notes: "AI should NOT directly control unlimited trading risk
... the risk engine should have authority to reject an AI signal."
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.signal import Signal

DEFAULT_MAX_AGE_MINUTES = 30


async def signal_allows(
    session: AsyncSession,
    symbol: str,
    side: str | None = None,
    max_age_minutes: int = DEFAULT_MAX_AGE_MINUTES,
) -> tuple[bool, str]:
    """Should a bot open a `side` position in `symbol` right now?

    side=None: any directional signal (BUY or SELL) counts as allowed —
    only NO_TRADE (or no signal at all, or a stale one) blocks. This is
    the right check for a non-directional strategy like GRID, which trades
    both sides at once and just wants "is this a live, tradeable moment"
    from Kronos rather than a specific direction.

    side="BUY"/"SELL": the latest signal must match that exact side. This
    is the right check for a directional strategy like DCA.

    Returns (allowed, reason) — `reason` is always populated (even when
    allowed) so callers can log/surface *why*, not just the yes/no.
    """
    stmt = select(Signal).where(Signal.symbol == symbol).order_by(Signal.created_at.desc()).limit(1)
    row = (await session.scalars(stmt)).first()

    if row is None:
        return False, f"No signal has been published yet for {symbol}."

    created_at = row.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - created_at
    if age > timedelta(minutes=max_age_minutes):
        return False, (
            f"Latest {symbol} signal is {int(age.total_seconds() // 60)}m old "
            f"(source={row.source}) — older than the {max_age_minutes}m freshness limit, treated as stale."
        )

    if row.side == "NO_TRADE":
        return False, f"Latest {symbol} signal is NO_TRADE (confidence {row.confidence}%)."

    if side is not None and row.side != side.upper():
        return False, f"Latest {symbol} signal is {row.side}, this entry wants {side.upper()}."

    return True, f"Signal OK: {row.side} at {row.confidence}% confidence ({row.timeframe}, {row.source})."
