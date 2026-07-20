import AVFoundation
import Speech
import SwiftUI
import UIKit

struct XAgeDataDashboardView: View {
    let managerRequest: Int
    @ObservedObject var appleHealthSync: AppleHealthSyncViewModel
    @ObservedObject var serverSync: XAgeServerSyncViewModel
    let scores: XAgeCompositeScores
    let accountScope: String?
    let onSyncAppleHealth: () async -> Void
    let onOpenMetricGuide: (XAgeDataKind) -> Void
    let onOpenQuickAction: (String) -> Void
    @State private var activeSheet: XAgeDataSheet?
    @State private var showsMetricManager = false
    @State private var metrics: [XAgeMetric]
    @State private var metricPreference: XAgeDataCardPreferenceSnapshot
    @State private var pendingMetricScrollID: String?
    @State private var isTodayStatusHidden = false

    init(
        managerRequest: Int,
        appleHealthSync: AppleHealthSyncViewModel,
        serverSync: XAgeServerSyncViewModel,
        scores: XAgeCompositeScores,
        accountScope: String?,
        onSyncAppleHealth: @escaping () async -> Void,
        onOpenMetricGuide: @escaping (XAgeDataKind) -> Void,
        onOpenQuickAction: @escaping (String) -> Void
    ) {
        self.managerRequest = managerRequest
        self.appleHealthSync = appleHealthSync
        self.serverSync = serverSync
        self.scores = scores
        self.accountScope = accountScope
        self.onSyncAppleHealth = onSyncAppleHealth
        self.onOpenMetricGuide = onOpenMetricGuide
        self.onOpenQuickAction = onOpenQuickAction
        self._metrics = State(initialValue: XAgeDataCardPreferences.initialMetrics(accountScope: accountScope))
        self._metricPreference = State(initialValue: XAgeDataCardPreferences.load(accountScope: accountScope))
    }

    var body: some View {
        VStack(spacing: 0) {
            stickyHeader
            metricsScroll
        }
        .onChange(of: appleHealthSync.samples) { _, samples in
            mergeAppleHealthSamples(samples)
        }
        .onReceive(serverSync.$metricCards) { cards in
            mergeServerMetrics(cards)
        }
        .onReceive(serverSync.$indicatorCatalogCards) { _ in
            restoreMetricPreferencesFromAvailableCatalog()
        }
        .onChange(of: accountScope) { _, newScope in
            resetMetrics(for: newScope)
        }
        .onChange(of: managerRequest) { _, _ in
            showsMetricManager = true
        }
        .task {
            await refreshAllData(includeAppleHealth: true)
        }
        .navigationDestination(isPresented: $showsMetricManager) {
            XAgeMetricManagerPage(
                pinnedMetrics: $metrics,
                catalogSections: metricCatalogSections,
                appleHealthSync: appleHealthSync,
                onSyncAppleHealth: onSyncAppleHealth,
                onMetricsChanged: persistMetricPreferences,
                onOpenMetric: { metric in
                    activeSheet = .metricDetail(metric)
                }
            )
        }
        .sheet(item: $activeSheet) { sheet in
            sheetContent(sheet)
        }
    }

    private var stickyHeader: some View {
        XAgeDataStickyHeader(
            collapseProgress: 0,
            caption: serverSync.snapshot.headerCaption,
            scores: scores,
            showsTodayStatus: !isTodayStatusHidden,
            onSelectDetail: { activeSheet = .detail($0) },
            onSelectInfo: { activeSheet = .scoreInfo($0) }
        )
        .padding(.horizontal, 24)
        .padding(.top, 16)
        .padding(.bottom, 10)
        .zIndex(2)
    }

    private var metricsScroll: some View {
        ScrollViewReader { proxy in
            ScrollView {
                XAgeDataScrollOffsetProbe()
                metricList
            }
            .coordinateSpace(name: XAgeDataScrollSpace.name)
            .scrollIndicators(.hidden)
            .accessibilityIdentifier("xage.data.scroll")
            .refreshable {
                await refreshAllData(includeAppleHealth: true)
            }
            .accessibilityScrollAction { edge in
                switch edge {
                case .bottom:
                    setTodayStatusHidden(true)
                case .top:
                    setTodayStatusHidden(false)
                default:
                    break
                }
            }
            .modifier(
                XAgeDataScrollOffsetTracker { offset in
                    updateTodayStatusVisibility(forOffset: offset)
                }
            )
            .onPreferenceChange(XAgeDataScrollOffsetPreferenceKey.self) { minY in
                updateTodayStatusVisibility(forOffset: max(0, -minY))
            }
            .onChange(of: metrics.count) { _, _ in
                scrollToPendingMetric(with: proxy)
            }
            .onChange(of: metricOrderIDs) { _, _ in
                scrollToPendingMetric(with: proxy)
            }
        }
    }

    private var metricList: some View {
        LazyVStack(spacing: 12) {
            quickActionStrip

            if XAgeAppleHealthSyncFlow.shouldShowHomeAuthorization(
                hasSuccessfulSync: appleHealthSync.lastSyncedAt != nil
            ) {
                XAgeAppleHealthSyncCard(
                    viewModel: appleHealthSync,
                    compactAuthorization: true,
                    onSyncAppleHealth: onSyncAppleHealth
                )
            }

            if metrics.isEmpty {
                XAgeMetricEmptyRow(
                    title: "首页暂无数据卡片",
                    subtitle: "打开数据卡片管理，添加需要长期关注的指标。"
                )
                .accessibilityIdentifier("xage.data.metric.empty")
            }

            ForEach(metrics) { card in
                metricCard(card)
            }

            metricLibraryEntries
        }
        .padding(.horizontal, 24)
        .padding(.top, 10)
        .padding(.bottom, 32)
    }

    private var quickActionStrip: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("快捷功能")
                .font(.system(size: 15, weight: .bold))
                .foregroundStyle(Color(hex: "173F64"))

            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 9) {
                    ForEach(Array(XAgeDataPanelCategory.homeQuickActions.enumerated()), id: \.element.id) { _, action in
                        Button {
                            openQuickAction(action)
                        } label: {
                            VStack(spacing: 6) {
                                Image(systemName: action.systemImage)
                                    .font(.system(size: 20, weight: .bold))
                                    .foregroundStyle(Color(hex: "277EBB"))
                                Text(action.title)
                                    .font(.system(size: action.title.count > 3 ? 11 : 12, weight: .bold))
                                    .foregroundStyle(Color(hex: "173F64"))
                                    .lineLimit(1)
                                    .minimumScaleFactor(0.8)
                            }
                            .frame(width: 72, height: 72)
                            .background(XAgeGlassCardBackground(cornerRadius: 22))
                            .contentShape(RoundedRectangle(cornerRadius: 22, style: .continuous))
                        }
                        .buttonStyle(.plain)
                        .accessibilityLabel(action.title)
                        .accessibilityHint(action.id == "data-manager" ? "打开数据卡片管理" : "打开\(action.title)功能")
                        .accessibilityIdentifier("xage.quickAction.\(action.id)")
                    }
                }
            }
            .accessibilityIdentifier("xage.quickActions")
        }
    }

    private func openQuickAction(_ action: XAgeQuickActionSpec) {
        switch action.id {
        case "data-manager":
            showsMetricManager = true
        case "weight":
            guard let metric = XAgeMetric.appleHealthCandidates.first(where: { $0.id == "bodyWeight" }) else {
                return
            }
            activeSheet = .manualEntry(metric)
        default:
            guard action.destination == action.id else { return }
            onOpenQuickAction(action.id)
        }
    }

    @ViewBuilder
    private var metricLibraryEntries: some View {
        XAgeMetricLibraryEntryCard(
            availableCount: availableCandidateCount,
            totalCount: allCatalogMetrics.count,
            onManage: { showsMetricManager = true }
        )
        .id("metric-library")
        .accessibilityIdentifier("xage.data.metric.library")
    }

    private func metricCard(_ card: XAgeMetric) -> some View {
        XAgeMetricCard(
            card: card
        ) {
            activeSheet = .metricDetail(card)
        }
        .id(card.id)
        .accessibilityIdentifier("xage.data.metric.\(card.id)")
    }

    @ViewBuilder
    private func sheetContent(_ sheet: XAgeDataSheet) -> some View {
        switch sheet {
        case .detail(let kind):
            XAgeDataDetailView(
                kind: kind,
                metric: scores.score(for: kind),
                onSyncAppleHealth: onSyncAppleHealth,
                onOpenGuide: {
                    activeSheet = nil
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.24) {
                        onOpenMetricGuide(kind)
                    }
                }
            )
            .presentationDetents([.large])
            .presentationDragIndicator(.visible)
        case .scoreInfo(let kind):
            XAgeScoreInfoSheet(kind: kind, metric: scores.score(for: kind))
                .presentationDetents([.large])
                .presentationDragIndicator(.visible)
        case .metricDetail(let metric):
            XAgeMetricDetailSheet(
                metric: metric,
                trend: serverSync.trend(for: metric),
                onManualRecord: {
                    activeSheet = .manualEntry(metric)
                }
            )
            .presentationDetents([.large])
            .presentationDragIndicator(.visible)
        case .manualEntry(let metric):
            XAgeManualMetricEntrySheet(
                metric: metric,
                onCancel: {
                    activeSheet = .metricDetail(metric)
                },
                onSaved: {
                    Task {
                        await refreshAllData(includeAppleHealth: false)
                        await MainActor.run {
                            activeSheet = nil
                        }
                    }
                }
            )
            .presentationDetents([.large])
        }
    }

    private func scrollToPendingMetric(with proxy: ScrollViewProxy) {
        guard let metricID = pendingMetricScrollID else { return }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.16) {
            withAnimation(.spring(response: 0.3, dampingFraction: 0.9)) {
                proxy.scrollTo(metricID, anchor: .top)
            }
            pendingMetricScrollID = nil
        }
    }

    private func refreshAllData(includeAppleHealth: Bool) async {
        if includeAppleHealth {
            await appleHealthSync.refreshIfPreviouslySynced()
        }
        await serverSync.refresh()
        mergeServerMetrics(serverSync.metricCards)
    }

    private func updateTodayStatusVisibility(forOffset scrollOffset: CGFloat) {
        let offset = max(0, scrollOffset)
        let shouldHide = isTodayStatusHidden ? offset > 8 : offset > 28
        guard shouldHide != isTodayStatusHidden else { return }
        setTodayStatusHidden(shouldHide)
    }

    private func setTodayStatusHidden(_ hidden: Bool) {
        guard hidden != isTodayStatusHidden else { return }
        withAnimation(.easeInOut(duration: 0.18)) {
            isTodayStatusHidden = hidden
        }
    }

    private var availableCandidateMetrics: [XAgeMetric] {
        let currentIDs = Set(metrics.map(\.id))
        return allCatalogMetrics.filter { !currentIDs.contains($0.id) }
    }

    private var availableCandidateCount: Int {
        availableCandidateMetrics.count
    }

    private var metricOrderIDs: [String] {
        metrics.map(\.id)
    }

    private var metricCatalogSections: [XAgeMetricCatalogSection] {
        XAgeMetric.catalogSections(serverMetrics: serverSync.indicatorCatalogCards)
    }

    private var allCatalogMetrics: [XAgeMetric] {
        dedupedMetrics(metrics + metricCatalogSections.flatMap(\.metrics))
    }

    private func addMetric(_ metric: XAgeMetric) {
        guard !metrics.contains(where: { $0.id == metric.id }) else { return }
        pendingMetricScrollID = metric.id
        withAnimation(.spring(response: 0.26, dampingFraction: 0.88)) {
            metrics.append(metric)
        }
        persistMetricPreferences()
    }

    private func mergeAppleHealthSamples(_ samples: [AppleHealthSyncSample]) {
        let synced = samples.compactMap { XAgeMetric.appleHealthMetric(from: $0) }
        guard !synced.isEmpty else { return }
        withAnimation(.spring(response: 0.26, dampingFraction: 0.88)) {
            if metricPreference.isCustomized {
                metrics = XAgeDataCardPreferences.orderedMetrics(
                    for: metricPreference,
                    from: synced + metrics + metricCatalogSections.flatMap(\.metrics)
                )
            } else {
                for metric in synced {
                    if let index = metrics.firstIndex(where: { $0.id == metric.id }) {
                        metrics[index] = metric
                    } else {
                        metrics.append(metric)
                    }
                }
            }
        }
    }

    private func mergeServerMetrics(_ serverMetrics: [XAgeMetric]) {
        guard !serverMetrics.isEmpty else {
            restoreMetricPreferencesFromAvailableCatalog()
            return
        }
        let shouldAnimate = metrics.contains { metric in
            serverMetrics.contains(where: { $0.id == metric.id })
        }
        let apply = {
            if metricPreference.isCustomized {
                metrics = XAgeDataCardPreferences.orderedMetrics(
                    for: metricPreference,
                    from: serverMetrics + metrics + metricCatalogSections.flatMap(\.metrics)
                )
            } else {
                var next = metrics
                for metric in serverMetrics {
                    if let index = next.firstIndex(where: { $0.id == metric.id }) {
                        next[index] = metric
                    } else {
                        next.insert(metric, at: 0)
                    }
                }
                metrics = dedupedMetrics(next)
            }
        }
        if shouldAnimate {
            withAnimation(.spring(response: 0.26, dampingFraction: 0.88), apply)
        } else {
            apply()
        }
    }

    private func restoreMetricPreferencesFromAvailableCatalog() {
        guard metricPreference.isCustomized else { return }
        let restored = XAgeDataCardPreferences.orderedMetrics(
            for: metricPreference,
            from: serverSync.metricCards + metrics + metricCatalogSections.flatMap(\.metrics)
        )
        guard metricSnapshots(metrics) != metricSnapshots(restored) else { return }
        metrics = restored
    }

    private func persistMetricPreferences() {
        metricPreference = XAgeDataCardPreferences.save(metrics: metrics, accountScope: accountScope)
    }

    private func resetMetrics(for accountScope: String?) {
        activeSheet = nil
        showsMetricManager = false
        pendingMetricScrollID = nil
        isTodayStatusHidden = false
        metricPreference = XAgeDataCardPreferences.load(accountScope: accountScope)
        metrics = XAgeDataCardPreferences.placeholderMetrics(for: metricPreference)
    }

    private func metricSnapshots(_ source: [XAgeMetric]) -> [String] {
        source.map { metric in
            [
                metric.id,
                metric.title,
                metric.value,
                metric.unit,
                metric.time,
                metric.subtitle,
                metric.source ?? "",
                metric.measuredAt ?? "",
                "\(metric.isPlaceholder)",
                "\(metric.isStale)"
            ].joined(separator: "|")
        }
    }

    private func dedupedMetrics(_ source: [XAgeMetric]) -> [XAgeMetric] {
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
}

@MainActor
final class XAgeServerSyncViewModel: ObservableObject {
    @Published private(set) var snapshot = XAgeServerSyncSnapshot.placeholder
    @Published private(set) var metricCards: [XAgeMetric] = []
    @Published private(set) var indicatorCatalogCards: [XAgeMetric] = []
    @Published private(set) var metricTrends: [IndicatorTrend] = []
    @Published private(set) var isLoading = false

    private let api: APIServiceProtocol
    private var refreshGate = XAgeAccountScopedRefreshGate(accountScope: nil)

    init(api: APIServiceProtocol = APIService.shared) {
        self.api = api
    }

    func setAccountScope(_ accountScope: String?) {
        guard refreshGate.switchAccount(to: accountScope) else { return }
        snapshot = refreshGate.accountScope == nil ? .loggedOut : .placeholder
        metricCards = []
        indicatorCatalogCards = []
        metricTrends = []
        isLoading = false
    }

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

private enum XAgeServerSyncFormat {
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

