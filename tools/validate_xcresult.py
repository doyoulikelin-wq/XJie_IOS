#!/usr/bin/env python3
"""Fail closed unless an xcresult contains the required executed tests."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EXPECTED_TESTS_PATH = REPO_ROOT / "quality" / "expected_xctests.json"
EXPECTED_PROFILES = ("ios_unit", "ios_ui_full", "ios_ui_small", "ios_all")


class XCResultValidationError(RuntimeError):
    pass


@dataclass(frozen=True)
class TestCaseResult:
    identifier: str
    result: str


def _integer(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise XCResultValidationError(f"xcresult summary has invalid {key}: {value!r}")
    return value


def _canonical_identifier(node: dict[str, Any]) -> str:
    raw_url = node.get("nodeIdentifierURL")
    if isinstance(raw_url, str) and raw_url:
        components = [part for part in urlparse(raw_url).path.split("/") if part]
        if len(components) >= 3:
            return "/".join(components[-3:]).removesuffix("()")
    raw_identifier = node.get("nodeIdentifier")
    if isinstance(raw_identifier, str) and raw_identifier:
        return raw_identifier.removesuffix("()")
    raise XCResultValidationError("xcresult test case is missing a stable identifier")


def collect_test_cases(payload: dict[str, Any]) -> list[TestCaseResult]:
    cases: list[TestCaseResult] = []

    def visit(value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                visit(item)
            return
        if not isinstance(value, dict):
            return
        if value.get("nodeType") == "Test Case":
            result = value.get("result")
            if not isinstance(result, str) or not result:
                raise XCResultValidationError(
                    f"xcresult test case has no result: {_canonical_identifier(value)}"
                )
            cases.append(TestCaseResult(_canonical_identifier(value), result))
            return
        for key in ("testNodes", "children"):
            if key in value:
                visit(value[key])

    visit(payload.get("testNodes", []))
    return cases


def validate_expected_test_profiles(payload: dict[str, Any]) -> dict[str, list[str]]:
    if payload.get("schema_version") != 1:
        raise XCResultValidationError("expected XCTest manifest schema_version must be 1")
    profiles = payload.get("profiles")
    if not isinstance(profiles, dict) or tuple(profiles) != EXPECTED_PROFILES:
        raise XCResultValidationError(
            "expected XCTest manifest profiles must be ordered exactly as: "
            + ", ".join(EXPECTED_PROFILES)
        )
    canonical = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*/[A-Za-z_][A-Za-z0-9_]*/test[A-Za-z0-9_]+$")
    validated: dict[str, list[str]] = {}
    for profile in EXPECTED_PROFILES:
        identifiers = profiles.get(profile)
        if not isinstance(identifiers, list) or not identifiers:
            raise XCResultValidationError(f"expected XCTest profile is empty: {profile}")
        if any(not isinstance(item, str) or canonical.fullmatch(item) is None for item in identifiers):
            raise XCResultValidationError(f"expected XCTest profile has invalid identifiers: {profile}")
        if identifiers != sorted(identifiers) or len(identifiers) != len(set(identifiers)):
            raise XCResultValidationError(
                f"expected XCTest profile must be sorted and duplicate-free: {profile}"
            )
        validated[profile] = identifiers

    unit = set(validated["ios_unit"])
    ui = set(validated["ios_ui_full"])
    small = set(validated["ios_ui_small"])
    all_tests = set(validated["ios_all"])
    if any(not item.startswith("XjieTests/") for item in unit):
        raise XCResultValidationError("ios_unit profile contains a non-unit test")
    if any(not item.startswith("XjieUITests/") for item in ui):
        raise XCResultValidationError("ios_ui_full profile contains a non-UI test")
    if not small.issubset(ui):
        raise XCResultValidationError("ios_ui_small must be a subset of ios_ui_full")
    if all_tests != unit | ui or len(validated["ios_all"]) != len(unit) + len(ui):
        raise XCResultValidationError("ios_all must be the exact union of unit and full UI tests")
    return validated


def load_expected_test_profiles(path: Path) -> dict[str, list[str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise XCResultValidationError(f"cannot read expected XCTest manifest: {path}") from exc
    if not isinstance(payload, dict):
        raise XCResultValidationError("expected XCTest manifest must be a JSON object")
    return validate_expected_test_profiles(payload)


def collect_swift_source_test_identifiers(source_root: Path) -> dict[str, list[str]]:
    profiles = {"ios_unit": [], "ios_ui_full": []}
    for target, relative_root, profile in (
        ("XjieTests", Path("Xjie") / "XjieTests", "ios_unit"),
        ("XjieUITests", Path("Xjie") / "XjieUITests", "ios_ui_full"),
    ):
        directory = source_root / relative_root
        if not directory.is_dir():
            raise XCResultValidationError(f"XCTest source directory does not exist: {directory}")
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
                raise XCResultValidationError(
                    f"test source with test methods must have exactly one recognized class: {path}"
                )
            profiles[profile].extend(f"{target}/{classes[0]}/{method}" for method in methods)
    for profile in profiles:
        profiles[profile].sort()
        if len(profiles[profile]) != len(set(profiles[profile])):
            raise XCResultValidationError(f"duplicate Swift source test identifiers: {profile}")
    return profiles


def validate_swift_source_inventory(
    profiles: dict[str, list[str]],
    source_root: Path = REPO_ROOT,
) -> None:
    source_profiles = collect_swift_source_test_identifiers(source_root)
    for profile in ("ios_unit", "ios_ui_full"):
        expected = set(profiles[profile])
        actual = set(source_profiles[profile])
        if expected != actual:
            missing = sorted(expected - actual)
            untracked = sorted(actual - expected)
            detail = []
            if missing:
                detail.append("manifest-only=" + ", ".join(missing[:5]))
            if untracked:
                detail.append("source-only=" + ", ".join(untracked[:5]))
            raise XCResultValidationError(
                f"Swift source tests do not match {profile}: " + "; ".join(detail)
            )


def validate_payloads(
    summary: dict[str, Any],
    tests: dict[str, Any],
    *,
    minimum_tests: int,
    required_tests: Iterable[str],
    required_device_model: str | None = None,
    expected_tests: Iterable[str] | None = None,
) -> dict[str, Any]:
    if minimum_tests <= 0:
        raise XCResultValidationError("minimum_tests must be greater than zero")

    total = _integer(summary, "totalTestCount")
    passed = _integer(summary, "passedTests")
    skipped = _integer(summary, "skippedTests")
    failed = _integer(summary, "failedTests")
    expected_failures = _integer(summary, "expectedFailures")
    if summary.get("result") != "Passed":
        raise XCResultValidationError(
            f"xcresult overall result is {summary.get('result')!r}, expected 'Passed'"
        )
    if total < minimum_tests:
        raise XCResultValidationError(
            f"xcresult executed {total} tests; at least {minimum_tests} are required"
        )
    if skipped != 0 or failed != 0 or expected_failures != 0:
        raise XCResultValidationError(
            "xcresult contains non-passing tests: "
            f"failed={failed}, skipped={skipped}, expected_failures={expected_failures}"
        )
    if passed != total:
        raise XCResultValidationError(
            f"xcresult count mismatch: total={total}, passed={passed}"
        )

    if required_device_model is not None:
        configurations = summary.get("devicesAndConfigurations")
        if not isinstance(configurations, list) or not configurations:
            raise XCResultValidationError("xcresult has no device configuration evidence")
        models = {
            item.get("device", {}).get("modelName")
            for item in configurations
            if isinstance(item, dict) and isinstance(item.get("device"), dict)
        }
        if models != {required_device_model}:
            raise XCResultValidationError(
                f"xcresult device models are {sorted(str(item) for item in models)!r}; "
                f"required {required_device_model!r}"
            )

    cases = collect_test_cases(tests)
    if len(cases) != total:
        raise XCResultValidationError(
            f"xcresult test tree contains {len(cases)} cases but summary reports {total}"
        )
    non_passing = [case for case in cases if case.result != "Passed"]
    if non_passing:
        detail = ", ".join(f"{item.identifier}={item.result}" for item in non_passing[:5])
        raise XCResultValidationError(f"xcresult tree contains non-passing cases: {detail}")

    case_identifiers = [case.identifier for case in cases]
    if len(case_identifiers) != len(set(case_identifiers)):
        raise XCResultValidationError("xcresult tree contains duplicate test identifiers")
    normalized_expected = None
    if expected_tests is not None:
        normalized_expected = [item.removesuffix("()") for item in expected_tests]
        expected_set = set(normalized_expected)
        actual_set = set(case_identifiers)
        missing_expected = sorted(expected_set - actual_set)
        unexpected = sorted(actual_set - expected_set)
        if missing_expected or unexpected or len(normalized_expected) != len(expected_set):
            detail = []
            if missing_expected:
                detail.append("missing=" + ", ".join(missing_expected[:5]))
            if unexpected:
                detail.append("unexpected=" + ", ".join(unexpected[:5]))
            if len(normalized_expected) != len(expected_set):
                detail.append("expected manifest contains duplicates")
            raise XCResultValidationError(
                "xcresult does not exactly match its expected test profile: " + "; ".join(detail)
            )

    normalized_required = [item.removesuffix("()") for item in required_tests]
    case_ids = set(case_identifiers)
    missing = [item for item in normalized_required if item not in case_ids]
    if missing:
        raise XCResultValidationError(
            "xcresult is missing required tests: " + ", ".join(missing)
        )
    return {
        "total": total,
        "passed": passed,
        "required_tests": normalized_required,
        "device_model": required_device_model,
        "expected_tests": normalized_expected,
    }


def _xcresult_json(path: Path, section: str) -> dict[str, Any]:
    result = subprocess.run(
        [
            "xcrun",
            "xcresulttool",
            "get",
            "test-results",
            section,
            "--path",
            str(path),
            "--compact",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise XCResultValidationError(
            result.stderr.strip() or f"xcresulttool could not read {section}"
        )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise XCResultValidationError(f"xcresulttool returned invalid {section} JSON") from exc
    if not isinstance(payload, dict):
        raise XCResultValidationError(f"xcresulttool returned non-object {section} JSON")
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", required=True, type=Path)
    parser.add_argument("--minimum-tests", type=int)
    parser.add_argument("--required-test", action="append", default=[])
    parser.add_argument("--required-device-model")
    parser.add_argument("--expected-tests-file", type=Path, default=DEFAULT_EXPECTED_TESTS_PATH)
    parser.add_argument("--expected-profile", choices=EXPECTED_PROFILES)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if not args.path.is_dir():
            raise XCResultValidationError(f"xcresult bundle does not exist: {args.path}")
        expected_tests = None
        if args.expected_profile is not None:
            profiles = load_expected_test_profiles(args.expected_tests_file)
            validate_swift_source_inventory(profiles)
            expected_tests = profiles[args.expected_profile]
        minimum_tests = args.minimum_tests
        if minimum_tests is None:
            if expected_tests is None:
                raise XCResultValidationError(
                    "provide --expected-profile (preferred) or a positive --minimum-tests"
                )
            minimum_tests = len(expected_tests)
        report = validate_payloads(
            _xcresult_json(args.path, "summary"),
            _xcresult_json(args.path, "tests"),
            minimum_tests=minimum_tests,
            required_tests=args.required_test,
            required_device_model=args.required_device_model,
            expected_tests=expected_tests,
        )
    except XCResultValidationError as exc:
        print(f"XCRESULT VALIDATION: FAILED: {exc}", file=sys.stderr)
        return 1
    print(
        "XCRESULT VALIDATION: PASSED; "
        f"executed={report['total']} expected="
        f"{len(report['expected_tests'] or report['required_tests'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
