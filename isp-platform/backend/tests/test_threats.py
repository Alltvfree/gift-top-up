import json

import httpx
import psycopg
import pytest
from psycopg.rows import dict_row

from app import config
from app.adapters.mikrotik import RouterOS, ros_duration
from app.services import monitor, threats
from tests.conftest import login


def conn():
    return psycopg.connect(config.DATABASE_URL, row_factory=dict_row, autocommit=True)


@pytest.fixture(autouse=True)
def clean():
    with conn() as c:
        c.execute("DELETE FROM security_events; DELETE FROM blocked_addresses; DELETE FROM alerts WHERE kind LIKE 'bruteforce:%'")
    yield


def router_device(name="NEILAIDHOO-GPON-NEW", ip="192.168.174.40"):
    with conn() as c:
        c.execute("DELETE FROM devices WHERE name=%s", (name,))
        return c.execute("INSERT INTO devices(name,vendor,role,management_ip) VALUES (%s,'mikrotik','island_router',%s) RETURNING *",
                         (name, ip)).fetchone()


def fail(c, device, ip, n, user="admin"):
    threats.record_events(c, device, [{"src_ip": ip, "username": user, "via": "winbox", "message": "x"}] * n, None)


# ---------- router log parsing
LOG = [
    {".id": "*10", "message": "login failure for user admin from 16.5.0.227 via winbox"},
    {".id": "*11", "message": "user satai logged in from 192.168.101.10 via winbox"},
    {".id": "*12", "message": "login failure for user root from 16.5.0.228 via ssh"},
]


def ros_with(log_rows, post_ok=True):
    def handler(req):
        if req.url.path.endswith("/log/print"):
            assert json.loads(req.content)[".query"] == ["topics=system,error,critical"]
            return httpx.Response(200, json=log_rows) if post_ok else httpx.Response(400, json={"detail": "no"})
        if req.url.path.endswith("/log"):
            return httpx.Response(200, json=log_rows)
        raise AssertionError(req.url)
    return RouterOS("10.0.0.1", "u", "p", transport=httpx.MockTransport(handler))


def test_login_failures_parse_and_cursor():
    events, cur = ros_with(LOG).login_failures(None)
    assert [(e["src_ip"], e["username"], e["via"]) for e in events] == [("16.5.0.227", "admin", "winbox"), ("16.5.0.228", "root", "ssh")]
    assert cur == 0x12
    assert ros_with(LOG).login_failures(0x11)[0][0]["src_ip"] == "16.5.0.228"    # only newer lines
    assert ros_with(LOG).login_failures(0x12)[0] == []
    assert len(ros_with(LOG).login_failures(0x500)[0]) == 2                     # log restarted -> read all
    assert len(ros_with(LOG, post_ok=False).login_failures(None)[0]) == 2       # GET fallback


def test_ros_duration():
    assert ros_duration(7 * 86400) == "7d0h0m" and ros_duration(3700) == "1h1m" and ros_duration(5) == "0h1m"


# ---------- decisions
def test_public_attacker_blocked_after_threshold():
    d = router_device()
    with conn() as c:
        fail(c, d, "45.9.20.1", config.THREAT_FAILURES - 1)
        assert threats.evaluate(c)["blocked"] == []
        fail(c, d, "45.9.20.1", 1)
        r = threats.evaluate(c)
        assert r["blocked"] == ["45.9.20.1/32"]
        assert threats.evaluate(c)["blocked"] == []      # not twice
        b = c.execute("SELECT source, hits, expires_at > now() + interval '6 days' AS long FROM blocked_addresses").fetchone()
        assert b == {"source": "auto", "hits": config.THREAT_FAILURES, "long": True}


def test_rotating_attacker_becomes_slash24():
    d = router_device()
    with conn() as c:
        for last in (226, 227, 228):
            fail(c, d, f"16.5.0.{last}", config.THREAT_FAILURES)
        r = threats.evaluate(c)
        assert r["merged"] == ["16.5.0.0/24"]
        active = [x["address"] for x in c.execute("SELECT address::text FROM blocked_addresses WHERE removed_at IS NULL")]
        assert active == ["16.5.0.0/24"]
        fail(c, d, "16.5.0.241", config.THREAT_FAILURES)   # new host in the same /24 is already covered
        assert threats.evaluate(c)["blocked"] == []


def test_internal_sources_alert_but_never_block():
    d = router_device()
    with conn() as c:
        fail(c, d, "10.0.5.77", 20)          # infected customer
        fail(c, d, "100.64.3.9", 20)         # CGNAT
        r = threats.evaluate(c)
        assert r["blocked"] == [] and {o["ip"] for o in r["internal"]} == {"10.0.5.77", "100.64.3.9"}
        monitor.threat_alerts(c, r)
        kinds = {a["kind"] for a in c.execute("SELECT kind FROM alerts WHERE resolved_at IS NULL AND kind LIKE 'bruteforce:%'")}
        assert kinds == {"bruteforce:10.0.5.77", "bruteforce:100.64.3.9"}
        c.execute("DELETE FROM security_events")
        monitor.threat_alerts(c, threats.evaluate(c))
        assert c.execute("SELECT count(*) AS n FROM alerts WHERE resolved_at IS NULL AND kind LIKE 'bruteforce:%'").fetchone()["n"] == 0


