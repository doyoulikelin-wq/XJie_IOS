import Foundation
import Combine

/// 认证管理器 — SEC-01: 使用 Keychain 安全存储 Token（替代 UserDefaults）
@MainActor
final class AuthManager: ObservableObject {
    static let shared = AuthManager()

    @Published var token: String = ""
    @Published var refreshToken: String = ""
    @Published var subjectId: String = ""
    @Published var userInfo: UserInfo?

    var isLoggedIn: Bool { !token.isEmpty }
    var isUIValidationSession: Bool {
        #if DEBUG
        token == Self.uiValidationToken && subjectId == Self.uiValidationSubjectId
        #else
        false
        #endif
    }

    #if DEBUG
    private static let uiValidationToken = "ui-validation-token"
    private static let uiValidationSubjectId = "UI-VALIDATION"
    #endif

    private let persistsAuth: Bool

    private enum Keys {
        static let token = "auth_token"
        static let refreshToken = "auth_refresh_token"
        static let subjectId = "auth_subject_id"
    }

    private init(
        loadStoredAuth: Bool = true,
        persistsAuth: Bool = true,
        honorDebugOverrides: Bool = true
    ) {
        self.persistsAuth = persistsAuth
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

    func logout() {
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

    #if DEBUG
    static func makeTestingInstance() -> AuthManager {
        AuthManager(loadStoredAuth: false, persistsAuth: false, honorDebugOverrides: false)
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
