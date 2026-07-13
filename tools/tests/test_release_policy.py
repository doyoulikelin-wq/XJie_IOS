from __future__ import annotations

import importlib.util
import json
import os
import plistlib
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
GUARD_PATH = REPO_ROOT / "tools" / "regression_guard.py"
GUARD_SPEC = importlib.util.spec_from_file_location("release_policy_regression_guard", GUARD_PATH)
assert GUARD_SPEC is not None and GUARD_SPEC.loader is not None
guard = importlib.util.module_from_spec(GUARD_SPEC)
sys.modules[GUARD_SPEC.name] = guard
GUARD_SPEC.loader.exec_module(guard)
NOTIFICATION_CENTER_PATTERN = re.compile(
    r"\bUNUserNotificationCenter\s*\.\s*current\s*\(\s*\)",
    re.MULTILINE,
)


def ui_test_policy_violations(sources: dict[str, str]) -> list[str]:
    violations: list[str] = []
    support_path = "XAgeUITestCase.swift"
    static_sources = {
        path: guard._swift_static_code(source)
        for path, source in sources.items()
    }
    support = static_sources.get(support_path, "")
    combined = "\n".join(static_sources.values())
    if len(re.findall(r"\bXCUIApplication\b", combined)) != 3 \
            or len(re.findall(r"\bXCUIApplication\s*\(", combined)) != 1:
        violations.append("UI suite must keep the exact shared application type/initializer contract")
    if len(re.findall(r"\.\s*launch\b", support)) != 1 \
            or len(re.findall(r"\.\s*terminate\b", support)) != 2:
        violations.append("shared UI base must keep the exact audited lifecycle contract")
    if "final override func setUpWithError" not in support \
            or "final override func tearDownWithError" not in support \
            or "auditCurrentApplicationLaunch()" not in support \
            or "didLaunchAtLeastOnce" not in support:
        violations.append("shared UI base must audit every launch from teardown")
    for path, source in static_sources.items():
        if path != support_path and re.search(r"\bXCUIApplication\b", source):
            violations.append(f"application type or initializer outside shared support: {path}")
        if path != support_path and re.search(r"\.\s*(?:launch|terminate)\b", source):
            violations.append(f"direct application lifecycle outside shared support: {path}")
        if path != support_path and "XAgeUITestApplicationFactory" in source:
            violations.append(f"shared application factory used outside audited base: {path}")
        if path != support_path and re.search(
            r"\boverride\s+func\s+(?:setUpWithError|tearDownWithError)\b", source
        ):
            violations.append(f"audited lifecycle overridden outside shared support: {path}")
        if re.search(r"\bfunc\s+test\w+\s*\(", source):
            classes = re.findall(r"\bclass\s+\w+\s*:\s*([\w.]+)", source)
            if not classes or any(base != "XAgeUITestCase" for base in classes):
                violations.append(f"UI test class does not inherit audited base: {path}")
    return violations


def production_session_violations(sources: dict[str, str]) -> list[str]:
    return guard.network_transport_violations(sources)


def workflow_fail_open_violations(workflow: str) -> list[str]:
    violations: list[str] = []
    if re.search(r"(?m)^\s*continue-on-error\s*:", workflow):
        violations.append("continue-on-error is forbidden")
    for line in workflow.splitlines():
        stripped = line.strip()
        if stripped.startswith("if:") and stripped != "if: always()":
            violations.append(f"conditional skip is forbidden: {stripped}")
        if "||" in stripped and not (
            stripped.startswith("if [[") and stripped.endswith("]]; then")
        ):
            violations.append(f"OR-list can swallow a failure: {stripped}")
        if "&&" in stripped and not (
            stripped.startswith("if [[") and stripped.endswith("]]; then")
        ):
            violations.append(f"AND-list can swallow a failure: {stripped}")
    for pattern, label in (
        (r"(?m)(?:^\s*|[;&|]\s*)set\s+\+[euo]", "shell strict mode disabled"),
        (r"(?m)(?:^\s*|[;&|]\s*)exit\s+0(?:\s|$)", "forced successful exit"),
    ):
        if re.search(pattern, workflow):
            violations.append(label)

    lines = workflow.splitlines()
    for index, line in enumerate(lines):
        match = re.match(r"^(\s*)run:\s*\|\s*$", line)
        if match is None:
            if re.match(r"^\s*run:\s*\S", line):
                violations.append("one-line run step cannot prove strict shell mode")
            continue
        indentation = len(match.group(1))
        commands: list[str] = []
        for candidate in lines[index + 1:]:
            if candidate.strip() and len(candidate) - len(candidate.lstrip()) <= indentation:
                break
            stripped = candidate.strip()
            if stripped and not stripped.startswith("#"):
                commands.append(stripped)
        if not commands or commands[0] != "set -euo pipefail":
            violations.append(f"run block at line {index + 1} does not start fail-closed")
    return violations


