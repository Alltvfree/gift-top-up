"""Pull and store device configuration backups (MikroTik /export, Huawei display current-configuration).

Three ways a backup gets taken, which all stay available side by side rather than replacing one
another:
  manual        the "Back up now" button
  scheduled     the worker, every BACKUP_INTERVAL_HOURS -- or a device's own
                settings.backup_interval_hours, which overrides the default (0 disables scheduled
                backups for just that device; everything else still applies)
  after_change  automatically, the moment a config_changes apply finishes (applied, failed or
                rolled back -- the resulting state is worth capturing either way);
                settings.backup_after_change: false opts a device out

Stored gzip-compressed then Fernet-encrypted (the same key that protects device credentials),
because a MikroTik export with show-sensitive carries real passwords. Only ever decrypted for a
download, never shown in the UI or logged. The newest BACKUP_KEEP_PER_DEVICE per device are kept;
older ones are pruned after every successful backup.
"""
import gzip
import logging
import re
from datetime import datetime, timezone

from .. import config, db
from ..security import decrypt_bytes, decrypt_json, encrypt_bytes
from . import devices as dev

log = logging.getLogger(__name__)
CAPABLE_VENDORS = ("mikrotik", "huawei")


def capable(device: dict) -> bool:
    """Whether a config backup can even be attempted: a stored login, not just an SNMP community."""
    if device["vendor"] == "mikrotik":
        return bool(decrypt_json(device.get("credentials_enc")).get("username"))
    if device["vendor"] == "huawei":
        return bool(device.get("credentials_enc"))
    return False


def _pull(device: dict) -> tuple[str, str]:
    """(config text, filename). The device name is free text, so the filename is sanitised: it
    ends up in a Content-Disposition header on download."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", device["name"]).strip("-")[:60] or "device"
    if device["vendor"] == "mikrotik":
        if not decrypt_json(device.get("credentials_enc")).get("username"):
            raise RuntimeError("Backups need the router's REST login (SNMP-only monitoring cannot export a config)")
        with dev.mikrotik(device) as ros:
            text = ros.export_config()
        return text, f"{safe_name}-{stamp}.rsc"
    with dev.olt(device) as olt:
        text = olt.query("display current-configuration")
    return text, f"{safe_name}-{stamp}.cfg"


def take(conn, device: dict, source: str, actor: str | None = None, change_id: int | None = None) -> dict:
    """Pull a backup now and store it. Never raises: a failure is stored as a row too, so the
    history (and why the last attempt didn't work) stays visible in the UI."""
    row = {"device_id": device["id"], "source": source, "taken_by": actor, "change_id": change_id}
    try:
        text, filename = _pull(device)
        if not text.strip():
            raise RuntimeError("Empty configuration read back")
        blob = encrypt_bytes(gzip.compress(text.encode()))
        saved = conn.execute(
            """INSERT INTO device_backups(device_id,source,taken_by,change_id,ok,filename,size_bytes,content_enc)
               VALUES (%(device_id)s,%(source)s,%(taken_by)s,%(change_id)s,true,%(filename)s,%(size)s,%(blob)s)
               RETURNING id,taken_at""",
            {**row, "filename": filename, "size": len(text.encode()), "blob": blob},
        ).fetchone()
        _prune(conn, device["id"])
        log.info("backup taken: %s (%s, %d bytes, %s)", device["name"], source, len(text), filename)
        return {"ok": True, "id": saved["id"], "taken_at": saved["taken_at"], "filename": filename, "size_bytes": len(text.encode())}
    except Exception as exc:
        err = f"{type(exc).__name__}: {exc}"[:500]
        conn.execute(
            "INSERT INTO device_backups(device_id,source,taken_by,change_id,ok,error) VALUES (%(device_id)s,%(source)s,%(taken_by)s,%(change_id)s,false,%(err)s)",
            {**row, "err": err},
        )
        log.warning("backup failed: %s (%s): %s", device["name"], source, err)
        return {"ok": False, "error": err}


def _prune(conn, device_id):
    conn.execute(
        """DELETE FROM device_backups WHERE device_id=%s AND id NOT IN
           (SELECT id FROM device_backups WHERE device_id=%s ORDER BY taken_at DESC LIMIT %s)""",
        (device_id, device_id, config.BACKUP_KEEP_PER_DEVICE),
    )


def after_change(device: dict, actor: str, change_id: int):
    """Called once a change has finished applying to `device` (any resulting status)."""
    if not capable(device) or (device.get("settings") or {}).get("backup_after_change") is False:
        return
    with db.connect() as conn:
        take(conn, device, "after_change", actor, change_id)


def _interval_hours(device: dict) -> int:
    v = (device.get("settings") or {}).get("backup_interval_hours")
    try:
        return int(v) if v is not None else config.BACKUP_INTERVAL_HOURS
    except (TypeError, ValueError):
        return config.BACKUP_INTERVAL_HOURS  # a stray non-numeric setting never breaks scheduling


def due_for_scheduled(conn) -> list[dict]:
    """Capable devices whose own interval has elapsed since their last backup (of any source)."""
    devices = conn.execute(
        """SELECT d.*, (SELECT max(taken_at) FROM device_backups b WHERE b.device_id=d.id) AS last_backup_at
           FROM devices d WHERE d.vendor = ANY(%s) AND d.credentials_enc IS NOT NULL""",
        (list(CAPABLE_VENDORS),),
    ).fetchall()
    now = datetime.now(timezone.utc)
    due = []
    for d in devices:
        if not capable(d):
            continue
        hours = _interval_hours(d)
        if hours <= 0:
            continue
        if not d["last_backup_at"] or (now - d["last_backup_at"]).total_seconds() >= hours * 3600:
            due.append(d)
    return due


def run_scheduled() -> dict:
    from concurrent.futures import ThreadPoolExecutor
    with db.connect() as conn:
        devices = due_for_scheduled(conn)
    if not devices:
        return {"attempted": 0, "ok": 0, "failed": 0}

    def one(d):
        with db.connect() as conn:
            return take(conn, d, "scheduled")
    with ThreadPoolExecutor(max_workers=config.POLL_WORKERS) as pool:
        results = list(pool.map(one, devices))
    out = {"attempted": len(results), "ok": sum(r["ok"] for r in results), "failed": sum(not r["ok"] for r in results)}
    log.info("scheduled backups: %s", out)
    return out


def content(conn, backup_id: int) -> tuple[bytes, str] | None:
    """(decrypted config bytes, filename) for a successful backup, or None."""
    row = conn.execute("SELECT content_enc, filename FROM device_backups WHERE id=%s AND ok", (backup_id,)).fetchone()
    if not row or not row["content_enc"]:
        return None
    return gzip.decompress(decrypt_bytes(row["content_enc"])), row["filename"]
