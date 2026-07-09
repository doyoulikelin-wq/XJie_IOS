from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from app.services.numeric_health_risk import analyze_numeric_health_risk


@dataclass(frozen=True)
class HealthConcept:
    key: str
    display: str
    category: str
    aliases: tuple[str, ...]
    source_hint: str = ""
    data_requirements: tuple[str, ...] = ()
    safety_tags: tuple[str, ...] = ()


NLU_VERSION = "2026-07-10.2"

MACRO_PROBLEM_CATEGORIES = {
    "medical_semantic_normalization": "把用户缩写、口语和中英文混用归一到医学概念",
    "intent_routing": "决定快答、深度分析、报告状态、数据源查询或安全模板",
    "subject_boundary": "区分本人、家属、伴侣和未授权病例",
    "data_source_memory": "记住已经同步的 Apple 健康、CGM、手动和报告数据",
    "data_freshness": "判断指标能否代表今天或当前状态",
    "data_conflict": "发现同指标不同来源/时间的冲突，不简单覆盖",
    "report_task_state": "区分报告待识别、已完成、失败和可分析状态",
    "safety_boundary": "识别急症、孕产、用药和高风险判断边界",
    "symptom_triage": "普通症状先筛红旗，再给观察窗口和健康管理建议",
    "lifestyle_behavior": "把饮食、运动、饮水、酒精、咖啡因和作息映射到可执行行为",
    "mental_health_boundary": "识别焦虑、低落、睡眠压力和危机边界",
    "session_memory": "避免同一会话重复解释和重复追问",
    "evidence_depth": "决定是否需要医学证据检索和更严谨表达",
}


