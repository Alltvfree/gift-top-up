# Self-hosting the Tilly backend (API + bot worker)

Run the FastAPI API + Celery bot worker on your own Ubuntu server, exposed
through your existing **Cloudflare Tunnel**. The database stays on Supabase and
the web app stays on Cloudflare Pages — this just adds the always-on backend
that provisions brokers (Task 3) and runs bots 24/5 (Task 4). **Free** (uses
your server), no Render/paid host needed.

```
Browser → Pages (static)                     ┌── Supabase (DB + Auth)
        → https://tilly-api.<you>  ──tunnel──▶│   Ubuntu server:
                                              └──  api + worker + redis (docker)
```

## Prerequisites
- Docker + Docker Compose on the server (`docker --version`, `docker compose version`).
- Your `cloudflared` tunnel already running (it is).
- Three values: your **Supabase JWT secret**, your **MetaAPI token**, and a
  **hostname** on your Cloudflare domain for the API (e.g. `tilly-api.yourdomain`).

## 1. Get the code on the server
```bash
git clone https://github.com/Alltvfree/gift-top-up
cd gift-top-up/tilly-trading
cp .env.selfhost.example .env.selfhost
```

## 2. Fill in secrets
Edit `.env.selfhost` and set:
- `SUPABASE_JWT_SECRET` — Supabase → Project Settings → API → JWT Secret
- `METAAPI_TOKEN` — app.metaapi.cloud → Tokens

`DATABASE_URL` and `CORS_ORIGINS` are pre-filled for this project. If your Pages
URL differs from `gift-top-up1.pages.dev`, update `CORS_ORIGINS`.

## 3. Start it
```bash
docker compose -f docker-compose.selfhost.yml up -d --build
docker compose -f docker-compose.selfhost.yml logs -f api      # watch startup
curl http://localhost:8000/health                              # {"status":"ok",...}
```
`api` listens on `127.0.0.1:8000` only (not public); the tunnel exposes it.

## 4. Route your Cloudflare Tunnel to it
**Dashboard (easiest):** Zero Trust → Networks → Tunnels → *your tunnel* →
**Public Hostname → Add**:
- Subdomain `tilly-api`, Domain `yourdomain`
- Service: **HTTP** → `localhost:8000`

**Or config file:** merge the `tilly-api` block from
[`deploy/cloudflared-config.example.yml`](./deploy/cloudflared-config.example.yml)
into your existing `~/.cloudflared/config.yml` ingress (keep the `http_status:404`
catch-all last), then `sudo systemctl restart cloudflared`.

Verify from anywhere: `https://tilly-api.yourdomain/health`.

## 5. Point the web app at it
Cloudflare Pages → **gift-top-up1** → Settings → Environment variables →
add **Production** var `NEXT_PUBLIC_API_URL = https://tilly-api.yourdomain`
(no trailing slash) → **Deployments → Retry deployment**.

The Account page **+ LINK** form is now live.

## 6. Updating later
```bash
cd gift-top-up && git pull
cd tilly-trading && docker compose -f docker-compose.selfhost.yml up -d --build
```

## Operating notes
- Run the worker as a **single instance** (the compose file already does — it's
  one `worker` container with `--pool=solo`). Multiple workers would double-drive
  bots; a distributed lock isn't implemented yet.
- Logs: `docker compose -f docker-compose.selfhost.yml logs -f worker`.
- The engine only acts when `METAAPI_TOKEN` is set and at least one bot is
  `running` with a linked, provisioned broker account.
- **Real-money risk:** a `live` broker account will place real trades. Test on
  a **demo** account first.
