import logging
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.cgm_integration import CGMDeviceBinding
from app.models.conversation import ChatMessage, Conversation
from app.models.health_document import HealthDocument, HealthSummary, PatientHistoryProfile
from app.models.health_trust import ConfirmedHealthObservation, HealthReportWorkflow
from app.models.omics import OmicsUpload
from app.models.feature import FeatureSnapshot
from app.models.user_indicator_value import UserIndicatorValue
from app.models.user_profile import UserProfile
from app.services.chat_evidence import assess_trend_evidence
from app.services.chat_routing import resolve_chat_route
from app.services.health_profile_trust_service import confirmed_profile_context
from app.services.medication_trust_service import confirmed_medication_context
from app.services.trusted_health_context_service import (
    build_trusted_health_context,
    require_declared_consumer,
)
from app.services.health_nlu import analyze_health_message
from app.services.patient_history_service import normalize_sections

logger = logging.getLogger(__name__)

_APPLE_HEALTH_SOURCES = {"apple_health", "healthkit", "apple"}
_CGM_SOURCES = {"cgm", "vendor_cgm", "dexcom", "libre"}
_HEALTH_QUERY_RE = re.compile(
    r"血糖|血压|血脂|尿酸|痛风|心率|HRV|睡眠|恢复|压力|炎症|X年龄|体检|报告|"
    r"检查|化验|指标|异常|偏高|偏低|药|用药|备孕|怀孕|孕|NT|胎儿|健康|病史|症状|"
    r"头疼|头痛|头晕|咳嗽|嗓子疼|喉咙痛|腹痛|肚子疼|胃痛|腹泻|便秘|恶心|呕吐|"
    r"皮疹|过敏|水肿|发烧|发热|失眠|睡不着|焦虑|情绪低落|饮食|喝水|饮酒|咖啡|"
    r"抽烟|戒烟|运动|锻炼|热量|碳水|蛋白质",
    re.IGNORECASE,
)
_GREETING_RE = re.compile(r"^(你好|您好|在吗|在不在|hello|hi|嗨|哈喽)[。!！?\s]*$", re.IGNORECASE)
_RELATIVE_PATTERNS = [
    ("wife", "妻子", re.compile(r"老婆|妻子|太太|媳妇|nt\s*是帮我老婆|NT\s*是帮我老婆", re.IGNORECASE)),
    ("husband", "丈夫", re.compile(r"老公|丈夫|我先生|她老公", re.IGNORECASE)),
    ("partner", "伴侣", re.compile(r"爱人|伴侣|对象", re.IGNORECASE)),
    ("father", "父亲", re.compile(r"我爸|爸爸|父亲|老爸", re.IGNORECASE)),
    ("mother", "母亲", re.compile(r"我妈|妈妈|母亲|老妈", re.IGNORECASE)),
    ("child", "孩子", re.compile(r"孩子|儿子|女儿|小孩", re.IGNORECASE)),
    ("sibling", "兄弟姐妹", re.compile(r"哥哥|弟弟|姐姐|妹妹|兄弟|姐妹", re.IGNORECASE)),
    ("grandparent", "祖辈", re.compile(r"爷爷|奶奶|外公|外婆|姥姥|姥爷", re.IGNORECASE)),
    ("friend", "朋友", re.compile(r"朋友|同事|同学", re.IGNORECASE)),
    ("relative", "家人", re.compile(r"家人|家属|亲戚", re.IGNORECASE)),
]
_COVERED_FACT_PATTERNS = {
    "uric_acid": re.compile(r"尿酸|419\.7"),
    "hba1c": re.compile(r"HbA1c|糖化|5\.5"),
    "tir": re.compile(r"\bTIR\b|93\.8", re.IGNORECASE),
    "nt": re.compile(r"\bNT\b|颈项透明层", re.IGNORECASE),
    "apple_health": re.compile(r"Apple\s*健康|苹果健康|HealthKit", re.IGNORECASE),
    "hrv": re.compile(r"\bHRV\b|心率变异", re.IGNORECASE),
    "blood_pressure": re.compile(r"血压|收缩压|舒张压|mmHg", re.IGNORECASE),
    "report_status": re.compile(r"报告.*(识别|分析|后台|pending|完成|失败)|识别中"),
    "medication_safety": re.compile(r"用药|药物|相互作用|停药|加量|减量|他汀|二甲双胍|抗生素|抗凝"),
    "symptom_red_flags": re.compile(r"红旗|急症|就医|急救|胸痛|呼吸困难|昏厥|半边无力"),
    "sleep_recovery": re.compile(r"睡眠|失眠|HRV|恢复|深睡|咖啡因", re.IGNORECASE),
    "lifestyle_nutrition": re.compile(r"饮食|喝水|饮水|酒精|咖啡|碳水|蛋白质|热量|运动|步数"),
    "pregnancy_nt": re.compile(r"孕周|产科|NT|颈项透明层|CRL|无创", re.IGNORECASE),
}
_COMMON_REPEATED_ADVICE = [
    ("drink_2000ml_water", re.compile(r"2000\s*ml|2000毫升|喝够?水")),
    ("avoid_offal_seafood", re.compile(r"内脏|海鲜")),
    ("uric_acid_mild_high", re.compile(r"尿酸.*(轻度|稍微|偏高)|419\.7")),
    ("glucose_good", re.compile(r"TIR\s*93\.8|血糖控制.*(好|理想)", re.IGNORECASE)),
    ("bp_remeasure_resting", re.compile(r"血压.*(复测|静坐|袖带|上臂)|复测.*血压")),
    ("report_pending_status", re.compile(r"报告.*(后台|识别中|pending|完成后)")),
    ("medication_no_self_adjust", re.compile(r"(不要|不能|不建议).*自行.*(停药|加量|减量|调整剂量)|遵医嘱")),
    ("emergency_seek_care", re.compile(r"立即.*(就医|急救)|拨打\s*120|急诊")),
    ("sleep_schedule", re.compile(r"固定.*(入睡|起床)|睡眠窗口|睡前")),
    ("avoid_late_caffeine", re.compile(r"咖啡.*(下午|晚上|睡前)|咖啡因")),
    ("symptom_observe_red_flags", re.compile(r"红旗信号|观察.*小时|如果.*加重.*就医")),
    ("pregnancy_ob_consult", re.compile(r"产科|孕周|CRL|NT|无创")),
]
_FOLLOWUP_RE = re.compile(r"^(那|那么|这个|刚才|继续|再|还有|如果|那如果|为什么|所以|然后|上面|上一条|刚刚)")


