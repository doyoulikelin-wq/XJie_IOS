import AVFoundation
import Speech
import SwiftUI
import UIKit

struct XAgeMoreMenu: View {
    @Binding var selectedCategory: XAgeDataPanelCategory
    @ObservedObject var appleHealthSync: AppleHealthSyncViewModel
    let snapshot: XAgeServerSyncSnapshot
    let onSyncAppleHealth: () async -> Void
    let onSelectCategory: (XAgeDataPanelCategory) -> Void
    let onClose: () -> Void
    @EnvironmentObject private var authManager: AuthManager
    @StateObject private var accountVM = XAgeAccountViewModel()
    @StateObject private var settingsVM = SettingsViewModel()
    @State private var showFamilyMode = false
    @State private var showPersonalInfo = false
    @State private var showAccountSecurity = false
    @State private var supportDestination: XAgeSupportDestination?
    @State private var presentedMoreDestination: XAgeMoreDestination?

    var body: some View {
        ZStack {
            XAgeLiquidBackground()
                .ignoresSafeArea()

            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    HStack {
                        Text("更多")
                            .font(.system(size: 28, weight: .bold))
                            .foregroundStyle(Color(hex: "123E67"))
                        Spacer()
                        Button {
                            onClose()
                        } label: {
                            Image(systemName: "xmark")
                                .font(.system(size: 13, weight: .bold))
                                .foregroundStyle(Color(hex: "1268BD"))
                                .frame(width: 34, height: 34)
                                .background(XAgeCapsuleFill())
                        }
                        .frame(width: 44, height: 44)
                        .contentShape(Rectangle())
                        .buttonStyle(.plain)
                        .accessibilityLabel("关闭")
                    }

                    VStack(alignment: .leading, spacing: 10) {
                        Text("资料与设备")
                            .font(.system(size: 13, weight: .bold))
                            .foregroundStyle(Color(hex: "5D7890"))
                            .padding(.horizontal, 4)
                        ForEach(XAgeDataPanelCategory.moreProfileCategories) { category in
                            XAgeAccountMenuRow(
                                icon: category.iconName,
                                title: category.rawValue,
                                subtitle: category.headline,
                                selected: selectedCategory == category,
                                identifier: "xage.more.category.\(category.id)"
                            ) {
                                selectedCategory = category
                                onSelectCategory(category)
                                presentedMoreDestination = .profile
                            }
                        }
                        XAgeAccountMenuRow(
                            icon: "sensor.tag.radiowaves.forward.fill",
                            title: "设备管理",
                            subtitle: XAgeDeviceManagementContract.unsupportedTitle,
                            identifier: "xage.more.deviceManagement"
                        ) {
                            presentedMoreDestination = .device
                        }
                    }
                    .padding(14)
                    .background(XAgeGlassCardBackground(cornerRadius: 28))

                    VStack(alignment: .leading, spacing: 10) {
                        Text("账号管理")
                            .font(.system(size: 13, weight: .bold))
                            .foregroundStyle(Color(hex: "5D7890"))
                            .padding(.horizontal, 4)

                        XAgeAccountMenuRow(
                            icon: "person.text.rectangle.fill",
                            title: "个人信息与权限",
                            subtitle: "资料完整度、健康权限和隐私授权"
                        ) {
                            showPersonalInfo = true
                        }
                        XAgeAccountMenuRow(
                            icon: "lock.shield.fill",
                            title: "账号与安全",
                            subtitle: "查看手机号、修改密码或注销账号",
                            identifier: "xage.account.security"
                        ) {
                            showAccountSecurity = true
                        }
                        XAgeAccountMenuRow(
                            icon: "person.2.fill",
                            title: "关联用户",
                            subtitle: "家庭模式、邀请和授权"
                        ) {
                            showFamilyMode = true
                        }
                    }
                    .padding(14)
                    .background(XAgeGlassCardBackground(cornerRadius: 28))

                    VStack(alignment: .leading, spacing: 10) {
                        Text("帮助与关于")
                            .font(.system(size: 13, weight: .bold))
                            .foregroundStyle(Color(hex: "5D7890"))
                            .padding(.horizontal, 4)

                        XAgeAccountMenuRow(
                            icon: "questionmark.circle.fill",
                            title: "使用帮助",
                            subtitle: "查看报告、指标和同步操作",
                            identifier: "xage.support.help"
                        ) {
                            supportDestination = .help
                        }
                        XAgeAccountMenuRow(
                            icon: "info.circle.fill",
                            title: "版本信息",
                            subtitle: "查看当前版本与备案信息",
                            identifier: "xage.support.version"
                        ) {
                            supportDestination = .version
                        }
                        XAgeAccountMenuRow(
                            icon: "hand.raised.fill",
                            title: "隐私政策",
                            subtitle: "了解数据处理和你的权利",
                            identifier: "xage.support.privacy"
                        ) {
                            supportDestination = .privacy
                        }
                        XAgeAccountMenuRow(
                            icon: "list.bullet.rectangle.fill",
                            title: "权限申请与使用情况说明",
                            subtitle: "查看系统权限的申请时机与用途",
                            identifier: "xage.support.permissions"
                        ) {
                            supportDestination = .permissions
                        }
                        XAgeAccountMenuRow(
                            icon: "bubble.left.and.text.bubble.right.fill",
                            title: "意见反馈",
                            subtitle: "提交问题、建议或数据异常",
                            identifier: "xage.support.feedback"
                        ) {
                            supportDestination = .feedback
                        }
                    }
                    .padding(14)
                    .background(XAgeGlassCardBackground(cornerRadius: 28))

                    Text("备案号：皖ICP备2026008853号-2")
                        .font(.system(size: 11, weight: .medium))
                        .foregroundStyle(Color(hex: "7D9AB1"))
                        .frame(maxWidth: .infinity)
                        .padding(.top, 2)
                }
                .padding(24)
            }
            .scrollIndicators(.hidden)
        }
        .fullScreenCover(isPresented: $showFamilyMode) {
            XAgeFamilyModeSheet()
        }
        .fullScreenCover(isPresented: $showPersonalInfo) {
            XAgePersonalInfoPermissionSheet(
                snapshot: snapshot,
                appleHealthSync: appleHealthSync,
                onSyncAppleHealth: onSyncAppleHealth
            )
        }
        .fullScreenCover(isPresented: $showAccountSecurity) {
            XAgeAccountSecurityView(
                phone: settingsVM.user?.phone,
                isLoading: settingsVM.loading,
                isDeleting: accountVM.isWorking,
                onClose: { showAccountSecurity = false },
                onLogout: {
                    let accountToken = authManager.token
                    showAccountSecurity = false
                    onClose()
                    authManager.logout(ifCurrentToken: accountToken)
                    Task {
                        await accountVM.revokeLogoutToken(accountToken)
                    }
                },
                onDeleteAccount: {
                    let accountToken = authManager.token
                    guard await accountVM.deleteAccountOnServer() else { return false }
                    onClose()
                    authManager.logout(ifCurrentToken: accountToken)
                    return true
                }
            )
            .task {
                if settingsVM.user == nil {
                    await settingsVM.fetchData()
                }
            }
        }
        .xAgeSupportPresentation(destination: $supportDestination, settingsVM: settingsVM)
        .fullScreenCover(item: $presentedMoreDestination) { destination in
            if destination == .device {
                XAgeDeviceManagementView(onClose: { presentedMoreDestination = nil })
            } else {
                XAgePanelDestinationView(
                    category: .profile,
                    appleHealthSync: appleHealthSync,
                    snapshot: snapshot,
                    onSyncAppleHealth: onSyncAppleHealth,
                    onClose: { presentedMoreDestination = nil }
                )
            }
        }
        .alert("账号操作失败", isPresented: Binding(
            get: { accountVM.errorMessage != nil },
            set: { if !$0 { accountVM.errorMessage = nil } }
        )) {
            Button("知道了", role: .cancel) {}
        } message: {
            Text(accountVM.errorMessage ?? "")
        }
    }

}

