import SwiftUI

enum XAgeSupportComplianceContract {
    static let destinationIDs = ["help", "version", "privacy", "permissions", "feedback"]
    static let privacyPolicyUpdatedAt = "2026年7月26日"
    static let privacyPolicyEffectiveAt = "2026年7月26日"
    static let privacyPolicyVersion = "2026.07"
    static let privacyPolicyURL = URL(string: "https://www.jianjieaitech.com/privacy")!
    /// 注册页与“更多 > 隐私政策”共用同一份正文，避免政策内容分叉。
    static var privacyPolicySections: [XAgeComplianceSection] {
        XAgeComplianceContent.privacySections
    }
    static let supportEmail = "support@xjie-health.com"
    static let privacyPolicyRequiredTopics = [
        "适用范围与重要提示", "我们如何收集和使用信息", "敏感个人信息与单独同意",
        "共享、委托与公开披露", "存储与保护", "你的权利", "未成年人", "联系我们"
    ]
    static let permissionDisclosureIDs = [
        "health", "notifications", "camera", "photos", "photo-save", "microphone", "speech", "network", "not-used"
    ]

    static func isFeedbackValid(_ content: String) -> Bool {
        let count = content.trimmingCharacters(in: .whitespacesAndNewlines).count
        return (2...2_000).contains(count)
    }

    static func hasFeedbackDraft(content: String, contact: String) -> Bool {
        !content.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            || !contact.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }
}

struct XAgeComplianceSection: Identifiable {
    let title: String
    let content: String

    var id: String { title }
}

private struct XAgePermissionDisclosure: Identifiable {
    let id: String
    let icon: String
    let title: String
    let badge: String
    let timing: String
    let purpose: String
    let consequence: String
}

private enum XAgeComplianceContent {
    static let privacySections: [XAgeComplianceSection] = [
        .init(
            title: "适用范围与重要提示",
            content: "本政策适用于“小捷”App提供的账号、健康档案、报告上传与识别、健康趋势、用药提醒和 AI 健康助手等服务。健康信息属于敏感个人信息；请在充分理解后自主决定是否提供。健康管理建议不替代医生诊断、处方、急救或线下就医。"
        ),
        .init(
            title: "我们如何收集和使用信息",
            content: "为完成账号登录、身份核验和服务保障，我们处理手机号、账号状态和必要的安全记录。你填写的基础资料、健康记录、用药信息、健康目标，以及主动上传的报告、图片或病历，用于展示档案、趋势、提醒和你请求的分析结果。使用 AI 健康助手或报告识别时，你输入的问题、上传资料及为本次回答所需的健康上下文会被处理。"
        ),
        .init(
            title: "敏感个人信息与单独同意",
            content: "健康数据、医疗资料、生理记录和语音内容可能构成敏感个人信息。Apple 健康仅在你逐项授权后读取，且当前版本不向 Apple 健康写入数据；相机、相册、麦克风、语音识别和通知仅在你主动触发相应功能时申请。拒绝可选权限不会影响账号、基础浏览和手动记录等不依赖该权限的功能。"
        ),
        .init(
            title: "共享、委托与公开披露",
            content: "除为实现你主动选择的功能、履行法定义务或取得你的单独同意外，我们不会向无关第三方出售或公开健康信息。使用 Apple 健康、系统通知、相册、相机或语音识别等系统能力时，相关处理还受 Apple 及系统服务的规则约束。涉及受托处理、第三方服务或用途变化时，我们会按适用要求另行告知并取得必要同意。"
        ),
        .init(
            title: "存储与保护",
            content: "我们在实现服务所必需的期限内保存信息，并采取访问权限控制、传输保护、审计和最小化处理等措施降低风险。互联网环境并非绝对安全；请妥善保管账号和验证码，避免在非私密环境展示报告、用药或健康状态。"
        ),
        .init(
            title: "你的权利",
            content: "你可以在应用内查看、更正或补充基础资料和健康信息，管理 Apple 健康与系统权限，撤回可选授权，提交反馈，退出登录或申请注销账号。关闭系统权限不会自动删除此前主动提交的数据；如需更正、删除或了解处理情况，可通过本政策的联系方式提出申请。注销账号为不可逆操作，请谨慎确认。"
        ),
        .init(
            title: "未成年人",
            content: "如你是未成年人，请在监护人同意和指导下使用本服务。监护人认为未成年人信息被不当处理的，可按本政策联系方式与我们联系。"
        ),
        .init(
            title: "联系我们与政策更新",
            content: "本政策版本为 \(XAgeSupportComplianceContract.privacyPolicyVersion)，生效日期为 \(XAgeSupportComplianceContract.privacyPolicyEffectiveAt)。如服务、处理目的或权利行使方式发生实质变化，我们会通过应用内页面或其他合理方式更新并提示。隐私、数据更正、删除或账号问题请联系 \(XAgeSupportComplianceContract.supportEmail)，我们将在核验身份后处理。"
        )
    ]

