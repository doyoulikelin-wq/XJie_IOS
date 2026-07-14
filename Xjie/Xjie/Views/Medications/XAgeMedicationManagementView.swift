import SwiftUI

// MARK: - 用药管理主页

/// 新版 XAGE 设置中的用药管理页面。
/// 服务端用药记录由 `MedicationViewModel` 维护；每次加载、保存或删除成功后，ViewModel 会按最新列表重新调度本地通知。
struct XAgeMedicationManagementView: View {
    var onClose: (() -> Void)?

    @StateObject private var vm = MedicationViewModel()
    // 新建和编辑分别驱动不同 Sheet；删除对象与正在删除的 ID 分开保存，用于确认文案和全列表防重复操作。
    @State private var editing: Medication?
    @State private var creating = false
    @State private var showAlarmPicker = false
    @State private var alarmDate = Date().addingTimeInterval(60)
    @State private var alarmFeedback: String?
    @State private var pendingDeletion: Medication?
    @State private var deletingMedicationID: Int?

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
    var body: some View {
        ZStack {
            XAgeMedicationLiquidBackground()
                .ignoresSafeArea()

            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    header

                    statusCard

                    if vm.loading && vm.medications.isEmpty {
                        XAgeMedicationLoadingCard()
                    } else if vm.medications.isEmpty {
                        emptyCard
                    } else {
                        VStack(spacing: 10) {
                            ForEach(vm.medications) { medication in
                                XAgeMedicationRow(
                                    medication: medication,
                                    isDeleting: deletingMedicationID == medication.id,
                                    deletionBusy: deletingMedicationID != nil,
                                    onEdit: {
                                        guard deletingMedicationID == nil else { return }
                                        editing = medication
                                    },
                                    onDelete: {
                                        guard deletingMedicationID == nil else { return }
                                        pendingDeletion = medication
                                    }
                                )
                            }
                        }
                    }

                    Button {
                        creating = true
                    } label: {
                        XAgeMedicationPrimaryActionLabel(title: "新增用药", icon: "plus")
                    }
                    .buttonStyle(.plain)
                    .disabled(deletingMedicationID != nil)
                    .accessibilityIdentifier("xage.medication.add")
                }
                .padding(.horizontal, 24)
                .padding(.top, 20)
                .padding(.bottom, 28)
            }
            .scrollIndicators(.hidden)
            .accessibilityIdentifier("xage.medication.root")
        }
        .task { await vm.load() }
        .sheet(isPresented: $creating) {
            // 新建成功后由保存闭包关闭 Sheet；失败时保留表单，错误通过主页统一提示。
            XAgeMedicationEditSheet(editing: nil) { body in
                let ok = await vm.save(body, editing: nil)
                if ok { creating = false }
            }
            .presentationDetents([.large])
        }
        .sheet(item: $editing) { medication in
            // 编辑页接收当前模型生成初始草稿，保存成功后再清空 selection，避免请求期间页面提前消失。
            XAgeMedicationEditSheet(editing: medication) { body in
                let ok = await vm.save(body, editing: medication)
                if ok { editing = nil }
            }
            .presentationDetents([.large])
        }
        .sheet(isPresented: $showAlarmPicker) {
            // 顶栏闹钟是独立的一次性本地提醒，不属于任何具体药物，也不会上传到服务端。
            XAgeMedicationAlarmSheet(alarmDate: $alarmDate) { target in
                let interval = max(1, target.timeIntervalSinceNow)
                await NotificationScheduler.shared.scheduleCustomAlarm(at: target)
                await MainActor.run {
                    let formatter = DateFormatter()
                    formatter.dateFormat = "yyyy-MM-dd HH:mm"
                    alarmFeedback = "将于 \(formatter.string(from: target)) 提醒你（约 \(Int(interval / 60)) 分钟后）。"
                    showAlarmPicker = false
                }
            }
            .presentationDetents([.large])
            .presentationDragIndicator(.visible)
        }
        .alert(
            "删除用药？",
            isPresented: Binding(
                get: { pendingDeletion != nil },
                set: { if !$0 { pendingDeletion = nil } }
            ),
            presenting: pendingDeletion
        ) { medication in
            // 删除会同时移除服务端记录，并由 ViewModel 基于剩余药物重建本地提醒。
            Button("取消", role: .cancel) {}
            Button("删除", role: .destructive) {
                deleteMedication(medication)
            }
        } message: { medication in
            Text("“\(medication.name)”及其本地提醒将被删除，此操作无法撤销。")
        }
        .alert("提示", isPresented: Binding(get: { vm.error != nil }, set: { if !$0 { vm.error = nil } })) {
            Button("好") { vm.error = nil }
        } message: {
            Text(vm.error ?? "")
        }
        .alert("闹钟已设定", isPresented: Binding(get: { alarmFeedback != nil }, set: { if !$0 { alarmFeedback = nil } })) {
            Button("好") { alarmFeedback = nil }
        } message: {
            Text(alarmFeedback ?? "")
        }
    }

    /// 构建 `header` 对应的局部 SwiftUI 视图，并组合所需的展示状态与交互。
    private var header: some View {
        HStack(spacing: 12) {
            Button {
                onClose?()
            } label: {
                Image(systemName: "chevron.left")
                    .font(.system(size: 15, weight: .bold))
                    .foregroundStyle(Color(hex: "1268BD"))
                    .frame(width: 38, height: 38)
                    .background(XAgeMedicationCapsuleFill())
                    .frame(width: 44, height: 44)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .disabled(deletingMedicationID != nil)
            .opacity(onClose == nil ? 0 : 1)
            .allowsHitTesting(onClose != nil)
            .accessibilityHidden(onClose == nil)
            .accessibilityLabel("返回")

            VStack(alignment: .leading, spacing: 3) {
                Text("用药管理")
                    .font(.system(size: 28, weight: .bold))
                    .foregroundStyle(Color(hex: "123E67"))
                Text("药物、提醒和疗程")
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(Color(hex: "5D7890"))
            }

            Spacer()

            Button {
                alarmDate = Date().addingTimeInterval(60)
                showAlarmPicker = true
            } label: {
                Image(systemName: "alarm.fill")
                    .font(.system(size: 15, weight: .bold))
                    .foregroundStyle(Color(hex: "1268BD"))
                    .frame(width: 38, height: 38)
                    .background(XAgeMedicationCapsuleFill())
                    .frame(width: 44, height: 44)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .disabled(deletingMedicationID != nil)
            .accessibilityIdentifier("xage.medication.alarm")
        }
    }

    /// 构建 `statusCard` 对应的局部 SwiftUI 视图，并组合所需的展示状态与交互。
    private var statusCard: some View {
        HStack(spacing: 14) {
            ZStack {
                Circle()
                    .fill(LinearGradient(colors: [Color(hex: "22D4BF"), Color(hex: "1E8BE3")], startPoint: .topLeading, endPoint: .bottomTrailing))
                Image(systemName: "pills.fill")
                    .font(.system(size: 24, weight: .bold))
                    .foregroundStyle(.white)
            }
            .frame(width: 58, height: 58)

            VStack(alignment: .leading, spacing: 5) {
                Text(statusTitle)
                    .font(.system(size: 21, weight: .bold))
                    .foregroundStyle(Color(hex: "123E67"))
                Text(statusSubtitle)
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(Color(hex: "5D7890"))
                    .lineLimit(2)
            }

            Spacer(minLength: 0)
        }
        .padding(18)
        .background(XAgeMedicationGlassCard(cornerRadius: 28))
    }

    /// 构建 `emptyCard` 对应的局部 SwiftUI 视图，并组合所需的展示状态与交互。
    private var emptyCard: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 10) {
                Image(systemName: "plus.circle.fill")
                    .font(.system(size: 22, weight: .bold))
                    .foregroundStyle(Color(hex: "20CDB1"))
                Text("还没有用药记录")
                    .font(.system(size: 20, weight: .bold))
                    .foregroundStyle(Color(hex: "123E67"))
            }
            Text("添加正在使用的药物、剂量和提醒时间后，小捷会把用药信息纳入问答上下文，并在本地安排提醒。")
                .font(.system(size: 14))
                .foregroundStyle(Color(hex: "496A83"))
                .lineSpacing(3)
            Button {
                creating = true
            } label: {
                XAgeMedicationPrimaryActionLabel(title: "添加第一条", icon: "plus")
            }
            .buttonStyle(.plain)
        }
        .padding(18)
        .background(XAgeMedicationGlassCard(cornerRadius: 28))
    }

    private var statusTitle: String {
        if vm.medications.isEmpty { return "待添加用药" }
        let activeCount = vm.medications.filter { $0.enabled && $0.isCourseActive() }.count
        return "\(activeCount) 项正在提醒"
    }

    private var statusSubtitle: String {
        if vm.medications.isEmpty { return "当前没有入库用药，问答不会引用用药上下文。" }
        let totalTimes = vm.medications.reduce(0) { $0 + $1.schedule_times.count }
        return "共 \(vm.medications.count) 项记录，\(totalTimes) 个提醒时间；保存后会重新同步本地提醒。"
    }

    /// 执行 `deleteMedication` 对应的删除、撤销或退出操作，并处理关联状态。
    private func deleteMedication(_ medication: Medication) {
        // 同一时间只允许一个删除任务；ID 同时用于禁用其他操作并在对应行显示进度。
        guard deletingMedicationID == nil else { return }
        deletingMedicationID = medication.id
        Task {
            await vm.delete(medication)
            deletingMedicationID = nil
        }
    }
}

