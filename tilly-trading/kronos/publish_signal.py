"""Writes one row per prediction to Supabase's `signals` table.

That table is what Tilly's frontend Signals page reads from (replacing its
placeholder mock data), and — once a bot opts into checking it — what the
trading engine can use as an entry filter. See
tilly-trading/supabase/migrations/0007_signals.sql for the schema and RLS.

Needs the project's SERVICE ROLE key, not the anon/publishable key the
Tilly frontend uses: the signals table's RLS policy only allows SELECT for
anon/authenticated, no INSERT — only service_role bypasses RLS. Get it from
Supabase dashboard -> Project Settings -> API -> service_role secret.

Keep SUPABASE_SERVICE_ROLE_KEY on this machine only. Never put it in the
Tilly frontend or backend, never commit it — it has full read/write access
to every table in the project, bypassing every RLS policy.
"""
from __future__ import annotations

import os

from supabase import Client, create_client

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

_client: Client | None = None


def _get_client() -> Client:
    global _client
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError(
            "Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY before publishing signals."
        )
    if _client is None:
        _client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
    return _client


def publish_signal(
    *,
    symbol: str,
    side: str,
    confidence: float,
    timeframe: str,
    tp: float | None = None,
    sl: float | None = None,
    expected_move: float | None = None,
    note: str = "",
) -> None:
    """side: "BUY" | "SELL" | "NO_TRADE". confidence: 0-100."""
    if side.upper() not in ("BUY", "SELL", "NO_TRADE"):
        raise ValueError(f"side must be BUY, SELL, or NO_TRADE, got {side!r}")
    _get_client().table("signals").insert(
        {
            "symbol": symbol,
            "side": side.upper(),
            "confidence": confidence,
            "timeframe": timeframe,
            "tp": tp,
            "sl": sl,
            "expected_move": expected_move,
            "note": note,
            "source": "kronos",
        }
    ).execute()
