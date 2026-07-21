# XAGE 更多菜单拆分与 upstream 门禁适配 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变 XAGE 现有页面行为的前提下，把“更多”菜单及其子页面从 `XAgeMainView.swift` 拆入单一聚焦文件，合入最新 `upstream/XAGE`，通过精确回归门禁并创建 Draft PR。

**Architecture:** 以 `// MARK: - 设置、资料与账号管理` 为完整迁移边界，将该标记到文件末尾的实现原样移入 `XAgeMoreMenuViews.swift`，根页面仍以原参数和回调创建 `XAgeMoreMenu`。合并冲突采用 upstream 的聊天静止边界实现，同时保留当前分支的 XAGE 功能；只放宽六个真实跨文件依赖的 Swift 可见性，不提高任何架构上限。

**Tech Stack:** Swift 5、SwiftUI、XCTest/XCUITest、Xcode project (`project.pbxproj`)、Python 3 质量门禁、Git/GitHub CLI。

## Global Constraints

- 直接在当前 `XAGE` 分支执行，不创建 worktree 分支；质量 hook 自己创建的只读临时候选 worktree 不受此限制。
- 不纳入三个用户既有未跟踪路径：`Xjie/Xjie.xcodeproj/project.xcworkspace/`、`docs/superpowers/plans/2026-07-13-xage-key-logic-comments.md`、`docs/superpowers/specs/2026-07-13-xage-key-logic-comments-design.md`。
- 不修改 `quality/regression_contracts.json` 中 `XAgeMainView.swift` 的行数、struct/enum、sheet、full-screen cover、alert 等上限。
- 不改变 `XAgeMoreMenu` 的初始化参数、状态所有权、回调方向、页面文案、视觉、导航行为、接口请求和 accessibility identifier。
- `XjieApp.swift` 同时保留 upstream 的 `runUIAutomationNetworkProbeIfNeeded()` 与当前分支 `debugFlag(_:)` 的中文说明。
- 聊天滚动只使用 upstream 的同步无动画 `ChatAutoScroll.toBottom(Self.bottomAnchorID, using: proxy)`，并保留 `dismissChatKeyboard()`、`sendStarterPrompt(_:)`、`retryMessage(id:)`。
- 完整 UI 测试类必须继承 `XAgeUITestCase`；只有共享基类可创建、启动、重启或终止 `XCUIApplication`。
- 精确 XCTest 数量必须是 Unit 158、完整 UI 9、小屏 UI 2、Unit + 完整 UI 167；不使用最低数量、通配符、skip 或 expected failure 代替精确 ID。
- 每个强制 `xcodebuild test` 都必须写入新的 `.xcresult`，并由 `tools/validate_xcresult.py` 对应 profile 校验。
- 任一必需门禁失败都要保存原始证据、说明根因和永久约束，并在修复后的新提交上重新完成闭环；不得用简单重跑覆盖失败。
- 所有文件编辑使用 `apply_patch`；不使用 `git commit --no-verify`、`git push --no-verify` 或其他跳过 hook 的参数。

---

## File Map

| Path | Responsibility | Planned action |
|---|---|---|
| `Xjie/Xjie/Views/Home/XAgeMainView.swift` | XAGE 根页面、数据、报告、聊天和 X 年龄页面 | 删除完整“设置、资料与账号管理”尾部区域；做五个依赖类型的最小可见性调整；采用 upstream 聊天冲突版本 |
| `Xjie/Xjie/Views/Home/XAgeMoreMenuViews.swift` | 更多菜单、账号安全、法律说明、问题反馈、关于、家庭管理 | 新建；原样承接迁移区域；将 `XAgeMoreMenu` 改为模块内可见 |
| `Xjie/Xjie/App/XjieApp.swift` | App 启动与 Debug 自动化探针 | 合并双方 Debug 实现 |
| `Xjie/Xjie.xcodeproj/project.pbxproj` | Xcode 文件和 Sources 图 | 只新增新 Swift 文件的四处引用并保留当前分支已有文件引用 |
| `Xjie/XjieTests/UtilsTests.swift` | Utils、样式和用药输入单元测试 | 把 3 个方法级 `@MainActor` 测试改为显式主线程执行，保留测试 ID |
| `Xjie/XjieUITests/XAgeHighIntensityContextUITests.swift` | XAGE 完整 UI 套件 | 将 4 个当前分支用例接入 upstream 共享 app 生命周期，并保留更多菜单返回语义断言 |
| `quality/expected_xctests.json` | XCTest 精确清单 | 增加 9 个 Unit ID 和 4 个完整 UI ID，并重建 167 项合集 |
| `AGENTS.md` | 仓库强制工程规则 | 将受控 XCTest 数量更新为 158/9/2/167 |
| `docs/quality/REGRESSION_POLICY.md` | 回归制度 | 同步精确数量和本轮闭环说明 |
| `quality/change_impact.json` | 当前改动影响与验证声明 | 在 upstream 聊天影响基础上登记 XAGE 拆分、功能增量、工程图和测试清单变化 |
| `tools/tests/test_validate_xcresult.py` | xcresult validator 的工具回归 | 把精确计数断言更新为 158 与 167 |
| `implementation_audit/ios_xage_more_menu_extraction_20260714/pre_refactor_regression_guard_failure.txt` | 首次门禁失败证据 | 新建并记录此前合并候选的六项阻断 |
| `implementation_audit/ios_xage_more_menu_extraction_20260714/verification_report.md` | 最终本地验证证据 | 新建并记录 exact SHA、命令、result bundle 与结论 |