// MARK: - 用药列表行

/// 单条用药摘要，展示启停状态、剂量、频次、最多四个提醒时间和疗程范围。
private struct XAgeMedicationRow: View {
    let medication: Medication
    let isDeleting: Bool
    let deletionBusy: Bool
    var onEdit: () -> Void
    var onDelete: () -> Void

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .top, spacing: 12) {
                ZStack {
                    Circle()
                        .fill(medication.enabled ? Color(hex: "20CDB1") : Color(hex: "A8B8C8"))
                    Image(systemName: medication.enabled ? "bell.fill" : "bell.slash.fill")
                        .font(.system(size: 15, weight: .bold))
                        .foregroundStyle(.white)
                }
                .frame(width: 34, height: 34)

                VStack(alignment: .leading, spacing: 4) {
                    HStack(alignment: .firstTextBaseline, spacing: 6) {
                        Text(medication.name)
                            .font(.system(size: 19, weight: .bold))
                            .foregroundStyle(Color(hex: "123E67"))
                            .lineLimit(1)
                        if let dosage = medication.dosage, !dosage.isEmpty {
                            Text(dosage)
                                .font(.system(size: 13, weight: .bold))
                                .foregroundStyle(Color(hex: "5D7890"))
                                .lineLimit(1)
                        }
                    }
                    Text(medication.frequency?.nilIfBlank ?? "未填写频次")
                        .font(.system(size: 13, weight: .semibold))
                        .foregroundStyle(Color(hex: "5D7890"))
                        .lineLimit(1)
                }

                Spacer(minLength: 0)

                Text(medication.enabled ? "启用" : "暂停")
                    .font(.system(size: 12, weight: .bold))
                    .foregroundStyle(medication.enabled ? Color(hex: "13A98F") : Color(hex: "7D8EA0"))
                    .padding(.horizontal, 10)
                    .padding(.vertical, 6)
                    .background(XAgeMedicationCapsuleFill())
            }

            if !medication.schedule_times.isEmpty {
                HStack(spacing: 7) {
                    ForEach(medication.schedule_times.prefix(4), id: \.self) { time in
                        Text(time)
                            .font(.system(size: 12, weight: .bold, design: .monospaced))
                            .foregroundStyle(Color(hex: "1268BD"))
                            .padding(.horizontal, 9)
                            .padding(.vertical, 6)
                            .background(XAgeMedicationCapsuleFill())
                    }
                    if medication.schedule_times.count > 4 {
                        Text("+\(medication.schedule_times.count - 4)")
                            .font(.system(size: 12, weight: .bold))
                            .foregroundStyle(Color(hex: "5D7890"))
                    }
                }
            }

            if let instructions = medication.instructions, !instructions.isEmpty {
                Text(instructions)
                    .font(.system(size: 13))
                    .foregroundStyle(Color(hex: "496A83"))
                    .lineLimit(2)
            }

            HStack(spacing: 10) {
                if let range = courseRangeText {
                    Text(range)
                        .font(.system(size: 12, weight: .semibold))
                        .foregroundStyle(Color(hex: "6D8498"))
                        .lineLimit(1)
                    Spacer(minLength: 0)
                }

                Button(action: onEdit) {
                    Text("编辑")
                        .font(.system(size: 13, weight: .bold))
                        .foregroundStyle(Color(hex: "1268BD"))
                        .frame(minWidth: 56, minHeight: 44)
                        .background {
                            XAgeMedicationCapsuleFill()
                                .frame(height: 32)
                        }
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .disabled(deletionBusy)

                Button(role: .destructive, action: onDelete) {
                    Group {
                        if isDeleting {
                            ProgressView()
                                .controlSize(.small)
                        } else {
                            Text("删除")
                                .font(.system(size: 13, weight: .bold))
                        }
                    }
                    .frame(minWidth: 56, minHeight: 44)
                    .background {
                        XAgeMedicationCapsuleFill()
                            .frame(height: 32)
                    }
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .disabled(deletionBusy)
                .accessibilityLabel(isDeleting ? "正在删除\(medication.name)" : "删除\(medication.name)")
            }
        }
        .padding(16)
        .background(XAgeMedicationGlassCard(cornerRadius: 26))
    }

    private var courseRangeText: String? {
        guard let start = medication.course_start, let end = medication.course_end else { return nil }
        return "\(start) - \(end)"
    }
}

