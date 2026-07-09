import Foundation

/// 聊天消息展示模型（本地 UI 用）
enum ChatDeliveryStatus: String, Equatable {
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

private struct PendingChatConsentRetry {
    let text: String
    let clientMessageID: String
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
    @Published var thinkingStepIndex = 0
    @Published private(set) var activeRoute: ChatInteractionRoute?
    @Published var showAIConsentPrompt = false
    /// PERF-03: 会话列表分页
    @Published var hasMoreConversations = true
    /// 是否正在查看历史对话（非当前对话）
    @Published var isViewingHistory = false
    private var savedMessages: [ChatMessageItem] = []
    private var savedThreadId: String?
    private let convPageSize = APIConstants.pageSize
    private var thinkingTask: Task<Void, Never>?
    private var activeThinkingHints: [String] = []
    private var activeRequestID: UUID?
    private var pendingConsentRetry: PendingChatConsentRetry?
    private static let defaultThinkingHints = [
        "正在识别当前问题和主体…",
        "正在核对本轮可用的会话与数据范围…",
        "正在等待回答完成…",
        "响应较慢，仍在继续处理…"
    ]

    private let api: APIServiceProtocol

    init(api: APIServiceProtocol = APIService.shared) {
        self.api = api
    }

    var thinkingProgressItems: [String] {
        guard !activeThinkingHints.isEmpty else { return [] }
        let count = min(activeThinkingHints.count, max(0, thinkingStepIndex))
        return Array(activeThinkingHints.prefix(count))
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
        guard !sending else {
            errorMessage = "当前回答完成后再打开历史对话，避免消息进入错误的会话。"
            return
        }
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
                                analysis: Self.cleanAnalysis($0.analysis), confidence: nil, followups: nil,
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
        guard let msg = consumeInputForSending() else { return }
        await send(text: msg, clientMessageId: UUID().uuidString, existingUserMessageId: nil)
    }

    func consumeInputForSending() -> String? {
        let msg = inputValue.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !msg.isEmpty, !sending else { return nil }
        inputValue = ""
        return msg
    }

    func sendText(_ text: String) async {
        let msg = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !msg.isEmpty, !sending else { return }
        if inputValue.trimmingCharacters(in: .whitespacesAndNewlines) == msg {
            inputValue = ""
        }
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
        let requestID = UUID()
        activeRequestID = requestID
        activeRoute = nil
        activeThinkingHints = Self.thinkingHints(for: msg)
        thinkingHint = activeThinkingHints.first ?? "正在思考…"
        thinkingStepIndex = 0
        startThinkingTicker()
        defer {
            if activeRequestID == requestID {
                activeRequestID = nil
                sending = false
                stopThinkingTicker()
            }
        }

        do {
            let response = try await performChatRequest(
                message: msg,
                clientMessageID: clientMessageId,
                requestID: requestID
            )
            guard activeRequestID == requestID else { return }
            apply(response: response, clientMessageID: clientMessageId)
        } catch let error as APIError {
            guard activeRequestID == requestID else { return }
            markUserMessage(id: clientMessageId, status: .failed)
            if case .httpError(403, _) = error {
                pendingConsentRetry = PendingChatConsentRetry(text: msg, clientMessageID: clientMessageId)
                showAIConsentPrompt = true
            } else {
                errorMessage = Self.userFacingError(error)
            }
        } catch is CancellationError {
            return
        } catch {
            guard activeRequestID == requestID else { return }
            markUserMessage(id: clientMessageId, status: .failed)
            errorMessage = Self.userFacingError(error)
        }
    }

    private func performChatRequest(
        message: String,
        clientMessageID: String,
        requestID: UUID
    ) async throws -> ChatResponse {
        let request = ChatRequest(message: message, thread_id: threadId, client_message_id: clientMessageID)
        do {
            let stream = try await api.postChatStream(request, timeout: APIConstants.llmTimeout)
            var finalResponse: ChatResponse?
            for try await event in stream {
                guard activeRequestID == requestID else { throw CancellationError() }
                switch event {
                case .route(let route):
                    apply(route: route)
                case .progress(let step):
                    appendProgressStep(step)
                case .token:
                    continue
                case .done(let response):
                    finalResponse = response
                }
            }
            guard let finalResponse else { throw APIError.invalidResponse }
            return finalResponse
        } catch let error as APIError {
            guard case .httpError(let status, _) = error, status == 404 || status == 405 else {
                throw error
            }
            return try await api.post(
                "/api/chat",
                body: request,
                timeout: APIConstants.llmTimeout
            )
        }
    }

