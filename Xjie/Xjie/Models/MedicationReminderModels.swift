import Foundation

enum MedicationReminderCadence: String, Codable, CaseIterable, Sendable {
    case daily
    case everyOtherDay = "every_other_day"

    var title: String {
        switch self {
        case .daily: return "每日"
        case .everyOtherDay: return "隔日"
        }
    }
}

enum MedicationReminderPermissionState: String, Codable, Equatable, Sendable {
    case unknown
    case notDetermined = "not_determined"
    case allowed
    case denied
    case unavailable

    var title: String {
        switch self {
        case .unknown: return "正在检查通知权限"
        case .notDetermined: return "开启提醒时将请求通知权限"
        case .allowed: return "通知权限已开启"
        case .denied: return "通知权限已关闭"
        case .unavailable: return "当前环境不能使用系统通知"
        }
    }
}

struct MedicationReminderSettings: Identifiable, Codable, Equatable, Sendable {
    let planID: Int
    let subjectUserID: Int
    var planVersion: Int
    var enabled: Bool
    var cadence: MedicationReminderCadence
    var times: [String]
    var advanceMinutes: Int
    var snoozeMinutes: Int
    var soundEnabled: Bool
    var showMedicationNameOnLockScreen: Bool
    var mealRelation: MedicationMealRelation
    var courseEnd: String?
    var cadenceAnchorDate: String
    var timezoneIdentifier: String
    var updatedAt: String

    var id: Int { planID }

    static func defaultValue(
        for plan: TrustedMedicationPlan,
        localDate: String,
        timezoneIdentifier: String
    ) -> Self {
        Self(
            planID: plan.plan_id,
            subjectUserID: plan.subject_user_id,
            planVersion: plan.version,
            enabled: false,
            cadence: .daily,
            times: plan.schedule_times,
            advanceMinutes: 0,
            snoozeMinutes: 15,
            soundEnabled: true,
            showMedicationNameOnLockScreen: false,
            mealRelation: plan.meal_relation,
            courseEnd: plan.course_end,
            cadenceAnchorDate: localDate,
            timezoneIdentifier: timezoneIdentifier,
            updatedAt: timestamp(Date())
        )
    }

    private static func timestamp(_ date: Date) -> String {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter.string(from: date)
    }
}

struct MedicationReminderOccurrence: Identifiable, Equatable, Sendable {
    let id: String
    let planID: Int
    let subjectUserID: Int
    let planVersion: Int
    let fireDate: Date
    let scheduledTime: String
}

struct MedicationReminderReconcileResult: Equatable, Sendable {
    let permission: MedicationReminderPermissionState
    let scheduledCount: Int
    let detail: String?
}

enum MedicationReminderPolicy {
    static let pendingRequestLimit = 60
    static let schedulingHorizonDays = 45
    static let allowedAdvanceMinutes = [0, 5, 10, 15, 30, 60]
    static let allowedSnoozeMinutes = [5, 10, 15, 30, 60]

    static func ordinaryRequestBudget(preservedSnoozeCount: Int) -> Int {
        max(0, pendingRequestLimit - max(0, preservedSnoozeCount))
    }

    static func isVersionCompatible(
        _ settings: MedicationReminderSettings,
        with plan: TrustedMedicationPlan
    ) -> Bool {
        settings.subjectUserID == plan.subject_user_id
            && settings.planID == plan.plan_id
            && settings.planVersion == plan.version
            && plan.status == .active
    }

