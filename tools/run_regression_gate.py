#!/usr/bin/env python3
"""Run impacted or release-quality gates and bind release evidence to HEAD."""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import fcntl
import fnmatch
import hashlib
import json
import os
import pwd
import re
import secrets
import shlex
import ssl
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / "quality" / "regression_contracts.json"
MANIFEST_PATH = REPO_ROOT / "quality" / "change_impact.json"
EVIDENCE_PATH = REPO_ROOT / ".quality" / "release_gate.json"
SIGNOFF_PATH = REPO_ROOT / ".quality" / "release_signoffs.json"
SIGNOFF_EVIDENCE_ROOT = REPO_ROOT / ".quality" / "evidence"
PROJECT_FILE_PATH = REPO_ROOT / "Xjie" / "Xjie.xcodeproj" / "project.pbxproj"
EXPECTED_PYTHON_TESTS_PATH = REPO_ROOT / "quality" / "expected_python_tests.json"
BACKEND_VENV_DIR = REPO_ROOT / "backend" / ".venv"
BACKEND_JUNIT_PATHS = {
    "backend_ai": Path("/tmp/xjie-backend-ai.xml"),
    "backend_health": Path("/tmp/xjie-backend-health.xml"),
    "backend_full": Path("/tmp/xjie-backend-full.xml"),
}
BACKEND_FULL_ALLOWED_SKIPS = {
    "tests.integration.test_api_chat_mock::test_chat_mock_placeholder": (
        "requires dockerized postgres + redis stack"
    ),
    "tests.integration.test_api_glucose_import::test_glucose_import_flow_placeholder": (
        "requires dockerized postgres + redis stack"
    ),
    "tests.integration.test_api_meals_flow::test_meals_photo_flow_placeholder": (
        "requires dockerized postgres + redis stack"
    ),
}
MAX_BACKEND_JUNIT_BYTES = 16 * 1024 * 1024
MANDATORY_RELEASE_COMMAND_TEMPLATES = {
    "guard_unit": "/usr/bin/python3 -I tools/python_test_gate.py tools",
    "ios_unit": "rm -rf /tmp/xjie-quality-unit.xcresult /tmp/xjie-quality-unit-derived && xcodebuild test -project Xjie/Xjie.xcodeproj -scheme Xjie -configuration Debug -destination 'platform=iOS Simulator,name={simulator}' -derivedDataPath /tmp/xjie-quality-unit-derived -resultBundlePath /tmp/xjie-quality-unit.xcresult -only-testing:XjieTests && /usr/bin/python3 -I tools/validate_xcresult.py --path /tmp/xjie-quality-unit.xcresult --expected-profile ios_unit",
    "ios_ui_full": "rm -rf /tmp/xjie-quality-ui.xcresult /tmp/xjie-quality-ui-derived && xcodebuild test -project Xjie/Xjie.xcodeproj -scheme Xjie -configuration Debug -destination 'platform=iOS Simulator,name={simulator}' -derivedDataPath /tmp/xjie-quality-ui-derived -resultBundlePath /tmp/xjie-quality-ui.xcresult -only-testing:XjieUITests && /usr/bin/python3 -I tools/validate_xcresult.py --path /tmp/xjie-quality-ui.xcresult --expected-profile ios_ui_full",
    "ios_ui_small": "rm -rf /tmp/xjie-quality-ui-small.xcresult /tmp/xjie-quality-ui-small-derived && xcodebuild test -project Xjie/Xjie.xcodeproj -scheme Xjie -configuration Debug -destination 'platform=iOS Simulator,name={small_simulator}' -derivedDataPath /tmp/xjie-quality-ui-small-derived -resultBundlePath /tmp/xjie-quality-ui-small.xcresult -only-testing:XjieUITests/XAgeHighIntensityContextUITests/testNavigationTouchTargetsAndFormDismissalConventions -only-testing:XjieUITests/XAgeHighIntensityContextUITests/testMetricManagerPageAndChatKeyboardLifecycle && /usr/bin/python3 -I tools/validate_xcresult.py --path /tmp/xjie-quality-ui-small.xcresult --expected-profile ios_ui_small --required-device-model 'iPhone SE (3rd generation)'",
    "backend_full": "{backend_python} -I tools/python_test_gate.py backend --profile full --junitxml /tmp/xjie-backend-full.xml -- backend/tests -q",
    "ios_release_build": "xcodebuild -project Xjie/Xjie.xcodeproj -scheme Xjie -configuration Release -destination 'generic/platform=iOS' -showBuildSettings -json | /usr/bin/python3 -I tools/verify_release_bundle.py --release-build-settings-stdin && rm -rf /tmp/xjie-quality-release.xcarchive /tmp/xjie-quality-release-derived && xcodebuild archive -project Xjie/Xjie.xcodeproj -scheme Xjie -configuration Release -destination 'generic/platform=iOS' -archivePath /tmp/xjie-quality-release.xcarchive -derivedDataPath /tmp/xjie-quality-release-derived CODE_SIGNING_ALLOWED=NO CODE_SIGNING_REQUIRED=NO && /usr/bin/python3 -I tools/verify_release_bundle.py /tmp/xjie-quality-release.xcarchive/Products/Applications/Xjie.app",
    "diff_check": "if git rev-parse --verify HEAD^1 >/dev/null 2>&1; then git diff --check HEAD^1 HEAD; else git diff-tree --check --root --no-commit-id HEAD; fi",
}
PINNED_FOCUSED_BACKEND_COMMAND_TEMPLATES = {
    "backend_ai": "{backend_python} -I tools/python_test_gate.py backend --profile focused --junitxml /tmp/xjie-backend-ai.xml -- backend/tests/unit/test_chat_execution_pipeline.py backend/tests/unit/test_chat_routing.py backend/tests/unit/test_chat_message_structure.py backend/tests/unit/test_health_nlu.py backend/tests/unit/test_numeric_health_risk.py backend/tests/unit/test_numeric_risk_reply.py backend/tests/unit/test_safety_response.py backend/tests/unit/test_chat_response_guard.py backend/tests/unit/test_openai_provider_parsing.py backend/tests/unit/test_chat_citations.py backend/tests/unit/test_chat_evidence.py -q",
    "backend_health": "{backend_python} -I tools/python_test_gate.py backend --profile focused --junitxml /tmp/xjie-backend-health.xml -- backend/tests/unit/test_device_indicator_sync.py backend/tests/unit/test_device_indicator_sync_http.py backend/tests/unit/test_migration_0021_device_indicator_identity.py backend/tests/unit/test_account_lifecycle.py -q",
}
MANDATORY_RELEASE_COMMANDS = tuple(MANDATORY_RELEASE_COMMAND_TEMPLATES)
MANDATORY_RELEASE_SIGNOFFS = (
    "real_device_healthkit",
    "apple_watch_background_sync",
    "third_party_keyboard",
    "accessibility_large_text_voiceover",
    "controlled_ai_answer",
)
PINNED_GITHUB_REPOSITORY = "doyoulikelin-wq/XJie_IOS"
PINNED_GITHUB_WORKFLOW = "ci.yml"
PINNED_REQUIRED_CHECK = {
    "name": "quality-gate",
    "app_slug": "github-actions",
    "app_id": 15368,
}
PINNED_PROTECTED_BRANCHES = ["XAGE", "main"]
PINNED_MAX_AGE_HOURS = 24
PINNED_SMALL_SIMULATOR_NAME = "XAGE UX SE 3"
PINNED_SMALL_DEVICE_TYPE = "com.apple.CoreSimulator.SimDeviceType.iPhone-SE-3rd-generation"
IMPACTED_DIFF_CHECK = "git diff --check HEAD + exact untracked-file whitespace check"
PINNED_BRANCH_PROTECTION = {
    "strict": True,
    "enforce_admins": True,
    "allow_force_pushes": False,
    "allow_deletions": False,
    "required_pull_request_reviews": {
        "required_approving_review_count": 0,
        "dismiss_stale_reviews": True,
        "require_code_owner_reviews": False,
        "require_last_push_approval": False,
        "bypass_pull_request_allowances_empty": True,
    },
}
ALLOWED_NON_REDIRECTING_GIT_ENVIRONMENT = frozenset(
    {
        "GIT_ASKPASS",
        "GIT_EDITOR",
        "GIT_FLUSH",
        "GIT_NO_REPLACE_OBJECTS",
        "GIT_PAGER",
        "GIT_SEQUENCE_EDITOR",
        "GIT_TERMINAL_PROMPT",
        "GIT_TRACE",
        "GIT_TRACE_CURL",
        "GIT_TRACE_PACKET",
        "GIT_TRACE_PERFORMANCE",
        "GIT_TRACE_REDACT",
        "GIT_TRACE_SETUP",
    }
)
INTERNAL_SAFE_GIT_ENVIRONMENT = {
    "GIT_ATTR_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_OPTIONAL_LOCKS": "0",
}
GATE_LOCK_FILENAME = "xjie-regression-gate.lock"
TRUSTED_GIT_BINARY = "/usr/bin/git"
TRUSTED_COMMAND_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"
PINNED_DEVELOPER_DIR = "/Applications/Xcode.app/Contents/Developer"
PINNED_XCODE_VERSION = "26.3"
PINNED_XCODE_BUILD = "17C529"
PINNED_LATEST_UPLOADED_BUILD = 17
FORBIDDEN_NETWORK_ENVIRONMENT = frozenset(
    {
        "all_proxy",
        "http_proxy",
        "https_proxy",
        "no_proxy",
        "curl_ca_bundle",
        "requests_ca_bundle",
        "ssl_cert_dir",
        "ssl_cert_file",
    }
)
UNSAFE_LOCAL_GIT_CONFIG_PATTERN = (
    r"^(core\.(attributesfile|fsmonitor|ignorestat|trustctime|checkstat|worktree)"
    r"|extensions\.worktreeconfig|filter\.|diff\.|include\.|url\.)"
)


class GateError(RuntimeError):
    pass


