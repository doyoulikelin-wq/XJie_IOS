import Foundation
import SwiftUI

/// 首页服务端聚合同步模型。
///
/// 使用 `APIServiceProtocol` 拉取当前账号的资料、健康指标、趋势、文档和计划，并生成首页只读快照。
/// `accountScope` 用于隔离账号切换；任何请求完成后都必须再次校验作用域，避免旧账号结果覆盖新账号页面。
@MainActor
final class XAgeServerSyncViewModel: ObservableObject {
    @Published private(set) var snapshot = XAgeServerSyncSnapshot.placeholder
    @Published private(set) var metricCards: [XAgeMetric] = []
    @Published private(set) var indicatorCatalogCards: [XAgeMetric] = []
    @Published private(set) var metricTrends: [IndicatorTrend] = []
    @Published private(set) var isLoading = false

    private let api: APIServiceProtocol
    private var refreshGate = XAgeAccountScopedRefreshGate(accountScope: nil)

    /// 创建服务端同步模型。
    /// - Parameter api: 可替换的 API 抽象；正式环境默认使用共享服务，测试可注入确定性实现。
    init(api: APIServiceProtocol = APIService.shared) {
        self.api = api
    }

    /// 切换当前账号作用域并清空上一账号的页面快照。
    /// - Parameter accountScope: 当前登录账号的隔离标识；`nil` 表示退出登录或无有效账号。
    func setAccountScope(_ accountScope: String?) {
        guard refreshGate.switchAccount(to: accountScope) else { return }
        snapshot = refreshGate.accountScope == nil ? .loggedOut : .placeholder
        metricCards = []
        indicatorCatalogCards = []
        metricTrends = []
        isLoading = false
    }

