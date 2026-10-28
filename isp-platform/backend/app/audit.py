from psycopg.types.json import Jsonb

from . import db


def record(actor: str, action: str, target_type: str | None = None, target_id=None, detail: dict | None = None, conn=None):
    sql = "INSERT INTO audit_events(actor,action,target_type,target_id,detail) VALUES (%s,%s,%s,%s,%s)"
    params = (actor, action, target_type, str(target_id) if target_id is not None else None, Jsonb(detail or {}))
    if conn is not None:
        conn.execute(sql, params)
    else:
        db.run(sql, params)
