# Tilly MT5 Bridge

A small HTTP service that lets the Tilly backend trade through a **real MT5
account** without MetaAPI. It's the `self_hosted` connection provider
(`backend/app/broker/mt5_bridge_client.py` on the backend side).

## Why this exists, and why it has to run on Windows

MetaTrader 5 has no official retail REST API — that's the entire reason
MetaAPI exists and charges for it. The only official programmatic access is
the `MetaTrader5` Python package, and it only works **on the same Windows
machine as a running, logged-in MT5 terminal** (it talks to the terminal
over local IPC, not a network protocol). There's no way around that from
Linux; this bridge is the one piece of Tilly Trading that has to live on
Windows.

> **Built but not run.** This file was written and syntax-checked, but
> never executed against a real MT5 terminal — that requires a Windows
> machine this environment doesn't have. Test it yourself against a demo
> account before pointing a live bot at it, and read `bridge.py` before you
> trust it with real money.

## What it does

Exposes 8 small endpoints (account info, price, positions, place/close/cancel)
that map 1:1 onto the same `BrokerClient` contract MetaAPI and the paper
provider already implement — so once it's linked, GRID/DCA bots, the engine,
and the dashboard work identically, no matter which provider is behind them.

## Setup

1. **Install MetaTrader 5**, log in to your broker account (start with a
   **demo** account), and leave the terminal open. "Algo Trading" must be
   enabled in the terminal (top toolbar) or `order_send` calls are rejected.

2. **Python 3.10+ on that same Windows machine**, then:
   ```powershell
   pip install -r requirements.txt
   ```

3. **Pick an API key** — any long random string, e.g.:
   ```powershell
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

4. **Run it:**
   ```powershell
   $env:MT5_BRIDGE_API_KEY = "paste-your-key-here"
   uvicorn bridge:app --host 0.0.0.0 --port 8787
   ```
   By default it attaches to whatever account is already logged in to the
   terminal. To have it log in itself instead, also set `MT5_LOGIN`,
   `MT5_PASSWORD`, `MT5_SERVER` (and `MT5_PATH` if `terminal64.exe` isn't on
   your `PATH`) before starting it.

5. **Expose it over HTTPS.** Render (or wherever the backend runs) needs to
   reach this over the internet. A Cloudflare Tunnel is free, needs no
   port-forwarding or static IP, and matches the rest of this project's
   stack:
   ```powershell
   cloudflared tunnel --url http://localhost:8787
   ```
   This prints a `https://<random>.trycloudflare.com` URL. That URL (a
   fresh one each run, unless you set up a named tunnel) plus your API key
   is what you enter as the MT5 bridge account on the Tilly **Account**
   page. Any other HTTPS tunnel (ngrok, a real reverse proxy on a VPS with a
   domain) works the same way — the backend just needs a reachable HTTPS URL.

6. **Link it in Tilly** — Account page → **+ MT5 BRIDGE** → paste the
   tunnel URL and API key. Tilly does a live round trip (`/health` +
   `/account`) before saving, so a wrong URL/key fails immediately instead
   of silently.

## Keeping it running

`uvicorn` in a terminal window dies when you close the window or the PC
sleeps. For anything beyond a quick test, run it as a Windows service —
[NSSM](https://nssm.cc/) is the simplest way:
```powershell
nssm install TillyMT5Bridge "C:\Python311\python.exe" "-m uvicorn bridge:app --host 0.0.0.0 --port 8787"
nssm set TillyMT5Bridge AppEnvironmentExtra MT5_BRIDGE_API_KEY=paste-your-key-here
nssm start TillyMT5Bridge
```
Also disable Windows sleep/hibernate on this machine — a sleeping PC means a
sleeping bridge means bots silently stop trading.

## Security notes

- Every endpoint (including `/health`) requires `Authorization: Bearer
  <MT5_BRIDGE_API_KEY>` — anyone who finds the tunnel URL without the key
  gets a 401, not your account number.
- The API key is stored in Supabase's `broker_accounts.bridge_api_key`,
  readable only by your own account (Row Level Security) and never returned
  by the Tilly backend's own API responses.
- This bridge can place and close real trades. Start on a demo account.
  Nothing in Tilly currently confirms "this is a live account, are you
  sure" before a bot starts trading through it — that's on you to check.
- `DEVIATION_POINTS` (max slippage) and `MAGIC` (order tag) are constants
  near the top of `bridge.py` — adjust for your broker/symbol if needed.

## Endpoint reference

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/health` | — | `{ok, logged_in, account}` |
| GET | `/account` | — | `{balance, equity, currency}` |
| GET | `/price/{symbol}` | — | `{bid, ask}` |
| GET | `/positions` | — | `[{id, symbol, type, volume, openPrice, currentPrice, unrealizedProfit}]` |
| GET | `/orders` | — | `[{id, symbol, type, openPrice, volume}]` |
| POST | `/orders/market` | `{symbol, side, volume}` | `{id, filled_price, status}` |
| POST | `/orders/limit` | `{symbol, side, price, volume}` | `{id, status}` |
| POST | `/positions/{id}/close` | — | `{ok}` |
| POST | `/orders/{id}/cancel` | — | `{ok}` |
