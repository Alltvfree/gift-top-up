import pytest

from mt5_ai.tickets import TicketError, TicketStore, fingerprint


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def _issue(store, **kw):
    base = dict(symbol="XAUUSD", side="buy", lots=0.2, sl=4995.0, tp=5010.0, ref_price=5000.0,
                risk_pct=1.0, risk_money=100.0, rr=3.0)
    return store.issue(**{**base, **kw})


def test_a_ticket_can_be_taken_exactly_once():
    store = TicketStore(300, Clock())
    t = _issue(store)
    assert store.take(t.id.lower()).id == t.id  # case-insensitive
    with pytest.raises(TicketError, match="already used"):
        store.take(t.id)


def test_an_expired_ticket_is_refused():
    clock = Clock()
    store = TicketStore(300, clock)
    t = _issue(store)
    clock.t += 301
    with pytest.raises(TicketError, match="expired|unknown"):
        store.take(t.id)


def test_unknown_ticket_is_refused():
    with pytest.raises(TicketError):
        TicketStore(300, Clock()).take("NOPE")
    with pytest.raises(TicketError):
        TicketStore(300, Clock()).take("")


def test_fingerprint_changes_with_any_parameter():
    base = ("XAUUSD", "BUY", 0.2, 4995.0, 5010.0, 5000.0)
    assert fingerprint(*base) == fingerprint(*base)
    for i, bump in enumerate([None, "SELL", 0.21, 4994.0, 5011.0, 5001.0]):
        if bump is None:
            continue
        changed = list(base)
        changed[i] = bump
        assert fingerprint(*changed) != fingerprint(*base)


def test_ticket_text_shows_everything_the_person_approves():
    store = TicketStore(300, Clock())
    text = store.describe(_issue(store, note="trend pullback"))
    for needle in ("BUY 0.2 lots XAUUSD", "stop-loss 4995.00", "take-profit 5010.00", "100.00", "single use", "trend pullback"):
        assert needle in text
