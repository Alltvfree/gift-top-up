"""A small local HTTP API so n8n (or any script) can read the account and hand the bot work.

It runs INSIDE the Telegram bot process (same service, same limits), on this machine only.

What it can do
  GET  /health              liveness (no secrets)
  GET  /status              account overview + today's result and loss budget
  GET  /positions           open trades this bot manages (live P&L, R, timer)
  GET  /journal             how the bot's placed trades ended, in R, by tag
  GET  /quote?symbol=       live price
  GET  /context?symbol=&side=&sl=&tp=   pre-trade flags for a trade you are considering
  GET  /bundle?symbol=&side=&sl=&tp=    all of the above in one call (what a reviewer agent needs)
  POST /prepare             make a TICKET and send it to Telegram with Approve / Reject buttons
  POST /notify              send a plain text message to the allowed Telegram users
  POST /halt                stop all new trades (the kill switch)

What it can NOT do, by construction: there is no endpoint that places, closes, modifies or sizes up an order.
A ticket made here still needs a human to tap Approve in Telegram, exactly like one made by /plan.

Safety
  - Bound to 127.0.0.1 by default. MT5_AI_API_HOST can name another address; do that only deliberately.
  - Every call except /health needs `Authorization: Bearer <MT5_AI_API_TOKEN>` (compared in constant time).
    The API refuses to start without a token of at least 20 characters.
  - Request bodies are capped at 4 KB; /prepare and /notify are rate limited; inputs are validated.
  - Tickets made here are tagged `source:n8n` so the journal keeps them apart from your own.
"""
from __future__ import annotations

import hmac
import json
import math
import re
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

MAX_BODY = 4096
MIN_TOKEN = 20
LIMITS = {"prepare": (6, 60.0), "notify": (30, 60.0), "halt": (6, 60.0)}     # (calls, per seconds)
_SYMBOL = re.compile(r"^[A-Za-z0-9._]{3,20}$")
_TAGS = re.compile(r"^[A-Za-z0-9:_,.\-]{0,120}$")


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


