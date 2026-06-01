import Foundation

// MARK: - 仪表板 & 血糖

struct DashboardHealth: Codable {
    let glucose: GlucoseDashboard?
    let kcal_today: Double?
    let meals_today: [MealItem]?
    let data_quality: DataQuality?
    let metabolic_state: MetabolicState?
    let weekly_validation: WeeklyValidation?
    let cgm_quality: CGMQuality?
}

struct DataQuality: Codable {
    let glucose_gaps_hours: Double?
    let variability: String?
}

struct GlucoseDashboard: Codable {
    let last_24h: GlucoseSummary?
    let last_7d: GlucoseSummary?
}

struct GlucoseSummary: Codable {
    let window: String?
    let avg: Double?
    let tir_70_180_pct: Double?
    let min: Double?
    let max: Double?
    let variability: String?
    let gaps_hours: Double?
}

struct ProactiveMessage: Codable {
    let message: String?
    let has_rescue: Bool?
}

struct GlucosePoint: Codable, Identifiable {
    var id: String { ts }
    let ts: String
    let glucose_mgdl: Double
}

struct GlucoseRange: Codable {
    let min_ts: String?
    let max_ts: String?
}

struct MetabolicState: Codable {
    let date: String
    let level: String
    let score: Int
    let headline: String
    let reason: String
    let action: String
    let metrics: MetabolicMetrics?
    let overview: [MetabolicDayState]
}

struct MetabolicMetrics: Codable {
    let avg: Double?
    let tir_70_180_pct: Double?
    let min: Double?
    let max: Double?
    let variability: String?
    let reading_count: Int?
}

struct MetabolicDayState: Codable, Identifiable {
    var id: String { date }
    let date: String
    let level: String
    let score: Int
    let headline: String
    let reason: String
    let action: String
    let avg: Double?
    let tir_70_180_pct: Double?
    let reading_count: Int
}

struct WeeklyValidation: Codable {
    let headline: String
    let adherence_pct: Int
    let completed_actions: Int
    let total_actions: Int
    let tir_delta_pct: Double?
    let avg_delta_mgdl: Double?
    let summary: String
}

struct CGMQuality: Codable {
    let window_days: Int
    let active_days: Int
    let reading_count: Int
    let expected_readings: Int
    let completeness_pct: Int
    let gap_hours: Double
    let latest_ts: String?
    let status: String
    let message: String
}
