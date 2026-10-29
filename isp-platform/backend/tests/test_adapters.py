import json

import httpx
import pytest

from app.adapters import huawei
from app.adapters.mikrotik import RouterOS, RouterOSError


def fake_router(scripts: list, fail_on: str | None = None):
    def handler(request: httpx.Request):
        path = request.url.path.removeprefix("/rest/")
        if path == "execute":
            script = json.loads(request.content)["script"]
            scripts.append(script)
            if fail_on and fail_on in script:
                return httpx.Response(400, json={"detail": "failure: bad command"})
            return httpx.Response(200, json={"ret": ""})
        data = {
            "system/resource": {"cpu-load": "7", "total-memory": "1000", "free-memory": "250", "uptime": "2d3h4m5s",
                                "version": "7.16.1 (stable)", "board-name": "CCR2004-1G-12S+2XS"},
            "ppp/active": [{"name": "a"}, {"name": "b"}],
            "interface": [{"name": "sfp1", "type": "ether", "running": "true", "disabled": "false"},
                          {"name": "sfp2", "type": "ether", "running": "false", "disabled": "false"}],
        }[path]
        return httpx.Response(200, json=data)
    return httpx.MockTransport(handler)


def test_poll_parses_resource():
    with RouterOS("10.0.0.1", "u", "p", transport=fake_router([])) as ros:
        r = ros.poll()
    assert r["cpu_load_pct"] == 7 and r["mem_used_pct"] == 75.0 and r["uptime_s"] == 2 * 86400 + 3 * 3600 + 245
    assert r["extra"] == {"version": "7.16.1 (stable)", "board": "CCR2004-1G-12S+2XS", "pppoe_active": 2, "interfaces_down": ["sfp2"]}


