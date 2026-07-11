import Foundation
import XCTest
@testable import Xjie

/// LoginViewModel 单元测试
@MainActor
final class LoginViewModelTests: XCTestCase {

    // MARK: - Validation

    func testLoginSubjectEmptyShowsAlert() async {
        let mock = MockAPIService()
        let vm = LoginViewModel(api: mock)
        let auth = AuthManager.makeTestingInstance()

        vm.selectedSubject = ""
        await vm.loginSubject(authManager: auth)

        XCTAssertTrue(vm.showAlert)
        XCTAssertEqual(vm.alertMessage, "请选择受试者")
    }

    func testLoginPhoneEmptyShowsAlert() async {
        let mock = MockAPIService()
        let vm = LoginViewModel(api: mock)
        let auth = AuthManager.makeTestingInstance()

        vm.phone = ""
        vm.password = ""
        await vm.loginPhone(authManager: auth)

        XCTAssertTrue(vm.showAlert)
        XCTAssertEqual(vm.alertMessage, "请填写手机号和密码")
    }

    func testLoginPhoneShortPasswordShowsAlert() async {
        let mock = MockAPIService()
        let vm = LoginViewModel(api: mock)
        let auth = AuthManager.makeTestingInstance()

        vm.phone = "13800138000"
        vm.password = "short"
        await vm.loginPhone(authManager: auth)

        XCTAssertTrue(vm.showAlert)
        XCTAssertEqual(vm.alertMessage, "密码至少 8 位")
    }

    // MARK: - Success

    func testLoginSubjectSuccess() async throws {
        let mock = MockAPIService()
        let response = AuthResponse(access_token: "tok_abc", refresh_token: "ref_xyz")
        try await mock.setResponse(for: "/api/auth/login-subject", value: response)

        let vm = LoginViewModel(api: mock)
        let auth = AuthManager.makeTestingInstance()
        auth.logout() // 清理

        vm.selectedSubject = "SC001"
        await vm.loginSubject(authManager: auth)

        XCTAssertFalse(vm.showAlert, "不应弹窗")
        XCTAssertEqual(auth.token, "tok_abc")
        XCTAssertEqual(auth.subjectId, "SC001")
        XCTAssertFalse(vm.loading)

        auth.logout() // 清理
    }

    func testLoginPhoneSuccess() async throws {
        let mock = MockAPIService()
        let response = AuthResponse(access_token: "tok_phone", refresh_token: "ref_phone")
        try await mock.setResponse(for: "/api/auth/login", value: response)

        let vm = LoginViewModel(api: mock)
        let auth = AuthManager.makeTestingInstance()
        auth.logout()

        vm.phone = "13800138000"
        vm.password = "password123"
        vm.isSignup = false
        await vm.loginPhone(authManager: auth)

        XCTAssertFalse(vm.showAlert)
        XCTAssertEqual(auth.token, "tok_phone")
        XCTAssertFalse(vm.loading)
        let paths = await mock.requestedPaths
        XCTAssertFalse(paths.contains("/api/users/consent"), "登录不得静默修改 AI 授权")

        auth.logout()
    }

    func testSignupDoesNotSilentlyGrantAIConsent() async throws {
        let mock = MockAPIService()
        let response = AuthResponse(access_token: "tok_signup", refresh_token: "ref_signup")
        try await mock.setResponse(for: "/api/auth/signup", value: response)

        let vm = LoginViewModel(api: mock)
        let auth = AuthManager.makeTestingInstance()
        auth.logout()
        vm.phone = "13800138001"
        vm.username = "新用户"
        vm.password = "password123"
        vm.isSignup = true
        vm.onboardingGeneratePlan = false

        await vm.loginPhone(authManager: auth)

        let paths = await mock.requestedPaths
        XCTAssertTrue(paths.contains("/api/auth/signup"))
        XCTAssertFalse(paths.contains("/api/users/consent"), "注册后的授权必须由用户明确确认")
        auth.logout()
    }

