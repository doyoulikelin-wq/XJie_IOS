# XAGE support and compliance regression contract

## Minimum reproduction and root cause

- In XAGE `更多`, `帮助与反馈` opened a static explanation that explicitly said online feedback would arrive in a future version, even though `/api/feedback` and the legacy Settings form already existed.
- `关于小捷` mixed the version description with an unspecified privacy statement. There was no independent privacy-policy page or personal-information collection list.
- `注销账号` used destructive red styling in the ordinary menu, making the irreversible action compete with routine account actions.
- Root cause: XAGE duplicated a reduced settings surface after the backend and legacy settings capabilities were built. There was no shared, executable contract for support destinations, so information architecture cleanup accidentally removed the real routes while leaving visually clickable placeholders.

## Permanent invariants

1. XAGE support presents distinct, working entries for usage help, version information, privacy policy, personal-information collection, and feedback.
2. Feedback accepts 2–2000 trimmed characters, preserves the draft on failure, disables duplicate submission while in flight, and closes only after `/api/feedback` succeeds. The server must trim before applying length constraints so whitespace-only input cannot bypass validation; clients attach their platform and current app version.
3. Privacy and collection information render locally without public-network dependency; the privacy page names its policy date and the official policy URL.
4. Every support row has a real destination. No row may claim that a future version will add the action it visually offers.
5. Account deletion stays visually secondary in the ordinary list, but its confirmation page remains explicitly destructive, requires the exact text `注销`, and keeps a safe cancel action.
6. `报告/日常/就医/用药` remain outside the `更多 > 资料` group; adding account/support entries must not reintroduce duplicate business launchers.

## Sibling entry points and states

- XAGE More menu and its help/version/privacy/collection/feedback sheets.
- Legacy Settings feedback form, which uses the same `SettingsViewModel.submitFeedback` backend call.
- Feedback empty, too-short, submitting, success, and failure states.
- Delete-account list row, confirmation input, disabled/enabled confirm, failure, and cancel states.

## Verification plan

- Strengthen the existing named unit/architecture tests without changing the exact iOS test inventory.
- Run the focused XAGE unit test and tracked regression guard.
- Run the existing deterministic high-intensity UI flow on the final merged tree; capture More/support screens and require the shared network audit to report zero escaped requests.
- Verify small-screen, Dynamic Type, VoiceOver order, and real feedback submission on a controlled candidate device. Simulator evidence does not replace those sign-offs.

## Local verification evidence (2026-07-15)

- Named regression: `XjieTests/XAgeCompositeScoresTests/testHomeInformationArchitectureUsesEightStableShortcutsAndProfileOnlyInMore` now covers the five support destinations, feedback length limits, and draft detection.
- Backend contract: `backend/tests/unit/test_feedback_contract.py` covers pre-validation normalization, whitespace-only category rejection, and whitespace-only content rejection — 3/3 passed.
- Command: `python3 tools/regression_guard.py validate` — passed with the tracked Home architecture budgets unchanged.
- Command: `xcodebuild test -project Xjie/Xjie.xcodeproj -scheme Xjie -configuration Debug -destination 'platform=iOS Simulator,name=iPhone 17 Pro' -derivedDataPath /tmp/xjie-stageg-ios-derived -resultBundlePath /tmp/xjie-stageg-ios-final.xcresult -only-testing:XjieTests/XAgeCompositeScoresTests/testHomeInformationArchitectureUsesEightStableShortcutsAndProfileOnlyInMore` — 1 executed, 1 passed, 0 failed; result bundle saved at `/tmp/xjie-stageg-ios-final.xcresult`.
- The support pages and their presentation/alerts were split into `Views/Settings/XAgeSupportComplianceViews.swift` and added to the Xcode Sources phase. `XAgeSettings.swift` remains below its fixed per-file budget; no architecture threshold was raised.
- Remaining limitation: this focused deterministic test proves the navigation/validation contract, not the live `/api/feedback` service, real-device keyboard, Dynamic Type, VoiceOver, or actual account deletion. Those remain candidate sign-offs.
