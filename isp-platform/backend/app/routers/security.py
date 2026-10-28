from dataclasses import fields
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import db
from ..deps import require
from ..services import firewall
from .changes import create_change

router = APIRouter(prefix="/api/security", tags=["security"])


class FirewallRequest(BaseModel):
    role: Literal["core_router", "island_router"]
    mgmt_networks: list[str] = Field(min_length=1)
    nms_addresses: list[str] = []
    uplink_interfaces: list[str] = Field(min_length=1)
    backhaul_interfaces: list[str] = []
    customer_interfaces: list[str] = []
    mgmt_interfaces: list[str] = []
    customer_pools: list[str] = []
    radius_servers: list[str] = []
    portal_ip: str | None = None
    dns_cache: bool = True
    routing_protocol: Literal["ospf", "bgp", "none"] = "ospf"
    snmp_community: str | None = None
    block_smtp_from_customers: bool = True
    isolate_customers: bool = True
    customers_have_public_ip: bool = False
    pppoe_service_name: str = "isp"
    radius_secret: str | None = None
    radius_src_address: str | None = None
    local_address: str | None = None
    # Optional: turn the script straight into a change request for this device.
    device_id: UUID | None = None


@router.post("/firewall")
def generate_firewall(body: FirewallRequest, user=Depends(require("network"))):
    data = body.model_dump()
    device_id = data.pop("device_id")
    names = {f.name for f in fields(firewall.FirewallInput)}
    cfg = firewall.FirewallInput(**{k: v for k, v in data.items() if k in names and v not in (None, "")})
    try:
        script = firewall.generate(cfg)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    result = {"script": script}
    if device_id:
        with db.connect() as conn:
            result["change_id"] = create_change(conn, device_id, f"Firewall/hardening ({body.role})", "mikrotik_script",
                                                script, None, user["username"])
    return result
