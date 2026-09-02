# XAUUSD MT5 Automated Trading Bot

A modular, testable automated trading system for **XAUUSD (Gold)** on
**MetaTrader 5**. The design goal is a robust, configurable bot that can be
thoroughly **backtested and demo-tested before any live use** — risk control,
execution reliability and reproducibility are prioritized over maximum returns.

> ⚠️ **Automated trading can lose money.** Past backtest performance does not
> guarantee future results. LIVE trading is disabled by default and requires
> explicit configuration plus in-app confirmation. Nothing in this project is a
> claim that the strategy is profitable.

---

## Build status — phased delivery

This project is built in phases (see the spec). **Phase 1 (foundation) is
complete and tested.**

| Phase | Scope | Status |
|------:|-------|--------|
| **1** | Project structure, config, logging, MT5 connection abstraction, XAUUSD symbol detection, market data, indicators (EMA/RSI/ATR), tests | ✅ Done |
| **2** | Strategy engine, BUY/SELL/WAIT signals, 0-100 scoring, ATR SL/TP, position sizing + per-trade risk gates | ✅ Done |
| **3** | Paper-trade execution, idempotent orders, candle dedup, position management (break-even + trailing), stateful daily limits, persistent emergency stop, trading engine | ✅ Done |
| **4** | Historical backtester (no look-ahead), full metrics, equity/drawdown curves, monthly/daily breakdowns, trading sessions, JSON/CSV reports | ✅ Done |
| **5** | Grid/random optimization, walk-forward (train/validation/OOS), overfitting detection (ROBUST/WARNING/HIGH RISK) | ✅ Done |
| **6** | FastAPI backend (all endpoints), WebSocket live updates, dark trading dashboard | ✅ Done |
| **7** | End-to-end integration: headless bot runner, Docker/compose, full-stack E2E test | ✅ Done |

**All 7 phases are complete.** 137 tests pass; everything except real
DEMO/LIVE order routing runs natively on Ubuntu with no MT5 terminal.

---

## Architecture

```
Web Dashboard (Phase 6)
        │
   Trading Engine (Phase 3)
        │
  ┌─────┼───────────────┐
Strategy   Risk      Market Data   ← Phase 2 / Phase 1
  └─────┼───────────────┘
     MT5 Adapter (interface)       ← Phase 1
        │
  MetaTrader 5 — XAUUSD
```

The application depends **only** on the abstract `MT5Adapter` interface, never on
the `MetaTrader5` package directly. That isolation lets the entire system run and
be tested on any OS through a **mock adapter** (synthetic data), and swaps in the
real terminal for DEMO/LIVE without touching strategy or risk code.

### Project layout (current)

```
xauusd-bot/
├── backend/
│   ├── app/
│   │   ├── core/          # config, logging, domain models (incl. Signal)
│   │   ├── indicators/    # EMA, RSI, ATR
│   │   ├── mt5/           # adapter interface, mock + real adapters, market data
│   │   ├── strategies/    # Strategy interface + XAUUSD_TrendPullback_v1
│   │   ├── risk/          # SL/TP, position sizing, risk manager, governor
│   │   ├── execution/     # brokers (paper/MT5), engine, position management
│   │   ├── backtesting/   # bar-based backtester, metrics, reports
│   │   ├── optimization/  # grid/random search, walk-forward, overfitting
│   │   ├── api/           # FastAPI app, BotService, WebSocket, ASGI entry
│   │   └── main.py        # runs one engine iteration (evaluate→risk→execute)
│   └── tests/             # pytest suite
├── frontend/index.html    # dark trading dashboard (no build step)
├── scripts/               # run_backtest / run_optimization / run_bot
├── docker/Dockerfile      # API/dashboard image
├── docker-compose.yml     # local stack (PAPER by default)
├── config/config.yaml     # strategy / risk parameters (no secrets)
├── .env.example           # environment template (copy to .env)
├── requirements.txt
└── pytest.ini
```

### Strategy — `XAUUSD_TrendPullback_v1` (Phase 2)

A modular, fully-configurable trend-pullback strategy. Every parameter lives in
`config.yaml`; nothing is hard-coded in the engine.

