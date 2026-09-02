# XAUUSD MT5 Trading Bot — API/dashboard image (PAPER/BACKTEST).
#
# NOTE: the MetaTrader5 package is Windows-only, so this Linux image runs
# PAPER/BACKTEST out of the box. For DEMO/LIVE, run the mt5linux Wine bridge
# separately (see README "Running on Ubuntu / Linux") and point the container at
# it with MT5_USE_LINUX_BRIDGE=true and MT5_BRIDGE_HOST.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/backend

WORKDIR /app

# Install dependencies first for better layer caching.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application.
COPY backend ./backend
COPY frontend ./frontend
COPY config ./config

# Non-root user.
RUN useradd -m bot && mkdir -p /app/data /app/logs && chown -R bot /app
USER bot

EXPOSE 8000

CMD ["uvicorn", "app.api.asgi:app", "--host", "0.0.0.0", "--port", "8000"]