private enum XAgeMedicationEditField: Hashable {
    case name
    case dosage
    case frequency
    case instructions

    var id: String {
        switch self {
        case .name: return "name"
        case .dosage: return "dosage"
        case .frequency: return "frequency"
        case .instructions: return "instructions"
        }
    }
}

// MARK: - 用药编辑表单

/// 编辑页的可比较快照。当前输入与初始快照不一致时，页面会阻止手势关闭并提示保存或放弃。
private struct XAgeMedicationDraft: Equatable {
    let name: String
    let dosage: String
    let frequency: String
    let instructions: String
    let scheduleTimes: [String]
    let courseStart: Date?
    let courseEnd: Date?
    let enabled: Bool
}

/// 新建和编辑共用的用药表单。
/// 页面只负责收集并规范化字段，实际创建/更新及通知重调度由外部提交闭包和 ViewModel 完成。
private struct XAgeMedicationEditSheet: View {
    let editing: Medication?
    let onSubmit: (MedicationBody) async -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var name = ""
    @State private var dosage = ""
    @State private var frequency = ""
    @State private var instructions = ""
    @State private var scheduleTimes: [String] = []
    @State private var courseStart: Date?
    @State private var courseEnd: Date?
    @State private var enabled = true
    @State private var showAddTime = false
    @State private var newTime = Date()
    @State private var saving = false
    @State private var initialDraft: XAgeMedicationDraft?
    @State private var showDiscardConfirmation = false
    @FocusState private var focusedField: XAgeMedicationEditField?

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
    var body: some View {
        ZStack {
            XAgeMedicationLiquidBackground()
                .ignoresSafeArea()

            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    sheetHeader
                    medicationFields
                    reminderFields
                    courseFields
                    saveButton
                }
                .padding(.horizontal, 24)
                .padding(.top, 20)
                .padding(.bottom, 28)
            }
            .scrollDismissesKeyboard(.interactively)
        }
        .onAppear(perform: loadFromEditing)
        // 有未保存修改或正在请求时禁止下滑关闭，避免用户无提示丢失输入或中断保存反馈。
        .interactiveDismissDisabled(hasUnsavedChanges || saving)
        .presentationDragIndicator(hasUnsavedChanges || saving ? .hidden : .visible)
        .toolbar {
            ToolbarItemGroup(placement: .keyboard) {
                Spacer()
                Button("完成") {
                    focusedField = nil
                }
                .font(.system(size: 15, weight: .bold))
            }
        }
        .sheet(isPresented: $showAddTime) {
            XAgeMedicationTimePicker(newTime: $newTime) { time in
                // 提醒时间统一保存为 HH:mm，并在加入时去重、排序，便于服务端和通知调度器稳定消费。
                let components = Calendar.current.dateComponents([.hour, .minute], from: time)
                let value = String(format: "%02d:%02d", components.hour ?? 0, components.minute ?? 0)
                if !scheduleTimes.contains(value) {
                    scheduleTimes.append(value)
                    scheduleTimes.sort()
                }
                showAddTime = false
            }
            .presentationDetents([.medium])
            .presentationDragIndicator(.visible)
        }
        .alert("放弃未保存的修改？", isPresented: $showDiscardConfirmation) {
            Button("继续编辑", role: .cancel) {}
            Button("放弃修改", role: .destructive) {
                focusedField = nil
                dismiss()
            }
        } message: {
            Text("当前填写的用药信息尚未保存，放弃后无法恢复。")
        }
    }

    /// 构建 `sheetHeader` 对应的局部 SwiftUI 视图，并组合所需的展示状态与交互。
    private var sheetHeader: some View {
        HStack {
            VStack(alignment: .leading, spacing: 4) {
                Text(editing == nil ? "添加用药" : "编辑用药")
                    .font(.system(size: 28, weight: .bold))
                    .foregroundStyle(Color(hex: "123E67"))
                Text("保存后会更新问答上下文和本地提醒")
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(Color(hex: "5D7890"))
            }
            Spacer()
            Button {
                requestDismiss()
            } label: {
                Image(systemName: "xmark")
                    .font(.system(size: 13, weight: .bold))
                    .foregroundStyle(Color(hex: "1268BD"))
                    .frame(width: 36, height: 36)
                    .background(XAgeMedicationCapsuleFill())
                    .frame(width: 44, height: 44)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .disabled(saving)
            .accessibilityLabel("关闭用药编辑")
        }
    }

    /// 构建 `medicationFields` 对应的局部 SwiftUI 视图，并组合所需的展示状态与交互。
    private var medicationFields: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("药品信息")
                .font(.system(size: 13, weight: .bold))
                .foregroundStyle(Color(hex: "5D7890"))
            XAgeMedicationTextField(
                title: "药品名称",
                text: $name,
                focusedField: $focusedField,
                field: .name,
                submitLabel: .next,
                onSubmit: { focusedField = .dosage }
            )
            XAgeMedicationTextField(
                title: "剂量",
                placeholder: "如 5mg / 1片",
                text: $dosage,
                focusedField: $focusedField,
                field: .dosage,
                submitLabel: .next,
                onSubmit: { focusedField = .frequency }
            )
            XAgeMedicationQuickOptions(
                fieldID: "dosage",
                options: MedicationQuickInput.dosageOptions
            ) { option in
                dosage = MedicationQuickInput.applying(option, to: dosage, behavior: .replace)
            }
            XAgeMedicationTextField(
                title: "频次",
                placeholder: "如 每日 3 次",
                text: $frequency,
                focusedField: $focusedField,
                field: .frequency,
                submitLabel: .next,
                onSubmit: { focusedField = .instructions }
            )
            XAgeMedicationQuickOptions(
                fieldID: "frequency",
                options: MedicationQuickInput.frequencyOptions
            ) { option in
                frequency = MedicationQuickInput.applying(option, to: frequency, behavior: .replace)
            }
            XAgeMedicationTextField(
                title: "使用说明",
                placeholder: "饭后 / 空腹 / 注意事项",
                text: $instructions,
                focusedField: $focusedField,
                field: .instructions,
                axis: .vertical
            )
            XAgeMedicationQuickOptions(
                fieldID: "instructions",
                options: MedicationQuickInput.instructionOptions
            ) { option in
                instructions = MedicationQuickInput.applying(option, to: instructions, behavior: .appendInstruction)
            }
        }
        .padding(16)
        .background(XAgeMedicationGlassCard(cornerRadius: 26))
    }

    /// 构建 `reminderFields` 对应的局部 SwiftUI 视图，并组合所需的展示状态与交互。
    private var reminderFields: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("提醒时间")
                    .font(.system(size: 13, weight: .bold))
                    .foregroundStyle(Color(hex: "5D7890"))
                Spacer()
                Button {
                    focusedField = nil
                    newTime = Date()
                    showAddTime = true
                } label: {
                    Label("添加", systemImage: "plus")
                        .font(.system(size: 13, weight: .bold))
                        .foregroundStyle(Color(hex: "1268BD"))
                        .padding(.horizontal, 12)
                        .frame(minHeight: 44)
                        .background {
                            XAgeMedicationCapsuleFill()
                                .frame(height: 32)
                        }
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
            }

            if scheduleTimes.isEmpty {
                Text("还没有提醒时间")
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(Color(hex: "7D9AB1"))
            } else {
                XAgeMedicationFlowLayout(spacing: 8) {
                    ForEach(scheduleTimes, id: \.self) { time in
                        Button {
                            scheduleTimes.removeAll { $0 == time }
                        } label: {
                            HStack(spacing: 6) {
                                Image(systemName: "bell.fill")
                                Text(time)
                                Image(systemName: "xmark.circle.fill")
                            }
                            .font(.system(size: 12, weight: .bold, design: .monospaced))
                            .foregroundStyle(Color(hex: "1268BD"))
                            .padding(.horizontal, 10)
                            .frame(minHeight: 44)
                            .background {
                                XAgeMedicationCapsuleFill()
                                    .frame(height: 32)
                            }
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        .accessibilityLabel("移除 \(time) 提醒")
                    }
                }
            }
        }
        .padding(16)
        .background(XAgeMedicationGlassCard(cornerRadius: 26))
    }

    /// 构建 `courseFields` 对应的局部 SwiftUI 视图，并组合所需的展示状态与交互。
    private var courseFields: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("疗程窗口")
                .font(.system(size: 13, weight: .bold))
                .foregroundStyle(Color(hex: "5D7890"))

            Toggle("启用提醒", isOn: $enabled)
                .tint(Color(hex: "20CDB1"))
                .font(.system(size: 15, weight: .semibold))

            DatePicker("开始日期", selection: Binding(
                get: { courseStart ?? Date() },
                set: { courseStart = $0 }
            ), displayedComponents: .date)

            DatePicker("结束日期", selection: Binding(
                get: { courseEnd ?? Date() },
                set: { courseEnd = $0 }
            ), displayedComponents: .date)
        }
        .font(.system(size: 15, weight: .semibold))
        .foregroundStyle(Color(hex: "123E67"))
        .padding(16)
        .background(XAgeMedicationGlassCard(cornerRadius: 26))
    }

    /// 构建 `saveButton` 对应的局部 SwiftUI 视图，并组合所需的展示状态与交互。
    private var saveButton: some View {
        Button {
            focusedField = nil
            Task { await submit() }
        } label: {
            XAgeMedicationPrimaryActionLabel(title: saving ? "保存中…" : "保存", icon: "checkmark")
        }
        .buttonStyle(.plain)
        .disabled(name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || saving)
        .opacity(name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? 0.48 : 1)
    }

    private var currentDraft: XAgeMedicationDraft {
        // 将分散的表单 State 聚合为值类型，便于一次比较所有字段是否发生变化。
        XAgeMedicationDraft(
            name: name,
            dosage: dosage,
            frequency: frequency,
            instructions: instructions,
            scheduleTimes: scheduleTimes,
            courseStart: courseStart,
            courseEnd: courseEnd,
            enabled: enabled
        )
    }

    private var hasUnsavedChanges: Bool {
        guard let initialDraft else { return false }
        return currentDraft != initialDraft
    }

    /// 加载或请求 `loadFromEditing` 所需的数据，并返回整理后的结果。
    private func loadFromEditing() {
        // 只初始化一次，防止 Sheet 内部状态刷新时用服务端旧值覆盖用户正在输入的内容。
        guard initialDraft == nil else { return }
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd"
        let draft = XAgeMedicationDraft(
            name: editing?.name ?? "",
            dosage: editing?.dosage ?? "",
            frequency: editing?.frequency ?? "",
            instructions: editing?.instructions ?? "",
            scheduleTimes: editing?.schedule_times ?? [],
            courseStart: editing?.course_start.flatMap { formatter.date(from: $0) },
            courseEnd: editing?.course_end.flatMap { formatter.date(from: $0) },
            enabled: editing?.enabled ?? true
        )
        name = draft.name
        dosage = draft.dosage
        frequency = draft.frequency
        instructions = draft.instructions
        scheduleTimes = draft.scheduleTimes
        courseStart = draft.courseStart
        courseEnd = draft.courseEnd
        enabled = draft.enabled
        initialDraft = draft
    }

    /// 发起 `requestDismiss` 对应的权限、关闭或状态变更请求。
    private func requestDismiss() {
        // 保存期间不允许关闭；其他情况下根据草稿比较结果决定直接退出或要求确认放弃。
        focusedField = nil
        guard !saving else { return }
        if hasUnsavedChanges {
            showDiscardConfirmation = true
        } else {
            dismiss()
        }
    }

    /// 校验并规范化编辑草稿，提交新增或更新请求；成功后同步本地提醒并关闭编辑页。
    private func submit() async {
        // 提交前清理首尾空白、把空选填项转换为 nil，并将日期格式化为服务端约定的 yyyy-MM-dd。
        guard !saving else { return }
        focusedField = nil
        saving = true
        defer { saving = false }
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd"
        let body = MedicationBody(
            name: name.trimmingCharacters(in: .whitespacesAndNewlines),
            dosage: dosage.trimmedNil,
            frequency: frequency.trimmedNil,
            instructions: instructions.trimmedNil,
            schedule_times: scheduleTimes,
            course_start: courseStart.map { formatter.string(from: $0) },
            course_end: courseEnd.map { formatter.string(from: $0) },
            photo_url: nil,
            enabled: enabled
        )
        await onSubmit(body)
    }
}

