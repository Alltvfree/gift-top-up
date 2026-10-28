from ipaddress import IPv4Address
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import audit, db
from ..deps import require
from ..security import generate_pppoe_password
from ..services import radius_sync

router = APIRouter(prefix="/api", tags=["subscribers"])
USERNAME = r"^[a-z0-9._@-]{3,64}$"


class SubscriberIn(BaseModel):
    full_name: str = Field(min_length=1, max_length=120)
    phone: str | None = Field(default=None, max_length=30)
    address: str | None = Field(default=None, max_length=200)
    island_id: UUID | None = None
    plan_id: UUID | None = None
    pppoe_username: str = Field(pattern=USERNAME)
    static_ip: IPv4Address | None = None


class StatusChange(BaseModel):
    status: Literal["active", "suspended", "cancelled", "pending"]
    reason: str | None = Field(default=None, max_length=200)


@router.get("/subscribers")
def subscribers(q: str | None = None, status: str | None = None, island_id: UUID | None = None,
                limit: int = 200, offset: int = 0, user=Depends(require("read"))):
    where, params = ["true"], []
    if q:
        where.append("(s.full_name ILIKE %s OR s.account_number ILIKE %s OR s.pppoe_username ILIKE %s OR s.phone ILIKE %s)")
        params += [f"%{q}%"] * 4
    if status:
        where.append("s.status=%s")
        params.append(status)
    if island_id:
        where.append("s.island_id=%s")
        params.append(island_id)
    params += [min(limit, 1000), offset]
    return db.rows(
        f"""SELECT s.id,s.account_number,s.full_name,s.phone,s.address,s.pppoe_username,s.status,s.suspended_reason,
                   host(s.static_ip) AS static_ip,s.island_id,s.plan_id,i.name AS island_name,p.name AS plan_name,
                   (SELECT coalesce(sum(amount_mvr-paid_mvr),0) FROM invoices v WHERE v.subscriber_id=s.id AND v.status IN ('unpaid','overdue')) AS balance_mvr,
                   EXISTS(SELECT 1 FROM radacct a WHERE a.username=s.pppoe_username AND a.acctstoptime IS NULL) AS online
            FROM subscribers s LEFT JOIN islands i ON i.id=s.island_id LEFT JOIN service_plans p ON p.id=s.plan_id
            WHERE {' AND '.join(where)} ORDER BY s.created_at DESC LIMIT %s OFFSET %s""", params)


@router.get("/subscribers/{sub_id}")
def subscriber(sub_id: UUID, user=Depends(require("read"))):
    s = db.row("SELECT *, host(static_ip) AS static_ip FROM subscribers WHERE id=%s", (sub_id,))
    if not s:
        raise HTTPException(404, "Subscriber not found")
    s["invoices"] = db.rows("SELECT * FROM invoices WHERE subscriber_id=%s ORDER BY created_at DESC LIMIT 24", (sub_id,))
    s["payments"] = db.rows("SELECT * FROM payments WHERE subscriber_id=%s ORDER BY received_at DESC LIMIT 24", (sub_id,))
    s["sessions"] = db.rows(
        """SELECT acctsessionid,host(nasipaddress) AS nas,host(framedipaddress) AS ip,callingstationid AS mac,acctstarttime,acctstoptime,
                  acctinputoctets,acctoutputoctets,acctterminatecause FROM radacct WHERE username=%s ORDER BY acctstarttime DESC LIMIT 20""",
        (s["pppoe_username"],))
    s["auth_log"] = db.rows("SELECT reply,authdate,callingstationid FROM radpostauth WHERE username=%s ORDER BY authdate DESC LIMIT 20",
                            (s["pppoe_username"],))
    s["radius_group"] = db.rows("SELECT groupname FROM radusergroup WHERE username=%s", (s["pppoe_username"],))
    s["onts"] = db.rows("SELECT * FROM onts WHERE subscriber_id=%s", (sub_id,))
    return s


