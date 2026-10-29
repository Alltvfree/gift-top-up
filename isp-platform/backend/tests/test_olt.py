from contextlib import contextmanager
from pathlib import Path

import psycopg
import pytest
from psycopg.rows import dict_row

from app import config
from app.adapters import huawei
from app.services import devices as dev
from app.services import monitor
from tests.conftest import login

REAL = (Path(__file__).parent / "fixtures" / "ma5608t_display_ont_info_0_all.txt").read_text()
OPTICAL = "  Rx optical power(dBm)                  : {rx}\n  Temperature(C)                         : 45\n  OLT Rx ONT optical power(dBm)          : -22.10\n"


class FakeOLT:
    """Stands in for HuaweiOLT: same methods, canned answers, records commands."""
    sent = []

    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def ont_list_frame(self, frame=0):
        return huawei.parse_ont_info_table(REAL)

    def optical_many(self, onts):
        # vary the signal so every bucket appears
        levels = [-19.5, -25.8, -27.9, -30.2]
        return {(o["frame"], o["slot"], o["port"], o["ont_id"]): huawei.parse_optical(OPTICAL.format(rx=levels[i % 4]))
                for i, o in enumerate(onts)}

    def autofind(self):
        return huawei.parse_autofind("""----\n   F/S/P               : 0/1/3\n   Ont SN              : 48575443AAAA0001 (HWTC-AAAA0001)\n----""")

    def on_board(self, frame, slot, command, confirm=False):
        FakeOLT.sent.append((frame, slot, command, confirm))
        return "OK" if "optical" not in command else OPTICAL.format(rx=-20.0)

    def ont_config(self, f, s, p, o):
        return f"> display current-configuration ont {f}/{s}/{p} {o}\n ont add {p} {o} sn-auth ..."


@pytest.fixture
def olt(monkeypatch):
    @contextmanager
    def fake(device):
        yield FakeOLT()
    monkeypatch.setattr(dev, "olt", fake)
    FakeOLT.sent = []
    with psycopg.connect(config.DATABASE_URL, row_factory=dict_row, autocommit=True) as c:
        c.execute("DELETE FROM devices WHERE name IN ('NEY-OLT','NEY-MT')")
        nas = c.execute("INSERT INTO devices(name,vendor,role,management_ip,status) VALUES ('NEY-MT','mikrotik','island_router','10.20.0.1','online') RETURNING id").fetchone()["id"]
        d = c.execute("""INSERT INTO devices(name,vendor,role,management_ip,model,parent_device_id,status)
                         VALUES ('NEY-OLT','huawei','olt','10.11.104.2','MA5608T',%s,'online') RETURNING *""", (nas,)).fetchone()
        r = monitor.poll_olt(d)
        monitor.store(c, d, {"reachable": True, "latency_ms": 2, "packet_loss_pct": 0,
                             "extra": {"onts": r["onts"], "autofind": r["autofind"]}})
    return d


def test_poll_stores_everything(olt):
    with psycopg.connect(config.DATABASE_URL, row_factory=dict_row) as c:
        n = c.execute("SELECT count(*) AS n, count(description) AS d, count(rx_power_dbm) AS rx FROM onts WHERE olt_device_id=%s",
                      (olt["id"],)).fetchone()
        assert n == {"n": 111, "d": 111, "rx": 50}          # 50 online ONTs have a reading; offline ones none
        row = c.execute("SELECT * FROM onts WHERE olt_device_id=%s AND slot=1 AND port=4 AND ont_id=100", (olt["id"],)).fetchone()
        assert row["serial"] == "485754436EF52196" and row["run_state"] == "offline" and row["control"] == "active"


def test_overview_and_summary(olt):
    a = login("alice")
    ov = next(r for r in a.get("/api/olt/overview").json() if r["id"] == str(olt["id"]))
    assert (ov["total"], ov["online"], ov["waiting"], ov["nas_name"]) == (111, 50, 1, "NEY-MT")
    sm = a.get(f"/api/olt/{olt['id']}/summary").json()
    c = sm["counts"]
    assert (c["total"], c["online"], c["offline"]) == (111, 50, 61)
    assert c["good"] + c["acceptable"] + c["weak"] + c["bad"] == 50 and min(c["good"], c["acceptable"], c["weak"], c["bad"]) > 0
    assert sm["nas"]["name"] == "NEY-MT" and sm["autofind"][0]["serial"] == "48575443AAAA0001"
    assert {p["port"]: p["total"] for p in sm["ports"]}["0/1/4"] == 28


def test_ont_list_filters_and_paging(olt):
    a = login("sam")                                       # read-only role can browse
    base = f"/api/olt/onts?olt_id={olt['id']}"
    assert a.get(base).json()["total"] == 111
    assert a.get(base + "&port=0/1/0").json()["total"] == 31
    assert a.get(base + "&port=0/1/0&status=online").json()["total"] == 15
    weak = a.get(base + "&signal=weak").json()
    assert weak["total"] > 0 and all(r["signal"] == "weak" and -29 <= r["rx_power_dbm"] < -27 for r in weak["rows"])
    hit = a.get(base + "&q=HOUSE-053").json()
    assert hit["total"] == 1 and hit["rows"][0]["description"].startswith("HOUSE-053")
    page2 = a.get(base + "&limit=100&offset=100").json()
    assert page2["total"] == 111 and len(page2["rows"]) == 11
    worst = a.get(base + "&sort=signal&status=online&limit=1").json()["rows"][0]
    assert worst["rx_power_dbm"] == pytest.approx(-30.2)
    assert a.get(base + "&port=bogus").status_code == 400


def test_ont_actions_send_exact_commands_and_audit(olt, sql):
    a, support = login("nina"), login("sam")
    ont = a.get(f"/api/olt/onts?olt_id={olt['id']}&q=485754435EF8859B").json()["rows"][0]   # 0/1/0 ONT 4
    assert support.post(f"/api/olt/onts/{ont['id']}/reboot").status_code == 403
    assert a.post(f"/api/olt/onts/{ont['id']}/reboot").status_code == 200
    assert a.post(f"/api/olt/onts/{ont['id']}/state", json={"active": False}).status_code == 200
    assert FakeOLT.sent == [(0, 1, "ont reset 0 4", True), (0, 1, "ont deactivate 0 4", True)]
    assert a.get(f"/api/olt/onts?olt_id={olt['id']}&q=485754435EF8859B").json()["rows"][0]["control"] == "deactivated"
    assert "current-configuration ont 0/1/0 4" in a.get(f"/api/olt/onts/{ont['id']}/config").json()["text"]
    sig = a.get(f"/api/olt/onts/{ont['id']}/signal").json()
    assert sig["rx_power_dbm"] == -20.0
    actions = {r[0] for r in sql("SELECT action FROM audit_events WHERE target_id=%s", (ont["id"],))}
    assert {"ont.reboot", "ont.deactivate", "ont.read_config"} <= actions
