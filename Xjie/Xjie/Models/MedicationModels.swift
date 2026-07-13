import Foundation

/// 用药记录数据模型 — 与后端 `/api/medications` 对齐。
struct Medication: Identifiable, Codable, Equatable {
    let id: Int
    var name: String
    var dosage: String?
    var frequency: String?
    var instructions: String?
    var schedule_times: [String]
    var course_start: String?   // YYYY-MM-DD
    var course_end: String?     // YYYY-MM-DD
    var photo_url: String?
    var enabled: Bool
    let created_at: String
    let updated_at: String

    /// 课程窗口是否当前激活
    func isCourseActive(on date: Date = Date()) -> Bool {
        let df = DateFormatter()
        df.dateFormat = "yyyy-MM-dd"
        df.timeZone = .current
        let today = df.string(from: date)
        if let s = course_start, today < s { return false }
        if let e = course_end,   today > e { return false }
        return true
    }
}

struct MedicationListResponse: Codable {
    let items: [Medication]
}

struct MedicationBody: Encodable {
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

struct MedicationRecognizeBody: Encodable {
    let raw_text: String
}

struct MedicationRecognizeResult: Codable {
    let name: String?
    let dosage: String?
    let frequency: String?
    let instructions: String?
    let schedule_times: [String]
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
