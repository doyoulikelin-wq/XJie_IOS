#!/usr/bin/env python3
"""Run impacted or release-quality gates and bind release evidence to HEAD."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / "quality" / "regression_contracts.json"
MANIFEST_PATH = REPO_ROOT / "quality" / "change_impact.json"
EVIDENCE_PATH = REPO_ROOT / ".quality" / "release_gate.json"


class GateError(RuntimeError):
    pass


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise GateError(f"cannot load {path.relative_to(REPO_ROOT)}: {exc}") from exc
    if not isinstance(value, dict):
        raise GateError(f"{path.relative_to(REPO_ROOT)} must contain a JSON object")
    return value


def git(*args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check and result.returncode != 0:
        raise GateError(result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip()


def backend_python() -> str:
    local = REPO_ROOT / "backend" / ".venv" / "bin" / "python"
    return str(local) if local.is_file() else sys.executable


def expand_command(command: str) -> str:
    quoted_values = {
        "backend_python": backend_python(),
    }
    literal_values = {
        "simulator": os.environ.get("XJIE_SIMULATOR_NAME", "iPhone 17 Pro"),
        "small_simulator": os.environ.get("XJIE_SMALL_SIMULATOR_NAME", "XAGE UX SE 3"),
    }
    for key, value in literal_values.items():
        if "'" in value:
            raise GateError(f"invalid simulator name: {value!r}")
        command = command.replace("{" + key + "}", value)
    for key, value in quoted_values.items():
        command = command.replace("{" + key + "}", shlex.quote(value))
    return command


def run_command(command_id: str, command: str, *, dry_run: bool) -> dict[str, Any]:
    expanded = expand_command(command)
    print(f"\n[{command_id}] {expanded}", flush=True)
    if dry_run:
        return {"id": command_id, "command": expanded, "status": "dry-run", "duration_seconds": 0.0}
    started = time.monotonic()
    result = subprocess.run(
        ["/bin/zsh", "-o", "pipefail", "-c", expanded],
        cwd=REPO_ROOT,
        check=False,
    )
    duration = round(time.monotonic() - started, 3)
    if result.returncode != 0:
        raise GateError(f"gate command failed ({command_id}, exit {result.returncode})")
    return {"id": command_id, "command": expanded, "status": "passed", "duration_seconds": duration}


def ensure_clean_and_synced() -> tuple[str, str]:
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


def worktree_fingerprint() -> str:
    payload = git("status", "--porcelain=v1", "--untracked-files=all")
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def command_ids_for_impacted(registry: dict[str, Any]) -> list[str]:
    manifest = load_json(MANIFEST_PATH)
    requested = set(manifest.get("impacted_domains", []))
    by_id = {domain["id"]: domain for domain in registry["behavior_domains"]}
    unknown = requested - set(by_id)
    if unknown:
        raise GateError("change manifest has unknown domains: " + ", ".join(sorted(unknown)))
    command_ids = ["guard_unit"]
    for domain_id in sorted(requested):
        command_ids.extend(by_id[domain_id]["verification_commands"])
    command_ids.append("diff_check")
    return list(dict.fromkeys(command_ids))


def run_gate(mode: str, *, dry_run: bool) -> int:
    registry = load_json(REGISTRY_PATH)
    commands = registry["commands"]
    if mode == "impacted":
        command_ids = command_ids_for_impacted(registry)
        guard_command = "python3 tools/regression_guard.py validate && python3 tools/regression_guard.py check --working"
        print(f"\n[static_guard] {guard_command}", flush=True)
        if not dry_run:
            result = subprocess.run(
                ["/bin/zsh", "-o", "pipefail", "-c", guard_command],
                cwd=REPO_ROOT,
                check=False,
            )
            if result.returncode != 0:
                raise GateError("static regression guard failed")
        for command_id in command_ids:
            run_command(command_id, commands[command_id], dry_run=dry_run)
        print("\nIMPACTED REGRESSION GATE: PASSED" if not dry_run else "\nIMPACTED REGRESSION GATE: DRY RUN OK")
        return 0

    if mode != "release":
        raise AssertionError(mode)
    if dry_run:
        head = git("rev-parse", "HEAD")
        branch = git("branch", "--show-current")
    else:
        head, branch = ensure_clean_and_synced()
    required = registry["release_gate"]["required_commands"]
    results = [run_command(command_id, commands[command_id], dry_run=dry_run) for command_id in required]
    if dry_run:
        print("\nRELEASE REGRESSION GATE: DRY RUN OK")
        return 0
    if git("rev-parse", "HEAD") != head:
        raise GateError("HEAD changed while the release gate was running; results are invalid")
    if git("status", "--porcelain"):
        raise GateError("worktree changed while the release gate was running; results are invalid")
    evidence = {
        "schema_version": 1,
        "head": head,
        "branch": branch,
        "completed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "worktree_fingerprint": worktree_fingerprint(),
        "required_commands": required,
        "results": results,
    }
    EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE_PATH.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nRELEASE REGRESSION GATE: PASSED; evidence={EVIDENCE_PATH.relative_to(REPO_ROOT)}")
    return 0


def assert_release() -> int:
    registry = load_json(REGISTRY_PATH)
    evidence = load_json(EVIDENCE_PATH)
    head = git("rev-parse", "HEAD")
    if evidence.get("head") != head:
        raise GateError("release evidence does not belong to current HEAD; rerun the release gate")
    if git("status", "--porcelain"):
        raise GateError("worktree is not clean; release evidence is invalid")
    try:
        completed = dt.datetime.fromisoformat(str(evidence["completed_at"]))
    except (KeyError, ValueError) as exc:
        raise GateError("release evidence has an invalid completed_at") from exc
    age = dt.datetime.now(dt.timezone.utc) - completed.astimezone(dt.timezone.utc)
    max_age = dt.timedelta(hours=float(registry["release_gate"]["max_age_hours"]))
    if age < dt.timedelta(0) or age > max_age:
        raise GateError(f"release evidence is older than {max_age}; rerun the release gate")
    required = set(registry["release_gate"]["required_commands"])
    passed = {item.get("id") for item in evidence.get("results", []) if item.get("status") == "passed"}
    missing = required - passed
    if missing:
        raise GateError("release evidence is missing passed commands: " + ", ".join(sorted(missing)))
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
