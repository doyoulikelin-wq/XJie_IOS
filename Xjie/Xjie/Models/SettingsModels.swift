import Foundation

// MARK: - 设置

struct UserSettings: Decodable {
    let intervention_level: String?
    let daily_reminder_limit: Int?
    let glucose_unit: String?
    let elderly_mode: Bool?
    let elderly_checkin_interval_min: Int?
}

struct UpdateSettingsBody: Encodable {
    let intervention_level: String?
    var glucose_unit: String? = nil
    var elderly_mode: Bool? = nil
    var elderly_checkin_interval_min: Int? = nil
}

struct UpdateConsentBody: Encodable {
    let allow_ai_chat: Bool?
    let allow_data_upload: Bool?
}
