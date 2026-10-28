from ipaddress import IPv4Address
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import audit, db
from ..deps import require

router = APIRouter(prefix="/api/radius", tags=["radius"])


@router.get("/sessions")
def sessions(active: bool = True, user=Depends(require("read"))):
    return db.rows(
        f"""SELECT a.username, s.full_name, s.account_number, host(a.nasipaddress) AS nas, n.shortname AS nas_name,
                   host(a.framedipaddress) AS ip, a.callingstationid AS mac, a.acctstarttime, a.acctstoptime,
                   a.acctsessiontime, a.acctinputoctets, a.acctoutputoctets, a.acctterminatecause
            FROM radacct a LEFT JOIN subscribers s ON s.pppoe_username=a.username
            LEFT JOIN nas n ON n.nasname=host(a.nasipaddress)
            WHERE {'a.acctstoptime IS NULL' if active else 'true'} ORDER BY a.acctstarttime DESC LIMIT 1000""")


@router.get("/auth-log")
def auth_log(rejects_only: bool = False, user=Depends(require("read"))):
    return db.rows(
        f"""SELECT username, reply, callingstationid, authdate FROM radpostauth
            {"WHERE reply <> 'Access-Accept'" if rejects_only else ''} ORDER BY authdate DESC LIMIT 500""")


class NasIn(BaseModel):
    nasname: IPv4Address
    shortname: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9._-]+$")
    secret: str = Field(min_length=12, max_length=64, pattern=r"^[A-Za-z0-9._@#%+=-]+$")
    device_id: UUID | None = None
    description: str | None = Field(default=None, max_length=200)


@router.get("/nas")
def nas_list(user=Depends(require("network"))):
    # Secrets are not returned.
    return db.rows("SELECT id,nasname,shortname,type,description,device_id FROM nas ORDER BY shortname")


@router.post("/nas", status_code=201)
def nas_create(body: NasIn, user=Depends(require("network"))):
    with db.connect() as conn:
        row = conn.execute(
            """INSERT INTO nas(nasname,shortname,type,secret,description,device_id) VALUES (%s,%s,'other',%s,%s,%s)
               ON CONFLICT (nasname) DO UPDATE SET shortname=EXCLUDED.shortname, secret=EXCLUDED.secret,
               description=EXCLUDED.description, device_id=EXCLUDED.device_id RETURNING id""",
            (str(body.nasname), body.shortname, body.secret, body.description, body.device_id)).fetchone()
        audit.record(user["username"], "radius.nas_upsert", "nas", row["id"], {"nasname": str(body.nasname)}, conn=conn)
    # FreeRADIUS reads clients at start: restart the radius container after adding a NAS.
    return {"id": row["id"], "note": "Restart FreeRADIUS to load new clients"}


@router.delete("/nas/{nas_id}")
def nas_delete(nas_id: int, user=Depends(require("network"))):
    with db.connect() as conn:
        if not conn.execute("DELETE FROM nas WHERE id=%s RETURNING id", (nas_id,)).fetchone():
            raise HTTPException(404, "NAS not found")
        audit.record(user["username"], "radius.nas_delete", "nas", nas_id, conn=conn)
    return {"ok": True}