    private func apply(response: ChatResponse, clientMessageID: String) {
        if let route = response.interaction_route { apply(route: route) }
        if let tid = response.thread_id { threadId = tid }
        markUserMessage(id: clientMessageID, status: .sent)

        if response.response_state == "processing" {
            errorMessage = response.summary ?? "这条消息已由服务器接收，仍在处理中，请稍后查看历史对话。"
            return
        }

        let rawContent = response.summary ?? response.answer_markdown ?? "这次回答没有完整生成，请重试。"
        let content = Self.cleanContent(rawContent)
        let assistantID = response.message_id.map { "server-\($0)" } ?? "assistant-\(UUID().uuidString)"
        let assistantMsg = ChatMessageItem(
            id: assistantID,
            role: "assistant",
            content: content,
            analysis: Self.cleanAnalysis(response.analysis),
            confidence: response.confidence,
            followups: response.followups,
            citations: response.citations ?? []
        )
        messages = Self.deduplicateMessages(messages + [assistantMsg])
    }

    private func apply(route: ChatInteractionRoute) {
        activeRoute = route
        let steps = route.progress_steps
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
        guard !steps.isEmpty else { return }
        activeThinkingHints = steps
        thinkingHint = steps[0]
        thinkingStepIndex = 0
        if sending { startThinkingTicker() }
    }

    private func appendProgressStep(_ step: String) {
        let normalized = step.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !normalized.isEmpty, !activeThinkingHints.contains(normalized) else { return }
        activeThinkingHints.append(normalized)
    }

    func grantAIConsentAndRetry() async {
        guard let pending = pendingConsentRetry else { return }
        showAIConsentPrompt = false
        do {
            let _: ConsentResponse = try await api.patch(
                "/api/users/consent",
                body: ConsentUpdate(allow_ai_chat: true)
            )
            pendingConsentRetry = nil
            await send(
                text: pending.text,
                clientMessageId: pending.clientMessageID,
                existingUserMessageId: pending.clientMessageID
            )
        } catch {
            errorMessage = "AI 健康问答授权没有保存，请稍后重试或在设置中开启。"
        }
    }

    func declineAIConsent() {
        showAIConsentPrompt = false
        pendingConsentRetry = nil
    }

    func newChat() {
        activeRequestID = nil
        messages = []
        threadId = nil
        isViewingHistory = false
        savedMessages = []
        savedThreadId = nil
        stopThinkingTicker()
        sending = false
        activeRoute = nil
        pendingConsentRetry = nil
        showAIConsentPrompt = false
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
                try? await Task.sleep(nanoseconds: 1_800_000_000)
                guard !Task.isCancelled else { return }
                await MainActor.run {
                    guard let self, self.sending else { return }
                    guard !self.activeThinkingHints.isEmpty else { return }
                    index = min(index + 1, self.activeThinkingHints.count - 1)
                    self.thinkingHint = self.activeThinkingHints[index]
                    self.thinkingStepIndex = index
                }
            }
        }
    }

    private func stopThinkingTicker() {
        thinkingTask?.cancel()
        thinkingTask = nil
        thinkingHint = ""
        thinkingStepIndex = 0
        activeThinkingHints = []
    }

    private static func thinkingHints(for message: String) -> [String] {
        _ = message
        return defaultThinkingHints
    }

    nonisolated private static func userFacingError(_ error: Error) -> String {
        if let urlError = error as? URLError {
            switch urlError.code {
            case .notConnectedToInternet, .internationalRoamingOff, .dataNotAllowed:
                return "当前网络不可用。原消息已经保留，恢复网络后点击重试。"
            case .cannotConnectToHost, .cannotFindHost, .dnsLookupFailed:
                return "暂时无法连接服务。原消息已经保留，请稍后点击重试。"
            case .timedOut:
                return "回答等待超时。原消息已经保留，点击重试会沿用同一会话。"
            case .networkConnectionLost:
                return "网络连接中断。原消息已经保留，请点击重试。"
            default:
                break
            }
        }
        return error.localizedDescription
    }

    /// Strip raw JSON/markdown fences that may leak from LLM responses
    nonisolated static func cleanContent(_ text: String) -> String {
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

    nonisolated static func cleanAnalysis(_ text: String?) -> String? {
        guard let text else { return nil }
        let cleanedLines = text
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .components(separatedBy: .newlines)
            .map { rawLine -> String in
                var line = rawLine.trimmingCharacters(in: .whitespacesAndNewlines)
                while line.hasPrefix("#") {
                    line.removeFirst()
                    line = line.trimmingCharacters(in: .whitespacesAndNewlines)
                }
                return line
            }
        let cleaned = cleanedLines
            .joined(separator: "\n")
            .replacingOccurrences(of: "\n\n\n", with: "\n\n")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        return cleaned.isEmpty ? nil : cleaned
    }

    nonisolated static func looksLikeHealthPlan(_ text: String) -> Bool {
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
