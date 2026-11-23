"""Telegram bot: allow-list, command flow against a fake terminal, the ticket-then-yes rule, AI chat limits."""
import httpx
import pytest

from fake_mt5 import FakeMT5
from mt5_ai.broker import Mt5Broker
from mt5_ai.config import Settings
from mt5_ai.llm import LLMError, complete
from mt5_ai.service import Mt5Service
from mt5_ai.telegram_bot import BotHandler, BotSettings, parse_plan, run

ME, STRANGER = 111, 999


@pytest.fixture
def env(tmp_path):
    mt5 = FakeMT5()
    svc = Mt5Service(Mt5Broker(mt5), Settings(state_dir=tmp_path, max_trades_per_day=50, max_open_positions=50))
    return mt5, svc


def bot(svc, llm=None, clock=lambda: 1000.0):
    return BotHandler(svc, {ME}, symbol="XAUUSD", llm=llm, clock=clock)


def test_strangers_and_empty_messages_are_ignored_silently(env):
    _, svc = env
    b = bot(svc)
    assert b.handle(STRANGER, "/status") is None and b.handle(STRANGER, "/yes abc") is None
    assert b.handle(ME, "   ") is None


def test_basic_commands(env):
    mt5, svc = env
    mt5.add_position(side="BUY")
    b = bot(svc)
    assert "DEMO" in b.handle(ME, "/status")
    assert "bid: 5000.0" in b.handle(ME, "/quote")
    assert "#" in b.handle(ME, "/positions") and "/plan" in b.handle(ME, "/help")
    assert "Unknown command" in b.handle(ME, "/nonsense")
    assert "not configured" in b.handle(ME, "/ask hello")


def test_plan_sends_nothing_and_yes_places_exactly_that_ticket(env):
    mt5, svc = env
    b = bot(svc)
    reply = b.handle(ME, "/plan buy XAUUSD sl 4995 tp 5010 hold 90 tags style:scalp")
    assert "TICKET" in reply and "/yes " in reply and mt5.sent == [], "a plan must not send an order"
    ticket = reply.split("/yes ")[1].split()[0]
    placed = b.handle(ME, f"/yes {ticket}")
    assert placed.startswith("PLACED") and len(mt5.sent) == 1 and "timer" in placed.lower()
    assert "NOT placed" in b.handle(ME, f"/yes {ticket}")        # single use
    assert len(mt5.sent) == 1


def test_yes_with_a_wrong_or_missing_ticket_places_nothing(env):
    mt5, svc = env
    b = bot(svc)
    assert "NOT placed" in b.handle(ME, "/yes nosuchticket") and "Usage" in b.handle(ME, "/yes")
    assert mt5.sent == []


def test_blocked_plan_gives_the_reasons_and_no_ticket(env):
    mt5, svc = env
    out = bot(svc).handle(ME, "/plan buy XAUUSD sl 5005 tp 5010")     # stop on the wrong side
    assert out.startswith("BLOCKED") and "/yes" not in out and mt5.sent == []


@pytest.mark.parametrize("text", ["/plan", "/plan hold buy", "/plan buy XAUUSD sl abc tp 1", "/plan buy XAUUSD sl 4995"])
def test_bad_plan_syntax_is_explained_not_executed(env, text):
    mt5, svc = env
    assert "Usage" in bot(svc).handle(ME, text) and mt5.sent == []


def test_parse_plan_defaults_symbol_and_reads_options():
    p = parse_plan(["sell", "sl", "5010", "tp", "4990", "risk", "0.5", "note", "fade", "the", "high"], "XAUUSDm")
    assert p["symbol"] == "XAUUSDm" and p["side"] == "SELL" and p["risk_pct"] == 0.5 and p["note"] == "fade the high"


def test_halt_blocks_new_plans(env):
    mt5, svc = env
    b = bot(svc)
    assert "HALTED" in b.handle(ME, "/halt")
    assert "BLOCKED" in b.handle(ME, "/plan buy XAUUSD sl 4995 tp 5010")


def test_close_only_touches_positions_this_server_opened(env):
    mt5, svc = env
    foreign = mt5.add_position(magic=999)
    out = bot(svc).handle(ME, f"/close {foreign.ticket}")
    assert "Error" in out and mt5.sent == []


# --- AI chat -----------------------------------------------------------------------------------
def test_ai_answer_without_a_plan_places_and_prepares_nothing(env):
    mt5, svc = env
    seen = {}
    def llm(system, user):
        seen["user"] = user
        return "Gold is range-bound; no edge shown."
    out = bot(svc, llm).handle(ME, "what do you think?")
    assert "range-bound" in out and "SNAPSHOT" in seen["user"] and mt5.sent == [] and not svc._log_path.exists()


