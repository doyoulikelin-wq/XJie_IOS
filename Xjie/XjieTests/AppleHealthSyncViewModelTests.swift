import Foundation
import XCTest
@testable import Xjie

@MainActor
final class AppleHealthSyncViewModelTests: XCTestCase {
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
            subtitle: "今日 Apple 健康步数"
        )
        let healthStore = FakeAppleHealthStore(samples: [sample])
        let vm = AppleHealthSyncViewModel(api: mock, healthStore: healthStore)

        await vm.requestAccessAndSync()

        let paths = await mock.getRequestedPaths()
        XCTAssertEqual(paths, ["/api/health-data/indicators/device-sync"])
        XCTAssertEqual(vm.samples, [sample])
        XCTAssertEqual(vm.syncResponse, response)
        XCTAssertEqual(vm.status, .synced)
    }

    func testUnavailableHealthStoreDoesNotCallAPI() async throws {
        let mock = MockAPIService()
        let healthStore = FakeAppleHealthStore(isHealthDataAvailable: false, samples: [])
        let vm = AppleHealthSyncViewModel(api: mock, healthStore: healthStore)

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
}

private struct FakeAppleHealthStore: AppleHealthStoreProtocol {
    var isHealthDataAvailable = true
    let samples: [AppleHealthSyncSample]

    func requestAuthorization() async throws {}

    func readDailySamples() async throws -> [AppleHealthSyncSample] {
        samples
    }
}
