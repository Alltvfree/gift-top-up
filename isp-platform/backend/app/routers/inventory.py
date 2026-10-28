from ipaddress import IPv4Address
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from .. import audit, db
from ..deps import require
from ..security import decrypt_json, encrypt_json
from ..services import devices as dev
from ..services import firewall, monitor

router = APIRouter(prefix="/api", tags=["inventory"])
Status = Literal["online", "degraded", "offline", "unknown"]


class IslandIn(BaseModel):
    code: str = Field(min_length=1, max_length=20, pattern=r"^[A-Za-z0-9._-]+$")
    name: str = Field(min_length=1, max_length=80)
    atoll: str | None = Field(default=None, max_length=60)


@router.get("/islands")
def islands(user=Depends(require("read"))):
    return db.rows(
        """SELECT i.id,i.code,i.name,i.atoll,i.status,count(DISTINCT d.id) AS device_count,
                  count(DISTINCT s.id) FILTER (WHERE s.status='active') AS active_subscribers,
                  count(DISTINCT a.id) AS open_alerts
           FROM islands i LEFT JOIN devices d ON d.island_id=i.id
           LEFT JOIN subscribers s ON s.island_id=i.id
           LEFT JOIN alerts a ON a.island_id=i.id AND a.resolved_at IS NULL
           GROUP BY i.id ORDER BY i.name""")


@router.post("/islands", status_code=201)
def create_island(body: IslandIn, user=Depends(require("network"))):
    with db.connect() as conn:
        row = conn.execute("INSERT INTO islands(code,name,atoll) VALUES (%s,%s,%s) ON CONFLICT (code) DO NOTHING RETURNING id",
                           (body.code.upper(), body.name, body.atoll)).fetchone()
        if not row:
            raise HTTPException(409, "Island code already exists")
        audit.record(user["username"], "island.create", "island", row["id"], body.model_dump(), conn=conn)
    return row


@router.put("/islands/{island_id}")
def update_island(island_id: UUID, body: IslandIn, user=Depends(require("network"))):
    with db.connect() as conn:
        if not conn.execute("UPDATE islands SET code=%s,name=%s,atoll=%s WHERE id=%s RETURNING id",
                            (body.code.upper(), body.name, body.atoll, island_id)).fetchone():
            raise HTTPException(404, "Island not found")
        audit.record(user["username"], "island.update", "island", island_id, body.model_dump(), conn=conn)
    return {"ok": True}


@router.delete("/islands/{island_id}")
def delete_island(island_id: UUID, user=Depends(require("approve"))):
    with db.connect() as conn:
        if conn.execute("SELECT 1 FROM devices WHERE island_id=%s UNION SELECT 1 FROM subscribers WHERE island_id=%s LIMIT 1",
                        (island_id, island_id)).fetchone():
            raise HTTPException(409, "Island still has devices or subscribers")
        conn.execute("DELETE FROM islands WHERE id=%s", (island_id,))
        audit.record(user["username"], "island.delete", "island", island_id, conn=conn)
    return {"ok": True}


# ---------------- devices
class Credentials(BaseModel):
    username: str | None = Field(default=None, max_length=64)
    password: str | None = Field(default=None, max_length=128)
    snmp_community: str | None = Field(default=None, max_length=64)


class DeviceIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    island_id: UUID | None = None
    parent_device_id: UUID | None = None
    vendor: Literal["mikrotik", "huawei", "ubiquiti", "other"]
    role: Literal["core_router", "island_router", "olt", "backhaul", "radius", "other"]
    management_ip: IPv4Address | None = None
    mgmt_port: int | None = Field(default=None, ge=1, le=65535)
    model: str | None = Field(default=None, max_length=80)
    poll_enabled: bool = True
    ssh_host_key: str | None = Field(default=None, max_length=120, pattern=r"^SHA256:[A-Za-z0-9+/]{43}$")
    settings: dict = Field(default_factory=dict)
    notes: str | None = Field(default=None, max_length=1000)
    credentials: Credentials | None = None  # write-only; never returned


DEVICE_COLS = """d.id,d.name,d.vendor,d.role,host(d.management_ip) AS management_ip,d.mgmt_port,d.model,d.software_version,
 d.status,d.last_seen_at,d.last_poll_error,d.poll_enabled,d.ssh_host_key,d.settings,d.notes,d.island_id,d.parent_device_id,
 i.name AS island_name,(d.credentials_enc IS NOT NULL) AS has_credentials"""


@router.get("/devices")
def devices(user=Depends(require("read"))):
    return db.rows(f"SELECT {DEVICE_COLS} FROM devices d LEFT JOIN islands i ON i.id=d.island_id ORDER BY i.name NULLS FIRST,d.name")


@router.get("/devices/{device_id}")
def device(device_id: UUID, user=Depends(require("read"))):
    row = db.row(f"SELECT {DEVICE_COLS} FROM devices d LEFT JOIN islands i ON i.id=d.island_id WHERE d.id=%s", (device_id,))
    if not row:
        raise HTTPException(404, "Device not found")
    row["metrics"] = db.rows(
        """SELECT at,reachable,latency_ms,packet_loss_pct,cpu_load_pct,mem_used_pct,uptime_s,extra
           FROM device_metrics WHERE device_id=%s ORDER BY at DESC LIMIT 288""", (device_id,))
    row["alerts"] = db.rows("SELECT * FROM alerts WHERE device_id=%s ORDER BY opened_at DESC LIMIT 50", (device_id,))
    return row


