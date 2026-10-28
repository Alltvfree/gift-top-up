import socket
import threading

import pytest

from app.adapters import huawei, radius_coa
from app.adapters.ping import parse_ping
from app.services import firewall

ISLAND = dict(role="island_router", mgmt_networks=["10.255.0.0/24"], nms_addresses=["10.255.0.10"],
              uplink_interfaces=["sfp1"], customer_interfaces=["vlan100-olt"], customer_pools=["100.64.16.0/20"],
              radius_servers=["10.0.0.5"], portal_ip="10.0.0.80", snmp_community="n0c-Read-7x",
              radius_secret="S3cret-island-01", local_address="100.64.16.1")


def test_island_firewall_contents():
    s = firewall.generate(firewall.FirewallInput(**ISLAND))
    assert "set telnet disabled=yes" in s and "set ssh address=10.255.0.0/24" in s
    assert "fasttrack" not in s.replace("No FastTrack", "").replace("FastTrack -", "")
    assert "src-address-list=!customer-pools" in s  # BCP38
    assert "dst-port=23,2323,7547" in s  # protect ONTs
    assert "psd=21,3s,3,1" in s
    assert "/radius incoming set accept=yes port=3799" in s
    assert 'secret="S3cret-island-01"' in s
    assert "authentication-port=1812 accounting-port=1813" in s
    moved = firewall.generate(firewall.FirewallInput(**{**ISLAND, "radius_auth_port": 11812, "radius_acct_port": 11813}))
    assert "authentication-port=11812 accounting-port=11813" in moved
    assert "interface-list=CUSTOMER" in s
    lines = [ln for ln in s.splitlines() if "chain=input" in ln]
    assert lines[-1].startswith("add chain=input action=drop")
    # management accept comes before the final drop
    assert any("SSH/Winbox from mgmt" in ln for ln in lines[:-1])


def test_core_firewall_has_bogons():
    s = firewall.generate(firewall.FirewallInput(role="core_router", mgmt_networks=["10.255.0.0/24"], nms_addresses=[],
                                                 uplink_interfaces=["ether1-isp"], backhaul_interfaces=["sfp-plus1"]))
    assert "list=bogons" in s and "in-interface-list=INTERNET src-address-list=bogons" in s
    assert "/ppp profile" not in s
    assert "protocol=ospf in-interface-list=UPLINK" not in s  # never OSPF toward the internet
    assert "protocol=ospf in-interface-list=BACKHAUL" in s
    assert "dst-port=23,2323,7547,135,139,445 in-interface-list=UPLINK out-interface-list=BACKHAUL" in s
    assert "dst-port=53 in-interface-list=BACKHAUL" in s


@pytest.mark.parametrize("bad", [
    {"uplink_interfaces": ['sfp1"; /system reset-configuration']},
    {"mgmt_networks": []},
    {"mgmt_networks": ["10.0.0.0/8; /user add"]},
    {"snmp_community": "public"},
    {"radius_secret": 'x" ; /system reboot'},
])
def test_firewall_rejects_bad_input(bad):
    with pytest.raises(ValueError):
        firewall.generate(firewall.FirewallInput(**{**ISLAND, **bad}))


def test_audit_flags_weak_router():
    snap = {
        "services": [{"name": "telnet", "disabled": "false"}, {"name": "winbox", "disabled": "false", "address": ""}],
        "users": [{"name": "admin", "disabled": "false"}],
        "dns": {"allow-remote-requests": "true"},
        "filter": [{"chain": "forward", "action": "fasttrack-connection"}],
        "snmp_communities": [{"name": "public", "disabled": "false"}],
        "socks": {"enabled": "true"}, "resource": {"version": "6.49.10 (long-term)"},
    }
    checks = {f["check"] for f in firewall.audit(snap)}
    assert {"service:telnet", "service:winbox:open", "user:admin", "dns:open-resolver", "firewall:input-empty",
            "firewall:fasttrack", "snmp:default-community", "socks:enabled", "routeros:v6"} <= checks


