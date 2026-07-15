#!/usr/bin/python3 -I
"""Root-only transactional installer for the production deployment trust bundle."""

from __future__ import annotations

import ctypes
import fcntl
import hashlib
import json
import os
import pwd
import re
import resource
import stat
import subprocess
import sys
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


TRUSTED_INSTALLER = "/usr/local/sbin/xjie-production-install"
TRUSTED_LAUNCHER = "/usr/local/sbin/xjie-production-launch"
TRUSTED_ENTRYPOINT = "/usr/local/sbin/xjie-production-deploy"
TRUSTED_BUNDLE_DIR = "/usr/local/libexec/xjie-production-deploy"
TRUSTED_SPEC = TRUSTED_BUNDLE_DIR + "/production_container.json"
TRUSTED_DEPLOY_GUARD = TRUSTED_BUNDLE_DIR + "/production_deploy_guard.py"
TRUSTED_RELEASE_GATE = TRUSTED_BUNDLE_DIR + "/run_regression_gate.py"
TRUSTED_TEST_INVENTORY = TRUSTED_BUNDLE_DIR + "/expected_python_tests.json"
APPROVAL_MANIFEST = "/etc/xjie-production-deploy/bundle-approval.json"
STATE_DIR = "/var/lib/xjie-production-deploy"
INSTALL_JOURNAL = STATE_DIR + "/bundle-install.json"
CUTOVER_JOURNAL = "/home/mayl/.locks/xjie-production-cutover.json"
DEPLOY_PRINCIPAL = "mayl"
DOCKER_BINARY = "/usr/bin/docker"
INSTALLER_ROOT_LOCK_FD = 9
INSTALLER_LEGACY_LOCK_FD = 11
INSTALLER_AUTHORITY_FD = 12
INSTALLER_AUTHORITY_MARKER = b"XJIE_BUNDLE_INSTALLER_DOCTOR_V1\0"
PR_SET_DUMPABLE = 4
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_MANIFEST_BYTES = 64 * 1024
MAX_JOURNAL_BYTES = 128 * 1024
SHA1_PATTERN = re.compile(r"[0-9a-f]{40}\Z")
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class BundleSpec:
    source: str
    destination: str
    mode: int


BUNDLE_SPECS = (
    BundleSpec(
        "scripts/launch_production_deploy.py",
        TRUSTED_LAUNCHER,
        0o555,
    ),
    BundleSpec(
        "scripts/deploy_literature.sh",
        TRUSTED_ENTRYPOINT,
        0o555,
    ),
    BundleSpec(
        "backend/deploy/production_container.json",
        TRUSTED_SPEC,
        0o444,
    ),
    BundleSpec(
        "backend/deploy/production_deploy_guard.py",
        TRUSTED_DEPLOY_GUARD,
        0o444,
    ),
    BundleSpec(
        "tools/run_regression_gate.py",
        TRUSTED_RELEASE_GATE,
        0o444,
    ),
    BundleSpec(
        "quality/expected_python_tests.json",
        TRUSTED_TEST_INVENTORY,
        0o444,
    ),
    # Keep the currently executing recovery implementation installed until
    # every other target has been durably replaced.
    BundleSpec(
        "scripts/install_production_deploy_bundle.py",
        TRUSTED_INSTALLER,
        0o555,
    ),
)

MANIFEST_KEYS = ("schema_version", "expected_main_sha", "files")
MANIFEST_FILE_KEYS = ("source", "destination", "mode", "sha256")
JOURNAL_KEYS = (
    "schema_version",
    "state",
    "expected_main_sha",
    "approval_sha256",
    "old_bundle_sha256",
    "new_bundle_sha256",
    "staged_count",
    "replaced_count",
    "rollback_count",
    "files",
)
JOURNAL_FILE_KEYS = (
    "source",
    "destination",
    "mode",
    "old_sha256",
    "new_sha256",
    "stage",
    "backup",
)
JOURNAL_STATES = (
    "planned",
    "staging",
    "prepared",
    "replacing",
    "verifying",
    "verified",
    "rolling_back",
)
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


class InstallError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise InstallError(message)


