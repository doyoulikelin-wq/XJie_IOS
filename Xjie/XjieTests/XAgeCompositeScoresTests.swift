import Foundation
import SwiftUI
import XCTest
@testable import Xjie

final class XAgeCompositeScoresTests: XCTestCase {
    func testInflammationUsesProxyAndCapsConfidenceWithoutLabData() {
        let context = XAgeAlgorithmContext(
            userAge: 34,
            samples: [
                sample(metricID: "hrv", name: "心率变异性", value: 32, unit: "ms"),
                sample(metricID: "restingHeartRate", name: "静息心率", value: 74, unit: "bpm"),
                sample(metricID: "sleep", name: "睡眠", value: 5.8, unit: "h"),
                sample(metricID: "bloodOxygen", name: "血氧", value: 96, unit: "%")
            ]
        )

        let scores = XAgeCompositeScores.compute(context: context)

        XCTAssertTrue(scores.inflammation.isProxy)
        XCTAssertTrue(scores.recovery.isReady)
        XCTAssertTrue(scores.inflammation.isReady)
        XCTAssertNotEqual(scores.recovery.researchValueText, "--")
        XCTAssertNotEqual(scores.inflammation.researchValueText, "--")
        XCTAssertFalse(scores.recovery.isTrustedForDisplay)
        XCTAssertFalse(scores.inflammation.isTrustedForDisplay)
        XCTAssertEqual(scores.recovery.displayValue, "--")
        XCTAssertEqual(scores.inflammation.displayValue, "--")
        XCTAssertLessThanOrEqual(scores.inflammation.confidence, 55)
        XCTAssertTrue(scores.inflammation.explanation.contains("代理信号"))
        XCTAssertTrue(scores.inflammation.explanation.contains("不是炎症诊断"))
    }

    func testInflammationUsesLabAnchorWhenHsCRPExists() {
        let context = XAgeAlgorithmContext(
            userAge: 34,
            trendPointCount: 45,
            documentCount: 3,
            samples: [
                sample(metricID: "restingHeartRate", name: "静息心率", value: 68, unit: "bpm")
            ],
            serverTrends: [
                XAgeAlgorithmTrend(
                    name: "hsCRP",
                    value: 4.2,
                    unit: "mg/L",
                    refLow: nil,
                    refHigh: nil,
                    abnormal: true,
                    measuredAt: "2026-07-01",
                    source: "server_trend",
                    confidence: 0.85
                )
            ]
        )

        let scores = XAgeCompositeScores.compute(context: context)

        XCTAssertFalse(scores.inflammation.isProxy)
        XCTAssertGreaterThan(scores.inflammation.value, 55)
        XCTAssertTrue(scores.inflammation.explanation.contains("hsCRP"))
    }

    func testUrineSedimentWhiteCellsDoNotPromoteInflammationToPro() {
        let context = XAgeAlgorithmContext(
            userAge: 34,
            trendPointCount: 20,
            documentCount: 1,
            serverTrends: [
                XAgeAlgorithmTrend(
                    name: "白细胞",
                    value: 1,
                    unit: "个/HP",
                    refLow: nil,
                    refHigh: nil,
                    abnormal: true,
                    measuredAt: "2026-07-01",
                    source: "document_flag",
                    confidence: 0.70
                )
            ]
        )

        let scores = XAgeCompositeScores.compute(context: context)

        XCTAssertTrue(scores.inflammation.isProxy)
        XCTAssertLessThanOrEqual(scores.inflammation.confidence, 55)
        XCTAssertTrue(scores.inflammation.explanation.contains("代理信号"))
    }

    func testUnqualifiedWhiteCellsDoNotPromoteInflammationToPro() {
        let context = XAgeAlgorithmContext(
            userAge: 34,
            trendPointCount: 20,
            documentCount: 1,
            serverTrends: [
                XAgeAlgorithmTrend(
                    name: "白细胞",
                    value: 2,
                    unit: nil,
                    refLow: nil,
                    refHigh: nil,
                    abnormal: true,
                    measuredAt: "2026-07-01",
                    source: "document_flag",
                    confidence: 0.70
                )
            ]
        )

        let scores = XAgeCompositeScores.compute(context: context)

        XCTAssertTrue(scores.inflammation.isProxy)
        XCTAssertLessThanOrEqual(scores.inflammation.confidence, 55)
    }

