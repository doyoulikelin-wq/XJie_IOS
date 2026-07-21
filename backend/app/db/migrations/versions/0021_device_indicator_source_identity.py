"""Add first-class device sample identity to indicator values.

Revision ID: 0021_device_indicator_identity
Revises: 0020_chat_request_receipts
Create Date: 2026-07-11
"""
from __future__ import annotations

import re
from datetime import date, datetime
from urllib.parse import quote, unquote

import sqlalchemy as sa
from alembic import op


revision = "0021_device_indicator_identity"
down_revision = "0020_chat_request_receipts"
branch_labels = None
depends_on = None


_SOURCE_METRIC_RE = re.compile(r"(?:^|[；;])source_metric=([^；;]+)")
_SOURCE_ID_RE = re.compile(r"(?:^|[；;])source_id=([^；;]+)")
_SOURCE_UPDATED_AT_RE = re.compile(r"(?:^|[；;])source_updated_at=([^；;]+)")
_SOURCE_VALUE_KIND_RE = re.compile(r"(?:^|[；;])source_value_kind=([^；;]+)")
_SOURCE_DISPLAY_VALUE_RE = re.compile(r"(?:^|[；;])source_display_value=([^；;]+)")
_SOURCE_LOCAL_DATE_RE = re.compile(r"(?:^|[；;])source_local_date=([^；;]+)")
_SOURCE_TIMEZONE_OFFSET_RE = re.compile(
    r"(?:^|[；;])source_timezone_offset_minutes=([^；;]+)"
)
_INTERNAL_NOTE_PREFIXES = (
    "source_metric=",
    "source_id=",
    "source_updated_at=",
    "source_value_kind=",
    "source_display_value=",
    "source_local_date=",
    "source_timezone_offset_minutes=",
)


def _extract(pattern: re.Pattern[str], notes: str | None, max_length: int) -> str | None:
    if not notes:
        return None
    match = pattern.search(notes)
    value = match.group(1).strip() if match else ""
    return value[:max_length] or None


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _parse_timezone_offset(value: str | None) -> int | None:
    try:
        parsed = int(value) if value is not None else None
    except ValueError:
        return None
    if parsed is None or not -840 <= parsed <= 840:
        return None
    return parsed


def _daily_source_local_date(source_metric: str | None, source_id: str | None) -> date | None:
    if not source_metric or not source_id:
        return None
    match = re.fullmatch(rf"{re.escape(source_metric)}-(\d{{8}})", source_id)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y%m%d").date()
    except ValueError:
        return None


def _clean_internal_notes(notes: str | None) -> str | None:
    parts = [
        part.strip()
        for part in re.split(r"[；;]", str(notes or ""))
        if part.strip()
        and not any(part.strip().startswith(prefix) for prefix in _INTERNAL_NOTE_PREFIXES)
    ]
    return "；".join(parts) or None


def _backfill_source_fields(bind) -> None:
    """Move legacy source metadata out of notes without logging note contents."""
    metadata = sa.MetaData()
    values = sa.Table("user_indicator_values", metadata, autoload_with=bind)
    rows = bind.execute(sa.select(values).order_by(values.c.id.desc())).mappings().all()

    seen_source_ids: set[tuple[int, str, str]] = set()
    for row in rows:
        source = str(row.get("source") or "")
        source_metric = row.get("source_metric")
        source_id = row.get("source_id")
        value_kind = row.get("value_kind")
        display_value = row.get("display_value")
        source_local_date = row.get("source_local_date")
        timezone_offset_minutes = row.get("timezone_offset_minutes")
        source_updated_at = None
        if source != "manual":
            source_metric = source_metric or _extract(_SOURCE_METRIC_RE, row.get("notes"), 64)
            source_id = source_id or _extract(_SOURCE_ID_RE, row.get("notes"), 128)
            value_kind = value_kind or _extract(_SOURCE_VALUE_KIND_RE, row.get("notes"), 16)
            encoded_display = _extract(_SOURCE_DISPLAY_VALUE_RE, row.get("notes"), 512)
            if display_value is None and encoded_display:
                display_value = unquote(encoded_display)[:128] or None
            source_local_date = source_local_date or _parse_date(
                _extract(_SOURCE_LOCAL_DATE_RE, row.get("notes"), 32)
            )
            timezone_offset_minutes = (
                timezone_offset_minutes
                if timezone_offset_minutes is not None
                else _parse_timezone_offset(
                    _extract(_SOURCE_TIMEZONE_OFFSET_RE, row.get("notes"), 8)
                )
            )
            source_updated_at = _parse_timestamp(
                _extract(_SOURCE_UPDATED_AT_RE, row.get("notes"), 64)
            )
            source_local_date = source_local_date or _daily_source_local_date(
                str(source_metric or "") or None,
                str(source_id or "") or None,
            )

        value_kind = value_kind if value_kind in {"numeric", "category"} else "numeric"

        # Keep the newest row addressable if legacy data contains a duplicate source ID.
        # Older duplicates remain valid historical rows but use the legacy, null-ID path.
        if source_id:
            key = (int(row["user_id"]), source, str(source_id))
            if key in seen_source_ids:
                source_id = None
            else:
                seen_source_ids.add(key)

        updates: dict[str, object | None] = {}
        if source_metric != row.get("source_metric"):
            updates["source_metric"] = source_metric
        if source_id != row.get("source_id"):
            updates["source_id"] = source_id
        if value_kind != row.get("value_kind"):
            updates["value_kind"] = value_kind
        if display_value != row.get("display_value"):
            updates["display_value"] = display_value
        if source_local_date != row.get("source_local_date"):
            updates["source_local_date"] = source_local_date
        if timezone_offset_minutes != row.get("timezone_offset_minutes"):
            updates["timezone_offset_minutes"] = timezone_offset_minutes
        if source_updated_at is not None:
            updates["updated_at"] = source_updated_at
        if source != "manual":
            cleaned_notes = _clean_internal_notes(row.get("notes"))
            if cleaned_notes != row.get("notes"):
                updates["notes"] = cleaned_notes
        if updates:
            bind.execute(values.update().where(values.c.id == row["id"]).values(**updates))

    bind.execute(
        values.update()
        .where(values.c.updated_at.is_(None))
        .values(updated_at=sa.func.coalesce(values.c.created_at, sa.func.now()))
    )
    bind.execute(
        values.update()
        .where(values.c.value_kind.is_(None))
        .values(value_kind="numeric")
    )