CONCEPT_CATALOG: tuple[HealthConcept, ...] = (
    HealthConcept("blood_pressure", "血压", "cardiovascular_vitals", ("血压", "bp", "blood pressure"), data_requirements=("latest_bp", "source_time")),
    HealthConcept("systolic_bp", "收缩压", "cardiovascular_vitals", ("收缩压", "高压", "sbp", "systolic"), data_requirements=("latest_bp", "source_time")),
    HealthConcept("diastolic_bp", "舒张压", "cardiovascular_vitals", ("舒张压", "低压", "dbp", "diastolic"), data_requirements=("latest_bp", "source_time")),
    HealthConcept("heart_rate", "心率", "cardiovascular_vitals", ("心率", "脉搏", "heart rate", "hr"), source_hint="apple_health_or_manual", data_requirements=("heart_rate_timeseries",)),
    HealthConcept("resting_hr", "静息心率", "cardiovascular_vitals", ("静息心率", "resting heart rate", "rhr"), source_hint="apple_health", data_requirements=("resting_hr_timeseries",)),
    HealthConcept("hrv", "心率变异性", "cardiovascular_vitals", ("hrv", "心率变异", "心率变异性", "rmssd", "sdnn"), source_hint="apple_health", data_requirements=("hrv_timeseries", "sleep_context")),
    HealthConcept("spo2", "血氧", "cardiovascular_vitals", ("血氧", "spo2", "氧饱和度", "blood oxygen"), source_hint="apple_health_or_wearable"),
    HealthConcept("respiratory_rate", "呼吸频率", "cardiovascular_vitals", ("呼吸频率", "呼吸率", "respiratory rate")),
    HealthConcept("ecg", "心电图", "cardiovascular_vitals", ("心电图", "ecg", "ekg")),
    HealthConcept("arrhythmia", "心律异常", "cardiovascular_vitals", ("心律不齐", "心律异常", "房颤", "早搏", "arrhythmia", "afib"), safety_tags=("cardiac",)),
    HealthConcept("chest_pain", "胸痛", "symptoms_emergency", ("胸痛", "胸口痛", "胸闷痛", "chest pain"), safety_tags=("emergency", "cardiac")),
    HealthConcept("palpitations", "心悸", "symptoms_emergency", ("心悸", "心慌", "palpitation")),
    HealthConcept("dyspnea", "呼吸困难", "symptoms_emergency", ("呼吸困难", "喘不上气", "憋气", "气短", "shortness of breath"), safety_tags=("emergency",)),
    HealthConcept("fainting", "昏厥", "symptoms_emergency", ("昏厥", "晕倒", "晕厥", "意识丧失", "faint", "syncope"), safety_tags=("emergency",)),
    HealthConcept("stroke_symptom", "卒中症状", "symptoms_emergency", ("口角歪", "说话不清", "半边无力", "偏瘫", "中风", "stroke"), safety_tags=("emergency",)),
    HealthConcept("glucose", "血糖", "glucose_metabolic", ("血糖", "glucose", "blood sugar"), source_hint="cgm_or_manual", data_requirements=("glucose_recent", "tir")),
    HealthConcept("fasting_glucose", "空腹血糖", "glucose_metabolic", ("空腹血糖", "fpg", "fasting glucose")),
    HealthConcept("postprandial_glucose", "餐后血糖", "glucose_metabolic", ("餐后血糖", "饭后血糖", "postprandial", "pbg")),
    HealthConcept("tir", "目标范围内时间", "glucose_metabolic", ("tir", "time in range", "目标范围内时间", "达标时间", "血糖达标率"), source_hint="cgm", data_requirements=("cgm_14d_or_7d",)),
    HealthConcept("hba1c", "糖化血红蛋白", "glucose_metabolic", ("hba1c", "a1c", "糖化", "糖化血红蛋白", "糖化血红素"), data_requirements=("lab_report", "measured_at")),
    HealthConcept("cgm", "连续血糖监测", "glucose_metabolic", ("cgm", "连续血糖", "动态血糖", "血糖设备", "血糖传感器", "libre", "dexcom"), source_hint="cgm"),
    HealthConcept("hypoglycemia", "低血糖", "glucose_metabolic", ("低血糖", "hypoglycemia", "血糖低"), safety_tags=("glucose_safety",)),
    HealthConcept("hyperglycemia", "高血糖", "glucose_metabolic", ("高血糖", "hyperglycemia", "血糖高")),
    HealthConcept("insulin_resistance", "胰岛素抵抗", "glucose_metabolic", ("胰岛素抵抗", "insulin resistance", "homa-ir", "homa ir")),
    HealthConcept("insulin", "胰岛素", "glucose_metabolic", ("胰岛素", "insulin"), safety_tags=("medication",)),
    HealthConcept("metabolic_syndrome", "代谢综合征", "glucose_metabolic", ("代谢综合征", "metabolic syndrome")),
    HealthConcept("uric_acid", "尿酸", "renal_uric", ("尿酸", "ua", "uric acid"), data_requirements=("uric_acid_lab", "renal_context")),
    HealthConcept("gout", "痛风", "renal_uric", ("痛风", "gout")),
    HealthConcept("creatinine", "肌酐", "renal_uric", ("肌酐", "creatinine", "scr")),
    HealthConcept("egfr", "估算肾小球滤过率", "renal_uric", ("egfr", "e-gfr", "肾小球滤过率", "估算肾小球滤过率")),
    HealthConcept("cystatin_c", "胱抑素C", "renal_uric", ("胱抑素c", "胱抑素 C", "cystatin c", "cysc", "cys-c")),
    HealthConcept("urea", "尿素", "renal_uric", ("尿素", "尿素氮", "bun", "urea")),
    HealthConcept("urine_protein", "尿蛋白", "renal_uric", ("尿蛋白", "蛋白尿", "proteinuria")),
    HealthConcept("microalbuminuria", "尿微量白蛋白", "renal_uric", ("尿微量白蛋白", "微量白蛋白尿", "acr", "uacr")),
    HealthConcept("hematuria", "血尿", "renal_uric", ("血尿", "尿潜血", "尿红细胞")),
    HealthConcept("alt", "谷丙转氨酶", "liver_lipids", ("alt", "谷丙", "谷丙转氨酶")),
    HealthConcept("ast", "谷草转氨酶", "liver_lipids", ("ast", "谷草", "谷草转氨酶")),
    HealthConcept("ggt", "γ-谷氨酰转移酶", "liver_lipids", ("ggt", "g-g t", "γ-gt", "谷氨酰转移酶")),
    HealthConcept("bilirubin", "胆红素", "liver_lipids", ("胆红素", "bilirubin")),
    HealthConcept("fatty_liver", "脂肪肝", "liver_lipids", ("脂肪肝", "fatty liver")),
    HealthConcept("triglycerides", "甘油三酯", "liver_lipids", ("甘油三酯", "tg", "triglyceride")),
    HealthConcept("ldl_c", "低密度脂蛋白胆固醇", "liver_lipids", ("ldl", "ldl-c", "低密度", "低密度脂蛋白")),
    HealthConcept("hdl_c", "高密度脂蛋白胆固醇", "liver_lipids", ("hdl", "hdl-c", "高密度", "高密度脂蛋白")),
    HealthConcept("total_cholesterol", "总胆固醇", "liver_lipids", ("总胆固醇", "tc", "cholesterol")),
    HealthConcept("apob", "载脂蛋白B", "liver_lipids", ("apob", "apo b", "载脂蛋白b")),
    HealthConcept("lpa", "脂蛋白(a)", "liver_lipids", ("lp(a)", "lpa", "脂蛋白a", "脂蛋白(a)")),
    HealthConcept("crp", "C反应蛋白", "inflammation_immune", ("crp", "c反应蛋白", "C反应蛋白")),
    HealthConcept("hscrp", "超敏C反应蛋白", "inflammation_immune", ("hscrp", "hs-crp", "超敏c反应蛋白", "超敏 C 反应蛋白")),
    HealthConcept("wbc", "白细胞", "inflammation_immune", ("白细胞", "wbc", "white blood cell")),
    HealthConcept("neutrophils", "中性粒细胞", "inflammation_immune", ("中性粒", "中性粒细胞", "neutrophil")),
    HealthConcept("lymphocytes", "淋巴细胞", "inflammation_immune", ("淋巴细胞", "lymphocyte")),
    HealthConcept("nlr", "中性粒/淋巴比值", "inflammation_immune", ("nlr", "中性粒淋巴比", "中性粒/淋巴")),
    HealthConcept("il6", "白介素6", "inflammation_immune", ("il-6", "il6", "白介素6")),
    HealthConcept("ferritin", "铁蛋白", "inflammation_immune", ("铁蛋白", "ferritin")),
    HealthConcept("fever", "发热", "symptoms_emergency", ("发烧", "发热", "fever")),
    HealthConcept("headache", "头痛", "symptoms_common", ("头疼", "头痛", "偏头痛", "headache", "migraine")),
    HealthConcept("dizziness", "头晕", "symptoms_common", ("头晕", "眩晕", "dizzy", "vertigo")),
    HealthConcept("fatigue", "乏力疲劳", "symptoms_common", ("疲劳", "乏力", "没精神", "累", "fatigue")),
    HealthConcept("cough", "咳嗽", "symptoms_common", ("咳嗽", "cough")),
    HealthConcept("sore_throat", "咽喉痛", "symptoms_common", ("嗓子疼", "喉咙痛", "咽痛", "sore throat")),
    HealthConcept("rhinitis", "鼻塞流涕", "symptoms_common", ("鼻塞", "流鼻涕", "打喷嚏", "runny nose")),
    HealthConcept("abdominal_pain", "腹痛", "symptoms_common", ("腹痛", "肚子疼", "肚子痛", "abdominal pain")),
    HealthConcept("stomach_pain", "胃痛", "symptoms_common", ("胃痛", "胃疼", "胃胀", "反酸", "heartburn")),
    HealthConcept("diarrhea", "腹泻", "symptoms_common", ("腹泻", "拉肚子", "diarrhea")),
    HealthConcept("constipation", "便秘", "symptoms_common", ("便秘", "constipation")),
    HealthConcept("nausea_vomiting", "恶心呕吐", "symptoms_common", ("恶心", "呕吐", "吐了", "nausea", "vomit")),
    HealthConcept("rash", "皮疹", "symptoms_common", ("皮疹", "皮肤痒", "红疹", "rash")),
    HealthConcept("allergy", "过敏", "symptoms_common", ("过敏", "allergy")),
    HealthConcept("edema", "水肿", "symptoms_common", ("水肿", "浮肿", "edema")),
    HealthConcept("insomnia", "失眠", "sleep_recovery", ("失眠", "睡不着", "入睡困难", "insomnia"), data_requirements=("sleep_duration", "sleep_stage")),
    HealthConcept("anxiety", "焦虑", "mental_wellbeing", ("焦虑", "紧张", "压力大", "panic", "anxiety"), safety_tags=("mental_health",)),
    HealthConcept("low_mood", "情绪低落", "mental_wellbeing", ("情绪低落", "抑郁", "心情不好", "depressed", "depression"), safety_tags=("mental_health",)),
    HealthConcept("pregnancy", "妊娠/怀孕", "pregnancy_reproductive", ("怀孕", "妊娠", "备孕", "孕期", "孕妇", "pregnancy"), safety_tags=("pregnancy",)),
    HealthConcept("nt", "NT 颈项透明层", "pregnancy_reproductive", ("nt", "颈项透明层", "胎儿颈项透明层", "nuchal translucency"), safety_tags=("pregnancy",), data_requirements=("gestational_week", "crl", "nt_value")),
    HealthConcept("nipt", "无创产前筛查", "pregnancy_reproductive", ("nipt", "无创", "无创dna", "无创 DNA", "产前筛查"), safety_tags=("pregnancy",)),
    HealthConcept("crl", "头臀长", "pregnancy_reproductive", ("crl", "头臀长"), safety_tags=("pregnancy",)),
    HealthConcept("hcg", "人绒毛膜促性腺激素", "pregnancy_reproductive", ("hcg", "β-hcg", "b-hcg", "绒毛膜促性腺激素")),
    HealthConcept("progesterone", "孕酮", "pregnancy_reproductive", ("孕酮", "progesterone")),
    HealthConcept("fetal", "胎儿", "pregnancy_reproductive", ("胎儿", "宝宝", "胎心", "胎动"), safety_tags=("pregnancy",)),
    HealthConcept("gestational_week", "孕周", "pregnancy_reproductive", ("孕周", "怀孕几周", "gestational week"), safety_tags=("pregnancy",)),
    HealthConcept("sleep", "睡眠", "sleep_recovery", ("睡眠", "睡着", "入睡", "sleep"), source_hint="apple_health", data_requirements=("sleep_duration", "sleep_stage")),
    HealthConcept("deep_sleep", "深睡", "sleep_recovery", ("深睡", "深度睡眠", "deep sleep")),
    HealthConcept("rem_sleep", "REM 睡眠", "sleep_recovery", ("rem", "快速眼动", "做梦期")),
    HealthConcept("awake_time", "清醒时间", "sleep_recovery", ("清醒时间", "夜醒", "醒来次数", "awake")),
    HealthConcept("recovery", "恢复", "sleep_recovery", ("恢复", "恢复评分", "recovery"), source_hint="apple_health"),
    HealthConcept("stress", "压力", "sleep_recovery", ("压力", "压力评分", "stress")),
    HealthConcept("temperature", "体温", "sleep_recovery", ("体温", "temperature", "发热")),
    HealthConcept("wrist_temperature", "手腕温度", "sleep_recovery", ("手腕温度", "腕温", "wrist temperature"), source_hint="apple_health"),
    HealthConcept("weight", "体重", "body_activity", ("体重", "weight")),
    HealthConcept("bmi", "BMI", "body_activity", ("bmi", "体质指数")),
    HealthConcept("body_fat", "体脂", "body_activity", ("体脂", "体脂率", "body fat")),
    HealthConcept("waist", "腰围", "body_activity", ("腰围", "waist")),
    HealthConcept("steps", "步数", "body_activity", ("步数", "steps"), source_hint="apple_health_or_wearable"),
    HealthConcept("exercise_minutes", "运动分钟", "body_activity", ("运动分钟", "锻炼分钟", "exercise minutes")),
    HealthConcept("vo2max", "最大摄氧量", "body_activity", ("vo2max", "vo2 max", "最大摄氧量")),
    HealthConcept("active_energy", "活动能量", "body_activity", ("活动能量", "active energy", "消耗热量")),
    HealthConcept("meal", "饮食", "lifestyle_nutrition", ("饮食", "吃饭", "晚饭", "早餐", "午餐", "meal")),
    HealthConcept("calories", "热量", "lifestyle_nutrition", ("热量", "卡路里", "calorie", "kcal")),
    HealthConcept("carbohydrate", "碳水", "lifestyle_nutrition", ("碳水", "主食", "carb", "carbohydrate")),
    HealthConcept("protein", "蛋白质", "lifestyle_nutrition", ("蛋白质", "蛋白摄入", "protein")),
    HealthConcept("fat_intake", "脂肪摄入", "lifestyle_nutrition", ("脂肪摄入", "油脂", "fat intake")),
    HealthConcept("fiber", "膳食纤维", "lifestyle_nutrition", ("膳食纤维", "纤维", "fiber")),
    HealthConcept("salt", "盐摄入", "lifestyle_nutrition", ("盐", "钠", "高盐", "salt", "sodium")),
    HealthConcept("hydration", "饮水", "lifestyle_nutrition", ("喝水", "饮水", "补水", "水喝", "hydration")),
    HealthConcept("alcohol", "酒精", "lifestyle_nutrition", ("喝酒", "酒精", "饮酒", "alcohol")),
    HealthConcept("caffeine", "咖啡因", "lifestyle_nutrition", ("咖啡", "咖啡因", "茶", "caffeine")),
    HealthConcept("smoking", "吸烟", "lifestyle_nutrition", ("抽烟", "吸烟", "戒烟", "smoking")),
    HealthConcept("tsh", "促甲状腺激素", "endocrine_nutrition", ("tsh", "促甲状腺激素")),
    HealthConcept("t3", "T3", "endocrine_nutrition", ("t3", "三碘甲状腺原氨酸")),
    HealthConcept("t4", "T4", "endocrine_nutrition", ("t4", "甲状腺素")),
    HealthConcept("vitamin_d", "维生素D", "endocrine_nutrition", ("维生素d", "vitamin d", "25羟维生素d", "25-oh-d")),
    HealthConcept("b12", "维生素B12", "endocrine_nutrition", ("b12", "维生素b12", "vitamin b12")),
    HealthConcept("folate", "叶酸", "endocrine_nutrition", ("叶酸", "folate")),
    HealthConcept("anemia", "贫血", "endocrine_nutrition", ("贫血", "anemia")),
    HealthConcept("hemoglobin", "血红蛋白", "endocrine_nutrition", ("血红蛋白", "hemoglobin", "hb")),
    HealthConcept("menstrual_cycle", "月经周期", "pregnancy_reproductive", ("月经", "经期", "姨妈", "月经周期", "menstrual")),
    HealthConcept("pcos", "多囊卵巢综合征", "pregnancy_reproductive", ("多囊", "pcos", "多囊卵巢")),
    HealthConcept("menopause", "围绝经期", "pregnancy_reproductive", ("更年期", "围绝经期", "menopause")),
    HealthConcept("report", "报告", "reports_tasks_devices", ("报告", "体检报告", "化验单", "检查单", "report", "pdf", "图片报告"), source_hint="uploaded_report"),
    HealthConcept("apple_health", "Apple 健康", "reports_tasks_devices", ("apple 健康", "苹果健康", "healthkit", "health kit", "apple health"), source_hint="apple_health"),
    HealthConcept("apple_watch", "Apple Watch", "reports_tasks_devices", ("apple watch", "iwatch", "苹果手表"), source_hint="wearable"),
    HealthConcept("wearable", "可穿戴设备", "reports_tasks_devices", ("手环", "手表", "可穿戴", "硬件", "设备", "wearable")),
    HealthConcept("sync_status", "同步状态", "reports_tasks_devices", ("同步", "接入", "入库", "数据源", "同步状态", "not found"), source_hint="data_source_memory"),
    HealthConcept("medication", "用药", "medication_safety", ("药", "用药", "药物", "处方", "吃药", "medication"), safety_tags=("medication",)),
    HealthConcept("side_effect", "副作用", "medication_safety", ("副作用", "不良反应", "side effect"), safety_tags=("medication",)),
    HealthConcept("interaction", "药物相互作用", "medication_safety", ("相互作用", "一起吃", "冲突", "interaction"), safety_tags=("medication",)),
    HealthConcept("antibiotic", "抗生素", "medication_safety", ("抗生素", "antibiotic"), safety_tags=("medication",)),
    HealthConcept("statin", "他汀", "medication_safety", ("他汀", "statin", "阿托伐他汀", "瑞舒伐他汀"), safety_tags=("medication",)),
    HealthConcept("metformin", "二甲双胍", "medication_safety", ("二甲双胍", "metformin"), safety_tags=("medication",)),
    HealthConcept("anticoagulant", "抗凝药", "medication_safety", ("抗凝", "华法林", "利伐沙班", "阿哌沙班", "warfarin"), safety_tags=("medication",)),
)


