"""Your own Telegram bot for the MT5 account: plain commands, optional AI chat.

    python -m mt5_ai.telegram_bot

Runs on the machine that has MT5 (the VPS), next to the same service the Claude Desktop (MCP)
connection uses, so every limit applies identically: demo-only, mandatory stop and target,
risk sized from the stop, the daily loss budget, the kill switch.

Safety design
- ONLY the Telegram user ids in MT5_AI_TELEGRAM_ALLOWED_IDS are served. Everyone else is ignored
  silently. The bot refuses to start with an empty list.
- Only private chats. Group messages are ignored.
- Placing an order takes TWO messages from you: `/plan ...` creates a ticket (sends nothing), and
  `/yes <ticket id>` places exactly that ticket. Tickets expire in minutes and work once.
- The AI chat can never place anything. It can at most propose a trade line, which becomes an
  unconfirmed ticket; you still have to send `/yes <id>` yourself.
- The bot token and API keys come from environment variables on the VPS. They are never logged;
  network errors are reported by type only (the Telegram URL contains the token).

Placing: every fresh ticket arrives with Approve / Reject buttons (or send /yes ID).
Commands: /help /status /quote [SYMBOL] /positions /today /plan ... /yes ID /close POSITION /halt /journal /ask TEXT
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from typing import Callable

import httpx

from .llm import DEFAULT_MODELS, KEY_ENV, PROVIDERS, LLMError, complete

MAX_MESSAGE = 3800
PLAN_USAGE = ("Usage: /plan buy|sell [SYMBOL] sl PRICE tp PRICE [risk PCT] [hold SECONDS] [tags a,b] [note TEXT...]\n"
              "Example: /plan buy XAUUSDm sl 3880 tp 3890 hold 90 tags style:scalp")
HELP = ("Commands:\n"
        "/status  account, mode, limits\n"
        "/quote [SYMBOL]  live price\n"
        "/positions  open positions\n"
        "/today  today's result and loss budget left\n"
        "/plan ...  prepare a ticket (sends NO order)\n"
        "/yes ID  place that exact ticket\n"
        "/close POSITION  close one position this server opened\n"
        "/halt  stop all new trades (you resume by deleting the HALT file)\n"
        "/journal  results of trades placed through this server\n"
        "/ask TEXT  ask the AI (if configured); it can propose a ticket, never place one\n\n" + PLAN_USAGE)

SYSTEM_PROMPT = (
    "You are a cautious assistant for a person trading a DEMO MetaTrader 5 account through a risk-checked bot. "
    "You are given a snapshot of account state, a quote and recent closed candles. Answer briefly and concretely. "
    "Do not invent data that is not in the snapshot. No strategy tested on this person's data has shown a proven edge; "
    "say so when asked whether a trade is likely to win, and never promise outcomes. "
    "If, and only if, the person asks for a trade idea, you may propose ONE trade by ending your reply with exactly one line:\n"
    "PLAN BUY|SELL <symbol> SL <price> TP <price> [HOLD <seconds>] [TAGS <comma,separated>]\n"
    "The stop must be on the losing side and the target at least 1.5 times the stop distance. "
    "You cannot place orders; the person must confirm separately. Never ask for passwords or keys.")

_PLAN_LINE = re.compile(r"^\s*PLAN\s+(BUY|SELL)\s+(\S+)\s+SL\s+([0-9.]+)\s+TP\s+([0-9.]+)(?:\s+HOLD\s+(\d+))?(?:\s+TAGS\s+(\S+))?\s*$",
                        re.IGNORECASE | re.MULTILINE)


@dataclass
class BotSettings:
    token: str
    allowed_ids: frozenset[int]
    symbol: str = "XAUUSDm"
    provider: str | None = None
    model: str | None = None
    llm_key: str | None = field(default=None, repr=False)

    @classmethod
    def from_env(cls, env: dict | None = None) -> "BotSettings":
        e = os.environ if env is None else env
        token = (e.get("MT5_AI_TELEGRAM_TOKEN") or "").strip()
        if not token:
            raise SystemExit("Set MT5_AI_TELEGRAM_TOKEN (from @BotFather) on this machine.")
        ids = frozenset(int(x) for x in re.split(r"[,\s]+", e.get("MT5_AI_TELEGRAM_ALLOWED_IDS", "").strip()) if x.strip().lstrip("-").isdigit())
        if not ids:
            raise SystemExit("Set MT5_AI_TELEGRAM_ALLOWED_IDS to your numeric Telegram id (ask @userinfobot). "
                             "Without it anyone who finds the bot could try to use your account, so it will not start.")
        provider = (e.get("MT5_AI_LLM_PROVIDER") or "").strip().lower() or None
        model = key = None
        if provider:
            if provider not in PROVIDERS:
                raise SystemExit(f"MT5_AI_LLM_PROVIDER must be one of {PROVIDERS}.")
            model = (e.get("MT5_AI_LLM_MODEL") or DEFAULT_MODELS.get(provider) or "").strip() or None
            key = (e.get(KEY_ENV[provider]) or "").strip() or None
        return cls(token=token, allowed_ids=ids, symbol=e.get("MT5_AI_TELEGRAM_SYMBOL") or "XAUUSDm",
                   provider=provider, model=model, llm_key=key)


@dataclass
class Reply:
    text: str
    ticket_id: str | None = None      # set when the text is a fresh ticket: the transport adds Approve/Reject buttons


def _kv(d: dict, skip=()) -> str:
    return "\n".join(f"{k}: {v}" for k, v in d.items() if k not in skip and not isinstance(v, (dict, list)))


def parse_plan(args: list[str], default_symbol: str) -> dict | str:
    """/plan buy [SYMBOL] sl P tp P [risk X] [hold S] [tags a,b] [note ...] -> dict, or an error string."""
    if not args or args[0].lower() not in ("buy", "sell"):
        return PLAN_USAGE
    out: dict = {"side": args[0].upper(), "symbol": default_symbol, "risk_pct": None, "hold": 0, "tags": "", "note": ""}
    rest = args[1:]
    if rest and rest[0].lower() not in ("sl", "tp", "risk", "hold", "tags", "note"):
        out["symbol"], rest = rest[0], rest[1:]
    i = 0
    while i < len(rest):
        k = rest[i].lower()
        if k == "note":
            out["note"] = " ".join(rest[i + 1:])
            break
        if k not in ("sl", "tp", "risk", "hold", "tags") or i + 1 >= len(rest):
            return f"Could not read '{rest[i]}'.\n" + PLAN_USAGE
        v = rest[i + 1]
        try:
            if k in ("sl", "tp"):
                out[k] = float(v)
            elif k == "risk":
                out["risk_pct"] = float(v)
            elif k == "hold":
                out["hold"] = int(v)
            else:
                out["tags"] = v
        except ValueError:
            return f"'{v}' is not a valid number for {k}.\n" + PLAN_USAGE
        i += 2
    if "sl" not in out or "tp" not in out:
        return "Both sl and tp are required.\n" + PLAN_USAGE
    return out


class BotHandler:
    def __init__(self, service, allowed_ids, *, symbol: str = "XAUUSDm", llm: Callable[[str, str], str] | None = None,
                 clock: Callable[[], float] = time.time):
        self.svc, self.allowed, self.symbol, self.llm, self.clock = service, frozenset(allowed_ids), symbol, llm, clock
        self._last_llm = 0.0
        self._ticket_out: str | None = None

    # ---------------------------------------------------------------- entry
    def handle(self, user_id: int, text: str) -> str | None:
        r = self.handle_reply(user_id, text)
        return None if r is None else r.text

    def handle_reply(self, user_id: int, text: str) -> Reply | None:
        """None means 'ignore silently' (not an allowed user)."""
        self._ticket_out = None
        out = self._handle(user_id, text)
        return None if out is None else Reply(out, self._ticket_out)

    def approve(self, user_id: int, ticket_id: str) -> str | None:
        """The Approve button. Same as /yes <id>: places exactly that ticket, once."""
        return None if user_id not in self.allowed else self._yes([ticket_id])

    def reject(self, user_id: int, ticket_id: str) -> str | None:
        """The Reject button: burns the ticket so it can never be placed."""
        if user_id not in self.allowed:
            return None
        try:
            self.svc.tickets.take(ticket_id)
        except Exception:  # noqa: BLE001 - already used or expired: nothing left to cancel
            return "That ticket was already used or has expired."
        return f"Ticket {ticket_id} rejected. Nothing was placed."

    def _handle(self, user_id: int, text: str) -> str | None:
        if user_id not in self.allowed:
            return None
        text = (text or "").strip()
        if not text:
            return None
        try:
            if text.startswith("/"):
                cmd, *args = text.split()
                return self._command(cmd.split("@")[0].lower(), args, text)
            if self.llm:
                return self._ask(text)
            return "Send /help for the commands. (AI chat is not configured on this bot.)"
        except Exception as exc:  # noqa: BLE001 - never crash the polling loop on one bad message
            return f"Error: {type(exc).__name__}: {str(exc)[:300]}"

    def _command(self, cmd: str, args: list[str], raw: str) -> str:
        if cmd in ("/start", "/help"):
            return HELP
        if cmd == "/status":
            return _kv(self.svc.account_overview()) + "\n" + _kv(self.svc.todays_summary(self.symbol))
        if cmd == "/quote":
            return _kv(self.svc.get_quote(args[0] if args else self.symbol))
        if cmd == "/positions":
            ps = self.svc.list_positions()["positions"]
            return "\n".join(f"#{p['ticket']} {p['side']} {p['volume']:g} {p['symbol']} sl {p['sl']} tp {p['tp']} pnl {p['profit']:+.2f}"
                             + ("" if p["opened_by_this_server"] else "  (not opened by this bot)") for p in ps) or "No open positions."
        if cmd == "/today":
            return _kv(self.svc.todays_summary(args[0] if args else self.symbol))
        if cmd == "/plan":
            return self._plan(args)
        if cmd == "/yes":
            return self._yes(args)
        if cmd == "/close":
            if not args or not args[0].isdigit():
                return "Usage: /close POSITION_NUMBER (see /positions)"
            r = self.svc.close_position(int(args[0]))
            return "Closed." if r.get("closed") else f"Not closed: {r.get('broker') or r}"
        if cmd == "/halt":
            return "TRADING HALTED. " + self.svc.halt_trading("halted from Telegram")["resume"]
        if cmd == "/journal":
            j = self.svc.journal_review()
            return (f"placed {j['placed']}, closed {j['closed']}, open {j['still_open']}\n"
                    + json.dumps(j["overall"]) + "\n" + j["caveat"])
        if cmd == "/ask":
            return self._ask(raw[len("/ask"):].strip()) if self.llm else "AI chat is not configured on this bot (see the README)."
        return "Unknown command. Send /help."

    # ---------------------------------------------------------------- orders
    def _plan(self, args: list[str]) -> str:
        p = parse_plan(args, self.symbol)
        if isinstance(p, str):
            return p
        return self._prepare(p["symbol"], p["side"], p["sl"], p["tp"], p["risk_pct"], p["note"], p["tags"], p["hold"])

    def _prepare(self, symbol, side, sl, tp, risk_pct, note, tags, hold) -> str:
        r = self.svc.prepare_trade(symbol, side, sl, tp, risk_pct, note, tags, hold)
        if r["verdict"] != "PASS":
            return "BLOCKED - nothing was prepared:\n- " + "\n- ".join(r["reasons"])
        self._ticket_out = r["ticket_id"]
        return (r["ticket"] + (f"\n  exits by timer after {hold}s" if hold else "")
                + f"\n\nTap Approve to place exactly this ticket, or send /yes {r['ticket_id']}\n(Expires in {r['expires_in_seconds']}s. Ignore it or tap Reject to cancel.)")

    def _yes(self, args: list[str]) -> str:
        if len(args) != 1:
            return "Usage: /yes TICKET_ID (copy it from the ticket message)."
        r = self.svc.place_prepared_trade(args[0])
        if r.get("placed"):
            return (f"PLACED {r['side']} {r['lots'] if 'lots' in r else ''} {r['symbol']} at {r['fill_price']}\n"
                    f"stop {r['stop_loss']}  target {r['take_profit']}  position #{r['position_ticket']}  max loss ~{r['max_loss_at_stop']}"
                    + (f"\n{r['timed_exit']}" if r.get("timed_exit") else ""))
        return f"NOT placed: {r.get('error')}\n{r.get('note', '')}".strip()

    # ---------------------------------------------------------------- AI chat
    def _ask(self, question: str) -> str:
        if not question:
            return "Usage: /ask your question"
        now = self.clock()
        if now - self._last_llm < 3:
            return "One moment - please wait a few seconds between questions."
        self._last_llm = now
        snap = {"account": self.svc.account_overview(), "today": self.svc.todays_summary(self.symbol),
                "quote": self.svc.get_quote(self.symbol),
                "m15_candles_oldest_first": self.svc.get_candles(self.symbol, "M15", 24)["rows"]}
        try:
            reply = self.llm(SYSTEM_PROMPT, f"SNAPSHOT:\n{json.dumps(snap, default=str)}\n\nQUESTION:\n{question[:1500]}")
        except LLMError as exc:
            return f"AI unavailable: {exc}"
        m = _PLAN_LINE.search(reply)
        text = _PLAN_LINE.sub("", reply).strip()
        if not m:
            return text or "(no answer)"
        side, sym, sl, tp, hold, tags = m.groups()
        return (text + "\n\nThe AI proposed a trade. Checking it against the risk rules:\n"
                + self._prepare(sym, side.upper(), float(sl), float(tp), None, "proposed by AI chat", tags or "", int(hold or 0)))


# --------------------------------------------------------------------------- Telegram transport
def _chunks(text: str):
    while text:
        yield text[:MAX_MESSAGE]
        text = text[MAX_MESSAGE:]


def _keyboard(ticket_id: str) -> dict:
    return {"inline_keyboard": [[{"text": "\u2705 Approve", "callback_data": f"ok:{ticket_id}"},
                                 {"text": "\u274c Reject", "callback_data": f"no:{ticket_id}"}]]}


def run(settings: BotSettings, handler: BotHandler, *, client: httpx.Client | None = None, stop=lambda: False) -> None:
    api = f"https://api.telegram.org/bot{settings.token}"
    client = client or httpx.Client(timeout=40.0)
    offset, backoff = 0, 1.0
    print(f"mt5-ai Telegram bot running for {len(settings.allowed_ids)} allowed user(s). AI chat: {'on' if handler.llm else 'off'}.", flush=True)

    def call(method: str, **payload):
        return client.post(f"{api}/{method}", json=payload)

    def send(chat_id, text, ticket_id=None):
        parts = list(_chunks(text)) or ["(empty)"]
        for i, part in enumerate(parts):
            extra = {"reply_markup": _keyboard(ticket_id)} if ticket_id and i == len(parts) - 1 else {}
            call("sendMessage", chat_id=chat_id, text=part, **extra)

    def on_message(m: dict) -> None:
        if (m.get("chat") or {}).get("type") != "private" or "text" not in m:
            return
        uid = (m.get("from") or {}).get("id")
        reply = handler.handle_reply(uid, m["text"])
        if reply is None:
            print(f"ignored a message from a user id that is not allowed: {uid}", flush=True)
            return
        send(m["chat"]["id"], reply.text, reply.ticket_id)

    def on_button(q: dict) -> None:
        uid = (q.get("from") or {}).get("id")
        msg = q.get("message") or {}
        action, _, ticket_id = (q.get("data") or "").partition(":")
        text = None
        if (msg.get("chat") or {}).get("type") == "private" and action in ("ok", "no") and ticket_id:
            text = handler.approve(uid, ticket_id) if action == "ok" else handler.reject(uid, ticket_id)
        call("answerCallbackQuery", callback_query_id=q.get("id"))
        if text is None:
            print(f"ignored a button press from a user id that is not allowed: {uid}", flush=True)
            return
        if msg.get("message_id"):      # remove the buttons so they cannot be pressed twice
            call("editMessageReplyMarkup", chat_id=msg["chat"]["id"], message_id=msg["message_id"], reply_markup={"inline_keyboard": []})
        send(msg["chat"]["id"], text)

    while not stop():
        try:
            r = client.post(f"{api}/getUpdates", json={"offset": offset, "timeout": 30, "allowed_updates": ["message", "callback_query"]})
            if r.status_code != 200:
                raise httpx.HTTPError(f"HTTP {r.status_code}")
            for u in r.json().get("result", []):
                offset = u["update_id"] + 1
                if u.get("callback_query"):
                    on_button(u["callback_query"])
                elif u.get("message"):
                    on_message(u["message"])
            backoff = 1.0
        except (httpx.HTTPError, ValueError) as exc:
            # The URL (which holds the token) is deliberately NOT printed.
            print(f"telegram connection problem ({type(exc).__name__}); retrying in {backoff:.0f}s", flush=True)
            time.sleep(backoff)
            backoff = min(backoff * 2, 60.0)


def main() -> None:
    from .server import make_service

    s = BotSettings.from_env()
    llm = None
    if s.provider:
        if not s.llm_key:
            raise SystemExit(f"AI chat is enabled but {KEY_ENV[s.provider]} is not set on this machine.")
        provider, model, key = s.provider, s.model, s.llm_key
        llm = lambda system, user: complete(provider, model, system, user, api_key=key)  # noqa: E731
    run(s, BotHandler(make_service(), s.allowed_ids, symbol=s.symbol, llm=llm))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
