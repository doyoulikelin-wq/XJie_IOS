# XJie iOS XAGE Repository Rules

These rules supplement `/Users/linlin/Desktop/X/AGENTS.md` and are mandatory for every change in this repository.

## Before editing behavior

1. Read the workspace memory and `/Users/linlin/Desktop/X/XJie_IOS/docs/quality/REGRESSION_POLICY.md`.
2. Search existing resolved issues, risks, regression contracts, production code, and tests for the same class of behavior.
3. Update `quality/change_impact.json` with the real root cause or risk hypothesis, all affected domains, sibling-entry scan, invariant IDs, tests, manual matrix, and remaining risk.
4. For a bug fix or user-visible behavior change, add or strengthen a named regression test. The test must contain a meaningful assertion or interaction and must be staged with the production change.

## Hard gates

- Run `python3 tools/regression_guard.py validate` before and after editing.
- Run `python3 tools/regression_guard.py check --working` before describing a behavior change as complete.
- Run `python3 tools/run_regression_gate.py impacted` for the domains in `quality/change_impact.json`.
- Never use `git commit --no-verify` or `git push --no-verify`. The tracked hooks are part of the delivery contract.
- A failing or skipped required gate blocks commit, completion language, deployment, and release.
- CI `quality-gate` must be green on the exact commit. A green job obtained through `|| true`, swallowed pipeline failures, skipped required tests, or a different SHA is invalid.

## Conservative XAGE rule

`Xjie/Xjie/Views/Home/XAgeMainView.swift` currently combines data, chat, X age, settings, account, upload, keyboard, navigation, presentations, and alerts. Until it is split, any modification to this file is treated as UI + interaction + AI client + Health client + account risk. It may not grow beyond the architecture limits in `quality/regression_contracts.json`; new responsibilities must be extracted into focused files.

The UI prompt loop in `XAgeHighIntensityContextUITests` proves input and shell interactions only. It must not be cited as proof that AI answer content, subject isolation, routing, citations, or safety are correct. Those claims require deterministic backend/client assertions or a controlled end-to-end evaluation that verifies the final assistant response.

## Release gate

TestFlight must not be archived or uploaded through an ad-hoc direct command. Required order:

1. Commit and push the exact candidate so the worktree is clean and `HEAD` equals upstream.
2. Run `python3 tools/run_regression_gate.py release`.
3. Record any required real-device HealthKit, Apple Watch, third-party keyboard, accessibility, and controlled AI-answer sign-offs.
4. Immediately before archive/export, run `python3 tools/run_regression_gate.py assert-release`.
5. Use `scripts/release_testflight.sh --archive-only` or `scripts/release_testflight.sh --upload`; do not call `xcodebuild -exportArchive` directly.
6. If source, tests, build settings, or `HEAD` changes, the evidence is invalid and the full release gate must run again.

For a HealthKit release, Simulator results never replace real-device authorization, foreground sync, background observer, and source/account verification. For an AI release, typing prompts without asserting the returned answer never counts as AI-content validation.
