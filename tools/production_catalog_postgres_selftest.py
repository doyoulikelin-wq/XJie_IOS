#!/usr/bin/env python3
"""Run the production schema-attestation path against real PostgreSQL 16.14.

This is deliberately an integration gate rather than a Python test-suite item. It
executes the generated materializer and SQL probes in locked-down, tracked Docker
containers so PostgreSQL parser/catalog incompatibilities cannot be hidden by
synthetic fixtures.
"""

import argparse
import collections
import hashlib
import importlib.util
import json
import os
import re
import resource
import secrets
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path


TRUSTED_POSTGRES_REFERENCE = (
    "postgres:16.14-alpine3.23@sha256:"
    "bb0628a764d870fed40e71423339e24111bed4a40b614ee68dcbd8981ed6474e"
)
TRUSTED_POSTGRES_REPOSITORY_DIGEST = (
    "postgres@sha256:"
    "bb0628a764d870fed40e71423339e24111bed4a40b614ee68dcbd8981ed6474e"
)
EXPECTED_POSTGRES_VERSION = "postgres (PostgreSQL) 16.14"
EXPECTED_MANIFEST_COUNTS = {
    "migrations": 25,
    "tables": 95,
}
EXPECTED_ALEMBIC_HEAD = "0025_dietary_records"
EXPECTED_CATALOG_COUNTS = {
    "tables": 95,
    "columns": 1159,
    "sequences": 93,
    "enums": 5,
    "constraints": 498,
    "primary_constraints": 95,
    "foreign_constraints": 145,
    "unique_constraints": 103,
    "check_constraints": 155,
    "indexes": 359,
    "constraint_backed_indexes": 198,
    "explicit_indexes": 161,
    "partial_indexes": 1,
}
EXPECTED_ATTESTATION_ERROR = {"error": "database schema attestation failed"}
SHA256_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
CONTAINER_ID = re.compile(r"^[0-9a-f]{64}$")
ROLE_NAME = "xjie_catalog_probe"
DATABASE_NAME = "xjie_reference"
ADMIN_NAME = "xjie_reference"
SOCKET_DESTINATION = "/var/run/postgresql"
PGDATA_DESTINATION = "/var/lib/postgresql/data"


class SelfTestError(RuntimeError):
    """A fail-closed integration assertion failed."""


def require(condition, message):
    if not condition:
        raise SelfTestError(message)


def load_guard(repository_root):
    source = repository_root / "backend" / "deploy" / "production_deploy_guard.py"
    spec = importlib.util.spec_from_file_location(
        "xjie_production_deploy_guard_selftest", source
    )
    require(spec is not None and spec.loader is not None, "cannot load deploy guard")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module, source


def canonical_json(value):
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )


def ordered_json(value):
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
    )


def parse_single_json(payload, label):
    require(len(payload) > 0, label + " is empty")
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise SelfTestError(label + " is not one UTF-8 JSON value") from exc
    return value


def write_owner_only(path, payload):
    require(not path.exists() and not path.is_symlink(), "output path already exists")
    descriptor = os.open(
        str(path),
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        stat.S_IRUSR | stat.S_IWUSR,
    )
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise
    metadata = path.stat()
    require(
        stat.S_ISREG(metadata.st_mode)
        and metadata.st_uid == os.geteuid()
        and stat.S_IMODE(metadata.st_mode) == 0o600
        and metadata.st_nlink == 1,
        "owner-only output identity is invalid",
    )


def sql_identifier(value):
    require(isinstance(value, str) and value, "SQL identifier is empty")
    return '"' + value.replace('"', '""') + '"'


def sql_literal(value):
    require(isinstance(value, str), "SQL literal is invalid")
    return "'" + value.replace("'", "''") + "'"


