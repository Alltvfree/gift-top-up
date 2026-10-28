"""Request authentication, role checks and CSRF guard."""
import ipaddress

from fastapi import Depends, HTTPException, Request

from . import config, db
from .security import token_hash

COOKIE = "isp_session"
# Role -> what it may do. admin implies everything.
ROLES = {
    "admin": {"read", "billing", "subscribers", "network", "approve", "users"},
    "noc": {"read", "subscribers", "network"},
    "billing": {"read", "billing", "subscribers"},
    "support": {"read"},
}
MFA_SETUP_PATHS = {"/api/auth/me", "/api/auth/logout", "/api/auth/mfa/setup", "/api/auth/mfa/enable"}
_TRUSTED = [ipaddress.ip_network(n.strip()) for n in config.TRUSTED_PROXY_NETS if n.strip()]


def client_ip(request: Request) -> str | None:
    """Peer IP; X-Real-IP is honoured only when the peer is our own reverse proxy."""
    try:
        peer = ipaddress.ip_address(request.client.host) if request.client else None
    except ValueError:
        return None
    if peer and any(peer in n for n in _TRUSTED):
        try:
            return str(ipaddress.ip_address(request.headers.get("x-real-ip", "")))
        except ValueError:
            pass
    return str(peer) if peer else None


def current_user(request: Request) -> dict:
    token = request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(401, "Not signed in")
    user = db.row(
        """SELECT u.id,u.username,u.full_name,u.role,u.totp_enabled FROM sessions s JOIN users u ON u.id=s.user_id
           WHERE s.token_hash=%s AND s.expires_at>now() AND u.active""",
        (token_hash(token),),
    )
    if not user:
        raise HTTPException(401, "Session expired")
    # A role that requires 2FA but has not enrolled yet may only enrol (or sign out).
    user["mfa_setup_required"] = user["role"] in config.MFA_REQUIRED_ROLES and not user["totp_enabled"]
    if user["mfa_setup_required"] and request.url.path not in MFA_SETUP_PATHS:
        raise HTTPException(403, "Two-factor authentication must be set up first")
    # Cookies are SameSite=Strict; this header check is a second CSRF layer (forms on other
    # sites cannot set custom headers without a CORS preflight, which we never allow).
    if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get("x-requested-with") != "islandnet":
        raise HTTPException(403, "Missing CSRF header")
    return user


def require(permission: str):
    def checker(user: dict = Depends(current_user)) -> dict:
        if permission not in ROLES.get(user["role"], set()):
            raise HTTPException(403, f"Role '{user['role']}' may not do this")
        return user
    return checker
