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
    /// Kept separate from `name` so report history can be organized by hospital
    /// without parsing a server-generated title.
    let hospital: String?
    let doc_date: String?
    /// Fallback ordering evidence when a medical date has not been confirmed.
    let created_at: String?
    let csv_data: CSVData?
    let abnormal_flags: [AbnormalFlag]?
    let ai_brief: String?
    let ai_summary: String?
    let file_url: String?
    /// New report-trust workflow fields are additive so older servers remain decodable.
    let report_workflow_id: Int?
    let report_workflow_status: String?
    let report_subject_user_id: Int?
    let report_duplicate: Bool?
}

enum HealthReportWorkflowStatus: Hashable, Sendable, Codable {
    case draft
    case uploading
    case recognizing
    case awaitingConfirmation
    case committing
    case completed
    case completedScorePending
    case failed
    case unknown(String)

    init(rawValue: String) {
        switch rawValue.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() {
        case "draft": self = .draft
        case "uploading": self = .uploading
        case "recognizing": self = .recognizing
        case "awaiting_confirmation": self = .awaitingConfirmation
        case "committing": self = .committing
        case "completed": self = .completed
        case "completed_score_pending": self = .completedScorePending
        case "failed": self = .failed
        default: self = .unknown(rawValue)
        }
    }

    var rawValue: String {
        switch self {
        case .draft: return "draft"
        case .uploading: return "uploading"
        case .recognizing: return "recognizing"
        case .awaitingConfirmation: return "awaiting_confirmation"
        case .committing: return "committing"
        case .completed: return "completed"
        case .completedScorePending: return "completed_score_pending"
        case .failed: return "failed"
        case .unknown(let value): return value
        }
    }

    init(from decoder: Decoder) throws {
        self.init(rawValue: try decoder.singleValueContainer().decode(String.self))
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        try container.encode(rawValue)
    }
}

enum HealthReportTrustState: Equatable, Sendable {
    case workflow(HealthReportWorkflowStatus)
    case legacyRecognizing
    case legacyUnverified
}

struct HealthReportWorkflowRoute: Identifiable, Hashable, Sendable {
    let workflowID: Int
    let subjectUserID: Int
    let status: HealthReportWorkflowStatus
    let isDuplicate: Bool

    var id: Int { workflowID }
}

extension HealthDocument {
    var reportTrustState: HealthReportTrustState {
        if report_workflow_id != nil, let rawStatus = report_workflow_status {
            return .workflow(HealthReportWorkflowStatus(rawValue: rawStatus))
        }
        if extraction_status?.lowercased() == "pending" {
            return .legacyRecognizing
        }
        return .legacyUnverified
    }

    var reportWorkflowRoute: HealthReportWorkflowRoute? {
        guard let workflowID = report_workflow_id,
              let subjectUserID = report_subject_user_id,
              let rawStatus = report_workflow_status else { return nil }
        return HealthReportWorkflowRoute(
            workflowID: workflowID,
            subjectUserID: subjectUserID,
            status: HealthReportWorkflowStatus(rawValue: rawStatus),
            isDuplicate: report_duplicate ?? false
        )
    }

    /// Admission and scoring are deliberately separate. A score-pending report is
    /// admitted, but must not be presented as if score recalculation has completed.
    var isAdmittedTrustedReport: Bool {
        guard case .workflow(let status) = reportTrustState else { return false }
        return status == .completed || status == .completedScorePending
    }

    var isTrustedForScoreInputs: Bool {
        guard case .workflow(.completed) = reportTrustState else { return false }
        return true
    }

    var reportUploadNotice: String {
        switch reportTrustState {
        case .workflow(.draft), .workflow(.uploading), .workflow(.recognizing):
            return "报告已上传，正在生成候选字段；确认前不会作为可信健康数据使用。"
        case .workflow(.awaitingConfirmation):
            return "识别完成，请检查字段并确认整份报告；当前尚未入库。"
        case .workflow(.committing):
            return "报告确认请求正在处理，请勿重复提交。"
        case .workflow(.completedScorePending):
            return "报告已确认入库，评分仍在更新。"
        case .workflow(.completed):
            return "报告已确认入库，评分流程已完成。"
        case .workflow(.failed):
            return "报告识别失败，未进入可信健康数据。"
        case .workflow(.unknown):
            return "报告已上传，但状态待刷新；确认前不会作为可信健康数据使用。"
        case .legacyRecognizing:
            return "报告已上传，正在进行历史兼容识别；该流程没有报告级确认，结果不会作为可信数据使用。"
        case .legacyUnverified:
            return "识别已结束，但属于历史未验证流程，不会进入可信趋势、画像、评分或 AI 上下文。"
        }
    }
}

