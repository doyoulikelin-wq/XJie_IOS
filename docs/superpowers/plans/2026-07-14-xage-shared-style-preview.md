# XAGE Shared Style Preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 创建一个由生产页面与 Xcode Canvas 共用的 `XAgeStyleComponents.swift`，集中预览 XAGE 通用样式和用药专用样式，同时删除临时测试文件且不改变现有业务逻辑与视觉参数。

**Architecture:** 把 `XAgeMainView.swift` 和 `XAgeMedicationManagementView.swift` 底部的基础视觉原语移动到 Home 目录下的共享文件，并把单行输入框的焦点类型泛型化。共享文件尾部用纯本地状态构建 `#Preview` 样式陈列页；用药流式布局和所有业务状态仍留在原页面。工程文件只保留新文件所需的最小引用，清除临时文件及 Xcode 自动产生的无关排序差异。

**Tech Stack:** Swift 5、SwiftUI、Xcode Canvas `#Preview`、XCTest/XCUITest、Xcode project `project.pbxproj`

## Global Constraints

- 直接在当前 `XAGE` 分支执行，不创建额外 worktree。
- 删除用户确认仅供临时测试的 `Xjie/Xjie/Views/Home/XAgeCapsuleFill.swift`。
- 不重新设计生产视觉参数，不改变问题反馈、家庭和用药管理业务逻辑。
- 不新增第三方依赖，不让预览初始化 ViewModel、读取环境对象、运行 `.task` 或访问网络。
- 保留 `XAgeMedicationFlowLayout` 和 `XAgeMedicationTextField` 在用药页面中。
- 保留用户在 `XAgeMainView.swift` 中的菜单文案/注释改动以及 `XAgeMedicationManagementView.swift` 中“剂量/次”改动。
- `project.pbxproj` 最终只新增 `XAgeStyleComponents.swift` 所需的 file reference、Home group 条目和 APP target Sources 条目，不包含 PatientHistory 等无关重排。
- 只暂存和提交本任务自己的差异；现有未跟踪 workspace 文件与历史文档不纳入提交。

---

### Task 1: 记录基线并建立唯一的共享生产样式文件

**Files:**
- Create: `Xjie/Xjie/Views/Home/XAgeStyleComponents.swift`
- Delete: `Xjie/Xjie/Views/Home/XAgeCapsuleFill.swift`
- Modify: `Xjie/Xjie.xcodeproj/project.pbxproj`

**Interfaces:**
- Consumes: 现有 `Color(hex:)` 扩展、SwiftUI 的 `FocusState`、`UIKeyboardType`、`UITextContentType` 和 `TextInputAutocapitalization`。
- Produces: `XAgeLiquidBackground`、`XAgeGlassCardBackground`、`XAgeCapsuleFill`、`XAgeGradientActionLabel`、`XAgeGlassTextField<Field: Hashable>`、`XAgeMedicationLiquidBackground`、`XAgeMedicationGlassCard`、`XAgeMedicationCapsuleFill`、`XAgeMedicationPrimaryActionLabel`。

- [ ] **Step 1: 记录当前工作区和 Debug 构建基线**

Run:

```bash
git status --short
git diff -- Xjie/Xjie/Views/Home/XAgeMainView.swift Xjie/Xjie/Views/Medications/XAgeMedicationManagementView.swift
xcodebuild -quiet -project Xjie/Xjie.xcodeproj -scheme Xjie -configuration Debug -destination 'platform=iOS Simulator,name=iPhone 17 Pro' -derivedDataPath /tmp/xjie-xage-style-baseline build
```

Expected: 保存两份业务文件的既有差异；若构建因临时 `XAgeCapsuleFill.swift` 与主文件重复定义而失败，将 duplicate declaration 记为已知基线，后续删除临时文件后必须消失。

- [ ] **Step 2: 新建共享文件并写入保持参数不变的生产组件**

在 `XAgeStyleComponents.swift` 中写入以下公开到同一 target 的内部类型；组件不得声明为 `private`：

