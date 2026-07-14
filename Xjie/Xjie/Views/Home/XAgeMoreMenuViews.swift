import SwiftUI

// MARK: - 设置、资料与账号管理

/// 新版 XAGE 的统一设置入口。
/// 资料分类和需要完整操作空间的功能使用全屏页面，帮助/关于等轻量内容使用 Sheet，危险账号操作要求二次确认。
struct XAgeMoreMenu: View {
    @Binding var selectedCategory: XAgeDataPanelCategory
    @ObservedObject var appleHealthSync: AppleHealthSyncViewModel
    let snapshot: XAgeServerSyncSnapshot
    let onSyncAppleHealth: () async -> Void
    let onSelectCategory: (XAgeDataPanelCategory) -> Void
    let onClose: () -> Void
    @EnvironmentObject private var authManager: AuthManager
    @StateObject private var accountVM = XAgeAccountViewModel()
    @StateObject private var feedbackVM = SettingsViewModel()
    @State private var showFamilyMode = false
    @State private var showPersonalInfo = false
    @State private var showAccountSecurity = false
    @State private var showMedicationManagement = false
    @State private var showHelpFeedback = false
    @State private var showProblemFeedback = false
    @State private var showFeedbackSuccess = false
    @State private var showAbout = false
    @State private var showPrivacyPolicy = false
    @State private var showPermissionUsage = false
    @State private var showLogoutConfirm = false
    @State private var presentedCategory: XAgeDataPanelCategory?

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
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
                        Text("资料")
                            .font(.system(size: 13, weight: .bold))
                            .foregroundStyle(Color(hex: "5D7890"))
                            .padding(.horizontal, 4)
                        ForEach(XAgeDataPanelCategory.allCases) { category in
                            XAgeAccountMenuRow(
                                icon: category.iconName,
                                title: category.rawValue,
                                subtitle: category.headline,
                                selected: selectedCategory == category
                            ) {
                                // 同时更新根页面选中的资料分类，并由当前设置页呈现对应的全屏工作台。
                                selectedCategory = category
                                onSelectCategory(category)
                                presentedCategory = category
                            }
                        }
                        XAgeAccountMenuRow(
                            icon: "pills.fill",
                            title: "用药管理",
                            subtitle: "用药记录、服药时间和本地提醒"
                        ) {
                            showMedicationManagement = true
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
                            icon: "person.badge.key.fill",
                            title: "账号与安全",
                            subtitle: "手机号、密码与账号注销"
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
                        XAgeAccountMenuRow(
                            icon: "rectangle.portrait.and.arrow.right",
                            title: "退出登录",
                            subtitle: "切换账号或重新登录"
                        ) {
                            showLogoutConfirm = true
                        }
//                        XAgeAccountMenuRow(
//                            icon: "person.crop.circle.badge.xmark",
//                            title: "注销账号",
//                            subtitle: "停用账号并清除登录态",
//                            destructive: true
//                        ) {
//                            showDeleteConfirm = true
//                        }
                    }
                    .padding(14)
                    .background(XAgeGlassCardBackground(cornerRadius: 28))

                    VStack(alignment: .leading, spacing: 10) {
                        Text("关于")
                            .font(.system(size: 13, weight: .bold))
                            .foregroundStyle(Color(hex: "5D7890"))
                            .padding(.horizontal, 4)

//                        XAgeAccountMenuRow(
//                            icon: "questionmark.bubble.fill",
//                            title: "帮助与反馈",
//                            subtitle: "提交问题、查看常见操作"
//                        ) {
//                            showHelpFeedback = true
//                        }
                        XAgeAccountMenuRow(
                            icon: "bubble.left.and.text.bubble.right.fill",
                            title: "问题反馈",
                            subtitle: "提交 APP 问题或改进建议"
                        ) {
                            showProblemFeedback = true
                        }
                        XAgeAccountMenuRow(
                            icon: "info.circle.fill",
                            title: "关于小捷",
                            subtitle: "版本说明"
                        ) {
                            showAbout = true
                        }
                        XAgeAccountMenuRow(
                            icon: "hand.raised.fill",
                            title: "隐私政策",
                            subtitle: "了解个人信息的收集、使用与保护"
                        ) {
                            showPrivacyPolicy = true
                        }
                        XAgeAccountMenuRow(
                            icon: "checkmark.shield.fill",
                            title: "权限申请与使用情况说明",
                            subtitle: "查看系统权限的用途与影响"
                        ) {
                            showPermissionUsage = true
                        }
                    }
                    .padding(14)
                    .background(XAgeGlassCardBackground(cornerRadius: 28))

