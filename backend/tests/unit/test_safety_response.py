from app.services.safety_service import emergency_response


def test_dka_warning_is_specific_and_actionable_on_first_screen() -> None:
    response = emergency_response("我妈血糖 20 mmol/L，恶心呕吐，呼吸很深很快")

    assert "20 mmol/L" in response["summary"]
    assert "酮症酸中毒" in response["summary"]
    assert "120" in response["summary"]
    assert "自行开车" in response["summary"]
    assert "尿酸" not in response["summary"]


def test_stroke_warning_captures_onset_time_without_waiting() -> None:
    response = emergency_response("我突然半边无力，口角歪，说话不清")

    assert "卒中" in response["summary"]
    assert "最后一次正常" in response["summary"]
    assert "120" in response["summary"]


def test_negated_chest_pain_is_not_used_to_create_specific_cardiac_template() -> None:
    response = emergency_response("我没有胸痛，只是误服了很多药")

    assert "胸痛、呼吸困难或昏厥" not in response["summary"]
    assert "急症风险" in response["summary"]


def test_unitless_glucose_with_vomiting_uses_ambiguity_safe_emergency_copy() -> None:
    response = emergency_response("血糖 20，后来开始呕吐")

    assert "未提供单位" in response["summary"]
    assert "同时出现呕吐" in response["summary"]
    assert "腹痛或深快呼吸" not in response["summary"]
    assert "mmol/L" in response["summary"]
    assert "mg/dL" in response["summary"]
    assert "120" in response["summary"]


def test_emergency_copy_does_not_turn_negated_symptoms_into_user_facts() -> None:
    response = emergency_response("血糖 20，没有腹痛，但是反复呕吐")

    assert "同时出现呕吐" in response["summary"]
    assert "同时出现腹痛" not in response["summary"]


def test_pregnancy_severe_pressure_emergency_names_only_active_warning_symptoms() -> None:
    response = emergency_response("孕 34 周，血压 165/112 mmHg，现在剧烈头痛，但没有上腹痛")

    assert "165/112 mmHg" in response["summary"]
    assert "同时出现剧烈头痛" in response["summary"]
    assert "同时出现上腹部疼痛" not in response["summary"]
    assert "产科急诊" in response["summary"]
    assert "120" in response["summary"]
    assert "自行开车" in response["summary"]
