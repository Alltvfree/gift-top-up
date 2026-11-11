"""The tool logic, independent of MCP so it can be unit-tested with a fake
broker. server.py only registers these methods as MCP tools.

The order path is deliberately narrow and has three layers:
  1. prepare_trade   sizes the trade, runs every risk rule and the broker's own
                     pre-flight, and issues a single-use ticket.
  2. the person      reads the ticket and says yes in chat.
  3. place_prepared_trade  re-checks everything against fresh prices and sends
                     ONLY that ticket. Claude's own Allow/Deny card sits on top.
There is no tool that sends arbitrary orders, closes everything, or touches
anything this server did not open.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Protocol

import pandas as pd

from .broker import Mt5Broker
from .config import Settings
from .rules import AccountContext, Check, evaluate_order
from .simulate import simulate_plan
from .tickets import TicketError, TicketStore


class Forecaster(Protocol):
    def forecast(self, df: pd.DataFrame, pred_len: int, samples: int) -> dict: ...


class SetupAdapter(Protocol):
    def status(self, base: pd.DataFrame, higher: pd.DataFrame, *, symbol: str, timeframe: str,
               higher_timeframe: str, now: pd.Timestamp, point: float) -> dict: ...


def _checks(checks: list[Check]) -> list[dict]:
    return sorted((asdict(c) for c in checks), key=lambda c: c["passed"])  # failures first


class Mt5Service:
    def __init__(self, broker: Mt5Broker, settings: Settings, *, forecaster: Forecaster | None = None,
                 setup: SetupAdapter | None = None, clock=time.time):
        self.broker, self.s = broker, settings
        self.forecaster, self.setup = forecaster, setup
        self.tickets = TicketStore(settings.ticket_ttl_seconds, clock)
        self._log_path = Path(settings.state_dir) / "trades.jsonl"
        self.halt_file = Path(settings.state_dir) / "HALT"

    # --- audit log ----------------------------------------------------------
    def _log(self, event: str, **data) -> None:
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": pd.Timestamp.now(tz="UTC").isoformat(), "event": event, **data}, default=str) + "\n")
        except OSError:
            pass  # an unwritable log must never block (or fake) a trade

    # --- kill switch ----------------------------------------------------------
    def halted(self) -> bool:
        return self.halt_file.exists()

    def halt_trading(self, reason: str = "") -> dict:
        """Blocks all NEW entries until the person deletes the HALT file. Claude can
        stop itself; only the person can resume. Open positions keep their broker-side
        stop and target; closing them stays a separate, explicit command."""
        self.halt_file.parent.mkdir(parents=True, exist_ok=True)
        self.halt_file.write_text(reason or "halted", encoding="utf-8")
        self._log("halted", reason=reason)
        return {"halted": True, "resume": f"Delete {self.halt_file} to allow new entries again.",
                "open_positions_unaffected": "Their broker-side stop-loss and take-profit stay in place."}

    _HALT_MSG = "Trading is HALTED (kill switch). Delete {path} to allow new entries again."

    # --- read-only ----------------------------------------------------------
    def account_overview(self) -> dict:
        a = self.broker.account()
        return {
            "account": f"***{str(a['login'])[-3:]}", "server": a["server"], "currency": a["currency"],
            "mode": a["mode"], "balance": a["balance"], "equity": a["equity"], "margin_free": a["margin_free"],
            "leverage": a["leverage"], "terminal_trading_allowed": a["trade_allowed"],
            "orders_allowed_by_this_server": (a["is_demo"] or self.s.allow_live) and not self.halted(),
            "halted": self.halted(),
            "limits": {
                "symbols": list(self.s.symbols), "max_risk_pct": self.s.max_risk_pct,
                "max_daily_loss_pct": self.s.max_daily_loss_pct, "max_trades_per_day": self.s.max_trades_per_day,
                "max_open_positions": self.s.max_open_positions, "max_lot": self.s.max_lot, "min_rr": self.s.min_rr,
            },
        }

    def symbol_details(self, symbol: str) -> dict:
        spec, tk = self.broker.spec(symbol), self.broker.tick(symbol)
        return {**asdict(spec), "bid": tk["bid"], "ask": tk["ask"], "spread_price": round(tk["ask"] - tk["bid"], spec.digits),
                "server_time": tk["time"].isoformat()}

    def get_quote(self, symbol: str) -> dict:
        spec, tk = self.broker.spec(symbol), self.broker.tick(symbol)
        return {"symbol": spec.symbol, "bid": tk["bid"], "ask": tk["ask"],
                "spread_price": round(tk["ask"] - tk["bid"], spec.digits), "server_time": tk["time"].isoformat()}

    def get_candles(self, symbol: str, timeframe: str = "M15", count: int = 100) -> dict:
        df = self.broker.rates(symbol, timeframe, min(max(count, 1), 1000))
        rows = [[r.time.isoformat(), r.open, r.high, r.low, r.close, int(r.tick_volume), int(r.spread)] for r in df.itertuples()]
        return {"symbol": symbol, "timeframe": timeframe.upper(), "closed_bars_only": True,
                "columns": ["time", "open", "high", "low", "close", "tick_volume", "spread_points"], "rows": rows}

    def list_positions(self) -> dict:
        pos = self.broker.positions()
        return {"positions": [{**p, "opened_by_this_server": p["magic"] == self.s.magic} for p in pos]}

    def list_pending_orders(self) -> dict:
        return {"orders": self.broker.pending_orders()}

    def todays_summary(self, symbol: str | None = None) -> dict:
        symbol = symbol or self.s.symbols[0].rstrip("*")
        t = self.broker.today(symbol, self.s.magic)
        a = self.broker.account()
        start = a["balance"] - t["realized"]
        limit = self.s.max_daily_loss_pct / 100 * start
        return {
            "server_day": t["server_day"], "realized_pnl_all_strategies": round(t["realized"], 2),
            "daily_loss_limit": round(-limit, 2), "loss_budget_left": round(limit + t["realized"], 2),
            "trades_opened_by_this_server": t["trades_ours"], "trades_left_today": max(self.s.max_trades_per_day - t["trades_ours"], 0),
        }

    # --- analysis -----------------------------------------------------------
    def kronos_forecast(self, symbol: str, timeframe: str = "M15", lookback: int = 400,
                        horizon_bars: int = 16, samples: int = 5) -> dict:
        if self.forecaster is None:
            return {"error": "Kronos is not configured: set MT5_AI_KRONOS_REPO to the folder holding Kronos' `model` package."}
        df = self.broker.rates(symbol, timeframe, lookback)
        return {"symbol": symbol, "timeframe": timeframe.upper(), **self.forecaster.forecast(df, horizon_bars, samples)}

    def rule_setup_status(self, symbol: str, timeframe: str = "M15", higher_timeframe: str = "H1") -> dict:
        if self.setup is None:
            return {"error": "The rule-based setup is not configured: set MT5_AI_KRONOS_DIR to the tilly-trading/kronos folder."}
        spec = self.broker.spec(symbol)
        now = self.broker.tick(symbol)["time"]
        base, higher = self.broker.rates(symbol, timeframe, 600), self.broker.rates(symbol, higher_timeframe, 300)
        return self.setup.status(base, higher, symbol=symbol, timeframe=timeframe, higher_timeframe=higher_timeframe,
                                 now=now, point=spec.point)

    def simulate_trade_plan(self, symbol: str, side: str, sl: float, tp: float, timeframe: str = "M15",
                            horizon_bars: int = 32, simulations: int = 5000, history_bars: int = 2000) -> dict:
        side = side.upper()
        tk, spec = self.broker.tick(symbol), self.broker.spec(symbol)
        entry = tk["ask"] if side == "BUY" else tk["bid"]
        bars = self.broker.rates(symbol, timeframe, history_bars)
        out = simulate_plan(bars, side=side, entry=entry, sl=sl, tp=tp, horizon_bars=horizon_bars,
                            spread_price=tk["ask"] - tk["bid"], simulations=min(max(simulations, 100), 20000))
        return {"symbol": spec.symbol, "side": side, "entry": entry, "sl": sl, "tp": tp, "timeframe": timeframe.upper(), **out}

    # --- the order path -----------------------------------------------------
    def _context(self, account: dict, symbol: str) -> AccountContext:
        t = self.broker.today(symbol, self.s.magic)
        ours_open = sum(1 for p in self.broker.positions() if p["magic"] == self.s.magic)
        return AccountContext(account["is_demo"], account["balance"], account["equity"], t["realized"], t["trades_ours"], ours_open)

    def prepare_trade(self, symbol: str, side: str, sl: float, tp: float, risk_pct: float | None = None, note: str = "") -> dict:
        if self.halted():
            return {"verdict": "BLOCK", "reasons": [self._HALT_MSG.format(path=self.halt_file)], "checks": []}
        side = side.upper()
        risk_pct = self.s.max_risk_pct if risk_pct is None else risk_pct
        a, spec, tk = self.broker.account(), self.broker.spec(symbol), self.broker.tick(symbol)
        entry = tk["ask"] if side == "BUY" else tk["bid"]
        sl, tp = round(sl, spec.digits), round(tp, spec.digits)
        ev = evaluate_order(side=side, entry=entry, sl=sl, tp=tp, risk_pct=risk_pct, spread_price=tk["ask"] - tk["bid"],
                            spec=spec, account=self._context(a, spec.symbol), settings=self.s)
        if ev.passed:
            req = self.broker.market_request(symbol=spec.symbol, side=side, lots=ev.lots, sl=sl, tp=tp, price=entry,
                                             deviation=self.s.deviation_points, magic=self.s.magic, comment="mt5-ai")
            pre = self.broker.check(req)
            ev.checks.append(Check("broker_preflight", pre["ok"], f"{pre['comment']} (retcode {pre['retcode']})"))
        if not ev.passed:
            self._log("blocked", symbol=spec.symbol, side=side, sl=sl, tp=tp, failures=[c.name for c in ev.failures])
            return {"verdict": "BLOCK", "reasons": [c.detail for c in ev.failures], "checks": _checks(ev.checks)}
        t = self.tickets.issue(symbol=spec.symbol, side=side, lots=ev.lots, sl=sl, tp=tp, ref_price=entry,
                               risk_pct=risk_pct, risk_money=ev.risk_money, rr=ev.rr, note=note)
        self._log("prepared", ticket=t.id, fingerprint=t.fingerprint, symbol=t.symbol, side=side, lots=t.lots, sl=sl, tp=tp, note=note)
        return {"verdict": "PASS", "ticket_id": t.id, "fingerprint": t.fingerprint, "expires_in_seconds": self.s.ticket_ttl_seconds,
                "ticket": self.tickets.describe(t, spec.digits), "checks": _checks(ev.checks),
                "next": "Show the person this ticket. Only if they reply with an explicit yes for THIS ticket, call place_prepared_trade."}

    def place_prepared_trade(self, ticket_id: str) -> dict:
        if self.halted():
            return {"placed": False, "error": self._HALT_MSG.format(path=self.halt_file)}
        try:
            t = self.tickets.take(ticket_id)
        except TicketError as e:
            return {"placed": False, "error": str(e)}
        a, spec, tk = self.broker.account(), self.broker.spec(t.symbol), self.broker.tick(t.symbol)
        entry = tk["ask"] if t.side == "BUY" else tk["bid"]

        def refuse(reason: str, **extra) -> dict:
            self._log("refused", ticket=t.id, reason=reason, **extra)
            return {"placed": False, "ticket": t.id, "error": reason, "note": "The ticket is spent. Prepare the trade again to retry.", **extra}

        drift, stop_dist = abs(entry - t.ref_price), abs(t.ref_price - t.sl)
        if drift > self.s.max_drift_to_stop * stop_dist:
            return refuse(f"Price moved {drift:.{spec.digits}f} since the ticket (limit {self.s.max_drift_to_stop * stop_dist:.{spec.digits}f}).")
        ev = evaluate_order(side=t.side, entry=entry, sl=t.sl, tp=t.tp, risk_pct=t.risk_pct, spread_price=tk["ask"] - tk["bid"],
                            spec=spec, account=self._context(a, t.symbol), settings=self.s)
        if not ev.passed:
            return refuse("Re-check failed: " + "; ".join(c.detail for c in ev.failures), checks=_checks(ev.checks))
        if ev.lots + 1e-9 < t.lots:
            return refuse(f"The risk budget shrank since the ticket: {ev.lots:g} lots now allowed, ticket was for {t.lots:g}.")
        req = self.broker.market_request(symbol=t.symbol, side=t.side, lots=t.lots, sl=t.sl, tp=t.tp, price=entry,
                                         deviation=self.s.deviation_points, magic=self.s.magic, comment="mt5-ai")
        pre = self.broker.check(req)
        if not pre["ok"]:
            return refuse(f"Broker pre-flight refused: {pre['comment']} (retcode {pre['retcode']}).")
        res = self.broker.send(req)
        self._log("placed" if res["ok"] else "failed", ticket=t.id, fingerprint=t.fingerprint, **res)
        if not res["ok"]:
            return {"placed": False, "ticket": t.id, "error": f"Broker rejected the order: {res['comment']} (retcode {res['retcode']}).",
                    "note": "The ticket is spent. Do not retry without a new check and a new yes."}
        return {"placed": True, "ticket": t.id, "side": t.side, "symbol": t.symbol, "lots": res["volume"], "fill_price": res["price"],
                "stop_loss": t.sl, "take_profit": t.tp, "position_ticket": res["order"], "max_loss_at_stop": round(t.risk_money, 2)}

    # --- managing what this server opened ------------------------------------
    def _ours(self, position_ticket: int) -> dict:
        for p in self.broker.positions():
            if p["ticket"] == position_ticket:
                if p["magic"] != self.s.magic:
                    raise ValueError(f"Position {position_ticket} was not opened by this server; this tool only manages its own.")
                return p
        raise ValueError(f"No open position {position_ticket}.")

    def move_stop(self, position_ticket: int, new_sl: float, new_tp: float | None = None) -> dict:
        p = self._ours(position_ticket)
        if p["sl"] and ((p["side"] == "BUY" and new_sl < p["sl"]) or (p["side"] == "SELL" and new_sl > p["sl"])):
            return {"moved": False, "error": f"Refused: that would WIDEN the stop (now {p['sl']}). A stop only ever moves toward or past entry."}
        tk, spec = self.broker.tick(p["symbol"]), self.broker.spec(p["symbol"])
        wrong_side = new_sl >= tk["bid"] if p["side"] == "BUY" else new_sl <= tk["ask"]
        if wrong_side:
            return {"moved": False, "error": "Refused: the new stop is already through the current price."}
        res = self.broker.send(self.broker.sltp_request(p, round(new_sl, spec.digits), round(new_tp if new_tp else p["tp"], spec.digits)))
        self._log("stop_moved" if res["ok"] else "stop_move_failed", position=position_ticket, new_sl=new_sl, **res)
        return {"moved": res["ok"], "position_ticket": position_ticket, "new_sl": new_sl, "broker": res["comment"]}

    def close_position(self, position_ticket: int) -> dict:
        p = self._ours(position_ticket)
        tk = self.broker.tick(p["symbol"])
        price = tk["bid"] if p["side"] == "BUY" else tk["ask"]
        res = self.broker.send(self.broker.close_request(p, price=price, deviation=self.s.deviation_points, magic=self.s.magic))
        self._log("closed" if res["ok"] else "close_failed", position=position_ticket, **res)
        return {"closed": res["ok"], "position_ticket": position_ticket, "fill_price": res.get("price"), "broker": res["comment"]}
