# XAGE Medication Quick Add and Feedback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add medication quick-entry chips to the XAGE medication editor and a server-backed problem feedback sheet under More → About.

**Architecture:** Keep medication form state local to `XAgeMedicationEditSheet`, but move replacement/append semantics and preset values into an internal pure helper in the existing medication model file so they can be unit tested. Add an XAGE-specific feedback sheet that owns only input/submission UI state, while a dedicated `SettingsViewModel` instance continues to own `/api/feedback` submission and error state.

**Tech Stack:** Swift 5, SwiftUI, Combine `ObservableObject`, XCTest, XCUITest, async/await, existing `APIServiceProtocol` and `SettingsViewModel`.

## Global Constraints

- Work directly on the current `XAGE` branch; do not create a worktree.
- Preserve unrelated unstaged and untracked user files and changes.
- It is permitted to normalize `struct XAgeMedicationManagementView : View` back to `struct XAgeMedicationManagementView: View`.
- Do not change medication API contracts or the legacy `SettingsView` feedback UI.
- Feedback must use `/api/feedback` through `SettingsViewModel.submitFeedback(category:content:contact:)` with category `general` and contact `nil`.
- Contact email is exactly `jianjieaitech@163.com`.
- Feedback length after trimming is 2 through 2000 characters.
- Quick options are exactly those listed in the approved design spec.
- Use Chinese comma `，` when appending a quick instruction to nonblank content.
- Follow RED → GREEN → REFACTOR for every production behavior.

---

## File Structure

- Modify `Xjie/Xjie/Models/MedicationModels.swift`: internal quick-entry presets and pure application rules.
- Modify `Xjie/XjieTests/UtilsTests.swift`: focused unit coverage for replacement and instruction append behavior; reuse this already-targeted test file to avoid unrelated Xcode project-file edits.
- Modify `Xjie/Xjie/Views/Medications/XAgeMedicationManagementView.swift`: quick-entry chip UI and bindings to medication form state.
- Modify `Xjie/Xjie/Views/Home/XAgeMainView.swift`: More-menu entry, feedback presentation state, XAGE feedback sheet, success/error presentation.
- Modify `Xjie/XjieUITests/XAgeHighIntensityContextUITests.swift`: navigation and interaction coverage for quick chips and feedback UI.

### Task 1: Medication Quick-Entry Rules

**Files:**
- Modify: `Xjie/XjieTests/UtilsTests.swift`
- Modify: `Xjie/Xjie/Models/MedicationModels.swift`

**Interfaces:**
- Produces: `MedicationQuickInput.Behavior` with `.replace` and `.appendInstruction`.
- Produces: `MedicationQuickInput.applying(_:to:behavior:) -> String`.
- Produces: `MedicationQuickInput.dosageOptions`, `frequencyOptions`, and `instructionOptions`.

- [ ] **Step 1: Write failing unit tests for replacement and append behavior**

Append this section to `UtilsTests`:

```swift
// MARK: - MedicationQuickInput

func testMedicationQuickInputReplacesDoseAndFrequency() {
    XCTAssertEqual(
        MedicationQuickInput.applying("每日3次", to: "每日1次", behavior: .replace),
        "每日3次"
    )
}

func testMedicationQuickInstructionUsesPhraseForEmptyOrWhitespaceContent() {
    XCTAssertEqual(
        MedicationQuickInput.applying("饭后服用", to: "", behavior: .appendInstruction),
        "饭后服用"
    )
    XCTAssertEqual(
        MedicationQuickInput.applying("随餐服用", to: "   ", behavior: .appendInstruction),
        "随餐服用"
    )
}

func testMedicationQuickInstructionAppendsWithChineseComma() {
    XCTAssertEqual(
        MedicationQuickInput.applying("睡前服用", to: "整片吞服", behavior: .appendInstruction),
        "整片吞服，睡前服用"
    )
}

func testMedicationQuickInputExposesApprovedOptions() {
    XCTAssertEqual(MedicationQuickInput.dosageOptions, ["半片", "1片", "2片", "5mg", "10mg"])
    XCTAssertEqual(MedicationQuickInput.frequencyOptions, ["每日1次", "每日2次", "每日3次", "睡前1次", "按需服用"])
    XCTAssertEqual(MedicationQuickInput.instructionOptions, ["饭后服用", "随餐服用", "空腹服用", "睡前服用", "整片吞服"])
}
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
xcodebuild test \
  -project Xjie/Xjie.xcodeproj \
  -scheme Xjie \
  -destination 'platform=iOS Simulator,name=iPhone 17 Pro' \
  -only-testing:XjieTests/UtilsTests
```