    func testBloodWhiteCellWithUnitUsesLabAnchor() {
        let context = XAgeAlgorithmContext(
            userAge: 34,
            trendPointCount: 20,
            documentCount: 1,
            serverTrends: [
                XAgeAlgorithmTrend(
                    name: "白细胞计数",
                    value: 12.2,
                    unit: "10^9/L",
                    refLow: nil,
                    refHigh: nil,
                    abnormal: true,
                    measuredAt: "2026-07-01",
                    source: "document_csv",
                    confidence: 0.70
                )
            ]
        )

        let scores = XAgeCompositeScores.compute(context: context)

        XCTAssertFalse(scores.inflammation.isProxy)
        XCTAssertTrue(scores.inflammation.explanation.contains("CBC"))
    }

    func testXAgeUsesChronologicalAgeAndProducesReadableExplanation() {
        let context = XAgeAlgorithmContext(
            userAge: 42,
            profileHeightCm: 170,
            profileWeightKg: 66,
            dashboardScore: 82,
            trendPointCount: 100,
            watchedIndicatorCount: 3,
            samples: [
                sample(metricID: "hrv", name: "心率变异性", value: 58, unit: "ms"),
                sample(metricID: "sleep", name: "睡眠", value: 7.6, unit: "h"),
                sample(metricID: "steps", name: "步数", value: 8200, unit: "步"),
                sample(metricID: "exerciseMinutes", name: "运动分钟", value: 36, unit: "min")
            ]
        )

        let scores = XAgeCompositeScores.compute(context: context)

        XCTAssertEqual(scores.xAge.chronologicalAge, 42)
        XCTAssertFalse(scores.xAge.age.isEmpty)
        XCTAssertTrue(scores.xAge.explanation.contains("趋势年龄"))
        XCTAssertGreaterThan(scores.xAge.confidence, 30)
    }

    func testProductionTrustPolicyRejectsReadyLocalResearchScoresAndKeepsXAgeDisabled() {
        let context = XAgeAlgorithmContext(
            userAge: 42,
            profileHeightCm: 170,
            profileWeightKg: 66,
            dashboardScore: 82,
            trendPointCount: 100,
            documentCount: 3,
            watchedIndicatorCount: 3,
            samples: [
                sample(metricID: "hrv", name: "心率变异性", value: 58, unit: "ms"),
                sample(metricID: "restingHeartRate", name: "静息心率", value: 62, unit: "bpm"),
                sample(metricID: "sleep", name: "睡眠", value: 7.6, unit: "h"),
                sample(metricID: "steps", name: "步数", value: 8200, unit: "步"),
                sample(metricID: "exerciseMinutes", name: "运动分钟", value: 36, unit: "min"),
                sample(metricID: "respiratoryRate", name: "呼吸频率", value: 15, unit: "次/分"),
                sample(metricID: "bloodOxygen", name: "血氧", value: 98, unit: "%"),
                sample(metricID: "bodyWeight", name: "体重", value: 66, unit: "kg"),
                sample(metricID: "bodyFatPercentage", name: "体脂率", value: 20, unit: "%")
            ],
            serverTrends: [
                XAgeAlgorithmTrend(
                    name: "hsCRP",
                    value: 0.8,
                    unit: "mg/L",
                    refLow: nil,
                    refHigh: 3,
                    abnormal: false,
                    measuredAt: "2026-07-14",
                    source: "confirmed_report",
                    confidence: 0.95
                )
            ]
        )

        let localResearch = XAgeCompositeScores.compute(context: context)
        XCTAssertTrue(localResearch.pressure.isReady)
        XCTAssertTrue(localResearch.recovery.isReady)
        XCTAssertTrue(localResearch.inflammation.isReady)
        XCTAssertTrue(localResearch.xAge.isReady)
        XCTAssertEqual(localResearch.xAge.chronologicalAge, 42)
        XCTAssertTrue(localResearch.xAge.explanation.contains("趋势年龄"))
        XCTAssertEqual(localResearch.pressure.researchValueText, "\(localResearch.pressure.value)")
        XCTAssertEqual(localResearch.recovery.researchValueText, "\(localResearch.recovery.value)")
        XCTAssertEqual(localResearch.inflammation.researchValueText, "\(localResearch.inflammation.value)")
        XCTAssertFalse(localResearch.pressure.isTrustedForDisplay)
        XCTAssertFalse(localResearch.recovery.isTrustedForDisplay)
        XCTAssertFalse(localResearch.inflammation.isTrustedForDisplay)
        XCTAssertEqual(localResearch.pressure.displayValue, "--")
        XCTAssertEqual(localResearch.recovery.displayValue, "--")
        XCTAssertEqual(localResearch.inflammation.displayValue, "--")

        var versionedPressure = localResearch.pressure
        versionedPressure.serverSnapshotVersion = "score.v1"
        XCTAssertTrue(versionedPressure.isTrustedForDisplay)
        XCTAssertEqual(versionedPressure.displayValue, versionedPressure.researchValueText)

        let production = XAgeTrustedScorePresentationPolicy.presentation(localResearch: localResearch)

        XCTAssertEqual(XAgeTrustedScorePresentationPolicy.authority, "server")
        XCTAssertFalse(XAgeTrustedScorePresentationPolicy.isXAgeConsumptionEnabled)
        XCTAssertEqual(production.pressure.displayValue, "--")
        XCTAssertEqual(production.recovery.displayValue, "--")
        XCTAssertEqual(production.inflammation.displayValue, "--")
        XCTAssertFalse(production.pressure.isTrustedForDisplay)
        XCTAssertFalse(production.recovery.isTrustedForDisplay)
        XCTAssertFalse(production.inflammation.isTrustedForDisplay)
        XCTAssertEqual(production.xAge.displayAge, "--")
        XCTAssertEqual(production.xAge.displayDelta, "尚未启用")
        XCTAssertEqual(production.xAge.status, "X年龄尚未启用")
        XCTAssertEqual(production.xAge.summary, "等待版本化验证")
    }

