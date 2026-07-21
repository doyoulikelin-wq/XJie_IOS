from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.user import User
from app.models.user_indicator_value import UserIndicatorValue
from app.routers.indicators_extra import (
    DeviceIndicatorSyncIn,
    DeviceIndicatorValueIn,
    sync_device_indicators,
)


def _db_session(phone: str = "18800000000"):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    db.add(User(id=1, phone=phone, username="tester", password="x"))
    db.commit()
    return db


def _value(
    *,
    value: float,
    measured_at: datetime,
    source_id: str | None,
    name: str = "步数",
    source_metric: str = "steps",
) -> DeviceIndicatorValueIn:
    return DeviceIndicatorValueIn(
        indicator_name=name,
        value=value,
        unit="步",
        measured_at=measured_at,
        source_metric=source_metric,
        source_id=source_id,
        notes="Apple Health 同步",
    )


def _sync(db, *values: DeviceIndicatorValueIn):
    return sync_device_indicators(
        DeviceIndicatorSyncIn(source="apple_health", values=list(values)),
        user_id=1,
        db=db,
    )


def test_distinct_source_ids_preserve_same_day_samples():
    db = _db_session()
    first = _value(
        value=8200,
        measured_at=datetime(2024, 7, 2, 9, 0, tzinfo=timezone.utc),
        source_id="steps-20240702-a",
    )
    second = _value(
        value=9300,
        measured_at=datetime(2024, 7, 2, 18, 0, tzinfo=timezone.utc),
        source_id="steps-20240702-b",
    )

    first_out = _sync(db, first)
    second_out = _sync(db, second)

    rows = db.execute(select(UserIndicatorValue).order_by(UserIndicatorValue.measured_at)).scalars().all()
    assert first_out.inserted == 1
    assert second_out.inserted == 1
    assert second_out.updated == 0
    assert [row.value for row in rows] == [8200, 9300]
    assert [row.source_id for row in rows] == ["steps-20240702-a", "steps-20240702-b"]


def test_same_source_id_updates_then_reports_unchanged_without_bumping_sync_time():
    db = _db_session("18800000001")
    source_id = "steps-cumulative-20240702"
    first = _value(
        value=8200,
        measured_at=datetime(2024, 7, 2, 9, 0, tzinfo=timezone.utc),
        source_id=source_id,
    )
    changed = _value(
        value=9300,
        measured_at=datetime(2024, 7, 2, 18, 0, tzinfo=timezone.utc),
        source_id=source_id,
    )

    _sync(db, first)
    changed_out = _sync(db, changed)
    db.expire_all()
    row = db.execute(select(UserIndicatorValue)).scalars().one()
    changed_sync_time = row.updated_at
    unchanged_out = _sync(db, changed)
    db.expire_all()
    row = db.execute(select(UserIndicatorValue)).scalars().one()

    assert changed_out.updated == 1
    assert unchanged_out.unchanged == 1
    assert unchanged_out.updated == 0
    assert unchanged_out.rejected == 0
    assert unchanged_out.skipped == 1
    assert row.value == 9300
    assert row.source_id == source_id
    assert row.updated_at == changed_sync_time


def test_apple_health_never_overwrites_manual_value():
    db = _db_session("18800000002")
    manual = UserIndicatorValue(
        user_id=1,
        indicator_name="收缩压",
        value=142,
        unit="mmHg",
        measured_at=datetime(2024, 7, 2, 8, 0, tzinfo=timezone.utc),
        notes="用户手动输入",
        source="manual",
    )
    db.add(manual)
    db.commit()
    manual_id = manual.id

    out = _sync(
        db,
        DeviceIndicatorValueIn(
            indicator_name="收缩压",
            value=124,
            unit="mmHg",
            measured_at=datetime(2024, 7, 2, 19, 30, tzinfo=timezone.utc),
            source_metric="systolicBloodPressure",
            source_id="systolic-20240702",
            notes="Apple Health 同步",
        ),
    )

    rows = db.execute(select(UserIndicatorValue).order_by(UserIndicatorValue.id)).scalars().all()
    assert out.inserted == 1
    assert out.updated == 0
    assert len(rows) == 2
    assert rows[0].id == manual_id
    assert rows[0].value == 142
    assert rows[0].source == "manual"
    assert rows[0].source_id is None
    assert rows[1].value == 124
    assert rows[1].source == "apple_health"
    assert rows[1].source_metric == "systolicBloodPressure"
    assert rows[1].source_id == "systolic-20240702"


