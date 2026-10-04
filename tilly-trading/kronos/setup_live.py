"""Live runner for setups/trend_pullback.py: on every newly CLOSED bar, apply
the exact rules the backtest tested and publish BUY / SELL / NO_TRADE to
Supabase's `signals` table (source="setup") with the stop and target prices.

INFORMATIONAL ONLY — it places no orders. A BUY/SELL row is "the rules fired
on the bar that just closed"; entry would be at the next bar's open, with the
stop/target DISTANCES given in the note (they apply from your actual fill).
Trading it is a separate, deliberate step that belongs after the backtest
verdict and a demo period, not before.

What mirrors the backtest, so live behavior matches what was measured:
  - only closed bars are used (bars.closed_bars_only) — never a forming candle
  - one hypothetical position at a time: after a signal, no new one until
    price hits that signal's SL/TP (checked bar by bar, SL first if one bar
    spans both) or max_holding_bars passes, then `cooldown_bars` more
  - max_trades_per_day signals per UTC day

State (the hypothetical open setup, today's count, cooldown) lives in
memory and in --state-file so a restart doesn't forget an active signal. It
does not replay history: a fresh start begins flat.

Session hours in [setup] are in BROKER SERVER time (that is the clock MT5
stamps on bars). Exness servers run on UTC; the startup line prints both
clocks so you can confirm yours does.

    python setup_live.py --config config/setup_xauusd.toml --symbol XAUUSDm
    python setup_live.py --config config/setup_xauusd.toml --symbol XAUUSD      # real account
"""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import pandas as pd

from backtest.config import BacktestConfig, load_config
from backtest.symbols import get_symbol_spec
from backtest.timeframes import TIMEFRAME_MINUTES
from bars import closed_bars_only
from features import compute_features, merge_higher_timeframe
from setups.trend_pullback import TrendPullbackParams, generate_signals, load_setup_params

BASE_BARS = 600
HIGHER_BARS = 300
MIN_BASE_BARS, MIN_HIGHER_BARS = 300, 120  # EMA/ATR warmup and the higher timeframe's swings


@dataclass
class ActiveSetup:
    side: str
    signal_time: str
    sl_price: float
    tp_price: float
    bars_held: int = 0


@dataclass
class TrackerState:
    last_bar_time: str | None = None
    active: ActiveSetup | None = None
    cooldown_remaining: int = 0
    signals_today: dict = field(default_factory=dict)  # {"YYYY-MM-DD": count}, only the current day is kept

    @classmethod
    def load(cls, path: str | Path | None) -> "TrackerState":
        if not path or not Path(path).exists():
            return cls()
        raw = json.loads(Path(path).read_text())
        active = ActiveSetup(**raw["active"]) if raw.get("active") else None
        return cls(raw.get("last_bar_time"), active, raw.get("cooldown_remaining", 0), raw.get("signals_today", {}))

    def save(self, path: str | Path | None) -> None:
        if path:
            Path(path).write_text(json.dumps(asdict(self), indent=2))


@dataclass
class Decision:
    side: str  # BUY | SELL | NO_TRADE
    note: str
    sl: float | None = None
    tp: float | None = None
    expected_move: float | None = None


def evaluate(
    base_raw: pd.DataFrame,
    higher_raw: pd.DataFrame,
    params: TrendPullbackParams,
    point: float,
    base_minutes: int,
    higher_minutes: int,
    now: pd.Timestamp,
) -> pd.Series:
    """The signal-frame row for the most recent CLOSED base bar."""
    base = closed_bars_only(base_raw, base_minutes, now)
    higher = closed_bars_only(higher_raw, higher_minutes, now)
    if len(base) < MIN_BASE_BARS or len(higher) < MIN_HIGHER_BARS:
        raise RuntimeError(
            f"Not enough closed history yet (base {len(base)}/{MIN_BASE_BARS}, higher {len(higher)}/{MIN_HIGHER_BARS})."
        )
    merged = merge_higher_timeframe(
        compute_features(base), compute_features(higher), prefix=params.higher_prefix
    )
    return generate_signals(merged.reset_index(drop=True), params, point).iloc[-1]


