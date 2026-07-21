from app.services.health_nlu import analyze_health_message
from app.services.numeric_health_risk import analyze_numeric_health_risk


def test_severe_blood_pressure_without_red_flags_is_high_not_emergency():
    risk = analyze_numeric_health_risk("我的血压 190/125 mmHg，没有胸痛或呼吸困难", concept_keys=["blood_pressure"])
    nlu = analyze_health_message("我的血压 190/125 mmHg，没有胸痛或呼吸困难")

    assert risk["level"] == "high"
    assert "bp:severe_range" in risk["reason_codes"]
    assert nlu["safety_profile"]["level"] == "high"
    assert nlu["primary_intent"] == "risk_judgment"
    assert nlu["emergency_context"] == "none"


def test_severe_blood_pressure_with_neurologic_symptom_is_emergency():
    nlu = analyze_health_message("我现在血压 190/125 mmHg，而且一侧无力说不清话")

    assert nlu["safety_profile"]["level"] == "emergency"
    assert nlu["primary_intent"] == "emergency_triage"


def test_level_two_hypoglycemia_is_high_risk_and_preserves_unit_conversion():
    risk = analyze_numeric_health_risk("血糖 2.8 mmol/L 怎么办", concept_keys=["glucose"])
    nlu = analyze_health_message("血糖 2.8 mmol/L 怎么办")

    assert risk["level"] == "high"
    assert risk["observations"][0]["normalized_mg_dl"] == 50.4
    assert "glucose:level_2_hypoglycemia" in risk["reason_codes"]
    assert nlu["safety_profile"]["level"] == "high"


def test_high_glucose_with_dka_symptom_combination_is_emergency():
    nlu = analyze_health_message("我血糖 20 mmol/L，还恶心呕吐、腹痛、呼吸又深又快")

    assert nlu["numeric_risk"]["level"] == "emergency"
    assert "glucose:dka_symptom_combination" in nlu["numeric_risk"]["reason_codes"]
    assert nlu["primary_intent"] == "emergency_triage"


def test_hrv_value_is_not_misclassified_as_glucose_or_blood_pressure_risk():
    nlu = analyze_health_message("我今天 HRV 43 ms，帮我分析一下")

    assert nlu["numeric_risk"]["level"] == "low"
    assert nlu["numeric_risk"]["observations"] == []


def test_negated_dka_symptoms_do_not_escalate_high_glucose_to_emergency():
    result = analyze_numeric_health_risk(
        "血糖 15 mmol/L，没有恶心呕吐，也没有腹痛，呼吸正常",
        concept_keys=["glucose"],
    )

    assert result["level"] == "high"
    assert "glucose:ketone_check_range" in result["reason_codes"]
    assert "glucose:dka_symptom_combination" not in result["reason_codes"]


def test_current_vomiting_after_prior_negation_still_escalates():
    result = analyze_numeric_health_risk(
        "血糖 15 mmol/L，之前没有呕吐，但现在开始呕吐",
        concept_keys=["glucose"],
    )

    assert result["level"] == "emergency"
    assert "glucose:dka_symptom_combination" in result["reason_codes"]


def test_single_severe_systolic_value_is_not_ignored():
    result = analyze_health_message("血压 190 怎么办")

    assert result["numeric_risk"]["level"] == "high"
    assert result["numeric_risk"]["observations"][0]["systolic"] == 190
    assert result["numeric_risk"]["observations"][0]["diastolic"] == 0


def test_unitless_glucose_uses_conservative_ambiguity_boundary():
    dangerous = analyze_health_message("血糖 20 怎么办")
    symptomatic = analyze_health_message("血糖 20，后来开始呕吐")
    needs_unit = analyze_health_message("血糖 5.5 正常吗")

    assert dangerous["numeric_risk"]["level"] == "high"
    assert "glucose:unit_ambiguous_dangerous" in dangerous["numeric_risk"]["reason_codes"]
    assert symptomatic["numeric_risk"]["level"] == "emergency"
    assert "glucose:ambiguous_unit_with_symptoms" in symptomatic["numeric_risk"]["reason_codes"]
    assert needs_unit["numeric_risk"]["level"] == "low"
    assert "glucose:unit_missing" in needs_unit["numeric_risk"]["reason_codes"]


