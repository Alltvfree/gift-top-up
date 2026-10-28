from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from .. import db
from ..deps import require
from ..services import importer

router = APIRouter(prefix="/api/import", tags=["import"])


class ImportIn(BaseModel):
    csv: str = Field(min_length=1, max_length=20_000_000)
    dry_run: bool = True
    default_island_id: UUID | None = None
    create_missing_plans: bool = False


@router.post("/subscribers")
def import_subscribers(body: ImportIn, user=Depends(require("approve"))):
    with db.connect() as conn:
        report = importer.import_subscribers(conn, body.csv, user["username"], dry_run=body.dry_run,
                                             default_island_id=body.default_island_id, create_missing_plans=body.create_missing_plans)
        if body.dry_run:
            conn.rollback()
    return report


@router.post("/nas")
def import_nas(body: ImportIn, user=Depends(require("approve"))):
    with db.connect() as conn:
        report = importer.import_nas(conn, body.csv, user["username"], dry_run=body.dry_run)
        if body.dry_run:
            conn.rollback()
    # FreeRADIUS reads clients at start-up.
    report["note"] = None if body.dry_run else "Restart FreeRADIUS to load the NAS clients: docker compose restart radius"
    return report