    /// 并发刷新首页需要的服务端资料，并只接纳仍属于当前账号的一组结果。
    func refresh() async {
        let auth = AuthManager.shared
        if auth.isUIValidationSession {
            setAccountScope(nil)
            snapshot = XAgeServerSyncSnapshot.placeholder
            metricCards = []
            indicatorCatalogCards = []
            metricTrends = []
            return
        }

        guard auth.isLoggedIn, let startedAccountScope = auth.accountScope else {
            setAccountScope(nil)
            snapshot = .loggedOut
            metricCards = []
            indicatorCatalogCards = []
            metricTrends = []
            return
        }
        setAccountScope(startedAccountScope)
        let startedGeneration = refreshGate.generation

        isLoading = true
        defer {
            if refreshGate.accountScope == startedAccountScope,
               refreshGate.generation == startedGeneration {
                isLoading = false
            }
        }

        async let userReq: UserInfo? = getOptional("/api/users/me")
        async let dashboardReq: DashboardHealth? = getOptional("/api/dashboard/health")
        async let todayReq: TodayBriefing? = getOptional("/api/agent/today")
        async let summaryReq: HealthDataSummary? = getOptional("/api/health-data/summary")
        async let recordReq: DocumentListResponse? = getOptional("/api/health-data/documents?doc_type=record")
        async let examReq: DocumentListResponse? = getOptional("/api/health-data/documents?doc_type=exam")
        async let indicatorReq: IndicatorListResponse? = getOptional("/api/health-data/indicators")
        async let watchedReq: WatchedListResponse? = getOptional("/api/health-data/indicators/watched")
        async let conversationsReq: [ChatConversation]? = getOptional("/api/chat/conversations?limit=20&offset=0")
        async let plansReq: HealthPlanListResponse? = getOptional("/api/health-plans")
        async let elderlyReq: ElderlyCheckinList? = getOptional("/api/elderly?limit=20&days=30")

        let user = await userReq
        let dashboard = await dashboardReq
        let today = await todayReq
        let summary = await summaryReq
        let records = await recordReq
        let exams = await examReq
        let indicators = await indicatorReq
        let watched = await watchedReq
        let conversations = await conversationsReq
        let plans = await plansReq
        let elderly = await elderlyReq

        guard refreshGate.accepts(
            startedScope: startedAccountScope,
            generation: startedGeneration,
            currentScope: auth.accountScope
        ) else { return }

        let watchedNames = watched?.items.map(\.indicator_name) ?? []
        let indicatorItems = indicators?.indicators ?? []
        let trendNames = Self.trendRequestNames(watchedNames: watchedNames)
        let trendResponse = await fetchTrends(for: trendNames)
        let trends = trendResponse?.indicators ?? []

        guard !Task.isCancelled,
              refreshGate.accepts(
                startedScope: startedAccountScope,
                generation: startedGeneration,
                currentScope: auth.accountScope
              ) else { return }

        snapshot = XAgeServerSyncSnapshot(
            isLoaded: true,
            isLoggedOut: false,
            summaryUpdatedAt: summary?.updated_at,
            hasSummary: !(summary?.summary_text?.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ?? true),
            recordCount: records?.items?.count ?? records?.total ?? 0,
            examCount: exams?.items?.count ?? exams?.total ?? 0,
            trustedDocumentCount: (records?.items ?? []).filter(\.isTrustedForScoreInputs).count
                + (exams?.items ?? []).filter(\.isTrustedForScoreInputs).count,
            indicatorCount: indicators?.indicators.count ?? 0,
            watchedIndicatorCount: watchedNames.count,
            trendPointCount: trends.reduce(0) { $0 + $1.points.count },
            conversationCount: conversations?.count ?? 0,
            planCount: plans?.items.count ?? 0,
            feedbackCount: elderly?.items.count ?? 0,
            profileCompletion: Self.profileCompletion(user?.profile),
            latestDocumentDate: Self.latestDocumentDate(records: records?.items ?? [], exams: exams?.items ?? []),
            dashboardScore: dashboard?.metabolic_state?.score,
            todayGoalCount: today?.today_goals?.count ?? today?.daily_plan?.payload.today_goals?.count ?? 0,
            primaryWatchedName: watchedNames.first,
            userAge: user?.profile?.age,
            profileHeightCm: user?.profile?.height_cm,
            profileWeightKg: user?.profile?.weight_kg,
            algorithmTrends: Self.algorithmTrends(
                from: trends,
                records: records?.items ?? [],
                exams: exams?.items ?? []
            )
        )
        metricCards = Self.metricCards(from: trends, dashboard: dashboard)
        indicatorCatalogCards = Self.indicatorCatalogCards(from: indicatorItems)
        metricTrends = trends
    }

    /// 查找某张指标卡对应的服务端趋势。
    /// - Parameter metric: 带稳定 ID 和标题的首页指标。
    /// - Returns: 匹配到的趋势；没有服务端数据时返回 `nil`。
    func trend(for metric: XAgeMetric) -> IndicatorTrend? {
        let title = metric.title.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        return metricTrends.first {
            $0.name.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() == title
        }
    }

    private func getOptional<T: Decodable>(_ path: String) async -> T? {
        try? await api.get(path)
    }

    private func fetchTrends(for names: [String]) async -> IndicatorTrendResponse? {
        guard !names.isEmpty else { return nil }
        var merged: [IndicatorTrend] = []
        var start = 0
        while start < names.count {
            let end = min(start + 10, names.count)
            let batch = Array(names[start..<end])
            if let response = await fetchTrendBatch(for: batch) {
                merged.append(contentsOf: response.indicators)
            }
            start = end
        }
        return merged.isEmpty ? nil : IndicatorTrendResponse(indicators: Self.dedupedTrends(merged))
    }

    private func fetchTrendBatch(for names: [String]) async -> IndicatorTrendResponse? {
        let joined = names.joined(separator: ",")
        var allowed = CharacterSet.urlQueryAllowed
        allowed.remove(charactersIn: "+&=?")
        let encoded = joined.addingPercentEncoding(withAllowedCharacters: allowed) ?? joined
        return try? await api.get("/api/health-data/indicators/trend?names=\(encoded)")
    }

    private static func trendRequestNames(watchedNames: [String]) -> [String] {
        XAgeHealthTrendRequestContract.names(watchedNames: watchedNames)
    }

