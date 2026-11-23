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
POLL_SECONDS = 8        # long-poll length: also how quickly a closed-trade alert can arrive
ALERT_EVERY = 8.0
PLAN_USAGE = ("Usage: /plan buy|sell [SYMBOL] sl PRICE tp PRICE [risk PCT] [hold SECONDS] [tags a,b] [note TEXT...]\n"
              "Example: /plan buy XAUUSDm sl 3880 tp 3890 hold 90 tags style:scalp")
HELP = ("Commands:\n"
        "/status  account, mode, limits\n"
        "/quote [SYMBOL]  live price\n"
        "/panel  live panel: price, today, open trades with Close / Breakeven buttons\n"
        "/ticket  show the latest waiting ticket again\n"
        "/positions  open positions\n"
        "/today  today's result and loss budget left\n"
        "/plan ...  prepare a ticket (sends NO order)\n"
        "/buy or /sell [SYMBOL] [stop D] [rr R] [hold S]  one-tap ticket from the live price (also the BUY / SELL buttons)\n"
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
    quick_hold: int = 90
    quick_rr: float = 2.0
    quick_stop: float | None = None     # price distance; None = automatic from spread and recent range
    block_flags: int = 0                # refuse to prepare a ticket that has at least this many warning flags (0 = only warn)

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
        def num(name, default, cast):
            raw = (e.get(name) or "").strip()
            return cast(raw) if raw else default

        return cls(token=token, allowed_ids=ids, symbol=e.get("MT5_AI_TELEGRAM_SYMBOL") or "XAUUSDm",
                   provider=provider, model=model, llm_key=key, quick_hold=num("MT5_AI_QUICK_HOLD", 90, int),
                   quick_rr=num("MT5_AI_QUICK_RR", 2.0, float), quick_stop=num("MT5_AI_QUICK_STOP", None, float),
                   block_flags=num("MT5_AI_QUICK_BLOCK_FLAGS", 0, int))


BTN_BUY, BTN_SELL = "\U0001F7E2 BUY", "\U0001F534 SELL"
BTN_QUOTE, BTN_STATUS, BTN_POS, BTN_HALT = "\U0001F4C8 Quote", "\U0001F4CA Status", "\U0001F4C2 Positions", "\U0001F6D1 Halt"
BTN_PANEL, BTN_TICKET = "\U0001F9ED Panel", "\U0001F3AB Ticket"
BUTTON_COMMANDS = {BTN_BUY: "/buy", BTN_SELL: "/sell", BTN_QUOTE: "/quote", BTN_STATUS: "/status", BTN_POS: "/positions", BTN_HALT: "/halt",
                   BTN_PANEL: "/panel", BTN_TICKET: "/ticket"}
MENU_KEYBOARD = {"keyboard": [[{"text": BTN_BUY}, {"text": BTN_SELL}], [{"text": BTN_PANEL}, {"text": BTN_TICKET}],
                              [{"text": BTN_QUOTE}, {"text": BTN_STATUS}, {"text": BTN_POS}], [{"text": BTN_HALT}]],
                 "resize_keyboard": True, "is_persistent": True}
QUICK_USAGE = "Usage: /buy or /sell [SYMBOL] [stop PRICE_DISTANCE] [rr RATIO] [hold SECONDS]"


@dataclass
class Reply:
    text: str
    ticket_id: str | None = None      # set when the text is a fresh ticket: the transport adds Approve/Reject buttons
    menu: bool = False                # show the BUY / SELL / Quote... keyboard
    markup: dict | None = None        # explicit inline keyboard (the panel); wins over the ticket buttons


@dataclass
class Press:
    """What a button press should do on screen."""
    toast: str = ""                   # the small pop-up
    send: str | None = None           # a new message
    ticket_id: str | None = None      # ...that carries Approve/Reject
    edit: tuple[str, dict] | None = None      # rewrite the message that held the button (text, inline keyboard)
    clear_buttons: bool = False       # remove the buttons from that message


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
                 clock: Callable[[], float] = time.time, quick_hold: int = 90, quick_rr: float = 2.0, quick_stop: float | None = None,
                 block_flags: int = 0):
        self.svc, self.allowed, self.symbol, self.llm, self.clock = service, frozenset(allowed_ids), symbol, llm, clock
        self.quick_hold, self.quick_rr, self.quick_stop = quick_hold, quick_rr, quick_stop
        self._last_llm = 0.0
        self.block_flags = block_flags
        self._ticket_out: str | None = None
        self._menu_out = False
        self._markup_out: dict | None = None
        self._last_ticket: tuple[str, str] | None = None
        self._budget_warned_day: str | None = None

    # ---------------------------------------------------------------- entry
    def handle(self, user_id: int, text: str) -> str | None:
        r = self.handle_reply(user_id, text)
        return None if r is None else r.text

    def handle_reply(self, user_id: int, text: str) -> Reply | None:
        """None means 'ignore silently' (not an allowed user)."""
        self._ticket_out, self._menu_out, self._markup_out = None, False, None
        out = self._handle(user_id, text)
        return None if out is None else Reply(out, self._ticket_out, self._menu_out, self._markup_out)

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

    def press(self, user_id: int, data: str) -> Press | None:
        """An inline-button press. None = not an allowed user (ignored silently)."""
        if user_id not in self.allowed:
            return None
        action, _, arg = (data or "").partition(":")
        try:
            if action == "ok" and arg:
                return Press(send=self.approve(user_id, arg), clear_buttons=True)
            if action == "no" and arg:
                return Press(send=self.reject(user_id, arg), clear_buttons=True)
            if action == "rf":
                return Press(toast="Refreshed", edit=self.panel())
            if action == "qk" and arg in ("BUY", "SELL"):
                self._ticket_out = None
                text = self._quick(arg, [])
                return Press(toast=f"{arg} ticket", send=text, ticket_id=self._ticket_out)
            if action in ("cl", "be", "tm") and arg.isdigit():
                pos = int(arg)
                if action == "cl":
                    r = self.svc.close_position(pos)
                    msg = "Closed." if r.get("closed") else f"Not closed: {r.get('broker') or r}"
                elif action == "be":
                    r = self.svc.move_to_breakeven(pos)
                    msg = f"Stop moved to breakeven ({r['breakeven_stop']})." if r.get("moved") else f"Not moved: {r.get('error') or r.get('broker')}"
                else:
                    r = self.svc.cancel_timer(pos)
                    msg = r.get("note") if r.get("cancelled") else r.get("error")
                return Press(toast=msg[:190], send=msg, edit=self.panel())
        except Exception as exc:  # noqa: BLE001
            return Press(toast="Error", send=f"Error: {type(exc).__name__}: {str(exc)[:300]}")
        return Press(toast="Unknown button.")

    # ---------------------------------------------------------------- panel and alerts
    def panel(self) -> tuple[str, dict]:
        """One screen with everything: price, today, each open trade and the buttons to manage it."""
        q = self.svc.get_quote(self.symbol)
        today = self.svc.todays_summary(self.symbol)
        cards = self.svc.position_cards()
        lines = [f"\U0001F9ED PANEL  {q['symbol']}  bid {q['bid']}  ask {q['ask']}  spread {q['spread_price']}",
                 f"Today: {today['realized_pnl_all_strategies']:+.2f}   loss budget left {today['loss_budget_left']:.2f}   trades left {today['trades_left_today']}"]
        rows = [[{"text": "\U0001F7E2 BUY", "callback_data": "qk:BUY"}, {"text": "\U0001F534 SELL", "callback_data": "qk:SELL"}],
                [{"text": "\U0001F504 Refresh", "callback_data": "rf"}]]
        if not cards["positions"]:
            lines.append("No open trades.")
        for c in cards["positions"]:
            r = f" ({c['r_now']:+.2f}R)" if c["r_now"] is not None else ""
            timer = f"  timer {c['timer_seconds_left']}s" if c["timer_seconds_left"] is not None else ""
            lines.append(f"#{c['position']} {c['side']} {c['lots']:g} @ {c['entry']}  now {c['price_now']}  {c['profit_now']:+.2f}{r}\n"
                         f"   stop {c['stop_loss']}  target {c['take_profit']}{timer}")
            row = [{"text": f"\u274c Close #{c['position']}", "callback_data": f"cl:{c['position']}"}]
            if c["can_move_stop_to_breakeven"]:
                row.append({"text": "\U0001F6E1 Breakeven", "callback_data": f"be:{c['position']}"})
            if c["timer_seconds_left"] is not None:
                row.append({"text": "\u23F1 Cancel timer", "callback_data": f"tm:{c['position']}"})
            rows.append(row)
        if cards["others_not_managed_here"]:
            lines.append(f"({cards['others_not_managed_here']} other open position(s) not opened by this bot; manage those in MT5.)")
        lines.append(f"Updated {q['server_time'][11:19]} server time")
        return "\n".join(lines), {"inline_keyboard": rows}

    def alerts(self) -> list[str]:
        """Messages the bot should push on its own: trades that closed, and a low loss budget (once a day)."""
        out = []
        for e in self.svc.new_closes():
            icon = "\u2705" if e["net"] > 0 else "\u274c" if e["net"] < 0 else "\u2796"
            r = f" ({e['r']:+.2f}R)" if e["r"] is not None else ""
            out.append(f"{icon} Closed #{e['position']} {e['side']} {e['lots']:g} {e['symbol']}: {e['reason']}.\nResult {e['net']:+.2f}{r}")
        try:
            t = self.svc.todays_summary(self.symbol)
            limit = -t["daily_loss_limit"]
            if limit > 0 and t["loss_budget_left"] <= 0.25 * limit and self._budget_warned_day != t["server_day"]:
                self._budget_warned_day = t["server_day"]
                out.append(f"\u26A0 Loss budget is nearly used: {t['loss_budget_left']:.2f} left of {limit:.2f} today. Consider stopping for the day.")
        except Exception:  # noqa: BLE001
            pass
        return out

    def _heads_up(self, symbol: str, side: str, sl: float, tp: float) -> dict:
        try:
            return self.svc.trade_context(symbol, side, sl, tp)
        except Exception:  # noqa: BLE001 - the checks are advice; they must never stop a ticket from being prepared
            return {"flags": [], "notes": [], "h1_trend": "unknown"}

    def _handle(self, user_id: int, text: str) -> str | None:
        if user_id not in self.allowed:
            return None
        text = BUTTON_COMMANDS.get((text or "").strip(), (text or "").strip())
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
        if cmd in ("/start", "/menu"):
            self._menu_out = True
            return "Menu on. Tap BUY or SELL to prepare a ticket from the live price, then Approve to place it.\n\n" + HELP
        if cmd == "/help":
            return HELP
        if cmd == "/panel":
            text, markup = self.panel()
            self._markup_out = markup
            return text
        if cmd == "/ticket":
            if self._last_ticket and self.svc.tickets.is_open(self._last_ticket[0]):
                self._ticket_out = self._last_ticket[0]
                return self._last_ticket[1]
            return "No ticket is waiting (it may have expired). Tap BUY or SELL for a fresh one."
        if cmd in ("/buy", "/sell"):
            return self._quick(cmd[1:].upper(), args)
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

    def _quick(self, side: str, args: list[str]) -> str:
        """One-tap trade: stop and target are computed from the live quote. Still only a TICKET."""
        symbol, stop, rr, hold, rest = self.symbol, self.quick_stop, self.quick_rr, self.quick_hold, list(args)
        if rest and rest[0].lower() not in ("stop", "rr", "hold"):
            symbol, rest = rest[0], rest[1:]
        i = 0
        while i < len(rest):
            k = rest[i].lower()
            if k not in ("stop", "rr", "hold") or i + 1 >= len(rest):
                return f"Could not read '{rest[i]}'.\n" + QUICK_USAGE
            try:
                v = rest[i + 1]
                stop, rr, hold = (float(v), rr, hold) if k == "stop" else (stop, float(v), hold) if k == "rr" else (stop, rr, int(v))
            except ValueError:
                return f"'{rest[i + 1]}' is not a valid number for {k}.\n" + QUICK_USAGE
            i += 2
        q = self.svc.get_quote(symbol)
        digits = self.svc.broker.spec(q["symbol"]).digits
        entry = q["ask"] if side == "BUY" else q["bid"]
        if stop is None:   # at least 6x the spread (the server blocks a spread above 20% of the stop), else the recent M5 range
            rows = self.svc.get_candles(q["symbol"], "M5", 12)["rows"]
            stop = max(6 * q["spread_price"], sum(r[2] - r[3] for r in rows) / max(len(rows), 1))
        sign = 1 if side == "BUY" else -1
        sl, tp = round(entry - sign * stop, digits), round(entry + sign * rr * stop, digits)
        return (f"Quick {side} {q['symbol']} at about {entry}: stop {stop:.{digits}f} away, target {rr:g}x that, exit timer {hold}s.\n\n"
                + self._prepare(q["symbol"], side, sl, tp, None, f"quick {side.lower()} from the Telegram button", "style:quick", hold))

    def _prepare(self, symbol, side, sl, tp, risk_pct, note, tags, hold) -> str:
        ctx = self._heads_up(symbol, side, sl, tp)
        flags = ctx["flags"]
        if self.block_flags and len(flags) >= self.block_flags:
            return ("NOT PREPARED - too many warning flags (" + str(len(flags)) + "):\n- " + "\n- ".join(ctx["notes"])
                    + "\n(Your limit is set by MT5_AI_QUICK_BLOCK_FLAGS. Wait for better conditions, or set the number higher.)")
        tags = ",".join(x for x in [tags, *[f"flag:{f.replace('_', '-')}" for f in flags]] if x)
        r = self.svc.prepare_trade(symbol, side, sl, tp, risk_pct, note, tags, hold)
        if r["verdict"] != "PASS":
            return "BLOCKED - nothing was prepared:\n- " + "\n- ".join(r["reasons"])
        self._ticket_out = r["ticket_id"]
        heads = ("\n\n\u26A0 Heads-up (context, not a forecast):\n- " + "\n- ".join(ctx["notes"])) if ctx["notes"] else ""
        text = (r["ticket"] + (f"\n  exits by timer after {hold}s" if hold else "")
                + f"\n  hourly trend: {ctx['h1_trend']}" + heads
                + f"\n\nTap Approve to place exactly this ticket, or send /yes {r['ticket_id']}\n(Expires in {r['expires_in_seconds']}s. Ignore it or tap Reject to cancel.)")
        self._last_ticket = (r["ticket_id"], text)
        return text

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
                "open_positions": self.svc.position_cards()["positions"],
                "journal_overall": self.svc.journal_review()["overall"],
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

    def send(chat_id, text, ticket_id=None, menu=False, markup=None):
        parts = list(_chunks(text)) or ["(empty)"]
        for i, part in enumerate(parts):
            extra = {}
            if i == len(parts) - 1:
                if markup:
                    extra = {"reply_markup": markup}
                elif ticket_id:
                    extra = {"reply_markup": _keyboard(ticket_id)}
                elif menu:
                    extra = {"reply_markup": MENU_KEYBOARD}
            call("sendMessage", chat_id=chat_id, text=part, **extra)

    def on_message(m: dict) -> None:
        if (m.get("chat") or {}).get("type") != "private" or "text" not in m:
            return
        uid = (m.get("from") or {}).get("id")
        reply = handler.handle_reply(uid, m["text"])
        if reply is None:
            print(f"ignored a message from a user id that is not allowed: {uid}", flush=True)
            return
        send(m["chat"]["id"], reply.text, reply.ticket_id, reply.menu, reply.markup)

    def on_button(q: dict) -> None:
        uid = (q.get("from") or {}).get("id")
        msg = q.get("message") or {}
        chat = msg.get("chat") or {}
        res = handler.press(uid, q.get("data") or "") if chat.get("type") == "private" else None
        call("answerCallbackQuery", callback_query_id=q.get("id"), **({"text": res.toast} if res and res.toast else {}))
        if res is None:
            print(f"ignored a button press from a user id that is not allowed: {uid}", flush=True)
            return
        mid, cid = msg.get("message_id"), chat.get("id")
        if res.clear_buttons and mid:      # remove the buttons so they cannot be pressed twice
            call("editMessageReplyMarkup", chat_id=cid, message_id=mid, reply_markup={"inline_keyboard": []})
        if res.edit and mid:
            call("editMessageText", chat_id=cid, message_id=mid, text=res.edit[0][:MAX_MESSAGE], reply_markup=res.edit[1])
        if res.send:
            send(cid, res.send, res.ticket_id)

    last_alert = 0.0

    def push_alerts() -> None:
        nonlocal last_alert
        if time.time() - last_alert < ALERT_EVERY:
            return
        last_alert = time.time()
        try:
            for text in handler.alerts():
                for uid in settings.allowed_ids:      # a private chat's id equals the user's id
                    send(uid, text)
        except Exception as exc:  # noqa: BLE001 - alerts are best-effort; never kill the loop
            print(f"alert check failed ({type(exc).__name__})", flush=True)

    while not stop():
        try:
            r = client.post(f"{api}/getUpdates", json={"offset": offset, "timeout": POLL_SECONDS, "allowed_updates": ["message", "callback_query"]})
            if r.status_code != 200:
                raise httpx.HTTPError(f"HTTP {r.status_code}")
            for u in r.json().get("result", []):
                offset = u["update_id"] + 1
                if u.get("callback_query"):
                    on_button(u["callback_query"])
                elif u.get("message"):
                    on_message(u["message"])
            backoff = 1.0
            push_alerts()
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
    run(s, BotHandler(make_service(), s.allowed_ids, symbol=s.symbol, llm=llm,
                      quick_hold=s.quick_hold, quick_rr=s.quick_rr, quick_stop=s.quick_stop, block_flags=s.block_flags))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
