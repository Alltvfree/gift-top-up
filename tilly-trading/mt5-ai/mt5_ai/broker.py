"""Thin, injectable wrapper over the MetaTrader5 Python module.

Takes the module as a constructor argument so tests can pass a fake — the
real package only exists on Windows next to a running terminal. Every call
holds one lock: the MetaTrader5 package talks to the terminal over a single
IPC channel and is not safe to call from two threads at once (same reason
mt5-bridge/bridge.py has its _mt5_lock).
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta

import pandas as pd

from .rules import SymbolSpec

TIMEFRAMES = ("M1", "M5", "M15", "M30", "H1", "H4", "D1")
TIMEFRAME_MINUTES = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "D1": 1440}
MAX_CANDLES = 5000


class BrokerError(RuntimeError):
    pass


class Mt5Broker:
    def __init__(self, mt5, lock: threading.RLock | None = None):
        self.mt5 = mt5
        self._lock = lock or threading.RLock()

    # --- connection -------------------------------------------------------
    def initialize(self, path: str | None = None) -> None:
        with self._lock:
            ok = self.mt5.initialize(path=path) if path else self.mt5.initialize()
            if not ok:
                raise BrokerError(f"MetaTrader5.initialize() failed: {self.mt5.last_error()}")

    def shutdown(self) -> None:
        with self._lock:
            self.mt5.shutdown()

    # --- account ----------------------------------------------------------
    def account(self) -> dict:
        with self._lock:
            a = self.mt5.account_info()
            if a is None:
                raise BrokerError(f"account_info() returned None: {self.mt5.last_error()}")
            return {
                "login": a.login, "server": a.server, "currency": a.currency,
                "balance": float(a.balance), "equity": float(a.equity), "margin": float(a.margin),
                "margin_free": float(a.margin_free), "leverage": int(a.leverage),
                "is_demo": a.trade_mode == self.mt5.ACCOUNT_TRADE_MODE_DEMO,
                "mode": {self.mt5.ACCOUNT_TRADE_MODE_DEMO: "DEMO", self.mt5.ACCOUNT_TRADE_MODE_REAL: "REAL"}.get(
                    a.trade_mode, "CONTEST"),
                "trade_allowed": bool(a.trade_allowed),
            }

    # --- symbols and prices ----------------------------------------------
    def _select(self, symbol: str):
        info = self.mt5.symbol_info(symbol)
        if info is None:
            raise BrokerError(f"Unknown symbol {symbol!r}. Check the exact name in Market Watch (e.g. XAUUSD vs XAUUSDm).")
        if not info.visible and not self.mt5.symbol_select(symbol, True):
            raise BrokerError(f"Could not add {symbol} to Market Watch: {self.mt5.last_error()}")
        return self.mt5.symbol_info(symbol)

    def spec(self, symbol: str) -> SymbolSpec:
        with self._lock:
            i = self._select(symbol)
            return SymbolSpec(
                symbol=i.name, digits=int(i.digits), point=float(i.point),
                volume_min=float(i.volume_min), volume_max=float(i.volume_max), volume_step=float(i.volume_step),
                tick_size=float(i.trade_tick_size),
                tick_value_loss=float(getattr(i, "trade_tick_value_loss", 0) or i.trade_tick_value),
                contract_size=float(i.trade_contract_size), stops_level_points=int(i.trade_stops_level),
                trade_allowed=i.trade_mode == self.mt5.SYMBOL_TRADE_MODE_FULL,
            )

    def filling_mode(self, symbol: str):
        with self._lock:
            flags = self._select(symbol).filling_mode
            if flags & 2:   # SYMBOL_FILLING_IOC
                return self.mt5.ORDER_FILLING_IOC
            if flags & 1:   # SYMBOL_FILLING_FOK
                return self.mt5.ORDER_FILLING_FOK
            return self.mt5.ORDER_FILLING_RETURN

    def tick(self, symbol: str) -> dict:
        with self._lock:
            self._select(symbol)
            t = self.mt5.symbol_info_tick(symbol)
            if t is None:
                raise BrokerError(f"No tick for {symbol}: {self.mt5.last_error()}")
            return {"bid": float(t.bid), "ask": float(t.ask), "time": pd.Timestamp(t.time, unit="s", tz="UTC")}

    def rates(self, symbol: str, timeframe: str, count: int) -> pd.DataFrame:
        """CLOSED bars only, oldest first. start_pos=1 skips MT5's bar 0, the
        still-forming candle — a decision made from a half-built bar would not
        match what any backtest saw."""
        tf = timeframe.upper()
        if tf not in TIMEFRAMES:
            raise BrokerError(f"timeframe must be one of {TIMEFRAMES}, got {timeframe!r}")
        if not 1 <= count <= MAX_CANDLES:
            raise BrokerError(f"count must be 1..{MAX_CANDLES}")
        with self._lock:
            self._select(symbol)
            frames, got, pos = [], 0, 1
            while got < count:  # chunked: terminals cap a single request
                n = min(5000, count - got)
                chunk = self.mt5.copy_rates_from_pos(symbol, getattr(self.mt5, f"TIMEFRAME_{tf}"), pos, n)
                if chunk is None or len(chunk) == 0:
                    if not frames:
                        raise BrokerError(f"No {tf} data for {symbol}: {self.mt5.last_error()}")
                    break
                frames.append(pd.DataFrame(chunk))
                got += len(chunk)
                pos += len(chunk)
                if len(chunk) < n:
                    break
        df = pd.concat(frames, ignore_index=True).drop_duplicates(subset="time").sort_values("time").reset_index(drop=True)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        return df[["time", "open", "high", "low", "close", "tick_volume", "spread"]]

    # --- positions, orders, history ---------------------------------------
    def positions(self) -> list[dict]:
        with self._lock:
            rows = self.mt5.positions_get() or ()
            return [
                {
                    "ticket": p.ticket, "symbol": p.symbol,
                    "side": "BUY" if p.type == self.mt5.POSITION_TYPE_BUY else "SELL",
                    "volume": float(p.volume), "price_open": float(p.price_open), "sl": float(p.sl), "tp": float(p.tp),
                    "profit": float(p.profit), "magic": int(p.magic),
                }
                for p in rows
            ]

    def pending_orders(self) -> list[dict]:
        with self._lock:
            rows = self.mt5.orders_get() or ()
            return [
                {"ticket": o.ticket, "symbol": o.symbol, "type": int(o.type), "volume": float(o.volume_current),
                 "price": float(o.price_open), "sl": float(o.sl), "tp": float(o.tp), "magic": int(o.magic)}
                for o in rows
            ]

    def today(self, symbol: str, magic: int) -> dict:
        """Realized P&L today across EVERY strategy on the account, plus how
        many entries this server's magic number opened. 'Today' is the broker
        server's calendar day, the clock the bars use."""
        with self._lock:
            now = self.tick(symbol)["time"]
            midnight = now.normalize()
            start = (midnight - pd.Timedelta(days=2)).to_pydatetime().replace(tzinfo=None)
            end = (midnight + pd.Timedelta(days=3)).to_pydatetime().replace(tzinfo=None)
            # Deal times are server-epoch seconds; the wide query window absorbs any
            # timezone interpretation of the naive datetimes, then we filter exactly.
            deals = self.mt5.history_deals_get(start, end) or ()
        realized, ours = 0.0, 0
        floor = midnight.timestamp()
        for d in deals:
            if d.time < floor or d.type not in (self.mt5.DEAL_TYPE_BUY, self.mt5.DEAL_TYPE_SELL):
                continue
            if d.entry in (self.mt5.DEAL_ENTRY_OUT, self.mt5.DEAL_ENTRY_INOUT, self.mt5.DEAL_ENTRY_OUT_BY):
                realized += float(d.profit) + float(d.commission) + float(d.swap) + float(getattr(d, "fee", 0.0))
            if d.entry == self.mt5.DEAL_ENTRY_IN and d.magic == magic:
                ours += 1
        return {"realized": realized, "trades_ours": ours, "server_day": str(midnight.date())}

    # --- requests -----------------------------------------------------------
    def market_request(self, *, symbol, side, lots, sl, tp, price, deviation, magic, comment) -> dict:
        m = self.mt5
        return {
            "action": m.TRADE_ACTION_DEAL, "symbol": symbol, "volume": float(lots),
            "type": m.ORDER_TYPE_BUY if side == "BUY" else m.ORDER_TYPE_SELL,
            "price": float(price), "sl": float(sl), "tp": float(tp), "deviation": int(deviation),
            "magic": int(magic), "comment": comment[:31], "type_time": m.ORDER_TIME_GTC,
            "type_filling": self.filling_mode(symbol),
        }

    def close_request(self, position: dict, *, price, deviation, magic) -> dict:
        m = self.mt5
        closing_buy = position["side"] == "SELL"   # closing a SELL means buying
        return {
            "action": m.TRADE_ACTION_DEAL, "symbol": position["symbol"], "volume": position["volume"],
            "type": m.ORDER_TYPE_BUY if closing_buy else m.ORDER_TYPE_SELL, "position": position["ticket"],
            "price": float(price), "deviation": int(deviation), "magic": int(magic), "comment": "mt5-ai close",
            "type_time": m.ORDER_TIME_GTC, "type_filling": self.filling_mode(position["symbol"]),
        }

    def sltp_request(self, position: dict, sl: float, tp: float) -> dict:
        return {"action": self.mt5.TRADE_ACTION_SLTP, "symbol": position["symbol"], "position": position["ticket"],
                "sl": float(sl), "tp": float(tp)}

    def check(self, request: dict) -> dict:
        """Broker pre-flight (order_check): margin, stops level, market open."""
        with self._lock:
            r = self.mt5.order_check(request)
            if r is None:
                return {"ok": False, "retcode": None, "comment": f"order_check returned None: {self.mt5.last_error()}"}
            return {"ok": r.retcode in (0, self.mt5.TRADE_RETCODE_DONE), "retcode": int(r.retcode),
                    "comment": str(r.comment), "margin_free": float(getattr(r, "margin_free", 0.0))}

    def send(self, request: dict) -> dict:
        with self._lock:
            r = self.mt5.order_send(request)
            if r is None:
                return {"ok": False, "retcode": None, "comment": f"order_send returned None: {self.mt5.last_error()}"}
            return {
                "ok": r.retcode in (self.mt5.TRADE_RETCODE_DONE, self.mt5.TRADE_RETCODE_PLACED),
                "retcode": int(r.retcode), "comment": str(r.comment), "price": float(r.price),
                "volume": float(r.volume), "deal": int(r.deal), "order": int(r.order),
            }
