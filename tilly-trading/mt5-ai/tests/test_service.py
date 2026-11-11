"""The broker wrapper and the whole order flow against a fake terminal."""
import json

import pytest

from fake_mt5 import FakeMT5
from mt5_ai.broker import BrokerError, Mt5Broker
from mt5_ai.config import Settings
from mt5_ai.service import Mt5Service
from mt5_ai.tickets import TicketStore

MAGIC = Settings().magic


@pytest.fixture
def mt5():
    return FakeMT5()


def make(mt5, tmp_path, **overrides):
    settings = Settings(state_dir=tmp_path, **overrides)
    clock = {"t": 1000.0}
    svc = Mt5Service(Mt5Broker(mt5), settings, clock=lambda: clock["t"])
    svc.clock = clock
    return svc


def prepare(svc, **kw):
    args = dict(symbol="XAUUSD", side="BUY", sl=4995.0, tp=5010.0)
    args.update(kw)
    return svc.prepare_trade(**args)


# --- broker wrapper -----------------------------------------------------------
def test_rates_skip_the_forming_bar_and_return_closed_bars_oldest_first(mt5):
    df = Mt5Broker(mt5).rates("XAUUSD", "M15", 50)
    assert mt5.rates_calls[0][2] == 1, "start_pos must be 1: bar 0 is the still-forming candle"
    assert len(df) == 50 and df["time"].is_monotonic_increasing
    forming_open = mt5.now // 900 * 900
    assert df["time"].iloc[-1].timestamp() == forming_open - 900


def test_rates_chunk_large_requests(mt5):
    df = Mt5Broker(mt5).rates("XAUUSD", "M5", 5000)
    assert len(df) == 5000 and len(mt5.rates_calls) == 1
    assert Mt5Broker(mt5).rates("XAUUSD", "M5", 5000)["time"].is_unique


def test_bad_inputs_raise_readable_errors(mt5):
    b = Mt5Broker(mt5)
    with pytest.raises(BrokerError, match="timeframe"):
        b.rates("XAUUSD", "M7", 10)
    with pytest.raises(BrokerError, match="count"):
        b.rates("XAUUSD", "M15", 0)
    with pytest.raises(BrokerError, match="Unknown symbol"):
        b.spec("NOPE")


@pytest.mark.parametrize("flags, expected", [(2, FakeMT5.ORDER_FILLING_IOC), (3, FakeMT5.ORDER_FILLING_IOC),
                                             (1, FakeMT5.ORDER_FILLING_FOK), (0, FakeMT5.ORDER_FILLING_RETURN)])
def test_filling_mode_follows_what_the_symbol_supports(mt5, flags, expected):
    mt5.filling_flags = flags
    assert Mt5Broker(mt5).filling_mode("XAUUSD") == expected


def test_today_sums_every_strategy_but_counts_only_our_entries(mt5):
    mt5.add_deal(entry=mt5.DEAL_ENTRY_OUT, profit=-120.0, magic=0)            # a GRID bot's loss
    mt5.add_deal(entry=mt5.DEAL_ENTRY_OUT, profit=50.0, commission=-1.0, magic=MAGIC)
    mt5.add_deal(entry=mt5.DEAL_ENTRY_IN, magic=MAGIC)
    mt5.add_deal(entry=mt5.DEAL_ENTRY_IN, magic=0)                            # not ours
    mt5.add_deal(entry=mt5.DEAL_ENTRY_OUT, profit=-999.0, seconds_ago=3 * 86400)  # not today
    mt5.add_deal(entry=mt5.DEAL_ENTRY_OUT, profit=5000.0, dtype=mt5.DEAL_TYPE_BALANCE)  # a deposit, not P&L
    t = Mt5Broker(mt5).today("XAUUSD", MAGIC)
    assert t["realized"] == pytest.approx(-71.0) and t["trades_ours"] == 1


def test_account_flags_demo_and_real(mt5):
    b = Mt5Broker(mt5)
    assert b.account()["is_demo"] and b.account()["mode"] == "DEMO"
    mt5.account_trade_mode = mt5.ACCOUNT_TRADE_MODE_REAL
    assert not b.account()["is_demo"] and b.account()["mode"] == "REAL"


