# XJie iOS Repository Rules

These rules are the repository-local development and delivery policy.

## Before changing behavior

1. Read `docs/quality/REGRESSION_POLICY.md` and inspect related production code and tests.
2. Update `quality/change_impact.json` with the real scope, risk and verification plan.
3. Add or strengthen a focused regression test when the change fixes a bug or changes user-visible behavior. Focused tests are preferred over automatically running every repository test.

## Default lightweight gates

- Normal editing: `/usr/bin/python3 -I tools/run_regression_gate.py fast`.
- Stable PR candidate: `/usr/bin/python3 -I tools/run_regression_gate.py impacted`.
- Internal TestFlight: `/usr/bin/python3 -I tools/run_regression_gate.py internal-testflight`, followed by `scripts/release_testflight.sh` when an upload is actually authorized.
- Final release: `/usr/bin/python3 -I tools/run_regression_gate.py release`.
- The default gates check repository whitespace and configuration syntax. `impacted` and later stages also perform a generic iOS Simulator compilation and Python source compilation. They do not automatically run the complete iOS Unit/UI suites, complete backend suite, PostgreSQL integration suite or exact test inventories.
- A lightweight green result proves only the checks printed by that command. It is not evidence that every business path, UI interaction, real device, HealthKit, AI response or database migration works.

## Optional strict gates

- Add `--strict` to `fast`, `impacted`, `internal-testflight`, `release`, `assert-internal-testflight`, `assert-release` or `qualify-testflight` to use the preserved comprehensive implementation.
- Set `XJIE_STRICT_GATES=1` when invoking tracked hooks, or configure the same repository variable in CI, to restore the comprehensive static, XCTest, backend, PostgreSQL and archive checks.
- Run strict mode for high-risk account, HealthKit, AI safety, migration, signing or release changes when the additional assurance is worth the cost.
- Exact XCTest/Python inventories remain stored under `quality/` for strict audits, but they are no longer mandatory in the default lightweight path.

## Hooks, CI and delivery

- Never use `git commit --no-verify` or `git push --no-verify`.
- Default hooks enforce whitespace and prohibit direct updates to protected `main` and legacy `XAGE`. Strict hook validation is opt-in through `XJIE_STRICT_GATES=1`.
- GitHub Actions must keep a `quality-gate` check for `main`. By default it runs lightweight policy, backend syntax and iOS compilation checks; repository variable `XJIE_STRICT_GATES=1` enables the retained comprehensive steps.
- `main` is the canonical PR and release branch. `XAGE` is retained as a read-only historical branch.

## Release safety retained in lightweight mode

- TestFlight upload must still use `scripts/release_testflight.sh`; do not call an uploader directly.
- The release script must continue validating the generated app/IPA identity, signing profile, entitlements, sensitive-file scan and upload receipt. Simplifying regression coverage does not authorize weakening package or credential safety.
- A successful upload is not proof that Apple processing, real-device behavior, HealthKit, accessibility, third-party keyboards or live AI answers have been validated. Record those checks manually or run strict qualification when that claim is required.

## Source and workspace safety

- Preserve unrelated staged, unstaged and untracked user changes.
- Do not use destructive Git commands to clean the worktree.
- Use `apply_patch` for hand edits and run `git diff --check` before handoff.
- Keep the existing XAGE seven-file responsibility split unless the user explicitly requests an architecture change.
