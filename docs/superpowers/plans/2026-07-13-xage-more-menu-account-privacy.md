# XAGE More Menu Account and Privacy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix child-page return behavior and add account-security, privacy-policy, and permission-usage pages to `XAgeMoreMenu`.

**Architecture:** Keep `XAgeMoreMenu` as presentation owner, with one local state per child so dismissing a child cannot dismiss the parent. Add small standalone SwiftUI structs in `XAgeMainView.swift` so they can reuse file-private XAGE visual components; split complex bodies into computed views to prevent Swift type-checker regressions. Reuse existing password and deletion services, adding only a pure phone formatter.

**Tech Stack:** Swift, SwiftUI, async/await, XCTest, XCUITest, `APIServiceProtocol`.

## Global Constraints

- Execute directly on current branch `XAGE`; do not create a worktree.
- Preserve all existing uncommitted and untracked user files.
- Do not change backend APIs or add WebView/network loading for legal content.
- Preserve the wording in `docs/privacy.html`.
- Child back buttons return to `XAgeMoreMenu`; only its close button returns to `XAgeMainView`.
- Decompose new SwiftUI expressions to avoid compiler type-check timeouts.

---

### Task 1: Test and implement phone masking

**Files:**
- Modify: `Xjie/Xjie/Utils/Utils.swift`
- Modify: `Xjie/XjieTests/UtilsTests.swift`

**Interfaces:**
- Consumes: `UserInfo.phone`.
- Produces: `Utils.maskedPhone(_ phone: String?) -> String`.

- [ ] **Step 1: Write failing tests**

```swift
// MARK: - maskedPhone

func testMaskedPhoneShowsOnlyRequiredDigits() {
    XCTAssertEqual(Utils.maskedPhone("13800131234"), "138****1234")
}

func testMaskedPhoneRejectsMissingOrMalformedValues() {
    XCTAssertEqual(Utils.maskedPhone(nil), "暂未获取")
    XCTAssertEqual(Utils.maskedPhone(""), "暂未获取")
    XCTAssertEqual(Utils.maskedPhone("1380013123"), "暂未获取")
    XCTAssertEqual(Utils.maskedPhone("13800A31234"), "暂未获取")
}
```

- [ ] **Step 2: Run tests and verify RED**

```bash
xcodebuild test -project Xjie/Xjie.xcodeproj -scheme Xjie -destination 'platform=iOS Simulator,name=iPhone 17 Pro' -only-testing:XjieTests/UtilsTests/testMaskedPhoneShowsOnlyRequiredDigits -only-testing:XjieTests/UtilsTests/testMaskedPhoneRejectsMissingOrMalformedValues
```

Expected: compile failure because `Utils.maskedPhone` is missing.

- [ ] **Step 3: Add the minimal implementation**

```swift
/// 对标准 11 位手机号脱敏；异常值不回显，避免意外暴露账号信息。
static func maskedPhone(_ phone: String?) -> String {
    guard let phone, phone.count == 11, phone.allSatisfy(\.isNumber) else {
        return "暂未获取"
    }
    return "\(phone.prefix(3))****\(phone.suffix(4))"
}
```

- [ ] **Step 4: Run Step 2 again and verify GREEN**

Expected: both selected tests pass.

- [ ] **Step 5: Commit**

```bash
git add Xjie/Xjie/Utils/Utils.swift Xjie/XjieTests/UtilsTests.swift
git commit -m "test: cover XAGE phone masking"
```

---

### Task 2: Keep the more menu open after category return

**Files:**
- Modify: `Xjie/Xjie/Views/Home/XAgeMainView.swift:9642-9877`
- Modify: `Xjie/XjieUITests/XAgeHighIntensityContextUITests.swift:204-233,654-662`

**Interfaces:**
- Consumes: `presentedCategory` and `XAgePanelDestinationView.onClose`.
- Produces: back behavior that clears only `presentedCategory`.

- [ ] **Step 1: Make the existing UI test require the menu after return**

```swift
private func closePresentedPanel() {
    let back = app.buttons["返回"]
    XCTAssertTrue(back.waitForExistence(timeout: 4), "资料详情页应显示返回按钮")
    back.tap()
    XCTAssertTrue(app.buttons["xage.account.报告"].waitForExistence(timeout: 8), "资料详情返回后应保留更多菜单")
    XCTAssertFalse(app.buttons["xage.segment.数据"].isHittable, "不应直接返回 XAgeMainView")
}
```

