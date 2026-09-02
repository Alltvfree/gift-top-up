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
| 4 | Historical backtester, metrics, equity/drawdown curves | ⏳ Planned |
| 5 | Optimization, walk-forward, overfitting detection | ⏳ Planned |
| 6 | FastAPI + WebSocket + React/Next.js dashboard | ⏳ Planned |
| 7 | End-to-end integration | ⏳ Planned |

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
│   │   └── main.py        # runs one engine iteration (evaluate→risk→execute)
│   └── tests/             # pytest suite
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
Full PostgreSQL trade/equity history and the backtester come next.

```bash
cd xauusd-bot/backend
PYTHONPATH=. python -m app.main      # one PAPER engine iteration
```

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