@router.post("/subscribers", status_code=201)
def create_subscriber(body: SubscriberIn, user=Depends(require("subscribers"))):
    password = generate_pppoe_password()
    with db.connect() as conn:
        if conn.execute("SELECT 1 FROM subscribers WHERE pppoe_username=%s", (body.pppoe_username,)).fetchone():
            raise HTTPException(409, "PPPoE username already in use")
        sub = conn.execute(
            """INSERT INTO subscribers(account_number,full_name,phone,address,island_id,plan_id,pppoe_username,static_ip,status)
               VALUES ('A'||nextval('account_number_seq'),%s,%s,%s,%s,%s,%s,%s,'pending') RETURNING *""",
            (body.full_name, body.phone, body.address, body.island_id, body.plan_id, body.pppoe_username,
             str(body.static_ip) if body.static_ip else None),
        ).fetchone()
        radius_sync.sync_subscriber(conn, sub, password=password)
        audit.record(user["username"], "subscriber.create", "subscriber", sub["id"], body.model_dump(mode="json"), conn=conn)
    # The password is shown once (needed for the ONT PPPoE config) and lives only in radcheck.
    return {"id": sub["id"], "account_number": sub["account_number"], "pppoe_password": password}


@router.put("/subscribers/{sub_id}")
def update_subscriber(sub_id: UUID, body: SubscriberIn, user=Depends(require("subscribers"))):
    with db.connect() as conn:
        old = conn.execute("SELECT * FROM subscribers WHERE id=%s FOR UPDATE", (sub_id,)).fetchone()
        if not old:
            raise HTTPException(404, "Subscriber not found")
        if body.pppoe_username != old["pppoe_username"] and conn.execute(
                "SELECT 1 FROM subscribers WHERE pppoe_username=%s", (body.pppoe_username,)).fetchone():
            raise HTTPException(409, "PPPoE username already in use")
        password = None
        if body.pppoe_username != old["pppoe_username"]:
            row = conn.execute("SELECT value FROM radcheck WHERE username=%s AND attribute='Cleartext-Password'",
                               (old["pppoe_username"],)).fetchone()
            password = row["value"] if row else None
        sub = conn.execute(
            """UPDATE subscribers SET full_name=%s,phone=%s,address=%s,island_id=%s,plan_id=%s,pppoe_username=%s,static_ip=%s
               WHERE id=%s RETURNING *""",
            (body.full_name, body.phone, body.address, body.island_id, body.plan_id, body.pppoe_username,
             str(body.static_ip) if body.static_ip else None, sub_id)).fetchone()
        radius_sync.sync_subscriber(conn, sub, password=password, old_username=old["pppoe_username"])
        audit.record(user["username"], "subscriber.update", "subscriber", sub_id, body.model_dump(mode="json"), conn=conn)
        changed_service = old["plan_id"] != sub["plan_id"] or old["static_ip"] != sub["static_ip"] or password is not None
    result = {"ok": True}
    if changed_service:
        with db.connect() as conn:
            result["disconnect"] = radius_sync.disconnect(conn, old["pppoe_username"])
    return result


@router.post("/subscribers/{sub_id}/status")
def set_status(sub_id: UUID, body: StatusChange, user=Depends(require("subscribers"))):
    with db.connect() as conn:
        sub = conn.execute(
            "UPDATE subscribers SET status=%s, suspended_reason=%s WHERE id=%s RETURNING *",
            (body.status, (body.reason or "manual") if body.status == "suspended" else None, sub_id)).fetchone()
        if not sub:
            raise HTTPException(404, "Subscriber not found")
        if body.status == "active" and not sub["plan_id"]:
            raise HTTPException(400, "Assign a plan before activating")
        radius_sync.sync_subscriber(conn, sub)
        audit.record(user["username"], f"subscriber.{body.status}", "subscriber", sub_id, {"reason": body.reason}, conn=conn)
    with db.connect() as conn:
        return {"ok": True, "disconnect": radius_sync.disconnect(conn, sub["pppoe_username"])}


@router.post("/subscribers/{sub_id}/reset-password")
def reset_password(sub_id: UUID, user=Depends(require("subscribers"))):
    password = generate_pppoe_password()
    with db.connect() as conn:
        sub = conn.execute("SELECT * FROM subscribers WHERE id=%s", (sub_id,)).fetchone()
        if not sub:
            raise HTTPException(404, "Subscriber not found")
        radius_sync.sync_subscriber(conn, sub, password=password)
        audit.record(user["username"], "subscriber.reset_password", "subscriber", sub_id, conn=conn)
    return {"pppoe_password": password}


@router.post("/subscribers/{sub_id}/disconnect")
def disconnect(sub_id: UUID, user=Depends(require("subscribers"))):
    sub = db.row("SELECT pppoe_username FROM subscribers WHERE id=%s", (sub_id,))
    if not sub:
        raise HTTPException(404, "Subscriber not found")
    audit.record(user["username"], "subscriber.disconnect", "subscriber", sub_id)
    with db.connect() as conn:
        return {"results": radius_sync.disconnect(conn, sub["pppoe_username"])}
