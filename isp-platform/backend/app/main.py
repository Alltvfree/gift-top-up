import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from . import db
from .migrate import migrate
from .routers import auth, billing, changes, inventory, monitoring, olt, radius, security, subscribers, threats

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")



@asynccontextmanager
async def lifespan(app):
    applied = migrate()
    if applied:
        logging.getLogger(__name__).info("migrations applied: %s", applied)
    yield


app = FastAPI(title="SatLink Operations API", version="0.2.0", docs_url=None, redoc_url=None, openapi_url=None,
              lifespan=lifespan)
for r in (auth.router, auth.users, inventory.router, subscribers.router, billing.router, radius.router,
          monitoring.router, olt.router, changes.router, security.router, threats.router):
    app.include_router(r)


@app.middleware("http")
async def headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    logging.getLogger(__name__).exception("unhandled error on %s", request.url.path)
    return JSONResponse({"detail": "Internal error"}, status_code=500)


@app.get("/health")
def health():
    db.row("SELECT 1")
    return {"status": "ok", "database": "connected"}