                    Text("皖ICP备2026008853号-2")
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
            XAgePersonalInfoPermissionSheet(snapshot: snapshot, appleHealthSync: appleHealthSync)
        }
        .fullScreenCover(isPresented: $showAccountSecurity) {
            XAgeAccountSecurityView(
                accountVM: accountVM,
                onClose: { showAccountSecurity = false },
                onAccountDeleted: {
                    showAccountSecurity = false
                    onClose()
                }
            )
            .environmentObject(authManager)
        }
        .fullScreenCover(isPresented: $showMedicationManagement) {
            XAgeMedicationManagementView {
                showMedicationManagement = false
            }
        }
        .sheet(isPresented: $showHelpFeedback) {
            XAgeHelpFeedbackSheet()
                .presentationDetents([.medium, .large])
                .presentationDragIndicator(.visible)
        }
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
        .sheet(isPresented: $showAbout) {
            XAgeAboutSheet()
                .presentationDetents([.medium, .large])
                .presentationDragIndicator(.visible)
        }
        .fullScreenCover(isPresented: $showPrivacyPolicy) {
            XAgePrivacyPolicyView(onClose: { showPrivacyPolicy = false })
        }
        .fullScreenCover(isPresented: $showPermissionUsage) {
            XAgePermissionUsageView(onClose: { showPermissionUsage = false })
        }
        .fullScreenCover(item: $presentedCategory) { category in
            XAgePanelDestinationView(
                category: category,
                appleHealthSync: appleHealthSync,
                snapshot: snapshot,
                onSyncAppleHealth: onSyncAppleHealth,
                onClose: {
                    presentedCategory = nil
                }
            )
        }
        .alert("确认退出", isPresented: $showLogoutConfirm) {
            Button("取消", role: .cancel) {}
            Button("退出", role: .destructive) {
                // 退出登录优先清除本地状态并返回登录页，服务端 token 撤销作为短超时后台请求执行。
                let accountToken = authManager.token
                onClose()
                authManager.logout(ifCurrentToken: accountToken)
                Task {
                    await accountVM.revokeLogoutToken(accountToken)
                }
            }
        } message: {
            Text("退出后会回到登录页，可使用其他账号登录。")
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

/// 加载账号安全页所需的最小用户信息；失败时保留其他安全操作可用。
@MainActor
final class XAgeAccountSecurityViewModel: ObservableObject {
    @Published private(set) var phone = "暂未获取"
    @Published private(set) var isLoading = false
    @Published private(set) var loadErrorMessage: String?

    private let api: APIServiceProtocol

    /// 注入用户信息接口，便于页面复用生产服务并保持可测试性。
    init(api: APIServiceProtocol = APIService.shared) {
        self.api = api
    }

    /// 拉取当前账号并只保留脱敏后的手机号，避免原始号码进入页面状态。
    func loadAccount() async {
        isLoading = true
        loadErrorMessage = nil
        defer { isLoading = false }
        do {
            let user: UserInfo = try await api.get("/api/users/me")
            guard !Task.isCancelled else { return }
            phone = Utils.maskedPhone(user.phone)
        } catch {
            guard !Task.isCancelled else { return }
            phone = "暂未获取"
            loadErrorMessage = "暂时无法获取当前账号手机号，请稍后重试。"
        }
    }
}

/// 集中管理当前账号的手机号展示、密码修改与不可逆注销操作。
private struct XAgeAccountSecurityView: View {
    @EnvironmentObject private var authManager: AuthManager
    @ObservedObject var accountVM: XAgeAccountViewModel
    @StateObject private var viewModel = XAgeAccountSecurityViewModel()
    @State private var showChangePassword = false
    @State private var showDeleteConfirm = false
    let onClose: () -> Void
    let onAccountDeleted: () -> Void

    /// 组合账号安全页面，并让修改密码和注销弹层由当前子页面独立管理。
    var body: some View {
        pageContent
            .task { await viewModel.loadAccount() }
            .sheet(isPresented: $showChangePassword) {
                ChangePasswordSheet()
            }
            .sheet(isPresented: $showDeleteConfirm) {
                deleteConfirmation
            }
            .alert("账号操作失败", isPresented: accountErrorBinding) {
                Button("知道了", role: .cancel) {}
            } message: {
                Text(accountVM.errorMessage ?? "")
            }
    }

    /// 构建稳定的小型根表达式，避免把完整页面与多层弹窗写入同一个 SwiftUI 表达式。
    private var pageContent: some View {
        ZStack {
            XAgeLiquidBackground()
                .ignoresSafeArea()

            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    header
                    securityRows
                }
                .padding(24)
            }
            .scrollIndicators(.hidden)
            .accessibilityIdentifier("xage.account.security.page")
        }
    }

    /// 提供只关闭账号安全子页面的返回入口。
    private var header: some View {
        HStack {
            Button(action: onClose) {
                Image(systemName: "chevron.left")
                    .font(.system(size: 17, weight: .bold))
                    .foregroundStyle(Color(hex: "347FB7"))
                    .frame(width: 42, height: 34)
                    .background(XAgeCapsuleFill())
            }
            .frame(width: 44, height: 44)
            .contentShape(Rectangle())
            .buttonStyle(.plain)
            .accessibilityLabel("返回")

            Spacer()

            Text("账号与安全")
                .font(.system(size: 19, weight: .bold))
                .foregroundStyle(Color(hex: "123E67"))

            Spacer()

            Color.clear.frame(width: 44, height: 44)
        }
    }

    /// 按需求固定为手机号、修改密码、注销账号三个展示条。
    private var securityRows: some View {
        VStack(spacing: 12) {
            phoneRow
            passwordRow
            deleteRow
        }
        .padding(14)
        .background(XAgeGlassCardBackground(cornerRadius: 28))
    }

    /// 手机号条仅展示服务端返回号码的脱敏结果，不提供编辑行为。
    private var phoneRow: some View {
        HStack(spacing: 12) {
            securityIcon("iphone", destructive: false)

            VStack(alignment: .leading, spacing: 4) {
                Text("当前账号手机号")
                    .font(.system(size: 16, weight: .bold))
                    .foregroundStyle(Color(hex: "173F64"))
                if let loadErrorMessage = viewModel.loadErrorMessage {
                    Text(loadErrorMessage)
                        .font(.system(size: 11, weight: .medium))
                        .foregroundStyle(Color(hex: "B06A3A"))
                }
            }

            Spacer(minLength: 8)

            HStack(spacing: 8) {
                Text(viewModel.phone)
                    .font(.system(size: 15, weight: .semibold, design: .monospaced))
                    .foregroundStyle(Color(hex: "496A83"))
                    .accessibilityIdentifier("xage.account.security.phone")
                if viewModel.isLoading {
                    ProgressView()
                        .tint(Color(hex: "237FC4"))
                }
            }
        }
        .padding(.horizontal, 14)
        .frame(minHeight: 68)
        .background(XAgeGlassCardBackground(cornerRadius: 22))
        .accessibilityElement(children: .contain)
    }

    /// 修改密码复用既有表单和接口校验，不在账号页重复维护密码字段。
    private var passwordRow: some View {
        Button {
            showChangePassword = true
        } label: {
            actionRowLabel(
                icon: "lock.rotation",
                title: "修改密码",
                subtitle: "验证旧密码后设置新密码",
                destructive: false
            )
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("xage.account.security.password")
    }

    /// 注销入口使用危险色，并在下一层要求输入指定文字后才能真正提交。
    private var deleteRow: some View {
        Button {
            showDeleteConfirm = true
        } label: {
            actionRowLabel(
                icon: "person.crop.circle.badge.xmark",
                title: "注销账号",
                subtitle: "永久删除账号及相关数据",
                destructive: true
            )
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("xage.account.security.delete")
    }

    /// 复用原有注销确认页，并仅在服务端确认删除后清理对应登录态。
    private var deleteConfirmation: some View {
        XAgeDeleteAccountSheet(
            isWorking: accountVM.isWorking,
            onCancel: { showDeleteConfirm = false },
            onConfirm: {
                Task {
                    let accountToken = authManager.token
                    if await accountVM.deleteAccountOnServer() {
                        showDeleteConfirm = false
                        onAccountDeleted()
                        authManager.logout(ifCurrentToken: accountToken)
                    }
                }
            }
        )
        .presentationDetents([.medium, .large])
        .interactiveDismissDisabled(accountVM.isWorking)
    }

    /// 将账号请求错误映射为 SwiftUI Alert 的布尔绑定。
    private var accountErrorBinding: Binding<Bool> {
        Binding(
            get: { accountVM.errorMessage != nil },
            set: { if !$0 { accountVM.errorMessage = nil } }
        )
    }

    /// 生成账号安全操作条的统一布局，减少页面主表达式复杂度。
    private func actionRowLabel(
        icon: String,
        title: String,
        subtitle: String,
        destructive: Bool
    ) -> some View {
        HStack(spacing: 12) {
            securityIcon(icon, destructive: destructive)

            VStack(alignment: .leading, spacing: 3) {
                Text(title)
                    .font(.system(size: 16, weight: .bold))
                    .foregroundStyle(destructive ? Color(hex: "B43D4B") : Color(hex: "173F64"))
                Text(subtitle)
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(Color(hex: "6C8194"))
            }

            Spacer()

            Image(systemName: "chevron.right")
                .font(.system(size: 13, weight: .bold))
                .foregroundStyle(Color(hex: "7D9AB1"))
        }
        .padding(.horizontal, 14)
        .frame(height: 68)
        .background(XAgeGlassCardBackground(cornerRadius: 22))
    }

    /// 生成展示条左侧图标，并根据危险操作切换颜色。
    private func securityIcon(_ name: String, destructive: Bool) -> some View {
        Image(systemName: name)
            .font(.system(size: 16, weight: .bold))
            .foregroundStyle(destructive ? Color(hex: "D85A66") : Color(hex: "237FC4"))
            .frame(width: 38, height: 38)
            .background(
                Circle()
                    .fill(.white.opacity(0.6))
                    .overlay(Circle().stroke(.white.opacity(0.78), lineWidth: 1))
            )
    }
}

/// 本地政策页面的章节数据，分别承载正文段落和列表项。
private struct XAgeLegalSection: Identifiable {
    let id: String
    let title: String
    let paragraphs: [String]
    let bullets: [String]
}

/// 权限说明条目明确区分申请时机、用途和拒绝后的影响。
private struct XAgePermissionDescription: Identifiable {
    let id: String
    let icon: String
    let title: String
    let applicationMoment: String
    let purpose: String
    let denialImpact: String
}

/// 隐私政策和权限说明共用的顶部返回栏，返回仅关闭当前全屏子页面。
private struct XAgeLocalDocumentHeader: View {
    let title: String
    let onClose: () -> Void

    /// 构建带 44pt 点击区域的返回按钮和居中标题。
    var body: some View {
        HStack {
            Button(action: onClose) {
                Image(systemName: "chevron.left")
                    .font(.system(size: 17, weight: .bold))
                    .foregroundStyle(Color(hex: "347FB7"))
                    .frame(width: 42, height: 34)
                    .background(XAgeCapsuleFill())
            }
            .frame(width: 44, height: 44)
            .contentShape(Rectangle())
            .buttonStyle(.plain)
            .accessibilityLabel("返回")

            Spacer()

            Text(title)
                .font(.system(size: 19, weight: .bold))
                .foregroundStyle(Color(hex: "123E67"))
                .multilineTextAlignment(.center)

            Spacer()

            Color.clear.frame(width: 44, height: 44)
        }
    }
}

/// 将项目现有隐私政策原文转换为不依赖网络的本地 SwiftUI 页面。
private struct XAgePrivacyPolicyView: View {
    let onClose: () -> Void

    private static let sections = [
        XAgeLegalSection(
            id: "collection",
            title: "1. 信息收集",
            paragraphs: ["我们可能收集以下信息："],
            bullets: [
                "账户信息：手机号码，用于注册和登录。",
                "健康数据：您主动上传的体检报告、病例记录、血糖监测数据等。",
                "设备信息：设备型号、操作系统版本，用于优化应用体验。"
            ]
        ),
        XAgeLegalSection(
            id: "use",
            title: "2. 信息使用",
            paragraphs: ["我们使用您的信息用于："],
            bullets: [
                "为您提供健康数据管理和分析服务。",
                "通过 AI 技术帮助整理和解读您的健康报告。",
                "改善和优化我们的产品和服务。"
            ]
        ),
        XAgeLegalSection(
            id: "storage",
            title: "3. 信息存储与安全",
            paragraphs: [],
            bullets: [
                "您的数据存储在安全的云服务器上，采用加密传输（HTTPS/TLS）。",
                "我们采取合理的技术和管理措施保护您的个人信息安全。",
                "仅经授权的人员可以访问您的数据。"
            ]
        ),
        XAgeLegalSection(
            id: "sharing",
            title: "4. 信息共享",
            paragraphs: ["我们不会向任何第三方出售、出租或交换您的个人信息，除非："],
            bullets: [
                "获得您的明确同意。",
                "根据法律法规要求或政府部门的强制要求。"
            ]
        ),
        XAgeLegalSection(
            id: "ai",
            title: "5. AI 数据处理",
            paragraphs: ["我们使用人工智能技术处理您上传的健康文档，提取结构化数据并生成分析报告。AI 处理仅用于为您提供服务，不会将您的数据用于模型训练。"],
            bullets: []
        ),
        XAgeLegalSection(
            id: "rights",
            title: "6. 您的权利",
            paragraphs: ["您有权："],
            bullets: [
                "访问和查看您的个人数据。",
                "删除您的账户及相关数据。",
                "撤回数据处理的同意。"
            ]
        ),
        XAgeLegalSection(
            id: "contact",
            title: "7. 联系我们",
            paragraphs: [
                "如您对本隐私政策有任何疑问，请通过以下方式联系我们：",
                "邮箱：support@xjie-health.com"
            ],
            bullets: []
        ),
        XAgeLegalSection(
            id: "changes",
            title: "8. 政策变更",
            paragraphs: ["我们保留更新本隐私政策的权利。变更将在本页面发布，建议您定期查看。"],
            bullets: []
        )
    ]

    /// 组合本地政策内容，所有文字随 App 安装包提供并支持离线滚动查看。
    var body: some View {
        ZStack {
            XAgeLiquidBackground()
                .ignoresSafeArea()

            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    XAgeLocalDocumentHeader(title: "隐私政策", onClose: onClose)
                    introductionCard
                    ForEach(Self.sections) { section in
                        sectionCard(section)
                    }
                }
                .padding(24)
            }
            .scrollIndicators(.hidden)
            .accessibilityIdentifier("xage.privacy.policy.page")
        }
    }

    /// 展示政策更新时间和与现有 HTML 一致的开篇说明。
    private var introductionCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("最后更新日期：2026年4月9日")
                .font(.system(size: 12, weight: .semibold))
                .foregroundStyle(Color(hex: "6C8194"))
            Text("小捷健康（以下简称\"我们\"）非常重视您的隐私。本隐私政策说明我们如何收集、使用、存储和保护您的个人信息。")
                .font(.system(size: 15))
                .foregroundStyle(Color(hex: "496A83"))
                .lineSpacing(4)
        }
        .padding(18)
        .background(XAgeGlassCardBackground(cornerRadius: 24))
    }

    /// 分别渲染章节正文和列表项，保持政策结构清晰并利于 VoiceOver 阅读。
    private func sectionCard(_ section: XAgeLegalSection) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(section.title)
                .font(.system(size: 17, weight: .bold))
                .foregroundStyle(Color(hex: "173F64"))

            ForEach(section.paragraphs, id: \.self) { paragraph in
                Text(paragraph)
                    .font(.system(size: 14))
                    .foregroundStyle(Color(hex: "496A83"))
                    .lineSpacing(4)
            }

            ForEach(section.bullets, id: \.self) { bullet in
                HStack(alignment: .top, spacing: 8) {
                    Text("•")
                        .foregroundStyle(Color(hex: "238AD6"))
                    Text(bullet)
                        .font(.system(size: 14))
                        .foregroundStyle(Color(hex: "496A83"))
                        .lineSpacing(4)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(18)
        .background(XAgeGlassCardBackground(cornerRadius: 24))
    }
}

