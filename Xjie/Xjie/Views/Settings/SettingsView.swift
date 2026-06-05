import SwiftUI

/// 设置页面 — 对应小程序 pages/settings/settings
struct SettingsView: View {
    @EnvironmentObject var authManager: AuthManager
    @StateObject private var vm = SettingsViewModel()
    @ObservedObject private var units = UnitsSettings.shared
    @ObservedObject private var demo = DemoSettings.shared
    @State private var showChangePwd = false
    @State private var showProfileEdit = false
    @State private var showFeedback = false
    @State private var showFeedbackSuccess = false

    var body: some View {
        ScrollView {
            VStack(spacing: 12) {
                // 用户信息
                accountCard

                // 意见反馈
                feedbackEntryCard

                // 干预级别
                interventionCard

                // 血糖单位
                glucoseUnitCard

                // 我的用药
                medicationsEntryCard

                // 关怀模式
                elderlyModeCard

                // 演示模式
                demoModeCard

                // 隐私同意
                consentCard

                // 管理后台（仅管理员可见）
                if vm.user?.is_admin == true {
                    NavigationLink {
                        AdminView()
                    } label: {
                        HStack {
                            Image(systemName: "shield.checkered")
                                .foregroundColor(.appWarning)
                            Text("管理后台")
                                .font(.headline)
                            Spacer()
                            Image(systemName: "chevron.right")
                                .foregroundColor(.appMuted)
                        }
                        .foregroundColor(.appText)
                    }
                    .cardStyle()
                }

                // 修改密码
                Button { showChangePwd = true } label: {
                    HStack {
                        Image(systemName: "lock.rotation")
                        Text("修改密码")
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 14)
                    .background(
                        RoundedRectangle(cornerRadius: 8)
                            .stroke(Color.appPrimary.opacity(0.6), lineWidth: 1)
                    )
                    .foregroundColor(.appPrimary)
                }
                .padding(.top, 12)

                // 退出登录
                Button { vm.showLogoutAlert = true } label: {
                    Text("退出登录")
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 14)
                        .background(
                            RoundedRectangle(cornerRadius: 8)
                                .stroke(Color.appPrimary, lineWidth: 1)
                        )
                        .foregroundColor(.appPrimary)
                }
            }
            .padding(.horizontal, 16)
            .padding(.top, 8)
        }
        .background(Color.appBackground)
        .navigationTitle("设置")
        .navigationBarTitleDisplayMode(.inline)
        .task { await vm.fetchData() }
        .overlay { if vm.loading { ProgressView() } }
        .alert("确认退出", isPresented: $vm.showLogoutAlert) {
            Button("退出", role: .destructive) {
                Task {
                    try? await APIService.shared.postVoid("/api/auth/logout")
                    authManager.logout()
                }
            }
            Button("取消", role: .cancel) {}
        } message: {
            Text("确定要退出登录吗？")
        }
        .alert("错误", isPresented: Binding(
            get: { vm.errorMessage != nil },
            set: { if !$0 { vm.errorMessage = nil } }
        )) {
            Button("好", role: .cancel) {}
        } message: {
            Text(vm.errorMessage ?? "")
        }
        .alert("已提交", isPresented: $showFeedbackSuccess) {
            Button("好", role: .cancel) {}
        } message: {
            Text("感谢反馈，开发者可在运维 Dashboard 中查看。")
        }
        .sheet(isPresented: $showChangePwd) {
            ChangePasswordSheet()
        }
        .sheet(isPresented: $showProfileEdit) {
            ProfileEditSheet(vm: vm)
        }
        .sheet(isPresented: $showFeedback) {
            FeedbackSheet(vm: vm) {
                showFeedbackSuccess = true
            }
        }
    }

    // MARK: - 账户信息

    private var accountCard: some View {
        Button { showProfileEdit = true } label: {
            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    Label("账户信息", systemImage: "person").font(.headline)
                    Spacer()
                    Image(systemName: "chevron.right").foregroundColor(.appMuted)
                }
                infoRow(label: "手机号", value: vm.user?.phone ?? vm.user?.email ?? "--")
                infoRow(label: "用户名", value: vm.user?.username ?? "--")
                infoRow(label: "昵称", value: vm.user?.profile?.display_name ?? "--")
                infoRow(label: "性别", value: sexLabel(vm.user?.profile?.sex))
                infoRow(label: "年龄", value: vm.user?.profile?.age.map { "\($0) 岁" } ?? "--")
                infoRow(label: "身高", value: vm.user?.profile?.height_cm.map { "\(Int($0)) cm" } ?? "--")
                infoRow(label: "体重", value: vm.user?.profile?.weight_kg.map { "\(Int($0)) kg" } ?? "--")
                infoRow(label: "注册时间", value: vm.user?.created_at ?? "--")
                Text("点击在线修改个人资料")
                    .font(.caption)
                    .foregroundColor(.appPrimary)
                    .padding(.top, 4)
            }
        }
        .buttonStyle(.plain)
        .cardStyle()
    }

    private func sexLabel(_ raw: String?) -> String {
        switch raw?.lowercased() {
        case "female", "f", "女": return "女"
        case "male", "m", "男": return "男"
        case nil, "": return "--"
        default: return "其他"
        }
    }

    // MARK: - 干预级别

    private var interventionCard: some View {
        VStack(alignment: .leading, spacing: 8) {
            Label("干预级别", systemImage: "bolt").font(.headline)

            ForEach(["L1", "L2", "L3"], id: \.self) { level in
                let labels = ["L1": "温和", "L2": "标准", "L3": "积极"]
                let descs = [
                    "L1": "仅在高风险时提醒，每天最多 1 条",
                    "L2": "中等风险时提醒，每天最多 2 条（默认）",
                    "L3": "主动提醒，每天最多 4 条",
                ]
                let isActive = vm.settings?.intervention_level == level

                Button {
                    Task { await vm.updateLevel(level) }
                } label: {
                    VStack(alignment: .leading, spacing: 4) {
                        HStack {
                            Text(level).font(.subheadline).bold()
                            Text(labels[level] ?? "").font(.caption).foregroundColor(.appMuted)
                            Spacer()
                            if isActive {
                                Image(systemName: "checkmark.circle.fill")
                                    .foregroundColor(.appPrimary)
                            }
                        }
                        Text(descs[level] ?? "")
                            .font(.caption)
                            .foregroundColor(.appMuted)
                    }
                    .padding(12)
                    .background(
                        RoundedRectangle(cornerRadius: 8)
                            .stroke(isActive ? Color.appPrimary : Color.gray.opacity(0.2), lineWidth: isActive ? 2 : 1)
                    )
                    .background(isActive ? Color.appPrimary.opacity(0.05) : Color.clear)
                    .cornerRadius(8)
                }
                .foregroundColor(.appText)
            }
        }
        .cardStyle()
    }

    // MARK: - 隐私同意

    private var consentCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            Label("隐私与同意", systemImage: "lock.shield").font(.headline)

            Toggle("允许 AI 聊天", isOn: Binding(
                get: { vm.user?.consent?.allow_ai_chat ?? false },
                set: { _ in Task { await vm.toggleAiChat() } }
            ))
            .tint(.appPrimary)

            Toggle("允许数据上传", isOn: Binding(
                get: { vm.user?.consent?.allow_data_upload ?? false },
                set: { _ in Task { await vm.toggleDataUpload() } }
            ))
            .tint(.appPrimary)
        }
        .cardStyle()
    }

    // MARK: - 意见反馈

    private var feedbackEntryCard: some View {
        Button { showFeedback = true } label: {
            HStack(spacing: 12) {
                Image(systemName: "bubble.left.and.text.bubble.right.fill")
                    .font(.system(size: 20))
                    .foregroundColor(.appPrimary)
                VStack(alignment: .leading, spacing: 4) {
                    Text("意见反馈").font(.headline)
                    Text("提交问题、建议或异常现象，开发者会在 Dashboard 中查看。")
                        .font(.caption)
                        .foregroundColor(.appMuted)
                        .multilineTextAlignment(.leading)
                }
                Spacer()
                Image(systemName: "chevron.right").foregroundColor(.appMuted)
            }
            .foregroundColor(.appText)
        }
        .cardStyle()
    }

    private func infoRow(label: String, value: String) -> some View {
        HStack {
            Text(label).font(.subheadline).foregroundColor(.appMuted)
            Spacer()
            Text(value).font(.subheadline)
        }
    }

    // MARK: - 血糖单位

    private var glucoseUnitCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            Label("血糖单位", systemImage: "drop").font(.headline)
            Text("中国临床惯用 mmol/L，欧美多用 mg/dL。1 mmol/L = 18.018 mg/dL。")
                .font(.caption).foregroundColor(.appMuted)
            Picker("单位", selection: Binding(
                get: { units.glucoseUnit },
                set: { newValue in
                    Task { await vm.updateGlucoseUnit(newValue) }
                }
            )) {
                Text("mmol/L").tag(GlucoseUnit.mmol)
                Text("mg/dL").tag(GlucoseUnit.mgdl)
            }
            .pickerStyle(.segmented)
        }
        .cardStyle()
    }

    // MARK: - 我的用药

    private var medicationsEntryCard: some View {
        NavigationLink {
            MedicationListView()
        } label: {
            HStack(spacing: 12) {
                Image(systemName: "pills.fill")
                    .font(.system(size: 20))
                    .foregroundColor(.appPrimary)
                VStack(alignment: .leading, spacing: 4) {
                    Text("我的用药").font(.headline)
                    Text("拍照识别 / 手动添加，按疗程和服药时间定时提醒")
                        .font(.caption).foregroundColor(.appMuted)
                        .multilineTextAlignment(.leading)
                }
                Spacer()
                Image(systemName: "chevron.right").foregroundColor(.appMuted)
            }
            .foregroundColor(.appText)
        }
        .cardStyle()
    }

    // MARK: - 关怀模式

    private var elderlyModeCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            Label("关怀模式", systemImage: "heart.text.square").font(.headline)
            Text("开启后，首页会出现大字体“关怀签到”卡片。App 会按设定间隔主动询问您的活动、身体感觉与心情，并保存为历史记录。")
                .font(.caption).foregroundColor(.appMuted)
            Toggle("启用关怀模式", isOn: Binding(
                get: { vm.settings?.elderly_mode ?? false },
                set: { newValue in Task { await vm.updateElderlyMode(enabled: newValue) } }
            )).tint(.appPrimary)

            if (vm.settings?.elderly_mode ?? false) {
                HStack {
                    Text("提醒间隔").font(.subheadline)
                    Spacer()
                    Picker("间隔", selection: Binding(
                        get: { vm.settings?.elderly_checkin_interval_min ?? 180 },
                        set: { v in Task { await vm.updateElderlyInterval(v) } }
                    )) {
                        Text("1小时").tag(60)
                        Text("2小时").tag(120)
                        Text("3小时").tag(180)
                        Text("4小时").tag(240)
                        Text("6小时").tag(360)
                    }
                    .pickerStyle(.menu)
                }
                NavigationLink {
                    ElderlyHistoryView()
                } label: {
                    HStack {
                        Image(systemName: "clock.arrow.circlepath")
                        Text("查看关怀记录")
                        Spacer()
                        Image(systemName: "chevron.right").foregroundColor(.appMuted)
                    }
                    .padding(.vertical, 6)
                    .foregroundColor(.appText)
                }
            }
        }
        .cardStyle()
    }

    // MARK: - 演示模式

    private var demoModeCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            Label("多组学演示模式", systemImage: "sparkles").font(.headline)
            Text("在尚无真实组学数据时，用合成的示例数据展示代谢指纹、蛋白炎症、基因风险与菌群画像。关闭后将仅在上传真实数据后显示结果。")
                .font(.caption).foregroundColor(.appMuted)
            Toggle("启用演示模式", isOn: Binding(
                get: { demo.omicsDemoEnabled },
                set: { demo.omicsDemoEnabled = $0 }
            ))
            .tint(.appPrimary)
        }
        .cardStyle()
    }
}