_GREETING_RE = re.compile(r"^(你好|您好|在吗|在不在|hello|hi|嗨|哈喽)[。!！?\s]*$", re.IGNORECASE)
_NUMERIC_VALUE_RE = re.compile(r"(?<!\d)(\d{1,4}(?:\.\d+)?)(?:\s*(?:mg/dl|mmol/l|mmhg|umol/l|μmol/l|%|ms|bpm|小时|分|周|天))?", re.IGNORECASE)
_NEGATION_SUFFIX_RE = re.compile(r"(?:没有|没|无|不伴|否认|并无|并未|不是|未出现|no|without)\s*$", re.IGNORECASE)
_NEGATION_SCOPE_RE = re.compile(
    r"(?:没有|没|无|不伴|否认|并无|并未|不是|未出现|no|without)"
    r"(?:(?![，,。！？;；]|但|但是|却|不过|然而|随后|后来|现在有|but|however|currently).){0,24}$",
    re.IGNORECASE,
)
_EMERGENCY_EDUCATION_RE = re.compile(r"(?:什么|哪些|哪种|何种)情况|什么是|怎么判断|如何识别|科普|为什么|如果|假如", re.IGNORECASE)
_CURRENT_SYMPTOM_RE = re.compile(r"现在|此刻|正在|已经|刚刚|刚才|目前|今天", re.IGNORECASE)
_PAST_RESOLVED_RE = re.compile(r"(?:昨天|前天|上周|之前|曾经|刚才).{0,20}(?:好了|缓解|不痛了|恢复了|没事了|现在正常)", re.IGNORECASE)
_CURRENT_PREGNANCY_RE = re.compile(
    r"怀孕|妊娠|孕期|孕妇|孕周|胎儿|胎心|胎动|已经怀上|有孕|"
    r"(?<!备)孕\s*(?:妇|妈|期|周|早期|中期|晚期|\d|[一二三四五六七八九十两])|"
    r"\b(?:nt|nipt|crl)\b|无创(?:dna)?|头臀长",
    re.IGNORECASE,
)
_PREGNANCY_NEGATION_RE = re.compile(r"没有怀孕|没怀孕|未怀孕|并未怀孕|不是孕妇|排除妊娠")
_POSTPARTUM_RE = re.compile(r"产后(?:\s*(\d{1,3})\s*(天|日|周|个月|月))?")
_PEDIATRIC_RE = re.compile(r"婴儿|幼儿|儿童|小孩|宝宝|未成年|青少年")
_AGE_YEARS_RE = re.compile(r"(?<!\d)(\d{1,2})\s*岁")
_SELF_REFERENCE_RE = re.compile(r"(?:^|[，。！？!?；;])\s*(?:我|我自己|本人|自己)")
_RELATION_HISTORY_PATTERNS: dict[str, re.Pattern[str]] = {
    "mother": re.compile(r"我妈|妈妈|母亲"),
    "father": re.compile(r"我爸|爸爸|父亲"),
    "wife": re.compile(r"老婆|妻子|太太|媳妇"),
    "husband": re.compile(r"老公|丈夫"),
    "child": re.compile(r"孩子|儿子|女儿|小孩|宝宝"),
    "friend": re.compile(r"朋友|同事"),
    "relative": re.compile(r"家人|家属|亲戚"),
}

