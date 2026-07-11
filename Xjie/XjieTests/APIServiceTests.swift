import Foundation
import XCTest
@testable import Xjie

final class APIServiceTests: XCTestCase {
    func testForegroundSessionDoesNotWaitIndefinitelyForConnectivity() {
        XCTAssertFalse(APIService.shared.trustedSession.configuration.waitsForConnectivity)
    }

    func testAuth401DoesNotAttemptTokenRefresh() {
        XCTAssertFalse(APIService.shouldAttemptTokenRefresh(path: "/api/auth/login", statusCode: 401, retried: false))
        XCTAssertFalse(APIService.shouldAttemptTokenRefresh(path: "/api/auth/signup", statusCode: 401, retried: false))
        XCTAssertFalse(APIService.shouldAttemptTokenRefresh(path: "/api/auth/password/reset/request", statusCode: 401, retried: false))
        XCTAssertFalse(APIService.shouldAttemptTokenRefresh(path: "/api/auth/login?source=ios", statusCode: 401, retried: false))
    }

    func testProtected401AttemptsTokenRefreshOnce() {
        XCTAssertTrue(APIService.shouldAttemptTokenRefresh(path: "/api/health-data/summary", statusCode: 401, retried: false))
        XCTAssertTrue(APIService.shouldAttemptTokenRefresh(path: "/api/auth/password/change", statusCode: 401, retried: false))
        XCTAssertFalse(APIService.shouldAttemptTokenRefresh(path: "/api/health-data/summary", statusCode: 401, retried: true))
    }

    func testNon401DoesNotAttemptTokenRefresh() {
        XCTAssertFalse(APIService.shouldAttemptTokenRefresh(path: "/api/health-data/summary", statusCode: 400, retried: false))
        XCTAssertFalse(APIService.shouldAttemptTokenRefresh(path: "/api/health-data/summary", statusCode: 500, retried: false))
    }

    func testAccountBoundRetryNeverAdoptsTokenFromAnotherAccount() {
        let decision = APIService.accountBoundRetryDecision(
            expectedAccountScope: "account-a",
            originalToken: "old-a-token",
            current: APIService.AccountBoundAuthSnapshot(
                token: "new-b-token",
                accountScope: "account-b"
            )
        )

        XCTAssertEqual(decision, .abort)
        XCTAssertFalse(APIService.shouldContinueAccountBoundRequest(
            expectedAccountScope: "account-a",
            currentAccountScope: "account-b"
        ))
        XCTAssertFalse(APIService.shouldContinueAccountBoundRequest(
            expectedAccountScope: "account-a",
            currentAccountScope: nil
        ))
    }

    func testAccountBoundRetryCanUseRefreshedTokenOnlyWithinSameAccount() {
        let refreshed = APIService.accountBoundRetryDecision(
            expectedAccountScope: "account-a",
            originalToken: "old-a-token",
            current: APIService.AccountBoundAuthSnapshot(
                token: "new-a-token",
                accountScope: "account-a"
            )
        )
        let needsRefresh = APIService.accountBoundRetryDecision(
            expectedAccountScope: "account-a",
            originalToken: "old-a-token",
            current: APIService.AccountBoundAuthSnapshot(
                token: "old-a-token",
                accountScope: "account-a"
            )
        )

        XCTAssertEqual(refreshed, .retry("new-a-token"))
        XCTAssertEqual(needsRefresh, .refresh)
    }

    func testAccountBoundNetworkAndServerRetriesRequireSameAccountBeforeAndAfterBackoff() {
        XCTAssertTrue(APIService.shouldRetryAccountBoundTransport(
            expectedAccountScope: "account-a",
            currentAccountScope: "account-a",
            retryCount: 0
        ))
        XCTAssertFalse(APIService.shouldRetryAccountBoundTransport(
            expectedAccountScope: "account-a",
            currentAccountScope: "account-b",
            retryCount: 0
        ))
        XCTAssertFalse(APIService.shouldRetryAccountBoundTransport(
            expectedAccountScope: "account-a",
            currentAccountScope: nil,
            retryCount: 0
        ))
        XCTAssertFalse(APIService.shouldRetryAccountBoundTransport(
            expectedAccountScope: "account-a",
            currentAccountScope: "account-a",
            retryCount: APIConstants.maxRetries
        ))
    }

