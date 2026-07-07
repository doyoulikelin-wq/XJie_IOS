import logging
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.cgm_integration import CGMDeviceBinding
from app.models.conversation import ChatMessage, Conversation
from app.models.health_document import HealthDocument, HealthSummary, PatientHistoryProfile
from app.models.meal import Meal
from app.models.medication import Medication
from app.models.omics import OmicsUpload
from app.models.symptom import Symptom
from app.models.feature import FeatureSnapshot
from app.models.user_indicator_value import UserIndicatorValue
from app.models.user_profile import UserProfile
from app.services.glucose_service import get_glucose_summary
from app.services.patient_history_service import compute_missing_sections, normalize_sections

logger = logging.getLogger(__name__)

_APPLE_HEALTH_SOURCES = {"apple_health", "healthkit", "apple"}
_CGM_SOURCES = {"cgm", "vendor_cgm", "dexcom", "libre"}
_HEALTH_QUERY_RE = re.compile(
    r"血糖|血压|血脂|尿酸|痛风|心率|HRV|睡眠|恢复|压力|炎症|X年龄|体检|报告|"
    r"检查|化验|指标|异常|偏高|偏低|药|用药|备孕|怀孕|孕|NT|胎儿|健康|病史|症状",
    re.IGNORECASE,
)
_GREETING_RE = re.compile(r"^(你好|您好|在吗|在不在|hello|hi|嗨|哈喽)[。!！?\s]*$", re.IGNORECASE)
_RELATIVE_PATTERNS = [
    ("wife", "妻子", re.compile(r"老婆|妻子|太太|媳妇|爱人|她的|帮她|给她|nt\s*是帮我老婆|NT\s*是帮我老婆", re.IGNORECASE)),
    ("husband", "丈夫", re.compile(r"老公|丈夫|先生|他老公|帮他问", re.IGNORECASE)),
    ("father", "父亲", re.compile(r"我爸|爸爸|父亲|老爸", re.IGNORECASE)),
    ("mother", "母亲", re.compile(r"我妈|妈妈|母亲|老妈", re.IGNORECASE)),
    ("child", "孩子", re.compile(r"孩子|儿子|女儿|小孩", re.IGNORECASE)),
]
_COVERED_FACT_PATTERNS = {
    "uric_acid": re.compile(r"尿酸|419\.7"),
    "hba1c": re.compile(r"HbA1c|糖化|5\.5"),
    "tir": re.compile(r"\bTIR\b|93\.8", re.IGNORECASE),
    "nt": re.compile(r"\bNT\b|颈项透明层", re.IGNORECASE),
    "apple_health": re.compile(r"Apple\s*健康|苹果健康|HealthKit", re.IGNORECASE),
    "hrv": re.compile(r"\bHRV\b|心率变异", re.IGNORECASE),
}
_COMMON_REPEATED_ADVICE = [
    ("drink_2000ml_water", re.compile(r"2000\s*ml|2000毫升|喝够?水")),
    ("avoid_offal_seafood", re.compile(r"内脏|海鲜")),
    ("uric_acid_mild_high", re.compile(r"尿酸.*(轻度|稍微|偏高)|419\.7")),
    ("glucose_good", re.compile(r"TIR\s*93\.8|血糖控制.*(好|理想)", re.IGNORECASE)),
]