_INTENT_PATTERNS: dict[str, re.Pattern[str]] = {
    "data_source_query": re.compile(r"(同步|数据源|硬件|设备|手表|手环|healthkit|apple\s*health|苹果健康|接入|not\s*found|有.*设备|有没有.*设备)", re.IGNORECASE),
    "report_status_query": re.compile(
        r"(?:报告|图片|pdf|化验单|检查单|入库).{0,30}(?:好了吗|完成(?:了吗)?|状态|进度|失败|还在|多久|到哪)"
        r"|(?:识别|入库).{0,12}(?:好了吗|完成(?:了吗)?|状态|进度|失败|还在|多久|到哪)",
        re.IGNORECASE,
    ),
    "report_summary": re.compile(
        r"(病史摘要|整理病史|总结病史|整理.*报告|报告趋势|按时间.*整理|异常指标.*整理|"
        r"(?:报告|化验单|检查单).{0,10}(?:分析一下|解读|总结|结果)|"
        r"(?:分析|解读|总结).{0,8}(?:报告|化验单|检查单))"
    ),
    "upload_intent": re.compile(
        r"上传(?!的|过的)|拍照(?:上传|采集)?|(?:从)?相册(?:上传|选择)|导入|报告入库",
        re.IGNORECASE,
    ),
    "risk_judgment": re.compile(r"(风险|危险|严重|有什么影响|影响.*吗|影响.*风险|后果|要不要去医院|正常吗|好不好|好吗|怎么样|是否|是不是|偏高|偏低|怎么办|会不会|可能.*吗|大吗)"),
    "trend_analysis": re.compile(r"(趋势|波动|变化|长期|对比|为什么.*变|为什么.*影响|哪几天|一周|一个月)"),
    "conflict_analysis": re.compile(r"(为什么.*(差这么多|不一样|不一致|变化这么大)|不同来源|两个来源|不一致|冲突|差这么多|哪个准|覆盖|同一天.*不同)"),
    "data_freshness_query": re.compile(
        r"(?:最近一次|最新(?:一次)?|多久前|时效|代表今天|还准吗|什么时候测|何时测)"
        r"|(?:今天|现在|当前).{0,14}(?:值|数据|指标|多少|怎么样|高不高|低不低|正常吗|情况)"
        r"|(?:值|数据|指标).{0,10}(?:今天|现在|当前|最新)"
    ),
    "metric_explanation": re.compile(r"(是什么|代表什么|什么意思|怎么看|原理|说明什么|怎么理解|怎么解读)"),
    "symptom_triage": re.compile(r"(头疼|头痛|头晕|眩晕|乏力|疲劳|咳嗽|嗓子疼|喉咙痛|咽痛|鼻塞|流鼻涕|腹痛|肚子疼|胃痛|胃疼|腹泻|拉肚子|便秘|恶心|呕吐|皮疹|过敏|水肿|发烧|发热|失眠|睡不着)"),
    "lifestyle_coaching": re.compile(r"(饮食|吃饭|早餐|午餐|晚饭|喝水|饮水|补水|喝酒|酒精|咖啡|咖啡因|抽烟|戒烟|作息|熬夜|睡眠|睡觉|怎么睡|睡多久|几点睡|入睡|运动|锻炼|步数|热量|卡路里|碳水|主食|蛋白质|膳食纤维|盐|钠)"),
    "mental_health_support": re.compile(r"(焦虑|压力大|紧张|恐慌|心情不好|情绪低落|抑郁|睡不着|失眠)"),
    "medication_safety": re.compile(r"(药|用药|副作用|相互作用|一起吃|能不能吃|能吃吗|剂量|停药|加量|减量|他汀|二甲双胍|抗生素|抗凝)"),
    "pregnancy_risk": re.compile(r"(怀孕|妊娠|备孕|孕|胎儿|nt|nipt|无创|crl|hcg|孕酮|胎心|孕周)", re.IGNORECASE),
    "family_authorization": re.compile(r"(我妈|妈妈|我爸|爸爸|老婆|妻子|太太|老公|丈夫|孩子|朋友|家人|帮.*问|给.*问|不是我)"),
    "family_data_access": re.compile(r"(授权|共享|绑定|家庭模式|能看|能不能看|可以看|查看).{0,12}(家人|家属|我妈|妈妈|我爸|爸爸|老婆|妻子|老公|丈夫|孩子).{0,8}(数据|报告|健康|记录)?"),
    "subject_correction": re.compile(r"(不是我|不是我的|帮.*问|给.*问|是.*问的|问的是|刚才说的是)"),
    "emergency_intent": re.compile(
        r"(胸痛|胸口压榨|喘不上气|无法呼吸|呼吸困难|昏厥|晕倒|意识模糊|意识不清|叫不醒|抽搐|"
        r"半边无力|一侧无力|单侧无力|半边发麻|说话不清|说不清话|口角歪|脸歪|嘴歪|突发剧烈头痛|"
        r"大出血|大量出血|呕血|严重低血糖|严重高血糖|喉咙肿|严重喘鸣|服药过量|药物过量|"
        r"自杀|不想活|想死|活不下去|结束生命|伤害自己)",
        re.IGNORECASE,
    ),
}


