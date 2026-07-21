#!/usr/bin/env python3
"""Exercise the approved 0021 -> 0022 -> 0023 -> 0024 -> 0025 path on PostgreSQL 16.

This is a Docker integration gate, not a unit-test inventory item.  It builds the
exact pre-0022 backend, creates and dumps that schema, restores the real custom
archive into a second PostgreSQL 16 instance, proves rollback at the transaction
failpoint, commits the same generated migration runner, compares the complete
physical catalog with the candidate reference, and runs the old image's ORM/CRUD
compatibility probe plus trusted-medication tenant/idempotency CRUD checks against
the expanded schema.
"""

import argparse
import copy
import importlib.util
import io
import os
import re
import shutil
import signal
import stat
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath


OLD_BACKEND_SHA = "aefcf46198ed586753dae29a79e17964d5996e7f"
OLD_HEAD = "0021_device_indicator_identity"
CANDIDATE_HEAD = "0025_dietary_records"
OLD_MIGRATION_COUNT = 21
OLD_TABLE_COUNT = 53
CANDIDATE_MIGRATION_COUNT = 25
CANDIDATE_TABLE_COUNT = 95
MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
MAX_BACKUP_BYTES = 64 * 1024 * 1024


class ExpandSelfTestError(RuntimeError):
    """A fail-closed expand-migration integration assertion failed."""


def require(condition, message):
    if not condition:
        raise ExpandSelfTestError(message)


def catalog_differences(
    expected,
    observed,
    path="$",
    *,
    value_limit=160,
    limit=32,
    differences=None,
):
    """Return bounded, deterministic catalog differences for gate diagnostics."""
    if differences is None:
        differences = []
    if len(differences) >= limit:
        return differences
    if type(expected) is not type(observed):
        differences.append(
            "{0}: type {1} != {2}".format(
                path,
                type(expected).__name__,
                type(observed).__name__,
            )
        )
        return differences
    if isinstance(expected, dict):
        expected_keys = sorted(expected)
        observed_keys = sorted(observed)
        if expected_keys != observed_keys:
            differences.append(
                "{0}: keys {1} != {2}".format(
                    path,
                    repr(expected_keys)[:value_limit],
                    repr(observed_keys)[:value_limit],
                )
            )
            return differences
        for key in expected_keys:
            catalog_differences(
                expected[key],
                observed[key],
                "{0}.{1}".format(path, key),
                value_limit=value_limit,
                limit=limit,
                differences=differences,
            )
        return differences
    if isinstance(expected, list):
        if len(expected) != len(observed):
            differences.append(
                "{0}: length {1} != {2}".format(
                    path,
                    len(expected),
                    len(observed),
                )
            )
            return differences
        for index, (expected_item, observed_item) in enumerate(
            zip(expected, observed)
        ):
            catalog_differences(
                expected_item,
                observed_item,
                "{0}[{1}]".format(path, index),
                value_limit=value_limit,
                limit=limit,
                differences=differences,
            )
        return differences
    if expected != observed:
        differences.append(
            "{0}: {1} != {2}".format(
                path,
                repr(expected)[:value_limit],
                repr(observed)[:value_limit],
            )
        )
    return differences


def first_catalog_difference(expected, observed, path="$", *, value_limit=240):
    differences = catalog_differences(
        expected,
        observed,
        path,
        value_limit=value_limit,
        limit=1,
    )
    return differences[0] if differences else None


_TEXT_ANY_CHECK_PATTERNS = (
    re.compile(
        r"^CHECK \(\(\((?P<lhs>[a-z_][a-z0-9_]*)\)::text = ANY "
        r"\(\(ARRAY\[(?P<items>.+)\]\)::text\[\]\)\)\)$"
    ),
    re.compile(
        r"^CHECK \(\(\((?P<lhs>[a-z_][a-z0-9_]*)\)::text = ANY "
        r"\(ARRAY\[(?P<items>.+)\]\)\)\)$"
    ),
)
_TEXT_ANY_CHECK_ITEM = re.compile(
    r"(?:(?P<direct>'(?:''|[^'])*')::character varying|"
    r"\((?P<roundtrip>'(?:''|[^'])*')::character varying\)::text)"
)


def canonicalize_dump_restore_check_definition(definition):
    """Normalize only PostgreSQL's two equivalent text-ANY dump forms."""
    if type(definition) is not str:
        return definition
    match = None
    for pattern in _TEXT_ANY_CHECK_PATTERNS:
        match = pattern.fullmatch(definition)
        if match is not None:
            break
    if match is None:
        return definition
    items = []
    cursor = 0
    for item_match in _TEXT_ANY_CHECK_ITEM.finditer(match.group("items")):
        if match.group("items")[cursor:item_match.start()] != (
            "" if not items else ", "
        ):
            return definition
        items.append(item_match.group("direct") or item_match.group("roundtrip"))
        cursor = item_match.end()
    if not items or cursor != len(match.group("items")):
        return definition
    return "CHECK ((({0})::text = ANY (ARRAY[{1}])))".format(
        match.group("lhs"),
        ", ".join(item + "::text" for item in items),
    )


def canonicalize_dump_restore_catalog(catalog):
    """Return a comparison-only copy stable across a real custom dump restore."""
    comparable = copy.deepcopy(catalog)
    for table in comparable.get("tables", []):
        for constraint in table.get("constraints", []):
            if constraint.get("type") == "c":
                constraint["definition"] = (
                    canonicalize_dump_restore_check_definition(
                        constraint.get("definition")
                    )
                )
    return comparable


def load_module(path, name):
    specification = importlib.util.spec_from_file_location(name, path)
    require(
        specification is not None and specification.loader is not None,
        "cannot load tracked self-test dependency: " + str(path),
    )
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


def safe_extract_git_archive(payload, destination):
    require(0 < len(payload) <= MAX_ARCHIVE_BYTES, "old Git archive size is invalid")
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:") as archive:
        members = archive.getmembers()
        require(members, "old Git archive is empty")
        for member in members:
            path = PurePosixPath(member.name)
            require(
                not path.is_absolute()
                and path.parts
                and ".." not in path.parts
                and member.name == path.as_posix(),
                "old Git archive contains an unsafe path",
            )
            require(
                member.isdir() or member.isfile(),
                "old Git archive contains a link or special file",
            )
        archive.extractall(destination, members=members, filter="data")


def build_old_backend(harness, repository_root, work):
    object_type, _, _ = harness.run(
        ["git", "-C", str(repository_root), "cat-file", "-t", OLD_BACKEND_SHA],
        "validate old backend Git object",
        stdout_limit=4096,
    )
    require(object_type.strip() == b"commit", "old backend SHA is not a commit")
    archive, _, _ = harness.run(
        [
            "git",
            "-C",
            str(repository_root),
            "archive",
            "--format=tar",
            OLD_BACKEND_SHA,
        ],
        "archive exact old backend",
        timeout=120,
        stdout_limit=MAX_ARCHIVE_BYTES,
    )
    old_root = work / "old-source"
    old_root.mkdir(mode=0o700)
    safe_extract_git_archive(archive, old_root)
    dockerfile = old_root / "backend" / "Dockerfile"
    metadata = dockerfile.lstat()
    require(
        stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1,
        "old backend Dockerfile identity is invalid",
    )
    tag = "xjie-expand-old-selftest:" + harness.run_id
    harness.docker(
        [
            "build",
            "--pull",
            "--platform",
            "linux/amd64",
            "--label",
            "org.opencontainers.image.revision=" + OLD_BACKEND_SHA,
            "--tag",
            tag,
            str(old_root / "backend"),
        ],
        "build exact old backend image",
        timeout=900,
        stdout_limit=16 * 1024 * 1024,
        stderr_limit=16 * 1024 * 1024,
    )
    image = harness.inspect_image(tag, "inspect exact old backend image")
    image_id = image.get("Id")
    require(
        harness_module.SHA256_ID.fullmatch(image_id or "") is not None,
        "old backend image ID is invalid",
    )
    require(
        image.get("Os") == "linux" and image.get("Architecture") == "amd64",
        "old backend image platform changed",
    )
    labels = image.get("Config", {}).get("Labels") or {}
    require(
        labels.get("org.opencontainers.image.revision") == OLD_BACKEND_SHA,
        "old backend image is not bound to the exact old SHA",
    )
    return tag, image_id


def emit_manifest(
    harness,
    guard,
    guard_source,
    image_id,
    work,
    label,
    expected_head,
    expected_migrations,
    expected_tables,
):
    probe = work / (label + "-migration-probe.py")
    output_path = work / (label + "-manifest.json")
    harness_module.emit_guard_file(
        harness,
        guard_source,
        ["emit-migration-probe"],
        probe,
        "emit " + label + " migration probe",
    )
    output = harness.run_one_shot(
        label + "-manifest",
        image_id,
        harness_module.hardened_one_shot_options("65534:65534")
        + ["--entrypoint", "python"],
        ["-I", "-"],
        input_bytes=probe.read_bytes(),
        stdout_limit=16 * 1024 * 1024,
    )
    manifest = harness_module.parse_single_json(output, label + " manifest")
    guard.validate_migration_manifest(manifest)
    require(
        manifest["heads"] == [expected_head]
        and len(manifest["migrations"]) == expected_migrations
        and len(manifest["model_schema"]) == expected_tables,
        label + " manifest inventory is not exact",
    )
    harness_module.write_owner_only(
        output_path,
        harness_module.ordered_json(manifest).encode("ascii"),
    )
    return manifest, output_path


