from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.deps import get_db
from app.core.security import create_access_token
from app.db.base import Base
from app.models.health_document import HealthSummary
from app.models.user import User
from app.models.user_indicator_value import UserIndicatorValue
from app.routers import health_data, indicators_extra


def _client() -> tuple[TestClient, sessionmaker, str]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with factory() as db:
        db.add(User(id=1, phone="18800000005", username="http-test", password="x"))
        db.commit()

    app = FastAPI()
    app.include_router(health_data.router, prefix="/api/health-data")
    app.include_router(indicators_extra.router, prefix="/api/health-data")

    def override_db() -> Iterator[Session]:
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    token = create_access_token("1")
    return TestClient(app), factory, f"Bearer {token}"


def _payload(*values: dict) -> dict:
    return {"source": "apple_health", "values": list(values)}


def _sample(
    *,
    source_id: str,
    value: float = 72,
    measured_at: datetime | None = None,
    indicator_name: str = "静息心率",
) -> dict:
    return {
        "indicator_name": indicator_name,
        "value": value,
        "unit": "bpm",
        "measured_at": (measured_at or datetime(2024, 7, 2, 8, tzinfo=timezone.utc)).isoformat(),
        "source_metric": "restingHeartRate",
        "source_id": source_id,
        "notes": "Apple Health 同步",
    }


def test_device_sync_requires_authentication_and_valid_schema():
    client, factory, authorization = _client()
    path = "/api/health-data/indicators/device-sync"

    unauthorized = client.post(path, json=_payload(_sample(source_id="auth-sample")))
    malformed = client.post(
        path,
        headers={"Authorization": authorization},
        json=_payload({**_sample(source_id="bad-schema"), "value": "not-a-number"}),
    )

    assert unauthorized.status_code == 401
    assert malformed.status_code == 422
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(UserIndicatorValue)) == 0


