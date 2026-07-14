#!/usr/bin/env python3
"""Static regression-prevention gate for XJie iOS XAGE.

The guard intentionally uses only the Python standard library so it can run in
Git hooks and CI before project dependencies are installed.
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / "quality" / "regression_contracts.json"
MANIFEST_PATH = REPO_ROOT / "quality" / "change_impact.json"
MANIFEST_REPO_PATH = "quality/change_impact.json"
DEVELOPMENT_RECORDS_PATH = REPO_ROOT / "development_records.json"
DEVELOPMENT_RECORDS_REPO_PATH = "development_records.json"
SIGNOFF_TEMPLATE_PATH = REPO_ROOT / "quality" / "release_signoffs.example.json"
PROJECT_FILE_PATH = REPO_ROOT / "Xjie" / "Xjie.xcodeproj" / "project.pbxproj"
SHARED_SCHEME_PATH = (
    REPO_ROOT / "Xjie" / "Xjie.xcodeproj" / "xcshareddata" / "xcschemes" / "Xjie.xcscheme"
)
EXPECTED_PYTHON_TESTS_PATH = REPO_ROOT / "quality" / "expected_python_tests.json"
EXPECTED_PYTHON_TEST_PROFILES = ("backend_full", "tools")
EXPECTED_XCTESTS_PATH = REPO_ROOT / "quality" / "expected_xctests.json"
EXPECTED_XCTEST_PROFILES = ("ios_unit", "ios_ui_full", "ios_ui_small", "ios_all")
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
PINNED_LATEST_UPLOADED_BUILD = 17
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
MANDATORY_PROCESS_SOURCE_PATTERNS = {
    ".github/workflows/*.yml",
    ".github/workflows/*.yaml",
    ".githooks/*",
    "scripts/release_testflight.sh",
    "scripts/ExportOptions-TestFlight.plist",
    "tools/validate_xcresult.py",
    "tools/python_test_gate.py",
    "tools/verify_release_bundle.py",
    "tools/regression_guard.py",
    "tools/run_regression_gate.py",
    "tools/generate_development_history.py",
    "quality/regression_contracts.json",
    "quality/expected_python_tests.json",
    "quality/expected_xctests.json",
    "quality/release_signoffs.example.json",
    ".gitignore",
    "AGENTS.md",
    "docs/quality/REGRESSION_POLICY.md",
}
MANDATORY_TEST_INTEGRITY_PATTERNS = {
    "backend/tests/**/*.py",
    "tools/tests/**/*.py",
    "Xjie/XjieTests/**/*.swift",
    "Xjie/XjieUITests/**/*.swift",
    "backend/pyproject.toml",
    ".github/workflows/*.yml",
    ".github/workflows/*.yaml",
    "tools/python_test_gate.py",
    "tools/validate_xcresult.py",
    "tools/regression_guard.py",
    "tools/run_regression_gate.py",
    "quality/regression_contracts.json",
    "quality/expected_python_tests.json",
    "quality/expected_xctests.json",
}
MANDATORY_BACKEND_CORE_SOURCE_PATTERNS = {
    "backend/app/**",
    "backend/app/db/migrations/**/*.py",
    "Dockerfile",
    ".dockerignore",
    "alembic.ini",
    "docker-compose*.yml",
    "docker-compose*.yaml",
    "compose*.yml",
    "compose*.yaml",
    "backend/Dockerfile",
    "backend/.dockerignore",
    "backend/.env.example",
    "backend/alembic.ini",
    "backend/pyproject.toml",
    "backend/requirements*.txt",
    "backend/static/**",
    "backend/deploy/**",
    "backend/docker-compose*.yml",
    "backend/docker-compose*.yaml",
    "backend/compose*.yml",
    "backend/compose*.yaml",
    "scripts/deploy_*.sh",
    "tools/xjie_dashboard_api.py",
}
MANDATORY_BACKEND_MIGRATION_SOURCE_PATTERNS = {
    "backend/app/db/migrations/versions/*.py",
}
PINNED_DOMAIN_REQUIRED_CONTRACT_IDS = {
    "ios_ui_interaction": (
        "UX-NAV-001",
        "UX-KEYBOARD-001",
        "UX-CHAT-QUIESCENCE-001",
        "UX-ACCESSIBILITY-001",
        "UX-FORM-001",
        "DATA-CARD-001",
        "TEST-DETERMINISM-001",
    ),
    "ios_chat_client": (
        "UX-KEYBOARD-001",
        "UX-CHAT-QUIESCENCE-001",
        "CHAT-SESSION-001",
        "AI-EVIDENCE-001",
        "TEST-DETERMINISM-001",
    ),
    "ios_health_client": (
        "DATA-CARD-001",
        "HEALTH-REGISTRY-001",
        "HEALTH-ACCOUNT-001",
        "TEST-DETERMINISM-001",
    ),
    "ios_account_client": (
        "UX-FORM-001",
        "TEST-DETERMINISM-001",
    ),
    "ios_project_release": ("RELEASE-GATE-001",),
    "ios_core": ("TEST-DETERMINISM-001",),
    "quality_process_gate": (
        "RELEASE-GATE-001",
        "PROCESS-GATE-001",
    ),
    "test_suite_integrity": ("TEST-SUITE-INTEGRITY-001",),
    "backend_chat_ai": (
        "CHAT-SESSION-001",
        "AI-SUBJECT-001",
        "AI-SAFETY-001",
        "AI-EVIDENCE-001",
    ),
    "backend_health_sync": (
        "HEALTH-REGISTRY-001",
        "HEALTH-ACCOUNT-001",
    ),
    "backend_core": ("BACKEND-CORE-001",),
}
PINNED_CONTRACT_DEFINITION_SHA256 = {
    "UX-NAV-001": "3d78f17eb28926992f98c2dbcd0c25c449f22140979ef5045629094fe64832fd",
    "UX-KEYBOARD-001": "311231cc1455f4f1916eed37ce0a76bc037706b01632b309444809d833492ac9",
    "UX-CHAT-QUIESCENCE-001": "3e094e92fd1875d54887abd9f988a5b320538b9922b90c233ecd81e0806fbe90",
    "UX-ACCESSIBILITY-001": "18a95a3fdd76f0d396f39175eee7f7a2cee0023e37d04624ac708724dc473f29",
    "UX-FORM-001": "a511ba265be7d7470bd67fddb9fa88dc1b11cf8d572bddfb3854d11cd70f7738",
    "DATA-CARD-001": "cc0e768156f89a2a0f6f8a2a11c0acc58809b828ca57f86a59775095955dbc7c",
    "CHAT-SESSION-001": "ece8d46ff6261869f46a45cc0e19b7de8122971626028291f60997f9cd8540a2",
    "AI-SUBJECT-001": "ab439bbc57e438f4259adbd8f7cf01e118301569b301fc05ac909f2af550bb0d",
    "AI-SAFETY-001": "49f29f6b03b04a49984f1c0c40488eb214e4d99ddaa13bc15fb12466b2ba3d97",
    "AI-EVIDENCE-001": "acf45194fd9b8777cf6be0e6c89e791684fa5becbe93663484447be650c861bd",
    "HEALTH-REGISTRY-001": "5f38a4fc14b01e109a7abb7f9da4fd7b09aadf0068a6a9897d58927f7f5df636",
    "HEALTH-ACCOUNT-001": "44554c82ce660f13a5212d43ff84d80851b8896edadbd32e67e35828c19a6646",
    "BACKEND-CORE-001": "d7ba39877e75b24a3b0735324944a520bfe85f9e0ceb8f3b4286a38afd154ee8",
    "TEST-SUITE-INTEGRITY-001": "8a93bd9943750aa9fbe05ba08fc9c95f6590d211ce09eddcd548b0aceb280b78",
    "TEST-DETERMINISM-001": "d38d25d412739b96e098527aa07fe2810187b438e3065ceb5823a47763085d7c",
    "RELEASE-GATE-001": "f7c7f3eb22768b330a6a473e750abb3f112da08d0b550e465490eb70aed77714",
    "PROCESS-GATE-001": "47e7358fbc2eb697bb5214931526994ee456df0129946041c4b56b176c3ad731",
}
PINNED_REGRESSION_REGISTRY_SHA256 = (
    "0d7e26e7f927f1ec6c507ae589beef52e0398ea0546c08606a9ea528726d7f9f"
)
SESSION_CONSTRUCTOR_PATTERN = re.compile(
    r"\b(?:Foundation\s*\.\s*)?URLSession\s*(?:\.\s*init\s*)?\(",
    re.MULTILINE,
)
INFERRED_SESSION_CONSTRUCTOR_PATTERN = re.compile(
    r":\s*(?:Foundation\s*\.\s*)?URLSession\s*=\s*"
    r"(?:\.\s*init\s*\(|\.\s*shared\b)",
    re.MULTILINE,
)
CONTEXTUAL_CONFIGURATION_INIT_PATTERN = re.compile(
    r"\.\s*init\s*\(\s*configuration\s*:",
    re.MULTILINE,
)
SESSION_SHARED_PATTERN = re.compile(r"\bURLSession\s*\.\s*shared\b", re.MULTILINE)
SESSION_ALIAS_PATTERN = re.compile(
    r"\btypealias\s+[A-Za-z_]\w*\s*=\s*(?:Foundation\s*\.\s*)?URLSession\b"
    r"|\b(?:Foundation\s*\.\s*)?URLSession\s*\.\s*self\b",
    re.MULTILINE,
)
API_SERVICE_SHADOW_PATTERN = re.compile(
    r"\b(?:let|var|for)\s+APIService\b"
    r"|\bcase\s+(?:let|var)\s+APIService\b"
    r"|\b(?:typealias|class|struct|enum|protocol|actor)\s+APIService\b"
    r"|(?:^|[,(])\s*APIService\s*:"
    r"|\bAPIService\s+in\b",
    re.MULTILINE,
)
LOCAL_FILE_READ_PATTERN = re.compile(
    r"\b(?:Foundation\s*\.\s*)?Data\s*(?:\.\s*init\s*)?\(\s*contentsOf\s*:",
    re.MULTILINE,
)
SESSION_REQUEST_PATTERN = re.compile(
    r"\.\s*(?:data|bytes)\s*\(\s*(?:for|from)\s*:"
    r"|\.\s*(?:dataTask|downloadTask|uploadTask|streamTask|webSocketTask)\s*\(",
    re.MULTILINE,
)
APPROVED_SESSION_REQUEST_PATTERN = re.compile(
    r"\bAPIService\s*\.\s*shared\s*\.\s*trustedSession\s*"
    r"\.\s*(?:data|bytes)\s*\(\s*(?:for|from)\s*:",
    re.MULTILINE,
)
APPROVED_API_SERVICE_REQUEST_PATTERN = re.compile(
    r"\bself\s*\.\s*trustedSession\s*\.\s*"
    r"(?:data|bytes)\s*\(\s*(?:for|from)\s*:",
    re.MULTILINE,
)
DIRECT_NETWORK_BYPASS_PATTERNS = (
    (
        re.compile(
            r"\b(?:Foundation\s*\.\s*)?"
            r"(?:NSData|NSString|String|NSArray|NSDictionary)\s*"
            r"(?:\.\s*init\s*)?\(\s*contentsOf\s*:",
            re.MULTILINE,
        ),
        "URL-backed Foundation contents loader",
    ),
    (
        re.compile(r"\.\s*init\s*\(\s*contentsOf\s*:", re.MULTILINE),
        "inferred URL contents loader",
    ),
    (
        re.compile(
            r"\btypealias\s+[A-Za-z_]\w*\s*=\s*"
            r"(?:Foundation\s*\.\s*)?(?:Data|NSData|String)\b",
            re.MULTILINE,
        ),
        "aliased URL contents loader type",
    ),
    (
        re.compile(
            r"\blet\s+([A-Za-z_]\w*)\s*=\s*"
            r"(?:Foundation\s*\.\s*)?(?:Data|NSData|String)\s*\.\s*self\b"
            r"[\s\S]{0,500}?\b\1\s*\.\s*init\s*\(\s*contentsOf\s*:",
            re.MULTILINE,
        ),
        "indirect URL contents loader constructor",
    ),
    (re.compile(r"\bAsyncImage\s*\(", re.MULTILINE), "SwiftUI AsyncImage"),
    (
        re.compile(r"\b(?:AVPlayer|AVURLAsset|AVAsset)\s*\(\s*url\s*:", re.MULTILINE),
        "AVFoundation URL transport",
    ),
    (
        re.compile(r"\bSFSafariViewController\s*\(", re.MULTILINE),
        "SafariServices transport",
    ),
    (re.compile(r"\bWKWebView\b|\bimport\s+WebKit\b", re.MULTILINE), "WebKit"),
    (
        re.compile(
            r"\b(?:NWConnection|NWConnectionGroup|NWBrowser|NWTCPConnection)\b",
            re.MULTILINE,
        ),
        "Network.framework direct connection",
    ),
    (
        re.compile(r"\bnw_[A-Za-z0-9_]+\b", re.MULTILINE),
        "Network.framework C API",
    ),
    (
        re.compile(r"\b(?:NSURLSession|NSURLConnection)\b", re.MULTILINE),
        "legacy Foundation network transport",
    ),
    (
        re.compile(
            r"\b(?:CFNetwork|CFHTTP[A-Za-z0-9_]*|CFHost[A-Za-z0-9_]*|"
            r"CFNetService[A-Za-z0-9_]*|CFReadStream[A-Za-z0-9_]*|"
            r"CFWriteStream[A-Za-z0-9_]*|CFStream[A-Za-z0-9_]*|"
            r"CFSocket[A-Za-z0-9_]*)\b",
            re.MULTILINE,
        ),
        "CFNetwork/socket transport",
    ),
    (
        re.compile(
            r"\bStream\s*\.\s*getStreamsToHost\b"
            r"|\bInputStream\s*\(\s*url\s*:",
            re.MULTILINE,
        ),
        "Foundation stream transport",
    ),
    (
        re.compile(
            r"\b(?:Darwin\s*\.\s*)?(?:socket|connect|getaddrinfo)\b",
            re.MULTILINE,
        ),
        "POSIX socket transport",
    ),
)
APPROVED_API_SERVICE_PATH = "Services/APIService.swift"
APPROVED_LOCAL_FILE_LOADER_PATH = "Utils/Utils.swift"
PINNED_SYSTEM_CONSTRUCTORS = (
    (
        re.compile(r"\bNWPathMonitor\s*\(", re.MULTILINE),
        "Utils/NetworkMonitor.swift",
        "NWPathMonitor",
    ),
    (
        re.compile(r"\bHKHealthStore\s*\(", re.MULTILINE),
        "ViewModels/AppleHealthSyncViewModel.swift",
        "HKHealthStore",
    ),
    (
        re.compile(
            r"\bUNUserNotificationCenter\s*\.\s*current\b",
            re.MULTILINE,
        ),
        "Services/PushNotificationManager.swift",
        "UNUserNotificationCenter.current",
    ),
)


def _swift_static_code(source: str) -> str:
    """Mask Swift comments/string text while retaining executable interpolation."""

    output = list(source)

    def mask(start: int, end: int) -> None:
        for index in range(start, end):
            if output[index] not in {"\n", "\r"}:
                output[index] = " "

    index = 0
    length = len(source)
    while index < length:
        if source.startswith("//", index):
            end = source.find("\n", index + 2)
            end = length if end < 0 else end
            mask(index, end)
            index = end
            continue
        if source.startswith("/*", index):
            start = index
            depth = 1
            index += 2
            while index < length and depth:
                if source.startswith("/*", index):
                    depth += 1
                    index += 2
                elif source.startswith("*/", index):
                    depth -= 1
                    index += 2
                else:
                    index += 1
            mask(start, index)
            continue

        hash_count = 0
        while index + hash_count < length and source[index + hash_count] == "#":
            hash_count += 1
        quote_index = index + hash_count
        if quote_index < length and source[quote_index] == '"':
            start = index
            quote_count = 3 if source.startswith('"""', quote_index) else 1
            closing = '"' * quote_count + "#" * hash_count
            interpolation = "\\" + "#" * hash_count + "("
            index = quote_index + quote_count
            interpolation_ranges: list[tuple[int, int]] = []
            ambiguous_expression_start: int | None = None
            while index < length:
                if source.startswith(closing, index):
                    index += len(closing)
                    break
                if source.startswith(interpolation, index):
                    expression_start = index + len(interpolation)
                    expression_end = _swift_interpolation_end(source, expression_start)
                    if expression_end is None:
                        # A lexer ambiguity must expose the remaining source to
                        # the deny patterns, never hide potentially executable
                        # code behind an unterminated/unsupported interpolation.
                        ambiguous_expression_start = expression_start
                        index = length
                        break
                    interpolation_ranges.append((expression_start, expression_end))
                    index = expression_end + 1
                    continue
                if hash_count == 0 and quote_count == 1 and source[index] == "\\":
                    index = min(length, index + 2)
                else:
                    index += 1
            mask(start, index)
            if ambiguous_expression_start is not None:
                output[ambiguous_expression_start:length] = source[
                    ambiguous_expression_start:length
                ]
            else:
                for expression_start, expression_end in interpolation_ranges:
                    output[expression_start:expression_end] = _swift_static_code(
                        source[expression_start:expression_end]
                    )
            continue
        index += 1
    masked = "".join(output)
    return re.sub(
        r"`([A-Za-z_]\w*)`",
        lambda match: " " + match.group(1) + " ",
        masked,
    )


