import SwiftUI

enum XAgeSupportComplianceContract {
    static let destinationIDs = ["help", "version", "privacy", "permissions", "feedback"]
    static let privacyPolicyUpdatedAt = "2026年4月9日"
    static let privacyPolicyURL = URL(string: "https://www.jianjieaitech.com/privacy")!
    static let supportEmail = "support@xjie-health.com"

    static func isFeedbackValid(_ content: String) -> Bool {
        let count = content.trimmingCharacters(in: .whitespacesAndNewlines).count
        return (2...2_000).contains(count)
    }

    static func hasFeedbackDraft(content: String, contact: String) -> Bool {
        !content.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            || !contact.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }
}

enum XAgeSupportDestination: String, Identifiable {
    case help
    case version
    case privacy
    case permissions
    case feedback

    var id: String { rawValue }
}

extension View {
    func xAgeSupportPresentation(
        destination: Binding<XAgeSupportDestination?>,
        settingsVM: SettingsViewModel
    ) -> some View {
        fullScreenCover(item: destination) { presented in
            XAgeSupportComplianceView(
                destination: presented,
                settingsVM: settingsVM,
                onClose: { destination.wrappedValue = nil }
            )
        }
    }
}

struct XAgeSupportComplianceView: View {
    let destination: XAgeSupportDestination
    @ObservedObject var settingsVM: SettingsViewModel
    let onClose: () -> Void

    @ViewBuilder
    var body: some View {
        switch destination {
        case .help:
            XAgeUsageHelpView(onClose: onClose)
        case .version:
            XAgeVersionInfoView(onClose: onClose)
        case .privacy:
            XAgePrivacyPolicyView(onClose: onClose)
        case .permissions:
            XAgePermissionUsageView(onClose: onClose)
        case .feedback:
            XAgeFeedbackView(vm: settingsVM, onClose: onClose)
        }
    }
}

private struct XAgeUsageHelpView: View {
    let onClose: () -> Void

    var body: some View {
        XAgeSettingsInfoSheetScaffold(
            title: "使用帮助",
            subtitle: "常见操作都从当前页面可到达",
            icon: "questionmark.circle.fill",
            onClose: onClose
        ) {
            XAgeSupportTextSection(
                title: "上传或查看报告",
                content: "回到首页，点“报告”。上传后可查看识别状态；识别结果需要你确认后才会进入正式健康档案。"
            )
            XAgeSupportTextSection(
                title: "补录健康指标",
                content: "回到首页，点“管理”进入数据卡片管理；或打开某个指标详情后选择手动记录。请同时确认测量时间和单位。"
            )
            XAgeSupportTextSection(
                title: "同步 Apple 健康",
                content: "更多 > 个人信息与权限，点“授权并同步 Apple 健康”。拒绝授权不会影响手动记录；系统只读取你单独允许的指标。"
            )
            XAgeSupportTextSection(
                title: "AI 回答怎么看",
                content: "回答中的来源和数据时间用于解释依据。内容仅供健康管理参考，不构成诊断或治疗建议；急症或明显不适请及时联系医疗机构。"
            )
        }
    }
}

private struct XAgeVersionInfoView: View {
    let onClose: () -> Void

    private var versionText: String {
        let info = Bundle.main.infoDictionary
        let version = info?["CFBundleShortVersionString"] as? String ?? "1.0"
        let build = info?["CFBundleVersion"] as? String ?? "-"
        return "\(version)(\(build))"
    }

    var body: some View {
        XAgeSettingsInfoSheetScaffold(
            title: "版本信息",
            subtitle: "当前安装版本与备案信息",
            icon: "info.circle.fill",
            onClose: onClose
        ) {
            XAgeMetricDetailRow(title: "当前版本", value: versionText)
            XAgeMetricDetailRow(title: "应用名称", value: "小捷")
            XAgeMetricDetailRow(title: "备案信息", value: "皖ICP备2026008853号-2")
            XAgeSupportTextSection(
                title: "版本说明",
                content: "本版本聚焦 XAGE 数据、问答和 X年龄体验：健康数据按来源和测量时间同步，报告上传进入 AI 识别队列，评分在数据不足时先显示待评估。"
            )
        }
    }
}

private struct XAgePrivacyPolicyView: View {
    let onClose: () -> Void

