"""Regression tests for the normalized health trust data contract.

These tests exercise the database boundary directly.  They intentionally do
not call report or trend routes: migration 0022 is an expand-only foundation,
and legacy OCR ``done`` rows must never become confirmed health facts merely
because the schema was upgraded.
"""

from __future__ import annotations

import importlib
import re
from datetime import datetime, timezone

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.exc import IntegrityError

from app.db.base import Base
from app.models.health_document import HealthDocument
from app.models.health_trust import (
    HEALTH_SCORE_KINDS,
    PROFILE_CANDIDATE_REVIEW_STATUSES,
    REPORT_ADMISSION_SCORE_KINDS,
    REPORT_CANDIDATE_REVIEW_STATUSES,
    REPORT_WORKFLOW_STATUSES,
    SCORE_DIRECTIONS,
    SCORE_SEMANTIC_OUTCOMES,
    ConfirmedHealthObservation,
    HealthProfileCandidate,
    HealthProfileFact,
    HealthProfileRevision,
    HealthProfileSource,
    HealthReportConfirmationEvent,
    HealthReportFieldCandidate,
    HealthReportWorkflow,
    HealthScoreSnapshot,
)
from app.models.user import User


MIGRATION_MODULE = "app.db.migrations.versions.0022_health_trust_contracts"
NOW = datetime(2026, 7, 15, 8, 30, tzinfo=timezone.utc)

TRUST_MODELS = (
    HealthReportWorkflow,
    HealthReportFieldCandidate,
    HealthReportConfirmationEvent,
    ConfirmedHealthObservation,
    HealthProfileFact,
    HealthProfileCandidate,
    HealthProfileSource,
    HealthProfileRevision,
    HealthScoreSnapshot,
)


def _contract_engine() -> sa.Engine:
    engine = sa.create_engine("sqlite:///:memory:")

    @sa.event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(
        engine,
        tables=[
            User.__table__,
            HealthDocument.__table__,
            *(model.__table__ for model in TRUST_MODELS),
        ],
    )
    return engine


def _seed_users_and_legacy_document(engine: sa.Engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            User.__table__.insert(),
            [
                {"id": 1, "phone": "13000000001", "username": "owner", "password": "x"},
                {"id": 2, "phone": "13000000002", "username": "subject", "password": "x"},
                {"id": 3, "phone": "13000000003", "username": "other", "password": "x"},
            ],
        )
        connection.execute(
            HealthDocument.__table__.insert().values(
                id=100,
                user_id=1,
                doc_type="exam",
                source_type="pdf",
                name="legacy-done-report",
                extraction_status="done",
            )
        )


def _expect_integrity_error(engine: sa.Engine, statement) -> None:
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(statement)


def _workflow_values(
    *,
    workflow_id: int,
    client_request_id: str,
    user_id: int = 1,
    subject_user_id: int = 2,
    status: str = "awaiting_confirmation",
    document_fingerprint: str | None = None,
    confirmed: bool = False,
) -> dict:
    values = {
        "id": workflow_id,
        "user_id": user_id,
        "subject_user_id": subject_user_id,
        "legacy_document_id": 100,
        "client_request_id": client_request_id,
        "document_fingerprint": document_fingerprint,
        "report_type": "exam",
        "status": status,
    }
    if confirmed:
        values.update(
            confirmed_at=NOW,
            confirmation_client_event_id=f"confirm-{client_request_id}",
            confirmed_by_user_id=user_id,
        )
    return values


def _candidate_values(
    *,
    candidate_id: int,
    candidate_key: str,
    workflow_id: int = 10,
    user_id: int = 1,
    subject_user_id: int = 2,
    review_status: str = "pending_review",
    abnormal_state: str = "unknown",
    requires_review: bool = True,
) -> dict:
    return {
        "id": candidate_id,
        "workflow_id": workflow_id,
        "user_id": user_id,
        "subject_user_id": subject_user_id,
        "candidate_key": candidate_key,
        "canonical_code": "lab.glucose",
        "canonical_name": "空腹血糖",
        "raw_name": "血糖",
        "raw_value": "5.6",
        "normalized_value": 5.6,
        "normalized_unit": "mmol/L",
        "abnormal_state": abnormal_state,
        "review_status": review_status,
        "requires_review": requires_review,
    }


