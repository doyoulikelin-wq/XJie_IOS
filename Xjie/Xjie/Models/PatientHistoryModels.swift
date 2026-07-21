import Foundation

// MARK: - 病史整理模型（对齐后端 /api/health-data/patient-history）

/// 单个字段（既往诊断、过敏、用药 等）
struct PatientHistoryField: Codable, Equatable {
    var value: String
    var date_label: String?
    /// missing | none | pending_review | confirmed | documented
    var status: String
    /// user | document | both | system | unknown
    var source_type: String
    var source_ref: String?
    var verified_by_user: Bool

    init(
        value: String = "",
        date_label: String? = nil,
        status: String = "missing",
        source_type: String = "user",
        source_ref: String? = nil,
        verified_by_user: Bool = false
    ) {
        self.value = value
        self.date_label = date_label
        self.status = status
        self.source_type = source_type
        self.source_ref = source_ref
        self.verified_by_user = verified_by_user
    }
}

struct PatientHistoryEvidence: Codable, Equatable {
    var record_count: Int
    var exam_count: Int
    var latest_record_date: String?
    var latest_exam_date: String?

    init(record_count: Int = 0, exam_count: Int = 0, latest_record_date: String? = nil, latest_exam_date: String? = nil) {
        self.record_count = record_count
        self.exam_count = exam_count
        self.latest_record_date = latest_record_date
        self.latest_exam_date = latest_exam_date
    }
}

struct PatientHistoryMetric: Codable, Identifiable, Equatable {
    var name: String
    var value: String
    var unit: String?
    var date_label: String?
    var status: String
    var source_type: String?
    var source_ref: String?
    /// records | exams | indicator | upload
    var focus: String

    var id: String { "\(name)-\(date_label ?? "")-\(value)" }
}

struct MissingSection: Codable, Identifiable, Equatable {
    var key: String
    var label: String
    var id: String { key }
}

struct PatientHistoryProfile: Codable, Equatable {
    var doctor_summary: String
    var sections: [String: PatientHistoryField]
    var key_metrics: [PatientHistoryMetric]
    var evidence_overview: PatientHistoryEvidence
    var missing_sections: [MissingSection]
    var completeness: Double
    var updated_at: String?
    var verified_at: String?

    init(
        doctor_summary: String,
        sections: [String: PatientHistoryField],
        key_metrics: [PatientHistoryMetric],
        evidence_overview: PatientHistoryEvidence,
        missing_sections: [MissingSection],
        completeness: Double,
        updated_at: String?,
        verified_at: String?
    ) {
        self.doctor_summary = doctor_summary
        self.sections = PatientHistorySectionCatalog.migrateLegacySections(sections)
        self.key_metrics = key_metrics
        self.evidence_overview = evidence_overview
        self.missing_sections = PatientHistorySectionCatalog.migrateLegacyMissingSections(missing_sections)
        self.completeness = completeness
        self.updated_at = updated_at
        self.verified_at = verified_at
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        self.init(
            doctor_summary: try container.decodeIfPresent(String.self, forKey: .doctor_summary) ?? "",
            sections: try container.decodeIfPresent([String: PatientHistoryField].self, forKey: .sections) ?? [:],
            key_metrics: try container.decodeIfPresent([PatientHistoryMetric].self, forKey: .key_metrics) ?? [],
            evidence_overview: try container.decodeIfPresent(PatientHistoryEvidence.self, forKey: .evidence_overview) ?? PatientHistoryEvidence(),
            missing_sections: try container.decodeIfPresent([MissingSection].self, forKey: .missing_sections) ?? [],
            completeness: try container.decodeIfPresent(Double.self, forKey: .completeness) ?? 0,
            updated_at: try container.decodeIfPresent(String.self, forKey: .updated_at),
            verified_at: try container.decodeIfPresent(String.self, forKey: .verified_at)
        )
    }

    static let empty = PatientHistoryProfile(
        doctor_summary: "",
        sections: [:],
        key_metrics: [],
        evidence_overview: PatientHistoryEvidence(),
        missing_sections: [],
        completeness: 0,
        updated_at: nil,
        verified_at: nil
    )
}

/// 保存请求体
struct PatientHistoryProfileIn: Encodable {
    var doctor_summary: String
    var sections: [String: PatientHistoryField]
    var verified_at: String?

