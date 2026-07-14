#!/usr/bin/python3 -I
"""Root-only, fail-closed supervisor for the production deploy entrypoint."""

import os
import sys


_INITIAL_TOKEN_ENVIRONMENT = tuple(
    name for name in ("GITHUB_TOKEN", "GH_TOKEN") if name in os.environ
)
os.environ.clear()

import ctypes
import fcntl
import hashlib
import json
import pwd
import re
import resource
import select
import signal
import socket
import stat
import struct
import time
import types
from pathlib import Path


TRUSTED_LAUNCHER = "/usr/local/sbin/xjie-production-launch"
TRUSTED_ENTRYPOINT = "/usr/local/sbin/xjie-production-deploy"
TRUSTED_INSTALLER = "/usr/local/sbin/xjie-production-install"
TRUSTED_BUNDLE_DIR = "/usr/local/libexec/xjie-production-deploy"
TRUSTED_SPEC = TRUSTED_BUNDLE_DIR + "/production_container.json"
TRUSTED_DEPLOY_GUARD = TRUSTED_BUNDLE_DIR + "/production_deploy_guard.py"
TRUSTED_RELEASE_GATE = TRUSTED_BUNDLE_DIR + "/run_regression_gate.py"
TRUSTED_TEST_INVENTORY = TRUSTED_BUNDLE_DIR + "/expected_python_tests.json"
LAUNCH_AUTHORITY = "/etc/xjie-production-deploy/launch-authority"
INSTALL_STATE_DIR = "/var/lib/xjie-production-deploy"
INSTALL_JOURNAL = INSTALL_STATE_DIR + "/bundle-install.json"
DEPLOY_PRINCIPAL = "mayl"
BROKER_FD = 8
LEGACY_LOCK_FD = 10
INSTALLER_ROOT_LOCK_FD = 9
INSTALLER_LEGACY_LOCK_FD = 11
INSTALLER_AUTHORITY_FD = 12
INSTALLER_AUTHORITY_MARKER = b"XJIE_BUNDLE_INSTALLER_DOCTOR_V1\0"
LOCK_PARENT = "/run/lock"
LOCK_DIRECTORY_NAME = "xjie-production-deploy"
LOCK_FILE_NAME = "deployment.lock"
LEASE_FILE_NAME = "deployment.lease.json"
LEGACY_LOCK_DIRECTORY = "/home/mayl/.locks"
LEGACY_LOCK_FILE_NAME = "xjie-production-deploy.lock"
MAX_TOKEN_BYTES = 4096
MAX_LEASE_BYTES = 4096
MAX_BROKER_REQUEST_BYTES = 256
DEATH_WATCHDOG_GRACE_SECONDS = 120
PR_SET_PDEATHSIG = 1
PR_SET_DUMPABLE = 4
EXPECTED_SHA_PATTERN = re.compile(r"[0-9a-f]{40}\Z")
ANONYMOUS_PIPE_PATTERN = re.compile(r"pipe:\[([0-9]+)\]\Z")


def fail(message):
    raise SystemExit("PRODUCTION DEPLOY LAUNCHER: FAILED: " + message)


def root_directory(path, *, allow_root_group_write=False):
    metadata = os.lstat(path)
    forbidden_write = 0o002 if allow_root_group_write else 0o022
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or metadata.st_uid != 0
        or metadata.st_gid != 0
        or stat.S_IMODE(metadata.st_mode) & forbidden_write
    ):
        fail("root-controlled directory identity is invalid: " + path)


