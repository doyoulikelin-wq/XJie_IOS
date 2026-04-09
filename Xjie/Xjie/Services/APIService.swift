import Foundation
import os
import Security

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

    /// 自定义 URLSession，信任服务器自签证书（其他模块可通过 APIService.shared.trustedSession 访问）
    nonisolated let trustedSession: URLSession = {
        let delegate = SelfSignedCertDelegate()
        let config = URLSessionConfiguration.default
        return URLSession(configuration: config, delegate: delegate, delegateQueue: nil)
    }()

    private var session: URLSession { trustedSession }

    // ERR-02: Token 刷新任务，防止并发 401 触发多次刷新
    private var refreshTask: Task<Void, Error>?

    // MARK: - 便捷方法

    func get<T: Decodable>(_ path: String, timeout: TimeInterval? = nil) async throws -> T {
        try await request(path, method: "GET", timeout: timeout)
    }

    func post<T: Decodable>(_ path: String, body: Encodable? = nil, timeout: TimeInterval? = nil) async throws -> T {
        try await request(path, method: "POST", body: body, timeout: timeout)
    }

    func patch<T: Decodable>(_ path: String, body: Encodable? = nil) async throws -> T {
        try await request(path, method: "PATCH", body: body)
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

    func deleteVoid(_ path: String) async throws {
        let _: EmptyResponse = try await request(path, method: "DELETE")
    }

    // MARK: - 通用请求

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

        if !path.hasPrefix("/api/auth/") && token.isEmpty {
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

        // ERR-02: 401 自动刷新 Token，使用 refreshTask 合并并发请求
        if httpResponse.statusCode == 401 && !retried {
            try await ensureTokenRefreshed()
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

    // MARK: - ERR-02: Token 刷新（合并并发请求）

    private func ensureTokenRefreshed() async throws {
        if let existingTask = refreshTask {
            try await existingTask.value
            return
        }

        let task = Task { [weak self] in
            defer { Task { await self?.clearRefreshTask() } }
            try await self?.performTokenRefresh()
        }
        refreshTask = task
        try await task.value
    }

    private func clearRefreshTask() {
        refreshTask = nil
    }

    private func performTokenRefresh() async throws {
        let auth = await AuthManager.shared
        let rt = await auth.refreshToken
        guard !rt.isEmpty else {
            await auth.logout()
            throw APIError.notLoggedIn
        }

        struct RefreshBody: Encodable { let refresh_token: String }
        struct RefreshResponse: Decodable { let access_token: String; let refresh_token: String? }

        guard let url = URL(string: baseURL + "/api/auth/refresh") else {
            throw APIError.invalidURL("/api/auth/refresh")
        }

        var urlRequest = URLRequest(url: url)
        urlRequest.httpMethod = "POST"
        urlRequest.setValue("application/json", forHTTPHeaderField: "Content-Type")
        urlRequest.httpBody = try JSONEncoder().encode(RefreshBody(refresh_token: rt))

        let (data, response) = try await session.data(for: urlRequest)

        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.invalidResponse
        }

        if httpResponse.statusCode == 200,
           let res = try? JSONDecoder().decode(RefreshResponse.self, from: data) {
            await auth.setAuth(accessToken: res.access_token, refreshToken: res.refresh_token ?? "")
        } else {
            await auth.logout()
            throw APIError.notLoggedIn
        }
    }

    // MARK: - 上传文件

    func uploadFile(_ path: String, fileData: Data, fileName: String, mimeType: String, formData: [String: String] = [:]) async throws -> Data {
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
    case httpError(Int, String)
    case invalidURL(String)
    case invalidResponse

    var errorDescription: String? {
        switch self {
        case .notLoggedIn: return "未登录"
        case .httpError(_, let msg): return msg
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

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        // detail 可能是 String 或 {"error_code":..., "message":...} 字典
        if let str = try? container.decode(String.self, forKey: .detail) {
            detail = str
        } else if let dict = try? container.decode([String: String].self, forKey: .detail),
                  let msg = dict["message"] {
            detail = msg
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

// MARK: - 自签证书信任代理

/// 仅信任指定服务器 IP 的自签证书
final class SelfSignedCertDelegate: NSObject, URLSessionDelegate, URLSessionTaskDelegate {
    private let trustedHost = "8.130.213.44"

    func urlSession(
        _ session: URLSession,
        didReceive challenge: URLAuthenticationChallenge,
        completionHandler: @escaping (URLSession.AuthChallengeDisposition, URLCredential?) -> Void
    ) {
        handleChallenge(challenge, completionHandler: completionHandler)
    }

    func urlSession(
        _ session: URLSession,
        task: URLSessionTask,
        didReceive challenge: URLAuthenticationChallenge,
        completionHandler: @escaping (URLSession.AuthChallengeDisposition, URLCredential?) -> Void
    ) {
        handleChallenge(challenge, completionHandler: completionHandler)
    }

    private func handleChallenge(
        _ challenge: URLAuthenticationChallenge,
        completionHandler: @escaping (URLSession.AuthChallengeDisposition, URLCredential?) -> Void
    ) {
        guard challenge.protectionSpace.authenticationMethod == NSURLAuthenticationMethodServerTrust,
              challenge.protectionSpace.host == trustedHost,
              let serverTrust = challenge.protectionSpace.serverTrust else {
            completionHandler(.performDefaultHandling, nil)
            return
        }
        let credential = URLCredential(trust: serverTrust)
        completionHandler(.useCredential, credential)
    }
}
