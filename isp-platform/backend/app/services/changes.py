"""Change workflow rules (approve / reject / apply), shared by the web API and the Telegram bot."""
from .. import audit, config, db
from ..adapters.ping import ping
from . import devices as dev
from . import telegram


class ChangeError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


def approval_problem(ch: dict | None, username: str, via: str) -> ChangeError | None:
    """Why `username` may not approve `ch` through `via` ('web' or 'telegram'), or None."""
    if not ch or ch["status"] != "pending":
        return ChangeError(409, "Only pending changes can be approved")
    if config.FOUR_EYES and ch["requested_by"] == username and not (via == "telegram" and config.SELF_APPROVE_VIA_TELEGRAM):
        hint = " (or approve it yourself in Telegram with your 2FA code)" if config.SELF_APPROVE_VIA_TELEGRAM else ""
        return ChangeError(403, "Four-eyes rule: someone else must approve your change" + hint)
    return None


def approve(conn, change_id: int, username: str, via: str = "web"):
    ch = conn.execute("SELECT * FROM config_changes WHERE id=%s FOR UPDATE", (change_id,)).fetchone()
    if problem := approval_problem(ch, username, via):
        raise problem
    conn.execute("UPDATE config_changes SET status='approved', approved_by=%s WHERE id=%s", (username, change_id))
    audit.record(username, "change.approve", "config_change", change_id, {"via": via}, conn=conn)
    telegram.change_updated(conn, change_id)
    if ch["requested_by"] != username:
        telegram.tell_user(conn, ch["requested_by"], f"Change #{change_id} \"{ch['title']}\" was approved by {username}.")


def reject(conn, change_id: int, username: str, via: str = "web"):
    ch = conn.execute("""UPDATE config_changes SET status='rejected', approved_by=%s
                         WHERE id=%s AND status IN ('pending','approved') RETURNING *""", (username, change_id)).fetchone()
    if not ch:
        raise ChangeError(409, "Change cannot be rejected now")
    audit.record(username, "change.reject", "config_change", change_id, {"via": via}, conn=conn)
    telegram.change_updated(conn, change_id)
    if ch["requested_by"] != username:
        telegram.tell_user(conn, ch["requested_by"], f"Change #{change_id} \"{ch['title']}\" was rejected by {username}.")


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
        telegram.change_updated(conn, change_id)
        if ch["requested_by"] != actor:
            telegram.tell_user(conn, ch["requested_by"], f"Change #{change_id} \"{ch['title']}\" on {device['name']}: {status} (by {actor}).")
    return {"ok": status == "applied", "status": status, "result": result}
