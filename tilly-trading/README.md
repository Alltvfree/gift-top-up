# Tilly Trading

A cloud-based **automated forex trading platform**. Connect a broker (Exness / XM /
Vantage via MetaAPI), run **GRID** and **DCA** bots 24/5, and spin up strategies from
**AI-generated presets** — all from a dark, mobile-first operator console.

> Status: **Task 1 — Project Scaffolding** ✅
> The monorepo, infra, backend skeleton (with the full bot/broker/AI engine code),
> and the Next.js console UI are in place. Persistence, auth, live broker execution
> and the bot runtime land in Tasks 2–8 (see [Build order](#build-order)).

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

# start Postgres + Redis (e.g. via `docker compose up db redis`)
cp ../.env.example ../.env      # config is read from the repo-root .env

# create the schema (once migrations exist — see Task 2)
alembic revision --autogenerate -m "init schema"
alembic upgrade head

uvicorn app.main:app --reload   # http://localhost:8000
```

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

- **FastAPI app** boots with `/`, `/health`, `/docs`, CORS, and the full `/api/v1` router.
- **AI presets** — `GET /api/v1/ai-presets` and `POST /api/v1/ai-presets/generate` are
  fully functional (pure logic, no DB).
- **Market data** — `GET /api/v1/market/symbols`, `GET /api/v1/market/price/{symbol}`,
  and `WS /api/v1/market/ws/{symbol}` serve **simulated** quotes until the MetaAPI feed
  is connected (flagged `source: "simulated"`).
- **Database models** for every table in the schema, ready for Alembic autogenerate.
- **Bot engine** — `BaseBot`, `GridBot`, `DCABot` and the strategy registry.
- **Broker adapter** — `BrokerClient` ABC and `MetaAPIClient` (lazily imports the SDK).
- **Console UI** — dark amber-on-ink operator console with Home / Signals / Trades /
  Risk / Admin, ported from the design you approved and wired to the real API client.
- **Stubbed endpoints** (`/auth/*`, `/bots/*`) return `501` with a pointer to the task
  that implements them — the request/response contracts are already defined.

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

## Build order

1. **Project scaffolding** ← _you are here_
2. Database & auth — Alembic migrations, register/login/refresh, bcrypt, protected routes
3. Broker integration — wire `MetaAPIClient`, account linking, test on an Exness demo
4. Bot engine core — Celery-backed runner, start/stop/pause lifecycle
5. API endpoints — full CRUD, validation, WebSocket price relay from the broker
6. Web frontend — bot creation wizard, TradingView charts, live tables
7. AI presets — "Generate with AI" in the wizard, optional backtest engine
8. Deployment — CI/CD, domain + SSL

---

## Disclaimer

Automated trading carries substantial financial risk. Run against **demo/paper
accounts** until every strategy is validated. This software is provided as-is with
no warranty; you are responsible for any live trading you enable.
