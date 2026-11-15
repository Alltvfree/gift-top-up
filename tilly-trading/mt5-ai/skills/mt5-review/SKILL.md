---
name: mt5-review
description: >-
  Manage and review open trades and the day: positions, stop moves, closing,
  P&L, loss budget, the kill switch. Use when the user says "how is my trade",
  "move my stop", "close it", "breakeven", "what did I do today", "stop trading",
  "halt", or at the end of a session.
---

# mt5-review

- `list_positions` and `todays_summary` first. Say which positions this server opened
  (`opened_by_this_server`); only those can be touched. GRID bots' positions are not yours.
- **Moving a stop**: `move_stop` only ever TIGHTENS. Typical, and only if the person agrees:
  to breakeven after price has moved one full stop-distance in favor. Never widen, never
  remove a stop, never "give it room".
- **Closing**: `close_position` closes one position at market. Ask first unless the person
  already told you to close it. There is deliberately no close-all tool.
- **Kill switch**: if the person says stop, or something looks wrong (price spike, wide spread,
  unexpected position, repeated errors, daily loss budget nearly gone), call `halt_trading`
  first, then explain. Resuming is the person's act: they delete the HALT file.
- **End of session**: summarize trades, realized P&L (all strategies), what the rules blocked
  and why, and what to look at next. Be straight about losses; do not rationalize them.
- Watch the person's behavior too: revenge trading after a loss, widening stops, oversizing,
  trading outside the plan. Name it kindly and point back to the limits.


## Journal review

Call `journal_review` to see how placed trades actually ended, in R, overall and by tag. Report its `reading` fields as written: with fewer than 30 closed trades it says "too few", and you must not call any tag or setup "working" on that basis. Remind the person that with many tags, one will look good by chance.