def build_user_context(
    db: Session,
    user_id: str | int,
    *,
    conversation_id: int | None = None,
    user_query: str = "",
    history: list[dict] | None = None,
) -> dict:
    now = datetime.now(timezone.utc)

    summary_24h = get_glucose_summary(db, user_id, "24h")
    summary_7d = get_glucose_summary(db, user_id, "7d")

    day_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    meals = db.execute(
        select(Meal)
        .where(Meal.user_id == user_id, Meal.meal_ts >= day_start, Meal.meal_ts < now)
        .order_by(Meal.meal_ts.asc())
    ).scalars().all()

    symptoms = db.execute(
        select(Symptom)
        .where(Symptom.user_id == user_id, Symptom.ts >= now - timedelta(days=7), Symptom.ts < now)
        .order_by(Symptom.ts.desc())
        .limit(20)
    ).scalars().all()

    kcal_today = sum(m.kcal for m in meals) if meals else 0

    profile_info = _get_profile_info(db, user_id)

    # Build health report text for Liver subjects
    health_report_text = _get_health_report_text(profile_info)

    # Also fetch AI health summary from health_summaries (for uploaded 体检报告)
    health_summary_text = _get_health_summary_text(db, user_id)
    patient_history = _get_patient_history_context(db, user_id)

    return {
        "profile": {},
        "glucose_summary": {
            "last_24h": summary_24h,
            "last_7d": summary_7d,
        },
        "meals_today": [
            {
                "ts": meal.meal_ts.isoformat(),
                "kcal": meal.kcal,
                "tags": meal.tags,
                "source": meal.meal_ts_source.value,
                "photo_id": str(meal.photo_id) if meal.photo_id else None,
            }
            for meal in meals
        ],
        "symptoms_last_7d": [
            {
                "ts": s.ts.isoformat(),
                "severity": s.severity,
                "text": s.text,
            }
            for s in symptoms
        ],
        "data_quality": {
            "glucose_gaps_hours": summary_24h["gaps_hours"],
            "kcal_today": kcal_today,
        },
        "agent_features": _get_agent_features(db, user_id),
        "user_profile_info": profile_info,
        "health_report_text": health_report_text,
        "health_summary_text": health_summary_text,
        "patient_history": patient_history,
        "omics_analyses": _get_omics_analyses(db, user_id),
        "current_medications": _get_current_medications(db, user_id),
        "recent_conversation_summaries": _get_recent_conversation_summaries(db, user_id),
        "message_structure": build_message_structure(
            db,
            user_id,
            user_query=user_query,
            conversation_id=conversation_id,
            history=history,
        ),
    }


def build_message_structure(
    db: Session,
    user_id: str | int,
    *,
    user_query: str = "",
    conversation_id: int | None = None,
    history: list[dict] | None = None,
) -> dict:
    """Build a deterministic chat envelope before the LLM sees context.

    This is the guardrail layer for subject ownership, source memory,
    freshness, response depth, and repetition control. It intentionally
    derives from persisted data instead of asking the LLM to guess.
    """
    query = user_query.strip()
    data_source_memory = _get_data_source_memory(db, user_id)
    report_status = _get_report_status_memory(db, user_id)
    active_subject = _resolve_active_subject(query, history or [])
    intent = _classify_intent(query, active_subject)
    session_memory = _build_session_memory(db, user_id, conversation_id, history or [])
    health_fact_index = _get_health_fact_index(db, user_id)
    response_plan = _build_response_plan(
        query=query,
        intent=intent,
        active_subject=active_subject,
        data_source_memory=data_source_memory,
        report_status=report_status,
        session_memory=session_memory,
        health_fact_index=health_fact_index,
    )
    return {
        "version": "2026-07-07",
        "user_message": {
            "raw": query,
            "normalized": _normalize_text(query),
            "length": len(query),
        },
        "intent": intent,
        "active_subject": active_subject,
        "data_source_memory": data_source_memory,
        "report_status": report_status,
        "health_fact_index": health_fact_index,
        "session_memory": session_memory,
        "response_plan": response_plan,
    }


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip()).lower()


def _safe_int(value: str | int) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_aware_utc(ts: datetime | None) -> datetime | None:
    if not ts:
        return None
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def _freshness_label(ts: datetime | None, *, now: datetime | None = None) -> str:
    measured_at = _as_aware_utc(ts)
    if not measured_at:
        return "unknown"
    now = now or datetime.now(timezone.utc)
    age_days = max(0.0, (now - measured_at).total_seconds() / 86400)
    if age_days <= 2:
        return "fresh"
    if age_days <= 14:
        return "recent"
    if age_days <= 90:
        return "stale"
    return "outdated"


def _format_ts(ts: datetime | None) -> str:
    aware = _as_aware_utc(ts)
    return aware.isoformat() if aware else ""


def _get_indicator_rows(db: Session, user_id: str | int, *, limit: int = 200) -> list[UserIndicatorValue]:
    uid = _safe_int(user_id)
    if uid is None:
        return []
    try:
        return db.execute(
            select(UserIndicatorValue)
            .where(UserIndicatorValue.user_id == uid)
            .order_by(UserIndicatorValue.measured_at.desc(), UserIndicatorValue.created_at.desc())
            .limit(limit)
        ).scalars().all()
    except Exception as e:  # noqa: BLE001
        logger.warning("indicator rows fetch failed: %s", e)
        return []


