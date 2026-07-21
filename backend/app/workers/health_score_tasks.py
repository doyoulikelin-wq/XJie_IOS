"""Celery wake-up and periodic sweep for durable report score jobs."""

from app.db.session import SessionLocal
from app.services.report_score_job_service import claim_score_job, execute_claimed_score_job
from app.workers.celery_app import celery_app


@celery_app.task(name="process_health_report_score_jobs")
def process_health_report_score_jobs(max_jobs: int = 20) -> dict[str, int]:
    processed = 0
    failed = 0
    for _ in range(max(1, min(max_jobs, 100))):
        with SessionLocal() as claim_db:
            claim = claim_score_job(claim_db)
        if not claim:
            break
        job_id, token = claim
        try:
            with SessionLocal() as execution_db:
                execute_claimed_score_job(execution_db, job_id=job_id, lease_token=token)
            processed += 1
        except Exception:
            failed += 1
    return {"processed": processed, "failed": failed}
