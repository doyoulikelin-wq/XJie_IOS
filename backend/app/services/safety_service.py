from app.services.health_nlu import analyze_health_message


EMERGENCY_KEYWORDS = [
    "胸痛",
    "胸口痛",
    "压榨样疼痛",
    "冷汗",
    "昏厥",
    "晕倒",
    "意识丧失",
    "呼吸困难",
    "喘不上气",
    "意识模糊",
    "抽搐",
    "口角歪",
    "说话不清",
    "半边无力",
    "偏瘫",
    "中风",
    "大出血",
    "严重低血糖",
    "严重高血糖",
    "不想活",
    "自杀",
    "seizure",
    "faint",
    "chest pain",
    "shortness of breath",
    "stroke",
    "suicide",
    "想死",
    "活不下去",
    "结束生命",
    "伤害自己",
    "说不清话",
    "一侧无力",
    "单侧无力",
    "无法呼吸",
    "叫不醒",
    "服药过量",
    "药物过量",
]


def detect_safety_flags(user_message: str) -> list[str]:
    try:
        safety = analyze_health_message(user_message).get("safety_profile") or {}
        if safety.get("level") == "emergency":
            return ["emergency_symptom"]
        return []
    except Exception:  # noqa: BLE001
        pass
    msg = user_message.lower()
    for kw in EMERGENCY_KEYWORDS:
        if kw.lower() in msg:
            return ["emergency_symptom"]
    return []


def emergency_template(user_message: str = "") -> str:
    return emergency_response(user_message)["analysis"]


def emergency_response(user_message: str = "") -> dict[str, str]:
    normalized = (user_message or "").lower()
    if any(term in normalized for term in ("自杀", "不想活", "轻生", "伤害自己", "suicide")):
        analysis = (
            "你现在的安全最重要。请立即联系当地急救或报警，并马上告诉身边可信任的人陪着你；"
            "不要独处，先远离药物、刀具、绳索或其他可能伤害自己的物品。"
            "如果你已经采取了伤害自己的行动，立即拨打 120 或 110。"
        )
        return {
            "summary": "现在先保证人身安全：立即联系 120 或 110，并让可信任的人马上陪在身边，不要独处。",
            "analysis": analysis,
        }

    try:
        nlu = analyze_health_message(user_message)
    except Exception:  # noqa: BLE001
        nlu = {}
    numeric = nlu.get("numeric_risk") or {}
    reason_codes = set(numeric.get("reason_codes") or [])
    concept_keys = set(nlu.get("concept_keys") or [])
    observations = numeric.get("observations") or []

    if "bp:pregnancy_severe_with_symptoms" in reason_codes:
        bp = next((item for item in observations if item.get("metric") == "blood_pressure"), {})
        systolic = int(bp.get("systolic") or 0)
        diastolic = int(bp.get("diastolic") or 0)
        if systolic and diastolic:
            reading = f"{systolic}/{diastolic} mmHg"
        elif systolic:
            reading = f"收缩压 {systolic} mmHg"
        else:
            reading = f"舒张压 {diastolic} mmHg"
        symptom_text = "、".join(bp.get("active_symptoms") or ["孕产期急症警示症状"])
        summary = (
            f"孕期或产后血压 {reading} 已达到严重高血压阈值，同时出现{symptom_text}。"
            "这是需要立即急诊评估的组合；现在拨打 120 或立即联系产科急诊，不要自行开车或继续在家观察。"
        )
        return {
            "summary": summary,
            "analysis": (
                summary
                + "记录症状开始时间；在不延误急救的前提下准备孕周、既往血压、当前用药和产检资料。"
                "不要自行加用、停用或改变降压药剂量。"
            ),
        }

    if "glucose:ambiguous_unit_with_symptoms" in reason_codes:
        glucose = next((item for item in observations if item.get("metric") == "blood_glucose"), {})
        value = glucose.get("value")
        reading = f"{float(value):g}" if isinstance(value, (int, float)) else "当前读数"
        symptom_text = "、".join(glucose.get("active_symptoms") or ["急症警示症状"])
        summary = (
            f"血糖 {reading} 未提供单位，同时出现{symptom_text}。"
            "按 mmol/L 可能是严重高血糖急症，按 mg/dL 可能是严重低血糖；两种情况都不能在家等待。"
            "立即拨打 120 或前往急诊，不要自行开车。"
        )
        return {
            "summary": summary,
            "analysis": summary + "带上血糖仪并说明仪器单位、末次用药、进食时间和症状开始时间；不要自行追加胰岛素、运动或经口强行喂食。",
        }

    if "glucose:dka_symptom_combination" in reason_codes:
        glucose = next((item for item in observations if item.get("metric") == "blood_glucose"), {})
        value = glucose.get("value")
        unit = glucose.get("unit") or ""
        reading = " ".join(
            part for part in (f"{float(value):g}" if isinstance(value, (int, float)) else "明显升高的血糖", unit) if part
        )
        symptom_text = "、".join(glucose.get("active_symptoms") or ["酮症酸中毒警示症状"])
        summary = (
            f"血糖 {reading} 同时伴{symptom_text}，属于糖尿病酮症酸中毒的急症警示组合。"
            "立即拨打 120 或前往急诊，不要自行开车，也不要继续在家观察。"
        )
        analysis = (
            summary
            + "如果手边能测血酮或尿酮，可在不延误呼叫急救的前提下测量并把结果带给急诊；"
            "准备说明糖尿病类型、正在使用的胰岛素或降糖药、末次用药时间和症状开始时间。"
            "按既定病日方案处理，不要临时自行大幅加药。"
        )
        return {"summary": summary, "analysis": analysis}

    if "glucose:level_2_hypoglycemia" in reason_codes and concept_keys.intersection({"fainting", "seizure"}):
        summary = "严重低血糖并伴意识异常或抽搐属于急症。立即拨打 120；患者不能安全吞咽时不要经口喂糖或喂水。"
        return {
            "summary": summary,
            "analysis": summary + "让患者侧卧并保持呼吸道通畅；如有医生预先开具的胰高血糖素，按既定说明使用并等待急救。",
        }

    if "stroke_symptom" in concept_keys:
        summary = "突然一侧无力、口角歪或说话不清属于卒中急症信号。立即拨打 120，并记录最后一次正常的准确时间。"
        return {
            "summary": summary,
            "analysis": summary + "不要自行开车、进食、饮水或等待症状缓解；准备药物清单，尤其说明是否正在使用抗凝药。",
        }

    if concept_keys.intersection({"chest_pain", "dyspnea", "fainting"}):
        summary = "当前胸痛、呼吸困难或昏厥信号需要按心肺急症处理。立即停止活动并拨打 120，不要自行开车。"
        return {
            "summary": summary,
            "analysis": summary + "让身边的人陪同，记录症状开始时间；不要为了上传报告、测更多指标或继续问答而延误急救。",
        }

    analysis = (
        "你描述的症状可能属于急症。请立即停止活动并联系当地急救；在中国大陆可拨打 120。"
        "不要自行开车，也不要先等待上传报告或继续观察。"
        "如果身边有人，请让对方陪同并准备说明症状开始时间、现有疾病和正在使用的药物。"
    )
    return {
        "summary": "当前症状包含急症风险信号。立即停止活动并拨打 120，不要自行开车或继续在家等待。",
        "analysis": analysis,
    }