def _get_data_source_memory(db: Session, user_id: str | int) -> dict:
    rows = _get_indicator_rows(db, user_id, limit=300)
    now = datetime.now(timezone.utc)
    source_map: dict[str, dict] = {}
    metric_sources: dict[str, dict] = {}
    rows_by_metric: dict[str, list[UserIndicatorValue]] = {}

    for row in rows:
        rows_by_metric.setdefault(row.indicator_name, []).append(row)
        source_key = (row.source or "manual").strip() or "manual"
        source = source_map.setdefault(source_key, {
            "source_key": source_key,
            "status": "connected",
            "metric_count": 0,
            "available_metrics": set(),
            "first_sample_at": None,
            "last_sample_at": None,
            "last_sync_at": None,
        })
        source["metric_count"] += 1
        source["available_metrics"].add(row.indicator_name)
        measured_at = _as_aware_utc(row.measured_at)
        created_at = _as_aware_utc(row.created_at)
        if measured_at:
            if not source["first_sample_at"] or measured_at < source["first_sample_at"]:
                source["first_sample_at"] = measured_at
            if not source["last_sample_at"] or measured_at > source["last_sample_at"]:
                source["last_sample_at"] = measured_at
        if created_at and (not source["last_sync_at"] or created_at > source["last_sync_at"]):
            source["last_sync_at"] = created_at

        metric = metric_sources.setdefault(row.indicator_name, {
            "metric": row.indicator_name,
            "source": source_key,
            "last_value": row.value,
            "unit": row.unit,
            "measured_at": row.measured_at,
            "freshness": _freshness_label(row.measured_at, now=now),
        })
        metric_ts = _as_aware_utc(metric.get("measured_at"))
        row_ts = _as_aware_utc(row.measured_at)
        if row_ts and (metric_ts is None or row_ts > metric_ts):
            metric.update({
                "source": source_key,
                "last_value": row.value,
                "unit": row.unit,
                "measured_at": row.measured_at,
                "freshness": _freshness_label(row.measured_at, now=now),
            })

    sources = []
    for source in source_map.values():
        last_sample_at = source["last_sample_at"]
        sources.append({
            "source_key": source["source_key"],
            "status": source["status"],
            "metric_count": source["metric_count"],
            "available_metrics": sorted(source["available_metrics"]),
            "first_sample_at": _format_ts(source["first_sample_at"]),
            "last_sample_at": _format_ts(last_sample_at),
            "last_sync_at": _format_ts(source["last_sync_at"]),
            "freshness": _freshness_label(last_sample_at, now=now),
        })

    uid = _safe_int(user_id)
    cgm_bindings = []
    if uid is not None:
        try:
            cgm_bindings = db.execute(
                select(CGMDeviceBinding)
                .where(CGMDeviceBinding.user_id == uid, CGMDeviceBinding.is_active == True)  # noqa: E712
                .order_by(CGMDeviceBinding.updated_at.desc())
                .limit(5)
            ).scalars().all()
        except Exception as e:  # noqa: BLE001
            logger.warning("cgm bindings fetch failed: %s", e)

    source_keys = {s["source_key"] for s in sources}
    apple_health_connected = bool(source_keys & _APPLE_HEALTH_SOURCES)
    cgm_connected = bool(source_keys & _CGM_SOURCES) or bool(cgm_bindings)

    if cgm_bindings and not any(s["source_key"] == "cgm" for s in sources):
        sources.append({
            "source_key": "cgm",
            "status": "connected",
            "metric_count": 0,
            "available_metrics": ["血糖"],
            "first_sample_at": "",
            "last_sample_at": "",
            "last_sync_at": _format_ts(cgm_bindings[0].updated_at),
            "freshness": "unknown",
        })

    forbidden_questions = []
    if apple_health_connected:
        forbidden_questions.extend([
            "你平时戴 Apple Watch 吗",
            "你有 Apple Watch 吗",
            "你有没有同步 Apple 健康",
            "把最近一周 HRV 趋势截图发给我",
        ])
    if cgm_connected:
        forbidden_questions.extend([
            "你有没有连续血糖监测设备",
            "你是否使用 CGM",
        ])
    metric_conflicts = _get_metric_conflicts(rows_by_metric, now=now)

    return {
        "sources": sorted(sources, key=lambda item: item.get("last_sample_at") or "", reverse=True),
        "metrics": [
            {
                "metric": item["metric"],
                "source": item["source"],
                "last_value": item["last_value"],
                "unit": item["unit"],
                "measured_at": _format_ts(item["measured_at"]),
                "freshness": item["freshness"],
            }
            for item in sorted(metric_sources.values(), key=lambda x: _format_ts(x.get("measured_at")), reverse=True)[:80]
        ],
        "connected": {
            "apple_health": apple_health_connected,
            "cgm": cgm_connected,
            "manual": "manual" in source_keys,
            "other_device": bool((source_keys - _APPLE_HEALTH_SOURCES - _CGM_SOURCES - {"manual"})),
        },
        "forbidden_questions": forbidden_questions,
        "metric_conflicts": metric_conflicts,
        "source_interpretation_rules": [
            "Apple 健康是健康数据聚合来源，不能自动等同于 Apple Watch，除非 device_metadata 明确显示。",
            "硬件/Apple 健康数据不能覆盖用户手动化验值；同指标冲突时必须说明来源和时间。",
            "数据过期时说上次同步时间和需要刷新，不要反问用户是否拥有设备。",
        ],
    }


