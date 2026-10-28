import ipaddress
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from .. import config, db
from ..deps import require
from ..services import threats
from .changes import create_change

router = APIRouter(prefix="/api/threats", tags=["threats"])


@router.get("/summary")
def summary(user=Depends(require("read"))):
    return db.row(
        """SELECT
           (SELECT count(*) FROM blocked_addresses WHERE removed_at IS NULL) AS blocked,
           (SELECT count(*) FROM blocked_addresses WHERE removed_at IS NULL AND source='auto') AS auto_blocked,
           (SELECT count(*) FROM security_events WHERE at > now() - interval '24 hours') AS failures_24h,
           (SELECT count(DISTINCT src_ip) FROM security_events WHERE at > now() - interval '24 hours') AS sources_24h,
           (SELECT count(*) FROM devices WHERE vendor='mikrotik' AND blocklist_enforced) AS routers_enforcing,
           (SELECT count(*) FROM devices WHERE vendor='mikrotik' AND credentials_enc IS NOT NULL) AS routers_managed""") | {
        "auto_block": config.THREAT_AUTO_BLOCK, "failures": config.THREAT_FAILURES, "window_min": config.THREAT_WINDOW_MIN,
        "block_hours": config.THREAT_BLOCK_HOURS, "subnet_after": config.THREAT_SUBNET_AFTER}


@router.get("/blocks")
def blocks(history: bool = False, user=Depends(require("read"))):
    return db.rows(
        f"""SELECT id, address::text AS address, reason, source, created_by, hits, created_at, expires_at, removed_at, removed_by
            FROM blocked_addresses {'' if history else 'WHERE removed_at IS NULL'} ORDER BY created_at DESC LIMIT 1000""")


class BlockIn(BaseModel):
    address: str = Field(max_length=50)
    reason: str = Field(min_length=3, max_length=200)
    hours: int | None = Field(default=None, ge=1, le=24 * 365)  # None = until removed

    @field_validator("address")
    @classmethod
    def valid(cls, v):
        net = ipaddress.ip_network(v.strip(), strict=False)
        if net.prefixlen < (16 if net.version == 4 else 32):
            raise ValueError("Refusing to block more than a /16 at once")
        return str(net)


@router.post("/blocks", status_code=201)
def block(body: BlockIn, user=Depends(require("network"))):
    with db.connect() as conn:
        try:
            row = threats.add_block(conn, body.address, body.reason, "manual", user["username"], body.hours)
        except threats.Protected as exc:
            raise HTTPException(400, str(exc)) from exc
        if not row:
            raise HTTPException(409, "Already blocked")
    # Push now rather than waiting for the next poll.
    return {"id": row["id"], "sync": threats.sync_all()}


@router.delete("/blocks/{block_id}")
def unblock(block_id: int, user=Depends(require("network"))):
    with db.connect() as conn:
        if not threats.remove_block(conn, block_id, user["username"]):
            raise HTTPException(404, "Not an active block")
    return {"ok": True, "sync": threats.sync_all()}


@router.get("/events")
def events(ip: str | None = None, user=Depends(require("read"))):
    if ip:
        ipaddress.ip_network(ip, strict=False)
    # One row per source/user/router per minute: a bot retrying every few seconds is one line, with a count.
    return db.rows(
        f"""SELECT max(e.at) AS at, host(e.src_ip) AS src_ip, e.username, e.via, d.name AS device_name, count(*) AS attempts,
                   EXISTS(SELECT 1 FROM blocked_addresses b WHERE b.removed_at IS NULL AND b.address >>= e.src_ip) AS blocked
            FROM security_events e LEFT JOIN devices d ON d.id=e.device_id
            {'WHERE e.src_ip <<= %s::inet' if ip else ''}
            GROUP BY date_trunc('minute', e.at), e.src_ip, e.username, e.via, d.name
            ORDER BY max(e.at) DESC LIMIT 500""", (ip,) if ip else None)


@router.get("/top-sources")
def top_sources(user=Depends(require("read"))):
    return db.rows(
        """SELECT host(src_ip) AS src_ip, count(*) AS failures, count(DISTINCT device_id) AS routers, max(at) AS last_seen,
                  array_agg(DISTINCT username) AS users,
                  EXISTS(SELECT 1 FROM blocked_addresses b WHERE b.removed_at IS NULL AND b.address >>= e.src_ip) AS blocked
           FROM security_events e WHERE at > now() - interval '7 days'
           GROUP BY src_ip ORDER BY failures DESC LIMIT 100""")


@router.get("/enforcement")
def enforcement(user=Depends(require("read"))):
    return db.rows(
        """SELECT d.id, d.name, i.name AS island_name, host(d.management_ip) AS management_ip, d.status,
                  d.blocklist_enforced, d.blocklist_synced_at, d.blocklist_error, (d.credentials_enc IS NOT NULL) AS has_credentials,
                  EXISTS(SELECT 1 FROM config_changes c WHERE c.device_id=d.id AND c.title LIKE 'Enable blocklist enforcement%%'
                         AND c.status IN ('pending','approved')) AS change_open
           FROM devices d LEFT JOIN islands i ON i.id=d.island_id WHERE d.vendor='mikrotik' ORDER BY i.name NULLS FIRST, d.name""")


@router.post("/enforcement/{device_id}", status_code=201)
def request_enforcement(device_id: UUID, user=Depends(require("network"))):
    """One RAW rule that drops the blocklist — reviewed and applied like any other change."""
    with db.connect() as conn:
        return {"change_id": create_change(conn, device_id, "Enable blocklist enforcement (RAW drop of address-list blocklist)",
                                           "mikrotik_script", threats.ENFORCE_SCRIPT, None, user["username"])}
