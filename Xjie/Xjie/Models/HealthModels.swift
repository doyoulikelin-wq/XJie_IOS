import Foundation

// MARK: - 健康数据 & 文档

struct HealthDataSummary: Decodable {
    let summary_text: String?
    let updated_at: String?
}

struct SummaryTaskResponse: Decodable {
    let task_id: String
    let status: String          // pending | running | done | failed
    let stage: String?          // l1 | l2 | l3
    let stage_current: Int?
    let stage_total: Int?
    let progress_pct: Double?
    let token_used: Int?
    let error_message: String?
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
    let ai_brief: String?
    let ai_summary: String?
    let file_url: String?
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

struct IndicatorExplanation: Decodable {
    let name: String
    let brief: String
    let detail: String
    let normal_range: String?
    let clinical_meaning: String?
    let source: String
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

// MARK: - 健康计划 & 试管执行入口

struct HealthPlanListResponse: Decodable {
    let items: [HealthPlan]
}

struct HealthPlan: Decodable, Identifiable {
    let id: String
    let title: String
    let goal: String?
    let background: String?
    let start_date: String
    let end_date: String
    let status: String
    let source_conversation_id: String?
    let source_message_id: String?
    let created_by: String
    let created_at: String
    let updated_at: String
    let task_count: Int
    let completed_task_count: Int
}

struct HealthPlanDetail: Decodable, Identifiable {
    let id: String
    let title: String
    let goal: String?
    let background: String?
    let start_date: String
    let end_date: String
    let status: String
    let source_conversation_id: String?
    let source_message_id: String?
    let created_by: String
    let created_at: String
    let updated_at: String
    let task_count: Int
    let completed_task_count: Int
    let raw_content: String?
    let tasks: [PlanTask]
}

struct PlanTask: Decodable, Identifiable {
    let id: String
    let plan_id: String?
    let date: String
    let task_type: String
    let title: String
    let description: String?
    let status: String
    let target_count: Int
    let completed_count: Int
    let target_value: Double?
    let completed_value: Double?
    let unit: String?
    let reminder_time: String?
    let source_type: String
    let source_ref: String
}

struct HealthPlanFromChatRequest: Encodable {
    let content: String
    let analysis: String?
    let conversation_id: String?
    let message_id: String?
    let title: String?
}

struct TubeWeek: Decodable {
    let week_start: String
    let week_end: String
    let today: String
    let has_omics_data: Bool?
    let has_medication_need: Bool?
    let task_types: [String]?
    let days: [TubeDay]
}

struct TubeDay: Decodable, Identifiable {
    var id: String { date }
    let date: String
    let weekday: Int
    let is_today: Bool
    let is_future: Bool
    let completion_ratio: Double
    let tasks: [TubeTaskProgress]
}

struct TubeTaskProgress: Decodable, Identifiable {
    var id: String { task_type }
    let task_type: String
    let label: String
    let title: String?
    let description: String?
    let summary: String?
    let details: [String]?
    let completed: Int
    let target: Int
    let completed_value: Double?
    let target_value: Double?
    let unit: String?
    let ratio: Double
}

struct TubeCompleteRequest: Encodable {
    let date: String
    let task_type: String
    let amount: Int
    let value: Double?
}

struct TubeCompleteResponse: Decodable {
    let day: TubeDay
}

struct HealthTreeSummary: Decodable {
    let trees_grown: Int
    let fruiting_count: Int
    let active_plan_count: Int
}
