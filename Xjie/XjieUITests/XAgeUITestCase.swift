import XCTest

class XAgeUITestCase: XCTestCase {
    var app: XCUIApplication!

    private var launchRequiresNetworkAudit = false
    private var didLaunchAtLeastOnce = false

    final override func setUpWithError() throws {
        try super.setUpWithError()
        continueAfterFailure = false
        app = XAgeUITestApplicationFactory.make(resetAuth: true, resetDataCards: true)
    }

    final override func tearDownWithError() throws {
        XCTAssertTrue(
            didLaunchAtLeastOnce,
            "每个 UI 测试都必须通过共享入口启动并审计 App；不允许空测试假通过"
        )
        if launchRequiresNetworkAudit {
            auditCurrentApplicationLaunch()
        }
        app.terminate()
        app = nil
        try super.tearDownWithError()
    }

    final func launchApplication() {
        XCTAssertFalse(launchRequiresNetworkAudit, "每次 UI 启动都必须先完成网络审计")
        app.launch()
        didLaunchAtLeastOnce = true
        launchRequiresNetworkAudit = true
    }

    final func relaunchApplication(resetAuth: Bool, resetDataCards: Bool) {
        auditCurrentApplicationLaunch()
        app.terminate()
        app = XAgeUITestApplicationFactory.make(
            resetAuth: resetAuth,
            resetDataCards: resetDataCards
        )
        launchApplication()
    }

    final func waitUntil(timeout: TimeInterval, condition: @escaping () -> Bool) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if condition() { return true }
            RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        }
        return condition()
    }

    private func auditCurrentApplicationLaunch() {
        guard launchRequiresNetworkAudit else {
            XCTFail("没有可审计的 UI 应用启动")
            return
        }
        let audit = app.descendants(matching: .any)["xjie.uiTest.networkAudit"]
        let auditExists = audit.waitForExistence(timeout: 4)
        XCTAssertTrue(auditExists, "UI 自动化必须暴露确定性网络审计")
        var stableValue: String?
        var stableSince = Date()
        let auditPassed = auditExists && waitUntil(timeout: 4) {
            guard let value = audit.value as? String else { return false }
            if stableValue != value {
                stableValue = value
                stableSince = Date()
                return false
            }
            let fields: [String: Int] = Dictionary(
                uniqueKeysWithValues: value.split(separator: ";").compactMap { field in
                    let pair = field.split(separator: "=", maxSplits: 1)
                    guard pair.count == 2, let count = Int(pair[1]) else { return nil }
                    return (String(pair[0]), count)
                }
            )
            return (fields["intercepted"] ?? 0) > 0
                && fields["unhandled"] == 0
                && Date().timeIntervalSince(stableSince) >= 1.5
        }
        XCTAssertTrue(
            auditPassed,
            "UI 自动化不得包含未声明 API 请求或生产公网回退：\(String(describing: audit.value))"
        )
        launchRequiresNetworkAudit = false
    }
}

private enum XAgeUITestApplicationFactory {
    static func make(resetAuth: Bool, resetDataCards: Bool) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = [
            "XJIE_UI_TEST_STUB_NETWORK",
            "XJIE_DISABLE_APP_UPDATE_CHECK",
            "XJIE_DISABLE_PUSH_PERMISSION"
        ]
        if resetAuth {
            app.launchArguments.append("XJIE_UI_TEST_RESET_AUTH")
        }
        if resetDataCards {
            app.launchArguments.append("XJIE_UI_TEST_RESET_DATA_CARDS")
        }
        return app
    }
}