def identity(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_uid,
        metadata.st_gid,
        metadata.st_nlink,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def write_all(descriptor: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        written = os.write(descriptor, payload[offset:])
        require(written > 0, "short write while persisting the bundle transaction")
        offset += written


def read_all(descriptor: int, maximum: int, label: str) -> bytes:
    payload = bytearray()
    while True:
        remaining = maximum + 1 - len(payload)
        require(remaining > 0, label + " exceeds its size limit")
        chunk = os.read(descriptor, min(1024 * 1024, remaining))
        if not chunk:
            return bytes(payload)
        payload.extend(chunk)
        require(len(payload) <= maximum, label + " exceeds its size limit")


@dataclass
class StableFile:
    path: str
    descriptor: int
    metadata: os.stat_result
    payload: bytes

    def assert_unchanged(self, label: str) -> None:
        observed = os.fstat(self.descriptor)
        require(identity(observed) == identity(self.metadata), label + " changed after read")
        try:
            path_metadata = os.stat(self.path, follow_symlinks=False)
        except FileNotFoundError as exc:
            raise InstallError(label + " disappeared after read") from exc
        require(
            (path_metadata.st_dev, path_metadata.st_ino)
            == (self.metadata.st_dev, self.metadata.st_ino),
            label + " path identity changed after read",
        )

    def close(self) -> None:
        os.close(self.descriptor)


def open_stable_root_file(
    path: str,
    *,
    expected_mode: int | None,
    maximum: int,
    label: str,
    allow_any_safe_mode: bool = False,
) -> StableFile:
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        before = os.fstat(descriptor)
        mode = stat.S_IMODE(before.st_mode)
        require(stat.S_ISREG(before.st_mode), label + " is not a regular file")
        require(before.st_uid == 0 and before.st_gid == 0, label + " is not root:root")
        require(before.st_nlink == 1, label + " has an unsafe hard-link count")
        if expected_mode is not None:
            require(mode == expected_mode, label + " mode is not exact")
        if allow_any_safe_mode:
            require(mode & 0o022 == 0, label + " is group/other writable")
        payload = read_all(descriptor, maximum, label)
        after = os.fstat(descriptor)
        require(identity(before) == identity(after), label + " changed while read")
        require(len(payload) == before.st_size, label + " size changed while read")
        path_metadata = os.stat(path, follow_symlinks=False)
        require(
            (path_metadata.st_dev, path_metadata.st_ino)
            == (before.st_dev, before.st_ino),
            label + " path changed while read",
        )
        return StableFile(path, descriptor, before, payload)
    except BaseException:
        os.close(descriptor)
        raise


def validate_root_directory(path: str, label: str) -> None:
    metadata = os.lstat(path)
    require(stat.S_ISDIR(metadata.st_mode), label + " is not a directory")
    require(not stat.S_ISLNK(metadata.st_mode), label + " is a symbolic link")
    require(metadata.st_uid == 0 and metadata.st_gid == 0, label + " is not root:root")
    require(stat.S_IMODE(metadata.st_mode) & 0o022 == 0, label + " is group/other writable")


def validate_root_directory_chain(path: str, label: str) -> str:
    require(os.path.isabs(path), label + " must be absolute")
    normalized = os.path.normpath(path)
    require(normalized == path, label + " must be normalized")
    validate_root_directory("/", label + " ancestor /")
    current = ""
    for component in Path(path).parts[1:]:
        current += "/" + component
        validate_root_directory(current, label + " ancestor " + current)
    return normalized


def ensure_state_directory(path: str = STATE_DIR) -> None:
    parent = os.path.dirname(path)
    validate_root_directory_chain(parent, "installer state parent")
    parent_descriptor = os.open(
        parent,
        os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
    )
    created = False
    try:
        try:
            os.mkdir(os.path.basename(path), 0o700, dir_fd=parent_descriptor)
            created = True
        except FileExistsError:
            pass
        if created:
            os.fsync(parent_descriptor)
    finally:
        os.close(parent_descriptor)
    metadata = os.lstat(path)
    require(stat.S_ISDIR(metadata.st_mode), "installer state path is not a directory")
    require(not stat.S_ISLNK(metadata.st_mode), "installer state path is a symbolic link")
    require(
        metadata.st_uid == 0
        and metadata.st_gid == 0
        and stat.S_IMODE(metadata.st_mode) == 0o700,
        "installer state directory identity is invalid",
    )
    if created:
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
        )
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def strict_json(payload: bytes, label: str) -> dict:
    def pairs_hook(pairs):
        keys = [key for key, _ in pairs]
        if len(keys) != len(set(keys)):
            raise InstallError(label + " contains duplicate JSON keys")
        return dict(pairs)

    try:
        value = json.loads(payload, object_pairs_hook=pairs_hook)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InstallError(label + " is not valid UTF-8 JSON") from exc
    require(type(value) is dict, label + " must be a JSON object")
    return value


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def bundle_sha256(entries: list[tuple[str, bytes]]) -> str:
    digest = hashlib.sha256()
    for destination, payload in entries:
        encoded_path = destination.encode("utf-8")
        digest.update(len(encoded_path).to_bytes(8, "big"))
        digest.update(encoded_path)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def artifact_paths(destination: str) -> tuple[str, str]:
    parent = os.path.dirname(destination)
    basename = os.path.basename(destination)
    return (
        os.path.join(parent, "." + basename + ".xjie-install-stage"),
        os.path.join(parent, "." + basename + ".xjie-install-backup"),
    )


def load_approval_manifest(
    expected_main_sha: str,
    path: str = APPROVAL_MANIFEST,
) -> tuple[StableFile, dict]:
    validate_root_directory_chain(os.path.dirname(path), "approval manifest parent")
    stable = open_stable_root_file(
        path,
        expected_mode=0o400,
        maximum=MAX_MANIFEST_BYTES,
        label="approval manifest",
    )
    try:
        manifest = strict_json(stable.payload, "approval manifest")
        require(tuple(manifest) == MANIFEST_KEYS, "approval manifest keys/order are invalid")
        require(
            type(manifest["schema_version"]) is int
            and manifest["schema_version"] == 1,
            "approval manifest schema is invalid",
        )
        require(
            type(manifest["expected_main_sha"]) is str
            and SHA1_PATTERN.fullmatch(manifest["expected_main_sha"]) is not None,
            "approval manifest expected_main_sha is invalid",
        )
        require(
            manifest["expected_main_sha"] == expected_main_sha,
            "approval manifest is bound to a different main SHA",
        )
        files = manifest["files"]
        require(type(files) is list and len(files) == len(BUNDLE_SPECS), "approval manifest must contain exactly seven files")
        for index, (entry, spec) in enumerate(zip(files, BUNDLE_SPECS)):
            require(type(entry) is dict, "approval file entry is not an object")
            require(tuple(entry) == MANIFEST_FILE_KEYS, "approval file keys/order are invalid")
            require(entry["source"] == spec.source, "approval source order/path is invalid")
            require(entry["destination"] == spec.destination, "approval destination is invalid")
            require(entry["mode"] == format(spec.mode, "04o"), "approval mode is invalid")
            require(
                type(entry["sha256"]) is str
                and SHA256_PATTERN.fullmatch(entry["sha256"]) is not None,
                "approval file SHA-256 is invalid at index " + str(index),
            )
        return stable, manifest
    except BaseException:
        stable.close()
        raise


def open_source_file(source_root: str, root_descriptor: int, relative: str) -> StableFile:
    parts = Path(relative).parts
    require(parts and all(part not in ("", ".", "..") for part in parts), "bundle source path is invalid")
    current = os.dup(root_descriptor)
    try:
        for component in parts[:-1]:
            next_descriptor = os.open(
                component,
                os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
                dir_fd=current,
            )
            os.close(current)
            current = next_descriptor
            metadata = os.fstat(current)
            require(stat.S_ISDIR(metadata.st_mode), "bundle source ancestor is not a directory")
            require(metadata.st_uid == 0 and metadata.st_gid == 0, "bundle source ancestor is not root:root")
            require(stat.S_IMODE(metadata.st_mode) & 0o022 == 0, "bundle source ancestor is writable")
        descriptor = os.open(
            parts[-1],
            os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
            dir_fd=current,
        )
    finally:
        os.close(current)
    full_path = os.path.join(source_root, *parts)
    try:
        before = os.fstat(descriptor)
        require(stat.S_ISREG(before.st_mode), "bundle source is not a regular file: " + relative)
        require(before.st_uid == 0 and before.st_gid == 0, "bundle source is not root:root: " + relative)
        require(before.st_nlink == 1, "bundle source is hard-linked: " + relative)
        require(stat.S_IMODE(before.st_mode) & 0o022 == 0, "bundle source is group/other writable: " + relative)
        payload = read_all(descriptor, MAX_FILE_BYTES, "bundle source " + relative)
        after = os.fstat(descriptor)
        require(identity(before) == identity(after), "bundle source changed while read: " + relative)
        require(len(payload) == before.st_size, "bundle source size changed while read: " + relative)
        path_metadata = os.stat(full_path, follow_symlinks=False)
        require(
            (path_metadata.st_dev, path_metadata.st_ino) == (before.st_dev, before.st_ino),
            "bundle source path changed while read: " + relative,
        )
        return StableFile(full_path, descriptor, before, payload)
    except BaseException:
        os.close(descriptor)
        raise


def load_approved_sources(source_root: str, manifest: dict) -> list[StableFile]:
    source_root = validate_root_directory_chain(source_root, "bundle source root")
    root_descriptor = os.open(
        source_root,
        os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
    )
    sources: list[StableFile] = []
    try:
        root_metadata = os.fstat(root_descriptor)
        require(stat.S_ISDIR(root_metadata.st_mode), "bundle source root is not a directory")
        require(root_metadata.st_uid == 0 and root_metadata.st_gid == 0, "bundle source root is not root:root")
        require(stat.S_IMODE(root_metadata.st_mode) & 0o022 == 0, "bundle source root is group/other writable")
        for spec, approved in zip(BUNDLE_SPECS, manifest["files"]):
            source = open_source_file(source_root, root_descriptor, spec.source)
            require(
                sha256(source.payload) == approved["sha256"],
                "bundle source SHA-256 differs from root approval: " + spec.source,
            )
            sources.append(source)
        return sources
    except BaseException:
        for source in sources:
            source.close()
        raise
    finally:
        os.close(root_descriptor)


def load_installed_bundle() -> list[StableFile]:
    installed: list[StableFile] = []
    try:
        for spec in BUNDLE_SPECS:
            validate_root_directory_chain(os.path.dirname(spec.destination), "installed bundle parent")
            installed.append(
                open_stable_root_file(
                    spec.destination,
                    expected_mode=spec.mode,
                    maximum=MAX_FILE_BYTES,
                    label="installed bundle file " + spec.destination,
                )
            )
        return installed
    except BaseException:
        for item in installed:
            item.close()
        raise


def journal_record(spec: BundleSpec, old_payload: bytes, new_payload: bytes) -> dict:
    stage, backup = artifact_paths(spec.destination)
    return {
        "source": spec.source,
        "destination": spec.destination,
        "mode": format(spec.mode, "04o"),
        "old_sha256": sha256(old_payload),
        "new_sha256": sha256(new_payload),
        "stage": stage,
        "backup": backup,
    }


def validate_journal(journal: dict) -> dict:
    require(type(journal) is dict, "bundle install journal must be an object")
    require(tuple(journal) == JOURNAL_KEYS, "bundle install journal keys/order are invalid")
    require(
        type(journal["schema_version"]) is int
        and journal["schema_version"] == 1,
        "bundle install journal schema is invalid",
    )
    require(
        type(journal["state"]) is str and journal["state"] in JOURNAL_STATES,
        "bundle install journal state is invalid",
    )
    require(
        type(journal["expected_main_sha"]) is str
        and SHA1_PATTERN.fullmatch(journal["expected_main_sha"]) is not None,
        "bundle install journal main SHA is invalid",
    )
    for key in ("approval_sha256", "old_bundle_sha256", "new_bundle_sha256"):
        require(
            type(journal[key]) is str and SHA256_PATTERN.fullmatch(journal[key]) is not None,
            "bundle install journal " + key + " is invalid",
        )
    count = len(BUNDLE_SPECS)
    for key in ("staged_count", "replaced_count", "rollback_count"):
        require(type(journal[key]) is int and 0 <= journal[key] <= count, "bundle install journal count is invalid")
    files = journal["files"]
    require(type(files) is list and len(files) == count, "bundle install journal file count is invalid")
    for record, spec in zip(files, BUNDLE_SPECS):
        require(
            type(record) is dict and tuple(record) == JOURNAL_FILE_KEYS,
            "bundle install journal file keys/order are invalid",
        )
        stage, backup = artifact_paths(spec.destination)
        require(
            type(record["source"]) is str and record["source"] == spec.source,
            "bundle install journal source is invalid",
        )
        require(
            type(record["destination"]) is str
            and record["destination"] == spec.destination,
            "bundle install journal destination is invalid",
        )
        require(
            type(record["mode"]) is str
            and record["mode"] == format(spec.mode, "04o"),
            "bundle install journal mode is invalid",
        )
        require(
            type(record["stage"]) is str
            and type(record["backup"]) is str
            and record["stage"] == stage
            and record["backup"] == backup,
            "bundle install journal artifact path is invalid",
        )
        require(
            type(record["old_sha256"]) is str
            and SHA256_PATTERN.fullmatch(record["old_sha256"]) is not None,
            "bundle install journal old digest is invalid",
        )
        require(
            type(record["new_sha256"]) is str
            and SHA256_PATTERN.fullmatch(record["new_sha256"]) is not None,
            "bundle install journal new digest is invalid",
        )
    return journal


class JournalStore:
    def __init__(self, path: str = INSTALL_JOURNAL):
        self.path = path
        ensure_state_directory(os.path.dirname(path))
        self.directory = os.path.dirname(path)
        self.name = os.path.basename(path)
        self.directory_descriptor = os.open(
            self.directory,
            os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
        )
        self.sequence = 0

    def close(self) -> None:
        os.close(self.directory_descriptor)

    def exists(self) -> bool:
        try:
            os.stat(self.name, dir_fd=self.directory_descriptor, follow_symlinks=False)
            return True
        except FileNotFoundError:
            return False

    def load(self) -> dict:
        stable = open_stable_root_file(
            self.path,
            expected_mode=0o600,
            maximum=MAX_JOURNAL_BYTES,
            label="bundle install journal",
        )
        try:
            return validate_journal(strict_json(stable.payload, "bundle install journal"))
        finally:
            stable.close()

    def write(self, journal: dict) -> None:
        validate_journal(journal)
        payload = (json.dumps(journal, separators=(",", ":")) + "\n").encode("ascii")
        require(len(payload) <= MAX_JOURNAL_BYTES, "bundle install journal is too large")
        self.sequence += 1
        temporary = ".{0}.write-{1}-{2}".format(self.name, os.getpid(), self.sequence)
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
            0o600,
            dir_fd=self.directory_descriptor,
        )
        try:
            os.fchown(descriptor, 0, 0)
            os.fchmod(descriptor, 0o600)
            write_all(descriptor, payload)
            os.fsync(descriptor)
            metadata = os.fstat(descriptor)
            require(
                stat.S_ISREG(metadata.st_mode)
                and metadata.st_uid == 0
                and metadata.st_gid == 0
                and stat.S_IMODE(metadata.st_mode) == 0o600
                and metadata.st_nlink == 1
                and metadata.st_size == len(payload),
                "new bundle install journal identity is invalid",
            )
        except BaseException:
            try:
                os.unlink(temporary, dir_fd=self.directory_descriptor)
            except FileNotFoundError:
                pass
            raise
        finally:
            os.close(descriptor)
        os.replace(
            temporary,
            self.name,
            src_dir_fd=self.directory_descriptor,
            dst_dir_fd=self.directory_descriptor,
        )
        os.fsync(self.directory_descriptor)

    def clear(self) -> None:
        stable = open_stable_root_file(
            self.path,
            expected_mode=0o600,
            maximum=MAX_JOURNAL_BYTES,
            label="bundle install journal",
        )
        try:
            metadata = os.stat(self.name, dir_fd=self.directory_descriptor, follow_symlinks=False)
            require(
                (metadata.st_dev, metadata.st_ino)
                == (stable.metadata.st_dev, stable.metadata.st_ino),
                "bundle install journal changed before clear",
            )
            os.unlink(self.name, dir_fd=self.directory_descriptor)
            os.fsync(self.directory_descriptor)
        finally:
            stable.close()

    def cleanup_write_temporaries(self) -> None:
        prefix = "." + self.name + ".write-"
        for name in os.listdir(self.directory_descriptor):
            if not name.startswith(prefix):
                continue
            metadata = os.stat(name, dir_fd=self.directory_descriptor, follow_symlinks=False)
            require(
                stat.S_ISREG(metadata.st_mode)
                and metadata.st_uid == 0
                and metadata.st_gid == 0
                and stat.S_IMODE(metadata.st_mode) == 0o600
                and metadata.st_nlink == 1,
                "stale bundle journal temporary has an unsafe identity",
            )
            os.unlink(name, dir_fd=self.directory_descriptor)
        os.fsync(self.directory_descriptor)


