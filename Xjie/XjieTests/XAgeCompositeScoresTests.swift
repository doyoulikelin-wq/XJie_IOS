import Foundation
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
        XCTAssertNotEqual(scores.recovery.displayValue, "--")
        XCTAssertNotEqual(scores.inflammation.displayValue, "--")
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
        XCTAssertEqual(localResearch.pressure.displayValue, "\(localResearch.pressure.value)")
        XCTAssertEqual(localResearch.recovery.displayValue, "\(localResearch.recovery.value)")
        XCTAssertEqual(localResearch.inflammation.displayValue, "\(localResearch.inflammation.value)")

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

    func testHomeInformationArchitectureUsesEightStableShortcutsAndProfileOnlyInMore() {
        let actions = XAgeDataPanelCategory.homeQuickActions

        XCTAssertEqual(
            actions.map { $0.id },
            ["meals", "mood", "weight", "reports", "medications", "health-plan", "medical"]
        )
        XCTAssertEqual(
            actions.map { $0.title },
            ["饮食", "感受", "体重", "报告", "用药", "健康计划", "就医助手"]
        )
        XCTAssertEqual(Set(actions.map { $0.id }).count, 7)
        XCTAssertEqual(Set(actions.compactMap { $0.destination }).count, 7)
        XCTAssertFalse(actions.contains(where: { $0.id == "data-manager" }))
        XCTAssertTrue(actions.allSatisfy { $0.destination == $0.id })

        let restored = XAgeQuickActionPreferences.orderedActions(
            savedIDs: ["reports", "unknown", "reports", "meals"]
        )
        XCTAssertEqual(
            restored.map(\.id),
            ["reports", "meals", "mood", "weight", "medications", "health-plan", "medical"]
        )
        let movedLater = XAgeQuickActionPreferences.reordered(
            actions,
            draggedID: "meals",
            targetID: "reports"
        )
        XCTAssertEqual(
            movedLater.map(\.id),
            ["mood", "weight", "reports", "meals", "medications", "health-plan", "medical"]
        )
        let movedEarlier = XAgeQuickActionPreferences.reordered(
            movedLater,
            draggedID: "medical",
            targetID: "mood"
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
