from __future__ import annotations

import re


NUMERIC_RISK_VERSION = "2026-07-10.2"

# Threshold sources:
# - American Heart Association: severe hypertension >180 systolic and/or >120 diastolic.
# - ACOG: severe hypertension during pregnancy/postpartum is >=160 systolic or
#   >=110 diastolic; persistent severe readings require urgent treatment.
# - American Diabetes Association: level 2 hypoglycemia <54 mg/dL (3.0 mmol/L);
#   glucose around 240 mg/dL (13.3 mmol/L) is a common ketone-check boundary.
_BP_PAIR_RE = re.compile(r"(?<!\d)(\d{2,3})\s*[/／]\s*(\d{2,3})(?!\d)")
_SYSTOLIC_RE = re.compile(r"(?:收缩压|高压|sbp)\D{0,8}(\d{2,3})", re.IGNORECASE)
_DIASTOLIC_RE = re.compile(r"(?:舒张压|低压|dbp)\D{0,8}(\d{2,3})", re.IGNORECASE)
_GENERIC_BP_SINGLE_RE = re.compile(r"(?:血压)\D{0,8}(\d{2,3})(?!\s*[/／])", re.IGNORECASE)
_GLUCOSE_RE = re.compile(
    r"(?:血糖|glucose|blood\s*sugar)\D{0,10}(\d{1,3}(?:\.\d+)?)\s*(mmol/l|mg/dl|毫摩尔|毫克)?",
    re.IGNORECASE,
)
_DKA_SYMPTOM_PATTERNS = (
    ("恶心", re.compile(r"恶心")),
    ("呕吐", re.compile(r"呕吐|吐了")),
    ("腹痛", re.compile(r"腹痛|肚子痛")),
    ("水果味呼气", re.compile(r"水果味|烂苹果味")),
    ("深快呼吸", re.compile(r"呼吸急促|深快呼吸|呼吸很深很快")),
    ("嗜睡", re.compile(r"嗜睡")),
    ("意识模糊", re.compile(r"意识模糊")),
)
_PREGNANCY_WARNING_PATTERNS = (
    ("剧烈头痛", re.compile(r"剧烈头痛|严重头痛|头痛(?:得|的)?(?:很|特别|非常)?厉害|头痛难忍")),
    ("视力变化", re.compile(r"视物模糊|视力模糊|眼前发花|看不清|闪光|黑蒙|视力变化")),
    ("上腹部疼痛", re.compile(r"右上腹痛|上腹痛|心窝痛|肋骨下(?:疼|痛)")),
    ("呼吸困难", re.compile(r"呼吸困难|喘不上气|无法呼吸|明显气短")),
    ("抽搐", re.compile(r"抽搐|惊厥")),
    ("意识异常", re.compile(r"意识模糊|意识不清|叫不醒|昏厥|晕倒")),
)
_PREGNANCY_CONTEXT_RE = re.compile(
    r"怀孕|妊娠|孕期|孕妇|孕周|胎儿|胎心|胎动|已经怀上|有孕|"
    r"(?<!备)孕\s*(?:妇|妈|期|周|早期|中期|晚期|\d|[一二三四五六七八九十两])|"
    r"\b(?:nt|nipt|crl)\b|无创(?:dna)?|头臀长",
    re.IGNORECASE,
)
_PREGNANCY_NEGATION_RE = re.compile(r"没有怀孕|没怀孕|未怀孕|并未怀孕|不是孕妇|排除妊娠")
_POSTPARTUM_RE = re.compile(r"产后(?:\s*(\d{1,3})\s*(天|日|周|个月|月))?")
_PEDIATRIC_CONTEXT_RE = re.compile(r"婴儿|幼儿|儿童|小孩|宝宝|未成年|青少年")
_AGE_YEARS_RE = re.compile(r"(?<!\d)(\d{1,2})\s*岁")
_NEGATION_RE = re.compile(r"没有|并无|无|否认|不伴|未见|未出现|不是")
_RESOLVED_RE = re.compile(r"已缓解|已经缓解|已经好了|现在好了|目前没有|现已消失")


