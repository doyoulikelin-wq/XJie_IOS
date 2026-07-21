import Foundation
import HealthKit
import SwiftUI

enum AppleHealthSyncValueKind: String, Equatable {
    case numeric
    case category
}

struct AppleHealthSyncSample: Identifiable, Equatable {
    let id: String
    let metricID: String
    let indicatorName: String
    let value: Double
    let unit: String
    let measuredAt: Date
    let displayValue: String
    let displayUnit: String
    let subtitle: String
    let valueKind: AppleHealthSyncValueKind
    let sourceLocalDate: String
    let timezoneOffsetMinutes: Int

    init(
        id: String,
        metricID: String,
        indicatorName: String,
        value: Double,
        unit: String,
        measuredAt: Date,
        displayValue: String,
        displayUnit: String,
        subtitle: String,
        valueKind: AppleHealthSyncValueKind = .numeric,
        sourceLocalDate: String? = nil,
        timezoneOffsetMinutes: Int? = nil,
        timeZone: TimeZone = .current
    ) {
        self.id = id
        self.metricID = metricID
        self.indicatorName = indicatorName
        self.value = value
        self.unit = unit
        self.measuredAt = measuredAt
        self.displayValue = displayValue
        self.displayUnit = displayUnit
        self.subtitle = subtitle
        self.valueKind = valueKind

        let formatter = DateFormatter()
        formatter.calendar = Calendar(identifier: .gregorian)
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = timeZone
        formatter.dateFormat = "yyyy-MM-dd"
        self.sourceLocalDate = sourceLocalDate ?? formatter.string(from: measuredAt)

        let derivedOffset = timeZone.secondsFromGMT(for: measuredAt) / 60
        let selectedOffset = timezoneOffsetMinutes ?? derivedOffset
        self.timezoneOffsetMinutes = min(840, max(-840, selectedOffset))
    }
}

struct AppleHealthMetricReadIssue: Identifiable, Equatable {
    enum Kind: Equatable {
        case noData
        case queryFailed
        case unsupported
    }

    var id: String { "\(metricID)-\(kind)" }
    let metricID: String
    let indicatorName: String
    let kind: Kind
    let message: String
}

struct AppleHealthReadResult: Equatable {
    let samples: [AppleHealthSyncSample]
    let issues: [AppleHealthMetricReadIssue]

    static let empty = AppleHealthReadResult(samples: [], issues: [])

    var failures: [AppleHealthMetricReadIssue] {
        issues.filter { $0.kind == .queryFailed }
    }

    var emptyMetrics: [AppleHealthMetricReadIssue] {
        issues.filter { $0.kind == .noData }
    }

    var unsupportedMetrics: [AppleHealthMetricReadIssue] {
        issues.filter { $0.kind == .unsupported }
    }
}

struct AppleHealthBackgroundDeliveryResult: Equatable {
    let attempted: Int
    let succeeded: Int
    let failures: [String]
    let failureMessages: [String: String]

    init(
        attempted: Int,
        succeeded: Int,
        failures: [String],
        failureMessages: [String: String] = [:]
    ) {
        self.attempted = attempted
        self.succeeded = succeeded
        self.failures = failures
        self.failureMessages = failureMessages
    }

    var allFailed: Bool { attempted > 0 && succeeded == 0 }
}

struct DeviceIndicatorSyncValue: Encodable {
    let indicator_name: String
    let value: Double
    let unit: String?
    let measured_at: String
    let value_kind: String
    let display_value: String
    let source_local_date: String
    let timezone_offset_minutes: Int
    let source_metric: String?
    let source_id: String?
    let notes: String?
}

struct DeviceIndicatorSyncRequest: Encodable {
    let source: String
    let values: [DeviceIndicatorSyncValue]
}

struct DeviceIndicatorSyncIssue: Codable, Equatable {
    let index: Int
    let code: String
}

struct DeviceIndicatorSyncRejection: Equatable {
    let code: String?
    let message: String?
    let response: DeviceIndicatorSyncResponse

    private struct Envelope: Decodable {
        let detail: Detail
    }

    private struct Detail: Decodable {
        let code: String?
        let message: String?
        let total: Int?
        let inserted: Int?
        let updated: Int?
        let skipped: Int?
        let unchanged: Int?
        let rejected: Int?
        let issues: [DeviceIndicatorSyncIssue]?
    }

    static func decode(from data: Data) -> DeviceIndicatorSyncRejection? {
        do {
            let detail = try JSONDecoder().decode(Envelope.self, from: data).detail
            guard let total = detail.total,
                  let inserted = detail.inserted,
                  let updated = detail.updated else { return nil }
            let unchanged = detail.unchanged ?? 0
            let rejected = detail.rejected ?? 0
            return DeviceIndicatorSyncRejection(
                code: detail.code,
                message: detail.message,
                response: DeviceIndicatorSyncResponse(
                    total: total,
                    inserted: inserted,
                    updated: updated,
                    skipped: detail.skipped ?? (unchanged + rejected),
                    unchanged: unchanged,
                    rejected: rejected,
                    issues: detail.issues
                )
            )
        } catch {
            return nil
        }
    }
}

struct DeviceIndicatorSyncResponse: Codable, Equatable {
    let total: Int
    let inserted: Int
    let updated: Int
    let skipped: Int
    let unchanged: Int?
    let rejected: Int?
    let issues: [DeviceIndicatorSyncIssue]?

    init(
        total: Int,
        inserted: Int,
        updated: Int,
        skipped: Int,
        unchanged: Int? = nil,
        rejected: Int? = nil,
        issues: [DeviceIndicatorSyncIssue]? = nil
    ) {
        self.total = total
        self.inserted = inserted
        self.updated = updated
        self.skipped = skipped
        self.unchanged = unchanged
        self.rejected = rejected
        self.issues = issues
    }

    var written: Int {
        max(0, inserted) + max(0, updated)
    }

    var unchangedCount: Int {
        if let unchanged { return max(0, unchanged) }
        // Legacy responses only exposed skipped, where every skipped value meant
        // an already-current value. New responses split skipped into unchanged + rejected.
        return max(0, skipped - max(0, rejected ?? 0))
    }

    func rejectedCount(requested: Int) -> Int {
        let missingFromResponse = max(0, requested - max(0, total))
        if let rejected {
            return max(0, rejected) + missingFromResponse
        }
        let unaccountedByLegacyServer = max(0, total - written - unchangedCount)
        return unaccountedByLegacyServer + missingFromResponse
    }
}

struct AppleHealthSyncExecution: Equatable {
    let readResult: AppleHealthReadResult
    let response: DeviceIndicatorSyncResponse?
}

private enum AppleHealthSyncPayloadBuilder {
    static func request(samples: [AppleHealthSyncSample]) -> DeviceIndicatorSyncRequest {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        return DeviceIndicatorSyncRequest(
            source: "apple_health",
            values: samples.map { sample in
                DeviceIndicatorSyncValue(
                    indicator_name: sample.indicatorName,
                    value: sample.value,
                    unit: sample.unit.isEmpty ? nil : sample.unit,
                    measured_at: formatter.string(from: sample.measuredAt),
                    value_kind: sample.valueKind.rawValue,
                    display_value: sample.displayValue,
                    source_local_date: sample.sourceLocalDate,
                    timezone_offset_minutes: sample.timezoneOffsetMinutes,
                    source_metric: sample.metricID,
                    source_id: sample.id,
                    notes: "Apple Health 同步"
                )
            }
        )
    }
}

@MainActor
final class AppleHealthSyncViewModel: ObservableObject {
    enum Status: Equatable {
        case idle
        case unavailable
        case requesting
        case reading
        case syncing
        case synced
        case upToDate
        case partiallySynced
        case rejected
        case failed(String)
    }

    @Published var status: Status = .idle
    @Published var samples: [AppleHealthSyncSample] = []
    @Published var readIssues: [AppleHealthMetricReadIssue] = []
    @Published var syncResponse: DeviceIndicatorSyncResponse?
    @Published var lastSyncedAt: Date?

    private let api: APIServiceProtocol
    private let healthStore: AppleHealthStoreProtocol
    private let backgroundCoordinator: AppleHealthBackgroundCoordinating
    private let userDefaults: UserDefaults
    private var accountScope: String?
    private var scopeGeneration = 0
    private var pendingSampleCount = 0
    private var uploadRejectionMessage: String?
    private var authorizationRecoveryNeeded = false
    private var zeroSampleRecoveryNeeded = false
    private let syncedAtKeyPrefix = "xage.appleHealth.lastSyncedAt"

    static func shouldUseHealthKit(arguments: [String]) -> Bool {
        #if DEBUG
        !UIAutomationMode.isEnabled(arguments: arguments)
        #else
        true
        #endif
    }

    init(
        api: APIServiceProtocol? = nil,
        healthStore: AppleHealthStoreProtocol? = nil,
        userDefaults: UserDefaults = .standard,
        accountScope: String? = nil,
        backgroundCoordinator: AppleHealthBackgroundCoordinating? = nil
    ) {
        let usesProductionDependencies = api == nil && healthStore == nil
        self.api = api ?? APIService.shared
        self.healthStore = healthStore ?? AppleHealthStore()
        self.backgroundCoordinator = backgroundCoordinator
            ?? (usesProductionDependencies
                ? AppleHealthBackgroundSyncCoordinator.shared
                : DisabledAppleHealthBackgroundCoordinator.shared)
        self.userDefaults = userDefaults
        self.accountScope = Self.normalizedScope(accountScope)
        // Never migrate the legacy device-global marker into a logged-in account.
        // Keeping it could make a newly logged-in user auto-upload this device's data.
        userDefaults.removeObject(forKey: syncedAtKeyPrefix)
        if let accountScope = self.accountScope {
            self.lastSyncedAt = userDefaults.object(forKey: Self.syncedAtKey(prefix: syncedAtKeyPrefix, scope: accountScope)) as? Date
            self.backgroundCoordinator.startIfEligible(accountScope: accountScope)
        }
    }

