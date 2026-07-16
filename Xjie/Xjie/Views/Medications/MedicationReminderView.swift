import SwiftUI
import UIKit

struct MedicationReminderEditorView: View {
    let plan: TrustedMedicationPlan
    let permission: MedicationReminderPermissionState
    let onSave: (MedicationReminderSettings) async -> Bool

    @Environment(\.dismiss) private var dismiss
    @Environment(\.openURL) private var openURL
    @State private var settings: MedicationReminderSettings
    @State private var initialSettings: MedicationReminderSettings
    @State private var timeText: String
    @State private var initialTimeText: String
    @State private var saving = false
    @State private var showDiscard = false
    @FocusState private var timeFocused: Bool

    init(
        plan: TrustedMedicationPlan,
        settings: MedicationReminderSettings,
        permission: MedicationReminderPermissionState,
        onSave: @escaping (MedicationReminderSettings) async -> Bool
    ) {
        self.plan = plan
        self.permission = permission
        self.onSave = onSave
        _settings = State(initialValue: settings)
        _initialSettings = State(initialValue: settings)
        let times = settings.times.joined(separator: "、")
        _timeText = State(initialValue: times)
        _initialTimeText = State(initialValue: times)
    }

    var body: some View {
        ZStack {
            LinearGradient(
                colors: [Color(hex: "D9F5FF"), Color(hex: "EAF9FF"), Color(hex: "F8FCFF")],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )
            .ignoresSafeArea()
            .onTapGesture { timeFocused = false }

            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    header
                    permissionCard
                    reminderFields
                    privacyFields
                    boundaryCard
                    saveButton
                }
                .padding(20)
                .xAgeDismissKeyboardOnDownwardPull(
                    verificationIdentifier: "xage.medication.reminder.pullDismiss.ready"
                ) {
                    timeFocused = false
                }
            }
            .scrollDismissesKeyboard(.interactively)
            .accessibilityIdentifier("xage.medication.reminder.root")
        }
        .interactiveDismissDisabled(hasChanges || saving)
        .presentationDragIndicator(hasChanges || saving ? .hidden : .visible)
        .xAgeKeyboardDoneAccessory(
            isPresented: timeFocused,
            accessibilityIdentifier: "xage.medication.reminder.keyboard.done"
        ) {
            timeFocused = false
        }
        .alert("放弃未保存的提醒设置？", isPresented: $showDiscard) {
            Button("继续编辑", role: .cancel) {}
            Button("放弃", role: .destructive) { dismiss() }
        }
    }

    private var header: some View {
        HStack(alignment: .top) {
            VStack(alignment: .leading, spacing: 3) {
                Text("服药提醒设置")
                    .font(.title.bold())
                    .foregroundStyle(Color(hex: "123E67"))
                Text("\(plan.displayName) · 绑定计划 v\(plan.version)")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(Color(hex: "5D7890"))
            }
            Spacer(minLength: 8)
            Button(action: requestClose) {
                Image(systemName: "xmark")
                    .frame(width: 44, height: 44)
                    .background(.white.opacity(0.62), in: Capsule())
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .disabled(saving)
            .accessibilityLabel("关闭提醒设置")
            .accessibilityIdentifier("xage.medication.reminder.close")
        }
    }

    private var permissionCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            Label(permission.title, systemImage: permission == .allowed ? "bell.badge.fill" : "bell.slash.fill")
                .font(.headline)
                .foregroundStyle(permission == .denied ? Color.orange : Color(hex: "1268BD"))
            if permission == .denied {
                Text("iOS 已拒绝通知。提醒不会投递，也不会显示为已开启。请在系统设置恢复后回到本页重新保存。")
                    .font(.caption)
                    .foregroundStyle(Color(hex: "5D7890"))
                    .fixedSize(horizontal: false, vertical: true)
                Button {
                    guard let url = URL(string: UIApplication.openSettingsURLString) else { return }
                    openURL(url)
                } label: {
                    Label("打开系统通知设置", systemImage: "gear")
                        .font(.subheadline.bold())
                        .frame(maxWidth: .infinity, minHeight: 44)
                }
                .buttonStyle(.bordered)
                .accessibilityIdentifier("xage.medication.reminder.openSettings")
            } else if permission == .notDetermined {
                Text("只有你主动开启并保存时才请求通知权限；保存计划本身不会弹权限框。")
                    .font(.caption)
                    .foregroundStyle(Color(hex: "5D7890"))
                    .fixedSize(horizontal: false, vertical: true)
            } else if permission == .unavailable {
                Text("当前环境无法验证真实通知投递，设置不会被冒充为已经安排。")
                    .font(.caption)
                    .foregroundStyle(Color.orange)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(16)
        .background(reminderCard)
    }

    private var reminderFields: some View {
        VStack(alignment: .leading, spacing: 14) {
            Toggle("主动开启本机提醒", isOn: $settings.enabled)
                .tint(Color(hex: "20CDB1"))
                .accessibilityIdentifier("xage.medication.reminder.enabled")

            Picker("提醒频次", selection: $settings.cadence) {
                ForEach(MedicationReminderCadence.allCases, id: \.self) { cadence in
                    Text(cadence.title).tag(cadence)
                }
            }
            .pickerStyle(.segmented)

            VStack(alignment: .leading, spacing: 5) {
                Text("提醒时点（HH:mm，可填写多个）")
                    .font(.caption.bold())
                    .foregroundStyle(Color(hex: "5D7890"))
                TextField("例如 08:00、20:00", text: $timeText)
                    .focused($timeFocused)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .padding(.horizontal, 13)
                    .padding(.vertical, 11)
                    .background(.white.opacity(0.56), in: RoundedRectangle(cornerRadius: 14))
                    .accessibilityIdentifier("xage.medication.reminder.times")
            }

            Picker("提前提醒", selection: $settings.advanceMinutes) {
                ForEach(MedicationReminderPolicy.allowedAdvanceMinutes, id: \.self) { minutes in
                    Text(minutes == 0 ? "按时提醒" : "提前 \(minutes) 分钟").tag(minutes)
                }
            }
            .pickerStyle(.menu)

            Picker("稍后提醒间隔", selection: $settings.snoozeMinutes) {
                ForEach(MedicationReminderPolicy.allowedSnoozeMinutes, id: \.self) { minutes in
                    Text("\(minutes) 分钟").tag(minutes)
                }
            }
            .pickerStyle(.menu)

            reminderDetail("服用关系", plan.meal_relation.title)
            reminderDetail("疗程结束", plan.course_end ?? "未设置；提醒会按最近排期续排")
        }
        .padding(16)
        .background(reminderCard)
    }

    private var privacyFields: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("声音与锁屏隐私")
                .font(.headline)
                .foregroundStyle(Color(hex: "123E67"))
            Toggle("通知声音", isOn: $settings.soundEnabled)
                .tint(Color(hex: "20CDB1"))
            Toggle("锁屏显示药名", isOn: $settings.showMedicationNameOnLockScreen)
                .tint(Color(hex: "20CDB1"))
            Text(settings.showMedicationNameOnLockScreen
                 ? "锁屏会显示药名；请确认设备隐私环境适合。"
                 : "默认只显示“用药提醒”，不在锁屏暴露药名。")
                .font(.caption)
                .foregroundStyle(Color(hex: "5D7890"))
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(16)
        .background(reminderCard)
    }

    private var boundaryCard: some View {
        VStack(alignment: .leading, spacing: 7) {
            Label("提醒与可信记录是两件事", systemImage: "checkmark.shield.fill")
                .font(.subheadline.bold())
                .foregroundStyle(Color(hex: "1268BD"))
            Text("通知只帮助你按计划核对；时间经过不会自动变成漏服，收到提醒也不会自动记录已服用。iOS 最多保留最近 60 次本机排期，打开小捷会按当前计划续排。")
                .font(.caption)
                .foregroundStyle(Color(hex: "5D7890"))
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(16)
        .background(reminderCard)
    }

    private var saveButton: some View {
        Button {
            timeFocused = false
            settings.times = MedicationReminderPolicy.normalizedTimes(timeText)
            settings.mealRelation = plan.meal_relation
            settings.courseEnd = plan.course_end
            settings.timezoneIdentifier = TimeZone.current.identifier
            settings.updatedAt = MedicationViewModel.isoString(Date())
            saving = true
            Task {
                let succeeded = await onSave(settings)
                await MainActor.run {
                    saving = false
                    if succeeded { dismiss() }
                }
            }
        } label: {
            HStack(spacing: 8) {
                Image(systemName: settings.enabled ? "bell.badge.fill" : "bell.slash.fill")
                Text(saving ? "保存中…" : settings.enabled ? "保存并开启提醒" : "保存并关闭提醒")
                    .font(.headline)
            }
            .foregroundStyle(.white)
            .frame(maxWidth: .infinity, minHeight: 56)
            .background(
                LinearGradient(
                    colors: [Color(hex: "22D4BF"), Color(hex: "1F8EEA")],
                    startPoint: .leading,
                    endPoint: .trailing
                ),
                in: Capsule()
            )
        }
        .buttonStyle(.plain)
        .disabled(validationIssue != nil || saving)
        .opacity(validationIssue == nil ? 1 : 0.5)
        .accessibilityIdentifier("xage.medication.reminder.save")
        .overlay(alignment: .topLeading) {
            if let validationIssue {
                Text(validationIssue)
                    .font(.caption)
                    .foregroundStyle(Color.orange)
                    .fixedSize(horizontal: false, vertical: true)
                    .offset(y: -30)
            }
        }
        .padding(.top, validationIssue == nil ? 0 : 30)
    }

    private var validationIssue: String? {
        var candidate = settings
        candidate.times = MedicationReminderPolicy.normalizedTimes(timeText)
        return MedicationReminderPolicy.validationIssue(for: candidate, plan: plan)
    }

    private var hasChanges: Bool {
        settings != initialSettings || timeText != initialTimeText
    }

    private var reminderCard: some ShapeStyle {
        Color.white.opacity(0.58)
    }

    private func reminderDetail(_ title: String, _ value: String) -> some View {
        HStack(alignment: .top, spacing: 10) {
            Text(title)
                .font(.caption.bold())
                .foregroundStyle(Color(hex: "5D7890"))
                .frame(width: 74, alignment: .leading)
            Text(value)
                .font(.caption)
                .foregroundStyle(Color(hex: "123E67"))
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 0)
        }
    }

    private func requestClose() {
        timeFocused = false
        guard !saving else { return }
        if hasChanges { showDiscard = true } else { dismiss() }
    }
}