def path_metadata(path: str) -> os.stat_result | None:
    try:
        return os.stat(path, follow_symlinks=False)
    except FileNotFoundError:
        return None


def create_artifact(path: str, payload: bytes, mode: int, label: str) -> None:
    parent = os.path.dirname(path)
    validate_root_directory_chain(parent, label + " parent")
    parent_descriptor = os.open(
        parent,
        os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
    )
    name = os.path.basename(path)
    try:
        descriptor = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
            mode,
            dir_fd=parent_descriptor,
        )
        try:
            os.fchown(descriptor, 0, 0)
            os.fchmod(descriptor, mode)
            write_all(descriptor, payload)
            os.fsync(descriptor)
            metadata = os.fstat(descriptor)
            require(
                stat.S_ISREG(metadata.st_mode)
                and metadata.st_uid == 0
                and metadata.st_gid == 0
                and stat.S_IMODE(metadata.st_mode) == mode
                and metadata.st_nlink == 1
                and metadata.st_size == len(payload),
                label + " identity is invalid",
            )
        finally:
            os.close(descriptor)
        os.fsync(parent_descriptor)
    finally:
        os.close(parent_descriptor)


def validate_artifact(path: str, mode: int, expected_sha256: str, label: str) -> bytes:
    stable = open_stable_root_file(
        path,
        expected_mode=mode,
        maximum=MAX_FILE_BYTES,
        label=label,
    )
    try:
        require(sha256(stable.payload) == expected_sha256, label + " SHA-256 is invalid")
        return stable.payload
    finally:
        stable.close()