def materialize_manifest(
    harness,
    guard,
    guard_source,
    image_id,
    manifest,
    manifest_path,
    socket_directory,
    password,
    work,
    label,
):
    materializer = work / (label + "-materializer.py")
    result_path = work / (label + "-materializer-result.json")
    harness_module.emit_guard_file(
        harness,
        guard_source,
        [
            "emit-reference-schema-materializer",
            "--candidate-manifest",
            str(manifest_path),
        ],
        materializer,
        "emit " + label + " materializer",
    )
    database_url = (
        "postgresql+psycopg://{0}:{1}@/{2}?host={3}".format(
            harness_module.ADMIN_NAME,
            password,
            harness_module.DATABASE_NAME,
            harness_module.SOCKET_DESTINATION,
        )
    )
    harness.add_secret(database_url)
    output = harness.run_one_shot(
        label + "-materializer",
        image_id,
        harness_module.hardened_one_shot_options("65534:65534")
        + [
            "--mount",
            "type=bind,src={0},dst={1},readonly".format(
                socket_directory,
                harness_module.SOCKET_DESTINATION,
            ),
            "--env",
            "XJIE_REFERENCE_DATABASE_URL=" + database_url,
            "--entrypoint",
            "python",
        ],
        ["-I", "-"],
        input_bytes=materializer.read_bytes(),
        stdout_limit=65536,
    )
    result = harness_module.parse_single_json(output, label + " materializer result")
    expected = {
        "schema_version": 3,
        "candidate_manifest_sha256": guard.candidate_manifest_sha256(manifest),
        "table_count": len(manifest["model_schema"]),
    }
    require(result == expected, label + " materializer result is not exact")
    harness_module.write_owner_only(
        result_path,
        harness_module.ordered_json(result).encode("ascii"),
    )
    harness_module.run_guard_cli(
        harness,
        guard_source,
        [
            "validate-expand-reference-materializer-result",
            "--candidate-manifest",
            str(manifest_path),
            "--result",
            str(result_path),
        ],
        "validate " + label + " materializer result",
    )


def catalog_for_server(
    harness,
    guard,
    guard_source,
    postgres_image_id,
    manifest,
    manifest_path,
    socket_directory,
    password,
    work,
    label,
    *,
    expects_alembic=False,
):
    probe = work / (label + "-catalog-probe.sql")
    path = work / (label + "-catalog.json")
    harness_module.emit_guard_file(
        harness,
        guard_source,
        [
            "emit-reference-catalog-probe",
            "--candidate-manifest",
            str(manifest_path),
        ],
        probe,
        "emit " + label + " catalog probe",
    )
    if expects_alembic:
        without_alembic = """AND NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_class AS relation
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = 'public'
          AND relation.relname = 'alembic_version'
      ) AS valid"""
        with_alembic = """AND EXISTS (
        SELECT 1
        FROM pg_catalog.pg_class AS relation
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = 'public'
          AND relation.relname = 'alembic_version'
          AND relation.relkind = 'r'
      ) AS valid"""
        source = probe.read_text(encoding="utf-8")
        require(
            source.count(without_alembic) == 1,
            "reference catalog Alembic boundary changed",
        )
        source = source.replace(without_alembic, with_alembic, 1)
        guard._validate_read_only_schema_probe(
            source,
            "restored production catalog probe",
        )
        probe.unlink()
        harness_module.write_owner_only(probe, source.encode("utf-8"))
    first = harness_module.run_psql(
        harness,
        postgres_image_id,
        socket_directory,
        harness_module.ADMIN_NAME,
        password,
        probe.read_bytes(),
        label + "-catalog-first",
        True,
        16 * 1024 * 1024,
    ).strip()
    second = harness_module.run_psql(
        harness,
        postgres_image_id,
        socket_directory,
        harness_module.ADMIN_NAME,
        password,
        probe.read_bytes(),
        label + "-catalog-second",
        True,
        16 * 1024 * 1024,
    ).strip()
    require(first == second, label + " catalog is not repeatable")
    catalog = harness_module.parse_single_json(first, label + " catalog")
    guard.validate_reference_catalog(manifest, catalog)
    harness_module.write_owner_only(
        path,
        harness_module.ordered_json(catalog).encode("ascii"),
    )
    return catalog, path, probe


def postgres_client_options(socket_directory, username, password, *, interactive=True):
    options = harness_module.hardened_one_shot_options(
        "70:70",
        interactive=interactive,
    )
    options.extend(
        [
            "--mount",
            "type=bind,src={0},dst={1},readonly".format(
                socket_directory,
                harness_module.SOCKET_DESTINATION,
            ),
            "--env",
            "PGHOST=" + harness_module.SOCKET_DESTINATION,
            "--env",
            "PGPORT=5432",
            "--env",
            "PGUSER=" + username,
            "--env",
            "PGPASSWORD=" + password,
            "--env",
            "PGDATABASE=" + harness_module.DATABASE_NAME,
        ]
    )
    return options


def inspect_volume(harness, name, label, *, check=True):
    output, _, return_code = harness.docker(
        ["volume", "inspect", name],
        label,
        stdout_limit=1024 * 1024,
        stderr_limit=1024 * 1024,
        check=check,
    )
    if not check and return_code != 0:
        return None
    values = harness_module.parse_single_json(output, label)
    require(
        isinstance(values, list)
        and len(values) == 1
        and isinstance(values[0], dict),
        label + " is not exactly one volume",
    )
    return values[0]


def create_restore_volume(
    harness,
    guard,
    expected_main_sha,
    postgres_image_id,
    run_id,
):
    name = guard.deployment_name(run_id, guard.RESTORE_VOLUME_ROLE)
    require(
        inspect_volume(harness, name, "pre-create restore volume", check=False)
        is None,
        "restore volume name was already occupied",
    )
    created = False
    try:
        arguments = ["volume", "create", "--driver", "local"]
        arguments.extend(
            guard.deployment_label_arguments(
                name,
                postgres_image_id,
                expected_main_sha,
                run_id,
                guard.RESTORE_VOLUME_ROLE,
            )
        )
        arguments.append(name)
        output, _, _ = harness.docker(
            arguments,
            "create restore volume",
            stdout_limit=4096,
        )
        require(output.decode("ascii").strip() == name, "restore volume name changed")
        created = True
        inspected = inspect_volume(harness, name, "inspect created restore volume")
        guard.validate_restore_volume_inspect(
            inspected,
            name,
            expected_main_sha,
            run_id,
            postgres_image_id,
        )
        return name, inspected
    except BaseException:
        if created:
            inspected = inspect_volume(
                harness,
                name,
                "inspect failed restore volume creation",
                check=False,
            )
            if inspected is not None:
                try:
                    guard.validate_restore_volume_inspect(
                        inspected,
                        name,
                        expected_main_sha,
                        run_id,
                        postgres_image_id,
                    )
                except BaseException:
                    pass
                else:
                    harness.docker(
                        ["volume", "rm", name],
                        "cleanup failed restore volume creation",
                        stdout_limit=4096,
                        check=False,
                    )
        raise


def capacity_and_initialize_restore_volume(
    harness,
    guard,
    postgres_image_id,
    volume_name,
    volume_inspect,
    database_size_output,
    backup_attestation,
    expected_main_sha,
    run_id,
):
    capacity = harness.run_one_shot(
        "restore-volume-capacity",
        postgres_image_id,
        harness_module.hardened_one_shot_options("70:70", interactive=False)
        + [
            "--env",
            "LC_ALL=C",
            "--mount",
            "type=volume,src={0},dst={1},readonly,volume-nocopy".format(
                volume_name,
                harness_module.PGDATA_DESTINATION,
            ),
            "--entrypoint",
            "/bin/stat",
        ],
        ["-f", "-c", "%a %S", harness_module.PGDATA_DESTINATION],
        stdout_limit=4096,
    )
    attestation = guard.build_expand_restore_volume_attestation(
        volume_inspect,
        database_size_output.decode("ascii"),
        capacity.decode("ascii"),
        backup_attestation,
        expected_main_sha,
        run_id,
        postgres_image_id,
    )
    harness.run_one_shot(
        "restore-volume-init",
        postgres_image_id,
        harness_module.hardened_one_shot_options("0:0", interactive=False)
        + [
            "--cap-add",
            "CHOWN",
            "--mount",
            "type=volume,src={0},dst={1},volume-nocopy".format(
                volume_name,
                harness_module.PGDATA_DESTINATION,
            ),
            "--entrypoint",
            "/bin/sh",
        ],
        [
            "-ceu",
            "chmod 0700 {0} && chown 70:70 {0}".format(
                harness_module.PGDATA_DESTINATION
            ),
        ],
        stdout_limit=4096,
    )
    guard.validate_restore_volume_inspect(
        inspect_volume(harness, volume_name, "post-init restore volume"),
        volume_name,
        expected_main_sha,
        run_id,
        postgres_image_id,
    )
    return attestation


def remove_restore_volume(
    harness,
    guard,
    volume_name,
    expected_main_sha,
    run_id,
    postgres_image_id,
):
    inspected = inspect_volume(harness, volume_name, "pre-remove restore volume")
    guard.validate_restore_volume_inspect(
        inspected,
        volume_name,
        expected_main_sha,
        run_id,
        postgres_image_id,
    )
    attached, _, _ = harness.docker(
        [
            "container",
            "ls",
            "--all",
            "--quiet",
            "--no-trunc",
            "--filter",
            "volume=" + volume_name,
        ],
        "check restore volume attachments",
        stdout_limit=4096,
    )
    require(not attached.strip(), "restore volume remained attached")
    harness.docker(
        ["volume", "rm", volume_name],
        "remove restore volume",
        stdout_limit=4096,
    )
    require(
        inspect_volume(harness, volume_name, "post-remove restore volume", check=False)
        is None,
        "restore volume survived cleanup",
    )