    func testHomeInformationArchitectureUsesFiveActiveShortcutsAndProfileOnlyInMore() {
        let actions = XAgeDataPanelCategory.homeQuickActions

        XCTAssertEqual(
            actions.map { $0.id },
            ["meals", "weight", "reports", "medications", "medical"]
        )
        XCTAssertEqual(
            actions.map { $0.title },
            ["饮食", "体重", "报告", "用药", "就医助手"]
        )
        XCTAssertEqual(Set(actions.map { $0.id }).count, 5)
        XCTAssertEqual(Set(actions.compactMap { $0.destination }).count, 5)
        XCTAssertFalse(actions.contains(where: { $0.id == "data-manager" }))
        XCTAssertTrue(actions.allSatisfy { $0.destination == $0.id })

        let restored = XAgeQuickActionPreferences.orderedActions(
            savedIDs: ["reports", "unknown", "reports", "meals"]
        )
        XCTAssertEqual(
            restored.map(\.id),
            ["reports", "meals", "weight", "medications", "medical"]
        )
        let movedLater = XAgeQuickActionPreferences.reordered(
            actions,
            draggedID: "meals",
            targetID: "reports"
        )
        XCTAssertEqual(
            movedLater.map(\.id),
            ["weight", "reports", "meals", "medications", "medical"]
        )
        let movedEarlier = XAgeQuickActionPreferences.reordered(
            movedLater,
            draggedID: "medical",
            targetID: "weight"
        )
        XCTAssertEqual(movedEarlier.first?.id, "medical")

        let suiteName = "XAgeQuickActionPreferencesTests.\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suiteName)!
        defer { defaults.removePersistentDomain(forName: suiteName) }
        XAgeQuickActionPreferences.save(movedEarlier, userDefaults: defaults)
        XCTAssertEqual(
            XAgeQuickActionPreferences.load(userDefaults: defaults).map(\.id),
            movedEarlier.map(\.id)
        )
        XCTAssertEqual(XAgeDataPanelCategory.moreProfileCategories, [.profile])
        XCTAssertFalse(XAgeDataPanelCategory.moreProfileCategories.contains(.reports))
        XCTAssertEqual(XAgeDeviceManagementContract.destinationID, "device-management")
        XCTAssertFalse(XAgeDeviceManagementContract.currentProtocolAvailable)
        XCTAssertEqual(XAgeDeviceManagementContract.unsupportedTitle, "首批设备协议尚未开放")
        XCTAssertTrue(XAgeDeviceManagementContract.availableMutationIDs.isEmpty)
        XCTAssertEqual(XAgeDeviceManagementContract.state(isLoading: true), .loading)
        XCTAssertEqual(XAgeDeviceManagementContract.state(isLoading: false), .unsupported)
        XCTAssertEqual(
            XAgeDeviceManagementContract.state(isLoading: false, protocolAvailable: true),
            .empty
        )

        let conversationActions = XAgeConversationNavigationAction.available
        XCTAssertEqual(conversationActions.map(\.id), ["meals", "reports", "medications", "profile"])
        XCTAssertEqual(conversationActions.map(\.title), ["膳食", "报告", "用药", "画像"])
        XCTAssertEqual(Set(conversationActions.map(\.id)).count, conversationActions.count)
        var openedAction: XAgeConversationNavigationAction?
        let draft = "请先不要发送\n我还在补充"
        let preservedDraft = conversationActions[0].open(preserving: draft) { openedAction = $0 }
        XCTAssertEqual(openedAction, conversationActions[0])
        XCTAssertEqual(preservedDraft, draft)
        XCTAssertEqual(
            XAgeSupportComplianceContract.destinationIDs,
            ["help", "version", "privacy", "permissions", "feedback"]
        )
        XCTAssertEqual(Utils.maskedPhone("13800138000"), "138****8000")
        XCTAssertEqual(Utils.maskedPhone(nil), "暂未获取")
        XCTAssertEqual(Utils.maskedPhone("1380013"), "暂未获取")
        XCTAssertFalse(XAgeSupportComplianceContract.isFeedbackValid(" "))
        XCTAssertTrue(XAgeSupportComplianceContract.isFeedbackValid("可以提交"))
        XCTAssertTrue(XAgeSupportComplianceContract.isFeedbackValid(String(repeating: "问", count: 2_000)))
        XCTAssertFalse(XAgeSupportComplianceContract.isFeedbackValid(String(repeating: "问", count: 2_001)))
        XCTAssertFalse(XAgeSupportComplianceContract.hasFeedbackDraft(content: " \n", contact: ""))
        XCTAssertTrue(XAgeSupportComplianceContract.hasFeedbackDraft(content: "草稿", contact: ""))
        XCTAssertTrue(XAgeSupportComplianceContract.hasFeedbackDraft(content: "", contact: "13800000000"))
        XCTAssertTrue(XAgeAppleHealthSyncFlow.shouldShowHomeAuthorization(hasSuccessfulSync: false))
        XCTAssertFalse(XAgeAppleHealthSyncFlow.shouldShowHomeAuthorization(hasSuccessfulSync: true))
    }