def unlink_artifact(path: str, mode: int, expected_sha256: str | None, label: str) -> None:
    if path_metadata(path) is None:
        return
    stable = open_stable_root_file(
        path,
        expected_mode=mode,
        maximum=MAX_FILE_BYTES,
        label=label,
    )
    try:
        if expected_sha256 is not None:
            require(sha256(stable.payload) == expected_sha256, label + " SHA-256 is invalid")
        parent = os.path.dirname(path)
        descriptor = os.open(
            parent,
            os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
        )
        try:
            current = os.stat(os.path.basename(path), dir_fd=descriptor, follow_symlinks=False)
            require(
                (current.st_dev, current.st_ino)
                == (stable.metadata.st_dev, stable.metadata.st_ino),
                label + " changed before cleanup",
            )
            os.unlink(os.path.basename(path), dir_fd=descriptor)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        stable.close()


def replace_same_directory(source: str, destination: str) -> None:
    parent = os.path.dirname(destination)
    require(parent == os.path.dirname(source), "bundle replacement is not same-directory")
    descriptor = os.open(
        parent,
        os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
    )
    try:
        os.replace(
            os.path.basename(source),
            os.path.basename(destination),
            src_dir_fd=descriptor,
            dst_dir_fd=descriptor,
        )
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def cleanup_transaction_artifacts(journal: dict | None = None) -> None:
    records = journal["files"] if journal is not None else [
        {
            "stage": artifact_paths(spec.destination)[0],
            "backup": artifact_paths(spec.destination)[1],
            "mode": format(spec.mode, "04o"),
            "old_sha256": None,
            "new_sha256": None,
        }
        for spec in BUNDLE_SPECS
    ]
    for record in records:
        mode = int(record["mode"], 8)
        unlink_artifact(
            record["stage"],
            mode,
            record.get("new_sha256"),
            "bundle stage artifact",
        )
        unlink_artifact(
            record["backup"],
            mode,
            record.get("old_sha256"),
            "bundle backup artifact",
        )