    var body: some View {
        XAgeSettingsInfoSheetScaffold(
            title: "隐私政策",
            subtitle: "更新日期：\(XAgeSupportComplianceContract.privacyPolicyUpdatedAt)",
            icon: "hand.raised.fill",
            onClose: onClose
        ) {
            XAgeSupportTextSection(
                title: "我们处理哪些信息",
                content: "为提供账号、健康档案、报告识别、健康趋势和 AI 健康助手服务，我们会在获得授权后处理账号信息、你主动填写或上传的健康信息、设备与运行信息。系统权限的申请时机和用途可在“权限申请与使用情况说明”查看。"
            )
            XAgeSupportTextSection(
                title: "健康与报告数据",
                content: "健康数据属于敏感个人信息。Apple 健康权限由系统逐项询问，小捷仅在你允许后读取相应指标；报告、病历和手动记录由你主动提交。拒绝非必要权限不影响账号和基础浏览功能。"
            )
            XAgeSupportTextSection(
                title: "AI 处理边界",
                content: "当你使用 AI 健康助手或报告识别时，相关问题和必要的健康上下文会用于生成本次结果，不用于公开展示。AI 内容仅供健康管理参考，不能替代医生诊断、处方或急救。"
            )
            XAgeSupportTextSection(
                title: "保存、安全与共享",
                content: "我们按实现服务所需的最短期限保存信息，并采取访问控制、传输保护和审计措施。除法律要求、提供你选择的服务或获得你的单独同意外，不向无关第三方出售或共享健康数据。"
            )
            XAgeSupportTextSection(
                title: "你的权利",
                content: "你可以在应用内查看、更正或补充资料，管理 Apple 健康和 AI/上传授权，提交反馈，退出登录或申请注销账号。注销是不可逆操作，必须在独立确认页输入“注销”。"
            )
            XAgeSupportTextSection(
                title: "联系我们",
                content: "隐私、数据更正或账号问题可发送至 \(XAgeSupportComplianceContract.supportEmail)。我们会核验身份后处理。"
            )
            Link(destination: XAgeSupportComplianceContract.privacyPolicyURL) {
                Label("查看官网政策原文", systemImage: "safari.fill")
                    .font(.system(size: 14, weight: .bold))
                    .foregroundStyle(Color(hex: "237FC4"))
                    .frame(maxWidth: .infinity)
                    .frame(height: 44)
                    .background(XAgeGlassCardBackground(cornerRadius: 14))
            }
            .accessibilityHint("需要网络连接")
        }
    }
}

private struct XAgePermissionUsageView: View {
    let onClose: () -> Void

    var body: some View {
        XAgeSettingsInfoSheetScaffold(
            title: "权限申请与使用情况说明",
            subtitle: "按系统权限说明申请时机、用途与拒绝影响",
            icon: "list.bullet.rectangle.fill",
            onClose: onClose
        ) {
            XAgeSupportTextSection(
                title: "Apple 健康",
                content: "申请时机：你主动点击授权或同步时。用途：读取你逐项允许的步数、距离、睡眠、心率变异性、静息心率和体重等指标。拒绝后仍可手动记录健康数据。"
            )
            XAgeSupportTextSection(
                title: "通知",
                content: "申请时机：你开启用药提醒或其他关怀提醒时。用途：按你设置的时间发送本地提醒。拒绝后不会发送系统通知，可继续使用其他功能。"
            )
            XAgeSupportTextSection(
                title: "相机与照片",
                content: "申请时机：你选择拍摄或从相册上传健康报告时。用途：获取你主动选择的报告图片并进行识别。拒绝后无法使用对应的拍摄或相册选择方式，其他功能不受影响。"
            )
            XAgeSupportTextSection(
                title: "麦克风与语音识别",
                content: "申请时机：你主动使用语音输入时。用途：采集本次语音并转换为文字。拒绝后可继续使用键盘输入。"
            )
            XAgeSupportTextSection(
                title: "蓝牙与 NFC",
                content: "当前版本尚未开放健康硬件绑定，因此不会申请蓝牙或 NFC 权限。相关设备功能开放前，我们会在实际使用场景中另行说明并征得授权。"
            )
            XAgeSupportTextSection(
                title: "权限管理方式",
                content: "你可以随时前往 iPhone“设置”中的小捷页面更改系统权限。关闭权限不会删除已经主动提交的数据；如需更正、删除或注销账号，可在应用内相关页面操作。"
            )
        }
    }
}

private struct XAgeFeedbackView: View {
    @ObservedObject var vm: SettingsViewModel
    let onClose: () -> Void

    @State private var category = "general"
    @State private var content = ""
    @State private var contact = ""
    @State private var isSubmitting = false
    @State private var showSuccess = false
    @State private var showDiscardConfirmation = false
    @FocusState private var focusedField: Field?

