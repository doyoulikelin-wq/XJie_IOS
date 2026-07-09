import Foundation

/// API 服务协议 — ARCH-01: 支持依赖注入和测试 Mock
protocol APIServiceProtocol: Sendable {
    func get<T: Decodable>(_ path: String, timeout: TimeInterval?) async throws -> T
    func post<T: Decodable>(_ path: String, body: Encodable?, timeout: TimeInterval?) async throws -> T
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