def stable_root_file(path, expected_mode, *, read_bytes=False):
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != 0
            or before.st_gid != 0
            or stat.S_IMODE(before.st_mode) != expected_mode
            or before.st_nlink != 1
        ):
            fail("root-controlled file identity is invalid: " + path)
        chunks = []
        if read_bytes:
            while True:
                chunk = os.read(descriptor, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
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
        if identity(before) != identity(after):
            fail("root-controlled file changed while it was read: " + path)
        payload = b"".join(chunks)
        if read_bytes and len(payload) != before.st_size:
            fail("root-controlled file size changed while it was read: " + path)
        return descriptor, payload
    except BaseException:
        os.close(descriptor)
        raise


def require_anonymous_pipe(descriptor, purpose):
    metadata = os.fstat(descriptor)
    if not stat.S_ISFIFO(metadata.st_mode):
        fail(purpose + " must be an anonymous pipe, not a file or TTY")
    try:
        kernel_identity = os.readlink(f"/proc/self/fd/{descriptor}")
    except OSError:
        fail(purpose + " requires Linux /proc anonymous-pipe identity")
    match = ANONYMOUS_PIPE_PATTERN.fullmatch(kernel_identity)
    if match is None or int(match.group(1)) != metadata.st_ino:
        fail(purpose + " must be an anonymous pipe, not a named FIFO")
    return metadata


def read_token_from_standard_input(arguments, descriptor=0):
    if _INITIAL_TOKEN_ENVIRONMENT:
        fail("GitHub tokens must not be inherited through the environment")
    if arguments == ["--doctor"]:
        return None
    require_anonymous_pipe(descriptor, "GitHub token stdin")
    payload = bytearray()
    while True:
        chunk = os.read(descriptor, MAX_TOKEN_BYTES + 2 - len(payload))
        if not chunk:
            break
        payload.extend(chunk)
        if len(payload) > MAX_TOKEN_BYTES + 1:
            fail("standard-input GitHub token is too large")
    if len(payload) < 2 or payload[-1:] != b"\0" or b"\0" in payload[:-1]:
        fail("deploy/ingest requires one NUL-terminated GitHub token on stdin")
    token = payload[:-1]
    if not token or b"\n" in token or b"\r" in token:
        fail("standard-input GitHub token is malformed")
    try:
        token.decode("ascii")
    except UnicodeDecodeError:
        fail("standard-input GitHub token must be ASCII")
    null_descriptor = os.open("/dev/null", os.O_RDONLY | os.O_CLOEXEC)
    try:
        os.dup2(null_descriptor, 0, inheritable=True)
    finally:
        if null_descriptor != 0:
            os.close(null_descriptor)
    return token


def descriptor_is_open(descriptor):
    try:
        os.fstat(descriptor)
        return True
    except OSError:
        return False


def consume_installer_doctor_authority(arguments):
    descriptors = (
        INSTALLER_ROOT_LOCK_FD,
        INSTALLER_LEGACY_LOCK_FD,
        INSTALLER_AUTHORITY_FD,
    )
    present = tuple(descriptor_is_open(value) for value in descriptors)
    if not any(present):
        return False
    if arguments != ["--doctor"] or not all(present):
        fail("partial or non-doctor bundle-installer descriptor protocol")
    require_anonymous_pipe(
        INSTALLER_AUTHORITY_FD,
        "bundle-installer doctor authority",
    )
    payload = bytearray()
    while True:
        chunk = os.read(
            INSTALLER_AUTHORITY_FD,
            len(INSTALLER_AUTHORITY_MARKER) + 1 - len(payload),
        )
        if not chunk:
            break
        payload.extend(chunk)
        if len(payload) > len(INSTALLER_AUTHORITY_MARKER):
            fail("bundle-installer doctor authority framing is invalid")
    os.close(INSTALLER_AUTHORITY_FD)
    if bytes(payload) != INSTALLER_AUTHORITY_MARKER:
        fail("bundle-installer doctor authority marker is invalid")
    return True


def close_unapproved_descriptors(allowed):
    try:
        names = os.listdir("/proc/self/fd")
    except OSError:
        fail("Linux /proc is required to close inherited descriptors")
    for name in names:
        if not name.isdigit():
            continue
        descriptor = int(name)
        if descriptor >= 3 and descriptor not in allowed:
            try:
                os.close(descriptor)
            except OSError:
                pass


def validate_root_regular_descriptor(descriptor, expected_mode, label):
    metadata = os.fstat(descriptor)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != 0
        or metadata.st_gid != 0
        or stat.S_IMODE(metadata.st_mode) != expected_mode
        or metadata.st_nlink != 1
    ):
        fail(label + " identity is invalid")
    return metadata


def open_lock_directory():
    root_directory("/run")
    root_directory(LOCK_PARENT, allow_root_group_write=True)
    parent = os.open(
        LOCK_PARENT, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
    )
    try:
        try:
            os.mkdir(LOCK_DIRECTORY_NAME, 0o700, dir_fd=parent)
        except FileExistsError:
            pass
        descriptor = os.open(
            LOCK_DIRECTORY_NAME,
            os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
            dir_fd=parent,
        )
    finally:
        os.close(parent)
    metadata = os.fstat(descriptor)
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != 0
        or metadata.st_gid != 0
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        os.close(descriptor)
        fail("root deployment lock directory identity is invalid")
    return descriptor


def open_deployment_lock(directory_descriptor):
    descriptor = os.open(
        LOCK_FILE_NAME,
        os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW,
        0o600,
        dir_fd=directory_descriptor,
    )
    metadata = validate_root_regular_descriptor(
        descriptor, 0o600, "root deployment lock file"
    )
    path_metadata = os.stat(
        LOCK_FILE_NAME, dir_fd=directory_descriptor, follow_symlinks=False
    )
    if (metadata.st_dev, metadata.st_ino) != (
        path_metadata.st_dev,
        path_metadata.st_ino,
    ):
        os.close(descriptor)
        fail("root deployment lock path changed while it was opened")
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(descriptor)
        fail("another production deployment supervisor owns the lock")
    return descriptor


def reject_active_install_journal(path=INSTALL_JOURNAL):
    try:
        state_metadata = os.lstat(INSTALL_STATE_DIR)
    except FileNotFoundError:
        return
    if (
        not stat.S_ISDIR(state_metadata.st_mode)
        or stat.S_ISLNK(state_metadata.st_mode)
        or state_metadata.st_uid != 0
        or state_metadata.st_gid != 0
        or stat.S_IMODE(state_metadata.st_mode) != 0o700
    ):
        fail("bundle installer state directory identity is invalid")
    try:
        os.lstat(path)
    except FileNotFoundError:
        return
    fail("an active bundle install journal blocks production launch")


def validate_inherited_root_lock(directory_descriptor, descriptor):
    metadata = validate_root_regular_descriptor(
        descriptor, 0o600, "installer-inherited root deployment lock"
    )
    path_metadata = os.stat(
        LOCK_FILE_NAME,
        dir_fd=directory_descriptor,
        follow_symlinks=False,
    )
    if (metadata.st_dev, metadata.st_ino) != (
        path_metadata.st_dev,
        path_metadata.st_ino,
    ):
        fail("installer-inherited root lock does not match the lock path")
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        fail("installer-inherited root lock is not owned by this process")
    return descriptor