def create_backup(
    harness,
    guard,
    postgres_image_id,
    socket_directory,
    password,
    work,
):
    backup = harness.run_one_shot(
        "old-schema-backup",
        postgres_image_id,
        postgres_client_options(
            socket_directory,
            harness_module.ADMIN_NAME,
            password,
            interactive=False,
        )
        + ["--entrypoint", "/usr/local/bin/pg_dump"],
        [
            "--format=custom",
            "--compress=gzip:9",
            "--no-owner",
            "--no-privileges",
            "--serializable-deferrable",
        ],
        stdout_limit=MAX_BACKUP_BYTES,
        timeout=300,
    )
    backup_path = work / "old-production.dump"
    harness_module.write_owner_only(backup_path, backup)
    toc = harness.run_one_shot(
        "old-schema-backup-toc",
        postgres_image_id,
        harness_module.hardened_one_shot_options("70:70")
        + ["--entrypoint", "/usr/local/bin/pg_restore"],
        ["--list"],
        input_bytes=backup,
        stdout_limit=16 * 1024 * 1024,
    )
    toc_path = work / "old-production.toc"
    harness_module.write_owner_only(toc_path, toc)
    attestation = guard.attest_expand_backup(backup_path, toc_path)
    require(
        attestation["backup_size"] == len(backup),
        "custom backup attestation size changed",
    )
    return backup, backup_path, toc_path, attestation


def restore_backup(
    harness,
    postgres_image_id,
    socket_directory,
    admin_password,
    migration_password,
    backup,
):
    role = "xjie_migration_rehearsal"
    setup = """
CREATE ROLE {role} LOGIN PASSWORD {password}
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
ALTER DATABASE {database} OWNER TO {role};
ALTER SCHEMA public OWNER TO {role};
GRANT ALL ON SCHEMA public TO {role};
""".format(
        role=harness_module.sql_identifier(role),
        password=harness_module.sql_literal(migration_password),
        database=harness_module.sql_identifier(harness_module.DATABASE_NAME),
    )
    harness_module.admin_sql(
        harness,
        postgres_image_id,
        socket_directory,
        admin_password,
        setup,
        "create isolated migration role",
    )
    harness.run_one_shot(
        "restore-real-backup",
        postgres_image_id,
        postgres_client_options(
            socket_directory,
            harness_module.ADMIN_NAME,
            admin_password,
        )
        + ["--entrypoint", "/usr/local/bin/pg_restore"],
        [
            "--exit-on-error",
            "--no-owner",
            "--no-privileges",
            "--role=" + role,
            "--dbname=" + harness_module.DATABASE_NAME,
        ],
        input_bytes=backup,
        stdout_limit=65536,
        timeout=300,
    )


def python_database_options(socket_directory, password):
    return harness_module.hardened_one_shot_options("65534:65534") + [
        "--mount",
        "type=bind,src={0},dst={1},readonly".format(
            socket_directory,
            harness_module.SOCKET_DESTINATION,
        ),
        "--env",
        "PGHOST=" + harness_module.SOCKET_DESTINATION,
        "--env",
        "PGPORT=5432",
        "--env",
        "PGUSER=xjie_migration_rehearsal",
        "--env",
        "PGPASSWORD=" + password,
        "--env",
        "PGDATABASE=" + harness_module.DATABASE_NAME,
        "--entrypoint",
        "python",
    ]


def run_expected_runner_failure(
    harness,
    candidate_image_id,
    socket_directory,
    migration_password,
    runner,
):
    container_id, _ = harness.create_container(
        "migration-failpoint",
        candidate_image_id,
        python_database_options(socket_directory, migration_password),
        ["-I", "-"],
    )
    try:
        _, _, return_code = harness.docker(
            ["container", "start", "--attach", "--interactive", container_id],
            "run migration transaction failpoint",
            input_bytes=runner,
            timeout=300,
            stdout_limit=65536,
            stderr_limit=1024 * 1024,
            check=False,
        )
        inspected = harness.inspect_container(
            container_id,
            "inspect migration failpoint container",
        )
        state = inspected.get("State", {})
        require(
            return_code != 0
            and state.get("Running") is False
            and type(state.get("ExitCode")) is int
            and state["ExitCode"] != 0
            and inspected.get("RestartCount") == 0,
            "migration failpoint did not fail closed",
        )
    finally:
        if container_id in harness._containers:
            harness.remove_container(container_id, "migration-failpoint", force=True)