private struct XAgeAccountSecurityView: View {
    let phone: String?
    let isLoading: Bool
    let isDeleting: Bool
    let onClose: () -> Void
    let onLogout: () -> Void
    let onDeleteAccount: () async -> Bool
    @State private var showChangePassword = false
    @State private var showDeleteConfirm = false
    @State private var showLogoutConfirm = false

    var body: some View {
        XAgeSettingsInfoSheetScaffold(
            title: "账号与安全",
            subtitle: "管理当前登录账号的安全设置",
            icon: "lock.shield.fill",
            onClose: onClose
        ) {
            XAgeAccountSecurityRow(
                icon: "phone.fill",
                title: "当前手机号",
                value: isLoading ? "正在获取…" : Utils.maskedPhone(phone),
                identifier: "xage.account.security.phone"
            )
            XAgeAccountSecurityRow(
                icon: "key.fill",
                title: "修改密码",
                subtitle: "验证旧密码并设置新密码",
                identifier: "xage.account.security.password"
            ) {
                showChangePassword = true
            }
            XAgeAccountSecurityRow(
                icon: "rectangle.portrait.and.arrow.right",
                title: "退出登录",
                subtitle: "切换账号或重新登录",
                identifier: "xage.account.退出登录"
            ) {
                showLogoutConfirm = true
            }
            XAgeAccountSecurityRow(
                icon: "person.crop.circle.badge.xmark",
                title: "注销账号",
                subtitle: "永久停用当前账号，此操作不可逆",
                destructive: true,
                identifier: "xage.account.注销账号"
            ) {
                showDeleteConfirm = true
            }
        }
        .sheet(isPresented: $showChangePassword) {
            ChangePasswordSheet()
        }
        .sheet(isPresented: $showDeleteConfirm) {
            XAgeDeleteAccountSheet(
                isWorking: isDeleting,
                onCancel: { showDeleteConfirm = false },
                onConfirm: {
                    Task {
                        if await onDeleteAccount() {
                            showDeleteConfirm = false
                        }
                    }
                }
            )
            .presentationDetents([.medium, .large])
            .interactiveDismissDisabled(isDeleting)
        }
        .alert("确认退出", isPresented: $showLogoutConfirm) {
            Button("取消", role: .cancel) {}
            Button("退出", role: .destructive, action: onLogout)
        } message: {
            Text("退出后会回到登录页，可使用其他账号登录。")
        }
    }
}

