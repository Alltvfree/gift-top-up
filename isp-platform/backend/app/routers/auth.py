from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from .. import audit, config, db, totp
from ..deps import COOKIE, ROLES, client_ip, current_user, require
from ..security import (decrypt_json, encrypt_json, hash_password, new_session_token, password_problem, token_hash,
                        verify_dummy, verify_password)

router = APIRouter(prefix="/api/auth", tags=["auth"])
MFA_CHALLENGE_MINUTES = 5
MFA_MAX_ATTEMPTS = 5


class Login(BaseModel):
    username: str = Field(max_length=40)
    password: str = Field(max_length=200)


class MfaLogin(BaseModel):
    mfa_token: str = Field(max_length=100)
    code: str = Field(max_length=40)  # 6-digit TOTP or a recovery code


class PasswordChange(BaseModel):
    current_password: str = Field(max_length=200)
    new_password: str = Field(max_length=200)


GENERIC = "Invalid username or password"


def _throttle(conn, ip):
    recent = conn.execute(
        "SELECT count(*) AS n FROM login_attempts WHERE ip IS NOT DISTINCT FROM %s AND NOT success AND at>now()-interval '15 minutes'",
        (ip,),
    ).fetchone()["n"]
    if recent >= config.LOGIN_MAX_FAILURES_PER_IP:
        raise HTTPException(429, "Too many failed attempts from this address. Try again later.")


def _fail(conn, user, username, ip, action, message):
    """Count a failed password or code toward the per-user lock and per-IP throttle, then reject."""
    conn.execute("INSERT INTO login_attempts(ip,username,success) VALUES (%s,%s,false)", (ip, username))
    if user is not None and not user["locked"]:
        conn.execute(
            """UPDATE users SET failed_logins=failed_logins+1,
               locked_until=CASE WHEN failed_logins+1>=%s THEN now()+make_interval(mins=>%s) ELSE locked_until END
               WHERE id=%s""",
            (config.LOGIN_MAX_FAILURES_PER_USER, config.LOGIN_LOCK_MINUTES, user["id"]),
        )
    audit.record(username or "?", action, detail={"ip": ip}, conn=conn)
    conn.commit()
    raise HTTPException(401, message)


def _start_session(conn, user, request, response, ip, detail):
    token, th = new_session_token()
    conn.execute("INSERT INTO login_attempts(ip,username,success) VALUES (%s,%s,true)", (ip, user["username"]))
    conn.execute("UPDATE users SET failed_logins=0,locked_until=NULL,last_login_at=now() WHERE id=%s", (user["id"],))
    conn.execute(
        "INSERT INTO sessions(token_hash,user_id,ip,user_agent,expires_at) VALUES (%s,%s,%s,%s,now()+%s)",
        (th, user["id"], ip, (request.headers.get("user-agent") or "")[:200], timedelta(hours=config.SESSION_HOURS)),
    )
    conn.execute("DELETE FROM sessions WHERE expires_at<now()")
    conn.execute("DELETE FROM mfa_challenges WHERE expires_at<now()")
    conn.execute("DELETE FROM login_attempts WHERE at<now()-interval '30 days'")
    audit.record(user["username"], "auth.login", detail={"ip": ip, **detail}, conn=conn)
    response.set_cookie(
        COOKIE, token, httponly=True, secure=config.COOKIE_SECURE, samesite="strict",
        max_age=config.SESSION_HOURS * 3600, path="/",
    )
    return {"username": user["username"], "role": user["role"]}


USER_COLS = "id,username,password_hash,role,active,totp_enabled,totp_secret_enc,totp_last_step,locked_until>now() AS locked"