    private static func dedupedTrends(_ source: [IndicatorTrend]) -> [IndicatorTrend] {
        var seen = Set<String>()
        return source.filter { trend in
            seen.insert(trend.name.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()).inserted
        }
    }

    private static func metricCards(from trends: [IndicatorTrend], dashboard: DashboardHealth?) -> [XAgeMetric] {
        let accents = [
            Color(hex: "238AD6"),
            Color(hex: "20CDB1"),
            Color(hex: "EF9A3D"),
            Color(hex: "7B4DFF")
        ]
        let trendCards = trends
            .filter { !isLegacyCombinedBloodPressure($0.name) }
            .enumerated()
            .compactMap { item -> XAgeMetric? in
                let (index, trend) = item
                guard let latest = latestPoint(from: trend.points) else { return nil }
                let source = latest.source ?? "document"
                let measuredRaw = latest.measured_at ?? latest.source_local_date ?? latest.date
                let dateLabel = XAgeServerSyncFormat.cardTime(measuredRaw, source: source)
                let stale = staleness(for: trend.name, source: source, measuredAt: measuredRaw)
                let sourceDescription = sourceLabel(source)
                let subtitle: String
                if stale.isStale {
                    subtitle = "\(sourceDescription) \(dateLabel)；已超过 \(stale.limitDays) 天未更新，仅作历史参考。"
                } else if latest.abnormal {
                    subtitle = "\(sourceDescription) \(dateLabel)；最近一次结果异常，已纳入当前趋势。"
                } else {
                    subtitle = "\(sourceDescription) \(dateLabel)；已同步到当前版本。"
                }
                return XAgeMetric(
                    id: canonicalMetricID(for: trend.name),
                    title: trend.name,
                    value: Self.displayValue(latest, indicatorName: trend.name),
                    unit: trend.unit ?? "",
                    time: stale.isStale ? "需更新" : dateLabel,
                    subtitle: subtitle,
                    accent: accents[index % accents.count],
                    source: source,
                    measuredAt: measuredRaw,
                    isStale: stale.isStale
                )
            }
        return dedupedMetrics([glucoseMetric(from: dashboard)].compactMap { $0 } + trendCards)
    }

    @MainActor
    private static func glucoseMetric(from dashboard: DashboardHealth?) -> XAgeMetric? {
        guard let summary = dashboard?.glucose?.last_24h,
              let avg = summary.avg else { return nil }
        let value = Utils.formatGlucose(avg, withUnit: false)
        let unit = Utils.glucoseUnitLabel
        let tir = summary.tir_70_180_pct.map { "TIR \(Int($0.rounded()))%" } ?? "TIR 待同步"
        let variability = summary.variability?.isEmpty == false ? summary.variability! : "波动待评估"
        let latest = dashboard?.cgm_quality?.latest_ts
        let time = XAgeServerSyncFormat.cardTime(latest, source: "cgm")
        let stale = staleness(for: "血糖波动", source: "cgm", measuredAt: latest)
        return XAgeMetric(
            id: "glucose",
            title: "血糖波动",
            value: value,
            unit: unit,
            time: stale.isStale ? "需更新" : time,
            subtitle: "CGM 最近 24 小时平均值；\(tir)，\(variability)。",
            accent: Color(hex: "11A7C8"),
            source: "cgm",
            measuredAt: latest,
            isStale: stale.isStale
        )
    }

