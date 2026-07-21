import Foundation
import SwiftUI

/// XAGE 本地评分算法模块。
///
/// 将 Apple 健康样本、服务端趋势和画像基础信息归一化为压力、恢复、炎症及研究态 X 年龄结果。
/// `XAgeAlgorithmContext` 是唯一输入快照；算法不发起网络请求，也不负责决定结果能否作为可信生产评分展示。
/// 评分算法可消费的一条标准化服务端趋势证据。
struct XAgeAlgorithmTrend: Equatable {
    let name: String
    let value: Double
    let unit: String?
    let refLow: Double?
    let refHigh: Double?
    let abnormal: Bool
    let measuredAt: String?
    let source: String
    let confidence: Double

    var displayValue: String {
        if value.rounded() == value {
            return "\(Int(value))\(unitLabel)"
        }
        return "\(String(format: "%.2f", value).replacingOccurrences(of: #"\.?0+$"#, with: "", options: .regularExpression))\(unitLabel)"
    }

    private var unitLabel: String {
        guard let unit, !unit.isEmpty else { return "" }
        return " \(unit)"
    }

    static func normalizedKey(_ raw: String) -> String {
        raw.lowercased()
            .replacingOccurrences(of: " ", with: "")
            .replacingOccurrences(of: "-", with: "")
            .replacingOccurrences(of: "_", with: "")
            .replacingOccurrences(of: "/", with: "")
            .replacingOccurrences(of: "（", with: "")
            .replacingOccurrences(of: "）", with: "")
            .replacingOccurrences(of: "(", with: "")
            .replacingOccurrences(of: ")", with: "")
    }
}

/// 一次评分计算的不可变输入上下文。
struct XAgeAlgorithmContext: Equatable {
    var userAge: Int?
    var profileHeightCm: Double?
    var profileWeightKg: Double?
    var dashboardScore: Int?
    var trendPointCount: Int
    var documentCount: Int
    var watchedIndicatorCount: Int
    var samples: [AppleHealthSyncSample]
    var serverTrends: [XAgeAlgorithmTrend]

    /// 创建算法输入上下文。
    /// - Parameters:
    ///   - userAge: 用户当前周岁；缺失时算法使用保守回退值。
    ///   - profileHeightCm: 画像中的身高，单位厘米。
    ///   - profileWeightKg: 画像中的体重，单位千克。
    ///   - dashboardScore: 服务端已有的综合评分参考值。
    ///   - trendPointCount: 服务端趋势点总数，用于估算数据覆盖度。
    ///   - documentCount: 已入库且可用于评分的可信文档数。
    ///   - watchedIndicatorCount: 用户关注指标数。
    ///   - samples: 当前账号的 Apple 健康样本。
    ///   - serverTrends: 已标准化的服务端指标证据。
    init(
        userAge: Int? = nil,
        profileHeightCm: Double? = nil,
        profileWeightKg: Double? = nil,
        dashboardScore: Int? = nil,
        trendPointCount: Int = 0,
        documentCount: Int = 0,
        watchedIndicatorCount: Int = 0,
        samples: [AppleHealthSyncSample] = [],
        serverTrends: [XAgeAlgorithmTrend] = []
    ) {
        self.userAge = userAge
        self.profileHeightCm = profileHeightCm
        self.profileWeightKg = profileWeightKg
        self.dashboardScore = dashboardScore
        self.trendPointCount = trendPointCount
        self.documentCount = documentCount
        self.watchedIndicatorCount = watchedIndicatorCount
        self.samples = samples
        self.serverTrends = serverTrends
    }
}

extension XAgeAlgorithmContext {
    /// 从首页服务端快照与设备样本生成算法上下文。
    /// - Parameters:
    ///   - snapshot: 当前账号的服务端聚合快照。
    ///   - samples: 当前账号已同步的 Apple 健康样本。
    init(snapshot: XAgeServerSyncSnapshot, samples: [AppleHealthSyncSample]) {
        self.init(
            userAge: snapshot.userAge,
            profileHeightCm: snapshot.profileHeightCm,
            profileWeightKg: snapshot.profileWeightKg,
            dashboardScore: snapshot.dashboardScore,
            trendPointCount: snapshot.trendPointCount,
            documentCount: snapshot.trustedDocumentCount,
            watchedIndicatorCount: snapshot.watchedIndicatorCount,
            samples: samples,
            serverTrends: snapshot.algorithmTrends
        )
    }
}

extension XAgeCompositeScores {
    /// 计算研究态本地评分。
    /// - Parameter context: 已完成账号隔离和数据标准化的输入上下文。
    /// - Returns: 压力、恢复、炎症与 X 年龄四项结果；生产展示仍受可信策略控制。
    static func compute(context: XAgeAlgorithmContext) -> XAgeCompositeScores {
        let pressure = makePressure(context)
        let recovery = makeRecovery(context)
        let inflammation = makeInflammation(context)
        let xAge = makeXAge(context, pressure: pressure, recovery: recovery, inflammation: inflammation)
        return XAgeCompositeScores(
            pressure: pressure,
            recovery: recovery,
            inflammation: inflammation,
            xAge: xAge
        )
    }
}

private extension XAgeCompositeScores {
    struct Evidence {
        let title: String
        let value: Double
        let displayValue: String
        let confidence: Double
        let abnormal: Bool
        let rawName: String?
        let unit: String?
        let source: String?
    }

    struct WeightedFeature {
        let title: String
        let score: Double
        let confidence: Double
        let weight: Double
        let displayValue: String
        let note: String

        var field: XAgeScoreField {
            XAgeScoreField(title: title, value: displayValue)
        }

        var driver: XAgeScoreDriver {
            XAgeScoreDriver(title: title, value: displayValue, note: note)
        }

        var driverStrength: Double {
            abs(score - 50) * confidence * weight
        }
    }

    struct WeightedResult {
        let score: Double
        let confidence: Int
        let drivers: [XAgeScoreDriver]
        let fields: [XAgeScoreField]
    }