// MARK: - 独立闹钟与每日提醒时间

/// 创建一次性的自定义本地闹钟，与用药记录中的每日循环提醒相互独立。
private struct XAgeMedicationAlarmSheet: View {
    @Binding var alarmDate: Date
    var onConfirm: (Date) async -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var saving = false

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
    var body: some View {
        ZStack {
            XAgeMedicationLiquidBackground()
                .ignoresSafeArea()
            VStack(alignment: .leading, spacing: 16) {
                HStack {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("设定闹钟")
                            .font(.system(size: 28, weight: .bold))
                            .foregroundStyle(Color(hex: "123E67"))
                        Text("独立本地提醒，不会上传到服务器。")
                            .font(.system(size: 13, weight: .semibold))
                            .foregroundStyle(Color(hex: "5D7890"))
                    }
                    Spacer()
                    Button { dismiss() } label: {
                        Image(systemName: "xmark")
                            .font(.system(size: 13, weight: .bold))
                            .foregroundStyle(Color(hex: "1268BD"))
                            .frame(width: 36, height: 36)
                            .background(XAgeMedicationCapsuleFill())
                            .frame(width: 44, height: 44)
                            .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("关闭闹钟设置")
                }
                DatePicker("提醒时间", selection: $alarmDate, in: Date()..., displayedComponents: [.date, .hourAndMinute])
                    .datePickerStyle(.graphical)
                    .padding(12)
                    .background(XAgeMedicationGlassCard(cornerRadius: 26))
                Button {
                    saving = true
                    Task {
                        await onConfirm(alarmDate)
                        await MainActor.run {
                            saving = false
                            dismiss()
                        }
                    }
                } label: {
                    XAgeMedicationPrimaryActionLabel(title: saving ? "设定中…" : "确定", icon: "alarm.fill")
                }
                .buttonStyle(.plain)
                .disabled(alarmDate <= Date() || saving)
                Spacer(minLength: 0)
            }
            .padding(24)
        }
    }
}

