from app.services.symptom_triage import missing_symptom_boundary


def test_headache_gets_specific_boundary_when_model_only_says_other_symptoms() -> None:
    boundary = missing_symptom_boundary(
        ["headache"],
        "先补水并休息，如果有其他症状再就医。",
    )

    assert boundary is not None
    assert "最严重程度" in boundary
    assert "一侧无力" in boundary


def test_existing_headache_red_flags_are_not_duplicated() -> None:
    boundary = missing_symptom_boundary(
        ["headache"],
        "若突然出现剧烈头痛或说话不清，立即就医。",
    )

    assert boundary is None


def test_allergy_boundary_prioritizes_airway_risk() -> None:
    boundary = missing_symptom_boundary(["rash", "allergy"], "先停止使用新护肤品。")

    assert boundary is not None
    assert "舌头肿胀" in boundary
    assert "120" in boundary
