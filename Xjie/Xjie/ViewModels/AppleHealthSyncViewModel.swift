import Foundation
import HealthKit
import SwiftUI

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
}

struct DeviceIndicatorSyncValue: Encodable {
    let indicator_name: String
    let value: Double
    let unit: String?
    let measured_at: String
    let source_metric: String?
    let source_id: String?
    let notes: String?
}

struct DeviceIndicatorSyncRequest: Encodable {
    let source: String
    let values: [DeviceIndicatorSyncValue]
}

struct DeviceIndicatorSyncResponse: Codable, Equatable {
    let total: Int
    let inserted: Int
    let updated: Int
    let skipped: Int
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
        case failed(String)
    }

    @Published var status: Status = .idle
    @Published var samples: [AppleHealthSyncSample] = []
    @Published var syncResponse: DeviceIndicatorSyncResponse?
    @Published var lastSyncedAt: Date?

    private let api: APIServiceProtocol
    private let healthStore: AppleHealthStoreProtocol
    private let isoFormatter: ISO8601DateFormatter
    private let syncedAtKey = "xage.appleHealth.lastSyncedAt"

    init(
        api: APIServiceProtocol = APIService.shared,
        healthStore: AppleHealthStoreProtocol = AppleHealthStore()
    ) {
        self.api = api
        self.healthStore = healthStore
        self.isoFormatter = ISO8601DateFormatter()
        self.isoFormatter.formatOptions = [.withInternetDateTime]
        if let saved = UserDefaults.standard.object(forKey: syncedAtKey) as? Date {
            self.lastSyncedAt = saved
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
            return "同步完成"
        case .failed:
            return "同步失败"
        }
    }

    var statusSubtitle: String {
        switch status {
        case .idle:
            if let lastSyncedAt {
                return "上次 \(Self.relativeFormatter.localizedString(for: lastSyncedAt, relativeTo: Date()))，可手动刷新最新数据。"
            }
            return "授权后读取步数、睡眠、HRV、静息心率等，并写入你的服务器指标趋势。"
        case .unavailable:
            return "当前设备或模拟器未开放 Apple 健康数据。"
        case .requesting:
            return "系统会弹出 Apple 健康权限，只读取你勾选的数据。"
        case .reading:
            return "正在汇总今日累计值和最近一次测量值。"
        case .syncing:
            return "正在把 \(samples.count) 项指标写入服务器。"
        case .synced:
            guard let syncResponse else { return "用户端已更新为最新同步值。" }
            return "服务器新增 \(syncResponse.inserted) 项，更新 \(syncResponse.updated) 项；用户端数据卡已刷新。"
        case .failed(let message):
            return message
        }
    }

    func requestAccessAndSync() async {
        guard healthStore.isHealthDataAvailable else {
            status = .unavailable
            return
        }

        status = .requesting
        do {
            try await healthStore.requestAuthorization()
        } catch {
            status = .failed("未获得 Apple 健康访问权限：\(error.localizedDescription)")
            return
        }

        await refreshAndSync()
    }

    func refreshIfPreviouslySynced() async {
        guard lastSyncedAt != nil, !isWorking else { return }
        await refreshAndSync()
    }

    func refreshAndSync() async {
        guard healthStore.isHealthDataAvailable else {
            status = .unavailable
            return
        }

        status = .reading
        do {
            let loaded = try await healthStore.readDailySamples()
            samples = loaded
            guard !loaded.isEmpty else {
                status = .failed("Apple 健康中暂无可同步的今日或最近指标。")
                return
            }

            status = .syncing
            let body = DeviceIndicatorSyncRequest(
                source: "apple_health",
                values: loaded.map(syncValue(from:))
            )
            let response: DeviceIndicatorSyncResponse = try await api.post(
                "/api/health-data/indicators/device-sync",
                body: body,
                timeout: nil
            )
            syncResponse = response
            let now = Date()
            lastSyncedAt = now
            UserDefaults.standard.set(now, forKey: syncedAtKey)
            status = .synced
        } catch {
            status = .failed(error.localizedDescription)
        }
    }

    private func syncValue(from sample: AppleHealthSyncSample) -> DeviceIndicatorSyncValue {
        DeviceIndicatorSyncValue(
            indicator_name: sample.indicatorName,
            value: sample.value,
            unit: sample.unit.isEmpty ? nil : sample.unit,
            measured_at: isoFormatter.string(from: sample.measuredAt),
            source_metric: sample.metricID,
            source_id: sample.id,
            notes: "Apple Health 同步"
        )
    }

    private static let relativeFormatter: RelativeDateTimeFormatter = {
        let formatter = RelativeDateTimeFormatter()
        formatter.unitsStyle = .short
        return formatter
    }()
}

protocol AppleHealthStoreProtocol {
    var isHealthDataAvailable: Bool { get }
    func requestAuthorization() async throws
    func readDailySamples() async throws -> [AppleHealthSyncSample]
}

