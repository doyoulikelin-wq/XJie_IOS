from app.services.numeric_health_risk import build_high_numeric_risk_reply


def test_severe_blood_pressure_reply_requires_recheck_without_declaring_emergency() -> None:
    reply = build_high_numeric_risk_reply({
        "reason_codes": ["bp:severe_range"],
        "observations": [{"metric": "blood_pressure", "systolic": 190, "diastolic": 125}],
    })

    assert "190/125 mmHg" in reply["summary"]
    assert "至少 1 分钟" in reply["summary"]
    assert "复测仍高于 180/120" in reply["summary"]
    assert "一旦出现胸痛" in reply["summary"]


def test_level_two_hypoglycemia_reply_has_swallowing_boundary() -> None:
    reply = build_high_numeric_risk_reply({
        "reason_codes": ["glucose:level_2_hypoglycemia"],
        "observations": [{"metric": "blood_glucose", "value": 2.8, "unit": "mmol/L"}],
    })

    assert "15 克快速糖" in reply["summary"]
    assert "15 分钟后复测" in reply["summary"]
    assert "不能吞咽时" in reply["summary"]
    assert "不要经口喂食" in reply["summary"]


def test_unitless_dangerous_glucose_reply_explains_both_units() -> None:
    reply = build_high_numeric_risk_reply({
        "reason_codes": ["glucose:unit_missing", "glucose:unit_ambiguous_dangerous"],
        "observations": [{"metric": "blood_glucose", "value": 20, "unit": None}],
    })

    assert "20" in reply["summary"]
    assert "mmol/L" in reply["summary"]
    assert "mg/dL" in reply["summary"]
    assert "立即核对仪器单位并复测" in reply["summary"]


def test_pregnancy_severe_pressure_reply_uses_obstetric_threshold_and_urgency() -> None:
    reply = build_high_numeric_risk_reply({
        "reason_codes": ["bp:pregnancy_severe"],
        "observations": [
            {
                "metric": "blood_pressure",
                "systolic": 160,
                "diastolic": 110,
                "pregnancy_context": True,
            }
        ],
    })

    assert "160/110 mmHg" in reply["summary"]
    assert "收缩压达到 160 或舒张压达到 110" in reply["summary"]
    assert "产科急诊" in reply["summary"]
    assert "15 分钟内" in reply["summary"]
    assert "180/120" not in reply["summary"]


def test_confirmed_child_hypoglycemia_does_not_apply_fixed_adult_dose() -> None:
    reply = build_high_numeric_risk_reply({
        "reason_codes": ["glucose:level_2_hypoglycemia"],
        "observations": [
            {
                "metric": "blood_glucose",
                "value": 2.8,
                "unit": "mmol/L",
                "subject_age_years": 5,
                "pediatric_context": True,
            }
        ],
    })

    assert "按孩子既定低血糖方案" in reply["summary"]
    assert "通常少于成人 15 克" in reply["summary"]
    assert "15 分钟后复测" in reply["summary"]
    assert "立即摄入 15 克快速糖" not in reply["summary"]


def test_unknown_age_child_relation_states_both_dosing_paths_without_guessing() -> None:
    reply = build_high_numeric_risk_reply(
        {
            "reason_codes": ["glucose:level_2_hypoglycemia"],
            "observations": [{"metric": "blood_glucose", "value": 50, "unit": "mg/dL"}],
        },
        subject={"type": "relative", "relation": "child"},
    )

    assert "未满 18 岁" in reply["summary"]
    assert "已经成年" in reply["summary"]
    assert "年龄不明确时不要直接套用成人剂量" in reply["summary"]
