#!/usr/bin/env python3
"""按阶段执行 XJie 回归门禁，并把发布证据绑定到不可变候选身份。

这个文件是仓库门禁的“编排层”，职责不是重新实现每一条静态规则，而是：

默认模式执行低成本的格式、配置、Python 语法和 iOS 编译检查；完整的影响域映射、
精确 XCTest/backend 清单、PG/Archive、远端身份和人工签核状态机保留在 ``--strict``
模式中。这样开发和普通交付不再重复承担完整发布门禁的成本，需要更高保证时仍可显式恢复。

所有校验都采用 fail-closed：无法读取、身份不一致、字段多出/缺失、运行时漂移或
两种模式都不吞掉命令失败。轻量 evidence 使用独立文件名，绝不冒充 strict 发布证据。
"""

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


# ---------------------------------------------------------------------------
# 仓库输入与证据路径
# ---------------------------------------------------------------------------
# 路径全部从当前脚本的真实位置推导，避免调用者通过工作目录把门禁指向另一套配置。
REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / "quality" / "regression_contracts.json"
MANIFEST_PATH = REPO_ROOT / "quality" / "change_impact.json"
EVIDENCE_PATH = REPO_ROOT / ".quality" / "release_gate.json"
INTERNAL_TESTFLIGHT_EVIDENCE_PATH = (
    REPO_ROOT / ".quality" / "internal_testflight_gate.json"
)
# 默认轻量门禁使用独立证据文件，避免它被旧的 strict schema 误认为完整发布证明。
LIGHT_RELEASE_EVIDENCE_PATH = REPO_ROOT / ".quality" / "light_release_gate.json"
LIGHT_INTERNAL_TESTFLIGHT_EVIDENCE_PATH = (
    REPO_ROOT / ".quality" / "light_internal_testflight_gate.json"
)
TESTFLIGHT_QUALIFICATIONS_PATH = REPO_ROOT / ".quality" / "testflight_qualifications"
RELEASE_SIGNOFF_PATH = REPO_ROOT / ".quality" / "release_signoffs.json"
TESTFLIGHT_SIGNOFF_PATH = REPO_ROOT / ".quality" / "testflight_signoffs.json"
SIGNOFF_EVIDENCE_ROOT = REPO_ROOT / ".quality" / "evidence"
PROJECT_FILE_PATH = REPO_ROOT / "Xjie" / "Xjie.xcodeproj" / "project.pbxproj"
EXPECTED_PYTHON_TESTS_PATH = REPO_ROOT / "quality" / "expected_python_tests.json"
BACKEND_VENV_DIR = REPO_ROOT / "backend" / ".venv"
# 后端每类命令使用独立且固定的 JUnit 文件。执行前删除旧文件，执行后重新解析，
# 从而阻止“测试没有运行，但复用了上一次 XML”的假绿结果。
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
BACKEND_JUNIT_EXPECTED_OWNER_UID: int | None = None
BACKEND_JUNIT_REQUIRED_MODE: int | None = None
MAX_BACKEND_JUNIT_BYTES = 16 * 1024 * 1024
MINIMUM_BACKEND_FULL_TESTS = 324
CURRENT_BACKEND_FULL_TESTS = 331
# ---------------------------------------------------------------------------
# 固定命令模板与运行清单
# ---------------------------------------------------------------------------
# registry 中的命令必须与这些代码侧模板一致。这样即使有人只修改 JSON，把测试命令
# 缩短、吞掉失败或改用 Simulator Archive，代码侧身份校验也会拒绝该 registry。
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
    "backend_ai": "{backend_python} -I tools/python_test_gate.py backend --profile focused --junitxml /tmp/xjie-backend-ai.xml -- backend/tests/unit/test_chat_execution_pipeline.py backend/tests/unit/test_chat_routing.py backend/tests/unit/test_chat_message_structure.py backend/tests/unit/test_health_nlu.py backend/tests/unit/test_numeric_health_risk.py backend/tests/unit/test_numeric_risk_reply.py backend/tests/unit/test_safety_response.py backend/tests/unit/test_chat_response_guard.py backend/tests/unit/test_openai_provider_parsing.py backend/tests/unit/test_chat_citations.py backend/tests/unit/test_chat_evidence.py backend/tests/unit/test_medication_trust.py -q",
    "backend_health": "{backend_python} -I tools/python_test_gate.py backend --profile focused --junitxml /tmp/xjie-backend-health.xml -- backend/tests/unit/test_device_indicator_sync.py backend/tests/unit/test_device_indicator_sync_http.py backend/tests/unit/test_dietary_records_contract.py backend/tests/unit/test_migration_0021_device_indicator_identity.py backend/tests/unit/test_health_report_admission.py backend/tests/unit/test_health_report_completion.py backend/tests/unit/test_health_profile_trust.py backend/tests/unit/test_health_profile_completion.py backend/tests/unit/test_health_trust_contracts.py backend/tests/unit/test_health_trust_expansion_schema.py backend/tests/unit/test_report_ocr_service.py backend/tests/unit/test_medication_trust.py backend/tests/unit/test_account_lifecycle.py -q",
}
MANDATORY_RELEASE_COMMANDS = tuple(MANDATORY_RELEASE_COMMAND_TEMPLATES)
# 五项签核代表自动化不能替代的真实系统边界；它们只在对应发布阶段生效。
MANDATORY_RELEASE_SIGNOFFS = (
    "real_device_healthkit",
    "apple_watch_background_sync",
    "third_party_keyboard",
    "accessibility_large_text_voiceover",
    "controlled_ai_answer",
)
# ---------------------------------------------------------------------------
# 官方仓库、分支保护与工具链固定值
# ---------------------------------------------------------------------------
# 这些常量避免通过修改本地 origin、切换 workflow/check 名称或换一套 Xcode 来伪造
# 合格候选。main 是唯一交付分支，XAGE 只保留为锁定的历史分支。
PINNED_GITHUB_REPOSITORY = "doyoulikelin-wq/XJie_IOS"
PINNED_GITHUB_WORKFLOW = "ci.yml"
PINNED_REQUIRED_CHECK = {
    "name": "quality-gate",
    "app_slug": "github-actions",
    "app_id": 15368,
}
PINNED_BRANCH_ROLES = {
    "canonical_branch": "main",
    "read_only_branches": ["XAGE"],
    "protected_branches": {
        "main": {
            "lock_branch": False,
            "allow_fork_syncing": False,
        },
        "XAGE": {
            "lock_branch": True,
            "allow_fork_syncing": False,
        },
    },
}
PINNED_PROTECTED_BRANCHES = list(PINNED_BRANCH_ROLES["protected_branches"])
PINNED_MAX_AGE_HOURS = 24
PINNED_TESTFLIGHT_SIGNOFF_MAX_AGE_HOURS = 7 * 24
PINNED_SMALL_SIMULATOR_NAME = "XAGE UX SE 3"
PINNED_SMALL_DEVICE_TYPE = "com.apple.CoreSimulator.SimDeviceType.iPhone-SE-3rd-generation"
IMPACTED_DIFF_CHECK = "git diff --check HEAD + exact untracked-file whitespace check"
# fast 是编辑反馈：保留静态检查、Unit 和被影响的后端测试，但主动排除耗时较长的
# 完整 UI、小屏 UI 和 device Archive。被排除意味着“本阶段不要求”，不是“已通过”。
FAST_EXCLUDED_COMMANDS = frozenset(
    {
        "ios_ui_full",
        "ios_ui_small",
        "ios_release_build",
    }
)
# 默认轻量路径明确排除这些高成本命令。原命令模板和完整状态机仍保留，由 --strict
# 显式调用；这里的集合也用于 dry-run 输出，让使用者能看到本次没有取得哪些证据。
LIGHT_EXCLUDED_COMMANDS = (
    "guard_unit",
    "ios_unit",
    "ios_ui_full",
    "ios_ui_small",
    "backend_ai",
    "backend_health",
    "backend_full",
    "ios_release_build",
)
BACKEND_FULL_SUPERSEDES = frozenset({"backend_ai", "backend_health"})
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
# ---------------------------------------------------------------------------
# 进程与 Git 信任边界
# ---------------------------------------------------------------------------
# 只允许不会改变对象解析、配置来源或网络目标的 Git 环境变量。其余 Git_* 输入若可
# 重定向仓库、对象或命令执行，必须在门禁启动时拒绝。
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
PINNED_LATEST_UPLOADED_BUILD = 18
PENDING_INTERNAL_CANDIDATE_KEYS = (
    "schema_version",
    "status",
    "head",
    "tree",
    "registry_blob",
    "app_version",
    "app_build",
    "uploaded_at",
    "installation_source",
    "upload",
    "external_promotion_allowed",
)
HISTORICAL_XCODE_UPLOAD_KEYS = (
    "method",
    "distribution_identifier",
    "app_store_app_id",
    "provider_id",
    "uploaded_build_number",
    "certificate_sha1",
    "state",
    "title",
    "archive_info_sha256",
    "archive_log_sha256",
    "upload_log_sha256",
    "ipa_sha256",
    "distribution_cdhash",
    "provenance_limitation",
)
VERIFIED_LOCAL_IPA_UPLOAD_KEYS = (
    "method",
    "ipa_sha256",
    "distribution_cdhash",
    "archive_info_sha256",
    "profile_sha256",
    "distribution_certificate_sha256",
    "upload_result_sha256",
    "internal_gate_sha256",
    "upload_tool",
)
PINNED_HISTORICAL_BUILD_18_PENDING = {
    "schema_version": 1,
    "status": "uploaded_pending_qualification",
    "head": "c93f020f95e4ad689668d58384909d978096f41d",
    "tree": "93026ae66e1680d3fac936f6f1b8d3963f1fe0e9",
    "registry_blob": "fb13a9a93e4533bc194f184bb286c7dbf925cfc0",
    "app_version": "1.0",
    "app_build": "18",
    "uploaded_at": "2026-07-16T06:04:09Z",
    "installation_source": "TestFlight",
    "upload": {
        "method": "xcode_destination_upload",
        "distribution_identifier": "0419e5e8-e865-45a2-9132-0cc43434779e",
        "app_store_app_id": "6761322429",
        "provider_id": "0bae3b2d-2dd8-424d-bcad-dfe50245fe9a",
        "uploaded_build_number": "18",
        "certificate_sha1": "D4FE01831AE2ED5CD5665CECB751E7F43374E000",
        "state": "success",
        "title": "Uploaded to Apple",
        "archive_info_sha256": "02ad616c1f117296146dd3d2143e2425a5404f22137f66ca7c88c5fb297ffabe",
        "archive_log_sha256": "16a31605236f252db880f8f639be0c773908e8da7d055067bce54eaacd8b12de",
        "upload_log_sha256": "c100340a86094605d7efa6c75a0d0f5dfa9e03710ab36eee832490867ebf65e1",
        "ipa_sha256": None,
        "distribution_cdhash": None,
        "provenance_limitation": (
            "Xcode destination=upload used managed remote signing and did not retain a "
            "locally inspectable distribution IPA; exact clean HEAD was checked in the "
            "upload session, but no package-level IPA SHA-256/CDHash can be recovered "
            "for this historical upload."
        ),
    },
    "external_promotion_allowed": False,
}
FINAL_EVIDENCE_KEYS = (
    "schema_version",
    "head",
    "branch",
    "tree",
    "registry_blob",
    "remote_tip",
    "completed_at",
    "worktree_fingerprint",
    "required_commands",
    "results",
    "remote_quality_gate",
    "merged_pull_request",
    "branch_protections",
    "small_simulator",
    "xcode_toolchain",
    "backend_runtime",
    "gate_python",
    "manual_signoffs",
)
INTERNAL_EVIDENCE_KEYS = (
    "schema_version",
    "phase",
    *FINAL_EVIDENCE_KEYS[1:-1],
)
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