    init(doctor_summary: String, sections: [String: PatientHistoryField], verified_at: String?) {
        self.doctor_summary = doctor_summary
        self.sections = PatientHistorySectionCatalog.migrateLegacySections(sections)
        self.verified_at = verified_at
    }
}

// MARK: - 字段元数据（顺序 + 中文标签 + 提示）

struct PatientHistorySectionMeta: Identifiable {
    let key: String
    let label: String
    let placeholder: String
    var id: String { key }
}

enum PatientHistorySectionCatalog {
    /// 与 Android `PatientHistorySections` / 后端默认字段对齐
    static let all: [PatientHistorySectionMeta] = [
        .init(key: "diagnoses", label: "既往明确诊断", placeholder: "如：2型糖尿病（2018 年）、高血压"),
        .init(key: "surgeries", label: "手术或住院史", placeholder: "如：2020 年阑尾切除"),
        .init(key: "medications", label: "长期 / 当前用药", placeholder: "如：二甲双胍 0.5g 每日 2 次"),
        .init(key: "allergies", label: "过敏或不良反应", placeholder: "如：青霉素皮疹；无明确过敏请填\"无\""),
        .init(key: "recent_findings", label: "近一年重要异常检查", placeholder: "如：HbA1c 7.6%、肝脏脂肪变性"),
        .init(key: "care_goals", label: "本次就诊重点关注", placeholder: "如：希望医生关注血糖波动与餐后血糖"),
        .init(key: "family_history", label: "家族史", placeholder: "如：父亲糖尿病、母亲高血压"),
        .init(key: "lifestyle_risks", label: "生活方式风险因素", placeholder: "如：久坐、夜班、吸烟史 10 年")
    ]

    private static let legacyKeys = [
        "abnormal_findings": "recent_findings",
        "current_focus": "care_goals"
    ]

    static func canonicalKey(for key: String) -> String {
        legacyKeys[key] ?? key
    }

    static func migrateLegacySections(
        _ sections: [String: PatientHistoryField]
    ) -> [String: PatientHistoryField] {
        var migrated = sections
        for (legacyKey, canonicalKey) in legacyKeys {
            guard let legacy = migrated.removeValue(forKey: legacyKey) else { continue }
            guard let canonical = migrated[canonicalKey] else {
                migrated[canonicalKey] = legacy
                continue
            }
            migrated[canonicalKey] = merge(canonical: canonical, legacy: legacy)
        }
        return migrated
    }

    static func migrateLegacyMissingSections(_ sections: [MissingSection]) -> [MissingSection] {
        var seen = Set<String>()
        return sections.compactMap { section in
            let key = canonicalKey(for: section.key)
            guard seen.insert(key).inserted else { return nil }
            return MissingSection(key: key, label: section.label)
        }
    }

    private static func merge(
        canonical: PatientHistoryField,
        legacy: PatientHistoryField
    ) -> PatientHistoryField {
        let canonicalValue = canonical.value.trimmingCharacters(in: .whitespacesAndNewlines)
        let legacyValue = legacy.value.trimmingCharacters(in: .whitespacesAndNewlines)
        let valuesConflict = !canonicalValue.isEmpty && !legacyValue.isEmpty && canonicalValue != legacyValue
        let noneConflicts = (canonical.status == "none" && !legacyValue.isEmpty)
            || (legacy.status == "none" && !canonicalValue.isEmpty)
        guard valuesConflict || noneConflicts else {
            if canonicalValue.isEmpty, !legacyValue.isEmpty { return legacy }
            if canonicalValue.isEmpty, canonical.status == "missing" { return legacy }
            return canonical
        }

        var merged = canonicalValue.isEmpty ? legacy : canonical
        merged.value = [canonicalValue, legacyValue]
            .filter { !$0.isEmpty }
            .reduce(into: [String]()) { values, value in
                if !values.contains(value) { values.append(value) }
            }
            .joined(separator: "\n")
        merged.date_label = canonical.date_label == legacy.date_label ? canonical.date_label : nil
        merged.status = "pending_review"
        merged.source_type = "both"
        merged.source_ref = canonical.source_ref == legacy.source_ref ? canonical.source_ref : nil
        merged.verified_by_user = false
        return merged
    }

    static func label(forKey key: String) -> String {
        let canonical = canonicalKey(for: key)
        return all.first(where: { $0.key == canonical })?.label ?? canonical
    }
}

// MARK: - 状态展示辅助