    var isWorking: Bool {
        switch status {
        case .requesting, .reading, .syncing:
            return true
        default:
            return false
        }
    }

    var statusTitle: String {
        switch status {
        case .idle:
            return lastSyncedAt == nil ? "未授权同步" : "可再次同步"
        case .unavailable:
            return "设备不支持"
        case .requesting:
            return "申请访问中"
        case .reading:
            return "正在读取 Apple 健康"
        case .syncing:
            return "正在同步服务器"
        case .synced:
            return "已写入服务器"
        case .upToDate:
            return "服务器已是最新"
        case .partiallySynced:
            return "部分写入服务器"
        case .rejected:
            return "服务器未接收"
        case .failed:
            return "同步失败"
        }
    }

    var shouldOfferHealthSettingsRecovery: Bool {
        authorizationRecoveryNeeded || zeroSampleRecoveryNeeded
    }

    var rejectionIssueDetails: [String] {
        guard let issues = syncResponse?.issues else { return [] }
        return issues.map { issue in
            let itemName: String
            if samples.indices.contains(issue.index) {
                itemName = samples[issue.index].indicatorName
            } else {
                itemName = "第 \(issue.index + 1) 项"
            }
            return "\(itemName)：\(Self.rejectionReason(for: issue.code))"
        }
    }

    var statusSubtitle: String {
        switch status {
        case .idle:
            if accountScope == nil {
                return "登录后可授权读取 Apple 健康；同步记录会按账号隔离。"
            }
            if let lastSyncedAt {
                return "上次 \(Self.relativeFormatter.localizedString(for: lastSyncedAt, relativeTo: Date()))，可手动刷新最新数据。"
            }
            return "授权后读取 Apple 健康中的可用指标，并写入当前账号的服务器趋势。"
        case .unavailable:
            return "当前设备或模拟器未开放 Apple 健康数据。"
        case .requesting:
            return "系统会弹出 Apple 健康权限，只读取你勾选的数据。"
        case .reading:
            return "正在按指标读取：今日累计、近 36 小时睡眠、近 14 天生命体征，体重/体脂/心肺适能及生殖记录近 365 天，身高/BMI/瘦体重/腰围全部历史。"
        case .syncing:
            return "已在本机读取 \(pendingSampleCount) 项，正在等待服务器确认；尚未标记为已上云。"
        case .synced:
            guard let response = syncResponse else { return "服务器已确认写入。" }
            return Self.appendReadIssueSummary(
                "服务器写入 \(response.written) 项（新增 \(response.inserted)、更新 \(response.updated)），\(response.unchangedCount) 项已是最新。",
                issues: readIssues
            )
        case .upToDate:
            guard let response = syncResponse else { return "服务器确认本次数据已是最新。" }
            return Self.appendReadIssueSummary(
                "服务器确认 \(response.unchangedCount) 项已存在且无需更新，本次没有重复写入。",
                issues: readIssues
            )
        case .partiallySynced:
            guard let response = syncResponse else { return "部分指标已写入，部分指标未被服务器接收。" }
            let rejected = response.rejectedCount(requested: pendingSampleCount)
            let summary = Self.appendReadIssueSummary(
                "服务器写入 \(response.written) 项，\(response.unchangedCount) 项已是最新，\(rejected) 项未接收。",
                issues: readIssues
            )
            return Self.appendRejectionDetails(summary, details: rejectionIssueDetails)
        case .rejected:
            guard let response = syncResponse else {
                return uploadRejectionMessage ?? "服务器没有接收本次 Apple 健康数据。"
            }
            let serverMessage = uploadRejectionMessage.map { "\($0) " } ?? ""
            let summary = "\(serverMessage)服务器没有接收本次 \(pendingSampleCount) 项数据（已是最新 \(response.unchangedCount) 项、未接收 \(response.rejectedCount(requested: pendingSampleCount)) 项）。"
            return Self.appendRejectionDetails(summary, details: rejectionIssueDetails)
        case .failed(let message):
            return message
        }
    }

    /// The UI must call this whenever the authenticated subject changes. A nil scope
    /// deliberately disables automatic refresh so one account can never inherit another
    /// account's Apple Health sync marker.
    func setAccountScope(_ scope: String?) {
        let normalized = Self.normalizedScope(scope)
        guard normalized != accountScope else { return }
        backgroundCoordinator.stop()
        accountScope = normalized
        scopeGeneration += 1
        status = .idle
        samples = []
        readIssues = []
        syncResponse = nil
        uploadRejectionMessage = nil
        pendingSampleCount = 0
        authorizationRecoveryNeeded = false
        zeroSampleRecoveryNeeded = false
        if let normalized {
            lastSyncedAt = userDefaults.object(forKey: Self.syncedAtKey(prefix: syncedAtKeyPrefix, scope: normalized)) as? Date
            backgroundCoordinator.startIfEligible(accountScope: normalized)
        } else {
            lastSyncedAt = nil
        }
    }

    func requestAccessAndSync() async {
        if !Self.shouldUseHealthKit(arguments: ProcessInfo.processInfo.arguments) {
            status = .idle
            return
        }
        guard let authorizationScope = accountScope else {
            status = .failed("无法确认当前登录账号，已停止上传 Apple 健康数据。请重新登录后再试。")
            return
        }
        guard healthStore.isHealthDataAvailable else {
            status = .unavailable
            return
        }

        let generation = scopeGeneration
        authorizationRecoveryNeeded = false
        zeroSampleRecoveryNeeded = false
        status = .requesting
        do {
            try await healthStore.requestAuthorization()
        } catch {
            authorizationRecoveryNeeded = true
            status = .failed("未获得 Apple 健康访问权限：\(error.localizedDescription)")
            return
        }

        guard accountScope == authorizationScope, scopeGeneration == generation else { return }
        // Enrollment records an explicit user action, not a successful read/upload.
        // It is written immediately after the HealthKit authorization sheet returns so
        // a later Health sample can wake the observer even when the first read is empty.
        backgroundCoordinator.enroll(accountScope: authorizationScope)

        await refreshAndSync()
        guard accountScope == authorizationScope, scopeGeneration == generation else { return }
        backgroundCoordinator.startIfEligible(accountScope: authorizationScope)
    }

    func refreshIfPreviouslySynced() async {
        guard Self.shouldUseHealthKit(arguments: ProcessInfo.processInfo.arguments) else {
            return
        }
        guard accountScope != nil, lastSyncedAt != nil, !isWorking else { return }
        await refreshAndSync()
    }

    func refreshAndSync() async {
        guard Self.shouldUseHealthKit(arguments: ProcessInfo.processInfo.arguments) else {
            status = .idle
            return
        }
        guard let syncScope = accountScope else {
            status = .failed("无法确认当前登录账号，已停止上传 Apple 健康数据。请重新登录后再试。")
            return
        }
        guard healthStore.isHealthDataAvailable else {
            status = .unavailable
            return
        }

        let generation = scopeGeneration
        status = .reading
        syncResponse = nil
        uploadRejectionMessage = nil
        authorizationRecoveryNeeded = false
        zeroSampleRecoveryNeeded = false
        do {
            let execution = try await backgroundCoordinator.performSync(accountScope: syncScope) { [weak self] in
                guard let self else { throw CancellationError() }
                return try await self.executeSync(accountScope: syncScope, generation: generation)
            }
            guard accountScope == syncScope, scopeGeneration == generation else { return }

            let readResult = execution.readResult
            samples = readResult.samples
            readIssues = readResult.issues
            pendingSampleCount = readResult.samples.count
            guard let response = execution.response else {
                zeroSampleRecoveryNeeded = true
                status = .failed(Self.zeroSampleMessage(for: readResult))
                return
            }
            syncResponse = response
            status = Self.status(for: response, requested: readResult.samples.count)
            switch status {
            case .synced, .upToDate, .partiallySynced:
                let now = Date()
                lastSyncedAt = now
                userDefaults.set(now, forKey: Self.syncedAtKey(prefix: syncedAtKeyPrefix, scope: syncScope))
            default:
                break
            }
        } catch APIError.httpErrorResponse(let code, let message, let data) where code == 422 {
            guard accountScope == syncScope, scopeGeneration == generation else { return }
            if let rejection = DeviceIndicatorSyncRejection.decode(from: data) {
                syncResponse = rejection.response
                uploadRejectionMessage = rejection.message ?? message
                status = Self.status(for: rejection.response, requested: pendingSampleCount)
            } else {
                uploadRejectionMessage = message
                status = .rejected
            }
        } catch APIError.httpError(let code, let message) where code == 422 {
            guard accountScope == syncScope, scopeGeneration == generation else { return }
            uploadRejectionMessage = message
            status = .rejected
        } catch {
            guard accountScope == syncScope, scopeGeneration == generation else { return }
            status = .failed(Self.healthSyncErrorMessage(error))
        }
    }

