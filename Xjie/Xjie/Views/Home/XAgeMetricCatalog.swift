import Foundation
import SwiftUI

/// 数据指标目录与展示模型。
///
/// 统一定义首页指标、Apple 健康候选项、服务端指标目录和图标语义，供首页、指标管理与体重趋势复用。
/// 指标库中的一个稳定分类。
struct XAgeMetricCatalogSection: Identifiable {
    var id: String { title }
    let title: String
    let icon: String
    let accent: Color
    let metrics: [XAgeMetric]
}

/// 某项指标在 Apple 健康中的支持状态及用户提示。
struct XAgeAppleHealthCatalogSemantics: Equatable {
    let source: String
    let value: String
    let time: String
    let subtitle: String

    /// 根据受支持目录生成指标的来源和值状态。
    /// - Parameters:
    ///   - metricID: 客户端稳定指标 ID。
    ///   - title: 面向用户的指标名称。
    static func resolve(metricID: String, title: String) -> XAgeAppleHealthCatalogSemantics {
        if AppleHealthStore.supportedMetricIDs.contains(metricID) {
            return XAgeAppleHealthCatalogSemantics(
                source: "apple_health_catalog",
                value: "待同步",
                time: "待同步",
                subtitle: "小捷当前支持从 Apple 健康读取" + title + "；授权后可手动同步到当前账号。"
            )
        }

        let isKnownUnsupported = AppleHealthStore.unsupportedMetricIDs.contains(metricID)
        return XAgeAppleHealthCatalogSemantics(
            source: "other_source_catalog",
            value: "暂不支持",
            time: "暂不支持自动同步",
            subtitle: isKnownUnsupported
                ? "当前版本不会从 Apple 健康自动读取" + title + "；可通过手动记录、报告或其他数据来源补充。"
                : title + "尚未接入 Apple 健康自动读取；可通过手动记录、报告或其他数据来源补充。"
        )
    }
}

/// 首页和指标管理共同消费的数据卡片模型。
struct XAgeMetric: Identifiable {
    let id: String
    let title: String
    let value: String
    let unit: String
    let time: String
    let subtitle: String
    let accent: Color
    let source: String?
    let measuredAt: String?
    let isPlaceholder: Bool
    let isStale: Bool

    /// 创建指标卡片。
    /// - Parameters:
    ///   - id: 跨排序、路由和持久化使用的稳定标识。
    ///   - title: 面向用户的指标名称。
    ///   - value: 已格式化的最新值。
    ///   - unit: 值对应的展示单位。
    ///   - time: 最新数据时间或同步状态文案。
    ///   - subtitle: 数据来源、用途或缺失状态说明。
    ///   - accent: 卡片强调色。
    ///   - source: 服务端或 Apple 健康来源标识。
    ///   - measuredAt: 服务端原始测量时间。
    ///   - isPlaceholder: 是否仍为等待真实数据的目录占位项。
    ///   - isStale: 数据是否超过对应来源的新鲜度范围。
    init(
        id: String,
        title: String,
        value: String,
        unit: String,
        time: String,
        subtitle: String,
        accent: Color,
        source: String? = nil,
        measuredAt: String? = nil,
        isPlaceholder: Bool = false,
        isStale: Bool = false
    ) {
        self.id = id
        self.title = title
        self.value = value
        self.unit = unit
        self.time = time
        self.subtitle = subtitle
        self.accent = accent
        self.source = source
        self.measuredAt = measuredAt
        self.isPlaceholder = isPlaceholder
        self.isStale = isStale
    }

    static let defaultCards = [
        XAgeMetric(id: "hrv", title: "心率变异性", value: "无", unit: "", time: "待同步", subtitle: "同步 Apple 健康后显示最近一次 HRV。", accent: Color(hex: "7B4DFF"), isPlaceholder: true),
        XAgeMetric(id: "sleep", title: "睡眠", value: "无", unit: "", time: "待同步", subtitle: "同步 Apple 健康后显示最近一晚睡眠。", accent: Color(hex: "14B887"), isPlaceholder: true),
        XAgeMetric(id: "glucose", title: "血糖波动", value: "待上传", unit: "", time: "待上传", subtitle: "上传血糖、CGM 或报告后显示波动趋势。", accent: Color(hex: "11A7C8"), isPlaceholder: true),
        XAgeMetric(id: "temp", title: "体温偏移", value: "无", unit: "", time: "待上传", subtitle: "上传或记录体温后显示最近体温偏移。", accent: Color(hex: "EF9A3D"), isPlaceholder: true)
    ]

