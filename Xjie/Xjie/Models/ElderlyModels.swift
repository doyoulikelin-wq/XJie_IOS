import Foundation

// MARK: - 老年人关怀模式

/// 兼容 FastAPI ISO8601（含/不含微秒、含/不含 Z）的日期解析。
private enum ElderlyDate {
    private static let isoFull: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()
    private static let isoBasic: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        return f
    }()
    static func parse(_ s: String) -> Date? {
        // 后端可能返回 "2026-05-20T12:09:55.197752Z" 或不含 Z 的形式
        var str = s
        if !str.hasSuffix("Z") && !str.contains("+") && !str.contains("-") {
            str += "Z"
        }
        return isoFull.date(from: str) ?? isoBasic.date(from: str)
    }
}

/// 单条主动询问签到记录
struct ElderlyCheckin: Decodable, Identifiable {
    let id: Int
    let activity: String?
    let body_feeling: String?
    let mood: String?
    let note: String?
    let source: String
    let prompt_type: String
    let created_at: Date

    enum CodingKeys: String, CodingKey {
        case id, activity, body_feeling, mood, note, source, prompt_type, created_at
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        self.id = try c.decode(Int.self, forKey: .id)
        self.activity = try c.decodeIfPresent(String.self, forKey: .activity)
        self.body_feeling = try c.decodeIfPresent(String.self, forKey: .body_feeling)
        self.mood = try c.decodeIfPresent(String.self, forKey: .mood)
        self.note = try c.decodeIfPresent(String.self, forKey: .note)
        self.source = try c.decodeIfPresent(String.self, forKey: .source) ?? "auto_prompt"
        self.prompt_type = try c.decodeIfPresent(String.self, forKey: .prompt_type) ?? "combined"
        let raw = try c.decode(String.self, forKey: .created_at)
        self.created_at = ElderlyDate.parse(raw) ?? Date()
    }
}

struct ElderlyCheckinList: Decodable {
    let items: [ElderlyCheckin]
}

/// `/api/elderly/today` 响应：是否需要弹出主动询问
struct ElderlyTodayStatus: Decodable {
    let enabled: Bool
    let interval_min: Int
    let last_checkin_at: Date?
    let minutes_since_last: Int?
    let should_prompt: Bool
    let today_count: Int

    enum CodingKeys: String, CodingKey {
        case enabled, interval_min, last_checkin_at, minutes_since_last, should_prompt, today_count
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        self.enabled = try c.decodeIfPresent(Bool.self, forKey: .enabled) ?? false
        self.interval_min = try c.decodeIfPresent(Int.self, forKey: .interval_min) ?? 180
        if let s = try c.decodeIfPresent(String.self, forKey: .last_checkin_at) {
            self.last_checkin_at = ElderlyDate.parse(s)
        } else {
            self.last_checkin_at = nil
        }
        self.minutes_since_last = try c.decodeIfPresent(Int.self, forKey: .minutes_since_last)
        self.should_prompt = try c.decodeIfPresent(Bool.self, forKey: .should_prompt) ?? false
        self.today_count = try c.decodeIfPresent(Int.self, forKey: .today_count) ?? 0
    }
}

/// 创建签到的请求体
struct ElderlyCheckinBody: Encodable {
    let activity: String?
    let body_feeling: String?
    let mood: String?
    let note: String?
    let source: String?
    let prompt_type: String?
}

// MARK: - 选项枚举

enum BodyFeeling: String, CaseIterable, Identifiable {
    case great, good, ok, uncomfortable, bad
    var id: String { rawValue }
    var emoji: String {
        switch self {
        case .great: return "💪"
        case .good: return "🙂"
        case .ok: return "😐"
        case .uncomfortable: return "🤕"
        case .bad: return "🤒"
        }
    }
    var label: String {
        switch self {
        case .great: return "很棒"
        case .good: return "良好"
        case .ok: return "一般"
        case .uncomfortable: return "不舒服"
        case .bad: return "很差"
        }
    }
}

enum MoodChoice: String, CaseIterable, Identifiable {
    case happy, calm, anxious, sad, angry
    var id: String { rawValue }
    var emoji: String {
        switch self {
        case .happy: return "😄"
        case .calm: return "😌"
        case .anxious: return "😟"
        case .sad: return "😢"
        case .angry: return "😠"
        }
    }
    var label: String {
        switch self {
        case .happy: return "开心"
        case .calm: return "平静"
        case .anxious: return "焦虑"
        case .sad: return "难过"
        case .angry: return "生气"
        }
    }
}

/// 常见日常活动快捷选项
enum CommonActivity: String, CaseIterable, Identifiable {
    case rest = "休息"
    case walk = "散步"
    case meal = "用餐"
    case chat = "聊天"
    case tv = "看电视"
    case housework = "做家务"
    case exercise = "锻炼"
    case sleep = "睡觉"
    var id: String { rawValue }
}
