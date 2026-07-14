import importlib
from datetime import date, datetime

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.routers.indicators_extra import (
    DeviceIndicatorSyncIn,
    DeviceIndicatorValueIn,
    sync_device_indicators,
)


MIGRATION_MODULE = "app.db.migrations.versions.0021_device_indicator_source_identity"


def _legacy_table(metadata: sa.MetaData) -> sa.Table:
    return sa.Table(
        "user_indicator_values",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("indicator_name", sa.String(length=128), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(length=32), nullable=True),
        sa.Column("measured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def _run_migration(connection, monkeypatch, name: str) -> None:
    migration = importlib.import_module(MIGRATION_MODULE)
    operations = Operations(MigrationContext.configure(connection))
    monkeypatch.setattr(migration, "op", operations)
    getattr(migration, name)()


def test_migration_adds_defaults_indexes_and_backfills_legacy_notes(monkeypatch):
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    legacy = _legacy_table(metadata)
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            legacy.insert(),
            [
                {
                    "id": 1,
                    "user_id": 7,
                    "indicator_name": "步数",
                    "value": 100,
                    "unit": "步",
                    "measured_at": datetime(2024, 7, 2, 8),
                    "notes": "Apple Health 同步；source_metric=steps；source_id=duplicate-id",
                    "source": "apple_health",
                    "created_at": datetime(2024, 7, 2, 8, 1),
                },
                {
                    "id": 2,
                    "user_id": 7,
                    "indicator_name": "步数",
                    "value": 200,
                    "unit": "步",
                    "measured_at": datetime(2024, 7, 2, 9),
                    "notes": "Apple Health 同步；source_metric=steps；source_id=duplicate-id",
                    "source": "apple_health",
                    "created_at": datetime(2024, 7, 2, 9, 1),
                },
                {
                    "id": 3,
                    "user_id": 7,
                    "indicator_name": "步数",
                    "value": 300,
                    "unit": "步",
                    "measured_at": datetime(2024, 7, 3, 9),
                    "notes": "Apple Health 同步；source_metric=steps；source_id=steps-20240703",
                    "source": "apple_health",
                    "created_at": datetime(2024, 7, 3, 9, 1),
                },
            ],
        )
        _run_migration(connection, monkeypatch, "upgrade")

    inspector = sa.inspect(engine)
    columns = {column["name"]: column for column in inspector.get_columns("user_indicator_values")}
    indexes = {index["name"]: index for index in inspector.get_indexes("user_indicator_values")}
    assert {
        "source_metric",
        "source_id",
        "value_kind",
        "display_value",
        "source_local_date",
        "timezone_offset_minutes",
        "updated_at",
    }.issubset(columns)
    assert columns["updated_at"]["nullable"] is False
    assert columns["updated_at"]["default"] is not None
    assert columns["value_kind"]["nullable"] is False
    assert columns["value_kind"]["default"] is not None
    assert indexes["uq_user_indicator_source_sample"]["unique"] == 1
    assert "ix_user_indicator_source_metric_time" in indexes
    assert "ix_user_indicator_source_local_date" in indexes
    check_names = {
        constraint["name"]
        for constraint in inspector.get_check_constraints("user_indicator_values")
    }
    assert "ck_user_indicator_value_kind" in check_names
    assert "ck_user_indicator_timezone_offset" in check_names

    migrated = sa.Table("user_indicator_values", sa.MetaData(), autoload_with=engine)
    with engine.connect() as connection:
        rows = connection.execute(sa.select(migrated).order_by(migrated.c.id)).mappings().all()
    assert rows[0]["source_metric"] == "steps"
    assert rows[0]["source_id"] is None
    assert rows[1]["source_metric"] == "steps"
    assert rows[1]["source_id"] == "duplicate-id"
    assert rows[2]["source_local_date"] == date(2024, 7, 3)
    assert all(row["value_kind"] == "numeric" for row in rows)
    assert all(row["notes"] == "Apple Health 同步" for row in rows)
    assert all(row["updated_at"] is not None for row in rows)

    db = sessionmaker(bind=engine)()
    before_time = rows[2]["updated_at"]
    unchanged = sync_device_indicators(
        DeviceIndicatorSyncIn(
            source="apple_health",
            values=[DeviceIndicatorValueIn(
                indicator_name="步数",
                value=300,
                unit="步",
                measured_at=datetime(2024, 7, 3, 18),
                source_metric="steps",
                source_id="steps-20240703",
                notes="Apple Health 同步",
            )],
        ),
        user_id=7,
        db=db,
    )
    db.close()
    with engine.connect() as connection:
        unchanged_row = connection.execute(
            sa.select(migrated).where(migrated.c.id == 3)
        ).mappings().one()
    assert unchanged.unchanged == 1
    assert unchanged.updated == 0
    assert unchanged_row["measured_at"] == datetime(2024, 7, 3, 9)
    assert unchanged_row["updated_at"] == before_time

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                migrated.insert().values(
                    user_id=7,
                    indicator_name="步数",
                    value=300,
                    unit="步",
                    measured_at=datetime(2024, 7, 2, 10),
                    notes=None,
                    source="apple_health",
                    source_metric="steps",
                    source_id="duplicate-id",
                    created_at=datetime(2024, 7, 2, 10, 1),
                )
            )

    with engine.begin() as connection:
        connection.execute(
            migrated.insert().values(
                user_id=7,
                indicator_name="步数",
                value=300,
                unit="步",
                measured_at=datetime(2024, 7, 2, 10),
                notes=None,
                source="apple_health",
                source_metric="steps",
                source_id=None,
                created_at=datetime(2024, 7, 2, 10, 1),
            )
        )
    with engine.connect() as connection:
        inserted = connection.execute(
            sa.select(migrated).where(migrated.c.notes.is_(None))
        ).mappings().one()
    assert inserted["updated_at"] is not None
    assert inserted["value_kind"] == "numeric"


