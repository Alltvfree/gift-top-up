"""Trade management shared by Telegram and MCP: cards, breakeven, timers, close alerts, pre-trade flags, the panel."""
import json

import numpy as np
import pandas as pd
import pytest

from fake_mt5 import FakeMT5
from mt5_ai.broker import Mt5Broker
from mt5_ai.config import Settings
from mt5_ai.context import assess, h1_trend
from mt5_ai.service import Mt5Service
from mt5_ai.telegram_bot import BotHandler

ME = 111
MAGIC = Settings().magic


@pytest.fixture
def env(tmp_path):
    mt5 = FakeMT5()
    svc = Mt5Service(Mt5Broker(mt5), Settings(state_dir=tmp_path, max_trades_per_day=50, max_open_positions=50), clock=lambda: 1000.0)
    return mt5, svc


def open_trade(svc, mt5, hold=0):
    p = svc.prepare_trade("XAUUSD", "BUY", 4995.0, 5010.0, tags="a", max_hold_seconds=hold)
    assert p["verdict"] == "PASS", p
    r = svc.place_prepared_trade(p["ticket_id"])
    assert r["placed"], r
    return r["position_ticket"]


# --- pre-trade context -----------------------------------------------------------------------------------
def bars(n, start=100.0, step=0.0, rng=2.0, spread=20):
    c = start + np.arange(n) * step
    return pd.DataFrame({"time": pd.date_range("2024-01-01", periods=n, freq="5min"), "open": c, "high": c + rng, "low": c - rng,
                         "close": c, "spread": spread})


def kw(**over):
    d = dict(m5=bars(60), m15=bars(60), h1=bars(80, step=0.5), spread_price=0.2, typical_spread_price=0.2, server_hour=12)
    d.update(over)
    return d


def test_h1_trend_reads_up_down_flat_and_unknown():
    assert h1_trend(bars(80, step=0.5)) == "up" and h1_trend(bars(80, step=-0.5)) == "down" and h1_trend(bars(10)) == "unknown"
    assert h1_trend(bars(80, step=0.0)) == "flat"


def test_clean_trade_has_no_flags():
    out = assess("BUY", 130.0, 126.0, 133.0, **kw(m15=bars(60, start=130, rng=5.0)))   # target inside the recent range
    assert out["flags"] == [] and out["h1_trend"] == "up"


@pytest.mark.parametrize("side,flag", [("SELL", "against_h1_trend")])
def test_against_the_hourly_trend_is_flagged(side, flag):
    assert flag in assess(side, 130.0, 134.0, 124.0, **kw())["flags"]


def test_each_other_flag_fires_on_its_own_condition():
    assert "wide_spread" in assess("BUY", 130, 126, 140, **kw(spread_price=0.5))["flags"]
    assert "stop_inside_noise" in assess("BUY", 130, 129, 140, **kw())["flags"]           # 1.0 stop vs a 4.0 typical range
    assert "target_beyond_range" in assess("BUY", 130, 126, 500, **kw())["flags"]
    assert "thin_hours" in assess("BUY", 130, 126, 140, **kw(server_hour=22))["flags"]
    assert "thin_hours" not in assess("BUY", 130, 126, 140, **kw(server_hour=12))["flags"]


# --- service: cards, breakeven, timer, closes ---------------------------------------------------------------
def test_position_cards_show_profit_r_timer_and_only_our_positions(env):
    mt5, svc = env
    pos = open_trade(svc, mt5, hold=90)
    mt5.add_position(magic=999)                                   # someone else's: counted, never managed
    next(p for p in mt5.positions if p.ticket == pos).profit = 20.0
    cards = svc.position_cards()
    c = cards["positions"][0]
    assert c["position"] == pos and c["profit_now"] == 20.0 and c["timer_seconds_left"] == 90 and cards["others_not_managed_here"] == 1
    assert c["r_now"] == pytest.approx(20.0 / c["risk_at_stop"], abs=0.01) and c["can_move_stop_to_breakeven"] is False


