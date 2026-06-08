import SwiftUI

struct FamilyModeView: View {
    @StateObject private var vm = FamilyViewModel()
    @State private var showInviteSheet = false
    @State private var showAcceptSheet = false
    @State private var careMessage = ""

    var body: some View {
        ScrollView {
            VStack(spacing: 14) {
                headerCard
                actionRow
                if let invite = vm.latestInvite {
                    inviteCodeCard(invite)
                }
                subjectsSection
                summarySection
                membersSection
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 12)
        }
        .background(Color.appBackground)
        .navigationTitle("家庭模式")
        .navigationBarTitleDisplayMode(.inline)
        .task { await vm.load() }
        .refreshable { await vm.load() }
        .overlay { if vm.loading { ProgressView() } }
        .alert("提示", isPresented: Binding(
            get: { vm.message != nil },
            set: { if !$0 { vm.message = nil } }
        )) {
            Button("好", role: .cancel) {}
        } message: {
            Text(vm.message ?? "")
        }
        .alert("错误", isPresented: Binding(
            get: { vm.errorMessage != nil },
            set: { if !$0 { vm.errorMessage = nil } }
        )) {
            Button("好", role: .cancel) {}
        } message: {
            Text(vm.errorMessage ?? "")
        }
        .sheet(isPresented: $showInviteSheet) {
            FamilyInviteSheet(vm: vm)
        }
        .sheet(isPresented: $showAcceptSheet) {
            FamilyAcceptInviteSheet(vm: vm)
        }
    }

    private var headerCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Image(systemName: "person.2.fill")
                    .font(.title2)
                    .foregroundColor(.appPrimary)
                VStack(alignment: .leading, spacing: 2) {
                    Text("家庭照护协作")
                        .font(.headline)
                    Text("家人可查看你授权的摘要，不能修改你的计划。")
                        .font(.caption)
                        .foregroundColor(.appMuted)
                }
                Spacer()
            }
            HStack(spacing: 8) {
                permissionBadge("默认隐藏病史")
                permissionBadge("单独授权")
                permissionBadge("计划只读")
            }
        }
        .cardStyle()
    }

    private var actionRow: some View {
        HStack(spacing: 10) {
            Button {
                showInviteSheet = true
            } label: {
                Label("邀请家人", systemImage: "person.badge.plus")
                    .frame(maxWidth: .infinity)
            }
            .primaryGradientButtonStyle()

            Button {
                showAcceptSheet = true
            } label: {
                Label("输入邀请码", systemImage: "number.square")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.bordered)
            .tint(.appPrimary)
        }
    }

    private var subjectsSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("我关心的人")
                .font(.headline)
            if vm.subjects.isEmpty {
                Text("暂无家庭成员。可以先邀请家人，或输入家人给你的邀请码。")
                    .font(.subheadline)
                    .foregroundColor(.appMuted)
            } else {
                ForEach(vm.subjects) { subject in
                    Button {
                        Task { await vm.loadSummary(subject) }
                    } label: {
                        HStack {
                            VStack(alignment: .leading, spacing: 4) {
                                Text(subject.display_name)
                                    .font(.subheadline.weight(.semibold))
                                Text(subject.relation ?? "家庭成员")
                                    .font(.caption)
                                    .foregroundColor(.appMuted)
                            }
                            Spacer()
                            if subject.user_id == vm.selectedSubject?.user_id {
                                Image(systemName: "checkmark.circle.fill")
                                    .foregroundColor(.appPrimary)
                            } else {
                                Image(systemName: "chevron.right")
                                    .foregroundColor(.appMuted)
                            }
                        }
                        .padding(12)
                        .background(Color.appSoftFill)
                        .clipShape(RoundedRectangle(cornerRadius: 10))
                    }
                    .buttonStyle(.plain)
                }
            }
        }
        .cardStyle()
    }

    @ViewBuilder
    private var summarySection: some View {
        if let summary = vm.selectedSummary {
            VStack(alignment: .leading, spacing: 12) {
                HStack {
                    Text("\(summary.subject.display_name) 今日摘要")
                        .font(.headline)
                    Spacer()
                    Text(summary.health_status.levelLabel)
                        .font(.caption.weight(.semibold))
                        .padding(.horizontal, 8)
                        .padding(.vertical, 4)
                        .background(levelColor(summary.health_status.level).opacity(0.12))
                        .foregroundColor(levelColor(summary.health_status.level))
                        .clipShape(Capsule())
                }

                HStack(spacing: 10) {
                    metricBox("计划", "\(summary.plan.tasks_completed)/\(summary.plan.tasks_total)", "\(summary.plan.completion_pct)%")
                    metricBox("血糖数据", "\(summary.health_status.reading_count)", "条")
                    metricBox("关怀记录", "\(summary.care.today_checkins)", "次")
                }

                if let avg = summary.health_status.avg {
                    Text("已授权血糖明细：平均 \(String(format: "%.0f", avg)) mg/dL，TIR \(String(format: "%.0f", summary.health_status.tir_70_180_pct ?? 0))%。")
                        .font(.caption)
                        .foregroundColor(.appMuted)
                } else {
                    Text("血糖明细未授权，仅显示数据量与风险等级。")
                        .font(.caption)
                        .foregroundColor(.appMuted)
                }

                if !summary.alerts.isEmpty {
                    VStack(alignment: .leading, spacing: 4) {
                        ForEach(summary.alerts, id: \.self) { alert in
                            Label(alert, systemImage: "exclamationmark.circle")
                                .font(.caption)
                                .foregroundColor(.appWarning)
                        }
                    }
                }

                HStack(spacing: 8) {
                    Button {
                        Task {
                            await vm.sendCareEvent(type: "care_reminder", message: "家人提醒：记得完成今日计划")
                        }
                    } label: {
                        Label("提醒计划", systemImage: "bell")
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.bordered)
                    .tint(.appPrimary)

                    Button {
                        Task {
                            await vm.sendCareEvent(type: "care_message", message: careMessage.nilIfBlank ?? "家人关心：今天感觉怎么样？")
                        }
                    } label: {
                        Label("发送关心", systemImage: "heart")
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.bordered)
                    .tint(.appPrimary)
                }
            }
            .cardStyle()
        }
    }

    private var membersSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("授权管理")
                .font(.headline)
            if vm.members.filter({ $0.user_id != vm.currentUserId }).isEmpty {
                Text("邀请家人加入后，可以在这里逐项授权。病例、体检、多组学等敏感数据默认不共享。")
                    .font(.subheadline)
                    .foregroundColor(.appMuted)
            } else {
                ForEach(vm.members.filter { $0.user_id != vm.currentUserId }) { member in
                    FamilyMemberPermissionCard(member: member, vm: vm)
                }
            }
        }
        .cardStyle()
    }

    private func permissionBadge(_ text: String) -> some View {
        Text(text)
            .font(.caption.weight(.medium))
            .padding(.horizontal, 8)
            .padding(.vertical, 5)
            .background(Color.appPrimary.opacity(0.08))
            .foregroundColor(.appPrimary)
            .clipShape(Capsule())
    }

    private func inviteCodeCard(_ invite: FamilyInvite) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("最新邀请码")
                .font(.headline)
            HStack {
                Text(invite.invite_code)
                    .font(.system(size: 28, weight: .bold, design: .monospaced))
                Spacer()
                Text("7 天内有效")
                    .font(.caption)
                    .foregroundColor(.appMuted)
            }
            Text("家人在自己的账号里输入该邀请码即可加入。加入后仍需你单独授权敏感数据。")
                .font(.caption)
                .foregroundColor(.appMuted)
        }
        .cardStyle()
    }

    private func metricBox(_ title: String, _ value: String, _ sub: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title).font(.caption).foregroundColor(.appMuted)
            HStack(alignment: .lastTextBaseline, spacing: 2) {
                Text(value).font(.headline)
                Text(sub).font(.caption).foregroundColor(.appMuted)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(10)
        .background(Color.appSoftFill)
        .clipShape(RoundedRectangle(cornerRadius: 10))
    }

    private func levelColor(_ level: String) -> Color {
        switch level {
        case "stable": return .appPrimary
        case "risk": return .red
        case "watch": return .appWarning
        default: return .appMuted
        }
    }
}

