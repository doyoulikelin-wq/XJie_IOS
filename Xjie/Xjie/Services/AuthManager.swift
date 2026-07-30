import Foundation
import Combine
import CryptoKit

/// 认证管理器 — SEC-01: 使用 Keychain 安全存储 Token（替代 UserDefaults）
@MainActor
final class AuthManager: ObservableObject {
    static let shared = AuthManager()

    @Published var token: String = ""
    @Published var refreshToken: String = ""
    @Published var subjectId: String = ""
    @Published var userInfo: UserInfo?

    var isLoggedIn: Bool { !token.isEmpty }
    /// 当前认证账号的数字用户 ID。
    ///
    /// 正式账号优先使用后端签名 JWT 的 `sub`，避免 App 冷启动或 `/api/users/me`
    /// 尚未返回时把有效登录态误判为“登录信息不完整”。旧 `userInfo` 与
    /// `subjectId` 只作为兼容来源，不能覆盖当前 JWT 已声明的主体。
    var authenticatedNumericUserID: Int? {
        if let jwtUserID = Self.numericUserID(fromJWT: token) {
            return jwtUserID
        }
        if let raw = userInfo?.id?.trimmingCharacters(in: .whitespacesAndNewlines),
           let value = Int(raw), value > 0 {
            return value
        }
        if let value = Int(subjectId.trimmingCharacters(in: .whitespacesAndNewlines)),
           value > 0 {
            return value
        }
        #if DEBUG
        if isUIValidationSession { return 1 }
        #endif
        return nil
    }
    /// 当前登录账号的稳定、不透明作用域。
    ///
    /// Apple Health 等设备级数据必须按“账号”隔离，不能使用会随主体切换的
    /// `subjectId`，也不能把 access token 本身写进 UserDefaults。JWT 的 `sub`
    /// 是服务端账号标识；这里只保留其 SHA-256 摘要，token 刷新后作用域不变。
    var accountScope: String? {
        guard isLoggedIn else { return nil }
        #if DEBUG
        // UI validation exercises account-scoped persistence without using a real
        // credential. Give that synthetic session a stable, opaque account key so
        // it follows the same isolation path as a JWT-backed production account.
        if isUIValidationSession {
            return Self.opaqueAccountScope(for: Self.uiValidationSubjectId)
        }
        #endif
        if let jwtScope = Self.accountScope(fromJWT: token) {
            return jwtScope
        }
        guard let userID = userInfo?.id?.trimmingCharacters(in: .whitespacesAndNewlines),
              !userID.isEmpty else {
            return nil
        }
        return Self.opaqueAccountScope(for: userID)
    }
    var isUIValidationSession: Bool {
        #if DEBUG
        token == Self.uiValidationToken && subjectId == Self.uiValidationSubjectId
        #else
        false
        #endif
    }

    #if DEBUG
    nonisolated static let uiValidationToken = "ui-validation-token"
    private static let uiValidationSubjectId = "UI-VALIDATION"
    #endif

    private let persistsAuth: Bool
    private let deviceHealthLifecycleStop: (() -> Void)?

    var managesDeviceHealthLifecycle: Bool {
        deviceHealthLifecycleStop != nil
    }

    private enum Keys {
        static let token = "auth_token"
        static let refreshToken = "auth_refresh_token"
        static let subjectId = "auth_subject_id"
    }

    private init(
        loadStoredAuth: Bool = true,
        persistsAuth: Bool = true,
        honorDebugOverrides: Bool = true,
        managesDeviceHealthLifecycle: Bool = true,
        deviceHealthLifecycleStop: (() -> Void)? = nil
    ) {
        self.persistsAuth = persistsAuth
        if managesDeviceHealthLifecycle {
            self.deviceHealthLifecycleStop = deviceHealthLifecycleStop ?? {
                AppleHealthBackgroundSyncCoordinator.shared.stop()
            }
        } else {
            self.deviceHealthLifecycleStop = nil
        }
        #if DEBUG
        let environment = ProcessInfo.processInfo.environment
        if honorDebugOverrides && Self.debugFlag("XJIE_UI_TEST_RESET_AUTH", environment: environment) {
            KeychainHelper.delete(forKey: Keys.token)
            KeychainHelper.delete(forKey: Keys.refreshToken)
            KeychainHelper.delete(forKey: Keys.subjectId)
        }
        if honorDebugOverrides,
           let debugToken = environment["XJIE_DEBUG_ACCESS_TOKEN"] ?? Self.launchArgumentValue(for: "XJIE_DEBUG_ACCESS_TOKEN"),
           !debugToken.isEmpty {
            token = debugToken
            refreshToken = environment["XJIE_DEBUG_REFRESH_TOKEN"] ?? Self.launchArgumentValue(for: "XJIE_DEBUG_REFRESH_TOKEN") ?? ""
            subjectId = environment["XJIE_DEBUG_SUBJECT_ID"] ?? Self.launchArgumentValue(for: "XJIE_DEBUG_SUBJECT_ID") ?? "UI-VALIDATION"
            return
        }
        #endif

        guard loadStoredAuth else { return }

        // SEC-01: 从 Keychain 读取登录态
        token = KeychainHelper.loadString(forKey: Keys.token) ?? ""
        refreshToken = KeychainHelper.loadString(forKey: Keys.refreshToken) ?? ""
        subjectId = KeychainHelper.loadString(forKey: Keys.subjectId) ?? ""

        #if DEBUG
        if token == Self.uiValidationToken && subjectId == Self.uiValidationSubjectId {
            clearStoredAuth()
            token = ""
            refreshToken = ""
            subjectId = ""
        }
        #endif
    }

