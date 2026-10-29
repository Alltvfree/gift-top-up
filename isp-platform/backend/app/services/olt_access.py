"""Reach an OLT (SSH) or an airFiber radio (SNMP) through its island MikroTik ("Upstream device").

OLTs sit on the island router's local network (e.g. 10.11.104.2 behind NEILAIDHOO-GPON), which the
platform often has no route to. With access via router the platform adds two NAT rules on that
MikroTik, both limited to the platform's own address:
  dstnat      <router mgmt IP>:<221xx>  ->  <OLT IP>:22
  masquerade  platform -> <OLT IP>:22    (the OLT answers the router, so it needs no route back)
then opens SSH to <router mgmt IP>:<221xx>. airFiber radios get the same pair for SNMP (udp 161,
forward ports 161xx), so a radio whose own gateway has no route back to the platform still answers.
The rules carry the comment 'isp-olt-fwd:<device id>'; nothing else on the router is touched.
"""
import ipaddress

from psycopg.types.json import Jsonb

from .. import audit, config
from . import devices as dev

COMMENT = "isp-olt-fwd:"
PORTS = range(22101, 22200)
# vendor -> (protocol, service port on the device, forward ports on the router)
SERVICES = {"huawei": ("tcp", 22, PORTS), "ubiquiti": ("udp", 161, range(16101, 16200))}


class AccessError(Exception):
    pass


def platform_address(ros, username: str) -> str:
    """The platform's IP as the router sees it: the address its own API user is restricted to."""
    users = ros.get(f"user?name={username}") or []
    for a in str((users[0] if users else {}).get("address") or "").split(","):
        try:
            net = ipaddress.ip_network(a.strip(), strict=False)
        except ValueError:
            continue
        if net.num_addresses == 1:
            return str(net.network_address)
    if config.NMS_SOURCE_IP:
        return config.NMS_SOURCE_IP
    raise AccessError(f"Cannot tell this platform's address: restrict router user '{username}' to it "
                      "(/user set isp-nms address=<platform IP>/32) or set NMS_SOURCE_IP in .env")


def plan(nat_rules: list[dict], olt_id: str, router_ip: str, olt_ip: str, src: str,
         proto: str = "tcp", target_port: int = 22, ports: range = PORTS) -> tuple[int, list[str], str]:
    """(forward port, ids of our old rules to delete, RouterOS script adding the new rules)."""
    tag = f"{COMMENT}{olt_id}"
    ours = [r for r in nat_rules if str(r.get("comment", "")).startswith(tag)]
    old_port = next((int(r["dst-port"]) for r in ours if r.get("chain") == "dstnat" and str(r.get("dst-port", "")).isdigit()), None)
    used = {int(p) for r in nat_rules if r not in ours for p in str(r.get("dst-port", "")).replace("-", ",").split(",") if p.isdigit()}
    port = old_port if old_port and old_port not in used else next((p for p in ports if p not in used), None)
    if port is None:
        raise AccessError("No free forward port left on this router")
    for v in (router_ip, olt_ip, src):
        ipaddress.ip_address(v)  # only plain addresses ever reach the script
    first = ':if ([:len [/ip firewall nat find]] > 0) do={{ {r} place-before=0 }} else={{ {r} }}\n'
    script = "".join(first.format(r=r) for r in (
        f'/ip firewall nat add chain=srcnat action=masquerade protocol={proto} src-address={src} dst-address={olt_ip} '
        f'dst-port={target_port} comment="{tag} masquerade"',
        f'/ip firewall nat add chain=dstnat action=dst-nat protocol={proto} src-address={src} dst-address={router_ip} '
        f'dst-port={port} to-addresses={olt_ip} to-ports={target_port} comment="{tag} {"ssh" if target_port == 22 else "snmp"}"',
    ))
    return port, [r[".id"] for r in ours], script


def _load(conn, olt_id):
    olt = conn.execute("SELECT * FROM devices WHERE id=%s", (olt_id,)).fetchone()
    if not olt or olt["vendor"] not in SERVICES:
        raise AccessError("Only Huawei OLTs and Ubiquiti radios can be reached through a router")
    if not olt["management_ip"]:
        raise AccessError("Set the device's management IP (its local IP behind the router) first")
    router = conn.execute("SELECT * FROM devices WHERE id=%s", (olt["parent_device_id"],)).fetchone() if olt["parent_device_id"] else None
    if not router or router["vendor"] != "mikrotik" or not router["management_ip"] or not router["credentials_enc"]:
        raise AccessError("Set the device's Upstream device to its island MikroTik (with a stored login) first")
    return olt, router


def enable(conn, olt_id, actor: str) -> dict:
    olt, router = _load(conn, olt_id)
    router_ip, olt_ip = str(router["management_ip"]), str(olt["management_ip"])
    with dev.mikrotik(router) as ros:
        src = platform_address(ros, dev.creds(router)["username"])
        proto, target_port, ports = SERVICES[olt["vendor"]]
        port, old, script = plan(ros.get("ip/firewall/nat"), str(olt["id"]), router_ip, olt_ip, src, proto, target_port, ports)
        for i in old:
            ros._req("DELETE", f"ip/firewall/nat/{i}")
        ros.run_script(script)
    settings = {**(olt["settings"] or {}), "via_router": True, "forward_host": router_ip, "forward_port": port}
    conn.execute("UPDATE devices SET settings=%s WHERE id=%s", (Jsonb(settings), olt["id"]))
    audit.record(actor, "olt.access_via_router", "device", olt["id"],
                 {"router": router["name"], "forward": f"{router_ip}:{port}", "olt": olt_ip, "from": src}, conn=conn)
    return {"router": router["name"], "host": router_ip, "port": port, "source": src}


def disable(conn, olt_id, actor: str) -> dict:
    olt = conn.execute("SELECT * FROM devices WHERE id=%s", (olt_id,)).fetchone()
    if not olt:
        raise AccessError("Device not found")
    removed = 0
    router = conn.execute("SELECT * FROM devices WHERE id=%s", (olt["parent_device_id"],)).fetchone() if olt["parent_device_id"] else None
    if router and router["credentials_enc"]:
        with dev.mikrotik(router) as ros:
            for r in ros.get("ip/firewall/nat"):
                if str(r.get("comment", "")).startswith(f"{COMMENT}{olt['id']}"):
                    ros._req("DELETE", f"ip/firewall/nat/{r['.id']}")
                    removed += 1
    settings = {k: v for k, v in (olt["settings"] or {}).items() if k not in ("via_router", "forward_host", "forward_port")}
    conn.execute("UPDATE devices SET settings=%s WHERE id=%s", (Jsonb(settings), olt["id"]))
    audit.record(actor, "olt.access_direct", "device", olt["id"], {"rules_removed": removed}, conn=conn)
    return {"rules_removed": removed}


def endpoint(device: dict) -> tuple[str, int]:
    """Where to connect (SSH for an OLT, SNMP for a radio): the device itself, or the router's forward port."""
    s = device.get("settings") or {}
    if s.get("via_router") and s.get("forward_host") and s.get("forward_port"):
        return s["forward_host"], int(s["forward_port"])
    if device.get("vendor") == "ubiquiti":
        return str(device["management_ip"]), 161
    return str(device["management_ip"]), device.get("mgmt_port") or 22