class Api:
    def __init__(self, handler, token: str, clock=time.monotonic):
        if len((token or "").strip()) < MIN_TOKEN:
            raise ValueError(f"MT5_AI_API_TOKEN must be at least {MIN_TOKEN} characters.")
        self.h, self._token, self._clock = handler, token.strip(), clock
        self._hits: dict[str, deque] = {}

    # ----------------------------------------------------------------- helpers
    def authorized(self, header: str | None) -> bool:
        got = (header or "")
        got = got[7:] if got.lower().startswith("bearer ") else ""
        return hmac.compare_digest(got.encode(), self._token.encode())

    def _limit(self, name: str) -> None:
        calls, window = LIMITS[name]
        q, now = self._hits.setdefault(name, deque()), self._clock()
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= calls:
            raise ApiError(429, f"Too many {name} calls (limit {calls} per {int(window)}s).")
        q.append(now)

    @staticmethod
    def _plan_args(q: dict) -> tuple[str, str, float, float]:
        symbol, side = (q.get("symbol") or [""])[0], (q.get("side") or [""])[0].upper()
        return Api._check_plan(symbol, side, (q.get("sl") or [None])[0], (q.get("tp") or [None])[0])

    @staticmethod
    def _check_plan(symbol, side, sl, tp) -> tuple[str, str, float, float]:
        if not _SYMBOL.match(str(symbol or "")):
            raise ApiError(400, "symbol must be letters/digits, 3-20 characters.")
        if str(side).upper() not in ("BUY", "SELL"):
            raise ApiError(400, "side must be BUY or SELL.")
        try:
            sl, tp = float(sl), float(tp)
        except (TypeError, ValueError):
            raise ApiError(400, "sl and tp must be numbers.") from None
        if not (math.isfinite(sl) and math.isfinite(tp) and sl > 0 and tp > 0):
            raise ApiError(400, "sl and tp must be positive, finite numbers.")
        return symbol, str(side).upper(), sl, tp

    # ------------------------------------------------------------------- routes
    def route(self, method: str, path: str, query: dict, body: dict) -> tuple[int, dict]:
        svc = self.h.svc
        try:
            if method == "GET":
                if path == "/status":
                    return 200, {"account": svc.account_overview(), "today": svc.todays_summary(self.h.symbol)}
                if path == "/positions":
                    return 200, svc.position_cards()
                if path == "/journal":
                    return 200, svc.journal_review()
                if path == "/quote":
                    sym = (query.get("symbol") or [self.h.symbol])[0]
                    if not _SYMBOL.match(sym):
                        raise ApiError(400, "bad symbol")
                    return 200, svc.get_quote(sym)
                if path == "/context":
                    return 200, svc.trade_context(*self._plan_args(query))
                if path == "/bundle":
                    sym, side, sl, tp = self._plan_args(query)
                    return 200, {"status": svc.account_overview(), "today": svc.todays_summary(sym), "positions": svc.position_cards(),
                                 "journal": svc.journal_review(), "context": svc.trade_context(sym, side, sl, tp),
                                 "quote": svc.get_quote(sym)}
            if method == "POST":
                if path == "/prepare":
                    self._limit("prepare")
                    sym, side, sl, tp = self._check_plan(body.get("symbol"), body.get("side"), body.get("sl"), body.get("tp"))
                    hold = int(body.get("hold", 0) or 0)
                    tags, note = str(body.get("tags", "") or ""), str(body.get("note", "") or "")[:200]
                    if not 0 <= hold <= 3600 or not _TAGS.match(tags):
                        raise ApiError(400, "hold must be 0-3600 and tags only letters, digits and : _ , . -")
                    tags = ",".join(x for x in (tags, "source:n8n") if x)
                    with self.h.lock:
                        self.h._ticket_out = None
                        text = self.h._prepare(sym, side, sl, tp, None, note or "prepared by n8n", tags, hold)
                        ticket_id = self.h._ticket_out
                    if ticket_id:
                        self.h.push(text, ticket_id)
                    return 200, {"verdict": "TICKET" if ticket_id else "NOT_PREPARED", "ticket_id": ticket_id, "text": text,
                                 "next": "A human must tap Approve in Telegram. This API cannot place orders." if ticket_id else None}
                if path == "/notify":
                    self._limit("notify")
                    text = str(body.get("text", "") or "").strip()
                    if not text:
                        raise ApiError(400, "text is required.")
                    return 200, {"queued": bool(self.h.push(text[:3500]))}
                if path == "/halt":
                    self._limit("halt")
                    r = self.svc_halt(str(body.get("reason", "") or "halted from the automation API")[:200])
                    self.h.push("\U0001F6D1 TRADING HALTED from the automation API. " + r["resume"])
                    return 200, r
            raise ApiError(404, "no such endpoint")
        except ApiError as e:
            return e.status, {"error": e.message}
        except Exception as exc:  # noqa: BLE001 - never leak internals; the bot's log has the detail
            return 500, {"error": f"{type(exc).__name__}"}

    def svc_halt(self, reason: str) -> dict:
        return self.h.svc.halt_trading(reason)


def make_server(handler, token: str, host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    api = Api(handler, token)

    class Req(BaseHTTPRequestHandler):
        server_version = "mt5-ai"

        def log_message(self, *args):          # keep the console quiet; never log headers or bodies
            pass

        def _send(self, status: int, payload: dict) -> None:
            data = json.dumps(payload, default=str).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _handle(self, method: str) -> None:
            url = urlparse(self.path)
            if method == "GET" and url.path == "/health":
                return self._send(200, {"ok": True})
            if not api.authorized(self.headers.get("Authorization")):
                return self._send(401, {"error": "missing or wrong bearer token"})
            body: dict = {}
            if method == "POST":
                try:
                    length = int(self.headers.get("Content-Length") or 0)
                except ValueError:
                    length = -1
                if length < 0 or length > MAX_BODY:
                    return self._send(413, {"error": f"body must be at most {MAX_BODY} bytes"})
                try:
                    body = json.loads(self.rfile.read(length) or b"{}")
                    if not isinstance(body, dict):
                        raise ValueError
                except ValueError:
                    return self._send(400, {"error": "body must be a JSON object"})
            status, payload = api.route(method, url.path, parse_qs(url.query), body)
            self._send(status, payload)

        def do_GET(self):
            self._handle("GET")

        def do_POST(self):
            self._handle("POST")

    return ThreadingHTTPServer((host, port), Req)


def start_in_thread(handler, token: str, host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    server = make_server(handler, token, host, port)
    threading.Thread(target=server.serve_forever, name="mt5-ai-automation-api", daemon=True).start()
    return server