def test_breakeven_needs_price_beyond_entry_plus_spread_then_never_widens(env):
    mt5, svc = env
    pos = open_trade(svc, mt5)
    assert svc.move_to_breakeven(pos)["moved"] is False and "Not yet" in svc.move_to_breakeven(pos)["error"]
    mt5.bid, mt5.ask = 5006.0, 5006.25
    entry = next(p for p in mt5.positions if p.ticket == pos).price_open
    out = svc.move_to_breakeven(pos)
    assert out["moved"] and out["breakeven_stop"] == pytest.approx(entry + 0.25, abs=0.01)
    assert next(p for p in mt5.positions if p.ticket == pos).sl == pytest.approx(entry + 0.25, abs=0.01)
    assert svc.move_to_breakeven(pos)["moved"] is False                       # already there
    assert svc.move_to_breakeven(424242)["moved"] is False


def test_cancel_timer_only_removes_a_timer(env):
    mt5, svc = env
    pos = open_trade(svc, mt5, hold=60)
    assert svc.cancel_timer(pos)["cancelled"] and svc.cancel_timer(pos)["cancelled"] is False
    svc._clock = lambda: 9999.0
    assert svc.run_expiries() == [] and any(p.ticket == pos for p in mt5.positions)


def test_new_closes_reports_result_r_and_reason_once_and_never_the_past(env):
    mt5, svc = env
    assert svc.new_closes() == []                                              # first call only records
    pos = open_trade(svc, mt5)
    assert svc.new_closes() == []
    risk = next(e for e in svc_events(svc) if e["event"] == "placed")["risk_money"]
    mt5.positions = []
    mt5.add_deal(entry=mt5.DEAL_ENTRY_IN, position_id=pos, magic=MAGIC)
    mt5.add_deal(entry=mt5.DEAL_ENTRY_OUT, position_id=pos, magic=MAGIC, profit=-risk, dtype=mt5.DEAL_TYPE_SELL, reason=mt5.DEAL_REASON_SL, price=4995.0)
    [e] = svc.new_closes()
    assert e["position"] == pos and e["net"] == pytest.approx(-risk, abs=0.01) and e["r"] == pytest.approx(-1.0, abs=0.01)
    assert e["reason"] == "hit its stop-loss" and svc.new_closes() == []


def svc_events(svc):
    return [json.loads(line) for line in svc._log_path.read_text().splitlines()]


# --- Telegram -------------------------------------------------------------------------------------------------------
@pytest.fixture
def bot(env):
    mt5, svc = env
    return mt5, svc, BotHandler(svc, {ME}, symbol="XAUUSD", clock=lambda: 1000.0)


def test_panel_shows_price_today_and_buttons_for_each_open_trade(bot):
    mt5, svc, b = bot
    assert "No open trades" in b.handle(ME, "/panel")
    pos = open_trade(svc, mt5, hold=90)
    mt5.bid, mt5.ask = 5006.0, 5006.25
    r = b.handle_reply(ME, "\U0001F9ED Panel")
    data = [btn["callback_data"] for row in r.markup["inline_keyboard"] for btn in row]
    assert "PANEL" in r.text and f"#{pos} BUY" in r.text and "timer 90s" in r.text
    assert {"qk:BUY", "qk:SELL", "rf", f"cl:{pos}", f"be:{pos}", f"tm:{pos}"} <= set(data)


def test_panel_buttons_close_breakeven_and_cancel_timer(bot):
    mt5, svc, b = bot
    pos = open_trade(svc, mt5, hold=90)
    assert "Not moved" in b.press(ME, f"be:{pos}").send
    mt5.bid, mt5.ask = 5006.0, 5006.25
    assert "breakeven" in b.press(ME, f"be:{pos}").send
    assert "closes only at its stop-loss" in b.press(ME, f"tm:{pos}").send
    res = b.press(ME, f"cl:{pos}")
    assert res.send == "Closed." and res.edit and not any(p.ticket == pos for p in mt5.positions)


