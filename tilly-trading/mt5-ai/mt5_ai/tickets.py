"""Single-use, expiring order tickets — the only way an order can be sent.

prepare_trade sizes and risk-checks a trade and issues a ticket holding the
EXACT parameters shown to the person. place_prepared_trade can only send a
ticket, so what was reviewed is what is sent, and one yes covers one order.
"""
from __future__ import annotations

import hashlib
import secrets
import time
from dataclasses import dataclass


class TicketError(Exception):
    pass


@dataclass(frozen=True)
class Ticket:
    id: str
    created: float
    expires: float
    symbol: str
    side: str
    lots: float
    sl: float
    tp: float
    ref_price: float
    risk_pct: float
    risk_money: float
    rr: float
    note: str
    fingerprint: str


def fingerprint(symbol: str, side: str, lots: float, sl: float, tp: float, ref_price: float) -> str:
    raw = f"{symbol}|{side}|{lots:.8f}|{sl:.8f}|{tp:.8f}|{ref_price:.8f}"
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


class TicketStore:
    def __init__(self, ttl_seconds: int, clock=time.time):
        self._ttl, self._clock = ttl_seconds, clock
        self._open: dict[str, Ticket] = {}

    def issue(self, *, symbol, side, lots, sl, tp, ref_price, risk_pct, risk_money, rr, note="") -> Ticket:
        now = self._clock()
        self._open = {k: t for k, t in self._open.items() if t.expires > now}
        t = Ticket(
            id=secrets.token_hex(3).upper(), created=now, expires=now + self._ttl,
            symbol=symbol, side=side.upper(), lots=lots, sl=sl, tp=tp, ref_price=ref_price,
            risk_pct=risk_pct, risk_money=risk_money, rr=rr, note=note,
            fingerprint=fingerprint(symbol, side.upper(), lots, sl, tp, ref_price),
        )
        self._open[t.id] = t
        return t

    def take(self, ticket_id: str) -> Ticket:
        """Removes and returns the ticket: it can be sent once, ever. A failed
        send does not give it back — prepare a fresh one."""
        key = (ticket_id or "").strip().upper()
        t = self._open.pop(key, None)
        if t is None:
            raise TicketError(f"No open ticket {ticket_id!r}: unknown, already used, or expired. Prepare the trade again.")
        if t.expires <= self._clock():
            raise TicketError(f"Ticket {t.id} expired {int(self._clock() - t.expires)}s ago. Prepare the trade again.")
        return t

    def describe(self, t: Ticket, digits: int = 2) -> str:
        f = lambda v: f"{v:.{digits}f}"  # noqa: E731
        return (
            f"TICKET {t.id}: {t.side} {t.lots:g} lots {t.symbol} at market (about {f(t.ref_price)})\n"
            f"  stop-loss {f(t.sl)}   take-profit {f(t.tp)}   reward:risk {t.rr:.2f}\n"
            f"  max loss about {t.risk_money:.2f} if the stop fills at its price "
            f"({t.risk_pct:g}% of the account; a fast market can fill worse)\n"
            f"  valid for {int(t.expires - t.created)}s, single use"
            + (f"\n  why: {t.note}" if t.note else "")
        )