/// 只选择每日时刻，最终的去重、排序和写入由父编辑页处理。
private struct XAgeMedicationTimePicker: View {
    @Binding var newTime: Date
    var onAdd: (Date) -> Void
    @Environment(\.dismiss) private var dismiss

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
    var body: some View {
        ZStack {
            XAgeMedicationLiquidBackground()
                .ignoresSafeArea()
            VStack(spacing: 16) {
                HStack {
                    Text("添加提醒时间")
                        .font(.system(size: 24, weight: .bold))
                        .foregroundStyle(Color(hex: "123E67"))
                    Spacer()
                    Button("取消") { dismiss() }
                        .font(.system(size: 14, weight: .bold))
                        .foregroundStyle(Color(hex: "1268BD"))
                        .frame(minWidth: 44, minHeight: 44, alignment: .trailing)
                        .contentShape(Rectangle())
                }
                DatePicker("选择时间", selection: $newTime, displayedComponents: .hourAndMinute)
                    .datePickerStyle(.wheel)
                    .labelsHidden()
                Button {
                    onAdd(newTime)
                    dismiss()
                } label: {
                    XAgeMedicationPrimaryActionLabel(title: "添加", icon: "plus")
                }
                .buttonStyle(.plain)
            }
            .padding(24)
        }
    }
}