    static func validationIssue(
        for settings: MedicationReminderSettings,
        plan: TrustedMedicationPlan
    ) -> String? {
        guard settings.subjectUserID == plan.subject_user_id,
              settings.planID == plan.plan_id else {
            return "提醒设置与当前用药主体不一致，请重新打开页面。"
        }
        guard settings.planVersion == plan.version else {
            return "用药计划已更新，请按新版本重新确认提醒设置。"
        }
        guard allowedAdvanceMinutes.contains(settings.advanceMinutes),
              allowedSnoozeMinutes.contains(settings.snoozeMinutes) else {
            return "提醒提前量或稍后间隔不在允许范围。"
        }
        guard !settings.cadenceAnchorDate.isEmpty,
              dayComponents(settings.cadenceAnchorDate) != nil else {
            return "隔日提醒的起算日期无效。"
        }
        if let courseEnd = settings.courseEnd,
           dayComponents(courseEnd) == nil {
            return "疗程结束日期无效。"
        }
        if settings.enabled {
            guard plan.status == .active else { return "只有服用中的计划可以开启提醒。" }
            guard !settings.times.isEmpty else { return "请先设置至少一个服药时间。" }
            guard settings.times.count <= 24,
                  settings.times.allSatisfy(isValidTime) else {
                return "服药时间必须是 00:00–23:59 的 HH:mm 格式。"
            }
        }
        return nil
    }

    static func occurrences(
        settings: MedicationReminderSettings,
        plan: TrustedMedicationPlan,
        now: Date,
        currentTimezone: TimeZone
    ) -> [MedicationReminderOccurrence] {
        guard settings.enabled,
              isVersionCompatible(settings, with: plan),
              validationIssue(for: settings, plan: plan) == nil else { return [] }

        var calendar = Calendar(identifier: .gregorian)
        calendar.locale = Locale(identifier: "en_US_POSIX")
        calendar.timeZone = currentTimezone
        let today = calendar.startOfDay(for: now)
        let courseStart = plan.course_start.flatMap { date($0, calendar: calendar) }
        let start = max(today, courseStart ?? today)
        let horizon = calendar.date(byAdding: .day, value: schedulingHorizonDays, to: start) ?? start
        let courseEnd = settings.courseEnd.flatMap { date($0, calendar: calendar) }
        let end = min(courseEnd ?? horizon, horizon)
        guard start <= end,
              let anchor = date(settings.cadenceAnchorDate, calendar: calendar) else { return [] }

        let normalizedTimes = Array(Set(settings.times.filter(isValidTime))).sorted()
        var result: [MedicationReminderOccurrence] = []
        var day = start
        while day <= end {
            let dayDistance = calendar.dateComponents([.day], from: anchor, to: day).day ?? 0
            let shouldSchedule = settings.cadence == .daily || positiveModulo(dayDistance, 2) == 0
            if shouldSchedule {
                for time in normalizedTimes {
                    guard let parts = timeComponents(time),
                          let scheduled = calendar.date(
                            bySettingHour: parts.hour,
                            minute: parts.minute,
                            second: 0,
                            of: day
                          ),
                          let fireDate = calendar.date(
                            byAdding: .minute,
                            value: -settings.advanceMinutes,
                            to: scheduled
                          ),
                          fireDate > now else { continue }
                    let dayKey = localDay(fireDate, calendar: calendar)
                    let timeKey = time.replacingOccurrences(of: ":", with: "")
                    result.append(
                        MedicationReminderOccurrence(
                            id: "trusted.med.schedule.\(settings.subjectUserID).\(settings.planID).v\(settings.planVersion).\(dayKey).\(timeKey).a\(settings.advanceMinutes)",
                            planID: settings.planID,
                            subjectUserID: settings.subjectUserID,
                            planVersion: settings.planVersion,
                            fireDate: fireDate,
                            scheduledTime: time
                        )
                    )
                }
            }
            guard let next = calendar.date(byAdding: .day, value: 1, to: day) else { break }
            day = next
        }
        return result.sorted { $0.fireDate < $1.fireDate }
    }

    /// One pending snooze exists per trusted occurrence. Repeated snoozes and
    /// corrections intentionally reuse this identifier so iOS replaces the old
    /// request instead of accumulating multiple alerts for the same dose.
    static func snoozeIdentifier(
        task: MedicationTodayTask,
        plan: TrustedMedicationPlan
    ) -> String {
        let day = task.scheduled_local_date.replacingOccurrences(of: "-", with: "")
        let time = task.scheduled_time.replacingOccurrences(of: ":", with: "")
        return "trusted.med.snooze.\(plan.subject_user_id).\(plan.plan_id).v\(plan.version).\(day).\(time)"
    }

