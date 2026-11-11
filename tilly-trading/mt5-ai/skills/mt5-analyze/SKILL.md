---
name: mt5-analyze
description: >-
  Read the gold (XAUUSD) market with the mt5 tools: price, closed candles, the
  rule-based trend+pullback setup, and a Kronos forecast, then say plainly whether
  they agree. Use when the user says "analyze gold", "what is the market doing",
  "any setup", "should I trade", "check XAUUSD", or starts a trading session.
---

# mt5-analyze

Goal: an honest read, not a trade. **"No trade" is a normal and good answer.**

1. `account_overview`: confirm DEMO, note halted/limits. If `halted` is true, say so and stop.
2. `todays_summary`: loss budget and trades left. If none left, stop here.
3. `get_quote` and `get_candles` (M15 ~ 100, H1 ~ 50): state price, spread, and the
   plain-words trend from the candles. Only CLOSED candles are returned; say "as of the last closed bar".
4. `rule_setup_status`: does the setup fire (BUY/SELL/NONE)? NONE is the usual result.
5. `kronos_forecast` (samples 5+, horizon 8-16). It takes up to a minute. Report the
   share of paths ending higher WITH its standard error, and the mean move.
6. Say whether they **agree**. Table: setup / Kronos lean / agreement.

Rules for how to talk about it:
- Kronos is an unverified generative model. Its "share ending higher" is a vote count,
  not a probability. If the person has run `python -m mt5_ai.kronos_eval` on this
  symbol, quote its VERDICT; if not, say it has never been measured on their data.
- The setup has an edge only if a backtest with 500+ trades said so. Never claim one.
- Conditions to even consider a trade: the setup fired, Kronos does not lean against it,
  there is loss budget and trade count left, and no halt. Otherwise the answer is no trade.
- Do not present forecasts as predictions of fact, and never promise outcomes.

If the person wants to proceed, hand over to `mt5-plan-trade`.
