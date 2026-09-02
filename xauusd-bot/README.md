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
| 2 | Strategy engine, BUY/SELL/WAIT signals, scoring, SL/TP, risk engine | ⏳ Planned |
| 3 | Paper trading, order execution, duplicate protection, position management, break-even, trailing stop, daily limits | ⏳ Planned |
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
│   │   ├── core/          # config, logging, domain models
│   │   ├── indicators/    # EMA, RSI, ATR
│   │   ├── mt5/           # adapter interface, mock + real adapters, market data
│   │   └── main.py        # Phase 1 foundation smoke check
│   └── tests/             # pytest suite
├── config/config.yaml     # strategy / risk parameters (no secrets)
├── .env.example           # environment template (copy to .env)
├── requirements.txt
└── pytest.ini
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
