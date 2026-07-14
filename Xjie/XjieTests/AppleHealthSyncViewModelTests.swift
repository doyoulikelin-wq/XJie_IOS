import Foundation
import SwiftUI
import XCTest
@testable import Xjie

@MainActor
final class AppleHealthSyncViewModelTests: XCTestCase {
    func testUnitTestHostNeverAutoStartsRealAppleHealthBackgroundSync() {
        XCTAssertNotNil(NSClassFromString("XCTestCase"))
        XCTAssertFalse(AppDelegate.shouldStartAppleHealthBackgroundSync)
    }

    func testRequestAccessAndSyncPostsDeviceIndicatorBatch() async throws {
        let mock = MockAPIService()
        let response = DeviceIndicatorSyncResponse(total: 1, inserted: 1, updated: 0, skipped: 0)
        try await mock.setResponse(for: "/api/health-data/indicators/device-sync", value: response)

        let sample = AppleHealthSyncSample(
            id: "steps-20260702",
            metricID: "steps",
            indicatorName: "步数",
            value: 8240,
            unit: "步",
            measuredAt: Date(timeIntervalSince1970: 1_783_008_000),
            displayValue: "8240",
            displayUnit: "步",
            subtitle: "今日 Apple 健康步数",
            sourceLocalDate: "2026-07-02",
            timezoneOffsetMinutes: 480
        )
        let healthStore = FakeAppleHealthStore(samples: [sample])
        let vm = AppleHealthSyncViewModel(
            api: mock,
            healthStore: healthStore,
            userDefaults: makeUserDefaults(),
            accountScope: "user-a"
        )

        await vm.requestAccessAndSync()

        let paths = await mock.getRequestedPaths()
        XCTAssertEqual(paths, ["/api/health-data/indicators/device-sync"])
        let accountScopes = await mock.requestedAccountScopes
        XCTAssertEqual(accountScopes, ["user-a"])
        XCTAssertEqual(vm.samples, [sample])
        XCTAssertEqual(vm.syncResponse, response)
        XCTAssertEqual(vm.status, .synced)

        let body = await mock.requestBodyJSON(for: "/api/health-data/indicators/device-sync")
        let values = try XCTUnwrap(body?["values"] as? [[String: Any]])
        let uploaded = try XCTUnwrap(values.first)
        XCTAssertEqual(uploaded["value_kind"] as? String, "numeric")
        XCTAssertEqual(uploaded["display_value"] as? String, "8240")
        XCTAssertEqual(uploaded["source_local_date"] as? String, "2026-07-02")
        XCTAssertEqual(uploaded["timezone_offset_minutes"] as? Int, 480)
        XCTAssertEqual(uploaded["source_metric"] as? String, "steps")
        XCTAssertEqual(uploaded["source_id"] as? String, "steps-20260702")
    }

    func testCategoryPayloadKeepsRawValueAndChineseDisplayLabel() async throws {
        let mock = MockAPIService()
        try await mock.setResponse(
            for: "/api/health-data/indicators/device-sync",
            value: DeviceIndicatorSyncResponse(total: 1, inserted: 1, updated: 0, skipped: 0)
        )
        let sample = AppleHealthSyncSample(
            id: "menstrualFlow-category-sample",
            metricID: "menstrualFlow",
            indicatorName: "经期",
            value: 3,
            unit: "",
            measuredAt: Date(timeIntervalSince1970: 1_783_008_000),
            displayValue: "中等",
            displayUnit: "",
            subtitle: "最近一次经期流量记录",
            valueKind: .category,
            sourceLocalDate: "2026-07-02",
            timezoneOffsetMinutes: 480
        )
        let vm = AppleHealthSyncViewModel(
            api: mock,
            healthStore: FakeAppleHealthStore(samples: [sample]),
            userDefaults: makeUserDefaults(),
            accountScope: "user-a"
        )

        await vm.requestAccessAndSync()

        let body = await mock.requestBodyJSON(for: "/api/health-data/indicators/device-sync")
        let values = try XCTUnwrap(body?["values"] as? [[String: Any]])
        let uploaded = try XCTUnwrap(values.first)
        XCTAssertEqual(uploaded["value_kind"] as? String, "category")
        XCTAssertEqual(uploaded["value"] as? Double, 3)
        XCTAssertEqual(uploaded["display_value"] as? String, "中等")
        XCTAssertEqual(uploaded["source_local_date"] as? String, "2026-07-02")
        XCTAssertEqual(uploaded["timezone_offset_minutes"] as? Int, 480)
    }

    func testUnavailableHealthStoreDoesNotCallAPI() async throws {
        let mock = MockAPIService()
        let healthStore = FakeAppleHealthStore(isHealthDataAvailable: false, samples: [])
        let vm = AppleHealthSyncViewModel(
            api: mock,
            healthStore: healthStore,
            userDefaults: makeUserDefaults(),
            accountScope: "user-a"
        )

        await vm.requestAccessAndSync()

        let paths = await mock.getRequestedPaths()
        XCTAssertEqual(paths, [])
        XCTAssertEqual(vm.status, .unavailable)
    }

    func testMergedSleepSecondsDoesNotDoubleCountOverlaps() {
        let base = Date(timeIntervalSince1970: 1_783_008_000)
        let intervals = [
            (base, base.addingTimeInterval(2 * 3600)),
            (base.addingTimeInterval(3600), base.addingTimeInterval(3 * 3600)),
            (base.addingTimeInterval(4 * 3600), base.addingTimeInterval(5 * 3600))
        ]

        let seconds = AppleHealthStore.mergedSleepSeconds(intervals)

        XCTAssertEqual(seconds, 4 * 3600, accuracy: 0.01)
    }

