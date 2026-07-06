import XCTest
@testable import Xjie

/// LoginViewModel 单元测试
@MainActor
final class LoginViewModelTests: XCTestCase {

    // MARK: - Validation

    func testLoginSubjectEmptyShowsAlert() async {
        let mock = MockAPIService()
        let vm = LoginViewModel(api: mock)
        let auth = AuthManager.shared

        vm.selectedSubject = ""
        await vm.loginSubject(authManager: auth)

        XCTAssertTrue(vm.showAlert)
        XCTAssertEqual(vm.alertMessage, "请选择受试者")
    }

    func testLoginPhoneEmptyShowsAlert() async {
        let mock = MockAPIService()
        let vm = LoginViewModel(api: mock)
        let auth = AuthManager.shared

        vm.phone = ""
        vm.password = ""
        await vm.loginPhone(authManager: auth)

        XCTAssertTrue(vm.showAlert)
        XCTAssertEqual(vm.alertMessage, "请填写手机号和密码")
    }

    func testLoginPhoneShortPasswordShowsAlert() async {
        let mock = MockAPIService()
        let vm = LoginViewModel(api: mock)
        let auth = AuthManager.shared

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
        let auth = AuthManager.shared
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
        let auth = AuthManager.shared
        auth.logout()

        vm.phone = "13800138000"
        vm.password = "password123"
        vm.isSignup = false
        await vm.loginPhone(authManager: auth)

        XCTAssertFalse(vm.showAlert)
        XCTAssertEqual(auth.token, "tok_phone")
        XCTAssertFalse(vm.loading)

        auth.logout()
    }

    // MARK: - Error

    func testLoginSubjectNetworkError() async {
        let mock = MockAPIService()
        await mock.setError(URLError(.timedOut))

        let vm = LoginViewModel(api: mock)
        let auth = AuthManager.shared

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
        let auth = AuthManager.shared
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
        let auth = AuthManager.shared
        auth.setAuth(accessToken: "tok_old", refreshToken: "ref_old")

        let logoutTask = Task {
            await vm.logout(authManager: auth)
        }
        try? await Task.sleep(nanoseconds: 30_000_000)
        auth.setAuth(accessToken: "tok_new", refreshToken: "ref_new")
        await logoutTask.value

        XCTAssertEqual(auth.token, "tok_new")
        XCTAssertEqual(auth.refreshToken, "ref_new")
        auth.logout()
    }

    func testXAgeDeleteAccountRequestsBackendAndClearsAuth() async {
        let mock = MockAPIService()
        let vm = XAgeAccountViewModel(api: mock)
        let auth = AuthManager.shared
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
        let auth = AuthManager.shared
        auth.setAuth(accessToken: "tok_keep", refreshToken: "ref_keep")

        await vm.deleteAccount(authManager: auth)

        XCTAssertTrue(auth.isLoggedIn)
        XCTAssertNotNil(vm.errorMessage)
        auth.logout()
    }
}
