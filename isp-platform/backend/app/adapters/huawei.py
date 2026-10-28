"""Huawei MA56xx (MA5608T / MA5683T / MA5800) GPON OLT adapter over SSH CLI.

Commands follow the MA5600 V800R01x CLI. Output formats drift between firmware releases, so
every parser is tolerant and covered by tests with captured output; check against your OLT
before trusting provisioning.
"""
import re
import time

import paramiko

from .sshpin import PinnedKeyPolicy

PROMPT = re.compile(r"(\n|^)[\w.\-]+(\([\w\-/]+\))?[>#]\s*$")
MORE = re.compile(r"-+\s*More\s*\(.*?\)\s*-+|---- More ----")
CR_PROMPT = re.compile(r"\{\s*<cr>.*\}:\s*$", re.S)
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


class OLTError(Exception):
    pass


class HuaweiOLT:
    def __init__(self, host, username, password, port=22, host_key=None, timeout=15):
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(PinnedKeyPolicy(host_key))
        self.client.connect(
            host, port=port or 22, username=username, password=password, timeout=timeout,
            look_for_keys=False, allow_agent=False,
        )
        self.shell = self.client.invoke_shell(width=512, height=1000)
        self.timeout = timeout
        self._read_until_prompt()
        for cmd in ("enable", "scroll 512", "undo smart", "config"):
            self.cmd(cmd)

    def close(self):
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _read_until_prompt(self) -> str:
        buf, deadline = "", time.time() + self.timeout
        while time.time() < deadline:
            if self.shell.recv_ready():
                buf += ANSI.sub("", self.shell.recv(65535).decode(errors="replace"))
                if MORE.search(buf[-200:]):
                    buf = MORE.sub("", buf)
                    self.shell.send(" ")
                    continue
                if CR_PROMPT.search(buf[-300:]):
                    self.shell.send("\n")
                    continue
                if PROMPT.search(buf[-200:]):
                    return buf
            else:
                time.sleep(0.1)
        raise OLTError("Timed out waiting for OLT prompt")

    def cmd(self, command: str) -> str:
        self.shell.send(command + "\n")
        out = self._read_until_prompt()
        if re.search(r"^\s*% (Unknown command|Parameter error|Incomplete command)", out, re.M) or "Failure:" in out:
            raise OLTError(f"`{command}` failed:\n{out.strip()[-500:]}")
        return out

    def run_lines(self, lines: list[str]) -> str:
        return "\n".join(f"> {line}\n{self.cmd(line).strip()}" for line in lines)

    # ---- read-only
    def autofind(self):
        return parse_autofind(self.cmd("display ont autofind all"))

    def ont_list(self, frame: int, slot: int):
        self.cmd(f"interface gpon {frame}/{slot}")
        try:
            out = ""
            for port in range(16):  # ports without ONTs (or past the board's last port) answer "Failure"
                try:
                    out += self.cmd(f"display ont info {port} all")
                except OLTError:
                    continue
            return parse_ont_info_table(out)
        finally:
            self.cmd("quit")

    def optical(self, frame, slot, port, ont_id):
        self.cmd(f"interface gpon {frame}/{slot}")
        try:
            return parse_optical(self.cmd(f"display ont optical-info {port} {ont_id}"))
        finally:
            self.cmd("quit")


# ---------- parsers
def parse_autofind(text: str) -> list[dict]:
    rows = []
    for block in re.split(r"-{20,}", text):
        fields = {}
        for line in block.splitlines():
            if ":" in line:
                k, _, v = line.partition(":")
                fields[k.strip().lower()] = v.strip()
        if "ont sn" not in fields or "f/s/p" not in fields:
            continue
        f, s, p = (int(x) for x in fields["f/s/p"].replace(" ", "").split("/"))
        rows.append({
            "frame": f, "slot": s, "port": p,
            "serial": fields["ont sn"].split()[0].upper(),
            "equipment_id": fields.get("ont equipmentid") or None,
            "version": fields.get("ont softwareversion") or None,
            "found_at": fields.get("ont autofind time") or None,
        })
    return rows


