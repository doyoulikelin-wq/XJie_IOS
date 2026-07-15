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
        ("报告图片识别到哪了", {"report"}, "report_status_query"),
        ("帮我整理病史摘要和报告异常", {"report"}, "report_summary"),
        ("报告分析一下", {"report"}, "report_summary"),
        ("请分析报告结果", {"report"}, "report_summary"),
        ("我上传的报告里尿酸是多少", {"report", "uric_acid"}, "medical_question"),
        ("我上传的图片里血压是多少", {"blood_pressure"}, "medical_question"),
        ("怎么上传 PDF 报告", {"report"}, "upload_intent"),
        ("今天晚上该怎么睡", set(), "lifestyle_coaching"),
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

    assert result["primary_intent"] == "medical_question"
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


def test_current_time_words_do_not_override_common_symptom_triage():
    for message in ("今天还是轻微头疼", "现在有点腹痛", "当前头晕站不稳"):
        result = analyze_health_message(message)
        assert result["primary_intent"] == "symptom_triage", message


def test_numeric_high_risk_precedes_data_freshness_wording():
    result = analyze_health_message("我现在血糖 15 mmol/L，没有恶心呕吐")

    assert result["primary_intent"] == "risk_judgment"
    assert result["safety_profile"]["level"] == "high"
    constraints = "\n".join(
        result["safety_profile"]["must_include"] + result["quality_gates"]
    )
    assert "来源、时间和不确定边界" in constraints
    assert "给出下一步可执行动作" in constraints
    assert "不能给超过健康管理范围的确定诊断或处方" in constraints


def test_health_state_analysis_is_not_misrouted_as_report_task_status():
    result = analyze_health_message(
        "请结合我的睡眠、HRV、血压和最近症状，分层分析过去一个月恢复状态变化，并给出今天、未来一周和复查时点的建议。"
    )

    assert result["primary_intent"] == "trend_analysis"
    assert result["intent_signals"]["report_status_query"] is False
    assert result["intent_signals"]["data_freshness_query"] is False


def test_compound_sleep_rhinitis_scoliosis_question_routes_to_causal_assessment():
    result = analyze_health_message("我的失眠抑郁是不是跟我鼻炎、脊柱侧弯导致缺氧有关系")

    assert {"insomnia", "low_mood", "rhinitis", "scoliosis", "hypoxia"}.issubset(
        set(result["concept_keys"])
    )
    assert result["primary_intent"] == "causal_assessment"
    assert result["depth_hint"] == "deep"
    assert result["safety_profile"]["level"] == "medium"
    assert result["compound_assessment"]["required"] is True
    assert result["compound_assessment"]["coverage_rule"] == "address_every_concept"
    assert result["compound_assessment"]["hypoxia_boundary_required"] is True
    evaluations = "\n".join(result["compound_assessment"]["evaluation_requirements"])
    for concept in result["compound_assessment"]["concepts"]:
        assert concept["display"] in evaluations
    assert "耳鼻喉评估" in evaluations
    assert "规范血氧测量" in evaluations
    assert "肺功能" in evaluations
    assert "causal_reasoning" in result["macro_categories"]
    assert "evidence_relevance" in result["macro_categories"]
    assert any("每个因素" in gate for gate in result["quality_gates"])


def test_causal_assessment_covers_common_colloquial_sleep_wording():
    result = analyze_health_message("鼻炎会导致我睡不好吗")

    assert {"rhinitis", "insomnia"}.issubset(set(result["concept_keys"]))
    assert result["primary_intent"] == "causal_assessment"
    assert result["compound_assessment"]["hypoxia_boundary_required"] is False
    constraints = "\n".join(
        result["safety_profile"]["must_include"] + result["safety_profile"]["forbidden"]
    )
    assert "缺氧" not in constraints


def test_causal_assessment_covers_scoliosis_and_nocturnal_hypoxia():
    result = analyze_health_message("脊柱侧弯是不是造成夜间低氧")

    assert {"scoliosis", "hypoxia"}.issubset(set(result["concept_keys"]))
    assert result["primary_intent"] == "causal_assessment"


def test_generic_causal_assessment_uses_only_matched_sleep_and_glucose_requirements():
    result = analyze_health_message("失眠会导致血糖升高吗")

    assert {"insomnia", "glucose"}.issubset(set(result["concept_keys"]))
    assert result["primary_intent"] == "causal_assessment"
    constraints = "\n".join(
        result["safety_profile"]["must_include"]
        + result["safety_profile"]["forbidden"]
        + result["quality_gates"]
    )
    assert "失眠" in constraints
    assert "睡眠时长" in constraints
    assert "血糖" in constraints
    assert "测量时间" in constraints
    assert all(term not in constraints for term in ("缺氧", "鼻炎", "脊柱侧弯", "肺功能", "耳鼻喉"))
    assert result["compound_assessment"]["hypoxia_boundary_required"] is False


def test_hypoxia_causal_requirements_do_not_invent_unmatched_rhinitis_or_scoliosis():
    result = analyze_health_message("打鼾会导致夜间低氧吗")

    assert {"sleep_disordered_breathing", "hypoxia"}.issubset(set(result["concept_keys"]))
    assert result["primary_intent"] == "causal_assessment"
    constraints = "\n".join(
        result["safety_profile"]["must_include"]
        + result["safety_profile"]["forbidden"]
        + result["compound_assessment"]["evaluation_requirements"]
    )
    assert "规范睡眠监测" in constraints
    assert "规范血氧测量" in constraints
    assert all(term not in constraints for term in ("鼻炎", "脊柱侧弯", "肺功能", "耳鼻喉"))


def test_generic_blood_pressure_heart_rate_causal_question_has_concept_limited_evaluations():
    result = analyze_health_message("血压和心率有关系吗")

    assert {"blood_pressure", "heart_rate"}.issubset(set(result["concept_keys"]))
    assert result["primary_intent"] == "causal_assessment"
    evaluations = result["compound_assessment"]["evaluation_requirements"]
    assert evaluations
    evaluation_text = "\n".join(evaluations)
    assert "血压" in evaluation_text
    assert "心率" in evaluation_text
    assert "客观记录" in evaluation_text
    assert "测量时间" in evaluation_text
    assert all(term not in evaluation_text for term in ("缺氧", "鼻炎", "脊柱侧弯", "肺功能"))


def test_single_rhinitis_management_question_remains_symptom_triage():
    result = analyze_health_message("鼻炎怎么办")

    assert result["primary_intent"] == "symptom_triage"


def test_current_cyanosis_overrides_causal_route_with_emergency_triage():
    result = analyze_health_message("我现在嘴唇发紫，是不是鼻炎导致缺氧")

    assert result["primary_intent"] == "emergency_triage"
    assert result["safety_profile"]["level"] == "emergency"
