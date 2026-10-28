"""Ubiquiti airFiber / UISP backhaul radios over SNMP (net-snmp CLI in the container).

Standard MIB-II OIDs are fixed. Vendor OIDs differ between airFiber families (AF-5XHD, AF60,
AF-24...) and firmware, so they live in AF_OIDS and must be confirmed with:
    snmpwalk -v2c -c <community> <radio-ip> 1.3.6.1.4.1.41112
Leave an OID out rather than guess: wrong OIDs produce confident, wrong graphs.
"""
import json
import os
import re
import subprocess

STANDARD = {
    "sys_descr": "1.3.6.1.2.1.1.1.0",
    "uptime_ticks": "1.3.6.1.2.1.1.3.0",
}
# Override with AIRFIBER_OIDS='{"rx_capacity_bps":"1.3.6.1.4.1.41112....","remote_rssi_dbm":"..."}'
AF_OIDS = json.loads(os.environ.get("AIRFIBER_OIDS", "{}"))


def snmp_get(host: str, community: str, oids: dict, timeout=2) -> dict:
    if not oids:
        return {}
    cmd = ["snmpget", "-v2c", "-c", community, "-On", "-Oq", "-t", str(timeout), "-r", "1", host, *oids.values()]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout * 3 + 3).stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return {}
    by_oid = {}
    for line in out.splitlines():
        oid, _, value = line.partition(" ")
        by_oid[oid.lstrip(".")] = value.strip().strip('"')
    return {name: by_oid.get(oid) for name, oid in oids.items()}


def _num(v):
    if v is None:
        return None
    m = re.search(r"-?\d+(\.\d+)?", v)
    return float(m.group(0)) if m else None


def poll(host: str, community: str) -> dict:
    values = snmp_get(host, community, {**STANDARD, **AF_OIDS})
    if not values or values.get("uptime_ticks") is None:
        raise RuntimeError("No SNMP response (check community, ACL and that SNMP is enabled on the radio)")
    ticks = re.search(r"\((\d+)\)", values["uptime_ticks"] or "") or re.search(r"^(\d+)$", values["uptime_ticks"] or "")
    return {
        "uptime_s": int(ticks.group(1)) // 100 if ticks else None,
        "extra": {"sys_descr": values.get("sys_descr"),
                  **{k: _num(values.get(k)) for k in AF_OIDS}},
    }
