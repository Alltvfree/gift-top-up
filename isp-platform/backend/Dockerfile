FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 MIGRATIONS_DIR=/app/migrations
# ping for reachability, snmpget for airFiber radios
RUN apt-get update && apt-get install -y --no-install-recommends iputils-ping snmp \
    && rm -rf /var/lib/apt/lists/* && useradd --system --uid 10001 app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
COPY database/migrations ./migrations
USER app
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8000"]