    private static func indicatorCatalogCards(from indicators: [IndicatorInfo]) -> [XAgeMetric] {
        indicators
            .filter { !isLegacyCombinedBloodPressure($0.name) }
            .prefix(80)
            .enumerated()
            .map { index, indicator in
                let accents = [
                    Color(hex: "238AD6"),
                    Color(hex: "20CDB1"),
                    Color(hex: "EF9A3D"),
                    Color(hex: "7B4DFF"),
                    Color(hex: "F05B72")
                ]
                let countText = indicator.count > 0 ? "\(indicator.count)点" : "待上传"
                return XAgeMetric(
                    id: canonicalMetricID(for: indicator.name),
                    title: indicator.name,
                    value: countText,
                    unit: "",
                    time: indicator.category ?? "服务器",
                    subtitle: "来自服务器指标库；已有 \(indicator.count) 个历史点，可置顶后查看趋势或继续补录。",
                    accent: accents[index % accents.count],
                    source: indicator.count > 0 ? "server_indicator_catalog" : "server_catalog",
                    isPlaceholder: indicator.count == 0
                )
            }
    }

    private static func dedupedMetrics(_ source: [XAgeMetric]) -> [XAgeMetric] {
        var seenIDs = Set<String>()
        var seenTitles = Set<String>()
        var result: [XAgeMetric] = []
        for metric in source {
            let titleKey = metric.title.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
            guard !seenIDs.contains(metric.id), !seenTitles.contains(titleKey) else { continue }
            seenIDs.insert(metric.id)
            seenTitles.insert(titleKey)
            result.append(metric)
        }
        return result
    }

    private static func latestPoint(from points: [TrendPoint]) -> TrendPoint? {
        points.sorted {
            let lhs = XAgeServerSyncFormat.date(from: $0.measured_at ?? $0.source_local_date ?? $0.date) ?? .distantPast
            let rhs = XAgeServerSyncFormat.date(from: $1.measured_at ?? $1.source_local_date ?? $1.date) ?? .distantPast
            return lhs < rhs
        }.last
    }

    private static func staleness(for name: String, source: String, measuredAt raw: String?) -> (isStale: Bool, limitDays: Int) {
        let limit = freshnessLimitDays(for: name, source: source)
        guard let date = XAgeServerSyncFormat.date(from: raw) else { return (false, limit) }
        let days = Calendar.current.dateComponents(
            [.day],
            from: Calendar.current.startOfDay(for: date),
            to: Calendar.current.startOfDay(for: Date())
        ).day ?? 0
        return (max(0, days) > limit, limit)
    }

    private static func freshnessLimitDays(for name: String, source: String) -> Int {
        if source.lowercased() == "apple_health",
           let registryLimit = XAgeHealthMetricRegistryContract.freshnessLimitDays(forIndicatorName: name) {
            return registryLimit
        }
        let normalized = name.lowercased()
        if ["体重", "体脂", "血压", "收缩压", "舒张压"].contains(where: { normalized.contains($0) }) {
            return 14
        }
        if ["步数", "睡眠", "hrv", "心率", "呼吸", "血氧", "活动", "运动", "爬楼", "距离", "能量"].contains(where: { normalized.contains($0.lowercased()) }) {
            return 2
        }
        return 180
    }

    private static func sourceLabel(_ source: String?) -> String {
        switch (source ?? "").lowercased() {
        case "apple_health": return "Apple 健康"
        case "manual": return "手动记录"
        case "device": return "设备同步"
        case "cgm": return "CGM"
        default: return "报告趋势"
        }
    }

    private static func isLegacyCombinedBloodPressure(_ name: String) -> Bool {
        name.trimmingCharacters(in: .whitespacesAndNewlines) == "血压"
    }

    private static func canonicalMetricID(for name: String) -> String {
        if let registeredID = XAgeHealthMetricRegistryContract.metricID(forIndicatorName: name) {
            return registeredID
        }
        let normalized = name.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if normalized.contains("hrv") || normalized.contains("心率变异") { return "hrv" }
        if normalized.contains("睡眠") { return "sleep" }
        if normalized.contains("血糖") || normalized.contains("葡萄糖") { return "glucose" }
        if normalized.contains("体温") { return "temp" }
        if normalized.contains("步数") { return "steps" }
        if normalized.contains("步行+跑步距离") || normalized.contains("步行跑步距离") { return "distance" }
        if normalized.contains("活动能量") { return "activeEnergy" }
        if normalized.contains("运动分钟") { return "exerciseMinutes" }
        if normalized.contains("爬楼") { return "flights" }
        if normalized.contains("静息心率") { return "restingHeartRate" }
        if normalized.contains("呼吸频率") { return "respiratoryRate" }
        if normalized.contains("血氧") { return "bloodOxygen" }
        if normalized.contains("收缩压") { return "systolicBloodPressure" }
        if normalized.contains("舒张压") { return "diastolicBloodPressure" }
        if normalized.contains("体重") { return "bodyWeight" }
        if normalized.contains("体脂") { return "bodyFat" }
        if normalized.contains("正念") { return "mindfulMinutes" }
        if normalized.contains("日照") { return "daylight" }
        return "server-\(name)"
    }