private struct XAgeAccountSecurityRow: View {
    let icon: String
    let title: String
    var subtitle: String? = nil
    var value: String? = nil
    var destructive = false
    let identifier: String
    var action: (() -> Void)? = nil

    var body: some View {
        Group {
            if let action {
                Button(action: action) { content }
                    .buttonStyle(.plain)
            } else {
                content
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel([title, value ?? subtitle].compactMap { $0 }.joined(separator: "，"))
        .accessibilityAddTraits(action == nil ? .isStaticText : .isButton)
        .accessibilityIdentifier(identifier)
    }

    private var content: some View {
        HStack(spacing: 12) {
            Image(systemName: icon)
                .font(.system(size: 17, weight: .bold))
                .foregroundStyle(destructive ? Color(hex: "D85A66") : Color(hex: "237FC4"))
                .frame(width: 40, height: 40)
                .background(Circle().fill(.white.opacity(0.62)))
            VStack(alignment: .leading, spacing: 4) {
                Text(title)
                    .font(.system(size: 16, weight: .bold))
                    .foregroundStyle(destructive ? Color(hex: "B84350") : Color(hex: "173F64"))
                if let subtitle {
                    Text(subtitle)
                        .font(.system(size: 12, weight: .medium))
                        .foregroundStyle(Color(hex: "6C8194"))
                }
            }
            Spacer()
            if let value {
                Text(value)
                    .font(.system(size: 15, weight: .semibold, design: .monospaced))
                    .foregroundStyle(Color(hex: "365F80"))
            } else {
                Image(systemName: "chevron.right")
                    .font(.system(size: 13, weight: .bold))
                    .foregroundStyle(Color(hex: "7D9AB1"))
            }
        }
        .padding(.horizontal, 14)
        .frame(minHeight: 66)
        .background(XAgeGlassCardBackground(cornerRadius: 22))
    }
}

private struct XAgeMoreDestination: Identifiable, Equatable {
    let id: String
    static let profile = Self(id: "profile"), device = Self(id: XAgeDeviceManagementContract.destinationID)
}

private struct XAgeDeviceManagementView: View {
    let onClose: () -> Void
    @State private var state = XAgeDevicePageState.loading

    var body: some View {
        XAgeSettingsInfoSheetScaffold(
            title: "设备管理",
            subtitle: "管理与当前账号关联的健康硬件",
            icon: "sensor.tag.radiowaves.forward.fill",
            onClose: onClose
        ) {
            Group {
                switch state {
                case .loading:
                    HStack(spacing: 10) {
                        ProgressView()
                        Text("正在检查设备支持状态")
                    }
                    .accessibilityIdentifier("xage.device.loading")
                case .empty:
                    Label("暂无已绑定设备", systemImage: "sensor.tag.radiowaves.forward")
                        .accessibilityIdentifier("xage.device.empty")
                case .unsupported:
                    VStack(alignment: .leading, spacing: 14) {
                        Label(XAgeDeviceManagementContract.unsupportedTitle, systemImage: "lock.shield.fill")
                            .font(.title3.bold()).foregroundStyle(Color(hex: "173F64"))
                        Text("蓝牙与 NFC 绑定将在首批型号、协议、鉴权和凭证撤销规则完成后开放。")
                        Text("序列号、电量和保修信息只会展示厂商权威来源；当前不会生成占位设备。")
                        Text("当前没有可执行的添加、查看或解绑操作。")
                    }
                    .accessibilityIdentifier("xage.device.unsupported")
                }
            }
            .font(.body).foregroundStyle(Color(hex: "496A83"))
            .lineSpacing(3).fixedSize(horizontal: false, vertical: true)
        }
        .task {
            await Task.yield()
            state = XAgeDeviceManagementContract.state(isLoading: false)
        }
    }
}

@MainActor
final class XAgeAccountViewModel: ObservableObject {
    @Published var isWorking = false
    @Published var errorMessage: String?

    private let api: APIServiceProtocol

    init(api: APIServiceProtocol = APIService.shared) {
        self.api = api
    }

    func logout(authManager: AuthManager) async {
        let accountToken = authManager.token
        isWorking = true
        defer { isWorking = false }
        do {
            try await api.postVoid("/api/auth/logout")
        } catch {
            // 退出登录必须允许本地完成，避免网络错误把用户锁在当前账号。
        }
        authManager.logout(ifCurrentToken: accountToken)
    }

    func revokeLogoutToken(_ token: String) async {
        guard !token.isEmpty,
              let url = URL(string: AppEnvironment.apiBaseURL + "/api/auth/logout")
        else { return }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.timeoutInterval = 4
        _ = try? await APIService.shared.trustedSession.data(for: request)
    }

    func deleteAccount(authManager: AuthManager) async {
        let accountToken = authManager.token
        if await deleteAccountOnServer() {
            authManager.logout(ifCurrentToken: accountToken)
        }
    }

    func deleteAccountOnServer() async -> Bool {
        isWorking = true
        defer { isWorking = false }
        do {
            try await api.deleteVoid("/api/users/me")
            return true
        } catch {
            errorMessage = error.localizedDescription
            return false
        }
    }
}

private struct XAgeAccountMenuRow: View {
    let icon: String
    let title: String
    let subtitle: String
    var lowEmphasis = false
    var selected = false
    var identifier: String? = nil
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 12) {
                Image(systemName: icon)
                    .font(.system(size: 16, weight: .bold))
                    .foregroundStyle(lowEmphasis ? Color(hex: "72879A") : Color(hex: "237FC4"))
                    .frame(width: 38, height: 38)
                    .background(Circle().fill(.white.opacity(0.6)).overlay(Circle().stroke(.white.opacity(0.78), lineWidth: 1)))

                VStack(alignment: .leading, spacing: 3) {
                    Text(title)
                        .font(.system(size: 16, weight: .bold))
                        .foregroundStyle(lowEmphasis ? Color(hex: "5D7890") : Color(hex: "173F64"))
                    Text(subtitle)
                        .font(.system(size: 12, weight: .medium))
                        .foregroundStyle(Color(hex: "6C8194"))
                        .lineLimit(1)
                }

                Spacer()
                Image(systemName: "chevron.right")
                    .font(.system(size: 13, weight: .bold))
                    .foregroundStyle(Color(hex: "7D9AB1"))
            }
            .padding(.horizontal, 14)
            .frame(height: 62)
            .background(XAgeGlassCardBackground(cornerRadius: 22))
            .overlay(
                RoundedRectangle(cornerRadius: 22, style: .continuous)
                    .stroke(Color(hex: "238AD6").opacity(selected ? 0.58 : 0), lineWidth: selected ? 1.5 : 0)
            )
        }
        .buttonStyle(.plain)
        .accessibilityElement(children: .ignore)
        .accessibilityAddTraits(.isButton)
        .accessibilityLabel("\(title)、\(subtitle)")
        .accessibilityValue(selected ? "当前资料分类" : "")
        .xAgeAccessibilitySelected(selected)
        .accessibilityIdentifier(identifier ?? "xage.account.\(title)")
    }
}