def open_legacy_deployment_lock(principal):
    home_descriptor = os.open(
        principal.pw_dir,
        os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
    )
    try:
        home_metadata = os.fstat(home_descriptor)
        if (
            not stat.S_ISDIR(home_metadata.st_mode)
            or home_metadata.st_uid != principal.pw_uid
            or stat.S_IMODE(home_metadata.st_mode) & 0o022
        ):
            fail("legacy deployment home identity is invalid")
        try:
            os.mkdir(".locks", 0o700, dir_fd=home_descriptor)
            os.chown(
                ".locks",
                principal.pw_uid,
                principal.pw_gid,
                dir_fd=home_descriptor,
                follow_symlinks=False,
            )
        except FileExistsError:
            pass
        directory_descriptor = os.open(
            ".locks",
            os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
            dir_fd=home_descriptor,
        )
    finally:
        os.close(home_descriptor)
    directory_metadata = os.fstat(directory_descriptor)
    if (
        not stat.S_ISDIR(directory_metadata.st_mode)
        or directory_metadata.st_uid != principal.pw_uid
        or directory_metadata.st_gid != principal.pw_gid
        or stat.S_IMODE(directory_metadata.st_mode) != 0o700
    ):
        os.close(directory_descriptor)
        fail("legacy deployment lock directory identity is invalid")
    try:
        try:
            descriptor = os.open(
                LEGACY_LOCK_FILE_NAME,
                os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW,
                dir_fd=directory_descriptor,
            )
        except FileNotFoundError:
            descriptor = os.open(
                LEGACY_LOCK_FILE_NAME,
                os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
                0o600,
                dir_fd=directory_descriptor,
            )
            os.fchown(descriptor, principal.pw_uid, principal.pw_gid)
        metadata = os.fstat(descriptor)
        path_metadata = os.stat(
            LEGACY_LOCK_FILE_NAME,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
        if (
            (metadata.st_dev, metadata.st_ino)
            != (path_metadata.st_dev, path_metadata.st_ino)
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != principal.pw_uid
            or metadata.st_gid != principal.pw_gid
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_nlink != 1
        ):
            fail("legacy deployment lock file identity is invalid")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            fail("a legacy production deployment still owns its compatibility lock")
        return descriptor
    except BaseException:
        try:
            os.close(descriptor)
        except (NameError, OSError):
            pass
        raise
    finally:
        os.close(directory_descriptor)


def validate_inherited_legacy_lock(principal, descriptor):
    home_descriptor = os.open(
        principal.pw_dir,
        os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
    )
    try:
        home_metadata = os.fstat(home_descriptor)
        if (
            not stat.S_ISDIR(home_metadata.st_mode)
            or home_metadata.st_uid != principal.pw_uid
            or stat.S_IMODE(home_metadata.st_mode) & 0o022
        ):
            fail("installer-inherited legacy lock home identity is invalid")
        directory_descriptor = os.open(
            ".locks",
            os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
            dir_fd=home_descriptor,
        )
    finally:
        os.close(home_descriptor)
    try:
        directory_metadata = os.fstat(directory_descriptor)
        if (
            not stat.S_ISDIR(directory_metadata.st_mode)
            or directory_metadata.st_uid != principal.pw_uid
            or directory_metadata.st_gid != principal.pw_gid
            or stat.S_IMODE(directory_metadata.st_mode) != 0o700
        ):
            fail("installer-inherited legacy lock directory identity is invalid")
        metadata = os.fstat(descriptor)
        path_metadata = os.stat(
            LEGACY_LOCK_FILE_NAME,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
        if (
            (metadata.st_dev, metadata.st_ino)
            != (path_metadata.st_dev, path_metadata.st_ino)
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != principal.pw_uid
            or metadata.st_gid != principal.pw_gid
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_nlink != 1
        ):
            fail("installer-inherited legacy lock identity is invalid")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            fail("installer-inherited legacy lock is not owned by this process")
        return descriptor
    finally:
        os.close(directory_descriptor)


def boot_id():
    descriptor = os.open(
        "/proc/sys/kernel/random/boot_id",
        os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
    )
    try:
        payload = os.read(descriptor, 128)
        if os.read(descriptor, 1):
            fail("kernel boot identity is unexpectedly large")
    finally:
        os.close(descriptor)
    try:
        value = payload.decode("ascii").strip()
    except UnicodeDecodeError:
        fail("kernel boot identity is malformed")
    if len(value) != 36:
        fail("kernel boot identity is malformed")
    return value


def process_record(pid):
    try:
        with open(f"/proc/{pid}/stat", "rb", buffering=0) as handle:
            payload = handle.read(4096)
    except (FileNotFoundError, ProcessLookupError):
        return None
    if len(payload) == 4096 or b") " not in payload:
        fail("cannot validate deployment process identity")
    fields = payload.rsplit(b") ", 1)[1].split()
    if len(fields) < 20:
        fail("deployment process identity is malformed")
    try:
        process_group = int(fields[2])
        start_time = int(fields[19])
    except ValueError:
        fail("deployment process identity is malformed")
    return process_group, start_time, fields[0]


def process_identity(pid):
    record = process_record(pid)
    if record is None:
        return None
    return record[:2]


def process_parent_and_group(pid):
    try:
        with open(f"/proc/{pid}/stat", "rb", buffering=0) as handle:
            payload = handle.read(4096)
    except (FileNotFoundError, ProcessLookupError):
        return None
    if len(payload) == 4096 or b") " not in payload:
        fail("cannot validate broker sender process identity")
    fields = payload.rsplit(b") ", 1)[1].split()
    if len(fields) < 3:
        fail("broker sender process identity is malformed")
    try:
        return int(fields[1]), int(fields[2])
    except ValueError:
        fail("broker sender process identity is malformed")


def process_group_exists(process_group, ignored_zombie=None):
    try:
        names = os.listdir("/proc")
    except OSError:
        fail("Linux /proc is required to validate the deployment lease")
    for name in names:
        if not name.isdigit():
            continue
        pid = int(name)
        record = process_record(pid)
        if record is None or record[0] != process_group:
            continue
        if (
            ignored_zombie is not None
            and (pid, record[1]) == ignored_zombie
            and record[2] == b"Z"
        ):
            continue
        if record is not None:
            return True
    return False


def exact_process_exists(pid, start_time):
    identity = process_identity(pid)
    return identity is not None and identity[1] == start_time


def wait_for_exact_process_exit(pid, start_time, timeout_seconds):
    deadline = time.monotonic() + timeout_seconds
    while exact_process_exists(pid, start_time):
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)
    return True


def stable_lease(directory_descriptor):
    try:
        descriptor = os.open(
            LEASE_FILE_NAME,
            os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
            dir_fd=directory_descriptor,
        )
    except FileNotFoundError:
        return None, None
    try:
        before = validate_root_regular_descriptor(
            descriptor, 0o600, "root deployment lease"
        )
        payload = os.read(descriptor, MAX_LEASE_BYTES + 1)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if (
        len(payload) > MAX_LEASE_BYTES
        or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        or len(payload) != before.st_size
    ):
        fail("root deployment lease changed while it was read")
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError):
        fail("root deployment lease is malformed")
    if (
        type(value) is not dict
        or tuple(value) != ("schema_version", "boot_id", "pid", "start_time")
        or value["schema_version"] != 1
        or not isinstance(value["boot_id"], str)
        or type(value["pid"]) is not int
        or value["pid"] <= 1
        or type(value["start_time"]) is not int
        or value["start_time"] <= 0
    ):
        fail("root deployment lease has an invalid schema")
    return value, before


