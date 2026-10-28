from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import audit, db
from ..deps import require
from ..services import billing, radius_sync

router = APIRouter(prefix="/api", tags=["billing"])


class PlanIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    download_mbps: int = Field(gt=0, le=100000)
    upload_mbps: int = Field(gt=0, le=100000)
    monthly_price_mvr: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    active: bool = True


@router.get("/plans")
def plans(user=Depends(require("read"))):
    return db.rows("""SELECT p.*, (SELECT count(*) FROM subscribers s WHERE s.plan_id=p.id AND s.status='active') AS active_subscribers
                      FROM service_plans p ORDER BY p.active DESC, p.monthly_price_mvr""")


@router.post("/plans", status_code=201)
def create_plan(body: PlanIn, user=Depends(require("billing"))):
    with db.connect() as conn:
        plan = conn.execute(
            """INSERT INTO service_plans(name,download_mbps,upload_mbps,monthly_price_mvr,active) VALUES (%s,%s,%s,%s,%s)
               ON CONFLICT (name) DO NOTHING RETURNING *""",
            (body.name, body.download_mbps, body.upload_mbps, body.monthly_price_mvr, body.active)).fetchone()
        if not plan:
            raise HTTPException(409, "Plan name exists")
        radius_sync.sync_plan(conn, plan)
        audit.record(user["username"], "plan.create", "plan", plan["id"], body.model_dump(mode="json"), conn=conn)
    return {"id": plan["id"]}


@router.put("/plans/{plan_id}")
def update_plan(plan_id: UUID, body: PlanIn, user=Depends(require("billing"))):
    with db.connect() as conn:
        plan = conn.execute(
            "UPDATE service_plans SET name=%s,download_mbps=%s,upload_mbps=%s,monthly_price_mvr=%s,active=%s WHERE id=%s RETURNING *",
            (body.name, body.download_mbps, body.upload_mbps, body.monthly_price_mvr, body.active, plan_id)).fetchone()
        if not plan:
            raise HTTPException(404, "Plan not found")
        radius_sync.sync_plan(conn, plan)
        audit.record(user["username"], "plan.update", "plan", plan_id, body.model_dump(mode="json"), conn=conn)
    # Speeds apply at the next login; disconnect customers from the subscriber page to force it now.
    return {"ok": True}


@router.get("/invoices")
def invoices(status: str | None = None, subscriber_id: UUID | None = None, user=Depends(require("read"))):
    where, params = ["true"], []
    if status:
        where.append("v.status=%s")
        params.append(status)
    if subscriber_id:
        where.append("v.subscriber_id=%s")
        params.append(subscriber_id)
    return db.rows(f"""SELECT v.*, s.account_number, s.full_name FROM invoices v JOIN subscribers s ON s.id=v.subscriber_id
                       WHERE {' AND '.join(where)} ORDER BY v.created_at DESC LIMIT 500""", params)


class PaymentIn(BaseModel):
    subscriber_id: UUID
    amount_mvr: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    method: Literal["cash", "bank_transfer", "card", "online", "other"]
    reference: str | None = Field(default=None, max_length=100)


@router.get("/payments")
def payments(user=Depends(require("read"))):
    return db.rows("""SELECT p.*, s.account_number, s.full_name FROM payments p JOIN subscribers s ON s.id=p.subscriber_id
                      ORDER BY p.received_at DESC LIMIT 500""")


@router.post("/payments", status_code=201)
def record_payment(body: PaymentIn, user=Depends(require("billing"))):
    with db.connect() as conn:
        if not conn.execute("SELECT 1 FROM subscribers WHERE id=%s", (body.subscriber_id,)).fetchone():
            raise HTTPException(404, "Subscriber not found")
        result = billing.record_payment(conn, body.subscriber_id, body.amount_mvr, body.method, body.reference, user["username"])
    if result["service_resumed"] and result["username"]:
        with db.connect() as conn:
            result["disconnect"] = radius_sync.disconnect(conn, result["username"])
    return result


class RunBilling(BaseModel):
    period: date | None = None


@router.post("/billing/run")
def run_billing(body: RunBilling, user=Depends(require("billing"))):
    with db.connect() as conn:
        created = billing.generate_invoices(conn, body.period or date.today(), user["username"])
        suspended = billing.enforce_overdue(conn, user["username"])
    with db.connect() as conn:
        for username in suspended:
            radius_sync.disconnect(conn, username)
    return {"invoices_created": created, "suspended": suspended}


@router.post("/invoices/{invoice_id}/void")
def void_invoice(invoice_id: UUID, user=Depends(require("approve"))):
    with db.connect() as conn:
        if not conn.execute("UPDATE invoices SET status='void' WHERE id=%s AND paid_mvr=0 RETURNING id", (invoice_id,)).fetchone():
            raise HTTPException(409, "Only unpaid invoices can be voided")
        audit.record(user["username"], "invoice.void", "invoice", invoice_id, conn=conn)
    return {"ok": True}
