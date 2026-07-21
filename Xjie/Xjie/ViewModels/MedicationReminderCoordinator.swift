import Foundation
import UserNotifications

@MainActor
protocol MedicationReminderStoreProtocol: AnyObject {
    func load(accountScope: String, subjectUserID: Int) -> [MedicationReminderSettings]
    func save(
        _ settings: [MedicationReminderSettings],
        accountScope: String,
        subjectUserID: Int
    ) throws
}

@MainActor
final class MedicationReminderStore: MedicationReminderStoreProtocol {
    private let defaults: UserDefaults

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
    }

    func load(accountScope: String, subjectUserID: Int) -> [MedicationReminderSettings] {
        guard let data = defaults.data(forKey: key(accountScope: accountScope, subjectUserID: subjectUserID)),
              let values = try? JSONDecoder().decode([MedicationReminderSettings].self, from: data) else {
            return []
        }
        return values.filter { $0.subjectUserID == subjectUserID }
    }

    func save(
        _ settings: [MedicationReminderSettings],
        accountScope: String,
        subjectUserID: Int
    ) throws {
        guard settings.allSatisfy({ $0.subjectUserID == subjectUserID }) else {
            throw MedicationClientContractError.subjectMismatch
        }
        let data = try JSONEncoder().encode(settings.sorted { $0.planID < $1.planID })
        defaults.set(data, forKey: key(accountScope: accountScope, subjectUserID: subjectUserID))
    }

    private func key(accountScope: String, subjectUserID: Int) -> String {
        let encodedScope = Data(accountScope.utf8).base64EncodedString()
        return "xjie.medication.reminders.v1.\(encodedScope).\(subjectUserID)"
    }
}

@MainActor
protocol MedicationReminderCoordinating: AnyObject {
    func permissionState() async -> MedicationReminderPermissionState
    func requestPermission() async -> MedicationReminderPermissionState
    func reconcile(
        settings: [MedicationReminderSettings],
        plans: [TrustedMedicationPlan],
        now: Date,
        timezone: TimeZone
    ) async -> MedicationReminderReconcileResult
    func clearAllMedicationNotifications() async
    func cancelSnooze(task: MedicationTodayTask, plan: TrustedMedicationPlan) async
    func scheduleSnooze(
        eventID: Int,
        task: MedicationTodayTask,
        plan: TrustedMedicationPlan,
        settings: MedicationReminderSettings?,
        at date: Date
    ) async -> Bool
}

@MainActor
final class MedicationReminderCoordinator: MedicationReminderCoordinating {
    private static let requestPrefix = "trusted.med."
    private static let snoozePrefix = "trusted.med.snooze."

    func permissionState() async -> MedicationReminderPermissionState {
        guard let center = PushNotificationManager.notificationCenter() else { return .unavailable }
        return Self.permissionState(await center.notificationSettings().authorizationStatus)
    }

    func requestPermission() async -> MedicationReminderPermissionState {
        guard let center = PushNotificationManager.notificationCenter() else { return .unavailable }
        let current = await center.notificationSettings().authorizationStatus
        switch current {
        case .notDetermined:
            _ = try? await center.requestAuthorization(options: [.alert, .sound, .badge])
        default:
            break
        }
        return Self.permissionState(await center.notificationSettings().authorizationStatus)
    }

    func reconcile(
        settings: [MedicationReminderSettings],
        plans: [TrustedMedicationPlan],
        now: Date,
        timezone: TimeZone
    ) async -> MedicationReminderReconcileResult {
        guard let center = PushNotificationManager.notificationCenter() else {
            return MedicationReminderReconcileResult(
                permission: .unavailable,
                scheduledCount: 0,
                detail: "UI 自动化或当前系统环境不使用真实通知中心。"
            )
        }

        let existing = await center.pendingNotificationRequests()
        let validPlanVersions = Set(
            plans.filter { $0.status == .active }.map {
                PlanVersion(subjectUserID: $0.subject_user_id, planID: $0.plan_id, version: $0.version)
            }
        )
        let preservedSnoozeCount = existing.filter { request in
            request.identifier.hasPrefix(Self.snoozePrefix)
                && Self.planVersion(from: request).map(validPlanVersions.contains) == true
        }.count
        // Rebuild only ordinary schedule-derived reminders. A user-requested
        // snooze survives refresh while its subject, plan and version remain
        // valid; stale snoozes are removed fail-closed.
        let identifiers = existing.compactMap { request -> String? in
            guard request.identifier.hasPrefix(Self.requestPrefix) else { return nil }
            guard request.identifier.hasPrefix(Self.snoozePrefix) else { return request.identifier }
            guard let version = Self.planVersion(from: request),
                  validPlanVersions.contains(version) else {
                return request.identifier
            }
            return nil
        }
        if !identifiers.isEmpty {
            center.removePendingNotificationRequests(withIdentifiers: identifiers)
        }

        let permission = Self.permissionState(await center.notificationSettings().authorizationStatus)
        guard permission == .allowed else {
            return MedicationReminderReconcileResult(
                permission: permission,
                scheduledCount: 0,
                detail: permission == .denied ? "通知权限已关闭，未安排本机提醒。" : nil
            )
        }

        let planByID = Dictionary(uniqueKeysWithValues: plans.map { ($0.plan_id, $0) })
        let candidates: [(MedicationReminderOccurrence, TrustedMedicationPlan, MedicationReminderSettings)] = settings
            .flatMap { reminder -> [(MedicationReminderOccurrence, TrustedMedicationPlan, MedicationReminderSettings)] in
                guard let plan = planByID[reminder.planID] else { return [] }
                return MedicationReminderPolicy.occurrences(
                    settings: reminder,
                    plan: plan,
                    now: now,
                    currentTimezone: timezone
                ).map { ($0, plan, reminder) }
            }
            .sorted { $0.0.fireDate < $1.0.fireDate }

        let ordinaryBudget = MedicationReminderPolicy.ordinaryRequestBudget(
            preservedSnoozeCount: preservedSnoozeCount
        )
        var scheduled = 0
        for (occurrence, plan, reminder) in candidates.prefix(ordinaryBudget) {
            let content = UNMutableNotificationContent()
            content.title = reminder.showMedicationNameOnLockScreen
                ? "用药提醒 · \(plan.displayName)"
                : "用药提醒"
            if reminder.showMedicationNameOnLockScreen {
                let dose = plan.dose_text.map { " · \($0)" } ?? ""
                content.body = "计划时间 \(occurrence.scheduledTime)\(dose)，请核对后再记录。"
            } else {
                content.body = "请打开小捷核对已确认的用药计划。"
            }
            content.sound = reminder.soundEnabled ? .default : nil
            content.userInfo = [
                "type": "trusted_medication_reminder",
                "plan_id": plan.plan_id,
                "subject_user_id": plan.subject_user_id,
                "plan_version": plan.version
            ]
            var calendar = Calendar(identifier: .gregorian)
            calendar.timeZone = timezone
            var components = calendar.dateComponents(
                [.calendar, .timeZone, .year, .month, .day, .hour, .minute],
                from: occurrence.fireDate
            )
            components.second = 0
            let trigger = UNCalendarNotificationTrigger(dateMatching: components, repeats: false)
            let request = UNNotificationRequest(
                identifier: occurrence.id,
                content: content,
                trigger: trigger
            )
            do {
                try await center.add(request)
                scheduled += 1
            } catch {
                AppLogger.auth.error("trusted medication reminder add failed: \(error.localizedDescription)")
            }
        }
        let limited = candidates.count > ordinaryBudget
        return MedicationReminderReconcileResult(
            permission: permission,
            scheduledCount: scheduled,
            detail: limited
                ? "iOS 本轮保留 \(preservedSnoozeCount) 次稍后提醒，并续排最近 \(ordinaryBudget) 次常规提醒；打开小捷会按当前计划继续续排。"
                : nil
        )
    }

