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

## Setup: one shared VPS, many clients (recommended, scripted)

Every account — yours or a client's — needs its own bridge, but they don't
need their own machine. MetaTrader5's Python package can only talk to ONE
terminal per process, so running several clients on one box means each
gets its own **isolated copy** of the MT5 terminal (a plain folder copy —
MetaTrader derives its per-install data directory from the install path,
so two copies in two different folders are automatically independent, no
special "portable" flag needed) plus its own `bridge.py` process on its own
port. Everything else — Python, cloudflared, the VPS itself — is shared.

1. **Provision one Windows VPS** (widely sold cheap specifically for this —
   search "Windows VPS MT5/MT4 hosting"), RDP into it, and copy this
   `mt5-bridge/` folder onto it.

2. **One-time per VPS** — install Python and cloudflared:
   ```powershell
   .\bootstrap-vps.ps1
   ```

3. **Install each broker's MT5 terminal you'll need, once, as a "master" copy**
   — e.g. the broker's normal installer into `C:\MT5-Master-Exness\`. Don't
   log in to it; `add-client.ps1` clones it fresh per client.

4. **For each client**, run:
   ```powershell
   .\add-client.ps1 -ClientSlug "acme" -Mt5Login "12345678" -Mt5Password "their-password" -Mt5Server "Exness-MT5Real8" -MasterTerminalDir "C:\MT5-Master-Exness"
   ```
   This clones the master terminal into its own folder, picks the next
   free port automatically, generates an API key, registers a dedicated
   Scheduled Task, starts it, and confirms `/health` responds. It prints
   the API key at the end — save it.

5. **Give that client a permanent URL:**
   ```powershell
   .\setup-tunnel.ps1 -ClientSlug "acme" -Domain "bridges.yourdomain.com"
   ```
   Needs a domain (or subdomain) that's an active zone in your Cloudflare
   account — set one aside for this, don't reuse a domain serving another
   site. The first time you run this on a VPS it opens a browser for
   `cloudflared tunnel login`; every client added after that on the same
   VPS reuses the same login automatically. Each client still gets their
   own tunnel process, so one client's tunnel restarting never touches
   another's. Unlike a quick tunnel (`cloudflared tunnel --url ...`), this
   URL is permanent.

6. **Link it in Tilly** — Account page → **+ BRIDGE** → paste the printed
   `https://acme.bridges.yourdomain.com` URL and the API key from step 4.
   Tilly does a live round trip (`/health` + `/account`) before saving, so
   a wrong URL/key fails immediately instead of silently.

Repeat steps 4–6 for the next client — steps 1–3 are one-time per VPS.

> **Written, not run.** All four scripts were authored and reviewed
> carefully — checked for balanced braces/parens, matched against the
> exact PowerShell patterns already verified working on a real Windows box
> earlier in this project (Task Scheduler with `-LogonType Interactive`,
> corrected `-AllowStartIfOnBatteries` pluralization) — but this sandbox
> has no Windows machine to actually execute them against. Dry-run on a
> throwaway VPS with a demo account first.

**Critical VPS gotcha:** every bridge and tunnel runs as a Scheduled Task
tied to an *interactive logon session*, not a true background service —
MT5's IPC only works inside a real desktop session (a true Windows service
runs in Session 0, which is isolated from it). This means: after setting
up, **disconnect your RDP client, don't log off**. Disconnecting keeps the
session — and every client's bridge/tunnel running in it — alive; logging
off ends the session and kills all of them at once.

## Setup: manual / a single always-on PC

If you're running this on your own PC with just one account (not a shared
client VPS), or want to understand what the scripts above automate:

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
sleeps. `add-client.ps1` (and `bootstrap-vps.ps1`'s single-PC equivalent)
handles this via a Scheduled Task; doing it by hand with
[NSSM](https://nssm.cc/) also works, though NSSM registers a true Windows
service, which hits the Session 0 IPC problem above — the Scheduled Task
approach is the one that's actually been confirmed working. Either way,
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
- `DEVIATION_POINTS` (max slippage) and `MAGIC` (default order tag, used
  when a request doesn't send its own) are constants near the top of
  `bridge.py` — adjust for your broker/symbol if needed.
- **Multiple Tilly bots sharing one account/symbol are isolated by `magic`.**
  Every order Tilly places is tagged with a per-bot magic number, and
  `GET /positions?magic=` filters to just that bot's own positions — MT5
  itself has no other concept of "which bot" opened a position, so without
  this, two bots on the same symbol would see (and could close) each
  other's trades. If you call this bridge directly rather than through
  Tilly, omit `magic` and every position on the account is returned.

## Endpoint reference

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/health` | — | `{ok, logged_in, account}` |
| GET | `/account` | — | `{balance, equity, currency}` |
| GET | `/price/{symbol}` | — | `{bid, ask}` |
| GET | `/positions?magic=` | — | `[{id, symbol, type, volume, openPrice, currentPrice, unrealizedProfit, magic}]` — `magic` filters to one bot's positions, omit for all |
| GET | `/symbols` | — | `["EURUSD", "XAUUSDm", ...]` — every symbol name this terminal/broker knows |
| GET | `/candles/{symbol}?timeframe=&limit=` | — | `{symbol, timeframe, bars: [{time, open, high, low, close}]}` — real history via `copy_rates_from_pos` |
| GET | `/orders` | — | `[{id, symbol, type, openPrice, volume}]` |
| POST | `/orders/market` | `{symbol, side, volume, magic?}` | `{id, filled_price, status}` |
| POST | `/orders/limit` | `{symbol, side, price, volume, magic?}` | `{id, status}` |
| POST | `/positions/{id}/close` | — | `{ok}` |
| POST | `/orders/{id}/cancel` | — | `{ok}` |
