import SwiftUI

/// 数据页可推入根导航栈的页面类型。
///
/// 数据页本身位于分页 `TabView` 中，因此只发送该稳定路由，不直接注册
/// `navigationDestination`。
enum XAgeDataNavigationRoute: String, Identifiable, Hashable {
    case metricManager
    case weightRecord

    var id: String { rawValue }
}

/// 一次根导航展示请求，携带创建时的账号代次。
///
/// - Parameters:
///   - route: 要打开的数据页目标。
///   - accountGeneration: 创建请求时的账号代次；A→B→A 也不会复用。
struct XAgeDataNavigationPresentation: Identifiable, Hashable {
    let route: XAgeDataNavigationRoute
    let accountGeneration: UUID

    var id: String { "\(accountGeneration.uuidString)-\(route.id)" }
}

/// 一次数据详情 Sheet 请求，携带创建时的账号代次。
///
/// - Parameters:
///   - sheet: 要展示的评分、指标或手动录入内容。
///   - accountGeneration: 创建请求时的账号代次。
struct XAgeDataSheetPresentation: Identifiable {
    let sheet: XAgeDataSheet
    let accountGeneration: UUID

    var id: String { "\(accountGeneration.uuidString)-\(sheet.id)" }
}

/// 数据页与根导航目标共享的账号隔离状态。
///
/// 指标管理页会直接修改置顶卡片，因此指标、偏好、导航路由和详情 Sheet 必须由同一个
/// 长生命周期对象持有。账号变化时在这里原子清空展示状态，避免旧账号页面或实时值泄漏
/// 到新账号。
@MainActor
final class XAgeDataDashboardCoordinator: ObservableObject {
    /// 根 `NavigationStack` 当前消费的数据页路由；`nil` 表示停留在数据页。
    @Published var route: XAgeDataNavigationPresentation?
    /// 根页面当前展示的数据详情 Sheet。
    @Published var activeSheet: XAgeDataSheetPresentation?
    /// 首页与指标管理页共享的置顶指标集合。
    @Published var metrics: [XAgeMetric]
    /// 当前账号的指标排序偏好，只允许协调器在配置或持久化时更新。
    @Published private(set) var metricPreference: XAgeDataCardPreferenceSnapshot

    private var accountScope: String?
    private var accountGeneration = UUID()
    private var hasConfiguredAccountScope = false

    /// 创建尚未绑定登录账号的安全占位状态；首次页面任务会立即调用 `configure`。
    init() {
        let preference = XAgeDataCardPreferences.load(accountScope: nil)
        self.metricPreference = preference
        self.metrics = XAgeDataCardPreferences.placeholderMetrics(for: preference)
    }

    /// 绑定账号并重置全部可见状态。
    /// - Parameter newScope: 当前登录账号的稳定隔离标识；退出登录时为 `nil`。
    func configure(accountScope newScope: String?) {
        guard !hasConfiguredAccountScope || accountScope != newScope else { return }
        accountScope = newScope
        accountGeneration = UUID()
        route = nil
        activeSheet = nil
        metricPreference = XAgeDataCardPreferences.load(accountScope: newScope)
        metrics = XAgeDataCardPreferences.placeholderMetrics(for: metricPreference)
        hasConfiguredAccountScope = true
    }

    /// 创建绑定当前账号代次的根导航请求。
    /// - Parameter destination: 要打开的数据页目标。
    func present(route destination: XAgeDataNavigationRoute) {
        route = XAgeDataNavigationPresentation(
            route: destination,
            accountGeneration: accountGeneration
        )
    }

    /// 创建绑定当前账号代次的数据详情 Sheet 请求。
    /// - Parameter destination: 要展示的评分、指标或手动录入内容。
    func present(sheet destination: XAgeDataSheet) {
        activeSheet = XAgeDataSheetPresentation(
            sheet: destination,
            accountGeneration: accountGeneration
        )
    }

    /// 判断异步回调是否仍属于当前账号代次。
    /// - Parameter generation: 操作开始时捕获的账号代次。
    func accepts(accountGeneration generation: UUID) -> Bool {
        hasConfiguredAccountScope && accountGeneration == generation
    }