    func clearAllMedicationNotifications() async {
        guard let center = PushNotificationManager.notificationCenter() else { return }
        let identifiers = await center.pendingNotificationRequests()
            .map(\.identifier)
            .filter { $0.hasPrefix(Self.requestPrefix) }
        guard !identifiers.isEmpty else { return }
        center.removePendingNotificationRequests(withIdentifiers: identifiers)
    }

    func cancelSnooze(task: MedicationTodayTask, plan: TrustedMedicationPlan) async {
        guard let center = PushNotificationManager.notificationCenter() else { return }
        center.removePendingNotificationRequests(
            withIdentifiers: [MedicationReminderPolicy.snoozeIdentifier(task: task, plan: plan)]
        )
    }

    func scheduleSnooze(
        eventID: Int,
        task: MedicationTodayTask,
        plan: TrustedMedicationPlan,
        settings: MedicationReminderSettings?,
        at date: Date
    ) async -> Bool {
        guard date > Date(),
              let center = PushNotificationManager.notificationCenter(),
              Self.permissionState(await center.notificationSettings().authorizationStatus) == .allowed else {
            return false
        }
        let content = UNMutableNotificationContent()
        let showName = settings?.showMedicationNameOnLockScreen == true
        content.title = showName ? "用药稍后提醒 · \(plan.displayName)" : "用药稍后提醒"
        content.body = showName
            ? "请核对 \(task.scheduled_time) 的已确认用药计划。"
            : "请打开小捷核对本次用药。"
        content.sound = settings?.soundEnabled == false ? nil : .default
        content.userInfo = [
            "type": "trusted_medication_snooze",
            "plan_id": plan.plan_id,
            "subject_user_id": plan.subject_user_id,
            "plan_version": plan.version,
            "dose_event_id": eventID
        ]
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = .current
        var components = calendar.dateComponents(
            [.calendar, .timeZone, .year, .month, .day, .hour, .minute],
            from: date
        )
        components.second = 0
        let trigger = UNCalendarNotificationTrigger(dateMatching: components, repeats: false)
        let identifier = MedicationReminderPolicy.snoozeIdentifier(task: task, plan: plan)
        do {
            try await center.add(
                UNNotificationRequest(identifier: identifier, content: content, trigger: trigger)
            )
            return true
        } catch {
            AppLogger.auth.error("trusted medication snooze add failed: \(error.localizedDescription)")
            return false
        }
    }

    private static func permissionState(
        _ status: UNAuthorizationStatus
    ) -> MedicationReminderPermissionState {
        switch status {
        case .authorized, .provisional, .ephemeral: return .allowed
        case .denied: return .denied
        case .notDetermined: return .notDetermined
        @unknown default: return .unavailable
        }
    }

    private struct PlanVersion: Hashable {
        let subjectUserID: Int
        let planID: Int
        let version: Int
    }

    private static func planVersion(from request: UNNotificationRequest) -> PlanVersion? {
        let info = request.content.userInfo
        guard info["type"] as? String == "trusted_medication_snooze",
              let subject = integer(info["subject_user_id"]),
              let plan = integer(info["plan_id"]),
              let version = integer(info["plan_version"]) else {
            return nil
        }
        return PlanVersion(subjectUserID: subject, planID: plan, version: version)
    }

    private static func integer(_ value: Any?) -> Int? {
        if let value = value as? Int { return value }
        return (value as? NSNumber)?.intValue
    }
}