    private func executeSync(accountScope: String, generation: Int) async throws -> AppleHealthSyncExecution {
        let readResult = try await healthStore.readDailySamples()
        guard self.accountScope == accountScope, scopeGeneration == generation else {
            throw APIError.accountScopeChanged
        }
        samples = readResult.samples
        readIssues = readResult.issues
        pendingSampleCount = readResult.samples.count
        guard !readResult.samples.isEmpty else {
            return AppleHealthSyncExecution(readResult: readResult, response: nil)
        }

        status = .syncing
        let response: DeviceIndicatorSyncResponse = try await api.postAccountBound(
            "/api/health-data/indicators/device-sync",
            body: AppleHealthSyncPayloadBuilder.request(samples: readResult.samples),
            expectedAccountScope: accountScope,
            timeout: nil
        )
        guard self.accountScope == accountScope, scopeGeneration == generation else {
            throw APIError.accountScopeChanged
        }
        return AppleHealthSyncExecution(readResult: readResult, response: response)
    }

    private static func status(for response: DeviceIndicatorSyncResponse, requested: Int) -> Status {
        let rejected = response.rejectedCount(requested: requested)
        if rejected > 0 {
            return response.written > 0 || response.unchangedCount > 0 ? .partiallySynced : .rejected
        }
        if response.written > 0 {
            return .synced
        }
        if requested > 0, response.unchangedCount >= requested {
            return .upToDate
        }
        return .rejected
    }

    private static let relativeFormatter: RelativeDateTimeFormatter = {
        let formatter = RelativeDateTimeFormatter()
        formatter.unitsStyle = .short
        return formatter
    }()

    private static func zeroSampleMessage(for result: AppleHealthReadResult) -> String {
        var details: [String] = []
        if !result.failures.isEmpty {
            details.append("\(result.failures.count) 项查询失败")
        }
        if !result.emptyMetrics.isEmpty {
            details.append("\(result.emptyMetrics.count) 项在读取时间窗内没有样本")
        }
        let detailText = details.isEmpty ? "" : "（\(details.joined(separator: "，"))）"
        return "Apple 健康暂无可同步样本\(detailText)。请确认“健康”App 中已有数据，并在系统设置中允许小捷读取；累计项目读取今天，睡眠读取近 36 小时，生命体征读取近 14 天，体重/体脂/心肺适能及生殖记录读取近 365 天，身高/BMI/瘦体重/腰围读取全部历史。为保护隐私，系统也可能把拒绝读取显示成无数据。"
    }

    private static func appendReadIssueSummary(_ base: String, issues: [AppleHealthMetricReadIssue]) -> String {
        let failed = issues.filter { $0.kind == .queryFailed }.count
        let empty = issues.filter { $0.kind == .noData }.count
        guard failed > 0 || empty > 0 else { return base }
        var parts: [String] = []
        if empty > 0 { parts.append("\(empty) 项无近期数据") }
        if failed > 0 { parts.append("\(failed) 项读取失败") }
        return "\(base) 另有\(parts.joined(separator: "、"))。"
    }

    private static func appendRejectionDetails(_ base: String, details: [String]) -> String {
        guard !details.isEmpty else { return base }
        return "\(base) 未接收原因：\(details.joined(separator: "；"))。"
    }

    private static func rejectionReason(for code: String) -> String {
        switch code {
        case "invalid_indicator_name":
            return "指标名称无效"
        case "future_measured_at":
            return "测量时间晚于当前时间"
        case "invalid_value":
            return "数值无效"
        case "missing_display_value":
            return "分类值缺少显示标签"
        case "source_id_conflict":
            return "来源标识已属于另一个指标"
        case "source_local_date_conflict":
            return "本地日期与测量时间不一致"
        default:
            return "服务器拒绝（\(code)）"
        }
    }

    private static func healthSyncErrorMessage(_ error: Error) -> String {
        let message = error.localizedDescription
        if message.localizedCaseInsensitiveContains("not found") {
            return "没有找到可同步的 Apple 健康样本。请确认健康 App 中已有记录，并在系统权限中允许小捷读取。"
        }
        return "Apple 健康同步失败：\(message)"
    }

    private static func normalizedScope(_ scope: String?) -> String? {
        guard let value = scope?.trimmingCharacters(in: .whitespacesAndNewlines), !value.isEmpty else { return nil }
        return value
    }

    private static func syncedAtKey(prefix: String, scope: String) -> String {
        let token = Data(scope.utf8).base64EncodedString()
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "=", with: "")
        return "\(prefix).\(token)"
    }
}

protocol AppleHealthStoreProtocol {
    var isHealthDataAvailable: Bool { get }
    func requestAuthorization() async throws
    func readDailySamples() async throws -> AppleHealthReadResult
}

protocol AppleHealthBackgroundStoreProtocol: AppleHealthStoreProtocol {
    func startObserverQueries(
        updateHandler: @escaping (@escaping () -> Void) -> Void
    )
    func stopObserverQueries()
    func enableBackgroundDelivery() async -> AppleHealthBackgroundDeliveryResult
    func disableBackgroundDelivery() async -> AppleHealthBackgroundDeliveryResult
}

struct AppleHealthMetricDefinition {
    enum Lookback: Equatable {
        case days(Int)
        case allHistory

        var noDataWindowDescription: String {
            switch self {
            case .days(let days):
                return "近 \(days) 天"
            case .allHistory:
                return "全部历史记录中"
            }
        }

        func startDate(
            endingAt end: Date,
            calendar: Calendar
        ) -> Date? {
            switch self {
            case .days(let days):
                let fallback = end.addingTimeInterval(-Double(days) * 24 * 3600)
                return calendar.date(byAdding: .day, value: -days, to: end) ?? fallback
            case .allHistory:
                return nil
            }
        }

        func predicate(
            endingAt end: Date,
            calendar: Calendar
        ) -> NSPredicate {
            // Even all-history reads retain an explicit end bound. A truly nil
            // predicate could select a future-dated bad sample as the latest one and
            // hide the newest valid historical value behind a server-side rejection.
            HKQuery.predicateForSamples(
                withStart: startDate(endingAt: end, calendar: calendar),
                end: end,
                options: .strictEndDate
            )
        }
    }

    enum Query {
        case cumulativeToday(HKQuantityTypeIdentifier, HKUnit, multiplyBy: Double)
        case latest(HKQuantityTypeIdentifier, HKUnit, multiplyBy: Double, lookback: Lookback)
        case durationToday(HKCategoryTypeIdentifier)
        case sleep(asleep: Bool)
        case latestCategory(HKCategoryTypeIdentifier, lookback: Lookback)
        case unsupported(String)
    }

    let metricID: String
    let indicatorName: String
    let displayUnit: String
    let subtitle: String
    let query: Query

    var isSupported: Bool {
        if case .unsupported = query { return false }
        return true
    }

    var lookback: Lookback? {
        switch query {
        case .latest(_, _, _, let lookback), .latestCategory(_, let lookback):
            return lookback
        default:
            return nil
        }
    }

    fileprivate var objectType: HKObjectType? {
        switch query {
        case .cumulativeToday(let identifier, _, _), .latest(let identifier, _, _, _):
            return HKQuantityType.quantityType(forIdentifier: identifier)
        case .durationToday(let identifier), .latestCategory(let identifier, _):
            return HKCategoryType.categoryType(forIdentifier: identifier)
        case .sleep:
            return HKCategoryType.categoryType(forIdentifier: .sleepAnalysis)
        case .unsupported:
            return nil
        }
    }
}

final class AppleHealthStore: AppleHealthBackgroundStoreProtocol, @unchecked Sendable {
    private enum ReadOutcome {
        case sample(AppleHealthSyncSample)
        case issue(AppleHealthMetricReadIssue)
    }

    private enum StoreError: LocalizedError {
        case typeUnavailable(String)

        var errorDescription: String? {
            switch self {
            case .typeUnavailable(let name):
                return "当前系统没有提供 \(name) 的 HealthKit 类型"
            }
        }
    }

    private let store: HKHealthStore
    private let calendar: Calendar
    private let now: () -> Date
    private let observerLock = NSLock()
    private var observerQueries: [HKObserverQuery] = []

    init(
        store: HKHealthStore = HKHealthStore(),
        calendar: Calendar = .current,
        now: @escaping () -> Date = Date.init
    ) {
        self.store = store
        self.calendar = calendar
        self.now = now
    }

    var isHealthDataAvailable: Bool {
        HKHealthStore.isHealthDataAvailable()
    }

    func requestAuthorization() async throws {
        try await store.requestAuthorization(toShare: Set<HKSampleType>(), read: Self.readTypes)
    }

    func startObserverQueries(
        updateHandler: @escaping (@escaping () -> Void) -> Void
    ) {
        stopObserverQueries()
        let queries = Self.backgroundSampleTypes.map { sampleType in
            HKObserverQuery(sampleType: sampleType, predicate: nil) { _, completion, error in
                if let error {
                    AppLogger.data.error("HealthKit observer failed for \(sampleType.identifier, privacy: .public): \(error.localizedDescription, privacy: .public)")
                    completion()
                    return
                }
                updateHandler(completion)
            }
        }
        observerLock.lock()
        observerQueries = queries
        observerLock.unlock()
        queries.forEach { store.execute($0) }
    }

    func stopObserverQueries() {
        observerLock.lock()
        let queries = observerQueries
        observerQueries = []
        observerLock.unlock()
        queries.forEach { store.stop($0) }
    }