    static func makePressure(_ context: XAgeAlgorithmContext) -> XAgeMetricScore {
        var features: [WeightedFeature] = []

        if let hrv = evidence(context, metricID: "hrv", aliases: ["心率变异性", "hrv", "sdnn", "rmssd"], title: "HRV/PRV") {
            features.append(WeightedFeature(
                title: "HRV/PRV",
                score: hrvSuppressionBad(hrv.value),
                confidence: hrv.confidence,
                weight: 18,
                displayValue: hrv.displayValue,
                note: "HRV/PRV 越低，算法把交感负荷子分打得越高。"
            ))
        }

        if let rhr = evidence(context, metricID: "restingHeartRate", aliases: ["静息心率", "rhr", "restingheartrate"], title: "静息心率") {
            features.append(WeightedFeature(
                title: "静息心率",
                score: rhrBad(rhr.value),
                confidence: rhr.confidence,
                weight: 18,
                displayValue: rhr.displayValue,
                note: "静息心率高于基线时，压力子分上调。"
            ))
        }

        if let respiration = evidence(context, metricID: "respiratoryRate", aliases: ["呼吸频率", "呼吸率", "respiratory", "respiration"], title: "呼吸") {
            features.append(WeightedFeature(
                title: "呼吸",
                score: respirationBad(respiration.value),
                confidence: respiration.confidence,
                weight: 10,
                displayValue: respiration.displayValue,
                note: "呼吸频率偏离个人常态时，压力子分按偏离幅度上调。"
            ))
        }

        if let temperature = evidence(context, metricID: nil, aliases: ["体温", "temperature", "temp"], title: "体温") {
            features.append(WeightedFeature(
                title: "体温",
                score: temperatureBad(temperature.value),
                confidence: temperature.confidence * 0.86,
                weight: 6,
                displayValue: temperature.displayValue,
                note: "体温偏离按低权重进入压力分。"
            ))
        }

        if let load = activityLoad(context) {
            features.append(WeightedFeature(
                title: "活动负荷",
                score: load.score,
                confidence: load.confidence,
                weight: 8,
                displayValue: load.displayValue,
                note: "活动负荷越高，短期压力子分越高。"
            ))
        }

        if let sleep = evidence(context, metricID: "sleep", aliases: ["睡眠", "sleep"], title: "睡眠") {
            features.append(WeightedFeature(
                title: "睡眠债",
                score: sleepDebtBad(sleep.value),
                confidence: sleep.confidence,
                weight: 8,
                displayValue: sleep.displayValue,
                note: "睡眠低于 7 小时时，睡眠债子分上调压力分。"
            ))
        }

        let result = weightedResult(features, context: context, requiredSignals: 6, requiredDomains: 3, cap: nil, fallback: 50)
        let value = Int(result.score.rounded())
        let hasAutonomic = features.contains { $0.title == "HRV/PRV" || $0.title == "静息心率" }
        let isReady = result.confidence >= 35 && features.count >= 3 && hasAutonomic
        return XAgeMetricScore(
            value: value,
            confidence: result.confidence,
            isReady: isReady,
            badgeLabel: isReady ? pressureBadge(value) : "待评估",
            stateLabel: isReady ? pressureState(value) : "压力待评估",
            summary: isReady ? pressureSummary(value) : "压力评估需要 HRV/静息心率，再配合睡眠、活动、呼吸或体温中的至少两类近期数据。",
            simpleExplanation: "压力分看的是身体是否处在“紧绷和占用恢复资源”的状态。HRV 降低、静息心率升高、睡眠不足或负荷过高时，分数会上升；数据不足时先不显示分数。",
            explanation: "压力分先把 HRV/PRV 抑制、静息心率、呼吸频率、睡眠债、活动负荷和体温偏移换算为 0-100 子分，再按权重加权平均。HRV 低、静息心率高、睡眠不足和高负荷会推高分数，因为这些输入代表交感负荷和恢复资源占用增加。",
            nextAction: isReady
                ? (value >= 70 ? "先降低刺激并做 2 分钟延长呼气，再复测心率和 HRV；这些输入会直接改变下一次压力分。" : "保持当前睡眠、补水和短时走动节律；这些输入会把 HRV、心率和睡眠债维持在低负荷区间。")
                : "先同步 Apple 健康中的 HRV、静息心率、睡眠和活动；如果没有可穿戴数据，可以在指标详情里手动记录。",
            fields: scoreFields(result.fields, confidence: result.confidence, isReady: isReady, missing: "HRV/静息心率 + 睡眠/活动/呼吸"),
            drivers: scoreDrivers(result.drivers, isReady: isReady, title: "补齐压力输入", note: "达到 3 类近期信号后才显示压力分，避免把单次 HRV 或心率误读成长期压力。"),
            isProxy: false
        )
    }

