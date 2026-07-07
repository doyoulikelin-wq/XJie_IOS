import Foundation
import UserNotifications

/// 集中管理本地通知（用药定时 / 关怀模式定时 / 血糖异常由后端 APNs）。
///
/// - 用药提醒：根据 `Medication.schedule_times`（HH:MM）按天循环；
/// - 关怀模式：根据 `UserSettings.elderly_interval_min` 周期触发；
/// - 血糖异常：依赖后端推送（APNs HTTP/2），客户端只需保证权限 + token。
@MainActor
final class NotificationScheduler {
    static let shared = NotificationScheduler()
    private init() {}

    /// 通知 identifier 前缀，便于按类型清理
    private enum Prefix {
        static let medication = "med."
        static let elderly = "elderly."
        static let reportRecognition = "report.recognition."
    }

    // MARK: - 权限

    func ensurePermission() async -> Bool {
        let center = UNUserNotificationCenter.current()
        let status = (try? await center.notificationSettings()).map(\.authorizationStatus) ?? .notDetermined
        switch status {
        case .authorized, .provisional, .ephemeral: return true
        case .denied: return false
        case .notDetermined:
            return (try? await center.requestAuthorization(options: [.alert, .sound, .badge])) ?? false
        @unknown default: return false
        }
    }

    // MARK: - 用药提醒

    /// 重新调度所有用药提醒：清除旧的，按当前列表重新注册。
    func rescheduleAll(medications: [Medication]) async {
        guard await ensurePermission() else { return }
        let center = UNUserNotificationCenter.current()
        let existing = await center.pendingNotificationRequests()
        let toRemove = existing.map(\.identifier).filter { $0.hasPrefix(Prefix.medication) }
        center.removePendingNotificationRequests(withIdentifiers: toRemove)

        let today = Date()
        for m in medications where m.enabled && m.isCourseActive(on: today) {
            for (idx, t) in m.schedule_times.enumerated() {
                let parts = t.split(separator: ":").compactMap { Int($0) }
                guard parts.count == 2 else { continue }
                var comp = DateComponents()
                comp.hour = parts[0]
                comp.minute = parts[1]
                let trigger = UNCalendarNotificationTrigger(dateMatching: comp, repeats: true)
                let content = UNMutableNotificationContent()
                content.title = "用药提醒"
                let dose = (m.dosage?.isEmpty == false) ? "（\(m.dosage!)）" : ""
                content.body = "该服用 \(m.name)\(dose) 了"
                content.sound = .default
                content.userInfo = ["type": "medication", "medication_id": m.id]
                let id = "\(Prefix.medication)\(m.id).\(idx)"
                let req = UNNotificationRequest(identifier: id, content: content, trigger: trigger)
                try? await center.add(req)
            }
        }
    }

    // MARK: - 报告识别

    func scheduleReportRecognitionComplete(fileName: String?) async {
        guard await ensurePermission() else { return }
        let content = UNMutableNotificationContent()
        content.title = "报告识别完成"
        content.body = "小捷已完成一份健康资料识别，可返回报告页查看摘要和入库结果。"
        content.sound = .default
        content.userInfo = [
            "type": "report_recognition_complete",
            "file_name": fileName ?? ""
        ]
        let trigger = UNTimeIntervalNotificationTrigger(timeInterval: 1, repeats: false)
        let id = "\(Prefix.reportRecognition)\(UUID().uuidString)"
        let req = UNNotificationRequest(identifier: id, content: content, trigger: trigger)
        try? await UNUserNotificationCenter.current().add(req)
    }

    // MARK: - 关怀模式定时