/// 为用药表单字段展示可自动换行的快捷输入气泡，具体写入规则由父表单决定。
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
                    Button(option) {
                        onSelect(option)
                    }
                    .font(.system(size: 12, weight: .bold))
                    .foregroundStyle(Color(hex: "1268BD"))
                    .padding(.horizontal, 11)
                    .frame(minHeight: 44)
                    .background {
                        XAgeMedicationCapsuleFill()
                            .frame(height: 32)
                    }
                    .contentShape(Rectangle())
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("xage.medication.quick.\(fieldID).\(option)")
                }
            }
        }
    }
}

private struct XAgeMedicationTextField: View {
    let title: String
    var placeholder: String = ""
    @Binding var text: String
    var focusedField: FocusState<XAgeMedicationEditField?>.Binding
    let field: XAgeMedicationEditField
    var axis: Axis = .horizontal
    var submitLabel: SubmitLabel = .done
    var onSubmit: (() -> Void)?

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            Text(title)
                .font(.system(size: 12, weight: .bold))
                .foregroundStyle(Color(hex: "6C8194"))
            Group {
                if axis == .vertical {
                    baseTextField
                } else {
                    baseTextField
                        .submitLabel(submitLabel)
                        .onSubmit {
                            onSubmit?()
                        }
                }
            }
        }
    }

    /// 构建 `baseTextField` 对应的局部 SwiftUI 视图，并组合所需的展示状态与交互。
    private var baseTextField: some View {
        TextField(placeholder.isEmpty ? title : placeholder, text: $text, axis: axis)
            .focused(focusedField, equals: field)
            .font(.system(size: 16, weight: .semibold))
            .foregroundStyle(Color(hex: "123E67"))
            .lineLimit(axis == .vertical ? 2...5 : 1...1)
            .padding(.horizontal, 14)
            .padding(.vertical, 12)
            .background(XAgeMedicationCapsuleFill())
            .accessibilityIdentifier("xage.medication.edit.\(field.id)")
    }
}

