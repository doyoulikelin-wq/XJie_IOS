"""Periodic wake-up for DB-authoritative ordered-report OCR work."""

import logging

from app.core.config import settings
from app.db.session import SessionLocal
from app.services.report_asset_service import cleanup_expired_asset_sets
from app.services.report_ocr_service import (
    OpenAIReportPageExtractor,
    REPORT_OCR_INFRASTRUCTURE_ERRORS,
    claim_report_ocr_workflow,
    defer_report_ocr_infrastructure_claim,
    execute_report_ocr_workflow,
    fail_report_ocr_claim,
    report_ocr_infrastructure_reason,
)
from app.services.object_storage import configured_private_object_store
from app.workers.celery_app import celery_app


logger = logging.getLogger(__name__)


@celery_app.task(name="cleanup_expired_health_report_upload_sessions")
def cleanup_expired_health_report_upload_sessions() -> dict[str, int]:
    """Retire only workflow-unbound report staging bytes past the configured TTL."""

    object_store = configured_private_object_store(settings)
    with SessionLocal() as db:
        return cleanup_expired_asset_sets(
            db,
            object_store=object_store,
            ttl_hours=settings.REPORT_UPLOAD_SESSION_TTL_HOURS,
            batch_size=settings.REPORT_UPLOAD_CLEANUP_BATCH_SIZE,
        )


@celery_app.task(name="process_health_report_ocr_workflows")
def process_health_report_ocr_workflows(max_workflows: int = 10) -> dict[str, int]:
    # 在认领数据库任务前先验证跨容器存储，配置错误不得消耗 OCR 重试次数。
    object_store = configured_private_object_store(settings)
    processed = 0
    failed = 0
    infrastructure_deferred = 0
    attempted_workflow_ids: set[int] = set()
    for _ in range(max(1, min(max_workflows, 50))):
        with SessionLocal() as claim_db:
            claim = claim_report_ocr_workflow(
                claim_db,
                exclude_workflow_ids=attempted_workflow_ids,
            )
        if not claim:
            break
        workflow_id, token = claim
        attempted_workflow_ids.add(workflow_id)
        try:
            extractor = OpenAIReportPageExtractor()
            with SessionLocal() as execution_db:
                execute_report_ocr_workflow(
                    execution_db,
                    workflow_id=workflow_id,
                    claim_token=token,
                    extractor=extractor,
                    object_store=object_store,
                )
            processed += 1
        except REPORT_OCR_INFRASTRUCTURE_ERRORS as exc:
            logger.warning(
                "health report OCR infrastructure delayed for workflow_id=%s reason=%s",
                workflow_id,
                report_ocr_infrastructure_reason(exc),
            )
            with SessionLocal() as failure_db:
                defer_report_ocr_infrastructure_claim(
                    failure_db,
                    workflow_id=workflow_id,
                    claim_token=token,
                    reason_code=report_ocr_infrastructure_reason(exc),
                )
            infrastructure_deferred += 1
        except Exception:
            logger.exception("health report OCR failed for workflow_id=%s", workflow_id)
            with SessionLocal() as failure_db:
                fail_report_ocr_claim(
                    failure_db,
                    workflow_id=workflow_id,
                    claim_token=token,
                )
            failed += 1
    return {
        "processed": processed,
        "failed": failed,
        "infrastructure_deferred": infrastructure_deferred,
    }