    static func makeRecovery(_ context: XAgeAlgorithmContext) -> XAgeMetricScore {
        var features: [WeightedFeature] = []
        let hrv = evidence(context, metricID: "hrv", aliases: ["心率变异性", "hrv", "sdnn", "rmssd"], title: "HRV/PRV")
        let sleep = evidence(context, metricID: "sleep", aliases: ["睡眠", "sleep"], title: "睡眠")

        if let hrv {
            features.append(WeightedFeature(
                title: "HRV/PRV",
                score: hrvGood(hrv.value),
                confidence: hrv.confidence,
                weight: 25,
                displayValue: hrv.displayValue,
                note: "HRV/PRV 越高且越接近个人稳定区间，恢复子分越高。"
            ))
        }

        if let rhr = evidence(context, metricID: "restingHeartRate", aliases: ["静息心率", "rhr", "restingheartrate"], title: "静息心率") {
            features.append(WeightedFeature(
                title: "静息心率",
                score: rhrGood(rhr.value),
                confidence: rhr.confidence,
                weight: 15,
                displayValue: rhr.displayValue,
                note: "静息心率越接近基线，恢复子分越高。"
            ))
        }

        if let sleep {
            features.append(WeightedFeature(
                title: "睡眠",
                score: sleepGood(sleep.value),
                confidence: sleep.confidence,
                weight: 20,
                displayValue: sleep.displayValue,
                note: "睡眠时长和连续性直接决定睡眠恢复子分。"
            ))
        }

        if let stability = stabilityGood(context) {
            features.append(WeightedFeature(
                title: "生理稳定性",
                score: stability.score,
                confidence: stability.confidence,
                weight: 12,
                displayValue: stability.displayValue,
                note: "呼吸、血氧和体温越接近稳定区间，恢复分越高。"
            ))
        }

        if let load = activityLoad(context) {
            features.append(WeightedFeature(
                title: "前日/今日负荷",
                score: 100 - load.score,
                confidence: load.confidence,
                weight: 10,
                displayValue: load.displayValue,
                note: "活动负荷越高，恢复分按负荷权重下调。"
            ))
        }

        var caps: [Double] = []
        if hrv == nil { caps.append(55) }
        if sleep == nil { caps.append(70) }
        let result = weightedResult(features, context: context, requiredSignals: 6, requiredDomains: 3, cap: caps.min(), fallback: 55)
        let value = Int(result.score.rounded())
        let isReady = result.confidence > 0 && features.count >= 2
        return XAgeMetricScore(
            value: value,
            confidence: result.confidence,
            isReady: isReady,
            badgeLabel: isReady ? recoveryBadge(value) : "待评估",
            stateLabel: isReady ? recoveryState(value) : "恢复待评估",
            summary: isReady ? recoverySummary(value) : "恢复评估至少需要 HRV、睡眠、静息心率、呼吸/血氧/体温或活动负荷中的两类近期信号。",
            simpleExplanation: "恢复分看的是身体有没有回到稳定状态。HRV 越稳定、睡眠越充分、静息心率和呼吸越平稳，恢复越好；缺少 HRV 或睡眠时会降低置信度并限制分数上限。",
            explanation: "恢复分先把 HRV/PRV、静息心率、昨夜睡眠、呼吸/血氧/体温稳定性和前日/今日负荷换算为 0-100 子分，再按权重加权。HRV 高、静息心率接近基线、睡眠充足和生理稳定会提高分数，因为这些输入代表自主神经和能量系统回到稳定区间。",
            nextAction: isReady
                ? (value >= 67 ? "今天可以安排挑战任务；算法依据是 HRV、睡眠和稳定性子分都在较高区间。" : "今天把任务强度降一档，优先补水、低强度活动和提前睡眠；这些动作对应恢复分的主要输入。")
                : "先同步 Apple 健康中的 HRV、睡眠、静息心率和呼吸/血氧；至少两类信号后显示恢复分。",
            fields: scoreFields(result.fields, confidence: result.confidence, isReady: isReady, missing: "至少 2 类恢复信号"),
            drivers: scoreDrivers(result.drivers, isReady: isReady, title: "补齐恢复输入", note: "HRV 和睡眠缺失时会降低置信度并限制分数上限；至少两类有效信号后才展示。"),
            isProxy: false
        )
    }