def test_all_future_values_return_structured_422_instead_of_success():
    client, factory, authorization = _client()
    response = client.post(
        "/api/health-data/indicators/device-sync",
        headers={"Authorization": authorization},
        json=_payload(
            _sample(
                source_id="future-sample",
                measured_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
        ),
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail == {
        "code": "all_values_rejected",
        "message": "没有可写入的设备健康样本，请检查样本时间或数据格式。",
        "total": 1,
        "inserted": 0,
        "updated": 0,
        "unchanged": 0,
        "rejected": 1,
        "skipped": 1,
        "issues": [{"index": 0, "code": "future_measured_at"}],
    }
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(UserIndicatorValue)) == 0


def test_partial_sync_distinguishes_rejected_and_unchanged_samples():
    client, _factory, authorization = _client()
    path = "/api/health-data/indicators/device-sync"
    valid = _sample(source_id="stable-sample")
    future = _sample(
        source_id="future-sample",
        measured_at=datetime.now(timezone.utc) + timedelta(days=1),
    )

    first = client.post(
        path,
        headers={"Authorization": authorization},
        json=_payload(valid, future),
    )
    second = client.post(
        path,
        headers={"Authorization": authorization},
        json=_payload(valid),
    )

    assert first.status_code == 200
    assert first.json() == {
        "total": 2,
        "inserted": 1,
        "updated": 0,
        "unchanged": 0,
        "rejected": 1,
        "issues": [{"index": 1, "code": "future_measured_at"}],
        "skipped": 1,
    }
    assert second.status_code == 200
    assert second.json()["inserted"] == 0
    assert second.json()["updated"] == 0
    assert second.json()["unchanged"] == 1
    assert second.json()["rejected"] == 0
    assert second.json()["skipped"] == 1


def test_source_id_cannot_be_rebound_to_a_different_metric():
    client, factory, authorization = _client()
    path = "/api/health-data/indicators/device-sync"
    headers = {"Authorization": authorization}
    original = _sample(source_id="immutable-source-id")
    collision = {
        **_sample(
            source_id="immutable-source-id",
            value=65,
            indicator_name="体重",
        ),
        "unit": "kg",
        "source_metric": "bodyWeight",
    }

    assert client.post(path, headers=headers, json=_payload(original)).status_code == 200
    rejected = client.post(path, headers=headers, json=_payload(collision))

    assert rejected.status_code == 422
    assert rejected.json()["detail"]["issues"] == [
        {"index": 0, "code": "source_id_conflict"}
    ]
    with factory() as db:
        row = db.execute(select(UserIndicatorValue)).scalars().one()
        assert row.indicator_name == "静息心率"
        assert row.value == 72
        assert row.source_metric == "restingHeartRate"


def test_manual_value_is_protected_and_distinct_device_samples_round_trip_in_trend():
    client, factory, authorization = _client()
    headers = {"Authorization": authorization}
    manual = client.post(
        "/api/health-data/indicators/manual",
        headers=headers,
        json={
            "indicator_name": "静息心率",
            "value": 80,
            "unit": "bpm",
            "measured_at": "2024-07-02T07:00:00+00:00",
            "notes": "用户手动输入",
        },
    )
    sync = client.post(
        "/api/health-data/indicators/device-sync",
        headers=headers,
        json=_payload(
            _sample(
                source_id="heart-rate-a",
                value=72,
                measured_at=datetime(2024, 7, 2, 8, tzinfo=timezone.utc),
            ),
            _sample(
                source_id="heart-rate-b",
                value=68,
                measured_at=datetime(2024, 7, 2, 9, tzinfo=timezone.utc),
            ),
        ),
    )
    trend = client.get(
        "/api/health-data/indicators/trend",
        headers=headers,
        params={"names": "静息心率"},
    )

    assert manual.status_code == 200
    assert sync.status_code == 200
    assert sync.json()["inserted"] == 2
    assert trend.status_code == 200
    points = trend.json()["indicators"][0]["points"]
    assert [point["value"] for point in points] == [80, 72, 68]
    assert [point["source"] for point in points] == ["manual", "apple_health", "apple_health"]
    assert [point["source_id"] for point in points] == [None, "heart-rate-a", "heart-rate-b"]

    with factory() as db:
        rows = db.execute(
            select(UserIndicatorValue).order_by(UserIndicatorValue.measured_at)
        ).scalars().all()
        assert len(rows) == 3
        assert rows[0].source == "manual"
        assert rows[0].value == 80
        assert rows[0].source_id is None


def test_device_sync_does_not_falsely_refresh_document_health_summary():
    client, factory, authorization = _client()
    summary_time = datetime(2024, 6, 30, 12, tzinfo=timezone.utc)
    with factory() as db:
        db.add(HealthSummary(
            user_id=1,
            summary_text="仅由报告生成的既有摘要",
            version=1,
            created_at=summary_time,
            updated_at=summary_time,
        ))
        db.commit()

    sync = client.post(
        "/api/health-data/indicators/device-sync",
        headers={"Authorization": authorization},
        json=_payload(_sample(source_id="summary-boundary-sample")),
    )
    summary = client.get(
        "/api/health-data/summary",
        headers={"Authorization": authorization},
    )

    assert sync.status_code == 200
    assert sync.json()["inserted"] == 1
    assert summary.status_code == 200
    # A legacy cache is not trusted evidence without an active admitted report
    # observation. Device sync must not make that cache appear current.
    assert summary.json() == {"summary_text": "", "updated_at": None}


def test_category_value_and_explicit_local_date_round_trip_in_trend():
    client, factory, authorization = _client()
    response = client.post(
        "/api/health-data/indicators/device-sync",
        headers={"Authorization": authorization},
        json=_payload({
            "indicator_name": "意识状态",
            "value": 1,
            "unit": None,
            "measured_at": "2026-07-01T16:30:00+00:00",
            "source_metric": "stateOfMind",
            "source_id": "stateOfMind-00000000-0000-0000-0000-000000000010",
            "value_kind": "category",
            "display_value": "平静",
            "source_local_date": "2026-07-02",
            "timezone_offset_minutes": 480,
            "notes": "Apple Health 同步",
        }),
    )
    trend = client.get(
        "/api/health-data/indicators/trend",
        headers={"Authorization": authorization},
        params={"names": "意识状态"},
    )

    assert response.status_code == 200
    assert response.json()["inserted"] == 1
    assert trend.status_code == 200
    point = trend.json()["indicators"][0]["points"][0]
    assert point["date"] == "2026-07-02"
    assert point["value"] == 1
    assert point["value_kind"] == "category"
    assert point["display_value"] == "平静"
    assert point["source_local_date"] == "2026-07-02"
    assert point["timezone_offset_minutes"] == 480
    with factory() as db:
        row = db.execute(select(UserIndicatorValue)).scalars().one()
        assert row.value_kind == "category"
        assert row.display_value == "平静"
        assert row.source_local_date.isoformat() == "2026-07-02"


def test_category_requires_label_and_daily_identity_must_match_local_date():
    client, _factory, authorization = _client()
    path = "/api/health-data/indicators/device-sync"
    headers = {"Authorization": authorization}
    missing_label = client.post(
        path,
        headers=headers,
        json=_payload({
            **_sample(source_id="stateOfMind-20260702", indicator_name="意识状态"),
            "source_metric": "stateOfMind",
            "value_kind": "category",
            "display_value": "",
            "source_local_date": "2026-07-02",
        }),
    )
    conflicting_date = client.post(
        path,
        headers=headers,
        json=_payload({
            **_sample(source_id="steps-20260702"),
            "source_metric": "steps",
            "source_local_date": "2026-07-03",
        }),
    )
    invalid_offset = client.post(
        path,
        headers=headers,
        json=_payload({
            **_sample(source_id="offset-schema"),
            "timezone_offset_minutes": 900,
        }),
    )

    assert missing_label.status_code == 422
    assert missing_label.json()["detail"]["issues"] == [
        {"index": 0, "code": "missing_display_value"}
    ]
    assert conflicting_date.status_code == 422
    assert conflicting_date.json()["detail"]["issues"] == [
        {"index": 0, "code": "source_local_date_conflict"}
    ]
    assert invalid_offset.status_code == 422