    fileprivate func stats(for category: XAgeDataPanelCategory) -> [XAgePanelStat] {
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
        let isReady = result.confidence >= 35 && features.count >= 3 && hrv != nil && sleep != nil
        return XAgeMetricScore(
            value: value,
            confidence: result.confidence,
            isReady: isReady,
            badgeLabel: isReady ? recoveryBadge(value) : "待评估",
            stateLabel: isReady ? recoveryState(value) : "恢复待评估",
            summary: isReady ? recoverySummary(value) : "恢复评估需要 HRV 和最近一晚睡眠，再配合静息心率、呼吸/血氧/体温或活动负荷。",
            simpleExplanation: "恢复分看的是身体有没有回到稳定状态。HRV 越稳定、睡眠越充分、静息心率和呼吸越平稳，恢复越好；缺少 HRV 或睡眠时不显示分数。",
            explanation: "恢复分先把 HRV/PRV、静息心率、昨夜睡眠、呼吸/血氧/体温稳定性和前日/今日负荷换算为 0-100 子分，再按权重加权。HRV 高、静息心率接近基线、睡眠充足和生理稳定会提高分数，因为这些输入代表自主神经和能量系统回到稳定区间。",
            nextAction: isReady
                ? (value >= 67 ? "今天可以安排挑战任务；算法依据是 HRV、睡眠和稳定性子分都在较高区间。" : "今天把任务强度降一档，优先补水、低强度活动和提前睡眠；这些动作对应恢复分的主要输入。")
                : "先同步 Apple 健康中的 HRV、睡眠、静息心率和呼吸/血氧；连续几天后恢复分会更稳定。",
            fields: scoreFields(result.fields, confidence: result.confidence, isReady: isReady, missing: "HRV + 睡眠 + 至少 1 类稳定性信号"),
            drivers: scoreDrivers(result.drivers, isReady: isReady, title: "补齐恢复输入", note: "恢复分必须同时看到 HRV 和睡眠，否则容易把单项数据误判为整体恢复。"),
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
        let isReady = hasLab && result.confidence >= 35
        return XAgeMetricScore(
            value: value,
            confidence: result.confidence,
            isReady: isReady,
            badgeLabel: isReady ? inflammationBadge(value) : "待评估",
            stateLabel: isReady ? inflammationState(value, proxy: !hasLab) : "炎症待评估",
            summary: isReady ? inflammationSummary(value, proxy: !hasLab) : "炎症评分需要近期 hsCRP、血常规/CBC、NLR 或炎症因子报告。可穿戴数据只作为辅助，不单独给炎症分。",
            simpleExplanation: hasLab
                ? "炎症分先看报告里的炎症锚点，再用体温、心率、HRV、呼吸和血氧补充判断。实验室指标直接反映炎症相关反应，所以权重最高。"
                : "当前没有报告里的炎症锚点，小捷只看到体温、心率、睡眠等辅助信号。这些信号能提示身体负荷，但不能单独说明炎症，所以首页先显示待评估。",
            explanation: hasLab
                ? "炎症分优先把 hsCRP、CBC/NLR、IL-6/TNFα/GlycA 换算为实验室子分，并给这些子分最高权重；再加入体温、静息心率、HRV、呼吸和血氧作为补充。实验室项权重最高，因为它们直接对应炎症相关生物标志物。"
                : "当前没有可信实验室锚点，算法启用“身体小火苗”代理信号：把体温偏移、静息心率、HRV 抑制、呼吸、血氧、睡眠债和活动负荷换算为代理子分并加权。该代理信号只表示算法风险负荷，不是炎症诊断。",
            nextAction: isReady
                ? (value >= 60 ? "先记录体温、症状、睡眠、饮酒和训练；连续偏高时上传最新报告，实验室锚点会替代代理项并重算炎症分。" : "继续同步 Apple 健康和上传报告；新增实验室锚点会替代代理项并提高置信度。")
                : "上传近期血常规、hsCRP 或体检化验报告后再评估炎症分；Apple 健康的体温、心率和睡眠会作为辅助输入。",
            fields: scoreFields((hasLab ? result.fields : [XAgeScoreField(title: "类型", value: "代理信号")] + result.fields), confidence: result.confidence, isReady: isReady, missing: "hsCRP / 血常规 / NLR / 炎症因子报告"),
            drivers: scoreDrivers(result.drivers, isReady: isReady, title: "上传炎症锚点", note: "炎症必须有实验室指标支撑；没有报告时只保留辅助信号，不展示炎症分。"),
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

private enum XAgeDataScrollSpace {
    static let name = "xageDataScroll"
}

private struct XAgeDataScrollOffsetPreferenceKey: PreferenceKey {
    static var defaultValue: CGFloat = 0

    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) {
        value = nextValue()
    }
}

private struct XAgeDataScrollOffsetProbe: View {
    var body: some View {
        GeometryReader { proxy in
            Color.clear
                .preference(
                    key: XAgeDataScrollOffsetPreferenceKey.self,
                    value: proxy.frame(in: .named(XAgeDataScrollSpace.name)).minY
                )
        }
        .frame(height: 1)
        .accessibilityHidden(true)
    }
}

private struct XAgeDataScrollOffsetTracker: ViewModifier {
    let onOffsetChange: (CGFloat) -> Void

    func body(content: Content) -> some View {
        if #available(iOS 18.0, *) {
            content
                .onScrollGeometryChange(for: CGFloat.self) { geometry in
                    geometry.contentOffset.y
                } action: { _, newValue in
                    onOffsetChange(newValue)
                }
        } else {
            content
        }
    }
}

private enum XAgeDataSheet: Identifiable {
    case detail(XAgeDataKind)
    case scoreInfo(XAgeDataKind)
    case metricDetail(XAgeMetric)
    case manualEntry(XAgeMetric)

    var id: String {
        switch self {
        case .detail(let kind): return "detail-\(kind.id)"
        case .scoreInfo(let kind): return "score-info-\(kind.id)"
        case .metricDetail(let metric): return "metric-detail-\(metric.id)"
        case .manualEntry(let metric): return "manual-entry-\(metric.id)"
        }
    }
}

private struct XAgeDataStickyHeader: View {
    let collapseProgress: CGFloat
    let caption: String
    let scores: XAgeCompositeScores
    let showsTodayStatus: Bool
    let onSelectDetail: (XAgeDataKind) -> Void
    let onSelectInfo: (XAgeDataKind) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 12 - 4 * collapseProgress) {
            VStack(alignment: .leading, spacing: 4) {
                Text("今日健康数据")
                    .font(.system(size: 27 - 4 * collapseProgress, weight: .bold))
                    .foregroundStyle(Color(hex: "123E67"))
                    .lineLimit(1)
                Text(caption)
                    .font(.system(size: 13))
                    .foregroundStyle(Color(hex: "5D7B95"))
                    .opacity(Double(1 - collapseProgress))
                    .frame(height: 18 * (1 - collapseProgress), alignment: .top)
                    .clipped()
            }
            .frame(height: 52 - 18 * collapseProgress, alignment: .topLeading)

            XAgeScoreRingPanel(
                collapseProgress: collapseProgress,
                scores: scores,
                onSelectDetail: onSelectDetail,
                onSelectInfo: onSelectInfo
            )

            if showsTodayStatus {
                XAgeScoreSummaryCard(compactProgress: collapseProgress, scores: scores)
                    .transition(.opacity.combined(with: .move(edge: .top)))
            }
        }
    }
}

enum XAgeDataKind: String, Identifiable {
    case pressure = "压力"
    case recovery = "恢复"
    case inflammation = "炎症"

    var id: String { rawValue }

    var tint: Color {
        switch self {
        case .pressure: return Color(hex: "2789D8")
        case .recovery: return Color(hex: "14B887")
        case .inflammation: return Color(hex: "EF9A3D")
        }
    }

    var accessibilityKey: String {
        switch self {
        case .pressure: return "pressure"
        case .recovery: return "recovery"
        case .inflammation: return "inflammation"
        }
    }
}

private struct XAgeScoreRing: View {
    let kind: XAgeDataKind
    let metric: XAgeMetricScore
    var ringSize: CGFloat = 86
    var onSelect: (() -> Void)? = nil
    var onInfo: (() -> Void)? = nil

    var body: some View {
        VStack(spacing: 7) {
            ringControl

            HStack(spacing: 3) {
                Text(kind.rawValue)
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(Color(hex: "43657F"))
                    .lineLimit(1)
                if let onInfo {
                    Button(action: onInfo) {
                        Image(systemName: "info.circle.fill")
                            .font(.system(size: 12, weight: .bold))
                            .foregroundStyle(kind.tint)
                            .frame(width: 44, height: 44)
                            .contentShape(Rectangle())
                    }
                    .padding(.horizontal, -13)
                    .padding(.vertical, -13)
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("xage.data.score.\(kind.accessibilityKey).info")
                    .accessibilityLabel("\(kind.rawValue)原理")
                }
            }
            .frame(height: 18)
        }
        .frame(maxWidth: .infinity)
    }

    @ViewBuilder
    private var ringControl: some View {
        if let onSelect {
            Button(action: onSelect) {
                ringGraphic
            }
            .buttonStyle(.plain)
            .accessibilityLabel("\(kind.rawValue)评分，\(metric.displayValue)")
            .accessibilityHint("打开\(kind.rawValue)详情")
            .accessibilityIdentifier("xage.data.score.\(kind.accessibilityKey)")
        } else {
            ringGraphic
                .accessibilityElement(children: .ignore)
                .accessibilityLabel("\(kind.rawValue)评分，\(metric.displayValue)")
        }
    }

    private var ringGraphic: some View {
        let lineWidth = max(7, ringSize * 0.1)
        return ZStack {
            Circle()
                .trim(from: 0.04, to: 0.9)
                .stroke(Color.white.opacity(0.52), style: StrokeStyle(lineWidth: lineWidth, lineCap: .round))
                .rotationEffect(.degrees(112))
            Circle()
                .trim(from: 0.04, to: 0.04 + 0.86 * CGFloat(metric.isTrustedForDisplay ? metric.value : 0) / 100)
                .stroke(
                    AngularGradient(
                        colors: [kind.tint.opacity(0.35), kind.tint, Color.appAccent, kind.tint],
                        center: .center
                    ),
                    style: StrokeStyle(lineWidth: lineWidth, lineCap: .round)
                )
                .rotationEffect(.degrees(112))
                .opacity(metric.isTrustedForDisplay ? 1 : 0.28)
                .shadow(color: kind.tint.opacity(metric.isTrustedForDisplay ? 0.22 : 0.08), radius: 8, x: 0, y: 3)
            Text(metric.displayValue)
                .font(.system(size: metric.isTrustedForDisplay ? (ringSize >= 80 ? 25 : 22) : 20, weight: .bold))
                .foregroundStyle(Color(hex: "17324E"))
        }
        .frame(width: ringSize, height: ringSize)
        .contentShape(Circle())
    }
}

private struct XAgeScoreRingPanel: View {
    let collapseProgress: CGFloat
    let scores: XAgeCompositeScores
    let onSelectDetail: (XAgeDataKind) -> Void
    let onSelectInfo: (XAgeDataKind) -> Void

    var body: some View {
        let ringSize = 86 - 14 * collapseProgress
        HStack(spacing: 8) {
            XAgeScoreRing(
                kind: .pressure,
                metric: scores.pressure,
                ringSize: ringSize,
                onSelect: { onSelectDetail(.pressure) },
                onInfo: { onSelectInfo(.pressure) }
            )
            XAgeScoreRing(
                kind: .recovery,
                metric: scores.recovery,
                ringSize: ringSize,
                onSelect: { onSelectDetail(.recovery) },
                onInfo: { onSelectInfo(.recovery) }
            )
            XAgeScoreRing(
                kind: .inflammation,
                metric: scores.inflammation,
                ringSize: ringSize,
                onSelect: { onSelectDetail(.inflammation) },
                onInfo: { onSelectInfo(.inflammation) }
            )
        }
        .frame(maxWidth: .infinity)
        .frame(height: 122)
        .background(XAgeGlassCardBackground(cornerRadius: 28))
    }
}

private struct XAgeScoreSummaryCard: View {
    let compactProgress: CGFloat
    let scores: XAgeCompositeScores

    private var badges: [(id: String, title: String, color: Color)] {
        [
            ("pressure", scores.pressure.badgeLabel, Color(hex: "2789D8")),
            ("recovery", scores.recovery.badgeLabel, Color(hex: "14B887")),
            ("inflammation", scores.inflammation.badgeLabel, Color(hex: "EF9A3D"))
        ]
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8 - 2 * compactProgress) {
            HStack(spacing: 8) {
                Text("今日状态")
                    .font(.system(size: 16, weight: .bold))
                    .foregroundStyle(Color(hex: "173F64"))
                    .lineLimit(1)
                Spacer(minLength: 4)
                HStack(spacing: 5) {
                    ForEach(badges, id: \.id) { item in
                        HStack(spacing: 3) {
                            Circle()
                                .fill(item.color)
                                .frame(width: 6, height: 6)
                            Text(item.title)
                                .font(.system(size: 9, weight: .bold))
                                .foregroundStyle(item.color)
                                .lineLimit(1)
                        }
                        .frame(width: 60, height: 22)
                        .background(
                            Capsule()
                                .fill(.white.opacity(0.48))
                                .overlay(Capsule().stroke(.white.opacity(0.76), lineWidth: 1))
                        )
                    }
                }
            }
            Text(scores.todaySummary)
                .font(.system(size: 13))
                .foregroundStyle(Color(hex: "496A83"))
                .lineSpacing(2)
                .lineLimit(compactProgress > 0.7 ? 1 : 2)
                .accessibilityIdentifier("xage.score.trust.notice")
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 12 - 2 * compactProgress)
        .background(XAgeGlassCardBackground(cornerRadius: 24))
    }
}

struct XAgeMetricCatalogSection: Identifiable {
    var id: String { title }
    let title: String
    let icon: String
    let accent: Color
    let metrics: [XAgeMetric]
}

struct XAgeAppleHealthCatalogSemantics: Equatable {
    let source: String
    let value: String
    let time: String
    let subtitle: String

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

private extension XAgeMetric {
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

private struct XAgeAppleHealthSyncCard: View {
    @ObservedObject var viewModel: AppleHealthSyncViewModel
    let compactAuthorization: Bool
    let onSyncAppleHealth: () async -> Void
    @Environment(\.openURL) private var openURL

    @ViewBuilder
    var body: some View {
        if compactAuthorization {
            authorizationBody
        } else {
            managementBody
        }
    }

    private var authorizationBody: some View {
        HStack(spacing: 12) {
            Image(systemName: "heart.text.square.fill")
                .font(.system(size: 18, weight: .bold))
                .foregroundStyle(.white)
                .frame(width: 44, height: 44)
                .background(
                    Circle().fill(
                        LinearGradient(
                            colors: [Color(hex: "238AD6"), Color(hex: "20CDB1")],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        )
                    )
                )

            VStack(alignment: .leading, spacing: 4) {
                Text("Apple 健康")
                    .font(.system(size: 16, weight: .bold))
                    .foregroundStyle(Color(hex: "173F64"))
                Text("授权后可以更好地评估当前的身体指标")
                    .font(.system(size: 12))
                    .foregroundStyle(Color(hex: "6C8194"))
                    .fixedSize(horizontal: false, vertical: true)
                if viewModel.status != .idle {
                    Text(viewModel.statusTitle)
                        .font(.system(size: 11, weight: .bold))
                        .foregroundStyle(Color(hex: "347FB7"))
                        .lineLimit(1)
                }
            }

            Spacer(minLength: 6)

            Button {
                Task { await onSyncAppleHealth() }
            } label: {
                Group {
                    if viewModel.isWorking {
                        ProgressView().tint(.white)
                    } else {
                        Text("授权")
                            .font(.system(size: 14, weight: .bold))
                    }
                }
                .foregroundStyle(.white)
                .frame(width: 62, height: 36)
                .background(
                    Capsule().fill(
                        LinearGradient(
                            colors: [Color(hex: "238AD6"), Color(hex: "20CDB1")],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        )
                    )
                )
            }
            .buttonStyle(.plain)
            .disabled(viewModel.isWorking)
            .accessibilityIdentifier("xage.appleHealth.authorize.button")
        }
        .padding(16)
        .background(XAgeGlassCardBackground(cornerRadius: 24))
    }

    private var managementBody: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 12) {
                ZStack {
                    Circle()
                        .fill(
                            LinearGradient(
                                colors: [Color(hex: "238AD6"), Color(hex: "20CDB1")],
                                startPoint: .topLeading,
                                endPoint: .bottomTrailing
                            )
                        )
                        .shadow(color: Color(hex: "20CDB1").opacity(0.22), radius: 12, x: 0, y: 7)
                    Image(systemName: "heart.text.square.fill")
                        .font(.system(size: 18, weight: .bold))
                        .foregroundStyle(.white)
                }
                .frame(width: 48, height: 48)

                VStack(alignment: .leading, spacing: 4) {
                    Text("Apple 健康同步")
                        .font(.system(size: 17, weight: .bold))
                        .foregroundStyle(Color(hex: "173F64"))
                        .lineLimit(1)
                    Text(viewModel.statusSubtitle)
                        .font(.system(size: 12))
                        .foregroundStyle(Color(hex: "6C8194"))
                        .lineSpacing(2)
                        .fixedSize(horizontal: false, vertical: true)
                }

                Spacer(minLength: 8)

                Button {
                    Task { await onSyncAppleHealth() }
                } label: {
                    Group {
                        if viewModel.isWorking {
                            ProgressView()
                                .tint(.white)
                        } else {
                            Text(viewModel.lastSyncedAt == nil ? "授权" : "同步")
                                .font(.system(size: 14, weight: .bold))
                        }
                    }
                    .foregroundStyle(.white)
                    .frame(width: 62, height: 34)
                    .background(
                        Capsule()
                            .fill(LinearGradient(colors: [Color(hex: "238AD6"), Color(hex: "20CDB1")], startPoint: .topLeading, endPoint: .bottomTrailing))
                    )
                }
                .buttonStyle(.plain)
                .disabled(viewModel.isWorking)
                .accessibilityIdentifier("xage.appleHealth.sync.button")
            }

            if showsSettingsButton {
                Button {
                    guard let settingsURL = URL(string: UIApplication.openSettingsURLString) else { return }
                    openURL(settingsURL)
                } label: {
                    Label("管理或恢复 Apple 健康权限", systemImage: "gearshape.fill")
                        .font(.system(size: 12, weight: .bold))
                        .foregroundStyle(Color(hex: "347FB7"))
                        .frame(maxWidth: .infinity)
                        .frame(minHeight: 34)
                        .background(XAgeCapsuleFill())
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("xage.appleHealth.openSettings")
            }

            XAgeAppleHealthSyncDetailDisclosure(viewModel: viewModel)

            HStack(spacing: 7) {
                XAgeSyncBadge(title: viewModel.statusTitle)
                if let response = viewModel.syncResponse {
                    if response.written > 0 {
                        XAgeSyncBadge(title: String(response.written) + " 项已写入")
                    } else if response.unchangedCount > 0 {
                        XAgeSyncBadge(title: String(response.unchangedCount) + " 项无变化")
                    } else {
                        XAgeSyncBadge(title: String(response.rejectedCount(requested: viewModel.samples.count)) + " 项未接收")
                    }
                } else {
                    XAgeSyncBadge(title: "只读授权")
                }
                XAgeSyncBadge(title: "\(viewModel.samples.count) 项本地数据")
            }
        }
        .padding(16)
        .background(XAgeGlassCardBackground(cornerRadius: 24))
    }

    private var showsSettingsButton: Bool {
        viewModel.shouldOfferHealthSettingsRecovery
    }
}

private struct XAgeAppleHealthSyncDetailDisclosure: View {
    private struct Detail: Identifiable {
        let id: String
        let title: String
        let message: String
    }

    @ObservedObject var viewModel: AppleHealthSyncViewModel

