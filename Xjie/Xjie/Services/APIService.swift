import Foundation
import os

/// API 请求封装 — 自动携带 JWT Token，401 时自动刷新
/// SEC-02: 消除所有 force unwrap
/// SEC-03: 使用 AppEnvironment 配置 baseURL
/// ERR-02: 使用 refreshTask 合并并发 token 刷新
/// ARCH-01: 遵循 APIServiceProtocol
/// NET-02: 非 401 错误自动重试（指数退避）
/// NET-04: 请求超时配置
actor APIService: APIServiceProtocol {
    static let shared = APIService()

    private let baseURL: String = AppEnvironment.apiBaseURL

    /// 统一网络会话。名称保留以兼容现有图片/原件加载调用方，TLS 完全交由系统校验。
    nonisolated let trustedSession: URLSession = {
        let config = URLSessionConfiguration.default
        // Foreground interactions must fail into a retryable UI state instead of
        // remaining on "sending" while iOS waits indefinitely for connectivity.
        config.waitsForConnectivity = false
        config.requestCachePolicy = .reloadIgnoringLocalCacheData
        config.urlCache = nil
        config.httpCookieStorage = nil
        return URLSession(configuration: config)
    }()

    private var session: URLSession { trustedSession }

    private struct RefreshOperation {
        let id: UUID
        let accessToken: String
        let task: Task<Void, Error>
    }

    // Token-bound refresh prevents an old request from clearing a newer login session.
    private var refreshOperation: RefreshOperation?

    // MARK: - 便捷方法

    func get<T: Decodable>(_ path: String, timeout: TimeInterval? = nil) async throws -> T {
        try await request(path, method: "GET", timeout: timeout)
    }

    func post<T: Decodable>(_ path: String, body: Encodable? = nil, timeout: TimeInterval? = nil) async throws -> T {
        try await request(path, method: "POST", body: body, timeout: timeout)
    }

    func postAccountBound<T: Decodable>(
        _ path: String,
        body: Encodable? = nil,
        expectedAccountScope: String,
        timeout: TimeInterval? = nil
    ) async throws -> T {
        let snapshot = await Self.accountBoundAuthSnapshot()
        guard snapshot.accountScope == expectedAccountScope, !snapshot.token.isEmpty else {
            throw APIError.accountScopeChanged
        }
        let bodyData = try body.map { try JSONEncoder().encode(AnyEncodable($0)) }
        return try await accountBoundRequest(
            path,
            bodyData: bodyData,
            expectedAccountScope: expectedAccountScope,
            token: snapshot.token,
            timeout: timeout,
            retried: false,
            retryCount: 0
        )
    }

    func postChatStream(
        _ request: ChatRequest,
        timeout: TimeInterval? = nil
    ) async throws -> AsyncThrowingStream<ChatStreamEvent, Error> {
        try await openChatStream(request, timeout: timeout, retried: false)
    }

    func patch<T: Decodable>(_ path: String, body: Encodable? = nil) async throws -> T {
        try await request(path, method: "PATCH", body: body)
    }

    func put<T: Decodable>(_ path: String, body: Encodable? = nil) async throws -> T {
        try await request(path, method: "PUT", body: body)
    }

    func delete<T: Decodable>(_ path: String) async throws -> T {
        try await request(path, method: "DELETE")
    }

    func postVoid(_ path: String, body: Encodable? = nil) async throws {
        let _: EmptyResponse = try await request(path, method: "POST", body: body)
    }

    func patchVoid(_ path: String, body: Encodable? = nil) async throws {
        let _: EmptyResponse = try await request(path, method: "PATCH", body: body)
    }

    func putVoid(_ path: String, body: Encodable? = nil) async throws {
        let _: EmptyResponse = try await request(path, method: "PUT", body: body)
    }

    func deleteVoid(_ path: String) async throws {
        let _: EmptyResponse = try await request(path, method: "DELETE")
    }

    // MARK: - 通用请求

    private func openChatStream(
        _ body: ChatRequest,
        timeout: TimeInterval?,
        retried: Bool
    ) async throws -> AsyncThrowingStream<ChatStreamEvent, Error> {
        let path = "/api/chat/stream"
        let auth = await AuthManager.shared
        let token = await auth.token
        guard !token.isEmpty else {
            await auth.logout()
            throw APIError.notLoggedIn
        }
        guard let url = URL(string: baseURL + path) else {
            throw APIError.invalidURL(path)
        }

        var urlRequest = URLRequest(url: url)
        urlRequest.httpMethod = "POST"
        urlRequest.timeoutInterval = timeout ?? APIConstants.llmTimeout
        urlRequest.setValue("application/json", forHTTPHeaderField: "Content-Type")
        urlRequest.setValue("text/event-stream", forHTTPHeaderField: "Accept")
        urlRequest.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        urlRequest.httpBody = try JSONEncoder().encode(body)

        AppLogger.network.debug("POST \(path) [SSE]")
        let (bytes, response) = try await session.bytes(for: urlRequest)
        guard let httpResponse = response as? HTTPURLResponse else {
            bytes.task.cancel()
            throw APIError.invalidResponse
        }

        if httpResponse.statusCode == 401, await auth.isUIValidationSession {
            bytes.task.cancel()
            throw APIError.notLoggedIn
        }

        if Self.shouldAttemptTokenRefresh(path: path, statusCode: httpResponse.statusCode, retried: retried) {
            bytes.task.cancel()
            if await auth.token != token {
                return try await openChatStream(body, timeout: timeout, retried: true)
            }
            try await ensureTokenRefreshed(expectedAccessToken: token)
            return try await openChatStream(body, timeout: timeout, retried: true)
        }

        guard (200..<300).contains(httpResponse.statusCode) else {
            var errorData = Data()
            for try await byte in bytes.prefix(64 * 1024) {
                errorData.append(byte)
            }
            let detail = try? JSONDecoder().decode(ErrorDetail.self, from: errorData)
            throw APIError.httpError(httpResponse.statusCode, detail?.detail ?? "问答请求失败")
        }

        let networkTask = bytes.task
        return AsyncThrowingStream { continuation in
            let parserTask = Task {
                do {
                    for try await line in bytes.lines {
                        try Task.checkCancellation()
                        guard line.hasPrefix("data:") else { continue }
                        let payload = line.dropFirst(5).trimmingCharacters(in: .whitespaces)
                        guard !payload.isEmpty, let data = payload.data(using: .utf8) else { continue }
                        let envelope = try JSONDecoder().decode(ChatStreamEnvelope.self, from: data)
                        switch envelope.type {
                        case "route":
                            if let route = envelope.route { continuation.yield(.route(route)) }
                        case "progress":
                            if let step = envelope.step { continuation.yield(.progress(step)) }
                        case "token":
                            if let delta = envelope.delta { continuation.yield(.token(delta)) }
                        case "done":
                            guard let result = envelope.result else { throw APIError.invalidResponse }
                            continuation.yield(.done(result))
                        case "error":
                            throw APIError.httpError(503, envelope.message ?? "这次回答没有完成，请重试")
                        default:
                            continue
                        }
                    }
                    continuation.finish()
                } catch is CancellationError {
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: error)
                }
            }
            continuation.onTermination = { @Sendable _ in
                parserTask.cancel()
                networkTask.cancel()
            }
        }
    }

    private func request<T: Decodable>(
        _ path: String,
        method: String,
        body: Encodable? = nil,
        timeout: TimeInterval? = nil,
        retried: Bool = false,
        retryCount: Int = 0
    ) async throws -> T {
        let auth = await AuthManager.shared
        let token = await auth.token

        if !path.hasPrefix("/api/auth/") && !path.hasPrefix("/api/app-version") && token.isEmpty {
            await auth.logout()
            throw APIError.notLoggedIn
        }

        // SEC-02: 安全构建 URL（消除 force unwrap）
        guard let url = URL(string: baseURL + path) else {
            throw APIError.invalidURL(path)
        }

        var urlRequest = URLRequest(url: url)
        urlRequest.httpMethod = method
        // NET-04: 请求超时
        urlRequest.timeoutInterval = timeout ?? APIConstants.requestTimeout
        urlRequest.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if !token.isEmpty {
            urlRequest.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }

        if let body {
            urlRequest.httpBody = try JSONEncoder().encode(AnyEncodable(body))
        }

        AppLogger.network.debug("\(method) \(path)")

        // NET-02: 网络错误自动重试
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: urlRequest)
        } catch let error as URLError where retryCount < APIConstants.maxRetries {
            if error.code == .timedOut || error.code == .networkConnectionLost || error.code == .notConnectedToInternet {
                let delay = UInt64(pow(2.0, Double(retryCount))) * 1_000_000_000
                AppLogger.network.warning("Retry \(retryCount + 1) for \(path) after \(error.code.rawValue)")
                try await Task.sleep(nanoseconds: delay)
                return try await request(path, method: method, body: body, timeout: timeout, retried: retried, retryCount: retryCount + 1)
            }
            throw error
        }

        // SEC-02: 安全类型转换（消除 as! 强制转换）
        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.invalidResponse
        }

        if httpResponse.statusCode == 401, await auth.isUIValidationSession {
            throw APIError.notLoggedIn
        }

        // ERR-02: 401 自动刷新 Token，使用 refreshTask 合并并发请求。
        // 匿名登录/注册/重置入口的 401 必须保留后端错误文案，不能改写成“未登录”。
        if Self.shouldAttemptTokenRefresh(path: path, statusCode: httpResponse.statusCode, retried: retried) {
            if await auth.token != token {
                return try await request(path, method: method, body: body, timeout: timeout, retried: true, retryCount: retryCount)
            }
            try await ensureTokenRefreshed(expectedAccessToken: token)
            return try await request(path, method: method, body: body, timeout: timeout, retried: true, retryCount: retryCount)
        }

        // NET-02: 5xx 服务端错误自动重试
        if (500...599).contains(httpResponse.statusCode) && retryCount < APIConstants.maxRetries {
            let delay = UInt64(pow(2.0, Double(retryCount))) * 1_000_000_000
            AppLogger.network.warning("Retry \(retryCount + 1) for \(path) (HTTP \(httpResponse.statusCode))")
            try await Task.sleep(nanoseconds: delay)
            return try await request(path, method: method, body: body, timeout: timeout, retried: retried, retryCount: retryCount + 1)
        }

        guard (200..<300).contains(httpResponse.statusCode) else {
            let detail = try? JSONDecoder().decode(ErrorDetail.self, from: data)
            throw APIError.httpError(httpResponse.statusCode, detail?.detail ?? "请求失败")
        }

        if data.isEmpty || T.self == EmptyResponse.self {
            if let empty = EmptyResponse() as? T { return empty }
        }

        return try JSONDecoder().decode(T.self, from: data)
    }

    private func accountBoundRequest<T: Decodable>(
        _ path: String,
        bodyData: Data?,
        expectedAccountScope: String,
        token: String,
        timeout: TimeInterval?,
        retried: Bool,
        retryCount: Int
    ) async throws -> T {
        let currentScope = await Self.accountBoundAuthSnapshot().accountScope
        guard Self.shouldContinueAccountBoundRequest(
            expectedAccountScope: expectedAccountScope,
            currentAccountScope: currentScope
        ) else {
            throw APIError.accountScopeChanged
        }
        guard let url = URL(string: baseURL + path) else {
            throw APIError.invalidURL(path)
        }

        var urlRequest = URLRequest(url: url)
        urlRequest.httpMethod = "POST"
        urlRequest.timeoutInterval = timeout ?? APIConstants.requestTimeout
        urlRequest.setValue("application/json", forHTTPHeaderField: "Content-Type")
        urlRequest.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        urlRequest.httpBody = bodyData

        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: urlRequest)
        } catch let error as URLError {
            let isRetriable = error.code == .timedOut
                || error.code == .networkConnectionLost
                || error.code == .notConnectedToInternet
            guard isRetriable, retryCount < APIConstants.maxRetries else { throw error }
            try await waitBeforeAccountBoundRetry(
                expectedAccountScope: expectedAccountScope,
                retryCount: retryCount
            )
            return try await accountBoundRequest(
                path,
                bodyData: bodyData,
                expectedAccountScope: expectedAccountScope,
                token: token,
                timeout: timeout,
                retried: retried,
                retryCount: retryCount + 1
            )
        }

        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.invalidResponse
        }

        if Self.shouldAttemptTokenRefresh(path: path, statusCode: httpResponse.statusCode, retried: retried) {
            let current = await Self.accountBoundAuthSnapshot()
            switch Self.accountBoundRetryDecision(
                expectedAccountScope: expectedAccountScope,
                originalToken: token,
                current: current
            ) {
            case .abort:
                throw APIError.accountScopeChanged
            case .retry(let currentToken):
                return try await accountBoundRequest(
                    path,
                    bodyData: bodyData,
                    expectedAccountScope: expectedAccountScope,
                    token: currentToken,
                    timeout: timeout,
                    retried: true,
                    retryCount: retryCount
                )
            case .refresh:
                try await ensureTokenRefreshed(expectedAccessToken: token)
                let refreshed = await Self.accountBoundAuthSnapshot()
                guard refreshed.accountScope == expectedAccountScope,
                      !refreshed.token.isEmpty,
                      refreshed.token != token else {
                    throw APIError.accountScopeChanged
                }
                return try await accountBoundRequest(
                    path,
                    bodyData: bodyData,
                    expectedAccountScope: expectedAccountScope,
                    token: refreshed.token,
                    timeout: timeout,
                    retried: true,
                    retryCount: retryCount
                )
            }
        }

        if (500...599).contains(httpResponse.statusCode) && retryCount < APIConstants.maxRetries {
            try await waitBeforeAccountBoundRetry(
                expectedAccountScope: expectedAccountScope,
                retryCount: retryCount
            )
            return try await accountBoundRequest(
                path,
                bodyData: bodyData,
                expectedAccountScope: expectedAccountScope,
                token: token,
                timeout: timeout,
                retried: retried,
                retryCount: retryCount + 1
            )
        }

        guard (200..<300).contains(httpResponse.statusCode) else {
            throw APIError.httpErrorResponse(
                httpResponse.statusCode,
                Self.errorMessage(from: data, fallback: "请求失败"),
                data
            )
        }

        if data.isEmpty || T.self == EmptyResponse.self {
            if let empty = EmptyResponse() as? T { return empty }
        }
        return try JSONDecoder().decode(T.self, from: data)
    }

    private func waitBeforeAccountBoundRetry(
        expectedAccountScope: String,
        retryCount: Int
    ) async throws {
        let beforeBackoff = await Self.accountBoundAuthSnapshot().accountScope
        guard Self.shouldRetryAccountBoundTransport(
            expectedAccountScope: expectedAccountScope,
            currentAccountScope: beforeBackoff,
            retryCount: retryCount
        ) else {
            throw APIError.accountScopeChanged
        }

        let delay = UInt64(pow(2.0, Double(retryCount))) * 1_000_000_000
        try await Task.sleep(nanoseconds: delay)

        let afterBackoff = await Self.accountBoundAuthSnapshot().accountScope
        guard Self.shouldRetryAccountBoundTransport(
            expectedAccountScope: expectedAccountScope,
            currentAccountScope: afterBackoff,
            retryCount: retryCount
        ) else {
            throw APIError.accountScopeChanged
        }
    }

    // MARK: - ERR-02: Token 刷新（合并并发请求）

    private func ensureTokenRefreshed(expectedAccessToken: String) async throws {
        let auth = await AuthManager.shared
        guard await auth.token == expectedAccessToken else { return }

        if let existing = refreshOperation,
           existing.accessToken == expectedAccessToken {
            try await existing.task.value
            return
        }

        let operationID = UUID()
        let task = Task<Void, Error> { [weak self] in
            guard let self else { return }
            try await self.performTokenRefresh(expectedAccessToken: expectedAccessToken)
        }
        refreshOperation = RefreshOperation(id: operationID, accessToken: expectedAccessToken, task: task)
        do {
            try await task.value
            clearRefreshOperation(id: operationID)
        } catch {
            clearRefreshOperation(id: operationID)
            throw error
        }
    }

    private func clearRefreshOperation(id: UUID) {
        guard refreshOperation?.id == id else { return }
        refreshOperation = nil
    }

    struct AccountBoundAuthSnapshot: Equatable, Sendable {
        let token: String
        let accountScope: String?
    }

    enum AccountBoundRetryDecision: Equatable {
        case abort
        case retry(String)
        case refresh
    }

    @MainActor
    private static func accountBoundAuthSnapshot() -> AccountBoundAuthSnapshot {
        let auth = AuthManager.shared
        return AccountBoundAuthSnapshot(token: auth.token, accountScope: auth.accountScope)
    }

    static func accountBoundRetryDecision(
        expectedAccountScope: String,
        originalToken: String,
        current: AccountBoundAuthSnapshot
    ) -> AccountBoundRetryDecision {
        guard current.accountScope == expectedAccountScope, !current.token.isEmpty else {
            return .abort
        }
        if current.token != originalToken {
            return .retry(current.token)
        }
        return .refresh
    }

    static func shouldContinueAccountBoundRequest(
        expectedAccountScope: String,
        currentAccountScope: String?
    ) -> Bool {
        currentAccountScope == expectedAccountScope
    }

    static func shouldRetryAccountBoundTransport(
        expectedAccountScope: String,
        currentAccountScope: String?,
        retryCount: Int
    ) -> Bool {
        retryCount < APIConstants.maxRetries
            && shouldContinueAccountBoundRequest(
                expectedAccountScope: expectedAccountScope,
                currentAccountScope: currentAccountScope
            )
    }

    static func errorMessage(from data: Data, fallback: String) -> String {
        (try? JSONDecoder().decode(ErrorDetail.self, from: data))?.detail ?? fallback
    }

    private static let anonymousAuthPaths: Set<String> = [
        "/api/auth/login",
        "/api/auth/login-subject",
        "/api/auth/signup",
        "/api/auth/wx-login",
        "/api/auth/password/reset/request",
        "/api/auth/password/reset/confirm",
        "/api/auth/refresh"
    ]

    static func shouldAttemptTokenRefresh(path: String, statusCode: Int, retried: Bool) -> Bool {
        statusCode == 401 && !retried && !anonymousAuthPaths.contains(Self.normalizedPath(path))
    }

    private static func normalizedPath(_ path: String) -> String {
        String(path.split(separator: "?", maxSplits: 1, omittingEmptySubsequences: false).first ?? Substring(path))
    }

    private func performTokenRefresh(expectedAccessToken: String) async throws {
        let auth = await AuthManager.shared
        guard await auth.token == expectedAccessToken else { return }
        let rt = await auth.refreshToken
        guard !rt.isEmpty else {
            await auth.logout(ifCurrentToken: expectedAccessToken)
            throw APIError.notLoggedIn
        }

        struct RefreshBody: Encodable { let refresh_token: String }
        struct RefreshResponse: Decodable { let access_token: String; let refresh_token: String? }

        guard let url = URL(string: baseURL + "/api/auth/refresh") else {
            throw APIError.invalidURL("/api/auth/refresh")
        }

        var urlRequest = URLRequest(url: url)
        urlRequest.httpMethod = "POST"
        urlRequest.timeoutInterval = APIConstants.requestTimeout
        urlRequest.setValue("application/json", forHTTPHeaderField: "Content-Type")
        urlRequest.httpBody = try JSONEncoder().encode(RefreshBody(refresh_token: rt))

        let (data, response) = try await session.data(for: urlRequest)
        guard await auth.token == expectedAccessToken else { return }

        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.invalidResponse
        }

        if httpResponse.statusCode == 200,
           let res = try? JSONDecoder().decode(RefreshResponse.self, from: data) {
            await auth.setAuth(accessToken: res.access_token, refreshToken: res.refresh_token ?? "")
        } else {
            await auth.logout(ifCurrentToken: expectedAccessToken)
            throw APIError.notLoggedIn
        }
    }

    // MARK: - 上传文件

    func uploadFile(_ path: String, fileData: Data, fileName: String, mimeType: String, formData: [String: String] = [:]) async throws -> Data {
        try await uploadFileRequest(
            path,
            fileData: fileData,
            fileName: fileName,
            mimeType: mimeType,
            formData: formData,
            retried: false
        )
    }

    private func uploadFileRequest(_ path: String, fileData: Data, fileName: String, mimeType: String, formData: [String: String], retried: Bool) async throws -> Data {
        let auth = await AuthManager.shared
        let token = await auth.token
        let boundary = UUID().uuidString

        guard let url = URL(string: baseURL + path) else {
            throw APIError.invalidURL(path)
        }

        var urlRequest = URLRequest(url: url)
        urlRequest.httpMethod = "POST"
        // NET-04: 上传超时 60s
        urlRequest.timeoutInterval = APIConstants.uploadTimeout
        urlRequest.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        if !token.isEmpty {
            urlRequest.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }

        var body = Data()
        for (key, value) in formData {
            body.append(Data("--\(boundary)\r\n".utf8))
            body.append(Data("Content-Disposition: form-data; name=\"\(key)\"\r\n\r\n".utf8))
            body.append(Data("\(value)\r\n".utf8))
        }
        body.append(Data("--\(boundary)\r\n".utf8))
        body.append(Data("Content-Disposition: form-data; name=\"file\"; filename=\"\(fileName)\"\r\n".utf8))
        body.append(Data("Content-Type: \(mimeType)\r\n\r\n".utf8))
        body.append(fileData)
        body.append(Data("\r\n--\(boundary)--\r\n".utf8))

        urlRequest.httpBody = body

        let (data, response) = try await session.data(for: urlRequest)

        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.invalidResponse
        }
        if Self.shouldAttemptTokenRefresh(path: path, statusCode: httpResponse.statusCode, retried: retried) {
            if await auth.token != token {
                return try await uploadFileRequest(
                    path,
                    fileData: fileData,
                    fileName: fileName,
                    mimeType: mimeType,
                    formData: formData,
                    retried: true
                )
            }
            try await ensureTokenRefreshed(expectedAccessToken: token)
            return try await uploadFileRequest(
                path,
                fileData: fileData,
                fileName: fileName,
                mimeType: mimeType,
                formData: formData,
                retried: true
            )
        }

        guard (200..<300).contains(httpResponse.statusCode) else {
            let detail = try? JSONDecoder().decode(ErrorDetail.self, from: data)
            throw APIError.httpError(httpResponse.statusCode, detail?.detail ?? "上传失败")
        }
        return data
    }
}

