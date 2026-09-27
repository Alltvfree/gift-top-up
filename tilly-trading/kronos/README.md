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
> exists in this environment — same caveat as `bridge.py`. Confirm it
> against your own broker/terminal before trusting a trained model.

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
     v
Tilly's Signals page (web/src/app/signals/page.tsx) reads it live
```

## Setup

1. **Install MetaTrader 5** on a Windows machine/VPS and log in to your
   broker account (same as `mt5-bridge/`'s setup — demo account first).
2. `pip install -r requirements.txt`
3. **Train a model:**
   ```powershell
   python train.py --symbol XAUUSDm --timeframe M5 --bars 50000 --side BUY --tp 3.0 --sl 2.0 --out kronos_model.txt
   ```
   This downloads 50,000 bars (chunked automatically — the "Invalid params"
   bug from the notes is fixed by `mt5_data.py`'s `MAX_BARS_PER_REQUEST`
   chunking, not by guessing your broker's exact undocumented cap), builds
   features + TP-before-SL labels, does a 70/15/15 chronological
   train/val/test split, and prints test AUC/accuracy. **A model this
   simple (single chronological split, no walk-forward, no realistic
   backtest with spread/slippage) is a first checkpoint, not something to
   trade real money on** — see "What's not built yet" below.
4. **Set Supabase credentials** for publishing (get the service_role key
   from Supabase dashboard → Project Settings → API — not the anon key):
   ```powershell
   $env:SUPABASE_URL = "https://vvkddynlfgilymzvugfo.supabase.co"
   $env:SUPABASE_SERVICE_ROLE_KEY = "paste-the-service-role-secret-here"
   ```
5. **Run live inference:**
   ```powershell
   python infer.py --model kronos_model.txt --symbol XAUUSDm --timeframe M5 --poll-seconds 60
   ```
   Every cycle it fetches recent bars, predicts, and publishes to Supabase.
   Keep this running the same way as `bridge.py` (Task Scheduler,
   `-LogonType Interactive`, same Session-0-IPC reasoning documented in
   `mt5-bridge/README.md` — MT5's IPC only works inside a real desktop
   session).
6. **Check the Tilly app's Signals tab** — it reads directly from the
   `signals` table, so a successful publish shows up there within its
   15-second poll, no backend/redeploy needed.

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
- **Bot-side gating** — Tilly's GRID/DCA bots don't check `signals` before
  opening a position yet. That's a deliberate follow-up, not an oversight:
  wiring an AI signal into when a bot is *allowed* to open a real position
  is a live-trading-behavior change and deserves its own review, separate
  from just getting the forecast visible on the Signals page.
- **The trade-quality / expected-movement models** from the notes'
  three-model architecture — this is the single TP-before-SL direction
  model only (Model 3 from the notes, doing double duty).
