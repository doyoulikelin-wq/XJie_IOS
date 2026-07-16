import AVFoundation
import Speech
import SwiftUI
import UIKit

func xAgeWelcomeGreeting(at date: Date = Date(), calendar: Calendar = .autoupdatingCurrent) -> String {
    let hour = calendar.component(.hour, from: date)
    let period = hour == 23 || hour < 5 ? "夜深了" : hour < 11 ? "早上好" : hour < 14 ? "中午好" : hour < 18 ? "下午好" : "晚上好"
    return "\(period)，想问什么？"
}

struct XAgeConversationSurface: View {
    private static let bottomAnchorID = "xage.chat.bottom"

    @EnvironmentObject private var authManager: AuthManager
    @Environment(\.xAgeOpenConversationModule) private var openConversationModule
    @Binding var selectedSection: XAgeTopSection
    let historyRequest: Int
    @StateObject private var vm = ChatViewModel()
    @StateObject private var reportUploadVM = HealthReportCompletionViewModel()
    @StateObject private var speechInput = XAgeSpeechInputManager()
    @State private var selectedAnalysis: ChatMessageItem?
    @State private var selectedEvidence: ChatMessageItem?
    @State private var showCamera = false
    @State private var showPhotoLibrary = false
    @State private var showDocumentPicker = false
    @State private var showAttachmentMenu = false
    @State private var pendingUpload: XAgePendingReportUpload?
    @State private var uploadQualityWarning: String?
    @State private var recoveryAssetIndex: Int?
    @FocusState private var inputFocused: Bool

