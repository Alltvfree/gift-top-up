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
YES_NO = re.compile(r"\(y/n\)\[[yn]\]:\s*$")
# "Failure: The automatically found ONTs do not exist" / "There is no ONT available": an empty answer, not an error
EMPTY = re.compile(r"Failure:\s*(The automatically found ONTs do not exist|There is no ONT available|The ONT does not exist)", re.I)
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

    def _read_until_prompt(self, confirm: bool = False) -> str:
        # Idle timeout: a big OLT prints for a long time, so every chunk received extends the deadline.
        buf, deadline = "", time.time() + self.timeout
        while time.time() < deadline:
            if self.shell.recv_ready():
                buf += ANSI.sub("", self.shell.recv(65535).decode(errors="replace"))
                deadline = time.time() + self.timeout
                if YES_NO.search(buf[-200:]):
                    if confirm:              # a command a person chose to run (reboot, approved change)
                        self.shell.send("y\n")
                        buf += "y\n"
                        continue
                    self.shell.send("n\n")  # never confirm anything we did not plan for
                    raise OLTError("OLT asked for a yes/no confirmation (answered no):\n" + buf.strip()[-300:])
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

    def cmd(self, command: str, confirm: bool = False) -> str:
        self.shell.send(command + "\n")
        out = self._read_until_prompt(confirm)
        if re.search(r"^\s*% (Unknown command|Parameter error|Incomplete command)", out, re.M) or "Failure:" in out:
            raise OLTError(f"`{command}` failed:\n{out.strip()[-500:]}")
        return out

    def run_lines(self, lines: list[str]) -> str:
        # Lines of an approved plan: their confirmation questions are part of what was approved.
        return "\n".join(f"> {line}\n{self.cmd(line, confirm=True).strip()}" for line in lines)

    def on_board(self, frame: int, slot: int, command: str, confirm: bool = False) -> str:
        self.cmd(f"interface gpon {int(frame)}/{int(slot)}")
        try:
            return self.cmd(command, confirm=confirm)
        finally:
            self.cmd("quit")

    def ont_config(self, frame, slot, port, ont_id) -> str:
        """Read-only: the ONT's lines from current-configuration plus its service-ports."""
        parts = []
        for c in (f"display current-configuration ont {frame}/{slot}/{port} {ont_id}",
                  f"display service-port port {frame}/{slot}/{port} ont {ont_id}"):
            try:
                parts.append(f"> {c}\n{self.query(c).strip()}")
            except OLTError as exc:
                parts.append(f"> {c}\n(not supported on this firmware: {str(exc).splitlines()[-1][:120]})")
        return "\n\n".join(parts)

    def query(self, command: str) -> str:
        """Read-only command where "nothing found" is a normal (empty) answer."""
        try:
            return self.cmd(command)
        except OLTError as exc:
            if EMPTY.search(str(exc)):
                return ""
            raise

    # ---- read-only
    def autofind(self):
        return parse_autofind(self.query("display ont autofind all"))

    def ont_list_frame(self, frame: int = 0) -> list[dict]:
        """Every ONT on every GPON board of a frame, with descriptions, in one command (config mode)."""
        return parse_ont_info_table(self.query(f"display ont info {int(frame)} all"))

    def optical_many(self, onts: list[dict]) -> dict:
        """Optical levels for several ONTs: one `display ont optical-info <port> all` per port (V800R017 and later),
        falling back to one ONT at a time where a board does not support the table. {(f,s,p,id): {...}}"""
        out = {}
        by_port = {}
        for o in onts:
            by_port.setdefault((o["frame"], o["slot"]), {}).setdefault(o["port"], []).append(o)
        for (frame, slot), ports in by_port.items():
            self.cmd(f"interface gpon {frame}/{slot}")
            try:
                for port, items in ports.items():
                    try:
                        table = parse_optical_table(self.query(f"display ont optical-info {port} all"))
                    except OLTError:
                        table = {}
                    for o in items:
                        if o["ont_id"] in table:
                            out[(frame, slot, port, o["ont_id"])] = table[o["ont_id"]]
                            continue
                        try:
                            out[(frame, slot, port, o["ont_id"])] = parse_optical(self.cmd(f"display ont optical-info {port} {o['ont_id']}"))
                        except OLTError:
                            continue  # went offline between the list and this read
            finally:
                self.cmd("quit")
        return out

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


