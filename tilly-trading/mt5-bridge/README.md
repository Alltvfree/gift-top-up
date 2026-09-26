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

## Setup: per-client VPS (recommended, scripted)

Every account — yours or a client's — needs its own bridge. Rather than
asking a client to install Python and MT5 on their own PC, provision them a
small Windows VPS (widely sold cheap specifically for running MetaTrader —
search "Windows VPS MT5/MT4 hosting"), get their MT5 login/password/server
from them, and run this **on that VPS**, as Administrator, over RDP:

1. **Install MetaTrader 5** on the VPS (the broker's own installer) — you
   don't need to log in manually, the script below does it.

2. **Copy this `mt5-bridge/` folder to the VPS**, then run:
   ```powershell
   .\install-windows.ps1 -Mt5Login "414312080" -Mt5Password "the-clients-password" -Mt5Server "Exness-MT5Real8"
   ```
   This installs Python if missing, installs dependencies, generates an API
   key, writes a launcher with the MT5 credentials baked in, registers a
   Scheduled Task so it survives reboots, starts it, and hits `/health` to
   confirm it's actually up. It prints the generated API key at the end —
   save it.

3. **Give it a permanent URL:**
   ```powershell
   .\setup-tunnel.ps1 -ClientSlug "acme" -Domain "bridges.yourdomain.com"
   ```
   Needs a domain (or subdomain) that's an active zone in your Cloudflare
   account — set one aside for this, don't reuse a domain serving another
   site. The first time you run this on a *new* VPS it opens a browser for
   `cloudflared tunnel login`; skip that by copying `cert.pem` from a VPS
   you've already logged in on (same Cloudflare account) and passing
   `-CertPath`. Unlike a quick tunnel (`cloudflared tunnel --url ...`),
   this URL is permanent — it survives reboots and doesn't change.

4. **Link it in Tilly** — Account page → **+ BRIDGE** → paste the printed
   `https://acme.bridges.yourdomain.com` URL and the API key from step 2.
   Tilly does a live round trip (`/health` + `/account`) before saving, so
   a wrong URL/key fails immediately instead of silently.

> **Written, not run.** Both scripts were authored and reviewed carefully —
> checked for balanced braces/parens, matched against the exact PowerShell
> patterns already verified working on a real Windows box earlier in this
> project (Task Scheduler with `-LogonType Interactive`, corrected
> `-AllowStartIfOnBatteries` pluralization) — but this sandbox has no
> Windows machine to actually execute them against. Dry-run on a throwaway
> VPS with a demo account first.

**Critical VPS gotcha:** the bridge runs as a Scheduled Task tied to an
*interactive logon session*, not a true background service — MT5's IPC only
works inside a real desktop session (a true Windows service runs in Session
0, which is isolated from it). On a VPS this means: after running the
scripts, **disconnect your RDP client, don't log off**. Disconnecting keeps
the session (and the task) alive; logging off ends it and kills the bridge.

## Setup: manual / your own PC

If you're running this on your own always-on PC (not a client VPS), or want
to understand what the scripts above automate:

1. Install MetaTrader 5, log in, leave the terminal open. "Algo Trading"
   must be enabled (top toolbar) or `order_send` calls are rejected.
2. `pip install -r requirements.txt` (Python 3.10+ on the same machine).
3. Pick an API key: `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
4. Run it:
   ```powershell
   $env:MT5_BRIDGE_API_KEY = "paste-your-key-here"
   uvicorn bridge:app --host 0.0.0.0 --port 8787
   ```
   By default it attaches to whatever account is already logged in. To have
   it log in itself, also set `MT5_LOGIN`, `MT5_PASSWORD`, `MT5_SERVER` (and
   `MT5_PATH` if `terminal64.exe` isn't on `PATH`) before starting it.
5. Expose it over HTTPS — `cloudflared tunnel --url http://localhost:8787`
   for a quick disposable URL (changes every restart), or `setup-tunnel.ps1`
   for a permanent one.
6. Link it in Tilly — Account page → **+ BRIDGE**.

## Keeping it running

`uvicorn` in a terminal window dies when you close the window or the PC
sleeps. `install-windows.ps1` handles this via a Scheduled Task; doing it by
hand with [NSSM](https://nssm.cc/) also works, though NSSM registers a true
Windows service, which hits the Session 0 IPC problem above — the Scheduled
Task approach is the one that's actually been confirmed working. Either way,
disable Windows sleep/hibernate — a sleeping PC means a sleeping bridge
means bots silently stop trading.

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
| GET | `/symbols` | — | `["EURUSD", "XAUUSDm", ...]` — every symbol name this terminal/broker knows |
| GET | `/candles/{symbol}?timeframe=&limit=` | — | `{symbol, timeframe, bars: [{time, open, high, low, close}]}` — real history via `copy_rates_from_pos` |
| GET | `/orders` | — | `[{id, symbol, type, openPrice, volume}]` |
| POST | `/orders/market` | `{symbol, side, volume}` | `{id, filled_price, status}` |
| POST | `/orders/limit` | `{symbol, side, price, volume}` | `{id, status}` |
| POST | `/positions/{id}/close` | — | `{ok}` |
| POST | `/orders/{id}/cancel` | — | `{ok}` |