# --- prepare ------------------------------------------------------------------
def test_a_good_trade_passes_and_issues_a_ticket_without_sending_anything(mt5, tmp_path):
    r = prepare(make(mt5, tmp_path))
    assert r["verdict"] == "PASS" and r["ticket_id"]
    assert "BUY 0.19 lots XAUUSD" in r["ticket"] and "stop-loss 4995.00" in r["ticket"]
    assert mt5.sent == [], "preparing must never send an order"
    assert len(mt5.checked) == 1, "but it does run the broker's own pre-flight"
    assert any(c["name"] == "broker_preflight" and c["passed"] for c in r["checks"])


def test_block_lists_every_reason_and_issues_no_ticket(mt5, tmp_path):
    mt5.account_trade_mode = mt5.ACCOUNT_TRADE_MODE_REAL
    r = prepare(make(mt5, tmp_path), sl=5001.0)
    assert r["verdict"] == "BLOCK" and "ticket_id" not in r
    joined = " ".join(r["reasons"])
    assert "REAL-money" in joined and "stop-loss" in joined.lower()


def test_real_account_needs_the_person_to_enable_it(mt5, tmp_path):
    mt5.account_trade_mode = mt5.ACCOUNT_TRADE_MODE_REAL
    assert prepare(make(mt5, tmp_path))["verdict"] == "BLOCK"
    assert prepare(make(mt5, tmp_path, allow_live=True))["verdict"] == "PASS"


def test_broker_preflight_failure_blocks(mt5, tmp_path):
    mt5.check_retcode = 10018
    r = prepare(make(mt5, tmp_path))
    assert r["verdict"] == "BLOCK" and "Market closed" in " ".join(r["reasons"])


def test_daily_limits_come_from_real_history(mt5, tmp_path):
    for _ in range(3):
        mt5.add_deal(entry=mt5.DEAL_ENTRY_IN, magic=MAGIC)
    assert "trades" in " ".join(prepare(make(mt5, tmp_path))["reasons"])

    mt5.deals.clear()
    mt5.balance = mt5.equity = 9_700.0
    mt5.add_deal(entry=mt5.DEAL_ENTRY_OUT, profit=-300.0)  # a GRID bot's losses count too
    assert "daily loss" in " ".join(prepare(make(mt5, tmp_path))["reasons"]).lower()


def test_an_existing_position_of_ours_blocks_a_second_one(mt5, tmp_path):
    mt5.add_position()
    assert "positions" in " ".join(prepare(make(mt5, tmp_path))["reasons"])
    mt5.positions.clear()
    mt5.add_position(magic=0)  # another strategy's position does not use up our slot
    assert prepare(make(mt5, tmp_path))["verdict"] == "PASS"


# --- place ----------------------------------------------------------------------
def test_placing_a_ticket_sends_exactly_what_was_shown(mt5, tmp_path):
    svc = make(mt5, tmp_path)
    t = prepare(svc)
    r = svc.place_prepared_trade(t["ticket_id"])
    assert r["placed"] and r["lots"] == pytest.approx(0.19) and r["position_ticket"]
    req = mt5.sent[0]
    assert (req["type"], req["volume"], req["sl"], req["tp"], req["magic"]) == (mt5.ORDER_TYPE_BUY, 0.19, 4995.0, 5010.0, MAGIC)
    assert req["price"] == 5000.25 and req["type_filling"] == mt5.ORDER_FILLING_IOC
    assert len(mt5.positions) == 1 and mt5.positions[0].magic == MAGIC


def test_a_short_sells_at_the_bid(mt5, tmp_path):
    svc = make(mt5, tmp_path)
    t = prepare(svc, side="SELL", sl=5005.0, tp=4990.0)
    assert t["verdict"] == "PASS"
    svc.place_prepared_trade(t["ticket_id"])
    assert (mt5.sent[0]["type"], mt5.sent[0]["price"]) == (mt5.ORDER_TYPE_SELL, 5000.00)