private struct XAgeDeleteAccountSheet: View {
    let isWorking: Bool
    let onCancel: () -> Void
    let onConfirm: () -> Void
    @State private var confirmText = ""
    @FocusState private var confirmFocused: Bool

    private var canConfirm: Bool {
        confirmText.trimmingCharacters(in: .whitespacesAndNewlines) == "注销"
    }

    var body: some View {
        ZStack {
            XAgeLiquidBackground()
                .ignoresSafeArea()

            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                HStack(spacing: 12) {
                    Image(systemName: "person.crop.circle.badge.xmark")
                        .font(.system(size: 24, weight: .bold))
                        .foregroundStyle(Color(hex: "D85A66"))
                        .frame(width: 52, height: 52)
                        .background(XAgeCapsuleFill())
                    VStack(alignment: .leading, spacing: 4) {
                        Text("注销账号")
                            .font(.system(size: 24, weight: .bold))
                            .foregroundStyle(Color(hex: "123E67"))
                        Text("账号停用后会立即退出登录")
                            .font(.system(size: 13, weight: .medium))
                            .foregroundStyle(Color(hex: "5D7890"))
                    }
                }

                Text("系统会停用当前账号并清除本机登录态。为避免误触，请输入“注销”后再确认。")
                    .font(.system(size: 13))
                    .foregroundStyle(Color(hex: "496A83"))
                    .lineSpacing(3)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(14)
                    .background(XAgeCapsuleFill())

                TextField("输入：注销", text: $confirmText)
                    .font(.system(size: 16, weight: .bold))
                    .textInputAutocapitalization(.never)
                    .disableAutocorrection(true)
                    .padding(.horizontal, 14)
                    .frame(height: 48)
                    .background(XAgeGlassCardBackground(cornerRadius: 22))
                    .focused($confirmFocused)
                    .submitLabel(.done)
                    .onSubmit {
                        confirmFocused = false
                        XAgeKeyboard.dismiss()
                    }
                    .accessibilityIdentifier("xage.account.delete.input")

                HStack(spacing: 10) {
                    Button {
                        confirmFocused = false
                        XAgeKeyboard.dismiss()
                        onCancel()
                    } label: {
                        Text("取消")
                            .font(.system(size: 15, weight: .bold))
                            .foregroundStyle(Color(hex: "365F80"))
                            .frame(maxWidth: .infinity)
                            .frame(height: 46)
                            .background(XAgeCapsuleFill())
                    }
                    .buttonStyle(.plain)
                    .disabled(isWorking)

                    Button {
                        confirmFocused = false
                        XAgeKeyboard.dismiss()
                        onConfirm()
                    } label: {
                        HStack(spacing: 8) {
                            if isWorking {
                                ProgressView()
                                    .tint(.white)
                            }
                            Text(isWorking ? "处理中" : "确认注销")
                                .font(.system(size: 15, weight: .bold))
                        }
                        .foregroundStyle(.white)
                        .frame(maxWidth: .infinity)
                        .frame(height: 46)
                        .background(
                            Capsule()
                                .fill(canConfirm ? AnyShapeStyle(Color(hex: "D85A66")) : AnyShapeStyle(Color(hex: "AEBFCD")))
                        )
                    }
                    .buttonStyle(.plain)
                    .disabled(!canConfirm || isWorking)
                    .accessibilityIdentifier("xage.account.delete.confirm")
                }
                }
                .padding(24)
            }
            .scrollIndicators(.hidden)
            .scrollDismissesKeyboard(.interactively)
        }
        .xAgeKeyboardDoneAccessory(
            isPresented: confirmFocused,
            accessibilityIdentifier: "xage.account.delete.keyboard.done"
        ) {
            confirmFocused = false
        }
    }
}