def test_protected_addresses(monkeypatch):
    d = router_device(name="core-public", ip="8.8.4.4")          # a router whose management IP is public
    monkeypatch.setattr(config, "THREAT_NEVER_BLOCK", ["9.9.9.0/24"])
    with conn() as c:
        fail(c, d, "8.8.4.4", 10)
        fail(c, d, "9.9.9.9", 10)
        assert threats.evaluate(c)["blocked"] == []
        with pytest.raises(threats.Protected):
            threats.add_block(c, "8.8.0.0/16", "x", "manual", "t", None)


def test_expiry_and_auto_block_switch(monkeypatch):
    d = router_device()
    with conn() as c:
        threats.add_block(c, "45.9.30.0/24", "x", "manual", "t", 1)
        c.execute("UPDATE blocked_addresses SET expires_at = now() - interval '1 minute'")
        assert threats.evaluate(c)["expired"] == 1
        monkeypatch.setattr(config, "THREAT_AUTO_BLOCK", False)
        fail(c, d, "45.9.20.2", 50)
        assert threats.evaluate(c)["blocked"] == []


# ---------- pushing to a router
class FakeRouter:
    def __init__(self, entries, enforced=True):
        self.entries, self.enforced, self.added, self.removed = entries, enforced, [], []

    def blocklist_entries(self):
        return self.entries

    def blocklist_add(self, address, timeout_s, comment):
        self.added.append((address, timeout_s, comment))

    def blocklist_remove(self, item_id):
        self.removed.append(item_id)

    def blocklist_enforced(self):
        return self.enforced


def test_sync_only_touches_platform_entries():
    import ipaddress
    r = FakeRouter([
        {".id": "*1", "address": "16.5.0.0/24", "comment": "isp-block: old"},     # still wanted -> kept
        {".id": "*2", "address": "45.9.20.1", "comment": "isp-block: unblocked"},  # no longer wanted -> removed
        {".id": "*3", "address": "77.1.1.1", "comment": ""},                        # router's own dynamic entry -> untouched
        {".id": "*4", "address": "88.1.1.0/24", "comment": "added by hand"},       # someone's manual entry -> untouched
    ], enforced=False)
    desired = {ipaddress.ip_network("16.5.0.0/24"): ("isp-block: rotating", 600000),
               ipaddress.ip_network("203.0.113.9/32"): ("isp-block: brute force", 3600)}
    out = threats.sync_router(r, desired)
    assert r.removed == ["*2"]
    assert r.added == [("203.0.113.9", 3600, "isp-block: brute force")]      # /32 sent as a plain address
    assert out == {"added": 1, "removed": 1, "enforced": False}


def test_store_records_router_events():
    d = router_device()
    with conn() as c:
        monitor.store(c, d, {"reachable": True, "latency_ms": 3, "packet_loss_pct": 0, "extra": {},
                             "security": ([{"src_ip": "16.5.0.227", "username": "admin", "via": "winbox", "message": "m"}], 0x40)})
        assert c.execute("SELECT count(*) AS n FROM security_events").fetchone()["n"] == 1
        assert c.execute("SELECT log_cursor FROM devices WHERE id=%s", (d["id"],)).fetchone()["log_cursor"] == 0x40


# ---------- API
def test_api_manual_block_unblock_and_rbac():
    router_device()
    admin = login("alice")
    r = admin.post("/api/threats/blocks", json={"address": "16.5.0.0/24", "reason": "winbox brute force", "hours": 24})
    assert r.status_code == 201, r.text
    assert admin.post("/api/threats/blocks", json={"address": "16.5.0.0/24", "reason": "again"}).status_code == 409
    assert admin.post("/api/threats/blocks", json={"address": "16.0.0.0/8", "reason": "too big"}).status_code == 422
    assert admin.post("/api/threats/blocks", json={"address": "192.168.174.0/24", "reason": "own router"}).status_code == 400
    assert login("sam").post("/api/threats/blocks", json={"address": "1.2.3.4", "reason": "support"}).status_code == 403
    blocks = admin.get("/api/threats/blocks").json()
    assert [b["address"] for b in blocks] == ["16.5.0.0/24"]
    assert admin.delete(f"/api/threats/blocks/{blocks[0]['id']}").status_code == 200
    assert admin.get("/api/threats/blocks").json() == []
    assert admin.get("/api/threats/summary").json()["failures"] == config.THREAT_FAILURES


def test_api_enforcement_change_request():
    d = router_device()
    admin = login("alice")
    r = admin.post(f"/api/threats/enforcement/{d['id']}")
    assert r.status_code == 201
    change = admin.get(f"/api/changes/{r.json()['change_id']}").json()
    assert "src-address-list=blocklist" in change["plan"] and change["status"] == "pending"
    row = next(x for x in admin.get("/api/threats/enforcement").json() if x["id"] == str(d["id"]))
    assert row["change_open"] is True