    func enableBackgroundDelivery() async -> AppleHealthBackgroundDeliveryResult {
        var attempted = 0
        var succeeded = 0
        var failures: [String] = []
        var failureMessages: [String: String] = [:]
        for type in Self.backgroundSampleTypes {
            guard !Task.isCancelled else { break }
            attempted += 1
            let outcome: (enabled: Bool, message: String?) = await withCheckedContinuation { continuation in
                store.enableBackgroundDelivery(for: type, frequency: .immediate) { success, error in
                    let enabled = success && error == nil
                    let message = enabled
                        ? nil
                        : (error?.localizedDescription ?? "HealthKit 返回失败但未提供错误详情")
                    continuation.resume(returning: (enabled, message))
                }
            }
            if outcome.enabled {
                succeeded += 1
            } else {
                failures.append(type.identifier)
                failureMessages[type.identifier] = outcome.message
                AppLogger.data.error("HealthKit background enable failed for \(type.identifier, privacy: .public): \(outcome.message ?? "unknown", privacy: .public)")
            }
        }
        let result = AppleHealthBackgroundDeliveryResult(
            attempted: attempted,
            succeeded: succeeded,
            failures: failures,
            failureMessages: failureMessages
        )
        AppLogger.data.info("HealthKit background enable attempted=\(result.attempted, privacy: .public) succeeded=\(result.succeeded, privacy: .public) failed=\(result.failures.count, privacy: .public)")
        return result
    }

    func disableBackgroundDelivery() async -> AppleHealthBackgroundDeliveryResult {
        var attempted = 0
        var succeeded = 0
        var failures: [String] = []
        var failureMessages: [String: String] = [:]
        for type in Self.backgroundSampleTypes {
            guard !Task.isCancelled else { break }
            attempted += 1
            let outcome: (disabled: Bool, message: String?) = await withCheckedContinuation { continuation in
                store.disableBackgroundDelivery(for: type) { success, error in
                    let disabled = success && error == nil
                    let message = disabled
                        ? nil
                        : (error?.localizedDescription ?? "HealthKit 返回失败但未提供错误详情")
                    continuation.resume(returning: (disabled, message))
                }
            }
            if outcome.disabled {
                succeeded += 1
            } else {
                failures.append(type.identifier)
                failureMessages[type.identifier] = outcome.message
                AppLogger.data.error("HealthKit background disable failed for \(type.identifier, privacy: .public): \(outcome.message ?? "unknown", privacy: .public)")
            }
        }
        let result = AppleHealthBackgroundDeliveryResult(
            attempted: attempted,
            succeeded: succeeded,
            failures: failures,
            failureMessages: failureMessages
        )
        AppLogger.data.info("HealthKit background disable attempted=\(result.attempted, privacy: .public) succeeded=\(result.succeeded, privacy: .public) failed=\(result.failures.count, privacy: .public)")
        return result
    }

    func readDailySamples() async throws -> AppleHealthReadResult {
        let registry = Self.metricRegistry
        var outcomesByIndex: [Int: ReadOutcome] = [:]

        await withTaskGroup(of: (Int, ReadOutcome).self) { group in
            for (index, definition) in registry.enumerated() {
                if case .unsupported(let reason) = definition.query {
                    outcomesByIndex[index] = .issue(AppleHealthMetricReadIssue(
                        metricID: definition.metricID,
                        indicatorName: definition.indicatorName,
                        kind: .unsupported,
                        message: reason
                    ))
                    continue
                }
                group.addTask { [self] in
                    do {
                        if let sample = try await read(definition) {
                            return (index, .sample(sample))
                        }
                        return (index, .issue(AppleHealthMetricReadIssue(
                            metricID: definition.metricID,
                            indicatorName: definition.indicatorName,
                            kind: .noData,
                            message: noDataMessage(for: definition)
                        )))
                    } catch {
                        return (index, .issue(AppleHealthMetricReadIssue(
                            metricID: definition.metricID,
                            indicatorName: definition.indicatorName,
                            kind: .queryFailed,
                            message: error.localizedDescription
                        )))
                    }
                }
            }
            for await (index, outcome) in group {
                outcomesByIndex[index] = outcome
            }
        }

        var samples: [AppleHealthSyncSample] = []
        var issues: [AppleHealthMetricReadIssue] = []
        for index in registry.indices {
            switch outcomesByIndex[index] {
            case .sample(let sample):
                samples.append(sample)
            case .issue(let issue):
                issues.append(issue)
            case nil:
                let definition = registry[index]
                issues.append(AppleHealthMetricReadIssue(
                    metricID: definition.metricID,
                    indicatorName: definition.indicatorName,
                    kind: .queryFailed,
                    message: "读取任务没有返回结果"
                ))
            }
        }
        return AppleHealthReadResult(samples: samples, issues: issues)
    }

    private func read(_ definition: AppleHealthMetricDefinition) async throws -> AppleHealthSyncSample? {
        switch definition.query {
        case .cumulativeToday(let identifier, let unit, let multiplier):
            return try await cumulativeToday(definition, identifier: identifier, unit: unit, multiplier: multiplier)
        case .latest(let identifier, let unit, let multiplier, let lookback):
            return try await latest(
                definition,
                identifier: identifier,
                unit: unit,
                multiplier: multiplier,
                lookback: lookback
            )
        case .durationToday(let identifier):
            return try await categoryDurationToday(definition, identifier: identifier)
        case .sleep(let asleep):
            return try await sleepDuration(definition, asleep: asleep)
        case .latestCategory(let identifier, let lookback):
            return try await latestCategory(
                definition,
                identifier: identifier,
                lookback: lookback
            )
        case .unsupported:
            return nil
        }
    }

    private func cumulativeToday(
        _ definition: AppleHealthMetricDefinition,
        identifier: HKQuantityTypeIdentifier,
        unit: HKUnit,
        multiplier: Double
    ) async throws -> AppleHealthSyncSample? {
        guard let quantityType = HKQuantityType.quantityType(forIdentifier: identifier) else {
            throw StoreError.typeUnavailable(definition.indicatorName)
        }
        let end = now()
        let start = calendar.startOfDay(for: end)
        let predicate = HKQuery.predicateForSamples(withStart: start, end: end, options: .strictStartDate)
        return try await withCheckedThrowingContinuation { continuation in
            let query = HKStatisticsQuery(quantityType: quantityType, quantitySamplePredicate: predicate, options: .cumulativeSum) { _, stats, error in
                if let error {
                    continuation.resume(throwing: error)
                    return
                }
                guard let quantity = stats?.sumQuantity() else {
                    continuation.resume(returning: nil)
                    return
                }
                let value = quantity.doubleValue(for: unit) * multiplier
                guard value.isFinite, value >= 0 else {
                    continuation.resume(returning: nil)
                    return
                }
                continuation.resume(returning: Self.sample(
                    definition: definition,
                    rawValue: value,
                    measuredAt: end,
                    sourceID: Self.dayKey(for: start, timeZone: self.calendar.timeZone),
                    timeZone: self.calendar.timeZone
                ))
            }
            store.execute(query)
        }
    }

    private func latest(
        _ definition: AppleHealthMetricDefinition,
        identifier: HKQuantityTypeIdentifier,
        unit: HKUnit,
        multiplier: Double,
        lookback: AppleHealthMetricDefinition.Lookback
    ) async throws -> AppleHealthSyncSample? {
        guard let quantityType = HKQuantityType.quantityType(forIdentifier: identifier) else {
            throw StoreError.typeUnavailable(definition.indicatorName)
        }
        let end = now()
        let predicate = lookback.predicate(endingAt: end, calendar: calendar)
        let sort = NSSortDescriptor(key: HKSampleSortIdentifierEndDate, ascending: false)
        return try await withCheckedThrowingContinuation { continuation in
            let query = HKSampleQuery(sampleType: quantityType, predicate: predicate, limit: 1, sortDescriptors: [sort]) { _, samples, error in
                if let error {
                    continuation.resume(throwing: error)
                    return
                }
                guard let sample = samples?.first as? HKQuantitySample else {
                    continuation.resume(returning: nil)
                    return
                }
                let value = sample.quantity.doubleValue(for: unit) * multiplier
                guard value.isFinite, value >= 0 else {
                    continuation.resume(returning: nil)
                    return
                }
                continuation.resume(returning: Self.sample(
                    definition: definition,
                    rawValue: value,
                    measuredAt: sample.endDate,
                    sourceID: sample.uuid.uuidString,
                    timeZone: self.calendar.timeZone
                ))
            }
            store.execute(query)
        }
    }

    private func categoryDurationToday(
        _ definition: AppleHealthMetricDefinition,
        identifier: HKCategoryTypeIdentifier
    ) async throws -> AppleHealthSyncSample? {
        guard let categoryType = HKCategoryType.categoryType(forIdentifier: identifier) else {
            throw StoreError.typeUnavailable(definition.indicatorName)
        }
        let end = now()
        let start = calendar.startOfDay(for: end)
        let predicate = HKQuery.predicateForSamples(withStart: start, end: end, options: .strictStartDate)
        return try await withCheckedThrowingContinuation { continuation in
            let query = HKSampleQuery(sampleType: categoryType, predicate: predicate, limit: HKObjectQueryNoLimit, sortDescriptors: nil) { _, samples, error in
                if let error {
                    continuation.resume(throwing: error)
                    return
                }
                let categories = samples as? [HKCategorySample] ?? []
                guard !categories.isEmpty else {
                    continuation.resume(returning: nil)
                    return
                }
                let seconds = Self.mergedSleepSeconds(categories.map { ($0.startDate, $0.endDate) })
                guard seconds > 0 else {
                    continuation.resume(returning: nil)
                    return
                }
                let minutes = seconds / 60
                continuation.resume(returning: Self.sample(
                    definition: definition,
                    rawValue: minutes,
                    measuredAt: categories.map(\.endDate).max() ?? end,
                    sourceID: Self.dayKey(for: start, timeZone: self.calendar.timeZone),
                    timeZone: self.calendar.timeZone
                ))
            }
            store.execute(query)
        }
    }