enum PatientHistoryStatusDisplay {
    static func text(_ status: String) -> String {
        switch status {
        case "confirmed": return "已确认"
        case "pending_review": return "待核对"
        case "none": return "明确无"
        case "documented": return "有资料"
        case "missing": return "未填写"
        default: return status
        }
    }

    static func sourceText(_ source: String?) -> String {
        switch source {
        case "user": return "患者填写"
        case "document": return "资料提取"
        case "both": return "两者结合"
        case "system": return "系统汇总"
        default: return "未知来源"
        }
    }
}

// MARK: - Server-authoritative health profile

/// The legacy patient-history types above remain decode-only compatibility for
/// previously saved records. New product UI must use this trust contract and
/// must never promote report-derived candidates into facts locally.
struct HealthProfileTrustResponse: Codable, Equatable, Sendable {
    let subject_user_id: Int
    let profile_status: String?
    let overview: HealthProfileOverview
    let facts: [HealthProfileFact]
    let candidates: [HealthProfileCandidate]
    let goals: [HealthProfileGoal]
    let management_plans: [HealthProfileManagementPlan]

    init(
        subject_user_id: Int,
        profile_status: String? = nil,
        overview: HealthProfileOverview,
        facts: [HealthProfileFact],
        candidates: [HealthProfileCandidate],
        goals: [HealthProfileGoal] = [],
        management_plans: [HealthProfileManagementPlan] = []
    ) {
        self.subject_user_id = subject_user_id
        self.profile_status = profile_status
        self.overview = overview
        self.facts = facts
        self.candidates = candidates
        self.goals = goals
        self.management_plans = management_plans
    }

    private enum CodingKeys: String, CodingKey {
        case subject_user_id
        case profile_status
        case overview
        case facts
        case candidates
        case goals
        case management_plans
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        subject_user_id = try container.decode(Int.self, forKey: .subject_user_id)
        profile_status = try container.decodeIfPresent(String.self, forKey: .profile_status)
        overview = try container.decode(HealthProfileOverview.self, forKey: .overview)
        facts = try container.decode([HealthProfileFact].self, forKey: .facts)
        candidates = try container.decode([HealthProfileCandidate].self, forKey: .candidates)
        goals = try container.decodeIfPresent([HealthProfileGoal].self, forKey: .goals) ?? []
        management_plans = try container.decodeIfPresent(
            [HealthProfileManagementPlan].self,
            forKey: .management_plans
        ) ?? []
    }
}

struct HealthProfileOverview: Codable, Equatable, Sendable {
    let completeness_percent: Int
    let resolved_required_weight: Int
    let total_required_weight: Int
    let missing_required_fact_keys: [String]
    let pending_update_count: Int
    let independent_source_count: Int
    let primary_action: HealthProfilePrimaryAction?

    init(
        completeness_percent: Int,
        resolved_required_weight: Int,
        total_required_weight: Int,
        missing_required_fact_keys: [String],
        pending_update_count: Int,
        independent_source_count: Int,
        primary_action: HealthProfilePrimaryAction? = nil
    ) {
        self.completeness_percent = completeness_percent
        self.resolved_required_weight = resolved_required_weight
        self.total_required_weight = total_required_weight
        self.missing_required_fact_keys = missing_required_fact_keys
        self.pending_update_count = pending_update_count
        self.independent_source_count = independent_source_count
        self.primary_action = primary_action
    }
}

struct HealthProfilePrimaryAction: Codable, Equatable, Sendable {
    let kind: String
    let item_count: Int
    let localization_key: String
    let route: String

    var isSupported: Bool {
        item_count >= 0
            && ["review_updates", "complete_profile", "edit_profile"].contains(kind)
            && ["profile_updates", "profile_safety_editor", "profile_editor"].contains(route)
    }

    /// The count is intentionally taken only from the server action. The app
    /// never recomputes action priority or item counts from local arrays.
    var title: String {
        switch kind {
        case "review_updates": return "检查 \(item_count) 项更新"
        case "complete_profile": return "完善 \(item_count) 项资料"
        case "edit_profile": return "编辑健康画像"
        default: return "画像状态暂不可用"
        }
    }

    var statusText: String {
        switch kind {
        case "review_updates": return "有 \(item_count) 项更新等待你决定"
        case "complete_profile": return "还有 \(item_count) 项资料可完善"
        case "edit_profile": return "画像已更新"
        default: return "服务端暂未返回可执行的画像状态"
        }
    }
}

