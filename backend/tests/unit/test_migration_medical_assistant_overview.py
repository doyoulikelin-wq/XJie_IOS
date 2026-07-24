"""就医助手概况的新鲜度、主体和近一年证据回归。"""

from __future__ import annotations

from collections.abc import Iterator
import contextlib
import copy
from datetime import datetime, timedelta, timezone
import importlib
import io
import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.deps import get_db
from app.core.security import create_access_token
from app.db.base import Base
from app.models.health_document import (
    HealthDocument,
    MedicalAssistantOverview,
)
from app.models.health_trust import HealthReportWorkflow
from app.models.user import User
from app.routers import health_data
from app.services.medical_assistant_service import generate_medical_assistant_overview
from deploy import production_deploy_guard as deploy_guard


def _candidate_manifest() -> dict:
    """读取当前模型与 Alembic 链的候选清单。"""

    backend_root = Path(__file__).resolve().parents[2]
    probe = deploy_guard.MIGRATION_PROBE_SOURCE.replace(
        'APPLICATION_ROOT = Path("/app")',
        f"APPLICATION_ROOT = Path({str(backend_root)!r})",
    )
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        exec(
            compile(probe, "candidate_medical_assistant_migration_probe.py", "exec"),
            {"__name__": "__main__"},
        )
    return json.loads(output.getvalue())


def _old_0025_manifest(candidate: dict) -> dict:
    """从当前候选剥离 0026 表与 revision，构造真实旧 head。"""

    old = copy.deepcopy(candidate)
    old["migrations"] = old["migrations"][:-1]
    old["heads"] = [old["migrations"][-1]["revision"]]
    old["model_schema"] = [
        table
        for table in old["model_schema"]
        if table["name"] != "medical_assistant_overviews"
    ]
    return old


def test_0026_migration_adds_isolated_overview_snapshot_and_timestamp_evidence(monkeypatch):
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    sa.Table(
        "user_account",
        metadata,
        sa.Column("id", sa.BigInteger(), primary_key=True),
    )
    metadata.create_all(engine)
    migration = importlib.import_module(
        "app.db.migrations.versions.0026_medical_assistant_overview"
    )
    with engine.begin() as connection:
        monkeypatch.setattr(
            migration,
            "op",
            Operations(MigrationContext.configure(connection)),
        )
        migration.upgrade()

    inspector = sa.inspect(engine)
    columns = {
        column["name"]: column
        for column in inspector.get_columns("medical_assistant_overviews")
    }
    assert {
        "summary_text",
        "generated_at",
        "source_latest_upload_at",
        "source_workflow_ids",
        "source_document_count",
    }.issubset(columns)
    assert columns["generated_at"]["nullable"] is False
    assert columns["source_latest_upload_at"]["nullable"] is False
    unique_indexes = {
        tuple(index["column_names"])
        for index in inspector.get_indexes("medical_assistant_overviews")
        if index["unique"]
    }
    assert ("user_id",) in unique_indexes
    foreign_keys = inspector.get_foreign_keys("medical_assistant_overviews")
    assert any(
        item["referred_table"] == "user_account"
        and item["options"].get("ondelete") == "CASCADE"
        for item in foreign_keys
    )

    candidate = _candidate_manifest()
    old = _old_0025_manifest(candidate)
    migration_path = (
        Path(__file__).resolve().parents[2]
        / "app"
        / "db"
        / "migrations"
        / "versions"
        / "0026_medical_assistant_overview.py"
    )
    plan = deploy_guard.validate_expand_migration_source(
        migration_path.read_bytes(),
        old,
        candidate,
    )
    assert plan["old_head"] == "0025_dietary_records"
    assert plan["candidate_head"] == "0026_medical_assistant"
    assert [item["revision"] for item in plan["migrations"]] == [
        "0026_medical_assistant"
    ]
    assert [item["op"] for item in plan["operations"]].count("create_table") == 1
    assert [item["op"] for item in plan["operations"]].count("create_index") == 1


def _client() -> tuple[TestClient, sessionmaker, dict[str, str], dict[str, str]]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with factory() as db:
        db.add_all(
            [
                User(id=1, phone="18800000401", username="overview-owner", password="x"),
                User(id=2, phone="18800000402", username="overview-other", password="x"),
            ]
        )
        db.commit()

    app = FastAPI()
    app.include_router(health_data.router, prefix="/api/health-data")

    def override_db() -> Iterator[Session]:
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    return (
        TestClient(app, raise_server_exceptions=False),
        factory,
        {"Authorization": f"Bearer {create_access_token('1')}"},
        {"Authorization": f"Bearer {create_access_token('2')}"},
    )