TRUSTED_MEDICATION_PROBE_TEMPLATE = r'''#!/usr/bin/env python3
import json
import os

from sqlalchemy import URL, create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import NullPool

import app.models
from app.db.base import Base


CANDIDATE_HEAD = __CANDIDATE_HEAD__
EXPECTED_TABLES = {
    "trusted_medication_plans",
    "medication_prefill_candidates",
    "medication_plan_events",
    "medication_dose_events",
    "medication_adverse_reaction_events",
}
EXPECTED_CONSTRAINTS = {
    "trusted_medication_plans": {
        "uq_trusted_med_plan_tenant_request",
        "uq_trusted_med_plan_tenant_id",
        "ck_trusted_med_plan_user_confirmed",
    },
    "medication_prefill_candidates": {
        "fk_med_prefill_accepted_plan_tenant",
        "uq_med_prefill_tenant_event",
        "uq_med_prefill_tenant_review_event",
        "uq_med_prefill_tenant_id",
    },
    "medication_plan_events": {
        "fk_med_plan_event_plan_tenant",
        "uq_med_plan_event_tenant_client",
    },
    "medication_dose_events": {
        "fk_med_dose_event_plan_tenant",
        "fk_med_dose_event_supersedes_tenant",
        "uq_med_dose_event_tenant_client",
        "uq_med_dose_event_occurrence_version",
    },
    "medication_adverse_reaction_events": {
        "fk_med_reaction_event_plan_tenant",
        "uq_med_reaction_event_tenant_client",
        "uq_med_reaction_event_version",
        "ck_med_reaction_temporal_only",
    },
}
REQUIRED_PG_ENV = ("PGHOST", "PGPORT", "PGUSER", "PGPASSWORD", "PGDATABASE")


def fail(message):
    raise RuntimeError(message)


def database_url():
    if any(not os.environ.get(name) for name in REQUIRED_PG_ENV):
        fail("trusted medication probe lacks the minimal database identity")
    if (
        os.environ["PGHOST"] != "/var/run/postgresql"
        or os.environ["PGPORT"] != "5432"
        or os.environ["PGUSER"] != "xjie_migration_rehearsal"
        or os.environ["PGDATABASE"] != "xjie_reference"
        or any(name.startswith("DATABASE_") for name in os.environ)
    ):
        fail("trusted medication probe is not isolated")
    return URL.create(
        "postgresql+psycopg",
        username=os.environ["PGUSER"],
        password=os.environ["PGPASSWORD"],
        host=os.environ["PGHOST"],
        port=int(os.environ["PGPORT"]),
        database=os.environ["PGDATABASE"],
    )


def expect_integrity(connection, sql, parameters, label):
    savepoint = connection.begin_nested()
    try:
        connection.exec_driver_sql(sql, parameters)
    except IntegrityError:
        savepoint.rollback()
        return
    savepoint.rollback()
    fail(label + " was accepted")


def run():
    observed_tables = set(Base.metadata.tables) & EXPECTED_TABLES
    if observed_tables != EXPECTED_TABLES:
        fail("trusted medication model table inventory changed")
    for table_name, expected in EXPECTED_CONSTRAINTS.items():
        observed = {
            constraint.name
            for constraint in Base.metadata.tables[table_name].constraints
            if constraint.name is not None
        }
        if not expected.issubset(observed):
            fail("trusted medication model constraint inventory changed: " + table_name)

    owner_id = -2147483000
    other_id = -2147482999
    plan_id = -2147482000
    prefill_id = -2147481999
    plan_event_id = -2147481998
    dose_event_id = -2147481997
    reaction_event_id = -2147481996
    engine = create_engine(database_url(), poolclass=NullPool)
    try:
        with engine.begin() as connection:
            head = connection.exec_driver_sql(
                "SELECT version_num FROM public.alembic_version"
            ).scalar_one()
            if head != CANDIDATE_HEAD:
                fail("trusted medication probe database head changed")
            connection.exec_driver_sql(
                "INSERT INTO public.user_account "
                "(id, phone, username, password, is_admin, sync_flag, deleted) "
                "VALUES (%s, %s, %s, %s, false, 0, 0), "
                "(%s, %s, %s, %s, false, 0, 0)",
                (
                    owner_id,
                    "expand-med-owner",
                    "expand-med-owner",
                    "not-a-production-credential",
                    other_id,
                    "expand-med-other",
                    "expand-med-other",
                    "not-a-production-credential",
                ),
            )
            connection.exec_driver_sql(
                "INSERT INTO public.trusted_medication_plans "
                "(id, user_id, subject_user_id, client_request_id, generic_name, "
                "schedule_times, source_type, source_ref, source_snapshot, "
                "confirmed_by_user_id, confirmed_at) "
                "VALUES (%s, %s, %s, %s, %s, '[]'::jsonb, 'manual', %s, "
                "'{}'::jsonb, %s, now())",
                (
                    plan_id,
                    owner_id,
                    owner_id,
                    "expand-plan-idempotency",
                    "test medicine",
                    "expand-selftest",
                    owner_id,
                ),
            )
            updated = connection.exec_driver_sql(
                "UPDATE public.trusted_medication_plans SET brand_name = %s "
                "WHERE id = %s AND user_id = %s AND subject_user_id = %s",
                ("updated brand", plan_id, owner_id, owner_id),
            )
            if updated.rowcount != 1 or connection.exec_driver_sql(
                "SELECT brand_name FROM public.trusted_medication_plans "
                "WHERE id = %s AND user_id = %s AND subject_user_id = %s",
                (plan_id, owner_id, owner_id),
            ).scalar_one() != "updated brand":
                fail("trusted medication plan CRUD failed")
            expect_integrity(
                connection,
                "INSERT INTO public.trusted_medication_plans "
                "(id, user_id, subject_user_id, client_request_id, generic_name, "
                "schedule_times, source_type, source_ref, source_snapshot, "
                "confirmed_by_user_id, confirmed_at) "
                "VALUES (%s, %s, %s, %s, %s, '[]'::jsonb, 'manual', %s, "
                "'{}'::jsonb, %s, now())",
                (
                    plan_id + 100,
                    owner_id,
                    owner_id,
                    "expand-plan-idempotency",
                    "duplicate",
                    "expand-selftest",
                    owner_id,
                ),
                "duplicate tenant idempotency key",
            )
            connection.exec_driver_sql(
                "INSERT INTO public.medication_prefill_candidates "
                "(id, user_id, subject_user_id, client_event_id, source_type, "
                "source_ref, extracted_data, field_confidences, source_snapshot) "
                "VALUES (%s, %s, %s, %s, 'ocr', %s, '{}'::jsonb, '{}'::jsonb, "
                "'{}'::jsonb)",
                (
                    prefill_id,
                    owner_id,
                    owner_id,
                    "expand-prefill-create",
                    "expand-selftest",
                ),
            )
            connection.exec_driver_sql(
                "UPDATE public.medication_prefill_candidates SET "
                "review_status = 'rejected', reviewed_by_user_id = %s, "
                "reviewed_at = now(), review_client_event_id = %s "
                "WHERE id = %s AND user_id = %s AND subject_user_id = %s",
                (
                    owner_id,
                    "expand-prefill-review",
                    prefill_id,
                    owner_id,
                    owner_id,
                ),
            )
            connection.exec_driver_sql(
                "INSERT INTO public.medication_plan_events "
                "(id, plan_id, user_id, subject_user_id, actor_user_id, "
                "client_event_id, request_fingerprint, event_type, target_version, "
                "before_data, after_data) VALUES "
                "(%s, %s, %s, %s, %s, %s, %s, 'confirm', 1, '{}'::jsonb, "
                "'{}'::jsonb)",
                (
                    plan_event_id,
                    plan_id,
                    owner_id,
                    owner_id,
                    owner_id,
                    "expand-plan-event",
                    "a" * 64,
                ),
            )
            expect_integrity(
                connection,
                "INSERT INTO public.medication_plan_events "
                "(id, plan_id, user_id, subject_user_id, actor_user_id, "
                "client_event_id, request_fingerprint, event_type, target_version, "
                "before_data, after_data) VALUES "
                "(%s, %s, %s, %s, %s, %s, %s, 'confirm', 1, '{}'::jsonb, "
                "'{}'::jsonb)",
                (
                    plan_event_id + 100,
                    plan_id,
                    other_id,
                    other_id,
                    other_id,
                    "expand-cross-tenant-plan",
                    "b" * 64,
                ),
                "cross-tenant plan event",
            )
            connection.exec_driver_sql(
                "INSERT INTO public.medication_dose_events "
                "(id, plan_id, user_id, subject_user_id, actor_user_id, "
                "client_event_id, request_fingerprint, occurrence_key, "
                "scheduled_local_date, scheduled_time, action, effective_status, "
                "occurrence_version, taken_quantity, confirmed_by_user_id, "
                "confirmed_at) VALUES "
                "(%s, %s, %s, %s, %s, %s, %s, %s, current_date, '08:00', "
                "'taken', 'taken', 1, 1, %s, now())",
                (
                    dose_event_id,
                    plan_id,
                    owner_id,
                    owner_id,
                    owner_id,
                    "expand-dose-idempotency",
                    "c" * 64,
                    "expand-dose-occurrence",
                    owner_id,
                ),
            )
            expect_integrity(
                connection,
                "INSERT INTO public.medication_dose_events "
                "(id, plan_id, user_id, subject_user_id, actor_user_id, "
                "client_event_id, request_fingerprint, occurrence_key, "
                "scheduled_local_date, scheduled_time, action, effective_status, "
                "occurrence_version, taken_quantity, confirmed_by_user_id, "
                "confirmed_at) VALUES "
                "(%s, %s, %s, %s, %s, %s, %s, %s, current_date, '09:00', "
                "'taken', 'taken', 1, 1, %s, now())",
                (
                    dose_event_id + 100,
                    plan_id,
                    owner_id,
                    owner_id,
                    owner_id,
                    "expand-dose-idempotency",
                    "d" * 64,
                    "expand-dose-duplicate",
                    owner_id,
                ),
                "duplicate dose client event",
            )
            connection.exec_driver_sql(
                "INSERT INTO public.medication_adverse_reaction_events "
                "(id, plan_id, user_id, subject_user_id, actor_user_id, "
                "client_event_id, request_fingerprint, reaction_key, "
                "reaction_version, event_type, status, symptoms, onset_at, "
                "severity, confirmed_by_user_id, confirmed_at) VALUES "
                "(%s, %s, %s, %s, %s, %s, %s, %s, 1, 'create', 'active', "
                "%s, now(), 'mild', %s, now())",
                (
                    reaction_event_id,
                    plan_id,
                    owner_id,
                    owner_id,
                    owner_id,
                    "expand-reaction-event",
                    "e" * 64,
                    "expand-reaction",
                    "test symptom",
                    owner_id,
                ),
            )
            expect_integrity(
                connection,
                "INSERT INTO public.medication_adverse_reaction_events "
                "(id, plan_id, user_id, subject_user_id, actor_user_id, "
                "client_event_id, request_fingerprint, reaction_key, "
                "reaction_version, event_type, status, symptoms, onset_at, "
                "severity, causal_attribution, confirmed_by_user_id, confirmed_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 1, 'create', "
                "'active', %s, now(), 'mild', 'certain', %s, now())",
                (
                    reaction_event_id + 100,
                    plan_id,
                    owner_id,
                    owner_id,
                    owner_id,
                    "expand-invalid-causality",
                    "f" * 64,
                    "expand-invalid-causality",
                    "test symptom",
                    owner_id,
                ),
                "non-temporal adverse-reaction attribution",
            )

            for table, identifier in (
                ("medication_adverse_reaction_events", reaction_event_id),
                ("medication_dose_events", dose_event_id),
                ("medication_plan_events", plan_event_id),
                ("medication_prefill_candidates", prefill_id),
                ("trusted_medication_plans", plan_id),
            ):
                deleted = connection.exec_driver_sql(
                    "DELETE FROM public.{0} WHERE id = %s".format(table),
                    (identifier,),
                )
                if deleted.rowcount != 1:
                    fail("trusted medication model-backed delete failed: " + table)
            deleted_users = connection.exec_driver_sql(
                "DELETE FROM public.user_account WHERE id IN (%s, %s)",
                (owner_id, other_id),
            )
            if deleted_users.rowcount != 2:
                fail("trusted medication user cleanup failed")
    finally:
        engine.dispose()
    print(json.dumps({
        "schema_version": 1,
        "candidate_head": CANDIDATE_HEAD,
        "table_count": len(EXPECTED_TABLES),
        "catalog_constraints_verified": True,
        "crud_verified": True,
        "tenant_isolation_verified": True,
        "idempotency_verified": True,
    }, ensure_ascii=True, separators=(",", ":")))


if __name__ == "__main__":
    run()
'''


def run_trusted_medication_contract_probe(
    harness,
    candidate_image_id,
    socket_directory,
    migration_password,
):
    source = TRUSTED_MEDICATION_PROBE_TEMPLATE.replace(
        "__CANDIDATE_HEAD__",
        repr(CANDIDATE_HEAD),
    )
    require(
        "__CANDIDATE_HEAD__" not in source,
        "trusted medication probe template is incomplete",
    )
    compile(source, "TRUSTED_MEDICATION_EXPAND_PROBE.py", "exec")
    output = harness.run_one_shot(
        "trusted-medication-contract",
        candidate_image_id,
        python_database_options(socket_directory, migration_password),
        ["-I", "-"],
        input_bytes=source.encode("utf-8"),
        stdout_limit=65536,
        timeout=300,
    )
    result = harness_module.parse_single_json(
        output,
        "trusted medication contract result",
    )
    expected = {
        "schema_version": 1,
        "candidate_head": CANDIDATE_HEAD,
        "table_count": 5,
        "catalog_constraints_verified": True,
        "crud_verified": True,
        "tenant_isolation_verified": True,
        "idempotency_verified": True,
    }
    require(result == expected, "trusted medication contract result is not exact")
    return result


