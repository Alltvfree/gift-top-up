"""Keep FreeRADIUS SQL tables in step with subscribers and plans.

  active     -> password + Simultaneous-Use 1, group plan:<id> (Mikrotik-Rate-Limit)
  suspended  -> same password, group 'suspended' (256k + address-list=suspended -> payment page)
  pending    -> password kept, Auth-Type := Reject
  cancelled  -> every RADIUS row removed
After a state change the open session is disconnected (RFC 5176) so the router re-authenticates.
"""
import logging

from ..adapters import radius_coa

log = logging.getLogger(__name__)


def plan_group(plan_id) -> str:
    return f"plan:{plan_id}"


def rate_limit(upload_mbps: int, download_mbps: int) -> str:
    # MikroTik rate-limit is rx/tx from the router's view: rx = customer upload.
    return f"{upload_mbps}M/{download_mbps}M"


def sync_plan(conn, plan: dict):
    group = plan_group(plan["id"])
    conn.execute("DELETE FROM radgroupreply WHERE groupname=%s", (group,))
    conn.execute(
        "INSERT INTO radgroupreply(groupname,attribute,op,value) VALUES (%s,'Mikrotik-Rate-Limit',':=',%s)",
        (group, rate_limit(plan["upload_mbps"], plan["download_mbps"])),
    )


def _set(conn, table, username, attribute, op, value):
    conn.execute(f"DELETE FROM {table} WHERE username=%s AND attribute=%s", (username, attribute))
    if value is not None:
        conn.execute(f"INSERT INTO {table}(username,attribute,op,value) VALUES (%s,%s,%s,%s)",
                     (username, attribute, op, value))


def sync_subscriber(conn, sub: dict, password: str | None = None, old_username: str | None = None):
    user = sub["pppoe_username"]
    if old_username and old_username != user:
        purge(conn, old_username)
    if not user:
        return
    if sub["status"] == "cancelled":
        purge(conn, user)
        return
    if password is not None:
        _set(conn, "radcheck", user, "Cleartext-Password", ":=", password)
    _set(conn, "radcheck", user, "Simultaneous-Use", ":=", "1")
    _set(conn, "radcheck", user, "Auth-Type", ":=", "Reject" if sub["status"] == "pending" else None)
    _set(conn, "radreply", user, "Framed-IP-Address", ":=", str(sub["static_ip"]) if sub.get("static_ip") else None)
    conn.execute("DELETE FROM radusergroup WHERE username=%s", (user,))
    group = "suspended" if sub["status"] == "suspended" else (plan_group(sub["plan_id"]) if sub.get("plan_id") else None)
    if group:
        conn.execute("INSERT INTO radusergroup(username,groupname,priority) VALUES (%s,%s,1)", (user, group))


def purge(conn, username: str):
    for table in ("radcheck", "radreply", "radusergroup"):
        conn.execute(f"DELETE FROM {table} WHERE username=%s", (username,))


def disconnect(conn, username: str) -> list[dict]:
    """Send Disconnect-Request for every open session of `username`. Call after commit."""
    sessions = conn.execute(
        """SELECT a.acctsessionid, host(a.nasipaddress) AS nas_ip, host(a.framedipaddress) AS framed_ip, n.secret
           FROM radacct a LEFT JOIN nas n ON n.nasname=host(a.nasipaddress)
           WHERE a.username=%s AND a.acctstoptime IS NULL""",
        (username,),
    ).fetchall()
    results = []
    for s in sessions:
        if not s["secret"]:
            results.append({"nas": s["nas_ip"], "result": "no NAS secret configured"})
            continue
        try:
            outcome = radius_coa.send(s["nas_ip"], s["secret"], username=username,
                                      session_id=s["acctsessionid"], framed_ip=s["framed_ip"])
        except OSError as exc:
            outcome = f"error: {exc}"
        log.info("disconnect %s on %s: %s", username, s["nas_ip"], outcome)
        results.append({"nas": s["nas_ip"], "result": outcome})
    return results
