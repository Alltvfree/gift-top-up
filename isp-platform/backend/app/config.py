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

# Threat protection: block sources of repeated failed router logins on every MikroTik.
THREAT_AUTO_BLOCK = os.environ.get("THREAT_AUTO_BLOCK", "true").lower() == "true"
THREAT_FAILURES = _int("THREAT_FAILURES", 5)              # failed logins from one IP ...
THREAT_WINDOW_MIN = _int("THREAT_WINDOW_MIN", 30)         # ... within this many minutes
THREAT_BLOCK_HOURS = _int("THREAT_BLOCK_HOURS", 168)      # auto-blocks expire (7 days)
THREAT_SUBNET_AFTER = _int("THREAT_SUBNET_AFTER", 3)      # this many blocked IPs in one /24 -> block the /24
# Never auto-blocked (your NOC, VPN, upstream...). Private/CGNAT ranges are never auto-blocked either:
# an attack from inside raises an alert instead, so a customer or a NOC PC is never cut off by a script.
THREAT_NEVER_BLOCK = [n.strip() for n in os.environ.get("THREAT_NEVER_BLOCK", "").split(",") if n.strip()]

# SMS via MessageOwl (msgowl.com). Leave the key empty to keep SMS off; messages then stay queued.
MSGOWL_ACCESS_KEY = os.environ.get("MSGOWL_ACCESS_KEY", "")
MSGOWL_SENDER_ID = os.environ.get("MSGOWL_SENDER_ID", "SatLink")
SMS_PER_MINUTE = _int("SMS_PER_MINUTE", 40)          # MessageOwl allows 50 POST/min
SMS_BULK_CHUNK = _int("SMS_BULK_CHUNK", 100)         # recipients per bulk POST (broadcasts)
SMS_REMINDER_DAYS = _int("SMS_REMINDER_DAYS", 3)     # due_reminder this many days before due date
