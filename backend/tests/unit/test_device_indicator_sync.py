from datetime import datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.user import User
from app.models.user_indicator_value import UserIndicatorValue
from app.routers.indicators_extra import DeviceIndicatorSyncIn, DeviceIndicatorValueIn, sync_device_indicators


def test_device_sync_updates_same_day_metric_instead_of_duplicating():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    db.add(User(id=1, phone="18800000000", username="tester", password="x"))
    db.commit()

    first = DeviceIndicatorSyncIn(
        source="apple_health",
        values=[
            DeviceIndicatorValueIn(
                indicator_name="步数",
                value=8200,
                unit="步",
                measured_at=datetime(2024, 7, 2, 9, 0, tzinfo=timezone.utc),
                source_metric="steps",
                source_id="steps-20260702-a",
                notes="Apple Health 同步",
            )
        ],
    )
    second = DeviceIndicatorSyncIn(
        source="apple_health",
        values=[
            DeviceIndicatorValueIn(
                indicator_name="步数",
                value=9300,
                unit="步",
                measured_at=datetime(2024, 7, 2, 18, 0, tzinfo=timezone.utc),
                source_metric="steps",
                source_id="steps-20260702-b",
                notes="Apple Health 同步",
            )
        ],
    )

    first_out = sync_device_indicators(first, user_id=1, db=db)
    second_out = sync_device_indicators(second, user_id=1, db=db)

    rows = db.execute(select(UserIndicatorValue)).scalars().all()
    assert first_out.inserted == 1
    assert second_out.updated == 1
    assert len(rows) == 1
    assert rows[0].value == 9300
    assert rows[0].source == "apple_health"
