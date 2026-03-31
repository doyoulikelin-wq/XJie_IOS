import Foundation

// MARK: - 健康数据 & 文档

struct HealthDataSummary: Decodable {
    let summary_text: String?
    let updated_at: String?
}

struct DocumentListResponse: Decodable {
    let items: [HealthDocument]?
    let total: Int?
}

struct HealthDocument: Decodable, Identifiable {
    let id: String
    let name: String?
    let doc_type: String?
    let source_type: String?
    let extraction_status: String?
    let doc_date: String?
    let csv_data: CSVData?
    let abnormal_flags: [AbnormalFlag]?
}

struct CSVData: Decodable {
    let columns: [String]?
    let rows: [[String]]?
}

struct AbnormalFlag: Decodable, Identifiable {
    var id: String { field ?? name ?? UUID().uuidString }
    let field: String?
    let name: String?
    let value: String?
    let unit: String?
    let ref_range: String?
}

// MARK: - 健康简报

struct TodayBriefing: Decodable {
    let glucose_status: GlucoseStatus?
    let daily_plan: DailyPlan?
    let pending_rescues: [RescueItem]?
    let recent_actions: [ActionItem]?
}

struct GlucoseStatus: Decodable {
    let current_mgdl: Double?
    let trend: String?
    let tir_24h: Double?
}

struct DailyPlan: Decodable {
    let payload: DailyPlanPayload
}

struct DailyPlanPayload: Decodable {
    let title: String?
    let risk_windows: [RiskWindow]?
    let today_goals: [String]?
}

struct RiskWindow: Decodable, Identifiable {
    var id: String { "\(start ?? "")-\(end ?? "")" }
    let start: String?
    let end: String?
    let risk: String?
}

struct RescueItem: Decodable, Identifiable {
    let id: String
    let payload: RescuePayload?
}

struct RescuePayload: Decodable {
    let title: String?
    let risk_level: String?
}

struct ActionItem: Decodable, Identifiable {
    let id: String
    let action_type: String?
    let created_ts: String?
}

struct HealthReports: Decodable {
    let initial: HealthReportEntry?
    let `final`: HealthReportEntry?
}

struct HealthReportEntry: Decodable {
    let date: String?
}

struct AISummaryResponse: Decodable {
    let summary: String?
}

// MARK: - 指标趋势

struct IndicatorInfo: Decodable, Identifiable {
    var id: String { name }
    let name: String
    let category: String?
    let count: Int
}

struct IndicatorListResponse: Decodable {
    let indicators: [IndicatorInfo]
}

struct TrendPoint: Decodable, Identifiable {
    var id: String { date }
    let date: String
    let value: Double
    let abnormal: Bool
}

struct IndicatorTrend: Decodable, Identifiable {
    var id: String { name }
    let name: String
    let unit: String?
    let ref_low: Double?
    let ref_high: Double?
    let points: [TrendPoint]
}

struct IndicatorTrendResponse: Decodable {
    let indicators: [IndicatorTrend]
}

struct WatchedIndicatorItem: Decodable, Identifiable {
    var id: String { indicator_name }
    let indicator_name: String
    let category: String?
    let display_order: Int
}

struct WatchedListResponse: Decodable {
    let items: [WatchedIndicatorItem]
}