def step(
    state: TrackerState,
    bar: pd.Series,
    cfg: BacktestConfig,
    params: TrendPullbackParams,
) -> Decision:
    """Advance the tracker by ONE newly closed bar and decide what to publish."""
    bar_time = pd.Timestamp(bar["time"])
    day = str(bar_time.date())
    state.signals_today = {day: state.signals_today.get(day, 0)}
    state.last_bar_time = bar_time.isoformat()

    if state.active is not None:
        a = state.active
        a.bars_held += 1
        is_buy = a.side == "BUY"
        hit_sl = bar["low"] <= a.sl_price if is_buy else bar["high"] >= a.sl_price
        hit_tp = bar["high"] >= a.tp_price if is_buy else bar["low"] <= a.tp_price
        outcome = "SL" if hit_sl else "TP" if hit_tp else None  # SL first when one bar spans both, like the backtest
        if outcome is None and a.bars_held >= cfg.execution.max_holding_bars:
            outcome = "time exit"
        if outcome is None:
            return Decision("NO_TRADE", f"{a.side} setup from {a.signal_time} still active (bar {a.bars_held}) — no new signals until it resolves.")
        state.active = None
        state.cooldown_remaining = cfg.signal.cooldown_bars
        return Decision("NO_TRADE", f"Previous {a.side} setup resolved by {outcome}.")

    if state.cooldown_remaining > 0:
        state.cooldown_remaining -= 1
        return Decision("NO_TRADE", f"Cooling down after the last setup ({state.cooldown_remaining + 1} bar(s) left).")

    limit = cfg.risk.max_trades_per_day
    if limit and state.signals_today[day] >= limit:
        return Decision("NO_TRADE", f"Daily limit reached ({limit} signals today).")

    if not (bar["setup_buy"] or bar["setup_sell"]):
        return Decision("NO_TRADE", f"No setup on the {bar_time:%H:%M} bar.")

    side = "BUY" if bar["setup_buy"] else "SELL"
    close = float(bar["close"])
    sl_dist, tp_dist = float(bar["signal_sl_distance"]), float(bar["signal_tp_distance"])
    sign = 1 if side == "BUY" else -1
    sl_price, tp_price = close - sign * sl_dist, close + sign * tp_dist
    state.active = ActiveSetup(side, bar_time.isoformat(), sl_price, tp_price)
    state.signals_today[day] += 1
    return Decision(
        side,
        f"Trend-pullback {side}, enter at the next bar's open. Stop {sl_dist:.2f} / target {tp_dist:.2f} "
        f"({params.rr:g}R) from your fill; levels shown are off the signal close {close:.2f}. "
        f"Rule-based, no probability behind it. Signal {state.signals_today[day]}/{limit or 'unlimited'} today.",
        sl=round(sl_price, 5), tp=round(tp_price, 5),
        expected_move=round(sign * tp_dist / close * 100, 3),
    )


def publish_decision(decision: Decision, symbol: str, timeframe: str, publish: Callable[..., None]) -> None:
    publish(
        symbol=symbol, side=decision.side,
        # No probability exists for a rule — 100 = "rules satisfied" on an entry, 0 otherwise.
        # The Signals page shows RULES instead of CONF for source="setup".
        confidence=100.0 if decision.side != "NO_TRADE" else 0.0,
        timeframe=timeframe, tp=decision.tp, sl=decision.sl,
        expected_move=decision.expected_move, note=decision.note, source="setup",
    )


def run_once(
    state: TrackerState,
    base_raw: pd.DataFrame,
    higher_raw: pd.DataFrame,
    cfg: BacktestConfig,
    params: TrendPullbackParams,
    point: float,
    now: pd.Timestamp,
    publish: Callable[..., None],
) -> Decision | None:
    """One poll. Returns the published Decision, or None if no new bar has closed since the last one."""
    bar = evaluate(
        base_raw, higher_raw, params, point,
        TIMEFRAME_MINUTES[cfg.timeframe.upper()], TIMEFRAME_MINUTES[cfg.higher_timeframe.upper()], now,
    )
    if state.last_bar_time is not None and pd.Timestamp(bar["time"]) <= pd.Timestamp(state.last_bar_time):
        return None
    decision = step(state, bar, cfg, params)
    publish_decision(decision, cfg.symbol, cfg.timeframe, publish)
    return decision


def run_loop(cfg: BacktestConfig, params: TrendPullbackParams, poll_seconds: int, state_file: str | None) -> None:
    from mt5_data import connect, disconnect, download_history, server_time_now
    from publish_signal import publish_signal

    point = get_symbol_spec(cfg.symbol).point
    state = TrackerState.load(state_file)
    connect()
    try:
        print(
            f"{cfg.symbol} {cfg.timeframe}+{cfg.higher_timeframe} — broker server time {server_time_now(cfg.symbol)} "
            f"vs PC UTC {datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S} (session hours are in server time)"
        )
        while True:
            try:
                now = server_time_now(cfg.symbol)
                base_raw = download_history(cfg.symbol, cfg.timeframe, BASE_BARS)
                higher_raw = download_history(cfg.symbol, cfg.higher_timeframe, HIGHER_BARS)
                decision = run_once(state, base_raw, higher_raw, cfg, params, point, now, publish_signal)
                if decision is not None:
                    state.save(state_file)
                    print(f"Published {decision.side}: {decision.note}")
            except Exception as exc:  # noqa: BLE001 - one bad cycle shouldn't kill the loop
                print(f"Cycle failed: {exc}")
            time.sleep(poll_seconds)
    finally:
        disconnect()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default="config/setup_xauusd.toml")
    parser.add_argument("--symbol", default=None, help="XAUUSDm (demo/mini) or XAUUSD (real account).")
    parser.add_argument("--poll-seconds", type=int, default=30)
    parser.add_argument("--state-file", default="setup_state.json")
    args = parser.parse_args()

    cfg = load_config(args.config)
    if args.symbol:
        cfg.symbol = args.symbol
    if not cfg.higher_timeframe:
        raise SystemExit("The setup needs a higher_timeframe in the config.")
    run_loop(cfg, load_setup_params(args.config), args.poll_seconds, args.state_file)


if __name__ == "__main__":
    main()