def _merge_creds(existing_enc, new: Credentials | None):
    if new is None:
        return existing_enc
    merged = {**decrypt_json(existing_enc), **{k: v for k, v in new.model_dump().items() if v not in (None, "")}}
    return encrypt_json(merged) if merged else None


@router.post("/devices", status_code=201)
def create_device(body: DeviceIn, user=Depends(require("network"))):
    with db.connect() as conn:
        row = conn.execute(
            """INSERT INTO devices(name,island_id,parent_device_id,vendor,role,management_ip,mgmt_port,model,poll_enabled,
                                   ssh_host_key,settings,notes,credentials_enc)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (body.name, body.island_id, body.parent_device_id, body.vendor, body.role,
             str(body.management_ip) if body.management_ip else None, body.mgmt_port, body.model, body.poll_enabled,
             body.ssh_host_key, Jsonb(body.settings), body.notes, _merge_creds(None, body.credentials)),
        ).fetchone()
        audit.record(user["username"], "device.create", "device", row["id"],
                     body.model_dump(mode="json", exclude={"credentials"}), conn=conn)
    return row


@router.put("/devices/{device_id}")
def update_device(device_id: UUID, body: DeviceIn, user=Depends(require("network"))):
    with db.connect() as conn:
        cur = conn.execute("SELECT credentials_enc FROM devices WHERE id=%s FOR UPDATE", (device_id,)).fetchone()
        if not cur:
            raise HTTPException(404, "Device not found")
        conn.execute(
            """UPDATE devices SET name=%s,island_id=%s,parent_device_id=%s,vendor=%s,role=%s,management_ip=%s,mgmt_port=%s,
               model=%s,poll_enabled=%s,ssh_host_key=%s,settings=%s,notes=%s,credentials_enc=%s WHERE id=%s""",
            (body.name, body.island_id, body.parent_device_id, body.vendor, body.role,
             str(body.management_ip) if body.management_ip else None, body.mgmt_port, body.model, body.poll_enabled,
             body.ssh_host_key, Jsonb(body.settings), body.notes, _merge_creds(cur["credentials_enc"], body.credentials), device_id),
        )
        audit.record(user["username"], "device.update", "device", device_id,
                     {**body.model_dump(mode="json", exclude={"credentials"}), "credentials_changed": body.credentials is not None}, conn=conn)
    return {"ok": True}


@router.delete("/devices/{device_id}")
def delete_device(device_id: UUID, user=Depends(require("approve"))):
    with db.connect() as conn:
        conn.execute("DELETE FROM devices WHERE id=%s", (device_id,))
        audit.record(user["username"], "device.delete", "device", device_id, conn=conn)
    return {"ok": True}


@router.post("/devices/{device_id}/poll")
def poll_now(device_id: UUID, user=Depends(require("network"))):
    return monitor.sweep(cycle=0, device_ids=[device_id])


@router.get("/devices/{device_id}/security-audit")
def security_audit(device_id: UUID, user=Depends(require("network"))):
    d = db.row("SELECT * FROM devices WHERE id=%s", (device_id,))
    if not d or d["vendor"] != "mikrotik":
        raise HTTPException(400, "Security audit is available for MikroTik devices")
    try:
        with dev.mikrotik(d) as ros:
            snap = ros.firewall_snapshot()
    except Exception as exc:  # unreachable, bad credentials, TLS, ...

        raise HTTPException(502, f"Could not read router: {exc}") from exc
    findings = firewall.audit(snap)
    audit.record(user["username"], "device.security_audit", "device", device_id,
                 {"critical": sum(f["severity"] == "critical" for f in findings)})
    return {"device": d["name"], "findings": findings}


# ---------------- backhaul links
class LinkIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: Literal["fiber", "airfiber", "other"]
    a_device_id: UUID | None = None
    b_device_id: UUID | None = None
    capacity_mbps: int | None = Field(default=None, ge=1)


@router.get("/links")
def links(user=Depends(require("read"))):
    return db.rows(
        """SELECT l.*, a.name AS a_name, b.name AS b_name, ia.name AS a_island, ib.name AS b_island
           FROM backhaul_links l LEFT JOIN devices a ON a.id=l.a_device_id LEFT JOIN devices b ON b.id=l.b_device_id
           LEFT JOIN islands ia ON ia.id=a.island_id LEFT JOIN islands ib ON ib.id=b.island_id ORDER BY l.name""")


@router.post("/links", status_code=201)
def create_link(body: LinkIn, user=Depends(require("network"))):
    with db.connect() as conn:
        row = conn.execute(
            "INSERT INTO backhaul_links(name,kind,a_device_id,b_device_id,capacity_mbps) VALUES (%s,%s,%s,%s,%s) RETURNING id",
            (body.name, body.kind, body.a_device_id, body.b_device_id, body.capacity_mbps)).fetchone()
        audit.record(user["username"], "link.create", "link", row["id"], body.model_dump(mode="json"), conn=conn)
    return row


@router.delete("/links/{link_id}")
def delete_link(link_id: UUID, user=Depends(require("network"))):
    with db.connect() as conn:
        conn.execute("DELETE FROM backhaul_links WHERE id=%s", (link_id,))
        audit.record(user["username"], "link.delete", "link", link_id, conn=conn)
    return {"ok": True}
