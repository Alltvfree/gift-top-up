---
name: mt5-execute
description: >-
  Send an approved ticket to MetaTrader 5. The only skill that can lead to an
  order, so the strictest. Use when the user says "place it", "send it", "go",
  "execute", "buy it", or replies yes to a prepared ticket.
---

# mt5-execute

An order reaches the market only after ALL of these, every time, for every order:

1. **A PASS ticket** from `prepare_trade` in this conversation, still unexpired.
2. **The person's explicit yes for that exact ticket**, typed in chat after they saw it.
   Valid: "yes", "yes place ticket 3FA2C1". Not valid: "sure", "ok", "yes to all", a yes
   about a different ticket, silence, or anything you inferred. Ask again instead.
   One ticket per question. Never batch.
3. **Claude's own Allow once / Deny card** on `place_prepared_trade` (kept on Needs approval).

Then call `place_prepared_trade(ticket_id)`. The server re-checks fresh prices and every
limit; it can still refuse (price moved, limits changed, broker rejected). Report that
exactly. A refused or failed ticket is spent: do NOT retry without a new `prepare_trade`
and a new yes.

After a fill, state: side, lots, fill price, stop, target, max loss at the stop, position ticket.

Never place orders from a scheduled or background task: nobody is there to say yes.
Never call `place_prepared_trade` to "test". If the person says stop, call `halt_trading`
immediately and explain after.