    static func makeInflammation(_ context: XAgeAlgorithmContext) -> XAgeMetricScore {
        let hscrp = evidence(context, metricID: nil, aliases: ["hscrp", "crp", "超敏c反应蛋白", "c反应蛋白"], title: "hsCRP")
        let wbc = evidence(context, metricID: nil, aliases: ["白细胞", "wbc"], title: "WBC")
            .flatMap { credibleBloodWhiteCell($0) ? $0 : nil }
        let nlr = evidence(context, metricID: nil, aliases: ["nlr", "中性粒细胞淋巴细胞比值"], title: "NLR")
        let cytokine = evidence(context, metricID: nil, aliases: ["il6", "白介素6", "tnf", "glyca"], title: "炎症因子")
        let hasLab = hscrp != nil || wbc != nil || nlr != nil || cytokine != nil

        var features: [WeightedFeature] = []
        if let hscrp {
            features.append(WeightedFeature(
                title: "hsCRP",
                score: hscrpBad(hscrp.value),
                confidence: hscrp.confidence,
                weight: 30,
                displayValue: hscrp.displayValue,
                note: hscrp.value > 10 ? "hsCRP 超过 10 时按急性异常上限处理，并降低本次慢性评分权重。" : "hsCRP 作为实验室锚点直接进入炎症主权重。"
            ))
        }
        if let nlr {
            features.append(WeightedFeature(
                title: "CBC/NLR",
                score: nlrBad(nlr.value),
                confidence: nlr.confidence,
                weight: 16,
                displayValue: nlr.displayValue,
                note: "NLR 越高，CBC/NLR 子分越高。"
            ))
        } else if let wbc {
            features.append(WeightedFeature(
                title: "CBC/WBC",
                score: wbcBad(wbc.value),
                confidence: wbc.confidence,
                weight: 16,
                displayValue: wbc.displayValue,
                note: "白细胞超出血常规区间时，CBC/WBC 子分上调炎症分。"
            ))
        }
        if let cytokine {
            features.append(WeightedFeature(
                title: "炎症因子",
                score: cytokineBad(cytokine.value),
                confidence: cytokine.confidence,
                weight: 14,
                displayValue: cytokine.displayValue,
                note: "IL-6/TNFα/GlycA 有值时按炎症因子主权重进入模型。"
            ))
        }

        if let temperature = evidence(context, metricID: nil, aliases: ["体温", "temperature", "temp"], title: "体温") {
            features.append(WeightedFeature(
                title: "体温",
                score: temperatureBad(temperature.value),
                confidence: temperature.confidence * 0.86,
                weight: hasLab ? 8 : 20,
                displayValue: temperature.displayValue,
                note: "体温偏离按体温子分进入模型；无实验室锚点时权重提高。"
            ))
        }
        if let rhr = evidence(context, metricID: "restingHeartRate", aliases: ["静息心率", "rhr", "restingheartrate"], title: "静息心率") {
            features.append(WeightedFeature(
                title: "静息心率",
                score: rhrBad(rhr.value),
                confidence: rhr.confidence,
                weight: hasLab ? 7 : 18,
                displayValue: rhr.displayValue,
                note: "静息心率越高，身体小火苗代理子分越高。"
            ))
        }
        if let hrv = evidence(context, metricID: "hrv", aliases: ["心率变异性", "hrv", "sdnn", "rmssd"], title: "HRV/PRV") {
            features.append(WeightedFeature(
                title: "HRV/PRV",
                score: hrvSuppressionBad(hrv.value),
                confidence: hrv.confidence,
                weight: hasLab ? 6 : 16,
                displayValue: hrv.displayValue,
                note: "HRV/PRV 越低，慢性负荷代理子分越高。"
            ))
        }
        if let respiration = evidence(context, metricID: "respiratoryRate", aliases: ["呼吸频率", "呼吸率", "respiratory", "respiration"], title: "呼吸") {
            features.append(WeightedFeature(
                title: "呼吸",
                score: respirationBad(respiration.value),
                confidence: respiration.confidence,
                weight: hasLab ? 4 : 12,
                displayValue: respiration.displayValue,
                note: "呼吸偏离按偏离幅度提高代理子分。"
            ))
        }
        if let oxygen = evidence(context, metricID: "bloodOxygen", aliases: ["血氧", "spo2", "氧饱和"], title: "血氧") {
            features.append(WeightedFeature(
                title: "血氧",
                score: oxygenBad(oxygen.value),
                confidence: oxygen.confidence,
                weight: hasLab ? 2 : 6,
                displayValue: oxygen.displayValue,
                note: "血氧低于稳定区间时，提高呼吸/睡眠复核子分。"
            ))
        }
        if !hasLab, let load = sleepOrOverloadBad(context) {
            features.append(WeightedFeature(
                title: "睡眠/负荷",
                score: load.score,
                confidence: load.confidence,
                weight: 8,
                displayValue: load.displayValue,
                note: "睡眠债和过度负荷直接提高身体小火苗代理分。"
            ))
        }

        let cap: Double? = hasLab ? ((hscrp?.value ?? 0) > 10 ? 70 : nil) : 55
        let result = weightedResult(features, context: context, requiredSignals: hasLab ? 6 : 5, requiredDomains: hasLab ? 3 : 2, cap: cap, fallback: hasLab ? 42 : 35)
        let value = Int(result.score.rounded())
        let isReady = result.confidence > 0 && features.count >= 2
        return XAgeMetricScore(
            value: value,
            confidence: result.confidence,
            isReady: isReady,
            badgeLabel: isReady ? inflammationBadge(value) : "待评估",
            stateLabel: isReady ? inflammationState(value, proxy: !hasLab) : "炎症待评估",
            summary: isReady ? inflammationSummary(value, proxy: !hasLab) : "炎症评估至少需要两类近期实验室或生理信号；没有实验室锚点时只显示低置信度身体小火苗代理分。",
            simpleExplanation: hasLab
                ? "炎症分先看报告里的炎症锚点，再用体温、心率、HRV、呼吸和血氧补充判断。实验室指标直接反映炎症相关反应，所以权重最高。"
                : "当前没有报告里的炎症锚点，小捷只看到体温、心率、睡眠等辅助信号，因此首页显示低置信度的身体小火苗代理分；它只提示身体负荷，不能单独说明炎症。",
            explanation: hasLab
                ? "炎症分优先把 hsCRP、CBC/NLR、IL-6/TNFα/GlycA 换算为实验室子分，并给这些子分最高权重；再加入体温、静息心率、HRV、呼吸和血氧作为补充。实验室项权重最高，因为它们直接对应炎症相关生物标志物。"
                : "当前没有可信实验室锚点，算法启用“身体小火苗”代理信号：把体温偏移、静息心率、HRV 抑制、呼吸、血氧、睡眠债和活动负荷换算为代理子分并加权。该代理信号只表示算法风险负荷，不是炎症诊断。",
            nextAction: isReady
                ? (value >= 60 ? "先记录体温、症状、睡眠、饮酒和训练；连续偏高时上传最新报告，实验室锚点会替代代理项并重算炎症分。" : "继续同步 Apple 健康和上传报告；新增实验室锚点会替代代理项并提高置信度。")
                : "继续同步 Apple 健康；上传近期血常规、hsCRP 或体检化验报告后，实验室锚点会替代代理项并提高置信度。",
            fields: scoreFields((hasLab ? result.fields : [XAgeScoreField(title: "类型", value: "代理信号")] + result.fields), confidence: result.confidence, isReady: isReady, missing: "至少 2 类信号"),
            drivers: scoreDrivers(result.drivers, isReady: isReady, title: "补齐炎症输入", note: "至少两类有效信号后显示；没有实验室锚点时只提供低置信度代理分，不是炎症诊断。"),
            isProxy: !hasLab
        )
    }