def test_legacy_samples_dedupe_by_encoded_local_calendar_day():
    db = _db_session("18800000003")
    # Both timestamps are July 2 in the encoded +14:00 local time, but they fall
    # on different UTC dates. Legacy clients should still update one daily row.
    first = _value(
        value=100,
        measured_at=datetime.fromisoformat("2024-07-02T00:30:00+14:00"),
        source_id=None,
    )
    second = _value(
        value=200,
        measured_at=datetime.fromisoformat("2024-07-02T23:30:00+14:00"),
        source_id=None,
    )

    first_out = _sync(db, first)
    second_out = _sync(db, second)
    rows = db.execute(select(UserIndicatorValue)).scalars().all()

    assert first_out.inserted == 1
    assert second_out.updated == 1
    assert len(rows) == 1
    assert rows[0].value == 200
    assert rows[0].source_id is None


def test_source_id_remains_authoritative_across_local_date_boundary():
    db = _db_session("18800000004")
    source_id = "daily-cumulative-stable-id"
    first = _value(
        value=100,
        measured_at=datetime.fromisoformat("2024-07-02T23:59:00+08:00"),
        source_id=source_id,
    )
    second = _value(
        value=120,
        measured_at=datetime.fromisoformat("2024-07-03T00:01:00+08:00"),
        source_id=source_id,
    )

    _sync(db, first)
    out = _sync(db, second)
    rows = db.execute(select(UserIndicatorValue)).scalars().all()

    assert out.updated == 1
    assert len(rows) == 1
    assert rows[0].value == 120
    assert rows[0].source_id == source_id


def test_daily_cumulative_time_only_change_is_unchanged_and_preserves_timestamps():
    db = _db_session("18800000006")
    source_id = "steps-20240702"
    first = _value(
        value=8200,
        measured_at=datetime(2024, 7, 2, 9, tzinfo=timezone.utc),
        source_id=source_id,
    )
    time_only = _value(
        value=8200,
        measured_at=datetime(2024, 7, 2, 18, tzinfo=timezone.utc),
        source_id=source_id,
    )

    _sync(db, first)
    db.expire_all()
    before = db.execute(select(UserIndicatorValue)).scalars().one()
    original_measured_at = before.measured_at
    original_updated_at = before.updated_at
    out = _sync(db, time_only)
    db.expire_all()
    after = db.execute(select(UserIndicatorValue)).scalars().one()

    assert out.unchanged == 1
    assert out.updated == 0
    assert after.measured_at == original_measured_at
    assert after.updated_at == original_updated_at
    assert after.source_local_date.isoformat() == "2024-07-02"


def test_uuid_identity_time_correction_updates_discrete_sample():
    db = _db_session("18800000007")
    source_id = "hrv-00000000-0000-0000-0000-000000000001"
    first = _value(
        name="心率变异性",
        source_metric="hrv",
        value=42,
        measured_at=datetime(2024, 7, 2, 9, tzinfo=timezone.utc),
        source_id=source_id,
    )
    corrected = _value(
        name="心率变异性",
        source_metric="hrv",
        value=42,
        measured_at=datetime(2024, 7, 2, 9, 1, tzinfo=timezone.utc),
        source_id=source_id,
    )

    _sync(db, first)
    out = _sync(db, corrected)
    row = db.execute(select(UserIndicatorValue)).scalars().one()

    assert out.updated == 1
    assert row.measured_at.minute == 1


def test_latest_sample_uuid_adopts_exact_legacy_timestamp_identity():
    db = _db_session("18800000008")
    measured_at = datetime(2024, 7, 2, 9, tzinfo=timezone.utc)
    legacy_id = f"hrv-{int(measured_at.timestamp())}"
    uuid_id = "hrv-00000000-0000-0000-0000-000000000008"
    legacy = _value(
        name="心率变异性",
        source_metric="hrv",
        value=42,
        measured_at=measured_at,
        source_id=legacy_id,
    )
    current = _value(
        name="心率变异性",
        source_metric="hrv",
        value=42,
        measured_at=measured_at,
        source_id=uuid_id,
    )

    _sync(db, legacy)
    db.expire_all()
    before = db.execute(select(UserIndicatorValue)).scalars().one()
    original_updated_at = before.updated_at
    out = _sync(db, current)
    db.expire_all()
    rows = db.execute(select(UserIndicatorValue)).scalars().all()

    assert out.unchanged == 1
    assert out.inserted == 0
    assert out.updated == 0
    assert len(rows) == 1
    assert rows[0].source_id == uuid_id
    assert rows[0].updated_at == original_updated_at