struct HealthProfileGoalMetric: Codable, Equatable, Identifiable, Sendable {
    let metric_key: String
    let display_label: String?

    var id: String { metric_key }
    var title: String {
        let trimmed = display_label?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return trimmed.isEmpty ? metric_key : trimmed
    }
}

struct HealthProfileGoal: Codable, Equatable, Identifiable, Sendable {
    let goal_id: Int
    let name: String
    let status: HealthProfileGoalStatus
    let started_on: String
    let version: Int
    let confirmed_at: String
    let metrics: [HealthProfileGoalMetric]

    var id: Int { goal_id }
}

/// Read-only health-plan projection returned with the trusted profile.
/// Editing and execution stay in the existing HealthPlan module.
struct HealthProfileManagementPlan: Codable, Equatable, Identifiable, Sendable {
    let plan_id: Int
    let title: String
    let goal: String?
    let start_date: String
    let end_date: String
    let status: String
    let created_by: String
    let updated_at: String
    let task_count: Int
    let completed_task_count: Int

    var id: Int { plan_id }
}

struct HealthProfileGoalMetricRequest: Codable, Equatable, Sendable {
    let metric_key: String
    let display_label: String?
}

struct HealthProfileGoalCreateRequest: Encodable, Equatable, Sendable {
    let subject_user_id: Int
    let client_event_id: String
    let name: String
    let started_on: String
    let metrics: [HealthProfileGoalMetricRequest]
}

struct HealthProfileGoalUpdateRequest: Encodable, Equatable, Sendable {
    let subject_user_id: Int
    let client_event_id: String
    let expected_version: Int
    let name: String
    let started_on: String
    let metrics: [HealthProfileGoalMetricRequest]
}

enum HealthProfileGoalAction: String, Codable, Equatable, Sendable {
    case pause
    case resume
    case complete
    case archive
}

struct HealthProfileGoalStatusRequest: Encodable, Equatable, Sendable {
    let subject_user_id: Int
    let client_event_id: String
    let expected_version: Int
    let action: HealthProfileGoalAction
}

enum HealthProfileRevisionTargetKind: String, Codable, Equatable, Sendable {
    case fact
    case goal
}

struct HealthProfileRevisionItem: Codable, Equatable, Identifiable, Sendable {
    let revision_id: Int
    let event_type: String
    let target_version: Int
    let actor_user_id: Int?
    let before_data: [String: HealthReportJSONValue]
    let after_data: [String: HealthReportJSONValue]
    let created_at: String

    var id: Int { revision_id }
}

struct HealthProfileRevisionList: Codable, Equatable, Sendable {
    let subject_user_id: Int
    let target_kind: HealthProfileRevisionTargetKind
    let target_id: Int
    let items: [HealthProfileRevisionItem]
    let next_after_revision_id: Int?
}

struct HealthProfileHistoryTarget: Identifiable, Equatable, Sendable {
    let kind: HealthProfileRevisionTargetKind
    let id: Int
    let title: String
}

struct HealthProfileLongTermMedicationSummary: Codable, Equatable, Sendable {
    let subject_user_id: Int
    let items: [HealthProfileLongTermMedicationSummaryItem]
}

struct HealthProfileLongTermMedicationSummaryItem: Codable, Equatable, Identifiable, Sendable {
    let medication_name: String
    let purpose: String?
    let started_on: String?
    let is_still_taking: Bool
    let source: String
    let last_confirmed_at: String

    var id: String {
        [medication_name, started_on ?? "", source, last_confirmed_at].joined(separator: "|")
    }

    /// This is the sole rendering contract for the profile medication card.
    /// Dose, reminder and adherence operations cannot enter it by construction.
    var displayFields: [HealthProfileMedicationSummaryDisplayField] {
        let normalizedPurpose = purpose?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        let normalizedStart = started_on?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return [
            .init(key: .medicationName, title: "药名", value: medication_name),
            .init(key: .purpose, title: "用途", value: normalizedPurpose.isEmpty ? "未填写" : normalizedPurpose),
            .init(key: .startedOn, title: "开始时间", value: normalizedStart.isEmpty ? "未填写" : normalizedStart),
            .init(key: .isStillTaking, title: "是否仍在服用", value: is_still_taking ? "是" : "否"),
            .init(key: .source, title: "来源", value: HealthProfileDisplayFormatter.medicationSource(source)),
            .init(key: .lastConfirmedAt, title: "最近确认", value: HealthProfileDisplayFormatter.timestamp(last_confirmed_at))
        ]
    }
}

