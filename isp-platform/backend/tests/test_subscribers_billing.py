from datetime import date, timedelta

import psycopg

from app import config
from app.services import billing


def _setup(admin, uname):
    plan = admin.post("/api/plans", json={"name": f"Fiber 50 {uname}", "download_mbps": 50, "upload_mbps": 10,
                                          "monthly_price_mvr": "500.00"}).json()["id"]
    island = admin.post("/api/islands", json={"code": f"I{uname[:6]}", "name": f"Island {uname}"}).json()["id"]
    r = admin.post("/api/subscribers", json={"full_name": "Aishath", "island_id": island, "plan_id": plan,
                                             "pppoe_username": uname, "phone": "7771234"})
    assert r.status_code == 201, r.text
    return plan, r.json()


def _radius(sql, user):
    return {
        "check": {a: v for a, v in sql("SELECT attribute,value FROM radcheck WHERE username=%s", (user,))},
        "groups": [g for (g,) in sql("SELECT groupname FROM radusergroup WHERE username=%s", (user,))],
        "reply": {a: v for a, v in sql("SELECT attribute,value FROM radreply WHERE username=%s", (user,))},
    }


def test_lifecycle_drives_radius(admin, sql):
    plan, sub = _setup(admin, "cust.one")
    assert len(sub["pppoe_password"]) == 12
    assert sql("SELECT value FROM radgroupreply WHERE groupname=%s", (f"plan:{plan}",)) == [("10M/50M",)]
    r = _radius(sql, "cust.one")
    assert r["check"]["Auth-Type"] == "Reject"  # pending
    assert r["check"]["Cleartext-Password"] == sub["pppoe_password"]

    assert admin.post(f"/api/subscribers/{sub['id']}/status", json={"status": "active"}).status_code == 200
    r = _radius(sql, "cust.one")
    assert "Auth-Type" not in r["check"] and r["check"]["Simultaneous-Use"] == "1" and r["groups"] == [f"plan:{plan}"]

    admin.post(f"/api/subscribers/{sub['id']}/status", json={"status": "suspended", "reason": "test"})
    assert _radius(sql, "cust.one")["groups"] == ["suspended"]

    # Rename moves the RADIUS rows, keeping the password
    s = admin.get(f"/api/subscribers/{sub['id']}").json()
    body = {k: s[k] for k in ("full_name", "phone", "address", "island_id", "plan_id")} | {"pppoe_username": "cust.uno", "static_ip": "100.64.1.9"}
    assert admin.put(f"/api/subscribers/{sub['id']}", json=body).status_code == 200
    assert _radius(sql, "cust.one") == {"check": {}, "groups": [], "reply": {}}
    r = _radius(sql, "cust.uno")
    assert r["check"]["Cleartext-Password"] == sub["pppoe_password"] and r["reply"]["Framed-IP-Address"] == "100.64.1.9"

    admin.post(f"/api/subscribers/{sub['id']}/status", json={"status": "cancelled"})
    assert _radius(sql, "cust.uno") == {"check": {}, "groups": [], "reply": {}}


def test_activation_needs_plan(admin):
    r = admin.post("/api/subscribers", json={"full_name": "No plan", "pppoe_username": "noplan"}).json()
    assert admin.post(f"/api/subscribers/{r['id']}/status", json={"status": "active"}).status_code == 400
    assert admin.get(f"/api/subscribers/{r['id']}").json()["status"] == "pending"


def test_duplicate_username(admin):
    admin.post("/api/subscribers", json={"full_name": "A", "pppoe_username": "dupe"})
    assert admin.post("/api/subscribers", json={"full_name": "B", "pppoe_username": "dupe"}).status_code == 409


def test_billing_cycle_suspend_and_resume(admin, sql):
    plan, sub = _setup(admin, "payer")
    admin.post(f"/api/subscribers/{sub['id']}/status", json={"status": "active"})
    period = date.today().replace(day=1) - timedelta(days=40)
    with psycopg.connect(config.DATABASE_URL) as conn:
        conn.row_factory = psycopg.rows.dict_row
        assert billing.generate_invoices(conn, period, "test") >= 1
        assert billing.generate_invoices(conn, period, "test") == 0  # idempotent
        suspended = billing.enforce_overdue(conn, "test", today=date.today())
    assert "payer" in suspended
    assert _radius(sql, "payer")["groups"] == ["suspended"]

    r = admin.post("/api/payments", json={"subscriber_id": sub["id"], "amount_mvr": "200.00", "method": "cash"}).json()
    assert r["service_resumed"] is False  # partial payment
    r = admin.post("/api/payments", json={"subscriber_id": sub["id"], "amount_mvr": "300.00", "method": "bank_transfer",
                                          "reference": "BML123"}).json()
    assert r["service_resumed"] is True and r["unallocated"] == "0.00"
    assert _radius(sql, "payer")["groups"] == [f"plan:{plan}"]
    assert admin.get(f"/api/subscribers/{sub['id']}").json()["status"] == "active"


def test_billing_role_cannot_touch_network():
    from tests.conftest import login
    bill = login("bill")
    assert bill.post("/api/plans", json={"name": "B plan", "download_mbps": 5, "upload_mbps": 1, "monthly_price_mvr": "1"}).status_code == 201
    assert bill.post("/api/devices", json={"name": "x", "vendor": "mikrotik", "role": "other"}).status_code == 403
