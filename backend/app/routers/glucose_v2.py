from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_user_id, get_db
from app.models.glucose import GlucoseReading
from app.schemas.glucose import GlucoseImportResponse, GlucoseSummary
from app.services.etl.glucose_etl import _parse_clarity_csv  # noqa: PLC2701
from app.services.glucose_service import get_glucose_points, get_glucose_summary
from app.utils.csv_import import parse_glucose_payload

router = APIRouter()

DATA_DIR = Path(getattr(settings, "DATA_DIR", "/app/data"))


@router.get("/range")
def glucose_range(
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Return the min/max timestamp of all glucose data for this user."""
    row = db.execute(
        select(func.min(GlucoseReading.ts), func.max(GlucoseReading.ts), func.count(GlucoseReading.id))
        .where(GlucoseReading.user_id == user_id)
    ).one()
    if row[2] == 0:
        return {"min_ts": None, "max_ts": None, "count": 0}
    return {
        "min_ts": row[0].isoformat() if row[0] else None,
        "max_ts": row[1].isoformat() if row[1] else None,
        "count": row[2],
    }


@router.get("")
def list_glucose(
    from_ts: datetime = Query(alias="from"),
    to_ts: datetime = Query(alias="to"),
    limit: int = Query(default=2000, ge=1, le=10000),
    user_id: int = 8,
    db: Session = Depends(get_db),
):
    if to_ts <= from_ts:
        raise HTTPException(status_code=400, detail={"error_code": "BAD_RANGE", "message": "to must be > from"})

    rows = get_glucose_points(db, user_id, from_ts, to_ts)
    # Down-sample if too many points
    if len(rows) > limit:
        step = len(rows) / limit
        rows = [rows[int(i * step)] for i in range(limit)]
    return [
        {
            "id": str(r.id),
            "ts": r.ts,
            "glucose_mgdl": round(r.glucose_mgdl / 18 ,1),
            "source": r.source,
        }
        for r in rows
    ]


@router.get("/summary", response_model=GlucoseSummary)
def summary(
    window: str = Query(default="24h", pattern="^(24h|7d|30d)$"),
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        result = get_glucose_summary(db, user_id, window)
        if result.get("avg") is not None:
            result["avg"] = round(result["avg"] / 18, 1)
        if result.get("min") is not None:
            result["min"] = round(result["min"] / 18, 1)
        if result.get("max") is not None:
            result["max"] = round(result["max"] / 18, 1)
        return GlucoseSummary(**result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"error_code": "BAD_WINDOW", "message": str(exc)}) from exc

