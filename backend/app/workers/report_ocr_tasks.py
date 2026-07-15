"""Periodic wake-up for DB-authoritative ordered-report OCR work."""

import logging

from app.core.config import settings
from app.db.session import SessionLocal
from app.services.report_ocr_service import (
    OpenAIReportPageExtractor,
    claim_report_ocr_workflow,
    execute_report_ocr_workflow,
    fail_report_ocr_claim,
)
from app.workers.celery_app import celery_app


logger = logging.getLogger(__name__)


@celery_app.task(name="process_health_report_ocr_workflows")
def process_health_report_ocr_workflows(max_workflows: int = 10) -> dict[str, int]:
    processed = 0
    failed = 0
    for _ in range(max(1, min(max_workflows, 50))):
        with SessionLocal() as claim_db:
            claim = claim_report_ocr_workflow(claim_db)
        if not claim:
            break
        workflow_id, token = claim
        try:
            extractor = OpenAIReportPageExtractor()
            with SessionLocal() as execution_db:
                execute_report_ocr_workflow(
                    execution_db,
                    workflow_id=workflow_id,
                    claim_token=token,
                    extractor=extractor,
                    storage_root=settings.LOCAL_STORAGE_DIR,
                )
            processed += 1
        except Exception:
            logger.exception("health report OCR failed for workflow_id=%s", workflow_id)
            with SessionLocal() as failure_db:
                fail_report_ocr_claim(
                    failure_db,
                    workflow_id=workflow_id,
                    claim_token=token,
                )
            failed += 1
    return {"processed": processed, "failed": failed}