def analyze_numeric_health_risk(
    query: str,
    *,
    concept_keys: list[str] | None = None,
    context_traits: dict | None = None,
) -> dict:
    normalized = (query or "").replace("μ", "u").lower()
    concept_keys = concept_keys or []
    context_traits = context_traits or {}
    observations: list[dict] = []
    must_include: list[str] = []
    forbidden: list[str] = []
    reason_codes: list[str] = []
    level = "low"

    bp_values = _blood_pressure_values(normalized, concept_keys)
    if bp_values:
        systolic, diastolic = bp_values
        pregnancy_context = _is_pregnancy_or_postpartum_context(normalized, concept_keys, context_traits)
        pregnancy_warning_symptoms = _active_symptoms(normalized, _PREGNANCY_WARNING_PATTERNS)
        observation = {
            "metric": "blood_pressure",
            "systolic": systolic,
            "diastolic": diastolic,
            "unit": "mmHg",
        }
        if pregnancy_context:
            observation["pregnancy_context"] = True
        if pregnancy_warning_symptoms:
            observation["active_symptoms"] = pregnancy_warning_symptoms
        observations.append(observation)

        if pregnancy_context and (systolic >= 160 or diastolic >= 110):
            level = _max_level(level, "high")
            reason_codes.append("bp:pregnancy_severe")
            must_include.extend([
                "立即联系产科急诊或分娩医院，不等待下次产检",
                "在不延误就医的前提下于 15 分钟内规范复测",
                "不能自行加用、停用或改变降压药剂量",
            ])
            forbidden.append("不能把孕产期严重高血压按普通成人 180/120 阈值处理")
            if pregnancy_warning_symptoms:
                level = "emergency"
                reason_codes.append("bp:pregnancy_severe_with_symptoms")
        elif pregnancy_context and (systolic >= 140 or diastolic >= 90):
            if pregnancy_warning_symptoms:
                level = _max_level(level, "high")
                reason_codes.append("bp:pregnancy_elevated_with_warning_symptoms")
                must_include.append("血压升高合并孕产期警示症状时立即联系产科急诊")
            else:
                level = _max_level(level, "medium")
                reason_codes.append("bp:pregnancy_hypertension")
                must_include.append("孕产期血压达到 140/90 mmHg 应规范复测并尽快联系产科评估")
            forbidden.append("不能等待常规产检再处理持续升高的孕产期血压")
        elif systolic > 180 or diastolic > 120:
            level = _max_level(level, "high")
            reason_codes.append("bp:severe_range")
            must_include.extend([
                "静坐至少 1 分钟后用正确姿势复测血压",
                "复测仍高于 180/120 时立即联系医疗专业人员",
                "合并胸痛、呼吸困难、麻木无力、视力变化或说话困难时立即急救",
            ])
            forbidden.append("不能仅凭一次极高读数直接给出长期诊断或自行加药指令")
        elif systolic >= 160 or diastolic >= 100:
            level = _max_level(level, "medium")
            reason_codes.append("bp:markedly_high")
            must_include.extend(["说明需要规范复测并尽快评估持续升高原因", "不能把单次读数当作长期基线"])

    glucose = _glucose_value(normalized, concept_keys)
    if glucose:
        value, unit, mg_dl = glucose
        active_dka_symptoms = _active_dka_symptoms(normalized)
        observation = {
            "metric": "blood_glucose",
            "value": value,
            "unit": unit or None,
            "normalized_mg_dl": round(mg_dl, 1) if mg_dl is not None else None,
        }
        age_years = _subject_age_years(normalized, context_traits)
        if age_years is not None:
            observation["subject_age_years"] = age_years
        if _is_pediatric_context(normalized, context_traits, age_years):
            observation["pediatric_context"] = True
        elif context_traits.get("possible_pediatric"):
            observation["possible_pediatric_context"] = True
        if active_dka_symptoms:
            observation["active_symptoms"] = active_dka_symptoms
        observations.append(observation)
        if mg_dl is None:
            reason_codes.append("glucose:unit_missing")
            must_include.append("先核对设备显示单位是 mmol/L 还是 mg/dL")
            if _unitless_glucose_is_dangerous(value):
                level = _max_level(level, "high")
                reason_codes.append("glucose:unit_ambiguous_dangerous")
                must_include.append("单位不明但数值在常见两种解释下均可能需要立即处理")
                forbidden.append("不能在单位缺失时直接按单一高血糖或低血糖方案自行加药")
                if active_dka_symptoms:
                    level = "emergency"
                    reason_codes.append("glucose:ambiguous_unit_with_symptoms")
        elif mg_dl < 54:
            level = _max_level(level, "high")
            reason_codes.append("glucose:level_2_hypoglycemia")
            must_include.extend(["先按既定低血糖处理方案立即处理并复测", "意识异常、抽搐或不能吞咽时立即急救，不能经口喂食"])
            forbidden.append("不能把低于 54 mg/dL 的读数仅作为普通趋势观察")
        elif mg_dl < 70:
            level = _max_level(level, "medium")
            reason_codes.append("glucose:low")
            must_include.append("说明低血糖处理和短时间复测要求")
        elif mg_dl >= 240:
            level = _max_level(level, "high")
            reason_codes.append("glucose:ketone_check_range")
            must_include.extend(["结合糖尿病类型、用药和症状判断，并提示按既定方案检查酮体", "出现恶心呕吐、腹痛、深快呼吸、嗜睡或意识异常时立即急诊"])
            forbidden.append("不能只给饮食建议而忽略酮症酸中毒风险筛查")
            if active_dka_symptoms:
                level = "emergency"
                reason_codes.append("glucose:dka_symptom_combination")

    return {
        "version": NUMERIC_RISK_VERSION,
        "level": level,
        "observations": observations,
        "reason_codes": list(dict.fromkeys(reason_codes)),
        "must_include": list(dict.fromkeys(must_include)),
        "forbidden": list(dict.fromkeys(forbidden)),
    }


