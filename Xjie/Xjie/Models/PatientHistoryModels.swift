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
        .init(key: "abnormal_findings", label: "近一年重要异常检查", placeholder: "如：HbA1c 7.6%、肝脏脂肪变性"),
        .init(key: "current_focus", label: "本次就诊重点关注", placeholder: "如：希望医生关注血糖波动与餐后血糖"),
        .init(key: "family_history", label: "家族史", placeholder: "如：父亲糖尿病、母亲高血压"),
        .init(key: "lifestyle_risks", label: "生活方式风险因素", placeholder: "如：久坐、夜班、吸烟史 10 年")
    ]

    static func label(forKey key: String) -> String {
        all.first(where: { $0.key == key })?.label ?? key
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