    private enum Field {
        case content
        case contact
    }

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
        XAgeSupportComplianceContract.isFeedbackValid(content) && !isSubmitting
    }

    private var hasDraft: Bool {
        XAgeSupportComplianceContract.hasFeedbackDraft(content: content, contact: contact)
    }

    var body: some View {
        XAgeSettingsInfoSheetScaffold(
            title: "意见反馈",
            subtitle: "提交后由小捷团队跟进",
            icon: "bubble.left.and.text.bubble.right.fill",
            onClose: requestClose
        ) {
            VStack(alignment: .leading, spacing: 8) {
                Text("反馈类型")
                    .font(.system(size: 13, weight: .bold))
                    .foregroundStyle(Color(hex: "5D7890"))
                Picker("反馈类型", selection: $category) {
                    ForEach(categories, id: \.0) { item in
                        Text(item.1).tag(item.0)
                    }
                }
                .pickerStyle(.segmented)
            }

            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    Text("问题或建议")
                        .font(.system(size: 13, weight: .bold))
                        .foregroundStyle(Color(hex: "5D7890"))
                    Spacer()
                    Text("\(trimmedContent.count)/2000")
                        .font(.system(size: 12, weight: .medium))
                        .foregroundStyle(trimmedContent.count > 2_000 ? Color(hex: "D85A66") : Color(hex: "6C8194"))
                }
                TextEditor(text: $content)
                    .font(.system(size: 16))
                    .frame(minHeight: 180)
                    .padding(10)
                    .scrollContentBackground(.hidden)
                    .background(XAgeCapsuleFill())
                    .focused($focusedField, equals: .content)
                    .accessibilityIdentifier("xage.feedback.content")
            }

            VStack(alignment: .leading, spacing: 8) {
                Text("联系方式（可选）")
                    .font(.system(size: 13, weight: .bold))
                    .foregroundStyle(Color(hex: "5D7890"))
                TextField("手机号、邮箱或微信", text: $contact)
                    .textInputAutocapitalization(.never)
                    .disableAutocorrection(true)
                    .padding(.horizontal, 14)
                    .frame(height: 48)
                    .background(XAgeCapsuleFill())
                    .focused($focusedField, equals: .contact)
                    .submitLabel(.done)
                    .onSubmit(dismissKeyboard)
            }

            Button(action: submit) {
                HStack(spacing: 8) {
                    if isSubmitting {
                        ProgressView().tint(.white)
                    } else {
                        Image(systemName: "paperplane.fill")
                    }
                    Text(isSubmitting ? "正在提交" : "提交反馈")
                        .font(.system(size: 15, weight: .bold))
                }
                .foregroundStyle(.white)
                .frame(maxWidth: .infinity)
                .frame(height: 48)
                .background(Capsule().fill(canSubmit ? Color(hex: "238AD6") : Color(hex: "AEBFCD")))
            }
            .buttonStyle(.plain)
            .disabled(!canSubmit)
            .accessibilityIdentifier("xage.feedback.submit")
        }
        .interactiveDismissDisabled(isSubmitting || hasDraft)
        .xAgeKeyboardDoneAccessory(
            isPresented: focusedField != nil,
            accessibilityIdentifier: "xage.feedback.keyboard.done"
        ) {
            dismissKeyboard()
        }
        .alert("反馈已提交", isPresented: $showSuccess) {
            Button("完成", action: onClose)
        } message: {
            Text("感谢你的反馈，我们会结合应用版本和你填写的信息进行排查。")
        }
        .alert("提交失败", isPresented: Binding(
            get: { vm.errorMessage != nil },
            set: { if !$0 { vm.errorMessage = nil } }
        )) {
            Button("知道了", role: .cancel) {}
        } message: {
            Text(vm.errorMessage ?? "请稍后重试")
        }
        .alert("放弃这次反馈？", isPresented: $showDiscardConfirmation) {
            Button("继续编辑", role: .cancel) {}
            Button("放弃反馈", role: .destructive, action: onClose)
        } message: {
            Text("已输入的内容不会保存。")
        }
    }

    private func requestClose() {
        guard !isSubmitting else { return }
        dismissKeyboard()
        if hasDraft {
            showDiscardConfirmation = true
        } else {
            onClose()
        }
    }

    private func dismissKeyboard() {
        focusedField = nil
        XAgeKeyboard.dismiss()
    }

    private func submit() {
        guard canSubmit else { return }
        dismissKeyboard()
        isSubmitting = true
        let normalizedContact = contact.trimmingCharacters(in: .whitespacesAndNewlines)
        Task {
            let didSubmit = await vm.submitFeedback(
                category: category,
                content: trimmedContent,
                contact: normalizedContact.isEmpty ? nil : normalizedContact
            )
            isSubmitting = false
            if didSubmit {
                showSuccess = true
            }
        }
    }
}

private struct XAgeSupportTextSection: View {
    let title: String
    let content: String

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title)
                .font(.system(size: 14, weight: .bold))
                .foregroundStyle(Color(hex: "173F64"))
            Text(content)
                .font(.system(size: 13))
                .foregroundStyle(Color(hex: "496A83"))
                .lineSpacing(3)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(14)
        .background(XAgeGlassCardBackground(cornerRadius: 14))
    }
}

struct XAgeSettingsInfoSheetScaffold<Content: View>: View {
    let title: String
    let subtitle: String
    let icon: String
    let onClose: () -> Void
    let content: () -> Content

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
            .scrollDismissesKeyboard(.interactively)
        }
    }
}