def project_version_identity(project_file: Path = PROJECT_FILE_PATH) -> dict[str, str]:
    try:
        source = project_file.read_text(encoding="utf-8")
    except (FileNotFoundError, UnicodeDecodeError) as exc:
        raise GateError(f"cannot read Xcode project version settings: {project_file}") from exc

    def unique_numeric_setting(name: str, pattern: str) -> str:
        values = [
            match.group(1).strip()
            for match in re.finditer(
                rf"(?m)^\s*{re.escape(name)}\s*=\s*([^;]+);",
                source,
            )
        ]
        if not values:
            raise GateError(f"Xcode project is missing {name}")
        invalid = sorted({value for value in values if re.fullmatch(pattern, value) is None})
        if invalid:
            raise GateError(f"Xcode project has a non-numeric {name}: {', '.join(invalid)}")
        unique = sorted(set(values))
        if len(unique) != 1:
            raise GateError(f"Xcode project must have one unique {name}: {', '.join(unique)}")
        return unique[0]

    return {
        "app_version": unique_numeric_setting(
            "MARKETING_VERSION", r"[0-9]+(?:\.[0-9]+)*"
        ),
        "app_build": unique_numeric_setting("CURRENT_PROJECT_VERSION", r"[1-9][0-9]*"),
    }


def require_new_release_build(
    registry: dict[str, Any],
    app_identity: dict[str, str] | None = None,
) -> dict[str, str]:
    identity = project_version_identity() if app_identity is None else app_identity
    latest_uploaded = registry.get("release_gate", {}).get("latest_uploaded_build")
    if latest_uploaded != PINNED_LATEST_UPLOADED_BUILD:
        raise GateError("release registry latest_uploaded_build was redirected or is stale")
    try:
        candidate_build = int(identity["app_build"])
    except (KeyError, TypeError, ValueError) as exc:
        raise GateError("release candidate has an invalid CURRENT_PROJECT_VERSION") from exc
    if candidate_build <= latest_uploaded:
        raise GateError(
            "release candidate must use a never-uploaded CURRENT_PROJECT_VERSION: "
            f"candidate={candidate_build}, latest_uploaded={latest_uploaded}; "
            f"bump the build to at least {latest_uploaded + 1} and repeat every candidate-bound signoff"
        )
    return identity


def ensure_no_git_repository_redirects(
    environment: dict[str, str] | os._Environ[str] | None = None,
) -> None:
    values = os.environ if environment is None else environment
    redirected = sorted(
        key
        for key in values
        if key.startswith("GIT_")
        and key not in ALLOWED_NON_REDIRECTING_GIT_ENVIRONMENT
        and INTERNAL_SAFE_GIT_ENVIRONMENT.get(key) != values.get(key)
    )
    if redirected:
        raise GateError(
            "gate rejects repository-affecting GIT_* environment variables: "
            + ", ".join(redirected)
        )


def ensure_no_network_verification_redirects(
    environment: dict[str, str] | os._Environ[str] | None = None,
) -> None:
    values = os.environ if environment is None else environment
    redirected = sorted(
        key for key in values if key.lower() in FORBIDDEN_NETWORK_ENVIRONMENT
    )
    if redirected:
        raise GateError(
            "gate rejects proxy or custom-CA environment variables: "
            + ", ".join(redirected)
        )


def trusted_subprocess_environment() -> dict[str, str]:
    try:
        home = Path(pwd.getpwuid(os.getuid()).pw_dir).resolve(strict=True)
    except (KeyError, OSError, RuntimeError) as exc:
        raise GateError("cannot resolve the current account home directory") from exc
    if not home.is_dir():
        raise GateError("current account home directory is not a real directory")
    environment = {
        "PATH": TRUSTED_COMMAND_PATH,
        "HOME": str(home),
        "TMPDIR": "/tmp",
        "LANG": "en_US.UTF-8",
        "LC_ALL": "C",
        "ZDOTDIR": "/var/empty",
        "PYTHONDONTWRITEBYTECODE": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
        **INTERNAL_SAFE_GIT_ENVIRONMENT,
    }
    if Path(PINNED_DEVELOPER_DIR).is_dir():
        environment["DEVELOPER_DIR"] = PINNED_DEVELOPER_DIR
    return environment


