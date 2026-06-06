import SwiftUI
import UIKit
import AVFoundation
import Speech

/// AI 聊天页面 — 对应小程序 pages/chat/chat
struct ChatView: View {
    @StateObject private var vm = ChatViewModel()
    @StateObject private var speechInput = SpeechInputManager()
    @State private var expandedIDs: Set<String> = []
    var isEmbedded: Bool = false
    var initialPrompt: String? = nil
    var onInitialPromptConsumed: () -> Void = {}

    var body: some View {
        let content = chatContent
        if isEmbedded {
            content
        } else {
            NavigationStack { content }
        }
    }

    private var chatContent: some View {
        VStack(spacing: 0) {
            // 消息列表
            messageList

            // 推荐问题
            if let lastAssistant = vm.messages.last(where: { $0.role == "assistant" }),
               let followups = lastAssistant.followups, !followups.isEmpty {
                followupsBar(followups)
            }

            // 输入栏
            inputBar
        }
        .navigationTitle(vm.isViewingHistory ? "历史对话" : "助手小捷")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .navigationBarLeading) {
                if vm.isViewingHistory {
                    Button {
                        vm.backToCurrentChat()
                    } label: {
                        HStack(spacing: 4) {
                            Image(systemName: "chevron.left")
                            Text("当前对话")
                        }
                        .font(.subheadline)
                    }
                } else {
                    Button("+ 新对话") { vm.newChat() }
                        .font(.subheadline)
                }
            }
            ToolbarItem(placement: .navigationBarTrailing) {
                Button { vm.showHistory.toggle() } label: {
                    Label("历史", systemImage: "clock.arrow.circlepath")
                }
                .font(.subheadline)
            }
        }
        .sheet(isPresented: $vm.showHistory) {
            historySheet
        }
        .task {
            await vm.loadConversations()
            await handleInitialPrompt()
        }
        .onChange(of: initialPrompt ?? "") { _, _ in
            Task { await handleInitialPrompt() }
        }
        .alert("提示", isPresented: Binding(
            get: { vm.errorMessage != nil },
            set: { if !$0 { vm.errorMessage = nil } }
        )) {
            Button("确定", role: .cancel) {}
        } message: {
            Text(vm.errorMessage ?? "")
        }
        .alert("语音输入", isPresented: Binding(
            get: { speechInput.errorMessage != nil },
            set: { if !$0 { speechInput.errorMessage = nil } }
        )) {
            Button("知道了", role: .cancel) {}
        } message: {
            Text(speechInput.errorMessage ?? "")
        }
    }

    private func handleInitialPrompt() async {
        guard let prompt = initialPrompt?.trimmingCharacters(in: .whitespacesAndNewlines),
              !prompt.isEmpty else { return }
        await vm.startPlanConversation(prompt: prompt)
        await MainActor.run { onInitialPromptConsumed() }
    }

    // MARK: - 消息列表

    private var messageList: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(spacing: 14) {
                    if vm.messages.isEmpty {
                        welcomeMessage
                    }

                    ForEach(vm.messages) { msg in
                        messageBubble(msg)
                    }

                    if vm.sending {
                        HStack {
                            Text(vm.thinkingHint.isEmpty ? "正在思考…" : vm.thinkingHint)
                                .font(.subheadline)
                                .foregroundColor(.appMuted)
                                .padding(12)
                                .background(Color.appCardBg)
                                .cornerRadius(12)
                            Spacer()
                        }
                        .padding(.horizontal, 16)
                    }

                    Color.clear.frame(height: 1).id("bottom")
                }
                .padding(.vertical, 12)
            }
            .scrollDismissesKeyboard(.interactively)
            .simultaneousGesture(TapGesture().onEnded { Self.hideKeyboard() })
            .background(
                Color.clear
                    .contentShape(Rectangle())
                    .onTapGesture { Self.hideKeyboard() }
            )
            .onChange(of: vm.messages.count) { _, _ in
                withAnimation {
                    proxy.scrollTo("bottom", anchor: .bottom)
                }
            }
        }
    }

    private static func hideKeyboard() {
        UIApplication.shared.sendAction(
            #selector(UIResponder.resignFirstResponder), to: nil, from: nil, for: nil
        )
    }

    private var welcomeMessage: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack(spacing: 12) {
                AssistantAvatar(size: 58, bordered: true)
                VStack(alignment: .leading, spacing: 5) {
                    Text("助手小捷")
                        .font(.title3.bold())
                    Text("把血糖、膳食、体检和病史连起来，先给你下一步。")
                        .font(.subheadline)
                        .foregroundColor(.appMuted)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: 0)
            }

            VStack(alignment: .leading, spacing: 10) {
                Text("常用任务")
                    .font(.caption.bold())
                    .foregroundColor(.appMuted)
                    .padding(.horizontal, 2)

                NavigationLink(destination: PatientHistoryView()) {
                    assistantActionRow(
                        icon: "stethoscope",
                        title: "整理病史摘要",
                        subtitle: "诊断、用药、过敏和异常检查分区核对",
                        tint: .appPrimary,
                        trailing: "整理"
                    )
                }
                .buttonStyle(.plain)

                Button {
                    sendStarterPrompt("今天血糖波动怎么解读？")
                } label: {
                    assistantActionRow(
                        icon: "waveform.path.ecg",
                        title: "解读血糖波动",
                        subtitle: "结合 TIR、平均值和异常时段说明",
                        tint: .appSuccess,
                        trailing: "提问"
                    )
                }
                .buttonStyle(.plain)
                .disabled(vm.sending)

                Button {
                    sendStarterPrompt("帮我做一个低负担饮食建议")
                } label: {
                    assistantActionRow(
                        icon: "fork.knife",
                        title: "低负担饮食建议",
                        subtitle: "按当前健康资料给出下一餐选择",
                        tint: .appWarning,
                        trailing: "提问"
                    )
                }
                .buttonStyle(.plain)
                .disabled(vm.sending)
            }
        }
        .padding(.horizontal, 20)
        .padding(.top, 28)
        .padding(.bottom, 24)
        .accessibilityElement(children: .contain)
    }

    private func assistantActionRow(
        icon: String,
        title: String,
        subtitle: String,
        tint: Color,
        trailing: String
    ) -> some View {
        HStack(spacing: 12) {
            Image(systemName: icon)
                .font(.system(size: 18, weight: .semibold))
                .foregroundColor(tint)
                .frame(width: 38, height: 38)
                .background(tint.opacity(0.12))
                .clipShape(RoundedRectangle(cornerRadius: 10))
            VStack(alignment: .leading, spacing: 3) {
                Text(title)
                    .font(.subheadline.bold())
                    .foregroundColor(.appText)
                Text(subtitle)
                    .font(.caption)
                    .foregroundColor(.appMuted)
                    .lineLimit(2)
                    .multilineTextAlignment(.leading)
            }
            Spacer(minLength: 8)
            Text(trailing)
                .font(.caption.bold())
                .foregroundColor(tint)
                .padding(.horizontal, 9)
                .padding(.vertical, 5)
                .background(tint.opacity(0.1))
                .clipShape(Capsule())
        }
        .padding(12)
        .background(Color.appCardBg)
        .overlay(
            RoundedRectangle(cornerRadius: 14)
                .stroke(Color.appStroke, lineWidth: 1)
        )
        .clipShape(RoundedRectangle(cornerRadius: 14))
    }

    private func sendStarterPrompt(_ prompt: String) {
        vm.inputValue = prompt
        Task { await vm.sendMessage() }
    }

    private func messageBubble(_ msg: ChatMessageItem) -> some View {
        let isUser = msg.role == "user"
        let isExpanded = expandedIDs.contains(msg.id)

        return HStack(alignment: .bottom, spacing: 8) {
            if !isUser {
                AssistantAvatar(size: 30, bordered: true)
                    .padding(.bottom, 2)
            }
            if isUser { Spacer(minLength: 48) }
            VStack(alignment: .leading, spacing: 6) {
                Text(msg.content)
                    .font(.subheadline)
                    .lineSpacing(3)
                    .textSelection(.enabled)

                if isUser, let status = msg.status {
                    HStack(spacing: 8) {
                        Text(status.rawValue)
                            .font(.caption2)
                            .foregroundColor(.white.opacity(status == .failed ? 0.95 : 0.75))
                        if status == .failed {
                            Button("重试") {
                                Task { await vm.retryMessage(id: msg.id) }
                            }
                            .font(.caption2.bold())
                            .foregroundColor(.white)
                        }
                    }
                    .accessibilityLabel(status.rawValue)
                }

                // 展开/收起详细分析
                if !isUser, let analysis = msg.analysis, !analysis.isEmpty {
                    Button {
                        withAnimation(.easeInOut(duration: 0.25)) {
                            if isExpanded { expandedIDs.remove(msg.id) }
                            else { expandedIDs.insert(msg.id) }
                        }
                    } label: {
                        HStack(spacing: 4) {
                            Text(isExpanded ? "收起分析" : "查看详细分析")
                            Image(systemName: isExpanded ? "chevron.up" : "chevron.down")
                        }
                        .font(.caption)
                        .foregroundColor(.appPrimary)
                    }
                    .buttonStyle(.plain)

                    if isExpanded {
                        Divider()
                        Text(analysis)
                            .font(.caption)
                            .foregroundColor(.appMuted)
                            .transition(.opacity.combined(with: .move(edge: .top)))
                    }
                }

                // 文献引用（小字脚注 + 点击展开）
                if !isUser && !msg.citations.isEmpty {
                    Divider()
                    CitationFootnoteView(citations: msg.citations)
                }

                if vm.shouldOfferSavePlan(for: msg) {
                    Button {
                        Task { await vm.saveAsHealthPlan(message: msg) }
                    } label: {
                        HStack(spacing: 6) {
                            if vm.planSavingMessageID == msg.id {
                                ProgressView()
                                    .controlSize(.small)
                                    .tint(.appPrimary)
                            } else {
                                Image(systemName: "list.clipboard")
                            }
                            Text(vm.planSavingMessageID == msg.id ? "保存中..." : "保存为健康计划")
                        }
                        .font(.caption.bold())
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 8)
                        .background(Color.appPrimary.opacity(0.1))
                        .foregroundColor(.appPrimary)
                        .cornerRadius(8)
                    }
                    .buttonStyle(.plain)
                    .disabled(vm.planSavingMessageID == msg.id)
                }
            }
            .padding(.horizontal, 13)
            .padding(.vertical, 11)
            .frame(maxWidth: 300, alignment: .leading)
            .background(
                RoundedRectangle(cornerRadius: 18, style: .continuous)
                    .fill(isUser ? Color.appPrimary : Color.appCardBg)
            )
            .overlay(
                RoundedRectangle(cornerRadius: 18, style: .continuous)
                    .stroke(isUser ? Color.clear : Color.appStroke, lineWidth: 1)
            )
            .foregroundColor(isUser ? .white : .appText)
            .shadow(color: .black.opacity(isUser ? 0.03 : 0.04), radius: 8, x: 0, y: 3)
            if !isUser { Spacer(minLength: 48) }
        }
        .padding(.horizontal, 14)
    }

    // MARK: - 快捷回复

    private func followupsBar(_ items: [String]) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 4) {
                Image(systemName: "bubble.left.and.text.bubble.right")
                    .font(.caption2)
                    .foregroundColor(.appMuted)
                Text("你可以这样问：")
                    .font(.caption2)
                    .foregroundColor(.appMuted)
            }
            .padding(.leading, 16)

            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 8) {
                    ForEach(items, id: \.self) { q in
                        Button {
                            vm.inputValue = q
                            Task { await vm.sendMessage() }
                        } label: {
                            HStack(spacing: 4) {
                                Image(systemName: "arrowshape.turn.up.right.fill")
                                    .font(.system(size: 9))
                                Text(q)
                                    .font(.caption)
                                    .lineLimit(1)
                            }
                            .padding(.horizontal, 12)
                            .padding(.vertical, 7)
                            .background(Color.appPrimary.opacity(0.08))
                            .foregroundColor(.appPrimary)
                            .cornerRadius(16)
                            .overlay(
                                RoundedRectangle(cornerRadius: 16)
                                    .stroke(Color.appPrimary.opacity(0.2), lineWidth: 0.5)
                            )
                        }
                    }
                }
                .padding(.horizontal, 16)
            }
        }
        .padding(.vertical, 6)
    }

    // MARK: - 输入栏

    private var inputBar: some View {
        let canSend = !vm.inputValue.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && !vm.sending
        return HStack(alignment: .bottom, spacing: 8) {
            CompositionSafeTextView(
                text: $vm.inputValue,
                placeholder: "问血糖、饮食、病史...",
                isEnabled: !vm.sending,
                onSubmit: { Task { await vm.sendMessage() } }
            )
            .frame(minHeight: 42, maxHeight: 104)

            Button {
                if speechInput.isRecording {
                    speechInput.stop()
                } else {
                    Self.hideKeyboard()
                    speechInput.start { text in
                        vm.inputValue = text
                    }
                }
            } label: {
                Image(systemName: speechInput.isRecording ? "stop.circle.fill" : "mic.fill")
                    .font(.system(size: 18, weight: .semibold))
                    .foregroundColor(speechInput.isRecording ? .white : .appPrimary)
                    .frame(width: 38, height: 38)
                    .background(speechInput.isRecording ? Color.appWarning : Color.appPrimary.opacity(0.1))
                    .clipShape(Circle())
            }
            .buttonStyle(.plain)
            .disabled(vm.sending)
            .accessibilityLabel(speechInput.isRecording ? "停止语音输入" : "语音输入")

            Button {
                Self.hideKeyboard()
                Task { await vm.sendMessage() }
            } label: {
                Image(systemName: "paperplane.fill")
                    .font(.system(size: 16, weight: .bold))
                    .foregroundColor(canSend ? .white : .appMuted)
                    .frame(width: 38, height: 38)
                    .background(canSend ? Color.appPrimary : Color.appSoftFill)
                    .clipShape(Circle())
            }
            .buttonStyle(.plain)
            .disabled(!canSend)
            .accessibilityLabel("发送")
        }
        .padding(.horizontal, 12)
        .padding(.top, 10)
        .padding(.bottom, 10)
        .background(Color.appCardBg)
        .overlay(
            Rectangle()
                .fill(Color.appStroke)
                .frame(height: 1),
            alignment: .top
        )
    }

    // MARK: - 历史会话

    private var historySheet: some View {
        NavigationStack {
            List {
                ForEach(vm.conversations) { conv in
                    Button {
                        Task {
                            await vm.loadConversation(id: conv.id)
                            vm.showHistory = false
                        }
                    } label: {
                        VStack(alignment: .leading, spacing: 4) {
                            Text(conv.title ?? "对话")
                                .foregroundColor(.appText)
                                .lineLimit(2)
                            HStack {
                                Text("\(conv.message_count ?? 0) 条消息")
                                    .font(.caption)
                                    .foregroundColor(.appMuted)
                                Spacer()
                                if let ts = conv.updated_at ?? conv.created_at {
                                    Text(Self.formatTimestamp(ts))
                                        .font(.caption)
                                        .foregroundColor(.appMuted)
                                }
                            }
                        }
                    }
                }
                // PERF-03: 加载更多会话
                if vm.hasMoreConversations {
                    Button {
                        Task { await vm.loadMoreConversations() }
                    } label: {
                        Text("加载更多")
                            .font(.subheadline)
                            .frame(maxWidth: .infinity)
                    }
                }
            }
            .navigationTitle("历史对话")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("关闭") { vm.showHistory = false }
                }
            }
            .overlay {
                if vm.conversations.isEmpty {
                    Text("暂无历史对话")
                        .foregroundColor(.appMuted)
                }
            }
        }
    }

    /// ISO 8601 时间戳 → 友好文本
    private static func formatTimestamp(_ iso: String) -> String {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        guard let date = formatter.date(from: iso) ?? ISO8601DateFormatter().date(from: iso) else {
            return iso.prefix(10).description
        }
        let now = Date()
        let diff = now.timeIntervalSince(date)
        if diff < 60 { return "刚刚" }
        if diff < 3600 { return "\(Int(diff / 60))分钟前" }
        if diff < 86400 { return "\(Int(diff / 3600))小时前" }
        if diff < 86400 * 7 { return "\(Int(diff / 86400))天前" }
        let df = DateFormatter()
        df.dateFormat = "MM-dd HH:mm"
        return df.string(from: date)
    }
}

