"""Bulk-restore an OLT's remembered ONTs onto its replacement (disaster recovery)."""
import hashlib

import psycopg
import pytest
from psycopg.rows import dict_row

from app import config
from tests.conftest import login


def serial_for(username: str) -> str:
    return hashlib.md5(username.encode()).hexdigest()[:16].upper()


def mk_subscriber(admin, suffix):
    username = f"restore.{suffix}"
    r = admin.post("/api/subscribers", json={"full_name": f"Restore Test {suffix}", "pppoe_username": username})
    assert r.status_code == 201, r.text
    return {**r.json(), "pppoe_username": username}


def mk_olt(admin, name):
    return admin.post("/api/devices", json={"name": name, "vendor": "huawei", "role": "olt", "management_ip": f"10.44.0.{len(name)}"}).json()["id"]


@pytest.fixture
def two_olts(admin):
    with psycopg.connect(config.DATABASE_URL, row_factory=dict_row, autocommit=True) as c:
        c.execute("DELETE FROM devices WHERE name IN ('OLD-OLT','NEW-OLT','OLD-OLT2')")
    return mk_olt(admin, "OLD-OLT"), mk_olt(admin, "NEW-OLT")


def provision(admin, olt_id, sub, port=3, slot=1, line=10, service=20, vlan=100):
    r = admin.post(f"/api/olt/{olt_id}/provision", json={
        "subscriber_id": sub["id"], "serial": serial_for(sub["pppoe_username"]),
        "frame": 0, "slot": slot, "port": port, "line_profile_id": line, "service_profile_id": service, "vlan": vlan})
    assert r.status_code == 201, r.text
    return r.json()


def test_restore_preview_and_apply_builds_one_change(admin, two_olts, sql):
    old_id, new_id = two_olts
    sub = mk_subscriber(admin, "1")
    provision(admin, old_id, sub)

    prev = admin.get(f"/api/olt/{old_id}/restore-preview", params={"new_olt_id": new_id})
    assert prev.status_code == 200, prev.text
    assert prev.json()["skipped"] == [] and len(prev.json()["ready"]) == 1
    ready0 = prev.json()["ready"][0]
    assert ready0["account_number"] == sub["account_number"] and ready0["frame"] == 0 and ready0["slot"] == 1 and ready0["port"] == 3

    r = admin.post(f"/api/olt/{old_id}/restore-into/{new_id}", json={})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["restored"] == 1 and body["skipped"] == []
    cid = body["change_id"]

    ch = admin.get(f"/api/changes/{cid}").json()
    assert ch["kind"] == "huawei_cli"
    assert "OLD-OLT" in ch["title"] and "NEW-OLT" in ch["title"] and "1 ONTs" in ch["title"]
    assert f'sn-auth "{ready0["serial"]}"' in ch["plan"] and f'username "{sub["pppoe_username"]}"' in ch["plan"]
    assert "ont delete" in ch["rollback"]  # rollback present

    new_rows = sql("SELECT serial, ont_id, frame, slot, port, subscriber_id FROM onts WHERE olt_device_id=%s", (new_id,))
    assert len(new_rows) == 1 and new_rows[0][0] == ready0["serial"]
    old_rows = sql("SELECT serial FROM onts WHERE olt_device_id=%s", (old_id,))
    assert len(old_rows) == 1  # the old OLT's own history row is untouched, not moved


def test_ont_id_reassigned_on_new_olt_not_copied(admin, two_olts, sql):
    old_id, new_id = two_olts
    # occupy ont_id 0 on the NEW olt at the same port first, so the restored ONT cannot reuse it
    sub0 = mk_subscriber(admin, "occ")
    provision(admin, new_id, sub0, port=3, slot=1)
    sub1 = mk_subscriber(admin, "2")
    provision(admin, old_id, sub1, port=3, slot=1)

    r = admin.post(f"/api/olt/{old_id}/restore-into/{new_id}", json={})
    assert r.status_code == 201, r.text
    new_ont_id = sql("SELECT ont_id FROM onts WHERE olt_device_id=%s AND subscriber_id=%s", (new_id, sub1["id"]))[0][0]
    assert new_ont_id != 0  # 0 was taken, so a different slot had to be picked