Expected: compilation fails because `MedicationQuickInput` does not exist. Confirm the failure points to the new tests, not an unrelated source error.

- [ ] **Step 3: Implement the minimal pure helper**

Append to `MedicationModels.swift`:

```swift
enum MedicationQuickInput {
    enum Behavior {
        case replace
        case appendInstruction
    }

    static let dosageOptions = ["半片", "1片", "2片", "5mg", "10mg"]
    static let frequencyOptions = ["每日1次", "每日2次", "每日3次", "睡前1次", "按需服用"]
    static let instructionOptions = ["饭后服用", "随餐服用", "空腹服用", "睡前服用", "整片吞服"]

    static func applying(_ option: String, to current: String, behavior: Behavior) -> String {
        switch behavior {
        case .replace:
            return option
        case .appendInstruction:
            guard !current.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
                return option
            }
            return "\(current)，\(option)"
        }
    }
}
```

- [ ] **Step 4: Run the unit tests and verify GREEN**

Run the command from Step 2.

Expected: `UtilsTests` pass with zero failures.

- [ ] **Step 5: Commit the behavior and tests**

```bash
git add Xjie/Xjie/Models/MedicationModels.swift Xjie/XjieTests/UtilsTests.swift
git commit -m "feat: add medication quick input rules"
```

### Task 2: Medication Quick-Entry Chips

**Files:**
- Modify: `Xjie/XjieUITests/XAgeHighIntensityContextUITests.swift`
- Modify: `Xjie/Xjie/Views/Medications/XAgeMedicationManagementView.swift`

**Interfaces:**
- Consumes: `MedicationQuickInput` from Task 1.
- Produces: private `XAgeMedicationQuickOptions` SwiftUI component.
- Produces identifiers `xage.medication.quick.dosage.<option>`, `xage.medication.quick.frequency.<option>`, and `xage.medication.quick.instructions.<option>`.

- [ ] **Step 1: Write a failing UI test for quick chips**

Add a new test to `XAgeHighIntensityContextUITests`:

```swift
func testMedicationEditorQuickInputsReplaceAndAppend() throws {
    app.launch()
    enterDebugValidationSession()

    tapAndWait(app.buttons["xage.more"], for: app.buttons["xage.account.用药管理"])
    tapAndWait(app.buttons["xage.account.用药管理"], for: app.scrollViews["xage.medication.root"])
    tapAndWait(app.buttons["xage.medication.add"], for: app.buttons["xage.medication.quick.dosage.1片"])

    let dosage = app.descendants(matching: .any)["xage.medication.edit.dosage"]
    app.buttons["xage.medication.quick.dosage.1片"].tap()
    XCTAssertEqual(dosage.value as? String, "1片")

    let frequency = app.descendants(matching: .any)["xage.medication.edit.frequency"]
    app.buttons["xage.medication.quick.frequency.每日3次"].tap()
    XCTAssertEqual(frequency.value as? String, "每日3次")

    let instructions = app.descendants(matching: .any)["xage.medication.edit.instructions"]
    app.buttons["xage.medication.quick.instructions.饭后服用"].tap()
    app.buttons["xage.medication.quick.instructions.整片吞服"].tap()
    XCTAssertEqual(instructions.value as? String, "饭后服用，整片吞服")
}
```

- [ ] **Step 2: Run the new UI test and verify RED**

```bash
xcodebuild test \
  -project Xjie/Xjie.xcodeproj \
  -scheme Xjie \
  -destination 'platform=iOS Simulator,name=iPhone 17 Pro' \
  -only-testing:XjieUITests/XAgeHighIntensityContextUITests/testMedicationEditorQuickInputsReplaceAndAppend
```

