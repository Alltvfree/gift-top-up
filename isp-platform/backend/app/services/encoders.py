"""IP video encoder incident workflow: layered diagnosis (video/audio), consecutive-failure
counting, incident open/close, and a rate-limited, opt-in, config-required recovery hook.

No automatic restart is ever attempted unless an admin has configured AND marked "verified" a
restart adapter for that specific encoder (settings.restart_adapter.verified = true) -- per the
project's own principle: identify and manually test a model's real restart mechanism first, never
guess an undocumented endpoint. Until then, every incident just sits there for a human to act on
(portal alert + Telegram), exactly as if auto-recovery were off.
"""
import logging
from datetime import datetime, timezone

from psycopg.types.json import Jsonb

from .. import audit
from ..adapters import encoder as enc
from ..security import decrypt_json
from . import olt_access, telegram

log = logging.getLogger(__name__)

DEFAULTS = {
    "rtsp_port": 554, "rtsp_path": "/", "audio_threshold_db": -50.0,
    "video_fail_checks": 1, "audio_fail_checks": 3,
    "max_reboots_per_hour": 2, "reboot_cooldown_min": 5, "recovery_verify_s": 60, "auto_recovery": False,
}


class RestartNotConfigured(Exception):
    pass


def settings_of(device: dict) -> dict:
    return {**DEFAULTS, **(device.get("settings") or {})}


def rtsp_url(device: dict) -> str:
    s = settings_of(device)
    if (device.get("settings") or {}).get("via_router"):
        host, _ = olt_access.endpoint(device)
    else:
        host = str(device["management_ip"])
    creds = decrypt_json(device.get("credentials_enc")) if device.get("credentials_enc") else {}
    return enc.build_rtsp_url(host, int(s["rtsp_port"]), s["rtsp_path"], creds.get("username"), creds.get("password"))


def check(device: dict) -> dict:
    """{"video": {...}, "audio": {...}}, each with at least "ok" and (on failure) "reason"."""
    url = rtsp_url(device)
    tracks = enc.probe_tracks(url)
    if not tracks["ok"]:
        return {"video": {"ok": False, "reason": tracks["error"]}, "audio": {"ok": False, "reason": "stream did not open"}}
    video = {"ok": tracks["has_video"], "codec": tracks.get("video_codec")}
    if not video["ok"]:
        video["reason"] = "no video track"
    if not tracks["has_audio"]:
        return {"video": video, "audio": {"ok": False, "reason": "no audio track"}}
    level = enc.audio_level(url)
    if not level["ok"]:
        return {"video": video, "audio": {"ok": False, "reason": level["error"], "codec": tracks.get("audio_codec")}}
    threshold = float(settings_of(device)["audio_threshold_db"])
    silent = level["mean_db"] <= threshold
    audio = {"ok": not silent, "mean_db": level["mean_db"], "peak_db": level["peak_db"], "threshold_db": threshold,
             "codec": tracks.get("audio_codec")}
    if silent:
        audio["reason"] = f"mean level {level['mean_db']} dB at/below threshold {threshold} dB"
    return {"video": video, "audio": audio}


def _consecutive_fails(conn, device_id, kind: str, n: int) -> bool:
    if n <= 1:
        return True
    rows = conn.execute(
        "SELECT (extra->'encoder'->%s->>'ok')::boolean AS ok FROM device_metrics WHERE device_id=%s ORDER BY at DESC LIMIT %s",
        (kind, device_id, n)).fetchall()
    return len(rows) >= n and all(r["ok"] is False for r in rows)


def _open_incident(conn, device, kind, diagnosis) -> int | None:
    row = conn.execute(
        """INSERT INTO encoder_incidents(device_id,kind,severity,diagnosis) VALUES (%s,%s,'warning',%s)
           ON CONFLICT (device_id,kind) WHERE closed_at IS NULL DO NOTHING RETURNING id""",
        (device["id"], kind, Jsonb(diagnosis))).fetchone()
    if row:
        telegram.alert(conn, f"[WARNING] {device['name']}: {kind} failure -- {diagnosis.get('reason', 'see incident')}")
    return row["id"] if row else None


def _close_incident(conn, device, kind, reason="self_recovered"):
    row = conn.execute(
        """UPDATE encoder_incidents SET closed_at=now(), closed_reason=%s WHERE device_id=%s AND kind=%s AND closed_at IS NULL
           RETURNING id""", (reason, device["id"], kind)).fetchone()
    if row:
        telegram.alert(conn, f"[RESOLVED] {device['name']}: {kind} recovered ({reason})")
    return row["id"] if row else None