def _confirmation_event_values(
    *,
    event_id: int,
    candidate_id: int,
    client_event_id: str,
    workflow_id: int = 10,
    user_id: int = 1,
    subject_user_id: int = 2,
) -> dict:
    return {
        "id": event_id,
        "workflow_id": workflow_id,
        "candidate_id": candidate_id,
        "user_id": user_id,
        "subject_user_id": subject_user_id,
        "actor_user_id": user_id,
        "client_event_id": client_event_id,
        "event_type": "confirm",
        "candidate_version": 1,
    }


def _observation_values(
    *,
    observation_id: int,
    candidate_id: int,
    event_id: int,
    idempotency_key: str,
    value_numeric: float | None = 5.6,
    value_text: str | None = None,
) -> dict:
    return {
        "id": observation_id,
        "workflow_id": 10,
        "source_candidate_id": candidate_id,
        "confirmation_event_id": event_id,
        "user_id": 1,
        "subject_user_id": 2,
        "report_confirmation_client_event_id": "confirm-request-1",
        "idempotency_key": idempotency_key,
        "canonical_code": "lab.glucose",
        "canonical_name": "空腹血糖",
        "value_numeric": value_numeric,
        "value_text": value_text,
        "unit": "mmol/L",
        "abnormal_state": "normal",
        "effective_at": NOW,
        "confirmed_by_user_id": 1,
        "confirmed_at": NOW,
    }


def test_report_contract_enforces_tenant_owner_idempotency_and_confirmation():
    assert REPORT_WORKFLOW_STATUSES == (
        "draft",
        "uploading",
        "recognizing",
        "awaiting_confirmation",
        "committing",
        "completed",
        "completed_score_pending",
        "failed",
    )
    assert REPORT_CANDIDATE_REVIEW_STATUSES == (
        "pending_review",
        "auto_accepted",
        "confirmed",
        "corrected",
        "rejected",
    )

    engine = _contract_engine()
    _seed_users_and_legacy_document(engine)
    workflow = HealthReportWorkflow.__table__
    candidate = HealthReportFieldCandidate.__table__
    event = HealthReportConfirmationEvent.__table__
    observation = ConfirmedHealthObservation.__table__

    with engine.begin() as connection:
        connection.execute(
            workflow.insert().values(
                **_workflow_values(
                    workflow_id=10,
                    client_request_id="request-1",
                    document_fingerprint="a" * 64,
                )
            )
        )

    # The legacy document owner is part of the FK, so knowing another user's
    # document id cannot attach it to a different tenant workflow.
    _expect_integrity_error(
        engine,
        workflow.insert().values(
            **_workflow_values(
                workflow_id=11,
                client_request_id="wrong-owner",
                user_id=3,
            )
        ),
    )
    _expect_integrity_error(
        engine,
        workflow.insert().values(
            **_workflow_values(
                workflow_id=12,
                client_request_id="request-1",
                document_fingerprint="b" * 64,
            )
        ),
    )
    _expect_integrity_error(
        engine,
        workflow.insert().values(
            **_workflow_values(
                workflow_id=13,
                client_request_id="request-2",
                document_fingerprint="a" * 64,
            )
        ),
    )
    _expect_integrity_error(
        engine,
        workflow.insert().values(
            **_workflow_values(
                workflow_id=14,
                client_request_id="unconfirmed-complete",
                status="completed",
            )
        ),
    )
    partial_confirmation = _workflow_values(
        workflow_id=15,
        client_request_id="partial-confirmation",
        status="committing",
    )
    partial_confirmation["confirmed_at"] = NOW
    _expect_integrity_error(
        engine,
        workflow.insert().values(**partial_confirmation),
    )
    with engine.begin() as connection:
        connection.execute(
            workflow.insert().values(
                **_workflow_values(
                    workflow_id=16,
                    client_request_id="complete",
                    status="completed",
                    confirmed=True,
                )
            )
        )

    with engine.begin() as connection:
        connection.execute(
            candidate.insert().values(
                **_candidate_values(candidate_id=20, candidate_key="glucose")
            )
        )
    _expect_integrity_error(
        engine,
        candidate.insert().values(
            **_candidate_values(
                candidate_id=21,
                candidate_key="cross-tenant",
                user_id=3,
            )
        ),
    )
    _expect_integrity_error(
        engine,
        candidate.insert().values(
            **_candidate_values(
                candidate_id=22,
                candidate_key="unsafe-auto",
                review_status="auto_accepted",
                abnormal_state="abnormal",
                requires_review=False,
            )
        ),
    )
    with engine.begin() as connection:
        connection.execute(
            candidate.insert().values(
                **_candidate_values(
                    candidate_id=22,
                    candidate_key="safe-auto",
                    review_status="auto_accepted",
                    abnormal_state="normal",
                    requires_review=False,
                )
            )
        )

    with engine.begin() as connection:
        connection.execute(
            event.insert().values(
                **_confirmation_event_values(
                    event_id=30,
                    candidate_id=20,
                    client_event_id="candidate-confirm-1",
                )
            )
        )
        connection.execute(
            event.insert().values(
                **_confirmation_event_values(
                    event_id=31,
                    candidate_id=22,
                    client_event_id="candidate-confirm-2",
                )
            )
        )
    _expect_integrity_error(
        engine,
        event.insert().values(
            **_confirmation_event_values(
                event_id=32,
                candidate_id=20,
                client_event_id="cross-tenant-event",
                user_id=3,
            )
        ),
    )

    # Candidate confirmation is necessary but insufficient: admission must
    # also reference the report-level confirmation recorded on its workflow.
    _expect_integrity_error(
        engine,
        observation.insert().values(
            **_observation_values(
                observation_id=40,
                candidate_id=20,
                event_id=30,
                idempotency_key="observation-before-report-confirmation",
            )
        ),
    )
    with engine.begin() as connection:
        connection.execute(
            workflow.update()
            .where(workflow.c.id == 10)
            .values(
                status="committing",
                confirmed_at=NOW,
                confirmation_client_event_id="confirm-request-1",
                confirmed_by_user_id=1,
            )
        )

    _expect_integrity_error(
        engine,
        observation.insert().values(
            **_observation_values(
                observation_id=40,
                candidate_id=20,
                event_id=30,
                idempotency_key="observation-1",
                value_numeric=5.6,
                value_text="five point six",
            )
        ),
    )
    with engine.begin() as connection:
        connection.execute(
            observation.insert().values(
                **_observation_values(
                    observation_id=40,
                    candidate_id=20,
                    event_id=30,
                    idempotency_key="observation-1",
                )
            )
        )
    _expect_integrity_error(
        engine,
        observation.insert().values(
            **_observation_values(
                observation_id=41,
                candidate_id=22,
                event_id=31,
                idempotency_key="observation-1",
            )
        ),
    )