# GateError 表示“候选不满足门禁”，main() 会把它转成稳定的非零退出码和简洁错误；
# 这与程序自身的 AssertionError/编码错误区分开，便于 CI 判断失败性质。
class GateError(RuntimeError):
    pass


def project_version_identity_from_source(
    source: str, *, label: str = "Xcode project"
) -> dict[str, str]:
    """从 PBX 文本提取唯一版本号与构建号，并拒绝缺失或多值配置。

    发布证据最终绑定的是 App 的实际 ``MARKETING_VERSION`` 和
    ``CURRENT_PROJECT_VERSION``。如果不同 build configuration 给出多个值，门禁无法
    确定上传身份，因此不选择“看起来正确”的一个，而是直接失败。
    """
    def unique_numeric_setting(name: str, pattern: str) -> str:
        values = [
            match.group(1).strip()
            for match in re.finditer(
                rf"(?m)^\s*{re.escape(name)}\s*=\s*([^;]+);",
                source,
            )
        ]
        if not values:
            raise GateError(f"{label} is missing {name}")
        invalid = sorted({value for value in values if re.fullmatch(pattern, value) is None})
        if invalid:
            raise GateError(f"{label} has a non-numeric {name}: {', '.join(invalid)}")
        unique = sorted(set(values))
        if len(unique) != 1:
            raise GateError(f"{label} must have one unique {name}: {', '.join(unique)}")
        return unique[0]

    return {
        "app_version": unique_numeric_setting(
            "MARKETING_VERSION", r"[0-9]+(?:\.[0-9]+)*"
        ),
        "app_build": unique_numeric_setting("CURRENT_PROJECT_VERSION", r"[1-9][0-9]*"),
    }


def project_version_identity(project_file: Path = PROJECT_FILE_PATH) -> dict[str, str]:
    try:
        source = project_file.read_text(encoding="utf-8")
    except (FileNotFoundError, UnicodeDecodeError) as exc:
        raise GateError(f"cannot read Xcode project version settings: {project_file}") from exc
    return project_version_identity_from_source(source)


def require_new_release_build(
    registry: dict[str, Any],
    app_identity: dict[str, str] | None = None,
) -> dict[str, str]:
    """确保候选构建号严格大于已经上传的构建号，阻止覆盖或重试旧 build。"""
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
    """拒绝会改变 Git 仓库、对象库、索引或 replace refs 解析结果的环境变量。"""
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
    """拒绝代理/证书等网络重定向变量，保证 GitHub 身份核验访问预期信任边界。"""
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
    """构造子命令的最小受控环境，清除可改变 Git/Python/网络行为的继承状态。"""
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
    """核对固定 Developer 目录和精确 Xcode 版本，并返回可写入证据的工具链身份。"""
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
    """在 Git common directory 上取得排他锁，防止两个门禁同时写证据或复用输出。"""
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


def _matches_exact_json(actual: Any, expected: Any) -> bool:
    """Compare JSON-compatible values without Python's bool/int/float coercions."""

    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return tuple(actual) == tuple(expected) and all(
            _matches_exact_json(actual[key], expected[key]) for key in expected
        )
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(
            _matches_exact_json(actual_item, expected_item)
            for actual_item, expected_item in zip(actual, expected)
        )
    return actual == expected


