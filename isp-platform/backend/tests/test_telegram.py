import pytest

from app import config, telegram_bot
from app.adapters.telegram import TelegramError
from app.telegram_bot import Bot

from .conftest import current_code

ALICE, BOB, NINA, STRANGER = 1001, 1002, 1003, 9999


class FakeTelegram:
    def __init__(self):
        self.sent, self.edits, self.answers, self.deleted = [], [], [], []
        self.next_id = 500

    def send_message(self, chat_id, text, keyboard=None, force_reply=False):
        self.next_id += 1
        self.sent.append({"chat": chat_id, "text": text, "keyboard": keyboard, "id": self.next_id})
        return {"message_id": self.next_id}

    def edit_message(self, chat_id, message_id, text, keyboard=None):
        self.edits.append({"chat": chat_id, "id": message_id, "text": text, "keyboard": keyboard})
        return {}

    def answer_callback(self, callback_id, text=""):
        self.answers.append(text)

    def delete_message(self, chat_id, message_id):
        self.deleted.append(message_id)

    def to(self, chat):
        return [m for m in self.sent if m["chat"] == chat]


def msg(chat, text, mid=1):
    return {"update_id": 1, "message": {"message_id": mid, "chat": {"id": chat, "type": "private"},
                                        "from": {"id": chat, "first_name": "T"}, "text": text}}


def press(chat, data):
    return {"update_id": 2, "callback_query": {"id": "cb", "from": {"id": chat}, "data": data,
                                               "message": {"message_id": 7, "chat": {"id": chat, "type": "private"}}}}


@pytest.fixture
def tg(monkeypatch, sql):
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "test-token")
    sql("UPDATE users SET telegram_chat_id=NULL, telegram_alerts=true, totp_last_step=0; DELETE FROM telegram_outbox; "
        "DELETE FROM telegram_pending; DELETE FROM telegram_change_messages")
    return Bot(FakeTelegram(), background=False)


def link(client, bot, chat):
    code = client.post("/api/auth/telegram/link").json()["code"]
    bot.handle(msg(chat, f"/start {code}"))
    return code


def new_change(admin):
    dev = admin.post("/api/devices", json={"name": f"TG-MT-{id(admin)}", "vendor": "mikrotik", "role": "island_router",
                                           "management_ip": "10.9.9.1"}).json()["id"]
    return admin.post("/api/changes", json={"device_id": dev, "title": "Test rule", "kind": "mikrotik_script",
                                            "plan": "/ip firewall filter print <b>"}).json()["id"]


def test_link_and_unlink(admin, tg, sql):
    status = admin.get("/api/auth/telegram").json()
    assert status["enabled"] and not status["linked"]
    code = link(admin, tg, ALICE)
    assert "Linked to SatLink user <b>alice</b>" in tg.api.to(ALICE)[-1]["text"]
    assert admin.get("/api/auth/telegram").json()["linked"]
    tg.handle(msg(STRANGER, f"/start {code}"))  # one-time code
    assert "expired" in tg.api.to(STRANGER)[-1]["text"]
    tg.handle(msg(STRANGER, "/pending"))
    assert "not linked" in tg.api.to(STRANGER)[-1]["text"]
    assert sql("SELECT count(*) FROM telegram_link_codes WHERE expires_at > now()")[0][0] == 0
    tg.handle(msg(ALICE, "/unlink"))
    assert not admin.get("/api/auth/telegram").json()["linked"]


def test_change_goes_to_other_admins_and_needs_2fa(admin, admin2, tg, sql, monkeypatch):
    link(admin, tg, ALICE)
    link(admin2, tg, BOB)
    cid = new_change(admin)
    tg.flush_outbox()
    posted = [m for m in tg.api.to(BOB) if f"Change #{cid}" in m["text"]]
    assert len(posted) == 1 and posted[0]["keyboard"]
    assert "&lt;b&gt;" in posted[0]["text"]  # plan is escaped
    assert not [m for m in tg.api.to(ALICE) if f"Change #{cid}" in m["text"]]  # requester is skipped

    # requester cannot approve own change from Telegram either (FOUR_EYES=true)
    tg.handle(press(ALICE, f"a:{cid}"))
    assert "Four-eyes" in tg.api.answers[-1]

    tg.handle(press(BOB, f"a:{cid}"))
    assert "6-digit" in tg.api.to(BOB)[-1]["text"]
    tg.handle(msg(BOB, "000000", mid=77))
    assert "Wrong code" in tg.api.to(BOB)[-1]["text"] and 77 in tg.api.deleted
    assert admin.get(f"/api/changes/{cid}").json()["status"] == "pending"
    tg.handle(msg(BOB, current_code(), mid=78))
    assert "approved" in tg.api.to(BOB)[-1]["text"] and 78 in tg.api.deleted
    ch = admin.get(f"/api/changes/{cid}").json()
    assert ch["status"] == "approved" and ch["approved_by"] == "bob"
    assert sql("SELECT detail->>'via' FROM audit_events WHERE action='change.approve' AND target_id=%s", (str(cid),))[0][0] == "telegram"

    tg.flush_outbox()  # buttons replaced; requester told
    assert any(e["keyboard"] and e["keyboard"][0][0]["callback_data"] == f"x:{cid}" for e in tg.api.edits)
    assert any("approved by bob" in m["text"] for m in tg.api.to(ALICE))

    # apply from Telegram (needs a fresh code)
    applied = []
    monkeypatch.setattr(telegram_bot.changes, "apply",
                        lambda change_id, actor: applied.append((change_id, actor)) or {"ok": True, "status": "applied", "result": "done"})
    tg.handle(press(BOB, f"x:{cid}"))
    sql("UPDATE users SET totp_last_step=0 WHERE username='bob'")
    tg.handle(msg(BOB, current_code()))
    assert applied == [(cid, "bob")]
    assert "applied" in tg.api.to(BOB)[-1]["text"]