Expected: test fails because `xage.medication.quick.dosage.1片` does not exist.

- [ ] **Step 3: Add the reusable quick-chip component**

Add near the existing medication text-field components:

```swift
private struct XAgeMedicationQuickOptions: View {
    let fieldID: String
    let options: [String]
    let onSelect: (String) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            Text("快捷添加")
                .font(.system(size: 12, weight: .bold))
                .foregroundStyle(Color(hex: "6C8194"))

            XAgeMedicationFlowLayout(spacing: 8) {
                ForEach(options, id: \.self) { option in
                    Button(option) { onSelect(option) }
                        .font(.system(size: 12, weight: .bold))
                        .foregroundStyle(Color(hex: "1268BD"))
                        .padding(.horizontal, 11)
                        .frame(minHeight: 44)
                        .background {
                            XAgeMedicationCapsuleFill().frame(height: 32)
                        }
                        .contentShape(Rectangle())
                        .buttonStyle(.plain)
                        .accessibilityIdentifier("xage.medication.quick.\(fieldID).\(option)")
                }
            }
        }
    }
}
```

- [ ] **Step 4: Wire chips beneath dose, frequency, and instructions**

In `medicationFields`, insert each option group immediately after its corresponding `XAgeMedicationTextField`:

```swift
XAgeMedicationQuickOptions(fieldID: "dosage", options: MedicationQuickInput.dosageOptions) { option in
    dosage = MedicationQuickInput.applying(option, to: dosage, behavior: .replace)
}

XAgeMedicationQuickOptions(fieldID: "frequency", options: MedicationQuickInput.frequencyOptions) { option in
    frequency = MedicationQuickInput.applying(option, to: frequency, behavior: .replace)
}

XAgeMedicationQuickOptions(fieldID: "instructions", options: MedicationQuickInput.instructionOptions) { option in
    instructions = MedicationQuickInput.applying(option, to: instructions, behavior: .appendInstruction)
}
```

Also normalize the allowed formatting change:

```swift
struct XAgeMedicationManagementView: View {
```

- [ ] **Step 5: Run the unit and UI tests and verify GREEN**

Run the Task 1 unit-test command, then the Task 2 UI-test command.

Expected: both commands succeed with zero failures. If the multiline SwiftUI `TextField` appears under a different XCUI element type, keep the accessibility identifier and query through `descendants(matching: .any)` rather than changing production semantics.

- [ ] **Step 6: Commit the quick-entry UI**

```bash
git add Xjie/Xjie/Views/Medications/XAgeMedicationManagementView.swift Xjie/XjieUITests/XAgeHighIntensityContextUITests.swift
git commit -m "feat: add XAGE medication quick entry chips"
```

### Task 3: XAGE Problem Feedback Sheet

**Files:**
- Modify: `Xjie/XjieUITests/XAgeHighIntensityContextUITests.swift`
- Modify: `Xjie/Xjie/Views/Home/XAgeMainView.swift`

**Interfaces:**
- Consumes: `SettingsViewModel.submitFeedback(category:content:contact:) async -> Bool`.
- Produces: private `XAgeProblemFeedbackSheet`.
- Produces identifiers `xage.account.问题反馈`, `xage.feedback.page`, `xage.feedback.content`, `xage.feedback.email`, and `xage.feedback.submit`.

- [ ] **Step 1: Write a failing UI test for feedback navigation and content**

Add to `XAgeHighIntensityContextUITests`:

```swift
func testMoreMenuProblemFeedbackShowsInputAndContactEmail() throws {
    app.launch()
    enterDebugValidationSession()

    tapAndWait(app.buttons["xage.more"], for: app.buttons["xage.account.问题反馈"])
    tapAndWait(app.buttons["xage.account.问题反馈"], for: app.descendants(matching: .any)["xage.feedback.page"])

    XCTAssertTrue(app.descendants(matching: .any)["xage.feedback.content"].exists)
    XCTAssertTrue(app.staticTexts["jianjieaitech@163.com"].exists)
    XCTAssertTrue(app.buttons["xage.feedback.submit"].exists)
}
```

- [ ] **Step 2: Run the feedback UI test and verify RED**