    static let appleHealthCandidates = [
        XAgeMetric(id: "steps", title: "步数", value: "待同步", unit: "", time: "待同步", subtitle: "同步后显示今日 Apple 健康步数。", accent: Color(hex: "238AD6"), isPlaceholder: true),
        XAgeMetric(id: "distance", title: "步行+跑步距离", value: "待同步", unit: "", time: "待同步", subtitle: "同步后显示今日步行和跑步距离。", accent: Color(hex: "18B7D6"), isPlaceholder: true),
        XAgeMetric(id: "activeEnergy", title: "活动能量", value: "待同步", unit: "", time: "待同步", subtitle: "同步后显示今日活动能量消耗。", accent: Color(hex: "EF9A3D"), isPlaceholder: true),
        XAgeMetric(id: "exerciseMinutes", title: "运动分钟", value: "待同步", unit: "", time: "待同步", subtitle: "同步后显示今日运动分钟。", accent: Color(hex: "14B887"), isPlaceholder: true),
        XAgeMetric(id: "flights", title: "爬楼层数", value: "待同步", unit: "", time: "待同步", subtitle: "同步后显示今日爬楼层数。", accent: Color(hex: "4E8FE9"), isPlaceholder: true),
        XAgeMetric(id: "restingHeartRate", title: "静息心率", value: "待同步", unit: "", time: "待同步", subtitle: "同步后显示最近一次静息心率。", accent: Color(hex: "F05B72"), isPlaceholder: true),
        XAgeMetric(id: "respiratoryRate", title: "呼吸频率", value: "待同步", unit: "", time: "待同步", subtitle: "同步后显示最近一次呼吸频率。", accent: Color(hex: "2A79C7"), isPlaceholder: true),
        XAgeMetric(id: "bloodOxygen", title: "血氧", value: "待同步", unit: "", time: "待同步", subtitle: "同步后显示最近一次血氧。", accent: Color(hex: "7B4DFF"), isPlaceholder: true),
        XAgeMetric(id: "systolicBloodPressure", title: "收缩压", value: "待上传", unit: "", time: "待上传", subtitle: "同步 Apple 健康或手动记录后显示收缩压。", accent: Color(hex: "DB5B9B"), isPlaceholder: true),
        XAgeMetric(id: "diastolicBloodPressure", title: "舒张压", value: "待上传", unit: "", time: "待上传", subtitle: "同步 Apple 健康或手动记录后显示舒张压。", accent: Color(hex: "A47BEF"), isPlaceholder: true),
        XAgeMetric(id: "bodyWeight", title: "体重", value: "待同步", unit: "", time: "待同步", subtitle: "同步后显示最近一次体重。", accent: Color(hex: "11A7C8"), isPlaceholder: true),
        XAgeMetric(id: "bodyFat", title: "体脂率", value: "待同步", unit: "", time: "待同步", subtitle: "同步后显示最近一次体脂率。", accent: Color(hex: "A47BEF"), isPlaceholder: true),
        XAgeMetric(id: "mindfulMinutes", title: "正念分钟", value: "待上传", unit: "", time: "待上传", subtitle: "记录正念时间后用于压力管理分析。", accent: Color(hex: "20CDB1"), isPlaceholder: true),
        XAgeMetric(id: "daylight", title: "日照时间", value: "待上传", unit: "", time: "待上传", subtitle: "记录户外日照后用于节律和睡眠分析。", accent: Color(hex: "F3B349"), isPlaceholder: true)
    ]

