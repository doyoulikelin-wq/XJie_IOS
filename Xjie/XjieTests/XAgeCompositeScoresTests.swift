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