enum HealthProfileMedicationSummaryFieldKey: String, CaseIterable, Sendable {
    case medicationName = "medication_name"
    case purpose
    case startedOn = "started_on"
    case isStillTaking = "is_still_taking"
    case source
    case lastConfirmedAt = "last_confirmed_at"
}

struct HealthProfileMedicationSummaryDisplayField: Identifiable, Equatable, Sendable {
    let key: HealthProfileMedicationSummaryFieldKey
    let title: String
    let value: String

    var id: HealthProfileMedicationSummaryFieldKey { key }
}

struct HealthProfileSource: Codable, Equatable, Identifiable, Sendable {
    let source_id: Int
    let source_type: String
    let source_ref: String
    let confidence: Double?
    let source_snapshot: [String: HealthReportJSONValue]
    let created_at: String

    var id: Int { source_id }
}

struct HealthProfileFact: Codable, Equatable, Identifiable, Sendable {
    let fact_id: Int
    let fact_key: String
    let category: String
    let value_data: [String: HealthReportJSONValue]
    let is_safety_critical: Bool
    let confirmation_method: String
    let version: Int
    let confirmed_at: String?
    let updated_at: String
    let sources: [HealthProfileSource]

    var id: Int { fact_id }
    var typedCategory: HealthProfileCategory? { HealthProfileCategory(rawValue: category) }
    var responseState: HealthProfileResponseState? {
        value_data["response_state"]?.stringValue.flatMap(HealthProfileResponseState.init(rawValue:))
    }
}

struct HealthProfileCandidate: Codable, Equatable, Identifiable, Sendable {
    let candidate_id: Int
    let fact_key: String
    let category: String
    let proposed_value: [String: HealthReportJSONValue]
    let is_safety_critical: Bool
    let review_status: String
    let conflict_with_fact_id: Int?
    let confidence: Double?
    let version: Int
    let created_at: String
    let updated_at: String
    let sources: [HealthProfileSource]

    var id: Int { candidate_id }
    var typedCategory: HealthProfileCategory? { HealthProfileCategory(rawValue: category) }
    var isReviewable: Bool {
        canReview(.accept)
    }

    func canReview(_ action: HealthProfileCandidateAction) -> Bool {
        guard review_status == "pending_review" || review_status == "conflict",
              let typedCategory else { return false }
        if action == .reject { return true }
        return typedCategory != .goal
            && typedCategory != .safety
            && !is_safety_critical
    }
}

enum HealthProfileCategory: String, Codable, CaseIterable, Sendable {
    case basic
    case longTermHealth = "long_term_health"
    case safety
    case medication
    case goal

    var title: String {
        switch self {
        case .basic: return "基础资料"
        case .longTermHealth: return "长期健康标签"
        case .safety: return "安全信息"
        case .medication: return "长期用药摘要"
        case .goal: return "健康目标与计划"
        }
    }
}

enum HealthProfileResponseState: String, Codable, CaseIterable, Sendable {
    case value
    case none
    case notApplicable = "not_applicable"
    case preferNotToAnswer = "prefer_not_to_answer"

    var title: String {
        switch self {
        case .value: return "填写内容"
        case .none: return "明确没有"
        case .notApplicable: return "不适用"
        case .preferNotToAnswer: return "暂不回答"
        }
    }
}

enum HealthProfileGoalStatus: String, Codable, CaseIterable, Sendable {
    case active
    case paused
    case completed
    case archived

    var title: String {
        switch self {
        case .active: return "进行中"
        case .paused: return "已暂停"
        case .completed: return "已完成"
        case .archived: return "已归档"
        }
    }
}

enum HealthProfileGoalInputParser {
    static func splitMetrics(_ raw: String) -> [String] {
        raw.components(separatedBy: CharacterSet(charactersIn: "，,、\n"))
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
            .reduce(into: [String]()) { result, metric in
                if !result.contains(metric) { result.append(metric) }
            }
    }