    var body: some View {
        if !details.isEmpty {
            DisclosureGroup {
                VStack(alignment: .leading, spacing: 9) {
                    ForEach(details) { detail in
                        VStack(alignment: .leading, spacing: 2) {
                            Text(detail.title)
                                .font(.system(size: 12, weight: .bold))
                                .foregroundStyle(Color(hex: "365F80"))
                            Text(detail.message)
                                .font(.system(size: 12))
                                .foregroundStyle(Color(hex: "6C8194"))
                                .lineSpacing(2)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                }
                .padding(.top, 8)
            } label: {
                Text("查看全部 " + String(details.count) + " 项读取/写入详情")
                    .font(.system(size: 12, weight: .bold))
                    .foregroundStyle(Color(hex: "347FB7"))
            }
            .tint(Color(hex: "347FB7"))
            .accessibilityIdentifier("xage.appleHealth.sync.details")
        }
    }

    private var details: [Detail] {
        let readDetails = viewModel.readIssues.enumerated().map { index, issue in
            Detail(
                id: "read-" + String(index) + "-" + issue.metricID,
                title: issue.indicatorName,
                message: issue.message
            )
        }
        let writeDetails = (viewModel.syncResponse?.issues ?? []).enumerated().map { index, issue in
            let sample = viewModel.samples.indices.contains(issue.index) ? viewModel.samples[issue.index] : nil
            return Detail(
                id: "write-" + String(index) + "-" + String(issue.index),
                title: sample?.indicatorName ?? "第 " + String(issue.index + 1) + " 项服务器数据",
                message: Self.serverIssueMessage(issue.code)
            )
        }
        return readDetails + writeDetails
    }

    private static func serverIssueMessage(_ code: String) -> String {
        switch code {
        case "invalid_indicator_name":
            return "指标名称无效，服务器未接收。"
        case "invalid_value":
            return "数值无效，服务器未接收。"
        case "future_measured_at":
            return "测量时间晚于当前时间，服务器未接收。"
        case "source_id_conflict":
            return "样本标识与既有指标冲突，服务器为避免覆盖错误数据而拒绝写入。"
        default:
            return "服务器未接收（" + code + "），请稍后重试。"
        }
    }
}

private struct XAgeSyncBadge: View {
    let title: String

    var body: some View {
        Text(title)
            .font(.system(size: 11, weight: .bold))
            .foregroundStyle(Color(hex: "347FB7"))
            .lineLimit(1)
            .minimumScaleFactor(0.78)
            .frame(maxWidth: .infinity)
            .frame(height: 28)
            .background(XAgeCapsuleFill())
    }
}

private struct XAgeMetricCard: View {
    let card: XAgeMetric
    let onOpen: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 8) {
                Circle()
                    .fill(
                        LinearGradient(
                            colors: [card.accent, Color(hex: "20CDB1")],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        )
                    )
                    .frame(width: 14, height: 14)
                Text(card.title)
                    .font(.system(size: 17, weight: .bold))
                    .foregroundStyle(card.accent)
                    .lineLimit(1)
                Spacer(minLength: 8)
                Text(card.time)
                    .font(.system(size: 13, weight: .medium))
                    .foregroundStyle(card.isStale ? Color(hex: "EF9A3D") : Color(hex: "6A8198"))
                    .lineLimit(1)
                Image(systemName: "chevron.right")
                    .font(.system(size: 13, weight: .bold))
                    .foregroundStyle(Color(hex: "A0B1C0"))
                    .frame(width: 14)
            }

            HStack(alignment: .firstTextBaseline, spacing: 4) {
                Text(card.value)
                    .font(.system(size: card.value.count > 4 ? 27 : 31, weight: .bold))
                    .foregroundStyle(card.isPlaceholder ? Color(hex: "6C8194") : (card.isStale ? Color(hex: "496A83") : Color(hex: "101C2F")))
                    .lineLimit(1)
                    .minimumScaleFactor(0.82)
                if !card.unit.isEmpty {
                    Text(card.unit)
                        .font(.system(size: 14, weight: .medium))
                        .foregroundStyle(Color(hex: "70879D"))
                        .lineLimit(1)
                }
                Spacer(minLength: 0)
            }

            Text(card.subtitle)
                .font(.system(size: 12))
                .foregroundStyle(card.isStale ? Color(hex: "9A6A28") : Color(hex: "5D7890"))
                .lineSpacing(2)
                .lineLimit(2)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 16)
        .background(XAgeGlassCardBackground(cornerRadius: 24))
        .contentShape(RoundedRectangle(cornerRadius: 24, style: .continuous))
        .onTapGesture(perform: onOpen)
        .xAgeMetricCardAccessibility(
            sortMode: false,
            label: "\(card.title)，\(card.value) \(card.unit)，\(card.time)",
            hint: "打开指标详情"
        )
    }
}

private struct XAgeMetricLibraryEntryCard: View {
    let availableCount: Int
    let totalCount: Int
    let onManage: () -> Void

    var body: some View {
        Button(action: onManage) {
            HStack(spacing: 14) {
                ZStack {
                    Circle()
                        .fill(
                            LinearGradient(
                                colors: [Color(hex: "238AD6"), Color(hex: "20CDB1")],
                                startPoint: .topLeading,
                                endPoint: .bottomTrailing
                            )
                        )
                        .shadow(color: Color(hex: "20CDB1").opacity(0.24), radius: 12, x: 0, y: 7)
                    Circle()
                        .stroke(.white.opacity(0.58), lineWidth: 1)
                        .frame(width: 34, height: 34)
                    Image(systemName: "list.bullet.rectangle.portrait.fill")
                        .font(.system(size: 17, weight: .bold))
                        .foregroundStyle(.white)
                }
                .frame(width: 50, height: 50)

                VStack(alignment: .leading, spacing: 5) {
                    Text("数据卡片管理")
                        .font(.system(size: 18, weight: .bold))
                        .foregroundStyle(Color(hex: "173F64"))
                        .lineLimit(1)
                        .minimumScaleFactor(0.82)
                    Text("\(totalCount) 项指标 · \(availableCount) 项可添加")
                        .font(.system(size: 12, weight: .medium))
                        .foregroundStyle(Color(hex: "5D7890"))
                        .lineLimit(1)
                        .minimumScaleFactor(0.8)
                }

                Spacer(minLength: 8)

                HStack(spacing: 6) {
                    Text("管理")
                        .font(.system(size: 12, weight: .bold))
                    Image(systemName: "chevron.right")
                        .font(.system(size: 11, weight: .black))
                }
                .foregroundStyle(.white)
                .frame(width: 62, height: 32)
                .background(
                    Capsule()
                        .fill(LinearGradient(colors: [Color(hex: "238AD6"), Color(hex: "20CDB1")], startPoint: .topLeading, endPoint: .bottomTrailing))
                        .overlay(Capsule().stroke(.white.opacity(0.72), lineWidth: 1))
                )
            }
            .padding(.horizontal, 18)
            .frame(height: 94)
            .background(XAgeGlassCardBackground(cornerRadius: 24))
        }
        .buttonStyle(.plain)
        .accessibilityLabel("数据卡片管理，\(totalCount) 项指标，\(availableCount) 项可添加")
        .accessibilityIdentifier("xage.metric.library.manage")
    }
}

private struct XAgeMetricManagerPage: View {
    @Binding var pinnedMetrics: [XAgeMetric]
    let catalogSections: [XAgeMetricCatalogSection]
    @ObservedObject var appleHealthSync: AppleHealthSyncViewModel
    let onSyncAppleHealth: () async -> Void
    let onMetricsChanged: () -> Void
    let onOpenMetric: (XAgeMetric) -> Void
    @State private var searchText = ""
    @FocusState private var searchFocused: Bool

    var body: some View {
        ZStack {
            XAgeLiquidBackground()
                .ignoresSafeArea()

            VStack(spacing: 0) {
                HStack(spacing: 12) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("管理数据页长期关注的指标")
                            .font(.system(size: 17, weight: .bold))
                            .foregroundStyle(Color(hex: "173F64"))
                        Text("置顶、排序、查看解释或添加新指标")
                            .font(.system(size: 13, weight: .medium))
                            .foregroundStyle(Color(hex: "5D7890"))
                    }

                    Spacer(minLength: 8)

                    Text("\(pinnedMetrics.count) 置顶")
                        .font(.system(size: 12, weight: .bold))
                        .foregroundStyle(Color(hex: "347FB7"))
                        .padding(.horizontal, 12)
                        .frame(height: 32)
                        .background(XAgeCapsuleFill())
                }
                .accessibilityIdentifier("xage.metric.manager.page")
                .padding(.horizontal, 24)
                .padding(.top, 16)
                .padding(.bottom, 12)

                XAgeAppleHealthSyncCard(
                    viewModel: appleHealthSync,
                    compactAuthorization: false,
                    onSyncAppleHealth: onSyncAppleHealth
                )
                .padding(.horizontal, 24)
                .padding(.bottom, 12)
                .accessibilityIdentifier("xage.metric.manager.appleHealth")

                XAgeMetricSearchField(
                    text: $searchText,
                    placeholder: "搜索指标",
                    isFocused: $searchFocused
                )
                    .padding(.horizontal, 24)
                    .padding(.bottom, 12)
                    .accessibilityIdentifier("xage.metric.manager.search")

                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 14) {
                        XAgeMetricSectionHeader(
                            title: "置顶",
                            subtitle: pinnedMetrics.isEmpty ? "点击下方加号把指标固定到数据页" : "使用箭头调整顺序，点击减号取消置顶",
                            icon: "pin.fill",
                            accent: Color(hex: "238AD6")
                        )

                        if filteredPinnedMetrics.isEmpty {
                            XAgeMetricEmptyRow(
                                title: pinnedMetrics.isEmpty ? "还没有置顶指标" : "置顶中没有匹配项",
                                subtitle: pinnedMetrics.isEmpty ? "从下面的候选列表选择需要长期关注的项目。" : "换一个关键词再试。"
                            )
                        } else {
                            ForEach(filteredPinnedMetrics) { metric in
                                let actualIndex = pinnedMetrics.firstIndex(where: { $0.id == metric.id }) ?? 0
                                XAgeMetricPinnedManagerRow(
                                    metric: metric,
                                    canMoveUp: actualIndex > 0,
                                    canMoveDown: actualIndex < pinnedMetrics.count - 1,
                                    onOpen: { openMetric(metric) },
                                    onUnpin: { unpin(metric) },
                                    onMoveUp: { moveMetric(from: actualIndex, by: -1) },
                                    onMoveDown: { moveMetric(from: actualIndex, by: 1) }
                                )
                                .id("pinned-\(metric.id)")
                                .accessibilityIdentifier("xage.metric.manager.pinned.\(metric.id)")
                            }
                        }

                        ForEach(filteredCandidateSections) { section in
                            XAgeMetricSectionHeader(
                                title: section.title,
                                subtitle: "\(section.metrics.count) 项可添加",
                                icon: section.icon,
                                accent: section.accent
                            )

                            ForEach(section.metrics) { metric in
                                XAgeMetricLibraryCandidateRow(
                                    metric: metric,
                                    isPinned: false,
                                    onOpen: { openMetric(metric) },
                                    onTogglePinned: { pin(metric) }
                                )
                                .id("manager-candidate-\(metric.id)")
                                .accessibilityIdentifier("xage.metric.manager.candidate.\(metric.id)")
                            }
                        }

                        if filteredCandidateSections.isEmpty && !searchText.isEmpty {
                            XAgeMetricEmptyRow(title: "没有匹配的候选指标", subtitle: "已置顶项目会显示在上方；也可以打开全部指标查看。")
                        }
                    }
                    .padding(.horizontal, 24)
                    .padding(.bottom, 30)
                }
                .scrollIndicators(.hidden)
                .scrollDismissesKeyboard(.interactively)
                .accessibilityIdentifier("xage.metric.manager.scroll")
            }
        }
        .navigationTitle("数据卡片管理")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar(.visible, for: .navigationBar)
        .toolbarBackground(.hidden, for: .navigationBar)
    }

    private var pinnedIDs: Set<String> {
        Set(pinnedMetrics.map(\.id))
    }

    private var normalizedSearchText: String {
        searchText.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    }

    private var filteredPinnedMetrics: [XAgeMetric] {
        filter(pinnedMetrics)
    }

    private var filteredCandidateSections: [XAgeMetricCatalogSection] {
        catalogSections.compactMap { section in
            let metrics = filter(section.metrics.filter { !pinnedIDs.contains($0.id) })
            guard !metrics.isEmpty else { return nil }
            return XAgeMetricCatalogSection(title: section.title, icon: section.icon, accent: section.accent, metrics: metrics)
        }
    }

    private func filter(_ metrics: [XAgeMetric]) -> [XAgeMetric] {
        guard !normalizedSearchText.isEmpty else { return metrics }
        return metrics.filter { metric in
            [
                metric.title,
                metric.subtitle,
                metric.time,
                metric.unit
            ]
            .joined(separator: " ")
            .lowercased()
            .contains(normalizedSearchText)
        }
    }

    private func pin(_ metric: XAgeMetric) {
        guard !pinnedMetrics.contains(where: { $0.id == metric.id }) else { return }
        withAnimation(.spring(response: 0.24, dampingFraction: 0.88)) {
            pinnedMetrics.append(metric)
        }
        onMetricsChanged()
    }

    private func unpin(_ metric: XAgeMetric) {
        guard let index = pinnedMetrics.firstIndex(where: { $0.id == metric.id }) else { return }
        withAnimation(.spring(response: 0.24, dampingFraction: 0.88)) {
            _ = pinnedMetrics.remove(at: index)
        }
        onMetricsChanged()
    }

    private func moveMetric(from index: Int, by delta: Int) {
        let target = index + delta
        guard pinnedMetrics.indices.contains(index), pinnedMetrics.indices.contains(target) else { return }
        withAnimation(.spring(response: 0.24, dampingFraction: 0.88)) {
            pinnedMetrics.swapAt(index, target)
        }
        onMetricsChanged()
    }

    private func openMetric(_ metric: XAgeMetric) {
        searchFocused = false
        XAgeKeyboard.dismiss()
        onOpenMetric(metric)
    }
}

private struct XAgeMetricSheetHeader: View {
    let title: String
    let subtitle: String
    let countText: String
    let closeIcon: String
    let onClose: () -> Void

    var body: some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 4) {
                Text(title)
                    .font(.system(size: 27, weight: .bold))
                    .foregroundStyle(Color(hex: "123E67"))
                    .lineLimit(1)
                Text(subtitle)
                    .font(.system(size: 13, weight: .medium))
                    .foregroundStyle(Color(hex: "5D7890"))
                    .lineLimit(1)
                    .minimumScaleFactor(0.8)
            }

            Spacer(minLength: 8)

            Text(countText)
                .font(.system(size: 12, weight: .bold))
                .foregroundStyle(Color(hex: "347FB7"))
                .frame(minWidth: 58)
                .padding(.horizontal, 10)
                .frame(height: 32)
                .background(XAgeCapsuleFill())

            Button(action: onClose) {
                Image(systemName: closeIcon)
                    .font(.system(size: 13, weight: .bold))
                    .foregroundStyle(Color(hex: "1268BD"))
                    .frame(width: 34, height: 34)
                    .background(XAgeCapsuleFill())
            }
            .frame(width: 44, height: 44)
            .contentShape(Rectangle())
            .buttonStyle(.plain)
            .accessibilityLabel(closeIcon == "checkmark" ? "完成" : "关闭")
        }
    }
}

private struct XAgeMetricSearchField: View {
    @Binding var text: String
    let placeholder: String
    var isFocused: FocusState<Bool>.Binding

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: "magnifyingglass")
                .font(.system(size: 14, weight: .bold))
                .foregroundStyle(Color(hex: "6C8194"))
            TextField(placeholder, text: $text)
                .font(.system(size: 14, weight: .semibold))
                .foregroundStyle(Color(hex: "173F64"))
                .textFieldStyle(.plain)
                .submitLabel(.search)
                .focused(isFocused)
                .onSubmit {
                    isFocused.wrappedValue = false
                }
            if !text.isEmpty {
                Button {
                    text = ""
                } label: {
                    Image(systemName: "xmark.circle.fill")
                        .font(.system(size: 14, weight: .bold))
                        .foregroundStyle(Color(hex: "8AA1B5"))
                        .frame(width: 44, height: 44)
                        .contentShape(Rectangle())
                }
                .padding(.horizontal, -15)
                .buttonStyle(.plain)
                .accessibilityLabel("清除搜索")
            }
        }
        .padding(.horizontal, 14)
        .frame(height: 44)
        .background(XAgeCapsuleFill())
    }
}

private struct XAgeMetricSectionHeader: View {
    let title: String
    let subtitle: String
    let icon: String
    let accent: Color

    var body: some View {
        HStack(spacing: 9) {
            Image(systemName: icon)
                .font(.system(size: 12, weight: .bold))
                .foregroundStyle(.white)
                .frame(width: 26, height: 26)
                .background(Circle().fill(accent))
            VStack(alignment: .leading, spacing: 1) {
                Text(title)
                    .font(.system(size: 15, weight: .bold))
                    .foregroundStyle(Color(hex: "173F64"))
                    .lineLimit(1)
                Text(subtitle)
                    .font(.system(size: 11, weight: .medium))
                    .foregroundStyle(Color(hex: "6C8194"))
                    .lineLimit(1)
            }
            Spacer(minLength: 0)
        }
        .padding(.top, 4)
    }
}

private struct XAgeMetricPinnedManagerRow: View {
    let metric: XAgeMetric
    let canMoveUp: Bool
    let canMoveDown: Bool
    let onOpen: () -> Void
    let onUnpin: () -> Void
    let onMoveUp: () -> Void
    let onMoveDown: () -> Void