```bash
xcodebuild test \
  -project Xjie/Xjie.xcodeproj \
  -scheme Xjie \
  -destination 'platform=iOS Simulator,name=iPhone 17 Pro' \
  -only-testing:XjieUITests/XAgeHighIntensityContextUITests/testMoreMenuProblemFeedbackShowsInputAndContactEmail
```

Expected: test fails because `xage.account.问题反馈` does not exist.

- [ ] **Step 3: Add More-menu state and entry**

Add to `XAgeMoreMenu`:

```swift
@StateObject private var feedbackVM = SettingsViewModel()
@State private var showProblemFeedback = false
@State private var showFeedbackSuccess = false
```

Add under the “关于” heading before “关于小捷”:

```swift
XAgeAccountMenuRow(
    icon: "bubble.left.and.text.bubble.right.fill",
    title: "问题反馈",
    subtitle: "提交 APP 问题或改进建议"
) {
    showProblemFeedback = true
}
```

- [ ] **Step 4: Present the feedback sheet and success alert**

Add to the More-menu presentation modifiers:

```swift
.sheet(isPresented: $showProblemFeedback) {
    XAgeProblemFeedbackSheet(viewModel: feedbackVM) {
        showFeedbackSuccess = true
    }
    .presentationDetents([.large])
    .presentationDragIndicator(.visible)
}
.alert("反馈已提交", isPresented: $showFeedbackSuccess) {
    Button("好", role: .cancel) {}
} message: {
    Text("感谢你的反馈，我们会认真查看并持续改进小捷。")
}
```

- [ ] **Step 5: Implement the XAGE feedback sheet**

Add near the existing About/help sheets in `XAgeMainView.swift`:

```swift
private struct XAgeProblemFeedbackSheet: View {
    @Environment(\.dismiss) private var dismiss
    @ObservedObject var viewModel: SettingsViewModel
    let onSubmitted: () -> Void

    @State private var content = ""
    @State private var submitting = false

    private var trimmedContent: String {
        content.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private var canSubmit: Bool {
        (2...2000).contains(trimmedContent.count) && !submitting
    }

    var body: some View {
        XAgeSettingsInfoSheetScaffold(
            title: "问题反馈",
            subtitle: "告诉我们遇到的问题或改进建议",
            icon: "bubble.left.and.text.bubble.right.fill",
            onClose: {
                guard !submitting else { return }
                dismiss()
            }
        ) {
            VStack(alignment: .leading, spacing: 8) {
                Text("反馈内容")
                    .font(.system(size: 13, weight: .bold))
                    .foregroundStyle(Color(hex: "5D7890"))
                TextEditor(text: $content)
                    .frame(minHeight: 180)
                    .padding(10)
                    .scrollContentBackground(.hidden)
                    .background(XAgeCapsuleFill())
                    .accessibilityIdentifier("xage.feedback.content")
                Text("\(trimmedContent.count)/2000")
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(trimmedContent.count > 2000 ? .red : Color(hex: "7D9AB1"))
                    .frame(maxWidth: .infinity, alignment: .trailing)
            }

            XAgeMetricDetailRow(title: "联系我们", value: "jianjieaitech@163.com")
                .accessibilityIdentifier("xage.feedback.email")

            Button {
                guard canSubmit else { return }
                submitting = true
                viewModel.errorMessage = nil
                Task {
                    let ok = await viewModel.submitFeedback(
                        category: "general",
                        content: trimmedContent,
                        contact: nil
                    )
                    submitting = false
                    if ok {
                        dismiss()
                        onSubmitted()
                    }
                }
            } label: {
                XAgeGradientActionLabel(
                    title: submitting ? "提交中…" : "提交反馈",
                    icon: "paperplane.fill"
                )
            }
            .buttonStyle(.plain)
            .disabled(!canSubmit)
            .opacity(canSubmit ? 1 : 0.5)
            .accessibilityIdentifier("xage.feedback.submit")
        }
        .interactiveDismissDisabled(submitting)
        .accessibilityIdentifier("xage.feedback.page")
        .alert("提交失败", isPresented: Binding(
            get: { viewModel.errorMessage != nil },
            set: { if !$0 { viewModel.errorMessage = nil } }
        )) {
            Button("知道了", role: .cancel) {}
        } message: {
            Text(viewModel.errorMessage ?? "")
        }
    }
}
```

