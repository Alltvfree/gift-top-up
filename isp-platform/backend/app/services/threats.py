"""Network-wide blocking of hosts that brute-force router logins.

Detection: each poll reads new 'login failure for user X from IP via winbox|ssh|api' lines from
every MikroTik. Decision: THREAT_FAILURES failures from one public IP within THREAT_WINDOW_MIN
blocks it; THREAT_SUBNET_AFTER blocked IPs in the same /24 (rotating bots) blocks the /24.
Enforcement: active blocks are pushed to the `blocklist` address list on every MikroTik, where the
generated firewall drops them in RAW. Only entries commented 'isp-block:' are ever added or removed.
"""
import ipaddress
import logging
from concurrent.futures import ThreadPoolExecutor

from .. import audit, config, db
from ..security import decrypt_json
from . import devices as dev

log = logging.getLogger(__name__)
COMMENT = "isp-block:"
ENFORCE_SCRIPT = (
    ':local r "isp-platform: blocklisted (brute force / port scan)"\n'
    ':if ([:len [/ip firewall raw find]] > 0) do={\n'
    '  /ip firewall raw add chain=prerouting action=drop src-address-list=blocklist comment=$r place-before=0\n'
    '} else={\n'
    '  /ip firewall raw add chain=prerouting action=drop src-address-list=blocklist comment=$r\n'
    '}\n'
)


class Protected(ValueError):
    pass


def protected_reason(conn, network) -> str | None:
    """Why `network` must not be blocked, or None. Applies to auto and manual blocks alike."""
    net = ipaddress.ip_network(network, strict=False)
    for n in config.THREAT_NEVER_BLOCK:
        if net.overlaps(ipaddress.ip_network(n, strict=False)):
            return f"overlaps never-block network {n}"
    for row in conn.execute("SELECT name, host(management_ip) AS ip FROM devices WHERE management_ip IS NOT NULL"):
        if ipaddress.ip_address(row["ip"]) in net:
            return f"contains the management IP of {row['name']}"
    for row in conn.execute("SELECT shortname, nasname FROM nas"):
        try:
            if ipaddress.ip_address(row["nasname"]) in net:
                return f"contains RADIUS client {row['shortname']}"
        except ValueError:
            pass
    return None


def auto_blockable(ip: str) -> bool:
    # is_global is False for RFC1918, CGNAT 100.64/10, loopback, link-local, documentation ranges...
    return ipaddress.ip_address(ip).is_global


def record_events(conn, device: dict, events: list[dict], cursor):
    for e in events:
        try:
            ipaddress.ip_address(e["src_ip"])
        except ValueError:
            continue
        conn.execute(
            "INSERT INTO security_events(device_id,kind,src_ip,username,via,message) VALUES (%s,'login_failure',%s,%s,%s,%s)",
            (device["id"], e["src_ip"], e.get("username"), e.get("via"), e.get("message")),
        )
    if cursor is not None:
        conn.execute("UPDATE devices SET log_cursor=%s WHERE id=%s", (cursor, device["id"]))


def _active_covering(conn, ip) -> bool:
    return conn.execute("SELECT 1 FROM blocked_addresses WHERE removed_at IS NULL AND address >>= %s::inet LIMIT 1",
                        (str(ip),)).fetchone() is not None


def add_block(conn, address: str, reason: str, source: str, actor: str, hours: int | None, hits: int = 0) -> dict:
    net = ipaddress.ip_network(address, strict=False)
    if why := protected_reason(conn, net):
        raise Protected(f"{net} is protected: {why}")
    row = conn.execute(
        """INSERT INTO blocked_addresses(address,reason,source,created_by,hits,expires_at)
           VALUES (%s,%s,%s,%s,%s, CASE WHEN %s::int IS NULL THEN NULL ELSE now() + make_interval(hours => %s::int) END)
           ON CONFLICT (address) WHERE removed_at IS NULL DO NOTHING RETURNING *""",
        (str(net), reason, source, actor, hits, hours, hours),
    ).fetchone()
    if row:
        audit.record(actor, f"threat.block_{source}", "address", str(net), {"reason": reason, "hours": hours}, conn=conn)
    return row


def remove_block(conn, block_id: int, actor: str, why: str = "manual") -> bool:
    row = conn.execute("UPDATE blocked_addresses SET removed_at=now(), removed_by=%s WHERE id=%s AND removed_at IS NULL RETURNING address",
                       (actor if why == "manual" else why, block_id)).fetchone()
    if row and why == "manual":
        audit.record(actor, "threat.unblock", "address", str(row["address"]), conn=conn)
    return row is not None