    func testLoginPhoneNormalizesWhitespaceBeforeSubmitting() async throws {
        let mock = MockAPIService()
        let response = AuthResponse(access_token: "tok_phone_trim", refresh_token: "ref_phone_trim")
        try await mock.setResponse(for: "/api/auth/login", value: response)

        let vm = LoginViewModel(api: mock)
        let auth = AuthManager.makeTestingInstance()
        auth.logout()

        vm.phone = " 138 0013 8000 "
        vm.password = " UnitTestPassword!42 "
        vm.isSignup = false
        await vm.loginPhone(authManager: auth)

        let body = await mock.requestBodyJSON(for: "/api/auth/login")
        XCTAssertEqual(body?["phone"] as? String, "13800138000")
        XCTAssertEqual(body?["password"] as? String, "UnitTestPassword!42")

        auth.logout()
    }

    func testPasswordResetNormalizesWhitespaceBeforeSubmitting() async throws {
        let mock = MockAPIService()
        try await mock.setResponse(for: "/api/auth/password/reset/request", value: SimpleOk(ok: true, message: "sent", added: nil, total_seed: nil))
        try await mock.setResponse(for: "/api/auth/password/reset/confirm", value: SimpleOk(ok: true, message: "reset", added: nil, total_seed: nil))
        let vm = PasswordResetViewModel(api: mock)

        vm.phone = " 138 0013 8000 "
        await vm.requestCode()
        vm.code = "123456"
        vm.newPassword = "UnitTestPassword!42"
        await vm.confirm()

        let requestBody = await mock.requestBodyJSON(for: "/api/auth/password/reset/request")
        let confirmBody = await mock.requestBodyJSON(for: "/api/auth/password/reset/confirm")
        XCTAssertEqual(requestBody?["phone"] as? String, "13800138000")
        XCTAssertEqual(confirmBody?["phone"] as? String, "13800138000")
        XCTAssertTrue(vm.resetOk)
    }

    func testManualIndicatorSubmitUsesManualIndicatorEndpoint() async throws {
        let mock = MockAPIService()
        let item = ManualIndicatorResponseStub(
            id: 42,
            indicator_name: "收缩压",
            value: 121,
            unit: "mmHg",
            measured_at: "2026-07-07T08:00:00Z",
            notes: "home"
        )
        try await mock.setResponse(for: "/api/health-data/indicators/manual", value: item)

        let vm = ManualIndicatorViewModel(api: mock)
        await vm.submit(
            indicatorName: "收缩压",
            value: 121,
            unit: "mmHg",
            measuredAt: Date(timeIntervalSince1970: 1_783_488_000),
            notes: "home"
        )

        let paths = await mock.requestedPaths
        let body = await mock.requestBodyJSON(for: "/api/health-data/indicators/manual")
        XCTAssertTrue(paths.contains("/api/health-data/indicators/manual"))
        XCTAssertEqual(body?["indicator_name"] as? String, "收缩压")
        XCTAssertEqual(body?["value"] as? Double, 121)
        XCTAssertEqual(body?["unit"] as? String, "mmHg")
        XCTAssertTrue(vm.savedOk)
    }

    // MARK: - Error

    func testLoginSubjectNetworkError() async {
        let mock = MockAPIService()
        await mock.setError(URLError(.timedOut))

        let vm = LoginViewModel(api: mock)
        let auth = AuthManager.makeTestingInstance()

        vm.selectedSubject = "SC001"
        await vm.loginSubject(authManager: auth)

        XCTAssertTrue(vm.showAlert)
        XCTAssertFalse(vm.alertMessage.isEmpty)
        XCTAssertFalse(vm.loading)
    }

    // MARK: - loadSubjects

    func testLoadSubjectsSuccess() async throws {
        let mock = MockAPIService()
        let subjects = [
            SubjectItem(subject_id: "SC001", cohort: "A"),
            SubjectItem(subject_id: "SC002", cohort: "B"),
        ]
        try await mock.setResult(subjects)

        let vm = LoginViewModel(api: mock)
        await vm.loadSubjects()

        XCTAssertEqual(vm.subjects.count, 2)
        XCTAssertEqual(vm.subjects[0].subject_id, "SC001")
    }

    func testLoadSubjectsError() async {
        let mock = MockAPIService()
        await mock.setError(URLError(.cannotConnectToHost))

        let vm = LoginViewModel(api: mock)
        await vm.loadSubjects()

        XCTAssertTrue(vm.subjects.isEmpty)
        XCTAssertNotNil(vm.errorMessage)
    }

    // MARK: - XAGE account management

