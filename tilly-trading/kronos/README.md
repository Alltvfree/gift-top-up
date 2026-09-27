# Kronos — local AI signal generator

A small local LightGBM model that watches MT5 market data and publishes
BUY / SELL / NO_TRADE forecasts for Tilly to display (and, eventually, for
bots to optionally use as an entry filter). Based on the project notes in
`forex_local_ai_kronos_notes.txt` (LightGBM over an LLM, TP-before-SL
labeling instead of raw direction, chronological/walk-forward validation,
an independent risk engine with veto power).

## Why this exists, and why it has to run on Windows

Same reason as `tilly-trading/mt5-bridge/`: the official `MetaTrader5`
Python package drives the terminal over local IPC, not a network protocol,
so `mt5_data.py` must run on a Windows machine with a logged-in MT5
terminal. It can run on the same machine as the MT5 bridge, or a separate
one — either way, it needs its own MT5 terminal login (it does not go
through the bridge).

> **Tested against synthetic data, not real MT5 history.** `features.py`,
> `labels.py`, and `train.py`'s chronological split/training loop have no
> MT5 dependency and were verified end-to-end against synthetic OHLC data:
> a no-lookahead check (truncating future bars doesn't change past feature
> values), a multi-timeframe merge check (never attaches a future
> higher-timeframe bar), a labeling check against a hand-constructed price
> path with a known TP/SL outcome, and a full train/val/test run whose test
> AUC came out ≈0.50 on pure random-walk data — exactly what "no leakage"
> looks like, since real leakage would show up as suspiciously *high* AUC
> on data with no actual signal in it. `mt5_data.py` itself (the real MT5
> IPC calls) could not be tested — no Windows machine or MT5 terminal
> exists in this environment — same caveat as `bridge.py`. `add-kronos.ps1`
> was reviewed the same way as every other script in this project (checked
> for balanced braces/parens, matches the exact Scheduled Task pattern
> already field-verified in `mt5-bridge/`) but likewise not executed.
> Confirm it against your own broker/terminal before trusting a trained
> model.

## How the pieces fit together

```
mt5_data.py  (MT5 -> chunked OHLC download, Windows-only)
     |
     v
features.py  (indicators, pure pandas — testable anywhere)
     |
     v
labels.py    (TP-before-SL outcome labels, only place that looks forward)
     |
     v
train.py     (chronological split + LightGBM -> kronos_model.txt)
     |
     v
infer.py     (loads the model, polls live bars, predicts, publishes)
     |
     v
publish_signal.py  (writes one row to Supabase's `signals` table)
     |
     +--> Tilly's Signals page (web/src/app/signals/page.tsx) reads it live
     |
     +--> backend/app/services/signal_gate.py — a bot with require_signal
          set checks the latest row here before opening a position
          (backend/app/bots/grid_bot.py, dca_bot.py)
```

## Setup: on the shared VPS (recommended, scripted)

Kronos runs on the same Windows VPS as your MT5 bridge clients
(`../mt5-bridge/`), not a separate machine — it just needs its own isolated
MT5 terminal copy, same reasoning as `add-client.ps1`: `MetaTrader5` can
only attach to one terminal per process, so Kronos's process and a client's
`bridge.py` process each need their own terminal instance to avoid
colliding on the same IPC channel (a race that a lock *inside* one process,
like `bridge.py`'s own `_mt5_lock`, can't prevent across two processes).

1. **Run `../mt5-bridge/bootstrap-vps.ps1` first** if you haven't on this
   VPS — installs Python. Kronos needs no Cloudflare tunnel (unlike a
   bridge, nothing needs to reach it from the internet — it only makes
   outbound calls to MT5 locally and to Supabase).
