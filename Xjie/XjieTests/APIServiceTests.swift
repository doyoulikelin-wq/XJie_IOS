import XCTest
@testable import Xjie

final class APIServiceTests: XCTestCase {
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
}
