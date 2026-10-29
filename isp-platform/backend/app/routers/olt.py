from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import audit, config, db
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


def _bucket_sql():
    return (f"""CASE WHEN o.run_state <> 'online' THEN 'offline' WHEN o.rx_power_dbm IS NULL THEN 'unknown'
                 WHEN o.rx_power_dbm >= {float(config.ONT_RX_GOOD)} THEN 'good'
                 WHEN o.rx_power_dbm >= {float(config.ONT_RX_ACCEPTABLE)} THEN 'acceptable'
                 WHEN o.rx_power_dbm >= {float(config.ONT_RX_WEAK)} THEN 'weak' ELSE 'bad' END""")


@router.get("/overview")
def overview(user=Depends(require("read"))):
    """Every OLT with ONT counts, signal health, autofind queue and the NAS it hangs off."""
    rows = db.rows(
        f"""SELECT d.id, d.name, d.status, host(d.management_ip) AS host, d.model, i.name AS island_name, p.name AS nas_name,
                   count(o.id) AS total, count(o.id) FILTER (WHERE o.run_state='online') AS online,
                   count(o.id) FILTER (WHERE ({_bucket_sql()}) IN ('weak','bad')) AS weak_bad,
                   max(o.polled_at) AS polled_at
            FROM devices d LEFT JOIN islands i ON i.id=d.island_id LEFT JOIN devices p ON p.id=d.parent_device_id
            LEFT JOIN onts o ON o.olt_device_id=d.id
            WHERE d.vendor='huawei' AND d.role='olt' GROUP BY d.id, i.name, p.name ORDER BY i.name NULLS LAST, d.name""")
    waiting = {str(r["device_id"]): r["n"] for r in db.rows(
        """SELECT DISTINCT ON (device_id) device_id, jsonb_array_length(coalesce(extra->'autofind','[]'::jsonb)) AS n
           FROM device_metrics WHERE extra ? 'autofind' ORDER BY device_id, at DESC""")}
    for r in rows:
        r["waiting"] = waiting.get(str(r["id"]), 0)
    return rows


@router.get("/{olt_id}/summary")
def summary(olt_id: UUID, user=Depends(require("read"))):
    d = _olt(olt_id)
    counts = db.row(
        f"""SELECT count(*) AS total, count(*) FILTER (WHERE run_state='online') AS online,
                   count(*) FILTER (WHERE run_state<>'online') AS offline,
                   {", ".join(f"count(*) FILTER (WHERE b='{k}') AS {k}" for k in ("good", "acceptable", "weak", "bad", "unknown"))},
                   max(polled_at) AS polled_at
            FROM (SELECT o.*, {_bucket_sql()} AS b FROM onts o WHERE o.olt_device_id=%s) o""", (olt_id,))
    ports = db.rows("""SELECT frame||'/'||slot||'/'||port AS port, count(*) AS total, count(*) FILTER (WHERE run_state='online') AS online
                       FROM onts WHERE olt_device_id=%s GROUP BY frame, slot, port ORDER BY frame, slot, port""", (olt_id,))
    last = db.row("""SELECT extra->'autofind' AS autofind, at FROM device_metrics WHERE device_id=%s AND extra ? 'autofind'
                     ORDER BY at DESC LIMIT 1""", (olt_id,))
    parent = db.row("SELECT name, host(management_ip) AS ip FROM devices WHERE id=%s", (d["parent_device_id"],)) if d.get("parent_device_id") else None
    return {"olt": {"id": d["id"], "name": d["name"], "host": str(d["management_ip"]) if d["management_ip"] else None,
                    "status": d["status"], "model": d["model"], "last_seen_at": d["last_seen_at"], "last_poll_error": d["last_poll_error"]},
            "nas": parent, "counts": counts, "ports": ports,
            "autofind": (last or {}).get("autofind") or [], "autofind_at": (last or {}).get("at"),
            "thresholds": {"good": config.ONT_RX_GOOD, "acceptable": config.ONT_RX_ACCEPTABLE, "weak": config.ONT_RX_WEAK}}


SORTS = {"port": "o.frame, o.slot, o.port, o.ont_id", "signal": "o.rx_power_dbm ASC NULLS LAST",
         "description": "o.description NULLS LAST", "last_seen": "o.last_seen_at DESC NULLS LAST"}