* **H1 trend bias** — `EMA50 vs EMA200` + price vs `EMA50` → BULLISH / BEARISH /
  NO_TREND. No trade unless the higher-timeframe trend is clear.
* **M15 setup** — higher-low / lower-high structure + a pullback toward EMA-fast
  (within a configurable ATR distance), with a volatility (ATR) gate.
* **M5 entry** — candle + short-EMA momentum and an RSI band check.
* **Score (0-100)** — weighted `trend 30 / structure 25 / pullback 20 /
  momentum 15 / rsi 10`; a trade is proposed only when
  `score >= min_score` **and** spread is acceptable.
* **Output** — every evaluated bar yields a fully-explained `Signal`
  (BUY/SELL/WAIT) with entry, ATR-based SL, RR-based TP, per-component score
  breakdown, indicator values, a human-readable reason, and a unique signal id.

**Risk engine.** ATR-scaled stop-loss (never a fixed dollar value), risk/reward
take-profit, and percentage-of-equity position sizing that clamps to the
broker's lot rules and **rounds down** so the configured risk % is never
exceeded. The `RiskManager` is the single gate every actionable signal must pass
(actionable + has SL, spread OK, position count OK, sizable within budget).

> These thresholds are a configurable starting point, **not** proven-profitable
> settings — see the safety principles below.

### Execution & safety (Phase 3)

The `TradingEngine` runs one deterministic iteration — *evaluate → risk gate →
execute → manage positions* — with the protections that make it safe to leave
running:

* **Paper broker** — a fully simulated broker fills orders at the tick (with
  configurable slippage/commission), marks positions to market, and auto-closes
  on SL/TP. It is the source of truth for the simulated PAPER account. DEMO/LIVE
  swap in the real MT5 broker behind the same interface.
* **Idempotent orders** — every order is keyed by `signal_id`; a retry or
  duplicate signal never opens a second position.
* **Candle dedup** — a completed entry-timeframe candle is evaluated exactly
  once (no repeat entries on the same bar, no look-ahead).
* **Stateful risk governor** — daily-loss `STOP_TRADING`, account-drawdown
  disable, max-trades-per-day, post-trade cooldown, consecutive-loss tracking.
* **Position management** — break-even (move SL to entry ± buffer at +1R) and
  ATR trailing stop, both **forward-only** (a stop never moves backward).
* **Emergency stop** — persisted to disk (JSON state), survives restart, and
  optionally flattens open positions.

State (emergency stop, daily counters, candle markers, open-trade metadata) is
persisted every iteration to `data/bot_state.json`, so a restart resumes safely.

```bash
cd xauusd-bot/backend
PYTHONPATH=. python -m app.main      # one PAPER engine iteration
```

### Backtesting (Phase 4)

A bar-based backtester replays the entry timeframe and, at each completed bar,
rebuilds the higher-timeframe views from **only the candles that had closed by
that moment** — so the strategy never sees the future (spec §§18,37). It reuses
the same strategy, sizing, SL/TP and break-even/trailing logic as live, and
honors costs (commission/slippage), daily-loss limits, cooldown and trading
sessions. Intrabar SL/TP fills use each bar's high/low; when a bar touches both,
the **stop is assumed hit first** (worst case).

Metrics (spec §21): total/win/loss, win rate, net/gross profit, profit factor,
average win/loss/trade, max drawdown, Sharpe & Sortino (per-trade, not
annualized), expectancy (currency and R), longest win/loss streaks — plus equity
& drawdown curves, monthly/daily performance, and an R-multiple trade
distribution. Reports export to JSON and CSV.

```bash
cd xauusd-bot
python scripts/run_backtest.py       # demo on SYNTHETIC data
```

> The demo runs on synthetic random data and will not be profitable — that is
> the point. It proves the mechanics; it makes **no** profitability claim. Feed
> real historical candles for a meaningful backtest, then validate out-of-sample
> and on a demo account before risking capital.

### Optimization & walk-forward (Phase 5)