Replace the post-loop assertion with:

```swift
XCTAssertTrue(app.buttons["xage.account.报告"].exists, "四个资料详情关闭后应仍停留在更多菜单")
```

- [ ] **Step 2: Run the existing flow and verify RED**

```bash
xcodebuild test -project Xjie/Xjie.xcodeproj -scheme Xjie -destination 'platform=iOS Simulator,name=iPhone 17 Pro' -only-testing:XjieUITests/XAgeHighIntensityContextUITests/testHighIntensityContextFlowUsesRealButtons
```

Expected: failure after first category return because the current cover `onDismiss` closes the menu.

- [ ] **Step 3: Remove the coupled parent dismissal**

Delete `categoryDetailWasPresented`, its assignment, and `closeMenuAfterCategoryDetail()`. Replace the cover with:

```swift
.fullScreenCover(item: $presentedCategory) { category in
    XAgePanelDestinationView(
        category: category,
        appleHealthSync: appleHealthSync,
        snapshot: snapshot,
        onSyncAppleHealth: onSyncAppleHealth,
        onClose: { presentedCategory = nil }
    )
}
```

- [ ] **Step 4: Run Step 2 again and verify GREEN**

Expected: all four categories return to the still-visible menu; final explicit menu close returns to data.

- [ ] **Step 5: Commit**

```bash
git add Xjie/Xjie/Views/Home/XAgeMainView.swift Xjie/XjieUITests/XAgeHighIntensityContextUITests.swift
git commit -m "fix: keep XAGE more menu open after child return"
```

---

### Task 3: Add account and security

**Files:**
- Modify: `Xjie/Xjie/Views/Home/XAgeMainView.swift`
- Modify: `Xjie/XjieUITests/XAgeHighIntensityContextUITests.swift`

**Interfaces:**
- Consumes: `/api/users/me`, `Utils.maskedPhone`, `ChangePasswordSheet`, `XAgeDeleteAccountSheet`, and `XAgeAccountViewModel.deleteAccountOnServer()`.
- Produces: `XAgeAccountSecurityViewModel`, `XAgeAccountSecurityView`, and `showAccountSecurity`.

- [ ] **Step 1: Add a failing account-page UI test**

```swift
func testMoreMenuAccountSecurityNavigation() throws {
    app.launch()
    enterDebugValidationSession()
    tapAndWait(app.buttons["xage.more"], for: app.buttons["xage.account.账号与安全"])
    app.buttons["xage.account.账号与安全"].tap()
    XCTAssertTrue(app.descendants(matching: .any)["xage.account.security.page"].waitForExistence(timeout: 5))
    XCTAssertTrue(app.staticTexts["xage.account.security.phone"].exists)
    XCTAssertTrue(app.buttons["xage.account.security.password"].exists)
    XCTAssertTrue(app.buttons["xage.account.security.delete"].exists)
    app.buttons["返回"].tap()
    XCTAssertTrue(app.buttons["xage.account.账号与安全"].waitForExistence(timeout: 5))
}
```

- [ ] **Step 2: Run the new test and verify RED**

```bash
xcodebuild test -project Xjie/Xjie.xcodeproj -scheme Xjie -destination 'platform=iOS Simulator,name=iPhone 17 Pro' -only-testing:XjieUITests/XAgeHighIntensityContextUITests/testMoreMenuAccountSecurityNavigation
```

Expected: the account-security entry is missing.

- [ ] **Step 3: Add menu state, row, and cover**

Remove the obsolete `showDeleteConfirm` state and its parent-level `.sheet`, because deletion presentation moves into the account-security child. Keep `showLogoutConfirm` unchanged.

```swift
@State private var showAccountSecurity = false
```

```swift
XAgeAccountMenuRow(icon: "person.badge.key.fill", title: "账号与安全", subtitle: "手机号、密码与账号注销") {
    showAccountSecurity = true
}
```

```swift
.fullScreenCover(isPresented: $showAccountSecurity) {
    XAgeAccountSecurityView(
        accountVM: accountVM,
        onClose: { showAccountSecurity = false },
        onAccountDeleted: {
            showAccountSecurity = false
            onClose()
        }
    )
    .environmentObject(authManager)
}
```