    var body: some View {
        HStack(spacing: 12) {
            Button(action: onUnpin) {
                Image(systemName: "minus")
                    .font(.system(size: 12, weight: .black))
                    .foregroundStyle(.white)
                    .frame(width: 44, height: 44)
                    .background {
                        Circle()
                            .fill(Color(hex: "A9B8C5").opacity(0.82))
                            .overlay(Circle().stroke(.white.opacity(0.72), lineWidth: 1))
                            .frame(width: 28, height: 28)
                    }
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel("取消置顶\(metric.title)")
            .accessibilityIdentifier("xage.metric.manager.unpin.\(metric.id)")

            Button(action: onOpen) {
                HStack(spacing: 10) {
                    XAgeMetricRoundIcon(metric: metric)
                    VStack(alignment: .leading, spacing: 4) {
                        Text(metric.title)
                            .font(.system(size: 16, weight: .bold))
                            .foregroundStyle(Color(hex: "173F64"))
                            .lineLimit(1)
                        Text(metric.subtitle)
                            .font(.system(size: 12))
                            .foregroundStyle(Color(hex: "6C8194"))
                            .lineLimit(1)
                            .minimumScaleFactor(0.82)
                    }
                    Spacer(minLength: 4)
                    Image(systemName: "info.circle")
                        .font(.system(size: 16, weight: .bold))
                        .foregroundStyle(metric.accent)
                        .frame(width: 24, height: 44)
                }
                .contentShape(Rectangle())
            }
            .frame(maxWidth: .infinity)
            .buttonStyle(.plain)
            .accessibilityLabel("\(metric.title)解释")
            .accessibilityIdentifier("xage.metric.manager.detail.\(metric.id)")

            HStack(spacing: 2) {
                Button(action: onMoveUp) {
                    Image(systemName: "chevron.up")
                        .font(.system(size: 11, weight: .black))
                        .foregroundStyle(canMoveUp ? Color(hex: "347FB7") : Color(hex: "A9B8C5"))
                        .frame(width: 44, height: 44)
                        .background {
                            Circle()
                                .fill(.white.opacity(0.46))
                                .frame(width: 32, height: 32)
                        }
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .disabled(!canMoveUp)
                .accessibilityLabel("上移\(metric.title)")
                .accessibilityIdentifier("xage.metric.manager.moveUp.\(metric.id)")

                Button(action: onMoveDown) {
                    Image(systemName: "chevron.down")
                        .font(.system(size: 11, weight: .black))
                        .foregroundStyle(canMoveDown ? Color(hex: "347FB7") : Color(hex: "A9B8C5"))
                        .frame(width: 44, height: 44)
                        .background {
                            Circle()
                                .fill(.white.opacity(0.46))
                                .frame(width: 32, height: 32)
                        }
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .disabled(!canMoveDown)
                .accessibilityLabel("下移\(metric.title)")
                .accessibilityIdentifier("xage.metric.manager.moveDown.\(metric.id)")
            }
        }
        .padding(.horizontal, 10)
        .frame(minHeight: 76)
        .background(XAgeGlassCardBackground(cornerRadius: 22))
        .accessibilityElement(children: .contain)
    }
}

private struct XAgeMetricLibraryCandidateRow: View {
    let metric: XAgeMetric
    let isPinned: Bool
    let onOpen: () -> Void
    let onTogglePinned: () -> Void

    var body: some View {
        HStack(spacing: 12) {
            Button(action: onTogglePinned) {
                Image(systemName: isPinned ? "checkmark" : "pin.fill")
                    .font(.system(size: 13, weight: .bold))
                    .foregroundStyle(isPinned ? .white : metric.accent)
                    .frame(width: 44, height: 44)
                    .background {
                        Circle()
                            .fill(isPinned ? AnyShapeStyle(LinearGradient(colors: [Color(hex: "238AD6"), Color(hex: "20CDB1")], startPoint: .topLeading, endPoint: .bottomTrailing)) : AnyShapeStyle(.white.opacity(0.56)))
                            .overlay(Circle().stroke(.white.opacity(0.78), lineWidth: 1))
                            .frame(width: 30, height: 30)
                    }
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel(isPinned ? "取消置顶\(metric.title)" : "置顶\(metric.title)")
            .accessibilityIdentifier(isPinned ? "xage.metric.manager.unpin.\(metric.id)" : "xage.metric.manager.pin.\(metric.id)")

            Button(action: onOpen) {
                HStack(spacing: 10) {
                    XAgeMetricRoundIcon(metric: metric)
                    VStack(alignment: .leading, spacing: 4) {
                        HStack(alignment: .firstTextBaseline, spacing: 6) {
                            Text(metric.title)
                                .font(.system(size: 16, weight: .bold))
                                .foregroundStyle(Color(hex: "173F64"))
                                .lineLimit(1)
                            Text(metric.time)
                                .font(.system(size: 11, weight: .bold))
                                .foregroundStyle(metric.accent)
                                .lineLimit(1)
                        }
                        Text(metric.subtitle)
                            .font(.system(size: 12))
                            .foregroundStyle(Color(hex: "6C8194"))
                            .lineLimit(1)
                            .minimumScaleFactor(0.82)
                    }
                    Spacer(minLength: 4)
                    Image(systemName: "info.circle")
                        .font(.system(size: 16, weight: .bold))
                        .foregroundStyle(metric.accent)
                        .frame(width: 24, height: 44)
                }
                .contentShape(Rectangle())
            }
            .frame(maxWidth: .infinity)
            .buttonStyle(.plain)
            .accessibilityLabel("\(metric.title)详情")
            .accessibilityIdentifier("xage.metric.manager.detail.\(metric.id)")
        }
        .padding(.horizontal, 10)
        .frame(minHeight: 72)
        .background(XAgeGlassCardBackground(cornerRadius: 22))
        .accessibilityElement(children: .contain)
    }
}

private struct XAgeMetricRoundIcon: View {
    let metric: XAgeMetric

    var body: some View {
        ZStack {
            Circle()
                .fill(
                    LinearGradient(
                        colors: [metric.accent, Color(hex: "20CDB1")],
                        startPoint: .topLeading,
                        endPoint: .bottomTrailing
                    )
                )
                .shadow(color: metric.accent.opacity(0.18), radius: 10, x: 0, y: 5)
            Image(systemName: metric.libraryIconName)
                .font(.system(size: 15, weight: .bold))
                .foregroundStyle(.white)
        }
        .frame(width: 42, height: 42)
    }
}

private struct XAgeMetricEmptyRow: View {
    let title: String
    let subtitle: String

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title)
                .font(.system(size: 17, weight: .bold))
                .foregroundStyle(Color(hex: "173F64"))
            Text(subtitle)
                .font(.system(size: 13, weight: .medium))
                .foregroundStyle(Color(hex: "6C8194"))
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(XAgeGlassCardBackground(cornerRadius: 22))
    }
}

private struct XAgeMetricDetailSheet: View {
    let metric: XAgeMetric
    let trend: IndicatorTrend?
    let onManualRecord: () -> Void
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        ZStack {
            XAgeLiquidBackground()
                .ignoresSafeArea()

            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    HStack(spacing: 12) {
                        ZStack {
                            Circle()
                                .fill(LinearGradient(colors: [metric.accent, Color(hex: "20CDB1")], startPoint: .topLeading, endPoint: .bottomTrailing))
                            Image(systemName: iconName)
                                .font(.system(size: 18, weight: .bold))
                                .foregroundStyle(.white)
                        }
                        .frame(width: 48, height: 48)

                        VStack(alignment: .leading, spacing: 4) {
                            Text(metric.title)
                                .font(.system(size: 24, weight: .bold))
                                .foregroundStyle(Color(hex: "173F64"))
                                .lineLimit(1)
                            Text(statusTitle)
                                .font(.system(size: 12, weight: .bold))
                                .foregroundStyle(statusColor)
                                .padding(.horizontal, 10)
                                .padding(.vertical, 4)
                                .background(XAgeCapsuleFill())
                        }

                        Spacer()

                        Button {
                            dismiss()
                        } label: {
                            Image(systemName: "xmark")
                                .font(.system(size: 14, weight: .bold))
                                .foregroundStyle(Color(hex: "2A79BB"))
                                .frame(width: 36, height: 36)
                                .background(XAgeCapsuleFill())
                        }
                        .frame(width: 44, height: 44)
                        .contentShape(Rectangle())
                        .buttonStyle(.plain)
                        .accessibilityLabel("关闭\(metric.title)详情")
                    }

                    VStack(alignment: .leading, spacing: 10) {
                        HStack(alignment: .firstTextBaseline, spacing: 5) {
                            Text(metric.value)
                                .font(.system(size: metric.value.count > 4 ? 32 : 40, weight: .bold))
                                .foregroundStyle(metric.isPlaceholder ? Color(hex: "6C8194") : Color(hex: "101C2F"))
                                .lineLimit(1)
                                .minimumScaleFactor(0.72)
                            if !metric.unit.isEmpty {
                                Text(metric.unit)
                                    .font(.system(size: 15, weight: .semibold))
                                    .foregroundStyle(Color(hex: "70879D"))
                            }
                            Spacer()
                        }
                        Text(metric.subtitle)
                            .font(.system(size: 14))
                            .foregroundStyle(Color(hex: "496A83"))
                            .lineSpacing(3)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    .padding(18)
                    .background(XAgeGlassCardBackground(cornerRadius: 26))

                    VStack(alignment: .leading, spacing: 10) {
                        XAgeMetricDetailRow(title: "数据来源", value: sourceLabel)
                        XAgeMetricDetailRow(title: "更新时间", value: updateLabel)
                        XAgeMetricDetailRow(title: "当前状态", value: statusTitle)
                    }
                    .padding(16)
                    .background(XAgeGlassCardBackground(cornerRadius: 24))

                    XAgeMetricTrendView(
                        trend: trend,
                        fallbackUnit: metric.unit,
                        accent: metric.accent
                    )
                    .accessibilityIdentifier("xage.metric.trend")

                    Button {
                        onManualRecord()
                    } label: {
                        HStack(spacing: 10) {
                            Image(systemName: "square.and.pencil")
                                .font(.system(size: 15, weight: .bold))
                            VStack(alignment: .leading, spacing: 2) {
                                Text("手动记录")
                                    .font(.system(size: 15, weight: .bold))
                                Text("录入后进入趋势，并刷新主界面")
                                    .font(.system(size: 11, weight: .medium))
                                    .opacity(0.86)
                            }
                            Spacer()
                            Image(systemName: "chevron.right")
                                .font(.system(size: 12, weight: .bold))
                        }
                        .foregroundStyle(.white)
                        .padding(.horizontal, 16)
                        .frame(height: 54)
                        .background(
                            Capsule()
                                .fill(LinearGradient(colors: [metric.accent, Color(hex: "20CDB1")], startPoint: .topLeading, endPoint: .bottomTrailing))
                                .overlay(Capsule().stroke(.white.opacity(0.68), lineWidth: 1))
                        )
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("xage.metric.manualEntry")
                    .accessibilityLabel("手动记录\(metric.title)")

                    Text(detailExplanation)
                        .font(.system(size: 13, weight: .medium))
                        .foregroundStyle(statusColor)
                        .lineSpacing(3)
                        .fixedSize(horizontal: false, vertical: true)
                        .padding(14)
                        .background(XAgeCapsuleFill())
                }
                .padding(24)
            }
            .scrollIndicators(.hidden)
        }
    }

    private var statusTitle: String {
        if metric.source == "other_source_catalog" { return "暂不支持自动同步" }
        if metric.isPlaceholder { return metric.time.contains("上传") ? "待上传" : "暂无数据" }
        if metric.source == "server_indicator_catalog" { return "已入库" }
        if metric.isStale { return "需更新" }
        return "已同步"
    }

    private var statusColor: Color {
        if metric.isPlaceholder { return Color(hex: "6C8194") }
        if metric.isStale { return Color(hex: "EF9A3D") }
        return metric.accent
    }

    private var sourceLabel: String {
        switch (metric.source ?? "").lowercased() {
        case "apple_health": return "Apple 健康"
        case "apple_health_catalog": return "Apple 健康可同步"
        case "other_source_catalog": return "其他来源"
        case "manual": return "手动记录"
        case "device": return "设备同步"
        case "cgm": return "CGM"
        case "document": return "报告趋势"
        case "server_catalog": return "服务器指标库"
        case "server_indicator_catalog": return "服务器已入库指标"
        default: return metric.isPlaceholder ? "暂无" : "服务端趋势"
        }
    }

    private var updateLabel: String {
        if let measuredAt = metric.measuredAt {
            return XAgeServerSyncFormat.shortDate(measuredAt)
        }
        return metric.time
    }

    private var detailExplanation: String {
        if metric.isPlaceholder {
            if metric.source == "apple_health_catalog" {
                return "这是小捷当前已实现的 Apple 健康读取项目。完成授权后可手动同步；只有同一账号明确同步过，App 才会在回到前台时刷新。"
            }
            if metric.source == "other_source_catalog" {
                return "当前版本不会从 Apple 健康自动读取这个指标，也不会在授权后承诺自动更新。你仍可手动记录、上传报告，或等待后续接入其他数据来源。"
            }
            if metric.source == "server_catalog" {
                return "这是服务器指标库候选项。上传报告或手动记录后，小捷会把该指标写入趋势，并用最新有效值更新数据页。"
            }
            return "当前没有这个指标的有效数据；同步 Apple 健康、手动记录或上传报告后，主界面会用真实数值替换占位。"
        }
        if metric.source == "server_indicator_catalog" {
            return "这个指标已经存在服务器历史记录。置顶后先展示历史点数量；上传报告、Apple 健康同步或手动记录产生新值后，数据页会按最新测量时间更新。"
        }
        if metric.isStale {
            return "这条数据已超过当前指标的时效窗口，保留为历史参考，不作为最新状态展示。"
        }
        return "这条数据来自\(sourceLabel)，按测量时间进入趋势，并用于当前数据页展示。"
    }

    private var iconName: String {
        metric.libraryIconName
    }
}

private enum XAgeManualMetricField: Int, CaseIterable {
    case indicator
    case value
    case unit
    case notes
}

private struct XAgeManualMetricEntrySheet: View {
    let metric: XAgeMetric
    let onCancel: () -> Void
    let onSaved: () -> Void
    @StateObject private var vm = ManualIndicatorViewModel()
    @State private var indicatorName: String
    @State private var valueText = ""
    @State private var unitText: String
    @State private var measuredAt = Date()
    @State private var initialMeasuredAt = Date()
    @State private var notes = ""
    @State private var showDiscardConfirmation = false
    @FocusState private var focusedField: XAgeManualMetricField?

    init(metric: XAgeMetric, onCancel: @escaping () -> Void, onSaved: @escaping () -> Void) {
        let now = Date()
        self.metric = metric
        self.onCancel = onCancel
        self.onSaved = onSaved
        _indicatorName = State(initialValue: metric.title)
        _unitText = State(initialValue: metric.unit)
        _measuredAt = State(initialValue: now)
        _initialMeasuredAt = State(initialValue: now)
    }

    var body: some View {
        NavigationStack {
            ZStack {
                XAgeLiquidBackground()
                    .ignoresSafeArea()

                ScrollView {
                    VStack(alignment: .leading, spacing: 16) {
                    HStack(spacing: 12) {
                        Button {
                            requestCancel()
                        } label: {
                            Image(systemName: "chevron.left")
                                .font(.system(size: 16, weight: .bold))
                                .foregroundStyle(Color(hex: "2A79BB"))
                                .frame(width: 44, height: 44)
                                .background {
                                    XAgeCapsuleFill()
                                        .frame(width: 36, height: 36)
                                }
                                .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        .disabled(vm.saving)
                        .accessibilityLabel("返回\(metric.title)详情")
                        .accessibilityIdentifier("xage.metric.manualEntry.back")

                        ZStack {
                            Circle()
                                .fill(LinearGradient(colors: [metric.accent, Color(hex: "20CDB1")], startPoint: .topLeading, endPoint: .bottomTrailing))
                            Image(systemName: "square.and.pencil")
                                .font(.system(size: 18, weight: .bold))
                                .foregroundStyle(.white)
                        }
                        .frame(width: 48, height: 48)

                        VStack(alignment: .leading, spacing: 3) {
                            Text("手动记录")
                                .font(.system(size: 24, weight: .bold))
                                .foregroundStyle(Color(hex: "173F64"))
                            Text("保存后进入用户端趋势")
                                .font(.system(size: 13, weight: .medium))
                                .foregroundStyle(Color(hex: "5D7890"))
                        }

                        Spacer()
                    }

                    VStack(alignment: .leading, spacing: 12) {
                        XAgeManualMetricTextField(
                            title: "指标",
                            placeholder: "指标名称",
                            text: $indicatorName,
                            field: .indicator,
                            focusedField: $focusedField
                        )
                        .accessibilityIdentifier("xage.metric.manualEntry.indicator")
                        XAgeManualMetricTextField(
                            title: "数值",
                            placeholder: "例如 120",
                            text: $valueText,
                            keyboardType: .decimalPad,
                            field: .value,
                            focusedField: $focusedField
                        )
                        .accessibilityIdentifier("xage.metric.manualEntry.value")
                        XAgeManualMetricTextField(
                            title: "单位",
                            placeholder: "可选",
                            text: $unitText,
                            field: .unit,
                            focusedField: $focusedField
                        )
                        .accessibilityIdentifier("xage.metric.manualEntry.unit")
                        DatePicker("测量时间", selection: $measuredAt, in: ...Date(), displayedComponents: [.date, .hourAndMinute])
                            .font(.system(size: 14, weight: .bold))
                            .foregroundStyle(Color(hex: "173F64"))
                            .padding(.horizontal, 14)
                            .frame(height: 52)
                            .background(XAgeCapsuleFill())
                            .simultaneousGesture(TapGesture().onEnded {
                                focusedField = nil
                            })
                        XAgeManualMetricTextField(
                            title: "备注",
                            placeholder: "可选，可填写测量场景或说明",
                            text: $notes,
                            field: .notes,
                            focusedField: $focusedField,
                            isMultiline: true
                        )
                        .accessibilityIdentifier("xage.metric.manualEntry.notes")
                    }
                    .padding(16)
                    .background(XAgeGlassCardBackground(cornerRadius: 24))

                    Text("手动记录会标记为“手动记录”来源。Apple 健康同日同步到同一指标时，会按来源和测量时间合并，主界面始终显示当前最有效的数据。")
                        .font(.system(size: 13))
                        .foregroundStyle(Color(hex: "496A83"))
                        .lineSpacing(3)
                        .fixedSize(horizontal: false, vertical: true)
                        .padding(14)
                        .background(XAgeCapsuleFill())

                    Button {
                        focusedField = nil
                        XAgeKeyboard.dismiss()
                        Task { await save() }
                    } label: {
                        HStack(spacing: 8) {
                            if vm.saving {
                                ProgressView()
                                    .tint(.white)
                            }
                            Text(vm.saving ? "保存中" : "保存记录")
                                .font(.system(size: 15, weight: .bold))
                        }
                        .foregroundStyle(.white)
                        .frame(maxWidth: .infinity)
                        .frame(height: 46)
                        .background(
                            Capsule()
                                .fill(LinearGradient(colors: [metric.accent, Color(hex: "20CDB1")], startPoint: .topLeading, endPoint: .bottomTrailing))
                        )
                    }
                    .buttonStyle(.plain)
                    .disabled(!canSave || vm.saving)
                    .opacity(!canSave || vm.saving ? 0.55 : 1)
                    .accessibilityIdentifier("xage.metric.manualEntry.save")
                }
                    .padding(24)
                }
                .scrollIndicators(.hidden)
                .scrollDismissesKeyboard(.interactively)
            }
            .toolbar(.hidden, for: .navigationBar)
        }
        .interactiveDismissDisabled(hasUnsavedChanges || vm.saving)
        .presentationDragIndicator(hasUnsavedChanges || vm.saving ? .hidden : .visible)
        .safeAreaInset(edge: .bottom, spacing: 0) {
            if focusedField != nil {
                HStack(spacing: 16) {
                    Button {
                        moveFocus(by: -1)
                    } label: {
                        Text("上一项")
                            .frame(minWidth: 44, minHeight: 44)
                            .contentShape(Rectangle())
                    }
                    .disabled(previousField == nil)
                    .accessibilityIdentifier("xage.metric.manualEntry.keyboard.previous")

                    Button {
                        moveFocus(by: 1)
                    } label: {
                        Text("下一项")
                            .frame(minWidth: 44, minHeight: 44)
                            .contentShape(Rectangle())
                    }
                    .disabled(nextField == nil)
                    .accessibilityIdentifier("xage.metric.manualEntry.keyboard.next")

                    Spacer()

                    Button {
                        focusedField = nil
                        XAgeKeyboard.dismiss()
                    } label: {
                        Text("完成")
                            .frame(minWidth: 44, minHeight: 44)
                            .contentShape(Rectangle())
                    }
                    .accessibilityIdentifier("xage.metric.manualEntry.keyboard.done")
                }
                .font(.system(size: 15, weight: .semibold))
                .foregroundStyle(Color(hex: "1268BD"))
                .padding(.horizontal, 18)
                .frame(height: 52)
                .frame(maxWidth: .infinity)
                .background(.ultraThinMaterial)
                .overlay(alignment: .top) {
                    Divider().opacity(0.35)
                }
            }
        }
        .onChange(of: vm.savedOk) { _, saved in
            guard saved else { return }
            onSaved()
        }
        .alert("保存失败", isPresented: Binding(
            get: { vm.errorMessage != nil },
            set: { if !$0 { vm.errorMessage = nil } }
        )) {
            Button("知道了", role: .cancel) {}
        } message: {
            Text(vm.errorMessage ?? "")
        }
        .alert("放弃本次记录？", isPresented: $showDiscardConfirmation) {
            Button("继续编辑", role: .cancel) {}
            Button("放弃修改", role: .destructive) {
                focusedField = nil
                XAgeKeyboard.dismiss()
                onCancel()
            }
        } message: {
            Text("已填写的内容不会保存。")
        }
    }

    private var canSave: Bool {
        !indicatorName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && parsedValue != nil
    }

    private var parsedValue: Double? {
        Double(valueText.replacingOccurrences(of: "，", with: ".").trimmingCharacters(in: .whitespacesAndNewlines))
    }

    private var hasUnsavedChanges: Bool {
        indicatorName != metric.title ||
        !valueText.isEmpty ||
        unitText != metric.unit ||
        !notes.isEmpty ||
        abs(measuredAt.timeIntervalSince(initialMeasuredAt)) > 1
    }

    private var previousField: XAgeManualMetricField? {
        guard let focusedField,
              let index = XAgeManualMetricField.allCases.firstIndex(of: focusedField),
              index > XAgeManualMetricField.allCases.startIndex
        else { return nil }
        return XAgeManualMetricField.allCases[index - 1]
    }

    private var nextField: XAgeManualMetricField? {
        guard let focusedField,
              let index = XAgeManualMetricField.allCases.firstIndex(of: focusedField),
              index < XAgeManualMetricField.allCases.index(before: XAgeManualMetricField.allCases.endIndex)
        else { return nil }
        return XAgeManualMetricField.allCases[index + 1]
    }

    private func moveFocus(by offset: Int) {
        focusedField = offset < 0 ? previousField : nextField
    }

    private func requestCancel() {
        focusedField = nil
        XAgeKeyboard.dismiss()
        if hasUnsavedChanges {
            showDiscardConfirmation = true
        } else {
            onCancel()
        }
    }

    private func save() async {
        guard let value = parsedValue else { return }
        let trimmedUnit = unitText.trimmingCharacters(in: .whitespacesAndNewlines)
        let trimmedNotes = notes.trimmingCharacters(in: .whitespacesAndNewlines)
        await vm.submit(
            indicatorName: indicatorName.trimmingCharacters(in: .whitespacesAndNewlines),
            value: value,
            unit: trimmedUnit.isEmpty ? nil : trimmedUnit,
            measuredAt: measuredAt,
            notes: trimmedNotes.isEmpty ? nil : trimmedNotes
        )
    }
}

private struct XAgeManualMetricTextField: View {
    let title: String
    let placeholder: String
    @Binding var text: String
    var keyboardType: UIKeyboardType = .default
    let field: XAgeManualMetricField
    var focusedField: FocusState<XAgeManualMetricField?>.Binding
    var isMultiline = false