### Task 1: 建立合并候选并按既定策略解决冲突

**Files:**
- Modify: `Xjie/Xjie/App/XjieApp.swift`
- Modify: `Xjie/Xjie/Views/Home/XAgeMainView.swift`
- Create: `implementation_audit/ios_xage_more_menu_extraction_20260714/pre_refactor_regression_guard_failure.txt`

**Interfaces:**
- Consumes: 当前 `XAGE`、`upstream/XAGE`、设计文档 `docs/superpowers/specs/2026-07-14-xage-more-menu-extraction-design.md`
- Produces: 未提交但无冲突标记的 merge candidate；后续任务在该 candidate 上拆分与适配

- [ ] **Step 1: 确认当前分支、远端和用户未跟踪文件边界**

Run:

```bash
git status --short --branch
git fetch upstream XAGE
git rev-parse --abbrev-ref HEAD
git rev-parse upstream/XAGE
```

Expected: 当前分支为 `XAGE`；只显示计划文档和三个已知未跟踪路径，不出现未知 tracked 修改；保存新的 upstream SHA 供最终报告引用。

- [ ] **Step 2: 以不自动提交方式创建 merge candidate**

Run:

```bash
git merge --no-ff --no-commit upstream/XAGE
git status --short
```

Expected: merge 停在待提交状态；若仍与已知情况一致，只在 `XjieApp.swift` 和 `XAgeMainView.swift` 出现 `UU`。

- [ ] **Step 3: 解决 `XjieApp.swift` 冲突并保留双方 Debug 入口**

Apply the conflict resolution so the `#if DEBUG` block keeps both callable paths:

```swift
#if DEBUG
runUIAutomationNetworkProbeIfNeeded()
#endif
```

Keep the existing Chinese documentation and implementation of:

```swift
private func debugFlag(_ name: String) -> Bool
```

Run:

```bash
rg -n '<<<<<<<|=======|>>>>>>>' Xjie/Xjie/App/XjieApp.swift
rg -n 'runUIAutomationNetworkProbeIfNeeded|debugFlag' Xjie/Xjie/App/XjieApp.swift
```

Expected: first command has no output; both symbol names are present.

- [ ] **Step 4: 解决 `XAgeMainView.swift` 聊天冲突**

Keep this upstream call as the only bottom-scroll implementation:

```swift
ChatAutoScroll.toBottom(Self.bottomAnchorID, using: proxy)
```

Keep the upstream methods and their call sites:

```swift
private func dismissChatKeyboard()
private func sendStarterPrompt(_ prompt: String)
private func retryMessage(id: UUID)
```

Remove the conflicting current-branch implementation that schedules `DispatchQueue.main.async` plus animated `proxy.scrollTo` calls. Preserve non-conflicting Chinese method comments.

Run:

```bash
rg -n '<<<<<<<|=======|>>>>>>>' Xjie/Xjie/Views/Home/XAgeMainView.swift
rg -n 'ChatAutoScroll\.toBottom|dismissChatKeyboard|sendStarterPrompt|retryMessage' Xjie/Xjie/Views/Home/XAgeMainView.swift
```

Expected: no conflict markers; all four upstream contracts are present.

- [ ] **Step 5: 保存已发生的首轮门禁失败证据**

Create `implementation_audit/ios_xage_more_menu_extraction_20260714/pre_refactor_regression_guard_failure.txt` with exactly this factual record:

```text
Date: 2026-07-14 Asia/Shanghai
Candidate: current XAGE merged with upstream/XAGE before architecture extraction
Command: /usr/bin/python3 -I tools/regression_guard.py validate
Result: FAIL (blocking)

Observed failures:
1. Exact XCTest inventory did not include all tests introduced by the XAGE branch.
2. Xjie/Xjie/Views/Home/XAgeMainView.swift had 11409 lines, above maximum 10305.
3. XAgeMainView.swift had 102 struct declarations, above maximum 100.
4. XAgeMainView.swift had 21 sheet presentations, above maximum 19.
5. XAgeMainView.swift had 9 full-screen presentations, above maximum 6.
6. XAgeMainView.swift had 23 alert presentations, above maximum 20.

Root-cause direction:
- The XAGE branch added tests that predated upstream's exact XCTest manifest.
- The more-menu feature family remained inside the already-large XAgeMainView.swift.

Required invariant before closure:
- Register every new XCTest ID exactly.
- Move the complete more-menu section into XAgeMoreMenuViews.swift without increasing architecture limits.
- Run all mandatory gates on a new committed tree; a green rerun alone does not erase this failure.
```

- [ ] **Step 6: 标记已解决文件并确认 merge candidate 状态**

Run:

```bash
git add Xjie/Xjie/App/XjieApp.swift Xjie/Xjie/Views/Home/XAgeMainView.swift implementation_audit/ios_xage_more_menu_extraction_20260714/pre_refactor_regression_guard_failure.txt
git diff --check
git status --short
```

Expected: no `UU` entries and no whitespace errors; merge remains uncommitted.

### Task 2: 以完整边界拆出更多菜单文件

**Files:**
- Create: `Xjie/Xjie/Views/Home/XAgeMoreMenuViews.swift`
- Modify: `Xjie/Xjie/Views/Home/XAgeMainView.swift`
- Modify: `Xjie/Xjie.xcodeproj/project.pbxproj`

