import json
from datetime import date, timedelta

import httpx
import psycopg
import pytest
from psycopg.rows import dict_row

from app import config
from app.adapters.msgowl import MessageOwl, SmsError, normalize_phone
from app.services import billing, importer, sms
from tests.conftest import login


def conn():
    return psycopg.connect(config.DATABASE_URL, row_factory=dict_row, autocommit=True)


@pytest.fixture(autouse=True)
def clean():
    with conn() as c:
        c.execute("DELETE FROM sms_messages")
    yield


# ---------------- MessageOwl adapter
def test_normalize_phone():
    assert normalize_phone("7771234") == "9607771234"
    assert normalize_phone("+960 777-1234") == "9607771234"
    assert normalize_phone("009607771234") == "9607771234"
    assert normalize_phone("9607771234") == "9607771234"
    assert normalize_phone("123") is None and normalize_phone("") is None and normalize_phone(None) is None
    assert normalize_phone("96077712") is None          # 960 + wrong length


def owl(responses, seen):
    def handler(req):
        seen.append({"path": req.url.path, "auth": req.headers["authorization"], "json": json.loads(req.content or b"null")})
        status, body = responses.pop(0) if responses else (200, {"id": 1, "message": "Message has been sent successfully."})
        return httpx.Response(status, json=body)
    return MessageOwl("KEY123", "SatLink", transport=httpx.MockTransport(handler))


def test_msgowl_request_format_and_errors():
    seen = []
    c = owl([(200, {"id": 55, "message": "ok"})], seen)
    assert c.send(["9607771234"], "hi") == "55"
    assert seen[0] == {"path": "/messages", "auth": "AccessKey KEY123",
                       "json": {"recipients": "9607771234", "sender_id": "SatLink", "body": "hi"}}
    c.send(["9607771234", "9607779999"], "bulk")
    assert seen[1]["json"]["recipients"] == ["9607771234", "9607779999"]
    with pytest.raises(SmsError) as e:
        owl([(429, {"message": "slow down", "retry_after": 30})], []).send(["9607771234"], "x")
    assert e.value.status == 429 and e.value.retry_after == 30