    var body: some View {
        HStack(alignment: isMultiline ? .top : .center, spacing: 12) {
            Text(title)
                .font(.system(size: 13, weight: .bold))
                .foregroundStyle(Color(hex: "5D7890"))
                .frame(width: 54, alignment: .leading)
                .padding(.top, isMultiline ? 12 : 0)
            TextField(placeholder, text: $text, axis: isMultiline ? .vertical : .horizontal)
                .font(.system(size: 14, weight: .bold))
                .foregroundStyle(Color(hex: "173F64"))
                .keyboardType(keyboardType)
                .textFieldStyle(.plain)
                .lineLimit(isMultiline ? 2...5 : 1...1)
                .multilineTextAlignment(isMultiline ? .leading : .trailing)
                .padding(.vertical, isMultiline ? 10 : 0)
                .focused(focusedField, equals: field)
                .submitLabel(field == .notes ? .done : .next)
                .onSubmit {
                    if let index = XAgeManualMetricField.allCases.firstIndex(of: field),
                       index < XAgeManualMetricField.allCases.index(before: XAgeManualMetricField.allCases.endIndex) {
                        focusedField.wrappedValue = XAgeManualMetricField.allCases[index + 1]
                    } else {
                        focusedField.wrappedValue = nil
                    }
                }
        }
        .padding(.horizontal, 14)
        .frame(minHeight: 52)
        .background {
            if isMultiline {
                XAgeGlassCardBackground(cornerRadius: 22)
            } else {
                XAgeCapsuleFill()
            }
        }
    }
}

struct XAgeMetricDetailRow: View {
    let title: String
    let value: String

    var body: some View {
        HStack {
            Text(title)
                .font(.system(size: 13, weight: .medium))
                .foregroundStyle(Color(hex: "5D7890"))
            Spacer(minLength: 12)
            Text(value)
                .font(.system(size: 13, weight: .bold))
                .foregroundStyle(Color(hex: "17324E"))
                .lineLimit(1)
                .minimumScaleFactor(0.8)
        }
        .padding(11)
        .background(XAgeCapsuleFill())
    }
}

enum XAgeDataPanelCategory: String, CaseIterable, Identifiable, Hashable {
    case reports = "报告"
    case daily = "日常"
    case medical = "就医助手"
    case profile = "画像"

    var id: String {
        switch self {
        case .reports: return "reports"
        case .daily: return "daily"
        case .medical: return "medical"
        case .profile: return "profile"
        }
    }

    var headline: String {
        switch self {
        case .reports: return "报告管理"
        case .daily: return "日常同步"
        case .medical: return "就医助手"
        case .profile: return "健康画像"
        }
    }

    var subtitle: String {
        switch self {
        case .reports: return "体检、化验、影像"
        case .daily: return "睡眠、步数、HRV"
        case .medical: return "上传、列表、详情"
        case .profile: return "基础、慢病、过敏"
        }
    }

    var actionTitle: String {
        switch self {
        case .reports: return "上传"
        case .daily: return "查看"
        case .medical: return "查看"
        case .profile: return "完善"
        }
    }

    var iconName: String {
        switch self {
        case .reports: return "doc.text.fill"
        case .daily: return "waveform.path.ecg"
        case .medical: return "cross.case.fill"
        case .profile: return "person.text.rectangle.fill"
        }
    }

    var gradient: [Color] {
        switch self {
        case .reports: return [Color(hex: "238AD6"), Color(hex: "20CDB1")]
        case .daily: return [Color(hex: "18B7D6"), Color(hex: "34D6A6")]
        case .medical: return [Color(hex: "4E8FE9"), Color(hex: "7BD5F1")]
        case .profile: return [Color(hex: "2A79C7"), Color(hex: "6EE4C6")]
        }
    }

    var detailSummary: String {
        switch self {
        case .reports: return "上传体检、化验和影像资料后，先检查识别候选并确认整份报告，再纳入可信健康数据。"
        case .daily: return "聚合睡眠、步数、HRV 和训练负荷，用来解释当天压力、恢复和炎症评分变化。"
        case .medical: return "管理你主动上传的真实就医资料，并在详情中查看原件和资料整理；不替代医生判断。"
        case .profile: return "维护基础资料、慢病、过敏和长期用药，让问答和计划生成更贴近个人状态。"
        }
    }

    fileprivate var rows: [XAgePanelRow] {
        switch self {
        case .reports:
            return [
                XAgePanelRow(icon: "arrow.up.doc.fill", title: "数据上传", subtitle: "体检报告、化验单、影像截图"),
                XAgePanelRow(icon: "doc.text.magnifyingglass", title: "AI 识别队列", subtitle: "抽取指标、异常值和参考范围"),
                XAgePanelRow(icon: "clock.arrow.circlepath", title: "历史报告", subtitle: "单份摘要、异常项和原始资料"),
                XAgePanelRow(icon: "checkmark.seal.fill", title: "需要确认", subtitle: "核对姓名、日期和关键指标")
            ]
        case .daily:
            return [
                XAgePanelRow(icon: "heart.text.square.fill", title: "Apple Health", subtitle: "同步睡眠、步数、静息心率"),
                XAgePanelRow(icon: "waveform.path.ecg", title: "恢复信号", subtitle: "HRV、呼吸率和训练负荷"),
                XAgePanelRow(icon: "chart.line.uptrend.xyaxis", title: "趋势解释", subtitle: "连接日常变化与三项评分")
            ]
        case .medical:
            return [
                XAgePanelRow(icon: "list.clipboard.fill", title: "真实就医资料", subtitle: "上传、列表、详情和原件查看")
            ]
        case .profile:
            return [
                XAgePanelRow(icon: "person.fill", title: "基础资料", subtitle: "年龄、身高、体重和目标"),
                XAgePanelRow(icon: "tag.fill", title: "长期标签", subtitle: "慢病、家族史和风险因素"),
                XAgePanelRow(icon: "exclamationmark.shield.fill", title: "安全信息", subtitle: "过敏、禁忌和长期用药")
            ]
        }
    }
}

private struct XAgePanelStat: Identifiable {
    var id: String { title }
    let title: String
    let value: String
    let unit: String
}

private struct XAgePanelRow: Identifiable {
    var id: String { title }
    let icon: String
    let title: String
    let subtitle: String

    var key: String {
        switch title {
        case "数据上传", "拍照上传": return "upload"
        case "AI 识别队列": return "recognition"
        case "历史报告": return "history"
        case "需要确认": return "confirm"
        case "Apple Health": return "apple-health"
        case "恢复信号": return "recovery"
        case "趋势解释": return "trend"
        case "真实就医资料": return "medical-documents"
        case "基础资料": return "basic"
        case "长期标签": return "tags"
        case "安全信息": return "safety"
        default: return title
        }
    }
}

private struct XAgePanelCategoryGlyph: View {
    let category: XAgeDataPanelCategory
    let selected: Bool

    var body: some View {
        ZStack {
            Circle()
                .fill(
                    selected
                    ? AnyShapeStyle(LinearGradient(colors: category.gradient, startPoint: .topLeading, endPoint: .bottomTrailing))
                    : AnyShapeStyle(Color(hex: "B8DFF5").opacity(0.3))
                )
                .overlay(Circle().stroke(.white.opacity(selected ? 0.84 : 0.58), lineWidth: 0.8))

            glyph
                .foregroundStyle(selected ? .white : Color(hex: "347FB7"))
        }
        .accessibilityHidden(true)
    }

    @ViewBuilder
    private var glyph: some View {
        switch category {
        case .reports:
            VStack(spacing: 1.6) {
                ForEach([8.0, 5.8, 7.2], id: \.self) { width in
                    RoundedRectangle(cornerRadius: 1.2, style: .continuous)
                        .frame(width: width, height: 1.8)
                }
            }
        case .daily:
            HStack(alignment: .bottom, spacing: 1.5) {
                ForEach([5.0, 9.0, 6.0, 11.0], id: \.self) { height in
                    RoundedRectangle(cornerRadius: 1.2, style: .continuous)
                        .frame(width: 2, height: height)
                }
            }
        case .medical:
            Image(systemName: "cross.fill")
                .font(.system(size: 8.5, weight: .bold))
        case .profile:
            Image(systemName: "checkmark")
                .font(.system(size: 8.5, weight: .bold))
        }
    }
}

private struct XAgePanelHeroAsset: View {
    let category: XAgeDataPanelCategory

    var body: some View {
        ZStack {
            Circle()
                .fill(LinearGradient(colors: category.gradient, startPoint: .topLeading, endPoint: .bottomTrailing))
                .shadow(color: category.gradient.last?.opacity(0.24) ?? Color(hex: "20CDB1").opacity(0.24), radius: 12, x: 0, y: 7)
            Circle()
                .stroke(.white.opacity(0.42), lineWidth: 1)
                .frame(width: 34, height: 34)
            XAgePanelCategoryGlyph(category: category, selected: true)
                .frame(width: 24, height: 24)
            Image(systemName: category.iconName)
                .font(.system(size: 9, weight: .black))
                .foregroundStyle(.white.opacity(0.92))
                .offset(x: 12, y: -12)
        }
        .frame(width: 48, height: 48)
        .accessibilityHidden(true)
    }
}

private enum XAgeReportUploadAction {
    case camera
    case document
    case photoLibrary
}

struct XAgeReportUploadFile: Identifiable, Equatable {
    let id = UUID()
    let data: Data
    let fileName: String

    var previewImage: UIImage? {
        UIImage(data: data)
    }
}

struct XAgePendingReportUpload: Identifiable, Equatable {
    let id = UUID()
    let title: String
    let source: String
    let files: [XAgeReportUploadFile]

    var totalSizeText: String {
        let totalBytes = files.reduce(0) { $0 + $1.data.count }
        let formatter = ByteCountFormatter()
        formatter.allowedUnits = totalBytes >= 1_000_000 ? [.useMB] : [.useKB]
        formatter.countStyle = .file
        return formatter.string(fromByteCount: Int64(totalBytes))
    }
}

struct XAgePanelDestinationView: View {
    let category: XAgeDataPanelCategory
    @ObservedObject var appleHealthSync: AppleHealthSyncViewModel
    let snapshot: XAgeServerSyncSnapshot
    let onSyncAppleHealth: () async -> Void
    var onClose: (() -> Void)?
    @Environment(\.dismiss) private var dismiss
    @EnvironmentObject private var authManager: AuthManager
    @StateObject private var reportUploadVM = HealthReportCompletionViewModel()
    @State private var selectedRowID: String?
    @State private var showCamera = false
    @State private var showPhotoLibrary = false
    @State private var showDocumentPicker = false
    @State private var showReportUploadOptions = false
    @State private var showReportHistory = false
    @State private var pendingUpload: XAgePendingReportUpload?
    @State private var recoveryAssetIndex: Int?
    @State private var uploadQualityWarning: String?
    @State private var reportReviewRoute: HealthReportWorkflowRoute?

    private var activeRow: XAgePanelRow {
        category.rows.first { $0.id == selectedRowID } ?? category.rows[0]
    }

    @ViewBuilder
    var body: some View {
        NavigationStack {
            if category == .profile {
                PatientHistoryView(onClose: onClose)
            } else if category == .medical {
                MedicalRecordListView()
            } else {
                genericPanel
            }
        }
    }

