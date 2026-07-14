# XAGE Feedback Rounded Input Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将问题反馈多行输入框从胶囊背景改为默认 `18pt` 的共享连续圆角矩形，并让实际页面与 Canvas 预览同步使用该组件。

**Architecture:** 在现有 `XAgeStyleComponents.swift` 通用生产组件区域新增 `XAgeRoundedFieldBackground`，复用当前胶囊背景的填充、材质、描边和阴影参数，仅替换形状。`XAgeMainView` 的实际反馈编辑器与共享文件内的预览编辑器直接引用同一组件，不改动输入状态或提交逻辑。

**Tech Stack:** Swift 5、SwiftUI、XCTest、XCUITest、Xcode Canvas `#Preview`

## Global Constraints

- 直接在当前 `XAGE` 分支执行，不创建额外 worktree。
- `XAgeRoundedFieldBackground.cornerRadius` 默认值必须为 `18pt`，形状必须使用 `.continuous` 连续圆角。
- 保留当前 `XAgeCapsuleFill` 的填充透明度 `0.58`、`ultraThinMaterial`、描边透明度 `0.88`/线宽 `1pt`、`7ACAF5` 阴影透明度 `0.12`/半径 `14pt`/纵向偏移 `7pt`。
- 只替换实际问题反馈页和 Canvas 预览的两个多行 `TextEditor` 背景。
- 不调整单行输入、用药快捷气泡、按钮、输入框高度、内边距、字体、字数限制、提交接口或 accessibility identifier。
- 保留用户当前未提交的更多菜单、“剂量/次”、workspace 和历史文档差异。
- 不执行 push 或创建 PR。

---

### Task 1: 新增共享多行输入背景并同步生产页与预览

**Files:**
- Modify: `Xjie/Xjie/Views/Home/XAgeStyleComponents.swift:91-103,284-293`
- Modify: `Xjie/Xjie/Views/Home/XAgeMainView.swift:10870-10881`
- Test: `Xjie/XjieTests/UtilsTests.swift:9-39`
- Test: `Xjie/XjieUITests/XAgeHighIntensityContextUITests.swift:251-265`

**Interfaces:**
- Consumes: SwiftUI `RoundedRectangle`、现有 `Color(hex:)` 扩展和问题反馈页当前的 `TextEditor` 布局。
- Produces: `XAgeRoundedFieldBackground(cornerRadius: CGFloat = 18)`；生产页与预览均通过无参数初始化使用默认 `18pt` 圆角。

- [ ] **Step 1: 添加默认圆角与可配置圆角的失败测试**

在 `UtilsTests` 的 `// MARK: - XAGE shared styles` 区域加入：

```swift
@MainActor
func testXAgeRoundedFieldBackgroundUsesEighteenPointDefaultRadius() {
    let defaultBackground = XAgeRoundedFieldBackground()
    let customBackground = XAgeRoundedFieldBackground(cornerRadius: 24)

    XCTAssertEqual(defaultBackground.cornerRadius, 18)
    XCTAssertEqual(customBackground.cornerRadius, 24)
}
```

- [ ] **Step 2: 运行测试并确认因共享组件尚不存在而失败**

Run:

```bash
xcodebuild -quiet -project Xjie/Xjie.xcodeproj -scheme Xjie -destination 'platform=iOS Simulator,name=iPhone 17 Pro' -derivedDataPath /tmp/xjie-xage-feedback-radius-red -only-testing:XjieTests/UtilsTests/testXAgeRoundedFieldBackgroundUsesEighteenPointDefaultRadius test
```

Expected: FAIL，`UtilsTests.swift` 报告 `cannot find 'XAgeRoundedFieldBackground' in scope`；失败原因不得是测试拼写或工程配置错误。

- [ ] **Step 3: 在共享样式文件中实现最小生产组件**

紧接 `XAgeCapsuleFill` 后加入：