def _parse_timezone_datetime(value: Any, *, label: str) -> dt.datetime:
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise GateError(f"{label} is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise GateError(f"{label} must include a timezone")
    return parsed


def _sha256_json(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validated_pending_internal_candidate(
    release: dict[str, Any],
) -> dict[str, Any] | None:
    """严格验证 registry 中待验收 TestFlight 候选的字段、来源和历史/未来回执形态。"""
    pending = release.get("pending_internal_candidate")
    if pending is None:
        return None
    if not isinstance(pending, dict) or tuple(pending) != PENDING_INTERNAL_CANDIDATE_KEYS:
        raise GateError("pending_internal_candidate does not match the tracked receipt schema")
    if pending.get("schema_version") != 1 \
            or pending.get("status") != "uploaded_pending_qualification":
        raise GateError("pending internal candidate must be uploaded and awaiting qualification")
    for field in ("head", "tree", "registry_blob"):
        if re.fullmatch(r"[0-9a-f]{40}", str(pending.get(field, ""))) is None:
            raise GateError(f"pending internal candidate has an invalid {field}")
    if re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", str(pending.get("app_version", ""))) is None:
        raise GateError("pending internal candidate has an invalid app_version")
    if pending.get("app_build") != str(PINNED_LATEST_UPLOADED_BUILD):
        raise GateError("pending internal candidate must identify latest_uploaded_build")
    if pending.get("app_build") == "18" \
            and not _matches_exact_json(pending, PINNED_HISTORICAL_BUILD_18_PENDING):
        raise GateError(
            "historical build 18 pending identity is immutable and internal-only"
        )
    _parse_timezone_datetime(
        pending.get("uploaded_at"), label="pending internal candidate uploaded_at"
    )
    if pending.get("installation_source") != "TestFlight" \
            or pending.get("external_promotion_allowed") is not False:
        raise GateError(
            "pending internal candidate must require TestFlight and deny external promotion"
        )
    upload = pending.get("upload")
    if not isinstance(upload, dict):
        raise GateError("pending internal candidate upload receipt must be an object")
    method = upload.get("method")
    if method == "xcode_destination_upload":
        if tuple(upload) != HISTORICAL_XCODE_UPLOAD_KEYS:
            raise GateError("historical Xcode upload receipt shape is invalid")
        for field in ("distribution_identifier", "provider_id"):
            if re.fullmatch(
                r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
                str(upload.get(field, "")),
            ) is None:
                raise GateError(f"historical Xcode upload has an invalid {field}")
        if re.fullmatch(r"[1-9][0-9]*", str(upload.get("app_store_app_id", ""))) is None \
                or upload.get("uploaded_build_number") != pending.get("app_build"):
            raise GateError("historical Xcode upload app/build identity is invalid")
        if re.fullmatch(r"[0-9A-F]{40}", str(upload.get("certificate_sha1", ""))) is None:
            raise GateError("historical Xcode upload certificate SHA-1 is invalid")
        if upload.get("state") != "success" or upload.get("title") != "Uploaded to Apple":
            raise GateError("historical Xcode receipt does not prove a successful Apple upload")
        for field in ("archive_info_sha256", "archive_log_sha256", "upload_log_sha256"):
            if re.fullmatch(r"[0-9a-f]{64}", str(upload.get(field, ""))) is None:
                raise GateError(f"historical Xcode upload has an invalid {field}")
        if upload.get("ipa_sha256") is not None \
                or upload.get("distribution_cdhash") is not None:
            raise GateError("historical Xcode upload must not invent an IPA/CDHash binding")
        limitation = upload.get("provenance_limitation")
        if not isinstance(limitation, str) or len(limitation.strip()) < 32:
            raise GateError("historical Xcode upload must disclose its provenance limitation")
    elif method == "verified_local_ipa_altool":
        if tuple(upload) != VERIFIED_LOCAL_IPA_UPLOAD_KEYS:
            raise GateError("verified local IPA upload receipt shape is invalid")
        for field in (
            "ipa_sha256",
            "archive_info_sha256",
            "profile_sha256",
            "distribution_certificate_sha256",
            "upload_result_sha256",
            "internal_gate_sha256",
        ):
            if re.fullmatch(r"[0-9a-f]{64}", str(upload.get(field, ""))) is None:
                raise GateError(f"verified local IPA upload has an invalid {field}")
        if re.fullmatch(
            r"[0-9a-f]{40,64}", str(upload.get("distribution_cdhash", ""))
        ) is None:
            raise GateError("verified local IPA upload has an invalid distribution_cdhash")
        upload_tool = str(upload.get("upload_tool", ""))
        if not upload_tool.startswith(
            "/Applications/Xcode.app/Contents/SharedFrameworks/"
            "ContentDelivery.framework/Versions/"
        ) or not upload_tool.endswith("/Resources/altoolShim"):
            raise GateError("verified local IPA upload tool is outside pinned Xcode")
    else:
        raise GateError("pending internal candidate upload method is unsupported")
    return pending


def pending_upload_receipt_identifier(pending: dict[str, Any]) -> str:
    upload = pending["upload"]
    if upload["method"] == "xcode_destination_upload":
        return f"xcode-distribution:{upload['distribution_identifier']}"
    if upload["method"] == "verified_local_ipa_altool":
        return f"altool-result-sha256:{upload['upload_result_sha256']}"
    raise GateError("pending internal candidate upload method is unsupported")


def testflight_qualification_path(pending: dict[str, Any]) -> Path:
    return TESTFLIGHT_QUALIFICATIONS_PATH / (
        f"{pending['app_version']}-{pending['app_build']}.json"
    )


def pending_internal_candidate(registry: dict[str, Any]) -> dict[str, Any]:
    validate_release_registry_identity(registry)
    pending = _validated_pending_internal_candidate(registry["release_gate"])
    if pending is None:
        raise GateError("there is no tracked internal TestFlight candidate to qualify")
    return pending


def require_no_pending_internal_candidate(registry: dict[str, Any]) -> None:
    if _validated_pending_internal_candidate(registry["release_gate"]) is not None:
        raise GateError(
            "an internal TestFlight candidate is still pending qualification; "
            "qualify or explicitly retire it by setting pending_internal_candidate to null "
            "in a protected registry PR first; local receipt files cannot retire it"
        )


def validate_release_registry_identity(registry: dict[str, Any]) -> None:
    """确认发布 registry 与代码侧固定合同完全一致，阻止只改配置来降低门槛。"""
    release = registry.get("release_gate")
    if not isinstance(release, dict):
        raise GateError("release registry is missing release_gate")
    expected = {
        "github_repository": PINNED_GITHUB_REPOSITORY,
        "github_workflow": PINNED_GITHUB_WORKFLOW,
        "required_check": PINNED_REQUIRED_CHECK,
        "branch_roles": PINNED_BRANCH_ROLES,
        "max_age_hours": PINNED_MAX_AGE_HOURS,
        "testflight_signoff_max_age_hours": PINNED_TESTFLIGHT_SIGNOFF_MAX_AGE_HOURS,
        "branch_protection": PINNED_BRANCH_PROTECTION,
        "latest_uploaded_build": PINNED_LATEST_UPLOADED_BUILD,
    }
    for field, value in expected.items():
        if not _matches_exact_json(release.get(field), value):
            raise GateError(f"release registry identity was redirected or weakened: {field}")
    if "protected_branches" in release:
        raise GateError("release registry must not retain the legacy protected_branches field")
    branch_roles = release["branch_roles"]
    if list(branch_roles) != list(PINNED_BRANCH_ROLES):
        raise GateError("release registry branch_roles fields were reordered or changed")
    protected_branches = branch_roles["protected_branches"]
    if list(protected_branches) != PINNED_PROTECTED_BRANCHES:
        raise GateError("release registry protected branch roles were reordered or changed")
    for branch, expected_role in PINNED_BRANCH_ROLES["protected_branches"].items():
        if list(protected_branches[branch]) != list(expected_role):
            raise GateError(
                f"release registry protected branch role fields were reordered: {branch}"
            )
        if any(
            type(protected_branches[branch].get(field)) is not bool
            for field in expected_role
        ):
            raise GateError(
                f"release registry protected branch role values must be booleans: {branch}"
            )
    _validated_pending_internal_candidate(release)
    definitions = release.get("post_upload_signoffs")
    ids = [item.get("id") for item in definitions if isinstance(item, dict)] \
        if isinstance(definitions, list) else []
    if ids != list(MANDATORY_RELEASE_SIGNOFFS) \
            or not isinstance(definitions, list) or len(ids) != len(definitions):
        raise GateError("release registry post_upload_signoffs does not match mandatory checks")
    for item in definitions:
        description = item.get("description")
        if not isinstance(description, str) or len(description.strip()) < 8 \
                or "TestFlight" not in description:
            raise GateError("every post-upload signoff must describe its TestFlight boundary")


def canonical_release_branch(registry: dict[str, Any]) -> str:
    validate_release_registry_identity(registry)
    return registry["release_gate"]["branch_roles"]["canonical_branch"]


def load_json(path: Path) -> dict[str, Any]:
    """读取必须是普通文件的 JSON 对象；格式错误或顶层非对象都作为门禁失败。"""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise GateError(f"cannot load {path.relative_to(REPO_ROOT)}: {exc}") from exc
    if not isinstance(value, dict):
        raise GateError(f"{path.relative_to(REPO_ROOT)} must contain a JSON object")
    return value


def git(*args: str, check: bool = True) -> str:
    """通过固定系统 Git 和受控环境执行文本命令，默认要求退出码为零。"""
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
    """绑定后端原生 Python、隔离路径和 site-packages 字节，检测测试期间依赖漂移。"""
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
    if len(values) < MINIMUM_BACKEND_FULL_TESTS:
        raise GateError(
            "exact backend Python test inventory fell below the non-shrink floor: "
            f"actual={len(values)} minimum={MINIMUM_BACKEND_FULL_TESTS}"
        )
    if len(values) != CURRENT_BACKEND_FULL_TESTS:
        raise GateError(
            "exact backend Python test inventory does not match the current baseline: "
            f"actual={len(values)} expected={CURRENT_BACKEND_FULL_TESTS}"
        )
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
    """重新解析本次生成的 JUnit，核对精确 ID、skip 白名单、数量和文件身份。"""
    if command_id not in BACKEND_JUNIT_PATHS or path != BACKEND_JUNIT_PATHS[command_id]:
        raise GateError(f"backend JUnit path is not pinned for {command_id}")
    expected_command = (
        MANDATORY_RELEASE_COMMAND_TEMPLATES["backend_full"]
        if command_id == "backend_full"
        else PINNED_FOCUSED_BACKEND_COMMAND_TEMPLATES.get(command_id)
    )
    if command != expected_command:
        raise GateError(f"backend test selection or JUnit command changed: {command_id}")
    payload, metadata = _read_stable_regular_file(
        path,
        label=f"{command_id} JUnit result",
        maximum_bytes=MAX_BACKEND_JUNIT_BYTES,
        require_current_uid=BACKEND_JUNIT_EXPECTED_OWNER_UID is None,
        require_single_link=True,
    )
    if (
        BACKEND_JUNIT_EXPECTED_OWNER_UID is not None
        and metadata.st_uid != BACKEND_JUNIT_EXPECTED_OWNER_UID
    ):
        raise GateError(f"{command_id} JUnit result has an unexpected owner")
    if (
        BACKEND_JUNIT_REQUIRED_MODE is not None
        and stat.S_IMODE(metadata.st_mode) != BACKEND_JUNIT_REQUIRED_MODE
    ):
        raise GateError(f"{command_id} JUnit result has an unexpected mode")
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
            if skipped.get("type") not in (None, "pytest.skip"):
                raise GateError(
                    f"{command_id} JUnit contains an expected-failure/non-skip result: "
                    f"{node_id}"
                )
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
    """执行 registry 中一个命令，并在需要时追加 JUnit 与运行时一致性验证。"""
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


def ensure_clean_and_synced(registry: dict[str, Any]) -> tuple[str, str]:
    """要求发布候选位于干净的 canonical main，且本地 HEAD 等于官方远端 tip。"""
    canonical_branch = canonical_release_branch(registry)
    ensure_no_hidden_index_flags()
    status = git("status", "--porcelain")
    if status:
        raise GateError("release gate requires a clean worktree; commit the verified source first")
    branch = git("branch", "--show-current")
    if branch != canonical_branch:
        raise GateError(
            "release gate is only allowed on the canonical branch from the pinned registry: "
            f"required={canonical_branch!r} current={branch!r}"
        )
    head = git("rev-parse", "HEAD")
    upstream_ref = git(
        "rev-parse", "--symbolic-full-name", "@{upstream}", check=False
    )
    if not upstream_ref:
        raise GateError("release gate requires an upstream branch")
    expected_upstream_ref = f"refs/remotes/origin/{canonical_branch}"
    if upstream_ref != expected_upstream_ref:
        raise GateError(
            "release gate upstream must track the canonical branch from the pinned registry: "
            f"required={expected_upstream_ref!r} upstream={upstream_ref!r}"
        )
    upstream = git("rev-parse", "@{upstream}", check=False)
    if not upstream:
        raise GateError("release gate cannot resolve the canonical upstream tip")
    ahead_behind = git("rev-list", "--left-right", "--count", "@{upstream}...HEAD").split()
    if ahead_behind != ["0", "0"]:
        raise GateError(
            "release gate requires HEAD to equal its upstream; push code first, then run the full gate"
        )
    return head, branch


def ensure_official_remote_tip(
    head: str,
    registry: dict[str, Any],
) -> str:
    branch = canonical_release_branch(registry)
    repository = registry["release_gate"]["github_repository"]
    repository_payload = github_json(
        f"/repos/{repository}",
        require_auth=True,
    )
    if repository_payload.get("full_name") != repository:
        raise GateError(f"cannot verify official GitHub repository identity: {repository}")
    if repository_payload.get("default_branch") != branch:
        raise GateError(
            f"official {repository} default_branch must equal canonical {branch!r}; "
            f"found={repository_payload.get('default_branch')!r}"
        )
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
    registry: dict[str, Any],
) -> dict[str, Any]:
    """核对 exact-SHA 的 push workflow 和 GitHub Actions quality-gate 身份及结论。"""
    branch = canonical_release_branch(registry)
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
    if (
        type(run.get("id")) is not int
        or run["id"] <= 0
        or type(run.get("run_attempt")) is not int
        or run["run_attempt"] <= 0
        or not isinstance(run.get("html_url"), str)
        or not run["html_url"]
    ):
        raise GateError("exact-SHA workflow run identity has invalid JSON types")
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
        and _matches_exact_json(check["app"].get("id"), required_check["app_id"])
        and expected_run_fragment in str(check.get("details_url", ""))
    ]
    if not matches:
        raise GateError(
            f"exact-SHA {required_check['name']} from {required_check['app_slug']} is missing or not successful"
        )
    check = max(matches, key=lambda item: int(item.get("id", 0)))
    if (
        type(check.get("id")) is not int
        or check["id"] <= 0
        or not isinstance(check.get("completed_at"), str)
        or not check["completed_at"]
    ):
        raise GateError("exact-SHA quality-gate check identity has invalid JSON types")
    return {
        "head_sha": head,
        "head_branch": branch,
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
    registry: dict[str, Any],
) -> dict[str, Any]:
    """证明当前候选确由一个合入 main 且 merge_commit_sha 精确匹配 HEAD 的 PR 产生。"""
    branch = canonical_release_branch(registry)
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
    if type(pull.get("number")) is not int or pull["number"] <= 0:
        raise GateError("merged pull request number must be a positive integer")
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
    """从 GitHub 实时回读单个分支保护，拒绝本地 JSON 声称但远端未安装的保护。"""
    validate_release_registry_identity(registry)
    release = registry["release_gate"]
    repository = release["github_repository"]
    expected = release["branch_protection"]
    expected_branch_roles = release["branch_roles"]["protected_branches"]
    if branch not in expected_branch_roles:
        raise GateError(f"cannot verify an unpinned protected branch: {branch!r}")
    expected_branch = expected_branch_roles[branch]
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
        and _matches_exact_json(item.get("app_id"), expected_app_id)
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
    bypass_field = "bypass_pull_request_allowances"
    if bypass_field not in reviews:
        # GitHub omits this object when no actor has pull-request bypass rights.
        bypass_empty = True
    else:
        bypass = reviews[bypass_field]
        bypass_empty = (
            isinstance(bypass, dict)
            and set(bypass) == {"users", "teams", "apps"}
            and all(
                isinstance(bypass[key], list) and not bypass[key]
                for key in ("users", "teams", "apps")
            )
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
        "lock_branch": required_enabled("lock_branch"),
        "allow_fork_syncing": required_enabled("allow_fork_syncing"),
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
    for field in ("lock_branch", "allow_fork_syncing"):
        if actual[field] != expected_branch[field]:
            raise GateError(
                f"origin/{branch} branch protection {field}={actual[field]!r}; "
                f"required={expected_branch[field]!r}"
            )
    return actual


def require_all_branch_protections(
    registry: dict[str, Any],
    *,
    expected_app_id: int,
) -> dict[str, dict[str, Any]]:
    validate_release_registry_identity(registry)
    branches = registry["release_gate"]["branch_roles"]["protected_branches"]
    if list(branches) != PINNED_PROTECTED_BRANCHES:
        raise GateError("release registry must protect canonical main and read-only XAGE")
    return {
        branch: require_branch_protection(
            branch,
            registry,
            expected_app_id=expected_app_id,
        )
        for branch in branches
    }


def worktree_fingerprint() -> str:
    """对工作树状态和相关文件字节建立摘要，用于发现门禁运行期间的并发修改。"""
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
    signoff_path: Path,
    head: str,
    tree: str,
    registry_blob: str,
    now: dt.datetime | None = None,
    candidate_identity: dict[str, str] | None = None,
    definitions_key: str = "manual_signoffs",
    minimum_tested_at: dt.datetime | None = None,
    require_testflight: bool = False,
    pending_candidate_sha256: str | None = None,
    upload_receipt_identifier: str | None = None,
) -> dict[str, Any]:
    """校验真实设备/受控签核、时间、候选身份及本地脱敏证据 SHA-256。"""
    signoffs = load_json(signoff_path)
    app_identity = (
        require_new_release_build(registry)
        if candidate_identity is None
        else candidate_identity
    )
    if type(signoffs.get("schema_version")) is not int or signoffs["schema_version"] != 1:
        raise GateError("release signoffs schema_version must be 1")
    for field, expected in {
        "head": head,
        "tree": tree,
        "registry_blob": registry_blob,
    }.items():
        if signoffs.get(field) != expected:
            raise GateError(f"release signoffs {field} does not match current candidate")
    if require_testflight:
        if signoffs.get("installation_source") != "TestFlight":
            raise GateError("post-upload signoffs must come from a TestFlight installation")
        if signoffs.get("pending_candidate_sha256") != pending_candidate_sha256:
            raise GateError("post-upload signoffs do not match the tracked pending candidate")
        if signoffs.get("upload_receipt_identifier") != upload_receipt_identifier:
            raise GateError("post-upload signoffs do not match the Apple upload receipt")
    try:
        completed = dt.datetime.fromisoformat(str(signoffs["completed_at"]))
    except (KeyError, ValueError) as exc:
        raise GateError("release signoffs completed_at is invalid") from exc
    if completed.tzinfo is None or completed.utcoffset() is None:
        raise GateError("release signoffs completed_at must include a timezone")
    current_time = now or dt.datetime.now(dt.timezone.utc)
    age = current_time - completed.astimezone(dt.timezone.utc)
    max_age_field = (
        "testflight_signoff_max_age_hours" if require_testflight else "max_age_hours"
    )
    max_age = dt.timedelta(hours=float(registry["release_gate"][max_age_field]))
    if age < dt.timedelta(0) or age > max_age:
        raise GateError(f"release signoffs are older than {max_age}; repeat the manual checks")

    definitions = registry["release_gate"].get(definitions_key)
    expected_ids = [item.get("id") for item in definitions if isinstance(item, dict)] \
        if isinstance(definitions, list) else []
    if expected_ids != list(MANDATORY_RELEASE_SIGNOFFS):
        raise GateError(
            f"release registry {definitions_key} does not match mandatory checks"
        )
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
        if require_testflight and item.get("installation_source") != "TestFlight":
            raise GateError(
                f"post-upload signoff was not performed from TestFlight: {signoff_id}"
            )
        if require_testflight and item.get("pending_candidate_sha256") \
                != pending_candidate_sha256:
            raise GateError(
                f"post-upload signoff pending candidate binding changed: {signoff_id}"
            )
        if require_testflight and item.get("upload_receipt_identifier") \
                != upload_receipt_identifier:
            raise GateError(
                f"post-upload signoff upload receipt binding changed: {signoff_id}"
            )
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
        if minimum_tested_at is not None \
                and tested_utc <= minimum_tested_at.astimezone(dt.timezone.utc):
            raise GateError(
                f"post-upload signoff predates the TestFlight upload: {signoff_id}"
            )

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

    summary = {
        "schema_version": 1,
        "head": head,
        "tree": tree,
        "registry_blob": registry_blob,
        "completed_at": signoffs["completed_at"],
        "items": expected_ids,
        **app_identity,
        "sha256": hashlib.sha256(signoff_path.read_bytes()).hexdigest(),
    }
    if require_testflight:
        summary.update(
            {
                "installation_source": "TestFlight",
                "pending_candidate_sha256": pending_candidate_sha256,
                "upload_receipt_identifier": upload_receipt_identifier,
            }
        )
    return summary


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
    """收集新增、修改、删除、复制和重命名两侧路径，并纳入未跟踪普通文件。"""
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
    """同时检查 tracked/untracked 文件空白错误，避免只检查 Git diff 而漏掉新文件。"""
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
    """把 change impact 和实际测试路径映射为去重后的受影响命令集合。

    如果选择了 backend full，会删除已被其覆盖的 AI/Health focused 命令；测试文件没有
    对应影响域时直接失败，防止新增测试落在门禁之外。
    """
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
    command_ids: list[str] = []
    for domain_id in sorted(requested):
        command_ids.extend(by_id[domain_id]["verification_commands"])
    command_ids.append("diff_check")
    unique = list(dict.fromkeys(command_ids))
    if "backend_full" in unique:
        unique = [
            command_id
            for command_id in unique
            if command_id not in BACKEND_FULL_SUPERSEDES
        ]
    return unique