final class AppleHealthStore: AppleHealthStoreProtocol {
    private let store = HKHealthStore()
    private let calendar = Calendar.current

    var isHealthDataAvailable: Bool {
        HKHealthStore.isHealthDataAvailable()
    }

    func requestAuthorization() async throws {
        try await store.requestAuthorization(toShare: Set<HKSampleType>(), read: Self.readTypes)
    }

    func readDailySamples() async throws -> [AppleHealthSyncSample] {
        async let steps = try? cumulative(.stepCount, metricID: "steps", indicatorName: "步数", unit: .count(), displayUnit: "步", subtitle: "今日 Apple 健康步数")
        async let distance = try? cumulative(.distanceWalkingRunning, metricID: "distance", indicatorName: "步行+跑步距离", unit: .meterUnit(with: .kilo), displayUnit: "km", subtitle: "今日步行和跑步距离")
        async let energy = try? cumulative(.activeEnergyBurned, metricID: "activeEnergy", indicatorName: "活动能量", unit: .kilocalorie(), displayUnit: "kcal", subtitle: "今日活动能量消耗")
        async let exercise = try? cumulative(.appleExerciseTime, metricID: "exerciseMinutes", indicatorName: "运动分钟", unit: .minute(), displayUnit: "min", subtitle: "今日运动分钟")
        async let flights = try? cumulative(.flightsClimbed, metricID: "flights", indicatorName: "爬楼层数", unit: .count(), displayUnit: "层", subtitle: "今日爬楼层数")
        async let hrv = try? latest(.heartRateVariabilitySDNN, metricID: "hrv", indicatorName: "心率变异性", unit: .secondUnit(with: .milli), displayUnit: "ms", subtitle: "最近一次 HRV")
        async let restingHeartRate = try? latest(.restingHeartRate, metricID: "restingHeartRate", indicatorName: "静息心率", unit: HKUnit.count().unitDivided(by: .minute()), displayUnit: "bpm", subtitle: "最近一次静息心率")
        async let respiratoryRate = try? latest(.respiratoryRate, metricID: "respiratoryRate", indicatorName: "呼吸频率", unit: HKUnit.count().unitDivided(by: .minute()), displayUnit: "次/分", subtitle: "最近一次呼吸频率")
        async let oxygen = try? latest(.oxygenSaturation, metricID: "bloodOxygen", indicatorName: "血氧", unit: .percent(), displayUnit: "%", subtitle: "最近一次血氧")
        async let systolic = try? latest(.bloodPressureSystolic, metricID: "systolicBloodPressure", indicatorName: "收缩压", unit: .millimeterOfMercury(), displayUnit: "mmHg", subtitle: "最近一次收缩压")
        async let diastolic = try? latest(.bloodPressureDiastolic, metricID: "diastolicBloodPressure", indicatorName: "舒张压", unit: .millimeterOfMercury(), displayUnit: "mmHg", subtitle: "最近一次舒张压")
        async let weight = try? latest(.bodyMass, metricID: "bodyWeight", indicatorName: "体重", unit: .gramUnit(with: .kilo), displayUnit: "kg", subtitle: "最近一次体重")
        async let bodyFat = try? latest(.bodyFatPercentage, metricID: "bodyFat", indicatorName: "体脂率", unit: .percent(), displayUnit: "%", subtitle: "最近一次体脂率")
        async let sleep = try? sleepDuration()

        let optionals = await [
            steps, distance, energy, exercise, flights, hrv, restingHeartRate,
            respiratoryRate, oxygen, systolic, diastolic, weight, bodyFat, sleep
        ]
        return optionals.compactMap { $0 }
    }