def _swift_regex_literal_end(
    source: str,
    start: int,
    expression_start: int,
) -> tuple[bool, int | None]:
    """Recognize a Swift bare/raw regex and return its end, fail-closed."""

    hash_count = 0
    while start + hash_count < len(source) and source[start + hash_count] == "#":
        hash_count += 1
    slash_index = start + hash_count
    if slash_index >= len(source) or source[slash_index] != "/":
        return False, None
    if hash_count == 0:
        prefix = source[expression_start:start].rstrip()
        if prefix and prefix[-1] not in "([{=,:;!?&|+-*%^~<>":
            if re.search(r"\b(?:return|throw|case|in|where|try|await)\s*$", prefix) is None:
                return False, None

    closing = "/" + "#" * hash_count
    interpolation = "\\" + "#" * hash_count + "("
    index = slash_index + 1
    in_character_class = False
    while index < len(source):
        if source.startswith(interpolation, index):
            nested_start = index + len(interpolation)
            nested_end = _swift_interpolation_end(source, nested_start)
            if nested_end is None:
                return True, None
            index = nested_end + 1
            continue
        if source[index] == "\\":
            index = min(len(source), index + 2)
            continue
        if source[index] == "[":
            in_character_class = True
            index += 1
            continue
        if source[index] == "]" and in_character_class:
            in_character_class = False
            index += 1
            continue
        if not in_character_class and source.startswith(closing, index):
            return True, index + len(closing)
        index += 1
    return True, None


def _swift_interpolation_end(source: str, expression_start: int) -> int | None:
    """Return the closing parenthesis for one Swift string interpolation."""

    depth = 1
    index = expression_start
    length = len(source)
    while index < length:
        if source.startswith("//", index):
            end = source.find("\n", index + 2)
            index = length if end < 0 else end
            continue
        if source.startswith("/*", index):
            comment_depth = 1
            index += 2
            while index < length and comment_depth:
                if source.startswith("/*", index):
                    comment_depth += 1
                    index += 2
                elif source.startswith("*/", index):
                    comment_depth -= 1
                    index += 2
                else:
                    index += 1
            continue

        regex_recognized, regex_end = _swift_regex_literal_end(
            source, index, expression_start
        )
        if regex_recognized:
            if regex_end is None:
                return None
            index = regex_end
            continue
        if source[index] == "/":
            # Ambiguous division/regex syntax is deliberately unsupported;
            # the caller exposes the rest of the interpolation to deny rules.
            return None

        hash_count = 0
        while index + hash_count < length and source[index + hash_count] == "#":
            hash_count += 1
        quote_index = index + hash_count
        if quote_index < length and source[quote_index] == '"':
            quote_count = 3 if source.startswith('"""', quote_index) else 1
            closing = '"' * quote_count + "#" * hash_count
            nested_interpolation = "\\" + "#" * hash_count + "("
            index = quote_index + quote_count
            while index < length:
                if source.startswith(closing, index):
                    index += len(closing)
                    break
                if source.startswith(nested_interpolation, index):
                    nested_start = index + len(nested_interpolation)
                    nested_end = _swift_interpolation_end(source, nested_start)
                    if nested_end is None:
                        return None
                    index = nested_end + 1
                    continue
                if hash_count == 0 and quote_count == 1 and source[index] == "\\":
                    index = min(length, index + 2)
                else:
                    index += 1
            continue

        if source[index] == "(":
            depth += 1
        elif source[index] == ")":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return None


def network_transport_violations(sources: dict[str, str]) -> list[str]:
    """Reject network/file APIs that can bypass the deterministic APIService boundary."""

    violations: list[str] = []
    constructors: list[str] = []
    local_file_reads: list[str] = []
    for path, source in sources.items():
        code = _swift_static_code(source)
        api_service_tokens = list(re.finditer(r"\bAPIService\b", code))
        if path != APPROVED_API_SERVICE_PATH:
            invalid_api_service_tokens = [
                match for match in api_service_tokens
                if re.match(r"\s*\.\s*shared\b", code[match.end():]) is None
            ]
            if invalid_api_service_tokens:
                violations.append(
                    f"APIService may only be referenced through exact APIService.shared: {path}"
                )
        url_session_tokens = len(re.findall(r"\bURLSession\b", code))
        if path != APPROVED_API_SERVICE_PATH and url_session_tokens:
            violations.append(f"URLSession type may only appear in APIService: {path}")
        if SESSION_SHARED_PATTERN.search(code):
            violations.append(f"URLSession.shared bypass: {path}")
        if SESSION_ALIAS_PATTERN.search(code):
            violations.append(f"aliased URLSession bypass: {path}")
        if CONTEXTUAL_CONFIGURATION_INIT_PATTERN.search(code):
            violations.append(f"contextual session constructor bypass: {path}")
        shadow_matches = list(API_SERVICE_SHADOW_PATTERN.finditer(code))
        if path == APPROVED_API_SERVICE_PATH:
            shadow_matches = [
                match for match in shadow_matches
                if not re.fullmatch(r"actor\s+APIService", match.group(0).strip())
            ]
        if shadow_matches:
            violations.append(f"APIService identifier may not be shadowed: {path}")
        pattern_binding = False
        for binding in re.finditer(r"\b(?:let|var)\b", code):
            tail = code[binding.end():binding.end() + 500]
            lhs = re.split(r"=|;|\{|\}|\bin\b", tail, maxsplit=1)[0]
            if re.search(r"\bAPIService\b", lhs):
                pattern_binding = True
                break
        if pattern_binding:
            violations.append(f"APIService identifier may not be pattern-bound: {path}")
        if path != APPROVED_API_SERVICE_PATH and re.search(
            r"\b(?:let|var)\s+trustedSession\b", code
        ):
            violations.append(f"trustedSession identity may not be redeclared: {path}")
        constructors.extend(path for _ in SESSION_CONSTRUCTOR_PATTERN.finditer(code))
        constructors.extend(
            path for _ in INFERRED_SESSION_CONSTRUCTOR_PATTERN.finditer(code)
        )
        local_file_reads.extend(path for _ in LOCAL_FILE_READ_PATTERN.finditer(code))
        for pattern, label in DIRECT_NETWORK_BYPASS_PATTERNS:
            if pattern.search(code):
                violations.append(f"{label} bypass: {path}")

        request_count = len(SESSION_REQUEST_PATTERN.findall(code))
        approved_request_count = len(APPROVED_SESSION_REQUEST_PATTERN.findall(code))
        if path == APPROVED_API_SERVICE_PATH:
            approved_request_count = len(
                APPROVED_API_SERVICE_REQUEST_PATTERN.findall(code)
            )
        elif path.startswith("XjieUITests/"):
            approved_request_count = 0
        if request_count != approved_request_count:
            violations.append(
                f"URLSession request does not use the explicit APIService transport: {path}"
            )

    if constructors != [APPROVED_API_SERVICE_PATH]:
        violations.append(
            "expected one controlled URLSession constructor in APIService; "
            f"got {constructors}"
        )
    api_source = _swift_static_code(sources.get(APPROVED_API_SERVICE_PATH, ""))
    if len(re.findall(r"\bAPIService\b", api_source)) != 3 \
            or re.search(r"\bactor\s+APIService\s*:\s*APIServiceProtocol\b", api_source) is None \
            or re.search(
                r"\bstatic\s+let\s+shared\s*=\s*APIService\s*\(\s*\)", api_source
            ) is None:
        violations.append("APIService owner identity or singleton contract changed")
    if len(re.findall(r"\bURLSession\b", api_source)) != 2:
        violations.append("APIService must contain exactly the pinned URLSession type and constructor")
    approved_constructor = re.search(
        r"trustedSession\s*:\s*URLSession\s*=\s*URLSession\s*\(\s*"
        r"configuration\s*:\s*APIService\.makeSessionConfiguration\s*\(\s*\)\s*\)",
        api_source,
        re.MULTILINE,
    )
    if approved_constructor is None:
        violations.append("approved APIService transport constructor is missing")
    if len(re.findall(r"\b(?:let|var)\s+trustedSession\b", api_source)) != 1 \
            or len(re.findall(r"(?<!\.)\btrustedSession\s*:", api_source)) != 1:
        violations.append("APIService trustedSession identity may not be shadowed or redeclared")

    if local_file_reads != [APPROVED_LOCAL_FILE_LOADER_PATH]:
        violations.append(
            "Data(contentsOf:) must appear exactly once inside LocalFileDataLoader; "
            f"got {local_file_reads}"
        )
    loader_source = _swift_static_code(sources.get(APPROVED_LOCAL_FILE_LOADER_PATH, ""))
    if re.search(
        r"enum\s+LocalFileDataLoader\b[\s\S]*?guard\s+url\s*\.\s*isFileURL\s+else\s*\{"
        r"[\s\S]*?throw\s+URLError\s*\(\s*\.unsupportedURL\s*\)",
        loader_source,
    ) is None:
        violations.append("LocalFileDataLoader must reject every non-file URL before reading")
    return violations


def deterministic_system_boundary_violations(
    sources: dict[str, str],
) -> list[str]:
    """Keep every nondeterministic system constructor behind its one UI-safe owner."""

    violations: list[str] = []
    static_sources = {
        path: _swift_static_code(source)
        for path, source in sources.items()
    }
    token_contracts = (
        ("NWPathMonitor", "Utils/NetworkMonitor.swift", 1),
        ("HKHealthStore", "ViewModels/AppleHealthSyncViewModel.swift", 4),
    )
    for token, expected_path, expected_count in token_contracts:
        locations = [
            path
            for path, code in static_sources.items()
            for _ in re.finditer(rf"\b{re.escape(token)}\b", code)
        ]
        if locations != [expected_path] * expected_count:
            violations.append(
                f"{token} token identity changed; expected {expected_count} in "
                f"{expected_path}, got {locations}"
            )
    for pattern, expected_path, label in PINNED_SYSTEM_CONSTRUCTORS:
        locations = [
            path
            for path, code in static_sources.items()
            for _ in pattern.finditer(code)
        ]
        if locations != [expected_path]:
            violations.append(
                f"expected one {label} constructor in {expected_path}; got {locations}"
            )

    network_monitor = static_sources.get("Utils/NetworkMonitor.swift", "")
    if re.search(
        r"shouldStartPathMonitor\s*\(\s*arguments\s*:\s*\[String\]\s*\)"
        r"[\s\S]*?!UIAutomationMode\s*\.\s*isEnabled\s*\(",
        network_monitor,
    ) is None:
        violations.append("NWPathMonitor owner must fail closed during UI automation")

    health_owner = static_sources.get("ViewModels/AppleHealthSyncViewModel.swift", "")
    if re.search(
        r"init\s*\([\s\S]{0,300}?store\s*:\s*HKHealthStore\s*=\s*HKHealthStore\s*\(",
        health_owner,
    ) is None:
        violations.append("HKHealthStore must remain injectable through its pinned owner")

    notification_owner = static_sources.get("Services/PushNotificationManager.swift", "")
    if re.search(
        r"guard\s+shouldUseNotificationCenter\s*\(\s*arguments\s*:\s*arguments\s*\)"
        r"\s*else\s*\{\s*return\s+nil\s*\}[\s\S]{0,120}?"
        r"UNUserNotificationCenter\s*\.\s*current\s*\(",
        notification_owner,
    ) is None:
        violations.append("notification center must remain behind the UI-safe factory")
    return violations


def _mask_openstep_comments(source: str) -> tuple[str, dict[str, str], bool]:
    """Remove comments and opaque quoted values before structural PBX matching."""

    if "__XJIE_PBX_STRING_" in source:
        return source, {}, False
    output: list[str] = []
    quoted_values: dict[str, str] = {}
    index = 0
    while index < len(source):
        if source[index] == '"':
            end = index + 1
            while end < len(source):
                if source[end] in "\r\n":
                    return "".join(output), quoted_values, False
                if source[end] == "\\":
                    end += 2
                    continue
                if source[end] == '"':
                    end += 1
                    break
                end += 1
            else:
                return "".join(output), quoted_values, False
            literal = source[index:end]
            try:
                decoded = ast.literal_eval(literal)
            except (SyntaxError, ValueError):
                return "".join(output), quoted_values, False
            if not isinstance(decoded, str):
                return "".join(output), quoted_values, False
            token = f"__XJIE_PBX_STRING_{len(quoted_values):06d}__"
            quoted_values[token] = decoded
            output.append(token)
            index = end
            continue
        if source.startswith("/*", index):
            end = source.find("*/", index + 2)
            if end < 0:
                return "".join(output), quoted_values, False
            comment = source[index:end + 2]
            output.append("".join(character if character in "\r\n" else " " for character in comment))
            index = end + 2
            continue
        if source.startswith("//", index):
            end = source.find("\n", index + 2)
            end = len(source) if end < 0 else end
            output.append(" " * (end - index))
            index = end
            continue
        output.append(source[index])
        index += 1
    return "".join(output), quoted_values, True


def _openstep_object_body(source: str, object_id: str) -> str | None:
    """Return one sanitized OpenStep object body using balanced braces."""

    matches = list(re.finditer(
        rf"(?m)^\s*{re.escape(object_id)}\s*=\s*\{{",
        source,
    ))
    bodies: list[str] = []
    for match in matches:
        start = match.end()
        depth = 1
        for index in range(start, len(source)):
            if source[index] == "{":
                depth += 1
            elif source[index] == "}":
                depth -= 1
                if depth == 0:
                    bodies.append(source[start:index])
                    break
    structural_bodies = [
        body for body in bodies
        if re.search(r"(?:^|[;{])\s*isa\s*=", body) is not None
    ]
    return structural_bodies[0] if len(structural_bodies) == 1 else None