**Interfaces:**
- Consumes: `Binding<XAgeDataPanelCategory>`、`AppleHealthSyncViewModel`、`XAgeServerSyncSnapshot`、异步 Health 同步回调、分类选择回调、关闭回调
- Produces: `struct XAgeMoreMenu: View`，初始化接口保持设计文档中的六个参数不变

- [ ] **Step 1: 先运行架构门禁，确认旧布局仍被拒绝**

Run:

```bash
/usr/bin/python3 -I tools/regression_guard.py validate
```

Expected: FAIL，至少包含 `XAgeMainView.swift` 行数、结构体或 presentation 上限，以及精确 XCTest 清单阻断；输出与 Task 1 的证据方向一致。

- [ ] **Step 2: 创建更多菜单聚焦文件并迁移完整尾部区域**

Create the file with these imports and then copy, without behavioral edits, every declaration from the source marker through the old end of file:

```swift
import SwiftUI

// MARK: - 设置、资料与账号管理

struct XAgeMoreMenu: View {
    // 此处接原 XAgeMoreMenu 的现有属性、初始化器和 body，内容保持不变。
}
```

The actual patch must include the complete existing implementations under that marker, including account security, password change, account deletion, privacy policy, permission usage, problem feedback, about, personal information, medication navigation, family linking/invite/member authorization, menu rows and section titles. Delete the same marker-through-EOF range from `XAgeMainView.swift` so every declaration has exactly one owner.

Run:

```bash
rg -n '^// MARK: - 设置、资料与账号管理$' Xjie/Xjie/Views/Home/XAgeMainView.swift Xjie/Xjie/Views/Home/XAgeMoreMenuViews.swift
rg -n '^(private )?struct XAgeMoreMenu:' Xjie/Xjie/Views/Home/XAgeMainView.swift Xjie/Xjie/Views/Home/XAgeMoreMenuViews.swift
wc -l Xjie/Xjie/Views/Home/XAgeMainView.swift Xjie/Xjie/Views/Home/XAgeMoreMenuViews.swift
```

Expected: marker and `XAgeMoreMenu` each occur only in the new file; `XAgeMainView.swift` is below 10305 lines.

- [ ] **Step 3: 只放宽六个真实跨文件符号的可见性**

Apply these exact declaration changes:

```swift
// XAgeMainView.swift
enum XAgeKeyboard { /* existing cases unchanged */ }
struct XAgeServerSyncSnapshot { /* existing members unchanged */ }
struct XAgeMetricDetailRow: View { /* existing implementation unchanged */ }
enum XAgeDataPanelCategory { /* existing cases unchanged */ }
struct XAgePanelDestinationView: View { /* existing implementation unchanged */ }

// XAgeMoreMenuViews.swift
struct XAgeMoreMenu: View { /* migrated implementation unchanged */ }
```

All nested/helper declarations that are used only inside their own file remain `private`.

Run:

```bash
rg -n '^private (enum XAgeKeyboard|struct XAgeServerSyncSnapshot|struct XAgeMetricDetailRow|enum XAgeDataPanelCategory|struct XAgePanelDestinationView|struct XAgeMoreMenu)' Xjie/Xjie/Views/Home/XAgeMainView.swift Xjie/Xjie/Views/Home/XAgeMoreMenuViews.swift
```

Expected: no output.

- [ ] **Step 4: 给 Xcode 工程增加且仅增加四处文件图引用**

Use the verified-unused IDs `A90004` and `B90004`. Add one `PBXBuildFile`, one `PBXFileReference`, one Home group child and one Xjie target Sources entry, following the adjacent `XAgeStyleComponents.swift` shape:

```pbxproj
A90004 /* XAgeMoreMenuViews.swift in Sources */ = {isa = PBXBuildFile; fileRef = B90004 /* XAgeMoreMenuViews.swift */; };
B90004 /* XAgeMoreMenuViews.swift */ = {isa = PBXFileReference; lastKnownFileType = sourcecode.swift; path = XAgeMoreMenuViews.swift; sourceTree = "<group>"; };
```

Add `B90004` to the Home group beside the other XAGE view files and `A90004` to the Xjie target Sources phase beside `XAgeStyleComponents.swift`. Re-run `rg -n 'A90004|B90004'` after the merge; abort this step and select the next unused `A90005`/`B90005` pair only if upstream has independently claimed either ID.

Run:

```bash
rg -n 'XAgeMoreMenuViews\.swift' Xjie/Xjie.xcodeproj/project.pbxproj
/usr/bin/python3 -I tools/regression_guard.py validate
```

Expected: exactly four project-file references; project source graph checks pass, while test inventory may remain blocking until Task 3.

- [ ] **Step 5: 进行 Swift 编译级检查**

Run:

```bash
rm -rf /tmp/xjie-xage-extraction-derived
xcodebuild build -project Xjie/Xjie.xcodeproj -scheme Xjie -configuration Debug -destination 'generic/platform=iOS Simulator' -derivedDataPath /tmp/xjie-xage-extraction-derived CODE_SIGNING_ALLOWED=NO
```

Expected: `** BUILD SUCCEEDED **`; no inaccessible/private symbol, duplicate declaration or missing Sources reference error.

### Task 3: 让新增测试遵守 upstream 生命周期和精确发现规则

**Files:**
- Modify: `Xjie/XjieTests/UtilsTests.swift`
- Modify: `Xjie/XjieUITests/XAgeHighIntensityContextUITests.swift`

