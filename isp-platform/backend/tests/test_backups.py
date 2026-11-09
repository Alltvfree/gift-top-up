import contextlib
import gzip

from app import db
from app.security import decrypt_bytes
from app.services import backups


def make_device(admin, **extra):
    body = {"name": "BK-MT", "vendor": "mikrotik", "role": "island_router", "management_ip": "10.5.5.1",
            "credentials": {"username": "nms", "password": "pw-secret-1"}, **extra}
    return admin.post("/api/devices", json=body).json()["id"]


def test_capable_needs_a_real_login_not_just_snmp(admin):
    mt_login = db.row("SELECT * FROM devices WHERE id=%s", (make_device(admin),))
    assert backups.capable(mt_login)
    snmp_only = db.row("SELECT * FROM devices WHERE id=%s",
                       (admin.post("/api/devices", json={"name": "BK-SNMP", "vendor": "mikrotik", "role": "island_router",
                                                         "management_ip": "10.5.5.2", "credentials": {"snmp_community": "c"}}).json()["id"],))
    assert not backups.capable(snmp_only)
    olt = db.row("SELECT * FROM devices WHERE id=%s",
                (admin.post("/api/devices", json={"name": "BK-OLT", "vendor": "huawei", "role": "olt", "management_ip": "10.5.5.3",
                                                  "credentials": {"username": "root", "password": "pw-secret-2"}}).json()["id"],))
    assert backups.capable(olt)
    bare = db.row("SELECT * FROM devices WHERE id=%s",
                 (admin.post("/api/devices", json={"name": "BK-BARE", "vendor": "mikrotik", "role": "island_router"}).json()["id"],))
    assert not backups.capable(bare)


def test_take_stores_encrypted_prunes_old_and_records_failures(admin, monkeypatch, sql):
    did = make_device(admin)
    device = db.row("SELECT * FROM devices WHERE id=%s", (did,))
    monkeypatch.setattr(backups.dev, "mikrotik", contextlib.contextmanager(
        lambda d: (yield type("R", (), {"export_config": lambda self: "# config\n/ip address add address=10.5.5.1/24"})())))
    with db.connect() as conn:
        r = backups.take(conn, device, "manual", "alice")
        conn.commit()
    assert r["ok"] and r["filename"].startswith("BK-MT-") and r["filename"].endswith(".rsc")
    raw = sql("SELECT content_enc, ok, size_bytes, source, taken_by FROM device_backups WHERE id=%s", (r["id"],))[0]
    assert raw[1] is True and raw[3] == "manual" and raw[4] == "alice"
    assert "nowhere-in-plaintext" not in raw[0]  # sanity: column holds the Fernet token, not raw text
    plain = gzip.decompress(decrypt_bytes(raw[0])).decode()
    assert "ip address add" in plain and raw[2] == len(plain.encode())

    # a failing pull is stored too, not silently dropped
    def boom(d):
        raise RuntimeError("no route to host")
    monkeypatch.setattr(backups.dev, "mikrotik", contextlib.contextmanager(lambda d: (_ for _ in ()).throw(RuntimeError("no route to host"))))
    with db.connect() as conn:
        r2 = backups.take(conn, device, "manual", "alice")
        conn.commit()
    assert not r2["ok"] and "no route to host" in r2["error"]
    assert sql("SELECT ok, content_enc FROM device_backups WHERE device_id=%s AND ok=false", (did,))[0] == (False, None)

    # pruning: BACKUP_KEEP_PER_DEVICE is respected
    monkeypatch.setattr(backups.config, "BACKUP_KEEP_PER_DEVICE", 3)
    monkeypatch.setattr(backups.dev, "mikrotik", contextlib.contextmanager(
        lambda d: (yield type("R", (), {"export_config": lambda self: "/ip address add address=10.5.5.1/24"})())))
    with db.connect() as conn:
        for _ in range(5):
            backups.take(conn, device, "manual", "alice")
        conn.commit()
    assert sql("SELECT count(*) FROM device_backups WHERE device_id=%s", (did,))[0][0] == 3