def _reboots_in_last_hour(conn, device_id) -> int:
    return conn.execute(
        "SELECT count(*) AS n FROM encoder_incidents WHERE device_id=%s AND recovery_action='auto_restart' AND recovery_at > now() - interval '1 hour'",
        (device_id,)).fetchone()["n"]


def _in_cooldown(conn, device_id, cooldown_min) -> bool:
    row = conn.execute(
        "SELECT max(recovery_at) AS t FROM encoder_incidents WHERE device_id=%s AND recovery_action IS NOT NULL", (device_id,)).fetchone()
    return bool(row["t"]) and (datetime.now(timezone.utc) - row["t"]).total_seconds() < cooldown_min * 60


def restart(device: dict) -> dict:
    """Run the configured restart adapter. Raises RestartNotConfigured if none is set or it has
    not been marked verified (an admin must test it manually first and set verified=true)."""
    adapter = (device.get("settings") or {}).get("restart_adapter")
    if not adapter:
        raise RestartNotConfigured(f"No restart method configured for {device['name']} yet. Inspect its web "
                                   "interface, identify the real restart request, test it manually, then set "
                                   "settings.restart_adapter (and verified: true) on this device.")
    if not adapter.get("verified"):
        raise RestartNotConfigured("A restart_adapter is configured but not marked verified=true -- "
                                   "test it manually on this device first, then set verified: true.")
    if adapter.get("type") == "http":
        import httpx
        r = httpx.request(adapter.get("method", "POST"), adapter["url"], timeout=10,
                          auth=tuple(adapter["basic_auth"]) if adapter.get("basic_auth") else None,
                          headers=adapter.get("headers"), content=adapter.get("body"))
        return {"ok": r.status_code < 400, "detail": f"HTTP {r.status_code}"}
    raise RestartNotConfigured(f"Unknown restart_adapter type {adapter.get('type')!r}")


def evaluate(conn, device: dict, result: dict):
    """Called once per poll with this cycle's check() result. Opens/closes incidents and, only if
    auto_recovery is on and a verified adapter exists, may attempt one rate-limited restart."""
    s = settings_of(device)
    any_failing = False
    for kind, checks in (("video", s["video_fail_checks"]), ("audio", s["audio_fail_checks"])):
        r = result.get(kind) or {}
        if r.get("ok"):
            _close_incident(conn, device, kind)
            continue
        if _consecutive_fails(conn, device["id"], kind, int(checks)):
            any_failing = True
            _open_incident(conn, device, kind, r)
    if not any_failing or not s["auto_recovery"]:
        return
    adapter = (device.get("settings") or {}).get("restart_adapter") or {}
    if not adapter.get("verified"):
        return  # nothing safe to do automatically; the open incident is the signal for a human
    if _in_cooldown(conn, device["id"], int(s["reboot_cooldown_min"])):
        return
    if _reboots_in_last_hour(conn, device["id"]) >= int(s["max_reboots_per_hour"]):
        log.warning("encoder %s: reboot rate limit reached, not retrying automatically", device["name"])
        return
    try:
        r = restart(device)
        result_text = r.get("detail", "ok") if r.get("ok") else f"failed: {r.get('detail')}"
    except Exception as exc:
        result_text = f"{type(exc).__name__}: {exc}"
    conn.execute(
        """UPDATE encoder_incidents SET recovery_action='auto_restart', recovery_at=now(), recovery_by='auto', recovery_result=%s
           WHERE device_id=%s AND closed_at IS NULL""", (result_text[:300], device["id"]))
    audit.record("system", "encoder.auto_restart", "device", device["id"], {"result": result_text}, conn=conn)
    telegram.alert(conn, f"[AUTO-RESTART] {device['name']}: {result_text}")


def manual_restart(conn, device: dict, actor: str) -> dict:
    r = restart(device)  # raises RestartNotConfigured if unset/unverified -- caller turns that into a 400
    conn.execute(
        """UPDATE encoder_incidents SET recovery_action='manual_restart', recovery_at=now(), recovery_by=%s, recovery_result=%s
           WHERE device_id=%s AND closed_at IS NULL""", (actor, (r.get("detail") or "ok")[:300], device["id"]))
    audit.record(actor, "encoder.manual_restart", "device", device["id"], r, conn=conn)
    return r
