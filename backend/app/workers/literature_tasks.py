"""Celery tasks for literature ingestion (weekly delta crawl)."""
from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from pathlib import Path

from celery import shared_task

from app.db.session import SessionLocal
from app.services.literature.ingest import ingest_pubmed_query

logger = logging.getLogger(__name__)

_OMICS_SEEDS_PATH = Path(__file__).parent / "omics_literature_seeds.json"


@shared_task(name="weekly_omics_literature_ingest")
def weekly_omics_literature_ingest(days_back: int = 14, per_query_max: int = 5) -> dict:
    """Each Monday 03:00 — incrementally crawl recent omics papers.

    Strategy:
      - Restrict each seed query to the last `days_back` days via &mindate.
      - Cap per query at `per_query_max` (default 5) to keep job <30 min.
      - Skip duplicates (handled by ingest_pubmed_query via PMID uniqueness).
    """
    if not _OMICS_SEEDS_PATH.exists():
        logger.warning("omics seeds file missing: %s", _OMICS_SEEDS_PATH)
        return {"status": "skipped", "reason": "no seeds file"}

    seeds = json.loads(_OMICS_SEEDS_PATH.read_text(encoding="utf-8"))
    since = (date.today() - timedelta(days=days_back)).strftime("%Y/%m/%d")

    total_inserted = 0
    total_jobs = 0
    db = SessionLocal()
    try:
        for s in seeds:
            query = f"{s['query']} AND (\"{since}\"[PDAT] : \"3000\"[PDAT])"
            try:
                job = ingest_pubmed_query(
                    db,
                    query=query,
                    topic=s["topic"],
                    max_results=per_query_max,
                    min_year=s.get("min_year"),
                )
                # Tag claims if a tag is provided in the seed
                _apply_tag(db, job_id=job.id, tag=s.get("tag"))
                total_inserted += job.inserted_count
                total_jobs += 1
            except Exception as exc:  # noqa: BLE001
                logger.exception("weekly omics ingest failed for query %r: %s", query, exc)
                continue
    finally:
        db.close()

    return {"status": "ok", "jobs": total_jobs, "inserted": total_inserted, "since": since}


def _apply_tag(db, *, job_id: int, tag: str | None) -> None:
    """Append a tag to all claims created in this ingest job (cheap heuristic)."""
    if not tag:
        return
    from app.models.literature import Claim, IngestJob, Literature
    from sqlalchemy import select

    job = db.get(IngestJob, job_id)
    if not job or job.inserted_count == 0:
        return
    # Heuristic: claims whose literature was inserted in this run are the most recent N.
    rows = db.execute(
        select(Claim)
        .join(Literature, Claim.literature_id == Literature.id)
        .order_by(Claim.id.desc())
        .limit(job.inserted_count * 3)
    ).scalars().all()
    for c in rows:
        if tag not in (c.tags or []):
            c.tags = [*(c.tags or []), tag]
    db.commit()
