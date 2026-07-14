import XCTest

final class XAgeHighIntensityContextUITests: XAgeUITestCase {
    func testHighIntensityContextFlowUsesDeterministicChatTransportAndVerifiesAllPrompts() throws {
        app.launchArguments.append("XJIE_UI_TEST_STUB_CHAT")
        launchApplication()
        enterDebugValidationSession()
        verifyDataButtonsAndPanels()
        verifyMetricManagerAndSortControls()
        verifyChatButtonsAndContextPrompts()
        verifyXAgeInfoButton()
        attachScreenshot(named: "xage-high-intensity-final")
    }

    func testDataCardManagerPersistsSelectedCardsAcrossRelaunch() throws {
        launchApplication()
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
        relaunchApplication(resetAuth: false, resetDataCards: false)
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
        app.launchArguments.append("XJIE_UI_TEST_STUB_CHAT")
        launchApplication()
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
        XCTAssertTrue(app.buttons["xage.segment.问答"].isHittable, "职责拆分后问答入口仍应由主页面直接承载")
        XCTAssertTrue(app.buttons["xage.segment.X年龄"].isHittable, "职责拆分后 X年龄入口仍应由主页面直接承载")

        app.buttons["xage.segment.问答"].tap()
        let input = app.textFields["xage.chat.input"]
        XCTAssertTrue(input.waitForExistence(timeout: 6), "问答输入框应存在")
        let initialHeight = input.frame.height

        input.tap()
        XCTAssertTrue(app.keyboards.firstMatch.waitForExistence(timeout: 4), "点击输入框后应显示输入法")
        let longPrompt = "请结合我最近的睡眠心率血压运动饮食压力恢复情况做一次完整分析并逐项说明原因和下一步建议请不要遗漏任何一个问题"
        input.typeText(longPrompt)
        XCTAssertTrue(waitUntil(timeout: 4) { input.frame.height >= initialHeight + 12 }, "长文本应让输入框从单行自动增长为多行")
        XCTAssertLessThan(input.frame.height, app.frame.height * 0.3, "输入框应限制最大行数，避免长文本占满页面")
        let multilineContinuation = "\n补充：请按优先级排序"
        input.typeText(multilineContinuation)
        let submittedPrompt = longPrompt + multilineContinuation
        XCTAssertTrue(waitUntil(timeout: 4) {
            (input.value as? String) == submittedPrompt
        }, "回车应插入新行而不是发送或关闭键盘，保持微信式多行编辑")
        attachScreenshot(named: "chat-multiline-input")

        let chatScroll = app.scrollViews["xage.chat.scroll"]
        XCTAssertTrue(chatScroll.waitForExistence(timeout: 4), "问答滚动区域应存在")
        let send = app.buttons["xage.chat.send"]
        XCTAssertTrue(waitUntil(timeout: 4) { send.isEnabled && send.isHittable }, "长问题输入完成后发送按钮应可用")
        send.tap()
        assertChatSettled(expectedMessageCount: 2, context: "小屏长问题发送")
        XCTAssertTrue(app.keyboards.firstMatch.waitForNonExistence(timeout: 4), "发送长问题后应关闭输入法")
        XCTAssertTrue(app.staticTexts[submittedPrompt].waitForExistence(timeout: 5), "含手动换行的长问题应完整显示为用户消息")
        XCTAssertTrue(
            app.staticTexts["UI 自动化回复：\(submittedPrompt)"].waitForExistence(timeout: 5),
            "小屏内容首次溢出后仍应显示确定性助手回复"
        )

        input.tap()
        XCTAssertTrue(app.keyboards.firstMatch.waitForExistence(timeout: 4), "发送完成后输入框应可再次获得焦点")
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

    func testNavigationTouchTargetsAndFormDismissalConventions() throws {
        launchApplication()
        enterDebugValidationSession()

        verifyHorizontalSectionNavigationAndTopInfo()
        verifyManagerSearchKeyboardDismissal()
        verifySettingsFormDismissalConventions()
        verifyManualEntryDismissal()
        verifySortTouchTargetsAndDisabledStates()
        attachScreenshot(named: "ux-conventions-final-data")
    }

    func testLoginKeyboardToolbarAndPasswordVisibilityFocus() throws {
        launchApplication()

        let modeSwitch = app.buttons["login.mode.switch"]
        XCTAssertTrue(modeSwitch.waitForExistence(timeout: 8), "登录页应显示登录方式切换按钮")
        if modeSwitch.label == "使用手机号登录" {
            modeSwitch.tap()
        }
        let rootScroll = app.scrollViews.firstMatch

        let phone = app.textFields["login.phone"]
        XCTAssertTrue(phone.waitForExistence(timeout: 5), "手机号登录应显示手机号输入框")
        phone.tap()
        XCTAssertTrue(app.keyboards.firstMatch.waitForExistence(timeout: 4), "手机号输入框应打开 phonePad")
        phone.typeText("13800138000")
        tapKeyboardDone(message: "手机号 phonePad 应提供完成按钮")

        let securePassword = passwordSecureField()
        scrollIntoView(securePassword, in: rootScroll, maxSwipes: 4)
        XCTAssertTrue(securePassword.exists, "登录密码默认应使用安全输入框")
        securePassword.tap()
        XCTAssertTrue(app.keyboards.firstMatch.waitForExistence(timeout: 4), "点击密码框后应显示输入法")
        securePassword.typeText("testPass123")

        let reveal = app.buttons["显示密码"]
        XCTAssertTrue(reveal.waitForExistence(timeout: 4), "密码框应提供显示密码按钮")
        reveal.tap()
        XCTAssertTrue(app.buttons["隐藏"].waitForExistence(timeout: 4), "显示密码后按钮应切换为隐藏")
        XCTAssertTrue(app.keyboards.firstMatch.waitForExistence(timeout: 4), "切换密码显隐时不应丢失键盘焦点")
        let visiblePassword = passwordVisibleField()
        XCTAssertTrue(visiblePassword.waitForExistence(timeout: 4), "显示密码后应切换为普通文本框")
        XCTAssertEqual(visiblePassword.value as? String, "testPass123", "切换密码显隐不应丢失已输入内容")

        app.buttons["隐藏"].tap()
        XCTAssertTrue(passwordSecureField().waitForExistence(timeout: 4), "再次隐藏后应恢复安全输入框")
        XCTAssertTrue(app.keyboards.firstMatch.waitForExistence(timeout: 4), "再次隐藏密码时仍应保持输入焦点")
        attachScreenshot(named: "login-password-visibility-focus")
        tapKeyboardDone(message: "密码键盘应提供完成按钮")

        app.buttons["login.signup.toggle"].tap()
        XCTAssertTrue(app.textFields["login.username"].waitForExistence(timeout: 5), "切换注册后应显示用户名输入框")

        for (identifier, name) in [
            ("login.age", "年龄 numberPad"),
            ("login.height", "身高 decimalPad"),
            ("login.weight", "体重 decimalPad")
        ] {
            let field = app.textFields[identifier]
            scrollIntoView(field, in: rootScroll, maxSwipes: 6)
            field.tap()
            XCTAssertTrue(app.keyboards.firstMatch.waitForExistence(timeout: 4), "\(name) 应显示数字输入法")
            tapKeyboardDone(message: "\(name) 应提供完成按钮")
        }
        attachScreenshot(named: "signup-numeric-keyboard-toolbar")
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
        XCTAssertTrue(app.buttons["返回"].waitForExistence(timeout: 4), "用药管理应显示返回设置按钮")
        app.buttons["返回"].tap()
        XCTAssertTrue(app.buttons["xage.account.用药管理"].waitForExistence(timeout: 6), "用药管理返回后应先回到设置页")
        closeSettingsMenu()
        XCTAssertTrue(app.buttons["xage.segment.数据"].waitForExistence(timeout: 6), "关闭设置后应回到数据页")
    }

    private func verifyMetricManagerAndSortControls() {
        tapAndWait(app.buttons["xage.data.sort"], for: app.buttons["xage.data.sort.bottomDone"])
        XCTAssertTrue(app.buttons.matching(NSPredicate(format: "label CONTAINS '置顶'")).firstMatch.exists, "排序态卡片应出现置顶按钮")
        XCTAssertTrue(app.buttons.matching(NSPredicate(format: "label CONTAINS '移出首页'")).firstMatch.exists, "排序态卡片应出现移出首页按钮")
        app.buttons["xage.data.sort.bottomDone"].tap()
        XCTAssertTrue(app.buttons["xage.data.sort"].waitForExistence(timeout: 6), "底部完成排序后应退出排序态")

        let managerEntry = dataCardManagerEntry()
        openDataCardManager()
        XCTAssertFalse(app.buttons["xage.data.metric.add"].exists, "数据页不应再保留独立添加指标入口")
        XCTAssertTrue(app.staticTexts["数据卡片管理"].waitForExistence(timeout: 3), "管理页标题应为数据卡片管理")

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

        sendPrompt(
            "[查看指南](https://example.com)",
            expectedMessageCount: 2,
            expectedAssistantLinkLabel: "查看指南"
        )

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
            sendPrompt(prompt, expectedMessageCount: (index + 2) * 2)
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

    private func verifyHorizontalSectionNavigationAndTopInfo() {
        let sectionContent = app.descendants(matching: .any).matching(identifier: "xage.section.content").firstMatch
        XCTAssertTrue(sectionContent.waitForExistence(timeout: 6), "三栏内容区应暴露稳定的横滑区域")

        swipeHorizontally(in: sectionContent, direction: .left)
        XCTAssertTrue(waitUntil(timeout: 6) { self.app.textFields["xage.chat.input"].isHittable }, "数据页左滑应进入问答页")

        swipeHorizontally(in: sectionContent, direction: .left)
        let topInfo = app.buttons["xage.xage.info.top"]
        XCTAssertTrue(waitUntil(timeout: 6) { topInfo.isHittable }, "问答页左滑应进入 X年龄页")

        swipeHorizontally(in: sectionContent, direction: .left)
        RunLoop.current.run(until: Date().addingTimeInterval(0.45))
        XCTAssertTrue(topInfo.isHittable, "X年龄页继续左滑不应循环回数据页")
        XCTAssertFalse(app.textFields["xage.chat.input"].isHittable, "X年龄边界左滑后不应误回问答页")

        assertMinimumTouchTarget(topInfo, name: "顶部 X年龄原理")
        topInfo.tap()
        XCTAssertTrue(app.buttons["xage.info.close"].waitForExistence(timeout: 5), "顶部 X年龄原理按钮应能打开说明")
        attachScreenshot(named: "ux-top-xage-info")
        app.buttons["xage.info.close"].tap()
        XCTAssertTrue(topInfo.waitForExistence(timeout: 5), "关闭原理后应停留在 X年龄页")

        swipeHorizontally(in: sectionContent, direction: .right)
        XCTAssertTrue(waitUntil(timeout: 6) { self.app.textFields["xage.chat.input"].isHittable }, "X年龄页右滑应回到问答页")
        swipeHorizontally(in: sectionContent, direction: .right)
        XCTAssertTrue(waitUntil(timeout: 6) { self.app.scrollViews["xage.data.scroll"].isHittable }, "问答页右滑应回到数据页")
        attachScreenshot(named: "ux-horizontal-sections-returned-data")
    }

    private func verifySortTouchTargetsAndDisabledStates() {
        tapAndWait(app.buttons["xage.data.sort"], for: app.buttons["xage.data.sort.bottomDone"])

        let moveUp = app.buttons["上移心率变异性"]
        let moveDown = app.buttons["下移心率变异性"]
        let pin = app.buttons["置顶心率变异性"]
        let remove = app.buttons["将心率变异性移出首页"]
        XCTAssertTrue(moveUp.waitForExistence(timeout: 6), "排序首卡应显示上移按钮")
        XCTAssertTrue(moveDown.waitForExistence(timeout: 4), "排序首卡应显示下移按钮")
        XCTAssertTrue(pin.waitForExistence(timeout: 4), "排序首卡应显示置顶按钮")
        XCTAssertTrue(remove.waitForExistence(timeout: 4), "排序首卡应显示移出首页按钮")
        XCTAssertFalse(moveUp.isEnabled, "首卡上移应处于禁用态，不能点击后静默无反应")
        XCTAssertFalse(pin.isEnabled, "首卡已位于顶部，置顶应处于禁用态")
        XCTAssertTrue(moveDown.isEnabled, "存在下一张卡片时首卡下移应可用")
        XCTAssertTrue(remove.isEnabled, "移出首页操作应可用")
        for (button, name) in [
            (moveUp, "排序上移"),
            (moveDown, "排序下移"),
            (pin, "排序置顶"),
            (remove, "移出首页")
        ] {
            assertMinimumTouchTarget(button, name: name)
        }
        attachScreenshot(named: "ux-sort-disabled-states-and-targets")

        app.buttons["xage.data.sort.bottomDone"].tap()
        XCTAssertTrue(app.buttons["xage.data.sort"].waitForExistence(timeout: 5), "完成排序后应退出排序态")
    }

    private func verifyManagerSearchKeyboardDismissal() {
        openDataCardManager()
        searchMetricInManager("步数")
        XCTAssertTrue(app.keyboards.firstMatch.waitForExistence(timeout: 4), "搜索指标时应显示输入法")

        let detail = app.buttons["xage.metric.manager.detail.steps"]
        XCTAssertTrue(detail.waitForExistence(timeout: 5), "搜索步数后应显示详情按钮")
        assertMinimumTouchTarget(detail, name: "管理页步数详情")

        let pin = app.buttons["xage.metric.manager.pin.steps"]
        if pin.waitForExistence(timeout: 1) {
            assertMinimumTouchTarget(pin, name: "管理页置顶步数")
        } else {
            for (button, name) in [
                (app.buttons["xage.metric.manager.unpin.steps"], "管理页取消置顶步数"),
                (app.buttons["xage.metric.manager.moveUp.steps"], "管理页上移步数"),
                (app.buttons["xage.metric.manager.moveDown.steps"], "管理页下移步数")
            ] {
                XCTAssertTrue(button.waitForExistence(timeout: 3), "\(name)按钮应存在")
                assertMinimumTouchTarget(button, name: name)
            }
        }
        detail.tap()
        XCTAssertTrue(app.keyboards.firstMatch.waitForNonExistence(timeout: 5), "从搜索结果打开详情时应自动关闭输入法")
        let closeStepDetail = app.buttons["关闭步数详情"]
        XCTAssertTrue(closeStepDetail.waitForExistence(timeout: 5), "步数详情应显示关闭按钮")
        attachScreenshot(named: "ux-manager-detail-keyboard-dismissed")
        closeStepDetail.tap()
        XCTAssertTrue(app.navigationBars["数据卡片管理"].waitForExistence(timeout: 5), "关闭详情后应回到管理页")
        closeMetricManagerPage()
    }

    private func verifyManualEntryDismissal() {
        let scroll = app.scrollViews["xage.data.scroll"]
        let hrvCard = app.descendants(matching: .any).matching(identifier: "xage.data.metric.hrv").firstMatch
        scrollIntoView(hrvCard, in: scroll, maxSwipes: 8)
        hrvCard.tap()

        let manualEntry = app.buttons["xage.metric.manualEntry"]
        XCTAssertTrue(manualEntry.waitForExistence(timeout: 5), "指标详情应提供手动记录入口")
        manualEntry.tap()
        let value = app.textFields["xage.metric.manualEntry.value"]
        XCTAssertTrue(value.waitForExistence(timeout: 5), "手动记录应显示数值输入框")
        value.tap()
        XCTAssertTrue(app.keyboards.firstMatch.waitForExistence(timeout: 4), "数值输入框应打开 decimalPad")
        for (identifier, name) in [
            ("xage.metric.manualEntry.keyboard.previous", "手动记录上一项"),
            ("xage.metric.manualEntry.keyboard.next", "手动记录下一项"),
            ("xage.metric.manualEntry.keyboard.done", "手动记录完成")
        ] {
            let button = app.buttons[identifier]
            XCTAssertTrue(button.waitForExistence(timeout: 3), "\(name)按钮应存在")
            assertMinimumTouchTarget(button, name: name)
        }
        value.typeText("12.3")
        tapKeyboardDone(message: "手动记录 decimalPad 应提供完成按钮")

        let back = app.buttons["xage.metric.manualEntry.back"]
        XCTAssertTrue(back.waitForExistence(timeout: 4), "手动记录应显示返回详情按钮")
        back.tap()
        let discardAlert = app.alerts["放弃本次记录？"]
        XCTAssertTrue(discardAlert.waitForExistence(timeout: 4), "输入数值后返回应先询问是否放弃")
        attachScreenshot(named: "ux-manual-entry-discard-confirmation")
        discardAlert.buttons["放弃修改"].tap()
        XCTAssertTrue(manualEntry.waitForExistence(timeout: 5), "放弃修改后应回到原指标详情，而不是直接关闭全部页面")

        let closeMetricDetail = app.buttons.matching(NSPredicate(format: "label BEGINSWITH '关闭' AND label ENDSWITH '详情'")).firstMatch
        XCTAssertTrue(closeMetricDetail.waitForExistence(timeout: 4), "返回指标详情后应能关闭详情")
        closeMetricDetail.tap()
        XCTAssertTrue(waitUntil(timeout: 5) { self.app.scrollViews["xage.data.scroll"].isHittable }, "关闭指标详情后应回到数据页")
    }

    private func verifySettingsFormDismissalConventions() {
        tapAndWait(app.buttons["xage.more"], for: app.buttons["xage.account.报告"])

        let family = app.buttons["xage.account.关联用户"]
        scrollIntoViewOnActiveScreen(family, direction: .up, maxSwipes: 8)
        family.tap()
        let phone = app.textFields["xage.family.phone"]
        XCTAssertTrue(phone.waitForExistence(timeout: 6), "关联用户页应显示手机号输入框")
        XCTAssertTrue(waitUntil(timeout: 6) { phone.isHittable }, "家庭资料加载结束后手机号输入框应可操作")
        XCTAssertFalse(app.alerts.firstMatch.exists, "确定性家庭资料不得通过关闭网络错误弹窗继续测试")
        phone.tap()
        XCTAssertTrue(app.keyboards.firstMatch.waitForExistence(timeout: 4), "关联用户手机号应打开 phonePad")
        phone.typeText("13800138000")
        tapKeyboardDone(message: "关联用户 phonePad 应提供完成按钮")

        let familyBack = app.buttons["返回设置"]
        XCTAssertTrue(familyBack.waitForExistence(timeout: 4), "关联用户页应显示返回设置按钮")
        familyBack.tap()
        let familyDiscard = app.alerts["放弃未提交的内容？"]
        XCTAssertTrue(familyDiscard.waitForExistence(timeout: 4), "关联用户存在脏输入时返回应先确认放弃")
        attachScreenshot(named: "ux-family-discard-confirmation")
        familyDiscard.buttons["放弃修改"].tap()
        XCTAssertTrue(app.buttons["xage.account.关联用户"].waitForExistence(timeout: 6), "放弃家庭表单后应回到设置页")

        let deleteAccount = app.buttons["xage.account.注销账号"]
        scrollIntoViewOnActiveScreen(deleteAccount, direction: .up, maxSwipes: 6)
        deleteAccount.tap()
        let deleteInput = app.textFields["xage.account.delete.input"]
        XCTAssertTrue(deleteInput.waitForExistence(timeout: 5), "注销确认页应显示确认文字输入框")
        deleteInput.tap()
        XCTAssertTrue(app.keyboards.firstMatch.waitForExistence(timeout: 4), "注销确认输入框应显示输入法")
        deleteInput.typeText("注销")
        tapKeyboardDone(message: "注销确认输入框应提供完成按钮")
        let destructiveConfirm = app.buttons["xage.account.delete.confirm"]
        XCTAssertTrue(destructiveConfirm.isEnabled, "输入注销后确认按钮应变为可用")
        XCTAssertTrue(app.buttons["取消"].waitForExistence(timeout: 4), "注销页应允许安全取消")
        attachScreenshot(named: "ux-delete-account-safe-cancel")
        app.buttons["取消"].tap()
        XCTAssertTrue(app.buttons["xage.account.注销账号"].waitForExistence(timeout: 5), "取消注销后应回到设置页且保持登录")

        closeSettingsMenu()
        XCTAssertTrue(app.buttons["xage.segment.数据"].waitForExistence(timeout: 6), "关闭设置后应回到数据页")
    }

    private func sendPrompt(
        _ text: String,
        expectedMessageCount: Int,
        expectedAssistantLinkLabel: String? = nil
    ) {
        let input = app.textFields["xage.chat.input"]
        XCTAssertTrue(input.waitForExistence(timeout: 6), "问答输入框应存在")
        XCTAssertTrue(waitUntil(timeout: 12) { input.isHittable }, "发送下一条问题前输入框应可操作")
        input.tap()
        XCTAssertTrue(app.keyboards.firstMatch.waitForExistence(timeout: 4), "点击问答输入框后应获得焦点并显示输入法")
        input.typeText(text)
        let send = app.buttons["xage.chat.send"]
        XCTAssertTrue(waitUntil(timeout: 20) { send.exists && send.isEnabled && send.isHittable }, "上一条回复完成后发送按钮应恢复可用")
        send.tap()
        assertChatSettled(expectedMessageCount: expectedMessageCount, context: "发送问题：\(text)")
        XCTAssertTrue(app.keyboards.firstMatch.waitForNonExistence(timeout: 5), "发送后应释放输入框焦点并关闭输入法")
        XCTAssertTrue(waitUntil(timeout: 5) {
            guard let value = input.value as? String else { return true }
            return value.isEmpty || value == "输入或长按说话"
        }, "发送后输入框应清空，避免下一条问题重复拼接")
        XCTAssertTrue(app.staticTexts[text].waitForExistence(timeout: 5), "发送后应出现内容完全一致的用户消息")
        if let expectedAssistantLinkLabel {
            // SwiftUI Link is exposed by XCTest as an actionable Button inside
            // accessibilityRepresentation; the exact Link(destination:) source
            // contract is independently locked by the static mutation gate.
            let link = app.buttons[expectedAssistantLinkLabel]
            XCTAssertTrue(
                link.waitForExistence(timeout: 5),
                "富文本助手回复必须向辅助功能树暴露可激活 Link 动作"
            )
            XCTAssertTrue(link.isHittable, "富文本助手链接必须可以由用户激活")
        } else {
            XCTAssertTrue(
                app.staticTexts["UI 自动化回复：\(text)"].waitForExistence(timeout: 5),
                "确定性 UI 传输应为每条问题返回对应回显，证明发送链路已经完成"
            )
        }
        XCTAssertFalse(app.alerts.firstMatch.exists, "确定性 UI 传输不应依赖或吞掉网络错误弹窗")
    }

    private func assertChatSettled(expectedMessageCount: Int, context: String) {
        let lifecycle = app.descendants(matching: .any)["xage.chat.lifecycle"]
        XCTAssertTrue(lifecycle.waitForExistence(timeout: 4), "\(context)：应暴露可审计的聊天生命周期状态")
        let expected = "phase=idle;messages=\(expectedMessageCount);latest=assistant;focused=false"
        XCTAssertTrue(
            waitUntil(timeout: 6) { (lifecycle.value as? String) == expected },
            "\(context)：聊天必须唯一收口到 \(expected)，实际为 \(String(describing: lifecycle.value))"
        )
        XCTAssertFalse(
            app.descendants(matching: .any)["xage.chat.thinking.card"].exists,
            "\(context)：助手回复完成后思考状态必须消失"
        )
    }

    private func tapAndWait(_ element: XCUIElement, for expected: XCUIElement, timeout: TimeInterval = 8) {
        XCTAssertTrue(element.waitForExistence(timeout: timeout), "待点击控件不存在：\(element)")
        element.tap()
        XCTAssertTrue(expected.waitForExistence(timeout: timeout), "点击后未出现预期控件：\(expected)")
    }

    private enum HorizontalSwipeDirection: Equatable {
        case left
        case right
    }

    private enum VerticalScrollDirection {
        case up
        case down
    }

    private func swipeHorizontally(in element: XCUIElement, direction: HorizontalSwipeDirection) {
        XCTAssertTrue(element.exists, "横滑区域应存在")
        let pageContainer = app.collectionViews["xage.section.content"]
        let target = pageContainer.exists ? pageContainer : element
        if direction == .left {
            target.swipeLeft()
        } else {
            target.swipeRight()
        }
        RunLoop.current.run(until: Date().addingTimeInterval(0.7))
    }

    private func assertMinimumTouchTarget(_ element: XCUIElement, name: String, file: StaticString = #filePath, line: UInt = #line) {
        XCTAssertTrue(element.exists, "\(name)控件应存在", file: file, line: line)
        XCTAssertGreaterThanOrEqual(element.frame.width, 43.5, "\(name)触控宽度应至少为 44pt", file: file, line: line)
        XCTAssertGreaterThanOrEqual(element.frame.height, 43.5, "\(name)触控高度应至少为 44pt", file: file, line: line)
    }

    private func scrollIntoView(_ element: XCUIElement, in scrollView: XCUIElement, maxSwipes: Int) {
        XCTAssertTrue(scrollView.waitForExistence(timeout: 6), "滚动区域应存在")
        for _ in 0..<maxSwipes where !isVisibleOnScreen(element) {
            scrollView.swipeUp()
        }
        if !isVisibleOnScreen(element) {
            for _ in 0..<maxSwipes where !isVisibleOnScreen(element) {
                scrollView.swipeDown()
            }
        }
        XCTAssertTrue(waitUntil(timeout: 4) { self.isVisibleOnScreen(element) }, "目标控件滚动后仍未进入屏幕：\(element)")
    }

    private func scrollIntoViewOnActiveScreen(_ element: XCUIElement, direction: VerticalScrollDirection, maxSwipes: Int) {
        for _ in 0..<maxSwipes where !isVisibleOnScreen(element) {
            if direction == .up {
                app.swipeUp()
            } else {
                app.swipeDown()
            }
        }
        XCTAssertTrue(waitUntil(timeout: 4) { self.isVisibleOnScreen(element) }, "活动页面滚动后目标仍不可见：\(element)")
    }

    private func tapKeyboardDone(message: String, file: StaticString = #filePath, line: UInt = #line) {
        XCTAssertTrue(app.keyboards.firstMatch.exists, "点击键盘完成前输入法应存在", file: file, line: line)
        let candidates = [
            app.buttons["xage.metric.manualEntry.keyboard.done"],
            app.toolbars.buttons["完成"],
            app.keyboards.buttons["完成"],
            app.buttons["完成"]
        ]
        guard let done = candidates.first(where: { $0.exists && $0.isHittable }) else {
            XCTFail(message, file: file, line: line)
            return
        }
        done.tap()
        XCTAssertTrue(app.keyboards.firstMatch.waitForNonExistence(timeout: 4), "点击完成后应关闭输入法", file: file, line: line)
    }

    private func passwordSecureField() -> XCUIElement {
        let identified = app.secureTextFields["login.password"]
        return identified.exists ? identified : app.secureTextFields["至少 8 位"]
    }

    private func passwordVisibleField() -> XCUIElement {
        let identified = app.textFields["login.password"]
        return identified.exists ? identified : app.textFields["至少 8 位"]
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
        let managerEntry = dataCardManagerEntry()
        XCTAssertTrue(scroll.waitForExistence(timeout: 6), "数据页滚动区域应存在")
        for _ in 0..<8 where !isVisibleOnScreen(managerEntry) {
            scroll.swipeDown()
        }
        if !isVisibleOnScreen(managerEntry) {
            swipeUp(until: managerEntry, in: scroll, maxSwipes: 8)
        }
        XCTAssertTrue(isVisibleOnScreen(managerEntry), "数据卡片管理入口应能滚动到可见位置")
        tapAndWait(managerEntry, for: app.navigationBars["数据卡片管理"])
        XCTAssertTrue(app.textFields["xage.metric.manager.search"].waitForExistence(timeout: 4), "管理页搜索框应存在")
        XCTAssertTrue(app.navigationBars["数据卡片管理"].waitForExistence(timeout: 3), "应打开数据卡片管理页面")
    }

    private func dataCardManagerEntry() -> XCUIElement {
        app.buttons.matching(
            NSPredicate(
                format: "identifier == %@ OR identifier == %@ OR label BEGINSWITH %@",
                "xage.metric.library.manage",
                "xage.data.metric.library",
                "数据卡片管理"
            )
        ).firstMatch
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

    private func closePresentedPanel() {
        if app.buttons["返回"].waitForExistence(timeout: 4) {
            app.buttons["返回"].tap()
        } else if app.buttons["关闭"].waitForExistence(timeout: 2) {
            app.buttons["关闭"].tap()
        }
        _ = app.buttons["xage.segment.数据"].waitForExistence(timeout: 8)
    }

    private func closeSettingsMenu() {
        let close = app.buttons["关闭"]
        scrollIntoViewOnActiveScreen(close, direction: .down, maxSwipes: 10)
        close.tap()
        XCTAssertTrue(app.buttons["xage.segment.数据"].waitForExistence(timeout: 8), "关闭设置后应回到数据页")
    }

    private func attachScreenshot(named name: String) {
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