def test_a_ticket_is_single_use(mt5, tmp_path):
    svc = make(mt5, tmp_path)
    tid = prepare(svc)["ticket_id"]
    assert svc.place_prepared_trade(tid)["placed"]
    again = svc.place_prepared_trade(tid)
    assert not again["placed"] and "already used" in again["error"] and len(mt5.sent) == 1


def test_unknown_and_expired_tickets_send_nothing(mt5, tmp_path):
    svc = make(mt5, tmp_path)
    assert not svc.place_prepared_trade("BOGUS")["placed"]
    tid = prepare(svc)["ticket_id"]
    svc.tickets._clock = lambda: 10_000.0  # well past the 300s validity
    assert not svc.place_prepared_trade(tid)["placed"] and mt5.sent == []


def test_price_drift_since_the_ticket_cancels_it(mt5, tmp_path):
    svc = make(mt5, tmp_path)
    tid = prepare(svc)["ticket_id"]
    mt5.bid, mt5.ask = 5003.0, 5003.25   # moved 3.0 against a 5.25 stop; limit is 25% = 1.31
    r = svc.place_prepared_trade(tid)
    assert not r["placed"] and "moved" in r["error"] and mt5.sent == []
    assert not svc.place_prepared_trade(tid)["placed"], "a refused ticket is still spent"


def test_conditions_are_rechecked_at_placement(mt5, tmp_path):
    svc = make(mt5, tmp_path)
    tid = prepare(svc)["ticket_id"]
    mt5.account_trade_mode = mt5.ACCOUNT_TRADE_MODE_REAL   # account switched between prepare and place
    r = svc.place_prepared_trade(tid)
    assert not r["placed"] and "REAL-money" in r["error"] and mt5.sent == []


def test_a_shrunk_risk_budget_cancels_the_ticket(mt5, tmp_path):
    svc = make(mt5, tmp_path)
    tid = prepare(svc)["ticket_id"]
    mt5.balance = mt5.equity = 5_000.0   # half the account is gone: 0.19 lots is now too big
    r = svc.place_prepared_trade(tid)
    assert not r["placed"] and "shrank" in r["error"] and mt5.sent == []


def test_a_broker_rejection_is_reported_and_not_retried(mt5, tmp_path):
    svc = make(mt5, tmp_path)
    tid = prepare(svc)["ticket_id"]
    mt5.send_retcode = 10004
    r = svc.place_prepared_trade(tid)
    assert not r["placed"] and "Requote" in r["error"] and len(mt5.sent) == 1
    assert not svc.place_prepared_trade(tid)["placed"] and len(mt5.sent) == 1


def test_every_step_is_written_to_the_audit_log(mt5, tmp_path):
    svc = make(mt5, tmp_path)
    svc.place_prepared_trade(prepare(svc)["ticket_id"])
    prepare(svc, sl=5001.0)
    events = [json.loads(line)["event"] for line in (tmp_path / "trades.jsonl").read_text().splitlines()]
    assert events == ["prepared", "placed", "blocked"]


# --- managing positions -----------------------------------------------------------
def test_stop_can_be_tightened_but_never_widened(mt5, tmp_path):
    svc = make(mt5, tmp_path)
    p = mt5.add_position(side="BUY", sl=4995.0, tp=5010.0)
    assert not svc.move_stop(p.ticket, 4990.0)["moved"]            # widening a long's stop
    assert svc.move_stop(p.ticket, 4999.0)["moved"] and mt5.positions[0].sl == 4999.0
    assert mt5.positions[0].tp == 5010.0, "tp is kept when not given"
    assert not svc.move_stop(p.ticket, 5001.0)["moved"]            # through the current bid of 5000


def test_short_stop_moves_the_other_way(mt5, tmp_path):
    svc = make(mt5, tmp_path)
    p = mt5.add_position(side="SELL", sl=5005.0, tp=4990.0)
    assert not svc.move_stop(p.ticket, 5009.0)["moved"]
    assert svc.move_stop(p.ticket, 5002.0)["moved"]