DIETARY_CONCURRENCY_PROBE_TEMPLATE = r'''#!/usr/bin/env python3
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone

from fastapi import HTTPException
from sqlalchemy import URL, create_engine, func, select, text as sql_text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from app.models.dietary_records import (
    DietaryDraft,
    DietaryRecord,
    DietaryRecordEvent,
)
from app.schemas.dietary_records import (
    DietaryDraftConfirmIn,
    DietaryDraftCreateIn,
    DietaryRecordDeleteIn,
    DietaryRecordReuseIn,
    DietaryRecordUpdateIn,
)
from app.services import dietary_records_service as service


CANDIDATE_HEAD = __CANDIDATE_HEAD__
REQUIRED_PG_ENV = ("PGHOST", "PGPORT", "PGUSER", "PGPASSWORD", "PGDATABASE")
OWNER_ID = 2147481000
SUBJECT_ID = OWNER_ID
OWNER_PHONE = "+8613800001000"
OWNER_USERNAME = "pgdietconcurrency"
PROBE_DATE = date(2026, 7, 15)
EATEN_AT = datetime(2026, 7, 15, 5, 30, tzinfo=timezone.utc)
FOOD_ITEM = {
    "item_id": "pg-concurrency-food",
    "name": "并发探针豆腐",
    "portion_text": "一份",
    "categories": ["protein"],
    "confidence": 0.91,
    "is_estimated": True,
}
SHARED_EVENT_ID = "pg-dietary-cross-operation"


def fail(message):
    raise RuntimeError(message)


def require(condition, message):
    if not condition:
        fail(message)


def database_url():
    if any(not os.environ.get(name) for name in REQUIRED_PG_ENV):
        fail("dietary concurrency probe lacks the minimal database identity")
    if (
        os.environ["PGHOST"] != "/var/run/postgresql"
        or os.environ["PGPORT"] != "5432"
        or os.environ["PGUSER"] != "xjie_migration_rehearsal"
        or os.environ["PGDATABASE"] != "xjie_reference"
        or any(name.startswith("DATABASE_") for name in os.environ)
    ):
        fail("dietary concurrency probe is not isolated")
    return URL.create(
        "postgresql+psycopg",
        username=os.environ["PGUSER"],
        password=os.environ["PGPASSWORD"],
        host=os.environ["PGHOST"],
        port=int(os.environ["PGPORT"]),
        database=os.environ["PGDATABASE"],
    )


class MemoryPrivateObjectStore:
    backend_name = "memory"

    def __init__(self):
        self._lock = threading.Lock()
        self._objects = {}
        self.put_calls = 0

    def put(self, *, content, metadata):
        with self._lock:
            self.put_calls += 1
            existing = self._objects.get(metadata.key)
            value = (bytes(content), metadata)
            if existing is not None and existing != value:
                fail("dietary concurrency object collision")
            self._objects[metadata.key] = value

    def get(self, *, metadata, max_bytes):
        with self._lock:
            value = self._objects.get(metadata.key)
        if value is None or value[1] != metadata or len(value[0]) > max_bytes:
            fail("dietary concurrency object lookup changed")
        return value[0]


def normalized(value):
    return service._jsonable(value)


def exact_payload(value):
    return json.dumps(
        normalized(value),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )


def run_pair(session_factory, label, operation):
    barrier = threading.Barrier(2)

    def invoke(index):
        db = session_factory()
        try:
            db.execute(sql_text("SET LOCAL lock_timeout = '15s'"))
            db.execute(sql_text("SET LOCAL statement_timeout = '30s'"))
            barrier.wait(timeout=10)
            try:
                result = operation(db, index)
                db.commit()
                return {"status": 200, "value": normalized(result)}
            except HTTPException as exc:
                db.rollback()
                return {"status": int(exc.status_code), "detail": str(exc.detail)}
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2, thread_name_prefix=label) as executor:
        futures = [executor.submit(invoke, index) for index in range(2)]
        return [future.result(timeout=45) for future in futures]


def require_same_success(results, label):
    require(
        [item["status"] for item in results] == [200, 200],
        label + " did not return two successful replays",
    )
    payloads = [exact_payload(item["value"]) for item in results]
    require(payloads[0] == payloads[1], label + " replay snapshot changed")
    return results[0]["value"]


def require_one_conflict(results, label):
    statuses = sorted(item["status"] for item in results)
    require(statuses == [200, 409], label + " was not exactly one success and one 409")
    return next(item["value"] for item in results if item["status"] == 200)


def require_single_conflict(session_factory, label, operation):
    db = session_factory()
    try:
        db.execute(sql_text("SET LOCAL lock_timeout = '15s'"))
        try:
            operation(db)
        except HTTPException as exc:
            db.rollback()
            require(int(exc.status_code) == 409, label + " did not return 409")
            return
        db.rollback()
        fail(label + " unexpectedly succeeded")
    finally:
        db.close()


def run():
    engine = create_engine(database_url(), poolclass=NullPool)
    session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    provider_lock = threading.Lock()
    provider_calls = {"text": 0, "photo": 0}
    object_store = MemoryPrivateObjectStore()
    original_photo_provider = service.recognize_image_bytes
    try:
        require(
            1 <= len(OWNER_PHONE) <= 20 and 1 <= len(OWNER_USERNAME) <= 80,
            "dietary concurrency fixture identity exceeds the real schema",
        )
        draft_scope_constraint = next(
            constraint
            for constraint in DietaryDraft.__table__.constraints
            if constraint.name == "uq_dietary_draft_tenant_scope_event"
        )
        require(
            [column.name for column in draft_scope_constraint.columns]
            == ["user_id", "subject_user_id", "event_scope", "client_event_id"],
            "dietary draft operation-scoped receipt constraint changed",
        )
        event_scope_constraint = next(
            constraint
            for constraint in DietaryRecordEvent.__table__.constraints
            if constraint.name == "uq_dietary_record_event_tenant_type_event"
        )
        require(
            [column.name for column in event_scope_constraint.columns]
            == ["user_id", "subject_user_id", "event_type", "client_event_id"],
            "dietary record-event operation-scoped receipt constraint changed",
        )
        require(
            DietaryDraft.__table__.c.recognition_status.type.length == 40,
            "dietary recognition status capacity changed",
        )
        with engine.begin() as connection:
            head = connection.exec_driver_sql(
                "SELECT version_num FROM public.alembic_version"
            ).scalar_one()
            require(head == CANDIDATE_HEAD, "dietary concurrency probe head changed")
            connection.exec_driver_sql(
                "INSERT INTO public.user_account "
                "(id, phone, username, password, is_admin, sync_flag, deleted) "
                "VALUES (%s, %s, %s, %s, false, 0, 0)",
                (
                    OWNER_ID,
                    OWNER_PHONE,
                    OWNER_USERNAME,
                    "not-a-production-credential",
                ),
            )

        text_payload = DietaryDraftCreateIn(
            subject_user_id=SUBJECT_ID,
            client_event_id=SHARED_EVENT_ID,
            source_type="text",
            source_ref="pg-concurrency:text",
            timezone="UTC",
            diet_date=PROBE_DATE,
            meal_type="lunch",
            eaten_at=EATEN_AT,
            raw_input="午餐吃了一份豆腐",
            food_items=[],
        )

        def text_provider(_payload):
            with provider_lock:
                provider_calls["text"] += 1
            time.sleep(0.15)
            return {
                "food_items": [FOOD_ITEM],
                "portion_text": "一份",
                "structure": {"protein": "adequate"},
                "estimated_nutrition": {
                    "energy_kcal_range": [160, 220],
                    "is_estimate": True,
                },
                "field_confidences": {"food_items": 0.91},
                "recognition_confidence": 0.91,
                "recognition_status": "completed",
                "recognition_version": "pg-text-extractor.v1",
            }

        text_results = run_pair(
            session_factory,
            "dietary-text-create",
            lambda db, _index: service.create_draft(
                db,
                user_id=OWNER_ID,
                subject_user_id=SUBJECT_ID,
                payload=text_payload,
                recognition_hook=text_provider,
            ),
        )
        text_draft = require_same_success(text_results, "same-event text create")
        require(provider_calls["text"] == 1, "same-event text provider ran more than once")
        conflicting_text_payload = text_payload.model_copy(
            update={"raw_input": "同事件但不同文字"}
        )
        require_single_conflict(
            session_factory,
            "same-endpoint text payload conflict",
            lambda db: service.create_draft(
                db,
                user_id=OWNER_ID,
                subject_user_id=SUBJECT_ID,
                payload=conflicting_text_payload,
                recognition_hook=text_provider,
            ),
        )
        require(provider_calls["text"] == 1, "conflicting text replay reached provider")

        def photo_provider(_content, _filename):
            with provider_lock:
                provider_calls["photo"] += 1
            time.sleep(0.15)
            raise RuntimeError("controlled provider failure")

        service.recognize_image_bytes = photo_provider
        photo_content = b"pg-dietary-photo-concurrency-content"
        photo_results = run_pair(
            session_factory,
            "dietary-photo-create",
            lambda db, _index: service.create_photo_draft(
                db,
                user_id=OWNER_ID,
                subject_user_id=SUBJECT_ID,
                client_event_id=SHARED_EVENT_ID,
                content=photo_content,
                filename="probe.jpg",
                content_type="image/jpeg",
                source_type="camera",
                diet_date=PROBE_DATE,
                meal_type="dinner",
                eaten_at=EATEN_AT,
                timezone_name="UTC",
                object_store=object_store,
            ),
        )
        photo_draft = require_same_success(photo_results, "same-event photo create")
        require(provider_calls["photo"] == 1, "same-event photo provider ran more than once")
        require(object_store.put_calls == 1, "same-event photo object was persisted twice")
        require(
            photo_draft["recognition_status"] == "failed_manual_entry_available",
            "long photo failure status was not persisted",
        )
        require_single_conflict(
            session_factory,
            "same-endpoint photo payload conflict",
            lambda db: service.create_photo_draft(
                db,
                user_id=OWNER_ID,
                subject_user_id=SUBJECT_ID,
                client_event_id=SHARED_EVENT_ID,
                content=photo_content + b"-different",
                filename="probe.jpg",
                content_type="image/jpeg",
                source_type="camera",
                diet_date=PROBE_DATE,
                meal_type="dinner",
                eaten_at=EATEN_AT,
                timezone_name="UTC",
                object_store=object_store,
            ),
        )
        require(provider_calls["photo"] == 1, "conflicting photo replay reached provider")
        require(object_store.put_calls == 1, "conflicting photo replay reached storage")

        confirm_base = {
            "subject_user_id": SUBJECT_ID,
            "expected_version": 1,
            "timezone": "UTC",
            "diet_date": PROBE_DATE,
            "meal_type": "lunch",
            "eaten_at": EATEN_AT,
            "food_items": [FOOD_ITEM],
            "portion_text": "一份",
            "structure": {"protein": "adequate"},
            "estimated_nutrition": {
                "energy_kcal_range": [160, 220],
                "is_estimate": True,
            },
            "field_confidences": {"food_items": 0.91},
            "recognition_confidence": 0.91,
        }
        confirm_results = run_pair(
            session_factory,
            "dietary-confirm-race",
            lambda db, index: service.confirm_draft(
                db,
                draft_id=int(text_draft["draft_id"]),
                user_id=OWNER_ID,
                subject_user_id=SUBJECT_ID,
                payload=DietaryDraftConfirmIn(
                    client_event_id="pg-dietary-confirm-{0}".format(index),
                    **confirm_base,
                ),
            ),
        )
        confirmed_record = require_one_conflict(
            confirm_results,
            "different-event draft confirmation",
        )
        record_id = int(confirmed_record["record_id"])

        reuse_payload = DietaryRecordReuseIn(
            subject_user_id=SUBJECT_ID,
            client_event_id=SHARED_EVENT_ID,
            expected_version=1,
            timezone="UTC",
            diet_date=PROBE_DATE,
            meal_type="dinner",
            eaten_at=EATEN_AT,
        )
        reuse_results = run_pair(
            session_factory,
            "dietary-reuse-replay",
            lambda db, _index: service.reuse_record(
                db,
                record_id=record_id,
                user_id=OWNER_ID,
                subject_user_id=SUBJECT_ID,
                payload=reuse_payload,
            ),
        )
        reused_draft = require_same_success(reuse_results, "same-event record reuse")
        require_single_conflict(
            session_factory,
            "same-endpoint reuse payload conflict",
            lambda db: service.reuse_record(
                db,
                record_id=record_id,
                user_id=OWNER_ID,
                subject_user_id=SUBJECT_ID,
                payload=reuse_payload.model_copy(update={"meal_type": "snack"}),
            ),
        )

        replay_update_payload = DietaryRecordUpdateIn(
            subject_user_id=SUBJECT_ID,
            client_event_id=SHARED_EVENT_ID,
            expected_version=1,
            portion_text="并发回放后的一份",
        )
        replay_update_results = run_pair(
            session_factory,
            "dietary-update-replay",
            lambda db, _index: service.update_record(
                db,
                record_id=record_id,
                user_id=OWNER_ID,
                subject_user_id=SUBJECT_ID,
                payload=replay_update_payload,
            ),
        )
        require_same_success(replay_update_results, "same-event record update")
        require_single_conflict(
            session_factory,
            "same-endpoint update payload conflict",
            lambda db: service.update_record(
                db,
                record_id=record_id,
                user_id=OWNER_ID,
                subject_user_id=SUBJECT_ID,
                payload=replay_update_payload.model_copy(
                    update={"portion_text": "同事件冲突更新"}
                ),
            ),
        )

        update_race_results = run_pair(
            session_factory,
            "dietary-update-race",
            lambda db, index: service.update_record(
                db,
                record_id=record_id,
                user_id=OWNER_ID,
                subject_user_id=SUBJECT_ID,
                payload=DietaryRecordUpdateIn(
                    subject_user_id=SUBJECT_ID,
                    client_event_id="pg-dietary-update-race-{0}".format(index),
                    expected_version=2,
                    portion_text="竞争更新-{0}".format(index),
                ),
            ),
        )
        require_one_conflict(update_race_results, "different-event record update")

        delete_replay_payload = DietaryRecordDeleteIn(
            subject_user_id=SUBJECT_ID,
            client_event_id=SHARED_EVENT_ID,
            expected_version=3,
        )
        delete_replay_results = run_pair(
            session_factory,
            "dietary-delete-replay",
            lambda db, _index: service.delete_record(
                db,
                record_id=record_id,
                user_id=OWNER_ID,
                subject_user_id=SUBJECT_ID,
                payload=delete_replay_payload,
            ),
        )
        require_same_success(delete_replay_results, "same-event record delete")
        require_single_conflict(
            session_factory,
            "same-endpoint delete payload conflict",
            lambda db: service.delete_record(
                db,
                record_id=record_id,
                user_id=OWNER_ID,
                subject_user_id=SUBJECT_ID,
                payload=delete_replay_payload.model_copy(update={"expected_version": 4}),
            ),
        )

        second_confirm_payload = DietaryDraftConfirmIn(
            client_event_id="pg-dietary-reuse-confirm",
            subject_user_id=SUBJECT_ID,
            expected_version=1,
            timezone="UTC",
            diet_date=PROBE_DATE,
            meal_type="dinner",
            eaten_at=EATEN_AT,
            food_items=[FOOD_ITEM],
            portion_text="一份",
            structure={"protein": "adequate"},
            estimated_nutrition={
                "energy_kcal_range": [160, 220],
                "is_estimate": True,
            },
            field_confidences={"food_items": 0.91},
            recognition_confidence=0.91,
        )
        with session_factory() as db:
            second_record = service.confirm_draft(
                db,
                draft_id=int(reused_draft["draft_id"]),
                user_id=OWNER_ID,
                subject_user_id=SUBJECT_ID,
                payload=second_confirm_payload,
            )
            db.commit()
        second_record_id = int(second_record["record_id"])

        delete_race_results = run_pair(
            session_factory,
            "dietary-delete-race",
            lambda db, index: service.delete_record(
                db,
                record_id=second_record_id,
                user_id=OWNER_ID,
                subject_user_id=SUBJECT_ID,
                payload=DietaryRecordDeleteIn(
                    subject_user_id=SUBJECT_ID,
                    client_event_id="pg-dietary-delete-race-{0}".format(index),
                    expected_version=1,
                ),
            ),
        )
        require_one_conflict(delete_race_results, "different-event record delete")

        with session_factory() as db:
            def draft_count(event_scope, client_event_id):
                return db.scalar(
                    select(func.count())
                    .select_from(DietaryDraft)
                    .where(
                        DietaryDraft.user_id == OWNER_ID,
                        DietaryDraft.subject_user_id == SUBJECT_ID,
                        DietaryDraft.event_scope == event_scope,
                        DietaryDraft.client_event_id == client_event_id,
                    )
                )

            def event_count(client_event_ids, event_type=None):
                statement = (
                    select(func.count())
                    .select_from(DietaryRecordEvent)
                    .where(
                        DietaryRecordEvent.user_id == OWNER_ID,
                        DietaryRecordEvent.subject_user_id == SUBJECT_ID,
                        DietaryRecordEvent.client_event_id.in_(client_event_ids),
                    )
                )
                if event_type is not None:
                    statement = statement.where(
                        DietaryRecordEvent.event_type == event_type
                    )
                return db.scalar(statement)

            require(draft_count("create", SHARED_EVENT_ID) == 1, "text replay duplicated a draft")
            require(draft_count("photo", SHARED_EVENT_ID) == 1, "photo replay duplicated a draft")
            require(draft_count("reuse", SHARED_EVENT_ID) == 1, "reuse replay duplicated a draft")
            stored_reuse = db.scalar(
                select(DietaryDraft).where(
                    DietaryDraft.user_id == OWNER_ID,
                    DietaryDraft.subject_user_id == SUBJECT_ID,
                    DietaryDraft.event_scope == "reuse",
                    DietaryDraft.client_event_id == SHARED_EVENT_ID,
                )
            )
            require(
                stored_reuse is not None
                and stored_reuse.recognition_status == "reused_user_confirmed_record",
                "long reuse recognition status was not persisted",
            )
            require(
                event_count(["pg-dietary-confirm-0", "pg-dietary-confirm-1"]) == 1,
                "confirmation race persisted the wrong event count",
            )
            require(
                event_count([SHARED_EVENT_ID], "reuse") == 1,
                "reuse replay persisted the wrong event count",
            )
            require(
                event_count([SHARED_EVENT_ID], "update") == 1,
                "update replay persisted the wrong event count",
            )
            require(
                event_count([SHARED_EVENT_ID], "delete") == 1,
                "delete replay persisted the wrong event count",
            )
            require(
                event_count(["pg-dietary-update-race-0", "pg-dietary-update-race-1"]) == 1,
                "update race persisted the wrong event count",
            )
            require(
                event_count(["pg-dietary-delete-race-0", "pg-dietary-delete-race-1"]) == 1,
                "delete race persisted the wrong event count",
            )
            require(
                event_count([SHARED_EVENT_ID]) == 3,
                "cross-operation record-event receipts collided",
            )
            records = list(
                db.scalars(
                    select(DietaryRecord).where(
                        DietaryRecord.user_id == OWNER_ID,
                        DietaryRecord.subject_user_id == SUBJECT_ID,
                        DietaryRecord.source_draft_id == int(text_draft["draft_id"]),
                    )
                ).all()
            )
            require(len(records) == 1, "confirmation race duplicated the formal record")
            require(
                records[0].version == 4 and records[0].status == "deleted",
                "version races did not produce the exact final record state",
            )
            second = db.get(DietaryRecord, second_record_id)
            require(
                second is not None and second.version == 2 and second.status == "deleted",
                "delete version race did not produce the exact second-record state",
            )

        print(json.dumps({
            "schema_version": 1,
            "candidate_head": CANDIDATE_HEAD,
            "text_create": {"successes": 2, "drafts": 1, "provider_calls": 1},
            "photo_create": {"successes": 2, "drafts": 1, "provider_calls": 1},
            "confirm_race": {"successes": 1, "conflicts": 1, "records": 1},
            "reuse_replay": {"successes": 2, "drafts": 1, "events": 1},
            "update_replay": {"successes": 2, "events": 1},
            "update_race": {"successes": 1, "conflicts": 1, "events": 1},
            "delete_replay": {"successes": 2, "events": 1},
            "delete_race": {"successes": 1, "conflicts": 1, "events": 1},
            "cross_operation_event": {"draft_scopes": 3, "record_event_types": 3},
            "same_endpoint_conflicts": 5,
            "long_statuses_verified": True,
        }, ensure_ascii=True, separators=(",", ":")))
    finally:
        service.recognize_image_bytes = original_photo_provider
        engine.dispose()


if __name__ == "__main__":
    run()
'''