AUTOFIND = """
   ----------------------------------------------------------------------------
   Number              : 1
   F/S/P               : 0/1/3
   Ont SN              : 48575443A1B2C3D4 (HWTC-A1B2C3D4)
   VendorID            : HWTC
   Ont EquipmentID     : HG8546M
   Ont autofind time   : 2026-10-27 10:12:13+05:00
   ----------------------------------------------------------------------------
   Number              : 2
   F/S/P               : 0/1/7
   Ont SN              : 485754431122AABB (HWTC-1122AABB)
   Ont EquipmentID     : EG8145V5
   ----------------------------------------------------------------------------
"""
ONT_TABLE = """
  -----------------------------------------------------------------------------
  F/S/P   ONT         SN         Control     Run      Config   Match    Protect
          ID                     flag        state    state    state    side
  -----------------------------------------------------------------------------
  0/ 1/0    0  48575443A1B2C3D4  active      online   normal   match    no
  0/ 1/0    1  4857544311223344  active      offline  initial  initial  no
  -----------------------------------------------------------------------------
"""
OPTICAL = """
  ONU NNI port ID                        : 0
  Rx optical power(dBm)                  : -19.62
  Tx optical power(dBm)                  : 2.31
  Temperature(C)                         : 48
  OLT Rx ONT optical power(dBm)          : -21.40
"""


def test_huawei_parsers():
    af = huawei.parse_autofind(AUTOFIND)
    assert [(a["port"], a["serial"], a["equipment_id"]) for a in af] == [(3, "48575443A1B2C3D4", "HG8546M"), (7, "485754431122AABB", "EG8145V5")]
    t = huawei.parse_ont_info_table(ONT_TABLE)
    assert [(o["slot"], o["ont_id"], o["run_state"]) for o in t] == [(1, 0, "online"), (1, 1, "offline")]
    assert huawei.parse_optical(OPTICAL) == {"rx_power_dbm": -19.62, "tx_power_dbm": 2.31, "olt_rx_power_dbm": -21.4, "temperature_c": 48.0}


def test_huawei_provision_builder_and_validation():
    apply, rollback = huawei.build_ont_provision(
        frame=0, slot=1, port=3, ont_id=5, serial="48575443a1b2c3d4", line_profile_id=10, service_profile_id=10,
        vlan=100, gemport=1, description="A1001", pppoe_username="cust.one", pppoe_password="Abc123xyz")
    assert 'ont add 3 5 sn-auth "48575443A1B2C3D4"' in apply[1]
    assert 'user-account username "cust.one" password "Abc123xyz"' in apply[2]
    assert apply[-1].startswith("service-port vlan 100 gpon 0/1/3 ont 5")
    assert rollback[0] == "undo service-port port 0/1/3 ont 5"
    with pytest.raises(ValueError):
        huawei.build_ont_provision(frame=0, slot=1, port=3, ont_id=5, serial="48575443A1B2C3D4", line_profile_id=10,
                                   service_profile_id=10, vlan=100, gemport=1, description='x"\nreboot',
                                   pppoe_username="u", pppoe_password="Abc123xyz")


def test_ping_parser():
    out = "3 packets transmitted, 3 received, 0% packet loss, time 2003ms\nrtt min/avg/max/mdev = 1.1/12.5/30.2/1.0 ms"
    assert parse_ping(out) == {"reachable": True, "latency_ms": 12.5, "packet_loss_pct": 0.0}
    assert parse_ping("3 packets transmitted, 0 received, 100% packet loss")["reachable"] is False