def _openstep_assignment_count(body: str, key: str) -> int:
    return len(re.findall(rf"(?:^|[;{{])\s*{re.escape(key)}\s*=", body))


def _openstep_direct_assignments(body: str) -> tuple[dict[str, list[str]], bool]:
    """Parse direct key/value assignments from one sanitized OpenStep dictionary."""

    assignments: dict[str, list[str]] = {}
    index = 0
    while index < len(body):
        while index < len(body) and body[index].isspace():
            index += 1
        if index == len(body):
            break
        key_match = re.match(r"[A-Za-z_][A-Za-z0-9_]*", body[index:])
        if key_match is None:
            return assignments, False
        key = key_match.group(0)
        index += len(key)
        while index < len(body) and body[index].isspace():
            index += 1
        if index >= len(body) or body[index] != "=":
            return assignments, False
        index += 1
        value_start = index
        brace_depth = 0
        parenthesis_depth = 0
        while index < len(body):
            character = body[index]
            if character == "{":
                brace_depth += 1
            elif character == "}":
                brace_depth -= 1
            elif character == "(":
                parenthesis_depth += 1
            elif character == ")":
                parenthesis_depth -= 1
            elif character == ";" and brace_depth == 0 and parenthesis_depth == 0:
                assignments.setdefault(key, []).append(body[value_start:index].strip())
                index += 1
                break
            if brace_depth < 0 or parenthesis_depth < 0:
                return assignments, False
            index += 1
        else:
            return assignments, False
    return assignments, True


def _openstep_top_level_objects(source: str) -> tuple[dict[str, str], bool]:
    """Parse every direct object entry so `isa` order cannot hide an object."""

    match = re.search(r"\bobjects\s*=\s*\{", source)
    if match is None:
        return {}, False
    start = match.end()
    depth = 1
    end = None
    for cursor in range(start, len(source)):
        if source[cursor] == "{":
            depth += 1
        elif source[cursor] == "}":
            depth -= 1
            if depth == 0:
                end = cursor
                break
    if end is None:
        return {}, False
    region = source[start:end]
    objects: dict[str, str] = {}
    index = 0
    while index < len(region):
        while index < len(region) and region[index].isspace():
            index += 1
        if index == len(region):
            break
        identifier_match = re.match(r"[A-Za-z0-9]+", region[index:])
        if identifier_match is None:
            return objects, False
        object_id = identifier_match.group(0)
        index += len(object_id)
        while index < len(region) and region[index].isspace():
            index += 1
        if index >= len(region) or region[index] != "=":
            return objects, False
        index += 1
        while index < len(region) and region[index].isspace():
            index += 1
        if index >= len(region) or region[index] != "{":
            return objects, False
        body_start = index + 1
        depth = 1
        index += 1
        while index < len(region) and depth:
            if region[index] == "{":
                depth += 1
            elif region[index] == "}":
                depth -= 1
            index += 1
        if depth or object_id in objects:
            return objects, False
        objects[object_id] = region[body_start:index - 1]
        while index < len(region) and region[index].isspace():
            index += 1
        if index >= len(region) or region[index] != ";":
            return objects, False
        index += 1
    return objects, True


def repository_filesystem_identity_violations(
    repo_root: Path,
    source_roots: tuple[Path, ...],
    pinned_files: tuple[Path, ...],
) -> list[str]:
    """Reject symlink/mutable ancestors before reading build inputs."""

    violations: list[str] = []
    checked: set[Path] = set()

    def validate(path: Path, *, expect_directory: bool | None = None) -> bool:
        if path in checked:
            return True
        checked.add(path)
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            violations.append(f"required repository path is missing: {path}")
            return False
        if stat.S_ISLNK(metadata.st_mode):
            violations.append(f"repository build input may not be a symlink: {path}")
            return False
        if expect_directory is True and not stat.S_ISDIR(metadata.st_mode):
            violations.append(f"required repository directory is not real: {path}")
            return False
        if expect_directory is False and not stat.S_ISREG(metadata.st_mode):
            violations.append(f"required repository file is not regular: {path}")
            return False
        return True

    validate(repo_root, expect_directory=True)
    for root in source_roots:
        if not validate(root, expect_directory=True):
            continue
        for directory, directory_names, file_names in os.walk(root, followlinks=False):
            directory_path = Path(directory)
            validate(directory_path, expect_directory=True)
            for name in directory_names:
                validate(directory_path / name, expect_directory=True)
            for name in file_names:
                validate(directory_path / name, expect_directory=False)
    for path in pinned_files:
        current = path
        while current != repo_root:
            if not current.is_relative_to(repo_root):
                violations.append(f"repository build input escapes repository root: {path}")
                break
            validate(current, expect_directory=current != path)
            current = current.parent
        validate(repo_root, expect_directory=True)
    return violations


def swift_source_layout_violations(
    swift_paths: set[str],
    project_source: str,
) -> list[str]:
    """Bind audited Swift files to the actual build-file/ref/group path graph."""

    violations: list[str] = []
    project_source, quoted_values, syntax_valid = _mask_openstep_comments(project_source)
    if not syntax_valid:
        violations.append("Xcode project contains unsupported comments or quoted strings")
    allowed_roots = ("Xjie/Xjie/", "Xjie/XjieTests/", "Xjie/XjieUITests/")
    outside = sorted(
        path for path in swift_paths
        if not any(path.startswith(root) for root in allowed_roots)
    )
    if outside:
        violations.append(
            "Swift source exists outside the audited app/test roots: " + ", ".join(outside)
        )

    def field(body: str, name: str) -> str | None:
        match = re.search(
            rf"\b{re.escape(name)}\s*=\s*(\"(?:\\.|[^\"\\])*\"|[^;\r\n]+)\s*;",
            body,
        )
        if match is None:
            return None
        value = match.group(1).strip()
        return quoted_values.get(value, value)

    top_level_objects, objects_valid = _openstep_top_level_objects(project_source)
    object_types: dict[str, str] = {}
    direct_fields: dict[str, dict[str, list[str]]] = {}
    if not objects_valid:
        violations.append("Xcode project objects dictionary is not uniquely parseable")
    for object_id, body in top_level_objects.items():
        fields, fields_valid = _openstep_direct_assignments(body)
        direct_fields[object_id] = fields
        isa_values = fields.get("isa", [])
        if not fields_valid or len(isa_values) != 1 \
                or re.fullmatch(r"[A-Za-z0-9]+", isa_values[0]) is None:
            violations.append(f"Xcode object {object_id} has invalid or duplicate isa")
            continue
        object_types[object_id] = isa_values[0]

    allowed_object_types = {
        "PBXBuildFile",
        "PBXContainerItemProxy",
        "PBXFileReference",
        "PBXFrameworksBuildPhase",
        "PBXGroup",
        "PBXNativeTarget",
        "PBXProject",
        "PBXResourcesBuildPhase",
        "PBXSourcesBuildPhase",
        "PBXTargetDependency",
        "PBXVariantGroup",
        "XCBuildConfiguration",
        "XCConfigurationList",
    }
    unexpected_types = sorted(set(object_types.values()) - allowed_object_types)
    if unexpected_types:
        violations.append("Xcode project contains forbidden object types: " + ", ".join(unexpected_types))
    exact_type_ids = {
        "PBXContainerItemProxy": {"J10001", "J300000000000000000001"},
        "PBXFrameworksBuildPhase": {"D10001", "D20001", "D300000000000000000001"},
        "PBXNativeTarget": {"F10001", "F20001", "F300000000000000000001"},
        "PBXProject": {"H10001"},
        "PBXResourcesBuildPhase": {"F10003"},
        "PBXSourcesBuildPhase": {"F10002", "F20002", "F300000000000000000002"},
        "PBXTargetDependency": {"K10001", "K300000000000000000001"},
    }
    for object_type, expected_ids in exact_type_ids.items():
        actual_ids = {
            object_id for object_id, candidate_type in object_types.items()
            if candidate_type == object_type
        }
        if actual_ids != expected_ids:
            violations.append(
                f"Xcode {object_type} identities changed; expected {sorted(expected_ids)}, "
                f"got {sorted(actual_ids)}"
            )

    def exact_direct_values(object_id: str, expected: dict[str, str]) -> None:
        fields = direct_fields.get(object_id, {})
        for key, value in expected.items():
            if fields.get(key) != [value]:
                violations.append(
                    f"Xcode object {object_id} {key} changed; expected {value}"
                )

    exact_direct_values("K10001", {"target": "F10001", "targetProxy": "J10001"})
    exact_direct_values(
        "K300000000000000000001",
        {"target": "F10001", "targetProxy": "J300000000000000000001"},
    )
    exact_direct_values(
        "J10001",
        {"containerPortal": "H10001", "proxyType": "1", "remoteGlobalIDString": "F10001"},
    )
    exact_direct_values(
        "J300000000000000000001",
        {"containerPortal": "H10001", "proxyType": "1", "remoteGlobalIDString": "F10001"},
    )
    project_targets = direct_fields.get("H10001", {}).get("targets", [])
    parsed_project_targets = () if len(project_targets) != 1 else tuple(
        re.findall(r"\b([A-Za-z0-9]+)\s*,", project_targets[0])
    )
    if parsed_project_targets != (
        "F10001",
        "F20001",
        "F300000000000000000001",
    ):
        violations.append("PBXProject targets must remain the exact three pinned native targets")

    build_files: dict[str, str] = {}
    for match in re.finditer(
        r"(?m)^\s*([A-Za-z0-9]+)(?:\s+/\*.*?\*/)?\s*=\s*"
        r"\{isa\s*=\s*PBXBuildFile;\s*fileRef\s*=\s*([A-Za-z0-9]+)\b[^}]*\};\s*$",
        project_source,
    ):
        build_id, reference_id = match.groups()
        object_body = _openstep_object_body(project_source, build_id)
        if object_body is None or _openstep_assignment_count(object_body, "isa") != 1 \
                or _openstep_assignment_count(object_body, "fileRef") != 1:
            violations.append(f"PBXBuildFile {build_id} contains duplicate structural keys")
        if build_id in build_files:
            violations.append(f"duplicate PBXBuildFile identifier: {build_id}")
        build_files[build_id] = reference_id

    references: dict[str, tuple[str, str]] = {}
    for match in re.finditer(
        r"(?m)^\s*([A-Za-z0-9]+)(?:\s+/\*.*?\*/)?\s*=\s*\{"
        r"isa\s*=\s*PBXFileReference;(?P<body>.*?)\};\s*$",
        project_source,
    ):
        reference_id = match.group(1)
        body = match.group("body")
        object_body = _openstep_object_body(project_source, reference_id)
        if object_body is None \
                or _openstep_assignment_count(object_body, "isa") != 1 \
                or _openstep_assignment_count(object_body, "path") != 1 \
                or _openstep_assignment_count(object_body, "sourceTree") != 1:
            violations.append(
                f"PBXFileReference {reference_id} contains duplicate structural keys"
            )
        path = field(body, "path")
        source_tree = field(body, "sourceTree")
        if path is not None and source_tree is not None:
            references[reference_id] = (path, source_tree)

    groups: dict[str, tuple[tuple[str, ...], str | None, str | None]] = {}
    for match in re.finditer(
        r"(?ms)^\s*([A-Za-z0-9]+)(?:\s+/\*[^\r\n]*?\*/)?\s*=\s*\{\s*"
        r"isa\s*=\s*PBXGroup;(?P<body>.*?)^\s*\};\s*$",
        project_source,
    ):
        group_id = match.group(1)
        body = match.group("body")
        object_body = _openstep_object_body(project_source, group_id)
        if object_body is None \
                or _openstep_assignment_count(object_body, "isa") != 1 \
                or _openstep_assignment_count(object_body, "children") != 1 \
                or _openstep_assignment_count(object_body, "sourceTree") != 1 \
                or _openstep_assignment_count(object_body, "path") > 1:
            violations.append(f"PBXGroup {group_id} contains duplicate structural keys")
        children_match = re.search(r"(?ms)\bchildren\s*=\s*\((.*?)\);", body)
        if children_match is None:
            violations.append(f"PBXGroup {group_id} has no parseable children list")
            children: tuple[str, ...] = ()
        else:
            children = tuple(re.findall(
                r"\b([A-Za-z0-9]+)(?:\s+/\*.*?\*/)?\s*,",
                children_match.group(1),
            ))
            residual = re.sub(
                r"\b[A-Za-z0-9]+(?:\s+/\*.*?\*/)?\s*,",
                "",
                children_match.group(1),
            )
            if residual.strip():
                violations.append(f"PBXGroup {group_id} has unparseable child entries")
        groups[group_id] = (children, field(body, "path"), field(body, "sourceTree"))

    parent_groups: dict[str, list[str]] = {}
    for group_id, (children, _path, _source_tree) in groups.items():
        for child in children:
            parent_groups.setdefault(child, []).append(group_id)

    project_body = _openstep_object_body(project_source, "H10001")
    if project_body is None \
            or _openstep_assignment_count(project_body, "isa") != 1 \
            or _openstep_assignment_count(project_body, "buildConfigurationList") != 1 \
            or _openstep_assignment_count(project_body, "mainGroup") != 1 \
            or _openstep_assignment_count(project_body, "targets") != 1:
        violations.append("PBXProject contains missing or duplicate structural keys")
    main_group_match = re.search(
        r"(?m)^\s*mainGroup\s*=\s*([A-Za-z0-9]+)\b",
        "" if project_body is None else project_body,
    )
    main_group = None if main_group_match is None else main_group_match.group(1)
    if main_group not in groups:
        violations.append("Xcode project has no parseable mainGroup")

    def safe_join(base: PurePosixPath, value: str, description: str) -> PurePosixPath | None:
        if not value or "\\" in value or "\x00" in value or "$" in value:
            violations.append(f"unsafe {description}: {value!r}")
            return None
        candidate = PurePosixPath(value)
        if candidate.is_absolute() or any(
            part in {"", ".", ".."}
            or any(ord(character) < 32 or ord(character) == 127 for character in part)
            for part in candidate.parts
        ):
            violations.append(f"unsafe {description}: {value!r}")
            return None
        return base.joinpath(candidate)

    project_directory = PurePosixPath("Xjie")
    group_cache: dict[str, PurePosixPath | None] = {}

    def resolve_group(group_id: str, stack: tuple[str, ...] = ()) -> PurePosixPath | None:
        if group_id in group_cache:
            return group_cache[group_id]
        if group_id in stack:
            violations.append(f"cyclic PBXGroup ancestry: {' -> '.join(stack + (group_id,))}")
            group_cache[group_id] = None
            return None
        group = groups.get(group_id)
        if group is None:
            violations.append(f"missing PBXGroup referenced by source path: {group_id}")
            return None
        _children, path, source_tree = group
        if source_tree == "SOURCE_ROOT" or group_id == main_group:
            base = project_directory
        elif source_tree == "<group>":
            parents = parent_groups.get(group_id, [])
            if len(parents) != 1:
                violations.append(
                    f"PBXGroup {group_id} must have exactly one parent; got {parents}"
                )
                group_cache[group_id] = None
                return None
            base = resolve_group(parents[0], stack + (group_id,))
        else:
            violations.append(
                f"PBXGroup {group_id} uses unsupported sourceTree {source_tree!r}"
            )
            group_cache[group_id] = None
            return None
        if base is None:
            group_cache[group_id] = None
            return None
        resolved = base if path is None else safe_join(base, path, f"PBXGroup path {group_id}")
        group_cache[group_id] = resolved
        return resolved

    def resolve_reference(reference_id: str) -> str | None:
        reference = references.get(reference_id)
        if reference is None:
            violations.append(f"missing or malformed PBXFileReference: {reference_id}")
            return None
        path, source_tree = reference
        if source_tree == "SOURCE_ROOT":
            base = project_directory
        elif source_tree == "<group>":
            parents = parent_groups.get(reference_id, [])
            if len(parents) != 1:
                violations.append(
                    f"PBXFileReference {reference_id} must have exactly one group parent; "
                    f"got {parents}"
                )
                return None
            base = resolve_group(parents[0])
            if base is None:
                return None
        else:
            violations.append(
                f"PBXFileReference {reference_id} uses unsupported sourceTree {source_tree!r}"
            )
            return None
        resolved = safe_join(base, path, f"PBXFileReference path {reference_id}")
        return None if resolved is None else resolved.as_posix()

    phase_roots = {
        "F10002": "Xjie/Xjie/",
        "F20002": "Xjie/XjieTests/",
        "F300000000000000000002": "Xjie/XjieUITests/",
    }
    source_phase_ids = {
        object_id
        for object_id, object_type in object_types.items()
        if object_type == "PBXSourcesBuildPhase"
    }
    if source_phase_ids != set(phase_roots):
        violations.append(
            "Xcode project must contain only the three pinned source phases; "
            f"got {sorted(source_phase_ids)}"
        )
    if any(object_type == "PBXShellScriptBuildPhase" for object_type in object_types.values()):
        violations.append("Xcode project may not contain PBXShellScriptBuildPhase objects")

    target_contracts = {
        "F10001": {
            "buildPhases": ("F10002", "D10001", "F10003"),
            "buildRules": (),
            "dependencies": (),
        },
        "F20001": {
            "buildPhases": ("F20002", "D20001"),
            "buildRules": (),
            "dependencies": ("K10001",),
        },
        "F300000000000000000001": {
            "buildPhases": (
                "F300000000000000000002",
                "D300000000000000000001",
            ),
            "buildRules": (),
            "dependencies": ("K300000000000000000001",),
        },
    }
    target_configuration_lists = {
        "F10001": "G10003",
        "F20001": "G20003",
        "F300000000000000000001": "G300000000000000000003",
    }
    expected_phase_types = {
        "F10002": "PBXSourcesBuildPhase",
        "D10001": "PBXFrameworksBuildPhase",
        "F10003": "PBXResourcesBuildPhase",
        "F20002": "PBXSourcesBuildPhase",
        "D20001": "PBXFrameworksBuildPhase",
        "F300000000000000000002": "PBXSourcesBuildPhase",
        "D300000000000000000001": "PBXFrameworksBuildPhase",
    }
    for phase_id, expected_type in expected_phase_types.items():
        if object_types.get(phase_id) != expected_type:
            violations.append(
                f"Xcode phase {phase_id} must remain {expected_type}; "
                f"got {object_types.get(phase_id)!r}"
            )

    for target_id, contract in target_contracts.items():
        object_body = _openstep_object_body(project_source, target_id)
        required_target_keys = (
            "isa",
            "buildConfigurationList",
            "buildPhases",
            "buildRules",
            "dependencies",
        )
        if object_body is None or any(
            _openstep_assignment_count(object_body, key) != 1
            for key in required_target_keys
        ):
            violations.append(
                f"PBXNativeTarget {target_id} contains missing or duplicate structural keys"
            )
        target_match = re.search(
            rf"(?ms)^\s*{re.escape(target_id)}(?:\s+/\*[^\r\n]*?\*/)?\s*=\s*\{{"
            r"\s*isa\s*=\s*PBXNativeTarget\s*;(?P<body>.*?)^\s*\};\s*$",
            project_source,
        )
        if target_match is None:
            violations.append(f"missing pinned PBXNativeTarget {target_id}")
            continue
        if re.search(r"\bpackageProductDependencies\s*=", target_match.group("body")):
            violations.append(
                f"PBXNativeTarget {target_id} may not use Swift package products"
            )
        configuration_match = re.search(
            r"\bbuildConfigurationList\s*=\s*([A-Za-z0-9]+)\b",
            target_match.group("body"),
        )
        expected_configuration = target_configuration_lists[target_id]
        if configuration_match is None or configuration_match.group(1) != expected_configuration:
            violations.append(
                f"PBXNativeTarget {target_id} buildConfigurationList changed; "
                f"expected {expected_configuration}"
            )
        for field_name, expected_ids in contract.items():
            values_match = re.search(
                rf"(?ms)\b{re.escape(field_name)}\s*=\s*\((.*?)\);",
                target_match.group("body"),
            )
            if values_match is None:
                violations.append(
                    f"PBXNativeTarget {target_id} has no {field_name} list"
                )
                continue
            values = tuple(re.findall(
                r"\b([A-Za-z0-9]+)(?:\s+/\*.*?\*/)?\s*,",
                values_match.group(1),
            ))
            residual = re.sub(
                r"\b[A-Za-z0-9]+(?:\s+/\*.*?\*/)?\s*,",
                "",
                values_match.group(1),
            )
            if residual.strip() or values != expected_ids:
                violations.append(
                    f"PBXNativeTarget {target_id} {field_name} changed; "
                    f"expected {expected_ids}, got {values}"
                )

    for phase_id in ("D10001", "D20001", "D300000000000000000001"):
        object_body = _openstep_object_body(project_source, phase_id)
        if object_body is None \
                or _openstep_assignment_count(object_body, "isa") != 1 \
                or _openstep_assignment_count(object_body, "files") != 1:
            violations.append(
                f"PBXFrameworksBuildPhase {phase_id} contains duplicate structural keys"
            )
        phase_match = re.search(
            rf"(?ms)^\s*{re.escape(phase_id)}\s*=\s*\{{\s*"
            r"isa\s*=\s*PBXFrameworksBuildPhase\s*;(?P<body>.*?)^\s*\};\s*$",
            project_source,
        )
        if phase_match is None:
            violations.append(f"missing pinned PBXFrameworksBuildPhase {phase_id}")
            continue
        files_match = re.search(
            r"(?ms)\bfiles\s*=\s*\((?P<files>.*?)\);",
            phase_match.group("body"),
        )
        if files_match is None or files_match.group("files").strip():
            violations.append(f"PBXFrameworksBuildPhase {phase_id} must remain empty")

    if re.search(r"\bpackageReferences\s*=", project_source):
        violations.append("PBXProject may not use Swift package references")
    forbidden_package_types = {
        "XCRemoteSwiftPackageReference",
        "XCLocalSwiftPackageReference",
        "XCSwiftPackageProductDependency",
    }
    present_package_types = sorted(forbidden_package_types & set(object_types.values()))
    if present_package_types:
        violations.append(
            "Xcode project may not contain Swift package objects: "
            + ", ".join(present_package_types)
        )

    for phase_id, root in phase_roots.items():
        object_body = _openstep_object_body(project_source, phase_id)
        if object_body is None \
                or _openstep_assignment_count(object_body, "isa") != 1 \
                or _openstep_assignment_count(object_body, "files") != 1:
            violations.append(
                f"PBXSourcesBuildPhase {phase_id} contains duplicate structural keys"
            )
        phase_match = re.search(
            rf"(?ms)^\s*{re.escape(phase_id)}(?:\s+/\*[^\r\n]*?\*/)?\s*=\s*\{{\s*"
            r"isa\s*=\s*PBXSourcesBuildPhase\s*;.*?^\s*\};",
            project_source,
        )
        if phase_match is None:
            violations.append(f"missing pinned PBXSourcesBuildPhase {phase_id}")
            continue
        files_match = re.search(r"(?ms)\bfiles\s*=\s*\((.*?)\);", phase_match.group(0))
        if files_match is None:
            violations.append(f"PBXSourcesBuildPhase {phase_id} has no files list")
            continue
        file_block = files_match.group(1)
        build_ids = re.findall(
            r"\b([A-Za-z0-9]+)(?:\s+/\*.*?\*/)?\s*,",
            file_block,
        )
        residual = re.sub(
            r"\b[A-Za-z0-9]+(?:\s+/\*.*?\*/)?\s*,",
            "",
            file_block,
        )
        if residual.strip():
            violations.append(f"PBXSourcesBuildPhase {phase_id} has unparseable file entries")
        if len(build_ids) != len(set(build_ids)):
            violations.append(f"PBXSourcesBuildPhase {phase_id} has duplicate build-file IDs")
        actual_paths: list[str] = []
        for build_id in build_ids:
            reference_id = build_files.get(build_id)
            if reference_id is None:
                violations.append(
                    f"PBXSourcesBuildPhase {phase_id} references missing PBXBuildFile {build_id}"
                )
                continue
            resolved = resolve_reference(reference_id)
            if resolved is not None:
                actual_paths.append(resolved)
        if len(actual_paths) != len(set(actual_paths)):
            violations.append(f"PBXSourcesBuildPhase {phase_id} compiles a Swift path twice")
        actual = set(actual_paths)
        expected = {path for path in swift_paths if path.startswith(root)}
        if actual != expected:
            missing = sorted(expected - actual)
            foreign = sorted(actual - expected)
            violations.append(
                f"PBXSourcesBuildPhase {phase_id} does not exactly match {root}; "
                f"missing={missing}, foreign={foreign}"
            )
    return violations