    static func isValidDate(_ raw: String) -> Bool {
        let value = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard value.range(of: #"^\d{4}-\d{2}-\d{2}$"#, options: .regularExpression) != nil else {
            return false
        }
        let formatter = DateFormatter()
        formatter.calendar = Calendar(identifier: .gregorian)
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone(secondsFromGMT: 0)
        formatter.dateFormat = "yyyy-MM-dd"
        formatter.isLenient = false
        return formatter.date(from: value) != nil
    }
}

enum HealthProfileCandidateAction: String, Codable, Sendable {
    case accept
    case reject
}

struct HealthProfileCandidateReviewRequest: Encodable, Equatable, Sendable {
    let subject_user_id: Int
    let client_event_id: String
    let candidate_version: Int
    let action: HealthProfileCandidateAction
}

struct HealthProfileFactUpsertRequest: Encodable, Equatable, Sendable {
    let subject_user_id: Int
    let client_event_id: String
    let fact_key: String
    let category: HealthProfileCategory
    let response_state: HealthProfileResponseState
    let value: HealthReportJSONValue?
    let is_safety_critical: Bool
    let expected_version: Int?
}

struct HealthProfileFactRetractRequest: Encodable, Equatable, Sendable {
    let subject_user_id: Int
    let client_event_id: String
    let expected_version: Int
}

struct HealthProfileFieldDefinition: Identifiable, Equatable, Sendable {
    let key: String
    let category: HealthProfileCategory
    let title: String
    let placeholder: String

    var id: String { key }
    var isSafetyCritical: Bool { category == .safety }
    var showsResponseStatePicker: Bool { category != .longTermHealth }
}

enum HealthProfileFieldCatalog {
    static let editable: [HealthProfileFieldDefinition] = [
        .init(key: "basic.birth_date", category: .basic, title: "出生日期", placeholder: "例如 1985-06-18"),
        .init(key: "basic.sex", category: .basic, title: "性别", placeholder: "按你的意愿填写"),
        .init(key: "basic.height", category: .basic, title: "身高", placeholder: "例如 170 cm"),
        .init(key: "basic.weight", category: .basic, title: "体重", placeholder: "例如 65 kg"),
        .init(key: "basic.blood_type", category: .basic, title: "血型", placeholder: "例如 A 型"),
        .init(key: "basic.region", category: .basic, title: "所在地区", placeholder: "例如 上海"),
        .init(key: "basic.lifestyle", category: .basic, title: "生活方式", placeholder: "例如 久坐、夜班"),
        .init(key: "long_term_health.diagnoses", category: .longTermHealth, title: "已确认慢病", placeholder: "填写医生已经明确诊断、需要长期管理的疾病，例如：高血压、2 型糖尿病"),
        .init(key: "long_term_health.family_history", category: .longTermHealth, title: "家族病史", placeholder: "填写血亲家庭成员曾患的疾病，例如：父亲高血压、母亲高血脂"),
        .init(key: "long_term_health.recent_findings", category: .longTermHealth, title: "长期异常指标", placeholder: "填写多次检查异常或需要长期复查的指标，例如：低密度脂蛋白偏高、尿酸持续升高"),
        .init(key: "long_term_health.risk_factor", category: .longTermHealth, title: "长期风险因素", placeholder: "填写会持续影响健康的生活方式或暴露，例如：长期吸烟、久坐少动"),
        .init(key: "long_term_health.active_concern", category: .longTermHealth, title: "主动关注问题", placeholder: "填写希望持续观察或改善的健康问题，例如：睡眠质量、餐后血糖波动"),
        .init(key: "safety.medication_allergy", category: .safety, title: "药物过敏", placeholder: "例如 青霉素过敏；没有可选择“明确没有”"),
        .init(key: "safety.other_allergy", category: .safety, title: "食物或其他过敏", placeholder: "例如 花生过敏"),
        .init(key: "safety.contraindication", category: .safety, title: "禁忌", placeholder: "填写医生明确告知的禁忌"),
        .init(key: "safety.pregnancy_or_breastfeeding", category: .safety, title: "妊娠或哺乳状态", placeholder: "按当前情况填写"),
        .init(key: "safety.major_surgery", category: .safety, title: "重要手术史", placeholder: "例如 2020 年阑尾切除"),
        .init(key: "safety.important_condition", category: .safety, title: "需特别注意的疾病", placeholder: "填写已确认疾病"),
        .init(key: "safety.clinician_restriction", category: .safety, title: "医生明确限制", placeholder: "例如 避免负重运动")
    ]