    /// 按 `intervalMinutes` 调度白天 (8:00-22:00) 的关怀提醒。
    /// 传 `intervalMinutes=0` 表示关闭。
    func scheduleElderlyReminders(intervalMinutes: Int, enabled: Bool) async {
        let center = UNUserNotificationCenter.current()
        let existing = await center.pendingNotificationRequests()
        let toRemove = existing.map(\.identifier).filter { $0.hasPrefix(Prefix.elderly) }
        center.removePendingNotificationRequests(withIdentifiers: toRemove)

        guard enabled, intervalMinutes > 0 else { return }
        guard await ensurePermission() else { return }

        // 按 8:00 起、22:00 止，按 intervalMinutes 摆点；每个点一个 daily 循环 trigger。
        let cal = Calendar.current
        var minutesOfDay = 8 * 60
        let end = 22 * 60
        var idx = 0
        while minutesOfDay <= end {
            var comp = DateComponents()
            comp.hour = minutesOfDay / 60
            comp.minute = minutesOfDay % 60
            _ = cal // silence unused
            let trigger = UNCalendarNotificationTrigger(dateMatching: comp, repeats: true)
            let content = UNMutableNotificationContent()
            content.title = "关怀复查"
            content.body = "现在感觉怎么样？打开小捷打个卡吧。"
            content.sound = .default
            content.userInfo = ["type": "elderly_checkin"]
            let id = "\(Prefix.elderly)\(idx)"
            let req = UNNotificationRequest(identifier: id, content: content, trigger: trigger)
            try? await center.add(req)
            minutesOfDay += intervalMinutes
            idx += 1
            if idx > 32 { break }
        }
    }

    // MARK: - 诊断 / 自检

    /// 立即弹一条本地通知，用于验证权限/通道是否生效。
    func fireTestNotification() async {
        let granted = await ensurePermission()
        let content = UNMutableNotificationContent()
        content.title = "测试通知"
        content.body = granted
            ? "如果你看到了这条，说明 iOS 通知权限正常。"
            : "权限未开启：请到 设置 → 小捷 → 通知 中允许通知。"
        content.sound = .default
        // 立即触发（1 秒后）；UNCalendarNotificationTrigger 不允许 0 秒
        let trigger = UNTimeIntervalNotificationTrigger(timeInterval: 1, repeats: false)
        let req = UNNotificationRequest(identifier: "test.now.\(UUID().uuidString)",
                                        content: content, trigger: trigger)
        do {
            try await UNUserNotificationCenter.current().add(req)
            AppLogger.auth.info("fireTestNotification queued, granted=\(granted)")
        } catch {
            AppLogger.auth.error("fireTestNotification add failed: \(error.localizedDescription)")
        }
    }

    /// 安排一个 N 秒后的本地通知（前台/后台都应弹出）。
    func scheduleTestAlarm(seconds: Int) async {
        _ = await ensurePermission()
        let content = UNMutableNotificationContent()
        content.title = "测试闹钟"
        content.body = "这是 \(seconds) 秒前安排的本地通知。"
        content.sound = .default
        let trigger = UNTimeIntervalNotificationTrigger(timeInterval: TimeInterval(seconds), repeats: false)
        let req = UNNotificationRequest(identifier: "test.alarm.\(UUID().uuidString)",
                                        content: content, trigger: trigger)
        try? await UNUserNotificationCenter.current().add(req)
    }

    /// 安排一个用户自定义时间的本地通知（一次性）。
    func scheduleCustomAlarm(at date: Date, title: String = "用药提醒", body: String? = nil) async {
        _ = await ensurePermission()
        let interval = date.timeIntervalSinceNow
        guard interval > 0 else { return }
        let content = UNMutableNotificationContent()
        content.title = title
        let f = DateFormatter()
        f.dateFormat = "HH:mm"
        content.body = body ?? "已到 \(f.string(from: date))，请按时服药。"
        content.sound = .default
        let trigger = UNTimeIntervalNotificationTrigger(timeInterval: interval, repeats: false)
        let req = UNNotificationRequest(identifier: "user.alarm.\(UUID().uuidString)",
                                        content: content, trigger: trigger)
        do {
            try await UNUserNotificationCenter.current().add(req)
            AppLogger.auth.info("scheduleCustomAlarm at=\(f.string(from: date)) in \(Int(interval))s")
        } catch {
            AppLogger.auth.error("scheduleCustomAlarm add failed: \(error.localizedDescription)")
        }
    }

    /// 把当前所有已注册的本地通知打印到控制台，方便用 Console.app 查看。
    func dumpPending() async {
        let center = UNUserNotificationCenter.current()
        let settings = await center.notificationSettings()
        AppLogger.auth.info("notif auth=\(String(describing: settings.authorizationStatus.rawValue)) alert=\(String(describing: settings.alertSetting.rawValue)) sound=\(String(describing: settings.soundSetting.rawValue))")
        let pending = await center.pendingNotificationRequests()
        AppLogger.auth.info("pending count=\(pending.count)")
        for r in pending.prefix(40) {
            AppLogger.auth.info("  - id=\(r.identifier) title=\(r.content.title) trigger=\(String(describing: r.trigger))")
        }
    }
}