// MARK: - 辅助类型

enum APIError: LocalizedError {
    case notLoggedIn
    case accountScopeChanged
    case httpError(Int, String)
    case httpErrorResponse(Int, String, Data)
    case invalidURL(String)
    case invalidResponse

    var errorDescription: String? {
        switch self {
        case .notLoggedIn: return "未登录"
        case .accountScopeChanged: return "登录账号已变化，已停止本次请求"
        case .httpError(_, let msg): return msg
        case .httpErrorResponse(_, let msg, _): return msg
        case .invalidURL(let path): return "无效的请求地址: \(path)"
        case .invalidResponse: return "服务器响应异常"
        }
    }
}

struct EmptyResponse: Decodable {
    init() {}
    init(from decoder: Decoder) throws {}
}

private struct ErrorDetail: Decodable {
    let detail: String?

    private struct StructuredDetail: Decodable {
        let message: String?
        let code: String?
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        // detail 可能是 String 或 {"error_code":..., "message":...} 字典
        if let str = try? container.decode(String.self, forKey: .detail) {
            detail = str
        } else if let structured = try? container.decode(StructuredDetail.self, forKey: .detail) {
            detail = structured.message ?? structured.code
        } else {
            detail = nil
        }
    }

    private enum CodingKeys: String, CodingKey { case detail }
}

/// 类型擦除的 Encodable 包装
private struct AnyEncodable: Encodable {
    private let _encode: (Encoder) throws -> Void
    init(_ wrapped: Encodable) {
        _encode = { try wrapped.encode(to: $0) }
    }
    func encode(to encoder: Encoder) throws {
        try _encode(encoder)
    }
}
