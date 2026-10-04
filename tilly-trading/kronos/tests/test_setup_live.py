"""setup_live.py: the signal tracker's rules (mirroring the backtest's one-
position / cooldown / daily-cap behavior), closed-bars-only evaluation, and
state persistence — all with an injected publisher, no Supabase or MT5."""
import pandas as pd
import pytest

from backtest.config import load_config
from conftest import make_synthetic_ohlc
from setup_live import ActiveSetup, TrackerState, evaluate, publish_decision, run_once, step
from setups.trend_pullback import TrendPullbackParams

CFG_PATH = "config/setup_xauusd.toml"
PARAMS = TrendPullbackParams()


def cfg(**risk_or_exec):
    c = load_config(CFG_PATH)
    for k, v in risk_or_exec.items():
        section, name = k.split("__")
        setattr(getattr(c, section), name, v)
    return c


def bar(minutes, *, high=100.0, low=90.0, close=95.0, buy=False, sell=False, sl=2.0, tp=4.0, day="2024-01-03"):
    t = pd.Timestamp(f"{day} 10:00", tz="UTC") + pd.Timedelta(minutes=minutes)
    return pd.Series(
        {
            "time": t, "high": high, "low": low, "close": close, "setup_buy": buy, "setup_sell": sell,
            "signal_sl_distance": sl if (buy or sell) else float("nan"),
            "signal_tp_distance": tp if (buy or sell) else float("nan"),
        }
    )


def test_quiet_bar_publishes_no_trade_and_holds_no_position():
    state = TrackerState()
    d = step(state, bar(0), cfg(), PARAMS)
    assert d.side == "NO_TRADE" and "No setup" in d.note and state.active is None


def test_buy_setup_publishes_levels_off_the_signal_close():
    state = TrackerState()
    d = step(state, bar(0, close=100.0, buy=True, sl=2.0, tp=4.0), cfg(), PARAMS)
    assert d.side == "BUY"
    assert (d.sl, d.tp) == (98.0, 104.0)
    assert d.expected_move == pytest.approx(4.0)  # +4% of 100
    assert state.active.side == "BUY" and state.signals_today == {"2024-01-03": 1}


def test_sell_setup_mirrors_the_levels_and_sign():
    d = step(TrackerState(), bar(0, close=100.0, sell=True, sl=2.0, tp=4.0), cfg(), PARAMS)
    assert (d.side, d.sl, d.tp) == ("SELL", 102.0, 96.0)
    assert d.expected_move == pytest.approx(-4.0)


def test_no_second_signal_while_one_is_still_active():
    state = TrackerState()
    step(state, bar(0, close=100.0, buy=True), cfg(), PARAMS)
    d = step(state, bar(15, high=101.0, low=99.0, close=100.5, buy=True), cfg(), PARAMS)  # touches neither 98 nor 104
    assert d.side == "NO_TRADE" and "still active" in d.note
    assert state.signals_today["2024-01-03"] == 1


def test_stop_ends_the_setup_then_cooldown_blocks_exactly_cooldown_bars():
    c = cfg()
    assert c.signal.cooldown_bars == 3
    state = TrackerState()
    step(state, bar(0, close=100.0, buy=True), c, PARAMS)
    d = step(state, bar(15, high=100.5, low=97.5), c, PARAMS)  # low pierces the 98 stop
    assert "resolved by SL" in d.note and state.active is None
    for i in (2, 3, 4):  # three blocked bars, even with the rules firing
        blocked = step(state, bar(15 * i, close=100.0, buy=True), c, PARAMS)
        assert blocked.side == "NO_TRADE" and "Cooling down" in blocked.note, i
    again = step(state, bar(15 * 5, close=100.0, buy=True), c, PARAMS)
    assert again.side == "BUY"


def test_target_ends_the_setup():
    state = TrackerState()
    step(state, bar(0, close=100.0, sell=True, sl=2.0, tp=4.0), cfg(), PARAMS)
    d = step(state, bar(15, high=99.0, low=95.5), cfg(), PARAMS)  # low reaches the 96 target
    assert "resolved by TP" in d.note and state.active is None


def test_one_bar_spanning_stop_and_target_counts_as_the_stop():
    state = TrackerState()
    step(state, bar(0, close=100.0, buy=True, sl=2.0, tp=4.0), cfg(), PARAMS)
    d = step(state, bar(15, high=105.0, low=97.0), cfg(), PARAMS)
    assert "resolved by SL" in d.note


def test_setup_times_out_after_max_holding_bars():
    c = cfg(execution__max_holding_bars=3)
    state = TrackerState()
    step(state, bar(0, close=100.0, buy=True), c, PARAMS)
    assert "still active" in step(state, bar(15, high=101, low=99), c, PARAMS).note
    assert "still active" in step(state, bar(30, high=101, low=99), c, PARAMS).note
    assert "time exit" in step(state, bar(45, high=101, low=99), c, PARAMS).note


