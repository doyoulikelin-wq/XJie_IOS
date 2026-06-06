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

    private enum Keys {
        static let token = "auth_token"
        static let refreshToken = "auth_refresh_token"
        static let subjectId = "auth_subject_id"
    }

    private init() {
        #if DEBUG
        let environment = ProcessInfo.processInfo.environment
        if let debugToken = environment["XJIE_DEBUG_ACCESS_TOKEN"], !debugToken.isEmpty {
            token = debugToken
            refreshToken = environment["XJIE_DEBUG_REFRESH_TOKEN"] ?? ""
            subjectId = environment["XJIE_DEBUG_SUBJECT_ID"] ?? "UI-VALIDATION"
            return
        }
        #endif

        // SEC-01: 从 Keychain 读取登录态
        token = KeychainHelper.loadString(forKey: Keys.token) ?? ""
        refreshToken = KeychainHelper.loadString(forKey: Keys.refreshToken) ?? ""
        subjectId = KeychainHelper.loadString(forKey: Keys.subjectId) ?? ""
    }

    func setAuth(accessToken: String, refreshToken: String = "") {
        self.token = accessToken
        self.refreshToken = refreshToken
        KeychainHelper.save(accessToken, forKey: Keys.token)
        KeychainHelper.save(refreshToken, forKey: Keys.refreshToken)
    }

    func setSubject(_ sid: String) {
        self.subjectId = sid
        KeychainHelper.save(sid, forKey: Keys.subjectId)
    }

    func logout() {
        token = ""
        refreshToken = ""
        subjectId = ""
        userInfo = nil
        KeychainHelper.delete(forKey: Keys.token)
        KeychainHelper.delete(forKey: Keys.refreshToken)
        KeychainHelper.delete(forKey: Keys.subjectId)
    }
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