```swift
import SwiftUI

struct XAgeGlassTextField<Field: Hashable>: View {
    let placeholder: String
    @Binding var text: String
    var keyboardType: UIKeyboardType = .default
    let field: Field
    var focusedField: FocusState<Field?>.Binding
    var contentType: UITextContentType? = nil
    var capitalization: TextInputAutocapitalization = .sentences
    var submitLabel: SubmitLabel = .done
    var nextField: Field? = nil

    var body: some View {
        TextField(placeholder, text: $text)
            .font(.system(size: 14, weight: .semibold))
            .keyboardType(keyboardType)
            .textContentType(contentType)
            .textInputAutocapitalization(capitalization)
            .disableAutocorrection(true)
            .focused(focusedField, equals: field)
            .submitLabel(submitLabel)
            .onSubmit { focusedField.wrappedValue = nextField }
            .padding(.horizontal, 12)
            .frame(height: 44)
            .background(XAgeCapsuleFill())
    }
}

struct XAgeGradientActionLabel: View {
    let title: String
    let icon: String

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: icon).font(.system(size: 13, weight: .bold))
            Text(title).font(.system(size: 14, weight: .bold))
        }
        .foregroundStyle(.white)
        .frame(maxWidth: .infinity)
        .frame(height: 44)
        .background(Capsule().fill(LinearGradient(
            colors: [Color(hex: "238AD6"), Color(hex: "20CDB1")],
            startPoint: .topLeading,
            endPoint: .bottomTrailing
        )))
    }
}
```

同一文件继续写入以下实现，保持颜色、透明度、圆角、模糊、偏移、描边和阴影数值不变：

```swift
struct XAgeGlassCardBackground: View {
    var cornerRadius: CGFloat

    var body: some View {
        RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
            .fill(.white.opacity(0.56))
            .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: cornerRadius, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                    .stroke(.white.opacity(0.84), lineWidth: 1)
            )
            .shadow(color: Color(hex: "73C8F0").opacity(0.18), radius: 28, x: 0, y: 14)
    }
}

struct XAgeCapsuleFill: View {
    var body: some View {
        Capsule()
            .fill(.white.opacity(0.58))
            .background(.ultraThinMaterial, in: Capsule())
            .overlay(Capsule().stroke(.white.opacity(0.88), lineWidth: 1))
            .shadow(color: Color(hex: "7ACAF5").opacity(0.12), radius: 14, x: 0, y: 7)
    }
}

struct XAgeLiquidBackground: View {
    var body: some View {
        ZStack {
            LinearGradient(
                colors: [Color(hex: "E8F7FF"), Color(hex: "D5ECFF"), Color(hex: "F7FCFF")],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )
            Circle()
                .fill(Color(hex: "61E7E1").opacity(0.28))
                .frame(width: 235, height: 235)
                .blur(radius: 26)
                .offset(x: -150, y: -260)
            Circle()
                .fill(Color(hex: "8CC8FF").opacity(0.32))
                .frame(width: 260, height: 300)
                .blur(radius: 30)
                .offset(x: 160, y: -320)
            Circle()
                .fill(Color(hex: "C9C2FF").opacity(0.22))
                .frame(width: 230, height: 260)
                .blur(radius: 34)
                .offset(x: 135, y: 150)
            Rectangle()
                .fill(.white.opacity(0.2))
                .frame(width: 88)
                .blur(radius: 22)
                .rotationEffect(.degrees(5))
                .offset(x: -6)
        }
    }
}

struct XAgeMedicationPrimaryActionLabel: View {
    let title: String
    let icon: String

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: icon).font(.system(size: 15, weight: .bold))
            Text(title).font(.system(size: 17, weight: .bold))
        }
        .foregroundStyle(.white)
        .frame(maxWidth: .infinity)
        .frame(height: 56)
        .background(LinearGradient(
            colors: [Color(hex: "22D4BF"), Color(hex: "1F8EEA")],
            startPoint: .leading,
            endPoint: .trailing
        ))
        .clipShape(Capsule())
        .shadow(color: Color(hex: "20CDB1").opacity(0.24), radius: 16, x: 0, y: 10)
    }
}

struct XAgeMedicationGlassCard: View {
    var cornerRadius: CGFloat

    var body: some View {
        RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
            .fill(.white.opacity(0.58))
            .overlay(
                RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                    .stroke(.white.opacity(0.76), lineWidth: 1)
            )
            .shadow(color: Color(hex: "78BCE8").opacity(0.12), radius: 22, x: 0, y: 10)
    }
}

struct XAgeMedicationCapsuleFill: View {
    var body: some View {
        Capsule()
            .fill(.white.opacity(0.62))
            .overlay(Capsule().stroke(.white.opacity(0.72), lineWidth: 1))
            .shadow(color: Color(hex: "78BCE8").opacity(0.10), radius: 10, x: 0, y: 5)
    }
}

struct XAgeMedicationLiquidBackground: View {
    var body: some View {
        LinearGradient(
            colors: [Color(hex: "D9F5FF"), Color(hex: "EAF9FF"), Color(hex: "F8FCFF")],
            startPoint: .topLeading,
            endPoint: .bottomTrailing
        )
    }
}
```