def test_skips_ont_without_subscriber_link(admin, two_olts, sql):
    old_id, new_id = two_olts
    sql("""INSERT INTO onts(olt_device_id,frame,slot,port,ont_id,serial,line_profile_id,service_profile_id,vlan)
          VALUES (%s,0,2,4,7,'4857544100000001',10,20,100)""", (old_id,))
    prev = admin.get(f"/api/olt/{old_id}/restore-preview", params={"new_olt_id": new_id}).json()
    assert prev["ready"] == [] and len(prev["skipped"]) == 1 and "No subscriber" in prev["skipped"][0]["reason"]

    r = admin.post(f"/api/olt/{old_id}/restore-into/{new_id}", json={})
    assert r.status_code == 400 and "No subscriber" in r.json()["detail"]


def test_skips_subscriber_without_radius_password(admin, two_olts, sql):
    old_id, new_id = two_olts
    sub = mk_subscriber(admin, "3")
    provision(admin, old_id, sub)
    sql("DELETE FROM radcheck WHERE username=%s AND attribute='Cleartext-Password'", (sub["pppoe_username"],))
    prev = admin.get(f"/api/olt/{old_id}/restore-preview", params={"new_olt_id": new_id}).json()
    assert prev["ready"] == [] and "RADIUS password" in prev["skipped"][0]["reason"]


def test_one_bad_ont_does_not_block_the_rest(admin, two_olts, sql):
    old_id, new_id = two_olts
    good = mk_subscriber(admin, "4")
    provision(admin, old_id, good, port=1)
    bad = mk_subscriber(admin, "5")
    provision(admin, old_id, bad, port=2)
    sql("DELETE FROM radcheck WHERE username=%s AND attribute='Cleartext-Password'", (bad["pppoe_username"],))

    r = admin.post(f"/api/olt/{old_id}/restore-into/{new_id}", json={})
    assert r.status_code == 201, r.text
    assert r.json()["restored"] == 1 and len(r.json()["skipped"]) == 1
    assert sql("SELECT count(*) FROM onts WHERE olt_device_id=%s", (new_id,))[0][0] == 1


def test_serials_filter_restricts_the_batch(admin, two_olts):
    old_id, new_id = two_olts
    a, b = mk_subscriber(admin, "6"), mk_subscriber(admin, "7")
    provision(admin, old_id, a, port=1)
    provision(admin, old_id, b, port=2)
    serial_a = admin.get(f"/api/olt/{old_id}/restore-preview", params={"new_olt_id": new_id}).json()["ready"]
    want = next(x["serial"] for x in serial_a if x["account_number"] == a["account_number"])
    r = admin.post(f"/api/olt/{old_id}/restore-into/{new_id}", json={"serials": [want]})
    assert r.json()["restored"] == 1


def test_full_port_reports_no_free_slot(admin, two_olts, sql):
    old_id, new_id = two_olts
    for i in range(128):
        sql("""INSERT INTO onts(olt_device_id,frame,slot,port,ont_id,serial) VALUES (%s,0,5,9,%s,%s)""",
            (new_id, i, f"4857544{i:09d}"[:16].upper()))
    sub = mk_subscriber(admin, "8")
    provision(admin, old_id, sub, slot=5, port=9)
    prev = admin.get(f"/api/olt/{old_id}/restore-preview", params={"new_olt_id": new_id}).json()
    assert prev["ready"] == [] and "No free ONT slot" in prev["skipped"][0]["reason"]


def test_same_olt_rejected_and_non_olt_404s(admin, two_olts):
    old_id, new_id = two_olts
    assert admin.get(f"/api/olt/{old_id}/restore-preview", params={"new_olt_id": old_id}).status_code == 400
    assert admin.post(f"/api/olt/{old_id}/restore-into/{old_id}", json={}).status_code == 400
    mt = admin.post("/api/devices", json={"name": "NOT-OLT", "vendor": "mikrotik", "role": "island_router"}).json()["id"]
    assert admin.get(f"/api/olt/{old_id}/restore-preview", params={"new_olt_id": mt}).status_code == 404
    assert admin.post(f"/api/olt/{mt}/restore-into/{old_id}", json={}).status_code == 404


def test_support_role_cannot_restore(admin, two_olts):
    old_id, new_id = two_olts
    sam = login("sam")  # support: read-only
    assert sam.get(f"/api/olt/{old_id}/restore-preview", params={"new_olt_id": new_id}).status_code == 403
    assert sam.post(f"/api/olt/{old_id}/restore-into/{new_id}", json={}).status_code == 403


def test_gemport_is_honoured(admin, two_olts):
    old_id, new_id = two_olts
    sub = mk_subscriber(admin, "9")
    provision(admin, old_id, sub)
    r = admin.post(f"/api/olt/{old_id}/restore-into/{new_id}", json={"gemport": 42})
    plan = admin.get(f"/api/changes/{r.json()['change_id']}").json()["plan"]
    assert "gemport 42" in plan
