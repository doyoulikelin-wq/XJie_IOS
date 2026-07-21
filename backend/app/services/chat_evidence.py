from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone


_CONCEPT_METRIC_ALIASES: dict[str, tuple[str, ...]] = {
    "blood_pressure": ("blood_pressure", "systolic_blood_pressure", "diastolic_blood_pressure", "收缩压", "舒张压", "血压"),
    "systolic_bp": ("systolic_blood_pressure", "blood_pressure_systolic", "收缩压", "高压"),
    "diastolic_bp": ("diastolic_blood_pressure", "blood_pressure_diastolic", "舒张压", "低压"),
    "heart_rate": ("heart_rate", "心率"),
    "resting_hr": ("resting_heart_rate", "静息心率"),
    "hrv": ("hrv", "heart_rate_variability", "心率变异性", "心率变异"),
    "spo2": ("spo2", "oxygen_saturation", "血氧"),
    "sleep": ("sleep", "sleep_analysis", "睡眠"),
    "steps": ("steps", "step_count", "步数"),
    "temperature": ("temperature", "body_temperature", "体温"),
    "wrist_temperature": ("wrist_temperature", "腕温", "手腕温度"),
    "weight": ("weight", "body_mass", "体重"),
    "glucose": ("glucose", "blood_glucose", "血糖"),
}


def assess_trend_evidence(
    *,
    user_query: str,
    health_nlu: dict,
    data_source_memory: dict,
    subject_type: str,
    now: datetime | None = None,
) -> dict:
    """Return an auditable evidence gate for longitudinal claims."""

    if health_nlu.get("primary_intent") != "trend_analysis" or subject_type != "self":
        return {"status": "not_applicable"}

    window_days = _requested_window_days(user_query)
    min_samples, min_distinct_days = _minimum_coverage(window_days)
    concept_keys = [str(item) for item in health_nlu.get("concept_keys") or []]
    concept_displays = {
        str(item.get("key")): str(item.get("display") or item.get("key") or "指标")
        for item in health_nlu.get("matched_concepts") or []
    }
    metrics = data_source_memory.get("metrics") or []
    selected = _select_metric(metrics, concept_keys)
    display_name = concept_displays.get(concept_keys[0], concept_keys[0]) if concept_keys else "该指标"

    if selected is None:
        return {
            "status": "missing",
            "metric": concept_keys[0] if concept_keys else "",
            "display_name": display_name,
            "window_days": window_days,
            "sample_count": 0,
            "distinct_days": 0,
            "min_required_samples": min_samples,
            "min_required_days": min_distinct_days,
            "latest_sample": None,
        }

    display_name = concept_displays.get(concept_keys[0]) or str(selected.get("display_name") or selected.get("metric") or display_name)
    current = _as_aware(now) or datetime.now(timezone.utc)
    cutoff = current - timedelta(days=window_days)
    samples: list[tuple[datetime, dict]] = []
    for sample in selected.get("recent_samples") or []:
        measured_at = _parse_time(sample.get("measured_at"))
        if measured_at is not None and measured_at >= cutoff:
            samples.append((measured_at, sample))
    samples.sort(key=lambda item: item[0])
    distinct_days = len({
        _sample_local_date(item[1]) or item[0].date()
        for item in samples
    })
    status = "sufficient" if len(samples) >= min_samples and distinct_days >= min_distinct_days else "insufficient"
    latest = dict(samples[-1][1]) if samples else None

    value_kind = str(selected.get("value_kind") or "numeric")
    values = [
        float(item[1]["value"])
        for item in samples
        if value_kind == "numeric" and isinstance(item[1].get("value"), (int, float))
    ]
    computed = {}
    if values:
        computed = {
            "minimum": min(values),
            "maximum": max(values),
            "first": values[0],
            "last": values[-1],
            "delta": values[-1] - values[0],
        }

    return {
        "status": status,
        "metric": selected.get("metric"),
        "display_name": display_name,
        "window_days": window_days,
        "sample_count": len(samples),
        "distinct_days": distinct_days,
        "min_required_samples": min_samples,
        "min_required_days": min_distinct_days,
        "latest_sample": latest,
        "value_kind": value_kind,
        "computed_range": computed,
        "claim_rules": [
            "样本覆盖未达到门槛时，禁止描述稳定、上升、下降、波动或几天偏高/偏低。",
            "达到门槛后也只能引用结构化样本中的数量、范围和首末变化，不能虚构未提供的日期。",
            "category 指标只能按 display_value 标签描述记录和类别变化，禁止对原始编码计算升降、均值或范围。",
        ],
    }