DESC_HEADER = re.compile(r"^\s*F/S/P\s+ONT-ID\s+Description\s*$", re.I)
DESC_ROW = re.compile(r"^\s*(\d+)/\s*(\d+)/\s*(\d+)\s+(\d+)(?:\s+(.*?))?\s*$")
PORT_TOTAL = re.compile(r"In port\s+(\d+)/\s*(\d+)/\s*(\d+)\s*,\s*the total of ONTs are:\s*(\d+),\s*online:\s*(\d+)", re.I)


def parse_ont_descriptions(text: str) -> dict:
    """{(f,s,p,ont_id): description} from the 'F/S/P ONT-ID Description' tables."""
    out, inside = {}, False
    for line in text.splitlines():
        if DESC_HEADER.match(line):
            inside = "header"
            continue
        if inside and set(line.strip()) <= {"-"}:
            inside = True if inside == "header" else False   # dashes under the header, then the closing dashes
            continue
        if inside is True:
            m = DESC_ROW.match(line)
            if m:
                out[(int(m[1]), int(m[2]), int(m[3]), int(m[4]))] = (m[5] or "").strip()
    return out


def parse_port_totals(text: str) -> dict:
    return {(int(m[1]), int(m[2]), int(m[3])): {"total": int(m[4]), "online": int(m[5])} for m in PORT_TOTAL.finditer(text)}


def parse_ont_info_table(text: str) -> list[dict]:
    desc = parse_ont_descriptions(text)
    rows = []
    for m in ONT_ROW.finditer(text):
        key = (int(m[1]), int(m[2]), int(m[3]), int(m[4]))
        rows.append({"frame": key[0], "slot": key[1], "port": key[2], "ont_id": key[3], "serial": m[5].upper(),
                     "control": m[6], "run_state": m[7], "config_state": m[8], "match_state": m[9],
                     "description": desc.get(key)})
    return rows


def _dbm(text, label):
    m = re.search(rf"^\s*{label}\s*:\s*(-?[\d.]+)", text, re.M | re.I)
    return float(m.group(1)) if m else None


def parse_optical(text: str) -> dict:
    return {
        "rx_power_dbm": _dbm(text, r"Rx optical power\(dBm\)"),
        "tx_power_dbm": _dbm(text, r"Tx optical power\(dBm\)"),
        "olt_rx_power_dbm": _dbm(text, r"OLT Rx ONT optical power\(dBm\)"),
        "temperature_c": _dbm(text, r"Temperature\(C\)"),
        "voltage_v": _dbm(text, r"Voltage\(V\)"),
        "bias_ma": _dbm(text, r"Laser bias current\(mA\)"),
    }


OPTICAL_ROW = re.compile(r"^\s*(\d+)\s+(-?[\d.]+|-)\s+(-?[\d.]+|-)\s+(-?[\d.]+|-)\s+(-?[\d.]+|-)\s+([\d.]+|-)\s+([\d.]+|-)\s*$", re.M)


def parse_optical_table(text: str) -> dict:
    """`display ont optical-info <port> all`: {ont_id: {rx, tx, olt_rx, temperature, voltage, bias}}."""
    num = lambda v: None if v == "-" else float(v)  # noqa: E731
    return {int(m[1]): {"rx_power_dbm": num(m[2]), "tx_power_dbm": num(m[3]), "olt_rx_power_dbm": num(m[4]),
                        "temperature_c": num(m[5]), "voltage_v": num(m[6]), "bias_ma": num(m[7])}
            for m in OPTICAL_ROW.finditer(text)}


def parse_ont_config(text: str) -> dict:
    """Profiles, VLAN and GEM port from `display current-configuration ont F/S/P ID` (lines may wrap)."""
    flat = re.sub(r"\s+", " ", text)
    g = lambda pat: (lambda m: int(m.group(1)) if m else None)(re.search(pat, flat))  # noqa: E731
    return {"line_profile_id": g(r"ont-lineprofile-id (\d+)"), "service_profile_id": g(r"ont-srvprofile-id (\d+)"),
            "vlan": g(r"service-port \d+ vlan (\d+)"), "gemport": g(r"gemport (\d+)"),
            "service_port_index": g(r"service-port (\d+) vlan")}


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
