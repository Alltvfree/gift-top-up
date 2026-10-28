from fastapi import APIRouter, Depends, HTTPException

from .. import audit, db
from ..deps import require

router = APIRouter(prefix="/api", tags=["monitoring"])


@router.get("/summary")
def summary(user=Depends(require("read"))):
    return db.row(
        """SELECT
           (SELECT json_build_object('total',count(*),'online',count(*) FILTER (WHERE status='online'),
                   'degraded',count(*) FILTER (WHERE status='degraded'),'offline',count(*) FILTER (WHERE status='offline')) FROM islands) AS islands,
           (SELECT json_build_object('total',count(*),'online',count(*) FILTER (WHERE status='online'),
                   'offline',count(*) FILTER (WHERE status='offline')) FROM devices WHERE poll_enabled) AS devices,
           (SELECT json_build_object('total',count(*),'active',count(*) FILTER (WHERE status='active'),
                   'suspended',count(*) FILTER (WHERE status='suspended'),'pending',count(*) FILTER (WHERE status='pending')) FROM subscribers) AS subscribers,
           (SELECT count(*) FROM radacct WHERE acctstoptime IS NULL) AS online_sessions,
           (SELECT json_build_object('critical',count(*) FILTER (WHERE severity='critical'),'warning',count(*) FILTER (WHERE severity='warning'))
              FROM alerts WHERE resolved_at IS NULL) AS alerts,
           (SELECT coalesce(sum(amount_mvr-paid_mvr),0) FROM invoices WHERE status IN ('unpaid','overdue')) AS receivable_mvr,
           (SELECT count(*) FROM config_changes WHERE status='pending') AS pending_changes,
           (SELECT count(*) FROM radpostauth WHERE reply<>'Access-Accept' AND authdate>now()-interval '1 hour') AS auth_rejects_1h""")


@router.get("/alerts")
def alerts(open_only: bool = True, user=Depends(require("read"))):
    return db.rows(
        f"""SELECT a.*, d.name AS device_name, i.name AS island_name FROM alerts a
            LEFT JOIN devices d ON d.id=a.device_id LEFT JOIN islands i ON i.id=a.island_id
            {'WHERE a.resolved_at IS NULL' if open_only else ''}
            ORDER BY (a.severity='critical') DESC, a.opened_at DESC LIMIT 500""")


@router.post("/alerts/{alert_id}/ack")
def ack(alert_id: int, user=Depends(require("network"))):
    with db.connect() as conn:
        if not conn.execute("UPDATE alerts SET acknowledged_by=%s WHERE id=%s RETURNING id", (user["username"], alert_id)).fetchone():
            raise HTTPException(404, "Alert not found")
        audit.record(user["username"], "alert.ack", "alert", alert_id, conn=conn)
    return {"ok": True}


@router.get("/audit")
def audit_log(user=Depends(require("approve"))):
    return db.rows("SELECT * FROM audit_events ORDER BY created_at DESC LIMIT 500")
