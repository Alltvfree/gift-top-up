---
name: mt5-plan-trade
description: >-
  Turn an idea into a concrete, risk-sized trade ticket: entry, stop, target,
  lot size, odds check and every rule. Use when the user says "plan the trade",
  "size it", "what lot", "set my stop and target", "prepare the order", or after
  mt5-analyze found something worth trading.
---

# mt5-plan-trade

Stop and target are set BEFORE the entry, never after.

1. Levels. If `rule_setup_status` fired, use its stop and target prices (structural stop,
   2R). Otherwise take the person's levels; suggest a stop beyond a real swing, never
   a round number inside the noise. Both are required.
2. `simulate_trade_plan` with those levels. Read it honestly: it replays this symbol's own
   recent candles with no directional view, so it shows the plan's GEOMETRY (how often
   target vs stop vs neither, spread cost), not an edge. If it says the plan "costs you",
   say so and suggest a tighter horizon or different levels.
3. `prepare_trade` with side, sl, tp and a one-line `note` giving the reason. It sizes
   the lot from the stop distance and the account, runs every rule and the broker's
   own pre-flight, and sends nothing.
4. If **BLOCK**: list EVERY reason in plain words. Do not nudge the numbers to slip under
   a rule, do not raise risk, do not retry with different wording. Offer a genuinely
   different plan only if the person asks.
5. If **PASS**: show the ticket text exactly as returned. Then hand over to `mt5-execute`.
   The ticket expires in minutes and can be used once.

Never size by feel, never raise `risk_pct` above what the person set, never add to a loser.
