"""Periodic wake-up for DB-authoritative ordered-report OCR work."""

import logging

from app.core.config import settings
from app.db.session import SessionLocal
from app.services.report_asset_service import (
    cleanup_expired_asset_sets,
    cleanup_pending_attached_report_objects,
    queue_attached_report_object_retirement,
    queue_terminal_report_object_retirements,
    retire_attached_report_objects,
)
from app.services.report_ocr_service import (
    OpenAIReportPageExtractor,
    REPORT_OCR_INFRASTRUCTURE_ERRORS,
    ReportOCRProviderInitializationError,
    claim_report_ocr_workflow,
    defer_report_ocr_infrastructure_claim,
    execute_report_ocr_workflow,
    fail_report_ocr_claim,
    reconcile_stale_report_ocr_workflows,
    report_ocr_infrastructure_reason,
)
from app.services.object_storage import configured_report_object_store
from app.workers.celery_app import celery_app


logger = logging.getLogger(__name__)


def _configured_report_page_extractor() -> OpenAIReportPageExtractor:
    """Normalize every provider-construction failure into a durable retry class."""

    try:
        return OpenAIReportPageExtractor()
    except ReportOCRProviderInitializationError:
        raise
    except Exception as exc:
        raise ReportOCRProviderInitializationError(
            "Report OCR provider initialization failed."
        ) from exc


@celery_app.task(name="cleanup_expired_health_report_upload_sessions")
def cleanup_expired_health_report_upload_sessions() -> dict[str, int]:
    """Retire only workflow-unbound report staging bytes past the configured TTL."""

    object_store = configured_report_object_store(settings)
    with SessionLocal() as db:
        return cleanup_expired_asset_sets(
            db,
            object_store=object_store,
            ttl_hours=settings.REPORT_UPLOAD_SESSION_TTL_HOURS,
            batch_size=settings.REPORT_UPLOAD_CLEANUP_BATCH_SIZE,
        )


@celery_app.task(name="cleanup_terminal_health_report_originals")
def cleanup_terminal_health_report_originals() -> dict[str, int]:
    """重放 OCR 终态的服务端临时原件删除队列。"""

    with SessionLocal() as queue_db:
        queued = queue_terminal_report_object_retirements(
            queue_db,
            batch_size=settings.REPORT_UPLOAD_CLEANUP_BATCH_SIZE,
        )
    object_store = configured_report_object_store(settings)
    with SessionLocal() as db:
        result = cleanup_pending_attached_report_objects(
            db,
            object_store=object_store,
            batch_size=settings.REPORT_UPLOAD_CLEANUP_BATCH_SIZE,
        )
    return {"queued": queued, **result}


@celery_app.task(name="process_health_report_ocr_workflows")
def process_health_report_ocr_workflows(max_workflows: int = 10) -> dict[str, int]:
    batch_size = max(1, min(max_workflows * 5, 250))
    with SessionLocal() as terminal_db:
        terminal_retirements_queued = queue_terminal_report_object_retirements(
            terminal_db,
            batch_size=batch_size,
        )
    with SessionLocal() as reconciliation_db:
        stale_reconciled = reconcile_stale_report_ocr_workflows(
            reconciliation_db,
            batch_size=batch_size,
        )
    extractor = None
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
        object_store = None
        try:
            # 初始化也必须发生在持久 claim 内；失败走独立基础设施预算，
            # defer 会补回内容 attempt，因此不会消耗报告内容重试。
            if extractor is None:
                extractor = _configured_report_page_extractor()
            # 先认领再构造存储：即使配置坏了，也必须把本次基础设施失败
            # 写回数据库，不能让用户永久停在“识别中”。
            object_store = configured_report_object_store(settings)
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
            _retire_terminal_report_source(
                workflow_id=workflow_id,
                object_store=object_store,
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
            _retire_terminal_report_source(
                workflow_id=workflow_id,
                object_store=object_store,
            )
            failed += 1
    # claim 可能在发现重试预算耗尽时直接落 failed 并返回 None；再次补扫，
    # 保证这种无执行 token 的终态也进入 purge_pending。
    with SessionLocal() as terminal_db:
        terminal_retirements_queued += queue_terminal_report_object_retirements(
            terminal_db,
            batch_size=batch_size,
        )
    return {
        "processed": processed,
        "failed": failed,
        "infrastructure_deferred": infrastructure_deferred,
        "stale_reconciled": stale_reconciled,
        "terminal_retirements_queued": terminal_retirements_queued,
    }


def _retire_terminal_report_source(*, workflow_id: int, object_store) -> None:
    """终态删除意图必须落库；存储恢复后可安全重放精确删除。"""

    try:
        with SessionLocal() as cleanup_db:
            if object_store is None:
                queue_attached_report_object_retirement(
                    cleanup_db,
                    workflow_id=workflow_id,
                )
            else:
                retire_attached_report_objects(
                    cleanup_db,
                    workflow_id=workflow_id,
                    object_store=object_store,
                )
    except Exception:
        logger.warning(
            "health report terminal source retirement deferred workflow_id=%s",
            workflow_id,
        )
