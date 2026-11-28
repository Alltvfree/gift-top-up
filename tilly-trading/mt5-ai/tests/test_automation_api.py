"""The n8n-facing API: auth, loopback, rate limits, and above all that it can never place or close an order."""
import json
import threading

import httpx
import pytest

from fake_mt5 import FakeMT5
from mt5_ai.automation_api import MAX_BODY, Api, make_server
from mt5_ai.broker import Mt5Broker
from mt5_ai.config import Settings
from mt5_ai.service import Mt5Service
from mt5_ai.telegram_bot import BotHandler, BotSettings, run

TOKEN = "t" * 32
ME = 111


@pytest.fixture
def env(tmp_path):
    mt5 = FakeMT5()
    svc = Mt5Service(Mt5Broker(mt5), Settings(state_dir=tmp_path, max_trades_per_day=50, max_open_positions=50))
    handler = BotHandler(svc, {ME}, symbol="XAUUSD")
    server = make_server(handler, TOKEN, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    yield mt5, svc, handler, base
    server.shutdown()
    server.server_close()


def call(base, method, path, token=TOKEN, **kw):
    headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
    return httpx.request(method, base + path, headers=headers, timeout=10, **kw)


def test_refuses_to_start_without_a_strong_token(env):
    _, _, handler, _ = env
    for bad in ("", "short", "x" * 19, None):
        with pytest.raises(ValueError):
            Api(handler, bad)


def test_binds_to_loopback_by_default(env):
    assert env[3].startswith("http://127.0.0.1:")


def test_health_is_open_and_everything_else_needs_the_exact_token(env):
    _, _, _, base = env
    assert call(base, "GET", "/health", token=None).json() == {"ok": True}
    for path in ("/status", "/positions", "/journal", "/quote"):
        assert call(base, "GET", path, token=None).status_code == 401
        assert call(base, "GET", path, token="wrong" * 8).status_code == 401
        assert call(base, "GET", path, token=TOKEN[:-1]).status_code == 401
    assert call(base, "POST", "/halt", token=None, json={}).status_code == 401
    assert call(base, "GET", "/status", token=TOKEN).status_code == 200


def test_read_endpoints_return_data(env):
    mt5, svc, _, base = env
    st = call(base, "GET", "/status").json()
    assert st["account"]["mode"] == "DEMO" and "loss_budget_left" in st["today"]
    assert call(base, "GET", "/positions").json()["positions"] == []
    assert call(base, "GET", "/journal").json()["placed"] == 0
    assert call(base, "GET", "/quote?symbol=XAUUSD").json()["bid"] == 5000.0
    ctx = call(base, "GET", "/context?symbol=XAUUSD&side=buy&sl=4995&tp=5010").json()
    assert "flags" in ctx and "h1_trend" in ctx
    b = call(base, "GET", "/bundle?symbol=XAUUSD&side=SELL&sl=5005&tp=4990").json()
    assert {"status", "today", "positions", "journal", "context", "quote"} <= set(b)


def test_prepare_makes_a_ticket_queues_it_for_telegram_and_places_nothing(env):
    mt5, svc, handler, base = env
    r = call(base, "POST", "/prepare", json={"symbol": "XAUUSD", "side": "buy", "sl": 4995, "tp": 5010, "hold": 90, "tags": "style:scalp"})
    body = r.json()
    assert r.status_code == 200 and body["verdict"] == "TICKET" and body["ticket_id"] and "Approve" in body["next"] + "Approve"
    assert mt5.sent == []
    text, ticket = handler.outbox.get_nowait()
    assert ticket == body["ticket_id"] and "TICKET" in text
    prepared = [json.loads(line) for line in svc._log_path.read_text().splitlines() if '"prepared"' in line][-1]
    assert "source:n8n" in prepared["tags"] and "style:scalp" in prepared["tags"]


def test_a_rule_breaking_plan_gets_no_ticket(env):
    mt5, _, handler, base = env
    r = call(base, "POST", "/prepare", json={"symbol": "XAUUSD", "side": "BUY", "sl": 5005, "tp": 5010}).json()
    assert r["verdict"] == "NOT_PREPARED" and r["ticket_id"] is None and mt5.sent == [] and handler.outbox.empty()


@pytest.mark.parametrize("payload", [
    {}, {"symbol": "X", "side": "BUY", "sl": 1, "tp": 2}, {"symbol": "XAUUSD", "side": "HOLD", "sl": 1, "tp": 2},
    {"symbol": "XAUUSD", "side": "BUY", "sl": "abc", "tp": 5010}, {"symbol": "XAUUSD", "side": "BUY", "sl": -1, "tp": 5010},
    {"symbol": "XAUUSD", "side": "BUY", "sl": 4995, "tp": 5010, "hold": 99999},
    {"symbol": "XAUUSD", "side": "BUY", "sl": 4995, "tp": 5010, "tags": "bad tag!"},
    {"symbol": "XAU/USD;DROP", "side": "BUY", "sl": 4995, "tp": 5010},
])
def test_bad_prepare_input_is_rejected_with_400_and_nothing_happens(env, payload):
    mt5, _, handler, base = env
    assert call(base, "POST", "/prepare", json=payload).status_code == 400
    assert mt5.sent == [] and handler.outbox.empty()


@pytest.mark.parametrize("method,path", [("POST", "/place"), ("POST", "/yes"), ("POST", "/close"), ("POST", "/order"), ("POST", "/approve"),
                                         ("POST", "/move_stop"), ("GET", "/place"), ("POST", "/positions/1/close"), ("DELETE", "/positions")])
def test_there_is_no_endpoint_that_places_closes_or_modifies_orders(env, method, path):
    mt5, svc, _, base = env
    ticket = svc.prepare_trade("XAUUSD", "BUY", 4995.0, 5010.0)["ticket_id"]
    pos = mt5.add_position()
    r = call(base, method, path, json={"ticket_id": ticket, "position": pos.ticket}) if method != "GET" else call(base, method, path)
    assert r.status_code in (404, 501) and mt5.sent == [] and any(p.ticket == pos.ticket for p in mt5.positions)
    assert svc.tickets.is_open(ticket)                                   # the ticket was never consumed


def test_notify_halt_and_the_kill_switch(env):
    _, svc, handler, base = env
    assert call(base, "POST", "/notify", json={"text": "daily report"}).json() == {"queued": True}
    assert handler.outbox.get_nowait() == ("daily report", None)
    assert call(base, "POST", "/notify", json={"text": "  "}).status_code == 400
    assert call(base, "POST", "/halt", json={"reason": "test"}).json()["halted"] is True and svc.halted()
    assert "HALTED" in handler.outbox.get_nowait()[0]
    assert "BLOCKED" in handler.handle(ME, "/plan buy XAUUSD sl 4995 tp 5010")


def test_rate_limits(env):
    _, _, _, base = env
    codes = [call(base, "POST", "/prepare", json={"symbol": "XAUUSD", "side": "BUY", "sl": 4995, "tp": 5010}).status_code for _ in range(8)]
    assert codes[:6] == [200] * 6 and codes[6:] == [429, 429]


def test_oversized_and_malformed_bodies(env):
    _, _, _, base = env
    assert call(base, "POST", "/notify", content=b"x" * (MAX_BODY + 10)).status_code == 413
    assert call(base, "POST", "/notify", content=b"not json").status_code == 400
    assert call(base, "POST", "/notify", content=b"[1,2]").status_code == 400


def test_errors_never_leak_internals(env, monkeypatch):
    _, svc, _, base = env
    monkeypatch.setattr(svc, "position_cards", lambda: (_ for _ in ()).throw(RuntimeError("SECRET-PATH C:/x/y")))
    r = call(base, "GET", "/positions")
    assert r.status_code == 500 and "SECRET" not in r.text and r.json() == {"error": "RuntimeError"}


def test_the_bot_loop_delivers_queued_messages_and_tickets_to_allowed_users_only(env):
    mt5, _, handler, _ = env
    handler.push("daily report")
    r = Api(handler, TOKEN).route("POST", "/prepare", {}, {"symbol": "XAUUSD", "side": "BUY", "sl": 4995, "tp": 5010})
    assert r[0] == 200
    sent, state = [], {"n": 0}

    def route(request):
        if request.url.path.endswith("/getUpdates"):
            state["n"] += 1
            return httpx.Response(200, json={"result": []})
        sent.append(json.loads(request.read()))
        return httpx.Response(200, json={"ok": True})

    client = httpx.Client(transport=httpx.MockTransport(route))
    run(BotSettings(token="TOKEN123", allowed_ids=frozenset({ME})), handler, client=client, stop=lambda: state["n"] >= 2)
    assert [m["chat_id"] for m in sent] == [ME, ME] and sent[0]["text"] == "daily report"
    assert "TICKET" in sent[1]["text"] and sent[1]["reply_markup"]["inline_keyboard"][0][0]["callback_data"].startswith("ok:") and mt5.sent == []


# --- the n8n workflows shipped with the repo ------------------------------------------------------------------
def test_shipped_workflows_only_call_endpoints_this_api_really_offers_and_never_an_order_endpoint():
    import re
    from pathlib import Path

    files = sorted((Path(__file__).resolve().parent.parent / "n8n" / "workflows").glob("*.json"))
    assert len(files) >= 3
    allowed = {"/status", "/positions", "/journal", "/bundle", "/notify", "/quote", "/context"}
    for f in files:
        wf = json.loads(f.read_text())
        names = {n["name"] for n in wf["nodes"]}
        assert len(names) == len(wf["nodes"])
        for src, v in wf["connections"].items():
            assert src in names and all(t["node"] in names for out in v["main"] for t in out)
        for n in wf["nodes"]:
            url = n["parameters"].get("url", "")
            if url.startswith("http://host.docker.internal"):
                assert re.sub(r"^http://host\.docker\.internal:8765", "", url) in allowed, (f.name, url)
            else:
                assert not url or url.startswith("https://api.anthropic.com/"), (f.name, url)
        blob = json.dumps(wf)
        assert not any(bad in blob for bad in ("/place", "/yes", "/close", "/order", "/approve", "/halt", "/prepare")), f.name