def test_refresh_and_quick_buttons(bot):
    mt5, svc, b = bot
    assert "PANEL" in b.press(ME, "rf").edit[0]
    r = b.press(ME, "qk:BUY")
    assert "TICKET" in r.send and r.ticket_id and mt5.sent == []


def test_strangers_and_garbage_cannot_use_panel_buttons(bot):
    mt5, svc, b = bot
    pos = open_trade(svc, mt5)
    sent = len(mt5.sent)
    assert b.press(999, f"cl:{pos}") is None and b.press(999, "qk:BUY") is None
    assert len(mt5.sent) == sent and any(p.ticket == pos for p in mt5.positions)
    for junk in ("", "cl:", "cl:abc", "zz:1", "qk:HOLD"):
        assert b.press(ME, junk).send is None
    assert len(mt5.sent) == sent


def test_ticket_button_reshows_a_waiting_ticket_and_not_a_used_one(bot):
    mt5, svc, b = bot
    assert "No ticket is waiting" in b.handle(ME, "\U0001F3AB Ticket")
    first = b.handle_reply(ME, "/plan buy XAUUSD sl 4995 tp 5010")
    again = b.handle_reply(ME, "/ticket")
    assert again.ticket_id == first.ticket_id and "TICKET" in again.text
    b.handle(ME, f"/yes {first.ticket_id}")
    assert "No ticket is waiting" in b.handle(ME, "/ticket")


def test_flags_are_shown_logged_as_tags_and_can_block(bot, monkeypatch):
    mt5, svc, b = bot
    ctx = {"flags": ["against_h1_trend", "wide_spread"], "notes": ["going against the hourly trend", "spread is wider than usual"], "h1_trend": "down"}
    monkeypatch.setattr(svc, "trade_context", lambda *a, **k: ctx)
    text = b.handle(ME, "/plan buy XAUUSD sl 4995 tp 5010 tags style:scalp")
    assert "Heads-up" in text and "against the hourly trend" in text and "hourly trend: down" in text
    prepared = [e for e in svc_events(svc) if e["event"] == "prepared"][-1]
    assert prepared["tags"] == "style:scalp,flag:against-h1-trend,flag:wide-spread"
    strict = BotHandler(svc, {ME}, symbol="XAUUSD", block_flags=2)
    out = strict.handle(ME, "/plan buy XAUUSD sl 4995 tp 5010")
    assert out.startswith("NOT PREPARED") and "/yes" not in out
    assert len([e for e in svc_events(svc) if e["event"] == "prepared"]) == 1


def test_a_failing_context_check_never_stops_a_ticket(bot, monkeypatch):
    mt5, svc, b = bot
    monkeypatch.setattr(svc, "trade_context", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert "TICKET" in b.handle(ME, "/plan buy XAUUSD sl 4995 tp 5010")


def test_alerts_report_a_close_once_and_warn_about_the_loss_budget_once(bot):
    mt5, svc, b = bot
    assert b.alerts() == []
    pos = open_trade(svc, mt5)
    assert b.alerts() == []
    risk = next(e for e in svc_events(svc) if e["event"] == "placed")["risk_money"]
    mt5.positions = []
    mt5.add_deal(entry=mt5.DEAL_ENTRY_OUT, position_id=pos, magic=MAGIC, profit=-risk, dtype=mt5.DEAL_TYPE_SELL, reason=mt5.DEAL_REASON_SL, price=4995.0, seconds_ago=5)
    mt5.add_deal(entry=mt5.DEAL_ENTRY_OUT, position_id=777, magic=0, profit=-250.0, dtype=mt5.DEAL_TYPE_SELL, seconds_ago=4)   # a big manual loss
    first = b.alerts()
    assert any("Closed" in a and "hit its stop-loss" in a and "-1.00R" in a for a in first)
    assert any("Loss budget is nearly used" in a for a in first)
    assert b.alerts() == []
