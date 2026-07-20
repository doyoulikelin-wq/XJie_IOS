"""Evidence-bound report follow-up items and localized presentation."""

from __future__ import annotations

import hashlib
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.models.health_trust import HealthReportConfirmationEvent, HealthReportFieldCandidate, HealthReportWorkflow
from app.models.health_trust_expansion import HealthReportFollowUpEvidence, HealthReportFollowUpItem
from app.services.report_score_job_service import localized_text


FOLLOW_UP_RULE_VERSION = "evidence-bound-follow-up-v1"
CLINICIAN_FOLLOW_UP_NAMES = frozenset({"医师建议", "随访医嘱", "复查建议", "复诊建议"})


def is_clinician_follow_up_candidate(candidate: HealthReportFieldCandidate) -> bool:
    return candidate.canonical_name.strip() in CLINICIAN_FOLLOW_UP_NAMES


def _evidence_key(prefix: str, value: str) -> str:
    return f"{prefix}:{hashlib.sha256(value.encode('utf-8')).hexdigest()[:72]}"[:96]


def generate_follow_ups(db: Session, *, workflow: HealthReportWorkflow) -> list[HealthReportFollowUpItem]:
    """Create items only from an explicit confirmation or admitted observation."""

    created: list[HealthReportFollowUpItem] = []
    clinician_rows = db.execute(
        select(HealthReportFieldCandidate, HealthReportConfirmationEvent)
        .join(
            HealthReportConfirmationEvent,
            and_(
                HealthReportConfirmationEvent.candidate_id == HealthReportFieldCandidate.id,
                HealthReportConfirmationEvent.workflow_id == HealthReportFieldCandidate.workflow_id,
                HealthReportConfirmationEvent.user_id == HealthReportFieldCandidate.user_id,
                HealthReportConfirmationEvent.subject_user_id == HealthReportFieldCandidate.subject_user_id,
            ),
        )
        .where(
            HealthReportFieldCandidate.workflow_id == workflow.id,
            HealthReportFieldCandidate.user_id == workflow.user_id,
            HealthReportFieldCandidate.subject_user_id == workflow.subject_user_id,
            HealthReportConfirmationEvent.event_type.in_(("confirm", "correct")),
        )
    ).all()
    for candidate, event in clinician_rows:
        if not is_clinician_follow_up_candidate(candidate):
            continue
        statement = candidate.normalized_text or candidate.raw_value
        if not statement:
            continue
        item_code = f"clinician:{candidate.id}"
        item = db.execute(
            select(HealthReportFollowUpItem).where(
                HealthReportFollowUpItem.workflow_id == workflow.id,
                HealthReportFollowUpItem.user_id == workflow.user_id,
                HealthReportFollowUpItem.subject_user_id == workflow.subject_user_id,
                HealthReportFollowUpItem.rule_id == "confirmed-clinician-statement",
                HealthReportFollowUpItem.rule_version == FOLLOW_UP_RULE_VERSION,
                HealthReportFollowUpItem.item_code == item_code,
            )
        ).scalars().first()
        if not item:
            item = HealthReportFollowUpItem(
                workflow_id=workflow.id,
                user_id=workflow.user_id,
                subject_user_id=workflow.subject_user_id,
                rule_id="confirmed-clinician-statement",
                rule_version=FOLLOW_UP_RULE_VERSION,
                item_code=item_code,
                message_key="report.follow_up.clinician_statement",
                message_params={"statement": statement},
                status="active",
            )
            db.add(item)
            db.flush()
        evidence = db.execute(
            select(HealthReportFollowUpEvidence).where(
                HealthReportFollowUpEvidence.follow_up_item_id == item.id,
                HealthReportFollowUpEvidence.evidence_key
                == _evidence_key("confirmation", f"{event.id}:{candidate.id}"),
            )
        ).scalars().first()
        if not evidence:
            db.add(
                HealthReportFollowUpEvidence(
                    follow_up_item_id=item.id,
                    workflow_id=workflow.id,
                    user_id=workflow.user_id,
                    subject_user_id=workflow.subject_user_id,
                    evidence_key=_evidence_key("confirmation", f"{event.id}:{candidate.id}"),
                    source_kind="clinician_confirmation",
                    confirmation_event_id=event.id,
                    confirmation_candidate_id=candidate.id,
                )
            )
        created.append(item)

    db.flush()
    return created


def follow_up_presentation(
    db: Session, *, workflow_id: int, user_id: int, subject_user_id: int, locale: str
) -> dict:
    items = list(
        db.execute(
            select(HealthReportFollowUpItem).where(
                HealthReportFollowUpItem.workflow_id == workflow_id,
                HealthReportFollowUpItem.user_id == user_id,
                HealthReportFollowUpItem.subject_user_id == subject_user_id,
                HealthReportFollowUpItem.status == "active",
            )
            .order_by(HealthReportFollowUpItem.id)
        ).scalars().all()
    )
    details = []
    for item in items:
        evidence = list(
            db.execute(
                select(HealthReportFollowUpEvidence).where(
                    HealthReportFollowUpEvidence.follow_up_item_id == item.id,
                    HealthReportFollowUpEvidence.workflow_id == workflow_id,
                    HealthReportFollowUpEvidence.user_id == user_id,
                    HealthReportFollowUpEvidence.subject_user_id == subject_user_id,
                )
            ).scalars().all()
        )
        if not evidence:
            continue
        message = _localized_follow_up(item.message_key, item.message_params or {}, locale=locale)
        details.append(
            {
                "item_id": item.id,
                "item_code": item.item_code,
                "message": message,
                "due_at": item.due_at,
                "evidence": [
                    {
                        "source_kind": row.source_kind,
                        "observation_id": row.observation_id,
                        "confirmation_event_id": row.confirmation_event_id,
                        "confirmation_candidate_id": row.confirmation_candidate_id,
                    }
                    for row in evidence
                ],
            }
        )
    return {
        "available": bool(details),
        "items": [row["message"]["text"] for row in details],
        "details": details,
        "unavailable_reason": (
            None
            if details
            else "当前没有经过确认且可追溯的复查或持续观察项；系统不会根据异常值自行推断。"
        ),
    }


def _localized_follow_up(key: str, params: dict, *, locale: str) -> dict:
    templates = {
        "report.follow_up.clinician_statement": "报告中的已确认医师建议：{statement}",
        "report.follow_up.observe_abnormal": "{name}为已确认异常项，请结合原报告与医生确认是否需要复查或持续观察。",
    }
    template = templates.get(key)
    if not template:
        return localized_text(key, params, locale=locale)
    try:
        text = template.format(**params)
    except (KeyError, ValueError):
        text = "该随访信息暂不可用。"
    return {
        "key": key,
        "params": params,
        "text": text,
        "locale": "zh-Hans",
        "catalog_version": "zh-Hans-report-follow-up-v1",
    }
