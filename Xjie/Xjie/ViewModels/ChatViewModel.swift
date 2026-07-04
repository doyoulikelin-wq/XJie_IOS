import Foundation

/// 聊天消息展示模型（本地 UI 用）
enum ChatDeliveryStatus: String {
    case sending = "发送中"
    case sent = "已发送"
    case failed = "发送失败，可重试"
}

struct ChatMessageItem: Identifiable {
    let id: String
    let role: String
    let content: String       // summary (简约)
    let analysis: String?     // 详细分析 (Markdown)
    let confidence: Double?
    let followups: [String]?
    let citations: [Citation]
    let status: ChatDeliveryStatus?
    let retryText: String?

    init(
        id: String = UUID().uuidString,
        role: String,
        content: String,
        analysis: String?,
        confidence: Double?,
        followups: [String]?,
        citations: [Citation] = [],
        status: ChatDeliveryStatus? = nil,
        retryText: String? = nil
    ) {
        self.id = id
        self.role = role
        self.content = content
        self.analysis = analysis
        self.confidence = confidence
        self.followups = followups
        self.citations = citations
        self.status = status
        self.retryText = retryText
    }
}

extension ChatMessageItem {
    var relevantCitations: [Citation] {
        let answerText = [content, analysis ?? ""].joined(separator: "\n")
        return citations.filter { $0.isLikelyRelevant(to: answerText) }
    }
}

private extension Citation {
    func isLikelyRelevant(to answerText: String) -> Bool {
        let answer = Self.normalized(answerText)
        let claim = Self.normalized([claim_text, short_ref, journal ?? ""].joined(separator: " "))
        guard !claim.isEmpty else { return false }
        if answer.contains(claim) { return true }

        let answerGroups = Self.relevanceGroups(in: answer)
        let claimGroups = Self.relevanceGroups(in: claim)
        guard !answerGroups.isEmpty, !claimGroups.isEmpty else { return true }
        return !answerGroups.isDisjoint(with: claimGroups)
    }

    static func normalized(_ text: String) -> String {
        text.folding(options: [.caseInsensitive, .diacriticInsensitive], locale: .current)
            .lowercased()
    }

    static func relevanceGroups(in text: String) -> Set<Int> {
        Set(relevanceTermGroups.enumerated().compactMap { index, terms in
            terms.contains { text.contains($0) } ? index : nil
        })
    }

    static let relevanceTermGroups: [[String]] = [
        ["肝", "肝功能", "alt", "ast", "ggt", "alp", "胆道", "胆汁", "胆红素", "黄疸", "尿色", "mrcp", "肝硬化", "肝炎"],
        ["血糖", "糖尿病", "空腹血糖", "hba1c", "胰岛素", "降糖"],
        ["甘油三酯", "tg", "血脂", "胆固醇", "ldl", "hdl", "胰腺炎"],
        ["血压", "高血压", "收缩压", "舒张压"],
        ["限时进食", "进食", "禁食", "饮食", "热量", "膳食"],
        ["肥胖", "bmi", "体重", "腰围"],
        ["睡眠", "hrv", "心率", "步数", "活动", "运动"],
        ["肾", "肌酐", "egfr", "尿酸"],
        ["炎症", "crp", "白细胞"]
    ]
}

@MainActor
final class ChatViewModel: ObservableObject {
    @Published var messages: [ChatMessageItem] = []
    @Published var inputValue = ""
    @Published var sending = false
    @Published var threadId: String?
    @Published var conversations: [ChatConversation] = []
    @Published var showHistory = false
    @Published var errorMessage: String?
    @Published var planSavingMessageID: String?
    @Published var savedPlanMessageIDs: Set<String> = []
    @Published var thinkingHint = ""
    /// PERF-03: 会话列表分页
    @Published var hasMoreConversations = true
    /// 是否正在查看历史对话（非当前对话）
    @Published var isViewingHistory = false
    private var savedMessages: [ChatMessageItem] = []
    private var savedThreadId: String?
    private let convPageSize = APIConstants.pageSize
    private var thinkingTask: Task<Void, Never>?
    private let thinkingHints = [
        "正在理解你的问题…",
        "正在结合你的健康记录分析…",
        "正在生成建议…",
        "当前响应较慢，请稍候…"
    ]

    private let api: APIServiceProtocol

    init(api: APIServiceProtocol = APIService.shared) {
        self.api = api
    }

    func loadConversations(showErrors: Bool = true) async {
        do {
            let path = URLBuilder.path("/api/chat/conversations", queryItems: [
                URLQueryItem(name: "limit", value: "\(convPageSize)"),
                URLQueryItem(name: "offset", value: "0")
            ])
            conversations = try await api.get(path)
            hasMoreConversations = conversations.count >= convPageSize
        } catch {
            if showErrors {
                errorMessage = error.localizedDescription
            }
        }
    }