def _get_metric_conflicts(rows_by_metric: dict[str, list[UserIndicatorValue]], *, now: datetime) -> list[dict]:
    conflicts = []
    for metric, rows in rows_by_metric.items():
        latest_by_source: dict[str, UserIndicatorValue] = {}
        for row in sorted(rows, key=lambda item: (_as_aware_utc(item.measured_at) or datetime.min.replace(tzinfo=timezone.utc)), reverse=True):
            source_key = (row.source or "manual").strip() or "manual"
            latest_by_source.setdefault(source_key, row)
        if len(latest_by_source) < 2:
            continue
        samples = list(latest_by_source.values())
        newest_ts = max((_as_aware_utc(row.measured_at) for row in samples if _as_aware_utc(row.measured_at)), default=None)
        if newest_ts is None:
            continue
        close_samples = [
            row for row in samples
            if _as_aware_utc(row.measured_at)
            and abs((newest_ts - _as_aware_utc(row.measured_at)).total_seconds()) <= 48 * 3600
        ]
        if len(close_samples) < 2:
            continue
        values = [float(row.value) for row in close_samples if row.value is not None]
        if len(values) < 2:
            continue
        tolerance = max(3.0, abs(values[0]) * 0.05)
        if max(values) - min(values) < tolerance:
            continue
        conflicts.append({
            "metric": metric,
            "samples": [
                {
                    "source": (row.source or "manual").strip() or "manual",
                    "value": row.value,
                    "unit": row.unit,
                    "measured_at": _format_ts(row.measured_at),
                    "freshness": _freshness_label(row.measured_at, now=now),
                }
                for row in sorted(close_samples, key=lambda item: _format_ts(item.measured_at), reverse=True)
            ],
            "rule": "同一指标在 48 小时内出现不同来源且差异明显；回答时必须按来源/时间解释，不能简单覆盖成单个结论。",
        })
    return conflicts[:12]


def _get_report_status_memory(db: Session, user_id: str | int) -> dict:
    uid = _safe_int(user_id)
    if uid is None:
        return {"documents": [], "pending_count": 0, "done_count": 0, "failed_count": 0, "latest": None}
    try:
        docs = db.execute(
            select(HealthDocument)
            .where(HealthDocument.user_id == uid)
            .order_by(HealthDocument.created_at.desc())
            .limit(20)
        ).scalars().all()
    except Exception as e:  # noqa: BLE001
        logger.warning("report status fetch failed: %s", e)
        return {"documents": [], "pending_count": 0, "done_count": 0, "failed_count": 0, "latest": None}

    documents = [
        {
            "id": doc.id,
            "name": doc.name,
            "doc_type": doc.doc_type,
            "source_type": doc.source_type,
            "extraction_status": doc.extraction_status,
            "created_at": _format_ts(doc.created_at),
            "doc_date": _format_ts(doc.doc_date),
            "has_ai_summary": bool(doc.ai_summary),
        }
        for doc in docs
    ]
    return {
        "documents": documents,
        "pending_count": sum(1 for doc in docs if doc.extraction_status == "pending"),
        "done_count": sum(1 for doc in docs if doc.extraction_status == "done"),
        "failed_count": sum(1 for doc in docs if doc.extraction_status == "failed"),
        "latest": documents[0] if documents else None,
        "rules": [
            "报告状态类问题优先回答识别/分析状态，不进入深度医学分析。",
            "pending 表示后台识别中；done 才能基于 AI 摘要和结构化指标解读。",
        ],
    }