    private static func displayValue(_ value: Double, indicatorName: String) -> String {
        if let categoryValue = XAgeHealthMetricRegistryContract.categoryDisplayValue(
            forIndicatorName: indicatorName,
            value: value
        ) {
            return categoryValue
        }
        if value.rounded() == value {
            return String(Int(value))
        }
        if abs(value) >= 100 {
            return String(format: "%.1f", value)
        }
        return String(format: "%.2f", value).replacingOccurrences(of: #"\.?0+$"#, with: "", options: .regularExpression)
    }

    private static func displayValue(_ point: TrendPoint, indicatorName: String) -> String {
        point.preferredDisplayValue ?? displayValue(point.value, indicatorName: indicatorName)
    }

    private static func algorithmTrends(
        from trends: [IndicatorTrend],
        records: [HealthDocument],
        exams: [HealthDocument]
    ) -> [XAgeAlgorithmTrend] {
        var items = trends.compactMap { trend -> XAgeAlgorithmTrend? in
            guard let latest = latestPoint(from: trend.points) else { return nil }
            return XAgeAlgorithmTrend(
                name: trend.name,
                value: latest.value,
                unit: trend.unit,
                refLow: trend.ref_low,
                refHigh: trend.ref_high,
                abnormal: latest.abnormal,
                measuredAt: latest.measured_at ?? latest.source_local_date ?? latest.date,
                source: latest.source ?? "server_trend",
                confidence: trend.points.count >= 2 ? 0.82 : 0.72
            )
        }

        for document in (records + exams).filter(\.isTrustedForScoreInputs) {
            let documentDate = document.doc_date
            items.append(contentsOf: labFeatures(from: document.abnormal_flags ?? [], date: documentDate))
            items.append(contentsOf: labFeatures(from: document.csv_data, date: documentDate))
        }

        var unique: [String: XAgeAlgorithmTrend] = [:]
        for item in items {
            let key = XAgeAlgorithmTrend.normalizedKey(item.name)
            if let existing = unique[key], existing.source == "server_trend" {
                continue
            }
            unique[key] = item
        }
        return Array(unique.values)
    }

    private static func labFeatures(from flags: [AbnormalFlag], date: String?) -> [XAgeAlgorithmTrend] {
        flags.compactMap { flag in
            let name = flag.name ?? flag.field ?? ""
            guard !name.isEmpty, let value = parseNumericValue(flag.value) else { return nil }
            return XAgeAlgorithmTrend(
                name: name,
                value: value,
                unit: flag.unit,
                refLow: nil,
                refHigh: nil,
                abnormal: true,
                measuredAt: date,
                source: "document_flag",
                confidence: 0.62
            )
        }
    }

    private static func labFeatures(from csv: CSVData?, date: String?) -> [XAgeAlgorithmTrend] {
        guard let columns = csv?.columns, let rows = csv?.rows, !columns.isEmpty else { return [] }
        let normalized = columns.map { $0.lowercased() }
        let nameIndex = firstIndex(in: normalized, matching: ["项目", "指标", "名称", "name", "indicator", "item"])
        let valueIndex = firstIndex(in: normalized, matching: ["结果", "数值", "value", "result"])
        let unitIndex = firstIndex(in: normalized, matching: ["单位", "unit"])
        guard let nameIndex, let valueIndex else { return [] }

        return rows.compactMap { row in
            guard row.indices.contains(nameIndex), row.indices.contains(valueIndex) else { return nil }
            let name = row[nameIndex].trimmingCharacters(in: .whitespacesAndNewlines)
            guard !name.isEmpty, let value = parseNumericValue(row[valueIndex]) else { return nil }
            let unit = unitIndex.flatMap { row.indices.contains($0) ? row[$0] : nil }
            return XAgeAlgorithmTrend(
                name: name,
                value: value,
                unit: unit,
                refLow: nil,
                refHigh: nil,
                abnormal: false,
                measuredAt: date,
                source: "document_csv",
                confidence: 0.58
            )
        }
    }

    private static func firstIndex(in columns: [String], matching needles: [String]) -> Int? {
        columns.firstIndex { column in
            needles.contains { column.contains($0) }
        }
    }

    private static func parseNumericValue(_ raw: String?) -> Double? {
        guard let raw else { return nil }
        let normalized = raw
            .replacingOccurrences(of: ",", with: "")
            .replacingOccurrences(of: "＞", with: ">")
            .replacingOccurrences(of: "＜", with: "<")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        let pattern = #"[-+]?\d+(?:\.\d+)?"#
        guard let range = normalized.range(of: pattern, options: .regularExpression) else { return nil }
        return Double(normalized[range])
    }

    private static func profileCompletion(_ profile: UserProfile?) -> Int {
        guard let profile else { return 0 }
        let fields: [Bool] = [
            !(profile.sex?.isEmpty ?? true),
            profile.age != nil,
            profile.height_cm != nil,
            profile.weight_kg != nil,
            !(profile.display_name?.isEmpty ?? true)
        ]
        let filled = fields.filter { $0 }.count
        return Int((Double(filled) / Double(fields.count) * 100).rounded())
    }

    private static func latestDocumentDate(records: [HealthDocument], exams: [HealthDocument]) -> String? {
        (records + exams)
            .compactMap(\.doc_date)
            .sorted()
            .last
    }

}

/// 将服务端时间字段统一转换为首页需要的日期和相对时间文案。
enum XAgeServerSyncFormat {
    static func date(from raw: String?) -> Date? {
        guard let raw, !raw.isEmpty else { return nil }
        return Utils.parseISO(raw) ?? dateOnlyFormatter.date(from: raw)
    }