def test_huawei_pulls_current_configuration(admin, monkeypatch, sql):
    did = admin.post("/api/devices", json={"name": "BK OLT #1", "vendor": "huawei", "role": "olt", "management_ip": "10.5.5.9",
                                           "credentials": {"username": "root", "password": "pw-secret-3"}}).json()["id"]
    device = db.row("SELECT * FROM devices WHERE id=%s", (did,))
    seen = []

    class FakeOLT:
        def query(self, cmd):
            seen.append(cmd)
            return "#\nsysname NEL-OLT\n#\nreturn"
    monkeypatch.setattr(backups.dev, "olt", contextlib.contextmanager(lambda d: (yield FakeOLT())))
    with db.connect() as conn:
        r = backups.take(conn, device, "manual", "alice")
        conn.commit()
    assert r["ok"] and seen == ["display current-configuration"]
    assert r["filename"].startswith("BK-OLT-1-") and r["filename"].endswith(".cfg")  # sanitised, no spaces/#


def test_snmp_only_mikrotik_gives_a_clear_error(admin):
    did = admin.post("/api/devices", json={"name": "BK-SNMP2", "vendor": "mikrotik", "role": "island_router",
                                           "management_ip": "10.5.5.4", "credentials": {"snmp_community": "c"}}).json()["id"]
    r = admin.post(f"/api/devices/{did}/backups")
    assert r.status_code == 400 and "SNMP" in r.json()["detail"]


def test_api_manual_backup_list_and_download(admin, monkeypatch):
    did = make_device(admin)
    monkeypatch.setattr(backups.dev, "mikrotik", contextlib.contextmanager(
        lambda d: (yield type("R", (), {"export_config": lambda self: "/ip address add address=10.5.5.1/24"})())))
    r = admin.post(f"/api/devices/{did}/backups")
    assert r.status_code == 201, r.text
    bid = r.json()["id"]
    listed = admin.get(f"/api/devices/{did}/backups").json()
    assert len(listed) == 1 and listed[0]["id"] == bid and "content_enc" not in listed[0]  # never exposed over JSON
    dl = admin.get(f"/api/devices/{did}/backups/{bid}/download")
    assert dl.status_code == 200 and "ip address add" in dl.text
    assert dl.headers["content-disposition"].startswith("attachment; filename=")

    other_id = admin.post("/api/devices", json={"name": "other", "vendor": "mikrotik", "role": "island_router"}).json()["id"]
    assert admin.get(f"/api/devices/{other_id}/backups/{bid}/download").status_code == 404  # wrong device

    from .conftest import login
    nina = login("nina")  # noc: has 'network' permission
    assert nina.get(f"/api/devices/{did}/backups/{bid}/download").status_code == 200
    bill = login("bill")  # billing: no 'network' permission
    assert bill.get(f"/api/devices/{did}/backups/{bid}/download").status_code == 403


def test_download_of_failed_attempt_is_404(admin, monkeypatch):
    did = make_device(admin)
    monkeypatch.setattr(backups.dev, "mikrotik", contextlib.contextmanager(lambda d: (_ for _ in ()).throw(RuntimeError("timeout"))))
    bid = admin.post(f"/api/devices/{did}/backups")
    assert bid.status_code == 502  # the API call itself fails...
    with db.connect() as conn:  # ...but the attempt is in history for the UI to show
        failed_id = conn.execute("SELECT id FROM device_backups WHERE device_id=%s AND ok=false", (did,)).fetchone()["id"]
    assert admin.get(f"/api/devices/{did}/backups/{failed_id}/download").status_code == 404


