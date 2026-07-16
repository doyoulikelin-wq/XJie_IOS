#!/usr/bin/python3 -I
"""Root-only Linux runtime checks for the production deployment supervisor.

This is intentionally not a unittest module: the release inventory counts are
fixed, while CI still needs executable coverage of Linux-only credential,
descriptor, lock, death-pipe, and process-group semantics.
"""

import argparse
import array
import ctypes
import fcntl
import hashlib
import json
import os
import re
import runpy
import select
import secrets
import shlex
import signal
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import time
import types
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = REPO_ROOT / "scripts" / "launch_production_deploy.py"
DEPLOY_SHELL = REPO_ROOT / "scripts" / "deploy_literature.sh"
DEPLOY_GUARD = REPO_ROOT / "backend" / "deploy" / "production_deploy_guard.py"


def load_live_script_api(path, run_name, anchor_name):
    """Return the namespace actually read by functions loaded through runpy."""
    exports = runpy.run_path(str(path), run_name=run_name)
    anchor = exports.get(anchor_name)
    if not isinstance(anchor, types.FunctionType):
        raise RuntimeError(f"{path} does not export callable anchor {anchor_name}")
    namespace = anchor.__globals__
    if namespace.get(anchor_name) is not anchor:
        raise RuntimeError(f"{path} returned a detached execution namespace")
    return namespace


API = load_live_script_api(
    LAUNCHER,
    "xjie_linux_launcher_selftest",
    "broker_approve_expand_migration",
)
GUARD_API = load_live_script_api(
    DEPLOY_GUARD,
    "xjie_linux_launcher_docker_selftest",
    "deployment_name",
)
NOBODY_UID = 65534
NOBODY_GID = 65534
PR_SET_CHILD_SUBREAPER = 36
DOCKER = Path("/usr/bin/docker")
CONTAINER_ID_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
IMAGE_ID_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")
CONTAINER_NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
DOCKER_ENVIRONMENT = {
    "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
    "LC_ALL": "C",
    "HOME": "/nonexistent",
    "XDG_CONFIG_HOME": "/nonexistent",
    "DOCKER_HOST": "unix:///var/run/docker.sock",
}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def wait_child(pid, label):
    observed, status = os.waitpid(pid, 0)
    require(observed == pid, label + " was not reaped")
    require(os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0, label + " failed")


def enable_child_subreaper():
    libc = ctypes.CDLL(None, use_errno=True)
    require(
        libc.prctl(PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) == 0,
        "cannot enable child subreaper",
    )


def read_exact(descriptor, size, timeout=5):
    payload = bytearray()
    deadline = time.monotonic() + timeout
    while len(payload) < size:
        remaining = deadline - time.monotonic()
        require(remaining > 0, "timed out reading child metadata")
        ready, _, _ = select.select([descriptor], [], [], remaining)
        require(ready, "timed out reading child metadata")
        chunk = os.read(descriptor, size - len(payload))
        require(chunk, "child metadata closed early")
        payload.extend(chunk)
    return bytes(payload)


def docker_command(arguments, *, timeout=30):
    return subprocess.run(
        [str(DOCKER), *arguments],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=DOCKER_ENVIRONMENT,
        close_fds=True,
        check=False,
        timeout=timeout,
    )


def docker_output(arguments, label, *, timeout=30):
    result = docker_command(arguments, timeout=timeout)
    require(result.returncode == 0, label + " failed")
    try:
        return result.stdout.decode("ascii", "strict").strip()
    except UnicodeDecodeError as error:
        raise RuntimeError(label + " returned non-ASCII identity metadata") from error


def resolve_immutable_image(image_reference):
    metadata = docker_output(
        [
            "image",
            "inspect",
            "--format",
            "{{.Id}}|{{.Os}}|{{.Architecture}}",
            "--",
            image_reference,
        ],
        "production image identity inspection",
    )
    fields = metadata.split("|")
    require(len(fields) == 3, "production image identity shape changed")
    image_id, operating_system, architecture = fields
    require(
        IMAGE_ID_PATTERN.fullmatch(image_id) is not None,
        "production image is not bound to an immutable full ID",
    )
    require(
        operating_system == "linux" and architecture == "amd64",
        "production image is not linux/amd64",
    )
    exact_id = docker_output(
        ["image", "inspect", "--format", "{{.Id}}", "--", image_id],
        "immutable production image reinspection",
    )
    require(exact_id == image_id, "production image ID changed during resolution")
    return image_id


def inspect_container_identity(reference):
    result = docker_command(
        [
            "container",
            "inspect",
            "--format",
            (
                "{{.Id}}|{{.Image}}|{{.Config.Image}}|"
                "{{.HostConfig.NetworkMode}}|{{.HostConfig.AutoRemove}}|"
                "{{.State.Running}}|{{.State.Pid}}"
            ),
            "--",
            reference,
        ]
    )
    if result.returncode != 0:
        if CONTAINER_ID_PATTERN.fullmatch(reference) is not None:
            filter_value = "id=" + reference
        else:
            require(
                CONTAINER_NAME_PATTERN.fullmatch(reference) is not None,
                "container lookup reference is invalid",
            )
            filter_value = "name=^/" + reference + "$"
        listing = docker_command(
            [
                "container",
                "ls",
                "--all",
                "--quiet",
                "--no-trunc",
                "--filter",
                filter_value,
            ]
        )
        require(listing.returncode == 0, "cannot distinguish absent container from daemon failure")
        require(
            not listing.stdout.strip(),
            "container exists but exact identity inspection failed",
        )
        return None
    try:
        metadata = result.stdout.decode("ascii", "strict").strip()
    except UnicodeDecodeError as error:
        raise RuntimeError("container identity metadata is not ASCII") from error
    fields = metadata.split("|")
    require(len(fields) == 7, "container identity metadata shape changed")
    require(
        CONTAINER_ID_PATTERN.fullmatch(fields[0]) is not None,
        "container inspect returned a non-immutable ID",
    )
    return fields


