from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from .. import audit, config, db
from ..deps import COOKIE, ROLES, client_ip, current_user, require
from ..security import hash_password, new_session_token, password_problem, token_hash, verify_dummy, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


class Login(BaseModel):
    username: str = Field(max_length=40)
    password: str = Field(max_length=200)


class PasswordChange(BaseModel):
    current_password: str = Field(max_length=200)
    new_password: str = Field(max_length=200)


GENERIC = "Invalid username or password"


@router.post("/login")
def login(body: Login, request: Request, response: Response):
    ip = client_ip(request)
    username = body.username.strip().lower()
    with db.connect() as conn:
        recent = conn.execute(
            "SELECT count(*) AS n FROM login_attempts WHERE ip IS NOT DISTINCT FROM %s AND NOT success AND at>now()-interval '15 minutes'",
            (ip,),
        ).fetchone()["n"]
        if recent >= config.LOGIN_MAX_FAILURES_PER_IP:
            raise HTTPException(429, "Too many failed attempts from this address. Try again later.")
        user = conn.execute(
            "SELECT id,username,password_hash,role,active,failed_logins,locked_until,locked_until>now() AS locked FROM users WHERE username=%s",
            (username,),
        ).fetchone()
        ok = False
        if user is None:
            verify_dummy(body.password)
        elif user["locked"]:
            verify_dummy(body.password)
        else:
            ok = verify_password(body.password, user["password_hash"]) and user["active"]
        conn.execute("INSERT INTO login_attempts(ip,username,success) VALUES (%s,%s,%s)", (ip, username, ok))
        if not ok:
            if user is not None and not user["locked"]:
                conn.execute(
                    """UPDATE users SET failed_logins=failed_logins+1,
                       locked_until=CASE WHEN failed_logins+1>=%s THEN now()+make_interval(mins=>%s) ELSE locked_until END
                       WHERE id=%s""",
                    (config.LOGIN_MAX_FAILURES_PER_USER, config.LOGIN_LOCK_MINUTES, user["id"]),
                )
            audit.record(username or "?", "auth.login_failed", detail={"ip": ip}, conn=conn)
            conn.commit()
            raise HTTPException(401, GENERIC)
        token, th = new_session_token()
        conn.execute("UPDATE users SET failed_logins=0,locked_until=NULL,last_login_at=now() WHERE id=%s", (user["id"],))
        conn.execute(
            "INSERT INTO sessions(token_hash,user_id,ip,user_agent,expires_at) VALUES (%s,%s,%s,%s,now()+%s)",
            (th, user["id"], ip, (request.headers.get("user-agent") or "")[:200], timedelta(hours=config.SESSION_HOURS)),
        )
        conn.execute("DELETE FROM sessions WHERE expires_at<now()")
        conn.execute("DELETE FROM login_attempts WHERE at<now()-interval '30 days'")
        audit.record(user["username"], "auth.login", detail={"ip": ip}, conn=conn)
    response.set_cookie(
        COOKIE, token, httponly=True, secure=config.COOKIE_SECURE, samesite="strict",
        max_age=config.SESSION_HOURS * 3600, path="/",
    )
    return {"username": user["username"], "role": user["role"]}


@router.post("/logout")
def logout(request: Request, response: Response, user=Depends(current_user)):
    db.run("DELETE FROM sessions WHERE token_hash=%s", (token_hash(request.cookies.get(COOKIE, "")),))
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(user=Depends(current_user)):
    return {**user, "permissions": sorted(ROLES[user["role"]])}


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


users = APIRouter(prefix="/api/users", tags=["users"])


@users.get("")
def list_users(user=Depends(require("users"))):
    return db.rows("SELECT id,username,full_name,role,active,last_login_at,locked_until FROM users ORDER BY username")


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
    with db.connect() as conn:
        if body.password is not None:
            if problem := password_problem(body.password):
                raise HTTPException(400, problem)
            conn.execute("UPDATE users SET password_hash=%s,failed_logins=0,locked_until=NULL WHERE id=%s", (hash_password(body.password), user_id))
            conn.execute("DELETE FROM sessions WHERE user_id=%s", (user_id,))
        if body.role is not None:
            conn.execute("UPDATE users SET role=%s WHERE id=%s", (body.role, user_id))
        if body.active is not None:
            conn.execute("UPDATE users SET active=%s WHERE id=%s", (body.active, user_id))
            if not body.active:
                conn.execute("DELETE FROM sessions WHERE user_id=%s", (user_id,))
        audit.record(user["username"], "user.update", "user", user_id,
                     {"role": body.role, "active": body.active, "password_reset": body.password is not None}, conn=conn)
    return {"ok": True}