Grid and random search over a parameter space (dotted config paths like
`take_profit.risk_reward`), each candidate scored by a configurable objective
(net profit, profit factor, expectancy, Sharpe) with a **minimum trade count** so
a 2-trade fluke can't win. Every result is saved.

**Walk-forward** splits history into consecutive train → validation →
out-of-sample windows; parameters are optimized on TRAIN only, checked on
VALIDATION, and measured on OUT-OF-SAMPLE data never used for selection (spec
§22). Each fold is graded by the **overfitting detector**
(`ROBUST` / `WARNING` / `HIGH OVERFITTING RISK`) which flags extreme returns,
thin trade counts, excessive drawdown, and train→validation→OOS degradation.
The system **never auto-deploys** an optimized strategy to live trading.

```bash
cd xauusd-bot
python scripts/run_optimization.py   # grid search + walk-forward demo
```

> **Backtest performance:** the per-bar indicator window is capped so a backtest
> is ~O(n) rather than O(n²), keeping multi-thousand-bar runs and optimization
> sweeps tractable. The window is several multiples of the longest indicator, so
> values match full-history indicators for practical purposes.

### API + dashboard (Phase 6)

A FastAPI backend exposes the endpoints from spec §30 and pushes live snapshots
over a WebSocket; a background loop ticks the trading engine on an interval (idle
until you start the bot).

```bash
cd xauusd-bot/backend
PYTHONPATH=. uvicorn app.api.asgi:app --host 0.0.0.0 --port 8000
# open http://localhost:8000  ->  dark trading dashboard
```

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/status` | mode, running, connection, emergency stop |
| GET | `/api/account` | balance / equity / margin |
| GET | `/api/market/xauusd` | bid/ask/spread, trend, current signal + score |
| GET | `/api/positions` | open positions |
| GET | `/api/trades` | recent closed trades |
| GET | `/api/signals` | recent signals |
| GET | `/api/performance` | win rate, P/L, today's stats |
| GET | `/api/equity` | equity snapshots |
| GET | `/api/chart` | price + EMA overlay |
| POST | `/api/bot/start` | start (LIVE requires `{"confirm":"ENABLE LIVE TRADING"}`) |
| POST | `/api/bot/stop` | stop |
| POST | `/api/bot/emergency-stop` | halt new trades (optionally flatten) |
| POST | `/api/bot/resume` | clear emergency stop |
| POST | `/api/settings` | update risk / min-score at runtime |
| POST | `/api/backtest` | run a backtest, return the full report |
| POST | `/api/optimization` | run a small grid search |
| WS | `/ws` | live snapshot stream |

The dashboard (`frontend/index.html`) is a dependency-free dark UI: status pills,
stat cards (balance/equity/today's P/L/trades/price/spread), the live signal with
score + reason, open positions, recent signals, an equity curve and a price chart
with EMA overlay, and Start / Stop / **Emergency Stop** controls. LIVE mode shows
a warning banner and requires typing the confirmation phrase before starting.

> **Dashboard note:** this is a served single-page app (vanilla JS + WebSocket),
> chosen so it runs on a headless Ubuntu server with **zero npm/build step**. A
> React/Next.js version can consume the same API unchanged.

### Integration & deployment (Phase 7)

**Headless runner** (no dashboard) — runs the engine loop directly:

```bash
cd xauusd-bot
python scripts/run_bot.py               # PAPER, ticks every 5s
BOT_TICK_SECONDS=2 python scripts/run_bot.py
```

**Docker** — API + dashboard, PAPER by default:

```bash
cd xauusd-bot
cp .env.example .env
docker compose up --build               # -> http://localhost:8000
```

The image is Linux, so it runs PAPER/BACKTEST out of the box. For DEMO/LIVE,
run the `mt5linux` Wine bridge on the host and set `MT5_USE_LINUX_BRIDGE=true`
plus `MT5_BRIDGE_HOST=host.docker.internal` in `.env`.

---

## ⚠️ Enabling LIVE trading — read this

```
WARNING

Automated trading can lose money.
Past backtest performance does not guarantee future results.