def _get_health_fact_index(db: Session, user_id: str | int) -> dict:
    rows = _get_indicator_rows(db, user_id, limit=120)
    now = datetime.now(timezone.utc)
    facts = []
    seen: set[str] = set()
    for row in rows:
        if row.indicator_name in seen:
            continue
        seen.add(row.indicator_name)
        facts.append({
            "owner": "user_self",
            "metric": row.indicator_name,
            "value": row.value,
            "unit": row.unit,
            "source": row.source,
            "measured_at": _format_ts(row.measured_at),
            "freshness": _freshness_label(row.measured_at, now=now),
            "confidence": "high" if row.source in {"manual", "apple_health", "cgm"} else "medium",
        })
    return {
        "facts": facts[:60],
        "rules": [
            "每条健康事实必须按 owner/source/measured_at 使用。",
            "active_subject 不是 user_self 时，默认禁止使用 user_self 健康指标。",
            "freshness 为 stale/outdated 的指标必须说明数据时效，不能当作今天状态。",
        ],
    }


def _resolve_active_subject(query: str, history: list[dict]) -> dict:
    text = _normalize_text(query)
    correction = bool(re.search(r"不是我|不是我的|帮.*问|给.*问|是.*问的|问的是", query))
    for key, label, pattern in _RELATIVE_PATTERNS:
        if pattern.search(query):
            return {
                "type": "relative",
                "relation": key,
                "display": label,
                "data_binding": "not_authorized",
                "data_permission_scope": "user_statement_only",
                "source": "current_user_message",
                "confidence": 0.96 if correction else 0.88,
                "correction_applied": correction,
            }

    recent_user_text = "\n".join(m.get("content", "") for m in history[-6:] if m.get("role") == "user")
    if re.search(r"老婆|妻子|太太|媳妇|NT|nt", recent_user_text) and re.search(r"她|这个|刚才|不是", query):
        return {
            "type": "relative",
            "relation": "wife",
            "display": "妻子",
            "data_binding": "not_authorized",
            "data_permission_scope": "user_statement_only",
            "source": "recent_conversation",
            "confidence": 0.74,
            "correction_applied": correction,
        }

    if text:
        return {
            "type": "self",
            "relation": "self",
            "display": "本人",
            "data_binding": "authorized_user_account",
            "data_permission_scope": "full_self_context",
            "source": "default_self",
            "confidence": 0.72,
            "correction_applied": False,
        }
    return {
        "type": "self",
        "relation": "self",
        "display": "本人",
        "data_binding": "authorized_user_account",
        "data_permission_scope": "full_self_context",
        "source": "empty_message_default",
        "confidence": 0.55,
        "correction_applied": False,
    }


