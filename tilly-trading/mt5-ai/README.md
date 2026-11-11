# mt5-ai — Claude + Kronos + MetaTrader 5, on your PC

A Claude trading assistant for MetaTrader 5, built from two open-source projects and the
tested code already in this repo. Runs on the Windows PC with your MT5 terminal. **Demo
accounts only by default.**

| piece | where it comes from | what it does here |
| --- | --- | --- |
| Workflow and safety gates | [Jakeschincariol/day-trader-skill](https://github.com/Jakeschincariol/day-trader-skill) (MIT) | The analyze -> plan -> size -> risk-check -> explicit-yes -> execute sequence, single-use tickets and the "nothing trades without your yes" rule, rebuilt for MT5 as five skills and a risk gate |
| Forecaster | [shiyu-coder/Kronos](https://github.com/shiyu-coder/Kronos) (MIT) | `kronos_forecast`: sampled price paths from the foundation model on live closed candles |
| Strategy | `tilly-trading/kronos` (this repo) | `rule_setup_status`: the rule-based trend+pullback setup, the same code the backtester measured |
| Broker link | `mt5_ai` (this folder) | An MCP server over the MetaTrader5 Python package |

**What was not reused:** day-trader-skill's *code* is built for US stocks (NYSE hours, Yahoo
data, shares, long-only, Alpaca) and cannot run on gold, so its method was kept and its code
was not. Kronos was used as-is.

## How a trade happens

```
mt5-analyze   price, closed candles, rule setup, Kronos vote -> do they agree? (no trade is a fine answer)
mt5-plan-trade   stop + target first, odds replay, prepare_trade -> sized lots, every rule, broker pre-flight
                 -> PASS + single-use ticket   or   BLOCK + every reason
you           read the ticket, type an explicit yes for THAT ticket
mt5-execute   place_prepared_trade -> re-checks fresh prices and limits -> Claude's Allow/Deny card -> order
mt5-review    positions, tighten-only stops, close, daily summary, kill switch
```

There is no tool that sends an arbitrary order, closes everything, or touches a position this
server did not open. `place_prepared_trade` can only send a ticket `prepare_trade` issued, so
what you reviewed is what is sent.

## Safety model

- **Demo only.** Refused on a real-money account unless *you* set `MT5_AI_ALLOW_LIVE=1`. Claude cannot.
- **Stop-loss and take-profit are mandatory**, on the correct sides, with reward:risk >= 1.5.
- **Sized from the stop**: lots rounded *down* so the loss at the stop never exceeds your risk %.
  If the minimum lot would risk more, the trade is blocked, not rounded up.
- **Daily loss limit counts every strategy on the account** (your GRID bots included), 3% by default.
- 3 trades/day, 1 open position, 1 lot cap, spread <= 20% of the stop, gold symbols only (defaults).
- **Re-checked at send time**: account, limits, price drift (>25% of the stop since the ticket cancels it), margin.
- Tickets expire in 5 minutes and work once; a refused or failed ticket is spent.
- **Kill switch**: `halt_trading` blocks new entries until you delete `~/.mt5-ai/HALT`. Claude can halt, only you resume.
- Stops only tighten. Everything is appended to `~/.mt5-ai/trades.jsonl`.
- Claude's own approval card stays on top: keep the three order tools on **Needs approval**.

## Install (Windows PC with MT5 open and logged in to a demo account)

1. Use a Python 3.10-3.12 environment. If you set up Kronos already, reuse its venv:
   `C:\kronos-foundation\venv\Scripts\python.exe -m pip install -r requirements.txt`
2. Put this folder at `C:\mt5-ai`. For the rule setup, `C:\tilly-kronos` must hold the synced
   `tilly-trading/kronos` files (including `setups/` and `setup_live.py`).
3. Add the server to Claude Desktop with `claude_desktop_config.example.json` (adjust paths),
   or install this folder as a Claude Code plugin (`.mcp.json`). Restart Claude.
4. Customize > Connectors > mt5: leave read-only tools on Always allow; set
   `place_prepared_trade`, `move_stop`, `close_position` to **Needs approval**.
5. Ask Claude: "run account_overview". Confirm `mode: DEMO`.
6. **Measure Kronos before believing it:**
   `python -m mt5_ai.kronos_eval --symbol XAUUSD --timeframe M15 --windows 60`
   It walks back through recent history, forecasts each window and counts how often the
   direction was right, with a confidence interval and a plain verdict.

Settings are environment variables: `MT5_AI_SYMBOLS` (e.g. `XAUUSD*`; use `XAUUSDm` on a mini
account), `MT5_AI_MAX_RISK_PCT`, `MT5_AI_MAX_DAILY_LOSS_PCT`, `MT5_AI_MAX_TRADES_PER_DAY`,
`MT5_AI_MAX_OPEN_POSITIONS`, `MT5_AI_MAX_LOT`, `MT5_AI_MIN_RR`, `MT5_AI_ALLOW_LIVE`,
`MT5_AI_KRONOS_REPO`, `MT5_AI_KRONOS_DIR`, `MT5_AI_KRONOS_MODEL` (mini/small/base),
`MT5_AI_STATE_DIR`, `MT5_AI_TERMINAL_PATH`. See `mt5_ai/config.py`.

## Tools

Read-only: `account_overview`, `symbol_details`, `get_quote`, `get_candles` (closed bars only),
`list_positions`, `list_pending_orders`, `todays_summary`.
Analysis: `kronos_forecast`, `rule_setup_status`, `simulate_trade_plan`.
Order path: `prepare_trade` (sends nothing), `place_prepared_trade`, `move_stop`, `close_position`.
Safety: `halt_trading`.

## Honest limits

- **None of the signals is proven.** Kronos has never been measured on your data until you run
  `kronos_eval`; the rule setup has an edge only if its backtest (500+ trades) says so. The tools
  say this in their own output so Claude repeats it.
- `simulate_trade_plan` is a direction-neutral replay: it tells you a plan's geometry and spread
  cost, and *cannot* create an edge. (An earlier draft of it quietly favored whichever side the
  sample history trended toward; it now mirrors every bar so BUY and SELL are symmetric.)
- Only the MetaTrader5 calls are untested against a real terminal: everything else, including the
  full MCP handshake and the order flow, is tested against a fake one (`pytest tests`).
- The loss limit uses the broker server's calendar day from deal history; confirm it matches your broker's.
- Educational software, not financial advice. You can lose money.

## Tests

```
pip install pytest "mcp<2" pandas numpy
pytest tests
```