def test_commit_confirm_disarms_when_reachable(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    scripts = []
    with RouterOS("10.0.0.1", "u", "p", transport=fake_router(scripts)) as ros:
        log = ros.apply_with_commit_confirm(7, "/ip service set telnet disabled=yes", 5, lambda: True)
    assert scripts[0].startswith("/system backup save name=isp-change-7")
    assert "/system scheduler add name=isp-change-7 interval=5m" in scripts[2] and "backup load name=isp-change-7.backup" in scripts[2]
    assert scripts[3] == "/ip service set telnet disabled=yes"
    assert scripts[4] == "/system scheduler remove [find name=isp-change-7]"
    assert "disarmed" in log


def test_commit_confirm_leaves_rollback_armed_when_unreachable(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    scripts = []
    with RouterOS("10.0.0.1", "u", "p", transport=fake_router(scripts)) as ros:
        with pytest.raises(RouterOSError, match="auto-rollback will restore"):
            ros.apply_with_commit_confirm(8, "/ip firewall filter add chain=input action=drop", 5, lambda: False)
    assert not any(s.startswith("/system scheduler remove") for s in scripts)


def test_commit_confirm_script_error_keeps_rollback(monkeypatch):
    scripts = []
    with RouterOS("10.0.0.1", "u", "p", transport=fake_router(scripts, fail_on="bogus")) as ros:
        with pytest.raises(RouterOSError, match="leaving auto-rollback armed"):
            ros.apply_with_commit_confirm(9, "/bogus command", 5, lambda: True)
    assert not any(s.startswith("/system scheduler remove") for s in scripts)


class FakeShell:
    """Replays canned OLT output per command, including paging and a <cr> prompt."""
    def __init__(self, responses):
        self.responses, self.queue, self.sent = responses, ["MA5608T>"], []

    def recv_ready(self):
        return bool(self.queue)

    def recv(self, n):
        return self.queue.pop(0).encode()

    def send(self, data):
        self.sent.append(data)
        if data == " ":
            self.queue.append("  0/ 1/0    1  4857544311223344  active      offline  initial  initial  no\nMA5608T(config-if-gpon-0/1)#")
        elif data == "\n" and self.sent[-2:-1] and self.sent[-2] != "\n" and "pending_cr" in self.__dict__:
            del self.pending_cr
            self.queue.append("\nresult after enter\nMA5608T(config)#")
        else:
            cmd = data.strip()
            out = self.responses.get(cmd, "")
            if out == "CR":
                self.pending_cr = True
                self.queue.append(f"{cmd}\n{{ <cr>|ontid<U><0,127> }}:")
            else:
                self.queue.append(f"{cmd}\n{out}\nMA5608T(config)#" if out != "PAGED" else
                                  f"{cmd}\n  0/ 1/0    0  48575443A1B2C3D4  active      online   normal   match    no\n---- More ( Press 'Q' to break ) ----")


def make_olt(responses):
    olt = huawei.HuaweiOLT.__new__(huawei.HuaweiOLT)
    olt.shell, olt.timeout = FakeShell(responses), 2
    olt._read_until_prompt()
    return olt


def test_olt_paging_and_cr_prompt():
    olt = make_olt({"display ont info 0 all": "PAGED", "display ont autofind 0": "CR"})
    out = olt.cmd("display ont info 0 all")
    assert [o["ont_id"] for o in huawei.parse_ont_info_table(out)] == [0, 1]
    assert " " in olt.shell.sent  # pressed space at --More--
    assert "result after enter" in olt.cmd("display ont autofind 0")


def test_olt_error_detection():
    olt = make_olt({"ont add 0 1 bad": "  % Unknown command, the error locates at '^'",
                    "ont delete 0 9": "  Failure: The ONT does not exist"})
    with pytest.raises(huawei.OLTError):
        olt.cmd("ont add 0 1 bad")
    with pytest.raises(huawei.OLTError):
        olt.cmd("ont delete 0 9")


# ---------- real MA5608T output (descriptions anonymised, layout untouched)
from pathlib import Path

REAL = (Path(__file__).parent / "fixtures" / "ma5608t_display_ont_info_0_all.txt").read_text()


def test_real_ma5608t_frame_listing():
    rows = huawei.parse_ont_info_table(REAL)
    assert len(rows) == 31 + 14 + 12 + 22 + 28 + 2 + 1 + 1          # every port of slot 1
    totals = huawei.parse_port_totals(REAL)
    assert totals[(0, 1, 0)] == {"total": 31, "online": 15} and totals[(0, 1, 7)] == {"total": 1, "online": 1}
    for (f, s, p), t in totals.items():                                  # parser agrees with the OLT's own counts
        port_rows = [r for r in rows if (r["frame"], r["slot"], r["port"]) == (f, s, p)]
        assert len(port_rows) == t["total"] and sum(r["run_state"] == "online" for r in port_rows) == t["online"]
    first = rows[0]
    assert (first["frame"], first["slot"], first["port"], first["ont_id"], first["serial"], first["run_state"]) == \
        (0, 1, 0, 0, "485754434C62729B", "offline")
    assert all(r["description"] for r in rows)                           # every ONT got its description
    by_id = {(r["port"], r["ont_id"]): r for r in rows}
    assert by_id[(4, 100)]["serial"] == "485754436EF52196"               # 3-digit ONT id
    assert " 5G" in by_id[(2, 9)]["description"]                         # description with a space
    assert by_id[(0, 10)]["description"] == by_id[(0, 10)]["description"].strip()   # trailing spaces trimmed
    assert by_id[(4, 60)]["description"].islower()


def test_empty_answers_and_yes_no():
    olt = make_olt({"display ont autofind all": "  Failure: The automatically found ONTs do not exist",
                    "display ont info 3 all": "  Failure: There is no ONT available"})
    assert olt.autofind() == []
    assert olt.ont_list_frame(3) == []
    yn = make_olt({})
    yn.shell.queue.append("quit\n  Check whether system data has been changed.\nAre you sure to log out? (y/n)[n]:")
    with pytest.raises(huawei.OLTError, match="yes/no"):
        yn._read_until_prompt()
    assert yn.shell.sent[-1] == "n\n"


OPT = (Path(__file__).parent / "fixtures" / "ma5608t_optical.txt").read_text()
OPT_SINGLE, rest = OPT.split("===TABLE===")
OPT_TABLE, OPT_CONFIG = rest.split("===CONFIG===")


def test_real_optical_single_and_table():
    one = huawei.parse_optical(OPT_SINGLE)
    assert one == {"rx_power_dbm": -19.95, "tx_power_dbm": 2.06, "olt_rx_power_dbm": -22.30,
                   "temperature_c": 55.0, "voltage_v": 3.28, "bias_ma": 8.0}   # threshold lines are not mistaken for values
    table = huawei.parse_optical_table(OPT_TABLE)
    assert sorted(table) == [3, 4, 9, 10, 11, 13, 20, 23, 24, 25, 44, 45, 49, 51, 54]
    assert table[11] == {"rx_power_dbm": -30.96, "tx_power_dbm": 2.11, "olt_rx_power_dbm": -29.21,
                         "temperature_c": 44.0, "voltage_v": 3.28, "bias_ma": 13.0}
    assert table[4]["rx_power_dbm"] == one["rx_power_dbm"]


def test_real_ont_config():
    assert huawei.parse_ont_config(OPT_CONFIG) == {"line_profile_id": 10, "service_profile_id": 10, "vlan": 100,
                                                   "gemport": 1, "service_port_index": 19}


class OpticalShell(FakeShell):
    """Port table for port 0, unsupported on port 1 (forces the per-ONT fallback)."""
    def send(self, data):
        self.sent.append(data)
        cmd = data.strip()
        if cmd == "display ont optical-info 0 all":
            self.queue.append(cmd + "\n" + OPT_TABLE + "\nMA5608T(config-if-gpon-0/1)#")
        elif cmd == "display ont optical-info 1 all":
            self.queue.append(cmd + "\n  % Parameter error, the error locates at '^'\nMA5608T(config-if-gpon-0/1)#")
        elif cmd.startswith("display ont optical-info 1 "):
            self.queue.append(cmd + "\n" + OPT_SINGLE + "\nMA5608T(config-if-gpon-0/1)#")
        else:
            self.queue.append(cmd + "\nMA5608T(config)#")


def test_optical_many_uses_port_table_and_falls_back():
    olt = huawei.HuaweiOLT.__new__(huawei.HuaweiOLT)
    olt.shell, olt.timeout = OpticalShell({}), 2
    olt._read_until_prompt()
    onts = [{"frame": 0, "slot": 1, "port": 0, "ont_id": i} for i in (3, 4, 11)] + [{"frame": 0, "slot": 1, "port": 1, "ont_id": 7}]
    out = olt.optical_many(onts)
    assert out[(0, 1, 0, 11)]["rx_power_dbm"] == -30.96 and out[(0, 1, 1, 7)]["rx_power_dbm"] == -19.95
    cmds = [c.strip() for c in olt.shell.sent if c.strip()]
    assert cmds.count("display ont optical-info 0 all") == 1 and not any(c.startswith("display ont optical-info 0 ") and not c.endswith("all") for c in cmds)