def _add_document(
    db: Session,
    *,
    user_id: int,
    title: str,
    uploaded_at: datetime,
    admitted: bool,
    report_type: str = "exam",
) -> int:
    """添加报告夹具；admitted 决定是否创建已确认工作流。"""

    document = HealthDocument(
        user_id=user_id,
        doc_type="record" if report_type == "medical_record" else "exam",
        source_type="pdf",
        name=title,
        hospital="市第一人民医院",
        doc_date=uploaded_at,
        original_file_path=f"data:base64:{title}.pdf",
        extraction_status="done" if admitted else "pending",
        created_at=uploaded_at,
    )
    db.add(document)
    db.flush()
    if admitted:
        event_id = f"confirm-overview-{user_id}-{document.id}"
        db.add(
            HealthReportWorkflow(
                user_id=user_id,
                subject_user_id=user_id,
                legacy_document_id=document.id,
                client_request_id=f"overview-upload-{user_id}-{document.id}",
                document_fingerprint=f"{user_id:02d}{document.id:062d}"[-64:],
                report_type=report_type,
                status="completed",
                version=2,
                workflow_metadata={"test": True},
                recognized_at=uploaded_at,
                confirmed_at=uploaded_at,
                confirmation_client_event_id=event_id,
                confirmed_by_user_id=user_id,
                completed_at=uploaded_at,
                created_at=uploaded_at,
                updated_at=uploaded_at,
            )
        )
    db.commit()
    return document.id


def test_medical_assistant_overview_load_generate_and_no_update_are_server_authoritative():
    client, factory, owner_headers, other_headers = _client()

    empty = client.get("/api/health-data/medical-assistant/overview", headers=owner_headers)
    assert empty.status_code == 200, empty.text
    assert empty.json()["summary"] == ""
    assert empty.json()["generated_at"] is None
    assert empty.json()["latest_report_uploaded_at"] is None

    uploaded_at = datetime.now(timezone.utc) - timedelta(hours=2)
    with factory() as db:
        document_id = _add_document(
            db,
            user_id=1,
            title="门诊病历",
            uploaded_at=uploaded_at,
            admitted=False,
            report_type="medical_record",
        )

    processing = client.post(
        "/api/health-data/medical-assistant/overview/generate",
        headers=owner_headers,
    )
    assert processing.status_code == 200, processing.text
    assert processing.json()["generation_result"] == "report_processing"
    assert processing.json()["summary"] == ""

    with factory() as db:
        stored = db.get(HealthDocument, document_id)
        stored.extraction_status = "done"
        event_id = f"confirm-overview-1-{stored.id}"
        db.add(
            HealthReportWorkflow(
                user_id=1,
                subject_user_id=1,
                legacy_document_id=stored.id,
                client_request_id=f"overview-upload-1-{stored.id}",
                document_fingerprint=f"{stored.id:064d}"[-64:],
                report_type="medical_record",
                status="completed",
                version=2,
                workflow_metadata={"test": True},
                recognized_at=uploaded_at,
                confirmed_at=uploaded_at,
                confirmation_client_event_id=event_id,
                confirmed_by_user_id=1,
                completed_at=uploaded_at,
                created_at=uploaded_at,
                updated_at=uploaded_at,
            )
        )
        db.commit()

    generated = client.post(
        "/api/health-data/medical-assistant/overview/generate",
        headers=owner_headers,
    )
    assert generated.status_code == 200, generated.text
    body = generated.json()
    assert body["generation_result"] == "generated"
    assert "门诊病历" in body["summary"]
    assert "已确认并入库" in body["summary"]
    generated_at = body["generated_at"]

    replay = client.post(
        "/api/health-data/medical-assistant/overview/generate",
        headers=owner_headers,
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["generation_result"] == "no_information_update"
    assert replay.json()["generated_at"] == generated_at

    other = client.get("/api/health-data/medical-assistant/overview", headers=other_headers)
    assert other.status_code == 200
    assert other.json()["subject_user_id"] == 2
    assert other.json()["summary"] == ""
    with factory() as db:
        assert db.scalar(
            select(MedicalAssistantOverview).where(MedicalAssistantOverview.user_id == 2)
        ) is None


def test_medical_assistant_generation_uses_only_last_year_confirmed_reports():
    _client_instance, factory, _owner_headers, _other_headers = _client()
    now = datetime(2026, 7, 24, 8, 0, tzinfo=timezone.utc)
    with factory() as db:
        _add_document(
            db,
            user_id=1,
            title="超过一年的旧报告",
            uploaded_at=now - timedelta(days=366),
            admitted=True,
        )
        _add_document(
            db,
            user_id=1,
            title="近一年体检报告",
            uploaded_at=now - timedelta(days=10),
            admitted=True,
        )
        _add_document(
            db,
            user_id=2,
            title="另一账号的一年前报告",
            uploaded_at=now - timedelta(days=366),
            admitted=True,
        )

    with factory() as db:
        result = generate_medical_assistant_overview(db, user_id=1, now=now)
        assert result["generation_result"] == "generated"
        assert result["report_count_last_year"] == 1
        assert "近一年体检报告" in result["summary"]
        assert "超过一年的旧报告" not in result["summary"]
        stored = db.scalar(
            select(MedicalAssistantOverview).where(MedicalAssistantOverview.user_id == 1)
        )
        assert stored is not None
        assert stored.generated_at.replace(tzinfo=timezone.utc) == now
        assert stored.source_document_count == 1

    with factory() as db:
        old_only = generate_medical_assistant_overview(db, user_id=2, now=now)
        assert old_only["generation_result"] == "no_reports"
        assert old_only["report_count_last_year"] == 0
        assert old_only["summary"] == ""