    /// 保存当前置顶指标的稳定 ID 顺序，不持久化服务端实时值。
    func persistMetricPreferences() {
        metricPreference = XAgeDataCardPreferences.save(
            metrics: metrics,
            accountScope: accountScope
        )
    }

    /// 合并 Apple 健康返回的本地样本。
    /// - Parameters:
    ///   - samples: 当前账号刚读取到的设备健康样本。
    ///   - catalogSections: 当前可用指标目录，用于恢复已自定义的卡片顺序。
    func mergeAppleHealthSamples(
        _ samples: [AppleHealthSyncSample],
        catalogSections: [XAgeMetricCatalogSection]
    ) {
        let synced = samples.compactMap { XAgeMetric.appleHealthMetric(from: $0) }
        guard !synced.isEmpty else { return }
        withAnimation(.spring(response: 0.26, dampingFraction: 0.88)) {
            if metricPreference.isCustomized {
                metrics = XAgeDataCardPreferences.orderedMetrics(
                    for: metricPreference,
                    from: synced + metrics + catalogSections.flatMap(\.metrics)
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

    /// 合并服务端权威指标，同时保留用户自定义的置顶顺序。
    /// - Parameters:
    ///   - serverMetrics: 当前账号的服务端指标卡。
    ///   - catalogSections: 当前可用指标目录。
    func mergeServerMetrics(
        _ serverMetrics: [XAgeMetric],
        catalogSections: [XAgeMetricCatalogSection]
    ) {
        guard !serverMetrics.isEmpty else {
            restoreMetricPreferences(
                serverMetrics: serverMetrics,
                catalogSections: catalogSections
            )
            return
        }
        let shouldAnimate = metrics.contains { metric in
            serverMetrics.contains(where: { $0.id == metric.id })
        }
        let apply = {
            if self.metricPreference.isCustomized {
                self.metrics = XAgeDataCardPreferences.orderedMetrics(
                    for: self.metricPreference,
                    from: serverMetrics + self.metrics + catalogSections.flatMap(\.metrics)
                )
            } else {
                var next = self.metrics
                for metric in serverMetrics {
                    if let index = next.firstIndex(where: { $0.id == metric.id }) {
                        next[index] = metric
                    } else {
                        next.insert(metric, at: 0)
                    }
                }
                self.metrics = self.dedupedMetrics(next)
            }
        }
        if shouldAnimate {
            withAnimation(.spring(response: 0.26, dampingFraction: 0.88), apply)
        } else {
            apply()
        }
    }

    /// 当指标目录异步更新时，恢复当前账号已保存但此前尚未加载到的卡片。
    /// - Parameters:
    ///   - serverMetrics: 当前账号的服务端指标卡。
    ///   - catalogSections: 更新后的完整指标目录。
    func restoreMetricPreferences(
        serverMetrics: [XAgeMetric],
        catalogSections: [XAgeMetricCatalogSection]
    ) {
        guard metricPreference.isCustomized else { return }
        let restored = XAgeDataCardPreferences.orderedMetrics(
            for: metricPreference,
            from: serverMetrics + metrics + catalogSections.flatMap(\.metrics)
        )
        guard metricSnapshots(metrics) != metricSnapshots(restored) else { return }
        metrics = restored
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

/// XAGE 首页的数据总览容器。
///
/// 该组件只负责编排评分摘要、快捷功能和健康数据卡片，并向根页面发送类型化路由；
/// 具体导航目标、同步、评分、指标管理、报告面板与体重流程分别由独立模块实现。
struct XAgeDataDashboardView: View {
    let managerRequest: Int
    @ObservedObject var coordinator: XAgeDataDashboardCoordinator
    @ObservedObject var appleHealthSync: AppleHealthSyncViewModel
    @ObservedObject var serverSync: XAgeServerSyncViewModel
    let scores: XAgeCompositeScores
    let accountScope: String?
    let onSyncAppleHealth: () async -> Void
    let onOpenMetricGuide: (XAgeDataKind) -> Void
    let onOpenQuickAction: (String) -> Void
    @State private var isTodayStatusHidden = false

    /// 创建数据总览页。
    /// - Parameters:
    ///   - managerRequest: 外部触发“打开数据卡片管理”的递增请求标记。
    ///   - coordinator: 数据页、根导航目标与详情 Sheet 共享的账号隔离状态。
    ///   - appleHealthSync: Apple 健康授权与设备样本同步模型。
    ///   - serverSync: 当前账号的服务端聚合数据模型。
    ///   - scores: 已经过展示策略处理的评分快照。
    ///   - accountScope: 当前账号隔离标识；账号切换时用于重置本地卡片状态。
    ///   - onSyncAppleHealth: 用户主动同步 Apple 健康时执行的异步动作。
    ///   - onOpenMetricGuide: 打开某项评分数据补充说明的回调。
    ///   - onOpenQuickAction: 打开业务快捷功能的回调，参数为稳定功能 ID。
    init(
        managerRequest: Int,
        coordinator: XAgeDataDashboardCoordinator,
        appleHealthSync: AppleHealthSyncViewModel,
        serverSync: XAgeServerSyncViewModel,
        scores: XAgeCompositeScores,
        accountScope: String?,
        onSyncAppleHealth: @escaping () async -> Void,
        onOpenMetricGuide: @escaping (XAgeDataKind) -> Void,
        onOpenQuickAction: @escaping (String) -> Void
    ) {
        self.managerRequest = managerRequest
        self.coordinator = coordinator
        self.appleHealthSync = appleHealthSync
        self.serverSync = serverSync
        self.scores = scores
        self.accountScope = accountScope
        self.onSyncAppleHealth = onSyncAppleHealth
        self.onOpenMetricGuide = onOpenMetricGuide
        self.onOpenQuickAction = onOpenQuickAction
    }

    var body: some View {
        VStack(spacing: 0) {
            stickyHeader
            metricsScroll
        }
        .onChange(of: appleHealthSync.samples) { _, samples in
            coordinator.mergeAppleHealthSamples(samples, catalogSections: metricCatalogSections)
        }
        .onReceive(serverSync.$metricCards) { cards in
            coordinator.mergeServerMetrics(cards, catalogSections: metricCatalogSections)
        }
        .onReceive(serverSync.$indicatorCatalogCards) { _ in
            coordinator.restoreMetricPreferences(
                serverMetrics: serverSync.metricCards,
                catalogSections: metricCatalogSections
            )
        }
        .onChange(of: managerRequest) { _, _ in
            coordinator.present(route: .metricManager)
        }
        .task {
            await refreshAllData(includeAppleHealth: true)
        }
    }

    private var stickyHeader: some View {
        XAgeDataStickyHeader(
            collapseProgress: 0,
            caption: serverSync.snapshot.headerCaption,
            scores: scores,
            showsTodayStatus: !isTodayStatusHidden,
            onSelectDetail: { coordinator.present(sheet: .detail($0)) },
            onSelectInfo: { coordinator.present(sheet: .scoreInfo($0)) }
        )
        .padding(.horizontal, 24)
        .padding(.top, 16)
        .padding(.bottom, 7)
        .zIndex(2)
    }

    private var metricsScroll: some View {
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

            if coordinator.metrics.isEmpty {
                XAgeMetricEmptyRow(
                    title: "首页暂无数据卡片",
                    subtitle: "打开数据卡片管理，添加需要长期关注的指标。"
                )
                .accessibilityIdentifier("xage.data.metric.empty")
            }

            ForEach(coordinator.metrics) { card in
                metricCard(card)
            }
        }
        .padding(.horizontal, 24)
        .padding(.top, 7)
        .padding(.bottom, 32)
    }

    /// 将稳定快捷功能 ID 分流到数据页自有导航或上层业务路由。
    /// - Parameter action: 当前被点击的快捷功能定义。
    private func openQuickAction(_ action: XAgeQuickActionSpec) {
        switch action.id {
        case "data-manager":
            coordinator.present(route: .metricManager)
        case "weight":
            coordinator.present(route: .weightRecord)
        default:
            guard action.destination == action.id else { return }
            onOpenQuickAction(action.id)
        }
    }

    private func metricCard(_ card: XAgeMetric) -> some View {
        XAgeMetricCard(
            card: card
        ) {
            coordinator.present(sheet: .metricDetail(card))
        }
        .id(card.id)
        .accessibilityIdentifier("xage.data.metric.\(card.id)")
    }

    private func refreshAllData(includeAppleHealth: Bool) async {
        if includeAppleHealth {
            await appleHealthSync.refreshIfPreviouslySynced()
        }
        await serverSync.refresh()
        coordinator.mergeServerMetrics(
            serverSync.metricCards,
            catalogSections: metricCatalogSections
        )
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

    private var metricCatalogSections: [XAgeMetricCatalogSection] {
        XAgeMetric.catalogSections(serverMetrics: serverSync.indicatorCatalogCards)
    }
}

/// 根导航栈的数据页目标构造器。
///
/// - Parameters:
///   - presentation: 数据页发出的目标类型和创建时账号代次。
///   - coordinator: 首页与目标页共享的卡片、偏好和 Sheet 状态。
///   - appleHealthSync: 指标管理页使用的 Apple 健康同步状态。
///   - serverSync: 体重页与指标目录使用的服务端数据。
///   - onSyncAppleHealth: 用户在指标管理页主动发起同步的动作。
struct XAgeDataNavigationDestinationView: View {
    let presentation: XAgeDataNavigationPresentation
    @ObservedObject var coordinator: XAgeDataDashboardCoordinator
    @ObservedObject var appleHealthSync: AppleHealthSyncViewModel
    @ObservedObject var serverSync: XAgeServerSyncViewModel
    let onSyncAppleHealth: () async -> Void

    @ViewBuilder
    var body: some View {
        switch presentation.route {
        case .metricManager:
            XAgeMetricManagerPage(
                pinnedMetrics: $coordinator.metrics,
                catalogSections: metricCatalogSections,
                appleHealthSync: appleHealthSync,
                onSyncAppleHealth: onSyncAppleHealth,
                onMetricsChanged: {
                    guard coordinator.accepts(
                        accountGeneration: presentation.accountGeneration
                    ) else { return }
                    coordinator.persistMetricPreferences()
                },
                onOpenMetric: { metric in
                    guard coordinator.accepts(
                        accountGeneration: presentation.accountGeneration
                    ) else { return }
                    coordinator.present(sheet: .metricDetail(metric))
                }
            )
        case .weightRecord:
            XAgeWeightRecordDestinationView(
                metric: weightRecordMetric,
                accountGeneration: presentation.accountGeneration,
                coordinator: coordinator,
                serverSync: serverSync
            )
            .navigationBarBackButtonHidden(true)
        }
    }

    private var metricCatalogSections: [XAgeMetricCatalogSection] {
        XAgeMetric.catalogSections(serverMetrics: serverSync.indicatorCatalogCards)
    }

    private var weightRecordMetric: XAgeMetric {
        serverSync.metricCards.first(where: { $0.id == "bodyWeight" })
            ?? XAgeMetric.appleHealthCandidates.first(where: { $0.id == "bodyWeight" })!
    }
}

/// 根页面的数据详情 Sheet 构造器。
///
/// - Parameters:
///   - presentation: 被点击的目标和创建时账号代次。
///   - coordinator: 负责 Sheet 之间的切换和账号变化清理。
///   - appleHealthSync: 评分详情主动同步 Apple 健康时使用。
///   - serverSync: 指标趋势、身高和保存后刷新使用。
///   - scores: 当前可信的评分展示快照。
///   - onSyncAppleHealth: 用户主动同步 Apple 健康的动作。
///   - onOpenMetricGuide: 关闭评分 Sheet 后打开对应资料说明的动作。
struct XAgeDataSheetDestinationView: View {
    let presentation: XAgeDataSheetPresentation
    @ObservedObject var coordinator: XAgeDataDashboardCoordinator
    @ObservedObject var appleHealthSync: AppleHealthSyncViewModel
    @ObservedObject var serverSync: XAgeServerSyncViewModel
    let scores: XAgeCompositeScores
    let onSyncAppleHealth: () async -> Void
    let onOpenMetricGuide: (XAgeDataKind) -> Void

    @ViewBuilder
    var body: some View {
        switch presentation.sheet {
        case .detail(let kind):
            XAgeDataDetailView(
                kind: kind,
                metric: scores.score(for: kind),
                onSyncAppleHealth: onSyncAppleHealth,
                onOpenGuide: {
                    guard coordinator.accepts(
                        accountGeneration: presentation.accountGeneration
                    ) else { return }
                    coordinator.activeSheet = nil
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.24) {
                        guard coordinator.accepts(
                            accountGeneration: presentation.accountGeneration
                        ) else { return }
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
                XAgeWeightRecordDestinationView(
                    metric: metric,
                    accountGeneration: presentation.accountGeneration,
                    coordinator: coordinator,
                    serverSync: serverSync
                )
                .presentationDetents([.large])
                .presentationDragIndicator(.visible)
            } else {
                XAgeMetricDetailSheet(
                    metric: metric,
                    trend: serverSync.trend(for: metric),
                    onManualRecord: {
                        guard coordinator.accepts(
                            accountGeneration: presentation.accountGeneration
                        ) else { return }
                        coordinator.present(sheet: .manualEntry(metric))
                    }
                )
                .presentationDetents([.large])
                .presentationDragIndicator(.visible)
            }
        case .manualEntry(let metric):
            XAgeManualMetricEntrySheet(
                metric: metric,
                onCancel: {
                    guard coordinator.accepts(
                        accountGeneration: presentation.accountGeneration
                    ) else { return }
                    coordinator.present(sheet: .metricDetail(metric))
                },
                onSaved: {
                    finishManualEntry()
                }
            )
            .presentationDetents([.large])
        }
    }

    /// 手动录入保存完成后仅在账号代次仍一致时合并并关闭原 Sheet。
    private func finishManualEntry() {
        let generation = presentation.accountGeneration
        Task { @MainActor in
            await serverSync.refresh()
            guard coordinator.accepts(accountGeneration: generation) else { return }
            coordinator.mergeServerMetrics(
                serverSync.metricCards,
                catalogSections: XAgeMetric.catalogSections(
                    serverMetrics: serverSync.indicatorCatalogCards
                )
            )
            coordinator.activeSheet = nil
        }
    }
}

/// 体重详情的共享目标，供根导航页和体重指标 Sheet 复用。
///
/// - Parameters:
///   - metric: 打开页面时使用的体重指标；刷新失败时作为安全回退。
///   - accountGeneration: 打开页面时捕获的账号代次。
///   - coordinator: 刷新后接收最新服务端卡片的共享状态。
///   - serverSync: 提供体重趋势、身高与保存后刷新。
private struct XAgeWeightRecordDestinationView: View {
    let metric: XAgeMetric
    let accountGeneration: UUID
    @ObservedObject var coordinator: XAgeDataDashboardCoordinator
    @ObservedObject var serverSync: XAgeServerSyncViewModel

    var body: some View {
        XAgeWeightRecordFlowView(
            metric: metric,
            trend: serverSync.trend(for: metric),
            heightCentimeters: recordedHeightCentimeters,
            refresh: refreshSnapshot
        )
    }

    /// 保存体重后拉取最新快照，返回同一指标、趋势和身高给流程页面。
    private func refreshSnapshot() async -> XAgeWeightRecordSnapshot {
        let fallback = XAgeWeightRecordSnapshot(
            metric: metric,
            trend: serverSync.trend(for: metric),
            heightCentimeters: recordedHeightCentimeters
        )
        await serverSync.refresh()
        guard coordinator.accepts(accountGeneration: accountGeneration) else {
            return fallback
        }
        coordinator.mergeServerMetrics(
            serverSync.metricCards,
            catalogSections: XAgeMetric.catalogSections(
                serverMetrics: serverSync.indicatorCatalogCards
            )
        )
        let refreshedMetric = serverSync.metricCards.first(where: { $0.id == metric.id }) ?? metric
        return XAgeWeightRecordSnapshot(
            metric: refreshedMetric,
            trend: serverSync.trend(for: refreshedMetric),
            heightCentimeters: recordedHeightCentimeters
        )
    }

    /// 优先使用用户画像身高，缺失时再回退到服务端身高趋势的最新值。
    private var recordedHeightCentimeters: Double? {
        if let profileHeight = serverSync.snapshot.profileHeightCm, profileHeight > 0 {
            return profileHeight
        }
        guard let heightMetric = XAgeMetric.appleHealthCandidates.first(where: { $0.id == "bodyHeight" }),
              let heightTrend = serverSync.trend(for: heightMetric) else { return nil }
        return XAgeMetricTrendContract.samples(from: heightTrend).last?.value
    }
}