@router.post("/login")
def login(body: Login, request: Request, response: Response):
    ip = client_ip(request)
    username = body.username.strip().lower()
    with db.connect() as conn:
        _throttle(conn, ip)
        user = conn.execute(f"SELECT {USER_COLS} FROM users WHERE username=%s", (username,)).fetchone()
        ok = False
        if user is None or user["locked"]:
            verify_dummy(body.password)
        else:
            ok = verify_password(body.password, user["password_hash"]) and user["active"]
        if not ok:
            _fail(conn, user, username, ip, "auth.login_failed", GENERIC)
        if user["totp_enabled"]:
            # Password is right; no session until the second factor is checked.
            token, th = new_session_token()
            conn.execute("INSERT INTO mfa_challenges(token_hash,user_id,ip,expires_at) VALUES (%s,%s,%s,now()+%s)",
                         (th, user["id"], ip, timedelta(minutes=MFA_CHALLENGE_MINUTES)))
            return {"mfa_required": True, "mfa_token": token}
        return _start_session(conn, user, request, response, ip, {"mfa": "none"})


@router.post("/login/mfa")
def login_mfa(body: MfaLogin, request: Request, response: Response):
    ip = client_ip(request)
    with db.connect() as conn:
        _throttle(conn, ip)
        ch = conn.execute("SELECT * FROM mfa_challenges WHERE token_hash=%s AND expires_at>now() FOR UPDATE",
                          (token_hash(body.mfa_token),)).fetchone()
        if not ch:
            raise HTTPException(401, "Sign-in expired. Enter your password again.")
        user = conn.execute(f"SELECT {USER_COLS} FROM users WHERE id=%s FOR UPDATE", (ch["user_id"],)).fetchone()
        if user["locked"] or not user["active"] or not user["totp_enabled"]:
            conn.execute("DELETE FROM mfa_challenges WHERE token_hash=%s", (ch["token_hash"],))
            conn.commit()
            raise HTTPException(401, "Sign-in expired. Enter your password again.")
        method = None
        step = totp.verify(decrypt_json(user["totp_secret_enc"])["secret"], body.code, user["totp_last_step"])
        if step is not None:
            conn.execute("UPDATE users SET totp_last_step=%s WHERE id=%s", (step, user["id"]))
            method = "totp"
        elif conn.execute("""UPDATE user_recovery_codes SET used_at=now()
                             WHERE user_id=%s AND code_hash=%s AND used_at IS NULL RETURNING id""",
                          (user["id"], totp.hash_recovery(body.code))).fetchone():
            method = "recovery_code"
        if method is None:
            if ch["attempts"] + 1 >= MFA_MAX_ATTEMPTS:
                conn.execute("DELETE FROM mfa_challenges WHERE token_hash=%s", (ch["token_hash"],))
            else:
                conn.execute("UPDATE mfa_challenges SET attempts=attempts+1 WHERE token_hash=%s", (ch["token_hash"],))
            _fail(conn, user, user["username"], ip, "auth.mfa_failed", "Invalid code")
        conn.execute("DELETE FROM mfa_challenges WHERE token_hash=%s", (ch["token_hash"],))
        result = _start_session(conn, user, request, response, ip, {"mfa": method})
        result["recovery_codes_left"] = conn.execute(
            "SELECT count(*) AS n FROM user_recovery_codes WHERE user_id=%s AND used_at IS NULL", (user["id"],)).fetchone()["n"]
        return result


@router.post("/logout")
def logout(request: Request, response: Response, user=Depends(current_user)):
    db.run("DELETE FROM sessions WHERE token_hash=%s", (token_hash(request.cookies.get(COOKIE, "")),))
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(user=Depends(current_user)):
    return {**user, "mfa_required_for_role": user["role"] in config.MFA_REQUIRED_ROLES,
            "permissions": [] if user["mfa_setup_required"] else sorted(ROLES[user["role"]])}


# ---- two-factor enrolment / management
class MfaCode(BaseModel):
    code: str = Field(max_length=10)


class MfaDisable(BaseModel):
    password: str = Field(max_length=200)
    code: str = Field(max_length=10)


def _issue_recovery_codes(conn, user_id) -> list[str]:
    codes = totp.new_recovery_codes()
    conn.execute("DELETE FROM user_recovery_codes WHERE user_id=%s", (user_id,))
    for c in codes:
        conn.execute("INSERT INTO user_recovery_codes(user_id,code_hash) VALUES (%s,%s)", (user_id, totp.hash_recovery(c)))
    return codes