2. **Copy this `kronos/` folder onto the VPS** (alongside `mt5-bridge/`).
3. Run, as Administrator:
   ```powershell
   .\add-kronos.ps1 -Mt5Login "414312080" -Mt5Password "..." -Mt5Server "Exness-MT5Real8" -MasterTerminalDir "C:\MT5-Master-Exness" -SupabaseUrl "https://vvkddynlfgilymzvugfo.supabase.co" -SupabaseServiceRoleKey "paste-the-service-role-secret-here"
   ```
   The MT5 login can be the same one a client's bridge already uses —
   Kronos only reads candle history, never places orders, and its own
   terminal copy keeps it off that bridge's IPC channel regardless. This
   installs dependencies, clones an isolated terminal copy, and registers
   (but does not start) a Scheduled Task for live inference.
4. **Train a model** — a one-off, interactive step the script deliberately
   doesn't run for you (it prints the exact command with your paths filled
   in at the end): read the printed test AUC/accuracy before trusting it
   with anything. **A model this simple (single chronological split, no
   walk-forward, no realistic backtest with spread/slippage) is a first
   checkpoint, not something to trade real money on** — see "What's not
   built yet" below.
5. **Start live inference** once a model file exists:
   `Start-ScheduledTask -TaskName "TillyKronosInfer"`.
6. **Check the Tilly app's Signals tab** — it reads directly from the
   `signals` table, so a successful publish shows up there within its
   15-second poll, no backend/redeploy needed.
7. Same rule as every Scheduled Task on this VPS: **disconnect your RDP
   client afterwards, don't log off** — logging off ends the session every
   task on the box (bridges, tunnels, and now Kronos) runs inside.

## Setup: standalone machine (manual)

If Kronos runs somewhere other than the shared VPS, or you want to
understand what `add-kronos.ps1` automates:

1. Install MetaTrader 5 and log in to your broker account (demo first).
2. `pip install -r requirements.txt`
3. Train: `python train.py --symbol XAUUSDm --timeframe M5 --bars 50000 --side BUY --tp 3.0 --sl 2.0 --out kronos_model.txt`
   — chunked download avoids the notes' "Invalid params" 100k-bar bug.
4. Set credentials: `$env:SUPABASE_URL = "..."`, `$env:SUPABASE_SERVICE_ROLE_KEY = "..."`.
5. Run inference: `python infer.py --model kronos_model.txt --symbol XAUUSDm --timeframe M5 --poll-seconds 60`
   — keep it running the same way as `bridge.py` (Task Scheduler,
   `-LogonType Interactive`; MT5's IPC only works inside a real desktop
   session).

## The `signals` table

Schema and RLS: `tilly-trading/supabase/migrations/0007_signals.sql`.
Shared/market-wide, not scoped to any one user (a symbol's forecast is the
same for everyone) — readable by anyone, but only the service_role key can
write, so `publish_signal.py`'s key must never end up in the Tilly frontend
or backend or get committed anywhere.

## What's not built yet (see the notes' own phased roadmap)

- **Walk-forward validation** (retraining across multiple rolling windows)
  — this is a single chronological split, Phase 1/2 of the notes, not
  Phase 5.
- **A realistic backtester** with spread/slippage/commission, drawdown,
  Sharpe/Sortino, expectancy — `train.py` only reports classification
  metrics (AUC, accuracy), which the notes explicitly warn isn't enough:
  "A model can have good classification accuracy and still lose money
  after spread, slippage, commissions and bad risk management."
- **Multi-timeframe features** — `features.merge_higher_timeframe()` exists
  and is tested, but `train.py`/`infer.py` don't call it yet; they train on
  one timeframe's own indicators only.
- ~~**Bot-side gating**~~ — done: a bot opts in with `require_signal: true`
  in its parameters (a checkbox on the New Bot page), and only then checks
  `app/services/signal_gate.py` before opening a position — GRID before
  arming its ladder (side=None: any non-NO_TRADE signal unblocks, since
  GRID trades both directions at once), DCA before each entry (side=BUY,
  since it's directional). Every bot that doesn't set `require_signal`
  behaves exactly as before this existed — verified with a regression test
  proving the ungated path is untouched, plus tests for the gated wait/arm
  behavior, against a real (in-memory) database, not mocks.
- **The trade-quality / expected-movement models** from the notes'
  three-model architecture — this is the single TP-before-SL direction
  model only (Model 3 from the notes, doing double duty).
