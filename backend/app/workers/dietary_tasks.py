"""Periodic database-authoritative completion of due dietary days."""

from __future__ import annotations

from datetime import datetime, timezone
import logging

from app.db.session import SessionLocal
from app.services import dietary_records_service as dietary_service
from app.workers.celery_app import celery_app


logger = logging.getLogger(__name__)


def _effective_now(now_iso: str | None) -> datetime:
    if now_iso is None:
        return datetime.now(timezone.utc)
    value = datetime.fromisoformat(now_iso.replace("Z", "+00:00"))
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("now_iso must include timezone")
    return value.astimezone(timezone.utc)


@celery_app.task(name="process_due_dietary_days")
def process_due_dietary_days(
    max_days: int = 100,
    now_iso: str | None = None,
) -> dict[str, int]:
    """Discover, claim, and close due days in isolated transactions.

    Beat delivery is intentionally at-least-once.  PostgreSQL row claims and
    the day/summary database invariants make the resulting transition
    effectively once for each dietary-day record version.
    """

    effective_now = _effective_now(now_iso)
    bounded_max_days = max(1, min(max_days, 500))
    with SessionLocal() as discovery_db:
        day_ids = dietary_service.discover_due_dietary_day_ids(
            discovery_db,
            now=effective_now,
            limit=bounded_max_days,
        )

    counts = {
        "discovered": len(day_ids),
        "processed": 0,
        "ready": 0,
        "waiting_confirmation": 0,
        "incomplete": 0,
        "skipped": 0,
        "failed": 0,
    }
    for day_id in day_ids:
        try:
            with SessionLocal() as db:
                result = dietary_service.auto_complete_due_day_by_id(
                    db,
                    day_id=day_id,
                    now=effective_now,
                )
                if result is None:
                    db.rollback()
                    counts["skipped"] += 1
                    continue
                db.commit()
            state = str(result["state"])
            counts["processed"] += 1
            if state in {"ready", "waiting_confirmation", "incomplete"}:
                counts[state] += 1
        except Exception:
            logger.exception("dietary day completion failed for day_id=%s", day_id)
            counts["failed"] += 1
    return counts
