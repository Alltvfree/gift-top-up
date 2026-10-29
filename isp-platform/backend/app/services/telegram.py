"""Telegram side of the platform: who gets what, account linking, and how a change looks in a chat.

The API and worker only write to telegram_outbox; the bot service (app.telegram_bot) sends it.
So nothing here talks to Telegram, and a Telegram outage never slows down the portal.
"""
import hashlib
import html
import secrets

from .. import audit, config
from ..deps import ROLES

LINK_MINUTES = 10
PLAN_CHARS = 2500  # Telegram messages are capped at 4096 characters
ICON = {"pending": "🟡", "approved": "🔵", "applying": "⏳", "applied": "✅", "failed": "❌",
        "rolled_back": "↩️", "rejected": "⛔"}


def enabled() -> bool:
    return bool(config.TELEGRAM_BOT_TOKEN)


def roles_with(permission: str) -> list[str]:
    return [r for r, perms in ROLES.items() if permission in perms]


def esc(v) -> str:
    return html.escape(str(v if v is not None else ""), quote=False)


# ---------------------------------------------------------------- outbox
def change_requested(conn, change_id: int):
    """Post a new change, with buttons, to every linked user who may approve it."""
    if not enabled():
        return
    ch = conn.execute("SELECT requested_by FROM config_changes WHERE id=%s", (change_id,)).fetchone()
    skip_requester = config.FOUR_EYES and not config.SELF_APPROVE_VIA_TELEGRAM
    for u in conn.execute(
            """SELECT telegram_chat_id FROM users WHERE active AND telegram_chat_id IS NOT NULL AND role = ANY(%s)
               AND NOT (%s AND username = %s)""", (roles_with("approve"), skip_requester, ch["requested_by"])):
        conn.execute("INSERT INTO telegram_outbox(kind,chat_id,change_id) VALUES ('change_request',%s,%s)",
                     (u["telegram_chat_id"], change_id))


def change_updated(conn, change_id: int):
    """The change's status moved: replace the buttons on every copy already posted."""
    if enabled():
        conn.execute("INSERT INTO telegram_outbox(kind,change_id) VALUES ('refresh',%s)", (change_id,))


def tell_user(conn, username: str, text: str):
    if not enabled():
        return
    u = conn.execute("SELECT telegram_chat_id FROM users WHERE username=%s AND active AND telegram_chat_id IS NOT NULL",
                     (username,)).fetchone()
    if u:
        conn.execute("INSERT INTO telegram_outbox(kind,chat_id,body) VALUES ('text',%s,%s)", (u["telegram_chat_id"], esc(text)))


def alert(conn, text: str):
    """Monitoring/threat alerts to linked network staff who keep alerts on."""
    if not enabled():
        return
    for u in conn.execute("""SELECT telegram_chat_id FROM users WHERE active AND telegram_chat_id IS NOT NULL
                             AND telegram_alerts AND role = ANY(%s)""", (roles_with("network"),)):
        conn.execute("INSERT INTO telegram_outbox(kind,chat_id,body) VALUES ('text',%s,%s)", (u["telegram_chat_id"], esc(text)))


# ---------------------------------------------------------------- linking
def _hash(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def new_link_code(conn, user_id) -> str:
    code = secrets.token_urlsafe(18)  # Telegram /start payloads allow A-Z a-z 0-9 _ -
    conn.execute("DELETE FROM telegram_link_codes WHERE user_id=%s OR expires_at < now()", (user_id,))
    conn.execute("INSERT INTO telegram_link_codes(code_hash,user_id,expires_at) VALUES (%s,%s,now() + make_interval(mins => %s))",
                 (_hash(code), user_id, LINK_MINUTES))
    return code


def link(conn, code: str, chat_id: int, name: str) -> dict | None:
    """Bind the Telegram chat to the user who generated `code`. One chat per user and one user per chat."""
    row = conn.execute("DELETE FROM telegram_link_codes WHERE code_hash=%s RETURNING user_id, expires_at > now() AS valid",
                       (_hash(code),)).fetchone()
    if not row or not row["valid"]:
        return None
    conn.execute("UPDATE users SET telegram_chat_id=NULL, telegram_linked_at=NULL WHERE telegram_chat_id=%s AND id<>%s",
                 (chat_id, row["user_id"]))
    user = conn.execute("""UPDATE users SET telegram_chat_id=%s, telegram_name=%s, telegram_linked_at=now()
                           WHERE id=%s AND active RETURNING id, username, role""", (chat_id, name[:120], row["user_id"])).fetchone()
    if user:
        audit.record(user["username"], "telegram.link", "user", user["id"], {"telegram": name}, conn=conn)
    return user


def unlink(conn, user_id, actor: str):
    conn.execute("DELETE FROM telegram_pending WHERE user_id=%s", (user_id,))
    row = conn.execute("""UPDATE users SET telegram_chat_id=NULL, telegram_name=NULL, telegram_linked_at=NULL
                          WHERE id=%s AND telegram_chat_id IS NOT NULL RETURNING id""", (user_id,)).fetchone()
    if row:
        audit.record(actor, "telegram.unlink", "user", user_id, conn=conn)
    return row is not None


def bot_username(conn) -> str | None:
    row = conn.execute("SELECT value FROM telegram_state WHERE key='bot_username'").fetchone()
    return row["value"] if row else None


# ---------------------------------------------------------------- rendering
def load_change(conn, change_id: int) -> dict | None:
    return conn.execute("""SELECT c.*, d.name AS device_name, i.name AS island_name FROM config_changes c
                           JOIN devices d ON d.id=c.device_id LEFT JOIN islands i ON i.id=d.island_id WHERE c.id=%s""",
                        (change_id,)).fetchone()


def render_change(ch: dict) -> tuple[str, list]:
    plan = ch["plan"] if len(ch["plan"]) <= PLAN_CHARS else ch["plan"][:PLAN_CHARS] + "\n… (cut, see the portal)"
    lines = [f"{ICON.get(ch['status'], '•')} <b>Change #{ch['id']}: {esc(ch['title'])}</b>",
             f"Device: <b>{esc(ch['device_name'])}</b>" + (f" ({esc(ch['island_name'])})" if ch.get("island_name") else ""),
             f"Requested by: {esc(ch['requested_by'])}",
             f"Status: <b>{esc(ch['status'])}</b>" + (f" by {esc(ch['approved_by'])}" if ch.get("approved_by") else "")]
    if config.PORTAL_URL:
        lines.append(f'<a href="{esc(config.PORTAL_URL)}/#/change/{ch["id"]}">Open in SatLink</a>')
    if ch["kind"] == "mikrotik_script":
        lines.append("<i>Apply makes a backup and arms an auto-restore on the router first.</i>")
    text = "\n".join(lines) + f"\n\n<pre>{esc(plan)}</pre>"
    if ch["status"] == "pending":
        keyboard = [[{"text": "✅ Approve", "callback_data": f"a:{ch['id']}"},
                     {"text": "🚀 Approve & apply", "callback_data": f"aa:{ch['id']}"}],
                    [{"text": "⛔ Reject", "callback_data": f"r:{ch['id']}"}]]
    elif ch["status"] == "approved":
        keyboard = [[{"text": "🚀 Apply now", "callback_data": f"x:{ch['id']}"},
                     {"text": "⛔ Reject", "callback_data": f"r:{ch['id']}"}]]
    else:
        keyboard = []
    return text, keyboard