enum HealthReportJSONValue: Equatable, Sendable, Codable {
    case string(String)
    case number(Double)
    case bool(Bool)
    case object([String: HealthReportJSONValue])
    case array([HealthReportJSONValue])
    case null

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() {
            self = .null
        } else if let value = try? container.decode(Bool.self) {
            self = .bool(value)
        } else if let value = try? container.decode(Double.self) {
            self = .number(value)
        } else if let value = try? container.decode(String.self) {
            self = .string(value)
        } else if let value = try? container.decode([String: HealthReportJSONValue].self) {
            self = .object(value)
        } else if let value = try? container.decode([HealthReportJSONValue].self) {
            self = .array(value)
        } else {
            throw DecodingError.typeMismatch(
                HealthReportJSONValue.self,
                DecodingError.Context(codingPath: decoder.codingPath, debugDescription: "Unsupported JSON value")
            )
        }
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .string(let value): try container.encode(value)
        case .number(let value): try container.encode(value)
        case .bool(let value): try container.encode(value)
        case .object(let value): try container.encode(value)
        case .array(let value): try container.encode(value)
        case .null: try container.encodeNil()
        }
    }

    var stringValue: String? {
        guard case .string(let value) = self else { return nil }
        return value
    }

    var intValue: Int? {
        guard case .number(let value) = self, value.rounded() == value else { return nil }
        return Int(value)
    }
}

enum HealthReportCandidateReviewStatus: Equatable, Sendable, Codable {
    case pendingReview
    case autoAccepted
    case confirmed
    case corrected
    case rejected
    case unknown(String)

    init(rawValue: String) {
        switch rawValue.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() {
        case "pending_review": self = .pendingReview
        case "auto_accepted": self = .autoAccepted
        case "confirmed": self = .confirmed
        case "corrected": self = .corrected
        case "rejected": self = .rejected
        default: self = .unknown(rawValue)
        }
    }

    var rawValue: String {
        switch self {
        case .pendingReview: return "pending_review"
        case .autoAccepted: return "auto_accepted"
        case .confirmed: return "confirmed"
        case .corrected: return "corrected"
        case .rejected: return "rejected"
        case .unknown(let value): return value
        }
    }

    init(from decoder: Decoder) throws {
        self.init(rawValue: try decoder.singleValueContainer().decode(String.self))
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        try container.encode(rawValue)
    }
}

struct HealthReportFieldCandidate: Identifiable, Equatable, Sendable, Codable {
    let candidate_id: Int
    let candidate_key: String
    let version: Int
    let canonical_code: String?
    let canonical_name: String
    let raw_name: String?
    let raw_value: String?
    let raw_unit: String?
    let normalized_value: Double?
    let normalized_text: String?
    let normalized_unit: String?
    let reference_low: Double?
    let reference_high: Double?
    let reference_text: String?
    let abnormal_state: String
    let confidence: Double?
    let low_confidence: Bool?
    let conflict_reasons: [String]?
    let effective_at: String?
    let source_locator: [String: HealthReportJSONValue]
    let model_version: String?
    let review_status: HealthReportCandidateReviewStatus
    let requires_review: Bool

    var id: Int { candidate_id }
    var isLowConfidence: Bool { low_confidence == true }
    var hasConflict: Bool { !(conflict_reasons ?? []).isEmpty }
}

struct HealthReportFailureRecovery: Equatable, Sendable, Codable {
    let failure_code: String
    let recovery_action: String
    let retryable: Bool
    let allows_manual_candidate: Bool
}

struct HealthReportReview: Identifiable, Equatable, Sendable, Codable {
    let workflow_id: Int
    let legacy_document_id: Int?
    let subject_user_id: Int
    let status: HealthReportWorkflowStatus
    let version: Int
    let report_type: String
    let document_fingerprint: String?
    let recognized_at: String?
    let confirmed_at: String?
    let completed_at: String?
    let confirmation_client_event_id: String?
    let failure_code: String?
    let failure_detail: String?
    let failure_recovery: HealthReportFailureRecovery?
    let pending_review_count: Int
    let auto_accepted_count: Int
    let admitted_observation_count: Int
    let requires_report_confirmation: Bool
    let can_confirm: Bool
    let document: [String: HealthReportJSONValue]?
    let candidates: [HealthReportFieldCandidate]

    var id: Int { workflow_id }
}

struct HealthReportConfirmationEvent: Identifiable, Equatable, Sendable, Codable {
    let event_id: Int
    let candidate_id: Int
    let event_type: String
    let candidate_version: Int
    let before_data: [String: HealthReportJSONValue]
    let after_data: [String: HealthReportJSONValue]
    let created_at: String

    var id: Int { event_id }
}

struct HealthReportObservation: Identifiable, Equatable, Sendable, Codable {
    let observation_id: Int
    let source_candidate_id: Int
    let confirmation_event_id: Int
    let canonical_code: String?
    let canonical_name: String
    let value_numeric: Double?
    let value_text: String?
    let unit: String?
    let reference_low: Double?
    let reference_high: Double?
    let reference_text: String?
    let abnormal_state: String
    let effective_at: String
    let confirmed_at: String

    var id: Int { observation_id }
}

struct HealthReportProfileImpact: Identifiable, Equatable, Sendable, Codable {
    let profile_candidate_id: Int
    let source_id: Int
    let source_observation_id: Int
    let fact_key: String
    let category: String
    let proposed_value: [String: HealthReportJSONValue]
    let review_status: String
    let confidence: Double?