/// 说明当前版本声明的系统权限、申请场景以及用户拒绝后的实际影响。
private struct XAgePermissionUsageView: View {
    let onClose: () -> Void

    private static let permissions = [
        XAgePermissionDescription(
            id: "camera",
            icon: "camera.fill",
            title: "相机",
            applicationMoment: "拍摄膳食或体检报告时",
            purpose: "需要使用相机拍摄膳食/体检报告等照片，用于记录与上传分析。",
            denialImpact: "拒绝后仍可从相册或文件中选择已有资料。"
        ),
        XAgePermissionDescription(
            id: "photo-read",
            icon: "photo.on.rectangle",
            title: "相册读取",
            applicationMoment: "从相册选择资料时",
            purpose: "需要访问相册以选择膳食/体检报告等照片用于上传。",
            denialImpact: "拒绝后无法从相册选择，但仍可使用相机或文件导入。"
        ),
        XAgePermissionDescription(
            id: "photo-write",
            icon: "square.and.arrow.down.fill",
            title: "相册写入",
            applicationMoment: "选择保存拍摄照片时",
            purpose: "需要将拍摄的膳食照片保存到相册（可选）。",
            denialImpact: "该能力为可选；拒绝不会影响上传本次已拍摄内容。"
        ),
        XAgePermissionDescription(
            id: "microphone",
            icon: "mic.fill",
            title: "麦克风",
            applicationMoment: "使用助手小捷语音输入时",
            purpose: "需要使用麦克风进行助手小捷语音输入。",
            denialImpact: "拒绝后可以继续使用键盘输入。"
        ),
        XAgePermissionDescription(
            id: "speech",
            icon: "waveform",
            title: "语音识别",
            applicationMoment: "将语音输入转换成文字时",
            purpose: "需要使用语音识别将您的语音转换成文字消息。",
            denialImpact: "拒绝后可以继续使用键盘输入。"
        ),
        XAgePermissionDescription(
            id: "health-read",
            icon: "heart.text.square.fill",
            title: "Apple 健康读取",
            applicationMoment: "主动授权或开启 Apple 健康同步时",
            purpose: "在你选择授权后，小捷会只读 Apple 健康中的活动、身体测量、心脏与呼吸、睡眠、营养、血糖与胰岛素、声音环境，以及经期、排卵和性活动等生理记录，并在前台或后台同步到当前登录账号的健康趋势；未授权项目不会读取。",
            denialImpact: "拒绝或仅授权部分项目，不会影响手动记录和其他未依赖该数据的功能。"
        ),
        XAgePermissionDescription(
            id: "health-write",
            icon: "heart.badge.plus",
            title: "Apple 健康写入",
            applicationMoment: "当前版本不会申请",
            purpose: "小捷当前不会向 Apple 健康写入数据；未来如提供写入功能，会在操作前另行说明并再次请求你的授权。",
            denialImpact: "当前版本没有影响。"
        )
    ]

