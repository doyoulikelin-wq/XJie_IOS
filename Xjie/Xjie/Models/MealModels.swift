import Foundation

// MARK: - Legacy dashboard compatibility

/// Legacy meal projection still decoded by the old glucose dashboard.
/// New dietary records must never be written through this type or `/api/meals`.
struct MealItem: Codable, Identifiable {
    let id: String?
    let meal_ts: String?
    let meal_ts_source: String?
    let kcal: Double?
    let tags: [String]?
    let notes: String?
}

struct MealPhoto: Decodable, Identifiable {
    let id: String?
    let status: String?
    let calorie_estimate_kcal: Double?
    let confidence: Double?
    let uploaded_at: String?
}

// MARK: - Dietary record contract

private protocol DietaryUnknownStringEnum: RawRepresentable, Codable where RawValue == String {
    static var unknown: Self { get }
}

extension DietaryUnknownStringEnum {
    init(from decoder: Decoder) throws {
        let raw = try decoder.singleValueContainer().decode(String.self)
        self = Self(rawValue: raw) ?? Self.unknown
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        try container.encode(rawValue)
    }
}

enum DietaryEntrySource: String, CaseIterable, Equatable, DietaryUnknownStringEnum, Sendable {
    case camera
    case photoLibrary = "photo_library"
    case text
    case voice
    case recent
    case chat
    case manual
    case unknown

    static let userFacingSources: [DietaryEntrySource] = [
        .camera, .photoLibrary, .text, .voice, .recent,
    ]

    var title: String {
        switch self {
        case .camera: return String(localized: "dietary.source.camera", defaultValue: "拍照记录")
        case .photoLibrary: return String(localized: "dietary.source.library", defaultValue: "从相册选择")
        case .text: return String(localized: "dietary.source.text", defaultValue: "文字描述")
        case .voice: return String(localized: "dietary.source.voice", defaultValue: "语音描述")
        case .recent: return String(localized: "dietary.source.recent", defaultValue: "最近餐食")
        case .chat: return String(localized: "dietary.source.chat", defaultValue: "来自问答")
        case .manual: return String(localized: "dietary.source.manual", defaultValue: "手动记录")
        case .unknown: return String(localized: "dietary.source.unknown", defaultValue: "其他来源")
        }
    }

    var symbol: String {
        switch self {
        case .camera: return "camera.fill"
        case .photoLibrary: return "photo.on.rectangle"
        case .text: return "text.cursor"
        case .voice: return "waveform"
        case .recent: return "clock.arrow.circlepath"
        case .chat: return "message.fill"
        case .manual: return "square.and.pencil"
        case .unknown: return "questionmark.circle"
        }
    }
}

/// Typed, local-only copy passed from another product surface into dietary entry.
/// Constructing this value never creates a server draft or a formal meal record.
struct DietaryEntryHandoff: Equatable, Sendable {
    let source: DietaryEntrySource
    let draftText: String

    static func chatCopy(_ rawDraft: String) -> Self? {
        guard !rawDraft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return nil }
        return Self(source: .chat, draftText: rawDraft)
    }
}

enum DietaryCameraDraftPresentationGate {
    static func canPresent(
        coverDidDismiss: Bool,
        hasPendingDraft: Bool,
        hasActiveSheet: Bool
    ) -> Bool {
        coverDidDismiss && hasPendingDraft && !hasActiveSheet
    }
}

enum DietaryMealType: String, CaseIterable, Equatable, DietaryUnknownStringEnum, Sendable {
    case breakfast
    case lunch
    case dinner
    case snack
    case unknown

    var title: String {
        switch self {
        case .breakfast: return String(localized: "dietary.meal.breakfast", defaultValue: "早餐")
        case .lunch: return String(localized: "dietary.meal.lunch", defaultValue: "午餐")
        case .dinner: return String(localized: "dietary.meal.dinner", defaultValue: "晚餐")
        case .snack: return String(localized: "dietary.meal.snack", defaultValue: "加餐")
        case .unknown: return String(localized: "dietary.meal.unknown", defaultValue: "未选择餐次")
        }
    }

