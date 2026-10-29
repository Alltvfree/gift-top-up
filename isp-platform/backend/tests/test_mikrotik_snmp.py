from app.adapters.mikrotik_snmp import MikroTikSNMP, SnmpError, parse

# Shaped like `snmpget/snmpbulkwalk -v2c -Onqet` from a hAP ac on RouterOS 6.49
OUT = {
    "snmpget": '''.1.3.6.1.2.1.1.1.0 "RouterOS RB962UiGS-5HacT2HnT"
.1.3.6.1.2.1.1.3.0 123456789
.1.3.6.1.4.1.14988.1.1.4.4.0 "6.49.21"
.1.3.6.1.4.1.14988.1.1.7.8.0 No Such Object available on this agent at this OID''',
    "1.3.6.1.2.1.25.3.3.1.2": ".1.3.6.1.2.1.25.3.3.1.2.1 10\n.1.3.6.1.2.1.25.3.3.1.2.2 20",
    "1.3.6.1.2.1.25.2.3.1": '''.1.3.6.1.2.1.25.2.3.1.3.65536 "main memory"
.1.3.6.1.2.1.25.2.3.1.3.131072 "system disk"
.1.3.6.1.2.1.25.2.3.1.5.65536 131072
.1.3.6.1.2.1.25.2.3.1.5.131072 16384
.1.3.6.1.2.1.25.2.3.1.6.65536 32768
.1.3.6.1.2.1.25.2.3.1.6.131072 9000''',
    "1.3.6.1.2.1.2.2.1.2": '''.1.3.6.1.2.1.2.2.1.2.1 "ether1"
.1.3.6.1.2.1.2.2.1.2.2 "ether2-olt"
.1.3.6.1.2.1.2.2.1.2.3 "ether3"
.1.3.6.1.2.1.2.2.1.2.9 "l2tp-out1"
.1.3.6.1.2.1.2.2.1.2.20 "<pppoe-HDNL0094>"
.1.3.6.1.2.1.2.2.1.2.21 "<pppoe-HDNL0117>"''',
    "1.3.6.1.2.1.2.2.1.3": '''.1.3.6.1.2.1.2.2.1.3.1 6
.1.3.6.1.2.1.2.2.1.3.2 6
.1.3.6.1.2.1.2.2.1.3.3 6
.1.3.6.1.2.1.2.2.1.3.9 23
.1.3.6.1.2.1.2.2.1.3.20 23
.1.3.6.1.2.1.2.2.1.3.21 23''',
    "1.3.6.1.2.1.2.2.1.7": "\n".join(f".1.3.6.1.2.1.2.2.1.7.{i} {a}" for i, a in ((1, 1), (2, 1), (3, 2), (9, 1), (20, 1), (21, 1))),
    "1.3.6.1.2.1.2.2.1.8": "\n".join(f".1.3.6.1.2.1.2.2.1.8.{i} {o}" for i, o in ((1, 1), (2, 2), (3, 2), (9, 1), (20, 1), (21, 1))),
}


def fake_runner(args, timeout):
    assert args[1:4] == ["-v2c", "-c", "s3cret"]
    return OUT["snmpget"] if args[0] == "snmpget" else OUT[args[-1]]


def test_poll_routeros6():
    r = MikroTikSNMP("10.0.0.1", "s3cret", runner=fake_runner).poll()
    assert r["uptime_s"] == 1234567 and r["cpu_load_pct"] == 15.0 and r["mem_used_pct"] == 25.0
    assert r["extra"]["version"] == "6.49.21" and r["extra"]["board"] == "RB962UiGS-5HacT2HnT"
    assert r["extra"]["pppoe_active"] == 2
    assert r["extra"]["interfaces_down"] == ["ether2-olt"]  # ether3 is disabled, l2tp/pppoe not watched


def test_no_answer():
    import pytest
    with pytest.raises(SnmpError):
        MikroTikSNMP("10.0.0.1", "s3cret", runner=lambda a, t: "").poll()
    assert parse('.1.3.6.1.2.1.1.5.0 "a b"\nTimeout: No Response') == {"1.3.6.1.2.1.1.5.0": "a b"}


def test_monitor_uses_snmp_when_no_login(admin, monkeypatch):
    from app.services import monitor
    did = admin.post("/api/devices", json={"name": "SNMP-ONLY", "vendor": "mikrotik", "role": "island_router", "management_ip": "10.0.0.1",
                                           "credentials": {"snmp_community": "s3cret"}}).json()["id"]
    from app import db
    device = db.row("SELECT * FROM devices WHERE id=%s", (did,))
    monkeypatch.setattr(monitor, "ping", lambda host: {"reachable": True, "latency_ms": 3.0, "packet_loss_pct": 0.0})
    monkeypatch.setattr(monitor, "MikroTikSNMP", lambda host, community: MikroTikSNMP(host, community, runner=fake_runner))
    m = monitor.poll_device(device)
    assert m["extra"]["pppoe_active"] == 2 and m["uptime_s"] == 1234567
    assert m["extra"]["via"] == "snmp" and m["error"] == "interfaces down: ether2-olt"
