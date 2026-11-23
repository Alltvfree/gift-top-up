"""Video encoder adapter, incident state machine, and API -- exercised against real ffmpeg/ffprobe
on small generated clips (not mocked), so a wrong CLI flag or parsing assumption actually fails."""
import subprocess

import pytest

from app import db
from app.adapters import encoder as enc
from app.services import encoders as svc
from tests.conftest import login


@pytest.fixture(scope="session")
def clips(tmp_path_factory):
    d = tmp_path_factory.mktemp("encoder-clips")
    files = {}
    specs = {
        "loud": '-f lavfi -i testsrc=size=160x120:rate=5:duration=1 -f lavfi -i "sine=frequency=1000:duration=1" -c:v libx264 -c:a aac',
        "silent": '-f lavfi -i testsrc=size=160x120:rate=5:duration=1 -f lavfi -i "anullsrc=duration=1" -c:v libx264 -c:a aac',
        "noaudio": '-f lavfi -i testsrc=size=160x120:rate=5:duration=1 -an -c:v libx264',
    }
    for name, args in specs.items():
        out = d / f"{name}.mp4"
        subprocess.run(f'ffmpeg -y -v error {args} "{out}"', shell=True, check=True)
        files[name] = str(out)
    return files


# ---------------------------------------------------------------- adapter, against real files
def test_probe_tracks_real_files(clips):
    loud = enc.probe_tracks(clips["loud"])
    assert loud == {"ok": True, "has_video": True, "has_audio": True, "video_codec": "h264", "audio_codec": "aac"}
    noaudio = enc.probe_tracks(clips["noaudio"])
    assert noaudio["ok"] and noaudio["has_video"] and not noaudio["has_audio"]
    missing = enc.probe_tracks(str(clips["loud"]) + ".missing")
    assert not missing["ok"] and "No such file" in missing["error"]


def test_audio_level_distinguishes_loud_from_silent(clips):
    loud = enc.audio_level(clips["loud"], duration_s=0.5)
    silent = enc.audio_level(clips["silent"], duration_s=0.5)
    assert loud["ok"] and loud["mean_db"] > -30  # clearly audible
    assert silent["ok"] and silent["mean_db"] < -80  # effectively silent
    no_audio_track = enc.audio_level(clips["noaudio"], duration_s=0.5)
    assert not no_audio_track["ok"] and no_audio_track["mean_db"] is None


def test_audio_level_missing_file_raises_nothing_bad():
    r = enc.audio_level("/no/such/file.mp4", duration_s=0.5)
    assert not r["ok"] and r["error"]


def test_build_rtsp_url():
    assert enc.build_rtsp_url("10.1.1.5", 554, "stream1", "admin", "pw") == "rtsp://admin:pw@10.1.1.5:554/stream1"
    assert enc.build_rtsp_url("10.1.1.5", 554, "/stream1", None, None) == "rtsp://10.1.1.5:554/stream1"


# ---------------------------------------------------------------- service: check() end to end
def test_check_pipeline_loud_silent_noaudio(clips, monkeypatch):
    for name, expect in (("loud", True), ("silent", False), ("noaudio", False)):
        monkeypatch.setattr(svc, "rtsp_url", lambda d, n=name: clips[n])
        r = svc.check({"settings": {"audio_threshold_db": -50}})
        assert r["video"]["ok"] is True
        assert r["audio"]["ok"] is expect, (name, r["audio"])
    monkeypatch.setattr(svc, "rtsp_url", lambda d: clips["noaudio"] + ".missing")
    r = svc.check({"settings": {}})
    assert r["video"]["ok"] is False and "no such file" in r["video"]["reason"].lower()
    assert r["audio"]["ok"] is False and r["audio"]["reason"] == "stream did not open"


# ---------------------------------------------------------------- service: incident state machine
def mk_encoder(admin, name="ENC-1"):
    return admin.post("/api/devices", json={"name": name, "vendor": "encoder", "role": "video_encoder",
                                             "management_ip": "10.50.0.1"}).json()["id"]