def _classify_intent(query: str, active_subject: dict) -> dict:
    normalized = _normalize_text(query)
    is_greeting = bool(_GREETING_RE.search(query.strip()))
    is_correction = bool(active_subject.get("correction_applied"))
    device_query = bool(re.search(r"Apple\s*健康|苹果健康|HealthKit|同步|手表|手环|硬件|设备|数据源", query, re.IGNORECASE))
    report_summary = bool(re.search(r"病史摘要|整理病史|总结病史|报告趋势|整理.*报告", query))
    report_status_query = bool(re.search(r"报告.*(好了吗|完成|状态|进度|分析)|识别.*(好了吗|完成|状态)|分析.*好了吗|入库.*(好了吗|完成|状态)", query))
    upload_intent = bool(re.search(r"上传|图片|pdf|拍照|相册|报告", normalized))
    health_query = bool(_HEALTH_QUERY_RE.search(query))
    deep = bool(re.search(r"详细|深入|全面|趋势|长期|病史|整理|分析|为什么|依据|证据", query))

    if is_greeting:
        kind = "greeting"
    elif is_correction:
        kind = "correction_followup"
    elif device_query:
        kind = "data_source_query"
    elif report_status_query:
        kind = "report_status_query"
    elif report_summary:
        kind = "summary_request"
    elif upload_intent:
        kind = "upload_or_report_question"
    elif health_query:
        kind = "medical_question"
    else:
        kind = "general_chat"

    if kind in {"greeting", "data_source_query", "correction_followup", "report_status_query"}:
        depth = "quick"
    elif deep:
        depth = "deep"
    else:
        depth = "standard"

    latent_purpose = "clarify_context"
    if report_summary:
        latent_purpose = "organize_health_record"
    elif report_status_query:
        latent_purpose = "check_upload_processing_status"
    elif device_query:
        latent_purpose = "verify_data_availability"
    elif health_query and re.search(r"严重|危险|风险|影响|后果|要不要去医院|怎么办|怀孕|NT|nt", query, re.IGNORECASE):
        latent_purpose = "risk_judgment"
    elif health_query:
        latent_purpose = "personalized_health_analysis"
    elif is_greeting:
        latent_purpose = "resume_conversation"

    return {
        "kind": kind,
        "depth": depth,
        "health_related": health_query,
        "requires_llm": kind not in {"greeting", "data_source_query", "report_status_query"} or (health_query and kind not in {"greeting", "report_status_query"}),
        "latent_purpose": latent_purpose,
    }


def _build_session_memory(
    db: Session,
    user_id: str | int,
    conversation_id: int | None,
    history: list[dict],
) -> dict:
    messages = list(history[-16:])
    if conversation_id and not messages:
        try:
            rows = db.execute(
                select(ChatMessage)
                .join(Conversation, Conversation.id == ChatMessage.conversation_id)
                .where(Conversation.id == conversation_id, Conversation.user_id == _safe_int(user_id))
                .order_by(ChatMessage.seq.desc())
                .limit(16)
            ).scalars().all()
            messages = [{"role": m.role, "content": m.content, "analysis": m.analysis or ""} for m in reversed(rows)]
        except Exception as e:  # noqa: BLE001
            logger.warning("session memory fetch failed: %s", e)

    covered_facts = []
    user_corrections = []
    avoid_repeating = []
    assistant_text = "\n".join(
        f"{m.get('content', '')}\n{m.get('analysis', '')}" for m in messages if m.get("role") == "assistant"
    )
    user_text = "\n".join(m.get("content", "") for m in messages if m.get("role") == "user")

    for fact_key, pattern in _COVERED_FACT_PATTERNS.items():
        if pattern.search(assistant_text) or pattern.search(user_text):
            covered_facts.append(fact_key)

    for correction in re.finditer(r"[^。！？\n]*(不是我|帮.*问|给.*问|老婆|妻子|NT|nt)[^。！？\n]*", user_text):
        sentence = correction.group(0).strip()
        if sentence:
            user_corrections.append(sentence[-120:])

    for key, pattern in _COMMON_REPEATED_ADVICE:
        if len(pattern.findall(assistant_text)) >= 1:
            avoid_repeating.append(key)

    return {
        "covered_facts": sorted(set(covered_facts)),
        "user_corrections": user_corrections[-6:],
        "avoid_repeating": sorted(set(avoid_repeating)),
        "recent_turn_count": len(messages),
        "rules": [
            "用户纠正优先级高于历史摘要。",
            "已覆盖事实不要逐字重复，除非用户明确要求复述。",
            "问候只恢复上下文，不主动输出完整病史摘要。",
        ],
    }