def run_dietary_concurrency_contract_probe(
    harness,
    candidate_image_id,
    socket_directory,
    migration_password,
):
    source = DIETARY_CONCURRENCY_PROBE_TEMPLATE.replace(
        "__CANDIDATE_HEAD__",
        repr(CANDIDATE_HEAD),
    )
    require(
        "__CANDIDATE_HEAD__" not in source,
        "dietary concurrency probe template is incomplete",
    )
    compile(source, "DIETARY_CONCURRENCY_EXPAND_PROBE.py", "exec")
    output = harness.run_one_shot(
        "dietary-concurrency-contract",
        candidate_image_id,
        python_database_options(socket_directory, migration_password),
        ["-I", "-"],
        input_bytes=source.encode("utf-8"),
        stdout_limit=65536,
        timeout=300,
    )
    result = harness_module.parse_single_json(
        output,
        "dietary concurrency contract result",
    )
    expected = {
        "schema_version": 1,
        "candidate_head": CANDIDATE_HEAD,
        "text_create": {"successes": 2, "drafts": 1, "provider_calls": 1},
        "photo_create": {"successes": 2, "drafts": 1, "provider_calls": 1},
        "confirm_race": {"successes": 1, "conflicts": 1, "records": 1},
        "reuse_replay": {"successes": 2, "drafts": 1, "events": 1},
        "update_replay": {"successes": 2, "events": 1},
        "update_race": {"successes": 1, "conflicts": 1, "events": 1},
        "delete_replay": {"successes": 2, "events": 1},
        "delete_race": {"successes": 1, "conflicts": 1, "events": 1},
        "cross_operation_event": {"draft_scopes": 3, "record_event_types": 3},
        "same_endpoint_conflicts": 5,
        "long_statuses_verified": True,
    }
    require(result == expected, "dietary concurrency contract result is not exact")
    return result


