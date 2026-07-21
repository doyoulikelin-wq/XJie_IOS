from app.services.payload_validator import validate_payload


def test_daily_briefing_payload_matches_persisted_action_schema() -> None:
    payload = {
        "type": "daily_briefing",
        "title": "今日代谢天气",
        "greeting": "还没有今日血糖数据。",
        "glucose_status": {
            "current_mgdl": None,
            "trend": "unknown",
            "tir_24h": None,
            "cv_24h": None,
            "mean_24h": None,
        },
        "risk_windows": [],
        "today_goals": ["保持当前节奏"],
        "evidence": {"window": "24h", "n_readings": 0},
    }

    result = validate_payload("daily_plan", "1.0.0", payload)

    assert result.valid is True
    assert result.status == "valid"
    assert result.payload == payload
