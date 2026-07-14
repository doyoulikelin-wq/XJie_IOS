import Foundation

/// API 服务协议 — ARCH-01: 支持依赖注入和测试 Mock
protocol APIServiceProtocol: Sendable {
    func get<T: Decodable>(_ path: String, timeout: TimeInterval?) async throws -> T
    func post<T: Decodable>(_ path: String, body: Encodable?, timeout: TimeInterval?) async throws -> T
    /// Performs a protected POST whose bearer token is cryptographically/account scoped.
    /// A retry must never adopt a token from a different authenticated account.
    func postAccountBound<T: Decodable>(
        _ path: String,
        body: Encodable?,
        expectedAccountScope: String,
        timeout: TimeInterval?
    ) async throws -> T
    func postChatStream(_ request: ChatRequest, timeout: TimeInterval?) async throws -> AsyncThrowingStream<ChatStreamEvent, Error>
    func patch<T: Decodable>(_ path: String, body: Encodable?) async throws -> T
    func put<T: Decodable>(_ path: String, body: Encodable?) async throws -> T
    func delete<T: Decodable>(_ path: String) async throws -> T
    func postVoid(_ path: String, body: Encodable?) async throws
    func patchVoid(_ path: String, body: Encodable?) async throws
    func putVoid(_ path: String, body: Encodable?) async throws
    func deleteVoid(_ path: String) async throws
    func uploadFile(_ path: String, fileData: Data, fileName: String, mimeType: String, formData: [String: String]) async throws -> Data
}

/// 提供默认 body=nil 的便捷方法，避免调用方每次传 nil
extension APIServiceProtocol {
    func get<T: Decodable>(_ path: String) async throws -> T {
        try await get(path, timeout: nil)
    }
    func post<T: Decodable>(_ path: String, body: Encodable? = nil, timeout: TimeInterval? = nil) async throws -> T {
        try await post(path, body: body, timeout: timeout)
    }
    func postAccountBound<T: Decodable>(
        _ path: String,
        body: Encodable? = nil,
        expectedAccountScope: String,
        timeout: TimeInterval? = nil
    ) async throws -> T {
        try await postAccountBound(
            path,
            body: body,
            expectedAccountScope: expectedAccountScope,
            timeout: timeout
        )
    }
    func postVoid(_ path: String) async throws {
        try await postVoid(path, body: nil)
    }
    func patch<T: Decodable>(_ path: String) async throws -> T {
        try await patch(path, body: nil)
    }
    func patchVoid(_ path: String) async throws {
        try await patchVoid(path, body: nil)
    }
    func put<T: Decodable>(_ path: String) async throws -> T {
        try await put(path, body: nil)
    }
    func putVoid(_ path: String) async throws {
        try await putVoid(path, body: nil)
    }
}

#if DEBUG
/// Deterministic transport used only by explicit UI-automation launches.
///
/// Keeping this behind both `DEBUG` and a launch argument prevents UI tests from
/// depending on production latency while making it impossible to enter a
/// Release build. Unsupported calls fail immediately instead of silently
/// falling back to the network.
struct UIAutomationChatAPIService: APIServiceProtocol {
    static let launchArgument = "XJIE_UI_TEST_STUB_CHAT"

    static func isEnabled(arguments: [String]) -> Bool {
        arguments.contains(launchArgument)
    }

    static func isSupportedConversationGET(_ path: String) -> Bool {
        UIAutomationRequestContract.isSupportedConversationGET(path)
    }

    private func unsupported(_ path: String) -> UIAutomationChatAPIError {
        UIAutomationNetworkAudit.shared.record(handled: false)
        return .unsupported(path)
    }

    func get<T: Decodable>(_ path: String, timeout: TimeInterval?) async throws -> T {
        guard Self.isSupportedConversationGET(path) else {
            throw unsupported(path)
        }
        UIAutomationNetworkAudit.shared.record(handled: true)
        return try JSONDecoder().decode(T.self, from: Data("[]".utf8))
    }

    func post<T: Decodable>(
        _ path: String,
        body: Encodable?,
        timeout: TimeInterval?
    ) async throws -> T {
        throw unsupported(path)
    }

    func postAccountBound<T: Decodable>(
        _ path: String,
        body: Encodable?,
        expectedAccountScope: String,
        timeout: TimeInterval?
    ) async throws -> T {
        throw unsupported(path)
    }

    func postChatStream(
        _ request: ChatRequest,
        timeout: TimeInterval?
    ) async throws -> AsyncThrowingStream<ChatStreamEvent, Error> {
        UIAutomationNetworkAudit.shared.record(handled: true)
        let response = ChatResponse(
            summary: "UI 自动化回复：\(request.message)",
            thread_id: request.thread_id ?? "ui-automation-thread",
            message_id: "ui-automation-\(request.client_message_id ?? "message")",
            response_state: "complete"
        )
        return AsyncThrowingStream { continuation in
            continuation.yield(.done(response))
            continuation.finish()
        }
    }

    func patch<T: Decodable>(_ path: String, body: Encodable?) async throws -> T {
        throw unsupported(path)
    }

    func put<T: Decodable>(_ path: String, body: Encodable?) async throws -> T {
        throw unsupported(path)
    }

    func delete<T: Decodable>(_ path: String) async throws -> T {
        throw unsupported(path)
    }

    func postVoid(_ path: String, body: Encodable?) async throws {
        throw unsupported(path)
    }

    func patchVoid(_ path: String, body: Encodable?) async throws {
        throw unsupported(path)
    }

    func putVoid(_ path: String, body: Encodable?) async throws {
        throw unsupported(path)
    }

    func deleteVoid(_ path: String) async throws {
        throw unsupported(path)
    }

    func uploadFile(
        _ path: String,
        fileData: Data,
        fileName: String,
        mimeType: String,
        formData: [String: String]
    ) async throws -> Data {
        throw unsupported(path)
    }
}

private enum UIAutomationChatAPIError: LocalizedError, Sendable {
    case unsupported(String)

    var errorDescription: String? {
        switch self {
        case .unsupported(let path):
            return "UI automation chat transport received an unsupported request: \(path)"
        }
    }
}
#endif