    private func sleepDuration(
        _ definition: AppleHealthMetricDefinition,
        asleep: Bool
    ) async throws -> AppleHealthSyncSample? {
        guard let categoryType = HKCategoryType.categoryType(forIdentifier: .sleepAnalysis) else {
            throw StoreError.typeUnavailable(definition.indicatorName)
        }
        let end = now()
        let start = calendar.date(byAdding: .hour, value: -36, to: end) ?? end.addingTimeInterval(-36 * 3600)
        let predicate = HKQuery.predicateForSamples(withStart: start, end: end, options: .strictEndDate)
        let sort = NSSortDescriptor(key: HKSampleSortIdentifierEndDate, ascending: false)
        return try await withCheckedThrowingContinuation { continuation in
            let query = HKSampleQuery(sampleType: categoryType, predicate: predicate, limit: HKObjectQueryNoLimit, sortDescriptors: [sort]) { _, samples, error in
                if let error {
                    continuation.resume(throwing: error)
                    return
                }
                let acceptedValues: Set<Int>
                if asleep {
                    acceptedValues = [
                        HKCategoryValueSleepAnalysis.asleepCore.rawValue,
                        HKCategoryValueSleepAnalysis.asleepDeep.rawValue,
                        HKCategoryValueSleepAnalysis.asleepREM.rawValue,
                        HKCategoryValueSleepAnalysis.asleepUnspecified.rawValue
                    ]
                } else {
                    acceptedValues = [HKCategoryValueSleepAnalysis.inBed.rawValue]
                }
                let categories = (samples as? [HKCategorySample] ?? [])
                    .filter { acceptedValues.contains($0.value) }
                let seconds = Self.mergedSleepSeconds(categories.map { ($0.startDate, $0.endDate) })
                guard seconds > 0 else {
                    continuation.resume(returning: nil)
                    return
                }
                let measuredAt = categories.map(\.endDate).max() ?? end
                continuation.resume(returning: Self.sample(
                    definition: definition,
                    rawValue: seconds / 3600,
                    measuredAt: measuredAt,
                    sourceID: Self.dayKey(for: measuredAt, timeZone: self.calendar.timeZone),
                    timeZone: self.calendar.timeZone
                ))
            }
            store.execute(query)
        }
    }

    private func latestCategory(
        _ definition: AppleHealthMetricDefinition,
        identifier: HKCategoryTypeIdentifier,
        lookback: AppleHealthMetricDefinition.Lookback
    ) async throws -> AppleHealthSyncSample? {
        guard let categoryType = HKCategoryType.categoryType(forIdentifier: identifier) else {
            throw StoreError.typeUnavailable(definition.indicatorName)
        }
        let end = now()
        let predicate = lookback.predicate(endingAt: end, calendar: calendar)
        let sort = NSSortDescriptor(key: HKSampleSortIdentifierEndDate, ascending: false)
        return try await withCheckedThrowingContinuation { continuation in
            let query = HKSampleQuery(sampleType: categoryType, predicate: predicate, limit: 1, sortDescriptors: [sort]) { _, samples, error in
                if let error {
                    continuation.resume(throwing: error)
                    return
                }
                guard let sample = samples?.first as? HKCategorySample else {
                    continuation.resume(returning: nil)
                    return
                }
                let rawValue = Double(sample.value)
                continuation.resume(returning: AppleHealthSyncSample(
                    id: Self.sourceID(metricID: definition.metricID, sampleUUID: sample.uuid),
                    metricID: definition.metricID,
                    indicatorName: definition.indicatorName,
                    value: rawValue,
                    unit: "",
                    measuredAt: sample.endDate,
                    displayValue: Self.categoryDisplayValue(metricID: definition.metricID, value: sample.value),
                    displayUnit: "",
                    subtitle: definition.subtitle,
                    valueKind: .category,
                    timeZone: self.calendar.timeZone
                ))
            }
            store.execute(query)
        }
    }

    private func noDataMessage(for definition: AppleHealthMetricDefinition) -> String {
        switch definition.query {
        case .cumulativeToday, .durationToday:
            return "今天没有可读样本，或当前账号未授权读取该指标"
        case .sleep:
            return "近 36 小时没有可读样本，或当前账号未授权读取该指标"
        case .latest(_, _, _, let lookback), .latestCategory(_, let lookback):
            return "\(lookback.noDataWindowDescription)没有可读样本，或当前账号未授权读取该指标"
        case .unsupported(let reason):
            return reason
        }
    }

    static let metricRegistry: [AppleHealthMetricDefinition] = [
        cumulative("steps", "步数", .stepCount, .count(), "步", "今日 Apple 健康步数"),
        cumulative("distance", "步行+跑步距离", .distanceWalkingRunning, .meterUnit(with: .kilo), "km", "今日步行和跑步距离"),
        cumulative("exerciseMinutes", "运动分钟", .appleExerciseTime, .minute(), "min", "今日锻炼分钟"),
        cumulative("activeMinutes", "活动分钟数", .appleMoveTime, .minute(), "min", "今日活动分钟"),
        cumulative("activeEnergy", "活动能量", .activeEnergyBurned, .kilocalorie(), "kcal", "今日活动能量消耗"),
        cumulative("basalEnergy", "静息能量", .basalEnergyBurned, .kilocalorie(), "kcal", "今日静息能量消耗"),
        cumulative("flights", "爬楼层数", .flightsClimbed, .count(), "层", "今日爬楼层数"),
        cumulative("cyclingDistance", "骑行距离", .distanceCycling, .meterUnit(with: .kilo), "km", "今日骑行距离"),
        cumulative("swimmingDistance", "游泳距离", .distanceSwimming, .meter(), "m", "今日游泳距离"),
        cumulative("swimmingStrokes", "划水次数", .swimmingStrokeCount, .count(), "次", "今日游泳划水次数"),
        cumulative("wheelchairDistance", "推轮椅距离", .distanceWheelchair, .meterUnit(with: .kilo), "km", "今日推轮椅距离"),
        latest("vo2Max", "心肺适能", .vo2Max, HKUnit(from: "ml/kg*min"), "ml/kg/min", "最近一次最大摄氧量", lookback: .days(365)),

        latest("bodyHeight", "身高", .height, .meterUnit(with: .centi), "cm", "最近一次身高", lookback: .allHistory),
        latest("bodyWeight", "体重", .bodyMass, .gramUnit(with: .kilo), "kg", "最近一次体重", lookback: .days(365)),
        latest("bodyMassIndex", "BMI", .bodyMassIndex, .count(), "", "最近一次 BMI", lookback: .allHistory),
        latest("bodyFat", "体脂率", .bodyFatPercentage, .percent(), "%", "最近一次体脂率", lookback: .days(365), multiplyBy: 100),
        latest("leanBodyMass", "瘦体重", .leanBodyMass, .gramUnit(with: .kilo), "kg", "最近一次瘦体重", lookback: .allHistory),
        latest("waistCircumference", "腰围", .waistCircumference, .meterUnit(with: .centi), "cm", "最近一次腰围", lookback: .allHistory),
        latest("bodyTemperature", "体温", .bodyTemperature, .degreeCelsius(), "°C", "最近一次体温", lookback: .days(14)),
        latest("basalBodyTemperature", "基础体温", .basalBodyTemperature, .degreeCelsius(), "°C", "最近一次基础体温", lookback: .days(14)),

        latest("heartRate", "心率", .heartRate, rateUnit, "bpm", "最近一次心率", lookback: .days(14)),
        latest("restingHeartRate", "静息心率", .restingHeartRate, rateUnit, "bpm", "最近一次静息心率", lookback: .days(14)),
        latest("walkingHeartRateAverage", "步行心率平均值", .walkingHeartRateAverage, rateUnit, "bpm", "最近一次步行心率平均值", lookback: .days(14)),
        latest("hrv", "心率变异性", .heartRateVariabilitySDNN, .secondUnit(with: .milli), "ms", "最近一次 HRV", lookback: .days(14)),
        latest("heartRateRecovery", "心率恢复", .heartRateRecoveryOneMinute, rateUnit, "bpm", "最近一次一分钟心率恢复", lookback: .days(14)),
        latest("systolicBloodPressure", "收缩压", .bloodPressureSystolic, .millimeterOfMercury(), "mmHg", "最近一次收缩压", lookback: .days(14)),
        latest("diastolicBloodPressure", "舒张压", .bloodPressureDiastolic, .millimeterOfMercury(), "mmHg", "最近一次舒张压", lookback: .days(14)),

        AppleHealthMetricDefinition(metricID: "sleep", indicatorName: "睡眠", displayUnit: "h", subtitle: "最近一晚 Apple 健康睡眠", query: .sleep(asleep: true)),
        unsupported("sleepScore", "睡眠评分", "HealthKit 在 iOS 17 没有统一的标准睡眠评分类型；不同设备算法不可当作同一指标。"),
        AppleHealthMetricDefinition(metricID: "timeInBed", indicatorName: "卧床时间", displayUnit: "h", subtitle: "近 36 小时卧床时间", query: .sleep(asleep: false)),
        latest("respiratoryRate", "呼吸频率", .respiratoryRate, rateUnit, "次/分", "最近一次呼吸频率", lookback: .days(14)),
        latest("bloodOxygen", "血氧", .oxygenSaturation, .percent(), "%", "最近一次血氧", lookback: .days(14), multiplyBy: 100),
        cumulative("inhalerUsage", "吸入器使用次数", .inhalerUsage, .count(), "次", "今日吸入器使用次数"),

        unsupported("glucose", "血糖波动", "HealthKit 提供单次血糖样本，但没有统一的 CGM 波动汇总类型；请使用血糖指标或服务端趋势计算。"),
        latest("bloodGlucose", "血糖", .bloodGlucose, bloodGlucoseUnit, "mmol/L", "最近一次血糖", lookback: .days(14)),
        cumulative("insulinDelivery", "胰岛素输注", .insulinDelivery, .internationalUnit(), "IU", "今日胰岛素输注"),
        cumulative("dietaryEnergy", "膳食能量", .dietaryEnergyConsumed, .kilocalorie(), "kcal", "今日膳食能量"),
        cumulative("dietaryWater", "水", .dietaryWater, .literUnit(with: .milli), "ml", "今日饮水量"),
        cumulative("dietaryCarbs", "碳水化合物", .dietaryCarbohydrates, .gram(), "g", "今日碳水化合物摄入"),
        cumulative("dietaryProtein", "蛋白质", .dietaryProtein, .gram(), "g", "今日蛋白质摄入"),
        cumulative("dietaryFat", "总脂肪", .dietaryFatTotal, .gram(), "g", "今日脂肪摄入"),
        cumulative("dietaryFiber", "膳食纤维", .dietaryFiber, .gram(), "g", "今日膳食纤维摄入"),
        cumulative("dietaryCaffeine", "咖啡因", .dietaryCaffeine, .gramUnit(with: .milli), "mg", "今日咖啡因摄入"),

        AppleHealthMetricDefinition(metricID: "mindfulMinutes", indicatorName: "正念分钟", displayUnit: "min", subtitle: "今日正念时长", query: .durationToday(.mindfulSession)),
        cumulative("daylight", "日照时间", .timeInDaylight, .minute(), "min", "今日日照时间"),
        latest("environmentalAudio", "环境噪声级别", .environmentalAudioExposure, .decibelAWeightedSoundPressureLevel(), "dB", "最近一次环境声音暴露", lookback: .days(14)),
        latest("headphoneAudio", "耳机音量", .headphoneAudioExposure, .decibelAWeightedSoundPressureLevel(), "dB", "最近一次耳机声音暴露", lookback: .days(14)),
        latest("uvExposure", "紫外线指数", .uvExposure, .count(), "", "最近一次紫外线暴露", lookback: .days(14)),

        latestCategory("menstrualFlow", "经期", .menstrualFlow, "最近一次经期流量记录", lookback: .days(365)),
        latestCategory("intermenstrualBleeding", "点滴出血", .intermenstrualBleeding, "最近一次点滴出血记录", lookback: .days(365)),
        latestCategory("cervicalMucus", "宫颈黏液质量", .cervicalMucusQuality, "最近一次宫颈黏液记录", lookback: .days(365)),
        latestCategory("ovulationTest", "排卵测试结果", .ovulationTestResult, "最近一次排卵测试", lookback: .days(365)),
        latestCategory("sexualActivity", "性活动", .sexualActivity, "最近一次性活动记录", lookback: .days(365)),
        unsupported("symptoms", "症状", "HealthKit 没有单一的“症状”聚合类型；每种症状都有独立类型，不能伪造为一个数值。")
    ]