    var body: some View {
        ZStack(alignment: .bottomTrailing) {
            VStack(spacing: 0) {
                ScrollViewReader { proxy in
                    ScrollView {
                        LazyVStack(spacing: 12) {
                            if vm.messages.isEmpty {
                                XAgeChatWelcome(
                                    vm: vm,
                                    onSendPrompt: sendStarterPrompt
                                )
                                    .padding(.top, 34)
                            }
                            ForEach(vm.messages) { msg in
                                XAgeChatBubble(
                                    message: msg,
                                    onRetry: { retryMessage(id: msg.id) },
                                    onAnalysis: { selectedAnalysis = msg },
                                    onEvidence: { selectedEvidence = msg }
                                )
                                .id(msg.id)
                            }
                            if reportUploadVM.uploading || reportUploadVM.backgroundTaskHint != nil {
                                XAgeChatUploadStatusCard(
                                    uploading: reportUploadVM.uploading,
                                    title: reportUploadVM.uploading
                                        ? (reportUploadVM.uploadStage.isEmpty ? "正在上传报告…" : reportUploadVM.uploadStage)
                                        : "报告已上传，AI 正在识别",
                                    subtitle: reportUploadVM.backgroundTaskHint ?? "识别完成后仍需在报告页面检查并确认。"
                                )
                                .id("xage.upload.status")
                            }
                            if vm.sending {
                                XAgeChatThinkingCard(
                                    currentHint: vm.thinkingHint.isEmpty ? "正在思考…" : vm.thinkingHint,
                                    steps: vm.thinkingProgressItems
                                )
                                .id("xage.chat.thinking")
                            }
                            Color.clear
                                .frame(height: 1)
                                .id(Self.bottomAnchorID)
                        }
                        .padding(.horizontal, 24)
                        .padding(.bottom, 96)
                    }
                    .scrollIndicators(.hidden)
                    .scrollDismissesKeyboard(.interactively)
                    .scrollBounceBehavior(.always, axes: .vertical)
                    .simultaneousGesture(
                        TapGesture().onEnded {
                            inputFocused = false
                        }
                    )
                    .background(
                        Color.clear
                            .contentShape(Rectangle())
                            .onTapGesture {
                                inputFocused = false
                            }
                    )
                    .background {
                        XAgeVerticalKeyboardDismissInstaller {
                            inputFocused = false
                            XAgeKeyboard.dismiss()
                        }
                        .frame(width: 0, height: 0)
                    }
                    .accessibilityIdentifier("xage.chat.scroll")
                    .onChange(of: vm.messages.count) { _, _ in
                        scrollToBottom(proxy)
                    }
                    .onChange(of: vm.sending) { _, _ in
                        scrollToBottom(proxy)
                    }
                    .onChange(of: vm.thinkingStepIndex) { _, _ in
                        scrollToBottom(proxy)
                    }
                    .onChange(of: reportUploadVM.uploading) { _, _ in
                        scrollToBottom(proxy)
                    }
                    .onChange(of: reportUploadVM.backgroundTaskHint ?? "") { _, _ in
                        scrollToBottom(proxy)
                    }
                }

                XAgeConversationModuleRow { action in
                    dismissChatKeyboard()
                    showAttachmentMenu = false
                    openConversationModule(action.handoff(preserving: vm.inputValue))
                }
                .padding(.horizontal, 24)
                .padding(.bottom, 8)

                XAgeChatInputBar(
                    vm: vm,
                    isRecording: speechInput.isRecording,
                    isUploading: reportUploadVM.uploading,
                    inputFocused: $inputFocused,
                    onMicTap: toggleSpeechInput,
                    onPlusTap: {
                        inputFocused = false
                        XAgeKeyboard.dismiss()
                        withAnimation(.spring(response: 0.22, dampingFraction: 0.9)) {
                            showAttachmentMenu.toggle()
                        }
                    }
                )
                .padding(.horizontal, 24)
                .padding(.bottom, 20)
            }

            if showAttachmentMenu {
                attachmentMenuOverlay
                    .transition(.opacity)
                    .zIndex(5)
            }
            ChatLifecycleProbe(
                sending: vm.sending,
                messageCount: vm.messages.count,
                latestRole: vm.messages.last?.role,
                inputFocused: inputFocused
            )
        }
        .task { await vm.loadConversations(showErrors: false) }
        .onChange(of: historyRequest) { _, _ in
            openHistorySheet()
        }
        .onChange(of: selectedSection) { _, section in
            guard section != .chat else { return }
            inputFocused = false
            showAttachmentMenu = false
        }
        .fullScreenCover(isPresented: $showCamera) {
            CameraImagePicker(
                onPick: { data, name in
                    preparePendingReportUpload(
                        files: [XAgeReportUploadFile(data: data, fileName: name)],
                        title: "确认数据上传",
                        source: "相机"
                    )
                },
                fileNamePrefix: "xage_report_camera"
            )
            .ignoresSafeArea()
        }
        .sheet(isPresented: $showPhotoLibrary) {
            MultiPhotoPicker(
                selectionLimit: recoveryAssetIndex == nil ? 9 : 1,
                fileNamePrefix: "xage_report_album",
                onPick: { photos in
                    preparePendingReportUpload(
                        files: photos.map { XAgeReportUploadFile(data: $0.data, fileName: $0.fileName) },
                        title: photos.count > 1 ? "确认上传 \(photos.count) 张照片" : "确认相册上传",
                        source: "相册"
                    )
                },
                onError: { message in
                    reportUploadVM.errorMessage = message
                }
            )
        }
        .sheet(isPresented: $showDocumentPicker) {
            DocumentPickerView(
                onPick: { data, fileName in
                    preparePendingReportUpload(
                        files: [XAgeReportUploadFile(data: data, fileName: fileName)],
                        title: "确认上传文件",
                        source: "文件"
                    )
                },
                onError: { message in
                    reportUploadVM.errorMessage = message
                }
            )
        }
        .sheet(item: $pendingUpload) { upload in
            XAgeReportUploadConfirmSheet(
                upload: upload,
                isUploading: reportUploadVM.uploading,
                onCancel: { pendingUpload = nil },
                onConfirm: {
                    pendingUpload = nil
                    uploadReports(upload.files, source: upload.source)
                }
            )
            .presentationDetents([.medium, .large])
            .presentationDragIndicator(.visible)
        }
        .sheet(isPresented: $vm.showHistory) {
            XAgeChatHistorySheet(vm: vm)
                .presentationDetents([.medium, .large])
                .presentationDragIndicator(.visible)
        }
        .sheet(item: $selectedAnalysis) { msg in
            XAgeAnalysisSheet(message: msg)
                .presentationDetents([.large])
                .presentationDragIndicator(.visible)
        }
        .sheet(item: $selectedEvidence) { msg in
            XAgeEvidenceSheet(message: msg)
                .presentationDetents([.large])
                .presentationDragIndicator(.visible)
        }
        .confirmationDialog(
            "检测到可能重复的报告",
            isPresented: Binding(
                get: { reportUploadVM.duplicatePrompt != nil },
                set: { if !$0 { reportUploadVM.deferDuplicateDecision() } }
            ),
            titleVisibility: .visible
        ) {
            Button("使用已有报告") {
                if let prompt = reportUploadVM.duplicatePrompt {
                    Task { await reportUploadVM.decideDuplicate(.useExisting, prompt: prompt) }
                }
            }
            Button("继续新建报告") {
                if let prompt = reportUploadVM.duplicatePrompt {
                    Task { await reportUploadVM.decideDuplicate(.continueNew, prompt: prompt) }
                }
            }
            Button("稍后处理", role: .cancel) {
                reportUploadVM.deferDuplicateDecision()
            }
        } message: {
            Text("系统只提示最相近的一份报告，不会自动覆盖。请选择是否复用已有报告。")
        }
        .alert("语音输入", isPresented: Binding(
            get: { speechInput.errorMessage != nil },
            set: { if !$0 { speechInput.errorMessage = nil } }
        )) {
            Button("确定", role: .cancel) {}
        } message: {
            Text(speechInput.errorMessage ?? "")
        }
        .alert("拍摄质量不足", isPresented: Binding(
            get: { uploadQualityWarning != nil },
            set: { if !$0 { uploadQualityWarning = nil } }
        )) {
            Button("重新拍摄") { uploadQualityWarning = nil; showCamera = true }
            Button("取消", role: .cancel) { uploadQualityWarning = nil }
        } message: {
            Text(uploadQualityWarning ?? "")
        }
        .alert("上传提示", isPresented: Binding(
            get: { reportUploadVM.infoMessage != nil },
            set: { if !$0 { reportUploadVM.infoMessage = nil } }
        )) {
            Button("知道了", role: .cancel) {}
        } message: {
            Text(reportUploadVM.infoMessage ?? "")
        }
        .alert(reportUploadVM.uploadRecovery == nil ? "上传失败" : "报告需要补传", isPresented: Binding(
            get: { reportUploadVM.errorMessage != nil },
            set: { if !$0 { reportUploadVM.errorMessage = nil } }
        )) {
            if let recovery = reportUploadVM.uploadRecovery,
               let index = recovery.nextAssetIndex {
                Button(recovery.actionCode == "upload_missing_pages" ? "拍照补第 \(index) 页" : "拍照替换第 \(index) 页") {
                    beginReportRecovery(assetIndex: index, useCamera: true)
                }
                Button(recovery.actionCode == "upload_missing_pages" ? "从相册补第 \(index) 页" : "从相册替换第 \(index) 页") {
                    beginReportRecovery(assetIndex: index, useCamera: false)
                }
                Button("重新上传整份", role: .destructive) {
                    reportUploadVM.abandonUploadRecovery()
                    recoveryAssetIndex = nil
                    showAttachmentMenu = true
                }
                Button("稍后处理", role: .cancel) {}
            } else if reportUploadVM.uploadRecovery != nil {
                Button("重新上传整份") {
                    reportUploadVM.abandonUploadRecovery()
                    recoveryAssetIndex = nil
                    showAttachmentMenu = true
                }
                Button("稍后处理", role: .cancel) {}
            } else {
                Button("确定", role: .cancel) {}
            }
        } message: {
            Text(reportUploadVM.errorMessage ?? "")
        }
        .alert("开启 AI 健康问答", isPresented: $vm.showAIConsentPrompt) {
            Button("暂不开启", role: .cancel) { vm.declineAIConsent() }
            Button("同意并继续") {
                dismissChatKeyboard()
                Task { await vm.grantAIConsentAndRetry() }
            }
        } message: {
            Text("小捷需要读取你已授权的健康档案和当前会话来生成个性化回答。只有你明确同意后才会继续处理这条消息。")
        }
        .alert("提示", isPresented: Binding(
            get: { vm.errorMessage != nil },
            set: { if !$0 { vm.errorMessage = nil } }
        )) {
            Button("确定", role: .cancel) {}
        } message: {
            Text(vm.errorMessage ?? "")
        }
        .onChange(of: authManager.accountScope) { _, scope in
            reportUploadVM.accountDidChange(to: scope)
        }
    }

