import SwiftUI

struct XAgeMedicationManagementView: View {
    var onClose: (() -> Void)?

    @StateObject private var vm = MedicationViewModel()
    @State private var editing: Medication?
    @State private var creating = false
    @State private var showAlarmPicker = false
    @State private var alarmDate = Date().addingTimeInterval(60)
    @State private var alarmFeedback: String?
    @State private var pendingDeletion: Medication?
    @State private var deletingMedicationID: Int?

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
            XAgeMedicationEditSheet(editing: nil) { body in
                let ok = await vm.save(body, editing: nil)
                if ok { creating = false }
            }
            .presentationDetents([.large])
        }
        .sheet(item: $editing) { medication in
            XAgeMedicationEditSheet(editing: medication) { body in
                let ok = await vm.save(body, editing: medication)
                if ok { editing = nil }
            }
            .presentationDetents([.large])
        }
        .sheet(isPresented: $showAlarmPicker) {
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

    private func deleteMedication(_ medication: Medication) {
        guard deletingMedicationID == nil else { return }
        deletingMedicationID = medication.id
        Task {
            await vm.delete(medication)
            deletingMedicationID = nil
        }
    }
}

private struct XAgeMedicationRow: View {
    let medication: Medication
    let isDeleting: Bool
    let deletionBusy: Bool
    var onEdit: () -> Void
    var onDelete: () -> Void

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
            XAgeMedicationTextField(
                title: "频次",
                placeholder: "如 每日 3 次",
                text: $frequency,
                focusedField: $focusedField,
                field: .frequency,
                submitLabel: .next,
                onSubmit: { focusedField = .instructions }
            )
            XAgeMedicationTextField(
                title: "使用说明",
                placeholder: "饭后 / 空腹 / 注意事项",
                text: $instructions,
                focusedField: $focusedField,
                field: .instructions,
                axis: .vertical
            )
        }
        .padding(16)
        .background(XAgeMedicationGlassCard(cornerRadius: 26))
    }

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

    private func loadFromEditing() {
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

    private func requestDismiss() {
        focusedField = nil
        guard !saving else { return }
        if hasUnsavedChanges {
            showDiscardConfirmation = true
        } else {
            dismiss()
        }
    }

    private func submit() async {
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

private struct XAgeMedicationAlarmSheet: View {
    @Binding var alarmDate: Date
    var onConfirm: (Date) async -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var saving = false

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

private struct XAgeMedicationTimePicker: View {
    @Binding var newTime: Date
    var onAdd: (Date) -> Void
    @Environment(\.dismiss) private var dismiss

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

private struct XAgeMedicationTextField: View {
    let title: String
    var placeholder: String = ""
    @Binding var text: String
    var focusedField: FocusState<XAgeMedicationEditField?>.Binding
    let field: XAgeMedicationEditField
    var axis: Axis = .horizontal
    var submitLabel: SubmitLabel = .done
    var onSubmit: (() -> Void)?

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

private struct XAgeMedicationPrimaryActionLabel: View {
    let title: String
    let icon: String

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: icon)
                .font(.system(size: 15, weight: .bold))
            Text(title)
                .font(.system(size: 17, weight: .bold))
        }
        .foregroundStyle(.white)
        .frame(maxWidth: .infinity)
        .frame(height: 56)
        .background(
            LinearGradient(colors: [Color(hex: "22D4BF"), Color(hex: "1F8EEA")], startPoint: .leading, endPoint: .trailing)
        )
        .clipShape(Capsule())
        .shadow(color: Color(hex: "20CDB1").opacity(0.24), radius: 16, x: 0, y: 10)
    }
}

private struct XAgeMedicationLoadingCard: View {
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

private struct XAgeMedicationGlassCard: View {
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

private struct XAgeMedicationCapsuleFill: View {
    var body: some View {
        Capsule()
            .fill(.white.opacity(0.62))
            .overlay(Capsule().stroke(.white.opacity(0.72), lineWidth: 1))
            .shadow(color: Color(hex: "78BCE8").opacity(0.10), radius: 10, x: 0, y: 5)
    }
}

private struct XAgeMedicationLiquidBackground: View {
    var body: some View {
        LinearGradient(
            colors: [
                Color(hex: "D9F5FF"),
                Color(hex: "EAF9FF"),
                Color(hex: "F8FCFF")
            ],
            startPoint: .topLeading,
            endPoint: .bottomTrailing
        )
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
