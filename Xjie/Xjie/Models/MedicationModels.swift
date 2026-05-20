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