def prepare_transaction(store: JournalStore, journal: dict, old: list[StableFile], new: list[StableFile]) -> dict:
    store.write(journal)
    for index, (record, old_file, new_file, spec) in enumerate(
        zip(journal["files"], old, new, BUNDLE_SPECS)
    ):
        create_artifact(record["backup"], old_file.payload, spec.mode, "bundle backup")
        create_artifact(record["stage"], new_file.payload, spec.mode, "bundle stage")
        journal["state"] = "staging"
        journal["staged_count"] = index + 1
        store.write(journal)
    for record, spec in zip(journal["files"], BUNDLE_SPECS):
        validate_artifact(record["backup"], spec.mode, record["old_sha256"], "prepared bundle backup")
        validate_artifact(record["stage"], spec.mode, record["new_sha256"], "prepared bundle stage")
    journal["state"] = "prepared"
    store.write(journal)
    return journal


def replace_transaction(store: JournalStore, journal: dict) -> dict:
    journal["state"] = "replacing"
    store.write(journal)
    for index, (record, spec) in enumerate(zip(journal["files"], BUNDLE_SPECS)):
        validate_artifact(record["stage"], spec.mode, record["new_sha256"], "bundle replacement stage")
        validate_artifact(record["destination"], spec.mode, record["old_sha256"], "bundle replacement target")
        replace_same_directory(record["stage"], record["destination"])
        validate_artifact(record["destination"], spec.mode, record["new_sha256"], "replaced bundle target")
        journal["replaced_count"] = index + 1
        store.write(journal)
    journal["state"] = "verifying"
    store.write(journal)
    return journal


