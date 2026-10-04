"""Realistic MT5-style execution simulation (Phases 6, 7, 9, 12, 13).

Execution convention (documented per Phase 13, not left implicit):
  - A signal at bar T is computed from bar T's own close (features are
    already lookahead-safe as of that close).
  - With execution.next_bar=True (the default, and the only realistic
    option), the trade enters at bar T+1's OPEN, never bar T's own close —
    you cannot act on a candle's close the instant it prints.
  - Spread is charged once, at entry (crossing the bid/ask on a market
    order). TP/SL exits are modeled as resting orders triggered at their
    exact level plus slippage only — no second spread charge, matching how
    MT5 accounts for stop/limit exits. TIME_EXIT/END_OF_TEST exits are
    market-order closes, so they DO cross the spread again.
  - If both TP and SL are reachable within the same bar (only OHLC is
    available, not tick data), same_bar_exit_policy decides — "conservative"
    (default) assumes the stop loss happened first.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import costs
from .account import Account
from .config import BacktestConfig
from .position_sizing import calculate_position_size
from .signal_engine import decide_side
from .symbols import SymbolSpec

_trade_id_counter = itertools.count(1)


@dataclass
class Trade:
    trade_id: int
    symbol: str
    direction: str
    signal_time: pd.Timestamp
    entry_time: pd.Timestamp
    entry_price: float
    exit_time: pd.Timestamp
    exit_price: float
    lots: float
    stop_loss: float
    take_profit: float
    gross_pnl: float
    commission: float
    spread_cost: float
    slippage_cost: float
    net_pnl: float
    return_percent: float
    holding_time: pd.Timedelta
    exit_reason: str
    model_probability: float
    signal_threshold: float
    walk_forward_window: int


def _stop_loss_distance(cfg: BacktestConfig, spec: SymbolSpec) -> float:
    if cfg.stop_loss.type == "points":
        return cfg.stop_loss.value * spec.point
    if cfg.stop_loss.type == "price":
        return cfg.stop_loss.value
    raise ValueError(f"Unknown stop_loss.type {cfg.stop_loss.type!r}")


def _take_profit_distance(cfg: BacktestConfig, spec: SymbolSpec) -> float:
    if cfg.take_profit.type == "points":
        return cfg.take_profit.value * spec.point
    if cfg.take_profit.type == "price":
        return cfg.take_profit.value
    raise ValueError(f"Unknown take_profit.type {cfg.take_profit.type!r}")


def _resolve_same_bar(policy: str, rng: np.random.Generator) -> str:
    if policy == "conservative":
        return "SL"
    if policy == "optimistic":
        return "TP"
    if policy == "random":
        return "SL" if rng.random() < 0.5 else "TP"
    raise ValueError(f"Unknown same_bar_exit_policy {policy!r}")


def _daily_limit_hit(risk, account: Account, day_start_balance: float, trades_today: int) -> bool:
    if risk.max_trades_per_day and trades_today >= risk.max_trades_per_day:
        return True
    if risk.max_daily_loss_percent and day_start_balance > 0:
        lost = day_start_balance - account.balance
        if lost >= day_start_balance * risk.max_daily_loss_percent / 100.0:
            return True
    return False


def run_simulation(
    test_df: pd.DataFrame,
    cfg: BacktestConfig,
    spec: SymbolSpec,
    account: Account,
    window_index: int,
    seed: int | None = None,
) -> list[Trade]:
    """test_df must be sorted by time and carry columns: time, open, high,
    low, close, spread (MT5's own recorded spread column, in points — used
    only if cfg.spread.mode == "historical"), predicted_probability_buy,
    predicted_probability_sell — two independent probabilities, one per
    side's own trained model (see signal_engine.py's module docstring for
    why this must NOT be a single probability with a complementary
    threshold). Mutates `account` in place (realized balance + a
    mark-to-market point per bar) and returns the list of closed trades.

    Optional columns signal_sl_distance / signal_tp_distance (price units,
    read from the SIGNAL bar) override the config's fixed SL/TP for that one
    trade — how a rule-based setup supplies its own structural stop and
    risk:reward target. Position size then follows that trade's own SL.
    """
    required = {
        "time", "open", "high", "low", "close",
        "predicted_probability_buy", "predicted_probability_sell",
    }
    missing = required - set(test_df.columns)
    if missing:
        raise ValueError(f"test_df is missing required columns: {missing}")

    rng = np.random.default_rng(seed if seed is not None else cfg.random_seed)
    trades: list[Trade] = []
    n = len(test_df)
    rows = test_df.reset_index(drop=True)

    default_tp_distance = _take_profit_distance(cfg, spec)
    default_sl_distance = _stop_loss_distance(cfg, spec)
    has_signal_distances = {"signal_sl_distance", "signal_tp_distance"} <= set(rows.columns)

    i = 0
    cooldown_until = -1
    current_day = None
    day_start_balance, trades_today = account.balance, 0
    while i < n:
        bar = rows.iloc[i]
        prob_buy, prob_sell = bar["predicted_probability_buy"], bar["predicted_probability_sell"]

        bar_day = bar["time"].date()
        if bar_day != current_day:
            current_day, day_start_balance, trades_today = bar_day, account.balance, 0

        opened = False
        if (
            i > cooldown_until and pd.notna(prob_buy) and pd.notna(prob_sell)
            and not _daily_limit_hit(cfg.risk, account, day_start_balance, trades_today)
        ):
            side = decide_side(float(prob_buy), float(prob_sell), cfg.signal)
            if side != "NO_TRADE":
                probability = float(prob_buy) if side == "BUY" else float(prob_sell)
                entry_idx = i + 1 if cfg.execution.next_bar else i
                tp_distance, sl_distance = default_tp_distance, default_sl_distance
                if has_signal_distances:
                    sig_sl, sig_tp = bar["signal_sl_distance"], bar["signal_tp_distance"]
                    if pd.notna(sig_sl) and pd.notna(sig_tp) and sig_sl > 0 and sig_tp > 0:
                        sl_distance, tp_distance = float(sig_sl), float(sig_tp)
                if entry_idx < n:
                    opened = _open_and_scan(
                        rows, entry_idx, side, probability, bar["time"],
                        cfg, spec, account, rng, tp_distance, sl_distance,
                        window_index, trades,
                    )
                    if opened:
                        cooldown_until = opened + cfg.signal.cooldown_bars
                        trades_today += 1

        if not opened:
            account.mark(bar["time"], 0.0, 0)
            i += 1
        else:
            i = opened + 1

    return trades


def _open_and_scan(
    rows: pd.DataFrame,
    entry_idx: int,
    side: str,
    probability: float,
    signal_time: pd.Timestamp,
    cfg: BacktestConfig,
    spec: SymbolSpec,
    account: Account,
    rng: np.random.Generator,
    tp_distance: float,
    sl_distance: float,
    window_index: int,
    trades: list[Trade],
) -> int | None:
    """Opens a trade at rows.iloc[entry_idx]'s open, scans forward for its
    exit, records the trade and marks equity along the way. Returns the
    exit bar's index (so the caller resumes scanning for new signals right
    after it), or None if the position couldn't be sized (skipped, no
    trade opened, no bars consumed)."""
    entry_bar = rows.iloc[entry_idx]
    raw_entry_price = float(entry_bar["open"])

    spread_pts = costs.spread_points(
        cfg.spread, spec,
        float(entry_bar["spread"]) if "spread" in rows.columns and pd.notna(entry_bar.get("spread")) else None,
        raw_entry_price,
    )
    half_spread_price = spec.point * spread_pts / 2
    entry_slip = costs.slippage_points(cfg.slippage, rng)
    entry_price = costs.entry_price(side, raw_entry_price, spec, half_spread_price, entry_slip)

    lots = calculate_position_size(cfg.risk, spec, account.balance, sl_distance)
    if lots <= 0:
        return None  # can't express this risk at or above the symbol's minimum lot — skip, don't force it

    if side == "BUY":
        tp_price, sl_price = entry_price + tp_distance, entry_price - sl_distance
    else:
        tp_price, sl_price = entry_price - tp_distance, entry_price + sl_distance

    horizon_end = min(entry_idx + cfg.execution.max_holding_bars, len(rows))
    exit_idx, exit_price_raw, exit_reason, crosses_spread = None, None, None, False

    for j in range(entry_idx, horizon_end):
        b = rows.iloc[j]
        high, low = float(b["high"]), float(b["low"])
        hit_tp = high >= tp_price if side == "BUY" else low <= tp_price
        hit_sl = low <= sl_price if side == "BUY" else high >= sl_price

        if hit_tp and hit_sl:
            outcome = _resolve_same_bar(cfg.execution.same_bar_exit_policy, rng)
            exit_idx, exit_price_raw = j, (tp_price if outcome == "TP" else sl_price)
            exit_reason = "TP" if outcome == "TP" else "SL"
        elif hit_tp:
            exit_idx, exit_price_raw, exit_reason = j, tp_price, "TP"
        elif hit_sl:
            exit_idx, exit_price_raw, exit_reason = j, sl_price, "SL"

        if exit_idx is not None:
            break

        unrealized = _unrealized_pnl(side, entry_price, float(b["close"]), lots, spec)
        account.mark(b["time"], unrealized, 1)

    if exit_idx is None:
        # Neither TP nor SL hit within max_holding_bars.
        last_idx = horizon_end - 1
        exit_idx = last_idx
        exit_price_raw = float(rows.iloc[last_idx]["close"])
        exit_reason = "END_OF_TEST" if horizon_end == len(rows) else "TIME_EXIT"
        crosses_spread = True  # a market-order close, not a triggered stop/limit

    exit_slip = costs.slippage_points(cfg.slippage, rng)
    if crosses_spread:
        exit_bar = rows.iloc[exit_idx]
        exit_spread_pts = costs.spread_points(
            cfg.spread, spec,
            float(exit_bar["spread"]) if "spread" in rows.columns and pd.notna(exit_bar.get("spread")) else None,
            exit_price_raw,
        )
        half_spread_exit = spec.point * exit_spread_pts / 2
    else:
        half_spread_exit = 0.0  # TP/SL trigger fills at its level, only slippage applies
    final_exit_price = costs.exit_price(side, exit_price_raw, spec, half_spread_exit, exit_slip)

    direction_sign = 1 if side == "BUY" else -1
    gross_pnl = (final_exit_price - entry_price) * spec.contract_size * lots * direction_sign
    notional = entry_price * spec.contract_size * lots
    commission = costs.commission_cost(cfg.commission, lots, notional)
    spread_cost = half_spread_price * spec.contract_size * lots + half_spread_exit * spec.contract_size * lots
    slippage_cost = (entry_slip + exit_slip) * spec.point * spec.contract_size * lots
    net_pnl = gross_pnl - commission

    account.realize(net_pnl)
    exit_time = rows.iloc[exit_idx]["time"]
    account.mark(exit_time, 0.0, 0)

    trades.append(
        Trade(
            trade_id=next(_trade_id_counter),
            symbol=spec.symbol,
            direction=side,
            signal_time=signal_time,
            entry_time=entry_bar["time"],
            entry_price=entry_price,
            exit_time=exit_time,
            exit_price=final_exit_price,
            lots=lots,
            stop_loss=sl_price,
            take_profit=tp_price,
            gross_pnl=gross_pnl,
            commission=commission,
            spread_cost=spread_cost,
            slippage_cost=slippage_cost,
            net_pnl=net_pnl,
            return_percent=(net_pnl / account.initial_balance) * 100.0,
            holding_time=exit_time - entry_bar["time"],
            exit_reason=exit_reason,
            model_probability=probability,
            signal_threshold=cfg.signal.buy_threshold if side == "BUY" else cfg.signal.sell_threshold,
            walk_forward_window=window_index,
        )
    )
    return exit_idx


def _unrealized_pnl(side: str, entry_price: float, mark_price: float, lots: float, spec: SymbolSpec) -> float:
    direction_sign = 1 if side == "BUY" else -1
    return (mark_price - entry_price) * spec.contract_size * lots * direction_sign


def trades_to_frame(trades: list[Trade]) -> pd.DataFrame:
    return pd.DataFrame([vars(t) for t in trades])