def remove_exact_container_if_present(container_id):
    if container_id is None:
        return
    require(
        CONTAINER_ID_PATTERN.fullmatch(container_id) is not None,
        "refusing non-exact container cleanup identity",
    )
    result = docker_command(
        ["container", "rm", "--force", "--volumes", container_id],
        timeout=30,
    )
    require(
        result.returncode == 0 or inspect_container_identity(container_id) is None,
        "finally cleanup could not remove the exact self-test container",
    )


def extract_shell_region(payload, start_marker, end_marker, label):
    require(payload.count(start_marker) == 1, label + " start marker changed")
    start = payload.index(start_marker)
    end = payload.find(end_marker, start + len(start_marker))
    require(end >= 0, label + " end marker changed")
    return payload[start:end].rstrip() + "\n"


def production_cleanup_functions():
    payload = DEPLOY_SHELL.read_text(encoding="utf-8")
    container_exists = extract_shell_region(
        payload,
        "container_exists() {\n",
        "assert_exact_stopped_one_shot() {\n",
        "deploy container_exists",
    )
    remove_exact = extract_shell_region(
        payload,
        "remove_exact_prejournal_container() {\n",
        "cleanup() {\n",
        "deploy exact pre-journal cleanup",
    )
    cleanup = extract_shell_region(
        payload,
        "cleanup() {\n",
        "trap cleanup EXIT\n",
        "deploy EXIT cleanup",
    )
    require(
        remove_exact.count(
            'docker container rm --force --volumes "$expected_id"'
        )
        == 1,
        "deploy cleanup no longer force-removes only its exact container ID",
    )
    require(
        '"$ephemeral_container" "$ephemeral_container_id"' in cleanup,
        "deploy EXIT cleanup no longer binds ephemeral name and exact ID",
    )
    return container_exists + "\n" + remove_exact + "\n" + cleanup


def test_descriptor_scrub():
    child = os.fork()
    if child == 0:
        try:
            for target in range(3, 13):
                descriptor = os.open("/dev/null", os.O_RDONLY | os.O_CLOEXEC)
                if descriptor != target:
                    os.dup2(descriptor, target, inheritable=True)
                    os.close(descriptor)
            API["close_unapproved_descriptors"](set())
            for target in range(3, 13):
                try:
                    os.fstat(target)
                except OSError:
                    continue
                raise RuntimeError("inherited descriptor survived scrub")
            os._exit(0)
        except BaseException:
            os._exit(1)
    wait_child(child, "descriptor scrub")


def test_credential_pipe_identity():
    child = os.fork()
    if child == 0:
        try:
            read_descriptor, write_descriptor = os.pipe2(os.O_CLOEXEC)
            os.write(write_descriptor, b"synthetic-token\0")
            os.close(write_descriptor)
            token = API["read_token_from_standard_input"](
                ["a" * 40, "deploy"],
                read_descriptor,
            )
            os.close(read_descriptor)
            require(bytes(token) == b"synthetic-token", "anonymous token pipe failed")
            os._exit(0)
        except BaseException:
            os._exit(1)
    wait_child(child, "anonymous credential pipe")

    with tempfile.TemporaryDirectory(prefix="xjie-named-fifo-") as temp_dir:
        fifo_path = Path(temp_dir) / "credential.fifo"
        os.mkfifo(fifo_path, 0o600)
        fifo_descriptor = os.open(
            fifo_path,
            os.O_RDWR | os.O_NONBLOCK | os.O_CLOEXEC,
        )
        try:
            rejected = False
            try:
                API["read_token_from_standard_input"](
                    ["a" * 40, "deploy"],
                    fifo_descriptor,
                )
            except SystemExit as error:
                rejected = "named FIFO" in str(error)
            require(rejected, "named FIFO was accepted as the GitHub token channel")

            child = os.fork()
            if child == 0:
                try:
                    null_descriptor = os.open(
                        "/dev/null",
                        os.O_RDONLY | os.O_CLOEXEC,
                    )
                    os.dup2(
                        null_descriptor,
                        API["INSTALLER_ROOT_LOCK_FD"],
                        inheritable=True,
                    )
                    os.dup2(
                        null_descriptor,
                        API["INSTALLER_LEGACY_LOCK_FD"],
                        inheritable=True,
                    )
                    os.dup2(
                        fifo_descriptor,
                        API["INSTALLER_AUTHORITY_FD"],
                        inheritable=True,
                    )
                    if null_descriptor not in {
                        API["INSTALLER_ROOT_LOCK_FD"],
                        API["INSTALLER_LEGACY_LOCK_FD"],
                        API["INSTALLER_AUTHORITY_FD"],
                    }:
                        os.close(null_descriptor)
                    rejected = False
                    try:
                        API["consume_installer_doctor_authority"](["--doctor"])
                    except SystemExit as error:
                        rejected = "named FIFO" in str(error)
                    require(
                        rejected,
                        "named FIFO was accepted as installer doctor authority",
                    )
                    os._exit(0)
                except BaseException:
                    os._exit(1)
            wait_child(child, "named installer authority FIFO rejection")
        finally:
            os.close(fifo_descriptor)