def build_high_numeric_risk_reply(
    numeric_risk: dict,
    *,
    subject: dict | None = None,
    profile: dict | None = None,
) -> dict[str, object]:
    observations = numeric_risk.get("observations") or []
    reason_codes = set(numeric_risk.get("reason_codes") or [])

    if reason_codes.intersection({"bp:pregnancy_severe", "bp:pregnancy_elevated_with_warning_symptoms"}):
        bp = next((item for item in observations if item.get("metric") == "blood_pressure"), {})
        reading = _blood_pressure_reading(bp, fallback="当前孕产期血压")
        symptom_text = "、".join(bp.get("active_symptoms") or [])
        if "bp:pregnancy_severe" in reason_codes:
            summary = (
                f"孕期或产后血压 {reading} 已达到严重高血压阈值：收缩压达到 160 或舒张压达到 110 mmHg 就需要立即处理。"
                "现在立即联系产科急诊或分娩医院，不要等待下次产检；在不延误联系和就医的前提下，安静坐位并在 15 分钟内规范复测。"
            )
        else:
            summary = (
                f"孕期或产后血压 {reading} 已升高"
                f"，同时出现{symptom_text or '孕产期警示症状'}。现在立即联系产科急诊或分娩医院，不要继续在家观察。"
            )
        summary += "出现抽搐、意识异常、呼吸困难或症状快速加重时立即拨打 120。"
        return {
            "summary": summary,
            "analysis": summary + "不要自行加药、减药或停药；带上孕周、两次血压、症状开始时间和当前用药信息。",
            "followups": ["记录 15 分钟内复测结果"],
        }

    if "bp:severe_range" in reason_codes:
        bp = next((item for item in observations if item.get("metric") == "blood_pressure"), {})
        reading = _blood_pressure_reading(bp, fallback="高于 180/120 mmHg 的读数")
        summary = (
            f"血压 {reading} 属于严重升高范围。现在安静坐至少 1 分钟，用合适袖带在同一上臂复测；"
            "如果复测仍高于 180/120，立即联系医生或医疗机构获取当日处理指导。"
            "一旦出现胸痛、呼吸困难、视力变化、麻木无力或说话困难，立即拨打 120。"
        )
        return {
            "summary": summary,
            "analysis": summary + "不要因单次读数自行加药、减药或停药；记录两次读数、测量时间、当时症状和现用药物。",
            "followups": ["记录复测血压结果"],
        }

    glucose = next((item for item in observations if item.get("metric") == "blood_glucose"), {})
    value = glucose.get("value")
    unit = str(glucose.get("unit") or "")
    reading = " ".join(part for part in (f"{float(value):g}" if isinstance(value, (int, float)) else "当前读数", unit) if part)
    pediatric_scope = _pediatric_scope(glucose, subject or {}, profile or {})

    if "glucose:unit_ambiguous_dangerous" in reason_codes:
        numeric_value = float(value) if isinstance(value, (int, float)) else None
        if numeric_value is not None and numeric_value < 3.9:
            meaning = "按 mmol/L 或 mg/dL 理解都属于低血糖危险值"
            immediate = _hypoglycemia_immediate_action(pediatric_scope)
        elif numeric_value is not None and numeric_value >= 240:
            meaning = "按 mg/dL 已明显升高，按 mmol/L 则更高"
            immediate = "立即复测并检查血酮或尿酮"
        else:
            meaning = "按 mmol/L 属于严重高值，按 mg/dL 属于严重低值"
            immediate = "立即核对仪器单位并复测，不要自行追加胰岛素、运动或盲目补糖"
        summary = (
            f"血糖 {reading} 未提供单位，{meaning}。{immediate}。"
            "出现意识异常、抽搐、不能吞咽、持续呕吐、腹痛或深快呼吸时立即拨打 120。"
        )
        return {
            "summary": summary,
            "analysis": summary + "记录仪器单位、复测值、症状和末次用药时间，并在当天联系医生确认后续处理。",
            "followups": ["记录单位和复测结果"],
        }

    if "glucose:level_2_hypoglycemia" in reason_codes:
        immediate = _hypoglycemia_immediate_action(pediatric_scope)
        summary = (
            f"血糖 {reading} 属于严重低血糖范围。{immediate}；"
            "仍低于 3.9 mmol/L（70 mg/dL）就重复一次。意识异常、抽搐或不能吞咽时立即拨打 120，不要经口喂食。"
        )
        return {
            "summary": summary,
            "analysis": summary + "处理后补充一次含碳水和蛋白质的加餐，并联系医生排查用药、进食或运动原因。",
            "followups": ["记录 15 分钟复测结果"],
        }

    if "glucose:ketone_check_range" in reason_codes:
        summary = (
            f"血糖 {reading} 已达到需要检查酮体的范围。现在按设备说明测血酮或尿酮；"
            "出现中高水平酮体，或恶心呕吐、腹痛、深快呼吸、嗜睡、意识异常时立即急诊。"
            "没有这些信号时，按既定病日方案补水和用药，并在当天联系医生；有酮体时不要运动。"
        )
        return {
            "summary": summary,
            "analysis": summary + "不要只用运动压低血糖，也不要临时自行大幅增加胰岛素或停药。",
            "followups": ["记录酮体检查结果"],
        }

    summary = "当前数值达到高风险范围，请按既定处理方案立即复测并联系医疗专业人员。"
    return {"summary": summary, "analysis": summary, "followups": ["记录复测结果"]}


