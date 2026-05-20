import Foundation

// MARK: - 老年人关怀模式

/// 单条主动询问签到记录
struct ElderlyCheckin: Decodable, Identifiable {
    let id: Int
    let activity: String?
    let body_feeling: String?
    let mood: String?
    let note: String?
    let source: String
    let created_at: Date
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
}

/// 创建签到的请求体
struct ElderlyCheckinBody: Encodable {
    let activity: String?
    let body_feeling: String?
    let mood: String?
    let note: String?
    let source: String?
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