def test_scheduled_interval_default_override_and_disable(admin, monkeypatch):
    monkeypatch.setattr(backups.config, "BACKUP_INTERVAL_HOURS", 24)
    default_dev = make_device(admin)
    short_dev = make_device(admin, name="BK-SHORT", settings={"backup_interval_hours": 1})
    off_dev = make_device(admin, name="BK-OFF", settings={"backup_interval_hours": 0})
    bad_dev = make_device(admin, name="BK-BAD", settings={"backup_interval_hours": "not-a-number"})
    with db.connect() as conn:
        due_ids = {d["id"] for d in backups.due_for_scheduled(conn)}
    assert {default_dev, short_dev, bad_dev} <= {str(i) for i in due_ids} and off_dev not in {str(i) for i in due_ids}

    monkeypatch.setattr(backups.dev, "mikrotik", contextlib.contextmanager(
        lambda d: (yield type("R", (), {"export_config": lambda self: "/x"})())))
    with db.connect() as conn:
        for d in backups.due_for_scheduled(conn):
            if str(d["id"]) == default_dev:
                backups.take(conn, d, "scheduled")
        conn.commit()
    # just backed up, 24h interval: no longer due
    with db.connect() as conn:
        due_ids = {str(d["id"]) for d in backups.due_for_scheduled(conn)}
    assert default_dev not in due_ids and short_dev in due_ids  # 1h interval still due immediately


def test_after_change_hook_fires_and_can_be_disabled(admin, admin2, monkeypatch, sql):
    did = make_device(admin)
    monkeypatch.setattr(backups.dev, "mikrotik", contextlib.contextmanager(
        lambda d: (yield type("R", (), {"export_config": lambda self: "/x"})())))

    class FakeRos:
        def apply_with_commit_confirm(self, *a, **k):
            return "ok"
    monkeypatch.setattr("app.services.changes.dev.mikrotik", contextlib.contextmanager(lambda d: (yield FakeRos())))
    monkeypatch.setattr("app.services.changes.ping", lambda host: {"reachable": True})
    cid = admin.post("/api/changes", json={"device_id": did, "title": "change t", "kind": "mikrotik_script", "plan": "/ip x"}).json()["id"]
    admin2.post(f"/api/changes/{cid}/approve")
    admin.post(f"/api/changes/{cid}/apply")
    rows = sql("SELECT source, change_id FROM device_backups WHERE device_id=%s AND source='after_change'", (did,))
    assert rows and rows[0] == ("after_change", cid)

    # opted out device: no after-change backup
    did2 = make_device(admin, name="BK-NOAC", settings={"backup_after_change": False})
    cid2 = admin.post("/api/changes", json={"device_id": did2, "title": "change t2", "kind": "mikrotik_script", "plan": "/ip x"}).json()["id"]
    admin2.post(f"/api/changes/{cid2}/approve")
    admin.post(f"/api/changes/{cid2}/apply")
    assert not sql("SELECT 1 FROM device_backups WHERE device_id=%s", (did2,))


def test_mikrotik_export_falls_back_without_sensitive_policy():
    from app.adapters.mikrotik import RouterOS, RouterOSError
    calls = []

    class Stub(RouterOS):
        def __init__(self):
            pass

        def run_script(self, script):
            calls.append(script)
            if "show-sensitive" in script:
                raise RouterOSError("HTTP 400: no such item")
            return "/export output"
    assert Stub().export_config() == "/export output"
    assert calls == ["/export show-sensitive terse", "/export terse"]


def test_run_scheduled_end_to_end(admin, monkeypatch, sql):
    did = make_device(admin)
    monkeypatch.setattr(backups.config, "BACKUP_INTERVAL_HOURS", 24)
    monkeypatch.setattr(backups.dev, "mikrotik", contextlib.contextmanager(
        lambda d: (yield type("R", (), {"export_config": lambda self: "/x"})())))
    out = backups.run_scheduled()
    assert out["attempted"] >= 1 and out["ok"] >= 1
    assert sql("SELECT source FROM device_backups WHERE device_id=%s", (did,))[0][0] == "scheduled"
    # second run right after: that device is no longer due
    backups.run_scheduled()
    assert sql("SELECT count(*) FROM device_backups WHERE device_id=%s AND source='scheduled'", (did,))[0][0] == 1


def test_capable_tolerates_corrupt_credentials():
    assert not backups.capable({"vendor": "mikrotik", "credentials_enc": None})