    static func shortDate(_ raw: String?) -> String {
        guard let raw, !raw.isEmpty else { return "暂无" }
        if let date = date(from: raw) {
            return monthDayFormatter.string(from: date)
        }
        if raw.count >= 10 {
            let end = raw.index(raw.startIndex, offsetBy: 10)
            return String(raw[..<end])
        }
        return raw
    }

    static func cardTime(_ raw: String?, source: String?) -> String {
        guard let raw, !raw.isEmpty else { return "暂无" }
        guard let date = date(from: raw) else { return shortDate(raw) }
        let sourceKey = (source ?? "").lowercased()
        if sourceKey == "apple_health" || sourceKey == "device" || sourceKey == "cgm" {
            if Calendar.current.isDateInToday(date) {
                return timeFormatter.string(from: date)
            }
            return monthDayFormatter.string(from: date)
        }
        return monthDayFormatter.string(from: date)
    }

    private static let dateOnlyFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "zh_CN")
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter
    }()

    private static let monthDayFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "zh_CN")
        formatter.dateFormat = "M月d日"
        return formatter
    }()

    private static let timeFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "zh_CN")
        formatter.dateFormat = "H:mm"
        return formatter
    }()
}

struct XAgeServerSyncSnapshot: Equatable {
    let isLoaded: Bool
    let isLoggedOut: Bool
    let summaryUpdatedAt: String?
    let hasSummary: Bool
    let recordCount: Int
    let examCount: Int
    /// Only report-level confirmed documents whose score workflow completed.
    let trustedDocumentCount: Int
    let indicatorCount: Int
    let watchedIndicatorCount: Int
    let trendPointCount: Int
    let conversationCount: Int
    let planCount: Int
    let feedbackCount: Int
    let profileCompletion: Int
    let latestDocumentDate: String?
    let dashboardScore: Int?
    let todayGoalCount: Int
    let primaryWatchedName: String?
    let userAge: Int?
    let profileHeightCm: Double?
    let profileWeightKg: Double?
    let algorithmTrends: [XAgeAlgorithmTrend]