private struct XAgePersonalInfoPermissionSheet: View {
    let snapshot: XAgeServerSyncSnapshot
    @ObservedObject var appleHealthSync: AppleHealthSyncViewModel
    let onSyncAppleHealth: () async -> Void
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        XAgeSettingsInfoSheetScaffold(
            title: "个人信息与权限",
            subtitle: "查看资料完整度和健康数据授权",
            icon: "person.text.rectangle.fill",
            onClose: { dismiss() }
        ) {
            XAgeMetricDetailRow(title: "资料完整度", value: "\(snapshot.profileCompletion)%")
            XAgeMetricDetailRow(title: "身高", value: snapshot.profileHeightCm.map { "\(Int($0.rounded())) cm" } ?? "待补充")
            XAgeMetricDetailRow(title: "体重", value: snapshot.profileWeightKg.map { String(format: "%.1f kg", $0) } ?? "待补充")
            XAgeMetricDetailRow(title: "Apple 健康", value: appleHealthSync.lastSyncedAt == nil ? "未同步" : appleHealthSync.statusTitle)
            Button {
                Task { await onSyncAppleHealth() }
            } label: {
                HStack(spacing: 8) {
                    if appleHealthSync.isWorking {
                        ProgressView().tint(.white)
                    } else {
                        Image(systemName: "arrow.triangle.2.circlepath")
                    }
                    Text(appleHealthSync.lastSyncedAt == nil ? "授权并同步 Apple 健康" : "手动同步 Apple 健康")
                        .font(.system(size: 14, weight: .bold))
                }
                .foregroundStyle(.white)
                .frame(maxWidth: .infinity)
                .frame(height: 44)
                .background(
                    Capsule().fill(
                        LinearGradient(
                            colors: [Color(hex: "238AD6"), Color(hex: "20CDB1")],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        )
                    )
                )
            }
            .buttonStyle(.plain)
            .disabled(appleHealthSync.isWorking)
            .accessibilityIdentifier("xage.personal.appleHealth.sync")
            XAgeMetricDetailRow(title: "健康资料", value: "\(snapshot.recordCount + snapshot.examCount) 份")
            Text("家庭共享、Apple 健康和报告资料都需要单独授权。小捷只在你允许后读取数据，并按来源和测量时间写入用户端趋势。")
                .font(.system(size: 13))
                .foregroundStyle(Color(hex: "496A83"))
                .lineSpacing(3)
                .fixedSize(horizontal: false, vertical: true)
                .padding(14)
                .background(XAgeCapsuleFill())
        }
    }
}

