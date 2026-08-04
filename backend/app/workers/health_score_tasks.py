"""Celery wake-up and periodic sweep for durable report score jobs."""

import logging

from app.db.session import SessionLocal
from app.services.report_score_job_service import (
    claim_score_job,
    execute_claimed_score_job,
    fail_score_job_claim,
    reconcile_exhausted_score_jobs,
)
from app.workers.celery_app import celery_app


logger = logging.getLogger(__name__)


@celery_app.task(name="process_health_report_score_jobs")
def process_health_report_score_jobs(max_jobs: int = 20) -> dict[str, int]:
    batch_size = max(1, min(max_jobs * 5, 500))
    with SessionLocal() as reconciliation_db:
        exhausted_reconciled = reconcile_exhausted_score_jobs(
            reconciliation_db,
            batch_size=batch_size,
        )
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
            # 异常文本可能含第三方或数据库细节；日志只记录非敏感任务 ID。
            logger.warning("health report score job failed job_id=%s", job_id)
            with SessionLocal() as failure_db:
                fail_score_job_claim(
                    failure_db,
                    job_id=job_id,
                    lease_token=token,
                )
            failed += 1
    return {
        "processed": processed,
        "failed": failed,
        "exhausted_reconciled": exhausted_reconciled,
    }
