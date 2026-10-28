"""SMS notifications: templates, a once-only queue, and the sender run by the worker."""
import logging
import time

from .. import audit, config
from ..adapters.msgowl import MessageOwl, SmsError, normalize_phone

log = logging.getLogger(__name__)
PLACEHOLDERS = ("name", "account", "amount", "due", "invoice", "balance", "plan")


class _Blank(dict):
    def __missing__(self, key):
        return ""


def render(template: str, **values) -> str:
    return template.format_map(_Blank({k: "" if v is None else v for k, v in values.items()}))[:640]


def enqueue(conn, sub: dict, kind: str, ref=None, actor="system", body: str | None = None, **values) -> bool:
    """Queue one SMS for a subscriber. Template kinds respect the template's on/off switch;
    (subscriber, kind, ref) is sent at most once, so re-running billing never double-texts."""
    if body is None:
        t = conn.execute("SELECT body, enabled FROM sms_templates WHERE kind=%s", (kind,)).fetchone()
        if not t or not t["enabled"]:
            return False
        body = render(t["body"], name=sub.get("full_name"), account=sub.get("account_number"), **values)
    phone = normalize_phone(sub.get("phone"))
    row = conn.execute(
        """INSERT INTO sms_messages(subscriber_id,phone,kind,ref,body,status,error,created_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (subscriber_id, kind, ref) WHERE ref IS NOT NULL DO NOTHING RETURNING id""",
        (sub.get("id"), phone or (sub.get("phone") or ""), kind, str(ref) if ref is not None else None, body,
         "queued" if phone else "skipped", None if phone else "no valid mobile number", actor),
    ).fetchone()
    return bool(row) and bool(phone)


def queue_due_reminders(conn) -> int:
    """Unpaid invoices due in SMS_REMINDER_DAYS days (platform-billed customers only)."""
    n = 0
    for r in conn.execute(
        """SELECT v.id, v.invoice_number, v.amount_mvr - v.paid_mvr AS amount, v.due_at, s.*
           FROM invoices v JOIN subscribers s ON s.id=v.subscriber_id
           WHERE v.status='unpaid' AND s.managed_by='platform' AND s.status='active'
             AND v.due_at = current_date + %s""", (config.SMS_REMINDER_DAYS,)).fetchall():
        n += enqueue(conn, r, "due_reminder", ref=f"inv:{r['invoice_number']}",
                     invoice=r["invoice_number"], amount=f"{r['amount']:.2f}", due=r["due_at"])
    return n


def send_pending(conn, client=None) -> dict:
    """Send queued messages, staying under MessageOwl's rate limit. Identical texts (broadcasts) go
    out as bulk POSTs. Returns counts. Call from the worker every cycle."""
    out = {"sent": 0, "failed": 0, "posts": 0}
    if not config.MSGOWL_ACCESS_KEY and client is None:
        return out
    rows = conn.execute(
        "SELECT id, phone, body FROM sms_messages WHERE status='queued' ORDER BY id LIMIT 2000 FOR UPDATE SKIP LOCKED").fetchall()
    if not rows:
        return out
    groups: dict[str, list] = {}
    for r in rows:
        groups.setdefault(r["body"], []).append(r)
    batches = []
    for body, items in groups.items():
        for i in range(0, len(items), max(1, config.SMS_BULK_CHUNK)):
            batches.append((body, items[i:i + config.SMS_BULK_CHUNK]))
    own = client is None
    client = client or MessageOwl(config.MSGOWL_ACCESS_KEY, config.MSGOWL_SENDER_ID)
    try:
        for body, items in batches[:config.SMS_PER_MINUTE]:
            ids = [r["id"] for r in items]
            try:
                provider_id = client.send([r["phone"] for r in items], body)
            except SmsError as exc:
                if exc.status == 429 or exc.status is None:   # rate limited / network: try again next cycle
                    log.warning("sms paused: %s", exc)
                    break
                conn.execute("UPDATE sms_messages SET status='failed', error=%s WHERE id = ANY(%s)", (str(exc)[:300], ids))
                out["failed"] += len(ids)
                if exc.status == 401:                         # bad key: stop, everything else would fail too
                    log.error("MessageOwl rejected the access key")
                    break
                continue
            finally:
                out["posts"] += 1
            conn.execute("UPDATE sms_messages SET status='sent', provider_id=%s, sent_at=now(), error=NULL WHERE id = ANY(%s)",
                         (provider_id, ids))
            out["sent"] += len(ids)
    finally:
        if own:
            client.close()
    return out


def broadcast(conn, actor: str, body: str, island_id=None, statuses=("active",)) -> dict:
    """Same text to every subscriber on an island (or everyone): outage and maintenance notices."""
    ref = f"bc:{int(time.time())}"
    where, params = ["s.status = ANY(%s)"], [list(statuses)]
    if island_id:
        where.append("s.island_id=%s")
        params.append(island_id)
    subs = conn.execute(f"SELECT * FROM subscribers s WHERE {' AND '.join(where)}", params).fetchall()
    queued = sum(enqueue(conn, s, "broadcast", ref=ref, actor=actor, body=body[:640]) for s in subs)
    audit.record(actor, "sms.broadcast", "island", island_id, {"subscribers": len(subs), "queued": queued, "body": body[:640]}, conn=conn)
    return {"subscribers": len(subs), "queued": queued, "no_phone": len(subs) - queued}