**Interfaces:**
- Consumes: `XAgeUITestCase.launchApplication()` and inherited `app`; `MainActor.run`; existing UI helpers `enterDebugValidationSession()`、`tapAndWait`、`scrollIntoViewOnActiveScreen`
- Produces: 9 stable Unit IDs and 4 new full UI IDs with no independent app lifecycle tokens

- [ ] **Step 1: 改写三个共享样式测试的主线程边界，保持方法名不变**

Replace each method-level actor annotation with an async method and body-level main-actor hop. The three declarations must begin directly with `func test...` and use this shape:

```swift
func testXAgeGlassTextFieldSupportsGenericFocusFields() async {
    await MainActor.run {
        var text = ""
        let textBinding = Binding(
            get: { text },
            set: { text = $0 }
        )
        let focusState = FocusState<XAgeStyleTestField?>()
        let field = XAgeGlassTextField(
            placeholder: "测试输入",
            text: textBinding,
            field: .input,
            focusedField: focusState.projectedValue
        )
        XCTAssertEqual(field.placeholder, "测试输入")
        XCTAssertEqual(field.field, .input)
    }
}

func testXAgeStyleComponentsPreviewHasStandaloneInitializer() async {
    await MainActor.run {
        _ = XAgeStyleComponentsPreview()
    }
}

func testXAgeRoundedFieldBackgroundUsesEighteenPointDefaultRadius() async {
    await MainActor.run {
        let defaultBackground = XAgeRoundedFieldBackground()
        let customBackground = XAgeRoundedFieldBackground(cornerRadius: 24)
        XCTAssertEqual(defaultBackground.cornerRadius, 18)
        XCTAssertEqual(customBackground.cornerRadius, 24)
    }
}
```

Run:

```bash
rg -n -B1 '@MainActor|func testXAge(GlassTextField|StyleComponents|RoundedField)' Xjie/XjieTests/UtilsTests.swift
```

Expected: the three test method names remain unchanged and none has method-level `@MainActor`.

- [ ] **Step 2: 将四个 UI 用例接入共享 application 生命周期**

Keep the existing bodies and identifiers for:

```swift
func testMoreMenuAccountSecurityNavigation() throws
func testMoreMenuLegalPagesReturnToMenu() throws
func testMedicationEditorQuickInputsReplaceAndAppend() throws
func testMoreMenuProblemFeedbackShowsInputAndContactEmail() throws
```

At the first line of each body, replace direct launch with:

```swift
launchApplication()
enterDebugValidationSession()
```

The class declaration must remain:

```swift
final class XAgeHighIntensityContextUITests: XAgeUITestCase
```

Also retain the current branch's changed navigation assertions:

```swift
XCTAssertTrue(app.buttons["xage.account.报告"].exists, "四个资料详情关闭后应仍停留在更多菜单")
```

and:

```swift
private func closePresentedPanel() {
    let back = app.buttons["返回"]
    XCTAssertTrue(back.waitForExistence(timeout: 4), "资料详情页应显示返回按钮")
    back.tap()
    XCTAssertTrue(app.buttons["xage.account.报告"].waitForExistence(timeout: 8), "资料详情返回后应保留更多菜单")
    XCTAssertFalse(app.buttons["xage.segment.数据"].isHittable, "不应直接返回 XAgeMainView")
}
```

Run:

```bash
rg -n 'XCUIApplication|app\.launch\(|app\.terminate\(' Xjie/XjieUITests/XAgeHighIntensityContextUITests.swift
rg -n 'testMoreMenuAccountSecurityNavigation|testMoreMenuLegalPagesReturnToMenu|testMedicationEditorQuickInputsReplaceAndAppend|testMoreMenuProblemFeedbackShowsInputAndContactEmail' Xjie/XjieUITests/XAgeHighIntensityContextUITests.swift
```

Expected: first command has no output; each new test name occurs exactly once.

- [ ] **Step 3: 运行 test inventory parser 的 focused 工具测试，确认此时仍按旧清单拒绝新增 ID**

Run:

```bash
/usr/bin/python3 -I -m unittest tools.tests.test_validate_xcresult
```

Expected: FAIL because version-controlled expectations still assert Unit 149 / combined 154 or omit the 13 new IDs. This is the red phase for Task 4.

### Task 4: 更新精确 XCTest 清单和数量断言

**Files:**
- Modify: `quality/expected_xctests.json`
- Modify: `tools/tests/test_validate_xcresult.py`
- Modify: `AGENTS.md`
- Modify: `docs/quality/REGRESSION_POLICY.md`

**Interfaces:**
- Consumes: source-discovered XCTest method names from Task 3
- Produces: `ios_unit` 158 IDs、`ios_ui_full` 9 IDs、`ios_ui_small` 2 IDs、`ios_all` 167 IDs

- [ ] **Step 1: 将九个 Unit ID 以字典序加入 `ios_unit`**

Add exactly:

```text
XjieTests/UtilsTests/testMaskedPhoneRejectsMissingOrMalformedValues
XjieTests/UtilsTests/testMaskedPhoneShowsOnlyRequiredDigits
XjieTests/UtilsTests/testMedicationQuickInputExposesApprovedOptions
XjieTests/UtilsTests/testMedicationQuickInputReplacesDoseAndFrequency
XjieTests/UtilsTests/testMedicationQuickInstructionAppendsWithChineseComma
XjieTests/UtilsTests/testMedicationQuickInstructionUsesPhraseForEmptyOrWhitespaceContent
XjieTests/UtilsTests/testXAgeGlassTextFieldSupportsGenericFocusFields
XjieTests/UtilsTests/testXAgeRoundedFieldBackgroundUsesEighteenPointDefaultRadius
XjieTests/UtilsTests/testXAgeStyleComponentsPreviewHasStandaloneInitializer
```