    private var genericPanel: some View {
        ZStack {
            XAgeLiquidBackground()
                .ignoresSafeArea()

            ScrollView {
                VStack(spacing: 16) {
                    header
                        .padding(.top, 18)

                    VStack(alignment: .leading, spacing: 16) {
                        HStack(spacing: 14) {
                            XAgePanelHeroAsset(category: category)
                                .frame(width: 62, height: 62)
                            VStack(alignment: .leading, spacing: 5) {
                                Text(category.headline)
                                    .font(.system(size: 27, weight: .bold))
                                    .foregroundStyle(Color(hex: "123E67"))
                                    .lineLimit(1)
                                    .minimumScaleFactor(0.82)
                                Text(category.subtitle)
                                    .font(.system(size: 14, weight: .semibold))
                                    .foregroundStyle(Color(hex: "5D7890"))
                                    .lineLimit(1)
                            }
                            Spacer(minLength: 0)
                        }

                        Text(category.detailSummary)
                            .font(.system(size: 14))
                            .foregroundStyle(Color(hex: "496A83"))
                            .lineSpacing(3)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    .padding(18)
                    .background(XAgeGlassCardBackground(cornerRadius: 28))

                    HStack(spacing: 9) {
                        ForEach(snapshot.stats(for: category)) { stat in
                            VStack(spacing: 5) {
                                Text(stat.title)
                                    .font(.system(size: 11, weight: .bold))
                                    .foregroundStyle(Color(hex: "6C8194"))
                                    .lineLimit(1)
                                HStack(alignment: .firstTextBaseline, spacing: 2) {
                                    Text(stat.value)
                                        .font(.system(size: 20, weight: .bold))
                                        .foregroundStyle(Color(hex: "12324F"))
                                        .lineLimit(1)
                                        .minimumScaleFactor(0.76)
                                    if !stat.unit.isEmpty {
                                        Text(stat.unit)
                                            .font(.system(size: 10, weight: .semibold))
                                            .foregroundStyle(Color(hex: "6C8194"))
                                    }
                                }
                            }
                            .frame(maxWidth: .infinity)
                            .frame(height: 70)
                            .background(XAgeGlassCardBackground(cornerRadius: 22))
                        }
                    }

                    VStack(spacing: 10) {
                        ForEach(category.rows) { row in
                            let isSelected = activeRow.id == row.id
                            if category == .daily && row.title == "Apple Health" {
                                Button {
                                    select(row)
                                    Task { await onSyncAppleHealth() }
                                } label: {
                                    XAgePanelActionRow(
                                        category: category,
                                        row: row,
                                        trailingTitle: appleHealthSync.isWorking ? nil : appleHealthSync.statusTitle,
                                        showsProgress: appleHealthSync.isWorking,
                                        isSelected: isSelected
                                    )
                                }
                                .buttonStyle(.plain)
                                .disabled(appleHealthSync.isWorking)
                                .accessibilityIdentifier("xage.appleHealth.destination.sync")
                            } else {
                                Button {
                                    select(row)
                                } label: {
                                    XAgePanelActionRow(
                                        category: category,
                                        row: row,
                                        trailingTitle: isSelected ? "查看中" : nil,
                                        isSelected: isSelected
                                    )
                                }
                                .buttonStyle(.plain)
                                .accessibilityIdentifier("xage.panel.\(category.id).row.\(row.key)")
                            }

                            if isSelected {
                                XAgePanelInteractiveDetail(
                                    category: category,
                                    row: activeRow,
                                    snapshot: snapshot,
                                    onReportUploadAction: handleReportUploadAction,
                                    onReportHistoryAction: { showReportHistory = true }
                                )
                                .transition(.opacity.combined(with: .move(edge: .top)))
                            }
                        }
                    }

                    if category == .reports,
                       reportUploadVM.uploading || reportUploadVM.backgroundTaskHint != nil {
                        Button {
                            reportReviewRoute = reportUploadVM.activeReportWorkflow
                        } label: {
                            XAgeChatUploadStatusCard(
                                uploading: reportUploadVM.uploading,
                                title: reportUploadVM.uploading
                                    ? (reportUploadVM.uploadStage.isEmpty ? "正在上传报告…" : reportUploadVM.uploadStage)
                                    : reportUploadVM.activeReportWorkflow == nil ? "报告处理状态" : "查看报告确认任务",
                                subtitle: reportUploadVM.backgroundTaskHint ?? "识别完成后仍需检查字段并确认整份报告。"
                            )
                        }
                        .buttonStyle(.plain)
                        .disabled(reportUploadVM.activeReportWorkflow == nil)
                        .accessibilityIdentifier("xage.panel.reports.upload.status")
                    }

                }
                .padding(.horizontal, 24)
                .padding(.bottom, 18)
            }
            .accessibilityIdentifier("xage.panel.\(category.id).scroll")
            .safeAreaInset(edge: .bottom) {
                primaryActionButton
                    .padding(.horizontal, 24)
                    .padding(.top, 8)
                    .padding(.bottom, 12)
                    .background(
                        LinearGradient(
                            colors: [
                                Color(hex: "E9F8FF").opacity(0),
                                Color(hex: "E9F8FF").opacity(0.92)
                            ],
                            startPoint: .top,
                            endPoint: .bottom
                        )
                        .ignoresSafeArea()
                    )
            }
        }
        .navigationBarBackButtonHidden(true)
        .toolbar(.hidden, for: .navigationBar)
        .fullScreenCover(isPresented: $showCamera) {
            CameraImagePicker(
                onPick: { data, name in
                    preparePendingReportUpload(
                        files: [XAgeReportUploadFile(data: data, fileName: name)],
                        title: "确认数据上传",
                        source: "相机"
                    )
                },
                fileNamePrefix: "xage_panel_report_camera"
            )
            .ignoresSafeArea()
        }
        .sheet(isPresented: $showPhotoLibrary) {
            MultiPhotoPicker(
                selectionLimit: recoveryAssetIndex == nil ? 9 : 1,
                fileNamePrefix: "xage_panel_report_album",
                onPick: { photos in
                    preparePendingReportUpload(
                        files: photos.map { XAgeReportUploadFile(data: $0.data, fileName: $0.fileName) },
                        title: photos.count > 1 ? "确认上传 \(photos.count) 张照片" : "确认相册上传",
                        source: "相册"
                    )
                },
                onError: { message in
                    reportUploadVM.errorMessage = message
                }
            )
        }
        .sheet(isPresented: $showDocumentPicker) {
            DocumentPickerView(
                onPick: { data, fileName in
                    preparePendingReportUpload(
                        files: [XAgeReportUploadFile(data: data, fileName: fileName)],
                        title: "确认上传文件",
                        source: "文件"
                    )
                },
                onError: { message in
                    reportUploadVM.errorMessage = message
                }
            )
        }
        .sheet(isPresented: $showReportUploadOptions) {
            XAgeReportUploadSourceSheet(
                onCamera: { presentReportUploadActionFromOptions(.camera) },
                onDocument: { presentReportUploadActionFromOptions(.document) },
                onPhotoLibrary: { presentReportUploadActionFromOptions(.photoLibrary) }
            )
            .presentationDetents([.height(330)])
            .presentationDragIndicator(.visible)
        }
        .sheet(isPresented: $showReportHistory) {
            XAgeReportHistorySheet()
                .presentationDetents([.large])
                .presentationDragIndicator(.visible)
        }
        .sheet(item: $pendingUpload) { upload in
            XAgeReportUploadConfirmSheet(
                upload: upload,
                isUploading: reportUploadVM.uploading,
                onCancel: { pendingUpload = nil },
                onConfirm: {
                    pendingUpload = nil
                    uploadReports(upload.files, source: upload.source)
                }
            )
            .presentationDetents([.medium, .large])
            .presentationDragIndicator(.visible)
        }
        .navigationDestination(item: $reportReviewRoute) { route in
            HealthReportReviewView(
                route: route,
                accountScope: authManager.accountScope,
                documentTitle: reportUploadVM.activeReportTitle
            )
        }
        .confirmationDialog(
            "检测到可能重复的报告",
            isPresented: Binding(
                get: { reportUploadVM.duplicatePrompt != nil },
                set: { if !$0 { reportUploadVM.deferDuplicateDecision() } }
            ),
            titleVisibility: .visible
        ) {
            Button("使用已有报告") {
                if let prompt = reportUploadVM.duplicatePrompt {
                    Task { await reportUploadVM.decideDuplicate(.useExisting, prompt: prompt) }
                }
            }
            Button("继续新建报告") {
                if let prompt = reportUploadVM.duplicatePrompt {
                    Task { await reportUploadVM.decideDuplicate(.continueNew, prompt: prompt) }
                }
            }
            Button("稍后处理", role: .cancel) {
                reportUploadVM.deferDuplicateDecision()
            }
        } message: {
            Text("系统只提示最相近的一份报告，不会自动覆盖。请选择是否复用已有报告。")
        }
        .alert("拍摄质量不足", isPresented: Binding(
            get: { uploadQualityWarning != nil },
            set: { if !$0 { uploadQualityWarning = nil } }
        )) {
            Button("重新拍摄") { uploadQualityWarning = nil; showCamera = true }
            Button("取消", role: .cancel) { uploadQualityWarning = nil }
        } message: {
            Text(uploadQualityWarning ?? "")
        }
        .alert("上传提示", isPresented: Binding(
            get: { reportUploadVM.infoMessage != nil },
            set: { if !$0 { reportUploadVM.infoMessage = nil } }
        )) {
            Button("知道了", role: .cancel) {}
        } message: {
            Text(reportUploadVM.infoMessage ?? "")
        }
        .alert(reportUploadVM.uploadRecovery == nil ? "上传失败" : "报告需要补传", isPresented: Binding(
            get: { reportUploadVM.errorMessage != nil },
            set: { if !$0 { reportUploadVM.errorMessage = nil } }
        )) {
            if let recovery = reportUploadVM.uploadRecovery,
               let index = recovery.nextAssetIndex {
                Button(recovery.actionCode == "upload_missing_pages" ? "拍照补第 \(index) 页" : "拍照替换第 \(index) 页") {
                    beginReportRecovery(assetIndex: index, useCamera: true)
                }
                Button(recovery.actionCode == "upload_missing_pages" ? "从相册补第 \(index) 页" : "从相册替换第 \(index) 页") {
                    beginReportRecovery(assetIndex: index, useCamera: false)
                }
                Button("重新上传整份", role: .destructive) {
                    reportUploadVM.abandonUploadRecovery()
                    recoveryAssetIndex = nil
                    showReportUploadOptions = true
                }
                Button("稍后处理", role: .cancel) {}
            } else if reportUploadVM.uploadRecovery != nil {
                Button("重新上传整份") {
                    reportUploadVM.abandonUploadRecovery()
                    recoveryAssetIndex = nil
                    showReportUploadOptions = true
                }
                Button("稍后处理", role: .cancel) {}
            } else {
                Button("确定", role: .cancel) {}
            }
        } message: {
            Text(reportUploadVM.errorMessage ?? "")
        }
        .onChange(of: reportUploadVM.activeReportWorkflow) { _, route in
            guard let route else { return }
            if [.awaitingConfirmation, .completedScorePending, .completed].contains(route.status) {
                reportReviewRoute = route
            }
        }
        .onChange(of: authManager.accountScope) { _, scope in
            reportUploadVM.accountDidChange(to: scope)
            reportReviewRoute = nil
        }
    }

    private var primaryActionButton: some View {
        Button {
            runPrimaryAction()
        } label: {
            Text(primaryButtonTitle)
                .font(.system(size: 15, weight: .bold))
                .foregroundStyle(.white)
                .frame(maxWidth: .infinity)
                .frame(height: 46)
                .background(
                    Capsule()
                        .fill(LinearGradient(colors: category.gradient, startPoint: .topLeading, endPoint: .bottomTrailing))
                        .shadow(color: (category.gradient.last ?? Color(hex: "20CDB1")).opacity(0.22), radius: 12, x: 0, y: 7)
                )
        }
        .buttonStyle(.plain)
        .disabled(category != .reports)
        .accessibilityIdentifier("xage.panel.\(category.id).primary")
    }

    private var primaryButtonTitle: String {
        switch category {
        case .reports:
            switch activeRow.key {
            case "upload": return "选择报告"
            case "history": return "查看历史报告"
            case "recognition": return "刷新识别状态"
            default: return "打开待确认报告"
            }
        case .daily:
            return "请从数据页同步 Apple Health"
        case .medical:
            return "打开就医助手"
        case .profile:
            return "打开可信健康画像"
        }
    }

    private func select(_ row: XAgePanelRow) {
        withAnimation(.spring(response: 0.24, dampingFraction: 0.88)) {
            selectedRowID = row.id
        }
    }

    private func runPrimaryAction() {
        guard category == .reports else { return }
        let row = activeRow
        switch row.key {
        case "upload":
            showReportUploadOptions = true
        case "history":
            showReportHistory = true
        case "recognition":
            Task { await reportUploadVM.refreshActiveRuntime() }
        default:
            showReportHistory = true
        }
    }

    private func runHeaderAction() {
        if category == .reports {
            showReportUploadOptions = true
            return
        }
        runPrimaryAction()
    }

    private func handleReportUploadAction(_ action: XAgeReportUploadAction) {
        guard category == .reports else { return }
        switch action {
        case .camera:
            showCamera = true
        case .document:
            showDocumentPicker = true
        case .photoLibrary:
            showPhotoLibrary = true
        }
    }

    private func presentReportUploadActionFromOptions(_ action: XAgeReportUploadAction) {
        showReportUploadOptions = false
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.28) {
            handleReportUploadAction(action)
        }
    }

    private func preparePendingReportUpload(files: [XAgeReportUploadFile], title: String, source: String) {
        guard !files.isEmpty else { return }
        for file in files {
            if let warning = validateReportImageQuality(data: file.data, fileName: file.fileName) {
                uploadQualityWarning = "\(file.fileName)：\(warning)"
                return
            }
        }
        if let assetIndex = recoveryAssetIndex {
            guard let file = files.first, files.count == 1 else {
                reportUploadVM.errorMessage = "补传时每次只能选择一页。"
                return
            }
            recoveryAssetIndex = nil
            Task {
                let route = await reportUploadVM.recoverReportAsset(
                    input: HealthReportUploadAssetInput(
                        data: file.data,
                        fileName: file.fileName
                    ),
                    assetIndex: assetIndex
                )
                if let route,
                   [.awaitingConfirmation, .completedScorePending, .completed].contains(route.status) {
                    reportReviewRoute = route
                }
            }
            return
        }
        let upload = XAgePendingReportUpload(title: title, source: source, files: files)
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.25) {
            pendingUpload = upload
        }
    }

    private func beginReportRecovery(assetIndex: Int, useCamera: Bool) {
        reportUploadVM.errorMessage = nil
        recoveryAssetIndex = assetIndex
        Task { @MainActor in
            await Task.yield()
            if useCamera {
                showCamera = true
            } else {
                showPhotoLibrary = true
            }
        }
    }

    private func uploadReports(_ files: [XAgeReportUploadFile], source: String) {
        guard !files.isEmpty else { return }
        Task {
            let route = await reportUploadVM.uploadReport(
                files: files.map {
                    HealthReportUploadAssetInput(data: $0.data, fileName: $0.fileName)
                },
                source: source,
                subjectUserID: authManager.authenticatedNumericUserID,
                accountScope: authManager.accountScope
            )
            if let route,
               [.awaitingConfirmation, .completedScorePending, .completed].contains(route.status) {
                reportReviewRoute = route
            }
        }
    }

    private func validateReportImageQuality(data: Data, fileName: String) -> String? {
        let lower = fileName.lowercased()
        let isImage = [".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".tif", ".tiff"].contains { lower.hasSuffix($0) }
        guard isImage else { return nil }
        if data.count < 30 * 1024 {
            return "图片过小（小于 30KB），可能不是完整报告。请重新拍摄。"
        }
        if let img = UIImage(data: data) {
            let shortEdge = min(img.size.width, img.size.height) * img.scale
            if shortEdge < 600 {
                return "图片分辨率过低（短边 \(Int(shortEdge))px），识别可能失败。请重新拍摄。"
            }
        } else {
            return "未能读取图片数据，请重新拍摄或选择 PDF。"
        }
        return nil
    }

    private var header: some View {
        HStack {
            Button {
                if let onClose {
                    onClose()
                } else {
                    dismiss()
                }
            } label: {
                Image(systemName: "chevron.left")
                    .font(.system(size: 17, weight: .bold))
                    .foregroundStyle(Color(hex: "347FB7"))
                    .frame(width: 42, height: 34)
                    .background(XAgeCapsuleFill())
            }
            .buttonStyle(.plain)
            .accessibilityLabel("返回")

            Spacer()

            Text(category.rawValue)
                .font(.system(size: 17, weight: .bold))
                .foregroundStyle(Color(hex: "123E67"))
                .frame(height: 34)
                .padding(.horizontal, 18)
                .background(XAgeCapsuleFill())

            Spacer()

            Button {
                runHeaderAction()
            } label: {
                Image(systemName: category.iconName)
                    .font(.system(size: 14, weight: .bold))
                    .foregroundStyle(.white)
                    .frame(width: 42, height: 34)
                    .background(
                        Capsule()
                            .fill(LinearGradient(colors: category.gradient, startPoint: .topLeading, endPoint: .bottomTrailing))
                            .overlay(Capsule().stroke(.white.opacity(0.72), lineWidth: 1))
                    )
            }
            .buttonStyle(.plain)
            .accessibilityLabel(category == .reports ? "上传报告" : "\(category.rawValue)快捷操作")
        }
    }
}

private struct XAgePanelInteractiveDetail: View {
    let category: XAgeDataPanelCategory
    let row: XAgePanelRow
    let snapshot: XAgeServerSyncSnapshot
    let onReportUploadAction: (XAgeReportUploadAction) -> Void
    let onReportHistoryAction: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 13) {
            HStack {
                VStack(alignment: .leading, spacing: 4) {
                    Text(row.title)
                        .font(.system(size: 18, weight: .bold))
                        .foregroundStyle(Color(hex: "173F64"))
                    Text(detailSubtitle)
                        .font(.system(size: 12))
                        .foregroundStyle(Color(hex: "6C8194"))
                        .lineLimit(2)
                }
                Spacer(minLength: 10)
                Text(category == .reports ? "可信链路" : "入口停用")
                    .font(.system(size: 11, weight: .bold))
                    .foregroundStyle(Color(hex: "347FB7"))
                    .frame(width: 62, height: 28)
                    .background(XAgeCapsuleFill())
            }

            content
        }
        .padding(16)
        .background(XAgeGlassCardBackground(cornerRadius: 24))
        .accessibilityIdentifier("xage.panel.\(category.id).detail.\(row.key)")
    }

    private var detailSubtitle: String {
        switch category {
        case .reports:
            return "选择入口、检查识别队列，并确认关键报告字段。"
        case .daily:
            return "请从数据页的 Apple Health 入口执行真实同步。"
        case .medical:
            return "仅展示真实上传、列表、详情和原件查看能力。"
        case .profile:
            return "健康画像由服务端事实、来源和版本统一管理。"
        }
    }

    @ViewBuilder
    private var content: some View {
        switch category {
        case .reports:
            reportsContent
        case .daily, .medical:
            disabledContent
        case .profile:
            EmptyView()
        }
    }

    @ViewBuilder
    private var reportsContent: some View {
        if row.key == "upload" {
            HStack(spacing: 9) {
                actionChip("拍照", icon: "camera.fill") { onReportUploadAction(.camera) }
                actionChip("选 PDF", icon: "doc.fill") { onReportUploadAction(.document) }
                actionChip("相册", icon: "photo.fill") { onReportUploadAction(.photoLibrary) }
            }
            infoRow("姓名与报告一致", subtitle: "未匹配时会进入人工确认")
            infoRow("最近报告 \(snapshot.latestDocumentLabel)", subtitle: "报告级确认后才能用于可信趋势")
            infoRow("\(snapshot.trustedDocumentCount) 份可信报告", subtitle: "未确认报告不会进入画像、评分或 AI")
        } else if row.key == "recognition" {
            progressLine("病历资料", value: progress(snapshot.recordCount, cap: 20), trailing: "\(snapshot.recordCount) 份")
            progressLine("体检化验", value: progress(snapshot.examCount, cap: 300), trailing: "\(snapshot.examCount) 份")
            progressLine("指标趋势", value: progress(snapshot.indicatorCount, cap: 300), trailing: "\(snapshot.indicatorCount) 项")
            HStack(spacing: 9) {
                infoBadge("异常项需复核", icon: "exclamationmark.triangle.fill")
                infoBadge("全部字段可追溯", icon: "list.bullet.rectangle")
            }
        } else if row.key == "history" {
            Button(action: onReportHistoryAction) {
                HStack(spacing: 10) {
                    Image(systemName: "clock.arrow.circlepath")
                        .font(.system(size: 15, weight: .bold))
                    VStack(alignment: .leading, spacing: 2) {
                        Text("打开历史报告")
                            .font(.system(size: 13, weight: .bold))
                        Text("查看识别状态、可信状态和待确认字段")
                            .font(.system(size: 11, weight: .medium))
                    }
                    Spacer()
                    Image(systemName: "chevron.right")
                        .font(.system(size: 12, weight: .bold))
                }
                .foregroundStyle(Color(hex: "347FB7"))
                .padding(.horizontal, 12)
                .frame(height: 52)
                .background(XAgeCapsuleFill())
            }
            .buttonStyle(.plain)
            progressLine("历史报告", value: progress(snapshot.examCount, cap: 30), trailing: "\(snapshot.examCount) 份")
            progressLine("历史病历", value: progress(snapshot.recordCount, cap: 20), trailing: "\(snapshot.recordCount) 份")
            infoRow("单份报告复核", subtitle: "检查原值、候选值、单位、异常和来源")
        } else {
            infoRow(snapshot.primaryWatchedLabel, subtitle: "\(snapshot.trendPointCount) 个历史趋势点可用于复核")
            infoRow("健康摘要", subtitle: snapshot.hasSummary ? "已生成，可作为问答上下文" : "暂无摘要，建议生成后再问答")
            infoRow("报告日期 \(snapshot.latestDocumentLabel)", subtitle: "确认后会用于排序")
        }
    }

    private var disabledContent: some View {
        Label("该快捷入口尚未接入服务端，已停用本地模拟操作。", systemImage: "nosign")
            .font(.system(size: 13, weight: .semibold))
            .foregroundStyle(Color(hex: "8B5B35"))
            .fixedSize(horizontal: false, vertical: true)
            .padding(12)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Color(hex: "FFF1E9").opacity(0.82), in: RoundedRectangle(cornerRadius: 18))
    }

    private func progress(_ value: Int, cap: Int) -> CGFloat {
        guard cap > 0 else { return 0 }
        return min(1, CGFloat(value) / CGFloat(cap))
    }

    private func actionChip(_ title: String, icon: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: 5) {
                Image(systemName: icon)
                    .font(.system(size: 11, weight: .bold))
                Text(title)
                    .font(.system(size: 12, weight: .bold))
                    .lineLimit(1)
                    .minimumScaleFactor(0.8)
            }
            .foregroundStyle(Color(hex: "347FB7"))
            .frame(maxWidth: .infinity)
            .frame(height: 34)
            .background(
                Capsule()
                    .fill(Color.white.opacity(0.62))
                    .overlay(Capsule().stroke(.white.opacity(0.78), lineWidth: 1))
            )
        }
        .buttonStyle(.plain)
    }

    private func infoRow(_ title: String, subtitle: String) -> some View {
        HStack(spacing: 10) {
                Image(systemName: "info.circle.fill")
                    .font(.system(size: 18, weight: .bold))
                    .foregroundStyle(Color(hex: "347FB7"))
                VStack(alignment: .leading, spacing: 2) {
                    Text(title)
                        .font(.system(size: 13, weight: .bold))
                        .foregroundStyle(Color(hex: "173F64"))
                        .lineLimit(1)
                        .minimumScaleFactor(0.82)
                    Text(subtitle)
                        .font(.system(size: 11))
                        .foregroundStyle(Color(hex: "6C8194"))
                        .lineLimit(1)
                        .minimumScaleFactor(0.78)
                }
                Spacer(minLength: 6)
            }
            .padding(.horizontal, 12)
            .frame(height: 52)
            .background(
                RoundedRectangle(cornerRadius: 18, style: .continuous)
                    .fill(.white.opacity(0.48))
                    .overlay(
                        RoundedRectangle(cornerRadius: 18, style: .continuous)
                            .stroke(.white.opacity(0.7), lineWidth: 1)
                    )
            )
    }

    private func infoBadge(_ title: String, icon: String) -> some View {
        Label(title, systemImage: icon)
            .font(.system(size: 11, weight: .bold))
            .foregroundStyle(Color(hex: "347FB7"))
            .lineLimit(1)
            .minimumScaleFactor(0.76)
            .frame(maxWidth: .infinity)
            .frame(height: 34)
            .background(XAgeCapsuleFill())
    }

    private func progressLine(_ title: String, value: CGFloat, trailing: String) -> some View {
        VStack(alignment: .leading, spacing: 7) {
            HStack {
                Text(title)
                    .font(.system(size: 12, weight: .bold))
                    .foregroundStyle(Color(hex: "173F64"))
                Spacer()
                Text(trailing)
                    .font(.system(size: 12, weight: .bold))
                    .foregroundStyle(Color(hex: "347FB7"))
            }
            GeometryReader { proxy in
                ZStack(alignment: .leading) {
                    Capsule()
                        .fill(.white.opacity(0.54))
                    Capsule()
                        .fill(LinearGradient(colors: category.gradient, startPoint: .leading, endPoint: .trailing))
                        .frame(width: max(14, proxy.size.width * min(max(value, 0), 1)))
                }
            }
            .frame(height: 8)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
        .background(
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .fill(.white.opacity(0.48))
                .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous).stroke(.white.opacity(0.7), lineWidth: 1))
        )
    }

}

