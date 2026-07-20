from __future__ import annotations

import copy
import datetime as dt
import hashlib
import importlib.util
import inspect
import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).resolve().parents[1] / "run_regression_gate.py"
SPEC = importlib.util.spec_from_file_location("run_regression_gate", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
gate = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gate
SPEC.loader.exec_module(gate)


def pending_candidate_fixture() -> dict:
    return copy.deepcopy(gate.PINNED_HISTORICAL_BUILD_18_PENDING)


def verified_local_candidate_fixture() -> dict:
    return {
        "schema_version": 1,
        "status": "uploaded_pending_qualification",
        "head": "a" * 40,
        "tree": "b" * 40,
        "registry_blob": "c" * 40,
        "app_version": "1.0",
        "app_build": "19",
        "uploaded_at": "2026-07-16T06:04:09Z",
        "installation_source": "TestFlight",
        "upload": {
            "method": "verified_local_ipa_altool",
            "ipa_sha256": "4" * 64,
            "distribution_cdhash": "5" * 40,
            "archive_info_sha256": "1" * 64,
            "profile_sha256": "2" * 64,
            "distribution_certificate_sha256": "3" * 64,
            "upload_result_sha256": "6" * 64,
            "internal_gate_sha256": "7" * 64,
            "upload_tool": (
                "/Applications/Xcode.app/Contents/SharedFrameworks/"
                "ContentDelivery.framework/Versions/A/Resources/altoolShim"
            ),
        },
        "external_promotion_allowed": False,
    }


def registry(
    *,
    pending: bool = True,
    pending_candidate: dict | None = None,
    latest_uploaded_build: int | None = None,
) -> dict:
    latest = (
        gate.PINNED_LATEST_UPLOADED_BUILD
        if latest_uploaded_build is None
        else latest_uploaded_build
    )
    return {
        "commands": dict(gate.MANDATORY_RELEASE_COMMAND_TEMPLATES),
        "release_gate": {
            "max_age_hours": gate.PINNED_MAX_AGE_HOURS,
            "testflight_signoff_max_age_hours": (
                gate.PINNED_TESTFLIGHT_SIGNOFF_MAX_AGE_HOURS
            ),
            "latest_uploaded_build": latest,
            "github_repository": gate.PINNED_GITHUB_REPOSITORY,
            "github_workflow": gate.PINNED_GITHUB_WORKFLOW,
            "required_check": gate.PINNED_REQUIRED_CHECK,
            "branch_protection": copy.deepcopy(gate.PINNED_BRANCH_PROTECTION),
            "branch_roles": copy.deepcopy(gate.PINNED_BRANCH_ROLES),
            "pending_internal_candidate": (
                copy.deepcopy(pending_candidate or pending_candidate_fixture())
                if pending else None
            ),
            "post_upload_signoffs": [
                {
                    "id": signoff_id,
                    "description": f"Required TestFlight evidence for {signoff_id}.",
                }
                for signoff_id in gate.MANDATORY_RELEASE_SIGNOFFS
            ],
            "manual_signoffs": [
                {"id": signoff_id, "description": f"Required evidence for {signoff_id}."}
                for signoff_id in gate.MANDATORY_RELEASE_SIGNOFFS
            ],
            "required_commands": list(gate.MANDATORY_RELEASE_COMMANDS),
        },
    }


def backend_runtime_fixture() -> dict:
    return {
        "launcher": "/tmp/backend/.venv/bin/python",
        "resolved_executable": "/usr/bin/python3",
        "binary_sha256": "1" * 64,
        "version": "3.11.0",
        "prefix": "/tmp/backend/.venv",
        "base_prefix": "/usr",
        "purelib": "/tmp/backend/.venv/lib/python3.11/site-packages",
        "dependency_sha256": "2" * 64,
        "dependency_files": 100,
    }


def gate_python_fixture() -> dict:
    return {
        "executable": "/Applications/Xcode.app/Contents/Developer/usr/bin/python3",
        "version": "3.9.6",
        "isolated": "true",
    }


def remote_payloads(
    head: str = "a" * 40,
    branch: str = "main",
    app_slug: str = "github-actions",
    app_id: int = 15368,
):
    run = {
        "id": 42,
        "run_attempt": 1,
        "head_sha": head,
        "head_branch": branch,
        "path": ".github/workflows/ci.yml",
        "event": "push",
        "conclusion": "success",
        "html_url": "https://github.com/example/repo/actions/runs/42",
    }
    check = {
        "id": 84,
        "name": "quality-gate",
        "head_sha": head,
        "status": "completed",
        "conclusion": "success",
        "details_url": "https://github.com/example/repo/actions/runs/42/job/84",
        "completed_at": "2026-07-13T14:00:00Z",
        "app": {"slug": app_slug, "id": app_id},
    }
    return {"workflow_runs": [run]}, {"check_runs": [check]}


class RemoteQualityGateTests(unittest.TestCase):
    def test_impacted_gate_checks_current_working_tree_whitespace(self):
        self.assertIn("untracked-file", gate.IMPACTED_DIFF_CHECK)
        run_gate_source = inspect.getsource(gate.run_gate)
        first_diff_check = run_gate_source.index(
            "check_working_tree_whitespace(dry_run=dry_run)"
        )
        command_loop = run_gate_source.index("for command_id in command_ids:")
        final_diff_check = run_gate_source.rindex(
            "check_working_tree_whitespace(dry_run=dry_run)"
        )
        self.assertLess(first_diff_check, command_loop)
        self.assertLess(command_loop, final_diff_check)
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = Path(temp_dir)
            subprocess.run(["/usr/bin/git", "init", "-q"], cwd=repository, check=True)
            (repository / "tracked.txt").write_text("tracked\n", encoding="utf-8")
            subprocess.run(["/usr/bin/git", "add", "tracked.txt"], cwd=repository, check=True)
            subprocess.run(
                [
                    "/usr/bin/git", "-c", "user.name=Gate Test",
                    "-c", "user.email=gate@example.invalid", "commit", "-qm", "base",
                ],
                cwd=repository,
                check=True,
            )
            untracked = repository / "new file.txt"
            untracked.write_text("clean\n", encoding="utf-8")
            gate.check_working_tree_whitespace(dry_run=False, repo_root=repository)
            untracked.write_text("trailing space \n", encoding="utf-8")
            with self.assertRaisesRegex(gate.GateError, "untracked-file whitespace"):
                gate.check_working_tree_whitespace(dry_run=False, repo_root=repository)
        with tempfile.TemporaryDirectory() as temp_dir:
            lock_root = Path(temp_dir)
            with gate.gate_lock(lock_root):
                with self.assertRaisesRegex(gate.GateError, "already running"):
                    with gate.gate_lock(lock_root):
                        self.fail("a second gate acquired the repository lock")
        with mock.patch.object(gate, "worktree_fingerprint", return_value="changed"):
            with self.assertRaisesRegex(gate.GateError, "changed while the gate ran"):
                gate.ensure_working_state_unchanged("initial")

    def test_changed_test_files_add_every_corresponding_impacted_command(self):
        candidate = registry()
        candidate["behavior_domains"] = [
            {
                "id": "backend_chat_ai",
                "test_patterns": ["backend/tests/unit/test_chat_*.py"],
                "verification_commands": ["backend_ai"],
            },
            {
                "id": "backend_core",
                "test_patterns": ["backend/tests/**/*.py"],
                "verification_commands": ["backend_full"],
            },
            {
                "id": "quality_process_gate",
                "test_patterns": ["tools/tests/**/*.py"],
                "verification_commands": ["guard_unit", "ios_release_build", "diff_check"],
            },
        ]
        changed = [
            "backend/tests/unit/test_chat_routing.py",
            "tools/tests/test_python_test_gate.py",
        ]
        with mock.patch.object(gate, "load_json", return_value={"impacted_domains": []}):
            commands = gate.command_ids_for_impacted(candidate, changed_paths=changed)
            fast_commands = gate.command_ids_for_fast(candidate, changed_paths=changed)
        self.assertEqual(
            commands,
            ["backend_full", "guard_unit", "ios_release_build", "diff_check"],
        )
        self.assertEqual(
            fast_commands,
            ["backend_full", "guard_unit", "diff_check"],
        )
        self.assertNotIn("backend_ai", commands)
        self.assertNotIn("ios_release_build", fast_commands)
        self.assertTrue(gate.FAST_EXCLUDED_COMMANDS.isdisjoint(fast_commands))

        ios_candidate = registry()
        ios_candidate["behavior_domains"] = [
            {
                "id": "ios_ui_interaction",
                "test_patterns": ["Xjie/XjieUITests/**/*.swift"],
                "verification_commands": [
                    "ios_unit",
                    "ios_ui_full",
                    "ios_ui_small",
                    "ios_release_build",
                ],
            }
        ]
        with mock.patch.object(
            gate,
            "load_json",
            return_value={"impacted_domains": ["ios_ui_interaction"]},
        ):
            self.assertEqual(
                gate.command_ids_for_fast(ios_candidate, changed_paths=[]),
                ["ios_unit", "diff_check"],
            )

    def test_unmapped_test_file_cannot_produce_an_impacted_false_green(self):
        candidate = registry()
        candidate["behavior_domains"] = []
        with mock.patch.object(gate, "load_json", return_value={"impacted_domains": []}):
            with self.assertRaisesRegex(gate.GateError, "not mapped"):
                gate.command_ids_for_impacted(
                    candidate,
                    changed_paths=["experiments/test_unmapped.py"],
                )

    def test_impacted_change_parser_keeps_both_sides_of_test_rename(self):
        self.assertEqual(
            gate._parse_name_status(
                "R100\0backend/tests/unit/test_old.py\0docs/test_old.md\0"
            ),
            ["backend/tests/unit/test_old.py", "docs/test_old.md"],
        )

    def test_release_rejects_assume_unchanged_and_skip_worktree_index_flags(self):
        self.assertEqual(gate.hidden_index_paths("H normal.swift\n"), [])
        self.assertEqual(
            gate.hidden_index_paths("H normal.swift\nh hidden.swift\nS skipped.swift\n"),
            ["hidden.swift", "skipped.swift"],
        )
        with mock.patch.object(
            gate,
            "git",
            return_value="H normal.swift\nh hidden.swift\n",
        ), self.assertRaises(gate.GateError):
            gate.ensure_no_hidden_index_flags()

        completed = mock.Mock(returncode=0, stdout="", stderr="")
        with mock.patch.object(gate.subprocess, "run", return_value=completed) as git_run:
            gate.git("status", "--porcelain")
        self.assertEqual(git_run.call_args.args[0][0], "/usr/bin/git")
        self.assertEqual(git_run.call_args.kwargs["env"]["GIT_NO_REPLACE_OBJECTS"], "1")
        self.assertEqual(git_run.call_args.kwargs["env"]["GIT_CONFIG_GLOBAL"], "/dev/null")
        self.assertEqual(git_run.call_args.kwargs["env"]["GIT_CONFIG_NOSYSTEM"], "1")
        gate.ensure_no_git_repository_redirects(dict(gate.INTERNAL_SAFE_GIT_ENVIRONMENT))
        with self.assertRaises(gate.GateError):
            gate.ensure_no_git_repository_redirects({"GIT_CONFIG_GLOBAL": "/tmp/redirect"})
        with mock.patch.dict(
            os.environ,
            {
                "PYTEST_ADDOPTS": "--ignore=backend/tests",
                "PYTEST_PLUGINS": "untrusted_plugin",
                "SWIFT_EXEC": "/tmp/untrusted-swift",
                "TOOLCHAINS": "untrusted",
                "XCODE_XCCONFIG_FILE": "/tmp/untrusted.xcconfig",
            },
        ):
            child_environment = gate.trusted_subprocess_environment()
        for rejected in (
            "PYTEST_ADDOPTS",
            "PYTEST_PLUGINS",
            "SWIFT_EXEC",
            "TOOLCHAINS",
            "XCODE_XCCONFIG_FILE",
        ):
            self.assertNotIn(rejected, child_environment)

        with mock.patch.object(
            gate,
            "git",
            side_effect=[str(gate.REPO_ROOT), "refs/replace/official-head"],
        ), self.assertRaisesRegex(gate.GateError, "replace refs"):
            gate.ensure_canonical_repository_without_replace_refs()
        with tempfile.TemporaryDirectory() as redirected_root, mock.patch.object(
            gate,
            "git",
            return_value=redirected_root,
        ), self.assertRaisesRegex(gate.GateError, "repository root was redirected"):
            gate.ensure_canonical_repository_without_replace_refs()
        with mock.patch.object(
            gate,
            "git",
            return_value="url.https://secret-token@example.invalid/.insteadOf upstream:",
        ), self.assertRaisesRegex(
            gate.GateError, "unsafe local Git configuration"
        ) as unsafe_config:
            gate.ensure_safe_repository_configuration()
        self.assertNotIn("secret-token", str(unsafe_config.exception))
        with tempfile.TemporaryDirectory() as common_dir:
            info = Path(common_dir) / "info"
            info.mkdir()
            (info / "attributes").write_text("*.swift filter=audit\n", encoding="utf-8")
            with mock.patch.object(gate, "git", return_value=""), mock.patch.object(
                gate,
                "_git_common_directory",
                return_value=Path(common_dir),
            ), self.assertRaisesRegex(gate.GateError, "attributes override"):
                gate.ensure_safe_repository_configuration()

        for arguments in (
            ["fast", "--dry-run"],
            ["impacted", "--dry-run"],
            ["release", "--dry-run"],
            ["internal-testflight", "--dry-run"],
            ["assert-release"],
            ["assert-internal-testflight"],
            ["qualify-testflight"],
        ):
            with self.subTest(arguments=arguments), mock.patch.dict(
                "os.environ", {"GIT_DIR": "/tmp/redirected-repository"}
            ), mock.patch.object(gate, "git") as git_call:
                self.assertEqual(gate.main(arguments), 1)
                git_call.assert_not_called()

        for variable in ("HTTPS_PROXY", "http_proxy", "ALL_PROXY", "SSL_CERT_FILE"):
            with self.subTest(variable=variable), mock.patch.dict(
                "os.environ", {variable: "/tmp/untrusted-network-redirection"}
            ), mock.patch.object(gate, "git") as git_call:
                self.assertEqual(gate.main(["assert-release"]), 1)
                git_call.assert_not_called()

        for command in (
            "fast",
            "impacted",
            "release",
            "internal-testflight",
            "assert-release",
            "assert-internal-testflight",
            "qualify-testflight",
        ):
            arguments = [command, "--dry-run"] \
                if command in {"fast", "impacted", "release", "internal-testflight"} \
                else [command]
            with self.subTest(untrusted_gate_python=command), mock.patch.object(
                gate,
                "require_trusted_gate_python_runtime",
                side_effect=gate.GateError("untrusted gate Python"),
            ) as runtime_check, mock.patch.object(gate, "git") as git_call:
                self.assertEqual(gate.main(arguments), 1)
                runtime_check.assert_called_once_with()
                git_call.assert_not_called()

    def test_exact_sha_github_actions_quality_gate_is_required(self):
        head = "a" * 40
        payloads = remote_payloads(head=head)
        with mock.patch.object(gate, "github_json", side_effect=payloads) as github:
            result = gate.require_remote_quality_gate(head, registry())
        self.assertEqual(result["head_sha"], head)
        self.assertEqual(result["head_branch"], "main")
        self.assertEqual(result["workflow_run_id"], 42)
        self.assertEqual(result["check_run_id"], 84)
        self.assertEqual(result["check_app_slug"], "github-actions")
        self.assertEqual(result["check_app_id"], 15368)
        self.assertIn("branch=main", github.call_args_list[0].args[0])

    def test_branch_protection_requires_exact_check_and_non_bypassable_settings(self):
        payload = {
            "required_status_checks": {
                "strict": True,
                "checks": [{"context": "quality-gate", "app_id": 15368}],
            },
            "enforce_admins": {"enabled": True},
            "allow_force_pushes": {"enabled": False},
            "allow_deletions": {"enabled": False},
            "lock_branch": {"enabled": True},
            "allow_fork_syncing": {"enabled": False},
            "required_pull_request_reviews": {
                "required_approving_review_count": 0,
                "dismiss_stale_reviews": True,
                "require_code_owner_reviews": False,
                "require_last_push_approval": False,
            },
        }
        with mock.patch.object(gate, "github_json", return_value=payload):
            result = gate.require_branch_protection("XAGE", registry(), expected_app_id=15368)
        self.assertEqual(result["required_check"], "quality-gate")
        self.assertEqual(result["required_check_app_id"], 15368)
        self.assertTrue(result["strict"])
        self.assertTrue(result["enforce_admins"])
        self.assertTrue(result["lock_branch"])
        self.assertFalse(result["allow_fork_syncing"])

        explicit_empty_bypass = copy.deepcopy(payload)
        explicit_empty_bypass["required_pull_request_reviews"][
            "bypass_pull_request_allowances"
        ] = {"users": [], "teams": [], "apps": []}
        with mock.patch.object(gate, "github_json", return_value=explicit_empty_bypass):
            explicit_result = gate.require_branch_protection(
                "XAGE", registry(), expected_app_id=15368
            )
        self.assertTrue(
            explicit_result["required_pull_request_reviews"][
                "bypass_pull_request_allowances_empty"
            ]
        )

        main_payload = copy.deepcopy(payload)
        main_payload["lock_branch"]["enabled"] = False
        with mock.patch.object(gate, "github_json", return_value=main_payload):
            main_result = gate.require_branch_protection(
                "main", registry(), expected_app_id=15368
            )
        self.assertFalse(main_result["lock_branch"])
        self.assertFalse(main_result["allow_fork_syncing"])
        with mock.patch.object(gate, "github_json") as github, self.assertRaises(
            gate.GateError
        ):
            gate.require_branch_protection(
                "release-candidate", registry(), expected_app_id=15368
            )
        github.assert_not_called()

        mutations = (
            lambda item: item["required_status_checks"].update(strict=False),
            lambda item: item["required_status_checks"].pop("strict"),
            lambda item: item["required_status_checks"].update(strict=1),
            lambda item: item["required_status_checks"].update(checks=[]),
            lambda item: item["required_status_checks"]["checks"][0].update(app_id=-1),
            lambda item: item["enforce_admins"].update(enabled=False),
            lambda item: item.pop("enforce_admins"),
            lambda item: item.update(enforce_admins={"enabled": "true"}),
            lambda item: item["allow_force_pushes"].update(enabled=True),
            lambda item: item["allow_force_pushes"].pop("enabled"),
            lambda item: item.update(allow_force_pushes={"enabled": 0}),
            lambda item: item["allow_deletions"].update(enabled=True),
            lambda item: item.pop("allow_deletions"),
            lambda item: item["lock_branch"].update(enabled=False),
            lambda item: item["lock_branch"].pop("enabled"),
            lambda item: item["allow_fork_syncing"].update(enabled=True),
            lambda item: item.pop("allow_fork_syncing"),
            lambda item: item.update(required_pull_request_reviews=None),
            lambda item: item["required_pull_request_reviews"].update(
                required_approving_review_count=1
            ),
            lambda item: item["required_pull_request_reviews"].update(
                required_approving_review_count=False
            ),
            lambda item: item["required_pull_request_reviews"].pop(
                "require_code_owner_reviews"
            ),
            lambda item: item["required_pull_request_reviews"].update(
                require_last_push_approval=0
            ),
            lambda item: item["required_pull_request_reviews"].update(
                bypass_pull_request_allowances=None
            ),
            lambda item: item["required_pull_request_reviews"].update(
                bypass_pull_request_allowances={}
            ),
            lambda item: item["required_pull_request_reviews"].update(
                bypass_pull_request_allowances={
                    "users": [{"login": "admin"}], "teams": [], "apps": []
                }
            ),
            lambda item: item["required_pull_request_reviews"].update(
                bypass_pull_request_allowances={
                    "users": [], "teams": [], "apps": [], "extra": []
                }
            ),
        )
        for mutate in mutations:
            invalid = copy.deepcopy(payload)
            mutate(invalid)
            with self.subTest(payload=invalid), mock.patch.object(
                gate, "github_json", return_value=invalid
            ):
                with self.assertRaises(gate.GateError):
                    gate.require_branch_protection("XAGE", registry(), expected_app_id=15368)

    def test_release_requires_protection_on_both_xage_and_main(self):
        protected = {
            "required_check": "quality-gate",
            "required_check_app_id": 15368,
            "strict": True,
            "enforce_admins": True,
            "allow_force_pushes": False,
            "allow_deletions": False,
            "required_pull_request_reviews": copy.deepcopy(
                gate.PINNED_BRANCH_PROTECTION["required_pull_request_reviews"]
            ),
        }

        def protected_for(branch, _registry, *, expected_app_id):
            return {
                **copy.deepcopy(protected),
                **copy.deepcopy(gate.PINNED_BRANCH_ROLES["protected_branches"][branch]),
            }

        with mock.patch.object(
            gate, "require_branch_protection", side_effect=protected_for
        ) as verifier:
            result = gate.require_all_branch_protections(registry(), expected_app_id=15368)
        self.assertEqual(list(result), ["main", "XAGE"])
        self.assertFalse(result["main"]["lock_branch"])
        self.assertTrue(result["XAGE"]["lock_branch"])
        self.assertEqual([call.args[0] for call in verifier.call_args_list], ["main", "XAGE"])

    def test_release_registry_cannot_remove_or_reorder_mandatory_commands(self):
        self.assertEqual(
            gate.required_release_commands(registry()),
            list(gate.MANDATORY_RELEASE_COMMANDS),
        )
        for mutate in (
            lambda item: item["release_gate"]["required_commands"].pop(),
            lambda item: item["release_gate"]["required_commands"].reverse(),
            lambda item: item["commands"].pop("ios_ui_full"),
        ):
            weakened = copy.deepcopy(registry())
            mutate(weakened)
            with self.assertRaises(gate.GateError):
                gate.required_release_commands(weakened)

    def test_release_registry_identity_and_small_device_override_are_pinned(self):
        for field, value in (
            ("github_repository", "other/repo"),
            ("github_workflow", "other.yml"),
            ("required_check", {"name": "fake", "app_slug": "github-actions"}),
            (
                "branch_roles",
                {
                    "canonical_branch": "XAGE",
                    "read_only_branches": ["main"],
                    "protected_branches": {},
                },
            ),
            ("max_age_hours", 240),
            ("testflight_signoff_max_age_hours", 24),
            ("latest_uploaded_build", 16),
            ("branch_protection", {"strict": True}),
        ):
            redirected = copy.deepcopy(registry())
            redirected["release_gate"][field] = value
            with self.assertRaises(gate.GateError):
                gate.validate_release_registry_identity(redirected)

        for mutate in (
            lambda item: item["release_gate"]["branch_roles"].update(
                canonical_branch="XAGE"
            ),
            lambda item: item["release_gate"]["branch_roles"].update(
                read_only_branches=[]
            ),
            lambda item: item["release_gate"]["branch_roles"].update(
                protected_branches={
                    "XAGE": {"lock_branch": True, "allow_fork_syncing": False},
                    "main": {"lock_branch": False, "allow_fork_syncing": False},
                }
            ),
            lambda item: item["release_gate"]["branch_roles"]["protected_branches"]
            ["main"].update(lock_branch=True),
            lambda item: item["release_gate"]["branch_roles"]["protected_branches"]
            ["main"].update(lock_branch=0),
            lambda item: item["release_gate"]["branch_roles"]["protected_branches"]
            ["XAGE"].update(allow_fork_syncing=True),
            lambda item: item["release_gate"]["branch_roles"]["protected_branches"]
            ["XAGE"].update(allow_fork_syncing=0),
            lambda item: item["release_gate"]["branch_protection"].update(
                allow_force_pushes=0
            ),
            lambda item: item["release_gate"].update(max_age_hours=24.0),
            lambda item: item["release_gate"].update(
                testflight_signoff_max_age_hours=168.0
            ),
            lambda item: item["release_gate"].update(latest_uploaded_build=18.0),
            lambda item: item["release_gate"]["pending_internal_candidate"].update(
                external_promotion_allowed=True
            ),
            lambda item: item["release_gate"]["pending_internal_candidate"]["upload"].update(
                upload_result_sha256="not-a-digest"
            ),
            lambda item: item["release_gate"]["pending_internal_candidate"].update(
                upload=verified_local_candidate_fixture()["upload"]
            ),
            lambda item: item["release_gate"]["post_upload_signoffs"].pop(),
            lambda item: item["release_gate"].update(protected_branches=["main", "XAGE"]),
        ):
            redirected = copy.deepcopy(registry())
            mutate(redirected)
            with self.assertRaises(gate.GateError):
                gate.validate_release_registry_identity(redirected)

        self.assertEqual(gate.canonical_release_branch(registry()), "main")
        head = "a" * 40
        with mock.patch.object(
            gate,
            "git",
            side_effect=[
                "",
                "",
                "main",
                head,
                "refs/remotes/origin/main",
                head,
                "0\t0",
            ],
        ):
            self.assertEqual(gate.ensure_clean_and_synced(registry()), (head, "main"))
        for values in (
            ["", "", "XAGE"],
            ["", "", "main", head, "refs/remotes/origin/XAGE"],
            ["", "", "main", head, "refs/remotes/untrusted/main"],
        ):
            with self.subTest(git_values=values), mock.patch.object(
                gate, "git", side_effect=values
            ), self.assertRaises(gate.GateError):
                gate.ensure_clean_and_synced(registry())

        with mock.patch.dict("os.environ", {"XJIE_SMALL_SIMULATOR_NAME": "iPhone 17 Pro"}):
            with self.assertRaises(gate.GateError):
                gate.expand_command(gate.MANDATORY_RELEASE_COMMAND_TEMPLATES["ios_ui_small"])

    def test_wrong_sha_branch_app_or_workflow_run_link_fails_closed(self):
        head = "a" * 40
        cases = []

        wrong_sha = remote_payloads(head="b" * 40)
        cases.append(wrong_sha)

        wrong_branch = remote_payloads(head=head, branch="XAGE")
        cases.append(wrong_branch)

        wrong_app = remote_payloads(head=head, app_slug="third-party")
        cases.append(wrong_app)

        float_app_id = remote_payloads(head=head)
        float_app_id[1]["check_runs"][0]["app"]["id"] = 15368.0
        cases.append(float_app_id)

        float_run_id = remote_payloads(head=head)
        float_run_id[0]["workflow_runs"][0]["id"] = 42.0
        cases.append(float_run_id)

        wrong_app_id = remote_payloads(head=head, app_id=999)
        cases.append(wrong_app_id)

        wrong_link = list(remote_payloads(head=head))
        wrong_link[1] = copy.deepcopy(wrong_link[1])
        wrong_link[1]["check_runs"][0]["details_url"] = (
            "https://github.com/example/repo/actions/runs/999/job/84"
        )
        cases.append(tuple(wrong_link))

        manual_dispatch = list(remote_payloads(head=head))
        manual_dispatch[0] = copy.deepcopy(manual_dispatch[0])
        manual_dispatch[0]["workflow_runs"][0]["event"] = "workflow_dispatch"
        cases.append(tuple(manual_dispatch))

        for payloads in cases:
            with self.subTest(payloads=payloads), mock.patch.object(
                gate, "github_json", side_effect=payloads
            ):
                with self.assertRaises(gate.GateError):
                    gate.require_remote_quality_gate(head, registry())

    def test_official_remote_tip_does_not_trust_mutable_origin(self):
        head = "a" * 40
        with mock.patch.object(
            gate,
            "github_json",
            side_effect=[
                {
                    "full_name": gate.PINNED_GITHUB_REPOSITORY,
                    "default_branch": "main",
                },
                {"commit": {"sha": head}},
            ],
        ) as github:
            self.assertEqual(
                gate.ensure_official_remote_tip(head, registry()),
                head,
            )
        requested_paths = [call.args[0] for call in github.call_args_list]
        self.assertEqual(requested_paths[0], "/repos/doyoulikelin-wq/XJie_IOS")
        self.assertIn(
            "/repos/doyoulikelin-wq/XJie_IOS/branches/main",
            requested_paths[1],
        )
        self.assertFalse(any("/branches/XAGE" in path for path in requested_paths))

        with mock.patch.object(
            gate,
            "github_json",
            side_effect=[
                {
                    "full_name": gate.PINNED_GITHUB_REPOSITORY,
                    "default_branch": "main",
                },
                {"commit": {"sha": "b" * 40}},
            ],
        ):
            with self.assertRaises(gate.GateError):
                gate.ensure_official_remote_tip(head, registry())

        for repository_payload in (
            {
                "full_name": gate.PINNED_GITHUB_REPOSITORY,
                "default_branch": "XAGE",
            },
            {"full_name": "fork/XJie_IOS", "default_branch": "main"},
        ):
            with self.subTest(repository=repository_payload), mock.patch.object(
                gate, "github_json", return_value=repository_payload
            ) as github:
                with self.assertRaises(gate.GateError):
                    gate.ensure_official_remote_tip(head, registry())
            github.assert_called_once_with(
                "/repos/doyoulikelin-wq/XJie_IOS", require_auth=True
            )

        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{"ok": true}'
        opener = mock.Mock()
        opener.open.return_value = response
        with mock.patch.object(gate, "github_token", return_value=None), mock.patch.object(
            gate.urllib.request,
            "build_opener",
            return_value=opener,
        ) as build_opener:
            self.assertEqual(gate._github_payload("/rate_limit"), {"ok": True})
        proxy_handler, https_handler = build_opener.call_args.args
        self.assertEqual(proxy_handler.proxies, {})
        self.assertIsNotNone(https_handler._context)

    def test_release_head_must_be_from_merged_pull_request_into_official_branch(self):
        head = "a" * 40
        pull = {
            "number": 123,
            "html_url": "https://github.com/doyoulikelin-wq/XJie_IOS/pull/123",
            "state": "closed",
            "merged_at": "2026-07-13T14:00:00Z",
            "merge_commit_sha": head,
            "base": {
                "ref": "main",
                "repo": {"full_name": gate.PINNED_GITHUB_REPOSITORY},
            },
        }
        with mock.patch.object(gate, "github_list", return_value=[pull]):
            result = gate.require_merged_pull_request(head, registry())
        self.assertEqual(result["number"], 123)
        self.assertEqual(result["merge_commit_sha"], head)
        self.assertEqual(result["base_branch"], "main")

        for mutate in (
            lambda item: item.update(state="open"),
            lambda item: item.update(merged_at=None),
            lambda item: item.update(merge_commit_sha="b" * 40),
            lambda item: item["base"].update(ref="XAGE"),
            lambda item: item["base"]["repo"].update(full_name="fork/XJie_IOS"),
        ):
            invalid = copy.deepcopy(pull)
            mutate(invalid)
            with self.subTest(pull=invalid), mock.patch.object(
                gate, "github_list", return_value=[invalid]
            ):
                with self.assertRaises(gate.GateError):
                    gate.require_merged_pull_request(head, registry())

    def test_release_evidence_rejects_identity_command_and_remote_tampering(self):
        now = dt.datetime(2026, 7, 13, 15, 0, tzinfo=dt.timezone.utc)
        app_identity = gate.project_version_identity()
        remote = {
            "head_sha": "a" * 40,
            "head_branch": "main",
            "workflow_run_id": 42,
            "workflow_run_attempt": 1,
            "workflow_url": "https://github.com/doyoulikelin-wq/XJie_IOS/actions/runs/42",
            "check_run_id": 84,
            "check_name": "quality-gate",
            "check_app_slug": "github-actions",
            "check_app_id": 15368,
            "check_completed_at": "2026-07-13T14:05:00Z",
        }
        protection = {
            "required_check": "quality-gate",
            "required_check_app_id": 15368,
            "strict": True,
            "enforce_admins": True,
            "allow_force_pushes": False,
            "allow_deletions": False,
            "lock_branch": False,
            "allow_fork_syncing": False,
            "required_pull_request_reviews": copy.deepcopy(
                gate.PINNED_BRANCH_PROTECTION["required_pull_request_reviews"]
            ),
        }
        protections = {
            "main": {
                **copy.deepcopy(protection),
            },
            "XAGE": {
                **copy.deepcopy(protection),
                "lock_branch": True,
            },
        }
        signoffs = {
            "schema_version": 1,
            "head": "a" * 40,
            "tree": "tree",
            "registry_blob": "registry",
            "completed_at": (now - dt.timedelta(minutes=10)).isoformat(),
            "items": list(gate.MANDATORY_RELEASE_SIGNOFFS),
            **app_identity,
            "sha256": "signoff-digest",
        }
        small_simulator = {
            "name": gate.PINNED_SMALL_SIMULATOR_NAME,
            "udid": "small-udid",
            "device_type": gate.PINNED_SMALL_DEVICE_TYPE,
            "runtime": "com.apple.CoreSimulator.SimRuntime.iOS-26-3",
        }
        xcode_toolchain = {
            "developer_dir": gate.PINNED_DEVELOPER_DIR,
            "version": gate.PINNED_XCODE_VERSION,
            "build": gate.PINNED_XCODE_BUILD,
            "binary": f"{gate.PINNED_DEVELOPER_DIR}/usr/bin/xcodebuild",
        }
        merged_pull_request = {
            "number": 123,
            "url": "https://github.com/doyoulikelin-wq/XJie_IOS/pull/123",
            "merged_at": "2026-07-13T14:00:00Z",
            "merge_commit_sha": "a" * 40,
            "base_repository": gate.PINNED_GITHUB_REPOSITORY,
            "base_branch": "main",
        }
        backend_runtime = backend_runtime_fixture()
        gate_python = gate_python_fixture()
        backend_inventory = gate._load_expected_backend_tests()
        backend_skip_count = len(gate.BACKEND_FULL_ALLOWED_SKIPS)
        self.assertEqual(len(backend_inventory), gate.CURRENT_BACKEND_FULL_TESTS)
        self.assertEqual(gate.CURRENT_BACKEND_FULL_TESTS, 335)
        self.assertEqual(gate.MINIMUM_BACKEND_FULL_TESTS, 324)
        backend_junit = {
            "junit_path": str(gate.BACKEND_JUNIT_PATHS["backend_full"]),
            "junit_sha256": "3" * 64,
            "junit_inventory_sha256": gate._backend_inventory_sha256(
                backend_inventory
            ),
            "executed_tests": len(backend_inventory),
            "passed_tests": len(backend_inventory) - backend_skip_count,
            "skipped_tests": backend_skip_count,
        }
        commands = registry()["commands"]
        evidence = {
            "schema_version": 5,
            "head": "a" * 40,
            "branch": "main",
            "tree": "tree",
            "registry_blob": "registry",
            "remote_tip": "a" * 40,
            "completed_at": (now - dt.timedelta(minutes=5)).isoformat(),
            "worktree_fingerprint": "fp",
            "required_commands": list(gate.MANDATORY_RELEASE_COMMANDS),
            "results": [
                {
                    "id": command_id,
                    "template": commands[command_id],
                    "command": gate.expand_command(
                        commands[command_id], backend_runtime=backend_runtime
                    ),
                    "status": "passed",
                    **(backend_junit if command_id == "backend_full" else {}),
                }
                for command_id in gate.MANDATORY_RELEASE_COMMANDS
            ],
            "remote_quality_gate": remote,
            "merged_pull_request": merged_pull_request,
            "branch_protections": protections,
            "small_simulator": small_simulator,
            "xcode_toolchain": xcode_toolchain,
            "backend_runtime": backend_runtime,
            "gate_python": gate_python,
            "manual_signoffs": signoffs,
        }
        arguments = dict(
            head="a" * 40,
            tree="tree",
            registry_blob="registry",
            remote_tip="a" * 40,
            remote_gate=remote,
            merged_pull_request=merged_pull_request,
            branch_protections=protections,
            manual_signoffs=signoffs,
            small_simulator=small_simulator,
            xcode_toolchain=xcode_toolchain,
            backend_runtime=backend_runtime,
            gate_python=gate_python,
            now=now,
        )
        with mock.patch.object(gate, "worktree_fingerprint", return_value="fp"), mock.patch.object(
            gate, "validate_backend_junit_output", return_value=backend_junit
        ):
            gate.validate_release_evidence(evidence, registry(), **arguments)

            internal_as_final = {
                "schema_version": 1,
                "phase": "internal_testflight_upload",
                **{
                    key: value
                    for key, value in evidence.items()
                    if key not in {"schema_version", "manual_signoffs"}
                },
            }
            copied_internal = copy.deepcopy(internal_as_final)
            copied_internal["schema_version"] = 5
            copied_internal["manual_signoffs"] = copy.deepcopy(signoffs)
            with self.assertRaisesRegex(gate.GateError, "exact final schema"):
                gate.validate_release_evidence(
                    copied_internal, registry(), **arguments
                )

            for mutate in (
                lambda item: item.update(schema_version=5.0),
                lambda item: item.update(branch="XAGE"),
                lambda item: item.update(remote_tip="b" * 40),
                lambda item: item["results"].reverse(),
                lambda item: item["results"][0].update(template="true"),
                lambda item: item["remote_quality_gate"].update(check_run_id=999),
                lambda item: item["remote_quality_gate"].update(workflow_run_id=42.0),
                lambda item: item["remote_quality_gate"].update(head_branch="XAGE"),
                lambda item: item["remote_quality_gate"].update(head_sha="b" * 40),
                lambda item: item["merged_pull_request"].update(number=999),
                lambda item: item["merged_pull_request"].update(base_branch="XAGE"),
                lambda item: item["merged_pull_request"].update(
                    merge_commit_sha="b" * 40
                ),
                lambda item: item["branch_protections"]["main"].update(enforce_admins=False),
                lambda item: item["branch_protections"]["main"].update(lock_branch=True),
                lambda item: item["branch_protections"]["XAGE"].update(
                    allow_fork_syncing=True
                ),
                lambda item: item["manual_signoffs"].update(sha256="changed"),
                lambda item: item["manual_signoffs"].update(app_build="999999"),
                lambda item: item["small_simulator"].update(device_type="iPhone Pro"),
                lambda item: item["xcode_toolchain"].update(build="untrusted"),
                lambda item: item["backend_runtime"].update(dependency_sha256="4" * 64),
                lambda item: item["gate_python"].update(isolated="false"),
                lambda item: next(
                    result for result in item["results"] if result["id"] == "backend_full"
                ).update(executed_tests=0),
            ):
                tampered = copy.deepcopy(evidence)
                mutate(tampered)
                with self.assertRaises(gate.GateError):
                    gate.validate_release_evidence(tampered, registry(), **arguments)

            coupled_mutations = (
                lambda cached, live: (
                    cached.update(remote_tip="b" * 40),
                    live.update(remote_tip="b" * 40),
                ),
                lambda cached, live: (
                    cached["remote_quality_gate"].update(head_branch="XAGE"),
                    live["remote_gate"].update(head_branch="XAGE"),
                ),
                lambda cached, live: (
                    cached["merged_pull_request"].update(base_branch="XAGE"),
                    live["merged_pull_request"].update(base_branch="XAGE"),
                ),
                lambda cached, live: (
                    cached["merged_pull_request"].update(
                        merge_commit_sha="b" * 40
                    ),
                    live["merged_pull_request"].update(
                        merge_commit_sha="b" * 40
                    ),
                ),
                lambda cached, live: (
                    cached.update(
                        branch_protections={
                            "XAGE": cached["branch_protections"]["XAGE"],
                            "main": cached["branch_protections"]["main"],
                        }
                    ),
                    live.update(
                        branch_protections={
                            "XAGE": live["branch_protections"]["XAGE"],
                            "main": live["branch_protections"]["main"],
                        }
                    ),
                ),
                lambda cached, live: (
                    cached["remote_quality_gate"].update(workflow_run_id=42.0),
                    live["remote_gate"].update(workflow_run_id=42.0),
                ),
                lambda cached, live: (
                    cached["branch_protections"]["main"].update(lock_branch=0),
                    live["branch_protections"]["main"].update(lock_branch=0),
                ),
            )
            for mutate in coupled_mutations:
                tampered = copy.deepcopy(evidence)
                live_arguments = copy.deepcopy(arguments)
                mutate(tampered, live_arguments)
                with self.assertRaises(gate.GateError):
                    gate.validate_release_evidence(
                        tampered, registry(), **live_arguments
                    )

        with tempfile.TemporaryDirectory() as dot_dir:
            sentinel = Path(dot_dir) / "zshenv-was-loaded"
            (Path(dot_dir) / ".zshenv").write_text(
                f"print loaded > {shlex.quote(str(sentinel))}\nreturn 97\n",
                encoding="utf-8",
            )
            with mock.patch.dict(os.environ, {"ZDOTDIR": dot_dir}):
                result = gate.run_command("zsh_no_user_rc", "/usr/bin/true", dry_run=False)
            self.assertEqual(result["status"], "passed")
            self.assertFalse(sentinel.exists())

        with tempfile.TemporaryDirectory() as temp_dir:
            junit_path = Path(temp_dir) / "backend-health.xml"
            health_command = gate.load_json(gate.REGISTRY_PATH)["commands"]["backend_health"]
            health_modules = gate._focused_backend_modules(health_command)
            health_ids = sorted(
                node
                for node in gate._load_expected_backend_tests()
                if any(
                    node.partition("::")[0] == module
                    or node.partition("::")[0].startswith(module + ".")
                    for module in health_modules
                )
            )

            def write_health_junit() -> ET.Element:
                root = ET.Element("testsuites")
                suite = ET.SubElement(root, "testsuite")
                for node in health_ids:
                    classname, name = node.split("::", maxsplit=1)
                    ET.SubElement(suite, "testcase", classname=classname, name=name)
                junit_path.write_bytes(ET.tostring(root, encoding="utf-8"))
                return root

            with mock.patch.object(
                gate, "BACKEND_JUNIT_PATHS", {"backend_health": junit_path}
            ):
                root = write_health_junit()
                summary = gate.validate_backend_junit_output(
                    "backend_health", junit_path, health_command
                )
                self.assertEqual(
                    (summary["executed_tests"], summary["passed_tests"], summary["skipped_tests"]),
                    (87, 87, 0),
                )
                with self.assertRaisesRegex(gate.GateError, "selection"):
                    gate.validate_backend_junit_output(
                        "backend_health",
                        junit_path,
                        health_command.replace(
                            " backend/tests/unit/test_account_lifecycle.py", ""
                        ),
                    )

                suite = next(root.iter("testsuite"))
                suite.remove(list(suite)[-1])
                junit_path.write_bytes(ET.tostring(root, encoding="utf-8"))
                with self.assertRaisesRegex(gate.GateError, "inventory mismatch"):
                    gate.validate_backend_junit_output(
                        "backend_health", junit_path, health_command
                    )

                write_health_junit()
                with junit_path.open("ab") as handle:
                    handle.write(b"not-xml")
                with self.assertRaisesRegex(gate.GateError, "malformed"):
                    gate.validate_backend_junit_output(
                        "backend_health", junit_path, health_command
                    )

                write_health_junit()
                with self.assertRaises(gate.GateError):
                    gate.run_command(
                        "backend_health",
                        "/usr/bin/true",
                        dry_run=False,
                        backend_runtime=backend_runtime_fixture(),
                    )
                self.assertFalse(junit_path.exists())

        with tempfile.TemporaryDirectory() as temp_dir:
            fake_venv = Path(temp_dir) / ".venv"
            (fake_venv / "bin").mkdir(parents=True)
            (fake_venv / "pyvenv.cfg").write_text(
                "include-system-site-packages = false\n", encoding="utf-8"
            )
            launcher = fake_venv / "bin" / "python"
            launcher.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            launcher.chmod(0o755)
            with self.assertRaisesRegex(gate.GateError, "native executable"):
                gate.backend_runtime_identity(fake_venv)
            launcher.unlink()
            launcher.symlink_to("/usr/bin/true")
            with self.assertRaisesRegex(gate.GateError, "identity probe"):
                gate.backend_runtime_identity(fake_venv)

    def test_upload_gate_allows_missing_post_upload_signoffs_but_preserves_candidate_checks(self):
        candidate_registry = registry(pending=False)
        candidate_identity = {"app_version": "1.0", "app_build": "19"}
        gate.require_no_pending_internal_candidate(candidate_registry)
        with self.assertRaisesRegex(gate.GateError, "protected registry PR"):
            gate.require_no_pending_internal_candidate(registry())
        with mock.patch.object(
            gate, "load_json", return_value=candidate_registry
        ), mock.patch.object(
            gate, "project_version_identity", return_value=candidate_identity
        ), mock.patch.object(
            gate,
            "require_new_release_build",
            wraps=gate.require_new_release_build,
        ) as version_check, mock.patch.object(
            gate, "require_trusted_gate_python_runtime", return_value=gate_python_fixture()
        ), mock.patch.object(
            gate, "backend_runtime_identity", return_value=backend_runtime_fixture()
        ), mock.patch.object(
            gate, "git", side_effect=["a" * 40, "main"]
        ), mock.patch.object(
            gate, "run_command", return_value={"status": "dry-run"}
        ) as command, mock.patch.object(
            gate,
            "validate_manual_signoffs",
            side_effect=AssertionError("upload gate must not read post-upload signoffs"),
        ) as signoffs:
            self.assertEqual(gate.run_gate("internal-testflight", dry_run=True), 0)
        version_check.assert_called_once_with(candidate_registry)
        signoffs.assert_not_called()
        self.assertEqual(
            [call.args[0] for call in command.call_args_list],
            list(gate.MANDATORY_RELEASE_COMMANDS),
        )

        with self.assertRaisesRegex(gate.GateError, "exact internal schema"):
            gate.validate_internal_testflight_evidence(
                {"schema_version": 5, "phase": "internal_testflight_upload"},
                candidate_registry,
                head="a" * 40,
                tree="b" * 40,
                registry_blob="c" * 40,
                remote_tip="a" * 40,
                remote_gate={},
                merged_pull_request={},
                branch_protections={},
                small_simulator={},
                xcode_toolchain={},
                backend_runtime={},
                gate_python={},
            )

    def test_post_upload_qualification_binds_successful_receipt_and_rejects_wrong_build_or_preupload_evidence(self):
        now = dt.datetime(2026, 7, 20, 7, 0, tzinfo=dt.timezone.utc)
        pending = verified_local_candidate_fixture()
        future_registry = registry(
            pending_candidate=pending,
            latest_uploaded_build=19,
        )
        uploaded_at = dt.datetime.fromisoformat(
            pending["uploaded_at"].replace("Z", "+00:00")
        )
        pending_sha256 = gate._sha256_json(pending)
        payload = {
            "schema_version": 1,
            "head": pending["head"],
            "tree": pending["tree"],
            "registry_blob": pending["registry_blob"],
            "pending_candidate_sha256": pending_sha256,
            "upload_receipt_identifier": gate.pending_upload_receipt_identifier(pending),
            "installation_source": "TestFlight",
            "completed_at": (now - dt.timedelta(minutes=5)).isoformat(),
            "items": [
                {
                    "id": signoff_id,
                    "status": "passed",
                    "tester": "Lin Reviewer",
                    "app_version": pending["app_version"],
                    "app_build": pending["app_build"],
                    "pending_candidate_sha256": pending_sha256,
                    "upload_receipt_identifier": gate.pending_upload_receipt_identifier(
                        pending
                    ),
                    "installation_source": "TestFlight",
                    "tested_at": (uploaded_at + dt.timedelta(minutes=20)).isoformat(),
                    "environment": "TestFlight on iPhone 17 Pro with iOS 26.3.1",
                    "steps": [
                        "Install the exact build from TestFlight and execute the named scenario.",
                        "Compare the observed result with the expected result and record evidence.",
                    ],
                    "evidence_reference": f"evidence/{signoff_id}.md",
                    "evidence_sha256": "0" * 64,
                }
                for signoff_id in gate.MANDATORY_RELEASE_SIGNOFFS
            ],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            signoff_path = Path(temp_dir) / "release_signoffs.json"
            evidence_root = Path(temp_dir) / "evidence"
            evidence_root.mkdir()
            for item in payload["items"]:
                evidence_path = evidence_root / f"{item['id']}.md"
                evidence_path.write_text(
                    f"redacted TestFlight evidence for {item['id']}\n", encoding="utf-8"
                )
                item["evidence_reference"] = str(evidence_path)
                item["evidence_sha256"] = hashlib.sha256(
                    evidence_path.read_bytes()
                ).hexdigest()

            def validate(
                candidate: dict,
                *,
                validation_now: dt.datetime = now,
            ) -> dict:
                signoff_path.write_text(json.dumps(candidate), encoding="utf-8")
                with mock.patch.object(
                    gate, "SIGNOFF_EVIDENCE_ROOT", evidence_root
                ):
                    return gate.validate_manual_signoffs(
                        future_registry,
                        signoff_path=signoff_path,
                        head=pending["head"],
                        tree=pending["tree"],
                        registry_blob=pending["registry_blob"],
                        now=validation_now,
                        candidate_identity={
                            "app_version": pending["app_version"],
                            "app_build": pending["app_build"],
                        },
                        definitions_key="post_upload_signoffs",
                        minimum_tested_at=uploaded_at,
                        require_testflight=True,
                        pending_candidate_sha256=pending_sha256,
                        upload_receipt_identifier=gate.pending_upload_receipt_identifier(
                            pending
                        ),
                    )

            summary = validate(payload)
            self.assertEqual(summary["installation_source"], "TestFlight")
            self.assertEqual(summary["pending_candidate_sha256"], pending_sha256)
            self.assertEqual(
                summary["upload_receipt_identifier"],
                f"altool-result-sha256:{pending['upload']['upload_result_sha256']}",
            )
            with self.assertRaisesRegex(gate.GateError, "stale"):
                validate(
                    payload,
                    validation_now=uploaded_at + dt.timedelta(days=8),
                )

            mutations = (
                lambda item: item["items"][0].update(app_build="999"),
                lambda item: item["items"][0].update(
                    tested_at=(uploaded_at - dt.timedelta(seconds=1)).isoformat()
                ),
                lambda item: item["items"][0].update(
                    tested_at=uploaded_at.isoformat()
                ),
                lambda item: item.update(installation_source="Local archive"),
                lambda item: item["items"][0].update(installation_source="Xcode"),
                lambda item: item.update(pending_candidate_sha256="f" * 64),
                lambda item: item.update(upload_receipt_identifier="wrong-receipt"),
                lambda item: item["items"][0].update(
                    pending_candidate_sha256="f" * 64
                ),
                lambda item: item["items"][0].update(
                    upload_receipt_identifier="wrong-receipt"
                ),
            )
            for mutate in mutations:
                invalid = copy.deepcopy(payload)
                mutate(invalid)
                with self.subTest(mutation=mutate), self.assertRaises(gate.GateError):
                    validate(invalid)

        def qualification_for(
            candidate_registry: dict,
            *,
            pinned_latest: int,
            candidate_tree: str | None = None,
            candidate_registry_blob: str | None = None,
            candidate_project_version: str | None = None,
            candidate_project_build: str | None = None,
        ) -> dict:
            tracked = candidate_registry["release_gate"]["pending_internal_candidate"]
            git_results = [
                tracked["tree"] if candidate_tree is None else candidate_tree,
                (
                    tracked["registry_blob"]
                    if candidate_registry_blob is None
                    else candidate_registry_blob
                ),
                (
                    "MARKETING_VERSION = "
                    f"{tracked['app_version'] if candidate_project_version is None else candidate_project_version};\n"
                    "CURRENT_PROJECT_VERSION = "
                    f"{tracked['app_build'] if candidate_project_build is None else candidate_project_build};\n"
                ),
            ]
            with mock.patch.object(
                gate, "PINNED_LATEST_UPLOADED_BUILD", pinned_latest
            ), mock.patch.object(
                gate, "load_json", return_value=candidate_registry
            ), mock.patch.object(
                gate, "ensure_clean_and_synced", return_value=("d" * 40, "main")
            ), mock.patch.object(
                gate, "ensure_official_remote_tip", return_value="d" * 40
            ), mock.patch.object(
                gate, "git", side_effect=git_results
            ), mock.patch.object(
                gate, "require_remote_quality_gate", return_value={"check_app_id": 15368}
            ) as remote_gate_validator, mock.patch.object(
                gate, "require_merged_pull_request", return_value={"number": 100}
            ), mock.patch.object(
                gate, "require_all_branch_protections", return_value={"main": {}, "XAGE": {}}
            ), mock.patch.object(
                gate, "validate_manual_signoffs", return_value={"schema_version": 1}
            ) as signoff_validator, mock.patch.object(
                gate, "_write_new_local_evidence"
            ) as writer:
                self.assertEqual(gate.qualify_testflight(), 0)
            self.assertEqual(
                signoff_validator.call_args.kwargs["signoff_path"],
                gate.TESTFLIGHT_SIGNOFF_PATH,
            )
            self.assertEqual(
                [call.args[0] for call in remote_gate_validator.call_args_list],
                ["d" * 40, tracked["head"]],
            )
            writer.assert_called_once()
            self.assertEqual(
                writer.call_args.args[0],
                gate.testflight_qualification_path(tracked),
            )
            return writer.call_args.args[1]

        verified_ipa_qualification = qualification_for(
            future_registry,
            pinned_latest=19,
        )
        self.assertTrue(verified_ipa_qualification["internal_testflight_qualified"])
        self.assertTrue(verified_ipa_qualification["external_promotion_allowed"])
        self.assertEqual(
            verified_ipa_qualification["qualification_scope"],
            "same_verified_ipa_external_candidate",
        )
        self.assertEqual(
            verified_ipa_qualification["candidate_git_identity"],
            {
                "tree": pending["tree"],
                "registry_blob": pending["registry_blob"],
                "app_version": pending["app_version"],
                "app_build": pending["app_build"],
            },
        )
        with self.assertRaisesRegex(gate.GateError, "tree does not match"):
            qualification_for(
                future_registry,
                pinned_latest=19,
                candidate_tree="f" * 40,
            )
        with self.assertRaisesRegex(gate.GateError, "registry blob does not match"):
            qualification_for(
                future_registry,
                pinned_latest=19,
                candidate_registry_blob="e" * 40,
            )
        for field, value in (("version", "9.9"), ("build", "999")):
            arguments = (
                {"candidate_project_version": value}
                if field == "version"
                else {"candidate_project_build": value}
            )
            with self.subTest(candidate_project_field=field), self.assertRaisesRegex(
                gate.GateError, "version/build does not match"
            ):
                qualification_for(
                    future_registry,
                    pinned_latest=19,
                    **arguments,
                )

        historical_registry = registry()
        historical_pending = historical_registry["release_gate"][
            "pending_internal_candidate"
        ]
        self.assertEqual(
            gate.pending_upload_receipt_identifier(historical_pending),
            "xcode-distribution:0419e5e8-e865-45a2-9132-0cc43434779e",
        )
        historical_qualification = qualification_for(
            historical_registry,
            pinned_latest=18,
        )
        self.assertTrue(historical_qualification["internal_testflight_qualified"])
        self.assertFalse(historical_qualification["external_promotion_allowed"])
        self.assertEqual(
            historical_qualification["qualification_scope"],
            "internal_testflight_only_missing_local_ipa_identity",
        )
        self.assertNotEqual(
            gate.testflight_qualification_path(pending),
            gate.testflight_qualification_path(historical_pending),
        )
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.object(
            gate, "TESTFLIGHT_QUALIFICATIONS_PATH", Path(temp_dir)
        ):
            build_18_path = gate.testflight_qualification_path(historical_pending)
            build_19_path = gate.testflight_qualification_path(pending)
            gate._write_new_local_evidence(build_18_path, {"build": "18"})
            with self.assertRaisesRegex(gate.GateError, "refusing to overwrite"):
                gate._write_new_local_evidence(build_18_path, {"build": "18-retry"})
            gate._write_new_local_evidence(build_19_path, {"build": "19"})
            self.assertEqual(json.loads(build_18_path.read_text())["build"], "18")
            self.assertEqual(json.loads(build_19_path.read_text())["build"], "19")

    def test_head_bound_manual_signoffs_require_every_passed_item_and_evidence(self):
        now = dt.datetime(2026, 7, 13, 15, 0, tzinfo=dt.timezone.utc)
        app_identity = gate.project_version_identity()
        self.assertRegex(app_identity["app_version"], r"^[0-9]+(?:\.[0-9]+)*$")
        self.assertRegex(app_identity["app_build"], r"^[1-9][0-9]*$")
        if int(app_identity["app_build"]) <= gate.PINNED_LATEST_UPLOADED_BUILD:
            with self.assertRaisesRegex(gate.GateError, "never-uploaded"):
                gate.require_new_release_build(registry(), app_identity)
        else:
            self.assertEqual(
                gate.require_new_release_build(registry(), app_identity),
                app_identity,
            )
        release_identity = {**app_identity, "app_build": "19"}
        self.assertEqual(
            gate.require_new_release_build(registry(), release_identity),
            release_identity,
        )

        with tempfile.TemporaryDirectory() as project_temp_dir:
            project_file = Path(project_temp_dir) / "project.pbxproj"
            project_file.write_text(
                "MARKETING_VERSION = 1.0;\n"
                "CURRENT_PROJECT_VERSION = 17;\n"
                "MARKETING_VERSION = 1.0;\n"
                "CURRENT_PROJECT_VERSION = 17;\n",
                encoding="utf-8",
            )
            self.assertEqual(
                gate.project_version_identity(project_file),
                {"app_version": "1.0", "app_build": "17"},
            )
            with self.assertRaisesRegex(gate.GateError, "never-uploaded"):
                gate.require_new_release_build(
                    registry(), gate.project_version_identity(project_file)
                )
            project_file.write_text(
                "MARKETING_VERSION = 1.0;\nCURRENT_PROJECT_VERSION = 19;\n",
                encoding="utf-8",
            )
            self.assertEqual(
                gate.require_new_release_build(
                    registry(), gate.project_version_identity(project_file)
                )["app_build"],
                "19",
            )
            invalid_projects = (
                "MARKETING_VERSION = 1.0;\n",
                "MARKETING_VERSION = 1.beta;\nCURRENT_PROJECT_VERSION = 17;\n",
                "MARKETING_VERSION = 1.0;\nMARKETING_VERSION = 1.1;\n"
                "CURRENT_PROJECT_VERSION = 17;\n",
                "MARKETING_VERSION = 1.0;\nCURRENT_PROJECT_VERSION = 0;\n",
                "MARKETING_VERSION = 1.0;\nCURRENT_PROJECT_VERSION = 17;\n"
                "CURRENT_PROJECT_VERSION = 18;\n",
            )
            for invalid_source in invalid_projects:
                project_file.write_text(invalid_source, encoding="utf-8")
                with self.subTest(project=invalid_source), self.assertRaises(gate.GateError):
                    gate.project_version_identity(project_file)

        payload = {
            "schema_version": 1,
            "head": "a" * 40,
            "tree": "tree",
            "registry_blob": "registry",
            "completed_at": (now - dt.timedelta(minutes=5)).isoformat(),
            "items": [
                {
                    "id": signoff_id,
                    "status": "passed",
                    "tester": "Lin Reviewer",
                    **release_identity,
                    "tested_at": (now - dt.timedelta(minutes=15)).isoformat(),
                    "environment": "iPhone 17 Pro, iOS 26.3.1, XJie build 19",
                    "steps": [
                        "Open the named scenario and perform every recorded interaction.",
                        "Compare the visible result with the expected result and record it.",
                    ],
                    "evidence_reference": f"evidence/{signoff_id}.md",
                    "evidence_sha256": "a" * 64,
                }
                for signoff_id in gate.MANDATORY_RELEASE_SIGNOFFS
            ],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "release_signoffs.json"
            evidence_root = Path(temp_dir) / "evidence"
            evidence_root.mkdir()
            for item in payload["items"]:
                evidence_path = evidence_root / f"{item['id']}.md"
                evidence_path.write_text(f"redacted evidence for {item['id']}\n", encoding="utf-8")
                item["evidence_reference"] = str(evidence_path)
                item["evidence_sha256"] = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
            path.write_text(json.dumps(payload), encoding="utf-8")
            with mock.patch.object(
                gate, "SIGNOFF_EVIDENCE_ROOT", evidence_root
            ), mock.patch.object(
                gate, "project_version_identity", return_value=release_identity
            ):
                result = gate.validate_manual_signoffs(
                    registry(),
                    signoff_path=path,
                    head="a" * 40,
                    tree="tree",
                    registry_blob="registry",
                    now=now,
                )
                self.assertEqual(result["items"], list(gate.MANDATORY_RELEASE_SIGNOFFS))
                self.assertEqual(result["app_version"], release_identity["app_version"])
                self.assertEqual(result["app_build"], release_identity["app_build"])

                for mutate in (
                    lambda item: item.update(head="b" * 40),
                    lambda item: item["items"][0].update(status="pending"),
                    lambda item: item["items"][0].update(app_version="9.9"),
                    lambda item: item["items"][0].update(app_build="999999"),
                    lambda item: item["items"][0].update(evidence_reference="12345678"),
                    lambda item: item["items"][0].update(evidence_sha256="not-a-digest"),
                    lambda item: item["items"][0].update(evidence_sha256="a" * 64),
                    lambda item: item["items"][0].update(
                        evidence_reference=str(Path(temp_dir) / "missing-evidence.md")
                    ),
                    lambda item: item["items"][0].update(steps=["too short"]),
                    lambda item: item["items"].pop(),
                    lambda item: item.update(completed_at="2026-07-13T14:55:00"),
                    lambda item: item["items"][0].update(
                        tested_at=(now - dt.timedelta(hours=25)).isoformat()
                    ),
                ):
                    invalid = copy.deepcopy(payload)
                    mutate(invalid)
                    path.write_text(json.dumps(invalid), encoding="utf-8")
                    with self.assertRaises(gate.GateError):
                        gate.validate_manual_signoffs(
                            registry(),
                            signoff_path=path,
                            head="a" * 40,
                            tree="tree",
                            registry_blob="registry",
                            now=now,
                        )

                first_evidence = Path(payload["items"][0]["evidence_reference"])
                original_evidence = first_evidence.read_bytes()
                first_evidence.write_bytes(b"")
                empty_evidence = copy.deepcopy(payload)
                empty_evidence["items"][0]["evidence_sha256"] = hashlib.sha256(b"").hexdigest()
                path.write_text(json.dumps(empty_evidence), encoding="utf-8")
                with self.assertRaisesRegex(gate.GateError, "non-empty"):
                    gate.validate_manual_signoffs(
                        registry(),
                        signoff_path=path,
                        head="a" * 40,
                        tree="tree",
                        registry_blob="registry",
                        now=now,
                    )
                first_evidence.write_bytes(original_evidence)

                outside = Path(temp_dir) / "outside-evidence"
                outside.mkdir()
                outside_file = outside / "linked.md"
                outside_file.write_text("evidence outside the approved directory\n", encoding="utf-8")
                intermediate_link = evidence_root / "linked-directory"
                intermediate_link.symlink_to(outside, target_is_directory=True)
                linked_evidence = copy.deepcopy(payload)
                linked_evidence["items"][0]["evidence_reference"] = str(
                    intermediate_link / outside_file.name
                )
                linked_evidence["items"][0]["evidence_sha256"] = hashlib.sha256(
                    outside_file.read_bytes()
                ).hexdigest()
                path.write_text(json.dumps(linked_evidence), encoding="utf-8")
                with self.assertRaisesRegex(gate.GateError, "non-symlink directory"):
                    gate.validate_manual_signoffs(
                        registry(),
                        signoff_path=path,
                        head="a" * 40,
                        tree="tree",
                        registry_blob="registry",
                        now=now,
                    )

                evidence_root_link = Path(temp_dir) / "evidence-root-link"
                evidence_root_link.symlink_to(evidence_root, target_is_directory=True)
                root_linked = copy.deepcopy(payload)
                for item in root_linked["items"]:
                    item["evidence_reference"] = str(
                        evidence_root_link / Path(item["evidence_reference"]).name
                    )
                path.write_text(json.dumps(root_linked), encoding="utf-8")
                with mock.patch.object(
                    gate, "SIGNOFF_EVIDENCE_ROOT", evidence_root_link
                ), self.assertRaisesRegex(gate.GateError, "non-symlink directory"):
                    gate.validate_manual_signoffs(
                        registry(),
                        signoff_path=path,
                        head="a" * 40,
                        tree="tree",
                        registry_blob="registry",
                        now=now,
                    )


if __name__ == "__main__":
    unittest.main()