def test_profile_contract_rejects_automatic_safety_and_invalid_conflicts():
    assert PROFILE_CANDIDATE_REVIEW_STATUSES == (
        "pending_review",
        "accepted",
        "rejected",
        "superseded",
        "conflict",
    )

    engine = _contract_engine()
    _seed_users_and_legacy_document(engine)
    fact = HealthProfileFact.__table__
    candidate = HealthProfileCandidate.__table__
    source = HealthProfileSource.__table__
    revision = HealthProfileRevision.__table__

    with engine.begin() as connection:
        connection.execute(
            fact.insert().values(
                id=50,
                user_id=1,
                subject_user_id=2,
                fact_key="preference.sleep_goal",
                category="preference",
                value_data={"hours": 8},
                is_safety_critical=False,
                confirmation_method="automatic",
            )
        )

    _expect_integrity_error(
        engine,
        fact.insert().values(
            id=51,
            user_id=1,
            subject_user_id=2,
            fact_key="allergy.penicillin",
            category="allergy",
            value_data={"substance": "penicillin"},
            is_safety_critical=True,
            confirmation_method="automatic",
        ),
    )
    _expect_integrity_error(
        engine,
        fact.insert().values(
            id=51,
            user_id=1,
            subject_user_id=2,
            fact_key="allergy.penicillin",
            category="allergy",
            value_data={"substance": "penicillin"},
            is_safety_critical=True,
            confirmation_method="user",
            confirmed_by_user_id=1,
        ),
    )
    with engine.begin() as connection:
        connection.execute(
            fact.insert().values(
                id=51,
                user_id=1,
                subject_user_id=2,
                fact_key="allergy.penicillin",
                category="allergy",
                value_data={"substance": "penicillin"},
                is_safety_critical=True,
                confirmation_method="user",
                confirmed_by_user_id=1,
                confirmed_at=NOW,
            )
        )

    base_candidate = {
        "id": 60,
        "user_id": 1,
        "subject_user_id": 2,
        "fact_key": "allergy.penicillin",
        "category": "allergy",
        "proposed_value": {"substance": "amoxicillin"},
        "is_safety_critical": True,
        "idempotency_key": "profile-candidate-1",
    }
    _expect_integrity_error(
        engine,
        candidate.insert().values(**base_candidate, review_status="conflict"),
    )
    _expect_integrity_error(
        engine,
        candidate.insert().values(
            **base_candidate,
            review_status="pending_review",
            conflict_with_fact_id=51,
        ),
    )
    with engine.begin() as connection:
        connection.execute(
            candidate.insert().values(
                **base_candidate,
                review_status="conflict",
                conflict_with_fact_id=51,
            )
        )
    _expect_integrity_error(
        engine,
        candidate.insert().values(
            id=61,
            user_id=3,
            subject_user_id=2,
            fact_key="allergy.penicillin",
            category="allergy",
            proposed_value={"substance": "amoxicillin"},
            is_safety_critical=True,
            review_status="conflict",
            conflict_with_fact_id=51,
            idempotency_key="cross-tenant-conflict",
        ),
    )
    _expect_integrity_error(
        engine,
        candidate.insert().values(
            id=61,
            user_id=1,
            subject_user_id=2,
            fact_key="allergy.other",
            category="allergy",
            proposed_value={"substance": "other"},
            is_safety_critical=True,
            review_status="pending_review",
            idempotency_key="profile-candidate-1",
        ),
    )

    _expect_integrity_error(
        engine,
        source.insert().values(
            id=70,
            user_id=1,
            subject_user_id=2,
            fact_id=51,
            candidate_id=60,
            source_type="manual",
            source_ref="profile-review",
            idempotency_key="profile-source-1",
        ),
    )
    with engine.begin() as connection:
        connection.execute(
            source.insert().values(
                id=70,
                user_id=1,
                subject_user_id=2,
                fact_id=51,
                source_type="manual",
                source_ref="profile-review",
                idempotency_key="profile-source-1",
            )
        )

    _expect_integrity_error(
        engine,
        revision.insert().values(
            id=80,
            user_id=1,
            subject_user_id=2,
            fact_id=51,
            candidate_id=60,
            actor_user_id=1,
            client_event_id="profile-revision-1",
            event_type="confirm",
            target_version=1,
        ),
    )
    with engine.begin() as connection:
        connection.execute(
            revision.insert().values(
                id=80,
                user_id=1,
                subject_user_id=2,
                candidate_id=60,
                actor_user_id=1,
                client_event_id="profile-revision-1",
                event_type="confirm",
                target_version=1,
            )
        )