def test_code_replay_and_lockout(admin, admin2, tg, sql):
    link(admin2, tg, BOB)
    cid = new_change(admin)
    code = current_code()
    tg.handle(press(BOB, f"a:{cid}"))
    tg.handle(msg(BOB, code))
    assert admin.get(f"/api/changes/{cid}").json()["status"] == "approved"
    cid2 = new_change(admin)
    tg.handle(press(BOB, f"a:{cid2}"))
    tg.handle(msg(BOB, code))  # same code again: replay
    assert "Wrong code" in tg.api.to(BOB)[-1]["text"]
    tg.handle(msg(BOB, "111111"))
    tg.handle(msg(BOB, "222222"))
    assert "Cancelled" in tg.api.to(BOB)[-1]["text"]
    assert sql("SELECT count(*) FROM telegram_pending")[0][0] == 0
    assert admin.get(f"/api/changes/{cid2}").json()["status"] == "pending"


def test_reject_and_roles(admin, admin2, tg, sql):
    from .conftest import login
    nina = login("nina")
    link(admin2, tg, BOB)
    link(nina, tg, NINA)
    cid = new_change(admin)
    tg.flush_outbox()
    assert not [m for m in tg.api.to(NINA) if "Change #" in m["text"]]  # noc cannot approve: not sent
    tg.handle(press(NINA, f"a:{cid}"))
    assert "may not" in tg.api.answers[-1]
    tg.handle(press(BOB, f"r:{cid}"))  # reject needs no code
    assert admin.get(f"/api/changes/{cid}").json()["status"] == "rejected"
    # groups are ignored entirely
    before = len(tg.api.sent)
    tg.handle({"update_id": 3, "message": {"message_id": 1, "chat": {"id": -5, "type": "group"}, "from": {"id": BOB}, "text": "/pending"}})
    assert len(tg.api.sent) == before


def test_self_approve_mode(admin, tg, monkeypatch):
    monkeypatch.setattr(config, "SELF_APPROVE_VIA_TELEGRAM", True)
    link(admin, tg, ALICE)
    cid = new_change(admin)
    r = admin.post(f"/api/changes/{cid}/approve")
    assert r.status_code == 403 and "Telegram" in r.json()["detail"]  # web still refuses
    tg.flush_outbox()
    assert [m for m in tg.api.to(ALICE) if f"Change #{cid}" in m["text"]]  # requester gets the buttons
    tg.handle(press(ALICE, f"a:{cid}"))
    tg.handle(msg(ALICE, current_code()))
    assert admin.get(f"/api/changes/{cid}").json()["status"] == "approved"


def test_alerts_and_blocked_bot(admin, tg, sql):
    from app import db
    from app.services import telegram
    link(admin, tg, ALICE)
    admin.put("/api/auth/telegram/alerts", json={"enabled": False})
    with db.connect() as conn:
        telegram.alert(conn, "[CRITICAL] x down")
    assert sql("SELECT count(*) FROM telegram_outbox WHERE kind='text'")[0][0] == 0
    admin.put("/api/auth/telegram/alerts", json={"enabled": True})
    with db.connect() as conn:
        telegram.alert(conn, "[CRITICAL] <x> down")
    tg.flush_outbox()
    assert tg.api.to(ALICE)[-1]["text"] == "[CRITICAL] &lt;x&gt; down"

    def blocked(*a, **k):
        raise TelegramError("Forbidden: bot was blocked by the user", 403)
    tg.api.send_message = blocked
    with db.connect() as conn:
        telegram.alert(conn, "again")
    tg.flush_outbox()
    assert sql("SELECT attempts FROM telegram_outbox WHERE body='again'")[0][0] == 5  # not retried


def test_link_needs_token(admin, monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "")
    assert admin.post("/api/auth/telegram/link").status_code == 409


def test_client_hides_token():
    import httpx
    from app.adapters.telegram import Telegram

    def handler(request):
        if request.url.path.endswith("/getMe"):
            return httpx.Response(200, json={"ok": True, "result": {"username": "satlink_bot"}})
        if request.url.path.endswith("/sendMessage"):
            return httpx.Response(429, json={"ok": False, "error_code": 429, "description": "Too Many Requests",
                                             "parameters": {"retry_after": 7}})
        raise httpx.ConnectError(f"cannot reach {request.url}")
    api = Telegram("123:SECRET", transport=httpx.MockTransport(handler))
    assert api.get_me()["username"] == "satlink_bot"
    with pytest.raises(TelegramError) as e:
        api.send_message(1, "hi", keyboard=[[{"text": "x", "callback_data": "a:1"}]])
    assert e.value.retry_after == 7
    with pytest.raises(TelegramError) as e:
        api.get_updates(None)
    assert "SECRET" not in str(e.value)