    var symbol: String {
        switch self {
        case .breakfast: return "sunrise.fill"
        case .lunch: return "sun.max.fill"
        case .dinner: return "moon.stars.fill"
        case .snack: return "takeoutbag.and.cup.and.straw.fill"
        case .unknown: return "fork.knife"
        }
    }

    static func inferred(at date: Date, calendar: Calendar) -> DietaryMealType {
        switch calendar.component(.hour, from: date) {
        case 4..<10: return .breakfast
        case 10..<15: return .lunch
        case 17..<22: return .dinner
        default: return .snack
        }
    }
}

enum DietaryDraftStatus: String, Equatable, DietaryUnknownStringEnum, Sendable {
    case pendingConfirmation = "pending_confirmation"
    case confirmed
    case rejected
    case recognitionFailed = "recognition_failed"
    case recognizing
    case unknown
}

enum DietaryRecordStatus: String, Equatable, DietaryUnknownStringEnum, Sendable {
    case userConfirmed = "user_confirmed"
    case modified
    case deleted
    case unknown

    var title: String {
        switch self {
        case .userConfirmed: return String(localized: "dietary.status.confirmed", defaultValue: "已确认")
        case .modified: return String(localized: "dietary.status.modified", defaultValue: "已修改")
        case .deleted: return String(localized: "dietary.status.deleted", defaultValue: "已删除")
        case .unknown: return String(localized: "dietary.status.unknown", defaultValue: "状态待同步")
        }
    }
}

enum DietaryDayState: String, Equatable, DietaryUnknownStringEnum, Sendable {
    case open
    case waitingConfirmation = "waiting_confirmation"
    case incomplete
    case ready
    case stale
    case recalculating
    case failed
    case unknown
}

enum DietarySummaryState: String, Equatable, DietaryUnknownStringEnum, Sendable {
    case ready
    case incomplete
    case waitingConfirmation = "waiting_confirmation"
    case stale
    case recalculating
    case failed
    case unknown

    var canDisplayConclusion: Bool {
        self == .ready || self == .stale || self == .recalculating
    }
}

enum DietaryCompletionMode: String, Equatable, DietaryUnknownStringEnum, Sendable {
    case automatic
    case manual
    case unknown
}

enum DietaryCompletenessStatus: String, Equatable, DietaryUnknownStringEnum, Sendable {
    case complete
    case incomplete
    case waitingConfirmation = "waiting_confirmation"
    case unknown
}

/// Codable JSON value keeps server-owned structure/rule fields without teaching
/// the client to invent nutrition thresholds or natural-language conclusions.
indirect enum DietaryJSONValue: Codable, Equatable, Sendable {
    case string(String)
    case number(Double)
    case bool(Bool)
    case object([String: DietaryJSONValue])
    case array([DietaryJSONValue])
    case null

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() { self = .null }
        else if let value = try? container.decode(Bool.self) { self = .bool(value) }
        else if let value = try? container.decode(Double.self) { self = .number(value) }
        else if let value = try? container.decode(String.self) { self = .string(value) }
        else if let value = try? container.decode([String: DietaryJSONValue].self) { self = .object(value) }
        else if let value = try? container.decode([DietaryJSONValue].self) { self = .array(value) }
        else { throw DecodingError.dataCorruptedError(in: container, debugDescription: "Unsupported dietary JSON value") }
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
}

struct DietaryFoodItem: Codable, Identifiable, Equatable, Sendable {
    static let maximumNameLength = 160
    static let maximumDescriptionLength = 4_000

    var itemID: String
    var name: String
    var portionText: String?
    var categories: [String]
    var confidence: Double?
    var isEstimated: Bool

    var id: String { itemID }
    var isLowConfidence: Bool { (confidence ?? 1) < 0.7 }

    init(
        itemID: String = UUID().uuidString.lowercased(),
        name: String,
        portionText: String? = nil,
        categories: [String] = [],
        confidence: Double? = nil,
        isEstimated: Bool = false
    ) {
        self.itemID = itemID
        self.name = name
        self.portionText = portionText
        self.categories = categories
        self.confidence = confidence
        self.isEstimated = isEstimated
    }

