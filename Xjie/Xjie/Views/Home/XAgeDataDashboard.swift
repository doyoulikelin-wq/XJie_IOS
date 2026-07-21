import SwiftUI

/// XAGE 首页的数据总览容器。
///
/// 该组件只负责编排评分摘要、快捷功能、健康数据卡片和页面级导航；具体的同步、评分、
/// 指标管理、报告面板与体重流程分别由独立模块实现，避免业务继续堆回首页文件。
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
    @State private var showsWeightRecordPage = false
    @State private var metrics: [XAgeMetric]
    @State private var metricPreference: XAgeDataCardPreferenceSnapshot
    @State private var pendingMetricScrollID: String?
    @State private var isTodayStatusHidden = false

    /// 创建数据总览页。
    /// - Parameters:
    ///   - managerRequest: 外部触发“打开数据卡片管理”的递增请求标记。
    ///   - appleHealthSync: Apple 健康授权与设备样本同步模型。
    ///   - serverSync: 当前账号的服务端聚合数据模型。
    ///   - scores: 已经过展示策略处理的评分快照。
    ///   - accountScope: 当前账号隔离标识；账号切换时用于重置本地卡片状态。
    ///   - onSyncAppleHealth: 用户主动同步 Apple 健康时执行的异步动作。
    ///   - onOpenMetricGuide: 打开某项评分数据补充说明的回调。
    ///   - onOpenQuickAction: 打开业务快捷功能的回调，参数为稳定功能 ID。
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
        .navigationDestination(isPresented: $showsWeightRecordPage) {
            weightRecordPage
                .navigationBarBackButtonHidden(true)
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
            XAgeQuickActionStrip(onOpen: openQuickAction)

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

    /// 将稳定快捷功能 ID 分流到数据页自有导航或上层业务路由。
    /// - Parameter action: 当前被点击的快捷功能定义。
    private func openQuickAction(_ action: XAgeQuickActionSpec) {
        switch action.id {
        case "data-manager":
            showsMetricManager = true
        case "weight":
            showsWeightRecordPage = true
        default:
            guard action.destination == action.id else { return }
            onOpenQuickAction(action.id)
        }
    }

    private var weightRecordMetric: XAgeMetric {
        serverSync.metricCards.first(where: { $0.id == "bodyWeight" })
            ?? XAgeMetric.appleHealthCandidates.first(where: { $0.id == "bodyWeight" })!
    }

    private var weightRecordPage: some View {
        let metric = weightRecordMetric
        return XAgeWeightRecordFlowView(
            metric: metric,
            trend: serverSync.trend(for: metric),
            heightCentimeters: recordedHeightCentimeters,
            refresh: {
                await refreshAllData(includeAppleHealth: false)
                let refreshedMetric = serverSync.metricCards.first(where: { $0.id == metric.id }) ?? metric
                return XAgeWeightRecordSnapshot(
                    metric: refreshedMetric,
                    trend: serverSync.trend(for: refreshedMetric),
                    heightCentimeters: recordedHeightCentimeters
                )
            }
        )
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
            if metric.id == "bodyWeight" {
                XAgeWeightRecordFlowView(
                    metric: metric,
                    trend: serverSync.trend(for: metric),
                    heightCentimeters: recordedHeightCentimeters,
                    refresh: {
                        await refreshAllData(includeAppleHealth: false)
                        let refreshedMetric = serverSync.metricCards.first(where: { $0.id == metric.id }) ?? metric
                        return XAgeWeightRecordSnapshot(
                            metric: refreshedMetric,
                            trend: serverSync.trend(for: refreshedMetric),
                            heightCentimeters: recordedHeightCentimeters
                        )
                    }
                )
                .presentationDetents([.large])
                .presentationDragIndicator(.visible)
            } else {
                XAgeMetricDetailSheet(
                    metric: metric,
                    trend: serverSync.trend(for: metric),
                    onManualRecord: {
                        activeSheet = .manualEntry(metric)
                    }
                )
                .presentationDetents([.large])
                .presentationDragIndicator(.visible)
            }
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

    private var recordedHeightCentimeters: Double? {
        if let profileHeight = serverSync.snapshot.profileHeightCm, profileHeight > 0 {
            return profileHeight
        }
        guard let heightMetric = XAgeMetric.appleHealthCandidates.first(where: { $0.id == "bodyHeight" }),
              let heightTrend = serverSync.trend(for: heightMetric) else { return nil }
        return XAgeMetricTrendContract.samples(from: heightTrend).last?.value
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
