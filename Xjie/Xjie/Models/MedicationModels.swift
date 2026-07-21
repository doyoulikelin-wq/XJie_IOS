import Foundation

// MARK: - Legacy read-only migration data

/// Historical `/api/medications` row. Trusted medication screens may show it only
/// as a migration hint; it is never a confirmed plan, dose event, inventory fact,
/// or AI-visible medication source.
struct Medication: Identifiable, Codable, Equatable, Sendable {
    let id: Int
    var name: String
    var dosage: String?
    var frequency: String?
    var instructions: String?
    var schedule_times: [String]
    var course_start: String?
    var course_end: String?
    var photo_url: String?
    var enabled: Bool
    let created_at: String
    let updated_at: String

    func isCourseActive(on date: Date = Date()) -> Bool {
        let formatter = DateFormatter()
        formatter.calendar = Calendar(identifier: .gregorian)
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = .current
        formatter.dateFormat = "yyyy-MM-dd"
        let day = formatter.string(from: date)
        if let course_start, day < course_start { return false }
        if let course_end, day > course_end { return false }
        return true
    }
}

struct MedicationListResponse: Codable, Equatable, Sendable {
    let items: [Medication]
}

/// Kept only so the unreachable historical editor source continues to compile.
/// Production medication routes no longer submit this legacy CRUD body.
struct MedicationBody: Encodable, Equatable, Sendable {
    let name: String
    let dosage: String?
    let frequency: String?
    let instructions: String?
    let schedule_times: [String]
    let course_start: String?
    let course_end: String?
    let photo_url: String?
    let enabled: Bool
}

// MARK: - Trusted medication values

enum MedicationJSONValue: Codable, Equatable, Sendable {
    case string(String)
    case number(Double)
    case bool(Bool)
    case array([MedicationJSONValue])
    case object([String: MedicationJSONValue])
    case null

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() { self = .null }
        else if let value = try? container.decode(Bool.self) { self = .bool(value) }
        else if let value = try? container.decode(Double.self) { self = .number(value) }
        else if let value = try? container.decode(String.self) { self = .string(value) }
        else if let value = try? container.decode([MedicationJSONValue].self) { self = .array(value) }
        else { self = .object(try container.decode([String: MedicationJSONValue].self)) }
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .string(let value): try container.encode(value)
        case .number(let value): try container.encode(value)
        case .bool(let value): try container.encode(value)
        case .array(let value): try container.encode(value)
        case .object(let value): try container.encode(value)
        case .null: try container.encodeNil()
        }
    }

    var text: String? {
        switch self {
        case .string(let value): return value
        case .number(let value): return String(value)
        default: return nil
        }
    }

    var stringArray: [String] {
        guard case .array(let values) = self else { return [] }
        return values.compactMap(\.text)
    }
}

enum MedicationMealRelation: String, Codable, CaseIterable, Sendable {
    case unspecified
    case beforeMeal = "before_meal"
    case afterMeal = "after_meal"
    case withMeal = "with_meal"

    var title: String {
        switch self {
        case .unspecified: return "未指定"
        case .beforeMeal: return "饭前"
        case .afterMeal: return "饭后"
        case .withMeal: return "随餐"
        }
    }
}

enum MedicationSourceType: String, Codable, Sendable {
    case manual
    case prescriptionImport = "prescription_import"
    case ocr
    case history

    var title: String {
        switch self {
        case .manual: return "手动确认"
        case .prescriptionImport: return "已确认处方"
        case .ocr: return "OCR 识别后确认"
        case .history: return "历史用药重新确认"
        }
    }
}

enum MedicationPlanStatus: String, Codable, Sendable {
    case active
    case paused
    case completed
    case retracted

    var title: String {
        switch self {
        case .active: return "服用中"
        case .paused: return "已暂停"
        case .completed: return "已结束"
        case .retracted: return "已撤回"
        }
    }
}

enum MedicationTaskStatus: String, Codable, Sendable {
    case upcoming
    case awaitingConfirmation = "awaiting_confirmation"
    case snoozed
    case possiblyMissed = "possibly_missed"
    case taken
    case skipped