    private func scrollToBottom(_ proxy: ScrollViewProxy) {
        ChatAutoScroll.toBottom(Self.bottomAnchorID, using: proxy)
    }
    private func dismissChatKeyboard() {
        inputFocused = false
        XAgeKeyboard.dismiss()
    }
    private func sendStarterPrompt(_ prompt: String) {
        dismissChatKeyboard()
        Task { await vm.sendText(prompt) }
    }
    private func retryMessage(id: String) {
        dismissChatKeyboard()
        Task { await vm.retryMessage(id: id) }
    }

    private var attachmentMenuOverlay: some View {
        ZStack(alignment: .bottomTrailing) {
            Color.black.opacity(0.001)
                .ignoresSafeArea()
                .onTapGesture {
                    withAnimation(.spring(response: 0.22, dampingFraction: 0.9)) {
                        showAttachmentMenu = false
                    }
                }

            XAgeAttachmentMenu(
                isNewChatEnabled: !vm.sending,
                onCamera: { presentAttachmentActionAfterMenu(.camera) },
                onDocument: { presentAttachmentActionAfterMenu(.documentPicker) },
                onPhotoLibrary: { presentAttachmentActionAfterMenu(.photoLibrary) },
                onNewChat: { presentAttachmentActionAfterMenu(.newChat) }
            )
            .padding(.trailing, 42)
            .padding(.bottom, 88)
        }
    }

    private enum XAgeAttachmentAction {
        case camera
        case documentPicker
        case photoLibrary
        case newChat
    }

    private func presentAttachmentActionAfterMenu(_ action: XAgeAttachmentAction) {
        showAttachmentMenu = false
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.35) {
            performAttachmentAction(action)
        }
    }

    private func performAttachmentAction(_ action: XAgeAttachmentAction) {
        switch action {
        case .camera:
            showCamera = true
        case .documentPicker:
            showDocumentPicker = true
        case .photoLibrary:
            showPhotoLibrary = true
        case .newChat:
            vm.newChat()
        }
    }

    private func openHistorySheet() {
        guard selectedSection == .chat else { return }
        inputFocused = false
        XAgeKeyboard.dismiss()
        showAttachmentMenu = false
        vm.showHistory = true
        Task { await vm.loadConversations(showErrors: false) }
    }

    private func toggleSpeechInput() {
        if speechInput.isRecording {
            speechInput.stop()
            return
        }
        inputFocused = false
        XAgeKeyboard.dismiss()
        speechInput.start { recognizedText in
            vm.inputValue = recognizedText
        }
    }

    private func preparePendingReportUpload(files: [XAgeReportUploadFile], title: String, source: String) {
        guard !files.isEmpty else { return }
        for file in files {
            if let warning = validateReportImageQuality(data: file.data, fileName: file.fileName) {
                uploadQualityWarning = "\(file.fileName)：\(warning)"
                return
            }
        }
        if let assetIndex = recoveryAssetIndex {
            guard let file = files.first, files.count == 1 else {
                reportUploadVM.errorMessage = "补传时每次只能选择一页。"
                return
            }
            recoveryAssetIndex = nil
            Task {
                _ = await reportUploadVM.recoverReportAsset(
                    input: HealthReportUploadAssetInput(
                        data: file.data,
                        fileName: file.fileName
                    ),
                    assetIndex: assetIndex
                )
            }
            return
        }
        let upload = XAgePendingReportUpload(title: title, source: source, files: files)
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.25) {
            pendingUpload = upload
        }
    }

    private func beginReportRecovery(assetIndex: Int, useCamera: Bool) {
        reportUploadVM.errorMessage = nil
        recoveryAssetIndex = assetIndex
        Task { @MainActor in
            await Task.yield()
            if useCamera {
                showCamera = true
            } else {
                showPhotoLibrary = true
            }
        }
    }

    private func uploadReports(_ files: [XAgeReportUploadFile], source: String) {
        guard !files.isEmpty else { return }
        inputFocused = false
        XAgeKeyboard.dismiss()
        Task {
            _ = await reportUploadVM.uploadReport(
                files: files.map {
                    HealthReportUploadAssetInput(data: $0.data, fileName: $0.fileName)
                },
                source: source,
                subjectUserID: authManager.authenticatedNumericUserID,
                accountScope: authManager.accountScope
            )
        }
    }

    private func validateReportImageQuality(data: Data, fileName: String) -> String? {
        let lower = fileName.lowercased()
        let isImage = [".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".tif", ".tiff"].contains { lower.hasSuffix($0) }
        guard isImage else { return nil }
        if data.count < 30 * 1024 {
            return "图片过小（小于 30KB），可能不是完整报告。请重新拍摄。"
        }
        if let img = UIImage(data: data) {
            let shortEdge = min(img.size.width, img.size.height) * img.scale
            if shortEdge < 600 {
                return "图片分辨率过低（短边 \(Int(shortEdge))px），识别可能失败。请重新拍摄。"
            }
        } else {
            return "未能读取图片数据，请重新拍摄或选择 PDF。"
        }
        return nil
    }
}

