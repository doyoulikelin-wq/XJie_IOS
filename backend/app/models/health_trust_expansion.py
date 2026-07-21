"""Additive contracts that complete trusted profile and report workflows.

The objects in this module deliberately extend the 0022/0023 trust boundary
without changing the meaning of any legacy row.  Device measurements, goals,
report assets, duplicate decisions, score jobs, and follow-up items all keep
their own tenant-bound identities and audit trails.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text as sa_text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.compat import JSONB


class TrustedDeviceProfileObservation(Base):
    """Immutable, versioned snapshot of one whitelisted device measurement."""

    __tablename__ = "trusted_device_profile_observations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_indicator_value_id", "user_id"],
            ["user_indicator_values.id", "user_indicator_values.user_id"],
            name="fk_device_profile_observation_indicator_owner",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "id", "user_id", "subject_user_id", name="uq_device_profile_observation_tenant_id"
        ),
        UniqueConstraint(
            "user_id",
            "subject_user_id",
            "idempotency_key",
            name="uq_device_profile_observation_tenant_idempotency",
        ),
        UniqueConstraint(
            "user_id",
            "subject_user_id",
            "user_indicator_value_id",
            "version",
            name="uq_device_profile_observation_source_version",
        ),
        UniqueConstraint(
            "user_id",
            "subject_user_id",
            "user_indicator_value_id",
            "active_slot",
            name="uq_device_profile_observation_active_source",
        ),
        CheckConstraint(
            "value_numeric IS NOT NULL AND value_text IS NULL",
            name="ck_device_profile_observation_has_value",
        ),
        CheckConstraint(
            "user_id = subject_user_id",
            name="ck_device_profile_observation_self_subject",
        ),
        CheckConstraint(
            "fact_key IN ('basic.height', 'basic.weight')",
            name="ck_device_profile_observation_fact_key",
        ),
        CheckConstraint(
            "metric_mapping_version = 'device-profile.height-weight.v1'",
            name="ck_device_profile_observation_mapping_version",
        ),
        CheckConstraint(
            "(fact_key = 'basic.height' AND unit = 'cm' "
            "AND value_numeric >= 30 AND value_numeric <= 300) OR "
            "(fact_key = 'basic.weight' AND unit = 'kg' "
            "AND value_numeric >= 1 AND value_numeric <= 500)",
            name="ck_device_profile_observation_value_domain",
        ),
        CheckConstraint(
            "status IN ('active', 'superseded', 'retracted')",
            name="ck_device_profile_observation_status",
        ),
        CheckConstraint(
            "(status = 'active' AND active_slot = 1) OR "
            "(status IN ('superseded', 'retracted') AND active_slot IS NULL)",
            name="ck_device_profile_observation_active_slot",
        ),
        CheckConstraint("version >= 1", name="ck_device_profile_observation_version"),
        Index(
            "ix_device_profile_observation_subject_fact_time",
            "user_id",
            "subject_user_id",
            "fact_key",
            "effective_at",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="CASCADE"), nullable=False
    )
    subject_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="CASCADE"), nullable=False
    )
    user_indicator_value_id: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(96), nullable=False)
    source_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    metric_mapping_version: Mapped[str] = mapped_column(String(80), nullable=False)
    fact_key: Mapped[str] = mapped_column(String(128), nullable=False)
    value_numeric: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    value_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_snapshot: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=sa_text("'{}'")
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default="active"
    )
    active_slot: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=1, server_default="1"
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class HealthProfileFactSourceVersion(Base):
    """Append-only source set for one exact confirmed fact version."""

    __tablename__ = "health_profile_fact_source_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["fact_id", "user_id", "subject_user_id"],
            [
                "health_profile_facts.id",
                "health_profile_facts.user_id",
                "health_profile_facts.subject_user_id",
            ],
            name="fk_profile_fact_source_version_fact_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["profile_source_id", "user_id", "subject_user_id"],
            [
                "health_profile_sources.id",
                "health_profile_sources.user_id",
                "health_profile_sources.subject_user_id",
            ],
            name="fk_profile_fact_source_version_source_tenant",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "fact_id",
            "user_id",
            "subject_user_id",
            "fact_version",
            "source_identity",
            name="uq_profile_fact_source_version_identity",
        ),
        CheckConstraint("fact_version >= 1", name="ck_profile_fact_source_version_positive"),
        Index(
            "ix_profile_fact_source_version_current",
            "user_id",
            "subject_user_id",
            "fact_id",
            "fact_version",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fact_id: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    subject_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    fact_version: Mapped[int] = mapped_column(Integer, nullable=False)
    profile_source_id: Mapped[int] = mapped_column(Integer, nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_identity: Mapped[str] = mapped_column(String(192), nullable=False)
    source_snapshot: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=sa_text("'{}'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class HealthProfileDeviceSourceLink(Base):
    """Tenant-bound edge proving which immutable device snapshot supports a source."""

    __tablename__ = "health_profile_device_source_links"
    __table_args__ = (
        ForeignKeyConstraint(
            ["profile_source_id", "user_id", "subject_user_id"],
            [
                "health_profile_sources.id",
                "health_profile_sources.user_id",
                "health_profile_sources.subject_user_id",
            ],
            name="fk_profile_device_source_link_source_tenant",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["device_observation_id", "user_id", "subject_user_id"],
            [
                "trusted_device_profile_observations.id",
                "trusted_device_profile_observations.user_id",
                "trusted_device_profile_observations.subject_user_id",
            ],
            name="fk_profile_device_source_link_observation_tenant",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "profile_source_id",
            "user_id",
            "subject_user_id",
            name="uq_profile_device_source_link_source",
        ),
        UniqueConstraint(
            "device_observation_id",
            "profile_source_id",
            "user_id",
            "subject_user_id",
            name="uq_profile_device_source_link_pair",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_source_id: Mapped[int] = mapped_column(Integer, nullable=False)
    device_observation_id: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    subject_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class HealthProfileGoal(Base):
    """User-created goal; AI and extracted candidates cannot create rows here."""

    __tablename__ = "health_profile_goals"
    __table_args__ = (
        UniqueConstraint("id", "user_id", "subject_user_id", name="uq_profile_goal_tenant_id"),
        UniqueConstraint(
            "user_id",
            "subject_user_id",
            "creation_client_event_id",
            name="uq_profile_goal_tenant_creation_event",
        ),
        CheckConstraint(
            "status IN ('active', 'paused', 'completed', 'archived')",
            name="ck_profile_goal_status",
        ),
        CheckConstraint("version >= 1", name="ck_profile_goal_version"),
        CheckConstraint("length(name) > 0", name="ck_profile_goal_name_nonempty"),
        Index(
            "ix_profile_goal_subject_status",
            "user_id",
            "subject_user_id",
            "status",
            "started_on",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="CASCADE"), nullable=False
    )
    subject_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="CASCADE"), nullable=False
    )
    creation_client_event_id: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default="active"
    )
    started_on: Mapped[date] = mapped_column(Date, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    confirmed_by_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="RESTRICT"), nullable=False
    )
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class HealthProfileGoalMetric(Base):
    """Stable metric association for a user-created health goal."""

    __tablename__ = "health_profile_goal_metrics"
    __table_args__ = (
        ForeignKeyConstraint(
            ["goal_id", "user_id", "subject_user_id"],
            [
                "health_profile_goals.id",
                "health_profile_goals.user_id",
                "health_profile_goals.subject_user_id",
            ],
            name="fk_profile_goal_metric_goal_tenant",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "goal_id",
            "user_id",
            "subject_user_id",
            "metric_key",
            name="uq_profile_goal_metric_key",
        ),
        CheckConstraint("length(metric_key) > 0", name="ck_profile_goal_metric_nonempty"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    goal_id: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    subject_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    metric_key: Mapped[str] = mapped_column(String(128), nullable=False)
    display_label: Mapped[str | None] = mapped_column(String(160), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class HealthProfileGoalRevision(Base):
    """Append-only audit event for goal creation, editing, and archival."""

    __tablename__ = "health_profile_goal_revisions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["goal_id", "user_id", "subject_user_id"],
            [
                "health_profile_goals.id",
                "health_profile_goals.user_id",
                "health_profile_goals.subject_user_id",
            ],
            name="fk_profile_goal_revision_goal_tenant",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "user_id",
            "subject_user_id",
            "client_event_id",
            name="uq_profile_goal_revision_tenant_event",
        ),
        UniqueConstraint(
            "goal_id",
            "user_id",
            "subject_user_id",
            "target_version",
            name="uq_profile_goal_revision_target_version",
        ),
        CheckConstraint(
            "event_type IN ('create', 'update', 'status_change', 'archive')",
            name="ck_profile_goal_revision_event_type",
        ),
        CheckConstraint("target_version >= 1", name="ck_profile_goal_revision_version"),
        Index(
            "ix_profile_goal_revision_history",
            "user_id",
            "subject_user_id",
            "goal_id",
            "target_version",
            "id",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    goal_id: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    subject_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    actor_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="RESTRICT"), nullable=False
    )
    client_event_id: Mapped[str] = mapped_column(String(80), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(24), nullable=False)
    target_version: Mapped[int] = mapped_column(Integer, nullable=False)
    before_data: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=sa_text("'{}'")
    )
    after_data: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=sa_text("'{}'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class HealthReportAssetSet(Base):
    """Upload session that preserves ordered originals before workflow creation."""

    __tablename__ = "health_report_asset_sets"
    __table_args__ = (
        UniqueConstraint("id", "user_id", "subject_user_id", name="uq_report_asset_set_tenant_id"),
        UniqueConstraint(
            "user_id",
            "subject_user_id",
            "client_request_id",
            name="uq_report_asset_set_tenant_request",
        ),
        CheckConstraint(
            "media_kind IN ('camera', 'photo_library', 'pdf', 'csv', 'legacy')",
            name="ck_report_asset_set_media_kind",
        ),
        CheckConstraint(
            "status IN ('open', 'sealed', 'attached', 'rejected', 'retracted')",
            name="ck_report_asset_set_status",
        ),
        CheckConstraint(
            "expected_page_count IS NULL OR expected_page_count >= 1",
            name="ck_report_asset_set_expected_pages",
        ),
        CheckConstraint(
            "status = 'open' OR expected_page_count IS NOT NULL",
            name="ck_report_asset_set_sealed_expected_pages",
        ),
        CheckConstraint("received_asset_count >= 0", name="ck_report_asset_set_received_assets"),
        CheckConstraint(
            "completeness_basis IS NULL OR completeness_basis IN "
            "('user_declared', 'pdf_page_count', 'ocr_page_numbers', 'legacy')",
            name="ck_report_asset_set_completeness_basis",
        ),
        Index(
            "ix_report_asset_set_aggregate_digest",
            "user_id",
            "subject_user_id",
            "aggregate_sha256",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="CASCADE"), nullable=False
    )
    subject_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="CASCADE"), nullable=False
    )
    client_request_id: Mapped[str] = mapped_column(String(80), nullable=False)
    media_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="open", server_default="open"
    )
    expected_page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    received_asset_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    completeness_basis: Mapped[str | None] = mapped_column(String(32), nullable=True)
    aggregate_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    original_summary: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=sa_text("'{}'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    sealed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class HealthReportAsset(Base):
    """One immutable user-supplied original (an image, PDF, or CSV)."""

    __tablename__ = "health_report_assets"
    __table_args__ = (
        ForeignKeyConstraint(
            ["asset_set_id", "user_id", "subject_user_id"],
            [
                "health_report_asset_sets.id",
                "health_report_asset_sets.user_id",
                "health_report_asset_sets.subject_user_id",
            ],
            name="fk_report_asset_set_tenant",
            ondelete="CASCADE",
        ),
        UniqueConstraint("id", "user_id", "subject_user_id", name="uq_report_asset_tenant_id"),
        UniqueConstraint(
            "id",
            "asset_set_id",
            "user_id",
            "subject_user_id",
            name="uq_report_asset_set_asset_tenant_id",
        ),
        UniqueConstraint(
            "asset_set_id",
            "user_id",
            "subject_user_id",
            "asset_index",
            name="uq_report_asset_set_page",
        ),
        UniqueConstraint(
            "asset_set_id",
            "user_id",
            "subject_user_id",
            "client_asset_id",
            name="uq_report_asset_set_client_asset",
        ),
        CheckConstraint("asset_index >= 1", name="ck_report_asset_index"),
        CheckConstraint("byte_size >= 0", name="ck_report_asset_byte_size"),
        CheckConstraint(
            "ingest_status IN ('uploaded', 'accepted', 'rejected')",
            name="ck_report_asset_ingest_status",
        ),
        Index("ix_report_asset_set_order", "user_id", "subject_user_id", "asset_set_id", "asset_index"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_set_id: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    subject_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    asset_index: Mapped[int] = mapped_column(Integer, nullable=False)
    client_asset_id: Mapped[str] = mapped_column(String(80), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(256), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    byte_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    width_px: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height_px: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ingest_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="uploaded", server_default="uploaded"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class HealthReportAssetSetWorkflowLink(Base):
    """One-way attachment created only after exact-byte duplicate checks pass."""

    __tablename__ = "health_report_asset_set_workflow_links"
    __table_args__ = (
        ForeignKeyConstraint(
            ["asset_set_id", "user_id", "subject_user_id"],
            [
                "health_report_asset_sets.id",
                "health_report_asset_sets.user_id",
                "health_report_asset_sets.subject_user_id",
            ],
            name="fk_report_asset_set_link_set_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workflow_id", "user_id", "subject_user_id"],
            [
                "health_report_workflows.id",
                "health_report_workflows.user_id",
                "health_report_workflows.subject_user_id",
            ],
            name="fk_report_asset_set_link_workflow_tenant",
            ondelete="CASCADE",
        ),
        UniqueConstraint("asset_set_id", "user_id", "subject_user_id", name="uq_report_asset_set_link_set"),
        UniqueConstraint("workflow_id", "user_id", "subject_user_id", name="uq_report_asset_set_link_workflow"),
        UniqueConstraint(
            "asset_set_id",
            "workflow_id",
            "user_id",
            "subject_user_id",
            name="uq_report_asset_set_link_pair",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_set_id: Mapped[int] = mapped_column(Integer, nullable=False)
    workflow_id: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    subject_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class HealthReportPage(Base):
    """Logical page rendered from an original PDF or represented by an image."""

    __tablename__ = "health_report_pages"
    __table_args__ = (
        ForeignKeyConstraint(
            ["asset_set_id", "user_id", "subject_user_id"],
            [
                "health_report_asset_sets.id",
                "health_report_asset_sets.user_id",
                "health_report_asset_sets.subject_user_id",
            ],
            name="fk_report_page_set_tenant",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["source_asset_id", "asset_set_id", "user_id", "subject_user_id"],
            [
                "health_report_assets.id",
                "health_report_assets.asset_set_id",
                "health_report_assets.user_id",
                "health_report_assets.subject_user_id",
            ],
            name="fk_report_page_asset_tenant",
            ondelete="CASCADE",
        ),
        UniqueConstraint("id", "user_id", "subject_user_id", name="uq_report_page_tenant_id"),
        UniqueConstraint(
            "id",
            "asset_set_id",
            "user_id",
            "subject_user_id",
            name="uq_report_page_set_tenant_id",
        ),
        UniqueConstraint(
            "asset_set_id", "user_id", "subject_user_id", "page_index", name="uq_report_page_set_index"
        ),
        UniqueConstraint(
            "source_asset_id",
            "user_id",
            "subject_user_id",
            "source_page_index",
            name="uq_report_page_asset_source_index",
        ),
        CheckConstraint("page_index >= 1", name="ck_report_page_index"),
        CheckConstraint("source_page_index >= 1", name="ck_report_page_source_index"),
        Index("ix_report_page_set_order", "user_id", "subject_user_id", "asset_set_id", "page_index"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_set_id: Mapped[int] = mapped_column(Integer, nullable=False)
    source_asset_id: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    subject_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    page_index: Mapped[int] = mapped_column(Integer, nullable=False)
    source_page_index: Mapped[int] = mapped_column(Integer, nullable=False)
    rendered_byte_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    rendered_storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    width_px: Mapped[int] = mapped_column(Integer, nullable=False)
    height_px: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class HealthReportCompletenessAssessment(Base):
    """Set-level proof for declared, rendered, or detected missing pages."""

    __tablename__ = "health_report_completeness_assessments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["asset_set_id", "user_id", "subject_user_id"],
            [
                "health_report_asset_sets.id",
                "health_report_asset_sets.user_id",
                "health_report_asset_sets.subject_user_id",
            ],
            name="fk_report_completeness_set_tenant",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "asset_set_id",
            "user_id",
            "subject_user_id",
            "detector_id",
            "detector_version",
            name="uq_report_completeness_detector_version",
        ),
        CheckConstraint(
            "completeness_status IN ('complete', 'missing_page', 'invalid_manifest')",
            name="ck_report_completeness_status",
        ),
        CheckConstraint("expected_page_count >= 1", name="ck_report_completeness_expected"),
        CheckConstraint("observed_page_count >= 0", name="ck_report_completeness_observed"),
        CheckConstraint(
            "basis IN ('user_declared', 'pdf_page_count', 'ocr_page_numbers', 'legacy')",
            name="ck_report_completeness_basis",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_set_id: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    subject_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    detector_id: Mapped[str] = mapped_column(String(80), nullable=False)
    detector_version: Mapped[str] = mapped_column(String(80), nullable=False)
    completeness_status: Mapped[str] = mapped_column(String(24), nullable=False)
    basis: Mapped[str] = mapped_column(String(32), nullable=False)
    expected_page_count: Mapped[int] = mapped_column(Integer, nullable=False)
    observed_page_count: Mapped[int] = mapped_column(Integer, nullable=False)
    missing_page_indices: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=sa_text("'[]'")
    )
    evidence: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=sa_text("'{}'")
    )
    failure_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class HealthReportAssetQualityResult(Base):
    """Versioned, machine-readable quality evidence for one rendered page."""

    __tablename__ = "health_report_asset_quality_results"
    __table_args__ = (
        ForeignKeyConstraint(
            ["page_id", "user_id", "subject_user_id"],
            [
                "health_report_pages.id",
                "health_report_pages.user_id",
                "health_report_pages.subject_user_id",
            ],
            name="fk_report_asset_quality_page_tenant",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "page_id",
            "user_id",
            "subject_user_id",
            "detector_id",
            "detector_version",
            name="uq_report_asset_quality_detector_version",
        ),
        CheckConstraint(
            "quality_status IN ('accepted', 'blurry', 'blank', 'unreadable', 'low_resolution')",
            name="ck_report_asset_quality_status",
        ),
        CheckConstraint("blur_score IS NULL OR blur_score >= 0", name="ck_report_asset_blur_score"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    page_id: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    subject_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    detector_id: Mapped[str] = mapped_column(String(80), nullable=False)
    detector_version: Mapped[str] = mapped_column(String(80), nullable=False)
    quality_status: Mapped[str] = mapped_column(String(24), nullable=False)
    blur_score: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    quality_metrics: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=sa_text("'{}'")
    )
    missing_page_evidence: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=sa_text("'{}'")
    )
    failure_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class HealthReportFieldLocator(Base):
    """Canonical page and normalized bounding box for an extracted candidate."""

    __tablename__ = "health_report_field_locators"
    __table_args__ = (
        ForeignKeyConstraint(
            ["candidate_id", "workflow_id", "user_id", "subject_user_id"],
            [
                "health_report_field_candidates.id",
                "health_report_field_candidates.workflow_id",
                "health_report_field_candidates.user_id",
                "health_report_field_candidates.subject_user_id",
            ],
            name="fk_report_field_locator_candidate_tenant",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["page_id", "user_id", "subject_user_id"],
            [
                "health_report_pages.id",
                "health_report_pages.user_id",
                "health_report_pages.subject_user_id",
            ],
            name="fk_report_field_locator_page_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["asset_set_id", "workflow_id", "user_id", "subject_user_id"],
            [
                "health_report_asset_set_workflow_links.asset_set_id",
                "health_report_asset_set_workflow_links.workflow_id",
                "health_report_asset_set_workflow_links.user_id",
                "health_report_asset_set_workflow_links.subject_user_id",
            ],
            name="fk_report_field_locator_set_workflow_tenant",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "candidate_id",
            "workflow_id",
            "user_id",
            "subject_user_id",
            "region_index",
            name="uq_report_field_locator_candidate_region",
        ),
        CheckConstraint("x >= 0 AND x <= 1", name="ck_report_field_locator_x"),
        CheckConstraint("y >= 0 AND y <= 1", name="ck_report_field_locator_y"),
        CheckConstraint("width > 0 AND width <= 1", name="ck_report_field_locator_width"),
        CheckConstraint("height > 0 AND height <= 1", name="ck_report_field_locator_height"),
        CheckConstraint("x + width <= 1", name="ck_report_field_locator_right"),
        CheckConstraint("y + height <= 1", name="ck_report_field_locator_bottom"),
        CheckConstraint("region_index >= 1", name="ck_report_field_locator_region_index"),
        CheckConstraint(
            "region_role IN ('name', 'value', 'unit', 'reference', 'row')",
            name="ck_report_field_locator_region_role",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_report_field_locator_confidence",
        ),
        CheckConstraint(
            "coordinate_space = 'normalized_top_left'", name="ck_report_field_locator_coordinate_space"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(Integer, nullable=False)
    workflow_id: Mapped[int] = mapped_column(Integer, nullable=False)
    asset_set_id: Mapped[int] = mapped_column(Integer, nullable=False)
    page_id: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    subject_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    x: Mapped[Decimal] = mapped_column(Numeric(7, 6), nullable=False)
    y: Mapped[Decimal] = mapped_column(Numeric(7, 6), nullable=False)
    width: Mapped[Decimal] = mapped_column(Numeric(7, 6), nullable=False)
    height: Mapped[Decimal] = mapped_column(Numeric(7, 6), nullable=False)
    region_index: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    region_role: Mapped[str] = mapped_column(String(32), nullable=False, default="value", server_default="value")
    polygon_norm: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=sa_text("'[]'")
    )
    provider_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    coordinate_space: Mapped[str] = mapped_column(
        String(32), nullable=False, default="normalized_top_left", server_default="normalized_top_left"
    )
    locator_version: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class HealthReportDescriptor(Base):
    """Normalized, filterable metadata for trusted report history."""

    __tablename__ = "health_report_descriptors"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workflow_id", "user_id", "subject_user_id"],
            [
                "health_report_workflows.id",
                "health_report_workflows.user_id",
                "health_report_workflows.subject_user_id",
            ],
            name="fk_report_descriptor_workflow_tenant",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "workflow_id", "user_id", "subject_user_id", name="uq_report_descriptor_workflow"
        ),
        Index(
            "ix_report_descriptor_history",
            "user_id",
            "subject_user_id",
            "report_date",
            "hospital_normalized",
            "report_type",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workflow_id: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    subject_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    hospital: Mapped[str | None] = mapped_column(String(256), nullable=True)
    hospital_normalized: Mapped[str | None] = mapped_column(String(256), nullable=True)
    report_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    report_type: Mapped[str] = mapped_column(String(24), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class HealthReportSemanticSignature(Base):
    """Versioned normalized signature used only to propose semantic duplicates."""

    __tablename__ = "health_report_semantic_signatures"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workflow_id", "user_id", "subject_user_id"],
            [
                "health_report_workflows.id",
                "health_report_workflows.user_id",
                "health_report_workflows.subject_user_id",
            ],
            name="fk_report_semantic_signature_workflow_tenant",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "workflow_id",
            "user_id",
            "subject_user_id",
            "algorithm_version",
            name="uq_report_semantic_signature_workflow_version",
        ),
        Index(
            "ix_report_semantic_signature_candidates",
            "user_id",
            "subject_user_id",
            "report_type",
            "report_date_key",
            "hospital_key",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workflow_id: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    subject_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(80), nullable=False)
    threshold_version: Mapped[str] = mapped_column(String(80), nullable=False)
    report_type: Mapped[str] = mapped_column(String(24), nullable=False)
    report_date_key: Mapped[str | None] = mapped_column(String(16), nullable=True)
    hospital_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    normalized_metadata: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=sa_text("'{}'")
    )
    field_token_manifest: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=sa_text("'{}'")
    )
    signature_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class HealthReportExactDuplicateMatch(Base):
    """Persistent proof that a sealed upload reuses a byte-identical workflow."""

    __tablename__ = "health_report_exact_duplicate_matches"
    __table_args__ = (
        ForeignKeyConstraint(
            ["asset_set_id", "user_id", "subject_user_id"],
            [
                "health_report_asset_sets.id",
                "health_report_asset_sets.user_id",
                "health_report_asset_sets.subject_user_id",
            ],
            name="fk_report_exact_duplicate_set_tenant",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["matched_workflow_id", "user_id", "subject_user_id"],
            [
                "health_report_workflows.id",
                "health_report_workflows.user_id",
                "health_report_workflows.subject_user_id",
            ],
            name="fk_report_exact_duplicate_workflow_tenant",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "asset_set_id", "user_id", "subject_user_id", name="uq_report_exact_duplicate_set"
        ),
        CheckConstraint("length(aggregate_sha256) = 64", name="ck_report_exact_duplicate_digest"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_set_id: Mapped[int] = mapped_column(Integer, nullable=False)
    matched_workflow_id: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    subject_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    aggregate_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    matched_document_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class HealthReportDuplicateDecision(Base):
    """Explicit user decision for a semantic (not byte-identical) duplicate."""

    __tablename__ = "health_report_duplicate_decisions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workflow_id", "user_id", "subject_user_id"],
            [
                "health_report_workflows.id",
                "health_report_workflows.user_id",
                "health_report_workflows.subject_user_id",
            ],
            name="fk_report_duplicate_workflow_tenant",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["matched_workflow_id", "user_id", "subject_user_id"],
            [
                "health_report_workflows.id",
                "health_report_workflows.user_id",
                "health_report_workflows.subject_user_id",
            ],
            name="fk_report_duplicate_match_tenant",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "id", "user_id", "subject_user_id", name="uq_report_duplicate_decision_tenant_id"
        ),
        UniqueConstraint(
            "workflow_id",
            "matched_workflow_id",
            "user_id",
            "subject_user_id",
            "semantic_algorithm_version",
            name="uq_report_duplicate_pair_version",
        ),
        UniqueConstraint(
            "workflow_id",
            "user_id",
            "subject_user_id",
            "semantic_algorithm_version",
            name="uq_report_duplicate_top_match_version",
        ),
        UniqueConstraint(
            "user_id",
            "subject_user_id",
            "decision_client_event_id",
            name="uq_report_duplicate_decision_tenant_event",
        ),
        UniqueConstraint(
            "user_id",
            "subject_user_id",
            "detection_key",
            name="uq_report_duplicate_detection_key",
        ),
        CheckConstraint(
            "duplicate_kind IN ('semantic')", name="ck_report_duplicate_kind"
        ),
        CheckConstraint(
            "workflow_id <> matched_workflow_id", name="ck_report_duplicate_distinct_workflows"
        ),
        CheckConstraint(
            "decision_status IN ('awaiting_user_choice', 'use_existing', 'continue_new')",
            name="ck_report_duplicate_decision_status",
        ),
        CheckConstraint("similarity >= 0 AND similarity <= 1", name="ck_report_duplicate_similarity"),
        CheckConstraint(
            "(decision_status = 'awaiting_user_choice' AND decided_by_user_id IS NULL "
            "AND decided_at IS NULL AND decision_client_event_id IS NULL) OR "
            "(decision_status <> 'awaiting_user_choice' AND decided_by_user_id IS NOT NULL "
            "AND decided_at IS NOT NULL AND decision_client_event_id IS NOT NULL)",
            name="ck_report_duplicate_decision_complete",
        ),
        Index(
            "ix_report_duplicate_pending",
            "user_id",
            "subject_user_id",
            "decision_status",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workflow_id: Mapped[int] = mapped_column(Integer, nullable=False)
    matched_workflow_id: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    subject_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    duplicate_kind: Mapped[str] = mapped_column(String(16), nullable=False, default="semantic")
    semantic_algorithm_version: Mapped[str] = mapped_column(String(80), nullable=False)
    similarity: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    decision_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="awaiting_user_choice", server_default="awaiting_user_choice"
    )
    detection_key: Mapped[str] = mapped_column(String(96), nullable=False)
    decision_client_event_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    evidence: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=sa_text("'{}'")
    )
    decided_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="RESTRICT"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class HealthReportScoreJob(Base):
    """Durable outbox/lease for versioned post-admission score calculation."""

    __tablename__ = "health_report_score_jobs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workflow_id", "user_id", "subject_user_id"],
            [
                "health_report_workflows.id",
                "health_report_workflows.user_id",
                "health_report_workflows.subject_user_id",
            ],
            name="fk_report_score_job_workflow_tenant",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "id", "user_id", "subject_user_id", name="uq_report_score_job_tenant_id"
        ),
        UniqueConstraint(
            "id",
            "workflow_id",
            "user_id",
            "subject_user_id",
            name="uq_report_score_job_workflow_tenant_id",
        ),
        ForeignKeyConstraint(
            ["supersedes_job_id", "workflow_id", "user_id", "subject_user_id"],
            [
                "health_report_score_jobs.id",
                "health_report_score_jobs.workflow_id",
                "health_report_score_jobs.user_id",
                "health_report_score_jobs.subject_user_id",
            ],
            name="fk_report_score_job_supersedes_tenant",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "user_id", "subject_user_id", "job_key", name="uq_report_score_job_tenant_key"
        ),
        UniqueConstraint(
            "workflow_id",
            "user_id",
            "subject_user_id",
            "algorithm_bundle_version",
            "input_revision",
            name="uq_report_score_job_workflow_bundle_revision",
        ),
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'partial_failed', "
            "'failed', 'cancelled')",
            name="ck_report_score_job_status",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_report_score_job_attempts"),
        CheckConstraint("max_attempts >= 1", name="ck_report_score_job_max_attempts"),
        CheckConstraint(
            "attempt_count <= max_attempts", name="ck_report_score_job_attempt_bound"
        ),
        CheckConstraint(
            "(lease_token IS NULL AND lease_expires_at IS NULL) OR "
            "(lease_token IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="ck_report_score_job_lease_pair",
        ),
        Index(
            "ix_report_score_job_claim",
            "status",
            "next_attempt_at",
            "lease_expires_at",
            "id",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workflow_id: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    subject_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    job_key: Mapped[str] = mapped_column(String(96), nullable=False)
    input_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    algorithm_bundle_version: Mapped[str] = mapped_column(String(80), nullable=False)
    input_manifest_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    supersedes_job_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="pending", server_default="pending"
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3, server_default="3")
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_token: Mapped[str | None] = mapped_column(String(96), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_failure_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class HealthReportScoreJobItem(Base):
    """Independent score-kind item so partial failure never rolls back admission."""

    __tablename__ = "health_report_score_job_items"
    __table_args__ = (
        ForeignKeyConstraint(
            ["job_id", "workflow_id", "user_id", "subject_user_id"],
            [
                "health_report_score_jobs.id",
                "health_report_score_jobs.workflow_id",
                "health_report_score_jobs.user_id",
                "health_report_score_jobs.subject_user_id",
            ],
            name="fk_report_score_job_item_job_tenant",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "id", "user_id", "subject_user_id", name="uq_report_score_job_item_tenant_id"
        ),
        UniqueConstraint(
            "id",
            "workflow_id",
            "user_id",
            "subject_user_id",
            name="uq_report_score_job_item_workflow_tenant_id",
        ),
        UniqueConstraint(
            "job_id", "user_id", "subject_user_id", "score_kind", name="uq_report_score_job_item_kind"
        ),
        CheckConstraint(
            "score_kind IN ('stress', 'recovery', 'inflammation')",
            name="ck_report_score_job_item_kind",
        ),
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'unavailable', 'failed', 'cancelled')",
            name="ck_report_score_job_item_status",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_report_score_job_item_attempts"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(Integer, nullable=False)
    workflow_id: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    subject_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    score_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    policy_id: Mapped[str] = mapped_column(String(80), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    input_manifest: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=sa_text("'{}'")
    )
    missing_inputs: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=sa_text("'{}'")
    )
    failure_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    retryable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=sa_text("false")
    )
    failure_message_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    failure_message_params: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=sa_text("'{}'")
    )
    method_summary_key: Mapped[str] = mapped_column(String(128), nullable=False)
    method_summary_params: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=sa_text("'{}'")
    )
    catalog_version: Mapped[str] = mapped_column(String(80), nullable=False)
    input_basis: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=sa_text("'[]'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    computed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class HealthReportScoreSnapshotLink(Base):
    """Tenant-bound output edge from a score job item to its durable snapshot."""

    __tablename__ = "health_report_score_snapshot_links"
    __table_args__ = (
        ForeignKeyConstraint(
            ["job_item_id", "workflow_id", "user_id", "subject_user_id"],
            [
                "health_report_score_job_items.id",
                "health_report_score_job_items.workflow_id",
                "health_report_score_job_items.user_id",
                "health_report_score_job_items.subject_user_id",
            ],
            name="fk_report_score_snapshot_link_item_tenant",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["snapshot_id", "workflow_id", "user_id", "subject_user_id"],
            [
                "health_score_snapshots.id",
                "health_score_snapshots.source_report_workflow_id",
                "health_score_snapshots.user_id",
                "health_score_snapshots.subject_user_id",
            ],
            name="fk_report_score_snapshot_link_snapshot_tenant",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "job_item_id", "user_id", "subject_user_id", name="uq_report_score_snapshot_link_item"
        ),
        UniqueConstraint(
            "snapshot_id",
            "workflow_id",
            "user_id",
            "subject_user_id",
            name="uq_report_score_snapshot_link_snapshot",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_item_id: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot_id: Mapped[int] = mapped_column(Integer, nullable=False)
    workflow_id: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    subject_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class HealthReportFollowUpItem(Base):
    """Traceable, localized follow-up generated only from admitted evidence."""

    __tablename__ = "health_report_follow_up_items"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workflow_id", "user_id", "subject_user_id"],
            [
                "health_report_workflows.id",
                "health_report_workflows.user_id",
                "health_report_workflows.subject_user_id",
            ],
            name="fk_report_follow_up_workflow_tenant",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "workflow_id",
            "user_id",
            "subject_user_id",
            "rule_id",
            "rule_version",
            "item_code",
            name="uq_report_follow_up_rule_source",
        ),
        UniqueConstraint(
            "id",
            "workflow_id",
            "user_id",
            "subject_user_id",
            name="uq_report_follow_up_item_workflow_tenant_id",
        ),
        CheckConstraint(
            "status IN ('active', 'resolved', 'retracted')",
            name="ck_report_follow_up_status",
        ),
        Index(
            "ix_report_follow_up_active",
            "user_id",
            "subject_user_id",
            "workflow_id",
            "status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workflow_id: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    subject_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    rule_id: Mapped[str] = mapped_column(String(80), nullable=False)
    rule_version: Mapped[str] = mapped_column(String(80), nullable=False)
    item_code: Mapped[str] = mapped_column(String(80), nullable=False)
    message_key: Mapped[str] = mapped_column(String(128), nullable=False)
    message_params: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=sa_text("'{}'")
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default="active"
    )
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class HealthReportFollowUpEvidence(Base):
    """One admitted observation or explicit confirmation supporting follow-up."""

    __tablename__ = "health_report_follow_up_evidence"
    __table_args__ = (
        ForeignKeyConstraint(
            ["follow_up_item_id", "workflow_id", "user_id", "subject_user_id"],
            [
                "health_report_follow_up_items.id",
                "health_report_follow_up_items.workflow_id",
                "health_report_follow_up_items.user_id",
                "health_report_follow_up_items.subject_user_id",
            ],
            name="fk_report_follow_up_evidence_item_tenant",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["observation_id", "user_id", "subject_user_id"],
            [
                "confirmed_health_observations.id",
                "confirmed_health_observations.user_id",
                "confirmed_health_observations.subject_user_id",
            ],
            name="fk_report_follow_up_evidence_observation_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "confirmation_event_id",
                "confirmation_candidate_id",
                "workflow_id",
                "user_id",
                "subject_user_id",
            ],
            [
                "health_report_confirmation_events.id",
                "health_report_confirmation_events.candidate_id",
                "health_report_confirmation_events.workflow_id",
                "health_report_confirmation_events.user_id",
                "health_report_confirmation_events.subject_user_id",
            ],
            name="fk_report_follow_up_evidence_confirmation_tenant",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "follow_up_item_id",
            "workflow_id",
            "user_id",
            "subject_user_id",
            "evidence_key",
            name="uq_report_follow_up_evidence_key",
        ),
        CheckConstraint(
            "source_kind IN ('confirmed_observation', 'clinician_confirmation')",
            name="ck_report_follow_up_evidence_source_kind",
        ),
        CheckConstraint(
            "(source_kind = 'confirmed_observation' AND observation_id IS NOT NULL "
            "AND confirmation_event_id IS NULL AND confirmation_candidate_id IS NULL) OR "
            "(source_kind = 'clinician_confirmation' AND observation_id IS NULL "
            "AND confirmation_event_id IS NOT NULL AND confirmation_candidate_id IS NOT NULL)",
            name="ck_report_follow_up_evidence_source_complete",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    follow_up_item_id: Mapped[int] = mapped_column(Integer, nullable=False)
    workflow_id: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    subject_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    evidence_key: Mapped[str] = mapped_column(String(96), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    observation_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confirmation_event_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confirmation_candidate_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