If `XAgeMetricDetailRow` does not expose its value as a separate static text in XCUITest, retain the explicit `xage.feedback.email` identifier and assert that element's label/value contains the exact email instead of duplicating visible text.

- [ ] **Step 6: Run the feedback UI test and verify GREEN**

Run the command from Step 2.

Expected: one UI test passes with zero failures.

- [ ] **Step 7: Run existing More-menu regression UI tests**

```bash
xcodebuild test \
  -project Xjie/Xjie.xcodeproj \
  -scheme Xjie \
  -destination 'platform=iOS Simulator,name=iPhone 17 Pro' \
  -only-testing:XjieUITests/XAgeHighIntensityContextUITests/testHighIntensityContextFlowUsesRealButtons \
  -only-testing:XjieUITests/XAgeHighIntensityContextUITests/testMoreMenuAccountSecurityNavigation \
  -only-testing:XjieUITests/XAgeHighIntensityContextUITests/testMoreMenuLegalPagesReturnToMenu
```

Expected: three UI tests pass; the new About entry does not break scrolling or return behavior.

- [ ] **Step 8: Commit the feedback feature**

Use interactive staging for `XAgeMainView.swift` because it contains pre-existing user changes. Stage only new feedback-related hunks plus the UI test:

```bash
git add -p Xjie/Xjie/Views/Home/XAgeMainView.swift
git add Xjie/XjieUITests/XAgeHighIntensityContextUITests.swift
git diff --cached --check
git commit -m "feat: add XAGE problem feedback page"
```

Before committing, inspect `git diff --cached` and confirm the staged `XAgeMainView.swift` changes do not include the pre-existing title/comment/subtitle edits unrelated to this feature.

### Task 4: Final Verification and Scope Audit

**Files:**
- Verify only; no expected production edits.

**Interfaces:**
- Consumes all behavior and UI produced by Tasks 1–3.
- Produces build/test evidence and a clean staging boundary.

- [ ] **Step 1: Run focused unit tests**

```bash
xcodebuild test \
  -project Xjie/Xjie.xcodeproj \
  -scheme Xjie \
  -destination 'platform=iOS Simulator,name=iPhone 17 Pro' \
  -only-testing:XjieTests/UtilsTests
```

Expected: all `UtilsTests` pass with zero failures.

- [ ] **Step 2: Run the two new UI tests together**

```bash
xcodebuild test \
  -project Xjie/Xjie.xcodeproj \
  -scheme Xjie \
  -destination 'platform=iOS Simulator,name=iPhone 17 Pro' \
  -only-testing:XjieUITests/XAgeHighIntensityContextUITests/testMedicationEditorQuickInputsReplaceAndAppend \
  -only-testing:XjieUITests/XAgeHighIntensityContextUITests/testMoreMenuProblemFeedbackShowsInputAndContactEmail
```

Expected: two UI tests pass with zero failures.

- [ ] **Step 3: Build the Debug app**

```bash
xcodebuild build \
  -project Xjie/Xjie.xcodeproj \
  -scheme Xjie \
  -configuration Debug \
  -destination 'platform=iOS Simulator,name=iPhone 17 Pro'
```

Expected: `BUILD SUCCEEDED`, with no “compiler is unable to type-check this expression in reasonable time” error.

- [ ] **Step 4: Audit whitespace and repository scope**

```bash
git diff --check
git status --short --branch
git log -8 --oneline --decorate
git diff -- Xjie/Xjie/Views/Home/XAgeMainView.swift
```

Expected:

- No whitespace errors.
- No staged changes remain after feature commits.
- Pre-existing unrelated `XAgeMainView.swift` edits and untracked user files remain untouched.
- Current branch remains `XAGE`.

- [ ] **Step 5: Report completion without pushing**

Summarize feature behavior, exact tests/build run, commits created, remaining unrelated working-tree changes, and current ahead/behind state. Do not push or open a PR unless the user explicitly requests it.
