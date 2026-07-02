import XCTest
@testable import Xjie

/// ChatViewModel 单元测试
@MainActor
final class ChatViewModelTests: XCTestCase {

    func testSendMessageAppendsUserMessage() async throws {
        let mock = MockAPIService()
        let response = ChatResponse(
            summary: nil,
            analysis: nil,
            answer_markdown: "Hello!",
            confidence: 0.9,
            followups: ["追问1"],
            thread_id: "thread-1",
            citations: nil
        )
        try await mock.setResponse(for: "/api/chat", value: response)

        let vm = ChatViewModel(api: mock)
        vm.inputValue = "你好"
        await vm.sendMessage()

        XCTAssertEqual(vm.messages.count, 2, "应有 user + assistant 两条消息")
        XCTAssertEqual(vm.messages[0].role, "user")
        XCTAssertEqual(vm.messages[0].content, "你好")
        XCTAssertEqual(vm.messages[1].role, "assistant")
        XCTAssertEqual(vm.messages[1].content, "Hello!")
        XCTAssertEqual(vm.threadId, "thread-1")
        let requestedPaths = await mock.getRequestedPaths()
        XCTAssertEqual(requestedPaths, ["/api/chat"])
    }

    func testSendTextRoutesToChatEndpoint() async throws {
        let mock = MockAPIService()
        let response = ChatResponse(summary: "已收到", analysis: nil, answer_markdown: nil, confidence: nil, followups: nil, thread_id: nil, citations: nil)
        try await mock.setResponse(for: "/api/chat", value: response)

        let vm = ChatViewModel(api: mock)
        await vm.sendText("上传报告后自动解读")

        let requestedPaths = await mock.getRequestedPaths()
        XCTAssertEqual(requestedPaths, ["/api/chat"])
        XCTAssertEqual(vm.messages.first?.content, "上传报告后自动解读")
        XCTAssertEqual(vm.messages.last?.content, "已收到")
    }

    func testSendEmptyMessageDoesNothing() async {
        let mock = MockAPIService()
        let vm = ChatViewModel(api: mock)
        vm.inputValue = "   "
        await vm.sendMessage()

        XCTAssertTrue(vm.messages.isEmpty)
    }

    func testSendMessageErrorAppendsErrorMessage() async {
        let mock = MockAPIService()
        await mock.setError(URLError(.notConnectedToInternet))

        let vm = ChatViewModel(api: mock)
        vm.inputValue = "test"
        await vm.sendMessage()

        XCTAssertEqual(vm.messages.count, 2)
        XCTAssertEqual(vm.messages[1].role, "assistant")
        XCTAssertTrue(vm.messages[1].content.contains("请求失败"))
        XCTAssertNotNil(vm.errorMessage)
    }

    func testNewChatClearsState() async throws {
        let mock = MockAPIService()
        let response = ChatResponse(summary: nil, analysis: nil, answer_markdown: "hi", confidence: nil, followups: nil, thread_id: "t1", citations: nil)
        try await mock.setResponse(for: "/api/chat", value: response)

        let vm = ChatViewModel(api: mock)
        vm.inputValue = "hello"
        await vm.sendMessage()
        XCTAssertFalse(vm.messages.isEmpty)

        vm.newChat()
        XCTAssertTrue(vm.messages.isEmpty)
        XCTAssertNil(vm.threadId)
    }

    func testLoadConversationsSuccess() async throws {
        let mock = MockAPIService()
        let convos = [
            ChatConversation(id: "c1", title: "对话1", message_count: 5, updated_at: nil, created_at: nil),
            ChatConversation(id: "c2", title: "对话2", message_count: 3, updated_at: nil, created_at: nil),
        ]
        try await mock.setResult(convos)

        let vm = ChatViewModel(api: mock)
        await vm.loadConversations()

        XCTAssertEqual(vm.conversations.count, 2)
        XCTAssertEqual(vm.conversations[0].title, "对话1")
    }

    func testLoadConversationById() async throws {
        let mock = MockAPIService()
        let msgs = [
            ChatMessage(id: "m1", role: "user", content: "q"),
            ChatMessage(id: "m2", role: "assistant", content: "a"),
        ]
        // ChatMessage 有自定义 init(from decoder:) 所以需要手动编码
        let data = try JSONEncoder().encode(msgs.map { EncodableChatMessage(id: $0.id, role: $0.role, content: $0.content) })
        await mock.setResponseData(for: "/api/chat/conversations/c1", data: data)

        let vm = ChatViewModel(api: mock)
        await vm.loadConversation(id: "c1")

        XCTAssertEqual(vm.messages.count, 2)
        XCTAssertEqual(vm.threadId, "c1")
    }
}

/// 辅助编码结构（ChatMessage 只有自定义 Decodable，没有 Encodable）
private struct EncodableChatMessage: Encodable {
    let id: String
    let role: String
    let content: String
}

/// MockAPIService 扩展：支持按路径设置原始 Data
extension MockAPIService {
    func getRequestedPaths() -> [String] {
        requestedPaths
    }

    func setResponseData(for path: String, data: Data) {
        responseMap[path] = data
    }
}