LIVE TRADING requires explicit confirmation.
```

LIVE is gated three ways, on purpose:

1. `TRADING_MODE=LIVE` **and** `BOT_ALLOW_LIVE=true` in `.env` (the app refuses
   to start LIVE without the second flag).
2. Starting the bot via the API/dashboard requires the phrase
   `ENABLE LIVE TRADING` (the dashboard prompts for it and shows a warning
   banner); the headless runner requires `RUN_BOT_CONFIRM_LIVE='ENABLE LIVE
   TRADING'`.
3. The emergency stop is always available and persists across restarts.

**Do not enable LIVE until you have:** run a meaningful backtest on *real*
historical data, validated out-of-sample and via walk-forward (checking the
overfitting grade), and forward-tested on a **demo** account. The bundled
strategy parameters are a starting point, not proven-profitable settings.

---

## Final deliverables checklist

| # | Deliverable | Where |
|---|-------------|-------|
| 1 | Complete source code | `backend/app/`, `frontend/` |
| 2 | MT5 integration (real + mock, Ubuntu bridge) | `app/mt5/` |
| 3 | Trading strategy (`XAUUSD_TrendPullback_v1`) | `app/strategies/` |
| 4 | Risk engine (sizing, SL/TP, governor, sessions) | `app/risk/` |
| 5 | Paper trading + execution engine | `app/execution/` |
| 6 | Backtesting engine + metrics + reports | `app/backtesting/` |
| 7 | Optimization + walk-forward + overfitting | `app/optimization/` |
| 8 | Operational state persistence (JSON) | `app/core/state.py` |
| 9 | FastAPI backend | `app/api/` |
| 10 | Web dashboard | `frontend/index.html` |
| 11 | Docker configuration | `docker/`, `docker-compose.yml` |
| 12 | `.env.example` | `./.env.example` |
| 13 | Automated tests (137) | `backend/tests/` |
| 14–18 | README + install / MT5 / backtest / demo instructions | this file |

> **Scope note:** operational state (emergency stop, daily counters, candle
> dedup, open-trade metadata) uses an atomic JSON store — enough to run and
> restart safely with no external database. A PostgreSQL history layer for
> long-term trade/equity records is scaffolded in `docker-compose.yml`
> (commented) and is the one spec item intentionally left as an optional add-on.

---

## Installation

Requires **Python 3.11+**.

```bash
cd xauusd-bot
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # then edit .env
```

`MetaTrader5` is **not** installed by `requirements.txt` because it is
Windows-only. Install it separately on the Windows host that will run DEMO/LIVE:

```bash
pip install MetaTrader5
```

---

## Configuration

Two layers, kept strictly separate:

* **Secrets & runtime** (`.env`) — trading mode, MT5 credentials, DB URL. Never
  committed; `.env` is git-ignored.
* **Strategy & risk** (`config/config.yaml`) — all indicator, risk, SL/TP,
  session parameters. No credentials.

Key `.env` settings:

| Variable | Purpose | Default |
|----------|---------|---------|
| `TRADING_MODE` | `BACKTEST` \| `PAPER` \| `DEMO` \| `LIVE` | `PAPER` |
| `BOT_ALLOW_LIVE` | Must be `true` for LIVE to be accepted | `false` |
| `MT5_LOGIN` / `MT5_PASSWORD` / `MT5_SERVER` | Terminal login (DEMO/LIVE only) | — |
| `MT5_TERMINAL_PATH` | Path to `terminal64.exe` (optional) | auto-detect |

**LIVE safety gate:** starting with `TRADING_MODE=LIVE` while `BOT_ALLOW_LIVE`
is not `true` raises an error rather than trading — the operator's intent is
never ambiguous.

---

## Running the Phase 1 foundation check

Verifies connection, account info, XAUUSD symbol detection, market data and
indicator calculations end-to-end. In `PAPER`/`BACKTEST` it uses the mock
adapter (synthetic data) so it runs anywhere.

```bash
cd xauusd-bot/backend
PYTHONPATH=. python -m app.main
```

Expected output is a series of structured log lines
(`MT5_CONNECTED`, `SYMBOL_RESOLVED`, `TICK`, `INDICATORS`, …).

---

## Platform support — important