def test_tools_refuse_positions_this_server_did_not_open(mt5, tmp_path):
    svc = make(mt5, tmp_path)
    other = mt5.add_position(magic=0)
    with pytest.raises(ValueError, match="not opened by this server"):
        svc.close_position(other.ticket)
    with pytest.raises(ValueError, match="not opened by this server"):
        svc.move_stop(other.ticket, 4999.0)
    with pytest.raises(ValueError, match="No open position"):
        svc.close_position(1)


def test_close_position_sends_the_opposite_deal(mt5, tmp_path):
    svc = make(mt5, tmp_path)
    p = mt5.add_position(side="BUY")
    assert svc.close_position(p.ticket)["closed"]
    req = mt5.sent[0]
    assert (req["type"], req["position"], req["price"]) == (mt5.ORDER_TYPE_SELL, p.ticket, 5000.00)
    assert mt5.positions == []


# --- read-only tools ------------------------------------------------------------------
def test_account_overview_masks_the_login_and_shows_limits(mt5, tmp_path):
    o = make(mt5, tmp_path).account_overview()
    assert o["account"] == "***789" and "123456789" not in json.dumps(o)
    assert o["mode"] == "DEMO" and o["orders_allowed_by_this_server"] is True and o["limits"]["max_risk_pct"] == 1.0


def test_todays_summary_reports_budget_left(mt5, tmp_path):
    mt5.add_deal(entry=mt5.DEAL_ENTRY_OUT, profit=-100.0)
    mt5.add_deal(entry=mt5.DEAL_ENTRY_IN, magic=MAGIC)
    mt5.balance = mt5.equity = 9_900.0
    s = make(mt5, tmp_path).todays_summary("XAUUSD")
    assert s["realized_pnl_all_strategies"] == -100.0 and s["daily_loss_limit"] == -300.0
    assert s["loss_budget_left"] == 200.0 and s["trades_left_today"] == 2


def test_candles_come_back_compact_and_closed_only(mt5, tmp_path):
    c = make(mt5, tmp_path).get_candles("XAUUSD", "M15", 5)
    assert c["closed_bars_only"] and len(c["rows"]) == 5 and c["columns"][0] == "time"


def test_analysis_tools_say_so_when_not_configured(mt5, tmp_path):
    svc = make(mt5, tmp_path)
    assert "not configured" in svc.kronos_forecast("XAUUSD")["error"]
    assert "not configured" in svc.rule_setup_status("XAUUSD")["error"]


def test_simulate_trade_plan_uses_live_price_and_spread(mt5, tmp_path):
    r = make(mt5, tmp_path).simulate_trade_plan("XAUUSD", "BUY", 4995.0, 5010.0, history_bars=500, simulations=500)
    assert r["entry"] == 5000.25 and r["side"] == "BUY"
    assert r["p_target_first"] + r["p_stop_first"] + r["p_neither"] == pytest.approx(1.0)


# --- kill switch -------------------------------------------------------------------
def test_halting_blocks_new_entries_and_only_the_person_can_resume(mt5, tmp_path):
    svc = make(mt5, tmp_path)
    tid = prepare(svc)["ticket_id"]
    r = svc.halt_trading("looks wrong")
    assert r["halted"] and (tmp_path / "HALT").read_text() == "looks wrong"
    assert svc.account_overview()["halted"] is True and svc.account_overview()["orders_allowed_by_this_server"] is False
    blocked = prepare(svc)
    assert blocked["verdict"] == "BLOCK" and "HALTED" in blocked["reasons"][0]
    placed = svc.place_prepared_trade(tid)          # even a ticket prepared BEFORE the halt is refused
    assert not placed["placed"] and "HALTED" in placed["error"] and mt5.sent == []
    (tmp_path / "HALT").unlink()                     # the person resumes
    assert prepare(svc)["verdict"] == "PASS"


def test_halting_does_not_stop_closing_or_tightening_open_positions(mt5, tmp_path):
    svc = make(mt5, tmp_path)
    p = mt5.add_position(side="BUY", sl=4995.0)
    svc.halt_trading()
    assert svc.move_stop(p.ticket, 4999.0)["moved"] and svc.close_position(p.ticket)["closed"]