def test_broker_kernel_credentials():
    parent, child_endpoint = socket.socketpair(
        socket.AF_UNIX,
        socket.SOCK_SEQPACKET | socket.SOCK_CLOEXEC,
    )
    parent.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
    result_read, result_write = os.pipe2(os.O_CLOEXEC)
    supervisor_pid = os.getpid()
    leader = os.fork()
    if leader == 0:
        try:
            parent.close()
            os.close(result_read)
            os.setsid()
            helper = os.fork()
            if helper == 0:
                try:
                    os.setgroups([])
                    os.setgid(NOBODY_GID)
                    os.setuid(NOBODY_UID)
                    peer = struct.unpack(
                        "3i",
                        child_endpoint.getsockopt(
                            socket.SOL_SOCKET,
                            socket.SO_PEERCRED,
                            struct.calcsize("3i"),
                        ),
                    )
                    require(
                        peer == (supervisor_pid, 0, 0),
                        "broker helper did not authenticate the root supervisor",
                    )
                    require(child_endpoint.send(b"PING\0") == 5, "broker send failed")
                    response = child_endpoint.recv(1025)
                    require(response == b"OK broker ready\0", "broker response changed")
                    os.write(result_write, b"P")
                    os._exit(0)
                except BaseException:
                    os._exit(1)
            child_endpoint.close()
            os.close(result_write)
            wait_child(helper, "broker helper")
            os._exit(0)
        except BaseException:
            os._exit(1)

    child_endpoint.close()
    os.close(result_write)
    principal = types.SimpleNamespace(pw_uid=NOBODY_UID, pw_gid=NOBODY_GID)
    API["broker_wait_for_child"](
        leader,
        parent,
        None,
        principal,
        None,
        ["a" * 40, "deploy"],
    )
    require(read_exact(result_read, 1) == b"P", "broker roundtrip failed")
    observed, status = os.waitpid(leader, 0)
    require(observed == leader, "broker leader was not reaped")
    require(os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0, "broker leader failed")
    os.close(result_read)
    parent.close()

    # Build the peer endpoint only after dropping privileges, then pass its
    # opposite endpoint to root. Linux SO_PEERCRED must expose the non-root
    # creator and therefore make the shell-side root-peer predicate fail.
    control_parent, control_child = socket.socketpair(socket.AF_UNIX, socket.SOCK_DGRAM)
    release_read, release_write = os.pipe2(os.O_CLOEXEC)
    fake = os.fork()
    if fake == 0:
        try:
            control_parent.close()
            os.close(release_write)
            os.setgroups([])
            os.setgid(NOBODY_GID)
            os.setuid(NOBODY_UID)
            root_side, fake_side = socket.socketpair(
                socket.AF_UNIX,
                socket.SOCK_SEQPACKET | socket.SOCK_CLOEXEC,
            )
            rights = array.array("i", [root_side.fileno()])
            control_child.sendmsg(
                [b"F"],
                [(socket.SOL_SOCKET, socket.SCM_RIGHTS, rights)],
            )
            root_side.close()
            os.read(release_read, 1)
            fake_side.close()
            os._exit(0)
        except BaseException:
            os._exit(1)
    control_child.close()
    os.close(release_read)
    message, ancillary, _, _ = control_parent.recvmsg(
        1,
        socket.CMSG_SPACE(array.array("i").itemsize),
    )
    require(message == b"F", "fake broker descriptor transfer failed")
    received = array.array("i")
    for level, kind, data in ancillary:
        if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
            received.frombytes(data[: received.itemsize])
    require(len(received) == 1, "fake broker descriptor is missing")
    fake_peer = socket.socket(fileno=received[0])
    peer_pid, peer_uid, peer_gid = struct.unpack(
        "3i",
        fake_peer.getsockopt(
            socket.SOL_SOCKET,
            socket.SO_PEERCRED,
            struct.calcsize("3i"),
        ),
    )
    require(peer_pid == fake, "fake broker peer pid is not kernel-bound")
    require(
        (peer_uid, peer_gid) == (NOBODY_UID, NOBODY_GID),
        "fake non-root broker peer was not rejected by its credentials",
    )
    fake_peer.close()
    os.write(release_write, b"X")
    os.close(release_write)
    control_parent.close()
    wait_child(fake, "fake broker peer")