def installed_bundle_digest(expected_field: str, journal: dict) -> str:
    entries: list[tuple[str, bytes]] = []
    for record, spec in zip(journal["files"], BUNDLE_SPECS):
        expected = record[expected_field]
        payload = validate_artifact(
            record["destination"],
            spec.mode,
            expected,
            "installed bundle verification",
        )
        entries.append((record["destination"], payload))
    return bundle_sha256(entries)


def rollback_transaction(
    store: JournalStore,
    doctor: Callable[[], None],
    health: Callable[[], None],
) -> None:
    journal = store.load()
    journal["state"] = "rolling_back"
    store.write(journal)
    restored = 0
    for record, spec in reversed(list(zip(journal["files"], BUNDLE_SPECS))):
        current = open_stable_root_file(
            record["destination"],
            expected_mode=spec.mode,
            maximum=MAX_FILE_BYTES,
            label="rollback current bundle target",
        )
        try:
            current_digest = sha256(current.payload)
            require(
                current_digest in (record["old_sha256"], record["new_sha256"]),
                "rollback target contains an unjournaled third-party version",
            )
        finally:
            current.close()
        backup_metadata = path_metadata(record["backup"])
        if backup_metadata is not None:
            validate_artifact(record["backup"], spec.mode, record["old_sha256"], "rollback bundle backup")
            replace_same_directory(record["backup"], record["destination"])
        else:
            validate_artifact(record["destination"], spec.mode, record["old_sha256"], "already-restored bundle target")
        validate_artifact(record["destination"], spec.mode, record["old_sha256"], "rollback bundle target")
        unlink_artifact(record["stage"], spec.mode, record["new_sha256"], "rollback bundle stage")
        restored += 1
        journal["rollback_count"] = restored
        store.write(journal)
    require(
        installed_bundle_digest("old_sha256", journal) == journal["old_bundle_sha256"],
        "rolled-back bundle digest differs from the journal",
    )
    doctor()
    health()
    store.clear()
    cleanup_transaction_artifacts(journal)


def make_journal(
    expected_main_sha: str,
    approval_payload: bytes,
    old: list[StableFile],
    new: list[StableFile],
) -> dict:
    old_entries = [(spec.destination, item.payload) for spec, item in zip(BUNDLE_SPECS, old)]
    new_entries = [(spec.destination, item.payload) for spec, item in zip(BUNDLE_SPECS, new)]
    return {
        "schema_version": 1,
        "state": "planned",
        "expected_main_sha": expected_main_sha,
        "approval_sha256": sha256(approval_payload),
        "old_bundle_sha256": bundle_sha256(old_entries),
        "new_bundle_sha256": bundle_sha256(new_entries),
        "staged_count": 0,
        "replaced_count": 0,
        "rollback_count": 0,
        "files": [
            journal_record(spec, old_file.payload, new_file.payload)
            for spec, old_file, new_file in zip(BUNDLE_SPECS, old, new)
        ],
    }