private struct XAgeConversationModuleRow: View {
    let onOpen: (XAgeConversationNavigationAction) -> Void

    var body: some View {
        ScrollView(.horizontal) {
            HStack(spacing: 8) {
                ForEach(XAgeConversationNavigationAction.available) { action in
                    Button { onOpen(action) } label: {
                        Label(action.title, systemImage: action.systemImage)
                            .font(.subheadline.weight(.semibold))
                            .foregroundStyle(Color(hex: "173F64"))
                            .padding(.horizontal, 14)
                            .frame(minHeight: 44)
                            .background(XAgeCapsuleFill())
                    }
                    .buttonStyle(.plain)
                    .fixedSize(horizontal: true, vertical: true)
                    .accessibilityLabel("打开\(action.title)模块")
                    .accessibilityHint("保留当前未发送内容并进入功能页面")
                    .accessibilityIdentifier("xage.chat.module.\(action.id)")
                }
            }
        }
        .scrollIndicators(.hidden)
    }
}

private struct XAgeChatThinkingCard: View {
    let currentHint: String
    let steps: [String]

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            XAgeAssistantOrb()
                .frame(width: 34, height: 34)

            VStack(alignment: .leading, spacing: 9) {
                HStack(spacing: 7) {
                    ChatProgressIndicator(tint: Color(hex: "18AFA7"))
                    Text(currentHint)
                        .font(.system(size: 13, weight: .bold))
                        .foregroundStyle(Color(hex: "173F64"))
                        .lineLimit(2)
                        .fixedSize(horizontal: false, vertical: true)
                }

                VStack(alignment: .leading, spacing: 6) {
                    ForEach(Array(steps.enumerated()), id: \.offset) { index, step in
                        HStack(alignment: .top, spacing: 7) {
                            Image(systemName: index == steps.count - 1 ? "ellipsis.circle.fill" : "checkmark.circle.fill")
                                .font(.system(size: 12, weight: .bold))
                                .foregroundStyle(index == steps.count - 1 ? Color(hex: "238AD6") : Color(hex: "20CDB1"))
                                .frame(width: 16, height: 16)
                            Text(step)
                                .font(.system(size: 12, weight: .medium))
                                .foregroundStyle(Color(hex: "5D7890"))
                                .lineLimit(2)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                }
            }
            .padding(14)
            .background(XAgeGlassCardBackground(cornerRadius: 22))

            Spacer(minLength: 0)
        }
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("xage.chat.thinking.card")
    }
}

private struct XAgeChatWelcome: View {
    @ObservedObject var vm: ChatViewModel
    let onSendPrompt: (String) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 16) {
                XAgeAssistantOrb()
                    .frame(width: 40, height: 40)
                VStack(alignment: .leading, spacing: 4) {
                    Text(xAgeWelcomeGreeting())
                        .font(.system(size: 25, weight: .bold))
                        .foregroundStyle(Color(hex: "111827"))
                        .lineLimit(1)
                        .minimumScaleFactor(0.85)
                    Text("小捷先帮你问清关键问题。")
                        .font(.system(size: 12))
                        .foregroundStyle(Color(hex: "637083"))
                        .lineLimit(1)
                }
            }

            Spacer()
                .frame(height: 50)

            Text("你可以这样问")
                .font(.system(size: 21, weight: .bold))
                .foregroundStyle(Color(hex: "111827"))
                .lineLimit(1)

            Spacer()
                .frame(height: 28)

            Button {
                onSendPrompt("帮我整理病史摘要")
            } label: {
                XAgeStarterRow(icon: "doc.text", title: "整理病史摘要", subtitle: "诊断、用药、过敏信息", primary: true)
            }
            .buttonStyle(.plain)
            .disabled(vm.sending)

            Spacer()
                .frame(height: 32)

            Button {
                onSendPrompt("帮我分析最近报告趋势")
            } label: {
                XAgeStarterRow(icon: "chart.bar", title: "分析报告趋势", subtitle: nil, primary: false)
            }
            .buttonStyle(.plain)
            .disabled(vm.sending)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

private struct XAgeStarterRow: View {
    let icon: String
    let title: String
    let subtitle: String?
    let primary: Bool

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: icon)
                .font(.system(size: 19, weight: .semibold))
                .foregroundStyle(Color.appPrimary)
                .frame(width: 36, height: 36)
                .background(
                    Circle()
                        .fill(Color(hex: "E7FAFF").opacity(0.46))
                        .overlay(Circle().stroke(.white.opacity(0.62), lineWidth: 1))
                )
            VStack(alignment: .leading, spacing: 3) {
                Text(title)
                    .font(.system(size: 18, weight: .bold))
                    .foregroundStyle(Color(hex: "111827"))
                    .lineLimit(1)
                if let subtitle {
                    Text(subtitle)
                        .font(.system(size: 12))
                        .foregroundStyle(Color(hex: "637083"))
                        .lineLimit(1)
                }
            }
            Spacer(minLength: 8)
            Image(systemName: "chevron.right")
                .font(.system(size: 20, weight: .bold))
                .foregroundStyle(Color(hex: "6F7F91").opacity(0.72))
                .frame(width: 24, height: 24)
        }
        .padding(.horizontal, 18)
        .frame(height: primary ? 84 : 66)
        .background(XAgeGlassCardBackground(cornerRadius: primary ? 34 : 33))
    }
}

private struct XAgeAssistantOrb: View {
    var body: some View {
        ZStack {
            Circle()
                .fill(.white.opacity(0.42))
                .shadow(color: Color(hex: "00C9A7").opacity(0.25), radius: 16, x: 0, y: 8)
            RoundedRectangle(cornerRadius: 9, style: .continuous)
                .fill(
                    LinearGradient(
                        colors: [Color(hex: "00C9A7"), Color(hex: "1565C0")],
                        startPoint: .topLeading,
                        endPoint: .bottomTrailing
                    )
                )
                .frame(width: 20, height: 20)
            Capsule()
                .fill(.white.opacity(0.26))
                .frame(width: 10, height: 28)
                .blur(radius: 1)
                .offset(x: 8, y: -4)
        }
    }
}