# ---------------- queue + sender
def subscriber(c, user, phone="7771234", managed_by="platform", status="active", plan=True):
    c.execute("DELETE FROM subscribers WHERE pppoe_username=%s", (user,))
    plan_id = None
    if plan:
        plan_id = c.execute("""INSERT INTO service_plans(name,download_mbps,upload_mbps,monthly_price_mvr) VALUES ('SMS plan',20,5,450)
                               ON CONFLICT (name) DO UPDATE SET name=EXCLUDED.name RETURNING id""").fetchone()["id"]
    return c.execute("""INSERT INTO subscribers(account_number,full_name,phone,pppoe_username,status,managed_by,plan_id)
                        VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
                     (f"T-{user}", f"Name {user}", phone, user, status, managed_by, plan_id)).fetchone()


def test_enqueue_once_and_template_switch():
    with conn() as c:
        s = subscriber(c, "sms.one")
        assert sms.enqueue(c, s, "payment_received", ref="pay:1", amount="450.00") is True
        assert sms.enqueue(c, s, "payment_received", ref="pay:1", amount="450.00") is False   # once only
        body = c.execute("SELECT body, phone FROM sms_messages").fetchone()
        assert body == {"body": "SatLink: Payment of MVR 450.00 received for account T-sms.one. Thank you!", "phone": "9607771234"}
        c.execute("UPDATE sms_templates SET enabled=false WHERE kind='payment_received'")
        assert sms.enqueue(c, s, "payment_received", ref="pay:2") is False
        c.execute("UPDATE sms_templates SET enabled=true WHERE kind='payment_received'")
        nophone = subscriber(c, "sms.nophone", phone="")
        assert sms.enqueue(c, nophone, "manual", body="x") is False
        assert c.execute("SELECT status FROM sms_messages WHERE subscriber_id=%s", (nophone["id"],)).fetchone()["status"] == "skipped"


def test_send_pending_bulk_rate_limit_and_bad_key(monkeypatch):
    monkeypatch.setattr(config, "SMS_BULK_CHUNK", 2)
    with conn() as c:
        subs = [subscriber(c, f"bc{i}", phone=f"77700{i:02d}") for i in range(5)]
        for s in subs:
            sms.enqueue(c, s, "broadcast", ref="bc:1", body="Outage on Neykurendhoo until 15:00")
        sms.enqueue(c, subs[0], "manual", body="personal note")
        seen = []
        out = sms.send_pending(c, owl([], seen))
        assert out == {"sent": 6, "failed": 0, "posts": 4}            # 5 identical -> 2+2+1, plus 1 personal
        assert sorted(len(s["json"]["recipients"]) if isinstance(s["json"]["recipients"], list) else 1 for s in seen) == [1, 1, 2, 2]
        # rate limited: stays queued
        sms.enqueue(c, subs[1], "manual", body="later")
        assert sms.send_pending(c, owl([(429, {"message": "limit"})], []))["sent"] == 0
        assert c.execute("SELECT status FROM sms_messages WHERE body='later'").fetchone()["status"] == "queued"
        # bad key: marked failed with the reason
        assert sms.send_pending(c, owl([(401, {"message": "Unauthorized"})], []))["failed"] == 1
        assert c.execute("SELECT status, error FROM sms_messages WHERE body='later'").fetchone() == {"status": "failed", "error": "Unauthorized"}


def test_billing_texts_platform_customers_but_never_dma_ones():
    with conn() as c:
        mine = subscriber(c, "plat.cust")
        dma = subscriber(c, "HDNL9999", managed_by="dma")
        period = date.today().replace(day=1) - timedelta(days=40)
        billing.generate_invoices(c, period, "test")
        assert c.execute("SELECT count(*) AS n FROM invoices WHERE subscriber_id=%s", (dma["id"],)).fetchone()["n"] == 0
        assert c.execute("SELECT kind FROM sms_messages WHERE subscriber_id=%s", (mine["id"],)).fetchone()["kind"] == "invoice_issued"
        suspended = billing.enforce_overdue(c, "test", today=date.today())
        assert "plat.cust" in suspended and "HDNL9999" not in suspended
        kinds = {r["kind"] for r in c.execute("SELECT kind FROM sms_messages WHERE subscriber_id=%s", (mine["id"],))}
        assert kinds == {"invoice_issued", "suspended"}
        assert c.execute("SELECT count(*) AS n FROM sms_messages WHERE subscriber_id=%s", (dma["id"],)).fetchone()["n"] == 0


# ---------------- DMA import
DMA_CSV = """username;password;firstname;lastname;mobile;address;city;srvname;expiration;enableuser;staticipcpe
HDNL0069;Ab12cd;Aishath;Ali;7771001;Hirundhu;Neykurendhoo;2MU;2099-01-01 00:00:00;1;
HDNL0070;Ef34gh;Mohamed;Hassan;+960 777-1002;;Neykurendhoo;5M;2020-01-01 00:00:00;1;
HDNL0071;;Fathimath;;12;;;2MU;2099-01-01 00:00:00;0;10.0.9.9
Saef;Zz99yy;Saef;;7771004;;;Unknown Plan;2099-01-01;1;not-an-ip
HDNL0069;dup;Dup;;;;;2MU;;1;
bad user;x;Bad;;;;;2MU;;1;
HDNL0072;Qq11ww;Late;;7771005;;;2MU;31/12/2099;1;
"""


def test_import_subscribers_dry_run_then_apply():
    with conn() as c:
        c.execute("DELETE FROM subscribers WHERE managed_by='dma' OR pppoe_username LIKE 'HDNL%%' OR pppoe_username='Saef'")
        for name, down, up in (("2MU", 2, 1), ("5M", 5, 2)):
            c.execute("""INSERT INTO service_plans(name,download_mbps,upload_mbps,monthly_price_mvr) VALUES (%s,%s,%s,300)
                         ON CONFLICT (name) DO NOTHING""", (name, down, up))
        c.execute("DELETE FROM service_plans WHERE name='Unknown Plan'")
        isl = c.execute("""INSERT INTO islands(code,name) VALUES ('HDH-NEY','Neykurendhoo') ON CONFLICT (code)
                           DO UPDATE SET name=EXCLUDED.name RETURNING id""").fetchone()["id"]

        r = importer.import_subscribers(c, DMA_CSV, "test", dry_run=True)
        assert r["columns"]["username"] == "username" and r["columns"]["plan"] == "srvname" and r["columns"]["phone"] == "mobile"
        assert (r["rows"], r["new"], r["updated"]) == (7, 5, 0)
        assert {e["row"] for e in r["errors"]} == {6, 7}                     # duplicate + bad characters
        assert r["plans_missing"] == [{"name": "Unknown Plan", "subscribers": 1}]
        assert r["status"] == {"active": 2, "suspended": 2, "pending": 1}  # 0070 expired, 0071 disabled, Saef has no plan
        assert r["no_password"] == 1 and r["invalid_phones"] == 1
        assert c.execute("SELECT count(*) AS n FROM subscribers WHERE pppoe_username LIKE 'HDNL%%'").fetchone()["n"] == 0

        r = importer.import_subscribers(c, DMA_CSV, "test", dry_run=False, default_island_id=isl, create_missing_plans=True)
        assert r["new"] == 5
        s = c.execute("SELECT * FROM subscribers WHERE pppoe_username='HDNL0069'").fetchone()
        assert (s["full_name"], s["phone"], s["address"], s["managed_by"], s["status"], str(s["expires_at"]), s["account_number"]) == \
            ("Aishath Ali", "7771001", "Hirundhu, Neykurendhoo", "dma", "active", "2099-01-01", "HDNL0069")
        assert s["island_id"] == isl
        pw = c.execute("SELECT value FROM radcheck WHERE username='HDNL0069' AND attribute='Cleartext-Password'").fetchone()
        assert pw["value"] == "Ab12cd"                                        # case-sensitive username kept, password migrated
        assert c.execute("SELECT status, suspended_reason FROM subscribers WHERE pppoe_username='HDNL0070'").fetchone() == \
            {"status": "suspended", "suspended_reason": "imported: expired in DMA"}
        assert c.execute("SELECT host(static_ip) AS ip FROM subscribers WHERE pppoe_username='HDNL0071'").fetchone()["ip"] == "10.0.9.9"
        assert c.execute("SELECT active FROM service_plans WHERE name='Unknown Plan'").fetchone()["active"] is False
        assert str(c.execute("SELECT expires_at FROM subscribers WHERE pppoe_username='HDNL0072'").fetchone()["expires_at"]) == "2099-12-31"

        # re-import refreshes, never duplicates; platform-managed accounts are left alone
        c.execute("UPDATE subscribers SET managed_by='platform' WHERE pppoe_username='HDNL0072'")
        r = importer.import_subscribers(c, DMA_CSV, "test", dry_run=False, default_island_id=isl)
        assert (r["new"], r["updated"], r["skipped"]) == (0, 4, 1)


def test_import_mysql_tab_export_with_nulls():
    text = "username\tpassword\tfirstname\tmobile\tsrvname\texpiration\tenableuser\nHDNL0500\tPw55aa\tAli\tNULL\tNULL\t0000-00-00 00:00:00\t1\n"
    with conn() as c:
        r = importer.import_subscribers(c, text, "test", dry_run=True)
    assert r["new"] == 1 and r["errors"] == [] and r["invalid_phones"] == 0
    assert r["sample"][0] == {"username": "HDNL0500", "name": "Ali", "phone": None, "plan": "", "expires": "", "status": "pending", "has_password": True}


def test_import_nas():
    csv_text = "nasname,shortname,secret,type,description\n192.168.174.40,NEILAIDHOO-GPON-NEW,short1,mikrotik,island\nnot-ip,x,y,,\n"
    with conn() as c:
        c.execute("DELETE FROM nas WHERE nasname='192.168.174.40'")
        r = importer.import_nas(c, csv_text, "test", dry_run=False)
        assert (r["new"], r["weak_secrets"], len(r["errors"])) == (1, 1, 1)
        assert c.execute("SELECT shortname, secret, type FROM nas WHERE nasname='192.168.174.40'").fetchone() == \
            {"shortname": "NEILAIDHOO-GPON-NEW", "secret": "short1", "type": "mikrotik"}


def test_import_and_sms_api_permissions():
    admin, noc = login("alice"), login("nina")
    assert noc.post("/api/import/subscribers", json={"csv": "username\nx1"}).status_code == 403
    r = admin.post("/api/import/subscribers", json={"csv": "username\nzz.dry1", "dry_run": True})
    assert r.status_code == 200 and r.json()["new"] == 1
    with conn() as c:
        assert c.execute("SELECT count(*) AS n FROM subscribers WHERE pppoe_username='zz.dry1'").fetchone()["n"] == 0  # dry run wrote nothing
    assert noc.post("/api/sms/broadcast", json={"body": "outage notice"}).status_code == 403
    assert admin.get("/api/sms/status").json()["configured"] is False
    assert admin.put("/api/sms/templates/restored", json={"body": "SatLink: {account} back online", "enabled": True}).status_code == 200
    assert admin.put("/api/sms/templates/restored", json={"body": "SatLink: {account back", "enabled": True}).status_code == 400