def _preserve_source_fields_for_legacy(bind) -> None:
    """Keep device identity recoverable if an application rollback drops the columns."""
    metadata = sa.MetaData()
    values = sa.Table("user_indicator_values", metadata, autoload_with=bind)
    rows = bind.execute(
        sa.select(
            values.c.id,
            values.c.notes,
            values.c.source_metric,
            values.c.source_id,
            values.c.value_kind,
            values.c.display_value,
            values.c.source_local_date,
            values.c.timezone_offset_minutes,
            values.c.created_at,
            values.c.updated_at,
        ).where(
            sa.and_(
                values.c.source != "manual",
                sa.or_(
                    values.c.source_metric.is_not(None),
                    values.c.source_id.is_not(None),
                    values.c.value_kind == "category",
                    values.c.display_value.is_not(None),
                    values.c.source_local_date.is_not(None),
                    values.c.timezone_offset_minutes.is_not(None),
                    values.c.updated_at != values.c.created_at,
                ),
            )
        )
    ).mappings().all()

    for row in rows:
        source_metric = str(row.get("source_metric") or "").strip() or None
        source_id = str(row.get("source_id") or "").strip() or None
        note_parts = [_clean_internal_notes(row.get("notes"))]
        note_parts = [part for part in note_parts if part]
        if source_metric:
            note_parts.append(f"source_metric={source_metric}")
        if source_id:
            note_parts.append(f"source_id={source_id}")
        if row.get("value_kind") == "category":
            note_parts.append("source_value_kind=category")
        if row.get("display_value"):
            note_parts.append(
                f"source_display_value={quote(str(row['display_value']), safe='')}"
            )
        if row.get("source_local_date"):
            note_parts.append(f"source_local_date={row['source_local_date'].isoformat()}")
        if row.get("timezone_offset_minutes") is not None:
            note_parts.append(
                f"source_timezone_offset_minutes={row['timezone_offset_minutes']}"
            )
        if row.get("updated_at") != row.get("created_at"):
            note_parts.append(f"source_updated_at={row['updated_at'].isoformat()}")
        desired_notes = "；".join(note_parts) or None
        if desired_notes == row.get("notes"):
            continue
        bind.execute(
            values.update()
            .where(values.c.id == row["id"])
            .values(notes=desired_notes)
        )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "user_indicator_values" not in inspector.get_table_names():
        # This legacy table is still created from SQLAlchemy metadata on a fresh install.
        # In that case create_all will use the current model, including these fields/indexes.
        return

    columns = {column["name"] for column in inspector.get_columns("user_indicator_values")}
    with op.batch_alter_table("user_indicator_values") as batch_op:
        if "source_metric" not in columns:
            batch_op.add_column(sa.Column("source_metric", sa.String(length=64), nullable=True))
        if "source_id" not in columns:
            batch_op.add_column(sa.Column("source_id", sa.String(length=128), nullable=True))
        if "value_kind" not in columns:
            batch_op.add_column(sa.Column("value_kind", sa.String(length=16), nullable=True))
        if "display_value" not in columns:
            batch_op.add_column(sa.Column("display_value", sa.String(length=128), nullable=True))
        if "source_local_date" not in columns:
            batch_op.add_column(sa.Column("source_local_date", sa.Date(), nullable=True))
        if "timezone_offset_minutes" not in columns:
            batch_op.add_column(
                sa.Column("timezone_offset_minutes", sa.SmallInteger(), nullable=True)
            )
        if "updated_at" not in columns:
            batch_op.add_column(sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))

    _backfill_source_fields(bind)

    columns = {column["name"]: column for column in sa.inspect(bind).get_columns("user_indicator_values")}
    updated_at = columns["updated_at"]
    if updated_at.get("nullable", True) or updated_at.get("default") is None:
        with op.batch_alter_table("user_indicator_values") as batch_op:
            batch_op.alter_column(
                "updated_at",
                existing_type=sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            )
    value_kind = columns["value_kind"]
    if value_kind.get("nullable", True) or value_kind.get("default") is None:
        with op.batch_alter_table("user_indicator_values") as batch_op:
            batch_op.alter_column(
                "value_kind",
                existing_type=sa.String(length=16),
                nullable=False,
                server_default="numeric",
            )

    check_names = {
        constraint["name"]
        for constraint in sa.inspect(bind).get_check_constraints("user_indicator_values")
    }
    with op.batch_alter_table("user_indicator_values") as batch_op:
        if "ck_user_indicator_value_kind" not in check_names:
            batch_op.create_check_constraint(
                "ck_user_indicator_value_kind",
                "value_kind IN ('numeric', 'category')",
            )
        if "ck_user_indicator_timezone_offset" not in check_names:
            batch_op.create_check_constraint(
                "ck_user_indicator_timezone_offset",
                "timezone_offset_minutes IS NULL OR "
                "timezone_offset_minutes BETWEEN -840 AND 840",
            )

    index_names = {index["name"] for index in sa.inspect(bind).get_indexes("user_indicator_values")}
    if "uq_user_indicator_source_sample" not in index_names:
        op.create_index(
            "uq_user_indicator_source_sample",
            "user_indicator_values",
            ["user_id", "source", "source_id"],
            unique=True,
            postgresql_where=sa.text("source_id IS NOT NULL"),
            sqlite_where=sa.text("source_id IS NOT NULL"),
        )
    if "ix_user_indicator_source_metric_time" not in index_names:
        op.create_index(
            "ix_user_indicator_source_metric_time",
            "user_indicator_values",
            ["user_id", "source", "source_metric", "measured_at"],
            unique=False,
        )
    if "ix_user_indicator_source_local_date" not in index_names:
        op.create_index(
            "ix_user_indicator_source_local_date",
            "user_indicator_values",
            ["user_id", "source", "source_metric", "source_local_date"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "user_indicator_values" not in inspector.get_table_names():
        return

    index_names = {index["name"] for index in inspector.get_indexes("user_indicator_values")}
    if "ix_user_indicator_source_local_date" in index_names:
        op.drop_index("ix_user_indicator_source_local_date", table_name="user_indicator_values")
    if "ix_user_indicator_source_metric_time" in index_names:
        op.drop_index("ix_user_indicator_source_metric_time", table_name="user_indicator_values")
    if "uq_user_indicator_source_sample" in index_names:
        op.drop_index("uq_user_indicator_source_sample", table_name="user_indicator_values")

    columns = {column["name"] for column in sa.inspect(bind).get_columns("user_indicator_values")}
    preserved_columns = {
        "source_metric",
        "source_id",
        "value_kind",
        "display_value",
        "source_local_date",
        "timezone_offset_minutes",
        "updated_at",
    }
    if preserved_columns.issubset(columns):
        _preserve_source_fields_for_legacy(bind)

    check_names = {
        constraint["name"]
        for constraint in sa.inspect(bind).get_check_constraints("user_indicator_values")
    }
    with op.batch_alter_table("user_indicator_values") as batch_op:
        if "ck_user_indicator_timezone_offset" in check_names:
            batch_op.drop_constraint(
                "ck_user_indicator_timezone_offset",
                type_="check",
            )
        if "ck_user_indicator_value_kind" in check_names:
            batch_op.drop_constraint("ck_user_indicator_value_kind", type_="check")
        if "updated_at" in columns:
            batch_op.drop_column("updated_at")
        if "timezone_offset_minutes" in columns:
            batch_op.drop_column("timezone_offset_minutes")
        if "source_local_date" in columns:
            batch_op.drop_column("source_local_date")
        if "display_value" in columns:
            batch_op.drop_column("display_value")
        if "value_kind" in columns:
            batch_op.drop_column("value_kind")
        if "source_id" in columns:
            batch_op.drop_column("source_id")
        if "source_metric" in columns:
            batch_op.drop_column("source_metric")