def analyze_health_message(
    query: str,
    *,
    active_subject: dict | None = None,
    history: list[dict] | None = None,
    subject_profile: dict | None = None,
) -> dict:
    raw = query or ""
    normalized = _normalize(raw)
    active_subject = active_subject or {}
    subject_profile = subject_profile or {}
    matched = _matched_concepts(normalized)
    concept_keys = [item["key"] for item in matched]
    categories = sorted({item["category"] for item in matched})
    signal_names = {
        name for name, pattern in _INTENT_PATTERNS.items()
        if name != "emergency_intent" and pattern.search(normalized)
    }
    emergency_context = _emergency_context(normalized)
    if emergency_context == "active":
        signal_names.add("emergency_intent")
    elif emergency_context == "resolved_history":
        signal_names.add("urgent_followup")
    subject_traits = _build_subject_traits(
        normalized,
        active_subject=active_subject,
        history=history or [],
        subject_profile=subject_profile,
    )
    numeric_risk = analyze_numeric_health_risk(
        normalized,
        concept_keys=concept_keys,
        context_traits=subject_traits,
    )
    if numeric_risk.get("level") == "emergency":
        signal_names.add("emergency_intent")
        emergency_context = "active"
    elif numeric_risk.get("level") == "high":
        signal_names.add("numeric_high_risk")

    if _GREETING_RE.search(raw.strip()):
        signal_names.add("greeting")
    if active_subject.get("correction_applied"):
        signal_names.add("subject_correction")
    if active_subject.get("type") == "relative":
        signal_names.add("family_authorization")
    if history and not concept_keys:
        recent_health = "\n".join((msg.get("content") or "") for msg in history[-4:])
        if _matched_concepts(_normalize(recent_health)):
            signal_names.add("session_health_context")

    safety_tags = sorted({tag for item in matched for tag in item.get("safety_tags", [])})
    if emergency_context != "active":
        safety_tags = [tag for tag in safety_tags if tag != "emergency"]
    if emergency_context == "resolved_history":
        safety_tags.append("urgent_followup")
    if "emergency_intent" in signal_names or "emergency" in safety_tags:
        safety_tags.append("emergency")
    safety_tags = sorted(set(safety_tags))

    primary_intent = _primary_intent(signal_names, concept_keys, active_subject, normalized)
    depth_hint = _depth_hint(normalized, primary_intent, signal_names, concept_keys)
    safety_profile = _safety_profile(primary_intent, safety_tags, signal_names)
    safety_profile = _merge_numeric_safety(safety_profile, numeric_risk)
    data_requirements = sorted({req for item in matched for req in item.get("data_requirements", [])})
    latent_purpose = _latent_purpose(primary_intent)
    route_hint = _route_hint(primary_intent, safety_profile, depth_hint)
    quality_gates = _quality_gates(primary_intent, categories, active_subject, bool(data_requirements))

    has_health_signal = bool(
        concept_keys
        or signal_names.intersection({
            "risk_judgment",
            "trend_analysis",
            "conflict_analysis",
            "data_freshness_query",
            "symptom_triage",
            "lifestyle_coaching",
            "mental_health_support",
            "medication_safety",
            "pregnancy_risk",
            "emergency_intent",
            "report_summary",
            "upload_intent",
            "report_status_query",
            "data_source_query",
            "session_health_context",
        })
    )

    return {
        "version": NLU_VERSION,
        "normalized_query": normalized,
        "matched_concepts": matched,
        "concept_keys": concept_keys,
        "semantic_categories": categories,
        "intent_signals": {name: name in signal_names for name in sorted(set(_INTENT_PATTERNS) | {"greeting", "session_health_context", "urgent_followup", "numeric_high_risk"})},
        "primary_intent": primary_intent,
        "depth_hint": depth_hint,
        "latent_purpose": latent_purpose,
        "route_hint": route_hint,
        "safety_profile": safety_profile,
        "data_requirements": data_requirements,
        "quality_gates": quality_gates,
        "macro_categories": _macro_categories(primary_intent, categories, active_subject, signal_names),
        "has_health_signal": has_health_signal,
        "numeric_values_present": bool(_NUMERIC_VALUE_RE.search(normalized)),
        "numeric_risk": numeric_risk,
        "subject_traits": subject_traits,
        "emergency_context": emergency_context,
    }