def test_ai_proposed_trade_becomes_a_ticket_but_is_never_placed(env):
    mt5, svc = env
    llm = lambda s, u: "Buy the dip.\nPLAN BUY XAUUSD SL 4995 TP 5010 HOLD 60 TAGS style:scalp"  # noqa: E731
    out = bot(svc, llm).handle(ME, "/ask give me a trade")
    assert "TICKET" in out and "/yes " in out and "PLAN BUY" not in out and mt5.sent == []


def test_ai_proposal_that_breaks_the_rules_is_blocked(env):
    mt5, svc = env
    llm = lambda s, u: "PLAN BUY XAUUSD SL 5100 TP 5200"  # noqa: E731
    out = bot(svc, llm).handle(ME, "/ask trade")
    assert "BLOCKED" in out and mt5.sent == []


def test_ai_errors_are_reported_not_raised_and_questions_are_rate_limited(env):
    _, svc = env
    def llm(s, u):
        raise LLMError("no key")
    t = {"now": 1000.0}
    b = bot(svc, llm, clock=lambda: t["now"])
    assert "AI unavailable: no key" in b.handle(ME, "hi")
    assert "wait" in b.handle(ME, "hi again")
    t["now"] += 10
    assert "AI unavailable" in b.handle(ME, "hi again")


# --- settings -----------------------------------------------------------------------------------
def test_bot_refuses_to_start_without_an_allow_list_or_token():
    with pytest.raises(SystemExit):
        BotSettings.from_env({"MT5_AI_TELEGRAM_TOKEN": "t"})
    with pytest.raises(SystemExit):
        BotSettings.from_env({"MT5_AI_TELEGRAM_ALLOWED_IDS": "1"})
    s = BotSettings.from_env({"MT5_AI_TELEGRAM_TOKEN": "t", "MT5_AI_TELEGRAM_ALLOWED_IDS": "1, 2"})
    assert s.allowed_ids == {1, 2} and s.provider is None


def test_ai_settings_pick_up_the_right_key_and_never_print_it():
    s = BotSettings.from_env({"MT5_AI_TELEGRAM_TOKEN": "t", "MT5_AI_TELEGRAM_ALLOWED_IDS": "1", "MT5_AI_LLM_PROVIDER": "google",
                              "MT5_AI_LLM_MODEL": "m", "GOOGLE_API_KEY": "SECRETKEY", "OPENAI_API_KEY": "other"})
    assert s.llm_key == "SECRETKEY" and "SECRETKEY" not in repr(s)
    with pytest.raises(SystemExit):
        BotSettings.from_env({"MT5_AI_TELEGRAM_TOKEN": "t", "MT5_AI_TELEGRAM_ALLOWED_IDS": "1", "MT5_AI_LLM_PROVIDER": "nope"})


# --- transport ----------------------------------------------------------------------------------
def test_polling_serves_only_allowed_private_chats_and_replies(env, capsys):
    mt5, svc = env
    sent, calls = [], {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/getUpdates"):
            calls["n"] += 1
            if calls["n"] > 1:
                return httpx.Response(200, json={"result": []})
            msg = lambda uid, text, kind="private": {"update_id": uid, "message": {"chat": {"id": uid, "type": kind}, "from": {"id": uid}, "text": text}}  # noqa: E731
            return httpx.Response(200, json={"result": [msg(ME, "/help"), msg(STRANGER, "/status"), msg(ME, "/help", "group")]})
        sent.append(request.read().decode())
        return httpx.Response(200, json={"ok": True})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    s = BotSettings(token="TOKEN123", allowed_ids=frozenset({ME}))
    run(s, bot(svc), client=client, stop=lambda: calls["n"] >= 2)
    out = capsys.readouterr().out
    assert len(sent) == 1 and "/plan" in sent[0]
    assert "TOKEN123" not in out and "not allowed" in out


def test_connection_errors_never_print_the_token(env, capsys, monkeypatch):
    _, svc = env
    monkeypatch.setattr("time.sleep", lambda s: None)
    n = {"i": 0}
    def handler(request):
        n["i"] += 1
        raise httpx.ConnectError("boom " + str(request.url))
    client = httpx.Client(transport=httpx.MockTransport(handler))
    run(BotSettings(token="TOKEN123", allowed_ids=frozenset({ME})), bot(svc), client=client, stop=lambda: n["i"] >= 2)
    out = capsys.readouterr().out
    assert "ConnectError" in out and "TOKEN123" not in out


# --- LLM providers ------------------------------------------------------------------------------
@pytest.mark.parametrize("provider,reply,expect_url,header", [
    ("anthropic", {"content": [{"type": "text", "text": "hi"}]}, "api.anthropic.com", "x-api-key"),
    ("openai", {"choices": [{"message": {"content": "hi"}}]}, "api.openai.com", "authorization"),
    ("google", {"candidates": [{"content": {"parts": [{"text": "hi"}]}}]}, "generativelanguage.googleapis.com", "x-goog-api-key"),
])
def test_each_provider_is_called_with_its_own_format_and_key_stays_in_a_header(provider, reply, expect_url, header):
    seen = {}
    def handler(request):
        seen["url"], seen["headers"], seen["body"] = str(request.url), request.headers, request.read().decode()
        return httpx.Response(200, json=reply)
    out = complete(provider, "some-model", "SYS", "USER", api_key="KEY123", client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert out == "hi" and expect_url in seen["url"] and "KEY123" in seen["headers"][header]
    assert "KEY123" not in seen["url"] and "KEY123" not in seen["body"] and "USER" in seen["body"]


def test_llm_errors_are_clear_and_do_not_leak_the_key():
    bad = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(401, json={"error": "nope"})))
    with pytest.raises(LLMError) as e:
        complete("openai", "m", "s", "u", api_key="KEY123", client=bad)
    assert "401" in str(e.value) and "KEY123" not in str(e.value)
    with pytest.raises(LLMError):
        complete("anthropic", "m", "s", "u", api_key="")
    with pytest.raises(LLMError):
        complete("openai", "", "s", "u", api_key="k")
    with pytest.raises(LLMError):
        complete("mystery", "m", "s", "u", api_key="k")