    private func cumulative(
        _ identifier: HKQuantityTypeIdentifier,
        metricID: String,
        indicatorName: String,
        unit: HKUnit,
        displayUnit: String,
        subtitle: String
    ) async throws -> AppleHealthSyncSample? {
        guard let quantityType = HKQuantityType.quantityType(forIdentifier: identifier) else { return nil }
        let start = calendar.startOfDay(for: Date())
        let predicate = HKQuery.predicateForSamples(withStart: start, end: Date(), options: .strictStartDate)
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
                let value = quantity.doubleValue(for: unit)
                guard value.isFinite, value > 0 else {
                    continuation.resume(returning: nil)
                    return
                }
                continuation.resume(returning: AppleHealthSyncSample(
                    id: "\(metricID)-\(Self.dayKey(for: start))",
                    metricID: metricID,
                    indicatorName: indicatorName,
                    value: Self.serverValue(value, displayUnit: displayUnit),
                    unit: displayUnit,
                    measuredAt: Date(),
                    displayValue: Self.displayValue(value, displayUnit: displayUnit),
                    displayUnit: displayUnit,
                    subtitle: subtitle
                ))
            }
            store.execute(query)
        }
    }

    private func latest(
        _ identifier: HKQuantityTypeIdentifier,
        metricID: String,
        indicatorName: String,
        unit: HKUnit,
        displayUnit: String,
        subtitle: String
    ) async throws -> AppleHealthSyncSample? {
        guard let quantityType = HKQuantityType.quantityType(forIdentifier: identifier) else { return nil }
        let start = calendar.date(byAdding: .day, value: -14, to: Date()) ?? Date().addingTimeInterval(-14 * 24 * 3600)
        let predicate = HKQuery.predicateForSamples(withStart: start, end: Date(), options: .strictEndDate)
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
                let rawValue = sample.quantity.doubleValue(for: unit)
                let value = displayUnit == "%" ? rawValue * 100 : rawValue
                guard value.isFinite, value > 0 else {
                    continuation.resume(returning: nil)
                    return
                }
                continuation.resume(returning: AppleHealthSyncSample(
                    id: "\(metricID)-\(Int(sample.endDate.timeIntervalSince1970))",
                    metricID: metricID,
                    indicatorName: indicatorName,
                    value: Self.serverValue(value, displayUnit: displayUnit),
                    unit: displayUnit,
                    measuredAt: sample.endDate,
                    displayValue: Self.displayValue(value, displayUnit: displayUnit),
                    displayUnit: displayUnit,
                    subtitle: subtitle
                ))
            }
            store.execute(query)
        }
    }

    private func sleepDuration() async throws -> AppleHealthSyncSample? {
        guard let categoryType = HKCategoryType.categoryType(forIdentifier: .sleepAnalysis) else { return nil }
        let end = Date()
        let start = calendar.date(byAdding: .hour, value: -36, to: end) ?? end.addingTimeInterval(-36 * 3600)
        let predicate = HKQuery.predicateForSamples(withStart: start, end: end, options: .strictEndDate)
        let sort = NSSortDescriptor(key: HKSampleSortIdentifierEndDate, ascending: false)
        return try await withCheckedThrowingContinuation { continuation in
            let query = HKSampleQuery(sampleType: categoryType, predicate: predicate, limit: HKObjectQueryNoLimit, sortDescriptors: [sort]) { _, samples, error in
                if let error {
                    continuation.resume(throwing: error)
                    return
                }
                let asleepValues = Set([
                    HKCategoryValueSleepAnalysis.asleepCore.rawValue,
                    HKCategoryValueSleepAnalysis.asleepDeep.rawValue,
                    HKCategoryValueSleepAnalysis.asleepREM.rawValue,
                    HKCategoryValueSleepAnalysis.asleepUnspecified.rawValue
                ])
                let seconds = (samples as? [HKCategorySample] ?? [])
                    .filter { asleepValues.contains($0.value) }
                    .reduce(0.0) { $0 + $1.endDate.timeIntervalSince($1.startDate) }
                guard seconds > 0 else {
                    continuation.resume(returning: nil)
                    return
                }
                let hours = seconds / 3600
                continuation.resume(returning: AppleHealthSyncSample(
                    id: "sleep-\(Self.dayKey(for: end))",
                    metricID: "sleep",
                    indicatorName: "睡眠",
                    value: (hours * 100).rounded() / 100,
                    unit: "h",
                    measuredAt: end,
                    displayValue: Self.displayValue(hours, displayUnit: "h"),
                    displayUnit: "",
                    subtitle: "最近一晚 Apple 健康睡眠"
                ))
            }
            store.execute(query)
        }
    }

    private static let readTypes: Set<HKObjectType> = {
        var types: Set<HKObjectType> = []
        [
            HKQuantityTypeIdentifier.stepCount,
            .distanceWalkingRunning,
            .activeEnergyBurned,
            .appleExerciseTime,
            .flightsClimbed,
            .heartRateVariabilitySDNN,
            .restingHeartRate,
            .respiratoryRate,
            .oxygenSaturation,
            .bloodPressureSystolic,
            .bloodPressureDiastolic,
            .bodyMass,
            .bodyFatPercentage
        ].compactMap { HKQuantityType.quantityType(forIdentifier: $0) }.forEach { types.insert($0) }
        if let sleep = HKCategoryType.categoryType(forIdentifier: .sleepAnalysis) {
            types.insert(sleep)
        }
        return types
    }()

    private static func displayValue(_ value: Double, displayUnit: String) -> String {
        switch displayUnit {
        case "步", "kcal", "min", "层":
            return "\(Int(value.rounded()))"
        case "km", "kg", "h":
            return String(format: "%.1f", value)
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
        case "步", "kcal", "min", "层":
            return value.rounded()
        case "km", "kg", "h":
            return (value * 100).rounded() / 100
        case "mmHg":
            return value.rounded()
        default:
            return (value * 10).rounded() / 10
        }
    }

    private static func dayKey(for date: Date) -> String {
        let formatter = DateFormatter()
        formatter.calendar = Calendar(identifier: .gregorian)
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyyMMdd"
        return formatter.string(from: date)
    }
}
