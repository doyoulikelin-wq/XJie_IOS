#!/usr/bin/env python3
"""Static regression-prevention gate for XJie iOS XAGE.

The guard intentionally uses only the Python standard library so it can run in
Git hooks and CI before project dependencies are installed.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / "quality" / "regression_contracts.json"
MANIFEST_PATH = REPO_ROOT / "quality" / "change_impact.json"
MANIFEST_REPO_PATH = "quality/change_impact.json"
DEVELOPMENT_RECORDS_PATH = REPO_ROOT / "development_records.json"
DEVELOPMENT_RECORDS_REPO_PATH = "development_records.json"


class GuardError(RuntimeError):
    pass


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


def _existing_commit_or_parent(candidate: str, head: str) -> str:
    if candidate and set(candidate) != {"0"}:
        result = subprocess.run(
            ["git", "cat-file", "-e", f"{candidate}^{{commit}}"],
            cwd=REPO_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if result.returncode == 0:
            return candidate
    parent = _git("rev-parse", f"{head}^").strip()
    if not parent:
        raise GuardError(f"cannot determine comparison base for {head}")
    return parent


def collect_changes(
    *, staged: bool = False, working: bool = False, base: str | None = None, head: str = "HEAD"
) -> ChangeSet:
    selected = sum((staged, working, base is not None))
    if selected != 1:
        raise GuardError("select exactly one change source: --staged, --working, or --base")

    if staged:
        name_args = ("diff", "--cached", "--name-only", "--diff-filter=ACMR")
        diff_args = ("diff", "--cached", "--unified=0", "--diff-filter=ACMR")
        paths = [line for line in _git(*name_args).splitlines() if line]
        return ChangeSet(tuple(sorted(set(paths))), _parse_added_lines(_git(*diff_args)))

    if working:
        paths = [
            line
            for line in _git("diff", "HEAD", "--name-only", "--diff-filter=ACMR").splitlines()
            if line
        ]
        added = _parse_added_lines(_git("diff", "HEAD", "--unified=0", "--diff-filter=ACMR"))
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
    paths = [
        line
        for line in _git("diff", resolved_base, head, "--name-only", "--diff-filter=ACMR").splitlines()
        if line
    ]
    diff_text = _git("diff", resolved_base, head, "--unified=0", "--diff-filter=ACMR")
    return ChangeSet(tuple(sorted(set(paths))), _parse_added_lines(diff_text))


def validate_registry(registry: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if registry.get("schema_version") != 1:
        errors.append("regression_contracts.json schema_version must be 1")

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
        unknown = set(contract.get("domains", [])) - domain_ids
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
        for command_id in release_gate.get("required_commands", []):
            if command_id not in commands:
                errors.append(f"release_gate references unknown command {command_id}")

    return errors


def classify_changes(
    paths: Iterable[str], registry: dict[str, Any]
) -> tuple[dict[str, list[str]], set[str]]:
    domains = registry["behavior_domains"]
    primary: dict[str, list[str]] = {}
    production_candidates: list[str] = []
    for path in paths:
        is_ios = path.startswith("Xjie/Xjie/") and path.endswith(".swift")
        is_backend = path.startswith("backend/app/") and path.endswith(".py")
        if "/XjieTests/" in path or "/XjieUITests/" in path:
            continue
        matched_domain: str | None = None
        for domain in domains:
            if _matches(path, domain["source_patterns"]):
                matched_domain = domain["id"]
                break
        if not (is_ios or is_backend or matched_domain is not None):
            continue
        production_candidates.append(path)
        if matched_domain is None:
            primary.setdefault("__unmapped__", []).append(path)
        else:
            primary.setdefault(matched_domain, []).append(path)

    verification = {domain_id for domain_id in primary if domain_id != "__unmapped__"}
    for path in production_candidates:
        for override in registry.get("conservative_overrides", []):
            if fnmatch.fnmatchcase(path, override["pattern"]):
                verification.update(override.get("verification_domains", []))
    return primary, verification


def _meaningful_test_change(
    domain: dict[str, Any], changes: ChangeSet
) -> tuple[bool, list[str]]:
    candidates = [path for path in changes.paths if _matches(path, domain["test_patterns"])]
    compiled = [re.compile(pattern) for pattern in domain["meaningful_test_patterns"]]
    for path in candidates:
        for line in changes.added_lines.get(path, ()):
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

    valid_contracts = {item["id"] for item in registry["contracts"]}
    listed_contracts = set(manifest.get("regression_contracts", []))
    if not listed_contracts:
        errors.append("behavior change requires at least one regression contract")
    unknown_contracts = listed_contracts - valid_contracts
    if unknown_contracts:
        errors.append("change_impact.json has unknown contracts: " + ", ".join(sorted(unknown_contracts)))

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

    domain_by_id = {item["id"]: item for item in registry["behavior_domains"]}
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
