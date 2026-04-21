import SwiftUI

/// 设置页面 — 对应小程序 pages/settings/settings
struct SettingsView: View {
    @EnvironmentObject var authManager: AuthManager
    @StateObject private var vm = SettingsViewModel()
    @ObservedObject private var units = UnitsSettings.shared
    @ObservedObject private var demo = DemoSettings.shared

    var body: some View {
        ScrollView {
            VStack(spacing: 12) {
                // 用户信息
                accountCard

                // 干预级别
                interventionCard

                // 血糖单位
                glucoseUnitCard

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
                .padding(.top, 12)
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
    }

    // MARK: - 账户信息

    private var accountCard: some View {
        VStack(alignment: .leading, spacing: 8) {
            Label("账户信息", systemImage: "person").font(.headline)
            infoRow(label: "邮箱", value: vm.user?.email ?? "--")
            infoRow(label: "注册时间", value: vm.user?.created_at ?? "--")
        }
        .cardStyle()
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