class ReleasePolicyTests(unittest.TestCase):
    def test_ci_covers_xage_backend_and_never_swallows_failures(self):
        workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        policy_job = workflow[
            workflow.index("  policy:\n"):workflow.index("  backend:\n")
        ]
        self.assertEqual(workflow_fail_open_violations(workflow), [])
        self.assertIn("branches: [main, XAGE]", workflow)
        self.assertEqual(
            re.findall(r"^    runs-on:\s*(\S+)\s*$", policy_job, re.MULTILINE),
            ["macos-15"],
        )
        self.assertIn("/usr/bin/python3 -I tools/python_test_gate.py tools", policy_job)
        self.assertIn("/usr/bin/python3 -I tools/regression_guard.py validate", policy_job)
        self.assertIn("/usr/bin/python3 -I tools/regression_guard.py check", policy_job)
        self.assertIn("Backend full regression", workflow)
        self.assertIn("python -I tools/python_test_gate.py backend", workflow)
        self.assertNotRegex(policy_job, r"(?m)^\s+python3\s+-I\s+")
        self.assertIn("regression_guard.py validate", workflow)
        self.assertIn("name: quality-gate", workflow)
        self.assertIn("set -o pipefail", workflow)
        self.assertNotIn("|| true", workflow)
        self.assertNotIn("    paths:", workflow)
        self.assertNotIn("workflow_dispatch:", workflow)
        self.assertNotRegex(workflow, r"uses:\s+[^\s]+@v\d")
        self.assertIn("xcode-version: '26.3'", workflow)
        for mutation in (
            workflow.replace("set -euo pipefail", "set +e", 1),
            workflow.replace("- name: Run backend tests", "- name: Run backend tests\n        continue-on-error: true"),
            workflow.replace("- name: Run backend tests", "- name: Run backend tests\n        if: false"),
            workflow.replace("echo \"All required regression gates passed.\"", "exit 0"),
            workflow.replace(
                "/usr/bin/python3 -I tools/python_test_gate.py tools",
                "/usr/bin/python3 -I tools/python_test_gate.py tools && echo tools-passed",
                1,
            ),
        ):
            with self.subTest(mutation=mutation):
                self.assertTrue(workflow_fail_open_violations(mutation))

    def test_every_python_test_command_uses_the_inventory_and_skip_gate(self):
        registry = json.loads(
            (REPO_ROOT / "quality" / "regression_contracts.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            registry["commands"]["guard_unit"],
            "/usr/bin/python3 -I tools/python_test_gate.py tools",
        )
        self.assertEqual(registry["release_gate"]["latest_uploaded_build"], 17)
        for command_id in ("backend_ai", "backend_health", "backend_full"):
            command = registry["commands"][command_id]
            self.assertIn("tools/python_test_gate.py backend", command)
            self.assertIn(" -I tools/python_test_gate.py", command)
            self.assertIn("--junitxml", command)
            self.assertNotIn(" -m pytest ", command)
        self.assertIn("--profile full", registry["commands"]["backend_full"])
        self.assertIn("--profile focused", registry["commands"]["backend_ai"])
        self.assertIn("--profile focused", registry["commands"]["backend_health"])
        python_gate = (REPO_ROOT / "tools" / "python_test_gate.py").read_text(encoding="utf-8")
        self.assertIn('[sys.executable, "-I", "-m", "pytest"', python_gate)

    def test_release_script_requires_head_bound_gate_before_archive(self):
        script = (REPO_ROOT / "scripts" / "release_testflight.sh").read_text(encoding="utf-8")
        self.assertTrue(script.startswith("#!/bin/zsh -f\n"))
        registry = json.loads(
            (REPO_ROOT / "quality" / "regression_contracts.json").read_text(encoding="utf-8")
        )
        gate_position = script.index("run_regression_gate.py assert-release")
        archive_position = script.index("clean archive")
        export_position = script.index("-exportArchive")
        ipa_container_position = script.index(
            '"$candidate_repo/tools/verify_release_bundle.py" --ipa "$ipa"'
        )
        ipa_snapshot_position = script.index(
            'ipa_snapshot_parent=$(/usr/bin/mktemp -d "$tmp_parent/xjie-ipa-snapshot.XXXXXX")'
        )
        ipa_extract_position = script.index('/usr/bin/ditto -x -k "$ipa"')
        distribution_position = script.index("Distribution IPA verified")
        archive_only_position = script.index('if [[ "$mode" == "--archive-only" ]]')
        upload_position = script.index("--upload-app")
        git_guard_position = script.index("readonly -a forbidden_git_environment")
        replace_guard_position = script.index("for-each-ref --format='%(refname)' refs/replace")
        release_lock_position = script.index('/bin/mkdir -- "$release_lock_dir"')
        cleanup_trap_position = script.index("trap 'cleanup_release' EXIT")
        auth_preflight_position = script.index(
            'if [[ "$mode" == "--upload" ]]; then\n  configure_upload_authentication\nfi'
        )
        xcode_pin_position = script.index('readonly pinned_developer_dir=')
        version_validation_position = script.index("Refusing invalid MARKETING_VERSION")
        build_validation_position = script.index("Refusing invalid CURRENT_PROJECT_VERSION")
        archive_removal_position = script.index('/bin/rm -rf -- "$archive"')
        entitlement_redirection_position = script.index('> "$entitlements"')
        self.assertLess(git_guard_position, gate_position)
        self.assertLess(replace_guard_position, gate_position)
        self.assertLess(release_lock_position, gate_position)
        self.assertLess(release_lock_position, cleanup_trap_position)
        self.assertLess(cleanup_trap_position, auth_preflight_position)
        self.assertLess(release_lock_position, auth_preflight_position)
        self.assertLess(auth_preflight_position, xcode_pin_position)
        self.assertLess(auth_preflight_position, gate_position)
        self.assertLess(gate_position, archive_position)
        self.assertLess(archive_position, export_position)
        self.assertLess(export_position, ipa_snapshot_position)
        self.assertLess(ipa_snapshot_position, ipa_container_position)
        self.assertLess(export_position, ipa_container_position)
        self.assertLess(ipa_container_position, ipa_extract_position)
        self.assertLess(ipa_extract_position, distribution_position)
        self.assertLess(export_position, distribution_position)
        self.assertLess(distribution_position, archive_only_position)
        self.assertLess(archive_only_position, upload_position)
        self.assertLess(version_validation_position, archive_removal_position)
        self.assertLess(build_validation_position, archive_removal_position)
        self.assertLess(version_validation_position, entitlement_redirection_position)
        self.assertLess(build_validation_position, entitlement_redirection_position)
        self.assertGreaterEqual(script.count("run_regression_gate.py assert-release"), 2)
        self.assertIn('"$python_bin" -I "$candidate_repo/tools/verify_release_bundle.py" "$app"', script)
        self.assertIn("/usr/bin/env -i", script)
        self.assertIn('export PATH="$safe_path"', script)
        self.assertIn('readonly safe_path="/usr/bin:/bin:/usr/sbin:/sbin"', script)
        self.assertIn('readonly python_bin="/usr/bin/python3"', script)
        self.assertNotIn("command -v python3", script)
        self.assertIn("unset PYTHONHOME PYTHONPATH", script)
        self.assertIn("XCODE_XCCONFIG_FILE", script)
        self.assertIn('[[ "$testability" == "NO" ]]', script)
        self.assertIn('[[ "$swift_conditions" != *DEBUG* ]]', script)
        self.assertIn("-showBuildSettings", script)
        self.assertIn("-json", script)
        self.assertIn("ApplicationProperties:ApplicationPath", script)
        self.assertIn("--path-format=absolute --git-common-dir", script)
        self.assertIn("/usr/bin/git", script)
        self.assertIn("export GIT_NO_REPLACE_OBJECTS=1", script)
        self.assertIn('"GIT_NO_REPLACE_OBJECTS=1"', script)
        self.assertIn("Refusing release with local Git replace refs", script)
        self.assertIn("Refusing release with unsafe local Git configuration", script)
        self.assertNotIn("${unsafe_git_config", script)
        self.assertIn("Refusing release with repository-local attributes override", script)
        self.assertIn('readonly pinned_developer_dir="/Applications/Xcode.app/Contents/Developer"', script)
        self.assertIn("Xcode 26.3\\nBuild version 17C529", script)
        self.assertIn("clone --no-local --no-checkout --no-tags", script)
        self.assertIn('project="$candidate_repo/Xjie/Xjie.xcodeproj"', script)
        self.assertGreaterEqual(script.count("verify_candidate_snapshot"), 4)
        self.assertIn("archive_cdhash=", script)
        self.assertIn('[[ "$current_cdhash" != "$archive_cdhash" ]]', script)
        self.assertEqual(script.count("-exportArchive"), 1)
        self.assertEqual(script.count("--upload-app"), 1)
        self.assertIn('[[ "$(/usr/libexec/PlistBuddy -c \'Print :destination\' "$export_options")" == "export" ]]', script)
        self.assertIn('ipa_candidates=("$export_path"/*.ipa(N))', script)
        self.assertIn('(( ${#ipa_candidates[@]} != 1 ))', script)
        self.assertIn('distribution_apps=("$distribution_payload"/*.app(N))', script)
        self.assertIn('[[ "$(/usr/bin/lipo -archs "$distribution_executable")" == "arm64" ]]', script)
        self.assertIn('set(platforms) != {2}', script)
        self.assertIn('get-task-allow raw', script)
        self.assertIn('beta-reports-active raw', script)
        self.assertIn('embedded.mobileprovision', script)
        self.assertIn('profile.get("ProvisionedDevices") is not None', script)
        self.assertEqual(
            script.count('"$candidate_repo/tools/verify_release_bundle.py" --ipa "$ipa"'),
            2,
        )
        self.assertIn('/bin/chmod 700 "$ipa_snapshot_parent"', script)
        self.assertIn('exported_ipa_sha256_before=$(sha256_file "$exported_ipa")', script)
        self.assertIn('exported_ipa_sha256_after=$(sha256_file "$exported_ipa")', script)
        self.assertIn('ipa_sha256=$(sha256_file "$ipa")', script)
        self.assertIn('[[ "$exported_ipa_sha256_before" != "$exported_ipa_sha256_after"', script)
        self.assertIn('[[ "$(sha256_file "$ipa")" != "$ipa_sha256" ]]', script)
        self.assertIn('/bin/chmod 400 "$ipa"', script)
        self.assertIn('"$(/usr/bin/stat -f \'%l\' "$ipa")" != "1"', script)
        self.assertIn('--extract-certificates "$distribution_app"', script)
        self.assertIn('profile.get("DeveloperCertificates")', script)
        self.assertIn('leaf_certificate not in developer_certificates', script)
        cms_status_position = script.index("security cms -D -h 0 -n")
        cms_validation_position = script.index("--cms-status-stdin")
        cms_decode_position = script.index('security cms -D -i "$embedded_profile"')
        self.assertLess(cms_status_position, cms_validation_position)
        self.assertLess(cms_validation_position, cms_decode_position)
        self.assertIn(
            'profile_cms_status=$(/usr/bin/security cms -D -h 0 -n -i '
            '"$embedded_profile" 2>&1)',
            script,
        )
        self.assertIn("Apple iPhone OS Provisioning Profile Signing", (
            REPO_ROOT / "tools" / "verify_release_bundle.py"
        ).read_text(encoding="utf-8"))
        self.assertIn('ipa_sha256=$(sha256_file "$ipa")', script)
        self.assertIn('distribution_cdhash=$(code_directory_hash "$distribution_app")', script)
        self.assertIn('current_ipa_sha256=$(sha256_file "$ipa")', script)
        self.assertIn('current_distribution_cdhash=$(code_directory_hash "$distribution_app")', script)
        self.assertGreaterEqual(script.count("recheck_distribution_identity"), 3)
        self.assertIn('XJIE_ASC_API_KEY_ID', script)
        self.assertIn('XJIE_ASC_API_ISSUER_ID', script)
        self.assertIn('XJIE_ASC_USERNAME', script)
        self.assertIn('XJIE_ASC_PASSWORD_KEYCHAIN_ITEM', script)
        self.assertIn('--password "@keychain:$XJIE_ASC_PASSWORD_KEYCHAIN_ITEM"', script)
        self.assertIn('Refusing mixed App Store Connect authentication metadata.', script)
        self.assertIn('/usr/bin/xcrun altool', script)
        self.assertIn('-f "$ipa"', script)
        self.assertNotIn('@env:', script)
        self.assertNotIn('--auth-string', script)
        self.assertNotIn('--p8-file-path', script)
        self.assertNotIn('destination\' "$export_options")" == "upload"', script)
        self.assertIn('/bin/mkdir -- "$archive_parent_path"', script)
        self.assertIn('release_lock_dir="$common_dir/xjie-testflight-release.lock"', script)
        self.assertIn("trap 'cleanup_release' EXIT", script)
        self.assertIn("re.fullmatch(r\"[0-9]+(?:\\.[0-9]+)*\"", script)
        self.assertIn("re.fullmatch(r\"[1-9][0-9]*\"", script)
        self.assertIn("require_canonical_direct_child", script)
        self.assertIn('require_canonical_direct_child "$archive_parent" "$archive"', script)
        self.assertIn('require_canonical_direct_child "$tmp_parent" "$export_path"', script)
        self.assertIn(
            'export_path=$(/usr/bin/mktemp -d "$tmp_parent/xjie-testflight-export.XXXXXX")',
            script,
        )
        self.assertIn('/bin/chmod 700 "$export_path"', script)
        self.assertIn('"$(/usr/bin/stat -f \'%Lp\' "$export_path")" != "700"', script)
        self.assertIn('/usr/bin/mktemp "$tmp_parent/xjie-release-entitlements.XXXXXX"', script)
        self.assertIn('/bin/unlink "$entitlements"', script)
        self.assertIn("manageAppVersionAndBuildNumber", script)

        required_distribution_fragments = (
            '== "export" ]]',
            'ipa_candidates=("$export_path"/*.ipa(N))',
            '"$candidate_repo/tools/verify_release_bundle.py" --ipa "$ipa"',
            'Distribution IPA verified:',
            'current_ipa_sha256=$(sha256_file "$ipa")',
            'current_distribution_cdhash=$(code_directory_hash "$distribution_app")',
            'plutil -extract beta-reports-active raw -o - "$distribution_entitlements"',
            'leaf_certificate not in developer_certificates',
            '--password "@keychain:$XJIE_ASC_PASSWORD_KEYCHAIN_ITEM"',
            '--upload-app \\\n    -f "$ipa"',
        )

        def distribution_policy_violations(candidate: str) -> list[str]:
            violations = [
                fragment for fragment in required_distribution_fragments
                if fragment not in candidate
            ]
            if any(forbidden in candidate for forbidden in ("@env:", "--auth-string", "--p8-file-path")):
                violations.append("unsafe credential transport")
            try:
                if not (
                    candidate.index("-exportArchive")
                    < candidate.index('"$candidate_repo/tools/verify_release_bundle.py" --ipa "$ipa"')
                    < candidate.index('/usr/bin/ditto -x -k "$ipa"')
                    < candidate.index("Distribution IPA verified:")
                    < candidate.index('if [[ "$mode" == "--archive-only" ]]')
                    < candidate.index("--upload-app")
                ):
                    violations.append("distribution verification order")
            except ValueError:
                violations.append("missing distribution stage")
            return violations

        self.assertEqual(distribution_policy_violations(script), [])
        for mutation in (
            script.replace('== "export" ]]', '== "upload" ]]', 1),
            script.replace('"$candidate_repo/tools/verify_release_bundle.py" --ipa "$ipa"', "", 1),
            script.replace('current_ipa_sha256=$(sha256_file "$ipa")', "current_ipa_sha256=$ipa_sha256", 1),
            script.replace('plutil -extract beta-reports-active raw -o - "$distribution_entitlements"', 'plutil -extract removed-beta-entitlement raw -o - "$distribution_entitlements"', 1),
            script.replace('leaf_certificate not in developer_certificates', 'False', 1),
            script.replace('--password "@keychain:$XJIE_ASC_PASSWORD_KEYCHAIN_ITEM"', '--password "@env:XJIE_ASC_PASSWORD"', 1),
            script.replace('--upload-app \\\n    -f "$ipa"', '--upload-app \\\n    -f "$archive"', 1),
        ):
            with self.subTest(distribution_mutation=mutation):
                self.assertTrue(distribution_policy_violations(mutation))
        forbidden_git_environment = (
            "GIT_DIR",
            "GIT_WORK_TREE",
            "GIT_INDEX_FILE",
            "GIT_OBJECT_DIRECTORY",
            "GIT_ALTERNATE_OBJECT_DIRECTORIES",
            "GIT_COMMON_DIR",
            "GIT_CONFIG",
            "GIT_CONFIG_GLOBAL",
            "GIT_CONFIG_SYSTEM",
            "GIT_CONFIG_COUNT",
            "GIT_CEILING_DIRECTORIES",
        )
        clean_environment = {
            key: value for key, value in os.environ.items()
            if key not in forbidden_git_environment
            and not key.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_"))
        }
        for variable in forbidden_git_environment:
            with self.subTest(variable=variable):
                environment = dict(clean_environment)
                environment[variable] = "/tmp/untrusted-release-redirection"
                result = subprocess.run(
                    ["/bin/zsh", "-f", "scripts/release_testflight.sh", "--archive-only"],
                    cwd=REPO_ROOT,
                    env=environment,
                    check=False,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(
                    f"Refusing release with repository-redirecting environment: {variable}",
                    result.stdout,
                )
        for variable in ("HTTPS_PROXY", "http_proxy", "ALL_PROXY", "SSL_CERT_FILE"):
            with self.subTest(variable=variable):
                environment = dict(clean_environment)
                environment[variable] = "/tmp/untrusted-network-redirection"
                result = subprocess.run(
                    ["/bin/zsh", "-f", "scripts/release_testflight.sh", "--archive-only"],
                    cwd=REPO_ROOT,
                    env=environment,
                    check=False,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(
                    f"Refusing release with proxy or custom-CA environment: {variable}",
                    result.stdout,
                )
        auth_environment = {
            "HOME": os.environ.get("HOME", "/var/empty"),
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "LANG": "en_US.UTF-8",
        }
        for authentication, expected_message in (
            ({}, "Upload requires one complete App Store Connect authentication method."),
            ({"XJIE_ASC_API_KEY_ID": "ABCDEFGHIJ"}, "Upload requires one complete App Store Connect authentication method."),
            (
                {
                    "XJIE_ASC_API_KEY_ID": "ABCDEFGHIJ",
                    "XJIE_ASC_API_ISSUER_ID": "01234567-89ab-cdef-0123-456789abcdef",
                    "XJIE_ASC_USERNAME": "qa@example.invalid",
                    "XJIE_ASC_PASSWORD_KEYCHAIN_ITEM": "xjie-testflight",
                },
                "Refusing mixed App Store Connect authentication metadata.",
            ),
        ):
            with self.subTest(authentication=authentication):
                result = subprocess.run(
                    ["/bin/zsh", "-f", "scripts/release_testflight.sh", "--upload"],
                    cwd=REPO_ROOT,
                    env={**auth_environment, **authentication},
                    check=False,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected_message, result.stdout)
        self.assertIn(
            "xcodebuild archive",
            registry["commands"]["ios_release_build"],
        )
        self.assertIn(
            "-destination 'generic/platform=iOS'",
            registry["commands"]["ios_release_build"],
        )
        self.assertIn(
            "tools/verify_release_bundle.py /tmp/xjie-quality-release.xcarchive/Products/Applications/Xjie.app",
            registry["commands"]["ios_release_build"],
        )

    def test_hooks_never_use_verify_bypass(self):
        hooks = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted((REPO_ROOT / ".githooks").iterdir())
            if path.is_file()
        )
        self.assertIn("regression_guard.py", hooks)
        self.assertNotIn("\n  python3 tools/regression_guard.py", hooks)
        self.assertNotIn("\n    python3 tools/regression_guard.py", hooks)
        self.assertGreaterEqual(
            hooks.count("/usr/bin/python3 -I tools/regression_guard.py"),
            4,
        )
        self.assertNotIn("--no-verify", hooks)

    def test_pre_push_allows_candidate_push_before_release_evidence(self):
        hook = (REPO_ROOT / ".githooks" / "pre-push").read_text(encoding="utf-8")
        self.assertIn("regression_guard.py validate", hook)
        self.assertIn("regression_guard.py check", hook)
        self.assertIn("clean_git -C \"$repo_root\" worktree add --detach", hook)
        self.assertNotIn("assert-release", hook)

    def test_hooks_validate_immutable_candidate_snapshots(self):
        pre_commit = (REPO_ROOT / ".githooks" / "pre-commit").read_text(encoding="utf-8")
        pre_push = (REPO_ROOT / ".githooks" / "pre-push").read_text(encoding="utf-8")
        self.assertIn("git write-tree", pre_commit)
        self.assertIn("git commit-tree", pre_commit)
        self.assertIn('clean_git -C "$repo_root" worktree add --detach --quiet "$snapshot"', pre_commit)
        self.assertIn("check --base HEAD^ --head HEAD", pre_commit)
        self.assertNotIn("check --staged", pre_commit)
        self.assertIn('clean_git -C "$repo_root" worktree add --detach --quiet "$active_snapshot" "$local_sha"', pre_push)
        self.assertIn('git merge-base "$local_sha" refs/remotes/origin/XAGE', pre_push)
        self.assertNotIn('git rev-parse "$local_sha^"', pre_push)
        self.assertIn("local_git_env=$(git rev-parse --local-env-vars)", pre_commit)
        self.assertIn("unset $local_git_env", pre_commit)
        self.assertIn("local_git_env=$(git rev-parse --local-env-vars)", pre_push)
        self.assertIn("unset $local_git_env", pre_push)

        environment = os.environ.copy()
        environment["GIT_INDEX_FILE"] = ".git/index"
        result = subprocess.run(
            ["/bin/sh", str(REPO_ROOT / ".githooks" / "pre-commit")],
            cwd=REPO_ROOT,
            env=environment,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout)

    def test_ui_domain_always_includes_small_screen_gate(self):
        registry = json.loads(
            (REPO_ROOT / "quality" / "regression_contracts.json").read_text(encoding="utf-8")
        )
        ui_domain = next(
            item for item in registry["behavior_domains"] if item["id"] == "ios_ui_interaction"
        )
        self.assertIn("ios_ui_small", ui_domain["verification_commands"])

    def test_ci_runs_small_screen_before_quality_gate(self):
        workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn("small_device_id", workflow)
        self.assertIn("Xjie-CI-Small.xcresult", workflow)
        self.assertIn(
            "testNavigationTouchTargetsAndFormDismissalConventions",
            workflow,
        )
        self.assertIn("testMetricManagerPageAndChatKeyboardLifecycle", workflow)
        self.assertIn("deviceTypeIdentifier", workflow)
        self.assertGreaterEqual(workflow.count("validate_xcresult.py"), 2)
        self.assertIn("--expected-profile ios_all", workflow)
        self.assertIn("--expected-profile ios_ui_small", workflow)
        self.assertNotIn("--minimum-tests", workflow)
        self.assertNotIn("actions/cache", workflow)
        self.assertIn("rm -rf /tmp/Xjie-CI.xcresult /tmp/Xjie-CI-Derived", workflow)
        self.assertIn("-derivedDataPath /tmp/Xjie-CI-Small-Derived", workflow)
        self.assertIn("/bin/zsh -f -n scripts/release_testflight.sh", workflow)
        self.assertIn("Xcode 26.3\\nBuild version 17C529", workflow)
        self.assertIn("xcodebuild archive", workflow)
        self.assertIn("-destination 'generic/platform=iOS'", workflow)
        self.assertIn("/tmp/Xjie-CI-Release.xcarchive/Products/Applications/Xjie.app", workflow)
        self.assertNotIn("Release-iphonesimulator", workflow)
        self.assertIn('python3 -I tools/verify_release_bundle.py "$release_app"', workflow)
        self.assertIn("needs: [policy, backend, ios]", workflow)

    def test_required_ui_tests_use_single_deterministic_app_factory_and_audit(self):
        source_root = REPO_ROOT / "Xjie" / "XjieUITests"
        sources = {
            str(path.relative_to(source_root)): path.read_text(encoding="utf-8")
            for path in sorted(source_root.rglob("*.swift"))
        }
        combined = "\n".join(sources.values())
        support = sources["XAgeUITestCase.swift"]
        teardown_start = support.index("final override func tearDownWithError")
        launch_start = support.index("final func launchApplication", teardown_start)
        teardown = support[teardown_start:launch_start]
        quiet_window = re.search(
            r"timeIntervalSince\(stableSince\)\s*>=\s*([0-9]+(?:\.[0-9]+)?)",
            support,
        )
        self.assertEqual(ui_test_policy_violations(sources), [])
        self.assertIn("XAgeUITestApplicationFactory", combined)
        self.assertIn("XJIE_UI_TEST_STUB_NETWORK", combined)
        self.assertIn("app.terminate()", teardown)
        self.assertIsNotNone(quiet_window)
        self.assertGreaterEqual(float(quiet_window.group(1)), 1.5)
        self.assertNotIn("dismissKnownAlertsIfNeeded", combined)

    def test_nested_or_direct_ui_application_bypass_is_rejected(self):
        valid_support = {
            "XAgeUITestCase.swift": """
                class XAgeUITestCase: XCTestCase {
                    var app: XCUIApplication!
                    var didLaunchAtLeastOnce = false
                    final override func setUpWithError() throws {}
                    final override func tearDownWithError() throws {
                        auditCurrentApplicationLaunch(); app.terminate()
                    }
                    final func launchApplication() { app.launch() }
                    final func relaunchApplication() { app.terminate() }
                    func auditCurrentApplicationLaunch() {}
                }
                private enum XAgeUITestApplicationFactory {
                    static func make() -> XCUIApplication { XCUIApplication() }
                }
            """,
            "FlowTests.swift": "class FlowTests: XAgeUITestCase { func testFlow() {} }",
        }
        self.assertEqual(ui_test_policy_violations(valid_support), [])
        bypass = dict(valid_support)
        bypass["Nested/BypassTests.swift"] = """
            class BypassTests: XCTestCase {
                func testBypass() { let app = XCUIApplication ( bundleIdentifier: "bad" ); app.launch() }
            }
        """
        self.assertTrue(ui_test_policy_violations(bypass))

        lifecycle_bypass = dict(valid_support)
        lifecycle_bypass["Nested/LifecycleBypassTests.swift"] = """
            class LifecycleBypassTests: XAgeUITestCase {
                override func tearDownWithError() throws {}
                func testBypass() {
                    let candidate = XAgeUITestApplicationFactory.make(
                        resetAuth: true,
                        resetDataCards: true
                    )
                    candidate.launch()
                }
            }
        """
        violations = ui_test_policy_violations(lifecycle_bypass)
        self.assertTrue(any("lifecycle" in item for item in violations))
        self.assertTrue(any("factory" in item for item in violations))

        for rogue_source in (
            """
                class CommentBypassTests: XAgeUITestCase {
                    func testBypass() {
                        let rogue = XCUIApplication/*gap*/()
                        rogue/*gap*/.launch()
                    }
                }
            """,
            """
                class EscapedBypassTests: XAgeUITestCase {
                    func testBypass() {
                        let rogue = `XCUIApplication`/*gap*/()
                        rogue/*gap*/.`launch`/*gap*/()
                    }
                }
            """,
            'class InterpolationBypassTests: XAgeUITestCase { '
            'func testBypass() { _ = "\\(XCUIApplication().description)" } }',
            """
                class ExplicitInitBypassTests: XAgeUITestCase {
                    func testBypass() { _ = XCUIApplication.init() }
                }
            """,
            """
                class ContextualInitBypassTests: XAgeUITestCase {
                    func testBypass() { let app: XCUIApplication = .init(); _ = app }
                }
            """,
            """
                class MethodReferenceBypassTests: XAgeUITestCase {
                    func testBypass() { let start = app.launch; start() }
                }
            """,
        ):
            bypass = dict(valid_support)
            bypass["Nested/LexerBypassTests.swift"] = rogue_source
            with self.subTest(rogue_source=rogue_source):
                self.assertTrue(ui_test_policy_violations(bypass))

    def test_production_network_calls_cannot_bypass_api_service_transport(self):
        source_root = REPO_ROOT / "Xjie" / "Xjie"
        sources = {
            str(path.relative_to(source_root)): path.read_text(encoding="utf-8")
            for path in source_root.rglob("*.swift")
        }
        ui_test_root = REPO_ROOT / "Xjie" / "XjieUITests"
        sources.update({
            "XjieUITests/" + str(path.relative_to(ui_test_root)): path.read_text(encoding="utf-8")
            for path in ui_test_root.rglob("*.swift")
        })
        self.assertEqual(production_session_violations(sources), [])
        self.assertEqual(guard.deterministic_system_boundary_violations(sources), [])
        for path, source in (
            ("Views/PathBypass.swift", "let monitor = NWPathMonitor()"),
            ("Views/PathBypass.swift", "let monitor = `NWPathMonitor`/*gap*/()"),
            ("Views/PathBypass.swift", "let monitor = NWPathMonitor.init()"),
            (
                "Views/PathBypass.swift",
                "let make: () -> NWPathMonitor = { .init() }; let monitor = make()",
            ),
            ("Views/HealthBypass.swift", "let store = HKHealthStore()"),
            ("Views/HealthBypass.swift", "let store = HKHealthStore.init()"),
            (
                "Views/HealthBypass.swift",
                "let make: () -> HKHealthStore = { .init() }; let store = make()",
            ),
            (
                "Views/NotificationBypass.swift",
                "let center = `UNUserNotificationCenter`/*gap*/.`current`/*gap*/()",
            ),
            (
                "Views/NotificationBypass.swift",
                "let factory = UNUserNotificationCenter.current; let center = factory()",
            ),
        ):
            mutated = dict(sources)
            mutated[path] = source
            with self.subTest(system_boundary_path=path, source=source):
                self.assertTrue(guard.deterministic_system_boundary_violations(mutated))
        swift_paths = {
            path.relative_to(REPO_ROOT).as_posix()
            for path in REPO_ROOT.rglob("*.swift")
            if path.is_file() and ".git" not in path.relative_to(REPO_ROOT).parts
        }
        project_source = (REPO_ROOT / "Xjie" / "Xjie.xcodeproj" / "project.pbxproj").read_text(
            encoding="utf-8"
        )
        self.assertEqual(guard.swift_source_layout_violations(swift_paths, project_source), [])
        self.assertEqual(guard.xcode_release_build_setting_violations(project_source), [])

    def test_network_boundary_rejects_whitespace_bypasses_and_second_constructor(self):
        approved = {
            "Services/APIService.swift": """
                actor APIService: APIServiceProtocol {
                    static let shared = APIService()
                    let trustedSession: URLSession = URLSession(
                        configuration: APIService.makeSessionConfiguration()
                    )
                }
            """,
            "Utils/Utils.swift": """
                enum LocalFileDataLoader {
                    static func read(_ url: URL) throws -> Data {
                        guard url.isFileURL else { throw URLError(.unsupportedURL) }
                        return try Data(contentsOf: url)
                    }
                }
            """,
            "Views/NetworkWords.swift": """
                let note = "URLSession.shared Data(contentsOf:) WKWebView NWConnection"
                let raw = #"SFSafariViewController AVPlayer(url:)"#
                // URLSession.shared and Data(contentsOf:) are documentation only here.
            """,
        }
        self.assertEqual(production_session_violations(approved), [])
        for path, source in (
            ("Views/Bypass.swift", "let session = URLSession . shared"),
            ("Views/Bypass.swift", "let session = URLSession/*gap*/.shared"),
            ("Views/Bypass.swift", "let session = URLSession ( configuration: .default )"),
            ("Views/Bypass.swift", "let session = URLSession/*gap*/(configuration: .default)"),
            ("Views/Bypass.swift", "let session = Foundation.URLSession.init(configuration: .default)"),
            (
                "Views/Bypass.swift",
                "func makeRogue() -> URLSession { .init(configuration: .default) }",
            ),
            ("Views/Bypass.swift", "func makeRogue() -> URLSession { .shared }"),
            (
                "Views/Bypass.swift",
                "final class Rogue { var session: URLSession!; init() { "
                "session = .init(configuration: .ephemeral) } }",
            ),
            ("Views/Bypass.swift", "typealias Session = URLSession\nlet session = Session(configuration: .default)"),
            ("Views/Bypass.swift", "let constructor = URLSession.self\nlet session = constructor.init(configuration: .default)"),
            ("Services/APIService.swift", approved["Services/APIService.swift"] + "\nlet second = URLSession(configuration: .ephemeral)"),
            (
                "Services/APIService.swift",
                approved["Services/APIService.swift"]
                + "\nprivate let rogue: URLSession = .init(configuration: .ephemeral)"
                + "\nfunc escape(_ request: URLRequest) async throws {"
                + " _ = try await rogue.data(for: request) }",
            ),
            (
                "Services/APIService.swift",
                approved["Services/APIService.swift"]
                + "\nfunc escape(_ request: URLRequest) async throws {"
                + " let trustedSession: URLSession = .shared;"
                + " _ = try await trustedSession.data(for: request) }",
            ),
            ("Views/Bypass.swift", "let payload = try Data(contentsOf: URL(string: \"https://example.invalid\")!)"),
            ("Views/Bypass.swift", "let payload = try Data/*gap*/(contentsOf: remoteURL)"),
            ("Views/Bypass.swift", "let payload: Data = try .init(contentsOf: remoteURL)"),
            ("Views/Bypass.swift", "typealias Payload = Data\nlet payload = try Payload(contentsOf: remoteURL)"),
            ("Views/Bypass.swift", "let constructor = Data.self\nlet payload = try constructor.init(contentsOf: remoteURL)"),
            ("Views/Bypass.swift", "let payload = NSData(contentsOf: URL(string: \"https://example.invalid\")!)"),
            ("Views/Bypass.swift", "let payload = NSString(contentsOf: remoteURL, encoding: 4)"),
            ("Views/Bypass.swift", "let payload = NSArray(contentsOf: remoteURL)"),
            ("Views/Bypass.swift", "let payload = NSDictionary(contentsOf: remoteURL)"),
            ("Views/Bypass.swift", "let payload = try String(contentsOf: URL(string: \"https://example.invalid\")!)"),
            (
                "Views/Bypass.swift",
                'let rendered = "payload: \\(try Data(contentsOf: remoteURL))"',
            ),
            (
                "Views/Bypass.swift",
                'let rendered = #"payload: \\#(AVPlayer(url: remoteURL))"#',
            ),
            (
                "Views/Bypass.swift",
                'let rendered = "\\(/[)]/.wholeMatch(in: \")\") != nil '
                '? (try await URLSession.shared.data(from: remoteURL)).0.count : 0)"',
            ),
            (
                "Views/Bypass.swift",
                "let rogue = Foundation.`URLSession`.`shared`\n"
                "_ = try await rogue.`data`(from: remoteURL)",
            ),
            ("Views/Bypass.swift", "let connection = NWConnection(host: \"example.invalid\", port: 443, using: .tls)"),
            (
                "Views/Bypass.swift",
                "let connection = nw_connection_create(endpoint, parameters)\n"
                "nw_connection_start(connection)",
            ),
            (
                "Views/Bypass.swift",
                "let createSocket = Darwin.socket\nlet openConnection = Darwin.connect",
            ),
            ("Views/Bypass.swift", "let createSocket = CFSocketCreate"),
            ("Views/Bypass.swift", "let connectSocket = CFSocketConnectToAddress"),
            (
                "Views/Bypass.swift",
                "let createPair = CFStreamCreatePairWithSocket",
            ),
            (
                "Views/Bypass.swift",
                "let ftp = CFReadStreamCreateWithFTPURL",
            ),
            ("Views/Bypass.swift", "import CFNetwork"),
            (
                "Views/Bypass.swift",
                "let APIService = ShadowAPI()\n"
                "_ = try await APIService.shared.trustedSession.data(for: request)",
            ),
            (
                "Views/Bypass.swift",
                "let (APIService, ignored) = pair\n"
                "_ = try await APIService.shared.trustedSession.data(for: request)",
            ),
            (
                "Views/Bypass.swift",
                "for (APIService, ignored) in pairs { "
                "_ = try await APIService.shared.trustedSession.data(for: request) }",
            ),
            (
                "Views/Bypass.swift",
                "func rogue(_ APIService: ShadowAPI) async throws { "
                "_ = try await APIService.shared.trustedSession.data(for: request) }",
            ),
            (
                "Views/Bypass.swift",
                "func rogue(label APIService: ShadowAPI) async throws { "
                "_ = try await APIService.shared.trustedSession.data(for: request) }",
            ),
            (
                "Views/Bypass.swift",
                "let trustedSession = APIService.shared.trustedSession\n"
                "_ = try await trustedSession.data(for: request)",
            ),
            (
                "Views/Bypass.swift",
                "let task = APIService.shared.trustedSession.webSocketTask("
                "with: URL(string: \"wss://example.invalid/socket\")!)",
            ),
            (
                "Views/Bypass.swift",
                "let task = APIService.shared.trustedSession.streamTask("
                "withHostName: \"example.invalid\", port: 443)",
            ),
            (
                "Views/Bypass.swift",
                "let task = APIService.shared.trustedSession.downloadTask("
                "with: URL(string: \"https://example.invalid/file\")!)",
            ),
            (
                "Views/Bypass.swift",
                "let task = APIService.shared.trustedSession.uploadTask("
                "with: request, from: payload)",
            ),
            ("Views/Bypass.swift", "let browser = WKWebView()"),
            ("Views/Bypass.swift", "AsyncImage(url: URL(string: \"https://example.invalid\"))"),
            ("Views/Bypass.swift", "let player = AVPlayer(url: remoteURL)"),
            ("Views/Bypass.swift", "let asset = AVURLAsset(url: remoteURL)"),
            ("Views/Bypass.swift", "let browser = SFSafariViewController(url: remoteURL)"),
            ("Views/Bypass.swift", "let connection = NSURLConnection(request: request, delegate: nil)"),
            ("Views/Bypass.swift", "let result = try await session.data(for: request)"),
            (
                "XjieUITests/Bypass.swift",
                "let result = try await APIService.shared.trustedSession.data(for: request)",
            ),
            (
                "Utils/Utils.swift",
                approved["Utils/Utils.swift"].replace(
                    "guard url.isFileURL else { throw URLError(.unsupportedURL) }",
                    "let accepted = url",
                ),
            ),
        ):
            mutated = dict(approved)
            mutated[path] = source
            with self.subTest(path=path, source=source):
                self.assertTrue(production_session_violations(mutated))

        layout_paths = {
            "Xjie/Xjie/Services/APIService.swift",
            "Xjie/Xjie/Utils/Utils.swift",
            "Xjie/XjieTests/APIServiceTests.swift",
            "Xjie/XjieUITests/XAgeUITestCase.swift",
        }

        layout_files = (
            ("A0", "B0", "APIService.swift", "Xjie/Services/APIService.swift"),
            ("A1", "B1", "Utils.swift", "Xjie/Utils/Utils.swift"),
            ("A2", "B2", "APIServiceTests.swift", "XjieTests/APIServiceTests.swift"),
            ("A3", "B3", "XAgeUITestCase.swift", "XjieUITests/XAgeUITestCase.swift"),
        )
        build_files = "\n".join(
            f"{build_id} /* {name} in Sources */ = {{isa = PBXBuildFile; "
            f"fileRef = {reference_id} /* {name} */; }};"
            for build_id, reference_id, name, _path in layout_files
        )
        references = "\n".join(
            f"{reference_id} /* {name} */ = {{isa = PBXFileReference; "
            f"path = {path}; sourceTree = SOURCE_ROOT; }};"
            for _build_id, reference_id, name, path in layout_files
        )

        def source_phase(phase_id: str, build_ids: tuple[str, ...]) -> str:
            entries = "\n".join(f"{build_id} /* retained comment in Sources */," for build_id in build_ids)
            return f"""
                {phase_id} /* Sources */ = {{
                    isa = PBXSourcesBuildPhase;
                    files = (
                        {entries}
                    );
                }};
            """

        layout_project = f"""
            objects = {{
            /* Begin PBXBuildFile section */
            {build_files}
            /* End PBXBuildFile section */
            /* Begin PBXFileReference section */
            {references}
            /* End PBXFileReference section */
            /* Begin PBXGroup section */
            EROOT = {{
                isa = PBXGroup;
                children = (
                );
                sourceTree = "<group>";
            }};
            /* End PBXGroup section */
            H10001 = {{
                isa = PBXProject;
                buildConfigurationList = G10001;
                mainGroup = EROOT;
                targets = (F10001, F20001, F300000000000000000001,);
            }};
            J10001 = {{
                isa = PBXContainerItemProxy;
                containerPortal = H10001;
                proxyType = 1;
                remoteGlobalIDString = F10001;
            }};
            J300000000000000000001 = {{
                isa = PBXContainerItemProxy;
                containerPortal = H10001;
                proxyType = 1;
                remoteGlobalIDString = F10001;
            }};
            K10001 = {{isa = PBXTargetDependency; target = F10001; targetProxy = J10001;}};
            K300000000000000000001 = {{isa = PBXTargetDependency; target = F10001; targetProxy = J300000000000000000001;}};
            /* Begin PBXNativeTarget section */
            F10001 /* Xjie */ = {{
                isa = PBXNativeTarget;
                buildConfigurationList = G10003;
                buildPhases = (
                    F10002 /* Sources */,
                    D10001 /* Frameworks */,
                    F10003 /* Resources */,
                );
                buildRules = (
                );
                dependencies = (
                );
            }};
            F20001 /* XjieTests */ = {{
                isa = PBXNativeTarget;
                buildConfigurationList = G20003;
                buildPhases = (
                    F20002 /* Sources */,
                    D20001 /* Frameworks */,
                );
                buildRules = (
                );
                dependencies = (
                    K10001 /* PBXTargetDependency */,
                );
            }};
            F300000000000000000001 /* XjieUITests */ = {{
                isa = PBXNativeTarget;
                buildConfigurationList = G300000000000000000003;
                buildPhases = (
                    F300000000000000000002 /* Sources */,
                    D300000000000000000001 /* Frameworks */,
                );
                buildRules = (
                );
                dependencies = (
                    K300000000000000000001 /* PBXTargetDependency */,
                );
            }};
            /* End PBXNativeTarget section */
            D10001 = {{isa = PBXFrameworksBuildPhase; files = ();}};
            F10003 = {{isa = PBXResourcesBuildPhase;}};
            D20001 = {{isa = PBXFrameworksBuildPhase; files = ();}};
            D300000000000000000001 = {{isa = PBXFrameworksBuildPhase; files = ();}};
            /* Begin PBXSourcesBuildPhase section */
            {source_phase("F10002", ("A0", "A1"))}
            {source_phase("F20002", ("A2",))}
            {source_phase("F300000000000000000002", ("A3",))}
            /* End PBXSourcesBuildPhase section */
            }};
        """
        self.assertEqual(guard.swift_source_layout_violations(layout_paths, layout_project), [])
        self.assertTrue(guard.swift_source_layout_violations(
            layout_paths | {"Sources/Bypass.swift"},
            layout_project,
        ))
        foreign_target = layout_project.replace(
            "A1 /* retained comment in Sources */",
            "A2 /* retained comment in Sources */",
            1,
        )
        self.assertTrue(guard.swift_source_layout_violations(layout_paths, foreign_target))
        forged_comment = layout_project.replace(
            "fileRef = B1 /* Utils.swift */",
            "fileRef = B2 /* Utils.swift */",
            1,
        )
        self.assertTrue(guard.swift_source_layout_violations(layout_paths, forged_comment))
        swapped_target_phase = layout_project.replace(
            "F10002 /* Sources */,",
            "F20002 /* Sources */,",
            1,
        )
        self.assertTrue(
            guard.swift_source_layout_violations(layout_paths, swapped_target_phase)
        )
        hidden_source_phase = layout_project.replace(
            "D10001 = {isa = PBXFrameworksBuildPhase; files = ();};",
            "D10001 = {isa = PBXFrameworksBuildPhase; files = ();};\n"
            "FEVIL = {isa = PBXSourcesBuildPhase; files = (A2,);};",
            1,
        ).replace(
            "D10001 /* Frameworks */,",
            "D10001 /* Frameworks */,\nFEVIL /* harmless-looking phase */,",
            1,
        )
        self.assertTrue(
            guard.swift_source_layout_violations(layout_paths, hidden_source_phase)
        )
        swapped_configuration = layout_project.replace(
            "buildConfigurationList = G10003;",
            "buildConfigurationList = G20003;",
            1,
        )
        self.assertTrue(
            guard.swift_source_layout_violations(layout_paths, swapped_configuration)
        )
        linked_framework = layout_project.replace(
            "D10001 = {isa = PBXFrameworksBuildPhase; files = ();};",
            "D10001 = {isa = PBXFrameworksBuildPhase; files = (EVIL,);};",
            1,
        )
        self.assertTrue(guard.swift_source_layout_violations(layout_paths, linked_framework))
        package_product = layout_project.replace(
            "buildRules = (",
            "packageProductDependencies = (EVIL_PACKAGE,);\n                buildRules = (",
            1,
        )
        self.assertTrue(guard.swift_source_layout_violations(layout_paths, package_product))
        package_reference = layout_project + "\npackageReferences = (EVIL_PACKAGE);"
        self.assertTrue(guard.swift_source_layout_violations(layout_paths, package_reference))

        valid_app_phase = source_phase("F10002", ("A0", "A1"))
        reordered_app_phase = valid_app_phase.replace(
            "isa = PBXSourcesBuildPhase;",
            "buildActionMask = 2147483647;\n                    isa = PBXSourcesBuildPhase;",
            1,
        ).replace("A1 /* retained comment in Sources */,", "", 1)
        comment_spoof = layout_project.replace(
            valid_app_phase,
            "/*" + valid_app_phase + "*/\n" + reordered_app_phase,
            1,
        )
        self.assertTrue(guard.swift_source_layout_violations(layout_paths, comment_spoof))
        multiline_string_spoof = layout_project.replace(
            valid_app_phase,
            'FAKESTRING = "' + valid_app_phase + '";\n' + reordered_app_phase,
            1,
        )
        self.assertTrue(
            guard.swift_source_layout_violations(layout_paths, multiline_string_spoof)
        )
        single_line_string_spoof = layout_project.replace(
            "buildConfigurationList = G10003;",
            'note = "buildConfigurationList = G10003;";\n'
            "                buildConfigurationList = G20003;",
            1,
        )
        self.assertTrue(
            guard.swift_source_layout_violations(layout_paths, single_line_string_spoof)
        )
        duplicate_target_configuration = layout_project.replace(
            "buildConfigurationList = G10003;",
            "buildConfigurationList = G10003;\n"
            "                buildConfigurationList = G20003;",
            1,
        )
        self.assertTrue(
            guard.swift_source_layout_violations(
                layout_paths, duplicate_target_configuration
            )
        )
        duplicate_source_files = layout_project.replace(
            valid_app_phase,
            valid_app_phase.replace(
                "                    );",
                "                    );\n                    files = ();",
                1,
            ),
            1,
        )
        self.assertTrue(
            guard.swift_source_layout_violations(layout_paths, duplicate_source_files)
        )
        hidden_aggregate = layout_project.replace(
            "F10001, F20001, F300000000000000000001,",
            "F10001, F20001, F300000000000000000001, EVILT,",
            1,
        ).replace(
            "target = F10001; targetProxy = J10001;",
            "target = EVILT; targetProxy = J10001;",
            1,
        ).replace(
            "/* End PBXSourcesBuildPhase section */",
            """
            EVILP = { files = (); shellScript = __XJIE_SAFE_TOKEN__; isa = PBXShellScriptBuildPhase; };
            EVILT = {
                buildConfigurationList = G10003;
                buildPhases = (EVILP,);
                buildRules = ();
                dependencies = ();
                isa = PBXAggregateTarget;
            };
            /* End PBXSourcesBuildPhase section */
            """,
            1,
        )
        self.assertTrue(guard.swift_source_layout_violations(layout_paths, hidden_aggregate))

        with tempfile.TemporaryDirectory() as filesystem_temp:
            repository = Path(filesystem_temp) / "repo"
            app_root = repository / "Xjie" / "Xjie"
            unit_root = repository / "Xjie" / "XjieTests"
            ui_root = repository / "Xjie" / "XjieUITests"
            project_file = repository / "Xjie" / "Xjie.xcodeproj" / "project.pbxproj"
            scheme_file = (
                repository / "Xjie" / "Xjie.xcodeproj" / "xcshareddata"
                / "xcschemes" / "Xjie.xcscheme"
            )
            for directory in (app_root, unit_root, ui_root, project_file.parent, scheme_file.parent):
                directory.mkdir(parents=True, exist_ok=True)
            (app_root / "App.swift").write_text("struct App {}", encoding="utf-8")
            project_file.write_text("{}", encoding="utf-8")
            scheme_file.write_text("<Scheme/>", encoding="utf-8")
            self.assertEqual(
                guard.repository_filesystem_identity_violations(
                    repository,
                    (app_root, unit_root, ui_root),
                    (project_file, scheme_file),
                ),
                [],
            )
            outside = Path(filesystem_temp) / "outside"
            outside.mkdir()
            (outside / "Bypass.swift").write_text("struct Bypass {}", encoding="utf-8")
            (app_root / "LinkedSources").symlink_to(outside, target_is_directory=True)
            self.assertTrue(
                guard.repository_filesystem_identity_violations(
                    repository,
                    (app_root, unit_root, ui_root),
                    (project_file, scheme_file),
                )
            )
            (app_root / "LinkedSources").unlink()
            outside_plist = Path(filesystem_temp) / "outside.plist"
            outside_plist.write_text("{}", encoding="utf-8")
            (app_root / "Info.plist").symlink_to(outside_plist)
            self.assertTrue(
                guard.repository_filesystem_identity_violations(
                    repository,
                    (app_root, unit_root, ui_root),
                    (project_file, scheme_file),
                )
            )

    def test_release_commands_validate_executed_xcresult_tests(self):
        registry = json.loads(
            (REPO_ROOT / "quality" / "regression_contracts.json").read_text(encoding="utf-8")
        )
        for command_id, profile in (
            ("ios_unit", "ios_unit"),
            ("ios_ui_full", "ios_ui_full"),
            ("ios_ui_small", "ios_ui_small"),
        ):
            command = registry["commands"][command_id]
            self.assertIn("-resultBundlePath", command)
            self.assertIn("validate_xcresult.py", command)
            self.assertIn(f"--expected-profile {profile}", command)
            self.assertNotIn("--minimum-tests", command)

    def test_release_export_options_and_production_api_are_pinned(self):
        script = (REPO_ROOT / "scripts" / "release_testflight.sh").read_text(encoding="utf-8")
        self.assertIn('export_options="$candidate_repo/scripts/ExportOptions-TestFlight.plist"', script)
        self.assertIn('[[ "$api_base" == "https://www.jianjieaitech.com" ]]', script)
        self.assertIn("--release-build-settings-stdin", script)
        self.assertLess(
            script.index("--release-build-settings-stdin"),
            script.index("  clean archive "),
        )
        with (REPO_ROOT / "scripts" / "ExportOptions-TestFlight.plist").open("rb") as handle:
            options = plistlib.load(handle)
        self.assertEqual(options["destination"], "export")
        self.assertEqual(options["method"], "app-store-connect")
        self.assertEqual(options["teamID"], "52BRF299Y7")
        self.assertIs(options["manageAppVersionAndBuildNumber"], False)

        project = (REPO_ROOT / "Xjie" / "Xjie.xcodeproj" / "project.pbxproj").read_text(
            encoding="utf-8"
        )
        self.assertEqual(guard.xcode_release_build_setting_violations(project), [])

        for forbidden in (
            "EXCLUDED_SOURCE_FILE_NAMES = APIService.swift;",
            "INCLUDED_SOURCE_FILE_NAMES = SafeOnly.swift;",
            "COMPILER_FLAGS = \"-DDEBUG\";",
            "baseConfigurationReference = EVIL;",
            'OTHER_LDFLAGS = "-force_load /tmp/rogue.a";',
            "SWIFT_OBJC_BRIDGING_HEADER = /tmp/rogue.h;",
            "SWIFT_INCLUDE_PATHS = /tmp/rogue-modules;",
            "LIBRARY_SEARCH_PATHS = /tmp/rogue-libraries;",
            "FRAMEWORK_SEARCH_PATHS = /tmp/rogue-frameworks;",
        ):
            with self.subTest(forbidden_project_setting=forbidden):
                self.assertTrue(
                    guard.xcode_release_build_setting_violations(project + "\n" + forbidden)
                )

        release_prefix, release_body = project.split("G10006 /* Release */", 1)
        for forbidden in (
            'SWIFT_ACTIVE_COMPILATION_CONDITIONS = "$(inherited) DEBUG";',
            'OTHER_SWIFT_FLAGS = "-DDEBUG";',
            'GCC_PREPROCESSOR_DEFINITIONS = "DEBUG=1";',
            "ENABLE_TESTABILITY = YES;",
            'EXCLUDED_ARCHS[sdk=iphoneos*] = arm64;',
            'OTHER_CFLAGS = "-include /tmp/rogue.h";',
            'OTHER_CPLUSPLUSFLAGS = "-include /tmp/rogue.hpp";',
        ):
            with self.subTest(forbidden_release_setting=forbidden):
                mutated_release = release_body.replace(
                    "buildSettings = {",
                    "buildSettings = {\n\t\t\t\t" + forbidden,
                    1,
                )
                self.assertTrue(
                    guard.xcode_release_build_setting_violations(
                        release_prefix + "G10006 /* Release */" + mutated_release
                    )
                )

        swapped_list = project.replace(
            "G10005 /* Debug */,\n\t\t\t\tG10006 /* Release */",
            "G10006 /* Release */,\n\t\t\t\tG10005 /* Debug */",
            1,
        )
        self.assertTrue(guard.xcode_release_build_setting_violations(swapped_list))

        scheme = (
            REPO_ROOT
            / "Xjie"
            / "Xjie.xcodeproj"
            / "xcshareddata"
            / "xcschemes"
            / "Xjie.xcscheme"
        ).read_text(encoding="utf-8")
        self.assertEqual(guard.xcode_scheme_violations(scheme), [])
        for mutated_scheme in (
            scheme.replace(
                "<BuildActionEntries>",
                '<PreActions><ExecutionAction scriptText="exit 0"/></PreActions>'
                "<BuildActionEntries>",
                1,
            ),
            scheme.replace(
                '<ArchiveAction\n      buildConfiguration = "Release"',
                '<ArchiveAction\n      buildConfiguration = "Debug"',
                1,
            ),
            scheme.replace('skipped = "NO"', 'skipped = "YES"', 1),
            scheme.replace('BlueprintIdentifier = "F20001"', 'BlueprintIdentifier = "F10001"', 1),
            scheme.replace(
                '<Testables>',
                '<TestPlans><TestPlanReference reference="container:Bypass.xctestplan"/></TestPlans><Testables>',
                1,
            ),
        ):
            with self.subTest(mutated_scheme=mutated_scheme[:120]):
                self.assertTrue(guard.xcode_scheme_violations(mutated_scheme))

    def test_diff_check_fails_on_trailing_whitespace_inside_merge_commit(self):
        registry = json.loads(
            (REPO_ROOT / "quality" / "regression_contracts.json").read_text(encoding="utf-8")
        )
        command = registry["commands"]["diff_check"]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            def git(*arguments: str) -> None:
                subprocess.run(
                    ["git", *arguments], cwd=root, check=True,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )

            git("init")
            git("config", "user.email", "quality@example.invalid")
            git("config", "user.name", "Quality Gate")
            git("checkout", "-b", "main")
            (root / "base.txt").write_text("base\n", encoding="utf-8")
            git("add", "base.txt")
            git("commit", "-m", "base")
            git("checkout", "-b", "feature")
            (root / "bad.txt").write_text("trailing whitespace   \n", encoding="utf-8")
            git("add", "bad.txt")
            git("commit", "-m", "bad whitespace")
            git("checkout", "main")
            (root / "main.txt").write_text("main\n", encoding="utf-8")
            git("add", "main.txt")
            git("commit", "-m", "advance main")
            git("merge", "--no-ff", "feature", "-m", "merge feature")
            result = subprocess.run(
                ["/bin/zsh", "-f", "-c", command], cwd=root, check=False,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("trailing whitespace", result.stdout)

    def test_release_signoff_template_is_pending_and_unforgeable_by_default(self):
        template = json.loads(
            (REPO_ROOT / "quality" / "release_signoffs.example.json").read_text(encoding="utf-8")
        )
        self.assertTrue(str(template["head"]).startswith("REPLACE_WITH_"))
        self.assertTrue(str(template["tree"]).startswith("REPLACE_WITH_"))
        self.assertTrue(str(template["registry_blob"]).startswith("REPLACE_WITH_"))
        for item in template["items"]:
            self.assertEqual(item["status"], "pending")
            self.assertEqual(item["tester"], "")
            self.assertEqual(item["app_version"], "REPLACE_WITH_MARKETING_VERSION")
            self.assertEqual(item["app_build"], "REPLACE_WITH_CURRENT_PROJECT_VERSION")
            self.assertTrue(str(item["evidence_reference"]).startswith("填写"))
            self.assertEqual(item["evidence_sha256"], "")

    def test_ui_automation_disables_every_notification_center_entry_point(self):
        source_root = REPO_ROOT / "Xjie" / "Xjie"
        sources = {
            str(path.relative_to(source_root)): path.read_text(encoding="utf-8")
            for path in source_root.rglob("*.swift")
        }
        self.assertEqual(guard.deterministic_system_boundary_violations(sources), [])
        scheduler = sources["Services/NotificationScheduler.swift"]
        push = sources["Services/PushNotificationManager.swift"]
        app_delegate = sources["App/AppDelegate.swift"]
        self.assertGreaterEqual(scheduler.count("guard let center = Self.notificationCenter()"), 8)
        self.assertIn("PushNotificationManager.notificationCenter", scheduler)
        self.assertIn("shouldUseNotificationCenter", push)
        self.assertIn("PushNotificationManager.notificationCenter", app_delegate)
        self.assertIn("shouldConfigureSystemServices", app_delegate)
        whitespace_bypass = dict(sources)
        whitespace_bypass["Views/NotificationBypass.swift"] = (
            "let center = `UNUserNotificationCenter`/*gap*/ . `current` ( )"
        )
        self.assertTrue(
            guard.deterministic_system_boundary_violations(whitespace_bypass)
        )


if __name__ == "__main__":
    unittest.main()