ONT_ROW = re.compile(
    r"^\s*(\d+)/\s*(\d+)/\s*(\d+)\s+(\d+)\s+([0-9A-Fa-f]{16})\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)", re.M)


def parse_ont_info_table(text: str) -> list[dict]:
    return [{
        "frame": int(m[1]), "slot": int(m[2]), "port": int(m[3]), "ont_id": int(m[4]),
        "serial": m[5].upper(), "control": m[6], "run_state": m[7], "config_state": m[8], "match_state": m[9],
    } for m in ONT_ROW.finditer(text)]


def _dbm(text, label):
    m = re.search(rf"^\s*{label}\s*:\s*(-?[\d.]+)", text, re.M | re.I)
    return float(m.group(1)) if m else None


def parse_optical(text: str) -> dict:
    return {
        "rx_power_dbm": _dbm(text, r"Rx optical power\(dBm\)"),
        "tx_power_dbm": _dbm(text, r"Tx optical power\(dBm\)"),
        "olt_rx_power_dbm": _dbm(text, r"OLT Rx ONT optical power\(dBm\)"),
        "temperature_c": _dbm(text, r"Temperature\(C\)"),
    }


# ---------- command builders (become reviewed change plans, never run directly)
SN_RE = re.compile(r"^[0-9A-F]{16}$")
SAFE_TEXT = re.compile(r"^[A-Za-z0-9 ._@-]{0,64}$")


def _check(value, pattern, name):
    if not pattern.match(str(value)):
        raise ValueError(f"Invalid {name}")
    return value


def build_ont_provision(*, frame, slot, port, ont_id, serial, line_profile_id, service_profile_id,
                        vlan, gemport, description, pppoe_username, pppoe_password) -> tuple[list[str], list[str]]:
    """ONT add + PPPoE WAN via OMCI + service-port. Returns (apply_lines, rollback_lines)."""
    serial = _check(serial.upper(), SN_RE, "serial (16 hex chars)")
    _check(description, SAFE_TEXT, "description")
    _check(pppoe_username, SAFE_TEXT, "PPPoE username")
    _check(pppoe_password, re.compile(r"^[A-Za-z0-9._@#%+=-]{6,64}$"), "PPPoE password")
    for name, v, hi in (("frame", frame, 7), ("slot", slot, 21), ("port", port, 15), ("ont_id", ont_id, 127),
                        ("vlan", vlan, 4094), ("gemport", gemport, 1023)):
        if not isinstance(v, int) or not 0 <= v <= hi:
            raise ValueError(f"Invalid {name}")
    apply = [
        f"interface gpon {frame}/{slot}",
        f'ont add {port} {ont_id} sn-auth "{serial}" omci ont-lineprofile-id {line_profile_id} '
        f'ont-srvprofile-id {service_profile_id} desc "{description}"',
        f'ont ipconfig {port} {ont_id} ip-index 0 pppoe vlan {vlan} priority 0 '
        f'user-account username "{pppoe_username}" password "{pppoe_password}"',
        f"ont internet-config {port} {ont_id} ip-index 0",
        "quit",
        f"service-port vlan {vlan} gpon {frame}/{slot}/{port} ont {ont_id} gemport {gemport} "
        f"multi-service user-vlan {vlan} tag-transform translate",
    ]
    rollback = [
        f"undo service-port port {frame}/{slot}/{port} ont {ont_id}",
        f"interface gpon {frame}/{slot}",
        f"ont delete {port} {ont_id}",
        "quit",
    ]
    return apply, rollback


def build_ont_reboot(frame, slot, port, ont_id) -> list[str]:
    return [f"interface gpon {frame}/{slot}", f"ont reset {port} {ont_id}", "quit"]