def command_ids_for_fast(
    registry: dict[str, Any], *, changed_paths: list[str] | None = None
) -> list[str]:
    """Return the bounded daily-development plan; never release evidence."""

    return [
        command_id
        for command_id in command_ids_for_impacted(
            registry,
            changed_paths=changed_paths,
        )
        if command_id not in FAST_EXCLUDED_COMMANDS
    ]


def validate_release_evidence(
    evidence: dict[str, Any],
    registry: dict[str, Any],
    *,
    head: str,
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
    if tuple(evidence) != FINAL_EVIDENCE_KEYS:
        raise GateError(
            "release evidence must use the exact final schema and reject internal fields"
        )
    if type(evidence.get("schema_version")) is not int or evidence["schema_version"] != 5:
        raise GateError("release evidence schema_version must be 5")
    branch = canonical_release_branch(registry)
    if remote_tip != head:
        raise GateError("release evidence official canonical tip does not match candidate HEAD")
    expected_remote_keys = (
        "head_sha",
        "head_branch",
        "workflow_run_id",
        "workflow_run_attempt",
        "workflow_url",
        "check_run_id",
        "check_name",
        "check_app_slug",
        "check_app_id",
        "check_completed_at",
    )
    if tuple(remote_gate) != expected_remote_keys:
        raise GateError("release evidence remote quality gate shape is invalid")
    if remote_gate.get("head_sha") != head or remote_gate.get("head_branch") != branch:
        raise GateError("release evidence remote quality gate is not bound to canonical HEAD")
    for field in ("workflow_run_id", "workflow_run_attempt", "check_run_id", "check_app_id"):
        if type(remote_gate.get(field)) is not int or remote_gate[field] <= 0:
            raise GateError(f"release evidence remote quality gate {field} must be an integer")
    for field in ("workflow_url", "check_name", "check_app_slug", "check_completed_at"):
        if not isinstance(remote_gate.get(field), str) or not remote_gate[field]:
            raise GateError(f"release evidence remote quality gate {field} must be a string")
    if (
        remote_gate["check_name"] != registry["release_gate"]["required_check"]["name"]
        or remote_gate["check_app_slug"]
        != registry["release_gate"]["required_check"]["app_slug"]
        or remote_gate["check_app_id"]
        != registry["release_gate"]["required_check"]["app_id"]
    ):
        raise GateError("release evidence remote quality gate check identity is invalid")
    if tuple(merged_pull_request) != (
        "number",
        "url",
        "merged_at",
        "merge_commit_sha",
        "base_repository",
        "base_branch",
    ):
        raise GateError("release evidence merged pull request shape is invalid")
    if type(merged_pull_request.get("number")) is not int or merged_pull_request["number"] <= 0:
        raise GateError("release evidence merged pull request number must be an integer")
    if any(
        not isinstance(merged_pull_request.get(field), str)
        or not merged_pull_request[field]
        for field in ("url", "merged_at", "merge_commit_sha", "base_repository", "base_branch")
    ):
        raise GateError("release evidence merged pull request fields must be strings")
    if (
        merged_pull_request.get("merge_commit_sha") != head
        or merged_pull_request.get("base_branch") != branch
        or merged_pull_request.get("base_repository") != PINNED_GITHUB_REPOSITORY
    ):
        raise GateError("release evidence merged pull request is not bound to canonical HEAD/base")
    expected_branch_roles = registry["release_gate"]["branch_roles"]["protected_branches"]
    if list(branch_protections) != list(expected_branch_roles):
        raise GateError("release evidence branch protections are missing or reordered")
    for protected_branch, expected_role in expected_branch_roles.items():
        actual_protection = branch_protections.get(protected_branch)
        common = registry["release_gate"]["branch_protection"]
        expected_protection = {
            "required_check": registry["release_gate"]["required_check"]["name"],
            "required_check_app_id": registry["release_gate"]["required_check"]["app_id"],
            "strict": common["strict"],
            "enforce_admins": common["enforce_admins"],
            "allow_force_pushes": common["allow_force_pushes"],
            "allow_deletions": common["allow_deletions"],
            "lock_branch": expected_role["lock_branch"],
            "allow_fork_syncing": expected_role["allow_fork_syncing"],
            "required_pull_request_reviews": common["required_pull_request_reviews"],
        }
        if not _matches_exact_json(actual_protection, expected_protection):
            raise GateError(
                f"release evidence branch role is invalid: {protected_branch}"
            )
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
                if not _matches_exact_json(result.get(field), expected):
                    raise GateError(
                        f"release evidence backend JUnit field changed: {command_id}.{field}"
                    )

    cached_remote = evidence.get("remote_quality_gate")
    if not isinstance(cached_remote, dict):
        raise GateError("release evidence is missing remote_quality_gate")
    if not _matches_exact_json(cached_remote, remote_gate):
        raise GateError("release evidence remote quality gate changed or is incomplete")

    if not _matches_exact_json(evidence.get("merged_pull_request"), merged_pull_request):
        raise GateError("release evidence merged pull request changed or is invalid")
    if not _matches_exact_json(evidence.get("branch_protections"), branch_protections):
        raise GateError("release evidence branch protections changed or are incomplete")
    if not _matches_exact_json(evidence.get("manual_signoffs"), manual_signoffs):
        raise GateError("release evidence manual signoffs changed or are incomplete")
    if not _matches_exact_json(evidence.get("small_simulator"), small_simulator):
        raise GateError("release evidence small simulator identity changed or is invalid")
    if not _matches_exact_json(evidence.get("xcode_toolchain"), xcode_toolchain):
        raise GateError("release evidence Xcode toolchain identity changed or is invalid")
    if not _matches_exact_json(evidence.get("backend_runtime"), backend_runtime):
        raise GateError("release evidence backend runtime identity changed or is invalid")
    if not _matches_exact_json(evidence.get("gate_python"), gate_python):
        raise GateError("release evidence gate Python identity changed or is invalid")


def validate_internal_testflight_evidence(
    evidence: dict[str, Any],
    registry: dict[str, Any],
    *,
    head: str,
    tree: str,
    registry_blob: str,
    remote_tip: str,
    remote_gate: dict[str, Any],
    merged_pull_request: dict[str, Any],
    branch_protections: dict[str, dict[str, Any]],
    small_simulator: dict[str, str],
    xcode_toolchain: dict[str, str],
    backend_runtime: dict[str, Any],
    gate_python: dict[str, str],
    now: dt.datetime | None = None,
) -> None:
    if tuple(evidence) != INTERNAL_EVIDENCE_KEYS:
        raise GateError("internal TestFlight evidence must use the exact internal schema")
    if type(evidence.get("schema_version")) is not int \
            or evidence.get("schema_version") != 1 \
            or evidence.get("phase") != "internal_testflight_upload":
        raise GateError("internal TestFlight evidence must use its dedicated schema 1")
    if "manual_signoffs" in evidence or "external_promotion_allowed" in evidence:
        raise GateError(
            "internal TestFlight evidence must not contain or imply final qualification"
        )
    pending_signoffs = {
        "phase": "post_upload_required",
        "items": list(MANDATORY_RELEASE_SIGNOFFS),
    }
    projected = {
        key: (
            5
            if key == "schema_version"
            else pending_signoffs
            if key == "manual_signoffs"
            else evidence[key]
        )
        for key in FINAL_EVIDENCE_KEYS
    }
    validate_release_evidence(
        projected,
        registry,
        head=head,
        tree=tree,
        registry_blob=registry_blob,
        remote_tip=remote_tip,
        remote_gate=remote_gate,
        merged_pull_request=merged_pull_request,
        branch_protections=branch_protections,
        manual_signoffs=pending_signoffs,
        small_simulator=small_simulator,
        xcode_toolchain=xcode_toolchain,
        backend_runtime=backend_runtime,
        gate_python=gate_python,
        now=now,
    )


def run_gate(mode: str, *, dry_run: bool) -> int:
    """执行 fast、impacted、internal-testflight 或 final release 的阶段状态机。

    fast/impacted 先静态检查和空白检查，再运行选择出的命令并复核工作树未漂移；两个
    发布模式还会绑定官方 main、PR、远端 CI、工具链、签核和证据。dry-run 只打印计划，
    不运行测试，也不会产生可用于发布的证据。
    """
    registry = load_json(REGISTRY_PATH)
    validate_release_registry_identity(registry)
    commands = registry["commands"]
    if mode in {"fast", "impacted"}:
        initial_working_state = worktree_fingerprint() if not dry_run else ""
        planned_command_ids = (
            command_ids_for_fast(registry)
            if mode == "fast"
            else command_ids_for_impacted(registry)
        )
        command_ids = [
            command_id
            for command_id in planned_command_ids
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
        guard_command = "/usr/bin/python3 -I tools/regression_guard.py check --working"
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
        # Reject cheap tracked/untracked whitespace failures before starting
        # expensive backend or Xcode work. Keep the post-run check below as a
        # separate drift guard for files that change while commands execute.
        check_working_tree_whitespace(dry_run=dry_run)
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
        if mode == "fast":
            print(
                "\nFAST DEVELOPMENT CHECK: PASSED; NOT RELEASE EVIDENCE"
                if not dry_run
                else "\nFAST DEVELOPMENT CHECK: DRY RUN OK; NOT RELEASE EVIDENCE"
            )
        else:
            print(
                "\nIMPACTED REGRESSION GATE: PASSED; NOT RELEASE EVIDENCE"
                if not dry_run
                else "\nIMPACTED REGRESSION GATE: DRY RUN OK; NOT RELEASE EVIDENCE"
            )
        return 0

    if mode not in {"release", "internal-testflight"}:
        raise AssertionError(mode)
    internal_testflight = mode == "internal-testflight"
    gate_python = require_trusted_gate_python_runtime()
    require_new_release_build(registry)
    if internal_testflight:
        require_no_pending_internal_candidate(registry)
    required = required_release_commands(registry)
    initial_backend_runtime = backend_runtime_identity()
    canonical_branch = canonical_release_branch(registry)
    if dry_run:
        head = git("rev-parse", "HEAD")
        current_branch = git("branch", "--show-current")
        if current_branch != canonical_branch:
            raise GateError(
                f"{mode} dry-run is only allowed on the canonical branch from the pinned "
                f"registry: required={canonical_branch!r} current={current_branch!r}"
            )
        branch = canonical_branch
    else:
        head, branch = ensure_clean_and_synced(registry)
        initial_xcode_toolchain = require_pinned_xcode_toolchain()
        tree = git("rev-parse", "HEAD^{tree}")
        registry_blob = git("rev-parse", f"HEAD:{REGISTRY_PATH.relative_to(REPO_ROOT)}")
        initial_manual_signoffs = None
        if not internal_testflight:
            initial_manual_signoffs = validate_manual_signoffs(
                registry,
                signoff_path=RELEASE_SIGNOFF_PATH,
                head=head,
                tree=tree,
                registry_blob=registry_blob,
            )
        ensure_official_remote_tip(head, registry)
        initial_remote_gate = require_remote_quality_gate(head, registry)
        initial_merged_pull_request = require_merged_pull_request(head, registry)
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
        label = "INTERNAL TESTFLIGHT UPLOAD GATE" if internal_testflight \
            else "RELEASE REGRESSION GATE"
        print(f"\n{label}: DRY RUN OK")
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
    remote_tip = ensure_official_remote_tip(head, registry)
    remote_gate = require_remote_quality_gate(head, registry)
    if remote_gate != initial_remote_gate:
        raise GateError("remote quality-gate identity changed while the full gate was running")
    merged_pull_request = require_merged_pull_request(head, registry)
    if merged_pull_request != initial_merged_pull_request:
        raise GateError("merged pull request identity changed while the full gate was running")
    branch_protections = require_all_branch_protections(
        registry,
        expected_app_id=remote_gate["check_app_id"],
    )
    if branch_protections != initial_branch_protections:
        raise GateError("branch protections changed while the full gate was running")
    manual_signoffs = None
    if not internal_testflight:
        manual_signoffs = validate_manual_signoffs(
            registry,
            signoff_path=RELEASE_SIGNOFF_PATH,
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
        "schema_version": 1 if internal_testflight else 5,
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
        "small_simulator": small_simulator,
        "xcode_toolchain": xcode_toolchain,
        "backend_runtime": backend_runtime,
        "gate_python": gate_python,
    }
    if internal_testflight:
        evidence = {"schema_version": 1, "phase": "internal_testflight_upload", **{
            key: value for key, value in evidence.items() if key != "schema_version"
        }}
        evidence_path = INTERNAL_TESTFLIGHT_EVIDENCE_PATH
        label = "INTERNAL TESTFLIGHT UPLOAD GATE"
    else:
        evidence["manual_signoffs"] = manual_signoffs
        evidence_path = EVIDENCE_PATH
        label = "RELEASE REGRESSION GATE"
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"\n{label}: PASSED; evidence={evidence_path.relative_to(REPO_ROOT)}")
    return 0


def assert_release() -> int:
    """在最终归档前即时复核 schema 5 证据和所有可变外部状态仍与候选一致。"""
    registry = load_json(REGISTRY_PATH)
    validate_release_registry_identity(registry)
    require_new_release_build(registry)
    evidence = load_json(EVIDENCE_PATH)
    head, branch = ensure_clean_and_synced(registry)
    remote_tip = ensure_official_remote_tip(head, registry)
    remote_gate = require_remote_quality_gate(head, registry)
    merged_pull_request = require_merged_pull_request(head, registry)
    branch_protections = require_all_branch_protections(
        registry,
        expected_app_id=remote_gate["check_app_id"],
    )
    tree = git("rev-parse", "HEAD^{tree}")
    registry_blob = git("rev-parse", f"HEAD:{REGISTRY_PATH.relative_to(REPO_ROOT)}")
    manual_signoffs = validate_manual_signoffs(
        registry,
        signoff_path=RELEASE_SIGNOFF_PATH,
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


def assert_internal_testflight() -> int:
    """在 TestFlight 脚本三个关键边界即时复核 schema 1 上传资格。"""
    registry = load_json(REGISTRY_PATH)
    validate_release_registry_identity(registry)
    require_new_release_build(registry)
    require_no_pending_internal_candidate(registry)
    evidence = load_json(INTERNAL_TESTFLIGHT_EVIDENCE_PATH)
    head, _branch = ensure_clean_and_synced(registry)
    remote_tip = ensure_official_remote_tip(head, registry)
    remote_gate = require_remote_quality_gate(head, registry)
    merged_pull_request = require_merged_pull_request(head, registry)
    branch_protections = require_all_branch_protections(
        registry,
        expected_app_id=remote_gate["check_app_id"],
    )
    tree = git("rev-parse", "HEAD^{tree}")
    registry_blob = git("rev-parse", f"HEAD:{REGISTRY_PATH.relative_to(REPO_ROOT)}")
    small_simulator = small_simulator_identity()
    xcode_toolchain = require_pinned_xcode_toolchain()
    backend_runtime = backend_runtime_identity()
    gate_python = require_trusted_gate_python_runtime()
    validate_internal_testflight_evidence(
        evidence,
        registry,
        head=head,
        tree=tree,
        registry_blob=registry_blob,
        remote_tip=remote_tip,
        remote_gate=remote_gate,
        merged_pull_request=merged_pull_request,
        branch_protections=branch_protections,
        small_simulator=small_simulator,
        xcode_toolchain=xcode_toolchain,
        backend_runtime=backend_runtime,
        gate_python=gate_python,
    )
    print(f"INTERNAL TESTFLIGHT UPLOAD GATE: valid for {head[:12]}")
    return 0


def _write_new_local_evidence(path: Path, payload: dict[str, Any]) -> None:
    parent = path.parent
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    parent_metadata = parent.lstat()
    if not stat.S_ISDIR(parent_metadata.st_mode) or stat.S_ISLNK(parent_metadata.st_mode):
        raise GateError(f"local evidence parent must be a real directory: {parent}")
    if path.exists() or path.is_symlink():
        raise GateError(f"refusing to overwrite existing local evidence: {path}")
    temporary = parent / f".{path.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp"
    descriptor = -1
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        encoded = (
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8")
        offset = 0
        while offset < len(encoded):
            offset += os.write(descriptor, encoded[offset:])
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.link(temporary, path, follow_symlinks=False)
        os.unlink(temporary)
    except OSError as exc:
        raise GateError(f"cannot atomically create local evidence {path}: {exc}") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def qualify_testflight() -> int:
    """在 Apple 接受上传后校验回执绑定签核，并原子写入该 build 的资格结果。"""
    registry = load_json(REGISTRY_PATH)
    validate_release_registry_identity(registry)
    pending = pending_internal_candidate(registry)
    pending_sha256 = _sha256_json(pending)
    uploaded_at = _parse_timezone_datetime(
        pending["uploaded_at"], label="pending internal candidate uploaded_at"
    )
    current_head, _branch = ensure_clean_and_synced(registry)
    current_remote_tip = ensure_official_remote_tip(current_head, registry)
    current_remote_gate = require_remote_quality_gate(current_head, registry)
    current_merged_pull_request = require_merged_pull_request(current_head, registry)
    candidate_tree = git("rev-parse", f"{pending['head']}^{{tree}}")
    if candidate_tree != pending["tree"]:
        raise GateError("tracked pending candidate tree does not match its Git object")
    candidate_registry_blob = git(
        "rev-parse",
        f"{pending['head']}:{REGISTRY_PATH.relative_to(REPO_ROOT)}",
    )
    if candidate_registry_blob != pending["registry_blob"]:
        raise GateError(
            "tracked pending candidate registry blob does not match its Git object"
        )
    candidate_project_source = git(
        "show",
        f"{pending['head']}:Xjie/Xjie.xcodeproj/project.pbxproj",
    )
    candidate_project_identity = project_version_identity_from_source(
        candidate_project_source,
        label="tracked pending Xcode project",
    )
    if candidate_project_identity != {
        "app_version": pending["app_version"],
        "app_build": pending["app_build"],
    }:
        raise GateError(
            "tracked pending candidate version/build does not match its Xcode project"
        )
    candidate_remote_gate = require_remote_quality_gate(pending["head"], registry)
    candidate_merged_pull_request = require_merged_pull_request(pending["head"], registry)
    branch_protections = require_all_branch_protections(
        registry,
        expected_app_id=current_remote_gate["check_app_id"],
    )
    signoffs = validate_manual_signoffs(
        registry,
        signoff_path=TESTFLIGHT_SIGNOFF_PATH,
        head=pending["head"],
        tree=pending["tree"],
        registry_blob=pending["registry_blob"],
        candidate_identity={
            "app_version": pending["app_version"],
            "app_build": pending["app_build"],
        },
        definitions_key="post_upload_signoffs",
        minimum_tested_at=uploaded_at,
        require_testflight=True,
        pending_candidate_sha256=pending_sha256,
        upload_receipt_identifier=pending_upload_receipt_identifier(pending),
    )
    external_promotion_allowed = (
        pending["upload"]["method"] == "verified_local_ipa_altool"
        and re.fullmatch(
            r"[0-9a-f]{64}", str(pending["upload"].get("ipa_sha256", ""))
        ) is not None
        and re.fullmatch(
            r"[0-9a-f]{40,64}",
            str(pending["upload"].get("distribution_cdhash", "")),
        ) is not None
    )
    qualification = {
        "schema_version": 1,
        "phase": "post_upload_testflight_qualification",
        "qualification_head": current_head,
        "qualification_remote_tip": current_remote_tip,
        "qualification_remote_quality_gate": current_remote_gate,
        "qualification_merged_pull_request": current_merged_pull_request,
        "completed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "pending_candidate_sha256": pending_sha256,
        "pending_candidate": pending,
        "candidate_git_identity": {
            "tree": candidate_tree,
            "registry_blob": candidate_registry_blob,
            **candidate_project_identity,
        },
        "candidate_remote_quality_gate": candidate_remote_gate,
        "candidate_merged_pull_request": candidate_merged_pull_request,
        "branch_protections": branch_protections,
        "manual_signoffs": signoffs,
        "internal_testflight_qualified": True,
        "external_promotion_allowed": external_promotion_allowed,
        "qualification_scope": (
            "same_verified_ipa_external_candidate"
            if external_promotion_allowed
            else "internal_testflight_only_missing_local_ipa_identity"
        ),
    }
    qualification_path = testflight_qualification_path(pending)
    _write_new_local_evidence(qualification_path, qualification)
    print(
        "TESTFLIGHT QUALIFICATION: INTERNAL PASSED; "
        f"candidate={pending['app_version']}({pending['app_build']}) "
        f"external_promotion_allowed={str(external_promotion_allowed).lower()} "
        f"evidence={qualification_path.relative_to(REPO_ROOT)}"
    )
    return 0


# ---------------------------------------------------------------------------
# 默认轻量门禁
# ---------------------------------------------------------------------------
def _run_light_process(
    label: str,
    arguments: list[str],
    *,
    dry_run: bool,
    environment: dict[str, str] | None = None,
) -> None:
    """运行一个轻量检查，并保留真实退出码；dry-run 只展示计划。"""

    print(f"\n[{label}] {shlex.join(arguments)}", flush=True)
    if dry_run:
        return
    result = subprocess.run(
        arguments,
        cwd=REPO_ROOT,
        env=environment or trusted_subprocess_environment(),
        check=False,
    )
    if result.returncode != 0:
        raise GateError(f"lightweight check failed: {label}")


def _validate_light_configuration() -> None:
    """只验证轻量门禁会直接消费的 JSON，不执行旧 registry 的精确摘要合同。"""

    for relative in (
        "quality/change_impact.json",
        "quality/regression_contracts.json",
        "quality/expected_xctests.json",
        "quality/expected_python_tests.json",
        "quality/swift_source_manifest.json",
        "backend/deploy/production_container.json",
    ):
        path = REPO_ROOT / relative
        if path.exists():
            load_json(path)


def _write_light_evidence(path: Path, payload: dict[str, Any]) -> None:
    """原子替换轻量证据；其独立文件名保证不会冒充 strict evidence。"""

    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.is_symlink():
        raise GateError(f"lightweight evidence path must not be a symlink: {path}")
    temporary = path.parent / f".{path.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp"
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.chmod(0o600)
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _light_candidate_identity(mode: str) -> dict[str, Any]:
    """发布类轻量门禁只绑定本地 clean main，不进行旧 strict 的远端/签核复核。"""

    branch = git("branch", "--show-current")
    if branch != "main":
        raise GateError(f"{mode} lightweight gate requires branch 'main'; current={branch!r}")
    if git("status", "--porcelain"):
        raise GateError(f"{mode} lightweight gate requires a clean working tree")
    return {
        "head": git("rev-parse", "HEAD"),
        "tree": git("rev-parse", "HEAD^{tree}"),
        "branch": branch,
    }


def run_light_gate(mode: str, *, dry_run: bool) -> int:
    """执行默认低成本门禁，不运行完整 XCTest/backend/PG/Archive 清单。"""

    if mode not in {"fast", "impacted", "release", "internal-testflight"}:
        raise AssertionError(mode)
    print(
        "LIGHTWEIGHT GATE: complete XCTest/backend/PG/archive checks are skipped; "
        "use --strict for the preserved comprehensive gate."
    )
    print("[excluded] " + ", ".join(LIGHT_EXCLUDED_COMMANDS))
    initial_working_state = worktree_fingerprint() if not dry_run else ""
    check_working_tree_whitespace(dry_run=dry_run)
    if not dry_run:
        _validate_light_configuration()

    python_environment = trusted_subprocess_environment()
    python_environment["PYTHONPYCACHEPREFIX"] = "/tmp/xjie-light-pycache"
    _run_light_process(
        "gate_python_syntax",
        [
            "/usr/bin/python3",
            "-m",
            "py_compile",
            "tools/run_regression_gate.py",
            "tools/regression_guard.py",
            "tools/validate_xcresult.py",
            "tools/verify_release_bundle.py",
        ],
        dry_run=dry_run,
        environment=python_environment,
    )
    _run_light_process(
        "hook_shell_syntax",
        ["/bin/sh", "-n", ".githooks/pre-commit", ".githooks/pre-push"],
        dry_run=dry_run,
    )
    _run_light_process(
        "release_shell_syntax",
        ["/bin/zsh", "-f", "-n", "scripts/release_testflight.sh"],
        dry_run=dry_run,
    )

    if mode != "fast":
        _run_light_process(
            "python_source_compile",
            [
                "/usr/bin/python3",
                "-m",
                "compileall",
                "-q",
                "backend/app",
                "tools",
            ],
            dry_run=dry_run,
            environment=python_environment,
        )
        _run_light_process(
            "ios_debug_compile",
            [
                "xcodebuild",
                "build",
                "-quiet",
                "-project",
                "Xjie/Xjie.xcodeproj",
                "-scheme",
                "Xjie",
                "-configuration",
                "Debug",
                "-destination",
                "generic/platform=iOS Simulator",
                "-derivedDataPath",
                "/tmp/xjie-light-derived",
                "CODE_SIGNING_ALLOWED=NO",
                "CODE_SIGNING_REQUIRED=NO",
            ],
            dry_run=dry_run,
        )

    check_working_tree_whitespace(dry_run=dry_run)
    if not dry_run:
        ensure_working_state_unchanged(initial_working_state)

    if mode in {"release", "internal-testflight"} and not dry_run:
        identity = _light_candidate_identity(mode)
        evidence_path = (
            LIGHT_INTERNAL_TESTFLIGHT_EVIDENCE_PATH
            if mode == "internal-testflight"
            else LIGHT_RELEASE_EVIDENCE_PATH
        )
        _write_light_evidence(
            evidence_path,
            {
                "schema_version": 1,
                "profile": "lightweight",
                "mode": mode,
                **identity,
                "completed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                "excluded_commands": list(LIGHT_EXCLUDED_COMMANDS),
            },
        )
        print(f"LIGHTWEIGHT EVIDENCE: {evidence_path.relative_to(REPO_ROOT)}")

    label = mode.upper().replace("-", " ")
    suffix = "DRY RUN OK" if dry_run else "PASSED"
    print(f"\n{label} LIGHTWEIGHT GATE: {suffix}; NOT STRICT REGRESSION EVIDENCE")
    return 0


def assert_light_gate(mode: str) -> int:
    """即时确认轻量 evidence 仍绑定当前 clean main；不检查 strict 人工签核。"""

    path = (
        LIGHT_INTERNAL_TESTFLIGHT_EVIDENCE_PATH
        if mode == "internal-testflight"
        else LIGHT_RELEASE_EVIDENCE_PATH
    )
    evidence = load_json(path)
    if evidence.get("profile") != "lightweight" or evidence.get("mode") != mode:
        raise GateError(f"invalid {mode} lightweight evidence")
    identity = _light_candidate_identity(mode)
    for key in ("head", "tree", "branch"):
        if evidence.get(key) != identity[key]:
            raise GateError(f"{mode} lightweight evidence no longer matches {key}")
    print(
        f"{mode.upper().replace('-', ' ')} LIGHTWEIGHT GATE: valid for "
        f"{identity['head'][:12]}; NOT STRICT REGRESSION EVIDENCE"
    )
    return 0


def qualify_light_testflight() -> int:
    """轻量资格只复核候选绑定；真实设备/人工结论由操作者另行记录。"""

    assert_light_gate("internal-testflight")
    print(
        "TESTFLIGHT LIGHTWEIGHT QUALIFICATION: candidate binding passed; "
        "real-device, HealthKit, accessibility, keyboard and live-AI sign-offs were not checked"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    """声明唯一受支持的阶段命令，避免任意字符串绕过状态机。"""
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("fast", "impacted", "release", "internal-testflight"):
        item = subparsers.add_parser(command)
        item.add_argument("--dry-run", action="store_true")
        item.add_argument("--strict", action="store_true")
    for command in ("assert-release", "assert-internal-testflight", "qualify-testflight"):
        item = subparsers.add_parser(command)
        item.add_argument("--strict", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    """统一建立信任边界和进程锁，再分派阶段；所有 GateError 均返回退出码 1。"""
    args = build_parser().parse_args(argv)
    try:
        ensure_no_git_repository_redirects()
        ensure_no_network_verification_redirects()
        require_trusted_gate_python_runtime()
        with gate_lock():
            ensure_canonical_repository_without_replace_refs()
            ensure_safe_repository_configuration()
            strict_requested = args.strict or os.environ.get("XJIE_STRICT_GATES") == "1"
            if args.command in {"fast", "impacted", "release", "internal-testflight"}:
                if strict_requested:
                    return run_gate(args.command, dry_run=args.dry_run)
                return run_light_gate(args.command, dry_run=args.dry_run)
            if args.command == "assert-release":
                return assert_release() if strict_requested else assert_light_gate("release")
            if args.command == "assert-internal-testflight":
                return (
                    assert_internal_testflight()
                    if strict_requested
                    else assert_light_gate("internal-testflight")
                )
            if args.command == "qualify-testflight":
                return qualify_testflight() if strict_requested else qualify_light_testflight()
            raise AssertionError(args.command)
    except GateError as exc:
        print(f"REGRESSION GATE: FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