def test_uuid_does_not_adopt_non_exact_legacy_timestamp_identity():
    db = _db_session("18800000009")
    measured_at = datetime(2024, 7, 2, 9, tzinfo=timezone.utc)
    legacy = _value(
        name="心率变异性",
        source_metric="hrv",
        value=42,
        measured_at=measured_at,
        source_id=f"hrv-{int(measured_at.timestamp()) - 1}",
    )
    current = _value(
        name="心率变异性",
        source_metric="hrv",
        value=42,
        measured_at=measured_at,
        source_id="hrv-00000000-0000-0000-0000-000000000009",
    )

    _sync(db, legacy)
    out = _sync(db, current)
    rows = db.execute(select(UserIndicatorValue)).scalars().all()

    assert out.inserted == 1
    assert len(rows) == 2


def test_identity_rollout_uses_stable_source_metric_when_display_name_changed():
    db = _db_session("18800000012")
    measured_at = datetime(2024, 7, 2, 9, tzinfo=timezone.utc)
    legacy_id = f"hrv-{int(measured_at.timestamp())}"
    uuid_id = "hrv-00000000-0000-0000-0000-000000000012"
    db.add(UserIndicatorValue(
        user_id=1,
        indicator_name="旧版 HRV 名称",
        value=42,
        unit="步",
        measured_at=measured_at,
        notes="Apple Health 同步",
        source="apple_health",
        source_metric="hrv",
        source_id=legacy_id,
        value_kind="numeric",
    ))
    db.commit()

    out = _sync(
        db,
        _value(
            name="心率变异性",
            source_metric="hrv",
            value=42,
            measured_at=measured_at,
            source_id=uuid_id,
        ),
    )
    row = db.execute(select(UserIndicatorValue)).scalars().one()

    assert out.unchanged == 1
    assert row.source_id == uuid_id
    assert row.indicator_name == "心率变异性"


def test_existing_uuid_request_removes_exact_legacy_duplicate():
    db = _db_session("18800000010")
    measured_at = datetime(2024, 7, 2, 9, tzinfo=timezone.utc)
    legacy_id = f"hrv-{int(measured_at.timestamp())}"
    uuid_id = "hrv-00000000-0000-0000-0000-000000000010"
    for source_id in (legacy_id, uuid_id):
        db.add(UserIndicatorValue(
            user_id=1,
            indicator_name="心率变异性",
            value=42,
            unit="步",
            measured_at=measured_at,
            notes="Apple Health 同步",
            source="apple_health",
            source_metric="hrv",
            source_id=source_id,
            value_kind="numeric",
        ))
    db.commit()

    out = _sync(
        db,
        _value(
            name="心率变异性",
            source_metric="hrv",
            value=42,
            measured_at=measured_at,
            source_id=uuid_id,
        ),
    )
    rows = db.execute(select(UserIndicatorValue)).scalars().all()

    assert out.unchanged == 1
    assert len(rows) == 1
    assert rows[0].source_id == uuid_id


def test_conflicting_uuid_does_not_delete_valid_legacy_identity():
    db = _db_session("18800000011")
    measured_at = datetime(2024, 7, 2, 9, tzinfo=timezone.utc)
    legacy_id = f"hrv-{int(measured_at.timestamp())}"
    uuid_id = "hrv-00000000-0000-0000-0000-000000000011"
    db.add_all([
        UserIndicatorValue(
            user_id=1,
            indicator_name="心率变异性",
            value=42,
            unit="步",
            measured_at=measured_at,
            notes="Apple Health 同步",
            source="apple_health",
            source_metric="hrv",
            source_id=legacy_id,
            value_kind="numeric",
        ),
        UserIndicatorValue(
            user_id=1,
            indicator_name="体重",
            value=65,
            unit="kg",
            measured_at=measured_at,
            notes="冲突样本",
            source="apple_health",
            source_metric="bodyWeight",
            source_id=uuid_id,
            value_kind="numeric",
        ),
    ])
    db.commit()

    with pytest.raises(HTTPException) as rejected:
        _sync(
            db,
            _value(
                name="心率变异性",
                source_metric="hrv",
                value=42,
                measured_at=measured_at,
                source_id=uuid_id,
            ),
        )
    rows = db.execute(select(UserIndicatorValue)).scalars().all()

    assert rejected.value.status_code == 422
    assert rejected.value.detail["issues"] == [
        {"index": 0, "code": "source_id_conflict"}
    ]
    assert len(rows) == 2
    assert {row.source_id for row in rows} == {legacy_id, uuid_id}