def assert_head(
    harness,
    postgres_image_id,
    socket_directory,
    admin_password,
    expected,
    label,
):
    output = harness_module.run_psql(
        harness,
        postgres_image_id,
        socket_directory,
        harness_module.ADMIN_NAME,
        admin_password,
        b"SELECT version_num FROM public.alembic_version;\n",
        label,
        True,
        4096,
    ).decode("utf-8").strip()
    require(output == expected, label + " Alembic head is not exact")


def stamp_materialized_old_head(
    harness,
    postgres_image_id,
    socket_directory,
    admin_password,
):
    """Add the standard Alembic control row omitted by metadata.create_all()."""
    sql = """
CREATE TABLE public.alembic_version (
  version_num VARCHAR(32) NOT NULL,
  CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);
INSERT INTO public.alembic_version (version_num) VALUES ({head});
""".format(head=harness_module.sql_literal(OLD_HEAD))
    harness_module.admin_sql(
        harness,
        postgres_image_id,
        socket_directory,
        admin_password,
        sql,
        "stamp materialized old Alembic head",
    )
    assert_head(
        harness,
        postgres_image_id,
        socket_directory,
        admin_password,
        OLD_HEAD,
        "materialized-old-head",
    )


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Run the real PostgreSQL 16 expand-migration integration gate."
    )
    parser.add_argument(
        "--backend-image",
        required=True,
        help="Already-built linux/amd64 candidate production backend image.",
    )
    return parser.parse_args()


