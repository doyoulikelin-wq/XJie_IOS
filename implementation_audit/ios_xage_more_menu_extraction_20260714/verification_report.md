# XAGE upstream integration and More Menu extraction verification

Date: 2026-07-14 (Asia/Shanghai)

## Scope

- Merge the latest `upstream/XAGE` into the current `XAGE` branch.
- Preserve the branch's account security, legal information, feedback, medication quick-entry, Preview, styling, and Chinese-comment work.
- Move the complete More Menu feature family from `XAgeMainView.swift` into `XAgeMoreMenuViews.swift` without raising architecture limits.
- Align the exact XCTest manifests and upstream fail-closed quality policy with the split source layout.

## Required failures preserved

- Before extraction, `regression_guard validate` rejected six conditions: missing branch test IDs plus the existing line, struct, sheet, full-screen, and alert limits. See `pre_refactor_regression_guard_failure.txt`.
- The first full UI run passed 8/9 and correctly failed because the upstream navigation test searched for the old root-level delete-account button. The branch intentionally places deletion inside Account & Security. See `full_ui_navigation_failure.txt`.
- The first small-screen command ran the wrong second test and was rejected by the exact manifest despite both XCTest methods passing. See `small_ui_manifest_mismatch.txt`.
- The first complete tools run exposed stale compiler/submit inventories and raw-structure digests after file extraction and Chinese comments. The policy was updated to lock the new files and current structures; its negative mutation suite remained active.
- The pinned impacted gate stopped before tests because this host has Xcode 26.6 (17F113), not required Xcode 26.3 (17C529). See `toolchain_gate_failure.txt`. The pinned constants were not changed or bypassed.

## Passing evidence

- Debug generic iOS Simulator compilation: passed after the extraction and visibility fixes.
- Unit XCTest result `/tmp/xjie-xage-unit.xcresult`: exact `ios_unit` profile passed, 158 executed, 0 failed, 0 skipped.
- Corrected full UI result `/tmp/xjie-xage-ui-full-fixed.xcresult`: exact `ios_ui_full` profile passed, 9 executed, 0 failed, 0 skipped.
- Focused navigation result `/tmp/xjie-xage-ui-navigation-focused.xcresult`: 1/1 passed after following More Menu → Account & Security → Delete Account and returning to More Menu.
- Corrected small-screen result `/tmp/xjie-xage-ui-small-exact.xcresult`: exact `ios_ui_small` profile passed, 2 executed, 0 failed, 0 skipped, on iPhone SE (3rd generation).
- Exact manifest self-consistency: Unit 158, full UI 9, small UI 2, `ios_all` strict sorted union 167.
- Focused xcresult validator suite: 8/8 passed.
- Focused release-policy mutation test: 1/1 passed after proving the upload-dismiss mutation actually changes source.
- Complete tools gate: 74 executed, 0 failed, 0 skipped.
- `regression_guard.py validate`: passed.
- `regression_guard.py check --working`: passed for all declared impacted domains.
- Unsigned Release compilation under installed Xcode 26.6 / iPhoneOS 26.5 SDK: `** BUILD SUCCEEDED **`. This only checks Release Swift compilation and is not pinned-toolchain release evidence.

## Remaining external gate

The local `impacted` aggregate and compliant unsigned archive cannot be produced on this host because the required Xcode 26.3 / SDK 26.2 toolchain is absent; `backend/.venv` is also absent. The Draft PR GitHub Actions `quality-gate`, configured for Xcode 26.3, remains mandatory before merge. No TestFlight build, signed archive, IPA export, upload, or release was performed.
