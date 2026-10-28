import base64

import psycopg
from fastapi.testclient import TestClient

from app import config, totp
from app.main import app
from app.security import hash_password
from tests.conftest import ADMIN_TOTP, PASSWORD, current_code, login


def client():
    return TestClient(app, headers={"X-Requested-With": "islandnet"})


def sql(q, params=None):
    with psycopg.connect(config.DATABASE_URL, autocommit=True) as conn:
        cur = conn.execute(q, params)
        return cur.fetchall() if cur.description else None


def new_user(name, role):
    sql("DELETE FROM users WHERE username=%s", (name,))
    sql("INSERT INTO users(username,role,password_hash) VALUES (%s,%s,%s)", (name, role, hash_password(PASSWORD)))


def test_rfc6238_vector():
    secret = base64.b32encode(b"12345678901234567890").decode()
    assert totp.code_at(secret, 59 // 30) == "287082"          # RFC 6238 SHA1 vector (last 6 of 94287082)
    assert totp.code_at(secret, 1111111109 // 30) == "081804"  # 07081804
    assert totp.verify(secret, "287082", now=59) == 1
    assert totp.verify(secret, "287082", last_step=1, now=59) is None  # replay
    assert totp.verify(secret, "287082", now=59 + 90) is None           # too old


def enrol(c):
    setup = c.post("/api/auth/mfa/setup").json()
    assert setup["uri"].startswith("otpauth://totp/") and f"secret={setup['secret']}" in setup["uri"]
    assert c.post("/api/auth/mfa/enable", json={"code": "000000" if current_code(setup["secret"]) != "000000" else "111111"}).status_code == 400
    code = current_code(setup["secret"])
    r = c.post("/api/auth/mfa/enable", json={"code": code})
    assert r.status_code == 200, r.text
    enrol.last_code = code
    return setup["secret"], r.json()["recovery_codes"]


def test_admin_must_enrol_before_anything_else():
    new_user("carol", "admin")
    c = client()
    r = c.post("/api/auth/login", json={"username": "carol", "password": PASSWORD})
    assert r.status_code == 200 and "mfa_required" not in r.json()
    me = c.get("/api/auth/me").json()
    assert me["mfa_setup_required"] is True and me["permissions"] == []
    assert c.get("/api/summary").status_code == 403
    assert c.get("/api/users").status_code == 403
    secret, codes = enrol(c)
    assert len(codes) == 10 and len(set(codes)) == 10
    assert c.get("/api/summary").status_code == 200
    assert c.get("/api/auth/me").json()["mfa_setup_required"] is False


def test_two_step_login_wrong_code_replay_and_recovery():
    new_user("dave", "admin")
    c = client()
    c.post("/api/auth/login", json={"username": "dave", "password": PASSWORD})
    secret, codes = enrol(c)

    c2 = client()
    r = c2.post("/api/auth/login", json={"username": "dave", "password": PASSWORD})
    assert r.json()["mfa_required"] is True
    assert "isp_session" not in c2.cookies                  # no session after password alone
    assert c2.get("/api/auth/me").status_code == 401
    token = r.json()["mfa_token"]
    assert c2.post("/api/auth/login/mfa", json={"mfa_token": token, "code": "12345"}).status_code == 401
    # The exact code used for enrolment cannot be replayed
    assert c2.post("/api/auth/login/mfa", json={"mfa_token": token, "code": enrol.last_code}).status_code == 401
    # Recovery code works once
    r = c2.post("/api/auth/login/mfa", json={"mfa_token": token, "code": codes[0].upper()})
    assert r.status_code == 200 and r.json()["recovery_codes_left"] == 9
    assert c2.get("/api/summary").status_code == 200

    c3 = client()
    t3 = c3.post("/api/auth/login", json={"username": "dave", "password": PASSWORD}).json()["mfa_token"]
    assert c3.post("/api/auth/login/mfa", json={"mfa_token": t3, "code": codes[0]}).status_code == 401
    # The challenge token is single-use
    assert c2.post("/api/auth/login/mfa", json={"mfa_token": token, "code": codes[1]}).status_code == 401


def test_code_guessing_is_limited():
    new_user("erin", "admin")
    c = client()
    c.post("/api/auth/login", json={"username": "erin", "password": PASSWORD})
    secret, _ = enrol(c)
    c2 = client()
    token = c2.post("/api/auth/login", json={"username": "erin", "password": PASSWORD}).json()["mfa_token"]
    for _ in range(5):
        assert c2.post("/api/auth/login/mfa", json={"mfa_token": token, "code": "000000"}).status_code == 401
    # Account is now locked (5 failures) and the challenge is gone, even with a right code
    sql("UPDATE users SET totp_last_step=0 WHERE username='erin'")
    assert c2.post("/api/auth/login/mfa", json={"mfa_token": token, "code": current_code(secret)}).status_code == 401
    assert sql("SELECT locked_until > now() FROM users WHERE username='erin'") == [(True,)]


def test_admin_reset_and_role_change_revoke_sessions():
    new_user("fred", "noc")
    fred = client()
    assert fred.post("/api/auth/login", json={"username": "fred", "password": PASSWORD}).json()["role"] == "noc"
    assert fred.get("/api/summary").status_code == 200   # 2FA optional for noc
    alice = login("alice")
    fid = sql("SELECT id FROM users WHERE username='fred'")[0][0]
    assert alice.patch(f"/api/users/{fid}", json={"role": "admin"}).status_code == 200
    assert fred.get("/api/summary").status_code == 401   # signed out by role change
    fred.post("/api/auth/login", json={"username": "fred", "password": PASSWORD})
    assert fred.get("/api/summary").status_code == 403   # now must enrol
    enrol(fred)
    assert fred.get("/api/summary").status_code == 200
    # Lost phone: another admin resets
    assert alice.patch(f"/api/users/{fid}", json={"reset_mfa": True}).status_code == 200
    assert fred.get("/api/summary").status_code == 401
    assert sql("SELECT totp_enabled, totp_secret_enc FROM users WHERE id=%s", (fid,)) == [(False, None)]
    assert sql("SELECT count(*) FROM user_recovery_codes WHERE user_id=%s", (fid,)) == [(0,)]
    aid = sql("SELECT id FROM users WHERE username='alice'")[0][0]
    assert alice.patch(f"/api/users/{aid}", json={"reset_mfa": True}).status_code == 400  # not your own


def test_optional_mfa_for_other_roles_and_disable():
    new_user("gina", "billing")
    c = client()
    c.post("/api/auth/login", json={"username": "gina", "password": PASSWORD})
    secret, _ = enrol(c)
    c2 = client()
    assert c2.post("/api/auth/login", json={"username": "gina", "password": PASSWORD}).json()["mfa_required"] is True
    # Disabling needs an unused code; clear the replay marker set by enrolment.
    sql("UPDATE users SET totp_last_step=0 WHERE username='gina'")
    assert c.post("/api/auth/mfa/disable", json={"password": "wrong", "code": current_code(secret)}).status_code == 400
    assert c.post("/api/auth/mfa/disable", json={"password": PASSWORD, "code": current_code(secret)}).status_code == 200
    assert "mfa_required" not in client().post("/api/auth/login", json={"username": "gina", "password": PASSWORD}).json()


def test_admin_cannot_disable_and_secret_is_encrypted():
    alice = login("alice")
    sql("UPDATE users SET totp_last_step=0 WHERE username='alice'")
    assert alice.post("/api/auth/mfa/disable", json={"password": PASSWORD, "code": current_code()}).status_code == 403
    stored = sql("SELECT totp_secret_enc FROM users WHERE username='alice'")[0][0]
    assert ADMIN_TOTP not in stored
    r = alice.post("/api/auth/mfa/recovery-codes", json={"code": current_code()})
    assert r.status_code == 200 and len(r.json()["recovery_codes"]) == 10
