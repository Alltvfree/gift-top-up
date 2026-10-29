import contextlib
import socket

import pytest

from app.adapters.ping import tcp_ping
from app.services import olt_access


def test_plan_picks_free_port_and_reuses_own():
    rules = [{".id": "*1", "chain": "dstnat", "dst-port": "22101", "comment": "customer camera"},
             {".id": "*2", "chain": "dstnat", "dst-port": "22102-22103", "comment": "other"}]
    port, old, script = olt_access.plan(rules, "olt-a", "192.168.174.40", "10.11.104.2", "172.17.205.188")
    assert port == 22104 and old == []
    assert "dst-address=192.168.174.40 dst-port=22104 to-addresses=10.11.104.2 to-ports=22" in script
    assert "src-address=172.17.205.188 dst-address=10.11.104.2 dst-port=22" in script
    assert script.count("place-before=0") == 2 and 'comment="isp-olt-fwd:olt-a ssh"' in script
    rules.append({".id": "*9", "chain": "dstnat", "dst-port": "22104", "comment": "isp-olt-fwd:olt-a ssh"})
    rules.append({".id": "*A", "chain": "srcnat", "comment": "isp-olt-fwd:olt-a masquerade"})
    port2, old2, _ = olt_access.plan(rules, "olt-a", "192.168.174.40", "10.11.104.2", "172.17.205.188")
    assert port2 == 22104 and old2 == ["*9", "*A"]  # same port kept, old rules replaced
    with pytest.raises(ValueError):
        olt_access.plan([], "x", "192.168.174.40", "10.11.104.2; /system reset", "172.17.205.188")


def test_platform_address_from_router_user(monkeypatch):
    class Ros:
        def get(self, path):
            assert path == "user?name=isp-nms"
            return [{"name": "isp-nms", "address": "172.17.205.188/32"}]
    assert olt_access.platform_address(Ros(), "isp-nms") == "172.17.205.188"

    class Open:
        def get(self, path):
            return [{"name": "isp-nms", "address": ""}]
    monkeypatch.setattr(olt_access.config, "NMS_SOURCE_IP", "")
    with pytest.raises(olt_access.AccessError):
        olt_access.platform_address(Open(), "isp-nms")
    monkeypatch.setattr(olt_access.config, "NMS_SOURCE_IP", "172.17.205.188")
    assert olt_access.platform_address(Open(), "isp-nms") == "172.17.205.188"


def test_enable_and_disable_via_api(admin, monkeypatch):
    rt = admin.post("/api/devices", json={"name": "ACC-MT", "vendor": "mikrotik", "role": "island_router", "management_ip": "192.168.174.40",
                                          "credentials": {"username": "isp-nms", "password": "pw-secret-1"}}).json()["id"]
    olt = admin.post("/api/devices", json={"name": "ACC-OLT", "vendor": "huawei", "role": "olt", "management_ip": "10.11.104.2",
                                           "credentials": {"username": "satlink", "password": "pw-secret-2"}}).json()["id"]
    r = admin.post(f"/api/olt/{olt}/access", json={"via_router": True})
    assert r.status_code == 400 and "Upstream" in r.json()["detail"]
    d = admin.get(f"/api/devices/{olt}").json()
    admin.put(f"/api/devices/{olt}", json={**{k: d[k] for k in ("name", "vendor", "role", "management_ip", "notes", "settings")},
                                            "parent_device_id": rt})

    nat, scripts = [], []

    class FakeRos:
        def get(self, path):
            return [{"name": "isp-nms", "address": "172.17.205.188/32"}] if path.startswith("user") else list(nat)

        def run_script(self, s):
            scripts.append(s)
            nat.append({".id": "*5", "chain": "dstnat", "dst-port": "22101", "comment": f"isp-olt-fwd:{olt} ssh"})

        def _req(self, method, path):
            nat[:] = [x for x in nat if x[".id"] != path.rsplit("/", 1)[1]]

    monkeypatch.setattr(olt_access.dev, "mikrotik", contextlib.contextmanager(lambda device: (yield FakeRos())))
    r = admin.post(f"/api/olt/{olt}/access", json={"via_router": True})
    assert r.status_code == 200, r.text
    assert r.json() == {"router": "ACC-MT", "host": "192.168.174.40", "port": 22101, "source": "172.17.205.188"}
    d = admin.get(f"/api/devices/{olt}").json()
    assert d["parent_name"] == "ACC-MT" and d["settings"]["via_router"] and d["settings"]["forward_port"] == 22101
    assert olt_access.endpoint(d) == ("192.168.174.40", 22101)
    r = admin.post(f"/api/olt/{olt}/access", json={"via_router": False})
    assert r.json()["rules_removed"] == 1 and nat == []
    d = admin.get(f"/api/devices/{olt}").json()
    assert "via_router" not in d["settings"] and olt_access.endpoint(d) == ("10.11.104.2", 22)