private struct FeedbackSheet: View {
    @Environment(\.dismiss) private var dismiss
    @ObservedObject var vm: SettingsViewModel
    let onSubmitted: () -> Void

    @State private var category = "general"
    @State private var content = ""
    @State private var contact = ""
    @State private var submitting = false

    private let categories = [
        ("general", "建议"),
        ("bug", "问题"),
        ("data", "数据异常"),
        ("ui", "界面体验"),
    ]

    private var trimmedContent: String {
        content.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private var canSubmit: Bool {
        trimmedContent.count >= 2 && trimmedContent.count <= 2000 && !submitting
    }

    var body: some View {
        NavigationView {
            Form {
                Section("反馈类型") {
                    Picker("类型", selection: $category) {
                        ForEach(categories, id: \.0) { item in
                            Text(item.1).tag(item.0)
                        }
                    }
                    .pickerStyle(.segmented)
                }

                Section("反馈内容") {
                    TextEditor(text: $content)
                        .frame(minHeight: 150)
                    Text("\(trimmedContent.count)/2000")
                        .font(.caption)
                        .foregroundColor(trimmedContent.count > 2000 ? .red : .appMuted)
                }

                Section("联系方式（可选）") {
                    TextField("手机号、邮箱或微信", text: $contact)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                }
            }
            .navigationTitle("意见反馈")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("取消") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button {
                        submit()
                    } label: {
                        if submitting {
                            ProgressView()
                        } else {
                            Text("提交")
                        }
                    }
                    .disabled(!canSubmit)
                }
            }
        }
    }

    private func submit() {
        guard canSubmit else { return }
        submitting = true
        Task {
            let ok = await vm.submitFeedback(
                category: category,
                content: trimmedContent,
                contact: contact.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? nil : contact.trimmingCharacters(in: .whitespacesAndNewlines)
            )
            submitting = false
            if ok {
                dismiss()
                onSubmitted()
            }
        }
    }
}
