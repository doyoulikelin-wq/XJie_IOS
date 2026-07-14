from __future__ import annotations

import copy
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).resolve().parents[1] / "regression_guard.py"
SPEC = importlib.util.spec_from_file_location("regression_guard", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
guard = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = guard
SPEC.loader.exec_module(guard)


def minimal_registry() -> dict:
    return {
        "schema_version": 1,
        "behavior_domains": [
            {
                "id": "ios_ui_interaction",
                "description": "UI",
                "source_patterns": ["Xjie/Xjie/Views/**/*.swift"],
                "test_patterns": ["Xjie/XjieUITests/**/*.swift"],
                "meaningful_test_patterns": [r"XCTAssert", r"\bfunc\s+test"],
                "verification_commands": ["ios_ui_full"],
            },
            {
                "id": "test_suite_integrity",
                "description": "Test suite integrity",
                "source_patterns": [
                    "Xjie/XjieUITests/**/*.swift",
                    "tools/tests/**/*.py",
                    "tools/regression_guard.py",
                ],
                "test_patterns": [
                    "Xjie/XjieUITests/**/*.swift",
                    "tools/tests/**/*.py",
                    "tools/regression_guard.py",
                ],
                "meaningful_test_patterns": [r"XCTAssert", r"self\.assert", r"\bassert\b"],
                "verification_commands": ["guard_unit", "diff_check"],
            }
        ],
        "conservative_overrides": [],
        "architecture_limits": [],
        "contracts": [
            {
                "id": "UX-NAV-001",
                "domains": ["ios_ui_interaction"],
                "invariant": "Navigation remains predictable.",
                "test_anchors": [],
            },
            {
                "id": "TEST-SUITE-INTEGRITY-001",
                "domains": ["test_suite_integrity"],
                "invariant": "Tests cannot be silently removed or disabled.",
                "test_anchors": [],
            }
        ],
        "commands": {command_id: "true" for command_id in guard.MANDATORY_RELEASE_COMMANDS},
        "release_gate": {
            "latest_uploaded_build": guard.PINNED_LATEST_UPLOADED_BUILD,
            "github_repository": "example/repo",
            "github_workflow": "ci.yml",
            "required_check": {
                "name": "quality-gate", "app_slug": "github-actions", "app_id": 15368
            },
            "branch_protection": {
                "strict": True,
                "enforce_admins": True,
                "allow_force_pushes": False,
                "allow_deletions": False,
            },
            "protected_branches": ["XAGE", "main"],
            "manual_signoffs": [
                {"id": signoff_id, "description": f"Required evidence for {signoff_id}."}
                for signoff_id in guard.MANDATORY_RELEASE_SIGNOFFS
            ],
            "required_commands": list(guard.MANDATORY_RELEASE_COMMANDS),
        },
    }


def valid_manifest() -> dict:
    return {
        "schema_version": 1,
        "change_id": "2026-07-13-navigation-regression",
        "change_type": "bugfix",
        "summary": "Fix navigation dismissal behavior.",
        "root_cause": "Two independent presentation states could be active at the same time.",
        "risk_hypothesis": "Other presentation entry points may use the same conflicting state pattern.",
        "impacted_domains": ["ios_ui_interaction", "test_suite_integrity"],
        "regression_contracts": ["UX-NAV-001", "TEST-SUITE-INTEGRITY-001"],
        "same_class_scan": ["Searched all sheet and full-screen presentation entry points."],
        "tests_added_or_updated": ["Xjie/XjieUITests/NavigationTests.swift"],
        "verification_plan": ["Run the focused UI test and full UI suite."],
        "manual_checks": ["Verify small screen, keyboard and dirty form states."],
        "unresolved_risks": [],
    }


def valid_record() -> dict:
    return {
        "id": "2026-07-13-navigation-regression",
        "root_cause": "Two presentation states could be active concurrently.",
        "regression_contracts": ["UX-NAV-001", "TEST-SUITE-INTEGRITY-001"],
        "same_class_scan": ["All presentation entry points."],
        "regression_tests": ["NavigationTests/testDismissal"],
        "test_evidence": ["Focused and full UI suites passed."],
    }


class RegressionGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = minimal_registry()
        self.source = "Xjie/Xjie/Views/Home/ExampleView.swift"
        self.test = "Xjie/XjieUITests/NavigationTests.swift"

    def evaluate(self, changes, manifest=None, registry=None):
        original_loader = guard.load_manifest
        original_record_loader = guard.load_latest_development_record
        guard.load_manifest = lambda: copy.deepcopy(manifest or valid_manifest())
        guard.load_latest_development_record = lambda: copy.deepcopy(valid_record())
        try:
            return guard.evaluate_changes(changes, registry or self.registry)
        finally:
            guard.load_manifest = original_loader
            guard.load_latest_development_record = original_record_loader

    def test_docs_only_change_passes_without_manifest(self):
        changes = guard.ChangeSet(("docs/README.md",), {"docs/README.md": ("new text",)})
        errors, summary = self.evaluate(changes)
        self.assertEqual(errors, [])
        self.assertEqual(summary["primary_domains"], [])

    def test_test_only_change_is_primary_and_requires_manifest_and_record(self):
        changes = guard.ChangeSet(
            (self.test,),
            {self.test: ('XCTAssertTrue(app.buttons["Save"].exists)',)},
        )
        errors, summary = self.evaluate(changes)
        message = "\n".join(errors)
        self.assertIn("quality/change_impact.json", message)
        self.assertIn("development_records.json", message)
        self.assertEqual(
            summary["primary_domains"],
            ["ios_ui_interaction", "test_suite_integrity"],
        )
        self.assertEqual(
            summary["verification_domains"],
            ["ios_ui_interaction", "test_suite_integrity"],
        )
        self.assertEqual(
            summary["test_files"],
            {
                "ios_ui_interaction": [self.test],
                "test_suite_integrity": [self.test],
            },
        )

    def test_manifest_contracts_must_cover_every_primary_domain(self):
        changes = guard.ChangeSet(
            (
                self.source,
                self.test,
                guard.MANIFEST_REPO_PATH,
                guard.DEVELOPMENT_RECORDS_REPO_PATH,
            ),
            {
                self.source: ('Text("changed")',),
                self.test: ('XCTAssertTrue(app.buttons["Save"].exists)',),
                guard.MANIFEST_REPO_PATH: ("updated",),
                guard.DEVELOPMENT_RECORDS_REPO_PATH: ("updated",),
            },
        )
        manifest = valid_manifest()
        manifest["regression_contracts"] = ["UX-NAV-001"]
        errors, _ = self.evaluate(changes, manifest)
        self.assertTrue(any("do not cover primary domains" in item for item in errors))

    def test_backend_and_tool_tests_map_to_every_corresponding_gate(self):
        registry = guard.load_registry()
        backend_test = "backend/tests/unit/test_chat_routing.py"
        tool_test = "tools/tests/test_python_test_gate.py"
        primary, verification = guard.classify_changes((backend_test, tool_test), registry)
        self.assertEqual(
            sorted(primary),
            ["backend_chat_ai", "backend_core", "quality_process_gate", "test_suite_integrity"],
        )
        self.assertEqual(
            sorted(verification),
            ["backend_chat_ai", "backend_core", "quality_process_gate", "test_suite_integrity"],
        )
        self.assertEqual(
            primary["backend_core"],
            [backend_test],
        )

        deployment_paths = (
            "docker-compose.yml",
            "backend/Dockerfile",
            "backend/.dockerignore",
            "backend/.env.example",
            "backend/alembic.ini",
            "backend/static/index.html",
            "backend/deploy/nginx/xjie-api-exact-locations.conf",
            "backend/app/static/admin.html",
            "backend/app/workers/literature_seeds.json",
            "scripts/deploy_literature.sh",
            "tools/xjie_dashboard_api.py",
            "backend/app/db/migrations/versions/0022_future.py",
        )
        deployment_primary, deployment_verification = guard.classify_changes(
            deployment_paths, registry
        )
        self.assertEqual(
            deployment_primary["backend_core"],
            list(deployment_paths[:-1]),
        )
        self.assertEqual(
            deployment_primary["backend_health_sync"],
            [deployment_paths[-1]],
        )
        self.assertEqual(
            deployment_verification,
            {"backend_core", "backend_health_sync"},
        )
        domains = {domain["id"]: domain for domain in registry["behavior_domains"]}
        for domain_id in deployment_verification:
            self.assertTrue(
                {"backend_full", "guard_unit", "diff_check"}.issubset(
                    domains[domain_id]["verification_commands"]
                )
            )

        process_primary, process_verification = guard.classify_changes(
            ("tools/generate_development_history.py",), registry
        )
        self.assertEqual(process_primary, {"quality_process_gate": ["tools/generate_development_history.py"]})
        self.assertEqual(process_verification, {"quality_process_gate"})

        history_primary, history_verification = guard.classify_changes(
            ("development_history.html",), registry
        )
        self.assertEqual(history_primary, {})
        self.assertEqual(history_verification, set())

    def test_test_only_assertion_deletion_or_constant_replacement_requires_manifest_and_meaningful_test(self):
        cases = (
            (self.test, ()),
            (self.test, ("XCTAssertEqual(1, 1)",)),
            (self.test, ('try XCTSkip("temporary")',)),
            ("tools/tests/test_disabled.py", ("__test__ = False",)),
        )
        for test_path, added_lines in cases:
            manifest = valid_manifest()
            manifest["tests_added_or_updated"] = [test_path]
            changes = guard.ChangeSet(
                (
                    test_path,
                    guard.MANIFEST_REPO_PATH,
                    guard.DEVELOPMENT_RECORDS_REPO_PATH,
                ),
                {
                    test_path: added_lines,
                    guard.MANIFEST_REPO_PATH: ("updated",),
                    guard.DEVELOPMENT_RECORDS_REPO_PATH: ("updated",),
                },
            )
            with self.subTest(test_path=test_path, added_lines=added_lines):
                errors, summary = self.evaluate(changes, manifest)
                self.assertIn("test_suite_integrity", summary["primary_domains"])
                self.assertTrue(
                    any(
                        "domain test_suite_integrity requires a meaningful regression test"
                        in error
                        for error in errors
                    )
                )

    def test_unmapped_test_or_support_file_fails_closed(self):
        path = "experiments/test_new_behavior.py"
        changes = guard.ChangeSet((path,), {path: ("def test_new_behavior():", "    assert True")})
        errors, summary = self.evaluate(changes)
        self.assertTrue(any("test/support files are not mapped" in item for item in errors))
        self.assertEqual(summary["primary_domains"], [])

    def test_behavior_change_without_manifest_or_test_fails(self):
        changes = guard.ChangeSet((self.source,), {self.source: ("Button(\"Save\") {}",)})
        manifest = valid_manifest()
        errors, _ = self.evaluate(changes, manifest)
        message = "\n".join(errors)
        self.assertIn("quality/change_impact.json", message)
        self.assertIn("meaningful regression test", message)

    def test_behavior_change_with_manifest_and_meaningful_test_passes(self):
        changes = guard.ChangeSet(
            (self.source, self.test, guard.MANIFEST_REPO_PATH, guard.DEVELOPMENT_RECORDS_REPO_PATH),
            {
                self.source: ("Button(\"Save\") {}",),
                self.test: ("XCTAssertTrue(app.buttons[\"Save\"].waitForExistence(timeout: 2))",),
                guard.MANIFEST_REPO_PATH: ("updated",),
                guard.DEVELOPMENT_RECORDS_REPO_PATH: ("updated",),
            },
        )
        errors, summary = self.evaluate(changes, valid_manifest())
        self.assertEqual(errors, [])
        self.assertEqual(
            summary["primary_domains"],
            ["ios_ui_interaction", "test_suite_integrity"],
        )

    def test_declared_test_must_be_part_of_change(self):
        changes = guard.ChangeSet(
            (self.source, guard.MANIFEST_REPO_PATH),
            {self.source: ("Text(\"Changed\")",), guard.MANIFEST_REPO_PATH: ("updated",)},
        )
        errors, _ = self.evaluate(changes, valid_manifest())
        self.assertTrue(any("declared regression tests were not changed" in item for item in errors))

    def test_unmapped_production_file_fails(self):
        registry = minimal_registry()
        registry["behavior_domains"][0]["source_patterns"] = ["Xjie/Xjie/Views/Home/*.swift"]
        changes = guard.ChangeSet(
            ("Xjie/Xjie/ViewModels/NewBehavior.swift",),
            {"Xjie/Xjie/ViewModels/NewBehavior.swift": ("final class NewBehavior {}",)},
        )
        original_loader = guard.load_manifest
        guard.load_manifest = valid_manifest
        try:
            errors, _ = guard.evaluate_changes(changes, registry)
        finally:
            guard.load_manifest = original_loader
        self.assertTrue(any("not mapped" in item for item in errors))

    def test_gate_or_workflow_weakening_is_behavior_change_and_needs_guard_test(self):
        registry = minimal_registry()
        registry["behavior_domains"].append(
            {
                "id": "quality_process_gate",
                "description": "Process gate",
                "source_patterns": ["tools/regression_guard.py", ".github/workflows/*.yml"],
                "test_patterns": ["tools/tests/test_*.py"],
                "meaningful_test_patterns": [r"self\.assert", r"\bdef\s+test_"],
                "verification_commands": ["guard_unit", "diff_check"],
            }
        )
        registry["contracts"].append(
            {
                "id": "PROCESS-GATE-001",
                "domains": ["quality_process_gate"],
                "invariant": "The process gate cannot be silently weakened.",
                "test_anchors": [],
            }
        )
        changes = guard.ChangeSet(
            ("tools/regression_guard.py",),
            {"tools/regression_guard.py": ("return []",)},
        )
        errors, summary = self.evaluate(changes, valid_manifest(), registry)
        message = "\n".join(errors)
        self.assertEqual(
            summary["primary_domains"],
            ["quality_process_gate", "test_suite_integrity"],
        )
        self.assertIn("quality/change_impact.json", message)
        self.assertIn("meaningful regression test", message)

    def test_deleted_production_file_still_requires_manifest_and_regression_test(self):
        changes = guard.ChangeSet((self.source,), {})
        errors, summary = self.evaluate(changes, valid_manifest())
        message = "\n".join(errors)
        self.assertEqual(
            summary["primary_domains"],
            ["ios_ui_interaction"],
        )
        self.assertIn("quality/change_impact.json", message)
        self.assertIn("meaningful regression test", message)

    def test_trivial_assertion_cannot_satisfy_regression_requirement(self):
        changes = guard.ChangeSet(
            (self.source, self.test, guard.MANIFEST_REPO_PATH, guard.DEVELOPMENT_RECORDS_REPO_PATH),
            {
                self.source: ("Button(\"Save\") {}",),
                self.test: ("func testFakeCoverage() {}", "XCTAssertTrue(true)"),
                guard.MANIFEST_REPO_PATH: ("updated",),
                guard.DEVELOPMENT_RECORDS_REPO_PATH: ("updated",),
            },
        )
        errors, _ = self.evaluate(changes, valid_manifest())
        self.assertTrue(any("meaningful regression test" in item for item in errors))

    def test_constant_equality_and_standalone_interaction_are_not_meaningful_tests(self):
        ios_domain = self.registry["behavior_domains"][0]
        for line in (
            "XCTAssertEqual(1, 1)",
            'XCTAssertTrue("same" == "same")',
            'app.buttons["Save"].tap()',
            'app.swipeUp()',
        ):
            with self.subTest(line=line):
                meaningful, _ = guard._meaningful_test_change(
                    ios_domain,
                    guard.ChangeSet((self.test,), {self.test: (line,)}),
                )
                self.assertFalse(meaningful)

        python_domain = {
            "test_patterns": ["tools/tests/**/*.py"],
            "meaningful_test_patterns": [r"self\.assert", r"\bassert\b"],
        }
        python_test = "tools/tests/test_example.py"
        for line in ("self.assertEqual(1, 1)", "assert 1 + 1 == 2"):
            with self.subTest(line=line):
                meaningful, _ = guard._meaningful_test_change(
                    python_domain,
                    guard.ChangeSet((python_test,), {python_test: (line,)}),
                )
                self.assertFalse(meaningful)

        meaningful, _ = guard._meaningful_test_change(
            ios_domain,
            guard.ChangeSet(
                (self.test,),
                {self.test: ('XCTAssertEqual(app.staticTexts["Status"].label, "Ready")',)},
            ),
        )
        self.assertTrue(meaningful)

    def test_change_collection_includes_deletes_and_disables_rename_hiding(self):
        paths = guard._parse_name_status(
            "D\0Xjie/Xjie/Views/Deleted.swift\0"
            "R100\0Xjie/Xjie/Views/Old Name.swift\0docs/New Name.swift\0"
        )
        self.assertEqual(
            paths,
            [
                "Xjie/Xjie/Views/Deleted.swift",
                "Xjie/Xjie/Views/Old Name.swift",
                "docs/New Name.swift",
            ],
        )

    def test_malformed_name_status_fails_closed(self):
        with self.assertRaises(guard.GuardError):
            guard._parse_name_status("R100\0only-old-path.swift\0")

    def test_missing_explicit_base_fails_instead_of_falling_back_to_parent(self):
        missing = subprocess.CompletedProcess(["git"], returncode=1)
        with mock.patch.object(guard.subprocess, "run", return_value=missing), mock.patch.object(
            guard, "_git"
        ) as fallback:
            with self.assertRaisesRegex(guard.GuardError, "not a local commit"):
                guard._existing_commit_or_parent("deadbeef", "HEAD")
        fallback.assert_not_called()

        with mock.patch.object(guard, "_git", return_value="parent-sha\n") as fallback:
            self.assertEqual(
                guard._existing_commit_or_parent("0" * 40, "candidate-sha"),
                "parent-sha",
            )
        fallback.assert_called_once_with("rev-parse", "candidate-sha^")

    def test_python_test_inventory_cannot_delete_or_rename_existing_id_at_same_count(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Regression Guard"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "guard@example.com"], cwd=repo, check=True)
            test_path = repo / "backend" / "tests" / "unit" / "test_contract.py"
            test_path.parent.mkdir(parents=True)
            test_path.write_text("def test_required_contract():\n    assert behavior()\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "baseline"], cwd=repo, check=True)
            base = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=repo, check=True,
                stdout=subprocess.PIPE, text=True,
            ).stdout.strip()

            test_path.write_text("def test_replacement_contract():\n    assert behavior()\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "replace test at same count"], cwd=repo, check=True)
            head = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=repo, check=True,
                stdout=subprocess.PIPE, text=True,
            ).stdout.strip()

            original_root = guard.REPO_ROOT
            guard.REPO_ROOT = repo
            try:
                with self.assertRaisesRegex(guard.GuardError, "removed or renamed"):
                    guard.validate_python_test_inventory_range(base, head)
            finally:
                guard.REPO_ROOT = original_root

    def test_tracked_python_runtime_inventory_rejects_parameterization_shrink(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Regression Guard"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "guard@example.com"], cwd=repo, check=True)
            test_path = repo / "backend" / "tests" / "unit" / "test_matrix.py"
            test_path.parent.mkdir(parents=True)
            test_path.write_text("def test_matrix(case):\n    assert case\n", encoding="utf-8")
            inventory_path = repo / "quality" / "expected_python_tests.json"
            inventory_path.parent.mkdir(parents=True)

            def payload(backend_tests: list[str]) -> dict:
                return {
                    "schema_version": 1,
                    "backend_full": sorted(backend_tests),
                    "tools": ["test_guard.GuardTests.test_policy"],
                }

            first = "tests.unit.test_matrix::test_matrix[first]"
            second = "tests.unit.test_matrix::test_matrix[second]"
            inventory_path.write_text(
                json.dumps(payload([first, second])), encoding="utf-8"
            )
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "baseline"], cwd=repo, check=True)
            base = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=repo, check=True,
                stdout=subprocess.PIPE, text=True,
            ).stdout.strip()

            inventory_path.write_text(json.dumps(payload([first])), encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "shrink parameter matrix"], cwd=repo, check=True)
            head = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=repo, check=True,
                stdout=subprocess.PIPE, text=True,
            ).stdout.strip()

            original_root = guard.REPO_ROOT
            original_inventory_path = guard.EXPECTED_PYTHON_TESTS_PATH
            guard.REPO_ROOT = repo
            guard.EXPECTED_PYTHON_TESTS_PATH = inventory_path
            try:
                with self.assertRaisesRegex(guard.GuardError, "parameterization-shrunk"):
                    guard.validate_python_test_inventory_range(base, head)
            finally:
                guard.REPO_ROOT = original_root
                guard.EXPECTED_PYTHON_TESTS_PATH = original_inventory_path

    def test_xctest_inventory_cannot_shrink_with_manifest(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Regression Guard"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "guard@example.com"], cwd=repo, check=True)
            inventory_path = repo / "quality" / "expected_xctests.json"
            inventory_path.parent.mkdir(parents=True)

            def payload(unit_tests: list[str]) -> dict:
                ui = ["XjieUITests/FlowTests/testFlow"]
                return {
                    "schema_version": 1,
                    "profiles": {
                        "ios_unit": sorted(unit_tests),
                        "ios_ui_full": ui,
                        "ios_ui_small": ui,
                        "ios_all": sorted(unit_tests + ui),
                    },
                }

            original = [
                "XjieTests/ExampleTests/testOne",
                "XjieTests/ExampleTests/testTwo",
            ]
            inventory_path.write_text(json.dumps(payload(original)), encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "baseline"], cwd=repo, check=True)
            base = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=repo, check=True,
                stdout=subprocess.PIPE, text=True,
            ).stdout.strip()

            inventory_path.write_text(
                json.dumps(payload([original[1]])),
                encoding="utf-8",
            )
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "shrink XCTest inventory"], cwd=repo, check=True)
            head = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=repo, check=True,
                stdout=subprocess.PIPE, text=True,
            ).stdout.strip()

            original_root = guard.REPO_ROOT
            original_inventory_path = guard.EXPECTED_XCTESTS_PATH
            guard.REPO_ROOT = repo
            guard.EXPECTED_XCTESTS_PATH = inventory_path
            try:
                with self.assertRaisesRegex(guard.GuardError, "XCTest inventory must be monotonic"):
                    guard.validate_xctest_inventory_range(base, head)
            finally:
                guard.REPO_ROOT = original_root
                guard.EXPECTED_XCTESTS_PATH = original_inventory_path

    def test_rename_out_of_production_keeps_old_domain_classification(self):
        changes = guard.ChangeSet(
            (
                self.source,
                "docs/ArchivedView.swift",
                self.test,
                guard.MANIFEST_REPO_PATH,
                guard.DEVELOPMENT_RECORDS_REPO_PATH,
            ),
            {
                self.test: ("XCTAssertTrue(app.buttons[\"Save\"].exists)",),
                guard.MANIFEST_REPO_PATH: ("updated",),
                guard.DEVELOPMENT_RECORDS_REPO_PATH: ("updated",),
            },
        )
        errors, summary = self.evaluate(changes, valid_manifest())
        self.assertEqual(errors, [])
        self.assertEqual(
            summary["primary_domains"],
            ["ios_ui_interaction", "test_suite_integrity"],
        )

    def test_staged_unchanged_rename_or_copy_cannot_fake_new_test_assertions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Regression Guard"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "guard@example.com"], cwd=repo, check=True)

            tests = repo / "Xjie" / "XjieUITests"
            source = repo / "Xjie" / "Xjie" / "Views" / "Home" / "ExampleView.swift"
            tests.mkdir(parents=True)
            source.parent.mkdir(parents=True)
            old_test = tests / "OldTests.swift"
            copy_source = tests / "ExistingTests.swift"
            old_test.write_text("func helper() { XCTAssertTrue(app.buttons[\"Save\"].exists) }\n")
            copy_source.write_text("func helper2() { XCTAssertFalse(app.alerts.firstMatch.exists) }\n")
            source.write_text("Text(\"Before\")\n")
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "baseline"], cwd=repo, check=True)

            subprocess.run(
                ["git", "mv", str(old_test.relative_to(repo)), str(tests.joinpath("RenamedTests.swift").relative_to(repo))],
                cwd=repo,
                check=True,
            )
            shutil.copy2(copy_source, tests / "CopiedTests.swift")
            source.write_text("Text(\"After\")\n")
            subprocess.run(["git", "add", "-A"], cwd=repo, check=True)

            original_root = guard.REPO_ROOT
            guard.REPO_ROOT = repo
            try:
                changes = guard.collect_changes(staged=True)
            finally:
                guard.REPO_ROOT = original_root

            self.assertIn("Xjie/XjieUITests/OldTests.swift", changes.paths)
            self.assertIn("Xjie/XjieUITests/RenamedTests.swift", changes.paths)
            self.assertIn("Xjie/XjieUITests/CopiedTests.swift", changes.paths)
            self.assertEqual(changes.added_lines.get("Xjie/XjieUITests/RenamedTests.swift", ()), ())
            self.assertEqual(changes.added_lines.get("Xjie/XjieUITests/CopiedTests.swift", ()), ())

    def test_real_registry_rejects_process_identity_and_command_weakening(self):
        registry = guard.load_registry()
        self.assertEqual(guard.validate_registry(registry), [])

        mutations = (
            lambda item: item["behavior_domains"].__setitem__(
                slice(None),
                [domain for domain in item["behavior_domains"] if domain["id"] != "quality_process_gate"],
            ),
            lambda item: next(
                domain for domain in item["behavior_domains"] if domain["id"] == "quality_process_gate"
            )["source_patterns"].remove("tools/validate_xcresult.py"),
            lambda item: next(
                domain for domain in item["behavior_domains"] if domain["id"] == "quality_process_gate"
            )["source_patterns"].remove("tools/generate_development_history.py"),
            lambda item: next(
                contract for contract in item["contracts"] if contract["id"] == "PROCESS-GATE-001"
            ).update(domains=[]),
            lambda item: item["release_gate"].update(github_repository="fork/XJie_IOS"),
            lambda item: item["release_gate"].update(latest_uploaded_build=16),
            lambda item: item["release_gate"].update(branch_protection={"strict": True}),
            lambda item: item["commands"].update(diff_check="true"),
            lambda item: item["commands"].update(
                backend_ai=item["commands"]["backend_ai"].replace(
                    " backend/tests/unit/test_chat_evidence.py", ""
                )
            ),
            lambda item: next(
                domain for domain in item["behavior_domains"] if domain["id"] == "ios_core"
            )["verification_commands"].remove("ios_release_build"),
            lambda item: next(
                domain
                for domain in item["behavior_domains"]
                if domain["id"] == "quality_process_gate"
            )["verification_commands"].remove("ios_release_build"),
            lambda item: next(
                domain
                for domain in item["behavior_domains"]
                if domain["id"] == "test_suite_integrity"
            )["verification_commands"].remove("ios_release_build"),
            lambda item: next(
                domain for domain in item["behavior_domains"] if domain["id"] == "backend_core"
            )["source_patterns"].remove("backend/Dockerfile"),
            lambda item: next(
                domain for domain in item["behavior_domains"] if domain["id"] == "backend_core"
            )["verification_commands"].remove("guard_unit"),
            lambda item: next(
                domain
                for domain in item["behavior_domains"]
                if domain["id"] == "backend_health_sync"
            )["verification_commands"].remove("backend_full"),
        )
        for mutate in mutations:
            weakened = copy.deepcopy(registry)
            mutate(weakened)
            with self.subTest(mutation=mutate):
                self.assertTrue(guard.validate_registry(weakened))

        app_identity = guard.project_version_identity()
        self.assertRegex(app_identity["app_version"], r"^[0-9]+(?:\.[0-9]+)*$")
        self.assertRegex(app_identity["app_build"], r"^[1-9][0-9]*$")
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            project_file = temp_root / "project.pbxproj"
            for invalid_source in (
                "MARKETING_VERSION = variable;\nCURRENT_PROJECT_VERSION = 17;\n",
                "MARKETING_VERSION = 1.0;\nMARKETING_VERSION = 2.0;\n"
                "CURRENT_PROJECT_VERSION = 17;\n",
                "MARKETING_VERSION = 1.0;\nCURRENT_PROJECT_VERSION = 17;\n"
                "CURRENT_PROJECT_VERSION = 18;\n",
            ):
                project_file.write_text(invalid_source, encoding="utf-8")
                with self.subTest(project=invalid_source), self.assertRaises(guard.GuardError):
                    guard.project_version_identity(project_file)

            template = json.loads(guard.SIGNOFF_TEMPLATE_PATH.read_text(encoding="utf-8"))
            template_path = temp_root / "release_signoffs.example.json"
            for field in ("app_version", "app_build"):
                tampered_template = copy.deepcopy(template)
                tampered_template["items"][0][field] = ""
                template_path.write_text(json.dumps(tampered_template), encoding="utf-8")
                with self.subTest(template_field=field), mock.patch.object(
                    guard, "SIGNOFF_TEMPLATE_PATH", template_path
                ):
                    self.assertTrue(
                        any(
                            "release signoff template must remain pending" in error
                            for error in guard.validate_registry(registry)
                        )
                    )

    def test_registry_validation_rejects_unmapped_test_inventory(self):
        registry = copy.deepcopy(guard.load_registry())
        process_domain = next(
            domain
            for domain in registry["behavior_domains"]
            if domain["id"] == "quality_process_gate"
        )
        process_domain["test_patterns"] = ["tools/tests/test_*.py"]
        integrity_domain = next(
            domain
            for domain in registry["behavior_domains"]
            if domain["id"] == "test_suite_integrity"
        )
        integrity_domain["test_patterns"] = ["backend/tests/**/*.py"]
        path = "tools/tests/helpers.py"
        with mock.patch.object(
            guard,
            "_repository_test_support_paths",
            return_value=[path],
        ):
            errors = guard.validate_registry(registry)
        self.assertIn(
            f"test/support file is not mapped to a regression domain: {path}",
            errors,
        )


if __name__ == "__main__":
    unittest.main()