# --- Approve / Reject buttons ---------------------------------------------------------------------
import json as _json


def _run_updates(svc, updates, handler=None):
    """Feeds one batch of Telegram updates through run(); returns the API calls the bot made, in order."""
    calls, state = [], {"polled": 0}

    def route(request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", 1)[-1]
        body = _json.loads(request.read().decode() or "{}")
        if method == "getUpdates":
            state["polled"] += 1
            return httpx.Response(200, json={"result": updates if state["polled"] == 1 else []})
        calls.append((method, body))
        return httpx.Response(200, json={"ok": True})

    client = httpx.Client(transport=httpx.MockTransport(route))
    run(BotSettings(token="TOKEN123", allowed_ids=frozenset({ME})), handler or bot(svc), client=client, stop=lambda: state["polled"] >= 2)
    return calls


def _msg(uid, text, update_id=1):
    return {"update_id": update_id, "message": {"message_id": 10, "chat": {"id": uid, "type": "private"}, "from": {"id": uid}, "text": text}}


def _press(uid, data, update_id=2):
    return {"update_id": update_id, "callback_query": {"id": "cb1", "from": {"id": uid}, "data": data,
            "message": {"message_id": 11, "chat": {"id": uid, "type": "private"}}}}


def test_a_fresh_ticket_comes_with_approve_and_reject_buttons_but_a_block_does_not(env):
    mt5, svc = env
    ok = _run_updates(svc, [_msg(ME, "/plan buy XAUUSD sl 4995 tp 5010")])
    sent = [b for m, b in ok if m == "sendMessage"][0]
    buttons = sent["reply_markup"]["inline_keyboard"][0]
    assert [b["text"] for b in buttons] == ["✅ Approve", "❌ Reject"] and buttons[0]["callback_data"].startswith("ok:")
    assert mt5.sent == []
    blocked = _run_updates(svc, [_msg(ME, "/plan buy XAUUSD sl 5005 tp 5010")])
    assert "reply_markup" not in [b for m, b in blocked if m == "sendMessage"][0]


def test_approve_button_places_exactly_that_ticket_once_and_removes_the_buttons(env):
    mt5, svc = env
    b = bot(svc)
    ticket = b.handle_reply(ME, "/plan buy XAUUSD sl 4995 tp 5010").ticket_id
    calls = _run_updates(svc, [_press(ME, f"ok:{ticket}"), _press(ME, f"ok:{ticket}", 3)], handler=b)
    assert len(mt5.sent) == 1                                          # second tap placed nothing
    texts = [body["text"] for m, body in calls if m == "sendMessage"]
    assert texts[0].startswith("PLACED") and texts[1].startswith("NOT placed")
    assert any(m == "editMessageReplyMarkup" and body["reply_markup"] == {"inline_keyboard": []} for m, body in calls)


def test_reject_button_burns_the_ticket_so_a_later_yes_cannot_place_it(env):
    mt5, svc = env
    b = bot(svc)
    ticket = b.handle_reply(ME, "/plan buy XAUUSD sl 4995 tp 5010").ticket_id
    calls = _run_updates(svc, [_press(ME, f"no:{ticket}")], handler=b)
    assert any("rejected" in body.get("text", "") for m, body in calls)
    assert "NOT placed" in b.handle(ME, f"/yes {ticket}") and mt5.sent == []


def test_a_strangers_button_press_does_nothing(env, capsys):
    mt5, svc = env
    b = bot(svc)
    ticket = b.handle_reply(ME, "/plan buy XAUUSD sl 4995 tp 5010").ticket_id
    calls = _run_updates(svc, [_press(STRANGER, f"ok:{ticket}")], handler=b)
    assert mt5.sent == [] and [m for m, _ in calls] == ["answerCallbackQuery"]
    assert "not allowed" in capsys.readouterr().out
    assert b.handle(ME, f"/yes {ticket}").startswith("PLACED")        # the ticket was untouched


@pytest.mark.parametrize("data", ["", "ok:", "ok", "zz:abc", "ok:nosuchticket"])
def test_malformed_or_unknown_button_data_places_nothing(env, data):
    mt5, svc = env
    _run_updates(svc, [_press(ME, data)])
    assert mt5.sent == []


# --- one-tap BUY / SELL ---------------------------------------------------------------------------
from mt5_ai.telegram_bot import BTN_BUY, BTN_SELL, MENU_KEYBOARD


def test_buy_button_builds_a_ticket_from_the_live_price_and_places_nothing(env):
    mt5, svc = env                                     # fake: bid 5000.00, ask 5000.25, M5 ranges 4.0
    r = bot(svc).handle_reply(ME, BTN_BUY)
    assert r.ticket_id and "TICKET" in r.text and mt5.sent == []
    assert "stop 4.00 away" in r.text and "exit timer 90s" in r.text
    assert "stop-loss 4996.25" in r.text and "take-profit 5008.25" in r.text      # ask -4, +2x4 on the other side


def test_sell_button_mirrors_it(env):
    mt5, svc = env
    r = bot(svc).handle_reply(ME, BTN_SELL)
    assert "SELL" in r.text and "stop-loss 5004.00" in r.text and "take-profit 4992.00" in r.text and mt5.sent == []


def test_overrides_for_stop_rr_and_hold_work_and_are_validated(env):
    _, svc = env
    r = bot(svc).handle_reply(ME, "/buy XAUUSD stop 3 rr 3 hold 45")
    assert "stop-loss 4997.25" in r.text and "take-profit 5009.25" in r.text and "exit timer 45s" in r.text
    assert "Usage" in bot(svc).handle(ME, "/buy stop") and "Usage" in bot(svc).handle(ME, "/sell stop x")


def test_a_stop_that_is_too_tight_for_the_spread_is_blocked_not_forced(env):
    mt5, svc = env
    out = bot(svc).handle(ME, "/buy stop 0.5")
    assert "BLOCKED" in out and "/yes" not in out and mt5.sent == []


def test_configured_defaults_are_used(env):
    _, svc = env
    b = BotHandler(svc, {ME}, symbol="XAUUSD", quick_hold=30, quick_rr=3.0, quick_stop=5.0)
    out = b.handle(ME, "/buy")
    assert "stop 5.00 away" in out and "exit timer 30s" in out and "take-profit 5015.25" in out


def test_buttons_from_strangers_do_nothing(env):
    mt5, svc = env
    assert bot(svc).handle(STRANGER, BTN_BUY) is None and mt5.sent == []


def test_start_shows_the_menu_keyboard_and_the_other_buttons_map_to_commands(env):
    _, svc = env
    b = bot(svc)
    assert b.handle_reply(ME, "/start").menu and b.handle_reply(ME, "/menu").menu and not b.handle_reply(ME, "/status").menu
    assert "DEMO" in b.handle(ME, "\U0001F4CA Status") and "bid" in b.handle(ME, "\U0001F4C8 Quote")


def test_transport_sends_the_menu_keyboard_with_start_and_approve_buttons_with_a_quick_ticket(env):
    mt5, svc = env
    calls = _run_updates(svc, [_msg(ME, "/start", 1), _msg(ME, BTN_BUY, 2)])
    sent = [b for m, b in calls if m == "sendMessage"]
    assert sent[0]["reply_markup"] == MENU_KEYBOARD
    assert sent[1]["reply_markup"]["inline_keyboard"][0][0]["callback_data"].startswith("ok:") and mt5.sent == []


def test_quick_settings_come_from_the_environment():
    s = BotSettings.from_env({"MT5_AI_TELEGRAM_TOKEN": "t", "MT5_AI_TELEGRAM_ALLOWED_IDS": "1", "MT5_AI_QUICK_HOLD": "60",
                              "MT5_AI_QUICK_RR": "2.5", "MT5_AI_QUICK_STOP": "1.8"})
    assert (s.quick_hold, s.quick_rr, s.quick_stop) == (60, 2.5, 1.8)
    d = BotSettings.from_env({"MT5_AI_TELEGRAM_TOKEN": "t", "MT5_AI_TELEGRAM_ALLOWED_IDS": "1"})
    assert (d.quick_hold, d.quick_rr, d.quick_stop) == (90, 2.0, None)