def _check_current_code(conn, user_id, code):
    u = conn.execute("SELECT totp_secret_enc,totp_last_step,totp_enabled FROM users WHERE id=%s FOR UPDATE", (user_id,)).fetchone()
    if not u["totp_enabled"]:
        raise HTTPException(409, "Two-factor is not enabled")
    step = totp.verify(decrypt_json(u["totp_secret_enc"])["secret"], code, u["totp_last_step"])
    if step is None:
        raise HTTPException(400, "Invalid code")
    conn.execute("UPDATE users SET totp_last_step=%s WHERE id=%s", (step, user_id))


@router.post("/mfa/setup")
def mfa_setup(user=Depends(current_user)):
    """Start enrolment: a new secret is stored (not yet active) until /mfa/enable proves the app has it."""
    if user["totp_enabled"]:
        raise HTTPException(409, "Two-factor is already enabled")
    secret = totp.new_secret()
    db.run("UPDATE users SET totp_secret_enc=%s, totp_last_step=0 WHERE id=%s", (encrypt_json({"secret": secret}), user["id"]))
    return {"secret": secret, "uri": totp.provisioning_uri(secret, user["username"], config.MFA_ISSUER)}


@router.post("/mfa/enable")
def mfa_enable(body: MfaCode, user=Depends(current_user)):
    with db.connect() as conn:
        u = conn.execute("SELECT totp_secret_enc,totp_enabled FROM users WHERE id=%s FOR UPDATE", (user["id"],)).fetchone()
        if u["totp_enabled"]:
            raise HTTPException(409, "Two-factor is already enabled")
        if not u["totp_secret_enc"]:
            raise HTTPException(400, "Start setup first")
        step = totp.verify(decrypt_json(u["totp_secret_enc"])["secret"], body.code)
        if step is None:
            raise HTTPException(400, "Code does not match. Check the phone's clock and try the next code.")
        conn.execute("UPDATE users SET totp_enabled=true, totp_last_step=%s WHERE id=%s", (step, user["id"]))
        codes = _issue_recovery_codes(conn, user["id"])
        audit.record(user["username"], "auth.mfa_enabled", "user", user["id"], conn=conn)
    return {"recovery_codes": codes}


@router.post("/mfa/recovery-codes")
def mfa_new_recovery_codes(body: MfaCode, user=Depends(current_user)):
    with db.connect() as conn:
        _check_current_code(conn, user["id"], body.code)
        codes = _issue_recovery_codes(conn, user["id"])
        audit.record(user["username"], "auth.mfa_recovery_codes_regenerated", "user", user["id"], conn=conn)
    return {"recovery_codes": codes}


@router.post("/mfa/disable")
def mfa_disable(body: MfaDisable, user=Depends(current_user)):
    if user["role"] in config.MFA_REQUIRED_ROLES:
        raise HTTPException(403, f"Two-factor is mandatory for the {user['role']} role")
    with db.connect() as conn:
        stored = conn.execute("SELECT password_hash FROM users WHERE id=%s", (user["id"],)).fetchone()
        if not verify_password(body.password, stored["password_hash"]):
            raise HTTPException(400, "Password is wrong")
        _check_current_code(conn, user["id"], body.code)
        conn.execute("UPDATE users SET totp_enabled=false, totp_secret_enc=NULL, totp_last_step=0 WHERE id=%s", (user["id"],))
        conn.execute("DELETE FROM user_recovery_codes WHERE user_id=%s", (user["id"],))
        audit.record(user["username"], "auth.mfa_disabled", "user", user["id"], conn=conn)
    return {"ok": True}