- [ ] **Step 4: Add the account loader**

```swift
@MainActor
final class XAgeAccountSecurityViewModel: ObservableObject {
    @Published private(set) var phone = "暂未获取"
    @Published private(set) var isLoading = false
    @Published var errorMessage: String?
    private let api: APIServiceProtocol

    init(api: APIServiceProtocol = APIService.shared) { self.api = api }

    func loadAccount() async {
        isLoading = true
        defer { isLoading = false }
        do {
            let user: UserInfo = try await api.get("/api/users/me")
            guard !Task.isCancelled else { return }
            phone = Utils.maskedPhone(user.phone)
        } catch {
            guard !Task.isCancelled else { return }
            phone = "暂未获取"
            errorMessage = error.localizedDescription
        }
    }
}
```

- [ ] **Step 5: Add the decomposed page**

Implement `XAgeAccountSecurityView` with a root `ZStack`, `XAgeLiquidBackground`, and `ScrollView`. Split `header`, `phoneRow`, `passwordRow`, `deleteRow`, and `deleteConfirmation` into computed properties. Required state and actions:

```swift
@EnvironmentObject private var authManager: AuthManager
@ObservedObject var accountVM: XAgeAccountViewModel
@StateObject private var viewModel = XAgeAccountSecurityViewModel()
@State private var showChangePassword = false
@State private var showDeleteConfirm = false
let onClose: () -> Void
let onAccountDeleted: () -> Void
```

The phone row is display-only and uses identifier `xage.account.security.phone`. The password button uses `xage.account.security.password` and presents `ChangePasswordSheet`. The delete button uses `xage.account.security.delete` and presents the existing confirmation. On confirm, capture `authManager.token`, await `deleteAccountOnServer()`, and only on success dismiss, call `onAccountDeleted()`, then `authManager.logout(ifCurrentToken:)`. Preserve `interactiveDismissDisabled(accountVM.isWorking)` and surface `accountVM.errorMessage` in this child. Set the page root identifier to `xage.account.security.page`.

- [ ] **Step 6: Run Task 1 unit tests plus the new UI test**

Run the commands from Task 1 Step 2 and Task 3 Step 2.

Expected: all selected tests pass.

- [ ] **Step 7: Commit**

```bash
git add Xjie/Xjie/Views/Home/XAgeMainView.swift Xjie/XjieUITests/XAgeHighIntensityContextUITests.swift
git commit -m "feat: add XAGE account security page"
```

---

### Task 4: Add local privacy and permission pages

**Files:**
- Modify: `Xjie/Xjie/Views/Home/XAgeMainView.swift`
- Modify: `Xjie/XjieUITests/XAgeHighIntensityContextUITests.swift`
- Read: `docs/privacy.html`
- Read: `Xjie/Xjie/Info.plist`
- Read: `Xjie/Xjie/PrivacyInfo.xcprivacy`

**Interfaces:**
- Consumes: local legal wording and permission declarations.
- Produces: `XAgePrivacyPolicyView`, `XAgePermissionUsageView`, `showPrivacyPolicy`, and `showPermissionUsage`.

- [ ] **Step 1: Add a failing legal-page UI test**

```swift
func testMoreMenuLegalPagesReturnToMenu() throws {
    app.launch()
    enterDebugValidationSession()
    tapAndWait(app.buttons["xage.more"], for: app.buttons["xage.account.隐私政策"])
    for (entry, page) in [
        ("xage.account.隐私政策", "xage.privacy.policy.page"),
        ("xage.account.权限申请与使用情况说明", "xage.permissions.usage.page")
    ] {
        app.buttons[entry].tap()
        XCTAssertTrue(app.descendants(matching: .any)[page].waitForExistence(timeout: 5))
        app.buttons["返回"].tap()
        XCTAssertTrue(app.buttons[entry].waitForExistence(timeout: 5))
    }
}
```

- [ ] **Step 2: Run the test and verify RED**

```bash
xcodebuild test -project Xjie/Xjie.xcodeproj -scheme Xjie -destination 'platform=iOS Simulator,name=iPhone 17 Pro' -only-testing:XjieUITests/XAgeHighIntensityContextUITests/testMoreMenuLegalPagesReturnToMenu
```

Expected: the legal entries are missing.

- [ ] **Step 3: Add menu states, rows, and independent covers**

