# Tilly Trading

A cloud-based **automated forex trading platform**. Connect a broker (Exness / XM /
Vantage via MetaAPI), run **GRID** and **DCA** bots 24/5, and spin up strategies from
**AI-generated presets** — all from a dark, mobile-first operator console.

> Status: **Runnable full stack** ✅
> Scaffolding + database + JWT auth + bot CRUD/lifecycle are done and tested.
> It runs locally with **zero external services** (SQLite by default). Live broker
> execution (MetaAPI) and the Celery trading loop land in Tasks 3–4
> (see [Build order](#build-order)).

---

## ⚡ Fastest way to run (VS Code, zero setup)

No Docker, no Postgres, no config required — the backend uses a local SQLite file
by default and creates its tables + seeds AI presets on first boot.

**1. Backend** (terminal 1):

```bash
cd tilly-trading/backend
python -m venv .venv
# macOS/Linux:
source .venv/bin/activate
# Windows (PowerShell):  .venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload      # → http://localhost:8000/docs
```

**2. Frontend** (terminal 2):

```bash
cd tilly-trading/web
npm install
npm run dev                         # → http://localhost:3000
```

Open **http://localhost:3000** for the console UI, and **http://localhost:8000/docs**
for the interactive API (register a user, click **Authorize**, then create/start bots).

**In VS Code:** open the `tilly-trading` folder, then **Run and Debug → “Run Full Stack
(backend + web)”** to launch both at once. Recommended extensions are prompted on open.

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