def _normalize(text: str) -> str:
    normalized = (text or "").replace("\u3000", " ").replace("μ", "u").lower()
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _build_subject_traits(
    normalized: str,
    *,
    active_subject: dict,
    history: list[dict],
    subject_profile: dict,
) -> dict:
    current_state = _pregnancy_state(normalized)
    pregnancy_source = "current_message" if current_state is not None else None
    if current_state is None:
        history_state = _history_same_subject_pregnancy_state(history, active_subject)
        if history_state is not None:
            current_state = history_state
            pregnancy_source = "recent_same_subject"
    current_pregnancy = current_state is True

    age_years = _age_years(normalized)
    if age_years is None and active_subject.get("type") == "self":
        profile_age = subject_profile.get("age")
        if isinstance(profile_age, int) and 0 <= profile_age <= 120:
            age_years = profile_age

    pediatric = bool(_PEDIATRIC_RE.search(normalized)) or (
        isinstance(age_years, int) and age_years < 18
    )
    possible_pediatric = bool(
        not pediatric
        and active_subject.get("type") == "relative"
        and active_subject.get("relation") == "child"
    )
    return {
        "pregnancy_or_postpartum": current_pregnancy,
        "pregnancy_context_source": pregnancy_source,
        "pediatric": pediatric,
        "possible_pediatric": possible_pediatric,
        "age_years": age_years,
    }


def _has_pregnancy_or_recent_postpartum_context(text: str) -> bool:
    return _pregnancy_state(text) is True


def _pregnancy_state(text: str) -> bool | None:
    if _PREGNANCY_NEGATION_RE.search(text):
        return False
    if _CURRENT_PREGNANCY_RE.search(text):
        return True
    postpartum = _POSTPARTUM_RE.search(text)
    if not postpartum:
        return None
    value_text, unit = postpartum.groups()
    if not value_text:
        return True
    value = int(value_text)
    if unit in {"天", "日"}:
        return value <= 42
    if unit == "周":
        return value <= 6
    return value <= 1


def _history_same_subject_pregnancy_state(history: list[dict], active_subject: dict) -> bool | None:
    recent = [
        _normalize(str(item.get("content") or ""))
        for item in history[-10:]
        if item.get("role") == "user" and item.get("content")
    ]
    if not recent:
        return None

    if active_subject.get("type") == "relative":
        relation = str(active_subject.get("relation") or "")
        target_pattern = _RELATION_HISTORY_PATTERNS.get(relation)
        if not target_pattern:
            return None
        anchor_index = None
        anchor_relation = None
        for index in range(len(recent) - 1, -1, -1):
            for candidate_relation, pattern in _RELATION_HISTORY_PATTERNS.items():
                if pattern.search(recent[index]):
                    anchor_index = index
                    anchor_relation = candidate_relation
                    break
            if anchor_index is not None:
                break
        if anchor_index is None or anchor_relation != relation:
            return None
        for text in reversed(recent[anchor_index:]):
            state = _pregnancy_state(text)
            if state is not None:
                return state
        return None

    if active_subject.get("type") != "self" or active_subject.get("correction_applied"):
        return None
    for text in reversed(recent):
        state = _pregnancy_state(text)
        if state is None:
            continue
        if any(pattern.search(text) for pattern in _RELATION_HISTORY_PATTERNS.values()):
            continue
        if _SELF_REFERENCE_RE.search(text):
            return state
    return None


def _age_years(text: str) -> int | None:
    match = _AGE_YEARS_RE.search(text)
    if not match:
        return None
    value = int(match.group(1))
    return value if 0 <= value <= 120 else None


def _matched_concepts(normalized_text: str) -> list[dict]:
    matches: list[dict] = []
    for concept in CONCEPT_CATALOG:
        matched_aliases = [
            alias for alias in concept.aliases
            if _contains_alias(normalized_text, alias) and not _alias_only_negated(normalized_text, alias)
        ]
        if not matched_aliases:
            continue
        matches.append({
            "key": concept.key,
            "display": concept.display,
            "category": concept.category,
            "matched_aliases": sorted(set(matched_aliases), key=len, reverse=True)[:4],
            "source_hint": concept.source_hint,
            "data_requirements": list(concept.data_requirements),
            "safety_tags": list(concept.safety_tags),
        })
    return matches


def _contains_alias(text: str, alias: str) -> bool:
    alias_norm = _normalize(alias)
    if not alias_norm:
        return False
    if re.fullmatch(r"[a-z0-9][a-z0-9+\-.()]{0,5}", alias_norm):
        pattern = re.compile(rf"(?<![a-z0-9]){re.escape(alias_norm)}(?![a-z0-9])", re.IGNORECASE)
        return bool(pattern.search(text))
    compact_text = re.sub(r"\s+", "", text)
    compact_alias = re.sub(r"\s+", "", alias_norm)
    return compact_alias in compact_text