def test_coa_disconnect_roundtrip():
    """Fake NAS validates the request authenticator and answers Disconnect-ACK."""
    secret = b"testing123"
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    seen = {}

    def nas():
        data, addr = sock.recvfrom(4096)
        import hashlib
        seen["valid"] = hashlib.md5(data[:4] + b"\x00" * 16 + data[20:] + secret).digest() == data[4:20]
        seen["code"] = data[0]
        seen["has_user"] = b"cust.one" in data
        reply_attrs = b""
        header = bytes([radius_coa.DISCONNECT_ACK, data[1]]) + (20).to_bytes(2, "big")
        auth = hashlib.md5(header + data[4:20] + reply_attrs + secret).digest()
        sock.sendto(header + auth + reply_attrs, addr)

    t = threading.Thread(target=nas)
    t.start()
    assert radius_coa.send("127.0.0.1", "testing123", port=port, username="cust.one", session_id="81a00001",
                           framed_ip="100.64.16.20") == "ack"
    t.join()
    sock.close()
    assert seen == {"valid": True, "code": 40, "has_user": True}


def test_change_workflow_four_eyes(admin, admin2):
    dev = admin.post("/api/devices", json={"name": "HDH-MT", "vendor": "mikrotik", "role": "island_router",
                                           "management_ip": "10.1.1.1",
                                           "credentials": {"username": "nms", "password": "pw-secret-1"}}).json()["id"]
    d = admin.get(f"/api/devices/{dev}").json()
    assert d["has_credentials"] is True and "credentials_enc" not in d and "pw-secret-1" not in str(d)
    r = admin.post("/api/security/firewall", json={**ISLAND, "device_id": dev})
    assert r.status_code == 200, r.text
    cid = r.json()["change_id"]
    assert admin.post(f"/api/changes/{cid}/apply").status_code == 409  # not approved
    assert admin.post(f"/api/changes/{cid}/approve").status_code == 403  # own change
    assert admin2.post(f"/api/changes/{cid}/approve").status_code == 200
    assert admin.get(f"/api/changes/{cid}").json()["status"] == "approved"
    # Huawei CLI cannot target a MikroTik
    bad = admin.post("/api/changes", json={"device_id": dev, "title": "oops", "kind": "huawei_cli", "plan": "display version"})
    assert bad.status_code == 400


def test_monitor_store_alerts_and_rollup(admin, sql):
    from app import db
    from app.services import monitor
    isl = admin.post("/api/islands", json={"code": "MON1", "name": "Monitor isle"}).json()["id"]
    d1 = admin.post("/api/devices", json={"name": "m1", "vendor": "mikrotik", "role": "island_router", "island_id": isl}).json()["id"]
    d2 = admin.post("/api/devices", json={"name": "o1", "vendor": "huawei", "role": "olt", "island_id": isl}).json()["id"]
    dev1 = db.row("SELECT * FROM devices WHERE id=%s", (d1,))
    dev2 = db.row("SELECT * FROM devices WHERE id=%s", (d2,))
    with db.connect() as conn:
        monitor.store(conn, dev1, {"reachable": True, "latency_ms": 5, "packet_loss_pct": 0, "extra": {}})
        monitor.store(conn, dev2, {"reachable": False, "packet_loss_pct": 100, "extra": {}})
        monitor.rollup(conn)
    assert sql("SELECT status FROM islands WHERE id=%s", (isl,)) == [("degraded",)]
    assert sql("SELECT kind FROM alerts WHERE device_id=%s AND resolved_at IS NULL", (d2,)) == [("unreachable",)]
    with db.connect() as conn:
        monitor.store(conn, dev2, {"reachable": True, "latency_ms": 3, "packet_loss_pct": 0,
                                   "extra": {"onts": [{"frame": 0, "slot": 1, "port": 0, "ont_id": 0, "serial": "48575443A1B2C3D4",
                                                       "run_state": "online", "rx_power_dbm": -29.1}]}})
        monitor.rollup(conn)
    assert sql("SELECT status FROM islands WHERE id=%s", (isl,)) == [("online",)]
    assert sql("SELECT kind FROM alerts WHERE device_id=%s AND resolved_at IS NULL", (d2,)) == [("ont_low_rx:48575443A1B2C3D4",)]
    assert sql("SELECT rx_power_dbm FROM onts WHERE serial='48575443A1B2C3D4'") == [(-29.1,)]