- [ ] **Step 2: 将四个 UI ID 以字典序加入 `ios_ui_full`**

Add exactly:

```text
XjieUITests/XAgeHighIntensityContextUITests/testMedicationEditorQuickInputsReplaceAndAppend
XjieUITests/XAgeHighIntensityContextUITests/testMoreMenuAccountSecurityNavigation
XjieUITests/XAgeHighIntensityContextUITests/testMoreMenuLegalPagesReturnToMenu
XjieUITests/XAgeHighIntensityContextUITests/testMoreMenuProblemFeedbackShowsInputAndContactEmail
```

Keep `ios_ui_small` unchanged with its two existing IDs.

- [ ] **Step 3: 重建 `ios_all` 为 `ios_unit` 与 `ios_ui_full` 的严格有序并集**

Insert the same 13 IDs into `ios_all` in lexical order. Validate structure and exact relations without writing the file from Python:

```bash
/usr/bin/python3 -I - <<'PY'
import json
from pathlib import Path
p = json.loads(Path('quality/expected_xctests.json').read_text())['profiles']
assert len(p['ios_unit']) == 158
assert len(p['ios_ui_full']) == 9
assert len(p['ios_ui_small']) == 2
assert len(p['ios_all']) == 167
assert p['ios_unit'] == sorted(set(p['ios_unit']))
assert p['ios_ui_full'] == sorted(set(p['ios_ui_full']))
assert p['ios_all'] == sorted(set(p['ios_unit']) | set(p['ios_ui_full']))
print('exact XCTest manifests: OK (158/9/2/167)')
PY
```

Expected: `exact XCTest manifests: OK (158/9/2/167)`.

- [ ] **Step 4: 同步工具断言和制度中的精确数量**

In `tools/tests/test_validate_xcresult.py`, change exact assertions from:

```python
self.assertEqual(len(...), 149)
self.assertEqual(len(...), 154)
```

to:

```python
self.assertEqual(len(...), 158)
self.assertEqual(len(...), 167)
```

In `AGENTS.md` and `docs/quality/REGRESSION_POLICY.md`, replace every current-suite statement `Unit 149` with `Unit 158`, `完整 UI 5` with `完整 UI 9`, and `并集 154` with `并集 167`; keep small-screen 2 unchanged. Historical statements tied to an explicitly named old commit remain historical and are not rewritten as current evidence.

- [ ] **Step 5: 运行精确清单工具测试和静态 validate**

Run:

```bash
/usr/bin/python3 -I -m unittest tools.tests.test_validate_xcresult
/usr/bin/python3 -I tools/regression_guard.py validate
```

Expected: focused Python suite passes; `regression_guard validate` passes the XCTest inventory and architecture limits without changing `quality/regression_contracts.json`.

### Task 5: 登记组合改动的影响、永久约束和验证计划

**Files:**
- Modify: `quality/change_impact.json`
- Modify: `docs/quality/REGRESSION_POLICY.md`

**Interfaces:**
- Consumes: upstream 的聊天稳定性 change impact、Task 1 失败证据、Task 2 架构边界、Task 4 精确清单
- Produces: 能驱动 `run_regression_gate.py impacted` 的完整影响域与可审计闭环

- [ ] **Step 1: 将 change identity 改为本轮组合集成**

Set the top-level identity fields to:

```json
{
  "schema_version": 1,
  "change_id": "2026-07-14-ios-xage-upstream-integration-more-menu-extraction",
  "change_type": "refactor",
  "summary": "合入 upstream/XAGE 的聊天可访问性静止边界，保留当前分支的账号安全、法律说明、用药快捷输入和问题反馈功能，并将更多菜单完整拆出 XAgeMainView 以满足既有架构上限。"
}
```

Replace `root_cause` with a statement containing all three facts: upstream added exact XCTest and architecture gates after this branch diverged; current XAGE tests were absent from the manifest; more-menu features kept `XAgeMainView.swift` above existing limits. Replace `risk_hypothesis` with the concrete risks of partial-section extraction, widened unrelated visibility, independent UI app lifecycle, stale exact manifests, and loss of upstream synchronous chat quiescence.

- [ ] **Step 2: 登记所有受影响域和契约**

Ensure `impacted_domains` is a sorted unique array containing:

```json
[
  "ios_account_client",
  "ios_chat_client",
  "ios_core",
  "ios_health_client",
  "ios_project_release",
  "ios_ui_interaction",
  "quality_process_gate",
  "test_suite_integrity"
]
```

Ensure `regression_contracts` contains the upstream chat contracts plus these existing registry IDs:

```json
[
  "UX-NAV-001",
  "UX-FORM-001",
  "TEST-SUITE-INTEGRITY-001",
  "PROCESS-GATE-001",
  "RELEASE-GATE-001"
]
```

Architecture ceilings remain enforced by the existing `architecture_limits` block and are not represented by a newly invented contract ID.

- [ ] **Step 3: 扩充同类扫描和验证文字**

Append explicit `same_class_scan` entries covering:

