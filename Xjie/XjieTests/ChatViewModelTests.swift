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
        try await mock.setResponse(for: "/api/chat/stream", value: response)

        let vm = ChatViewModel(api: mock)
        vm.inputValue = "你好"
        await vm.sendMessage()

        XCTAssertEqual(vm.messages.count, 2, "应有 user + assistant 两条消息")
        XCTAssertEqual(vm.messages[0].role, "user")
        XCTAssertEqual(vm.messages[0].content, "你好")
        XCTAssertEqual(vm.messages[1].role, "assistant")
        XCTAssertEqual(vm.messages[1].content, "Hello!")
        XCTAssertEqual(vm.threadId, "thread-1")
        XCTAssertFalse(vm.sending)
        XCTAssertEqual(vm.thinkingHint, "")
        XCTAssertTrue(vm.thinkingProgressItems.isEmpty)

        vm.inputValue = "继续问"
        await vm.sendMessage()

        XCTAssertEqual(vm.messages.count, 4, "连续发送后每轮都应恰好追加 user + assistant")
        XCTAssertEqual(vm.messages[2].content, "继续问")
        XCTAssertEqual(vm.messages[3].content, "Hello!")
        XCTAssertFalse(vm.sending)
        XCTAssertEqual(vm.thinkingHint, "")
        XCTAssertTrue(vm.thinkingProgressItems.isEmpty)
        let requestedPaths = await mock.getRequestedPaths()
        XCTAssertEqual(requestedPaths, ["/api/chat/stream", "/api/chat/stream"])

        for plainText in [
            "普通医学文本：A_B/C，2 * 3 = 6",
            "A * B * C",
            "约 ~ 2 天 ~ 左右",
            "- 列表"
        ] {
            let rendering = AccessibleMarkdownRenderer.render(plainText)
            XCTAssertNil(rendering.attributed, "视觉不变的普通文本不得暴露富文本 AX 树：\(plainText)")
            XCTAssertEqual(rendering.accessibilityText, plainText)
        }

        let richTextCases = [
            ("**粗体**", "粗体"),
            ("*斜体*", "斜体"),
            ("_斜体_", "斜体"),
            ("~~删除线~~", "删除线"),
            ("`代码`", "代码"),
            ("[指南](https://example.com)", "指南"),
            ("<https://example.com>", "https://example.com"),
            ("*跨行\n强调*", "跨行\n强调"),
            ("__跨行\n强调__", "跨行\n强调"),
            ("~~跨行\n删除~~", "跨行\n删除"),
            ("[跨行\n链接](https://example.com)", "跨行\n链接"),
            ("\\*字面星号\\*", "*字面星号*"),
            ("A &amp; B", "A & B"),
            ("H~2~O", "H2O"),
            ("访问 https://example.com 获取指南", "访问 https://example.com 获取指南"),
            ("ftp://example.com", "ftp://example.com"),
            ("www.example.com", "www.example.com"),
            ("联系 test@example.com", "联系 test@example.com"),
            ("A\rB", "A\nB"),
            ("A\r\nB", "A\nB"),
            ("A\0B", "A\u{FFFD}B")
        ]
        for (markdown, expectedAccessibilityText) in richTextCases {
            let rendering = AccessibleMarkdownRenderer.render(markdown)
            XCTAssertNotNil(rendering.attributed, "旧 inline Markdown 的视觉语义必须保留：\(markdown)")
            XCTAssertEqual(
                rendering.accessibilityText,
                expectedAccessibilityText,
                "辅助功能正文必须读取渲染后的去标记文本"
            )
        }
        for autolink in [
            "访问 https://example.com 获取指南",
            "ftp://example.com",
            "www.example.com",
            "联系 test@example.com"
        ] {
            let rendered = AccessibleMarkdownRenderer.render(autolink).attributed
            XCTAssertTrue(
                rendered?.runs.contains(where: { $0.link != nil }) == true,
                "Foundation 自动链接属性必须保留：\(autolink)"
            )
        }
        let linkedRendering = AccessibleMarkdownRenderer.render(
            "前缀 [查看指南](https://example.com) 后缀"
        )
        XCTAssertEqual(
            linkedRendering.accessibilitySegments.map(\.text),
            ["前缀 ", "查看指南", " 后缀"],
            "链接辅助功能表示必须去除 Markdown 标记且保持阅读顺序"
        )
        XCTAssertEqual(
            linkedRendering.accessibilitySegments.compactMap(\.link),
            [URL(string: "https://example.com")!],
            "链接辅助功能表示必须保留可激活的目标，不能退化为普通静态文本"
        )
        let singleTildeText = AccessibleMarkdownRenderer.render("H~2~O").attributed
        XCTAssertTrue(
            singleTildeText?.runs.contains(where: { $0.inlinePresentationIntent != nil }) == true,
            "单波浪线删除线必须保留 inline presentation intent"
        )
    }

    func testXAgeWelcomeGreetingUsesLocalTimeBoundaries() throws {
        var localCalendar = Calendar(identifier: .gregorian)
        localCalendar.timeZone = try XCTUnwrap(TimeZone(secondsFromGMT: 8 * 60 * 60))
        let expectedGreetings = [
            "夜深了", "夜深了", "夜深了", "夜深了", "夜深了",
            "早上好", "早上好", "早上好", "早上好", "早上好", "早上好",
            "中午好", "中午好", "中午好",
            "下午好", "下午好", "下午好", "下午好",
            "晚上好", "晚上好", "晚上好", "晚上好", "晚上好",
            "夜深了"
        ]
        for (hour, period) in expectedGreetings.enumerated() {
            let date = try XCTUnwrap(localCalendar.date(from: DateComponents(
                year: 2026, month: 7, day: 15, hour: hour
            )))
            XCTAssertEqual(
                xAgeWelcomeGreeting(at: date, calendar: localCalendar),
                "\(period)，想问什么？",
                "第 \(hour) 时的问候必须与 Android 共用时段规则"
            )
        }
    }

    func testSendTextRoutesToChatEndpoint() async throws {
        let mock = MockAPIService()
        let response = ChatResponse(summary: "已收到", analysis: nil, answer_markdown: nil, confidence: nil, followups: nil, thread_id: nil, citations: nil)
        try await mock.setResponse(for: "/api/chat/stream", value: response)

        let vm = ChatViewModel(api: mock)
        await vm.sendText("上传报告后自动解读")

        let requestedPaths = await mock.getRequestedPaths()
        XCTAssertEqual(requestedPaths, ["/api/chat/stream"])
        XCTAssertEqual(vm.messages.first?.content, "上传报告后自动解读")
        XCTAssertEqual(vm.messages.last?.content, "已收到")
    }

    func testConsumeInputForSendingClearsCommittedChineseDraftSynchronously() {
        let vm = ChatViewModel(api: MockAPIService())
        vm.inputValue = "  5岁孩子血糖 2.8 mmol/L  "

        let consumed = vm.consumeInputForSending()

        XCTAssertEqual(consumed, "5岁孩子血糖 2.8 mmol/L")
        XCTAssertEqual(vm.inputValue, "")
    }

    func testSendTextClearsMatchingIMECommitButPreservesNewerDraft() async throws {
        let mock = MockAPIService()
        try await mock.setResponse(
            for: "/api/chat/stream",
            value: ChatResponse(summary: "已收到")
        )
        let vm = ChatViewModel(api: mock)

        vm.inputValue = "刚提交的中文消息"
        await vm.sendText("刚提交的中文消息")
        XCTAssertEqual(vm.inputValue, "")

        vm.inputValue = "下一条草稿"
        await vm.sendText("上一条消息")
        XCTAssertEqual(vm.inputValue, "下一条草稿")
    }

    func testCleanAnalysisRemovesMarkdownHeadingMarkers() {
        let raw = """
        # 病史整理
        ## 指标解读
        正文内容
        ### 下一步
        """

        let cleaned = ChatViewModel.cleanAnalysis(raw)

        XCTAssertEqual(cleaned, "病史整理\n指标解读\n正文内容\n下一步")
    }

    func testThinkingProgressAdvancesWhileWaitingForResponse() async throws {
        let mock = MockAPIService()
        let response = ChatResponse(summary: "已收到", analysis: nil, answer_markdown: nil, confidence: nil, followups: nil, thread_id: nil, citations: nil)
        try await mock.setResponse(for: "/api/chat/stream", value: response)
        await mock.setDelay(nanoseconds: 2_300_000_000)

        let vm = ChatViewModel(api: mock)
        let task = Task { await vm.sendText("最近睡眠不好") }

        try await Task.sleep(nanoseconds: 1_950_000_000)
        XCTAssertTrue(vm.sending)
        XCTAssertGreaterThanOrEqual(vm.thinkingProgressItems.count, 1)
        XCTAssertTrue(vm.thinkingProgressItems.contains { $0.contains("识别") })
        XCTAssertTrue(vm.thinkingHint.contains("会话") || vm.thinkingHint.contains("数据范围"))
        XCTAssertFalse(vm.thinkingProgressItems.contains(vm.thinkingHint))
        XCTAssertFalse(vm.thinkingProgressItems.contains { $0.contains("文献") })

        await task.value
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

        XCTAssertEqual(vm.messages.count, 1)
        XCTAssertEqual(vm.messages[0].role, "user")
        XCTAssertEqual(vm.messages[0].status, .failed)
        XCTAssertNotNil(vm.errorMessage)
    }

    func testProcessingReplayDoesNotCreateAssistantBubble() async throws {
        let mock = MockAPIService()
        let response = ChatResponse(
            summary: "这条消息已收到，小捷仍在处理中，请稍后查看历史对话。",
            thread_id: "thread-processing",
            response_state: "processing"
        )
        try await mock.setResponse(for: "/api/chat/stream", value: response)

        let vm = ChatViewModel(api: mock)
        await vm.sendText("重试上一条问题")

        XCTAssertEqual(vm.messages.count, 1)
        XCTAssertEqual(vm.messages.first?.role, "user")
        XCTAssertEqual(vm.messages.first?.status, .sent)
        XCTAssertEqual(vm.threadId, "thread-processing")
        XCTAssertEqual(vm.errorMessage, response.summary)
    }

    func testNewChatClearsState() async throws {
        let mock = MockAPIService()
        let response = ChatResponse(summary: nil, analysis: nil, answer_markdown: "hi", confidence: nil, followups: nil, thread_id: "t1", citations: nil)
        try await mock.setResponse(for: "/api/chat/stream", value: response)

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

    func testServerRouteDrivesProgressAndIsRetainedForDiagnostics() async throws {
        let mock = MockAPIService()
        let route = ChatInteractionRoute(
            version: "2026-07-10",
            route_id: "llm.health.deep",
            strategy: "llm",
            primary_intent: "trend_analysis",
            depth: "deep",
            safety_level: "low",
            subject_type: "self",
            needs_literature: true,
            max_followups: 1,
            progress_steps: ["已核对 HRV 来源和时效", "正在检索相关医学证据"]
        )
        let response = ChatResponse(
            summary: "已完成 HRV 分析",
            analysis: "HRV 的完整分析正文，包含数据来源、时间、判断依据和下一步行动。",
            answer_markdown: "HRV 的完整分析正文，包含数据来源、时间、判断依据和下一步行动。",
            message_id: "42",
            interaction_route: route
        )
        await mock.setChatStreamEvents([.route(route), .done(response)])

        let vm = ChatViewModel(api: mock)
        await vm.sendText("帮我分析最近 HRV")

        XCTAssertEqual(vm.activeRoute?.route_id, "llm.health.deep")
        XCTAssertEqual(vm.messages.last?.id, "server-42")
        XCTAssertEqual(vm.messages.last?.content, "HRV 的完整分析正文，包含数据来源、时间、判断依据和下一步行动。")
        XCTAssertFalse(vm.messages.last?.hasDistinctAnalysis ?? true)
    }

    func testDeepHealthResponseShowsCompleteBodyInsteadOfShortSummary() async throws {
        let mock = MockAPIService()
        let route = ChatInteractionRoute(
            version: "2026-07-10",
            route_id: "llm.health.deep",
            strategy: "llm",
            primary_intent: "causal_assessment",
            depth: "deep",
            safety_level: "medium",
            subject_type: "self",
            needs_literature: true,
            max_followups: 1,
            progress_steps: []
        )
        let fullAnswer = "**直接结论**\n鼻炎可通过鼻塞加重睡眠问题；只有严重脊柱侧弯伴肺功能受限时才支持夜间低氧，需要客观检查确认。"
        await mock.setChatStreamEvents([.done(ChatResponse(
            summary: "可能有关，但",
            analysis: fullAnswer,
            answer_markdown: fullAnswer,
            interaction_route: route
        ))])

        let vm = ChatViewModel(api: mock)
        await vm.sendText("我的失眠抑郁是不是跟鼻炎脊柱侧弯导致缺氧有关系")

        XCTAssertEqual(vm.messages.last?.content, "**直接结论**\n鼻炎可通过鼻塞加重睡眠问题；只有严重脊柱侧弯伴肺功能受限时才支持夜间低氧，需要客观检查确认。")
        XCTAssertNil(vm.messages.last?.analysis)
    }

    func testIncompleteSummaryFallsBackToCompleteAnswerForStandardRoute() async throws {
        let mock = MockAPIService()
        let complete = "鼻炎可能通过鼻塞和夜间呼吸不畅影响睡眠，但是否存在缺氧需要血氧或睡眠监测确认。"
        try await mock.setResponse(
            for: "/api/chat/stream",
            value: ChatResponse(summary: "鼻炎可能影响睡眠，但", analysis: complete, answer_markdown: complete)
        )

        let vm = ChatViewModel(api: mock)
        await vm.sendText("鼻炎和失眠有关系吗")

        XCTAssertEqual(vm.messages.last?.content, complete)
    }

    func testLooksIncompleteDetectsDanglingSentenceAndMarkdown() {
        XCTAssertTrue(ChatViewModel.looksIncomplete("鼻炎可能影响睡眠，但"))
        XCTAssertTrue(ChatViewModel.looksIncomplete("鼻炎可能影响睡眠，但[1]"))
        XCTAssertTrue(ChatViewModel.looksIncomplete("鼻炎可能影响睡眠，但[1]。"))
        XCTAssertTrue(ChatViewModel.looksIncomplete("鼻炎可能影响睡眠，但。[1]"))
        XCTAssertTrue(ChatViewModel.looksIncomplete("鼻炎可能影响睡眠，但[1][2]。"))
        XCTAssertTrue(ChatViewModel.looksIncomplete("**结论"))
        XCTAssertFalse(ChatViewModel.looksIncomplete("鼻炎可能影响睡眠，但需要进一步评估。"))
        XCTAssertFalse(ChatViewModel.looksIncomplete("鼻炎可能影响睡眠，但需要进一步评估。[1]"))
        XCTAssertFalse(ChatViewModel.looksIncomplete("结论完整。[1]"))
    }

    func testNewChatWhileRequestIsInFlightDoesNotReceiveOldAnswer() async throws {
        let mock = MockAPIService()
        let response = ChatResponse(summary: "旧会话回答", thread_id: "old-thread")
        try await mock.setResponse(for: "/api/chat/stream", value: response)
        await mock.setDelay(nanoseconds: 300_000_000)

        let vm = ChatViewModel(api: mock)
        let task = Task { await vm.sendText("旧会话问题") }
        try await Task.sleep(nanoseconds: 50_000_000)
        vm.newChat()
        await task.value

        XCTAssertTrue(vm.messages.isEmpty)
        XCTAssertNil(vm.threadId)
        XCTAssertFalse(vm.sending)
    }

    func testConsentFailureRequiresExplicitUserAction() async {
        let mock = MockAPIService()
        await mock.setError(APIError.httpError(403, "需要授权"))

        let vm = ChatViewModel(api: mock)
        await vm.sendText("帮我分析睡眠")

        XCTAssertTrue(vm.showAIConsentPrompt)
        XCTAssertEqual(vm.messages.count, 1)
        XCTAssertEqual(vm.messages.first?.status, .failed)
        let requestedPaths = await mock.getRequestedPaths()
        XCTAssertEqual(requestedPaths, ["/api/chat/stream"])
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