    static func normalizedTimes(_ raw: String) -> [String] {
        raw.components(separatedBy: CharacterSet(charactersIn: "、,，;； \n\t"))
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
            .reduce(into: [String]()) { result, value in
                if !result.contains(value) { result.append(value) }
            }
            .sorted()
    }

    static func isValidTime(_ value: String) -> Bool {
        timeComponents(value) != nil
    }

    private static func timeComponents(_ value: String) -> (hour: Int, minute: Int)? {
        let pieces = value.split(separator: ":", omittingEmptySubsequences: false)
        guard pieces.count == 2,
              pieces[0].count == 2,
              pieces[1].count == 2,
              let hour = Int(pieces[0]),
              let minute = Int(pieces[1]),
              (0...23).contains(hour),
              (0...59).contains(minute) else { return nil }
        return (hour, minute)
    }

    private static func dayComponents(_ value: String) -> DateComponents? {
        let pieces = value.split(separator: "-", omittingEmptySubsequences: false)
        guard pieces.count == 3,
              pieces[0].count == 4,
              pieces[1].count == 2,
              pieces[2].count == 2,
              let year = Int(pieces[0]),
              let month = Int(pieces[1]),
              let day = Int(pieces[2]),
              (1...12).contains(month),
              (1...31).contains(day) else { return nil }
        return DateComponents(year: year, month: month, day: day)
    }

    private static func date(_ value: String, calendar: Calendar) -> Date? {
        guard let components = dayComponents(value),
              let date = calendar.date(from: components),
              calendar.dateComponents([.year, .month, .day], from: date) == components else {
            return nil
        }
        return date
    }

    private static func localDay(_ date: Date, calendar: Calendar) -> String {
        let parts = calendar.dateComponents([.year, .month, .day], from: date)
        return String(format: "%04d%02d%02d", parts.year ?? 0, parts.month ?? 0, parts.day ?? 0)
    }

    private static func positiveModulo(_ value: Int, _ divisor: Int) -> Int {
        let remainder = value % divisor
        return remainder >= 0 ? remainder : remainder + divisor
    }
}

struct MedicationConfirmationMetric: Equatable, Sendable {
    let confirmedCount: Int
    let plannedCount: Int
    let unavailableReason: String?

    var isAvailable: Bool { unavailableReason == nil }
    var percentage: Int? {
        guard isAvailable, plannedCount > 0 else { return nil }
        return Int((Double(confirmedCount) / Double(plannedCount) * 100).rounded())
    }

    static func unavailable(_ reason: String) -> Self {
        Self(confirmedCount: 0, plannedCount: 0, unavailableReason: reason)
    }
}

struct MedicationConfirmationInsights: Equatable, Sendable {
    let today: MedicationConfirmationMetric
    let sevenDay: MedicationConfirmationMetric
    let courseByPlanID: [Int: MedicationConfirmationMetric]

    static let unavailable = Self(
        today: .unavailable("今日可信任务尚未加载。"),
        sevenDay: .unavailable("近七日可信任务尚未加载。"),
        courseByPlanID: [:]
    )
}

enum MedicationConfirmationPolicy {
    static func metric(
        summaries: [MedicationTodaySummary],
        planID: Int? = nil
    ) -> MedicationConfirmationMetric {
        let tasks = summaries.flatMap(\.tasks).filter { task in
            planID == nil || task.plan_id == planID
        }
        let confirmed = tasks.filter { $0.status == .taken || $0.status == .skipped }.count
        return MedicationConfirmationMetric(
            confirmedCount: confirmed,
            plannedCount: tasks.count,
            unavailableReason: nil
        )
    }

    static func sevenDay(
        summaries: [MedicationTodaySummary],
        expectedLocalDates: [String]
    ) -> MedicationConfirmationMetric {
        let actual = Set(summaries.map(\.local_date))
        guard actual == Set(expectedLocalDates), summaries.count == expectedLocalDates.count else {
            return .unavailable("近七日数据没有完整返回，本页不会用局部数据计算已确认率。")
        }
        return metric(summaries: summaries)
    }