    /// 组合权限总说明与七个权限条目，内容完全本地可用。
    var body: some View {
        ZStack {
            XAgeLiquidBackground()
                .ignoresSafeArea()

            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    XAgeLocalDocumentHeader(title: "权限申请与使用情况说明", onClose: onClose)
                    overviewCard
                    ForEach(Self.permissions) { permission in
                        permissionCard(permission)
                    }
                }
                .padding(24)
            }
            .scrollIndicators(.hidden)
            .accessibilityIdentifier("xage.permissions.usage.page")
        }
    }

    /// 告知用户授权自愿、按场景触发，并可在系统设置中调整。
    private var overviewCard: some View {
        Text("以下权限仅在你使用对应功能时申请。是否授权由你决定，你可以随时前往 iOS“设置”中调整；未授权的项目不会被读取。")
            .font(.system(size: 14))
            .foregroundStyle(Color(hex: "496A83"))
            .lineSpacing(4)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(18)
            .background(XAgeGlassCardBackground(cornerRadius: 24))
    }

    /// 为单项权限展示名称、申请时机、用途和拒绝影响。
    private func permissionCard(_ permission: XAgePermissionDescription) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Label(permission.title, systemImage: permission.icon)
                .font(.system(size: 17, weight: .bold))
                .foregroundStyle(Color(hex: "173F64"))

            permissionDetail(label: "申请时机", value: permission.applicationMoment)
            permissionDetail(label: "使用目的", value: permission.purpose)
            permissionDetail(label: "拒绝影响", value: permission.denialImpact)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(18)
        .background(XAgeGlassCardBackground(cornerRadius: 24))
    }

    /// 使用独立文本层级展示权限字段，避免长说明挤压标题。
    private func permissionDetail(label: String, value: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(label)
                .font(.system(size: 12, weight: .bold))
                .foregroundStyle(Color(hex: "237FC4"))
            Text(value)
                .font(.system(size: 14))
                .foregroundStyle(Color(hex: "496A83"))
                .lineSpacing(4)
        }
    }
}