def _blood_pressure_values(text: str, concept_keys: list[str]) -> tuple[int, int] | None:
    pair = _BP_PAIR_RE.search(text)
    has_bp_context = any(key in concept_keys for key in ("blood_pressure", "systolic_bp", "diastolic_bp")) or bool(
        re.search(r"血压|高压|低压|sbp|dbp|mmhg", text, re.IGNORECASE)
    )
    if pair and has_bp_context:
        systolic, diastolic = int(pair.group(1)), int(pair.group(2))
        if 50 <= systolic <= 300 and 30 <= diastolic <= 200:
            return systolic, diastolic
    systolic_match = _SYSTOLIC_RE.search(text)
    diastolic_match = _DIASTOLIC_RE.search(text)
    if systolic_match or diastolic_match:
        return (
            int(systolic_match.group(1)) if systolic_match else 0,
            int(diastolic_match.group(1)) if diastolic_match else 0,
        )
    generic_single = _GENERIC_BP_SINGLE_RE.search(text)
    if generic_single:
        return int(generic_single.group(1)), 0
    return None


def _glucose_value(text: str, concept_keys: list[str]) -> tuple[float, str, float | None] | None:
    match = _GLUCOSE_RE.search(text)
    if not match or not any(key in concept_keys for key in ("glucose", "fasting_glucose", "postprandial_glucose", "hypoglycemia", "hyperglycemia")):
        return None
    value = float(match.group(1))
    raw_unit = (match.group(2) or "").lower()
    if "mg" in raw_unit or "毫克" in raw_unit:
        return value, "mg/dL", value
    if "mmol" in raw_unit or "毫摩尔" in raw_unit:
        return value, "mmol/L", value * 18.0
    return value, "", None


