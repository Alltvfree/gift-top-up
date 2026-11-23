"""A pre-trade reality check: not a prediction, a list of reasons a particular trade may be worse than usual.

Every flag is something observable in the last few hours of prices, and each is logged on the trade
(tag `flag:<code>`), so the journal can later show whether flagged trades really did worse. Until it has
30+ trades, treat the flags as prompts to think, nothing more.

Flags
  against_h1_trend       buying below a rising/falling hourly trend (or selling against it)
  wide_spread            spread more than 1.5x its recent typical value (costs more, fills worse)
  stop_inside_noise      stop smaller than 0.8x the recent typical 5-minute range (likely to be hit by noise)
  target_beyond_range    target needs price to make a new 12-hour extreme first
  thin_hours             21:00-01:00 server time, when spreads widen and moves are erratic
"""
from __future__ import annotations

import pandas as pd

LABELS = {
    "against_h1_trend": "going against the hourly trend",
    "wide_spread": "spread is wider than usual",
    "stop_inside_noise": "stop is smaller than normal 5-minute noise",
    "target_beyond_range": "target needs a new 12-hour high/low",
    "thin_hours": "thin hours (spreads widen, moves are erratic)",
}


def h1_trend(h1: pd.DataFrame) -> str:
    """'up', 'down' or 'flat' from the last closed hourly bars: price vs EMA50 and EMA20 vs EMA50."""
    if len(h1) < 55:
        return "unknown"
    c = h1["close"]
    e20, e50 = c.ewm(span=20, adjust=False).mean().iloc[-1], c.ewm(span=50, adjust=False).mean().iloc[-1]
    if c.iloc[-1] > e50 and e20 > e50:
        return "up"
    if c.iloc[-1] < e50 and e20 < e50:
        return "down"
    return "flat"


def assess(side: str, entry: float, sl: float, tp: float, *, m5: pd.DataFrame, m15: pd.DataFrame, h1: pd.DataFrame,
           spread_price: float, typical_spread_price: float, server_hour: int) -> dict:
    side = side.upper()
    flags: list[str] = []
    trend = h1_trend(h1)
    if (side == "BUY" and trend == "down") or (side == "SELL" and trend == "up"):
        flags.append("against_h1_trend")
    if typical_spread_price > 0 and spread_price > 1.5 * typical_spread_price:
        flags.append("wide_spread")
    typical_range = float((m5["high"] - m5["low"]).tail(12).mean()) if len(m5) else 0.0
    if typical_range > 0 and abs(entry - sl) < 0.8 * typical_range:
        flags.append("stop_inside_noise")
    recent = m15.tail(48)                                  # 12 hours of 15-minute bars
    if len(recent) and ((side == "BUY" and tp > recent["high"].max()) or (side == "SELL" and tp < recent["low"].min())):
        flags.append("target_beyond_range")
    if server_hour in (21, 22, 23, 0):
        flags.append("thin_hours")
    return {"h1_trend": trend, "flags": flags, "notes": [LABELS[f] for f in flags],
            "typical_5m_range": round(typical_range, 5), "caveat": "Context, not a forecast: it can't tell you which way price will go."}