def main():
    require(sys.flags.isolated == 1, "self-test must run with Python isolated mode")
    require(shutil.which("docker") is not None, "docker is unavailable")
    require(shutil.which("git") is not None, "git is unavailable")
    arguments = parse_arguments()
    require(
        arguments.backend_image
        and not arguments.backend_image.startswith("-")
        and "\x00" not in arguments.backend_image,
        "candidate backend image reference is invalid",
    )
    repository_root = Path(__file__).resolve().parent.parent
    global harness_module
    harness_module = load_module(
        repository_root / "tools" / "production_catalog_postgres_selftest.py",
        "xjie_catalog_postgres_selftest_dependency",
    )
    guard, guard_source = harness_module.load_guard(repository_root)
    require(
        guard.REFERENCE_SCHEMA_TABLE_COUNT == CANDIDATE_TABLE_COUNT,
        "candidate reference table pin changed",
    )
    work = Path(
        tempfile.mkdtemp(prefix="xjie-expand-pg-selftest-", dir="/tmp")
    ).resolve()
    os.chmod(work, 0o700)
    harness = harness_module.DockerHarness(work)
    old_tag = None
    restore_volume_name = None
    restore_volume_owned = False
    restore_volume_run_id = None
    expected_main_sha = None
    postgres_image_id = None
    old_handlers = {}

    def interrupted(signum, _frame):
        raise KeyboardInterrupt("signal {0}".format(signum))

    for signum in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
        old_handlers[signum] = signal.signal(signum, interrupted)

    primary_error = None
    cleanup_failures = []
    current_stage = "candidate image identity"
    try:
        candidate_image_id, postgres_image_id = harness_module.assert_image_identity(
            harness,
            arguments.backend_image,
            guard,
        )
        candidate_image = harness.inspect_image(
            candidate_image_id,
            "inspect candidate revision label",
        )
        expected_main_sha = (
            candidate_image.get("Config", {}).get("Labels") or {}
        ).get("org.opencontainers.image.revision")
        require(
            isinstance(expected_main_sha, str)
            and guard.REVISION.fullmatch(expected_main_sha) is not None,
            "candidate image revision label is invalid",
        )
        current_stage = "build exact old backend"
        old_tag, old_image_id = build_old_backend(harness, repository_root, work)
        current_stage = "emit old and candidate manifests"
        old_manifest, old_manifest_path = emit_manifest(
            harness,
            guard,
            guard_source,
            old_image_id,
            work,
            "old",
            OLD_HEAD,
            OLD_MIGRATION_COUNT,
            OLD_TABLE_COUNT,
        )
        candidate_manifest, candidate_manifest_path = emit_manifest(
            harness,
            guard,
            guard_source,
            candidate_image_id,
            work,
            "candidate",
            CANDIDATE_HEAD,
            CANDIDATE_MIGRATION_COUNT,
            CANDIDATE_TABLE_COUNT,
        )
        migration_root = (
            repository_root
            / "backend"
            / "app"
            / "db"
            / "migrations"
            / "versions"
        )
        migration_sources = [
            (migration_root / name).read_bytes()
            for name in (
                "0022_health_trust_contracts.py",
                "0023_trusted_medication_loop.py",
                "0024_health_profile_report_completion.py",
                "0025_dietary_records.py",
            )
        ]
        plan = guard.validate_expand_migration_source(
            migration_sources,
            old_manifest,
            candidate_manifest,
        )
        require(
            plan["old_head"] == OLD_HEAD
            and plan["candidate_head"] == CANDIDATE_HEAD
            and [item["revision"] for item in plan["migrations"]]
            == [
                "0022_health_trust_contracts",
                "0023_trusted_medication_loop",
                "0024_health_profile_report",
                "0025_dietary_records",
            ],
            "expand plan heads changed",
        )

        current_stage = "materialize and back up old schema"
        old_password = os.urandom(32).hex()
        harness.add_secret(old_password)
        old_socket = work / "old-socket"
        old_socket.mkdir(mode=0o777)
        os.chmod(old_socket, 0o777)
        old_server = harness.start_postgres(
            "old-server",
            postgres_image_id,
            old_socket,
            old_password,
        )
        try:
            materialize_manifest(
                harness,
                guard,
                guard_source,
                old_image_id,
                old_manifest,
                old_manifest_path,
                old_socket,
                old_password,
                work,
                "old",
            )
            old_catalog, _, _ = catalog_for_server(
                harness,
                guard,
                guard_source,
                postgres_image_id,
                old_manifest,
                old_manifest_path,
                old_socket,
                old_password,
                work,
                "old-reference",
            )
            comparable_old_catalog = canonicalize_dump_restore_catalog(old_catalog)
            stamp_materialized_old_head(
                harness,
                postgres_image_id,
                old_socket,
                old_password,
            )
            database_size_output = harness_module.run_psql(
                harness,
                postgres_image_id,
                old_socket,
                harness_module.ADMIN_NAME,
                old_password,
                b"SELECT pg_catalog.pg_database_size(current_database());\n",
                "old-production-database-size",
                True,
                4096,
            )
            backup, backup_path, toc_path, backup_attestation = create_backup(
                harness,
                guard,
                postgres_image_id,
                old_socket,
                old_password,
                work,
            )
        finally:
            if old_server in harness._containers:
                harness.stop_postgres(old_server, "old-server")

        current_stage = "materialize candidate reference schema"
        candidate_password = os.urandom(32).hex()
        harness.add_secret(candidate_password)
        candidate_socket = work / "candidate-reference-socket"
        candidate_socket.mkdir(mode=0o777)
        os.chmod(candidate_socket, 0o777)
        candidate_server = harness.start_postgres(
            "candidate-reference-server",
            postgres_image_id,
            candidate_socket,
            candidate_password,
        )
        try:
            materialize_manifest(
                harness,
                guard,
                guard_source,
                candidate_image_id,
                candidate_manifest,
                candidate_manifest_path,
                candidate_socket,
                candidate_password,
                work,
                "candidate-reference",
            )
            candidate_catalog, candidate_catalog_path, _ = catalog_for_server(
                harness,
                guard,
                guard_source,
                postgres_image_id,
                candidate_manifest,
                candidate_manifest_path,
                candidate_socket,
                candidate_password,
                work,
                "candidate-reference",
            )
            comparable_candidate_catalog = canonicalize_dump_restore_catalog(
                candidate_catalog
            )
            harness_module.assert_catalog_inventory(candidate_catalog)
        finally:
            if candidate_server in harness._containers:
                harness.stop_postgres(
                    candidate_server,
                    "candidate-reference-server",
                )

        current_stage = "restore real old backup"
        restore_admin_password = os.urandom(32).hex()
        migration_password = os.urandom(32).hex()
        harness.add_secret(restore_admin_password)
        harness.add_secret(migration_password)
        restore_socket = work / "restore-socket"
        restore_socket.mkdir(mode=0o777)
        os.chmod(restore_socket, 0o777)
        restore_volume_run_id = os.urandom(16).hex()
        restore_volume_name = guard.deployment_name(
            restore_volume_run_id,
            guard.RESTORE_VOLUME_ROLE,
        )
        created_restore_volume_name, restore_volume_inspect = create_restore_volume(
            harness,
            guard,
            expected_main_sha,
            postgres_image_id,
            restore_volume_run_id,
        )
        require(
            created_restore_volume_name == restore_volume_name,
            "restore volume execution name changed",
        )
        restore_volume_owned = True
        restore_volume_attestation = capacity_and_initialize_restore_volume(
            harness,
            guard,
            postgres_image_id,
            restore_volume_name,
            restore_volume_inspect,
            database_size_output,
            backup_attestation,
            expected_main_sha,
            restore_volume_run_id,
        )
        restore_server = harness.start_postgres(
            "restore-server",
            postgres_image_id,
            restore_socket,
            restore_admin_password,
            data_volume=restore_volume_name,
        )
        try:
            restore_backup(
                harness,
                postgres_image_id,
                restore_socket,
                restore_admin_password,
                migration_password,
                backup,
            )
            restored_old_catalog, _, _ = catalog_for_server(
                harness,
                guard,
                guard_source,
                postgres_image_id,
                old_manifest,
                old_manifest_path,
                restore_socket,
                restore_admin_password,
                work,
                "restored-old",
                expects_alembic=True,
            )
            comparable_restored_old_catalog = canonicalize_dump_restore_catalog(
                restored_old_catalog
            )
            restored_old_digest = guard.reference_catalog_sha256(
                comparable_restored_old_catalog
            )
            old_catalog_digest = guard.reference_catalog_sha256(
                comparable_old_catalog
            )
            require(
                restored_old_digest == old_catalog_digest,
                "restored real backup is not the exact old catalog: "
                + (
                    first_catalog_difference(
                        comparable_old_catalog,
                        comparable_restored_old_catalog,
                    )
                    or "catalog digests differ without a structural difference"
                ),
            )
            assert_head(
                harness,
                postgres_image_id,
                restore_socket,
                restore_admin_password,
                OLD_HEAD,
                "restored-old-head",
            )

            current_stage = "prove transactional rollback"
            failed_runner = guard.render_expand_transaction_runner(
                plan,
                fail_after_upgrade=True,
            ).encode("utf-8")
            run_expected_runner_failure(
                harness,
                candidate_image_id,
                restore_socket,
                migration_password,
                failed_runner,
            )
            assert_head(
                harness,
                postgres_image_id,
                restore_socket,
                restore_admin_password,
                OLD_HEAD,
                "post-failpoint-old-head",
            )
            rollback_catalog, _, _ = catalog_for_server(
                harness,
                guard,
                guard_source,
                postgres_image_id,
                old_manifest,
                old_manifest_path,
                restore_socket,
                restore_admin_password,
                work,
                "post-failpoint-old",
                expects_alembic=True,
            )
            require(
                guard.reference_catalog_sha256(
                    canonicalize_dump_restore_catalog(rollback_catalog)
                )
                == guard.reference_catalog_sha256(comparable_old_catalog),
                "transaction failpoint left partial DDL",
            )

            current_stage = "commit expand migration chain"
            runner = guard.render_expand_transaction_runner(plan).encode("utf-8")
            transaction_output = harness.run_one_shot(
                "migration-transaction",
                candidate_image_id,
                python_database_options(restore_socket, migration_password),
                ["-I", "-"],
                input_bytes=runner,
                stdout_limit=65536,
                timeout=300,
            )
            transaction_result = harness_module.parse_single_json(
                transaction_output,
                "migration transaction result",
            )
            guard.validate_expand_transaction_result(plan, transaction_result)
            assert_head(
                harness,
                postgres_image_id,
                restore_socket,
                restore_admin_password,
                CANDIDATE_HEAD,
                "committed-candidate-head",
            )
            migrated_catalog, migrated_catalog_path, _ = catalog_for_server(
                harness,
                guard,
                guard_source,
                postgres_image_id,
                candidate_manifest,
                candidate_manifest_path,
                restore_socket,
                restore_admin_password,
                work,
                "migrated-candidate",
                expects_alembic=True,
            )
            current_stage = "validate expanded physical catalog"
            comparable_migrated_catalog = canonicalize_dump_restore_catalog(
                migrated_catalog
            )
            require(
                guard.reference_catalog_sha256(comparable_migrated_catalog)
                == guard.reference_catalog_sha256(comparable_candidate_catalog),
                "migrated catalog differs from candidate reference after "
                "the bounded dump/restore canonicalization: "
                + (
                    "; ".join(
                        catalog_differences(
                            comparable_candidate_catalog,
                            comparable_migrated_catalog,
                        )
                    )
                    or "catalog digests differ without a structural difference"
                ),
            )
            guard.validate_expand_catalog_transition(
                old_manifest,
                candidate_manifest,
                comparable_old_catalog,
                comparable_migrated_catalog,
                comparable_candidate_catalog,
                plan,
            )

            current_stage = "run old app and trusted medication compatibility"
            old_compat = guard.render_expand_old_app_compat_probe(
                old_manifest,
                plan,
            ).encode("utf-8")
            old_compat_output = harness.run_one_shot(
                "old-image-crud-compat",
                old_image_id,
                python_database_options(restore_socket, migration_password),
                ["-I", "-"],
                input_bytes=old_compat,
                stdout_limit=65536,
                timeout=300,
            )
            old_compat_result = harness_module.parse_single_json(
                old_compat_output,
                "old image CRUD compatibility result",
            )
            guard.validate_expand_old_app_compat_result(
                old_compat_result,
                old_manifest,
                plan,
            )
            trusted_medication_result = run_trusted_medication_contract_probe(
                harness,
                candidate_image_id,
                restore_socket,
                migration_password,
            )
            current_stage = "run real PostgreSQL dietary concurrency contract"
            dietary_concurrency_result = run_dietary_concurrency_contract_probe(
                harness,
                candidate_image_id,
                restore_socket,
                migration_password,
            )
        finally:
            if restore_server in harness._containers:
                harness.stop_postgres(restore_server, "restore-server")
        remove_restore_volume(
            harness,
            guard,
            restore_volume_name,
            expected_main_sha,
            restore_volume_run_id,
            postgres_image_id,
        )
        restore_volume_name = None
        restore_volume_owned = False

        print(
            "POSTGRES EXPAND MIGRATION SELF-TEST: passed; "
            "postgres=16.14 old_sha={0} old_head={1} candidate_head={2} "
            "old_tables={3} candidate_tables={4} backup_sha256={5} "
            "candidate_catalog_sha256={6} restore_volume_identity_sha256={7} "
            "restore_required_bytes={8} old_image_crud=true "
            "trusted_medication_tables={9} tenant=true idempotency=true "
            "dietary_concurrency=true dietary_text_provider_calls={10} "
            "dietary_photo_provider_calls={11} long_statuses=true".format(
                OLD_BACKEND_SHA,
                OLD_HEAD,
                CANDIDATE_HEAD,
                len(old_catalog["tables"]),
                len(candidate_catalog["tables"]),
                backup_attestation["backup_sha256"],
                guard.reference_catalog_sha256(candidate_catalog),
                restore_volume_attestation["volume_identity_sha256"],
                restore_volume_attestation["required_bytes"],
                trusted_medication_result["table_count"],
                dietary_concurrency_result["text_create"]["provider_calls"],
                dietary_concurrency_result["photo_create"]["provider_calls"],
            )
        )
    except BaseException as exc:
        primary_error = ExpandSelfTestError(
            "{0}: {1}".format(current_stage, str(exc))
        )
    finally:
        cleanup_failures = harness.cleanup()
        if restore_volume_owned and restore_volume_name is not None:
            try:
                remove_restore_volume(
                    harness,
                    guard,
                    restore_volume_name,
                    expected_main_sha,
                    restore_volume_run_id,
                    postgres_image_id,
                )
            except BaseException as exc:
                cleanup_failures.append(
                    "restore volume cleanup: " + harness.redact(str(exc))
                )
        if old_tag is not None:
            try:
                _, stderr, return_code = harness.docker(
                    ["image", "rm", old_tag],
                    "remove exact old backend self-test image",
                    timeout=120,
                    stdout_limit=1024 * 1024,
                    stderr_limit=1024 * 1024,
                    check=False,
                )
                if return_code != 0:
                    cleanup_failures.append(
                        "old image tag cleanup failed: "
                        + harness.redact(stderr.decode("utf-8", errors="replace"))
                    )
            except BaseException as exc:
                cleanup_failures.append("old image cleanup: " + harness.redact(str(exc)))
        shutil.rmtree(work, ignore_errors=True)
        for signum, handler in old_handlers.items():
            signal.signal(signum, handler)
    if primary_error is not None:
        detail = harness.redact(str(primary_error))
        if cleanup_failures:
            detail += "; cleanup: " + "; ".join(cleanup_failures)
        raise SystemExit("POSTGRES EXPAND MIGRATION SELF-TEST: failed: " + detail)
    if cleanup_failures:
        raise SystemExit(
            "POSTGRES EXPAND MIGRATION SELF-TEST: failed cleanup: "
            + "; ".join(cleanup_failures)
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