    func testPrivacyAndPermissionDisclosureContractsExposeRealCapabilityBoundary() {
        XCTAssertEqual(XAgeSupportComplianceContract.privacyPolicyVersion, "2026.07")
        XCTAssertEqual(
            XAgeSupportComplianceContract.privacyPolicyRequiredTopics,
            ["适用范围与重要提示", "我们如何收集和使用信息", "敏感个人信息与单独同意", "共享、委托与公开披露", "存储与保护", "你的权利", "未成年人", "联系我们"]
        )
        XCTAssertEqual(
            XAgeSupportComplianceContract.permissionDisclosureIDs,
            ["health", "notifications", "camera", "photos", "photo-save", "microphone", "speech", "network", "not-used"]
        )
    }

    func testScoreStatusPresentationSeparatesFirstUseMissingDataAndReadyState() {
        func metric(isReady: Bool, confidence: Int) -> XAgeMetricScore {
            XAgeMetricScore(
                value: isReady ? 62 : 0,
                confidence: confidence,
                isReady: isReady,
                badgeLabel: isReady ? "稳定" : "待评估",
                stateLabel: isReady ? "状态稳定" : "待评估",
                summary: "测试摘要",
                simpleExplanation: "测试说明",
                explanation: "测试说明",
                nextAction: "测试操作",
                fields: [],
                drivers: [],
                isProxy: false
            )
        }

        // 不使用算法上下文的默认回退值，显式表达三项均没有评分支撑数据的首页状态。
        let empty = XAgeCompositeScores(
            pressure: metric(isReady: false, confidence: 0),
            recovery: metric(isReady: false, confidence: 0),
            inflammation: metric(isReady: false, confidence: 0),
            xAge: XAgeCompositeScores.compute(context: XAgeAlgorithmContext()).xAge
        )
        XCTAssertTrue(XAgeScoreStatusPresentation.isFirstUse(scores: empty))
        XCTAssertEqual(XAgeScoreStatusPresentation.missingKinds(scores: empty), [.pressure, .recovery, .inflammation])
        XCTAssertEqual(XAgeScoreStatusPresentation.noSupportDataPromptTitle, "评分数据不足")
        XCTAssertEqual(
            XAgeScoreStatusPresentation.noSupportDataPromptMessage,
            "当前数据不足以支撑评分，请上传评分支撑数据。点击对应评分圆环，可查看所需数据。"
        )
        XCTAssertFalse(XAgeScoreStatusPresentation.noSupportDataPromptMessage.contains("HRV"))

        // 即使有零散输入，只要三项均未生成评分，也应保持首页简短说明。
        let pendingWithEvidence = XAgeCompositeScores(
            pressure: metric(isReady: false, confidence: 28),
            recovery: metric(isReady: false, confidence: 16),
            inflammation: metric(isReady: false, confidence: 22),
            xAge: empty.xAge
        )
        XCTAssertTrue(XAgeScoreStatusPresentation.isFirstUse(scores: pendingWithEvidence))
        XCTAssertFalse(XAgeScoreStatusPresentation.needsData(scores: pendingWithEvidence))

        let partial = XAgeCompositeScores(
            pressure: metric(isReady: true, confidence: 72),
            recovery: metric(isReady: false, confidence: 24),
            inflammation: metric(isReady: false, confidence: 0),
            xAge: empty.xAge
        )
        XCTAssertFalse(XAgeScoreStatusPresentation.isFirstUse(scores: partial))
        XCTAssertTrue(XAgeScoreStatusPresentation.needsData(scores: partial))
        XCTAssertEqual(XAgeScoreStatusPresentation.missingKinds(scores: partial), [.recovery, .inflammation])
        XCTAssertTrue(XAgeScoreStatusPresentation.missingDataMessage(for: .pressure).contains("HRV"))
        XCTAssertEqual(XAgeScoreStatusPresentation.confidenceProgress(for: metric(isReady: true, confidence: 140)), 1)
    }

