"""SatLink Telegram bot: approve, reject and apply config changes from a phone, and receive alerts.

  docker compose up -d telegram      (needs TELEGRAM_BOT_TOKEN in .env)

Security:
  * only private chats linked to an active platform user (My account -> Connect Telegram) are served;
  * the user's role is checked on every press, exactly as in the portal (four-eyes rule included);
  * approve and apply need the user's current 6-digit 2FA code, sent as the next message, which the bot
    deletes from the chat; 3 wrong codes cancel the action and count as failed sign-ins;
  * it long-polls Telegram (outbound HTTPS only), so the platform needs no public address.
"""
import logging
import re
import threading
import time

from . import audit, config, db, totp
from .adapters.telegram import Telegram, TelegramError
from .deps import ROLES
from .migrate import migrate
from .security import decrypt_json
from .services import changes, telegram as tg

log = logging.getLogger("telegram")
CODE_MINUTES = 3
CODE_ATTEMPTS = 3
ACTIONS = {"a": "approve", "aa": "approve_apply", "x": "apply", "r": "reject"}
VERB = {"approve": "approve", "approve_apply": "approve and apply", "apply": "apply"}
HELP = ("SatLink bot.\n/pending - changes waiting for approval\n/unlink - disconnect this chat from SatLink\n"
        "New change requests and alerts arrive here by themselves.")