def xcode_release_build_setting_violations(project_source: str) -> list[str]:
    """Pin source participation and Release compilation settings fail closed."""

    violations: list[str] = []
    project_source, quoted_values, syntax_valid = _mask_openstep_comments(project_source)
    if not syntax_valid:
        violations.append("Xcode project contains unsupported comments or quoted strings")
    globally_forbidden = (
        "EXCLUDED_SOURCE_FILE_NAMES",
        "INCLUDED_SOURCE_FILE_NAMES",
        "COMPILER_FLAGS",
        "baseConfigurationReference",
        "OTHER_LDFLAGS",
        "SWIFT_OBJC_BRIDGING_HEADER",
        "SWIFT_INCLUDE_PATHS",
        "LIBRARY_SEARCH_PATHS",
        "FRAMEWORK_SEARCH_PATHS",
    )
    for key in globally_forbidden:
        if re.search(rf"\b{re.escape(key)}\b\s*=", project_source):
            violations.append(f"Xcode project may not set {key}")

    configuration_contracts = {
        "G10002": "Debug",
        "G10004": "Release",
        "G10005": "Debug",
        "G10006": "Release",
        "G20005": "Debug",
        "G20006": "Release",
        "G300000000000000000005": "Debug",
        "G300000000000000000006": "Release",
    }
    release_forbidden = (
        "SWIFT_ACTIVE_COMPILATION_CONDITIONS",
        "OTHER_SWIFT_FLAGS",
        "GCC_PREPROCESSOR_DEFINITIONS",
        "ENABLE_TESTABILITY",
        "EXCLUDED_ARCHS",
        "ONLY_ACTIVE_ARCH",
        "OTHER_CFLAGS",
        "OTHER_CPLUSPLUSFLAGS",
    )
    for configuration_id, expected_name in configuration_contracts.items():
        object_body = _openstep_object_body(project_source, configuration_id)
        if object_body is None \
                or _openstep_assignment_count(object_body, "isa") != 1 \
                or _openstep_assignment_count(object_body, "buildSettings") != 1 \
                or _openstep_assignment_count(object_body, "name") != 1:
            violations.append(
                f"XCBuildConfiguration {configuration_id} contains duplicate structural keys"
            )
        match = re.search(
            rf"(?ms)^\s*{re.escape(configuration_id)}(?:\s+/\*[^\r\n]*?\*/)?\s*=\s*\{{\s*"
            r"isa\s*=\s*XCBuildConfiguration\s*;\s*"
            r"buildSettings\s*=\s*\{(?P<settings>.*?)^\s*\};\s*"
            r"name\s*=\s*(?P<name>[^;\r\n]+)\s*;\s*^\s*\};\s*$",
            project_source,
        )
        if match is None:
            violations.append(f"missing pinned XCBuildConfiguration {configuration_id}")
            continue
        raw_name = match.group("name").strip()
        if quoted_values.get(raw_name, raw_name) != expected_name:
            violations.append(
                f"XCBuildConfiguration {configuration_id} must remain {expected_name}"
            )
        if expected_name == "Release":
            settings = match.group("settings")
            for key in release_forbidden:
                if re.search(
                    rf"(?m)^\s*{re.escape(key)}(?:\[[^\]\r\n]+\])?\s*=",
                    settings,
                ):
                    violations.append(
                        f"Release XCBuildConfiguration {configuration_id} may not set {key}"
                    )

    list_contracts = {
        "G10001": ("G10002", "G10004"),
        "G10003": ("G10005", "G10006"),
        "G20003": ("G20005", "G20006"),
        "G300000000000000000003": (
            "G300000000000000000005",
            "G300000000000000000006",
        ),
    }
    for list_id, expected_configurations in list_contracts.items():
        object_body = _openstep_object_body(project_source, list_id)
        if object_body is None \
                or _openstep_assignment_count(object_body, "isa") != 1 \
                or _openstep_assignment_count(object_body, "buildConfigurations") != 1 \
                or _openstep_assignment_count(object_body, "defaultConfigurationName") != 1:
            violations.append(
                f"XCConfigurationList {list_id} contains duplicate structural keys"
            )
        match = re.search(
            rf"(?ms)^\s*{re.escape(list_id)}(?:\s+/\*[^\r\n]*?\*/)?\s*=\s*\{{\s*"
            r"isa\s*=\s*XCConfigurationList\s*;(?P<body>.*?)^\s*\};\s*$",
            project_source,
        )
        if match is None:
            violations.append(f"missing pinned XCConfigurationList {list_id}")
            continue
        configurations_match = re.search(
            r"(?ms)\bbuildConfigurations\s*=\s*\((.*?)\);",
            match.group("body"),
        )
        configurations = () if configurations_match is None else tuple(
            re.findall(
                r"\b([A-Za-z0-9]+)(?:\s+/\*.*?\*/)?\s*,",
                configurations_match.group(1),
            )
        )
        default_match = re.search(
            r"\bdefaultConfigurationName\s*=\s*([^;\r\n]+)\s*;",
            match.group("body"),
        )
        raw_default = None if default_match is None else default_match.group(1).strip()
        default_name = None if raw_default is None else quoted_values.get(raw_default, raw_default)
        if configurations != expected_configurations or default_name != "Release":
            violations.append(
                f"XCConfigurationList {list_id} must keep Debug/Release ordering and Release default"
            )

    project_body = _openstep_object_body(project_source, "H10001")
    if project_body is None \
            or _openstep_assignment_count(project_body, "buildConfigurationList") != 1 \
            or re.search(
                r"(?m)^\s*buildConfigurationList\s*=\s*G10001\b", project_body
            ) is None:
        violations.append("PBXProject must use the pinned G10001 configuration list")
    return violations