def build_user_context(
    db: Session,
    user_id: str | int,
    *,
    trusted_health_consumer: str,
    conversation_id: int | None = None,
    user_query: str = "",
    history: list[dict] | None = None,
) -> dict:
    declared_consumer = require_declared_consumer(trusted_health_consumer)
    uid = _safe_int(user_id)
    trusted_health_context: dict = {
        "consumer": declared_consumer,
        "profile_facts": [],
    }
    trusted_context_loaded = uid is None
    if uid is not None:
        try:
            trusted_health_context = build_trusted_health_context(
                db,
                user_id=uid,
                consumer=declared_consumer,
            )
            trusted_context_loaded = True
        except Exception as exc:  # noqa: BLE001
            # A trust-store outage must remove health context, never fall back
            # to unconfirmed legacy summaries or OCR output.
            logger.warning("trusted health context fetch failed: %s", exc)

    # Glucose summaries, meals, and symptoms do not yet have an admitted
    # trust-store projection. Keep their legacy response keys fail-closed so
    # no raw table or service value can bypass the admission boundary.
    summary_24h = {"gaps_hours": None}
    summary_7d = {"gaps_hours": None}

    profile_info = _trusted_profile_info(trusted_health_context)

    # Every AI entry point receives the same fail-closed trust projection.
    # Unversioned legacy AI summaries are intentionally not forwarded.
    health_report_text = _trusted_report_text(trusted_health_context)
    health_summary_text = ""
    patient_history = _trusted_profile_history(trusted_health_context)

    return {
        "profile": {},
        "glucose_summary": {
            "last_24h": summary_24h,
            "last_7d": summary_7d,
        },
        "meals_today": [],
        "symptoms_last_7d": [],
        "data_quality": {
            "glucose_gaps_hours": summary_24h["gaps_hours"],
            "kcal_today": 0,
        },
        # Feature snapshots and omics summaries remain excluded until they
        # have their own admitted-evidence projection.
        "agent_features": {},
        "user_profile_info": profile_info,
        "health_report_text": health_report_text,
        "health_summary_text": health_summary_text,
        "patient_history": patient_history,
        "omics_analyses": [],
        "current_medications": list(
            trusted_health_context.get("medications") or []
        ),
        "trusted_health_context": trusted_health_context,
        # Cross-conversation assistant text can contain health values that
        # predate the trust boundary. Only the explicitly supplied/current
        # authorized history is retained by build_message_structure.
        "recent_conversation_summaries": [],
        "message_structure": build_message_structure(
            db,
            user_id,
            user_query=user_query,
            conversation_id=conversation_id if trusted_context_loaded else None,
            history=history if trusted_context_loaded else [],
            subject_profile=profile_info,
            trusted_health_context=trusted_health_context,
        ),
    }


