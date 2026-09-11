"""Quick connectivity check for the configured database.

Run from the backend directory (with your .env in place):

    python scripts/check_db.py

Prints a clear PASS/FAIL and a hint if it can't connect — useful for
verifying your Supabase connection string before starting the app.
"""
from __future__ import annotations

import asyncio
import sys

from sqlalchemy import text

# Import the app's engine so this uses the exact same settings/.env.
from app.core.config import settings
from app.db.session import engine


async def main() -> int:
    # Mask the password when echoing the target.
    url = settings.database_url
    safe = url
    if "@" in url and ":" in url.split("@")[0]:
        prefix, rest = url.split("@", 1)
        scheme_user = prefix.rsplit(":", 1)[0]
        safe = f"{scheme_user}:***@{rest}"
    print(f"Connecting to: {safe}")

    try:
        async with engine.connect() as conn:
            who = await conn.scalar(text("select current_user"))
            n = await conn.scalar(text("select count(*) from ai_presets"))
        print(f"PASS ✅  connected as '{who}' — ai_presets has {n} rows.")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL ❌  {type(exc).__name__}: {exc}")
        print(
            "\nHints:\n"
            "  • 'Tenant or user not found' / timeout on the pooler → the host is\n"
            "    the other cluster: switch aws-0 ↔ aws-1 in DATABASE_URL (see .env).\n"
            "  • 'password authentication failed' → wrong DB password.\n"
            "  • 'Network is unreachable' on the direct host → your network is IPv4-only;\n"
            "    use the Session pooler URL (default in .env).\n"
        )
        return 1
    finally:
        await engine.dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