class Bot:
    def __init__(self, api, background=True):
        self.api = api
        self.background = background  # tests run applies inline

    # ------------------------------------------------------------ updates
    def handle(self, update: dict):
        if "callback_query" in update:
            self.on_button(update["callback_query"])
        elif "message" in update:
            self.on_message(update["message"])

    @staticmethod
    def _user(conn, chat_id):
        return conn.execute("""SELECT id, username, role, active, totp_enabled, telegram_chat_id FROM users
                               WHERE telegram_chat_id=%s AND active""", (chat_id,)).fetchone()

    def on_button(self, cq: dict):
        chat = (cq.get("message") or {}).get("chat") or {}
        if chat.get("type") != "private" or chat.get("id") != cq["from"]["id"]:
            return self.api.answer_callback(cq["id"], "Use the bot in a private chat.")
        m = re.fullmatch(r"(aa|a|x|r):(\d+)", cq.get("data") or "")
        if not m:
            return self.api.answer_callback(cq["id"])
        action, change_id = ACTIONS[m.group(1)], int(m.group(2))
        with db.connect() as conn:
            user = self._user(conn, chat["id"])
            if not user:
                return self.api.answer_callback(cq["id"], "This Telegram account is not linked to SatLink.")
            need = {"approve", "network"} if action in ("apply", "approve_apply") else {"approve"}
            if not need <= ROLES.get(user["role"], set()):
                return self.api.answer_callback(cq["id"], f"Role '{user['role']}' may not do this.")
            if action == "reject":
                try:
                    changes.reject(conn, change_id, user["username"], via="telegram")
                except changes.ChangeError as exc:
                    return self.api.answer_callback(cq["id"], exc.detail)
                return self.api.answer_callback(cq["id"], f"Change #{change_id} rejected.")
            ch = conn.execute("SELECT * FROM config_changes WHERE id=%s", (change_id,)).fetchone()
            if action == "apply":
                problem = None if ch and ch["status"] == "approved" else "Only approved changes can be applied."
            else:
                problem = getattr(changes.approval_problem(ch, user["username"], "telegram"), "detail", None)
            if problem:
                return self.api.answer_callback(cq["id"], problem)
            if not user["totp_enabled"]:
                return self.api.answer_callback(cq["id"], "Set up two-factor in SatLink (My account) first.")
            conn.execute("""INSERT INTO telegram_pending(chat_id,user_id,change_id,action,expires_at)
                            VALUES (%s,%s,%s,%s,now() + make_interval(mins => %s))
                            ON CONFLICT (chat_id) DO UPDATE SET user_id=EXCLUDED.user_id, change_id=EXCLUDED.change_id,
                            action=EXCLUDED.action, attempts=0, expires_at=EXCLUDED.expires_at""",
                         (chat["id"], user["id"], change_id, action, CODE_MINUTES))
        self.api.answer_callback(cq["id"])
        self.api.send_message(chat["id"], f"🔐 To {VERB[action]} change #{change_id}, send your current 6-digit SatLink "
                                          f"code (authenticator app). Valid {CODE_MINUTES} minutes. /cancel to stop.",
                              force_reply=True)

    def on_message(self, msg: dict):
        chat = msg.get("chat") or {}
        if chat.get("type") != "private":
            return  # never act in groups
        chat_id, text = chat["id"], (msg.get("text") or "").strip()
        name = " ".join(x for x in ((msg.get("from") or {}).get("first_name"), (msg.get("from") or {}).get("last_name")) if x)
        if (msg.get("from") or {}).get("username"):
            name = f"{name} (@{msg['from']['username']})".strip()
        with db.connect() as conn:
            if text.startswith("/start"):
                code = text[6:].strip()
                if code:
                    user = tg.link(conn, code, chat_id, name or str(chat_id))
                    reply = (f"✅ Linked to SatLink user <b>{tg.esc(user['username'])}</b> ({tg.esc(user['role'])}).\n\n{tg.esc(HELP)}"
                             if user else "This link has expired or was already used. Make a new one in SatLink → My account.")
                else:
                    reply = ("Linked. " + tg.esc(HELP)) if self._user(conn, chat_id) else \
                        "To use this bot, open SatLink → My account → Connect Telegram."
                return self.api.send_message(chat_id, reply)
            user = self._user(conn, chat_id)
            if not user:
                return self.api.send_message(chat_id, "This chat is not linked. Open SatLink → My account → Connect Telegram.")
            if text in ("/unlink", "/stop"):
                tg.unlink(conn, user["id"], user["username"])
                return self.api.send_message(chat_id, "Disconnected from SatLink. You will get no more messages here.")
            if text == "/cancel":
                conn.execute("DELETE FROM telegram_pending WHERE chat_id=%s", (chat_id,))
                return self.api.send_message(chat_id, "Cancelled.")
            if text == "/pending":
                return self.send_pending(conn, user, chat_id)
            pending = conn.execute("SELECT * FROM telegram_pending WHERE chat_id=%s FOR UPDATE", (chat_id,)).fetchone()
            if not pending:
                return self.api.send_message(chat_id, tg.esc(HELP))
            reply, apply_change = self.confirm(conn, user, pending, text)
        self._delete(chat_id, msg.get("message_id"))  # do not leave 2FA codes in the chat history
        self.api.send_message(chat_id, reply)
        if apply_change:
            self._apply(chat_id, apply_change, user["username"])

    def confirm(self, conn, user, pending, text) -> tuple[str, int | None]:
        """Check the 2FA code for a pending action and carry it out. Returns (reply, change id to apply next)."""
        chat_id = pending["chat_id"]
        if conn.execute("SELECT now() > %s AS late", (pending["expires_at"],)).fetchone()["late"]:
            conn.execute("DELETE FROM telegram_pending WHERE chat_id=%s", (chat_id,))
            return "That request expired. Press the button again.", None
        u = conn.execute("""SELECT id, username, totp_secret_enc, totp_last_step, locked_until > now() AS locked
                            FROM users WHERE id=%s AND active AND totp_enabled FOR UPDATE""", (pending["user_id"],)).fetchone()
        if not u or u["locked"] or u["id"] != user["id"]:
            conn.execute("DELETE FROM telegram_pending WHERE chat_id=%s", (chat_id,))
            return "Your SatLink account is locked or has no two-factor. Sign in to the portal.", None
        step = totp.verify(decrypt_json(u["totp_secret_enc"])["secret"], text, u["totp_last_step"])
        if step is None:
            conn.execute("""UPDATE users SET failed_logins=failed_logins+1,
                            locked_until=CASE WHEN failed_logins+1>=%s THEN now()+make_interval(mins=>%s) ELSE locked_until END
                            WHERE id=%s""", (config.LOGIN_MAX_FAILURES_PER_USER, config.LOGIN_LOCK_MINUTES, u["id"]))
            audit.record(u["username"], "telegram.mfa_failed", "config_change", pending["change_id"], conn=conn)
            if pending["attempts"] + 1 >= CODE_ATTEMPTS:
                conn.execute("DELETE FROM telegram_pending WHERE chat_id=%s", (chat_id,))
                return "❌ Wrong code. Cancelled; press the button again to retry.", None
            conn.execute("UPDATE telegram_pending SET attempts=attempts+1 WHERE chat_id=%s", (chat_id,))
            return f"❌ Wrong code. {CODE_ATTEMPTS - pending['attempts'] - 1} tries left.", None
        conn.execute("UPDATE users SET totp_last_step=%s, failed_logins=0 WHERE id=%s", (step, u["id"]))
        conn.execute("DELETE FROM telegram_pending WHERE chat_id=%s", (chat_id,))
        change_id, action = pending["change_id"], pending["action"]
        if action in ("approve", "approve_apply"):
            try:
                changes.approve(conn, change_id, u["username"], via="telegram")
            except changes.ChangeError as exc:
                return f"Not approved: {tg.esc(exc.detail)}", None
            if action == "approve":
                return f"✅ Change #{change_id} approved.", None
        return f"⏳ Applying change #{change_id}… you will get the result here.", change_id

    def _apply(self, chat_id, change_id, username):
        def run():
            try:
                r = changes.apply(change_id, username)
                if "status" not in r:
                    text = f"Change #{change_id} was not applied: {tg.esc(r['detail'])}"
                else:
                    tail = (r.get("result") or "")[-1500:]
                    text = (f"{tg.ICON.get(r['status'], '•')} Change #{change_id}: <b>{tg.esc(r['status'])}</b>"
                            + (f"\n<pre>{tg.esc(tail)}</pre>" if tail.strip() else ""))
            except Exception as exc:  # never let an apply crash the bot
                log.exception("apply %s failed", change_id)
                text = f"❌ Change #{change_id}: {tg.esc(type(exc).__name__)}"
            self.api.send_message(chat_id, text)
        if self.background:
            threading.Thread(target=run, daemon=True).start()
        else:
            run()

    def send_pending(self, conn, user, chat_id):
        if "approve" not in ROLES.get(user["role"], set()):
            return self.api.send_message(chat_id, "Your role cannot approve changes.")
        rows = conn.execute("SELECT id FROM config_changes WHERE status IN ('pending','approved') ORDER BY id LIMIT 10").fetchall()
        if not rows:
            return self.api.send_message(chat_id, "Nothing waiting for approval.")
        for r in rows:
            self._post_change(conn, chat_id, r["id"])

    def _post_change(self, conn, chat_id, change_id):
        ch = tg.load_change(conn, change_id)
        if not ch:
            return
        text, keyboard = tg.render_change(ch)
        m = self.api.send_message(chat_id, text, keyboard)
        conn.execute("INSERT INTO telegram_change_messages(change_id,chat_id,message_id) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                     (change_id, chat_id, m["message_id"]))

    def _delete(self, chat_id, message_id):
        if message_id:
            try:
                self.api.delete_message(chat_id, message_id)
            except TelegramError:
                pass

    # ------------------------------------------------------------ outbox
    def flush_outbox(self) -> int:
        sent = 0
        with db.connect() as conn:
            conn.execute("DELETE FROM telegram_link_codes WHERE expires_at < now()")
            conn.execute("DELETE FROM telegram_pending WHERE expires_at < now() - interval '1 hour'")
            items = conn.execute("""SELECT * FROM telegram_outbox WHERE sent_at IS NULL AND attempts < 5
                                    ORDER BY id LIMIT 25 FOR UPDATE SKIP LOCKED""").fetchall()
            for item in items:
                try:
                    if item["kind"] == "change_request":
                        self._post_change(conn, item["chat_id"], item["change_id"])
                    elif item["kind"] == "refresh":
                        self._refresh(conn, item["change_id"])
                    else:
                        self.api.send_message(item["chat_id"], item["body"])
                    conn.execute("UPDATE telegram_outbox SET sent_at=now(), error=NULL WHERE id=%s", (item["id"],))
                    sent += 1
                except TelegramError as exc:
                    conn.execute("UPDATE telegram_outbox SET attempts=attempts+1, error=%s WHERE id=%s", (str(exc)[:300], item["id"]))
                    if exc.code == 403:  # user blocked the bot: stop at once
                        conn.execute("UPDATE telegram_outbox SET attempts=5 WHERE id=%s", (item["id"],))
                    if exc.retry_after:
                        conn.commit()
                        time.sleep(min(int(exc.retry_after), 30))
                conn.commit()
        return sent

    def _refresh(self, conn, change_id):
        ch = tg.load_change(conn, change_id)
        if not ch:
            return
        text, keyboard = tg.render_change(ch)
        for m in conn.execute("SELECT chat_id, message_id FROM telegram_change_messages WHERE change_id=%s", (change_id,)).fetchall():
            try:
                self.api.edit_message(m["chat_id"], m["message_id"], text, keyboard)
            except TelegramError as exc:
                if "not modified" not in str(exc) and "not found" not in str(exc):
                    raise

    # ------------------------------------------------------------ loop
    def run(self):
        me = self.api.get_me()
        self.api.delete_webhook()  # getUpdates and a webhook cannot both be active
        with db.connect() as conn:
            conn.execute("""INSERT INTO telegram_state(key,value) VALUES ('bot_username',%s)
                            ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value""", (me["username"],))
            row = conn.execute("SELECT value FROM telegram_state WHERE key='offset'").fetchone()
        offset = int(row["value"]) if row else None
        log.info("bot @%s running", me["username"])

        def outbox_loop():
            while True:
                try:
                    self.flush_outbox()
                except Exception:
                    log.exception("outbox failed")
                time.sleep(2)
        threading.Thread(target=outbox_loop, daemon=True).start()

        while True:
            try:
                updates = self.api.get_updates(offset)
            except TelegramError as exc:
                log.warning("getUpdates: %s", exc)
                time.sleep(5)
                continue
            for u in updates:
                offset = u["update_id"] + 1
                try:
                    self.handle(u)
                except Exception:
                    log.exception("update %s failed", u.get("update_id"))
            if updates:
                db.run("""INSERT INTO telegram_state(key,value) VALUES ('offset',%s)
                          ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value""", (str(offset),))


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # request URLs contain the bot token
    if not config.TELEGRAM_BOT_TOKEN:
        log.warning("TELEGRAM_BOT_TOKEN is empty; Telegram is off. Sleeping.")
        while True:
            time.sleep(3600)
    migrate()
    Bot(Telegram(config.TELEGRAM_BOT_TOKEN)).run()


if __name__ == "__main__":
    main()