- [ ] **Step 3: 删除临时文件并把工程引用收敛为最小差异**

使用补丁删除 `XAgeCapsuleFill.swift`，并在 `project.pbxproj` 中将当前临时文件的三处引用替换为新文件：

```text
XAgeStyleComponents.swift in Sources = PBXBuildFile(fileRef: XAgeStyleComponents.swift)
XAgeStyleComponents.swift = PBXFileReference(path: XAgeStyleComponents.swift)
Home group children += XAgeStyleComponents.swift
Xjie Sources files += XAgeStyleComponents.swift in Sources
```

先对照 `git show HEAD:Xjie/Xjie.xcodeproj/project.pbxproj`，撤除当前工作树中与临时文件无关的排序变化；不得删除 HEAD 已存在的任何文件引用。完成后运行：

```bash
rg -n 'XAgeCapsuleFill.swift|XAgeStyleComponents.swift' Xjie/Xjie.xcodeproj/project.pbxproj
git diff -- Xjie/Xjie.xcodeproj/project.pbxproj
```

Expected: 搜索只出现 `XAgeStyleComponents.swift` 的 BuildFile、FileReference、Home group、Sources 共四处；工程 diff 不包含 PatientHistory 或其他文件重排。

- [ ] **Step 4: 运行编译，确认“重复定义”形成预期的迁移红灯**

Run:

```bash
xcodebuild -quiet -project Xjie/Xjie.xcodeproj -scheme Xjie -configuration Debug -destination 'platform=iOS Simulator,name=iPhone 17 Pro' -derivedDataPath /tmp/xjie-xage-style-shared-red build
```

Expected: FAIL，错误只指向共享文件与两个原页面仍并存的重复类型定义；不得出现工程缺失文件或新依赖错误。

---

### Task 2: 让生产页面改用共享组件

**Files:**
- Modify: `Xjie/Xjie/Views/Home/XAgeMainView.swift:11169-11255,11374-11519`
- Modify: `Xjie/Xjie/Views/Medications/XAgeMedicationManagementView.swift:957-1081`
- Test: `Xjie/XjieTests/UtilsTests.swift`

**Interfaces:**
- Consumes: Task 1 产生的全部共享样式类型与泛型 `XAgeGlassTextField<Field>`。
- Produces: 无重复私有样式定义、现有家庭输入焦点顺序不变、用药快捷气泡继续使用相同的 `XAgeMedicationCapsuleFill`。

- [ ] **Step 1: 删除两个页面中的重复样式定义**

从 `XAgeMainView.swift` 删除以下完整类型，不改动相邻的 `XAgeSectionHeader` 和 `CapsuleButton`：

```text
private struct XAgeGlassTextField
private struct XAgeGradientActionLabel
private struct XAgeGlassCardBackground
private struct XAgeCapsuleFill
private struct XAgeLiquidBackground
```

从 `XAgeMedicationManagementView.swift` 删除以下完整类型，不删除 `XAgeMedicationTextField`、`XAgeMedicationFlowLayout`、`XAgeMedicationLoadingCard` 或 `String` 扩展：