def test_score_snapshot_requires_direction_and_semantic_outcome():
    assert SCORE_DIRECTIONS == (
        "higher_is_better",
        "lower_is_better",
        "target_range",
        "informational",
    )
    assert SCORE_SEMANTIC_OUTCOMES == (
        "improved",
        "worsened",
        "unchanged",
        "unknown",
    )
    assert HEALTH_SCORE_KINDS == ("stress", "recovery", "inflammation", "x_age")
    assert REPORT_ADMISSION_SCORE_KINDS == {"stress", "recovery", "inflammation"}
    assert "x_age" not in REPORT_ADMISSION_SCORE_KINDS

    engine = _contract_engine()
    _seed_users_and_legacy_document(engine)
    workflow = HealthReportWorkflow.__table__
    snapshot = HealthScoreSnapshot.__table__
    with engine.begin() as connection:
        connection.execute(
            workflow.insert().values(
                **_workflow_values(
                    workflow_id=10,
                    client_request_id="score-report",
                    status="completed",
                    confirmed=True,
                )
            )
        )

    base_snapshot = {
        "id": 90,
        "user_id": 1,
        "subject_user_id": 2,
        "source_report_workflow_id": 10,
        "idempotency_key": "score-snapshot-1",
        "score_kind": "stress",
        "algorithm_id": "stress-score",
        "algorithm_version": "1.0.0",
        "before_value": 62,
        "after_value": 55,
        "calculation_status": "completed",
    }
    _expect_integrity_error(
        engine,
        snapshot.insert().values(**base_snapshot),
    )
    _expect_integrity_error(
        engine,
        snapshot.insert().values(
            **base_snapshot,
            score_direction="sideways",
            semantic_outcome="improved",
        ),
    )
    with engine.begin() as connection:
        connection.execute(
            snapshot.insert().values(
                **base_snapshot,
                score_direction="lower_is_better",
                semantic_outcome="improved",
            )
        )
    _expect_integrity_error(
        engine,
        snapshot.insert().values(
            id=91,
            user_id=3,
            subject_user_id=2,
            source_report_workflow_id=10,
            idempotency_key="cross-tenant-score",
            score_kind="recovery",
            algorithm_id="recovery-score",
            algorithm_version="1.0.0",
            calculation_status="pending",
        ),
    )
    _expect_integrity_error(
        engine,
        snapshot.insert().values(
            id=92,
            user_id=1,
            subject_user_id=2,
            source_report_workflow_id=10,
            idempotency_key="score-snapshot-1",
            score_kind="recovery",
            algorithm_id="recovery-score",
            algorithm_version="1.0.0",
            calculation_status="pending",
        ),
    )