class DockerHarness:
    def __init__(self, work_directory):
        self.work_directory = work_directory
        self.run_id = secrets.token_hex(12)
        self._counter = 0
        self._containers = collections.OrderedDict()
        self._secrets = set()

    def add_secret(self, value):
        if value:
            self._secrets.add(value)

    def redact(self, value):
        result = value
        for secret in sorted(self._secrets, key=len, reverse=True):
            result = result.replace(secret, "[REDACTED]")
        return result

    def _next_path(self, stem):
        self._counter += 1
        return self.work_directory / ("{0}-{1}".format(stem, self._counter))

    def unique_name(self, role):
        self._counter += 1
        safe_role = re.sub(r"[^a-zA-Z0-9_.-]+", "-", role).strip("-.")
        require(bool(safe_role), "container role cannot form a safe name")
        return "xjie-pg-selftest-{0}-{1}-{2}".format(
            self.run_id, safe_role, self._counter
        )

    def run(
        self,
        arguments,
        label,
        input_bytes=None,
        timeout=120,
        stdout_limit=1024 * 1024,
        stderr_limit=1024 * 1024,
        check=True,
    ):
        require(arguments and all(isinstance(item, str) for item in arguments), label)
        if input_bytes is not None:
            require(
                isinstance(input_bytes, bytes) and len(input_bytes) <= 16 * 1024 * 1024,
                label + " input is invalid or too large",
            )
        stdout_path = self._next_path("command-stdout")
        stderr_path = self._next_path("command-stderr")
        stdout_fd = os.open(
            str(stdout_path),
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            stat.S_IRUSR | stat.S_IWUSR,
        )
        stderr_fd = os.open(
            str(stderr_path),
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            stat.S_IRUSR | stat.S_IWUSR,
        )
        limit = max(stdout_limit, stderr_limit)

        def child_limits():
            resource.setrlimit(resource.RLIMIT_FSIZE, (limit, limit))

        process = None
        timed_out = False
        try:
            with os.fdopen(stdout_fd, "wb", closefd=True) as stdout_file, os.fdopen(
                stderr_fd, "wb", closefd=True
            ) as stderr_file:
                process = subprocess.Popen(
                    arguments,
                    stdin=(subprocess.PIPE if input_bytes is not None else subprocess.DEVNULL),
                    stdout=stdout_file,
                    stderr=stderr_file,
                    close_fds=True,
                    preexec_fn=child_limits,
                )
                try:
                    process.communicate(input=input_bytes, timeout=timeout)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    process.terminate()
                    try:
                        process.communicate(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.communicate(timeout=10)
        except BaseException:
            if process is not None and process.poll() is None:
                process.kill()
                process.wait(timeout=10)
            raise

        try:
            stdout_size = stdout_path.stat().st_size
            stderr_size = stderr_path.stat().st_size
            require(stdout_size <= stdout_limit, label + " stdout exceeded its limit")
            require(stderr_size <= stderr_limit, label + " stderr exceeded its limit")
            stdout = stdout_path.read_bytes()
            stderr = stderr_path.read_bytes()
        finally:
            stdout_path.unlink(missing_ok=True)
            stderr_path.unlink(missing_ok=True)
        if timed_out:
            raise SelfTestError(label + " timed out")
        require(process is not None, label + " did not start")
        if check and process.returncode != 0:
            detail = self.redact(stderr[-4096:].decode("utf-8", errors="replace")).strip()
            suffix = ": " + detail if detail else ""
            raise SelfTestError(
                "{0} exited with status {1}{2}".format(label, process.returncode, suffix)
            )
        return stdout, stderr, process.returncode

    def docker(self, arguments, label, **kwargs):
        return self.run(["docker"] + list(arguments), label, **kwargs)

    def inspect_image(self, reference, label):
        stdout, _, _ = self.docker(
            ["image", "inspect", reference],
            label,
            stdout_limit=4 * 1024 * 1024,
        )
        try:
            values = json.loads(stdout.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise SelfTestError(label + " returned invalid JSON") from exc
        require(isinstance(values, list) and len(values) == 1, label + " is ambiguous")
        return values[0]

    def inspect_container(self, container_id, label, check=True):
        stdout, stderr, return_code = self.docker(
            ["container", "inspect", container_id],
            label,
            check=check,
            stdout_limit=4 * 1024 * 1024,
        )
        if return_code != 0:
            detail = self.redact(stderr.decode("utf-8", errors="replace")).strip()
            if "No such object" in detail or "No such container" in detail:
                return None
            raise SelfTestError(label + " failed: " + detail)
        try:
            values = json.loads(stdout.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise SelfTestError(label + " returned invalid JSON") from exc
        require(isinstance(values, list) and len(values) == 1, label + " is ambiguous")
        value = values[0]
        require(value.get("Id") == container_id, label + " ID changed")
        return value

    def create_container(self, role, image_id, options, command):
        require(SHA256_ID.fullmatch(image_id) is not None, "container image ID is invalid")
        name = self.unique_name(role)
        cidfile = self._next_path("container-id")
        stdout = b""
        stdout_id = ""
        file_id = ""
        try:
            stdout, _, _ = self.docker(
                [
                    "container",
                    "create",
                    "--cidfile",
                    str(cidfile),
                    "--name",
                    name,
                    "--label",
                    "com.jianjieaitech.xjie.postgres-selftest=1",
                    "--label",
                    "com.jianjieaitech.xjie.postgres-selftest-run=" + self.run_id,
                ]
                + list(options)
                + [image_id]
                + list(command),
                "create " + role + " container",
                stdout_limit=4096,
            )
            stdout_id = stdout.decode("ascii", errors="strict").strip()
            if CONTAINER_ID.fullmatch(stdout_id) is not None:
                self._containers.setdefault(stdout_id, role)
            file_id = cidfile.read_text(encoding="ascii").strip()
            if CONTAINER_ID.fullmatch(file_id) is not None:
                self._containers.setdefault(file_id, role)
            require(
                stdout_id == file_id and CONTAINER_ID.fullmatch(file_id) is not None,
                role + " cidfile/stdout identity mismatch",
            )
            inspected = self.inspect_container(file_id, "inspect " + role + " container")
            require(inspected.get("Image") == image_id, role + " image ID changed")
            require(
                inspected.get("Config", {}).get("Image") == image_id,
                role + " Config.Image is not immutable",
            )
            require(inspected.get("Name") == "/" + name, role + " name changed")
            return file_id, inspected
        except BaseException:
            if cidfile.exists() and not cidfile.is_symlink():
                try:
                    recovery_id = cidfile.read_text(encoding="ascii").strip()
                except (OSError, UnicodeError):
                    recovery_id = ""
                if CONTAINER_ID.fullmatch(recovery_id) is not None:
                    self._containers.setdefault(recovery_id, role)
            raise
        finally:
            cidfile.unlink(missing_ok=True)

    def remove_container(self, container_id, label, force=False):
        require(container_id in self._containers, label + " is not tracked")
        inspected = self.inspect_container(container_id, "pre-remove inspect " + label)
        require(inspected is not None, label + " disappeared before removal")
        arguments = ["container", "rm", "--volumes"]
        if force:
            arguments.append("--force")
        arguments.append(container_id)
        self.docker(arguments, "remove " + label, stdout_limit=4096)
        missing = self.inspect_container(
            container_id, "post-remove inspect " + label, check=False
        )
        require(missing is None, label + " still exists after removal")
        self._containers.pop(container_id, None)

    def run_one_shot(
        self,
        role,
        image_id,
        options,
        command,
        input_bytes=None,
        stdout_limit=1024 * 1024,
        timeout=120,
    ):
        container_id, _ = self.create_container(role, image_id, options, command)
        start_arguments = ["container", "start", "--attach"]
        if input_bytes is not None:
            start_arguments.append("--interactive")
        start_arguments.append(container_id)
        stdout, stderr, return_code = self.docker(
            start_arguments,
            "run " + role + " container",
            input_bytes=input_bytes,
            timeout=timeout,
            stdout_limit=stdout_limit,
            stderr_limit=1024 * 1024,
            check=False,
        )
        inspected = self.inspect_container(container_id, "inspect stopped " + role)
        state = inspected.get("State", {})
        require(state.get("Running") is False, role + " container is still running")
        require(state.get("Status") == "exited", role + " container did not exit")
        require(inspected.get("RestartCount") == 0, role + " container restarted")
        if return_code != 0 or state.get("ExitCode") != 0:
            detail = self.redact(stderr[-4096:].decode("utf-8", errors="replace")).strip()
            suffix = ": " + detail if detail else ""
            raise SelfTestError(role + " container failed" + suffix)
        self.remove_container(container_id, role)
        return stdout

    def start_postgres(
        self,
        role,
        postgres_image_id,
        socket_directory,
        password,
        data_volume=None,
    ):
        memory = "1024m" if data_volume is not None else "512m"
        options = [
            "--platform",
            "linux/amd64",
            "--network",
            "none",
            "--log-driver",
            "none",
            "--user",
            "70:70",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--restart",
            "no",
            "--stop-timeout",
            "20",
            "--memory",
            memory,
            "--memory-swap",
            memory,
            "--pids-limit",
            "256",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,nodev,size=16m,mode=1777",
            "--mount",
            "type=bind,src={0},dst={1}".format(socket_directory, SOCKET_DESTINATION),
            "--env",
            "POSTGRES_USER=" + ADMIN_NAME,
            "--env",
            "POSTGRES_PASSWORD=" + password,
            "--env",
            "POSTGRES_DB=" + DATABASE_NAME,
            "--env",
            "POSTGRES_INITDB_ARGS=--auth-local=scram-sha-256 --auth-host=scram-sha-256",
            "--env",
            "PGDATA=" + PGDATA_DESTINATION + "/pgdata",
        ]
        if data_volume is None:
            options.extend(
                [
                    "--tmpfs",
                    PGDATA_DESTINATION
                    + ":rw,noexec,nosuid,nodev,size=256m,uid=70,gid=70,mode=0700",
                ]
            )
        else:
            options.extend(
                [
                    "--mount",
                    "type=volume,src={0},dst={1},volume-nocopy".format(
                        data_volume,
                        PGDATA_DESTINATION,
                    ),
                ]
            )
        command = [
            "postgres",
            "-c",
            "listen_addresses=",
            "-c",
            "unix_socket_directories=" + SOCKET_DESTINATION,
        ]
        container_id, inspected = self.create_container(
            role, postgres_image_id, options, command
        )
        assert_postgres_topology(inspected, socket_directory, data_volume)
        self.docker(
            ["container", "start", container_id],
            "start " + role,
            stdout_limit=4096,
        )
        ready = False
        for _ in range(120):
            current = self.inspect_container(container_id, "readiness inspect " + role)
            if current.get("State", {}).get("Running") is True:
                stdout, _, return_code = self.docker(
                    [
                        "container",
                        "exec",
                        "--env",
                        "PGPASSWORD=" + password,
                        container_id,
                        "/usr/local/bin/psql",
                        "--no-psqlrc",
                        "--quiet",
                        "--tuples-only",
                        "--no-align",
                        "--host",
                        SOCKET_DESTINATION,
                        "--username",
                        ADMIN_NAME,
                        "--dbname",
                        DATABASE_NAME,
                        "--command",
                        "SELECT 1",
                    ],
                    "probe " + role + " readiness",
                    timeout=10,
                    stdout_limit=4096,
                    stderr_limit=4096,
                    check=False,
                )
                if return_code == 0 and stdout.decode("ascii", errors="ignore").strip() == "1":
                    ready = True
                    break
            time.sleep(0.25)
        require(ready, role + " initialization timed out")
        time.sleep(1)
        current = self.inspect_container(container_id, "stable inspect " + role)
        require(current.get("State", {}).get("Running") is True, role + " stopped")
        require(current.get("RestartCount") == 0, role + " restarted")
        stdout, _, _ = self.docker(
            [
                "container",
                "exec",
                "--env",
                "PGPASSWORD=" + password,
                container_id,
                "/usr/local/bin/psql",
                "--no-psqlrc",
                "--quiet",
                "--tuples-only",
                "--no-align",
                "--host",
                SOCKET_DESTINATION,
                "--username",
                ADMIN_NAME,
                "--dbname",
                DATABASE_NAME,
                "--command",
                "SELECT 1",
            ],
            "probe stable " + role,
            timeout=10,
            stdout_limit=4096,
            stderr_limit=4096,
        )
        require(stdout.decode("ascii").strip() == "1", role + " is not stable")
        return container_id

    def stop_postgres(self, container_id, role):
        inspected = self.inspect_container(container_id, "pre-stop inspect " + role)
        require(inspected.get("State", {}).get("Running") is True, role + " not running")
        self.docker(
            ["container", "stop", "--time", "20", container_id],
            "stop " + role,
            timeout=30,
            stdout_limit=4096,
        )
        inspected = self.inspect_container(container_id, "stopped inspect " + role)
        state = inspected.get("State", {})
        require(state.get("Running") is False, role + " failed to stop")
        require(state.get("ExitCode") == 0, role + " did not stop cleanly")
        self.remove_container(container_id, role)

    def cleanup(self):
        failures = []
        for container_id, role in reversed(list(self._containers.items())):
            try:
                inspected = self.inspect_container(
                    container_id, "cleanup inspect " + role, check=False
                )
                if inspected is None:
                    self._containers.pop(container_id, None)
                    continue
                if inspected.get("State", {}).get("Running") is True:
                    self.docker(
                        ["container", "stop", "--time", "5", container_id],
                        "cleanup stop " + role,
                        timeout=15,
                        stdout_limit=4096,
                        check=False,
                    )
                self.docker(
                    ["container", "rm", "--volumes", "--force", container_id],
                    "cleanup remove " + role,
                    timeout=15,
                    stdout_limit=4096,
                    check=False,
                )
                remaining = self.inspect_container(
                    container_id, "cleanup verify " + role, check=False
                )
                if remaining is not None:
                    failures.append(role + " remains after cleanup")
                else:
                    self._containers.pop(container_id, None)
            except BaseException as exc:
                failures.append(role + ": " + self.redact(str(exc)))
        return failures


def parse_size(value):
    match = re.fullmatch(r"([0-9]+)([kKmMgG]?)", value)
    require(match is not None, "tmpfs size is invalid")
    multiplier = {"": 1, "k": 1024, "m": 1024 ** 2, "g": 1024 ** 3}[
        match.group(2).lower()
    ]
    return int(match.group(1)) * multiplier


def assert_tmpfs(options, size, required):
    values = options.split(",")
    flags = {item for item in values if "=" not in item}
    settings = dict(item.split("=", 1) for item in values if "=" in item)
    require(required.issubset(flags), "tmpfs security flags changed")
    require(parse_size(settings.get("size", "")) == size, "tmpfs size changed")
    return settings


def assert_postgres_topology(inspected, socket_directory, data_volume=None):
    config = inspected.get("Config", {})
    host = inspected.get("HostConfig", {})
    require(config.get("User") == "70:70", "PostgreSQL user changed")
    require(config.get("Image") == inspected.get("Image"), "PostgreSQL image drifted")
    require(config.get("StopTimeout") == 20, "PostgreSQL stop timeout changed")
    require(
        config.get("Cmd")
        == [
            "postgres",
            "-c",
            "listen_addresses=",
            "-c",
            "unix_socket_directories=" + SOCKET_DESTINATION,
        ],
        "PostgreSQL command changed",
    )
    require(host.get("NetworkMode") == "none", "PostgreSQL network is enabled")
    require(host.get("ReadonlyRootfs") is True, "PostgreSQL rootfs is writable")
    require(host.get("Privileged") is False, "PostgreSQL is privileged")
    require(host.get("AutoRemove") is False, "PostgreSQL escaped exact-ID cleanup")
    require(host.get("CapDrop") == ["ALL"], "PostgreSQL capability drop changed")
    require(
        host.get("SecurityOpt") == ["no-new-privileges"],
        "PostgreSQL no-new-privileges changed",
    )
    require(
        host.get("RestartPolicy") == {"Name": "no", "MaximumRetryCount": 0},
        "PostgreSQL restart policy changed",
    )
    expected_memory = (1024 if data_volume is not None else 512) * 1024 * 1024
    require(host.get("Memory") == expected_memory, "PostgreSQL memory changed")
    require(
        host.get("MemorySwap") == expected_memory,
        "PostgreSQL memory-swap changed",
    )
    require(host.get("PidsLimit") == 256, "PostgreSQL pids limit changed")
    require(host.get("LogConfig", {}).get("Type") == "none", "PostgreSQL logs enabled")
    tmpfs = host.get("Tmpfs", {})
    expected_tmpfs = {"/tmp"} if data_volume is not None else {
        "/tmp",
        PGDATA_DESTINATION,
    }
    require(set(tmpfs) == expected_tmpfs, "PostgreSQL tmpfs changed")
    temporary = assert_tmpfs(
        tmpfs["/tmp"], 16 * 1024 * 1024, {"rw", "noexec", "nosuid", "nodev"}
    )
    require(temporary.get("mode") == "1777", "temporary tmpfs mode changed")
    if data_volume is None:
        data = assert_tmpfs(
            tmpfs[PGDATA_DESTINATION],
            256 * 1024 * 1024,
            {"rw", "noexec", "nosuid", "nodev"},
        )
        require(
            data.get("uid") == "70"
            and data.get("gid") == "70"
            and data.get("mode") in ("0700", "700"),
            "PostgreSQL data tmpfs ownership changed",
        )
    matching_mounts = [
        item
        for item in inspected.get("Mounts", [])
        if item.get("Destination") == SOCKET_DESTINATION
    ]
    require(len(matching_mounts) == 1, "PostgreSQL socket mount changed")
    mount = matching_mounts[0]
    require(mount.get("Type") == "bind" and mount.get("RW") is True, "socket is not RW")
    require(
        Path(mount.get("Source", "")).resolve() == Path(socket_directory).resolve(),
        "PostgreSQL socket source changed",
    )
    data_mounts = [
        item
        for item in inspected.get("Mounts", [])
        if item.get("Destination") == PGDATA_DESTINATION
    ]
    if data_volume is None:
        require(not data_mounts, "tmpfs PostgreSQL gained a data volume")
    else:
        require(len(data_mounts) == 1, "PostgreSQL data volume is missing")
        data_mount = data_mounts[0]
        require(
            data_mount.get("Type") == "volume"
            and data_mount.get("Name") == data_volume
            and data_mount.get("Driver") == "local"
            and data_mount.get("RW") is True,
            "PostgreSQL data volume identity changed",
        )


def hardened_one_shot_options(user, interactive=True):
    values = [
        "--platform",
        "linux/amd64",
        "--network",
        "none",
        "--log-driver",
        "none",
        "--user",
        user,
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--restart",
        "no",
        "--memory",
        "512m",
        "--memory-swap",
        "512m",
        "--pids-limit",
        "256",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,nodev,size=16m,mode=1777",
    ]
    if interactive:
        values.append("--interactive")
    return values


def psql_options(socket_directory, username, password, read_only):
    values = hardened_one_shot_options("70:70")
    values.extend(
        [
            "--tmpfs",
            PGDATA_DESTINATION
            + ":rw,noexec,nosuid,nodev,size=16m,uid=70,gid=70,mode=0700",
            "--mount",
            "type=bind,src={0},dst={1},readonly".format(
                socket_directory, SOCKET_DESTINATION
            ),
            "--env",
            "PGHOST=" + SOCKET_DESTINATION,
            "--env",
            "PGPORT=5432",
            "--env",
            "PGUSER=" + username,
            "--env",
            "PGPASSWORD=" + password,
            "--env",
            "PGDATABASE=" + DATABASE_NAME,
            "--env",
            "XJIE_EXPECTED_DATABASE=" + DATABASE_NAME,
        ]
    )
    if read_only:
        values.extend(["--env", "PGOPTIONS=-c default_transaction_read_only=on"])
    values.extend(["--entrypoint", "/usr/local/bin/psql"])
    return values


def run_psql(
    harness,
    postgres_image_id,
    socket_directory,
    username,
    password,
    sql,
    role,
    read_only,
    stdout_limit,
):
    return harness.run_one_shot(
        role,
        postgres_image_id,
        psql_options(socket_directory, username, password, read_only),
        [
            "--no-psqlrc",
            "--quiet",
            "--tuples-only",
            "--no-align",
            "--set",
            "ON_ERROR_STOP=1",
        ],
        input_bytes=sql,
        stdout_limit=stdout_limit,
    )


def run_guard_cli(harness, guard_source, arguments, label, check=True):
    return harness.run(
        [sys.executable, "-I", str(guard_source)] + list(arguments),
        label,
        timeout=120,
        stdout_limit=1024 * 1024,
        stderr_limit=1024 * 1024,
        check=check,
    )


def emit_guard_file(harness, guard_source, arguments, output, label):
    require(not output.exists(), label + " output already exists")
    run_guard_cli(
        harness,
        guard_source,
        list(arguments) + ["--output", str(output)],
        label,
    )
    metadata = output.stat()
    require(
        stat.S_ISREG(metadata.st_mode)
        and metadata.st_uid == os.geteuid()
        and stat.S_IMODE(metadata.st_mode) == 0o600
        and metadata.st_nlink == 1,
        label + " output is not owner-only",
    )


def assert_image_identity(harness, backend_reference, guard):
    require(
        guard.PINNED_SPEC.get("database_probe_image") == TRUSTED_POSTGRES_REFERENCE,
        "guard PostgreSQL image pin changed",
    )
    harness.docker(
        ["image", "pull", "--platform", "linux/amd64", TRUSTED_POSTGRES_REFERENCE],
        "pull trusted PostgreSQL image",
        timeout=300,
        stdout_limit=4 * 1024 * 1024,
        stderr_limit=4 * 1024 * 1024,
    )
    postgres = harness.inspect_image(TRUSTED_POSTGRES_REFERENCE, "inspect PostgreSQL image")
    postgres_id = postgres.get("Id")
    require(SHA256_ID.fullmatch(postgres_id or "") is not None, "PostgreSQL ID invalid")
    require(
        postgres.get("Os") == "linux" and postgres.get("Architecture") == "amd64",
        "PostgreSQL platform changed",
    )
    require(
        TRUSTED_POSTGRES_REPOSITORY_DIGEST in (postgres.get("RepoDigests") or []),
        "PostgreSQL repository digest changed",
    )
    backend = harness.inspect_image(backend_reference, "inspect backend image")
    backend_id = backend.get("Id")
    require(SHA256_ID.fullmatch(backend_id or "") is not None, "backend ID invalid")
    require(
        backend.get("Os") == "linux" and backend.get("Architecture") == "amd64",
        "backend image is not linux/amd64",
    )
    version = harness.run_one_shot(
        "postgres-version",
        postgres_id,
        hardened_one_shot_options("70:70", interactive=False)
        + ["--entrypoint", "postgres"],
        ["--version"],
        stdout_limit=4096,
    )
    require(version.decode("utf-8").strip() == EXPECTED_POSTGRES_VERSION, "PG version drift")
    return backend_id, postgres_id


def emit_candidate_manifest(harness, guard, guard_source, backend_image_id, work):
    probe = work / "migration-probe.py"
    manifest_path = work / "candidate-manifest.json"
    emit_guard_file(
        harness,
        guard_source,
        ["emit-migration-probe"],
        probe,
        "emit migration probe",
    )
    output = harness.run_one_shot(
        "candidate-manifest",
        backend_image_id,
        hardened_one_shot_options("65534:65534") + ["--entrypoint", "python"],
        ["-I", "-"],
        input_bytes=probe.read_bytes(),
        stdout_limit=4 * 1024 * 1024,
    )
    manifest = parse_single_json(output, "candidate migration manifest")
    guard.validate_migration_manifest(manifest)
    require(
        len(manifest["migrations"]) == EXPECTED_MANIFEST_COUNTS["migrations"],
        "migration inventory changed",
    )
    require(manifest["heads"] == [EXPECTED_ALEMBIC_HEAD], "Alembic head changed")
    require(
        len(manifest["model_schema"]) == EXPECTED_MANIFEST_COUNTS["tables"],
        "candidate table inventory changed",
    )
    write_owner_only(manifest_path, ordered_json(manifest).encode("ascii"))
    return manifest, manifest_path


def materialize_candidate(
    harness,
    guard_source,
    backend_image_id,
    manifest,
    manifest_path,
    socket_directory,
    password,
    work,
    label,
):
    materializer = work / (label + "-materializer.py")
    result_path = work / (label + "-materializer-result.json")
    emit_guard_file(
        harness,
        guard_source,
        ["emit-reference-schema-materializer", "--candidate-manifest", str(manifest_path)],
        materializer,
        "emit " + label + " materializer",
    )
    database_url = (
        "postgresql+psycopg://{0}:{1}@/{2}?host={3}".format(
            ADMIN_NAME, password, DATABASE_NAME, SOCKET_DESTINATION
        )
    )
    harness.add_secret(database_url)
    output = harness.run_one_shot(
        label + "-materializer",
        backend_image_id,
        hardened_one_shot_options("65534:65534")
        + [
            "--mount",
            "type=bind,src={0},dst={1},readonly".format(
                socket_directory, SOCKET_DESTINATION
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
    result = parse_single_json(output, label + " materializer result")
    expected = {
        "schema_version": 3,
        "candidate_manifest_sha256": hashlib.sha256(
            canonical_json(manifest).encode("ascii")
        ).hexdigest(),
        "table_count": EXPECTED_MANIFEST_COUNTS["tables"],
    }
    require(result == expected, label + " materializer result is not exact")
    write_owner_only(result_path, ordered_json(result).encode("ascii"))
    run_guard_cli(
        harness,
        guard_source,
        [
            "validate-reference-materializer-result",
            "--candidate-manifest",
            str(manifest_path),
            "--result",
            str(result_path),
        ],
        "validate " + label + " materializer result",
    )


def assert_catalog_inventory(catalog):
    tables = catalog["tables"]
    columns = [column for table in tables for column in table["columns"]]
    constraints = [item for table in tables for item in table["constraints"]]
    indexes = [item for table in tables for item in table["indexes"]]
    by_type = collections.Counter(item["type"] for item in constraints)
    backed = [item for item in indexes if item["constraint"] is not None]
    explicit = [item for item in indexes if item["constraint"] is None]
    partial = [item for item in indexes if item["predicate"] is not None]
    observed = {
        "tables": len(tables),
        "columns": len(columns),
        "sequences": len(catalog["sequences"]),
        "enums": len(catalog["enum_types"]),
        "constraints": len(constraints),
        "primary_constraints": by_type["p"],
        "foreign_constraints": by_type["f"],
        "unique_constraints": by_type["u"],
        "check_constraints": by_type["c"],
        "indexes": len(indexes),
        "constraint_backed_indexes": len(backed),
        "explicit_indexes": len(explicit),
        "partial_indexes": len(partial),
    }
    require(
        observed == EXPECTED_CATALOG_COUNTS,
        "physical catalog inventory changed: observed={0} expected={1}".format(
            ordered_json(observed),
            ordered_json(EXPECTED_CATALOG_COUNTS),
        ),
    )
    require(
        all(item["constraint"]["type"] in ("p", "u") for item in backed),
        "an FK was incorrectly joined to a constraint-backed index",
    )
    require(
        len({(table["schema"], index["name"]) for table in tables for index in table["indexes"]})
        == len(indexes),
        "physical index identities are duplicated",
    )


def build_reference_catalog(
    harness,
    guard,
    guard_source,
    backend_image_id,
    postgres_image_id,
    manifest,
    manifest_path,
    work,
):
    password = secrets.token_hex(32)
    harness.add_secret(password)
    socket_directory = work / "reference-socket"
    socket_directory.mkdir(mode=0o777)
    os.chmod(socket_directory, 0o777)
    server_id = harness.start_postgres(
        "reference-server", postgres_image_id, socket_directory, password
    )
    try:
        materialize_candidate(
            harness,
            guard_source,
            backend_image_id,
            manifest,
            manifest_path,
            socket_directory,
            password,
            work,
            "reference",
        )
        probe = work / "reference-catalog-probe.sql"
        emit_guard_file(
            harness,
            guard_source,
            ["emit-reference-catalog-probe", "--candidate-manifest", str(manifest_path)],
            probe,
            "emit reference catalog probe",
        )
        first = run_psql(
            harness,
            postgres_image_id,
            socket_directory,
            ADMIN_NAME,
            password,
            probe.read_bytes(),
            "reference-catalog-first",
            True,
            16 * 1024 * 1024,
        ).strip()
        second = run_psql(
            harness,
            postgres_image_id,
            socket_directory,
            ADMIN_NAME,
            password,
            probe.read_bytes(),
            "reference-catalog-second",
            True,
            16 * 1024 * 1024,
        ).strip()
        require(first == second, "reference catalog is not repeatable")
        catalog = parse_single_json(first, "reference catalog")
        guard.validate_reference_catalog(manifest, catalog)
        assert_catalog_inventory(catalog)
    finally:
        if server_id in harness._containers:
            harness.stop_postgres(server_id, "reference-server")
    catalog_path = work / "reference-catalog.json"
    write_owner_only(catalog_path, ordered_json(catalog).encode("ascii"))
    return catalog, catalog_path


def setup_production_role(
    harness, postgres_image_id, socket_directory, admin_password, probe_password, head
):
    sql = """
CREATE TABLE public.alembic_version (
  version_num VARCHAR(32) NOT NULL,
  CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);
INSERT INTO public.alembic_version(version_num) VALUES ({head});
REVOKE CREATE ON DATABASE {database} FROM PUBLIC;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
CREATE ROLE {role}
  LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT
  NOREPLICATION NOBYPASSRLS PASSWORD {password};
GRANT CONNECT ON DATABASE {database} TO {role};
GRANT USAGE ON SCHEMA public TO {role};
GRANT SELECT ON public.alembic_version TO {role};
""".format(
        head=sql_literal(head),
        database=sql_identifier(DATABASE_NAME),
        role=sql_identifier(ROLE_NAME),
        password=sql_literal(probe_password),
    )
    run_psql(
        harness,
        postgres_image_id,
        socket_directory,
        ADMIN_NAME,
        admin_password,
        sql.encode("utf-8"),
        "production-role-setup",
        False,
        65536,
    )


def probe_production(
    harness,
    postgres_image_id,
    socket_directory,
    probe_password,
    probe_sql,
    label,
):
    output = run_psql(
        harness,
        postgres_image_id,
        socket_directory,
        ROLE_NAME,
        probe_password,
        probe_sql,
        label,
        True,
        65536,
    ).strip()
    return parse_single_json(output, label + " result")


def render_attestation_diagnostic(probe_sql):
    marker = b"SELECT CASE WHEN\n  attestation.valid"
    start = probe_sql.rfind(marker)
    end = probe_sql.find(b"\nROLLBACK;", start)
    require(start > 0 and end > start, "database probe diagnostic markers changed")
    diagnostic = b"""SELECT pg_catalog.jsonb_build_object(
  'attestation', attestation.valid,
  'alembic', alembic_attestation.valid,
  'role', role_attestation.valid,
  'unsupported_count', unsupported.count,
  'catalog_equal', observed.catalog = expected.catalog
)
FROM expected, observed, unsupported, alembic_attestation, role_attestation, attestation;
"""
    return probe_sql[:start] + diagnostic + probe_sql[end:]


def alembic_structure_diagnostic():
    return br"""\set ON_ERROR_STOP on
BEGIN TRANSACTION ISOLATION LEVEL SERIALIZABLE READ ONLY;
SET LOCAL search_path TO public, pg_catalog;
WITH relation AS (
  SELECT relation.*
  FROM pg_catalog.pg_class AS relation
  JOIN pg_catalog.pg_namespace AS namespace
    ON namespace.oid = relation.relnamespace
  WHERE namespace.nspname = 'public'
    AND relation.relname = 'alembic_version'
)
SELECT pg_catalog.jsonb_build_object(
  'relations', (SELECT COALESCE(pg_catalog.jsonb_agg(
    pg_catalog.jsonb_build_object(
      'kind', relation.relkind,
      'persistence', relation.relpersistence,
      'row_security', relation.relrowsecurity,
      'force_row_security', relation.relforcerowsecurity,
      'replica_identity', relation.relreplident,
      'options', relation.reloptions,
      'access_method', access_method.amname,
      'has_select', pg_catalog.has_table_privilege(
        current_user, relation.oid, 'SELECT'
      )
    )), '[]'::pg_catalog.jsonb)
    FROM relation
    LEFT JOIN pg_catalog.pg_am AS access_method
      ON access_method.oid = relation.relam),
  'columns', (SELECT COALESCE(pg_catalog.jsonb_agg(
    pg_catalog.jsonb_build_object(
      'position', attribute.attnum,
      'name', attribute.attname,
      'not_null', attribute.attnotnull,
      'identity', attribute.attidentity,
      'generated', attribute.attgenerated,
      'dimensions', attribute.attndims,
      'type_schema', type_namespace.nspname,
      'type_name', type_value.typname,
      'typmod', attribute.atttypmod,
      'formatted', pg_catalog.format_type(attribute.atttypid, attribute.atttypmod),
      'collation_schema', collation_namespace.nspname,
      'collation_name', collation_value.collname,
      'default_count', (SELECT pg_catalog.count(*)
        FROM pg_catalog.pg_attrdef AS default_value
        WHERE default_value.adrelid = attribute.attrelid
          AND default_value.adnum = attribute.attnum)
    ) ORDER BY attribute.attnum), '[]'::pg_catalog.jsonb)
    FROM relation
    JOIN pg_catalog.pg_attribute AS attribute
      ON attribute.attrelid = relation.oid
    JOIN pg_catalog.pg_type AS type_value ON type_value.oid = attribute.atttypid
    JOIN pg_catalog.pg_namespace AS type_namespace
      ON type_namespace.oid = type_value.typnamespace
    LEFT JOIN pg_catalog.pg_collation AS collation_value
      ON collation_value.oid = attribute.attcollation
    LEFT JOIN pg_catalog.pg_namespace AS collation_namespace
      ON collation_namespace.oid = collation_value.collnamespace
    WHERE attribute.attnum > 0 AND NOT attribute.attisdropped),
  'constraints', (SELECT COALESCE(pg_catalog.jsonb_agg(
    pg_catalog.jsonb_build_object(
      'name', constraint_value.conname,
      'type', constraint_value.contype,
      'key', constraint_value.conkey::pg_catalog.text,
      'deferrable', constraint_value.condeferrable,
      'deferred', constraint_value.condeferred,
      'validated', constraint_value.convalidated,
      'no_inherit', constraint_value.connoinherit
    ) ORDER BY constraint_value.conname), '[]'::pg_catalog.jsonb)
    FROM relation
    JOIN pg_catalog.pg_constraint AS constraint_value
      ON constraint_value.conrelid = relation.oid),
  'indexes', (SELECT COALESCE(pg_catalog.jsonb_agg(
    pg_catalog.jsonb_build_object(
      'name', index_relation.relname,
      'kind', index_relation.relkind,
      'options', index_relation.reloptions,
      'method', access_method.amname,
      'unique', index_value.indisunique,
      'primary', index_value.indisprimary,
      'valid', index_value.indisvalid,
      'ready', index_value.indisready,
      'live', index_value.indislive,
      'clustered', index_value.indisclustered,
      'replica_identity', index_value.indisreplident,
      'nulls_not_distinct', index_value.indnullsnotdistinct,
      'key_attributes', index_value.indnkeyatts,
      'all_attributes', index_value.indnatts,
      'key', index_value.indkey::pg_catalog.text,
      'has_predicate', index_value.indpred IS NOT NULL,
      'has_expressions', index_value.indexprs IS NOT NULL
    ) ORDER BY index_relation.relname), '[]'::pg_catalog.jsonb)
    FROM relation
    JOIN pg_catalog.pg_index AS index_value
      ON index_value.indrelid = relation.oid
    JOIN pg_catalog.pg_class AS index_relation
      ON index_relation.oid = index_value.indexrelid
    JOIN pg_catalog.pg_am AS access_method
      ON access_method.oid = index_relation.relam),
  'row_count', (SELECT pg_catalog.count(*) FROM public.alembic_version),
  'head', (SELECT pg_catalog.min(version_num) FROM public.alembic_version)
);
ROLLBACK;
"""


def validate_database_result_cli(
    harness,
    guard_source,
    manifest_path,
    catalog_path,
    result,
    work,
    label,
    expect_success,
):
    path = work / (label + "-result.json")
    write_owner_only(path, ordered_json(result).encode("ascii"))
    _, _, return_code = run_guard_cli(
        harness,
        guard_source,
        [
            "validate-database-schema",
            "--candidate-manifest",
            str(manifest_path),
            "--reference-catalog",
            str(catalog_path),
            "--database-catalog",
            str(path),
        ],
        "validate " + label,
        check=False,
    )
    if expect_success:
        require(return_code == 0, label + " did not pass the guard CLI")
    else:
        require(return_code != 0, label + " unexpectedly passed the guard CLI")


def admin_sql(
    harness,
    postgres_image_id,
    socket_directory,
    admin_password,
    sql,
    label,
):
    run_psql(
        harness,
        postgres_image_id,
        socket_directory,
        ADMIN_NAME,
        admin_password,
        sql.encode("utf-8"),
        label,
        False,
        65536,
    )


def exercise_production_attestation(
    harness,
    guard,
    guard_source,
    backend_image_id,
    postgres_image_id,
    manifest,
    manifest_path,
    catalog,
    catalog_path,
    work,
):
    admin_password = secrets.token_hex(32)
    probe_password = secrets.token_hex(32)
    harness.add_secret(admin_password)
    harness.add_secret(probe_password)
    socket_directory = work / "production-socket"
    socket_directory.mkdir(mode=0o777)
    os.chmod(socket_directory, 0o777)
    server_id = harness.start_postgres(
        "production-server", postgres_image_id, socket_directory, admin_password
    )
    try:
        materialize_candidate(
            harness,
            guard_source,
            backend_image_id,
            manifest,
            manifest_path,
            socket_directory,
            admin_password,
            work,
            "production",
        )
        setup_production_role(
            harness,
            postgres_image_id,
            socket_directory,
            admin_password,
            probe_password,
            manifest["heads"][0],
        )
        database_probe = work / "database-schema-probe.sql"
        emit_guard_file(
            harness,
            guard_source,
            [
                "emit-database-schema-probe",
                "--candidate-manifest",
                str(manifest_path),
                "--reference-catalog",
                str(catalog_path),
            ],
            database_probe,
            "emit database schema probe",
        )
        probe_sql = database_probe.read_bytes()
        positive = probe_production(
            harness,
            postgres_image_id,
            socket_directory,
            probe_password,
            probe_sql,
            "production-positive",
        )
        expected = guard.expected_database_schema_result(manifest, catalog)
        diagnostic = None
        if positive != expected:
            diagnostic = probe_production(
                harness,
                postgres_image_id,
                socket_directory,
                probe_password,
                render_attestation_diagnostic(probe_sql),
                "production-positive-diagnostic",
            )
            if diagnostic.get("alembic") is False:
                diagnostic["alembic_structure"] = probe_production(
                    harness,
                    postgres_image_id,
                    socket_directory,
                    probe_password,
                    alembic_structure_diagnostic(),
                    "production-alembic-structure-diagnostic",
                )
        require(
            positive == expected,
            "production positive result is not exact: {0}; diagnostic={1}".format(
                ordered_json(positive), ordered_json(diagnostic)
            ),
        )
        guard.validate_database_schema(manifest, catalog, positive)
        validate_database_result_cli(
            harness,
            guard_source,
            manifest_path,
            catalog_path,
            positive,
            work,
            "production-positive",
            True,
        )

        def require_rejection(label):
            result = probe_production(
                harness,
                postgres_image_id,
                socket_directory,
                probe_password,
                probe_sql,
                label,
            )
            require(result == EXPECTED_ATTESTATION_ERROR, label + " was not rejected")
            validate_database_result_cli(
                harness,
                guard_source,
                manifest_path,
                catalog_path,
                result,
                work,
                label,
                False,
            )

        feedback = next(
            (item for item in catalog["tables"] if item["name"] == "user_feedback"),
            None,
        )
        require(feedback is not None, "default drift target table is missing")
        status_column = next(
            (item for item in feedback["columns"] if item["name"] == "status"), None
        )
        require(
            status_column is not None and status_column["default"] is not None,
            "default drift target is missing",
        )
        default_target = "{0}.{1}".format(
            sql_identifier(feedback["schema"]), sql_identifier(feedback["name"])
        )
        default_column = sql_identifier(status_column["name"])
        default_changed = False
        try:
            admin_sql(
                harness,
                postgres_image_id,
                socket_directory,
                admin_password,
                "ALTER TABLE {0} ALTER COLUMN {1} SET DEFAULT NULL;".format(
                    default_target, default_column
                ),
                "mutate production default",
            )
            default_changed = True
            require_rejection("production-default-drift")
        finally:
            if default_changed:
                admin_sql(
                    harness,
                    postgres_image_id,
                    socket_directory,
                    admin_password,
                    "ALTER TABLE {0} ALTER COLUMN {1} SET DEFAULT {2};".format(
                        default_target, default_column, status_column["default"]
                    ),
                    "restore production default",
                )

        backing_target = None
        for table in catalog["tables"]:
            for index in table["indexes"]:
                owner = index["constraint"]
                if (
                    owner is not None
                    and owner["type"] in ("p", "u")
                    and index["method"] == "btree"
                    and index["options"] == []
                ):
                    backing_target = (table["schema"], index["name"])
                    break
            if backing_target is not None:
                break
        require(backing_target is not None, "constraint-backed index target is missing")
        backing_name = "{0}.{1}".format(
            sql_identifier(backing_target[0]), sql_identifier(backing_target[1])
        )
        index_changed = False
        try:
            admin_sql(
                harness,
                postgres_image_id,
                socket_directory,
                admin_password,
                "ALTER INDEX {0} SET (fillfactor=70);".format(backing_name),
                "mutate constraint-backed index",
            )
            index_changed = True
            require_rejection("production-backed-index-drift")
        finally:
            if index_changed:
                admin_sql(
                    harness,
                    postgres_image_id,
                    socket_directory,
                    admin_password,
                    "ALTER INDEX {0} RESET (fillfactor);".format(backing_name),
                    "restore constraint-backed index",
                )

        head_changed = False
        try:
            admin_sql(
                harness,
                postgres_image_id,
                socket_directory,
                admin_password,
                "UPDATE public.alembic_version SET version_num = "
                + sql_literal("0000_selftest_wrong_head")
                + ";",
                "mutate Alembic head",
            )
            head_changed = True
            require_rejection("production-wrong-alembic-head")
        finally:
            if head_changed:
                admin_sql(
                    harness,
                    postgres_image_id,
                    socket_directory,
                    admin_password,
                    "UPDATE public.alembic_version SET version_num = "
                    + sql_literal(manifest["heads"][0])
                    + ";",
                    "restore Alembic head",
                )

        restored = probe_production(
            harness,
            postgres_image_id,
            socket_directory,
            probe_password,
            probe_sql,
            "production-restored-positive",
        )
        require(restored == expected, "restored production catalog is not exact")
        guard.validate_database_schema(manifest, catalog, restored)
    finally:
        if server_id in harness._containers:
            harness.stop_postgres(server_id, "production-server")
    return positive


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Run the real PostgreSQL production catalog integration gate."
    )
    parser.add_argument(
        "--backend-image",
        required=True,
        help="Already-built linux/amd64 production backend image tag or ID.",
    )
    return parser.parse_args()


def main():
    require(sys.flags.isolated == 1, "self-test must run with Python isolated mode")
    require(shutil.which("docker") is not None, "docker is unavailable")
    arguments = parse_arguments()
    require(
        arguments.backend_image
        and not arguments.backend_image.startswith("-")
        and "\x00" not in arguments.backend_image,
        "backend image reference is invalid",
    )
    repository_root = Path(__file__).resolve().parent.parent
    guard, guard_source = load_guard(repository_root)
    work = Path(tempfile.mkdtemp(prefix="xjie-pg-selftest-", dir="/tmp")).resolve()
    os.chmod(work, 0o700)
    harness = DockerHarness(work)
    old_handlers = {}

    def interrupted(signum, _frame):
        raise KeyboardInterrupt("signal {0}".format(signum))

    for signum in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
        old_handlers[signum] = signal.signal(signum, interrupted)

    primary_error = None
    cleanup_failures = []
    try:
        backend_image_id, postgres_image_id = assert_image_identity(
            harness, arguments.backend_image, guard
        )
        manifest, manifest_path = emit_candidate_manifest(
            harness, guard, guard_source, backend_image_id, work
        )
        catalog, catalog_path = build_reference_catalog(
            harness,
            guard,
            guard_source,
            backend_image_id,
            postgres_image_id,
            manifest,
            manifest_path,
            work,
        )
        result = exercise_production_attestation(
            harness,
            guard,
            guard_source,
            backend_image_id,
            postgres_image_id,
            manifest,
            manifest_path,
            catalog,
            catalog_path,
            work,
        )
        print(
            "POSTGRES CATALOG SELF-TEST: passed; "
            "postgres=16.14 migrations={0} tables={1} constraints={2} indexes={3} "
            "digest={4}".format(
                len(manifest["migrations"]),
                len(catalog["tables"]),
                EXPECTED_CATALOG_COUNTS["constraints"],
                EXPECTED_CATALOG_COUNTS["indexes"],
                result["reference_catalog_sha256"],
            )
        )
    except BaseException as exc:
        primary_error = exc
    finally:
        cleanup_failures = harness.cleanup()
        shutil.rmtree(work, ignore_errors=True)
        for signum, handler in old_handlers.items():
            signal.signal(signum, handler)
    if primary_error is not None:
        detail = harness.redact(str(primary_error))
        if cleanup_failures:
            detail += "; cleanup: " + "; ".join(cleanup_failures)
        raise SystemExit("POSTGRES CATALOG SELF-TEST: failed: " + detail)
    if cleanup_failures:
        raise SystemExit(
            "POSTGRES CATALOG SELF-TEST: failed cleanup: "
            + "; ".join(cleanup_failures)
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