def _alias_only_negated(text: str, alias: str) -> bool:
    alias_norm = _normalize(alias)
    compact_text = re.sub(r"\s+", "", text)
    compact_alias = re.sub(r"\s+", "", alias_norm)
    positions = [match.start() for match in re.finditer(re.escape(compact_alias), compact_text, re.IGNORECASE)]
    if not positions:
        return False
    for position in positions:
        if not _match_is_negated(compact_text, position):
            return False
    return True


def _emergency_context(normalized: str) -> str:
    pattern = _INTENT_PATTERNS["emergency_intent"]
    positive_matches = []
    for match in pattern.finditer(normalized):
        if not _match_is_negated(normalized, match.start()):
            positive_matches.append(match)
    if not positive_matches:
        return "none"
    if _PAST_RESOLVED_RE.search(normalized):
        return "resolved_history"
    if _EMERGENCY_EDUCATION_RE.search(normalized) and not _CURRENT_SYMPTOM_RE.search(normalized):
        return "educational"
    return "active"


def _match_is_negated(text: str, start: int) -> bool:
    prefix = text[max(0, start - 32):start].replace("是不是", "")
    return bool(_NEGATION_SUFFIX_RE.search(prefix) or _NEGATION_SCOPE_RE.search(prefix))


def _primary_intent(signal_names: set[str], concept_keys: list[str], active_subject: dict, normalized: str) -> str:
    if "greeting" in signal_names:
        return "greeting"
    if "emergency_intent" in signal_names:
        return "emergency_triage"
    if "urgent_followup" in signal_names:
        return "risk_judgment"
    if "report_status_query" in signal_names:
        return "report_status_query"
    if "data_source_query" in signal_names and "report" not in concept_keys:
        return "data_source_query"
    if "family_data_access" in signal_names:
        return "family_authorization"
    if "subject_correction" in signal_names and _is_correction_only(signal_names, normalized):
        return "subject_correction"
    if "pregnancy_risk" in signal_names or any(key in concept_keys for key in ("pregnancy", "nt", "nipt", "crl", "hcg", "progesterone", "fetal")):
        return "pregnancy_risk"
    if "medication_safety" in signal_names or any(key in concept_keys for key in ("medication", "interaction", "side_effect", "statin", "metformin", "anticoagulant", "insulin")):
        return "medication_safety"
    if "mental_health_support" in signal_names or any(key in concept_keys for key in ("anxiety", "low_mood")):
        return "mental_health_support"
    if "conflict_analysis" in signal_names:
        return "conflict_analysis"
    if "numeric_high_risk" in signal_names:
        return "risk_judgment"
    if "symptom_triage" in signal_names or "symptoms_common" in _categories_for_keys(concept_keys):
        return "symptom_triage"
    if "data_freshness_query" in signal_names:
        return "data_freshness_query"
    if "report_summary" in signal_names and "risk_judgment" not in signal_names:
        return "report_summary"
    if "trend_analysis" in signal_names:
        return "trend_analysis"
    if "lifestyle_coaching" in signal_names or "lifestyle_nutrition" in _categories_for_keys(concept_keys):
        return "lifestyle_coaching"
    if "metric_explanation" in signal_names and not _explicit_risk_request(normalized):
        return "metric_explanation"
    if "risk_judgment" in signal_names:
        return "risk_judgment"
    if "report_summary" in signal_names:
        return "report_summary"
    if "upload_intent" in signal_names:
        return "upload_intent"
    if "metric_explanation" in signal_names:
        return "metric_explanation"
    if concept_keys or "session_health_context" in signal_names:
        return "medical_question"
    return "general_chat"


def _is_correction_only(signal_names: set[str], normalized: str) -> bool:
    clinical_signals = {
        "risk_judgment",
        "trend_analysis",
        "conflict_analysis",
        "data_freshness_query",
        "symptom_triage",
        "lifestyle_coaching",
        "mental_health_support",
        "medication_safety",
        "report_summary",
        "upload_intent",
        "report_status_query",
        "data_source_query",
        "emergency_intent",
    }
    if signal_names.intersection(clinical_signals):
        return False
    if _NUMERIC_VALUE_RE.search(normalized) and re.search(r"风险|正常|怎么办|严重|影响", normalized):
        return False
    return True


def _explicit_risk_request(normalized: str) -> bool:
    return bool(re.search(r"(风险|危险|严重|要不要去医院|正常吗|好不好|好吗|怎么样|是否|是不是|怎么办|会不会|可能.*吗|大吗|有什么影响|影响.*吗|后果)", normalized))


def _depth_hint(normalized: str, primary_intent: str, signal_names: set[str], concept_keys: list[str]) -> str:
    if primary_intent in {"greeting", "data_source_query", "report_status_query", "subject_correction"}:
        return "quick"
    if primary_intent == "emergency_triage":
        return "quick"
    if primary_intent in {"report_summary", "conflict_analysis", "trend_analysis"}:
        return "deep"
    if primary_intent in {"pregnancy_risk", "medication_safety", "mental_health_support", "symptom_triage", "risk_judgment"}:
        return "deep" if _NUMERIC_VALUE_RE.search(normalized) or len(concept_keys) >= 2 else "standard"
    if re.search(r"(详细|深入|全面|依据|证据|机制|原理|长期|完整|病史|整理)", normalized):
        return "deep"
    if "metric_explanation" in signal_names:
        return "standard"
    return "standard"


def _safety_profile(primary_intent: str, safety_tags: list[str], signal_names: set[str]) -> dict:
    level = "low"
    must_include: list[str] = []
    forbidden: list[str] = []
    tags = list(safety_tags)
    if primary_intent == "emergency_triage" or "emergency" in tags:
        level = "emergency"
        must_include.extend([
            "先给立即就医/急救建议",
            "只做紧急分流，不给居家观察替代方案",
        ])
        forbidden.extend(["不能淡化急症风险", "不能要求用户先上传报告再处理急症"])
    elif primary_intent == "medication_safety":
        level = "high"
        must_include.extend(["说明不能自行调整剂量或停药", "提示核对处方、肝肾功能和禁忌"])
        forbidden.extend(["不能给出替代医生处方的具体加减量指令"])
    elif primary_intent == "pregnancy_risk":
        level = "medium"
        must_include.extend(["结合孕周/报告数值解释", "提示产科医生或报告结论优先"])
        forbidden.extend(["不能用登录用户本人的指标判断孕妇或胎儿"])
    elif primary_intent == "mental_health_support":
        level = "medium"
        must_include.extend(["先回应情绪和睡眠压力", "筛查自伤念头、惊恐发作或功能受损等升级信号"])
        forbidden.extend(["不能把心理危机当作普通压力建议处理"])
    elif primary_intent == "symptom_triage":
        level = "medium"
        must_include.extend(["先筛急症红旗信号", "给出观察窗口和下一步处理"])
        forbidden.extend(["不能把胸痛、呼吸困难、昏厥、卒中信号当普通症状处理"])
    elif primary_intent in {"risk_judgment", "conflict_analysis"}:
        level = "medium"
        must_include.extend(["说明来源、时间和不确定边界", "给出下一步可执行动作"])
    if "urgent_followup" in tags:
        level = "high"
        must_include.extend(["说明既往急症信号即使缓解也需要尽快医疗评估", "询问是否再次出现或仍有残余症状"])
        forbidden.extend(["不能因为症状已经缓解就判定没有风险"])
    if "glucose_safety" in tags:
        level = "high" if level == "medium" else level
        must_include.append("低血糖/高血糖严重症状需及时处理")
    return {
        "level": level,
        "tags": sorted(set(tags)),
        "must_include": sorted(set(must_include)),
        "forbidden": sorted(set(forbidden)),
    }