    func setAuth(accessToken: String, refreshToken: String = "") {
        let currentScope = Self.accountScope(fromJWT: token)
        let incomingScope = Self.accountScope(fromJWT: accessToken)
        let isProvenSameAccount = currentScope != nil && currentScope == incomingScope

        // `setAuth` is also used by login flows that can replace an existing
        // session without first calling logout. Only matching JWT subjects prove
        // this is a token refresh; every other transition must isolate device data
        // before the new credential becomes observable.
        if !isProvenSameAccount {
            deviceHealthLifecycleStop?()
            subjectId = ""
            userInfo = nil
            if persistsAuth {
                KeychainHelper.delete(forKey: Keys.subjectId)
            }
        }

        self.token = accessToken
        self.refreshToken = refreshToken
        guard persistsAuth else { return }
        KeychainHelper.save(accessToken, forKey: Keys.token)
        KeychainHelper.save(refreshToken, forKey: Keys.refreshToken)
    }

    func setSubject(_ sid: String) {
        self.subjectId = sid
        guard persistsAuth else { return }
        KeychainHelper.save(sid, forKey: Keys.subjectId)
    }

    /// 拉取并同步当前账号的权威用户资料。
    ///
    /// - Parameter api: 用户资料请求使用的 API 实现；测试传入确定性 Mock。
    /// - Returns: 已通过当前账号校验并写入 `userInfo` 的服务端资料。
    /// - Throws: 请求失败、账号在请求期间切换，或响应 ID 与 JWT 主体不一致时抛错。
    @discardableResult
    func synchronizeUserInfo(using api: APIServiceProtocol = APIService.shared) async throws -> UserInfo {
        let expectedToken = token
        let expectedAccountScope = accountScope
        guard !expectedToken.isEmpty else { throw APIError.notLoggedIn }

        let fetched: UserInfo = try await api.get("/api/users/me")
        guard adoptUserInfo(
            fetched,
            expectedToken: expectedToken,
            expectedAccountScope: expectedAccountScope
        ) else {
            throw APIError.accountScopeChanged
        }
        return fetched
    }

    /// 将其他页面已获取的 `/api/users/me` 结果安全合并到全局认证状态。
    ///
    /// - Parameters:
    ///   - fetched: 服务端返回的当前用户资料。
    ///   - expectedAccountScope: 请求发起时捕获的账号作用域。
    /// - Returns: 仅当请求仍属于当前账号且用户 ID 一致时返回 `true`。
    @discardableResult
    func adoptUserInfo(_ fetched: UserInfo, expectedAccountScope: String) -> Bool {
        adoptUserInfo(
            fetched,
            expectedToken: token,
            expectedAccountScope: expectedAccountScope
        )
    }

    func logout() {
        deviceHealthLifecycleStop?()
        token = ""
        refreshToken = ""
        subjectId = ""
        userInfo = nil
        clearStoredAuth()
    }

    private func clearStoredAuth() {
        guard persistsAuth else { return }
        KeychainHelper.delete(forKey: Keys.token)
        KeychainHelper.delete(forKey: Keys.refreshToken)
        KeychainHelper.delete(forKey: Keys.subjectId)
    }

    func logout(ifCurrentToken expectedToken: String) {
        guard token == expectedToken else { return }
        logout()
    }

    /// 从 JWT 安全提取账号 `sub`，并返回不可逆的本地存储作用域。
    /// 无效、缺少 `sub` 或不是标准三段 JWT 时返回 nil，绝不退化为 token 明文。
    nonisolated static func accountScope(fromJWT token: String) -> String? {
        guard let subject = jwtSubject(from: token) else { return nil }
        return opaqueAccountScope(for: subject)
    }

