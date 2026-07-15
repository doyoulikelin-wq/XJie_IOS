import Foundation
import Combine
import os
import UIKit

#if DEBUG
enum UIAutomationRequestContract {
    private static let conversationsRoot = "/api/chat/conversations"
    private static let reportHistoryPath = "/api/health-data/report-workflows"
    private static let reportTracePath = "/api/health-data/report-workflows/4242/trace"
    private static let reportAssetContentPath = "/api/health-data/report-workflows/4242/assets/5/content"
    private static let reportReviewPath = "/api/health-data/report-workflows/4242/review"
    private static let reportInterpretationPath = "/api/health-data/report-workflows/4242/interpretation"
    private static let trustedMedicationTodayPath = "/api/medications/trust/today"

    static func hasAllowedConversationListQuery(_ components: URLComponents) -> Bool {
        let items = components.queryItems ?? []
        let allowed = Set(["limit", "offset"])
        guard !(components.percentEncodedQuery != nil && items.isEmpty),
              items.count == Set(items.map(\.name)).count,
              items.allSatisfy({ allowed.contains($0.name) })
        else { return false }
        return items.allSatisfy { item in
            guard let raw = item.value,
                  let value = Int(raw),
                  value >= 0
            else { return false }
            return item.name != "limit" || value > 0
        }
    }

    static func isSupportedConversationGET(_ path: String) -> Bool {
        guard let components = URLComponents(string: "https://ui-automation.invalid\(path)"),
              components.fragment == nil
        else { return false }
        if components.path == conversationsRoot {
            return hasAllowedConversationListQuery(components)
        }
        let detail = components.path.dropFirst(conversationsRoot.count + 1)
        return components.path.hasPrefix(conversationsRoot + "/")
            && !detail.isEmpty
            && !detail.contains("/")
            && components.percentEncodedQuery == nil
    }

    static func hasAllowedDocumentListQuery(_ components: URLComponents) -> Bool {
        let items = components.queryItems ?? []
        guard items.count == 1,
              items[0].name == "doc_type",
              let value = items[0].value else { return false }
        return value == "exam" || value == "record"
    }

    static func hasAllowedReportHistoryQuery(_ components: URLComponents) -> Bool {
        guard components.path == reportHistoryPath else { return false }
        let items = components.queryItems ?? []
        let names = items.map(\.name)
        let allowedNames = Set(["subject_user_id", "date_from", "date_to", "hospital", "report_type"])
        guard !items.isEmpty,
              names.count == Set(names).count,
              Set(names).isSubset(of: allowedNames),
              items.first(where: { $0.name == "subject_user_id" })?.value == "1"
        else { return false }

        for name in ["date_from", "date_to"] {
            if let item = items.first(where: { $0.name == name }),
               !isValidLocalDate(item.value ?? "") {
                return false
            }
        }
        if let from = items.first(where: { $0.name == "date_from" })?.value,
           let to = items.first(where: { $0.name == "date_to" })?.value,
           from > to {
            return false
        }
        if let hospital = items.first(where: { $0.name == "hospital" })?.value {
            let trimmed = hospital.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !trimmed.isEmpty, trimmed == hospital, hospital.count <= 256 else { return false }
        }
        if let type = items.first(where: { $0.name == "report_type" })?.value {
            guard Set(["unknown", "exam", "lab", "imaging", "medical_record", "other"]).contains(type) else {
                return false
            }
        }
        return true
    }

    static func hasAllowedReportTraceQuery(_ components: URLComponents) -> Bool {
        hasExactSubjectQuery(components, path: reportTracePath)
    }

    static func hasAllowedReportAssetContentQuery(_ components: URLComponents) -> Bool {
        hasExactSubjectQuery(components, path: reportAssetContentPath)
    }

    static func hasAllowedReportReviewQuery(_ components: URLComponents) -> Bool {
        guard components.path == reportReviewPath else { return false }
        let items = components.queryItems ?? []
        return items.count == 1
            && items[0].name == "subject_user_id"
            && items[0].value == "1"
    }

    static func hasAllowedReportInterpretationQuery(_ components: URLComponents) -> Bool {
        guard components.path == reportInterpretationPath else { return false }
        let items = components.queryItems ?? []
        return items.count == 1
            && items[0].name == "subject_user_id"
            && items[0].value == "1"
    }

    static func hasAllowedMedicationTodayQuery(_ components: URLComponents) -> Bool {
        guard components.path == trustedMedicationTodayPath else { return false }
        let items = components.queryItems ?? []
        let allowedNames = Set(["subject_user_id", "local_date", "timezone_offset_minutes"])
        let names = items.map(\.name)
        guard (items.count == 2 || items.count == 3),
              names.count == Set(names).count,
              Set(names).isSubset(of: allowedNames),
              let localDate = items.first(where: { $0.name == "local_date" })?.value,
              isValidLocalDate(localDate),
              let rawOffset = items.first(where: { $0.name == "timezone_offset_minutes" })?.value,
              let offset = Int(rawOffset),
              (-840...840).contains(offset)
        else { return false }

        let subjectItems = items.filter { $0.name == "subject_user_id" }
        return subjectItems.isEmpty
            || (subjectItems.count == 1 && subjectItems[0].value == "1")
    }

    static func hasAllowedMedicationSubjectQuery(_ components: URLComponents) -> Bool {
        let items = components.queryItems ?? []
        return items.count == 1
            && items[0].name == "subject_user_id"
            && items[0].value == "1"
    }

    static func hasAllowedProfileRevisionQuery(_ components: URLComponents) -> Bool {
        let items = components.queryItems ?? []
        let names = items.map(\.name)
        let allowed = Set(["subject_user_id", "limit", "after_revision_id"])
        guard (items.count == 2 || items.count == 3),
              names.count == Set(names).count,
              Set(names).isSubset(of: allowed),
              items.first(where: { $0.name == "subject_user_id" })?.value == "1",
              items.first(where: { $0.name == "limit" })?.value == "50"
        else { return false }
        guard let after = items.first(where: { $0.name == "after_revision_id" }) else {
            return items.count == 2
        }
        guard let raw = after.value, let value = Int(raw), value > 0 else { return false }
        return items.count == 3
    }

    private static func isValidLocalDate(_ value: String) -> Bool {
        guard value.count == 10 else { return false }
        let formatter = DateFormatter()
        formatter.calendar = Calendar(identifier: .gregorian)
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone(secondsFromGMT: 0)
        formatter.dateFormat = "yyyy-MM-dd"
        formatter.isLenient = false
        guard let date = formatter.date(from: value) else { return false }
        return formatter.string(from: date) == value
    }

    private static func hasExactSubjectQuery(_ components: URLComponents, path: String) -> Bool {
        guard components.path == path else { return false }
        let items = components.queryItems ?? []
        return items.count == 1
            && items[0].name == "subject_user_id"
            && items[0].value == "1"
    }
}

enum UIAutomationMode {
    static let launchArgument = "XJIE_UI_TEST_STUB_NETWORK"