enum XAgeFamilyField: Int, CaseIterable {
    case phone
    case relation
    case inviteCode
    case displayName
}

private struct XAgeFamilyModeSheet: View {
    @Environment(\.dismiss) private var dismiss
    @StateObject private var vm = FamilyViewModel()
    @State private var invitePhone = ""
    @State private var inviteRelation = ""
    @State private var inviteCode = ""
    @State private var displayName = ""
    @State private var showDiscardConfirmation = false
    @State private var submitting = false
    @FocusState private var focusedField: XAgeFamilyField?

    var body: some View {
        NavigationStack {
            ZStack {
                XAgeLiquidBackground()
                    .ignoresSafeArea()

                ScrollView {
                    VStack(alignment: .leading, spacing: 16) {
                        HStack {
                            VStack(alignment: .leading, spacing: 4) {
                                Text("关联用户")
                                    .font(.system(size: 28, weight: .bold))
                                    .foregroundStyle(Color(hex: "123E67"))
                                Text("家庭模式需要逐项授权，敏感健康资料默认不共享。")
                                    .font(.system(size: 13, weight: .medium))
                                    .foregroundStyle(Color(hex: "5D7890"))
                            }
                            Spacer()
                            Button {
                                requestClose()
                            } label: {
                                Image(systemName: "xmark")
                                    .font(.system(size: 13, weight: .bold))
                                    .foregroundStyle(Color(hex: "1268BD"))
                                    .frame(width: 44, height: 44)
                                    .background {
                                        XAgeCapsuleFill()
                                            .frame(width: 34, height: 34)
                                    }
                                    .contentShape(Rectangle())
                            }
                            .buttonStyle(.plain)
                            .disabled(isBusy)
                            .accessibilityLabel("返回设置")
                        }
                        .padding(.top, 10)

                        inviteCard
                        acceptCard
                        membersCard
                    }
                    .padding(24)
                }
                .scrollIndicators(.hidden)
                .scrollDismissesKeyboard(.interactively)
                .accessibilityHidden(isBusy)

                if isBusy {
                    Color.black.opacity(0.03)
                        .ignoresSafeArea()
                        .contentShape(Rectangle())
                    ProgressView()
                        .controlSize(.large)
                        .padding(18)
                        .background(XAgeGlassCardBackground(cornerRadius: 22))
                }
            }
            .toolbar(.hidden, for: .navigationBar)
            .toolbar {
                ToolbarItemGroup(placement: .keyboard) {
                    Spacer()
                    Button("完成") {
                        focusedField = nil
                        XAgeKeyboard.dismiss()
                    }
                }
            }
            .task { await vm.load() }
            .alert("家庭模式提示", isPresented: Binding(
                get: { vm.message != nil },
                set: { if !$0 { vm.message = nil } }
            )) {
                Button("知道了", role: .cancel) {}
            } message: {
                Text(vm.message ?? "")
            }
            .alert("家庭模式错误", isPresented: Binding(
                get: { vm.errorMessage != nil },
                set: { if !$0 { vm.errorMessage = nil } }
            )) {
                Button("知道了", role: .cancel) {}
            } message: {
                Text(vm.errorMessage ?? "")
            }
            .alert("放弃未提交的内容？", isPresented: $showDiscardConfirmation) {
                Button("继续编辑", role: .cancel) {}
                Button("放弃修改", role: .destructive) {
                    focusedField = nil
                    XAgeKeyboard.dismiss()
                    dismiss()
                }
            } message: {
                Text("已填写的邀请码、手机号或关系不会保存。")
            }
        }
    }