    func testRegistryCoversEveryCatalogMetricAndExplicitlyMarksNonStandardTypes() {
        let catalogIDs: Set<String> = [
            "steps", "distance", "exerciseMinutes", "activeMinutes", "activeEnergy", "basalEnergy",
            "flights", "cyclingDistance", "swimmingDistance", "swimmingStrokes", "wheelchairDistance", "vo2Max",
            "bodyHeight", "bodyWeight", "bodyMassIndex", "bodyFat", "leanBodyMass", "waistCircumference",
            "bodyTemperature", "basalBodyTemperature", "heartRate", "restingHeartRate", "walkingHeartRateAverage",
            "hrv", "heartRateRecovery", "systolicBloodPressure", "diastolicBloodPressure", "sleep", "sleepScore",
            "timeInBed", "respiratoryRate", "bloodOxygen", "inhalerUsage", "glucose", "bloodGlucose",
            "insulinDelivery", "dietaryEnergy", "dietaryWater", "dietaryCarbs", "dietaryProtein", "dietaryFat",
            "dietaryFiber", "dietaryCaffeine", "mindfulMinutes", "daylight", "environmentalAudio", "headphoneAudio",
            "uvExposure", "menstrualFlow", "intermenstrualBleeding", "cervicalMucus", "ovulationTest",
            "sexualActivity", "symptoms"
        ]

        let registeredIDs = Set(AppleHealthStore.metricRegistry.map(\.metricID))
        XCTAssertEqual(AppleHealthStore.metricRegistry.count, 54)
        XCTAssertEqual(registeredIDs, catalogIDs)
        XCTAssertEqual(AppleHealthStore.supportedMetricIDs.count, 51)
        XCTAssertEqual(AppleHealthStore.unsupportedMetricIDs, ["sleepScore", "glucose", "symptoms"])
        XCTAssertTrue(AppleHealthStore.supportedMetricIDs.isDisjoint(with: AppleHealthStore.unsupportedMetricIDs))

        let requiredSupport: Set<String> = [
            "heartRate", "vo2Max", "bodyHeight", "bodyMassIndex", "leanBodyMass", "waistCircumference",
            "bodyTemperature", "basalEnergy", "cyclingDistance", "swimmingDistance", "swimmingStrokes",
            "wheelchairDistance", "heartRateRecovery", "timeInBed", "bloodGlucose", "insulinDelivery",
            "dietaryEnergy", "dietaryWater", "dietaryCarbs", "dietaryProtein", "dietaryFat", "dietaryFiber",
            "dietaryCaffeine", "mindfulMinutes", "daylight", "environmentalAudio", "headphoneAudio", "uvExposure",
            "inhalerUsage", "menstrualFlow", "intermenstrualBleeding", "cervicalMucus", "ovulationTest", "sexualActivity"
        ]
        XCTAssertTrue(requiredSupport.isSubset(of: AppleHealthStore.supportedMetricIDs))
        XCTAssertEqual(AppleHealthStore.metricID(forIndicatorName: "运动分钟"), "exerciseMinutes")
        XCTAssertEqual(AppleHealthStore.metricID(forIndicatorName: "  心率  "), "heartRate")
        XCTAssertEqual(AppleHealthStore.categoryDisplayValue(metricID: "menstrualFlow", value: 3), "中等")
        XCTAssertEqual(AppleHealthStore.categoryDisplayValue(metricID: "ovulationTest", value: 2), "黄体生成素峰值")
    }

    func testRegistryUsesMetricSpecificLatestLookbackPolicies() throws {
        let definitions = Dictionary(
            uniqueKeysWithValues: AppleHealthStore.metricRegistry.map { ($0.metricID, $0) }
        )

        for metricID in ["bodyHeight", "bodyMassIndex", "leanBodyMass", "waistCircumference"] {
            XCTAssertEqual(
                try XCTUnwrap(definitions[metricID]).lookback,
                AppleHealthMetricDefinition.Lookback.allHistory,
                metricID
            )
            XCTAssertEqual(
                try XCTUnwrap(definitions[metricID]).lookback?.noDataWindowDescription,
                "全部历史记录中",
                metricID
            )
        }
        for metricID in ["bodyWeight", "bodyFat", "vo2Max"] {
            XCTAssertEqual(
                try XCTUnwrap(definitions[metricID]).lookback,
                AppleHealthMetricDefinition.Lookback.days(365),
                metricID
            )
        }
        for metricID in ["heartRate", "restingHeartRate", "hrv", "systolicBloodPressure", "respiratoryRate", "bloodOxygen"] {
            XCTAssertEqual(
                try XCTUnwrap(definitions[metricID]).lookback,
                AppleHealthMetricDefinition.Lookback.days(14),
                metricID
            )
        }
    }

    func testAllHistoryLookbackUsesNoStartButKeepsEndBoundPredicate() {
        let now = Date(timeIntervalSince1970: 1_783_008_000)
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(secondsFromGMT: 0)!
        let lookback = AppleHealthMetricDefinition.Lookback.allHistory

        XCTAssertNil(lookback.startDate(endingAt: now, calendar: calendar))
        let predicate: NSPredicate? = lookback.predicate(endingAt: now, calendar: calendar)
        XCTAssertNotNil(predicate, "全历史查询也必须保留 end=now，排除未来样本")
        XCTAssertEqual(lookback.noDataWindowDescription, "全部历史记录中")

        let yearStart = AppleHealthMetricDefinition.Lookback.days(365)
            .startDate(endingAt: now, calendar: calendar)
        XCTAssertEqual(
            yearStart,
            calendar.date(byAdding: .day, value: -365, to: now)
        )
    }

    func testPartialHealthKitReadStillUploadsSamplesAndKeepsPerMetricIssues() async throws {
        let mock = MockAPIService()
        try await mock.setResponse(
            for: "/api/health-data/indicators/device-sync",
            value: DeviceIndicatorSyncResponse(total: 1, inserted: 0, updated: 1, skipped: 0)
        )
        let sample = makeSample(metricID: "heartRate", indicatorName: "心率", value: 72, unit: "bpm")
        let issues = [
            AppleHealthMetricReadIssue(metricID: "vo2Max", indicatorName: "心肺适能", kind: .queryFailed, message: "读取失败"),
            AppleHealthMetricReadIssue(metricID: "bodyTemperature", indicatorName: "体温", kind: .noData, message: "近 14 天无数据")
        ]
        let healthStore = FakeAppleHealthStore(result: AppleHealthReadResult(samples: [sample], issues: issues))
        let vm = AppleHealthSyncViewModel(
            api: mock,
            healthStore: healthStore,
            userDefaults: makeUserDefaults(),
            accountScope: "user-a"
        )

        await vm.requestAccessAndSync()

        XCTAssertEqual(vm.status, .synced)
        XCTAssertEqual(vm.samples, [sample])
        XCTAssertEqual(vm.readIssues, issues)
        XCTAssertTrue(vm.statusSubtitle.contains("1 项无近期数据"))
        XCTAssertTrue(vm.statusSubtitle.contains("1 项读取失败"))
        XCTAssertFalse(vm.shouldOfferHealthSettingsRecovery)
        let requestedPaths = await mock.getRequestedPaths()
        XCTAssertEqual(requestedPaths, ["/api/health-data/indicators/device-sync"])
    }

