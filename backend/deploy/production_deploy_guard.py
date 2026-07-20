#!/usr/bin/env python3
"""Fail-closed helpers for recreating the production API container.

The helper never prints environment values.  It validates that the existing
container has no runtime command/image-default overrides, that its complete
HostConfig is reproduced by the declarative candidate, and that the owner-only
server env file contains exactly the runtime environment delta.  It also binds
an owner-only ``docker image save`` archive to the immutable image ID and scans
every saved layer without extracting or following archive links.
"""

import argparse
import ast
import base64
import hashlib
import ipaddress
import json
import math
import os
import posixpath
import re
import secrets
import stat
import sys
import tarfile
import urllib.parse
from pathlib import Path


class DeployGuardError(RuntimeError):
    pass


SPEC_KEYS = (
    "schema_version",
    "container_name",
    "image_repository",
    "secret_env_file",
    "restart_policy",
    "published_ports",
    "extra_hosts",
    "supervised_roles",
    "database_probe_image",
    "container_health_url",
    "public_health_url",
)
PINNED_SPEC = {
    "schema_version": 2,
    "container_name": "xjie-api",
    "image_repository": "xjie-backend",
    "secret_env_file": "/home/mayl/.config/xjie/backend.env",
    "restart_policy": "unless-stopped",
    "published_ports": ["127.0.0.1:8000:8000"],
    "extra_hosts": ["host.docker.internal:host-gateway"],
    "supervised_roles": ["celery-worker", "celery-beat"],
    "database_probe_image": "postgres:16.14-alpine3.23@sha256:bb0628a764d870fed40e71423339e24111bed4a40b614ee68dcbd8981ed6474e",
    "container_health_url": "http://127.0.0.1:8000/healthz",
    "public_health_url": "https://www.jianjieaitech.com/healthz",
}
IMAGE_DEFAULT_FIELDS = (
    "Cmd",
    "Entrypoint",
    "User",
    "WorkingDir",
    "Healthcheck",
    "ExposedPorts",
    "Volumes",
    "OnBuild",
    "ArgsEscaped",
    "StopSignal",
    "Shell",
    "Labels",
)
RUNTIME_CONFIG_DEFAULTS = {
    "AttachStdin": False,
    "AttachStdout": True,
    "AttachStderr": True,
    "OpenStdin": False,
    "StdinOnce": False,
    "Tty": False,
    "Domainname": "",
    "MacAddress": "",
    "NetworkDisabled": False,
    "StopTimeout": None,
}
CONTAINER_CONFIG_KEYS = frozenset(
    {
        "Hostname",
        "Domainname",
        "User",
        "AttachStdin",
        "AttachStdout",
        "AttachStderr",
        "ExposedPorts",
        "Tty",
        "OpenStdin",
        "StdinOnce",
        "Env",
        "Cmd",
        "Healthcheck",
        "ArgsEscaped",
        "Image",
        "Volumes",
        "WorkingDir",
        "Entrypoint",
        "NetworkDisabled",
        "MacAddress",
        "OnBuild",
        "Labels",
        "StopSignal",
        "StopTimeout",
        "Shell",
    }
)
NETWORK_ENDPOINT_KEYS = frozenset(
    {
        "IPAMConfig",
        "Links",
        "Aliases",
        "MacAddress",
        "DriverOpts",
        "GwPriority",
        "NetworkID",
        "EndpointID",
        "Gateway",
        "IPAddress",
        "IPPrefixLen",
        "IPv6Gateway",
        "GlobalIPv6Address",
        "GlobalIPv6PrefixLen",
        "DNSNames",
    }
)
NETWORK_IPAM_KEYS = frozenset({"IPv4Address", "IPv6Address", "LinkLocalIPs"})
EMITTED_SPEC_KEYS = (
    "container_name",
    "image_repository",
    "secret_env_file",
    "database_probe_image",
    "container_health_url",
    "public_health_url",
)
JOURNAL_SCHEMA_VERSION = 2
JOURNAL_STATES = (
    "prepared",
    "old_stopped",
    "old_renamed",
    "candidate_renamed",
    "candidate_started",
)
JOURNAL_KEYS = (
    "schema_version",
    "state",
    "expected_sha",
    "trusted_bundle_sha256",
    "container_name",
    "backup_name",
    "candidate_name",
    "old_container_id",
    "candidate_container_id",
    "old_image_id",
    "candidate_image_id",
)
EMITTED_JOURNAL_KEYS = JOURNAL_KEYS[1:]
RECOVERY_ACTIONS = (
    "stop_official_candidate",
    "quarantine_official_candidate",
    "rename_backup_to_official",
    "start_official",
    "verify_named_candidate_quarantined",
    "verify_official_old",
)
DEPLOY_LABEL_PREFIX = "com.jianjieaitech.xjie.deploy."
DEPLOY_LABEL_KEYS = (
    DEPLOY_LABEL_PREFIX + "schema",
    DEPLOY_LABEL_PREFIX + "scope",
    DEPLOY_LABEL_PREFIX + "branch",
    DEPLOY_LABEL_PREFIX + "revision",
    DEPLOY_LABEL_PREFIX + "run-id",
    DEPLOY_LABEL_PREFIX + "role",
    DEPLOY_LABEL_PREFIX + "original-name",
    DEPLOY_LABEL_PREFIX + "image-id",
    DEPLOY_LABEL_PREFIX + "cleanup-phase",
)
DEPLOY_ROLES = (
    "candidate",
    "celery-worker",
    "celery-beat",
    "backend-test",
    "alembic-heads",
    "alembic-current",
    "database-schema",
    "schema-reference-server",
    "schema-reference-materializer",
    "schema-reference-catalog",
    "literature-ingest",
    "schema-old",
    "schema-candidate",
    "schema-backup",
    "schema-backup-toc",
    "schema-restore",
    "schema-migration-rehearsal",
    "schema-migration-production",
    "schema-old-compat",
    "schema-restore-capacity",
    "schema-restore-volume-init",
    "schema-restore-server",
)
RESTORE_VOLUME_ROLE = "schema-restore-volume"
DEPLOY_LIFECYCLE_ROLES = (*DEPLOY_ROLES, RESTORE_VOLUME_ROLE)
DEPLOY_ROLE_COMMANDS = {
    "celery-worker": (
        None,
        (
            "python",
            "-I",
            "-m",
            "celery",
            "--app",
            "app.workers.celery_app:celery_app",
            "worker",
            "--loglevel=INFO",
            "--concurrency=2",
            "--hostname=xjie-worker@%h",
            "--without-gossip",
            "--without-mingle",
        ),
    ),
    "celery-beat": (
        None,
        (
            "python",
            "-I",
            "-m",
            "celery",
            "--app",
            "app.workers.celery_app:celery_app",
            "beat",
            "--loglevel=INFO",
            "--schedule=/tmp/celerybeat-schedule",
            "--pidfile=/tmp/celerybeat.pid",
        ),
    ),
    "backend-test": (
        ("python",),
        ("-I", "-m", "pytest", "tests", "-q", "--junitxml=/tmp/xjie-backend-full.xml"),
    ),
    "alembic-heads": (None, ("alembic", "heads", "--verbose")),
    "alembic-current": (None, ("alembic", "current", "--verbose")),
    "database-schema": (
        ("/usr/local/bin/psql",),
        (
            "--no-psqlrc",
            "--quiet",
            "--tuples-only",
            "--no-align",
            "--set",
            "ON_ERROR_STOP=1",
        ),
    ),
    "schema-reference-server": (
        ("docker-entrypoint.sh",),
        (
            "postgres",
            "-c",
            "listen_addresses=",
            "-c",
            "unix_socket_directories=/var/run/postgresql",
        ),
    ),
    "schema-reference-materializer": (("python",), ("-I", "-")),
    "schema-reference-catalog": (
        ("/usr/local/bin/psql",),
        (
            "--no-psqlrc",
            "--quiet",
            "--tuples-only",
            "--no-align",
            "--set",
            "ON_ERROR_STOP=1",
        ),
    ),
    "literature-ingest": (
        None,
        (
            "python",
            "-I",
            "-m",
            "app.workers.literature_ingest",
            "--seed",
            "app/workers/literature_seeds.json",
        ),
    ),
    "schema-old": (("python",), ("-I", "-")),
    "schema-candidate": (("python",), ("-I", "-")),
    "schema-backup": (
        ("/usr/local/bin/pg_dump",),
        (
            "--format=custom",
            "--compress=gzip:9",
            "--no-owner",
            "--no-privileges",
            "--serializable-deferrable",
        ),
    ),
    "schema-backup-toc": (("/usr/local/bin/pg_restore",), ("--list",)),
    "schema-restore": (
        ("/usr/local/bin/pg_restore",),
        (
            "--exit-on-error",
            "--no-owner",
            "--no-privileges",
            "--role=xjie_migration_rehearsal",
            "--dbname=xjie_reference",
        ),
    ),
    "schema-migration-rehearsal": (("python",), ("-I", "-")),
    "schema-migration-production": (("python",), ("-I", "-")),
    "schema-old-compat": (("python",), ("-I", "-")),
    "schema-restore-capacity": (
        ("/bin/stat",),
        ("-f", "-c", "%a %S", "/var/lib/postgresql/data"),
    ),
    "schema-restore-volume-init": (
        ("/bin/sh",),
        (
            "-ceu",
            "chmod 0700 /var/lib/postgresql/data && "
            "chown 70:70 /var/lib/postgresql/data",
        ),
    ),
    "schema-restore-server": (
        ("docker-entrypoint.sh",),
        (
            "postgres",
            "-c",
            "listen_addresses=",
            "-c",
            "unix_socket_directories=/var/run/postgresql",
        ),
    ),
}
CANDIDATE_COMMAND = (
    "uvicorn",
    "app.main:app",
    "--host",
    "0.0.0.0",
    "--port",
    "8000",
)
SUPERVISED_SERVICE_ROLES = frozenset(PINNED_SPEC["supervised_roles"])
LONG_RUNNING_ROLES = frozenset({"candidate", *SUPERVISED_SERVICE_ROLES})
RUNTIME_ENV_ROLES = frozenset(
    {
        "candidate",
        *SUPERVISED_SERVICE_ROLES,
        "alembic-heads",
        "alembic-current",
        "database-schema",
        "literature-ingest",
    }
)
ISOLATED_NETWORK_ROLES = frozenset(
    {
        "backend-test",
        "schema-old",
        "schema-candidate",
        "schema-reference-server",
        "schema-reference-materializer",
        "schema-reference-catalog",
        "schema-backup-toc",
        "schema-restore",
        "schema-migration-rehearsal",
        "schema-old-compat",
        "schema-restore-capacity",
        "schema-restore-volume-init",
        "schema-restore-server",
    }
)
REFERENCE_SCHEMA_ROLES = frozenset(
    {
        "schema-reference-server",
        "schema-reference-materializer",
        "schema-reference-catalog",
    }
)
EXPAND_SOCKET_ROLES = frozenset(
    {
        "schema-restore",
        "schema-migration-rehearsal",
        "schema-old-compat",
    }
)
PRODUCTION_MIGRATION_ROLES = frozenset(
    {"schema-backup", "schema-migration-production"}
)
EXPAND_REHEARSAL_ROLES = frozenset(
    {"schema-reference-server", "schema-restore-server", *EXPAND_SOCKET_ROLES}
)
HARDENED_PROBE_ROLES = frozenset(
    {
        *SUPERVISED_SERVICE_ROLES,
        "database-schema",
        "literature-ingest",
        "schema-old",
        "schema-candidate",
        *REFERENCE_SCHEMA_ROLES,
        "schema-backup",
        "schema-backup-toc",
        *EXPAND_SOCKET_ROLES,
        "schema-migration-production",
        "schema-restore-capacity",
        "schema-restore-volume-init",
        "schema-restore-server",
    }
)
AUTO_REMOVE_ROLES = frozenset()
INTERACTIVE_ROLES = frozenset(
    {
        "database-schema",
        "schema-old",
        "schema-candidate",
        "schema-reference-materializer",
        "schema-reference-catalog",
        "schema-backup-toc",
        *EXPAND_SOCKET_ROLES,
        "schema-migration-production",
    }
)
RESTORE_VOLUME_CONTAINER_ROLES = frozenset(
    {
        "schema-restore-capacity",
        "schema-restore-volume-init",
        "schema-restore-server",
    }
)
SCHEMA_PROBE_TMPFS = {"/tmp": "rw,noexec,nosuid,nodev,size=16m"}
SCHEMA_PROBE_TMPFS_ARGUMENT = "/tmp:" + SCHEMA_PROBE_TMPFS["/tmp"]
SUPERVISED_SERVICE_TMPFS = {
    "/tmp": "rw,noexec,nosuid,nodev,size=64m,mode=1777"
}
DATABASE_PROBE_TMPFS = {
    "/tmp": "rw,noexec,nosuid,nodev,size=16m,mode=1777",
    "/var/lib/postgresql/data": (
        "rw,noexec,nosuid,nodev,size=16m,uid=70,gid=70,mode=0700"
    ),
}
REFERENCE_MATERIALIZER_TMPFS = {
    "/tmp": "rw,noexec,nosuid,nodev,size=16m,mode=1777",
}
REFERENCE_SERVER_TMPFS = {
    **REFERENCE_MATERIALIZER_TMPFS,
    "/var/lib/postgresql/data": (
        "rw,noexec,nosuid,nodev,size=256m,uid=70,gid=70,mode=0700"
    ),
}
RESTORE_SERVER_TMPFS = dict(REFERENCE_MATERIALIZER_TMPFS)
REFERENCE_CATALOG_TMPFS = dict(DATABASE_PROBE_TMPFS)
REFERENCE_SOCKET_SOURCE = re.compile(
    r"/dev/shm/xjie-deploy-[0-9]+/runtime/reference-pg-socket\Z"
)
REFERENCE_SOCKET_DESTINATION = "/var/run/postgresql"
RESTORE_VOLUME_DESTINATION = "/var/lib/postgresql/data"
RESTORE_VOLUME_NAME = re.compile(
    r"xjie-api-deploy-([0-9a-f]{32})-schema-restore-volume\Z"
)
REFERENCE_DATABASE_URI = re.compile(
    r"postgresql\+psycopg://xjie_reference:([0-9a-f]{64})@/xjie_reference"
    r"\?host=/var/run/postgresql\Z"
)
REFERENCE_ROLE_RESOURCES = {
    "celery-worker": ("65534:65534", 30, 512 * 1024 * 1024, 128),
    "celery-beat": ("65534:65534", 30, 256 * 1024 * 1024, 64),
    "database-schema": ("70:70", None, 256 * 1024 * 1024, 128),
    "schema-reference-server": ("70:70", 20, 512 * 1024 * 1024, 256),
    "schema-reference-materializer": (
        "65534:65534",
        None,
        512 * 1024 * 1024,
        256,
    ),
    "schema-reference-catalog": ("70:70", None, 256 * 1024 * 1024, 128),
    "schema-backup": ("70:70", None, 512 * 1024 * 1024, 128),
    "schema-backup-toc": ("70:70", None, 256 * 1024 * 1024, 128),
    "schema-restore": ("70:70", None, 512 * 1024 * 1024, 128),
    "schema-migration-rehearsal": (
        "65534:65534",
        None,
        512 * 1024 * 1024,
        128,
    ),
    "schema-migration-production": (
        "65534:65534",
        None,
        512 * 1024 * 1024,
        128,
    ),
    "schema-old-compat": ("65534:65534", None, 512 * 1024 * 1024, 128),
    "schema-restore-capacity": ("70:70", None, 256 * 1024 * 1024, 64),
    "schema-restore-volume-init": ("0:0", None, 128 * 1024 * 1024, 32),
    "schema-restore-server": ("70:70", 20, 1024 * 1024 * 1024, 256),
}
REQUIRED_IMAGE_ENVIRONMENT = {
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONUNBUFFERED": "1",
}
ORPHAN_PLAN_VERSION = "orphan-cleanup-v1"
BACKUP_RETENTION_PLAN_VERSION = "backup-retention-v1"
ORPHAN_PLAN_RECORD_SIZE = 7
MAX_GIT_TREE_MANIFEST_BYTES = 16 * 1024 * 1024
MAX_GIT_TREE_ENTRIES = 100000
GIT_OBJECT_ID = re.compile(r"[0-9a-f]{40}\Z")
ENVIRONMENT_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
REVISION = re.compile(r"[0-9a-f]{40}\Z")
DEPLOY_RUN_ID = re.compile(r"[0-9a-f]{32}\Z")
CONTAINER_ID = re.compile(r"[0-9a-f]{64}\Z")
IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")
CONTAINER_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
BACKUP_CONTAINER_NAME = re.compile(
    r"xjie-api-backup-main-[0-9a-f]{12}-[0-9]{14}\Z"
)
ALEMBIC_REVISION = re.compile(r"^Rev:\s+([^\s]+)(?:\s+\(head\))?\s*$", re.MULTILINE)
MAX_ENV_FILE_BYTES = 1024 * 1024
MAX_IMAGE_INSPECT_BYTES = 16 * 1024 * 1024
MAX_IMAGE_ARCHIVE_BYTES = 8 * 1024 * 1024 * 1024
MAX_IMAGE_ARCHIVE_MEMBER_BYTES = 4 * 1024 * 1024 * 1024
MAX_IMAGE_ARCHIVE_MEMBERS = 500000
MAX_IMAGE_MANIFEST_BYTES = 1024 * 1024
MAX_IMAGE_PATH_BYTES = 4096
IMAGE_ARCHIVE_READ_BYTES = 64 * 1024
IMAGE_ARCHIVE_MARKERS = (
    b"-----BEGIN PRIVATE KEY",
    b"-----BEGIN OPENSSH PRIVATE KEY",
    b"-----BEGIN RSA PRIVATE KEY",
    b"-----BEGIN EC PRIVATE KEY",
    b"SQLite format 3\x00",
)
IMAGE_UNSAFE_NAMES = frozenset({".env", "id_rsa", "id_ed25519"})
IMAGE_UNSAFE_SUFFIXES = frozenset(
    {".key", ".p8", ".p12", ".pfx", ".sqlite", ".db"}
)
SENSITIVE_ENVIRONMENT_NAME = re.compile(
    r"(?:SECRET|TOKEN|PASSWORD|PASSWD|PRIVATE|CREDENTIAL|API_KEY|DATABASE_URL|"
    r"REDIS_URL|DSN|SIGNING|AUTH_KEY)",
    re.IGNORECASE,
)
MIGRATION_PROBE_SCHEMA_VERSION = 1
MIGRATION_PROBE_KEYS = (
    "schema_version",
    "migrations",
    "heads",
    "model_schema",
)
MIGRATION_ENTRY_KEYS = ("revision", "down_revision", "sha256")
MODEL_TABLE_KEYS = ("name", "schema", "columns", "constraints", "indexes")
MODEL_COLUMN_KEYS = (
    "name",
    "type",
    "nullable",
    "primary_key",
    "autoincrement",
    "default",
    "server_default",
    "onupdate",
    "server_onupdate",
    "identity",
    "computed",
    "comment",
)
MODEL_TYPE_KEYS = ("class", "sql", "cache_key", "attributes")
MODEL_DEFAULT_KEYS = ("kind", "value")
MODEL_IDENTITY_KEYS = (
    "always",
    "start",
    "increment",
    "minvalue",
    "maxvalue",
    "nominvalue",
    "nomaxvalue",
    "cycle",
    "cache",
    "order",
    "on_null",
)
MODEL_COMPUTED_KEYS = ("sql", "persisted")
MODEL_CONSTRAINT_KEYS = (
    "kind",
    "name",
    "columns",
    "references",
    "options",
    "expression",
)
MODEL_INDEX_KEYS = ("name", "unique", "expressions", "options")
MODEL_CATALOG_SCHEMA_VERSION = 3
PHYSICAL_CATALOG_KEYS = (
    "schema_version",
    "candidate_manifest_sha256",
    "server_major",
    "database_encoding",
    "database_collate",
    "database_ctype",
    "database_locale_provider",
    "database_collation_version",
    "database_icu_locale",
    "database_icu_rules",
    "standard_conforming_strings",
    "tables",
    "sequences",
    "enum_types",
)
PHYSICAL_TABLE_KEYS = (
    "schema",
    "name",
    "kind",
    "persistence",
    "access_method",
    "row_security",
    "force_row_security",
    "replica_identity",
    "options",
    "columns",
    "constraints",
    "indexes",
)
PHYSICAL_COLUMN_KEYS = (
    "position",
    "name",
    "type",
    "nullable",
    "default",
    "identity",
    "generated",
    "collation",
    "compression",
    "storage",
    "owned_sequence",
)
PHYSICAL_TYPE_KEYS = (
    "schema",
    "name",
    "formatted",
    "kind",
    "category",
    "dimensions",
    "enum_labels",
    "array_item",
)
PHYSICAL_COLLATION_KEYS = ("schema", "name")
PHYSICAL_CONSTRAINT_KEYS = (
    "name",
    "type",
    "definition",
    "columns",
    "references",
    "deferrable",
    "deferred",
    "validated",
    "no_inherit",
    "nulls_not_distinct",
)
PHYSICAL_REFERENCE_KEYS = ("schema", "table", "columns")
PHYSICAL_INDEX_KEYS = (
    "name",
    "unique",
    "nulls_not_distinct",
    "clustered",
    "replica_identity",
    "valid",
    "ready",
    "live",
    "constraint",
    "method",
    "definition",
    "predicate",
    "expressions",
    "include_columns",
    "options",
    "tablespace",
)
PHYSICAL_INDEX_CONSTRAINT_KEYS = ("name", "type")
PHYSICAL_SEQUENCE_KEYS = (
    "schema",
    "name",
    "data_type",
    "start",
    "increment",
    "minimum",
    "maximum",
    "cache",
    "cycle",
    "owned_by",
)
PHYSICAL_SEQUENCE_OWNER_KEYS = ("schema", "table", "column", "dependency")
PHYSICAL_ENUM_KEYS = ("schema", "name", "labels")
DATABASE_SCHEMA_LEGACY_ALLOWLIST_VERSION = 1
DATABASE_SCHEMA_LEGACY_PUBLIC_TABLES = ("alembic_version",)
DATABASE_SCHEMA_RESULT_KEYS = (
    "schema_version",
    "candidate_manifest_sha256",
    "reference_catalog_sha256",
    "observed_catalog_sha256",
    "server_major",
    "table_count",
)
MIGRATION_REVISION = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
SHA256_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
MAX_MIGRATION_MANIFEST_BYTES = 16 * 1024 * 1024
MAX_MIGRATION_OUTPUT_BYTES = 1024 * 1024
MAX_REFERENCE_CATALOG_BYTES = 16 * 1024 * 1024
MAX_REFERENCE_MATERIALIZER_RESULT_BYTES = 64 * 1024
REFERENCE_SCHEMA_TABLE_COUNT = 95
REFERENCE_MATERIALIZER_RESULT_KEYS = (
    "schema_version",
    "candidate_manifest_sha256",
    "table_count",
)
MAX_DATABASE_SCHEMA_RESULT_BYTES = 64 * 1024
DATABASE_PROBE_URL_KEY = "DATABASE_PROBE_URL"
DATABASE_MIGRATION_URL_KEY = "DATABASE_MIGRATION_URL"
DATABASE_PROBE_PGOPTIONS = "-c default_transaction_read_only=on"
REFERENCE_DATABASE_URL_KEY = "XJIE_REFERENCE_DATABASE_URL"
REFERENCE_DATABASE_USER = "xjie_reference"
REFERENCE_DATABASE_NAME = "xjie_reference"
REFERENCE_DATABASE_SOCKET = "/var/run/postgresql"
PINNED_POSTGRESQL_MAJOR = 16
EXPAND_MIGRATION_POLICY_SCHEMA_VERSION = 1
EXPAND_MIGRATION_PLAN_SCHEMA_VERSION = 2
EXPAND_MIGRATION_PLAN_KEYS = (
    "schema_version",
    "old_manifest_sha256",
    "old_head",
    "candidate_manifest_sha256",
    "candidate_head",
    "migrations",
    "migration_sha256",
    "operation_policy_sha256",
    "operations",
)
EXPAND_MIGRATION_ITEM_KEYS = (
    "revision",
    "down_revision",
    "sha256",
)
EXPAND_OPERATION_KEYS = ("op", "table", "name", "columns")
MAX_EXPAND_MIGRATION_SOURCE_BYTES = 2 * 1024 * 1024
MAX_EXPAND_MIGRATIONS = 16
MAX_EXPAND_MIGRATION_SOURCE_BUNDLE_BYTES = (
    MAX_EXPAND_MIGRATIONS * MAX_EXPAND_MIGRATION_SOURCE_BYTES * 2
)
EXPAND_MIGRATION_SOURCE_BUNDLE_SCHEMA_VERSION = 1
EXPAND_MIGRATION_SOURCE_BUNDLE_KEYS = ("schema_version", "migrations")
EXPAND_MIGRATION_SOURCE_ITEM_KEYS = ("revision", "sha256", "source_base64")
EXPAND_APPROVAL_PLAN_SCHEMA_VERSION = 2
EXPAND_APPROVAL_PLAN_KEYS = (
    "schema_version",
    "expected_main_sha",
    "trusted_bundle_sha256",
    "old_manifest_sha256",
    "old_head",
    "candidate_manifest_sha256",
    "candidate_head",
    "migrations",
    "migration_sha256",
    "operation_policy_sha256",
    "old_catalog_sha256",
    "candidate_catalog_sha256",
)
EXPAND_JOURNAL_SCHEMA_VERSION = 2
EXPAND_JOURNAL_STATES = (
    "approved",
    "backup_verified",
    "restore_verified",
    "production_transaction_started",
    "production_schema_attested",
    "cutover_started",
    "completed",
)
EXPAND_JOURNAL_KEYS = (
    "schema_version",
    "state",
    "expected_main_sha",
    "trusted_bundle_sha256",
    "approval_sha256",
    "plan_sha256",
    "old_head",
    "candidate_head",
    "old_manifest_sha256",
    "candidate_manifest_sha256",
    "migration_sha256",
    "operation_policy_sha256",
    "old_catalog_sha256",
    "candidate_catalog_sha256",
    "backup_path",
    "backup_size",
    "backup_sha256",
    "backup_toc_sha256",
    "restore_volume_name",
    "restore_volume_identity_sha256",
    "restore_database_size_bytes",
    "restore_required_bytes",
    "restore_available_bytes",
    "old_image_id",
    "candidate_image_id",
)
EXPAND_BACKUP_ATTESTATION_KEYS = (
    "backup_path",
    "backup_size",
    "backup_sha256",
    "backup_toc_sha256",
)
EXPAND_RESTORE_VOLUME_ATTESTATION_SCHEMA_VERSION = 1
EXPAND_RESTORE_VOLUME_ATTESTATION_KEYS = (
    "schema_version",
    "volume_name",
    "expected_main_sha",
    "run_id",
    "database_probe_image_id",
    "backup_sha256",
    "backup_size",
    "database_size_bytes",
    "required_bytes",
    "available_bytes",
    "volume_identity_sha256",
)
EXPAND_EVIDENCE_SCHEMA_VERSION = 3
EXPAND_EVIDENCE_KEYS = (
    "schema_version",
    "expected_main_sha",
    "trusted_bundle_sha256",
    "approval_sha256",
    "plan_sha256",
    "old_head",
    "candidate_head",
    "old_manifest_sha256",
    "candidate_manifest_sha256",
    "migration_sha256",
    "operation_policy_sha256",
    "old_catalog_sha256",
    "candidate_catalog_sha256",
    "backup_size",
    "backup_sha256",
    "backup_toc_sha256",
    "restore_volume_name",
    "restore_volume_identity_sha256",
    "restore_database_size_bytes",
    "restore_required_bytes",
    "restore_available_bytes",
    "old_image_id",
    "candidate_image_id",
    "rehearsal_transaction_result_sha256",
    "old_app_compat_result_sha256",
    "transaction_result_sha256",
    "post_catalog_sha256",
)
MAX_EXPAND_APPROVAL_PLAN_BYTES = 64 * 1024
MAX_EXPAND_JOURNAL_BYTES = 128 * 1024
MAX_EXPAND_BACKUP_BYTES = 64 * 1024 * 1024 * 1024
MAX_EXPAND_BACKUP_TOC_BYTES = 64 * 1024 * 1024
MAX_EXPAND_EVIDENCE_BYTES = 128 * 1024
MAX_EXPAND_RESTORE_CAPACITY_OUTPUT_BYTES = 4096
MAX_EXPAND_RESTORE_DATABASE_BYTES = 64 * 1024 * 1024 * 1024 * 1024
MIN_EXPAND_RESTORE_HEADROOM_BYTES = 1024 * 1024 * 1024
EXPAND_RESTORE_CAPACITY_MULTIPLIER = 2
RESTORE_VOLUME_CLEANUP_PLAN_VERSION = "restore-volume-cleanup-v1"
_EXPAND_ALLOWED_SA_CALLS = frozenset(
    {
        "sa.BigInteger",
        "sa.Boolean",
        "sa.CheckConstraint",
        "sa.Column",
        "sa.Date",
        "sa.DateTime",
        "sa.ForeignKeyConstraint",
        "sa.false",
        "sa.Integer",
        "sa.Numeric",
        "sa.String",
        "sa.Text",
        "sa.UniqueConstraint",
        "sa.func.now",
        "sa.text",
        "sa.true",
    }
)
_EXPAND_SAFE_TEXT_DEFAULT = re.compile(
    r"'(?:[A-Za-z0-9_.:-]{0,128}|\{\}|\[\])'(?:::[A-Za-z0-9_.\[\]]+)?\Z"
)
MIGRATION_PROBE_SOURCE = r'''#!/usr/bin/env python3
import ast
import enum
import hashlib
import importlib
import json
import math
import stat
import sys
from pathlib import Path


SCHEMA_VERSION = 1
APPLICATION_ROOT = Path("/app")
PACKAGE_ROOT = APPLICATION_ROOT / "app"
MODEL_ROOT = PACKAGE_ROOT / "models"
MIGRATION_ROOT = PACKAGE_ROOT / "db" / "migrations" / "versions"
MAX_SOURCE_BYTES = 2 * 1024 * 1024


def _regular_source(path, label):
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise RuntimeError(label + " is not a single regular file")
    if metadata.st_size > MAX_SOURCE_BYTES:
        raise RuntimeError(label + " is too large")
    payload = path.read_bytes()
    if len(payload) != metadata.st_size:
        raise RuntimeError(label + " changed while it was read")
    return payload


def _qualified_name(value):
    module = getattr(value, "__module__", None)
    name = getattr(value, "__qualname__", None)
    if not isinstance(module, str) or not module or not isinstance(name, str) or not name:
        raise RuntimeError("value has no stable qualified name")
    return module + "." + name


def _json_value(value):
    if value is None or type(value) in (bool, int, str):
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise RuntimeError("non-finite model metadata value")
        return value
    if isinstance(value, type):
        return {"class": _qualified_name(value)}
    if isinstance(value, enum.Enum):
        return {
            "enum_class": _qualified_name(type(value)),
            "name": value.name,
            "value": _json_value(value.value),
        }
    if isinstance(value, str):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        if any(type(key) is not str for key in value):
            raise RuntimeError("model metadata mapping key is not a string")
        return {key: _json_value(value[key]) for key in sorted(value)}
    raise RuntimeError("model metadata value has no stable JSON representation")


def _sql_text(value, dialect):
    try:
        return str(
            value.compile(
                dialect=dialect,
                compile_kwargs={"literal_binds": True},
            )
        )
    except Exception as exc:
        raise RuntimeError("cannot compile model SQL metadata") from exc


def _default_value(value, dialect):
    if value is None:
        return None
    argument = value.arg
    if getattr(value, "is_callable", False):
        while hasattr(argument, "__wrapped__"):
            argument = argument.__wrapped__
        return {"kind": "callable", "value": _qualified_name(argument)}
    if getattr(value, "is_scalar", False):
        return {"kind": "scalar", "value": _json_value(argument)}
    if getattr(value, "is_clause_element", False) or hasattr(argument, "compile"):
        return {"kind": "sql", "value": _sql_text(argument, dialect)}
    return {"kind": "scalar", "value": _json_value(argument)}


def _identity_value(value):
    if value is None:
        return None
    return {
        "always": _json_value(getattr(value, "always", None)),
        "start": _json_value(getattr(value, "start", None)),
        "increment": _json_value(getattr(value, "increment", None)),
        "minvalue": _json_value(getattr(value, "minvalue", None)),
        "maxvalue": _json_value(getattr(value, "maxvalue", None)),
        "nominvalue": _json_value(getattr(value, "nominvalue", None)),
        "nomaxvalue": _json_value(getattr(value, "nomaxvalue", None)),
        "cycle": _json_value(getattr(value, "cycle", None)),
        "cache": _json_value(getattr(value, "cache", None)),
        "order": _json_value(getattr(value, "order", None)),
        "on_null": _json_value(getattr(value, "on_null", None)),
    }


def _computed_value(value, dialect):
    if value is None:
        return None
    return {
        "sql": _sql_text(value.sqltext, dialect),
        "persisted": _json_value(value.persisted),
    }


def _type_value(value, dialect):
    try:
        sql = str(value.compile(dialect=dialect))
        dialect_value = value.dialect_impl(dialect)
    except Exception as exc:
        raise RuntimeError("cannot compile model column type") from exc
    attributes = {}
    for name in (
        "length",
        "collation",
        "precision",
        "scale",
        "decimal_return_scale",
        "asdecimal",
        "timezone",
        "native_enum",
        "create_constraint",
        "validate_strings",
        "name",
        "schema",
        "inherit_schema",
        "none_as_null",
        "dimensions",
        "zero_indexes",
    ):
        if hasattr(value, name):
            attributes[name] = _json_value(getattr(value, name))
        elif hasattr(dialect_value, name):
            attributes[name] = _json_value(getattr(dialect_value, name))
    enum_values = getattr(value, "enums", None)
    if enum_values is None:
        enum_values = getattr(dialect_value, "enums", None)
    if enum_values is not None:
        attributes["enums"] = _json_value(enum_values)
    item_type = getattr(value, "item_type", None)
    if item_type is None:
        item_type = getattr(dialect_value, "item_type", None)
    if item_type is not None:
        attributes["item_type"] = _type_value(item_type, dialect)
    enum_class = getattr(value, "enum_class", None)
    if enum_class is None:
        enum_class = getattr(dialect_value, "enum_class", None)
    if enum_class is not None:
        attributes["enum_class"] = _qualified_name(enum_class)
    cache_key = _json_value(getattr(value, "_static_cache_key", None))
    if (
        isinstance(cache_key, list)
        and cache_key
        and all(
            isinstance(item, list)
            and len(item) == 2
            and isinstance(item[0], str)
            for item in cache_key[1:]
        )
    ):
        cache_key = [cache_key[0]] + sorted(cache_key[1:], key=lambda item: item[0])
    return {
        "class": _qualified_name(type(value)),
        "sql": sql,
        "cache_key": cache_key,
        "attributes": {key: attributes[key] for key in sorted(attributes)},
    }


def _column_value(column, dialect):
    return {
        "name": column.name,
        "type": _type_value(column.type, dialect),
        "nullable": bool(column.nullable),
        "primary_key": bool(column.primary_key),
        "autoincrement": _json_value(column.autoincrement),
        "default": _default_value(column.default, dialect),
        "server_default": _default_value(column.server_default, dialect),
        "onupdate": _default_value(column.onupdate, dialect),
        "server_onupdate": _default_value(column.server_onupdate, dialect),
        "identity": _identity_value(column.identity),
        "computed": _computed_value(column.computed, dialect),
        "comment": column.comment,
    }


def _option_value(value, dialect):
    if hasattr(value, "compile"):
        return _sql_text(value, dialect)
    return _json_value(value)


def _constraint_value(constraint, dialect, constraint_types):
    primary_key, unique, foreign_key, check = constraint_types
    if isinstance(constraint, primary_key):
        kind = "primary_key"
        references = []
        options = {}
        expression = None
    elif isinstance(constraint, unique):
        kind = "unique"
        references = []
        options = {
            key: _option_value(value, dialect)
            for key, value in sorted(constraint.dialect_kwargs.items())
        }
        expression = None
    elif isinstance(constraint, foreign_key):
        kind = "foreign_key"
        references = [element.target_fullname for element in constraint.elements]
        options = {
            "deferrable": _json_value(constraint.deferrable),
            "initially": _json_value(constraint.initially),
            "match": _json_value(constraint.match),
            "ondelete": _json_value(constraint.ondelete),
            "onupdate": _json_value(constraint.onupdate),
            "use_alter": _json_value(constraint.use_alter),
        }
        expression = None
    elif isinstance(constraint, check):
        kind = "check"
        references = []
        options = {
            key: _option_value(value, dialect)
            for key, value in sorted(constraint.dialect_kwargs.items())
        }
        expression = _sql_text(constraint.sqltext, dialect)
    else:
        raise RuntimeError("unsupported model constraint type")
    return {
        "kind": kind,
        "name": None if constraint.name is None else str(constraint.name),
        "columns": [column.name for column in constraint.columns],
        "references": references,
        "options": options,
        "expression": expression,
    }


def _index_value(index, dialect):
    return {
        "name": None if index.name is None else str(index.name),
        "unique": bool(index.unique),
        "expressions": [_sql_text(expression, dialect) for expression in index.expressions],
        "options": {
            key: _option_value(value, dialect)
            for key, value in sorted(index.dialect_kwargs.items())
        },
    }


def _canonical_key(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _model_schema():
    sys.path.insert(0, str(APPLICATION_ROOT))
    package = importlib.import_module("app")
    package_file = Path(package.__file__).resolve(strict=True)
    try:
        package_file.relative_to(PACKAGE_ROOT)
    except ValueError as exc:
        raise RuntimeError("application package did not resolve under /app/app") from exc
    modules = {"app.models"}
    for source in sorted(MODEL_ROOT.rglob("*.py")):
        _regular_source(source, "model source")
        relative = source.relative_to(MODEL_ROOT)
        parts = list(relative.parts)
        if any(not part.replace(".py", "").isidentifier() for part in parts):
            raise RuntimeError("model module path is invalid")
        if parts[-1] == "__init__.py":
            parts = parts[:-1]
        else:
            parts[-1] = source.stem
        modules.add(".".join(["app", "models"] + parts))
    for module in sorted(modules):
        importlib.import_module(module)

    from app.db.base import Base
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.schema import (
        CheckConstraint,
        ForeignKeyConstraint,
        PrimaryKeyConstraint,
        UniqueConstraint,
    )

    dialect = postgresql.dialect()
    constraint_types = (
        PrimaryKeyConstraint,
        UniqueConstraint,
        ForeignKeyConstraint,
        CheckConstraint,
    )
    tables = []
    for table in sorted(
        Base.metadata.tables.values(),
        key=lambda item: ((item.schema or ""), item.name),
    ):
        constraints = [
            _constraint_value(item, dialect, constraint_types)
            for item in table.constraints
        ]
        indexes = [_index_value(item, dialect) for item in table.indexes]
        tables.append(
            {
                "name": table.name,
                "schema": table.schema,
                "columns": [
                    _column_value(column, dialect)
                    for column in sorted(table.columns, key=lambda item: item.name)
                ],
                "constraints": sorted(constraints, key=_canonical_key),
                "indexes": sorted(indexes, key=_canonical_key),
            }
        )
    if not tables:
        raise RuntimeError("model metadata is empty")
    return tables


def _literal_assignment(tree, name):
    values = []
    for node in tree.body:
        candidate = None
        if isinstance(node, ast.Assign):
            if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                if node.targets[0].id == name:
                    candidate = node.value
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == name:
                candidate = node.value
        if candidate is not None:
            try:
                values.append(ast.literal_eval(candidate))
            except (ValueError, TypeError) as exc:
                raise RuntimeError("migration metadata is not a literal") from exc
    if len(values) != 1:
        raise RuntimeError("migration metadata assignment count is invalid")
    return values[0]


def _migration_schema():
    entries = []
    for source in sorted(MIGRATION_ROOT.glob("*.py")):
        if source.name == "__init__.py":
            continue
        payload = _regular_source(source, "migration source")
        try:
            text = payload.decode("utf-8")
            tree = ast.parse(text, filename=source.name)
        except (UnicodeError, SyntaxError) as exc:
            raise RuntimeError("migration source is invalid") from exc
        revision = _literal_assignment(tree, "revision")
        down_revision = _literal_assignment(tree, "down_revision")
        if type(revision) is not str or not revision:
            raise RuntimeError("migration revision is invalid")
        if down_revision is not None and (type(down_revision) is not str or not down_revision):
            raise RuntimeError("migration down revision is invalid")
        entries.append(
            {
                "revision": revision,
                "down_revision": down_revision,
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    if not entries:
        raise RuntimeError("migration history is empty")
    by_revision = {}
    for entry in entries:
        revision = entry["revision"]
        if revision in by_revision:
            raise RuntimeError("migration revisions are not unique")
        by_revision[revision] = entry
    roots = [entry for entry in entries if entry["down_revision"] is None]
    if len(roots) != 1:
        raise RuntimeError("migration history must have one root")
    children = {revision: [] for revision in by_revision}
    for entry in entries:
        down_revision = entry["down_revision"]
        if down_revision is None:
            continue
        if down_revision not in by_revision:
            raise RuntimeError("migration down revision is missing")
        children[down_revision].append(entry["revision"])
    if any(len(values) > 1 for values in children.values()):
        raise RuntimeError("migration history is branched")
    ordered = []
    seen = set()
    revision = roots[0]["revision"]
    while True:
        if revision in seen:
            raise RuntimeError("migration history contains a cycle")
        seen.add(revision)
        ordered.append(by_revision[revision])
        next_revisions = children[revision]
        if not next_revisions:
            break
        revision = next_revisions[0]
    if len(ordered) != len(entries):
        raise RuntimeError("migration history is disconnected")
    return ordered, [ordered[-1]["revision"]]


def main():
    migrations, heads = _migration_schema()
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "migrations": migrations,
        "heads": heads,
        "model_schema": _model_schema(),
    }
    print(json.dumps(manifest, ensure_ascii=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
'''

# This exact CTE graph is inserted into both the disposable-reference reader and
# the production reader. It uses only pg_catalog and emits no OIDs, so catalogs
# from two PostgreSQL instances can be compared byte-for-byte after canonical
# JSON serialization.
PHYSICAL_SCHEMA_CATALOG_SQL = r'''server_identity AS (
  SELECT
    current_setting('server_version_num')::integer / 10000 AS server_major,
    current_setting('server_version_num')::integer AS server_version_num,
    pg_catalog.pg_encoding_to_char(database_value.encoding) AS database_encoding,
    database_value.datcollate AS database_collate,
    database_value.datctype AS database_ctype,
    database_value.datlocprovider AS database_locale_provider,
    database_value.datcollversion AS database_collation_version,
    database_value.daticulocale AS database_icu_locale,
    database_value.daticurules AS database_icu_rules,
    current_setting('standard_conforming_strings') AS standard_conforming_strings
  FROM pg_catalog.pg_database AS database_value
  WHERE database_value.datname = current_database()
),
managed_relations AS (
  SELECT
    relation.oid,
    namespace.nspname AS schema_name,
    relation.relname,
    relation.relkind,
    relation.relpersistence,
    relation.relrowsecurity,
    relation.relforcerowsecurity,
    relation.relreplident,
    relation.reloptions,
    access_method.amname AS access_method
  FROM pg_catalog.pg_class AS relation
  JOIN pg_catalog.pg_namespace AS namespace
    ON namespace.oid = relation.relnamespace
  LEFT JOIN pg_catalog.pg_am AS access_method
    ON access_method.oid = relation.relam
  WHERE namespace.nspname = 'public'
    AND relation.relkind IN ('r', 'p')
    AND relation.relname <> 'alembic_version'
),
public_sequences AS (
  SELECT
    relation.oid,
    namespace.nspname AS schema_name,
    relation.relname,
    sequence_value.seqtypid,
    sequence_value.seqstart,
    sequence_value.seqincrement,
    sequence_value.seqmax,
    sequence_value.seqmin,
    sequence_value.seqcache,
    sequence_value.seqcycle
  FROM pg_catalog.pg_class AS relation
  JOIN pg_catalog.pg_namespace AS namespace
    ON namespace.oid = relation.relnamespace
  JOIN pg_catalog.pg_sequence AS sequence_value
    ON sequence_value.seqrelid = relation.oid
  WHERE namespace.nspname = 'public' AND relation.relkind = 'S'
),
sequence_ownership AS (
  SELECT
    dependency.objid AS sequence_oid,
    dependency.refobjid AS relation_oid,
    dependency.refobjsubid AS attribute_number,
    dependency.deptype AS dependency_type,
    owner_namespace.nspname AS owner_schema,
    owner_relation.relname AS owner_table,
    owner_attribute.attname AS owner_column
  FROM pg_catalog.pg_depend AS dependency
  JOIN pg_catalog.pg_class AS sequence_relation
    ON sequence_relation.oid = dependency.objid
   AND sequence_relation.relkind = 'S'
  JOIN pg_catalog.pg_namespace AS sequence_namespace
    ON sequence_namespace.oid = sequence_relation.relnamespace
  JOIN pg_catalog.pg_class AS owner_relation
    ON owner_relation.oid = dependency.refobjid
  JOIN pg_catalog.pg_namespace AS owner_namespace
    ON owner_namespace.oid = owner_relation.relnamespace
  JOIN pg_catalog.pg_attribute AS owner_attribute
    ON owner_attribute.attrelid = owner_relation.oid
   AND owner_attribute.attnum = dependency.refobjsubid
   AND NOT owner_attribute.attisdropped
  WHERE dependency.classid = 'pg_catalog.pg_class'::pg_catalog.regclass
    AND dependency.refclassid = 'pg_catalog.pg_class'::pg_catalog.regclass
    AND dependency.objsubid = 0
    AND dependency.refobjsubid > 0
    AND dependency.deptype IN ('a', 'i')
    AND sequence_namespace.nspname = 'public'
),
sequence_records AS (
  SELECT
    sequence_value.oid AS sequence_oid,
    ownership.relation_oid,
    ownership.attribute_number,
    pg_catalog.jsonb_build_object(
      'schema', sequence_value.schema_name,
      'name', sequence_value.relname,
      'data_type', pg_catalog.format_type(sequence_value.seqtypid, NULL),
      'start', sequence_value.seqstart,
      'increment', sequence_value.seqincrement,
      'minimum', sequence_value.seqmin,
      'maximum', sequence_value.seqmax,
      'cache', sequence_value.seqcache,
      'cycle', sequence_value.seqcycle,
      'owned_by', CASE WHEN ownership.sequence_oid IS NULL THEN NULL
        ELSE pg_catalog.jsonb_build_object(
          'schema', ownership.owner_schema,
          'table', ownership.owner_table,
          'column', ownership.owner_column,
          'dependency', ownership.dependency_type
        ) END
    ) AS record
  FROM public_sequences AS sequence_value
  LEFT JOIN sequence_ownership AS ownership
    ON ownership.sequence_oid = sequence_value.oid
),
column_records AS (
  SELECT
    relation.oid AS relation_oid,
    attribute.attnum AS position,
    pg_catalog.jsonb_build_object(
      'position', attribute.attnum,
      'name', attribute.attname,
      'type', pg_catalog.jsonb_build_object(
        'schema', type_namespace.nspname,
        'name', column_type.typname,
        'formatted', pg_catalog.format_type(attribute.atttypid, attribute.atttypmod),
        'kind', column_type.typtype,
        'category', column_type.typcategory,
        'dimensions', attribute.attndims,
        'enum_labels', CASE WHEN column_type.typtype = 'e' THEN (
          SELECT pg_catalog.jsonb_agg(enum_value.enumlabel ORDER BY enum_value.enumsortorder)
          FROM pg_catalog.pg_enum AS enum_value
          WHERE enum_value.enumtypid = column_type.oid
        ) ELSE NULL END,
        'array_item', CASE WHEN column_type.typcategory = 'A' THEN
          pg_catalog.jsonb_build_object(
            'schema', element_namespace.nspname,
            'name', element_type.typname,
            'formatted', pg_catalog.format_type(element_type.oid, attribute.atttypmod),
            'kind', element_type.typtype,
            'category', element_type.typcategory,
            'dimensions', 0,
            'enum_labels', CASE WHEN element_type.typtype = 'e' THEN (
              SELECT pg_catalog.jsonb_agg(enum_value.enumlabel ORDER BY enum_value.enumsortorder)
              FROM pg_catalog.pg_enum AS enum_value
              WHERE enum_value.enumtypid = element_type.oid
            ) ELSE NULL END,
            'array_item', NULL
          ) ELSE NULL END
      ),
      'nullable', NOT attribute.attnotnull,
      'default', pg_catalog.pg_get_expr(default_value.adbin, default_value.adrelid, false),
      'identity', attribute.attidentity,
      'generated', attribute.attgenerated,
      'collation', CASE WHEN collation_value.oid IS NULL THEN NULL
        ELSE pg_catalog.jsonb_build_object(
          'schema', collation_namespace.nspname,
          'name', collation_value.collname
        ) END,
      'compression', attribute.attcompression,
      'storage', attribute.attstorage,
      'owned_sequence', (
        SELECT sequence_record.record
        FROM sequence_records AS sequence_record
        WHERE sequence_record.relation_oid = relation.oid
          AND sequence_record.attribute_number = attribute.attnum
      )
    ) AS record
  FROM managed_relations AS relation
  JOIN pg_catalog.pg_attribute AS attribute
    ON attribute.attrelid = relation.oid
  JOIN pg_catalog.pg_type AS column_type
    ON column_type.oid = attribute.atttypid
  JOIN pg_catalog.pg_namespace AS type_namespace
    ON type_namespace.oid = column_type.typnamespace
  LEFT JOIN pg_catalog.pg_type AS element_type
    ON element_type.oid = column_type.typelem
  LEFT JOIN pg_catalog.pg_namespace AS element_namespace
    ON element_namespace.oid = element_type.typnamespace
  LEFT JOIN pg_catalog.pg_attrdef AS default_value
    ON default_value.adrelid = relation.oid
   AND default_value.adnum = attribute.attnum
  LEFT JOIN pg_catalog.pg_collation AS collation_value
    ON collation_value.oid = attribute.attcollation
  LEFT JOIN pg_catalog.pg_namespace AS collation_namespace
    ON collation_namespace.oid = collation_value.collnamespace
  WHERE attribute.attnum > 0 AND NOT attribute.attisdropped
),
__PHYSICAL_SCHEMA_CATALOG_CONTINUATION__'''

_PHYSICAL_SCHEMA_CATALOG_CONTINUATION_SQL = r'''constraint_records AS (
  SELECT
    constraint_value.conrelid AS relation_oid,
    constraint_value.contype AS constraint_type,
    constraint_value.conname AS constraint_name,
    pg_catalog.jsonb_build_object(
      'name', constraint_value.conname,
      'type', constraint_value.contype,
      'definition', pg_catalog.pg_get_constraintdef(constraint_value.oid, false),
      'columns', COALESCE((
        SELECT pg_catalog.jsonb_agg(attribute.attname ORDER BY key_value.ordinality)
        FROM pg_catalog.unnest(constraint_value.conkey)
          WITH ORDINALITY AS key_value(attribute_number, ordinality)
        JOIN pg_catalog.pg_attribute AS attribute
          ON attribute.attrelid = constraint_value.conrelid
         AND attribute.attnum = key_value.attribute_number
      ), '[]'::pg_catalog.jsonb),
      'references', CASE WHEN constraint_value.contype = 'f' THEN
        pg_catalog.jsonb_build_object(
          'schema', reference_namespace.nspname,
          'table', reference_relation.relname,
          'columns', COALESCE((
            SELECT pg_catalog.jsonb_agg(attribute.attname ORDER BY key_value.ordinality)
            FROM pg_catalog.unnest(constraint_value.confkey)
              WITH ORDINALITY AS key_value(attribute_number, ordinality)
            JOIN pg_catalog.pg_attribute AS attribute
              ON attribute.attrelid = constraint_value.confrelid
             AND attribute.attnum = key_value.attribute_number
          ), '[]'::pg_catalog.jsonb)
        ) ELSE NULL END,
      'deferrable', constraint_value.condeferrable,
      'deferred', constraint_value.condeferred,
      'validated', constraint_value.convalidated,
      'no_inherit', constraint_value.connoinherit,
      'nulls_not_distinct', COALESCE((
        SELECT backing_index.indnullsnotdistinct
        FROM pg_catalog.pg_index AS backing_index
        WHERE backing_index.indexrelid = constraint_value.conindid
      ), false)
    ) AS record
  FROM pg_catalog.pg_constraint AS constraint_value
  JOIN managed_relations AS relation
    ON relation.oid = constraint_value.conrelid
  LEFT JOIN pg_catalog.pg_class AS reference_relation
    ON reference_relation.oid = constraint_value.confrelid
  LEFT JOIN pg_catalog.pg_namespace AS reference_namespace
    ON reference_namespace.oid = reference_relation.relnamespace
  WHERE constraint_value.contype IN ('p', 'u', 'f', 'c')
),
index_records AS (
  SELECT
    index_value.indrelid AS relation_oid,
    index_relation.relname AS index_name,
    pg_catalog.jsonb_build_object(
      'name', index_relation.relname,
      'unique', index_value.indisunique,
      'nulls_not_distinct', index_value.indnullsnotdistinct,
      'clustered', index_value.indisclustered,
      'replica_identity', index_value.indisreplident,
      'valid', index_value.indisvalid,
      'ready', index_value.indisready,
      'live', index_value.indislive,
      'constraint', CASE WHEN owning_constraint.oid IS NULL THEN NULL
        ELSE pg_catalog.jsonb_build_object(
          'name', owning_constraint.conname,
          'type', owning_constraint.contype
        ) END,
      'method', access_method.amname,
      'definition', pg_catalog.pg_get_indexdef(index_value.indexrelid, 0, false),
      'predicate', pg_catalog.pg_get_expr(index_value.indpred, index_value.indrelid, false),
      'expressions', COALESCE((
        SELECT pg_catalog.jsonb_agg(
          pg_catalog.pg_get_indexdef(index_value.indexrelid, position, false)
          ORDER BY position
        )
        FROM pg_catalog.generate_series(1, index_value.indnkeyatts) AS position
      ), '[]'::pg_catalog.jsonb),
      'include_columns', COALESCE((
        SELECT pg_catalog.jsonb_agg(
          pg_catalog.pg_get_indexdef(index_value.indexrelid, position, false)
          ORDER BY position
        )
        FROM pg_catalog.generate_series(
          index_value.indnkeyatts + 1,
          index_value.indnatts
        ) AS position
      ), '[]'::pg_catalog.jsonb),
      'options', COALESCE((
        SELECT pg_catalog.jsonb_agg(option_value ORDER BY option_value)
        FROM pg_catalog.unnest(index_relation.reloptions) AS option_value
      ), '[]'::pg_catalog.jsonb),
      'tablespace', tablespace.spcname
    ) AS record
  FROM pg_catalog.pg_index AS index_value
  JOIN managed_relations AS relation
    ON relation.oid = index_value.indrelid
  JOIN pg_catalog.pg_class AS index_relation
    ON index_relation.oid = index_value.indexrelid
  JOIN pg_catalog.pg_am AS access_method
    ON access_method.oid = index_relation.relam
  LEFT JOIN pg_catalog.pg_tablespace AS tablespace
    ON tablespace.oid = index_relation.reltablespace
  LEFT JOIN pg_catalog.pg_constraint AS owning_constraint
    ON owning_constraint.conindid = index_value.indexrelid
   AND owning_constraint.conrelid = index_value.indrelid
   AND owning_constraint.contype IN ('p', 'u', 'x')
),
table_records AS (
  SELECT
    relation.schema_name,
    relation.relname,
    pg_catalog.jsonb_build_object(
      'schema', relation.schema_name,
      'name', relation.relname,
      'kind', relation.relkind,
      'persistence', relation.relpersistence,
      'access_method', relation.access_method,
      'row_security', relation.relrowsecurity,
      'force_row_security', relation.relforcerowsecurity,
      'replica_identity', relation.relreplident,
      'options', COALESCE((
        SELECT pg_catalog.jsonb_agg(option_value ORDER BY option_value)
        FROM pg_catalog.unnest(relation.reloptions) AS option_value
      ), '[]'::pg_catalog.jsonb),
      'columns', COALESCE((
        SELECT pg_catalog.jsonb_agg(column_value.record ORDER BY column_value.position)
        FROM column_records AS column_value
        WHERE column_value.relation_oid = relation.oid
      ), '[]'::pg_catalog.jsonb),
      'constraints', COALESCE((
        SELECT pg_catalog.jsonb_agg(
          constraint_value.record
          ORDER BY constraint_value.constraint_type, constraint_value.constraint_name
        )
        FROM constraint_records AS constraint_value
        WHERE constraint_value.relation_oid = relation.oid
      ), '[]'::pg_catalog.jsonb),
      'indexes', COALESCE((
        SELECT pg_catalog.jsonb_agg(index_value.record ORDER BY index_value.index_name)
        FROM index_records AS index_value
        WHERE index_value.relation_oid = relation.oid
      ), '[]'::pg_catalog.jsonb)
    ) AS record
  FROM managed_relations AS relation
),
table_catalog AS (
  SELECT COALESCE(
    pg_catalog.jsonb_agg(record ORDER BY schema_name, relname),
    '[]'::pg_catalog.jsonb
  ) AS records
  FROM table_records
),
sequence_catalog AS (
  SELECT COALESCE(
    pg_catalog.jsonb_agg(record ORDER BY record->>'schema', record->>'name'),
    '[]'::pg_catalog.jsonb
  ) AS records
  FROM sequence_records
),
enum_records AS (
  SELECT
    namespace.nspname AS schema_name,
    type_value.typname,
    pg_catalog.jsonb_build_object(
      'schema', namespace.nspname,
      'name', type_value.typname,
      'labels', COALESCE((
        SELECT pg_catalog.jsonb_agg(enum_value.enumlabel ORDER BY enum_value.enumsortorder)
        FROM pg_catalog.pg_enum AS enum_value
        WHERE enum_value.enumtypid = type_value.oid
      ), '[]'::pg_catalog.jsonb)
    ) AS record
  FROM pg_catalog.pg_type AS type_value
  JOIN pg_catalog.pg_namespace AS namespace
    ON namespace.oid = type_value.typnamespace
  WHERE namespace.nspname = 'public' AND type_value.typtype = 'e'
),
enum_catalog AS (
  SELECT COALESCE(
    pg_catalog.jsonb_agg(record ORDER BY schema_name, typname),
    '[]'::pg_catalog.jsonb
  ) AS records
  FROM enum_records
),
__PHYSICAL_SCHEMA_UNSUPPORTED_CONTINUATION__'''

if PHYSICAL_SCHEMA_CATALOG_SQL.count(
    "__PHYSICAL_SCHEMA_CATALOG_CONTINUATION__"
) != 1:
    raise RuntimeError("physical schema catalog continuation marker is invalid")
PHYSICAL_SCHEMA_CATALOG_SQL = PHYSICAL_SCHEMA_CATALOG_SQL.replace(
    "__PHYSICAL_SCHEMA_CATALOG_CONTINUATION__",
    _PHYSICAL_SCHEMA_CATALOG_CONTINUATION_SQL,
)

_PHYSICAL_SCHEMA_UNSUPPORTED_SQL = r'''unsupported AS (
  SELECT (
    (SELECT pg_catalog.count(*)
     FROM pg_catalog.pg_class AS relation
     JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
     WHERE namespace.nspname = 'public'
       AND relation.relkind NOT IN ('r', 'S', 'i'))
    + (SELECT pg_catalog.count(*) FROM managed_relations WHERE relkind <> 'r')
    + (SELECT pg_catalog.count(*)
       FROM pg_catalog.pg_attribute AS attribute
       JOIN managed_relations AS relation ON relation.oid = attribute.attrelid
       WHERE attribute.attnum > 0
         AND (attribute.attisdropped OR attribute.attinhcount <> 0 OR NOT attribute.attislocal))
    + (SELECT pg_catalog.count(*)
       FROM pg_catalog.pg_constraint AS constraint_value
       JOIN managed_relations AS relation ON relation.oid = constraint_value.conrelid
       WHERE constraint_value.contype NOT IN ('p', 'u', 'f', 'c')
          OR constraint_value.conparentid <> 0
          OR (constraint_value.contype = 'f' AND NOT EXISTS (
            SELECT 1 FROM managed_relations AS reference_value
            WHERE reference_value.oid = constraint_value.confrelid
          )))
    + (SELECT pg_catalog.count(*)
       FROM pg_catalog.pg_type AS type_value
       JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = type_value.typnamespace
       WHERE namespace.nspname = 'public'
         AND NOT (
           type_value.typtype = 'e'
           OR (type_value.typtype = 'c' AND type_value.typrelid <> 0)
           OR (type_value.typtype = 'b' AND type_value.typcategory = 'A'
               AND type_value.typelem <> 0)
         ))
    + (SELECT pg_catalog.count(*)
       FROM public_sequences AS sequence_value
       WHERE (SELECT pg_catalog.count(*) FROM sequence_ownership AS ownership
              WHERE ownership.sequence_oid = sequence_value.oid) <> 1)
    + (SELECT pg_catalog.count(*)
       FROM pg_catalog.pg_trigger AS trigger_value
       JOIN managed_relations AS relation ON relation.oid = trigger_value.tgrelid
       WHERE NOT trigger_value.tgisinternal)
    + (SELECT pg_catalog.count(*)
       FROM pg_catalog.pg_rewrite AS rule_value
       JOIN managed_relations AS relation ON relation.oid = rule_value.ev_class)
    + (SELECT pg_catalog.count(*)
       FROM pg_catalog.pg_policy AS policy_value
       JOIN managed_relations AS relation ON relation.oid = policy_value.polrelid)
    + (SELECT pg_catalog.count(*)
       FROM pg_catalog.pg_inherits AS inheritance
       JOIN managed_relations AS relation ON relation.oid = inheritance.inhrelid)
    + (SELECT pg_catalog.count(*)
       FROM pg_catalog.pg_proc AS procedure_value
       JOIN pg_catalog.pg_namespace AS namespace
         ON namespace.oid = procedure_value.pronamespace
       WHERE namespace.nspname = 'public')
    + (SELECT pg_catalog.count(*)
       FROM pg_catalog.pg_collation AS collation_value
       JOIN pg_catalog.pg_namespace AS namespace
         ON namespace.oid = collation_value.collnamespace
       WHERE namespace.nspname = 'public')
    + (SELECT pg_catalog.count(*)
       FROM pg_catalog.pg_operator AS operator_value
       JOIN pg_catalog.pg_namespace AS namespace
         ON namespace.oid = operator_value.oprnamespace
       WHERE namespace.nspname = 'public')
    + (SELECT pg_catalog.count(*)
       FROM pg_catalog.pg_opclass AS opclass_value
       JOIN pg_catalog.pg_namespace AS namespace
         ON namespace.oid = opclass_value.opcnamespace
       WHERE namespace.nspname = 'public')
    + (SELECT pg_catalog.count(*)
       FROM pg_catalog.pg_opfamily AS opfamily_value
       JOIN pg_catalog.pg_namespace AS namespace
         ON namespace.oid = opfamily_value.opfnamespace
       WHERE namespace.nspname = 'public')
    + (SELECT pg_catalog.count(*)
       FROM pg_catalog.pg_conversion AS conversion_value
       JOIN pg_catalog.pg_namespace AS namespace
         ON namespace.oid = conversion_value.connamespace
       WHERE namespace.nspname = 'public')
    + (SELECT pg_catalog.count(*)
       FROM pg_catalog.pg_extension AS extension_value
       JOIN pg_catalog.pg_namespace AS namespace
         ON namespace.oid = extension_value.extnamespace
       WHERE namespace.nspname = 'public')
    + (SELECT pg_catalog.count(*)
       FROM pg_catalog.pg_index AS index_value
       JOIN managed_relations AS relation ON relation.oid = index_value.indrelid
       WHERE NOT index_value.indisvalid
          OR NOT index_value.indisready
          OR NOT index_value.indislive)
  ) AS count
),
observed AS (
  SELECT pg_catalog.jsonb_build_object(
    'schema_version', 3,
    'candidate_manifest_sha256', __CANDIDATE_MANIFEST_SHA256_SQL__,
    'server_major', server_identity.server_major,
    'database_encoding', server_identity.database_encoding,
    'database_collate', server_identity.database_collate,
    'database_ctype', server_identity.database_ctype,
    'database_locale_provider', server_identity.database_locale_provider,
    'database_collation_version', server_identity.database_collation_version,
    'database_icu_locale', server_identity.database_icu_locale,
    'database_icu_rules', server_identity.database_icu_rules,
    'standard_conforming_strings', server_identity.standard_conforming_strings,
    'tables', table_catalog.records,
    'sequences', sequence_catalog.records,
    'enum_types', enum_catalog.records
  ) AS catalog
  FROM server_identity, table_catalog, sequence_catalog, enum_catalog
)'''

if PHYSICAL_SCHEMA_CATALOG_SQL.count(
    "__PHYSICAL_SCHEMA_UNSUPPORTED_CONTINUATION__"
) != 1:
    raise RuntimeError("physical schema unsupported marker is invalid")
PHYSICAL_SCHEMA_CATALOG_SQL = PHYSICAL_SCHEMA_CATALOG_SQL.replace(
    "__PHYSICAL_SCHEMA_UNSUPPORTED_CONTINUATION__",
    _PHYSICAL_SCHEMA_UNSUPPORTED_SQL,
)

REFERENCE_CATALOG_PROBE_SQL = r'''\set ON_ERROR_STOP on
BEGIN TRANSACTION ISOLATION LEVEL SERIALIZABLE READ ONLY;
SET LOCAL search_path TO public, pg_catalog;
SET LOCAL standard_conforming_strings TO on;
WITH
__PHYSICAL_SCHEMA_CATALOG_SQL__,
expected_table_names AS (
  SELECT __EXPECTED_TABLE_IDENTITIES_SQL__ AS names
),
observed_table_names AS (
  SELECT COALESCE(
    pg_catalog.jsonb_agg(
      (table_value->>'schema') || '.' || (table_value->>'name')
      ORDER BY table_value->>'schema', table_value->>'name'
    ),
    '[]'::pg_catalog.jsonb
  ) AS names
  FROM observed,
    LATERAL pg_catalog.jsonb_array_elements(observed.catalog->'tables') AS table_value
),
attestation AS (
  SELECT
    current_setting('transaction_read_only') = 'on'
      AND current_setting('search_path') = 'public, pg_catalog'
      AND current_database() = 'xjie_reference'
      AND current_user = 'xjie_reference'
      AND pg_catalog.inet_server_addr() IS NULL
      AND pg_catalog.inet_server_port() IS NULL
      AND current_schema() = 'public'
      AND (SELECT server_major FROM server_identity) = 16
      AND NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_class AS relation
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = 'public'
          AND relation.relname = 'alembic_version'
      ) AS valid
)
SELECT CASE WHEN
  attestation.valid
  AND unsupported.count = 0
  AND observed_table_names.names = expected_table_names.names
THEN observed.catalog
ELSE pg_catalog.jsonb_build_object('error', 'reference schema catalog attestation failed')
END
FROM observed, unsupported, expected_table_names, observed_table_names, attestation;
ROLLBACK;
'''

DATABASE_SCHEMA_PROBE_SQL = r'''\set ON_ERROR_STOP on
\getenv expected_database XJIE_EXPECTED_DATABASE
BEGIN TRANSACTION ISOLATION LEVEL SERIALIZABLE READ ONLY;
SET LOCAL search_path TO public, pg_catalog;
SET LOCAL standard_conforming_strings TO on;
WITH
__PHYSICAL_SCHEMA_CATALOG_SQL__,
expected AS (
  SELECT __EXPECTED_REFERENCE_CATALOG_SQL__ AS catalog
),
alembic_relation AS (
  SELECT relation.oid
  FROM pg_catalog.pg_class AS relation
  JOIN pg_catalog.pg_namespace AS namespace
    ON namespace.oid = relation.relnamespace
  WHERE namespace.nspname = 'public'
    AND relation.relname = 'alembic_version'
    AND relation.relkind = 'r'
),
alembic_attestation AS (
  SELECT
    (SELECT pg_catalog.count(*) FROM alembic_relation) = 1
      AND COALESCE((
        SELECT pg_catalog.bool_and(
          relation.relpersistence = 'p'
            AND NOT relation.relrowsecurity
            AND NOT relation.relforcerowsecurity
            AND relation.relreplident = 'd'
            AND relation.reloptions IS NULL
            AND access_method.amname = 'heap'
            AND pg_catalog.has_table_privilege(
              current_user, relation.oid, 'SELECT'
            )
        )
        FROM alembic_relation
        JOIN pg_catalog.pg_class AS relation ON relation.oid = alembic_relation.oid
        JOIN pg_catalog.pg_am AS access_method ON access_method.oid = relation.relam
      ), false)
      AND (SELECT pg_catalog.count(*)
           FROM alembic_relation
           JOIN pg_catalog.pg_attribute AS attribute
             ON attribute.attrelid = alembic_relation.oid
           WHERE attribute.attnum > 0 AND NOT attribute.attisdropped) = 1
      AND (SELECT pg_catalog.count(*)
           FROM alembic_relation
           JOIN pg_catalog.pg_attribute AS attribute
             ON attribute.attrelid = alembic_relation.oid
           JOIN pg_catalog.pg_type AS type_value ON type_value.oid = attribute.atttypid
           JOIN pg_catalog.pg_namespace AS type_namespace
             ON type_namespace.oid = type_value.typnamespace
           JOIN pg_catalog.pg_collation AS collation_value
             ON collation_value.oid = attribute.attcollation
           JOIN pg_catalog.pg_namespace AS collation_namespace
             ON collation_namespace.oid = collation_value.collnamespace
           WHERE attribute.attnum = 1
             AND attribute.attname = 'version_num'
             AND attribute.attnotnull
             AND attribute.attidentity = ''
             AND attribute.attgenerated = ''
             AND attribute.attndims = 0
             AND type_namespace.nspname = 'pg_catalog'
             AND type_value.typname = 'varchar'
             AND attribute.atttypmod = 36
             AND pg_catalog.format_type(attribute.atttypid, attribute.atttypmod)
                   = 'character varying(32)'
             AND collation_namespace.nspname = 'pg_catalog'
             AND collation_value.collname = 'default'
             AND NOT EXISTS (
               SELECT 1 FROM pg_catalog.pg_attrdef AS default_value
               WHERE default_value.adrelid = attribute.attrelid
                 AND default_value.adnum = attribute.attnum
             )) = 1
      AND (SELECT pg_catalog.count(*)
           FROM alembic_relation
           JOIN pg_catalog.pg_constraint AS constraint_value
             ON constraint_value.conrelid = alembic_relation.oid) = 1
      AND (SELECT pg_catalog.count(*)
           FROM alembic_relation
           JOIN pg_catalog.pg_constraint AS constraint_value
             ON constraint_value.conrelid = alembic_relation.oid
           WHERE constraint_value.conname = 'alembic_version_pkc'
             AND constraint_value.contype = 'p'
             AND constraint_value.conkey = ARRAY[1]::pg_catalog.int2[]
             AND NOT constraint_value.condeferrable
             AND NOT constraint_value.condeferred
             AND constraint_value.convalidated
             AND constraint_value.connoinherit) = 1
      AND (SELECT pg_catalog.count(*)
           FROM alembic_relation
           JOIN pg_catalog.pg_index AS index_value
             ON index_value.indrelid = alembic_relation.oid) = 1
      AND (SELECT pg_catalog.count(*)
           FROM alembic_relation
           JOIN pg_catalog.pg_index AS index_value
             ON index_value.indrelid = alembic_relation.oid
           JOIN pg_catalog.pg_class AS index_relation
             ON index_relation.oid = index_value.indexrelid
           JOIN pg_catalog.pg_am AS access_method
             ON access_method.oid = index_relation.relam
           WHERE index_relation.relname = 'alembic_version_pkc'
             AND index_relation.relkind = 'i'
             AND index_relation.reloptions IS NULL
             AND access_method.amname = 'btree'
             AND index_value.indisunique
             AND index_value.indisprimary
             AND index_value.indisvalid
             AND index_value.indisready
             AND index_value.indislive
             AND NOT index_value.indisclustered
             AND NOT index_value.indisreplident
             AND NOT index_value.indnullsnotdistinct
             AND index_value.indnkeyatts = 1
             AND index_value.indnatts = 1
             AND index_value.indkey::pg_catalog.text = '1'
             AND index_value.indpred IS NULL
             AND index_value.indexprs IS NULL) = 1
      AND (SELECT pg_catalog.count(*) FROM public.alembic_version) = 1
      AND (SELECT pg_catalog.min(version_num) FROM public.alembic_version)
            = __EXPECTED_ALEMBIC_HEAD_SQL__ AS valid
),
role_attestation AS (
  SELECT
    NOT role_value.rolsuper
      AND NOT role_value.rolcreatedb
      AND NOT role_value.rolcreaterole
      AND NOT role_value.rolreplication
      AND NOT role_value.rolbypassrls
      AND NOT pg_catalog.has_database_privilege(
        current_user, current_database(), 'CREATE'
      )
      AND NOT pg_catalog.has_schema_privilege(current_user, 'public', 'CREATE')
      AND NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_roles AS granted_role
        WHERE granted_role.rolname <> current_user
          AND pg_catalog.pg_has_role(current_user, granted_role.oid, 'MEMBER')
      )
      AND NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_class AS relation
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = 'public'
          AND relation.relkind IN ('r', 'p')
          AND (
            pg_catalog.has_table_privilege(current_user, relation.oid, 'INSERT')
            OR pg_catalog.has_table_privilege(current_user, relation.oid, 'UPDATE')
            OR pg_catalog.has_table_privilege(current_user, relation.oid, 'DELETE')
            OR pg_catalog.has_table_privilege(current_user, relation.oid, 'TRUNCATE')
            OR pg_catalog.has_table_privilege(current_user, relation.oid, 'TRIGGER')
            OR pg_catalog.has_table_privilege(current_user, relation.oid, 'REFERENCES')
          )
      )
      AND NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_class AS sequence_value
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = sequence_value.relnamespace
        WHERE namespace.nspname = 'public'
          AND sequence_value.relkind = 'S'
          AND (
            pg_catalog.has_sequence_privilege(current_user, sequence_value.oid, 'UPDATE')
            OR pg_catalog.has_sequence_privilege(current_user, sequence_value.oid, 'USAGE')
          )
      ) AS valid
  FROM pg_catalog.pg_roles AS role_value
  WHERE role_value.rolname = current_user
),
attestation AS (
  SELECT
    current_setting('transaction_read_only') = 'on'
      AND current_setting('search_path') = 'public, pg_catalog'
      AND current_database() = :'expected_database'
      AND current_schema() = 'public'
      AND (SELECT pg_catalog.count(*) FROM pg_catalog.pg_roles
           WHERE rolname = current_user) = 1
      AND (SELECT pg_catalog.count(*)
           FROM pg_catalog.pg_class AS relation
           JOIN pg_catalog.pg_namespace AS namespace
             ON namespace.oid = relation.relnamespace
           WHERE namespace.nspname = 'public'
             AND relation.relname = 'alembic_version'
             AND relation.relkind = 'r') = 1 AS valid
)
SELECT CASE WHEN
  attestation.valid
  AND alembic_attestation.valid
  AND role_attestation.valid
  AND unsupported.count = 0
  AND observed.catalog = expected.catalog
THEN pg_catalog.jsonb_build_object(
  'schema_version', 3,
  'candidate_manifest_sha256', __CANDIDATE_MANIFEST_SHA256_SQL__,
  'reference_catalog_sha256', __REFERENCE_CATALOG_SHA256_SQL__,
  'observed_catalog_sha256', __REFERENCE_CATALOG_SHA256_SQL__,
  'server_major', (expected.catalog->>'server_major')::integer,
  'table_count', pg_catalog.jsonb_array_length(expected.catalog->'tables')
)
ELSE pg_catalog.jsonb_build_object('error', 'database schema attestation failed')
END
FROM expected, observed, unsupported, alembic_attestation, role_attestation, attestation;
ROLLBACK;
'''
_MIGRATION_PROBE_ENTRYPOINT = '''

if __name__ == "__main__":
    main()
'''
REFERENCE_SCHEMA_MATERIALIZER_SUFFIX = r'''
import os
import re


REFERENCE_URL_KEY = "XJIE_REFERENCE_DATABASE_URL"
REFERENCE_USER = "xjie_reference"
REFERENCE_DATABASE = "xjie_reference"
REFERENCE_SOCKET = "/var/run/postgresql"
POSTGRESQL_MAJOR = 16
EXPECTED_MANIFEST = json.loads(__EXPECTED_MANIFEST_JSON_LITERAL__)
PASSWORD = re.compile(r"[0-9a-f]{64}\Z")


def _reference_url(make_url):
    raw = os.environ.pop(REFERENCE_URL_KEY, None)
    if not isinstance(raw, str) or raw != raw.strip() or not raw:
        raise RuntimeError("isolated reference database URL is missing")
    if "DATABASE_URL" in os.environ or "DATABASE_PROBE_URL" in os.environ:
        raise RuntimeError("application or production database URL reached materializer")
    if any(name.startswith("PG") for name in os.environ):
        raise RuntimeError("libpq environment reached reference materializer")
    try:
        url = make_url(raw)
    except Exception as exc:
        raise RuntimeError("isolated reference database URL is invalid") from exc
    if (
        url.drivername != "postgresql+psycopg"
        or url.username != REFERENCE_USER
        or not isinstance(url.password, str)
        or PASSWORD.fullmatch(url.password) is None
        or url.host is not None
        or url.port is not None
        or url.database != REFERENCE_DATABASE
        or dict(url.query) != {"host": REFERENCE_SOCKET}
    ):
        raise RuntimeError("isolated reference database identity is invalid")
    return raw


def materialize_reference_schema():
    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url
    from sqlalchemy.pool import NullPool

    reference_url = _reference_url(make_url)
    migrations, heads = _migration_schema()
    candidate_manifest = {
        "schema_version": SCHEMA_VERSION,
        "migrations": migrations,
        "heads": heads,
        "model_schema": _model_schema(),
    }
    if candidate_manifest != EXPECTED_MANIFEST:
        raise RuntimeError("candidate runtime manifest differs from bound manifest")
    from app.db.base import Base

    engine = create_engine(reference_url, poolclass=NullPool)
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("SET LOCAL search_path TO public, pg_catalog")
            connection.exec_driver_sql(
                "SET LOCAL standard_conforming_strings TO on"
            )
            identity = connection.exec_driver_sql(
                "SELECT current_database(), current_user, "
                "pg_catalog.inet_server_addr() IS NULL, "
                "pg_catalog.inet_server_port() IS NULL, "
                "current_setting('server_version_num')::integer / 10000, "
                "current_setting('transaction_read_only')"
            ).one()
            if tuple(identity) != (
                REFERENCE_DATABASE,
                REFERENCE_USER,
                True,
                True,
                POSTGRESQL_MAJOR,
                "off",
            ):
                raise RuntimeError("isolated reference database attestation failed")
            relation_count = connection.exec_driver_sql(
                "SELECT pg_catalog.count(*) FROM pg_catalog.pg_class AS relation "
                "JOIN pg_catalog.pg_namespace AS namespace "
                "ON namespace.oid = relation.relnamespace "
                "WHERE namespace.nspname = 'public' "
                "AND relation.relkind IN ('r','p','S','v','m','f')"
            ).scalar_one()
            enum_count = connection.exec_driver_sql(
                "SELECT pg_catalog.count(*) FROM pg_catalog.pg_type AS type_value "
                "JOIN pg_catalog.pg_namespace AS namespace "
                "ON namespace.oid = type_value.typnamespace "
                "WHERE namespace.nspname = 'public' AND type_value.typtype = 'e'"
            ).scalar_one()
            if type(relation_count) is not int or relation_count != 0:
                raise RuntimeError("isolated reference database is not empty")
            if type(enum_count) is not int or enum_count != 0:
                raise RuntimeError("isolated reference database has a preexisting enum")
            Base.metadata.create_all(bind=connection, checkfirst=False)
    finally:
        engine.dispose()
    canonical = json.dumps(
        candidate_manifest,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    print(json.dumps({
        "schema_version": 3,
        "candidate_manifest_sha256": hashlib.sha256(canonical).hexdigest(),
        "table_count": len(candidate_manifest["model_schema"]),
    }, ensure_ascii=True, separators=(",", ":")))


if __name__ == "__main__":
    materialize_reference_schema()
'''

if MIGRATION_PROBE_SOURCE.count(_MIGRATION_PROBE_ENTRYPOINT) != 1:
    raise RuntimeError("migration probe entrypoint identity is invalid")
REFERENCE_SCHEMA_MATERIALIZER_SOURCE = MIGRATION_PROBE_SOURCE.replace(
    _MIGRATION_PROBE_ENTRYPOINT,
    "",
) + REFERENCE_SCHEMA_MATERIALIZER_SUFFIX


def exact_json(actual, expected):
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return set(actual) == set(expected) and all(
            exact_json(actual[key], expected[key]) for key in expected
        )
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(
            exact_json(left, right) for left, right in zip(actual, expected)
        )
    return actual == expected


def require_pinned_spec(value):
    if not isinstance(value, dict) or tuple(value) != SPEC_KEYS:
        raise DeployGuardError("production container spec keys/order are invalid")
    if not exact_json(value, PINNED_SPEC):
        raise DeployGuardError("production container spec differs from the pinned contract")
    return value


def load_spec(path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DeployGuardError("cannot load production container spec") from exc
    return require_pinned_spec(value)


def _owner_only_file_identity(metadata):
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_nlink,
        metadata.st_uid,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _require_owner_only_regular(metadata, label):
    if not stat.S_ISREG(metadata.st_mode):
        raise DeployGuardError("{0} is not a regular file".format(label))
    if metadata.st_uid != os.geteuid():
        raise DeployGuardError("{0} is not owned by the effective user".format(label))
    if stat.S_IMODE(metadata.st_mode) != 0o600:
        raise DeployGuardError("{0} mode must be exactly 0600".format(label))
    if metadata.st_nlink != 1:
        raise DeployGuardError("{0} must have exactly one hard link".format(label))


def read_owner_only_bytes(path, label, maximum_bytes=None):
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
    try:
        descriptor = os.open(os.fspath(path), flags)
    except OSError as exc:
        raise DeployGuardError("cannot open {0}".format(label)) from exc
    try:
        before = os.fstat(descriptor)
        _require_owner_only_regular(before, label)
        if maximum_bytes is not None and before.st_size > maximum_bytes:
            raise DeployGuardError("{0} is too large".format(label))
        chunks = []
        total = 0
        while True:
            remaining = 65536
            if maximum_bytes is not None:
                remaining = min(remaining, maximum_bytes + 1 - total)
                if remaining <= 0:
                    raise DeployGuardError("{0} is too large".format(label))
            chunk = os.read(descriptor, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        after = os.fstat(descriptor)
        _require_owner_only_regular(after, label)
        if _owner_only_file_identity(before) != _owner_only_file_identity(after):
            raise DeployGuardError("{0} changed while it was read".format(label))
        payload = b"".join(chunks)
        if len(payload) != before.st_size:
            raise DeployGuardError("{0} size changed while it was read".format(label))
        return payload
    finally:
        os.close(descriptor)


def _parse_git_tree_manifest(path):
    payload = read_owner_only_bytes(
        path,
        "owner-only exact Git tree manifest",
        maximum_bytes=MAX_GIT_TREE_MANIFEST_BYTES,
    )
    if not payload or not payload.endswith(b"\0"):
        raise DeployGuardError("exact Git tree manifest is not NUL terminated")
    raw_records = payload[:-1].split(b"\0")
    if not raw_records or len(raw_records) > MAX_GIT_TREE_ENTRIES:
        raise DeployGuardError("exact Git tree manifest entry count is invalid")
    entries = {}
    for raw_record in raw_records:
        try:
            header, raw_name = raw_record.split(b"\t", 1)
            mode, object_type, object_id = header.decode("ascii").split(" ")
            name = raw_name.decode("utf-8")
        except (UnicodeError, ValueError) as exc:
            raise DeployGuardError("exact Git tree manifest record is invalid") from exc
        components = name.split("/")
        if (
            mode not in ("100644", "100755")
            or object_type != "blob"
            or GIT_OBJECT_ID.fullmatch(object_id) is None
            or not name
            or name.startswith("/")
            or "\\" in name
            or any(component in ("", ".", "..", ".git") for component in components)
            or posixpath.normpath(name) != name
            or name in entries
        ):
            raise DeployGuardError("exact Git tree manifest identity is invalid")
        entries[name] = (mode, object_id)
    return entries


def _stable_snapshot_file(path, expected_mode, expected_object_id):
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
    try:
        descriptor = os.open(os.fspath(path), flags)
    except OSError as exc:
        raise DeployGuardError("cannot open source snapshot file") from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.geteuid()
            or before.st_nlink != 1
        ):
            raise DeployGuardError("source snapshot file identity is invalid")
        executable = bool(stat.S_IMODE(before.st_mode) & 0o111)
        if executable is not (expected_mode == "100755"):
            raise DeployGuardError("source snapshot executable mode differs from Git")
        digest = hashlib.sha1()
        digest.update("blob {0}\0".format(before.st_size).encode("ascii"))
        total = 0
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            total += len(chunk)
        after = os.fstat(descriptor)
        if _owner_only_file_identity(before) != _owner_only_file_identity(after):
            raise DeployGuardError("source snapshot file changed while it was read")
        if total != before.st_size or digest.hexdigest() != expected_object_id:
            raise DeployGuardError("source snapshot bytes differ from exact Git blob")
    finally:
        os.close(descriptor)


def validate_source_snapshot(manifest, source_root):
    entries = _parse_git_tree_manifest(manifest)
    root = Path(source_root)
    try:
        root_metadata = os.lstat(root)
    except OSError as exc:
        raise DeployGuardError("cannot inspect source snapshot root") from exc
    if (
        not stat.S_ISDIR(root_metadata.st_mode)
        or stat.S_ISLNK(root_metadata.st_mode)
        or root_metadata.st_uid != os.geteuid()
        or stat.S_IMODE(root_metadata.st_mode) & 0o022
    ):
        raise DeployGuardError("source snapshot root identity is invalid")

    expected_directories = set()
    for name in entries:
        parent = posixpath.dirname(name)
        while parent:
            expected_directories.add(parent)
            parent = posixpath.dirname(parent)
    observed_files = set()
    observed_directories = set()
    for directory, directory_names, file_names in os.walk(
        root, topdown=True, followlinks=False
    ):
        directory_names.sort()
        file_names.sort()
        for child_name in directory_names:
            child = Path(directory) / child_name
            relative = child.relative_to(root).as_posix()
            metadata = os.lstat(child)
            if (
                not stat.S_ISDIR(metadata.st_mode)
                or stat.S_ISLNK(metadata.st_mode)
                or metadata.st_uid != os.geteuid()
                or stat.S_IMODE(metadata.st_mode) & 0o022
            ):
                raise DeployGuardError("source snapshot directory identity is invalid")
            observed_directories.add(relative)
        for child_name in file_names:
            child = Path(directory) / child_name
            relative = child.relative_to(root).as_posix()
            expected = entries.get(relative)
            if expected is None:
                raise DeployGuardError("source snapshot contains an extra file")
            _stable_snapshot_file(child, expected[0], expected[1])
            observed_files.add(relative)
    if observed_directories != expected_directories:
        raise DeployGuardError("source snapshot directory set differs from exact Git tree")
    if observed_files != set(entries):
        raise DeployGuardError("source snapshot file set differs from exact Git tree")
    return len(entries)


def _open_safe_output_parent(path):
    output = Path(path)
    parent = output.parent
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_DIRECTORY
    try:
        descriptor = os.open(os.fspath(parent), flags)
    except OSError as exc:
        raise DeployGuardError("cannot open output directory") from exc
    metadata = os.fstat(descriptor)
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.geteuid():
        os.close(descriptor)
        raise DeployGuardError("output directory identity is invalid")
    if stat.S_IMODE(metadata.st_mode) & 0o022:
        os.close(descriptor)
        raise DeployGuardError("output directory must not be group/world writable")
    if output.name in ("", ".", ".."):
        os.close(descriptor)
        raise DeployGuardError("output filename is invalid")
    return descriptor, output.name


def _write_all(descriptor, payload):
    offset = 0
    while offset < len(payload):
        written = os.write(descriptor, payload[offset:])
        if written <= 0:
            raise DeployGuardError("cannot complete owner-only output")
        offset += written


def write_exclusive_bytes(path, payload):
    parent_descriptor, name = _open_safe_output_parent(path)
    descriptor = None
    created = False
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= os.O_CLOEXEC | os.O_NOFOLLOW
        descriptor = os.open(name, flags, 0o600, dir_fd=parent_descriptor)
        created = True
        os.fchmod(descriptor, 0o600)
        _require_owner_only_regular(os.fstat(descriptor), "owner-only output")
        _write_all(descriptor, payload)
        os.fsync(descriptor)
        _require_owner_only_regular(os.fstat(descriptor), "owner-only output")
        os.fsync(parent_descriptor)
    except OSError as exc:
        if created:
            try:
                os.unlink(name, dir_fd=parent_descriptor)
            except OSError:
                pass
        raise DeployGuardError("cannot create owner-only output") from exc
    except Exception:
        if created:
            try:
                os.unlink(name, dir_fd=parent_descriptor)
            except OSError:
                pass
        raise
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(parent_descriptor)


def parse_env_bytes(payload):
    if b"\0" in payload or b"\r" in payload:
        raise DeployGuardError("production env file contains an invalid entry")
    try:
        text = payload.decode("utf-8")
    except UnicodeError as exc:
        raise DeployGuardError("production env file is not UTF-8") from exc
    values = {}
    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in raw_line:
            raise DeployGuardError("production env file contains an invalid entry")
        name, value = raw_line.split("=", 1)
        if name != name.strip():
            raise DeployGuardError("production env file has whitespace around a name")
        if ENVIRONMENT_NAME.fullmatch(name) is None or name in values:
            raise DeployGuardError("production env file has an invalid or duplicate name")
        values[name] = value
    if not values:
        raise DeployGuardError("production env file is empty")
    return values


def parse_env_file(path):
    return parse_env_bytes(
        read_owner_only_bytes(
            path,
            "owner-only production env file",
            maximum_bytes=MAX_ENV_FILE_BYTES,
        )
    )


def _runtime_image_markers(env_values):
    if not isinstance(env_values, dict) or not env_values:
        raise DeployGuardError("runtime environment marker map is invalid")
    markers = set(IMAGE_ARCHIVE_MARKERS)
    for name, value in env_values.items():
        if (
            not isinstance(name, str)
            or ENVIRONMENT_NAME.fullmatch(name) is None
            or not isinstance(value, str)
        ):
            raise DeployGuardError("runtime environment marker map is invalid")
        try:
            assignment = "{0}={1}".format(name, value).encode("utf-8")
            encoded_value = value.encode("utf-8")
        except UnicodeError as exc:
            raise DeployGuardError("runtime environment marker is not UTF-8") from exc
        markers.add(assignment)
        if len(encoded_value) >= 8 and SENSITIVE_ENVIRONMENT_NAME.search(name):
            markers.add(encoded_value)
    return tuple(sorted(markers, key=lambda item: (len(item), item)))


class _MarkerScanner:
    def __init__(self, markers):
        if not markers or any(not isinstance(item, bytes) or not item for item in markers):
            raise DeployGuardError("image archive marker set is invalid")
        self._markers = tuple(markers)
        self._tail = b""
        self._tail_size = max(len(item) for item in self._markers) - 1

    def feed(self, payload):
        if not payload:
            return
        combined = self._tail + payload
        if any(marker in combined for marker in self._markers):
            raise DeployGuardError("candidate image archive contains forbidden material")
        if self._tail_size:
            self._tail = combined[-self._tail_size :]


class _OwnerOnlyArchiveStream:
    def __init__(self, descriptor, size, scanner):
        self._descriptor = descriptor
        self.remaining = size
        self._scanner = scanner

    def read(self, size=-1):
        if self.remaining == 0:
            return b""
        if size is None or size < 0:
            size = self.remaining
        size = min(size, self.remaining)
        try:
            payload = os.read(self._descriptor, size)
        except OSError as exc:
            raise DeployGuardError("cannot read owner-only image archive") from exc
        if not payload:
            raise DeployGuardError("candidate image archive is truncated")
        self.remaining -= len(payload)
        self._scanner.feed(payload)
        return payload

    def readable(self):
        return True


def _safe_tar_path(value, label):
    if not isinstance(value, str) or not value or "\x00" in value or "\\" in value:
        raise DeployGuardError("{0} path is invalid".format(label))
    try:
        encoded = value.encode("utf-8")
    except UnicodeError as exc:
        raise DeployGuardError("{0} path is not UTF-8".format(label)) from exc
    if len(encoded) > MAX_IMAGE_PATH_BYTES or value.startswith("/"):
        raise DeployGuardError("{0} path is unsafe".format(label))
    normalized = value.rstrip("/")
    components = normalized.split("/")
    if (
        not normalized
        or any(component in ("", ".", "..") for component in components)
        or posixpath.normpath(normalized) != normalized
    ):
        raise DeployGuardError("{0} path is unsafe".format(label))
    return normalized


def _safe_tar_link_target(value):
    if not isinstance(value, str) or not value or "\x00" in value or "\\" in value:
        raise DeployGuardError("image layer link target is invalid")
    try:
        encoded = value.encode("utf-8")
    except UnicodeError as exc:
        raise DeployGuardError("image layer link target is not UTF-8") from exc
    if len(encoded) > MAX_IMAGE_PATH_BYTES or "//" in value:
        raise DeployGuardError("image layer link target is unsafe")
    normalized = value.lstrip("/").rstrip("/")
    components = normalized.split("/")
    if not normalized or any(component in ("", ".", "..") for component in components):
        raise DeployGuardError("image layer link target is unsafe")


def _unsafe_image_path(path):
    name = path.rsplit("/", 1)[-1]
    lower = name.lower()
    return (
        lower in IMAGE_UNSAFE_NAMES
        or lower.startswith(".env.")
        or any(lower.endswith(suffix) for suffix in IMAGE_UNSAFE_SUFFIXES)
    )


def _read_tar_member(stream, size, *, collect=False, digest=False):
    if type(size) is not int or size < 0 or size > MAX_IMAGE_ARCHIVE_MEMBER_BYTES:
        raise DeployGuardError("candidate image archive member size is invalid")
    remaining = size
    chunks = [] if collect else None
    hasher = hashlib.sha256() if digest else None
    while remaining:
        payload = stream.read(min(IMAGE_ARCHIVE_READ_BYTES, remaining))
        if not payload:
            raise DeployGuardError("candidate image archive member is truncated")
        if len(payload) > remaining:
            raise DeployGuardError("candidate image archive member exceeded its declared size")
        remaining -= len(payload)
        if chunks is not None:
            chunks.append(payload)
        if hasher is not None:
            hasher.update(payload)
    return (
        b"".join(chunks) if chunks is not None else None,
        hasher.hexdigest() if hasher is not None else None,
    )


def _scan_image_layer(stream):
    seen = set()
    count = 0
    try:
        archive = tarfile.open(fileobj=stream, mode="r|")
        try:
            for member in archive:
                count += 1
                if count > MAX_IMAGE_ARCHIVE_MEMBERS:
                    raise DeployGuardError("candidate image layer has too many members")
                path = _safe_tar_path(member.name, "image layer member")
                if path in seen:
                    raise DeployGuardError("candidate image layer contains a duplicate path")
                seen.add(path)
                if type(member.size) is not int or member.size < 0:
                    raise DeployGuardError("candidate image layer member size is invalid")
                if member.size > MAX_IMAGE_ARCHIVE_MEMBER_BYTES:
                    raise DeployGuardError("candidate image layer member is too large")
                if member.isreg():
                    if _unsafe_image_path(path):
                        raise DeployGuardError("candidate image layer contains a forbidden path")
                    extracted = archive.extractfile(member)
                    if extracted is None:
                        raise DeployGuardError("candidate image layer member cannot be read")
                    _read_tar_member(extracted, member.size)
                elif member.isdir():
                    if member.size != 0:
                        raise DeployGuardError("candidate image layer directory has content")
                elif member.issym() or member.islnk():
                    if member.size != 0:
                        raise DeployGuardError("candidate image layer link has content")
                    _safe_tar_link_target(member.linkname)
                elif (
                    member.ischr()
                    and path.rsplit("/", 1)[-1].startswith(".wh.")
                    and member.size == 0
                    and member.devmajor == 0
                    and member.devminor == 0
                ):
                    # OCI/Docker whiteouts are the sole special-file exception.  They are
                    # metadata for a deleted lower-layer path and are never extracted here.
                    continue
                else:
                    raise DeployGuardError("candidate image layer contains a special member")
        finally:
            archive.close()
    except (tarfile.TarError, ValueError, OverflowError) as exc:
        raise DeployGuardError("candidate image layer tar is invalid") from exc
    if not seen:
        raise DeployGuardError("candidate image layer is empty")
    return count


def _validate_docker_save_manifest(payload, expected_image_id):
    try:
        manifest = json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise DeployGuardError("docker image save manifest is invalid") from exc
    if not isinstance(manifest, list) or len(manifest) != 1 or not isinstance(manifest[0], dict):
        raise DeployGuardError("docker image save must contain exactly one image")
    entry = manifest[0]
    config = entry.get("Config")
    layers = entry.get("Layers")
    if not isinstance(config, str) or not isinstance(layers, list) or not layers:
        raise DeployGuardError("docker image save manifest is incomplete")
    config = _safe_tar_path(config, "docker image config")
    normalized_layers = []
    for layer in layers:
        normalized_layers.append(_safe_tar_path(layer, "docker image layer"))
    if len(normalized_layers) != len(set(normalized_layers)):
        raise DeployGuardError("docker image save manifest repeats a layer")
    digest = expected_image_id.removeprefix("sha256:")
    if config != digest + ".json":
        raise DeployGuardError("docker image save config is not bound to the expected image ID")
    return config, normalized_layers


def _scan_docker_save_archive(stream, expected_image_id):
    seen = set()
    member_digests = {}
    manifest_payload = None
    scanned_layers = set()
    member_count = 0
    layer_member_count = 0
    try:
        archive = tarfile.open(fileobj=stream, mode="r|")
        try:
            for member in archive:
                member_count += 1
                if member_count > MAX_IMAGE_ARCHIVE_MEMBERS:
                    raise DeployGuardError("docker image save archive has too many members")
                path = _safe_tar_path(member.name, "docker image save member")
                if path in seen:
                    raise DeployGuardError("docker image save archive contains a duplicate path")
                seen.add(path)
                if type(member.size) is not int or member.size < 0:
                    raise DeployGuardError("docker image save member size is invalid")
                if member.size > MAX_IMAGE_ARCHIVE_MEMBER_BYTES:
                    raise DeployGuardError("docker image save member is too large")
                if member.isreg():
                    extracted = archive.extractfile(member)
                    if extracted is None:
                        raise DeployGuardError("docker image save member cannot be read")
                    if path.endswith("/layer.tar"):
                        layer_member_count += _scan_image_layer(extracted)
                        scanned_layers.add(path)
                    else:
                        collect = path == "manifest.json"
                        if collect and member.size > MAX_IMAGE_MANIFEST_BYTES:
                            raise DeployGuardError("docker image save manifest is too large")
                        payload, digest = _read_tar_member(
                            extracted,
                            member.size,
                            collect=collect,
                            digest=True,
                        )
                        member_digests[path] = digest
                        if collect:
                            if manifest_payload is not None:
                                raise DeployGuardError("docker image save repeats its manifest")
                            manifest_payload = payload
                elif member.isdir():
                    if member.size != 0:
                        raise DeployGuardError("docker image save directory has content")
                else:
                    raise DeployGuardError("docker image save contains a link or special member")
        finally:
            archive.close()
    except (tarfile.TarError, ValueError, OverflowError) as exc:
        raise DeployGuardError("docker image save tar is invalid") from exc
    if manifest_payload is None:
        raise DeployGuardError("docker image save manifest is missing")
    config, manifest_layers = _validate_docker_save_manifest(
        manifest_payload, expected_image_id
    )
    if set(manifest_layers) != scanned_layers:
        raise DeployGuardError("docker image save layers do not match its manifest")
    if config not in member_digests:
        raise DeployGuardError("docker image save config is missing")
    if member_digests[config] != expected_image_id.removeprefix("sha256:"):
        raise DeployGuardError("docker image save config digest differs from its image ID")
    if layer_member_count > MAX_IMAGE_ARCHIVE_MEMBERS:
        raise DeployGuardError("docker image save layers contain too many members")


def validate_candidate_image_secret_boundary(image_inspect, env_values, expected_image_id):
    if not isinstance(expected_image_id, str) or IMAGE_ID.fullmatch(expected_image_id) is None:
        raise DeployGuardError("expected candidate image ID is invalid")
    image_id, config = require_image(image_inspect, "candidate")
    if image_id != expected_image_id:
        raise DeployGuardError("candidate image inspect differs from the expected image ID")
    image_environment = environment_map(config.get("Env") or [], "candidate image")
    if set(image_environment).intersection(env_values):
        raise DeployGuardError("candidate image Config.Env contains a runtime-only key")
    if any(SENSITIVE_ENVIRONMENT_NAME.search(name) for name in image_environment):
        raise DeployGuardError("candidate image Config.Env contains a sensitive key")
    return image_id


def scan_owner_only_image_archive(path, env_values, expected_image_id):
    if not isinstance(expected_image_id, str) or IMAGE_ID.fullmatch(expected_image_id) is None:
        raise DeployGuardError("expected candidate image ID is invalid")
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
    try:
        descriptor = os.open(os.fspath(path), flags)
    except OSError as exc:
        raise DeployGuardError("cannot open owner-only image archive") from exc
    try:
        before = os.fstat(descriptor)
        _require_owner_only_regular(before, "owner-only image archive")
        if before.st_size <= 0 or before.st_size > MAX_IMAGE_ARCHIVE_BYTES:
            raise DeployGuardError("owner-only image archive size is invalid")
        scanner = _MarkerScanner(_runtime_image_markers(env_values))
        stream = _OwnerOnlyArchiveStream(descriptor, before.st_size, scanner)
        _scan_docker_save_archive(stream, expected_image_id)
        while stream.remaining:
            trailing = stream.read(min(IMAGE_ARCHIVE_READ_BYTES, stream.remaining))
            if any(trailing):
                raise DeployGuardError("docker image save has non-zero trailing data")
        after = os.fstat(descriptor)
        _require_owner_only_regular(after, "owner-only image archive")
        if _owner_only_file_identity(before) != _owner_only_file_identity(after):
            raise DeployGuardError("owner-only image archive changed while it was read")
    finally:
        os.close(descriptor)


def one_owner_only_object(path, label, maximum_bytes=MAX_IMAGE_INSPECT_BYTES):
    raw = read_owner_only_bytes(path, label, maximum_bytes=maximum_bytes)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise DeployGuardError("cannot load {0}".format(label)) from exc
    if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
        raise DeployGuardError("{0} must contain exactly one object".format(label))
    return payload[0]


def snapshot_env_file(spec, source, output):
    require_pinned_spec(spec)
    if os.fspath(source) != spec["secret_env_file"]:
        raise DeployGuardError("env snapshot source differs from the pinned spec")
    payload = read_owner_only_bytes(
        source,
        "owner-only production env file",
        maximum_bytes=MAX_ENV_FILE_BYTES,
    )
    values = parse_env_bytes(payload)
    values.pop(DATABASE_PROBE_URL_KEY, None)
    values.pop(DATABASE_MIGRATION_URL_KEY, None)
    if not values:
        raise DeployGuardError("production application env snapshot is empty")
    application_payload = "".join(
        "{0}={1}\n".format(name, value) for name, value in values.items()
    ).encode("utf-8")
    write_exclusive_bytes(output, application_payload)


DATABASE_CONNECTION_QUERY_ENVIRONMENT = {
    "application_name": "PGAPPNAME",
    "channel_binding": "PGCHANNELBINDING",
    "connect_timeout": "PGCONNECT_TIMEOUT",
    "sslmode": "PGSSLMODE",
    "target_session_attrs": "PGTARGETSESSIONATTRS",
}


def _normalized_database_hostname(value, label):
    if (
        type(value) is not str
        or not value
        or "%" in value
        or any(character.isspace() for character in value)
    ):
        raise DeployGuardError("{0} hostname is invalid".format(label))
    try:
        return ipaddress.ip_address(value).compressed.lower()
    except ValueError:
        try:
            normalized = value.rstrip(".").encode("idna").decode("ascii").lower()
        except UnicodeError as exc:
            raise DeployGuardError("{0} hostname is invalid".format(label)) from exc
        if (
            not normalized
            or len(normalized) > 253
            or any(
                re.fullmatch(
                    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?",
                    part,
                )
                is None
                for part in normalized.split(".")
            )
        ):
            raise DeployGuardError("{0} hostname is invalid".format(label))
        return normalized


def _database_connection_identity(raw, label):
    if type(raw) is not str or raw != raw.strip() or not raw:
        raise DeployGuardError("{0} identity is invalid".format(label))
    parsed = urllib.parse.urlsplit(raw)
    try:
        port = parsed.port or 5432
        query_pairs = (
            urllib.parse.parse_qsl(
                parsed.query,
                keep_blank_values=True,
                strict_parsing=True,
                encoding="utf-8",
                errors="strict",
            )
            if parsed.query
            else []
        )
    except (ValueError, UnicodeError) as exc:
        raise DeployGuardError("{0} identity is invalid".format(label)) from exc
    if (
        parsed.scheme not in ("postgresql", "postgresql+psycopg")
        or not parsed.hostname
        or parsed.username is None
        or parsed.password is None
        or not parsed.path.startswith("/")
        or parsed.path == "/"
        or parsed.fragment
        or not 1 <= port <= 65535
    ):
        raise DeployGuardError("{0} identity is invalid".format(label))
    try:
        database_name = urllib.parse.unquote(parsed.path[1:], errors="strict")
        username = urllib.parse.unquote(parsed.username, errors="strict")
        password = urllib.parse.unquote(parsed.password, errors="strict")
    except UnicodeError as exc:
        raise DeployGuardError("{0} encoding is invalid".format(label)) from exc
    if (
        not database_name
        or "/" in database_name
        or not username
        or not password
        or any("\0" in item or "\n" in item or "\r" in item for item in (
            database_name,
            username,
            password,
        ))
    ):
        raise DeployGuardError("{0} identity is invalid".format(label))
    if len(query_pairs) != len({name for name, _ in query_pairs}):
        raise DeployGuardError("{0} query contains duplicates".format(label))
    query_values = {}
    for name, value in query_pairs:
        environment_name = DATABASE_CONNECTION_QUERY_ENVIRONMENT.get(name)
        if environment_name is None or not value or any(
            character in value for character in "\0\n\r"
        ):
            raise DeployGuardError("{0} query is unsupported".format(label))
        query_values[environment_name] = value
    return {
        "scheme": parsed.scheme,
        "hostname": _normalized_database_hostname(parsed.hostname, label),
        "port": port,
        "database": database_name,
        "username": username,
        "password": password,
        "query_environment": query_values,
    }


def snapshot_database_probe_env_file(spec, source, application_env, output):
    require_pinned_spec(spec)
    if os.fspath(source) != spec["secret_env_file"]:
        raise DeployGuardError("database probe env source differs from the pinned spec")
    source_payload = read_owner_only_bytes(
        source,
        "owner-only production env file",
        maximum_bytes=MAX_ENV_FILE_BYTES,
    )
    values = parse_env_bytes(source_payload)
    application_values = parse_env_bytes(
        read_owner_only_bytes(
            application_env,
            "owner-only application env snapshot",
            maximum_bytes=MAX_ENV_FILE_BYTES,
        )
    )
    source_application_values = dict(values)
    source_application_values.pop(DATABASE_PROBE_URL_KEY, None)
    source_application_values.pop(DATABASE_MIGRATION_URL_KEY, None)
    if not source_application_values or not exact_json(
        source_application_values,
        application_values,
    ):
        raise DeployGuardError(
            "production env changed after the application snapshot"
        )
    application_url = values.get("DATABASE_URL")
    probe_url = values.get(DATABASE_PROBE_URL_KEY)
    if (
        not isinstance(application_url, str)
        or not application_url
        or not isinstance(probe_url, str)
        or probe_url != probe_url.strip()
        or probe_url == application_url
    ):
        raise DeployGuardError(
            "production env requires a distinct PostgreSQL DATABASE_PROBE_URL"
        )
    application_identity = _database_connection_identity(
        application_url,
        "DATABASE_URL",
    )
    probe_identity = _database_connection_identity(
        probe_url,
        "DATABASE_PROBE_URL",
    )
    if application_identity["username"] == probe_identity["username"]:
        raise DeployGuardError(
            "DATABASE_PROBE_URL must authenticate as a distinct PostgreSQL role"
        )
    for key in ("scheme", "hostname", "port", "database"):
        if application_identity[key] != probe_identity[key]:
            raise DeployGuardError(
                "DATABASE_URL and DATABASE_PROBE_URL endpoints differ"
            )
    connection_values = {
        "PGHOST": probe_identity["hostname"],
        "PGPORT": str(probe_identity["port"]),
        "PGUSER": probe_identity["username"],
        "PGPASSWORD": probe_identity["password"],
        "PGDATABASE": probe_identity["database"],
    }
    connection_values.update(probe_identity["query_environment"])
    for name, value in connection_values.items():
        if not value or any(character in value for character in "\0\n\r"):
            raise DeployGuardError(
                "DATABASE_PROBE_URL {0} value is invalid".format(name)
            )
    connection_values["PGOPTIONS"] = DATABASE_PROBE_PGOPTIONS
    connection_values["XJIE_EXPECTED_DATABASE"] = probe_identity["database"]
    payload = "".join(
        "{0}={1}\n".format(name, connection_values[name])
        for name in (
            "PGHOST",
            "PGPORT",
            "PGUSER",
            "PGPASSWORD",
            "PGDATABASE",
            *sorted(set(connection_values) - {
                "PGHOST", "PGPORT", "PGUSER", "PGPASSWORD", "PGDATABASE",
                "PGOPTIONS", "XJIE_EXPECTED_DATABASE",
            }),
            "PGOPTIONS",
            "XJIE_EXPECTED_DATABASE",
        )
    ).encode("utf-8")
    write_exclusive_bytes(output, payload)


def snapshot_database_migration_env_file(spec, source, application_env, output):
    """Emit only the approved migration role's libpq identity.

    The original owner-only env is reread after the application snapshot.  The
    comparison intentionally removes both privileged database identities, so
    neither can enter the candidate application's runtime environment.
    """

    require_pinned_spec(spec)
    if os.fspath(source) != spec["secret_env_file"]:
        raise DeployGuardError("database migration env source differs from the pinned spec")
    source_payload = read_owner_only_bytes(
        source,
        "owner-only production env file",
        maximum_bytes=MAX_ENV_FILE_BYTES,
    )
    values = parse_env_bytes(source_payload)
    application_values = parse_env_bytes(
        read_owner_only_bytes(
            application_env,
            "owner-only application env snapshot",
            maximum_bytes=MAX_ENV_FILE_BYTES,
        )
    )
    source_application_values = dict(values)
    source_application_values.pop(DATABASE_PROBE_URL_KEY, None)
    source_application_values.pop(DATABASE_MIGRATION_URL_KEY, None)
    if not source_application_values or not exact_json(
        source_application_values,
        application_values,
    ):
        raise DeployGuardError(
            "production env changed after the application snapshot"
        )

    identities = {
        name: _database_connection_identity(values.get(name), name)
        for name in (
            "DATABASE_URL",
            DATABASE_PROBE_URL_KEY,
            DATABASE_MIGRATION_URL_KEY,
        )
    }
    usernames = [identity["username"] for identity in identities.values()]
    if len(set(usernames)) != len(usernames):
        raise DeployGuardError(
            "application, probe, and migration database roles must be distinct"
        )
    application_identity = identities["DATABASE_URL"]
    for name in (DATABASE_PROBE_URL_KEY, DATABASE_MIGRATION_URL_KEY):
        identity = identities[name]
        for key in ("scheme", "hostname", "port", "database"):
            if identity[key] != application_identity[key]:
                raise DeployGuardError(
                    "DATABASE_URL and {0} endpoints differ".format(name)
                )

    migration_identity = identities[DATABASE_MIGRATION_URL_KEY]
    connection_values = {
        "PGHOST": migration_identity["hostname"],
        "PGPORT": str(migration_identity["port"]),
        "PGUSER": migration_identity["username"],
        "PGPASSWORD": migration_identity["password"],
        "PGDATABASE": migration_identity["database"],
    }
    connection_values.update(migration_identity["query_environment"])
    for name, value in connection_values.items():
        if not value or any(character in value for character in "\0\n\r"):
            raise DeployGuardError(
                "DATABASE_MIGRATION_URL {0} value is invalid".format(name)
            )
    ordered_names = (
        "PGHOST",
        "PGPORT",
        "PGUSER",
        "PGPASSWORD",
        "PGDATABASE",
        *sorted(
            set(connection_values)
            - {"PGHOST", "PGPORT", "PGUSER", "PGPASSWORD", "PGDATABASE"}
        ),
    )
    payload = "".join(
        "{0}={1}\n".format(name, connection_values[name])
        for name in ordered_names
    ).encode("utf-8")
    write_exclusive_bytes(output, payload)


def emitted_spec_values(spec):
    require_pinned_spec(spec)
    return [spec[key] for key in EMITTED_SPEC_KEYS]


def environment_map(items, source):
    if not isinstance(items, list):
        raise DeployGuardError("{0} environment is not a list".format(source))
    values = {}
    for item in items:
        if not isinstance(item, str) or "=" not in item or "\x00" in item:
            raise DeployGuardError("{0} environment contains an invalid entry".format(source))
        name, value = item.split("=", 1)
        if ENVIRONMENT_NAME.fullmatch(name) is None or name in values:
            raise DeployGuardError("{0} environment has an invalid or duplicate name".format(source))
        values[name] = value
    return values


def one_object(path, label):
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DeployGuardError("cannot load {0} inspect payload".format(label)) from exc
    if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
        raise DeployGuardError("{0} inspect must contain exactly one object".format(label))
    return payload[0]


def require_image(payload, label):
    image_id = payload.get("Id")
    config = payload.get("Config")
    if not isinstance(image_id, str) or IMAGE_ID.fullmatch(image_id) is None:
        raise DeployGuardError("{0} image ID is invalid".format(label))
    if not isinstance(config, dict):
        raise DeployGuardError("{0} image Config is missing".format(label))
    return image_id, config


def require_container(payload, label):
    container_id = payload.get("Id")
    name = payload.get("Name")
    image_id = payload.get("Image")
    config = payload.get("Config")
    host = payload.get("HostConfig")
    mounts = payload.get("Mounts")
    network_settings = payload.get("NetworkSettings")
    if not isinstance(container_id, str) or CONTAINER_ID.fullmatch(container_id) is None:
        raise DeployGuardError("{0} container ID is invalid".format(label))
    if not isinstance(name, str) or not name.startswith("/") or CONTAINER_NAME.fullmatch(name[1:]) is None:
        raise DeployGuardError("{0} container name is invalid".format(label))
    if not isinstance(image_id, str) or IMAGE_ID.fullmatch(image_id) is None:
        raise DeployGuardError("{0} container image ID is invalid".format(label))
    if (
        not isinstance(config, dict)
        or not isinstance(host, dict)
        or not isinstance(mounts, list)
        or not isinstance(network_settings, dict)
        or not isinstance(network_settings.get("Networks"), dict)
    ):
        raise DeployGuardError("{0} container inspect is incomplete".format(label))
    unknown_config = set(config) - CONTAINER_CONFIG_KEYS
    if unknown_config:
        raise DeployGuardError("{0} container Config has unknown fields".format(label))
    return (
        container_id,
        name,
        image_id,
        config,
        host,
        mounts,
        network_settings["Networks"],
    )


def _normalized_string_list(value, label):
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise DeployGuardError("{0} must be a string list or null".format(label))
    return sorted(value)


def _stable_endpoint_mac(endpoint):
    mac_address = endpoint.get("MacAddress") or ""
    ip_address = endpoint.get("IPAddress") or ""
    try:
        packed = ipaddress.IPv4Address(ip_address).packed
    except ipaddress.AddressValueError:
        return mac_address
    automatic = "02:42:" + ":".join("{0:02x}".format(byte) for byte in packed)
    if mac_address.lower() == automatic:
        return ""
    return mac_address


def normalized_network_topology(networks, container_id, container_name, config, label):
    if not networks or any(not isinstance(name, str) or not name for name in networks):
        raise DeployGuardError("{0} Networks is empty or invalid".format(label))
    identity_aliases = {
        container_id,
        container_id[:12],
        container_name.removeprefix("/"),
        config.get("Hostname"),
    }
    normalized = {}
    for network_name, endpoint in networks.items():
        if not isinstance(endpoint, dict):
            raise DeployGuardError("{0} network endpoint is invalid".format(label))
        if set(endpoint) - NETWORK_ENDPOINT_KEYS:
            raise DeployGuardError("{0} network endpoint has unknown fields".format(label))
        ipam = endpoint.get("IPAMConfig")
        if ipam is not None and not isinstance(ipam, dict):
            raise DeployGuardError("{0} IPAMConfig is invalid".format(label))
        if isinstance(ipam, dict):
            if set(ipam) - NETWORK_IPAM_KEYS:
                raise DeployGuardError("{0} IPAMConfig has unknown fields".format(label))
            for address_key in ("IPv4Address", "IPv6Address"):
                if address_key in ipam and not isinstance(ipam[address_key], str):
                    raise DeployGuardError("{0} IPAMConfig address is invalid".format(label))
            link_local = ipam.get("LinkLocalIPs")
            if link_local is not None and (
                not isinstance(link_local, list)
                or any(not isinstance(item, str) for item in link_local)
            ):
                raise DeployGuardError("{0} LinkLocalIPs is invalid".format(label))
        driver_options = endpoint.get("DriverOpts")
        if driver_options is not None and (
            not isinstance(driver_options, dict)
            or any(not isinstance(key, str) or not isinstance(value, str)
                   for key, value in driver_options.items())
        ):
            raise DeployGuardError("{0} DriverOpts is invalid".format(label))
        gateway_priority = endpoint.get("GwPriority", 0)
        if type(gateway_priority) is not int:
            raise DeployGuardError("{0} GwPriority is invalid".format(label))
        for field in (
            "MacAddress",
            "NetworkID",
            "EndpointID",
            "Gateway",
            "IPAddress",
            "IPv6Gateway",
            "GlobalIPv6Address",
        ):
            if field in endpoint and not isinstance(endpoint[field], str):
                raise DeployGuardError("{0} network {1} is invalid".format(label, field))
        for field in ("IPPrefixLen", "GlobalIPv6PrefixLen"):
            if field in endpoint and type(endpoint[field]) is not int:
                raise DeployGuardError("{0} network {1} is invalid".format(label, field))
        aliases = [
            item for item in _normalized_string_list(
                endpoint.get("Aliases"), "{0} Aliases".format(label)
            )
            if item not in identity_aliases
        ]
        dns_names = [
            item for item in _normalized_string_list(
                endpoint.get("DNSNames"), "{0} DNSNames".format(label)
            )
            if item not in identity_aliases
        ]
        links = _normalized_string_list(
            endpoint.get("Links"), "{0} Links".format(label)
        )
        normalized[network_name] = {
            "IPAMConfig": ipam,
            "Links": links,
            "Aliases": sorted(aliases),
            "MacAddress": _stable_endpoint_mac(endpoint),
            "DriverOpts": driver_options,
            "GwPriority": gateway_priority,
            "DNSNames": sorted(dns_names),
        }
    return normalized


def _expected_port_bindings():
    return {"8000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8000"}]}


def host_configs_match_with_loopback_tightening(old_host, candidate_host):
    expected = _expected_port_bindings()
    if not exact_json(candidate_host.get("PortBindings"), expected):
        return False
    old_bindings = old_host.get("PortBindings")
    if not isinstance(old_bindings, dict) or set(old_bindings) != {"8000/tcp"}:
        return False
    bindings = old_bindings["8000/tcp"]
    if not isinstance(bindings, list) or len(bindings) != 1 or not isinstance(bindings[0], dict):
        return False
    if set(bindings[0]) != {"HostIp", "HostPort"}:
        return False
    if bindings[0]["HostIp"] not in ("", "0.0.0.0", "127.0.0.1"):
        return False
    if bindings[0]["HostPort"] != "8000":
        return False
    normalized_old = dict(old_host)
    normalized_candidate = dict(candidate_host)
    normalized_old["PortBindings"] = expected
    normalized_candidate["PortBindings"] = expected
    return exact_json(normalized_old, normalized_candidate)


def validate_inspects(
    spec,
    old_container,
    old_image,
    candidate_container,
    candidate_image,
    env_values,
    expected_sha,
):
    require_pinned_spec(spec)
    if REVISION.fullmatch(expected_sha) is None:
        raise DeployGuardError("expected revision must be a lowercase full Git SHA")
    old_image_id, old_image_config = require_image(old_image, "old")
    candidate_image_id, candidate_image_config = require_image(candidate_image, "candidate")
    (
        old_container_id,
        old_name,
        old_bound_image,
        old_config,
        old_host,
        old_mounts,
        old_networks,
    ) = require_container(
        old_container, "old"
    )
    (
        candidate_container_id,
        candidate_name,
        candidate_bound_image,
        candidate_config,
        candidate_host,
        candidate_mounts,
        candidate_networks,
    ) = require_container(candidate_container, "candidate")
    if old_name != "/" + spec["container_name"]:
        raise DeployGuardError("old container name differs from the pinned spec")
    if not candidate_name.startswith("/" + spec["container_name"] + "-"):
        raise DeployGuardError("candidate container name differs from the pinned spec")
    if old_bound_image != old_image_id or candidate_bound_image != candidate_image_id:
        raise DeployGuardError("container/image inspect IDs do not match")
    if candidate_config.get("Image") != candidate_bound_image:
        raise DeployGuardError("candidate Config.Image is not the immutable image ID")
    if old_mounts or candidate_mounts:
        raise DeployGuardError("the declarative production container does not permit mounts")
    if not host_configs_match_with_loopback_tightening(old_host, candidate_host):
        raise DeployGuardError(
            "candidate HostConfig differs beyond the one-way loopback port tightening"
        )
    old_topology = normalized_network_topology(
        old_networks, old_container_id, old_name, old_config, "old container"
    )
    candidate_topology = normalized_network_topology(
        candidate_networks,
        candidate_container_id,
        candidate_name,
        candidate_config,
        "candidate container",
    )
    if not exact_json(old_topology, candidate_topology):
        raise DeployGuardError("candidate network topology does not reproduce production")

    for field in IMAGE_DEFAULT_FIELDS:
        old_value = old_config.get(field)
        old_image_value = old_image_config.get(field)
        candidate_value = candidate_config.get(field)
        candidate_image_value = candidate_image_config.get(field)
        if field == "Labels":
            _validate_deployment_label_overlay(
                old_image_value,
                old_value,
                old_image_id,
                label="old container",
                expected_role="candidate",
                current_name=old_name.removeprefix("/"),
                allow_legacy=True,
            )
            _validate_deployment_label_overlay(
                candidate_image_value,
                candidate_value,
                candidate_image_id,
                label="candidate container",
                expected_sha=expected_sha,
                expected_role="candidate",
                current_name=candidate_name.removeprefix("/"),
            )
            continue
        if not exact_json(old_value, old_image_value):
            raise DeployGuardError("old container has a runtime {0} override".format(field))
        if not exact_json(candidate_value, candidate_image_value):
            raise DeployGuardError("candidate overrides the new image {0}".format(field))
    for field, expected_value in RUNTIME_CONFIG_DEFAULTS.items():
        if field not in old_config or field not in candidate_config:
            raise DeployGuardError("runtime container setting {0} is missing".format(field))
        if not exact_json(old_config[field], expected_value) or not exact_json(
            candidate_config[field], expected_value
        ):
            raise DeployGuardError(
                "runtime container setting {0} differs from its safe default".format(field)
            )
    if old_config.get("Hostname") != old_container_id[:12]:
        raise DeployGuardError("old container has a custom Hostname")
    if candidate_config.get("Hostname") != candidate_container_id[:12]:
        raise DeployGuardError("candidate container has a custom Hostname")

    old_image_env = environment_map(old_image_config.get("Env") or [], "old image")
    old_container_env = environment_map(old_config.get("Env") or [], "old container")
    runtime_delta = {
        name: value
        for name, value in old_container_env.items()
        if old_image_env.get(name) != value
    }
    if not exact_json(runtime_delta, env_values):
        raise DeployGuardError(
            "owner-only env file does not exactly match the old runtime environment delta"
        )
    expected_candidate_env = environment_map(
        candidate_image_config.get("Env") or [], "candidate image"
    )
    expected_candidate_env.update(env_values)
    candidate_env = environment_map(candidate_config.get("Env") or [], "candidate container")
    if not exact_json(candidate_env, expected_candidate_env):
        raise DeployGuardError("candidate environment does not preserve new image defaults")

    image_labels = candidate_image_config.get("Labels") or {}
    if not isinstance(image_labels, dict) or image_labels.get(
        "org.opencontainers.image.revision"
    ) != expected_sha:
        raise DeployGuardError("candidate image is not labeled with the expected Git SHA")
    if candidate_config.get("Labels", {}).get("org.opencontainers.image.revision") != expected_sha:
        raise DeployGuardError("candidate container is not bound to the expected Git SHA")
    if candidate_image_id == old_image_id:
        raise DeployGuardError("candidate image ID did not change")


def deployment_name(run_id, role):
    if not isinstance(run_id, str) or DEPLOY_RUN_ID.fullmatch(run_id) is None:
        raise DeployGuardError("deployment lifecycle run ID is invalid")
    if role not in DEPLOY_LIFECYCLE_ROLES:
        raise DeployGuardError("deployment lifecycle role is invalid")
    return "{0}-deploy-{1}-{2}".format(
        PINNED_SPEC["container_name"], run_id, role
    )


def deployment_labels(name, image, expected_sha, run_id, role):
    if not isinstance(image, str) or IMAGE_ID.fullmatch(image) is None:
        raise DeployGuardError("deployment lifecycle image ID is invalid")
    if not isinstance(expected_sha, str) or REVISION.fullmatch(expected_sha) is None:
        raise DeployGuardError("deployment lifecycle revision is invalid")
    expected_name = deployment_name(run_id, role)
    if name != expected_name:
        raise DeployGuardError("deployment lifecycle name/role identity is invalid")
    return {
        DEPLOY_LABEL_KEYS[0]: "1",
        DEPLOY_LABEL_KEYS[1]: "production-api",
        DEPLOY_LABEL_KEYS[2]: "main",
        DEPLOY_LABEL_KEYS[3]: expected_sha,
        DEPLOY_LABEL_KEYS[4]: run_id,
        DEPLOY_LABEL_KEYS[5]: role,
        DEPLOY_LABEL_KEYS[6]: name,
        DEPLOY_LABEL_KEYS[7]: image,
        DEPLOY_LABEL_KEYS[8]: "pre-journal",
    }


def deployment_label_arguments(name, image, expected_sha, run_id, role):
    labels = deployment_labels(name, image, expected_sha, run_id, role)
    arguments = []
    for key in DEPLOY_LABEL_KEYS:
        arguments.extend(("--label", "{0}={1}".format(key, labels[key])))
    return arguments


def _restore_volume_identity(payload):
    if not isinstance(payload, dict):
        raise DeployGuardError("restore volume inspect is invalid")
    name = payload.get("Name")
    labels = payload.get("Labels")
    if (
        type(name) is not str
        or RESTORE_VOLUME_NAME.fullmatch(name) is None
        or not isinstance(labels, dict)
        or set(labels) != set(DEPLOY_LABEL_KEYS)
    ):
        raise DeployGuardError("restore volume lifecycle identity is invalid")
    lifecycle = _deployment_label_values(labels, "restore volume")
    if lifecycle is None or lifecycle[DEPLOY_LABEL_KEYS[5]] != RESTORE_VOLUME_ROLE:
        raise DeployGuardError("restore volume lifecycle role is invalid")
    run_id = lifecycle[DEPLOY_LABEL_KEYS[4]]
    image_id = lifecycle[DEPLOY_LABEL_KEYS[7]]
    expected_sha = lifecycle[DEPLOY_LABEL_KEYS[3]]
    expected_labels = deployment_labels(
        name,
        image_id,
        expected_sha,
        run_id,
        RESTORE_VOLUME_ROLE,
    )
    if not exact_json(labels, expected_labels):
        raise DeployGuardError("restore volume labels are not exact")
    options = payload.get("Options")
    if options is None:
        options = {}
    if (
        payload.get("Driver") != "local"
        or payload.get("Scope") != "local"
        or not isinstance(options, dict)
        or options
    ):
        raise DeployGuardError("restore volume driver or options are unsafe")
    mountpoint = payload.get("Mountpoint")
    if (
        type(mountpoint) is not str
        or not mountpoint.startswith("/")
        or any(character in mountpoint for character in "\0\n\r")
    ):
        raise DeployGuardError("restore volume mountpoint is invalid")
    status = payload.get("Status")
    if status not in (None, {}):
        raise DeployGuardError("restore volume has an unexpected external status")
    created_at = payload.get("CreatedAt")
    if (
        type(created_at) is not str
        or not created_at
        or len(created_at.encode("utf-8")) > 128
        or any(character in created_at for character in "\0\n\r")
    ):
        raise DeployGuardError("restore volume creation identity is invalid")
    return {
        "name": name,
        "created_at": created_at,
        "driver": "local",
        "scope": "local",
        "labels": {key: labels[key] for key in DEPLOY_LABEL_KEYS},
        "options": {},
    }


def validate_restore_volume_inspect(
    payload,
    expected_name=None,
    expected_main_sha=None,
    run_id=None,
    database_probe_image_id=None,
):
    identity = _restore_volume_identity(payload)
    labels = identity["labels"]
    expected = {
        "name": expected_name,
        DEPLOY_LABEL_KEYS[3]: expected_main_sha,
        DEPLOY_LABEL_KEYS[4]: run_id,
        DEPLOY_LABEL_KEYS[7]: database_probe_image_id,
    }
    observed = {
        "name": identity["name"],
        DEPLOY_LABEL_KEYS[3]: labels[DEPLOY_LABEL_KEYS[3]],
        DEPLOY_LABEL_KEYS[4]: labels[DEPLOY_LABEL_KEYS[4]],
        DEPLOY_LABEL_KEYS[7]: labels[DEPLOY_LABEL_KEYS[7]],
    }
    for key, value in expected.items():
        if value is not None and observed[key] != value:
            raise DeployGuardError("restore volume differs from the exact execution")
    return identity


def restore_volume_identity_sha256(identity):
    if not isinstance(identity, dict):
        raise DeployGuardError("restore volume identity is invalid")
    expected = _canonical_json_key(identity)
    return hashlib.sha256(expected.encode("utf-8")).hexdigest()


def plan_restore_volume_cleanup(inspects):
    if not isinstance(inspects, list):
        raise DeployGuardError("restore volume inspect list is invalid")
    records = []
    names = set()
    for payload in inspects:
        identity = validate_restore_volume_inspect(payload)
        name = identity["name"]
        if name in names:
            raise DeployGuardError("restore volume inspect list contains duplicates")
        names.add(name)
        labels = identity["labels"]
        records.append(
            (
                name,
                restore_volume_identity_sha256(identity),
                labels[DEPLOY_LABEL_KEYS[3]],
                labels[DEPLOY_LABEL_KEYS[4]],
                labels[DEPLOY_LABEL_KEYS[7]],
            )
        )
    result = [RESTORE_VOLUME_CLEANUP_PLAN_VERSION]
    for name, digest, revision, run_id, image_id in sorted(records):
        result.extend(
            ("remove_restore_volume", name, digest, revision, run_id, image_id)
        )
    return result


def _deployment_label_values(labels, label):
    if not isinstance(labels, dict) or any(
        type(key) is not str or type(value) is not str
        for key, value in labels.items()
    ):
        raise DeployGuardError("{0} labels are invalid".format(label))
    present = [key in labels for key in DEPLOY_LABEL_KEYS]
    if any(present) and not all(present):
        raise DeployGuardError("{0} lifecycle labels are incomplete".format(label))
    if not all(present):
        return None
    return {key: labels[key] for key in DEPLOY_LABEL_KEYS}


def _validate_deployment_label_overlay(
    image_labels,
    container_labels,
    image_id,
    *,
    label,
    expected_sha=None,
    expected_role="candidate",
    current_name=None,
    allow_legacy=False,
):
    if image_labels is None:
        image_labels = {}
    if container_labels is None:
        container_labels = {}
    if not isinstance(image_labels, dict) or any(
        key in image_labels for key in DEPLOY_LABEL_KEYS
    ):
        raise DeployGuardError("{0} image lifecycle labels are invalid".format(label))
    values = _deployment_label_values(container_labels, label)
    if values is None:
        if allow_legacy and exact_json(container_labels, image_labels):
            return
        raise DeployGuardError("{0} lifecycle labels are missing".format(label))
    role = values[DEPLOY_LABEL_KEYS[5]]
    if role not in DEPLOY_ROLES:
        raise DeployGuardError("managed orphan lifecycle role is not a container role")
    revision = values[DEPLOY_LABEL_KEYS[3]]
    run_id = values[DEPLOY_LABEL_KEYS[4]]
    original_name = values[DEPLOY_LABEL_KEYS[6]]
    if role != expected_role:
        raise DeployGuardError("{0} lifecycle role is invalid".format(label))
    if expected_sha is not None and revision != expected_sha:
        raise DeployGuardError("{0} lifecycle revision is invalid".format(label))
    expected = deployment_labels(original_name, image_id, revision, run_id, role)
    if current_name is not None and current_name not in (
        original_name,
        PINNED_SPEC["container_name"],
    ) and BACKUP_CONTAINER_NAME.fullmatch(current_name) is None:
        raise DeployGuardError("{0} lifecycle current name is invalid".format(label))
    combined = dict(image_labels)
    combined.update(expected)
    if not exact_json(container_labels, combined):
        raise DeployGuardError("{0} lifecycle label overlay is invalid".format(label))


def create_arguments(
    spec,
    name,
    image,
    env_file,
    expected_sha=None,
    one_shot_command=None,
    *,
    image_reference=None,
    env_source=None,
    run_id=None,
    role=None,
):
    require_pinned_spec(spec)
    if not isinstance(name, str) or CONTAINER_NAME.fullmatch(name) is None:
        raise DeployGuardError("container name is invalid")
    if name != spec["container_name"] and not name.startswith(
        spec["container_name"] + "-"
    ):
        raise DeployGuardError("container name differs from the pinned spec identity")
    if not isinstance(image, str) or IMAGE_ID.fullmatch(image) is None:
        raise DeployGuardError("container image must be an immutable full image ID")
    if not isinstance(env_source, (str, os.PathLike)) or os.fspath(
        env_source
    ) != spec["secret_env_file"]:
        raise DeployGuardError("env source differs from the pinned spec identity")
    if not isinstance(env_file, (str, os.PathLike)) or not os.fspath(env_file):
        raise DeployGuardError("owner-only env snapshot path is required")
    if os.fspath(env_file) == os.fspath(env_source):
        raise DeployGuardError("container creation must use an atomic env snapshot")
    if not isinstance(expected_sha, str) or REVISION.fullmatch(expected_sha) is None:
        raise DeployGuardError("expected revision must be a lowercase full Git SHA")
    expected_reference = "{0}:main-{1}".format(
        spec["image_repository"], expected_sha
    )
    if image_reference != expected_reference:
        raise DeployGuardError("candidate image reference differs from the pinned spec")
    if role == "database-schema":
        raise DeployGuardError(
            "database schema probe requires the separately pinned PostgreSQL client"
        )
    if role == "candidate":
        if one_shot_command is not None:
            raise DeployGuardError("candidate lifecycle role forbids a one-shot command")
    elif role in SUPERVISED_SERVICE_ROLES:
        expected_command = DEPLOY_ROLE_COMMANDS[role][1]
        if tuple(one_shot_command or ()) != expected_command:
            raise DeployGuardError("supervised service command differs from its lifecycle role")
    else:
        expected_command = DEPLOY_ROLE_COMMANDS.get(role)
        if expected_command is None or tuple(one_shot_command or ()) != expected_command[1]:
            raise DeployGuardError("one-shot command differs from its lifecycle role")
    args = ["container", "create", "--name", name, "--env-file", str(env_file)]
    if role in HARDENED_PROBE_ROLES:
        if role in INTERACTIVE_ROLES:
            args.append("--interactive")
        args.extend(
            (
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
            )
        )
        expected_tmpfs = (
            DATABASE_PROBE_TMPFS
            if role == "database-schema"
            else SUPERVISED_SERVICE_TMPFS
            if role in SUPERVISED_SERVICE_ROLES
            else SCHEMA_PROBE_TMPFS
        )
        for destination, options in sorted(expected_tmpfs.items()):
            args.extend(("--tmpfs", destination + ":" + options))
    constrained_resources = REFERENCE_ROLE_RESOURCES.get(role)
    if role in SUPERVISED_SERVICE_ROLES:
        if constrained_resources is None:
            raise AssertionError("supervised service resource contract is missing")
        user, stop_timeout, memory_limit, pids_limit = constrained_resources
        args.extend(
            (
                "--user",
                user,
                "--stop-timeout",
                str(stop_timeout),
                "--memory",
                str(memory_limit),
                "--memory-swap",
                str(memory_limit),
                "--pids-limit",
                str(pids_limit),
            )
        )
    if role in LONG_RUNNING_ROLES:
        args.extend(("--restart", spec["restart_policy"]))
        if role == "candidate":
            for published_port in spec["published_ports"]:
                args.extend(("--publish", published_port))
    for host in spec["extra_hosts"]:
        args.extend(("--add-host", host))
    args.extend(deployment_label_arguments(name, image, expected_sha, run_id, role))
    args.append(image)
    if one_shot_command is not None:
        if not one_shot_command or any(
            not isinstance(item, str) or not item or "\0" in item
            for item in one_shot_command
        ):
            raise DeployGuardError("one-shot command is empty or invalid")
        args.extend(one_shot_command)
    return args


def write_nul_records(path, records):
    if not isinstance(records, list) or not records:
        raise DeployGuardError("NUL output records are empty or invalid")
    if any(not isinstance(item, str) or not item or "\0" in item for item in records):
        raise DeployGuardError("NUL output contains an invalid record")
    try:
        payload = b"\0".join(item.encode("utf-8") for item in records) + b"\0"
    except UnicodeError as exc:
        raise DeployGuardError("NUL output is not UTF-8 encodable") from exc
    write_exclusive_bytes(path, payload)


def write_arguments(path, args):
    write_nul_records(path, args)


def emit_migration_probe(path):
    write_exclusive_bytes(path, MIGRATION_PROBE_SOURCE.encode("utf-8"))


def _expand_appended_migrations(old_manifest, candidate_manifest):
    validate_migration_manifest(old_manifest)
    validate_migration_manifest(candidate_manifest)
    if len(old_manifest["heads"]) != 1 or len(candidate_manifest["heads"]) != 1:
        raise DeployGuardError("expand manifests must each have exactly one head")
    old_migrations = old_manifest["migrations"]
    candidate_migrations = candidate_manifest["migrations"]
    appended = candidate_migrations[len(old_migrations) :]
    if (
        not appended
        or len(appended) > MAX_EXPAND_MIGRATIONS
        or not exact_json(candidate_migrations[: len(old_migrations)], old_migrations)
    ):
        raise DeployGuardError(
            "candidate must append a bounded migration chain without rewriting history"
        )
    expected_down_revision = old_manifest["heads"][0]
    for migration in appended:
        if migration["down_revision"] != expected_down_revision:
            raise DeployGuardError(
                "candidate migration chain is not one linear append from the old head"
            )
        expected_down_revision = migration["revision"]
    if candidate_manifest["heads"] != [expected_down_revision]:
        raise DeployGuardError("candidate final appended migration is not its head")
    return appended


def _read_exact_expand_migration_source_file(path):
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
    try:
        descriptor = os.open(os.fspath(path), flags)
    except OSError as exc:
        raise DeployGuardError("cannot open exact-source migration") from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.geteuid()
            or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) & 0o022
            or before.st_size <= 0
            or before.st_size > MAX_EXPAND_MIGRATION_SOURCE_BYTES
        ):
            raise DeployGuardError("exact-source migration identity is invalid")
        chunks = []
        total = 0
        while True:
            chunk = os.read(descriptor, 65536)
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        after = os.fstat(descriptor)
        if (
            _owner_only_file_identity(before) != _owner_only_file_identity(after)
            or total != before.st_size
        ):
            raise DeployGuardError("exact-source migration changed while it was read")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def extract_expand_migration_source(
    old_manifest,
    candidate_manifest,
    source_root,
    output,
):
    appended = _expand_appended_migrations(old_manifest, candidate_manifest)
    targets = {item["revision"]: item for item in appended}
    migration_root = Path(source_root) / "backend" / "app" / "db" / "migrations" / "versions"
    try:
        metadata = os.lstat(migration_root)
    except OSError as exc:
        raise DeployGuardError("cannot inspect exact-source migration directory") from exc
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) & 0o022
    ):
        raise DeployGuardError("exact-source migration directory identity is invalid")
    matches = {}
    try:
        paths = sorted(migration_root.glob("*.py"))
    except OSError as exc:
        raise DeployGuardError("cannot enumerate exact-source migrations") from exc
    for path in paths:
        source = _read_exact_expand_migration_source_file(path)
        try:
            tree = ast.parse(source.decode("utf-8"), filename=str(path))
        except (UnicodeError, SyntaxError) as exc:
            raise DeployGuardError("exact-source migration is invalid Python") from exc
        revisions = []
        for node in tree.body:
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "revision"
            ):
                if not isinstance(node.value, ast.Constant) or type(node.value.value) is not str:
                    raise DeployGuardError("exact-source migration revision is dynamic")
                revisions.append(node.value.value)
        if len(revisions) == 1 and revisions[0] in targets:
            revision = revisions[0]
            if revision in matches:
                raise DeployGuardError(
                    "exact-source candidate migration is duplicated"
                )
            matches[revision] = source
    records = []
    for target in appended:
        source = matches.get(target["revision"])
        if source is None or hashlib.sha256(source).hexdigest() != target["sha256"]:
            raise DeployGuardError(
                "exact-source candidate migration is missing or changed"
            )
        record = {
            "revision": target["revision"],
            "sha256": target["sha256"],
            "source_base64": base64.b64encode(source).decode("ascii"),
        }
        if tuple(record) != EXPAND_MIGRATION_SOURCE_ITEM_KEYS:
            raise AssertionError("expand migration source record key order changed")
        records.append(record)
    bundle = {
        "schema_version": EXPAND_MIGRATION_SOURCE_BUNDLE_SCHEMA_VERSION,
        "migrations": records,
    }
    if tuple(bundle) != EXPAND_MIGRATION_SOURCE_BUNDLE_KEYS:
        raise AssertionError("expand migration source bundle key order changed")
    write_exclusive_bytes(
        output,
        (json.dumps(bundle, ensure_ascii=True, separators=(",", ":")) + "\n").encode(
            "ascii"
        ),
    )


def candidate_manifest_sha256(candidate_manifest):
    validate_migration_manifest(candidate_manifest)
    return hashlib.sha256(
        _canonical_json_key(candidate_manifest).encode("utf-8")
    ).hexdigest()


def _manifest_table_identities(candidate_manifest):
    validate_migration_manifest(candidate_manifest)
    identities = []
    for table in candidate_manifest["model_schema"]:
        schema = table["schema"] or "public"
        if schema != "public":
            raise DeployGuardError(
                "production reference catalog may manage only the public schema"
            )
        if table["name"] in DATABASE_SCHEMA_LEGACY_PUBLIC_TABLES:
            raise DeployGuardError(
                "candidate model table collides with the legacy allowlist"
            )
        identities.append(schema + "." + table["name"])
    if identities != sorted(identities) or len(identities) != len(set(identities)):
        raise DeployGuardError("candidate model table identities are invalid")
    return identities


def render_reference_schema_materializer(candidate_manifest):
    _manifest_table_identities(candidate_manifest)
    replacements = {
        "__EXPECTED_MANIFEST_JSON_LITERAL__": repr(
            _canonical_json_key(candidate_manifest)
        ),
    }
    if any(
        REFERENCE_SCHEMA_MATERIALIZER_SOURCE.count(marker) != 1
        for marker in replacements
    ):
        raise DeployGuardError("reference schema materializer template is invalid")
    source = REFERENCE_SCHEMA_MATERIALIZER_SOURCE
    for marker, replacement in replacements.items():
        source = source.replace(marker, replacement)
    if any(marker in source for marker in replacements):
        raise DeployGuardError("reference schema materializer is incomplete")
    compile(source, "REFERENCE_SCHEMA_MATERIALIZER.py", "exec")
    return source


def emit_reference_schema_materializer(path, candidate_manifest):
    write_exclusive_bytes(
        path,
        render_reference_schema_materializer(candidate_manifest).encode("utf-8"),
    )


def _render_physical_schema_catalog(candidate_manifest):
    marker = "__CANDIDATE_MANIFEST_SHA256_SQL__"
    if PHYSICAL_SCHEMA_CATALOG_SQL.count(marker) != 1:
        raise DeployGuardError("physical schema catalog template is invalid")
    source = PHYSICAL_SCHEMA_CATALOG_SQL.replace(
        marker,
        "'" + candidate_manifest_sha256(candidate_manifest) + "'",
    )
    if "__PHYSICAL_SCHEMA_" in source or marker in source:
        raise DeployGuardError("physical schema catalog template is incomplete")
    return source


def _validate_read_only_schema_probe(source, label):
    if (
        source.count("BEGIN TRANSACTION ISOLATION LEVEL SERIALIZABLE READ ONLY;")
        != 1
        or source.count("ROLLBACK;") != 1
        or re.search(
            r"(?im)^\s*(?:\\i(?:nclude)?|COPY|CREATE|ALTER|DROP|INSERT|UPDATE|DELETE|"
            r"TRUNCATE|GRANT|REVOKE|CALL|DO)\b",
            source,
        )
    ):
        raise DeployGuardError("{0} contains a write capability".format(label))
    return source


def render_reference_catalog_probe(candidate_manifest):
    table_identities = _manifest_table_identities(candidate_manifest)
    table_json = _canonical_json_key(table_identities)
    if "$xjie_table_names$" in table_json:
        raise DeployGuardError("reference table identities are not safely encodable")
    replacements = {
        "__PHYSICAL_SCHEMA_CATALOG_SQL__": _render_physical_schema_catalog(
            candidate_manifest
        ),
        "__EXPECTED_TABLE_IDENTITIES_SQL__": (
            "$xjie_table_names$"
            + table_json
            + "$xjie_table_names$::pg_catalog.jsonb"
        ),
    }
    if any(
        REFERENCE_CATALOG_PROBE_SQL.count(marker) != 1 for marker in replacements
    ):
        raise DeployGuardError("reference catalog probe template is invalid")
    source = REFERENCE_CATALOG_PROBE_SQL
    for marker, replacement in replacements.items():
        source = source.replace(marker, replacement)
    if any(marker in source for marker in replacements):
        raise DeployGuardError("reference catalog probe is incomplete")
    return _validate_read_only_schema_probe(source, "reference catalog probe")


def emit_reference_catalog_probe(path, candidate_manifest):
    write_exclusive_bytes(
        path,
        render_reference_catalog_probe(candidate_manifest).encode("utf-8"),
    )


def render_database_schema_probe(candidate_manifest, reference_catalog):
    validate_reference_catalog(candidate_manifest, reference_catalog)
    catalog_json = _canonical_json_key(reference_catalog)
    if "$xjie_reference_catalog$" in catalog_json:
        raise DeployGuardError("reference catalog is not safely encodable")
    catalog_digest = reference_catalog_sha256(reference_catalog)
    replacements = {
        "__PHYSICAL_SCHEMA_CATALOG_SQL__": _render_physical_schema_catalog(
            candidate_manifest
        ),
        "__EXPECTED_REFERENCE_CATALOG_SQL__": (
            "$xjie_reference_catalog$"
            + catalog_json
            + "$xjie_reference_catalog$::pg_catalog.jsonb"
        ),
        "__CANDIDATE_MANIFEST_SHA256_SQL__": (
            "'" + candidate_manifest_sha256(candidate_manifest) + "'"
        ),
        "__REFERENCE_CATALOG_SHA256_SQL__": "'" + catalog_digest + "'",
        "__EXPECTED_ALEMBIC_HEAD_SQL__": (
            "'" + candidate_manifest["heads"][0] + "'"
        ),
    }
    expected_marker_counts = {
        "__PHYSICAL_SCHEMA_CATALOG_SQL__": 1,
        "__EXPECTED_REFERENCE_CATALOG_SQL__": 1,
        "__CANDIDATE_MANIFEST_SHA256_SQL__": 1,
        "__REFERENCE_CATALOG_SHA256_SQL__": 2,
        "__EXPECTED_ALEMBIC_HEAD_SQL__": 1,
    }
    if any(
        DATABASE_SCHEMA_PROBE_SQL.count(marker) != expected_marker_counts[marker]
        for marker in replacements
    ):
        raise DeployGuardError("database schema probe template is invalid")
    source = DATABASE_SCHEMA_PROBE_SQL
    for marker, replacement in replacements.items():
        source = source.replace(marker, replacement)
    if any(marker in source for marker in replacements):
        raise DeployGuardError("database schema probe is incomplete")
    return _validate_read_only_schema_probe(source, "database schema probe")


def emit_database_schema_probe(path, candidate_manifest, reference_catalog):
    write_exclusive_bytes(
        path,
        render_database_schema_probe(
            candidate_manifest,
            reference_catalog,
        ).encode("utf-8"),
    )


def _canonical_json_key(value):
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )


def _require_exact_keys(value, keys, label):
    if not isinstance(value, dict) or tuple(value) != keys:
        raise DeployGuardError("{0} keys/order are invalid".format(label))


def _require_optional_string(value, label):
    if value is not None and (type(value) is not str or not value):
        raise DeployGuardError("{0} is invalid".format(label))


def _require_string_list(value, label, allow_empty=True):
    if not isinstance(value, list) or (
        not allow_empty and not value
    ) or any(type(item) is not str or not item for item in value):
        raise DeployGuardError("{0} is invalid".format(label))
    if len(value) != len(set(value)):
        raise DeployGuardError("{0} contains duplicates".format(label))


def _require_pure_json(value, label):
    if value is None or type(value) in (bool, int, str):
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise DeployGuardError("{0} contains a non-finite number".format(label))
        return
    if isinstance(value, list):
        for item in value:
            _require_pure_json(item, label)
        return
    if isinstance(value, dict):
        if any(type(key) is not str for key in value):
            raise DeployGuardError("{0} contains a non-string key".format(label))
        for key in value:
            _require_pure_json(value[key], label)
        return
    raise DeployGuardError("{0} is not pure JSON".format(label))


def _validate_model_default(value, label):
    if value is None:
        return
    _require_exact_keys(value, MODEL_DEFAULT_KEYS, label)
    if value["kind"] not in ("callable", "scalar", "sql"):
        raise DeployGuardError("{0} kind is invalid".format(label))
    _require_pure_json(value["value"], label)
    if value["kind"] in ("callable", "sql") and (
        type(value["value"]) is not str or not value["value"]
    ):
        raise DeployGuardError("{0} value is invalid".format(label))


def _validate_model_column(value, label):
    _require_exact_keys(value, MODEL_COLUMN_KEYS, label)
    if type(value["name"]) is not str or not value["name"]:
        raise DeployGuardError("{0} name is invalid".format(label))
    column_type = value["type"]
    _require_exact_keys(column_type, MODEL_TYPE_KEYS, label + " type")
    for key in ("class", "sql"):
        if type(column_type[key]) is not str or not column_type[key]:
            raise DeployGuardError("{0} type {1} is invalid".format(label, key))
    _require_pure_json(column_type["cache_key"], label + " type cache key")
    if not isinstance(column_type["attributes"], dict) or list(
        column_type["attributes"]
    ) != sorted(column_type["attributes"]):
        raise DeployGuardError("{0} type attributes are invalid".format(label))
    _require_pure_json(column_type["attributes"], label + " type attributes")
    for key in ("nullable", "primary_key"):
        if type(value[key]) is not bool:
            raise DeployGuardError("{0} {1} is invalid".format(label, key))
    _require_pure_json(value["autoincrement"], label + " autoincrement")
    for key in ("default", "server_default", "onupdate", "server_onupdate"):
        _validate_model_default(value[key], label + " " + key)
    identity = value["identity"]
    if identity is not None:
        _require_exact_keys(identity, MODEL_IDENTITY_KEYS, label + " identity")
        _require_pure_json(identity, label + " identity")
    computed = value["computed"]
    if computed is not None:
        _require_exact_keys(computed, MODEL_COMPUTED_KEYS, label + " computed")
        if type(computed["sql"]) is not str or not computed["sql"]:
            raise DeployGuardError("{0} computed SQL is invalid".format(label))
        if computed["persisted"] is not None and type(computed["persisted"]) is not bool:
            raise DeployGuardError("{0} computed persistence is invalid".format(label))
    _require_optional_string(value["comment"], label + " comment")


def _validate_model_constraint(value, label):
    _require_exact_keys(value, MODEL_CONSTRAINT_KEYS, label)
    if value["kind"] not in ("primary_key", "unique", "foreign_key", "check"):
        raise DeployGuardError("{0} kind is invalid".format(label))
    _require_optional_string(value["name"], label + " name")
    _require_string_list(value["columns"], label + " columns")
    _require_string_list(value["references"], label + " references")
    if not isinstance(value["options"], dict):
        raise DeployGuardError("{0} options are invalid".format(label))
    _require_pure_json(value["options"], label + " options")
    if value["kind"] == "foreign_key":
        if not value["columns"] or len(value["references"]) != len(value["columns"]):
            raise DeployGuardError("{0} foreign key shape is invalid".format(label))
    elif value["references"]:
        raise DeployGuardError("{0} has unexpected references".format(label))
    if value["kind"] == "check":
        if type(value["expression"]) is not str or not value["expression"]:
            raise DeployGuardError("{0} check expression is invalid".format(label))
    elif value["expression"] is not None:
        raise DeployGuardError("{0} has an unexpected expression".format(label))


def _validate_model_index(value, label):
    _require_exact_keys(value, MODEL_INDEX_KEYS, label)
    _require_optional_string(value["name"], label + " name")
    if type(value["unique"]) is not bool:
        raise DeployGuardError("{0} uniqueness is invalid".format(label))
    _require_string_list(value["expressions"], label + " expressions", allow_empty=False)
    if not isinstance(value["options"], dict):
        raise DeployGuardError("{0} options are invalid".format(label))
    _require_pure_json(value["options"], label + " options")


def _validate_model_schema(value):
    if not isinstance(value, list) or not value:
        raise DeployGuardError("migration probe model schema is empty or invalid")
    table_identities = []
    for table_number, table in enumerate(value):
        label = "migration probe model table {0}".format(table_number)
        _require_exact_keys(table, MODEL_TABLE_KEYS, label)
        if type(table["name"]) is not str or not table["name"]:
            raise DeployGuardError("{0} name is invalid".format(label))
        _require_optional_string(table["schema"], label + " schema")
        identity = (table["schema"] or "", table["name"])
        table_identities.append(identity)
        columns = table["columns"]
        if not isinstance(columns, list) or not columns:
            raise DeployGuardError("{0} columns are empty or invalid".format(label))
        for column_number, column in enumerate(columns):
            _validate_model_column(
                column,
                "{0} column {1}".format(label, column_number),
            )
        column_names = [column["name"] for column in columns]
        if column_names != sorted(column_names) or len(column_names) != len(set(column_names)):
            raise DeployGuardError("{0} columns are not uniquely ordered".format(label))
        for key, validator in (
            ("constraints", _validate_model_constraint),
            ("indexes", _validate_model_index),
        ):
            items = table[key]
            if not isinstance(items, list):
                raise DeployGuardError("{0} {1} are invalid".format(label, key))
            for item_number, item in enumerate(items):
                validator(item, "{0} {1} {2}".format(label, key, item_number))
            canonical = [_canonical_json_key(item) for item in items]
            if canonical != sorted(canonical) or len(canonical) != len(set(canonical)):
                raise DeployGuardError("{0} {1} are not uniquely ordered".format(label, key))
    if table_identities != sorted(table_identities) or len(table_identities) != len(
        set(table_identities)
    ):
        raise DeployGuardError("migration probe model tables are not uniquely ordered")


def _ordered_migrations(value):
    if not isinstance(value, list) or not value:
        raise DeployGuardError("migration probe history is empty or invalid")
    by_revision = {}
    for entry_number, entry in enumerate(value):
        label = "migration probe entry {0}".format(entry_number)
        _require_exact_keys(entry, MIGRATION_ENTRY_KEYS, label)
        revision = entry["revision"]
        down_revision = entry["down_revision"]
        if type(revision) is not str or MIGRATION_REVISION.fullmatch(revision) is None:
            raise DeployGuardError("{0} revision is invalid".format(label))
        if down_revision is not None and (
            type(down_revision) is not str
            or MIGRATION_REVISION.fullmatch(down_revision) is None
        ):
            raise DeployGuardError("{0} down revision is invalid".format(label))
        if type(entry["sha256"]) is not str or SHA256_DIGEST.fullmatch(
            entry["sha256"]
        ) is None:
            raise DeployGuardError("{0} digest is invalid".format(label))
        if revision in by_revision:
            raise DeployGuardError("migration probe revisions are not unique")
        by_revision[revision] = entry
    roots = [entry for entry in value if entry["down_revision"] is None]
    if len(roots) != 1:
        raise DeployGuardError("migration probe history must have exactly one root")
    children = {revision: [] for revision in by_revision}
    for entry in value:
        down_revision = entry["down_revision"]
        if down_revision is None:
            continue
        if down_revision not in by_revision:
            raise DeployGuardError("migration probe down revision is missing")
        children[down_revision].append(entry["revision"])
    if any(len(revisions) > 1 for revisions in children.values()):
        raise DeployGuardError("migration probe history is branched")
    ordered = []
    seen = set()
    revision = roots[0]["revision"]
    while True:
        if revision in seen:
            raise DeployGuardError("migration probe history contains a cycle")
        seen.add(revision)
        ordered.append(by_revision[revision])
        next_revisions = children[revision]
        if not next_revisions:
            break
        revision = next_revisions[0]
    if len(ordered) != len(value):
        raise DeployGuardError("migration probe history is disconnected")
    if [entry["revision"] for entry in value] != [
        entry["revision"] for entry in ordered
    ]:
        raise DeployGuardError("migration probe history is not linearly ordered")
    return ordered


def validate_migration_manifest(value):
    _require_exact_keys(value, MIGRATION_PROBE_KEYS, "migration probe manifest")
    if (
        type(value["schema_version"]) is not int
        or value["schema_version"] != MIGRATION_PROBE_SCHEMA_VERSION
    ):
        raise DeployGuardError("migration probe schema version is invalid")
    ordered = _ordered_migrations(value["migrations"])
    _require_string_list(value["heads"], "migration probe heads", allow_empty=False)
    expected_heads = [ordered[-1]["revision"]]
    if value["heads"] != expected_heads:
        raise DeployGuardError("migration probe must expose exactly its linear head")
    _validate_model_schema(value["model_schema"])
    return value


def _require_json_key_set(value, keys, label):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise DeployGuardError("{0} keys are invalid".format(label))


def _require_sorted_strings(value, label, allow_empty=True, unique=True):
    if (
        not isinstance(value, list)
        or (not allow_empty and not value)
        or any(type(item) is not str or not item for item in value)
    ):
        raise DeployGuardError("{0} is invalid".format(label))
    if value != sorted(value) or (unique and len(value) != len(set(value))):
        raise DeployGuardError("{0} is not deterministically ordered".format(label))


def _validate_physical_type(value, label):
    _require_json_key_set(value, PHYSICAL_TYPE_KEYS, label)
    for key in ("schema", "name", "formatted", "kind", "category"):
        if type(value[key]) is not str or not value[key]:
            raise DeployGuardError("{0} {1} is invalid".format(label, key))
    if value["kind"] not in ("b", "e"):
        raise DeployGuardError("{0} uses an unsupported PostgreSQL type".format(label))
    if type(value["dimensions"]) is not int or value["dimensions"] < 0:
        raise DeployGuardError("{0} dimensions are invalid".format(label))
    enum_labels = value["enum_labels"]
    array_item = value["array_item"]
    if value["kind"] == "e":
        if value["schema"] != "public":
            raise DeployGuardError("{0} enum schema is unsupported".format(label))
        _require_string_list(enum_labels, label + " enum labels", allow_empty=False)
    elif enum_labels is not None:
        raise DeployGuardError("{0} has unexpected enum labels".format(label))
    if value["category"] == "A":
        if array_item is None:
            raise DeployGuardError("{0} ARRAY item is missing".format(label))
        _validate_physical_type(array_item, label + " ARRAY item")
        if array_item["array_item"] is not None or array_item["dimensions"] != 0:
            raise DeployGuardError("{0} nested ARRAY identity is unsupported".format(label))
        if value["schema"] == "public":
            if array_item["schema"] != "public" or array_item["kind"] != "e":
                raise DeployGuardError(
                    "{0} public ARRAY is not backed by a public enum".format(label)
                )
        elif value["schema"] != "pg_catalog":
            raise DeployGuardError("{0} ARRAY schema is unsupported".format(label))
    elif array_item is not None:
        raise DeployGuardError("{0} has an unexpected ARRAY item".format(label))
    elif value["kind"] != "e" and value["schema"] != "pg_catalog":
        raise DeployGuardError("{0} base type schema is unsupported".format(label))
    return value


def _validate_physical_sequence(value, label):
    _require_json_key_set(value, PHYSICAL_SEQUENCE_KEYS, label)
    for key in ("schema", "name", "data_type"):
        if type(value[key]) is not str or not value[key]:
            raise DeployGuardError("{0} {1} is invalid".format(label, key))
    if value["schema"] != "public":
        raise DeployGuardError("{0} schema is unsupported".format(label))
    for key in ("start", "increment", "minimum", "maximum", "cache"):
        if type(value[key]) is not int:
            raise DeployGuardError("{0} {1} is invalid".format(label, key))
    if value["increment"] == 0 or value["cache"] <= 0:
        raise DeployGuardError("{0} numeric identity is invalid".format(label))
    if type(value["cycle"]) is not bool:
        raise DeployGuardError("{0} cycle flag is invalid".format(label))
    owner = value["owned_by"]
    if owner is None:
        raise DeployGuardError("{0} is not owned by a managed column".format(label))
    _require_json_key_set(owner, PHYSICAL_SEQUENCE_OWNER_KEYS, label + " owner")
    for key in ("schema", "table", "column", "dependency"):
        if type(owner[key]) is not str or not owner[key]:
            raise DeployGuardError("{0} owner {1} is invalid".format(label, key))
    if owner["schema"] != "public" or owner["dependency"] not in ("a", "i"):
        raise DeployGuardError("{0} owner identity is unsupported".format(label))
    return value


def _validate_physical_column(value, label):
    _require_json_key_set(value, PHYSICAL_COLUMN_KEYS, label)
    if type(value["position"]) is not int or value["position"] <= 0:
        raise DeployGuardError("{0} position is invalid".format(label))
    if type(value["name"]) is not str or not value["name"]:
        raise DeployGuardError("{0} name is invalid".format(label))
    _validate_physical_type(value["type"], label + " type")
    if type(value["nullable"]) is not bool:
        raise DeployGuardError("{0} nullability is invalid".format(label))
    if value["default"] is not None and (
        type(value["default"]) is not str or not value["default"]
    ):
        raise DeployGuardError("{0} default is invalid".format(label))
    if value["identity"] not in ("", "a", "d"):
        raise DeployGuardError("{0} identity mode is invalid".format(label))
    if value["generated"] not in ("", "s"):
        raise DeployGuardError("{0} generated mode is invalid".format(label))
    collation = value["collation"]
    if collation is not None:
        _require_json_key_set(
            collation,
            PHYSICAL_COLLATION_KEYS,
            label + " collation",
        )
        if not exact_json(
            collation,
            {"schema": "pg_catalog", "name": "default"},
        ):
            raise DeployGuardError("{0} collation is unsupported".format(label))
    if type(value["compression"]) is not str or value["compression"] not in (
        "",
        "p",
        "l",
    ):
        raise DeployGuardError("{0} compression is invalid".format(label))
    if type(value["storage"]) is not str or value["storage"] not in (
        "p",
        "e",
        "m",
        "x",
    ):
        raise DeployGuardError("{0} storage is invalid".format(label))
    if value["owned_sequence"] is not None:
        _validate_physical_sequence(value["owned_sequence"], label + " sequence")
    if value["identity"] and value["owned_sequence"] is None:
        raise DeployGuardError("{0} identity sequence is missing".format(label))
    return value


def _require_ordered_string_array(value, label, allow_empty=True):
    if (
        not isinstance(value, list)
        or (not allow_empty and not value)
        or any(type(item) is not str or not item for item in value)
    ):
        raise DeployGuardError("{0} is invalid".format(label))


def _validate_physical_constraint(value, label, column_names):
    _require_json_key_set(value, PHYSICAL_CONSTRAINT_KEYS, label)
    for key in ("name", "type", "definition"):
        if type(value[key]) is not str or not value[key]:
            raise DeployGuardError("{0} {1} is invalid".format(label, key))
    if value["type"] not in ("p", "u", "f", "c"):
        raise DeployGuardError("{0} type is unsupported".format(label))
    _require_ordered_string_array(value["columns"], label + " columns")
    if len(value["columns"]) != len(set(value["columns"])) or any(
        column not in column_names for column in value["columns"]
    ):
        raise DeployGuardError("{0} columns are invalid".format(label))
    if value["type"] in ("p", "u", "f") and not value["columns"]:
        raise DeployGuardError("{0} columns are empty".format(label))
    reference = value["references"]
    if value["type"] == "f":
        if reference is None:
            raise DeployGuardError("{0} reference is missing".format(label))
        _require_json_key_set(reference, PHYSICAL_REFERENCE_KEYS, label + " reference")
        for key in ("schema", "table"):
            if type(reference[key]) is not str or not reference[key]:
                raise DeployGuardError("{0} reference is invalid".format(label))
        _require_ordered_string_array(
            reference["columns"], label + " reference columns", allow_empty=False
        )
        if (
            reference["schema"] != "public"
            or len(reference["columns"]) != len(value["columns"])
        ):
            raise DeployGuardError("{0} reference shape is invalid".format(label))
    elif reference is not None:
        raise DeployGuardError("{0} has an unexpected reference".format(label))
    for key in (
        "deferrable",
        "deferred",
        "validated",
        "no_inherit",
        "nulls_not_distinct",
    ):
        if type(value[key]) is not bool:
            raise DeployGuardError("{0} {1} is invalid".format(label, key))
    return value


def _validate_physical_index(value, label, constraint_names):
    _require_json_key_set(value, PHYSICAL_INDEX_KEYS, label)
    for key in ("name", "method", "definition"):
        if type(value[key]) is not str or not value[key]:
            raise DeployGuardError("{0} {1} is invalid".format(label, key))
    for key in (
        "unique",
        "nulls_not_distinct",
        "clustered",
        "replica_identity",
        "valid",
        "ready",
        "live",
    ):
        if type(value[key]) is not bool:
            raise DeployGuardError("{0} {1} is invalid".format(label, key))
    if not value["valid"] or not value["ready"] or not value["live"]:
        raise DeployGuardError("{0} is not usable".format(label))
    owner = value["constraint"]
    if owner is not None:
        _require_json_key_set(
            owner,
            PHYSICAL_INDEX_CONSTRAINT_KEYS,
            label + " constraint",
        )
        if (
            type(owner["name"]) is not str
            or not owner["name"]
            or owner["name"] not in constraint_names
            or owner["type"] not in ("p", "u", "x")
        ):
            raise DeployGuardError("{0} constraint identity is invalid".format(label))
    _require_ordered_string_array(
        value["expressions"], label + " expressions", allow_empty=False
    )
    _require_ordered_string_array(
        value["include_columns"], label + " include columns"
    )
    _require_sorted_strings(value["options"], label + " options")
    if value["predicate"] is not None and (
        type(value["predicate"]) is not str or not value["predicate"]
    ):
        raise DeployGuardError("{0} predicate is invalid".format(label))
    if value["tablespace"] is not None and (
        type(value["tablespace"]) is not str or not value["tablespace"]
    ):
        raise DeployGuardError("{0} tablespace is invalid".format(label))
    return value


def _validate_physical_table(value, label):
    _require_json_key_set(value, PHYSICAL_TABLE_KEYS, label)
    for key in ("schema", "name", "kind", "persistence", "access_method"):
        if type(value[key]) is not str or not value[key]:
            raise DeployGuardError("{0} {1} is invalid".format(label, key))
    if (
        value["schema"] != "public"
        or value["kind"] != "r"
        or value["persistence"] != "p"
        or value["access_method"] != "heap"
    ):
        raise DeployGuardError("{0} physical table kind is unsupported".format(label))
    for key in ("row_security", "force_row_security"):
        if type(value[key]) is not bool:
            raise DeployGuardError("{0} {1} is invalid".format(label, key))
    if value["replica_identity"] not in ("d", "n", "f", "i"):
        raise DeployGuardError("{0} replica identity is invalid".format(label))
    _require_sorted_strings(value["options"], label + " options")
    columns = value["columns"]
    if not isinstance(columns, list) or not columns:
        raise DeployGuardError("{0} columns are empty or invalid".format(label))
    column_names = []
    for number, column in enumerate(columns, start=1):
        _validate_physical_column(column, "{0} column {1}".format(label, number))
        if column["position"] != number:
            raise DeployGuardError("{0} column positions are not contiguous".format(label))
        column_names.append(column["name"])
    if len(column_names) != len(set(column_names)):
        raise DeployGuardError("{0} column names are duplicated".format(label))
    constraints = value["constraints"]
    if not isinstance(constraints, list):
        raise DeployGuardError("{0} constraints are invalid".format(label))
    constraint_identities = []
    for number, constraint in enumerate(constraints):
        _validate_physical_constraint(
            constraint,
            "{0} constraint {1}".format(label, number),
            set(column_names),
        )
        constraint_identities.append((constraint["type"], constraint["name"]))
    if (
        constraint_identities != sorted(constraint_identities)
        or len(constraint_identities) != len(set(constraint_identities))
        or sum(item["type"] == "p" for item in constraints) != 1
    ):
        raise DeployGuardError("{0} constraints are not exact".format(label))
    indexes = value["indexes"]
    if not isinstance(indexes, list):
        raise DeployGuardError("{0} indexes are invalid".format(label))
    index_names = []
    constraint_names = {item["name"] for item in constraints}
    for number, index in enumerate(indexes):
        _validate_physical_index(
            index,
            "{0} index {1}".format(label, number),
            constraint_names,
        )
        index_names.append(index["name"])
    if index_names != sorted(index_names) or len(index_names) != len(set(index_names)):
        raise DeployGuardError("{0} indexes are not uniquely ordered".format(label))
    return value


def _validate_reference_catalog_shape(value):
    _require_json_key_set(value, PHYSICAL_CATALOG_KEYS, "reference catalog")
    if (
        type(value["schema_version"]) is not int
        or value["schema_version"] != MODEL_CATALOG_SCHEMA_VERSION
    ):
        raise DeployGuardError("reference catalog schema version is invalid")
    if (
        type(value["candidate_manifest_sha256"]) is not str
        or SHA256_DIGEST.fullmatch(value["candidate_manifest_sha256"]) is None
    ):
        raise DeployGuardError("reference catalog manifest digest is invalid")
    if (
        type(value["server_major"]) is not int
        or value["server_major"] != PINNED_POSTGRESQL_MAJOR
    ):
        raise DeployGuardError("reference catalog PostgreSQL version is invalid")
    for key in ("database_encoding", "database_collate", "database_ctype"):
        if type(value[key]) is not str or not value[key]:
            raise DeployGuardError("reference catalog {0} is invalid".format(key))
    if value["database_locale_provider"] not in ("c", "i"):
        raise DeployGuardError("reference catalog locale provider is unsupported")
    for key in (
        "database_collation_version",
        "database_icu_locale",
        "database_icu_rules",
    ):
        if value[key] is not None and type(value[key]) is not str:
            raise DeployGuardError("reference catalog {0} is invalid".format(key))
    if value["standard_conforming_strings"] != "on":
        raise DeployGuardError(
            "reference catalog requires standard_conforming_strings=on"
        )

    tables = value["tables"]
    if not isinstance(tables, list) or not tables:
        raise DeployGuardError("reference catalog tables are empty or invalid")
    table_identities = []
    index_names = []
    table_columns = {}
    for number, table in enumerate(tables):
        _validate_physical_table(table, "reference catalog table {0}".format(number))
        identity = (table["schema"], table["name"])
        table_identities.append(identity)
        table_columns[identity] = {column["name"] for column in table["columns"]}
        index_names.extend(index["name"] for index in table["indexes"])
    if table_identities != sorted(table_identities) or len(table_identities) != len(
        set(table_identities)
    ):
        raise DeployGuardError("reference catalog tables are not uniquely ordered")
    if len(index_names) != len(set(index_names)):
        raise DeployGuardError("reference catalog index names are duplicated")

    sequences = value["sequences"]
    if not isinstance(sequences, list):
        raise DeployGuardError("reference catalog sequences are invalid")
    sequence_identities = []
    sequence_by_owner = {}
    for number, sequence in enumerate(sequences):
        _validate_physical_sequence(
            sequence,
            "reference catalog sequence {0}".format(number),
        )
        identity = (sequence["schema"], sequence["name"])
        sequence_identities.append(identity)
        owner = sequence["owned_by"]
        owner_identity = (owner["schema"], owner["table"], owner["column"])
        if owner_identity in sequence_by_owner:
            raise DeployGuardError("managed column owns more than one sequence")
        sequence_by_owner[owner_identity] = sequence
    if sequence_identities != sorted(sequence_identities) or len(
        sequence_identities
    ) != len(set(sequence_identities)):
        raise DeployGuardError("reference catalog sequences are not uniquely ordered")

    enums = value["enum_types"]
    if not isinstance(enums, list):
        raise DeployGuardError("reference catalog enums are invalid")
    enum_identities = []
    enum_labels = {}
    for number, enum_value in enumerate(enums):
        label = "reference catalog enum {0}".format(number)
        _require_json_key_set(enum_value, PHYSICAL_ENUM_KEYS, label)
        if enum_value["schema"] != "public" or (
            type(enum_value["name"]) is not str or not enum_value["name"]
        ):
            raise DeployGuardError("{0} identity is invalid".format(label))
        _require_string_list(enum_value["labels"], label + " labels", allow_empty=False)
        identity = (enum_value["schema"], enum_value["name"])
        enum_identities.append(identity)
        enum_labels[identity] = enum_value["labels"]
    if enum_identities != sorted(enum_identities) or len(enum_identities) != len(
        set(enum_identities)
    ):
        raise DeployGuardError("reference catalog enums are not uniquely ordered")

    seen_owned_sequences = set()
    for table in tables:
        table_identity = (table["schema"], table["name"])
        for column in table["columns"]:
            column_identity = table_identity + (column["name"],)
            owned_sequence = column["owned_sequence"]
            expected_sequence = sequence_by_owner.get(column_identity)
            if not exact_json(owned_sequence, expected_sequence):
                raise DeployGuardError(
                    "column-owned sequence differs from sequence catalog"
                )
            if owned_sequence is not None:
                seen_owned_sequences.add(
                    (owned_sequence["schema"], owned_sequence["name"])
                )
            type_values = [column["type"]]
            if column["type"]["array_item"] is not None:
                type_values.append(column["type"]["array_item"])
            for type_value in type_values:
                if type_value["kind"] == "e":
                    identity = (type_value["schema"], type_value["name"])
                    if enum_labels.get(identity) != type_value["enum_labels"]:
                        raise DeployGuardError(
                            "column enum identity differs from enum catalog"
                        )
        for constraint in table["constraints"]:
            reference = constraint["references"]
            if reference is None:
                continue
            identity = (reference["schema"], reference["table"])
            if identity not in table_columns or any(
                column not in table_columns[identity]
                for column in reference["columns"]
            ):
                raise DeployGuardError(
                    "foreign key references an unmanaged table or column"
                )
    if seen_owned_sequences != set(sequence_identities):
        raise DeployGuardError("reference catalog has an unbound sequence")
    return value


def validate_reference_catalog(candidate_manifest, reference_catalog):
    _validate_reference_catalog_shape(reference_catalog)
    expected_digest = candidate_manifest_sha256(candidate_manifest)
    if reference_catalog["candidate_manifest_sha256"] != expected_digest:
        raise DeployGuardError(
            "reference catalog is not bound to the candidate manifest"
        )
    expected_tables = _manifest_table_identities(candidate_manifest)
    observed_tables = [
        table["schema"] + "." + table["name"]
        for table in reference_catalog["tables"]
    ]
    if observed_tables != expected_tables:
        raise DeployGuardError(
            "reference catalog table set differs from the candidate manifest"
        )
    return reference_catalog


def reference_catalog_sha256(reference_catalog):
    _validate_reference_catalog_shape(reference_catalog)
    return hashlib.sha256(
        _canonical_json_key(reference_catalog).encode("utf-8")
    ).hexdigest()


def expected_database_schema_result(candidate_manifest, reference_catalog):
    validate_reference_catalog(candidate_manifest, reference_catalog)
    catalog_digest = reference_catalog_sha256(reference_catalog)
    return {
        "schema_version": MODEL_CATALOG_SCHEMA_VERSION,
        "candidate_manifest_sha256": candidate_manifest_sha256(candidate_manifest),
        "reference_catalog_sha256": catalog_digest,
        "observed_catalog_sha256": catalog_digest,
        "server_major": reference_catalog["server_major"],
        "table_count": len(reference_catalog["tables"]),
    }


def validate_database_schema(
    candidate_manifest,
    reference_catalog,
    database_result,
):
    validate_reference_catalog(candidate_manifest, reference_catalog)
    _require_json_key_set(
        database_result,
        DATABASE_SCHEMA_RESULT_KEYS,
        "database schema result",
    )
    if (
        type(database_result["schema_version"]) is not int
        or database_result["schema_version"] != MODEL_CATALOG_SCHEMA_VERSION
        or type(database_result["server_major"]) is not int
        or database_result["server_major"] != PINNED_POSTGRESQL_MAJOR
        or type(database_result["table_count"]) is not int
        or database_result["table_count"] <= 0
    ):
        raise DeployGuardError("database schema result identity is invalid")
    for key in (
        "candidate_manifest_sha256",
        "reference_catalog_sha256",
        "observed_catalog_sha256",
    ):
        if (
            type(database_result[key]) is not str
            or SHA256_DIGEST.fullmatch(database_result[key]) is None
        ):
            raise DeployGuardError("database schema result digest is invalid")
    expected = expected_database_schema_result(
        candidate_manifest,
        reference_catalog,
    )
    if not exact_json(database_result, expected):
        raise DeployGuardError(
            "database schema result is not bound to the exact reference catalog"
        )
    return database_result


def validate_no_migration_delta(old_manifest, candidate_manifest, heads_text, current_text):
    validate_migration_manifest(old_manifest)
    validate_migration_manifest(candidate_manifest)
    if not exact_json(old_manifest, candidate_manifest):
        raise DeployGuardError(
            "candidate migration history or model schema differs from the running image"
        )
    database_revisions = validate_migration_outputs(heads_text, current_text)
    if database_revisions != candidate_manifest["heads"]:
        raise DeployGuardError(
            "database revision does not equal the no-delta manifest head"
        )
    return database_revisions


def _expand_ast_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _expand_ast_name(node.value)
        if prefix is not None:
            return prefix + "." + node.attr
    return None


def _expand_constant_string(node, label):
    if not isinstance(node, ast.Constant) or type(node.value) is not str or not node.value:
        raise DeployGuardError("{0} must be one non-empty string literal".format(label))
    if "\0" in node.value or "\n" in node.value or "\r" in node.value:
        raise DeployGuardError("{0} contains a control character".format(label))
    return node.value


def _expand_string_list(node, label):
    if not isinstance(node, (ast.List, ast.Tuple)):
        raise DeployGuardError("{0} must be one literal string list".format(label))
    values = [
        _expand_constant_string(item, "{0} item".format(label))
        for item in node.elts
    ]
    if not values or len(values) != len(set(values)):
        raise DeployGuardError("{0} is empty or duplicated".format(label))
    return values


def _expand_keyword_map(call, label):
    result = {}
    for keyword in call.keywords:
        if keyword.arg is None or keyword.arg in result:
            raise DeployGuardError("{0} has dynamic or duplicate keywords".format(label))
        result[keyword.arg] = keyword.value
    return result


def _expand_validate_safe_value(node, label):
    if isinstance(node, ast.Constant):
        if node.value is None or type(node.value) in (str, int, float, bool):
            return
        raise DeployGuardError("{0} contains an unsupported literal".format(label))
    if isinstance(node, (ast.List, ast.Tuple)):
        for item in node.elts:
            _expand_validate_safe_value(item, label)
        return
    if isinstance(node, ast.Dict):
        if any(key is None for key in node.keys):
            raise DeployGuardError("{0} contains a dynamic mapping".format(label))
        for key, value in zip(node.keys, node.values):
            _expand_validate_safe_value(key, label)
            _expand_validate_safe_value(value, label)
        return
    if isinstance(node, ast.Name) and node.id == "JSONB":
        return
    if not isinstance(node, ast.Call):
        raise DeployGuardError("{0} contains executable or dynamic syntax".format(label))
    dotted = _expand_ast_name(node.func)
    if dotted not in _EXPAND_ALLOWED_SA_CALLS:
        raise DeployGuardError(
            "{0} calls a non-allowlisted constructor: {1}".format(label, dotted)
        )
    if dotted in ("sa.false", "sa.func.now", "sa.true"):
        if node.args or node.keywords:
            raise DeployGuardError("{0} function arguments are not allowed".format(label))
        return
    if dotted == "sa.text":
        if len(node.args) != 1 or node.keywords:
            raise DeployGuardError("{0} SQL literal shape is invalid".format(label))
        value = _expand_constant_string(node.args[0], label + " SQL literal")
        if _EXPAND_SAFE_TEXT_DEFAULT.fullmatch(value) is None:
            raise DeployGuardError("{0} SQL text is not a safe literal".format(label))
        return
    for argument in node.args:
        if isinstance(argument, ast.Starred):
            raise DeployGuardError("{0} uses dynamic positional arguments".format(label))
        _expand_validate_safe_value(argument, label)
    for name, value in _expand_keyword_map(node, label).items():
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            raise DeployGuardError("{0} keyword is invalid".format(label))
        _expand_validate_safe_value(value, label)


def _expand_manifest_tables(manifest):
    validate_migration_manifest(manifest)
    return {
        (table["schema"] or "public", table["name"]): table
        for table in manifest["model_schema"]
    }


def _expand_unique_keys(table):
    return [
        frozenset(constraint["columns"])
        for constraint in table["constraints"]
        if constraint["kind"] in ("primary_key", "unique")
        and constraint["columns"]
    ]


def _expand_require_redundant_unique(
    old_table,
    columns,
    label,
    *,
    primary_only=False,
):
    requested = frozenset(columns)
    keys = [
        frozenset(constraint["columns"])
        for constraint in old_table["constraints"]
        if constraint["columns"]
        and (
            constraint["kind"] == "primary_key"
            or (not primary_only and constraint["kind"] == "unique")
        )
    ]
    if not any(key.issubset(requested) for key in keys):
        raise DeployGuardError(
            "{0} is not provably redundant with an existing primary/unique key".format(
                label
            )
        )


def _expand_parse_column(node, label):
    if not isinstance(node, ast.Call) or _expand_ast_name(node.func) != "sa.Column":
        raise DeployGuardError("{0} must be an explicit sa.Column".format(label))
    if len(node.args) < 2:
        raise DeployGuardError("{0} is missing its name or type".format(label))
    name = _expand_constant_string(node.args[0], label + " name")
    keywords = _expand_keyword_map(node, label)
    for forbidden in ("primary_key", "unique"):
        value = keywords.get(forbidden)
        if isinstance(value, ast.Constant) and value.value is True:
            raise DeployGuardError(
                "{0} cannot add an existing-table {1}".format(label, forbidden)
            )
    nullable_node = keywords.get("nullable")
    nullable = True
    if nullable_node is not None:
        if not isinstance(nullable_node, ast.Constant) or type(nullable_node.value) is not bool:
            raise DeployGuardError("{0} nullable must be a literal boolean".format(label))
        nullable = nullable_node.value
    server_default = keywords.get("server_default")
    if not nullable:
        if server_default is None:
            raise DeployGuardError(
                "{0} adds NOT NULL to an existing table without a safe default".format(
                    label
                )
            )
        safe_default = (
            isinstance(server_default, ast.Constant)
            and server_default.value is not None
            and type(server_default.value) in (str, int, float, bool)
        )
        if isinstance(server_default, ast.Call) and _expand_ast_name(
            server_default.func
        ) == "sa.text":
            try:
                _expand_validate_safe_value(server_default, label + " default")
            except DeployGuardError:
                safe_default = False
            else:
                safe_default = True
        if not safe_default:
            raise DeployGuardError(
                "{0} NOT NULL default is dynamic or unsafe".format(label)
            )
    _expand_validate_safe_value(node, label)
    return name


def _expand_operation(kind, table, name, columns):
    value = {
        "op": kind,
        "table": table,
        "name": name,
        "columns": list(columns),
    }
    if tuple(value) != EXPAND_OPERATION_KEYS:
        raise AssertionError("expand operation key order changed")
    return value


def _expand_validate_unique_call(
    call,
    table_name,
    old_table,
    label,
    *,
    batch,
    primary_only=False,
):
    expected = 2 if batch else 3
    if len(call.args) != expected or call.keywords:
        raise DeployGuardError("{0} arguments are invalid".format(label))
    name = _expand_constant_string(call.args[0], label + " name")
    if batch:
        columns_node = call.args[1]
    else:
        explicit_table = _expand_constant_string(call.args[1], label + " table")
        if explicit_table != table_name:
            raise DeployGuardError("{0} table identity changed".format(label))
        columns_node = call.args[2]
    columns = _expand_string_list(columns_node, label + " columns")
    _expand_require_redundant_unique(
        old_table,
        columns,
        label,
        primary_only=primary_only,
    )
    return _expand_operation("create_unique_constraint", table_name, name, columns)


def _expand_validate_upgrade(
    upgrade,
    old_manifest,
    candidate_manifest,
    previously_created_tables=(),
):
    old_tables = _expand_manifest_tables(old_manifest)
    old_by_name = {
        table_name: table
        for (schema, table_name), table in old_tables.items()
        if schema == "public"
    }
    candidate_tables = _expand_manifest_tables(candidate_manifest)
    candidate_by_name = {
        table_name: table
        for (schema, table_name), table in candidate_tables.items()
        if schema == "public"
    }
    if not isinstance(previously_created_tables, (set, frozenset)) or any(
        type(item) is not str or not item for item in previously_created_tables
    ):
        raise DeployGuardError("prior expand table identities are invalid")
    new_tables = set(previously_created_tables)
    declared_new_tables = set()
    operations = []
    for statement_number, statement in enumerate(upgrade.body, start=1):
        label = "expand upgrade statement {0}".format(statement_number)
        if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
            call = statement.value
            dotted = _expand_ast_name(call.func)
            if dotted == "op.create_table":
                if len(call.args) < 2 or call.keywords:
                    raise DeployGuardError("{0} create_table shape is invalid".format(label))
                table_name = _expand_constant_string(call.args[0], label + " table")
                if table_name in old_by_name or table_name in new_tables:
                    raise DeployGuardError("{0} table already exists".format(label))
                columns = []
                for item in call.args[1:]:
                    _expand_validate_safe_value(item, label)
                    if isinstance(item, ast.Call) and _expand_ast_name(item.func) == "sa.Column":
                        columns.append(
                            _expand_constant_string(item.args[0], label + " column")
                        )
                if not columns or len(columns) != len(set(columns)):
                    raise DeployGuardError("{0} columns are empty or duplicated".format(label))
                new_tables.add(table_name)
                declared_new_tables.add(table_name)
                operations.append(
                    _expand_operation("create_table", table_name, table_name, columns)
                )
                continue
            if dotted == "op.create_index":
                if len(call.args) != 3:
                    raise DeployGuardError("{0} create_index shape is invalid".format(label))
                index_name = _expand_constant_string(call.args[0], label + " name")
                table_name = _expand_constant_string(call.args[1], label + " table")
                columns = _expand_string_list(call.args[2], label + " columns")
                keywords = _expand_keyword_map(call, label)
                if set(keywords) - {"unique"}:
                    raise DeployGuardError("{0} create_index options are not allowlisted".format(label))
                unique = False
                if "unique" in keywords:
                    value = keywords["unique"]
                    if not isinstance(value, ast.Constant) or type(value.value) is not bool:
                        raise DeployGuardError("{0} unique must be a literal boolean".format(label))
                    unique = value.value
                if table_name not in new_tables and table_name not in old_by_name:
                    raise DeployGuardError("{0} targets an unknown table".format(label))
                if unique and table_name in old_by_name:
                    _expand_require_redundant_unique(
                        old_by_name[table_name], columns, label
                    )
                operations.append(
                    _expand_operation("create_index", table_name, index_name, columns)
                )
                continue
            if dotted == "op.add_column":
                if len(call.args) != 2 or call.keywords:
                    raise DeployGuardError("{0} add_column shape is invalid".format(label))
                table_name = _expand_constant_string(call.args[0], label + " table")
                if (
                    table_name not in old_by_name
                    and table_name not in previously_created_tables
                ):
                    raise DeployGuardError("{0} may target only an existing table".format(label))
                column_name = _expand_parse_column(call.args[1], label + " column")
                operations.append(
                    _expand_operation("add_column", table_name, column_name, [column_name])
                )
                continue
            if dotted == "op.create_unique_constraint":
                if len(call.args) != 3:
                    raise DeployGuardError("{0} unique constraint shape is invalid".format(label))
                table_name = _expand_constant_string(call.args[1], label + " table")
                prior_created = table_name in previously_created_tables
                target_table = old_by_name.get(table_name)
                if target_table is None and prior_created:
                    target_table = candidate_by_name.get(table_name)
                if target_table is None:
                    raise DeployGuardError("{0} may target only an existing table".format(label))
                operations.append(
                    _expand_validate_unique_call(
                        call,
                        table_name,
                        target_table,
                        label,
                        batch=False,
                        primary_only=prior_created,
                    )
                )
                continue
            raise DeployGuardError(
                "{0} uses a destructive, dynamic, or unknown operation: {1}".format(
                    label, dotted
                )
            )
        if isinstance(statement, ast.With):
            if len(statement.items) != 1:
                raise DeployGuardError("{0} batch context is invalid".format(label))
            item = statement.items[0]
            context_call = item.context_expr
            if (
                not isinstance(context_call, ast.Call)
                or _expand_ast_name(context_call.func) != "op.batch_alter_table"
                or len(context_call.args) != 1
                or context_call.keywords
                or not isinstance(item.optional_vars, ast.Name)
            ):
                raise DeployGuardError(
                    "{0} batch context may not recreate or redirect a table".format(label)
                )
            table_name = _expand_constant_string(
                context_call.args[0], label + " batch table"
            )
            if table_name not in old_by_name:
                raise DeployGuardError("{0} batch table is not an old table".format(label))
            alias = item.optional_vars.id
            if not statement.body:
                raise DeployGuardError("{0} batch body is empty".format(label))
            for batch_number, batch_statement in enumerate(statement.body, start=1):
                batch_label = "{0} batch operation {1}".format(label, batch_number)
                if not (
                    isinstance(batch_statement, ast.Expr)
                    and isinstance(batch_statement.value, ast.Call)
                    and _expand_ast_name(batch_statement.value.func)
                    == alias + ".create_unique_constraint"
                ):
                    raise DeployGuardError(
                        "{0} is destructive, dynamic, or not allowlisted".format(
                            batch_label
                        )
                    )
                operations.append(
                    _expand_validate_unique_call(
                        batch_statement.value,
                        table_name,
                        old_by_name[table_name],
                        batch_label,
                        batch=True,
                    )
                )
            continue
        raise DeployGuardError(
            "{0} is control flow, assignment, or another non-declarative operation".format(
                label
            )
        )
    if not operations or not declared_new_tables:
        raise DeployGuardError("expand migration did not declare an additive schema")
    identities = [(item["op"], item["table"], item["name"]) for item in operations]
    if len(identities) != len(set(identities)):
        raise DeployGuardError("expand migration operations are duplicated")
    return operations, declared_new_tables


def _expand_validate_function_shape(function, label):
    arguments = function.args
    if (
        arguments.posonlyargs
        or arguments.args
        or arguments.vararg is not None
        or arguments.kwonlyargs
        or arguments.kwarg is not None
        or arguments.defaults
        or arguments.kw_defaults
        or function.decorator_list
    ):
        raise DeployGuardError("{0} function signature is dynamic".format(label))
    if function.returns is not None and not (
        isinstance(function.returns, ast.Constant) and function.returns.value is None
    ):
        raise DeployGuardError("{0} return annotation is invalid".format(label))


def _validate_expand_migration_ast(
    source,
    migration,
    old_manifest,
    candidate_manifest,
    previously_created_tables,
):
    if not isinstance(source, bytes) or not source or len(source) > MAX_EXPAND_MIGRATION_SOURCE_BYTES:
        raise DeployGuardError("expand migration source size is invalid")
    if hashlib.sha256(source).hexdigest() != migration["sha256"]:
        raise DeployGuardError("expand migration source does not match the image manifest")
    try:
        tree = ast.parse(
            source.decode("utf-8"),
            filename="EXPAND_MIGRATION_{0}.py".format(migration["revision"]),
        )
    except (UnicodeError, SyntaxError) as exc:
        raise DeployGuardError("expand migration source is not valid UTF-8 Python") from exc

    assignments = {}
    functions = {}
    expected_imports = {
        ("import", "sqlalchemy", "sa"),
        ("from", "__future__", "annotations"),
        ("from", "alembic", "op"),
        ("from", "app.db.compat", "JSONB"),
    }
    observed_imports = set()
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and type(
            node.value.value
        ) is str:
            continue
        if isinstance(node, ast.Import):
            if len(node.names) != 1:
                raise DeployGuardError("expand migration import shape is invalid")
            alias = node.names[0]
            observed_imports.add(("import", alias.name, alias.asname))
            continue
        if isinstance(node, ast.ImportFrom):
            if node.level != 0 or len(node.names) != 1:
                raise DeployGuardError("expand migration from-import shape is invalid")
            alias = node.names[0]
            if alias.asname is not None:
                raise DeployGuardError("expand migration import aliases are forbidden")
            observed_imports.add(("from", node.module, alias.name))
            continue
        if isinstance(node, ast.Assign):
            if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                raise DeployGuardError("expand migration top-level assignment is dynamic")
            name = node.targets[0].id
            if name not in ("revision", "down_revision", "branch_labels", "depends_on"):
                raise DeployGuardError("expand migration has an executable top-level value")
            if name in assignments or not isinstance(node.value, ast.Constant):
                raise DeployGuardError("expand migration revision metadata is invalid")
            assignments[name] = node.value.value
            continue
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if isinstance(node, ast.AsyncFunctionDef) or node.name not in (
                "upgrade",
                "downgrade",
            ):
                raise DeployGuardError("expand migration helper functions are forbidden")
            if node.name in functions:
                raise DeployGuardError("expand migration functions are duplicated")
            _expand_validate_function_shape(node, node.name)
            functions[node.name] = node
            continue
        raise DeployGuardError("expand migration has executable top-level syntax")
    if observed_imports != expected_imports:
        raise DeployGuardError("expand migration imports are not the exact allowlist")
    if assignments != {
        "revision": migration["revision"],
        "down_revision": migration["down_revision"],
        "branch_labels": None,
        "depends_on": None,
    }:
        raise DeployGuardError("expand migration revision metadata is not exact")
    if set(functions) != {"upgrade", "downgrade"}:
        raise DeployGuardError("expand migration must define upgrade and downgrade")
    return _expand_validate_upgrade(
        functions["upgrade"],
        old_manifest,
        candidate_manifest,
        previously_created_tables,
    )


def validate_expand_migration_source(sources, old_manifest, candidate_manifest):
    appended = _expand_appended_migrations(old_manifest, candidate_manifest)
    if isinstance(sources, bytes):
        sources = [sources]
    if (
        not isinstance(sources, (list, tuple))
        or len(sources) != len(appended)
        or any(not isinstance(source, bytes) for source in sources)
    ):
        raise DeployGuardError(
            "expand migration sources do not exactly cover the appended chain"
        )

    migration_items = []
    operations = []
    previously_created_tables = set()
    for migration, source in zip(appended, sources):
        migration_operations, created_tables = _validate_expand_migration_ast(
            source,
            migration,
            old_manifest,
            candidate_manifest,
            previously_created_tables,
        )
        previously_created_tables.update(created_tables)
        item = {
            "revision": migration["revision"],
            "down_revision": migration["down_revision"],
            "sha256": migration["sha256"],
        }
        if tuple(item) != EXPAND_MIGRATION_ITEM_KEYS:
            raise AssertionError("expand migration plan item key order changed")
        migration_items.append(item)
        operations.extend(migration_operations)

    migration_digest = hashlib.sha256(
        _canonical_json_key(
            {
                "schema_version": EXPAND_MIGRATION_POLICY_SCHEMA_VERSION,
                "migrations": migration_items,
            }
        ).encode("utf-8")
    ).hexdigest()
    operation_digest = hashlib.sha256(
        _canonical_json_key(
            {
                "schema_version": EXPAND_MIGRATION_POLICY_SCHEMA_VERSION,
                "migrations": migration_items,
                "operations": operations,
            }
        ).encode("utf-8")
    ).hexdigest()
    plan = {
        "schema_version": EXPAND_MIGRATION_PLAN_SCHEMA_VERSION,
        "old_manifest_sha256": candidate_manifest_sha256(old_manifest),
        "old_head": old_manifest["heads"][0],
        "candidate_manifest_sha256": candidate_manifest_sha256(candidate_manifest),
        "candidate_head": candidate_manifest["heads"][0],
        "migrations": migration_items,
        "migration_sha256": migration_digest,
        "operation_policy_sha256": operation_digest,
        "operations": operations,
    }
    return validate_expand_migration_plan(plan)


def validate_expand_migration_plan(plan):
    _require_exact_keys(plan, EXPAND_MIGRATION_PLAN_KEYS, "expand migration plan")
    if (
        type(plan["schema_version"]) is not int
        or plan["schema_version"] != EXPAND_MIGRATION_PLAN_SCHEMA_VERSION
    ):
        raise DeployGuardError("expand migration plan schema version is invalid")
    for key in (
        "old_manifest_sha256",
        "candidate_manifest_sha256",
        "migration_sha256",
        "operation_policy_sha256",
    ):
        if type(plan[key]) is not str or SHA256_DIGEST.fullmatch(plan[key]) is None:
            raise DeployGuardError("expand migration plan {0} is invalid".format(key))
    for key in ("old_head", "candidate_head"):
        if type(plan[key]) is not str or MIGRATION_REVISION.fullmatch(plan[key]) is None:
            raise DeployGuardError("expand migration plan {0} is invalid".format(key))
    if plan["old_head"] == plan["candidate_head"]:
        raise DeployGuardError("expand migration plan heads must differ")
    migrations = plan["migrations"]
    if (
        not isinstance(migrations, list)
        or not migrations
        or len(migrations) > MAX_EXPAND_MIGRATIONS
    ):
        raise DeployGuardError("expand migration plan chain is empty or too large")
    expected_down_revision = plan["old_head"]
    observed_revisions = set()
    for number, migration in enumerate(migrations):
        _require_exact_keys(
            migration,
            EXPAND_MIGRATION_ITEM_KEYS,
            "expand migration plan item {0}".format(number),
        )
        if (
            type(migration["revision"]) is not str
            or MIGRATION_REVISION.fullmatch(migration["revision"]) is None
            or migration["revision"] in observed_revisions
            or type(migration["down_revision"]) is not str
            or migration["down_revision"] != expected_down_revision
            or type(migration["sha256"]) is not str
            or SHA256_DIGEST.fullmatch(migration["sha256"]) is None
        ):
            raise DeployGuardError("expand migration plan chain identity is invalid")
        observed_revisions.add(migration["revision"])
        expected_down_revision = migration["revision"]
    if expected_down_revision != plan["candidate_head"]:
        raise DeployGuardError("expand migration plan chain does not reach its candidate head")
    expected_migration_digest = hashlib.sha256(
        _canonical_json_key(
            {
                "schema_version": EXPAND_MIGRATION_POLICY_SCHEMA_VERSION,
                "migrations": migrations,
            }
        ).encode("utf-8")
    ).hexdigest()
    if plan["migration_sha256"] != expected_migration_digest:
        raise DeployGuardError("expand migration chain digest is invalid")
    operations = plan["operations"]
    if not isinstance(operations, list) or not operations:
        raise DeployGuardError("expand migration plan operations are empty")
    for number, operation in enumerate(operations):
        _require_exact_keys(
            operation,
            EXPAND_OPERATION_KEYS,
            "expand migration operation {0}".format(number),
        )
        if operation["op"] not in (
            "create_table",
            "create_index",
            "create_unique_constraint",
            "add_column",
        ):
            raise DeployGuardError("expand migration operation kind is invalid")
        for key in ("table", "name"):
            if type(operation[key]) is not str or not operation[key]:
                raise DeployGuardError("expand migration operation identity is invalid")
        _require_string_list(
            operation["columns"],
            "expand migration operation columns",
            allow_empty=False,
        )
    identities = [
        (operation["op"], operation["table"], operation["name"])
        for operation in operations
    ]
    if len(identities) != len(set(identities)):
        raise DeployGuardError("expand migration plan operations are duplicated")
    expected_policy_digest = hashlib.sha256(
        _canonical_json_key(
            {
                "schema_version": EXPAND_MIGRATION_POLICY_SCHEMA_VERSION,
                "migrations": migrations,
                "operations": operations,
            }
        ).encode("utf-8")
    ).hexdigest()
    if plan["operation_policy_sha256"] != expected_policy_digest:
        raise DeployGuardError("expand migration operation policy digest is invalid")
    return plan


def _expand_catalog_identity_map(values, keys):
    result = {}
    for value in values:
        identity = tuple(value[key] for key in keys)
        if identity in result:
            raise DeployGuardError("expand catalog identities are duplicated")
        result[identity] = value
    return result


def _expand_require_preserved_items(old_items, candidate_items, key, label):
    old_map = _expand_catalog_identity_map(old_items, (key,))
    candidate_map = _expand_catalog_identity_map(candidate_items, (key,))
    for identity, old_value in old_map.items():
        if identity not in candidate_map or not exact_json(
            old_value, candidate_map[identity]
        ):
            raise DeployGuardError("{0} changed or disappeared".format(label))
    return old_map, candidate_map


def _expand_added_item_names(old_map, candidate_map, label):
    """Unwrap the singleton identity tuples used by catalog item maps."""
    added_identities = set(candidate_map) - set(old_map)
    if any(
        not isinstance(identity, tuple)
        or len(identity) != 1
        or type(identity[0]) is not str
        or not identity[0]
        for identity in added_identities
    ):
        raise DeployGuardError("{0} identity is invalid".format(label))
    return {identity[0] for identity in added_identities}


def validate_expand_catalog_transition(
    old_manifest,
    candidate_manifest,
    old_catalog,
    migrated_catalog,
    candidate_reference_catalog,
    plan,
):
    validate_migration_manifest(old_manifest)
    validate_migration_manifest(candidate_manifest)
    validate_expand_migration_plan(plan)
    appended = _expand_appended_migrations(old_manifest, candidate_manifest)
    expected_migration_items = [
        {
            "revision": migration["revision"],
            "down_revision": migration["down_revision"],
            "sha256": migration["sha256"],
        }
        for migration in appended
    ]
    if (
        not exact_json(plan["migrations"], expected_migration_items)
        or old_manifest["heads"] != [plan["old_head"]]
        or candidate_manifest["heads"] != [plan["candidate_head"]]
    ):
        raise DeployGuardError(
            "expand catalog manifests are not the exact approved linear append"
        )
    if plan["old_manifest_sha256"] != candidate_manifest_sha256(old_manifest):
        raise DeployGuardError("expand catalog plan is not bound to the old manifest")
    if plan["candidate_manifest_sha256"] != candidate_manifest_sha256(
        candidate_manifest
    ):
        raise DeployGuardError("expand catalog plan is not bound to the candidate manifest")
    validate_reference_catalog(old_manifest, old_catalog)
    validate_reference_catalog(candidate_manifest, migrated_catalog)
    validate_reference_catalog(candidate_manifest, candidate_reference_catalog)
    if not exact_json(migrated_catalog, candidate_reference_catalog):
        raise DeployGuardError(
            "migration result catalog does not exactly equal candidate models"
        )

    old_tables = _expand_catalog_identity_map(old_catalog["tables"], ("schema", "name"))
    candidate_tables = _expand_catalog_identity_map(
        migrated_catalog["tables"], ("schema", "name")
    )
    declared_new_tables = {
        ("public", operation["table"])
        for operation in plan["operations"]
        if operation["op"] == "create_table"
    }
    actual_new_tables = set(candidate_tables) - set(old_tables)
    if actual_new_tables != declared_new_tables:
        raise DeployGuardError(
            "migration result added a table not declared by the expand policy"
        )
    if any(identity not in candidate_tables for identity in old_tables):
        raise DeployGuardError("migration result removed an old table")

    allowed_columns = {}
    allowed_constraints = {}
    allowed_indexes = {}
    for operation in plan["operations"]:
        identity = ("public", operation["table"])
        if operation["op"] == "add_column":
            allowed_columns.setdefault(identity, set()).add(operation["name"])
        elif operation["op"] == "create_unique_constraint":
            allowed_constraints.setdefault(identity, set()).add(operation["name"])
            allowed_indexes.setdefault(identity, set()).add(operation["name"])
        elif operation["op"] == "create_index":
            allowed_indexes.setdefault(identity, set()).add(operation["name"])

    for identity, old_table in old_tables.items():
        candidate_table = candidate_tables[identity]
        old_header = {
            key: old_table[key]
            for key in PHYSICAL_TABLE_KEYS
            if key not in ("columns", "constraints", "indexes")
        }
        candidate_header = {
            key: candidate_table[key]
            for key in PHYSICAL_TABLE_KEYS
            if key not in ("columns", "constraints", "indexes")
        }
        if not exact_json(old_header, candidate_header):
            raise DeployGuardError("expand migration changed an old table identity")

        old_column_map, candidate_column_map = _expand_require_preserved_items(
            old_table["columns"],
            candidate_table["columns"],
            "name",
            "old table column",
        )
        added_columns = _expand_added_item_names(
            old_column_map,
            candidate_column_map,
            "old table column",
        )
        if added_columns != allowed_columns.get(identity, set()):
            raise DeployGuardError("expand migration added an undeclared old-table column")

        old_constraint_map, candidate_constraint_map = _expand_require_preserved_items(
            old_table["constraints"],
            candidate_table["constraints"],
            "name",
            "old table constraint",
        )
        added_constraints = _expand_added_item_names(
            old_constraint_map,
            candidate_constraint_map,
            "old table constraint",
        )
        declared_constraints = allowed_constraints.get(identity, set())
        if added_constraints != declared_constraints:
            raise DeployGuardError(
                "expand migration added an undeclared old-table constraint: "
                "table={0}.{1} added={2} declared={3}".format(
                    identity[0],
                    identity[1],
                    sorted(added_constraints),
                    sorted(declared_constraints),
                )
            )

        old_index_map, candidate_index_map = _expand_require_preserved_items(
            old_table["indexes"],
            candidate_table["indexes"],
            "name",
            "old table index",
        )
        added_indexes = _expand_added_item_names(
            old_index_map,
            candidate_index_map,
            "old table index",
        )
        if added_indexes != allowed_indexes.get(identity, set()):
            raise DeployGuardError("expand migration added an undeclared old-table index")

    old_sequences = _expand_catalog_identity_map(
        old_catalog["sequences"], ("schema", "name")
    )
    candidate_sequences = _expand_catalog_identity_map(
        migrated_catalog["sequences"], ("schema", "name")
    )
    for identity, old_sequence in old_sequences.items():
        if identity not in candidate_sequences or not exact_json(
            old_sequence, candidate_sequences[identity]
        ):
            raise DeployGuardError("expand migration changed an old sequence")
    allowed_sequence_owners = declared_new_tables | set(allowed_columns)
    for identity in set(candidate_sequences) - set(old_sequences):
        owner = candidate_sequences[identity]["owned_by"]
        owner_table = (owner["schema"], owner["table"])
        if owner_table not in allowed_sequence_owners:
            raise DeployGuardError(
                "expand migration added an undeclared sequence: "
                "sequence={0}.{1} owner={2}.{3}.{4}".format(
                    identity[0],
                    identity[1],
                    owner["schema"],
                    owner["table"],
                    owner["column"],
                )
            )
        if (
            owner_table not in declared_new_tables
            and owner_table in allowed_columns
            and owner["column"] not in allowed_columns[owner_table]
        ):
            raise DeployGuardError(
                "expand migration sequence owner is undeclared: "
                "sequence={0}.{1} owner={2}.{3}.{4}".format(
                    identity[0],
                    identity[1],
                    owner["schema"],
                    owner["table"],
                    owner["column"],
                )
            )

    old_enums = _expand_catalog_identity_map(
        old_catalog["enum_types"], ("schema", "name")
    )
    candidate_enums = _expand_catalog_identity_map(
        migrated_catalog["enum_types"], ("schema", "name")
    )
    if set(old_enums) != set(candidate_enums) or any(
        not exact_json(value, candidate_enums[identity])
        for identity, value in old_enums.items()
    ):
        raise DeployGuardError(
            "expand migration changed or added an enum outside the allowlist"
        )
    return {
        "old_catalog_sha256": reference_catalog_sha256(old_catalog),
        "candidate_catalog_sha256": reference_catalog_sha256(migrated_catalog),
    }


def expand_migration_plan_sha256(plan):
    validate_expand_migration_plan(plan)
    return hashlib.sha256(_canonical_json_key(plan).encode("utf-8")).hexdigest()


def emitted_expand_migration_plan_values(plan):
    validate_expand_migration_plan(plan)
    return [plan["old_head"], plan["candidate_head"]]


def validate_expand_approval_plan(value, migration_plan=None):
    _require_exact_keys(value, EXPAND_APPROVAL_PLAN_KEYS, "expand approval plan")
    if (
        type(value["schema_version"]) is not int
        or value["schema_version"] != EXPAND_APPROVAL_PLAN_SCHEMA_VERSION
    ):
        raise DeployGuardError("expand approval plan schema version is invalid")
    if (
        type(value["expected_main_sha"]) is not str
        or GIT_OBJECT_ID.fullmatch(value["expected_main_sha"]) is None
    ):
        raise DeployGuardError("expand approval plan expected main SHA is invalid")
    for key in (
        "trusted_bundle_sha256",
        "old_manifest_sha256",
        "candidate_manifest_sha256",
        "migration_sha256",
        "operation_policy_sha256",
        "old_catalog_sha256",
        "candidate_catalog_sha256",
    ):
        if type(value[key]) is not str or SHA256_DIGEST.fullmatch(value[key]) is None:
            raise DeployGuardError(
                "expand approval plan {0} is invalid".format(key)
            )
    for key in ("old_head", "candidate_head"):
        if type(value[key]) is not str or MIGRATION_REVISION.fullmatch(value[key]) is None:
            raise DeployGuardError(
                "expand approval plan {0} is invalid".format(key)
            )
    if value["old_head"] == value["candidate_head"]:
        raise DeployGuardError("expand approval plan heads must differ")
    migrations = value["migrations"]
    if (
        not isinstance(migrations, list)
        or not migrations
        or len(migrations) > MAX_EXPAND_MIGRATIONS
    ):
        raise DeployGuardError("expand approval migration chain is empty or too large")
    expected_down_revision = value["old_head"]
    revisions = set()
    for number, migration in enumerate(migrations):
        _require_exact_keys(
            migration,
            EXPAND_MIGRATION_ITEM_KEYS,
            "expand approval migration item {0}".format(number),
        )
        if (
            type(migration["revision"]) is not str
            or MIGRATION_REVISION.fullmatch(migration["revision"]) is None
            or migration["revision"] in revisions
            or type(migration["down_revision"]) is not str
            or migration["down_revision"] != expected_down_revision
            or type(migration["sha256"]) is not str
            or SHA256_DIGEST.fullmatch(migration["sha256"]) is None
        ):
            raise DeployGuardError("expand approval migration chain is invalid")
        revisions.add(migration["revision"])
        expected_down_revision = migration["revision"]
    if expected_down_revision != value["candidate_head"]:
        raise DeployGuardError(
            "expand approval migration chain does not reach its candidate head"
        )
    expected_migration_digest = hashlib.sha256(
        _canonical_json_key(
            {
                "schema_version": EXPAND_MIGRATION_POLICY_SCHEMA_VERSION,
                "migrations": migrations,
            }
        ).encode("utf-8")
    ).hexdigest()
    if value["migration_sha256"] != expected_migration_digest:
        raise DeployGuardError("expand approval migration chain digest is invalid")
    if migration_plan is not None:
        validate_expand_migration_plan(migration_plan)
        expected = {
            "old_manifest_sha256": migration_plan["old_manifest_sha256"],
            "old_head": migration_plan["old_head"],
            "candidate_manifest_sha256": migration_plan[
                "candidate_manifest_sha256"
            ],
            "candidate_head": migration_plan["candidate_head"],
            "migrations": migration_plan["migrations"],
            "migration_sha256": migration_plan["migration_sha256"],
            "operation_policy_sha256": migration_plan[
                "operation_policy_sha256"
            ],
        }
        if any(not exact_json(value[key], expected[key]) for key in expected):
            raise DeployGuardError(
                "expand approval plan is not bound to the migration plan"
            )
    return value


def build_expand_approval_plan(
    expected_main_sha,
    trusted_bundle_sha256,
    old_manifest,
    candidate_manifest,
    old_catalog,
    candidate_catalog,
    migration_plan,
):
    validate_migration_manifest(old_manifest)
    validate_migration_manifest(candidate_manifest)
    validate_expand_migration_plan(migration_plan)
    validate_expand_catalog_transition(
        old_manifest,
        candidate_manifest,
        old_catalog,
        candidate_catalog,
        candidate_catalog,
        migration_plan,
    )
    old_manifest_digest = candidate_manifest_sha256(old_manifest)
    candidate_manifest_digest = candidate_manifest_sha256(candidate_manifest)
    if (
        migration_plan["old_manifest_sha256"] != old_manifest_digest
        or migration_plan["candidate_manifest_sha256"]
        != candidate_manifest_digest
        or old_manifest["heads"] != [migration_plan["old_head"]]
        or candidate_manifest["heads"] != [migration_plan["candidate_head"]]
    ):
        raise DeployGuardError(
            "expand approval inputs are not bound to the migration plan"
        )
    value = {
        "schema_version": EXPAND_APPROVAL_PLAN_SCHEMA_VERSION,
        "expected_main_sha": expected_main_sha,
        "trusted_bundle_sha256": trusted_bundle_sha256,
        "old_manifest_sha256": old_manifest_digest,
        "old_head": migration_plan["old_head"],
        "candidate_manifest_sha256": candidate_manifest_digest,
        "candidate_head": migration_plan["candidate_head"],
        "migrations": migration_plan["migrations"],
        "migration_sha256": migration_plan["migration_sha256"],
        "operation_policy_sha256": migration_plan["operation_policy_sha256"],
        "old_catalog_sha256": reference_catalog_sha256(old_catalog),
        "candidate_catalog_sha256": reference_catalog_sha256(candidate_catalog),
    }
    return validate_expand_approval_plan(value, migration_plan)


EXPAND_TRANSACTION_RUNNER_TEMPLATE = r'''#!/usr/bin/env python3
import ast
import hashlib
import importlib.util
import json
import os
import stat
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool


PLAN = json.loads(__EXPAND_PLAN_JSON_LITERAL__)
FAIL_AFTER_UPGRADE = __FAIL_AFTER_UPGRADE__
MIGRATION_ROOT = Path("/app/app/db/migrations/versions")
MAX_SOURCE_BYTES = 2 * 1024 * 1024
REQUIRED_PG_ENV = ("PGHOST", "PGPORT", "PGUSER", "PGPASSWORD", "PGDATABASE")


def fail(message):
    raise RuntimeError(message)


def stable_source(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_size <= 0
            or before.st_size > MAX_SOURCE_BYTES
        ):
            fail("candidate migration source identity is invalid")
        chunks = []
        total = 0
        while True:
            chunk = os.read(descriptor, 65536)
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        after = os.fstat(descriptor)
        identity = lambda value: (
            value.st_dev,
            value.st_ino,
            value.st_mode,
            value.st_uid,
            value.st_gid,
            value.st_nlink,
            value.st_size,
            value.st_mtime_ns,
            value.st_ctime_ns,
        )
        if identity(before) != identity(after) or total != before.st_size:
            fail("candidate migration source changed while it was read")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def literal_assignment(tree, name):
    values = []
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name) and target.id == name:
            if not isinstance(node.value, ast.Constant):
                fail("candidate migration revision is dynamic")
            values.append(node.value.value)
    if not values:
        return None
    if len(values) != 1:
        fail("candidate migration revision metadata is missing or duplicated")
    return values[0]


def locate_migrations():
    targets = {item["revision"]: item for item in PLAN["migrations"]}
    if len(targets) != len(PLAN["migrations"]):
        fail("approved migration revisions are duplicated")
    matches = {}
    for path in sorted(MIGRATION_ROOT.glob("*.py")):
        payload = stable_source(path)
        try:
            tree = ast.parse(payload.decode("utf-8"), filename=str(path))
        except (UnicodeError, SyntaxError):
            fail("candidate migration source is not valid UTF-8 Python")
        revision = literal_assignment(tree, "revision")
        if revision in targets:
            if revision in matches:
                fail("candidate migration revision is duplicated")
            matches[revision] = (path, payload)
    if set(matches) != set(targets):
        fail("candidate migration chain is incomplete")
    ordered = []
    for item in PLAN["migrations"]:
        path, payload = matches[item["revision"]]
        if hashlib.sha256(payload).hexdigest() != item["sha256"]:
            fail("candidate migration SHA-256 changed after approval")
        ordered.append((item, path))
    return ordered


def database_url():
    if any(not os.environ.get(name) for name in REQUIRED_PG_ENV):
        fail("migration runner lacks the minimal libpq identity")
    if any(
        name in os.environ
        for name in (
            "DATABASE_URL",
            "DATABASE_PROBE_URL",
            "DATABASE_MIGRATION_URL",
            "XJIE_REFERENCE_DATABASE_URL",
        )
    ):
        fail("application database URL reached migration runner")
    try:
        port = int(os.environ["PGPORT"])
    except ValueError:
        fail("migration runner PGPORT is invalid")
    if not 1 <= port <= 65535:
        fail("migration runner PGPORT is invalid")
    from sqlalchemy import URL

    return URL.create(
        "postgresql+psycopg",
        username=os.environ["PGUSER"],
        password=os.environ["PGPASSWORD"],
        host=os.environ["PGHOST"],
        port=port,
        database=os.environ["PGDATABASE"],
    )


def load_module(path, migration, number):
    spec = importlib.util.spec_from_file_location(
        "xjie_approved_expand_migration_{0}".format(number), path
    )
    if spec is None or spec.loader is None:
        fail("cannot load approved candidate migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if (
        module.revision != migration["revision"]
        or module.down_revision != migration["down_revision"]
        or module.branch_labels is not None
        or module.depends_on is not None
    ):
        fail("candidate migration runtime metadata changed")
    return module


def run():
    migrations = [
        (item, load_module(path, item, number))
        for number, (item, path) in enumerate(locate_migrations(), start=1)
    ]
    engine = create_engine(database_url(), poolclass=NullPool)
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("SET LOCAL search_path TO public, pg_catalog")
            connection.exec_driver_sql("SET LOCAL lock_timeout TO '10s'")
            connection.exec_driver_sql("SET LOCAL statement_timeout TO '10min'")
            identity = connection.exec_driver_sql(
                "SELECT current_database(), current_user, "
                "current_setting('server_version_num')::integer / 10000, "
                "current_setting('transaction_read_only'), "
                "role.rolsuper, role.rolcreatedb, role.rolcreaterole, "
                "role.rolreplication, role.rolbypassrls "
                "FROM pg_catalog.pg_roles AS role WHERE role.rolname = current_user"
            ).one()
            if tuple(identity) != (
                os.environ["PGDATABASE"],
                os.environ["PGUSER"],
                16,
                "off",
                False,
                False,
                False,
                False,
                False,
            ):
                fail("migration database/role attestation failed")
            revisions = connection.exec_driver_sql(
                "SELECT version_num FROM public.alembic_version FOR UPDATE"
            ).scalars().all()
            if revisions != [PLAN["old_head"]]:
                fail("production database is not at the approved old head")
            context = MigrationContext.configure(
                connection=connection,
                opts={"transactional_ddl": True, "transaction_per_migration": False},
            )
            for number, (_migration, module) in enumerate(migrations, start=1):
                module.op = Operations(context)
                module.upgrade()
                if FAIL_AFTER_UPGRADE and number == 1:
                    fail("deterministic migration-chain transaction failpoint")
            result = connection.exec_driver_sql(
                "UPDATE public.alembic_version SET version_num = %s "
                "WHERE version_num = %s",
                (PLAN["candidate_head"], PLAN["old_head"]),
            )
            if result.rowcount != 1:
                fail("Alembic version compare-and-swap failed")
            observed = connection.exec_driver_sql(
                "SELECT version_num FROM public.alembic_version"
            ).scalars().all()
            if observed != [PLAN["candidate_head"]]:
                fail("candidate head was not recorded in the transaction")
    finally:
        engine.dispose()
    print(json.dumps({
        "schema_version": 1,
        "old_head": PLAN["old_head"],
        "candidate_head": PLAN["candidate_head"],
        "migration_sha256": PLAN["migration_sha256"],
        "committed": True,
    }, ensure_ascii=True, separators=(",", ":")))


if __name__ == "__main__":
    run()
'''


def render_expand_transaction_runner(plan, *, fail_after_upgrade=False):
    validate_expand_migration_plan(plan)
    if type(fail_after_upgrade) is not bool:
        raise DeployGuardError("transaction runner failpoint flag is invalid")
    replacements = {
        "__EXPAND_PLAN_JSON_LITERAL__": repr(_canonical_json_key(plan)),
        "__FAIL_AFTER_UPGRADE__": "True" if fail_after_upgrade else "False",
    }
    source = EXPAND_TRANSACTION_RUNNER_TEMPLATE
    if any(source.count(marker) != 1 for marker in replacements):
        raise DeployGuardError("expand transaction runner template is invalid")
    for marker, replacement in replacements.items():
        source = source.replace(marker, replacement)
    if any(marker in source for marker in replacements):
        raise DeployGuardError("expand transaction runner is incomplete")
    compile(source, "EXPAND_TRANSACTION_RUNNER.py", "exec")
    return source


def emit_expand_transaction_runner(path, plan):
    write_exclusive_bytes(
        path,
        render_expand_transaction_runner(plan).encode("utf-8"),
    )


EXPAND_OLD_APP_COMPAT_RESULT_KEYS = (
    "schema_version",
    "old_manifest_sha256",
    "candidate_head",
    "table_count",
    "crud_verified",
)
EXPAND_OLD_APP_COMPAT_TEMPLATE = r'''#!/usr/bin/env python3
import importlib
import json
import os
import pkgutil

from sqlalchemy import URL, create_engine
from sqlalchemy.pool import NullPool

import app.models
from app.db.base import Base


EXPECTED_TABLES = json.loads(__EXPECTED_TABLES_LITERAL__)
OLD_MANIFEST_SHA256 = __OLD_MANIFEST_SHA_LITERAL__
CANDIDATE_HEAD = __CANDIDATE_HEAD_LITERAL__
REQUIRED_PG_ENV = ("PGHOST", "PGPORT", "PGUSER", "PGPASSWORD", "PGDATABASE")


def fail(message):
    raise RuntimeError(message)


def load_models():
    modules = {"app.models"}
    for info in pkgutil.walk_packages(app.models.__path__, prefix="app.models."):
        modules.add(info.name)
    for name in sorted(modules):
        importlib.import_module(name)
    observed = sorted(
        (table.schema or "public") + "." + table.name
        for table in Base.metadata.tables.values()
    )
    if observed != EXPECTED_TABLES:
        fail("old application model registry changed")


def database_url():
    if any(not os.environ.get(name) for name in REQUIRED_PG_ENV):
        fail("old application compatibility probe lacks a database identity")
    if (
        os.environ["PGHOST"] != "/var/run/postgresql"
        or os.environ["PGPORT"] != "5432"
        or os.environ["PGUSER"] != "xjie_migration_rehearsal"
        or os.environ["PGDATABASE"] != "xjie_reference"
        or any(name.startswith("DATABASE_") for name in os.environ)
    ):
        fail("old application compatibility probe is not isolated")
    return URL.create(
        "postgresql+psycopg",
        username=os.environ["PGUSER"],
        password=os.environ["PGPASSWORD"],
        host=os.environ["PGHOST"],
        port=int(os.environ["PGPORT"]),
        database=os.environ["PGDATABASE"],
    )


def run():
    load_models()
    engine = create_engine(database_url(), poolclass=NullPool)
    try:
        with engine.begin() as connection:
            identity = connection.exec_driver_sql(
                "SELECT current_database(), current_user, "
                "current_setting('server_version_num')::integer / 10000, "
                "current_setting('transaction_read_only')"
            ).one()
            if tuple(identity) != (
                "xjie_reference",
                "xjie_migration_rehearsal",
                16,
                "off",
            ):
                fail("old application compatibility database attestation failed")
            heads = connection.exec_driver_sql(
                "SELECT version_num FROM public.alembic_version"
            ).scalars().all()
            if heads != [CANDIDATE_HEAD]:
                fail("old application compatibility database is not at candidate head")
            for table in sorted(
                Base.metadata.tables.values(),
                key=lambda item: ((item.schema or "public"), item.name),
            ):
                connection.execute(table.select().limit(0)).all()
            user_account = Base.metadata.tables.get("user_account")
            if user_account is None:
                fail("old application user_account model is missing")
            probe_id = -2147483000
            if connection.execute(
                user_account.select().where(user_account.c.id == probe_id)
            ).first() is not None:
                fail("old application CRUD probe identity is occupied")
            connection.execute(
                user_account.insert().values(
                    id=probe_id,
                    phone="expand-probe-0023",
                    username="expand-probe-old-image",
                    password="not-a-production-credential",
                    is_admin=False,
                    sync_flag=0,
                    deleted=0,
                )
            )
            if connection.execute(
                user_account.select().where(user_account.c.id == probe_id)
            ).one().username != "expand-probe-old-image":
                fail("old application model-backed read failed")
            updated = connection.execute(
                user_account.update()
                .where(user_account.c.id == probe_id)
                .values(username="expand-probe-updated")
            )
            if updated.rowcount != 1:
                fail("old application model-backed update failed")
            deleted = connection.execute(
                user_account.delete().where(user_account.c.id == probe_id)
            )
            if deleted.rowcount != 1:
                fail("old application model-backed delete failed")
            if connection.execute(
                user_account.select().where(user_account.c.id == probe_id)
            ).first() is not None:
                fail("old application model-backed CRUD cleanup failed")
    finally:
        engine.dispose()
    print(json.dumps({
        "schema_version": 1,
        "old_manifest_sha256": OLD_MANIFEST_SHA256,
        "candidate_head": CANDIDATE_HEAD,
        "table_count": len(EXPECTED_TABLES),
        "crud_verified": True,
    }, ensure_ascii=True, separators=(",", ":")))


if __name__ == "__main__":
    run()
'''


def render_expand_old_app_compat_probe(old_manifest, migration_plan):
    validate_migration_manifest(old_manifest)
    validate_expand_migration_plan(migration_plan)
    if (
        candidate_manifest_sha256(old_manifest)
        != migration_plan["old_manifest_sha256"]
        or old_manifest["heads"] != [migration_plan["old_head"]]
    ):
        raise DeployGuardError("old application probe is not bound to the migration plan")
    replacements = {
        "__EXPECTED_TABLES_LITERAL__": repr(
            _canonical_json_key(_manifest_table_identities(old_manifest))
        ),
        "__OLD_MANIFEST_SHA_LITERAL__": repr(
            migration_plan["old_manifest_sha256"]
        ),
        "__CANDIDATE_HEAD_LITERAL__": repr(migration_plan["candidate_head"]),
    }
    source = EXPAND_OLD_APP_COMPAT_TEMPLATE
    if any(source.count(marker) != 1 for marker in replacements):
        raise DeployGuardError("old application compatibility template is invalid")
    for marker, replacement in replacements.items():
        source = source.replace(marker, replacement)
    if any(marker in source for marker in replacements):
        raise DeployGuardError("old application compatibility probe is incomplete")
    compile(source, "EXPAND_OLD_APP_COMPAT.py", "exec")
    return source


def emit_expand_old_app_compat_probe(path, old_manifest, migration_plan):
    write_exclusive_bytes(
        path,
        render_expand_old_app_compat_probe(old_manifest, migration_plan).encode(
            "utf-8"
        ),
    )


def validate_expand_old_app_compat_result(value, old_manifest, migration_plan):
    expected = expected_expand_old_app_compat_result(old_manifest, migration_plan)
    _require_exact_keys(value, EXPAND_OLD_APP_COMPAT_RESULT_KEYS, "old app CRUD result")
    if not exact_json(value, expected):
        raise DeployGuardError("old application CRUD compatibility result is not exact")
    return value


def expected_expand_old_app_compat_result(old_manifest, migration_plan):
    validate_migration_manifest(old_manifest)
    validate_expand_migration_plan(migration_plan)
    if (
        candidate_manifest_sha256(old_manifest)
        != migration_plan["old_manifest_sha256"]
        or old_manifest["heads"] != [migration_plan["old_head"]]
    ):
        raise DeployGuardError(
            "old application CRUD result is not bound to the migration plan"
        )
    return {
        "schema_version": 1,
        "old_manifest_sha256": migration_plan["old_manifest_sha256"],
        "candidate_head": migration_plan["candidate_head"],
        "table_count": len(_manifest_table_identities(old_manifest)),
        "crud_verified": True,
    }


def emit_expected_expand_old_app_compat_result(path, old_manifest, migration_plan):
    value = expected_expand_old_app_compat_result(old_manifest, migration_plan)
    write_exclusive_bytes(
        path,
        (json.dumps(value, ensure_ascii=True, separators=(",", ":")) + "\n").encode(
            "utf-8"
        ),
    )


def load_owner_only_expand_old_app_compat_result(path, old_manifest, migration_plan):
    raw = read_owner_only_bytes(
        path,
        "owner-only old application CRUD compatibility result",
        maximum_bytes=MAX_DATABASE_SCHEMA_RESULT_BYTES,
    )
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise DeployGuardError("old application CRUD result is not valid JSON") from exc
    return validate_expand_old_app_compat_result(
        value,
        old_manifest,
        migration_plan,
    )


def validate_expand_transaction_result(plan, value):
    validate_expand_migration_plan(plan)
    expected = {
        "schema_version": 1,
        "old_head": plan["old_head"],
        "candidate_head": plan["candidate_head"],
        "migration_sha256": plan["migration_sha256"],
        "committed": True,
    }
    if not isinstance(value, dict) or tuple(value) != tuple(expected) or not exact_json(
        value, expected
    ):
        raise DeployGuardError("expand transaction result is not exact")
    return value


def read_expand_migration_source(path):
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
    try:
        descriptor = os.open(os.fspath(path), flags)
    except OSError as exc:
        raise DeployGuardError("cannot open expand migration source") from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.geteuid()
            or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) & 0o022
            or before.st_size <= 0
            or before.st_size > MAX_EXPAND_MIGRATION_SOURCE_BUNDLE_BYTES
        ):
            raise DeployGuardError("expand migration source identity is invalid")
        chunks = []
        total = 0
        while True:
            chunk = os.read(descriptor, 65536)
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        after = os.fstat(descriptor)
        if _owner_only_file_identity(before) != _owner_only_file_identity(after):
            raise DeployGuardError("expand migration source changed while it was read")
        if total != before.st_size:
            raise DeployGuardError("expand migration source size changed")
        payload = b"".join(chunks)
    finally:
        os.close(descriptor)
    try:
        value = json.loads(payload.decode("ascii"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise DeployGuardError(
            "expand migration source bundle is not valid ASCII JSON"
        ) from exc
    _require_exact_keys(
        value,
        EXPAND_MIGRATION_SOURCE_BUNDLE_KEYS,
        "expand migration source bundle",
    )
    migrations = value["migrations"]
    if (
        type(value["schema_version"]) is not int
        or value["schema_version"] != EXPAND_MIGRATION_SOURCE_BUNDLE_SCHEMA_VERSION
        or not isinstance(migrations, list)
        or not migrations
        or len(migrations) > MAX_EXPAND_MIGRATIONS
    ):
        raise DeployGuardError("expand migration source bundle identity is invalid")
    sources = []
    revisions = set()
    for number, migration in enumerate(migrations):
        _require_exact_keys(
            migration,
            EXPAND_MIGRATION_SOURCE_ITEM_KEYS,
            "expand migration source item {0}".format(number),
        )
        revision = migration["revision"]
        digest = migration["sha256"]
        encoded = migration["source_base64"]
        if (
            type(revision) is not str
            or MIGRATION_REVISION.fullmatch(revision) is None
            or revision in revisions
            or type(digest) is not str
            or SHA256_DIGEST.fullmatch(digest) is None
            or type(encoded) is not str
            or not encoded
        ):
            raise DeployGuardError("expand migration source item identity is invalid")
        try:
            source = base64.b64decode(encoded.encode("ascii"), validate=True)
        except (UnicodeError, ValueError) as exc:
            raise DeployGuardError(
                "expand migration source item is not canonical base64"
            ) from exc
        if (
            not source
            or len(source) > MAX_EXPAND_MIGRATION_SOURCE_BYTES
            or base64.b64encode(source).decode("ascii") != encoded
            or hashlib.sha256(source).hexdigest() != digest
        ):
            raise DeployGuardError("expand migration source item digest is invalid")
        revisions.add(revision)
        sources.append(source)
    return sources


def load_owner_only_expand_migration_plan(path):
    raw = read_owner_only_bytes(
        path,
        "owner-only expand migration plan",
        maximum_bytes=MAX_MIGRATION_MANIFEST_BYTES,
    )
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise DeployGuardError("expand migration plan is not valid JSON") from exc
    return validate_expand_migration_plan(value)


def load_owner_only_expand_transaction_result(path, plan):
    raw = read_owner_only_bytes(
        path,
        "owner-only expand transaction result",
        maximum_bytes=MAX_DATABASE_SCHEMA_RESULT_BYTES,
    )
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise DeployGuardError("expand transaction result is not valid JSON") from exc
    return validate_expand_transaction_result(plan, value)


def load_owner_only_expand_approval_plan(path, migration_plan=None):
    raw = read_owner_only_bytes(
        path,
        "owner-only expand approval plan",
        maximum_bytes=MAX_EXPAND_APPROVAL_PLAN_BYTES,
    )
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise DeployGuardError("expand approval plan is not valid JSON") from exc
    return validate_expand_approval_plan(value, migration_plan)


def owner_only_file_sha256(path, label, maximum_bytes, *, require_nonempty=True):
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
    try:
        descriptor = os.open(os.fspath(path), flags)
    except OSError as exc:
        raise DeployGuardError("cannot open {0}".format(label)) from exc
    try:
        before = os.fstat(descriptor)
        _require_owner_only_regular(before, label)
        if (
            (require_nonempty and before.st_size <= 0)
            or before.st_size > maximum_bytes
        ):
            raise DeployGuardError("{0} size is invalid".format(label))
        digest = hashlib.sha256()
        prefix = b""
        total = 0
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            if len(prefix) < 16:
                prefix += chunk[: 16 - len(prefix)]
            digest.update(chunk)
            total += len(chunk)
        after = os.fstat(descriptor)
        _require_owner_only_regular(after, label)
        if (
            _owner_only_file_identity(before) != _owner_only_file_identity(after)
            or total != before.st_size
        ):
            raise DeployGuardError("{0} changed while it was read".format(label))
        return {
            "size": total,
            "sha256": digest.hexdigest(),
            "prefix": prefix,
        }
    finally:
        os.close(descriptor)


def _validate_expand_backup_path(path):
    if (
        type(path) is not str
        or not path.startswith("/")
        or path != os.path.normpath(path)
        or path in ("/", "/.", "/..")
        or any(character in path for character in "\0\n\r")
    ):
        raise DeployGuardError("expand backup path is invalid")
    return path


def attest_expand_backup(backup_path, toc_path):
    backup_path = _validate_expand_backup_path(os.fspath(backup_path))
    backup = owner_only_file_sha256(
        backup_path,
        "owner-only PostgreSQL custom backup",
        MAX_EXPAND_BACKUP_BYTES,
    )
    if backup["prefix"][:5] != b"PGDMP":
        raise DeployGuardError("PostgreSQL backup is not pg_dump custom format")
    toc_payload = read_owner_only_bytes(
        toc_path,
        "owner-only pg_restore table of contents",
        maximum_bytes=MAX_EXPAND_BACKUP_TOC_BYTES,
    )
    if (
        not toc_payload
        or not toc_payload.startswith(b";")
        or b"\0" in toc_payload
        or b"\n" not in toc_payload
        or (b" TABLE " not in toc_payload and b" TABLE DATA " not in toc_payload)
    ):
        raise DeployGuardError("pg_restore table of contents is incomplete")
    return {
        "backup_path": backup_path,
        "backup_size": backup["size"],
        "backup_sha256": backup["sha256"],
        "backup_toc_sha256": hashlib.sha256(toc_payload).hexdigest(),
    }


def validate_expand_backup_attestation(value):
    _require_exact_keys(
        value,
        EXPAND_BACKUP_ATTESTATION_KEYS,
        "expand backup attestation",
    )
    _validate_expand_backup_path(value["backup_path"])
    if (
        type(value["backup_size"]) is not int
        or not 0 < value["backup_size"] <= MAX_EXPAND_BACKUP_BYTES
    ):
        raise DeployGuardError("expand backup size is invalid")
    for key in ("backup_sha256", "backup_toc_sha256"):
        if type(value[key]) is not str or SHA256_DIGEST.fullmatch(value[key]) is None:
            raise DeployGuardError("expand backup digest is invalid")
    return value


def validate_expand_backup_binding(journal, attestation):
    validate_expand_journal(journal)
    validate_expand_backup_attestation(attestation)
    if journal["state"] == "approved":
        raise DeployGuardError("expand backup is not journal-attested yet")
    expected = {
        "backup_path": journal["backup_path"],
        "backup_size": journal["backup_size"],
        "backup_sha256": journal["backup_sha256"],
        "backup_toc_sha256": journal["backup_toc_sha256"],
    }
    if not exact_json(attestation, expected):
        raise DeployGuardError(
            "expand backup bytes or table of contents changed after attestation"
        )
    return attestation


def _expand_decimal_output(payload, label):
    if type(payload) is not str or len(payload.encode("utf-8")) > (
        MAX_EXPAND_RESTORE_CAPACITY_OUTPUT_BYTES
    ):
        raise DeployGuardError("{0} output is invalid".format(label))
    lines = [line.strip() for line in payload.splitlines() if line.strip()]
    if len(lines) != 1 or re.fullmatch(r"[0-9]+", lines[0]) is None:
        raise DeployGuardError("{0} output is not one decimal value".format(label))
    value = int(lines[0])
    if not 0 < value <= MAX_EXPAND_RESTORE_DATABASE_BYTES:
        raise DeployGuardError("{0} value is outside the approved range".format(label))
    return value


def _expand_restore_available_bytes(payload):
    if type(payload) is not str or len(payload.encode("utf-8")) > (
        MAX_EXPAND_RESTORE_CAPACITY_OUTPUT_BYTES
    ):
        raise DeployGuardError("restore volume capacity output is invalid")
    lines = [line.strip() for line in payload.splitlines() if line.strip()]
    if len(lines) != 1:
        raise DeployGuardError("restore volume stat output is ambiguous")
    fields = lines[0].split()
    if len(fields) != 2 or any(
        re.fullmatch(r"[0-9]+", field) is None for field in fields
    ):
        raise DeployGuardError("restore volume stat record is invalid")
    available_blocks, block_size = (int(field) for field in fields)
    if (
        available_blocks <= 0
        or block_size < 512
        or block_size > 65536
        or block_size & (block_size - 1)
    ):
        raise DeployGuardError("restore volume stat values are invalid")
    available = available_blocks * block_size
    if not 0 < available <= MAX_EXPAND_RESTORE_DATABASE_BYTES:
        raise DeployGuardError("restore volume available capacity is invalid")
    return available


def validate_expand_restore_volume_attestation(value):
    _require_exact_keys(
        value,
        EXPAND_RESTORE_VOLUME_ATTESTATION_KEYS,
        "expand restore volume attestation",
    )
    if (
        type(value["schema_version"]) is not int
        or value["schema_version"]
        != EXPAND_RESTORE_VOLUME_ATTESTATION_SCHEMA_VERSION
        or type(value["volume_name"]) is not str
        or RESTORE_VOLUME_NAME.fullmatch(value["volume_name"]) is None
        or type(value["expected_main_sha"]) is not str
        or REVISION.fullmatch(value["expected_main_sha"]) is None
        or type(value["run_id"]) is not str
        or DEPLOY_RUN_ID.fullmatch(value["run_id"]) is None
        or type(value["database_probe_image_id"]) is not str
        or IMAGE_ID.fullmatch(value["database_probe_image_id"]) is None
    ):
        raise DeployGuardError("expand restore volume execution identity is invalid")
    if value["volume_name"] != deployment_name(
        value["run_id"], RESTORE_VOLUME_ROLE
    ):
        raise DeployGuardError("expand restore volume name/run identity differs")
    for key in ("backup_sha256", "volume_identity_sha256"):
        if type(value[key]) is not str or SHA256_DIGEST.fullmatch(value[key]) is None:
            raise DeployGuardError(
                "expand restore volume {0} is invalid".format(key)
            )
    for key in (
        "backup_size",
        "database_size_bytes",
        "required_bytes",
        "available_bytes",
    ):
        if (
            type(value[key]) is not int
            or not 0 < value[key] <= MAX_EXPAND_RESTORE_DATABASE_BYTES
        ):
            raise DeployGuardError(
                "expand restore volume {0} is invalid".format(key)
            )
    expected_required = (
        value["database_size_bytes"] * EXPAND_RESTORE_CAPACITY_MULTIPLIER
        + MIN_EXPAND_RESTORE_HEADROOM_BYTES
    )
    if (
        expected_required > MAX_EXPAND_RESTORE_DATABASE_BYTES
        or value["required_bytes"] != expected_required
        or value["available_bytes"] < value["required_bytes"]
    ):
        raise DeployGuardError("expand restore volume capacity is insufficient")
    return value


def build_expand_restore_volume_attestation(
    volume_inspect,
    database_size_output,
    capacity_output,
    backup_attestation,
    expected_main_sha,
    run_id,
    database_probe_image_id,
):
    validate_expand_backup_attestation(backup_attestation)
    expected_name = deployment_name(run_id, RESTORE_VOLUME_ROLE)
    identity = validate_restore_volume_inspect(
        volume_inspect,
        expected_name,
        expected_main_sha,
        run_id,
        database_probe_image_id,
    )
    database_size = _expand_decimal_output(
        database_size_output,
        "production database size",
    )
    available = _expand_restore_available_bytes(capacity_output)
    required = (
        database_size * EXPAND_RESTORE_CAPACITY_MULTIPLIER
        + MIN_EXPAND_RESTORE_HEADROOM_BYTES
    )
    value = {
        "schema_version": EXPAND_RESTORE_VOLUME_ATTESTATION_SCHEMA_VERSION,
        "volume_name": expected_name,
        "expected_main_sha": expected_main_sha,
        "run_id": run_id,
        "database_probe_image_id": database_probe_image_id,
        "backup_sha256": backup_attestation["backup_sha256"],
        "backup_size": backup_attestation["backup_size"],
        "database_size_bytes": database_size,
        "required_bytes": required,
        "available_bytes": available,
        "volume_identity_sha256": restore_volume_identity_sha256(identity),
    }
    return validate_expand_restore_volume_attestation(value)


def load_owner_only_expand_restore_volume_attestation(path):
    raw = read_owner_only_bytes(
        path,
        "owner-only expand restore volume attestation",
        maximum_bytes=MAX_EXPAND_EVIDENCE_BYTES,
    )
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise DeployGuardError("expand restore volume attestation JSON is invalid") from exc
    return validate_expand_restore_volume_attestation(value)


def validate_expand_journal(value):
    _require_exact_keys(value, EXPAND_JOURNAL_KEYS, "expand migration journal")
    if (
        type(value["schema_version"]) is not int
        or value["schema_version"] != EXPAND_JOURNAL_SCHEMA_VERSION
        or value["state"] not in EXPAND_JOURNAL_STATES
    ):
        raise DeployGuardError("expand migration journal state is invalid")
    if (
        type(value["expected_main_sha"]) is not str
        or GIT_OBJECT_ID.fullmatch(value["expected_main_sha"]) is None
    ):
        raise DeployGuardError("expand migration journal main SHA is invalid")
    for key in (
        "trusted_bundle_sha256",
        "approval_sha256",
        "plan_sha256",
        "old_manifest_sha256",
        "candidate_manifest_sha256",
        "migration_sha256",
        "operation_policy_sha256",
        "old_catalog_sha256",
        "candidate_catalog_sha256",
    ):
        if type(value[key]) is not str or SHA256_DIGEST.fullmatch(value[key]) is None:
            raise DeployGuardError(
                "expand migration journal {0} is invalid".format(key)
            )
    for key in ("old_head", "candidate_head"):
        if type(value[key]) is not str or MIGRATION_REVISION.fullmatch(value[key]) is None:
            raise DeployGuardError(
                "expand migration journal {0} is invalid".format(key)
            )
    if value["old_head"] == value["candidate_head"]:
        raise DeployGuardError("expand migration journal heads must differ")
    _validate_expand_backup_path(value["backup_path"])
    backup_values = (
        value["backup_size"],
        value["backup_sha256"],
        value["backup_toc_sha256"],
    )
    if value["state"] == "approved":
        if any(item is not None for item in backup_values):
            raise DeployGuardError(
                "approved expand migration journal already claims a backup"
            )
    else:
        validate_expand_backup_attestation(
            {
                "backup_path": value["backup_path"],
                "backup_size": value["backup_size"],
                "backup_sha256": value["backup_sha256"],
                "backup_toc_sha256": value["backup_toc_sha256"],
            }
        )
    restore_values = (
        value["restore_volume_name"],
        value["restore_volume_identity_sha256"],
        value["restore_database_size_bytes"],
        value["restore_required_bytes"],
        value["restore_available_bytes"],
    )
    if value["state"] in ("approved", "backup_verified"):
        if any(item is not None for item in restore_values):
            raise DeployGuardError(
                "expand migration journal claims an unverified restore volume"
            )
    else:
        if (
            type(value["restore_volume_name"]) is not str
            or RESTORE_VOLUME_NAME.fullmatch(value["restore_volume_name"]) is None
            or type(value["restore_volume_identity_sha256"]) is not str
            or SHA256_DIGEST.fullmatch(
                value["restore_volume_identity_sha256"]
            )
            is None
        ):
            raise DeployGuardError(
                "expand migration journal restore volume identity is invalid"
            )
        for key in (
            "restore_database_size_bytes",
            "restore_required_bytes",
            "restore_available_bytes",
        ):
            if (
                type(value[key]) is not int
                or not 0 < value[key] <= MAX_EXPAND_RESTORE_DATABASE_BYTES
            ):
                raise DeployGuardError(
                    "expand migration journal {0} is invalid".format(key)
                )
        expected_required = (
            value["restore_database_size_bytes"]
            * EXPAND_RESTORE_CAPACITY_MULTIPLIER
            + MIN_EXPAND_RESTORE_HEADROOM_BYTES
        )
        if (
            value["restore_required_bytes"] != expected_required
            or value["restore_available_bytes"] < value["restore_required_bytes"]
        ):
            raise DeployGuardError(
                "expand migration journal restore capacity is insufficient"
            )
    for key in ("old_image_id", "candidate_image_id"):
        if type(value[key]) is not str or IMAGE_ID.fullmatch(value[key]) is None:
            raise DeployGuardError(
                "expand migration journal {0} is invalid".format(key)
            )
    if value["old_image_id"] == value["candidate_image_id"]:
        raise DeployGuardError("expand migration journal image IDs must differ")
    return value


def build_expand_journal(
    approval_plan,
    approval_sha256,
    migration_plan,
    backup_path,
    old_image_id,
    candidate_image_id,
):
    validate_expand_approval_plan(approval_plan, migration_plan)
    if type(approval_sha256) is not str or SHA256_DIGEST.fullmatch(approval_sha256) is None:
        raise DeployGuardError("expand approval SHA-256 is invalid")
    value = {
        "schema_version": EXPAND_JOURNAL_SCHEMA_VERSION,
        "state": "approved",
        "expected_main_sha": approval_plan["expected_main_sha"],
        "trusted_bundle_sha256": approval_plan["trusted_bundle_sha256"],
        "approval_sha256": approval_sha256,
        "plan_sha256": expand_migration_plan_sha256(migration_plan),
        "old_head": approval_plan["old_head"],
        "candidate_head": approval_plan["candidate_head"],
        "old_manifest_sha256": approval_plan["old_manifest_sha256"],
        "candidate_manifest_sha256": approval_plan["candidate_manifest_sha256"],
        "migration_sha256": approval_plan["migration_sha256"],
        "operation_policy_sha256": approval_plan["operation_policy_sha256"],
        "old_catalog_sha256": approval_plan["old_catalog_sha256"],
        "candidate_catalog_sha256": approval_plan["candidate_catalog_sha256"],
        "backup_path": _validate_expand_backup_path(os.fspath(backup_path)),
        "backup_size": None,
        "backup_sha256": None,
        "backup_toc_sha256": None,
        "restore_volume_name": None,
        "restore_volume_identity_sha256": None,
        "restore_database_size_bytes": None,
        "restore_required_bytes": None,
        "restore_available_bytes": None,
        "old_image_id": old_image_id,
        "candidate_image_id": candidate_image_id,
    }
    return validate_expand_journal(value)


def load_expand_journal(path):
    raw = read_owner_only_bytes(
        path,
        "expand migration journal",
        maximum_bytes=MAX_EXPAND_JOURNAL_BYTES,
    )
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise DeployGuardError("expand migration journal JSON is invalid") from exc
    return validate_expand_journal(value)


def _validate_expand_journal_transition(previous, candidate):
    validate_expand_journal(candidate)
    if previous is None:
        if candidate["state"] != EXPAND_JOURNAL_STATES[0]:
            raise DeployGuardError("expand migration journal must begin at approved")
        return
    validate_expand_journal(previous)
    previous_index = EXPAND_JOURNAL_STATES.index(previous["state"])
    candidate_index = EXPAND_JOURNAL_STATES.index(candidate["state"])
    if candidate_index == previous_index:
        if not exact_json(previous, candidate):
            raise DeployGuardError("expand migration journal idempotent state changed")
        return
    if candidate_index != previous_index + 1:
        raise DeployGuardError("expand migration journal state transition is invalid")
    mutable = {"state"}
    if previous["state"] == "approved" and candidate["state"] == "backup_verified":
        mutable.update(("backup_size", "backup_sha256", "backup_toc_sha256"))
    if (
        previous["state"] == "backup_verified"
        and candidate["state"] == "restore_verified"
    ):
        mutable.update(
            (
                "restore_volume_name",
                "restore_volume_identity_sha256",
                "restore_database_size_bytes",
                "restore_required_bytes",
                "restore_available_bytes",
            )
        )
    for key in EXPAND_JOURNAL_KEYS:
        if key in ("schema_version", *mutable):
            continue
        if not exact_json(previous[key], candidate[key]):
            raise DeployGuardError(
                "expand migration journal identity changed during transition"
            )


def _replace_owner_only_json(path, value, label):
    body = (json.dumps(value, ensure_ascii=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )
    parent_descriptor, name = _open_safe_output_parent(path)
    temporary_name = ".{0}.tmp.{1}".format(name, secrets.token_hex(16))
    descriptor = None
    created = False
    try:
        descriptor = os.open(
            temporary_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
            0o600,
            dir_fd=parent_descriptor,
        )
        created = True
        os.fchmod(descriptor, 0o600)
        _require_owner_only_regular(os.fstat(descriptor), label + " temporary file")
        _write_all(descriptor, body)
        os.fsync(descriptor)
        _require_owner_only_regular(os.fstat(descriptor), label + " temporary file")
        os.close(descriptor)
        descriptor = None
        os.rename(
            temporary_name,
            name,
            src_dir_fd=parent_descriptor,
            dst_dir_fd=parent_descriptor,
        )
        created = False
        os.fsync(parent_descriptor)
    except OSError as exc:
        raise DeployGuardError("cannot replace {0}".format(label)) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if created:
            try:
                os.unlink(temporary_name, dir_fd=parent_descriptor)
            except OSError:
                pass
        os.close(parent_descriptor)


def write_expand_journal(path, candidate):
    validate_expand_journal(candidate)
    try:
        previous = load_expand_journal(path)
    except DeployGuardError:
        try:
            os.lstat(path)
        except FileNotFoundError:
            previous = None
        else:
            raise
    _validate_expand_journal_transition(previous, candidate)
    _replace_owner_only_json(path, candidate, "expand migration journal")


def advance_expand_journal(
    path,
    state,
    backup_attestation=None,
    restore_volume_attestation=None,
):
    previous = load_expand_journal(path)
    candidate = dict(previous)
    candidate["state"] = state
    if backup_attestation is not None:
        validate_expand_backup_attestation(backup_attestation)
        if backup_attestation["backup_path"] != previous["backup_path"]:
            raise DeployGuardError("expand backup path changed after approval")
        for key in ("backup_size", "backup_sha256", "backup_toc_sha256"):
            candidate[key] = backup_attestation[key]
    if restore_volume_attestation is not None:
        validate_expand_restore_volume_attestation(restore_volume_attestation)
        if (
            previous["state"] != "backup_verified"
            or state != "restore_verified"
            or restore_volume_attestation["expected_main_sha"]
            != previous["expected_main_sha"]
            or restore_volume_attestation["backup_sha256"]
            != previous["backup_sha256"]
            or restore_volume_attestation["backup_size"]
            != previous["backup_size"]
        ):
            raise DeployGuardError(
                "restore volume attestation is not bound to the journal backup"
            )
        candidate.update(
            {
                "restore_volume_name": restore_volume_attestation["volume_name"],
                "restore_volume_identity_sha256": restore_volume_attestation[
                    "volume_identity_sha256"
                ],
                "restore_database_size_bytes": restore_volume_attestation[
                    "database_size_bytes"
                ],
                "restore_required_bytes": restore_volume_attestation[
                    "required_bytes"
                ],
                "restore_available_bytes": restore_volume_attestation[
                    "available_bytes"
                ],
            }
        )
    write_expand_journal(path, candidate)
    return candidate


def validate_expand_journal_binding(
    journal,
    approval_plan,
    approval_sha256,
    migration_plan,
    backup_path,
    old_image_id,
    candidate_image_id,
):
    validate_expand_journal(journal)
    expected = build_expand_journal(
        approval_plan,
        approval_sha256,
        migration_plan,
        backup_path,
        old_image_id,
        candidate_image_id,
    )
    mutable = {
        "state",
        "backup_size",
        "backup_sha256",
        "backup_toc_sha256",
        "restore_volume_name",
        "restore_volume_identity_sha256",
        "restore_database_size_bytes",
        "restore_required_bytes",
        "restore_available_bytes",
    }
    if any(
        key not in mutable and not exact_json(journal[key], expected[key])
        for key in EXPAND_JOURNAL_KEYS
    ):
        raise DeployGuardError(
            "existing expand migration journal is bound to another release"
        )
    return journal


def emitted_expand_journal_values(journal):
    validate_expand_journal(journal)
    return [
        journal["state"],
        journal["backup_path"],
        "" if journal["backup_size"] is None else str(journal["backup_size"]),
        journal["backup_sha256"] or "none",
        journal["backup_toc_sha256"] or "none",
    ]


def parse_expand_observed_head(payload, migration_plan):
    validate_expand_migration_plan(migration_plan)
    if type(payload) is not str:
        raise DeployGuardError("expand observed head output is invalid")
    revisions = ALEMBIC_REVISION.findall(payload)
    if revisions:
        if len(revisions) != 1:
            raise DeployGuardError("production database has multiple Alembic revisions")
        observed = revisions[0]
    else:
        lines = [line.strip() for line in payload.splitlines() if line.strip()]
        if len(lines) != 1:
            raise DeployGuardError("production database head output is ambiguous")
        observed = lines[0]
    if observed not in (
        migration_plan["old_head"],
        migration_plan["candidate_head"],
    ):
        raise DeployGuardError("production database head is outside the expand plan")
    return observed


def plan_expand_recovery_catalog(
    journal,
    observed_head,
    observed_manifest,
    observed_catalog,
):
    validate_expand_journal(journal)
    validate_migration_manifest(observed_manifest)
    validate_reference_catalog(observed_manifest, observed_catalog)
    expected_manifest_digest = (
        journal["old_manifest_sha256"]
        if observed_head == journal["old_head"]
        else journal["candidate_manifest_sha256"]
        if observed_head == journal["candidate_head"]
        else None
    )
    if (
        expected_manifest_digest is None
        or candidate_manifest_sha256(observed_manifest) != expected_manifest_digest
    ):
        raise DeployGuardError(
            "expand recovery catalog uses the wrong schema manifest"
        )
    return plan_expand_recovery(
        journal,
        observed_head,
        reference_catalog_sha256(observed_catalog),
    )


def reset_unverified_expand_backup(journal_path):
    journal = load_expand_journal(journal_path)
    if journal["state"] != "approved":
        raise DeployGuardError("only an unverified expand backup may be reset")
    backup_path = journal["backup_path"]
    try:
        descriptor = os.open(
            backup_path,
            os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
        )
    except FileNotFoundError:
        return
    except OSError as exc:
        raise DeployGuardError("cannot open unverified expand backup") from exc
    try:
        metadata = os.fstat(descriptor)
        _require_owner_only_regular(metadata, "unverified expand backup")
    finally:
        os.close(descriptor)
    current = os.lstat(backup_path)
    if _owner_only_file_identity(current) != _owner_only_file_identity(metadata):
        raise DeployGuardError("unverified expand backup changed before reset")
    parent_descriptor, name = _open_safe_output_parent(backup_path)
    try:
        current = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
        if _owner_only_file_identity(current) != _owner_only_file_identity(metadata):
            raise DeployGuardError("unverified expand backup changed before reset")
        try:
            os.unlink(name, dir_fd=parent_descriptor)
            os.fsync(parent_descriptor)
        except OSError as exc:
            raise DeployGuardError("cannot reset unverified expand backup") from exc
    finally:
        os.close(parent_descriptor)


def expected_expand_transaction_result(plan):
    validate_expand_migration_plan(plan)
    return {
        "schema_version": 1,
        "old_head": plan["old_head"],
        "candidate_head": plan["candidate_head"],
        "migration_sha256": plan["migration_sha256"],
        "committed": True,
    }


def emit_expected_expand_transaction_result(path, plan):
    value = expected_expand_transaction_result(plan)
    write_exclusive_bytes(
        path,
        (json.dumps(value, ensure_ascii=True, separators=(",", ":")) + "\n").encode(
            "utf-8"
        ),
    )


def plan_expand_recovery(journal, observed_head, observed_catalog_sha256):
    validate_expand_journal(journal)
    if (
        type(observed_head) is not str
        or MIGRATION_REVISION.fullmatch(observed_head) is None
        or type(observed_catalog_sha256) is not str
        or SHA256_DIGEST.fullmatch(observed_catalog_sha256) is None
    ):
        raise DeployGuardError("expand recovery observation is invalid")
    observed_old = (
        observed_head == journal["old_head"]
        and observed_catalog_sha256 == journal["old_catalog_sha256"]
    )
    observed_candidate = (
        observed_head == journal["candidate_head"]
        and observed_catalog_sha256 == journal["candidate_catalog_sha256"]
    )
    state = journal["state"]
    if state in ("approved", "backup_verified", "restore_verified"):
        if not observed_old:
            raise DeployGuardError(
                "expand recovery found schema mutation before the production transaction"
            )
        return {
            "approved": "resume_backup",
            "backup_verified": "resume_restore_rehearsal",
            "restore_verified": "start_transaction",
        }[state]
    if state == "production_transaction_started":
        if observed_old:
            return "retry_transaction"
        if observed_candidate:
            return "resume_post_transaction_attestation"
        raise DeployGuardError(
            "expand transaction recovery found a partial or unrelated schema state"
        )
    if not observed_candidate:
        raise DeployGuardError(
            "expand recovery lost the exact committed candidate schema"
        )
    return {
        "production_schema_attested": "resume_cutover",
        "cutover_started": "resume_cutover",
        "completed": "complete",
    }[state]


def clear_expand_journal(path):
    parent_descriptor, name = _open_safe_output_parent(path)
    try:
        load_expand_journal(path)
        try:
            os.unlink(name, dir_fd=parent_descriptor)
            os.fsync(parent_descriptor)
        except OSError as exc:
            raise DeployGuardError("cannot clear expand migration journal") from exc
    finally:
        os.close(parent_descriptor)


def build_expand_evidence(
    journal,
    migration_plan,
    rehearsal_transaction_result_sha256,
    old_app_compat_result_sha256,
    transaction_result_sha256,
    post_catalog_sha256,
):
    validate_expand_journal(journal)
    validate_expand_migration_plan(migration_plan)
    if journal["state"] not in ("cutover_started", "completed"):
        raise DeployGuardError(
            "expand evidence requires an attested cutover journal state"
        )
    if journal["plan_sha256"] != expand_migration_plan_sha256(migration_plan):
        raise DeployGuardError("expand evidence migration plan differs from the journal")
    for value, label in (
        (rehearsal_transaction_result_sha256, "rehearsal transaction result"),
        (old_app_compat_result_sha256, "old application CRUD result"),
        (transaction_result_sha256, "transaction result"),
        (post_catalog_sha256, "post-migration catalog"),
    ):
        if type(value) is not str or SHA256_DIGEST.fullmatch(value) is None:
            raise DeployGuardError("expand evidence {0} digest is invalid".format(label))
    if post_catalog_sha256 != journal["candidate_catalog_sha256"]:
        raise DeployGuardError("expand evidence post-migration catalog is not exact")
    value = {
        "schema_version": EXPAND_EVIDENCE_SCHEMA_VERSION,
        "expected_main_sha": journal["expected_main_sha"],
        "trusted_bundle_sha256": journal["trusted_bundle_sha256"],
        "approval_sha256": journal["approval_sha256"],
        "plan_sha256": journal["plan_sha256"],
        "old_head": journal["old_head"],
        "candidate_head": journal["candidate_head"],
        "old_manifest_sha256": journal["old_manifest_sha256"],
        "candidate_manifest_sha256": journal["candidate_manifest_sha256"],
        "migration_sha256": journal["migration_sha256"],
        "operation_policy_sha256": journal["operation_policy_sha256"],
        "old_catalog_sha256": journal["old_catalog_sha256"],
        "candidate_catalog_sha256": journal["candidate_catalog_sha256"],
        "backup_size": journal["backup_size"],
        "backup_sha256": journal["backup_sha256"],
        "backup_toc_sha256": journal["backup_toc_sha256"],
        "restore_volume_name": journal["restore_volume_name"],
        "restore_volume_identity_sha256": journal[
            "restore_volume_identity_sha256"
        ],
        "restore_database_size_bytes": journal[
            "restore_database_size_bytes"
        ],
        "restore_required_bytes": journal["restore_required_bytes"],
        "restore_available_bytes": journal["restore_available_bytes"],
        "old_image_id": journal["old_image_id"],
        "candidate_image_id": journal["candidate_image_id"],
        "rehearsal_transaction_result_sha256": (
            rehearsal_transaction_result_sha256
        ),
        "old_app_compat_result_sha256": old_app_compat_result_sha256,
        "transaction_result_sha256": transaction_result_sha256,
        "post_catalog_sha256": post_catalog_sha256,
    }
    _require_exact_keys(value, EXPAND_EVIDENCE_KEYS, "expand migration evidence")
    return value


def write_expand_evidence(path, value):
    _require_exact_keys(value, EXPAND_EVIDENCE_KEYS, "expand migration evidence")
    payload = (json.dumps(value, ensure_ascii=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )
    if len(payload) > MAX_EXPAND_EVIDENCE_BYTES:
        raise DeployGuardError("expand migration evidence is too large")
    write_exclusive_bytes(path, payload)


def validate_expand_evidence(value, expected):
    _require_exact_keys(value, EXPAND_EVIDENCE_KEYS, "expand migration evidence")
    _require_exact_keys(expected, EXPAND_EVIDENCE_KEYS, "expected expand evidence")
    if not exact_json(value, expected):
        raise DeployGuardError(
            "existing expand migration evidence differs from the exact release"
        )
    return value


def load_owner_only_expand_evidence(path, expected):
    raw = read_owner_only_bytes(
        path,
        "owner-only expand migration evidence",
        maximum_bytes=MAX_EXPAND_EVIDENCE_BYTES,
    )
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise DeployGuardError("expand migration evidence JSON is invalid") from exc
    return validate_expand_evidence(value, expected)


def _owner_only_text(path, label, maximum_bytes):
    payload = read_owner_only_bytes(path, label, maximum_bytes=maximum_bytes)
    try:
        return payload.decode("utf-8")
    except UnicodeError as exc:
        raise DeployGuardError("{0} is not UTF-8".format(label)) from exc


def load_owner_only_migration_manifest(path, label):
    text = _owner_only_text(path, label, MAX_MIGRATION_MANIFEST_BYTES)
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DeployGuardError("{0} is not valid JSON".format(label)) from exc
    return validate_migration_manifest(value)


def load_owner_only_reference_catalog(path, candidate_manifest):
    text = _owner_only_text(
        path,
        "owner-only reference schema catalog",
        MAX_REFERENCE_CATALOG_BYTES,
    )
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DeployGuardError(
            "owner-only reference schema catalog is not valid JSON"
        ) from exc
    return validate_reference_catalog(candidate_manifest, value)


def validate_reference_materializer_result(candidate_manifest, value):
    table_count = len(_manifest_table_identities(candidate_manifest))
    if table_count != REFERENCE_SCHEMA_TABLE_COUNT:
        raise DeployGuardError("candidate reference table count is not pinned")
    expected = {
        "schema_version": MODEL_CATALOG_SCHEMA_VERSION,
        "candidate_manifest_sha256": candidate_manifest_sha256(candidate_manifest),
        "table_count": REFERENCE_SCHEMA_TABLE_COUNT,
    }
    if not isinstance(value, dict) or not exact_json(value, expected):
        raise DeployGuardError(
            "reference schema materializer result is not exactly bound to the candidate"
        )
    return value


def validate_expand_reference_materializer_result(candidate_manifest, value):
    table_count = len(_manifest_table_identities(candidate_manifest))
    expected = {
        "schema_version": MODEL_CATALOG_SCHEMA_VERSION,
        "candidate_manifest_sha256": candidate_manifest_sha256(candidate_manifest),
        "table_count": table_count,
    }
    if not isinstance(value, dict) or not exact_json(value, expected):
        raise DeployGuardError(
            "expand reference materializer result is not exactly bound to its manifest"
        )
    return value


def load_owner_only_reference_materializer_result(path, candidate_manifest):
    text = _owner_only_text(
        path,
        "owner-only reference schema materializer result",
        MAX_REFERENCE_MATERIALIZER_RESULT_BYTES,
    )
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DeployGuardError(
            "reference schema materializer result is not one JSON object"
        ) from exc
    return validate_reference_materializer_result(candidate_manifest, value)


def load_owner_only_expand_reference_materializer_result(path, candidate_manifest):
    text = _owner_only_text(
        path,
        "owner-only expand reference schema materializer result",
        MAX_REFERENCE_MATERIALIZER_RESULT_BYTES,
    )
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DeployGuardError(
            "expand reference schema materializer result is not one JSON object"
        ) from exc
    return validate_expand_reference_materializer_result(candidate_manifest, value)


def load_owner_only_database_schema_result(path):
    text = _owner_only_text(
        path,
        "owner-only database schema result",
        MAX_DATABASE_SCHEMA_RESULT_BYTES,
    )
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DeployGuardError(
            "owner-only database schema result is not valid JSON"
        ) from exc
    return value


def revision_set(text, label):
    values = set(ALEMBIC_REVISION.findall(text))
    if not values:
        raise DeployGuardError("{0} did not expose an Alembic revision".format(label))
    return values


def validate_migration_outputs(heads_text, current_text):
    heads = revision_set(heads_text, "alembic heads")
    current = revision_set(current_text, "alembic current")
    if current != heads:
        raise DeployGuardError("database revisions do not exactly equal Alembic heads")
    return sorted(heads)


def validate_journal(payload):
    if not isinstance(payload, dict) or tuple(payload) != JOURNAL_KEYS:
        raise DeployGuardError("deployment journal keys/order are invalid")
    if type(payload["schema_version"]) is not int or payload["schema_version"] != JOURNAL_SCHEMA_VERSION:
        raise DeployGuardError("deployment journal schema is invalid")
    if payload["state"] not in JOURNAL_STATES:
        raise DeployGuardError("deployment journal state is invalid")
    if not isinstance(payload["expected_sha"], str) or REVISION.fullmatch(
        payload["expected_sha"]
    ) is None:
        raise DeployGuardError("deployment journal expected SHA is invalid")
    if (
        type(payload["trusted_bundle_sha256"]) is not str
        or SHA256_DIGEST.fullmatch(payload["trusted_bundle_sha256"]) is None
    ):
        raise DeployGuardError("deployment journal trusted bundle digest is invalid")
    if payload["container_name"] != PINNED_SPEC["container_name"]:
        raise DeployGuardError("deployment journal container name is invalid")
    for key in ("backup_name", "candidate_name"):
        value = payload[key]
        if (
            not isinstance(value, str)
            or CONTAINER_NAME.fullmatch(value) is None
            or not value.startswith(PINNED_SPEC["container_name"] + "-")
        ):
            raise DeployGuardError("deployment journal {0} is invalid".format(key))
    if payload["backup_name"] == payload["candidate_name"]:
        raise DeployGuardError("deployment journal container names must differ")
    for key in ("old_container_id", "candidate_container_id"):
        value = payload[key]
        if not isinstance(value, str) or CONTAINER_ID.fullmatch(value) is None:
            raise DeployGuardError("deployment journal {0} is invalid".format(key))
    for key in ("old_image_id", "candidate_image_id"):
        value = payload[key]
        if not isinstance(value, str) or IMAGE_ID.fullmatch(value) is None:
            raise DeployGuardError("deployment journal {0} is invalid".format(key))
    if payload["old_container_id"] == payload["candidate_container_id"]:
        raise DeployGuardError("deployment journal container IDs must differ")
    if payload["old_image_id"] == payload["candidate_image_id"]:
        raise DeployGuardError("deployment journal image IDs must differ")
    return payload


def load_journal(path):
    raw = read_owner_only_bytes(path, "deployment journal", maximum_bytes=65536)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise DeployGuardError("deployment journal JSON is invalid") from exc
    return validate_journal(payload)


def _validate_journal_transition(previous, candidate):
    if previous is None:
        if candidate["state"] != JOURNAL_STATES[0]:
            raise DeployGuardError("deployment journal must begin at prepared")
        return
    immutable_keys = tuple(key for key in JOURNAL_KEYS if key not in ("schema_version", "state"))
    if any(not exact_json(previous[key], candidate[key]) for key in immutable_keys):
        raise DeployGuardError("deployment journal identity changed during transition")
    previous_index = JOURNAL_STATES.index(previous["state"])
    candidate_index = JOURNAL_STATES.index(candidate["state"])
    if candidate_index == previous_index:
        if not exact_json(previous, candidate):
            raise DeployGuardError("deployment journal idempotent state changed")
        return
    if candidate_index != previous_index + 1:
        raise DeployGuardError("deployment journal state transition is invalid")


def write_journal(path, payload):
    validate_journal(payload)
    parent_descriptor, name = _open_safe_output_parent(path)
    previous = None
    try:
        try:
            existing_descriptor = os.open(
                name,
                os.O_RDONLY
                | os.O_CLOEXEC
                | os.O_NOFOLLOW,
                dir_fd=parent_descriptor,
            )
        except FileNotFoundError:
            existing_descriptor = None
        except OSError as exc:
            raise DeployGuardError("cannot open deployment journal") from exc
        if existing_descriptor is not None:
            os.close(existing_descriptor)
            previous = load_journal(path)
        _validate_journal_transition(previous, payload)
        body = (json.dumps(payload, ensure_ascii=True, separators=(",", ":")) + "\n").encode(
            "utf-8"
        )
        temporary_name = ".{0}.tmp.{1}".format(name, secrets.token_hex(16))
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= os.O_CLOEXEC | os.O_NOFOLLOW
        temporary_descriptor = None
        temporary_created = False
        try:
            temporary_descriptor = os.open(
                temporary_name,
                flags,
                0o600,
                dir_fd=parent_descriptor,
            )
            temporary_created = True
            os.fchmod(temporary_descriptor, 0o600)
            _require_owner_only_regular(
                os.fstat(temporary_descriptor), "deployment journal temporary file"
            )
            _write_all(temporary_descriptor, body)
            os.fsync(temporary_descriptor)
            _require_owner_only_regular(
                os.fstat(temporary_descriptor), "deployment journal temporary file"
            )
            os.close(temporary_descriptor)
            temporary_descriptor = None
            os.replace(
                temporary_name,
                name,
                src_dir_fd=parent_descriptor,
                dst_dir_fd=parent_descriptor,
            )
            temporary_created = False
            os.fsync(parent_descriptor)
        except OSError as exc:
            raise DeployGuardError("cannot persist deployment journal") from exc
        finally:
            if temporary_descriptor is not None:
                os.close(temporary_descriptor)
            if temporary_created:
                try:
                    os.unlink(temporary_name, dir_fd=parent_descriptor)
                except OSError:
                    pass
    finally:
        os.close(parent_descriptor)
    persisted = load_journal(path)
    if not exact_json(persisted, payload):
        raise DeployGuardError("persisted deployment journal differs from requested state")


def emitted_journal_values(payload):
    validate_journal(payload)
    return [payload[key] for key in EMITTED_JOURNAL_KEYS]


def _recovery_container(payload, expected_name, label):
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise DeployGuardError("{0} recovery inspect is invalid".format(label))
    container_id = payload.get("Id")
    image_id = payload.get("Image")
    name = payload.get("Name")
    state = payload.get("State")
    if not isinstance(container_id, str) or CONTAINER_ID.fullmatch(container_id) is None:
        raise DeployGuardError("{0} recovery container ID is invalid".format(label))
    if not isinstance(image_id, str) or IMAGE_ID.fullmatch(image_id) is None:
        raise DeployGuardError("{0} recovery image ID is invalid".format(label))
    if name != "/" + expected_name:
        raise DeployGuardError("{0} recovery container name is invalid".format(label))
    if not isinstance(state, dict) or type(state.get("Running")) is not bool:
        raise DeployGuardError("{0} recovery Running state is invalid".format(label))
    return {
        "container_id": container_id,
        "image_id": image_id,
        "running": state["Running"],
    }


def plan_recovery(journal, official=None, backup=None, named_candidate=None):
    validate_journal(journal)
    official_identity = _recovery_container(
        official, journal["container_name"], "official"
    )
    backup_identity = _recovery_container(backup, journal["backup_name"], "backup")
    candidate_identity = _recovery_container(
        named_candidate, journal["candidate_name"], "named candidate"
    )
    identities = [
        item["container_id"]
        for item in (official_identity, backup_identity, candidate_identity)
        if item is not None
    ]
    if len(identities) != len(set(identities)):
        raise DeployGuardError("recovery inspect container identities overlap")

    old_identity = (journal["old_container_id"], journal["old_image_id"])
    new_identity = (
        journal["candidate_container_id"],
        journal["candidate_image_id"],
    )

    def role(identity):
        if identity is None:
            return None
        value = (identity["container_id"], identity["image_id"])
        if value == old_identity:
            return "old"
        if value == new_identity:
            return "candidate"
        raise DeployGuardError("recovery inspect has an unknown container/image identity")

    official_role = role(official_identity)
    backup_role = role(backup_identity)
    candidate_role = role(candidate_identity)
    if backup_role not in (None, "old"):
        raise DeployGuardError("backup does not contain the journal old container")
    if candidate_role not in (None, "candidate"):
        raise DeployGuardError("named candidate does not contain the journal candidate")
    if backup_identity is not None and backup_identity["running"]:
        raise DeployGuardError("backup old container unexpectedly remained running")
    if candidate_identity is not None and candidate_identity["running"]:
        raise DeployGuardError("named candidate unexpectedly remained running")
    if official_role == "old" and backup_identity is not None:
        raise DeployGuardError("old container appears as both official and backup")
    if official_role == "candidate" and candidate_identity is not None:
        raise DeployGuardError("candidate appears under both official and candidate names")

    if official_role != "old" and backup_role != "old":
        raise DeployGuardError(
            "no valid old container exists; recovery plan must remain empty"
        )

    actions = []
    if official_role == "candidate":
        if official_identity["running"]:
            actions.append("stop_official_candidate")
        actions.append("quarantine_official_candidate")
    if backup_role == "old":
        actions.append("rename_backup_to_official")
        actions.append("start_official")
    elif official_identity is not None and not official_identity["running"]:
        actions.append("start_official")
    if candidate_role == "candidate" or official_role == "candidate":
        actions.append("verify_named_candidate_quarantined")
    actions.append("verify_official_old")
    if any(action not in RECOVERY_ACTIONS for action in actions):
        raise DeployGuardError("recovery plan contains an unknown action")
    if actions != [action for action in RECOVERY_ACTIONS if action in actions]:
        raise DeployGuardError("recovery plan action order is invalid")
    return actions


def optional_object(path, label):
    if path is None:
        return None
    return one_object(path, label)


def owner_only_object_list(path, label):
    payload = read_owner_only_bytes(
        path,
        label,
        maximum_bytes=MAX_IMAGE_INSPECT_BYTES,
    )
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise DeployGuardError("{0} is not valid JSON".format(label)) from exc
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise DeployGuardError("{0} must contain a JSON object list".format(label))
    return value


def _normalized_optional_string_list(value, label):
    if value is None:
        return []
    if not isinstance(value, list) or any(type(item) is not str for item in value):
        raise DeployGuardError("{0} is not a string list".format(label))
    if len(value) != len(set(value)):
        raise DeployGuardError("{0} contains duplicates".format(label))
    return sorted(value)


def _normalized_optional_string_mapping(value, label):
    if value is None:
        return {}
    if not isinstance(value, dict) or any(
        type(key) is not str or type(item) is not str for key, item in value.items()
    ):
        raise DeployGuardError("{0} is not a string mapping".format(label))
    return {key: value[key] for key in sorted(value)}


def _normalized_empty_collection(value, label):
    if value is None:
        return []
    if not isinstance(value, list):
        raise DeployGuardError("{0} is not a list".format(label))
    return value


def _normalized_docker_network_mode(value):
    if type(value) is not str or not value:
        raise DeployGuardError("managed orphan network mode is invalid")
    # Docker Engine 26+ persists the Linux default-network alias as ``bridge``;
    # older engines may still expose the CLI spelling ``default``.
    return "bridge" if value == "default" else value


def _orphan_expected_command(role):
    if role == "candidate":
        return None, CANDIDATE_COMMAND
    return DEPLOY_ROLE_COMMANDS[role]


def _require_reference_environment(environment, role):
    if role in ("schema-reference-server", "schema-restore-server"):
        required = {
            "POSTGRES_USER": REFERENCE_DATABASE_USER,
            "POSTGRES_DB": REFERENCE_DATABASE_NAME,
            "POSTGRES_INITDB_ARGS": (
                "--auth-local=scram-sha-256 --auth-host=scram-sha-256"
            ),
            "PGDATA": "/var/lib/postgresql/data/pgdata",
        }
        for name, expected in required.items():
            if environment.get(name) != expected:
                raise DeployGuardError(
                    "managed reference server environment is invalid"
                )
        password = environment.get("POSTGRES_PASSWORD")
        if type(password) is not str or re.fullmatch(r"[0-9a-f]{64}", password) is None:
            raise DeployGuardError("managed reference server password is invalid")
        allowed_postgres = set(required) | {"POSTGRES_PASSWORD"}
        if any(
            name.startswith("POSTGRES_") and name not in allowed_postgres
            for name in environment
        ):
            raise DeployGuardError(
                "managed reference server has an unexpected PostgreSQL setting"
            )
        if any(
            SENSITIVE_ENVIRONMENT_NAME.search(name)
            and name != "POSTGRES_PASSWORD"
            for name in environment
        ):
            raise DeployGuardError(
                "managed reference server received another credential"
            )
    elif role == "schema-reference-materializer":
        reference_url = environment.get(REFERENCE_DATABASE_URL_KEY)
        if (
            type(reference_url) is not str
            or REFERENCE_DATABASE_URI.fullmatch(reference_url) is None
        ):
            raise DeployGuardError(
                "managed reference materializer credential is invalid"
            )
        if any(
            name.startswith("PG")
            or name.startswith("POSTGRES_")
            or (
                SENSITIVE_ENVIRONMENT_NAME.search(name)
                and name != REFERENCE_DATABASE_URL_KEY
            )
            for name in environment
        ):
            raise DeployGuardError(
                "managed reference materializer received another credential"
            )
    elif role == "schema-reference-catalog":
        required = {
            "PGHOST": REFERENCE_DATABASE_SOCKET,
            "PGPORT": "5432",
            "PGUSER": REFERENCE_DATABASE_USER,
            "PGDATABASE": REFERENCE_DATABASE_NAME,
            "PGOPTIONS": DATABASE_PROBE_PGOPTIONS,
            "XJIE_EXPECTED_DATABASE": REFERENCE_DATABASE_NAME,
        }
        for name, expected in required.items():
            if environment.get(name) != expected:
                raise DeployGuardError(
                    "managed reference catalog environment is invalid"
                )
        password = environment.get("PGPASSWORD")
        if type(password) is not str or re.fullmatch(r"[0-9a-f]{64}", password) is None:
            raise DeployGuardError("managed reference catalog password is invalid")
        allowed_pg = set(required) | {
            "PGPASSWORD",
            "PGDATA",
            "PG_MAJOR",
            "PG_VERSION",
            "PG_SHA256",
        }
        if any(
            (name.startswith("PG") and name not in allowed_pg)
            or name.startswith("POSTGRES_")
            or (
                SENSITIVE_ENVIRONMENT_NAME.search(name)
                and name != "PGPASSWORD"
            )
            for name in environment
        ):
            raise DeployGuardError(
                "managed reference catalog received another credential"
            )
    else:
        raise AssertionError(role)


def _reference_password_sha256(environment, role):
    if role in ("schema-reference-server", "schema-restore-server"):
        password = environment["POSTGRES_PASSWORD"]
    elif role == "schema-reference-catalog":
        password = environment["PGPASSWORD"]
    elif role == "schema-reference-materializer":
        match = REFERENCE_DATABASE_URI.fullmatch(
            environment[REFERENCE_DATABASE_URL_KEY]
        )
        if match is None:
            raise DeployGuardError("managed reference credential is invalid")
        password = match.group(1)
    else:
        return None
    return hashlib.sha256(password.encode("ascii")).hexdigest()


def _orphan_environment(config, role):
    environment = environment_map(config.get("Env"), "managed orphan")
    for name, expected in REQUIRED_IMAGE_ENVIRONMENT.items():
        if (
            role not in REFERENCE_SCHEMA_ROLES
            and role != "database-schema"
            and role not in {"schema-backup", "schema-backup-toc", "schema-restore"}
            and role not in RESTORE_VOLUME_CONTAINER_ROLES
            and environment.get(name) != expected
        ):
            raise DeployGuardError(
                "managed orphan image environment invariant is missing"
            )
    if role in REFERENCE_SCHEMA_ROLES:
        _require_reference_environment(environment, role)
    elif role == "schema-restore-server":
        _require_reference_environment(environment, role)
    elif role in {"schema-restore-capacity", "schema-restore-volume-init"}:
        allowed_pg = {"PGDATA", "PG_MAJOR", "PG_VERSION", "PG_SHA256"}
        if any(
            (name.startswith("PG") and name not in allowed_pg)
            or name.startswith("POSTGRES_")
            or SENSITIVE_ENVIRONMENT_NAME.search(name)
            for name in environment
        ):
            raise DeployGuardError(
                "managed restore volume utility received a credential"
            )
    elif role in PRODUCTION_MIGRATION_ROLES:
        required = {"PGHOST", "PGPORT", "PGUSER", "PGPASSWORD", "PGDATABASE"}
        allowed = required | set(DATABASE_CONNECTION_QUERY_ENVIRONMENT.values()) | {
            "PGDATA",
            "PG_MAJOR",
            "PG_VERSION",
            "PG_SHA256",
            *REQUIRED_IMAGE_ENVIRONMENT,
        }
        if (
            not required.issubset(environment)
            or any(
                not environment[name]
                or any(character in environment[name] for character in "\0\n\r")
                for name in required
            )
            or any(name.startswith("DATABASE_") for name in environment)
            or any(name.startswith("PG") and name not in allowed for name in environment)
            or any(
                SENSITIVE_ENVIRONMENT_NAME.search(name)
                and name != "PGPASSWORD"
                for name in environment
            )
        ):
            raise DeployGuardError(
                "managed production schema role lacks a minimal libpq identity"
            )
    elif role in EXPAND_SOCKET_ROLES:
        required = {
            "PGHOST": REFERENCE_DATABASE_SOCKET,
            "PGPORT": "5432",
            "PGDATABASE": REFERENCE_DATABASE_NAME,
        }
        for name, expected in required.items():
            if environment.get(name) != expected:
                raise DeployGuardError(
                    "managed expand rehearsal database identity is invalid"
                )
        expected_user = (
            REFERENCE_DATABASE_USER
            if role == "schema-restore"
            else "xjie_migration_rehearsal"
        )
        if environment.get("PGUSER") != expected_user:
            raise DeployGuardError(
                "managed expand rehearsal database role is invalid"
            )
        password = environment.get("PGPASSWORD")
        if type(password) is not str or re.fullmatch(r"[0-9a-f]{64}", password) is None:
            raise DeployGuardError(
                "managed expand rehearsal database password is invalid"
            )
        allowed = set(required) | {
            "PGUSER",
            "PGPASSWORD",
            *REQUIRED_IMAGE_ENVIRONMENT,
            "PGDATA",
            "PG_MAJOR",
            "PG_VERSION",
            "PG_SHA256",
        }
        if any(
            (name.startswith("PG") and name not in allowed)
            or name.startswith("POSTGRES_")
            or (
                SENSITIVE_ENVIRONMENT_NAME.search(name)
                and name != "PGPASSWORD"
            )
            for name in environment
        ):
            raise DeployGuardError(
                "managed expand rehearsal role received another credential"
            )
    elif role == "schema-backup-toc":
        allowed_pg = {"PGDATA", "PG_MAJOR", "PG_VERSION", "PG_SHA256"}
        if any(
            (name.startswith("PG") and name not in allowed_pg)
            or name.startswith("POSTGRES_")
            or SENSITIVE_ENVIRONMENT_NAME.search(name)
            for name in environment
        ):
            raise DeployGuardError(
                "managed backup integrity reader received a credential"
            )
    elif role == "database-schema":
        required_probe_environment = {
            "PGHOST",
            "PGPORT",
            "PGUSER",
            "PGPASSWORD",
            "PGDATABASE",
            "PGOPTIONS",
            "XJIE_EXPECTED_DATABASE",
        }
        if not required_probe_environment.issubset(environment):
            raise DeployGuardError("managed database probe lacks pinned libpq identity")
        if environment["PGOPTIONS"] != DATABASE_PROBE_PGOPTIONS:
            raise DeployGuardError("managed database probe PGOPTIONS changed")
    elif role in RUNTIME_ENV_ROLES:
        if "DATABASE_URL" not in environment:
            raise DeployGuardError("managed runtime orphan lacks DATABASE_URL")
    elif any(SENSITIVE_ENVIRONMENT_NAME.search(name) for name in environment):
        raise DeployGuardError("managed isolated orphan contains a runtime secret key")
    return {name: environment[name] for name in sorted(environment)}


def _orphan_environment_class(role):
    if role in REFERENCE_SCHEMA_ROLES:
        return role
    if role == "database-schema":
        return "database-probe"
    if role in PRODUCTION_MIGRATION_ROLES:
        return "production-migration"
    if role in EXPAND_SOCKET_ROLES:
        return role
    if role == "schema-restore-server":
        return role
    if role in {"schema-restore-capacity", "schema-restore-volume-init"}:
        return role
    if role in RUNTIME_ENV_ROLES:
        return "application-runtime"
    return "image-only"


def _orphan_topology(payload, container_id, config, host, state, role):
    expected_entrypoint, expected_command = _orphan_expected_command(role)
    entrypoint = config.get("Entrypoint")
    command = config.get("Cmd")
    if expected_entrypoint is None:
        if entrypoint is not None:
            raise DeployGuardError("managed orphan entrypoint is invalid")
        normalized_entrypoint = None
    else:
        if not exact_json(entrypoint, list(expected_entrypoint)):
            raise DeployGuardError("managed orphan entrypoint is invalid")
        normalized_entrypoint = list(expected_entrypoint)
    if not exact_json(command, list(expected_command)):
        raise DeployGuardError("managed orphan command is invalid")

    if config.get("Hostname") != container_id[:12]:
        raise DeployGuardError("managed orphan hostname is not its container ID")
    constrained_resources = REFERENCE_ROLE_RESOURCES.get(role)
    if constrained_resources is not None:
        expected_user, expected_stop_timeout, expected_memory, expected_pids = (
            constrained_resources
        )
        if config.get("User") != expected_user:
            raise DeployGuardError("managed orphan user is invalid")
        observed_stop_timeout = config.get("StopTimeout")
        if "StopTimeout" not in config or (
            observed_stop_timeout is not None
            if expected_stop_timeout is None
            else type(observed_stop_timeout) is not int
            or observed_stop_timeout != expected_stop_timeout
        ):
            raise DeployGuardError("managed orphan stop timeout is invalid")
    interactive = role in INTERACTIVE_ROLES
    for key, expected in (
        ("AttachStdin", interactive),
        ("AttachStdout", True),
        ("AttachStderr", True),
        ("OpenStdin", interactive),
        ("StdinOnce", interactive),
        ("Tty", False),
    ):
        if type(config.get(key)) is not bool or config[key] is not expected:
            raise DeployGuardError(
                "managed orphan Config.{0} is invalid".format(key)
            )
    environment = _orphan_environment(config, role)
    environment_class = _orphan_environment_class(role)

    expected_restart = {
        "Name": PINNED_SPEC["restart_policy"] if role in LONG_RUNNING_ROLES else "no",
        "MaximumRetryCount": 0,
    }
    restart = host.get("RestartPolicy")
    if not exact_json(restart, expected_restart):
        raise DeployGuardError("managed orphan restart policy is invalid")

    port_bindings = host.get("PortBindings")
    if port_bindings is None:
        port_bindings = {}
    if not isinstance(port_bindings, dict):
        raise DeployGuardError("managed orphan port bindings are invalid")
    expected_ports = _expected_port_bindings() if role == "candidate" else {}
    if not exact_json(port_bindings, expected_ports):
        raise DeployGuardError("managed orphan port binding is invalid")

    expected_extra_hosts = (
        sorted(PINNED_SPEC["extra_hosts"])
        if role in RUNTIME_ENV_ROLES or role in PRODUCTION_MIGRATION_ROLES
        else []
    )
    extra_hosts = _normalized_optional_string_list(
        host.get("ExtraHosts"), "managed orphan ExtraHosts"
    )
    if not exact_json(extra_hosts, expected_extra_hosts):
        raise DeployGuardError("managed orphan extra hosts are invalid")

    expected_network_mode = (
        "none" if role in ISOLATED_NETWORK_ROLES else "bridge"
    )
    network_mode = _normalized_docker_network_mode(host.get("NetworkMode"))
    if network_mode != expected_network_mode:
        raise DeployGuardError("managed orphan network mode is invalid")

    hardened = role in HARDENED_PROBE_ROLES
    if role == "database-schema":
        expected_tmpfs = DATABASE_PROBE_TMPFS
    elif role in SUPERVISED_SERVICE_ROLES:
        expected_tmpfs = SUPERVISED_SERVICE_TMPFS
    elif role == "schema-reference-server":
        expected_tmpfs = REFERENCE_SERVER_TMPFS
    elif role == "schema-restore-server":
        expected_tmpfs = RESTORE_SERVER_TMPFS
    elif role == "schema-reference-materializer":
        expected_tmpfs = REFERENCE_MATERIALIZER_TMPFS
    elif role == "schema-reference-catalog":
        expected_tmpfs = REFERENCE_CATALOG_TMPFS
    else:
        expected_tmpfs = SCHEMA_PROBE_TMPFS if hardened else {}
    tmpfs = _normalized_optional_string_mapping(
        host.get("Tmpfs"), "managed orphan Tmpfs"
    )
    if not exact_json(tmpfs, expected_tmpfs):
        raise DeployGuardError("managed orphan tmpfs topology is invalid")

    expected_cap_drop = ["ALL"] if hardened else []
    cap_drop = _normalized_optional_string_list(
        host.get("CapDrop"), "managed orphan CapDrop"
    )
    if not exact_json(cap_drop, expected_cap_drop):
        raise DeployGuardError("managed orphan dropped capabilities are invalid")
    cap_add = _normalized_optional_string_list(
        host.get("CapAdd"), "managed orphan CapAdd"
    )
    expected_cap_add = (
        ["CHOWN"] if role == "schema-restore-volume-init" else []
    )
    if not exact_json(cap_add, expected_cap_add):
        raise DeployGuardError("managed orphan adds capabilities")

    expected_security = ["no-new-privileges"] if hardened else []
    security_options = _normalized_optional_string_list(
        host.get("SecurityOpt"), "managed orphan SecurityOpt"
    )
    if not exact_json(security_options, expected_security):
        raise DeployGuardError("managed orphan security options are invalid")

    if role in REFERENCE_SCHEMA_ROLES or role in (
        EXPAND_SOCKET_ROLES
        | {"schema-backup-toc"}
        | RESTORE_VOLUME_CONTAINER_ROLES
    ):
        expected_log_config = {"Type": "none", "Config": {}}
        if not exact_json(host.get("LogConfig"), expected_log_config):
            raise DeployGuardError("managed reference orphan log driver is invalid")
    else:
        expected_log_config = None

    resource_values = None
    if constrained_resources is not None:
        _, _, expected_memory, expected_pids = constrained_resources
        resource_values = {
            "Memory": expected_memory,
            "MemorySwap": expected_memory,
            "PidsLimit": expected_pids,
        }
        for key, expected in resource_values.items():
            if type(host.get(key)) is not int or host[key] != expected:
                raise DeployGuardError(
                    "managed orphan {0} resource limit is invalid".format(key)
                )

    expected_bools = {
        "AutoRemove": role in AUTO_REMOVE_ROLES,
        "Privileged": False,
        "PublishAllPorts": False,
        "ReadonlyRootfs": hardened,
    }
    normalized_bools = {}
    for key, expected in expected_bools.items():
        value = host.get(key)
        if type(value) is not bool or value is not expected:
            raise DeployGuardError("managed orphan {0} is invalid".format(key))
        normalized_bools[key] = value

    empty_host_collections = {}
    for key in (
        "Binds",
        "DeviceCgroupRules",
        "DeviceRequests",
        "Devices",
        "Links",
        "VolumesFrom",
    ):
        value = _normalized_empty_collection(
            host.get(key), "managed orphan {0}".format(key)
        )
        if value:
            raise DeployGuardError("managed orphan {0} is not empty".format(key))
        empty_host_collections[key] = []

    mounts = payload.get("Mounts")
    reference_socket_source = None
    restore_volume_name = None
    needs_socket = (
        role in REFERENCE_SCHEMA_ROLES
        or role in EXPAND_SOCKET_ROLES
        or role == "schema-restore-server"
    )
    needs_volume = role in RESTORE_VOLUME_CONTAINER_ROLES
    expected_mount_count = int(needs_socket) + int(needs_volume)
    if not isinstance(mounts, list) or len(mounts) != expected_mount_count:
        raise DeployGuardError("managed schema orphan mount count is invalid")
    normalized_mounts = []
    if needs_socket:
        socket_mounts = [
            item for item in mounts
            if isinstance(item, dict)
            and item.get("Destination") == REFERENCE_SOCKET_DESTINATION
        ]
        if len(socket_mounts) != 1:
            raise DeployGuardError("managed schema socket orphan mount is invalid")
        mount = socket_mounts[0]
        expected_mode = (
            ""
            if role in ("schema-reference-server", "schema-restore-server")
            else "ro"
        )
        expected_rw = role in (
            "schema-reference-server",
            "schema-restore-server",
        )
        if (
            set(mount)
            != {"Type", "Source", "Destination", "Mode", "RW", "Propagation"}
            or mount["Type"] != "bind"
            or type(mount["Source"]) is not str
            or REFERENCE_SOCKET_SOURCE.fullmatch(mount["Source"]) is None
            or mount["Destination"] != REFERENCE_SOCKET_DESTINATION
            or mount["Mode"] != expected_mode
            or type(mount["RW"]) is not bool
            or mount["RW"] is not expected_rw
            or mount["Propagation"] != "rprivate"
        ):
            raise DeployGuardError("managed reference socket mount is invalid")
        reference_socket_source = mount["Source"]
        normalized_mounts.append(dict(mount))
    if needs_volume:
        volume_mounts = [
            item for item in mounts
            if isinstance(item, dict)
            and item.get("Destination") == RESTORE_VOLUME_DESTINATION
        ]
        if len(volume_mounts) != 1:
            raise DeployGuardError("managed restore data volume mount is invalid")
        mount = volume_mounts[0]
        labels = config.get("Labels")
        run_id = labels.get(DEPLOY_LABEL_KEYS[4]) if isinstance(labels, dict) else None
        restore_volume_name = deployment_name(run_id, RESTORE_VOLUME_ROLE)
        expected_rw = role != "schema-restore-capacity"
        allowed_modes = ("", "z") if expected_rw else ("ro",)
        if (
            set(mount)
            != {
                "Type",
                "Name",
                "Source",
                "Destination",
                "Driver",
                "Mode",
                "RW",
                "Propagation",
            }
            or mount["Type"] != "volume"
            or mount["Name"] != restore_volume_name
            or mount["Driver"] != "local"
            or type(mount["Source"]) is not str
            or not mount["Source"].startswith("/")
            or any(character in mount["Source"] for character in "\0\n\r")
            or mount["Destination"] != RESTORE_VOLUME_DESTINATION
            or mount["Mode"] not in allowed_modes
            or type(mount["RW"]) is not bool
            or mount["RW"] is not expected_rw
            or mount["Propagation"] not in ("", "rprivate")
        ):
            raise DeployGuardError("managed restore data volume mount is unsafe")
        normalized_mounts.append(dict(mount))
    normalized_mounts.sort(key=lambda item: item["Destination"])
    network_settings = payload.get("NetworkSettings")
    networks = network_settings.get("Networks") if isinstance(network_settings, dict) else None
    if not isinstance(networks, dict) or any(
        type(name) is not str or not isinstance(endpoint, dict)
        for name, endpoint in networks.items()
    ):
        raise DeployGuardError("managed orphan network topology is incomplete")
    network_names = sorted(
        "bridge" if name == "default" else name for name in networks
    )
    if network_names != [expected_network_mode]:
        raise DeployGuardError("managed orphan attached networks are invalid")

    topology = {
        "config": {
            "attach_stdin": interactive,
            "attach_stderr": True,
            "attach_stdout": True,
            "command": list(expected_command),
            "entrypoint": normalized_entrypoint,
            "environment": environment,
            "environment_class": environment_class,
            "hostname": container_id[:12],
            "open_stdin": interactive,
            "stop_timeout": (
                constrained_resources[1]
                if constrained_resources is not None
                else config.get("StopTimeout")
            ),
            "stdin_once": interactive,
            "tty": False,
            "user": config.get("User"),
        },
        "host": {
            **normalized_bools,
            **empty_host_collections,
            "CapAdd": cap_add,
            "CapDrop": cap_drop,
            "ExtraHosts": extra_hosts,
            "NetworkMode": network_mode,
            "PortBindings": port_bindings,
            "RestartPolicy": restart,
            "SecurityOpt": security_options,
            "Tmpfs": tmpfs,
            "LogConfig": expected_log_config,
            "Resources": resource_values,
        },
        "mounts": normalized_mounts,
        "networks": network_names,
        "reference_socket_source": reference_socket_source,
        "restore_volume_name": restore_volume_name,
        "running": state["Running"],
    }
    encoded = json.dumps(
        topology,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return topology, hashlib.sha256(encoded).hexdigest()


def _orphan_container_identity(payload):
    container_id = payload.get("Id")
    image_id = payload.get("Image")
    raw_name = payload.get("Name")
    config = payload.get("Config")
    host = payload.get("HostConfig")
    state = payload.get("State")
    if not isinstance(container_id, str) or CONTAINER_ID.fullmatch(container_id) is None:
        raise DeployGuardError("managed orphan container ID is invalid")
    if not isinstance(image_id, str) or IMAGE_ID.fullmatch(image_id) is None:
        raise DeployGuardError("managed orphan image ID is invalid")
    if (
        not isinstance(raw_name, str)
        or not raw_name.startswith("/")
        or CONTAINER_NAME.fullmatch(raw_name[1:]) is None
    ):
        raise DeployGuardError("managed orphan name is invalid")
    if not isinstance(config, dict) or not isinstance(host, dict) or not isinstance(state, dict):
        raise DeployGuardError("managed orphan inspect is incomplete")
    if type(state.get("Running")) is not bool:
        raise DeployGuardError("managed orphan Running state is invalid")
    if config.get("Image") != image_id:
        raise DeployGuardError("managed orphan Config.Image is not immutable")
    labels = config.get("Labels")
    values = _deployment_label_values(labels, "managed orphan")
    if values is None:
        raise DeployGuardError("managed orphan lifecycle labels are missing")
    if any(
        key.startswith(DEPLOY_LABEL_PREFIX) and key not in DEPLOY_LABEL_KEYS
        for key in labels
    ):
        raise DeployGuardError("managed orphan has an unknown lifecycle label")
    role = values[DEPLOY_LABEL_KEYS[5]]
    if role not in DEPLOY_ROLES:
        raise DeployGuardError("managed orphan lifecycle role is not a container role")
    revision = values[DEPLOY_LABEL_KEYS[3]]
    run_id = values[DEPLOY_LABEL_KEYS[4]]
    original_name = values[DEPLOY_LABEL_KEYS[6]]
    if not exact_json(
        values,
        deployment_labels(original_name, image_id, revision, run_id, role),
    ):
        raise DeployGuardError("managed orphan lifecycle identity is invalid")

    name = raw_name[1:]
    official = name == PINNED_SPEC["container_name"]
    backup = BACKUP_CONTAINER_NAME.fullmatch(name) is not None
    renamed_production_container = official or backup
    if not renamed_production_container and name != original_name:
        raise DeployGuardError("managed orphan current/original name differs")
    if renamed_production_container and role != "candidate":
        raise DeployGuardError("protected production name requires the candidate role")
    if official and state["Running"] is not True:
        raise DeployGuardError("protected official container is not running")
    if backup and state["Running"] is not False:
        raise DeployGuardError("rollback backup container unexpectedly runs")
    protected = official or backup
    if role == "candidate" and not protected and state["Running"]:
        raise DeployGuardError("pre-journal candidate unexpectedly runs")

    topology, topology_sha256 = _orphan_topology(
        payload, container_id, config, host, state, role
    )
    return {
        "container_id": container_id,
        "name": name,
        "original_name": original_name,
        "image_id": image_id,
        "role": role,
        "revision": revision,
        "run_id": run_id,
        "protected": protected,
        "official": official,
        "backup": backup,
        "running": topology["running"],
        "environment": topology["config"]["environment"],
        "environment_class": topology["config"]["environment_class"],
        "reference_password_sha256": _reference_password_sha256(
            topology["config"]["environment"], role
        ),
        "reference_socket_source": topology["reference_socket_source"],
        "topology_sha256": topology_sha256,
    }


def _validate_orphan_environment_groups(identities):
    groups = {}
    for item in identities:
        key = (item["revision"], item["run_id"], item["image_id"])
        groups.setdefault(key, []).append(item)
    for items in groups.values():
        by_class = {}
        for item in items:
            by_class.setdefault(item["environment_class"], []).append(
                item["environment"]
            )
        for label, environments in by_class.items():
            if environments and any(
                not exact_json(value, environments[0]) for value in environments[1:]
            ):
                raise DeployGuardError(
                    "managed orphan {0} environments differ within one run".format(label)
                )
        application_runtime = by_class.get("application-runtime", [])
        image_only = by_class.get("image-only", [])
        if application_runtime and image_only and any(
            application_runtime[0].get(name) != value
            for name, value in image_only[0].items()
        ):
            raise DeployGuardError(
                "managed runtime orphan does not preserve its image environment"
            )
    reference_groups = {}
    for item in identities:
        if item["role"] in REFERENCE_SCHEMA_ROLES:
            reference_groups.setdefault(
                (item["revision"], item["run_id"]), []
            ).append(item)
    for items in reference_groups.values():
        socket_sources = {item["reference_socket_source"] for item in items}
        password_digests = {item["reference_password_sha256"] for item in items}
        if len(socket_sources) != 1:
            raise DeployGuardError(
                "managed reference orphans do not share one socket directory"
            )
        if len(password_digests) != 1:
            raise DeployGuardError(
                "managed reference orphans do not share one synthetic credential"
            )
        postgresql_images = {
            item["image_id"]
            for item in items
            if item["role"] in (
                "schema-reference-server",
                "schema-reference-catalog",
            )
        }
        if len(postgresql_images) > 1:
            raise DeployGuardError(
                "managed reference PostgreSQL roles use different images"
            )
    rehearsal_groups = {}
    for item in identities:
        if item["role"] in EXPAND_REHEARSAL_ROLES:
            rehearsal_groups.setdefault(
                (item["revision"], item["run_id"]), []
            ).append(item)
    for items in rehearsal_groups.values():
        socket_sources = {item["reference_socket_source"] for item in items}
        if len(socket_sources) != 1:
            raise DeployGuardError(
                "managed expand rehearsal roles do not share one socket directory"
            )


def _protect_supervised_companions(identities):
    """Protect only a complete worker/beat pair bound to the official API run."""

    officials = [item for item in identities if item["official"]]
    if len(officials) > 1:
        raise DeployGuardError("managed runtime has multiple official containers")
    if not officials:
        return
    official = officials[0]
    matching = [
        item
        for item in identities
        if item["role"] in SUPERVISED_SERVICE_ROLES
        and item["revision"] == official["revision"]
        and item["run_id"] == official["run_id"]
        and item["image_id"] == official["image_id"]
    ]
    if not matching:
        # Compatibility for the first deployment upgrading an API-only legacy
        # installation to the supervised worker/beat contract.
        return
    roles = [item["role"] for item in matching]
    if len(roles) != len(SUPERVISED_SERVICE_ROLES) or set(roles) != set(
        SUPERVISED_SERVICE_ROLES
    ):
        raise DeployGuardError("official supervised service set is incomplete or duplicated")
    if any(not item["running"] for item in matching):
        raise DeployGuardError("official supervised service is not running")
    for item in matching:
        item["protected"] = True


def plan_orphan_cleanup(inspects):
    if not isinstance(inspects, list):
        raise DeployGuardError("managed orphan inspect collection is invalid")
    identities = [_orphan_container_identity(item) for item in inspects]
    container_ids = [item["container_id"] for item in identities]
    names = [item["name"] for item in identities]
    if len(container_ids) != len(set(container_ids)) or len(names) != len(set(names)):
        raise DeployGuardError("managed orphan inspect identities overlap")
    run_roles = [(item["run_id"], item["role"]) for item in identities]
    if len(run_roles) != len(set(run_roles)):
        raise DeployGuardError("managed orphan run/role identities overlap")
    _validate_orphan_environment_groups(identities)
    _protect_supervised_companions(identities)
    records = [ORPHAN_PLAN_VERSION]
    for item in sorted(identities, key=lambda value: (value["name"], value["container_id"])):
        if item["protected"]:
            continue
        records.extend(
            (
                "remove_orphan",
                item["container_id"],
                item["original_name"],
                item["image_id"],
                item["role"],
                item["revision"],
                item["run_id"] + ":" + item["topology_sha256"],
            )
        )
    if (len(records) - 1) % ORPHAN_PLAN_RECORD_SIZE:
        raise AssertionError("orphan cleanup record shape is invalid")
    return records


def plan_backup_retention(inspects, retained_backup_id):
    if not isinstance(inspects, list):
        raise DeployGuardError("backup retention inspect collection is invalid")
    if (
        type(retained_backup_id) is not str
        or CONTAINER_ID.fullmatch(retained_backup_id) is None
    ):
        raise DeployGuardError("retained backup container ID is invalid")
    identities = [_orphan_container_identity(item) for item in inspects]
    container_ids = [item["container_id"] for item in identities]
    names = [item["name"] for item in identities]
    if len(container_ids) != len(set(container_ids)) or len(names) != len(set(names)):
        raise DeployGuardError("backup retention inspect identities overlap")
    run_roles = [(item["run_id"], item["role"]) for item in identities]
    if len(run_roles) != len(set(run_roles)):
        raise DeployGuardError("backup retention run/role identities overlap")
    _validate_orphan_environment_groups(identities)
    _protect_supervised_companions(identities)
    officials = [item for item in identities if item["official"]]
    backups = [item for item in identities if item["backup"]]
    others = [
        item
        for item in identities
        if not item["official"] and not item["backup"] and not item["protected"]
    ]
    if len(officials) != 1:
        raise DeployGuardError("backup retention requires exactly one managed official")
    if others:
        raise DeployGuardError("backup retention found a non-production orphan")
    retained = [
        item for item in backups if item["container_id"] == retained_backup_id
    ]
    if len(retained) != 1:
        raise DeployGuardError("backup retention cannot identify the current rollback")
    records = [BACKUP_RETENTION_PLAN_VERSION]
    for item in sorted(backups, key=lambda value: (value["name"], value["container_id"])):
        if item["container_id"] == retained_backup_id:
            continue
        records.extend(
            (
                "remove_expired_backup",
                item["container_id"],
                item["original_name"],
                item["image_id"],
                item["role"],
                item["revision"],
                item["run_id"] + ":" + item["topology_sha256"],
            )
        )
    if (len(records) - 1) % ORPHAN_PLAN_RECORD_SIZE:
        raise AssertionError("backup retention record shape is invalid")
    return records


def clear_journal(path):
    parent_descriptor, name = _open_safe_output_parent(path)
    try:
        load_journal(path)
        try:
            os.unlink(name, dir_fd=parent_descriptor)
            os.fsync(parent_descriptor)
        except OSError as exc:
            raise DeployGuardError("cannot clear deployment journal") from exc
    finally:
        os.close(parent_descriptor)


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate_spec = subparsers.add_parser("validate-spec")
    validate_spec.add_argument("--spec", required=True)

    emit_spec = subparsers.add_parser("emit-spec")
    emit_spec.add_argument("--spec", required=True)
    emit_spec.add_argument("--output", required=True)

    snapshot = subparsers.add_parser("snapshot-env")
    snapshot.add_argument("--spec", required=True)
    snapshot.add_argument("--source", required=True)
    snapshot.add_argument("--output", required=True)

    probe_snapshot = subparsers.add_parser("snapshot-database-probe-env")
    probe_snapshot.add_argument("--spec", required=True)
    probe_snapshot.add_argument("--source", required=True)
    probe_snapshot.add_argument("--application-env", required=True)
    probe_snapshot.add_argument("--output", required=True)

    migration_snapshot = subparsers.add_parser("snapshot-database-migration-env")
    migration_snapshot.add_argument("--spec", required=True)
    migration_snapshot.add_argument("--source", required=True)
    migration_snapshot.add_argument("--application-env", required=True)
    migration_snapshot.add_argument("--output", required=True)

    create = subparsers.add_parser("create-args")
    create.add_argument("--spec", required=True)
    create.add_argument("--name", required=True)
    create.add_argument("--image", required=True)
    create.add_argument("--image-ref")
    create.add_argument("--env-file", required=True)
    create.add_argument("--env-source", required=True)
    create.add_argument("--expected-sha", required=True)
    create.add_argument("--run-id", required=True)
    create.add_argument("--role", required=True, choices=DEPLOY_ROLES)
    create.add_argument("--output", required=True)
    create.add_argument("one_shot_command", nargs=argparse.REMAINDER)

    lifecycle_labels = subparsers.add_parser("emit-lifecycle-labels")
    lifecycle_labels.add_argument("--name", required=True)
    lifecycle_labels.add_argument("--image", required=True)
    lifecycle_labels.add_argument("--expected-sha", required=True)
    lifecycle_labels.add_argument("--run-id", required=True)
    lifecycle_labels.add_argument(
        "--role", required=True, choices=DEPLOY_LIFECYCLE_ROLES
    )
    lifecycle_labels.add_argument("--output", required=True)

    restore_volume_inspect = subparsers.add_parser(
        "validate-expand-restore-volume-inspect"
    )
    restore_volume_inspect.add_argument("--inspect", required=True)
    restore_volume_inspect.add_argument("--name", required=True)
    restore_volume_inspect.add_argument("--expected-sha", required=True)
    restore_volume_inspect.add_argument("--run-id", required=True)
    restore_volume_inspect.add_argument("--image-id", required=True)

    restore_volume_cleanup = subparsers.add_parser(
        "plan-expand-restore-volume-cleanup"
    )
    restore_volume_cleanup.add_argument("--inspects", required=True)
    restore_volume_cleanup.add_argument("--output", required=True)

    inspect = subparsers.add_parser("validate-inspects")
    inspect.add_argument("--spec", required=True)
    inspect.add_argument("--old-container", required=True)
    inspect.add_argument("--old-image", required=True)
    inspect.add_argument("--candidate-container", required=True)
    inspect.add_argument("--candidate-image", required=True)
    inspect.add_argument("--env-file", required=True)
    inspect.add_argument("--expected-sha", required=True)

    image_scan = subparsers.add_parser("scan-image")
    image_scan.add_argument("--image-inspect", required=True)
    image_scan.add_argument("--image-archive", required=True)
    image_scan.add_argument("--env-file", required=True)
    image_scan.add_argument("--expected-image-id", required=True)

    source_snapshot = subparsers.add_parser("validate-source-snapshot")
    source_snapshot.add_argument("--manifest", required=True)
    source_snapshot.add_argument("--source-root", required=True)

    migration_probe = subparsers.add_parser("emit-migration-probe")
    migration_probe.add_argument("--output", required=True)

    expand_source = subparsers.add_parser("extract-expand-migration-source")
    expand_source.add_argument("--old-manifest", required=True)
    expand_source.add_argument("--candidate-manifest", required=True)
    expand_source.add_argument("--source-root", required=True)
    expand_source.add_argument("--output", required=True)

    reference_materializer = subparsers.add_parser(
        "emit-reference-schema-materializer"
    )
    reference_materializer.add_argument("--candidate-manifest", required=True)
    reference_materializer.add_argument("--output", required=True)

    reference_materializer_result = subparsers.add_parser(
        "validate-reference-materializer-result"
    )
    reference_materializer_result.add_argument("--candidate-manifest", required=True)
    reference_materializer_result.add_argument("--result", required=True)

    expand_reference_materializer_result = subparsers.add_parser(
        "validate-expand-reference-materializer-result"
    )
    expand_reference_materializer_result.add_argument(
        "--candidate-manifest", required=True
    )
    expand_reference_materializer_result.add_argument("--result", required=True)

    reference_catalog_probe = subparsers.add_parser(
        "emit-reference-catalog-probe"
    )
    reference_catalog_probe.add_argument("--candidate-manifest", required=True)
    reference_catalog_probe.add_argument("--output", required=True)

    database_schema_probe = subparsers.add_parser("emit-database-schema-probe")
    database_schema_probe.add_argument("--candidate-manifest", required=True)
    database_schema_probe.add_argument("--reference-catalog", required=True)
    database_schema_probe.add_argument("--output", required=True)

    database_schema = subparsers.add_parser("validate-database-schema")
    database_schema.add_argument("--candidate-manifest", required=True)
    database_schema.add_argument("--reference-catalog", required=True)
    database_schema.add_argument("--database-catalog", required=True)

    no_migration_delta = subparsers.add_parser("validate-no-migration-delta")
    no_migration_delta.add_argument("--old-manifest", required=True)
    no_migration_delta.add_argument("--candidate-manifest", required=True)
    no_migration_delta.add_argument("--heads", required=True)
    no_migration_delta.add_argument("--current", required=True)

    expand_migration = subparsers.add_parser("validate-expand-migration")
    expand_migration.add_argument("--old-manifest", required=True)
    expand_migration.add_argument("--candidate-manifest", required=True)
    expand_migration.add_argument("--migration-source", required=True)
    expand_migration.add_argument("--output", required=True)

    expand_runner = subparsers.add_parser("emit-expand-transaction-runner")
    expand_runner.add_argument("--plan", required=True)
    expand_runner.add_argument("--output", required=True)

    expand_plan_read = subparsers.add_parser("read-expand-migration-plan")
    expand_plan_read.add_argument("--plan", required=True)
    expand_plan_read.add_argument("--output", required=True)

    expected_expand_result = subparsers.add_parser(
        "emit-expected-expand-transaction-result"
    )
    expected_expand_result.add_argument("--plan", required=True)
    expected_expand_result.add_argument("--output", required=True)

    expand_result = subparsers.add_parser("validate-expand-transaction-result")
    expand_result.add_argument("--plan", required=True)
    expand_result.add_argument("--result", required=True)

    old_app_compat_probe = subparsers.add_parser(
        "emit-expand-old-app-compat-probe"
    )
    old_app_compat_probe.add_argument("--old-manifest", required=True)
    old_app_compat_probe.add_argument("--plan", required=True)
    old_app_compat_probe.add_argument("--output", required=True)

    old_app_compat_result = subparsers.add_parser(
        "validate-expand-old-app-compat-result"
    )
    old_app_compat_result.add_argument("--old-manifest", required=True)
    old_app_compat_result.add_argument("--plan", required=True)
    old_app_compat_result.add_argument("--result", required=True)

    expected_old_app_compat_result = subparsers.add_parser(
        "emit-expected-expand-old-app-compat-result"
    )
    expected_old_app_compat_result.add_argument("--old-manifest", required=True)
    expected_old_app_compat_result.add_argument("--plan", required=True)
    expected_old_app_compat_result.add_argument("--output", required=True)

    expand_catalog = subparsers.add_parser("validate-expand-catalog-transition")
    expand_catalog.add_argument("--old-manifest", required=True)
    expand_catalog.add_argument("--candidate-manifest", required=True)
    expand_catalog.add_argument("--old-catalog", required=True)
    expand_catalog.add_argument("--migrated-catalog", required=True)
    expand_catalog.add_argument("--candidate-reference-catalog", required=True)
    expand_catalog.add_argument("--plan", required=True)

    expand_approval = subparsers.add_parser("emit-expand-approval-plan")
    expand_approval.add_argument("--expected-main-sha", required=True)
    expand_approval.add_argument("--trusted-bundle-sha256", required=True)
    expand_approval.add_argument("--old-manifest", required=True)
    expand_approval.add_argument("--candidate-manifest", required=True)
    expand_approval.add_argument("--old-catalog", required=True)
    expand_approval.add_argument("--candidate-catalog", required=True)
    expand_approval.add_argument("--plan", required=True)
    expand_approval.add_argument("--output", required=True)

    validate_expand_approval = subparsers.add_parser(
        "validate-expand-approval-plan"
    )
    validate_expand_approval.add_argument("--approval-plan", required=True)
    validate_expand_approval.add_argument("--plan", required=True)

    expand_backup = subparsers.add_parser("attest-expand-backup")
    expand_backup.add_argument("--backup", required=True)
    expand_backup.add_argument("--toc", required=True)
    expand_backup.add_argument("--output", required=True)

    expand_backup_binding = subparsers.add_parser(
        "validate-expand-backup-binding"
    )
    expand_backup_binding.add_argument("--journal", required=True)
    expand_backup_binding.add_argument("--backup-attestation", required=True)

    expand_journal_start = subparsers.add_parser("start-expand-journal")
    expand_journal_start.add_argument("--journal", required=True)
    expand_journal_start.add_argument("--approval-plan", required=True)
    expand_journal_start.add_argument("--plan", required=True)
    expand_journal_start.add_argument("--backup-path", required=True)
    expand_journal_start.add_argument("--old-image-id", required=True)
    expand_journal_start.add_argument("--candidate-image-id", required=True)

    expand_journal_advance = subparsers.add_parser("advance-expand-journal")
    expand_journal_advance.add_argument("--journal", required=True)
    expand_journal_advance.add_argument(
        "--state",
        required=True,
        choices=EXPAND_JOURNAL_STATES[1:],
    )
    expand_journal_advance.add_argument("--backup-attestation")
    expand_journal_advance.add_argument("--restore-volume-attestation")

    restore_volume_attestation = subparsers.add_parser(
        "attest-expand-restore-volume"
    )
    restore_volume_attestation.add_argument("--inspect", required=True)
    restore_volume_attestation.add_argument("--database-size", required=True)
    restore_volume_attestation.add_argument("--capacity", required=True)
    restore_volume_attestation.add_argument("--backup-attestation", required=True)
    restore_volume_attestation.add_argument("--expected-sha", required=True)
    restore_volume_attestation.add_argument("--run-id", required=True)
    restore_volume_attestation.add_argument("--image-id", required=True)
    restore_volume_attestation.add_argument("--output", required=True)

    expand_journal_read = subparsers.add_parser("read-expand-journal")
    expand_journal_read.add_argument("--journal", required=True)
    expand_journal_read.add_argument("--output", required=True)

    expand_journal_binding = subparsers.add_parser(
        "validate-expand-journal-binding"
    )
    expand_journal_binding.add_argument("--journal", required=True)
    expand_journal_binding.add_argument("--approval-plan", required=True)
    expand_journal_binding.add_argument("--plan", required=True)
    expand_journal_binding.add_argument("--backup-path", required=True)
    expand_journal_binding.add_argument("--old-image-id", required=True)
    expand_journal_binding.add_argument("--candidate-image-id", required=True)

    expand_observed_head = subparsers.add_parser("validate-expand-observed-head")
    expand_observed_head.add_argument("--plan", required=True)
    expand_observed_head.add_argument("--input", required=True)
    expand_observed_head.add_argument("--output", required=True)

    expand_recovery = subparsers.add_parser("plan-expand-recovery")
    expand_recovery.add_argument("--journal", required=True)
    expand_recovery.add_argument("--observed-head", required=True)
    expand_recovery.add_argument("--observed-catalog-sha256", required=True)
    expand_recovery.add_argument("--output", required=True)

    expand_recovery_catalog = subparsers.add_parser(
        "plan-expand-recovery-catalog"
    )
    expand_recovery_catalog.add_argument("--journal", required=True)
    expand_recovery_catalog.add_argument("--observed-head", required=True)
    expand_recovery_catalog.add_argument("--observed-manifest", required=True)
    expand_recovery_catalog.add_argument("--observed-catalog", required=True)
    expand_recovery_catalog.add_argument("--output", required=True)

    expand_backup_reset = subparsers.add_parser(
        "reset-unverified-expand-backup"
    )
    expand_backup_reset.add_argument("--journal", required=True)

    expand_evidence = subparsers.add_parser("write-expand-evidence")
    expand_evidence.add_argument("--journal", required=True)
    expand_evidence.add_argument("--plan", required=True)
    expand_evidence.add_argument("--old-manifest", required=True)
    expand_evidence.add_argument("--rehearsal-transaction-result", required=True)
    expand_evidence.add_argument("--old-app-compat-result", required=True)
    expand_evidence.add_argument("--transaction-result", required=True)
    expand_evidence.add_argument("--candidate-manifest", required=True)
    expand_evidence.add_argument("--post-catalog", required=True)
    expand_evidence.add_argument("--output", required=True)

    validate_expand_evidence_parser = subparsers.add_parser(
        "validate-expand-evidence"
    )
    validate_expand_evidence_parser.add_argument("--journal", required=True)
    validate_expand_evidence_parser.add_argument("--plan", required=True)
    validate_expand_evidence_parser.add_argument("--old-manifest", required=True)
    validate_expand_evidence_parser.add_argument(
        "--rehearsal-transaction-result", required=True
    )
    validate_expand_evidence_parser.add_argument(
        "--old-app-compat-result", required=True
    )
    validate_expand_evidence_parser.add_argument(
        "--transaction-result", required=True
    )
    validate_expand_evidence_parser.add_argument(
        "--candidate-manifest", required=True
    )
    validate_expand_evidence_parser.add_argument("--post-catalog", required=True)
    validate_expand_evidence_parser.add_argument("--evidence", required=True)

    expand_journal_clear = subparsers.add_parser("clear-expand-journal")
    expand_journal_clear.add_argument("--journal", required=True)

    migration = subparsers.add_parser("validate-migration")
    migration.add_argument("--spec", required=True)
    migration.add_argument("--heads", required=True)
    migration.add_argument("--current", required=True)

    write_deploy_journal = subparsers.add_parser("write-journal")
    write_deploy_journal.add_argument("--journal", required=True)
    write_deploy_journal.add_argument("--state", required=True, choices=JOURNAL_STATES)
    write_deploy_journal.add_argument("--expected-sha", required=True)
    write_deploy_journal.add_argument("--trusted-bundle-sha256", required=True)
    write_deploy_journal.add_argument("--container-name", required=True)
    write_deploy_journal.add_argument("--backup-name", required=True)
    write_deploy_journal.add_argument("--candidate-name", required=True)
    write_deploy_journal.add_argument("--old-container-id", required=True)
    write_deploy_journal.add_argument("--candidate-container-id", required=True)
    write_deploy_journal.add_argument("--old-image-id", required=True)
    write_deploy_journal.add_argument("--candidate-image-id", required=True)

    read_deploy_journal = subparsers.add_parser("read-journal")
    read_deploy_journal.add_argument("--journal", required=True)
    read_deploy_journal.add_argument("--output", required=True)

    clear_deploy_journal = subparsers.add_parser("clear-journal")
    clear_deploy_journal.add_argument("--journal", required=True)

    recovery = subparsers.add_parser("plan-recovery")
    recovery.add_argument("--journal", required=True)
    recovery.add_argument("--official")
    recovery.add_argument("--backup")
    recovery.add_argument("--named-candidate")
    recovery.add_argument("--output", required=True)

    orphan_cleanup = subparsers.add_parser("plan-orphan-cleanup")
    orphan_cleanup.add_argument("--inspects", required=True)
    orphan_cleanup.add_argument("--output", required=True)

    backup_retention = subparsers.add_parser("plan-backup-retention")
    backup_retention.add_argument("--inspects", required=True)
    backup_retention.add_argument("--retained-backup-id", required=True)
    backup_retention.add_argument("--output", required=True)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        spec = None
        if hasattr(args, "spec"):
            spec = load_spec(args.spec)
        if args.command == "validate-spec":
            print("production container spec is valid")
            return 0
        if args.command == "emit-spec":
            write_nul_records(args.output, emitted_spec_values(spec))
            return 0
        if args.command == "snapshot-env":
            snapshot_env_file(spec, args.source, args.output)
            return 0
        if args.command == "snapshot-database-probe-env":
            snapshot_database_probe_env_file(
                spec,
                args.source,
                args.application_env,
                args.output,
            )
            return 0
        if args.command == "snapshot-database-migration-env":
            snapshot_database_migration_env_file(
                spec,
                args.source,
                args.application_env,
                args.output,
            )
            return 0
        if args.command == "create-args":
            env_values = parse_env_file(args.env_file)
            del env_values
            one_shot = args.one_shot_command or None
            if one_shot and one_shot[0] == "--":
                one_shot = one_shot[1:]
            write_arguments(
                args.output,
                create_arguments(
                    spec,
                    args.name,
                    args.image,
                    args.env_file,
                    args.expected_sha,
                    one_shot,
                    image_reference=args.image_ref,
                    env_source=args.env_source,
                    run_id=args.run_id,
                    role=args.role,
                ),
            )
            return 0
        if args.command == "emit-lifecycle-labels":
            write_arguments(
                args.output,
                deployment_label_arguments(
                    args.name,
                    args.image,
                    args.expected_sha,
                    args.run_id,
                    args.role,
                ),
            )
            return 0
        if args.command == "validate-expand-restore-volume-inspect":
            values = owner_only_object_list(args.inspect, "restore volume inspect")
            if len(values) != 1:
                raise DeployGuardError(
                    "restore volume inspect must contain exactly one object"
                )
            validate_restore_volume_inspect(
                values[0],
                args.name,
                args.expected_sha,
                args.run_id,
                args.image_id,
            )
            print("restore volume is bound to the exact isolated execution")
            return 0
        if args.command == "plan-expand-restore-volume-cleanup":
            write_nul_records(
                args.output,
                plan_restore_volume_cleanup(
                    owner_only_object_list(
                        args.inspects,
                        "restore volume inspect list",
                    )
                ),
            )
            return 0
        if args.command == "validate-inspects":
            validate_inspects(
                spec,
                one_object(args.old_container, "old container"),
                one_object(args.old_image, "old image"),
                one_object(args.candidate_container, "candidate container"),
                one_object(args.candidate_image, "candidate image"),
                parse_env_file(args.env_file),
                args.expected_sha,
            )
            print("production container recreation is exact")
            return 0
        if args.command == "scan-image":
            env_values = parse_env_file(args.env_file)
            validate_candidate_image_secret_boundary(
                one_owner_only_object(
                    args.image_inspect,
                    "owner-only candidate image inspect",
                ),
                env_values,
                args.expected_image_id,
            )
            scan_owner_only_image_archive(
                args.image_archive,
                env_values,
                args.expected_image_id,
            )
            return 0
        if args.command == "validate-source-snapshot":
            count = validate_source_snapshot(args.manifest, args.source_root)
            print("source snapshot matches exact Git tree: files={0}".format(count))
            return 0
        if args.command == "emit-migration-probe":
            emit_migration_probe(args.output)
            return 0
        if args.command == "extract-expand-migration-source":
            extract_expand_migration_source(
                load_owner_only_migration_manifest(
                    args.old_manifest,
                    "owner-only running-image migration manifest",
                ),
                load_owner_only_migration_manifest(
                    args.candidate_manifest,
                    "owner-only candidate-image migration manifest",
                ),
                args.source_root,
                args.output,
            )
            return 0
        if args.command in (
            "emit-reference-schema-materializer",
            "validate-reference-materializer-result",
            "validate-expand-reference-materializer-result",
            "emit-reference-catalog-probe",
            "emit-database-schema-probe",
            "validate-database-schema",
        ):
            candidate_manifest = load_owner_only_migration_manifest(
                args.candidate_manifest,
                "owner-only candidate-image migration manifest",
            )
        if args.command == "emit-reference-schema-materializer":
            emit_reference_schema_materializer(
                args.output,
                candidate_manifest,
            )
            return 0
        if args.command == "validate-reference-materializer-result":
            result = load_owner_only_reference_materializer_result(
                args.result,
                candidate_manifest,
            )
            print(
                "reference schema materializer is exact: tables={0}".format(
                    result["table_count"]
                )
            )
            return 0
        if args.command == "validate-expand-reference-materializer-result":
            result = load_owner_only_expand_reference_materializer_result(
                args.result,
                candidate_manifest,
            )
            print(
                "expand reference schema materializer is exact: tables={0}".format(
                    result["table_count"]
                )
            )
            return 0
        if args.command == "emit-reference-catalog-probe":
            emit_reference_catalog_probe(
                args.output,
                candidate_manifest,
            )
            return 0
        if args.command == "emit-database-schema-probe":
            reference_catalog = load_owner_only_reference_catalog(
                args.reference_catalog,
                candidate_manifest,
            )
            emit_database_schema_probe(
                args.output,
                candidate_manifest,
                reference_catalog,
            )
            return 0
        if args.command == "validate-database-schema":
            reference_catalog = load_owner_only_reference_catalog(
                args.reference_catalog,
                candidate_manifest,
            )
            result = validate_database_schema(
                candidate_manifest,
                reference_catalog,
                load_owner_only_database_schema_result(args.database_catalog),
            )
            print(
                "database schema matches exact reference catalog: tables={0} digest={1}".format(
                    result["table_count"],
                    result["reference_catalog_sha256"],
                )
            )
            return 0
        if args.command == "validate-expand-migration":
            plan = validate_expand_migration_source(
                read_expand_migration_source(args.migration_source),
                load_owner_only_migration_manifest(
                    args.old_manifest,
                    "owner-only running-image migration manifest",
                ),
                load_owner_only_migration_manifest(
                    args.candidate_manifest,
                    "owner-only candidate-image migration manifest",
                ),
            )
            write_exclusive_bytes(
                args.output,
                (
                    json.dumps(plan, ensure_ascii=True, separators=(",", ":"))
                    + "\n"
                ).encode("utf-8"),
            )
            return 0
        if args.command == "emit-expand-transaction-runner":
            emit_expand_transaction_runner(
                args.output,
                load_owner_only_expand_migration_plan(args.plan),
            )
            return 0
        if args.command == "read-expand-migration-plan":
            write_nul_records(
                args.output,
                emitted_expand_migration_plan_values(
                    load_owner_only_expand_migration_plan(args.plan)
                ),
            )
            return 0
        if args.command == "emit-expected-expand-transaction-result":
            emit_expected_expand_transaction_result(
                args.output,
                load_owner_only_expand_migration_plan(args.plan),
            )
            return 0
        if args.command == "validate-expand-transaction-result":
            plan = load_owner_only_expand_migration_plan(args.plan)
            load_owner_only_expand_transaction_result(args.result, plan)
            print("expand migration transaction result is exact")
            return 0
        if args.command == "emit-expand-old-app-compat-probe":
            emit_expand_old_app_compat_probe(
                args.output,
                load_owner_only_migration_manifest(
                    args.old_manifest,
                    "owner-only running-image migration manifest",
                ),
                load_owner_only_expand_migration_plan(args.plan),
            )
            return 0
        if args.command == "validate-expand-old-app-compat-result":
            load_owner_only_expand_old_app_compat_result(
                args.result,
                load_owner_only_migration_manifest(
                    args.old_manifest,
                    "owner-only running-image migration manifest",
                ),
                load_owner_only_expand_migration_plan(args.plan),
            )
            print("old application CRUD is compatible with the expanded schema")
            return 0
        if args.command == "emit-expected-expand-old-app-compat-result":
            emit_expected_expand_old_app_compat_result(
                args.output,
                load_owner_only_migration_manifest(
                    args.old_manifest,
                    "owner-only running-image migration manifest",
                ),
                load_owner_only_expand_migration_plan(args.plan),
            )
            return 0
        if args.command == "validate-expand-catalog-transition":
            old_manifest = load_owner_only_migration_manifest(
                args.old_manifest,
                "owner-only running-image migration manifest",
            )
            candidate_manifest = load_owner_only_migration_manifest(
                args.candidate_manifest,
                "owner-only candidate-image migration manifest",
            )
            result = validate_expand_catalog_transition(
                old_manifest,
                candidate_manifest,
                load_owner_only_reference_catalog(args.old_catalog, old_manifest),
                load_owner_only_reference_catalog(
                    args.migrated_catalog, candidate_manifest
                ),
                load_owner_only_reference_catalog(
                    args.candidate_reference_catalog, candidate_manifest
                ),
                load_owner_only_expand_migration_plan(args.plan),
            )
            print(
                "expand migration catalog transition is exact: old={0} candidate={1}".format(
                    result["old_catalog_sha256"],
                    result["candidate_catalog_sha256"],
                )
            )
            return 0
        if args.command == "emit-expand-approval-plan":
            old_manifest = load_owner_only_migration_manifest(
                args.old_manifest,
                "owner-only running-image migration manifest",
            )
            candidate_manifest = load_owner_only_migration_manifest(
                args.candidate_manifest,
                "owner-only candidate-image migration manifest",
            )
            migration_plan = load_owner_only_expand_migration_plan(args.plan)
            value = build_expand_approval_plan(
                args.expected_main_sha,
                args.trusted_bundle_sha256,
                old_manifest,
                candidate_manifest,
                load_owner_only_reference_catalog(args.old_catalog, old_manifest),
                load_owner_only_reference_catalog(
                    args.candidate_catalog,
                    candidate_manifest,
                ),
                migration_plan,
            )
            write_exclusive_bytes(
                args.output,
                (
                    json.dumps(value, ensure_ascii=True, separators=(",", ":"))
                    + "\n"
                ).encode("utf-8"),
            )
            return 0
        if args.command == "validate-expand-approval-plan":
            load_owner_only_expand_approval_plan(
                args.approval_plan,
                load_owner_only_expand_migration_plan(args.plan),
            )
            print("expand approval plan is exact")
            return 0
        if args.command == "attest-expand-backup":
            value = attest_expand_backup(args.backup, args.toc)
            write_exclusive_bytes(
                args.output,
                (
                    json.dumps(value, ensure_ascii=True, separators=(",", ":"))
                    + "\n"
                ).encode("utf-8"),
            )
            return 0
        if args.command == "attest-expand-restore-volume":
            volume_inspects = owner_only_object_list(
                args.inspect,
                "restore volume inspect",
            )
            if len(volume_inspects) != 1:
                raise DeployGuardError(
                    "restore volume inspect must contain exactly one object"
                )
            try:
                backup_attestation = json.loads(
                    read_owner_only_bytes(
                        args.backup_attestation,
                        "owner-only expand backup attestation",
                        maximum_bytes=MAX_EXPAND_JOURNAL_BYTES,
                    ).decode("utf-8")
                )
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise DeployGuardError(
                    "expand backup attestation is not valid JSON"
                ) from exc
            value = build_expand_restore_volume_attestation(
                volume_inspects[0],
                _owner_only_text(
                    args.database_size,
                    "owner-only production database size result",
                    MAX_EXPAND_RESTORE_CAPACITY_OUTPUT_BYTES,
                ),
                _owner_only_text(
                    args.capacity,
                    "owner-only restore volume capacity result",
                    MAX_EXPAND_RESTORE_CAPACITY_OUTPUT_BYTES,
                ),
                backup_attestation,
                args.expected_sha,
                args.run_id,
                args.image_id,
            )
            write_exclusive_bytes(
                args.output,
                (
                    json.dumps(value, ensure_ascii=True, separators=(",", ":"))
                    + "\n"
                ).encode("utf-8"),
            )
            return 0
        if args.command == "validate-expand-backup-binding":
            try:
                backup_attestation = json.loads(
                    read_owner_only_bytes(
                        args.backup_attestation,
                        "owner-only expand backup attestation",
                        maximum_bytes=MAX_EXPAND_JOURNAL_BYTES,
                    ).decode("utf-8")
                )
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise DeployGuardError(
                    "expand backup attestation is not valid JSON"
                ) from exc
            validate_expand_backup_binding(
                load_expand_journal(args.journal),
                backup_attestation,
            )
            print("expand backup still matches its journal attestation")
            return 0
        if args.command == "start-expand-journal":
            migration_plan = load_owner_only_expand_migration_plan(args.plan)
            approval_plan = load_owner_only_expand_approval_plan(
                args.approval_plan,
                migration_plan,
            )
            approval_digest = owner_only_file_sha256(
                args.approval_plan,
                "owner-only expand approval plan",
                MAX_EXPAND_APPROVAL_PLAN_BYTES,
            )["sha256"]
            write_expand_journal(
                args.journal,
                build_expand_journal(
                    approval_plan,
                    approval_digest,
                    migration_plan,
                    args.backup_path,
                    args.old_image_id,
                    args.candidate_image_id,
                ),
            )
            return 0
        if args.command == "advance-expand-journal":
            backup_attestation = None
            restore_volume_attestation = None
            if args.backup_attestation is not None:
                try:
                    backup_attestation = json.loads(
                        read_owner_only_bytes(
                            args.backup_attestation,
                            "owner-only expand backup attestation",
                            maximum_bytes=MAX_EXPAND_JOURNAL_BYTES,
                        ).decode("utf-8")
                    )
                except (UnicodeError, json.JSONDecodeError) as exc:
                    raise DeployGuardError(
                        "expand backup attestation is not valid JSON"
                    ) from exc
                validate_expand_backup_attestation(backup_attestation)
            if args.restore_volume_attestation is not None:
                restore_volume_attestation = (
                    load_owner_only_expand_restore_volume_attestation(
                        args.restore_volume_attestation
                    )
                )
            if (args.state == "backup_verified") is not (
                backup_attestation is not None
            ):
                raise DeployGuardError(
                    "backup_verified requires exactly one backup attestation"
                )
            if (args.state == "restore_verified") is not (
                restore_volume_attestation is not None
            ):
                raise DeployGuardError(
                    "restore_verified requires exactly one restore volume attestation"
                )
            advance_expand_journal(
                args.journal,
                args.state,
                backup_attestation,
                restore_volume_attestation,
            )
            return 0
        if args.command == "read-expand-journal":
            write_nul_records(
                args.output,
                emitted_expand_journal_values(load_expand_journal(args.journal)),
            )
            return 0
        if args.command == "validate-expand-journal-binding":
            migration_plan = load_owner_only_expand_migration_plan(args.plan)
            approval_plan = load_owner_only_expand_approval_plan(
                args.approval_plan,
                migration_plan,
            )
            approval_digest = owner_only_file_sha256(
                args.approval_plan,
                "owner-only expand approval plan",
                MAX_EXPAND_APPROVAL_PLAN_BYTES,
            )["sha256"]
            validate_expand_journal_binding(
                load_expand_journal(args.journal),
                approval_plan,
                approval_digest,
                migration_plan,
                args.backup_path,
                args.old_image_id,
                args.candidate_image_id,
            )
            print("expand migration journal is bound to the exact approved release")
            return 0
        if args.command == "validate-expand-observed-head":
            observed = parse_expand_observed_head(
                _owner_only_text(
                    args.input,
                    "owner-only production Alembic head result",
                    MAX_MIGRATION_OUTPUT_BYTES,
                ),
                load_owner_only_expand_migration_plan(args.plan),
            )
            write_nul_records(args.output, [observed])
            return 0
        if args.command == "plan-expand-recovery":
            action = plan_expand_recovery(
                load_expand_journal(args.journal),
                args.observed_head,
                args.observed_catalog_sha256,
            )
            write_nul_records(args.output, [action])
            return 0
        if args.command == "plan-expand-recovery-catalog":
            observed_manifest = load_owner_only_migration_manifest(
                args.observed_manifest,
                "owner-only observed schema migration manifest",
            )
            action = plan_expand_recovery_catalog(
                load_expand_journal(args.journal),
                args.observed_head,
                observed_manifest,
                load_owner_only_reference_catalog(
                    args.observed_catalog,
                    observed_manifest,
                ),
            )
            write_nul_records(args.output, [action])
            return 0
        if args.command == "reset-unverified-expand-backup":
            reset_unverified_expand_backup(args.journal)
            return 0
        if args.command in ("write-expand-evidence", "validate-expand-evidence"):
            migration_plan = load_owner_only_expand_migration_plan(args.plan)
            old_manifest = load_owner_only_migration_manifest(
                args.old_manifest,
                "owner-only running-image migration manifest",
            )
            load_owner_only_expand_transaction_result(
                args.rehearsal_transaction_result,
                migration_plan,
            )
            rehearsal_transaction_digest = owner_only_file_sha256(
                args.rehearsal_transaction_result,
                "owner-only rehearsal transaction result",
                MAX_DATABASE_SCHEMA_RESULT_BYTES,
            )["sha256"]
            load_owner_only_expand_old_app_compat_result(
                args.old_app_compat_result,
                old_manifest,
                migration_plan,
            )
            old_app_compat_digest = owner_only_file_sha256(
                args.old_app_compat_result,
                "owner-only old application CRUD compatibility result",
                MAX_DATABASE_SCHEMA_RESULT_BYTES,
            )["sha256"]
            load_owner_only_expand_transaction_result(
                args.transaction_result,
                migration_plan,
            )
            transaction_digest = owner_only_file_sha256(
                args.transaction_result,
                "owner-only expand transaction result",
                MAX_DATABASE_SCHEMA_RESULT_BYTES,
            )["sha256"]
            candidate_manifest = load_owner_only_migration_manifest(
                args.candidate_manifest,
                "owner-only candidate-image migration manifest",
            )
            post_catalog = load_owner_only_reference_catalog(
                args.post_catalog,
                candidate_manifest,
            )
            expected_evidence = build_expand_evidence(
                load_expand_journal(args.journal),
                migration_plan,
                rehearsal_transaction_digest,
                old_app_compat_digest,
                transaction_digest,
                reference_catalog_sha256(post_catalog),
            )
            if args.command == "write-expand-evidence":
                write_expand_evidence(args.output, expected_evidence)
            else:
                load_owner_only_expand_evidence(args.evidence, expected_evidence)
                print("expand migration evidence matches the exact release")
            return 0
        if args.command == "clear-expand-journal":
            clear_expand_journal(args.journal)
            return 0
        if args.command == "validate-no-migration-delta":
            revisions = validate_no_migration_delta(
                load_owner_only_migration_manifest(
                    args.old_manifest,
                    "owner-only running-image migration manifest",
                ),
                load_owner_only_migration_manifest(
                    args.candidate_manifest,
                    "owner-only candidate-image migration manifest",
                ),
                _owner_only_text(
                    args.heads,
                    "owner-only Alembic heads output",
                    MAX_MIGRATION_OUTPUT_BYTES,
                ),
                _owner_only_text(
                    args.current,
                    "owner-only Alembic current output",
                    MAX_MIGRATION_OUTPUT_BYTES,
                ),
            )
            print("no migration delta; database is at head: {0}".format(revisions[0]))
            return 0
        if args.command == "validate-migration":
            heads = Path(args.heads).read_text(encoding="utf-8")
            current = Path(args.current).read_text(encoding="utf-8")
            revisions = validate_migration_outputs(heads, current)
            print("database is at Alembic heads: {0}".format(",".join(revisions)))
            return 0
        if args.command == "write-journal":
            write_journal(
                args.journal,
                {
                    "schema_version": JOURNAL_SCHEMA_VERSION,
                    "state": args.state,
                    "expected_sha": args.expected_sha,
                    "trusted_bundle_sha256": args.trusted_bundle_sha256,
                    "container_name": args.container_name,
                    "backup_name": args.backup_name,
                    "candidate_name": args.candidate_name,
                    "old_container_id": args.old_container_id,
                    "candidate_container_id": args.candidate_container_id,
                    "old_image_id": args.old_image_id,
                    "candidate_image_id": args.candidate_image_id,
                },
            )
            return 0
        if args.command == "read-journal":
            write_nul_records(args.output, emitted_journal_values(load_journal(args.journal)))
            return 0
        if args.command == "clear-journal":
            clear_journal(args.journal)
            return 0
        if args.command == "plan-recovery":
            actions = plan_recovery(
                load_journal(args.journal),
                official=optional_object(args.official, "official container"),
                backup=optional_object(args.backup, "backup container"),
                named_candidate=optional_object(
                    args.named_candidate, "named candidate container"
                ),
            )
            write_nul_records(args.output, actions)
            return 0
        if args.command == "plan-orphan-cleanup":
            write_nul_records(
                args.output,
                plan_orphan_cleanup(
                    owner_only_object_list(
                        args.inspects,
                        "owner-only managed orphan inspect collection",
                    )
                ),
            )
            return 0
        if args.command == "plan-backup-retention":
            write_nul_records(
                args.output,
                plan_backup_retention(
                    owner_only_object_list(
                        args.inspects,
                        "owner-only backup retention inspect collection",
                    ),
                    args.retained_backup_id,
                ),
            )
            return 0
        raise AssertionError(args.command)
    except (DeployGuardError, OSError, UnicodeError) as exc:
        print("PRODUCTION DEPLOY GUARD: FAILED: {0}".format(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