    private var hasUnsavedInput: Bool {
        !invitePhone.isEmpty || !inviteRelation.isEmpty || !inviteCode.isEmpty || !displayName.isEmpty
    }

    private var isBusy: Bool {
        vm.loading || submitting
    }

    private func requestClose() {
        focusedField = nil
        XAgeKeyboard.dismiss()
        if hasUnsavedInput {
            showDiscardConfirmation = true
        } else {
            dismiss()
        }
    }

    private var inviteCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            XAgeSectionHeader(title: "邀请家人", subtitle: "生成 7 天有效的邀请码")
            HStack(spacing: 8) {
                XAgeGlassTextField(
                    placeholder: "手机号（可选）",
                    text: $invitePhone,
                    keyboardType: .phonePad,
                    field: .phone,
                    focusedField: $focusedField,
                    contentType: .telephoneNumber,
                    capitalization: .never,
                    submitLabel: .next,
                    nextField: .relation
                )
                .accessibilityIdentifier("xage.family.phone")
                XAgeGlassTextField(
                    placeholder: "关系",
                    text: $inviteRelation,
                    field: .relation,
                    focusedField: $focusedField,
                    capitalization: .words,
                    submitLabel: .done
                )
                .accessibilityIdentifier("xage.family.relation")
            }
            Button {
                guard !isBusy else { return }
                focusedField = nil
                XAgeKeyboard.dismiss()
                submitting = true
                Task {
                    defer { submitting = false }
                    vm.errorMessage = nil
                    await vm.createInvite(targetPhone: invitePhone, relation: inviteRelation)
                    if vm.errorMessage == nil {
                        invitePhone = ""
                        inviteRelation = ""
                    }
                }
            } label: {
                XAgeGradientActionLabel(title: "生成邀请码", icon: "person.badge.plus")
            }
            .buttonStyle(.plain)
            .disabled(isBusy)
            .opacity(isBusy ? 0.55 : 1)
            .accessibilityIdentifier("xage.family.createInvite")

