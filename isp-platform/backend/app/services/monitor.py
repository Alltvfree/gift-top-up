"""Polling engine: ping every device, then vendor-specific health; derive status, alerts, rollups."""
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import httpx
from psycopg.types.json import Jsonb

from .. import config, db
from ..adapters import airfiber
from ..adapters.ping import ping
from ..security import decrypt_json
from . import devices as dev

log = logging.getLogger(__name__)


def classify(m: dict) -> str:
    if not m["reachable"]:
        return "offline"
    if (m.get("packet_loss_pct") or 0) >= 20 or (m.get("latency_ms") or 0) > config.LATENCY_WARN_MS \
            or (m.get("cpu_load_pct") or 0) >= 90 or m.get("error"):
        return "degraded"
    return "online"


def poll_device(device: dict, with_olt: bool = False) -> dict:
    m = {"reachable": False, "extra": {}}
    if not device.get("management_ip"):
        return {**m, "error": "no management IP"}
    m.update(ping(str(device["management_ip"])))
    if not m["reachable"]:
        return m
    try:
        if device["vendor"] == "mikrotik" and device.get("credentials_enc"):
            with dev.mikrotik(device) as ros:
                r = ros.poll()
            m.update({k: v for k, v in r.items() if k != "extra"})
            m["extra"].update(r["extra"])
            if r["extra"]["interfaces_down"]:
                m["error"] = "interfaces down: " + ", ".join(r["extra"]["interfaces_down"])
        elif device["vendor"] == "ubiquiti":
            community = decrypt_json(device.get("credentials_enc")).get("snmp_community")
            if community:
                r = airfiber.poll(str(device["management_ip"]), community)
                m["uptime_s"] = r["uptime_s"]
                m["extra"].update(r["extra"])
        elif device["vendor"] == "huawei" and device["role"] == "olt" and with_olt and device.get("credentials_enc"):
            m["extra"]["onts"] = poll_olt(device)
    except Exception as exc:  # one broken device must never stop the sweep
        m["error"] = f"{type(exc).__name__}: {exc}"[:300]
    return m


def poll_olt(device: dict) -> list[dict]:
    slots = (device.get("settings") or {}).get("gpon_slots") or [1]
    found = []
    with dev.olt(device) as olt:
        for slot in slots:
            for o in olt.ont_list(0, int(slot)):
                if o["run_state"] == "online":
                    o.update(olt.optical(o["frame"], o["slot"], o["port"], o["ont_id"]))
                found.append(o)
    return found


def _notify(text: str):
    if not config.ALERT_WEBHOOK_URL:
        return
    try:
        httpx.post(config.ALERT_WEBHOOK_URL, json={"text": text}, timeout=5)
    except httpx.HTTPError as exc:
        log.warning("alert webhook failed: %s", exc)


def _alert(conn, device, kind, severity, message, active: bool):
    if active:
        row = conn.execute(
            """INSERT INTO alerts(device_id,island_id,severity,kind,message) VALUES (%s,%s,%s,%s,%s)
               ON CONFLICT (device_id,kind) WHERE resolved_at IS NULL DO NOTHING RETURNING id""",
            (device["id"], device["island_id"], severity, kind, message),
        ).fetchone()
        if row:
            _notify(f"[{severity.upper()}] {device['name']}: {message}")
    else:
        row = conn.execute(
            "UPDATE alerts SET resolved_at=now() WHERE device_id=%s AND kind=%s AND resolved_at IS NULL RETURNING id",
            (device["id"], kind),
        ).fetchone()
        if row:
            _notify(f"[RESOLVED] {device['name']}: {kind}")


