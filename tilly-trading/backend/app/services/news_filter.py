"""Optional entry gate: pause new positions around high-impact economic
news events (FOMC, NFP, CPI, etc.) — a well-established risk-management
technique, distinct from having anything (AI or otherwise) generate a
signal from news commentary. This only ever says "not right now", never
"buy" or "sell" — no different in kind from a spread or volatility filter.

Strictly opt-in via a bot's own `avoid_news_minutes` parameter, same as
signal_gate.py's `require_signal`. Reads from the `news_events` table
(tilly-trading/supabase/migrations/0008_news_events.sql), which currently
has no automatic feed populating it — rows are inserted manually (or by a
future script) using Supabase's service_role key. This file only reads.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.news_event import NewsEvent

# Real, tradeable currency codes we can recognize inside a symbol name —
# deliberately simple substring matching (XAUUSD contains "USD", EURUSD
# contains both "EUR" and "USD") rather than a full symbol/currency
# mapping table. Good enough to know which economic events are relevant;
# revisit if a symbol's naming makes this ambiguous.
KNOWN_CURRENCIES = ("USD", "EUR", "GBP", "JPY", "AUD", "CAD", "CHF", "NZD")

_IMPACT_RANK = {"low": 0, "medium": 1, "high": 2}


def relevant_currencies(symbol: str) -> set[str]:
    upper = symbol.upper()
    return {c for c in KNOWN_CURRENCIES if c in upper}


async def is_near_high_impact_news(
    session: AsyncSession,
    symbol: str,
    buffer_minutes: int,
    min_impact: str = "high",
    now: datetime | None = None,
) -> tuple[bool, str]:
    """Should a bot avoid opening a new position in `symbol` right now?

    Returns (blocked, reason). Checks every news_events row whose
    event_time falls within `buffer_minutes` before or after `now`
    (defaults to the real current time), matching on currency — a row with
    currency="ALL" always applies, others apply only if they overlap
    `relevant_currencies(symbol)`. The first matching event at or above
    `min_impact` blocks; an empty news_events table (the default until
    someone populates it) never blocks anything.
    """
    now = now or datetime.now(timezone.utc)
    currencies = relevant_currencies(symbol)
    min_rank = _IMPACT_RANK.get(min_impact, 2)

    window_start = now - timedelta(minutes=buffer_minutes)
    window_end = now + timedelta(minutes=buffer_minutes)
    stmt = select(NewsEvent).where(
        NewsEvent.event_time >= window_start, NewsEvent.event_time <= window_end
    )
    rows = (await session.scalars(stmt)).all()

    for row in rows:
        if _IMPACT_RANK.get(row.impact, 0) < min_rank:
            continue
        if row.currency != "ALL" and row.currency not in currencies:
            continue
        event_time = row.event_time
        if event_time.tzinfo is None:
            event_time = event_time.replace(tzinfo=timezone.utc)
        minutes_away = (event_time - now).total_seconds() / 60
        when = f"in {minutes_away:.0f}m" if minutes_away >= 0 else f"{-minutes_away:.0f}m ago"
        return True, (
            f"{row.event_name} ({row.currency}, {row.impact} impact) is {when} — "
            f"within the {buffer_minutes}m no-trade window."
        )

    return False, "No high-impact news within the buffer window."
