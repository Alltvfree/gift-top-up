# SatLink — ISP operations platform

Monitoring, configuration, billing and RADIUS for an island ISP:
**core RADIUS + core MikroTik → fiber / airFiber → island MikroTik (PPPoE) → Huawei OLT → ONT (PPPoE)**.

| Area | What it does |
|---|---|
| Monitoring | Pings every device each minute; MikroTik CPU/memory/uptime/PPPoE count/down interfaces (REST API); airFiber over SNMP; Huawei ONT state and optical levels over SSH. Island and link status roll up from devices. Alerts (unreachable, degraded, weak ONT signal) with optional webhook. |
| Configuration | Every router/OLT write is a **change request**: requested by one person, approved by another admin, applied with a rollback. MikroTik changes arm an on-router auto-restore before applying, so a bad change on a remote island undoes itself. |
| Security | **Threat protection**: hosts brute-forcing router logins are detected from MikroTik logs and blocked on every router (rotating bots: whole /24). Two-factor sign-in (authenticator app) required for admins. RouterOS firewall/hardening generator (management lockdown, brute-force and port-scan blocklists, BCP38, ONT/CPE protection from botnets, customer isolation, anti-spam, open-resolver block, suspended-customer redirect) and a live **security audit** of each router. Platform: roles, lockouts, rate limits, strict CSP, encrypted device credentials, audit log. |
| Subscribers & RADIUS | Create → pending (rejected) → active (plan speed via `Mikrotik-Rate-Limit`) → suspended (256k + payment-page redirect) → cancelled. One login per account. State changes disconnect the live session (RFC 5176). |
| Billing | Monthly invoices (MVR), payment allocation oldest-first, auto-overdue, auto-suspend after a grace period, auto-restore when paid. |
| Telegram | Router/OLT change requests arrive in Telegram with **Approve / Approve & apply / Reject** buttons; approving or applying asks for your 6-digit two-factor code (deleted from the chat after use) and the result comes back in the chat. Alerts and threat blocks too. Each user links their own chat in **My account**. |
| SMS (MessageOwl) | Automatic invoice / reminder / payment / suspended / restored messages (editable templates), one-off SMS, outage notices to a whole island in bulk, full message log. |
| Import from DMA | CSV import of subscribers and NAS from DMA Radius Manager with a dry-run preview; imported customers stay billed by DMA until switched over ([docs/MIGRATE-FROM-DMA.md](docs/MIGRATE-FROM-DMA.md)). |
| Smart OLT | All OLTs at a glance; per-OLT dashboard (waiting authorization, online/offline, good/acceptable/weak/bad signal) with a filterable ONT list (port, status, signal, description/serial/account search); per-ONT live signal, read config, reboot, enable/disable (audited); autofind + provisioning as reviewed changes. Parser verified against real MA5608T output. |

## Layout
```
backend/app/        FastAPI API + worker
  adapters/         mikrotik (REST), huawei (SSH CLI), airfiber (SNMP), radius_coa, ping
  services/         monitor, billing, radius_sync, firewall (generator + audit), changes
  routers/          HTTP endpoints
backend/tests/      pytest against a real PostgreSQL
database/migrations SQL migrations, applied automatically on start
radius/             FreeRADIUS 3.2 image: SQL module + site patch
frontend/           nginx (TLS, rate limits, allowlist) + single-page UI
routeros/           one-time bootstrap script for each MikroTik
docs/               NETWORK-SETUP.md (step by step), SECURITY.md
```

## Run (Ubuntu + Docker Compose)
Runs alongside other services on the same server: every host port is set in `.env`
(defaults: web UI **8443**, HTTP redirect 8081, RADIUS 1812/1813 udp, API 8000 on loopback only — nothing on 80, 443 or 8080).
```bash
cp .env.example .env && chmod 600 .env     # fill every value; back up APP_SECRET_KEY
./scripts/check-ports.sh                    # are those ports free? does the Docker subnet clash?
./scripts/make-selfsigned-cert.sh noc.example.local
nano frontend/allowlist.conf                # your NOC / VPN ranges
docker compose up --build -d
docker compose exec api python -m app.cli create-admin yourname
```
Open `https://<server>:8443/` (or your `HTTPS_PORT`), sign in and set up two-factor (required for admins). Create a second admin (changes need another admin's approval), then follow
[docs/NETWORK-SETUP.md](docs/NETWORK-SETUP.md) — start with one island.

Services: `db` (PostgreSQL 16), `api`, `worker` (polling + daily billing), `telegram` (bot; idle until `TELEGRAM_BOT_TOKEN` is set), `radius` (UDP), `frontend` (nginx). The Compose
project is named `isp-platform`, so its containers, volume and network never mix with your other Compose projects.
Never publish the platform to the internet; reach it over your management network or VPN.

## Telegram approvals
1. In Telegram, open **@BotFather** → `/newbot` → copy the token.
2. In `.env`: `TELEGRAM_BOT_TOKEN=<token>` (and optionally `PORTAL_URL=https://<server>:8443`), then `docker compose up -d`.
3. Each admin: **My account → Connect Telegram** → press **Start** in Telegram.

`FOUR_EYES=true` (default): a change goes to every *other* linked admin. Working alone? `FOUR_EYES=telegram` lets you approve
your own change, but only in Telegram with your 2FA code. The portal still refuses it, so approval always takes a second device.

## Roles
`admin` everything (two-factor required) · `noc` network + subscribers · `billing` plans, invoices, payments, subscribers · `support` read-only.

## Development
```bash
cd backend && python -m venv .venv && . .venv/bin/activate && pip install -r requirements-dev.txt
DATABASE_URL=postgresql://postgres@localhost:5432/isp_test pytest -q   # uses (and wipes) that database
```

## Status
Tested here: API, RADIUS sync, billing, firewall generator/audit, Huawei parsers, CoA packets, MikroTik commit-confirm logic
(unit/integration tests), the UI in a browser, and FreeRADIUS 3.2 against this schema (accept/reject, plan speeds, suspended group,
accounting, one-login-per-account, NAS reboot).
**Not yet tested against real MikroTik, airFiber or Huawei hardware** — validate each adapter on one device before rolling out.
See [docs/SECURITY.md](docs/SECURITY.md) for remaining production gaps (backups, RADIUS HA).