def test_migration_is_safe_before_metadata_creates_legacy_table(monkeypatch):
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        _run_migration(connection, monkeypatch, "upgrade")
    assert "user_indicator_values" not in sa.inspect(engine).get_table_names()


def test_migration_does_not_treat_manual_notes_as_device_identity(monkeypatch):
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    legacy = _legacy_table(metadata)
    metadata.create_all(engine)
    created_at = datetime(2024, 7, 2, 8, 1)
    with engine.begin() as connection:
        connection.execute(
            legacy.insert().values(
                id=1,
                user_id=9,
                indicator_name="收缩压",
                value=142,
                unit="mmHg",
                measured_at=datetime(2024, 7, 2, 8),
                notes=(
                    "用户自由备注；source_metric=not-device；source_id=not-device-id；"
                    "source_updated_at=2024-07-03T09:00:00"
                ),
                source="manual",
                created_at=created_at,
            )
        )
        _run_migration(connection, monkeypatch, "upgrade")

    upgraded = sa.Table("user_indicator_values", sa.MetaData(), autoload_with=engine)
    with engine.connect() as connection:
        row = connection.execute(sa.select(upgraded)).mappings().one()
    assert row["source_metric"] is None
    assert row["source_id"] is None
    assert row["updated_at"] == created_at
    assert "source_id=not-device-id" in row["notes"]


def test_migration_round_trip_preserves_new_source_identity_in_legacy_notes(monkeypatch):
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    _legacy_table(metadata)
    metadata.create_all(engine)

    with engine.begin() as connection:
        _run_migration(connection, monkeypatch, "upgrade")
        upgraded = sa.Table(
            "user_indicator_values",
            sa.MetaData(),
            autoload_with=connection,
        )
        connection.execute(
            upgraded.insert().values(
                user_id=9,
                indicator_name="活动能量",
                value=456,
                unit="kcal",
                measured_at=datetime(2024, 7, 2, 10),
                notes="升级后写入的自由备注",
                source="apple_health",
                source_metric="activeEnergy",
                source_id="new-version-source-id",
                value_kind="category",
                display_value="清醒；平静",
                source_local_date=date(2024, 7, 2),
                timezone_offset_minutes=480,
                created_at=datetime(2024, 7, 2, 10, 1),
                updated_at=datetime(2024, 7, 3, 11, 30),
            )
        )
        _run_migration(connection, monkeypatch, "downgrade")

    downgraded_columns = {
        column["name"] for column in sa.inspect(engine).get_columns("user_indicator_values")
    }
    assert "source_metric" not in downgraded_columns
    assert "source_id" not in downgraded_columns
    assert "value_kind" not in downgraded_columns
    assert "display_value" not in downgraded_columns
    assert "source_local_date" not in downgraded_columns
    assert "timezone_offset_minutes" not in downgraded_columns
    assert "updated_at" not in downgraded_columns
    downgraded = sa.Table("user_indicator_values", sa.MetaData(), autoload_with=engine)
    with engine.connect() as connection:
        legacy_row = connection.execute(sa.select(downgraded)).mappings().one()
    assert legacy_row["notes"].startswith(
        "升级后写入的自由备注；source_metric=activeEnergy；"
        "source_id=new-version-source-id；source_value_kind=category；"
        "source_display_value="
    )
    assert "source_local_date=2024-07-02" in legacy_row["notes"]
    assert "source_timezone_offset_minutes=480" in legacy_row["notes"]
    assert "source_updated_at=2024-07-03T11:30:00" in legacy_row["notes"]

    with engine.begin() as connection:
        _run_migration(connection, monkeypatch, "upgrade")
    restored = sa.Table("user_indicator_values", sa.MetaData(), autoload_with=engine)
    with engine.connect() as connection:
        restored_row = connection.execute(sa.select(restored)).mappings().one()
    assert restored_row["source_metric"] == "activeEnergy"
    assert restored_row["source_id"] == "new-version-source-id"
    assert restored_row["value_kind"] == "category"
    assert restored_row["display_value"] == "清醒；平静"
    assert restored_row["source_local_date"] == date(2024, 7, 2)
    assert restored_row["timezone_offset_minutes"] == 480
    assert restored_row["value"] == 456
    assert restored_row["updated_at"] == datetime(2024, 7, 3, 11, 30)
    assert restored_row["notes"] == "升级后写入的自由备注"