    func testZeroSamplesExplainsPermissionsAndTimeWindowsWithoutCallingServer() async {
        let mock = MockAPIService()
        let result = AppleHealthReadResult(samples: [], issues: [
            AppleHealthMetricReadIssue(metricID: "steps", indicatorName: "步数", kind: .noData, message: "今天无数据"),
            AppleHealthMetricReadIssue(metricID: "heartRate", indicatorName: "心率", kind: .queryFailed, message: "权限错误")
        ])
        let vm = AppleHealthSyncViewModel(
            api: mock,
            healthStore: FakeAppleHealthStore(result: result),
            userDefaults: makeUserDefaults(),
            accountScope: "user-a"
        )

        await vm.requestAccessAndSync()

        guard case .failed(let message) = vm.status else {
            return XCTFail("零样本应进入可恢复的失败状态")
        }
        XCTAssertTrue(message.contains("系统设置"))
        XCTAssertTrue(message.contains("近 36 小时"))
        XCTAssertTrue(message.contains("近 14 天"))
        XCTAssertTrue(message.contains("近 365 天"))
        XCTAssertTrue(message.contains("全部历史"))
        XCTAssertTrue(message.contains("拒绝读取"))
        let requestedPaths = await mock.getRequestedPaths()
        XCTAssertEqual(requestedPaths, [])
    }

    func testAllSkippedMeansServerAlreadyHasLatestData() async throws {
        let mock = MockAPIService()
        try await mock.setResponse(
            for: "/api/health-data/indicators/device-sync",
            value: DeviceIndicatorSyncResponse(
                total: 1,
                inserted: 0,
                updated: 0,
                skipped: 1,
                unchanged: 1,
                rejected: 0,
                issues: []
            )
        )
        let vm = AppleHealthSyncViewModel(
            api: mock,
            healthStore: FakeAppleHealthStore(samples: [makeSample()]),
            userDefaults: makeUserDefaults(),
            accountScope: "user-a"
        )

        await vm.requestAccessAndSync()

        XCTAssertEqual(vm.status, .upToDate)
        XCTAssertEqual(vm.statusTitle, "服务器已是最新")
        XCTAssertTrue(vm.statusSubtitle.contains("无需更新"))
        XCTAssertFalse(vm.statusSubtitle.contains("已写入服务器"))
        XCTAssertNotNil(vm.lastSyncedAt)
    }

    func testServerRejectsOneOfTwoValuesAsPartialSync() async throws {
        let mock = MockAPIService()
        try await mock.setResponse(
            for: "/api/health-data/indicators/device-sync",
            value: DeviceIndicatorSyncResponse(
                total: 2,
                inserted: 1,
                updated: 0,
                skipped: 1,
                unchanged: 0,
                rejected: 1,
                issues: [DeviceIndicatorSyncIssue(index: 1, code: "source_id_conflict")]
            )
        )
        let samples = [
            makeSample(),
            makeSample(metricID: "heartRate", indicatorName: "心率", value: 72, unit: "bpm")
        ]
        let vm = AppleHealthSyncViewModel(
            api: mock,
            healthStore: FakeAppleHealthStore(samples: samples),
            userDefaults: makeUserDefaults(),
            accountScope: "user-a"
        )

        await vm.requestAccessAndSync()

        XCTAssertEqual(vm.status, .partiallySynced)
        XCTAssertEqual(vm.statusTitle, "部分写入服务器")
        XCTAssertTrue(vm.statusSubtitle.contains("0 项已是最新"))
        XCTAssertTrue(vm.statusSubtitle.contains("1 项未接收"))
        XCTAssertTrue(vm.statusSubtitle.contains("心率：来源标识已属于另一个指标"))
    }