@MainActor
private final class SpeechInputManager: NSObject, ObservableObject {
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
                AVAudioSession.sharedInstance().requestRecordPermission { [weak self] allowed in
                    DispatchQueue.main.async {
                        guard let self else { return }
                        guard allowed else {
                            self.errorMessage = "请在系统设置中允许麦克风权限。"
                            return
                        }
                        self.startRecording()
                    }
                }
            }
        }
    }

    func stop() {
        stopRecording(cancelTask: true)
    }

    private func startRecording() {
        guard recognizer?.isAvailable == true else {
            errorMessage = "当前设备语音识别暂不可用。"
            return
        }

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

private struct CompositionSafeTextView: UIViewRepresentable {
    @Binding var text: String
    let placeholder: String
    let isEnabled: Bool
    let onSubmit: () -> Void

    func makeCoordinator() -> Coordinator {
        Coordinator(self)
    }

    func makeUIView(context: Context) -> UITextView {
        let textView = UITextView()
        textView.delegate = context.coordinator
        textView.font = UIFont.preferredFont(forTextStyle: .body)
        textView.backgroundColor = UIColor.secondarySystemBackground
        textView.layer.cornerRadius = 8
        textView.layer.borderWidth = 0.5
        textView.layer.borderColor = UIColor.separator.cgColor
        textView.textContainerInset = UIEdgeInsets(top: 8, left: 8, bottom: 8, right: 8)
        textView.returnKeyType = .send
        textView.isScrollEnabled = true
        textView.text = placeholder
        textView.textColor = .placeholderText
        return textView
    }

    func updateUIView(_ uiView: UITextView, context: Context) {
        uiView.isEditable = isEnabled
        uiView.alpha = isEnabled ? 1 : 0.6
        if context.coordinator.isShowingPlaceholder {
            if !text.isEmpty {
                context.coordinator.isShowingPlaceholder = false
                uiView.text = text
                uiView.textColor = .label
            } else if uiView.text != placeholder {
                uiView.text = placeholder
                uiView.textColor = .placeholderText
            }
        } else if uiView.markedTextRange == nil && uiView.text != text {
            uiView.text = text.isEmpty ? placeholder : text
            uiView.textColor = text.isEmpty ? .placeholderText : .label
            context.coordinator.isShowingPlaceholder = text.isEmpty
        }
    }

    final class Coordinator: NSObject, UITextViewDelegate {
        var parent: CompositionSafeTextView
        var isShowingPlaceholder = true

        init(_ parent: CompositionSafeTextView) {
            self.parent = parent
        }

        func textViewDidBeginEditing(_ textView: UITextView) {
            if isShowingPlaceholder {
                textView.text = ""
                textView.textColor = .label
                isShowingPlaceholder = false
            }
        }

        func textViewDidEndEditing(_ textView: UITextView) {
            if textView.text.isEmpty {
                textView.text = parent.placeholder
                textView.textColor = .placeholderText
                isShowingPlaceholder = true
            }
        }

        func textViewDidChange(_ textView: UITextView) {
            guard textView.markedTextRange == nil else { return }
            parent.text = isShowingPlaceholder ? "" : textView.text
        }

        func textView(
            _ textView: UITextView,
            shouldChangeTextIn range: NSRange,
            replacementText replacement: String
        ) -> Bool {
            if replacement == "\n" {
                if textView.markedTextRange == nil {
                    parent.onSubmit()
                    return false
                }
            }
            return true
        }
    }
}
