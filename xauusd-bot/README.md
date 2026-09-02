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

## MT5 setup (for DEMO/LIVE, Phase 3+)

1. Install the MetaTrader 5 terminal and log in to a **demo** account first.
2. In the terminal: *Tools → Options → Expert Advisors* → enable *Allow
   algorithmic trading*.
3. `pip install MetaTrader5` in the same Python environment.
4. Set `TRADING_MODE=DEMO` and `MT5_LOGIN/PASSWORD/SERVER` in `.env`.
5. The bot auto-detects the broker's XAUUSD symbol name (`XAUUSD`, `XAUUSDm`,
   `XAUUSD.a`, `GOLD`, …) from the configured candidate list.

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
