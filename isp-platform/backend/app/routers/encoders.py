"""IP video encoder monitoring: dashboard, per-device detail, manual test and restart.

Automatic restart only ever fires from services.encoders.evaluate() during the normal poll, and
only once an admin has configured and verified a restart adapter for that specific device. This
router's /restart is the manual equivalent of that same gate -- see services/encoders.py.
"""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from .. import audit, db
from ..deps import require
from ..services import encoders as enc

router = APIRouter(prefix="/api/encoders", tags=["encoders"])


def _device(device_id) -> dict:
    d = db.row("SELECT * FROM devices WHERE id=%s AND vendor='encoder'", (device_id,))
    if not d:
        raise HTTPException(404, "Video encoder not found")
    return d


@router.get("/overview")
def overview(user=Depends(require("read"))):
    counts = db.row(
        """SELECT count(*) AS total, count(*) FILTER (WHERE status='online') AS online,
                  count(*) FILTER (WHERE status='offline') AS offline,
                  count(*) FILTER (WHERE status='degraded') AS degraded,
                  count(*) FILTER (WHERE (settings->>'auto_recovery')::boolean) AS auto_recovery_on
           FROM devices WHERE vendor='encoder'""")
    incidents = db.row(
        """SELECT count(*) FILTER (WHERE kind='video') AS video_failures,
                  count(*) FILTER (WHERE kind='audio') AS audio_failures
           FROM encoder_incidents WHERE closed_at IS NULL""")
    recoveries_today = db.row(
        """SELECT count(*) AS n FROM encoder_incidents
           WHERE recovery_at > date_trunc('day', now()) AND recovery_action IS NOT NULL""")["n"]
    return {**counts, **incidents, "recoveries_today": recoveries_today}


@router.get("")
def list_encoders(user=Depends(require("read"))):
    return db.rows(
        """SELECT d.id,d.name,d.island_id,i.name AS island_name,d.status,d.last_seen_at,d.last_poll_error,
                  d.settings,d.parent_device_id,p.name AS parent_name,
                  EXISTS(SELECT 1 FROM encoder_incidents e WHERE e.device_id=d.id AND e.kind='video' AND e.closed_at IS NULL) AS video_failing,
                  EXISTS(SELECT 1 FROM encoder_incidents e WHERE e.device_id=d.id AND e.kind='audio' AND e.closed_at IS NULL) AS audio_failing
           FROM devices d LEFT JOIN islands i ON i.id=d.island_id LEFT JOIN devices p ON p.id=d.parent_device_id
           WHERE d.vendor='encoder' ORDER BY i.name NULLS FIRST, d.name""")


@router.get("/{device_id}")
def get_encoder(device_id: UUID, user=Depends(require("read"))):
    d = _device(device_id)
    d["recent_checks"] = db.rows(
        "SELECT at,reachable,latency_ms,extra->'encoder' AS encoder FROM device_metrics WHERE device_id=%s ORDER BY at DESC LIMIT 50",
        (device_id,))
    d["incidents"] = db.rows("SELECT * FROM encoder_incidents WHERE device_id=%s ORDER BY opened_at DESC LIMIT 50", (device_id,))
    return d


@router.get("/{device_id}/incidents")
def incidents(device_id: UUID, user=Depends(require("read"))):
    _device(device_id)
    return db.rows("SELECT * FROM encoder_incidents WHERE device_id=%s ORDER BY opened_at DESC LIMIT 200", (device_id,))


@router.post("/{device_id}/test")
def test(device_id: UUID, user=Depends(require("network"))):
    """Run the video+audio checks right now and update incidents accordingly (same logic as a poll)."""
    d = _device(device_id)
    try:
        result = enc.check(d)
    except Exception as exc:
        raise HTTPException(502, f"{type(exc).__name__}: {exc}"[:300]) from exc
    with db.connect() as conn:
        conn.execute("INSERT INTO device_metrics(device_id,reachable,extra) VALUES (%s,true,%s)",
                     (device_id, Jsonb({"encoder": result})))
        enc.evaluate(conn, d, result)
        audit.record(user["username"], "encoder.test", "device", device_id, result, conn=conn)
    return result


class RestartIn(BaseModel):
    confirm: bool = Field(default=False)


@router.post("/{device_id}/restart")
def restart(device_id: UUID, body: RestartIn, user=Depends(require("network"))):
    if not body.confirm:
        raise HTTPException(400, "Pass confirm: true to actually restart this encoder")
    d = _device(device_id)
    with db.connect() as conn:
        try:
            result = enc.manual_restart(conn, d, user["username"])
        except enc.RestartNotConfigured as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(502, f"{type(exc).__name__}: {exc}"[:300]) from exc
    return result


class RecoveryIn(BaseModel):
    auto_recovery: bool


@router.put("/{device_id}/recovery")
def set_recovery(device_id: UUID, body: RecoveryIn, user=Depends(require("network"))):
    d = _device(device_id)
    with db.connect() as conn:
        settings = {**(d["settings"] or {}), "auto_recovery": body.auto_recovery}
        conn.execute("UPDATE devices SET settings=%s WHERE id=%s", (Jsonb(settings), device_id))
        audit.record(user["username"], "encoder.recovery_toggle", "device", device_id, {"auto_recovery": body.auto_recovery}, conn=conn)
    return {"ok": True}
