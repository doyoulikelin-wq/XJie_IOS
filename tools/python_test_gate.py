#!/usr/bin/env python3
"""Run Python test suites and reject zero-test, skip, and inventory false greens."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import unittest
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
BACKEND_TEST_ROOT = BACKEND_ROOT / "tests"
TOOLS_TEST_ROOT = REPO_ROOT / "tools" / "tests"
REGISTRY_PATH = REPO_ROOT / "quality" / "regression_contracts.json"
EXPECTED_TESTS_PATH = REPO_ROOT / "quality" / "expected_python_tests.json"

MINIMUM_BACKEND_FULL_TESTS = 324
MINIMUM_TOOL_TESTS = 77
CURRENT_BACKEND_FULL_TESTS = 331
CURRENT_TOOL_TESTS = 77
INTEGRATION_SKIP_REASON = "requires dockerized postgres + redis stack"
ALLOWED_BACKEND_FULL_SKIPS = {
    "tests.integration.test_api_chat_mock::test_chat_mock_placeholder": INTEGRATION_SKIP_REASON,
    "tests.integration.test_api_glucose_import::test_glucose_import_flow_placeholder": (
        INTEGRATION_SKIP_REASON
    ),
    "tests.integration.test_api_meals_flow::test_meals_photo_flow_placeholder": (
        INTEGRATION_SKIP_REASON
    ),
}
REQUIRED_BACKEND_FULL_TESTS = {
    "tests.unit.test_account_lifecycle::test_account_lifecycle_delete_and_reregister_same_phone",
    "tests.unit.test_chat_execution_pipeline::test_sse_pipeline_emits_route_then_done_and_replays_idempotently",
    "tests.unit.test_device_indicator_sync::test_apple_health_never_overwrites_manual_value",
    "tests.unit.test_health_nlu::test_family_relative_case_sets_subject_boundary_without_using_self_data",
    "tests.unit.test_migration_0021_device_indicator_identity::test_migration_round_trip_preserves_new_source_identity_in_legacy_notes",
    "tests.unit.test_safety_response::test_dka_warning_is_specific_and_actionable_on_first_screen",
}
REQUIRED_TOOL_TEST_METHODS = {
    "test_allowlisted_skip_missing_or_reason_changed_requires_policy_update",
    "test_backend_test_file_not_collected_fails_closed",
    "test_behavior_change_without_manifest_or_test_fails",
    "test_behavior_change_with_manifest_and_meaningful_test_passes",
    "test_changed_test_files_add_every_corresponding_impacted_command",
    "test_ci_covers_xage_backend_and_never_swallows_failures",
    "test_clean_bundle_passes_and_every_forbidden_marker_fails",
    "test_exact_profile_rejects_missing_extra_and_duplicate_tests",
    "test_exact_three_integration_skips_are_the_only_allowlist",
    "test_mandatory_backend_test_missing_fails_closed",
    "test_marker_split_across_read_chunks_is_detected",
    "test_manifest_contracts_must_cover_every_primary_domain",
    "test_python_test_inventory_cannot_delete_or_rename_existing_id_at_same_count",
    "test_tracked_xctest_profiles_are_exact_and_self_consistent",
    "test_tracked_python_runtime_inventory_rejects_parameterization_shrink",
    "test_unexpected_skip_fails_closed",
    "test_wrong_sha_branch_app_or_workflow_run_link_fails_closed",
    "test_zero_or_too_few_executed_tests_fail",
}


class PythonTestGateError(RuntimeError):
    pass


@dataclass(frozen=True)
class JUnitCase:
    module: str
    name: str
    skipped_reason: str | None
    failed: bool

    @property
    def node_id(self) -> str:
        return f"{self.module}::{self.name}"


def load_expected_tests(path: Path = EXPECTED_TESTS_PATH) -> dict[str, set[str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PythonTestGateError(f"cannot load exact Python test inventory: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise PythonTestGateError("exact Python test inventory schema_version must be 1")
    if tuple(payload) != ("schema_version", "backend_full", "tools"):
        raise PythonTestGateError(
            "exact Python test inventory keys must be ordered as schema_version, backend_full, tools"
        )
    current_counts = {
        "backend_full": CURRENT_BACKEND_FULL_TESTS,
        "tools": CURRENT_TOOL_TESTS,
    }
    minimum_counts = {
        "backend_full": MINIMUM_BACKEND_FULL_TESTS,
        "tools": MINIMUM_TOOL_TESTS,
    }
    result: dict[str, set[str]] = {}
    for profile in ("backend_full", "tools"):
        values = payload.get(profile)
        if not isinstance(values, list) or not values or any(
            not isinstance(value, str) or not value.strip() for value in values
        ):
            raise PythonTestGateError(
                f"exact Python test inventory {profile} must be a non-empty string list"
            )
        if values != sorted(values) or len(values) != len(set(values)):
            raise PythonTestGateError(
                f"exact Python test inventory {profile} must be sorted and duplicate-free"
            )
        if len(values) < minimum_counts[profile]:
            raise PythonTestGateError(
                f"exact Python test inventory {profile} fell below the non-shrink floor: "
                f"actual={len(values)} minimum={minimum_counts[profile]}"
            )
        if len(values) != current_counts[profile]:
            raise PythonTestGateError(
                f"exact Python test inventory {profile} does not match the current baseline: "
                f"actual={len(values)} expected={current_counts[profile]}"
            )
        result[profile] = set(values)
    return result


def _duplicates(values: Iterable[str]) -> list[str]:
    return sorted(value for value, count in Counter(values).items() if count > 1)


def _test_module_for_path(path: Path, *, root: Path) -> str:
    try:
        relative = path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise PythonTestGateError(f"test path is outside {root}: {path}") from exc
    return ".".join(relative.with_suffix("").parts)


def _backend_test_files(paths: Iterable[str]) -> set[Path]:
    selected: set[Path] = set()
    for raw_path in paths:
        if raw_path.startswith("-"):
            continue
        path = (REPO_ROOT / raw_path).resolve()
        if path.is_dir():
            selected.update(item for item in path.rglob("test_*.py") if item.is_file())
        elif path.is_file() and path.name.startswith("test_") and path.suffix == ".py":
            selected.add(path)
    if not selected:
        raise PythonTestGateError("pytest selection contains no backend test files")
    return selected


def _contract_backend_tests() -> set[str]:
    try:
        registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PythonTestGateError(f"cannot load regression contracts: {exc}") from exc
    required: set[str] = set()
    for contract in registry.get("contracts", []):
        if not isinstance(contract, dict):
            continue
        for anchor in contract.get("test_anchors", []):
            if not isinstance(anchor, dict):
                continue
            path = anchor.get("path")
            symbol = anchor.get("symbol")
            if not isinstance(path, str) or not path.startswith("backend/tests/"):
                continue
            if not isinstance(symbol, str) or not symbol:
                continue
            module = _test_module_for_path(REPO_ROOT / path, root=BACKEND_ROOT)
            required.add(f"{module}::{symbol}")
    return required


def _parse_junit(path: Path) -> list[JUnitCase]:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise PythonTestGateError(f"cannot parse pytest JUnit result {path}: {exc}") from exc
    cases: list[JUnitCase] = []
    for element in root.iter("testcase"):
        module = element.get("classname", "").strip()
        name = element.get("name", "").strip()
        if not module or not name:
            raise PythonTestGateError("pytest JUnit contains a testcase without classname/name")
        skipped = element.find("skipped")
        reason = None if skipped is None else (skipped.get("message") or "").strip()
        cases.append(
            JUnitCase(
                module=module,
                name=name,
                skipped_reason=reason,
                failed=element.find("failure") is not None or element.find("error") is not None,
            )
        )
    return cases


def _case_matches_required(case: JUnitCase, required_node: str) -> bool:
    module, separator, name = required_node.partition("::")
    if not separator or case.module != module:
        return False
    return case.name == name or case.name.startswith(name + "[")


def _node_belongs_to_modules(node: str, modules: set[str]) -> bool:
    classname = node.partition("::")[0]
    return any(classname == module or classname.startswith(module + ".") for module in modules)


def validate_backend_junit(
    path: Path,
    *,
    profile: str,
    selected_files: set[Path],
    minimum_tests: int | None = None,
    required_tests: set[str] | None = None,
    allowed_skips: dict[str, str] | None = None,
    expected_tests: set[str] | None = None,
) -> dict[str, int]:
    cases = _parse_junit(path)
    case_ids = [case.node_id for case in cases]
    duplicates = _duplicates(case_ids)
    if duplicates:
        raise PythonTestGateError(
            "backend JUnit contains duplicate test IDs: " + ", ".join(duplicates)
        )
    minimum = minimum_tests if minimum_tests is not None else (
        MINIMUM_BACKEND_FULL_TESTS if profile == "full" else 1
    )
    if len(cases) < minimum:
        raise PythonTestGateError(
            f"backend test count regressed: executed={len(cases)}, required>={minimum}"
        )
    failed = [case.node_id for case in cases if case.failed]
    if failed:
        raise PythonTestGateError("backend JUnit contains failed/error tests: " + ", ".join(failed))

    expected_modules = {
        _test_module_for_path(file_path, root=BACKEND_ROOT) for file_path in selected_files
    }
    collected_modules = {case.module for case in cases}
    missing_files = sorted(
        module
        for module in expected_modules
        if not any(value == module or value.startswith(module + ".") for value in collected_modules)
    )
    if missing_files:
        raise PythonTestGateError(
            "backend test files were not collected: " + ", ".join(missing_files)
        )

    full_expected = set(
        expected_tests
        if expected_tests is not None
        else load_expected_tests()["backend_full"]
    )
    selected_expected = full_expected if profile == "full" else {
        node
        for node in full_expected
        if _node_belongs_to_modules(node, expected_modules)
    }
    actual = set(case_ids)
    if actual != selected_expected:
        missing = sorted(selected_expected - actual)
        unexpected = sorted(actual - selected_expected)
        details = []
        if missing:
            details.append("missing=" + ",".join(missing))
        if unexpected:
            details.append("unexpected=" + ",".join(unexpected))
        raise PythonTestGateError(
            "backend exact test inventory mismatch: " + "; ".join(details)
        )

    required = set(required_tests or set())
    if required_tests is None:
        required.update(_contract_backend_tests())
        if profile == "full":
            required.update(REQUIRED_BACKEND_FULL_TESTS)
        else:
            required = {
                node for node in required if node.partition("::")[0] in expected_modules
            }
    missing_required = sorted(
        node for node in required if not any(_case_matches_required(case, node) for case in cases)
    )
    if missing_required:
        raise PythonTestGateError(
            "mandatory backend tests were not executed: " + ", ".join(missing_required)
        )

    expected_skips = dict(
        allowed_skips
        if allowed_skips is not None
        else (ALLOWED_BACKEND_FULL_SKIPS if profile == "full" else {})
    )
    actual_skips = {
        case.node_id: case.skipped_reason or "" for case in cases if case.skipped_reason is not None
    }
    if actual_skips != expected_skips:
        unexpected = sorted(set(actual_skips) - set(expected_skips))
        missing = sorted(set(expected_skips) - set(actual_skips))
        wrong_reason = sorted(
            node
            for node in set(actual_skips) & set(expected_skips)
            if actual_skips[node] != expected_skips[node]
        )
        details = []
        if unexpected:
            details.append("unexpected=" + ",".join(unexpected))
        if missing:
            details.append("allowlist-not-skipped=" + ",".join(missing))
        if wrong_reason:
            details.append("reason-changed=" + ",".join(wrong_reason))
        raise PythonTestGateError("backend skip allowlist mismatch: " + "; ".join(details))

    return {
        "executed": len(cases),
        "passed": len(cases) - len(actual_skips),
        "skipped": len(actual_skips),
    }


def run_backend(profile: str, pytest_args: list[str], junit_path: Path) -> int:
    args = list(pytest_args)
    if args and args[0] == "--":
        args.pop(0)
    if not args:
        raise PythonTestGateError("backend gate requires an explicit pytest selection")
    if any(item == "--collect-only" or item == "--co" or item.startswith("--junitxml") for item in args):
        raise PythonTestGateError("backend gate controls collection mode and JUnit output")
    selected_files = _backend_test_files(args)
    if profile == "full":
        expected_files = set(BACKEND_TEST_ROOT.rglob("test_*.py"))
        if selected_files != expected_files:
            raise PythonTestGateError("backend full profile must select every backend test file")

    junit_path.parent.mkdir(parents=True, exist_ok=True)
    junit_path.unlink(missing_ok=True)
    command = [sys.executable, "-I", "-m", "pytest", *args, f"--junitxml={junit_path}"]
    print("[backend-python-gate] " + " ".join(command), flush=True)
    completed = subprocess.run(command, cwd=REPO_ROOT, check=False)
    validation_error: PythonTestGateError | None = None
    try:
        summary = validate_backend_junit(
            junit_path,
            profile=profile,
            selected_files=selected_files,
        )
    except PythonTestGateError as exc:
        validation_error = exc
    if completed.returncode != 0:
        raise PythonTestGateError(f"pytest failed with exit code {completed.returncode}")
    if validation_error is not None:
        raise validation_error
    print(
        "PYTHON TEST GATE: backend passed; "
        f"executed={summary['executed']} passed={summary['passed']} skipped={summary['skipped']}"
    )
    return 0


def _flatten_suite(suite: unittest.TestSuite) -> list[unittest.TestCase]:
    cases: list[unittest.TestCase] = []
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            cases.extend(_flatten_suite(item))
        else:
            cases.append(item)
    return cases


def _contract_tool_test_methods() -> set[str]:
    try:
        registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PythonTestGateError(f"cannot load regression contracts: {exc}") from exc
    required: set[str] = set()
    for contract in registry.get("contracts", []):
        if not isinstance(contract, dict):
            continue
        for anchor in contract.get("test_anchors", []):
            if not isinstance(anchor, dict):
                continue
            path = anchor.get("path")
            symbol = anchor.get("symbol")
            if isinstance(path, str) and path.startswith("tools/tests/") \
                    and isinstance(symbol, str) and symbol:
                required.add(symbol)
    return required


def validate_tool_inventory(
    cases: list[unittest.TestCase],
    *,
    expected_files: set[Path] | None = None,
    required_methods: set[str] | None = None,
    minimum_tests: int = MINIMUM_TOOL_TESTS,
    expected_ids: set[str] | None = None,
) -> None:
    if len(cases) < minimum_tests:
        raise PythonTestGateError(
            f"tool test count regressed: discovered={len(cases)}, required>={minimum_tests}"
        )
    discovered_files: set[Path] = set()
    discovered_methods: set[str] = set()
    case_ids = [str(case.id()) for case in cases]
    duplicates = _duplicates(case_ids)
    if duplicates:
        raise PythonTestGateError(
            "tool unittest inventory contains duplicate test IDs: " + ", ".join(duplicates)
        )
    for case in cases:
        discovered_methods.add(str(case.id()).rsplit(".", maxsplit=1)[-1])
        module = sys.modules.get(case.__class__.__module__)
        module_file = getattr(module, "__file__", None)
        if module_file:
            discovered_files.add(Path(module_file).resolve())
    expected = {path.resolve() for path in (expected_files or set(TOOLS_TEST_ROOT.rglob("test_*.py")))}
    missing_files = sorted(str(path.relative_to(REPO_ROOT)) for path in expected - discovered_files)
    if missing_files:
        raise PythonTestGateError("tool test files were not discovered: " + ", ".join(missing_files))
    expected = set(
        expected_ids if expected_ids is not None else load_expected_tests()["tools"]
    )
    actual = set(case_ids)
    if actual != expected:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        details = []
        if missing:
            details.append("missing=" + ",".join(missing))
        if unexpected:
            details.append("unexpected=" + ",".join(unexpected))
        raise PythonTestGateError(
            "tool exact test inventory mismatch: " + "; ".join(details)
        )
    required = set(required_methods or set())
    if required_methods is None:
        required.update(REQUIRED_TOOL_TEST_METHODS)
        required.update(_contract_tool_test_methods())
    missing_methods = sorted(required - discovered_methods)
    if missing_methods:
        raise PythonTestGateError(
            "mandatory tool tests were not discovered: " + ", ".join(missing_methods)
        )


def run_tools() -> int:
    loader = unittest.TestLoader()
    suite = loader.discover(
        str(TOOLS_TEST_ROOT),
        pattern="test_*.py",
        top_level_dir=str(TOOLS_TEST_ROOT),
    )
    cases = _flatten_suite(suite)
    inventory_error: PythonTestGateError | None = None
    try:
        validate_tool_inventory(cases)
    except PythonTestGateError as exc:
        inventory_error = exc
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    if not result.wasSuccessful():
        raise PythonTestGateError("tool unittest suite failed")
    if result.skipped:
        names = ", ".join(case.id() for case, _ in result.skipped)
        raise PythonTestGateError("tool unittest skips are forbidden: " + names)
    if result.expectedFailures or result.unexpectedSuccesses:
        raise PythonTestGateError("tool unittest expected failures/unexpected successes are forbidden")
    if result.testsRun != len(cases):
        raise PythonTestGateError(
            f"tool unittest execution mismatch: discovered={len(cases)} executed={result.testsRun}"
        )
    if inventory_error is not None:
        raise inventory_error
    print(f"PYTHON TEST GATE: tools passed; executed={result.testsRun} skipped=0")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("tools")
    backend = subparsers.add_parser("backend")
    backend.add_argument("--profile", choices=("full", "focused"), required=True)
    backend.add_argument("--junitxml", type=Path, required=True)
    backend.add_argument("pytest_args", nargs=argparse.REMAINDER)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "tools":
            return run_tools()
        if args.command == "backend":
            return run_backend(args.profile, args.pytest_args, args.junitxml)
        raise AssertionError(args.command)
    except PythonTestGateError as exc:
        print(f"PYTHON TEST GATE: FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