    /// `goal.primary` remains only as the server completion requirement key.
    /// Goal mutations use the dedicated multi-record endpoints and never the
    /// fact editor.
    static let goalRequirement = HealthProfileFieldDefinition(
        key: "goal.primary",
        category: .goal,
        title: "健康目标",
        placeholder: "通过多目标列表主动添加"
    )

    static func definitions(for category: HealthProfileCategory) -> [HealthProfileFieldDefinition] {
        editable.filter { $0.category == category }
    }

    static func definition(for key: String) -> HealthProfileFieldDefinition? {
        if key == goalRequirement.key { return goalRequirement }
        return editable.first { $0.key == key }
    }

    static func label(for key: String) -> String {
        definition(for: key)?.title
            ?? key.split(separator: ".").last.map(String.init)
            ?? key
    }
}

enum HealthProfileDisplayFormatter {
    static func value(_ data: [String: HealthReportJSONValue], medicationSummaryOnly: Bool = false) -> String {
        if let state = data["response_state"]?.stringValue,
           state != HealthProfileResponseState.value.rawValue {
            return HealthProfileResponseState(rawValue: state)?.title ?? "状态待确认"
        }
        if let explicit = data["value"] {
            return render(explicit, medicationSummaryOnly: medicationSummaryOnly)
        }
        return render(.object(data), medicationSummaryOnly: medicationSummaryOnly)
    }

    static func source(_ type: String) -> String {
        source(type: type, reference: "")
    }

    static func source(_ item: HealthProfileSource) -> String {
        self.source(type: item.source_type, reference: item.source_ref)
    }

    static func source(type: String, reference: String) -> String {
        switch type {
        case "manual", "user": return "用户填写"
        case "apple_health": return "Apple Health"
        case "device":
            return reference.lowercased().contains("apple") ? "Apple Health" : "设备健康数据"
        case "report", "health_report", "confirmed_observation", "report_observation": return "已确认报告"
        case "medical_record": return "就医记录"
        case "medication": return "用药记录"
        case "health_plan": return "健康计划"
        case "ai_suggestion": return "AI 建议补充"
        default: return "其他来源"
        }
    }

    static func medicationSource(_ source: String) -> String {
        switch source {
        case "prescription": return "已确认处方"
        case "user_added": return "用户添加"
        case "ocr_confirmed": return "识别后确认"
        case "history_confirmed": return "历史用药确认"
        default: return "服务端来源"
        }
    }

    static func timestamp(_ raw: String?) -> String {
        guard let raw, !raw.isEmpty else { return "时间未知" }
        return raw.replacingOccurrences(of: "T", with: " ").prefix(16).description
    }

    private static func render(_ value: HealthReportJSONValue, medicationSummaryOnly: Bool) -> String {
        switch value {
        case .string(let text): return text
        case .number(let number):
            return number.rounded() == number ? String(Int(number)) : String(format: "%.2f", number)
        case .bool(let flag): return flag ? "是" : "否"
        case .null: return "未填写"
        case .array(let values):
            return values.map { render($0, medicationSummaryOnly: medicationSummaryOnly) }
                .filter { !$0.isEmpty }
                .joined(separator: "、")
        case .object(let object):
            let allowedMedicationKeys = Set(["medication_name", "purpose", "started_on", "is_still_taking", "source", "last_confirmed_at"])
            let entries = object.sorted { $0.key < $1.key }.filter {
                $0.key != "response_state" && (!medicationSummaryOnly || allowedMedicationKeys.contains($0.key))
            }
            let rendered = entries.map { key, nested in
                let label = medicationFieldLabel(key)
                return "\(label)：\(render(nested, medicationSummaryOnly: medicationSummaryOnly))"
            }
            return rendered.isEmpty ? "仅在用药记录中查看详情" : rendered.joined(separator: " · ")
        }
    }

    private static func medicationFieldLabel(_ key: String) -> String {
        switch key {
        case "count": return "数量"
        case "medication_name": return "药名"
        case "purpose": return "用途"
        case "started_on": return "开始时间"
        case "is_still_taking": return "仍在服用"
        case "source": return "来源"
        case "last_confirmed_at": return "最近确认"
        case "status": return "状态"
        case "started_at": return "开始时间"
        case "related_metrics": return "关联指标"
        case "occurrence_count": return "出现次数"
        case "latest_value_numeric": return "最近值"
        case "canonical_name": return "项目"
        default: return key.replacingOccurrences(of: "_", with: " ")
        }
    }
}