def store(conn, device: dict, m: dict):
    status = classify(m)
    extra = dict(m.get("extra") or {})
    onts = extra.pop("onts", None)
    if m.get("error"):
        extra["error"] = m["error"]
    conn.execute(
        """INSERT INTO device_metrics(device_id,reachable,latency_ms,packet_loss_pct,cpu_load_pct,mem_used_pct,uptime_s,extra)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
        (device["id"], m["reachable"], m.get("latency_ms"), m.get("packet_loss_pct"), m.get("cpu_load_pct"),
         m.get("mem_used_pct"), m.get("uptime_s"), Jsonb(extra)),
    )
    conn.execute(
        """UPDATE devices SET status=%s, last_poll_error=%s,
           last_seen_at=CASE WHEN %s THEN now() ELSE last_seen_at END,
           software_version=COALESCE(%s, software_version), model=COALESCE(model, %s) WHERE id=%s""",
        (status, m.get("error"), m["reachable"], extra.get("version"), extra.get("board"), device["id"]),
    )
    _alert(conn, device, "unreachable", "critical", "Device not answering ping", status == "offline")
    _alert(conn, device, "degraded", "warning",
           m.get("error") or f"loss {m.get('packet_loss_pct')}% / latency {m.get('latency_ms')} ms / cpu {m.get('cpu_load_pct')}%",
           status == "degraded")
    if onts is not None:
        store_onts(conn, device, onts)
    return status


def store_onts(conn, device, onts):
    for o in onts:
        conn.execute(
            """INSERT INTO onts(olt_device_id,frame,slot,port,ont_id,serial,run_state,rx_power_dbm,olt_rx_power_dbm,last_seen_at)
               VALUES (%(olt)s,%(frame)s,%(slot)s,%(port)s,%(ont_id)s,%(serial)s,%(run_state)s,%(rx)s,%(olt_rx)s,
                       CASE WHEN %(run_state)s='online' THEN now() END)
               ON CONFLICT (olt_device_id,serial) DO UPDATE SET frame=EXCLUDED.frame, slot=EXCLUDED.slot, port=EXCLUDED.port,
                 ont_id=EXCLUDED.ont_id, run_state=EXCLUDED.run_state,
                 rx_power_dbm=COALESCE(EXCLUDED.rx_power_dbm, onts.rx_power_dbm),
                 olt_rx_power_dbm=COALESCE(EXCLUDED.olt_rx_power_dbm, onts.olt_rx_power_dbm),
                 last_seen_at=COALESCE(EXCLUDED.last_seen_at, onts.last_seen_at)""",
            {"olt": device["id"], **o, "rx": o.get("rx_power_dbm"), "olt_rx": o.get("olt_rx_power_dbm")},
        )
        rx = o.get("rx_power_dbm")
        _alert(conn, device, f"ont_low_rx:{o['serial']}", "warning",
               f"ONT {o['serial']} ({o['frame']}/{o['slot']}/{o['port']}:{o['ont_id']}) rx {rx} dBm",
               rx is not None and rx < config.ONT_LOW_RX_DBM)


def rollup(conn):
    conn.execute(
        """UPDATE islands i SET status = CASE
             WHEN s.total = 0 THEN 'unknown'
             WHEN s.offline = s.total THEN 'offline'
             WHEN s.offline > 0 OR s.degraded > 0 THEN 'degraded'
             WHEN s.online = s.total THEN 'online' ELSE 'unknown' END
           FROM (SELECT island_id, count(*) total,
                        count(*) FILTER (WHERE status='online') online,
                        count(*) FILTER (WHERE status='offline') offline,
                        count(*) FILTER (WHERE status='degraded') degraded
                 FROM devices WHERE poll_enabled GROUP BY island_id) s
           WHERE s.island_id = i.id""")
    conn.execute(
        """UPDATE backhaul_links l SET status = CASE
             WHEN a.status='offline' OR b.status='offline' THEN 'offline'
             WHEN a.status='degraded' OR b.status='degraded' THEN 'degraded'
             WHEN a.status='online' AND b.status='online' THEN 'online' ELSE 'unknown' END
           FROM devices a, devices b WHERE a.id=l.a_device_id AND b.id=l.b_device_id""")


def sweep(cycle: int = 0, device_ids: list | None = None) -> dict:
    sql = "SELECT * FROM devices WHERE poll_enabled"
    params = None
    if device_ids:
        sql += " AND id = ANY(%s)"
        params = (device_ids,)
    devices = db.rows(sql, params)
    with_olt = cycle % max(config.OLT_POLL_EVERY_N, 1) == 0
    with ThreadPoolExecutor(max_workers=config.POLL_WORKERS) as pool:
        results = list(pool.map(lambda d: (d, poll_device(d, with_olt)), devices))
    counts = {}
    with db.connect() as conn:
        for device, m in results:
            s = store(conn, device, m)
            counts[s] = counts.get(s, 0) + 1
        rollup(conn)
        conn.execute("DELETE FROM device_metrics WHERE at < now() - interval '90 days'")
        # NAS rebooted or link dropped without Accounting-Stop: close sessions silent for 3+ interim periods.
        conn.execute("""UPDATE radacct SET acctstoptime=now(), acctterminatecause='Stale-Session'
                        WHERE acctstoptime IS NULL AND coalesce(acctupdatetime, acctstarttime) < now() - interval '20 minutes'""")
    log.info("sweep %s at %s: %s", cycle, datetime.now(timezone.utc).isoformat(timespec="seconds"), counts)
    return counts