def remove_stale_lease(directory_descriptor, metadata):
    current = os.stat(
        LEASE_FILE_NAME, dir_fd=directory_descriptor, follow_symlinks=False
    )
    if (current.st_dev, current.st_ino) != (metadata.st_dev, metadata.st_ino):
        fail("root deployment lease changed before stale cleanup")
    os.unlink(LEASE_FILE_NAME, dir_fd=directory_descriptor)
    os.fsync(directory_descriptor)


def reject_live_lease(directory_descriptor):
    lease, metadata = stable_lease(directory_descriptor)
    if lease is None:
        return
    same_boot = lease["boot_id"] == boot_id()
    identity = process_identity(lease["pid"]) if same_boot else None
    leader_matches = identity == (lease["pid"], lease["start_time"])
    group_alive = same_boot and process_group_exists(lease["pid"])
    if leader_matches or group_alive:
        fail("an earlier production deployment process group is still alive")
    remove_stale_lease(directory_descriptor, metadata)


def write_lease(directory_descriptor, pid, start_time):
    value = {
        "schema_version": 1,
        "boot_id": boot_id(),
        "pid": pid,
        "start_time": start_time,
    }
    payload = (json.dumps(value, separators=(",", ":")) + "\n").encode("ascii")
    temporary = f".{LEASE_FILE_NAME}.{os.getpid()}"
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
        0o600,
        dir_fd=directory_descriptor,
    )
    try:
        if os.write(descriptor, payload) != len(payload):
            fail("cannot write the deployment lease")
        os.fsync(descriptor)
        validate_root_regular_descriptor(descriptor, 0o600, "new deployment lease")
    except BaseException:
        try:
            os.unlink(temporary, dir_fd=directory_descriptor)
        except FileNotFoundError:
            pass
        raise
    finally:
        os.close(descriptor)
    os.rename(
        temporary,
        LEASE_FILE_NAME,
        src_dir_fd=directory_descriptor,
        dst_dir_fd=directory_descriptor,
    )
    os.fsync(directory_descriptor)


def set_parent_death_signal(parent_pid):
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(PR_SET_PDEATHSIG, signal.SIGTERM, 0, 0, 0) != 0:
        fail("cannot bind child lifetime to the root supervisor")
    if os.getppid() != parent_pid:
        raise SystemExit(128 + signal.SIGTERM)


def disable_process_dumping():
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(PR_SET_DUMPABLE, 0, 0, 0, 0) != 0:
        fail("cannot disable production-launcher process dumping")


