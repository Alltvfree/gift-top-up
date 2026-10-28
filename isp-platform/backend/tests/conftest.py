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
from app.security import hash_password  # noqa: E402

PASSWORD = "Correct-Horse-9"


@pytest.fixture(scope="session", autouse=True)
def fresh_db():
    with psycopg.connect(config.DATABASE_URL, autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    migrate()
    with psycopg.connect(config.DATABASE_URL, autocommit=True) as conn:
        for name, role in (("alice", "admin"), ("bob", "admin"), ("nina", "noc"), ("bill", "billing"), ("sam", "support")):
            conn.execute("INSERT INTO users(username,role,password_hash) VALUES (%s,%s,%s)", (name, role, hash_password(PASSWORD)))
    yield


@pytest.fixture(autouse=True)
def clear_throttle():
    with psycopg.connect(config.DATABASE_URL, autocommit=True) as conn:
        conn.execute("DELETE FROM login_attempts; UPDATE users SET failed_logins=0, locked_until=NULL")


def login(username):
    c = TestClient(app, headers={"X-Requested-With": "islandnet"})
    r = c.post("/api/auth/login", json={"username": username, "password": PASSWORD})
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