    static func catalogSections(serverMetrics: [XAgeMetric]) -> [XAgeMetricCatalogSection] {
        let serverDynamic = deduped(serverMetrics.map {
            XAgeMetric(
                id: $0.id,
                title: $0.title,
                value: $0.value,
                unit: $0.unit,
                time: $0.time,
                subtitle: $0.subtitle,
                accent: $0.accent,
                source: $0.source ?? "document",
                measuredAt: $0.measuredAt,
                isPlaceholder: $0.isPlaceholder,
                isStale: $0.isStale
            )
        })
        let serverStatic = deduped(serverKnowledgeCandidates.filter { candidate in
            !serverDynamic.contains { $0.title == candidate.title }
        })

        var sections: [XAgeMetricCatalogSection] = [
            XAgeMetricCatalogSection(
                title: "小捷核心指标",
                icon: "sparkles",
                accent: Color(hex: "238AD6"),
                metrics: defaultCards
            )
        ]
        sections.append(contentsOf: appleHealthCatalogSections)
        if !serverDynamic.isEmpty {
            sections.append(
                XAgeMetricCatalogSection(
                    title: "服务器已入库指标",
                    icon: "externaldrive.connected.to.line.below",
                    accent: Color(hex: "20CDB1"),
                    metrics: serverDynamic
                )
            )
        }
        sections.append(
            XAgeMetricCatalogSection(
                title: "服务器常见检验指标",
                icon: "cross.case.fill",
                accent: Color(hex: "7B4DFF"),
                metrics: serverStatic
            )
        )
        return sections
    }

    static var appleHealthCatalogCount: Int {
        rawAppleHealthCatalogSections
            .flatMap(\.metrics)
            .filter { AppleHealthStore.supportedMetricIDs.contains($0.id) }
            .count
    }

    private static var appleHealthCatalogSections: [XAgeMetricCatalogSection] {
        let supportedSections = rawAppleHealthCatalogSections.compactMap { section -> XAgeMetricCatalogSection? in
            let metrics = section.metrics.filter { AppleHealthStore.supportedMetricIDs.contains($0.id) }
            guard !metrics.isEmpty else { return nil }
            return XAgeMetricCatalogSection(
                title: "Apple 健康 · \(section.title)",
                icon: section.icon,
                accent: section.accent,
                metrics: metrics
            )
        }
        let unsupportedMetrics = rawAppleHealthCatalogSections
            .flatMap(\.metrics)
            .filter { !AppleHealthStore.supportedMetricIDs.contains($0.id) }
        guard !unsupportedMetrics.isEmpty else { return supportedSections }
        return supportedSections + [
            XAgeMetricCatalogSection(
                title: "其他来源 / 暂不支持自动同步",
                icon: "square.and.pencil",
                accent: Color(hex: "6C8194"),
                metrics: unsupportedMetrics
            )
        ]
    }