The official **`MetaTrader5` Python package is Windows-only**. What runs where:

| Mode | Windows | **Ubuntu / Linux** | macOS |
|------|:------:|:------:|:-----:|
| `BACKTEST` / `PAPER` (mock adapter) | ✅ native | ✅ **native** | ✅ native |
| Test suite, indicators, config, logging | ✅ | ✅ **native** | ✅ |
| `DEMO` / `LIVE` (real terminal) | ✅ native | ✅ via **Wine + `mt5linux` bridge** | ⚠️ Wine (unsupported) |

So on your **Ubuntu server** everything except real DEMO/LIVE runs natively with
zero extra setup. Real trading needs the Wine bridge below.

## Running on Ubuntu / Linux

**PAPER / BACKTEST / development** — nothing special, works out of the box:

```bash
cd xauusd-bot
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m pytest
cd backend && PYTHONPATH=. python -m app.main      # PAPER mode, mock adapter
```

**DEMO / LIVE on Ubuntu** — the MT5 terminal is a Windows app, so run it under
**Wine** and bridge it to native Python with [`mt5linux`](https://pypi.org/project/mt5linux/):

1. Install Wine and the MetaTrader 5 terminal:
   ```bash
   sudo dpkg --add-architecture i386 && sudo apt update
   sudo apt install -y wine64 wine32 winbind xvfb
   # download & run the broker's MT5 installer under Wine:
   wine mt5setup.exe
   ```
   Log in to a **demo** account in the terminal, and enable
   *Tools → Options → Expert Advisors → Allow algorithmic trading*.
2. Install a **Windows** Python inside the same Wine prefix, then in it:
   ```bash
   wine python -m pip install MetaTrader5 mt5linux
   ```
3. Install the bridge in your **native** Linux venv and start the RPC server
   (it launches the Wine-side Python and listens on port 18812):
   ```bash
   pip install mt5linux
   python -m mt5linux --host 0.0.0.0 -p 18812 <path-to-wine-python.exe>
   ```
   On a headless server wrap the terminal with `xvfb-run` so it has a display.
4. Point the bot at the bridge in `.env`:
   ```ini
   TRADING_MODE=DEMO
   MT5_USE_LINUX_BRIDGE=true
   MT5_BRIDGE_HOST=localhost
   MT5_BRIDGE_PORT=18812
   MT5_LOGIN=...     MT5_PASSWORD=...     MT5_SERVER=...
   ```

The bot's `MT5Adapter5` automatically uses the bridge when
`MT5_USE_LINUX_BRIDGE=true`; the adapter API is identical, so no strategy/risk
code changes. It auto-detects the broker's XAUUSD symbol name (`XAUUSD`,
`XAUUSDm`, `XAUUSD.a`, `GOLD`, …) from the configured candidate list.

> **Tip:** run the bot itself as a `systemd` service and the Wine bridge as a
> second service so both restart on reboot. Keep the terminal on a **demo**
> account until you have completed backtesting and forward-testing.

### MT5 setup on Windows (alternative)

If you instead run on Windows: install the terminal, log in to a demo account,
enable algorithmic trading, `pip install MetaTrader5`, set `TRADING_MODE=DEMO`
and the `MT5_*` credentials — leave `MT5_USE_LINUX_BRIDGE=false`.

---

## Testing

```bash
cd xauusd-bot
python -m pytest            # or: pytest --cov=backend/app
```

The suite covers indicator calculations, configuration + the LIVE gate,
structured logging, the mock adapter (determinism, unusual symbol profiles,
symbol resolution) and the market-data service. Tests require **no** MT5
terminal.

---

## Trading-safety principles (enforced throughout)

* Default mode is **PAPER**; LIVE requires an explicit gate + confirmation.
* Never present synthetic/mock data as real market data.
* No claim of profitability without statistical evidence.
* No look-ahead: the real adapter reads only **completed** candles.
* Do not optimize against out-of-sample data (enforced from Phase 5).

---

## License / disclaimer

For educational and research use. Trading foreign exchange and commodities on
margin carries substantial risk. Use demo accounts and validate thoroughly
before risking capital.
