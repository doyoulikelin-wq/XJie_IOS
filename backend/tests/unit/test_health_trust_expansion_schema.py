"""Fail-closed contract tests for the additive 0024 -> 0025 schema lane."""

from __future__ import annotations

import contextlib
import copy
import importlib
import inspect
import io
import json
from pathlib import Path

from app.db.base import Base
import app.models  # noqa: F401  Ensure every registered model is loaded.
from deploy import production_deploy_guard as deploy_guard


MIGRATION_MODULE = "app.db.migrations.versions.0024_health_profile_report_completion"
NEW_TABLES = {
    "trusted_device_profile_observations",
    "health_profile_fact_source_versions",
    "health_profile_device_source_links",
    "health_profile_goals",
    "health_profile_goal_metrics",
    "health_profile_goal_revisions",
    "health_report_asset_sets",
    "health_report_assets",
    "health_report_asset_set_workflow_links",
    "health_report_pages",
    "health_report_completeness_assessments",
    "health_report_asset_quality_results",
    "health_report_field_locators",
    "health_report_descriptors",
    "health_report_semantic_signatures",
    "health_report_exact_duplicate_matches",
    "health_report_duplicate_decisions",
    "health_report_score_jobs",
    "health_report_score_job_items",
    "health_report_score_snapshot_links",
    "health_report_follow_up_items",
    "health_report_follow_up_evidence",
}
DIETARY_TABLES = {
    "dietary_drafts",
    "dietary_records",
    "dietary_record_events",
    "dietary_days",
    "dietary_daily_summaries",
    "dietary_recognition_cache",
}


def _candidate_manifest() -> dict:
    backend_root = Path(__file__).resolve().parents[2]
    probe = deploy_guard.MIGRATION_PROBE_SOURCE.replace(
        'APPLICATION_ROOT = Path("/app")',
        f"APPLICATION_ROOT = Path({str(backend_root)!r})",
    )
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        exec(compile(probe, "candidate_migration_probe.py", "exec"), {"__name__": "__main__"})
    return json.loads(output.getvalue())


def _old_0023_manifest(candidate: dict) -> dict:
    old = copy.deepcopy(candidate)
    old["migrations"] = old["migrations"][:-2]
    old["heads"] = [old["migrations"][-1]["revision"]]
    old["model_schema"] = [
        table
        for table in old["model_schema"]
        if table["name"] not in NEW_TABLES | DIETARY_TABLES
    ]
    for table in old["model_schema"]:
        if table["name"] == "trusted_medication_plans":
            table["columns"] = [
                column for column in table["columns"] if column["name"] != "purpose"
            ]
        if table["name"] == "user_indicator_values":
            table["constraints"] = [
                item
                for item in table["constraints"]
                if item["name"] != "uq_user_indicator_value_id_user"
            ]
        if table["name"] == "health_profile_sources":
            table["constraints"] = [
                item
                for item in table["constraints"]
                if item["name"] != "uq_profile_source_tenant_id"
            ]
        if table["name"] == "health_score_snapshots":
            table["constraints"] = [
                item
                for item in table["constraints"]
                if item["name"] != "uq_score_snapshot_workflow_tenant_id"
            ]
        if table["name"] == "health_profile_revisions":
            table["indexes"] = [
                item
                for item in table["indexes"]
                if item["name"]
                not in {
                    "ix_profile_revision_fact_history",
                    "ix_profile_revision_candidate_history",
                }
            ]
    return old


def test_0024_schema_is_additive_registered_and_exact() -> None:
    migration = importlib.import_module(MIGRATION_MODULE)
    source = inspect.getsource(migration.upgrade)

    assert migration.revision == "0024_health_profile_report_completion"
    assert migration.down_revision == "0023_trusted_medication_loop"
    assert "drop_" not in source
    assert "alter_column" not in source
    assert "execute(" not in source
    assert source.count("op.create_table(") == 22
    assert source.count("op.create_unique_constraint(") == 3
    assert source.count("op.add_column(") == 1

    assert NEW_TABLES <= set(Base.metadata.tables)
    schema_object_owners: dict[str, list[str]] = {}
    for table in Base.metadata.tables.values():
        for item in (*table.constraints, *table.indexes):
            if item.name:
                schema_object_owners.setdefault(item.name, []).append(table.name)
    assert {
        name: owners
        for name, owners in schema_object_owners.items()
        if len(owners) != 1
    } == {}, "PostgreSQL schema constraint/index names must be globally unique"
    assert {
        constraint.name
        for constraint in Base.metadata.tables["health_report_assets"].constraints
    } >= {
        "uq_report_asset_set_asset_tenant_id",
        "uq_report_asset_tenant_id",
    }
    purpose = Base.metadata.tables["trusted_medication_plans"].c.purpose
    assert purpose.nullable is True
    assert purpose.server_default is None


def test_0024_source_passes_the_real_expand_policy_and_inventory() -> None:
    candidate = _candidate_manifest()
    old = _old_0023_manifest(candidate)
    versions_path = (
        Path(__file__).resolve().parents[2] / "app" / "db" / "migrations" / "versions"
    )
    sources = [
        (versions_path / "0024_health_profile_report_completion.py").read_bytes(),
        (versions_path / "0025_dietary_records.py").read_bytes(),
    ]
    plan = deploy_guard.validate_expand_migration_source(
        sources,
        old,
        candidate,
    )

    assert plan["old_head"] == "0023_trusted_medication_loop"
    assert plan["candidate_head"] == "0025_dietary_records"
    assert [item["revision"] for item in plan["migrations"]] == [
        "0024_health_profile_report_completion",
        "0025_dietary_records",
    ]
    assert [item["op"] for item in plan["operations"]].count("create_table") == 28
    assert [item["op"] for item in plan["operations"]].count("add_column") == 1
    assert len(candidate["migrations"]) == 25
    assert len(candidate["model_schema"]) == 95