            if let invite = vm.latestInvite {
                HStack {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(invite.invite_code)
                            .font(.system(size: 26, weight: .bold, design: .monospaced))
                            .foregroundStyle(Color(hex: "12324F"))
                        Text("家人在自己的账号中输入后加入")
                            .font(.system(size: 12))
                            .foregroundStyle(Color(hex: "6C8194"))
                    }
                    Spacer()
                    Text("7天有效")
                        .font(.system(size: 11, weight: .bold))
                        .foregroundStyle(Color(hex: "347FB7"))
                        .padding(.horizontal, 10)
                        .frame(height: 28)
                        .background(XAgeCapsuleFill())
                }
                .padding(14)
                .background(XAgeCapsuleFill())
            }
        }
        .padding(16)
        .background(XAgeGlassCardBackground(cornerRadius: 26))
    }

    private var acceptCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            XAgeSectionHeader(title: "加入家庭", subtitle: "输入对方分享的邀请码")
            XAgeGlassTextField(
                placeholder: "邀请码",
                text: $inviteCode,
                field: .inviteCode,
                focusedField: $focusedField,
                capitalization: .characters,
                submitLabel: .next,
                nextField: .displayName
            )
            .accessibilityIdentifier("xage.family.inviteCode")
            XAgeGlassTextField(
                placeholder: "我的显示名（可选）",
                text: $displayName,
                field: .displayName,
                focusedField: $focusedField,
                capitalization: .words,
                submitLabel: .done
            )
            .accessibilityIdentifier("xage.family.displayName")
            Button {
                guard !isBusy else { return }
                focusedField = nil
                XAgeKeyboard.dismiss()
                submitting = true
                Task {
                    defer { submitting = false }
                    vm.errorMessage = nil
                    await vm.acceptInvite(code: inviteCode.uppercased(), displayName: displayName)
                    if vm.errorMessage == nil {
                        inviteCode = ""
                        displayName = ""
                    }
                }
            } label: {
                XAgeGradientActionLabel(title: "确认加入", icon: "number.square")
            }
            .buttonStyle(.plain)
            .disabled(inviteCode.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || isBusy)
            .opacity(inviteCode.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || isBusy ? 0.55 : 1)
            .accessibilityIdentifier("xage.family.acceptInvite")
        }
        .padding(16)
        .background(XAgeGlassCardBackground(cornerRadius: 26))
    }

    private var membersCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            XAgeSectionHeader(title: "授权管理", subtitle: "家人加入后才会出现在这里")
            let members = vm.members.filter { $0.user_id != vm.currentUserId }
            if members.isEmpty {
                Text("暂无关联用户。邀请或加入家庭后，可以在这里给家人单独开启查看权限。")
                    .font(.system(size: 13))
                    .foregroundStyle(Color(hex: "6C8194"))
                    .lineSpacing(3)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(14)
                    .background(XAgeCapsuleFill())
            } else {
                ForEach(members) { member in
                    XAgeFamilyMemberCard(member: member, vm: vm)
                }
            }
        }
        .padding(16)
        .background(XAgeGlassCardBackground(cornerRadius: 26))
    }
}

private struct XAgeFamilyMemberCard: View {
    let member: FamilyMember
    @ObservedObject var vm: FamilyViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                VStack(alignment: .leading, spacing: 3) {
                    Text(member.bestName)
                        .font(.system(size: 16, weight: .bold))
                        .foregroundStyle(Color(hex: "173F64"))
                    Text(member.relation ?? member.role)
                        .font(.system(size: 12, weight: .medium))
                        .foregroundStyle(Color(hex: "6C8194"))
                }
                Spacer()
                Text(member.status == "active" ? "已关联" : "待加入")
                    .font(.system(size: 11, weight: .bold))
                    .foregroundStyle(Color(hex: "347FB7"))
                    .frame(width: 58, height: 28)
                    .background(XAgeCapsuleFill())
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
                            .font(.system(size: 13, weight: .bold))
                            .foregroundStyle(Color(hex: "173F64"))
                        Text(field.subtitle)
                            .font(.system(size: 11))
                            .foregroundStyle(Color(hex: "6C8194"))
                    }
                }
                .tint(Color(hex: "20CDB1"))
            }
        }
        .padding(14)
        .background(XAgeCapsuleFill())
    }
}

#if DEBUG
/// 为 Canvas 提供 XAgeMoreMenu 所需的本地状态和测试态认证环境，不连接真实账号。
private struct XAgeSettingsPreviewHost: View {
    @State private var selectedCategory: XAgeDataPanelCategory = .profile
    @StateObject private var appleHealthSync = AppleHealthSyncViewModel()
    @StateObject private var authManager = AuthManager.makeTestingInstance()

    var body: some View {
        XAgeMoreMenu(
            selectedCategory: $selectedCategory,
            appleHealthSync: appleHealthSync,
            snapshot: .placeholder,
            onSyncAppleHealth: {},
            onSelectCategory: { _ in },
            onClose: {}
        )
        .environmentObject(authManager)
        .environment(\.healthProfilePreviewFixtureEnabled, true)
    }
}

#Preview("XAGE 更多菜单") {
    XAgeSettingsPreviewHost()
}
#endif