def reset_process_signals():
    reset_signals = [
        signal.SIGHUP,
        signal.SIGINT,
        signal.SIGQUIT,
        signal.SIGTERM,
        signal.SIGPIPE,
        signal.SIGCHLD,
        signal.SIGTSTP,
        signal.SIGCONT,
    ]
    for optional_name in ("SIGXFSZ", "SIGXFZ"):
        optional_signal = getattr(signal, optional_name, None)
        if optional_signal is not None:
            reset_signals.append(optional_signal)
    for signum in reset_signals:
        signal.signal(signum, signal.SIG_DFL)
    signal.pthread_sigmask(signal.SIG_SETMASK, [])


def run_death_watchdog(
    supervisor_pid,
    deployment_process_group,
    deployment_start_time,
    death_descriptor,
):
    """Terminate the full deploy group if the root supervisor disappears."""
    try:
        reset_process_signals()
        disable_process_dumping()
        os.setpgid(0, 0)
        close_unapproved_descriptors({death_descriptor})
        while True:
            try:
                marker = os.read(death_descriptor, 1)
                break
            except InterruptedError:
                continue
        os.close(death_descriptor)
        if marker == b"N":
            os._exit(0)
        if marker:
            raise RuntimeError("invalid deployment death-pipe marker")

        # The pipe's sole writer belongs to the root supervisor. EOF is a
        # kernel-authenticated parent-death notification, including SIGKILL
        # and OOM. The watchdog has its own process group so SIGSTOP/SIGTERM
        # sent to the deployment group cannot prevent this response.
        try:
            os.killpg(deployment_process_group, signal.SIGTERM)
            os.killpg(deployment_process_group, signal.SIGCONT)
        except ProcessLookupError:
            os._exit(0)

        deadline = time.monotonic() + DEATH_WATCHDOG_GRACE_SECONDS
        while process_group_exists(
            deployment_process_group,
            ignored_zombie=(deployment_process_group, deployment_start_time),
        ):
            if time.monotonic() >= deadline:
                try:
                    os.killpg(deployment_process_group, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                os._exit(0)
            time.sleep(0.1)
        os._exit(0)
    except BaseException:
        # A watchdog failure must never leave a known deployment group alive.
        try:
            os.killpg(deployment_process_group, signal.SIGKILL)
        except (NameError, ProcessLookupError):
            pass
        os._exit(1)


def drop_to_principal(principal, parent_pid):
    os.umask(0o077)
    os.chdir("/")
    os.initgroups(DEPLOY_PRINCIPAL, principal.pw_gid)
    os.setgid(principal.pw_gid)
    os.setuid(principal.pw_uid)
    if os.geteuid() != principal.pw_uid or os.getegid() != principal.pw_gid:
        fail("cannot drop to the deployment principal")
    # Linux clears PR_SET_PDEATHSIG on credential changes; bind it again.
    set_parent_death_signal(parent_pid)


def child_environment(launcher_payload):
    environment = {
        "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
        "LC_ALL": "C",
        "HOME": "/nonexistent",
        "XDG_CONFIG_HOME": "/nonexistent",
        "XJIE_DEPLOY_LAUNCHER_SHA256": hashlib.sha256(
            launcher_payload
        ).hexdigest(),
        "XJIE_DEPLOY_LOCK_SUPERVISED": "1",
        "XJIE_DEPLOY_BROKER_FD": str(BROKER_FD),
        "XJIE_DEPLOY_LEGACY_LOCK_FD": str(LEGACY_LOCK_FD),
    }
    return environment


def load_trusted_release_gate():
    descriptor, source = stable_root_file(
        TRUSTED_RELEASE_GATE, 0o444, read_bytes=True
    )
    os.close(descriptor)
    module_path = Path(TRUSTED_RELEASE_GATE)
    gate = types.ModuleType("xjie_production_release_gate")
    gate.__file__ = str(module_path)
    sys.modules[gate.__name__] = gate
    exec(compile(source, str(module_path), "exec"), gate.__dict__)
    return gate


def qualification_root(principal):
    return Path(f"/dev/shm/xjie-deploy-{principal.pw_uid}/runtime/qualification")


def broker_verify_official_candidate(gate, principal, token, expected_sha):
    if token is None or not EXPECTED_SHA_PATTERN.fullmatch(expected_sha):
        fail("broker official-candidate request is invalid")
    source_root = qualification_root(principal)
    gate.github_token = lambda: bytes(token).decode("ascii")
    gate.REPO_ROOT = source_root
    gate.REGISTRY_PATH = source_root / "quality" / "regression_contracts.json"
    gate.ensure_no_git_repository_redirects()
    gate.ensure_no_network_verification_redirects()
    registry = gate.load_json(gate.REGISTRY_PATH)
    gate.validate_release_registry_identity(registry)
    gate.ensure_official_remote_tip(expected_sha, registry)
    remote = gate.require_remote_quality_gate(expected_sha, registry)
    for field in ("workflow_run_id", "workflow_run_attempt", "check_run_id", "check_app_id"):
        if type(remote.get(field)) is not int or remote[field] <= 0:
            fail("remote quality-gate identity has an invalid integer field")
    if remote.get("head_sha") != expected_sha or remote.get("head_branch") != "main":
        fail("remote quality-gate is not bound to exact main HEAD")
    pull = gate.require_merged_pull_request(expected_sha, registry)
    protections = gate.require_all_branch_protections(
        registry,
        expected_app_id=remote["check_app_id"],
    )
    if list(protections) != ["main", "XAGE"]:
        fail("canonical branch protection roles are incomplete or reordered")
    return "official candidate verified: pr={0} run={1} check={2}".format(
        pull["number"], remote["workflow_run_id"], remote["check_run_id"]
    )


def broker_validate_backend_junit(gate, principal):
    junit = Path(
        f"/dev/shm/xjie-deploy-{principal.pw_uid}/runtime/backend-full.xml"
    )
    gate.EXPECTED_PYTHON_TESTS_PATH = Path(TRUSTED_TEST_INVENTORY)
    gate.BACKEND_JUNIT_PATHS = {"backend_full": junit}
    gate.BACKEND_JUNIT_EXPECTED_OWNER_UID = principal.pw_uid
    gate.BACKEND_JUNIT_REQUIRED_MODE = 0o600
    summary = gate.validate_backend_junit_output(
        "backend_full",
        junit,
        gate.MANDATORY_RELEASE_COMMAND_TEMPLATES["backend_full"],
    )
    identity = {
        "executed": summary["executed_tests"],
        "passed": summary["passed_tests"],
        "skipped": summary["skipped_tests"],
    }
    if identity != {"executed": 264, "passed": 261, "skipped": 3}:
        fail("candidate backend JUnit summary is not the pinned 264/261/3 identity")
    return "candidate backend exact inventory verified: executed=264 passed=261 skipped=3"


def write_broker_response(broker_socket, message):
    payload = message.encode("ascii") + b"\0"
    if len(payload) > 1024 or broker_socket.send(payload) != len(payload):
        fail("cannot write the deployment broker response")


def process_broker_request(request, broker_socket, gate, principal, token):
    try:
        request_text = request.decode("ascii")
    except UnicodeDecodeError:
        write_broker_response(broker_socket, "ERROR invalid broker request")
        return
    try:
        if request_text == "PING":
            result = "broker ready"
        elif request_text == "JUNIT":
            result = broker_validate_backend_junit(gate, principal)
        elif request_text.startswith("VERIFY "):
            result = broker_verify_official_candidate(
                gate, principal, token, request_text.removeprefix("VERIFY ")
            )
        else:
            raise RuntimeError("unknown request")
    except BaseException:
        write_broker_response(broker_socket, "ERROR trusted broker validation failed")
        return
    write_broker_response(broker_socket, "OK " + result)


def broker_wait_for_child(
    child_pid,
    broker_socket,
    gate,
    principal,
    token,
):
    poller = select.poll()
    broker_descriptor = broker_socket.fileno()
    poller.register(broker_descriptor, select.POLLIN | select.POLLHUP | select.POLLERR)
    while True:
        observed = os.waitid(
            os.P_PID,
            child_pid,
            os.WEXITED | os.WNOHANG | os.WNOWAIT,
        )
        if observed is not None and observed.si_pid == child_pid:
            # Leave the leader as an unreaped zombie until the death-watchdog
            # protocol is complete. This prevents PID/PGID reuse while the
            # root watchdog decides between normal marker and abnormal EOF.
            return
        for descriptor, events in poller.poll(250):
            if descriptor != broker_descriptor:
                continue
            broker_closed = False
            if events & select.POLLIN:
                credentials_size = struct.calcsize("3i")
                packet, ancillary, flags, _ = broker_socket.recvmsg(
                    MAX_BROKER_REQUEST_BYTES + 1,
                    socket.CMSG_SPACE(credentials_size),
                )
                if not packet:
                    poller.unregister(broker_descriptor)
                    broker_closed = True
                    continue
                if (
                    flags & (socket.MSG_TRUNC | socket.MSG_CTRUNC)
                    or len(packet) > MAX_BROKER_REQUEST_BYTES
                    or not packet.endswith(b"\0")
                    or b"\0" in packet[:-1]
                ):
                    fail("deployment broker request framing is invalid")
                credentials = [
                    data
                    for level, kind, data in ancillary
                    if level == socket.SOL_SOCKET and kind == socket.SCM_CREDENTIALS
                ]
                if len(credentials) != 1 or len(credentials[0]) < credentials_size:
                    fail("deployment broker request lacks kernel credentials")
                sender_pid, sender_uid, sender_gid = struct.unpack(
                    "3i", credentials[0][:credentials_size]
                )
                sender_hierarchy = process_parent_and_group(sender_pid)
                if (
                    sender_uid != principal.pw_uid
                    or sender_gid != principal.pw_gid
                    or sender_hierarchy != (child_pid, child_pid)
                ):
                    fail("deployment broker request came from an unauthorized process")
                process_broker_request(
                    packet[:-1],
                    broker_socket,
                    gate,
                    principal,
                    token,
                )
            if not broker_closed and events & (select.POLLHUP | select.POLLERR):
                # The child may close its broker endpoint just before waitpid
                # reports completion; never treat HUP alone as success.
                poller.unregister(broker_descriptor)
                break


def supervise(
    arguments,
    principal,
    launcher_payload,
    token,
    *,
    installer_doctor=False,
):
    reset_process_signals()
    directory_descriptor = open_lock_directory()
    if installer_doctor:
        if arguments != ["--doctor"]:
            fail("bundle-installer inherited locks are doctor-only")
        lock_descriptor = validate_inherited_root_lock(
            directory_descriptor,
            INSTALLER_ROOT_LOCK_FD,
        )
        legacy_lock_descriptor = validate_inherited_legacy_lock(
            principal,
            INSTALLER_LEGACY_LOCK_FD,
        )
        reject_live_lease(directory_descriptor)
    else:
        lock_descriptor = open_deployment_lock(directory_descriptor)
        reject_active_install_journal()
        reject_live_lease(directory_descriptor)
        legacy_lock_descriptor = open_legacy_deployment_lock(principal)
    release_read, release_write = os.pipe2(os.O_CLOEXEC)
    ready_read, ready_write = os.pipe2(os.O_CLOEXEC)
    death_read, death_write = os.pipe2(os.O_CLOEXEC)
    parent_broker, child_broker = socket.socketpair(
        socket.AF_UNIX,
        socket.SOCK_SEQPACKET | socket.SOCK_CLOEXEC,
    )
    parent_broker.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
    parent_pid = os.getpid()
    child_pid = os.fork()
    if child_pid == 0:
        try:
            os.close(death_write)
            os.close(release_write)
            os.close(ready_read)
            parent_broker.close()
            child_broker_descriptor = child_broker.detach()
            os.close(directory_descriptor)
            os.close(lock_descriptor)
            set_parent_death_signal(parent_pid)
            os.setsid()
            deployment_identity = process_identity(os.getpid())
            if deployment_identity is None or deployment_identity[0] != os.getpid():
                raise SystemExit(1)
            watchdog_pid = os.fork()
            if watchdog_pid == 0:
                run_death_watchdog(
                    parent_pid,
                    os.getpgrp(),
                    deployment_identity[1],
                    death_read,
                )
            os.close(death_read)
            watchdog_deadline = time.monotonic() + 5
            while True:
                watchdog_identity = process_identity(watchdog_pid)
                if (
                    watchdog_identity is not None
                    and watchdog_identity[0] == watchdog_pid
                ):
                    break
                if time.monotonic() >= watchdog_deadline:
                    raise SystemExit(1)
                time.sleep(0.01)
            ready_payload = struct.pack(
                "!QQ", watchdog_pid, watchdog_identity[1]
            )
            if os.write(ready_write, ready_payload) != len(ready_payload):
                raise SystemExit(1)
            os.close(ready_write)
            if os.read(release_read, 1) != b"G":
                raise SystemExit(1)
            os.close(release_read)
            reset_process_signals()
            drop_to_principal(principal, parent_pid)
            if child_broker_descriptor in (BROKER_FD, LEGACY_LOCK_FD) or \
                    legacy_lock_descriptor in (BROKER_FD, LEGACY_LOCK_FD):
                raise SystemExit("deployment descriptor layout is unsafe")
            os.dup2(child_broker_descriptor, BROKER_FD, inheritable=True)
            os.dup2(legacy_lock_descriptor, LEGACY_LOCK_FD, inheritable=True)
            if child_broker_descriptor not in (BROKER_FD, LEGACY_LOCK_FD):
                os.close(child_broker_descriptor)
            if legacy_lock_descriptor not in (
                BROKER_FD,
                LEGACY_LOCK_FD,
            ):
                os.close(legacy_lock_descriptor)
            environment = child_environment(launcher_payload)
            close_unapproved_descriptors({BROKER_FD, LEGACY_LOCK_FD})
            os.execve(
                TRUSTED_ENTRYPOINT,
                [TRUSTED_ENTRYPOINT, *arguments],
                environment,
            )
        except BaseException:
            os._exit(1)

    os.close(release_read)
    os.close(ready_write)
    os.close(death_read)
    child_broker.close()
    ready_payload = bytearray()
    while len(ready_payload) < 16:
        chunk = os.read(ready_read, 16 - len(ready_payload))
        if not chunk:
            break
        ready_payload.extend(chunk)
    if len(ready_payload) != 16:
        os.close(ready_read)
        os.close(release_write)
        os.close(death_write)
        fail("deployment child failed before process-group isolation")
    os.close(ready_read)
    watchdog_pid, watchdog_start_time = struct.unpack("!QQ", ready_payload)
    watchdog_identity = process_identity(watchdog_pid)
    if watchdog_identity != (watchdog_pid, watchdog_start_time):
        os.close(release_write)
        os.close(death_write)
        fail("deployment death-watchdog identity is invalid")
    identity = process_identity(child_pid)
    if identity is None or identity[0] != child_pid:
        os.close(release_write)
        os.close(death_write)
        fail("deployment child process-group identity is invalid")
    write_lease(directory_descriptor, child_pid, identity[1])

    termination_forwarded = False

    def forward(signum, _frame):
        nonlocal termination_forwarded
        if termination_forwarded:
            return
        termination_forwarded = True
        try:
            os.killpg(child_pid, signum)
        except ProcessLookupError:
            pass

    for signum in (signal.SIGHUP, signal.SIGINT, signal.SIGQUIT, signal.SIGTERM):
        signal.signal(signum, forward)

    def suspend(_signum, _frame):
        try:
            # SIGTSTP is discarded for an orphaned process group; SIGSTOP is
            # the only reliable way to suspend the setsid-isolated child.
            os.killpg(child_pid, signal.SIGSTOP)
        except ProcessLookupError:
            return
        signal.signal(signal.SIGTSTP, signal.SIG_DFL)
        os.kill(os.getpid(), signal.SIGTSTP)
        signal.signal(signal.SIGTSTP, suspend)

    def resume(_signum, _frame):
        try:
            os.killpg(child_pid, signal.SIGCONT)
        except ProcessLookupError:
            pass

    signal.signal(signal.SIGTSTP, suspend)
    signal.signal(signal.SIGCONT, resume)
    if os.write(release_write, b"G") != 1:
        fail("cannot release the supervised deployment child")
    os.close(release_write)
    gate = load_trusted_release_gate()
    broker_wait_for_child(
        child_pid,
        parent_broker,
        gate,
        principal,
        token,
    )
    parent_broker.close()
    if process_group_exists(
        child_pid,
        ignored_zombie=(child_pid, identity[1]),
    ):
        os.close(death_write)
    else:
        if os.write(death_write, b"N") != 1:
            os.close(death_write)
            fail("cannot complete the deployment death-watchdog protocol")
        os.close(death_write)
    if not wait_for_exact_process_exit(
        watchdog_pid,
        watchdog_start_time,
        5,
    ):
        try:
            os.killpg(child_pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        if not wait_for_exact_process_exit(
            watchdog_pid,
            watchdog_start_time,
            5,
        ):
            fail("deployment death watchdog did not terminate")
    if token is not None:
        for index in range(len(token)):
            token[index] = 0
    if process_group_exists(
        child_pid,
        ignored_zombie=(child_pid, identity[1]),
    ):
        fail("deployment process group survived its leader")
    lease, metadata = stable_lease(directory_descriptor)
    if (
        lease is None
        or lease["boot_id"] != boot_id()
        or lease["pid"] != child_pid
        or lease["start_time"] != identity[1]
    ):
        fail("deployment lease changed while the child was running")
    remove_stale_lease(directory_descriptor, metadata)
    observed_pid, wait_status = os.waitpid(child_pid, 0)
    if observed_pid != child_pid:
        fail("cannot reap the supervised deployment child")
    os.close(lock_descriptor)
    os.close(legacy_lock_descriptor)
    os.close(directory_descriptor)
    if os.WIFEXITED(wait_status):
        raise SystemExit(os.WEXITSTATUS(wait_status))
    if os.WIFSIGNALED(wait_status):
        raise SystemExit(128 + os.WTERMSIG(wait_status))
    fail("deployment child returned an unknown wait status")


def main():
    if os.geteuid() != 0 or os.getegid() != 0:
        fail("launcher must start as root")
    if os.path.realpath(__file__) != TRUSTED_LAUNCHER:
        fail("only the installed launcher may run")
    arguments = sys.argv[1:]
    if not arguments:
        fail("missing deploy arguments")
    os.umask(0o077)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    disable_process_dumping()
    reset_process_signals()
    token = read_token_from_standard_input(arguments)
    installer_doctor = consume_installer_doctor_authority(arguments)
    inherited_descriptors = (
        {INSTALLER_ROOT_LOCK_FD, INSTALLER_LEGACY_LOCK_FD}
        if installer_doctor
        else set()
    )
    close_unapproved_descriptors(inherited_descriptors)
    for directory in (
        "/",
        "/usr",
        "/usr/local",
        "/usr/local/sbin",
        "/usr/local/libexec",
        TRUSTED_BUNDLE_DIR,
        "/etc",
        "/etc/xjie-production-deploy",
    ):
        root_directory(directory)
    launcher_descriptor, launcher_payload = stable_root_file(
        TRUSTED_LAUNCHER, 0o555, read_bytes=True
    )
    os.close(launcher_descriptor)
    entrypoint_descriptor, _ = stable_root_file(TRUSTED_ENTRYPOINT, 0o555)
    os.close(entrypoint_descriptor)
    installer_descriptor, installer_payload = stable_root_file(
        TRUSTED_INSTALLER,
        0o555,
        read_bytes=True,
    )
    os.close(installer_descriptor)
    try:
        compile(installer_payload, TRUSTED_INSTALLER, "exec", dont_inherit=True)
    except (SyntaxError, ValueError, TypeError):
        fail("trusted bundle installer is not valid Python source")
    spec_descriptor, _ = stable_root_file(TRUSTED_SPEC, 0o444)
    os.close(spec_descriptor)
    guard_descriptor, _ = stable_root_file(TRUSTED_DEPLOY_GUARD, 0o444)
    os.close(guard_descriptor)
    release_gate_descriptor, _ = stable_root_file(TRUSTED_RELEASE_GATE, 0o444)
    os.close(release_gate_descriptor)
    inventory_descriptor, _ = stable_root_file(TRUSTED_TEST_INVENTORY, 0o444)
    os.close(inventory_descriptor)
    authority_descriptor, _ = stable_root_file(LAUNCH_AUTHORITY, 0o400)
    os.close(authority_descriptor)
    try:
        principal = pwd.getpwnam(DEPLOY_PRINCIPAL)
    except KeyError:
        fail("deployment principal does not exist")
    if (
        principal.pw_uid == 0
        or principal.pw_gid == 0
        or principal.pw_dir != "/home/mayl"
    ):
        fail("deployment principal identity is invalid")
    supervise(
        arguments,
        principal,
        launcher_payload,
        token,
        installer_doctor=installer_doctor,
    )


if __name__ == "__main__":
    main()