private struct FamilyMemberPermissionCard: View {
    let member: FamilyMember
    @ObservedObject var vm: FamilyViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                VStack(alignment: .leading, spacing: 3) {
                    Text(member.bestName)
                        .font(.subheadline.weight(.semibold))
                    Text(member.relation ?? member.role)
                        .font(.caption)
                        .foregroundColor(.appMuted)
                }
                Spacer()
            }

            ForEach(FamilyPermissionField.allCases) { field in
                Toggle(isOn: Binding(
                    get: { vm.value(for: member.user_id, field: field) },
                    set: { value in
                        Task { await vm.togglePermission(viewerUserId: member.user_id, field: field, value: value) }
                    }
                )) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(field.title)
                            .font(.subheadline)
                        Text(field.subtitle)
                            .font(.caption2)
                            .foregroundColor(.appMuted)
                    }
                }
                .tint(.appPrimary)
            }
        }
        .padding(12)
        .background(Color.appSoftFill)
        .clipShape(RoundedRectangle(cornerRadius: 10))
    }
}

private struct FamilyInviteSheet: View {
    @Environment(\.dismiss) private var dismiss
    @ObservedObject var vm: FamilyViewModel
    @State private var phone = ""
    @State private var relation = ""

    var body: some View {
        NavigationView {
            Form {
                Section("邀请信息") {
                    TextField("对方手机号（可选）", text: $phone)
                        .keyboardType(.phonePad)
                    TextField("关系，如 父亲/母亲/配偶", text: $relation)
                }
                Section {
                    Text("邀请码只用于加入家庭。加入后，对方仍不能查看病史、体检、多组学、用药等敏感信息，除非你在授权管理中单独打开。")
                        .font(.caption)
                        .foregroundColor(.appMuted)
                }
            }
            .navigationTitle("邀请家人")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("取消") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("生成") {
                        Task {
                            await vm.createInvite(targetPhone: phone, relation: relation)
                            dismiss()
                        }
                    }
                }
            }
        }
    }
}

private struct FamilyAcceptInviteSheet: View {
    @Environment(\.dismiss) private var dismiss
    @ObservedObject var vm: FamilyViewModel
    @State private var code = ""
    @State private var displayName = ""

    var body: some View {
        NavigationView {
            Form {
                Section("邀请码") {
                    TextField("输入 8 位邀请码", text: $code)
                        .textInputAutocapitalization(.characters)
                        .autocorrectionDisabled()
                    TextField("我在对方家庭中的显示名（可选）", text: $displayName)
                }
                Section {
                    Text("加入家庭后，你可以关心多个家人。默认只能查看对方授权后的摘要，不能修改对方计划。")
                        .font(.caption)
                        .foregroundColor(.appMuted)
                }
            }
            .navigationTitle("加入家庭")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("取消") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("加入") {
                        Task {
                            await vm.acceptInvite(code: code, displayName: displayName)
                            dismiss()
                        }
                    }
                    .disabled(code.trimmingCharacters(in: .whitespacesAndNewlines).count < 4)
                }
            }
        }
    }
}

private extension String {
    var nilIfBlank: String? {
        let value = trimmingCharacters(in: .whitespacesAndNewlines)
        return value.isEmpty ? nil : value
    }
}