    static func makeXAge(
        _ context: XAgeAlgorithmContext,
        pressure: XAgeMetricScore,
        recovery: XAgeMetricScore,
        inflammation: XAgeMetricScore
    ) -> XAgeAgeScore {
        var domains: [WeightedFeature] = []
        domains.append(WeightedFeature(
            title: "自主神经",
            score: recovery.valueAsDouble,
            confidence: Double(recovery.confidence) / 100,
            weight: 15,
            displayValue: "\(recovery.value)",
            note: "恢复分越高，X年龄域分越高，年龄差向年轻方向移动。"
        ))

        if let sleep = evidence(context, metricID: "sleep", aliases: ["睡眠", "sleep"], title: "睡眠") {
            domains.append(WeightedFeature(
                title: "睡眠健康",
                score: sleepGood(sleep.value),
                confidence: sleep.confidence,
                weight: 15,
                displayValue: sleep.displayValue,
                note: "睡眠处于 7-9 小时区间时，睡眠域分提高。"
            ))
        }

        if let activity = activityGood(context) {
            domains.append(WeightedFeature(
                title: "活动与心肺",
                score: activity.score,
                confidence: activity.confidence,
                weight: 25,
                displayValue: activity.displayValue,
                note: "步数和运动分钟越接近目标，活动域分越高。"
            ))
        }

        let inflammationWeight: Double = inflammation.isProxy ? 10 : 20
        domains.append(WeightedFeature(
            title: inflammation.isProxy ? "小火苗代理" : "炎症与代谢",
            score: 100 - inflammation.valueAsDouble,
            confidence: Double(inflammation.confidence) / 100,
            weight: inflammationWeight,
            displayValue: "\(inflammation.value)",
            note: inflammation.isProxy ? "无实验室数据时，小火苗代理以低权重进入 X年龄。" : "实验室炎症和代谢信号以主权重进入 X年龄。"
        ))

        if let dashboardScore = context.dashboardScore {
            domains.append(WeightedFeature(
                title: "代谢状态",
                score: clamp(Double(dashboardScore)),
                confidence: 0.72,
                weight: inflammation.isProxy ? 10 : 8,
                displayValue: "\(dashboardScore)",
                note: "服务端代谢评分直接补充代谢域。"
            ))
        }

        if let body = bodyCompositionGood(context) {
            domains.append(WeightedFeature(
                title: "身体组成",
                score: body.score,
                confidence: body.confidence,
                weight: 15,
                displayValue: body.displayValue,
                note: "体重、BMI 或体脂进入身体组成域。"
            ))
        }

        let result = weightedResult(domains, context: context, requiredSignals: 8, requiredDomains: 4, cap: nil, fallback: 50)
        let validDays = estimatedValidDays(context)
        let dataCap: Double
        if validDays < 30 {
            dataCap = 30
        } else if validDays < 90 {
            dataCap = 60
        } else if validDays < 180 {
            dataCap = 75
        } else {
            dataCap = 90
        }
        let confidence = min(result.confidence, Int(dataCap.rounded()))
        let chronAge = Double(context.userAge ?? 35)
        let readyDomains = domains.filter { $0.confidence > 0 }.count
        let isReady = validDays >= 7 && confidence >= 35 && readyDomains >= 4 && pressure.isReady && recovery.isReady
        let shrinkage = min(1, Double(validDays) / 180) * (Double(confidence) / 100)
        let domainAgeDelta = (50 - result.score) / 10 * 2.2
        let loadDelta = (Double(pressure.value) - 50) / 50 * 1.2
        let rawDelta = clamp(domainAgeDelta + loadDelta - 0.35, -6.5, 3.5)
        let ageValue = chronAge + rawDelta * max(0.18, shrinkage)
        let deltaYears = ageValue - chronAge
        let pace = clamp(1 + (Double(pressure.value) - 50) * 0.006 - (Double(recovery.value) - 50) * 0.005 + (Double(inflammation.value) - 50) * 0.004, -1, 3)
        let rangeWidth = 0.8 + 3.0 * (1 - Double(confidence) / 100)

        return XAgeAgeScore(
            chronologicalAge: chronAge,
            ageValue: ageValue,
            isReady: isReady,
            age: isReady ? String(format: "%.1f", ageValue) : "--",
            delta: isReady ? deltaLabel(deltaYears) : "待评估",
            pace: pace,
            confidence: confidence,
            status: isReady ? xAgeStatus(pace: pace, delta: deltaYears, confidence: confidence) : "待评估",
            summary: isReady
                ? xAgeSummary(result: result, pressure: pressure, recovery: recovery, inflammation: inflammation, validDays: validDays)
                : "上一个评估周期的数据还不够。先同步 HRV、睡眠、活动和报告指标，达到门槛后再显示 X年龄。",
            explanation: "X年龄先把恢复、自主神经、睡眠、活动、炎症/小火苗、代谢和身体组成归一化为 0-100 域分，再把域分折算成年龄差并加到实际年龄上。域分越低，年龄差越往上；域分越高，年龄差越往下。有效天数决定置信度和年龄区间宽度，当前结果是趋势年龄。",
            nextAction: "继续同步睡眠、HRV、活动和报告指标；新增数据会增加有效天数、收窄年龄区间并提高置信度。",
            drivers: result.drivers,
            ageRange: isReady ? "\(String(format: "%.1f", ageValue - rangeWidth)) - \(String(format: "%.1f", ageValue + rangeWidth))" : "数据不足"
        )
    }

    static func weightedResult(
        _ features: [WeightedFeature],
        context: XAgeAlgorithmContext,
        requiredSignals: Double,
        requiredDomains: Double,
        cap: Double?,
        fallback: Double
    ) -> WeightedResult {
        let usable = features.filter { $0.confidence > 0 && $0.score.isFinite && $0.weight > 0 }
        guard !usable.isEmpty else {
            let field = XAgeScoreField(title: "数据状态", value: "建立基线中")
            let driver = XAgeScoreDriver(title: "数据不足", value: "--", note: "同步 Apple 健康或上传报告后，算法用真实输入替代占位值。")
            return WeightedResult(score: fallback, confidence: 12, drivers: [driver], fields: [field])
        }

        let expectedWeight = max(features.map(\.weight).reduce(0, +), usable.map(\.weight).reduce(0, +))
        let denominator = usable.reduce(0) { $0 + $1.weight * $1.confidence }
        let numerator = usable.reduce(0) { $0 + $1.weight * $1.confidence * $1.score }
        let coverage = denominator / expectedWeight
        let signalCount = Double(max(1, context.samples.count + min(context.serverTrends.count, 8) + min(context.watchedIndicatorCount, 4)))
        let sampleFactor = min(1, sqrt(signalCount / requiredSignals))
        let domainBalance = min(1, Double(usable.count) / requiredDomains)
        var confidence = 100 * pow(coverage, 0.55) * pow(sampleFactor, 0.25) * pow(domainBalance, 0.20) * 0.94
        if let cap {
            confidence = min(confidence, cap)
        }
        let sorted = usable.sorted { $0.driverStrength > $1.driverStrength }
        return WeightedResult(
            score: clamp(numerator / denominator),
            confidence: Int(clamp(confidence, 0, 100).rounded()),
            drivers: sorted.prefix(4).map(\.driver),
            fields: Array(usable.prefix(8).map(\.field))
        )
    }