def xcode_scheme_violations(scheme_source: str) -> list[str]:
    """Validate the shared scheme as an exact, script-free build/test/archive graph."""

    try:
        root = ET.fromstring(scheme_source)
    except ET.ParseError as exc:
        return [f"shared Xcode scheme is not valid XML: {exc}"]
    violations: list[str] = []

    def require_attributes(element: ET.Element, expected: dict[str, str], label: str) -> None:
        if element.attrib != expected:
            violations.append(
                f"{label} attributes changed; expected {expected}, got {element.attrib}"
            )

    def require_child_tags(element: ET.Element, expected: list[str], label: str) -> None:
        actual = [child.tag for child in element]
        if actual != expected:
            violations.append(f"{label} children changed; expected {expected}, got {actual}")

    def require_reference(element: ET.Element, blueprint: str, name: str, label: str) -> None:
        require_attributes(
            element,
            {
                "BuildableIdentifier": "primary",
                "BlueprintIdentifier": blueprint,
                "BuildableName": name,
                "BlueprintName": name.removesuffix(".app").removesuffix(".xctest"),
                "ReferencedContainer": "container:Xjie.xcodeproj",
            },
            label,
        )
        require_child_tags(element, [], label)

    if root.tag != "Scheme":
        return [f"shared Xcode scheme root must be Scheme, got {root.tag}"]
    require_attributes(root, {"LastUpgradeVersion": "1540", "version": "1.7"}, "Scheme")
    require_child_tags(
        root,
        ["BuildAction", "TestAction", "LaunchAction", "ProfileAction", "AnalyzeAction", "ArchiveAction"],
        "Scheme",
    )
    prohibited = {
        "PreActions",
        "PostActions",
        "ExecutionAction",
        "EnvironmentVariables",
        "CommandLineArguments",
        "TestPlans",
    }
    present_prohibited = sorted({element.tag for element in root.iter() if element.tag in prohibited})
    if present_prohibited:
        violations.append("shared Xcode scheme contains forbidden actions/configuration: " + ", ".join(present_prohibited))
    if violations and len(root) != 6:
        return violations

    try:
        build, test, launch, profile, analyze, archive = list(root)
        require_attributes(
            build,
            {"parallelizeBuildables": "YES", "buildImplicitDependencies": "YES"},
            "BuildAction",
        )
        require_child_tags(build, ["BuildActionEntries"], "BuildAction")
        entries_container = build[0]
        require_child_tags(
            entries_container,
            ["BuildActionEntry", "BuildActionEntry", "BuildActionEntry"],
            "BuildActionEntries",
        )
        build_contracts = (
            (
                "F10001",
                "Xjie.app",
                {"buildForTesting": "YES", "buildForRunning": "YES", "buildForProfiling": "YES", "buildForArchiving": "YES", "buildForAnalyzing": "YES"},
            ),
            (
                "F20001",
                "XjieTests.xctest",
                {"buildForTesting": "YES", "buildForRunning": "NO", "buildForProfiling": "NO", "buildForArchiving": "NO", "buildForAnalyzing": "NO"},
            ),
            (
                "F300000000000000000001",
                "XjieUITests.xctest",
                {"buildForTesting": "YES", "buildForRunning": "NO", "buildForProfiling": "NO", "buildForArchiving": "NO", "buildForAnalyzing": "NO"},
            ),
        )
        for index, (blueprint, name, attributes) in enumerate(build_contracts):
            entry = entries_container[index]
            require_attributes(entry, attributes, f"BuildActionEntry[{index}]")
            require_child_tags(entry, ["BuildableReference"], f"BuildActionEntry[{index}]")
            require_reference(entry[0], blueprint, name, f"BuildActionEntry[{index}] reference")

        require_attributes(
            test,
            {
                "buildConfiguration": "Debug",
                "selectedDebuggerIdentifier": "Xcode.DebuggerFoundation.Debugger.LLDB",
                "selectedLauncherIdentifier": "Xcode.DebuggerFoundation.Launcher.LLDB",
                "shouldUseLaunchSchemeArgsEnv": "YES",
                "shouldAutocreateTestPlan": "YES",
            },
            "TestAction",
        )
        require_child_tags(test, ["Testables"], "TestAction")
        testables = test[0]
        require_child_tags(testables, ["TestableReference", "TestableReference"], "Testables")
        for index, (blueprint, name) in enumerate((
            ("F20001", "XjieTests.xctest"),
            ("F300000000000000000001", "XjieUITests.xctest"),
        )):
            testable = testables[index]
            require_attributes(testable, {"skipped": "NO"}, f"TestableReference[{index}]")
            require_child_tags(testable, ["BuildableReference"], f"TestableReference[{index}]")
            require_reference(testable[0], blueprint, name, f"TestableReference[{index}] reference")

        require_attributes(
            launch,
            {
                "buildConfiguration": "Debug",
                "selectedDebuggerIdentifier": "Xcode.DebuggerFoundation.Debugger.LLDB",
                "selectedLauncherIdentifier": "Xcode.DebuggerFoundation.Launcher.LLDB",
                "launchStyle": "0",
                "useCustomWorkingDirectory": "NO",
                "ignoresPersistentStateOnLaunch": "NO",
                "debugDocumentVersioning": "YES",
                "debugServiceExtension": "internal",
                "allowLocationSimulation": "YES",
            },
            "LaunchAction",
        )
        require_child_tags(launch, ["BuildableProductRunnable"], "LaunchAction")
        require_attributes(launch[0], {"runnableDebuggingMode": "0"}, "Launch runnable")
        require_child_tags(launch[0], ["BuildableReference"], "Launch runnable")
        require_reference(launch[0][0], "F10001", "Xjie.app", "Launch reference")

        require_attributes(
            profile,
            {
                "buildConfiguration": "Release",
                "shouldUseLaunchSchemeArgsEnv": "YES",
                "savedToolIdentifier": "",
                "useCustomWorkingDirectory": "NO",
                "debugDocumentVersioning": "YES",
            },
            "ProfileAction",
        )
        require_child_tags(profile, ["BuildableProductRunnable"], "ProfileAction")
        require_attributes(profile[0], {"runnableDebuggingMode": "0"}, "Profile runnable")
        require_child_tags(profile[0], ["BuildableReference"], "Profile runnable")
        require_reference(profile[0][0], "F10001", "Xjie.app", "Profile reference")

        require_attributes(analyze, {"buildConfiguration": "Debug"}, "AnalyzeAction")
        require_child_tags(analyze, [], "AnalyzeAction")
        require_attributes(
            archive,
            {"buildConfiguration": "Release", "revealArchiveInOrganizer": "YES"},
            "ArchiveAction",
        )
        require_child_tags(archive, [], "ArchiveAction")
    except (IndexError, ValueError) as exc:
        violations.append(f"shared Xcode scheme structure is incomplete: {exc}")
    return violations


class GuardError(RuntimeError):
    pass


def project_version_identity(project_file: Path = PROJECT_FILE_PATH) -> dict[str, str]:
    try:
        source = project_file.read_text(encoding="utf-8")
    except (FileNotFoundError, UnicodeDecodeError) as exc:
        raise GuardError(f"cannot read Xcode project version settings: {project_file}") from exc

    def unique_numeric_setting(name: str, pattern: str) -> str:
        values = [
            match.group(1).strip()
            for match in re.finditer(
                rf"(?m)^\s*{re.escape(name)}\s*=\s*([^;]+);",
                source,
            )
        ]
        if not values:
            raise GuardError(f"Xcode project is missing {name}")
        invalid = sorted({value for value in values if re.fullmatch(pattern, value) is None})
        if invalid:
            raise GuardError(f"Xcode project has a non-numeric {name}: {', '.join(invalid)}")
        unique = sorted(set(values))
        if len(unique) != 1:
            raise GuardError(f"Xcode project must have one unique {name}: {', '.join(unique)}")
        return unique[0]

    return {
        "app_version": unique_numeric_setting(
            "MARKETING_VERSION", r"[0-9]+(?:\.[0-9]+)*"
        ),
        "app_build": unique_numeric_setting("CURRENT_PROJECT_VERSION", r"[1-9][0-9]*"),
    }


@dataclass(frozen=True)
class ChangeSet:
    paths: tuple[str, ...]
    added_lines: dict[str, tuple[str, ...]]


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise GuardError(f"missing required file: {path.relative_to(REPO_ROOT)}") from exc
    except json.JSONDecodeError as exc:
        raise GuardError(f"invalid JSON in {path.relative_to(REPO_ROOT)}: {exc}") from exc
    if not isinstance(value, dict):
        raise GuardError(f"top-level JSON must be an object: {path.relative_to(REPO_ROOT)}")
    return value


def load_registry() -> dict[str, Any]:
    return _load_json(REGISTRY_PATH)


def load_manifest() -> dict[str, Any]:
    return _load_json(MANIFEST_PATH)


