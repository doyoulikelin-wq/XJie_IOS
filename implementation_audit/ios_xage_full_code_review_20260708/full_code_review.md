# iOS XAGE Full Code Review - 2026-07-08

## Scope

- Repository: `/Users/linlin/Desktop/X/XJie_IOS`
- Local branch: `XAGE`
- Production backend target: `xjie-api`
- Review goal: enforce XAGE as the active app/backend path, find old-version reachable surfaces, check data-source chat regressions, verify server deployment from XAGE, and remove sensitive test residue from tracked files.

## Executive Result

XAGE is now the only active iOS app shell after login: `XjieApp -> MainTabView -> XAgeMainView`.
The production backend was moved off the dirty server `main` worktree and rebuilt from a clean `XAGE` checkout at commit `212efe3`.

The main reachable old-version issue found in this review was the XAGE menu opening the old `MedicationListView`. It has been replaced with a new XAGE liquid-glass medication management view and covered by the high-intensity Simulator UI test.

## Fixed During Review

1. XAGE medication entry
   - Before: `XAgeMoreMenu` opened old `MedicationListView`.
   - After: `XAgeMoreMenu` opens `XAgeMedicationManagementView`, a liquid-glass XAGE page using the existing medication API and local reminder scheduling.
   - Also updated the legacy `SettingsView` medication link to use the XAGE medication page if that old settings surface is ever reached.

2. Parent menu dismissal
   - Before: closing medication management returned to the parent settings/menu sheet, which could continue covering the data page and block controls.
   - After: closing medication management also closes the parent menu, returning directly to the data page.
   - The UI test initially failed at data sort after medication flow; this fix made the full UI test pass.

3. Sensitive test residue
   - `test_data/upload_all.py` and `test_data/upload_for_user8.py` now read test account credentials from `XJIE_UPLOAD_PHONE` and `XJIE_UPLOAD_PASSWORD`.
   - Removed tracked `test_data/upload_log.txt`, which contained a historical JWT-shaped token and report upload log.
   - Replaced fixed test password strings with `UnitTestPassword!42`.

4. Production backend source of truth
   - Created clean server checkout: `/home/mayl/XJie_IOS_XAGE`.
   - Built Docker image: `xjie-backend:xage-212efe3`.
   - Replaced running `xjie-api` with the XAGE image after a smoke container passed `/healthz`.
   - Kept previous container as backup: `xjie-api-backup-20260708174906`.

## Evidence

### Local iOS/XAGE

- `rg -n "MedicationListView\\(" Xjie/Xjie -g '*.swift'`: no reachable Swift call sites remain.
- `xcodebuild -quiet -project Xjie/Xjie.xcodeproj -scheme Xjie -destination 'platform=iOS Simulator,name=iPhone 17 Pro' -derivedDataPath /tmp/xjie-xage-full-review-build build`: passed.
- `xcodebuild -quiet -project Xjie/Xjie.xcodeproj -scheme Xjie -destination 'platform=iOS Simulator,name=iPhone 17 Pro' -skip-testing:XjieUITests -parallel-testing-enabled NO -derivedDataPath /tmp/xjie-xage-full-review-unit2 test`: passed.
- `xcodebuild -quiet -project Xjie/Xjie.xcodeproj -scheme Xjie -destination 'platform=iOS Simulator,name=iPhone 17 Pro' -only-testing:XjieUITests/XAgeHighIntensityContextUITests/testHighIntensityContextFlowUsesRealButtons -parallel-testing-enabled NO -derivedDataPath /tmp/xjie-xage-full-review-ui2 test`: passed.
- `backend/.venv/bin/python -m pytest backend/tests/unit -q`: 57 passed.
- `git diff --check`: passed.

### Production Backend

- Server checkout: `/home/mayl/XJie_IOS_XAGE`, branch `XAGE`, commit `212efe3`.
- Running container: `xjie-api xjie-backend:xage-212efe3`.
- Container tests: `docker exec xjie-api python -m pytest tests/unit/test_chat_message_structure.py tests/unit/test_health_nlu.py -q`: 45 passed.
- Public health checks:
  - `https://www.jianjieaitech.com/healthz`: `{"ok":true}`
  - `http://8.130.213.44:8000/healthz`: `{"ok":true}`

## Review Findings

### Resolved

- XAGE menu no longer opens old medication UI.
- Closing medication management no longer leaves the parent menu overlay blocking the data page.
- Data-source chat reply fix from commit `212efe3` is now deployed to production via XAGE image.
- Tracked test-data files no longer contain the previously found real phone/password/JWT residue.

### Still Present But Not Reachable From XAGE Root

- Old Swift files still exist and compile: `HomeView`, `HealthDataView`, `HealthView`, `OmicsView`, `ChatView`, `SettingsView`, `MedicationListView`.
- Current app root does not navigate into the old five-tab shell: after login, `XjieApp` presents `MainTabView`, and `MainTabView` embeds only `XAgeMainView`.
- These files remain for build compatibility and old feature reuse; further deletion should be handled as a separate cleanup because the old screens still contain referenced models/components.

### Remaining Risks

- `XAgeMainView.swift` remains too large and owns multiple feature surfaces. This is maintainability risk, not a current user-visible routing bug.
- `Info.plist` still uses `http://8.130.213.44:8000` with ATS exception. This matches current production behavior but should eventually move to HTTPS API base.
- Server still has the old dirty `~/XJie_IOS` worktree on `main`; it is no longer the active production backend source, but should not be used for future deploys.
- `xjie-cgm` remains unhealthy on the server. It is separate from this iOS XAGE app/backend switch, but should be investigated before CGM-dependent release claims.
- README/report docs still contain placeholder strings like `OPENAI_API_KEY=<...>` and `sk-xxx`; these are placeholders, not live secrets, but a stricter scanner will still flag them by pattern.

## Deployment Rule Going Forward

Use `/home/mayl/XJie_IOS_XAGE` and the `XAGE` branch for production backend deploys. Do not deploy from the server's old dirty `~/XJie_IOS` `main` worktree.
