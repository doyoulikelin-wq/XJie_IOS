import Foundation

/// 聊天消息展示模型（本地 UI 用）
struct ChatMessageItem: Identifiable {
    let id = UUID()
    let role: String
    let content: String       // summary (简约)
    let analysis: String?     // 详细分析 (Markdown)
    let confidence: Double?
    let followups: [String]?
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
    /// PERF-03: 会话列表分页
    @Published var hasMoreConversations = true
    /// 是否正在查看历史对话（非当前对话）
    @Published var isViewingHistory = false
    private var savedMessages: [ChatMessageItem] = []
    private var savedThreadId: String?
    private let convPageSize = APIConstants.pageSize

    private let api: APIServiceProtocol

    init(api: APIServiceProtocol = APIService.shared) {
        self.api = api
    }

    func loadConversations() async {
        do {
            let path = URLBuilder.path("/api/chat/conversations", queryItems: [
                URLQueryItem(name: "limit", value: "\(convPageSize)"),
                URLQueryItem(name: "offset", value: "0")
            ])
            conversations = try await api.get(path)
            hasMoreConversations = conversations.count >= convPageSize
        } catch {
            errorMessage = error.localizedDescription
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
            messages = msgs.map {
                ChatMessageItem(role: $0.role, content: $0.content,
                                analysis: $0.analysis, confidence: nil, followups: nil)
            }
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
        let msg = inputValue.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !msg.isEmpty, !sending else { return }

        // If viewing history, switch to this conversation as active
        if isViewingHistory {
            isViewingHistory = false
            savedMessages = []
            savedThreadId = nil
        }

        let userMsg = ChatMessageItem(role: "user", content: msg, analysis: nil, confidence: nil, followups: nil)
        messages.append(userMsg)
        inputValue = ""
        sending = true
        defer { sending = false }

        do {
            // TODO: [LLM API] 当前调用后端 /api/chat，后端再调用 LLM 服务
            // 如果后端 LLM 未部署，此请求会返回 mock/stub 响应
            let res: ChatResponse = try await api.post(
                "/api/chat",
                body: ChatRequest(message: msg, thread_id: threadId)
            )

            // answer_markdown 可能是 JSON 字符串 (来自 mock provider)
            let content = res.summary ?? res.answer_markdown ?? "..."

            if let tid = res.thread_id {
                threadId = tid
            }

            let assistantMsg = ChatMessageItem(
                role: "assistant",
                content: content,
                analysis: res.analysis,
                confidence: res.confidence,
                followups: res.followups
            )
            messages.append(assistantMsg)
        } catch let error as APIError {
            // 403 = AI 聊天未授权，自动开启后重试
            if case .httpError(403, _) = error {
                do {
                    let _: ConsentResponse = try await api.patch("/api/users/consent", body: ConsentUpdate(allow_ai_chat: true))
                    let res: ChatResponse = try await api.post("/api/chat", body: ChatRequest(message: msg, thread_id: threadId))
                    let content = res.summary ?? res.answer_markdown ?? "..."
                    if let tid = res.thread_id { threadId = tid }
                    messages.append(ChatMessageItem(role: "assistant", content: content, analysis: res.analysis, confidence: res.confidence, followups: res.followups))
                    return
                } catch {
                    // 自动授权失败，显示错误
                }
            }
            let errorMsg = ChatMessageItem(role: "assistant", content: "请求失败: \(error.localizedDescription)", analysis: nil, confidence: nil, followups: nil)
            messages.append(errorMsg)
            errorMessage = error.localizedDescription
        } catch {
            let errorMsg = ChatMessageItem(role: "assistant", content: "请求失败: \(error.localizedDescription)", analysis: nil, confidence: nil, followups: nil)
            messages.append(errorMsg)
            errorMessage = error.localizedDescription
        }
    }

    func newChat() {
        messages = []
        threadId = nil
        isViewingHistory = false
        savedMessages = []
        savedThreadId = nil
    }
}