    func testAllRejectedHTTPResponseUsesRejectedStatusNotSynced() async {
        let mock = MockAPIService()
        let errorBody = Data(#"{"detail":{"code":"all_values_rejected","message":"没有可写入的设备健康样本，请检查样本时间或数据格式。","total":1,"inserted":0,"updated":0,"unchanged":0,"rejected":1,"skipped":1,"issues":[{"index":0,"code":"future_measured_at"}]}}"#.utf8)
        await mock.setError(APIError.httpErrorResponse(
            422,
            "没有可写入的设备健康样本，请检查样本时间或数据格式。",
            errorBody
        ))
        let vm = AppleHealthSyncViewModel(
            api: mock,
            healthStore: FakeAppleHealthStore(samples: [makeSample()]),
            userDefaults: makeUserDefaults(),
            accountScope: "user-a"
        )

        await vm.requestAccessAndSync()

        XCTAssertEqual(vm.status, .rejected)
        XCTAssertEqual(vm.statusTitle, "服务器未接收")
        XCTAssertTrue(vm.statusSubtitle.contains("没有可写入"))
        XCTAssertTrue(vm.statusSubtitle.contains("步数：测量时间晚于当前时间"))
        XCTAssertEqual(vm.rejectionIssueDetails, ["步数：测量时间晚于当前时间"])
        XCTAssertEqual(vm.syncResponse, DeviceIndicatorSyncResponse(
            total: 1,
            inserted: 0,
            updated: 0,
            skipped: 1,
            unchanged: 0,
            rejected: 1,
            issues: [DeviceIndicatorSyncIssue(index: 0, code: "future_measured_at")]
        ))
        XCTAssertFalse(vm.shouldOfferHealthSettingsRecovery)
        XCTAssertNil(vm.lastSyncedAt)
    }

    func testSettingsRecoveryOnlyCoversAuthorizationOrReadLimitations() async throws {
        let mock = MockAPIService()
        let authorizationCoordinator = SpyAppleHealthBackgroundCoordinator()
        let authorizationVM = AppleHealthSyncViewModel(
            api: mock,
            healthStore: FakeAppleHealthStore(
                samples: [],
                authorizationError: TestHealthError.denied
            ),
            userDefaults: makeUserDefaults(),
            accountScope: "user-a",
            backgroundCoordinator: authorizationCoordinator
        )

        await authorizationVM.requestAccessAndSync()
        XCTAssertTrue(authorizationVM.shouldOfferHealthSettingsRecovery)

        let networkMock = MockAPIService()
        await networkMock.setError(URLError(.notConnectedToInternet))
        let networkVM = AppleHealthSyncViewModel(
            api: networkMock,
            healthStore: FakeAppleHealthStore(samples: [makeSample()]),
            userDefaults: makeUserDefaults(),
            accountScope: "user-a"
        )
        await networkVM.requestAccessAndSync()
        XCTAssertFalse(networkVM.shouldOfferHealthSettingsRecovery)

        let unavailableVM = AppleHealthSyncViewModel(
            api: mock,
            healthStore: FakeAppleHealthStore(isHealthDataAvailable: false, samples: []),
            userDefaults: makeUserDefaults(),
            accountScope: "user-a"
        )
        await unavailableVM.requestAccessAndSync()
        XCTAssertFalse(unavailableVM.shouldOfferHealthSettingsRecovery)
    }

    func testAuthorizationEnrollsBackgroundDeliveryEvenWhenInitialReadIsEmpty() async {
        let coordinator = SpyAppleHealthBackgroundCoordinator()
        let vm = AppleHealthSyncViewModel(
            api: MockAPIService(),
            healthStore: FakeAppleHealthStore(result: .empty),
            userDefaults: makeUserDefaults(),
            accountScope: "user-a",
            backgroundCoordinator: coordinator
        )

        await vm.requestAccessAndSync()

        XCTAssertEqual(coordinator.enrolledScopes, ["user-a"])
        XCTAssertEqual(coordinator.startedScopes.compactMap { $0 }.last, "user-a")
        XCTAssertGreaterThanOrEqual(coordinator.startedScopes.count, 1)
        XCTAssertTrue(vm.shouldOfferHealthSettingsRecovery)
        guard case .failed = vm.status else { return XCTFail("零样本仍应显示读取恢复状态") }
    }

    func testLegacyGlobalSyncMarkerIsDeletedAndNeverInherited() async {
        let defaults = makeUserDefaults()
        defaults.set(Date(), forKey: "xage.appleHealth.lastSyncedAt")
        let mock = MockAPIService()
        let vm = AppleHealthSyncViewModel(
            api: mock,
            healthStore: FakeAppleHealthStore(samples: [makeSample()]),
            userDefaults: defaults,
            accountScope: "new-user"
        )

        XCTAssertNil(defaults.object(forKey: "xage.appleHealth.lastSyncedAt"))
        XCTAssertNil(vm.lastSyncedAt)
        await vm.refreshIfPreviouslySynced()
        let paths = await mock.getRequestedPaths()
        XCTAssertEqual(paths, [])
    }

    func testLatestSampleSourceIdentityUsesHealthKitUUIDNotTimestamp() {
        let first = AppleHealthStore.sourceID(
            metricID: "heartRate",
            sampleUUID: UUID(uuidString: "00000000-0000-0000-0000-000000000001")!
        )
        let second = AppleHealthStore.sourceID(
            metricID: "heartRate",
            sampleUUID: UUID(uuidString: "00000000-0000-0000-0000-000000000002")!
        )

        XCTAssertNotEqual(first, second)
        XCTAssertTrue(first.hasPrefix("heartRate-"))
        XCTAssertTrue(first.hasSuffix("00000000-0000-0000-0000-000000000001"))
    }

    func testBackgroundCoordinatorRequiresScopedEnrollmentAndStopsOnSwitch() async {
        let defaults = makeUserDefaults()
        let store = FakeAppleHealthBackgroundStore(result: .empty)
        var currentScope: String? = "account-a"
        let coordinator = AppleHealthBackgroundSyncCoordinator(
            healthStore: store,
            api: MockAPIService(),
            userDefaults: defaults,
            currentAccountScope: { currentScope }
        )

        coordinator.startIfEligible(accountScope: "account-a")
        await coordinator.waitForLifecycleTransition()
        XCTAssertEqual(store.startObserverCount, 0)

        coordinator.enroll(accountScope: "account-a")
        coordinator.startIfEligible(accountScope: "account-a")
        await coordinator.waitForLifecycleTransition()
        XCTAssertEqual(store.startObserverCount, 1)
        XCTAssertEqual(store.enableCount, 1)

        currentScope = "account-b"
        coordinator.stop()
        await coordinator.waitForLifecycleTransition()
        XCTAssertNil(store.observerHandler)
        let startCountAfterStop = store.startObserverCount

        coordinator.startIfEligible(accountScope: "account-b")
        await coordinator.waitForLifecycleTransition()
        XCTAssertEqual(store.startObserverCount, startCountAfterStop)
    }

    func testUIAutomationCoordinatorNeverTouchesHealthKitStore() async throws {
        let defaults = makeUserDefaults()
        let store = FakeAppleHealthBackgroundStore(result: .empty)
        let coordinator = AppleHealthBackgroundSyncCoordinator(
            healthStore: store,
            api: MockAPIService(),
            userDefaults: defaults,
            currentAccountScope: { "account-a" },
            launchArguments: { [UIAutomationMode.launchArgument] }
        )
        var operationRan = false

        coordinator.enroll(accountScope: "account-a")
        coordinator.startIfEligible(accountScope: "account-a")
        coordinator.stop()
        let execution = try await coordinator.performSync(accountScope: "account-a") {
            operationRan = true
            _ = try await store.readDailySamples()
            return AppleHealthSyncExecution(readResult: .empty, response: nil)
        }
        await coordinator.waitForLifecycleTransition()

        XCTAssertEqual(execution, AppleHealthSyncExecution(readResult: .empty, response: nil))
        XCTAssertFalse(operationRan)
        XCTAssertFalse(defaults.bool(forKey: AppleHealthBackgroundSyncCoordinator.enrollmentKey(for: "account-a")))
        XCTAssertEqual(store.startObserverCount, 0)
        XCTAssertEqual(store.stopObserverCount, 0)
        XCTAssertEqual(store.enableCount, 0)
        XCTAssertEqual(store.disableCount, 0)
        XCTAssertEqual(store.readCount, 0)
    }

    func testBackgroundObserverUploadsOnceAndRejectsLatePreviousAccountCallback() async throws {
        let defaults = makeUserDefaults()
        let store = FakeAppleHealthBackgroundStore(
            result: AppleHealthReadResult(samples: [makeSample()], issues: [])
        )
        let mock = MockAPIService()
        try await mock.setResponse(
            for: "/api/health-data/indicators/device-sync",
            value: DeviceIndicatorSyncResponse(
                total: 1,
                inserted: 1,
                updated: 0,
                skipped: 0,
                unchanged: 0,
                rejected: 0,
                issues: []
            )
        )
        var currentScope: String? = "account-a"
        let coordinator = AppleHealthBackgroundSyncCoordinator(
            healthStore: store,
            api: mock,
            userDefaults: defaults,
            currentAccountScope: { currentScope }
        )
        coordinator.enroll(accountScope: "account-a")
        coordinator.startIfEligible(accountScope: "account-a")
        await coordinator.waitForLifecycleTransition()

        await store.triggerObserverUpdate()

        var paths = await mock.getRequestedPaths()
        XCTAssertEqual(paths, ["/api/health-data/indicators/device-sync"])
        let scopes = await mock.requestedAccountScopes
        XCTAssertEqual(scopes, ["account-a"])
        XCTAssertNotNil(defaults.object(forKey: AppleHealthBackgroundSyncCoordinator.lastSyncedAtKey(for: "account-a")))

        currentScope = "account-b"
        await store.triggerObserverUpdate()
        paths = await mock.getRequestedPaths()
        XCTAssertEqual(paths.count, 1)

        coordinator.stop()
        await coordinator.waitForLifecycleTransition()
    }

    func testConcurrentObserverCallbacksCoalesceToOneDeviceSync() async throws {
        let store = FakeAppleHealthBackgroundStore(
            result: AppleHealthReadResult(samples: [makeSample()], issues: [])
        )
        let mock = MockAPIService()
        try await mock.setResponse(
            for: "/api/health-data/indicators/device-sync",
            value: DeviceIndicatorSyncResponse(total: 1, inserted: 1, updated: 0, skipped: 0)
        )
        await mock.setDelay(nanoseconds: 100_000_000)
        let coordinator = AppleHealthBackgroundSyncCoordinator(
            healthStore: store,
            api: mock,
            userDefaults: makeUserDefaults(),
            currentAccountScope: { "account-a" }
        )
        coordinator.enroll(accountScope: "account-a")
        coordinator.startIfEligible(accountScope: "account-a")
        await coordinator.waitForLifecycleTransition()

        await store.triggerObserverBurst(count: 2)

        let paths = await mock.getRequestedPaths()
        XCTAssertEqual(paths.count, 1)
        XCTAssertEqual(store.readCount, 1)
        XCTAssertEqual(store.completionInvocationCount, 2)
        coordinator.stop()
        await coordinator.waitForLifecycleTransition()
    }

    func testObserverEventDuringActivePassRunsFreshReadAndCompletesEachEventOnce() async throws {
        let store = FakeAppleHealthBackgroundStore(
            result: AppleHealthReadResult(samples: [makeSample()], issues: [])
        )
        let mock = MockAPIService()
        try await mock.setResponse(
            for: "/api/health-data/indicators/device-sync",
            value: DeviceIndicatorSyncResponse(total: 1, inserted: 1, updated: 0, skipped: 0)
        )
        await mock.setDelay(nanoseconds: 150_000_000)
        let coordinator = AppleHealthBackgroundSyncCoordinator(
            healthStore: store,
            api: mock,
            userDefaults: makeUserDefaults(),
            currentAccountScope: { "account-a" }
        )
        coordinator.enroll(accountScope: "account-a")
        coordinator.startIfEligible(accountScope: "account-a")
        await coordinator.waitForLifecycleTransition()

        async let firstEvent: Void = store.triggerObserverUpdate()
        for _ in 0..<100 where store.readCount == 0 {
            try await Task.sleep(nanoseconds: 1_000_000)
        }
        XCTAssertEqual(store.readCount, 1)

        async let secondEvent: Void = store.triggerObserverUpdate()
        _ = await (firstEvent, secondEvent)

        let paths = await mock.getRequestedPaths()
        XCTAssertEqual(store.readCount, 2)
        XCTAssertEqual(paths.count, 2)
        XCTAssertEqual(store.completionInvocationCount, 2)
        coordinator.stop()
        await coordinator.waitForLifecycleTransition()
    }

    func testObserverEventQueuedInDrainFinishWindowImmediatelyRestartsDrain() async throws {
        let store = FakeAppleHealthBackgroundStore(result: .empty)
        var injectedFinishWindowEvent = false
        let coordinator = AppleHealthBackgroundSyncCoordinator(
            healthStore: store,
            api: MockAPIService(),
            userDefaults: makeUserDefaults(),
            currentAccountScope: { "account-a" },
            beforeObserverDrainFinish: {
                guard !injectedFinishWindowEvent else { return }
                injectedFinishWindowEvent = true
                store.emitObserverUpdate()
                await Task.yield()
                await Task.yield()
            }
        )
        coordinator.enroll(accountScope: "account-a")
        coordinator.startIfEligible(accountScope: "account-a")
        await coordinator.waitForLifecycleTransition()

        await store.triggerObserverUpdate()
        for _ in 0..<500 where store.completionInvocationCount < 2 {
            try await Task.sleep(nanoseconds: 1_000_000)
        }

        XCTAssertTrue(injectedFinishWindowEvent)
        XCTAssertEqual(store.readCount, 2)
        XCTAssertEqual(store.completionInvocationCount, 2)
        coordinator.stop()
        await coordinator.waitForLifecycleTransition()
    }

    func testObserverWaitsForForegroundOperationCleanupThenPerformsFreshRead() async throws {
        let store = FakeAppleHealthBackgroundStore(result: .empty)
        let coordinator = AppleHealthBackgroundSyncCoordinator(
            healthStore: store,
            api: MockAPIService(),
            userDefaults: makeUserDefaults(),
            currentAccountScope: { "account-a" }
        )
        coordinator.enroll(accountScope: "account-a")
        coordinator.startIfEligible(accountScope: "account-a")
        await coordinator.waitForLifecycleTransition()

        var releaseForeground: CheckedContinuation<Void, Never>?
        let foregroundTask = Task { @MainActor in
            try await coordinator.performSync(accountScope: "account-a") {
                await withCheckedContinuation { continuation in
                    releaseForeground = continuation
                }
                return AppleHealthSyncExecution(readResult: .empty, response: nil)
            }
        }
        for _ in 0..<100 where releaseForeground == nil {
            await Task.yield()
        }
        XCTAssertNotNil(releaseForeground)

        let observerTask = Task { await store.triggerObserverUpdate() }
        for _ in 0..<10 { await Task.yield() }
        releaseForeground?.resume()
        releaseForeground = nil

        _ = try await foregroundTask.value
        await observerTask.value
        XCTAssertEqual(store.readCount, 1, "observer must not reuse the just-completed foreground result")
        XCTAssertEqual(store.completionInvocationCount, 1)
        coordinator.stop()
        await coordinator.waitForLifecycleTransition()
    }

    func testStoppingCoordinatorFlushesPendingObserverCompletionExactlyOnce() async throws {
        let store = FakeAppleHealthBackgroundStore(
            result: AppleHealthReadResult(samples: [makeSample()], issues: [])
        )
        let mock = MockAPIService()
        try await mock.setResponse(
            for: "/api/health-data/indicators/device-sync",
            value: DeviceIndicatorSyncResponse(total: 1, inserted: 1, updated: 0, skipped: 0)
        )
        await mock.setDelay(nanoseconds: 2_000_000_000)
        let coordinator = AppleHealthBackgroundSyncCoordinator(
            healthStore: store,
            api: mock,
            userDefaults: makeUserDefaults(),
            currentAccountScope: { "account-a" }
        )
        coordinator.enroll(accountScope: "account-a")
        coordinator.startIfEligible(accountScope: "account-a")
        await coordinator.waitForLifecycleTransition()

        let event = Task { await store.triggerObserverUpdate() }
        for _ in 0..<100 where store.readCount == 0 {
            try await Task.sleep(nanoseconds: 1_000_000)
        }
        XCTAssertEqual(store.readCount, 1)

        coordinator.stop()
        await event.value
        await coordinator.waitForLifecycleTransition()
        XCTAssertEqual(store.completionInvocationCount, 1)
    }

    func testAllBackgroundDeliveryFailuresStopObserversAndRemainDiagnosable() async {
        let store = FakeAppleHealthBackgroundStore(
            result: .empty,
            enableResult: AppleHealthBackgroundDeliveryResult(
                attempted: 51,
                succeeded: 0,
                failures: ["all"],
                failureMessages: ["all": "测试后台启用失败"]
            )
        )
        let coordinator = AppleHealthBackgroundSyncCoordinator(
            healthStore: store,
            api: MockAPIService(),
            userDefaults: makeUserDefaults(),
            currentAccountScope: { "account-a" }
        )
        coordinator.enroll(accountScope: "account-a")
        coordinator.startIfEligible(accountScope: "account-a")
        await coordinator.waitForLifecycleTransition()

        XCTAssertEqual(coordinator.lastBackgroundDeliveryResult?.allFailed, true)
        XCTAssertEqual(
            coordinator.lastBackgroundDeliveryResult?.failureMessages["all"],
            "测试后台启用失败"
        )
        XCTAssertNil(store.observerHandler)
        XCTAssertGreaterThanOrEqual(store.stopObserverCount, 2)
    }

    func testPartialBackgroundDeliveryFailureKeepsWorkingObserversAndDiagnostics() async {
        let store = FakeAppleHealthBackgroundStore(
            result: .empty,
            enableResult: AppleHealthBackgroundDeliveryResult(
                attempted: 51,
                succeeded: 50,
                failures: ["HKQuantityTypeIdentifierHeartRate"],
                failureMessages: ["HKQuantityTypeIdentifierHeartRate": "测试单项启用失败"]
            )
        )
        let coordinator = AppleHealthBackgroundSyncCoordinator(
            healthStore: store,
            api: MockAPIService(),
            userDefaults: makeUserDefaults(),
            currentAccountScope: { "account-a" }
        )
        coordinator.enroll(accountScope: "account-a")

        coordinator.startIfEligible(accountScope: "account-a")
        await coordinator.waitForLifecycleTransition()

        XCTAssertNotNil(store.observerHandler)
        XCTAssertEqual(coordinator.lastBackgroundDeliveryResult?.allFailed, false)
        XCTAssertEqual(
            coordinator.lastBackgroundDeliveryResult?.failureMessages["HKQuantityTypeIdentifierHeartRate"],
            "测试单项启用失败"
        )
        coordinator.stop()
        await coordinator.waitForLifecycleTransition()
    }

    func testAccountScopeDoesNotReuseAnotherAccountsSyncMarker() async throws {
        let defaults = makeUserDefaults()
        let mock = MockAPIService()
        try await mock.setResponse(
            for: "/api/health-data/indicators/device-sync",
            value: DeviceIndicatorSyncResponse(total: 1, inserted: 1, updated: 0, skipped: 0)
        )
        let vm = AppleHealthSyncViewModel(
            api: mock,
            healthStore: FakeAppleHealthStore(samples: [makeSample()]),
            userDefaults: defaults,
            accountScope: "user-a"
        )
        await vm.requestAccessAndSync()
        XCTAssertNotNil(vm.lastSyncedAt)

        vm.setAccountScope("user-b")

        XCTAssertNil(vm.lastSyncedAt)
        XCTAssertEqual(vm.samples, [])
        XCTAssertEqual(vm.status, .idle)
        await vm.refreshIfPreviouslySynced()
        let requestedPaths = await mock.getRequestedPaths()
        XCTAssertEqual(requestedPaths.count, 1)
    }

    func testUnifiedAppleHealthActionRefreshesServerAfterHealthSync() async {
        var events: [String] = []

        let started = await XAgeAppleHealthSyncFlow.synchronize(
            accountScope: "account-test",
            configureAccount: { scope in events.append("scope:\(scope ?? "nil")") },
            synchronizeHealth: { events.append("health") },
            refreshServer: { events.append("server") }
        )

        XCTAssertTrue(started)
        XCTAssertEqual(events, ["scope:account-test", "health", "server"])
    }

    func testUnifiedAppleHealthActionDoesNotTouchDeviceDataWithoutAccountScope() async {
        var events: [String] = []

        let started = await XAgeAppleHealthSyncFlow.synchronize(
            accountScope: nil,
            configureAccount: { scope in events.append("scope:\(scope ?? "nil")") },
            synchronizeHealth: { events.append("health") },
            refreshServer: { events.append("server") }
        )

        XCTAssertFalse(started)
        XCTAssertEqual(events, ["scope:nil"])
    }

    func testAppleHealthCatalogOnlyPromisesAutomaticSyncForImplementedMetrics() throws {
        XCTAssertTrue(AppleHealthStore.supportedMetricIDs.isDisjoint(with: AppleHealthStore.unsupportedMetricIDs))
        XCTAssertEqual(AppleHealthStore.supportedMetricIDs.union(AppleHealthStore.unsupportedMetricIDs).count, 54)

        let supportedID = try XCTUnwrap(AppleHealthStore.supportedMetricIDs.first)
        let supported = XAgeAppleHealthCatalogSemantics.resolve(metricID: supportedID, title: "受支持指标")
        XCTAssertEqual(supported.source, "apple_health_catalog")
        XCTAssertEqual(supported.time, "待同步")
        XCTAssertTrue(supported.subtitle.contains("当前支持"))

        let unsupportedID = try XCTUnwrap(AppleHealthStore.unsupportedMetricIDs.first)
        let unsupported = XAgeAppleHealthCatalogSemantics.resolve(metricID: unsupportedID, title: "未接入指标")
        XCTAssertEqual(unsupported.source, "other_source_catalog")
        XCTAssertEqual(unsupported.time, "暂不支持自动同步")
        XCTAssertTrue(unsupported.subtitle.contains("不会从 Apple 健康自动读取"))
        XCTAssertFalse(unsupported.subtitle.contains("授权后自动更新"))
    }

    func testTrendRequestsCoverEverySupportedAppleHealthIndicatorName() {
        let supportedNames = Set(
            AppleHealthStore.metricRegistry
                .filter(\.isSupported)
                .map(\.indicatorName)
        )
        let requestedNames = XAgeHealthTrendRequestContract.names(watchedNames: [])

        XCTAssertEqual(AppleHealthStore.supportedIndicatorNames, supportedNames)
        XCTAssertEqual(Set(requestedNames), supportedNames)
        XCTAssertEqual(requestedNames.count, supportedNames.count)
        XCTAssertFalse(requestedNames.contains("睡眠评分"))

        let withWatched = XAgeHealthTrendRequestContract.names(watchedNames: ["尿酸", "  步数  "])
        XCTAssertTrue(withWatched.contains("尿酸"))
        XCTAssertEqual(withWatched.filter { $0 == "步数" }.count, 1)
    }

    func testRegistryMapsAllCatalogIndicatorNamesBackToStableMetricIDs() {
        let mappings = AppleHealthStore.metricRegistry.map { definition in
            XAgeHealthMetricRegistryContract.metricID(forIndicatorName: definition.indicatorName)
        }

        XCTAssertEqual(mappings.count, 54)
        XCTAssertFalse(mappings.contains(where: { $0 == nil }))
        XCTAssertEqual(Set(mappings.compactMap { $0 }).count, 54)
        XCTAssertEqual(XAgeHealthMetricRegistryContract.metricID(forIndicatorName: "运动分钟"), "exerciseMinutes")
        XCTAssertEqual(XAgeHealthMetricRegistryContract.metricID(forIndicatorName: "睡眠评分"), "sleepScore")
        XCTAssertEqual(XAgeHealthMetricRegistryContract.metricID(forIndicatorName: "血糖"), "bloodGlucose")
        XCTAssertEqual(XAgeHealthMetricRegistryContract.metricID(forIndicatorName: "血糖波动"), "glucose")
    }

    func testRegistryDrivenFreshnessCoversSupportedMetricsWithoutTwoDayBlanket() {
        let supportedNames = AppleHealthStore.metricRegistry
            .filter(\.isSupported)
            .map(\.indicatorName)
        let limits = supportedNames.compactMap {
            XAgeHealthMetricRegistryContract.freshnessLimitDays(forIndicatorName: $0)
        }

        XCTAssertEqual(limits.count, supportedNames.count)
        XCTAssertEqual(XAgeHealthMetricRegistryContract.freshnessLimitDays(forIndicatorName: "步数"), 2)
        XCTAssertEqual(XAgeHealthMetricRegistryContract.freshnessLimitDays(forIndicatorName: "睡眠"), 2)
        XCTAssertEqual(XAgeHealthMetricRegistryContract.freshnessLimitDays(forIndicatorName: "心率"), 14)
        XCTAssertEqual(XAgeHealthMetricRegistryContract.freshnessLimitDays(forIndicatorName: "体重"), 14)
        XCTAssertEqual(XAgeHealthMetricRegistryContract.freshnessLimitDays(forIndicatorName: "身高"), 180)
        XCTAssertEqual(XAgeHealthMetricRegistryContract.freshnessLimitDays(forIndicatorName: "BMI"), 180)
        XCTAssertEqual(XAgeHealthMetricRegistryContract.freshnessLimitDays(forIndicatorName: "腰围"), 180)
        XCTAssertEqual(XAgeHealthMetricRegistryContract.freshnessLimitDays(forIndicatorName: "经期"), 30)
        XCTAssertNotEqual(XAgeHealthMetricRegistryContract.freshnessLimitDays(forIndicatorName: "心率"), 2)
    }

    func testServerCategoryTrendValuesUseSameHealthKitLabelsAsLocalSamples() {
        XCTAssertEqual(
            XAgeHealthMetricRegistryContract.categoryDisplayValue(forIndicatorName: "经期", value: 3),
            "中等"
        )
        XCTAssertEqual(
            XAgeHealthMetricRegistryContract.categoryDisplayValue(forIndicatorName: "点滴出血", value: 0),
            "已记录"
        )
        XCTAssertEqual(
            XAgeHealthMetricRegistryContract.categoryDisplayValue(forIndicatorName: "宫颈黏液质量", value: 5),
            "蛋清样"
        )
        XCTAssertEqual(
            XAgeHealthMetricRegistryContract.categoryDisplayValue(forIndicatorName: "排卵测试结果", value: 2),
            "黄体生成素峰值"
        )
        XCTAssertEqual(
            XAgeHealthMetricRegistryContract.categoryDisplayValue(forIndicatorName: "性活动", value: 0),
            "已记录"
        )
        XCTAssertNil(XAgeHealthMetricRegistryContract.categoryDisplayValue(forIndicatorName: "步数", value: 2))
    }

    func testAccountScopedRefreshGateRejectsLatePreviousAccountResponse() {
        var gate = XAgeAccountScopedRefreshGate(accountScope: nil)
        XCTAssertTrue(gate.switchAccount(to: "account-a"))
        let accountAGeneration = gate.generation
        XCTAssertTrue(gate.accepts(
            startedScope: "account-a",
            generation: accountAGeneration,
            currentScope: "account-a"
        ))

        XCTAssertTrue(gate.switchAccount(to: "account-b"))
        XCTAssertFalse(gate.accepts(
            startedScope: "account-a",
            generation: accountAGeneration,
            currentScope: "account-b"
        ))
        XCTAssertTrue(gate.accepts(
            startedScope: "account-b",
            generation: gate.generation,
            currentScope: "account-b"
        ))

        XCTAssertTrue(gate.switchAccount(to: nil))
        XCTAssertFalse(gate.accepts(
            startedScope: "account-b",
            generation: gate.generation - 1,
            currentScope: nil
        ))
    }

    func testDashboardAccountResetReplacesLiveValuesWithPurePlaceholders() {
        let accountALiveMetric = XAgeMetric(
            id: "steps",
            title: "步数",
            value: "8240",
            unit: "步",
            time: "今天",
            subtitle: "A 账号实时值",
            accent: .blue,
            source: "apple_health",
            measuredAt: "2026-07-11T08:00:00Z"
        )
        let accountBPreference = XAgeDataCardPreferenceSnapshot(isCustomized: true, ids: ["steps"])

        let resetMetrics = XAgeDataCardPreferences.placeholderMetrics(for: accountBPreference)

        XCTAssertEqual(resetMetrics.map(\.id), ["steps"])
        XCTAssertTrue(resetMetrics.allSatisfy(\.isPlaceholder))
        XCTAssertEqual(resetMetrics.first?.source, "apple_health_catalog")
        XCTAssertNotEqual(resetMetrics.first?.value, accountALiveMetric.value)
        XCTAssertNil(resetMetrics.first?.measuredAt)
    }

    func testDashboardCardPreferencesAreIsolatedAndLegacyMigrationIsSingleUse() {
        XAgeDataCardPreferences.resetForTesting()
        defer { XAgeDataCardPreferences.resetForTesting() }
        UserDefaults.standard.set(["sleep"], forKey: "xage.data.card.ids.v1")
        UserDefaults.standard.set(true, forKey: "xage.data.card.customized.v1")

        let firstMigratedAccount = XAgeDataCardPreferences.load(accountScope: "legacy-account-a")
        let secondAccount = XAgeDataCardPreferences.load(accountScope: "legacy-account-b")

        XCTAssertTrue(firstMigratedAccount.isCustomized)
        XCTAssertEqual(firstMigratedAccount.ids, ["sleep"])
        XCTAssertFalse(secondAccount.isCustomized)
        XCTAssertTrue(secondAccount.ids.isEmpty)

        let metric = XAgeMetric(
            id: "steps",
            title: "步数",
            value: "8240",
            unit: "步",
            time: "今天",
            subtitle: "实时值不会持久化",
            accent: .blue,
            source: "apple_health"
        )

        _ = XAgeDataCardPreferences.save(metrics: [metric], accountScope: "account-a")

        XCTAssertEqual(XAgeDataCardPreferences.load(accountScope: "account-a").ids, ["steps"])
        XCTAssertTrue(XAgeDataCardPreferences.load(accountScope: "account-a").isCustomized)
        XCTAssertFalse(XAgeDataCardPreferences.load(accountScope: "account-b").isCustomized)
        XCTAssertTrue(XAgeDataCardPreferences.load(accountScope: "account-b").ids.isEmpty)
    }

    private func makeUserDefaults() -> UserDefaults {
        let suite = "AppleHealthSyncViewModelTests.\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suite)!
        defaults.removePersistentDomain(forName: suite)
        return defaults
    }

    private func makeSample(
        metricID: String = "steps",
        indicatorName: String = "步数",
        value: Double = 8240,
        unit: String = "步"
    ) -> AppleHealthSyncSample {
        AppleHealthSyncSample(
            id: "\(metricID)-20260702",
            metricID: metricID,
            indicatorName: indicatorName,
            value: value,
            unit: unit,
            measuredAt: Date(timeIntervalSince1970: 1_783_008_000),
            displayValue: "\(value)",
            displayUnit: unit,
            subtitle: "测试样本"
        )
    }
}

private struct FakeAppleHealthStore: AppleHealthStoreProtocol {
    var isHealthDataAvailable = true
    let result: AppleHealthReadResult
    let authorizationError: Error?

