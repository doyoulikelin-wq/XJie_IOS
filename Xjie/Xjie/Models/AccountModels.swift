import Foundation

// MARK: - 通用

struct SimpleOk: Codable {
    let ok: Bool?
    let message: String?
    let added: Int?
    let total_seed: Int?
}

// MARK: - 修改 / 重置密码

struct PasswordChangeBody: Encodable {
    let old_password: String
    let new_password: String
}

struct PasswordResetRequestBody: Encodable {
    let phone: String
}

struct PasswordResetConfirmBody: Encodable {
    let phone: String
    let code: String
    let new_password: String
}

// MARK: - 指标搜索 + 手动录入

struct IndicatorSearchItem: Codable, Identifiable {
    var id: String { name }
    let name: String
    let alias: String?
    let category: String?
    let brief: String?
    let normal_range: String?
    let unit: String?
    let score: Double?
}

struct IndicatorSearchResponse: Decodable {
    let items: [IndicatorSearchItem]
}

struct ManualIndicatorBody: Encodable {
    let indicator_name: String
    let value: Double
    let unit: String?
    let measured_at: String   // ISO-8601 with offset
    let notes: String?
}

struct ManualIndicatorItem: Decodable, Identifiable {
    let id: Int
    let indicator_name: String
    let value: Double
    let unit: String?
    let measured_at: String?
    let notes: String?
}

struct ManualIndicatorListResponse: Decodable {
    let items: [ManualIndicatorItem]
}

// MARK: - 锻炼记录

struct ExerciseBody: Encodable {
    let activity_type: String
    let duration_minutes: Int
    let intensity: String?
    let calories_kcal: Double?
    let notes: String?
    let started_at: String?
}

struct ExerciseItem: Decodable, Identifiable {
    let id: Int
    let activity_type: String
    let duration_minutes: Int
    let intensity: String?
    let calories_kcal: Double?
    let notes: String?
    let started_at: String?
}

struct ExerciseListResponse: Decodable {
    let items: [ExerciseItem]
    let total_minutes: Int
    let total_kcal: Double
}