private struct XAgeMedicationLoadingCard: View {
    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
    var body: some View {
        HStack(spacing: 12) {
            ProgressView()
                .tint(Color(hex: "20CDB1"))
            Text("正在读取用药记录")
                .font(.system(size: 15, weight: .semibold))
                .foregroundStyle(Color(hex: "496A83"))
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(18)
        .background(XAgeMedicationGlassCard(cornerRadius: 26))
    }
}

private struct XAgeMedicationFlowLayout: Layout {
    var spacing: CGFloat = 8

    /// 计算自定义布局在当前提议尺寸下所需的整体大小。
    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let maxWidth = proposal.width ?? 320
        var currentX: CGFloat = 0
        var currentY: CGFloat = 0
        var rowHeight: CGFloat = 0

        for subview in subviews {
            let size = subview.sizeThatFits(.unspecified)
            if currentX > 0, currentX + size.width > maxWidth {
                currentX = 0
                currentY += rowHeight + spacing
                rowHeight = 0
            }
            currentX += size.width + spacing
            rowHeight = max(rowHeight, size.height)
        }

        return CGSize(width: maxWidth, height: currentY + rowHeight)
    }

    /// 依据可用边界与提议尺寸排列自定义布局中的子视图。
    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var currentX = bounds.minX
        var currentY = bounds.minY
        var rowHeight: CGFloat = 0

        for subview in subviews {
            let size = subview.sizeThatFits(.unspecified)
            if currentX > bounds.minX, currentX + size.width > bounds.maxX {
                currentX = bounds.minX
                currentY += rowHeight + spacing
                rowHeight = 0
            }
            subview.place(
                at: CGPoint(x: currentX, y: currentY),
                proposal: ProposedViewSize(size)
            )
            currentX += size.width + spacing
            rowHeight = max(rowHeight, size.height)
        }
    }
}

private extension String {
    var trimmedNil: String? {
        let value = trimmingCharacters(in: .whitespacesAndNewlines)
        return value.isEmpty ? nil : value
    }

    var nilIfBlank: String? {
        trimmedNil
    }
}