    private static let rawAppleHealthCatalogSections: [XAgeMetricCatalogSection] = [
        XAgeMetricCatalogSection(
            title: "健身记录",
            icon: "figure.run",
            accent: Color(hex: "FF5A1F"),
            metrics: [
                catalogMetric("steps", "步数", "今日步数。", "步", Color(hex: "FF5A1F")),
                catalogMetric("distance", "步行+跑步距离", "今日步行和跑步距离。", "km", Color(hex: "18B7D6")),
                catalogMetric("exerciseMinutes", "锻炼分钟数", "Apple 健康记录的锻炼分钟。", "min", Color(hex: "14B887")),
                catalogMetric("activeMinutes", "活动分钟数", "日常活动累计分钟。", "min", Color(hex: "20CDB1")),
                catalogMetric("activeEnergy", "活动能量", "活动消耗能量。", "kcal", Color(hex: "EF9A3D")),
                catalogMetric("basalEnergy", "静息能量", "基础代谢消耗能量。", "kcal", Color(hex: "F3B349")),
                catalogMetric("flights", "爬楼层数", "今日爬楼层数。", "层", Color(hex: "4E8FE9")),
                catalogMetric("cyclingDistance", "骑行距离", "骑行训练或通勤距离。", "km", Color(hex: "11A7C8")),
                catalogMetric("swimmingDistance", "游泳距离", "游泳训练距离。", "m", Color(hex: "238AD6")),
                catalogMetric("swimmingStrokes", "划水次数", "游泳划水次数。", "次", Color(hex: "2A79C7")),
                catalogMetric("wheelchairDistance", "推轮椅距离", "轮椅推动距离。", "km", Color(hex: "7B4DFF")),
                catalogMetric("vo2Max", "心肺适能", "最大摄氧量，用于评估心肺耐力。", "ml/kg/min", Color(hex: "F05B72"))
            ]
        ),
        XAgeMetricCatalogSection(
            title: "身体测量",
            icon: "figure.stand",
            accent: Color(hex: "11A7C8"),
            metrics: [
                catalogMetric("bodyHeight", "身高", "个人身高记录。", "cm", Color(hex: "238AD6")),
                catalogMetric("bodyWeight", "体重", "最近一次体重。", "kg", Color(hex: "11A7C8")),
                catalogMetric("bodyMassIndex", "BMI", "体重和身高计算出的体质指数。", "", Color(hex: "20CDB1")),
                catalogMetric("bodyFat", "体脂率", "身体脂肪比例。", "%", Color(hex: "A47BEF")),
                catalogMetric("leanBodyMass", "瘦体重", "除脂肪外的体重估算。", "kg", Color(hex: "7B4DFF")),
                catalogMetric("waistCircumference", "腰围", "腹部脂肪和代谢风险参考。", "cm", Color(hex: "EF9A3D")),
                catalogMetric("bodyTemperature", "体温", "最近一次体温。", "°C", Color(hex: "EF9A3D")),
                catalogMetric("basalBodyTemperature", "基础体温", "静息状态体温趋势。", "°C", Color(hex: "F3B349"))
            ]
        ),
        XAgeMetricCatalogSection(
            title: "心脏",
            icon: "heart.fill",
            accent: Color(hex: "F05B72"),
            metrics: [
                catalogMetric("heartRate", "心率", "最近一次心率。", "bpm", Color(hex: "F05B72")),
                catalogMetric("restingHeartRate", "静息心率", "最近一次静息心率。", "bpm", Color(hex: "F05B72")),
                catalogMetric("walkingHeartRateAverage", "步行心率平均值", "步行时平均心率。", "bpm", Color(hex: "DB5B9B")),
                catalogMetric("hrv", "心率变异性", "最近一次 HRV。", "ms", Color(hex: "7B4DFF")),
                catalogMetric("heartRateRecovery", "心率恢复", "运动后心率下降速度。", "bpm", Color(hex: "EF9A3D")),
                catalogMetric("systolicBloodPressure", "收缩压", "血压高压。", "mmHg", Color(hex: "DB5B9B")),
                catalogMetric("diastolicBloodPressure", "舒张压", "血压低压。", "mmHg", Color(hex: "A47BEF"))
            ]
        ),
        XAgeMetricCatalogSection(
            title: "睡眠与呼吸",
            icon: "bed.double.fill",
            accent: Color(hex: "14B887"),
            metrics: [
                catalogMetric("sleep", "睡眠", "最近一晚睡眠时长。", "h", Color(hex: "14B887")),
                catalogMetric("sleepScore", "睡眠评分", "Apple 健康的睡眠评分。", "", Color(hex: "20CDB1")),
                catalogMetric("timeInBed", "卧床时间", "上床到起床的总时长。", "h", Color(hex: "238AD6")),
                catalogMetric("respiratoryRate", "呼吸频率", "最近一次呼吸频率。", "次/分", Color(hex: "2A79C7")),
                catalogMetric("bloodOxygen", "血氧", "最近一次血氧饱和度。", "%", Color(hex: "7B4DFF")),
                catalogMetric("inhalerUsage", "吸入器使用次数", "呼吸相关用药使用次数。", "次", Color(hex: "11A7C8"))
            ]
        ),
        XAgeMetricCatalogSection(
            title: "营养与代谢",
            icon: "fork.knife",
            accent: Color(hex: "EF9A3D"),
            metrics: [
                catalogMetric("glucose", "血糖波动", "血糖或 CGM 趋势。", "mmol/L", Color(hex: "11A7C8")),
                catalogMetric("bloodGlucose", "血糖", "血糖测量值。", "mmol/L", Color(hex: "11A7C8")),
                catalogMetric("insulinDelivery", "胰岛素输注", "胰岛素记录。", "IU", Color(hex: "238AD6")),
                catalogMetric("dietaryEnergy", "膳食能量", "饮食摄入能量。", "kcal", Color(hex: "EF9A3D")),
                catalogMetric("dietaryWater", "水", "饮水量。", "ml", Color(hex: "2A79C7")),
                catalogMetric("dietaryCarbs", "碳水化合物", "饮食碳水摄入。", "g", Color(hex: "F3B349")),
                catalogMetric("dietaryProtein", "蛋白质", "饮食蛋白摄入。", "g", Color(hex: "20CDB1")),
                catalogMetric("dietaryFat", "总脂肪", "饮食脂肪摄入。", "g", Color(hex: "A47BEF")),
                catalogMetric("dietaryFiber", "膳食纤维", "饮食纤维摄入。", "g", Color(hex: "14B887")),
                catalogMetric("dietaryCaffeine", "咖啡因", "咖啡因摄入。", "mg", Color(hex: "7B4DFF"))
            ]
        ),
        XAgeMetricCatalogSection(
            title: "身心与环境",
            icon: "sun.max.fill",
            accent: Color(hex: "F3B349"),
            metrics: [
                catalogMetric("mindfulMinutes", "正念分钟", "冥想或正念训练时间。", "min", Color(hex: "20CDB1")),
                catalogMetric("daylight", "日照时间", "户外日照暴露时间。", "min", Color(hex: "F3B349")),
                catalogMetric("environmentalAudio", "环境噪声级别", "环境声音暴露。", "dB", Color(hex: "6C8194")),
                catalogMetric("headphoneAudio", "耳机音量", "耳机声音暴露。", "dB", Color(hex: "238AD6")),
                catalogMetric("uvExposure", "紫外线指数", "紫外线暴露水平。", "", Color(hex: "EF9A3D"))
            ]
        ),
        XAgeMetricCatalogSection(
            title: "生理记录",
            icon: "calendar.badge.clock",
            accent: Color(hex: "DB5B9B"),
            metrics: [
                catalogMetric("menstrualFlow", "经期", "经期流量记录。", "", Color(hex: "DB5B9B")),
                catalogMetric("intermenstrualBleeding", "点滴出血", "非经期出血记录。", "", Color(hex: "F05B72")),
                catalogMetric("cervicalMucus", "宫颈黏液质量", "生理周期相关记录。", "", Color(hex: "A47BEF")),
                catalogMetric("ovulationTest", "排卵测试结果", "排卵测试记录。", "", Color(hex: "7B4DFF")),
                catalogMetric("sexualActivity", "性活动", "生理健康相关记录。", "", Color(hex: "20CDB1")),
                catalogMetric("symptoms", "症状", "身体症状记录。", "", Color(hex: "EF9A3D"))
            ]
        )
    ]