    static func evidence(
        _ context: XAgeAlgorithmContext,
        metricID: String?,
        aliases: [String],
        title: String
    ) -> Evidence? {
        if let metricID,
           let sample = context.samples
            .filter({ $0.metricID == metricID })
            .sorted(by: { $0.measuredAt > $1.measuredAt })
            .first {
            return Evidence(
                title: title,
                value: sample.value,
                displayValue: sample.displayUnit.isEmpty
                    ? "\(sample.displayValue)\(sample.unit.isEmpty ? "" : " \(sample.unit)")"
                    : "\(sample.displayValue) \(sample.displayUnit)",
                confidence: sampleConfidence(sample),
                abnormal: false,
                rawName: sample.indicatorName,
                unit: sample.displayUnit.isEmpty ? sample.unit : sample.displayUnit,
                source: "apple_health"
            )
        }

        let normalizedAliases = aliases.map(XAgeAlgorithmTrend.normalizedKey)
        guard let trend = context.serverTrends.first(where: { trend in
            let key = XAgeAlgorithmTrend.normalizedKey(trend.name)
            return normalizedAliases.contains { alias in
                key.contains(alias) || alias.contains(key)
            }
        }) else { return nil }

        return Evidence(
            title: title,
            value: normalizedPercentValue(trend.value, unit: trend.unit, title: title),
            displayValue: trend.displayValue,
            confidence: serverTrendConfidence(trend),
            abnormal: trend.abnormal,
            rawName: trend.name,
            unit: trend.unit,
            source: trend.source
        )
    }

    static func sampleConfidence(_ sample: AppleHealthSyncSample) -> Double {
        let days = max(0, Date().timeIntervalSince(sample.measuredAt) / 86_400)
        return clamp(0.9 * exp(-days / 21), 0.35, 0.9)
    }

    static func serverTrendConfidence(_ trend: XAgeAlgorithmTrend) -> Double {
        guard let measuredAt = trend.measuredAt, let date = parseDate(measuredAt) else {
            return clamp(trend.confidence, 0.35, 0.86)
        }
        let days = max(0, Date().timeIntervalSince(date) / 86_400)
        let freshness = exp(-days / 120)
        return clamp(trend.confidence * freshness, 0.25, 0.86)
    }

    static func parseDate(_ raw: String) -> Date? {
        if let date = isoFormatter.date(from: raw) { return date }
        return dateOnlyFormatter.date(from: raw)
    }

    static func activityLoad(_ context: XAgeAlgorithmContext) -> (score: Double, confidence: Double, displayValue: String)? {
        let steps = evidence(context, metricID: "steps", aliases: ["步数", "steps"], title: "步数")
        let exercise = evidence(context, metricID: "exerciseMinutes", aliases: ["运动分钟", "exercise"], title: "运动分钟")
        let energy = evidence(context, metricID: "activeEnergy", aliases: ["活动能量", "activeenergy", "kcal"], title: "活动能量")
        let values = [steps, exercise, energy].compactMap { $0 }
        guard !values.isEmpty else { return nil }
        let stepLoad = steps.map { linear($0.value, low: 9_000, high: 16_000, minScore: 18, maxScore: 86) } ?? 0
        let exerciseLoad = exercise.map { linear($0.value, low: 45, high: 120, minScore: 18, maxScore: 88) } ?? 0
        let energyLoad = energy.map { linear($0.value, low: 450, high: 900, minScore: 18, maxScore: 86) } ?? 0
        let score = max(stepLoad, exerciseLoad, energyLoad)
        return (
            score,
            values.map(\.confidence).reduce(0, +) / Double(values.count),
            values.prefix(2).map(\.displayValue).joined(separator: " · ")
        )
    }

    static func activityGood(_ context: XAgeAlgorithmContext) -> (score: Double, confidence: Double, displayValue: String)? {
        let steps = evidence(context, metricID: "steps", aliases: ["步数", "steps"], title: "步数")
        let exercise = evidence(context, metricID: "exerciseMinutes", aliases: ["运动分钟", "exercise"], title: "运动分钟")
        let values = [steps, exercise].compactMap { $0 }
        guard !values.isEmpty else { return nil }
        let stepGood = steps.map { linear($0.value, low: 2_000, high: 8_000, minScore: 35, maxScore: 95) } ?? 50
        let exerciseGood = exercise.map { linear($0.value, low: 0, high: 30, minScore: 45, maxScore: 95) } ?? 50
        let score = steps != nil && exercise != nil ? (stepGood * 0.65 + exerciseGood * 0.35) : (steps != nil ? stepGood : exerciseGood)
        return (
            score,
            values.map(\.confidence).reduce(0, +) / Double(values.count),
            values.map(\.displayValue).joined(separator: " · ")
        )
    }

    static func stabilityGood(_ context: XAgeAlgorithmContext) -> (score: Double, confidence: Double, displayValue: String)? {
        var parts: [(Double, Evidence)] = []
        if let respiration = evidence(context, metricID: "respiratoryRate", aliases: ["呼吸频率", "呼吸率", "respiratory"], title: "呼吸") {
            parts.append((100 - respirationBad(respiration.value), respiration))
        }
        if let oxygen = evidence(context, metricID: "bloodOxygen", aliases: ["血氧", "spo2", "氧饱和"], title: "血氧") {
            parts.append((100 - oxygenBad(oxygen.value), oxygen))
        }
        if let temperature = evidence(context, metricID: nil, aliases: ["体温", "temperature", "temp"], title: "体温") {
            parts.append((100 - temperatureBad(temperature.value), temperature))
        }
        guard !parts.isEmpty else { return nil }
        return (
            parts.map(\.0).reduce(0, +) / Double(parts.count),
            parts.map { $0.1.confidence }.reduce(0, +) / Double(parts.count),
            parts.prefix(2).map { $0.1.displayValue }.joined(separator: " · ")
        )
    }

    static func sleepOrOverloadBad(_ context: XAgeAlgorithmContext) -> (score: Double, confidence: Double, displayValue: String)? {
        var parts: [(Double, Evidence)] = []
        if let sleep = evidence(context, metricID: "sleep", aliases: ["睡眠", "sleep"], title: "睡眠") {
            parts.append((sleepDebtBad(sleep.value), sleep))
        }
        if let load = activityLoad(context) {
            let evidence = Evidence(
                title: "活动负荷",
                value: load.score,
                displayValue: load.displayValue,
                confidence: load.confidence,
                abnormal: false,
                rawName: nil,
                unit: nil,
                source: nil
            )
            parts.append((load.score, evidence))
        }
        guard !parts.isEmpty else { return nil }
        return (
            parts.map(\.0).max() ?? 0,
            parts.map { $0.1.confidence }.reduce(0, +) / Double(parts.count),
            parts.prefix(2).map { $0.1.displayValue }.joined(separator: " · ")
        )
    }

