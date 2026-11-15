"""The trade journal: joins what was planned and placed with how it ended, in R."""
import json

import numpy as np
import pytest

from fake_mt5 import FakeMT5
from mt5_ai.broker import Mt5Broker
from mt5_ai.config import Settings
from mt5_ai.journal import MIN_TRADES_FOR_CONCLUSION, placed_trades, read_events, review
from mt5_ai.service import Mt5Service


@pytest.fixture
def setup(tmp_path):
    mt5 = FakeMT5()
    svc = Mt5Service(Mt5Broker(mt5), Settings(state_dir=tmp_path, max_trades_per_day=50, max_open_positions=50))
    return mt5, svc


def place(svc, tags="", **kw):
    args = dict(symbol="XAUUSD", side="BUY", sl=4995.0, tp=5010.0, tags=tags)
    args.update(kw)
    p = svc.prepare_trade(**args)
    assert p["verdict"] == "PASS", p
    r = svc.place_prepared_trade(p["ticket_id"])
    assert r["placed"], r
    return r


def test_prepare_and_place_log_tags_and_risk(setup, tmp_path):
    mt5, svc = setup
    r = place(svc, tags="setup:sweep, session:london")
    ev = read_events(tmp_path / "trades.jsonl")
    prepared = next(e for e in ev if e["event"] == "prepared")
    placed = next(e for e in ev if e["event"] == "placed")
    assert prepared["tags"] == "setup:sweep, session:london" and prepared["risk_money"] > 0
    rows = placed_trades(ev)
    assert len(rows) == 1 and rows[0]["tags"] == ["setup:sweep", "session:london"]
    assert rows[0]["position"] == r["position_ticket"] and rows[0]["risk_money"] == placed["risk_money"]


def test_open_trade_has_no_result_yet_and_closed_trade_is_in_r(setup):
    mt5, svc = setup
    r = place(svc, tags="a")
    pos = r["position_ticket"]
    mt5.add_deal(entry=mt5.DEAL_ENTRY_IN, position_id=pos, magic=Settings().magic)
    out = svc.journal_review()
    assert out["placed"] == 1 and out["still_open"] == 1 and out["closed"] == 0
    risk = svc.journal_review  # noqa: F841
    plan_risk = next(e for e in read_events(svc._log_path) if e["event"] == "prepared")["risk_money"]
    mt5.add_deal(entry=mt5.DEAL_ENTRY_OUT, profit=2 * plan_risk, commission=-1.0, position_id=pos, magic=Settings().magic, dtype=mt5.DEAL_TYPE_SELL)
    out = svc.journal_review()
    assert out["closed"] == 1
    assert out["recent"][0]["r"] == pytest.approx((2 * plan_risk - 1.0) / plan_risk, abs=0.01)
    assert "too few" in out["overall"]["reading"].lower()


def test_unknown_position_is_reported_not_invented(setup):
    mt5, svc = setup
    place(svc)
    out = svc.journal_review()
    assert out["no_outcome_found"] == 1 and out["closed"] == 0


def test_review_groups_by_tag_and_refuses_conclusions_on_small_samples():
    trades = [{"ticket": f"t{i}", "position": i, "symbol": "X", "side": "BUY", "tags": ["good"] if i % 2 else ["bad"],
               "risk_money": 10.0, "note": ""} for i in range(1, 11)]
    outcomes = {i: {"net": 20.0 if i % 2 else -10.0, "closed": True} for i in range(1, 11)}
    out = review(trades, outcomes)
    assert out["by_tag"]["good"]["mean_r"] == 2.0 and out["by_tag"]["bad"]["mean_r"] == -1.0
    assert all("too few" in s["reading"].lower() for s in out["by_tag"].values())


def test_review_gives_a_reading_with_enough_trades_and_says_luck_when_ci_spans_zero():
    rng = np.random.default_rng(0)
    n = MIN_TRADES_FOR_CONCLUSION + 40
    nets = rng.choice([-10.0, 10.0], size=n)
    trades = [{"ticket": f"t{i}", "position": i, "symbol": "X", "side": "BUY", "tags": [], "risk_money": 10.0, "note": ""} for i in range(n)]
    out = review(trades, {i: {"net": float(nets[i]), "closed": True} for i in range(n)})
    assert out["overall"]["trades"] == n and "(untagged)" in out["by_tag"]
    assert out["overall"]["reading"] in ("Indistinguishable from luck at this sample size.", "Above zero with confidence.", "Below zero with confidence.")
    assert out["caveat"]


def test_torn_log_line_does_not_hide_the_rest(tmp_path):
    p = tmp_path / "trades.jsonl"
    p.write_text('{"event": "prepared", "ticket": "a"}\n{broken\n{"event": "placed", "ticket": "a", "order": 5, "risk_money": 3}\n')
    rows = placed_trades(read_events(p))
    assert len(rows) == 1 and rows[0]["position"] == 5
