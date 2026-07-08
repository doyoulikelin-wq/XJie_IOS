import pytest

from app.services.health_nlu import analyze_health_message


@pytest.mark.parametrize(
    ("query", "expected_concepts", "expected_intent"),
    [
        ("帮我分析一下 HRV 和 RMSSD 最近一周变化", {"hrv"}, "trend_analysis"),
        ("我的心率变异性为什么变低了", {"hrv"}, "trend_analysis"),
        ("我老婆 NT 2.8，CRL 58，正常吗", {"nt", "crl"}, "pregnancy_risk"),
        ("NIPT 和颈项透明层分别代表什么", {"nipt", "nt"}, "pregnancy_risk"),
        ("TIR 93.8% 说明血糖控制怎么样", {"tir", "glucose"}, "risk_judgment"),
        ("糖化血红蛋白 HbA1c 5.5 怎么看", {"hba1c"}, "metric_explanation"),
        ("肌酐和 eGFR 都正常还能说肾功能好吗", {"creatinine", "egfr"}, "risk_judgment"),
        ("胱抑素C 0.81 和尿酸 419 有什么关系", {"cystatin_c", "uric_acid"}, "medical_question"),
        ("hs-CRP 和白细胞升高是不是炎症", {"hscrp", "crp", "wbc"}, "risk_judgment"),
        ("NLR 偏高说明什么", {"nlr"}, "metric_explanation"),
        ("ALT AST 都高，脂肪肝风险大吗", {"alt", "ast", "fatty_liver"}, "risk_judgment"),
        ("LDL 和 ApoB 哪个更重要", {"ldl_c", "apob"}, "medical_question"),
        ("我的睡眠和深睡为什么影响恢复评分", {"sleep", "deep_sleep", "recovery"}, "trend_analysis"),
        ("Apple 健康同步 not found 是怎么回事", {"apple_health", "sync_status"}, "data_source_query"),
        ("我有血糖设备吗", {"glucose", "cgm"}, "data_source_query"),
        ("我的报告分析好了吗", {"report"}, "report_status_query"),
        ("帮我整理病史摘要和报告异常", {"report"}, "report_summary"),
        ("二甲双胍和他汀能一起吃吗", {"metformin", "statin", "interaction"}, "medication_safety"),
        ("我的血压为什么两个来源差这么多", {"blood_pressure"}, "conflict_analysis"),
        ("我今天血压怎么样，最近一次是什么时候", {"blood_pressure"}, "data_freshness_query"),
        ("尿酸 419.7 对我风险大吗", {"uric_acid"}, "risk_judgment"),
        ("体重、BMI、腰围一起怎么看", {"weight", "bmi", "waist"}, "metric_explanation"),
        ("TSH 和 T4 异常说明什么", {"tsh", "t4"}, "metric_explanation"),
        ("维生素D和B12都低怎么补", {"vitamin_d", "b12"}, "medical_question"),
        ("我头疼还恶心怎么办", {"headache", "nausea_vomiting"}, "symptom_triage"),
        ("胃痛腹泻一天了怎么办", {"stomach_pain", "diarrhea"}, "symptom_triage"),
        ("我最近焦虑睡不着，会不会影响恢复", {"anxiety", "insomnia", "recovery"}, "mental_health_support"),
        ("怎么调整晚饭碳水、咖啡和运动", {"meal", "carbohydrate", "caffeine"}, "lifestyle_coaching"),
    ],
)
def test_health_nlu_concept_and_intent_matrix(query, expected_concepts, expected_intent):
    result = analyze_health_message(query)

    assert expected_concepts.issubset(set(result["concept_keys"]))
    assert result["primary_intent"] == expected_intent
    assert result["has_health_signal"] is True
    assert "medical_semantic_normalization" in result["macro_categories"]
    assert "intent_routing" in result["macro_categories"]


def test_family_relative_case_sets_subject_boundary_without_using_self_data():
    result = analyze_health_message(
        "看看我妈的血糖",
        active_subject={"type": "relative", "relation": "mother", "display": "母亲"},
    )

    assert result["primary_intent"] == "family_authorization"
    assert "glucose" in result["concept_keys"]
    assert "subject_boundary" in result["macro_categories"]
    assert "当前主体不是本人，不能使用登录用户本人的健康数据做结论。" in result["quality_gates"]


def test_subject_correction_takes_priority_over_pregnancy_shortcut():
    result = analyze_health_message(
        "nt 是帮我老婆问的",
        active_subject={"type": "relative", "relation": "wife", "display": "妻子", "correction_applied": True},
    )

    assert result["primary_intent"] == "subject_correction"
    assert "nt" in result["concept_keys"]
    assert result["route_hint"] == "deterministic_fast_path"


def test_emergency_symptom_routes_to_emergency_profile():
    result = analyze_health_message("胸痛喘不上气还冒冷汗怎么办")

    assert result["primary_intent"] == "emergency_triage"
    assert result["safety_profile"]["level"] == "emergency"
    assert result["route_hint"] == "emergency_template"
    assert "safety_boundary" in result["macro_categories"]
    assert "不能淡化急症风险" in result["safety_profile"]["forbidden"]


def test_medication_safety_sets_high_safety_boundary():
    result = analyze_health_message("阿托伐他汀和抗生素一起吃会不会冲突")

    assert result["primary_intent"] == "medication_safety"
    assert result["safety_profile"]["level"] == "high"
    assert "medication" in result["safety_profile"]["tags"]
    assert "不能给出替代医生处方的具体加减量指令" in result["safety_profile"]["forbidden"]