    var title: String {
        switch self {
        case .upcoming: return "时间未到"
        case .awaitingConfirmation: return "等待确认"
        case .snoozed: return "稍后提醒"
        case .possiblyMissed: return "可能漏服，仍待确认"
        case .taken: return "已确认服用"
        case .skipped: return "本次跳过"
        }
    }

    var needsUserDecision: Bool {
        switch self {
        case .upcoming, .awaitingConfirmation, .snoozed, .possiblyMissed: return true
        case .taken, .skipped: return false
        }
    }
}

enum MedicationReactionSeverity: String, Codable, CaseIterable, Sendable {
    case mild
    case moderate
    case severe

    var title: String {
        switch self {
        case .mild: return "轻度"
        case .moderate: return "中度"
        case .severe: return "严重"
        }
    }
}

struct MedicationInventoryEstimate: Codable, Equatable, Sendable {
    let is_estimate: Bool
    let label: String
    let estimated_remaining: Double?
    let estimated_consumed: Double?
    let inventory_unit: String?
    let basis: String
    let unavailable_reason: String?
}

struct TrustedMedicationPlan: Identifiable, Codable, Equatable, Sendable {
    let plan_id: Int
    let subject_user_id: Int
    let generic_name: String
    let brand_name: String?
    let strength: String?
    let dose_text: String?
    let dose_quantity: Double?
    let frequency: String?
    let schedule_times: [String]
    let meal_relation: MedicationMealRelation
    let instructions: String?
    let course_start: String?
    let course_end: String?
    let prescriber: String?
    let initial_quantity: Double?
    let inventory_unit: String?
    let is_long_term: Bool
    let source_type: MedicationSourceType
    let source_ref: String
    let status: MedicationPlanStatus
    let version: Int
    let confirmed_at: String
    let trust_state: String
    let reminder_management: String
    let reminder_default_enabled: Bool
    let server_notification_scheduled: Bool
    let inventory: MedicationInventoryEstimate

    var id: Int { plan_id }
    var displayName: String {
        guard let brand_name, !brand_name.isEmpty else { return generic_name }
        return "\(generic_name)（\(brand_name)）"
    }
}

struct TrustedMedicationPlanList: Codable, Equatable, Sendable {
    let subject_user_id: Int
    let items: [TrustedMedicationPlan]
}

struct MedicationPrefillCandidate: Identifiable, Codable, Equatable, Sendable {
    let candidate_id: Int
    let subject_user_id: Int
    let client_event_id: String
    let source_type: MedicationSourceType
    let source_ref: String
    let extracted_data: [String: MedicationJSONValue]
    let field_confidences: [String: Double]
    let low_confidence_fields: [String]
    let review_status: String
    let version: Int
    let trust_state: String
    let requires_user_confirmation: Bool
    let plan_created: Bool
    let confirmation_endpoint: String

    var id: Int { candidate_id }
    var isPendingReview: Bool {
        review_status == "pending_review"
            && trust_state == "unconfirmed_prefill"
            && requires_user_confirmation
            && !plan_created
    }
}

struct MedicationPrefillList: Codable, Equatable, Sendable {
    let subject_user_id: Int
    let items: [MedicationPrefillCandidate]
}

struct MedicationTodayTask: Identifiable, Codable, Equatable, Sendable {
    let occurrence_key: String
    let plan_id: Int
    let plan_version: Int
    let generic_name: String
    let brand_name: String?
    let dose_text: String?
    let scheduled_local_date: String
    let scheduled_time: String
    let scheduled_at: String
    let status: MedicationTaskStatus
    let status_label: String
    let status_assertion: String
    let occurrence_version: Int
    let latest_event_id: Int?
    let snoozed_until: String?
    let confirmed_at: String?
    let possibly_missed_is_not_confirmation: Bool
    let notification_schedule_status: String

    var id: String { occurrence_key }
    var displayName: String {
        guard let brand_name, !brand_name.isEmpty else { return generic_name }
        return "\(generic_name)（\(brand_name)）"
    }
}