    private static let serverKnowledgeCandidates: [XAgeMetric] = [
        serverMetric("server-wbc", "白细胞", "血常规", "免疫与感染状态参考。", "×10^9/L", Color(hex: "F05B72")),
        serverMetric("server-rbc", "红细胞", "血常规", "携氧能力和贫血风险参考。", "×10^12/L", Color(hex: "DB5B9B")),
        serverMetric("server-hgb", "血红蛋白", "血常规", "贫血与携氧能力核心指标。", "g/L", Color(hex: "A47BEF")),
        serverMetric("server-plt", "血小板", "血常规", "凝血和炎症风险参考。", "×10^9/L", Color(hex: "7B4DFF")),
        serverMetric("server-alt", "谷丙转氨酶", "肝功能", "肝细胞损伤敏感指标。", "U/L", Color(hex: "EF9A3D")),
        serverMetric("server-ast", "谷草转氨酶", "肝功能", "肝脏、心肌和肌肉损伤参考。", "U/L", Color(hex: "F3B349")),
        serverMetric("server-tbil", "总胆红素", "肝功能", "肝胆代谢和黄疸风险参考。", "μmol/L", Color(hex: "EF9A3D")),
        serverMetric("server-alb", "白蛋白", "肝功能", "营养、肝合成和慢性病状态参考。", "g/L", Color(hex: "20CDB1")),
        serverMetric("server-ggt", "γ-谷氨酰转肽酶", "肝功能", "胆道和酒精相关肝负荷参考。", "U/L", Color(hex: "F3B349")),
        serverMetric("server-creatinine", "肌酐", "肾功能", "肾小球滤过能力参考。", "μmol/L", Color(hex: "238AD6")),
        serverMetric("server-bun", "尿素氮", "肾功能", "蛋白代谢、脱水和肾功能参考。", "mmol/L", Color(hex: "2A79C7")),
        serverMetric("server-uric-acid", "尿酸", "肾功能", "痛风和代谢风险参考。", "μmol/L", Color(hex: "7B4DFF")),
        serverMetric("server-tc", "总胆固醇", "血脂", "总体血脂水平。", "mmol/L", Color(hex: "EF9A3D")),
        serverMetric("server-tg", "甘油三酯", "血脂", "脂肪肝和心血管代谢风险参考。", "mmol/L", Color(hex: "F3B349")),
        serverMetric("server-hdl", "高密度脂蛋白", "血脂", "心血管保护性脂蛋白。", "mmol/L", Color(hex: "20CDB1")),
        serverMetric("server-ldl", "低密度脂蛋白", "血脂", "动脉粥样硬化风险核心指标。", "mmol/L", Color(hex: "F05B72")),
        serverMetric("server-fbg", "空腹血糖", "血糖", "空腹状态糖代谢参考。", "mmol/L", Color(hex: "11A7C8")),
        serverMetric("server-hba1c", "糖化血红蛋白", "血糖", "近 3 个月平均血糖水平。", "%", Color(hex: "238AD6")),
        serverMetric("server-2hpg", "餐后2小时血糖", "血糖", "餐后糖耐量参考。", "mmol/L", Color(hex: "2A79C7")),
        serverMetric("server-tsh", "促甲状腺激素", "甲状腺", "甲状腺功能调节核心指标。", "mIU/L", Color(hex: "7B4DFF")),
        serverMetric("server-ft3", "游离T3", "甲状腺", "活性甲状腺激素。", "pmol/L", Color(hex: "A47BEF")),
        serverMetric("server-ft4", "游离T4", "甲状腺", "甲状腺激素前体。", "pmol/L", Color(hex: "DB5B9B")),
        serverMetric("server-waist", "腰围", "体格", "中心性肥胖和代谢风险参考。", "cm", Color(hex: "EF9A3D")),
        serverMetric("server-cortisol", "皮质醇", "内分泌", "压力轴负荷参考。", "nmol/L", Color(hex: "F3B349")),
        serverMetric("server-hscrp", "hsCRP", "炎症", "低度炎症负荷参考。", "mg/L", Color(hex: "F05B72")),
        serverMetric("server-il6", "IL-6", "炎症", "炎症因子负荷参考。", "pg/mL", Color(hex: "DB5B9B"))
    ]