    func testMixedStructuredErrorDetailKeepsMessage() {
        let data = Data(#"{"detail":{"code":"all_values_rejected","message":"没有可写入的设备健康样本","total":2,"issues":[{"index":0,"code":"invalid_value"}]}}"#.utf8)

        XCTAssertEqual(
            APIService.errorMessage(from: data, fallback: "请求失败"),
            "没有可写入的设备健康样本"
        )
    }

    func testAccountBoundHTTPErrorPreservesStructuredResponseBody() {
        let data = Data(#"{"detail":{"code":"all_values_rejected","message":"没有可写入的设备健康样本","total":1,"inserted":0,"updated":0,"unchanged":0,"rejected":1,"skipped":1,"issues":[{"index":0,"code":"invalid_value"}]}}"#.utf8)
        let error = APIError.httpErrorResponse(422, "没有可写入的设备健康样本", data)

        guard case .httpErrorResponse(let statusCode, let message, let body) = error else {
            return XCTFail("account-bound error must preserve its response body")
        }
        XCTAssertEqual(statusCode, 422)
        XCTAssertEqual(message, "没有可写入的设备健康样本")
        XCTAssertEqual(body, data)

        let rejection = DeviceIndicatorSyncRejection.decode(from: body)
        XCTAssertEqual(rejection?.code, "all_values_rejected")
        XCTAssertEqual(rejection?.response.rejected, 1)
        XCTAssertEqual(rejection?.response.issues, [
            DeviceIndicatorSyncIssue(index: 0, code: "invalid_value")
        ])
    }

    func testTrendPointDecodesLegacyResponseWithoutSourceIdentity() throws {
        let data = Data(#"{"indicators":[{"name":"步数","unit":"步","ref_low":null,"ref_high":null,"points":[{"date":"2026-07-11","value":8200,"abnormal":false,"source":"apple_health","measured_at":"2026-07-11T08:00:00Z"}]}]}"#.utf8)

        let response = try JSONDecoder().decode(IndicatorTrendResponse.self, from: data)
        let point = try XCTUnwrap(response.indicators.first?.points.first)

        XCTAssertNil(point.source_metric)
        XCTAssertNil(point.source_id)
        XCTAssertNil(point.value_kind)
        XCTAssertNil(point.display_value)
        XCTAssertNil(point.source_local_date)
        XCTAssertNil(point.timezone_offset_minutes)
        XCTAssertEqual(point.displayDate, "2026-07-11")
        XCTAssertNil(point.preferredDisplayValue)
        XCTAssertFalse(point.isCategoricalValue)
        XCTAssertTrue(IndicatorTrendPresentationContract.shouldDrawContinuousLine(for: response.indicators[0]))
        XCTAssertEqual(point.id, "2026-07-11-apple_health-2026-07-11T08:00:00Z")
    }

    func testTrendPointUsesSourceIdentityForSameTimestampSamples() throws {
        let data = Data(#"{"indicators":[{"name":"心率","unit":"bpm","ref_low":null,"ref_high":null,"points":[{"date":"2026-07-11","value":68,"abnormal":false,"source":"apple_health","measured_at":"2026-07-11T08:00:00Z","source_metric":"heartRate","source_id":"sample-a"},{"date":"2026-07-11","value":72,"abnormal":false,"source":"apple_health","measured_at":"2026-07-11T08:00:00Z","source_metric":"heartRate","source_id":"sample-b"}]}]}"#.utf8)

        let response = try JSONDecoder().decode(IndicatorTrendResponse.self, from: data)
        let points = try XCTUnwrap(response.indicators.first?.points)

        XCTAssertEqual(points.map(\.source_metric), ["heartRate", "heartRate"])
        XCTAssertEqual(points.map(\.source_id), ["sample-a", "sample-b"])
        XCTAssertEqual(points.map(\.id), ["apple_health-sample-a", "apple_health-sample-b"])
        XCTAssertEqual(Set(points.map(\.id)).count, 2)
    }

    func testTrendPointDecodesCategoricalDisplayAndSourceLocalDay() throws {
        let data = Data(#"{"indicators":[{"name":"经期","unit":null,"ref_low":null,"ref_high":null,"points":[{"date":"2026-07-10","value":3,"abnormal":false,"source":"apple_health","measured_at":"2026-07-10T16:30:00Z","source_metric":"menstrualFlow","source_id":"sample-period-a","value_kind":"category","display_value":"经量较多","source_local_date":"2026-07-11","timezone_offset_minutes":480}]}]}"#.utf8)

        let response = try JSONDecoder().decode(IndicatorTrendResponse.self, from: data)
        let trend = try XCTUnwrap(response.indicators.first)
        let point = try XCTUnwrap(trend.points.first)

        XCTAssertEqual(point.value_kind, "category")
        XCTAssertEqual(point.display_value, "经量较多")
        XCTAssertEqual(point.source_local_date, "2026-07-11")
        XCTAssertEqual(point.timezone_offset_minutes, 480)
        XCTAssertEqual(point.displayDate, "2026-07-11")
        XCTAssertEqual(point.preferredDisplayValue, "经量较多")
        XCTAssertTrue(point.isCategoricalValue)
        XCTAssertEqual(point.id, "apple_health-sample-period-a")
        XCTAssertFalse(IndicatorTrendPresentationContract.shouldDrawContinuousLine(for: trend))
        XCTAssertEqual(
            IndicatorTrendPresentationContract.displayValue(for: point, indicatorName: trend.name),
            "经量较多"
        )
    }

}