    var id: Int { profile_candidate_id }
}

struct HealthReportScoreSnapshot: Identifiable, Equatable, Sendable, Codable {
    let snapshot_id: Int
    let score_kind: String
    let algorithm_id: String
    let algorithm_version: String
    let before_value: Double?
    let after_value: Double?
    let before_confidence: Double?
    let after_confidence: Double?
    let score_direction: String?
    let semantic_outcome: String?
    let calculation_status: String
    let evidence: [String: HealthReportJSONValue]
    let missing_inputs: [String: HealthReportJSONValue]
    let failure_code: String?
    let computed_at: String?
    /// Durable score-job presentation. These are server-owned localized
    /// explanations; clients must not recreate algorithms or missing-input rules.
    let job_item_status: String?
    let method_summary: [String: HealthReportJSONValue]?
    let input_basis: [[String: HealthReportJSONValue]]?
    let failure: [String: HealthReportJSONValue]?

    var id: Int { snapshot_id }

    init(
        snapshot_id: Int,
        score_kind: String,
        algorithm_id: String,
        algorithm_version: String,
        before_value: Double?,
        after_value: Double?,
        before_confidence: Double?,
        after_confidence: Double?,
        score_direction: String?,
        semantic_outcome: String?,
        calculation_status: String,
        evidence: [String: HealthReportJSONValue],
        missing_inputs: [String: HealthReportJSONValue],
        failure_code: String?,
        computed_at: String?,
        job_item_status: String? = nil,
        method_summary: [String: HealthReportJSONValue]? = nil,
        input_basis: [[String: HealthReportJSONValue]]? = nil,
        failure: [String: HealthReportJSONValue]? = nil
    ) {
        self.snapshot_id = snapshot_id
        self.score_kind = score_kind
        self.algorithm_id = algorithm_id
        self.algorithm_version = algorithm_version
        self.before_value = before_value
        self.after_value = after_value
        self.before_confidence = before_confidence
        self.after_confidence = after_confidence
        self.score_direction = score_direction
        self.semantic_outcome = semantic_outcome
        self.calculation_status = calculation_status
        self.evidence = evidence
        self.missing_inputs = missing_inputs
        self.failure_code = failure_code
        self.computed_at = computed_at
        self.job_item_status = job_item_status
        self.method_summary = method_summary
        self.input_basis = input_basis
        self.failure = failure
    }
}

struct HealthReportFollowUpDetail: Identifiable, Equatable, Sendable, Codable {
    let item_id: Int
    let item_code: String
    let message: [String: HealthReportJSONValue]
    let due_at: String?
    let evidence: [[String: HealthReportJSONValue]]

    var id: Int { item_id }
}

struct HealthReportFollowUp: Equatable, Sendable, Codable {
    let available: Bool
    let items: [String]
    let details: [HealthReportFollowUpDetail]?
    let unavailable_reason: String?

    init(
        available: Bool,
        items: [String],
        details: [HealthReportFollowUpDetail]? = nil,
        unavailable_reason: String?
    ) {
        self.available = available
        self.items = items
        self.details = details
        self.unavailable_reason = unavailable_reason
    }
}

struct HealthReportInterpretation: Identifiable, Equatable, Sendable, Codable {
    let workflow_id: Int
    let subject_user_id: Int
    let status: HealthReportWorkflowStatus
    let available: Bool
    let unavailable_reason: String?
    let non_diagnostic_notice: String
    let document: [String: HealthReportJSONValue]?
    let candidates: [HealthReportFieldCandidate]
    let confirmation_events: [HealthReportConfirmationEvent]
    let structured_additions: [HealthReportObservation]
    let major_abnormalities: [HealthReportObservation]
    let follow_up: HealthReportFollowUp
    let profile_impacts: [HealthReportProfileImpact]
    let score_state: String
    let score_pending: Bool
    let score_snapshots: [HealthReportScoreSnapshot]

    var id: Int { workflow_id }
    var originalFileURL: String? { document?["file_url"]?.stringValue }
}

enum HealthReportDecisionAction: String, Equatable, Sendable, Codable {
    case confirm
    case correct
    case reject
}

struct HealthReportConfirmationDecision: Equatable, Sendable, Encodable {
    let candidate_id: Int
    let candidate_version: Int
    let action: HealthReportDecisionAction
    let value_numeric: Double?
    let value_text: String?
    let unit: String?
}

struct HealthReportConfirmationRequest: Equatable, Sendable, Encodable {
    let subject_user_id: Int
    let client_event_id: String
    let workflow_version: Int
    let decisions: [HealthReportConfirmationDecision]
}

struct HealthReportManualCandidateRequest: Equatable, Sendable, Encodable {
    let subject_user_id: Int
    let workflow_version: Int
    let client_event_id: String
    let canonical_code: String?
    let canonical_name: String
    let raw_name: String
    let value_numeric: Double?
    let value_text: String?
    let unit: String?
    let reference_low: Double?
    let reference_high: Double?
    let reference_text: String?
    let effective_at: String?
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