def evaluate(conn, notify=None) -> dict:
    """Expire old blocks, create new auto-blocks, merge rotating attackers into /24s."""
    result = {"blocked": [], "merged": [], "expired": 0, "internal": []}
    result["expired"] = conn.execute(
        "UPDATE blocked_addresses SET removed_at=now(), removed_by='expired' WHERE removed_at IS NULL AND expires_at < now()"
    ).rowcount
    conn.execute(
        """UPDATE blocked_addresses b SET hits = (SELECT count(*) FROM security_events e
               WHERE e.src_ip <<= b.address AND e.at >= b.created_at - make_interval(mins => %s))
           WHERE removed_at IS NULL""", (config.THREAT_WINDOW_MIN,))
    if not config.THREAT_AUTO_BLOCK:
        return result
    offenders = conn.execute(
        """SELECT host(src_ip) AS ip, count(*) AS n, count(DISTINCT device_id) AS devices, array_agg(DISTINCT username) AS users,
                  (array_agg(device_id ORDER BY at DESC))[1] AS last_device_id
           FROM security_events WHERE kind='login_failure' AND at > now() - make_interval(mins => %s)
           GROUP BY src_ip HAVING count(*) >= %s""",
        (config.THREAT_WINDOW_MIN, config.THREAT_FAILURES),
    ).fetchall()
    for o in offenders:
        if _active_covering(conn, o["ip"]):
            continue
        if not auto_blockable(o["ip"]):
            result["internal"].append(o)  # inside our own network: alert a human, never auto-block
            continue
        reason = f"{o['n']} failed router logins in {config.THREAT_WINDOW_MIN} min on {o['devices']} router(s), users: {', '.join(sorted(u for u in o['users'] if u))[:80]}"
        try:
            row = add_block(conn, o["ip"], reason, "auto", "system", config.THREAT_BLOCK_HOURS, o["n"])
        except Protected as exc:
            log.warning("not blocking: %s", exc)
            continue
        if row:
            result["blocked"].append(str(row["address"]))
    # Rotating attackers (one /24, many IPs): replace the /32s with one /24 block.
    for s in conn.execute(
        """SELECT set_masklen(address::inet, 24)::cidr AS net, count(*) AS n, array_agg(id) AS ids, sum(hits) AS hits
           FROM blocked_addresses WHERE removed_at IS NULL AND source='auto' AND masklen(address)=32 AND family(address)=4
           GROUP BY 1 HAVING count(*) >= %s""", (config.THREAT_SUBNET_AFTER,)).fetchall():
        try:
            row = add_block(conn, str(s["net"]), f"{s['n']} attacking hosts in this /24", "auto", "system",
                            config.THREAT_BLOCK_HOURS, s["hits"])
        except Protected as exc:
            log.warning("not merging: %s", exc)
            continue
        if row:
            conn.execute("UPDATE blocked_addresses SET removed_at=now(), removed_by='merged' WHERE id = ANY(%s)", (s["ids"],))
            result["merged"].append(str(row["address"]))
    if notify:
        for a in result["blocked"] + result["merged"]:
            notify(f"[BLOCKED] {a} on all MikroTik routers (router login brute force)")
    return result


def desired_entries(conn) -> dict:
    rows = conn.execute(
        """SELECT address, reason, extract(epoch FROM expires_at - now())::bigint AS remaining
           FROM blocked_addresses WHERE removed_at IS NULL AND (expires_at IS NULL OR expires_at > now())""").fetchall()
    return {ipaddress.ip_network(str(r["address"])): (f"{COMMENT} {r['reason']}"[:120], r["remaining"]) for r in rows}


def _norm(address: str):
    try:
        return ipaddress.ip_network(address, strict=False)
    except ValueError:
        return None


def sync_router(ros, desired: dict) -> dict:
    """Make the router's platform-owned blocklist entries match `desired`. Never touches other entries."""
    ours = {}
    for e in ros.blocklist_entries():
        if str(e.get("comment", "")).startswith(COMMENT):
            ours.setdefault(_norm(e["address"]), []).append(e[".id"])
    added = removed = 0
    for net, ids in ours.items():
        if net not in desired:
            for i in ids:
                ros.blocklist_remove(i)
                removed += 1
    for net, (comment, remaining) in desired.items():
        if net not in ours:
            ros.blocklist_add(str(net) if net.prefixlen != net.max_prefixlen else str(net.network_address),
                              remaining, comment)
            added += 1
    return {"added": added, "removed": removed, "enforced": ros.blocklist_enforced()}


def sync_all(device_ids: list | None = None) -> dict:
    with db.connect() as conn:
        desired = desired_entries(conn)
        sql = """SELECT * FROM devices WHERE vendor='mikrotik' AND poll_enabled AND credentials_enc IS NOT NULL
                 AND status IN ('online','degraded')"""
        routers = conn.execute(sql + (" AND id = ANY(%s)" if device_ids else ""), (device_ids,) if device_ids else None).fetchall()
    # SNMP-only routers (RouterOS 6 / no API login) can be monitored but not written to
    routers = [d for d in routers if decrypt_json(d["credentials_enc"]).get("username")]

    def one(d):
        try:
            with dev.mikrotik(d) as ros:
                return d, sync_router(ros, desired), None
        except Exception as exc:
            return d, None, f"{type(exc).__name__}: {exc}"[:300]

    with ThreadPoolExecutor(max_workers=config.POLL_WORKERS) as pool:
        results = list(pool.map(one, routers))
    summary = {"routers": len(results), "errors": 0, "added": 0, "removed": 0, "not_enforced": 0}
    with db.connect() as conn:
        for d, r, err in results:
            if err:
                summary["errors"] += 1
                conn.execute("UPDATE devices SET blocklist_error=%s WHERE id=%s", (err, d["id"]))
                continue
            summary["added"] += r["added"]
            summary["removed"] += r["removed"]
            summary["not_enforced"] += not r["enforced"]
            conn.execute("UPDATE devices SET blocklist_enforced=%s, blocklist_synced_at=now(), blocklist_error=NULL WHERE id=%s",
                         (r["enforced"], d["id"]))
    return summary