def test_schema_migration_approval_binding():
    require(
        API is API["broker_approve_expand_migration"].__globals__,
        "launcher overrides must target the live execution namespace",
    )
    expected_sha = "a" * 40
    with tempfile.TemporaryDirectory(prefix="xjie-schema-approval-") as temporary:
        root = Path(temporary)
        locks = root / ".locks"
        locks.mkdir(mode=0o700)
        principal = types.SimpleNamespace(
            pw_uid=NOBODY_UID,
            pw_gid=NOBODY_GID,
            pw_dir=str(root),
        )
        migrations = [
            {
                "revision": "0022_candidate",
                "down_revision": "0021_old",
                "sha256": "4" * 64,
            },
            {
                "revision": "0023_candidate",
                "down_revision": "0022_candidate",
                "sha256": "5" * 64,
            },
        ]
        migration_digest = hashlib.sha256(
            json.dumps(
                {"schema_version": 1, "migrations": migrations},
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        plan = {
            "schema_version": 2,
            "expected_main_sha": expected_sha,
            "trusted_bundle_sha256": "1" * 64,
            "old_manifest_sha256": "2" * 64,
            "old_head": "0021_old",
            "candidate_manifest_sha256": "3" * 64,
            "candidate_head": "0023_candidate",
            "migrations": migrations,
            "migration_sha256": migration_digest,
            "operation_policy_sha256": "6" * 64,
            "old_catalog_sha256": "7" * 64,
            "candidate_catalog_sha256": "8" * 64,
        }
        plan_payload = (
            json.dumps(plan, separators=(",", ":")) + "\n"
        ).encode("ascii")
        plan_path = locks / f"xjie-production-expand-plan-{expected_sha}.json"
        plan_path.write_bytes(plan_payload)
        plan_path.chmod(0o600)
        os.chown(plan_path, NOBODY_UID, NOBODY_GID)
        approval_path = root / "schema-migration-approval.json"
        approval = {
            "schema_version": 1,
            "expected_main_sha": expected_sha,
            "plan_sha256": hashlib.sha256(plan_payload).hexdigest(),
        }
        approval_path.write_text(
            json.dumps(approval, separators=(",", ":")) + "\n",
            encoding="ascii",
        )
        approval_path.chmod(0o400)
        original_approval_path = API["SCHEMA_MIGRATION_APPROVAL"]
        API["SCHEMA_MIGRATION_APPROVAL"] = str(approval_path)
        try:
            exact_arguments = [
                expected_sha,
                "expand-deploy",
                "--confirm-expand-migration",
            ]
            response = API["broker_approve_expand_migration"](
                principal,
                expected_sha,
                exact_arguments,
            )
            require(
                response.endswith(approval["plan_sha256"]),
                "schema migration approval did not bind the exact plan digest",
            )
            for invalid_arguments in (
                [expected_sha, "deploy"],
                [expected_sha, "expand-deploy"],
                [
                    expected_sha,
                    "expand-deploy",
                    "--confirm-expand-migration",
                    "extra",
                ],
            ):
                rejected = False
                try:
                    API["broker_approve_expand_migration"](
                        principal,
                        expected_sha,
                        invalid_arguments,
                    )
                except SystemExit:
                    rejected = True
                require(rejected, "migration approval accepted a different action")
            for label, mutate in (
                (
                    "non-linear migration chain",
                    lambda value: value["migrations"][1].update(
                        down_revision="0021_old"
                    ),
                ),
                (
                    "per-file migration digest drift",
                    lambda value: value["migrations"][1].update(sha256="9" * 64),
                ),
            ):
                changed_plan = json.loads(plan_payload)
                mutate(changed_plan)
                changed_payload = (
                    json.dumps(changed_plan, separators=(",", ":")) + "\n"
                ).encode("ascii")
                plan_path.write_bytes(changed_payload)
                plan_path.chmod(0o600)
                os.chown(plan_path, NOBODY_UID, NOBODY_GID)
                approval["plan_sha256"] = hashlib.sha256(changed_payload).hexdigest()
                approval_path.chmod(0o600)
                approval_path.write_text(
                    json.dumps(approval, separators=(",", ":")) + "\n",
                    encoding="ascii",
                )
                approval_path.chmod(0o400)
                rejected = False
                try:
                    API["broker_approve_expand_migration"](
                        principal,
                        expected_sha,
                        exact_arguments,
                    )
                except SystemExit:
                    rejected = True
                require(rejected, "migration approval accepted " + label)
            plan_path.write_bytes(plan_payload)
            plan_path.chmod(0o600)
            os.chown(plan_path, NOBODY_UID, NOBODY_GID)
            approval["plan_sha256"] = "f" * 64
            approval_path.chmod(0o600)
            approval_path.write_text(
                json.dumps(approval, separators=(",", ":")) + "\n",
                encoding="ascii",
            )
            approval_path.chmod(0o400)
            rejected = False
            try:
                API["broker_approve_expand_migration"](
                    principal,
                    expected_sha,
                    exact_arguments,
                )
            except SystemExit:
                rejected = True
            require(rejected, "migration approval accepted a stale plan digest")
            plan_path.chmod(0o640)
            rejected = False
            try:
                API["broker_approve_expand_migration"](
                    principal,
                    expected_sha,
                    exact_arguments,
                )
            except SystemExit:
                rejected = True
            require(rejected, "migration approval accepted a non-owner-only plan")
        finally:
            API["SCHEMA_MIGRATION_APPROVAL"] = original_approval_path


HARNESS_SCRIPT = r'''
set -euo pipefail
cleanup() {
  trap '' HUP INT QUIT TERM
  printf 'CLEANUP_STARTED\n'
  /usr/bin/sleep 3
  printf 'CLEANUP_FINISHED\n'
}
terminate() {
  trap '' HUP INT QUIT TERM
  kill -TERM -- "-$$" 2>/dev/null || true
  exit 143
}
trap cleanup EXIT
trap terminate HUP INT QUIT TERM
printf 'READY\n'
/usr/bin/python3 -I -c 'import os,time; print("COMMAND %d" % os.getpid(), flush=True); time.sleep(30); print("NATURAL_DONE", flush=True)'
'''


def read_line(stream, pending, timeout):
    deadline = time.monotonic() + timeout
    while True:
        newline = pending.find(b"\n")
        if newline >= 0:
            line = bytes(pending[:newline]).decode("ascii", "strict")
            del pending[: newline + 1]
            return line
        remaining = deadline - time.monotonic()
        require(remaining > 0, "timed out waiting for harness output")
        ready, _, _ = select.select([stream], [], [], remaining)
        require(ready, "timed out waiting for harness output")
        chunk = os.read(stream, 4096)
        require(chunk, "harness output closed early")
        pending.extend(chunk)


def read_until_line(stream, pending, expected, timeout):
    deadline = time.monotonic() + timeout
    observed = []
    while True:
        remaining = deadline - time.monotonic()
        require(remaining > 0, "timed out before " + expected)
        try:
            line = read_line(stream, pending, remaining)
        except RuntimeError as error:
            tail = [line[-512:] for line in observed[-8:]]
            raise RuntimeError(
                f"{error}; waiting for {expected}; observed tail={tail!r}"
            ) from error
        observed.append(line)
        require(line != "NATURAL_DONE", "long command completed naturally")
        if line == expected:
            return observed


def test_read_until_line_reports_observed_tail():
    output_read, output_write = os.pipe()
    os.set_inheritable(output_read, False)
    os.set_inheritable(output_write, False)
    lines = ["oldest-marker", *[f"line-{index}" for index in range(8)], "X" * 600]
    try:
        os.write(output_write, ("\n".join(lines) + "\n").encode("ascii"))
    finally:
        os.close(output_write)
    try:
        read_until_line(output_read, bytearray(), "NEVER_EMITTED", 1)
    except RuntimeError as error:
        message = str(error)
    else:
        raise RuntimeError("closed harness output unexpectedly satisfied a missing marker")
    finally:
        os.close(output_read)
    require("harness output closed early" in message, "EOF cause was discarded")
    require("waiting for NEVER_EMITTED" in message, "expected marker was discarded")
    require("oldest-marker" not in message, "observed output tail is not line-bounded")
    require("X" * 512 in message, "latest observed output was discarded")
    require("X" * 513 not in message, "observed output line is not character-bounded")


def contender_lock(path, should_succeed):
    descriptor = os.open(path, os.O_RDWR | os.O_CLOEXEC)
    acquired = False
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except BlockingIOError:
            acquired = False
    finally:
        os.close(descriptor)
    require(acquired is should_succeed, "legacy flock lifetime changed")


def start_parent_death_harness(lock_path, script):
    output_read, output_write = os.pipe2(os.O_CLOEXEC)
    metadata_read, metadata_write = os.pipe2(os.O_CLOEXEC)
    supervisor = os.fork()
    if supervisor == 0:
        try:
            os.close(output_read)
            os.close(metadata_read)
            legacy = os.open(lock_path, os.O_RDWR | os.O_CLOEXEC)
            fcntl.flock(legacy, fcntl.LOCK_EX | fcntl.LOCK_NB)
            death_read, death_write = os.pipe2(os.O_CLOEXEC)
            leader = os.fork()
            if leader == 0:
                os.close(death_write)
                os.close(metadata_write)
                os.setsid()
                identity = API["process_identity"](os.getpid())
                require(identity is not None, "harness leader identity is missing")
                watchdog = os.fork()
                if watchdog == 0:
                    API["run_death_watchdog"](
                        os.getppid(),
                        os.getpgrp(),
                        identity[1],
                        death_read,
                    )
                os.close(death_read)
                os.dup2(legacy, 10, inheritable=True)
                os.dup2(output_write, 1, inheritable=True)
                os.dup2(output_write, 2, inheritable=True)
                if legacy != 10:
                    os.close(legacy)
                if output_write not in (1, 2, 10):
                    os.close(output_write)
                os.execve(
                    "/bin/bash",
                    ["/bin/bash", "-p", "-c", script],
                    {"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
                )
            os.close(death_read)
            os.close(output_write)
            os.write(metadata_write, struct.pack("!Q", leader))
            os.close(metadata_write)
            _, status = os.waitpid(leader, 0)
            os.close(death_write)
            os.close(legacy)
            if os.WIFEXITED(status):
                os._exit(os.WEXITSTATUS(status))
            os._exit(128 + os.WTERMSIG(status))
        except BaseException:
            os._exit(1)

    os.close(output_write)
    os.close(metadata_write)
    leader = struct.unpack("!Q", read_exact(metadata_read, 8))[0]
    os.close(metadata_read)
    return supervisor, leader, output_read


def test_parent_death_cleanup_and_lock():
    with tempfile.TemporaryDirectory(prefix="xjie-launcher-linux-") as temporary:
        root = Path(temporary)
        os.chmod(root, 0o700)
        lock_path = root / "legacy.lock"
        lock_path.touch(mode=0o600)
        supervisor, leader, output_read = start_parent_death_harness(
            lock_path,
            HARNESS_SCRIPT,
        )
        pending = bytearray()
        require(read_line(output_read, pending, 5) == "READY", "harness did not start")
        command_line = read_line(output_read, pending, 5)
        require(command_line.startswith("COMMAND "), "long command did not start")
        command_pid = int(command_line.split()[1])
        time.sleep(0.25)
        require(API["process_identity"](command_pid) is not None, "long command exited early")
        contender_lock(lock_path, False)

        lease_directory = os.open(
            root,
            os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
        )
        leader_identity = API["process_identity"](leader)
        require(leader_identity is not None, "harness leader vanished before lease")
        API["write_lease"](lease_directory, leader, leader_identity[1])
        try:
            API["reject_live_lease"](lease_directory)
        except SystemExit:
            pass
        else:
            raise RuntimeError("live deployment lease was accepted")

        os.kill(supervisor, signal.SIGKILL)
        os.waitpid(supervisor, 0)
        cleanup_started_at = time.monotonic()
        read_until_line(output_read, pending, "CLEANUP_STARTED", 1.5)
        require(
            time.monotonic() - cleanup_started_at <= 1.5,
            "parent-death cleanup exceeded its bound",
        )
        deadline = time.monotonic() + 1
        while API["process_identity"](command_pid) is not None and time.monotonic() < deadline:
            time.sleep(0.05)
        require(API["process_identity"](command_pid) is None, "long command survived parent death")
        require(b"NATURAL_DONE" not in pending, "long command completed naturally")
        contender_lock(lock_path, False)
        try:
            API["reject_live_lease"](lease_directory)
        except SystemExit:
            pass
        else:
            raise RuntimeError("lease cleared while cleanup still held fd10")

        read_until_line(output_read, pending, "CLEANUP_FINISHED", 5)
        deadline = time.monotonic() + 5
        while API["process_group_exists"](
            leader,
            ignored_zombie=(leader, leader_identity[1]),
        ) and time.monotonic() < deadline:
            time.sleep(0.05)
        require(
            not API["process_group_exists"](
                leader,
                ignored_zombie=(leader, leader_identity[1]),
            ),
            "deployment group survived cleanup",
        )
        contender_lock(lock_path, True)
        reap_deadline = time.monotonic() + 5
        while API["process_identity"](leader) is not None:
            try:
                os.waitpid(-1, os.WNOHANG)
            except ChildProcessError:
                pass
            require(time.monotonic() < reap_deadline, "adopted deploy leader was not reaped")
            time.sleep(0.05)
        API["reject_live_lease"](lease_directory)
        require(
            not (root / API["LEASE_FILE_NAME"]).exists(),
            "stale lease was not removed after the group exited",
        )
        os.close(lease_directory)
        os.close(output_read)


def docker_cleanup_harness(
    *,
    runtime_dir,
    probe_path,
    container_name,
    container_id,
    image_id,
    expected_sha,
    deployment_run_id,
):
    cleanup_functions = production_cleanup_functions()
    values = {
        "runtime_dir": runtime_dir,
        "probe_path": probe_path,
        "container_name": container_name,
        "container_id": container_id,
        "image_id": image_id,
        "expected_sha": expected_sha,
        "deployment_run_id": deployment_run_id,
        "deploy_guard": str(DEPLOY_GUARD),
    }
    quoted = {name: shlex.quote(str(value)) for name, value in values.items()}
    return rf'''set -euo pipefail
umask 077
readonly PATH="/usr/sbin:/usr/bin:/sbin:/bin"
readonly LC_ALL="C"
export PATH LC_ALL
runtime_dir={quoted["runtime_dir"]}
probe_path={quoted["probe_path"]}
deploy_guard={quoted["deploy_guard"]}
EXPECTED_SHA={quoted["expected_sha"]}
deployment_run_id={quoted["deployment_run_id"]}
trusted_bundle_sha256={shlex.quote("a" * 64)}
CUTOVER_JOURNAL="${{runtime_dir}}/absent-cutover-journal.json"
deployment_committed=0
old_container_stopped=0
ephemeral_container={quoted["container_name"]}
ephemeral_container_id={quoted["container_id"]}
ephemeral_image_id={quoted["image_id"]}
ephemeral_role="schema-old"
reference_server=""
reference_server_id=""
reference_server_image_id=""
reference_server_role=""
candidate_container=""
candidate_container_id=""
image_id={quoted["image_id"]}
container_name="xjie-api"
backup_container=""
restore_volume_name=""
restore_volume_image_id=""
restore_volume_owned=0
supervised_service_names=()
supervised_service_ids=()
supervised_service_roles=()

docker() {{
  if [[ "$#" -ge 2 && "$1" == "container" && "$2" == "rm" ]]; then
    if [[ "$#" -ne 5 || "$3" != "--force" || "$4" != "--volumes" \
      || "$5" != "$ephemeral_container_id" ]]; then
      printf 'NON_EXACT_CONTAINER_REMOVE\n' >&2
      return 97
    fi
    printf 'CLEANUP_STARTED\n' >&2
    /usr/bin/sleep 2
    /usr/bin/docker "$@"
    local status=$?
    if [[ "$status" -eq 0 ]]; then
      printf 'CONTAINER_REMOVED\n' >&2
      /usr/bin/sleep 3
    fi
    return "$status"
  fi
  /usr/bin/docker "$@"
}}

rm() {{
  local marks_cleanup_end=0
  local status
  if [[ "$#" -eq 3 && "$1" == "-rf" && "$2" == "--" \
    && "$3" == "$runtime_dir" ]]; then
    marks_cleanup_end=1
  fi
  /usr/bin/rm "$@"
  status=$?
  if [[ "$status" -eq 0 && "$marks_cleanup_end" -eq 1 ]]; then
    printf 'CLEANUP_FINISHED\n'
  fi
  return "$status"
}}

{cleanup_functions}

terminate_deploy_process_group() {{
  local signal_name=$1
  local exit_status=$2
  trap '' "$signal_name"
  kill -s "$signal_name" -- "-$$" 2>/dev/null || true
  exit "$exit_status"
}}
trap cleanup EXIT
trap 'terminate_deploy_process_group HUP 129' HUP
trap 'terminate_deploy_process_group INT 130' INT
trap 'terminate_deploy_process_group QUIT 131' QUIT
trap 'terminate_deploy_process_group TERM 143' TERM
printf 'READY\n'
docker container start --attach --interactive "$ephemeral_container_id" \
  <"$probe_path"
printf 'NATURAL_DONE\n'
'''


def test_docker_cleanup_harness_nounset_defaults():
    with tempfile.TemporaryDirectory(prefix="xjie-cleanup-nounset-") as temporary:
        absent_runtime = Path(temporary) / "absent-runtime"
        harness = docker_cleanup_harness(
            runtime_dir=absent_runtime,
            probe_path=absent_runtime / "unused-probe.py",
            container_name="xjie-cleanup-nounset",
            container_id="a" * 64,
            image_id="sha256:" + "b" * 64,
            expected_sha="c" * 40,
            deployment_run_id="d" * 32,
        )
        ready_marker = "printf 'READY\\n'\n"
        require(
            harness.count(ready_marker) == 1,
            "Docker cleanup harness READY boundary changed",
        )
        prelude = harness[: harness.index(ready_marker)]
        probe = prelude + r'''
ephemeral_container=""
declare -p reference_server_role restore_volume_name \
  restore_volume_image_id restore_volume_owned \
  supervised_service_names supervised_service_ids \
  supervised_service_roles >/dev/null
[[ -z "$reference_server_role" \
  && -z "$restore_volume_name" \
  && -z "$restore_volume_image_id" \
  && "$restore_volume_owned" -eq 0 \
  && "${#supervised_service_names[@]}" -eq 0 \
  && "${#supervised_service_ids[@]}" -eq 0 \
  && "${#supervised_service_roles[@]}" -eq 0 ]]
printf 'NOUNSET_STATE_OK\n'
exit 143
'''
        result = subprocess.run(
            ["/bin/bash", "-p", "-c", probe],
            check=False,
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=10,
        )
        try:
            output = result.stdout.decode("ascii", "strict")
        except UnicodeDecodeError as error:
            raise RuntimeError("cleanup nounset probe returned non-ASCII output") from error
        require(
            result.returncode == 143,
            f"cleanup nounset probe exited {result.returncode}: {output[-2048:]!r}",
        )
        require(
            output == "NOUNSET_STATE_OK\n",
            f"cleanup nounset probe emitted unexpected output: {output[-2048:]!r}",
        )


def wait_for_container_host_pid(container_id, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        identity = inspect_container_identity(container_id)
        if identity is not None and identity[5] == "true":
            try:
                host_pid = int(identity[6])
            except ValueError as error:
                raise RuntimeError("container host PID is invalid") from error
            if host_pid > 1:
                return host_pid
        time.sleep(0.05)
    raise RuntimeError("long-running container did not expose its host PID")


def reap_adopted_process(leader, leader_identity, timeout=10):
    deadline = time.monotonic() + timeout
    while API["process_group_exists"](
        leader,
        ignored_zombie=(leader, leader_identity[1]),
    ):
        require(time.monotonic() < deadline, "Docker cleanup process group survived")
        time.sleep(0.05)
    while API["process_identity"](leader) is not None:
        try:
            os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            pass
        require(time.monotonic() < deadline, "Docker cleanup leader was not reaped")
        time.sleep(0.05)


def test_real_docker_parent_death_cleanup(image_reference):
    require(DOCKER.is_file() and os.access(DOCKER, os.X_OK), "/usr/bin/docker is required")
    image_id = resolve_immutable_image(image_reference)
    expected_sha = secrets.token_hex(20)
    deployment_run_id = secrets.token_hex(16)
    container_name = GUARD_API["deployment_name"](
        deployment_run_id,
        "schema-old",
    )
    container_id = None
    supervisor = None
    leader = None
    leader_identity = None
    output_read = None
    pending = bytearray()

    with tempfile.TemporaryDirectory(prefix="xjie-launcher-docker-") as temporary:
        root = Path(temporary)
        os.chmod(root, 0o700)
        runtime_dir = root / "runtime"
        runtime_dir.mkdir(mode=0o700)
        probe_path = runtime_dir / "long-running-one-shot.py"
        probe_descriptor = os.open(
            probe_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
            0o600,
        )
        try:
            probe_payload = (
                b'import signal, time\n'
                b'signal.signal(signal.SIGTERM, signal.SIG_IGN)\n'
                b'signal.signal(signal.SIGHUP, signal.SIG_IGN)\n'
                b'print("CONTAINER_STARTED", flush=True)\n'
                b'time.sleep(600)\n'
                b'print("NATURAL_DONE", flush=True)\n'
            )
            require(
                os.write(probe_descriptor, probe_payload) == len(probe_payload),
                "cannot write Docker one-shot probe",
            )
            os.fsync(probe_descriptor)
        finally:
            os.close(probe_descriptor)
        lock_path = root / "legacy.lock"
        lock_path.touch(mode=0o600)

        try:
            lifecycle_arguments = GUARD_API["deployment_label_arguments"](
                container_name,
                image_id,
                expected_sha,
                deployment_run_id,
                "schema-old",
            )
            require(
                len(lifecycle_arguments) == 18,
                "Docker self-test lifecycle label shape changed",
            )
            creation = docker_command(
                [
                    "container",
                    "create",
                    "--platform",
                    "linux/amd64",
                    "--name",
                    container_name,
                    "--interactive",
                    "--network",
                    "none",
                    "--read-only",
                    "--cap-drop",
                    "ALL",
                    "--security-opt",
                    "no-new-privileges",
                    "--tmpfs",
                    "/tmp:rw,noexec,nosuid,nodev,size=16m",
                    *lifecycle_arguments,
                    "--entrypoint",
                    "python",
                    image_id,
                    "-I",
                    "-",
                ],
                timeout=30,
            )
            require(creation.returncode == 0, "cannot create Docker one-shot container")
            try:
                container_id = creation.stdout.decode("ascii", "strict").strip()
            except UnicodeDecodeError as error:
                raise RuntimeError("Docker create returned a non-ASCII ID") from error
            require(
                CONTAINER_ID_PATTERN.fullmatch(container_id) is not None,
                "Docker create did not return an immutable full container ID",
            )
            created = inspect_container_identity(container_id)
            require(created is not None, "created Docker one-shot container vanished")
            require(
                created
                == [
                    container_id,
                    image_id,
                    image_id,
                    "none",
                    "false",
                    "false",
                    "0",
                ],
                "Docker one-shot is not exact-image/network-none/non-auto-remove",
            )

            harness = docker_cleanup_harness(
                runtime_dir=runtime_dir,
                probe_path=probe_path,
                container_name=container_name,
                container_id=container_id,
                image_id=image_id,
                expected_sha=expected_sha,
                deployment_run_id=deployment_run_id,
            )
            supervisor, leader, output_read = start_parent_death_harness(
                lock_path,
                harness,
            )
            leader_identity = API["process_identity"](leader)
            require(leader_identity is not None, "Docker harness leader vanished")
            require(read_line(output_read, pending, 5) == "READY", "Docker harness did not start")
            read_until_line(output_read, pending, "CONTAINER_STARTED", 10)
            host_pid = wait_for_container_host_pid(container_id)
            host_identity = API["process_identity"](host_pid)
            require(host_identity is not None, "container host PID exited before supervisor death")
            contender_lock(lock_path, False)

            os.kill(supervisor, signal.SIGKILL)
            os.waitpid(supervisor, 0)
            supervisor = None
            read_until_line(output_read, pending, "CLEANUP_STARTED", 15)
            contender_lock(lock_path, False)
            still_running = inspect_container_identity(container_id)
            require(
                still_running is not None
                and still_running[5] == "true"
                and int(still_running[6]) == host_pid,
                "container did not remain live until exact-ID EXIT cleanup",
            )

            read_until_line(output_read, pending, "CONTAINER_REMOVED", 15)
            contender_lock(lock_path, False)
            require(
                inspect_container_identity(container_id) is None,
                "exact-ID cleanup left the Docker container present",
            )
            deadline = time.monotonic() + 5
            while API["process_identity"](host_pid) is not None and time.monotonic() < deadline:
                time.sleep(0.05)
            require(
                API["process_identity"](host_pid) is None,
                "container host PID survived forced exact-ID removal",
            )
            require(
                b"NATURAL_DONE" not in pending,
                "long-running Docker command completed naturally",
            )
            read_until_line(output_read, pending, "CLEANUP_FINISHED", 5)
            reap_adopted_process(leader, leader_identity)
            contender_lock(lock_path, True)
            require(
                inspect_container_identity(container_name) is None,
                "unique Docker self-test name survived cleanup",
            )
            container_id = None
            os.close(output_read)
            output_read = None
        finally:
            if supervisor is not None:
                try:
                    os.kill(supervisor, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                try:
                    os.waitpid(supervisor, 0)
                except ChildProcessError:
                    pass
            if (
                leader is not None
                and leader_identity is not None
                and API["process_identity"](leader) == leader_identity
            ):
                try:
                    os.killpg(leader, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            if output_read is not None:
                os.close(output_read)
            named_identity = inspect_container_identity(container_name)
            named_id = named_identity[0] if named_identity is not None else None
            if container_id is not None and named_id not in (None, container_id):
                raise RuntimeError("unique self-test name was rebound to another container")
            remove_exact_container_if_present(container_id or named_id)


def test_normal_completion_marker():
    read_descriptor, write_descriptor = os.pipe2(os.O_CLOEXEC)
    result_read, result_write = os.pipe2(os.O_CLOEXEC)
    process_group = os.fork()
    if process_group == 0:
        try:
            os.close(write_descriptor)
            os.close(result_read)
            os.setsid()
            identity = API["process_identity"](os.getpid())
            watcher = os.fork()
            if watcher == 0:
                API["run_death_watchdog"](
                    os.getppid(),
                    os.getpgrp(),
                    identity[1],
                    read_descriptor,
                )
            os.close(read_descriptor)
            os.write(result_write, struct.pack("!Q", watcher))
            wait_child(watcher, "normal-marker watchdog")
            os.write(result_write, b"M")
            time.sleep(2)
            os.close(result_write)
            os._exit(0)
        except BaseException:
            os._exit(1)
    os.close(read_descriptor)
    os.close(result_write)
    watcher = struct.unpack("!Q", read_exact(result_read, 8))[0]
    os.write(write_descriptor, b"N")
    os.close(write_descriptor)
    require(read_exact(result_read, 1, timeout=1) == b"M", "normal marker did not stop watchdog")
    os.close(result_read)
    require(API["process_identity"](process_group) is not None, "normal marker killed deploy group")
    os.killpg(process_group, signal.SIGTERM)
    os.waitpid(process_group, 0)


def main():
    parser = argparse.ArgumentParser(
        description="Validate production launcher Linux and real Docker cleanup semantics."
    )
    parser.add_argument(
        "--docker-image",
        required=True,
        help="locally available production image tag or immutable image ID",
    )
    arguments = parser.parse_args()
    require(sys.platform.startswith("linux"), "Linux is required")
    require(os.geteuid() == 0 and os.getegid() == 0, "root is required")
    require(stat.S_ISDIR(os.stat("/proc").st_mode), "/proc is required")
    enable_child_subreaper()
    test_read_until_line_reports_observed_tail()
    test_docker_cleanup_harness_nounset_defaults()
    test_descriptor_scrub()
    test_credential_pipe_identity()
    test_broker_kernel_credentials()
    test_schema_migration_approval_binding()
    test_normal_completion_marker()
    test_parent_death_cleanup_and_lock()
    test_real_docker_parent_death_cleanup(arguments.docker_image)
    print("production launcher Linux runtime self-test: PASS")


if __name__ == "__main__":
    main()
