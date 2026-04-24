import SwiftUI

/// AI 聊天页面 — 对应小程序 pages/chat/chat
struct ChatView: View {
    @StateObject private var vm = ChatViewModel()
    @State private var expandedIDs: Set<UUID> = []
    var isEmbedded: Bool = false

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
        .task { await vm.loadConversations() }
        .alert("错误", isPresented: Binding(
            get: { vm.errorMessage != nil },
            set: { if !$0 { vm.errorMessage = nil } }
        )) {
            Button("确定", role: .cancel) {}
        } message: {
            Text(vm.errorMessage ?? "")
        }
    }

    // MARK: - 消息列表

    private var messageList: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(spacing: 12) {
                    if vm.messages.isEmpty {
                        welcomeMessage
                    }

                    ForEach(Array(vm.messages.enumerated()), id: \.offset) { _, msg in
                        messageBubble(msg)
                    }

                    if vm.sending {
                        HStack {
                            Text("思考中...")
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
                .padding(.vertical, 8)
            }
            .onChange(of: vm.messages.count) { _, _ in
                withAnimation {
                    proxy.scrollTo("bottom", anchor: .bottom)
                }
            }
        }
    }

    private var welcomeMessage: some View {
        VStack(spacing: 8) {
            AssistantAvatar(size: 80, bordered: true)
            Text("你好！我是助手小捷。")
                .font(.headline)
            Text("可以问我关于血糖、膳食、健康管理的问题。")
                .font(.subheadline)
                .foregroundColor(.appMuted)
        }
        .padding(24)
        .accessibilityElement(children: .combine)
    }

    private func messageBubble(_ msg: ChatMessageItem) -> some View {
        let isUser = msg.role == "user"
        let isExpanded = expandedIDs.contains(msg.id)

        return HStack {
            if isUser { Spacer() }
            VStack(alignment: .leading, spacing: 6) {
                Text(msg.content)
                    .font(.subheadline)

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
            }
            .padding(12)
            .background(isUser ? Color.appPrimary : Color.appCardBg)
            .foregroundColor(isUser ? .white : .appText)
            .cornerRadius(12)
            .shadow(color: .black.opacity(0.04), radius: 4, x: 0, y: 2)
            if !isUser { Spacer() }
        }
        .padding(.horizontal, 16)
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
        HStack(spacing: 8) {
            TextField("输入消息...", text: $vm.inputValue)
                .textFieldStyle(.roundedBorder)
                .submitLabel(.send)
                .onSubmit { Task { await vm.sendMessage() } }

            Button {
                Task { await vm.sendMessage() }
            } label: {
                Text("发送")
                    .font(.subheadline.bold())
                    .foregroundColor(!vm.inputValue.isEmpty && !vm.sending ? .appPrimary : .appMuted)
            }
            .disabled(vm.inputValue.isEmpty || vm.sending)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 8)
        .background(Color.appCardBg)
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

