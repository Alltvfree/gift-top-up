from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import audit, config, db
from ..deps import require
from ..services import changes

router = APIRouter(prefix="/api/changes", tags=["changes"])


class ChangeIn(BaseModel):
    device_id: UUID
    title: str = Field(min_length=3, max_length=160)
    kind: Literal["mikrotik_script", "huawei_cli"]
    plan: str = Field(min_length=1, max_length=200000)
    rollback: str | None = Field(default=None, max_length=200000)


def create_change(conn, device_id, title, kind, plan, rollback, username) -> int:
    d = conn.execute("SELECT vendor FROM devices WHERE id=%s", (device_id,)).fetchone()
    if not d:
        raise HTTPException(404, "Device not found")
    if (kind == "mikrotik_script") != (d["vendor"] == "mikrotik") or (kind == "huawei_cli" and d["vendor"] != "huawei"):
        raise HTTPException(400, f"A {kind} change cannot target a {d['vendor']} device")
    row = conn.execute(
        "INSERT INTO config_changes(device_id,title,kind,plan,rollback,requested_by) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
        (device_id, title, kind, plan, rollback, username)).fetchone()
    audit.record(username, "change.request", "config_change", row["id"], {"title": title}, conn=conn)
    return row["id"]


@router.get("")
def list_changes(user=Depends(require("network"))):
    return db.rows("""SELECT c.id,c.title,c.kind,c.status,c.requested_by,c.approved_by,c.created_at,c.applied_at,d.name AS device_name
                      FROM config_changes c JOIN devices d ON d.id=c.device_id ORDER BY c.created_at DESC LIMIT 300""")


@router.get("/{change_id}")
def get_change(change_id: int, user=Depends(require("network"))):
    row = db.row("SELECT c.*, d.name AS device_name FROM config_changes c JOIN devices d ON d.id=c.device_id WHERE c.id=%s", (change_id,))
    if not row:
        raise HTTPException(404, "Change not found")
    return row


@router.post("", status_code=201)
def request_change(body: ChangeIn, user=Depends(require("network"))):
    with db.connect() as conn:
        return {"id": create_change(conn, body.device_id, body.title, body.kind, body.plan, body.rollback, user["username"])}


@router.post("/{change_id}/approve")
def approve(change_id: int, user=Depends(require("approve"))):
    with db.connect() as conn:
        ch = conn.execute("SELECT * FROM config_changes WHERE id=%s FOR UPDATE", (change_id,)).fetchone()
        if not ch or ch["status"] != "pending":
            raise HTTPException(409, "Only pending changes can be approved")
        if config.FOUR_EYES and ch["requested_by"] == user["username"]:
            raise HTTPException(403, "Four-eyes rule: someone else must approve your change")
        conn.execute("UPDATE config_changes SET status='approved', approved_by=%s WHERE id=%s", (user["username"], change_id))
        audit.record(user["username"], "change.approve", "config_change", change_id, conn=conn)
    return {"ok": True}


@router.post("/{change_id}/reject")
def reject(change_id: int, user=Depends(require("approve"))):
    with db.connect() as conn:
        if not conn.execute("UPDATE config_changes SET status='rejected', approved_by=%s WHERE id=%s AND status IN ('pending','approved') RETURNING id",
                            (user["username"], change_id)).fetchone():
            raise HTTPException(409, "Change cannot be rejected now")
        audit.record(user["username"], "change.reject", "config_change", change_id, conn=conn)
    return {"ok": True}


@router.post("/{change_id}/apply")
def apply(change_id: int, user=Depends(require("network"))):
    result = changes.apply(change_id, user["username"])
    if not result["ok"] and "status" not in result:
        raise HTTPException(409, result["detail"])
    return result