def test_pregnancy_uses_160_over_110_severe_threshold_without_adult_fallback():
    pregnant = analyze_health_message("我怀孕 32 周，血压 160/110 mmHg，没有头痛或视物模糊")
    nonpregnant = analyze_health_message("我血压 160/110 mmHg，没有头痛或视物模糊")

    assert pregnant["numeric_risk"]["level"] == "high"
    assert "bp:pregnancy_severe" in pregnant["numeric_risk"]["reason_codes"]
    assert "bp:severe_range" not in pregnant["numeric_risk"]["reason_codes"]
    assert nonpregnant["numeric_risk"]["level"] == "medium"
    assert "bp:pregnancy_severe" not in nonpregnant["numeric_risk"]["reason_codes"]


def test_pregnancy_severe_pressure_with_actual_warning_symptom_is_emergency():
    nlu = analyze_health_message("孕 34 周，血压 165/112 mmHg，现在剧烈头痛，但没有上腹痛")
    observation = nlu["numeric_risk"]["observations"][0]

    assert nlu["numeric_risk"]["level"] == "emergency"
    assert "bp:pregnancy_severe_with_symptoms" in nlu["numeric_risk"]["reason_codes"]
    assert observation["active_symptoms"] == ["剧烈头痛"]
    assert nlu["primary_intent"] == "emergency_triage"


def test_pregnancy_context_continues_only_for_same_relative_subject():
    history = [{"role": "user", "content": "我老婆怀孕 32 周"}]
    wife = analyze_health_message(
        "她现在血压 165/112 mmHg",
        active_subject={"type": "relative", "relation": "wife", "source": "recent_conversation"},
        history=history,
    )
    self_case = analyze_health_message(
        "说回我，我现在血压 165/112 mmHg",
        active_subject={"type": "self", "relation": "self", "correction_applied": True},
        history=history,
    )

    assert wife["subject_traits"]["pregnancy_context_source"] == "recent_same_subject"
    assert "bp:pregnancy_severe" in wife["numeric_risk"]["reason_codes"]
    assert self_case["subject_traits"]["pregnancy_or_postpartum"] is False
    assert "bp:pregnancy_severe" not in self_case["numeric_risk"]["reason_codes"]


def test_latest_same_subject_pregnancy_correction_overrides_older_history():
    history = [
        {"role": "user", "content": "我老婆之前以为怀孕 8 周"},
        {"role": "user", "content": "我老婆复查后确认没有怀孕"},
    ]
    nlu = analyze_health_message(
        "她现在血压 165/110 mmHg",
        active_subject={"type": "relative", "relation": "wife", "source": "recent_conversation"},
        history=history,
    )

    assert nlu["subject_traits"]["pregnancy_or_postpartum"] is False
    assert nlu["subject_traits"]["pregnancy_context_source"] == "recent_same_subject"
    assert "bp:pregnancy_severe" not in nlu["numeric_risk"]["reason_codes"]


def test_current_pregnancy_negation_blocks_older_positive_history():
    history = [{"role": "user", "content": "我老婆怀孕 8 周"}]
    nlu = analyze_health_message(
        "我老婆确认没怀孕，血压 165/110 mmHg",
        active_subject={"type": "relative", "relation": "wife", "source": "current_user_message"},
        history=history,
    )

    assert nlu["subject_traits"]["pregnancy_or_postpartum"] is False
    assert nlu["subject_traits"]["pregnancy_context_source"] == "current_message"
    assert "bp:pregnancy_severe" not in nlu["numeric_risk"]["reason_codes"]


def test_preconception_and_late_postpartum_do_not_use_pregnancy_threshold():
    preconception = analyze_health_message("我在备孕，血压 165/110 mmHg")
    late_postpartum = analyze_health_message("我产后 8 个月，血压 165/110 mmHg")

    assert "bp:pregnancy_severe" not in preconception["numeric_risk"]["reason_codes"]
    assert "bp:pregnancy_severe" not in late_postpartum["numeric_risk"]["reason_codes"]
    assert preconception["numeric_risk"]["level"] == "medium"
    assert late_postpartum["numeric_risk"]["level"] == "medium"


def test_pediatric_glucose_context_is_structured_without_turning_baby_into_pregnancy():
    nlu = analyze_health_message("5 岁孩子血糖 2.8 mmol/L")
    glucose = nlu["numeric_risk"]["observations"][0]

    assert glucose["subject_age_years"] == 5
    assert glucose["pediatric_context"] is True
    assert nlu["subject_traits"]["pregnancy_or_postpartum"] is False