    static func isEnabled(arguments: [String]) -> Bool {
        arguments.contains(launchArgument)
    }
}
#endif

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
    nonisolated let trustedSession: URLSession = URLSession(
        configuration: APIService.makeSessionConfiguration()
    )

    static func makeSessionConfiguration(
        arguments: [String] = ProcessInfo.processInfo.arguments
    ) -> URLSessionConfiguration {
        let config = URLSessionConfiguration.default
        // Foreground interactions must fail into a retryable UI state instead of
        // remaining on "sending" while iOS waits indefinitely for connectivity.
        config.waitsForConnectivity = false
        config.requestCachePolicy = .reloadIgnoringLocalCacheData
        config.urlCache = nil
        config.httpCookieStorage = nil
        #if DEBUG
        if UIAutomationMode.isEnabled(arguments: arguments) {
            config.protocolClasses = [UIAutomationNetworkStubURLProtocol.self]
                + (config.protocolClasses ?? [])
        }
        #endif
        return config
    }

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
            method: "POST",
            bodyData: bodyData,
            contentType: "application/json",
            expectedAccountScope: expectedAccountScope,
            token: snapshot.token,
            timeout: timeout,
            retried: false,
            retryCount: 0
        )
    }

    func patchAccountBound<T: Decodable>(
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
            method: "PATCH",
            bodyData: bodyData,
            contentType: "application/json",
            expectedAccountScope: expectedAccountScope,
            token: snapshot.token,
            timeout: timeout,
            retried: false,
            retryCount: 0
        )
    }

    func deleteVoidAccountBound(
        _ path: String,
        body: Encodable? = nil,
        expectedAccountScope: String,
        timeout: TimeInterval? = nil
    ) async throws {
        let snapshot = await Self.accountBoundAuthSnapshot()
        guard snapshot.accountScope == expectedAccountScope, !snapshot.token.isEmpty else {
            throw APIError.accountScopeChanged
        }
        let bodyData = try body.map { try JSONEncoder().encode(AnyEncodable($0)) }
        let _: EmptyResponse = try await accountBoundRequest(
            path,
            method: "DELETE",
            bodyData: bodyData,
            contentType: "application/json",
            expectedAccountScope: expectedAccountScope,
            token: snapshot.token,
            timeout: timeout,
            retried: false,
            retryCount: 0
        )
    }

    func putFileAccountBound(
        _ path: String,
        fileData: Data,
        fileName: String,
        mimeType: String,
        formData: [String: String] = [:],
        expectedAccountScope: String
    ) async throws -> Data {
        let snapshot = await Self.accountBoundAuthSnapshot()
        guard snapshot.accountScope == expectedAccountScope, !snapshot.token.isEmpty else {
            throw APIError.accountScopeChanged
        }
        let boundary = "xjie-\(UUID().uuidString.lowercased())"
        let body = try Self.makeMultipartBody(
            fileData: fileData,
            fileName: fileName,
            mimeType: mimeType,
            formData: formData,
            boundary: boundary
        )
        return try await accountBoundRequest(
            path,
            method: "PUT",
            bodyData: body,
            contentType: "multipart/form-data; boundary=\(boundary)",
            expectedAccountScope: expectedAccountScope,
            token: snapshot.token,
            timeout: APIConstants.uploadTimeout,
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
        let (bytes, response) = try await self.trustedSession.bytes(for: urlRequest)
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
            (data, response) = try await self.trustedSession.data(for: urlRequest)
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
        method: String,
        bodyData: Data?,
        contentType: String,
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
        urlRequest.httpMethod = method
        urlRequest.timeoutInterval = timeout ?? APIConstants.requestTimeout
        urlRequest.setValue(contentType, forHTTPHeaderField: "Content-Type")
        urlRequest.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        urlRequest.httpBody = bodyData

        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await self.trustedSession.data(for: urlRequest)
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
                method: method,
                bodyData: bodyData,
                contentType: contentType,
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
        let responseScope = await Self.accountBoundAuthSnapshot().accountScope
        guard Self.shouldContinueAccountBoundRequest(
            expectedAccountScope: expectedAccountScope,
            currentAccountScope: responseScope
        ) else {
            throw APIError.accountScopeChanged
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
                    method: method,
                    bodyData: bodyData,
                    contentType: contentType,
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
                    method: method,
                    bodyData: bodyData,
                    contentType: contentType,
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
                method: method,
                bodyData: bodyData,
                contentType: contentType,
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
        if let rawData = data as? T { return rawData }
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

        let (data, response) = try await self.trustedSession.data(for: urlRequest)
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

    static func makeMultipartBody(
        fileData: Data,
        fileName: String,
        mimeType: String,
        formData: [String: String],
        boundary: String
    ) throws -> Data {
        guard !boundary.isEmpty,
              !boundary.contains("\r"),
              !boundary.contains("\n"),
              fileData.range(of: Data(boundary.utf8)) == nil,
              let safeFileName = escapedMultipartHeaderToken(fileName),
              mimeType.range(
                of: #"^[A-Za-z0-9][A-Za-z0-9!#$&^_.+\-]*/[A-Za-z0-9][A-Za-z0-9!#$&^_.+\-]*$"#,
                options: .regularExpression
              ) != nil,
              !formData.values.contains(where: { $0.contains(boundary) })
        else {
            throw APIError.invalidMultipartForm("文件名、MIME 类型或边界无效")
        }

        var body = Data()
        for (key, value) in formData.sorted(by: { $0.key < $1.key }) {
            guard let safeKey = escapedMultipartHeaderToken(key) else {
                throw APIError.invalidMultipartForm("表单字段名无效")
            }
            body.append(Data("--\(boundary)\r\n".utf8))
            body.append(Data("Content-Disposition: form-data; name=\"\(safeKey)\"\r\n\r\n".utf8))
            body.append(Data("\(value)\r\n".utf8))
        }
        body.append(Data("--\(boundary)\r\n".utf8))
        body.append(Data("Content-Disposition: form-data; name=\"file\"; filename=\"\(safeFileName)\"\r\n".utf8))
        body.append(Data("Content-Type: \(mimeType)\r\n\r\n".utf8))
        body.append(fileData)
        body.append(Data("\r\n--\(boundary)--\r\n".utf8))
        return body
    }

    private static func escapedMultipartHeaderToken(_ value: String) -> String? {
        guard !value.isEmpty,
              !value.contains("\r"),
              !value.contains("\n"),
              !value.contains("\0") else { return nil }
        return value
            .replacingOccurrences(of: "\\", with: "\\\\")
            .replacingOccurrences(of: "\"", with: "\\\"")
    }

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

        urlRequest.httpBody = try Self.makeMultipartBody(
            fileData: fileData,
            fileName: fileName,
            mimeType: mimeType,
            formData: formData,
            boundary: boundary
        )

        let (data, response) = try await self.trustedSession.data(for: urlRequest)

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

#if DEBUG
/// `APIService` network boundary for UI automation.
///
/// Required UI tests opt in with an exact launch argument. Every HTTP(S)
/// request made through the required app transport is answered in-process, so
/// a newly introduced API call cannot
/// silently make the gate depend on production availability or model timing.
/// Known UI fixtures return minimal successful payloads; unknown endpoints fail
/// immediately with a deterministic client error.
final class UIAutomationNetworkStubURLProtocol: URLProtocol {
    static let launchArgument = UIAutomationMode.launchArgument

    private static let productionOrigin = URLComponents(string: AppEnvironment.apiBaseURL)

    struct StubbedResponse: Equatable {
        let statusCode: Int
        let data: Data
        let handled: Bool
    }

    static func isEnabled(arguments: [String]) -> Bool {
        UIAutomationMode.isEnabled(arguments: arguments)
    }

    static func stubbedResponse(for request: URLRequest) -> StubbedResponse {
        let method = request.httpMethod ?? "GET"
        guard let url = request.url,
              let components = URLComponents(url: url, resolvingAgainstBaseURL: false)
        else {
            return unhandledResponse(method: method, requestDescription: "<invalid URL>")
        }
        let path = components.path

        let isExactProbe = method == "GET"
            && components.scheme == "https"
            && components.host == "ui-automation.invalid"
            && components.port == nil
            && components.user == nil
            && components.password == nil
            && components.fragment == nil
            && components.percentEncodedQuery == nil
            && path == "/api/feature-flags"
            && request.value(forHTTPHeaderField: "Authorization") == nil
            && request.httpBody == nil
            && request.httpBodyStream == nil
        if isExactProbe {
            return StubbedResponse(
                statusCode: 200,
                data: Data(#"{"flags":{}}"#.utf8),
                handled: true
            )
        }

        // The login screen loads the subject catalogue before authentication.
        // Keep this public route exact and separate from authenticated fixtures so
        // the UI gate matches the production request contract instead of silently
        // teaching tests to attach a token that the app cannot have yet.
        let isExactAnonymousSubjectsRequest = method == "GET"
            && isProductionAPIRequest(components)
            && path == "/api/auth/subjects"
            && components.percentEncodedQuery == nil
            && request.value(forHTTPHeaderField: "Authorization") == nil
            && request.httpBody == nil
            && request.httpBodyStream == nil
        if isExactAnonymousSubjectsRequest {
            return StubbedResponse(statusCode: 200, data: Data("[]".utf8), handled: true)
        }

        guard isProductionAPIRequest(components),
              hasBearerAuthorization(request),
              hasAllowedQuery(components, for: path)
        else {
            return unhandledResponse(method: method, requestDescription: url.absoluteString)
        }

        switch (method, path) {
        case ("GET", "/api/feature-flags"):
            return StubbedResponse(statusCode: 200, data: Data(#"{"flags":{}}"#.utf8), handled: true)
        case ("GET", "/api/medications"):
            return StubbedResponse(statusCode: 200, data: Data(#"{"items":[]}"#.utf8), handled: true)
        case ("GET", "/api/medications/trust/today"):
            guard hasNoBody(request),
                  let localDate = components.queryItems?.first(where: { $0.name == "local_date" })?.value
            else {
                return unhandledResponse(method: method, requestDescription: "malformed medication today request")
            }
            return StubbedResponse(
                statusCode: 200,
                data: medicationTodayFixture(localDate: localDate),
                handled: true
            )
        case ("GET", "/api/medications/trust/plans"):
            guard hasNoBody(request) else {
                return unhandledResponse(method: method, requestDescription: "malformed medication plans request")
            }
            return StubbedResponse(statusCode: 200, data: trustedMedicationPlanListFixture, handled: true)
        case ("GET", "/api/medications/trust/prefill-candidates"):
            guard hasNoBody(request) else {
                return unhandledResponse(method: method, requestDescription: "malformed medication prefill request")
            }
            return StubbedResponse(statusCode: 200, data: trustedMedicationEmptyListFixture, handled: true)
        case ("GET", "/api/medications/trust/reactions"):
            guard hasNoBody(request) else {
                return unhandledResponse(method: method, requestDescription: "malformed medication reactions request")
            }
            return StubbedResponse(statusCode: 200, data: trustedMedicationEmptyListFixture, handled: true)
        case ("GET", "/api/medications/trust/long-term-summary"):
            guard hasNoBody(request) else {
                return unhandledResponse(method: method, requestDescription: "malformed long-term medication summary request")
            }
            return StubbedResponse(statusCode: 200, data: longTermMedicationSummaryFixture, handled: true)
        case ("GET", "/api/users/me"):
            return StubbedResponse(
                statusCode: 200,
                data: Data(#"{"id":"1","username":"UI Automation","is_admin":false}"#.utf8),
                handled: true
            )
        case ("GET", "/api/family/groups"),
             ("GET", "/api/family/members"),
             ("GET", "/api/family/subjects"):
            return StubbedResponse(statusCode: 200, data: Data("[]".utf8), handled: true)
        case ("GET", "/api/chat/conversations"):
            return StubbedResponse(statusCode: 200, data: Data("[]".utf8), handled: true)
        case ("GET", "/api/health-data/report-workflows"):
            guard hasNoBody(request) else {
                return unhandledResponse(method: method, requestDescription: "malformed report history request")
            }
            return StubbedResponse(statusCode: 200, data: reportWorkflowHistoryFixture, handled: true)
        case ("GET", "/api/health-data/report-workflows/4242/trace"):
            guard hasNoBody(request) else {
                return unhandledResponse(method: method, requestDescription: "malformed report trace request")
            }
            return StubbedResponse(statusCode: 200, data: reportTraceFixture, handled: true)
        case ("GET", "/api/health-data/report-workflows/4242/assets/5/content"):
            guard hasNoBody(request) else {
                return unhandledResponse(method: method, requestDescription: "malformed report asset request")
            }
            return StubbedResponse(statusCode: 200, data: originalReportImageFixture, handled: true)
        case ("GET", "/api/health-data/documents"):
            let docType = components.queryItems?.first?.value
            return StubbedResponse(
                statusCode: 200,
                data: docType == "exam" ? reportDocumentListFixture : Data(#"{"items":[],"total":0}"#.utf8),
                handled: true
            )
        case ("GET", "/api/health-data/report-workflows/4242/review"):
            return StubbedResponse(statusCode: 200, data: reportReviewFixture, handled: true)
        case ("GET", "/api/health-data/report-workflows/4242/interpretation"):
            return StubbedResponse(statusCode: 200, data: reportInterpretationFixture, handled: true)
        case ("GET", "/api/health-data/documents/4242/file"):
            return StubbedResponse(statusCode: 200, data: originalReportImageFixture, handled: true)
        case ("POST", "/api/health-data/report-workflows/4242/confirm"):
            guard isValidReportConfirmation(requestBodyData(from: request)) else {
                return unhandledResponse(method: method, requestDescription: "malformed report confirmation")
            }
            return StubbedResponse(statusCode: 200, data: confirmedReportReviewFixture, handled: true)
        case ("GET", "/api/health-data/profile-trust"):
            return StubbedResponse(statusCode: 200, data: healthProfileFixture, handled: true)
        case ("POST", "/api/health-data/profile-trust/candidates/301/review"):
            guard isValidProfileCandidateReview(requestBodyData(from: request)) else {
                return unhandledResponse(method: method, requestDescription: "malformed profile candidate review")
            }
            return StubbedResponse(statusCode: 200, data: acceptedHealthProfileFixture, handled: true)
        case ("POST", "/api/health-data/profile-trust/facts"):
            guard isValidProfileSafetyUpsert(requestBodyData(from: request)) else {
                return unhandledResponse(method: method, requestDescription: "malformed profile fact upsert")
            }
            return StubbedResponse(statusCode: 200, data: savedHealthProfileFixture, handled: true)
        case ("POST", "/api/health-data/profile-trust/facts/201/retract"):
            guard isValidProfileFactRetraction(requestBodyData(from: request)) else {
                return unhandledResponse(method: method, requestDescription: "malformed profile fact retraction")
            }
            return StubbedResponse(statusCode: 200, data: retractedHealthProfileFixture, handled: true)
        case ("GET", "/api/health-data/profile-trust/facts/201/revisions"):
            guard hasNoBody(request) else {
                return unhandledResponse(method: method, requestDescription: "malformed profile fact revisions request")
            }
            return StubbedResponse(statusCode: 200, data: healthProfileFactRevisionsFixture, handled: true)
        case ("GET", "/api/health-data/profile-trust/goals/701/revisions"):
            guard hasNoBody(request) else {
                return unhandledResponse(method: method, requestDescription: "malformed profile goal revisions request")
            }
            return StubbedResponse(statusCode: 200, data: healthProfileGoalRevisionsFixture, handled: true)
        case ("POST", "/api/health-data/profile-trust/goals"):
            guard isValidProfileGoalCreate(requestBodyData(from: request)) else {
                return unhandledResponse(method: method, requestDescription: "malformed profile goal create")
            }
            return StubbedResponse(statusCode: 200, data: createdGoalHealthProfileFixture, handled: true)
        case ("PATCH", "/api/health-data/profile-trust/goals/701"):
            guard isValidProfileGoalUpdate(requestBodyData(from: request)) else {
                return unhandledResponse(method: method, requestDescription: "malformed profile goal update")
            }
            return StubbedResponse(statusCode: 200, data: updatedGoalHealthProfileFixture, handled: true)
        case ("POST", "/api/health-data/profile-trust/goals/701/status"):
            guard isValidProfileGoalStatus(requestBodyData(from: request)) else {
                return unhandledResponse(method: method, requestDescription: "malformed profile goal status")
            }
            return StubbedResponse(statusCode: 200, data: updatedGoalHealthProfileFixture, handled: true)
        default:
            return unhandledResponse(method: method, requestDescription: url.absoluteString)
        }
    }

    private static func requestBodyData(from request: URLRequest, limit: Int = 64 * 1_024) -> Data? {
        if let body = request.httpBody {
            return body.count <= limit ? body : nil
        }
        guard let stream = request.httpBodyStream else { return nil }
        stream.open()
        defer { stream.close() }

        var data = Data()
        var buffer = [UInt8](repeating: 0, count: 4_096)
        while true {
            let count = stream.read(&buffer, maxLength: buffer.count)
            if count < 0 { return nil }
            if count == 0 { return data }
            guard data.count + count <= limit else { return nil }
            data.append(contentsOf: buffer.prefix(count))
        }
    }

    private static func isProductionAPIRequest(_ components: URLComponents) -> Bool {
        guard let expected = productionOrigin else { return false }
        return components.scheme == expected.scheme
            && components.host == expected.host
            && components.port == expected.port
            && components.user == nil
            && components.password == nil
            && components.fragment == nil
    }

    private static func hasBearerAuthorization(_ request: URLRequest) -> Bool {
        request.value(forHTTPHeaderField: "Authorization")
            == "Bearer \(AuthManager.uiValidationToken)"
    }

    private static func hasAllowedQuery(_ components: URLComponents, for path: String) -> Bool {
        switch path {
        case "/api/chat/conversations":
            return UIAutomationRequestContract.hasAllowedConversationListQuery(components)
        case "/api/health-data/documents":
            return UIAutomationRequestContract.hasAllowedDocumentListQuery(components)
        case "/api/health-data/report-workflows":
            return UIAutomationRequestContract.hasAllowedReportHistoryQuery(components)
        case "/api/health-data/report-workflows/4242/trace":
            return UIAutomationRequestContract.hasAllowedReportTraceQuery(components)
        case "/api/health-data/report-workflows/4242/assets/5/content":
            return UIAutomationRequestContract.hasAllowedReportAssetContentQuery(components)
        case "/api/health-data/report-workflows/4242/review":
            return UIAutomationRequestContract.hasAllowedReportReviewQuery(components)
        case "/api/health-data/report-workflows/4242/interpretation":
            return UIAutomationRequestContract.hasAllowedReportInterpretationQuery(components)
        case "/api/medications/trust/today":
            return UIAutomationRequestContract.hasAllowedMedicationTodayQuery(components)
        case "/api/medications/trust/plans",
             "/api/medications/trust/prefill-candidates",
             "/api/medications/trust/reactions",
             "/api/medications/trust/long-term-summary":
            return UIAutomationRequestContract.hasAllowedMedicationSubjectQuery(components)
        default:
            if path.hasPrefix("/api/health-data/profile-trust/facts/")
                && path.hasSuffix("/revisions")
                || path.hasPrefix("/api/health-data/profile-trust/goals/")
                && path.hasSuffix("/revisions") {
                return UIAutomationRequestContract.hasAllowedProfileRevisionQuery(components)
            }
            return components.percentEncodedQuery == nil
        }
    }

    private static func hasNoBody(_ request: URLRequest) -> Bool {
        request.httpBody == nil && request.httpBodyStream == nil
    }

    private static func isValidReportConfirmation(_ body: Data?) -> Bool {
        guard let body,
              let object = try? JSONSerialization.jsonObject(with: body) as? [String: Any],
              object["subject_user_id"] as? Int == 1,
              object["workflow_version"] as? Int == 3,
              let eventID = object["client_event_id"] as? String,
              !eventID.isEmpty,
              let decisions = object["decisions"] as? [[String: Any]],
              decisions.count == 1,
              decisions[0]["candidate_id"] as? Int == 101,
              decisions[0]["candidate_version"] as? Int == 1,
              decisions[0]["action"] as? String == "confirm"
        else { return false }
        return true
    }

    private static func isValidProfileCandidateReview(_ body: Data?) -> Bool {
        guard let object = jsonObject(body),
              object["subject_user_id"] as? Int == 1,
              object["candidate_version"] as? Int == 2,
              let eventID = object["client_event_id"] as? String,
              !eventID.isEmpty,
              let action = object["action"] as? String else { return false }
        return action == "accept" || action == "reject"
    }

    private static func isValidProfileSafetyUpsert(_ body: Data?) -> Bool {
        guard let object = jsonObject(body),
              object["subject_user_id"] as? Int == 1,
              object["fact_key"] as? String == "safety.medication_allergy",
              object["category"] as? String == "safety",
              object["response_state"] as? String == "value",
              object["is_safety_critical"] as? Bool == true,
              object["expected_version"] == nil,
              let eventID = object["client_event_id"] as? String,
              !eventID.isEmpty,
              let value = object["value"] as? String else { return false }
        return !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    private static func isValidProfileFactRetraction(_ body: Data?) -> Bool {
        guard let object = jsonObject(body),
              object["subject_user_id"] as? Int == 1,
              object["expected_version"] as? Int == 2,
              let eventID = object["client_event_id"] as? String else { return false }
        return !eventID.isEmpty
    }

    private static func isValidProfileGoalCreate(_ body: Data?) -> Bool {
        guard let object = jsonObject(body),
              object["subject_user_id"] as? Int == 1,
              let eventID = object["client_event_id"] as? String,
              !eventID.isEmpty,
              let name = object["name"] as? String,
              !name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              isValidISODate(object["started_on"] as? String),
              isValidProfileGoalMetrics(object["metrics"] as? [[String: Any]])
        else { return false }
        return true
    }

    private static func isValidProfileGoalUpdate(_ body: Data?) -> Bool {
        guard let object = jsonObject(body),
              object["subject_user_id"] as? Int == 1,
              object["expected_version"] as? Int == 3,
              let eventID = object["client_event_id"] as? String,
              !eventID.isEmpty,
              let name = object["name"] as? String,
              !name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              isValidISODate(object["started_on"] as? String),
              isValidProfileGoalMetrics(object["metrics"] as? [[String: Any]])
        else { return false }
        return true
    }

    private static func isValidProfileGoalStatus(_ body: Data?) -> Bool {
        guard let object = jsonObject(body),
              object["subject_user_id"] as? Int == 1,
              object["expected_version"] as? Int == 3,
              let eventID = object["client_event_id"] as? String,
              !eventID.isEmpty,
              let action = object["action"] as? String
        else { return false }
        return ["pause", "resume", "complete", "archive"].contains(action)
    }

    private static func isValidProfileGoalMetrics(_ metrics: [[String: Any]]?) -> Bool {
        guard let metrics, !metrics.isEmpty, metrics.count <= 32 else { return false }
        let expression = try? NSRegularExpression(pattern: #"^[a-z0-9_.:-]+$"#)
        return metrics.allSatisfy { metric in
            guard let key = metric["metric_key"] as? String, !key.isEmpty,
                  let expression,
                  expression.firstMatch(
                    in: key,
                    range: NSRange(location: 0, length: key.utf16.count)
                  ) != nil
            else { return false }
            return metric.keys.allSatisfy { $0 == "metric_key" || $0 == "display_label" }
        }
    }

    private static func isValidISODate(_ value: String?) -> Bool {
        guard let value, value.count == 10 else { return false }
        let formatter = DateFormatter()
        formatter.calendar = Calendar(identifier: .gregorian)
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone(secondsFromGMT: 0)
        formatter.dateFormat = "yyyy-MM-dd"
        formatter.isLenient = false
        guard let date = formatter.date(from: value) else { return false }
        return formatter.string(from: date) == value
    }

    private static func jsonObject(_ body: Data?) -> [String: Any]? {
        guard let body else { return nil }
        return try? JSONSerialization.jsonObject(with: body) as? [String: Any]
    }

    private static let reportWorkflowHistoryFixture = Data(#"""
    {"items":[
      {"workflow_id":4242,"status":"awaiting_confirmation","report_type":"exam","title":"2026年体检报告.pdf","hospital":"协和医院","report_date":"2026-07-15","created_at":"2026-07-15T08:00:00Z"}
    ]}
    """#.utf8)

    private static let reportTraceFixture = Data(#"""
    {"workflow":{"id":4242,"status":"awaiting_confirmation","version":3},"assets":[{"id":5,"index":1,"filename":"2026年体检报告.pdf","sha256":"ui-fixture-sha256"}],"pages":[{"id":6,"page_index":1,"asset_id":5}],"locators":[{"candidate_id":101,"page_id":6,"role":"value","bbox":[0.1,0.2,0.3,0.4]}],"candidates":[{"id":101,"name":"空腹血糖","status":"pending_review","version":1}],"confirmation_events":[],"observations":[],"score_jobs":[],"score_items":[],"score_snapshots":[],"follow_ups":[]}
    """#.utf8)

    private static let reportDocumentListFixture = Data(#"""
    {"items":[
      {"id":"report-4242","name":"2026年体检报告.pdf","doc_type":"exam","source_type":"upload","extraction_status":"done","hospital":"协和医院","doc_date":"2026-07-15","created_at":"2026-07-15T08:00:00Z","report_workflow_id":4242,"report_workflow_status":"awaiting_confirmation","report_subject_user_id":1,"report_duplicate":false},
      {"id":"legacy-done-1","name":"旧版化验单.pdf","doc_type":"exam","source_type":"upload","extraction_status":"done","doc_date":"2025-12-01","ai_brief":"旧流程 OCR 摘要"}
    ],"total":2}
    """#.utf8)

    private static func medicationTodayFixture(localDate: String) -> Data {
        Data(#"""
        {"subject_user_id":1,"local_date":"\#(localDate)","planned_count":0,"taken_count":0,"awaiting_confirmation_count":0,"possibly_missed_count":0,"skipped_count":0,"snoozed_count":0,"adverse_reaction_count":0,"next_task":null,"tasks":[],"empty_state":"今天暂无已确认的服药计划","missed_assertion_policy":"elapsed_time_never_confirms_missed"}
        """#.utf8)
    }

    private static let trustedMedicationEmptyListFixture = Data(
        #"{"subject_user_id":1,"items":[]}"#.utf8
    )

    private static let trustedMedicationPlanListFixture = Data(#"""
    {"subject_user_id":1,"items":[{
      "plan_id":7,"subject_user_id":1,"generic_name":"阿托伐他汀钙片","brand_name":"立普妥","strength":"20mg/片","dose_text":"20mg","dose_quantity":1.0,"frequency":"每日一次","schedule_times":["20:00"],"meal_relation":"after_meal","instructions":"晚饭后按已确认计划服用","course_start":"2026-07-15","course_end":"2026-07-31","prescriber":"UI 测试医生","initial_quantity":30.0,"inventory_unit":"片","is_long_term":false,"source_type":"manual","source_ref":"ui-automation:confirmed-plan-7","status":"active","version":4,"confirmed_at":"2026-07-15T08:00:00Z","trust_state":"user_confirmed","reminder_management":"client_managed","reminder_default_enabled":false,"server_notification_scheduled":false,
      "inventory":{"is_estimate":true,"label":"预计剩余","estimated_remaining":30.0,"estimated_consumed":0.0,"inventory_unit":"片","basis":"user_confirmed_taken_events_only","unavailable_reason":null}
    }]}
    """#.utf8)

    private static let reportReviewFixture = Data(#"""
    {"workflow_id":4242,"legacy_document_id":4242,"subject_user_id":1,"status":"awaiting_confirmation","version":3,"report_type":"exam","document_fingerprint":"ui-fixture-sha256","recognized_at":"2026-07-15T08:00:00Z","confirmed_at":null,"completed_at":null,"confirmation_client_event_id":null,"failure_code":null,"failure_detail":null,"pending_review_count":1,"auto_accepted_count":1,"admitted_observation_count":0,"requires_report_confirmation":true,"can_confirm":true,"document":{"id":"report-4242","name":"2026年体检报告.pdf","doc_type":"exam","source_type":"upload","extraction_status":"done"},"candidates":[
      {"candidate_id":101,"candidate_key":"glucose-101","version":1,"canonical_code":"glucose","canonical_name":"空腹血糖","raw_name":"葡萄糖","raw_value":"8.2","raw_unit":"mmol/L","normalized_value":8.2,"normalized_text":null,"normalized_unit":"mmol/L","reference_low":3.9,"reference_high":6.1,"reference_text":"3.9–6.1 mmol/L","abnormal_state":"abnormal","confidence":0.61,"low_confidence":true,"conflict_reasons":["unit_conflict"],"effective_at":"2026-07-15T00:00:00Z","source_locator":{"document_id":4242,"source_type":"pdf","row_index":3,"page":2,"name_column":0,"value_column":1,"unit_column":2,"reference_column":3},"review_status":"pending_review","requires_review":true},
      {"candidate_id":102,"candidate_key":"hdl-102","version":1,"canonical_code":"hdl","canonical_name":"高密度脂蛋白","raw_name":"高密度脂蛋白","raw_value":"1.42","raw_unit":"mmol/L","normalized_value":1.42,"normalized_text":null,"normalized_unit":"mmol/L","reference_low":1.0,"reference_high":null,"reference_text":"≥ 1.0 mmol/L","abnormal_state":"normal","confidence":0.98,"low_confidence":false,"conflict_reasons":[],"effective_at":"2026-07-15T00:00:00Z","source_locator":{"document_id":4242,"source_type":"pdf","row_index":4,"page":2,"name_column":0,"value_column":1,"unit_column":2,"reference_column":3},"review_status":"auto_accepted","requires_review":false}
    ]}
    """#.utf8)

    private static let confirmedReportReviewFixture = Data(#"""
    {"workflow_id":4242,"legacy_document_id":4242,"subject_user_id":1,"status":"completed_score_pending","version":4,"report_type":"exam","document_fingerprint":"ui-fixture-sha256","recognized_at":"2026-07-15T08:00:00Z","confirmed_at":"2026-07-15T08:05:00Z","completed_at":"2026-07-15T08:05:01Z","confirmation_client_event_id":"ui-confirmed-event","failure_code":null,"failure_detail":null,"pending_review_count":0,"auto_accepted_count":1,"admitted_observation_count":2,"requires_report_confirmation":false,"can_confirm":false,"document":{"id":"report-4242","name":"2026年体检报告.pdf","doc_type":"exam","source_type":"upload","extraction_status":"done"},"candidates":[
      {"candidate_id":101,"candidate_key":"glucose-101","version":2,"canonical_code":"glucose","canonical_name":"空腹血糖","raw_name":"葡萄糖","raw_value":"8.2","raw_unit":"mmol/L","normalized_value":8.2,"normalized_text":null,"normalized_unit":"mmol/L","reference_low":3.9,"reference_high":6.1,"reference_text":"3.9–6.1 mmol/L","abnormal_state":"abnormal","confidence":0.61,"low_confidence":true,"conflict_reasons":["unit_conflict"],"effective_at":"2026-07-15T00:00:00Z","source_locator":{"document_id":4242,"source_type":"pdf","row_index":3,"page":2,"name_column":0,"value_column":1,"unit_column":2,"reference_column":3},"review_status":"confirmed","requires_review":false},
      {"candidate_id":102,"candidate_key":"hdl-102","version":1,"canonical_code":"hdl","canonical_name":"高密度脂蛋白","raw_name":"高密度脂蛋白","raw_value":"1.42","raw_unit":"mmol/L","normalized_value":1.42,"normalized_text":null,"normalized_unit":"mmol/L","reference_low":1.0,"reference_high":null,"reference_text":"≥ 1.0 mmol/L","abnormal_state":"normal","confidence":0.98,"low_confidence":false,"conflict_reasons":[],"effective_at":"2026-07-15T00:00:00Z","source_locator":{"document_id":4242,"source_type":"pdf","row_index":4,"page":2,"name_column":0,"value_column":1,"unit_column":2,"reference_column":3},"review_status":"auto_accepted","requires_review":false}
    ]}
    """#.utf8)

    private static let reportInterpretationFixture = Data(#"""
    {"workflow_id":4242,"subject_user_id":1,"status":"completed_score_pending","available":true,"unavailable_reason":null,"non_diagnostic_notice":"本解读仅依据已确认的报告字段与服务端实际评分快照整理，不构成诊断或治疗建议。","document":{"id":"report-4242","name":"2026年体检报告.pdf","doc_type":"exam","source_type":"upload","extraction_status":"done","file_url":"/api/health-data/documents/4242/file"},"candidates":[
      {"candidate_id":101,"candidate_key":"glucose-101","version":2,"canonical_code":"glucose","canonical_name":"空腹血糖","raw_name":"葡萄糖","raw_value":"8.2","raw_unit":"mmol/L","normalized_value":8.2,"normalized_text":null,"normalized_unit":"mmol/L","reference_low":3.9,"reference_high":6.1,"reference_text":"3.9–6.1 mmol/L","abnormal_state":"abnormal","confidence":0.61,"low_confidence":true,"conflict_reasons":["unit_conflict"],"effective_at":"2026-07-15T00:00:00Z","source_locator":{"document_id":4242,"source_type":"pdf","row_index":3,"page":2},"review_status":"confirmed","requires_review":false},
      {"candidate_id":102,"candidate_key":"hdl-102","version":2,"canonical_code":"hdl","canonical_name":"高密度脂蛋白","raw_name":"高密度脂蛋白","raw_value":"1.42","raw_unit":"mmol/L","normalized_value":1.42,"normalized_text":null,"normalized_unit":"mmol/L","reference_low":1.0,"reference_high":null,"reference_text":"≥ 1.0 mmol/L","abnormal_state":"normal","confidence":0.98,"low_confidence":false,"conflict_reasons":[],"effective_at":"2026-07-15T00:00:00Z","source_locator":{"document_id":4242,"source_type":"pdf","row_index":4,"page":2},"review_status":"confirmed","requires_review":false}
    ],"confirmation_events":[
      {"event_id":901,"candidate_id":101,"event_type":"confirm","candidate_version":1,"before_data":{"value_numeric":"8.20000000","unit":"mmol/L"},"after_data":{"value_numeric":"8.20000000","unit":"mmol/L"},"created_at":"2026-07-15T08:05:00Z"},
      {"event_id":902,"candidate_id":102,"event_type":"confirm","candidate_version":1,"before_data":{"value_numeric":"1.42000000","unit":"mmol/L"},"after_data":{"value_numeric":"1.42000000","unit":"mmol/L"},"created_at":"2026-07-15T08:05:00Z"}
    ],"structured_additions":[
      {"observation_id":801,"source_candidate_id":101,"confirmation_event_id":901,"canonical_code":"glucose","canonical_name":"空腹血糖","value_numeric":8.2,"value_text":null,"unit":"mmol/L","reference_low":3.9,"reference_high":6.1,"reference_text":"3.9–6.1 mmol/L","abnormal_state":"abnormal","effective_at":"2026-07-15T00:00:00Z","confirmed_at":"2026-07-15T08:05:00Z"},
      {"observation_id":802,"source_candidate_id":102,"confirmation_event_id":902,"canonical_code":"hdl","canonical_name":"高密度脂蛋白","value_numeric":1.42,"value_text":null,"unit":"mmol/L","reference_low":1.0,"reference_high":null,"reference_text":"≥ 1.0 mmol/L","abnormal_state":"normal","effective_at":"2026-07-15T00:00:00Z","confirmed_at":"2026-07-15T08:05:00Z"}
    ],"major_abnormalities":[
      {"observation_id":801,"source_candidate_id":101,"confirmation_event_id":901,"canonical_code":"glucose","canonical_name":"空腹血糖","value_numeric":8.2,"value_text":null,"unit":"mmol/L","reference_low":3.9,"reference_high":6.1,"reference_text":"3.9–6.1 mmol/L","abnormal_state":"abnormal","effective_at":"2026-07-15T00:00:00Z","confirmed_at":"2026-07-15T08:05:00Z"}
    ],"follow_up":{"available":false,"items":[],"unavailable_reason":"当前没有经过确认的随访或复查建议数据；系统不会根据异常值自行推断。"},"profile_impacts":[
      {"profile_candidate_id":301,"source_id":501,"source_observation_id":801,"fact_key":"long_term_health.glucose","category":"long_term_health","proposed_value":{"canonical_name":"空腹血糖","latest_value_numeric":"8.2"},"review_status":"pending_review","confidence":0.61},
      {"profile_candidate_id":301,"source_id":502,"source_observation_id":802,"fact_key":"long_term_health.glucose","category":"long_term_health","proposed_value":{"canonical_name":"空腹血糖","latest_value_numeric":"8.2"},"review_status":"pending_review","confidence":0.61}
    ],"score_state":"partial_failed","score_pending":true,"score_snapshots":[
      {"snapshot_id":701,"score_kind":"stress","algorithm_id":"trusted-score","algorithm_version":"2026.07","before_value":58,"after_value":54,"before_confidence":0.8,"after_confidence":0.85,"score_direction":"lower_is_better","semantic_outcome":"improved","calculation_status":"completed","evidence":{"observation_ids":[801]},"missing_inputs":{},"failure_code":null,"computed_at":"2026-07-15T08:06:00Z"},
      {"snapshot_id":702,"score_kind":"inflammation","algorithm_id":"trusted-score","algorithm_version":"2026.07","before_value":null,"after_value":null,"before_confidence":null,"after_confidence":null,"score_direction":null,"semantic_outcome":null,"calculation_status":"failed","evidence":{},"missing_inputs":{"required":["hs_crp"]},"failure_code":"insufficient_evidence","computed_at":"2026-07-15T08:06:00Z"}
    ]}
    """#.utf8)

    private static let originalReportImageFixture: Data = {
        let size = CGSize(width: 1_000, height: 1_400)
        let format = UIGraphicsImageRendererFormat()
        format.scale = 1
        format.opaque = true
        let renderer = UIGraphicsImageRenderer(size: size, format: format)
        return renderer.pngData { rendererContext in
            let context = rendererContext.cgContext
            UIColor.white.setFill()
            context.fill(CGRect(origin: .zero, size: size))

            UIColor(red: 0.07, green: 0.29, blue: 0.46, alpha: 1).setFill()
            context.fill(CGRect(x: 0, y: 0, width: size.width, height: 150))

            func drawText(
                _ text: String,
                frame: CGRect,
                font: UIFont,
                color: UIColor,
                alignment: NSTextAlignment = .left
            ) {
                let style = NSMutableParagraphStyle()
                style.alignment = alignment
                style.lineBreakMode = .byWordWrapping
                (text as NSString).draw(
                    in: frame,
                    withAttributes: [
                        .font: font,
                        .foregroundColor: color,
                        .paragraphStyle: style
                    ]
                )
            }

            drawText(
                "体检检验报告",
                frame: CGRect(x: 60, y: 40, width: 880, height: 70),
                font: .systemFont(ofSize: 48, weight: .bold),
                color: .white,
                alignment: .center
            )
            drawText(
                "UI 自动化测试样本 · 不含真实个人信息",
                frame: CGRect(x: 80, y: 185, width: 840, height: 44),
                font: .systemFont(ofSize: 25, weight: .semibold),
                color: UIColor(red: 0.12, green: 0.48, blue: 0.58, alpha: 1),
                alignment: .center
            )
            drawText(
                "姓名：测试用户        检查日期：2026-07-15\n机构：协和医院（测试数据）        报告编号：UI-4242",
                frame: CGRect(x: 72, y: 260, width: 856, height: 100),
                font: .systemFont(ofSize: 25, weight: .medium),
                color: UIColor(red: 0.12, green: 0.25, blue: 0.34, alpha: 1)
            )

            let tableFrame = CGRect(x: 64, y: 410, width: 872, height: 530)
            UIColor(red: 0.93, green: 0.97, blue: 0.98, alpha: 1).setFill()
            context.fill(tableFrame)
            UIColor(red: 0.67, green: 0.77, blue: 0.82, alpha: 1).setStroke()
            context.setLineWidth(2)
            context.stroke(tableFrame)
            for row in 1...4 {
                let y = tableFrame.minY + CGFloat(row) * 106
                context.move(to: CGPoint(x: tableFrame.minX, y: y))
                context.addLine(to: CGPoint(x: tableFrame.maxX, y: y))
            }
            let columns: [CGFloat] = [360, 560, 760]
            for x in columns {
                context.move(to: CGPoint(x: x, y: tableFrame.minY))
                context.addLine(to: CGPoint(x: x, y: tableFrame.maxY))
            }
            context.strokePath()

            let headers = ["检验项目", "结果", "参考范围", "提示"]
            let headerFrames = [
                CGRect(x: 82, y: 438, width: 260, height: 54),
                CGRect(x: 378, y: 438, width: 165, height: 54),
                CGRect(x: 578, y: 438, width: 165, height: 54),
                CGRect(x: 778, y: 438, width: 140, height: 54)
            ]
            for index in headers.indices {
                drawText(
                    headers[index],
                    frame: headerFrames[index],
                    font: .systemFont(ofSize: 24, weight: .bold),
                    color: UIColor(red: 0.07, green: 0.29, blue: 0.46, alpha: 1),
                    alignment: .center
                )
            }

            let rows = [
                ["空腹血糖", "8.2 mmol/L", "3.9–6.1", "偏高"],
                ["高密度脂蛋白", "1.42 mmol/L", "≥ 1.0", "正常"],
                ["尿酸", "470 μmol/L", "208–428", "偏高"],
                ["高敏 C 反应蛋白", "待补充", "< 3.0", "未识别"]
            ]
            for (rowIndex, row) in rows.enumerated() {
                let y = 544 + CGFloat(rowIndex) * 106
                let frames = [
                    CGRect(x: 82, y: y, width: 260, height: 56),
                    CGRect(x: 378, y: y, width: 165, height: 56),
                    CGRect(x: 578, y: y, width: 165, height: 56),
                    CGRect(x: 778, y: y, width: 140, height: 56)
                ]
                for columnIndex in row.indices {
                    drawText(
                        row[columnIndex],
                        frame: frames[columnIndex],
                        font: .systemFont(ofSize: 21, weight: columnIndex == 3 ? .semibold : .regular),
                        color: columnIndex == 3 && row[columnIndex] == "偏高"
                            ? UIColor(red: 0.76, green: 0.31, blue: 0.17, alpha: 1)
                            : UIColor(red: 0.12, green: 0.25, blue: 0.34, alpha: 1),
                        alignment: .center
                    )
                }
            }

            drawText(
                "核对提示",
                frame: CGRect(x: 72, y: 1_010, width: 856, height: 44),
                font: .systemFont(ofSize: 28, weight: .bold),
                color: UIColor(red: 0.07, green: 0.29, blue: 0.46, alpha: 1)
            )
            drawText(
                "请对照原件确认数值、单位、参考范围和采样日期。低置信度或冲突字段在用户确认前不会进入趋势、健康画像、评分或 AI 对话。",
                frame: CGRect(x: 72, y: 1_075, width: 856, height: 145),
                font: .systemFont(ofSize: 24, weight: .regular),
                color: UIColor(red: 0.22, green: 0.37, blue: 0.47, alpha: 1)
            )
            drawText(
                "仅用于自动化界面验证 · 不是医学诊断或治疗建议",
                frame: CGRect(x: 72, y: 1_285, width: 856, height: 48),
                font: .systemFont(ofSize: 22, weight: .semibold),
                color: UIColor(red: 0.40, green: 0.49, blue: 0.55, alpha: 1),
                alignment: .center
            )
        }
    }()

    private static let healthProfileFixture = Data(#"""
    {"subject_user_id":1,"profile_status":"needs_attention","overview":{"completeness_percent":40,"resolved_required_weight":6,"total_required_weight":15,"missing_required_fact_keys":["basic.height","safety.medication_allergy"],"pending_update_count":1,"independent_source_count":3,"primary_action":{"kind":"review_updates","item_count":1,"localization_key":"health_profile.primary_action.review_updates","route":"profile_updates"}},"facts":[
      {"fact_id":201,"fact_key":"basic.birth_date","category":"basic","value_data":{"response_state":"value","value":"1985-06-18"},"is_safety_critical":false,"confirmation_method":"user","version":2,"confirmed_at":"2026-07-14T08:00:00Z","updated_at":"2026-07-15T08:00:00Z","sources":[{"source_id":501,"source_type":"manual","source_ref":"manual-fact:basic.birth_date","confidence":1.0,"source_snapshot":{"response_state":"value"},"created_at":"2026-07-14T08:00:00Z"}]}
    ],"candidates":[
      {"candidate_id":301,"fact_key":"long_term_health.repeated_abnormal.uric_acid","category":"long_term_health","proposed_value":{"canonical_name":"尿酸","occurrence_count":3,"latest_value_numeric":"470"},"is_safety_critical":false,"review_status":"pending_review","conflict_with_fact_id":null,"confidence":0.91,"version":2,"created_at":"2026-07-15T07:00:00Z","updated_at":"2026-07-15T08:00:00Z","sources":[{"source_id":503,"source_type":"report","source_ref":"report-1001","confidence":0.91,"source_snapshot":{"workflow_id":1001},"created_at":"2026-07-15T07:00:00Z"},{"source_id":504,"source_type":"report","source_ref":"report-1002","confidence":0.93,"source_snapshot":{"workflow_id":1002},"created_at":"2026-07-15T07:30:00Z"}]}
    ],"goals":[{"goal_id":701,"name":"改善睡眠规律","status":"active","started_on":"2026-07-01","version":3,"confirmed_at":"2026-07-15T08:00:00Z","metrics":[{"metric_key":"sleep_duration","display_label":"睡眠时长"},{"metric_key":"hrv","display_label":"HRV"}]}]}
    """#.utf8)

    private static let acceptedHealthProfileFixture = Data(#"""
    {"subject_user_id":1,"profile_status":"needs_attention","overview":{"completeness_percent":40,"resolved_required_weight":6,"total_required_weight":15,"missing_required_fact_keys":["basic.height","safety.medication_allergy"],"pending_update_count":0,"independent_source_count":4,"primary_action":{"kind":"complete_profile","item_count":2,"localization_key":"health_profile.primary_action.complete_profile","route":"profile_editor"}},"facts":[
      {"fact_id":201,"fact_key":"basic.birth_date","category":"basic","value_data":{"response_state":"value","value":"1985-06-18"},"is_safety_critical":false,"confirmation_method":"user","version":2,"confirmed_at":"2026-07-14T08:00:00Z","updated_at":"2026-07-15T08:00:00Z","sources":[{"source_id":501,"source_type":"manual","source_ref":"manual-fact:basic.birth_date","confidence":1.0,"source_snapshot":{},"created_at":"2026-07-14T08:00:00Z"}]},
      {"fact_id":203,"fact_key":"long_term_health.repeated_abnormal.uric_acid","category":"long_term_health","value_data":{"canonical_name":"尿酸","occurrence_count":3,"latest_value_numeric":"470"},"is_safety_critical":false,"confirmation_method":"user","version":1,"confirmed_at":"2026-07-15T08:05:00Z","updated_at":"2026-07-15T08:05:00Z","sources":[{"source_id":503,"source_type":"report","source_ref":"report-1001","confidence":0.91,"source_snapshot":{},"created_at":"2026-07-15T07:00:00Z"},{"source_id":504,"source_type":"report","source_ref":"report-1002","confidence":0.93,"source_snapshot":{},"created_at":"2026-07-15T07:30:00Z"}]}
    ],"candidates":[],"goals":[{"goal_id":701,"name":"改善睡眠规律","status":"active","started_on":"2026-07-01","version":3,"confirmed_at":"2026-07-15T08:00:00Z","metrics":[{"metric_key":"sleep_duration","display_label":"睡眠时长"}]}]}
    """#.utf8)

    private static let savedHealthProfileFixture = Data(#"""
    {"subject_user_id":1,"profile_status":"needs_attention","overview":{"completeness_percent":47,"resolved_required_weight":7,"total_required_weight":15,"missing_required_fact_keys":["basic.height"],"pending_update_count":0,"independent_source_count":4,"primary_action":{"kind":"complete_profile","item_count":1,"localization_key":"health_profile.primary_action.complete_profile","route":"profile_editor"}},"facts":[
      {"fact_id":201,"fact_key":"basic.birth_date","category":"basic","value_data":{"response_state":"value","value":"1985-06-18"},"is_safety_critical":false,"confirmation_method":"user","version":2,"confirmed_at":"2026-07-14T08:00:00Z","updated_at":"2026-07-15T08:00:00Z","sources":[]},
      {"fact_id":204,"fact_key":"safety.medication_allergy","category":"safety","value_data":{"response_state":"value","value":"青霉素过敏"},"is_safety_critical":true,"confirmation_method":"user","version":1,"confirmed_at":"2026-07-15T09:00:00Z","updated_at":"2026-07-15T09:00:00Z","sources":[{"source_id":505,"source_type":"manual","source_ref":"manual-fact:safety.medication_allergy","confidence":1.0,"source_snapshot":{},"created_at":"2026-07-15T09:00:00Z"}]}
    ],"candidates":[],"goals":[{"goal_id":701,"name":"改善睡眠规律","status":"active","started_on":"2026-07-01","version":3,"confirmed_at":"2026-07-15T08:00:00Z","metrics":[{"metric_key":"sleep_duration","display_label":"睡眠时长"}]}]}
    """#.utf8)

    private static let retractedHealthProfileFixture = Data(#"""
    {"subject_user_id":1,"profile_status":"needs_attention","overview":{"completeness_percent":33,"resolved_required_weight":5,"total_required_weight":15,"missing_required_fact_keys":["basic.birth_date","basic.height","safety.medication_allergy"],"pending_update_count":0,"independent_source_count":1,"primary_action":{"kind":"complete_profile","item_count":3,"localization_key":"health_profile.primary_action.complete_profile","route":"profile_editor"}},"facts":[],"candidates":[],"goals":[{"goal_id":701,"name":"改善睡眠规律","status":"active","started_on":"2026-07-01","version":3,"confirmed_at":"2026-07-15T08:00:00Z","metrics":[{"metric_key":"sleep_duration","display_label":"睡眠时长"}]}]}
    """#.utf8)

    private static let longTermMedicationSummaryFixture = Data(#"""
    {"subject_user_id":1,"items":[{"medication_name":"二甲双胍","purpose":"血糖管理","started_on":"2025-01-01","is_still_taking":true,"source":"prescription","last_confirmed_at":"2026-07-12T08:00:00Z"}]}
    """#.utf8)

    private static let healthProfileFactRevisionsFixture = Data(#"""
    {"subject_user_id":1,"target_kind":"fact","target_id":201,"items":[{"revision_id":801,"event_type":"updated","target_version":2,"actor_user_id":1,"before_data":{"response_state":"value","value":"1985-06-17"},"after_data":{"response_state":"value","value":"1985-06-18"},"created_at":"2026-07-15T08:00:00Z"}],"next_after_revision_id":null}
    """#.utf8)

    private static let healthProfileGoalRevisionsFixture = Data(#"""
    {"subject_user_id":1,"target_kind":"goal","target_id":701,"items":[{"revision_id":901,"event_type":"created","target_version":1,"actor_user_id":1,"before_data":{},"after_data":{"name":"改善睡眠规律","status":"active","started_on":"2026-07-01","metrics":[{"metric_key":"sleep_duration","display_label":"睡眠时长"}]},"created_at":"2026-07-01T08:00:00Z"}],"next_after_revision_id":null}
    """#.utf8)

    private static let createdGoalHealthProfileFixture = Data(#"""
    {"subject_user_id":1,"profile_status":"needs_attention","overview":{"completeness_percent":47,"resolved_required_weight":7,"total_required_weight":15,"missing_required_fact_keys":["basic.height","safety.medication_allergy"],"pending_update_count":1,"independent_source_count":3,"primary_action":{"kind":"review_updates","item_count":1,"localization_key":"health_profile.primary_action.review_updates","route":"profile_updates"}},"facts":[],"candidates":[],"goals":[{"goal_id":701,"name":"改善睡眠规律","status":"active","started_on":"2026-07-01","version":3,"confirmed_at":"2026-07-15T08:00:00Z","metrics":[{"metric_key":"sleep_duration","display_label":"睡眠时长"}]},{"goal_id":702,"name":"提高日均步数","status":"active","started_on":"2026-07-15","version":1,"confirmed_at":"2026-07-15T09:00:00Z","metrics":[{"metric_key":"steps","display_label":"步数"}]}]}
    """#.utf8)

    private static let updatedGoalHealthProfileFixture = Data(#"""
    {"subject_user_id":1,"profile_status":"needs_attention","overview":{"completeness_percent":47,"resolved_required_weight":7,"total_required_weight":15,"missing_required_fact_keys":["basic.height","safety.medication_allergy"],"pending_update_count":1,"independent_source_count":3,"primary_action":{"kind":"review_updates","item_count":1,"localization_key":"health_profile.primary_action.review_updates","route":"profile_updates"}},"facts":[],"candidates":[],"goals":[{"goal_id":701,"name":"改善睡眠质量","status":"paused","started_on":"2026-07-01","version":4,"confirmed_at":"2026-07-15T09:30:00Z","metrics":[{"metric_key":"sleep_duration","display_label":"睡眠时长"},{"metric_key":"hrv","display_label":"HRV"}]}]}
    """#.utf8)

    private static func unhandledResponse(
        method: String,
        requestDescription: String
    ) -> StubbedResponse {
        let detail = "Unstubbed UI automation request: \(method) \(requestDescription)"
        let payload = (try? JSONEncoder().encode(["detail": detail]))
            ?? Data(#"{"detail":"Unstubbed UI automation request"}"#.utf8)
        return StubbedResponse(statusCode: 418, data: payload, handled: false)
    }

    override class func canInit(with request: URLRequest) -> Bool {
        true
    }

    static func shouldIntercept(_ request: URLRequest, arguments: [String]) -> Bool {
        isEnabled(arguments: arguments)
    }

    override class func canonicalRequest(for request: URLRequest) -> URLRequest {
        request
    }

    override func startLoading() {
        let stub = Self.stubbedResponse(for: request)
        UIAutomationNetworkAudit.shared.record(handled: stub.handled)
        guard let url = request.url,
              let response = HTTPURLResponse(
                url: url,
                statusCode: stub.statusCode,
                httpVersion: "HTTP/1.1",
                headerFields: ["Content-Type": "application/json; charset=utf-8"]
              )
        else {
            client?.urlProtocol(self, didFailWithError: URLError(.badURL))
            return
        }
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: stub.data)
        client?.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {}
}

final class UIAutomationNetworkAudit: ObservableObject, @unchecked Sendable {
    static let shared = UIAutomationNetworkAudit()

    struct Snapshot: Equatable {
        let intercepted: Int
        let unhandled: Int
    }

    private let lock = NSLock()
    private var intercepted = 0
    private var unhandled = 0
    @Published private var revision = 0

    private init() {}

    func record(handled: Bool) {
        lock.lock()
        intercepted += 1
        if !handled {
            unhandled += 1
        }
        lock.unlock()
        if Thread.isMainThread {
            revision &+= 1
        } else {
            DispatchQueue.main.sync { [weak self] in
                self?.revision &+= 1
            }
        }
    }

    func snapshot() -> Snapshot {
        lock.lock()
        defer { lock.unlock() }
        return Snapshot(intercepted: intercepted, unhandled: unhandled)
    }

    var accessibilityValue: String {
        let current = snapshot()
        return "intercepted=\(current.intercepted);unhandled=\(current.unhandled)"
    }
}
#endif

// MARK: - 辅助类型

enum APIError: LocalizedError {
    case notLoggedIn
    case accountScopeChanged
    case unsupportedOperation(String)
    case invalidMultipartForm(String)
    case httpError(Int, String)
    case httpErrorResponse(Int, String, Data)
    case invalidURL(String)
    case invalidResponse

    var errorDescription: String? {
        switch self {
        case .notLoggedIn: return "未登录"
        case .accountScopeChanged: return "登录账号已变化，已停止本次请求"
        case .unsupportedOperation(let operation): return "当前传输不支持此操作：\(operation)"
        case .invalidMultipartForm(let reason): return "上传表单无效：\(reason)"
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
