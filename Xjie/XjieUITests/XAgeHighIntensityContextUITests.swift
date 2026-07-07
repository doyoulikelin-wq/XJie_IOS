import XCTest

final class XAgeHighIntensityContextUITests: XCTestCase {
    private var app: XCUIApplication!

    override func setUpWithError() throws {
        continueAfterFailure = false
        app = XCUIApplication()
        app.launchArguments = [
            "XJIE_UI_TEST_RESET_AUTH",
            "XJIE_DISABLE_APP_UPDATE_CHECK",
            "XJIE_DISABLE_PUSH_PERMISSION"
        ]
    }

    override func tearDownWithError() throws {
        app = nil
    }

    func testHighIntensityContextFlowUsesRealButtons() throws {
        app.launch()
        enterDebugValidationSession()
        verifyDataButtonsAndPanels()
        verifyMetricManagerAndSortControls()
        verifyChatButtonsAndContextPrompts()
        verifyXAgeInfoButton()
        attachScreenshot(named: "xage-high-intensity-final")
    }

    private func enterDebugValidationSession() {
        if app.buttons["xage.segment.数据"].waitForExistence(timeout: 8) {
            return
        }

        let validationButton = app.buttons["xjie.debug.uiValidationLogin"]
        XCTAssertTrue(validationButton.waitForExistence(timeout: 8), "登录页应显示 Debug UI 验证入口")
        validationButton.tap()
        XCTAssertTrue(app.buttons["xage.segment.数据"].waitForExistence(timeout: 8), "点击 UI 验证入口后应进入 XAGE 数据页")
        attachScreenshot(named: "01-entered-xage")
    }

    private func verifyDataButtonsAndPanels() {
        tapAndWait(app.buttons["xage.more"], for: app.buttons["xage.account.报告"])

        for (title, detailIdentifier) in [
            ("报告", "xage.panel.reports.primary"),
            ("日常", "xage.panel.daily.primary"),
            ("就医", "xage.panel.medical.primary"),
            ("画像", "xage.panel.profile.primary")
        ] {
            if !app.buttons["xage.account.\(title)"].exists {
                tapAndWait(app.buttons["xage.more"], for: app.buttons["xage.account.\(title)"])
            }
            tapAndWait(app.buttons["xage.account.\(title)"], for: app.buttons[detailIdentifier])
            attachScreenshot(named: "panel-\(title)")
            closePresentedPanel()
        }

        XCTAssertTrue(app.buttons["xage.segment.数据"].waitForExistence(timeout: 6), "四个资料详情页关闭后应回到数据页")
    }

    private func verifyMetricManagerAndSortControls() {
        tapAndWait(app.buttons["xage.data.sort"], for: app.buttons["xage.data.sort.bottomDone"])
        XCTAssertTrue(app.buttons.matching(NSPredicate(format: "label CONTAINS '置顶'")).firstMatch.exists, "排序态卡片应出现置顶按钮")
        XCTAssertTrue(app.buttons.matching(NSPredicate(format: "label CONTAINS '删除'")).firstMatch.exists, "排序态卡片应出现删除按钮")
        app.buttons["xage.data.sort.bottomDone"].tap()
        XCTAssertTrue(app.buttons["xage.data.sort"].waitForExistence(timeout: 6), "底部完成排序后应退出排序态")

        let scroll = app.scrollViews["xage.data.scroll"]
        swipeUp(until: app.buttons["xage.data.metric.add"], in: scroll, maxSwipes: 8)
        tapAndWait(app.buttons["xage.data.metric.add"], for: app.textFields["xage.metric.manager.search"])

        let candidate = app.buttons["xage.metric.manager.candidate.vo2Max"]
        if candidate.waitForExistence(timeout: 3) {
            candidate.tap()
            XCTAssertTrue(app.buttons["xage.data.metric.add"].waitForExistence(timeout: 8), "点击候选指标后应关闭候选表并回到数据页")
        } else {
            app.buttons["完成"].tap()
            XCTAssertTrue(app.buttons["xage.data.metric.add"].waitForExistence(timeout: 8), "无候选指标时也应能关闭候选表")
        }
        attachScreenshot(named: "metric-manager")
    }

