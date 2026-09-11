# Tilly Trading

A cloud-based **automated forex trading platform**. Connect a broker (Exness / XM /
Vantage via MetaAPI), run **GRID** and **DCA** bots 24/5, and spin up strategies from
**AI-generated presets** — all from a dark, mobile-first operator console.

> Status: **Web app runs on Supabase + Cloudflare Pages** ✅
> The Next.js console talks **directly to Supabase** — Supabase Auth for login and
> PostgREST + Row Level Security for data. No application server to run or host.
> Live broker execution (MetaAPI) and the trading loop land in Tasks 3–4.

---

## Architecture

There are two independent pieces:

**1. Web app (the live deployment)** — Next.js static export on **Cloudflare Pages**,
talking straight to **Supabase**:

```
Browser ── Next.js (Cloudflare Pages, static) ──► Supabase
                                                   ├─ Auth  (login/signup)
                                                   ├─ Postgres + PostgREST (bots, positions…)
                                                   └─ Row Level Security (per-user isolation)
```

No server process is needed — auth and data access happen in the browser against
Supabase, secured by RLS. This is what you deploy.

**2. FastAPI backend (optional, future bot-runner)** — the Python service in
`backend/` implements the GRID/DCA engine, MetaAPI broker adapter and Celery runner.
It is **not required by the web app** and isn't part of the Cloudflare/Supabase
deployment; it will run on a worker host when live trading is wired (Tasks 3–4).

---

## Run the web app locally

Only Node is required — it connects to the shared Supabase project.

```bash
cd tilly-trading/web
npm install
npm run dev                         # → http://localhost:3000
```

The Supabase URL + publishable key are baked in as fallbacks (and overridable via
`.env.local`; see [`web/.env.example`](./web/.env.example)). Sign up / sign in on the
first screen, then create a bot — it's written to your Supabase `bots` table and
shows up under **Table Editor → bots**.

> **Instant signup:** by default Supabase emails a confirmation link. To skip that
> while testing, turn off **Authentication → Sign In / Providers → Email → "Confirm
> email"** in the Supabase dashboard; otherwise click the link in the email, then sign in.

---

## Deploy the web app to Cloudflare Pages

`npm run build` produces a static site in `web/out/`. In Cloudflare Pages → **Create
project → Connect to Git**, then set:

| Setting                | Value            |
| ---------------------- | ---------------- |
| Framework preset       | Next.js (Static Export) |
| Root directory         | `tilly-trading/web` |
| Build command          | `npm run build`  |
| Build output directory | `out`            |

Optionally set the env vars `NEXT_PUBLIC_SUPABASE_URL` and
`NEXT_PUBLIC_SUPABASE_ANON_KEY` (they default to this project if omitted). After the
first deploy, add your Pages URL to the Supabase **Auth → URL Configuration → Site URL
/ Redirect URLs** so auth redirects resolve.

---

## Stack

| Layer        | Technology                                   |
| ------------ | -------------------------------------------- |
| Backend      | Python 3.11 · FastAPI                        |
| Database     | PostgreSQL 15                                |
| Cache / Queue| Redis 7                                      |
| ORM          | SQLAlchemy 2.0 (async) + Alembic             |
| Auth         | JWT (PyJWT) + OAuth2 password flow           |
| Broker API   | MetaAPI.cloud SDK (MetaTrader)               |
| Task queue   | Celery + Redis                               |
| Frontend     | Next.js 14 (App Router) · React 18           |
| Styling      | Tailwind CSS + shadcn/ui                     |
| Deployment   | Docker + Docker Compose                      |

---

## Monorepo layout

```
tilly-trading/
├── backend/                  # FastAPI backend
│   ├── app/
│   │   ├── api/v1/           # REST + WebSocket endpoints
│   │   ├── core/             # config, security (JWT/bcrypt), deps
│   │   ├── db/               # SQLAlchemy models + session
│   │   │   └── models/       # users, broker_accounts, bots, orders, positions, ai_presets
│   │   ├── schemas/          # Pydantic request/response models
│   │   ├── services/         # bot runner (strategy registry)
│   │   ├── bots/             # BaseBot, GridBot, DCABot
│   │   ├── broker/           # BrokerClient ABC + MetaAPIClient
│   │   ├── ai/               # AIPresetGenerator
│   │   ├── tasks/            # Celery app
│   │   └── main.py           # app entrypoint
│   ├── alembic/              # DB migrations
│   ├── tests/                # smoke tests (no DB needed)
│   ├── requirements.txt
│   └── Dockerfile
├── web/                      # Next.js 14 console
│   ├── src/
│   │   ├── app/              # /, /signals, /trades, /risk, /admin
│   │   ├── components/       # console-shell + ui/ (shadcn)
│   │   ├── lib/              # api client, utils, seed data
│   │   └── hooks/
│   ├── package.json
│   └── Dockerfile
├── docker-compose.yml        # db + redis + backend + worker + web
├── .env.example
└── README.md
```

---

## Quick start (Docker — recommended)

Requires Docker + Docker Compose.

```bash
cd tilly-trading
cp .env.example .env          # then set JWT_SECRET_KEY (and METAAPI_TOKEN when ready)
docker compose up --build
```

Services:

| Service   | URL                              |
| --------- | -------------------------------- |
| Web       | http://localhost:3000            |
| API       | http://localhost:8000            |
| API docs  | http://localhost:8000/docs       |
| Health    | http://localhost:8000/health     |
| Postgres  | localhost:5432                   |
| Redis     | localhost:6379                   |