def load_latest_development_record() -> dict[str, Any]:
    try:
        value = json.loads(DEVELOPMENT_RECORDS_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise GuardError(f"cannot load development_records.json: {exc}") from exc
    if not isinstance(value, list) or not value or not isinstance(value[-1], dict):
        raise GuardError("development_records.json must be a non-empty array of objects")
    return value[-1]


def _git(*args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise GuardError(f"git {' '.join(args)} failed: {detail}")
    return result.stdout


def _matches(path: str, patterns: Iterable[str]) -> bool:
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


def classify_test_changes(
    paths: Iterable[str], registry: dict[str, Any]
) -> tuple[dict[str, list[str]], list[str]]:
    mapped: dict[str, list[str]] = {}
    unmapped: list[str] = []
    domains = registry["behavior_domains"]
    for path in paths:
        matching = [
            domain["id"]
            for domain in domains
            if _matches(path, domain.get("test_patterns", []))
        ]
        if matching:
            for domain_id in matching:
                mapped.setdefault(domain_id, []).append(path)
        elif _looks_like_test_path(path):
            unmapped.append(path)
    return mapped, unmapped


def _repository_test_support_paths() -> list[str]:
    roots_and_suffixes = (
        (REPO_ROOT / "backend" / "tests", ".py"),
        (REPO_ROOT / "tools" / "tests", ".py"),
        (REPO_ROOT / "Xjie" / "XjieTests", ".swift"),
        (REPO_ROOT / "Xjie" / "XjieUITests", ".swift"),
    )
    paths: list[str] = []
    for root, suffix in roots_and_suffixes:
        if not root.is_dir():
            continue
        paths.extend(
            path.relative_to(REPO_ROOT).as_posix()
            for path in root.rglob(f"*{suffix}")
            if path.is_file()
        )
    return sorted(paths)


def _python_test_ids(source: str, *, path: str) -> set[str]:
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as exc:
        raise GuardError(f"cannot parse Python test inventory {path}: {exc}") from exc

    identifiers: set[str] = set()

    def visit_body(body: list[ast.stmt], prefix: tuple[str, ...] = ()) -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith("test_"):
                    identifiers.add(f"{path}::{'::'.join((*prefix, node.name))}")
                continue
            if isinstance(node, ast.ClassDef):
                visit_body(node.body, (*prefix, node.name))

    visit_body(tree.body)
    return identifiers


def python_test_inventory_at_revision(revision: str) -> set[str]:
    raw_paths = _git(
        "ls-tree", "-r", "--name-only", "-z", revision, "--", "backend/tests", "tools/tests"
    )
    paths = [
        path
        for path in raw_paths.split("\0")
        if path.endswith(".py")
        and (path.startswith("backend/tests/") or path.startswith("tools/tests/"))
    ]
    inventory: set[str] = set()
    for path in paths:
        inventory.update(_python_test_ids(_git("show", f"{revision}:{path}"), path=path))
    return inventory


def _python_runtime_profiles(
    payload: dict[str, Any], *, source: str
) -> dict[str, set[str]]:
    if payload.get("schema_version") != 1:
        raise GuardError(f"{source} schema_version must be 1")
    if tuple(key for key in payload if key != "schema_version") != EXPECTED_PYTHON_TEST_PROFILES:
        raise GuardError(
            f"{source} profiles must be ordered exactly as: "
            + ", ".join(EXPECTED_PYTHON_TEST_PROFILES)
        )
    profiles: dict[str, set[str]] = {}
    for profile in EXPECTED_PYTHON_TEST_PROFILES:
        values = payload.get(profile)
        if not isinstance(values, list) or not values:
            raise GuardError(f"{source} profile is empty: {profile}")
        if values != sorted(values) or len(values) != len(set(values)):
            raise GuardError(f"{source} profile must be sorted and duplicate-free: {profile}")
        if any(not isinstance(value, str) or not value.strip() for value in values):
            raise GuardError(f"{source} profile has an invalid test identifier: {profile}")
        profiles[profile] = set(values)
    if any("::" not in value for value in profiles["backend_full"]):
        raise GuardError(f"{source} backend_full contains a non-pytest identifier")
    if any("." not in value or "::" in value for value in profiles["tools"]):
        raise GuardError(f"{source} tools contains a non-unittest identifier")
    return profiles


def _load_python_runtime_profiles_text(
    raw: str, *, source: str
) -> dict[str, set[str]]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GuardError(f"cannot parse {source}: {exc}") from exc
    if not isinstance(payload, dict):
        raise GuardError(f"{source} must be a JSON object")
    return _python_runtime_profiles(payload, source=source)


def python_runtime_inventory_at_revision(
    revision: str,
    *,
    allow_missing: bool = False,
) -> dict[str, set[str]]:
    path = EXPECTED_PYTHON_TESTS_PATH.relative_to(REPO_ROOT).as_posix()
    exists = subprocess.run(
        ["git", "cat-file", "-e", f"{revision}:{path}"],
        cwd=REPO_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if exists.returncode != 0:
        if allow_missing:
            return {profile: set() for profile in EXPECTED_PYTHON_TEST_PROFILES}
        raise GuardError(f"Python runtime inventory is missing from candidate {revision}:{path}")
    return _load_python_runtime_profiles_text(
        _git("show", f"{revision}:{path}"),
        source=f"{revision}:{path}",
    )


def _validate_python_runtime_inventory_monotonic(
    previous: dict[str, set[str]],
    candidate: dict[str, set[str]],
) -> tuple[int, int]:
    removed = {
        profile: sorted(previous[profile] - candidate[profile])
        for profile in EXPECTED_PYTHON_TEST_PROFILES
        if previous[profile] - candidate[profile]
    }
    if removed:
        details = "; ".join(
            f"{profile}=" + ", ".join(identifiers)
            for profile, identifiers in removed.items()
        )
        raise GuardError(
            "Python runtime inventory must be monotonic; existing tests were removed, "
            "renamed, collection-disabled, or parameterization-shrunk: " + details
        )
    return (
        sum(len(previous[profile]) for profile in EXPECTED_PYTHON_TEST_PROFILES),
        sum(len(candidate[profile]) for profile in EXPECTED_PYTHON_TEST_PROFILES),
    )


def validate_python_test_inventory_range(base: str, head: str) -> tuple[int, int]:
    resolved_base = _existing_commit_or_parent(base, head)
    previous = python_test_inventory_at_revision(resolved_base)
    candidate = python_test_inventory_at_revision(head)
    missing = sorted(previous - candidate)
    if missing:
        raise GuardError(
            "Python test inventory must be monotonic; existing test IDs were removed or renamed: "
            + ", ".join(missing)
        )
    return _validate_python_runtime_inventory_monotonic(
        python_runtime_inventory_at_revision(resolved_base, allow_missing=True),
        python_runtime_inventory_at_revision(head),
    )


def _xctest_profiles(payload: dict[str, Any], *, source: str) -> dict[str, set[str]]:
    if payload.get("schema_version") != 1:
        raise GuardError(f"{source} schema_version must be 1")
    raw_profiles = payload.get("profiles")
    if not isinstance(raw_profiles, dict) or tuple(raw_profiles) != EXPECTED_XCTEST_PROFILES:
        raise GuardError(
            f"{source} profiles must be ordered exactly as: "
            + ", ".join(EXPECTED_XCTEST_PROFILES)
        )
    profiles: dict[str, set[str]] = {}
    identifier = re.compile(
        r"^[A-Za-z_][A-Za-z0-9_]*/[A-Za-z_][A-Za-z0-9_]*/test[A-Za-z0-9_]+$"
    )
    for profile in EXPECTED_XCTEST_PROFILES:
        values = raw_profiles.get(profile)
        if not isinstance(values, list) or not values:
            raise GuardError(f"{source} profile is empty: {profile}")
        if values != sorted(values) or len(values) != len(set(values)):
            raise GuardError(f"{source} profile must be sorted and duplicate-free: {profile}")
        if any(not isinstance(value, str) or identifier.fullmatch(value) is None for value in values):
            raise GuardError(f"{source} profile has an invalid test identifier: {profile}")
        profiles[profile] = set(values)
    if any(not value.startswith("XjieTests/") for value in profiles["ios_unit"]):
        raise GuardError(f"{source} ios_unit contains a non-unit test")
    if any(not value.startswith("XjieUITests/") for value in profiles["ios_ui_full"]):
        raise GuardError(f"{source} ios_ui_full contains a non-UI test")
    if not profiles["ios_ui_small"].issubset(profiles["ios_ui_full"]):
        raise GuardError(f"{source} ios_ui_small is not a subset of ios_ui_full")
    if profiles["ios_all"] != profiles["ios_unit"] | profiles["ios_ui_full"]:
        raise GuardError(f"{source} ios_all is not the exact unit/UI union")
    return profiles


def _load_xctest_profiles_text(raw: str, *, source: str) -> dict[str, set[str]]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GuardError(f"cannot parse {source}: {exc}") from exc
    if not isinstance(payload, dict):
        raise GuardError(f"{source} must be a JSON object")
    return _xctest_profiles(payload, source=source)


def xctest_inventory_at_revision(
    revision: str,
    *,
    allow_missing: bool = False,
) -> dict[str, set[str]]:
    path = EXPECTED_XCTESTS_PATH.relative_to(REPO_ROOT).as_posix()
    exists = subprocess.run(
        ["git", "cat-file", "-e", f"{revision}:{path}"],
        cwd=REPO_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if exists.returncode != 0:
        if allow_missing:
            return {profile: set() for profile in EXPECTED_XCTEST_PROFILES}
        raise GuardError(f"XCTest inventory is missing from candidate {revision}:{path}")
    return _load_xctest_profiles_text(
        _git("show", f"{revision}:{path}"),
        source=f"{revision}:{path}",
    )


def _validate_xctest_inventory_monotonic(
    previous: dict[str, set[str]],
    candidate: dict[str, set[str]],
) -> tuple[int, int]:
    removed = {
        profile: sorted(previous[profile] - candidate[profile])
        for profile in EXPECTED_XCTEST_PROFILES
        if previous[profile] - candidate[profile]
    }
    if removed:
        details = "; ".join(
            f"{profile}=" + ", ".join(identifiers)
            for profile, identifiers in removed.items()
        )
        raise GuardError(
            "XCTest inventory must be monotonic; existing tests were removed or renamed: "
            + details
        )
    return len(previous["ios_all"]), len(candidate["ios_all"])


def validate_xctest_inventory_range(base: str, head: str) -> tuple[int, int]:
    resolved_base = _existing_commit_or_parent(base, head)
    return _validate_xctest_inventory_monotonic(
        xctest_inventory_at_revision(resolved_base, allow_missing=True),
        xctest_inventory_at_revision(head),
    )


def _current_swift_xctest_inventory() -> dict[str, set[str]]:
    inventories = {"ios_unit": set(), "ios_ui_full": set()}
    for target, directory, profile in (
        ("XjieTests", REPO_ROOT / "Xjie" / "XjieTests", "ios_unit"),
        ("XjieUITests", REPO_ROOT / "Xjie" / "XjieUITests", "ios_ui_full"),
    ):
        if not directory.is_dir():
            raise GuardError(f"missing XCTest source directory: {directory}")
        for path in sorted(directory.rglob("*.swift")):
            source = path.read_text(encoding="utf-8")
            methods = re.findall(r"^\s*func\s+(test[A-Za-z0-9_]+)\s*\(", source, re.MULTILINE)
            if not methods:
                continue
            classes = re.findall(
                r"^\s*(?:final\s+)?class\s+([A-Za-z_][A-Za-z0-9_]*)\s*:\s*"
                r"(?:XCTestCase|XAgeUITestCase)\b",
                source,
                re.MULTILINE,
            )
            if len(classes) != 1:
                raise GuardError(
                    "XCTest source with tests must contain exactly one recognized class: "
                    + str(path.relative_to(REPO_ROOT))
                )
            inventories[profile].update(
                f"{target}/{classes[0]}/{method}" for method in methods
            )
    return inventories


def validate_current_xctest_inventory() -> None:
    profiles = _xctest_profiles(_load_json(EXPECTED_XCTESTS_PATH), source="expected_xctests.json")
    source = _current_swift_xctest_inventory()
    for profile in ("ios_unit", "ios_ui_full"):
        if source[profile] != profiles[profile]:
            missing = sorted(profiles[profile] - source[profile])
            untracked = sorted(source[profile] - profiles[profile])
            raise GuardError(
                f"Swift source does not exactly match {profile}; "
                f"manifest_only={missing[:5]}, source_only={untracked[:5]}"
            )


def _parse_added_lines(diff_text: str) -> dict[str, tuple[str, ...]]:
    result: dict[str, list[str]] = {}
    current_path: str | None = None
    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            current_path = line[6:]
            result.setdefault(current_path, [])
            continue
        if line.startswith("+++ /dev/null"):
            current_path = None
            continue
        if current_path is not None and line.startswith("+") and not line.startswith("+++"):
            result[current_path].append(line[1:])
    return {path: tuple(lines) for path, lines in result.items()}


def _parse_name_status(raw: str) -> list[str]:
    tokens = raw.split("\0")
    if tokens and tokens[-1] == "":
        tokens.pop()
    paths: list[str] = []
    index = 0
    while index < len(tokens):
        status = tokens[index]
        index += 1
        if not re.fullmatch(r"[ACDMRT](?:\d{1,3})?", status):
            raise GuardError(f"malformed git name-status entry: {status!r}")
        path_count = 2 if status[0] in {"R", "C"} else 1
        if index + path_count > len(tokens):
            raise GuardError(f"incomplete git name-status entry for {status!r}")
        entry_paths = tokens[index : index + path_count]
        if any(not path for path in entry_paths):
            raise GuardError(f"empty path in git name-status entry for {status!r}")
        paths.extend(entry_paths)
        index += path_count
    return paths


def _existing_commit_or_parent(candidate: str, head: str) -> str:
    if candidate and set(candidate) == {"0"}:
        parent = _git("rev-parse", f"{head}^").strip()
        if not parent:
            raise GuardError(f"cannot determine comparison base for {head}")
        return parent
    if not candidate:
        raise GuardError("comparison base must not be empty")
    result = subprocess.run(
        ["git", "cat-file", "-e", f"{candidate}^{{commit}}"],
        cwd=REPO_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if result.returncode != 0:
        raise GuardError(f"explicit comparison base is not a local commit: {candidate}")
    return candidate


def collect_changes(
    *, staged: bool = False, working: bool = False, base: str | None = None, head: str = "HEAD"
) -> ChangeSet:
    selected = sum((staged, working, base is not None))
    if selected != 1:
        raise GuardError("select exactly one change source: --staged, --working, or --base")

    if staged:
        name_args = (
            "diff", "--cached", "--name-status", "-z", "-M", "-C", "--find-copies-harder",
            "--diff-filter=ACDMRT",
        )
        diff_args = (
            "diff", "--cached", "--unified=0", "-M", "-C", "--find-copies-harder",
            "--diff-filter=ACMRD",
        )
        paths = _parse_name_status(_git(*name_args))
        return ChangeSet(tuple(sorted(set(paths))), _parse_added_lines(_git(*diff_args)))

    if working:
        paths = _parse_name_status(
            _git(
                "diff", "HEAD", "--name-status", "-z", "-M", "-C", "--find-copies-harder",
                "--diff-filter=ACDMRT",
            )
        )
        added = _parse_added_lines(
            _git(
                "diff", "HEAD", "--unified=0", "-M", "-C", "--find-copies-harder",
                "--diff-filter=ACMRD",
            )
        )
        untracked = [
            line
            for line in _git("ls-files", "--others", "--exclude-standard").splitlines()
            if line
        ]
        for path in untracked:
            file_path = REPO_ROOT / path
            if file_path.is_file():
                try:
                    added[path] = tuple(file_path.read_text(encoding="utf-8").splitlines())
                except UnicodeDecodeError:
                    added[path] = ()
        paths.extend(untracked)
        return ChangeSet(tuple(sorted(set(paths))), added)

    assert base is not None
    resolved_base = _existing_commit_or_parent(base, head)
    paths = _parse_name_status(
        _git(
            "diff", resolved_base, head, "--name-status", "-z", "-M", "-C",
            "--find-copies-harder", "--diff-filter=ACDMRT",
        )
    )
    diff_text = _git(
        "diff", resolved_base, head, "--unified=0", "-M", "-C", "--find-copies-harder",
        "--diff-filter=ACMRD",
    )
    return ChangeSet(tuple(sorted(set(paths))), _parse_added_lines(diff_text))


def validate_registry(registry: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    normalized_registry = json.dumps(
        registry,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if hashlib.sha256(normalized_registry).hexdigest() != PINNED_REGRESSION_REGISTRY_SHA256:
        errors.append(
            "regression_contracts.json normalized definition changed from the pinned digest"
        )
    try:
        project_version_identity()
    except GuardError as exc:
        errors.append(str(exc))
    try:
        _python_runtime_profiles(
            _load_json(EXPECTED_PYTHON_TESTS_PATH),
            source="expected_python_tests.json",
        )
    except GuardError as exc:
        errors.append(str(exc))
    try:
        validate_current_xctest_inventory()
    except GuardError as exc:
        errors.append(str(exc))
    if registry.get("schema_version") != 2:
        errors.append("regression_contracts.json schema_version must be 2")

    domains = registry.get("behavior_domains")
    if not isinstance(domains, list) or not domains:
        errors.append("behavior_domains must be a non-empty list")
        domains = []
    domain_ids: set[str] = set()
    for domain in domains:
        if not isinstance(domain, dict):
            errors.append("every behavior domain must be an object")
            continue
        domain_id = domain.get("id")
        if not isinstance(domain_id, str) or not domain_id:
            errors.append("every behavior domain needs a non-empty id")
            continue
        if domain_id in domain_ids:
            errors.append(f"duplicate behavior domain id: {domain_id}")
        domain_ids.add(domain_id)
        for field in ("source_patterns", "test_patterns", "meaningful_test_patterns", "verification_commands"):
            if not isinstance(domain.get(field), list) or not domain[field]:
                errors.append(f"domain {domain_id} requires non-empty {field}")
        required_contract_ids = domain.get("required_contract_ids")
        if not isinstance(required_contract_ids, list) or not required_contract_ids:
            errors.append(f"domain {domain_id} requires non-empty required_contract_ids")
        elif any(
            not isinstance(contract_id, str) or not contract_id
            for contract_id in required_contract_ids
        ):
            errors.append(
                f"domain {domain_id} required_contract_ids must contain non-empty strings"
            )
        elif len(set(required_contract_ids)) != len(required_contract_ids):
            errors.append(f"domain {domain_id} required_contract_ids must be unique")
        else:
            pinned_contract_ids = PINNED_DOMAIN_REQUIRED_CONTRACT_IDS.get(domain_id)
            if pinned_contract_ids is None:
                errors.append(
                    f"domain {domain_id} is not present in the pinned required-contract mapping"
                )
            elif tuple(required_contract_ids) != pinned_contract_ids:
                errors.append(
                    f"domain {domain_id} required_contract_ids changed from the pinned mapping"
                )

    pinned_domain_ids = set(PINNED_DOMAIN_REQUIRED_CONTRACT_IDS)
    if domain_ids != pinned_domain_ids:
        missing_domain_ids = sorted(pinned_domain_ids - domain_ids)
        unexpected_domain_ids = sorted(domain_ids - pinned_domain_ids)
        details: list[str] = []
        if missing_domain_ids:
            details.append("missing " + ", ".join(missing_domain_ids))
        if unexpected_domain_ids:
            details.append("unexpected " + ", ".join(unexpected_domain_ids))
        errors.append(
            "behavior domain ids must match the pinned required-contract mapping: "
            + "; ".join(details)
        )

    commands = registry.get("commands")
    if not isinstance(commands, dict) or not commands:
        errors.append("commands must be a non-empty object")
        commands = {}
    for domain in domains:
        if not isinstance(domain, dict):
            continue
        for command_id in domain.get("verification_commands", []):
            if command_id not in commands:
                errors.append(f"domain {domain.get('id')} references unknown command {command_id}")
        domain_id = domain.get("id")
        if isinstance(domain_id, str) and domain_id.startswith("ios_"):
            if "ios_release_build" not in domain.get("verification_commands", []):
                errors.append(f"iOS domain {domain_id} must run ios_release_build")

    for path in _repository_test_support_paths():
        if not any(_matches(path, domain.get("test_patterns", [])) for domain in domains):
            errors.append(
                "test/support file is not mapped to a regression domain: " + path
            )
    for command_id, template in MANDATORY_RELEASE_COMMAND_TEMPLATES.items():
        if commands.get(command_id) != template:
            errors.append(f"mandatory release command template changed: {command_id}")
    for command_id, template in PINNED_FOCUSED_BACKEND_COMMAND_TEMPLATES.items():
        if commands.get(command_id) != template:
            errors.append(f"focused backend command selection changed: {command_id}")

    process_domain = next(
        (item for item in domains if isinstance(item, dict) and item.get("id") == "quality_process_gate"),
        None,
    )
    if process_domain is None:
        errors.append("mandatory quality_process_gate domain is missing")
    else:
        missing_patterns = MANDATORY_PROCESS_SOURCE_PATTERNS - set(
            process_domain.get("source_patterns", [])
        )
        if missing_patterns:
            errors.append(
                "quality_process_gate is missing protected source patterns: "
                + ", ".join(sorted(missing_patterns))
            )
        if "tools/tests/**/*.py" not in process_domain.get("test_patterns", []):
            errors.append("quality_process_gate must require tools/tests/**/*.py")
        if not {"guard_unit", "diff_check", "ios_release_build"}.issubset(
            set(process_domain.get("verification_commands", []))
        ):
            errors.append(
                "quality_process_gate must run guard_unit, diff_check and ios_release_build"
            )

    integrity_domain = next(
        (item for item in domains if isinstance(item, dict) and item.get("id") == "test_suite_integrity"),
        None,
    )
    if integrity_domain is None:
        errors.append("mandatory test_suite_integrity domain is missing")
    else:
        for field in ("source_patterns", "test_patterns"):
            missing_patterns = MANDATORY_TEST_INTEGRITY_PATTERNS - set(
                integrity_domain.get(field, [])
            )
            if missing_patterns:
                errors.append(
                    f"test_suite_integrity is missing protected {field}: "
                    + ", ".join(sorted(missing_patterns))
                )
        if not {"guard_unit", "diff_check", "ios_release_build"}.issubset(
            set(integrity_domain.get("verification_commands", []))
        ):
            errors.append(
                "test_suite_integrity must run guard_unit, diff_check and ios_release_build"
            )

    backend_core_domain = next(
        (item for item in domains if isinstance(item, dict) and item.get("id") == "backend_core"),
        None,
    )
    if backend_core_domain is None:
        errors.append("mandatory backend_core domain is missing")
    else:
        missing_patterns = MANDATORY_BACKEND_CORE_SOURCE_PATTERNS - set(
            backend_core_domain.get("source_patterns", [])
        )
        if missing_patterns:
            errors.append(
                "backend_core is missing deployment/migration source patterns: "
                + ", ".join(sorted(missing_patterns))
            )
        if not {"backend_full", "guard_unit", "diff_check"}.issubset(
            set(backend_core_domain.get("verification_commands", []))
        ):
            errors.append("backend_core must run backend_full, guard_unit and diff_check")

    backend_health_domain = next(
        (
            item
            for item in domains
            if isinstance(item, dict) and item.get("id") == "backend_health_sync"
        ),
        None,
    )
    if backend_health_domain is None:
        errors.append("mandatory backend_health_sync domain is missing")
    else:
        missing_patterns = MANDATORY_BACKEND_MIGRATION_SOURCE_PATTERNS - set(
            backend_health_domain.get("source_patterns", [])
        )
        if missing_patterns:
            errors.append(
                "backend_health_sync is missing migration source patterns: "
                + ", ".join(sorted(missing_patterns))
            )
        if not {"backend_full", "guard_unit", "diff_check"}.issubset(
            set(backend_health_domain.get("verification_commands", []))
        ):
            errors.append(
                "backend_health_sync migration changes must run backend_full, guard_unit and diff_check"
            )

    overrides = registry.get("conservative_overrides", [])
    if not isinstance(overrides, list):
        errors.append("conservative_overrides must be a list")
        overrides = []
    for override in overrides:
        if not isinstance(override, dict) or not override.get("pattern"):
            errors.append("every conservative override needs a pattern")
            continue
        unknown = set(override.get("verification_domains", [])) - domain_ids
        if unknown:
            errors.append(
                f"override {override.get('pattern')} references unknown domains: {', '.join(sorted(unknown))}"
            )

    contracts = registry.get("contracts")
    if not isinstance(contracts, list) or not contracts:
        errors.append("contracts must be a non-empty list")
        contracts = []
    contract_ids: set[str] = set()
    for contract in contracts:
        if not isinstance(contract, dict):
            errors.append("every contract must be an object")
            continue
        contract_id = contract.get("id")
        if not isinstance(contract_id, str) or not contract_id:
            errors.append("every contract needs a non-empty id")
            continue
        if contract_id in contract_ids:
            errors.append(f"duplicate contract id: {contract_id}")
        contract_ids.add(contract_id)
        contract_domains = contract.get("domains")
        if not isinstance(contract_domains, list) or not contract_domains:
            errors.append(f"contract {contract_id} requires non-empty domains")
            contract_domains = []
        elif any(not isinstance(domain_id, str) or not domain_id for domain_id in contract_domains):
            errors.append(f"contract {contract_id} domains must contain non-empty strings")
            contract_domains = []
        elif len(set(contract_domains)) != len(contract_domains):
            errors.append(f"contract {contract_id} domains must be unique")
        unknown = set(contract_domains) - domain_ids
        if unknown:
            errors.append(f"contract {contract_id} references unknown domains: {', '.join(sorted(unknown))}")
        if not str(contract.get("invariant", "")).strip():
            errors.append(f"contract {contract_id} requires an invariant")
        anchors = contract.get("test_anchors")
        if not isinstance(anchors, list) or not anchors:
            errors.append(f"contract {contract_id} requires test_anchors")
            continue
        for anchor in anchors:
            if not isinstance(anchor, dict):
                errors.append(f"contract {contract_id} contains a non-object test anchor")
                continue
            path = anchor.get("path")
            symbol = anchor.get("symbol")
            if not isinstance(path, str) or not isinstance(symbol, str):
                errors.append(f"contract {contract_id} has an invalid test anchor")
                continue
            target = REPO_ROOT / path
            if not target.is_file():
                errors.append(f"contract {contract_id} anchor file does not exist: {path}")
                continue
            try:
                content = target.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                errors.append(f"contract {contract_id} anchor is not UTF-8 text: {path}")
                continue
            if symbol not in content:
                errors.append(f"contract {contract_id} anchor symbol missing: {path}::{symbol}")

    pinned_contract_domains: dict[str, tuple[str, ...]] = {}
    for domain_id, required_contract_ids in PINNED_DOMAIN_REQUIRED_CONTRACT_IDS.items():
        for contract_id in required_contract_ids:
            pinned_contract_domains.setdefault(contract_id, tuple())
            pinned_contract_domains[contract_id] = (
                *pinned_contract_domains[contract_id],
                domain_id,
            )
    pinned_contract_ids = set(pinned_contract_domains)
    if set(PINNED_CONTRACT_DEFINITION_SHA256) != pinned_contract_ids:
        errors.append(
            "pinned contract definition digests must match the pinned domain contract ids"
        )
    if contract_ids != pinned_contract_ids:
        missing_contract_ids = sorted(pinned_contract_ids - contract_ids)
        unexpected_contract_ids = sorted(contract_ids - pinned_contract_ids)
        details = []
        if missing_contract_ids:
            details.append("missing " + ", ".join(missing_contract_ids))
        if unexpected_contract_ids:
            details.append("unexpected " + ", ".join(unexpected_contract_ids))
        errors.append(
            "regression contract ids must match the pinned domain mapping: "
            + "; ".join(details)
        )
    for contract in contracts:
        if not isinstance(contract, dict):
            continue
        contract_id = contract.get("id")
        expected_domains = pinned_contract_domains.get(contract_id)
        if expected_domains is None:
            continue
        actual_domains = contract.get("domains")
        if not isinstance(actual_domains, list) or tuple(actual_domains) != expected_domains:
            errors.append(
                f"contract {contract_id} domains changed from the pinned required-contract reverse mapping"
            )
        normalized_contract = json.dumps(
            contract,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        actual_definition_sha256 = hashlib.sha256(normalized_contract).hexdigest()
        expected_definition_sha256 = PINNED_CONTRACT_DEFINITION_SHA256.get(contract_id)
        if actual_definition_sha256 != expected_definition_sha256:
            errors.append(
                f"contract {contract_id} invariant/anchor definition changed from the pinned digest"
            )

    contract_by_id = {
        item.get("id"): item for item in contracts if isinstance(item, dict)
    }
    covered_domain_ids = {
        domain_id
        for contract in contracts
        if isinstance(contract, dict)
        for domain_id in contract.get("domains", [])
        if isinstance(domain_id, str)
    }
    uncovered_domain_ids = domain_ids - covered_domain_ids
    if uncovered_domain_ids:
        errors.append(
            "behavior domains require at least one regression contract: "
            + ", ".join(sorted(uncovered_domain_ids))
        )
    process_contract = contract_by_id.get("PROCESS-GATE-001")
    if not isinstance(process_contract, dict) or "quality_process_gate" not in process_contract.get(
        "domains", []
    ):
        errors.append("PROCESS-GATE-001 must protect quality_process_gate")
    integrity_contract = contract_by_id.get("TEST-SUITE-INTEGRITY-001")
    if not isinstance(integrity_contract, dict) or "test_suite_integrity" not in integrity_contract.get(
        "domains", []
    ):
        errors.append("TEST-SUITE-INTEGRITY-001 must protect test_suite_integrity")
    release_contract = contract_by_id.get("RELEASE-GATE-001")
    if not isinstance(release_contract, dict) or "quality_process_gate" not in release_contract.get(
        "domains", []
    ):
        errors.append("RELEASE-GATE-001 must protect quality_process_gate")
    backend_core_contract = contract_by_id.get("BACKEND-CORE-001")
    if not isinstance(backend_core_contract, dict) or "backend_core" not in backend_core_contract.get(
        "domains", []
    ):
        errors.append("BACKEND-CORE-001 must protect backend_core")

    for limit in registry.get("architecture_limits", []):
        if not isinstance(limit, dict) or not isinstance(limit.get("path"), str):
            errors.append("every architecture limit requires a path")
            continue
        path = limit["path"]
        target = REPO_ROOT / path
        if not target.is_file():
            errors.append(f"architecture limit target does not exist: {path}")
            continue
        content = target.read_text(encoding="utf-8")
        max_lines = limit.get("max_lines")
        if isinstance(max_lines, int) and len(content.splitlines()) > max_lines:
            errors.append(
                f"architecture limit exceeded: {path} has {len(content.splitlines())} lines, max {max_lines}; "
                "extract responsibilities instead of adding more"
            )
        for pattern_limit in limit.get("pattern_limits", []):
            try:
                count = len(re.findall(pattern_limit["pattern"], content))
                maximum = int(pattern_limit["max_count"])
            except (KeyError, TypeError, ValueError, re.error) as exc:
                errors.append(f"invalid pattern limit for {path}: {exc}")
                continue
            if count > maximum:
                errors.append(
                    f"architecture limit exceeded: {path} has {count} {pattern_limit.get('name', 'matches')}, "
                    f"max {maximum}"
                )
        for forbidden in limit.get("forbidden_patterns", []):
            try:
                found = re.search(forbidden["pattern"], content)
            except (KeyError, TypeError, re.error) as exc:
                errors.append(f"invalid forbidden pattern for {path}: {exc}")
                continue
            if found:
                errors.append(f"forbidden architecture reference in {path}: {forbidden.get('name', forbidden)}")

    release_gate = registry.get("release_gate")
    if not isinstance(release_gate, dict):
        errors.append("release_gate must be an object")
    else:
        pinned_identity = {
            "github_repository": PINNED_GITHUB_REPOSITORY,
            "github_workflow": PINNED_GITHUB_WORKFLOW,
            "required_check": PINNED_REQUIRED_CHECK,
            "protected_branches": PINNED_PROTECTED_BRANCHES,
            "max_age_hours": PINNED_MAX_AGE_HOURS,
            "latest_uploaded_build": PINNED_LATEST_UPLOADED_BUILD,
        }
        for field, expected in pinned_identity.items():
            if release_gate.get(field) != expected:
                errors.append(f"release_gate pinned identity changed: {field}")
        required_check = release_gate.get("required_check")
        if not isinstance(required_check, dict):
            errors.append("release_gate required_check must be an object")
        else:
            for field in ("name", "app_slug"):
                if not isinstance(required_check.get(field), str) or not required_check[field].strip():
                    errors.append(f"release_gate required_check requires non-empty {field}")
            if not isinstance(required_check.get("app_id"), int) or required_check["app_id"] <= 0:
                errors.append("release_gate required_check requires a positive app_id")
        branch_protection = release_gate.get("branch_protection")
        if branch_protection != PINNED_BRANCH_PROTECTION:
            errors.append("release_gate branch_protection must exactly enforce the pinned PR workflow")
        if release_gate.get("protected_branches") != PINNED_PROTECTED_BRANCHES:
            errors.append("release_gate protected_branches must exactly be ['XAGE', 'main']")
        signoffs = release_gate.get("manual_signoffs")
        if not isinstance(signoffs, list):
            errors.append("release_gate manual_signoffs must be a list")
        else:
            signoff_ids = [item.get("id") for item in signoffs if isinstance(item, dict)]
            if signoff_ids != list(MANDATORY_RELEASE_SIGNOFFS) or len(signoff_ids) != len(signoffs):
                errors.append(
                    "release_gate manual_signoffs must contain the exact mandatory ordered IDs"
                )
            for item in signoffs:
                if not isinstance(item, dict) or not isinstance(item.get("description"), str) \
                        or len(item["description"].strip()) < 8:
                    errors.append("every release manual signoff requires a meaningful description")
        if release_gate.get("required_commands") != list(MANDATORY_RELEASE_COMMANDS):
            errors.append("release_gate required_commands must exactly match mandatory full gates")
        for command_id in release_gate.get("required_commands", []):
            if command_id not in commands:
                errors.append(f"release_gate references unknown command {command_id}")

    try:
        signoff_template = _load_json(SIGNOFF_TEMPLATE_PATH)
    except GuardError as exc:
        errors.append(str(exc))
    else:
        for field in ("head", "tree", "registry_blob", "completed_at"):
            if not str(signoff_template.get(field, "")).startswith("REPLACE_WITH_"):
                errors.append(f"release signoff template {field} must remain a placeholder")
        items = signoff_template.get("items")
        template_ids = [item.get("id") for item in items if isinstance(item, dict)] \
            if isinstance(items, list) else []
        if signoff_template.get("schema_version") != 1 \
                or template_ids != list(MANDATORY_RELEASE_SIGNOFFS) \
                or not isinstance(items, list) or len(template_ids) != len(items):
            errors.append("release signoff template must contain the exact mandatory ordered items")
        elif any(
            item.get("status") != "pending"
            or item.get("tester") != ""
            or item.get("app_version") != "REPLACE_WITH_MARKETING_VERSION"
            or item.get("app_build") != "REPLACE_WITH_CURRENT_PROJECT_VERSION"
            or not str(item.get("tested_at", "")).startswith("REPLACE_WITH_")
            or not str(item.get("environment", "")).startswith("填写")
            or not isinstance(item.get("steps"), list)
            or len(item["steps"]) < 2
            or any(not str(step).startswith("填写") for step in item["steps"])
            or not str(item.get("evidence_reference", "")).startswith("填写")
            or ".quality/evidence/" not in str(item.get("evidence_reference", ""))
            or "://" in str(item.get("evidence_reference", ""))
            or item.get("evidence_sha256") != ""
            for item in items
        ):
            errors.append("release signoff template must remain pending, blank and placeholder-only")

    source_roots = (
        REPO_ROOT / "Xjie" / "Xjie",
        REPO_ROOT / "Xjie" / "XjieTests",
        REPO_ROOT / "Xjie" / "XjieUITests",
    )
    filesystem_errors = repository_filesystem_identity_violations(
        REPO_ROOT,
        source_roots,
        (PROJECT_FILE_PATH, SHARED_SCHEME_PATH),
    )
    errors.extend(filesystem_errors)
    if filesystem_errors:
        return errors

    all_swift_files: list[Path] = []
    for path in sorted(REPO_ROOT.rglob("*.swift")):
        if ".git" in path.relative_to(REPO_ROOT).parts:
            continue
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            errors.append(f"Swift source disappeared during validation: {path}")
            continue
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            errors.append(
                "Swift source must be a regular non-symlink file: "
                + path.relative_to(REPO_ROOT).as_posix()
            )
            continue
        all_swift_files.append(path)
    all_swift_paths = {
        path.relative_to(REPO_ROOT).as_posix()
        for path in all_swift_files
    }
    project_source = PROJECT_FILE_PATH.read_text(encoding="utf-8")
    errors.extend(swift_source_layout_violations(all_swift_paths, project_source))
    errors.extend(xcode_release_build_setting_violations(project_source))
    shared_scheme_root = SHARED_SCHEME_PATH.parent
    shared_schemes = sorted(
        path for path in shared_scheme_root.glob("*.xcscheme")
        if path.exists() or path.is_symlink()
    ) if shared_scheme_root.is_dir() else []
    if shared_schemes != [SHARED_SCHEME_PATH]:
        errors.append(
            "Xcode project must contain exactly the pinned shared Xjie scheme; got "
            + ", ".join(path.name for path in shared_schemes)
        )
    else:
        scheme_metadata = SHARED_SCHEME_PATH.lstat()
        if stat.S_ISLNK(scheme_metadata.st_mode) or not stat.S_ISREG(scheme_metadata.st_mode):
            errors.append("shared Xcode scheme must be a regular non-symlink file")
        else:
            errors.extend(
                xcode_scheme_violations(SHARED_SCHEME_PATH.read_text(encoding="utf-8"))
            )
    swift_sources: dict[str, str] = {}
    for path in all_swift_files:
        repo_path = path.relative_to(REPO_ROOT).as_posix()
        if repo_path.startswith("Xjie/XjieTests/"):
            continue
        if repo_path.startswith("Xjie/Xjie/"):
            policy_path = repo_path.removeprefix("Xjie/Xjie/")
        elif repo_path.startswith("Xjie/XjieUITests/"):
            policy_path = "XjieUITests/" + repo_path.removeprefix("Xjie/XjieUITests/")
        else:
            policy_path = "ExternalSources/" + repo_path
        swift_sources[policy_path] = path.read_text(encoding="utf-8")
    errors.extend(network_transport_violations(swift_sources))
    errors.extend(deterministic_system_boundary_violations(swift_sources))

    return errors


def classify_changes(
    paths: Iterable[str], registry: dict[str, Any]
) -> tuple[dict[str, list[str]], set[str]]:
    domains = registry["behavior_domains"]
    path_list = list(paths)
    test_mapping, unmapped_tests = classify_test_changes(path_list, registry)
    test_domains_by_path: dict[str, set[str]] = {}
    for domain_id, matching_paths in test_mapping.items():
        for path in matching_paths:
            test_domains_by_path.setdefault(path, set()).add(domain_id)
    primary: dict[str, list[str]] = {}
    production_candidates: list[str] = []
    for path in path_list:
        is_ios = path.startswith("Xjie/Xjie/") and path.endswith(".swift")
        is_backend = path.startswith("backend/app/") and path.endswith(".py")
        matching_source_domains = [
            domain["id"]
            for domain in domains
            if _matches(path, domain["source_patterns"])
        ]
        matched_domain = matching_source_domains[0] if matching_source_domains else None
        mapped_test_domains = test_domains_by_path.get(path, set())
        if mapped_test_domains:
            for domain_id in sorted(mapped_test_domains):
                primary.setdefault(domain_id, []).append(path)
            for domain_id in matching_source_domains:
                if domain_id not in mapped_test_domains:
                    primary.setdefault(domain_id, []).append(path)
            if matching_source_domains:
                production_candidates.append(path)
            continue
        if _looks_like_test_path(path):
            continue
        if not (is_ios or is_backend or matched_domain is not None):
            continue
        production_candidates.append(path)
        if matched_domain is None:
            primary.setdefault("__unmapped__", []).append(path)
        else:
            primary.setdefault(matched_domain, []).append(path)

    verification = {
        domain_id for domain_id in primary if domain_id != "__unmapped__"
    } | set(test_mapping)
    for path in production_candidates:
        for override in registry.get("conservative_overrides", []):
            if fnmatch.fnmatchcase(path, override["pattern"]):
                verification.update(override.get("verification_domains", []))
    if unmapped_tests:
        primary["__unmapped_tests__"] = unmapped_tests
    return primary, verification


def _ast_is_constant_expression(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return all(_ast_is_constant_expression(item) for item in node.elts)
    if isinstance(node, ast.Dict):
        return all(
            key is not None
            and _ast_is_constant_expression(key)
            and _ast_is_constant_expression(value)
            for key, value in zip(node.keys, node.values)
        )
    if isinstance(node, ast.UnaryOp):
        return _ast_is_constant_expression(node.operand)
    if isinstance(node, ast.BinOp):
        return _ast_is_constant_expression(node.left) and _ast_is_constant_expression(node.right)
    if isinstance(node, ast.BoolOp):
        return all(_ast_is_constant_expression(value) for value in node.values)
    if isinstance(node, ast.Compare):
        return _ast_is_constant_expression(node.left) and all(
            _ast_is_constant_expression(value) for value in node.comparators
        )
    return False


def _is_trivial_test_evidence_line(line: str) -> bool:
    stripped = line.strip()
    if re.search(
        r"\.(?:tap|doubleTap|twoFingerTap|swipe\w*|typeText|press)\s*\(",
        stripped,
    ) and re.search(r"XCTAssert|XCTFail|\bassert\b|pytest\.raises", stripped) is None:
        return True

    swift_literal = r'(?:true|false|nil|-?\d+(?:\.\d+)?|"(?:\\.|[^"\\])*")'
    if re.search(
        rf"XCTAssert(?:Equal|NotEqual)\s*\(\s*{swift_literal}\s*,\s*{swift_literal}\s*[,)]",
        stripped,
    ):
        return True
    if re.search(
        rf"XCTAssert(?:True|False)\s*\(\s*{swift_literal}\s*(?:==|!=)\s*{swift_literal}\s*[,)]",
        stripped,
    ):
        return True

    try:
        parsed = ast.parse(stripped)
    except SyntaxError:
        return False
    if len(parsed.body) != 1:
        return False
    statement = parsed.body[0]
    if isinstance(statement, ast.Assert):
        return _ast_is_constant_expression(statement.test)
    if not isinstance(statement, ast.Expr) or not isinstance(statement.value, ast.Call):
        return False
    call = statement.value
    method = call.func.attr if isinstance(call.func, ast.Attribute) else ""
    if method in {"assertEqual", "assertNotEqual", "assertIs", "assertIsNot"}:
        return len(call.args) >= 2 and all(
            _ast_is_constant_expression(argument) for argument in call.args[:2]
        )
    if method in {"assertTrue", "assertFalse"}:
        return bool(call.args) and _ast_is_constant_expression(call.args[0])
    return False


def _meaningful_test_change(
    domain: dict[str, Any], changes: ChangeSet
) -> tuple[bool, list[str]]:
    candidates = [path for path in changes.paths if _matches(path, domain["test_patterns"])]
    compiled = [re.compile(pattern) for pattern in domain["meaningful_test_patterns"]]
    for path in candidates:
        for line in changes.added_lines.get(path, ()):
            stripped = line.strip()
            if re.search(r"\b(?:func\s+test|def\s+test_)", stripped):
                continue
            if re.search(
                r"\bXCTAssert(?:True|False|Nil|NotNil|Equal|NotEqual)?\s*\(\s*(?:true|false|nil)\s*[,)]",
                stripped,
            ) or re.fullmatch(r"assert\s+(?:True|False)", stripped):
                continue
            if _is_trivial_test_evidence_line(stripped):
                continue
            if any(pattern.search(line) for pattern in compiled):
                return True, candidates
    return False, candidates


def _validate_manifest(
    manifest: dict[str, Any],
    primary_domains: set[str],
    verification_domains: set[str],
    changes: ChangeSet,
    registry: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    if MANIFEST_REPO_PATH not in changes.paths:
        errors.append(
            "behavior change requires a staged/range update to quality/change_impact.json; "
            "record root cause, same-class scan, contracts, tests and verification plan"
        )
    if DEVELOPMENT_RECORDS_REPO_PATH not in changes.paths:
        errors.append(
            "behavior change requires a staged/range development_records.json entry with "
            "root cause, contracts, regression tests and evidence"
        )
    if manifest.get("schema_version") != 1:
        errors.append("change_impact.json schema_version must be 1")
    for field in ("change_id", "summary", "root_cause", "risk_hypothesis"):
        if not isinstance(manifest.get(field), str) or len(manifest[field].strip()) < 8:
            errors.append(f"change_impact.json requires a meaningful {field}")
    change_type = manifest.get("change_type")
    allowed_change_types = {"bugfix", "feature", "refactor", "process", "config", "release"}
    if change_type not in allowed_change_types:
        errors.append(
            "change_impact.json change_type must be one of: "
            + ", ".join(sorted(allowed_change_types))
        )
    for field in (
        "impacted_domains",
        "regression_contracts",
        "same_class_scan",
        "tests_added_or_updated",
        "verification_plan",
        "manual_checks",
        "unresolved_risks",
    ):
        if not isinstance(manifest.get(field), list):
            errors.append(f"change_impact.json {field} must be a list")

    manifest_domains = set(manifest.get("impacted_domains", []))
    missing_domains = verification_domains - manifest_domains
    if missing_domains:
        errors.append(
            "change_impact.json is missing impacted domains: " + ", ".join(sorted(missing_domains))
        )
    unknown_domains = manifest_domains - {item["id"] for item in registry["behavior_domains"]}
    if unknown_domains:
        errors.append("change_impact.json has unknown domains: " + ", ".join(sorted(unknown_domains)))

    domain_by_id = {item["id"]: item for item in registry["behavior_domains"]}
    valid_contracts = {item["id"] for item in registry["contracts"]}
    listed_contracts = set(manifest.get("regression_contracts", []))
    if not listed_contracts:
        errors.append("behavior change requires at least one regression contract")
    unknown_contracts = listed_contracts - valid_contracts
    if unknown_contracts:
        errors.append("change_impact.json has unknown contracts: " + ", ".join(sorted(unknown_contracts)))
    required_contracts = {
        contract_id
        for domain_id in primary_domains
        for contract_id in domain_by_id.get(domain_id, {}).get("required_contract_ids", [])
    }
    missing_required_contracts = required_contracts - listed_contracts
    if missing_required_contracts:
        errors.append(
            "change_impact.json regression_contracts are missing required contracts for "
            "primary domains: "
            + ", ".join(sorted(missing_required_contracts))
        )
    covered_contract_domains = {
        domain
        for contract in registry["contracts"]
        if contract.get("id") in listed_contracts
        for domain in contract.get("domains", [])
    }
    uncovered_primary_domains = primary_domains - covered_contract_domains
    if uncovered_primary_domains:
        errors.append(
            "change_impact.json regression_contracts do not cover primary domains: "
            + ", ".join(sorted(uncovered_primary_domains))
        )

    if not manifest.get("same_class_scan"):
        errors.append("behavior change requires a non-empty same_class_scan")
    if not manifest.get("verification_plan"):
        errors.append("behavior change requires a non-empty verification_plan")
    if "ios_ui_interaction" in verification_domains and not manifest.get("manual_checks"):
        errors.append("iOS UI/interaction change requires manual_checks for visual and state verification")

    declared_tests = set(manifest.get("tests_added_or_updated", []))
    if not declared_tests:
        errors.append("behavior change requires tests_added_or_updated")
    not_changed = sorted(path for path in declared_tests if path not in changes.paths)
    if not_changed:
        errors.append(
            "declared regression tests were not changed in this diff: " + ", ".join(not_changed)
        )

    try:
        record = load_latest_development_record()
    except GuardError as exc:
        errors.append(str(exc))
    else:
        if record.get("id") != manifest.get("change_id"):
            errors.append(
                "latest development record id must equal change_impact.json change_id "
                f"({manifest.get('change_id')})"
            )
        if not isinstance(record.get("root_cause"), str) or len(record["root_cause"].strip()) < 8:
            errors.append("latest development record requires root_cause")
        for field in ("regression_contracts", "same_class_scan", "regression_tests", "test_evidence"):
            if not isinstance(record.get(field), list) or not record[field]:
                errors.append(f"latest development record requires non-empty {field}")

    for domain_id in sorted(primary_domains):
        domain = domain_by_id[domain_id]
        if domain.get("requires_test_change", True) is False:
            continue
        meaningful, candidates = _meaningful_test_change(domain, changes)
        if not meaningful:
            detail = ", ".join(candidates) if candidates else "no matching test file changed"
            errors.append(
                f"domain {domain_id} requires a meaningful regression test addition/assertion; {detail}"
            )
    return errors


def evaluate_changes(changes: ChangeSet, registry: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    errors: list[str] = []
    primary, verification = classify_changes(changes.paths, registry)
    unmapped = primary.pop("__unmapped__", [])
    if unmapped:
        errors.append(
            "production files are not mapped to a regression domain: " + ", ".join(sorted(unmapped))
        )
    unmapped_tests = primary.pop("__unmapped_tests__", [])
    if unmapped_tests:
        errors.append(
            "test/support files are not mapped to a regression domain: "
            + ", ".join(sorted(unmapped_tests))
        )
    test_mapping, _ = classify_test_changes(changes.paths, registry)
    primary_ids = set(primary)
    if primary_ids:
        try:
            manifest = load_manifest()
        except GuardError as exc:
            errors.append(str(exc))
        else:
            errors.extend(
                _validate_manifest(manifest, primary_ids, verification, changes, registry)
            )
    summary = {
        "changed_paths": list(changes.paths),
        "primary_domains": sorted(primary_ids),
        "verification_domains": sorted(verification),
        "production_files": primary,
        "test_files": test_mapping,
    }
    return errors, summary


def _print_errors(errors: list[str]) -> None:
    print("REGRESSION GUARD: FAILED", file=sys.stderr)
    for index, error in enumerate(errors, start=1):
        print(f"  {index}. {error}", file=sys.stderr)


def command_validate() -> int:
    try:
        errors = validate_registry(load_registry())
    except GuardError as exc:
        _print_errors([str(exc)])
        return 1
    if errors:
        _print_errors(errors)
        return 1
    print("REGRESSION GUARD: contracts, anchors and architecture limits are valid")
    return 0


def command_check(args: argparse.Namespace) -> int:
    try:
        registry = load_registry()
        errors = validate_registry(registry)
        if errors:
            _print_errors(errors)
            return 1
        if args.base is not None:
            validate_python_test_inventory_range(args.base, args.head)
            validate_xctest_inventory_range(args.base, args.head)
        elif args.working:
            _validate_python_runtime_inventory_monotonic(
                python_runtime_inventory_at_revision("HEAD", allow_missing=True),
                _python_runtime_profiles(
                    _load_json(EXPECTED_PYTHON_TESTS_PATH), source="working tree"
                ),
            )
            _validate_xctest_inventory_monotonic(
                xctest_inventory_at_revision("HEAD", allow_missing=True),
                _xctest_profiles(_load_json(EXPECTED_XCTESTS_PATH), source="working tree"),
            )
        elif args.staged:
            python_path = EXPECTED_PYTHON_TESTS_PATH.relative_to(REPO_ROOT).as_posix()
            _validate_python_runtime_inventory_monotonic(
                python_runtime_inventory_at_revision("HEAD", allow_missing=True),
                _load_python_runtime_profiles_text(
                    _git("show", f":{python_path}"), source=f"index:{python_path}"
                ),
            )
            path = EXPECTED_XCTESTS_PATH.relative_to(REPO_ROOT).as_posix()
            _validate_xctest_inventory_monotonic(
                xctest_inventory_at_revision("HEAD", allow_missing=True),
                _load_xctest_profiles_text(_git("show", f":{path}"), source=f"index:{path}"),
            )
        changes = collect_changes(
            staged=args.staged,
            working=args.working,
            base=args.base,
            head=args.head,
        )
        change_errors, summary = evaluate_changes(changes, registry)
    except GuardError as exc:
        _print_errors([str(exc)])
        return 1
    if change_errors:
        _print_errors(change_errors)
        print(json.dumps(summary, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    domains = ", ".join(summary["verification_domains"]) or "none (non-behavior change)"
    print(f"REGRESSION GUARD: passed; verification domains: {domains}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate", help="validate contracts, test anchors and architecture limits")
    check = subparsers.add_parser("check", help="check a staged, working-tree, or commit-range change")
    source = check.add_mutually_exclusive_group(required=True)
    source.add_argument("--staged", action="store_true", help="check the staged index")
    source.add_argument("--working", action="store_true", help="check HEAD versus staged/unstaged/untracked work")
    source.add_argument("--base", help="check BASE..HEAD")
    check.add_argument("--head", default="HEAD", help="range head; defaults to HEAD")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "validate":
        return command_validate()
    if args.command == "check":
        return command_check(args)
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
