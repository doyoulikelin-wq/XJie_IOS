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
    "database_probe_image",
    "container_health_url",
    "public_health_url",
)
PINNED_SPEC = {
    "schema_version": 1,
    "container_name": "xjie-api",
    "image_repository": "xjie-backend",
    "secret_env_file": "/home/mayl/.config/xjie/backend.env",
    "restart_policy": "unless-stopped",
    "published_ports": ["127.0.0.1:8000:8000"],
    "extra_hosts": ["host.docker.internal:host-gateway"],
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
)
DEPLOY_ROLE_COMMANDS = {
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
}
CANDIDATE_COMMAND = (
    "uvicorn",
    "app.main:app",
    "--host",
    "0.0.0.0",
    "--port",
    "8000",
)
RUNTIME_ENV_ROLES = frozenset(
    {
        "candidate",
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
    }
)
REFERENCE_SCHEMA_ROLES = frozenset(
    {
        "schema-reference-server",
        "schema-reference-materializer",
        "schema-reference-catalog",
    }
)
HARDENED_PROBE_ROLES = frozenset(
    {
        "database-schema",
        "literature-ingest",
        "schema-old",
        "schema-candidate",
        *REFERENCE_SCHEMA_ROLES,
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
    }
)
SCHEMA_PROBE_TMPFS = {"/tmp": "rw,noexec,nosuid,nodev,size=16m"}
SCHEMA_PROBE_TMPFS_ARGUMENT = "/tmp:" + SCHEMA_PROBE_TMPFS["/tmp"]
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
REFERENCE_CATALOG_TMPFS = dict(DATABASE_PROBE_TMPFS)
REFERENCE_SOCKET_SOURCE = re.compile(
    r"/dev/shm/xjie-deploy-[0-9]+/runtime/reference-pg-socket\Z"
)
REFERENCE_SOCKET_DESTINATION = "/var/run/postgresql"
REFERENCE_DATABASE_URI = re.compile(
    r"postgresql\+psycopg://xjie_reference:([0-9a-f]{64})@/xjie_reference"
    r"\?host=/var/run/postgresql\Z"
)
REFERENCE_ROLE_RESOURCES = {
    "database-schema": ("70:70", None, 256 * 1024 * 1024, 128),
    "schema-reference-server": ("70:70", 20, 512 * 1024 * 1024, 256),
    "schema-reference-materializer": (
        "65534:65534",
        None,
        512 * 1024 * 1024,
        256,
    ),
    "schema-reference-catalog": ("70:70", None, 256 * 1024 * 1024, 128),
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
REFERENCE_SCHEMA_TABLE_COUNT = 53
REFERENCE_MATERIALIZER_RESULT_KEYS = (
    "schema_version",
    "candidate_manifest_sha256",
    "table_count",
)
MAX_DATABASE_SCHEMA_RESULT_BYTES = 64 * 1024
DATABASE_PROBE_URL_KEY = "DATABASE_PROBE_URL"
DATABASE_PROBE_PGOPTIONS = "-c default_transaction_read_only=on"
REFERENCE_DATABASE_URL_KEY = "XJIE_REFERENCE_DATABASE_URL"
REFERENCE_DATABASE_USER = "xjie_reference"
REFERENCE_DATABASE_NAME = "xjie_reference"
REFERENCE_DATABASE_SOCKET = "/var/run/postgresql"
PINNED_POSTGRESQL_MAJOR = 16
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
    return {
        "class": _qualified_name(type(value)),
        "sql": sql,
        "cache_key": _json_value(getattr(value, "_static_cache_key", None)),
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
    if role not in DEPLOY_ROLES:
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
            else SCHEMA_PROBE_TMPFS
        )
        for destination, options in sorted(expected_tmpfs.items()):
            args.extend(("--tmpfs", destination + ":" + options))
    if one_shot_command is None:
        args.extend(("--restart", spec["restart_policy"]))
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
    if role == "schema-reference-server":
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
    if role == "schema-reference-server":
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
            and environment.get(name) != expected
        ):
            raise DeployGuardError(
                "managed orphan image environment invariant is missing"
            )
    if role in REFERENCE_SCHEMA_ROLES:
        _require_reference_environment(environment, role)
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
        "Name": PINNED_SPEC["restart_policy"] if role == "candidate" else "no",
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
        if role in RUNTIME_ENV_ROLES
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
    elif role == "schema-reference-server":
        expected_tmpfs = REFERENCE_SERVER_TMPFS
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
    if cap_add:
        raise DeployGuardError("managed orphan adds capabilities")

    expected_security = ["no-new-privileges"] if hardened else []
    security_options = _normalized_optional_string_list(
        host.get("SecurityOpt"), "managed orphan SecurityOpt"
    )
    if not exact_json(security_options, expected_security):
        raise DeployGuardError("managed orphan security options are invalid")

    if role in REFERENCE_SCHEMA_ROLES:
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
    if role in REFERENCE_SCHEMA_ROLES:
        if not isinstance(mounts, list) or len(mounts) != 1:
            raise DeployGuardError("managed reference orphan mount is invalid")
        mount = mounts[0]
        expected_mode = "" if role == "schema-reference-server" else "ro"
        expected_rw = role == "schema-reference-server"
        if (
            not isinstance(mount, dict)
            or set(mount)
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
        normalized_mounts = [dict(mount)]
    else:
        if not isinstance(mounts, list) or mounts:
            raise DeployGuardError("managed orphan mounts are not empty")
        normalized_mounts = []
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
    officials = [item for item in identities if item["official"]]
    backups = [item for item in identities if item["backup"]]
    others = [
        item for item in identities if not item["official"] and not item["backup"]
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
    lifecycle_labels.add_argument("--role", required=True, choices=DEPLOY_ROLES)
    lifecycle_labels.add_argument("--output", required=True)

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
        if args.command in (
            "emit-reference-schema-materializer",
            "validate-reference-materializer-result",
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