def test_tcp_ping():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(5)
    up = tcp_ping("127.0.0.1", srv.getsockname()[1], count=2)
    assert up["reachable"] and up["packet_loss_pct"] == 0
    port = srv.getsockname()[1]
    srv.close()
    down = tcp_ping("127.0.0.1", port, count=1, timeout_s=0.5)
    assert not down["reachable"] and down["packet_loss_pct"] == 100


def test_pin_host_key(admin, sql):
    from .conftest import login
    nina = login("nina")
    did = admin.post("/api/devices", json={"name": "PIN-OLT", "vendor": "huawei", "role": "olt", "management_ip": "10.11.5.2"}).json()["id"]
    fp = "SHA256:" + "A" * 43
    assert admin.post(f"/api/devices/{did}/pin-host-key", json={"fingerprint": fp}).status_code == 409  # not seen yet
    sql("UPDATE devices SET last_poll_error=%s WHERE id=%s", (f"HostKeyMismatch: No pinned host key for [x]:22. Verify on the console, then pin: {fp}", did))
    assert nina.post(f"/api/devices/{did}/pin-host-key", json={"fingerprint": fp}).status_code == 200
    assert admin.get(f"/api/devices/{did}").json()["ssh_host_key"] == fp
    fp2 = "SHA256:" + "B" * 43
    sql("UPDATE devices SET last_poll_error=%s WHERE id=%s", (f"HostKeyMismatch: HOST KEY CHANGED for x: got {fp2}, pinned {fp}", did))
    assert nina.post(f"/api/devices/{did}/pin-host-key", json={"fingerprint": fp2}).status_code == 403  # only admins replace
    assert admin.post(f"/api/devices/{did}/pin-host-key", json={"fingerprint": fp2}).status_code == 200


def test_plan_radio_snmp():
    port, _, script = olt_access.plan([], "af-1", "192.168.174.40", "192.168.174.50", "172.17.205.188",
                                      *olt_access.SERVICES["ubiquiti"])
    assert port == 16101
    assert "protocol=udp src-address=172.17.205.188 dst-address=192.168.174.40 dst-port=16101 to-addresses=192.168.174.50 to-ports=161" in script
    assert 'masquerade protocol=udp src-address=172.17.205.188 dst-address=192.168.174.50 dst-port=161' in script
    assert olt_access.endpoint({"vendor": "ubiquiti", "management_ip": "192.168.174.50", "settings": {}}) == ("192.168.174.50", 161)


def test_radio_polled_through_router(monkeypatch):
    from app.security import encrypt_json
    from app.services import monitor
    seen = []

    def fake_poll(host, community):
        seen.append((host, community))
        return {"uptime_s": 99, "extra": {"sys_descr": "AF-5XHD"}}
    monkeypatch.setattr(monitor.airfiber, "poll", fake_poll)
    monkeypatch.setattr(monitor, "ping", lambda host: pytest.fail("radios behind a router are not pinged"))
    device = {"id": "x", "name": "KUL-NEL-AF-M", "vendor": "ubiquiti", "role": "backhaul", "management_ip": "192.168.174.50",
              "credentials_enc": encrypt_json({"snmp_community": "c0mm"}),
              "settings": {"via_router": True, "forward_host": "192.168.174.40", "forward_port": 16101}}
    m = monitor.poll_device(device)
    assert seen == [("192.168.174.40:16101", "c0mm")] and m["reachable"] and m["uptime_s"] == 99
    monkeypatch.setattr(monitor.airfiber, "poll", lambda h, c: (_ for _ in ()).throw(RuntimeError("No SNMP response")))
    m = monitor.poll_device(device)
    assert not m["reachable"] and "No SNMP response" in m["error"]