private struct XAgeChatBubble: View {
    let message: ChatMessageItem
    let onRetry: () -> Void
    let onAnalysis: () -> Void
    let onEvidence: () -> Void

    var body: some View {
        let isUser = message.role == "user"
        HStack {
            if isUser { Spacer(minLength: 44) }
            VStack(alignment: isUser ? .trailing : .leading, spacing: 8) {
                Group {
                    if isUser {
                        Text(message.content)
                    } else {
                        AccessibleMarkdownText(text: message.content)
                            .textSelection(.enabled)
                    }
                }
                    .font(.system(size: 15, weight: isUser ? .semibold : .regular))
                    .foregroundStyle(isUser ? .white : Color(hex: "244E6D"))
                    .lineSpacing(2)
                    .padding(.horizontal, isUser ? 15 : 15)
                    .padding(.vertical, isUser ? 11 : 14)
                    .background(
                        RoundedRectangle(cornerRadius: isUser ? 24 : 20, style: .continuous)
                            .fill(isUser ? AnyShapeStyle(LinearGradient(colors: [Color(hex: "238AD6"), Color(hex: "20CDB1")], startPoint: .topLeading, endPoint: .bottomTrailing)) : AnyShapeStyle(.white.opacity(0.56)))
                            .overlay(
                                RoundedRectangle(cornerRadius: isUser ? 24 : 20, style: .continuous)
                                    .stroke(.white.opacity(0.72), lineWidth: 1)
                            )
                    )
                    .fixedSize(horizontal: false, vertical: true)

                if let status = message.status {
                    HStack(spacing: 8) {
                        Text(status.rawValue)
                            .font(.system(size: 11, weight: .medium))
                            .foregroundStyle(isUser ? .white.opacity(0.82) : Color(hex: "6C8194"))
                        if status == .failed {
                            Button("重试", action: onRetry)
                                .font(.system(size: 11, weight: .bold))
                        }
                    }
                }

                if !isUser {
                    HStack(spacing: 8) {
                        if message.hasDistinctAnalysis {
                            CapsuleButton(title: "查看分析", action: onAnalysis)
                        }
                        if !message.relevantCitations.isEmpty {
                            CapsuleButton(title: "证据展示", action: onEvidence)
                        }
                    }
                }
            }
            if !isUser { Spacer(minLength: 44) }
        }
    }

}

private struct XAgeChatInputBar: View {
    @ObservedObject var vm: ChatViewModel
    let isRecording: Bool
    let isUploading: Bool
    var inputFocused: FocusState<Bool>.Binding
    let onMicTap: () -> Void
    let onPlusTap: () -> Void

    var body: some View {
        HStack(alignment: .bottom, spacing: 8) {
            Button(action: onMicTap) {
                Image(systemName: isRecording ? "stop.circle.fill" : "mic.fill")
                    .frame(width: 32, height: 32)
            }
            .frame(width: 44, height: 44)
            .contentShape(Rectangle())
            .buttonStyle(.plain)
            .foregroundStyle(isRecording ? Color(hex: "12B59C") : Color(hex: "172033"))
            .accessibilityIdentifier("xage.chat.mic")
            .accessibilityLabel(isRecording ? "停止语音输入" : "语音输入")

            TextField("输入或长按说话", text: $vm.inputValue, axis: .vertical)
                .font(.system(size: 15))
                .textFieldStyle(.plain)
                .lineLimit(1...5)
                .padding(.vertical, 11)
                .frame(minHeight: 44)
                .focused(inputFocused)
                .accessibilityIdentifier("xage.chat.input")

            Button(action: onPlusTap) {
                Image(systemName: "plus")
                    .font(.system(size: 19, weight: .semibold))
                    .frame(width: 32, height: 32)
                    .background(
                        Circle()
                            .fill(.white.opacity(0.58))
                            .overlay(Circle().stroke(.white.opacity(0.7), lineWidth: 1))
                    )
            }
            .frame(width: 44, height: 44)
            .contentShape(Rectangle())
            .buttonStyle(.plain)
            .foregroundStyle(Color(hex: "172033"))
            .disabled(isUploading)
            .accessibilityIdentifier("xage.chat.plus")
            .accessibilityLabel("添加内容")

            Button {
                sendCurrentInput()
            } label: {
                Image(systemName: "paperplane.fill")
                    .font(.system(size: 17, weight: .bold))
                    .offset(x: -1, y: 1)
                    .frame(width: 36, height: 36)
                    .background(
                        Circle()
                            .fill(LinearGradient(colors: [Color(hex: "228DD8"), Color(hex: "1DC8AE")], startPoint: .topLeading, endPoint: .bottomTrailing))
                    )
                    .foregroundStyle(.white)
            }
            .frame(width: 44, height: 44)
            .contentShape(Rectangle())
            .buttonStyle(.plain)
            .disabled(vm.inputValue.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || vm.sending)
            .accessibilityIdentifier("xage.chat.send")
            .accessibilityLabel("发送")
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 7)
        .frame(minHeight: 58)
        .background(XAgeGlassCardBackground(cornerRadius: 29))
    }

    private func sendCurrentInput() {
        guard let text = vm.consumeInputForSending() else { return }
        inputFocused.wrappedValue = false
        XAgeKeyboard.dismiss()
        Task { @MainActor in
            await Task.yield()
            if vm.inputValue.trimmingCharacters(in: .whitespacesAndNewlines) == text {
                vm.inputValue = ""
            }
            await vm.sendText(text)
        }
    }
}

private struct XAgeAttachmentMenu: View {
    let isNewChatEnabled: Bool
    let onCamera: () -> Void
    let onDocument: () -> Void
    let onPhotoLibrary: () -> Void
    let onNewChat: () -> Void