@router.get("/onts")
def onts(olt_id: UUID | None = None, port: str | None = None, status: str | None = None, signal: str | None = None,
         q: str | None = None, subscriber_id: UUID | None = None, sort: str = "port", limit: int = 100, offset: int = 0,
         user=Depends(require("read"))):
    where, params = ["true"], []
    if olt_id:
        where.append("o.olt_device_id=%s"); params.append(olt_id)
    if subscriber_id:
        where.append("o.subscriber_id=%s"); params.append(subscriber_id)
    if port:
        try:
            f, sl, p = (int(x) for x in port.split("/"))
        except ValueError as exc:
            raise HTTPException(400, "port must look like 0/1/3") from exc
        where.append("(o.frame, o.slot, o.port) = (%s, %s, %s)"); params += [f, sl, p]
    if status in ("online", "offline"):
        where.append("o.run_state = 'online'" if status == "online" else "o.run_state <> 'online'")
    if signal in ("good", "acceptable", "weak", "bad", "unknown", "offline"):
        where.append(f"({_bucket_sql()}) = %s"); params.append(signal)
    if q:
        where.append("(o.description ILIKE %s OR o.serial ILIKE %s OR s.account_number ILIKE %s OR s.full_name ILIKE %s OR s.pppoe_username ILIKE %s)")
        params += [f"%{q.strip()}%"] * 5
    sql_where = " AND ".join(where)
    base = "FROM onts o JOIN devices d ON d.id=o.olt_device_id LEFT JOIN subscribers s ON s.id=o.subscriber_id WHERE " + sql_where
    total = db.row(f"SELECT count(*) AS n {base}", params)["n"]
    rows = db.rows(
        f"""SELECT o.*, d.name AS olt_name, s.account_number, s.full_name, s.pppoe_username, ({_bucket_sql()}) AS signal
            {base} ORDER BY {SORTS.get(sort, SORTS['port'])} LIMIT %s OFFSET %s""", params + [min(max(limit, 1), 1000), max(offset, 0)])
    return {"total": total, "rows": rows}


def _ont(ont_uuid):
    o = db.row("SELECT * FROM onts WHERE id=%s", (ont_uuid,))
    if not o or o["ont_id"] is None:
        raise HTTPException(404, "ONT not found")
    return o, _olt(o["olt_device_id"])


@router.get("/onts/{ont_uuid}/signal")
def live_signal(ont_uuid: UUID, user=Depends(require("read"))):
    o, d = _ont(ont_uuid)
    try:
        with dev.olt(d) as olt:
            r = huawei.parse_optical(olt.on_board(o["frame"], o["slot"], f"display ont optical-info {o['port']} {o['ont_id']}"))
    except Exception as exc:
        raise HTTPException(502, f"OLT: {exc}") from exc
    db.run("UPDATE onts SET rx_power_dbm=%s, olt_rx_power_dbm=%s, temperature_c=%s, polled_at=now() WHERE id=%s",
           (r["rx_power_dbm"], r["olt_rx_power_dbm"], r["temperature_c"], ont_uuid))
    return r


@router.get("/onts/{ont_uuid}/config")
def ont_config(ont_uuid: UUID, user=Depends(require("network"))):
    o, d = _ont(ont_uuid)
    try:
        with dev.olt(d) as olt:
            text = olt.ont_config(o["frame"], o["slot"], o["port"], o["ont_id"])
    except Exception as exc:
        raise HTTPException(502, f"OLT: {exc}") from exc
    parsed = huawei.parse_ont_config(text)
    if parsed["line_profile_id"] is not None:
        db.run("UPDATE onts SET line_profile_id=%s, service_profile_id=%s, vlan=COALESCE(%s, vlan) WHERE id=%s",
               (parsed["line_profile_id"], parsed["service_profile_id"], parsed["vlan"], ont_uuid))
    audit.record(user["username"], "ont.read_config", "ont", ont_uuid)
    return {"text": text, "parsed": parsed}


class OntState(BaseModel):
    active: bool


@router.post("/onts/{ont_uuid}/state")
def ont_state(ont_uuid: UUID, body: OntState, user=Depends(require("network"))):
    """ont activate / deactivate: deactivating cuts the customer's fibre service until re-activated."""
    o, d = _ont(ont_uuid)
    cmd = f"ont {'activate' if body.active else 'deactivate'} {o['port']} {o['ont_id']}"
    try:
        with dev.olt(d) as olt:
            out = olt.on_board(o["frame"], o["slot"], cmd, confirm=True)
    except Exception as exc:
        raise HTTPException(502, f"OLT: {exc}") from exc
    db.run("UPDATE onts SET control=%s WHERE id=%s", ("active" if body.active else "deactivated", ont_uuid))
    audit.record(user["username"], f"ont.{'activate' if body.active else 'deactivate'}", "ont", ont_uuid,
                 {"olt": d["name"], "position": f"{o['frame']}/{o['slot']}/{o['port']}:{o['ont_id']}", "serial": o["serial"]})
    return {"ok": True, "output": out.strip()[-500:]}


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


@router.post("/onts/{ont_uuid}/reboot")
def reboot(ont_uuid: UUID, user=Depends(require("network"))):
    """Restart one ONT now (everyday NOC action, audited; no approval needed)."""
    o, d = _ont(ont_uuid)
    try:
        with dev.olt(d) as olt:
            out = olt.on_board(o["frame"], o["slot"], f"ont reset {o['port']} {o['ont_id']}", confirm=True)
    except Exception as exc:
        raise HTTPException(502, f"OLT: {exc}") from exc
    audit.record(user["username"], "ont.reboot", "ont", ont_uuid,
                 {"olt": d["name"], "position": f"{o['frame']}/{o['slot']}/{o['port']}:{o['ont_id']}", "serial": o["serial"]})
    return {"ok": True, "output": out.strip()[-500:]}