```text
扫描 // MARK: - 设置、资料与账号管理 到旧文件末尾的全部声明，确认菜单、账号、法律、反馈、关于和家庭管理整体迁移且未留下重复 owner。
扫描新文件对 XAgeMainView 私有符号的引用，只放宽 XAgeKeyboard、XAgeServerSyncSnapshot、XAgeDataPanelCategory、XAgePanelDestinationView、XAgeMetricDetailRow 和 XAgeMoreMenu 六个真实依赖。
解析 project.pbxproj 的 Sources/fileRef/group 关系，确认磁盘 Swift 集合与 target Sources 一致且只新增 XAgeMoreMenuViews.swift。
扫描 XAgeHighIntensityContextUITests 的 application lifecycle token，确认四个新增用例仅使用 XAgeUITestCase.launchApplication() 和共享网络审计。
比较源码发现、expected_xctests.json 和 xcresult 运行时 ID，确认 Unit 158、完整 UI 9、小屏 2、并集 167 精确一致。
```

Add both changed test source files to `tests_added_or_updated`. Update `verification_plan` to name the exact 158/9/2/167 counts, `regression_guard validate/check --working`, `run_regression_gate.py impacted`, unsigned generic-device Release archive, `verify_release_bundle.py`, hooks and Draft PR exact SHA. Preserve upstream chat quiescence and Markdown AX verification entries.

- [ ] **Step 4: 在回归制度中登记本轮首次失败不可被绿灯覆盖**

Append a dated current-state paragraph that cites:

```text
implementation_audit/ios_xage_more_menu_extraction_20260714/pre_refactor_regression_guard_failure.txt
```

State that the six pre-refactor failures remain blocking until the extraction, exact manifest update, fresh commit and complete mandatory gate all pass.

- [ ] **Step 5: 校验 JSON、影响域和静态门禁**

Run:

```bash
/usr/bin/python3 -m json.tool quality/change_impact.json >/dev/null
/usr/bin/python3 -I tools/regression_guard.py validate
/usr/bin/python3 -I tools/regression_guard.py check --working
git diff --check
```

Expected: all commands exit 0; changed domains have matching tests/contracts and no architecture baseline is raised.

### Task 6: 执行精确 iOS 测试与结果校验

**Files:**
- Create: `/tmp/xjie-xage-unit.xcresult` (untracked evidence bundle)
- Create: `/tmp/xjie-xage-ui-full.xcresult` (untracked evidence bundle)
- Create: `/tmp/xjie-xage-ui-small.xcresult` (untracked evidence bundle)

**Interfaces:**
- Consumes: `quality/expected_xctests.json` profiles
- Produces: validator-confirmed Unit 158、完整 UI 9、小屏 2 的 fresh `.xcresult`

- [ ] **Step 1: 运行完整 Unit 并校验 158 个精确 ID**

Run:

```bash
rm -rf /tmp/xjie-xage-unit.xcresult /tmp/xjie-xage-unit-derived
xcodebuild test -project Xjie/Xjie.xcodeproj -scheme Xjie -destination 'platform=iOS Simulator,name=iPhone 17 Pro' -derivedDataPath /tmp/xjie-xage-unit-derived -resultBundlePath /tmp/xjie-xage-unit.xcresult -only-testing:XjieTests
/usr/bin/python3 -I tools/validate_xcresult.py --path /tmp/xjie-xage-unit.xcresult --expected-profile ios_unit
```

Expected: test succeeds and validator reports exactly 158 passed, 0 failed, 0 skipped, no missing or extra IDs.

- [ ] **Step 2: 运行完整 UI 并校验 9 个精确 ID**

Run:

```bash
rm -rf /tmp/xjie-xage-ui-full.xcresult /tmp/xjie-xage-ui-full-derived
xcodebuild test -project Xjie/Xjie.xcodeproj -scheme Xjie -destination 'platform=iOS Simulator,name=iPhone 17 Pro' -derivedDataPath /tmp/xjie-xage-ui-full-derived -resultBundlePath /tmp/xjie-xage-ui-full.xcresult -only-testing:XjieUITests/XAgeHighIntensityContextUITests
/usr/bin/python3 -I tools/validate_xcresult.py --path /tmp/xjie-xage-ui-full.xcresult --expected-profile ios_ui_full
```

Expected: test succeeds and validator reports exactly 9 passed, 0 failed, 0 skipped, including all four new IDs; teardown network audit has `intercepted > 0` and `unhandled = 0` for every launch.

- [ ] **Step 3: 在 iPhone SE（第 3 代）运行两项小屏测试并校验设备**

Run:

```bash
rm -rf /tmp/xjie-xage-ui-small.xcresult /tmp/xjie-xage-ui-small-derived
xcodebuild test -project Xjie/Xjie.xcodeproj -scheme Xjie -destination 'platform=iOS Simulator,name=iPhone SE (3rd generation)' -derivedDataPath /tmp/xjie-xage-ui-small-derived -resultBundlePath /tmp/xjie-xage-ui-small.xcresult -only-testing:XjieUITests/XAgeHighIntensityContextUITests/testMetricManagerPageAndChatKeyboardLifecycle -only-testing:XjieUITests/XAgeHighIntensityContextUITests/testLoginKeyboardToolbarAndPasswordVisibilityFocus
/usr/bin/python3 -I tools/validate_xcresult.py --path /tmp/xjie-xage-ui-small.xcresult --expected-profile ios_ui_small
```

Expected: exactly 2 passed, 0 failed, 0 skipped; validator confirms iPhone SE (3rd generation).

- [ ] **Step 4: 运行工具精确清单**

Run:

```bash
/usr/bin/python3 -I -m unittest discover -s tools/tests -p 'test_*.py'
```

Expected: exact tools suite passes with the count required by merged `AGENTS.md`; no unexpected skip or failure.

### Task 7: 执行影响门禁和 device Release archive