    private func verifyChatButtonsAndContextPrompts() {
        app.buttons["xage.segment.问答"].tap()
        XCTAssertTrue(app.buttons["xage.chat.plus"].waitForExistence(timeout: 8), "切到问答页后应显示添加内容按钮")

        tapAndWait(app.buttons["xage.chat.plus"], for: app.buttons["xage.chat.attachment.documents"])
        XCTAssertTrue(app.buttons["xage.chat.attachment.camera"].exists, "附件菜单应包含拍照采集报告")
        XCTAssertTrue(app.buttons["xage.chat.attachment.photos"].exists, "附件菜单应包含相册上传报告")
        app.buttons["xage.chat.attachment.new"].tap()
        XCTAssertTrue(app.buttons["xage.chat.plus"].waitForExistence(timeout: 5), "新对话按钮应关闭附件菜单")

        let prompts = [
            "你好",
            "我是不是已经同步过 Apple 健康？",
            "nt 是帮我老婆问的",
            "帮我分析一下心率变异性",
            "帮我整理病史摘要",
            "我老婆 NT 2.8 正常吗？",
            "我今天血压怎么样？",
            "我的血压为什么变化这么大？",
            "我的报告分析好了吗？",
            "看看我妈的血糖",
            "我有血糖设备吗？",
            "尿酸 419.7 对我风险大吗？"
        ]

        for (index, prompt) in prompts.enumerated() {
            sendPrompt(prompt)
            dismissKnownAlertsIfNeeded()
            if index == 5 || index == prompts.count - 1 {
                attachScreenshot(named: "chat-prompts-sent-\(index + 1)")
            }
        }
    }

    private func verifyXAgeInfoButton() {
        app.buttons["xage.segment.X年龄"].tap()
        tapAndWait(app.buttons["xage.xage.info.inline"], for: app.buttons["xage.info.close"])
        attachScreenshot(named: "xage-info")
        app.buttons["xage.info.close"].tap()
        XCTAssertTrue(app.buttons["xage.segment.X年龄"].waitForExistence(timeout: 5), "关闭 X年龄原理后仍应停留在 X年龄页")
    }

    private func sendPrompt(_ text: String) {
        let input = app.textFields["xage.chat.input"]
        XCTAssertTrue(input.waitForExistence(timeout: 6), "问答输入框应存在")
        input.tap()
        input.typeText(text)
        app.buttons["xage.chat.send"].tap()
        XCTAssertTrue(app.buttons["xage.chat.send"].waitForExistence(timeout: 8), "发送后输入栏应保持可用")
    }

    private func tapAndWait(_ element: XCUIElement, for expected: XCUIElement, timeout: TimeInterval = 8) {
        XCTAssertTrue(element.waitForExistence(timeout: timeout), "待点击控件不存在：\(element)")
        element.tap()
        XCTAssertTrue(expected.waitForExistence(timeout: timeout), "点击后未出现预期控件：\(expected)")
    }

    private func swipeUp(until element: XCUIElement, in scrollView: XCUIElement, maxSwipes: Int) {
        XCTAssertTrue(scrollView.waitForExistence(timeout: 6), "滚动区域应存在")
        for _ in 0..<maxSwipes where !element.exists {
            scrollView.swipeUp()
        }
        XCTAssertTrue(element.waitForExistence(timeout: 4), "多次上滑后仍未找到目标控件：\(element)")
    }

    private func closePresentedPanel() {
        if app.buttons["返回"].waitForExistence(timeout: 4) {
            app.buttons["返回"].tap()
        } else if app.buttons["关闭"].waitForExistence(timeout: 2) {
            app.buttons["关闭"].tap()
        }
        _ = app.buttons["xage.segment.数据"].waitForExistence(timeout: 8)
    }

    private func dismissKnownAlertsIfNeeded() {
        let alert = app.alerts.firstMatch
        guard alert.waitForExistence(timeout: 2) else { return }
        if alert.buttons["确定"].exists {
            alert.buttons["确定"].tap()
        } else if alert.buttons["知道了"].exists {
            alert.buttons["知道了"].tap()
        } else if alert.buttons.firstMatch.exists {
            alert.buttons.firstMatch.tap()
        }
    }

    private func attachScreenshot(named name: String) {
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