    /// PERF-03: 加载更多会话
    func loadMoreConversations() async {
        guard hasMoreConversations else { return }
        let offset = conversations.count
        let path = URLBuilder.path("/api/chat/conversations", queryItems: [
            URLQueryItem(name: "limit", value: "\(convPageSize)"),
            URLQueryItem(name: "offset", value: "\(offset)")
        ])
        let more: [ChatConversation] = (try? await api.get(path)) ?? []
        conversations.append(contentsOf: more)
        hasMoreConversations = more.count >= convPageSize
    }

    func loadConversation(id: String) async {
        do {
            let msgs: [ChatMessage] = try await api.get("/api/chat/conversations/\(id)")
            guard !Task.isCancelled else { return }
            // Save current conversation before switching
            if !isViewingHistory {
                savedMessages = messages
                savedThreadId = threadId
            }
            messages = Self.deduplicateMessages(msgs.map {
                ChatMessageItem(id: "server-\($0.id)",
                                role: $0.role, content: $0.content,
                                analysis: $0.analysis, confidence: nil, followups: nil,
                                citations: $0.citations)
            })
            threadId = id
            isViewingHistory = true
        } catch {
            guard !Task.isCancelled else { return }
            errorMessage = error.localizedDescription
        }
    }

    /// 返回当前对话
    func backToCurrentChat() {
        messages = savedMessages
        threadId = savedThreadId
        isViewingHistory = false
        savedMessages = []
        savedThreadId = nil
    }

    func sendMessage() async {
        await sendText(inputValue)
    }

    func sendText(_ text: String) async {
        let msg = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !msg.isEmpty, !sending else { return }
        inputValue = ""
        await send(text: msg, clientMessageId: UUID().uuidString, existingUserMessageId: nil)
    }

    func startPlanConversation(prompt: String) async {
        guard !sending else { return }
        newChat()
        await send(text: prompt, clientMessageId: UUID().uuidString, existingUserMessageId: nil)
    }

    func retryMessage(id: String) async {
        guard !sending,
              let item = messages.first(where: { $0.id == id && $0.status == .failed }) else { return }
        await send(text: item.retryText ?? item.content, clientMessageId: id, existingUserMessageId: id)
    }

    private func send(text msg: String, clientMessageId: String, existingUserMessageId: String?) async {
        // If viewing history, switch to this conversation as active
        if isViewingHistory {
            isViewingHistory = false
            savedMessages = []
            savedThreadId = nil
        }

        if let existingUserMessageId,
           let idx = messages.firstIndex(where: { $0.id == existingUserMessageId }) {
            let existing = messages[idx]
            messages[idx] = ChatMessageItem(
                id: existing.id,
                role: existing.role,
                content: existing.content,
                analysis: existing.analysis,
                confidence: existing.confidence,
                followups: existing.followups,
                citations: existing.citations,
                status: .sending,
                retryText: existing.retryText ?? existing.content
            )
        } else {
            let userMsg = ChatMessageItem(
                id: clientMessageId,
                role: "user",
                content: msg,
                analysis: nil,
                confidence: nil,
                followups: nil,
                status: .sending,
                retryText: msg
            )
            messages.append(userMsg)
        }
        sending = true
        thinkingHint = thinkingHints.first ?? "正在思考…"
        startThinkingTicker()
        defer {
            sending = false
            stopThinkingTicker()
        }

        do {
            // XAGE and legacy chat both route through /api/chat so provider/model
            // selection remains centralized on the backend and covered by LLM audit logs.
            let res: ChatResponse = try await api.post(
                "/api/chat",
                body: ChatRequest(message: msg, thread_id: threadId, client_message_id: clientMessageId),
                timeout: APIConstants.llmTimeout
            )

            // answer_markdown 可能是 JSON 字符串 (来自 mock provider)
            let rawContent = res.summary ?? res.answer_markdown ?? "..."
            let content = Self.cleanContent(rawContent)

            if let tid = res.thread_id {
                threadId = tid
            }
            markUserMessage(id: clientMessageId, status: .sent)

            let assistantMsg = ChatMessageItem(
                id: "assistant-\(UUID().uuidString)",
                role: "assistant",
                content: content,
                analysis: res.analysis,
                confidence: res.confidence,
                followups: res.followups,
                citations: res.citations ?? []
            )
            messages = Self.deduplicateMessages(messages + [assistantMsg])
        } catch let error as APIError {
            // 403 = AI 聊天未授权，自动开启后重试
            if case .httpError(403, _) = error {
                do {
                    let _: ConsentResponse = try await api.patch("/api/users/consent", body: ConsentUpdate(allow_ai_chat: true))
                    let res: ChatResponse = try await api.post(
                        "/api/chat",
                        body: ChatRequest(message: msg, thread_id: threadId, client_message_id: clientMessageId),
                        timeout: APIConstants.llmTimeout
                    )
                    let content = Self.cleanContent(res.summary ?? res.answer_markdown ?? "...")
                    if let tid = res.thread_id { threadId = tid }
                    markUserMessage(id: clientMessageId, status: .sent)
                    messages = Self.deduplicateMessages(messages + [ChatMessageItem(
                        id: "assistant-\(UUID().uuidString)",
                        role: "assistant",
                        content: content,
                        analysis: res.analysis,
                        confidence: res.confidence,
                        followups: res.followups,
                        citations: res.citations ?? []
                    )])
                    return
                } catch {
                    // 自动授权失败，显示错误
                }
            }
            markUserMessage(id: clientMessageId, status: .failed)
            let errorMsg = ChatMessageItem(id: "error-\(UUID().uuidString)", role: "assistant", content: "请求失败: \(error.localizedDescription)", analysis: nil, confidence: nil, followups: nil)
            messages = Self.deduplicateMessages(messages + [errorMsg])
            errorMessage = error.localizedDescription
        } catch {
            markUserMessage(id: clientMessageId, status: .failed)
            let errorMsg = ChatMessageItem(id: "error-\(UUID().uuidString)", role: "assistant", content: "请求失败: \(error.localizedDescription)", analysis: nil, confidence: nil, followups: nil)
            messages = Self.deduplicateMessages(messages + [errorMsg])
            errorMessage = error.localizedDescription
        }
    }

