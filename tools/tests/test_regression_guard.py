from __future__ import annotations

import copy
import importlib.util
import sys
import unittest
from pathlib import Path


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
            }
        ],
        "commands": {"ios_ui_full": "true"},
        "release_gate": {"required_commands": ["ios_ui_full"]},
    }


def valid_manifest() -> dict:
    return {
        "schema_version": 1,
        "change_id": "2026-07-13-navigation-regression",
        "change_type": "bugfix",
        "summary": "Fix navigation dismissal behavior.",
        "root_cause": "Two independent presentation states could be active at the same time.",
        "risk_hypothesis": "Other presentation entry points may use the same conflicting state pattern.",
        "impacted_domains": ["ios_ui_interaction"],
        "regression_contracts": ["UX-NAV-001"],
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
        "regression_contracts": ["UX-NAV-001"],
        "same_class_scan": ["All presentation entry points."],
        "regression_tests": ["NavigationTests/testDismissal"],
        "test_evidence": ["Focused and full UI suites passed."],
    }


class RegressionGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = minimal_registry()
        self.source = "Xjie/Xjie/Views/Home/ExampleView.swift"
        self.test = "Xjie/XjieUITests/NavigationTests.swift"

    def evaluate(self, changes, manifest=None):
        original_loader = guard.load_manifest
        original_record_loader = guard.load_latest_development_record
        guard.load_manifest = lambda: copy.deepcopy(manifest or valid_manifest())
        guard.load_latest_development_record = lambda: copy.deepcopy(valid_record())
        try:
            return guard.evaluate_changes(changes, self.registry)
        finally:
            guard.load_manifest = original_loader
            guard.load_latest_development_record = original_record_loader

    def test_docs_only_change_passes_without_manifest(self):
        changes = guard.ChangeSet(("docs/README.md",), {"docs/README.md": ("new text",)})
        errors, summary = self.evaluate(changes)
        self.assertEqual(errors, [])
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
        self.assertEqual(summary["primary_domains"], ["ios_ui_interaction"])

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


if __name__ == "__main__":
    unittest.main()