    var body: some View {
        VStack(spacing: 8) {
            Text("添加内容")
                .font(.system(size: 13, weight: .bold))
                .foregroundStyle(Color(hex: "173F64"))
                .frame(maxWidth: .infinity)
                .padding(.bottom, 2)

            menuButton(
                title: "拍照采集报告",
                icon: "camera.fill",
                identifier: "xage.chat.attachment.camera",
                action: onCamera
            )
            menuButton(
                title: "数据上传 PDF / 图片",
                icon: "doc.badge.plus",
                identifier: "xage.chat.attachment.documents",
                action: onDocument
            )
            menuButton(
                title: "从相册上传报告",
                icon: "photo.on.rectangle.angled",
                identifier: "xage.chat.attachment.photos",
                action: onPhotoLibrary
            )
            menuButton(
                title: "新对话",
                icon: "plus.message.fill",
                identifier: "xage.chat.attachment.new",
                isEnabled: isNewChatEnabled,
                action: onNewChat
            )
        }
        .padding(12)
        .frame(width: 220)
        .background(XAgeGlassCardBackground(cornerRadius: 26))
        .shadow(color: Color(hex: "7CCAF5").opacity(0.22), radius: 22, x: 0, y: 10)
        .accessibilityElement(children: .contain)
    }

    private func menuButton(
        title: String,
        icon: String,
        identifier: String,
        isEnabled: Bool = true,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            HStack(spacing: 9) {
                Image(systemName: icon)
                    .font(.system(size: 13, weight: .bold))
                    .foregroundStyle(Color(hex: "237FC4"))
                    .frame(width: 22, height: 22)
                Text(title)
                    .font(.system(size: 14, weight: .bold))
                    .foregroundStyle(Color(hex: "173F64"))
                    .lineLimit(1)
                    .minimumScaleFactor(0.82)
                Spacer(minLength: 0)
            }
            .padding(.horizontal, 12)
            .frame(height: 44)
            .background(XAgeCapsuleFill())
        }
        .buttonStyle(.plain)
        .disabled(!isEnabled)
        .opacity(isEnabled ? 1 : 0.45)
        .accessibilityIdentifier(identifier)
    }
}

private struct XAgeChatHistorySheet: View {
    @ObservedObject var vm: ChatViewModel
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        ZStack {
            XAgeLiquidBackground()
                .ignoresSafeArea()

            VStack(alignment: .leading, spacing: 18) {
                HStack {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("历史对话")
                            .font(.system(size: 24, weight: .bold))
                            .foregroundStyle(Color(hex: "173F64"))
                        Text("继续之前的健康问答")
                            .font(.system(size: 13, weight: .medium))
                            .foregroundStyle(Color(hex: "5D7890"))
                    }

                    Spacer()

                    Button {
                        vm.showHistory = false
                        dismiss()
                    } label: {
                        Image(systemName: "xmark")
                            .font(.system(size: 14, weight: .bold))
                            .foregroundStyle(Color(hex: "2A79BB"))
                            .frame(width: 36, height: 36)
                            .background(XAgeCapsuleFill())
                    }
                    .frame(width: 44, height: 44)
                    .contentShape(Rectangle())
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("xage.chat.history.close")
                    .accessibilityLabel("关闭历史对话")
                }

                ScrollView {
                    LazyVStack(spacing: 12) {
                        if vm.conversations.isEmpty {
                            emptyState
                        } else {
                            ForEach(vm.conversations) { conversation in
                                Button {
                                    Task {
                                        await vm.loadConversation(id: conversation.id)
                                        vm.showHistory = false
                                        dismiss()
                                    }
                                } label: {
                                    conversationRow(conversation)
                                }
                                .buttonStyle(.plain)
                                .accessibilityIdentifier("xage.chat.history.row.\(conversation.id)")
                            }

                            if vm.hasMoreConversations {
                                Button {
                                    Task { await vm.loadMoreConversations() }
                                } label: {
                                    HStack(spacing: 8) {
                                        Image(systemName: "arrow.down.circle.fill")
                                            .font(.system(size: 15, weight: .bold))
                                        Text("加载更多")
                                            .font(.system(size: 15, weight: .bold))
                                    }
                                    .foregroundStyle(Color(hex: "237FC4"))
                                    .frame(maxWidth: .infinity)
                                    .frame(height: 48)
                                    .background(XAgeCapsuleFill())
                                }
                                .buttonStyle(.plain)
                                .accessibilityIdentifier("xage.chat.history.more")
                            }
                        }
                    }
                    .padding(.bottom, 24)
                }
                .scrollIndicators(.hidden)
            }
            .padding(.horizontal, 24)
            .padding(.top, 24)
        }
        .accessibilityIdentifier("xage.chat.history.sheet")
    }

    private var emptyState: some View {
        VStack(spacing: 12) {
            ZStack {
                Circle()
                    .fill(Color(hex: "6CD8DA").opacity(0.22))
                    .frame(width: 54, height: 54)
                Image(systemName: "clock.arrow.circlepath")
                    .font(.system(size: 24, weight: .bold))
                    .foregroundStyle(Color(hex: "237FC4"))
            }

            Text("暂无历史对话")
                .font(.system(size: 18, weight: .bold))
                .foregroundStyle(Color(hex: "173F64"))

            Text("登录并完成问答后，会在这里继续查看历史记录。")
                .font(.system(size: 13))
                .foregroundStyle(Color(hex: "5D7890"))
                .multilineTextAlignment(.center)
                .lineSpacing(3)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 34)
        .padding(.horizontal, 18)
        .background(XAgeGlassCardBackground(cornerRadius: 26))
    }

    private func conversationRow(_ conversation: ChatConversation) -> some View {
        HStack(spacing: 12) {
            ZStack {
                Circle()
                    .fill(Color(hex: "25C8BE").opacity(0.18))
                    .frame(width: 42, height: 42)
                Image(systemName: "bubble.left.and.bubble.right.fill")
                    .font(.system(size: 17, weight: .bold))
                    .foregroundStyle(Color(hex: "159D8F"))
            }

            VStack(alignment: .leading, spacing: 6) {
                Text(conversation.title ?? "健康问答")
                    .font(.system(size: 16, weight: .bold))
                    .foregroundStyle(Color(hex: "173F64"))
                    .lineLimit(2)

                HStack(spacing: 8) {
                    Text("\(conversation.message_count ?? 0) 条消息")
                    if let timestamp = conversation.updated_at ?? conversation.created_at {
                        Text("·")
                        Text(Self.formatTimestamp(timestamp))
                    }
                }
                .font(.system(size: 12, weight: .medium))
                .foregroundStyle(Color(hex: "6F879B"))
            }

            Spacer(minLength: 8)

            Image(systemName: "chevron.right")
                .font(.system(size: 13, weight: .bold))
                .foregroundStyle(Color(hex: "8BA6BA"))
        }
        .padding(16)
        .background(XAgeGlassCardBackground(cornerRadius: 24))
    }

    private static func formatTimestamp(_ iso: String) -> String {
        let fractional = ISO8601DateFormatter()
        fractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        guard let date = fractional.date(from: iso) ?? ISO8601DateFormatter().date(from: iso) else {
            return String(iso.prefix(10))
        }

        let diff = Date().timeIntervalSince(date)
        if diff < 60 { return "刚刚" }
        if diff < 3600 { return "\(Int(diff / 60))分钟前" }
        if diff < 86400 { return "\(Int(diff / 3600))小时前" }
        if diff < 86400 * 7 { return "\(Int(diff / 86400))天前" }

        let formatter = DateFormatter()
        formatter.dateFormat = "MM-dd HH:mm"
        return formatter.string(from: date)
    }
}