private struct XAgeReportUploadSourceSheet: View {
    let onCamera: () -> Void
    let onDocument: () -> Void
    let onPhotoLibrary: () -> Void

    var body: some View {
        ZStack {
            XAgeLiquidBackground()
                .ignoresSafeArea()

            VStack(alignment: .leading, spacing: 14) {
                HStack(spacing: 12) {
                    ZStack {
                        Circle()
                            .fill(LinearGradient(colors: [Color(hex: "238AD6"), Color(hex: "20CDB1")], startPoint: .topLeading, endPoint: .bottomTrailing))
                        Image(systemName: "arrow.up.doc.fill")
                            .font(.system(size: 22, weight: .bold))
                            .foregroundStyle(.white)
                    }
                    .frame(width: 52, height: 52)

                    VStack(alignment: .leading, spacing: 3) {
                        Text("数据上传")
                            .font(.system(size: 24, weight: .bold))
                            .foregroundStyle(Color(hex: "123E67"))
                        Text("选择报告、化验单或影像截图来源")
                            .font(.system(size: 13, weight: .medium))
                            .foregroundStyle(Color(hex: "5D7890"))
                    }
                }

                uploadSourceRow(title: "拍照采集", subtitle: "拍摄纸质报告或检查单", icon: "camera.fill", action: onCamera)
                uploadSourceRow(title: "选择 PDF / 图片", subtitle: "从文件中上传报告、病历或扫描件", icon: "doc.badge.plus", action: onDocument)
                uploadSourceRow(title: "从相册选择", subtitle: "一次可选择多张报告图片", icon: "photo.on.rectangle.angled", action: onPhotoLibrary)
            }
            .padding(24)
        }
    }

    private func uploadSourceRow(title: String, subtitle: String, icon: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: 12) {
                Image(systemName: icon)
                    .font(.system(size: 16, weight: .bold))
                    .foregroundStyle(.white)
                    .frame(width: 38, height: 38)
                    .background(
                        Circle()
                            .fill(LinearGradient(colors: [Color(hex: "238AD6"), Color(hex: "20CDB1")], startPoint: .topLeading, endPoint: .bottomTrailing))
                    )
                VStack(alignment: .leading, spacing: 3) {
                    Text(title)
                        .font(.system(size: 16, weight: .bold))
                        .foregroundStyle(Color(hex: "173F64"))
                    Text(subtitle)
                        .font(.system(size: 12, weight: .medium))
                        .foregroundStyle(Color(hex: "6C8194"))
                        .lineLimit(1)
                }
                Spacer()
                Image(systemName: "chevron.right")
                    .font(.system(size: 12, weight: .bold))
                    .foregroundStyle(Color(hex: "7D9AB1"))
            }
            .padding(.horizontal, 14)
            .frame(height: 62)
            .background(XAgeGlassCardBackground(cornerRadius: 22))
        }
        .buttonStyle(.plain)
    }
}

@MainActor
private final class XAgeReportHistoryViewModel: ObservableObject {
    @Published private(set) var loading = false
    @Published private(set) var traceLoadingWorkflowID: Int?
    @Published private(set) var items: [HealthReportHistoryItem] = []
    @Published private(set) var activeQuery = HealthReportHistoryQuery.empty
    @Published var selectedTrace: XAgeReportTraceSelection?
    @Published var errorMessage: String?

    private let repository: any HealthReportCompletionRepositoryProtocol
    private let currentAccountScope: @MainActor () -> String?
    private var activeContext: XAgeReportHistoryContext?
    private var loadGeneration = 0
    private var traceGeneration = 0

    init(
        repository: any HealthReportCompletionRepositoryProtocol = HealthReportCompletionRepository(),
        currentAccountScope: @escaping @MainActor () -> String? = { AuthManager.shared.accountScope }
    ) {
        self.repository = repository
        self.currentAccountScope = currentAccountScope
    }

    func load(
        subjectUserID: Int?,
        accountScope: String?,
        query: HealthReportHistoryQuery? = nil
    ) async {
        loadGeneration &+= 1
        let generation = loadGeneration
        guard let subjectUserID,
              let accountScope,
              !accountScope.isEmpty,
              currentAccountScope() == accountScope else {
            resetForUnavailableAccount()
            errorMessage = "当前账号无法读取报告历史，请重新登录后重试。"
            return
        }

        let context = XAgeReportHistoryContext(
            accountScope: accountScope,
            subjectUserID: subjectUserID
        )
        if activeContext != context {
            activeContext = context
            items = []
            selectedTrace = nil
            activeQuery = .empty
        }
        let requestedQuery = query ?? activeQuery
        activeQuery = requestedQuery
        errorMessage = nil
        loading = true
        defer {
            if loadGeneration == generation {
                loading = false
            }
        }
        do {
            let response = try await repository.fetchHistory(
                subjectUserID: subjectUserID,
                dateFrom: requestedQuery.dateFrom,
                dateTo: requestedQuery.dateTo,
                hospital: requestedQuery.hospital,
                reportType: requestedQuery.reportType
            )
            guard loadGeneration == generation,
                  activeContext == context,
                  currentAccountScope() == accountScope else { return }
            // The server owns ordering and workflow status; never re-sort or infer here.
            items = response.items
        } catch {
            guard loadGeneration == generation,
                  activeContext == context,
                  currentAccountScope() == accountScope else { return }
            errorMessage = error.localizedDescription
        }
    }

    func openTrace(
        for item: HealthReportHistoryItem,
        subjectUserID: Int?,
        accountScope: String?
    ) async {
        traceGeneration &+= 1
        let generation = traceGeneration
        guard let subjectUserID,
              let accountScope,
              !accountScope.isEmpty,
              currentAccountScope() == accountScope,
              activeContext == XAgeReportHistoryContext(
                accountScope: accountScope,
                subjectUserID: subjectUserID
              ) else {
            errorMessage = "账号已切换，请重新打开报告历史。"
            return
        }

        errorMessage = nil
        traceLoadingWorkflowID = item.workflow_id
        defer {
            if traceGeneration == generation {
                traceLoadingWorkflowID = nil
            }
        }
        do {
            let trace = try await repository.fetchTrace(
                workflowID: item.workflow_id,
                subjectUserID: subjectUserID
            )
            guard traceGeneration == generation,
                  currentAccountScope() == accountScope else { return }
            guard trace.workflow.id == item.workflow_id else {
                errorMessage = "服务器返回的追踪记录与所选报告不一致，请刷新后重试。"
                return
            }
            selectedTrace = XAgeReportTraceSelection(
                item: item,
                trace: trace,
                subjectUserID: subjectUserID,
                accountScope: accountScope
            )
        } catch {
            guard traceGeneration == generation,
                  currentAccountScope() == accountScope else { return }
            errorMessage = error.localizedDescription
        }
    }

    func presentError(_ message: String) {
        errorMessage = message
    }

    private func resetForUnavailableAccount() {
        loading = false
        traceLoadingWorkflowID = nil
        activeContext = nil
        activeQuery = .empty
        items = []
        selectedTrace = nil
    }
}

private struct XAgeReportHistoryContext: Equatable {
    let accountScope: String
    let subjectUserID: Int
}

private struct XAgeReportHistorySheet: View {
    @StateObject private var vm = XAgeReportHistoryViewModel()
    @Environment(\.dismiss) private var dismiss
    @EnvironmentObject private var authManager: AuthManager
    @FocusState private var hospitalFieldFocused: Bool
    @State private var filtersExpanded = false
    @State private var usesDateFrom = false
    @State private var usesDateTo = false
    @State private var dateFrom = Date().addingTimeInterval(-90 * 24 * 60 * 60)
    @State private var dateTo = Date()
    @State private var hospital = ""
    @State private var reportType = XAgeReportHistoryReportType.all

    var body: some View {
        ZStack {
            XAgeLiquidBackground()
                .ignoresSafeArea()

            VStack(spacing: 14) {
                header
                ScrollView {
                    LazyVStack(spacing: 12) {
                        filterSummary
                        if filtersExpanded {
                            filterCard
                                .transition(.opacity.combined(with: .move(edge: .top)))
                        }
                        historyContent
                    }
                    .padding(2)
                }
                .scrollDismissesKeyboard(.interactively)
                .scrollIndicators(.hidden)
                .refreshable { await loadActiveQuery() }
                .background(
                    Color.clear
                        .contentShape(Rectangle())
                        .onTapGesture { hospitalFieldFocused = false }
                )
            }
            .padding(24)
        }
        .task(id: authManager.accountScope) {
            resetFilterInputs()
            await vm.load(
                subjectUserID: authManager.authenticatedNumericUserID,
                accountScope: authManager.accountScope,
                query: .empty
            )
        }
        .sheet(item: $vm.selectedTrace) { selection in
            XAgeReportTraceSheet(selection: selection)
                .presentationDetents([.large])
                .presentationDragIndicator(.visible)
        }
        .xAgeKeyboardDoneAccessory(
            isPresented: hospitalFieldFocused,
            accessibilityIdentifier: "xage.report.history.keyboard.done"
        ) {
            hospitalFieldFocused = false
        }
        .alert("读取失败", isPresented: Binding(
            get: { vm.errorMessage != nil },
            set: { if !$0 { vm.errorMessage = nil } }
        )) {
            Button("知道了", role: .cancel) {}
        } message: {
            Text(vm.errorMessage ?? "")
        }
    }

    private var header: some View {
        HStack {
            VStack(alignment: .leading, spacing: 4) {
                Text("历史报告")
                    .font(.system(size: 25, weight: .bold))
                    .foregroundStyle(Color(hex: "123E67"))
                Text("列表、状态和追踪链均以服务器记录为准")
                    .font(.system(size: 13, weight: .medium))
                    .foregroundStyle(Color(hex: "5D7890"))
            }
            Spacer()
            Button {
                hospitalFieldFocused = false
                dismiss()
            } label: {
                Image(systemName: "xmark")
                    .font(.system(size: 13, weight: .bold))
                    .foregroundStyle(Color(hex: "1268BD"))
                    .frame(width: 34, height: 34)
                    .background(XAgeCapsuleFill())
            }
            .frame(width: 44, height: 44)
            .contentShape(Rectangle())
            .buttonStyle(.plain)
            .accessibilityLabel("关闭历史报告")
        }
    }

    private var filterSummary: some View {
        HStack(spacing: 10) {
            Button {
                hospitalFieldFocused = false
                withAnimation(.spring(response: 0.24, dampingFraction: 0.9)) {
                    filtersExpanded.toggle()
                }
            } label: {
                HStack(spacing: 8) {
                    Image(systemName: "line.3.horizontal.decrease.circle.fill")
                    Text(filtersExpanded ? "收起筛选" : "筛选报告")
                    if vm.activeQuery.activeFilterCount > 0 {
                        Text("\(vm.activeQuery.activeFilterCount)")
                            .font(.caption2.weight(.bold))
                            .foregroundStyle(.white)
                            .frame(minWidth: 22, minHeight: 22)
                            .background(Circle().fill(Color(hex: "238AD6")))
                    }
                }
                .font(.system(size: 14, weight: .bold))
                .foregroundStyle(Color(hex: "347FB7"))
                .frame(maxWidth: .infinity, minHeight: 44)
                .background(XAgeCapsuleFill())
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("xage.report.history.filters.toggle")

            if !vm.activeQuery.isEmpty {
                Button("清除") { clearFilters() }
                    .font(.system(size: 13, weight: .bold))
                    .foregroundStyle(Color(hex: "D85A66"))
                    .frame(minWidth: 64, minHeight: 44)
                    .background(XAgeCapsuleFill())
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("xage.report.history.clear")
            }
        }
    }

    private var filterCard: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("按服务器字段筛选")
                .font(.system(size: 16, weight: .bold))
                .foregroundStyle(Color(hex: "173F64"))
            dateFilterRow(title: "开始日期", enabled: $usesDateFrom, date: $dateFrom, identifier: "dateFrom")
            dateFilterRow(title: "结束日期", enabled: $usesDateTo, date: $dateTo, identifier: "dateTo")

            VStack(alignment: .leading, spacing: 6) {
                Text("医院")
                    .font(.caption.weight(.bold))
                    .foregroundStyle(Color(hex: "5D7890"))
                TextField("输入医院名称", text: $hospital)
                    .textInputAutocapitalization(.never)
                    .submitLabel(.done)
                    .focused($hospitalFieldFocused)
                    .onSubmit { hospitalFieldFocused = false }
                    .padding(.horizontal, 14)
                    .frame(minHeight: 44)
                    .background(XAgeCapsuleFill())
                    .accessibilityIdentifier("xage.report.history.hospital")
            }

            HStack {
                Text("报告类型")
                    .font(.system(size: 14, weight: .bold))
                    .foregroundStyle(Color(hex: "173F64"))
                Spacer()
                Picker("报告类型", selection: $reportType) {
                    ForEach(XAgeReportHistoryReportType.allCases) { type in
                        Text(type.title).tag(type)
                    }
                }
                .pickerStyle(.menu)
                .accessibilityIdentifier("xage.report.history.reportType")
            }
            .frame(minHeight: 44)

            HStack(spacing: 10) {
                Button("清除筛选") { clearFilters() }
                    .font(.system(size: 14, weight: .bold))
                    .foregroundStyle(Color(hex: "347FB7"))
                    .frame(maxWidth: .infinity, minHeight: 46)
                    .background(XAgeCapsuleFill())
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("xage.report.history.filters.clear")
                Button("应用筛选") { applyFilters() }
                    .font(.system(size: 14, weight: .bold))
                    .foregroundStyle(.white)
                    .frame(maxWidth: .infinity, minHeight: 46)
                    .background(
                        Capsule().fill(
                            LinearGradient(
                                colors: [Color(hex: "238AD6"), Color(hex: "20CDB1")],
                                startPoint: .leading,
                                endPoint: .trailing
                            )
                        )
                    )
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("xage.report.history.filters.apply")
            }
        }
        .padding(16)
        .background(XAgeGlassCardBackground(cornerRadius: 24))
    }

    @ViewBuilder
    private var historyContent: some View {
        if vm.loading && vm.items.isEmpty {
            VStack(spacing: 10) {
                ProgressView().tint(Color(hex: "18AFA7"))
                Text("正在读取服务器报告历史")
                    .font(.system(size: 13, weight: .medium))
                    .foregroundStyle(Color(hex: "5D7890"))
            }
            .frame(maxWidth: .infinity, minHeight: 300)
            .background(XAgeGlassCardBackground(cornerRadius: 24))
        } else if vm.items.isEmpty {
            XAgeReportHistoryEmptyState(filtered: !vm.activeQuery.isEmpty)
                .frame(minHeight: 300)
        } else {
            ForEach(vm.items) { item in
                Button {
                    hospitalFieldFocused = false
                    Task {
                        await vm.openTrace(
                            for: item,
                            subjectUserID: authManager.authenticatedNumericUserID,
                            accountScope: authManager.accountScope
                        )
                    }
                } label: {
                    XAgeReportHistoryRow(
                        item: item,
                        loadingTrace: vm.traceLoadingWorkflowID == item.workflow_id
                    )
                }
                .buttonStyle(.plain)
                .disabled(vm.traceLoadingWorkflowID != nil)
                .accessibilityIdentifier("xage.report.history.workflow.\(item.workflow_id)")
                .accessibilityLabel("\(item.title)，\(item.xAgeHistoryMetadataLabel)，\(item.xAgeWorkflowStatusLabel)")
            }
        }
    }

    private func dateFilterRow(
        title: String,
        enabled: Binding<Bool>,
        date: Binding<Date>,
        identifier: String
    ) -> some View {
        VStack(spacing: 6) {
            Toggle(title, isOn: enabled)
                .font(.system(size: 14, weight: .bold))
                .foregroundStyle(Color(hex: "173F64"))
                .frame(minHeight: 44)
                .accessibilityIdentifier("xage.report.history.\(identifier).enabled")
            if enabled.wrappedValue {
                DatePicker(title, selection: date, displayedComponents: .date)
                    .datePickerStyle(.compact)
                    .labelsHidden()
                    .frame(maxWidth: .infinity, alignment: .trailing)
                    .accessibilityIdentifier("xage.report.history.\(identifier).value")
            }
        }
    }

    private func applyFilters() {
        hospitalFieldFocused = false
        if usesDateFrom, usesDateTo, dateFrom > dateTo {
            vm.presentError("开始日期不能晚于结束日期。")
            return
        }
        let query = HealthReportHistoryQuery(
            dateFrom: usesDateFrom ? serverDate(dateFrom) : nil,
            dateTo: usesDateTo ? serverDate(dateTo) : nil,
            hospital: hospital,
            reportType: reportType == .all ? nil : reportType.rawValue
        )
        Task {
            await vm.load(
                subjectUserID: authManager.authenticatedNumericUserID,
                accountScope: authManager.accountScope,
                query: query
            )
        }
    }

    private func clearFilters() {
        hospitalFieldFocused = false
        resetFilterInputs()
        Task {
            await vm.load(
                subjectUserID: authManager.authenticatedNumericUserID,
                accountScope: authManager.accountScope,
                query: .empty
            )
        }
    }

    private func loadActiveQuery() async {
        await vm.load(
            subjectUserID: authManager.authenticatedNumericUserID,
            accountScope: authManager.accountScope
        )
    }

    private func resetFilterInputs() {
        usesDateFrom = false
        usesDateTo = false
        dateFrom = Date().addingTimeInterval(-90 * 24 * 60 * 60)
        dateTo = Date()
        hospital = ""
        reportType = .all
    }

    private func serverDate(_ date: Date) -> String {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = .current
        let parts = calendar.dateComponents([.year, .month, .day], from: date)
        return String(format: "%04d-%02d-%02d", parts.year ?? 0, parts.month ?? 0, parts.day ?? 0)
    }
}