def _run_migration(connection, monkeypatch, name: str) -> None:
    migration = importlib.import_module(MIGRATION_MODULE)
    operations = Operations(MigrationContext.configure(connection))
    monkeypatch.setattr(migration, "op", operations)
    getattr(migration, name)()


def _normalize_sql(value) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    while normalized.startswith("(") and normalized.endswith(")"):
        normalized = normalized[1:-1].strip()
    if len(normalized) >= 2 and normalized[0] == normalized[-1] == "'":
        normalized = normalized[1:-1]
    normalized = re.sub(r"\s+", "", normalized)
    aliases = {
        "true": "1",
        "false": "0",
        "now()": "current_timestamp",
    }
    return aliases.get(normalized, normalized)


def _model_server_default(column: sa.Column, dialect) -> str | None:
    if column.server_default is None:
        return None
    argument = column.server_default.arg
    if hasattr(argument, "compile"):
        argument = argument.compile(
            dialect=dialect,
            compile_kwargs={"literal_binds": True},
        )
    return _normalize_sql(argument)


def _model_foreign_keys(table: sa.Table) -> set[tuple]:
    return {
        (
            constraint.name,
            tuple(column.name for column in constraint.columns),
            constraint.referred_table.name,
            tuple(element.column.name for element in constraint.elements),
            (constraint.ondelete or "").upper(),
        )
        for constraint in table.foreign_key_constraints
    }


def _inspected_foreign_keys(inspector, table_name: str) -> set[tuple]:
    return {
        (
            constraint["name"],
            tuple(constraint["constrained_columns"]),
            constraint["referred_table"],
            tuple(constraint["referred_columns"]),
            (constraint.get("options", {}).get("ondelete") or "").upper(),
        )
        for constraint in inspector.get_foreign_keys(table_name)
    }