    static let supportedMetricIDs = Set(metricRegistry.filter(\.isSupported).map(\.metricID))
    static let supportedIndicatorNames = Set(metricRegistry.filter(\.isSupported).map(\.indicatorName))
    static let supportedMetricIDByIndicatorName = Dictionary(
        uniqueKeysWithValues: metricRegistry
            .filter(\.isSupported)
            .map { ($0.indicatorName, $0.metricID) }
    )
    static let unsupportedMetricIDs = Set(metricRegistry.filter { !$0.isSupported }.map(\.metricID))

    static func metricID(forIndicatorName indicatorName: String) -> String? {
        supportedMetricIDByIndicatorName[indicatorName.trimmingCharacters(in: .whitespacesAndNewlines)]
    }

    private static let readTypes: Set<HKObjectType> = Set(metricRegistry.compactMap(\.objectType))
    private static let backgroundSampleTypes: Set<HKSampleType> = Set(readTypes.compactMap { $0 as? HKSampleType })
    private static let rateUnit = HKUnit.count().unitDivided(by: .minute())
    private static let bloodGlucoseUnit = HKUnit.moleUnit(with: .milli, molarMass: HKUnitMolarMassBloodGlucose).unitDivided(by: .liter())

    private static func cumulative(
        _ metricID: String,
        _ indicatorName: String,
        _ identifier: HKQuantityTypeIdentifier,
        _ unit: HKUnit,
        _ displayUnit: String,
        _ subtitle: String,
        multiplyBy: Double = 1
    ) -> AppleHealthMetricDefinition {
        AppleHealthMetricDefinition(
            metricID: metricID,
            indicatorName: indicatorName,
            displayUnit: displayUnit,
            subtitle: subtitle,
            query: .cumulativeToday(identifier, unit, multiplyBy: multiplyBy)
        )
    }

    private static func latest(
        _ metricID: String,
        _ indicatorName: String,
        _ identifier: HKQuantityTypeIdentifier,
        _ unit: HKUnit,
        _ displayUnit: String,
        _ subtitle: String,
        lookback: AppleHealthMetricDefinition.Lookback,
        multiplyBy: Double = 1
    ) -> AppleHealthMetricDefinition {
        AppleHealthMetricDefinition(
            metricID: metricID,
            indicatorName: indicatorName,
            displayUnit: displayUnit,
            subtitle: subtitle,
            query: .latest(identifier, unit, multiplyBy: multiplyBy, lookback: lookback)
        )
    }

    private static func latestCategory(
        _ metricID: String,
        _ indicatorName: String,
        _ identifier: HKCategoryTypeIdentifier,
        _ subtitle: String,
        lookback: AppleHealthMetricDefinition.Lookback
    ) -> AppleHealthMetricDefinition {
        AppleHealthMetricDefinition(
            metricID: metricID,
            indicatorName: indicatorName,
            displayUnit: "",
            subtitle: subtitle,
            query: .latestCategory(identifier, lookback: lookback)
        )
    }

    private static func unsupported(
        _ metricID: String,
        _ indicatorName: String,
        _ reason: String
    ) -> AppleHealthMetricDefinition {
        AppleHealthMetricDefinition(
            metricID: metricID,
            indicatorName: indicatorName,
            displayUnit: "",
            subtitle: reason,
            query: .unsupported(reason)
        )
    }

    private static func sample(
        definition: AppleHealthMetricDefinition,
        rawValue: Double,
        measuredAt: Date,
        sourceID: String,
        timeZone: TimeZone
    ) -> AppleHealthSyncSample {
        AppleHealthSyncSample(
            id: "\(definition.metricID)-\(sourceID)",
            metricID: definition.metricID,
            indicatorName: definition.indicatorName,
            value: serverValue(rawValue, displayUnit: definition.displayUnit),
            unit: definition.displayUnit,
            measuredAt: measuredAt,
            displayValue: displayValue(rawValue, displayUnit: definition.displayUnit),
            displayUnit: definition.displayUnit,
            subtitle: definition.subtitle,
            timeZone: timeZone
        )
    }

    static func sourceID(metricID: String, sampleUUID: UUID) -> String {
        "\(metricID)-\(sampleUUID.uuidString)"
    }

    private static func displayValue(_ value: Double, displayUnit: String) -> String {
        switch displayUnit {
        case "步", "kcal", "min", "层", "次", "ml", "m", "mg":
            return "\(Int(value.rounded()))"
        case "km", "kg", "h", "cm", "g", "IU", "mmol/L", "ml/kg/min", "°C", "dB":
            return String(format: "%.1f", value).replacingOccurrences(of: ".0", with: "")
        case "bpm", "ms", "%", "次/分":
            return value >= 100 ? "\(Int(value.rounded()))" : String(format: "%.1f", value).replacingOccurrences(of: ".0", with: "")
        case "mmHg":
            return "\(Int(value.rounded()))"
        default:
            return String(format: "%.1f", value).replacingOccurrences(of: ".0", with: "")
        }
    }

    private static func serverValue(_ value: Double, displayUnit: String) -> Double {
        switch displayUnit {
        case "步", "kcal", "min", "层", "次", "ml", "m", "mg":
            return value.rounded()
        case "mmHg":
            return value.rounded()
        case "km", "kg", "h", "cm", "g", "IU", "mmol/L", "ml/kg/min", "°C", "dB":
            return (value * 100).rounded() / 100
        default:
            return (value * 10).rounded() / 10
        }
    }

    static func categoryDisplayValue(metricID: String, value: Int) -> String {
        switch metricID {
        case "menstrualFlow":
            return [1: "未指定", 2: "少量", 3: "中等", 4: "大量", 5: "无"][value] ?? "记录值 \(value)"
        case "intermenstrualBleeding":
            return value == 0 ? "已记录" : "记录值 \(value)"
        case "cervicalMucus":
            return [1: "干燥", 2: "黏稠", 3: "乳霜状", 4: "水样", 5: "蛋清样"][value] ?? "记录值 \(value)"
        case "ovulationTest":
            return [1: "阴性", 2: "黄体生成素峰值", 3: "不确定", 4: "雌激素峰值"][value] ?? "记录值 \(value)"
        case "sexualActivity":
            return value == 0 ? "已记录" : "记录值 \(value)"
        default:
            return "记录值 \(value)"
        }
    }