**Files:**
- Create: gate-owned `/tmp` result bundles and DerivedData
- Create: gate-owned unsigned generic-device Release archive

**Interfaces:**
- Consumes: `quality/change_impact.json` and all committed gate scripts
- Produces: backend/iOS/quality/project/release evidence for the complete working candidate

- [ ] **Step 1: 重新运行三个 mandatory gate entry points**

Run:

```bash
/usr/bin/python3 -I tools/regression_guard.py validate
/usr/bin/python3 -I tools/regression_guard.py check --working
/usr/bin/python3 -I tools/run_regression_gate.py impacted
```

Expected: all exit 0. `impacted` executes every domain selected by `change_impact.json`, including exact Unit/full UI/small UI, backend adjacency, tools, diff checks and release archive verification.

- [ ] **Step 2: 独立确认 fresh unsigned device archive 和 bundle verifier 证据存在**

The merged gate creates this fixed fresh archive. Re-run its verifier against the produced device app:

```bash
/usr/bin/python3 -I tools/verify_release_bundle.py /tmp/xjie-quality-release.xcarchive/Products/Applications/Xjie.app
```

Expected: verifier confirms a generic iOS device arm64 Release app, production API settings, no Debug/UI automation markers, and exits 0.

- [ ] **Step 3: 确认最终差异范围和用户文件隔离**

Run:

```bash
git diff --check
git status --short
git diff --stat --cached
git diff --name-only --cached
```

Expected: no whitespace errors; the three user-owned untracked paths remain untracked and absent from the staged list; no file outside the design, upstream merge, quality policy and audit evidence appears unexpectedly.

### Task 8: 记录验证、提交 merge candidate、再验证 exact commit

**Files:**
- Create: `implementation_audit/ios_xage_more_menu_extraction_20260714/verification_report.md`
- Stage: all intended merge/refactor/test/policy/audit files

**Interfaces:**
- Consumes: Tasks 1–7 command outputs and result bundle paths
- Produces: one hook-validated merge commit with immutable SHA and audit report

- [ ] **Step 1: 写入验证报告**

Create the report with this exact section structure and fill each line from the commands already run:

```markdown
# XAGE upstream integration and more-menu extraction verification

Date: 2026-07-14 Asia/Shanghai
Branch: XAGE
Upstream parent evidence: `git rev-parse MERGE_HEAD` output captured before commit
Candidate first-parent evidence: `git rev-parse HEAD` output captured before commit

## Preserved failure

- Evidence: `pre_refactor_regression_guard_failure.txt`
- Root cause: stale exact XCTest manifest plus complete more-menu feature family remaining in XAgeMainView.swift.
- Permanent invariant: exact XCTest IDs and unchanged architecture ceilings.

## Static and architecture gates

- regression_guard validate: PASS
- regression_guard check --working: PASS
- XAgeMainView line/struct/sheet/full-screen/alert limits: PASS without baseline increase
- project Sources graph: PASS

## Runtime tests

- iOS Unit: 158 passed, 0 failed, 0 skipped — `/tmp/xjie-xage-unit.xcresult`
- Full UI: 9 passed, 0 failed, 0 skipped — `/tmp/xjie-xage-ui-full.xcresult`
- iPhone SE small UI: 2 passed, 0 failed, 0 skipped — `/tmp/xjie-xage-ui-small.xcresult`
- Tools exact suite: PASS
- Backend impacted suite: PASS

## Release-shape verification

- Fresh unsigned generic/platform=iOS Release archive: PASS
- verify_release_bundle.py: PASS
- No signing, export, upload or TestFlight release performed.

## Final gate

- run_regression_gate.py impacted: PASS
- git diff --check: PASS
```

Replace the two evidence descriptions with the literal 40-character outputs captured from those commands before applying the report patch. Keep the listed `/tmp` paths because Tasks 6 and 7 create those exact paths; do not claim PASS without the corresponding successful output.

- [ ] **Step 2: 重新 stage 精确文件并让 pre-commit hook 验证候选树**

Run:

```bash
git add AGENTS.md Xjie/Xjie.xcodeproj/project.pbxproj Xjie/Xjie/App/XjieApp.swift Xjie/Xjie/Models/MedicationModels.swift Xjie/Xjie/Utils/Utils.swift Xjie/Xjie/Views/Home/MainTabView.swift Xjie/Xjie/Views/Home/XAgeMainView+Preview.swift Xjie/Xjie/Views/Home/XAgeMainView.swift Xjie/Xjie/Views/Home/XAgeMoreMenuViews.swift Xjie/Xjie/Views/Home/XAgeStyleComponents.swift Xjie/Xjie/Views/Medications/XAgeMedicationManagementView.swift Xjie/XjieTests/UtilsTests.swift Xjie/XjieUITests/XAgeHighIntensityContextUITests.swift docs/quality/REGRESSION_POLICY.md docs/superpowers/plans/2026-07-13-xage-more-menu-account-privacy.md docs/superpowers/plans/2026-07-14-xage-feedback-rounded-input.md docs/superpowers/plans/2026-07-14-xage-medication-quick-add-feedback.md docs/superpowers/plans/2026-07-14-xage-more-menu-extraction.md docs/superpowers/plans/2026-07-14-xage-shared-style-preview.md docs/superpowers/specs/2026-07-13-xage-more-menu-account-privacy-design.md docs/superpowers/specs/2026-07-14-xage-feedback-rounded-input-design.md docs/superpowers/specs/2026-07-14-xage-medication-quick-add-feedback-design.md docs/superpowers/specs/2026-07-14-xage-more-menu-extraction-design.md docs/superpowers/specs/2026-07-14-xage-shared-style-preview-design.md implementation_audit/ios_xage_more_menu_extraction_20260714/pre_refactor_regression_guard_failure.txt implementation_audit/ios_xage_more_menu_extraction_20260714/verification_report.md quality/change_impact.json quality/expected_xctests.json tools/tests/test_validate_xcresult.py
git diff --cached --check
git status --short
git commit -m "merge: integrate upstream XAGE and extract more menu"
```