    init(
        isHealthDataAvailable: Bool = true,
        samples: [AppleHealthSyncSample],
        authorizationError: Error? = nil
    ) {
        self.isHealthDataAvailable = isHealthDataAvailable
        self.result = AppleHealthReadResult(samples: samples, issues: [])
        self.authorizationError = authorizationError
    }

    init(
        isHealthDataAvailable: Bool = true,
        result: AppleHealthReadResult,
        authorizationError: Error? = nil
    ) {
        self.isHealthDataAvailable = isHealthDataAvailable
        self.result = result
        self.authorizationError = authorizationError
    }

    func requestAuthorization() async throws {
        if let authorizationError { throw authorizationError }
    }

    func readDailySamples() async throws -> AppleHealthReadResult {
        result
    }
}

private enum TestHealthError: LocalizedError {
    case denied

    var errorDescription: String? { "测试授权失败" }
}

@MainActor
private final class SpyAppleHealthBackgroundCoordinator: AppleHealthBackgroundCoordinating {
    var enrolledScopes: [String] = []
    var startedScopes: [String?] = []
    var stopCount = 0

    func enroll(accountScope: String) {
        enrolledScopes.append(accountScope)
    }

    func startIfEligible(accountScope: String?) {
        startedScopes.append(accountScope)
    }

