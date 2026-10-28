from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import audit, db
from ..adapters import huawei
from ..deps import require
from ..services import devices as dev
from .changes import create_change

router = APIRouter(prefix="/api/olt", tags=["olt"])


def _olt(device_id):
    d = db.row("SELECT * FROM devices WHERE id=%s AND vendor='huawei' AND role='olt'", (device_id,))
    if not d:
        raise HTTPException(404, "Huawei OLT not found")
    return d


@router.get("/onts")
def onts(olt_id: UUID | None = None, user=Depends(require("read"))):
    return db.rows(
        f"""SELECT o.*, d.name AS olt_name, s.account_number, s.full_name, s.pppoe_username
            FROM onts o JOIN devices d ON d.id=o.olt_device_id LEFT JOIN subscribers s ON s.id=o.subscriber_id
            {'WHERE o.olt_device_id=%s' if olt_id else ''} ORDER BY d.name,o.frame,o.slot,o.port,o.ont_id""",
        (olt_id,) if olt_id else None)


@router.get("/{olt_id}/autofind")
def autofind(olt_id: UUID, user=Depends(require("network"))):
    d = _olt(olt_id)
    try:
        with dev.olt(d) as olt:
            return olt.autofind()
    except Exception as exc:
        raise HTTPException(502, f"OLT: {exc}") from exc


@router.get("/{olt_id}/optical/{frame}/{slot}/{port}/{ont_id}")
def optical(olt_id: UUID, frame: int, slot: int, port: int, ont_id: int, user=Depends(require("read"))):
    d = _olt(olt_id)
    try:
        with dev.olt(d) as olt:
            return olt.optical(frame, slot, port, ont_id)
    except Exception as exc:
        raise HTTPException(502, f"OLT: {exc}") from exc


class ProvisionIn(BaseModel):
    subscriber_id: UUID
    serial: str = Field(pattern=r"^[0-9A-Fa-f]{16}$")
    frame: int = Field(ge=0, le=7, default=0)
    slot: int = Field(ge=0, le=21)
    port: int = Field(ge=0, le=15)
    ont_id: int | None = Field(default=None, ge=0, le=127)
    line_profile_id: int = Field(ge=0, le=8192)
    service_profile_id: int = Field(ge=0, le=8192)
    vlan: int = Field(ge=1, le=4094)
    gemport: int = Field(ge=0, le=1023, default=1)


@router.post("/{olt_id}/provision", status_code=201)
def provision(olt_id: UUID, body: ProvisionIn, user=Depends(require("network"))):
    """Builds the ONT add + PPPoE + service-port commands as a change awaiting approval."""
    _olt(olt_id)
    with db.connect() as conn:
        sub = conn.execute("SELECT * FROM subscribers WHERE id=%s", (body.subscriber_id,)).fetchone()
        if not sub:
            raise HTTPException(404, "Subscriber not found")
        pw = conn.execute("SELECT value FROM radcheck WHERE username=%s AND attribute='Cleartext-Password'",
                          (sub["pppoe_username"],)).fetchone()
        if not pw:
            raise HTTPException(400, "Subscriber has no RADIUS password; reset it first")
        ont_id = body.ont_id
        if ont_id is None:
            used = {r["ont_id"] for r in conn.execute(
                "SELECT ont_id FROM onts WHERE olt_device_id=%s AND frame=%s AND slot=%s AND port=%s AND ont_id IS NOT NULL",
                (olt_id, body.frame, body.slot, body.port))}
            ont_id = next(i for i in range(128) if i not in used)
        try:
            apply_lines, rollback = huawei.build_ont_provision(
                frame=body.frame, slot=body.slot, port=body.port, ont_id=ont_id, serial=body.serial,
                line_profile_id=body.line_profile_id, service_profile_id=body.service_profile_id,
                vlan=body.vlan, gemport=body.gemport, description=sub["account_number"],
                pppoe_username=sub["pppoe_username"], pppoe_password=pw["value"])
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        conn.execute(
            """INSERT INTO onts(olt_device_id,subscriber_id,frame,slot,port,ont_id,serial,description,line_profile_id,service_profile_id,vlan)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (olt_device_id,serial) DO UPDATE SET subscriber_id=EXCLUDED.subscriber_id, frame=EXCLUDED.frame,
               slot=EXCLUDED.slot, port=EXCLUDED.port, ont_id=EXCLUDED.ont_id, vlan=EXCLUDED.vlan""",
            (olt_id, body.subscriber_id, body.frame, body.slot, body.port, ont_id, body.serial.upper(), sub["account_number"],
             body.line_profile_id, body.service_profile_id, body.vlan))
        change_id = create_change(conn, olt_id, f"Provision ONT {body.serial.upper()} for {sub['account_number']}",
                                  "huawei_cli", "\n".join(apply_lines), "\n".join(rollback), user["username"])
    return {"change_id": change_id, "ont_id": ont_id}


@router.post("/onts/{ont_uuid}/reboot", status_code=201)
def reboot(ont_uuid: UUID, user=Depends(require("network"))):
    o = db.row("SELECT * FROM onts WHERE id=%s", (ont_uuid,))
    if not o or o["ont_id"] is None:
        raise HTTPException(404, "ONT not found")
    with db.connect() as conn:
        change_id = create_change(conn, o["olt_device_id"], f"Reboot ONT {o['serial']}", "huawei_cli",
                                  "\n".join(huawei.build_ont_reboot(o["frame"], o["slot"], o["port"], o["ont_id"])), None, user["username"])
        audit.record(user["username"], "ont.reboot_requested", "ont", ont_uuid, conn=conn)
    return {"change_id": change_id}
