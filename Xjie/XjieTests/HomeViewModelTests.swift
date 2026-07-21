import XCTest
@testable import Xjie

/// HomeViewModel 单元测试
@MainActor
final class HomeViewModelTests: XCTestCase {
    override func setUp() {
        super.setUp()
        OfflineCacheManager.shared.clearAll()
    }

    override func tearDown() {
        OfflineCacheManager.shared.clearAll()
        super.tearDown()
    }

    func testFetchDataSuccess() async throws {
        let mock = MockAPIService()
        let dashboard = DashboardHealth(
            glucose: GlucoseDashboard(
                last_24h: GlucoseSummary(window: "24h", avg: 110, tir_70_180_pct: 85, min: 65, max: 180, variability: "low", gaps_hours: 0),
                last_7d: nil
            ),
            kcal_today: 1500,
            meals_today: nil,
            data_quality: DataQuality(glucose_gaps_hours: 0, variability: "low"),
            metabolic_state: nil,
            weekly_validation: nil,
            cgm_quality: nil
        )
        try await mock.setResponse(for: "/api/dashboard/health", value: dashboard)

        let vm = HomeViewModel(api: mock)
        await vm.fetchData()

        XCTAssertNotNil(vm.dashboard)
        XCTAssertEqual(vm.dashboard?.glucose?.last_24h?.avg, 110)
        XCTAssertNil(vm.errorMessage)
        XCTAssertFalse(vm.loading)
    }

    func testFetchDataError() async throws {
        let mock = MockAPIService()
        await mock.setError(URLError(.notConnectedToInternet))

        let vm = HomeViewModel(api: mock)
        await vm.fetchData()

        XCTAssertNil(vm.dashboard)
        XCTAssertNotNil(vm.errorMessage)
        XCTAssertFalse(vm.loading)
    }

    func testFetchDataSetsLoadingState() async {
        let mock = MockAPIService()
        // 没有设置任何 result，会抛错
        let vm = HomeViewModel(api: mock)

        XCTAssertFalse(vm.loading, "初始 loading 应为 false")
        await vm.fetchData()
        XCTAssertFalse(vm.loading, "完成后 loading 应为 false")
    }
}