    static let permissionDisclosures: [XAgePermissionDisclosure] = [
        .init(id: "health", icon: "heart.text.square.fill", title: "Apple 健康", badge: "敏感信息", timing: "你主动点击“授权并同步 Apple 健康”时", purpose: "读取你逐项允许的活动、身体测量、心脏与呼吸、睡眠、营养、血糖与胰岛素及部分生理记录，并用于当前账号的健康趋势与同步。当前版本不向 Apple 健康写入数据。", consequence: "拒绝后不能同步 Apple 健康；仍可手动记录和查看其他功能。"),
        .init(id: "notifications", icon: "bell.badge.fill", title: "通知", badge: "可选", timing: "你开启用药、关怀或报告完成提醒时", purpose: "发送你主动设置的本地提醒，或接收报告完成等服务状态通知。", consequence: "拒绝后不会收到系统通知，其他功能可继续使用。"),
        .init(id: "camera", icon: "camera.fill", title: "相机", badge: "可选", timing: "你选择拍摄膳食、体检报告或其他健康资料时", purpose: "拍摄你主动选择上传的图片，用于记录或分析。", consequence: "拒绝后不能拍摄上传；可改用相册选择或其他录入方式。"),
        .init(id: "photos", icon: "photo.on.rectangle.angled", title: "相册读取", badge: "可选", timing: "你从相册选择报告、膳食或其他健康图片时", purpose: "仅获取你主动选择的图片，用于上传、记录或分析。", consequence: "拒绝后不能从相册选择图片，其他功能不受影响。"),
        .init(id: "photo-save", icon: "square.and.arrow.down.fill", title: "相册写入", badge: "可选", timing: "你主动选择保存拍摄图片到相册时", purpose: "将你刚拍摄的图片保存到系统相册。", consequence: "拒绝后不保存到相册，不影响拍摄、上传或其他功能。"),
        .init(id: "microphone", icon: "mic.fill", title: "麦克风", badge: "可选", timing: "你主动点击 AI 助手的语音输入时", purpose: "采集本次语音，以完成你请求的语音输入。", consequence: "拒绝后可继续用键盘输入。"),
        .init(id: "speech", icon: "waveform", title: "语音识别", badge: "可选", timing: "你主动使用语音输入且系统需要转换文字时", purpose: "将本次语音转换为文字，供你确认并发送。", consequence: "拒绝后无法使用语音转文字，可继续键盘输入。"),
        .init(id: "network", icon: "network", title: "网络连接", badge: "服务所需", timing: "你登录、同步、上传、调用 AI 或提交反馈时", purpose: "与服务端建立连接，完成账号、数据同步、文件上传、分析结果和服务状态的传输。该项不弹出 iOS 系统权限框。", consequence: "断开网络后，依赖服务端的功能不可用或无法更新；本地已显示内容不因此被删除。"),
        .init(id: "not-used", icon: "checkmark.shield.fill", title: "当前未申请的权限", badge: "当前版本", timing: "不适用", purpose: "当前版本不申请定位、通讯录、日历、蓝牙或 NFC 权限。", consequence: "若未来新增相关能力，我们会在实际使用场景中单独说明用途并按要求取得授权。")
    ]
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
            subtitle: "版本 \(XAgeSupportComplianceContract.privacyPolicyVersion) · 更新于 \(XAgeSupportComplianceContract.privacyPolicyUpdatedAt)",
            icon: "hand.raised.fill",
            onClose: onClose
        ) {
            XAgeComplianceHero(
                eyebrow: "请在使用前阅读",
                title: "你的健康信息，由你决定",
                message: "健康信息属于敏感个人信息。我们仅在提供你主动选择的服务所需范围内处理，并通过独立权限说明告诉你何时、为何需要系统能力。",
                icon: "lock.heart.fill"
            )
            XAgeComplianceQuickFacts(items: [
                ("健康数据", "敏感信息"),
                ("可选权限", "按需申请"),
                ("账号注销", "不可逆")
            ])
            ForEach(XAgeComplianceContent.privacySections) { section in
                XAgeSupportTextSection(title: section.title, content: section.content)
            }
            Link(destination: XAgeSupportComplianceContract.privacyPolicyURL) {
                Label("在浏览器查看最新政策", systemImage: "safari.fill")
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
            subtitle: "按需申请 · 你可随时在系统设置中管理",
            icon: "list.bullet.rectangle.fill",
            onClose: onClose
        ) {
            XAgeComplianceHero(
                eyebrow: "先说明，再申请",
                title: "不因打开 App 而索取权限",
                message: "只有在你主动使用同步、上传、语音或提醒等功能时，才会出现对应的系统授权请求。你可以拒绝或稍后在 iPhone 设置中修改。",
                icon: "checkmark.shield.fill"
            )
            XAgeSupportTextSection(
                title: "如何阅读本页",
                content: "每一项均写明申请时机、用途和拒绝后的影响。“服务所需”指网络连接，不会弹出系统权限框；“当前未申请”表示该能力在此版本没有调用。"
            )
            ForEach(XAgeComplianceContent.permissionDisclosures) { disclosure in
                XAgePermissionDisclosureCard(disclosure: disclosure)
            }
            XAgeSupportTextSection(
                title: "权限管理方式",
                content: "你可以随时前往 iPhone“设置”>“小捷”更改系统权限，Apple 健康可在“健康”App或系统设置中管理。关闭权限不会删除已经主动提交的数据；如需更正、删除或注销账号，可在应用内相关页面操作。"
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

private struct XAgeComplianceHero: View {
    let eyebrow: String
    let title: String
    let message: String
    let icon: String

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: icon)
                .font(.system(size: 18, weight: .bold))
                .foregroundStyle(.white)
                .frame(width: 42, height: 42)
                .background(
                    Circle().fill(
                        LinearGradient(
                            colors: [Color(hex: "238AD6"), Color(hex: "20CDB1")],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        )
                    )
                )
            VStack(alignment: .leading, spacing: 5) {
                Text(eyebrow)
                    .font(.system(size: 11, weight: .bold))
                    .foregroundStyle(Color(hex: "237FC4"))
                Text(title)
                    .font(.system(size: 17, weight: .bold))
                    .foregroundStyle(Color(hex: "173F64"))
                Text(message)
                    .font(.system(size: 13))
                    .foregroundStyle(Color(hex: "496A83"))
                    .lineSpacing(3)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(14)
        .background(
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .fill(LinearGradient(
                    colors: [.white.opacity(0.82), Color(hex: "E4F8FF").opacity(0.86)],
                    startPoint: .topLeading,
                    endPoint: .bottomTrailing
                ))
                .overlay(
                    RoundedRectangle(cornerRadius: 18, style: .continuous)
                        .stroke(Color(hex: "9DDFFF").opacity(0.72), lineWidth: 1)
                )
        )
    }
}

private struct XAgeComplianceQuickFacts: View {
    let items: [(String, String)]

    var body: some View {
        HStack(spacing: 8) {
            ForEach(items, id: \.0) { item in
                VStack(alignment: .leading, spacing: 3) {
                    Text(item.0)
                        .font(.system(size: 11, weight: .medium))
                        .foregroundStyle(Color(hex: "6C8194"))
                    Text(item.1)
                        .font(.system(size: 13, weight: .bold))
                        .foregroundStyle(Color(hex: "173F64"))
                        .lineLimit(1)
                        .minimumScaleFactor(0.82)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(10)
                .background(XAgeRoundedFieldBackground(cornerRadius: 12))
            }
        }
        .accessibilityElement(children: .combine)
    }
}

private struct XAgePermissionDisclosureCard: View {
    let disclosure: XAgePermissionDisclosure

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 10) {
                Image(systemName: disclosure.icon)
                    .font(.system(size: 15, weight: .bold))
                    .foregroundStyle(Color(hex: "237FC4"))
                    .frame(width: 32, height: 32)
                    .background(Color(hex: "DFF5FF").opacity(0.88), in: Circle())
                Text(disclosure.title)
                    .font(.system(size: 15, weight: .bold))
                    .foregroundStyle(Color(hex: "173F64"))
                Spacer()
                Text(disclosure.badge)
                    .font(.system(size: 11, weight: .bold))
                    .foregroundStyle(disclosure.badge == "敏感信息" ? Color(hex: "B85C38") : Color(hex: "237FC4"))
                    .padding(.horizontal, 8)
                    .padding(.vertical, 5)
                    .background(
                        (disclosure.badge == "敏感信息" ? Color(hex: "FFF1E9") : Color(hex: "E7F7FF")),
                        in: Capsule()
                    )
            }
            XAgePermissionDisclosureLine(label: "申请时机", text: disclosure.timing)
            XAgePermissionDisclosureLine(label: "使用目的", text: disclosure.purpose)
            XAgePermissionDisclosureLine(label: "拒绝影响", text: disclosure.consequence)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(14)
        .background(XAgeGlassCardBackground(cornerRadius: 16))
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("xage.permission.\(disclosure.id)")
    }
}

private struct XAgePermissionDisclosureLine: View {
    let label: String
    let text: String

    var body: some View {
        HStack(alignment: .top, spacing: 8) {
            Text(label)
                .font(.system(size: 11, weight: .bold))
                .foregroundStyle(Color(hex: "5D7890"))
                .frame(width: 48, alignment: .leading)
            Text(text)
                .font(.system(size: 12))
                .foregroundStyle(Color(hex: "496A83"))
                .lineSpacing(2)
                .fixedSize(horizontal: false, vertical: true)
        }
    }
}

struct XAgeSettingsInfoSheetScaffold<Content: View, Footer: View>: View {
    let title: String
    let subtitle: String
    let icon: String
    let onClose: () -> Void
    let content: () -> Content
    let footer: () -> Footer

    init(
        title: String,
        subtitle: String,
        icon: String,
        onClose: @escaping () -> Void,
        @ViewBuilder content: @escaping () -> Content,
        @ViewBuilder footer: @escaping () -> Footer
    ) {
        self.title = title
        self.subtitle = subtitle
        self.icon = icon
        self.onClose = onClose
        self.content = content
        self.footer = footer
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
                        .accessibilityLabel("关闭\(title)")
                        .accessibilityIdentifier("xage.settings.close.\(title)")
                    }

                    VStack(alignment: .leading, spacing: 10) {
                        content()
                    }
                    .padding(16)
                    .background(XAgeGlassCardBackground(cornerRadius: 26))

                    footer()
                }
                .padding(24)
            }
            .scrollIndicators(.hidden)
            .scrollDismissesKeyboard(.interactively)
        }
    }
}

extension XAgeSettingsInfoSheetScaffold where Footer == EmptyView {
    init(
        title: String,
        subtitle: String,
        icon: String,
        onClose: @escaping () -> Void,
        @ViewBuilder content: @escaping () -> Content
    ) {
        self.init(
            title: title,
            subtitle: subtitle,
            icon: icon,
            onClose: onClose,
            content: content,
            footer: { EmptyView() }
        )
    }
}
