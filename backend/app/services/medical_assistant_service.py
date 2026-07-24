"""就医助手病人概况的读取、生成与新鲜度判断。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.health_document import (
    HealthDocument,
    MedicalAssistantOverview,
)
from app.models.health_trust import (
    ConfirmedHealthObservation,
    HealthReportWorkflow,
)
from app.models.user import User


ADMITTED_REPORT_STATUSES = ("completed", "completed_score_pending")
ONE_YEAR = timedelta(days=365)


def _utc(value: datetime | None) -> datetime | None:
    """把数据库返回的有/无时区时间统一为 UTC，避免 SQLite 与 PostgreSQL 比较差异。"""

    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _document_status(workflow_status: str | None, extraction_status: str) -> str:
    """将底层处理状态收敛成首页可理解的三类状态。"""

    if workflow_status in ADMITTED_REPORT_STATUSES:
        return "admitted"
    if workflow_status == "failed" or extraction_status == "failed":
        return "failed"
    return "processing"


def _recent_documents(db: Session, user_id: int, limit: int = 5) -> list[dict[str, Any]]:
    """读取最近上传资料；入参 user_id 是当前认证账号，limit 控制首页最大展示条数。"""

    rows = db.execute(
        select(HealthDocument, HealthReportWorkflow.status)
        .outerjoin(
            HealthReportWorkflow,
            (HealthReportWorkflow.legacy_document_id == HealthDocument.id)
            & (HealthReportWorkflow.user_id == user_id)
            & (HealthReportWorkflow.subject_user_id == user_id),
        )
        .where(HealthDocument.user_id == user_id)
        .order_by(HealthDocument.created_at.desc(), HealthDocument.id.desc())
        .limit(limit)
    ).all()
    return [
        {
            "document_id": str(document.id),
            "title": document.name or "未命名就医资料",
            "hospital": document.hospital,
            "document_date": document.doc_date,
            "uploaded_at": document.created_at,
            "status": _document_status(workflow_status, document.extraction_status),
        }
        for document, workflow_status in rows
    ]


def _latest_upload_at(db: Session, user_id: int) -> datetime | None:
    """返回当前账号最后一次上传任意病历/报告的服务端时间。"""

    return db.scalar(
        select(func.max(HealthDocument.created_at)).where(HealthDocument.user_id == user_id)
    )


def _admitted_documents(
    db: Session,
    user_id: int,
    *,
    since: datetime,
) -> list[tuple[HealthDocument, HealthReportWorkflow]]:
    """读取近一年已由用户确认并完成入库的本人资料。"""

    return db.execute(
        select(HealthDocument, HealthReportWorkflow)
        .join(
            HealthReportWorkflow,
            HealthReportWorkflow.legacy_document_id == HealthDocument.id,
        )
        .where(
            HealthDocument.user_id == user_id,
            HealthDocument.created_at >= since,
            HealthReportWorkflow.user_id == user_id,
            HealthReportWorkflow.subject_user_id == user_id,
            HealthReportWorkflow.status.in_(ADMITTED_REPORT_STATUSES),
        )
        .order_by(HealthDocument.created_at.desc(), HealthDocument.id.desc())
    ).all()


def _display_value(observation: ConfirmedHealthObservation) -> str:
    """把已确认观察值转换成医生概况中的紧凑文本。"""

    if observation.value_numeric is not None:
        value = format(Decimal(observation.value_numeric).normalize(), "f")
    else:
        value = (observation.value_text or "").strip()
    return f"{value} {observation.unit}".strip()


def _build_summary(
    db: Session,
    documents: list[tuple[HealthDocument, HealthReportWorkflow]],
) -> str:
    """依据已确认资料生成给医生看的概况，不使用未确认 OCR 或旧 AI 摘要。"""

    workflow_ids = [workflow.id for _, workflow in documents]
    observations = db.execute(
        select(ConfirmedHealthObservation)
        .where(
            ConfirmedHealthObservation.workflow_id.in_(workflow_ids),
            ConfirmedHealthObservation.status == "active",
        )
        .order_by(
            ConfirmedHealthObservation.effective_at.desc(),
            ConfirmedHealthObservation.id.desc(),
        )
    ).scalars().all()

    record_count = sum(workflow.report_type == "medical_record" for _, workflow in documents)
    exam_count = len(documents) - record_count
    latest_document, _ = documents[0]
    latest_date = _utc(latest_document.doc_date) or _utc(latest_document.created_at)
    latest_label = latest_date.date().isoformat() if latest_date else "日期未记录"
    latest_place = f"（{latest_document.hospital}）" if latest_document.hospital else ""

    paragraphs = [
        (
            f"近一年共整理 {len(documents)} 份已确认并入库的资料，"
            f"其中病历或就诊资料 {record_count} 份、检查报告 {exam_count} 份。"
        ),
        f"最近一份资料为“{latest_document.name or '未命名就医资料'}”{latest_place}，日期 {latest_label}。",
    ]

    medical_points: list[str] = []
    abnormal_points: list[str] = []
    seen: set[tuple[str, str]] = set()
    workflow_types = {workflow.id: workflow.report_type for _, workflow in documents}
    for observation in observations:
        value = _display_value(observation)
        key = (observation.canonical_name, value)
        if not value or key in seen:
            continue
        seen.add(key)
        point = f"{observation.canonical_name}：{value}"
        if observation.abnormal_state == "abnormal" and len(abnormal_points) < 6:
            abnormal_points.append(point)
        elif workflow_types.get(observation.workflow_id) == "medical_record" and len(medical_points) < 6:
            medical_points.append(point)

    if medical_points:
        paragraphs.append("病历与就诊资料要点：" + "；".join(medical_points) + "。")
    if abnormal_points:
        paragraphs.append("已确认需关注的检查信息：" + "；".join(abnormal_points) + "。")
    elif observations:
        paragraphs.append("本次纳入的已确认字段中，没有标记为异常的检查项。")

    paragraphs.append(
        "以上内容仅整理用户已确认并入库的上传资料，供就诊沟通参考；"
        "诊断、用药与处置请由医生结合原件和当次情况判断。"
    )
    return "\n\n".join(paragraphs)


def medical_assistant_overview(
    db: Session,
    *,
    user_id: int,
    generation_result: str = "loaded",
    now: datetime | None = None,
) -> dict[str, Any]:
    """读取概况快照；now 仅用于稳定计算近一年窗口。"""

    current = _utc(now) or datetime.now(timezone.utc)
    since = current - ONE_YEAR
    overview = db.execute(
        select(MedicalAssistantOverview).where(MedicalAssistantOverview.user_id == user_id)
    ).scalars().first()
    latest_upload = _latest_upload_at(db, user_id)
    admitted = _admitted_documents(db, user_id, since=since)
    return {
        "subject_user_id": user_id,
        "summary": overview.summary_text if overview else "",
        "generated_at": overview.generated_at if overview else None,
        "latest_report_uploaded_at": latest_upload,
        "report_count_last_year": len(admitted),
        "recent_documents": _recent_documents(db, user_id),
        "generation_result": generation_result,
    }


def generate_medical_assistant_overview(
    db: Session,
    *,
    user_id: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    """原子判断新鲜度并生成概况；user_id 为当前认证账号。"""

    current = _utc(now) or datetime.now(timezone.utc)
    since = current - ONE_YEAR
    # 锁定账号行，使同一账号的并发点击按顺序比较和写入。
    db.execute(select(User.id).where(User.id == user_id).with_for_update()).scalar_one()
    overview = db.execute(
        select(MedicalAssistantOverview)
        .where(MedicalAssistantOverview.user_id == user_id)
        .with_for_update()
    ).scalars().first()
    latest_upload = _utc(_latest_upload_at(db, user_id))
    generated_at = _utc(overview.generated_at) if overview else None

    if latest_upload is None:
        return medical_assistant_overview(
            db, user_id=user_id, generation_result="no_reports", now=current
        )
    if latest_upload < since:
        return medical_assistant_overview(
            db, user_id=user_id, generation_result="no_reports", now=current
        )
    if overview and overview.summary_text.strip() and generated_at and latest_upload <= generated_at:
        return medical_assistant_overview(
            db, user_id=user_id, generation_result="no_information_update", now=current
        )

    admitted = _admitted_documents(db, user_id, since=since)
    latest_admitted_upload = max((_utc(document.created_at) for document, _ in admitted), default=None)
    if not admitted or latest_admitted_upload is None or latest_admitted_upload < latest_upload:
        return medical_assistant_overview(
            db, user_id=user_id, generation_result="report_processing", now=current
        )

    summary = _build_summary(db, admitted)
    if overview is None:
        overview = MedicalAssistantOverview(
            user_id=user_id,
            summary_text=summary,
            generated_at=current,
            source_latest_upload_at=latest_upload,
            source_workflow_ids=[workflow.id for _, workflow in admitted],
            source_document_count=len(admitted),
        )
        db.add(overview)
    else:
        overview.summary_text = summary
        overview.generated_at = current
        overview.source_latest_upload_at = latest_upload
        overview.source_workflow_ids = [workflow.id for _, workflow in admitted]
        overview.source_document_count = len(admitted)
    db.commit()
    return medical_assistant_overview(
        db, user_id=user_id, generation_result="generated", now=current
    )