struct MedicationTodaySummary: Codable, Equatable, Sendable {
    let subject_user_id: Int
    let local_date: String
    let planned_count: Int
    let taken_count: Int
    let awaiting_confirmation_count: Int
    let possibly_missed_count: Int
    let skipped_count: Int
    let snoozed_count: Int
    let adverse_reaction_count: Int
    let next_task: MedicationTodayTask?
    let tasks: [MedicationTodayTask]
    let empty_state: String?
    let missed_assertion_policy: String

    var allTasksExplicitlyResolved: Bool {
        planned_count > 0 && tasks.allSatisfy { !$0.status.needsUserDecision }
    }
}

struct MedicationRecognitionBody: Encodable, Equatable, Sendable {
    let raw_text: String
    let subject_user_id: Int
    let client_event_id: String
}

struct MedicationRecognitionResult: Codable, Equatable, Sendable {
    let name: String?
    let dosage: String?
    let frequency: String?
    let instructions: String?
    let schedule_times: [String]
    let candidate_id: Int
    let candidate_version: Int
    let client_event_id: String
    let field_confidences: [String: Double]
    let low_confidence_fields: [String]
    let trust_state: String
    let requires_user_confirmation: Bool
    let plan_created: Bool
    let confirmation_endpoint: String

    var isUnconfirmedPrefill: Bool {
        trust_state == "unconfirmed_prefill"
            && requires_user_confirmation
            && !plan_created
    }
}

// MARK: - Trusted mutation requests

struct MedicationPlanConfirmRequest: Encodable, Equatable, Sendable {
    let subject_user_id: Int
    let client_request_id: String
    let client_event_id: String
    let candidate_id: Int?
    let candidate_version: Int?
    let generic_name: String
    let brand_name: String?
    let strength: String?
    let dose_text: String?
    let dose_quantity: Double?
    let frequency: String?
    let schedule_times: [String]
    let meal_relation: MedicationMealRelation
    let instructions: String?
    let course_start: String?
    let course_end: String?
    let prescriber: String?
    let initial_quantity: Double?
    let inventory_unit: String?
    let is_long_term: Bool
    let source_type: MedicationSourceType
    let source_ref: String?
}

struct MedicationPlanReviseRequest: Encodable, Equatable, Sendable {
    let subject_user_id: Int
    let client_event_id: String
    let expected_version: Int
    let generic_name: String
    let brand_name: String?
    let strength: String?
    let dose_text: String?
    let dose_quantity: Double?
    let frequency: String?
    let schedule_times: [String]
    let meal_relation: MedicationMealRelation
    let instructions: String?
    let course_start: String?
    let course_end: String?
    let prescriber: String?
    let initial_quantity: Double?
    let inventory_unit: String?
    let is_long_term: Bool
    let source_type: MedicationSourceType
    let source_ref: String?
}

struct MedicationPlanStatusRequest: Encodable, Equatable, Sendable {
    enum Action: String, Encodable, Sendable { case pause, resume, complete, retract }
    let subject_user_id: Int
    let client_event_id: String
    let expected_version: Int
    let action: Action
    let reason: String?
}

struct MedicationPrefillRejectRequest: Encodable, Equatable, Sendable {
    let subject_user_id: Int
    let client_event_id: String
    let expected_version: Int
}

struct MedicationDoseActionRequest: Encodable, Equatable, Sendable {
    enum Action: String, Encodable, Sendable { case taken, snooze, skip, correct }
    enum CorrectedStatus: String, Encodable, Sendable { case taken, snoozed, skipped, pending }

    let subject_user_id: Int
    let plan_id: Int
    let expected_plan_version: Int
    let client_event_id: String
    let scheduled_local_date: String
    let scheduled_time: String
    let expected_occurrence_version: Int
    let action: Action
    let corrected_status: CorrectedStatus?
    let correction_of_event_id: Int?
    let snoozed_until: String?
    let taken_quantity: Double?
    let reason: String?
}

struct MedicationDoseEvent: Codable, Equatable, Sendable {
    let event_id: Int
    let occurrence_key: String
    let occurrence_version: Int
    let action: String
    let effective_status: String
    let supersedes_event_id: Int?
    let snoozed_until: String?
    let taken_quantity: Double?
    let reason: String?
    let confirmed_at: String
    let trust_state: String
    let notification_schedule_status: String
    let reminder_management: String
}

