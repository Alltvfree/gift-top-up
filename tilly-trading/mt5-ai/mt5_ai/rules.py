"""Position sizing and the PASS/BLOCK rules a trade must clear — pure
functions, no MetaTrader5 import, fully unit-tested. Every check is always
evaluated (no short-circuit) so the person sees every reason, not just the
first. Modeled on day-trader-skill's trader-budget + trader-risk split."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from fnmatch import fnmatchcase

from .config import Settings


@dataclass(frozen=True)
class SymbolSpec:
    symbol: str
    digits: int
    point: float
    volume_min: float
    volume_max: float
    volume_step: float
    tick_size: float
    tick_value_loss: float   # account-currency loss for a 1-tick adverse move on 1.0 lot
    contract_size: float
    stops_level_points: int  # broker's minimum stop distance
    trade_allowed: bool


@dataclass(frozen=True)
class AccountContext:
    is_demo: bool
    balance: float
    equity: float
    realized_today: float        # account-wide realized P&L today, ALL strategies (a GRID bot's losses count)
    trades_today_ours: int       # entries this server's magic number opened today
    open_positions_ours: int


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str


@dataclass
class Evaluation:
    checks: list[Check] = field(default_factory=list)
    lots: float = 0.0
    risk_money: float = 0.0
    rr: float = 0.0
    sl_distance: float = 0.0
    tp_distance: float = 0.0

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(c.passed for c in self.checks)

    @property
    def failures(self) -> list[Check]:
        return [c for c in self.checks if not c.passed]


def symbol_allowed(symbol: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatchcase(symbol.upper(), p.upper()) for p in patterns)


def value_per_price_unit_per_lot(spec: SymbolSpec) -> float:
    return spec.tick_value_loss / spec.tick_size if spec.tick_size else 0.0


def calc_lots(risk_money: float, sl_distance: float, spec: SymbolSpec) -> float:
    """Largest lot size, rounded DOWN to the volume step, whose loss at the
    stop does not exceed risk_money. 0.0 when even the minimum lot would risk
    more than asked — the trade is then skipped, never forced up."""
    per_unit = value_per_price_unit_per_lot(spec)
    if risk_money <= 0 or sl_distance <= 0 or per_unit <= 0:
        return 0.0
    raw = risk_money / (sl_distance * per_unit)
    steps = math.floor(raw / spec.volume_step + 1e-9)
    lots = round(steps * spec.volume_step, 8)
    lots = min(lots, spec.volume_max)
    return lots if lots >= spec.volume_min else 0.0


def loss_at_stop(lots: float, sl_distance: float, spec: SymbolSpec) -> float:
    return lots * sl_distance * value_per_price_unit_per_lot(spec)


def evaluate_order(
    *,
    side: str,
    entry: float,
    sl: float | None,
    tp: float | None,
    risk_pct: float,
    spread_price: float,
    spec: SymbolSpec,
    account: AccountContext,
    settings: Settings,
) -> Evaluation:
    """entry is the reference fill: the ask for a BUY, the bid for a SELL."""
    ev = Evaluation()
    add = lambda name, ok, detail: ev.checks.append(Check(name, bool(ok), detail))  # noqa: E731
    side = side.upper()

    add(
        "demo_account",
        account.is_demo or settings.allow_live,
        "Demo account." if account.is_demo
        else ("REAL-money account, allowed because MT5_AI_ALLOW_LIVE is on." if settings.allow_live
              else "This is a REAL-money account and MT5_AI_ALLOW_LIVE is off. Only the person can turn it on."),
    )
    add("symbol_allowed", symbol_allowed(spec.symbol, settings.symbols),
        f"{spec.symbol} vs allowed {list(settings.symbols)}.")
    add("symbol_tradable", spec.trade_allowed, "Broker allows trading this symbol." if spec.trade_allowed
        else f"{spec.symbol} is not tradable right now (market closed or trading disabled).")

    if side not in ("BUY", "SELL"):
        add("side", False, f"side must be BUY or SELL, got {side!r}.")
        return ev

    sl_ok = sl is not None and ((sl < entry) if side == "BUY" else (sl > entry))
    tp_ok = tp is not None and ((tp > entry) if side == "BUY" else (tp < entry))
    add("stop_loss", sl_ok, "Stop-loss is on the losing side of entry." if sl_ok
        else f"A stop-loss is required and must be {'below' if side == 'BUY' else 'above'} the entry {entry}.")
    add("take_profit", tp_ok, "Take-profit is on the winning side of entry." if tp_ok
        else f"A take-profit is required and must be {'above' if side == 'BUY' else 'below'} the entry {entry}.")
    if not (sl_ok and tp_ok):
        return ev

    ev.sl_distance, ev.tp_distance = abs(entry - sl), abs(tp - entry)
    ev.rr = ev.tp_distance / ev.sl_distance
    min_stop = spec.stops_level_points * spec.point
    add("min_stop_distance", ev.sl_distance >= min_stop,
        f"Stop is {ev.sl_distance:.{spec.digits}f} away; the broker needs at least {min_stop:.{spec.digits}f}.")
    add("risk_pct", 0 < risk_pct <= settings.max_risk_pct,
        f"Risk {risk_pct:g}% of the account vs your {settings.max_risk_pct:g}% limit.")
    add("reward_risk", ev.rr >= settings.min_rr, f"Reward:risk {ev.rr:.2f} vs minimum {settings.min_rr:g}.")
    add("spread", spread_price <= settings.max_spread_to_stop * ev.sl_distance,
        f"Spread {spread_price:.{spec.digits}f} is {spread_price / ev.sl_distance:.0%} of the stop distance "
        f"(limit {settings.max_spread_to_stop:.0%}).")

    base = min(account.balance, account.equity)
    ev.lots = min(calc_lots(base * min(risk_pct, 100) / 100.0, ev.sl_distance, spec), settings.max_lot)
    ev.lots = math.floor(ev.lots / spec.volume_step + 1e-9) * spec.volume_step if ev.lots else 0.0
    ev.lots = round(ev.lots, 8)
    ev.risk_money = loss_at_stop(ev.lots, ev.sl_distance, spec)
    add("position_size", ev.lots >= spec.volume_min and ev.lots > 0,
        f"{ev.lots:g} lots risks {ev.risk_money:.2f} at the stop." if ev.lots > 0
        else f"The minimum lot ({spec.volume_min:g}) would risk more than {risk_pct:g}% of {base:.2f} at this stop. "
             "Use a tighter stop or a larger account; the lot is never rounded up.")

    start_of_day = account.balance - account.realized_today
    loss_limit = settings.max_daily_loss_pct / 100.0 * start_of_day if start_of_day > 0 else 0.0
    add("daily_loss", -account.realized_today < loss_limit,
        f"Realized today {account.realized_today:+.2f} vs a daily loss limit of -{loss_limit:.2f} "
        f"({settings.max_daily_loss_pct:g}%). Includes every strategy on the account.")
    add("trades_today", account.trades_today_ours < settings.max_trades_per_day,
        f"{account.trades_today_ours} of {settings.max_trades_per_day} trades used today.")
    add("open_positions", account.open_positions_ours < settings.max_open_positions,
        f"{account.open_positions_ours} of {settings.max_open_positions} allowed positions open.")
    return ev
