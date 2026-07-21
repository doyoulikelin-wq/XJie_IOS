import XCTest

final class XAgeHighIntensityContextUITests: XAgeUITestCase {
    func testReportReviewRequiresFieldAndReportConfirmationThenShowsScorePending() throws {
        launchApplication()
        enterDebugValidationSession()

        openQuickAction("reports", expecting: app.buttons["xage.panel.reports.primary"])
        let historyRow = app.buttons["xage.panel.reports.row.history"]
        XCTAssertTrue(historyRow.waitForExistence(timeout: 5), "报告管理页应提供历史报告入口")
        let panelScroll = app.scrollViews["xage.panel.reports.scroll"]
        scrollIntoView(historyRow, in: panelScroll, maxSwipes: 6)
        panelScroll.swipeUp()
        XCTAssertTrue(waitUntil(timeout: 4) { historyRow.isHittable }, "历史报告入口不应被底部固定按钮遮挡")
        historyRow.tap()
        XCTAssertEqual(app.buttons["xage.panel.reports.primary"].label, "查看历史报告")
        tapAndWait(
            app.buttons["xage.panel.reports.primary"],
            for: app.buttons["xage.report.history.workflow.4242"]
        )
        let reportRow = app.buttons["xage.report.history.workflow.4242"]
        XCTAssertTrue(reportRow.label.contains("2026-07-15 · 协和医院 · 体检报告"), "历史报告应按日期、医院和资料类型展示")
        XCTAssertTrue(reportRow.label.contains("待确认"), "新报告工作流应保留待确认状态")
        attachScreenshot(named: "report-history-date-hospital-type")

        tapAndWait(
            reportRow,
            for: app.descendants(matching: .any)["xage.report.trace.root"]
        )
        let traceScroll = app.scrollViews["xage.report.trace.scroll"]
        XCTAssertTrue(traceScroll.waitForExistence(timeout: 5), "历史报告应先进入服务器追踪详情")
        let traceOriginal = app.descendants(matching: .any)["xage.report.trace.original"]
        XCTAssertTrue(traceOriginal.waitForExistence(timeout: 5), "追踪详情应展示原件与页码")
        XCTAssertTrue(app.staticTexts["2026年体检报告.pdf"].waitForExistence(timeout: 5))
        let traceCandidates = app.descendants(matching: .any)["xage.report.trace.candidates"]
        scrollIntoView(traceCandidates, in: traceScroll, maxSwipes: 6)
        XCTAssertTrue(app.staticTexts["空腹血糖"].waitForExistence(timeout: 5), "追踪详情应展示服务器候选与原件定位")
        let traceEvents = app.descendants(matching: .any)["xage.report.trace.events"]
        scrollIntoView(traceEvents, in: traceScroll, maxSwipes: 6)
        XCTAssertTrue(app.staticTexts["服务器尚未返回修正或确认事件。"].exists, "待确认工作流不得伪造未来事件")
        let traceScores = app.descendants(matching: .any)["xage.report.trace.scores"]
        scrollIntoView(traceScores, in: traceScroll, maxSwipes: 8)
        XCTAssertTrue(app.staticTexts["服务器未返回评分任务。"].exists, "空评分记录不得被解释为评分成功")
        attachScreenshot(named: "report-server-trace-before-confirmation")

        let openReview = app.buttons["xage.report.review.open"]
        scrollIntoView(openReview, in: traceScroll, maxSwipes: 8)
        tapAndWait(
            openReview,
            for: app.descendants(matching: .any)["xage.report.review.root"]
        )
        let reviewScroll = app.scrollViews["xage.report.review.scroll"]
        XCTAssertTrue(reviewScroll.waitForExistence(timeout: 5), "字段复核应使用可滚动独立页面")
        XCTAssertTrue(app.staticTexts["待确认"].firstMatch.waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["8.2 mmol/L"].firstMatch.waitForExistence(timeout: 5), "应同时展示原始值和候选值及单位")
        XCTAssertTrue(app.staticTexts["低置信度"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["冲突"].waitForExistence(timeout: 5))
        let conflictExplanation = app.staticTexts.matching(
            NSPredicate(format: "label CONTAINS %@", "识别单位与报告中的其他信息不一致")
        ).firstMatch
        XCTAssertTrue(conflictExplanation.waitForExistence(timeout: 5), "冲突原因应显示为用户可理解的中文")
        XCTAssertFalse(app.staticTexts["unit_conflict"].exists, "不得向用户暴露内部冲突 code")
        XCTAssertTrue(app.staticTexts["PDF 原件 · 第 2 页 · 数据区第 4 行"].waitForExistence(timeout: 5), "应展示可追溯的原件位置")

        let confirmField = app.buttons["xage.report.candidate.101.confirm"]
        scrollIntoView(confirmField, in: reviewScroll, maxSwipes: 8)
        confirmField.tap()
        let reportAcknowledgement = app.switches["xage.report.review.reportAcknowledgement"]
        scrollIntoView(reportAcknowledgement, in: reviewScroll, maxSwipes: 8)
        XCTAssertTrue(reportAcknowledgement.isEnabled, "字段决策完成后才允许报告级确认")
        reportAcknowledgement.coordinate(withNormalizedOffset: CGVector(dx: 0.9, dy: 0.5)).tap()
        XCTAssertTrue(
            waitUntil(timeout: 4) { (reportAcknowledgement.value as? String) == "1" },
            "点击系统开关的控制区域后应记录报告级确认"
        )

        let primary = app.buttons["xage.report.review.primary"]
        XCTAssertTrue(waitUntil(timeout: 4) { primary.isEnabled && primary.isHittable }, "字段确认和报告级确认完成后提交按钮才可用")
        attachScreenshot(named: "report-review-ready-to-confirm")
        primary.tap()
        XCTAssertTrue(
            app.staticTexts["已确认 · 评分待更新"].firstMatch.waitForExistence(timeout: 8),
            "确认完成必须区分评分待更新，不能伪造评分已完成"
        )
        XCTAssertTrue(waitUntil(timeout: 5) { primary.isEnabled && primary.label == "查看本次解读" }, "完成态主动作必须切换为真实可用的本次解读入口")
        attachScreenshot(named: "report-review-score-pending")
        primary.tap()

        let interpretationRoot = app.descendants(matching: .any)["xage.report.interpretation.root"]
        XCTAssertTrue(interpretationRoot.waitForExistence(timeout: 8), "最终态应进入独立报告解读页")
        XCTAssertTrue(app.staticTexts.matching(NSPredicate(format: "label CONTAINS %@", "不构成诊断")).firstMatch.waitForExistence(timeout: 5), "解读必须明确非诊断边界")
        XCTAssertTrue(app.staticTexts.matching(NSPredicate(format: "label CONTAINS %@", "评分仍待更新")).firstMatch.waitForExistence(timeout: 5), "有部分快照时仍必须以评分待更新为主文案")
        XCTAssertTrue(app.staticTexts["置信度：80% → 85%"].waitForExistence(timeout: 5), "评分快照必须展示服务端返回的前后置信度")
        XCTAssertTrue(app.staticTexts["服务端定义：数值越低越好"].waitForExistence(timeout: 5), "评分方向必须标明来自服务端定义，不能由分数变化推断")
        let interpretationScroll = app.scrollViews["xage.report.interpretation.scroll"]
        let profileSection = app.descendants(matching: .any)["xage.report.interpretation.profile"]
        scrollIntoView(profileSection, in: interpretationScroll, maxSwipes: 10)
        let profileCandidate = app.descendants(matching: .any)["xage.report.interpretation.profileCandidate.301"]
        scrollIntoView(profileCandidate, in: interpretationScroll, maxSwipes: 10)
        XCTAssertEqual(app.descendants(matching: .any).matching(identifier: "xage.report.interpretation.profileCandidate.301").count, 1, "同一画像候选的多个来源只能聚合展示为一项")
        XCTAssertTrue(app.staticTexts.matching(NSPredicate(format: "label CONTAINS %@", "候选只计为 1 项")).firstMatch.exists)
        let provenance = app.descendants(matching: .any)["xage.report.interpretation.provenance"]
        scrollIntoView(provenance, in: interpretationScroll, maxSwipes: 10)
        XCTAssertTrue(app.staticTexts.matching(NSPredicate(format: "label CONTAINS %@", "原始：8.2 mmol/L")).firstMatch.exists, "解读应保留原始识别值")
        let originalReport = app.descendants(matching: .any)["xage.report.interpretation.original"]
        scrollIntoView(originalReport, in: interpretationScroll, maxSwipes: 10)
        XCTAssertTrue(originalReport.exists, "历史解读应能追溯原始报告")
        let originalImage = app.descendants(matching: .any)["xage.report.original.image"]
        XCTAssertTrue(originalImage.waitForExistence(timeout: 8), "内容已知的有效报告原件应成功加载，不能使用空白占位图冒充证据")
        scrollIntoView(originalImage, in: interpretationScroll, maxSwipes: 4)
        XCTAssertFalse(app.alerts.firstMatch.exists, "确定性报告解读不得依赖或吞掉真实网络错误")
        attachScreenshot(named: "report-interpretation-real-original-evidence-and-score-pending")
    }

    func testHighIntensityContextFlowUsesDeterministicChatTransportAndVerifiesAllPrompts() throws {
        app.launchArguments.append("XJIE_UI_TEST_STUB_CHAT")
        app.launchArguments.append("XJIE_UI_TEST_RICH_LOCAL_SCORE_INPUTS")
        launchApplication()
        enterDebugValidationSession()
        verifyTrustedScorePolicyBlocksReadyLocalResearchScores()
        verifyDataButtonsAndPanels()
        verifyMetricManagerAndQuickActions()
        verifyChatButtonsAndContextPrompts()
        verifyXAgeInfoButton()
        attachScreenshot(named: "xage-high-intensity-final")
    }

    func testDataCardManagerPersistsSelectedCardsAcrossRelaunch() throws {
        launchApplication()
        enterDebugValidationSession()
        openDataCardManagerFromTop()

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
        app.launchArguments.append("XJIE_UI_TEST_RICH_LOCAL_SCORE_INPUTS")
        launchApplication()
        enterDebugValidationSession()
        verifyTrustedScorePolicyBlocksReadyLocalResearchScores()

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
        let assistantReply = app.staticTexts["UI 自动化回复：\(submittedPrompt)"]
        XCTAssertTrue(
            assistantReply.waitForExistence(timeout: 5),
            "小屏内容首次溢出后仍应显示确定性助手回复"
        )
        assertAssistantTextCanBeCopied(assistantReply, context: "普通助手回复")

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

        verifyHealthProfileKeyboardLifecycle()
    }

    func testNavigationTouchTargetsAndFormDismissalConventions() throws {
        launchApplication()
        enterDebugValidationSession()

        verifyHorizontalSectionNavigationAndTopInfo()
        verifyManagerSearchKeyboardDismissal()
        verifySettingsFormDismissalConventions()
        verifyManualEntryDismissal()
        verifyQuickActionTouchTargetsAndManagerRouting()
        verifyWeightQuickActionStartsAtMetricDetail()
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
        verifyHomeQuickActionIdentifiers()
        XCTAssertFalse(app.buttons["xage.data.sort"].exists, "数据页顶部不应再出现独立排序模式")
        XCTAssertTrue(app.buttons["xage.data.manage"].waitForExistence(timeout: 5), "数据页顶部主操作应统一为管理")
        XCTAssertTrue(app.staticTexts["授权后可以更好地评估当前的身体指标"].waitForExistence(timeout: 5), "首次成功同步前首页应显示精简 Apple 健康授权说明")
        XCTAssertTrue(app.buttons["xage.appleHealth.authorize.button"].waitForExistence(timeout: 4), "首次成功同步前首页应提供授权按钮")
        attachScreenshot(named: "home-quick-actions-and-apple-health-authorization")

        openQuickAction("reports", expecting: app.buttons["xage.panel.reports.primary"])
        attachScreenshot(named: "panel-报告")
        closePresentedPanel()
        XCTAssertTrue(app.scrollViews["xage.data.scroll"].waitForExistence(timeout: 6), "关闭报告页后应返回数据页")

        tapAndWait(app.buttons["xage.more"], for: app.buttons["xage.more.category.profile"])
        XCTAssertTrue(app.staticTexts["更多"].firstMatch.waitForExistence(timeout: 5), "更多页应使用明确标题")
        XCTAssertFalse(app.buttons["xage.account.报告"].exists, "报告不得在更多页重复出现")
        XCTAssertFalse(app.buttons["xage.account.用药管理"].exists, "用药不得在更多页重复出现")
        XCTAssertFalse(app.buttons["xage.account.日常"].exists, "日常假操作不得出现在更多资料入口")
        XCTAssertFalse(app.buttons["xage.account.就医"].exists, "就医快捷功能不得在更多页重复出现")
        attachScreenshot(named: "more-profile-only")

        tapAndWait(
            app.buttons["xage.more.category.profile"],
            for: app.descendants(matching: .any)["healthProfile.overview"]
        )
        let profileScroll = app.scrollViews["healthProfile.root"]
        XCTAssertTrue(profileScroll.waitForExistence(timeout: 5), "健康画像应为可滚动的独立服务端页面")
        XCTAssertTrue(app.buttons["healthProfile.module.basic"].waitForExistence(timeout: 5), "画像首页应提供基础资料模块")
        XCTAssertTrue(app.descendants(matching: .any)["healthProfile.candidates"].waitForExistence(timeout: 5))
        let accept = app.buttons["healthProfile.candidate.301.accept"]
        scrollIntoView(accept, in: profileScroll, maxSwipes: 6)
        XCTAssertTrue(accept.exists, "候选 section 标识不得覆盖确认加入按钮的独立标识")
        XCTAssertTrue(
            app.buttons["healthProfile.candidate.301.reject"].exists,
            "候选 section 标识不得覆盖暂不加入按钮的独立标识"
        )
        accept.tap()
        let candidateConfirmation = app.sheets.firstMatch
        XCTAssertTrue(candidateConfirmation.waitForExistence(timeout: 4), "候选加入画像前必须二次确认")
        candidateConfirmation.buttons["确认加入"].tap()
        XCTAssertTrue(
            app.descendants(matching: .any)["healthProfile.candidates"].waitForNonExistence(timeout: 6),
            "确认后应使用服务端响应移除候选，而不是只改本地勾选"
        )
        XCTAssertTrue(app.buttons["healthProfile.module.longTermHealth"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["healthProfile.module.safety"].waitForExistence(timeout: 5))
        let medicationLink = app.buttons["healthProfile.medication.open"]
        scrollIntoView(medicationLink, in: profileScroll, maxSwipes: 10)
        XCTAssertTrue(medicationLink.exists, "长期用药只能显示摘要并提供真实用药管理跳转")
        attachScreenshot(named: "panel-画像-trusted-server-state")
        app.buttons["healthProfile.close"].tap()
        XCTAssertTrue(app.buttons["xage.more.category.profile"].waitForExistence(timeout: 6), "关闭画像页后应返回更多页")
        closeSettingsMenu()

        openQuickAction("medications", expecting: app.scrollViews["xage.medication.root"])
        XCTAssertTrue(app.buttons["xage.medication.add"].exists, "用药管理应进入 XAGE 液态玻璃用药页")
        attachScreenshot(named: "panel-medication-xage")

        app.buttons["xage.medication.add"].tap()
        let addSourceRoot = app.scrollViews["xage.medication.addSource.root"]
        XCTAssertTrue(addSourceRoot.waitForExistence(timeout: 5), "新增用药必须先选择真实来源")
        XCTAssertTrue(app.buttons["xage.medication.addSource.ocrText"].waitForExistence(timeout: 4))
        XCTAssertTrue(app.buttons["xage.medication.addSource.manual"].waitForExistence(timeout: 4))
        XCTAssertTrue(
            app.staticTexts["当前不可用"].firstMatch.exists,
            "服务端没有处方或历史来源时必须明确不可用，不能展示假入口"
        )
        attachScreenshot(named: "panel-medication-add-source-boundaries")
        app.buttons["xage.medication.addSource.close"].tap()
        XCTAssertTrue(addSourceRoot.waitForNonExistence(timeout: 5))

        let medicationScroll = app.scrollViews["xage.medication.root"]
        let planCard = app.buttons["xage.medication.plan.7"]
        XCTAssertTrue(planCard.waitForExistence(timeout: 6), "确定性用药夹具应返回一条已确认计划")
        scrollIntoView(planCard, in: medicationScroll, maxSwipes: 8)
        planCard.tap()
        let reminderButton = app.buttons["xage.medication.reminder.open.7"]
        XCTAssertTrue(reminderButton.waitForExistence(timeout: 4), "展开计划后应显示提醒设置入口")
        XCTAssertTrue(
            app.buttons["xage.medication.plan.edit.7"].exists,
            "展开计划后编辑入口必须保留独立可访问标识"
        )
        XCTAssertTrue(
            app.buttons["xage.medication.plan.status.7"].exists,
            "展开计划后状态入口必须保留独立可访问标识"
        )
        XCTAssertTrue(
            app.buttons["xage.medication.plan.more.7"].exists,
            "展开计划后更多入口必须保留独立可访问标识"
        )
        scrollIntoView(reminderButton, in: medicationScroll, maxSwipes: 6)
        reminderButton.tap()
        let reminderRoot = app.scrollViews["xage.medication.reminder.root"]
        XCTAssertTrue(reminderRoot.waitForExistence(timeout: 5), "已确认计划应提供本机提醒设置")
        XCTAssertTrue(
            app.staticTexts["当前环境不能使用系统通知"].waitForExistence(timeout: 4),
            "确定性 UI 测试必须禁用真实通知中心并诚实显示不可用"
        )
        XCTAssertTrue(
            app.descendants(matching: .any)["xage.medication.reminder.pullDismiss.ready"]
                .waitForExistence(timeout: 4),
            "提醒表单必须把纵向下拉退键盘 hook 安装在滚动内容中"
        )
        let reminderTimes = app.textFields["xage.medication.reminder.times"]
        XCTAssertTrue(reminderTimes.waitForExistence(timeout: 4))
        reminderTimes.tap()
        XCTAssertTrue(app.keyboards.firstMatch.waitForExistence(timeout: 4))
        reminderTimes.typeText(",23:59")
        XCTAssertTrue(
            waitUntil(timeout: 4) {
                (reminderTimes.value as? String)?.contains("23:59") == true
            },
            "提醒下拉回归必须先形成未保存修改，避免 clean sheet 合法关闭与键盘消费竞速"
        )
        let reminderDragStart = reminderRoot.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.28))
        let reminderDragEnd = reminderRoot.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.78))
        reminderDragStart.press(forDuration: 0.05, thenDragTo: reminderDragEnd)
        XCTAssertTrue(
            app.keyboards.firstMatch.waitForNonExistence(timeout: 4),
            "下拉提醒设置内容应交互式关闭输入法"
        )
        XCTAssertTrue(
            reminderRoot.waitForExistence(timeout: 4),
            "有未保存修改时，下拉只能关闭输入法，不能关闭提醒表单"
        )
        let reminderClose = app.buttons["xage.medication.reminder.close"]
        XCTAssertTrue(
            reminderClose.waitForExistence(timeout: 4),
            "下拉关闭输入法后必须保留显式关闭入口"
        )
        attachScreenshot(named: "panel-medication-reminder-permission-and-keyboard")
        reminderClose.tap()
        let discardReminderAlert = app.alerts["放弃未保存的提醒设置？"]
        XCTAssertTrue(
            discardReminderAlert.waitForExistence(timeout: 4),
            "有未保存修改时显式关闭必须二次确认"
        )
        let discardReminder = discardReminderAlert.buttons["放弃"]
        XCTAssertTrue(discardReminder.waitForExistence(timeout: 4))
        discardReminder.tap()
        XCTAssertTrue(reminderRoot.waitForNonExistence(timeout: 5))

        let medicationBack = app.buttons["返回"]
        scrollIntoView(medicationBack, in: medicationScroll, maxSwipes: 8)
        XCTAssertTrue(medicationBack.exists, "用药管理应显示返回数据页按钮")
        medicationBack.tap()
        XCTAssertTrue(app.scrollViews["xage.data.scroll"].waitForExistence(timeout: 6), "用药管理返回后应回到数据页")
    }

    private func verifyHealthProfileKeyboardLifecycle() {
        tapAndWait(app.buttons["xage.more"], for: app.buttons["xage.more.category.profile"])
        tapAndWait(
            app.buttons["xage.more.category.profile"],
            for: app.descendants(matching: .any)["healthProfile.overview"]
        )
        let profileScroll = app.scrollViews["healthProfile.root"]
        XCTAssertTrue(profileScroll.waitForExistence(timeout: 5), "小屏画像页应提供滚动容器")
        XCTAssertTrue(
            app.descendants(matching: .any)["healthProfile.pullDismiss.ready"]
                .waitForExistence(timeout: 4),
            "健康画像必须把纵向下拉退键盘 hook 安装在滚动内容中"
        )
        let safetyEditor = app.buttons["healthProfile.edit.safety.medication_allergy"]
        let safetyModule = app.buttons["healthProfile.module.safety"]
        scrollIntoView(safetyModule, in: profileScroll, maxSwipes: 10)
        safetyModule.tap()
        let formScroll = app.scrollViews["healthProfile.form.scroll"]
        XCTAssertTrue(formScroll.waitForExistence(timeout: 5), "安全信息应打开独立表单页")
        scrollIntoView(safetyEditor, in: formScroll, maxSwipes: 10)
        safetyEditor.tap()

        let valueEditor = app.textViews["healthProfile.editor.value"]
        XCTAssertTrue(valueEditor.waitForExistence(timeout: 5), "安全信息应使用可换行的多行输入框")
        valueEditor.tap()
        XCTAssertTrue(app.keyboards.firstMatch.waitForExistence(timeout: 4), "点击安全信息输入框后应显示输入法")
        valueEditor.typeText("青霉素过敏，曾出现皮疹；请保留这段较长说明用于小屏换行与编辑验证。")

        let dragStart = valueEditor.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.35))
        let dragEnd = formScroll.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.78))
        dragStart.press(forDuration: 0.05, thenDragTo: dragEnd)
        XCTAssertTrue(app.keyboards.firstMatch.waitForNonExistence(timeout: 4), "下拉画像内容应交互式收起输入法")

        let save = app.buttons["healthProfile.editor.save"]
        scrollIntoView(save, in: formScroll, maxSwipes: 6)
        XCTAssertTrue(save.isEnabled, "填写安全信息后保存按钮应可用")
        save.tap()
        let safetyConfirmation = app.sheets.firstMatch
        XCTAssertTrue(safetyConfirmation.waitForExistence(timeout: 4), "安全信息保存必须再次确认")
        safetyConfirmation.buttons["确认并保存"].tap()
        XCTAssertTrue(app.staticTexts["青霉素过敏"].waitForExistence(timeout: 6), "服务端保存响应应回显确认后的安全事实")
        attachScreenshot(named: "health-profile-small-keyboard-and-safety-confirmation")

        app.buttons["healthProfile.form.close"].tap()
        XCTAssertTrue(app.buttons["healthProfile.module.safety"].waitForExistence(timeout: 5))
        app.buttons["healthProfile.close"].tap()
        XCTAssertTrue(app.buttons["xage.more.category.profile"].waitForExistence(timeout: 6))
        closeSettingsMenu()
    }

    private func verifyMetricManagerAndQuickActions() {
        openDataCardManagerFromTop()
        XCTAssertTrue(app.descendants(matching: .any)["xage.metric.manager.appleHealth"].waitForExistence(timeout: 5), "管理页应承接完整 Apple 健康状态与手动同步")
        closeMetricManagerPage()

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
        let returnedManagerEntry = dataCardManagerEntry()
        swipeUp(
            until: returnedManagerEntry,
            in: app.scrollViews["xage.data.scroll"],
            maxSwipes: 10
        )
        XCTAssertTrue(returnedManagerEntry.isHittable, "返回后应能再次滚动到底部的数据卡片管理入口")
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

    private func verifyTrustedScorePolicyBlocksReadyLocalResearchScores() {
        let audit = app.descendants(matching: .any)["xage.score.trust.audit"]
        XCTAssertTrue(audit.waitForExistence(timeout: 5), "确定性 UI 必须暴露可信评分展示审计")
        XCTAssertEqual(
            audit.value as? String,
            "authority=server;xage_enabled=false;input=ready_local_research;display=blocked",
            "即使输入为 ready 的本地研究分数，生产展示也必须由服务端策略拦截"
        )
        let notice = app.descendants(matching: .any)["xage.score.trust.notice"]
        XCTAssertTrue(notice.waitForExistence(timeout: 5), "数据页必须说明只展示服务端版本化评分")
        XCTAssertTrue(notice.label.contains("评分待更新"))
        for kind in ["pressure", "recovery", "inflammation"] {
            let ring = app.buttons["xage.data.score.\(kind)"]
            XCTAssertTrue(ring.waitForExistence(timeout: 4), "三项可信评分卡必须存在")
            XCTAssertTrue(ring.label.contains("--"), "本地 ready 分数不得进入生产评分卡：\(ring.label)")
        }

        app.buttons["xage.segment.X年龄"].tap()
        XCTAssertTrue(app.descendants(matching: .any)["xage.xage.disabled"].waitForExistence(timeout: 5))
        XCTAssertEqual(app.staticTexts["xage.xage.age"].label, "--")
        XCTAssertTrue(app.descendants(matching: .any)["xage.xage.validation"].waitForExistence(timeout: 4))
        XCTAssertFalse(app.buttons["xage.week.previous"].exists)
        XCTAssertFalse(app.buttons["xage.week.next"].exists)
        XCTAssertFalse(app.staticTexts["29.4"].exists)
        XCTAssertFalse(app.staticTexts["年轻 5.6 岁"].exists)
        XCTAssertFalse(app.staticTexts["0.7x"].exists)

        tapAndWait(app.buttons["xage.xage.info.inline"], for: app.buttons["xage.info.close"])
        XCTAssertTrue(app.staticTexts["等待版本化验证"].firstMatch.waitForExistence(timeout: 4))
        XCTAssertFalse(app.staticTexts.matching(NSPredicate(format: "label CONTAINS %@", "趋势年龄")).firstMatch.exists)
        app.buttons["xage.info.close"].tap()
        XCTAssertTrue(app.buttons["xage.segment.X年龄"].waitForExistence(timeout: 5))
        app.buttons["xage.segment.数据"].tap()
        XCTAssertTrue(app.scrollViews["xage.data.scroll"].waitForExistence(timeout: 5))
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

    private func verifyQuickActionTouchTargetsAndManagerRouting() {
        verifyHomeQuickActionIdentifiers()
        for (identifier, name) in [
            ("meals", "饮食"),
            ("mood", "感受"),
            ("weight", "体重"),
            ("reports", "报告"),
            ("medications", "用药"),
            ("health-plan", "健康计划"),
            ("medical", "就医")
        ] {
            let action = scrollQuickActionIntoView(identifier)
            assertMinimumTouchTarget(action, name: "快捷功能\(name)")
        }
        attachScreenshot(named: "ux-quick-actions-touch-targets")

        // 前四项同时处于快捷栏可视区：将第一项长按拖到第四项，验证手势触发的是重排而非点击跳转。
        let meals = scrollQuickActionIntoView("meals")
        let reports = scrollQuickActionIntoView("reports")
        XCTAssertLessThan(meals.frame.midX, reports.frame.midX, "默认顺序中饮食应位于报告之前")
        meals.press(forDuration: 0.8, thenDragTo: reports)
        XCTAssertTrue(
            waitUntil(timeout: 5) {
                self.app.buttons["xage.quickAction.meals"].frame.midX
                    > self.app.buttons["xage.quickAction.reports"].frame.midX
            },
            "长按并拖过报告后，饮食按钮应移动到报告之后"
        )
        XCTAssertFalse(app.navigationBars["饮食记录"].exists, "拖拽排序不应误触发快捷功能跳转")
        attachScreenshot(named: "ux-quick-actions-reordered")
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

    private func verifyWeightQuickActionStartsAtMetricDetail() {
        let weight = scrollQuickActionIntoView("weight")
        weight.tap()

        let manualEntry = app.buttons["xage.metric.manualEntry"]
        XCTAssertTrue(manualEntry.waitForExistence(timeout: 5), "体重快捷功能应先打开体重详情页")
        XCTAssertTrue(app.descendants(matching: .any)["xage.weight.detail"].exists, "体重详情应使用专属最新记录与趋势布局")
        XCTAssertTrue(app.descendants(matching: .any)["xage.weight.trend"].exists, "体重详情应提供近三个月趋势区域")
        XCTAssertTrue(app.buttons["xage.weight.recordHeight"].exists, "测试态无身高时应提供记录身高入口")
        XCTAssertTrue(app.staticTexts["还没有记录身高，无法计算BMI"].exists)
        XCTAssertFalse(app.textFields["xage.metric.manualEntry.value"].exists, "未点击手动记录前不应显示数值输入框")
        attachScreenshot(named: "weight-detail-latest-bmi-and-trend")

        app.buttons["xage.weight.recordHeight"].tap()
        XCTAssertTrue(app.descendants(matching: .any)["xage.height.entry"].waitForExistence(timeout: 5), "记录身高应打开专用数字键盘 sheet")
        let heightDigitButton = app.buttons["xage.height.entry.digit.1"]
        let heightSaveButton = app.buttons["xage.height.entry.save"]
        XCTAssertEqual(heightDigitButton.frame.height, heightSaveButton.frame.height, accuracy: 2, "保存按钮应与数字按钮等高")
        XCTAssertGreaterThan(heightSaveButton.frame.width, heightDigitButton.frame.width * 2.5, "保存按钮应横向填满数字键盘整体宽度")
        app.buttons["xage.height.entry.digit.4"].tap()
        app.buttons["xage.height.entry.digit.9"].tap()
        app.buttons["xage.height.entry.save"].tap()
        XCTAssertTrue(app.staticTexts["数据范围异常，请填写正确数字。"].waitForExistence(timeout: 3), "小于 50 cm 时必须阻止保存并显示范围提示")
        app.buttons["xage.height.entry.clear"].tap()
        app.buttons["xage.height.entry.digit.2"].tap()
        app.buttons["xage.height.entry.digit.1"].tap()
        app.buttons["xage.height.entry.digit.1"].tap()
        app.buttons["xage.height.entry.save"].tap()
        XCTAssertTrue(app.staticTexts["数据范围异常，请填写正确数字。"].waitForExistence(timeout: 3), "大于 210 cm 时必须阻止保存并显示范围提示")
        app.buttons["xage.height.entry.close"].tap()
        XCTAssertTrue(manualEntry.waitForExistence(timeout: 5), "关闭身高 sheet 后应回到体重详情页")

        manualEntry.tap()
        XCTAssertTrue(app.descendants(matching: .any)["xage.weight.picker"].waitForExistence(timeout: 5), "记录体重应弹出专用转轮选择器")
        XCTAssertTrue(app.descendants(matching: .any)["xage.weight.page"].exists, "记录转轮应覆盖在体重详情页面上，不能移除导航栈中的详情页")
        XCTAssertTrue(app.pickerWheels["xage.weight.picker.integer"].exists, "体重选择器应提供整数转轮")
        XCTAssertTrue(app.pickerWheels["xage.weight.picker.tenth"].exists, "体重选择器应提供一位小数转轮")
        XCTAssertTrue(app.buttons["xage.weight.picker.save"].exists)
        XCTAssertTrue(app.buttons["xage.weight.picker.cancel"].exists)
        attachScreenshot(named: "weight-picker-one-decimal-kilograms")

        app.buttons["xage.weight.picker.cancel"].tap()
        XCTAssertTrue(manualEntry.waitForExistence(timeout: 5), "取消体重转轮后应返回体重详情页")
        XCTAssertTrue(app.descendants(matching: .any)["xage.weight.page"].exists, "取消后应继续停留在同一个体重详情页面")
        XCTAssertTrue(app.descendants(matching: .any)["xage.weight.detail"].exists)
        let backFromWeightDetail = app.buttons["返回上一页"]
        XCTAssertTrue(backFromWeightDetail.waitForExistence(timeout: 4), "体重详情页应提供返回按钮")
        backFromWeightDetail.tap()
        XCTAssertTrue(waitUntil(timeout: 5) { self.app.scrollViews["xage.data.scroll"].isHittable }, "返回体重详情页的上一级后应回到数据页")
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
        tapAndWait(app.buttons["xage.more"], for: app.buttons["xage.more.category.profile"])

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

        let accountSecurity = app.buttons["xage.account.security"]
        scrollIntoViewOnActiveScreen(accountSecurity, direction: .up, maxSwipes: 6)
        XCTAssertFalse(app.buttons["xage.account.退出登录"].exists, "退出登录不应继续暴露在账号管理一级菜单")
        accountSecurity.tap()
        XCTAssertTrue(app.staticTexts["xage.account.security.phone"].waitForExistence(timeout: 6), "账号安全页应展示脱敏手机号")
        XCTAssertTrue(app.buttons["xage.account.退出登录"].waitForExistence(timeout: 4), "账号安全页应提供退出登录入口")
        let deleteAccount = app.buttons["xage.account.注销账号"]
        scrollIntoViewOnActiveScreen(deleteAccount, direction: .up, maxSwipes: 6)
        deleteAccount.tap()
        let deleteInput = app.textFields["xage.account.delete.input"]
        XCTAssertTrue(deleteInput.waitForExistence(timeout: 5), "注销确认页应显示确认文字输入框")
        deleteInput.tap()
        XCTAssertTrue(app.keyboards.firstMatch.waitForExistence(timeout: 4), "注销确认输入框应显示输入法")
        deleteInput.typeText("注销")
        let deleteKeyboardDone = app.buttons["xage.account.delete.keyboard.done"]
        XCTAssertTrue(deleteKeyboardDone.waitForExistence(timeout: 4), "注销确认输入框应提供稳定的完成按钮")
        assertMinimumTouchTarget(deleteKeyboardDone, name: "注销确认完成")
        deleteKeyboardDone.tap()
        XCTAssertTrue(app.keyboards.firstMatch.waitForNonExistence(timeout: 4), "注销确认完成按钮应关闭输入法")
        let destructiveConfirm = app.buttons["xage.account.delete.confirm"]
        XCTAssertTrue(destructiveConfirm.isEnabled, "输入注销后确认按钮应变为可用")
        XCTAssertTrue(app.buttons["取消"].waitForExistence(timeout: 4), "注销页应允许安全取消")
        attachScreenshot(named: "ux-delete-account-safe-cancel")
        app.buttons["取消"].tap()
        XCTAssertTrue(app.buttons["xage.account.注销账号"].waitForExistence(timeout: 5), "取消注销后应回到账号安全页且保持登录")

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
            assertAssistantTextCanBeCopied(
                app.staticTexts["UI 自动化回复："],
                context: "含真实链接的富文本助手回复"
            )
        } else {
            XCTAssertTrue(
                app.staticTexts["UI 自动化回复：\(text)"].waitForExistence(timeout: 5),
                "确定性 UI 传输应为每条问题返回对应回显，证明发送链路已经完成"
            )
        }
        XCTAssertFalse(app.alerts.firstMatch.exists, "确定性 UI 传输不应依赖或吞掉网络错误弹窗")
    }

    private func assertAssistantTextCanBeCopied(
        _ text: XCUIElement,
        context: String,
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        XCTAssertTrue(text.waitForExistence(timeout: 5), "\(context)：助手正文应存在", file: file, line: line)
        text.press(forDuration: 1.1)
        let copy = app.descendants(matching: .any)
            .matching(NSPredicate(format: "label IN %@", ["拷贝", "复制", "Copy"]))
            .firstMatch
        XCTAssertTrue(copy.waitForExistence(timeout: 4), "\(context)：长按助手正文应出现复制操作", file: file, line: line)
        XCTAssertTrue(copy.isHittable, "\(context)：复制操作应可点击", file: file, line: line)
        copy.tap()
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

        // XCTest's element-level swipe starts at the exact vertical centre. On the
        // data page that point belongs to the horizontally scrolling quick-action
        // strip, so the gesture correctly scrolls the child instead of paging the
        // outer TabView. Exercise the real paging gesture through a stable lane that
        // is shared by all three pages and does not overlap that nested scroller.
        let startX = direction == .left ? 0.82 : 0.18
        let endX = direction == .left ? 0.18 : 0.82
        let start = target.coordinate(withNormalizedOffset: CGVector(dx: startX, dy: 0.36))
        let end = target.coordinate(withNormalizedOffset: CGVector(dx: endX, dy: 0.36))
        start.press(forDuration: 0.05, thenDragTo: end)
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

    private func isInteractablyVisible(_ element: XCUIElement, within container: XCUIElement) -> Bool {
        guard element.exists, container.exists else { return false }
        let elementFrame = element.frame
        let containerFrame = container.frame.intersection(app.frame)
        guard !elementFrame.isEmpty, !elementFrame.isNull,
              !containerFrame.isEmpty, !containerFrame.isNull else { return false }
        let visibleFrame = elementFrame.intersection(containerFrame)
        return !visibleFrame.isNull
            && visibleFrame.width >= min(43.5, elementFrame.width)
            && visibleFrame.height >= min(43.5, elementFrame.height)
    }

    private func verifyHomeQuickActionIdentifiers() {
        let strip = app.scrollViews["xage.quickActions"]
        XCTAssertTrue(strip.waitForExistence(timeout: 6), "数据页应提供单行横向快捷功能")
        for identifier in [
            "meals", "mood", "weight", "reports", "medications", "health-plan", "medical"
        ] {
            XCTAssertTrue(
                app.buttons["xage.quickAction.\(identifier)"].waitForExistence(timeout: 4),
                "快捷功能应暴露稳定标识：\(identifier)"
            )
        }
    }

    private func scrollQuickActionIntoView(_ identifier: String) -> XCUIElement {
        let dataScroll = app.scrollViews["xage.data.scroll"]
        let strip = app.scrollViews["xage.quickActions"]
        let action = app.buttons["xage.quickAction.\(identifier)"]
        XCTAssertTrue(dataScroll.waitForExistence(timeout: 6), "数据页滚动区域应存在")
        XCTAssertTrue(strip.waitForExistence(timeout: 6), "快捷功能横向滚动区域应存在")
        // AX frames can remain inside the application bounds while being clipped by
        // an ancestor ScrollView. Judge the nested strip against its actual viewport
        // before asking XCTest to synthesize a gesture on it.
        for _ in 0..<8 where !isInteractablyVisible(strip, within: dataScroll) {
            dataScroll.swipeDown()
        }
        XCTAssertTrue(isInteractablyVisible(strip, within: dataScroll), "快捷功能应能回到屏幕可交互区域")
        for _ in 0..<8 where !isInteractablyVisible(action, within: strip) {
            strip.swipeLeft()
        }
        if !isInteractablyVisible(action, within: strip) {
            for _ in 0..<8 where !isInteractablyVisible(action, within: strip) {
                strip.swipeRight()
            }
        }
        XCTAssertTrue(
            waitUntil(timeout: 4) { self.isInteractablyVisible(action, within: strip) },
            "快捷功能滚动后仍不可交互：\(identifier)"
        )
        return action
    }

    private func openQuickAction(_ identifier: String, expecting destination: XCUIElement) {
        let action = scrollQuickActionIntoView(identifier)
        tapAndWait(action, for: destination)
    }

    private func openDataCardManagerFromTop() {
        let manager = app.buttons["xage.data.manage"]
        XCTAssertFalse(app.buttons["xage.data.sort"].exists, "顶部不得恢复独立排序入口")
        XCTAssertTrue(manager.waitForExistence(timeout: 6), "数据页顶部应显示管理")
        assertMinimumTouchTarget(manager, name: "顶部数据管理")
        tapAndWait(manager, for: app.navigationBars["数据卡片管理"])
        XCTAssertTrue(app.textFields["xage.metric.manager.search"].waitForExistence(timeout: 4), "顶部管理应进入同一数据卡片管理页")
    }

    private func openDataCardManager() {
        let scroll = app.scrollViews["xage.data.scroll"]
        let managerEntry = dataCardManagerEntry()
        XCTAssertTrue(scroll.waitForExistence(timeout: 6), "数据页滚动区域应存在")
        if !isVisibleOnScreen(managerEntry) {
            swipeUp(until: managerEntry, in: scroll, maxSwipes: 10)
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
        XCTAssertTrue(app.scrollViews["xage.data.scroll"].waitForExistence(timeout: 8), "关闭报告页后应返回父级数据页")
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
