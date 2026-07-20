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
        "schema_version": 3,
        "behavior_domains": [
            {
                "id": "ios_ui_interaction",
                "description": "UI",
                "source_patterns": ["Xjie/Xjie/Views/**/*.swift"],
                "test_patterns": ["Xjie/XjieUITests/**/*.swift"],
                "meaningful_test_patterns": [r"XCTAssert", r"\bfunc\s+test"],
                "verification_commands": ["ios_ui_full"],
                "required_contract_ids": ["UX-NAV-001"],
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
                "required_contract_ids": ["TEST-SUITE-INTEGRITY-001"],
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
            "branch_roles": copy.deepcopy(guard.PINNED_BRANCH_ROLES),
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

        historical_paths = (
            "backend/app/routers/chat.py",
            "backend/app/routers/health_data.py",
            "backend/tests/unit/test_chat_routing.py",
            "backend/tests/unit/test_device_indicator_sync.py",
            "tools/regression_guard.py",
            "tools/tests/test_regression_guard.py",
            guard.MANIFEST_REPO_PATH,
            guard.DEVELOPMENT_RECORDS_REPO_PATH,
        )
        historical_changes = guard.ChangeSet(
            historical_paths,
            {
                "backend/app/routers/chat.py": ("changed_chat_route = True",),
                "backend/app/routers/health_data.py": ("changed_health_route = True",),
                "backend/tests/unit/test_chat_routing.py": (
                    "def test_historical_chat_behavior():",
                    "    assert result.route_id == expected_route_id",
                ),
                "backend/tests/unit/test_device_indicator_sync.py": (
                    "def test_historical_health_behavior():",
                    "    assert stored.source_id == request.source_id",
                ),
                "tools/regression_guard.py": ("changed_guard = True",),
                "tools/tests/test_regression_guard.py": (
                    "self.assertIn('backend_core', primary_domains)",
                ),
                guard.MANIFEST_REPO_PATH: ("updated",),
                guard.DEVELOPMENT_RECORDS_REPO_PATH: ("updated",),
            },
        )
        registry = guard.load_registry()
        _, verification = guard.classify_changes(historical_paths, registry)
        historical_manifest = valid_manifest()
        historical_manifest["impacted_domains"] = [
            "quality_process_gate",
            "test_suite_integrity",
        ]
        historical_manifest["regression_contracts"] = [
            "PROCESS-GATE-001",
            "TEST-SUITE-INTEGRITY-001",
        ]
        historical_manifest["tests_added_or_updated"] = [
            "backend/tests/unit/test_chat_routing.py",
            "backend/tests/unit/test_device_indicator_sync.py",
            "tools/tests/test_regression_guard.py",
        ]
        errors, _ = self.evaluate(historical_changes, historical_manifest, registry)
        self.assertIn(
            "change_impact.json is missing impacted domains: "
            "backend_chat_ai, backend_core, backend_health_sync",
            errors,
        )
        self.assertIn(
            "change_impact.json regression_contracts do not cover primary domains: "
            "backend_chat_ai, backend_core, backend_health_sync",
            errors,
        )

        historical_manifest["impacted_domains"] = sorted(verification)
        required_without_backend_core = sorted(
            {
                contract_id
                for domain_id in verification
                if domain_id != "backend_core"
                for contract_id in next(
                    domain
                    for domain in registry["behavior_domains"]
                    if domain["id"] == domain_id
                )["required_contract_ids"]
            }
        )
        historical_manifest["regression_contracts"] = required_without_backend_core
        errors, _ = self.evaluate(historical_changes, historical_manifest, registry)
        self.assertEqual(
            errors,
            [
                "change_impact.json regression_contracts are missing required contracts for "
                "primary domains: BACKEND-CORE-001",
                "change_impact.json regression_contracts do not cover primary domains: "
                "backend_core"
            ],
        )

        historical_manifest["regression_contracts"].append("BACKEND-CORE-001")
        errors, _ = self.evaluate(historical_changes, historical_manifest, registry)
        self.assertEqual(errors, [])

        historical_manifest["regression_contracts"].remove("BRANCH-CANONICAL-001")
        errors, _ = self.evaluate(historical_changes, historical_manifest, registry)
        self.assertEqual(
            errors,
            [
                "change_impact.json regression_contracts are missing required contracts for "
                "primary domains: BRANCH-CANONICAL-001"
            ],
        )
        historical_manifest["regression_contracts"].append("BRANCH-CANONICAL-001")

        historical_manifest["regression_contracts"].remove("AI-SAFETY-001")
        errors, _ = self.evaluate(historical_changes, historical_manifest, registry)
        self.assertEqual(
            errors,
            [
                "change_impact.json regression_contracts are missing required contracts for "
                "primary domains: AI-SAFETY-001"
            ],
        )

        future_domain_registry = copy.deepcopy(registry)
        future_domain = copy.deepcopy(
            next(
                domain
                for domain in future_domain_registry["behavior_domains"]
                if domain["id"] == "ios_core"
            )
        )
        future_domain["id"] = "future_sensitive_domain"
        future_domain["required_contract_ids"] = ["PROCESS-GATE-001"]
        future_domain_registry["behavior_domains"].append(future_domain)
        next(
            contract
            for contract in future_domain_registry["contracts"]
            if contract["id"] == "PROCESS-GATE-001"
        )["domains"].append("future_sensitive_domain")
        future_errors = guard.validate_registry(future_domain_registry)
        self.assertIn(
            "domain future_sensitive_domain is not present in the pinned required-contract mapping",
            future_errors,
        )
        self.assertIn(
            "behavior domain ids must match the pinned required-contract mapping: "
            "unexpected future_sensitive_domain",
            future_errors,
        )
        self.assertIn(
            "contract PROCESS-GATE-001 domains changed from the pinned required-contract "
            "reverse mapping",
            future_errors,
        )

        def swap_contract_definitions(item):
            safety_contract = next(
                contract
                for contract in item["contracts"]
                if contract["id"] == "AI-SAFETY-001"
            )
            navigation_contract = next(
                contract
                for contract in item["contracts"]
                if contract["id"] == "UX-NAV-001"
            )
            safety_definition = (
                safety_contract["invariant"],
                safety_contract["test_anchors"],
            )
            safety_contract["invariant"] = navigation_contract["invariant"]
            safety_contract["test_anchors"] = navigation_contract["test_anchors"]
            navigation_contract["invariant"] = safety_definition[0]
            navigation_contract["test_anchors"] = safety_definition[1]

        for name, mutate, expected_error in (
            (
                "empty required ids",
                lambda item: next(
                    domain
                    for domain in item["behavior_domains"]
                    if domain["id"] == "ios_account_client"
                ).update(required_contract_ids=[]),
                "domain ios_account_client requires non-empty required_contract_ids",
            ),
            (
                "duplicate required id",
                lambda item: next(
                    domain
                    for domain in item["behavior_domains"]
                    if domain["id"] == "ios_core"
                ).update(
                    required_contract_ids=[
                        "TEST-DETERMINISM-001",
                        "TEST-DETERMINISM-001",
                    ]
                ),
                "domain ios_core required_contract_ids must be unique",
            ),
            (
                "pinned order",
                lambda item: next(
                    domain
                    for domain in item["behavior_domains"]
                    if domain["id"] == "ios_ui_interaction"
                )["required_contract_ids"].reverse(),
                "domain ios_ui_interaction required_contract_ids changed from the pinned mapping",
            ),
            (
                "reverse domain attachment",
                lambda item: next(
                    contract
                    for contract in item["contracts"]
                    if contract["id"] == "UX-FORM-001"
                )["domains"].remove("ios_account_client"),
                "contract UX-FORM-001 domains changed from the pinned required-contract "
                "reverse mapping",
            ),
            (
                "orphan contract",
                lambda item: item["contracts"].append(
                    {
                        "id": "BLANKET-BYPASS-001",
                        "domains": ["ios_core"],
                        "invariant": "An unrelated blanket contract must not become a bypass.",
                        "test_anchors": [
                            {
                                "path": "tools/tests/test_regression_guard.py",
                                "symbol": "test_manifest_contracts_must_cover_every_primary_domain",
                            }
                        ],
                    }
                ),
                "regression contract ids must match the pinned domain mapping: "
                "unexpected BLANKET-BYPASS-001",
            ),
            (
                "generic substring anchor",
                lambda item: next(
                    contract
                    for contract in item["contracts"]
                    if contract["id"] == "AI-SAFETY-001"
                ).update(
                    invariant="x",
                    test_anchors=[
                        {
                            "path": "tools/tests/test_regression_guard.py",
                            "symbol": "test_",
                        }
                    ],
                ),
                "contract AI-SAFETY-001 invariant/anchor definition changed from the pinned "
                "digest",
            ),
            (
                "cross-contract definition swap",
                swap_contract_definitions,
                "contract AI-SAFETY-001 invariant/anchor definition changed from the pinned "
                "digest",
            ),
            (
                "remove conservative overrides",
                lambda item: item["conservative_overrides"].clear(),
                "regression_contracts.json normalized definition changed from the pinned digest",
            ),
            (
                "shrink UI verification commands",
                lambda item: next(
                    domain
                    for domain in item["behavior_domains"]
                    if domain["id"] == "ios_ui_interaction"
                ).update(verification_commands=["ios_release_build"]),
                "regression_contracts.json normalized definition changed from the pinned digest",
            ),
            (
                "hide chat source paths",
                lambda item: next(
                    domain
                    for domain in item["behavior_domains"]
                    if domain["id"] == "ios_chat_client"
                ).update(source_patterns=["Xjie/Never/**/*.swift"]),
                "regression_contracts.json normalized definition changed from the pinned digest",
            ),
            (
                "accept every test line",
                lambda item: next(
                    domain
                    for domain in item["behavior_domains"]
                    if domain["id"] == "ios_core"
                ).update(meaningful_test_patterns=[".*"]),
                "regression_contracts.json normalized definition changed from the pinned digest",
            ),
            (
                "remove architecture limits",
                lambda item: item["architecture_limits"].clear(),
                "regression_contracts.json normalized definition changed from the pinned digest",
            ),
        ):
            weakened_registry = copy.deepcopy(registry)
            mutate(weakened_registry)
            with self.subTest(required_contract_mapping=name):
                self.assertIn(expected_error, guard.validate_registry(weakened_registry))

    def test_medication_trust_contract_pins_domains_definition_and_focused_suites(self):
        registry = guard.load_registry()
        medication_contract = next(
            contract
            for contract in registry["contracts"]
            if contract["id"] == "MEDICATION-TRUST-001"
        )
        self.assertEqual(
            medication_contract["domains"],
            ["backend_chat_ai", "backend_health_sync"],
        )
        self.assertEqual(
            {anchor["symbol"] for anchor in medication_contract["test_anchors"]},
            {
                "test_0023_migration_is_additive_and_enforces_confirmed_tenant_contract",
                "test_recognize_only_creates_unconfirmed_prefill_until_explicit_plan_confirmation",
                "test_today_tasks_actions_are_idempotent_correctable_and_never_assert_missed",
                "test_estimated_remaining_uses_only_latest_confirmed_taken_records",
                "test_adverse_reactions_are_temporal_only_and_correctable",
                "test_only_confirmed_long_term_medications_reach_profile_candidates_and_ai_context",
                "test_confirmed_long_term_medication_summary_exposes_exact_required_fields_only",
                "test_completed_last_long_term_medication_clears_profile_fact_before_ai_context",
                "test_paused_or_retracted_medication_updates_profile_fact_atomically",
                "test_current_fact_source_membership_excludes_retired_medication_plans",
                "test_legacy_medication_payload_redacts_all_dose_schedule_reminder_aliases",
            },
        )
        for domain_id in medication_contract["domains"]:
            domain = next(
                item
                for item in registry["behavior_domains"]
                if item["id"] == domain_id
            )
            self.assertIn("MEDICATION-TRUST-001", domain["required_contract_ids"])
        for command_id in ("backend_ai", "backend_health"):
            self.assertIn(
                "backend/tests/unit/test_medication_trust.py",
                registry["commands"][command_id],
            )

        weakened = copy.deepcopy(registry)
        next(
            contract
            for contract in weakened["contracts"]
            if contract["id"] == "MEDICATION-TRUST-001"
        )["invariant"] = "OCR can create a trusted plan automatically."
        self.assertIn(
            "contract MEDICATION-TRUST-001 invariant/anchor definition changed from the pinned digest",
            guard.validate_registry(weakened),
        )

        medication_paths = (
            guard.TRUSTED_MEDICATION_MANAGEMENT_VIEW_REPO_PATH,
            guard.TRUSTED_MEDICATION_REMINDER_VIEW_REPO_PATH,
            guard.XAGE_INTERACTION_CONTRACTS_REPO_PATH,
        )
        medication_sources = {
            path: (guard.REPO_ROOT / path).read_text(encoding="utf-8")
            for path in medication_paths
        }
        self.assertEqual(
            guard.trusted_medication_accessibility_violations(
                source_contents=medication_sources
            ),
            [],
        )
        accessibility_error = (
            "interactive medication plan cards must keep the plan toggle identifier on a leaf "
            "header button and preserve independent child action identities"
        )
        old_container_sources = dict(medication_sources)
        plan_tail = (
            "        .background(Color.white.opacity(0.42), in: RoundedRectangle(cornerRadius: 18))\n"
            "    }\n\n"
            "    private var planDetails"
        )
        self.assertIn(plan_tail, old_container_sources[guard.TRUSTED_MEDICATION_MANAGEMENT_VIEW_REPO_PATH])
        old_container_sources[guard.TRUSTED_MEDICATION_MANAGEMENT_VIEW_REPO_PATH] = (
            old_container_sources[guard.TRUSTED_MEDICATION_MANAGEMENT_VIEW_REPO_PATH].replace(
                plan_tail,
                "        .background(Color.white.opacity(0.42), in: RoundedRectangle(cornerRadius: 18))\n"
                "        .accessibilityIdentifier(\"xage.medication.plan.\\(plan.plan_id)\")\n"
                "    }\n\n"
                "    private var planDetails",
                1,
            )
        )
        self.assertIn(
            accessibility_error,
            guard.trusted_medication_accessibility_violations(
                source_contents=old_container_sources
            ),
        )

        missing_child_sources = dict(medication_sources)
        missing_child_sources[guard.TRUSTED_MEDICATION_MANAGEMENT_VIEW_REPO_PATH] = (
            missing_child_sources[guard.TRUSTED_MEDICATION_MANAGEMENT_VIEW_REPO_PATH].replace(
                '                .accessibilityIdentifier("xage.medication.plan.more.\\(plan.plan_id)")\n',
                "",
                1,
            )
        )
        self.assertIn(
            accessibility_error,
            guard.trusted_medication_accessibility_violations(
                source_contents=missing_child_sources
            ),
        )

        missing_pull_dismiss_sources = dict(medication_sources)
        pull_dismiss_block = (
            "                .xAgeDismissKeyboardOnDownwardPull(\n"
            "                    verificationIdentifier: \"xage.medication.reminder.pullDismiss.ready\"\n"
            "                ) {\n"
            "                    timeFocused = false\n"
            "                }\n"
        )
        self.assertIn(
            pull_dismiss_block,
            missing_pull_dismiss_sources[guard.TRUSTED_MEDICATION_REMINDER_VIEW_REPO_PATH],
        )
        missing_pull_dismiss_sources[guard.TRUSTED_MEDICATION_REMINDER_VIEW_REPO_PATH] = (
            missing_pull_dismiss_sources[guard.TRUSTED_MEDICATION_REMINDER_VIEW_REPO_PATH].replace(
                pull_dismiss_block,
                "",
                1,
            )
        )
        self.assertIn(
            "medication text editors must use the shared UIKit-only downward-pull keyboard "
            "contract without blocking native scrolling across reminder, plan, OCR, and sheet entry points",
            guard.trusted_medication_accessibility_violations(
                source_contents=missing_pull_dismiss_sources
            ),
        )

        scroll_blocking_sources = dict(medication_sources)
        interaction_path = guard.XAGE_INTERACTION_CONTRACTS_REPO_PATH
        installer_only_body = """        content
            .background {"""
        self.assertIn(installer_only_body, scroll_blocking_sources[interaction_path])
        scroll_blocking_sources[interaction_path] = scroll_blocking_sources[
            interaction_path
        ].replace(
            installer_only_body,
            """        content
            .simultaneousGesture(
                DragGesture(minimumDistance: 12, coordinateSpace: .local)
                    .onEnded { value in
                        let vertical = value.translation.height
                        guard vertical > 20,
                              abs(vertical) > abs(value.translation.width) * 1.2 else { return }
                        dismissKeyboard()
                    }
            )
            .background {""",
            1,
        )
        self.assertIn(
            "medication text editors must use the shared UIKit-only downward-pull keyboard "
            "contract without blocking native scrolling across reminder, plan, OCR, and sheet entry points",
            guard.trusted_medication_accessibility_violations(
                source_contents=scroll_blocking_sources
            ),
        )

    def test_health_trust_contract_rejects_unconfirmed_admission_and_xage_enablement(self):
        contract = guard.load_health_trust_contract()
        self.assertEqual(guard.health_trust_contract_violations(contract), [])

        client_paths = (
            guard.TRUSTED_HEALTH_PROFILE_MODEL_REPO_PATH,
            guard.TRUSTED_HEALTH_PROFILE_REPOSITORY_REPO_PATH,
            guard.TRUSTED_HEALTH_PROFILE_VIEW_MODEL_REPO_PATH,
            guard.TRUSTED_HEALTH_PROFILE_VIEW_REPO_PATH,
            guard.TRUSTED_HEALTH_REPORT_INTERPRETATION_VIEW_REPO_PATH,
            guard.TRUSTED_HEALTH_PROFILE_XAGE_REPO_PATH,
            guard.TRUSTED_HEALTH_PROFILE_MORE_REPO_PATH,
        )
        client_contents = {
            path: (guard.REPO_ROOT / path).read_text(encoding="utf-8")
            for path in client_paths
        }
        self.assertEqual(
            guard.trusted_health_profile_client_violations(
                source_contents=client_contents
            ),
            [],
        )
        client_mutations = (
            (
                "legacy local endpoint",
                guard.TRUSTED_HEALTH_PROFILE_REPOSITORY_REPO_PATH,
                'api.get("/api/health-data/profile-trust")',
                'api.get("/api/health-data/patient-history")',
                "subject-free canonical profile plus subject-bound medication and revision routes",
            ),
            (
                "profile subject injection",
                guard.TRUSTED_HEALTH_PROFILE_REPOSITORY_REPO_PATH,
                'api.get("/api/health-data/profile-trust")',
                'api.get("/api/health-data/profile-trust?subject_user_id=1")',
                "subject-free canonical profile plus subject-bound medication and revision routes",
            ),
            (
                "remove fact revision route",
                guard.TRUSTED_HEALTH_PROFILE_REPOSITORY_REPO_PATH,
                '"/api/health-data/profile-trust/facts/\\(factID)/revisions"',
                '"/api/health-data/profile-trust/facts/\\(factID)"',
                "subject-free canonical profile plus subject-bound medication and revision routes",
            ),
            (
                "unscoped mutation",
                guard.TRUSTED_HEALTH_PROFILE_REPOSITORY_REPO_PATH,
                "api.postAccountBound(",
                "api.post(",
                "account-bound to the six versioned fact, candidate, and goal routes",
            ),
            (
                "drop one medication summary field",
                guard.TRUSTED_HEALTH_PROFILE_MODEL_REPO_PATH,
                ".init(key: .lastConfirmedAt",
                ".init(key: .medicationName",
                "exact six-field medication summary",
            ),
            (
                "candidate bypass",
                guard.TRUSTED_HEALTH_PROFILE_VIEW_MODEL_REPO_PATH,
                "candidate.isReviewable",
                "true",
                "versioned safety confirmation",
            ),
            (
                "hide XAge boundary",
                guard.TRUSTED_HEALTH_PROFILE_VIEW_REPO_PATH,
                "X年龄暂不消费健康画像",
                "X年龄已消费健康画像",
                "XAge disabled notice",
            ),
            (
                "remove health-profile shared pull-dismiss consumer",
                guard.TRUSTED_HEALTH_PROFILE_VIEW_REPO_PATH,
                (
                    "                .xAgeDismissKeyboardOnDownwardPull(\n"
                    "                    verificationIdentifier: \"healthProfile.pullDismiss.ready\"\n"
                    "                ) {\n"
                    "                    editorFocused = false\n"
                    "                }\n"
                ),
                "",
                "shared downward-pull keyboard contract and clear the page FocusState",
            ),
            (
                "remove health-profile goal start-date focus binding",
                guard.TRUSTED_HEALTH_PROFILE_VIEW_REPO_PATH,
                (
                    "            .keyboardType(.numbersAndPunctuation)\n"
                    "            .focused($editorFocused)\n"
                    "            .accessibilityIdentifier(\"healthProfile.goal.editor.startedOn\")"
                ),
                (
                    "            .keyboardType(.numbersAndPunctuation)\n"
                    "            .accessibilityIdentifier(\"healthProfile.goal.editor.startedOn\")"
                ),
                "goal start-date editor must bind the page FocusState",
            ),
            (
                "restore profile container identifier override",
                guard.TRUSTED_HEALTH_PROFILE_VIEW_REPO_PATH,
                "        .cardStyle()\n    }\n\n    private func overviewTile",
                "        .cardStyle()\n        .accessibilityIdentifier(\"healthProfile.overview\")\n    }\n\n    private func overviewTile",
                "static sentinels so child actions retain independent accessibility identities",
            ),
            (
                "restore report root container identifier override",
                guard.TRUSTED_HEALTH_REPORT_INTERPRETATION_VIEW_REPO_PATH,
                "        .navigationBarBackButtonHidden(true)",
                "        .accessibilityIdentifier(\"xage.report.interpretation.root\")\n        .navigationBarBackButtonHidden(true)",
                "visible static title sentinels without overwriting named descendants",
            ),
            (
                "remove report profile static title sentinel",
                guard.TRUSTED_HEALTH_REPORT_INTERPRETATION_VIEW_REPO_PATH,
                '            staticTitleIdentifier: "xage.report.interpretation.profile"',
                '            staticTitleIdentifier: nil',
                "visible static title sentinels without overwriting named descendants",
            ),
            (
                "restore transparent report provenance marker",
                guard.TRUSTED_HEALTH_REPORT_INTERPRETATION_VIEW_REPO_PATH,
                '            staticTitleIdentifier: "xage.report.interpretation.provenance"\n        ) {',
                '            staticTitleIdentifier: nil\n        ) {\n            Color.clear\n                .frame(width: 1, height: 1)\n                .accessibilityIdentifier("xage.report.interpretation.provenance")',
                "visible static title sentinels without overwriting named descendants",
            ),
            (
                "restore fake profile save",
                guard.TRUSTED_HEALTH_PROFILE_XAGE_REPO_PATH,
                'return "打开可信健康画像"',
                'return "保存画像"',
                "without local fake saving",
            ),
            (
                "restore fake data entries",
                guard.TRUSTED_HEALTH_PROFILE_MORE_REPO_PATH,
                "ForEach(XAgeDataPanelCategory.moreProfileCategories)",
                "ForEach(XAgeDataPanelCategory.allCases)",
                "source only the trusted health-profile entry",
            ),
        )
        for name, path, old, new, expected_error in client_mutations:
            weakened = dict(client_contents)
            self.assertIn(old, weakened[path])
            weakened[path] = weakened[path].replace(old, new, 1)
            with self.subTest(health_profile_client=name):
                self.assertTrue(
                    any(
                        expected_error in error
                        for error in guard.trusted_health_profile_client_violations(
                            source_contents=weakened
                        )
                    )
                )

        mutations = (
            (
                "client authority",
                lambda item: item.update(authority="client"),
                "health_trust_contract.json authority must remain 'server'",
            ),
            (
                "skip report confirmation",
                lambda item: item["invariants"].update(
                    report_level_user_confirmation_is_required_before_admission=False
                ),
                "health_trust_contract.json every invariant must be the boolean true",
            ),
            (
                "admit unreviewed OCR into AI",
                lambda item: item["invariants"].update(
                    unadmitted_candidates_are_excluded_from_ai=False
                ),
                "health_trust_contract.json every invariant must be the boolean true",
            ),
            (
                "auto-confirm safety facts",
                lambda item: item["invariants"].update(
                    safety_facts_never_auto_confirm=False
                ),
                "health_trust_contract.json every invariant must be the boolean true",
            ),
            (
                "skip dietary confirmation",
                lambda item: item["invariants"].update(
                    dietary_formal_record_requires_user_confirmation=False
                ),
                "health_trust_contract.json every invariant must be the boolean true",
            ),
            (
                "remove provenance edge",
                lambda item: item["required_provenance_edges"].pop(),
                "health_trust_contract.json provenance chain changed from the pinned ordered edges",
            ),
            (
                "penalize privacy response",
                lambda item: item["profile_completeness"]["resolved_states"].remove(
                    "prefer_not_to_answer"
                ),
                "health_trust_contract.json profile completeness semantics changed",
            ),
            (
                "grandfather legacy OCR",
                lambda item: item["legacy_migration"].update(
                    legacy_unverified_is_admitted=True
                ),
                "health_trust_contract.json legacy admission policy changed",
            ),
            (
                "enable XAge without validation",
                lambda item: item["xage_consumption"].update(enabled=True),
                "health_trust_contract.json XAge enablement boundary changed",
            ),
        )
        for name, mutate, expected_error in mutations:
            weakened = copy.deepcopy(contract)
            mutate(weakened)
            with self.subTest(health_trust_boundary=name):
                self.assertIn(
                    expected_error,
                    guard.health_trust_contract_violations(weakened),
                )

    def test_health_report_completion_rejects_order_scope_recovery_and_version_bypasses(self):
        paths = (
            guard.TRUSTED_HEALTH_REPORT_COMPLETION_MODEL_REPO_PATH,
            guard.TRUSTED_HEALTH_REPORT_COMPLETION_REPOSITORY_REPO_PATH,
            guard.TRUSTED_HEALTH_REPORT_COMPLETION_VIEW_MODEL_REPO_PATH,
            guard.TRUSTED_HEALTH_REPORT_CONVERSATION_REPO_PATH,
            guard.TRUSTED_HEALTH_REPORT_DASHBOARD_REPO_PATH,
            guard.TRUSTED_HEALTH_REPORT_ROOT_REPO_PATH,
        )
        sources = {
            path: (guard.REPO_ROOT / path).read_text(encoding="utf-8")
            for path in paths
        }
        self.assertEqual(
            guard.trusted_health_report_completion_client_violations(
                source_contents=sources
            ),
            [],
        )

        ordered_error = (
            "ordered initial report upload must create one asset set, preserve 1-based "
            "order, and seal that same set once"
        )
        recovery_error = (
            "report recovery must use the server-selected index on the same rejected "
            "asset set, account-bound replacement PUT, then reseal before any workflow"
        )
        entry_error = (
            "every iOS report entry point must either recover exactly one server-selected "
            "page or explicitly restart in the report panel"
        )
        mutations = (
            (
                "collapse initial order",
                guard.TRUSTED_HEALTH_REPORT_COMPLETION_VIEW_MODEL_REPO_PATH,
                "assetIndex: offset + 1,",
                "assetIndex: 1,",
                ordered_error,
            ),
            (
                "seal another initial set",
                guard.TRUSTED_HEALTH_REPORT_COMPLETION_VIEW_MODEL_REPO_PATH,
                "let seal = try await repository.sealUploadSession(\n"
                "                assetSetID: session.asset_set_id,",
                "let seal = try await repository.sealUploadSession(\n"
                "                assetSetID: 0,",
                ordered_error,
            ),
            (
                "remove replacement endpoint",
                guard.TRUSTED_HEALTH_REPORT_COMPLETION_REPOSITORY_REPO_PATH,
                r'"/api/health-data/report-upload-sessions/\(assetSetID)/assets/\(assetIndex)/replacement"',
                r'"/api/health-data/report-upload-sessions/\(assetSetID)/assets/\(assetIndex)"',
                recovery_error,
            ),
            (
                "use unscoped replacement transport",
                guard.TRUSTED_HEALTH_REPORT_COMPLETION_REPOSITORY_REPO_PATH,
                "let data = try await transport.putFileAccountBound(\n"
                r'            "/api/health-data/report-upload-sessions/\(assetSetID)/assets/\(assetIndex)/replacement"',
                "let data = try await transport.putFile(\n"
                r'            "/api/health-data/report-upload-sessions/\(assetSetID)/assets/\(assetIndex)/replacement"',
                recovery_error,
            ),
            (
                "guess next recovery page",
                guard.TRUSTED_HEALTH_REPORT_COMPLETION_VIEW_MODEL_REPO_PATH,
                "missingPageIndices.first ?? problemAssetIndices.first",
                "1",
                recovery_error,
            ),
            (
                "replace guessed page",
                guard.TRUSTED_HEALTH_REPORT_COMPLETION_VIEW_MODEL_REPO_PATH,
                "assetIndex: assetIndex,\n                subjectUserID: context.subjectUserID",
                "assetIndex: 1,\n                subjectUserID: context.subjectUserID",
                recovery_error,
            ),
            (
                "start a new set during recovery",
                guard.TRUSTED_HEALTH_REPORT_COMPLETION_VIEW_MODEL_REPO_PATH,
                "repository.recoverAsset(",
                "repository.startUploadSession(",
                recovery_error,
            ),
            (
                "reseal another recovery set",
                guard.TRUSTED_HEALTH_REPORT_COMPLETION_VIEW_MODEL_REPO_PATH,
                "let seal = try await repository.sealUploadSession(\n"
                "                assetSetID: context.assetSetID,",
                "let seal = try await repository.sealUploadSession(\n"
                "                assetSetID: 0,",
                recovery_error,
            ),
            (
                "accept old account recovery",
                guard.TRUSTED_HEALTH_REPORT_COMPLETION_VIEW_MODEL_REPO_PATH,
                "currentAccountScope() == context.accountScope else",
                "true else",
                recovery_error,
            ),
            (
                "invent workflow after rejected seal",
                guard.TRUSTED_HEALTH_REPORT_COMPLETION_VIEW_MODEL_REPO_PATH,
                "if let failureCode = seal.failure_code {",
                "if false, let failureCode = seal.failure_code {",
                recovery_error,
            ),
            (
                "regenerate recovery id on retry",
                guard.TRUSTED_HEALTH_REPORT_COMPLETION_VIEW_MODEL_REPO_PATH,
                "clientAssetID: Self.recoveryClientAssetID(",
                r'clientAssetID: "recovery-\(makeID())",',
                recovery_error,
            ),
            (
                "retain recovery after account change",
                guard.TRUSTED_HEALTH_REPORT_COMPLETION_VIEW_MODEL_REPO_PATH,
                "pendingRecoveryContext = nil",
                "pendingRecoveryContext = pendingRecoveryContext",
                recovery_error,
            ),
            (
                "guess duplicate version",
                guard.TRUSTED_HEALTH_REPORT_COMPLETION_VIEW_MODEL_REPO_PATH,
                "workflow_version: prompt.workflowVersion",
                "workflow_version: 1",
                "report workflow action and duplicate version must remain server-owned",
            ),
            (
                "allow multi-select recovery in conversation",
                guard.TRUSTED_HEALTH_REPORT_CONVERSATION_REPO_PATH,
                "selectionLimit: recoveryAssetIndex == nil ? 9 : 1",
                "selectionLimit: 9",
                entry_error,
            ),
            (
                "allow multi-select recovery in dashboard",
                guard.TRUSTED_HEALTH_REPORT_DASHBOARD_REPO_PATH,
                "selectionLimit: recoveryAssetIndex == nil ? 9 : 1",
                "selectionLimit: 9",
                entry_error,
            ),
            (
                "route external recovery away from reports",
                guard.TRUSTED_HEALTH_REPORT_ROOT_REPO_PATH,
                "selectedDataPanelCategory = .reports",
                "selectedDataPanelCategory = .profile",
                entry_error,
            ),
        )
        for name, path, old, new, expected_error in mutations:
            weakened = dict(sources)
            self.assertIn(old, weakened[path])
            weakened[path] = weakened[path].replace(old, new, 1)
            with self.subTest(report_completion=name):
                self.assertIn(
                    expected_error,
                    guard.trusted_health_report_completion_client_violations(
                        source_contents=weakened
                    ),
                )

    def test_backend_and_tool_tests_map_to_every_corresponding_gate(self):
        registry = guard.load_registry()
        dietary_paths = (
            "Xjie/Xjie/Models/MealModels.swift",
            "Xjie/Xjie/ViewModels/MealsViewModel.swift",
            "Xjie/Xjie/Views/Meals/MealsView.swift",
            "Xjie/XjieTests/DietaryRecordsTests.swift",
            "backend/app/models/dietary_records.py",
            "backend/app/schemas/dietary_records.py",
            "backend/app/services/dietary_records_service.py",
            "backend/app/routers/dietary_records.py",
            "backend/app/workers/dietary_tasks.py",
            "backend/tests/unit/test_dietary_records_contract.py",
        )
        dietary_primary, dietary_verification = guard.classify_changes(
            dietary_paths, registry
        )
        self.assertEqual(
            dietary_primary["ios_health_client"],
            [dietary_paths[0], dietary_paths[1], dietary_paths[3]],
        )
        self.assertEqual(
            dietary_primary["ios_ui_interaction"],
            [dietary_paths[2]],
        )
        self.assertEqual(
            dietary_primary["backend_health_sync"],
            list(dietary_paths[4:]),
        )
        self.assertTrue(
            {"ios_health_client", "backend_health_sync"}.issubset(
                dietary_verification
            )
        )
        self.assertIn(
            "backend/tests/unit/test_dietary_records_contract.py",
            guard.PINNED_FOCUSED_BACKEND_COMMAND_TEMPLATES["backend_health"],
        )
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

        deploy_policy_test = "tools/tests/test_release_policy.py"
        deploy_test_primary, deploy_test_verification = guard.classify_changes(
            (deploy_policy_test,), registry
        )
        self.assertEqual(
            deploy_test_primary,
            {
                "backend_core": [deploy_policy_test],
                "quality_process_gate": [deploy_policy_test],
                "test_suite_integrity": [deploy_policy_test],
            },
        )
        self.assertEqual(
            deploy_test_verification,
            {"backend_core", "quality_process_gate", "test_suite_integrity"},
        )
        backend_core_domain = next(
            domain
            for domain in registry["behavior_domains"]
            if domain["id"] == "backend_core"
        )
        meaningful, candidates = guard._meaningful_test_change(
            backend_core_domain,
            guard.ChangeSet(
                (deploy_policy_test,),
                {
                    deploy_policy_test: (
                        'self.assertIn(\'docker build --tag "$IMAGE_REF"\', deploy)',
                    )
                },
            ),
        )
        self.assertTrue(meaningful)
        self.assertEqual(candidates, [deploy_policy_test])

        deployment_paths = (
            "docker-compose.yml",
            "backend/Dockerfile",
            "backend/.dockerignore",
            "backend/.env.example",
            "backend/alembic.ini",
            "backend/static/index.html",
            "backend/deploy/nginx/xjie-api-exact-locations.conf",
            "backend/deploy/production_container.json",
            "backend/deploy/production_deploy_guard.py",
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
            [
                *deployment_paths[:7],
                deployment_paths[9],
                deployment_paths[10],
                deployment_paths[12],
            ],
        )
        self.assertEqual(
            deployment_primary["quality_process_gate"],
            [
                "backend/Dockerfile",
                "backend/deploy/production_container.json",
                "backend/deploy/production_deploy_guard.py",
                "scripts/deploy_literature.sh",
            ],
        )
        self.assertEqual(
            deployment_primary["backend_health_sync"],
            [deployment_paths[-1]],
        )
        self.assertEqual(
            deployment_verification,
            {
                "backend_core",
                "backend_health_sync",
                "quality_process_gate",
                "test_suite_integrity",
            },
        )
        domains = {domain["id"]: domain for domain in registry["behavior_domains"]}
        self.assertTrue(
            {"backend_full", "guard_unit", "diff_check"}.issubset(
                domains["backend_core"]["verification_commands"]
            )
        )
        self.assertTrue(
            {"backend_full", "guard_unit", "diff_check"}.issubset(
                domains["backend_health_sync"]["verification_commands"]
            )
        )
        self.assertTrue(
            {"guard_unit", "ios_release_build", "diff_check"}.issubset(
                domains["quality_process_gate"]["verification_commands"]
            )
        )

        production_runtime_paths = (
            "backend/Dockerfile",
            "backend/pyproject.toml",
            "backend/requirements.lock",
            "scripts/launch_production_deploy.py",
            "scripts/install_production_deploy_bundle.py",
            "tools/production_catalog_postgres_selftest.py",
            "tools/production_launcher_linux_selftest.py",
            "tools/production_bundle_installer_linux_selftest.py",
        )
        runtime_primary, runtime_verification = guard.classify_changes(
            production_runtime_paths,
            registry,
        )
        self.assertEqual(
            runtime_primary,
            {
                "backend_core": list(production_runtime_paths),
                "quality_process_gate": list(production_runtime_paths),
                "test_suite_integrity": list(production_runtime_paths),
            },
        )
        self.assertEqual(
            runtime_verification,
            {"backend_core", "quality_process_gate", "test_suite_integrity"},
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
                "required_contract_ids": ["PROCESS-GATE-001"],
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

        swift_manifest = guard.load_swift_source_manifest()
        self.assertEqual(guard.swift_source_manifest_violations(swift_manifest), [])
        current_source_path = swift_manifest["sources"][0]["path"]
        current_contents = {
            entry["path"]: (guard.REPO_ROOT / entry["path"]).read_text(encoding="utf-8")
            for entry in swift_manifest["sources"]
        }
        self.assertNotIn(
            guard.TRUSTED_SCORE_POLICY_REPO_PATH,
            current_contents,
            "trusted score policy belongs to HealthData and must stay outside Home inventory",
        )
        self.assertEqual(
            Path(guard.TRUSTED_SCORE_POLICY_REPO_PATH).parent.as_posix(),
            "Xjie/Xjie/Views/HealthData",
        )
        trusted_paths = (
            guard.TRUSTED_SCORE_POLICY_REPO_PATH,
            guard.TRUSTED_SCORE_ROOT_REPO_PATH,
            guard.TRUSTED_SCORE_DASHBOARD_REPO_PATH,
            guard.TRUSTED_SCORE_XAGE_REPO_PATH,
        )
        trusted_contents = {
            path: (guard.REPO_ROOT / path).read_text(encoding="utf-8")
            for path in trusted_paths
        }
        self.assertEqual(
            guard.trusted_score_presentation_violations(
                source_contents=trusted_contents
            ),
            [],
        )
        trusted_mutations = (
            (
                "XAge enabled",
                guard.TRUSTED_SCORE_POLICY_REPO_PATH,
                "static let isXAgeConsumptionEnabled = false",
                "static let isXAgeConsumptionEnabled = true",
                "must keep XAge consumption disabled",
            ),
            (
                "local result returned",
                guard.TRUSTED_SCORE_POLICY_REPO_PATH,
                "return unavailable",
                "return localResearch!",
                "must reject every local research result",
            ),
            (
                "root local computation",
                guard.TRUSTED_SCORE_ROOT_REPO_PATH,
                "XAgeTrustedScorePresentationPolicy.currentPresentation()",
                "XAgeCompositeScores.compute(context: XAgeAlgorithmContext())",
                "XAge root must consume scores only through the trusted presentation policy",
            ),
            (
                "dashboard local readiness",
                guard.TRUSTED_SCORE_DASHBOARD_REPO_PATH,
                "metric.isTrustedForDisplay",
                "metric.isReady",
                "dashboard score consumers must use only trusted display readiness",
            ),
            (
                "XAge direct local consumer",
                guard.TRUSTED_SCORE_XAGE_REPO_PATH,
                "import SwiftUI",
                "import SwiftUI\nlet bypass = scores.xAge",
                "XAge view must remain disabled without local age, delta, pace, or weekly trends",
            ),
        )
        for name, path, old, new, expected_error in trusted_mutations:
            weakened = dict(trusted_contents)
            self.assertIn(old, weakened[path])
            weakened[path] = weakened[path].replace(old, new, 1)
            with self.subTest(trusted_score_presentation=name):
                self.assertTrue(
                    any(
                        expected_error in error
                        for error in guard.trusted_score_presentation_violations(
                            source_contents=weakened
                        )
                    )
                )

        missing_policy = dict(trusted_contents)
        missing_policy.pop(guard.TRUSTED_SCORE_POLICY_REPO_PATH)
        self.assertIn(
            "trusted score production source is missing: "
            + guard.TRUSTED_SCORE_POLICY_REPO_PATH,
            guard.trusted_score_presentation_violations(
                source_contents=missing_policy
            ),
        )

        def reverse_mapping(item):
            reordered = {
                key: copy.deepcopy(item[key]) for key in reversed(tuple(item))
            }
            item.clear()
            item.update(reordered)

        manifest_mutations = (
            (
                "top-level key order",
                reverse_mapping,
                "swift_source_manifest.json keys and order must exactly match the pinned schema",
            ),
            (
                "boolean schema version",
                lambda item: item.update(schema_version=True),
                "swift_source_manifest.json schema_version must be the integer 1",
            ),
            (
                "source root",
                lambda item: item.update(source_root="Xjie/Xjie/Views"),
                "swift_source_manifest.json source_root must remain",
            ),
            (
                "project path",
                lambda item: item.update(xcode_project="Xjie/Other.xcodeproj/project.pbxproj"),
                "swift_source_manifest.json xcode_project must remain",
            ),
            (
                "entry key order",
                lambda item: item["sources"].__setitem__(
                    0,
                    {
                        key: copy.deepcopy(item["sources"][0][key])
                        for key in reversed(tuple(item["sources"][0]))
                    },
                ),
                "swift source entry 0 keys and order must exactly match the pinned schema",
            ),
            (
                "unsafe nested path",
                lambda item: item["sources"][0].update(
                    path="Xjie/Xjie/Views/Home/Nested/XAgeMainView.swift"
                ),
                "path must be a normalized direct XAge*.swift child",
            ),
            (
                "unknown role",
                lambda item: item["sources"][0].update(role="root"),
                "has an unknown role",
            ),
            (
                "domain order",
                lambda item: item["sources"][0]["domains"].reverse(),
                "domains must exactly match the pinned ordered mapping",
            ),
            (
                "boolean per-file maximum",
                lambda item: item["sources"][0].update(max_lines=True),
                "max_lines must remain "
                + str(swift_manifest["sources"][0]["max_lines"]),
            ),
            (
                "aggregate key order",
                lambda item: item.__setitem__(
                    "aggregate_limits",
                    {
                        key: copy.deepcopy(item["aggregate_limits"][key])
                        for key in reversed(tuple(item["aggregate_limits"]))
                    },
                ),
                "swift aggregate limit keys and order must exactly match the pinned schema",
            ),
            (
                "raised aggregate line maximum",
                lambda item: item["aggregate_limits"].update(
                    max_nonblank_nonimport_lines=9549
                ),
                "swift aggregate max_nonblank_nonimport_lines must remain 9548",
            ),
            (
                "removed aggregate pattern",
                lambda item: item["aggregate_limits"]["pattern_limits"].pop(),
                "swift aggregate pattern_limits must exactly match the pinned baseline",
            ),
            (
                "integer pattern maximum replaced by boolean",
                lambda item: item["aggregate_limits"]["pattern_limits"][0].update(
                    max_count=True
                ),
                "swift aggregate pattern_limits must exactly match the pinned baseline",
            ),
            (
                "removed legacy route prohibition",
                lambda item: item["aggregate_limits"]["forbidden_patterns"].pop(),
                "swift aggregate forbidden_patterns must exactly match the pinned legacy-route set",
            ),
        )
        for name, mutate, expected_error in manifest_mutations:
            weakened = copy.deepcopy(swift_manifest)
            mutate(weakened)
            with self.subTest(swift_source_manifest=name):
                self.assertTrue(
                    any(
                        expected_error in error
                        for error in guard.swift_source_manifest_violations(
                            weakened,
                            source_contents=current_contents,
                        )
                    )
                )

        unlisted_source = {
            **current_contents,
            "Xjie/Xjie/Views/Home/XAgeUnlisted.swift": "import SwiftUI\n",
        }
        self.assertTrue(
            any(
                "must exactly cover every Home XAge*.swift file" in error
                for error in guard.swift_source_manifest_violations(
                    swift_manifest,
                    source_contents=unlisted_source,
                )
            )
        )
        overlong_source = {
            **current_contents,
            current_source_path: "// budget line\n"
            * (swift_manifest["sources"][0]["max_lines"] + 1),
        }
        self.assertTrue(
            any(
                "swift source per-file limit exceeded" in error
                for error in guard.swift_source_manifest_violations(
                    swift_manifest,
                    source_contents=overlong_source,
                )
            )
        )

        split_manifest = copy.deepcopy(swift_manifest)
        split_manifest["sources"] = []
        split_contents = {}
        for index, role in enumerate(guard.PINNED_SWIFT_SPLIT_ROLES):
            path = (
                f"{guard.PINNED_SWIFT_SOURCE_ROOT}/"
                f"XAgeSplit{index}_{role}.swift"
            )
            split_manifest["sources"].append(
                {
                    "path": path,
                    "role": role,
                    "domains": list(guard.PINNED_SWIFT_SOURCE_ROLE_DOMAINS[role]),
                    "max_lines": guard.PINNED_SWIFT_SOURCE_ROLE_MAX_LINES[role],
                }
            )
            split_contents[path] = "import SwiftUI\n"
        self.assertEqual(
            guard.swift_source_manifest_violations(
                split_manifest,
                source_contents=split_contents,
            ),
            [],
        )

        recombined_path = (
            f"{guard.PINNED_SWIFT_SOURCE_ROOT}/XAgeMainView.swift"
        )
        recombined_manifest = copy.deepcopy(swift_manifest)
        recombined_manifest["sources"] = [
            {
                "path": recombined_path,
                "role": "monolith",
                "domains": [
                    "ios_ui_interaction",
                    "ios_chat_client",
                    "ios_health_client",
                    "ios_account_client",
                ],
                "max_lines": 10305,
            }
        ]
        recombined_contents = {
            recombined_path: "\n".join(
                line
                for path in current_contents
                for line in current_contents[path].splitlines()
                if not line.strip().startswith("import ")
            )
        }
        recombined_errors = guard.swift_source_manifest_violations(
            recombined_manifest,
            source_contents=recombined_contents,
        )
        self.assertTrue(
            any("has an unknown role: 'monolith'" in error for error in recombined_errors)
        )
        self.assertIn(
            "swift source roles must be the complete ordered split role set",
            recombined_errors,
        )

        duplicate_split_path = copy.deepcopy(split_manifest)
        duplicate_split_path["sources"][1]["path"] = duplicate_split_path["sources"][0][
            "path"
        ]
        self.assertIn(
            "swift source manifest paths must be unique",
            guard.swift_source_manifest_violations(
                duplicate_split_path,
                source_contents=split_contents,
            ),
        )
        reordered_split = copy.deepcopy(split_manifest)
        reordered_split["sources"][0], reordered_split["sources"][1] = (
            reordered_split["sources"][1],
            reordered_split["sources"][0],
        )
        self.assertIn(
            "swift source roles must be the complete ordered split role set",
            guard.swift_source_manifest_violations(
                reordered_split,
                source_contents=split_contents,
            ),
        )

        split_pattern_bypass = dict(split_contents)
        split_pattern_bypass[split_manifest["sources"][3]["path"]] += "\n".join(
            f"struct SplitBypass{index} {{}}" for index in range(101)
        )
        self.assertTrue(
            any(
                "101 struct declarations, max 100" in error
                for error in guard.swift_source_manifest_violations(
                    split_manifest,
                    source_contents=split_pattern_bypass,
                )
            )
        )

        remaining_lines = guard.PINNED_SWIFT_AGGREGATE_LOGICAL_LINES + 1
        split_line_bypass = {}
        for entry in split_manifest["sources"]:
            line_count = min(entry["max_lines"], remaining_lines)
            split_line_bypass[entry["path"]] = "let splitBudget = 0\n" * line_count
            remaining_lines -= line_count
        self.assertEqual(remaining_lines, 0)
        line_bypass_errors = guard.swift_source_manifest_violations(
            split_manifest,
            source_contents=split_line_bypass,
        )
        self.assertIn(
            "swift aggregate architecture limit exceeded: source manifest has 9549 "
            "nonblank non-import lines, max 9548",
            line_bypass_errors,
        )
        self.assertFalse(
            any("per-file limit exceeded" in error for error in line_bypass_errors)
        )

        split_legacy_bypass = dict(split_contents)
        split_legacy_bypass[split_manifest["sources"][-1]["path"]] += (
            "let legacy = MedicationListView()\n"
        )
        self.assertIn(
            "forbidden aggregate Swift architecture reference: legacy MedicationListView route",
            guard.swift_source_manifest_violations(
                split_manifest,
                source_contents=split_legacy_bypass,
            ),
        )

        all_swift_paths = {
            path.relative_to(guard.REPO_ROOT).as_posix()
            for path in guard.REPO_ROOT.rglob("*.swift")
            if ".git" not in path.relative_to(guard.REPO_ROOT).parts
        }
        project_source = guard.PROJECT_FILE_PATH.read_text(encoding="utf-8")
        manifest_paths = tuple(entry["path"] for entry in swift_manifest["sources"])
        self.assertEqual(
            guard.swift_source_layout_violations(
                all_swift_paths,
                project_source,
                required_app_sources=manifest_paths,
            ),
            [],
        )
        source_phase_without_xage = project_source.replace(
            "\t\t\t\tA90001 /* XAgeMainView.swift in Sources */,\n",
            "",
            1,
        )
        self.assertIn(
            "XAGE Swift source manifest entries must each be compiled exactly once by the app "
            "source phase: ['Xjie/Xjie/Views/Home/XAgeMainView.swift']",
            guard.swift_source_layout_violations(
                all_swift_paths,
                source_phase_without_xage,
                required_app_sources=manifest_paths,
            ),
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            duplicate_manifest_path = Path(temp_dir) / "swift_source_manifest.json"
            duplicate_manifest_path.write_text(
                '{"schema_version":1,"schema_version":1}',
                encoding="utf-8",
            )
            with mock.patch.object(
                guard,
                "SWIFT_SOURCE_MANIFEST_PATH",
                duplicate_manifest_path,
            ), self.assertRaisesRegex(guard.GuardError, "duplicate JSON key"):
                guard.load_swift_source_manifest()

            real_manifest_path = Path(temp_dir) / "real.json"
            real_manifest_path.write_text("{}", encoding="utf-8")
            symlink_manifest_path = Path(temp_dir) / "symlink.json"
            symlink_manifest_path.symlink_to(real_manifest_path)
            with mock.patch.object(
                guard,
                "SWIFT_SOURCE_MANIFEST_PATH",
                symlink_manifest_path,
            ), self.assertRaisesRegex(guard.GuardError, "regular non-symlink"):
                guard.load_swift_source_manifest()

        production_patterns = (
            "backend/Dockerfile",
            "backend/pyproject.toml",
            "backend/requirements.lock",
            "scripts/*production_deploy*",
            "tools/production_*",
        )
        for pattern in production_patterns:
            weakened = copy.deepcopy(registry)
            weakened_domains = {
                domain["id"]: domain for domain in weakened["behavior_domains"]
            }
            weakened_domains["quality_process_gate"]["source_patterns"].remove(pattern)
            weakened_domains["test_suite_integrity"]["source_patterns"].remove(pattern)
            weakened_domains["test_suite_integrity"]["test_patterns"].remove(pattern)
            weakened_domains["backend_core"]["source_patterns"].remove(pattern)
            pattern_errors = guard.validate_registry(weakened)
            with self.subTest(production_runtime_pattern=pattern):
                self.assertTrue(
                    any(
                        error.startswith(
                            "quality_process_gate is missing protected source patterns:"
                        )
                        and pattern in error
                        for error in pattern_errors
                    )
                )
                self.assertTrue(
                    any(
                        error.startswith(
                            "test_suite_integrity is missing protected source_patterns:"
                        )
                        and pattern in error
                        for error in pattern_errors
                    )
                )
                self.assertTrue(
                    any(
                        error.startswith(
                            "test_suite_integrity is missing protected test_patterns:"
                        )
                        and pattern in error
                        for error in pattern_errors
                    )
                )
                self.assertTrue(
                    any(
                        error.startswith(
                            "backend_core is missing deployment/migration source patterns:"
                        )
                        and pattern in error
                        for error in pattern_errors
                    )
                )

        def swap_protected_branch_settings(item):
            settings = item["release_gate"]["branch_roles"]["protected_branches"]
            settings["main"], settings["XAGE"] = settings["XAGE"], settings["main"]

        def swap_branch_release_contract_definitions(item):
            branch_contract = next(
                contract
                for contract in item["contracts"]
                if contract["id"] == "BRANCH-CANONICAL-001"
            )
            release_contract = next(
                contract
                for contract in item["contracts"]
                if contract["id"] == "RELEASE-GATE-001"
            )
            branch_definition = (
                branch_contract["invariant"],
                branch_contract["test_anchors"],
            )
            branch_contract["invariant"] = release_contract["invariant"]
            branch_contract["test_anchors"] = release_contract["test_anchors"]
            release_contract["invariant"] = branch_definition[0]
            release_contract["test_anchors"] = branch_definition[1]

        branch_role_error = (
            "release_gate branch_roles must exactly define canonical main and locked "
            "read-only XAGE"
        )
        branch_role_mutations = (
            (
                "schema downgrade",
                lambda item: item.update(schema_version=2),
                "regression_contracts.json schema_version must be the integer 3",
            ),
            (
                "missing branch roles",
                lambda item: item["release_gate"].pop("branch_roles"),
                branch_role_error,
            ),
            (
                "extra branch role field",
                lambda item: item["release_gate"]["branch_roles"].update(
                    release_branch="main"
                ),
                branch_role_error,
            ),
            (
                "branch role key order",
                lambda item: item["release_gate"].__setitem__(
                    "branch_roles",
                    {
                        key: copy.deepcopy(item["release_gate"]["branch_roles"][key])
                        for key in (
                            "read_only_branches",
                            "canonical_branch",
                            "protected_branches",
                        )
                    },
                ),
                branch_role_error,
            ),
            (
                "canonical and read-only interchange",
                lambda item: item["release_gate"]["branch_roles"].update(
                    canonical_branch="XAGE",
                    read_only_branches=["main"],
                ),
                branch_role_error,
            ),
            (
                "protected branch order",
                lambda item: item["release_gate"]["branch_roles"].__setitem__(
                    "protected_branches",
                    {
                        key: copy.deepcopy(
                            item["release_gate"]["branch_roles"]["protected_branches"][key]
                        )
                        for key in ("XAGE", "main")
                    },
                ),
                branch_role_error,
            ),
            (
                "protected settings interchange",
                swap_protected_branch_settings,
                branch_role_error,
            ),
            (
                "missing XAGE protection",
                lambda item: item["release_gate"]["branch_roles"][
                    "protected_branches"
                ].pop("XAGE"),
                branch_role_error,
            ),
            (
                "extra protected branch",
                lambda item: item["release_gate"]["branch_roles"][
                    "protected_branches"
                ].update(
                    legacy={"lock_branch": True, "allow_fork_syncing": False}
                ),
                branch_role_error,
            ),
            (
                "nested setting key order",
                lambda item: item["release_gate"]["branch_roles"][
                    "protected_branches"
                ].__setitem__(
                    "main",
                    {"allow_fork_syncing": False, "lock_branch": False},
                ),
                branch_role_error,
            ),
            (
                "main locked",
                lambda item: item["release_gate"]["branch_roles"][
                    "protected_branches"
                ]["main"].update(lock_branch=True),
                branch_role_error,
            ),
            (
                "XAGE unlocked",
                lambda item: item["release_gate"]["branch_roles"][
                    "protected_branches"
                ]["XAGE"].update(lock_branch=False),
                branch_role_error,
            ),
            (
                "fork syncing enabled",
                lambda item: item["release_gate"]["branch_roles"][
                    "protected_branches"
                ]["main"].update(allow_fork_syncing=True),
                branch_role_error,
            ),
            (
                "boolean replaced by integer",
                lambda item: item["release_gate"]["branch_roles"][
                    "protected_branches"
                ]["main"].update(lock_branch=0),
                branch_role_error,
            ),
            (
                "obsolete parallel protected branches",
                lambda item: item["release_gate"].update(
                    protected_branches=["XAGE", "main"]
                ),
                "release_gate keys and order must exactly match the pinned schema",
            ),
            (
                "release gate parent key order",
                lambda item: item.__setitem__(
                    "release_gate",
                    {
                        key: copy.deepcopy(item["release_gate"][key])
                        for key in reversed(tuple(item["release_gate"]))
                    },
                ),
                "release_gate keys and order must exactly match the pinned schema",
            ),
            (
                "ios release contract order",
                lambda item: next(
                    domain
                    for domain in item["behavior_domains"]
                    if domain["id"] == "ios_project_release"
                )["required_contract_ids"].reverse(),
                "domain ios_project_release required_contract_ids changed from the pinned mapping",
            ),
            (
                "missing canonical contract mapping",
                lambda item: next(
                    domain
                    for domain in item["behavior_domains"]
                    if domain["id"] == "quality_process_gate"
                )["required_contract_ids"].remove("BRANCH-CANONICAL-001"),
                "domain quality_process_gate required_contract_ids changed from the pinned mapping",
            ),
            (
                "missing canonical contract definition",
                lambda item: item["contracts"].__setitem__(
                    slice(None),
                    [
                        contract
                        for contract in item["contracts"]
                        if contract["id"] != "BRANCH-CANONICAL-001"
                    ],
                ),
                "regression contract ids must match the pinned domain mapping: "
                "missing BRANCH-CANONICAL-001",
            ),
            (
                "canonical and release definition interchange",
                swap_branch_release_contract_definitions,
                "contract BRANCH-CANONICAL-001 invariant/anchor definition changed from "
                "the pinned digest",
            ),
        )
        for name, mutate, expected_error in branch_role_mutations:
            weakened = copy.deepcopy(registry)
            mutate(weakened)
            with self.subTest(branch_role_contract=name):
                self.assertIn(expected_error, guard.validate_registry(weakened))

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
                domain for domain in item["behavior_domains"] if domain["id"] == "quality_process_gate"
            )["source_patterns"].remove("scripts/deploy_*.sh"),
            lambda item: next(
                domain for domain in item["behavior_domains"] if domain["id"] == "quality_process_gate"
            )["source_patterns"].remove("backend/deploy/production_*"),
            lambda item: next(
                contract for contract in item["contracts"] if contract["id"] == "PROCESS-GATE-001"
            ).update(domains=[]),
            lambda item: next(
                contract for contract in item["contracts"] if contract["id"] == "BACKEND-CORE-001"
            ).update(domains=[]),
            lambda item: item["contracts"].__setitem__(
                slice(None),
                [
                    {
                        **contract,
                        "domains": [
                            domain
                            for domain in contract["domains"]
                            if domain != "backend_chat_ai"
                        ],
                    }
                    for contract in item["contracts"]
                ],
            ),
            lambda item: item["release_gate"].update(github_repository="fork/XJie_IOS"),
            lambda item: item["release_gate"].update(latest_uploaded_build=16),
            lambda item: item["release_gate"].update(
                testflight_signoff_max_age_hours=24
            ),
            lambda item: item["release_gate"].update(
                testflight_signoff_max_age_hours=168.0
            ),
            lambda item: item["release_gate"]["pending_internal_candidate"].update(
                external_promotion_allowed=True
            ),
            lambda item: item["release_gate"]["pending_internal_candidate"]["upload"].update(
                state="pending"
            ),
            lambda item: item["release_gate"]["pending_internal_candidate"]["upload"].update(
                method="verified_local_ipa_altool"
            ),
            lambda item: item["release_gate"]["post_upload_signoffs"].pop(),
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

            testflight_template = json.loads(
                guard.TESTFLIGHT_SIGNOFF_TEMPLATE_PATH.read_text(encoding="utf-8")
            )
            testflight_template_path = temp_root / "testflight_signoffs.example.json"
            for field in ("pending_candidate_sha256", "upload_receipt_identifier"):
                tampered_template = copy.deepcopy(testflight_template)
                tampered_template[field] = ""
                testflight_template_path.write_text(
                    json.dumps(tampered_template), encoding="utf-8"
                )
                with self.subTest(template_field=field), mock.patch.object(
                    guard, "TESTFLIGHT_SIGNOFF_TEMPLATE_PATH", testflight_template_path
                ):
                    self.assertIn(
                        f"TestFlight signoff template {field} must remain a placeholder",
                        guard.validate_registry(registry),
                    )

            for location in ("top", "item"):
                tampered_template = copy.deepcopy(testflight_template)
                if location == "top":
                    tampered_template["installation_source"] = "Local archive"
                else:
                    tampered_template["items"][0]["installation_source"] = "Xcode"
                testflight_template_path.write_text(
                    json.dumps(tampered_template), encoding="utf-8"
                )
                with self.subTest(template_installation_source=location), mock.patch.object(
                    guard, "TESTFLIGHT_SIGNOFF_TEMPLATE_PATH", testflight_template_path
                ):
                    self.assertTrue(
                        any(
                            "TestFlight signoff template" in error
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