    private static func catalogMetric(_ id: String, _ title: String, _: String, _: String, _ accent: Color) -> XAgeMetric {
        let semantics = XAgeAppleHealthCatalogSemantics.resolve(metricID: id, title: title)
        return XAgeMetric(
            id: id,
            title: title,
            value: semantics.value,
            unit: "",
            time: semantics.time,
            subtitle: semantics.subtitle,
            accent: accent,
            source: semantics.source,
            isPlaceholder: true
        )
    }

    private static func serverMetric(_ id: String, _ title: String, _ category: String, _ subtitle: String, _ unit: String, _ accent: Color) -> XAgeMetric {
        XAgeMetric(
            id: id,
            title: title,
            value: "待上传",
            unit: unit,
            time: category,
            subtitle: "服务器指标库：\(subtitle)",
            accent: accent,
            source: "server_catalog",
            isPlaceholder: true
        )
    }

    private static func deduped(_ source: [XAgeMetric]) -> [XAgeMetric] {
        var seenIDs = Set<String>()
        var seenTitles = Set<String>()
        var result: [XAgeMetric] = []
        for metric in source {
            let title = metric.title.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
            guard !seenIDs.contains(metric.id), !seenTitles.contains(title) else { continue }
            seenIDs.insert(metric.id)
            seenTitles.insert(title)
            result.append(metric)
        }
        return result
    }