    func testXAgeLogoutRequestsBackendAndClearsAuth() async {
        let mock = MockAPIService()
        let vm = XAgeAccountViewModel(api: mock)
        let auth = AuthManager.makeTestingInstance()
        auth.setAuth(accessToken: "tok_logout", refreshToken: "ref_logout")

        await vm.logout(authManager: auth)

        let paths = await mock.requestedPaths
        XCTAssertTrue(paths.contains("/api/auth/logout"))
        XCTAssertFalse(auth.isLoggedIn)
        XCTAssertNil(vm.errorMessage)
    }

    func testXAgeDelayedLogoutDoesNotClearNewLoginToken() async {
        let mock = MockAPIService()
        await mock.setDelay(nanoseconds: 150_000_000)
        let vm = XAgeAccountViewModel(api: mock)
        let auth = AuthManager.makeTestingInstance()
        auth.setAuth(accessToken: "tok_old", refreshToken: "ref_old")

        let logoutTask = Task {
            await vm.logout(authManager: auth)
        }
        var requestStarted = false
        for _ in 0..<100 where !requestStarted {
            requestStarted = await mock.requestedPaths.contains("/api/auth/logout")
            if !requestStarted {
                try? await Task.sleep(nanoseconds: 1_000_000)
            }
        }
        XCTAssertTrue(requestStarted, "登出请求应在切换登录态前开始")
        auth.setAuth(accessToken: "tok_new", refreshToken: "ref_new")
        await logoutTask.value

        XCTAssertEqual(auth.token, "tok_new")
        XCTAssertEqual(auth.refreshToken, "ref_new")
        auth.logout()
    }

    func testXAgeDeleteAccountRequestsBackendAndClearsAuth() async {
        let mock = MockAPIService()
        let vm = XAgeAccountViewModel(api: mock)
        let auth = AuthManager.makeTestingInstance()
        auth.setAuth(accessToken: "tok_delete", refreshToken: "ref_delete")

        await vm.deleteAccount(authManager: auth)

        let paths = await mock.requestedPaths
        XCTAssertTrue(paths.contains("/api/users/me"))
        XCTAssertFalse(auth.isLoggedIn)
        XCTAssertNil(vm.errorMessage)
    }

    func testXAgeDeleteAccountFailureKeepsAuth() async {
        let mock = MockAPIService()
        await mock.setError(URLError(.cannotConnectToHost))
        let vm = XAgeAccountViewModel(api: mock)
        let auth = AuthManager.makeTestingInstance()
        auth.setAuth(accessToken: "tok_keep", refreshToken: "ref_keep")

        await vm.deleteAccount(authManager: auth)

        XCTAssertTrue(auth.isLoggedIn)
        XCTAssertNotNil(vm.errorMessage)
        auth.logout()
    }

    // MARK: - Account-scoped device data

    func testJWTAccountScopeIsStableAcrossTokenRefresh() throws {
        let oldToken = try makeJWT(subject: "user-42", nonce: "old")
        let refreshedToken = try makeJWT(subject: "user-42", nonce: "new")

        let oldScope = AuthManager.accountScope(fromJWT: oldToken)
        let refreshedScope = AuthManager.accountScope(fromJWT: refreshedToken)

        XCTAssertNotNil(oldScope)
        XCTAssertEqual(oldScope, refreshedScope)
        XCTAssertFalse(oldScope?.contains("user-42") == true, "本地作用域不能暴露 JWT sub")
    }

    func testJWTAccountScopeSeparatesDifferentAccountsAndRejectsMalformedTokens() throws {
        let first = AuthManager.accountScope(fromJWT: try makeJWT(subject: "user-a", nonce: "1"))
        let second = AuthManager.accountScope(fromJWT: try makeJWT(subject: "user-b", nonce: "1"))

        XCTAssertNotEqual(first, second)
        XCTAssertNil(AuthManager.accountScope(fromJWT: "not-a-jwt"))
        XCTAssertNil(AuthManager.accountScope(fromJWT: try makeJWT(subject: "   ", nonce: "1")))
    }

    func testUIValidationSessionUsesStableOpaqueAccountScope() {
        let auth = AuthManager.makeTestingInstance()

        auth.startUIValidationSession()
        let firstScope = auth.accountScope
        let secondScope = auth.accountScope

        XCTAssertNotNil(firstScope)
        XCTAssertEqual(firstScope, secondScope)
        XCTAssertFalse(firstScope?.contains("UI-VALIDATION") == true)
        auth.logout()
        XCTAssertNil(auth.accountScope)
    }