def _trusted_report_text(context: dict) -> str:
    lines: list[str] = []
    for observation in context.get("report_observations") or []:
        value = observation.get("value_numeric")
        if value is None:
            value = observation.get("value_text") or ""
        unit = observation.get("unit") or ""
        abnormal = "，异常" if observation.get("abnormal_state") == "abnormal" else ""
        effective_at = str(observation.get("effective_at") or "")[:10]
        lines.append(
            f"{effective_at} {observation.get('canonical_name') or ''}: "
            f"{value} {unit}{abnormal}"
        )
    return "\n".join(lines)[:6000]


def _trusted_profile_history(context: dict) -> dict:
    grouped: dict[str, list[dict]] = {}
    for fact in context.get("profile_facts") or []:
        category = str(fact.get("category") or "other")
        grouped.setdefault(category, []).append(
            {
                "fact_key": fact.get("fact_key"),
                "value": fact.get("value"),
                "confirmed_at": fact.get("confirmed_at"),
                "version": fact.get("version"),
            }
        )
    return {"confirmed_facts": grouped} if grouped else {}


def _trusted_profile_info(context: dict) -> dict:
    profile: dict = {}
    key_map = {
        "basic.birth_date": "birth_date",
        "basic.sex": "sex",
        "basic.height": "height_cm",
        "basic.weight": "weight_kg",
        "basic.blood_type": "blood_type",
        "basic.region": "region",
    }
    for fact in context.get("profile_facts") or []:
        output_key = key_map.get(str(fact.get("fact_key") or ""))
        if output_key is None:
            continue
        payload = fact.get("value") or {}
        value = payload.get("value") if isinstance(payload, dict) else payload
        if isinstance(value, dict):
            value = value.get(output_key) or value.get("value")
        if value is not None:
            profile[output_key] = value
    return profile


def build_message_structure(
    db: Session,
    user_id: str | int,
    *,
    user_query: str = "",
    conversation_id: int | None = None,
    history: list[dict] | None = None,
    subject_profile: dict | None = None,
    trusted_health_context: dict | None = None,
) -> dict:
    """Build a deterministic chat envelope before the LLM sees context.

    This is the guardrail layer for subject ownership, source memory,
    freshness, response depth, and repetition control. It intentionally
    derives from persisted data instead of asking the LLM to guess.
    """
    query = user_query.strip()
    data_source_memory = _get_data_source_memory(db, user_id)
    if trusted_health_context is not None:
        data_source_memory = _trusted_data_source_memory(data_source_memory)
    report_status = _get_report_status_memory(db, user_id)
    active_subject = _resolve_active_subject(query, history or [])
    health_nlu = analyze_health_message(
        query,
        active_subject=active_subject,
        history=history or [],
        subject_profile=subject_profile or {},
    )
    intent = _classify_intent(query, active_subject, health_nlu)
    session_memory = _build_session_memory(db, user_id, conversation_id, history or [], current_query=query)
    health_fact_index = (
        _trusted_health_fact_index(trusted_health_context)
        if trusted_health_context is not None
        else _get_health_fact_index(db, user_id)
    )
    evidence_sufficiency = assess_trend_evidence(
        user_query=query,
        health_nlu=health_nlu,
        data_source_memory=data_source_memory,
        subject_type=str(active_subject.get("type") or "self"),
    )
    response_plan = _build_response_plan(
        query=query,
        intent=intent,
        active_subject=active_subject,
        data_source_memory=data_source_memory,
        report_status=report_status,
        session_memory=session_memory,
        health_fact_index=health_fact_index,
        health_nlu=health_nlu,
    )
    response_plan["evidence_sufficiency"] = evidence_sufficiency
    structure = {
        "version": "2026-07-10",
        "user_message": {
            "raw": query,
            "normalized": _normalize_text(query),
            "length": len(query),
        },
        "health_nlu": health_nlu,
        "intent": intent,
        "active_subject": active_subject,
        "data_source_memory": data_source_memory,
        "report_status": report_status,
        "health_fact_index": health_fact_index,
        "session_memory": session_memory,
        "response_plan": response_plan,
    }
    structure["interaction_route"] = resolve_chat_route(structure).to_dict()
    return structure


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
        synced_at = _as_aware_utc(row.updated_at or row.created_at)
        if measured_at:
            if not source["first_sample_at"] or measured_at < source["first_sample_at"]:
                source["first_sample_at"] = measured_at
            if not source["last_sample_at"] or measured_at > source["last_sample_at"]:
                source["last_sample_at"] = measured_at
        if synced_at and (not source["last_sync_at"] or synced_at > source["last_sync_at"]):
            source["last_sync_at"] = synced_at

        metric = metric_sources.setdefault(row.indicator_name, {
            "metric": row.indicator_name,
            "source": source_key,
            "last_value": row.value if row.value_kind != "category" else None,
            "display_value": row.display_value,
            "value_kind": row.value_kind or "numeric",
            "unit": row.unit,
            "measured_at": row.measured_at,
            "source_local_date": row.source_local_date,
            "freshness": _freshness_label(row.measured_at, now=now),
        })
        metric_ts = _as_aware_utc(metric.get("measured_at"))
        row_ts = _as_aware_utc(row.measured_at)
        if row_ts and (metric_ts is None or row_ts > metric_ts):
            metric.update({
                "source": source_key,
                "last_value": row.value if row.value_kind != "category" else None,
                "display_value": row.display_value,
                "value_kind": row.value_kind or "numeric",
                "unit": row.unit,
                "measured_at": row.measured_at,
                "source_local_date": row.source_local_date,
                "freshness": _freshness_label(row.measured_at, now=now),
            })

    uid = _safe_int(user_id)
    if uid is not None:
        try:
            source_sync_rows = db.execute(
                select(
                    UserIndicatorValue.source,
                    func.max(UserIndicatorValue.updated_at),
                )
                .where(UserIndicatorValue.user_id == uid)
                .group_by(UserIndicatorValue.source)
            ).all()
            for source_key, synced_at in source_sync_rows:
                normalized_key = (source_key or "manual").strip() or "manual"
                source = source_map.setdefault(normalized_key, {
                    "source_key": normalized_key,
                    "status": "connected",
                    "metric_count": 0,
                    "available_metrics": set(),
                    "first_sample_at": None,
                    "last_sample_at": None,
                    "last_sync_at": None,
                })
                source["last_sync_at"] = _as_aware_utc(synced_at)
        except Exception as e:  # noqa: BLE001
            logger.warning("indicator source sync times fetch failed: %s", e)

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

    for metric_name, metric in metric_sources.items():
        metric_rows = sorted(
            rows_by_metric.get(metric_name) or [],
            key=lambda item: _as_aware_utc(item.measured_at) or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        metric["recent_samples"] = [
            {
                "value": row.value if row.value_kind != "category" else None,
                "display_value": row.display_value,
                "value_kind": row.value_kind or "numeric",
                "unit": row.unit,
                "source": (row.source or "manual").strip() or "manual",
                "measured_at": _format_ts(row.measured_at),
                "source_local_date": (
                    row.source_local_date.isoformat() if row.source_local_date else None
                ),
                "freshness": _freshness_label(row.measured_at, now=now),
            }
            for row in metric_rows[:40]
        ]

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
                "display_value": item.get("display_value"),
                "value_kind": item.get("value_kind") or "numeric",
                "unit": item["unit"],
                "measured_at": _format_ts(item["measured_at"]),
                "source_local_date": (
                    item["source_local_date"].isoformat()
                    if item.get("source_local_date")
                    else None
                ),
                "freshness": item["freshness"],
                "recent_samples": item.get("recent_samples") or [],
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
            "category 指标只能使用 display_value 作为类别标签，禁止把原始编码当连续数值计算升降或范围。",
        ],
    }


