from datetime import datetime, timedelta, timezone

from app.services.chat_evidence import assess_trend_evidence, build_evidence_limited_reply


def _nlu() -> dict:
    return {
        "primary_intent": "trend_analysis",
        "concept_keys": ["hrv"],
        "matched_concepts": [{"key": "hrv", "display": "心率变异性"}],
    }


def _sample(when: datetime, value: float) -> dict:
    return {
        "value": value,
        "unit": "ms",
        "source": "apple_health",
        "measured_at": when.isoformat(),
    }


def test_single_hrv_sample_cannot_support_weekly_trend() -> None:
    now = datetime(2026, 7, 10, tzinfo=timezone.utc)
    memory = {
        "metrics": [{
            "metric": "hrv",
            "recent_samples": [_sample(now - timedelta(days=1), 43)],
        }],
    }

    evidence = assess_trend_evidence(
        user_query="帮我分析最近一周 HRV",
        health_nlu=_nlu(),
        data_source_memory=memory,
        subject_type="self",
        now=now,
    )

    assert evidence["status"] == "insufficient"
    assert evidence["sample_count"] == 1
    assert evidence["distinct_days"] == 1
    reply = build_evidence_limited_reply(evidence)
    assert "只有 1 个心率变异性样本" in reply["summary"]
    assert "不能得出“一周稳定、下降或几天偏低”" in reply["summary"]
    assert "43 ms" in reply["summary"]
    assert "Apple 健康" in reply["summary"]


def test_four_distinct_days_support_seven_day_evidence_gate() -> None:
    now = datetime(2026, 7, 10, tzinfo=timezone.utc)
    memory = {
        "metrics": [{
            "metric": "heart_rate_variability",
            "recent_samples": [
                _sample(now - timedelta(days=day), 40 + day)
                for day in (1, 2, 3, 4)
            ],
        }],
    }

    evidence = assess_trend_evidence(
        user_query="最近7天 HRV 趋势",
        health_nlu=_nlu(),
        data_source_memory=memory,
        subject_type="self",
        now=now,
    )

    assert evidence["status"] == "sufficient"
    assert evidence["sample_count"] == 4
    assert evidence["distinct_days"] == 4
    assert evidence["computed_range"]["minimum"] == 41
    assert evidence["computed_range"]["maximum"] == 44


def test_relative_trend_does_not_read_logged_in_users_series() -> None:
    evidence = assess_trend_evidence(
        user_query="帮我看我妈最近一周 HRV",
        health_nlu=_nlu(),
        data_source_memory={"metrics": []},
        subject_type="relative",
    )

    assert evidence == {"status": "not_applicable"}