    func stop() {
        stopCount += 1
    }

    func performSync(
        accountScope: String,
        operation: @escaping @MainActor () async throws -> AppleHealthSyncExecution
    ) async throws -> AppleHealthSyncExecution {
        try await operation()
    }
}

private final class FakeAppleHealthBackgroundStore: AppleHealthBackgroundStoreProtocol {
    var isHealthDataAvailable = true
    var result: AppleHealthReadResult
    var enableResult: AppleHealthBackgroundDeliveryResult
    var disableResult: AppleHealthBackgroundDeliveryResult
    var observerHandler: (((@escaping () -> Void) -> Void))?
    var startObserverCount = 0
    var stopObserverCount = 0
    var enableCount = 0
    var disableCount = 0
    var readCount = 0
    var completionInvocationCount = 0

    init(
        result: AppleHealthReadResult,
        enableResult: AppleHealthBackgroundDeliveryResult = AppleHealthBackgroundDeliveryResult(
            attempted: 51,
            succeeded: 51,
            failures: []
        ),
        disableResult: AppleHealthBackgroundDeliveryResult = AppleHealthBackgroundDeliveryResult(
            attempted: 51,
            succeeded: 51,
            failures: []
        )
    ) {
        self.result = result
        self.enableResult = enableResult
        self.disableResult = disableResult
    }