struct XAgeChatUploadStatusCard: View {
    let uploading: Bool
    let title: String
    let subtitle: String

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            ZStack {
                Circle()
                    .fill(.white.opacity(0.52))
                    .overlay(Circle().stroke(.white.opacity(0.7), lineWidth: 1))
                    .frame(width: 34, height: 34)
                if uploading {
                    ChatProgressIndicator(tint: Color(hex: "159D8F"))
                } else {
                    Image(systemName: "sparkles")
                        .font(.system(size: 15, weight: .bold))
                        .foregroundStyle(Color(hex: "159D8F"))
                }
            }

            VStack(alignment: .leading, spacing: 4) {
                Text(title)
                    .font(.system(size: 14, weight: .bold))
                    .foregroundStyle(Color(hex: "173F64"))
                    .lineLimit(2)
                Text(subtitle)
                    .font(.system(size: 12))
                    .foregroundStyle(Color(hex: "5D7890"))
                    .lineLimit(3)
            }
            Spacer(minLength: 0)
        }
        .padding(14)
        .background(XAgeGlassCardBackground(cornerRadius: 22))
        .accessibilityIdentifier("xage.chat.upload.status")
    }
}

@MainActor
private final class XAgeSpeechInputManager: NSObject, ObservableObject {
    @Published var isRecording = false
    @Published var errorMessage: String?

    private let recognizer = SFSpeechRecognizer(locale: Locale(identifier: "zh-CN"))
    private let audioEngine = AVAudioEngine()
    private var recognitionRequest: SFSpeechAudioBufferRecognitionRequest?
    private var recognitionTask: SFSpeechRecognitionTask?
    private var onResult: ((String) -> Void)?

    func start(onResult: @escaping (String) -> Void) {
        guard !isRecording else { return }
        self.onResult = onResult
        SFSpeechRecognizer.requestAuthorization { [weak self] status in
            DispatchQueue.main.async {
                guard let self else { return }
                guard status == .authorized else {
                    self.errorMessage = "请在系统设置中允许语音识别权限。"
                    return
                }
                self.requestRecordPermission()
            }
        }
    }

    private func requestRecordPermission() {
        if #available(iOS 17.0, *) {
            AVAudioApplication.requestRecordPermission { [weak self] allowed in
                Task { @MainActor in
                    self?.handleRecordPermission(allowed)
                }
            }
        } else {
            AVAudioSession.sharedInstance().requestRecordPermission { [weak self] allowed in
                DispatchQueue.main.async {
                    self?.handleRecordPermission(allowed)
                }
            }
        }
    }

    private func handleRecordPermission(_ allowed: Bool) {
        guard allowed else {
            errorMessage = "请在系统设置中允许麦克风权限。"
            return
        }
        startRecording()
    }

    func stop() {
        stopRecording(cancelTask: true)
    }

    private func startRecording() {
        guard recognizer?.isAvailable == true else {
            errorMessage = "当前设备语音识别暂不可用。"
            return
        }

#if targetEnvironment(simulator)
        errorMessage = "模拟器无法进行真实语音输入，请在真机上使用麦克风。"
        return
#else
        recognitionTask?.cancel()
        recognitionTask = nil
        recognitionRequest = SFSpeechAudioBufferRecognitionRequest()
        guard let recognitionRequest else { return }
        recognitionRequest.shouldReportPartialResults = true

        let session = AVAudioSession.sharedInstance()
        do {
            try session.setCategory(.record, mode: .measurement, options: .duckOthers)
            try session.setActive(true, options: .notifyOthersOnDeactivation)

            let inputNode = audioEngine.inputNode
            inputNode.removeTap(onBus: 0)
            let format = inputNode.outputFormat(forBus: 0)
            inputNode.installTap(onBus: 0, bufferSize: 1024, format: format) { [weak recognitionRequest] buffer, _ in
                recognitionRequest?.append(buffer)
            }

            audioEngine.prepare()
            try audioEngine.start()
            isRecording = true

            recognitionTask = recognizer?.recognitionTask(with: recognitionRequest) { [weak self] result, error in
                DispatchQueue.main.async {
                    guard let self else { return }
                    if let result {
                        self.onResult?(result.bestTranscription.formattedString)
                    }
                    if error != nil || result?.isFinal == true {
                        self.stopRecording(cancelTask: false)
                    }
                }
            }
        } catch {
            errorMessage = "语音输入启动失败：\(error.localizedDescription)"
            stopRecording(cancelTask: true)
        }
#endif
    }

    private func stopRecording(cancelTask: Bool) {
        if audioEngine.isRunning {
            audioEngine.stop()
            audioEngine.inputNode.removeTap(onBus: 0)
        }
        recognitionRequest?.endAudio()
        if cancelTask {
            recognitionTask?.cancel()
        }
        recognitionRequest = nil
        recognitionTask = nil
        isRecording = false
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }
}