    static func appleHealthMetric(from sample: AppleHealthSyncSample) -> XAgeMetric? {
        let fallback = appleHealthCandidates.first { $0.id == sample.metricID }
        let defaultMetric = defaultCards.first { $0.id == sample.metricID }
        let catalogMetric = rawAppleHealthCatalogSections
            .lazy
            .flatMap(\.metrics)
            .first { $0.id == sample.metricID }
        let base = fallback ?? defaultMetric ?? catalogMetric
        guard let base else { return nil }
        let measuredAt = appleHealthISOFormatter.string(from: sample.measuredAt)
        return XAgeMetric(
            id: sample.metricID,
            title: sample.indicatorName,
            value: sample.displayValue,
            unit: sample.displayUnit,
            time: appleHealthTimeLabel(sample.measuredAt),
            subtitle: "\(sample.subtitle)，已同步到服务器并更新用户端趋势。",
            accent: base.accent,
            source: "apple_health",
            measuredAt: measuredAt
        )
    }

    private static func appleHealthTimeLabel(_ date: Date) -> String {
        if Calendar.current.isDateInToday(date) {
            return appleHealthTimeFormatter.string(from: date)
        }
        return appleHealthShortFormatter.string(from: date)
    }

    private static let appleHealthISOFormatter = ISO8601DateFormatter()

    private static let appleHealthShortFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "zh_CN")
        formatter.dateFormat = "M月d日"
        return formatter
    }()

    private static let appleHealthTimeFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "zh_CN")
        formatter.dateFormat = "H:mm"
        return formatter
    }()
}

extension XAgeMetric {
    var libraryIconName: String {
        switch id {
        case "steps": return "figure.walk"
        case "distance", "cyclingDistance", "wheelchairDistance": return "map.fill"
        case "exerciseMinutes", "activeMinutes", "mindfulMinutes": return "timer"
        case "activeEnergy", "basalEnergy", "dietaryEnergy": return "flame.fill"
        case "flights": return "figure.stairs"
        case "swimmingDistance", "swimmingStrokes": return "water.waves"
        case "vo2Max": return "lungs.fill"
        case "bodyHeight", "leanBodyMass": return "figure.stand"
        case "bodyWeight": return "scalemass.fill"
        case "bodyMassIndex", "bodyFat": return "percent"
        case "waistCircumference": return "ruler.fill"
        case "bodyTemperature", "basalBodyTemperature", "temp": return "thermometer.medium"
        case "heartRate", "restingHeartRate", "walkingHeartRateAverage": return "heart.fill"
        case "hrv", "heartRateRecovery": return "waveform.path.ecg"
        case "systolicBloodPressure", "diastolicBloodPressure": return "gauge"
        case "sleep", "sleepScore", "timeInBed": return "bed.double.fill"
        case "respiratoryRate", "inhalerUsage": return "lungs.fill"
        case "bloodOxygen": return "drop.fill"
        case "glucose", "bloodGlucose", "insulinDelivery": return "drop.triangle.fill"
        case "dietaryWater": return "drop.fill"
        case "dietaryCarbs", "dietaryProtein", "dietaryFat", "dietaryFiber", "dietaryCaffeine": return "fork.knife"
        case "daylight", "uvExposure": return "sun.max.fill"
        case "environmentalAudio", "headphoneAudio": return "ear.fill"
        case "menstrualFlow", "intermenstrualBleeding", "cervicalMucus", "ovulationTest", "sexualActivity": return "calendar.badge.clock"
        case "symptoms": return "cross.case.fill"
        default:
            if id.hasPrefix("server-") || source == "server_catalog" || source == "document" {
                return "cross.case.fill"
            }
            return "chart.line.uptrend.xyaxis"
        }
    }
}