---

## Local development (without Docker)

### Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

uvicorn app.main:app --reload   # http://localhost:8000
```

On startup the app creates its tables (SQLite `tilly.db` by default) and seeds the
AI presets — **no migration step needed for local dev**. To use Postgres/Supabase
instead, set `DATABASE_URL` (see [`.env.example`](./.env.example)); for production,
generate Alembic migrations with `alembic revision --autogenerate -m "init"` and
`alembic upgrade head`.

Run the smoke tests (no database required):

```bash
cd backend
pytest -q
```

Run the Celery worker (needs Redis):

```bash
celery -A app.tasks.celery_app.celery_app worker --loglevel=info
```

### Frontend

```bash
cd web
npm install
npm run dev                     # http://localhost:3000
```

The console reads `NEXT_PUBLIC_API_URL` (default `http://localhost:8000`) to reach the API.

---

## What works today

- **Auth (JWT)** — `register`, `login` (OAuth2 password flow), `refresh`, `me`.
  Passwords hashed with bcrypt; protected routes via bearer token.
- **Bots** — full CRUD scoped to the authenticated user, plus `start`/`stop`
  (persists status + timestamps) and `orders`/`positions` listing.
- **AI presets** — `GET /api/v1/ai-presets` (DB-seeded) and
  `POST /api/v1/ai-presets/generate` (tuned to balance/symbol/volatility).
- **Market data** — `symbols`, `price/{symbol}`, and `WS ws/{symbol}` serve
  **simulated** quotes until MetaAPI is connected (flagged `source: "simulated"`).
- **Database** — all six tables, portable across SQLite and PostgreSQL/Supabase,
  auto-created + seeded on startup.
- **Bot engine** — `BaseBot`, `GridBot`, `DCABot` and the strategy registry.
- **Broker adapter** — `BrokerClient` ABC and `MetaAPIClient` (lazily imports the SDK).
- **Console UI** — dark amber-on-ink operator console (Home / Signals / Trades /
  Risk / Admin) wired to the real typed API client.
- **Tests** — `pytest` covers the health/presets/market endpoints and the full
  register → login → create → start → stop → delete bot flow (10 tests).

### Not yet wired (Tasks 3–4)

- Live broker order execution via MetaAPI (currently the engine classes + adapter
  exist but aren't driven by a running loop).
- The Celery worker that runs bots 24/5 and streams real fills into orders/positions.
  The console pages still show seed data for positions/trades until then.

---

## API surface

```
Auth        POST /api/v1/auth/register | login | refresh      GET /api/v1/auth/me
Bots        GET/POST /api/v1/bots       GET/PATCH/DELETE /api/v1/bots/{id}
            POST /api/v1/bots/{id}/start | stop
            GET  /api/v1/bots/{id}/orders | positions
AI presets  GET /api/v1/ai-presets      POST /api/v1/ai-presets/generate
Market      GET /api/v1/market/symbols  GET /api/v1/market/price/{symbol}
            WS  /api/v1/market/ws/{symbol}
```

---

## Configuration

All configuration is via environment variables — see [`.env.example`](./.env.example)
for the full list (Postgres, Redis/Celery, JWT, CORS, MetaAPI, optional LLM keys,
and the frontend `NEXT_PUBLIC_API_URL`). Copy it to `.env` before running.

**Never commit `.env`** — it is git-ignored. Generate a real JWT secret with
`openssl rand -hex 32`.

---

## Using Supabase (hosted Postgres)

Tilly runs on Supabase with no code changes — it's just PostgreSQL.

1. Create a project at [supabase.com](https://supabase.com).
2. **Project Settings → Database → Connection string** → copy the **Session pooler**
   URI (host `...pooler.supabase.com`, port `5432`).
3. In your `.env` set (see [`.env.example`](./.env.example) for the exact template):

   ```env
   DATABASE_URL=postgresql+asyncpg://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres
   DATABASE_URL_SYNC=postgresql+psycopg2://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres?sslmode=require
   DATABASE_SSL=true
   ```

4. Start the backend. Tables are created and presets seeded automatically on first boot
   (or run Alembic if you prefer managed migrations).

Notes:

- Use the **Session** pooler (port 5432) for this long-running server. If you must use
  the **Transaction** pooler (port 6543), also set `DATABASE_PGBOUNCER=true`.
- This uses Supabase only as the database. Tilly has its own JWT auth, so Supabase Auth
  is optional and not required.

---

## Build order

1. ✅ **Project scaffolding**
2. ✅ **Database & auth** — models, register/login/refresh, bcrypt, protected routes
3. Broker integration — wire `MetaAPIClient`, account linking, test on an Exness demo
4. Bot engine core — Celery-backed runner, live start/stop/pause loop ← _next_
5. API endpoints — WebSocket price relay from the broker, remaining validation
6. Web frontend — bot creation wizard, TradingView charts, live tables
7. AI presets — "Generate with AI" in the wizard, optional backtest engine
8. Deployment — CI/CD, domain + SSL

> Bot CRUD + start/stop (parts of Tasks 4–5) already work against the DB; what's left
> for Task 4 is driving them with a live broker loop.

---

## Disclaimer

Automated trading carries substantial financial risk. Run against **demo/paper
accounts** until every strategy is validated. This software is provided as-is with
no warranty; you are responsible for any live trading you enable.