private struct XAgeAnalysisSheet: View {
    let message: ChatMessageItem
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        ZStack {
            XAgeLiquidBackground().ignoresSafeArea()
            VStack(alignment: .leading, spacing: 14) {
                HStack {
                    Text("详细分析")
                        .font(.system(size: 24, weight: .bold))
                        .foregroundStyle(Color(hex: "123E67"))
                    Spacer()
                    Button {
                        dismiss()
                    } label: {
                        Image(systemName: "xmark")
                            .font(.system(size: 13, weight: .bold))
                            .foregroundStyle(Color(hex: "1268BD"))
                            .frame(width: 34, height: 34)
                            .background(XAgeCapsuleFill())
                    }
                    .frame(width: 44, height: 44)
                    .contentShape(Rectangle())
                    .accessibilityLabel("关闭")
                }
                ScrollView {
                    MarkdownTextView(text: ChatViewModel.cleanAnalysis(message.analysis) ?? "当前回答没有额外分析。")
                        .padding(16)
                        .background(XAgeGlassCardBackground(cornerRadius: 22))
                }
                .scrollIndicators(.hidden)
            }
            .padding(24)
        }
    }
}

private struct XAgeEvidenceSheet: View {
    let message: ChatMessageItem
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        ZStack {
            XAgeLiquidBackground().ignoresSafeArea()
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    HStack {
                        Text("证据展示")
                            .font(.system(size: 24, weight: .bold))
                            .foregroundStyle(Color(hex: "123E67"))
                        Spacer()
                        Button {
                            dismiss()
                        } label: {
                            Image(systemName: "xmark")
                                .font(.system(size: 13, weight: .bold))
                                .foregroundStyle(Color(hex: "1268BD"))
                                .frame(width: 34, height: 34)
                                .background(XAgeCapsuleFill())
                        }
                        .frame(width: 44, height: 44)
                        .contentShape(Rectangle())
                        .accessibilityLabel("关闭")
                    }
                    ForEach(message.relevantCitationReferences) { reference in
                        VStack(alignment: .leading, spacing: 8) {
                            HStack {
                                Text("[\(reference.number)]")
                                    .font(.system(size: 13, weight: .bold))
                                    .foregroundStyle(Color.appPrimary)
                                Text(reference.citation.evidence_level)
                                    .font(.system(size: 12, weight: .bold))
                                    .foregroundStyle(Color.appAccent)
                                    .padding(.horizontal, 8)
                                    .padding(.vertical, 3)
                                    .background(Capsule().fill(Color.appAccent.opacity(0.12)))
                                Spacer()
                                Text(reference.citation.confidence)
                                    .font(.system(size: 12, weight: .medium))
                                    .foregroundStyle(Color(hex: "6C8194"))
                            }
                            Text(reference.citation.claim_text)
                                .font(.system(size: 14))
                                .foregroundStyle(Color(hex: "244E6D"))

                            Text("适用人群：\(populationText(for: reference.citation))")
                                .font(.system(size: 12, weight: .medium))
                                .foregroundStyle(Color(hex: "496A83"))
                                .lineSpacing(2)
                                .fixedSize(horizontal: false, vertical: true)
                                .padding(.horizontal, 10)
                                .padding(.vertical, 8)
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .background(XAgeCapsuleFill())

                            let studyMetadata = studyMetadata(for: reference.citation)
                            if !studyMetadata.isEmpty {
                                Text(studyMetadata.joined(separator: " · "))
                                    .font(.system(size: 12, weight: .medium))
                                    .foregroundStyle(Color(hex: "5D7890"))
                                    .lineSpacing(2)
                                    .fixedSize(horizontal: false, vertical: true)
                            }

                            if let shortReference = nonEmpty(reference.citation.short_ref) {
                                Text(shortReference)
                                    .font(.system(size: 12))
                                    .foregroundStyle(Color(hex: "6C8194"))
                                    .fixedSize(horizontal: false, vertical: true)
                            }
                        }
                        .padding(14)
                        .background(XAgeGlassCardBackground(cornerRadius: 20))
                    }
                    if message.relevantCitations.isEmpty {
                        Text("当前回答暂无文献引用。")
                            .font(.system(size: 14))
                            .foregroundStyle(Color(hex: "6C8194"))
                            .padding(16)
                            .background(XAgeGlassCardBackground(cornerRadius: 20))
                    }
                }
                .padding(24)
            }
        }
    }

    private func populationText(for citation: Citation) -> String {
        nonEmpty(citation.population) ?? "文献未报告，需谨慎外推"
    }

    private func studyMetadata(for citation: Citation) -> [String] {
        var values: [String] = []
        if let studyDesign = citation.studyDesignDisplayText {
            values.append("研究类型：\(studyDesign)")
        }
        if let sampleSize = citation.sample_size, sampleSize > 0 {
            values.append("样本量：\(sampleSize)")
        }
        if let year = citation.year, year > 0 {
            values.append("年份：\(year)")
        }
        return values
    }

    private func nonEmpty(_ value: String?) -> String? {
        let normalized = value?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return normalized.isEmpty ? nil : normalized
    }
}