def require_pinned_xcode_toolchain() -> dict[str, str]:
    binary = Path(PINNED_DEVELOPER_DIR) / "usr" / "bin" / "xcodebuild"
    try:
        metadata = binary.lstat()
    except FileNotFoundError as exc:
        raise GateError(f"pinned Xcode is missing: {binary}") from exc
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != 0 or metadata.st_mode & 0o022:
        raise GateError(f"pinned xcodebuild must be a root-owned, non-writable regular file: {binary}")
    result = subprocess.run(
        [str(binary), "-version"],
        cwd=REPO_ROOT,
        env=trusted_subprocess_environment(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    expected = f"Xcode {PINNED_XCODE_VERSION}\nBuild version {PINNED_XCODE_BUILD}"
    if result.returncode != 0 or result.stdout.strip() != expected:
        raise GateError(
            f"local gates require {expected.replace(chr(10), ' / ')}; "
            f"found {result.stdout.strip() or result.stderr.strip()!r}"
        )
    return {
        "developer_dir": PINNED_DEVELOPER_DIR,
        "version": PINNED_XCODE_VERSION,
        "build": PINNED_XCODE_BUILD,
        "binary": str(binary),
    }


def _git_common_directory() -> Path:
    raw = git("rev-parse", "--git-common-dir")
    path = Path(raw)
    if not path.is_absolute():
        path = REPO_ROOT / path
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError as exc:
        raise GateError("cannot resolve the shared Git directory for the gate lock") from exc
    if not resolved.is_dir():
        raise GateError("shared Git directory for the gate lock is not a directory")
    return resolved


@contextlib.contextmanager
def gate_lock(common_git_directory: Path | None = None):
    """Serialize all fixed-output gates across every worktree of the repository."""

    lock_root = _git_common_directory() if common_git_directory is None else common_git_directory
    lock_path = lock_root / GATE_LOCK_FILENAME
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        raise GateError(f"cannot open shared regression-gate lock {lock_path}: {exc}") from exc
    acquired = False
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise GateError(f"shared regression-gate lock is not a regular file: {lock_path}")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise GateError(
                "another impacted/release/assert-release gate is already running for this repository"
            ) from exc
        acquired = True
        os.ftruncate(descriptor, 0)
        os.write(descriptor, f"pid={os.getpid()}\n".encode("ascii"))
        os.fsync(descriptor)
        yield
    finally:
        if acquired:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def validate_release_registry_identity(registry: dict[str, Any]) -> None:
    release = registry.get("release_gate")
    if not isinstance(release, dict):
        raise GateError("release registry is missing release_gate")
    expected = {
        "github_repository": PINNED_GITHUB_REPOSITORY,
        "github_workflow": PINNED_GITHUB_WORKFLOW,
        "required_check": PINNED_REQUIRED_CHECK,
        "protected_branches": PINNED_PROTECTED_BRANCHES,
        "max_age_hours": PINNED_MAX_AGE_HOURS,
        "branch_protection": PINNED_BRANCH_PROTECTION,
        "latest_uploaded_build": PINNED_LATEST_UPLOADED_BUILD,
    }
    for field, value in expected.items():
        if release.get(field) != value:
            raise GateError(f"release registry identity was redirected or weakened: {field}")


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise GateError(f"cannot load {path.relative_to(REPO_ROOT)}: {exc}") from exc
    if not isinstance(value, dict):
        raise GateError(f"{path.relative_to(REPO_ROOT)} must contain a JSON object")
    return value


def git(*args: str, check: bool = True) -> str:
    ensure_no_git_repository_redirects()
    environment = trusted_subprocess_environment()
    result = subprocess.run(
        [TRUSTED_GIT_BINARY, *args],
        cwd=REPO_ROOT,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check and result.returncode != 0:
        raise GateError(result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip()


def git_bytes(*args: str, check: bool = True) -> bytes:
    ensure_no_git_repository_redirects()
    environment = trusted_subprocess_environment()
    result = subprocess.run(
        [TRUSTED_GIT_BINARY, *args],
        cwd=REPO_ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check and result.returncode != 0:
        raise GateError(
            result.stderr.decode("utf-8", errors="replace").strip()
            or result.stdout.decode("utf-8", errors="replace").strip()
        )
    return result.stdout


def ensure_canonical_repository_without_replace_refs() -> None:
    """Bind every SHA/tree check to this checkout's real, unreplaced objects."""

    top_level = Path(git("rev-parse", "--show-toplevel"))
    try:
        resolved_top_level = top_level.resolve(strict=True)
    except FileNotFoundError as exc:
        raise GateError("cannot resolve the repository top level") from exc
    if resolved_top_level != REPO_ROOT:
        raise GateError(
            f"gate repository root was redirected: {resolved_top_level}; expected {REPO_ROOT}"
        )
    replace_refs = git("for-each-ref", "--format=%(refname)", "refs/replace")
    if replace_refs:
        raise GateError("gate rejects local Git replace refs: " + replace_refs.replace("\n", ", "))


def ensure_safe_repository_configuration() -> None:
    unsafe = git(
        "config",
        "--local",
        "--get-regexp",
        UNSAFE_LOCAL_GIT_CONFIG_PATTERN,
        check=False,
    )
    if unsafe:
        raise GateError("gate rejects unsafe local Git configuration")
    attributes = _git_common_directory() / "info" / "attributes"
    if attributes.exists() or attributes.is_symlink():
        raise GateError(f"gate rejects repository-local attributes override: {attributes}")


def _read_stable_regular_file(
    path: Path,
    *,
    label: str,
    maximum_bytes: int | None = None,
    require_current_uid: bool = False,
    require_single_link: bool = False,
) -> tuple[bytes, os.stat_result]:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise GateError(f"cannot open {label} as a non-symlink file: {path}") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise GateError(f"{label} must be a regular file: {path}")
        if require_current_uid and before.st_uid != os.getuid():
            raise GateError(f"{label} must be owned by the current gate account: {path}")
        if require_single_link and before.st_nlink != 1:
            raise GateError(f"{label} must have exactly one hard link: {path}")
        if maximum_bytes is not None and (before.st_size <= 0 or before.st_size > maximum_bytes):
            raise GateError(
                f"{label} must be non-empty and no larger than {maximum_bytes} bytes: {path}"
            )
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
        stable_fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        if any(getattr(before, field) != getattr(after, field) for field in stable_fields):
            raise GateError(f"{label} changed while it was being read: {path}")
        payload = b"".join(chunks)
        if len(payload) != before.st_size:
            raise GateError(f"{label} size changed while it was being read: {path}")
        return payload, before
    finally:
        os.close(descriptor)


def _is_recognized_native_executable(payload: bytes) -> bool:
    if len(payload) < 4:
        return False
    magic = payload[:4]
    return magic in {
        b"\x7fELF",
        b"\xfe\xed\xfa\xce",
        b"\xce\xfa\xed\xfe",
        b"\xfe\xed\xfa\xcf",
        b"\xcf\xfa\xed\xfe",
        b"\xca\xfe\xba\xbe",
        b"\xbe\xba\xfe\xca",
        b"\xca\xfe\xba\xbf",
        b"\xbf\xba\xfe\xca",
    } or payload[:2] == b"MZ"


def require_trusted_gate_python_runtime() -> dict[str, str]:
    if sys.version_info < (3, 9) or sys.flags.isolated != 1 \
            or sys.flags.no_user_site != 1 or sys.flags.ignore_environment != 1:
        raise GateError(
            "release gates must run with the isolated Apple toolchain Python: "
            "/usr/bin/python3 -I tools/run_regression_gate.py ..."
        )
    try:
        executable = Path(sys.executable).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise GateError("cannot resolve the release-gate Python executable") from exc
    try:
        trusted_root = Path(PINNED_DEVELOPER_DIR).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise GateError("pinned Xcode developer directory is unavailable") from exc
    try:
        executable.relative_to(trusted_root)
    except ValueError as exc:
        raise GateError("release gate Python must come from the pinned Apple/Xcode toolchain") from exc
    payload, metadata = _read_stable_regular_file(
        executable,
        label="release-gate Python executable",
    )
    if metadata.st_uid != 0 or metadata.st_mode & 0o022 \
            or metadata.st_mode & 0o111 == 0 or not _is_recognized_native_executable(payload):
        raise GateError(
            "release-gate Python must be a root-owned, non-writable native executable"
        )
    return {
        "executable": str(executable),
        "version": ".".join(str(value) for value in sys.version_info[:3]),
        "isolated": "true",
    }


def _require_real_path_components(path: Path, *, root: Path, label: str) -> None:
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise GateError(f"{label} must remain within {root}: {path}") from exc
    current = root
    for component in relative.parts:
        current /= component
        try:
            metadata = current.lstat()
        except FileNotFoundError as exc:
            raise GateError(f"{label} does not exist: {current}") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise GateError(f"{label} path must not contain symlinks: {current}")
        if current != path and not stat.S_ISDIR(metadata.st_mode):
            raise GateError(f"{label} parent must be a directory: {current}")


def _backend_dependency_snapshot(venv: Path, purelib: Path, config: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    file_count = 0

    def add_file(path: Path, relative: str) -> None:
        nonlocal file_count
        payload, metadata = _read_stable_regular_file(path, label="backend dependency")
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(f"{stat.S_IMODE(metadata.st_mode):o}".encode("ascii"))
        digest.update(b"\0")
        digest.update(str(len(payload)).encode("ascii"))
        digest.update(b"\0")
        digest.update(payload)
        digest.update(b"\0")
        file_count += 1

    add_file(config, "pyvenv.cfg")
    for directory, directory_names, file_names in os.walk(purelib, topdown=True, followlinks=False):
        directory_path = Path(directory)
        for name in sorted(directory_names):
            child = directory_path / name
            try:
                metadata = child.lstat()
            except FileNotFoundError as exc:
                raise GateError(f"backend dependency directory disappeared: {child}") from exc
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                raise GateError(f"backend dependency directories must be real directories: {child}")
        directory_names[:] = sorted(directory_names)
        for name in sorted(file_names):
            child = directory_path / name
            try:
                relative = child.relative_to(venv).as_posix()
            except ValueError as exc:
                raise GateError(f"backend dependency escaped the virtual environment: {child}") from exc
            add_file(child, relative)
    return digest.hexdigest(), file_count


def backend_runtime_identity(venv_dir: Path = BACKEND_VENV_DIR) -> dict[str, Any]:
    venv = Path(os.path.abspath(venv_dir))
    for directory, label in ((venv, "backend virtual environment"), (venv / "bin", "backend bin")):
        try:
            metadata = directory.lstat()
        except FileNotFoundError as exc:
            raise GateError(f"{label} is missing: {directory}") from exc
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise GateError(f"{label} must be a real non-symlink directory: {directory}")

    config = venv / "pyvenv.cfg"
    config_payload, _ = _read_stable_regular_file(config, label="backend pyvenv.cfg")
    try:
        config_text = config_payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GateError("backend pyvenv.cfg must be valid UTF-8") from exc
    system_site_values = re.findall(
        r"(?mi)^\s*include-system-site-packages\s*=\s*(\S+)\s*$", config_text
    )
    if [value.lower() for value in system_site_values] != ["false"]:
        raise GateError("backend pyvenv.cfg must disable system site-packages exactly once")

    launcher = venv / "bin" / "python"
    try:
        launcher_metadata = launcher.lstat()
        resolved_executable = launcher.resolve(strict=True)
    except (FileNotFoundError, RuntimeError, OSError) as exc:
        raise GateError(f"backend Python launcher cannot be resolved: {launcher}") from exc
    if not (stat.S_ISREG(launcher_metadata.st_mode) or stat.S_ISLNK(launcher_metadata.st_mode)):
        raise GateError(f"backend Python launcher must be a regular file or symlink: {launcher}")
    try:
        resolved_executable.relative_to(REPO_ROOT)
    except ValueError:
        pass
    else:
        raise GateError("backend Python must resolve to a native executable outside the repository")
    executable_payload, executable_metadata = _read_stable_regular_file(
        resolved_executable,
        label="resolved backend Python executable",
    )
    if executable_metadata.st_mode & 0o111 == 0:
        raise GateError("resolved backend Python executable is not executable")
    if not _is_recognized_native_executable(executable_payload):
        raise GateError("resolved backend Python must be an ELF, Mach-O, or PE native executable")

    probe = (
        "import json,os,site,sys,sysconfig;"
        "print(json.dumps({"
        "'version':list(sys.version_info[:3]),"
        "'executable':sys.executable,"
        "'resolved_executable':os.path.realpath(sys.executable),"
        "'prefix':os.path.realpath(sys.prefix),"
        "'base_prefix':os.path.realpath(sys.base_prefix),"
        "'purelib':sysconfig.get_path('purelib'),"
        "'resolved_purelib':os.path.realpath(sysconfig.get_path('purelib')),"
        "'isolated':sys.flags.isolated,"
        "'no_user_site':sys.flags.no_user_site,"
        "'ignore_environment':sys.flags.ignore_environment,"
        "'enable_user_site':site.ENABLE_USER_SITE}))"
    )
    result = subprocess.run(
        [str(launcher), "-I", "-c", probe],
        cwd=REPO_ROOT,
        env=trusted_subprocess_environment(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    try:
        runtime = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise GateError("backend Python failed the isolated runtime identity probe") from exc
    if result.returncode != 0 or not isinstance(runtime, dict) or result.stderr:
        raise GateError("backend Python failed the isolated runtime identity probe")
    version = runtime.get("version")
    if not isinstance(version, list) or len(version) != 3 \
            or any(type(value) is not int for value in version) or tuple(version) < (3, 11, 0):
        raise GateError("backend Python 3.11 or newer is required")
    if Path(str(runtime.get("executable", ""))) != launcher:
        raise GateError("backend Python sys.executable is not the validated virtualenv launcher")
    if Path(str(runtime.get("resolved_executable", ""))) != resolved_executable:
        raise GateError("backend Python resolved executable changed during the identity probe")
    if Path(str(runtime.get("prefix", ""))) != venv:
        raise GateError("backend Python sys.prefix is not the validated virtual environment")
    base_prefix = Path(str(runtime.get("base_prefix", "")))
    try:
        resolved_base_prefix = base_prefix.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise GateError("backend Python sys.base_prefix is invalid") from exc
    if not base_prefix.is_absolute() or resolved_base_prefix != base_prefix \
            or base_prefix == venv or not base_prefix.is_dir():
        raise GateError("backend Python sys.base_prefix is invalid")
    if runtime.get("isolated") != 1 or runtime.get("no_user_site") != 1 \
            or runtime.get("ignore_environment") != 1 or runtime.get("enable_user_site") is not False:
        raise GateError("backend Python probe was not fully isolated from user configuration")

    purelib = Path(str(runtime.get("purelib", "")))
    if not purelib.is_absolute() \
            or Path(str(runtime.get("resolved_purelib", ""))) != purelib:
        raise GateError("backend site-packages path must not resolve through symlinks")
    _require_real_path_components(purelib, root=venv, label="backend site-packages")
    try:
        purelib_metadata = purelib.lstat()
    except FileNotFoundError as exc:
        raise GateError(f"backend site-packages is missing: {purelib}") from exc
    if not stat.S_ISDIR(purelib_metadata.st_mode):
        raise GateError(f"backend site-packages must be a directory: {purelib}")

    dependency_sha256, dependency_files = _backend_dependency_snapshot(venv, purelib, config)
    return {
        "launcher": str(launcher),
        "resolved_executable": str(resolved_executable),
        "binary_sha256": hashlib.sha256(executable_payload).hexdigest(),
        "version": ".".join(str(value) for value in version),
        "prefix": str(venv),
        "base_prefix": str(base_prefix),
        "purelib": str(purelib),
        "dependency_sha256": dependency_sha256,
        "dependency_files": dependency_files,
    }


def _load_expected_backend_tests() -> list[str]:
    payload = load_json(EXPECTED_PYTHON_TESTS_PATH)
    values = payload.get("backend_full")
    if payload.get("schema_version") != 1 or tuple(payload) != (
        "schema_version", "backend_full", "tools"
    ) or not isinstance(values, list) or not values \
            or any(not isinstance(value, str) or not value for value in values) \
            or values != sorted(values) or len(values) != len(set(values)):
        raise GateError("exact backend Python test inventory is invalid")
    return values


def _focused_backend_modules(command: str) -> set[str]:
    try:
        tokens = shlex.split(command)
        selection = tokens[tokens.index("--") + 1:]
    except (ValueError, IndexError) as exc:
        raise GateError("focused backend command is missing its explicit test selection") from exc
    modules: set[str] = set()
    backend_root = REPO_ROOT / "backend"
    tests_root = backend_root / "tests"
    for token in selection:
        if token.startswith("-"):
            continue
        candidate = REPO_ROOT / token
        try:
            relative = candidate.relative_to(backend_root)
        except ValueError as exc:
            raise GateError(f"backend test selection escaped backend/: {token}") from exc
        if candidate == tests_root:
            raise GateError("focused backend command cannot select the full backend test directory")
        try:
            metadata = candidate.lstat()
            resolved_candidate = candidate.resolve(strict=True)
            resolved_candidate.relative_to(tests_root.resolve(strict=True))
        except (FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
            raise GateError(f"focused backend command has an invalid test file: {token}") from exc
        if candidate.suffix != ".py" or not candidate.name.startswith("test_") \
                or stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise GateError(f"focused backend command has an invalid test file: {token}")
        modules.add(".".join(relative.with_suffix("").parts))
    if not modules:
        raise GateError("focused backend command selected no test modules")
    return modules


def _backend_inventory_sha256(values: list[str]) -> str:
    return hashlib.sha256(("\n".join(values) + "\n").encode("utf-8")).hexdigest()


def validate_backend_junit_output(command_id: str, path: Path, command: str) -> dict[str, Any]:
    if command_id not in BACKEND_JUNIT_PATHS or path != BACKEND_JUNIT_PATHS[command_id]:
        raise GateError(f"backend JUnit path is not pinned for {command_id}")
    expected_command = (
        MANDATORY_RELEASE_COMMAND_TEMPLATES["backend_full"]
        if command_id == "backend_full"
        else PINNED_FOCUSED_BACKEND_COMMAND_TEMPLATES.get(command_id)
    )
    if command != expected_command:
        raise GateError(f"backend test selection or JUnit command changed: {command_id}")
    payload, _ = _read_stable_regular_file(
        path,
        label=f"{command_id} JUnit result",
        maximum_bytes=MAX_BACKEND_JUNIT_BYTES,
        require_current_uid=True,
        require_single_link=True,
    )
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise GateError(f"{command_id} produced malformed JUnit XML") from exc
    expected_all = _load_expected_backend_tests()
    if command_id == "backend_full":
        expected = set(expected_all)
        expected_skips = BACKEND_FULL_ALLOWED_SKIPS
    else:
        modules = _focused_backend_modules(command)
        expected = {
            node
            for node in expected_all
            if any(
                node.partition("::")[0] == module
                or node.partition("::")[0].startswith(module + ".")
                for module in modules
            )
        }
        expected_skips = {}
    case_ids: list[str] = []
    actual_skips: dict[str, str] = {}
    failed: list[str] = []
    for case in root.iter("testcase"):
        classname = (case.get("classname") or "").strip()
        name = (case.get("name") or "").strip()
        if not classname or not name:
            raise GateError(f"{command_id} JUnit contains a testcase without classname/name")
        node_id = f"{classname}::{name}"
        case_ids.append(node_id)
        if case.find("failure") is not None or case.find("error") is not None:
            failed.append(node_id)
        skipped = case.find("skipped")
        if skipped is not None:
            actual_skips[node_id] = (skipped.get("message") or "").strip()
    duplicates = sorted({node for node in case_ids if case_ids.count(node) > 1})
    if duplicates:
        raise GateError(f"{command_id} JUnit contains duplicate test IDs: {', '.join(duplicates)}")
    if failed:
        raise GateError(f"{command_id} JUnit contains failed/error tests: {', '.join(failed)}")
    actual = set(case_ids)
    if actual != expected:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        details: list[str] = []
        if missing:
            details.append("missing=" + ",".join(missing))
        if unexpected:
            details.append("unexpected=" + ",".join(unexpected))
        raise GateError(f"{command_id} exact JUnit inventory mismatch: {'; '.join(details)}")
    if actual_skips != expected_skips:
        raise GateError(f"{command_id} JUnit skip allowlist or reason changed")
    return {
        "junit_path": str(path),
        "junit_sha256": hashlib.sha256(payload).hexdigest(),
        "junit_inventory_sha256": _backend_inventory_sha256(sorted(actual)),
        "executed_tests": len(actual),
        "passed_tests": len(actual) - len(actual_skips),
        "skipped_tests": len(actual_skips),
    }


def _prepare_backend_junit(command_id: str) -> Path | None:
    path = BACKEND_JUNIT_PATHS.get(command_id)
    if path is None:
        return None
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return path
    if stat.S_ISDIR(metadata.st_mode):
        raise GateError(f"backend JUnit output path is a directory: {path}")
    try:
        path.unlink()
    except OSError as exc:
        raise GateError(f"cannot remove prior backend JUnit output: {path}") from exc
    return path


def expand_command(
    command: str,
    *,
    backend_runtime: dict[str, Any] | None = None,
) -> str:
    quoted_values: dict[str, str] = {}
    if "{backend_python}" in command:
        runtime = backend_runtime if backend_runtime is not None else backend_runtime_identity()
        launcher = runtime.get("launcher")
        if not isinstance(launcher, str) or not launcher:
            raise GateError("backend runtime identity is missing its validated launcher")
        quoted_values["backend_python"] = launcher
    literal_values = {
        "simulator": os.environ.get("XJIE_SIMULATOR_NAME", "iPhone 17 Pro"),
        "small_simulator": os.environ.get(
            "XJIE_SMALL_SIMULATOR_NAME", PINNED_SMALL_SIMULATOR_NAME
        ),
    }
    if "{small_simulator}" in command \
            and literal_values["small_simulator"] != PINNED_SMALL_SIMULATOR_NAME:
        raise GateError(
            f"small-screen gate requires the pinned simulator {PINNED_SMALL_SIMULATOR_NAME!r}"
        )
    for key, value in literal_values.items():
        if "'" in value:
            raise GateError(f"invalid simulator name: {value!r}")
        command = command.replace("{" + key + "}", value)
    for key, value in quoted_values.items():
        command = command.replace("{" + key + "}", shlex.quote(value))
    return command


def small_simulator_identity() -> dict[str, str]:
    result = subprocess.run(
        ["xcrun", "simctl", "list", "devices", "available", "-j"],
        cwd=REPO_ROOT,
        env=trusted_subprocess_environment(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise GateError(result.stderr.strip() or "cannot inspect the small-screen simulator")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise GateError("simctl returned invalid JSON for the small-screen simulator") from exc
    matches: list[dict[str, str]] = []
    for runtime, devices in payload.get("devices", {}).items():
        if not isinstance(devices, list):
            continue
        for device in devices:
            if not isinstance(device, dict) or device.get("name") != PINNED_SMALL_SIMULATOR_NAME:
                continue
            if device.get("deviceTypeIdentifier") != PINNED_SMALL_DEVICE_TYPE:
                raise GateError(
                    f"{PINNED_SMALL_SIMULATOR_NAME!r} is not an iPhone SE (3rd generation)"
                )
            if device.get("isAvailable") is not True:
                raise GateError(f"{PINNED_SMALL_SIMULATOR_NAME!r} is unavailable")
            matches.append(
                {
                    "name": device["name"],
                    "udid": str(device.get("udid", "")),
                    "device_type": device["deviceTypeIdentifier"],
                    "runtime": runtime,
                }
            )
    if len(matches) != 1 or not matches[0]["udid"]:
        raise GateError(
            f"expected exactly one available pinned small simulator, found {len(matches)}"
        )
    return matches[0]


def run_command(
    command_id: str,
    command: str,
    *,
    dry_run: bool,
    backend_runtime: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if command_id in BACKEND_JUNIT_PATHS and backend_runtime is None:
        backend_runtime = backend_runtime_identity()
    expanded = expand_command(command, backend_runtime=backend_runtime)
    print(f"\n[{command_id}] {expanded}", flush=True)
    if dry_run:
        return {
            "id": command_id,
            "template": command,
            "command": expanded,
            "status": "dry-run",
            "duration_seconds": 0.0,
        }
    junit_path = _prepare_backend_junit(command_id)
    started = time.monotonic()
    result = subprocess.run(
        ["/bin/zsh", "-f", "-o", "pipefail", "-c", expanded],
        cwd=REPO_ROOT,
        env=trusted_subprocess_environment(),
        check=False,
    )
    duration = round(time.monotonic() - started, 3)
    if result.returncode != 0:
        raise GateError(f"gate command failed ({command_id}, exit {result.returncode})")
    command_result = {
        "id": command_id,
        "template": command,
        "command": expanded,
        "status": "passed",
        "duration_seconds": duration,
    }
    if junit_path is not None:
        command_result.update(validate_backend_junit_output(command_id, junit_path, command))
    return command_result


def ensure_clean_and_synced() -> tuple[str, str]:
    ensure_no_hidden_index_flags()
    status = git("status", "--porcelain")
    if status:
        raise GateError("release gate requires a clean worktree; commit the verified source first")
    branch = git("branch", "--show-current")
    if branch not in {"XAGE", "main"}:
        raise GateError(f"release gate is only allowed on XAGE or main, current branch is {branch!r}")
    head = git("rev-parse", "HEAD")
    upstream = git("rev-parse", "@{upstream}", check=False)
    if not upstream:
        raise GateError("release gate requires an upstream branch")
    ahead_behind = git("rev-list", "--left-right", "--count", "@{upstream}...HEAD").split()
    if ahead_behind != ["0", "0"]:
        raise GateError(
            "release gate requires HEAD to equal its upstream; push code first, then run the full gate"
        )
    return head, branch


def ensure_official_remote_tip(
    head: str,
    branch: str,
    registry: dict[str, Any],
) -> str:
    validate_release_registry_identity(registry)
    if branch not in PINNED_PROTECTED_BRANCHES:
        raise GateError(f"cannot verify an unpinned release branch: {branch!r}")
    repository = registry["release_gate"]["github_repository"]
    payload = github_json(
        f"/repos/{repository}/branches/{urllib.parse.quote(branch, safe='')}",
        require_auth=True,
    )
    commit = payload.get("commit")
    remote_tip = commit.get("sha") if isinstance(commit, dict) else None
    if not isinstance(remote_tip, str) or len(remote_tip) != 40:
        raise GateError(f"cannot resolve official {repository}/{branch} tip")
    if remote_tip != head:
        raise GateError(
            f"release requires official {repository}/{branch} to equal HEAD; "
            f"remote={remote_tip[:12]} head={head[:12]}"
        )
    return remote_tip


def github_token() -> str | None:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        return token
    result = subprocess.run(
        [TRUSTED_GIT_BINARY, "credential", "fill"],
        cwd=REPO_ROOT,
        env=trusted_subprocess_environment(),
        input="protocol=https\nhost=github.com\n\n",
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        key, separator, value = line.partition("=")
        if separator and key == "password" and value:
            return value
    return None


def _github_payload(path: str, *, require_auth: bool = False) -> Any:
    url = "https://api.github.com" + path
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "xjie-release-gate",
    }
    token = github_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    elif require_auth:
        raise GateError(
            "GitHub branch-protection verification requires GITHUB_TOKEN/GH_TOKEN "
            "or an authenticated gh/Git credential session"
        )
    request = urllib.request.Request(url, headers=headers)
    tls_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    tls_context.check_hostname = True
    tls_context.verify_mode = ssl.CERT_REQUIRED
    tls_context.load_default_certs(ssl.Purpose.SERVER_AUTH)
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        urllib.request.HTTPSHandler(context=tls_context),
    )
    try:
        with opener.open(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise GateError(f"GitHub verification failed for {path}: {exc}") from exc
    return payload


def github_json(path: str, *, require_auth: bool = False) -> dict[str, Any]:
    payload = _github_payload(path, require_auth=require_auth)
    if not isinstance(payload, dict):
        raise GateError(f"GitHub verification returned a non-object for {path}")
    return payload


def github_list(path: str, *, require_auth: bool = False) -> list[Any]:
    payload = _github_payload(path, require_auth=require_auth)
    if not isinstance(payload, list):
        raise GateError(f"GitHub verification returned a non-list for {path}")
    return payload


def require_remote_quality_gate(
    head: str,
    branch: str,
    registry: dict[str, Any],
) -> dict[str, Any]:
    validate_release_registry_identity(registry)
    release = registry["release_gate"]
    repository = release["github_repository"]
    workflow = release["github_workflow"]
    required_check = release["required_check"]
    query = urllib.parse.urlencode(
        {
            "branch": branch,
            "head_sha": head,
            "status": "completed",
            "per_page": 20,
        }
    )
    runs_payload = github_json(
        f"/repos/{repository}/actions/workflows/{urllib.parse.quote(workflow, safe='')}/runs?{query}"
    )
    runs = runs_payload.get("workflow_runs")
    if not isinstance(runs, list):
        raise GateError("GitHub workflow response is missing workflow_runs")
    candidates = [
        run
        for run in runs
        if isinstance(run, dict)
        and run.get("head_sha") == head
        and run.get("head_branch") == branch
        and run.get("path") == f".github/workflows/{workflow}"
        and run.get("event") == "push"
    ]
    if not candidates:
        raise GateError(f"no completed {workflow} run exists for exact HEAD {head[:12]} on {branch}")
    run = max(candidates, key=lambda item: int(item.get("id", 0)))
    if run.get("conclusion") != "success":
        raise GateError(
            f"exact-SHA workflow run {run.get('id')} concluded {run.get('conclusion')!r}, not success"
        )

    checks_payload = github_json(
        f"/repos/{repository}/commits/{head}/check-runs?filter=latest&per_page=100"
    )
    checks = checks_payload.get("check_runs")
    if not isinstance(checks, list):
        raise GateError("GitHub checks response is missing check_runs")
    expected_run_fragment = f"/actions/runs/{run['id']}/"
    matches = [
        check
        for check in checks
        if isinstance(check, dict)
        and check.get("name") == required_check["name"]
        and check.get("head_sha") == head
        and check.get("status") == "completed"
        and check.get("conclusion") == "success"
        and isinstance(check.get("app"), dict)
        and check["app"].get("slug") == required_check["app_slug"]
        and check["app"].get("id") == required_check["app_id"]
        and expected_run_fragment in str(check.get("details_url", ""))
    ]
    if not matches:
        raise GateError(
            f"exact-SHA {required_check['name']} from {required_check['app_slug']} is missing or not successful"
        )
    check = max(matches, key=lambda item: int(item.get("id", 0)))
    return {
        "workflow_run_id": run["id"],
        "workflow_run_attempt": run.get("run_attempt"),
        "workflow_url": run.get("html_url"),
        "check_run_id": check["id"],
        "check_name": check["name"],
        "check_app_slug": check["app"]["slug"],
        "check_app_id": check["app"]["id"],
        "check_completed_at": check.get("completed_at"),
    }


def require_merged_pull_request(
    head: str,
    branch: str,
    registry: dict[str, Any],
) -> dict[str, Any]:
    validate_release_registry_identity(registry)
    release = registry["release_gate"]
    repository = release["github_repository"]
    pulls = github_list(
        f"/repos/{repository}/commits/{urllib.parse.quote(head, safe='')}/pulls",
        require_auth=True,
    )
    matches = []
    for pull in pulls:
        if not isinstance(pull, dict):
            continue
        base = pull.get("base")
        base_repo = base.get("repo") if isinstance(base, dict) else None
        if (
            pull.get("state") == "closed"
            and isinstance(pull.get("merged_at"), str)
            and pull.get("merged_at")
            and pull.get("merge_commit_sha") == head
            and isinstance(base, dict)
            and base.get("ref") == branch
            and isinstance(base_repo, dict)
            and base_repo.get("full_name") == repository
            and isinstance(pull.get("number"), int)
            and isinstance(pull.get("html_url"), str)
        ):
            matches.append(pull)
    if not matches:
        raise GateError(
            f"release HEAD {head[:12]} must be produced by a merged pull request into "
            f"official {repository}/{branch}"
        )
    pull = max(matches, key=lambda item: item["number"])
    return {
        "number": pull["number"],
        "url": pull["html_url"],
        "merged_at": pull["merged_at"],
        "merge_commit_sha": pull["merge_commit_sha"],
        "base_repository": repository,
        "base_branch": branch,
    }


def require_branch_protection(
    branch: str,
    registry: dict[str, Any],
    *,
    expected_app_id: int,
) -> dict[str, Any]:
    validate_release_registry_identity(registry)
    release = registry["release_gate"]
    repository = release["github_repository"]
    expected = release["branch_protection"]
    payload = github_json(
        f"/repos/{repository}/branches/{urllib.parse.quote(branch, safe='')}/protection",
        require_auth=True,
    )
    status_checks = payload.get("required_status_checks")
    if not isinstance(status_checks, dict):
        raise GateError(f"origin/{branch} has no required status checks")
    checks = status_checks.get("checks")
    if not isinstance(checks, list):
        raise GateError(f"origin/{branch} branch protection does not expose exact check bindings")
    required_check = release["required_check"]["name"]
    exact_check = any(
        isinstance(item, dict)
        and item.get("context") == required_check
        and item.get("app_id") == expected_app_id
        for item in checks
    )
    if not exact_check:
        raise GateError(
            f"origin/{branch} must require {required_check} from GitHub Actions app {expected_app_id}"
        )

    def required_boolean(mapping: dict[str, Any], field: str, location: str) -> bool:
        if field not in mapping or type(mapping[field]) is not bool:
            raise GateError(
                f"origin/{branch} branch protection {location}.{field} must be an explicit boolean"
            )
        return mapping[field]

    def required_enabled(field: str) -> bool:
        value = payload.get(field)
        if not isinstance(value, dict):
            raise GateError(
                f"origin/{branch} branch protection {field} must expose an enabled object"
            )
        return required_boolean(value, "enabled", field)

    reviews = payload.get("required_pull_request_reviews")
    if not isinstance(reviews, dict):
        raise GateError(f"origin/{branch} must require changes through a pull request")
    bypass = reviews.get("bypass_pull_request_allowances")
    bypass_empty = isinstance(bypass, dict) and all(
        isinstance(bypass.get(key), list) and not bypass[key]
        for key in ("users", "teams", "apps")
    )
    review_count = reviews.get("required_approving_review_count")
    if type(review_count) is not int:
        raise GateError(
            f"origin/{branch} branch protection required_approving_review_count must be an integer"
        )
    actual_reviews = {
        "required_approving_review_count": review_count,
        "dismiss_stale_reviews": required_boolean(
            reviews, "dismiss_stale_reviews", "required_pull_request_reviews"
        ),
        "require_code_owner_reviews": required_boolean(
            reviews, "require_code_owner_reviews", "required_pull_request_reviews"
        ),
        "require_last_push_approval": required_boolean(
            reviews, "require_last_push_approval", "required_pull_request_reviews"
        ),
        "bypass_pull_request_allowances_empty": bypass_empty,
    }

    actual = {
        "required_check": required_check,
        "required_check_app_id": expected_app_id,
        "strict": required_boolean(status_checks, "strict", "required_status_checks"),
        "enforce_admins": required_enabled("enforce_admins"),
        "allow_force_pushes": required_enabled("allow_force_pushes"),
        "allow_deletions": required_enabled("allow_deletions"),
        "required_pull_request_reviews": actual_reviews,
    }
    for field in (
        "strict",
        "enforce_admins",
        "allow_force_pushes",
        "allow_deletions",
        "required_pull_request_reviews",
    ):
        if actual[field] != expected[field]:
            raise GateError(
                f"origin/{branch} branch protection {field}={actual[field]!r}; "
                f"required={expected[field]!r}"
            )
    return actual


def require_all_branch_protections(
    registry: dict[str, Any],
    *,
    expected_app_id: int,
) -> dict[str, dict[str, Any]]:
    branches = registry["release_gate"].get("protected_branches")
    if branches != PINNED_PROTECTED_BRANCHES:
        raise GateError("release registry must protect both XAGE and main")
    return {
        branch: require_branch_protection(
            branch,
            registry,
            expected_app_id=expected_app_id,
        )
        for branch in branches
    }


def worktree_fingerprint() -> str:
    """Hash HEAD, index metadata and every tracked/non-ignored working byte."""

    digest = hashlib.sha256()
    for label, payload in (
        (b"head", git_bytes("rev-parse", "HEAD")),
        (b"index", git_bytes("ls-files", "--stage", "-z")),
        (b"flags", git_bytes("ls-files", "-v", "-z")),
        (b"local-config", git_bytes("config", "--local", "--list", "--null")),
    ):
        digest.update(label + b"\0" + len(payload).to_bytes(8, "big") + payload)

    listed = git_bytes("ls-files", "--cached", "--others", "--exclude-standard", "-z")
    paths = sorted(set(path for path in listed.split(b"\0") if path))
    for encoded_path in paths:
        relative = Path(os.fsdecode(encoded_path))
        candidate = REPO_ROOT / relative
        digest.update(b"path\0" + len(encoded_path).to_bytes(8, "big") + encoded_path)
        try:
            metadata = candidate.lstat()
        except FileNotFoundError:
            digest.update(b"missing\0")
            continue
        digest.update(str(metadata.st_mode).encode("ascii") + b"\0")
        if stat.S_ISLNK(metadata.st_mode):
            target = os.fsencode(os.readlink(candidate))
            digest.update(b"symlink\0" + len(target).to_bytes(8, "big") + target)
        elif stat.S_ISREG(metadata.st_mode):
            digest.update(b"file\0")
            try:
                with candidate.open("rb") as handle:
                    while chunk := handle.read(1024 * 1024):
                        digest.update(chunk)
            except OSError as exc:
                raise GateError(f"cannot fingerprint working file {relative}: {exc}") from exc
        else:
            digest.update(b"special\0")
    return digest.hexdigest()


def ensure_working_state_unchanged(expected: str) -> None:
    if worktree_fingerprint() != expected:
        raise GateError(
            "HEAD, index, manifest, tracked bytes or non-ignored files changed while the gate ran; "
            "discard these results and rerun the impacted gate"
        )


def hidden_index_paths(payload: str) -> list[str]:
    hidden: list[str] = []
    for line in payload.splitlines():
        if not line:
            continue
        if len(line) < 3 or line[1] != " ":
            raise GateError(f"cannot parse git ls-files -v output: {line!r}")
        if line[0] != "H":
            hidden.append(line[2:])
    return hidden


def ensure_no_hidden_index_flags() -> None:
    hidden = hidden_index_paths(git("ls-files", "-v"))
    if hidden:
        raise GateError(
            "release gate rejects assume-unchanged/skip-worktree or abnormal index flags: "
            + ", ".join(hidden[:10])
        )


def required_release_commands(registry: dict[str, Any]) -> list[str]:
    validate_release_registry_identity(registry)
    required = registry.get("release_gate", {}).get("required_commands")
    expected = list(MANDATORY_RELEASE_COMMANDS)
    if required != expected:
        raise GateError("release registry required_commands does not match mandatory full gates")
    commands = registry.get("commands")
    if not isinstance(commands, dict):
        raise GateError("release registry is missing mandatory command implementations")
    for command_id, template in MANDATORY_RELEASE_COMMAND_TEMPLATES.items():
        if commands.get(command_id) != template:
            raise GateError(f"release command template was weakened or changed: {command_id}")
    return expected


def _require_real_directory(path: Path, *, label: str) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise GateError(f"{label} does not exist: {path}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise GateError(f"{label} must be a real non-symlink directory: {path}")


def _read_signoff_evidence(path: Path, *, signoff_id: str) -> bytes:
    root = Path(os.path.abspath(SIGNOFF_EVIDENCE_ROOT))
    candidate = Path(os.path.abspath(path))

    repo_root = Path(os.path.abspath(REPO_ROOT))
    try:
        root_from_repo = root.relative_to(repo_root)
    except ValueError:
        _require_real_directory(root, label="release signoff evidence root")
    else:
        current = repo_root
        for component in root_from_repo.parts:
            current /= component
            _require_real_directory(current, label="release signoff evidence directory")

    try:
        relative = candidate.relative_to(root)
    except ValueError as exc:
        raise GateError(
            f"release signoff evidence must exist under {SIGNOFF_EVIDENCE_ROOT}: {signoff_id}"
        ) from exc
    if not relative.parts:
        raise GateError(f"release signoff evidence is not a file: {signoff_id}")

    current = root
    for component in relative.parts[:-1]:
        current /= component
        _require_real_directory(current, label="release signoff evidence directory")
    evidence_file = current / relative.parts[-1]
    try:
        metadata = evidence_file.lstat()
    except FileNotFoundError as exc:
        raise GateError(f"release signoff evidence file is missing: {signoff_id}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise GateError(
            f"release signoff evidence must be a regular non-symlink file: {signoff_id}"
        )
    if metadata.st_size <= 0:
        raise GateError(f"release signoff evidence must be non-empty: {signoff_id}")

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(evidence_file, flags)
    except OSError as exc:
        raise GateError(f"cannot open release signoff evidence safely: {signoff_id}") from exc
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or opened.st_size <= 0:
            raise GateError(
                f"release signoff evidence must remain a non-empty regular file: {signoff_id}"
            )
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        payload = b"".join(chunks)
        if not payload:
            raise GateError(f"release signoff evidence must be non-empty: {signoff_id}")
        return payload
    finally:
        os.close(descriptor)


def validate_manual_signoffs(
    registry: dict[str, Any],
    *,
    head: str,
    tree: str,
    registry_blob: str,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    signoffs = load_json(SIGNOFF_PATH)
    app_identity = require_new_release_build(registry)
    if signoffs.get("schema_version") != 1:
        raise GateError("release signoffs schema_version must be 1")
    for field, expected in {
        "head": head,
        "tree": tree,
        "registry_blob": registry_blob,
    }.items():
        if signoffs.get(field) != expected:
            raise GateError(f"release signoffs {field} does not match current candidate")
    try:
        completed = dt.datetime.fromisoformat(str(signoffs["completed_at"]))
    except (KeyError, ValueError) as exc:
        raise GateError("release signoffs completed_at is invalid") from exc
    if completed.tzinfo is None or completed.utcoffset() is None:
        raise GateError("release signoffs completed_at must include a timezone")
    current_time = now or dt.datetime.now(dt.timezone.utc)
    age = current_time - completed.astimezone(dt.timezone.utc)
    max_age = dt.timedelta(hours=float(registry["release_gate"]["max_age_hours"]))
    if age < dt.timedelta(0) or age > max_age:
        raise GateError(f"release signoffs are older than {max_age}; repeat the manual checks")

    definitions = registry["release_gate"].get("manual_signoffs")
    expected_ids = [item.get("id") for item in definitions if isinstance(item, dict)] \
        if isinstance(definitions, list) else []
    if expected_ids != list(MANDATORY_RELEASE_SIGNOFFS):
        raise GateError("release registry manual_signoffs does not match mandatory checks")
    items = signoffs.get("items")
    if not isinstance(items, list) or len(items) != len(expected_ids):
        raise GateError("release signoffs must contain every mandatory item exactly once")
    actual_ids = [item.get("id") for item in items if isinstance(item, dict)]
    if actual_ids != expected_ids or len(actual_ids) != len(items):
        raise GateError("release signoff IDs are missing, reordered or duplicated")
    for item in items:
        signoff_id = item["id"]
        if item.get("status") != "passed":
            raise GateError(f"release signoff has not passed: {signoff_id}")
        for field, expected in app_identity.items():
            if item.get(field) != expected:
                raise GateError(
                    f"release signoff {field} does not match the current App: {signoff_id}"
                )
        if not isinstance(item.get("tester"), str) or len(item["tester"].strip()) < 2:
            raise GateError(f"release signoff requires a tester: {signoff_id}")
        tester = item["tester"].strip().lower()
        if tester in {"qa", "tester", "测试员", "xx", "xxx", "name"} \
                or "填写" in tester or "replace" in tester:
            raise GateError(f"release signoff tester is still a placeholder: {signoff_id}")
        try:
            tested_at = dt.datetime.fromisoformat(str(item["tested_at"]))
        except (KeyError, ValueError) as exc:
            raise GateError(f"release signoff tested_at is invalid: {signoff_id}") from exc
        if tested_at.tzinfo is None or tested_at.utcoffset() is None:
            raise GateError(f"release signoff tested_at must include a timezone: {signoff_id}")
        tested_utc = tested_at.astimezone(dt.timezone.utc)
        if tested_utc > completed.astimezone(dt.timezone.utc) or current_time - tested_utc > max_age:
            raise GateError(f"release signoff tested_at is future or stale: {signoff_id}")

        placeholders = ("填写", "replace_with", "pending", "todo", "示例")
        environment = item.get("environment")
        if not isinstance(environment, str) or len(environment.strip()) < 8 \
                or any(marker in environment.strip().lower() for marker in placeholders):
            raise GateError(f"release signoff requires a real test environment: {signoff_id}")
        steps = item.get("steps")
        if not isinstance(steps, list) or len(steps) < 2 or any(
            not isinstance(step, str)
            or len(step.strip()) < 8
            or any(marker in step.strip().lower() for marker in placeholders)
            for step in steps
        ):
            raise GateError(f"release signoff requires repeatable steps and observations: {signoff_id}")
        evidence = item.get("evidence_reference")
        if not isinstance(evidence, str) or len(evidence.strip()) < 8 \
                or "://" in evidence \
                or any(marker in evidence.strip().lower() for marker in placeholders):
            raise GateError(f"release signoff requires a local evidence file: {signoff_id}")
        evidence_sha256 = item.get("evidence_sha256")
        if not isinstance(evidence_sha256, str) \
                or re.fullmatch(r"[0-9a-fA-F]{64}", evidence_sha256) is None:
            raise GateError(f"release signoff requires an evidence SHA-256 digest: {signoff_id}")
        raw_evidence_path = Path(evidence.strip()).expanduser()
        evidence_path = raw_evidence_path if raw_evidence_path.is_absolute() \
            else REPO_ROOT / raw_evidence_path
        evidence_payload = _read_signoff_evidence(evidence_path, signoff_id=signoff_id)
        actual_evidence_sha256 = hashlib.sha256(evidence_payload).hexdigest()
        if not secrets.compare_digest(actual_evidence_sha256, evidence_sha256.lower()):
            raise GateError(f"release signoff evidence digest does not match its file: {signoff_id}")

    return {
        "schema_version": 1,
        "head": head,
        "tree": tree,
        "registry_blob": registry_blob,
        "completed_at": signoffs["completed_at"],
        "items": expected_ids,
        **app_identity,
        "sha256": hashlib.sha256(SIGNOFF_PATH.read_bytes()).hexdigest(),
    }


def _matches_path(path: str, patterns: list[str]) -> bool:
    return any(
        fnmatch.fnmatchcase(path, pattern)
        or ("**/" in pattern and fnmatch.fnmatchcase(path, pattern.replace("**/", "")))
        for pattern in patterns
    )


def _looks_like_test_path(path: str) -> bool:
    return (
        path.startswith("backend/tests/")
        or path.startswith("tools/tests/")
        or "/XjieTests/" in path
        or "/XjieUITests/" in path
        or re.search(r"(?:^|/)test_[^/]+\.py$", path) is not None
    )


def _parse_name_status(raw: str) -> list[str]:
    tokens = raw.split("\0")
    if tokens and tokens[-1] == "":
        tokens.pop()
    paths: list[str] = []
    index = 0
    while index < len(tokens):
        status = tokens[index]
        index += 1
        if re.fullmatch(r"[ACDMRT](?:\d{1,3})?", status) is None:
            raise GateError(f"malformed git name-status entry: {status!r}")
        path_count = 2 if status[0] in {"R", "C"} else 1
        if index + path_count > len(tokens):
            raise GateError(f"incomplete git name-status entry for {status!r}")
        entry_paths = tokens[index : index + path_count]
        if any(not path for path in entry_paths):
            raise GateError(f"empty path in git name-status entry for {status!r}")
        paths.extend(entry_paths)
        index += path_count
    return paths


def working_changed_paths() -> list[str]:
    changed = _parse_name_status(
        git(
            "diff", "HEAD", "--name-status", "-z", "-M", "-C", "--find-copies-harder",
            "--diff-filter=ACDMRT",
        )
    )
    untracked_payload = git_bytes(
        "ls-files", "--others", "--exclude-standard", "-z"
    ).decode("utf-8", errors="surrogateescape")
    untracked = [path for path in untracked_payload.split("\0") if path]
    return sorted(set(changed) | {path for path in untracked if path})


def check_working_tree_whitespace(
    *,
    dry_run: bool,
    repo_root: Path = REPO_ROOT,
) -> None:
    """Run Git's whitespace checker over tracked changes and every new file."""

    print(f"\n[diff_check_working] {IMPACTED_DIFF_CHECK}", flush=True)
    if dry_run:
        return
    ensure_no_git_repository_redirects()
    environment = trusted_subprocess_environment()

    tracked = subprocess.run(
        [TRUSTED_GIT_BINARY, "diff", "--check", "HEAD"],
        cwd=repo_root,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if tracked.returncode != 0:
        details = (tracked.stderr or tracked.stdout).decode(
            "utf-8", errors="replace"
        ).strip()
        raise GateError(f"tracked working-tree whitespace check failed: {details}")

    listed = subprocess.run(
        [TRUSTED_GIT_BINARY, "ls-files", "--others", "--exclude-standard", "-z"],
        cwd=repo_root,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if listed.returncode != 0:
        raise GateError(
            "cannot enumerate untracked files for whitespace validation: "
            + listed.stderr.decode("utf-8", errors="replace").strip()
        )
    for raw_path in sorted(path for path in listed.stdout.split(b"\0") if path):
        path = raw_path.decode("utf-8", errors="surrogateescape")
        relative = Path(path)
        if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
            raise GateError(f"unsafe untracked path returned by Git: {path!r}")
        candidate = repo_root / relative
        try:
            metadata = candidate.lstat()
        except FileNotFoundError as exc:
            raise GateError(f"untracked file disappeared during whitespace check: {path}") from exc
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise GateError(f"untracked path must be a regular non-symlink file: {path}")
        result = subprocess.run(
            [TRUSTED_GIT_BINARY, "diff", "--no-index", "--check", "--", "/dev/null", path],
            cwd=repo_root,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        # A clean new file is still a no-index difference (exit 1). Whitespace
        # errors add status bit 2 and diagnostics; every other status fails.
        if result.returncode != 1 or result.stdout or result.stderr:
            details = (result.stderr or result.stdout).decode(
                "utf-8", errors="replace"
            ).strip()
            raise GateError(
                f"untracked-file whitespace check failed for {path}: {details}"
            )


def command_ids_for_impacted(
    registry: dict[str, Any], *, changed_paths: list[str] | None = None
) -> list[str]:
    manifest = load_json(MANIFEST_PATH)
    requested = set(manifest.get("impacted_domains", []))
    by_id = {domain["id"]: domain for domain in registry["behavior_domains"]}

    unmapped_tests: list[str] = []
    for path in working_changed_paths() if changed_paths is None else changed_paths:
        matching = [
            domain_id
            for domain_id, domain in by_id.items()
            if _matches_path(path, domain.get("test_patterns", []))
        ]
        requested.update(matching)
        if not matching and _looks_like_test_path(path):
            unmapped_tests.append(path)
    if unmapped_tests:
        raise GateError(
            "test/support files are not mapped to an impacted gate: "
            + ", ".join(sorted(unmapped_tests))
        )

    unknown = requested - set(by_id)
    if unknown:
        raise GateError("change manifest has unknown domains: " + ", ".join(sorted(unknown)))
    command_ids = ["guard_unit"]
    for domain_id in sorted(requested):
        command_ids.extend(by_id[domain_id]["verification_commands"])
    command_ids.append("diff_check")
    return list(dict.fromkeys(command_ids))


def validate_release_evidence(
    evidence: dict[str, Any],
    registry: dict[str, Any],
    *,
    head: str,
    branch: str,
    tree: str,
    registry_blob: str,
    remote_tip: str,
    remote_gate: dict[str, Any],
    merged_pull_request: dict[str, Any],
    branch_protections: dict[str, dict[str, Any]],
    manual_signoffs: dict[str, Any],
    small_simulator: dict[str, str],
    xcode_toolchain: dict[str, str],
    backend_runtime: dict[str, Any],
    gate_python: dict[str, str],
    now: dt.datetime | None = None,
) -> None:
    if evidence.get("schema_version") != 5:
        raise GateError("release evidence schema_version must be 5")
    expected_identity = {
        "head": head,
        "branch": branch,
        "tree": tree,
        "registry_blob": registry_blob,
        "remote_tip": remote_tip,
        "worktree_fingerprint": worktree_fingerprint(),
    }
    for field, expected in expected_identity.items():
        if evidence.get(field) != expected:
            raise GateError(f"release evidence {field} does not match current candidate")

    try:
        completed = dt.datetime.fromisoformat(str(evidence["completed_at"]))
    except (KeyError, ValueError) as exc:
        raise GateError("release evidence has an invalid completed_at") from exc
    if completed.tzinfo is None or completed.utcoffset() is None:
        raise GateError("release evidence completed_at must include a timezone")
    current_time = now or dt.datetime.now(dt.timezone.utc)
    age = current_time - completed.astimezone(dt.timezone.utc)
    max_age = dt.timedelta(hours=float(registry["release_gate"]["max_age_hours"]))
    if age < dt.timedelta(0) or age > max_age:
        raise GateError(f"release evidence is older than {max_age}; rerun the release gate")

    required = required_release_commands(registry)
    if evidence.get("required_commands") != required:
        raise GateError("release evidence required_commands does not exactly match the registry")
    results = evidence.get("results")
    if not isinstance(results, list) or len(results) != len(required):
        raise GateError("release evidence results must exactly match required_commands")
    result_ids = [item.get("id") for item in results if isinstance(item, dict)]
    if result_ids != required or len(set(result_ids)) != len(result_ids):
        raise GateError("release evidence result IDs are missing, reordered or duplicated")
    commands = registry["commands"]
    for result, command_id in zip(results, required):
        if result.get("status") != "passed":
            raise GateError(f"release evidence command did not pass: {command_id}")
        if result.get("template") != commands[command_id]:
            raise GateError(f"release evidence command template was changed: {command_id}")
        if result.get("command") != expand_command(
            commands[command_id], backend_runtime=backend_runtime
        ):
            raise GateError(f"release evidence expanded command changed: {command_id}")
        if command_id in BACKEND_JUNIT_PATHS:
            expected_junit = validate_backend_junit_output(
                command_id,
                BACKEND_JUNIT_PATHS[command_id],
                commands[command_id],
            )
            for field, expected in expected_junit.items():
                if result.get(field) != expected:
                    raise GateError(
                        f"release evidence backend JUnit field changed: {command_id}.{field}"
                    )

    cached_remote = evidence.get("remote_quality_gate")
    if not isinstance(cached_remote, dict):
        raise GateError("release evidence is missing remote_quality_gate")
    if cached_remote != remote_gate:
        raise GateError("release evidence remote quality gate changed or is incomplete")

    if evidence.get("merged_pull_request") != merged_pull_request:
        raise GateError("release evidence merged pull request changed or is invalid")
    if evidence.get("branch_protections") != branch_protections:
        raise GateError("release evidence branch protections changed or are incomplete")
    if evidence.get("manual_signoffs") != manual_signoffs:
        raise GateError("release evidence manual signoffs changed or are incomplete")
    if evidence.get("small_simulator") != small_simulator:
        raise GateError("release evidence small simulator identity changed or is invalid")
    if evidence.get("xcode_toolchain") != xcode_toolchain:
        raise GateError("release evidence Xcode toolchain identity changed or is invalid")
    if evidence.get("backend_runtime") != backend_runtime:
        raise GateError("release evidence backend runtime identity changed or is invalid")
    if evidence.get("gate_python") != gate_python:
        raise GateError("release evidence gate Python identity changed or is invalid")


def run_gate(mode: str, *, dry_run: bool) -> int:
    registry = load_json(REGISTRY_PATH)
    validate_release_registry_identity(registry)
    commands = registry["commands"]
    if mode == "impacted":
        initial_working_state = worktree_fingerprint() if not dry_run else ""
        command_ids = [
            command_id
            for command_id in command_ids_for_impacted(registry)
            if command_id != "diff_check"
        ]
        uses_xcode = any(command_id.startswith("ios_") for command_id in command_ids)
        initial_xcode_toolchain = (
            require_pinned_xcode_toolchain() if uses_xcode and not dry_run else None
        )
        backend_command_ids = [
            command_id for command_id in command_ids if command_id in BACKEND_JUNIT_PATHS
        ]
        initial_backend_runtime = (
            backend_runtime_identity() if backend_command_ids else None
        )
        guard_command = (
            "/usr/bin/python3 -I tools/regression_guard.py validate && "
            "/usr/bin/python3 -I tools/regression_guard.py check --working"
        )
        print(f"\n[static_guard] {guard_command}", flush=True)
        if not dry_run:
            result = subprocess.run(
                ["/bin/zsh", "-f", "-o", "pipefail", "-c", guard_command],
                cwd=REPO_ROOT,
                env=trusted_subprocess_environment(),
                check=False,
            )
            if result.returncode != 0:
                raise GateError("static regression guard failed")
        if not dry_run and "ios_ui_small" in command_ids:
            small_simulator_identity()
        for command_id in command_ids:
            run_command(
                command_id,
                commands[command_id],
                dry_run=dry_run,
                backend_runtime=initial_backend_runtime,
            )
        check_working_tree_whitespace(dry_run=dry_run)
        if not dry_run:
            if initial_xcode_toolchain is not None \
                    and require_pinned_xcode_toolchain() != initial_xcode_toolchain:
                raise GateError("Xcode toolchain changed while the impacted gate was running")
            if initial_backend_runtime is not None \
                    and backend_runtime_identity() != initial_backend_runtime:
                raise GateError("backend Python runtime changed while the impacted gate was running")
            ensure_working_state_unchanged(initial_working_state)
        print("\nIMPACTED REGRESSION GATE: PASSED" if not dry_run else "\nIMPACTED REGRESSION GATE: DRY RUN OK")
        return 0

    if mode != "release":
        raise AssertionError(mode)
    gate_python = require_trusted_gate_python_runtime()
    require_new_release_build(registry)
    required = required_release_commands(registry)
    initial_backend_runtime = backend_runtime_identity()
    if dry_run:
        head = git("rev-parse", "HEAD")
        branch = git("branch", "--show-current")
    else:
        head, branch = ensure_clean_and_synced()
        initial_xcode_toolchain = require_pinned_xcode_toolchain()
        tree = git("rev-parse", "HEAD^{tree}")
        registry_blob = git("rev-parse", f"HEAD:{REGISTRY_PATH.relative_to(REPO_ROOT)}")
        initial_manual_signoffs = validate_manual_signoffs(
            registry,
            head=head,
            tree=tree,
            registry_blob=registry_blob,
        )
        ensure_official_remote_tip(head, branch, registry)
        initial_remote_gate = require_remote_quality_gate(head, branch, registry)
        initial_merged_pull_request = require_merged_pull_request(head, branch, registry)
        initial_branch_protections = require_all_branch_protections(
            registry,
            expected_app_id=initial_remote_gate["check_app_id"],
        )
        initial_small_simulator = small_simulator_identity()
    results = [
        run_command(
            command_id,
            commands[command_id],
            dry_run=dry_run,
            backend_runtime=initial_backend_runtime,
        )
        for command_id in required
    ]
    if dry_run:
        print("\nRELEASE REGRESSION GATE: DRY RUN OK")
        return 0
    xcode_toolchain = require_pinned_xcode_toolchain()
    if xcode_toolchain != initial_xcode_toolchain:
        raise GateError("Xcode toolchain changed while the full release gate was running")
    backend_runtime = backend_runtime_identity()
    if backend_runtime != initial_backend_runtime:
        raise GateError("backend Python runtime changed while the full release gate was running")
    if git("rev-parse", "HEAD") != head:
        raise GateError("HEAD changed while the release gate was running; results are invalid")
    if git("status", "--porcelain"):
        raise GateError("worktree changed while the release gate was running; results are invalid")
    ensure_no_hidden_index_flags()
    remote_tip = ensure_official_remote_tip(head, branch, registry)
    remote_gate = require_remote_quality_gate(head, branch, registry)
    if remote_gate != initial_remote_gate:
        raise GateError("remote quality-gate identity changed while the full gate was running")
    merged_pull_request = require_merged_pull_request(head, branch, registry)
    if merged_pull_request != initial_merged_pull_request:
        raise GateError("merged pull request identity changed while the full gate was running")
    branch_protections = require_all_branch_protections(
        registry,
        expected_app_id=remote_gate["check_app_id"],
    )
    if branch_protections != initial_branch_protections:
        raise GateError("branch protections changed while the full gate was running")
    manual_signoffs = validate_manual_signoffs(
        registry,
        head=head,
        tree=tree,
        registry_blob=registry_blob,
    )
    if manual_signoffs != initial_manual_signoffs:
        raise GateError("manual release signoffs changed while the full gate was running")
    small_simulator = small_simulator_identity()
    if small_simulator != initial_small_simulator:
        raise GateError("small-screen simulator identity changed while the full gate was running")
    evidence = {
        "schema_version": 5,
        "head": head,
        "branch": branch,
        "tree": tree,
        "registry_blob": registry_blob,
        "remote_tip": remote_tip,
        "completed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "worktree_fingerprint": worktree_fingerprint(),
        "required_commands": required,
        "results": results,
        "remote_quality_gate": remote_gate,
        "merged_pull_request": merged_pull_request,
        "branch_protections": branch_protections,
        "manual_signoffs": manual_signoffs,
        "small_simulator": small_simulator,
        "xcode_toolchain": xcode_toolchain,
        "backend_runtime": backend_runtime,
        "gate_python": gate_python,
    }
    EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE_PATH.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nRELEASE REGRESSION GATE: PASSED; evidence={EVIDENCE_PATH.relative_to(REPO_ROOT)}")
    return 0


def assert_release() -> int:
    registry = load_json(REGISTRY_PATH)
    validate_release_registry_identity(registry)
    require_new_release_build(registry)
    evidence = load_json(EVIDENCE_PATH)
    head, branch = ensure_clean_and_synced()
    remote_tip = ensure_official_remote_tip(head, branch, registry)
    remote_gate = require_remote_quality_gate(head, branch, registry)
    merged_pull_request = require_merged_pull_request(head, branch, registry)
    branch_protections = require_all_branch_protections(
        registry,
        expected_app_id=remote_gate["check_app_id"],
    )
    tree = git("rev-parse", "HEAD^{tree}")
    registry_blob = git("rev-parse", f"HEAD:{REGISTRY_PATH.relative_to(REPO_ROOT)}")
    manual_signoffs = validate_manual_signoffs(
        registry,
        head=head,
        tree=tree,
        registry_blob=registry_blob,
    )
    small_simulator = small_simulator_identity()
    xcode_toolchain = require_pinned_xcode_toolchain()
    backend_runtime = backend_runtime_identity()
    gate_python = require_trusted_gate_python_runtime()
    validate_release_evidence(
        evidence,
        registry,
        head=head,
        branch=branch,
        tree=tree,
        registry_blob=registry_blob,
        remote_tip=remote_tip,
        remote_gate=remote_gate,
        merged_pull_request=merged_pull_request,
        branch_protections=branch_protections,
        manual_signoffs=manual_signoffs,
        small_simulator=small_simulator,
        xcode_toolchain=xcode_toolchain,
        backend_runtime=backend_runtime,
        gate_python=gate_python,
    )
    print(f"RELEASE REGRESSION GATE: valid for {head[:12]}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("impacted", "release"):
        item = subparsers.add_parser(command)
        item.add_argument("--dry-run", action="store_true")
    subparsers.add_parser("assert-release")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        ensure_no_git_repository_redirects()
        ensure_no_network_verification_redirects()
        require_trusted_gate_python_runtime()
        with gate_lock():
            ensure_canonical_repository_without_replace_refs()
            ensure_safe_repository_configuration()
            if args.command in {"impacted", "release"}:
                return run_gate(args.command, dry_run=args.dry_run)
            if args.command == "assert-release":
                return assert_release()
            raise AssertionError(args.command)
    except GateError as exc:
        print(f"REGRESSION GATE: FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