    static func mergedSleepSeconds(_ intervals: [(Date, Date)]) -> Double {
        let sorted = intervals
            .filter { $0.1 > $0.0 }
            .sorted { $0.0 < $1.0 }
        guard var current = sorted.first else { return 0 }
        var total: TimeInterval = 0
        for interval in sorted.dropFirst() {
            if interval.0 <= current.1 {
                current.1 = max(current.1, interval.1)
            } else {
                total += current.1.timeIntervalSince(current.0)
                current = interval
            }
        }
        total += current.1.timeIntervalSince(current.0)
        return total
    }

    private static func dayKey(for date: Date, timeZone: TimeZone) -> String {
        let formatter = DateFormatter()
        formatter.calendar = Calendar(identifier: .gregorian)
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = timeZone
        formatter.dateFormat = "yyyyMMdd"
        return formatter.string(from: date)
    }
}

/// HealthKit can synchronously deliver a burst from several observer queries on a
/// non-main queue. Stage that burst before crossing to MainActor so executor
/// scheduling cannot split callbacks that were already waiting into extra reads.
/// A coordinator creates one inbox per observer registration; late callbacks from
/// an old account therefore cannot be batched with a newer registration.
private final class AppleHealthObserverEventInbox: @unchecked Sendable {
    private enum QuiescenceCheck {
        case empty
        case waiting(revision: UInt64)
        case ready(completions: [() -> Void])
    }

    /// Observer queries for several HealthKit types can wake together but reach
    /// this shared handler on different executor turns. Waiting for a short quiet
    /// period keeps that one system wake-up as one read, while the maximum wait
    /// still guarantees that completions are not held by a continuous stream.
    static let quietPeriodNanoseconds: UInt64 = 10_000_000
    static let maximumCoalescingNanoseconds: UInt64 = 50_000_000

    private let lock = NSLock()
    private var pendingCompletions: [() -> Void] = []
    private var deliveryScheduled = false
    private var enqueueRevision: UInt64 = 0

    func enqueue(
        completion: @escaping () -> Void,
        scheduleDelivery: () -> Void
    ) {
        lock.lock()
        pendingCompletions.append(completion)
        enqueueRevision &+= 1
        let shouldSchedule = !deliveryScheduled
        if shouldSchedule {
            deliveryScheduled = true
        }
        lock.unlock()

        if shouldSchedule {
            scheduleDelivery()
        }
    }

    /// Atomically takes the staged callbacks only after no new callback has
    /// arrived for one quiet period. The revision check and batch removal share
    /// the same lock so a callback cannot slip between the quiet decision and
    /// the take. This delay happens before MainActor delivery becomes a sync pass;
    /// callbacks delivered later during an active pass therefore still receive a
    /// newer coordinator sequence and force a fresh read.
    @MainActor
    func takeBatchAfterQuiescence() async -> [() -> Void] {
        let startedAt = DispatchTime.now().uptimeNanoseconds
        guard var observedRevision = beginQuiescence() else { return [] }

        while true {
            try? await Task.sleep(nanoseconds: Self.quietPeriodNanoseconds)

            let now = DispatchTime.now().uptimeNanoseconds
            switch checkQuiescence(
                after: observedRevision,
                forceTake: now &- startedAt >= Self.maximumCoalescingNanoseconds
            ) {
            case .empty:
                return []
            case .waiting(let revision):
                observedRevision = revision
            case .ready(let completions):
                return completions
            }
        }
    }

    private func beginQuiescence() -> UInt64? {
        lock.lock()
        defer { lock.unlock() }
        guard !pendingCompletions.isEmpty else {
            deliveryScheduled = false
            return nil
        }
        return enqueueRevision
    }

    private func checkQuiescence(
        after observedRevision: UInt64,
        forceTake: Bool
    ) -> QuiescenceCheck {
        lock.lock()
        defer { lock.unlock() }
        guard !pendingCompletions.isEmpty else {
            deliveryScheduled = false
            return .empty
        }
        guard enqueueRevision == observedRevision || forceTake else {
            return .waiting(revision: enqueueRevision)
        }
        let completions = pendingCompletions
        pendingCompletions = []
        deliveryScheduled = false
        return .ready(completions: completions)
    }

    func takeBatch() -> [() -> Void] {
        lock.lock()
        let batch = pendingCompletions
        pendingCompletions = []
        deliveryScheduled = false
        lock.unlock()
        return batch
    }

    func flush() {
        takeBatch().forEach { $0() }
    }
}

@MainActor
protocol AppleHealthBackgroundCoordinating: AnyObject {
    func enroll(accountScope: String)
    func startIfEligible(accountScope: String?)
    func stop()
    func performSync(
        accountScope: String,
        operation: @escaping @MainActor () async throws -> AppleHealthSyncExecution
    ) async throws -> AppleHealthSyncExecution
}

@MainActor
final class DisabledAppleHealthBackgroundCoordinator: AppleHealthBackgroundCoordinating {
    static let shared = DisabledAppleHealthBackgroundCoordinator()

    private init() {}

    func enroll(accountScope: String) {}
    func startIfEligible(accountScope: String?) {}
    func stop() {}

    func performSync(
        accountScope: String,
        operation: @escaping @MainActor () async throws -> AppleHealthSyncExecution
    ) async throws -> AppleHealthSyncExecution {
        try await operation()
    }
}

@MainActor
final class AppleHealthBackgroundSyncCoordinator: AppleHealthBackgroundCoordinating {
    static let shared = AppleHealthBackgroundSyncCoordinator()

    private struct ActiveOperation {
        let id: UUID
        let accountScope: String
        let task: Task<AppleHealthSyncExecution, Error>
    }

    private struct PendingObserverCompletion {
        let sequence: Int
        let completion: () -> Void
    }

    private let healthStore: AppleHealthBackgroundStoreProtocol
    private let api: APIServiceProtocol
    private let userDefaults: UserDefaults
    private let now: () -> Date
    private let currentAccountScope: @MainActor () -> String?
    /// Deterministic scheduling hook for the finish-window regression test.
    /// Production uses the no-op default.
    private let beforeObserverDrainFinish: @MainActor () async -> Void
    private let launchArguments: () -> [String]
    private var activeAccountScope: String?
    private var generation = 0
    private var lifecycleTask: Task<Void, Never>?
    private var activeOperation: ActiveOperation?
    private var observerEventInbox: AppleHealthObserverEventInbox?
    private var observerEventSequence = 0
    private var pendingObserverCompletions: [PendingObserverCompletion] = []
    private var observerDrainID: UUID?
    private var observerDrainTask: Task<Void, Never>?
    private(set) var lastBackgroundDeliveryResult: AppleHealthBackgroundDeliveryResult?

    init(
        healthStore: AppleHealthBackgroundStoreProtocol = AppleHealthStore(),
        api: APIServiceProtocol = APIService.shared,
        userDefaults: UserDefaults = .standard,
        now: @escaping () -> Date = Date.init,
        currentAccountScope: @escaping @MainActor () -> String? = { AuthManager.shared.accountScope },
        beforeObserverDrainFinish: @escaping @MainActor () async -> Void = {},
        launchArguments: @escaping () -> [String] = { ProcessInfo.processInfo.arguments }
    ) {
        self.healthStore = healthStore
        self.api = api
        self.userDefaults = userDefaults
        self.now = now
        self.currentAccountScope = currentAccountScope
        self.beforeObserverDrainFinish = beforeObserverDrainFinish
        self.launchArguments = launchArguments
        // This marker pre-dated account isolation and must never enroll whichever
        // user happens to be logged in when the upgraded app first starts.
        userDefaults.removeObject(forKey: "xage.appleHealth.lastSyncedAt")
    }

    func enroll(accountScope: String) {
        guard shouldUseHealthKit else { return }
        guard !accountScope.isEmpty else { return }
        userDefaults.set(true, forKey: Self.enrollmentKey(for: accountScope))
    }

    func startIfEligible(accountScope: String?) {
        guard shouldUseHealthKit else {
            stopWithoutAccessingHealthStore()
            return
        }
        guard let accountScope, !accountScope.isEmpty else {
            stop()
            return
        }
        let explicitlyEnrolled = userDefaults.bool(forKey: Self.enrollmentKey(for: accountScope))
        let hasScopedSync = userDefaults.object(forKey: Self.lastSyncedAtKey(for: accountScope)) as? Date != nil
        guard explicitlyEnrolled || hasScopedSync else {
            stop()
            return
        }
        if hasScopedSync, !explicitlyEnrolled {
            // A scoped marker can only have been written after this account's own
            // manual sync. Promote it to the explicit observer enrollment marker.
            userDefaults.set(true, forKey: Self.enrollmentKey(for: accountScope))
        }
        guard activeAccountScope != accountScope else { return }

        cancelObserverDrainAndFlushCompletions()
        activeOperation?.task.cancel()
        activeOperation = nil
        healthStore.stopObserverQueries()
        activeAccountScope = accountScope
        generation += 1
        scheduleObserverTransition(accountScope: accountScope, generation: generation)
    }

    func stop() {
        guard shouldUseHealthKit else {
            stopWithoutAccessingHealthStore()
            return
        }
        activeAccountScope = nil
        generation += 1
        cancelObserverDrainAndFlushCompletions()
        activeOperation?.task.cancel()
        activeOperation = nil
        lastBackgroundDeliveryResult = nil
        // Stop in-process callbacks synchronously before any asynchronous cleanup.
        healthStore.stopObserverQueries()
        scheduleObserverTransition(accountScope: nil, generation: generation)
    }

