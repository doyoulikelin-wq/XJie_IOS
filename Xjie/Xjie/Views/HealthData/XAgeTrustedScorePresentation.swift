import Foundation

struct XAgeScoreField: Identifiable, Equatable {
    let title, value: String

    var id: String { "\(title)-\(value)" }
}

struct XAgeScoreDriver: Identifiable, Equatable {
    let title, value, note: String

    var id: String { "\(title)-\(value)-\(note)" }
}

struct XAgeMetricScore: Equatable {
    let value, confidence: Int
    let isReady: Bool
    let badgeLabel, stateLabel, summary: String
    let simpleExplanation, explanation, nextAction: String
    let fields: [XAgeScoreField]
    let drivers: [XAgeScoreDriver]
    let isProxy: Bool
    var serverSnapshotVersion: String? = nil

    var isTrustedForDisplay: Bool { isReady && serverSnapshotVersion != nil }

    var displayValue: String {
        isReady ? "\(value)" : "--"
    }
}

struct XAgeAgeScore: Equatable {
    let chronologicalAge, ageValue: Double
    let isReady: Bool
    let age, delta: String
    let pace: Double
    let confidence: Int
    let status, summary, explanation, nextAction: String
    let drivers: [XAgeScoreDriver]
    let ageRange: String
    var serverSnapshotVersion: String? = nil

    var isTrustedForDisplay: Bool { isReady && serverSnapshotVersion != nil && XAgeTrustedScorePresentationPolicy.isXAgeConsumptionEnabled }

    var displayAge: String { isTrustedForDisplay ? age : "--" }
    var displayDelta: String { isTrustedForDisplay ? delta : "尚未启用" }
}

struct XAgeCompositeScores: Equatable {
    let pressure, recovery, inflammation: XAgeMetricScore
    let xAge: XAgeAgeScore

    var todaySummary: String {
        guard pressure.isReady, recovery.isReady, inflammation.isReady else {
            return "数据还不够，先同步 Apple 健康或上传报告；达到评估门槛后再显示压力、恢复和炎症分。"
        }
        return "\(recovery.stateLabel)，\(pressure.stateLabel)；\(inflammation.stateLabel)。"
    }

    func score(for kind: XAgeDataKind) -> XAgeMetricScore {
        switch kind {
        case .pressure: return pressure
        case .recovery: return recovery
        case .inflammation: return inflammation
        }
    }
}

struct XAgeTrustedScorePresentationPolicy {
    static let authority = "server"
    static let isXAgeConsumptionEnabled = false
    static let debugReadyLocalResearchArgument = "XJIE_UI_TEST_RICH_LOCAL_SCORE_INPUTS"

    static func currentPresentation(arguments: [String] = ProcessInfo.processInfo.arguments) -> XAgeCompositeScores {
#if DEBUG
        let localResearch = arguments.contains(debugReadyLocalResearchArgument) ? debugReadyLocalResearchScores() : nil
        return presentation(localResearch: localResearch)
#else
        return presentation()
#endif
    }

    static func presentation(localResearch: XAgeCompositeScores? = nil) -> XAgeCompositeScores {
        _ = localResearch
        return unavailable
    }

    static func debugAuditValue(arguments: [String] = ProcessInfo.processInfo.arguments) -> String {
        let input = arguments.contains(debugReadyLocalResearchArgument) ? "ready_local_research" : "none"
        return "authority=\(authority);xage_enabled=\(isXAgeConsumptionEnabled);input=\(input);display=blocked"
    }

    private static var unavailable: XAgeCompositeScores {
        XAgeCompositeScores(
            pressure: pendingMetric(name: "压力"),
            recovery: pendingMetric(name: "恢复"),
            inflammation: pendingMetric(name: "炎症"),
            xAge: XAgeAgeScore(
                chronologicalAge: 0,
                ageValue: 0,
                isReady: false,
                age: "--",
                delta: "尚未启用",
                pace: 0,
                confidence: 0,
                status: "X年龄尚未启用",
                summary: "等待版本化验证",
                explanation: "X年龄只会在服务端版本化算法及其输入、账户和复现校验通过后启用。当前不会使用本地估算。",
                nextAction: "可继续同步健康数据；这不会在本地生成或展示 X年龄。",
                drivers: [],
                ageRange: "尚未启用"
            )
        )
    }

    private static func pendingMetric(name: String) -> XAgeMetricScore {
        XAgeMetricScore(
            value: 0,
            confidence: 0,
            isReady: false,
            badgeLabel: "待更新",
            stateLabel: "\(name)评分待更新",
            summary: "当前没有可展示的服务端版本化\(name)评分。",
            simpleExplanation: "评分待更新。只有服务端版本化评分快照可以展示。",
            explanation: "本地算法结果仅用于研究，不是实际评分，也不会进入生产展示。",
            nextAction: "可继续同步健康数据或上传报告；同步完成不代表评分已生成。",
            fields: [XAgeScoreField(title: "可信评分", value: "待服务端版本化快照")],
            drivers: [XAgeScoreDriver(title: "评分来源", value: "服务端", note: "当前尚无冻结并版本化的评分接口。")],
            isProxy: false
        )
    }

#if DEBUG
    private static func debugReadyLocalResearchScores() -> XAgeCompositeScores {
        func metric(_ name: String, value: Int) -> XAgeMetricScore {
            XAgeMetricScore(
                value: value,
                confidence: 99,
                isReady: true,
                badgeLabel: "本地 ready",
                stateLabel: "本地 \(name)",
                summary: "仅用于验证生产展示策略会拒绝本地分数。",
                simpleExplanation: "本地研究结果",
                explanation: "Debug 确定性输入",
                nextAction: "不得展示",
                fields: [],
                drivers: [],
                isProxy: false
            )
        }
        return XAgeCompositeScores(
            pressure: metric("压力", value: 91),
            recovery: metric("恢复", value: 89),
            inflammation: metric("炎症", value: 87),
            xAge: XAgeAgeScore(
                chronologicalAge: 35,
                ageValue: 29.4,
                isReady: true,
                age: "29.4",
                delta: "年轻 5.6 岁",
                pace: 0.7,
                confidence: 99,
                status: "本地 ready",
                summary: "仅用于门禁验证",
                explanation: "不得展示",
                nextAction: "不得展示",
                drivers: [],
                ageRange: "28.9 - 29.9"
            )
        )
    }
#endif
}