def _build_response_plan(
    *,
    query: str,
    intent: dict,
    active_subject: dict,
    data_source_memory: dict,
    report_status: dict,
    session_memory: dict,
    health_fact_index: dict,
) -> dict:
    is_self = active_subject.get("type") == "self"
    allowed_context = [
        "current_user_message",
        "conversation_memory",
    ]
    blocked_context = []
    if is_self:
        allowed_context.extend([
            "user_self_health_facts",
            "user_self_data_source_memory",
            "uploaded_reports",
            "medications",
            "glucose_and_daily_logs",
        ])
    else:
        allowed_context.extend([
            "user_provided_relative_case",
            "general_medical_knowledge",
        ])
        blocked_context.extend([
            "user_self_health_facts",
            "user_self_glucose_data",
            "user_self_reports",
            "user_self_medications",
            "recent_self_health_summary",
        ])

    forbidden_questions = list(data_source_memory.get("forbidden_questions") or [])
    if not is_self:
        forbidden_questions.extend([
            "基于你的尿酸",
            "你的血糖控制",
            "你正在备孕",
        ])
    if "hrv" in [m.get("metric", "").lower() for m in data_source_memory.get("metrics", [])]:
        forbidden_questions.append("把最近一周 HRV 趋势截图发给我")

    must_answer_first = intent.get("kind") in {"correction_followup", "medical_question", "data_source_query", "report_status_query"}
    needs_literature = bool(
        intent.get("health_related")
        and intent.get("depth") in {"standard", "deep"}
        and intent.get("kind") not in {"greeting", "data_source_query", "correction_followup", "report_status_query"}
    )
    progress_steps = _progress_steps(intent, active_subject, data_source_memory, needs_literature)

    return {
        "allowed_context": allowed_context,
        "blocked_context": blocked_context,
        "forbidden_questions": sorted(set(forbidden_questions)),
        "must_answer_first": must_answer_first,
        "max_followup_questions": 1,
        "needs_literature": needs_literature,
        "needs_llm": bool(intent.get("requires_llm")),
        "answer_style": "direct_then_reason" if must_answer_first else "brief_contextual",
        "progress_steps": progress_steps,
        "quality_gates": [
            "不能询问 data_source_memory 已经回答的问题。",
            "不能混用 blocked_context 里的本人健康数据。",
            "引用指标时必须包含来源或测量时间；无数据则说暂无记录/待同步/待上传。",
            "不能重复 session_memory.avoid_repeating 中的建议，除非用户明确要求。",
        ],
        "available_self_fact_count": len(health_fact_index.get("facts") or []),
        "pending_report_count": int(report_status.get("pending_count") or 0),
        "covered_facts": session_memory.get("covered_facts", []),
    }


def _progress_steps(intent: dict, active_subject: dict, data_source_memory: dict, needs_literature: bool) -> list[str]:
    steps = ["已识别当前问题主体"]
    if active_subject.get("type") == "self":
        steps.append("已读取你的健康档案和数据来源")
    else:
        steps.append(f"已切换到{active_subject.get('display', '家人')}这个独立病例")
    if data_source_memory.get("connected", {}).get("apple_health"):
        steps.append("已确认 Apple 健康同步状态")
    if data_source_memory.get("connected", {}).get("cgm"):
        steps.append("已确认连续血糖数据来源")
    if needs_literature:
        steps.append("正在检索相关医学证据")
    elif intent.get("kind") in {"greeting", "data_source_query", "correction_followup"}:
        steps.append("正在生成简短直接回复")
    else:
        steps.append("正在整理结论和下一步建议")
    return steps[:5]


def _get_current_medications(db: Session, user_id: str) -> list[dict]:
    """Fetch user's currently enabled medications for prompt context."""
    try:
        meds = db.execute(
            select(Medication)
            .where(Medication.user_id == int(user_id), Medication.enabled == True)  # noqa: E712
            .order_by(Medication.updated_at.desc())
            .limit(20)
        ).scalars().all()
    except Exception as e:  # noqa: BLE001
        logger.warning("current_medications fetch failed: %s", e)
        return []
    return [
        {
            "name": m.name,
            "dosage": m.dosage,
            "frequency": m.frequency,
            "instructions": m.instructions,
            "schedule_times": list(m.schedule_times or []),
            "course_start": m.course_start.isoformat() if m.course_start else None,
            "course_end": m.course_end.isoformat() if m.course_end else None,
        }
        for m in meds
    ]


