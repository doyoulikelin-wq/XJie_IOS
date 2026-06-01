import Foundation

// MARK: - 情绪 5 时段打卡（C4）

enum MoodSegment: String, Codable, CaseIterable, Identifiable {
    case morning, noon, afternoon, evening, night

    var id: String { rawValue }

    var label: String {
        switch self {
        case .morning:   return "早晨"
        case .noon:      return "中午"
        case .afternoon: return "下午"
        case .evening:   return "傍晚"
        case .night:     return "夜间"
        }
    }

    /// 24 小时窗口（与后端 SEGMENT_WINDOWS 保持一致），用于显示
    var window: String {
        switch self {
        case .morning:   return "06–10"
        case .noon:      return "10–14"
        case .afternoon: return "14–17"
        case .evening:   return "17–21"
        case .night:     return "21–02"
        }
    }
}

/// 5 级情绪：1=愤怒 2=低落 3=焦虑 4=平静 5=愉快
enum MoodLevel: Int, Codable, CaseIterable, Identifiable {
    case angry = 1, sad = 2, anxious = 3, neutral = 4, happy = 5

    var id: Int { rawValue }

    var emoji: String {
        switch self {
        case .angry:   return "怒"
        case .sad:     return "低"
        case .anxious: return "焦"
        case .neutral: return "平"
        case .happy:   return "悦"
        }
    }

    var label: String {
        switch self {
        case .angry:   return "愤怒"
        case .sad:     return "低落"
        case .anxious: return "焦虑"
        case .neutral: return "平静"
        case .happy:   return "愉快"
        }
    }
}

struct MoodLogIn: Codable {
    let ts: String           // ISO-8601
    let segment: String
    let mood_level: Int
    let note: String?
}

struct MoodLogOut: Codable, Identifiable {
    let id: Int
    let ts: String
    let ts_date: String
    let segment: String
    let mood_level: Int
    let note: String?
}

struct MoodDay: Codable, Identifiable {
    let date: String
    let morning: Int?
    let noon: Int?
    let afternoon: Int?
    let evening: Int?
    let night: Int?
    let avg: Double?

    var id: String { date }

    func level(for segment: MoodSegment) -> Int? {
        switch segment {
        case .morning:   return morning
        case .noon:      return noon
        case .afternoon: return afternoon
        case .evening:   return evening
        case .night:     return night
        }
    }
}

struct MoodGlucoseCorrelation: Codable {
    let days: Int
    let paired_samples: Int
    let pearson_r: Double?
    let p_value: Double?
    let interpretation: String
}