    func newChat() {
        messages = []
        threadId = nil
        isViewingHistory = false
        savedMessages = []
        savedThreadId = nil
        stopThinkingTicker()
        sending = false
    }

    func shouldOfferSavePlan(for message: ChatMessageItem) -> Bool {
        guard message.role == "assistant", !savedPlanMessageIDs.contains(message.id) else { return false }
        let text = "\(message.content)\n\(message.analysis ?? "")"
        return Self.looksLikeHealthPlan(text)
    }

    func saveAsHealthPlan(message: ChatMessageItem) async {
        guard shouldOfferSavePlan(for: message), planSavingMessageID == nil else { return }
        planSavingMessageID = message.id
        defer { planSavingMessageID = nil }
        do {
            let _: HealthPlanDetail = try await api.post(
                "/api/health-plans/from-chat",
                body: HealthPlanFromChatRequest(
                    content: message.content,
                    analysis: message.analysis,
                    conversation_id: threadId,
                    message_id: message.id,
                    title: nil
                )
            )
            savedPlanMessageIDs.insert(message.id)
            errorMessage = "已保存为健康计划，可在「计划」页查看。"
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func markUserMessage(id: String, status: ChatDeliveryStatus) {
        guard let idx = messages.firstIndex(where: { $0.id == id }) else { return }
        let item = messages[idx]
        messages[idx] = ChatMessageItem(
            id: item.id,
            role: item.role,
            content: item.content,
            analysis: item.analysis,
            confidence: item.confidence,
            followups: item.followups,
            citations: item.citations,
            status: status,
            retryText: item.retryText ?? item.content
        )
    }

    private func startThinkingTicker() {
        thinkingTask?.cancel()
        thinkingTask = Task { [weak self] in
            var index = 0
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 3_000_000_000)
                guard !Task.isCancelled else { return }
                await MainActor.run {
                    guard let self, self.sending else { return }
                    index = min(index + 1, self.thinkingHints.count - 1)
                    self.thinkingHint = self.thinkingHints[index]
                }
            }
        }
    }

    private func stopThinkingTicker() {
        thinkingTask?.cancel()
        thinkingTask = nil
        thinkingHint = ""
    }

    /// Strip raw JSON/markdown fences that may leak from LLM responses
    static func cleanContent(_ text: String) -> String {
        var s = text.trimmingCharacters(in: .whitespacesAndNewlines)
        // If it looks like raw JSON starting with { "summary", extract the summary value
        if s.hasPrefix("{") && s.contains("\"summary\"") {
            if let data = s.data(using: .utf8),
               let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
               let summary = json["summary"] as? String {
                return summary
            }
        }
        // Strip ```json fences
        if s.hasPrefix("```") {
            s = s.replacingOccurrences(of: "```json", with: "")
            s = s.replacingOccurrences(of: "```", with: "")
            s = s.trimmingCharacters(in: .whitespacesAndNewlines)
            // Try JSON parse after stripping fences
            if s.hasPrefix("{"), let data = s.data(using: .utf8),
               let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
               let summary = json["summary"] as? String {
                return summary
            }
        }
        return s
    }

    static func looksLikeHealthPlan(_ text: String) -> Bool {
        let lower = text.lowercased()
        let planWords = ["计划", "方案", "安排", "周期", "一周", "7天", "每日", "每天"]
        let healthWords = ["饮食", "运动", "康复", "用药", "服药", "控糖", "血糖", "热量", "恢复"]
        return planWords.contains(where: { lower.contains($0) }) &&
            healthWords.contains(where: { lower.contains($0) })
    }

    private static func deduplicateMessages(_ items: [ChatMessageItem]) -> [ChatMessageItem] {
        var seenIDs = Set<String>()
        var result: [ChatMessageItem] = []
        for item in items {
            guard seenIDs.insert(item.id).inserted else { continue }
            if let last = result.last,
               last.status == nil,
               item.status == nil,
               last.role == item.role,
               last.content.trimmingCharacters(in: .whitespacesAndNewlines) == item.content.trimmingCharacters(in: .whitespacesAndNewlines) {
                continue
            }
            result.append(item)
        }
        return result
    }
}