    static func bodyCompositionGood(_ context: XAgeAlgorithmContext) -> (score: Double, confidence: Double, displayValue: String)? {
        var scores: [(Double, String, Double)] = []
        if let weight = evidence(context, metricID: "bodyWeight", aliases: ["体重", "weight"], title: "体重"),
           let height = context.profileHeightCm, height > 0 {
            let bmi = weight.value / pow(height / 100, 2)
            scores.append((bmiGood(bmi), String(format: "BMI %.1f", bmi), min(weight.confidence, 0.78)))
        }
        if let bodyFat = evidence(context, metricID: "bodyFat", aliases: ["体脂", "bodyfat"], title: "体脂率") {
            scores.append((bodyFatGood(bodyFat.value), bodyFat.displayValue, bodyFat.confidence))
        }
        if scores.isEmpty, let weight = context.profileWeightKg, let height = context.profileHeightCm, height > 0 {
            let bmi = weight / pow(height / 100, 2)
            scores.append((bmiGood(bmi), String(format: "BMI %.1f", bmi), 0.62))
        }
        guard !scores.isEmpty else { return nil }
        return (
            scores.map(\.0).reduce(0, +) / Double(scores.count),
            scores.map(\.2).reduce(0, +) / Double(scores.count),
            scores.map(\.1).joined(separator: " · ")
        )
    }

    static func estimatedValidDays(_ context: XAgeAlgorithmContext) -> Int {
        let sampleDays = context.samples.isEmpty ? 0 : min(45, context.samples.count * 4)
        let documentDays = context.documentCount > 0 ? min(90, 25 + context.documentCount / 2) : 0
        return max(context.trendPointCount, sampleDays, documentDays)
    }

    static func addConfidenceField(_ fields: [XAgeScoreField], confidence: Int) -> [XAgeScoreField] {
        var merged = fields
        merged.append(XAgeScoreField(title: "置信度", value: "\(confidence)%"))
        return merged
    }

    static func scoreFields(_ fields: [XAgeScoreField], confidence: Int, isReady: Bool, missing: String) -> [XAgeScoreField] {
        if isReady {
            return addConfidenceField(fields, confidence: confidence)
        }
        var merged = [
            XAgeScoreField(title: "评估状态", value: "待评估"),
            XAgeScoreField(title: "还需要", value: missing),
            XAgeScoreField(title: "当前置信度", value: "\(confidence)%")
        ]
        if !fields.isEmpty {
            merged.append(contentsOf: fields.prefix(3))
        }
        return merged
    }

    static func scoreDrivers(_ drivers: [XAgeScoreDriver], isReady: Bool, title: String, note: String) -> [XAgeScoreDriver] {
        if isReady {
            return drivers
        }
        return [XAgeScoreDriver(title: title, value: "待补齐", note: note)] + drivers.prefix(2)
    }

    static func normalizedPercentValue(_ value: Double, unit: String?, title: String) -> Double {
        let lower = (unit ?? "").lowercased()
        if (title == "血氧" || title.contains("体脂")) && value <= 1.2 {
            return value * 100
        }
        if lower.contains("%"), value <= 1.2 {
            return value * 100
        }
        return value
    }

    static func credibleBloodWhiteCell(_ evidence: Evidence) -> Bool {
        let name = (evidence.rawName ?? evidence.title).lowercased()
        let normalizedName = XAgeAlgorithmTrend.normalizedKey(name)
        let unit = (evidence.unit ?? "").lowercased()
        let display = evidence.displayValue.lowercased()

        if urineSedimentLike(display) || urineSedimentLike(unit) || urineSedimentLike(name) {
            return false
        }
        if normalizedName.contains("尿")
            || normalizedName.contains("沉渣")
            || normalizedName.contains("镜检")
            || normalizedName.contains("上皮")
            || normalizedName.contains("粪") {
            return false
        }

        let compactUnit = unit
            .replacingOccurrences(of: " ", with: "")
            .replacingOccurrences(of: "×", with: "x")
            .replacingOccurrences(of: "*", with: "x")
        let hasBloodUnit = compactUnit.contains("/l")
            && (compactUnit.contains("10") || compactUnit.contains("e9") || compactUnit.contains("^9"))
        let hasBloodName = normalizedName.contains("白细胞计数")
            || normalizedName.contains("血白细胞")
            || normalizedName.contains("血常规")
            || normalizedName.contains("全血")
            || normalizedName.contains("cbc")
            || normalizedName == "wbc"

        return hasBloodUnit || hasBloodName
    }

    static func urineSedimentLike(_ text: String) -> Bool {
        let lower = text.lowercased()
        return lower.contains("/hp") || lower.contains("/lp") || lower.contains("个/hp") || lower.contains("个/lp")
    }

    static func hrvGood(_ value: Double) -> Double {
        linear(value, low: 18, high: 65, minScore: 25, maxScore: 95)
    }

    static func hrvSuppressionBad(_ value: Double) -> Double {
        100 - hrvGood(value)
    }

    static func rhrGood(_ value: Double) -> Double {
        if value <= 58 { return 92 }
        return 100 - linear(value, low: 58, high: 88, minScore: 18, maxScore: 88)
    }

    static func rhrBad(_ value: Double) -> Double {
        100 - rhrGood(value)
    }

    static func respirationBad(_ value: Double) -> Double {
        let deviation = abs(value - 16)
        return linear(deviation, low: 2, high: 8, minScore: 12, maxScore: 88)
    }

    static func temperatureBad(_ value: Double) -> Double {
        let deviation: Double
        if value > 30 {
            deviation = abs(value - 36.7)
        } else {
            deviation = abs(value)
        }
        return linear(deviation, low: 0.2, high: 1.1, minScore: 12, maxScore: 86)
    }

