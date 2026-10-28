"""Apply an approved config change to its device."""
from .. import audit, config, db
from ..adapters.ping import ping
from . import devices as dev


def apply(change_id: int, actor: str) -> dict:
    with db.connect() as conn:
        ch = conn.execute(
            "UPDATE config_changes SET status='applying' WHERE id=%s AND status='approved' RETURNING *", (change_id,)
        ).fetchone()
        if not ch:
            return {"ok": False, "detail": "Change is not in 'approved' state"}
        device = conn.execute("SELECT * FROM devices WHERE id=%s", (ch["device_id"],)).fetchone()
    status, result = "failed", ""
    try:
        if ch["kind"] == "mikrotik_script":
            with dev.mikrotik(device) as ros:
                result = ros.apply_with_commit_confirm(
                    ch["id"], ch["plan"], config.COMMIT_CONFIRM_MINUTES,
                    lambda: ping(str(device["management_ip"]))["reachable"],
                )
            status = "applied"
        else:
            with dev.olt(device) as olt:
                try:
                    result = olt.run_lines([ln for ln in ch["plan"].splitlines() if ln.strip()])
                    status = "applied"
                except Exception as exc:
                    result = f"apply failed: {exc}\n"
                    if ch["rollback"]:
                        result += olt.run_lines([ln for ln in ch["rollback"].splitlines() if ln.strip()])
                        status = "rolled_back"
    except Exception as exc:
        result = (result + "\n" if result else "") + f"{type(exc).__name__}: {exc}"
    with db.connect() as conn:
        conn.execute("UPDATE config_changes SET status=%s, result=%s, applied_at=now() WHERE id=%s",
                     (status, result[-20000:], change_id))
        audit.record(actor, f"change.{status}", "config_change", change_id, {"device": device["name"]}, conn=conn)
    return {"ok": status == "applied", "status": status, "result": result}