def seed_metric(sql, device_id, video_ok, audio_ok):
    sql("INSERT INTO device_metrics(device_id,reachable,extra) VALUES (%s,true,%s)",
        (device_id, __import__("json").dumps({"encoder": {"video": {"ok": video_ok}, "audio": {"ok": audio_ok}}})))


def test_incident_opens_only_after_consecutive_failures(admin, sql):
    did = mk_encoder(admin)
    device = db.row("SELECT * FROM devices WHERE id=%s", (did,))
    # default audio_fail_checks is 3: one or two failures alone must not open an incident
    seed_metric(sql, did, True, False)
    with db.connect() as conn:
        svc.evaluate(conn, device, {"video": {"ok": True}, "audio": {"ok": False, "reason": "silent"}})
        conn.commit()
    assert not sql("SELECT 1 FROM encoder_incidents WHERE device_id=%s", (did,))
    seed_metric(sql, did, True, False)
    with db.connect() as conn:
        svc.evaluate(conn, device, {"video": {"ok": True}, "audio": {"ok": False, "reason": "silent"}})
        conn.commit()
    assert not sql("SELECT 1 FROM encoder_incidents WHERE device_id=%s", (did,))  # 2 of 3, still nothing
    seed_metric(sql, did, True, False)
    with db.connect() as conn:
        svc.evaluate(conn, device, {"video": {"ok": True}, "audio": {"ok": False, "reason": "silent"}})
        conn.commit()
    rows = sql("SELECT kind, closed_at FROM encoder_incidents WHERE device_id=%s", (did,))
    assert rows == [("audio", None)]  # 3rd consecutive failure: now it opens


def test_video_failure_opens_immediately_default_threshold(admin, sql):
    did = mk_encoder(admin, "ENC-2")
    device = db.row("SELECT * FROM devices WHERE id=%s", (did,))
    seed_metric(sql, did, False, True)
    with db.connect() as conn:
        svc.evaluate(conn, device, {"video": {"ok": False, "reason": "no video track"}, "audio": {"ok": True}})
        conn.commit()
    assert sql("SELECT kind FROM encoder_incidents WHERE device_id=%s", (did,)) == [("video",)]


def test_incident_closes_on_recovery_and_does_not_duplicate(admin, sql):
    did = mk_encoder(admin, "ENC-3")
    device = db.row("SELECT * FROM devices WHERE id=%s", (did,))
    for _ in range(3):
        seed_metric(sql, did, True, False)
    with db.connect() as conn:
        svc.evaluate(conn, device, {"video": {"ok": True}, "audio": {"ok": False, "reason": "silent"}})
        conn.commit()
    assert sql("SELECT closed_at FROM encoder_incidents WHERE device_id=%s", (did,))[0][0] is None
    # a second open attempt while already open must not create a duplicate row (unique partial index)
    for _ in range(3):
        seed_metric(sql, did, True, False)
    with db.connect() as conn:
        svc.evaluate(conn, device, {"video": {"ok": True}, "audio": {"ok": False, "reason": "silent"}})
        conn.commit()
    assert sql("SELECT count(*) FROM encoder_incidents WHERE device_id=%s", (did,))[0][0] == 1
    seed_metric(sql, did, True, True)
    with db.connect() as conn:
        svc.evaluate(conn, device, {"video": {"ok": True}, "audio": {"ok": True}})
        conn.commit()
    row = sql("SELECT closed_at IS NOT NULL, closed_reason FROM encoder_incidents WHERE device_id=%s", (did,))[0]
    assert row == (True, "self_recovered")


# ---------------------------------------------------------------- restart gating
def test_restart_without_adapter_configured_raises():
    with pytest.raises(svc.RestartNotConfigured, match="No restart method configured"):
        svc.restart({"name": "x", "settings": {}})


def test_restart_adapter_present_but_unverified_raises():
    with pytest.raises(svc.RestartNotConfigured, match="not marked verified"):
        svc.restart({"name": "x", "settings": {"restart_adapter": {"type": "http", "url": "http://x/restart"}}})