def _assert_migrated_table_matches_model(
    engine: sa.Engine,
    inspector,
    model_table: sa.Table,
    *,
    post_migration_unique_names: frozenset[str] = frozenset(),
    post_migration_index_names: frozenset[str] = frozenset(),
) -> None:
    table_name = model_table.name
    inspected_columns = {
        column["name"]: column for column in inspector.get_columns(table_name)
    }
    assert set(inspected_columns) == {column.name for column in model_table.columns}
    for model_column in model_table.columns:
        inspected = inspected_columns[model_column.name]
        assert inspected["nullable"] == model_column.nullable
        assert inspected["primary_key"] == model_column.primary_key
        assert (
            inspected["type"].compile(dialect=engine.dialect).lower()
            == model_column.type.compile(dialect=engine.dialect).lower()
        )
        assert _normalize_sql(inspected["default"]) == _model_server_default(
            model_column,
            engine.dialect,
        )

    model_uniques = {
        constraint.name: tuple(column.name for column in constraint.columns)
        for constraint in model_table.constraints
        if isinstance(constraint, sa.UniqueConstraint)
        and constraint.name not in post_migration_unique_names
    }
    inspected_uniques = {
        constraint["name"]: tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints(table_name)
    }
    assert inspected_uniques == model_uniques

    model_checks = {
        constraint.name: _normalize_sql(constraint.sqltext)
        for constraint in model_table.constraints
        if isinstance(constraint, sa.CheckConstraint)
    }
    inspected_checks = {
        constraint["name"]: _normalize_sql(constraint["sqltext"])
        for constraint in inspector.get_check_constraints(table_name)
    }
    assert inspected_checks == model_checks

    model_indexes = {
        index.name: tuple(column.name for column in index.columns)
        for index in model_table.indexes
        if index.name not in post_migration_index_names
    }
    inspected_indexes = {
        index["name"]: tuple(index["column_names"])
        for index in inspector.get_indexes(table_name)
    }
    assert inspected_indexes == model_indexes
    assert _inspected_foreign_keys(inspector, table_name) == _model_foreign_keys(
        model_table
    )


def test_0022_migration_is_expand_only_without_legacy_backfill_and_matches_models(
    monkeypatch,
):
    migration = importlib.import_module(MIGRATION_MODULE)
    assert migration.revision == "0022_health_trust_contracts"
    assert migration.down_revision == "0021_device_indicator_identity"

    engine = sa.create_engine("sqlite:///:memory:")

    @sa.event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    metadata = sa.MetaData()
    users = sa.Table(
        "user_account",
        metadata,
        sa.Column("id", sa.BigInteger(), primary_key=True),
    )
    legacy_documents = sa.Table(
        "health_documents",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("extraction_status", sa.String(length=16), nullable=False),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(users.insert().values(id=1))
        connection.execute(
            legacy_documents.insert().values(
                id=100,
                user_id=1,
                extraction_status="done",
            )
        )
        _run_migration(connection, monkeypatch, "upgrade")

    inspector = sa.inspect(engine)
    expected_tables = {model.__table__.name for model in TRUST_MODELS}
    assert expected_tables.issubset(inspector.get_table_names())
    assert {
        constraint["name"]
        for constraint in inspector.get_unique_constraints("health_documents")
    } == {"uq_health_documents_id_user"}
    workflows = sa.Table(
        "health_report_workflows",
        sa.MetaData(),
        autoload_with=engine,
    )
    migrated_legacy = sa.Table(
        "health_documents",
        sa.MetaData(),
        autoload_with=engine,
    )
    with engine.connect() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(workflows)) == 0
        legacy_row = connection.execute(sa.select(migrated_legacy)).mappings().one()
    assert legacy_row["extraction_status"] == "done"

    post_0022_uniques = {
        "health_profile_sources": frozenset({"uq_profile_source_tenant_id"}),
        "health_score_snapshots": frozenset(
            {"uq_score_snapshot_workflow_tenant_id"}
        ),
    }
    post_0022_indexes = {
        "health_profile_revisions": frozenset(
            {
                "ix_profile_revision_fact_history",
                "ix_profile_revision_candidate_history",
            }
        ),
    }
    for model in TRUST_MODELS:
        table_name = model.__table__.name
        _assert_migrated_table_matches_model(
            engine,
            inspector,
            model.__table__,
            post_migration_unique_names=post_0022_uniques.get(
                table_name,
                frozenset(),
            ),
            post_migration_index_names=post_0022_indexes.get(
                table_name,
                frozenset(),
            ),
        )

    with engine.begin() as connection:
        _run_migration(connection, monkeypatch, "downgrade")

    downgraded_inspector = sa.inspect(engine)
    assert expected_tables.isdisjoint(downgraded_inspector.get_table_names())
    assert downgraded_inspector.get_unique_constraints("health_documents") == []
    downgraded_legacy = sa.Table(
        "health_documents",
        sa.MetaData(),
        autoload_with=engine,
    )
    with engine.connect() as connection:
        legacy_row = connection.execute(sa.select(downgraded_legacy)).mappings().one()
    assert legacy_row["id"] == 100
    assert legacy_row["extraction_status"] == "done"