    static let placeholder = XAgeServerSyncSnapshot(
        isLoaded: false,
        isLoggedOut: false,
        summaryUpdatedAt: nil,
        hasSummary: false,
        recordCount: 0,
        examCount: 0,
        trustedDocumentCount: 0,
        indicatorCount: 0,
        watchedIndicatorCount: 0,
        trendPointCount: 0,
        conversationCount: 0,
        planCount: 0,
        feedbackCount: 0,
        profileCompletion: 0,
        latestDocumentDate: nil,
        dashboardScore: nil,
        todayGoalCount: 0,
        primaryWatchedName: nil,
        userAge: nil,
        profileHeightCm: nil,
        profileWeightKg: nil,
        algorithmTrends: []
    )

    static let loggedOut = XAgeServerSyncSnapshot(
        isLoaded: true,
        isLoggedOut: true,
        summaryUpdatedAt: nil,
        hasSummary: false,
        recordCount: 0,
        examCount: 0,
        trustedDocumentCount: 0,
        indicatorCount: 0,
        watchedIndicatorCount: 0,
        trendPointCount: 0,
        conversationCount: 0,
        planCount: 0,
        feedbackCount: 0,
        profileCompletion: 0,
        latestDocumentDate: nil,
        dashboardScore: nil,
        todayGoalCount: 0,
        primaryWatchedName: nil,
        userAge: nil,
        profileHeightCm: nil,
        profileWeightKg: nil,
        algorithmTrends: []
    )

    var headerCaption: String {
        if !isLoaded { return "正在同步历史数据" }
        if isLoggedOut { return "未登录 · 待登录同步" }
        if recordCount + examCount + indicatorCount == 0 { return "暂无历史同步数据 · 待上传" }
        let date = XAgeServerSyncFormat.shortDate(summaryUpdatedAt ?? latestDocumentDate)
        return "\(date) · 已同步"
    }

    var latestDocumentLabel: String {
        XAgeServerSyncFormat.shortDate(latestDocumentDate)
    }

    var primaryWatchedLabel: String {
        primaryWatchedName ?? "关注指标"
    }

    /// 生成业务面板顶部的三项统计摘要。
    /// - Parameter category: 当前打开的数据业务分类。
    /// - Returns: 与分类对应且顺序稳定的统计项。
    func stats(for category: XAgeDataPanelCategory) -> [XAgePanelStat] {
        switch category {
        case .reports:
            return [
                XAgePanelStat(title: "病历", value: "\(recordCount)", unit: "份"),
                XAgePanelStat(title: "体检", value: "\(examCount)", unit: "份"),
                XAgePanelStat(title: "指标", value: "\(indicatorCount)", unit: "项")
            ]
        case .daily:
            return [
                XAgePanelStat(title: "关注", value: "\(watchedIndicatorCount)", unit: "项"),
                XAgePanelStat(title: "趋势", value: "\(trendPointCount)", unit: "点"),
                XAgePanelStat(title: "目标", value: "\(todayGoalCount)", unit: "条")
            ]
        case .medical:
            return [
                XAgePanelStat(title: "计划", value: "\(planCount)", unit: "个"),
                XAgePanelStat(title: "问答", value: "\(conversationCount)", unit: "次"),
                XAgePanelStat(title: "反馈", value: "\(feedbackCount)", unit: "条")
            ]
        case .profile:
            return [
                XAgePanelStat(title: "基础", value: "\(profileCompletion)", unit: "%"),
                XAgePanelStat(title: "摘要", value: hasSummary ? "有" : "待", unit: ""),
                XAgePanelStat(title: "可信评分", value: "--", unit: "")
            ]
        }
    }
}