    private enum CodingKeys: String, CodingKey {
        case itemID = "item_id"
        case id
        case name
        case portionText = "portion_text"
        case categories
        case confidence
        case isEstimated = "is_estimated"
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        itemID = try container.decodeLosslessStringIfPresent(forKey: .itemID)
            ?? container.decodeLosslessStringIfPresent(forKey: .id)
            ?? UUID().uuidString.lowercased()
        name = try container.decode(String.self, forKey: .name)
        portionText = try container.decodeIfPresent(String.self, forKey: .portionText)
        categories = try container.decodeIfPresent([String].self, forKey: .categories) ?? []
        confidence = try container.decodeIfPresent(Double.self, forKey: .confidence)
        isEstimated = (try container.decodeIfPresent(Bool.self, forKey: .isEstimated)) ?? (confidence != nil)
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(itemID, forKey: .itemID)
        try container.encode(name, forKey: .name)
        try container.encodeIfPresent(portionText, forKey: .portionText)
        try container.encode(categories, forKey: .categories)
        try container.encodeIfPresent(confidence, forKey: .confidence)
        try container.encode(isEstimated, forKey: .isEstimated)
    }
}

struct DietaryMealDraft: Codable, Identifiable, Equatable, Sendable {
    let draftID: String
    let subjectUserID: Int
    let sourceRef: String?
    var dietDate: String
    var timezone: String
    var mealType: DietaryMealType
    var eatenAt: String
    let sourceType: DietaryEntrySource
    var foodItems: [DietaryFoodItem]
    var portionText: String?
    var structure: [String: DietaryJSONValue]
    var estimatedNutrition: [String: DietaryJSONValue]
    var fieldConfidences: [String: Double]
    var recognitionConfidence: Double?
    var recognitionStatus: String
    var recognitionCacheReused: Bool
    var lowConfidenceFields: [String]
    var status: DietaryDraftStatus
    var version: Int
    let requiresUserConfirmation: Bool
    let formalRecordCreated: Bool
    let createdAt: String?
    let updatedAt: String?

    var id: String { draftID }
    var isEditable: Bool {
        (status == .pendingConfirmation || status == .recognitionFailed)
            && requiresUserConfirmation
            && !formalRecordCreated
    }
    var recognitionFailed: Bool {
        status == .recognitionFailed || recognitionStatus == "failed_manual_entry_available"
    }
    var canRetryRecognition: Bool {
        isEditable
            && recognitionFailed
            && (sourceType == .camera || sourceType == .photoLibrary)
    }

