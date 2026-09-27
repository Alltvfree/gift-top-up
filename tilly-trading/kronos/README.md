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
> `labels.py`, `train.py`'s chronological split/training loop, and the
> entire `backtest/` package have no MT5 dependency and are verified
> end-to-end against synthetic OHLC data by a committed pytest suite
> (`kronos/tests/` — run `pip install -r requirements.txt && pytest` from
> inside `kronos/`; 75 tests as of this writing): no-lookahead checks
> (truncating future bars doesn't change past feature values), a
> multi-timeframe merge check (never attaches a still-forming
> higher-timeframe bar — see "Leakage audit" below), a labeling check
> against hand-constructed price paths with known TP/SL outcomes, a full
> train/val/test run whose test AUC came out ≈0.50 on pure random-walk data
> (exactly what "no leakage" looks like — real leakage would show up as
> suspiciously *high* AUC on data with no actual signal in it), and the
> realistic execution simulator's cost/TP-SL/position-sizing math against
> known-outcome price paths. `mt5_data.py` itself (the real MT5 IPC calls)
> could not be tested — no Windows machine or MT5 terminal exists in this
> environment — same caveat as `bridge.py`. `add-kronos.ps1` was reviewed
> the same way as every other script in this project (checked for balanced
> braces/parens, matches the exact Scheduled Task pattern already
> field-verified in `mt5-bridge/`) but likewise not executed. Confirm it
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
     +--> backtest/ (Phase 3 — walk-forward retraining + realistic
     |     execution simulation -> reports/<timestamp>/report.html;
     |     see "Phase 3 — the realistic walk-forward backtester" below)
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
3. Train BOTH sides — two separate models, not one model whose complement
   stands in for the other direction (see infer.py's module docstring for
   why that broke a real backtest):
   `python train.py --symbol XAUUSDm --timeframe M5 --bars 50000 --side BUY --tp 3.0 --sl 2.0 --out kronos_model_buy.txt`
   `python train.py --symbol XAUUSDm --timeframe M5 --bars 50000 --side SELL --tp 3.0 --sl 2.0 --out kronos_model_sell.txt`
   — chunked download avoids the notes' "Invalid params" 100k-bar bug.
4. Set credentials: `$env:SUPABASE_URL = "..."`, `$env:SUPABASE_SERVICE_ROLE_KEY = "..."`.
5. Run inference: `python infer.py --model-buy kronos_model_buy.txt --model-sell kronos_model_sell.txt --symbol XAUUSDm --timeframe M5 --poll-seconds 60`
   — keep it running the same way as `bridge.py` (Task Scheduler,
   `-LogonType Interactive`; MT5's IPC only works inside a real desktop
   session).

## The `signals` table

Schema and RLS: `tilly-trading/supabase/migrations/0007_signals.sql`.
Shared/market-wide, not scoped to any one user (a symbol's forecast is the
same for everyone) — readable by anyone, but only the service_role key can
write, so `publish_signal.py`'s key must never end up in the Tilly frontend
or backend or get committed anywhere.

## Phase 3 — the realistic walk-forward backtester

`backtest/` answers the question `train.py`'s single AUC number can't:
does this model make money after real trading costs, evaluated the way a
live system would actually see the data (chronologically, retrained
forward through time, never peeking at a test period while building the
model that gets scored on it)?

```
mt5_data.py -> backtest/__main__.py (CLI)
                    |
                    v
              backtest/windows.py       (rolls [train][embargo][val][embargo][test] forward)
                    |
                    v
              backtest/walk_forward.py  (per window: trains a BUY model AND a SELL model,
                    |                    each frozen and predicting only that window's own test rows)
                    v
              backtest/simulator.py     (next-bar entry, bid/ask spread+slippage, TP/SL,
                    |                    same-bar-both-hit policy, cooldown, position sizing)
                    v
              backtest/metrics.py + report.py -> reports/<timestamp>/report.html + CSVs
```

Run it from inside `kronos/`:

```powershell
python -m backtest --symbol BTCUSDm --config config/backtest.toml --quick   # fast smoke test, ~6k bars
python -m backtest --symbol BTCUSDm --config config/backtest.toml --full    # full walk-forward, config's own window sizes
python -m backtest --symbol XAUUSDm --config config/backtest_xauusd.toml --full
```

(Not `backtest.py` — a same-named script and package can't coexist cleanly
in one directory, and `-m` is the unambiguous way to run a package as an
entrypoint. See `backtest/__main__.py`'s own docstring.)

**Execution convention** (documented explicitly, not left implicit — this
matters because it's easy to get backwards): a signal is computed from a
bar's own close, but the trade enters at the *next* bar's open
(`execution.next_bar: true`, the only realistic setting) — a live system
cannot act on a candle's close the instant it prints. Spread is charged
once, at entry (crossing the bid/ask on a market order); a TP/SL exit is
modeled as a resting order triggered at its exact level plus slippage only
(no second spread charge — this matches how MT5 accounts for stop/limit
exits); a `TIME_EXIT`/`END_OF_TEST` close is a market order and does cross
the spread again. If both TP and SL are reachable within the same bar
(OHLC only, no tick data), `same_bar_exit_policy: conservative` (the
default) assumes the stop-loss happened first.

**Two independent models, not one model's complement** — a real BTCUSDm
`--full` run against live MT5 history caught this the hard way. The first
working version of this backtester trained a single BUY-side model and
treated a low BUY probability as a SELL signal (`sell_threshold` as
`1 - buy_threshold` on one probability — inherited from `infer.py`'s
original live-inference convention). Result: 643 trades, 641 of them SELL,
net -$2,414 (-24%) on $10,000, 44% max drawdown. The overall AUC (0.542)
looked like a normal weak-but-real edge, which made it easy to miss that
almost the entire result was actually testing an assumption — "the market
probably won't let a BUY win" — that had never itself been trained or
validated, since a SELL trade's real outcome depends on different TP/SL
price levels entirely. Per-window, one bad regime (AUC 0.516, the weakest
of four windows) produced 251 of the 643 trades and accounted for nearly
all of the loss; the other three windows roughly netted to breakeven.

Fixed by training two separate models per window — `label_tp_before_sl`
already supported `side="BUY"`/`side="SELL"` as two distinct targets, just
never both at once — sharing one feature computation (features don't
depend on side, only the label does) but with fully independent
train/validate/freeze/predict cycles and independent thresholds
(`signal.buy_threshold` / `signal.sell_threshold`, both default 0.60 now,
each gating its own model — see `backtest/signal_engine.py`'s module
docstring). `infer.py` (live inference) got the same fix: it now loads
`--model-buy` and `--model-sell` and predicts both, rather than one model
standing in for both directions. The report's Model Metrics section shows
each side's AUC/accuracy/confusion matrix separately for exactly this
reason — a single blended number would hide precisely the kind of
imbalance that caused this.

**Leakage audit**: every backtest run re-verifies, independently of
`features.merge_higher_timeframe`'s own (already-fixed) logic, that no
attached higher-timeframe bar could see information from before it
actually closed (`backtest/leakage_audit.py`) — this is exactly the bug
this project already found and fixed once (the 0.7704 → 0.5317 AUC story
above). A regression test
(`tests/test_walk_forward.py::test_corrupted_merge_is_caught_by_the_runtime_leakage_audit`)
deliberately reintroduces the old naive merge and proves the audit stops
the run rather than silently producing an inflated AUC again. The full
audit table (which categories were checked, and why each one is safe) is
in every report's own "Leakage Audit" section — including *why* feature
scaling isn't a checked category here: LightGBM is tree-based and splits
on raw values, so there's no fitted scaler to leak train-set statistics
through in the first place.

**What it does NOT (yet) do**, so nobody mistakes an MVP for the whole
spec: TP/SL as an ATR multiple (only fixed points/price distances are
implemented — a symbol-appropriate fixed distance is what every real
training run in this file has used so far anyway); trailing stops or
break-even moves (the current strategy doesn't use them, and the project's
own instruction was "don't enable advanced features unless the current
strategy already uses them"); a historical bid/ask spread mode beyond
MT5's own recorded per-bar `spread` column (which is real data, and is the
default — `spread.mode: historical`). All three are additive, not
architectural, follow-ups.

**Tested against synthetic data** (`kronos/tests/`, run with `pytest` from
inside `kronos/`): 86 tests covering every module — no-lookahead checks on
`features.py`/`train.py` (now actually committed here, not just run ad hoc
during development), hand-constructed price paths with known TP/SL
outcomes through the realistic execution simulator (spread/slippage/
commission math, same-bar policy, cooldown, position sizing, time exits,
end-of-test handling), a dedicated check that a low BUY probability alone
never opens a SELL (the exact bug above), the walk-forward window
generator's chronological non-overlap guarantees, the leakage-audit
regression test above, and a full end-to-end walk-forward run producing a
real HTML report. Like every other file in this project,
`backtest/__main__.py`'s actual MT5 download step has not been run against
a live terminal in this repo's own CI — it has, however, now been run for
real against live BTCUSDm history on the project's own VPS (see the
BUY/SELL story above) — confirm each new symbol/config combination's first
`--quick` run before trusting a `--full` one.

## What's not built yet (see the notes' own phased roadmap)

- **Walk-forward validation** (retraining across multiple rolling windows)
  — this is a single chronological split, Phase 1/2 of the notes, not
  Phase 5.
- ~~**A realistic backtester**~~ — done: see "Phase 3 — the realistic
  walk-forward backtester" below. `train.py`'s own AUC/accuracy were never
  enough on their own — "A model can have good classification accuracy and
  still lose money after spread, slippage, commissions and bad risk
  management" (the notes' own warning) — the backtester is what actually
  answers the money question, not just the classification one.
- ~~**Multi-timeframe features**~~ — done: `train.py --higher-timeframe H1`
  (or any timeframe) merges that timeframe's own features in via
  `features.merge_higher_timeframe`, auto-computing how much higher-
  timeframe history to download (`mt5_data.bars_to_cover_same_span`) so the
  span matches the base timeframe's. `infer.py` takes the same
  `--higher-timeframe` flag and must be given the same one used at
  training time, or `predict()` fails loudly on a missing column rather
  than silently mispredicting. Verified end-to-end against synthetic data:
  no lookahead through the *full* pipeline (not just the merge function in
  isolation), `model.feature_name()` matching what it was actually trained
  on, and `infer.latest_signal()` correctly fetching and merging both
  timeframes.
  
  First real result on live data, though: training BTCUSDm and XAUUSDm
  both properly-scaled (TP/SL sized to each symbol's actual price level,
  not copy-pasted dollar amounts) landed at `test_auc` ≈ 0.51 either way —
  indistinguishable from chance, and true of the single-timeframe model
  too. Multi-timeframe context is wired up and ready to test, but hasn't
  yet been the thing that moves this number — that's still an open
  question, not something this feature already answered.
- ~~**Bot-side gating**~~ — done: a bot opts in with `require_signal: true`
  and/or `avoid_news_minutes: 30` in its parameters (checkboxes on the New
  Bot page), and only then checks `BaseBot.entry_allowed()` before opening
  a position — GRID before arming its ladder (side=None: any non-NO_TRADE
  signal unblocks, since GRID trades both directions at once), DCA before
  each entry (side=BUY, since it's directional). Both checks are
  independent and additive — a bot can require a matching signal, avoid
  high-impact news, both, or neither. Every bot that opts into neither
  behaves exactly as before either gate existed — verified with a
  regression test proving the ungated path is untouched, plus tests for
  signal-only, news-only, and combined gating, against a real (in-memory)
  database, not mocks.
- **The `news_events` table has no automatic feed** —
  `tilly-trading/supabase/migrations/0008_news_events.sql` and
  `backend/app/services/news_filter.py` exist and are tested, but nothing
  populates the table yet; rows go in manually (or via a future script)
  using the service_role key. Wiring up a real economic-calendar API
  (several exist, free and paid) is a deliberate follow-up requiring a
  data-source decision, not something to guess at.
- **The trade-quality / expected-movement models** from the notes'
  three-model architecture — this is the single TP-before-SL direction
  model only (Model 3 from the notes, doing double duty).
- ~~**Real market structure**~~ — done: `features.py` now computes real
  support/resistance levels from confirmed swing highs/lows (not lookahead
  — a swing needs `SWING_LAG` bars on both sides before it counts, so the
  most recent bars' swing status is genuinely unconfirmed, same as a human
  reading a chart) and flags a breakout once price clears every recently
  tracked level. This is a different thing from an LLM reading news
  commentary and calling it "market structure" — see the LLM-narrative
  discussion below.

## On "reading the news like ChatGPT"

Asked to make Kronos "read the news and check structure like ChatGPT
does," worth being explicit about why that's not what got built. An
example ChatGPT response shown as a reference point had a take-profit
target *below* both the entry price and the stop-loss on a long position —
an internally inconsistent number, because the response wasn't computed
from real price data at all; it was ChatGPT summarizing what a couple of
news/analysis sites already said, with citations, dressed in signal
format. That's fundamentally different from what this file does: every
number Kronos outputs is computed from real OHLC history it downloaded
itself, by a model trained on actual trade outcomes with a test AUC you
can check. It's exactly what the project notes (also written with
ChatGPT's help) warned against: *"Do NOT start with a large LLM... the
most useful AI is a fast tabular ML model trained specifically on market
features and trading outcomes."*

If an LLM-generated narrative signal source is wanted anyway, clearly
labeled as unverified commentary and never a Kronos prediction, that's a
separate, deliberate follow-up — not something to fold into this file
silently.
