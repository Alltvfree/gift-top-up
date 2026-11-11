---
name: mt5-setup
description: >-
  Connect Claude to MetaTrader 5 through the mt5-ai MCP server on this PC:
  install, configure, set tool permissions, confirm it is a DEMO account.
  Use when the user says "set up MT5", "connect MetaTrader", "connect my
  broker", "is it demo", or when a mt5 tool is missing or failing.
---

# mt5-setup

The server runs on the Windows PC that has the MT5 terminal open and logged in.
Never ask for, read or repeat an MT5 password or any key in chat. The terminal
holds its own login; the server just attaches to it.

1. Python 3.10+ environment with `pip install -r requirements.txt` (use the
   Kronos venv so `kronos_forecast` works). MT5 terminal open, logged in to a
   **demo** account, "Algo trading" button on.
2. Add the server to Claude Desktop (`claude_desktop_config.example.json`) or
   install this folder as a Claude Code plugin (`.mcp.json`). Settings are
   environment variables (`MT5_AI_*`, see README); defaults are demo-only,
   gold-only, 1% risk, 3 trades/day, 3% daily loss, 1 open position.
3. **Permissions** (Customize > Connectors > mt5): read-only and compute tools
   may be Always allow. Set `place_prepared_trade`, `move_stop` and
   `close_position` to **Needs approval**, never Always allow. `halt_trading`
   is safe to leave allowed. Claude Code: put order tools under `ask`, never `allow`.
4. Verify: call `account_overview`. Confirm `mode` is DEMO and the symbol list
   matches Market Watch (gold is `XAUUSD` on real accounts, `XAUUSDm` on mini).
   If the symbol name differs, tell the person to set `MT5_AI_SYMBOLS`.
5. Kronos is optional: it needs `MT5_AI_KRONOS_REPO`. The rule-based setup needs
   `MT5_AI_KRONOS_DIR`. A tool that says "not configured" just needs that variable.

Never switch `MT5_AI_ALLOW_LIVE` on for the person. If they want live trading,
tell them what it does and that they must set it themselves, after a demo period.