    private enum CodingKeys: String, CodingKey {
        case draftID = "draft_id"
        case subjectUserID = "subject_user_id"
        case sourceRef = "source_ref"
        case dietDate = "diet_date"
        case timezone
        case mealType = "meal_type"
        case eatenAt = "eaten_at"
        case sourceType = "source_type"
        case foodItems = "food_items"
        case portionText = "portion_text"
        case structure
        case estimatedNutrition = "estimated_nutrition"
        case fieldConfidences = "field_confidences"
        case recognitionConfidence = "recognition_confidence"
        case recognitionStatus = "recognition_status"
        case recognitionCacheReused = "recognition_cache_reused"
        case lowConfidenceFields = "low_confidence_fields"
        case status
        case version
        case requiresUserConfirmation = "requires_user_confirmation"
        case formalRecordCreated = "formal_record_created"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        guard let identifier = try container.decodeLosslessStringIfPresent(forKey: .draftID) else {
            throw DecodingError.keyNotFound(
                CodingKeys.draftID,
                .init(codingPath: decoder.codingPath, debugDescription: "draft_id is required")
            )
        }
        draftID = identifier
        subjectUserID = try container.decode(Int.self, forKey: .subjectUserID)
        sourceRef = try container.decodeIfPresent(String.self, forKey: .sourceRef)
        dietDate = try container.decode(String.self, forKey: .dietDate)
        timezone = try container.decodeIfPresent(String.self, forKey: .timezone) ?? "Asia/Shanghai"
        mealType = try container.decodeIfPresent(DietaryMealType.self, forKey: .mealType) ?? .unknown
        eatenAt = try container.decode(String.self, forKey: .eatenAt)
        sourceType = try container.decode(DietaryEntrySource.self, forKey: .sourceType)
        foodItems = try container.decodeIfPresent([DietaryFoodItem].self, forKey: .foodItems) ?? []
        portionText = try container.decodeIfPresent(String.self, forKey: .portionText)
        structure = try container.decodeIfPresent([String: DietaryJSONValue].self, forKey: .structure) ?? [:]
        estimatedNutrition = try container.decodeIfPresent([String: DietaryJSONValue].self, forKey: .estimatedNutrition) ?? [:]
        fieldConfidences = try container.decodeIfPresent([String: Double].self, forKey: .fieldConfidences) ?? [:]
        recognitionConfidence = try container.decodeIfPresent(Double.self, forKey: .recognitionConfidence)
        recognitionStatus = try container.decodeIfPresent(String.self, forKey: .recognitionStatus) ?? "not_required"
        recognitionCacheReused = try container.decodeIfPresent(Bool.self, forKey: .recognitionCacheReused) ?? false
        lowConfidenceFields = try container.decodeIfPresent([String].self, forKey: .lowConfidenceFields) ?? []
        status = try container.decode(DietaryDraftStatus.self, forKey: .status)
        version = try container.decode(Int.self, forKey: .version)
        requiresUserConfirmation = try container.decode(Bool.self, forKey: .requiresUserConfirmation)
        formalRecordCreated = try container.decodeIfPresent(Bool.self, forKey: .formalRecordCreated) ?? false
        createdAt = try container.decodeIfPresent(String.self, forKey: .createdAt)
        updatedAt = try container.decodeIfPresent(String.self, forKey: .updatedAt)
    }
}

struct DietaryMealRecord: Codable, Identifiable, Equatable, Sendable {
    let recordID: String
    let sourceDraftID: String?
    let subjectUserID: Int
    var dietDate: String
    var timezone: String
    var mealType: DietaryMealType
    var eatenAt: String
    let sourceType: DietaryEntrySource
    let sourceRef: String?
    var foodItems: [DietaryFoodItem]
    var portionText: String?
    var structure: [String: DietaryJSONValue]
    var estimatedNutrition: [String: DietaryJSONValue]
    var fieldConfidences: [String: Double]
    var confidence: Double?
    var status: DietaryRecordStatus
    var version: Int
    let trustState: String?
    let confirmedAt: String?
    let createdAt: String?
    let updatedAt: String?

    var id: String { recordID }
    var foodSummary: String {
        foodItems.map(\.name).filter { !$0.isEmpty }.joined(separator: "、")
    }

