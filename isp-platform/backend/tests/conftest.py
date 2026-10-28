import os

import psycopg
import pytest
from cryptography.fernet import Fernet

os.environ.setdefault("DATABASE_URL", "postgresql://postgres@localhost:55432/isp_test")
os.environ.setdefault("APP_SECRET_KEY", Fernet.generate_key().decode())
os.environ["COOKIE_SECURE"] = "false"

from fastapi.testclient import TestClient  # noqa: E402

from app import config  # noqa: E402
from app.main import app  # noqa: E402
from app.migrate import migrate  # noqa: E402
from app import totp  # noqa: E402
from app.security import encrypt_json, hash_password  # noqa: E402

PASSWORD = "Correct-Horse-9"
ADMIN_TOTP = totp.new_secret()  # alice and bob are enrolled with this secret


@pytest.fixture(scope="session", autouse=True)
def fresh_db():
    with psycopg.connect(config.DATABASE_URL, autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    migrate()
    with psycopg.connect(config.DATABASE_URL, autocommit=True) as conn:
        for name, role in (("alice", "admin"), ("bob", "admin"), ("nina", "noc"), ("bill", "billing"), ("sam", "support")):
            conn.execute("INSERT INTO users(username,role,password_hash,totp_enabled,totp_secret_enc) VALUES (%s,%s,%s,%s,%s)",
                         (name, role, hash_password(PASSWORD), role == "admin",
                          encrypt_json({"secret": ADMIN_TOTP}) if role == "admin" else None))
    yield


@pytest.fixture(autouse=True)
def clear_throttle():
    with psycopg.connect(config.DATABASE_URL, autocommit=True) as conn:
        conn.execute("DELETE FROM login_attempts; UPDATE users SET failed_logins=0, locked_until=NULL")


def current_code(secret=ADMIN_TOTP):
    import time
    return totp.code_at(secret, int(time.time() // totp.STEP))


def login(username):
    c = TestClient(app, headers={"X-Requested-With": "islandnet"})
    r = c.post("/api/auth/login", json={"username": username, "password": PASSWORD})
    assert r.status_code == 200, r.text
    if r.json().get("mfa_required"):
        # Tests sign in many times per 30 s step; clear replay protection (covered in test_mfa.py).
        with psycopg.connect(config.DATABASE_URL, autocommit=True) as conn:
            conn.execute("UPDATE users SET totp_last_step=0 WHERE username=%s", (username,))
        r = c.post("/api/auth/login/mfa", json={"mfa_token": r.json()["mfa_token"], "code": current_code()})
        assert r.status_code == 200, r.text
    return c


@pytest.fixture
def admin():
    return login("alice")


@pytest.fixture
def admin2():
    return login("bob")


@pytest.fixture
def sql():
    def run(q, params=None):
        with psycopg.connect(config.DATABASE_URL, autocommit=True) as conn:
            cur = conn.execute(q, params)
            return cur.fetchall() if cur.description else None
    return run
