"""Monthly invoicing, payment allocation and suspension for non-payment."""
from datetime import date, timedelta
from decimal import Decimal

from .. import audit, config
from . import radius_sync


def month_start(d: date) -> date:
    return d.replace(day=1)


def next_month(d: date) -> date:
    return (d.replace(day=28) + timedelta(days=4)).replace(day=1)


def generate_invoices(conn, period: date, actor: str) -> int:
    start = month_start(period)
    end = next_month(start) - timedelta(days=1)
    rows = conn.execute(
        """INSERT INTO invoices(subscriber_id,invoice_number,amount_mvr,due_at,status,period_start,period_end)
           SELECT s.id, 'INV-' || to_char(%(start)s::date,'YYYYMM') || '-' || nextval('invoice_number_seq'),
                  p.monthly_price_mvr, %(due)s, 'unpaid', %(start)s, %(end)s
           FROM subscribers s JOIN service_plans p ON p.id=s.plan_id
           WHERE s.status IN ('active','suspended')
           ON CONFLICT (subscriber_id, period_start) WHERE period_start IS NOT NULL DO NOTHING
           RETURNING id""",
        {"start": start, "end": end, "due": start + timedelta(days=config.BILLING_DUE_DAYS)},
    ).fetchall()
    audit.record(actor, "billing.generate", "period", start.isoformat(), {"created": len(rows)}, conn=conn)
    return len(rows)


def record_payment(conn, subscriber_id, amount: Decimal, method: str, reference: str | None, actor: str) -> dict:
    """Allocate oldest-first across open invoices. Returns allocation + whether service resumed."""
    pay = conn.execute(
        "INSERT INTO payments(subscriber_id,amount_mvr,method,reference,recorded_by) VALUES (%s,%s,%s,%s,%s) RETURNING id",
        (subscriber_id, amount, method, reference, actor),
    ).fetchone()
    remaining = Decimal(amount)
    allocated = []
    for inv in conn.execute(
        """SELECT id,invoice_number,amount_mvr,paid_mvr FROM invoices
           WHERE subscriber_id=%s AND status IN ('unpaid','overdue') ORDER BY due_at NULLS LAST, created_at FOR UPDATE""",
        (subscriber_id,),
    ).fetchall():
        if remaining <= 0:
            break
        take = min(remaining, inv["amount_mvr"] - inv["paid_mvr"])
        remaining -= take
        paid = inv["paid_mvr"] + take
        conn.execute(
            "UPDATE invoices SET paid_mvr=%s, status=CASE WHEN %s>=amount_mvr THEN 'paid' ELSE status END WHERE id=%s",
            (paid, paid, inv["id"]),
        )
        allocated.append({"invoice": inv["invoice_number"], "amount": str(take)})
    if allocated:
        conn.execute("UPDATE payments SET invoice_id=(SELECT id FROM invoices WHERE invoice_number=%s) WHERE id=%s",
                     (allocated[0]["invoice"], pay["id"]))
    resumed = False
    sub = conn.execute("SELECT * FROM subscribers WHERE id=%s FOR UPDATE", (subscriber_id,)).fetchone()
    still_overdue = conn.execute(
        "SELECT 1 FROM invoices WHERE subscriber_id=%s AND status='overdue' LIMIT 1", (subscriber_id,)).fetchone()
    if sub["status"] == "suspended" and sub["suspended_reason"] == "non-payment" and not still_overdue:
        conn.execute("UPDATE subscribers SET status='active', suspended_reason=NULL WHERE id=%s", (subscriber_id,))
        radius_sync.sync_subscriber(conn, {**sub, "status": "active"})
        resumed = True
    audit.record(actor, "billing.payment", "subscriber", subscriber_id,
                 {"amount": str(amount), "method": method, "reference": reference, "allocated": allocated,
                  "credit_left": str(remaining), "resumed": resumed}, conn=conn)
    return {"payment_id": str(pay["id"]), "allocated": allocated, "unallocated": str(remaining),
            "service_resumed": resumed, "username": sub["pppoe_username"]}


def enforce_overdue(conn, actor="system", today: date | None = None) -> list[str]:
    """Mark late invoices overdue; suspend customers past the grace period. Returns usernames to disconnect."""
    today = today or date.today()
    conn.execute("UPDATE invoices SET status='overdue' WHERE status='unpaid' AND due_at < %s", (today,))
    subs = conn.execute(
        """SELECT DISTINCT s.* FROM subscribers s JOIN invoices i ON i.subscriber_id=s.id
           WHERE s.status='active' AND i.status='overdue' AND i.due_at < %s""",
        (today - timedelta(days=config.SUSPEND_AFTER_DAYS_OVERDUE),),
    ).fetchall()
    usernames = []
    for sub in subs:
        conn.execute("UPDATE subscribers SET status='suspended', suspended_reason='non-payment' WHERE id=%s", (sub["id"],))
        radius_sync.sync_subscriber(conn, {**sub, "status": "suspended"})
        audit.record(actor, "subscriber.auto_suspend", "subscriber", sub["id"], {"reason": "non-payment"}, conn=conn)
        if sub["pppoe_username"]:
            usernames.append(sub["pppoe_username"])
    return usernames