@router.post("/password")
def change_password(body: PasswordChange, user=Depends(current_user)):
    stored = db.row("SELECT password_hash FROM users WHERE id=%s", (user["id"],))
    if not verify_password(body.current_password, stored["password_hash"]):
        raise HTTPException(400, "Current password is wrong")
    if problem := password_problem(body.new_password):
        raise HTTPException(400, problem)
    with db.connect() as conn:
        conn.execute("UPDATE users SET password_hash=%s WHERE id=%s", (hash_password(body.new_password), user["id"]))
        conn.execute("DELETE FROM sessions WHERE user_id=%s", (user["id"],))
        audit.record(user["username"], "auth.password_changed", "user", user["id"], conn=conn)
    return {"ok": True, "detail": "Password changed. Sign in again."}


# ---- user administration (admin only)
class UserIn(BaseModel):
    username: str = Field(pattern=r"^[a-z0-9._-]{3,40}$")
    full_name: str = Field(default="", max_length=120)
    role: str = Field(pattern="^(admin|noc|billing|support)$")
    password: str = Field(max_length=200)


class UserPatch(BaseModel):
    role: str | None = Field(default=None, pattern="^(admin|noc|billing|support)$")
    active: bool | None = None
    password: str | None = Field(default=None, max_length=200)
    reset_mfa: bool = False  # lost phone: user re-enrols at next sign-in


users = APIRouter(prefix="/api/users", tags=["users"])


@users.get("")
def list_users(user=Depends(require("users"))):
    return db.rows("SELECT id,username,full_name,role,active,totp_enabled,last_login_at,locked_until FROM users ORDER BY username")


@users.post("", status_code=201)
def create_user(body: UserIn, user=Depends(require("users"))):
    if problem := password_problem(body.password):
        raise HTTPException(400, problem)
    with db.connect() as conn:
        if conn.execute("SELECT 1 FROM users WHERE username=%s", (body.username,)).fetchone():
            raise HTTPException(409, "Username taken")
        row = conn.execute(
            "INSERT INTO users(username,full_name,role,password_hash) VALUES (%s,%s,%s,%s) RETURNING id",
            (body.username, body.full_name, body.role, hash_password(body.password)),
        ).fetchone()
        audit.record(user["username"], "user.create", "user", row["id"], {"username": body.username, "role": body.role}, conn=conn)
    return row


@users.patch("/{user_id}")
def update_user(user_id: str, body: UserPatch, user=Depends(require("users"))):
    if str(user_id) == str(user["id"]) and (body.active is False or (body.role and body.role != "admin")):
        raise HTTPException(400, "You cannot demote or disable your own account")
    if str(user_id) == str(user["id"]) and body.reset_mfa:
        raise HTTPException(400, "Another admin must reset your two-factor")
    with db.connect() as conn:
        if body.password is not None:
            if problem := password_problem(body.password):
                raise HTTPException(400, problem)
            conn.execute("UPDATE users SET password_hash=%s,failed_logins=0,locked_until=NULL WHERE id=%s", (hash_password(body.password), user_id))
            conn.execute("DELETE FROM sessions WHERE user_id=%s", (user_id,))
        if body.role is not None:
            # Sign them out so a new role's 2FA requirement applies straight away.
            if conn.execute("UPDATE users SET role=%s WHERE id=%s AND role<>%s RETURNING id", (body.role, user_id, body.role)).fetchone():
                conn.execute("DELETE FROM sessions WHERE user_id=%s", (user_id,))
        if body.reset_mfa:
            conn.execute("UPDATE users SET totp_enabled=false, totp_secret_enc=NULL, totp_last_step=0 WHERE id=%s", (user_id,))
            conn.execute("DELETE FROM user_recovery_codes WHERE user_id=%s", (user_id,))
            conn.execute("DELETE FROM sessions WHERE user_id=%s", (user_id,))
        if body.active is not None:
            conn.execute("UPDATE users SET active=%s WHERE id=%s", (body.active, user_id))
            if not body.active:
                conn.execute("DELETE FROM sessions WHERE user_id=%s", (user_id,))
        audit.record(user["username"], "user.update", "user", user_id,
                     {"role": body.role, "active": body.active, "password_reset": body.password is not None,
                      "mfa_reset": body.reset_mfa}, conn=conn)
    return {"ok": True}