@MainActor
/// 封装退出和注销等账号请求，并保护进行中状态。
/// 退出允许网络失败时本地完成；注销则必须服务端成功，避免客户端误以为账号已经停用。
final class XAgeAccountViewModel: ObservableObject {
    @Published var isWorking = false
    @Published var errorMessage: String?

    private let api: APIServiceProtocol

    /// 注入账号相关 API 实现，供退出登录和注销账号流程复用。
    init(api: APIServiceProtocol = APIService.shared) {
        self.api = api
    }

    /// 执行 `logout` 对应的删除、撤销或退出操作，并处理关联状态。
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

    /// 执行 `revokeLogoutToken` 对应的删除、撤销或退出操作，并处理关联状态。
    func revokeLogoutToken(_ token: String) async {
        // 使用捕获的旧 token 直接发短超时请求，因为本地 logout 后 AuthManager 已不再保存该 token。
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

    /// 执行 `deleteAccount` 对应的删除、撤销或退出操作，并处理关联状态。
    func deleteAccount(authManager: AuthManager) async {
        let accountToken = authManager.token
        if await deleteAccountOnServer() {
            authManager.logout(ifCurrentToken: accountToken)
        }
    }

    /// 执行 `deleteAccountOnServer` 对应的删除、撤销或退出操作，并处理关联状态。
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

private struct XAgeMoreMenuRow: View {
    let identifier: String
    let icon: String
    let title: String
    let subtitle: String
    let selected: Bool
    let action: () -> Void

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
    var body: some View {
        Button(action: action) {
            HStack(spacing: 12) {
                Image(systemName: icon)
                    .font(.system(size: 17, weight: .bold))
                    .foregroundStyle(.white)
                    .frame(width: 38, height: 38)
                    .background(
                        Circle()
                            .fill(
                                LinearGradient(
                                    colors: selected ? [Color(hex: "238AD6"), Color(hex: "20CDB1")] : [Color(hex: "7ABBE7"), Color(hex: "92DDCE")],
                                    startPoint: .topLeading,
                                    endPoint: .bottomTrailing
                                )
                            )
                    )

                VStack(alignment: .leading, spacing: 3) {
                    Text(title)
                        .font(.system(size: 18, weight: .bold))
                        .foregroundStyle(Color(hex: "173F64"))
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
            .frame(height: 64)
            .background(XAgeGlassCardBackground(cornerRadius: 22))
        }
        .buttonStyle(.plain)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(title)、\(subtitle)")
        .accessibilityValue(selected ? "已选中" : "")
        .xAgeAccessibilitySelected(selected)
        .accessibilityIdentifier("xage.more.category.\(identifier)")
    }
}

private struct XAgeAccountMenuRow: View {
    let icon: String
    let title: String
    let subtitle: String
    var destructive = false
    var selected = false
    let action: () -> Void

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
    var body: some View {
        Button(action: action) {
            HStack(spacing: 12) {
                Image(systemName: icon)
                    .font(.system(size: 16, weight: .bold))
                    .foregroundStyle(destructive ? Color(hex: "D85A66") : Color(hex: "237FC4"))
                    .frame(width: 38, height: 38)
                    .background(Circle().fill(.white.opacity(0.6)).overlay(Circle().stroke(.white.opacity(0.78), lineWidth: 1)))

                VStack(alignment: .leading, spacing: 3) {
                    Text(title)
                        .font(.system(size: 16, weight: .bold))
                        .foregroundStyle(destructive ? Color(hex: "B43D4B") : Color(hex: "173F64"))
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
        .accessibilityValue(selected ? "当前资料分类" : "")
        .xAgeAccessibilitySelected(selected)
        .accessibilityIdentifier("xage.account.\(title)")
    }
}

/// 注销确认页要求输入指定文字后才启用最终按钮，降低误触发不可逆账号操作的风险。
private struct XAgeDeleteAccountSheet: View {
    let isWorking: Bool
    let onCancel: () -> Void
    let onConfirm: () -> Void
    @State private var confirmText = ""
    @FocusState private var confirmFocused: Bool

    private var canConfirm: Bool {
        confirmText.trimmingCharacters(in: .whitespacesAndNewlines) == "注销"
    }

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
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
        .toolbar {
            ToolbarItemGroup(placement: .keyboard) {
                Spacer()
                Button("完成") {
                    confirmFocused = false
                    XAgeKeyboard.dismiss()
                }
            }
        }
    }
}

/// 个人信息与权限概览，汇总资料完整度、Apple Health 状态和隐私授权说明，不在此页直接修改健康数据。
private struct XAgePersonalInfoPermissionSheet: View {
    let snapshot: XAgeServerSyncSnapshot
    @ObservedObject var appleHealthSync: AppleHealthSyncViewModel
    @Environment(\.dismiss) private var dismiss

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
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

private struct XAgeHelpFeedbackSheet: View {
    @Environment(\.dismiss) private var dismiss

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
    var body: some View {
        XAgeSettingsInfoSheetScaffold(
            title: "帮助与反馈",
            subtitle: "常见操作和问题反馈入口",
            icon: "questionmark.bubble.fill",
            onClose: { dismiss() }
        ) {
            XAgeMetricDetailRow(title: "上传报告", value: "资料 > 报告")
            XAgeMetricDetailRow(title: "补录指标", value: "数据卡片 > 手动记录")
            XAgeMetricDetailRow(title: "同步日常", value: "资料 > 日常")
            Text("遇到识别失败、数据不同步或评分异常时，可以把问题截图和发生时间发给小捷团队。后续版本会把反馈入口接入线上工单。")
                .font(.system(size: 13))
                .foregroundStyle(Color(hex: "496A83"))
                .lineSpacing(3)
                .fixedSize(horizontal: false, vertical: true)
                .padding(14)
                .background(XAgeCapsuleFill())
        }
    }
}

/// 收集用户对 APP 的问题或改进建议，并复用设置模块的反馈接口提交到服务端。
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
            feedbackEditor

            XAgeMetricDetailRow(title: "联系我们", value: "jianjieaitech@163.com")
                .accessibilityIdentifier("xage.feedback.email")

            submitButton
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

    private var feedbackEditor: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("反馈内容")
                .font(.system(size: 13, weight: .bold))
                .foregroundStyle(Color(hex: "5D7890"))
            TextEditor(text: $content)
                .frame(minHeight: 180)
                .padding(10)
                .scrollContentBackground(.hidden)
                .background(XAgeRoundedFieldBackground())
                .accessibilityIdentifier("xage.feedback.content")
            Text("\(trimmedContent.count)/2000")
                .font(.system(size: 12, weight: .semibold))
                .foregroundStyle(trimmedContent.count > 2000 ? .red : Color(hex: "7D9AB1"))
                .frame(maxWidth: .infinity, alignment: .trailing)
        }
    }

    private var submitButton: some View {
        Button {
            submit()
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

    private func submit() {
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
    }
}

private struct XAgeAboutSheet: View {
    @Environment(\.dismiss) private var dismiss

    private var versionText: String {
        let info = Bundle.main.infoDictionary
        let version = info?["CFBundleShortVersionString"] as? String ?? "1.0"
        let build = info?["CFBundleVersion"] as? String ?? "-"
        return "\(version)(\(build))"
    }

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
    var body: some View {
        XAgeSettingsInfoSheetScaffold(
            title: "关于小捷",
            subtitle: "版本说明",
            icon: "info.circle.fill",
            onClose: { dismiss() }
        ) {
            XAgeMetricDetailRow(title: "当前版本", value: versionText)
            XAgeMetricDetailRow(title: "应用名称", value: "小捷")
            XAgeMetricDetailRow(title: "备案信息", value: "皖ICP备2026008853号-2")
            Text("本版本聚焦 XAGE 数据、问答和 X年龄体验：健康数据按来源和测量时间同步，报告上传进入 AI 识别队列，评分在数据不足时先显示待评估。")
                .font(.system(size: 13))
                .foregroundStyle(Color(hex: "496A83"))
                .lineSpacing(3)
                .fixedSize(horizontal: false, vertical: true)
                .padding(14)
                .background(XAgeCapsuleFill())
        }
    }
}

/// 帮助、关于等说明页共用的容器，统一背景、标题、关闭按钮和内容卡片样式。
private struct XAgeSettingsInfoSheetScaffold<Content: View>: View {
    let title: String
    let subtitle: String
    let icon: String
    let onClose: () -> Void
    let content: () -> Content

    /// 注入说明页标题、图标、关闭动作与自定义内容构建闭包。
    init(
        title: String,
        subtitle: String,
        icon: String,
        onClose: @escaping () -> Void,
        @ViewBuilder content: @escaping () -> Content
    ) {
        self.title = title
        self.subtitle = subtitle
        self.icon = icon
        self.onClose = onClose
        self.content = content
    }

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
    var body: some View {
        ZStack {
            XAgeLiquidBackground()
                .ignoresSafeArea()

            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    HStack(spacing: 12) {
                        Image(systemName: icon)
                            .font(.system(size: 22, weight: .bold))
                            .foregroundStyle(Color(hex: "237FC4"))
                            .frame(width: 52, height: 52)
                            .background(XAgeCapsuleFill())
                        VStack(alignment: .leading, spacing: 4) {
                            Text(title)
                                .font(.system(size: 24, weight: .bold))
                                .foregroundStyle(Color(hex: "123E67"))
                            Text(subtitle)
                                .font(.system(size: 13, weight: .medium))
                                .foregroundStyle(Color(hex: "5D7890"))
                        }
                        Spacer()
                        Button(action: onClose) {
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
                        content()
                    }
                    .padding(16)
                    .background(XAgeGlassCardBackground(cornerRadius: 26))
                }
                .padding(24)
            }
            .scrollIndicators(.hidden)
        }
    }
}

private enum XAgeFamilyField: Int, CaseIterable {
    case phone
    case relation
    case inviteCode
    case displayName
}

// MARK: - 家庭关联与逐项授权

/// 新版家庭模式页面，包含生成邀请码、接受邀请和成员权限管理三部分。
/// 邀请相关输入只保存在当前页面；关闭时如有未提交内容，会先要求确认放弃。
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

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
    var body: some View {
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
        // 页面首次出现时统一加载当前用户、成员、邀请码和权限状态，后续开关直接通过同一 ViewModel 更新。
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

    private var hasUnsavedInput: Bool {
        !invitePhone.isEmpty || !inviteRelation.isEmpty || !inviteCode.isEmpty || !displayName.isEmpty
    }

    private var isBusy: Bool {
        vm.loading || submitting
    }

    /// 发起 `requestClose` 对应的权限、关闭或状态变更请求。
    private func requestClose() {
        // 先退出键盘，再根据是否有未提交的邀请码/关系信息决定直接关闭或弹出确认。
        focusedField = nil
        XAgeKeyboard.dismiss()
        if hasUnsavedInput {
            showDiscardConfirmation = true
        } else {
            dismiss()
        }
    }

    /// 构建 `inviteCard` 对应的局部 SwiftUI 视图，并组合所需的展示状态与交互。
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
                    submitLabel: .next,
                    nextField: .inviteCode
                )
                .accessibilityIdentifier("xage.family.relation")
            }
            Button {
                // 生成成功后清空本次邀请输入，最新邀请码由 ViewModel 返回并显示在同一卡片中。
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

    /// 构建 `acceptCard` 对应的局部 SwiftUI 视图，并组合所需的展示状态与交互。
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
                submitLabel: .done,
                nextField: nil
            )
            .accessibilityIdentifier("xage.family.displayName")
            Button {
                // 邀请码统一转为大写提交；成功加入后清空输入并由 ViewModel 刷新成员关系。
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

    /// 构建 `membersCard` 对应的局部 SwiftUI 视图，并组合所需的展示状态与交互。
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

/// 单个家庭成员的权限卡片。每个 Toggle 对应独立权限字段，修改后立即向服务端提交该成员的授权值。
private struct XAgeFamilyMemberCard: View {
    let member: FamilyMember
    @ObservedObject var vm: FamilyViewModel

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
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

private struct XAgeSectionHeader: View {
    let title: String
    let subtitle: String

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(title)
                .font(.system(size: 18, weight: .bold))
                .foregroundStyle(Color(hex: "173F64"))
            Text(subtitle)
                .font(.system(size: 12, weight: .medium))
                .foregroundStyle(Color(hex: "6C8194"))
        }
    }
}

struct CapsuleButton: View {
    let title: String
    var isEnabled = true
    let action: () -> Void

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
    var body: some View {
        Button(action: action) {
            Text(title)
                .font(.system(size: 12, weight: .bold))
                .foregroundStyle(Color(hex: "365F80"))
                .frame(width: 56, height: 44)
                .background {
                    XAgeCapsuleFill()
                        .frame(height: 30)
                }
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .disabled(!isEnabled)
        .opacity(isEnabled ? 1 : 0.42)
    }
}
