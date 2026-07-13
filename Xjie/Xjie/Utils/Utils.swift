import Foundation

/// PERF-01: 缓存的日期格式化器（static let 只初始化一次）
private let cachedISOFractional: ISO8601DateFormatter = {
    let f = ISO8601DateFormatter()
    f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    return f
}()

private let cachedISOBasic = ISO8601DateFormatter()

private let cachedDateTimeFmt: DateFormatter = {
    let f = DateFormatter()
    f.dateFormat = "yyyy-MM-dd HH:mm"
    f.locale = Locale(identifier: "zh_CN")
    return f
}()

private let cachedTimeFmt: DateFormatter = {
    let f = DateFormatter()
    f.dateFormat = "HH:mm"
    return f
}()

/// 工具函数
enum Utils {
    /// 将 ISO8601 字符串解析为 Date
    static func parseISO(_ dateStr: String) -> Date? {
        cachedISOFractional.date(from: dateStr) ?? cachedISOBasic.date(from: dateStr)
    }

    /// 格式化日期为 YYYY-MM-DD HH:mm
    static func formatDate(_ dateStr: String?) -> String {
        guard let dateStr, !dateStr.isEmpty else { return "" }
        guard let date = parseISO(dateStr) else { return dateStr }
        return cachedDateTimeFmt.string(from: date)
    }

    /// 格式化时间为 HH:mm
    static func formatTime(_ dateStr: String?) -> String {
        guard let dateStr, !dateStr.isEmpty else { return "" }
        guard let date = parseISO(dateStr) else { return dateStr }
        return cachedTimeFmt.string(from: date)
    }

    /// 保留 n 位小数
    static func toFixed(_ num: Double?, n: Int = 1) -> String {
        guard let num, !num.isNaN else { return "--" }
        return String(format: "%.\(n)f", num)
    }

    /// 血糖范围着色
    static func glucoseColor(_ val: Double?) -> GlucoseLevel {
        guard let val else { return .normal }
        if val < 70 { return .low }
        if val > 180 { return .high }
        return .normal
    }

    /// 对标准 11 位手机号脱敏；异常值不回显，避免意外暴露账号信息。
    static func maskedPhone(_ phone: String?) -> String {
        guard let phone, phone.count == 11, phone.allSatisfy(\.isNumber) else {
            return "暂未获取"
        }
        return "\(phone.prefix(3))****\(phone.suffix(4))"
    }

    enum GlucoseLevel {
        case low, normal, high
    }
}

/// SEC-04: 安全构建带查询参数的 URL 路径
enum URLBuilder {
    static func path(_ basePath: String, queryItems: [URLQueryItem]) -> String {
        guard !queryItems.isEmpty else { return basePath }
        var components = URLComponents()
        components.path = basePath
        components.queryItems = queryItems
        if let query = components.percentEncodedQuery {
            return basePath + "?" + query
        }
        return basePath
    }
}