def test_daily_signal_cap_blocks_and_resets_the_next_day():
    c = cfg(risk__max_trades_per_day=2, signal__cooldown_bars=0)
    state = TrackerState()
    for m in (0, 30):  # signal, resolve, signal, resolve — two signals taken
        assert step(state, bar(m, close=100.0, buy=True), c, PARAMS).side == "BUY"
        step(state, bar(m + 15, high=100.5, low=97.0), c, PARAMS)
    d = step(state, bar(60, close=100.0, buy=True), c, PARAMS)
    assert d.side == "NO_TRADE" and "Daily limit" in d.note
    assert step(state, bar(0, close=100.0, buy=True, day="2024-01-04"), c, PARAMS).side == "BUY"
    assert state.signals_today == {"2024-01-04": 1}


def test_state_round_trips_through_its_file(tmp_path):
    path = tmp_path / "state.json"
    state = TrackerState("2024-01-03T10:00:00+00:00", ActiveSetup("BUY", "2024-01-03T10:00:00+00:00", 98.0, 104.0, 2), 1, {"2024-01-03": 2})
    state.save(path)
    loaded = TrackerState.load(path)
    assert loaded == state
    assert TrackerState.load(tmp_path / "missing.json") == TrackerState()
    TrackerState().save(None)  # no path -> no-op, no crash


def test_publish_decision_labels_rule_based_rows_and_carries_levels():
    calls = []
    d = step(TrackerState(), bar(0, close=100.0, buy=True), cfg(), PARAMS)
    publish_decision(d, "XAUUSDm", "M15", lambda **kw: calls.append(kw))
    publish_decision(step(TrackerState(), bar(0), cfg(), PARAMS), "XAUUSDm", "M15", lambda **kw: calls.append(kw))
    entry, flat = calls
    assert entry["source"] == "setup" and entry["side"] == "BUY" and entry["confidence"] == 100.0
    assert (entry["sl"], entry["tp"], entry["timeframe"], entry["symbol"]) == (98.0, 104.0, "M15", "XAUUSDm")
    assert flat["side"] == "NO_TRADE" and flat["confidence"] == 0.0 and flat["sl"] is None and flat["source"] == "setup"


def _market(n=3000):
    base = make_synthetic_ohlc(n, freq="15min", start_price=4000.0, seed=5, spread_points=25.0)
    higher = (
        base.set_index("time").resample("1h")
        .agg({"open": "first", "high": "max", "low": "min", "close": "last", "tick_volume": "sum", "spread": "max"})
        .dropna().reset_index()
    )
    return base, higher


def test_evaluate_ignores_the_forming_bar():
    base, higher = _market()
    last_open = base["time"].iloc[-1]
    forming = evaluate(base, higher, PARAMS, 0.01, 15, 60, last_open + pd.Timedelta(minutes=5))
    closed = evaluate(base, higher, PARAMS, 0.01, 15, 60, last_open + pd.Timedelta(minutes=15))
    assert forming["time"] == base["time"].iloc[-2], "the 5-minutes-old bar is still forming and must not be used"
    assert closed["time"] == last_open


def test_evaluate_refuses_to_decide_on_too_little_history():
    base, higher = _market(n=200)
    with pytest.raises(RuntimeError, match="Not enough closed history"):
        evaluate(base, higher, PARAMS, 0.01, 15, 60, base["time"].iloc[-1] + pd.Timedelta(minutes=15))


def test_run_once_publishes_once_per_closed_bar():
    base, higher = _market()
    c = cfg()
    calls = []
    publish = lambda **kw: calls.append(kw)  # noqa: E731
    state = TrackerState()
    now = base["time"].iloc[-1] + pd.Timedelta(minutes=5)  # last bar still forming

    first = run_once(state, base, higher, c, PARAMS, 0.01, now, publish)
    assert first is not None and len(calls) == 1
    assert state.last_bar_time == base["time"].iloc[-2].isoformat()

    assert run_once(state, base, higher, c, PARAMS, 0.01, now + pd.Timedelta(minutes=2), publish) is None
    assert len(calls) == 1, "same closed bar, nothing new to publish"

    run_once(state, base, higher, c, PARAMS, 0.01, base["time"].iloc[-1] + pd.Timedelta(minutes=15), publish)
    assert len(calls) == 2 and state.last_bar_time == base["time"].iloc[-1].isoformat()
    assert all(call["source"] == "setup" and call["symbol"] == "XAUUSDm" and call["timeframe"] == "M15" for call in calls)