def install_bundle(
    expected_main_sha: str,
    source_root: str,
    store: JournalStore,
    doctor: Callable[[], None],
    health: Callable[[], None],
    *,
    approval_path: str = APPROVAL_MANIFEST,
) -> None:
    require(not store.exists(), "an existing bundle install journal must be recovered first")
    store.cleanup_write_temporaries()
    cleanup_transaction_artifacts()
    health()
    doctor()
    approval, manifest = load_approval_manifest(expected_main_sha, approval_path)
    sources: list[StableFile] = []
    installed: list[StableFile] = []
    committed = False
    try:
        sources = load_approved_sources(source_root, manifest)
        installed = load_installed_bundle()
        journal = make_journal(expected_main_sha, approval.payload, installed, sources)
        prepare_transaction(store, journal, installed, sources)
        approval.assert_unchanged("approval manifest")
        for source in sources:
            source.assert_unchanged("approved bundle source")
        replace_transaction(store, journal)
        approval.assert_unchanged("approval manifest")
        for source in sources:
            source.assert_unchanged("approved bundle source")
        require(
            installed_bundle_digest("new_sha256", journal) == journal["new_bundle_sha256"],
            "installed bundle digest differs from the approved bundle",
        )
        doctor()
        health()
        approval.assert_unchanged("approval manifest")
        journal["state"] = "verified"
        store.write(journal)
        store.clear()
        committed = True
        cleanup_transaction_artifacts(journal)
    except BaseException as install_error:
        if store.exists():
            try:
                rollback_transaction(store, doctor, health)
            except BaseException as rollback_error:
                raise InstallError(
                    "bundle install failed and rollback remains incomplete: {0}; rollback: {1}".format(
                        install_error,
                        rollback_error,
                    )
                ) from rollback_error
        if isinstance(install_error, InstallError):
            raise
        raise InstallError("bundle install failed: " + str(install_error)) from install_error
    finally:
        approval.close()
        for source in sources:
            source.close()
        for item in installed:
            item.close()
        if committed:
            store.cleanup_write_temporaries()


def reject_active_cutover_journal(path: str = CUTOVER_JOURNAL) -> None:
    try:
        os.lstat(path)
    except FileNotFoundError:
        return
    raise InstallError("an active production cutover journal blocks bundle installation")


def load_launcher_api(path: str = TRUSTED_LAUNCHER) -> dict:
    validate_root_directory_chain(os.path.dirname(path), "trusted launcher parent")
    stable = open_stable_root_file(
        path,
        expected_mode=0o555,
        maximum=MAX_FILE_BYTES,
        label="trusted production launcher",
    )
    try:
        namespace = {
            "__file__": path,
            "__name__": "xjie_bundle_installer_launcher_api",
            "__package__": None,
        }
        exec(compile(stable.payload, path, "exec"), namespace)
        for name in (
            "open_lock_directory",
            "open_deployment_lock",
            "reject_live_lease",
            "open_legacy_deployment_lock",
        ):
            require(callable(namespace.get(name)), "trusted launcher lock API is incomplete")
        return namespace
    finally:
        stable.close()


def close_unapproved_descriptors(allowed: set[int]) -> None:
    for name in os.listdir("/proc/self/fd"):
        if not name.isdigit():
            continue
        descriptor = int(name)
        if descriptor >= 3 and descriptor not in allowed:
            try:
                os.close(descriptor)
            except OSError:
                pass


