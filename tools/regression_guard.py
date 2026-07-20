#!/usr/bin/env python3
"""Static regression-prevention gate for the XJie iOS canonical main branch.

The guard intentionally uses only the Python standard library so it can run in
Git hooks and CI before project dependencies are installed.
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
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
SWIFT_SOURCE_MANIFEST_PATH = REPO_ROOT / "quality" / "swift_source_manifest.json"
SWIFT_SOURCE_MANIFEST_REPO_PATH = "quality/swift_source_manifest.json"
HEALTH_TRUST_CONTRACT_PATH = REPO_ROOT / "quality" / "health_trust_contract.json"
HEALTH_TRUST_CONTRACT_REPO_PATH = "quality/health_trust_contract.json"
DEVELOPMENT_RECORDS_PATH = REPO_ROOT / "development_records.json"
DEVELOPMENT_RECORDS_REPO_PATH = "development_records.json"
SIGNOFF_TEMPLATE_PATH = REPO_ROOT / "quality" / "release_signoffs.example.json"
TESTFLIGHT_SIGNOFF_TEMPLATE_PATH = (
    REPO_ROOT / "quality" / "testflight_signoffs.example.json"
)
PROJECT_FILE_PATH = REPO_ROOT / "Xjie" / "Xjie.xcodeproj" / "project.pbxproj"
TRUSTED_SCORE_POLICY_REPO_PATH = "Xjie/Xjie/Views/HealthData/XAgeTrustedScorePresentation.swift"
TRUSTED_SCORE_ROOT_REPO_PATH = "Xjie/Xjie/Views/Home/XAgeMainView.swift"
TRUSTED_SCORE_DASHBOARD_REPO_PATH = "Xjie/Xjie/Views/Home/XAgeDataDashboard.swift"
TRUSTED_SCORE_XAGE_REPO_PATH = "Xjie/Xjie/Views/Home/XAgeHealthspan.swift"
TRUSTED_HEALTH_PROFILE_MODEL_REPO_PATH = "Xjie/Xjie/Models/PatientHistoryModels.swift"
TRUSTED_HEALTH_PROFILE_REPOSITORY_REPO_PATH = (
    "Xjie/Xjie/Repositories/PatientHistoryRepository.swift"
)
TRUSTED_HEALTH_PROFILE_VIEW_MODEL_REPO_PATH = (
    "Xjie/Xjie/ViewModels/PatientHistoryViewModel.swift"
)
TRUSTED_HEALTH_PROFILE_VIEW_REPO_PATH = (
    "Xjie/Xjie/Views/PatientHistory/PatientHistoryView.swift"
)
TRUSTED_HEALTH_REPORT_INTERPRETATION_VIEW_REPO_PATH = (
    "Xjie/Xjie/Views/HealthData/HealthReportInterpretationView.swift"
)
TRUSTED_HEALTH_REPORT_COMPLETION_MODEL_REPO_PATH = (
    "Xjie/Xjie/Models/HealthReportCompletionModels.swift"
)
TRUSTED_HEALTH_REPORT_COMPLETION_REPOSITORY_REPO_PATH = (
    "Xjie/Xjie/Repositories/HealthReportCompletionRepository.swift"
)
TRUSTED_HEALTH_REPORT_COMPLETION_VIEW_MODEL_REPO_PATH = (
    "Xjie/Xjie/ViewModels/HealthReportCompletionViewModel.swift"
)
TRUSTED_HEALTH_REPORT_CONVERSATION_REPO_PATH = (
    "Xjie/Xjie/Views/Home/XAgeConversation.swift"
)
TRUSTED_HEALTH_REPORT_DASHBOARD_REPO_PATH = (
    "Xjie/Xjie/Views/Home/XAgeDataDashboard.swift"
)
TRUSTED_HEALTH_REPORT_ROOT_REPO_PATH = "Xjie/Xjie/Views/Home/XAgeMainView.swift"
TRUSTED_MEDICATION_MANAGEMENT_VIEW_REPO_PATH = (
    "Xjie/Xjie/Views/Medications/XAgeMedicationManagementView.swift"
)
TRUSTED_MEDICATION_REMINDER_VIEW_REPO_PATH = (
    "Xjie/Xjie/Views/Medications/MedicationReminderView.swift"
)
XAGE_INTERACTION_CONTRACTS_REPO_PATH = "Xjie/Xjie/Views/Home/XAgeContracts.swift"
TRUSTED_HEALTH_PROFILE_XAGE_REPO_PATH = TRUSTED_SCORE_DASHBOARD_REPO_PATH
TRUSTED_HEALTH_PROFILE_MORE_REPO_PATH = "Xjie/Xjie/Views/Home/XAgeSettings.swift"
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
    "backend_ai": "{backend_python} -I tools/python_test_gate.py backend --profile focused --junitxml /tmp/xjie-backend-ai.xml -- backend/tests/unit/test_chat_execution_pipeline.py backend/tests/unit/test_chat_routing.py backend/tests/unit/test_chat_message_structure.py backend/tests/unit/test_health_nlu.py backend/tests/unit/test_numeric_health_risk.py backend/tests/unit/test_numeric_risk_reply.py backend/tests/unit/test_safety_response.py backend/tests/unit/test_chat_response_guard.py backend/tests/unit/test_openai_provider_parsing.py backend/tests/unit/test_chat_citations.py backend/tests/unit/test_chat_evidence.py backend/tests/unit/test_medication_trust.py -q",
    "backend_health": "{backend_python} -I tools/python_test_gate.py backend --profile focused --junitxml /tmp/xjie-backend-health.xml -- backend/tests/unit/test_device_indicator_sync.py backend/tests/unit/test_device_indicator_sync_http.py backend/tests/unit/test_dietary_records_contract.py backend/tests/unit/test_migration_0021_device_indicator_identity.py backend/tests/unit/test_health_report_admission.py backend/tests/unit/test_health_report_completion.py backend/tests/unit/test_health_profile_trust.py backend/tests/unit/test_health_profile_completion.py backend/tests/unit/test_health_trust_contracts.py backend/tests/unit/test_health_trust_expansion_schema.py backend/tests/unit/test_report_ocr_service.py backend/tests/unit/test_medication_trust.py backend/tests/unit/test_account_lifecycle.py -q",
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
PINNED_MAX_AGE_HOURS = 24
PINNED_TESTFLIGHT_SIGNOFF_MAX_AGE_HOURS = 7 * 24
PINNED_LATEST_UPLOADED_BUILD = 18
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
PINNED_RELEASE_GATE_KEYS = (
    "max_age_hours",
    "testflight_signoff_max_age_hours",
    "latest_uploaded_build",
    "github_repository",
    "github_workflow",
    "required_check",
    "branch_protection",
    "branch_roles",
    "pending_internal_candidate",
    "post_upload_signoffs",
    "manual_signoffs",
    "required_commands",
)
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
MANDATORY_PROCESS_SOURCE_PATTERNS = {
    ".github/workflows/*.yml",
    ".github/workflows/*.yaml",
    ".githooks/*",
    "backend/Dockerfile",
    "backend/pyproject.toml",
    "backend/requirements.lock",
    "scripts/deploy_*.sh",
    "scripts/*production_deploy*",
    "scripts/release_testflight.sh",
    "scripts/ExportOptions-TestFlight.plist",
    "backend/deploy/production_*",
    "tools/validate_xcresult.py",
    "tools/python_test_gate.py",
    "tools/verify_release_bundle.py",
    "tools/regression_guard.py",
    "tools/run_regression_gate.py",
    "tools/generate_development_history.py",
    "tools/production_*",
    "quality/regression_contracts.json",
    "quality/health_trust_contract.json",
    "quality/swift_source_manifest.json",
    "quality/expected_python_tests.json",
    "quality/expected_xctests.json",
    "quality/release_signoffs.example.json",
    "quality/testflight_signoffs.example.json",
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
    "backend/Dockerfile",
    "backend/requirements.lock",
    "scripts/*production_deploy*",
    "tools/production_*",
    ".github/workflows/*.yml",
    ".github/workflows/*.yaml",
    "tools/python_test_gate.py",
    "tools/validate_xcresult.py",
    "tools/regression_guard.py",
    "tools/run_regression_gate.py",
    "quality/regression_contracts.json",
    "quality/health_trust_contract.json",
    "quality/swift_source_manifest.json",
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
    "backend/requirements.lock",
    "backend/static/**",
    "backend/deploy/**",
    "backend/docker-compose*.yml",
    "backend/docker-compose*.yaml",
    "backend/compose*.yml",
    "backend/compose*.yaml",
    "scripts/deploy_*.sh",
    "scripts/*production_deploy*",
    "tools/production_*",
    "tools/xjie_dashboard_api.py",
}
MANDATORY_BACKEND_MIGRATION_SOURCE_PATTERNS = {
    "backend/app/db/migrations/versions/*.py",
}
MANDATORY_IOS_DIETARY_SOURCE_PATTERNS = {
    "Xjie/Xjie/Models/MealModels.swift",
    "Xjie/Xjie/ViewModels/MealsViewModel.swift",
    "Xjie/Xjie/Views/Meals/MealsView.swift",
}
MANDATORY_IOS_DIETARY_TEST_PATTERNS = {
    "Xjie/XjieTests/DietaryRecordsTests.swift",
}
MANDATORY_BACKEND_DIETARY_SOURCE_PATTERNS = {
    "backend/app/models/dietary_records.py",
    "backend/app/schemas/dietary_records.py",
    "backend/app/services/dietary_records_service.py",
    "backend/app/routers/dietary_records.py",
    "backend/app/workers/dietary_tasks.py",
}
MANDATORY_BACKEND_DIETARY_TEST_PATTERNS = {
    "backend/tests/unit/test_dietary_records_contract.py",
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
        "HEALTH-TRUST-001",
        "TEST-DETERMINISM-001",
    ),
    "ios_health_client": (
        "DATA-CARD-001",
        "HEALTH-REGISTRY-001",
        "HEALTH-ACCOUNT-001",
        "HEALTH-TRUST-001",
        "TEST-DETERMINISM-001",
    ),
    "ios_account_client": (
        "UX-FORM-001",
        "TEST-DETERMINISM-001",
    ),
    "ios_project_release": (
        "BRANCH-CANONICAL-001",
        "RELEASE-GATE-001",
    ),
    "ios_core": ("TEST-DETERMINISM-001",),
    "quality_process_gate": (
        "BRANCH-CANONICAL-001",
        "RELEASE-GATE-001",
        "PROCESS-GATE-001",
    ),
    "test_suite_integrity": ("TEST-SUITE-INTEGRITY-001",),
    "backend_chat_ai": (
        "CHAT-SESSION-001",
        "AI-SUBJECT-001",
        "AI-SAFETY-001",
        "AI-EVIDENCE-001",
        "HEALTH-TRUST-001",
        "MEDICATION-TRUST-001",
    ),
    "backend_health_sync": (
        "HEALTH-REGISTRY-001",
        "HEALTH-ACCOUNT-001",
        "HEALTH-TRUST-001",
        "MEDICATION-TRUST-001",
    ),
    "backend_core": ("BACKEND-CORE-001",),
}
PINNED_CONTRACT_DEFINITION_SHA256 = {
    "UX-NAV-001": "3d78f17eb28926992f98c2dbcd0c25c449f22140979ef5045629094fe64832fd",
    "UX-KEYBOARD-001": "311231cc1455f4f1916eed37ce0a76bc037706b01632b309444809d833492ac9",
    "UX-CHAT-QUIESCENCE-001": "6dcebe13349d85be28169791e6d3bee92ef6e7e7cfd5a8ef2e65133a94ebe455",
    "UX-ACCESSIBILITY-001": "18a95a3fdd76f0d396f39175eee7f7a2cee0023e37d04624ac708724dc473f29",
    "UX-FORM-001": "a511ba265be7d7470bd67fddb9fa88dc1b11cf8d572bddfb3854d11cd70f7738",
    "DATA-CARD-001": "cc0e768156f89a2a0f6f8a2a11c0acc58809b828ca57f86a59775095955dbc7c",
    "CHAT-SESSION-001": "ece8d46ff6261869f46a45cc0e19b7de8122971626028291f60997f9cd8540a2",
    "AI-SUBJECT-001": "ab439bbc57e438f4259adbd8f7cf01e118301569b301fc05ac909f2af550bb0d",
    "AI-SAFETY-001": "49f29f6b03b04a49984f1c0c40488eb214e4d99ddaa13bc15fb12466b2ba3d97",
    "AI-EVIDENCE-001": "acf45194fd9b8777cf6be0e6c89e791684fa5becbe93663484447be650c861bd",
    "HEALTH-REGISTRY-001": "5f38a4fc14b01e109a7abb7f9da4fd7b09aadf0068a6a9897d58927f7f5df636",
    "HEALTH-ACCOUNT-001": "44554c82ce660f13a5212d43ff84d80851b8896edadbd32e67e35828c19a6646",
    "HEALTH-TRUST-001": "be147364bf577b11c449ac4517f631d3f2503690bc3896aecd12f008ad2b0c0e",
    "MEDICATION-TRUST-001": "25afa18526f65ac299ac22be2c49e0ef856bc698c0053b002533f747d99f3ad3",
    "BACKEND-CORE-001": "156b0262c67540c90421c23d024bab07ff27ec47b85ce7cf95f39360dafe6266",
    "TEST-SUITE-INTEGRITY-001": "8a93bd9943750aa9fbe05ba08fc9c95f6590d211ce09eddcd548b0aceb280b78",
    "TEST-DETERMINISM-001": "d38d25d412739b96e098527aa07fe2810187b438e3065ceb5823a47763085d7c",
    "BRANCH-CANONICAL-001": "d56eac3bb366249fb61f98fd4d4e94f03699337b27010df20f7b150db5a4a145",
    "RELEASE-GATE-001": "287a76689de076de640d0ba3bb6633a0dcc7b986cd925ed81deb760af376725a",
    "PROCESS-GATE-001": "47e7358fbc2eb697bb5214931526994ee456df0129946041c4b56b176c3ad731",
}
PINNED_REGRESSION_REGISTRY_SHA256 = (
    "5e1475421d925c562602b6a3da870e3c8c433fea57f0ef7a2e05339e87b5b96d"
)
PINNED_HEALTH_TRUST_CONTRACT_SHA256 = (
    "7f1dde231dbc33d2f4dfd129fdf6288fae496a8f7cbf30b8f4d1266a8962221f"
)
PINNED_HEALTH_TRUST_CONTRACT_KEYS = (
    "schema_version",
    "contract_id",
    "contract_version",
    "authority",
    "report_workflow_states",
    "candidate_review_states",
    "profile_candidate_states",
    "observation_states",
    "profile_fact_states",
    "profile_confirmation_methods",
    "score_snapshot_states",
    "score_directions",
    "score_outcomes",
    "profile_response_states",
    "safety_fact_categories",
    "invariants",
    "required_provenance_edges",
    "profile_completeness",
    "legacy_migration",
    "xage_consumption",
)
PINNED_HEALTH_TRUST_ENUMS = {
    "report_workflow_states": (
        "draft",
        "uploading",
        "recognizing",
        "awaiting_confirmation",
        "committing",
        "completed",
        "completed_score_pending",
        "failed",
    ),
    "candidate_review_states": (
        "pending_review",
        "auto_accepted",
        "confirmed",
        "corrected",
        "rejected",
    ),
    "profile_candidate_states": (
        "pending_review",
        "accepted",
        "rejected",
        "superseded",
        "conflict",
    ),
    "observation_states": ("active", "superseded", "retracted"),
    "profile_fact_states": ("active", "superseded", "retracted"),
    "profile_confirmation_methods": (
        "user",
        "clinician",
        "verified_source",
        "automatic",
    ),
    "score_snapshot_states": ("pending", "completed", "failed"),
    "score_directions": (
        "higher_is_better",
        "lower_is_better",
        "target_range",
        "informational",
    ),
    "score_outcomes": ("improved", "worsened", "unchanged", "unknown"),
    "profile_response_states": (
        "value",
        "none",
        "not_applicable",
        "prefer_not_to_answer",
        "unknown",
    ),
    "safety_fact_categories": (
        "medication_allergy",
        "other_allergy",
        "contraindication",
        "pregnancy_or_breastfeeding",
        "major_surgery",
        "important_condition",
        "clinician_restriction",
    ),
}
PINNED_HEALTH_TRUST_INVARIANT_KEYS = (
    "raw_asset_is_immutable",
    "ocr_output_is_candidate_only",
    "high_confidence_normal_fields_may_auto_approve",
    "abnormal_low_confidence_or_conflicting_fields_require_review",
    "report_level_user_confirmation_is_required_before_admission",
    "candidate_correction_preserves_original_value",
    "admission_is_idempotent",
    "unadmitted_candidates_are_excluded_from_trends",
    "unadmitted_candidates_are_excluded_from_profile",
    "unadmitted_candidates_are_excluded_from_ai",
    "unadmitted_candidates_are_excluded_from_scores",
    "report_confirmation_and_profile_confirmation_are_separate",
    "profile_candidates_are_not_profile_facts",
    "safety_facts_never_auto_confirm",
    "confirmed_fact_edits_and_deletes_require_confirmation",
    "confirmed_fact_history_is_append_only",
    "conflicting_facts_never_silently_overwrite",
    "profile_completeness_is_not_health_quality",
    "profile_source_count_uses_independent_source_records",
    "score_delta_requires_semantic_outcome",
    "actual_score_impact_is_hidden_until_admission",
    "score_failure_does_not_roll_back_admission",
    "ai_consumes_confirmed_facts_and_admitted_observations_only",
    "xage_consumption_is_disabled_until_separately_validated",
    "every_derived_record_is_user_and_subject_scoped",
    "every_confirmation_has_an_idempotency_key",
    "provenance_chain_is_complete",
    "dietary_input_creates_candidate_only",
    "dietary_formal_record_requires_user_confirmation",
    "dietary_day_uses_local_0400_boundary",
    "dietary_summary_is_deterministic_without_llm",
    "dietary_records_are_tenant_scoped_and_idempotent",
)
PINNED_ARCHITECTURE_LIMITS = [
    {"swift_source_manifest": SWIFT_SOURCE_MANIFEST_REPO_PATH},
]
PINNED_SWIFT_SOURCE_MANIFEST_KEYS = (
    "schema_version",
    "source_root",
    "xcode_project",
    "sources",
    "aggregate_limits",
)
PINNED_SWIFT_SOURCE_ENTRY_KEYS = ("path", "role", "domains", "max_lines")
PINNED_SWIFT_AGGREGATE_LIMIT_KEYS = (
    "max_nonblank_nonimport_lines",
    "pattern_limits",
    "forbidden_patterns",
)
PINNED_SWIFT_PATTERN_LIMIT_KEYS = ("name", "pattern", "max_count")
PINNED_SWIFT_FORBIDDEN_PATTERN_KEYS = ("name", "pattern")
PINNED_SWIFT_SOURCE_ROOT = "Xjie/Xjie/Views/Home"
PINNED_SWIFT_XCODE_PROJECT = "Xjie/Xjie.xcodeproj/project.pbxproj"
PINNED_SWIFT_AGGREGATE_LOGICAL_LINES = 9548
PINNED_SWIFT_AGGREGATE_PATTERN_LIMITS = [
    {"name": "struct declarations", "pattern": r"\bstruct\s+[A-Za-z_]", "max_count": 100},
    {"name": "enum declarations", "pattern": r"\benum\s+[A-Za-z_]", "max_count": 17},
    {"name": "sheet presentations", "pattern": r"\.sheet\s*\(", "max_count": 19},
    {
        "name": "full-screen presentations",
        "pattern": r"\.fullScreenCover\s*\(",
        "max_count": 6,
    },
    {"name": "alerts", "pattern": r"\.alert\s*\(", "max_count": 20},
    {
        "name": "fixed presentation delays",
        "pattern": r"asyncAfter\s*\(",
        "max_count": 7,
    },
    {
        "name": "silenced API failures",
        "pattern": r"try\?\s+await\s+api\.",
        "max_count": 2,
    },
]
PINNED_SWIFT_FORBIDDEN_PATTERNS = [
    {"name": "legacy HomeView route", "pattern": r"\bHomeView\s*\("},
    {"name": "legacy ChatView route", "pattern": r"\bChatView\s*\("},
    {"name": "legacy SettingsView route", "pattern": r"\bSettingsView\s*\("},
    {
        "name": "legacy MedicationListView route",
        "pattern": r"\bMedicationListView\s*\(",
    },
]
PINNED_SWIFT_SOURCE_ROLE_DOMAINS = {
    "shared_contracts": (
        "ios_ui_interaction",
        "ios_chat_client",
        "ios_health_client",
        "ios_account_client",
    ),
    "root_shell": (
        "ios_ui_interaction",
        "ios_chat_client",
        "ios_health_client",
        "ios_account_client",
    ),
    "data_dashboard": ("ios_ui_interaction", "ios_health_client"),
    "conversation": ("ios_ui_interaction", "ios_chat_client"),
    "healthspan": ("ios_ui_interaction", "ios_health_client"),
    "settings": (
        "ios_ui_interaction",
        "ios_health_client",
        "ios_account_client",
    ),
    "shared_components": ("ios_ui_interaction",),
}
PINNED_SWIFT_SPLIT_ROLES = (
    "shared_contracts",
    "root_shell",
    "data_dashboard",
    "conversation",
    "healthspan",
    "settings",
    "shared_components",
)
PINNED_SWIFT_SOURCE_ROLE_MAX_LINES = {
    "shared_contracts": 800,
    "root_shell": 1200,
    "data_dashboard": 7000,
    "conversation": 1800,
    "healthspan": 800,
    "settings": 1500,
    "shared_components": 500,
}
SWIFT_IMPORT_DECLARATION_PATTERN = re.compile(
    r"^import(?:\s+(?:typealias|struct|class|enum|protocol|let|var|func))?"
    r"\s+[A-Za-z_][A-Za-z0-9_.]*$"
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


def _swift_declaration_body(
    source: str,
    declaration_pattern: str,
) -> tuple[str, str] | None:
    """Return the unique raw and masked body of one Swift declaration."""

    static = _swift_static_code(source)
    matches = list(re.finditer(declaration_pattern, static, flags=re.MULTILINE))
    if len(matches) != 1:
        return None
    opening = static.find("{", matches[0].end())
    if opening < 0:
        return None
    depth = 1
    for index in range(opening + 1, len(static)):
        if static[index] == "{":
            depth += 1
        elif static[index] == "}":
            depth -= 1
            if depth == 0:
                return source[opening + 1:index], static[opening + 1:index]
    return None


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


def swift_source_manifest_violations(
    manifest: dict[str, Any],
    *,
    source_contents: dict[str, str] | None = None,
) -> list[str]:
    """Validate the ordered XAGE source inventory and its aggregate budget."""

    violations: list[str] = []
    if tuple(manifest) != PINNED_SWIFT_SOURCE_MANIFEST_KEYS:
        violations.append(
            "swift_source_manifest.json keys and order must exactly match the pinned schema"
        )
    if type(manifest.get("schema_version")) is not int \
            or manifest.get("schema_version") != 1:
        violations.append("swift_source_manifest.json schema_version must be the integer 1")
    if manifest.get("source_root") != PINNED_SWIFT_SOURCE_ROOT:
        violations.append(
            "swift_source_manifest.json source_root must remain "
            + PINNED_SWIFT_SOURCE_ROOT
        )
    if manifest.get("xcode_project") != PINNED_SWIFT_XCODE_PROJECT:
        violations.append(
            "swift_source_manifest.json xcode_project must remain "
            + PINNED_SWIFT_XCODE_PROJECT
        )

    entries = manifest.get("sources")
    if not isinstance(entries, list) or not entries:
        violations.append("swift_source_manifest.json sources must be a non-empty list")
        entries = []

    paths: list[str] = []
    roles: list[str] = []
    contents: dict[str, str] = {}
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            violations.append(f"swift source entry {index} must be an object")
            continue
        if tuple(entry) != PINNED_SWIFT_SOURCE_ENTRY_KEYS:
            violations.append(
                f"swift source entry {index} keys and order must exactly match the pinned schema"
            )
        path = entry.get("path")
        role = entry.get("role")
        path_valid = isinstance(path, str)
        if path_valid:
            candidate = PurePosixPath(path)
            path_valid = (
                path == candidate.as_posix()
                and not candidate.is_absolute()
                and candidate.parent.as_posix() == PINNED_SWIFT_SOURCE_ROOT
                and re.fullmatch(r"XAge[A-Za-z0-9_]*\.swift", candidate.name) is not None
                and "\\" not in path
                and "\x00" not in path
                and all(part not in {"", ".", ".."} for part in candidate.parts)
                and all(
                    32 <= ord(character) != 127
                    for part in candidate.parts
                    for character in part
                )
            )
        if not path_valid:
            violations.append(
                f"swift source entry {index} path must be a normalized direct XAge*.swift child "
                f"of {PINNED_SWIFT_SOURCE_ROOT}"
            )
        else:
            paths.append(path)

        if not isinstance(role, str) or role not in PINNED_SWIFT_SOURCE_ROLE_DOMAINS:
            violations.append(f"swift source entry {index} has an unknown role: {role!r}")
        else:
            roles.append(role)
            domains = entry.get("domains")
            if not isinstance(domains, list) or tuple(domains) != PINNED_SWIFT_SOURCE_ROLE_DOMAINS[role]:
                violations.append(
                    f"swift source role {role} domains must exactly match the pinned ordered mapping"
                )
            max_lines = entry.get("max_lines")
            if type(max_lines) is not int \
                    or max_lines != PINNED_SWIFT_SOURCE_ROLE_MAX_LINES[role]:
                violations.append(
                    f"swift source role {role} max_lines must remain "
                    f"{PINNED_SWIFT_SOURCE_ROLE_MAX_LINES[role]}"
                )

    if len(paths) != len(set(paths)):
        violations.append("swift source manifest paths must be unique")
    if len(roles) != len(set(roles)):
        violations.append("swift source manifest roles must be unique")
    role_order = tuple(roles)
    if role_order != PINNED_SWIFT_SPLIT_ROLES:
        violations.append(
            "swift source roles must be the complete ordered split role set"
        )

    if source_contents is None:
        root = REPO_ROOT / PINNED_SWIFT_SOURCE_ROOT
        try:
            root_metadata = root.lstat()
        except FileNotFoundError:
            violations.append(
                "swift source manifest root does not exist: " + PINNED_SWIFT_SOURCE_ROOT
            )
            physical_paths: set[str] = set()
        else:
            if stat.S_ISLNK(root_metadata.st_mode) or not stat.S_ISDIR(root_metadata.st_mode):
                violations.append(
                    "swift source manifest root must be a real non-symlink directory: "
                    + PINNED_SWIFT_SOURCE_ROOT
                )
                physical_paths = set()
            else:
                physical_paths = {
                    candidate.relative_to(REPO_ROOT).as_posix()
                    for candidate in root.rglob("XAge*.swift")
                }
        for path in paths:
            target = REPO_ROOT / path
            try:
                metadata = target.lstat()
            except FileNotFoundError:
                violations.append(f"swift source manifest file does not exist: {path}")
                continue
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                violations.append(
                    f"swift source manifest file must be a regular non-symlink file: {path}"
                )
                continue
            try:
                contents[path] = target.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                violations.append(f"cannot read swift source manifest file {path}: {exc}")
    else:
        if not isinstance(source_contents, dict) or any(
            not isinstance(path, str) or not isinstance(content, str)
            for path, content in source_contents.items()
        ):
            violations.append("synthetic swift source contents must map paths to strings")
            physical_paths = set()
        else:
            physical_paths = set(source_contents)
            contents = dict(source_contents)

    manifest_paths = set(paths)
    if physical_paths != manifest_paths:
        missing = sorted(physical_paths - manifest_paths)
        foreign = sorted(manifest_paths - physical_paths)
        violations.append(
            "swift source manifest must exactly cover every Home XAge*.swift file; "
            f"missing={missing}, foreign={foreign}"
        )

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        path = entry.get("path")
        role = entry.get("role")
        content = contents.get(path) if isinstance(path, str) else None
        maximum = PINNED_SWIFT_SOURCE_ROLE_MAX_LINES.get(role) \
            if isinstance(role, str) else None
        if content is not None and maximum is not None:
            line_count = len(content.splitlines())
            if line_count > maximum:
                violations.append(
                    f"swift source per-file limit exceeded: {path} has {line_count} lines, "
                    f"max {maximum} for role {role}"
                )

    aggregate = manifest.get("aggregate_limits")
    if not isinstance(aggregate, dict):
        violations.append("swift_source_manifest.json aggregate_limits must be an object")
        aggregate = {}
    elif tuple(aggregate) != PINNED_SWIFT_AGGREGATE_LIMIT_KEYS:
        violations.append(
            "swift aggregate limit keys and order must exactly match the pinned schema"
        )
    if type(aggregate.get("max_nonblank_nonimport_lines")) is not int \
            or aggregate.get("max_nonblank_nonimport_lines") \
            != PINNED_SWIFT_AGGREGATE_LOGICAL_LINES:
        violations.append(
            "swift aggregate max_nonblank_nonimport_lines must remain "
            f"{PINNED_SWIFT_AGGREGATE_LOGICAL_LINES}"
        )
    if not _matches_pinned_json_value(
        aggregate.get("pattern_limits"), PINNED_SWIFT_AGGREGATE_PATTERN_LIMITS
    ):
        violations.append("swift aggregate pattern_limits must exactly match the pinned baseline")
    if not _matches_pinned_json_value(
        aggregate.get("forbidden_patterns"), PINNED_SWIFT_FORBIDDEN_PATTERNS
    ):
        violations.append(
            "swift aggregate forbidden_patterns must exactly match the pinned legacy-route set"
        )

    ordered_contents = [contents[path] for path in paths if path in contents]
    combined = "\n".join(ordered_contents)
    logical_lines = sum(
        bool(stripped) and SWIFT_IMPORT_DECLARATION_PATTERN.fullmatch(stripped) is None
        for content in ordered_contents
        for line in content.splitlines()
        for stripped in (line.strip(),)
    )
    if logical_lines > PINNED_SWIFT_AGGREGATE_LOGICAL_LINES:
        violations.append(
            "swift aggregate architecture limit exceeded: source manifest has "
            f"{logical_lines} nonblank non-import lines, max "
            f"{PINNED_SWIFT_AGGREGATE_LOGICAL_LINES}"
        )
    for pattern_limit in PINNED_SWIFT_AGGREGATE_PATTERN_LIMITS:
        count = len(re.findall(pattern_limit["pattern"], combined))
        maximum = pattern_limit["max_count"]
        if count > maximum:
            violations.append(
                "swift aggregate architecture limit exceeded: source manifest has "
                f"{count} {pattern_limit['name']}, max {maximum}"
            )
    for forbidden in PINNED_SWIFT_FORBIDDEN_PATTERNS:
        if re.search(forbidden["pattern"], combined):
            violations.append(
                "forbidden aggregate Swift architecture reference: " + forbidden["name"]
            )
    return violations


def trusted_score_presentation_violations(
    *, source_contents: dict[str, str] | None = None
) -> list[str]:
    """Keep local research scores disconnected from production score/XAge consumers."""

    paths = (
        TRUSTED_SCORE_POLICY_REPO_PATH,
        TRUSTED_SCORE_ROOT_REPO_PATH,
        TRUSTED_SCORE_DASHBOARD_REPO_PATH,
        TRUSTED_SCORE_XAGE_REPO_PATH,
    )
    contents: dict[str, str] = {}
    errors: list[str] = []
    for path in paths:
        if source_contents is not None:
            content = source_contents.get(path)
        else:
            try:
                content = (REPO_ROOT / path).read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                content = None
        if not isinstance(content, str):
            errors.append(f"trusted score production source is missing: {path}")
        else:
            contents[path] = content
    if errors:
        return errors

    policy = contents[TRUSTED_SCORE_POLICY_REPO_PATH]
    root = contents[TRUSTED_SCORE_ROOT_REPO_PATH]
    dashboard = contents[TRUSTED_SCORE_DASHBOARD_REPO_PATH]
    xage = contents[TRUSTED_SCORE_XAGE_REPO_PATH]
    normalized_policy = " ".join(policy.split())

    if policy.count('static let authority = "server"') != 1:
        errors.append("trusted score presentation authority must remain server")
    if policy.count("static let isXAgeConsumptionEnabled = false") != 1:
        errors.append("trusted score presentation must keep XAge consumption disabled")
    if "_ = localResearch return unavailable" not in normalized_policy \
            or re.search(r"return\s+localResearch(?:!|\b)", policy):
        errors.append("trusted score presentation must reject every local research result")
    if 'isTrustedForDisplay ? "\\(value)" : "--"' not in policy:
        errors.append("trusted score metric display must fail closed without a versioned snapshot")
    if 'var displayAge: String { isTrustedForDisplay ? age : "--" }' not in policy \
            or 'var displayDelta: String { isTrustedForDisplay ? delta : "尚未启用" }' not in policy:
        errors.append("trusted score XAge display must fail closed while disabled")
    if "isReady && serverSnapshotVersion != nil" not in policy:
        errors.append("trusted score display must require a server snapshot version")

    root_policy_call = "XAgeTrustedScorePresentationPolicy.currentPresentation()"
    if root.count(root_policy_call) != 1 \
            or "scores: compositeScores" not in root \
            or "XAgeCompositeScores.compute" in root \
            or "XAgeAlgorithmContext" in root:
        errors.append("XAge root must consume scores only through the trusted presentation policy")

    dashboard_ui = dashboard.partition("private struct XAgeScoreRing")[2]
    if not dashboard_ui \
            or "metric.isReady" in dashboard_ui \
            or "xage.score.trust.notice" not in dashboard_ui \
            or dashboard_ui.count("metric.isTrustedForDisplay") < 6:
        errors.append("dashboard score consumers must use only trusted display readiness")

    if xage.count(root_policy_call) != 1 \
            or any(token in xage for token in (
                "scores.xAge",
                "weekSnapshots",
                "chronologicalAge",
                "ageValue",
                "xage.week.previous",
                "xage.week.next",
            )) \
            or "等待版本化验证" not in xage \
            or "尚未启用" not in xage:
        errors.append("XAge view must remain disabled without local age, delta, pace, or weekly trends")
    return errors


def trusted_health_profile_client_violations(
    *, source_contents: dict[str, str] | None = None
) -> list[str]:
    """Keep health-profile facts server-authoritative and XAge consumption disabled."""

    paths = (
        TRUSTED_HEALTH_PROFILE_MODEL_REPO_PATH,
        TRUSTED_HEALTH_PROFILE_REPOSITORY_REPO_PATH,
        TRUSTED_HEALTH_PROFILE_VIEW_MODEL_REPO_PATH,
        TRUSTED_HEALTH_PROFILE_VIEW_REPO_PATH,
        TRUSTED_HEALTH_REPORT_INTERPRETATION_VIEW_REPO_PATH,
        TRUSTED_HEALTH_PROFILE_XAGE_REPO_PATH,
        TRUSTED_HEALTH_PROFILE_MORE_REPO_PATH,
    )
    contents: dict[str, str] = {}
    errors: list[str] = []
    for path in paths:
        if source_contents is not None:
            content = source_contents.get(path)
        else:
            try:
                content = (REPO_ROOT / path).read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                content = None
        if not isinstance(content, str):
            errors.append(f"trusted health-profile production source is missing: {path}")
        else:
            contents[path] = content
    if errors:
        return errors

    model = contents[TRUSTED_HEALTH_PROFILE_MODEL_REPO_PATH]
    repository = contents[TRUSTED_HEALTH_PROFILE_REPOSITORY_REPO_PATH]
    view_model = contents[TRUSTED_HEALTH_PROFILE_VIEW_MODEL_REPO_PATH]
    view = contents[TRUSTED_HEALTH_PROFILE_VIEW_REPO_PATH]
    report_interpretation = contents[
        TRUSTED_HEALTH_REPORT_INTERPRETATION_VIEW_REPO_PATH
    ]
    xage = contents[TRUSTED_HEALTH_PROFILE_XAGE_REPO_PATH]
    more = contents[TRUSTED_HEALTH_PROFILE_MORE_REPO_PATH]
    normalized_xage = " ".join(xage.split())

    required_profile_get_tokens = (
        'api.get("/api/health-data/profile-trust")',
        '"/api/medications/trust/long-term-summary?subject_user_id=\\(subjectUserID)"',
        '"/api/health-data/profile-trust/facts/\\(factID)/revisions"',
        '"/api/health-data/profile-trust/goals/\\(goalID)/revisions"',
        'query = ["subject_user_id=\\(subjectUserID)", "limit=50"]',
        'query.append("after_revision_id=\\(afterRevisionID)")',
    )
    if repository.count('api.get("/api/health-data/profile-trust")') != 1 \
            or repository.count("api.get(") != 4 \
            or "/patient-history" in repository \
            or any(token not in repository for token in required_profile_get_tokens):
        errors.append(
            "health-profile GETs must keep one subject-free canonical profile plus subject-bound medication and revision routes"
        )
    if repository.count("api.postAccountBound(") != 5 \
            or repository.count("api.patchAccountBound(") != 1 \
            or repository.count("expectedAccountScope: expectedAccountScope") != 6 \
            or not all(route in repository for route in (
                '"/api/health-data/profile-trust/candidates/\\(candidateID)/review"',
                '"/api/health-data/profile-trust/facts"',
                '"/api/health-data/profile-trust/facts/\\(factID)/retract"',
                '"/api/health-data/profile-trust/goals"',
                '"/api/health-data/profile-trust/goals/\\(goalID)"',
                '"/api/health-data/profile-trust/goals/\\(goalID)/status"',
            )):
        errors.append(
            "health-profile mutations must remain account-bound to the six versioned fact, candidate, and goal routes"
        )

    required_model_tokens = (
        "var isReviewable: Bool",
        "candidate_version: Int",
        "expected_version: Int?",
        "struct HealthProfileLongTermMedicationSummaryItem",
        "var displayFields: [HealthProfileMedicationSummaryDisplayField]",
    )
    medication_allowlist = model.partition("let allowedMedicationKeys")[2].partition("\n")[0]
    medication_summary_block = model.partition(
        "struct HealthProfileLongTermMedicationSummaryItem"
    )[2].partition("enum HealthProfileMedicationSummaryFieldKey")[0]
    required_medication_summary_fields = (
        ".init(key: .medicationName",
        ".init(key: .purpose",
        ".init(key: .startedOn",
        ".init(key: .isStillTaking",
        ".init(key: .source",
        ".init(key: .lastConfirmedAt",
    )
    if not all(token in model for token in required_model_tokens) \
            or '"dose"' in medication_allowlist \
            or medication_summary_block.count(".init(key:") != 6 \
            or any(
                token not in medication_summary_block
                for token in required_medication_summary_fields
            ):
        errors.append(
            "health-profile model must retain review versions and the exact six-field medication summary"
        )

    required_view_model_tokens = (
        "private var pendingMutation: PendingMutation?",
        "candidate.isReviewable",
        "!safetyConfirmed",
        "candidate.version",
        "expected_version: currentFact?.version",
        "expected_version: fact.version",
        "response.subject_user_id == subject",
        "currentAccountScope() == expected",
    )
    if any(token not in view_model for token in required_view_model_tokens) \
            or "UserDefaults" in view_model:
        errors.append(
            "health-profile view model must enforce versioned safety confirmation, idempotent retry, and account/subject isolation"
        )

    required_view_tokens = (
        "candidate.isReviewable",
        "confirmation = .candidate(candidate, .reject)",
        "confirmation = .candidate(candidate, .accept)",
        "ForEach(item.displayFields)",
        "MedicationListView()",
        "画像只展示已确认的必要摘要。剂量、提醒和服药操作请进入用药管理。",
        "X年龄暂不消费健康画像",
        "healthProfile.xage.notConsumed",
    )
    if not all(token in view for token in required_view_tokens):
        errors.append(
            "health-profile UI must keep explicit candidate decisions, medication summary-only display, and XAge disabled notice"
        )

    profile_pull_dismiss_contract = re.search(
        r'\.padding\(\.vertical,\s*12\)\s*'
        r'\.xAgeDismissKeyboardOnDownwardPull\(\s*'
        r'verificationIdentifier:\s*"healthProfile\.pullDismiss\.ready"\s*'
        r'\)\s*\{\s*editorFocused\s*=\s*false\s*\}',
        view,
        flags=re.DOTALL,
    )
    if profile_pull_dismiss_contract is None \
            or view.count(".xAgeDismissKeyboardOnDownwardPull(") != 1 \
            or view.count('"healthProfile.pullDismiss.ready"') != 1:
        errors.append(
            "health-profile scroll content must use the shared downward-pull keyboard contract and clear the page FocusState"
        )

    goal_started_on_focus_contract = re.search(
        r'\.keyboardType\(\.numbersAndPunctuation\)\s*'
        r'\.focused\(\$editorFocused\)\s*'
        r'\.accessibilityIdentifier\("healthProfile\.goal\.editor\.startedOn"\)',
        view,
    )
    if goal_started_on_focus_contract is None:
        errors.append(
            "health-profile goal start-date editor must bind the page FocusState after its numbers-and-punctuation keyboard type"
        )

    static_profile_section_sentinels = (
        r'Text\("持续更新的个人健康模型"\)\s*\.font\(\.headline\)\s*\.accessibilityIdentifier\("healthProfile\.overview"\)',
        r'Label\("候选更新",\s*systemImage:\s*"doc\.badge\.clock"\).*?\.accessibilityIdentifier\("healthProfile\.candidates"\)',
        r'Label\("完善画像资料",\s*systemImage:\s*"square\.and\.pencil"\)\s*\.font\(\.headline\)\s*\.accessibilityIdentifier\("healthProfile\.missing"\)',
        r'Label\("已确认画像事实",\s*systemImage:\s*"checkmark\.seal\.fill"\)\s*\.font\(\.headline\)\s*\.accessibilityIdentifier\("healthProfile\.facts"\)',
    )
    forbidden_profile_container_sentinel = re.search(
        r'\.cardStyle\(\)\s*\.accessibilityIdentifier\("healthProfile\.(?:overview|candidates|missing|facts)"\)',
        view,
    )
    required_profile_child_identifiers = (
        'accessibilityIdentifier("healthProfile.primaryAction")',
        r'accessibilityIdentifier("healthProfile.candidate.\(candidate.id).reject")',
        r'accessibilityIdentifier("healthProfile.candidate.\(candidate.id).accept")',
        r'accessibilityIdentifier("healthProfile.edit.\(definition.key)")',
        r'accessibilityIdentifier("healthProfile.fact.\(fact.id).edit")',
        r'accessibilityIdentifier("healthProfile.fact.\(fact.id).delete")',
        'accessibilityIdentifier("healthProfile.basic.derivedBMI")',
        'accessibilityIdentifier("healthProfile.medication.open")',
    )
    if any(re.search(pattern, view, flags=re.DOTALL) is None for pattern in static_profile_section_sentinels) \
            or forbidden_profile_container_sentinel \
            or any(identifier not in view for identifier in required_profile_child_identifiers):
        errors.append(
            "interactive health-profile sections must keep identifiers on static sentinels so child actions retain independent accessibility identities"
        )

    report_static_title_helper = re.search(
        r'private func sectionTitle\(\s*'
        r'_ title:\s*String,\s*icon:\s*String,\s*'
        r'staticTitleIdentifier:\s*String\?\s*\) -> some View\s*\{\s*'
        r'if let staticTitleIdentifier\s*\{\s*'
        r'Label\(title,\s*systemImage:\s*icon\).*?'
        r'\.accessibilityIdentifier\(staticTitleIdentifier\)\s*'
        r'\}\s*else\s*\{\s*Label\(title,\s*systemImage:\s*icon\).*?\}\s*\}',
        report_interpretation,
        flags=re.DOTALL,
    )
    required_report_static_title_sentinels = (
        r'Text\("本次报告解读"\).*?'
        r'\.accessibilityIdentifier\("xage\.report\.interpretation\.root"\)',
        r'sectionCard\(\s*title:\s*"健康画像候选",\s*'
        r'icon:\s*"person\.text\.rectangle\.fill",\s*'
        r'staticTitleIdentifier:\s*"xage\.report\.interpretation\.profile"\s*\)',
        r'sectionCard\(\s*title:\s*"识别、修正与确认记录",\s*'
        r'icon:\s*"point\.3\.connected\.trianglepath\.dotted",\s*'
        r'staticTitleIdentifier:\s*"xage\.report\.interpretation\.provenance"\s*\)',
        r'sectionCard\(\s*title:\s*"原始报告",\s*icon:\s*"doc\.richtext\.fill",\s*'
        r'staticTitleIdentifier:\s*"xage\.report\.interpretation\.original"\s*\)',
        r'sectionCard\(\s*title:\s*"原始报告",\s*icon:\s*"doc\.richtext\.fill",\s*'
        r'staticTitleIdentifier:\s*"xage\.report\.interpretation\.originalUnavailable"\s*\)',
    )
    forbidden_report_transparent_marker = (
        "accessibilityMarker(" in report_interpretation
        or re.search(
            r'Color\.clear.{0,320}(?:root|profile|provenance|original)',
            report_interpretation,
            flags=re.DOTALL,
        ) is not None
    )
    forbidden_report_section_container_identifier = re.search(
        r'\.accessibilityIdentifier\("xage\.report\.interpretation\.'
        r'(?:profile|provenance|original|originalUnavailable)"\)',
        report_interpretation,
    )
    if report_static_title_helper is None \
            or any(
                re.search(pattern, report_interpretation, flags=re.DOTALL) is None
                for pattern in required_report_static_title_sentinels
            ) \
            or report_interpretation.count(
                'accessibilityIdentifier("xage.report.interpretation.root")'
            ) != 1 \
            or report_interpretation.count(
                'accessibilityIdentifier("xage.report.interpretation.scroll")'
            ) != 1 \
            or forbidden_report_transparent_marker \
            or forbidden_report_section_container_identifier \
            or re.search(
                r'accessibilityIdentifier\(\s*'
                r'"xage\.report\.interpretation\.profileCandidate\.\\\(group\.id\)"\s*\)',
                report_interpretation,
            ) is None:
        errors.append(
            "report interpretation scroll targets must use visible static title sentinels without overwriting named descendants"
        )

    forbidden_fake_state = (
        "completedActionIDs",
        "selectedTagIDs",
        "primaryActionCount",
        "保存画像",
        "保存提醒",
        "整理到时间线",
        'Text(primaryActionCount > 0 ? "已更新" : "可编辑")',
        "private var profileContent",
    )
    if "if category == .profile { PatientHistoryView(onClose: onClose)" not in normalized_xage \
            or any(token in xage for token in forbidden_fake_state) \
            or "已停用本地模拟操作" not in xage:
        errors.append(
            "XAGE data entries must route to real server flows without local fake saving"
        )
    if "ForEach(XAgeDataPanelCategory.moreProfileCategories)" not in more \
            or "ForEach(XAgeDataPanelCategory.allCases)" in more:
        errors.append(
            "XAGE More data menu must source only the trusted health-profile entry"
        )
    return errors


def trusted_health_report_completion_client_violations(
    *, source_contents: dict[str, str] | None = None
) -> list[str]:
    """Keep ordered report upload and actionable page recovery fail closed."""

    paths = (
        TRUSTED_HEALTH_REPORT_COMPLETION_MODEL_REPO_PATH,
        TRUSTED_HEALTH_REPORT_COMPLETION_REPOSITORY_REPO_PATH,
        TRUSTED_HEALTH_REPORT_COMPLETION_VIEW_MODEL_REPO_PATH,
        TRUSTED_HEALTH_REPORT_CONVERSATION_REPO_PATH,
        TRUSTED_HEALTH_REPORT_DASHBOARD_REPO_PATH,
        TRUSTED_HEALTH_REPORT_ROOT_REPO_PATH,
    )
    contents: dict[str, str] = {}
    errors: list[str] = []
    for path in paths:
        if source_contents is not None:
            content = source_contents.get(path)
        else:
            try:
                content = (REPO_ROOT / path).read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                content = None
        if not isinstance(content, str):
            errors.append(f"trusted report-completion production source is missing: {path}")
        else:
            contents[path] = content
    if errors:
        return errors

    model = contents[TRUSTED_HEALTH_REPORT_COMPLETION_MODEL_REPO_PATH]
    repository = contents[TRUSTED_HEALTH_REPORT_COMPLETION_REPOSITORY_REPO_PATH]
    view_model = contents[TRUSTED_HEALTH_REPORT_COMPLETION_VIEW_MODEL_REPO_PATH]
    conversation = contents[TRUSTED_HEALTH_REPORT_CONVERSATION_REPO_PATH]
    dashboard = contents[TRUSTED_HEALTH_REPORT_DASHBOARD_REPO_PATH]
    root = contents[TRUSTED_HEALTH_REPORT_ROOT_REPO_PATH]

    upload_body = _swift_declaration_body(
        view_model,
        r"^\s*func\s+uploadReport\s*\(",
    )
    ordered_upload_valid = upload_body is not None
    if upload_body is not None:
        upload_raw, upload_static = upload_body
        ordered_tokens = (
            "let expectedPageCount = mediaKind == .pdf ? nil : files.count",
            "expected_page_count: expectedPageCount",
            "for (offset, input) in files.enumerated()",
            "assetIndex: offset + 1",
            r'clientAssetID: "\(requestID)-asset-\(offset + 1)"',
        )
        ordered_upload_valid = (
            all(token in upload_raw for token in ordered_tokens)
            and upload_static.count("repository.startUploadSession(") == 1
            and upload_static.count("repository.uploadAsset(") == 1
            and upload_static.count("repository.sealUploadSession(") == 1
            and len(re.findall(
                r"assetSetID\s*:\s*session\.asset_set_id",
                upload_static,
            )) == 3
            and upload_static.find("repository.startUploadSession(")
            < upload_static.find("files.enumerated()")
            < upload_static.find("repository.uploadAsset(")
            < upload_static.find("repository.sealUploadSession(")
            < upload_static.find("finishSeal(")
        )
    if not ordered_upload_valid:
        errors.append(
            "ordered initial report upload must create one asset set, preserve 1-based order, and seal that same set once"
        )

    repository_actor = repository.partition(
        "actor HealthReportCompletionRepository: HealthReportCompletionRepositoryProtocol"
    )[2]
    repository_recovery = _swift_declaration_body(
        repository_actor,
        r"^\s*func\s+recoverAsset\s*\(",
    )
    repository_seal = _swift_declaration_body(
        repository_actor,
        r"^\s*func\s+sealUploadSession\s*\(",
    )
    recovery_body = _swift_declaration_body(
        view_model,
        r"^\s*func\s+recoverReportAsset\s*\(",
    )
    finish_body = _swift_declaration_body(
        view_model,
        r"^\s*private\s+func\s+finishSeal\s*\(",
    )
    abandon_body = _swift_declaration_body(
        view_model,
        r"^\s*func\s+abandonUploadRecovery\s*\(",
    )
    account_change_body = _swift_declaration_body(
        view_model,
        r"^\s*func\s+accountDidChange\s*\(",
    )
    next_asset_index_body = _swift_declaration_body(
        view_model,
        r"^\s*var\s+nextAssetIndex\s*:\s*Int\?\s*",
    )

    recovery_valid = all(
        item is not None
        for item in (
            repository_recovery,
            repository_seal,
            recovery_body,
            finish_body,
            abandon_body,
            account_change_body,
            next_asset_index_body,
        )
    )
    required_model_tokens = (
        "let recovery_action: String?",
        "let problem_asset_indices: [Int]?",
        "let missing_page_indices: [Int]?",
        "let workflow_version: Int?",
        "let primary_action: HealthReportPrimaryAction?",
    )
    recovery_valid = recovery_valid and all(token in model for token in required_model_tokens)
    recovery_valid = recovery_valid and "extension APIService:" not in repository
    recovery_valid = recovery_valid and all(token in repository for token in (
        "private struct HealthReportCompletionAPITransport: HealthReportCompletionTransport",
        "let base: any APIServiceProtocol",
        "HealthReportCompletionAPITransport(base: APIService.shared)",
    ))
    if next_asset_index_body is not None:
        _, next_asset_index_static = next_asset_index_body
        recovery_valid = recovery_valid and (
            "missingPageIndices.first ?? problemAssetIndices.first"
            in next_asset_index_static
        )

    if repository_recovery is not None:
        recovery_repo_raw, recovery_repo_static = repository_recovery
        recovery_valid = recovery_valid and all(token in recovery_repo_raw for token in (
            r'"/api/health-data/report-upload-sessions/\(assetSetID)/assets/\(assetIndex)/replacement"',
            '"subject_user_id": String(subjectUserID)',
            '"client_asset_id": clientAssetID',
        ))
        recovery_valid = (
            recovery_valid
            and recovery_repo_static.count("transport.putFileAccountBound(") == 1
            and "expectedAccountScope: expectedAccountScope" in recovery_repo_static
        )
    if repository_seal is not None:
        seal_repo_raw, seal_repo_static = repository_seal
        recovery_valid = recovery_valid and (
            r'"/api/health-data/report-upload-sessions/\(assetSetID)/seal"'
            in seal_repo_raw
            and seal_repo_static.count("transport.postAccountBound(") == 1
            and "expectedAccountScope: expectedAccountScope" in seal_repo_static
        )
    if recovery_body is not None:
        recovery_raw, recovery_static = recovery_body
        recovery_order = tuple(
            recovery_static.find(token)
            for token in (
                "repository.recoverAsset(",
                "repository.sealUploadSession(",
                "finishSeal(",
            )
        )
        recovery_valid = recovery_valid and all(token in recovery_static for token in (
            "recovery.nextAssetIndex == assetIndex",
            "recovery.problemAssetIndices.contains(assetIndex)",
            "recovery.missingPageIndices.contains(assetIndex)",
            "context.assetSetID == recovery.assetSetID",
            "currentAccountScope() == context.accountScope",
            "assetSetID: context.assetSetID",
            "assetIndex: assetIndex",
            "subjectUserID: context.subjectUserID",
            "request: context.sealRequest",
            "expectedAccountScope: context.accountScope",
            "Self.recoveryClientAssetID(",
            "requestID: context.clientRequestID",
        ))
        recovery_valid = (
            recovery_valid
            and "repository.startUploadSession(" not in recovery_static
            and "repository.uploadAsset(" not in recovery_static
            and recovery_static.count("repository.recoverAsset(") == 1
            and recovery_static.count("repository.sealUploadSession(") == 1
            and recovery_static.count("assetSetID: context.assetSetID") == 2
            and recovery_static.count("assetIndex: assetIndex") == 2
            and recovery_static.count(
                "expectedAccountScope: context.accountScope"
            ) == 2
            and -1 not in recovery_order
            and recovery_order == tuple(sorted(recovery_order))
            and r'clientAssetID: "recovery-\(makeID())"' not in recovery_raw
        )
    if finish_body is not None:
        _, finish_static = finish_body
        failure_position = finish_static.find("seal.failure_code")
        apply_position = finish_static.find("applyPreWorkflowFailure(")
        workflow_position = finish_static.find("seal.workflow_id")
        runtime_position = finish_static.find("repository.fetchRuntime(")
        recovery_valid = recovery_valid and (
            -1 not in (failure_position, apply_position, workflow_position, runtime_position)
            and failure_position < apply_position < workflow_position < runtime_position
            and "if let failureCode = seal.failure_code" in finish_static
            and re.search(
                r"applyPreWorkflowFailure\([^}]+return\s+nil",
                finish_static,
                flags=re.DOTALL,
            ) is not None
        )
    for body in (abandon_body, account_change_body):
        if body is not None:
            _, body_static = body
            recovery_valid = recovery_valid and all(token in body_static for token in (
                "uploadRecovery = nil",
                "pendingRecoveryContext = nil",
            ))
    if not recovery_valid:
        errors.append(
            "report recovery must use the server-selected index on the same rejected asset set, account-bound replacement PUT, then reseal before any workflow"
        )

    runtime_body = _swift_declaration_body(
        view_model,
        r"^\s*private\s+func\s+applyRuntime\s*\(",
    )
    duplicate_body = _swift_declaration_body(
        view_model,
        r"^\s*func\s+decideDuplicate\s*\(",
    )
    server_runtime_valid = runtime_body is not None and duplicate_body is not None
    if runtime_body is not None:
        _, runtime_static = runtime_body
        server_runtime_valid = server_runtime_valid and all(token in runtime_static for token in (
            "switch runtime.primary_action?.code",
            "let version = runtime.workflow_version",
            "workflowVersion: version",
        ))
    if duplicate_body is not None:
        _, duplicate_static = duplicate_body
        server_runtime_valid = server_runtime_valid and (
            "workflow_version: prompt.workflowVersion" in duplicate_static
        )
    if not server_runtime_valid:
        errors.append(
            "report workflow action and duplicate version must remain server-owned"
        )

    conversation_decl = _swift_declaration_body(
        conversation,
        r"^\s*struct\s+XAgeConversationSurface\s*:\s*View\b",
    )
    dashboard_decl = _swift_declaration_body(
        dashboard,
        r"^\s*struct\s+XAgePanelDestinationView\s*:\s*View\b",
    )
    entries_valid = conversation_decl is not None and dashboard_decl is not None
    for declaration in (conversation_decl, dashboard_decl):
        if declaration is None:
            continue
        entry_raw, entry_static = declaration
        prepare_body = _swift_declaration_body(
            entry_raw,
            r"^\s*private\s+func\s+preparePendingReportUpload\s*\(",
        )
        begin_body = _swift_declaration_body(
            entry_raw,
            r"^\s*private\s+func\s+beginReportRecovery\s*\(",
        )
        entries_valid = entries_valid and prepare_body is not None and begin_body is not None
        entries_valid = entries_valid and all(token in entry_raw for token in (
            "selectionLimit: recoveryAssetIndex == nil ? 9 : 1",
            "let index = recovery.nextAssetIndex",
            "beginReportRecovery(assetIndex: index, useCamera: true)",
            "beginReportRecovery(assetIndex: index, useCamera: false)",
            "reportUploadVM.abandonUploadRecovery()",
        ))
        if prepare_body is not None:
            _, prepare_static = prepare_body
            entries_valid = entries_valid and all(token in prepare_static for token in (
                "if let assetIndex = recoveryAssetIndex",
                "files.count == 1",
                "reportUploadVM.recoverReportAsset(",
                "assetIndex: assetIndex",
            ))
        if begin_body is not None:
            _, begin_static = begin_body
            entries_valid = entries_valid and all(token in begin_static for token in (
                "recoveryAssetIndex = assetIndex",
                "if useCamera",
                "showCamera = true",
                "showPhotoLibrary = true",
            ))
        entries_valid = entries_valid and entry_static.count(
            "reportUploadVM.recoverReportAsset("
        ) == 1
    entries_valid = entries_valid and re.search(
        r"if\s+externalReportUploadVM\.uploadRecovery\s*!=\s*nil\s*\{"
        r"[\s\S]{0,300}?externalReportUploadVM\.abandonUploadRecovery\(\)\s*"
        r"selectedDataPanelCategory\s*=\s*\.reports\s*"
        r"selectedSection\s*=\s*\.data\s*"
        r'presentedQuickActionID\s*=\s*"reports"',
        root,
    ) is not None
    if not entries_valid:
        errors.append(
            "every iOS report entry point must either recover exactly one server-selected page or explicitly restart in the report panel"
        )
    return errors


def trusted_medication_accessibility_violations(
    *, source_contents: dict[str, str] | None = None
) -> list[str]:
    """Keep expandable medication controls independently addressable by AX."""

    paths = (
        TRUSTED_MEDICATION_MANAGEMENT_VIEW_REPO_PATH,
        TRUSTED_MEDICATION_REMINDER_VIEW_REPO_PATH,
        XAGE_INTERACTION_CONTRACTS_REPO_PATH,
    )
    contents: dict[str, str] = {}
    errors: list[str] = []
    for path in paths:
        if source_contents is not None:
            content = source_contents.get(path)
        else:
            try:
                content = (REPO_ROOT / path).read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                content = None
        if not isinstance(content, str):
            errors.append(f"trusted medication accessibility source is missing: {path}")
        else:
            contents[path] = content
    if errors:
        return errors

    management = contents[TRUSTED_MEDICATION_MANAGEMENT_VIEW_REPO_PATH]
    reminder = contents[TRUSTED_MEDICATION_REMINDER_VIEW_REPO_PATH]
    interaction_contracts = contents[XAGE_INTERACTION_CONTRACTS_REPO_PATH]
    plan_card = management.partition("private struct XAgeMedicationPlanCard")[2].partition(
        "private struct XAgeMedicationDoseRecordRow"
    )[0]
    plan_toggle_identifier = (
        'accessibilityIdentifier("xage.medication.plan.\\(plan.plan_id)")'
    )
    required_plan_child_identifiers = (
        'accessibilityIdentifier("xage.medication.reminder.open.\\(plan.plan_id)")',
        'accessibilityIdentifier("xage.medication.plan.edit.\\(plan.plan_id)")',
        'accessibilityIdentifier("xage.medication.plan.status.\\(plan.plan_id)")',
        'accessibilityIdentifier("xage.medication.plan.more.\\(plan.plan_id)")',
    )
    leaf_toggle = re.search(
        r'Button\s*\{.*?isExpanded\.toggle\(\).*?\}\s*label:\s*\{.*?\}\s*'
        r'\.buttonStyle\(\.plain\)\s*'
        r'\.accessibilityIdentifier\("xage\.medication\.plan\.\\\(plan\.plan_id\)"\)',
        plan_card,
        flags=re.DOTALL,
    )
    forbidden_container_identifier = re.search(
        r'\.background\(Color\.white\.opacity\(0\.42\),\s*in:\s*'
        r'RoundedRectangle\(cornerRadius:\s*18\)\)\s*'
        r'\.accessibilityIdentifier\("xage\.medication\.plan\.\\\(plan\.plan_id\)"\)',
        plan_card,
    )
    if not plan_card \
            or "DisclosureGroup" in plan_card \
            or "@State private var isExpanded = false" not in plan_card \
            or "if isExpanded" not in plan_card \
            or leaf_toggle is None \
            or plan_card.count(plan_toggle_identifier) != 1 \
            or forbidden_container_identifier is not None \
            or any(identifier not in plan_card for identifier in required_plan_child_identifiers):
        errors.append(
            "interactive medication plan cards must keep the plan toggle identifier on a leaf header button and preserve independent child action identities"
        )

    required_reminder_identifiers = (
        'accessibilityIdentifier("xage.medication.reminder.root")',
        'accessibilityIdentifier("xage.medication.reminder.close")',
        'accessibilityIdentifier("xage.medication.reminder.openSettings")',
        'accessibilityIdentifier("xage.medication.reminder.enabled")',
        'accessibilityIdentifier("xage.medication.reminder.times")',
        'accessibilityIdentifier("xage.medication.reminder.save")',
    )
    if reminder.count(required_reminder_identifiers[0]) != 1 \
            or any(identifier not in reminder for identifier in required_reminder_identifiers[1:]):
        errors.append(
            "medication reminder sheet must preserve independent root, close, permission, field, and save accessibility identities"
        )

    plan_editor = management.partition("private struct XAgeMedicationPlanEditor")[2].partition(
        "// MARK: - OCR text intake"
    )[0]
    recognition_editor = management.partition(
        "private struct XAgeMedicationRecognitionSheet"
    )[2].partition("// MARK: - Dose action sheets")[0]
    shared_sheet = management.partition(
        "private struct XAgeMedicationSheetContainer"
    )[2].partition("private struct XAgeMedicationCompactButtonStyle")[0]
    pull_dismiss_patterns = (
        (
            plan_editor,
            r'\.padding\(20\)\s*\.xAgeDismissKeyboardOnDownwardPull\s*\{\s*'
            r'focusedField\s*=\s*nil',
        ),
        (
            recognition_editor,
            r'\.padding\(20\)\s*\.xAgeDismissKeyboardOnDownwardPull\s*\{\s*'
            r'focused\s*=\s*false',
        ),
        (
            shared_sheet,
            r'\.padding\(20\)\s*\.xAgeDismissKeyboardOnDownwardPull\s*\{\s*'
            r'onKeyboardDismiss\(\)',
        ),
        (
            reminder,
            r'\.padding\(20\)\s*\.xAgeDismissKeyboardOnDownwardPull\(\s*'
            r'verificationIdentifier:\s*"xage\.medication\.reminder\.pullDismiss\.ready"\s*'
            r'\)\s*\{\s*timeFocused\s*=\s*false',
        ),
    )
    try:
        keyboard_helper_start = interaction_contracts.index(
            "struct XAgeVerticalKeyboardDismissInstaller"
        )
        keyboard_helper_end = interaction_contracts.index(
            "struct XAgeDataCardPreferenceSnapshot",
            keyboard_helper_start,
        )
        keyboard_helper = interaction_contracts[
            keyboard_helper_start:keyboard_helper_end
        ]
        modifier_start = keyboard_helper.index(
            "private struct XAgeDownwardKeyboardDismissModifier"
        )
        modifier = keyboard_helper[modifier_start:]
    except ValueError:
        keyboard_helper = ""
        modifier = ""
    required_pull_helper_tokens = (
        "private struct XAgeDownwardKeyboardDismissModifier: ViewModifier",
        "XAgeVerticalKeyboardDismissInstaller",
        "gesture.cancelsTouchesInView = false",
        "gesture.delegate = self",
        "func gestureRecognizerShouldBegin(_ gestureRecognizer: UIGestureRecognizer) -> Bool",
        "let velocity = pan.velocity(in: pan.view)",
        "return velocity.y > 0 && abs(velocity.y) > abs(velocity.x) * 1.2",
        "shouldRecognizeSimultaneouslyWith otherGestureRecognizer: UIGestureRecognizer",
        "scrollView.addGestureRecognizer(self.panGesture)",
        "gesture.translation(in: gesture.view).y > 20",
        "let verificationIdentifier: String?",
        ".accessibilityIdentifier(verificationIdentifier)",
        "onDismiss()",
        "XAgeKeyboard.dismiss()",
        "func xAgeDismissKeyboardOnDownwardPull(",
    )
    simultaneous_recognition_contract = re.search(
        r'func gestureRecognizer\(\s*'
        r'_ gestureRecognizer:\s*UIGestureRecognizer,\s*'
        r'shouldRecognizeSimultaneouslyWith otherGestureRecognizer:\s*UIGestureRecognizer\s*'
        r'\) -> Bool\s*\{\s*true\s*\}',
        keyboard_helper,
        flags=re.DOTALL,
    )
    required_sheet_focus_consumers = (
        "onKeyboardDismiss: { focused = false }",
        "onKeyboardDismiss: { focused = nil }",
    )
    if any(re.search(pattern, source, flags=re.DOTALL) is None for source, pattern in pull_dismiss_patterns) \
            or any(token not in keyboard_helper for token in required_pull_helper_tokens) \
            or simultaneous_recognition_contract is None \
            or ".simultaneousGesture(" in modifier \
            or "DragGesture(" in modifier \
            or management.count(required_sheet_focus_consumers[0]) != 2 \
            or management.count(required_sheet_focus_consumers[1]) != 1:
        errors.append(
            "medication text editors must use the shared UIKit-only downward-pull keyboard contract without blocking native scrolling across reminder, plan, OCR, and sheet entry points"
        )
    return errors


def swift_source_layout_violations(
    swift_paths: set[str],
    project_source: str,
    *,
    required_app_sources: tuple[str, ...] = (),
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
        if phase_id == "F10002" and required_app_sources:
            incorrect = sorted(
                path for path in required_app_sources if actual_paths.count(path) != 1
            )
            if incorrect:
                violations.append(
                    "XAGE Swift source manifest entries must each be compiled exactly once by "
                    f"the app source phase: {incorrect}"
                )
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


def _load_strict_ordered_json(path: Path) -> dict[str, Any]:
    """Load security-sensitive JSON without duplicate keys or non-JSON constants."""

    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise GuardError(f"missing required file: {path}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise GuardError(f"required JSON must be a regular non-symlink file: {path}")

    def ordered_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise GuardError(f"duplicate JSON key in {path}: {key}")
            value[key] = item
        return value

    def invalid_constant(value: str) -> None:
        raise GuardError(f"invalid JSON constant in {path}: {value}")

    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=ordered_object,
            parse_constant=invalid_constant,
        )
    except (OSError, UnicodeError) as exc:
        raise GuardError(f"cannot read required JSON {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise GuardError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise GuardError(f"top-level JSON must be an object: {path}")
    return value


def load_registry() -> dict[str, Any]:
    return _load_json(REGISTRY_PATH)


def load_manifest() -> dict[str, Any]:
    return _load_json(MANIFEST_PATH)


def load_swift_source_manifest() -> dict[str, Any]:
    return _load_strict_ordered_json(SWIFT_SOURCE_MANIFEST_PATH)


def load_health_trust_contract() -> dict[str, Any]:
    return _load_strict_ordered_json(HEALTH_TRUST_CONTRACT_PATH)


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


def _matches_pinned_json_value(actual: Any, expected: Any) -> bool:
    """Require exact JSON types, values, member order and nested key order."""

    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return tuple(actual) == tuple(expected) and all(
            _matches_pinned_json_value(actual[key], expected[key])
            for key in expected
        )
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(
            _matches_pinned_json_value(actual_item, expected_item)
            for actual_item, expected_item in zip(actual, expected)
        )
    return actual == expected


def health_trust_contract_violations(contract: dict[str, Any]) -> list[str]:
    """Reject any weakening or ambiguity in the trusted-health admission boundary."""

    errors: list[str] = []
    normalized = json.dumps(
        contract,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if hashlib.sha256(normalized).hexdigest() != PINNED_HEALTH_TRUST_CONTRACT_SHA256:
        errors.append(
            "health_trust_contract.json normalized definition changed from the pinned digest"
        )
    if tuple(contract) != PINNED_HEALTH_TRUST_CONTRACT_KEYS:
        errors.append(
            "health_trust_contract.json keys and order must exactly match the pinned schema"
        )
    if type(contract.get("schema_version")) is not int or contract.get("schema_version") != 1:
        errors.append("health_trust_contract.json schema_version must be the integer 1")
    for field, expected in (
        ("contract_id", "HEALTH-TRUST-001"),
        ("contract_version", "health-trust.v1"),
        ("authority", "server"),
    ):
        if type(contract.get(field)) is not str or contract.get(field) != expected:
            errors.append(f"health_trust_contract.json {field} must remain {expected!r}")

    for field, expected in PINNED_HEALTH_TRUST_ENUMS.items():
        actual = contract.get(field)
        if not isinstance(actual, list) or tuple(actual) != expected:
            errors.append(
                f"health_trust_contract.json {field} changed from the pinned ordered values"
            )

    invariants = contract.get("invariants")
    if not isinstance(invariants, dict) or tuple(invariants) != PINNED_HEALTH_TRUST_INVARIANT_KEYS:
        errors.append(
            "health_trust_contract.json invariants must exactly match the pinned ordered set"
        )
    elif any(value is not True for value in invariants.values()):
        errors.append("health_trust_contract.json every invariant must be the boolean true")

    expected_edges = (
        "report_asset->report_field_candidate",
        "report_field_candidate->confirmation_event",
        "report_level_confirmation->admitted_observation",
        "confirmation_event->admitted_observation",
        "admitted_observation->score_snapshot",
        "admitted_observation->profile_candidate",
        "profile_candidate->profile_confirmation_event",
        "profile_confirmation_event->profile_fact",
        "dietary_input->dietary_draft",
        "dietary_draft->dietary_confirmation_event",
        "dietary_confirmation_event->dietary_record",
        "dietary_record->dietary_daily_summary",
    )
    edges = contract.get("required_provenance_edges")
    if not isinstance(edges, list) or tuple(edges) != expected_edges:
        errors.append(
            "health_trust_contract.json provenance chain changed from the pinned ordered edges"
        )

    expected_completeness = {
        "canonical_owner": "server",
        "resolved_states": [
            "value",
            "none",
            "not_applicable",
            "prefer_not_to_answer",
        ],
        "unresolved_states": ["unknown"],
        "formula": "100 * resolved_required_weight / total_required_weight",
        "rounding": "nearest_integer",
    }
    if not _matches_pinned_json_value(
        contract.get("profile_completeness"), expected_completeness
    ):
        errors.append(
            "health_trust_contract.json profile completeness semantics changed"
        )

    expected_legacy = {
        "ocr_or_import_without_confirmation": "legacy_unverified",
        "legacy_unverified_is_admitted": False,
        "explicit_user_saved_profile_value": "confirmed_with_legacy_provenance",
        "ambiguous_safety_fact": "pending_confirmation",
    }
    if not _matches_pinned_json_value(contract.get("legacy_migration"), expected_legacy):
        errors.append("health_trust_contract.json legacy admission policy changed")

    expected_xage = {
        "enabled": False,
        "required_before_enablement": [
            "versioned_field_mapping",
            "versioned_weights",
            "direction_contract",
            "validation_dataset",
            "acceptance_thresholds",
            "rollback_plan",
        ],
    }
    if not _matches_pinned_json_value(contract.get("xage_consumption"), expected_xage):
        errors.append("health_trust_contract.json XAge enablement boundary changed")
    return errors


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
        health_trust_contract = load_health_trust_contract()
    except GuardError as exc:
        errors.append(str(exc))
    else:
        errors.extend(health_trust_contract_violations(health_trust_contract))
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
    if type(registry.get("schema_version")) is not int or registry["schema_version"] != 3:
        errors.append("regression_contracts.json schema_version must be the integer 3")

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

    ios_health_domain = next(
        (
            item
            for item in domains
            if isinstance(item, dict) and item.get("id") == "ios_health_client"
        ),
        None,
    )
    if ios_health_domain is None:
        errors.append("mandatory ios_health_client domain is missing")
    else:
        missing_sources = MANDATORY_IOS_DIETARY_SOURCE_PATTERNS - set(
            ios_health_domain.get("source_patterns", [])
        )
        missing_tests = MANDATORY_IOS_DIETARY_TEST_PATTERNS - set(
            ios_health_domain.get("test_patterns", [])
        )
        if missing_sources or missing_tests:
            errors.append(
                "ios_health_client is missing dietary source/test patterns: "
                + ", ".join(sorted(missing_sources | missing_tests))
            )

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
        source_patterns = set(backend_health_domain.get("source_patterns", []))
        test_patterns = set(backend_health_domain.get("test_patterns", []))
        missing_patterns = (
            MANDATORY_BACKEND_MIGRATION_SOURCE_PATTERNS
            | MANDATORY_BACKEND_DIETARY_SOURCE_PATTERNS
        ) - source_patterns
        missing_tests = MANDATORY_BACKEND_DIETARY_TEST_PATTERNS - test_patterns
        if missing_tests:
            missing_patterns |= missing_tests
        if missing_patterns:
            errors.append(
                "backend_health_sync is missing migration/dietary source/test patterns: "
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

    if not _matches_pinned_json_value(
        registry.get("architecture_limits"), PINNED_ARCHITECTURE_LIMITS
    ):
        errors.append(
            "architecture_limits must delegate exactly to quality/swift_source_manifest.json"
        )
    swift_manifest_paths: tuple[str, ...] = ()
    try:
        swift_source_manifest = load_swift_source_manifest()
    except GuardError as exc:
        errors.append(str(exc))
    else:
        swift_manifest_errors = swift_source_manifest_violations(swift_source_manifest)
        errors.extend(swift_manifest_errors)
        if not swift_manifest_errors:
            swift_manifest_paths = tuple(
                entry["path"] for entry in swift_source_manifest["sources"]
            )
    errors.extend(trusted_score_presentation_violations())
    errors.extend(trusted_health_profile_client_violations())
    errors.extend(trusted_health_report_completion_client_violations())
    errors.extend(trusted_medication_accessibility_violations())

    release_gate = registry.get("release_gate")
    if not isinstance(release_gate, dict):
        errors.append("release_gate must be an object")
    else:
        if tuple(release_gate) != PINNED_RELEASE_GATE_KEYS:
            errors.append(
                "release_gate keys and order must exactly match the pinned schema"
            )
        pinned_identity = {
            "github_repository": PINNED_GITHUB_REPOSITORY,
            "github_workflow": PINNED_GITHUB_WORKFLOW,
            "required_check": PINNED_REQUIRED_CHECK,
            "max_age_hours": PINNED_MAX_AGE_HOURS,
            "testflight_signoff_max_age_hours": (
                PINNED_TESTFLIGHT_SIGNOFF_MAX_AGE_HOURS
            ),
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
        if not _matches_pinned_json_value(branch_protection, PINNED_BRANCH_PROTECTION):
            errors.append("release_gate branch_protection must exactly enforce the pinned PR workflow")
        branch_roles = release_gate.get("branch_roles")
        if not _matches_pinned_json_value(branch_roles, PINNED_BRANCH_ROLES):
            errors.append(
                "release_gate branch_roles must exactly define canonical main and locked read-only XAGE"
            )
        pending = release_gate.get("pending_internal_candidate")
        if pending is None:
            # Null is the only idle state. Reaching it requires changing the pinned
            # registry digest through the same protected-main PR contract as any
            # other release-policy transition; local evidence cannot clear it.
            pass
        elif not isinstance(pending, dict) or tuple(pending) != PENDING_INTERNAL_CANDIDATE_KEYS:
            errors.append(
                "release_gate pending_internal_candidate must be null or match the exact tracked receipt schema"
            )
        else:
            for field in ("head", "tree", "registry_blob"):
                if re.fullmatch(r"[0-9a-f]{40}", str(pending.get(field, ""))) is None:
                    errors.append(f"pending internal candidate requires a lowercase SHA-1 {field}")
            if pending.get("schema_version") != 1 \
                    or pending.get("status") != "uploaded_pending_qualification":
                errors.append("pending internal candidate must use schema 1 and remain pending qualification")
            if re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", str(pending.get("app_version", ""))) is None \
                    or pending.get("app_build") != str(PINNED_LATEST_UPLOADED_BUILD):
                errors.append("pending internal candidate version/build must identify latest_uploaded_build")
            if pending.get("app_build") == "18" and not _matches_pinned_json_value(
                pending, PINNED_HISTORICAL_BUILD_18_PENDING
            ):
                errors.append(
                    "historical build 18 pending identity must remain exact and internal-only"
                )
            try:
                uploaded_at = dt.datetime.fromisoformat(
                    str(pending.get("uploaded_at", "")).replace("Z", "+00:00")
                )
            except ValueError:
                uploaded_at = None
            if uploaded_at is None or uploaded_at.tzinfo is None \
                    or uploaded_at.utcoffset() is None:
                errors.append("pending internal candidate uploaded_at must include a timezone")
            if pending.get("installation_source") != "TestFlight" \
                    or pending.get("external_promotion_allowed") is not False:
                errors.append(
                    "pending internal candidate must require TestFlight and fail closed for external promotion"
                )
            upload = pending.get("upload")
            if not isinstance(upload, dict):
                errors.append("pending internal candidate upload receipt must be an object")
            elif upload.get("method") == "xcode_destination_upload":
                if tuple(upload) != HISTORICAL_XCODE_UPLOAD_KEYS:
                    errors.append("historical Xcode upload receipt schema is invalid")
                for field in ("distribution_identifier", "provider_id"):
                    if re.fullmatch(
                        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
                        str(upload.get(field, "")),
                    ) is None:
                        errors.append(f"historical Xcode upload {field} is invalid")
                if re.fullmatch(r"[1-9][0-9]*", str(upload.get("app_store_app_id", ""))) is None \
                        or upload.get("uploaded_build_number") != pending.get("app_build"):
                    errors.append("historical Xcode upload app/build identity is invalid")
                if re.fullmatch(r"[0-9A-F]{40}", str(upload.get("certificate_sha1", ""))) is None:
                    errors.append("historical Xcode distribution certificate SHA-1 is invalid")
                if upload.get("state") != "success" or upload.get("title") != "Uploaded to Apple":
                    errors.append("historical Xcode upload must prove Apple success")
                for field in ("archive_info_sha256", "archive_log_sha256", "upload_log_sha256"):
                    if re.fullmatch(r"[0-9a-f]{64}", str(upload.get(field, ""))) is None:
                        errors.append(f"historical Xcode upload {field} is invalid")
                if upload.get("ipa_sha256") is not None \
                        or upload.get("distribution_cdhash") is not None:
                    errors.append("historical remote-signing upload must not invent an IPA hash or CDHash")
                if not isinstance(upload.get("provenance_limitation"), str) \
                        or len(upload["provenance_limitation"].strip()) < 32:
                    errors.append("historical Xcode upload must disclose its provenance limitation")
            elif upload.get("method") == "verified_local_ipa_altool":
                if tuple(upload) != VERIFIED_LOCAL_IPA_UPLOAD_KEYS:
                    errors.append("verified local IPA upload receipt schema is invalid")
                for field in (
                    "ipa_sha256",
                    "archive_info_sha256",
                    "profile_sha256",
                    "distribution_certificate_sha256",
                    "upload_result_sha256",
                    "internal_gate_sha256",
                ):
                    if re.fullmatch(r"[0-9a-f]{64}", str(upload.get(field, ""))) is None:
                        errors.append(f"verified local IPA upload {field} is invalid")
                if re.fullmatch(
                    r"[0-9a-f]{40,64}", str(upload.get("distribution_cdhash", ""))
                ) is None:
                    errors.append("verified local IPA upload distribution_cdhash is invalid")
                upload_tool = str(upload.get("upload_tool", ""))
                if not upload_tool.startswith(
                    "/Applications/Xcode.app/Contents/SharedFrameworks/"
                    "ContentDelivery.framework/Versions/"
                ) or not upload_tool.endswith("/Resources/altoolShim"):
                    errors.append("verified local IPA upload tool must belong to pinned Xcode")
            else:
                errors.append("pending internal candidate upload method is unsupported")
        post_upload_signoffs = release_gate.get("post_upload_signoffs")
        if not isinstance(post_upload_signoffs, list):
            errors.append("release_gate post_upload_signoffs must be a list")
        else:
            post_upload_ids = [
                item.get("id") for item in post_upload_signoffs if isinstance(item, dict)
            ]
            if post_upload_ids != list(MANDATORY_RELEASE_SIGNOFFS) \
                    or len(post_upload_ids) != len(post_upload_signoffs):
                errors.append(
                    "release_gate post_upload_signoffs must contain the exact mandatory ordered IDs"
                )
            for item in post_upload_signoffs:
                if not isinstance(item, dict) or not isinstance(item.get("description"), str) \
                        or len(item["description"].strip()) < 8 \
                        or "TestFlight" not in item["description"]:
                    errors.append(
                        "every post-upload signoff requires a meaningful TestFlight description"
                    )
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
        if tuple(signoff_template) != (
            "schema_version", "head", "tree", "registry_blob", "completed_at", "items"
        ):
            errors.append("release signoff template must keep its exact final schema")
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
            or tuple(item) != (
                "id", "status", "tester", "app_version", "app_build", "tested_at",
                "environment", "steps", "evidence_reference", "evidence_sha256"
            )
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

    try:
        testflight_template = _load_json(TESTFLIGHT_SIGNOFF_TEMPLATE_PATH)
    except GuardError as exc:
        errors.append(str(exc))
    else:
        if tuple(testflight_template) != (
            "schema_version", "head", "tree", "registry_blob",
            "pending_candidate_sha256", "upload_receipt_identifier",
            "installation_source", "completed_at", "items",
        ):
            errors.append("TestFlight signoff template must keep its exact post-upload schema")
        for field in (
            "head", "tree", "registry_blob", "pending_candidate_sha256",
            "upload_receipt_identifier", "completed_at",
        ):
            if not str(testflight_template.get(field, "")).startswith("REPLACE_WITH_"):
                errors.append(f"TestFlight signoff template {field} must remain a placeholder")
        if testflight_template.get("installation_source") != "TestFlight":
            errors.append("TestFlight signoff template installation_source must be TestFlight")
        items = testflight_template.get("items")
        template_ids = [item.get("id") for item in items if isinstance(item, dict)] \
            if isinstance(items, list) else []
        if testflight_template.get("schema_version") != 1 \
                or template_ids != list(MANDATORY_RELEASE_SIGNOFFS) \
                or not isinstance(items, list) or len(template_ids) != len(items):
            errors.append("TestFlight signoff template must contain exact mandatory ordered items")
        elif any(
            item.get("status") != "pending"
            or item.get("tester") != ""
            or item.get("app_version") != "REPLACE_WITH_MARKETING_VERSION"
            or item.get("app_build") != "REPLACE_WITH_CURRENT_PROJECT_VERSION"
            or item.get("pending_candidate_sha256")
                != "REPLACE_WITH_TRACKED_PENDING_CANDIDATE_SHA256"
            or item.get("upload_receipt_identifier")
                != "REPLACE_WITH_TRACKED_UPLOAD_RECEIPT_IDENTIFIER"
            or item.get("installation_source") != "TestFlight"
            or tuple(item) != (
                "id", "status", "tester", "app_version", "app_build",
                "pending_candidate_sha256", "upload_receipt_identifier",
                "installation_source", "tested_at", "environment", "steps",
                "evidence_reference", "evidence_sha256",
            )
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
            errors.append("TestFlight signoff template must remain pending and candidate-bound")

    source_roots = (
        REPO_ROOT / "Xjie" / "Xjie",
        REPO_ROOT / "Xjie" / "XjieTests",
        REPO_ROOT / "Xjie" / "XjieUITests",
    )
    filesystem_errors = repository_filesystem_identity_violations(
        REPO_ROOT,
        source_roots,
        (PROJECT_FILE_PATH, SHARED_SCHEME_PATH, SWIFT_SOURCE_MANIFEST_PATH),
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
    errors.extend(
        swift_source_layout_violations(
            all_swift_paths,
            project_source,
            required_app_sources=swift_manifest_paths,
        )
    )
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