    private enum CodingKeys: String, CodingKey {
        case recordID = "record_id"
        case sourceDraftID = "source_draft_id"
        case subjectUserID = "subject_user_id"
        case dietDate = "diet_date"
        case timezone
        case mealType = "meal_type"
        case eatenAt = "eaten_at"
        case sourceType = "source_type"
        case sourceRef = "source_ref"
        case foodItems = "food_items"
        case portionText = "portion_text"
        case structure
        case estimatedNutrition = "estimated_nutrition"
        case fieldConfidences = "field_confidences"
        case confidence
        case status
        case version
        case trustState = "trust_state"
        case confirmedAt = "confirmed_at"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        guard let identifier = try container.decodeLosslessStringIfPresent(forKey: .recordID) else {
            throw DecodingError.keyNotFound(
                CodingKeys.recordID,
                .init(codingPath: decoder.codingPath, debugDescription: "record_id is required")
            )
        }
        recordID = identifier
        sourceDraftID = try container.decodeLosslessStringIfPresent(forKey: .sourceDraftID)
        subjectUserID = try container.decode(Int.self, forKey: .subjectUserID)
        dietDate = try container.decode(String.self, forKey: .dietDate)
        timezone = try container.decodeIfPresent(String.self, forKey: .timezone) ?? "Asia/Shanghai"
        mealType = try container.decode(DietaryMealType.self, forKey: .mealType)
        eatenAt = try container.decode(String.self, forKey: .eatenAt)
        sourceType = try container.decode(DietaryEntrySource.self, forKey: .sourceType)
        sourceRef = try container.decodeIfPresent(String.self, forKey: .sourceRef)
        foodItems = try container.decodeIfPresent([DietaryFoodItem].self, forKey: .foodItems) ?? []
        portionText = try container.decodeIfPresent(String.self, forKey: .portionText)
        structure = try container.decodeIfPresent([String: DietaryJSONValue].self, forKey: .structure) ?? [:]
        estimatedNutrition = try container.decodeIfPresent([String: DietaryJSONValue].self, forKey: .estimatedNutrition) ?? [:]
        fieldConfidences = try container.decodeIfPresent([String: Double].self, forKey: .fieldConfidences) ?? [:]
        confidence = try container.decodeIfPresent(Double.self, forKey: .confidence)
        status = try container.decode(DietaryRecordStatus.self, forKey: .status)
        version = try container.decode(Int.self, forKey: .version)
        trustState = try container.decodeIfPresent(String.self, forKey: .trustState)
        confirmedAt = try container.decodeIfPresent(String.self, forKey: .confirmedAt)
        createdAt = try container.decodeIfPresent(String.self, forKey: .createdAt)
        updatedAt = try container.decodeIfPresent(String.self, forKey: .updatedAt)
    }
}

struct DietaryDailySummary: Codable, Equatable, Sendable {
    let summaryID: String
    let subjectUserID: Int
    let dietDate: String
    let closeMethod: DietaryCompletionMode
    let recordComplete: Bool
    let confirmedMealCount: Int
    let pendingCount: Int
    let structureSummary: [String: DietaryJSONValue]
    let conclusion: String
    let todaySuggestion: String
    let confidence: Double
    let evidence: [String: DietaryJSONValue]
    let ruleVersion: String
    let templateVersion: String
    let recordVersion: Int
    let generatedAt: String?
    let recalculatedAfterEdit: Bool

    var completionMode: DietaryCompletionMode { closeMethod }
    var completenessStatus: DietaryCompletenessStatus { recordComplete ? .complete : .incomplete }
    var structure: [String: DietaryJSONValue] { structureSummary }
    var summaryState: DietarySummaryState { recordComplete ? .ready : .incomplete }
    var summaryConfidence: Double? { confidence }
    var structureConclusion: String? { conclusion }
    var actionSuggestion: String? { todaySuggestion }
    var recalculated: Bool { recalculatedAfterEdit }

    var evidenceItems: [String] {
        var items: [String] = []
        if case .array(let values)? = evidence["included_record_ids"] {
            items.append(String(format: String(localized: "dietary.evidence.confirmedCount", defaultValue: "%d 个已确认餐次"), values.count))
        }
        if case .array(let values)? = evidence["excluded_pending_draft_ids"], !values.isEmpty {
            items.append(String(format: String(localized: "dietary.evidence.pendingCount", defaultValue: "%d 个待确认项未纳入"), values.count))
        }
        if case .bool(false)? = evidence["natural_language_generated_by_model"] {
            items.append(String(localized: "dietary.evidence.fixedRules", defaultValue: "结论由固定规则和模板生成"))
        }
        return items
    }