    func requestAuthorization() async throws {}

    func readDailySamples() async throws -> AppleHealthReadResult {
        readCount += 1
        return result
    }

    func startObserverQueries(
        updateHandler: @escaping (@escaping () -> Void) -> Void
    ) {
        startObserverCount += 1
        observerHandler = updateHandler
    }

    func stopObserverQueries() {
        stopObserverCount += 1
        observerHandler = nil
    }

    func enableBackgroundDelivery() async -> AppleHealthBackgroundDeliveryResult {
        enableCount += 1
        return enableResult
    }

    func disableBackgroundDelivery() async -> AppleHealthBackgroundDeliveryResult {
        disableCount += 1
        return disableResult
    }

    func triggerObserverUpdate() async {
        guard let observerHandler else { return }
        await withCheckedContinuation { continuation in
            observerHandler { [weak self] in
                self?.completionInvocationCount += 1
                continuation.resume()
            }
        }
    }

    func emitObserverUpdate() {
        guard let observerHandler else { return }
        observerHandler { [weak self] in
            self?.completionInvocationCount += 1
        }
    }

    func triggerObserverBurst(count: Int) async {
        guard count > 0, let observerHandler else { return }
        await withCheckedContinuation { continuation in
            var remaining = count
            for _ in 0..<count {
                observerHandler { [weak self] in
                    self?.completionInvocationCount += 1
                    remaining -= 1
                    if remaining == 0 {
                        continuation.resume()
                    }
                }
            }
        }
    }
}