Expected: pre-commit hook creates an immutable staged candidate, passes `regression_guard validate` and `check`, then Git creates a two-parent merge commit. The three user-owned untracked paths remain outside the commit.

- [ ] **Step 3: 在 immutable exact commit 上重复静态和 impacted 门禁**

Run:

```bash
/usr/bin/python3 -I tools/regression_guard.py validate
/usr/bin/python3 -I tools/regression_guard.py check --base HEAD^1 --head HEAD
/usr/bin/python3 -I tools/run_regression_gate.py impacted
git show --stat --oneline --decorate HEAD
git rev-list --parents -n 1 HEAD
```

Expected: all gates pass on the new SHA; `rev-list` prints the commit plus two parent SHAs.

- [ ] **Step 4: 若 exact-commit 门禁失败，按永久阻断规则修复**

Do not amend or rerun as the sole response. Save the failing command and output under the same audit directory, identify the invariant that allowed it, add/strengthen the corresponding regression check, create a new commit through the normal hook, and rerun Task 8 Step 3 on the new SHA.

Expected: only a newly committed tree with complete green evidence proceeds to push.

### Task 9: Push 并创建 upstream Draft PR

**Files:**
- Create: `/tmp/xage-more-menu-pr-body.md` (temporary PR body, not committed)

**Interfaces:**
- Consumes: gate-validated exact merge SHA
- Produces: `origin/XAGE` update and Draft PR `LoveWood233:XAGE` → `doyoulikelin-wq/XJie_IOS:XAGE`

- [ ] **Step 1: Push 当前分支并允许 pre-push hook 完整执行**

Run:

```bash
git push -u origin XAGE
```

Expected: pre-push hook validates the immutable pushed SHA against the remote base and push succeeds; no hook bypass is used.

- [ ] **Step 2: 创建 Draft PR 描述文件**

Create `/tmp/xage-more-menu-pr-body.md` with:

```markdown
## Summary

- merge the latest `upstream/XAGE` chat quiescence and quality-gate changes
- preserve the XAGE account security, legal/permission pages, medication quick input, problem feedback and shared style preview work
- extract the complete more-menu feature family into `XAgeMoreMenuViews.swift` without raising architecture limits
- register the branch's 9 unit and 4 full-UI tests in the exact XCTest manifests

## Conflict resolution

- keep upstream `runUIAutomationNetworkProbeIfNeeded()` and the existing documented Debug flag helper
- keep upstream synchronous non-animated `ChatAutoScroll`, keyboard dismissal, starter-prompt and retry paths
- adapt new UI tests to the shared `XAgeUITestCase` application lifecycle and fail-closed network audit

## Verification

- `regression_guard.py validate`: pass
- `regression_guard.py check`: pass
- `run_regression_gate.py impacted`: pass
- iOS Unit: 158 exact tests
- full UI: 9 exact tests
- iPhone SE (3rd generation): 2 exact tests
- Unit + full UI manifest: 167 exact IDs
- fresh unsigned generic-device Release archive and `verify_release_bundle.py`: pass
- pre-commit and pre-push hooks: pass

## Release scope

No build increment, signing, IPA export, upload, or TestFlight release is included.
```

- [ ] **Step 3: 创建目标正确的 Draft PR**

Run:

```bash
gh pr create --draft --repo doyoulikelin-wq/XJie_IOS --base XAGE --head LoveWood233:XAGE --title "Merge XAGE features and extract more menu views" --body-file /tmp/xage-more-menu-pr-body.md
```

Expected: GitHub returns a PR URL; base is `doyoulikelin-wq:XAGE`, head is `LoveWood233:XAGE`, and PR is Draft.

- [ ] **Step 4: 回读 PR 元数据和远端 SHA**

Run:

```bash
gh pr view --repo doyoulikelin-wq/XJie_IOS --json url,isDraft,baseRefName,headRefName,headRepositoryOwner,mergeable,statusCheckRollup
git rev-parse HEAD
git rev-parse origin/XAGE
```

Expected: `isDraft=true`, both ref names are `XAGE`, head owner is `LoveWood233`, mergeability has no content conflict, and local HEAD equals `origin/XAGE`. Remote CI may still be pending and must not be described as green until GitHub reports it green.

---

## Completion Criteria

- `XAgeMainView.swift` is below every unchanged upstream architecture limit.
- `XAgeMoreMenuViews.swift` owns the complete more-menu feature family with no duplicate declarations.
- All current XAGE functionality and accessibility identifiers remain intact.
- Upstream chat quiescence, keyboard and retry paths are preserved.
- Exact manifests and runtime results agree at 158/9/2/167.
- Failure evidence, root cause, same-class scan and permanent invariants are auditable.
- Mandatory gates, unsigned device archive verification, pre-commit and pre-push hooks pass on the exact pushed SHA.
- `origin/XAGE` contains the merge commit and a conflict-free Draft PR targets `upstream/XAGE`.