    private enum CodingKeys: String, CodingKey {
        case summaryID = "summary_id"
        case subjectUserID = "subject_user_id"
        case dietDate = "diet_date"
        case closeMethod = "close_method"
        case recordComplete = "record_complete"
        case confirmedMealCount = "confirmed_meal_count"
        case pendingCount = "pending_count"
        case structureSummary = "structure_summary"
        case conclusion
        case todaySuggestion = "today_suggestion"
        case confidence
        case evidence
        case ruleVersion = "rule_version"
        case templateVersion = "template_version"
        case recordVersion = "record_version"
        case generatedAt = "generated_at"
        case recalculatedAfterEdit = "recalculated_after_edit"
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        guard let identifier = try container.decodeLosslessStringIfPresent(forKey: .summaryID) else {
            throw DecodingError.keyNotFound(
                CodingKeys.summaryID,
                .init(codingPath: decoder.codingPath, debugDescription: "summary_id is required")
            )
        }
        summaryID = identifier
        subjectUserID = try container.decode(Int.self, forKey: .subjectUserID)
        dietDate = try container.decode(String.self, forKey: .dietDate)
        closeMethod = try container.decode(DietaryCompletionMode.self, forKey: .closeMethod)
        recordComplete = try container.decode(Bool.self, forKey: .recordComplete)
        confirmedMealCount = try container.decode(Int.self, forKey: .confirmedMealCount)
        pendingCount = try container.decode(Int.self, forKey: .pendingCount)
        structureSummary = try container.decodeIfPresent([String: DietaryJSONValue].self, forKey: .structureSummary) ?? [:]
        conclusion = try container.decode(String.self, forKey: .conclusion)
        todaySuggestion = try container.decode(String.self, forKey: .todaySuggestion)
        confidence = try container.decode(Double.self, forKey: .confidence)
        evidence = try container.decodeIfPresent([String: DietaryJSONValue].self, forKey: .evidence) ?? [:]
        ruleVersion = try container.decode(String.self, forKey: .ruleVersion)
        templateVersion = try container.decode(String.self, forKey: .templateVersion)
        recordVersion = try container.decode(Int.self, forKey: .recordVersion)
        generatedAt = try container.decodeIfPresent(String.self, forKey: .generatedAt)
        recalculatedAfterEdit = try container.decode(Bool.self, forKey: .recalculatedAfterEdit)
    }
}

struct DietaryWeeklyReview: Codable, Equatable, Sendable {
    let windowStart: String
    let windowEnd: String
    let recordedDayCount: Int
    let completeDayCount: Int
    let proteinLowDays: Int
    let vegetablesAdequateDays: Int
    let usesScore: Bool

    var completeDays: Int { completeDayCount }
    var recordedDays: Int { recordedDayCount }
    var insights: [String] {
        var values: [String] = []
        if proteinLowDays > 0 {
            values.append(String(format: String(localized: "dietary.weekly.proteinLow", defaultValue: "%d 个记录日蛋白质偏少"), proteinLowDays))
        }
        if vegetablesAdequateDays > 0 {
            values.append(String(format: String(localized: "dietary.weekly.vegetablesAdequate", defaultValue: "%d 个记录日蔬菜较充足"), vegetablesAdequateDays))
        }
        return values
    }

    private enum CodingKeys: String, CodingKey {
        case windowStart = "window_start"
        case windowEnd = "window_end"
        case recordedDayCount = "recorded_day_count"
        case completeDayCount = "complete_day_count"
        case proteinLowDays = "protein_low_days"
        case vegetablesAdequateDays = "vegetables_adequate_days"
        case usesScore = "uses_score"
    }
}

struct DietaryDashboardResponse: Codable, Equatable, Sendable {
    let subjectUserID: Int
    let selectedDate: String
    let isToday: Bool
    let recordedMealCount: Int
    let pendingCount: Int
    let streakDays: Int
    let dayState: DietaryDayState
    let records: [DietaryMealRecord]
    let pendingDrafts: [DietaryMealDraft]
    let selectedDaySummary: DietaryDailySummary?
    let displayedSummary: DietaryDailySummary?
    let displayedSummaryDate: String
    let weeklyReview: DietaryWeeklyReview?

    private enum CodingKeys: String, CodingKey {
        case subjectUserID = "subject_user_id"
        case selectedDate = "selected_date"
        case isToday = "is_today"
        case recordedMealCount = "recorded_meal_count"
        case pendingCount = "pending_count"
        case streakDays = "streak_days"
        case dayState = "day_state"
        case records
        case pendingDrafts = "pending_drafts"
        case selectedDaySummary = "selected_day_summary"
        case displayedSummary = "displayed_summary"
        case displayedSummaryDate = "displayed_summary_date"
        case weeklyReview = "weekly_review"
    }
}