def _merge_numeric_safety(safety_profile: dict, numeric_risk: dict) -> dict:
    order = {"low": 0, "medium": 1, "high": 2, "emergency": 3}
    current = str(safety_profile.get("level") or "low")
    numeric_level = str(numeric_risk.get("level") or "low")
    merged = dict(safety_profile)
    merged["level"] = numeric_level if order.get(numeric_level, 0) > order.get(current, 0) else current
    merged["tags"] = sorted(set((merged.get("tags") or []) + [f"numeric:{reason}" for reason in numeric_risk.get("reason_codes") or []]))
    merged["must_include"] = sorted(set((merged.get("must_include") or []) + (numeric_risk.get("must_include") or [])))
    merged["forbidden"] = sorted(set((merged.get("forbidden") or []) + (numeric_risk.get("forbidden") or [])))
    return merged


def _latent_purpose(primary_intent: str) -> str:
    mapping = {
        "greeting": "resume_conversation",
        "data_source_query": "verify_data_availability",
        "report_status_query": "check_upload_processing_status",
        "subject_correction": "repair_subject_boundary",
        "family_authorization": "separate_relative_case",
        "pregnancy_risk": "risk_judgment",
        "medication_safety": "medication_safety_check",
        "mental_health_support": "mental_health_support",
        "symptom_triage": "common_symptom_triage",
        "lifestyle_coaching": "behavior_change_coaching",
        "conflict_analysis": "explain_conflicting_measurements",
        "data_freshness_query": "verify_current_status",
        "risk_judgment": "risk_judgment",
        "trend_analysis": "personalized_health_analysis",
        "report_summary": "organize_health_record",
        "upload_intent": "report_upload_workflow",
        "metric_explanation": "metric_education",
        "emergency_triage": "urgent_safety_triage",
        "medical_question": "personalized_health_analysis",
    }
    return mapping.get(primary_intent, "clarify_context")


def _route_hint(primary_intent: str, safety_profile: dict, depth_hint: str) -> str:
    if safety_profile.get("level") == "emergency":
        return "emergency_template"
    if primary_intent in {"greeting", "data_source_query", "report_status_query", "subject_correction"}:
        return "deterministic_fast_path"
    if depth_hint == "deep":
        return "deep_llm"
    return "standard_llm"


def _quality_gates(
    primary_intent: str,
    categories: list[str],
    active_subject: dict,
    has_data_requirements: bool,
) -> list[str]:
    gates = [
        "先按归一化医学概念理解用户问题，不按缩写字面猜测。",
        "回答第一段直接回应用户问题，不先泛泛询问背景。",
    ]
    if active_subject.get("type") == "relative":
        gates.append("当前主体不是本人，不能使用登录用户本人的健康数据做结论。")
    if has_data_requirements:
        gates.append("需要指标时优先使用已入库的来源/时间；没有就明确暂无记录或待同步。")
    if primary_intent in {"data_freshness_query", "conflict_analysis"}:
        gates.append("必须解释数据来源、测量时间、时效性和可能冲突。")
    if primary_intent in {"pregnancy_risk", "medication_safety", "mental_health_support", "symptom_triage", "emergency_triage"}:
        gates.append("必须明确安全边界，不能给超过健康管理范围的确定诊断或处方。")
    if primary_intent == "symptom_triage":
        gates.append("普通症状先筛红旗信号，再给观察窗口、可执行处理和何时就医。")
    if primary_intent == "lifestyle_coaching":
        gates.append("生活方式建议要落到可执行动作，并结合已有睡眠、活动、血糖或指标时效。")
    if "reports_tasks_devices" in categories:
        gates.append("报告/设备问题先回答任务状态或数据源状态，再进入医学解释。")
    return gates


def _macro_categories(
    primary_intent: str,
    categories: list[str],
    active_subject: dict,
    signal_names: Iterable[str],
) -> list[str]:
    macros = {"medical_semantic_normalization", "intent_routing"}
    if active_subject.get("type") != "self" or "family_authorization" in signal_names:
        macros.add("subject_boundary")
    if "data_source_query" in signal_names or "reports_tasks_devices" in categories:
        macros.add("data_source_memory")
    if primary_intent == "data_freshness_query":
        macros.add("data_freshness")
    if primary_intent == "conflict_analysis":
        macros.add("data_conflict")
    if primary_intent == "report_status_query":
        macros.add("report_task_state")
    if primary_intent in {"emergency_triage", "pregnancy_risk", "medication_safety", "mental_health_support", "symptom_triage", "risk_judgment"}:
        macros.add("safety_boundary")
    if primary_intent == "symptom_triage" or "symptoms_common" in categories:
        macros.add("symptom_triage")
    if primary_intent == "lifestyle_coaching" or "lifestyle_nutrition" in categories:
        macros.add("lifestyle_behavior")
    if primary_intent == "mental_health_support" or "mental_wellbeing" in categories:
        macros.add("mental_health_boundary")
    if primary_intent in {"risk_judgment", "trend_analysis", "report_summary", "pregnancy_risk", "medication_safety", "mental_health_support", "symptom_triage", "conflict_analysis"}:
        macros.add("evidence_depth")
    if "session_health_context" in signal_names:
        macros.add("session_memory")
    return sorted(macros)


def _categories_for_keys(concept_keys: list[str]) -> set[str]:
    if not concept_keys:
        return set()
    wanted = set(concept_keys)
    return {concept.category for concept in CONCEPT_CATALOG if concept.key in wanted}