```text
private struct XAgeMedicationPrimaryActionLabel
private struct XAgeMedicationGlassCard
private struct XAgeMedicationCapsuleFill
private struct XAgeMedicationLiquidBackground
```

- [ ] **Step 2: 为四个家庭输入调用点显式传入提交行为**

保留 `XAgeFamilyField` 在 `XAgeMainView.swift`，并按现有 `CaseIterable` 顺序补齐参数：

```swift
// phone
submitLabel: .next,
nextField: .relation

// relation
submitLabel: .next,
nextField: .inviteCode

// inviteCode
submitLabel: .next,
nextField: .displayName

// displayName
submitLabel: .done,
nextField: nil
```

Expected: `XAgeGlassTextField` 的泛型参数由 `$focusedField` 和 `.phone/.relation/.inviteCode/.displayName` 自动推导为 `XAgeFamilyField`；键盘、content type、大小写和 accessibility identifier 保持原值。

- [ ] **Step 3: 构建并运行用药输入单元测试**

Run:

```bash
xcodebuild -quiet -project Xjie/Xjie.xcodeproj -scheme Xjie -destination 'platform=iOS Simulator,name=iPhone 17 Pro' -derivedDataPath /tmp/xjie-xage-style-unit -only-testing:XjieTests/UtilsTests/testMedicationQuickInputReplacesDoseAndFrequency -only-testing:XjieTests/UtilsTests/testMedicationQuickInstructionUsesPhraseForEmptyOrWhitespaceContent -only-testing:XjieTests/UtilsTests/testMedicationQuickInstructionAppendsWithChineseComma -only-testing:XjieTests/UtilsTests/testMedicationQuickInputExposesApprovedOptions test
```

Expected: BUILD SUCCEEDED；4 个测试通过、0 失败，且没有 duplicate declaration 或 compiler unable to type-check 错误。

- [ ] **Step 4: 只暂存本任务迁移 hunk 并提交**

交互式暂存时拒绝 `XAgeMainView.swift` 中菜单文案/注释的既有 hunk，拒绝用药页面“剂量/次”的既有 hunk：

```bash
git add Xjie/Xjie/Views/Home/XAgeStyleComponents.swift Xjie/Xjie/Views/Home/XAgeCapsuleFill.swift Xjie/Xjie.xcodeproj/project.pbxproj
git add -p Xjie/Xjie/Views/Home/XAgeMainView.swift Xjie/Xjie/Views/Medications/XAgeMedicationManagementView.swift
git diff --cached --check
git diff --cached --stat
git commit -m 'refactor: share XAGE style components'
```

Expected: 提交包含共享组件、临时文件删除、最小工程引用和两个页面的样式迁移；用户既有业务 hunk 仍留在工作树。

---

### Task 3: 在共享文件中加入无依赖 Canvas 样式陈列页

**Files:**
- Modify: `Xjie/Xjie/Views/Home/XAgeStyleComponents.swift`

**Interfaces:**
- Consumes: Task 1 的九个生产样式类型，以及 `MedicationQuickInput.dosageOptions`、`frequencyOptions`、`instructionOptions` 只读常量。
- Produces: `XAgeStyleComponentsPreview`、预览本地焦点枚举、文件末尾的 `#Preview("XAGE 样式组件")`。

- [ ] **Step 1: 添加只持有本地状态的预览根视图**

在共享文件的生产组件之后加入：