def test_restart_verified_http_adapter_calls_it(monkeypatch):
    calls = []

    class FakeResp:
        status_code = 200
    monkeypatch.setattr("httpx.request", lambda method, url, **kw: calls.append((method, url, kw)) or FakeResp())
    r = svc.restart({"name": "x", "settings": {"restart_adapter": {
        "type": "http", "url": "http://10.1.1.5/cgi-bin/reboot", "method": "POST", "verified": True,
        "basic_auth": ["admin", "pw"]}}})
    assert r == {"ok": True, "detail": "HTTP 200"}
    assert calls[0][:2] == ("POST", "http://10.1.1.5/cgi-bin/reboot") and calls[0][2]["auth"] == ("admin", "pw")


def test_auto_recovery_never_fires_without_verified_adapter(admin, sql):
    did = admin.post("/api/devices", json={"name": "ENC-AUTO", "vendor": "encoder", "role": "video_encoder",
                                           "management_ip": "10.50.0.2",
                                           "settings": {"auto_recovery": True}}).json()["id"]
    device = db.row("SELECT * FROM devices WHERE id=%s", (did,))
    for _ in range(3):
        seed_metric(sql, did, True, False)
    with db.connect() as conn:
        svc.evaluate(conn, device, {"video": {"ok": True}, "audio": {"ok": False, "reason": "silent"}})
        conn.commit()
    row = sql("SELECT recovery_action FROM encoder_incidents WHERE device_id=%s", (did,))[0]
    assert row == (None,)  # incident opened, but no restart attempted: nothing verified to run


# ---------------------------------------------------------------- API
def test_overview_and_list(admin, sql):
    did = mk_encoder(admin, "ENC-API-1")
    r = admin.get("/api/encoders/overview")
    assert r.status_code == 200 and r.json()["total"] >= 1
    rows = admin.get("/api/encoders").json()
    assert any(x["id"] == did for x in rows)


def test_get_detail_and_incidents(admin, sql):
    did = mk_encoder(admin, "ENC-API-2")
    d = admin.get(f"/api/encoders/{did}").json()
    assert d["name"] == "ENC-API-2" and d["incidents"] == [] and d["recent_checks"] == []
    assert admin.get(f"/api/encoders/{did}/incidents").json() == []
    other = mk_encoder(admin, "ENC-API-2b")
    assert admin.get(f"/api/devices/{other}").status_code == 200  # sanity: still a plain device too
    assert admin.get("/api/encoders/00000000-0000-0000-0000-000000000000").status_code == 404


def test_test_endpoint_runs_a_real_check_and_opens_incident_eventually(admin, monkeypatch, clips, sql):
    did = mk_encoder(admin, "ENC-API-3")
    monkeypatch.setattr(svc, "rtsp_url", lambda d: clips["silent"])
    for _ in range(3):
        r = admin.post(f"/api/encoders/{did}/test")
        assert r.status_code == 200 and r.json()["video"]["ok"] is True
    assert r.json()["audio"]["ok"] is False
    rows = sql("SELECT kind FROM encoder_incidents WHERE device_id=%s", (did,))
    assert rows == [("audio",)]


def test_restart_requires_confirm_and_reports_not_configured(admin):
    did = mk_encoder(admin, "ENC-API-4")
    assert admin.post(f"/api/encoders/{did}/restart", json={}).status_code == 400
    r = admin.post(f"/api/encoders/{did}/restart", json={"confirm": True})
    assert r.status_code == 400 and "No restart method configured" in r.json()["detail"]


def test_recovery_toggle(admin):
    did = mk_encoder(admin, "ENC-API-5")
    assert admin.put(f"/api/encoders/{did}/recovery", json={"auto_recovery": True}).status_code == 200
    d = admin.get(f"/api/devices/{did}").json()
    assert d["settings"]["auto_recovery"] is True


def test_support_role_is_read_only(admin):
    did = mk_encoder(admin, "ENC-API-6")
    sam = login("sam")
    assert sam.get("/api/encoders/overview").status_code == 200
    assert sam.get(f"/api/encoders/{did}").status_code == 200
    assert sam.post(f"/api/encoders/{did}/test").status_code == 403
    assert sam.post(f"/api/encoders/{did}/restart", json={"confirm": True}).status_code == 403
    assert sam.put(f"/api/encoders/{did}/recovery", json={"auto_recovery": True}).status_code == 403