struct MedicationReactionFields: Equatable, Sendable {
    let plan_id: Int
    let symptoms: String
    let onset_at: String
    let severity: MedicationReactionSeverity
    let duration_minutes: Int?
    let related_occurrence_key: String?
    let notes: String?
}

struct MedicationReactionCreateRequest: Encodable, Equatable, Sendable {
    let subject_user_id: Int
    let client_event_id: String
    let reaction_key: String
    let plan_id: Int
    let symptoms: String
    let onset_at: String
    let severity: MedicationReactionSeverity
    let duration_minutes: Int?
    let related_occurrence_key: String?
    let notes: String?
}

struct MedicationReactionCorrectRequest: Encodable, Equatable, Sendable {
    let subject_user_id: Int
    let client_event_id: String
    let expected_version: Int
    let plan_id: Int
    let symptoms: String
    let onset_at: String
    let severity: MedicationReactionSeverity
    let duration_minutes: Int?
    let related_occurrence_key: String?
    let notes: String?
}

struct MedicationReactionRetractRequest: Encodable, Equatable, Sendable {
    let subject_user_id: Int
    let client_event_id: String
    let expected_version: Int
}

struct MedicationReaction: Identifiable, Codable, Equatable, Sendable {
    let reaction_key: String
    let reaction_version: Int
    let plan_id: Int
    let symptoms: String
    let onset_at: String
    let severity: MedicationReactionSeverity
    let duration_minutes: Int?
    let related_occurrence_key: String?
    let notes: String?
    let status: String
    let causal_attribution: String
    let user_facing_causality: String
    let safety_guidance: String
    let confirmed_at: String

    var id: String { reaction_key }
}

struct MedicationReactionList: Codable, Equatable, Sendable {
    let subject_user_id: Int
    let items: [MedicationReaction]
}

// MARK: - Presentation invariants

enum MedicationPrimaryAction: Equatable, Sendable {
    case addFirstMedication
    case reviewPrefill(Int)
    case confirmDose(String)
    case viewMedicationRecord
}

enum MedicationTrustPolicy {
    static func primaryAction(
        today: MedicationTodaySummary?,
        plans: [TrustedMedicationPlan],
        pendingPrefills: [MedicationPrefillCandidate]
    ) -> MedicationPrimaryAction {
        if let candidate = pendingPrefills.first(where: \.isPendingReview) {
            return .reviewPrefill(candidate.candidate_id)
        }
        if let task = today?.next_task, task.status.needsUserDecision {
            return .confirmDose(task.occurrence_key)
        }
        if plans.filter({ $0.status != .retracted }).isEmpty {
            return .addFirstMedication
        }
        return .viewMedicationRecord
    }

    static func acceptsPossiblyMissedAsConfirmed(_ task: MedicationTodayTask) -> Bool {
        task.status != .possiblyMissed
            || (!task.possibly_missed_is_not_confirmation && task.status_assertion == "user_confirmed")
    }

    static func isServerInventoryEstimate(_ inventory: MedicationInventoryEstimate) -> Bool {
        inventory.is_estimate
            && inventory.label == "预计剩余"
            && inventory.basis == "user_confirmed_taken_events_only"
    }
}

struct MedicationPlanDraft: Equatable, Sendable {
    var genericName = ""
    var brandName = ""
    var strength = ""
    var doseText = ""
    var doseQuantity = ""
    var frequency = ""
    var scheduleTimes: [String] = []
    var mealRelation: MedicationMealRelation = .unspecified
    var instructions = ""
    var courseStart = ""
    var courseEnd = ""
    var prescriber = ""
    var initialQuantity = ""
    var inventoryUnit = ""
    var isLongTerm = false