def build_evidence_limited_reply(evidence: dict) -> dict:
    name = str(evidence.get("display_name") or evidence.get("metric") or "该指标")
    window_days = int(evidence.get("window_days") or 7)
    sample_count = int(evidence.get("sample_count") or 0)
    distinct_days = int(evidence.get("distinct_days") or 0)
    required_samples = int(evidence.get("min_required_samples") or 4)
    required_days = int(evidence.get("min_required_days") or 4)
    latest = evidence.get("latest_sample") or {}

    if sample_count == 0:
        summary = (
            f"最近 {window_days} 天没有查到{name}样本，所以当前不能生成趋势结论。"
            f"我不会把空白数据描述成稳定、升高或降低；同步到至少 {required_days} 天、{required_samples} 个有效样本后，"
            "再按实际范围和首末变化分析。"
        )
    else:
        value = (
            str(latest.get("display_value") or "")
            if evidence.get("value_kind") == "category"
            else _format_number(latest.get("value"))
        )
        unit = str(latest.get("unit") or "")
        source = _source_label(latest.get("source"))
        when = _format_time(latest.get("measured_at"))
        sample_text = f"最近 {window_days} 天只有 {sample_count} 个{name}样本，覆盖 {distinct_days} 天"
        measured_value = " ".join(part for part in (value, unit) if part)
        latest_parts = [part for part in (measured_value, source, when) if part]
        latest_text = f"；最近一次是{'，'.join(latest_parts)}" if latest_parts else ""
        summary = (
            f"{sample_text}{latest_text}。这只能代表已记录的测量点，不能得出“一周稳定、下降或几天偏低”这类趋势结论。"
            f"当前最需要关注的是样本覆盖：在相近测量条件下积累至少 {required_days} 天、{required_samples} 个有效样本，"
            "达到门槛后我再按真实范围和首末变化给出结论。"
        )

    analysis = (
        summary
        + "\n\n证据门槛按样本数量和独立日期共同控制，避免把单次测量扩写成连续趋势。"
        "现有记录会保留来源和时间，不会被手动记录或设备记录互相覆盖。"
    )
    return {
        "summary": summary,
        "analysis": analysis,
        "followups": [f"查看{name}采样记录"],
    }


def _select_metric(metrics: list[dict], concept_keys: list[str]) -> dict | None:
    aliases = []
    for key in concept_keys:
        aliases.extend(_CONCEPT_METRIC_ALIASES.get(key, (key,)))
    normalized_aliases = {_normalize(item) for item in aliases if _normalize(item)}
    for metric in metrics:
        normalized_metric = _normalize(metric.get("metric"))
        if normalized_metric in normalized_aliases:
            return metric
        if any(len(alias) >= 3 and (alias in normalized_metric or normalized_metric in alias) for alias in normalized_aliases):
            return metric
    return None


def _requested_window_days(query: str) -> int:
    text = query or ""
    match = re.search(r"(?:最近|近)?\s*(\d{1,3})\s*(?:天|日)", text)
    if match:
        return max(1, min(int(match.group(1)), 90))
    if re.search(r"一周|本周|这周|近周", text):
        return 7
    if re.search(r"一个月|本月|这月|近月", text):
        return 30
    if re.search(r"今天|今日|24\s*小时", text):
        return 1
    return 14


def _minimum_coverage(window_days: int) -> tuple[int, int]:
    if window_days <= 1:
        return 3, 1
    if window_days <= 7:
        return 4, 4
    if window_days <= 14:
        return 5, 4
    return 7, 7


def _normalize(value: object) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", str(value or "").lower())


def _parse_time(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return _as_aware(value)
    if not value:
        return None
    try:
        return _as_aware(datetime.fromisoformat(str(value).replace("Z", "+00:00")))
    except ValueError:
        return None


def _sample_local_date(sample: dict) -> date | None:
    value = sample.get("source_local_date")
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)).date()
    except ValueError:
        return None


def _as_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _format_time(value: object) -> str:
    parsed = _parse_time(value)
    if parsed is None:
        return ""
    local = parsed.astimezone(timezone(timedelta(hours=8)))
    return f"{local.year}年{local.month}月{local.day}日 {local.hour:02d}:{local.minute:02d}"


def _format_number(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return ""
    return f"{float(value):g}"


def _source_label(value: object) -> str:
    key = str(value or "").strip().lower()
    if key in {"apple_health", "healthkit", "apple"}:
        return "Apple 健康"
    if key in {"cgm", "vendor_cgm", "dexcom", "libre"}:
        return "连续血糖设备"
    if key == "manual":
        return "手动记录"
    return "其他设备" if key else ""
