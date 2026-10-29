"""MikroTik monitoring over SNMP v2c (net-snmp CLI in the container). Works on RouterOS 6 and 7.

Read-only: uptime, CPU, memory, version/board, interfaces down and active PPPoE sessions (each
PPPoE client is a dynamic interface named <pppoe-USER>). Router side:
    /snmp set enabled=yes
    /snmp community set [find default=yes] name=<secret> addresses=<platform IP>/32
Writing (blocklist sync, changes, OLT forwards) still needs the REST API on RouterOS 7.
"""
import re
import subprocess

SYS_DESCR = "1.3.6.1.2.1.1.1.0"
SYS_UPTIME = "1.3.6.1.2.1.1.3.0"
ROS_VERSION = "1.3.6.1.4.1.14988.1.1.4.4.0"     # MIKROTIK-MIB mtxrLicVersion
BOARD_NAME = "1.3.6.1.4.1.14988.1.1.7.8.0"      # mtxrBoardName (newer builds)
CPU_LOAD = "1.3.6.1.2.1.25.3.3.1.2"             # hrProcessorLoad, one row per core
STORAGE = "1.3.6.1.2.1.25.2.3.1"                # hrStorageTable: .3 descr, .5 size, .6 used
IF_DESCR = "1.3.6.1.2.1.2.2.1.2"
IF_TYPE = "1.3.6.1.2.1.2.2.1.3"
IF_ADMIN = "1.3.6.1.2.1.2.2.1.7"
IF_OPER = "1.3.6.1.2.1.2.2.1.8"
WATCHED_IF_TYPES = {"6", "135", "209"}         # ethernet (incl. SFP), VLAN, bridge


class SnmpError(Exception):
    pass


def _run(args, timeout):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout).stdout
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        raise SnmpError(f"snmp: {type(exc).__name__}") from None


def parse(out: str) -> dict:
    """'-Onqet' output ('.1.3.6... value' per line) -> {oid: value}."""
    values = {}
    for line in out.splitlines():
        oid, _, value = line.strip().partition(" ")
        v = value.strip()
        if oid.startswith(".") and not v.startswith(("No Such Object", "No Such Instance", "No more variables")):
            values[oid[1:]] = v[1:-1] if len(v) >= 2 and v[0] == v[-1] == '"' else v
    return values


def _below(values: dict, base: str) -> dict:
    """{row index: value} for every OID under `base`."""
    return {oid[len(base) + 1:]: v for oid, v in values.items() if oid.startswith(base + ".")}


class MikroTikSNMP:
    def __init__(self, host: str, community: str, timeout: int = 2, runner=_run):
        self.base = ["-v2c", "-c", community, "-Onqet", "-t", str(timeout), "-r", "1", host]
        self.timeout, self.runner = timeout, runner

    def get(self, *oids) -> dict:
        return parse(self.runner(["snmpget", *self.base, *oids], self.timeout * 4 + 3))

    def walk(self, oid) -> dict:
        return parse(self.runner(["snmpbulkwalk", *self.base, oid], self.timeout * 10 + 5))

    def poll(self) -> dict:
        top = self.get(SYS_DESCR, SYS_UPTIME, ROS_VERSION, BOARD_NAME)
        if not top.get(SYS_UPTIME, "").isdigit():
            raise SnmpError("No SNMP answer (SNMP enabled? right community? platform IP allowed in /snmp community?)")
        cpu = [int(v) for v in _below(self.walk(CPU_LOAD), CPU_LOAD).values() if v.isdigit()]
        storage = self.walk(STORAGE)
        mem = None
        for idx, descr in _below(storage, f"{STORAGE}.3").items():
            if descr.lower() in ("main memory", "physical memory"):
                size, used = storage.get(f"{STORAGE}.5.{idx}", ""), storage.get(f"{STORAGE}.6.{idx}", "")
                if size.isdigit() and used.isdigit() and int(size):
                    mem = round(100 * int(used) / int(size), 1)
        ifs = {**self.walk(IF_DESCR), **self.walk(IF_TYPE), **self.walk(IF_ADMIN), **self.walk(IF_OPER)}
        names = _below(ifs, IF_DESCR)
        down = [name for idx, name in names.items()
                if not name.startswith("<") and ifs.get(f"{IF_TYPE}.{idx}") in WATCHED_IF_TYPES
                and ifs.get(f"{IF_ADMIN}.{idx}") == "1" and ifs.get(f"{IF_OPER}.{idx}") == "2"]
        descr = top.get(SYS_DESCR, "")
        board = top.get(BOARD_NAME) or (descr[len("RouterOS "):] if descr.startswith("RouterOS ") else None)
        version = top.get(ROS_VERSION) or None
        if version and not re.match(r"^\d", version):
            version = None
        return {
            "cpu_load_pct": round(sum(cpu) / len(cpu), 1) if cpu else None,
            "mem_used_pct": mem,
            "uptime_s": int(top[SYS_UPTIME]) // 100,
            "extra": {
                "version": version,
                "board": board,
                "pppoe_active": sum(1 for n in names.values() if n.startswith("<pppoe-")),
                "interfaces_down": down,
                "via": "snmp",
            },
        }