```swift
private enum XAgeStylePreviewField: Hashable {
    case singleLine
}

private struct XAgeStyleComponentsPreview: View {
    @State private var singleLineText = "示例输入"
    @State private var feedbackText = "请描述你遇到的问题或改进建议"
    @FocusState private var focusedField: XAgeStylePreviewField?

    var body: some View {
        ZStack {
            XAgeLiquidBackground().ignoresSafeArea()
            ScrollView {
                VStack(alignment: .leading, spacing: 22) {
                    previewTitle("玻璃卡片")
                    HStack(spacing: 12) {
                        previewCard("圆角 20", radius: 20)
                        previewCard("圆角 28", radius: 28)
                    }

                    previewTitle("胶囊与阴影")
                    HStack(spacing: 12) {
                        capsuleSample("生产阴影", blackShadow: false)
                        capsuleSample("黑色阴影实验", blackShadow: true)
                    }

                    previewTitle("主操作按钮")
                    XAgeGradientActionLabel(title: "提交反馈", icon: "paperplane.fill")

                    previewTitle("单行输入")
                    XAgeGlassTextField(
                        placeholder: "请输入内容",
                        text: $singleLineText,
                        field: .singleLine,
                        focusedField: $focusedField
                    )

                    previewTitle("问题反馈多行输入")
                    TextEditor(text: $feedbackText)
                        .font(.system(size: 15))
                        .scrollContentBackground(.hidden)
                        .padding(12)
                        .frame(minHeight: 132)
                        .background(XAgeCapsuleFill())

                    quickOptionSection("剂量", options: MedicationQuickInput.dosageOptions)
                    quickOptionSection("频次", options: MedicationQuickInput.frequencyOptions)
                    quickOptionSection("使用说明", options: MedicationQuickInput.instructionOptions)

                    previewTitle("通用 / 用药样式对照")
                    HStack(spacing: 12) {
                        styleComparison("通用", background: AnyView(XAgeGlassCardBackground(cornerRadius: 22)))
                        styleComparison("用药", background: AnyView(XAgeMedicationGlassCard(cornerRadius: 22)))
                    }
                    XAgeMedicationPrimaryActionLabel(title: "保存用药", icon: "checkmark")
                }
                .padding(20)
            }
        }
    }
}
```

为避免 SwiftUI 类型检查器处理一个过大的表达式，加入以下独立方法，不把所有 section 内联回 `body`：

```swift
private func previewTitle(_ title: String) -> some View {
    Text(title)
        .font(.system(size: 17, weight: .bold))
        .foregroundStyle(Color(hex: "173F64"))
}

private func previewCard(_ title: String, radius: CGFloat) -> some View {
    Text(title)
        .font(.system(size: 13, weight: .semibold))
        .foregroundStyle(Color(hex: "365F80"))
        .frame(maxWidth: .infinity)
        .frame(height: 84)
        .background(XAgeGlassCardBackground(cornerRadius: radius))
}

private func capsuleSample(_ title: String, blackShadow: Bool) -> some View {
    Text(title)
        .font(.system(size: 12, weight: .bold))
        .foregroundStyle(Color(hex: "365F80"))
        .frame(maxWidth: .infinity)
        .frame(height: 42)
        .background {
            XAgeCapsuleFill()
                .shadow(
                    color: blackShadow ? .black.opacity(0.12) : .clear,
                    radius: 14,
                    x: 0,
                    y: 7
                )
        }
}

private func quickOptionSection(_ title: String, options: [String]) -> some View {
    VStack(alignment: .leading, spacing: 8) {
        previewTitle(title + "快捷气泡")
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 88), spacing: 8)], spacing: 8) {
            ForEach(options, id: \.self) { option in
                Button(option) {}
                    .buttonStyle(.plain)
                    .font(.system(size: 12, weight: .bold))
                    .foregroundStyle(Color(hex: "1268BD"))
                    .frame(maxWidth: .infinity)
                    .frame(height: 36)
                    .background(XAgeMedicationCapsuleFill())
            }
        }
    }
}

private func styleComparison(_ title: String, background: AnyView) -> some View {
    Text(title)
        .font(.system(size: 13, weight: .bold))
        .foregroundStyle(Color(hex: "365F80"))
        .frame(maxWidth: .infinity)
        .frame(height: 86)
        .background(background)
}
```

把对照区域中的用药背景改为以下组合，使 `XAgeMedicationLiquidBackground`、卡片与主按钮都能在预览中出现，同时不移动或复制生产页面的 `XAgeMedicationFlowLayout`：