struct HealthProfileDerivedBMI: Equatable, Sendable {
    let value: Double?
    let sourceDescription: String
    let updatedAt: String?

    var valueDescription: String {
        guard let value else { return "待补充" }
        return String(format: "%.1f", value)
    }
}

enum HealthProfileDerivedMetrics {
    static func bodyMassIndex(from facts: [HealthProfileFact]) -> HealthProfileDerivedBMI {
        guard let height = facts.first(where: { $0.fact_key == "basic.height" }),
              let weight = facts.first(where: { $0.fact_key == "basic.weight" }),
              isConfirmed(height),
              isConfirmed(weight),
              height.responseState == .value,
              weight.responseState == .value,
              let heightCM = confirmedMeasurement(from: height, kind: .height),
              let weightKG = confirmedMeasurement(from: weight, kind: .weight) else {
            return HealthProfileDerivedBMI(
                value: nil,
                sourceDescription: "需要已确认且带单位的身高与体重；无法安全解析时不会猜测。",
                updatedAt: nil
            )
        }
        let value = weightKG / pow(heightCM / 100, 2)
        guard value.isFinite, (8...80).contains(value) else {
            return HealthProfileDerivedBMI(
                value: nil,
                sourceDescription: "身高或体重超出可安全派生范围，请先核对原始事实。",
                updatedAt: max(height.updated_at, weight.updated_at)
            )
        }
        let heightSources = sourceLabels(height.sources)
        let weightSources = sourceLabels(weight.sources)
        return HealthProfileDerivedBMI(
            value: value,
            sourceDescription: "由已确认身高（\(heightSources)）与体重（\(weightSources)）透明计算，不是用户单独填写项。",
            updatedAt: max(height.updated_at, weight.updated_at)
        )
    }

    private enum MeasurementKind { case height, weight }

    private static func isConfirmed(_ fact: HealthProfileFact) -> Bool {
        ["user", "clinician", "verified_source"].contains(fact.confirmation_method)
    }

    private static func confirmedMeasurement(
        from fact: HealthProfileFact,
        kind: MeasurementKind
    ) -> Double? {
        guard let value = fact.value_data["value"] else { return nil }
        return parse(value, kind: kind)
    }

    private static func parse(_ value: HealthReportJSONValue, kind: MeasurementKind) -> Double? {
        switch value {
        case .string(let raw): return parse(raw, kind: kind)
        case .object(let object):
            let directKey = kind == .height ? "height_cm" : "weight_kg"
            if case .number(let direct)? = object[directKey] {
                return validated(direct, kind: kind)
            }
            if let nested = object["value"] {
                if case .number(let number) = nested,
                   let unit = object["unit"]?.stringValue {
                    return parse("\(number) \(unit)", kind: kind)
                }
                return parse(nested, kind: kind)
            }
            return nil
        default:
            return nil
        }
    }

    private static func parse(_ raw: String, kind: MeasurementKind) -> Double? {
        let normalized = raw.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard let range = normalized.range(of: #"\d+(?:\.\d+)?"#, options: .regularExpression),
              let number = Double(normalized[range]) else { return nil }
        let converted: Double?
        switch kind {
        case .height:
            if normalized.contains("cm") || normalized.contains("厘米") || normalized.contains("公分") {
                converted = number
            } else if normalized.contains("米") || normalized.hasSuffix("m") {
                converted = number * 100
            } else {
                converted = nil
            }
        case .weight:
            if normalized.contains("kg") || normalized.contains("千克") || normalized.contains("公斤") {
                converted = number
            } else if normalized.contains("克") || normalized.hasSuffix("g") {
                converted = number / 1000
            } else {
                converted = nil
            }
        }
        return converted.flatMap { validated($0, kind: kind) }
    }

    private static func validated(_ value: Double, kind: MeasurementKind) -> Double? {
        switch kind {
        case .height: return (80...250).contains(value) ? value : nil
        case .weight: return (20...400).contains(value) ? value : nil
        }
    }

    private static func sourceLabels(_ sources: [HealthProfileSource]) -> String {
        let labels = sources.map { HealthProfileDisplayFormatter.source($0) }.reduce(into: [String]()) { result, label in
            if !result.contains(label) { result.append(label) }
        }
        return labels.isEmpty ? "来源明细待服务端补充" : labels.joined(separator: "、")
    }
}