    func testAuthAccountScopeDoesNotReuseHealthSubjectAndClearsOnLogout() throws {
        let auth = AuthManager.makeTestingInstance()
        auth.setSubject("shared-health-subject")
        auth.setAuth(accessToken: try makeJWT(subject: "account-owner", nonce: "1"))

        let loggedInScope = auth.accountScope
        XCTAssertNotNil(loggedInScope)
        auth.setSubject("another-health-subject")
        XCTAssertEqual(auth.accountScope, loggedInScope)

        auth.logout()
        XCTAssertNil(auth.accountScope)
    }

    func testIsolatedTestingAuthLogoutDoesNotManageGlobalDeviceHealthLifecycle() {
        let auth = AuthManager.makeTestingInstance()

        XCTAssertFalse(auth.managesDeviceHealthLifecycle)
        auth.logout()
        XCTAssertFalse(auth.managesDeviceHealthLifecycle)
    }

    func testManagedAuthLogoutStopsInjectedDeviceHealthLifecycle() {
        var stopCount = 0
        let auth = AuthManager.makeTestingInstance {
            stopCount += 1
        }

        XCTAssertTrue(auth.managesDeviceHealthLifecycle)
        auth.logout()
        XCTAssertEqual(stopCount, 1)
    }

    func testSetAuthDifferentJWTAccountStopsLifecycleAndClearsAccountState() throws {
        let accountAToken = try makeJWT(subject: "account-a", nonce: "login")
        let accountBToken = try makeJWT(subject: "account-b", nonce: "login")
        var tokenObservedAtStop: [String] = []
        var auth: AuthManager!
        auth = AuthManager.makeTestingInstance {
            tokenObservedAtStop.append(auth.token)
        }

        auth.setAuth(accessToken: accountAToken, refreshToken: "refresh-a")
        auth.setSubject("health-subject-a")
        auth.userInfo = makeUserInfo(id: "profile-a")
        tokenObservedAtStop.removeAll()

        auth.setAuth(accessToken: accountBToken, refreshToken: "refresh-b")

        XCTAssertEqual(tokenObservedAtStop, [accountAToken], "必须在发布 B token 前停止 A 的设备健康生命周期")
        XCTAssertEqual(auth.token, accountBToken)
        XCTAssertEqual(auth.refreshToken, "refresh-b")
        XCTAssertEqual(auth.subjectId, "")
        XCTAssertNil(auth.userInfo)
    }

    func testSetAuthSameJWTAccountRefreshPreservesLifecycleAndAccountState() throws {
        let oldToken = try makeJWT(subject: "account-a", nonce: "old")
        let refreshedToken = try makeJWT(subject: "account-a", nonce: "new")
        var stopCount = 0
        let auth = AuthManager.makeTestingInstance {
            stopCount += 1
        }

        auth.setAuth(accessToken: oldToken, refreshToken: "refresh-old")
        auth.setSubject("health-subject-a")
        auth.userInfo = makeUserInfo(id: "profile-a")
        stopCount = 0

        auth.setAuth(accessToken: refreshedToken, refreshToken: "refresh-new")

        XCTAssertEqual(stopCount, 0, "同一 JWT sub 的正常刷新不应中断健康同步")
        XCTAssertEqual(auth.token, refreshedToken)
        XCTAssertEqual(auth.refreshToken, "refresh-new")
        XCTAssertEqual(auth.subjectId, "health-subject-a")
        XCTAssertEqual(auth.userInfo?.id, "profile-a")
    }

    private func makeUserInfo(id: String) -> UserInfo {
        UserInfo(
            id: id,
            email: nil,
            phone: nil,
            username: nil,
            is_admin: nil,
            created_at: nil,
            consent: nil,
            profile: nil
        )
    }

    private func makeJWT(subject: String, nonce: String) throws -> String {
        let header = try JSONSerialization.data(withJSONObject: ["alg": "none", "typ": "JWT"])
        let payload = try JSONSerialization.data(withJSONObject: ["sub": subject, "nonce": nonce])
        return "\(base64URL(header)).\(base64URL(payload)).signature"
    }

    private func base64URL(_ data: Data) -> String {
        data.base64EncodedString()
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
    }
}

private struct ManualIndicatorResponseStub: Encodable {
    let id: Int
    let indicator_name: String
    let value: Double
    let unit: String?
    let measured_at: String?
    let notes: String?
}