extension HealthDocument {
    var xAgeDisplayTitle: String {
        let title = (name ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        if !title.isEmpty { return title }
        let urlName = (file_url ?? "").split(separator: "/").last.map(String.init) ?? ""
        if !urlName.isEmpty { return urlName }
        return doc_type == "record" ? "未命名病历" : "未命名报告"
    }

    var xAgeStatusLabel: String {
        switch reportTrustState {
        case .workflow(let status):
            switch status {
            case .draft, .uploading: return "上传中"
            case .recognizing: return "识别中"
            case .awaitingConfirmation: return "待确认"
            case .committing: return "入库中"
            case .completedScorePending: return "已确认 · 评分待更新"
            case .completed: return "可信完成"
            case .failed: return "识别失败"
            case .unknown: return "状态待刷新"
            }
        case .legacyRecognizing:
            return "识别中"
        case .legacyUnverified:
            return "历史未验证"
        }
    }

    var xAgeStatusColor: Color {
        switch reportTrustState {
        case .workflow(.completed): return Color(hex: "18AFA7")
        case .workflow(.completedScorePending): return Color(hex: "C57A27")
        case .workflow(.failed): return Color(hex: "D85A66")
        case .workflow, .legacyRecognizing: return Color(hex: "238AD6")
        case .legacyUnverified: return Color(hex: "8B5B35")
        }
    }

    var xAgeReviewActionTitle: String {
        switch reportTrustState {
        case .workflow(.awaitingConfirmation): return "检查字段并确认整份报告"
        case .workflow(.recognizing), .workflow(.uploading), .workflow(.draft): return "查看识别进度"
        case .workflow(.committing): return "查看入库状态"
        case .workflow(.completedScorePending): return "查看已确认字段和评分状态"
        case .workflow(.completed): return "查看已确认字段"
        case .workflow(.failed): return "查看失败原因"
        case .workflow(.unknown): return "刷新报告状态"
        case .legacyRecognizing, .legacyUnverified: return "查看报告状态"
        }
    }

}

private struct XAgePanelActionRow: View {
    let category: XAgeDataPanelCategory
    let row: XAgePanelRow
    var trailingTitle: String?
    var showsProgress: Bool = false
    var isSelected: Bool = false

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: row.icon)
                .font(.system(size: 16, weight: .bold))
                .foregroundStyle(.white)
                .frame(width: 38, height: 38)
                .background(
                    Circle()
                        .fill(LinearGradient(colors: category.gradient, startPoint: .topLeading, endPoint: .bottomTrailing))
                        .shadow(color: (category.gradient.last ?? Color(hex: "20CDB1")).opacity(0.18), radius: 10, x: 0, y: 5)
                )
            VStack(alignment: .leading, spacing: 3) {
                Text(row.title)
                    .font(.system(size: 16, weight: .bold))
                    .foregroundStyle(Color(hex: "173F64"))
                    .lineLimit(1)
                Text(row.subtitle)
                    .font(.system(size: 12))
                    .foregroundStyle(Color(hex: "6C8194"))
                    .lineLimit(1)
                    .minimumScaleFactor(0.82)
            }
            Spacer(minLength: 8)
            if showsProgress {
                ProgressView()
                    .controlSize(.small)
                    .frame(width: 52, height: 30)
            } else if let trailingTitle {
                Text(trailingTitle)
                    .font(.system(size: 11, weight: .bold))
                    .foregroundStyle(Color(hex: "347FB7"))
                    .lineLimit(1)
                    .minimumScaleFactor(0.74)
                    .frame(width: 72, height: 30)
                    .background(XAgeCapsuleFill())
            } else {
                Image(systemName: "chevron.right")
                    .font(.system(size: 13, weight: .bold))
                    .foregroundStyle(Color(hex: "7D9AB1"))
            }
        }
        .padding(.horizontal, 14)
        .frame(height: 66)
        .background(XAgeGlassCardBackground(cornerRadius: 22))
        .overlay(
            RoundedRectangle(cornerRadius: 22, style: .continuous)
                .stroke(isSelected ? (category.gradient.last ?? Color(hex: "20CDB1")).opacity(0.58) : .clear, lineWidth: 1.2)
        )
    }
}

struct XAgeReportUploadConfirmSheet: View {
    let upload: XAgePendingReportUpload
    let isUploading: Bool
    let onCancel: () -> Void
    let onConfirm: () -> Void

    var body: some View {
        ZStack {
            XAgeLiquidBackground()
                .ignoresSafeArea()

            VStack(alignment: .leading, spacing: 16) {
                HStack(alignment: .top, spacing: 12) {
                    ZStack {
                        Circle()
                            .fill(
                                LinearGradient(
                                    colors: [Color(hex: "238AD6"), Color(hex: "20CDB1")],
                                    startPoint: .topLeading,
                                    endPoint: .bottomTrailing
                                )
                            )
                        Image(systemName: upload.files.count > 1 ? "photo.stack.fill" : "arrow.up.doc.fill")
                            .font(.system(size: 22, weight: .bold))
                            .foregroundStyle(.white)
                    }
                    .frame(width: 54, height: 54)

                    VStack(alignment: .leading, spacing: 4) {
                        Text(upload.title)
                            .font(.system(size: 24, weight: .bold))
                            .foregroundStyle(Color(hex: "123E67"))
                            .fixedSize(horizontal: false, vertical: true)
                        Text("\(upload.source) · \(upload.files.count) 个文件 · \(upload.totalSizeText)")
                            .font(.system(size: 13, weight: .medium))
                            .foregroundStyle(Color(hex: "5D7890"))
                    }

                    Spacer(minLength: 0)
                }

                Text("确认后才会上传到你的健康资料库，并进入 AI 识别队列。取消不会保存这些图片或文件。")
                    .font(.system(size: 13))
                    .foregroundStyle(Color(hex: "496A83"))
                    .lineSpacing(3)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(14)
                    .background(XAgeCapsuleFill())

                ScrollView {
                    LazyVGrid(columns: [GridItem(.adaptive(minimum: 92), spacing: 10)], spacing: 10) {
                        ForEach(upload.files) { file in
                            XAgeReportUploadPreviewCell(file: file)
                        }
                    }
                    .padding(2)
                }
                .scrollIndicators(.hidden)
                .frame(maxHeight: 230)

                HStack(spacing: 10) {
                    Button(action: onCancel) {
                        Text("取消")
                            .font(.system(size: 15, weight: .bold))
                            .foregroundStyle(Color(hex: "365F80"))
                            .frame(maxWidth: .infinity)
                            .frame(height: 46)
                            .background(XAgeCapsuleFill())
                    }
                    .buttonStyle(.plain)
                    .disabled(isUploading)

                    Button(action: onConfirm) {
                        HStack(spacing: 8) {
                            if isUploading {
                                ProgressView()
                                    .tint(.white)
                            }
                            Text(isUploading ? "上传中" : "确认上传")
                                .font(.system(size: 15, weight: .bold))
                        }
                        .foregroundStyle(.white)
                        .frame(maxWidth: .infinity)
                        .frame(height: 46)
                        .background(
                            Capsule()
                                .fill(
                                    LinearGradient(
                                        colors: [Color(hex: "238AD6"), Color(hex: "20CDB1")],
                                        startPoint: .topLeading,
                                        endPoint: .bottomTrailing
                                    )
                                )
                        )
                    }
                    .buttonStyle(.plain)
                    .disabled(isUploading)
                    .accessibilityIdentifier("xage.reportUpload.confirm")
                }
            }
            .padding(24)
        }
    }
}

private struct XAgeReportUploadPreviewCell: View {
    let file: XAgeReportUploadFile

    var body: some View {
        VStack(spacing: 8) {
            ZStack {
                RoundedRectangle(cornerRadius: 18, style: .continuous)
                    .fill(.white.opacity(0.54))
                    .overlay(
                        RoundedRectangle(cornerRadius: 18, style: .continuous)
                            .stroke(.white.opacity(0.74), lineWidth: 1)
                    )
                if let image = file.previewImage {
                    Image(uiImage: image)
                        .resizable()
                        .scaledToFill()
                        .frame(height: 86)
                        .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
                } else {
                    Image(systemName: "doc.fill")
                        .font(.system(size: 25, weight: .bold))
                        .foregroundStyle(Color(hex: "347FB7"))
                }
            }
            .frame(height: 86)

            Text(file.fileName)
                .font(.system(size: 10, weight: .medium))
                .foregroundStyle(Color(hex: "5D7890"))
                .lineLimit(2)
                .multilineTextAlignment(.center)
                .frame(height: 28)
        }
        .padding(8)
        .background(XAgeGlassCardBackground(cornerRadius: 22))
    }
}

private struct XAgeDataDetailView: View {
    let kind: XAgeDataKind
    let metric: XAgeMetricScore
    let onSyncAppleHealth: () async -> Void
    let onOpenGuide: () -> Void
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        ZStack {
            XAgeLiquidBackground()
                .ignoresSafeArea()
            ScrollView {
                VStack(spacing: 16) {
                    ZStack {
                        VStack(spacing: 3) {
                            Text(kind.rawValue)
                                .font(.system(size: 28, weight: .bold))
                                .foregroundStyle(Color(hex: "123E67"))
                            Text(metric.isTrustedForDisplay ? "服务端版本 \(metric.serverSnapshotVersion ?? "")" : "评分待更新")
                                .font(.system(size: 12, weight: .bold))
                                .foregroundStyle(kind.tint)
                                .padding(.horizontal, 10)
                                .padding(.vertical, 4)
                                .background(XAgeCapsuleFill())
                        }

                        HStack {
                            Spacer()
                            Button {
                                dismiss()
                            } label: {
                                Image(systemName: "xmark")
                                    .font(.system(size: 13, weight: .bold))
                                    .foregroundStyle(Color(hex: "1268BD"))
                                    .frame(width: 34, height: 34)
                                    .background(XAgeCapsuleFill())
                            }
                            .frame(width: 44, height: 44)
                            .contentShape(Rectangle())
                            .accessibilityLabel("关闭")
                        }
                    }
                    .padding(.top, 14)

                    XAgeScoreRing(kind: kind, metric: metric)
                        .frame(width: 150)
                        .padding(.vertical, 10)

                    if !metric.isTrustedForDisplay {
                        XAgeMissingDataGuideCard(
                            kind: kind,
                            metric: metric,
                            onSyncAppleHealth: onSyncAppleHealth,
                            onOpenGuide: onOpenGuide
                        )
                    }

                    VStack(alignment: .leading, spacing: 12) {
                        Text("指标构成")
                            .font(.system(size: 18, weight: .bold))
                            .foregroundStyle(Color(hex: "173F64"))
                        ForEach(metric.fields) { field in
                            HStack {
                                Text(field.title)
                                    .font(.system(size: 14, weight: .medium))
                                    .foregroundStyle(Color(hex: "496A83"))
                                Spacer()
                                Text(field.value)
                                    .font(.system(size: 14, weight: .bold))
                                    .foregroundStyle(Color(hex: "17324E"))
                            }
                            Divider().opacity(0.24)
                        }
                    }
                    .padding(18)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(XAgeGlassCardBackground(cornerRadius: 26))

                    VStack(alignment: .leading, spacing: 10) {
                        Text("主要输入")
                            .font(.system(size: 18, weight: .bold))
                            .foregroundStyle(Color(hex: "173F64"))
                        ForEach(metric.drivers.prefix(3)) { driver in
                            HStack(alignment: .top, spacing: 10) {
                                Circle()
                                    .fill(kind.tint)
                                    .frame(width: 7, height: 7)
                                    .padding(.top, 6)
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(driver.title)
                                        .font(.system(size: 14, weight: .bold))
                                        .foregroundStyle(Color(hex: "17324E"))
                                    Text(driver.note)
                                        .font(.system(size: 12))
                                        .foregroundStyle(Color(hex: "5D7890"))
                                        .lineSpacing(2)
                                }
                            }
                        }
                    }
                    .padding(18)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(XAgeGlassCardBackground(cornerRadius: 26))

                    VStack(alignment: .leading, spacing: 8) {
                        Text("先看结论")
                            .font(.system(size: 18, weight: .bold))
                            .foregroundStyle(Color(hex: "173F64"))
                        Text(metric.simpleExplanation)
                            .font(.system(size: 14))
                            .foregroundStyle(Color(hex: "496A83"))
                            .lineSpacing(3)
                        DisclosureGroup {
                            Text(metric.explanation)
                                .font(.system(size: 13))
                                .foregroundStyle(Color(hex: "5D7890"))
                                .lineSpacing(3)
                                .fixedSize(horizontal: false, vertical: true)
                                .padding(.top, 6)
                        } label: {
                            Text("专业依据")
                                .font(.system(size: 13, weight: .bold))
                                .foregroundStyle(kind.tint)
                        }
                        .tint(kind.tint)

                        Text(metric.nextAction)
                            .font(.system(size: 13, weight: .bold))
                            .foregroundStyle(kind.tint)
                            .lineSpacing(3)
                            .padding(12)
                            .background(XAgeCapsuleFill())
                    }
                    .padding(18)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(XAgeGlassCardBackground(cornerRadius: 26))
                }
                .padding(24)
            }
        }
    }
}

private struct XAgeMissingDataGuideCard: View {
    let kind: XAgeDataKind
    let metric: XAgeMetricScore
    let onSyncAppleHealth: () async -> Void
    let onOpenGuide: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 10) {
                Image(systemName: "tray.and.arrow.up.fill")
                    .font(.system(size: 16, weight: .bold))
                    .foregroundStyle(kind.tint)
                    .frame(width: 34, height: 34)
                    .background(XAgeCapsuleFill())
                VStack(alignment: .leading, spacing: 3) {
                    Text("等待可信评分")
                        .font(.system(size: 17, weight: .bold))
                        .foregroundStyle(Color(hex: "173F64"))
                    Text(metric.summary)
                        .font(.system(size: 12))
                        .foregroundStyle(Color(hex: "5D7890"))
                        .lineLimit(2)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }

            HStack(spacing: 10) {
                Button {
                    Task { await onSyncAppleHealth() }
                } label: {
                    guideButtonTitle("同步 Apple 健康", icon: "heart.text.square.fill", filled: true)
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("xage.score.missing.syncAppleHealth")

                Button(action: onOpenGuide) {
                    guideButtonTitle(kind == .inflammation ? "上传报告" : "打开指标", icon: kind == .inflammation ? "arrow.up.doc.fill" : "list.bullet.rectangle", filled: false)
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("xage.score.missing.openGuide")
            }
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(XAgeGlassCardBackground(cornerRadius: 26))
    }

    private func guideButtonTitle(_ title: String, icon: String, filled: Bool) -> some View {
        HStack(spacing: 6) {
            Image(systemName: icon)
                .font(.system(size: 12, weight: .bold))
            Text(title)
                .font(.system(size: 13, weight: .bold))
                .lineLimit(1)
                .minimumScaleFactor(0.82)
        }
        .foregroundStyle(filled ? .white : kind.tint)
        .frame(maxWidth: .infinity)
        .frame(height: 38)
        .background(
            Capsule()
                .fill(filled ? AnyShapeStyle(LinearGradient(colors: [kind.tint, Color(hex: "20CDB1")], startPoint: .leading, endPoint: .trailing)) : AnyShapeStyle(Color.white.opacity(0.62)))
                .overlay(Capsule().stroke(.white.opacity(0.8), lineWidth: 1))
        )
    }
}

private struct XAgeScoreInfoSheet: View {
    let kind: XAgeDataKind
    let metric: XAgeMetricScore
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        ZStack {
            XAgeLiquidBackground()
                .ignoresSafeArea()

            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    HStack(spacing: 12) {
                        Image(systemName: "info.circle.fill")
                            .font(.system(size: 22, weight: .bold))
                            .foregroundStyle(kind.tint)
                        VStack(alignment: .leading, spacing: 3) {
                            Text("\(kind.rawValue)原理")
                                .font(.system(size: 24, weight: .bold))
                                .foregroundStyle(Color(hex: "173F64"))
                            Text(metric.isTrustedForDisplay ? "服务端版本化评分" : "评分待更新")
                                .font(.system(size: 13, weight: .medium))
                                .foregroundStyle(Color(hex: "5D7890"))
                        }
                        Spacer()
                        Button {
                            dismiss()
                        } label: {
                            Image(systemName: "xmark")
                                .font(.system(size: 14, weight: .bold))
                                .foregroundStyle(Color(hex: "2A79BB"))
                                .frame(width: 36, height: 36)
                                .background(XAgeCapsuleFill())
                        }
                        .frame(width: 44, height: 44)
                        .contentShape(Rectangle())
                        .buttonStyle(.plain)
                        .accessibilityLabel("关闭\(kind.rawValue)原理")
                    }

                    VStack(alignment: .leading, spacing: 10) {
                        Text("先看结论")
                            .font(.system(size: 17, weight: .bold))
                            .foregroundStyle(Color(hex: "173F64"))
                        Text(metric.simpleExplanation)
                            .font(.system(size: 14))
                            .foregroundStyle(Color(hex: "496A83"))
                            .lineSpacing(4)
                            .fixedSize(horizontal: false, vertical: true)
                        DisclosureGroup {
                            Text(metric.explanation)
                                .font(.system(size: 13))
                                .foregroundStyle(Color(hex: "5D7890"))
                                .lineSpacing(4)
                                .fixedSize(horizontal: false, vertical: true)
                                .padding(.top, 6)
                        } label: {
                            Text("专业依据")
                                .font(.system(size: 13, weight: .bold))
                                .foregroundStyle(kind.tint)
                        }
                        .tint(kind.tint)
                    }
                    .padding(16)
                    .background(XAgeGlassCardBackground(cornerRadius: 24))

                    VStack(alignment: .leading, spacing: 10) {
                        Text("主要输入")
                            .font(.system(size: 17, weight: .bold))
                            .foregroundStyle(Color(hex: "173F64"))
                        ForEach(metric.drivers.prefix(3)) { driver in
                            HStack {
                                Text(driver.title)
                                    .font(.system(size: 13, weight: .bold))
                                    .foregroundStyle(Color(hex: "17324E"))
                                Spacer()
                                Text(driver.value)
                                    .font(.system(size: 13, weight: .bold))
                                    .foregroundStyle(kind.tint)
                            }
                            .padding(11)
                            .background(XAgeCapsuleFill())
                        }
                    }
                    .padding(16)
                    .background(XAgeGlassCardBackground(cornerRadius: 24))

                    Text(metric.nextAction)
                        .font(.system(size: 13, weight: .bold))
                        .foregroundStyle(kind.tint)
                        .lineSpacing(3)
                        .fixedSize(horizontal: false, vertical: true)
                        .padding(14)
                        .background(XAgeCapsuleFill())
                }
                .padding(24)
            }
            .scrollIndicators(.hidden)
        }
    }
}