def _unitless_glucose_is_dangerous(value: float) -> bool:
    return value < 3.9 or 13.3 <= value < 54 or value >= 240


def _active_dka_symptoms(text: str) -> list[str]:
    return _active_symptoms(text, _DKA_SYMPTOM_PATTERNS)


def _active_symptoms(text: str, patterns: tuple[tuple[str, re.Pattern[str]], ...]) -> list[str]:
    active: list[str] = []
    for label, pattern in patterns:
        for match in pattern.finditer(text):
            clause_start = max(text.rfind(mark, 0, match.start()) for mark in "，,。；;！？!?\n") + 1
            prefix = text[clause_start:match.start()]
            suffix = text[match.end():match.end() + 10]
            if _NEGATION_RE.search(prefix[-12:]) or _RESOLVED_RE.search(suffix):
                continue
            active.append(label)
            break
    return active


def _is_pregnancy_or_postpartum_context(text: str, concept_keys: list[str], context_traits: dict) -> bool:
    if context_traits.get("pregnancy_or_postpartum"):
        return True
    if _PREGNANCY_NEGATION_RE.search(text):
        return False
    if _PREGNANCY_CONTEXT_RE.search(text):
        return True
    postpartum = _POSTPARTUM_RE.search(text)
    if postpartum:
        value_text, unit = postpartum.groups()
        if not value_text:
            return True
        value = int(value_text)
        if unit in {"天", "日"}:
            return value <= 42
        if unit == "周":
            return value <= 6
        return value <= 1
    return bool(set(concept_keys).intersection({"nt", "nipt", "crl", "gestational_week"}))


def _subject_age_years(text: str, context_traits: dict) -> int | None:
    match = _AGE_YEARS_RE.search(text)
    if match:
        return int(match.group(1))
    value = context_traits.get("age_years")
    if isinstance(value, int) and 0 <= value <= 120:
        return value
    return None


def _is_pediatric_context(text: str, context_traits: dict, age_years: int | None) -> bool:
    if context_traits.get("pediatric"):
        return True
    if age_years is not None:
        return age_years < 18
    return bool(_PEDIATRIC_CONTEXT_RE.search(text))


def _blood_pressure_reading(observation: dict, *, fallback: str) -> str:
    systolic = int(observation.get("systolic") or 0)
    diastolic = int(observation.get("diastolic") or 0)
    if systolic and diastolic:
        return f"{systolic}/{diastolic} mmHg"
    if systolic:
        return f"收缩压 {systolic} mmHg（舒张压未提供）"
    if diastolic:
        return f"舒张压 {diastolic} mmHg（收缩压未提供）"
    return fallback


def _pediatric_scope(glucose: dict, subject: dict, profile: dict) -> str:
    if glucose.get("pediatric_context"):
        return "confirmed"
    age = glucose.get("subject_age_years")
    if not isinstance(age, int) and subject.get("type") == "self":
        age = profile.get("age")
    if isinstance(age, int):
        return "confirmed" if age < 18 else "adult"
    if glucose.get("possible_pediatric_context") or subject.get("relation") == "child":
        return "possible"
    return "adult"


def _hypoglycemia_immediate_action(pediatric_scope: str) -> str:
    if pediatric_scope == "confirmed":
        return (
            "清醒且能安全吞咽时，立即按孩子既定低血糖方案给予快速糖并在 15 分钟后复测；"
            "儿童尤其幼儿所需快速糖通常少于成人 15 克，不要固定套用成人剂量，没有个体方案时同时联系儿科或急救获取即时指导"
        )
    if pediatric_scope == "possible":
        return (
            "清醒且能安全吞咽时立即处理并在 15 分钟后复测：未满 18 岁按既定儿童方案，"
            "幼儿通常少于成人 15 克；已经成年则摄入 15 克快速糖。年龄不明确时不要直接套用成人剂量"
        )
    return "人清醒且能安全吞咽时，立即摄入 15 克快速糖，15 分钟后复测"


def _max_level(current: str, candidate: str) -> str:
    order = {"low": 0, "medium": 1, "high": 2, "emergency": 3}
    return candidate if order[candidate] > order[current] else current