```swift
/// 高度较大的多行输入区域背景，使用可控连续圆角避免胶囊形状过度圆润。
struct XAgeRoundedFieldBackground: View {
    var cornerRadius: CGFloat = 18

    /// 保留通用胶囊的材质参数，仅将轮廓改为连续圆角矩形。
    var body: some View {
        let shape = RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)

        shape
            .fill(.white.opacity(0.58))
            .background(.ultraThinMaterial, in: shape)
            .overlay(shape.stroke(.white.opacity(0.88), lineWidth: 1))
            .shadow(color: Color(hex: "7ACAF5").opacity(0.12), radius: 14, x: 0, y: 7)
    }
}
```

- [ ] **Step 4: 运行契约测试并确认由红转绿**

Run:

```bash
xcodebuild -quiet -project Xjie/Xjie.xcodeproj -scheme Xjie -destination 'platform=iOS Simulator,name=iPhone 17 Pro' -derivedDataPath /tmp/xjie-xage-feedback-radius-green -only-testing:XjieTests/UtilsTests/testXAgeRoundedFieldBackgroundUsesEighteenPointDefaultRadius test
```

Expected: 测试通过、退出码 0；默认圆角为 `18`，传入 `24` 时保留调用方配置。

- [ ] **Step 5: 同步替换实际反馈页与 Canvas 预览背景**

在 `XAgeMainView.feedbackEditor` 中只替换背景调用：

```swift
TextEditor(text: $content)
    .frame(minHeight: 180)
    .padding(10)
    .scrollContentBackground(.hidden)
    .background(XAgeRoundedFieldBackground())
    .accessibilityIdentifier("xage.feedback.content")
```

在 `XAgeStyleComponentsPreview.feedbackEditorSection` 中做同样替换：

```swift
TextEditor(text: $feedbackText)
    .frame(minHeight: 180)
    .padding(10)
    .scrollContentBackground(.hidden)
    .background(XAgeRoundedFieldBackground())
```

- [ ] **Step 6: 验证 Debug 构建和 Canvas 编译**

Run:

```bash
xcodebuild -quiet -project Xjie/Xjie.xcodeproj -scheme Xjie -configuration Debug -destination 'platform=iOS Simulator,name=iPhone 17 Pro' -derivedDataPath /tmp/xjie-xage-feedback-radius-build build
```

Expected: BUILD SUCCEEDED，输出不含 `unable to type-check this expression in reasonable time`。

- [ ] **Step 7: 运行问题反馈 UI 回归测试**

Run:

```bash
xcodebuild -quiet -project Xjie/Xjie.xcodeproj -scheme Xjie -destination 'platform=iOS Simulator,name=iPhone 17 Pro' -derivedDataPath /tmp/xjie-xage-feedback-radius-ui -parallel-testing-enabled NO -only-testing:XjieUITests/XAgeHighIntensityContextUITests/testMoreMenuProblemFeedbackShowsInputAndContactEmail test
```

Expected: 测试通过、退出码 0；问题反馈页面、输入框、联系邮箱和提交按钮仍存在。

- [ ] **Step 8: 审计差异并只提交本任务 hunk**

Run:

```bash
git diff --check
git add Xjie/Xjie/Views/Home/XAgeStyleComponents.swift Xjie/XjieTests/UtilsTests.swift
git add -p Xjie/Xjie/Views/Home/XAgeMainView.swift
git diff --cached --check
git diff --cached --stat
git commit -m 'fix: reduce XAGE feedback input radius'
```

交互暂存 `XAgeMainView.swift` 时，只接受 `.background(XAgeCapsuleFill())` 改为 `.background(XAgeRoundedFieldBackground())` 的 hunk；拒绝更多菜单文案和注释等用户既有 hunk。

Expected: 提交只包含共享圆角组件、测试、实际反馈页和 Canvas 预览同步替换；`git status --short` 中仍保留用户既有的 `XAgeMainView.swift` 菜单差异、`XAgeMedicationManagementView.swift` 的“剂量/次”差异以及原有未跟踪文件；没有 push。