def _get_metric_conflicts(rows_by_metric: dict[str, list[UserIndicatorValue]], *, now: datetime) -> list[dict]:
    conflicts = []
    for metric, rows in rows_by_metric.items():
        rows = [row for row in rows if (row.value_kind or "numeric") == "numeric"]
        if not rows:
            continue
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
    try:
        workflows = db.execute(
            select(HealthReportWorkflow)
            .where(HealthReportWorkflow.user_id == uid)
            .order_by(HealthReportWorkflow.created_at.desc())
            .limit(20)
        ).scalars().all()
    except Exception as e:  # noqa: BLE001
        logger.warning("report workflow status unavailable: %s", e)
        workflows = []

    workflows_by_document = {item.legacy_document_id: item for item in workflows}
    docs = [
        doc
        for doc in docs
        if not (
            (workflow := workflows_by_document.get(doc.id))
            and workflow.status == "failed"
            and workflow.failure_code == "withdrawn"
        )
    ]
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
            "workflow_id": workflows_by_document[doc.id].id if doc.id in workflows_by_document else None,
            "workflow_status": (
                workflows_by_document[doc.id].status if doc.id in workflows_by_document else None
            ),
        }
        for doc in docs
    ]
    return {
        "documents": documents,
        "pending_count": sum(1 for doc in docs if doc.extraction_status == "pending"),
        "done_count": sum(1 for doc in docs if doc.extraction_status == "done"),
        "failed_count": sum(1 for doc in docs if doc.extraction_status == "failed"),
        "awaiting_confirmation_count": sum(
            1 for workflow in workflows if workflow.status == "awaiting_confirmation"
        ),
        "admitted_count": sum(
            1 for workflow in workflows if workflow.status in {"completed", "completed_score_pending"}
        ),
        "latest": documents[0] if documents else None,
        "rules": [
            "报告状态类问题优先回答识别/分析状态，不进入深度医学分析。",
            "pending 表示后台 OCR 识别中；done 只表示 OCR 完成，不代表数据可信或已准入。",
            "只有 workflow_status 为 completed/completed_score_pending 的确认观察值才能用于医学解读。",
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
            "value": row.display_value if row.value_kind == "category" else row.value,
            "value_kind": row.value_kind or "numeric",
            "display_value": row.display_value,
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


def _trusted_data_source_memory(raw: dict) -> dict:
    """Keep connection/freshness metadata while removing unadmitted values."""
    sources = []
    for source in raw.get("sources") or []:
        sources.append(
            {
                "source_key": source.get("source_key"),
                "status": source.get("status"),
                "metric_count": source.get("metric_count"),
                "available_metrics": list(source.get("available_metrics") or []),
                "first_sample_at": source.get("first_sample_at"),
                "last_sample_at": source.get("last_sample_at"),
                "last_sync_at": source.get("last_sync_at"),
                "freshness": source.get("freshness"),
            }
        )
    metrics = [
        {
            "metric": metric.get("metric"),
            "source": metric.get("source"),
            "unit": metric.get("unit"),
            "measured_at": metric.get("measured_at"),
            "freshness": metric.get("freshness"),
            "trust_state": "metadata_only",
        }
        for metric in raw.get("metrics") or []
    ]
    return {
        "sources": sources,
        "metrics": metrics,
        "connected": dict(raw.get("connected") or {}),
        "forbidden_questions": list(raw.get("forbidden_questions") or []),
        "metric_conflicts": [],
        "source_interpretation_rules": [
            *(raw.get("source_interpretation_rules") or []),
            "数值只允许来自 trusted health projection；metadata_only 不能作为健康结论。",
        ],
    }


def _trusted_health_fact_index(context: dict) -> dict:
    facts: list[dict] = []
    for fact in context.get("profile_facts") or []:
        facts.append(
            {
                "owner": "user_self",
                "metric": fact.get("fact_key"),
                "value": fact.get("value"),
                "source": "confirmed_profile_fact",
                "measured_at": fact.get("confirmed_at"),
                "freshness": "confirmed",
                "confidence": "confirmed",
                "version": fact.get("version"),
            }
        )
    for observation in context.get("report_observations") or []:
        facts.append(
            {
                "owner": "user_self",
                "metric": observation.get("canonical_code")
                or observation.get("canonical_name"),
                "value": observation.get("value_numeric")
                if observation.get("value_numeric") is not None
                else observation.get("value_text"),
                "unit": observation.get("unit"),
                "source": "admitted_report_observation",
                "measured_at": observation.get("effective_at"),
                "freshness": "admitted",
                "confidence": "confirmed",
                "observation_id": observation.get("observation_id"),
            }
        )
    for observation in context.get("device_observations") or []:
        facts.append(
            {
                "owner": "user_self",
                "metric": observation.get("fact_key"),
                "value": observation.get("value_numeric")
                if observation.get("value_numeric") is not None
                else observation.get("value_text"),
                "unit": observation.get("unit"),
                "source": "confirmed_device_profile_observation",
                "measured_at": observation.get("effective_at"),
                "freshness": "confirmed",
                "confidence": "confirmed",
                "observation_id": observation.get("observation_id"),
            }
        )
    return {
        "facts": facts[:100],
        "rules": [
            "这里只包含已确认画像事实、已入库报告 observation 和确认绑定的设备 observation。",
            "不得从 metadata_only 数据源元数据推断健康数值。",
        ],
    }


def _resolve_active_subject(query: str, history: list[dict]) -> dict:
    text = _normalize_text(query)
    correction = bool(re.search(
        r"不是我|不是我的|帮.*问|给.*问|是.*问的|问的是|其实是我|这次是我|这回是我|说回我|回到我",
        query,
    ))
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

    explicit_self = bool(re.search(
        r"(?:^|[，。！？!?；;])\s*(?:"
        r"(?:其实|这次|这回|接下来|说回|回到|再说)\s*(?:是|说)?\s*(?:我自己|我本人|本人|我的|我)"
        r"|(?:现在|那)?\s*(?:我自己|我本人|本人|我的|我)(?:\s|刚|现在|今天|昨天|测|有|没有|觉得|是|也|自己|的)"
        r")",
        query,
    ))
    if explicit_self:
        recent_user_messages = [m.get("content", "") for m in history[-8:] if m.get("role") == "user"]
        switched_from_relative = any(
            pattern.search(prior)
            for prior in recent_user_messages
            for _, _, pattern in _RELATIVE_PATTERNS
        )
        return {
            "type": "self",
            "relation": "self",
            "display": "本人",
            "data_binding": "authorized_user_account",
            "data_permission_scope": "full_self_context",
            "source": "current_user_message",
            "confidence": 0.96,
            "correction_applied": correction or switched_from_relative,
        }
    continuation = bool(re.search(r"她|他|ta|这个|那个|刚才|后来|现在|那(?:么|就)?|继续|这种情况", query, re.IGNORECASE))
    if continuation and not explicit_self:
        recent_user_messages = [m.get("content", "") for m in history[-8:] if m.get("role") == "user"]
        for prior in reversed(recent_user_messages):
            for key, label, pattern in _RELATIVE_PATTERNS:
                if pattern.search(prior):
                    return {
                        "type": "relative",
                        "relation": key,
                        "display": label,
                        "data_binding": "not_authorized",
                        "data_permission_scope": "user_statement_only",
                        "source": "recent_conversation",
                        "confidence": 0.82,
                        "correction_applied": correction,
                    }

    if continuation and re.search(r"她|他|ta", query, re.IGNORECASE) and not explicit_self:
        return {
            "type": "other_case",
            "relation": "unspecified_other",
            "display": "对方",
            "data_binding": "not_authorized",
            "data_permission_scope": "user_statement_only",
            "source": "current_pronoun_without_owner",
            "confidence": 0.68,
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


def _classify_intent(query: str, active_subject: dict, health_nlu: dict) -> dict:
    normalized = _normalize_text(query)
    is_greeting = bool(_GREETING_RE.search(query.strip()))
    is_correction = bool(active_subject.get("correction_applied"))
    primary_intent = health_nlu.get("primary_intent") or "general_chat"
    concept_keys = health_nlu.get("concept_keys") or []
    health_query = bool(health_nlu.get("has_health_signal"))

    semantic_kind_map = {
        "greeting": "greeting",
        "data_source_query": "data_source_query",
        "report_status_query": "report_status_query",
        "subject_correction": "correction_followup",
        "report_summary": "summary_request",
        "upload_intent": "upload_or_report_question",
        "emergency_triage": "medical_question",
        "family_authorization": "medical_question",
        "pregnancy_risk": "medical_question",
        "medication_safety": "medical_question",
        "mental_health_support": "medical_question",
        "causal_assessment": "medical_question",
        "symptom_triage": "medical_question",
        "lifestyle_coaching": "medical_question",
        "conflict_analysis": "medical_question",
        "data_freshness_query": "medical_question",
        "risk_judgment": "medical_question",
        "trend_analysis": "medical_question",
        "metric_explanation": "medical_question",
        "medical_question": "medical_question",
        "general_chat": "general_chat",
    }

    if primary_intent in semantic_kind_map:
        kind = semantic_kind_map[primary_intent]
        depth = health_nlu.get("depth_hint") or "standard"
        if is_greeting:
            kind = "greeting"
            depth = "quick"
        elif is_correction and primary_intent == "subject_correction":
            kind = "correction_followup"
            depth = "quick"
        return {
            "kind": kind,
            "depth": depth,
            "health_related": health_query,
            "requires_llm": kind not in {"greeting", "data_source_query", "report_status_query"},
            "latent_purpose": health_nlu.get("latent_purpose") or "clarify_context",
            "semantic_intent": primary_intent,
            "concept_keys": concept_keys,
            "semantic_categories": health_nlu.get("semantic_categories") or [],
            "route_hint": health_nlu.get("route_hint") or "standard_llm",
            "safety_level": (health_nlu.get("safety_profile") or {}).get("level", "low"),
        }

    device_query = bool(re.search(r"Apple\s*健康|苹果健康|HealthKit|同步|手表|手环|硬件|设备|数据源", query, re.IGNORECASE))
    report_summary = bool(re.search(r"病史摘要|整理病史|总结病史|报告趋势|整理.*报告", query))
    report_status_query = bool(re.search(r"报告.*(好了吗|完成|状态|进度|分析)|识别.*(好了吗|完成|状态)|分析.*好了吗|入库.*(好了吗|完成|状态)", query))
    upload_intent = bool(re.search(r"上传|图片|pdf|拍照|相册|报告", normalized))
    health_query = health_query or bool(_HEALTH_QUERY_RE.search(query))
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
    *,
    current_query: str = "",
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

    current_normalized = _normalize_text(current_query)
    is_followup = bool(messages and _FOLLOWUP_RE.search(current_normalized))
    has_existing_health_context = bool(covered_facts or avoid_repeating or user_corrections)
    repetition_mode = "delta_only" if is_followup and has_existing_health_context else "normal"

    return {
        "covered_facts": sorted(set(covered_facts)),
        "user_corrections": user_corrections[-6:],
        "avoid_repeating": sorted(set(avoid_repeating)),
        "recent_turn_count": len(messages),
        "repetition_policy": {
            "mode": repetition_mode,
            "is_followup": is_followup,
            "max_repeated_advice_items": 1,
            "answer_delta_first": repetition_mode == "delta_only",
            "rules": [
                "连续追问时先回答新增问题，不重放已讲过的完整背景。",
                "如果必须重复旧结论，只用一句话承接，再进入新的判断或下一步。",
                "不要把快捷追问写成 AI 反问口吻。",
            ],
        },
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
    health_nlu: dict,
) -> dict:
    is_self = active_subject.get("type") == "self"
    primary_intent = intent.get("semantic_intent") or health_nlu.get("primary_intent") or intent.get("kind")
    safety_profile = health_nlu.get("safety_profile") or {"level": "low", "tags": [], "must_include": [], "forbidden": []}
    data_requirements = health_nlu.get("data_requirements") or []
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
    forbidden_questions.extend(safety_profile.get("forbidden") or [])
    repetition_policy = session_memory.get("repetition_policy") or {}

    must_answer_first = intent.get("kind") in {"correction_followup", "medical_question", "data_source_query", "report_status_query"}
    evidence_intents = {
        "risk_judgment",
        "pregnancy_risk",
        "medication_safety",
        "conflict_analysis",
        "trend_analysis",
        "report_summary",
        "metric_explanation",
        "causal_assessment",
    }
    needs_literature = bool(
        intent.get("health_related")
        and (intent.get("depth") in {"standard", "deep"} or primary_intent in evidence_intents)
        and intent.get("kind") not in {"greeting", "data_source_query", "correction_followup", "report_status_query"}
        and primary_intent != "emergency_triage"
    )
    progress_steps = _progress_steps(intent, active_subject, data_source_memory, needs_literature, health_nlu)
    answer_style = "direct_then_reason" if must_answer_first else "brief_contextual"
    if safety_profile.get("level") == "emergency":
        answer_style = "emergency_direct"
    elif primary_intent in {"data_freshness_query", "conflict_analysis"}:
        answer_style = "source_time_then_reason"

    return {
        "allowed_context": allowed_context,
        "blocked_context": blocked_context,
        "forbidden_questions": sorted(set(forbidden_questions)),
        "must_answer_first": must_answer_first,
        "max_followup_questions": 1,
        "needs_literature": needs_literature,
        "needs_llm": bool(intent.get("requires_llm")),
        "answer_style": answer_style,
        "progress_steps": progress_steps,
        "quality_gates": sorted(set([
            "不能询问 data_source_memory 已经回答的问题。",
            "不能混用 blocked_context 里的本人健康数据。",
            "引用指标时必须包含来源或测量时间；无数据则说暂无记录/待同步/待上传。",
            "不能重复 session_memory.avoid_repeating 中的建议，除非用户明确要求。",
            "如果 session_memory.repetition_policy.mode=delta_only，本轮只补新增判断和下一步，不重讲旧结论。",
            *(health_nlu.get("quality_gates") or []),
        ])),
        "safety_profile": safety_profile,
        "data_requirements": data_requirements,
        "semantic_categories": health_nlu.get("semantic_categories") or [],
        "macro_categories": health_nlu.get("macro_categories") or [],
        "primary_intent": primary_intent,
        "route_hint": health_nlu.get("route_hint") or intent.get("route_hint"),
        "available_self_fact_count": len(health_fact_index.get("facts") or []),
        "pending_report_count": int(report_status.get("pending_count") or 0),
        "covered_facts": session_memory.get("covered_facts", []),
        "repetition_policy": repetition_policy,
    }


def _progress_steps(intent: dict, active_subject: dict, data_source_memory: dict, needs_literature: bool, health_nlu: dict) -> list[str]:
    steps = ["已识别当前问题主体", "已归一化医学术语和用户意图"]
    if active_subject.get("type") == "self":
        steps.append("已读取你的健康档案和数据来源")
    else:
        steps.append(f"已切换到{active_subject.get('display', '家人')}这个独立病例")
    if data_source_memory.get("connected", {}).get("apple_health"):
        steps.append("已确认 Apple 健康同步状态")
    if data_source_memory.get("connected", {}).get("cgm"):
        steps.append("已确认连续血糖数据来源")
    if health_nlu.get("data_requirements"):
        steps.append("已检查所需指标、来源和时效")
    primary_intent = health_nlu.get("primary_intent")
    if (health_nlu.get("safety_profile") or {}).get("level") in {"medium", "high", "emergency"}:
        steps.append("已识别安全边界")
    if primary_intent == "symptom_triage":
        steps.append("已筛查普通症状和急症红旗")
    if primary_intent == "lifestyle_coaching":
        steps.append("已映射饮食、运动和作息因素")
    if primary_intent == "mental_health_support":
        steps.append("已识别心理压力和危机边界")
    if primary_intent == "causal_assessment":
        steps.append("已拆分各因素的因果链和证据边界")
    if needs_literature:
        steps.append("正在检索相关医学证据")
    elif intent.get("kind") in {"greeting", "data_source_query", "correction_followup"}:
        steps.append("正在生成简短直接回复")
    else:
        steps.append("正在整理结论和下一步建议")
    return steps[:5]


def _get_current_medications(db: Session, user_id: str) -> list[dict]:
    """Expose only active plans the user explicitly confirmed."""
    try:
        return confirmed_medication_context(db, user_id=int(user_id))
    except Exception as e:  # noqa: BLE001
        logger.warning("current_medications fetch failed: %s", e)
        return []


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
        "age": profile.age,
        "sex": profile.sex,
        "height_cm": profile.height_cm,
        "weight_kg": profile.weight_kg,
        "liver_risk_level": profile.liver_risk_level,
    }


def _get_health_report_text(db: Session, user_id: str | int) -> str:
    """Build AI context from active, user-confirmed report observations only."""
    uid = _safe_int(user_id)
    if uid is None:
        return ""
    try:
        observations = db.execute(
            select(ConfirmedHealthObservation)
            .join(
                HealthReportWorkflow,
                HealthReportWorkflow.id == ConfirmedHealthObservation.workflow_id,
            )
            .where(
                ConfirmedHealthObservation.user_id == uid,
                ConfirmedHealthObservation.subject_user_id == uid,
                ConfirmedHealthObservation.status == "active",
                HealthReportWorkflow.status.in_(["completed", "completed_score_pending"]),
            )
            .order_by(ConfirmedHealthObservation.effective_at.desc())
            .limit(120)
        ).scalars().all()
    except Exception:
        logger.warning("Failed to load admitted report observations", exc_info=True)
        return ""
    lines = []
    for observation in observations:
        value = (
            str(observation.value_numeric)
            if observation.value_numeric is not None
            else observation.value_text or ""
        )
        reference = f"，参考 {observation.reference_text}" if observation.reference_text else ""
        abnormal = "，异常" if observation.abnormal_state == "abnormal" else ""
        lines.append(
            f"{observation.effective_at.date().isoformat()} {observation.canonical_name}: "
            f"{value} {observation.unit or ''}{reference}{abnormal}"
        )
    return "\n".join(lines)[:6000]


def _get_health_summary_text(db: Session, user_id: str) -> str:
    """Fetch the AI-generated health summary from uploaded health documents."""
    uid = _safe_int(user_id)
    if uid is None:
        return ""
    try:
        admitted = db.scalar(
            select(func.count()).select_from(ConfirmedHealthObservation).join(
                HealthReportWorkflow,
                HealthReportWorkflow.id == ConfirmedHealthObservation.workflow_id,
            ).where(
                ConfirmedHealthObservation.user_id == uid,
                ConfirmedHealthObservation.subject_user_id == uid,
                ConfirmedHealthObservation.status == "active",
                HealthReportWorkflow.status.in_(["completed", "completed_score_pending"]),
            )
        )
    except Exception:
        return ""
    if not admitted:
        return ""
    row = db.execute(
        select(HealthSummary)
        .where(HealthSummary.user_id == uid)
        .order_by(HealthSummary.updated_at.desc())
        .limit(1)
    ).scalars().first()
    if row and row.summary_text:
        return row.summary_text[:2000]  # Cap length for context window
    return ""


def _get_patient_history_context(db: Session, user_id: str) -> dict:
    uid = _safe_int(user_id)
    if uid is not None:
        confirmed = confirmed_profile_context(db, user_id=uid)
        if confirmed:
            return {"confirmed_facts": confirmed}

    # Compatibility bridge: only legacy fields carrying an explicit
    # verified_by_user marker are trusted. Generated summaries, document
    # suggestions, missing-field metadata, and unverified legacy sections are
    # never sent to AI.
    row = db.execute(
        select(PatientHistoryProfile)
        .where(PatientHistoryProfile.user_id == user_id)
        .limit(1)
    ).scalars().first()
    if not row:
        return {}

    sections = normalize_sections(row.sections)
    verified_sections = {
        key: {
            "value": str(value.get("value") or "").strip(),
            "date_label": value.get("date_label"),
            "source": "confirmed_with_legacy_provenance",
        }
        for key, value in sections.items()
        if bool(value.get("verified_by_user"))
        and str(value.get("value") or "").strip()
    }
    if not verified_sections:
        return {}
    return {
        "confirmed_legacy_sections": verified_sections,
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