    func testScoreRingGapIsAnchoredAtBottom() {
        XCTAssertEqual(XAgeScoreRing.gapRotationDegrees, 90)
    }

    func testScoreSummaryCardFillsProposedHeaderWidth() {
        let targetWidth: CGFloat = 280
        let host = UIHostingController(
            rootView: XAgeScoreSummaryCard(
                compactProgress: 0,
                scores: XAgeTrustedScorePresentationPolicy.currentPresentation()
            )
        )

        let size = host.sizeThatFits(
            in: CGSize(width: targetWidth, height: .greatestFiniteMagnitude)
        )

        XCTAssertEqual(size.width, targetWidth, accuracy: 0.5)
    }

    func testScoreDashboardPreviewReflectsEditedScores() {
        let scores = XAgeScoreDashboardPreview.debugScores(
            pressure: 12,
            recovery: 67,
            inflammation: 105
        )

        XCTAssertEqual(scores.pressure.value, 12)
        XCTAssertEqual(scores.recovery.value, 67)
        XCTAssertEqual(scores.inflammation.value, 100)
        XCTAssertTrue(scores.pressure.isReady)
        XCTAssertTrue(scores.recovery.isReady)
        XCTAssertTrue(scores.inflammation.isReady)
    }

    private func sample(metricID: String, name: String, value: Double, unit: String) -> AppleHealthSyncSample {
        AppleHealthSyncSample(
            id: "\(metricID)-test",
            metricID: metricID,
            indicatorName: name,
            value: value,
            unit: unit,
            measuredAt: Date(),
            displayValue: value.rounded() == value ? "\(Int(value))" : String(format: "%.1f", value),
            displayUnit: unit,
            subtitle: "测试数据"
        )
    }
}
