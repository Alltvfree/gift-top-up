"""Settings read from the environment (see .env.example)."""
import os
from pathlib import Path


def _int(name, default):
    return int(os.environ.get(name, default))


DATABASE_URL = os.environ.get("DATABASE_URL", "")
# Fernet key used to encrypt device credentials at rest. Generate with:
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
APP_SECRET_KEY = os.environ.get("APP_SECRET_KEY", "")
MIGRATIONS_DIR = Path(os.environ.get("MIGRATIONS_DIR", Path(__file__).resolve().parents[2] / "database" / "migrations"))

SESSION_HOURS = _int("SESSION_HOURS", 12)
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "true").lower() == "true"
LOGIN_MAX_FAILURES_PER_USER = _int("LOGIN_MAX_FAILURES_PER_USER", 5)
LOGIN_LOCK_MINUTES = _int("LOGIN_LOCK_MINUTES", 15)
LOGIN_MAX_FAILURES_PER_IP = _int("LOGIN_MAX_FAILURES_PER_IP", 20)
# Only trust X-Forwarded-For from the bundled nginx (docker network).
TRUSTED_PROXY_NETS = os.environ.get("TRUSTED_PROXY_NETS", "172.16.0.0/12,127.0.0.1/32").split(",")

# Billing
BILLING_DUE_DAYS = _int("BILLING_DUE_DAYS", 10)
SUSPEND_AFTER_DAYS_OVERDUE = _int("SUSPEND_AFTER_DAYS_OVERDUE", 5)

# Monitoring
POLL_INTERVAL_S = _int("POLL_INTERVAL_S", 60)
POLL_WORKERS = _int("POLL_WORKERS", 32)
OLT_POLL_EVERY_N = _int("OLT_POLL_EVERY_N", 10)
ONT_LOW_RX_DBM = float(os.environ.get("ONT_LOW_RX_DBM", "-27"))
LATENCY_WARN_MS = float(os.environ.get("LATENCY_WARN_MS", "80"))
ALERT_WEBHOOK_URL = os.environ.get("ALERT_WEBHOOK_URL", "")

# Change workflow: requester may not approve their own change.
FOUR_EYES = os.environ.get("FOUR_EYES", "true").lower() == "true"
# Minutes before RouterOS auto-restores the pre-change backup unless the platform confirms.
COMMIT_CONFIRM_MINUTES = _int("COMMIT_CONFIRM_MINUTES", 5)

# Two-factor: roles that must enrol TOTP before they can use anything else (comma separated).
MFA_REQUIRED_ROLES = {r.strip() for r in os.environ.get("MFA_REQUIRED_ROLES", "admin").split(",") if r.strip()}
MFA_ISSUER = os.environ.get("MFA_ISSUER", "SatLink")
