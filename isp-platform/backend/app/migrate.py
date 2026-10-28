"""Apply database/migrations/*.sql in order, once each. Safe to run on every start."""
import os

import psycopg
from psycopg import sql

from . import config


def migrate(database_url=None):
    applied = []
    with psycopg.connect(database_url or config.DATABASE_URL, autocommit=True) as conn:
        conn.execute("SELECT pg_advisory_lock(727001)")
        try:
            conn.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
            conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY, applied_at TIMESTAMPTZ DEFAULT now())")
            done = {r[0] for r in conn.execute("SELECT name FROM schema_migrations")}
            for path in sorted(config.MIGRATIONS_DIR.glob("*.sql")):
                if path.name in done:
                    continue
                with conn.transaction():
                    conn.execute(path.read_text())
                    conn.execute("INSERT INTO schema_migrations(name) VALUES (%s)", (path.name,))
                applied.append(path.name)
            if os.environ.get("RADIUS_DB_PASSWORD"):
                conn.execute(sql.SQL("ALTER ROLE radius WITH LOGIN PASSWORD {}").format(sql.Literal(os.environ["RADIUS_DB_PASSWORD"])))
        finally:
            conn.execute("SELECT pg_advisory_unlock(727001)")
    return applied


if __name__ == "__main__":
    print("applied:", migrate() or "nothing new")