    /// 从当前后端 JWT 的 `sub` 读取数字用户 ID；零、负数和非数字主体均拒绝。
    nonisolated static func numericUserID(fromJWT token: String) -> Int? {
        guard let subject = jwtSubject(from: token),
              let value = Int(subject),
              value > 0 else {
            return nil
        }
        return value
    }

    /// 只负责解析 JWT payload 中经规范化的 `sub`，不校验或暴露其他 claim。
    nonisolated private static func jwtSubject(from token: String) -> String? {
        let parts = token.split(separator: ".", omittingEmptySubsequences: false)
        guard parts.count == 3,
              let payloadData = decodeBase64URL(String(parts[1])),
              let payload = try? JSONSerialization.jsonObject(with: payloadData) as? [String: Any],
              let subject = payload["sub"] as? String else {
            return nil
        }
        let normalized = subject.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !normalized.isEmpty else { return nil }
        return normalized
    }

    nonisolated private static func decodeBase64URL(_ encoded: String) -> Data? {
        var base64 = encoded
            .replacingOccurrences(of: "-", with: "+")
            .replacingOccurrences(of: "_", with: "/")
        let remainder = base64.count % 4
        if remainder != 0 {
            base64.append(String(repeating: "=", count: 4 - remainder))
        }
        return Data(base64Encoded: base64)
    }

    nonisolated private static func opaqueAccountScope(for subject: String) -> String {
        let digest = SHA256.hash(data: Data(subject.utf8))
        return "account-" + digest.map { String(format: "%02x", $0) }.joined()
    }

    /// 合并资料前同时核对账号作用域、兼容 token 身份和服务端用户 ID。
    ///
    /// 对标准 JWT 允许同一账号刷新 token；对历史非 JWT 登录态只允许原 token
    /// 未变化。这样既不会丢弃正常刷新后的响应，也不会接纳旧账号的迟到结果。
    private func adoptUserInfo(
        _ fetched: UserInfo,
        expectedToken: String,
        expectedAccountScope: String?
    ) -> Bool {
        guard isLoggedIn else { return false }
        if let expectedAccountScope {
            guard accountScope == expectedAccountScope else { return false }
        } else {
            guard token == expectedToken else { return false }
        }

        if let tokenUserID = Self.numericUserID(fromJWT: token) {
            guard let rawID = fetched.id?.trimmingCharacters(in: .whitespacesAndNewlines),
                  let fetchedUserID = Int(rawID),
                  fetchedUserID == tokenUserID else {
                return false
            }
        }
        userInfo = fetched
        return true
    }

    #if DEBUG
    static func makeTestingInstance(deviceHealthLifecycleStop: (() -> Void)? = nil) -> AuthManager {
        AuthManager(
            loadStoredAuth: false,
            persistsAuth: false,
            honorDebugOverrides: false,
            managesDeviceHealthLifecycle: deviceHealthLifecycleStop != nil,
            deviceHealthLifecycleStop: deviceHealthLifecycleStop
        )
    }

    func startUIValidationSession() {
        clearStoredAuth()
        token = Self.uiValidationToken
        refreshToken = ""
        subjectId = Self.uiValidationSubjectId
        userInfo = nil
    }

    private static func launchArgumentValue(for key: String) -> String? {
        let arguments = ProcessInfo.processInfo.arguments
        for (index, argument) in arguments.enumerated() {
            if argument == key, arguments.indices.contains(index + 1) {
                return arguments[index + 1]
            }
            if argument.hasPrefix("\(key)=") {
                return String(argument.dropFirst(key.count + 1))
            }
        }
        return nil
    }

    private static func debugFlag(_ key: String, environment: [String: String]) -> Bool {
        if let value = environment[key], ["1", "true", "YES", "yes"].contains(value) {
            return true
        }
        return ProcessInfo.processInfo.arguments.contains(key)
    }
    #endif
}

struct UserInfo: Codable {
    let id: String?
    let email: String?
    let phone: String?
    let username: String?
    let is_admin: Bool?
    let created_at: String?
    let consent: UserConsent?
    let profile: UserProfile?
}

struct UserProfile: Codable {
    let sex: String?
    let age: Int?
    let height_cm: Double?
    let weight_kg: Double?
    let display_name: String?
}

struct UpdateProfileBody: Encodable {
    var sex: String?
    var age: Int?
    var height_cm: Double?
    var weight_kg: Double?
    var display_name: String?
}

struct UserConsent: Codable {
    let allow_ai_chat: Bool?
    let allow_data_upload: Bool?
}