def run_launcher_doctor(
    root_lock_descriptor: int,
    legacy_lock_descriptor: int,
    launcher: str = TRUSTED_LAUNCHER,
) -> None:
    stdin_read, stdin_write = os.pipe2(os.O_CLOEXEC)
    authority_read, authority_write = os.pipe2(os.O_CLOEXEC)
    child = os.fork()
    if child == 0:
        try:
            os.close(stdin_write)
            os.close(authority_write)
            temporary_root = fcntl.fcntl(root_lock_descriptor, fcntl.F_DUPFD_CLOEXEC, 20)
            temporary_legacy = fcntl.fcntl(legacy_lock_descriptor, fcntl.F_DUPFD_CLOEXEC, 20)
            temporary_stdin = fcntl.fcntl(stdin_read, fcntl.F_DUPFD_CLOEXEC, 20)
            temporary_authority = fcntl.fcntl(authority_read, fcntl.F_DUPFD_CLOEXEC, 20)
            os.dup2(temporary_stdin, 0, inheritable=True)
            os.dup2(temporary_root, INSTALLER_ROOT_LOCK_FD, inheritable=True)
            os.dup2(temporary_legacy, INSTALLER_LEGACY_LOCK_FD, inheritable=True)
            os.dup2(temporary_authority, INSTALLER_AUTHORITY_FD, inheritable=True)
            close_unapproved_descriptors(
                {INSTALLER_ROOT_LOCK_FD, INSTALLER_LEGACY_LOCK_FD, INSTALLER_AUTHORITY_FD}
            )
            os.execve(
                launcher,
                [launcher, "--doctor"],
                {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C"},
            )
        except BaseException:
            os._exit(127)
    os.close(stdin_read)
    os.close(stdin_write)
    os.close(authority_read)
    try:
        write_all(authority_write, INSTALLER_AUTHORITY_MARKER)
    finally:
        os.close(authority_write)
    observed, status = os.waitpid(child, 0)
    require(observed == child, "cannot reap launcher doctor")
    require(os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0, "installed launcher --doctor failed")


def load_production_spec(path: str = TRUSTED_SPEC) -> dict:
    stable = open_stable_root_file(
        path,
        expected_mode=0o444,
        maximum=MAX_MANIFEST_BYTES,
        label="trusted production container spec",
    )
    try:
        spec = strict_json(stable.payload, "trusted production container spec")
        require(tuple(spec) == SPEC_KEYS, "trusted production container spec keys/order are invalid")
        require(
            type(spec["schema_version"]) is int
            and spec == PINNED_SPEC,
            "trusted production container spec differs from the exact pinned identity",
        )
        return spec
    finally:
        stable.close()


def verify_production_health(
    *,
    spec_path: str = TRUSTED_SPEC,
    docker_binary: str = DOCKER_BINARY,
) -> None:
    spec = load_production_spec(spec_path)
    container_name = spec["container_name"]
    inspect = subprocess.run(
        [
            docker_binary,
            "container",
            "inspect",
            "--format",
            "{{.Id}}|{{.Name}}|{{.State.Running}}|{{.Image}}",
            container_name,
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C"},
        close_fds=True,
        timeout=10,
    )
    require(inspect.returncode == 0, "production container cannot be inspected")
    try:
        fields = inspect.stdout.decode("ascii").strip().split("|")
    except UnicodeDecodeError as exc:
        raise InstallError("production container inspect output is invalid") from exc
    require(len(fields) == 4, "production container inspect projection is invalid")
    container_id, observed_name, running, image_id = fields
    require(
        re.fullmatch(r"[0-9a-f]{64}", container_id) is not None
        and observed_name == "/" + container_name
        and running == "true"
        and re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) is not None,
        "production container is not running with a stable identity",
    )
    health_program = (
        "import json,urllib.request;"
        "r=urllib.request.urlopen('http://127.0.0.1:8000/healthz',timeout=3);"
        "p=json.loads(r.read());"
        "raise SystemExit(0 if r.status==200 and p=={'ok':True} else 1)"
    )
    health = subprocess.run(
        [docker_binary, "exec", container_id, "python", "-I", "-c", health_program],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C"},
        close_fds=True,
        timeout=10,
    )
    require(health.returncode == 0, "production container health check failed")


def validate_installer_identity(path: str = TRUSTED_INSTALLER) -> StableFile:
    require(os.path.realpath(__file__) == path, "only the installed bundle installer may run")
    validate_root_directory_chain(os.path.dirname(path), "trusted installer parent")
    return open_stable_root_file(
        path,
        expected_mode=0o555,
        maximum=MAX_FILE_BYTES,
        label="trusted bundle installer",
    )


def sanitize_environment() -> None:
    os.environ.clear()
    os.environ.update(
        {
            "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
            "LC_ALL": "C",
            "HOME": "/nonexistent",
            "XDG_CONFIG_HOME": "/nonexistent",
        }
    )
    os.umask(0o077)


def disable_process_dumping() -> None:
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    libc = ctypes.CDLL(None, use_errno=True)
    require(
        libc.prctl(PR_SET_DUMPABLE, 0, 0, 0, 0) == 0,
        "cannot disable bundle-installer process dumping",
    )


def main() -> None:
    require(os.geteuid() == 0 and os.getegid() == 0, "bundle installer must run as root")
    disable_process_dumping()
    arguments = sys.argv[1:]
    recover_only = arguments == ["--recover"]
    require(
        recover_only
        or (
            len(arguments) == 2
            and SHA1_PATTERN.fullmatch(arguments[0]) is not None
            and os.path.isabs(arguments[1])
        ),
        "usage: xjie-production-install EXPECTED_MAIN_SHA SOURCE_ROOT | --recover",
    )
    installer_identity = validate_installer_identity()
    sanitize_environment()
    launcher_api = load_launcher_api()
    try:
        principal = pwd.getpwnam(DEPLOY_PRINCIPAL)
    except KeyError as exc:
        raise InstallError("deployment principal does not exist") from exc
    require(
        principal.pw_uid != 0
        and principal.pw_gid != 0
        and principal.pw_dir == "/home/mayl",
        "deployment principal identity is invalid",
    )
    directory_descriptor = launcher_api["open_lock_directory"]()
    lock_descriptor = launcher_api["open_deployment_lock"](directory_descriptor)
    legacy_descriptor = -1
    store: JournalStore | None = None
    try:
        launcher_api["reject_live_lease"](directory_descriptor)
        legacy_descriptor = launcher_api["open_legacy_deployment_lock"](principal)
        reject_active_cutover_journal()
        store = JournalStore()
        store.cleanup_write_temporaries()
        doctor = lambda: run_launcher_doctor(lock_descriptor, legacy_descriptor)
        health = verify_production_health
        if store.exists():
            rollback_transaction(store, doctor, health)
            if not recover_only:
                raise InstallError(
                    "the interrupted bundle transaction was rolled back; rerun the approved install command"
                )
            print("production bundle installer: interrupted transaction rolled back")
            return
        cleanup_transaction_artifacts()
        if recover_only:
            print("production bundle installer: no transaction requires recovery")
            return
        expected_main_sha, source_root = arguments
        installer_identity.assert_unchanged("trusted bundle installer")
        install_bundle(
            expected_main_sha,
            source_root,
            store,
            doctor,
            health,
        )
        print("production bundle installer: installed exact main " + expected_main_sha)
    finally:
        if store is not None:
            store.close()
        if legacy_descriptor >= 0:
            os.close(legacy_descriptor)
        os.close(lock_descriptor)
        os.close(directory_descriptor)
        installer_identity.close()


if __name__ == "__main__":
    try:
        main()
    except InstallError as exc:
        raise SystemExit("PRODUCTION BUNDLE INSTALLER: FAILED: " + str(exc))