```swift
@State private var showPrivacyPolicy = false
@State private var showPermissionUsage = false
```

Add “隐私政策” with `hand.raised.fill` and “权限申请与使用情况说明” with `checkmark.shield.fill`. Each row sets only its own state. Each `fullScreenCover` passes an `onClose` that resets only its own state.

- [ ] **Step 4: Add the local policy page**

Define:

```swift
private struct XAgeLegalSection: Identifiable {
    let id: String
    let title: String
    let paragraphs: [String]
    let bullets: [String]
}
```

Implement `XAgePrivacyPolicyView` with the exact introduction, update date `2026年4月9日`, and all eight sections from `docs/privacy.html`. Render paragraphs and bullets as separate text elements. Use the XAGE background/card/header style and identifier `xage.privacy.policy.page`.

- [ ] **Step 5: Add the permission page**

Implement `XAgePermissionUsageView` with seven cards: 相机、相册读取、相册写入、麦克风、语音识别、Apple 健康读取、Apple 健康写入. Each card must show application timing, purpose, and effect of denial using the exact purposes from `Info.plist`; the Apple Health write card states that the current version does not request write access. Add an opening note that authorization is voluntary and adjustable in iOS Settings. Use identifier `xage.permissions.usage.page`.

- [ ] **Step 6: Run Step 2 again and verify GREEN**

Expected: both pages open offline and their back buttons return to the more menu.

- [ ] **Step 7: Commit**

```bash
git add Xjie/Xjie/Views/Home/XAgeMainView.swift Xjie/XjieUITests/XAgeHighIntensityContextUITests.swift
git commit -m "feat: add XAGE privacy and permission pages"
```

---

### Task 5: Regression verification

**Files:**
- Verify: `Xjie/Xjie/Views/Home/XAgeMainView.swift`
- Verify: `Xjie/Xjie/Utils/Utils.swift`
- Verify: `Xjie/XjieTests/UtilsTests.swift`
- Verify: `Xjie/XjieUITests/XAgeHighIntensityContextUITests.swift`

**Interfaces:**
- Consumes: Tasks 1–4.
- Produces: test/build evidence and a scoped clean diff.

- [ ] **Step 1: Run Utils unit tests**

```bash
xcodebuild test -project Xjie/Xjie.xcodeproj -scheme Xjie -destination 'platform=iOS Simulator,name=iPhone 17 Pro' -only-testing:XjieTests/UtilsTests
```

Expected: zero failures.

- [ ] **Step 2: Run focused XAGE UI regressions**

```bash
xcodebuild test -project Xjie/Xjie.xcodeproj -scheme Xjie -destination 'platform=iOS Simulator,name=iPhone 17 Pro' -only-testing:XjieUITests/XAgeHighIntensityContextUITests/testHighIntensityContextFlowUsesRealButtons -only-testing:XjieUITests/XAgeHighIntensityContextUITests/testMoreMenuAccountSecurityNavigation -only-testing:XjieUITests/XAgeHighIntensityContextUITests/testMoreMenuLegalPagesReturnToMenu
```

Expected: all three UI tests pass.

- [ ] **Step 3: Build Debug**

```bash
xcodebuild build -project Xjie/Xjie.xcodeproj -scheme Xjie -configuration Debug -destination 'platform=iOS Simulator,name=iPhone 17 Pro'
```

Expected: `BUILD SUCCEEDED` without a type-check timeout.

- [ ] **Step 4: Check scope and whitespace**

```bash
git diff --check
git status --short
git diff -- Xjie/Xjie/Views/Home/XAgeMainView.swift Xjie/Xjie/Utils/Utils.swift Xjie/XjieTests/UtilsTests.swift Xjie/XjieUITests/XAgeHighIntensityContextUITests.swift
```

Expected: no whitespace error; pre-existing user edits remain intact; unrelated workspace files remain unstaged.

- [ ] **Step 5: Commit only if verification required a correction**

```bash
git add Xjie/Xjie/Views/Home/XAgeMainView.swift Xjie/Xjie/Utils/Utils.swift Xjie/XjieTests/UtilsTests.swift Xjie/XjieUITests/XAgeHighIntensityContextUITests.swift
git commit -m "test: verify XAGE more menu flows"
```

Expected: skip this commit if no corrective edit was needed.
