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
