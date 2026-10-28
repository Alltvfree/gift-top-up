# IslandNet — ISP operations platform

Monitoring, configuration, billing and RADIUS for an island ISP:
**core RADIUS + core MikroTik → fiber / airFiber → island MikroTik (PPPoE) → Huawei OLT → ONT (PPPoE)**.

| Area | What it does |
|---|---|
| Monitoring | Pings every device each minute; MikroTik CPU/memory/uptime/PPPoE count/down interfaces (REST API); airFiber over SNMP; Huawei ONT state and optical levels over SSH. Island and link status roll up from devices. Alerts (unreachable, degraded, weak ONT signal) with optional webhook. |
| Configuration | Every router/OLT write is a **change request**: requested by one person, approved by another admin, applied with a rollback. MikroTik changes arm an on-router auto-restore before applying, so a bad change on a remote island undoes itself. |
| Security | RouterOS firewall/hardening generator (management lockdown, brute-force and port-scan blocklists, BCP38, ONT/CPE protection from botnets, customer isolation, anti-spam, open-resolver block, suspended-customer redirect) and a live **security audit** of each router. Platform: roles, lockouts, rate limits, strict CSP, encrypted device credentials, audit log. |
| Subscribers & RADIUS | Create → pending (rejected) → active (plan speed via `Mikrotik-Rate-Limit`) → suspended (256k + payment-page redirect) → cancelled. One login per account. State changes disconnect the live session (RFC 5176). |
| Billing | Monthly invoices (MVR), payment allocation oldest-first, auto-overdue, auto-suspend after a grace period, auto-restore when paid. |
| Smart OLT | Autofind unregistered ONTs, provision ONT + PPPoE + service-port as a reviewed change, reboot ONT, optical levels per subscriber. |

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
```bash
cp .env.example .env && chmod 600 .env     # fill every value; back up APP_SECRET_KEY
./scripts/make-selfsigned-cert.sh noc.example.local
nano frontend/allowlist.conf                # your NOC / VPN ranges
docker compose up --build -d
docker compose exec api python -m app.cli create-admin yourname
```
Open `https://<server>/`. Create a second admin (changes need another admin's approval), then follow
[docs/NETWORK-SETUP.md](docs/NETWORK-SETUP.md) — start with one island.

Services: `db` (PostgreSQL 16), `api`, `worker` (polling + daily billing), `radius` (UDP 1812/1813), `frontend` (443).
Never publish the platform to the internet; reach it over your management network or VPN.

## Roles
`admin` everything · `noc` network + subscribers · `billing` plans, invoices, payments, subscribers · `support` read-only.

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
See [docs/SECURITY.md](docs/SECURITY.md) for remaining production gaps (MFA, backups, RADIUS HA).
