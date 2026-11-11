"""A stand-in for the MetaTrader5 module: just enough behavior (accounts,
ticks, candles, positions, deals, order_check/order_send) to exercise the
broker wrapper and the order flow end to end without a terminal."""
from __future__ import annotations

import itertools
from types import SimpleNamespace as NS

import numpy as np


class FakeMT5:
    ACCOUNT_TRADE_MODE_DEMO, ACCOUNT_TRADE_MODE_CONTEST, ACCOUNT_TRADE_MODE_REAL = 0, 1, 2
    SYMBOL_TRADE_MODE_FULL = 4
    TIMEFRAME_M1, TIMEFRAME_M5, TIMEFRAME_M15, TIMEFRAME_M30 = 1, 5, 15, 30
    TIMEFRAME_H1, TIMEFRAME_H4, TIMEFRAME_D1 = 16385, 16388, 16408
    POSITION_TYPE_BUY, POSITION_TYPE_SELL = 0, 1
    ORDER_TYPE_BUY, ORDER_TYPE_SELL = 0, 1
    TRADE_ACTION_DEAL, TRADE_ACTION_SLTP = 1, 6
    ORDER_TIME_GTC = 0
    ORDER_FILLING_FOK, ORDER_FILLING_IOC, ORDER_FILLING_RETURN = 0, 1, 2
    DEAL_TYPE_BUY, DEAL_TYPE_SELL, DEAL_TYPE_BALANCE = 0, 1, 2
    DEAL_ENTRY_IN, DEAL_ENTRY_OUT, DEAL_ENTRY_INOUT, DEAL_ENTRY_OUT_BY = 0, 1, 2, 3
    TRADE_RETCODE_PLACED, TRADE_RETCODE_DONE = 10008, 10009

    _TF_MINUTES = {1: 1, 5: 5, 15: 15, 30: 30, 16385: 60, 16388: 240, 16408: 1440}

    def __init__(self):
        self.login, self.server, self.currency = 123456789, "Demo-Server", "USD"
        self.balance = self.equity = 10_000.0
        self.account_trade_mode = self.ACCOUNT_TRADE_MODE_DEMO
        self.symbol_name, self.symbol_trade_mode, self.visible = "XAUUSD", self.SYMBOL_TRADE_MODE_FULL, True
        self.filling_flags, self.stops_level = 2, 0
        self.bid, self.ask = 5000.00, 5000.25
        self.now = 1_760_000_000  # a Thursday, server-epoch seconds
        self.positions: list[NS] = []
        self.deals: list[NS] = []
        self.check_retcode, self.send_retcode = 0, self.TRADE_RETCODE_DONE
        self.sent: list[dict] = []
        self.checked: list[dict] = []
        self.rates_calls: list[tuple] = []
        self._tickets = itertools.count(9001)
        self.initialized = False

    # --- connection ---
    def initialize(self, **kwargs):
        self.initialized = True
        return True

    def shutdown(self):
        self.initialized = False

    def last_error(self):
        return (1, "Success")

    # --- account / symbol ---
    def account_info(self):
        return NS(login=self.login, server=self.server, currency=self.currency, balance=self.balance, equity=self.equity,
                  margin=0.0, margin_free=self.equity, leverage=500, trade_mode=self.account_trade_mode, trade_allowed=True)

    def symbol_info(self, symbol):
        if symbol != self.symbol_name:
            return None
        return NS(name=self.symbol_name, visible=self.visible, digits=2, point=0.01, volume_min=0.01, volume_max=100.0,
                  volume_step=0.01, trade_tick_size=0.01, trade_tick_value=1.0, trade_tick_value_loss=1.0,
                  trade_contract_size=100.0, trade_stops_level=self.stops_level, trade_mode=self.symbol_trade_mode,
                  filling_mode=self.filling_flags, spread=25)

    def symbol_select(self, symbol, enable):
        self.visible = True
        return True

    def symbol_info_tick(self, symbol):
        return NS(bid=self.bid, ask=self.ask, time=self.now)

    # --- candles ---
    def copy_rates_from_pos(self, symbol, timeframe, start_pos, count):
        self.rates_calls.append((symbol, timeframe, start_pos, count))
        tf = self._TF_MINUTES[timeframe] * 60
        bar0_open = self.now // tf * tf  # the still-forming bar
        opens = np.array([bar0_open - (start_pos + count - 1 - i) * tf for i in range(count)], dtype=np.int64)
        base = 5000 + 8 * np.sin(np.arange(count) / 7.0)
        out = np.zeros(count, dtype=[("time", "i8"), ("open", "f8"), ("high", "f8"), ("low", "f8"), ("close", "f8"),
                                     ("tick_volume", "i8"), ("spread", "i4"), ("real_volume", "i8")])
        out["time"], out["open"], out["close"] = opens, base, base + 0.5
        out["high"], out["low"] = base + 2.0, base - 2.0
        out["tick_volume"], out["spread"] = 100, 25
        return out

    # --- positions / history ---
    def positions_get(self, **kwargs):
        return tuple(self.positions)

    def orders_get(self, **kwargs):
        return ()

    def history_deals_get(self, start, end):
        return tuple(self.deals)

    def add_deal(self, *, entry, profit=0.0, magic=0, seconds_ago=60, dtype=0, commission=0.0):
        self.deals.append(NS(time=self.now - seconds_ago, type=dtype, entry=entry, profit=profit, commission=commission,
                             swap=0.0, fee=0.0, magic=magic))

    def add_position(self, *, side="BUY", volume=0.19, price_open=5000.0, sl=4995.0, tp=5010.0, magic=26110001):
        p = NS(ticket=next(self._tickets), symbol=self.symbol_name, type=self.POSITION_TYPE_BUY if side == "BUY" else self.POSITION_TYPE_SELL,
               volume=volume, price_open=price_open, sl=sl, tp=tp, profit=0.0, magic=magic)
        self.positions.append(p)
        return p

    # --- orders ---
    def order_check(self, request):
        self.checked.append(dict(request))
        return NS(retcode=self.check_retcode, comment="Done" if self.check_retcode == 0 else "Market closed", margin_free=9_000.0)

    def order_send(self, request):
        self.sent.append(dict(request))
        if self.send_retcode != self.TRADE_RETCODE_DONE:
            return NS(retcode=self.send_retcode, comment="Requote", price=0.0, volume=0.0, deal=0, order=0)
        action = request["action"]
        if action == self.TRADE_ACTION_DEAL and "position" in request:
            self.positions = [p for p in self.positions if p.ticket != request["position"]]
        elif action == self.TRADE_ACTION_DEAL:
            self.add_position(side="BUY" if request["type"] == self.ORDER_TYPE_BUY else "SELL", volume=request["volume"],
                              price_open=request["price"], sl=request["sl"], tp=request["tp"], magic=request["magic"])
        elif action == self.TRADE_ACTION_SLTP:
            for p in self.positions:
                if p.ticket == request["position"]:
                    p.sl, p.tp = request["sl"], request["tp"]
        ticket = self.positions[-1].ticket if self.positions else 0
        return NS(retcode=self.TRADE_RETCODE_DONE, comment="Request executed", price=request.get("price", 0.0),
                  volume=request.get("volume", 0.0), deal=ticket + 100, order=ticket)