def _get_agent_features(db: Session, user_id: str) -> dict:
    """Fetch latest feature snapshots for agent context."""
    result = {}
    for window in ("24h", "7d", "28d"):
        snap = db.execute(
            select(FeatureSnapshot)
            .where(FeatureSnapshot.user_id == user_id, FeatureSnapshot.window == window)
            .order_by(FeatureSnapshot.computed_at.desc())
            .limit(1)
        ).scalars().first()
        if snap:
            result[window] = snap.features
    return result


def _get_profile_info(db: Session, user_id: str) -> dict:
    """Fetch user profile info for agent context."""
    profile = db.execute(
        select(UserProfile).where(UserProfile.user_id == user_id)
    ).scalars().first()
    if not profile:
        return {}
    return {
        "subject_id": profile.subject_id,
        "cohort": profile.cohort,
        "liver_risk_level": profile.liver_risk_level,
    }


def _get_health_report_text(profile_info: dict) -> str:
    """Build a text summary of health exam report data for the chat prompt.

    Uses lazy import to avoid circular dependency with health_reports router.
    """
    sid = profile_info.get("subject_id", "")
    cohort = profile_info.get("cohort", "")
    if not sid or not sid.startswith("Liver"):
        return ""
    try:
        from app.routers.health_reports import _build_report_data, _build_health_data_prompt
        report = _build_report_data(sid, cohort, None)  # db not used for Liver XLS parsing
        if not report.get("phases"):
            return ""
        return _build_health_data_prompt(report)
    except Exception:
        logger.warning("Failed to build health report text for chat context", exc_info=True)
        return ""


def _get_health_summary_text(db: Session, user_id: str) -> str:
    """Fetch the AI-generated health summary from uploaded health documents."""
    row = db.execute(
        select(HealthSummary)
        .where(HealthSummary.user_id == user_id)
        .order_by(HealthSummary.updated_at.desc())
        .limit(1)
    ).scalars().first()
    if row and row.summary_text:
        return row.summary_text[:2000]  # Cap length for context window
    return ""


def _get_patient_history_context(db: Session, user_id: str) -> dict:
    row = db.execute(
        select(PatientHistoryProfile)
        .where(PatientHistoryProfile.user_id == user_id)
        .limit(1)
    ).scalars().first()
    if not row:
        return {}

    sections = normalize_sections(row.sections)
    missing_sections = [item["label"] for item in compute_missing_sections(sections)]
    return {
        "doctor_summary": row.doctor_summary[:1200],
        "missing_sections": missing_sections[:6],
        "verified_at": row.verified_at.isoformat() if row.verified_at else "",
        "updated_at": row.updated_at.isoformat() if row.updated_at else "",
    }


def _get_omics_analyses(db: Session, user_id: str) -> list[dict]:
    """Fetch user's latest omics analysis results for LLM context."""
    uploads = db.execute(
        select(OmicsUpload)
        .where(OmicsUpload.user_id == user_id, OmicsUpload.llm_summary.isnot(None))
        .order_by(OmicsUpload.created_at.desc())
        .limit(3)
    ).scalars().all()
    return [
        {
            "type": u.omics_type,
            "file_name": u.file_name,
            "risk_level": u.risk_level,
            "summary": u.llm_summary,
            "analysis": (u.llm_analysis or "")[:500],
        }
        for u in uploads
    ]


def _get_recent_conversation_summaries(db: Session, user_id: str) -> list[dict]:
    """Load assistant summaries from recent conversations for cross-session memory."""
    recent_convs = db.execute(
        select(Conversation)
        .where(Conversation.user_id == user_id)
        .order_by(Conversation.updated_at.desc())
        .limit(5)
    ).scalars().all()

    summaries = []
    for conv in recent_convs:
        msgs = db.execute(
            select(ChatMessage)
            .where(
                ChatMessage.conversation_id == conv.id,
                ChatMessage.role == "assistant",
            )
            .order_by(ChatMessage.seq.desc())
            .limit(2)
        ).scalars().all()
        if msgs:
            summaries.append({
                "conv_title": conv.title,
                "updated_at": conv.updated_at.isoformat() if conv.updated_at else "",
                "messages": [
                    {"content": m.content[:200], "analysis_snippet": (m.analysis or "")[:150]}
                    for m in reversed(msgs)
                ],
            })
    return summaries