    static func course(
        plan: TrustedMedicationPlan,
        summaries: [MedicationTodaySummary],
        through localDate: String
    ) -> MedicationConfirmationMetric {
        guard let start = plan.course_start else {
            return .unavailable("计划没有疗程开始日期，无法确定完整统计窗口。")
        }
        let end = min(plan.course_end ?? localDate, localDate)
        let expected = MedicationDateWindow.inclusiveDates(from: start, through: end)
        guard !expected.isEmpty,
              Set(summaries.map(\.local_date)).isSuperset(of: Set(expected)) else {
            return .unavailable("服务端尚未提供这项计划的完整疗程历史；本页不把近七日数据冒充全疗程统计。")
        }
        return metric(
            summaries: summaries.filter { Set(expected).contains($0.local_date) },
            planID: plan.plan_id
        )
    }
}

struct MedicationCourseProgress: Equatable, Sendable {
    let elapsedDays: Int?
    let totalDays: Int?
    let remainingDays: Int?
    let endsSoon: Bool
}

enum MedicationCoursePolicy {
    static func progress(plan: TrustedMedicationPlan, on localDate: String) -> MedicationCourseProgress {
        guard let start = plan.course_start else {
            return MedicationCourseProgress(
                elapsedDays: nil,
                totalDays: nil,
                remainingDays: nil,
                endsSoon: false
            )
        }
        let elapsedDates = MedicationDateWindow.inclusiveDates(from: start, through: localDate)
        let totalDates = plan.course_end.map {
            MedicationDateWindow.inclusiveDates(from: start, through: $0)
        }
        let remaining = plan.course_end.flatMap { end -> Int? in
            let dates = MedicationDateWindow.inclusiveDates(from: localDate, through: end)
            guard !dates.isEmpty else { return 0 }
            return max(0, dates.count - 1)
        }
        return MedicationCourseProgress(
            elapsedDays: elapsedDates.isEmpty ? nil : elapsedDates.count,
            totalDays: totalDates?.count,
            remainingDays: remaining,
            endsSoon: remaining.map { (0...7).contains($0) } ?? false
        )
    }
}

enum MedicationDateWindow {
    static func recentDates(ending localDate: String, count: Int) -> [String] {
        guard count > 0, let end = parse(localDate) else { return [] }
        let calendarValue = calendar
        return (0..<count).reversed().compactMap { offset in
            calendarValue.date(byAdding: .day, value: -offset, to: end).map(format)
        }
    }

    static func inclusiveDates(from start: String, through end: String) -> [String] {
        guard let startDate = parse(start), let endDate = parse(end), startDate <= endDate else { return [] }
        let calendarValue = calendar
        guard let distance = calendarValue.dateComponents([.day], from: startDate, to: endDate).day,
              (0...3660).contains(distance) else {
            return []
        }
        return (0...distance).compactMap { offset in
            calendarValue.date(byAdding: .day, value: offset, to: startDate).map(format)
        }
    }

    private static var calendar: Calendar {
        var value = Calendar(identifier: .gregorian)
        value.locale = Locale(identifier: "en_US_POSIX")
        value.timeZone = TimeZone(secondsFromGMT: 0) ?? .current
        return value
    }

    private static func parse(_ value: String) -> Date? {
        let formatter = DateFormatter()
        formatter.calendar = calendar
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = calendar.timeZone
        formatter.dateFormat = "yyyy-MM-dd"
        formatter.isLenient = false
        return formatter.date(from: value)
    }

    private static func format(_ date: Date) -> String {
        let formatter = DateFormatter()
        formatter.calendar = calendar
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = calendar.timeZone
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter.string(from: date)
    }
}

enum MedicationQuickFill {
    static let dosePhrases = ["半片", "1片", "2片", "5毫升"]
    static let frequencyPhrases = ["每日1次", "每日2次", "每日3次", "隔日1次"]
    static let instructionPhrases = ["饭前", "饭后", "随餐", "睡前", "遵医嘱"]

    static func appending(_ phrase: String, to existing: String) -> String {
        let current = existing.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !phrase.isEmpty else { return current }
        guard !current.isEmpty else { return phrase }
        guard !current.contains(phrase) else { return current }
        return "\(current)；\(phrase)"
    }
}