    static func oxygenBad(_ value: Double) -> Double {
        if value >= 97 { return 10 }
        if value >= 95 { return linear(97 - value, low: 0, high: 2, minScore: 16, maxScore: 38) }
        return linear(95 - value, low: 0, high: 6, minScore: 48, maxScore: 90)
    }

    static func sleepGood(_ hours: Double) -> Double {
        if (7...9).contains(hours) { return 92 }
        if hours < 7 { return linear(hours, low: 4, high: 7, minScore: 28, maxScore: 88) }
        return clamp(92 - (hours - 9) * 16, 55, 92)
    }

    static func sleepDebtBad(_ hours: Double) -> Double {
        if hours >= 7 { return 14 }
        return linear(7 - hours, low: 0, high: 3, minScore: 18, maxScore: 88)
    }

    static func hscrpBad(_ value: Double) -> Double {
        if value < 1 { return 18 }
        if value < 3 { return linear(value, low: 1, high: 3, minScore: 35, maxScore: 58) }
        if value <= 10 { return linear(value, low: 3, high: 10, minScore: 62, maxScore: 92) }
        return 95
    }

    static func wbcBad(_ value: Double) -> Double {
        if (4...10).contains(value) { return 20 }
        if value < 4 { return linear(4 - value, low: 0, high: 2, minScore: 32, maxScore: 72) }
        return linear(value, low: 10, high: 16, minScore: 42, maxScore: 88)
    }

    static func nlrBad(_ value: Double) -> Double {
        if value < 2.5 { return 22 }
        return linear(value, low: 2.5, high: 5.5, minScore: 38, maxScore: 86)
    }

    static func cytokineBad(_ value: Double) -> Double {
        linear(value, low: 2, high: 10, minScore: 28, maxScore: 88)
    }

    static func bmiGood(_ value: Double) -> Double {
        if (18.5...24.9).contains(value) { return 88 }
        if value < 18.5 { return linear(value, low: 16, high: 18.5, minScore: 52, maxScore: 82) }
        return 100 - linear(value, low: 25, high: 33, minScore: 18, maxScore: 72)
    }

    static func bodyFatGood(_ value: Double) -> Double {
        if (16...28).contains(value) { return 84 }
        if value < 16 { return linear(value, low: 8, high: 16, minScore: 54, maxScore: 80) }
        return 100 - linear(value, low: 28, high: 42, minScore: 24, maxScore: 74)
    }

    static func pressureBadge(_ value: Int) -> String {
        if value >= 70 { return "压力偏高" }
        if value >= 40 { return "压力中等" }
        return "压力偏低"
    }

    static func pressureState(_ value: Int) -> String {
        value >= 70 ? "压力偏高" : (value >= 40 ? "压力中等" : "压力较低")
    }

    static func pressureSummary(_ value: Int) -> String {
        value >= 70 ? "压力输入处在高负荷区间；先降低刺激并复测。" : "压力负荷处在可管理区间。"
    }

    static func recoveryBadge(_ value: Int) -> String {
        if value >= 67 { return "恢复良好" }
        if value >= 34 { return "恢复一般" }
        return "恢复偏低"
    }

    static func recoveryState(_ value: Int) -> String {
        value >= 67 ? "恢复较好" : (value >= 34 ? "恢复一般" : "恢复偏低")
    }

    static func recoverySummary(_ value: Int) -> String {
        value >= 67 ? "恢复输入处在高分区间，可以承接适度挑战。" : "恢复输入处在保守区间，今天降低强度并补齐睡眠。"
    }

    static func inflammationBadge(_ value: Int) -> String {
        if value >= 70 { return "小火苗高" }
        if value >= 40 { return "炎症关注" }
        return "小火苗低"
    }

    static func inflammationState(_ value: Int, proxy: Bool) -> String {
        if value >= 70 { return proxy ? "小火苗偏高" : "炎症负荷偏高" }
        if value >= 40 { return proxy ? "小火苗中等" : "炎症负荷中等" }
        return proxy ? "小火苗较低" : "炎症负荷较低"
    }

    static func inflammationSummary(_ value: Int, proxy: Bool) -> String {
        if proxy {
            return value >= 60 ? "代理信号处在高位，体温和症状记录会参与下一次重算。" : "代理信号处在低位，实验室数据会替代当前代理项。"
        }
        return value >= 60 ? "实验室和生理信号处在复核区间。" : "炎症负荷处于较低区间。"
    }

    static func deltaLabel(_ value: Double) -> String {
        if value <= -0.15 { return "年轻 \(String(format: "%.1f", abs(value))) 岁" }
        if value >= 0.15 { return "偏大 \(String(format: "%.1f", value)) 岁" }
        return "接近实际年龄"
    }

    static func xAgeStatus(pace: Double, delta: Double, confidence: Int) -> String {
        if confidence < 35 { return "建立基线中" }
        if pace < 0.85 || delta < -0.5 { return "趋势变年轻" }
        if pace > 1.15 || delta > 0.5 { return "负荷略高" }
        return "稳定且健康"
    }

    static func xAgeSummary(result: WeightedResult, pressure: XAgeMetricScore, recovery: XAgeMetricScore, inflammation: XAgeMetricScore, validDays: Int) -> String {
        if validDays < 30 {
            return "有效天数不足 30 天，算法启用低影响系数和低置信度区间。"
        }
        if let driver = result.drivers.first {
            return "\(driver.title) 是本周年龄差的最大贡献项；算法每周用压力、恢复、炎症和日常节律重算 X年龄。"
        }
        return "当前 X年龄由压力、恢复、炎症和日常节律共同决定。"
    }

    static func linear(_ value: Double, low: Double, high: Double, minScore: Double, maxScore: Double) -> Double {
        guard high > low else { return minScore }
        let ratio = (value - low) / (high - low)
        return clamp(minScore + ratio * (maxScore - minScore))
    }

    static func clamp(_ value: Double, _ lower: Double = 0, _ upper: Double = 100) -> Double {
        min(max(value, lower), upper)
    }

    static let isoFormatter = ISO8601DateFormatter()

    static let dateOnlyFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "zh_CN")
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter
    }()
}

private extension XAgeMetricScore {
    var valueAsDouble: Double { Double(value) }
}