struct DietaryDayCompletionResponse: Codable, Equatable, Sendable {
    let subjectUserID: Int
    let dietDate: String
    let state: DietaryDayState
    let recordVersion: Int
    let closeMethod: DietaryCompletionMode?
    let recordComplete: Bool
    let confirmedMealCount: Int
    let pendingCount: Int
    let summary: DietaryDailySummary?

    private enum CodingKeys: String, CodingKey {
        case subjectUserID = "subject_user_id"
        case dietDate = "diet_date"
        case state
        case recordVersion = "record_version"
        case closeMethod = "close_method"
        case recordComplete = "record_complete"
        case confirmedMealCount = "confirmed_meal_count"
        case pendingCount = "pending_count"
        case summary
    }
}

struct DietaryRecentResponse: Codable, Equatable, Sendable {
    let subjectUserID: Int
    let items: [DietaryMealRecord]

    private enum CodingKeys: String, CodingKey {
        case subjectUserID = "subject_user_id"
        case items
    }
}

struct DietaryEditableDraft: Equatable, Sendable {
    let original: DietaryMealDraft
    var dietDate: String
    var mealType: DietaryMealType
    var eatenAt: String
    var foodItems: [DietaryFoodItem]
    var portionText: String
    var structure: [String: DietaryJSONValue]
    var estimatedNutrition: [String: DietaryJSONValue]

    init(_ draft: DietaryMealDraft) {
        original = draft
        dietDate = draft.dietDate
        mealType = draft.mealType
        eatenAt = draft.eatenAt
        foodItems = draft.foodItems.isEmpty
            ? [DietaryFoodItem(itemID: "draft-\(draft.draftID)-manual", name: "")]
            : draft.foodItems
        portionText = draft.portionText ?? ""
        structure = draft.structure
        estimatedNutrition = draft.estimatedNutrition
    }

    /// Adopts the server's new draft/version after a recognition retry while
    /// treating every locally edited field as authoritative. Recognition may
    /// fill untouched fields, but must never erase work entered before retry.
    func mergingRecognitionRetry(_ retried: DietaryMealDraft) -> Self {
        let baseline = Self(original)
        var merged = Self(retried)
        if dietDate != baseline.dietDate { merged.dietDate = dietDate }
        if mealType != baseline.mealType { merged.mealType = mealType }
        if eatenAt != baseline.eatenAt { merged.eatenAt = eatenAt }
        if foodItems != baseline.foodItems { merged.foodItems = foodItems }
        if portionText != baseline.portionText { merged.portionText = portionText }
        if structure != baseline.structure { merged.structure = structure }
        if estimatedNutrition != baseline.estimatedNutrition {
            merged.estimatedNutrition = estimatedNutrition
        }
        return merged
    }

    var isValid: Bool {
        mealType != .unknown
            && !dietDate.isEmpty
            && foodItems.contains { !$0.name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
    }
}

struct DietaryEditableRecord: Equatable, Sendable {
    let original: DietaryMealRecord
    var dietDate: String
    var mealType: DietaryMealType
    var eatenAt: String
    var foodItems: [DietaryFoodItem]
    var portionText: String
    var structure: [String: DietaryJSONValue]
    var estimatedNutrition: [String: DietaryJSONValue]

    init(record: DietaryMealRecord) {
        original = record
        dietDate = record.dietDate
        mealType = record.mealType
        eatenAt = record.eatenAt
        foodItems = record.foodItems.isEmpty ? [DietaryFoodItem(name: "")] : record.foodItems
        portionText = record.portionText ?? ""
        structure = record.structure
        estimatedNutrition = record.estimatedNutrition
    }