```swift
styleComparison(
    "用药",
    background: AnyView(
        ZStack {
            XAgeMedicationLiquidBackground()
            XAgeMedicationGlassCard(cornerRadius: 22).padding(6)
        }
    )
)
```

- [ ] **Step 2: 添加文件级 Preview 声明**

```swift
#Preview("XAGE 样式组件") {
    XAgeStyleComponentsPreview()
}
```

Expected: Preview 根视图只依赖本地 `@State/@FocusState`，没有 ViewModel、environment object、`.task`、API 或登录状态。

- [ ] **Step 3: 以 Debug 构建验证 Preview 编译表达式**

Run:

```bash
xcodebuild -quiet -project Xjie/Xjie.xcodeproj -scheme Xjie -configuration Debug -destination 'platform=iOS Simulator,name=iPhone 17 Pro' -derivedDataPath /tmp/xjie-xage-style-preview build
```

Expected: BUILD SUCCEEDED；输出不含 `unable to type-check this expression in reasonable time`。

- [ ] **Step 4: 提交预览陈列页**

```bash
git add Xjie/Xjie/Views/Home/XAgeStyleComponents.swift
git diff --cached --check
git commit -m 'feat: add XAGE style Canvas gallery'
```

Expected: 仅共享样式文件的预览部分进入该提交。

---

### Task 4: 回归验证和差异审计

**Files:**
- Verify: `Xjie/Xjie/Views/Home/XAgeStyleComponents.swift`
- Verify: `Xjie/Xjie/Views/Home/XAgeMainView.swift`
- Verify: `Xjie/Xjie/Views/Medications/XAgeMedicationManagementView.swift`
- Verify: `Xjie/Xjie.xcodeproj/project.pbxproj`
- Test: `Xjie/XjieUITests/XAgeHighIntensityContextUITests.swift`

**Interfaces:**
- Consumes: Tasks 1–3 的完整样式迁移和 Preview。
- Produces: 可交付的构建/回归证据以及明确保留的用户未提交差异清单。

- [ ] **Step 1: 运行用药快捷添加和问题反馈 UI 回归**

Run:

```bash
xcodebuild -quiet -project Xjie/Xjie.xcodeproj -scheme Xjie -destination 'platform=iOS Simulator,name=iPhone 17 Pro' -derivedDataPath /tmp/xjie-xage-style-ui -parallel-testing-enabled NO -only-testing:XjieUITests/XAgeHighIntensityContextUITests/testMedicationEditorQuickInputsReplaceAndAppend -only-testing:XjieUITests/XAgeHighIntensityContextUITests/testMoreMenuProblemFeedbackShowsInputAndContactEmail test
```

Expected: 两项 UI 测试通过、0 失败；添加/编辑页快捷输入和“更多 → 关于 → 问题反馈”入口仍可用。

- [ ] **Step 2: 运行最终 Debug 构建和静态检查**

Run:

```bash
xcodebuild -quiet -project Xjie/Xjie.xcodeproj -scheme Xjie -configuration Debug -destination 'platform=iOS Simulator,name=iPhone 17 Pro' -derivedDataPath /tmp/xjie-xage-style-final build
git diff --check
rg -n '^private struct XAge(GlassTextField|GradientActionLabel|GlassCardBackground|CapsuleFill|LiquidBackground|MedicationPrimaryActionLabel|MedicationGlassCard|MedicationCapsuleFill|MedicationLiquidBackground)' Xjie/Xjie/Views
test ! -e Xjie/Xjie/Views/Home/XAgeCapsuleFill.swift
```

Expected: BUILD SUCCEEDED；`git diff --check` 无输出；旧私有样式搜索无结果；临时文件不存在。

- [ ] **Step 3: 审计提交与保留的工作树差异**

Run:

```bash
git log --oneline -4
git show --stat --oneline HEAD~1..HEAD
git diff -- Xjie/Xjie.xcodeproj/project.pbxproj
git status --short
```

Expected: 本任务两个代码提交清晰可审；工程文件无未提交残余；用户原有的菜单文案/注释、“剂量/次”、workspace 和历史文档差异仍按原状态保留；没有执行 push。