    func performSync(
        accountScope: String,
        operation: @escaping @MainActor () async throws -> AppleHealthSyncExecution
    ) async throws -> AppleHealthSyncExecution {
        guard shouldUseHealthKit else {
            return AppleHealthSyncExecution(readResult: .empty, response: nil)
        }
        if let activeOperation, activeOperation.accountScope == accountScope {
            return try await activeOperation.task.value
        }
        if let activeOperation {
            activeOperation.task.cancel()
            self.activeOperation = nil
        }

        let operationID = UUID()
        let task = Task { @MainActor [weak self] in
            defer { self?.clearActiveOperation(id: operationID) }
            try Task.checkCancellation()
            return try await operation()
        }
        activeOperation = ActiveOperation(id: operationID, accountScope: accountScope, task: task)
        return try await task.value
    }

    private func clearActiveOperation(id: UUID) {
        guard activeOperation?.id == id else { return }
        activeOperation = nil
    }

    private var shouldUseHealthKit: Bool {
        AppleHealthSyncViewModel.shouldUseHealthKit(arguments: launchArguments())
    }

    private func stopWithoutAccessingHealthStore() {
        activeAccountScope = nil
        generation += 1
        lifecycleTask?.cancel()
        lifecycleTask = nil
        cancelObserverDrainAndFlushCompletions()
        activeOperation?.task.cancel()
        activeOperation = nil
        lastBackgroundDeliveryResult = nil
    }

    private func scheduleObserverTransition(accountScope: String?, generation: Int) {
        let previous = lifecycleTask
        previous?.cancel()
        lifecycleTask = Task { @MainActor [weak self] in
            if let previous { _ = await previous.result }
            guard let self else { return }

            self.healthStore.stopObserverQueries()
            _ = await self.healthStore.disableBackgroundDelivery()
            guard !Task.isCancelled,
                  let accountScope,
                  self.activeAccountScope == accountScope,
                  self.generation == generation,
                  self.currentAccountScope() == accountScope else { return }

            let eventInbox = AppleHealthObserverEventInbox()
            self.observerEventInbox = eventInbox
            self.healthStore.startObserverQueries { [weak self] completion in
                eventInbox.enqueue(completion: completion) {
                    Task { @MainActor in
                        guard let self else {
                            eventInbox.flush()
                            return
                        }
                        await self.deliverObserverBatch(
                            from: eventInbox,
                            accountScope: accountScope,
                            generation: generation
                        )
                    }
                }
            }
            let deliveryResult = await self.healthStore.enableBackgroundDelivery()
            guard !Task.isCancelled,
                  self.activeAccountScope == accountScope,
                  self.generation == generation,
                  self.currentAccountScope() == accountScope else {
                self.healthStore.stopObserverQueries()
                self.cancelObserverDrainAndFlushCompletions()
                _ = await self.healthStore.disableBackgroundDelivery()
                return
            }
            self.lastBackgroundDeliveryResult = deliveryResult
            if deliveryResult.allFailed {
                AppLogger.data.error("All HealthKit background delivery registrations failed; observer queries stopped")
                self.healthStore.stopObserverQueries()
                if self.activeAccountScope == accountScope, self.generation == generation {
                    self.activeAccountScope = nil
                }
                self.cancelObserverDrainAndFlushCompletions()
            }
        }
    }

    private func deliverObserverBatch(
        from eventInbox: AppleHealthObserverEventInbox,
        accountScope: String,
        generation: Int
    ) async {
        let completions = await eventInbox.takeBatchAfterQuiescence()
        guard !completions.isEmpty else { return }
        guard observerEventInbox === eventInbox,
              isCurrent(accountScope: accountScope, generation: generation) else {
            completions.forEach { $0() }
            return
        }

        for completion in completions {
            observerEventSequence += 1
            pendingObserverCompletions.append(PendingObserverCompletion(
                sequence: observerEventSequence,
                completion: completion
            ))
        }
        startObserverDrainIfNeeded(accountScope: accountScope, generation: generation)
    }

    private func startObserverDrainIfNeeded(accountScope: String, generation: Int) {
        guard observerDrainTask == nil, !pendingObserverCompletions.isEmpty else { return }

        let drainID = UUID()
        observerDrainID = drainID
        observerDrainTask = Task { @MainActor [weak self] in
            guard let self else { return }
            await self.drainObserverUpdates(
                accountScope: accountScope,
                generation: generation
            )
            if !Task.isCancelled {
                await self.beforeObserverDrainFinish()
            }
            self.finishObserverDrain(
                id: drainID,
                accountScope: accountScope,
                generation: generation
            )
        }
    }

    private func drainObserverUpdates(accountScope: String, generation: Int) async {
        // If a foreground/manual sync was already running when the HealthKit event
        // arrived, merely joining that operation is unsafe: its read may predate the
        // new sample. Wait for it, then always run a fresh observer pass.
        if let waitedOperation = activeOperation {
            _ = await waitedOperation.task.result
            // The original performSync caller can be queued behind this drain on the
            // MainActor. Clear the completed operation here as well so the mandatory
            // fresh observer pass cannot accidentally rejoin its stale result.
            clearActiveOperation(id: waitedOperation.id)
        }

        while !Task.isCancelled {
            guard isCurrent(accountScope: accountScope, generation: generation) else {
                flushObserverCompletions()
                return
            }
            guard !pendingObserverCompletions.isEmpty else { return }

            // Every event already queued at pass start is covered by this pass. Events
            // arriving while it runs receive a larger sequence and force one more pass,
            // coalescing an arbitrary callback burst without dropping the newest sample.
            let coveredThrough = observerEventSequence
            await performObserverSyncPass(accountScope: accountScope, generation: generation)

            guard !Task.isCancelled,
                  isCurrent(accountScope: accountScope, generation: generation) else {
                flushObserverCompletions()
                return
            }
            completeObserverEvents(through: coveredThrough)
        }
    }

    private func performObserverSyncPass(accountScope: String, generation: Int) async {
        do {
            let execution = try await performSync(accountScope: accountScope) { [weak self] in
                guard let self,
                      self.isCurrent(accountScope: accountScope, generation: generation) else {
                    throw APIError.accountScopeChanged
                }
                let readResult = try await self.healthStore.readDailySamples()
                guard self.isCurrent(accountScope: accountScope, generation: generation) else {
                    throw APIError.accountScopeChanged
                }
                guard !readResult.samples.isEmpty else {
                    return AppleHealthSyncExecution(readResult: readResult, response: nil)
                }
                let response: DeviceIndicatorSyncResponse = try await self.api.postAccountBound(
                    "/api/health-data/indicators/device-sync",
                    body: AppleHealthSyncPayloadBuilder.request(samples: readResult.samples),
                    expectedAccountScope: accountScope,
                    timeout: nil
                )
                guard self.isCurrent(accountScope: accountScope, generation: generation) else {
                    throw APIError.accountScopeChanged
                }
                return AppleHealthSyncExecution(readResult: readResult, response: response)
            }
            guard isCurrent(accountScope: accountScope, generation: generation) else { return }
            if let response = execution.response,
               response.written + response.unchangedCount > 0 {
                userDefaults.set(now(), forKey: Self.lastSyncedAtKey(for: accountScope))
            }
        } catch {
            // Observer delivery is best-effort. The drain still completes the event
            // after this attempted pass; the next HealthKit event retries safely.
        }
    }

    private func completeObserverEvents(through sequence: Int) {
        var completions: [() -> Void] = []
        var remaining: [PendingObserverCompletion] = []
        for pending in pendingObserverCompletions {
            if pending.sequence <= sequence {
                completions.append(pending.completion)
            } else {
                remaining.append(pending)
            }
        }
        pendingObserverCompletions = remaining
        completions.forEach { $0() }
    }

    private func flushObserverCompletions() {
        let completions = pendingObserverCompletions.map(\.completion)
        pendingObserverCompletions = []
        completions.forEach { $0() }
    }

    private func cancelObserverDrainAndFlushCompletions() {
        observerDrainTask?.cancel()
        observerDrainTask = nil
        observerDrainID = nil
        let eventInbox = observerEventInbox
        observerEventInbox = nil
        eventInbox?.flush()
        flushObserverCompletions()
    }

    private func finishObserverDrain(
        id: UUID,
        accountScope: String,
        generation: Int
    ) {
        guard observerDrainID == id else { return }
        observerDrainTask = nil
        observerDrainID = nil
        guard !pendingObserverCompletions.isEmpty else { return }
        guard isCurrent(accountScope: accountScope, generation: generation) else {
            flushObserverCompletions()
            return
        }
        // Close the return-to-finish scheduling window: an event may have been queued
        // after drainObserverUpdates observed an empty queue but before this caller
        // resumed. Restart synchronously while still on MainActor.
        startObserverDrainIfNeeded(accountScope: accountScope, generation: generation)
    }

    private func isCurrent(accountScope: String, generation: Int) -> Bool {
        activeAccountScope == accountScope
            && self.generation == generation
            && currentAccountScope() == accountScope
    }

    func waitForLifecycleTransition() async {
        if let lifecycleTask { _ = await lifecycleTask.result }
    }

    static func enrollmentKey(for accountScope: String) -> String {
        "xage.appleHealth.backgroundEnrollment.\(storageToken(for: accountScope))"
    }

    static func lastSyncedAtKey(for accountScope: String) -> String {
        "xage.appleHealth.lastSyncedAt.\(storageToken(for: accountScope))"
    }

    private static func storageToken(for accountScope: String) -> String {
        Data(accountScope.utf8).base64EncodedString()
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "=", with: "")
    }
}
