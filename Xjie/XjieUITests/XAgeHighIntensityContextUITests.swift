import XCTest

final class XAgeHighIntensityContextUITests: XCTestCase {
    private var app: XCUIApplication!

    override func setUpWithError() throws {
        continueAfterFailure = false
        app = XCUIApplication()
        app.launchArguments = [
            "XJIE_UI_TEST_RESET_AUTH",
            "XJIE_UI_TEST_RESET_DATA_CARDS",
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

    func testDataCardManagerPersistsSelectedCardsAcrossRelaunch() throws {
        app.launch()
        enterDebugValidationSession()
        openDataCardManager()

        searchMetricInManager("步数")
        let stepsPin = app.buttons["置顶步数"]
        XCTAssertTrue(stepsPin.waitForExistence(timeout: 4), "搜索步数后应显示可置顶按钮")
        stepsPin.tap()
        XCTAssertTrue(app.descendants(matching: .any)["xage.metric.manager.pinned.steps"].waitForExistence(timeout: 4), "添加步数后应出现在置顶区")
        closeMetricManagerPage()

        let dataScroll = app.scrollViews["xage.data.scroll"]
        let stepsCard = app.descendants(matching: .any).matching(identifier: "xage.data.metric.steps").firstMatch
        swipeUp(until: stepsCard, in: dataScroll, maxSwipes: 8)
        attachScreenshot(named: "metric-persist-before-relaunch")

        app.terminate()
        app = XCUIApplication()
        app.launchArguments = [
            "XJIE_DISABLE_APP_UPDATE_CHECK",
            "XJIE_DISABLE_PUSH_PERMISSION"
        ]
        app.launch()
        enterDebugValidationSession()

        let persistedCard = app.descendants(matching: .any).matching(identifier: "xage.data.metric.steps").firstMatch
        swipeUp(until: persistedCard, in: app.scrollViews["xage.data.scroll"], maxSwipes: 8)
        openDataCardManager()
        XCTAssertTrue(app.descendants(matching: .any)["xage.metric.manager.pinned.steps"].waitForExistence(timeout: 4), "重启后步数仍应在数据卡片管理置顶区")
        XCTAssertFalse(app.buttons["xage.metric.manager.pin.steps"].exists, "已置顶指标不应继续出现在候选添加按钮中")
        closeMetricManagerPage()
        attachScreenshot(named: "metric-persist-after-relaunch")
    }

    func testMetricManagerPageAndChatKeyboardLifecycle() throws {
        app.launch()
        enterDebugValidationSession()

        openDataCardManager()
        XCTAssertTrue(app.descendants(matching: .any)["xage.metric.manager.page"].waitForExistence(timeout: 4), "应进入数据卡片管理独立页面")
        let managerNavigationBar = app.navigationBars["数据卡片管理"]
        XCTAssertTrue(managerNavigationBar.waitForExistence(timeout: 4), "数据卡片管理应使用带返回导航的独立页面")
        XCTAssertFalse(app.buttons["xage.segment.数据"].isHittable, "进入管理页后不应仍可操作数据页顶部三栏")
        attachScreenshot(named: "metric-manager-page")

        let explanationButton = app.buttons.matching(NSPredicate(format: "label ENDSWITH '解释'")).firstMatch
        XCTAssertTrue(explanationButton.waitForExistence(timeout: 4), "管理页应保留指标解释入口")
        explanationButton.tap()
        let closeMetricDetail = app.buttons.matching(NSPredicate(format: "label BEGINSWITH '关闭' AND label ENDSWITH '详情'")).firstMatch
        XCTAssertTrue(closeMetricDetail.waitForExistence(timeout: 4), "从管理页应能打开指标详情")
        closeMetricDetail.tap()
        XCTAssertTrue(managerNavigationBar.waitForExistence(timeout: 4), "关闭指标详情后应返回数据卡片管理页")

        let managerScroll = app.scrollViews["xage.metric.manager.scroll"]
        XCTAssertTrue(managerScroll.waitForExistence(timeout: 4), "管理页滚动区域应存在")
        managerScroll.swipeUp()
        XCTAssertTrue(managerNavigationBar.exists, "滚动管理内容不应把页面当作弹窗关闭")
        closeMetricManagerPage()
        XCTAssertTrue(app.buttons["xage.segment.数据"].waitForExistence(timeout: 5), "返回后应回到数据页")

        app.buttons["xage.segment.问答"].tap()
        let input = app.textFields["xage.chat.input"]
        XCTAssertTrue(input.waitForExistence(timeout: 6), "问答输入框应存在")
        let initialHeight = input.frame.height

        input.tap()
        XCTAssertTrue(app.keyboards.firstMatch.waitForExistence(timeout: 4), "点击输入框后应显示输入法")
        input.typeText("请结合我最近的睡眠心率血压运动饮食压力恢复情况做一次完整分析并逐项说明原因和下一步建议请不要遗漏任何一个问题")
        XCTAssertTrue(waitUntil(timeout: 4) { input.frame.height >= initialHeight + 12 }, "长文本应让输入框从单行自动增长为多行")
        XCTAssertLessThan(input.frame.height, app.frame.height * 0.3, "输入框应限制最大行数，避免长文本占满页面")
        attachScreenshot(named: "chat-multiline-input")

        let chatScroll = app.scrollViews["xage.chat.scroll"]
        XCTAssertTrue(chatScroll.waitForExistence(timeout: 4), "问答滚动区域应存在")
        chatScroll.coordinate(withNormalizedOffset: CGVector(dx: 0.03, dy: 0.18)).tap()
        XCTAssertTrue(app.keyboards.firstMatch.waitForNonExistence(timeout: 4), "点击对话区空白后应收起输入法")

        input.tap()
        XCTAssertTrue(app.keyboards.firstMatch.waitForExistence(timeout: 4), "再次点击输入框后应重新显示输入法")
        let dragStart = chatScroll.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.25))
        let dragEnd = chatScroll.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.80))
        dragStart.press(forDuration: 0.05, thenDragTo: dragEnd)
        XCTAssertTrue(app.keyboards.firstMatch.waitForNonExistence(timeout: 4), "向下拖动对话区应交互式收起输入法")

        input.tap()
        XCTAssertTrue(app.keyboards.firstMatch.waitForExistence(timeout: 4), "切页前输入法应处于显示状态")
        app.buttons["xage.segment.数据"].tap()
        XCTAssertTrue(waitUntil(timeout: 5) { self.app.scrollViews["xage.data.scroll"].isHittable }, "切换后应进入数据页")
        XCTAssertTrue(app.keyboards.firstMatch.waitForNonExistence(timeout: 4), "切换顶部页面时应自动收起输入法")
        attachScreenshot(named: "chat-keyboard-dismissed-on-tab-switch")
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

        if !app.buttons["xage.account.用药管理"].exists {
            tapAndWait(app.buttons["xage.more"], for: app.buttons["xage.account.用药管理"])
        }
        tapAndWait(app.buttons["xage.account.用药管理"], for: app.scrollViews["xage.medication.root"])
        XCTAssertTrue(app.buttons["xage.medication.add"].exists, "用药管理应进入 XAGE 液态玻璃用药页")
        attachScreenshot(named: "panel-medication-xage")
        closePresentedPanel()
        XCTAssertTrue(app.buttons["xage.segment.数据"].waitForExistence(timeout: 6), "用药管理关闭后应回到数据页")
    }

    private func verifyMetricManagerAndSortControls() {
        tapAndWait(app.buttons["xage.data.sort"], for: app.buttons["xage.data.sort.bottomDone"])
        XCTAssertTrue(app.buttons.matching(NSPredicate(format: "label CONTAINS '置顶'")).firstMatch.exists, "排序态卡片应出现置顶按钮")
        XCTAssertTrue(app.buttons.matching(NSPredicate(format: "label CONTAINS '删除'")).firstMatch.exists, "排序态卡片应出现删除按钮")
        app.buttons["xage.data.sort.bottomDone"].tap()
        XCTAssertTrue(app.buttons["xage.data.sort"].waitForExistence(timeout: 6), "底部完成排序后应退出排序态")

        let scroll = app.scrollViews["xage.data.scroll"]
        let managerEntry = app.buttons["数据卡片管理"]
        swipeUp(until: managerEntry, in: scroll, maxSwipes: 8)
        XCTAssertFalse(app.buttons["xage.data.metric.add"].exists, "数据页不应再保留独立添加指标入口")
        tapAndWait(managerEntry, for: app.textFields["xage.metric.manager.search"])
        XCTAssertTrue(app.staticTexts["数据卡片管理"].waitForExistence(timeout: 3), "管理弹层标题应为数据卡片管理")

        searchMetricInManager("步数")
        let candidatePin = app.buttons["置顶步数"]
        if candidatePin.waitForExistence(timeout: 3) {
            candidatePin.tap()
            XCTAssertTrue(app.navigationBars["数据卡片管理"].waitForExistence(timeout: 3), "添加候选指标后应停留在数据卡片管理页面")
        }
        closeMetricManagerPage()
        XCTAssertTrue(managerEntry.waitForExistence(timeout: 8), "返回后应回到数据页的数据卡片管理入口")
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
        for _ in 0..<maxSwipes where !isVisibleOnScreen(element) {
            scrollView.swipeUp()
        }
        XCTAssertTrue(waitUntil(timeout: 4) { self.isVisibleOnScreen(element) }, "多次上滑后目标控件仍未进入屏幕：\(element)")
    }

    private func findBySwipingUp(_ element: XCUIElement, in scrollView: XCUIElement, maxSwipes: Int) -> Bool {
        guard scrollView.waitForExistence(timeout: 4) else { return false }
        for _ in 0..<maxSwipes where !isVisibleOnScreen(element) {
            scrollView.swipeUp()
        }
        return waitUntil(timeout: 2) { self.isVisibleOnScreen(element) }
    }

    private func isVisibleOnScreen(_ element: XCUIElement) -> Bool {
        guard element.exists else { return false }
        let frame = element.frame
        guard !frame.isEmpty, !frame.isNull else { return false }
        let visibleFrame = frame.intersection(app.frame)
        return !visibleFrame.isNull && visibleFrame.width > 1 && visibleFrame.height > 1
    }

    private func openDataCardManager() {
        let scroll = app.scrollViews["xage.data.scroll"]
        let managerEntry = app.buttons["数据卡片管理"]
        swipeUp(until: managerEntry, in: scroll, maxSwipes: 8)
        tapAndWait(managerEntry, for: app.navigationBars["数据卡片管理"])
        XCTAssertTrue(app.textFields["xage.metric.manager.search"].waitForExistence(timeout: 4), "管理页搜索框应存在")
        XCTAssertTrue(app.navigationBars["数据卡片管理"].waitForExistence(timeout: 3), "应打开数据卡片管理页面")
    }

    private func searchMetricInManager(_ text: String) {
        let search = app.textFields["xage.metric.manager.search"]
        XCTAssertTrue(search.waitForExistence(timeout: 4), "管理弹层搜索框应存在")
        search.tap()
        search.typeText(text)
    }

    private func closeMetricManagerPage() {
        let navigationBar = app.navigationBars["数据卡片管理"]
        XCTAssertTrue(navigationBar.waitForExistence(timeout: 4), "数据卡片管理导航栏应存在")
        let backButton = navigationBar.buttons.firstMatch
        XCTAssertTrue(backButton.waitForExistence(timeout: 3), "数据卡片管理页应有返回按钮")
        backButton.tap()
        XCTAssertTrue(app.descendants(matching: .any)["xage.metric.manager.page"].waitForNonExistence(timeout: 5), "返回后管理页应消失")
        XCTAssertTrue(waitUntil(timeout: 5) { self.app.scrollViews["xage.data.scroll"].isHittable }, "返回后应回到可操作的数据页")
    }

    private func waitUntil(timeout: TimeInterval, condition: @escaping () -> Bool) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if condition() { return true }
            RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        }
        return condition()
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
