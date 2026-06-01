import Foundation

// MARK: - 认证相关

struct AuthResponse: Codable {
    let access_token: String
    let refresh_token: String?
}

struct SubjectItem: Codable, Identifiable {
    var id: String { subject_id }
    let subject_id: String
    let cohort: String?
}

struct LoginSubjectBody: Encodable {
    let subject_id: String
}

struct LoginPhoneBody: Encodable {
    let phone: String
    let username: String
    let password: String
    var sex: String? = nil
    var age: Int? = nil
    var height_cm: Double? = nil
    var weight_kg: Double? = nil
}

struct WxLoginBody: Encodable {
    let code: String
}

struct OnboardingNeedsRequest: Encodable {
    let target: String?
    let contents: [String]
    let generate_plan: Bool
    let completed: Bool
}