    var validationIssue: String? {
        let name = genericName.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty else { return "请填写药品通用名。" }
        guard name.count <= 160 else { return "药品通用名不能超过 160 个字符。" }

        let dose = doseQuantity.trimmingCharacters(in: .whitespacesAndNewlines)
        var doseValue: Double?
        if !dose.isEmpty {
            guard let value = Double(dose), value.isFinite, value > 0 else {
                return "每次消耗数量必须是大于 0 的有限数字。"
            }
            doseValue = value
        }

        let initial = initialQuantity.trimmingCharacters(in: .whitespacesAndNewlines)
        let unit = inventoryUnit.trimmingCharacters(in: .whitespacesAndNewlines)
        if initial.isEmpty || unit.isEmpty {
            guard initial.isEmpty && unit.isEmpty else {
                return "初始数量与余量单位必须一起填写。"
            }
        } else {
            guard unit.count <= 32 else { return "余量单位不能超过 32 个字符。" }
            guard let value = Double(initial), value.isFinite, value >= 0 else {
                return "初始数量必须是大于或等于 0 的有限数字。"
            }
            guard let doseValue else {
                return "填写初始数量时，还需填写同一单位的每次消耗数量。"
            }
            guard value >= doseValue else {
                return "初始数量不足一次用量，请核对数量和单位。"
            }
        }

        if !courseStart.isEmpty,
           MedicationDateWindow.inclusiveDates(from: courseStart, through: courseStart).isEmpty {
            return "疗程开始日期必须是有效的 YYYY-MM-DD。"
        }
        if !courseEnd.isEmpty,
           MedicationDateWindow.inclusiveDates(from: courseEnd, through: courseEnd).isEmpty {
            return "疗程结束日期必须是有效的 YYYY-MM-DD。"
        }
        if !courseStart.isEmpty, !courseEnd.isEmpty,
           MedicationDateWindow.inclusiveDates(from: courseStart, through: courseEnd).isEmpty {
            return "疗程结束日期不能早于开始日期。"
        }
        guard scheduleTimes.count <= 24,
              scheduleTimes.allSatisfy(MedicationReminderPolicy.isValidTime) else {
            return "服用时间必须是 00:00–23:59 的 HH:mm 格式。"
        }
        return nil
    }

    var isValid: Bool { validationIssue == nil }

    init() {}

    init(candidate: MedicationPrefillCandidate) {
        genericName = candidate.extracted_data["name"]?.text ?? ""
        doseText = candidate.extracted_data["dosage"]?.text ?? ""
        frequency = candidate.extracted_data["frequency"]?.text ?? ""
        instructions = candidate.extracted_data["instructions"]?.text ?? ""
        scheduleTimes = candidate.extracted_data["schedule_times"]?.stringArray ?? []
    }

    init(plan: TrustedMedicationPlan) {
        genericName = plan.generic_name
        brandName = plan.brand_name ?? ""
        strength = plan.strength ?? ""
        doseText = plan.dose_text ?? ""
        doseQuantity = plan.dose_quantity.map { String($0) } ?? ""
        frequency = plan.frequency ?? ""
        scheduleTimes = plan.schedule_times
        mealRelation = plan.meal_relation
        instructions = plan.instructions ?? ""
        courseStart = plan.course_start ?? ""
        courseEnd = plan.course_end ?? ""
        prescriber = plan.prescriber ?? ""
        initialQuantity = plan.initial_quantity.map { String($0) } ?? ""
        inventoryUnit = plan.inventory_unit ?? ""
        isLongTerm = plan.is_long_term
    }

    init(legacy medication: Medication) {
        genericName = medication.name
        doseText = medication.dosage ?? ""
        frequency = medication.frequency ?? ""
        scheduleTimes = medication.schedule_times
        instructions = medication.instructions ?? ""
        courseStart = medication.course_start ?? ""
        courseEnd = medication.course_end ?? ""
    }
}

/// 用药编辑表单的快捷输入预设与应用规则。
/// 替换型字段直接使用选中值；使用说明则在已有有效内容后以中文逗号连接。
enum MedicationQuickInput {
    enum Behavior {
        case replace
        case appendInstruction
    }

    static let dosageOptions = ["半片", "1片", "2片", "5mg", "10mg"]
    static let frequencyOptions = ["每日1次", "每日2次", "每日3次", "睡前1次", "按需服用"]
    static let instructionOptions = ["饭后服用", "随餐服用", "空腹服用", "睡前服用", "整片吞服"]

    static func applying(_ option: String, to current: String, behavior: Behavior) -> String {
        switch behavior {
        case .replace:
            return option
        case .appendInstruction:
            guard !current.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
                return option
            }
            return "\(current)，\(option)"
        }
    }
}
