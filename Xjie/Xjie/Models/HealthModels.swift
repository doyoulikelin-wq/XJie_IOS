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
    let greeting: String?
    let glucose_status: GlucoseStatus?
    let risk_windows: [RiskWindow]?
    let today_goals: [String]?
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
    var id: String {
        if let sourceID = source_id?.trimmingCharacters(in: .whitespacesAndNewlines),
           !sourceID.isEmpty {
            return (source ?? "unknown") + "-" + sourceID
        }
        return "\(date)-\(source ?? "unknown")-\(measured_at ?? "")"
    }
    let date: String
    let value: Double
    let abnormal: Bool
    let source: String?
    let measured_at: String?
    let source_metric: String?
    let source_id: String?
    let value_kind: String?
    let display_value: String?
    let source_local_date: String?
    let timezone_offset_minutes: Int?

    /// The server's source-local calendar day is the authoritative day for
    /// day-bucketed HealthKit values. Older responses continue to use `date`.
    var displayDate: String {
        if let localDate = source_local_date?.trimmingCharacters(in: .whitespacesAndNewlines),
           !localDate.isEmpty {
            return localDate
        }
        return date
    }

    var preferredDisplayValue: String? {
        let displayValue = display_value?.trimmingCharacters(in: .whitespacesAndNewlines)
        return displayValue?.isEmpty == false ? displayValue : nil
    }

    var isCategoricalValue: Bool {
        switch value_kind?.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() {
        case "category", "categorical": return true
        default: return false
        }
    }
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
    let plan_code: String?
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
    let plan_code: String?
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

struct HealthPlanQuestionnaireRequest: Encodable {
    let target: String
    let duration_days: Int
    let frequency: String
    let contents: [String]
    let medication_needed: Bool
    let notes: String?
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
    let plan_ids: [String]?
    let plan_codes: [String]?
    let source_task_ids: [String]?
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

struct PlanTaskUpdateRequest: Encodable {
    let title: String?
    let description: String?
    let target_count: Int?
    let target_value: Double?
    let unit: String?
    let reminder_time: String?
}

struct PlanRevisionGenerateRequest: Encodable {
    let date: String?
    let purpose: String?
}

struct PlanRevisionApplyRequest: Encodable {
    let accepted_task_keys: [String]
    let accept_all: Bool
    let reject_all: Bool
}

struct PlanRevisionProposal: Decodable, Identifiable {
    let id: String
    let date: String
    let status: String
    let purpose: String
    let original_items: [PlanRevisionItem]
    let revised_items: [PlanRevisionItem]
    let reasons: [PlanRevisionReason]
    let context_summary: String?
    let daily_limit_used: Bool
    let created_at: String
    let applied_at: String?
}

struct PlanRevisionItem: Decodable, Identifiable {
    var id: String { task_key }
    let task_key: String
    let task_type: String
    let label: String
    let title: String
    let description: String?
    let target_count: Int
    let target_value: Double?
    let unit: String?
    let reminder_time: String?
    let plan_ids: [String]
    let plan_codes: [String]
    let source_task_ids: [String]
    let summary: String?
}

struct PlanRevisionReason: Decodable, Identifiable {
    var id: String { task_key }
    let task_key: String
    let reason: String
    let evidence: String?
}
