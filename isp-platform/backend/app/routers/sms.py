from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import audit, config, db
from ..adapters.msgowl import MessageOwl, SmsError, normalize_phone
from ..deps import require
from ..services import sms

router = APIRouter(prefix="/api/sms", tags=["sms"])


@router.get("/status")
def status(user=Depends(require("read"))):
    counts = db.row("""SELECT count(*) FILTER (WHERE status='queued') AS queued,
                              count(*) FILTER (WHERE status='sent' AND sent_at > now() - interval '24 hours') AS sent_24h,
                              count(*) FILTER (WHERE status='failed' AND created_at > now() - interval '24 hours') AS failed_24h
                       FROM sms_messages""")
    return {**counts, "configured": bool(config.MSGOWL_ACCESS_KEY), "sender_id": config.MSGOWL_SENDER_ID,
            "placeholders": list(sms.PLACEHOLDERS), "reminder_days": config.SMS_REMINDER_DAYS}


@router.get("/balance")
def balance(user=Depends(require("approve"))):
    if not config.MSGOWL_ACCESS_KEY:
        raise HTTPException(400, "MSGOWL_ACCESS_KEY is not set")
    try:
        with MessageOwl(config.MSGOWL_ACCESS_KEY, config.MSGOWL_SENDER_ID) as c:
            return c.balance()
    except SmsError as exc:
        raise HTTPException(502, f"MessageOwl: {exc}") from exc


@router.get("/messages")
def messages(subscriber_id: UUID | None = None, user=Depends(require("read"))):
    return db.rows(
        f"""SELECT m.id, m.created_at, m.sent_at, m.phone, m.kind, m.body, m.status, m.error, m.created_by,
                   s.account_number, s.full_name FROM sms_messages m LEFT JOIN subscribers s ON s.id=m.subscriber_id
            {'WHERE m.subscriber_id=%s' if subscriber_id else ''} ORDER BY m.id DESC LIMIT 500""",
        (subscriber_id,) if subscriber_id else None)


@router.get("/templates")
def templates(user=Depends(require("read"))):
    return db.rows("SELECT * FROM sms_templates ORDER BY kind")


class TemplateIn(BaseModel):
    body: str = Field(min_length=5, max_length=640)
    enabled: bool = True


@router.put("/templates/{kind}")
def update_template(kind: str, body: TemplateIn, user=Depends(require("approve"))):
    try:
        sms.render(body.body)
    except (KeyError, ValueError, IndexError) as exc:
        raise HTTPException(400, f"Template error: {exc}") from exc
    with db.connect() as conn:
        if not conn.execute("UPDATE sms_templates SET body=%s, enabled=%s, updated_by=%s, updated_at=now() WHERE kind=%s RETURNING kind",
                            (body.body, body.enabled, user["username"], kind)).fetchone():
            raise HTTPException(404, "No such template")
        audit.record(user["username"], "sms.template", "sms_template", kind, {"enabled": body.enabled}, conn=conn)
    return {"ok": True}


class SendIn(BaseModel):
    body: str = Field(min_length=1, max_length=640)


@router.post("/subscribers/{sub_id}")
def send_to_subscriber(sub_id: UUID, body: SendIn, user=Depends(require("subscribers"))):
    with db.connect() as conn:
        sub = conn.execute("SELECT * FROM subscribers WHERE id=%s", (sub_id,)).fetchone()
        if not sub:
            raise HTTPException(404, "Subscriber not found")
        if not normalize_phone(sub["phone"]):
            raise HTTPException(400, f"No valid mobile number on this account ({sub['phone'] or 'empty'})")
        sms.enqueue(conn, sub, "manual", actor=user["username"], body=body.body)
        audit.record(user["username"], "sms.send", "subscriber", sub_id, conn=conn)
    return {"queued": True}


class BroadcastIn(BaseModel):
    body: str = Field(min_length=5, max_length=640)
    island_id: UUID | None = None   # None = every island
    include_suspended: bool = False


@router.post("/broadcast")
def broadcast(body: BroadcastIn, user=Depends(require("approve"))):
    with db.connect() as conn:
        return sms.broadcast(conn, user["username"], body.body, body.island_id,
                             ("active", "suspended") if body.include_suspended else ("active",))


class TestIn(BaseModel):
    phone: str = Field(max_length=30)
    body: str = Field(default="SatLink: test message from the operations platform.", max_length=640)


@router.post("/test")
def test(body: TestIn, user=Depends(require("approve"))):
    """Sends immediately (not via the queue) so the result is shown on screen."""
    phone = normalize_phone(body.phone)
    if not phone:
        raise HTTPException(400, "Not a valid mobile number")
    if not config.MSGOWL_ACCESS_KEY:
        raise HTTPException(400, "MSGOWL_ACCESS_KEY is not set")
    try:
        with MessageOwl(config.MSGOWL_ACCESS_KEY, config.MSGOWL_SENDER_ID) as c:
            mid = c.send([phone], body.body)
    except SmsError as exc:
        raise HTTPException(502, f"MessageOwl: {exc}") from exc
    audit.record(user["username"], "sms.test", "phone", phone)
    return {"sent": True, "id": mid, "phone": phone}