    var isValid: Bool {
        mealType != .unknown
            && !dietDate.isEmpty
            && foodItems.contains { !$0.name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
    }
}

// MARK: - Requests

struct DietaryDraftCreateRequest: Encodable, Sendable {
    let subject_user_id: Int?
    let client_event_id: String
    let source_type: DietaryEntrySource
    let diet_date: String
    let timezone: String
    let meal_type: DietaryMealType
    let eaten_at: String
    let food_items: [DietaryFoodItem]
    let portion_text: String?
    let structure: [String: DietaryJSONValue]
    let estimated_nutrition: [String: DietaryJSONValue]
    let field_confidences: [String: Double]
    let recognition_confidence: Double?
    let source_ref: String?
    let raw_input: String?
}

struct DietaryDraftConfirmRequest: Encodable, Sendable {
    let subject_user_id: Int
    let client_event_id: String
    let expected_version: Int
    let timezone: String
    let diet_date: String
    let meal_type: DietaryMealType
    let eaten_at: String
    let food_items: [DietaryFoodItem]
    let portion_text: String?
    let structure: [String: DietaryJSONValue]
    let estimated_nutrition: [String: DietaryJSONValue]
    let field_confidences: [String: Double]
    let recognition_confidence: Double?
}

struct DietaryDraftRetryRecognitionRequest: Encodable, Sendable {
    let subject_user_id: Int
    let client_event_id: String
    let expected_version: Int
}

struct DietaryRecordUpdateRequest: Encodable, Sendable {
    let subject_user_id: Int
    let client_event_id: String
    let expected_version: Int
    let timezone: String
    let diet_date: String
    let meal_type: DietaryMealType
    let eaten_at: String
    let food_items: [DietaryFoodItem]
    let portion_text: String?
    let structure: [String: DietaryJSONValue]
    let estimated_nutrition: [String: DietaryJSONValue]
    let field_confidences: [String: Double]
    let recognition_confidence: Double?
}

struct DietaryMutationRequest: Encodable, Sendable {
    let subject_user_id: Int
    let client_event_id: String
    let expected_version: Int
}

struct DietaryRecordReuseRequest: Encodable, Sendable {
    let subject_user_id: Int
    let client_event_id: String
    let expected_version: Int
    let timezone: String
    let diet_date: String
    let meal_type: DietaryMealType
    let eaten_at: String
}

struct DietaryDayCompleteRequest: Encodable, Sendable {
    let timezone: String
    let subject_user_id: Int
    let client_event_id: String
    let complete_with_confirmed_only: Bool
}

// MARK: - Day boundary

enum DietaryDayBoundary {
    static func dietDate(for date: Date, calendar: Calendar = .current) -> Date {
        let dayStart = calendar.startOfDay(for: date)
        let boundary = calendar.date(bySettingHour: 4, minute: 0, second: 0, of: dayStart) ?? dayStart
        if date < boundary {
            return calendar.date(byAdding: .day, value: -1, to: dayStart) ?? dayStart
        }
        return dayStart
    }

    static func dateKey(for date: Date, calendar: Calendar = .current) -> String {
        localDateFormatter(calendar: calendar).string(from: dietDate(for: date, calendar: calendar))
    }

    static func calendarDateKey(for date: Date, calendar: Calendar = .current) -> String {
        localDateFormatter(calendar: calendar).string(from: calendar.startOfDay(for: date))
    }

    static func date(from key: String, calendar: Calendar = .current) -> Date? {
        localDateFormatter(calendar: calendar).date(from: key)
    }

    static func clampedSelection(_ date: Date, now: Date, calendar: Calendar = .current) -> Date {
        min(calendar.startOfDay(for: date), dietDate(for: now, calendar: calendar))
    }

    private static func localDateFormatter(calendar: Calendar) -> DateFormatter {
        let formatter = DateFormatter()
        formatter.calendar = calendar
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = calendar.timeZone
        formatter.dateFormat = "yyyy-MM-dd"
        formatter.isLenient = false
        return formatter
    }
}

private extension KeyedDecodingContainer {
    func decodeLosslessStringIfPresent(forKey key: Key) throws -> String? {
        guard contains(key), try !decodeNil(forKey: key) else { return nil }
        if let string = try? decode(String.self, forKey: key) { return string }
        if let integer = try? decode(Int.self, forKey: key) { return String(integer) }
        return nil
    }
}
