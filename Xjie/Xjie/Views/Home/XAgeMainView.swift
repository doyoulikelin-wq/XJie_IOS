import AVFoundation
import Speech
import SwiftUI
import UIKit

// MARK: - 顶层导航与通用交互

/// 新版 XAGE 的三个一级页面。枚举同时作为顶部选项和分页 TabView 的稳定 selection 值。
enum XAgeTopSection: String, CaseIterable, Identifiable {
    case data = "数据"
    case chat = "问答"
    case xAge = "X年龄"

    var id: String { rawValue }
}

private extension View {
    /// 根据选中状态为当前视图补充无障碍选中语义，未选中时保持原有特征不变。
    @ViewBuilder
    func xAgeAccessibilitySelected(_ isSelected: Bool) -> some View {
        if isSelected {
            accessibilityAddTraits(.isSelected)
        } else {
            self
        }
    }

    /// 按需为视图添加按钮无障碍特征，避免纯展示内容被读屏误识别为可点击控件。
    @ViewBuilder
    func xAgeAccessibilityButton(_ isButton: Bool) -> some View {
        if isButton {
            accessibilityAddTraits(.isButton)
        } else {
            self
        }
    }

    /// 根据排序模式切换指标卡片的无障碍结构：排序时保留子控件，浏览时合并为单个按钮。
    @ViewBuilder
    func xAgeMetricCardAccessibility(sortMode: Bool, label: String, hint: String) -> some View {
        if sortMode {
            accessibilityElement(children: .contain)
        } else {
            accessibilityElement(children: .ignore)
                .accessibilityAddTraits(.isButton)
                .accessibilityLabel(label)
                .accessibilityHint(hint)
        }
    }
}

@MainActor
/// 统一收起当前第一响应者，供分页切换、关闭菜单和提交表单时复用。
private enum XAgeKeyboard {
    /// 主动结束当前输入焦点并收起系统键盘。
    static func dismiss() {
        UIApplication.shared.sendAction(
            #selector(UIResponder.resignFirstResponder),
            to: nil,
            from: nil,
            for: nil
        )
    }
}

@MainActor
/// 将 UIKit 下拉手势安装到 SwiftUI 背后的滚动视图。
/// 用户明显向下拖动时主动收起键盘，同时允许原滚动手势继续识别，不改变列表的滚动行为。
private struct XAgeVerticalKeyboardDismissInstaller: UIViewRepresentable {
    let onDismiss: () -> Void

    /// 创建 SwiftUI 与 UIKit 手势交互之间的协调器。
    func makeCoordinator() -> Coordinator {
        Coordinator(onDismiss: onDismiss)
    }

    /// 创建并配置由 SwiftUI 托管的 UIKit 容器视图。
    func makeUIView(context: Context) -> UIView {
        let view = UIView(frame: .zero)
        view.isUserInteractionEnabled = false
        context.coordinator.install(from: view)
        return view
    }

    /// 在 SwiftUI 状态变化时同步更新 UIKit 容器的配置。
    func updateUIView(_ uiView: UIView, context: Context) {
        context.coordinator.onDismiss = onDismiss
        context.coordinator.install(from: uiView)
    }

    /// 在 UIKit 容器移除前释放手势和协调器持有的资源。
    static func dismantleUIView(_ uiView: UIView, coordinator: Coordinator) {
        coordinator.invalidate()
    }

    final class Coordinator: NSObject, UIGestureRecognizerDelegate {
        var onDismiss: () -> Void
        private weak var installedScrollView: UIScrollView?
        private var didDismiss = false
        private var isActive = true
        private lazy var panGesture: UIPanGestureRecognizer = {
            let gesture = UIPanGestureRecognizer(target: self, action: #selector(handlePan(_:)))
            gesture.cancelsTouchesInView = false
            gesture.delegate = self
            return gesture
        }()

        /// 保存键盘收起回调，供后续安装的下拉手势统一触发。
        init(onDismiss: @escaping () -> Void) {
            self.onDismiss = onDismiss
        }

        /// 安装 `install` 所需的手势监听，并绑定到合适的 UIKit 视图。
        func install(from view: UIView) {
            DispatchQueue.main.async { [weak self, weak view] in
                guard let self, let view else { return }
                guard self.isActive else { return }
                var ancestor = view.superview
                while let current = ancestor {
                    if let scrollView = current as? UIScrollView {
                        guard self.installedScrollView !== scrollView else { return }
                        self.detach()
                        scrollView.addGestureRecognizer(self.panGesture)
                        self.installedScrollView = scrollView
                        return
                    }
                    ancestor = current.superview
                }
            }
        }

        /// 结束 `detach` 对应的交互或资源监听，并清理临时状态。
        func detach() {
            installedScrollView?.removeGestureRecognizer(panGesture)
            installedScrollView = nil
        }

        /// 结束 `invalidate` 对应的交互或资源监听，并清理临时状态。
        func invalidate() {
            isActive = false
            detach()
        }

        /// 根据当前页面交互状态判断手势识别器是否应响应或并行工作。
        func gestureRecognizerShouldBegin(_ gestureRecognizer: UIGestureRecognizer) -> Bool {
            guard let pan = gestureRecognizer as? UIPanGestureRecognizer else { return false }
            let velocity = pan.velocity(in: pan.view)
            return velocity.y > 0 && abs(velocity.y) > abs(velocity.x) * 1.2
        }

        /// 根据当前页面交互状态判断手势识别器是否应响应或并行工作。
        func gestureRecognizer(
            _ gestureRecognizer: UIGestureRecognizer,
            shouldRecognizeSimultaneouslyWith otherGestureRecognizer: UIGestureRecognizer
        ) -> Bool {
            true
        }

        /// 处理 `handlePan` 对应的用户操作或系统回调，并推进后续流程。
        @objc private func handlePan(_ gesture: UIPanGestureRecognizer) {
            switch gesture.state {
            case .began:
                didDismiss = false
            case .changed:
                guard !didDismiss, gesture.translation(in: gesture.view).y > 20 else { return }
                didDismiss = true
                onDismiss()
            case .ended, .cancelled, .failed:
                didDismiss = false
            default:
                break
            }
        }
    }
}

// MARK: - 数据卡片偏好与账号隔离

/// 数据页卡片布局的持久化快照：区分“用户从未编辑”与“用户主动保存了空列表”两种情况。
struct XAgeDataCardPreferenceSnapshot {
    var isCustomized: Bool
    var ids: [String]
}

@MainActor
/// 按账号保存数据卡片顺序，只持久化指标 ID，不缓存任何健康指标值。
/// 真实数值始终由 Apple Health 或服务端重新合并，避免账号切换时带出上一账号的数据。
enum XAgeDataCardPreferences {
    private static let idsKey = "xage.data.card.ids.v1"
    private static let customizedKey = "xage.data.card.customized.v1"
    private static let scopedIDsKeyPrefix = "xage.data.card.ids.v2."
    private static let scopedCustomizedKeyPrefix = "xage.data.card.customized.v2."
    private static let resetArgument = "XJIE_UI_TEST_RESET_DATA_CARDS"
    #if DEBUG
    private static var didApplyUITestReset = false
    #endif

    /// 加载或请求 `load` 所需的数据，并返回整理后的结果。
    static func load(accountScope: String?) -> XAgeDataCardPreferenceSnapshot {
        #if DEBUG
        if shouldResetForUITest(), !didApplyUITestReset {
            reset()
            didApplyUITestReset = true
        }
        #endif
        guard let accountScope, !accountScope.isEmpty else {
            return XAgeDataCardPreferenceSnapshot(isCustomized: false, ids: [])
        }
        let token = storageToken(for: accountScope)
        let scopedIDsKey = scopedIDsKeyPrefix + token
        let scopedCustomizedKey = scopedCustomizedKeyPrefix + token
        if UserDefaults.standard.object(forKey: scopedCustomizedKey) != nil {
            return XAgeDataCardPreferenceSnapshot(
                isCustomized: UserDefaults.standard.bool(forKey: scopedCustomizedKey),
                ids: UserDefaults.standard.stringArray(forKey: scopedIDsKey) ?? []
            )
        }

        // 旧版全局偏好只保存布局 ID，不含指标值；首次读取时可安全迁移到当前账号。
        // 迁移仅用于保留用户的排列习惯，不会携带任何健康数据。
        let legacy = XAgeDataCardPreferenceSnapshot(
            isCustomized: UserDefaults.standard.bool(forKey: customizedKey),
            ids: UserDefaults.standard.stringArray(forKey: idsKey) ?? []
        )
        if legacy.isCustomized {
            UserDefaults.standard.set(dedupedIDs(legacy.ids), forKey: scopedIDsKey)
            UserDefaults.standard.set(true, forKey: scopedCustomizedKey)
        }
        // 旧布局只能迁移一次。迁移后立即删除全局键，后续登录的其他账号会从自己的布局开始。
        UserDefaults.standard.removeObject(forKey: idsKey)
        UserDefaults.standard.removeObject(forKey: customizedKey)
        return legacy
    }

    /// 读取账号级卡片偏好，并据此生成数据页首帧使用的指标占位列表。
    static func initialMetrics(accountScope: String?) -> [XAgeMetric] {
        let snapshot = load(accountScope: accountScope)
        return placeholderMetrics(for: snapshot)
    }

    /// 将偏好快照中的指标 ID 转换为保持用户顺序的占位卡片。
    static func placeholderMetrics(for snapshot: XAgeDataCardPreferenceSnapshot) -> [XAgeMetric] {
        guard snapshot.isCustomized else { return XAgeMetric.defaultCards }
        return orderedMetrics(for: snapshot, from: XAgeMetric.catalogSections(serverMetrics: []).flatMap(\.metrics))
    }

    /// 保存 `save` 对应的数据，并同步持久化后的页面状态。
    @discardableResult
    static func save(metrics: [XAgeMetric], accountScope: String?) -> XAgeDataCardPreferenceSnapshot {
        let ids = dedupedIDs(metrics.map(\.id))
        if let accountScope, !accountScope.isEmpty {
            let token = storageToken(for: accountScope)
            UserDefaults.standard.set(ids, forKey: scopedIDsKeyPrefix + token)
            UserDefaults.standard.set(true, forKey: scopedCustomizedKeyPrefix + token)
        }
        return XAgeDataCardPreferenceSnapshot(isCustomized: true, ids: ids)
    }

    /// 先按偏好顺序选择可用指标，再追加未记录在偏好中的新指标。
    static func orderedMetrics(for snapshot: XAgeDataCardPreferenceSnapshot, from source: [XAgeMetric]) -> [XAgeMetric] {
        guard snapshot.isCustomized else { return dedupedMetrics(source) }
        let lookup = firstMetricByID(from: source)
        return snapshot.ids.compactMap { lookup[$0] }
    }

    /// 按指标 ID 建立首个有效卡片索引，并按优先级处理同 ID 的重复数据。
    private static func firstMetricByID(from source: [XAgeMetric]) -> [String: XAgeMetric] {
        var lookup: [String: XAgeMetric] = [:]
        for metric in source {
            if let existing = lookup[metric.id] {
                if shouldPrefer(metric, over: existing) {
                    lookup[metric.id] = metric
                }
            } else {
                lookup[metric.id] = metric
            }
        }
        return lookup
    }

    /// 校验 `shouldPrefer` 对应的条件，决定数据或操作是否可以继续使用。
    private static func shouldPrefer(_ candidate: XAgeMetric, over existing: XAgeMetric) -> Bool {
        if existing.isPlaceholder != candidate.isPlaceholder {
            return !candidate.isPlaceholder
        }
        let existingSource = existing.source ?? ""
        let candidateSource = candidate.source ?? ""
        let existingIsCatalog = existingSource.contains("catalog")
        let candidateIsCatalog = candidateSource.contains("catalog")
        if existingIsCatalog != candidateIsCatalog {
            return !candidateIsCatalog
        }
        if existingSource == "server_catalog", candidateSource == "server_indicator_catalog" {
            return true
        }
        return false
    }

    /// 整理 `dedupedMetrics` 涉及的集合内容、顺序或去重结果。
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

    /// 整理 `dedupedIDs` 涉及的集合内容、顺序或去重结果。
    private static func dedupedIDs(_ ids: [String]) -> [String] {
        var seen = Set<String>()
        return ids.filter { seen.insert($0).inserted }
    }

    #if DEBUG
    /// 校验 `shouldResetForUITest` 对应的条件，决定数据或操作是否可以继续使用。
    private static func shouldResetForUITest() -> Bool {
        let environment = ProcessInfo.processInfo.environment
        if let value = environment[resetArgument], ["1", "true", "YES", "yes"].contains(value) {
            return true
        }
        return ProcessInfo.processInfo.arguments.contains(resetArgument)
    }
    #endif

    /// 重置 `reset` 管理的缓存、偏好或临时状态。
    private static func reset() {
        UserDefaults.standard.removeObject(forKey: idsKey)
        UserDefaults.standard.removeObject(forKey: customizedKey)
        for key in UserDefaults.standard.dictionaryRepresentation().keys
            where key.hasPrefix(scopedIDsKeyPrefix) || key.hasPrefix(scopedCustomizedKeyPrefix) {
            UserDefaults.standard.removeObject(forKey: key)
        }
    }

    /// 将账号作用域转换为安全稳定的存储键片段，隔离不同账号的卡片偏好。
    private static func storageToken(for accountScope: String) -> String {
        Data(accountScope.utf8).base64EncodedString()
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "=", with: "")
    }

    #if DEBUG
    /// 重置 `resetForTesting` 管理的缓存、偏好或临时状态。
    static func resetForTesting() {
        reset()
        didApplyUITestReset = false
    }
    #endif
}

/// Apple Health 的所有显式入口都经由同一条同步链路，保证本地读取/上传完成后
/// 一定刷新服务端快照。闭包形式也让账号隔离和刷新顺序可以在单元测试中验证。
@MainActor
enum XAgeAppleHealthSyncFlow {
    /// 同步 `synchronize` 涉及的本地与远端数据，并保持展示状态一致。
    @discardableResult
    static func synchronize(
        accountScope: String?,
        configureAccount: (String?) -> Void,
        synchronizeHealth: () async -> Void,
        refreshServer: () async -> Void
    ) async -> Bool {
        configureAccount(accountScope)
        guard accountScope != nil else { return false }
        await synchronizeHealth()
        await refreshServer()
        return true
    }
}

/// 汇总算法所需的 Apple Health 指标与用户关注指标，并按不区分大小写的名称去重。
/// 服务端趋势接口会使用这份名单，因此这里是“可同步指标”和“趋势卡片”的连接点。
enum XAgeHealthTrendRequestContract {
    /// 合并默认趋势名和用户关注指标名，规范化后去重为服务端请求参数。
    static func names(watchedNames: [String]) -> [String] {
        let supportedAppleHealthNames = AppleHealthStore.metricRegistry
            .filter(\.isSupported)
            .map(\.indicatorName)
        var seen = Set<String>()
        return (supportedAppleHealthNames + watchedNames).compactMap { name in
            let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !trimmed.isEmpty else { return nil }
            let key = trimmed.lowercased()
            guard seen.insert(key).inserted else { return nil }
            return trimmed
        }
    }
}

/// 把服务端指标名映射回 Apple Health 注册表，用于分类值显示和数据时效判断。
/// 不同查询类型采用不同的新鲜度窗口，过期值仍保留为历史数据，但不会被当作当前状态。
enum XAgeHealthMetricRegistryContract {
    private static let categoryMetricIDs: Set<String> = [
        "menstrualFlow",
        "intermenstrualBleeding",
        "cervicalMucus",
        "ovulationTest",
        "sexualActivity"
    ]
    private static let longLivedBodyMetricIDs: Set<String> = [
        "bodyHeight",
        "bodyMassIndex",
        "leanBodyMass",
        "waistCircumference"
    ]

    /// 将服务端指标名称映射为客户端稳定的指标 ID，供卡片合并和偏好存储使用。
    static func metricID(forIndicatorName indicatorName: String) -> String? {
        identifierByIndicatorName[normalize(indicatorName)]
    }

    /// 计算 `categoryDisplayValue` 对应的评分、状态或展示值。
    static func categoryDisplayValue(forIndicatorName indicatorName: String, value: Double) -> String? {
        guard value.isFinite,
              value.rounded() == value,
              let metricID = metricID(forIndicatorName: indicatorName),
              categoryMetricIDs.contains(metricID) else {
            return nil
        }
        return AppleHealthStore.categoryDisplayValue(metricID: metricID, value: Int(value))
    }

    /// 计算 `freshnessLimitDays` 对应的评分、状态或展示值。
    static func freshnessLimitDays(forIndicatorName indicatorName: String) -> Int? {
        guard let metricID = metricID(forIndicatorName: indicatorName),
              let definition = definitionByMetricID[metricID] else {
            return nil
        }
        if longLivedBodyMetricIDs.contains(metricID) {
            return 180
        }
        switch definition.query {
        case .cumulativeToday, .durationToday, .sleep:
            return 2
        case .latest:
            return 14
        case .latestCategory:
            return 30
        case .unsupported:
            return 180
        }
    }

    private static let identifierByIndicatorName: [String: String] = {
        var result: [String: String] = [:]
        for definition in AppleHealthStore.metricRegistry {
            result[normalize(definition.indicatorName)] = definition.metricID
        }
        return result
    }()

    private static let definitionByMetricID: [String: AppleHealthMetricDefinition] = {
        var result: [String: AppleHealthMetricDefinition] = [:]
        for definition in AppleHealthStore.metricRegistry {
            result[definition.metricID] = definition
        }
        return result
    }()

    /// 规范化 `normalize` 的输入值，并返回可安全参与后续计算的结果。
    private static func normalize(_ value: String) -> String {
        value.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    }
}

/// 账号维度的异步刷新闸门。
/// 每次账号切换都会递增 generation；旧请求即使稍后返回，也必须同时匹配账号和 generation 才能写回页面。
struct XAgeAccountScopedRefreshGate: Equatable {
    private(set) var accountScope: String?
    private(set) var generation = 0

    /// 更新 `switchAccount` 对应的配置或状态，并处理必要的联动。
    @discardableResult
    mutating func switchAccount(to scope: String?) -> Bool {
        let normalized = Self.normalize(scope)
        guard normalized != accountScope else { return false }
        accountScope = normalized
        generation += 1
        return true
    }

    /// 校验 `accepts` 对应的条件，决定数据或操作是否可以继续使用。
    func accepts(startedScope: String, generation startedGeneration: Int, currentScope: String?) -> Bool {
        accountScope == startedScope
            && generation == startedGeneration
            && Self.normalize(currentScope) == startedScope
    }

    /// 规范化 `normalize` 的输入值，并返回可安全参与后续计算的结果。
    private static func normalize(_ scope: String?) -> String? {
        guard let value = scope?.trimmingCharacters(in: .whitespacesAndNewlines),
              !value.isEmpty else {
            return nil
        }
        return value
    }
}

// MARK: - XAGE 主页面

/// 新版 XAGE 的页面总容器，统一承载“数据、问答、X年龄”三段内容和设置入口。
/// 页面级服务在这里创建并按账号配置，确保三个分页看到的是同一份 Apple Health 状态和服务端快照。
struct XAgeMainView: View {
    @Environment(\.scenePhase) private var scenePhase
    @EnvironmentObject private var externalReportImport: XAgeExternalReportImportRouter
    @EnvironmentObject private var authManager: AuthManager
    @StateObject private var appleHealthSync = AppleHealthSyncViewModel()
    @StateObject private var serverSync = XAgeServerSyncViewModel()
    @StateObject private var externalReportUploadVM = HealthDataViewModel()
    // 一级分页、资料分类和弹层状态都由根页面集中协调，避免子页面之间直接互相依赖。
    @State private var selectedSection: XAgeTopSection = Self.initialSection()
    @State private var selectedDataPanelCategory: XAgeDataPanelCategory = .reports
    @State private var showMoreMenu = false
    @State private var dataSortMode = false
    @State private var chatHistoryRequest = 0
    @State private var xAgeInfoRequest = 0
    @State private var pendingExternalUpload: XAgePendingReportUpload?
    @State private var externalImportError: String?
    @State private var configuredAppleHealthAccountScope: String?
    @State private var hasConfiguredAppleHealthAccountScope = false

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
    var body: some View {
        NavigationStack {
            ZStack {
                XAgeLiquidBackground()
                    .ignoresSafeArea()

                VStack(spacing: 0) {
                    XAgeTopBar(
                        selected: $selectedSection,
                        showMoreMenu: $showMoreMenu,
                        dataSortMode: dataSortMode,
                        onToggleDataSort: {
                            withAnimation(.spring(response: 0.28, dampingFraction: 0.88)) {
                                dataSortMode.toggle()
                            }
                        },
                        onOpenChatHistory: {
                            chatHistoryRequest += 1
                        },
                        onOpenXAgeInfo: {
                            xAgeInfoRequest += 1
                        }
                    )
                    .padding(.top, 12)
                    .padding(.horizontal, 24)
                    .zIndex(2)

                    // 顶栏和 TabView 共享 selectedSection：点击标题或横向翻页都会更新同一导航状态。
                    TabView(selection: $selectedSection) {
                        XAgeDataDashboardView(
                            sortMode: $dataSortMode,
                            appleHealthSync: appleHealthSync,
                            serverSync: serverSync,
                            scores: compositeScores,
                            accountScope: authManager.accountScope,
                            onSyncAppleHealth: syncAppleHealthAndRefreshServer,
                            onOpenMetricGuide: openMetricGuide
                        )
                            .id(authManager.accountScope ?? "logged-out")
                            .tag(XAgeTopSection.data)

                        XAgeConversationSurface(
                            selectedSection: $selectedSection,
                            historyRequest: chatHistoryRequest
                        )
                            .tag(XAgeTopSection.chat)

                        XAgeHealthspanView(
                            selectedSection: $selectedSection,
                            infoRequest: xAgeInfoRequest,
                            scores: compositeScores
                        )
                            .tag(XAgeTopSection.xAge)
                    }
                    .tabViewStyle(.page(indexDisplayMode: .never))
                    .accessibilityIdentifier("xage.section.content")
                }
            }
            .navigationBarHidden(true)
            .onChange(of: selectedSection) { _, section in
                if section != .data, dataSortMode {
                    dataSortMode = false
                }
            }
            .sheet(isPresented: $showMoreMenu) {
                // “更多”同时承担资料入口和账号设置；子页面关闭后仍回到当前一级分页。
                XAgeMoreMenu(
                    selectedCategory: $selectedDataPanelCategory,
                    appleHealthSync: appleHealthSync,
                    snapshot: serverSync.snapshot,
                    onSyncAppleHealth: syncAppleHealthAndRefreshServer,
                    onSelectCategory: selectPanelCategory,
                    onClose: { showMoreMenu = false }
                )
                    .presentationDetents([.large])
            }
            .sheet(item: $pendingExternalUpload) { upload in
                // 系统外部导入必须先由用户确认，只有确认后才真正上传到健康资料库。
                XAgeReportUploadConfirmSheet(
                    upload: upload,
                    isUploading: externalReportUploadVM.uploading,
                    onCancel: { pendingExternalUpload = nil },
                    onConfirm: {
                        pendingExternalUpload = nil
                        uploadExternalReports(upload.files)
                    }
                )
                .presentationDetents([.medium, .large])
                .presentationDragIndicator(.visible)
            }
            .alert("导入失败", isPresented: Binding(
                get: { externalImportError != nil },
                set: { if !$0 { externalImportError = nil } }
            )) {
                Button("知道了", role: .cancel) {}
            } message: {
                Text(externalImportError ?? "")
            }
            .alert("上传提示", isPresented: Binding(
                get: { externalReportUploadVM.infoMessage != nil },
                set: { if !$0 { externalReportUploadVM.infoMessage = nil } }
            )) {
                Button("知道了", role: .cancel) {}
            } message: {
                Text(externalReportUploadVM.infoMessage ?? "")
            }
            .alert("上传失败", isPresented: Binding(
                get: { externalReportUploadVM.errorMessage != nil },
                set: { if !$0 { externalReportUploadVM.errorMessage = nil } }
            )) {
                Button("确定", role: .cancel) {}
            } message: {
                Text(externalReportUploadVM.errorMessage ?? "")
            }
            .onAppear {
                // 首次显示时先绑定当前账号，再消费可能由系统入口传入的文件，最后刷新页面快照。
                configureAppleHealthAccountScope(authManager.accountScope)
                handlePendingExternalImportIfNeeded()
                Task { await refreshXAgeDataFromAppLifecycle() }
            }
            .onChange(of: scenePhase) { _, phase in
                // 回到前台时只刷新已授权/已同步的数据，不在后台阶段主动弹权限请求。
                guard phase == .active else { return }
                Task { await refreshXAgeDataFromAppLifecycle() }
            }
            .onChange(of: externalReportImport.pendingImport) { _, _ in
                handlePendingExternalImportIfNeeded()
            }
            .onChange(of: selectedSection) { _, _ in
                XAgeKeyboard.dismiss()
            }
            .onChange(of: showMoreMenu) { _, isPresented in
                if isPresented {
                    XAgeKeyboard.dismiss()
                }
            }
            .onChange(of: authManager.accountScope) { _, accountScope in
                // 切换账号会重置两个同步服务的作用域，旧账号尚未结束的请求会被 refresh gate 丢弃。
                configureAppleHealthAccountScope(accountScope)
                Task { await refreshXAgeDataFromAppLifecycle() }
            }
        }
    }

    private var compositeScores: XAgeCompositeScores {
        // 评分是服务端快照与本地 Apple Health 样本的纯计算结果，不在 View 中额外缓存，避免数据更新后显示旧分数。
        XAgeCompositeScores.compute(
            context: XAgeAlgorithmContext(
                snapshot: serverSync.snapshot,
                samples: appleHealthSync.samples
            )
        )
    }

    /// 响应 `selectPanelCategory` 对应的页面选择、展示或交互状态切换。
    private func selectPanelCategory(_ category: XAgeDataPanelCategory) {
        // 从设置选择资料分类时先切回数据页；具体分类详情由设置菜单自己的全屏页面展示。
        selectedDataPanelCategory = category
        dataSortMode = false
        withAnimation(.spring(response: 0.3, dampingFraction: 0.86)) {
            selectedSection = .data
        }
    }

    /// 响应 `openMetricGuide` 对应的页面选择、展示或交互状态切换。
    private func openMetricGuide(_ kind: XAgeDataKind) {
        // 缺失数据引导会根据评分类型选择最相关的资料分类，再打开统一的更多菜单。
        dataSortMode = false
        selectedDataPanelCategory = kind == .inflammation ? .reports : .daily
        showMoreMenu = true
    }

    /// 刷新 `refreshXAgeDataFromAppLifecycle` 对应的数据源，并同步页面所依赖的状态。
    private func refreshXAgeDataFromAppLifecycle() async {
        // 生命周期刷新遵循“恢复本地已同步数据 → 拉取服务端聚合快照”的顺序。
        // 未登录或账号尚未确定时直接停止，避免健康数据落入无账号作用域。
        let accountScope = authManager.accountScope
        configureAppleHealthAccountScope(accountScope)
        guard accountScope != nil else { return }
        await appleHealthSync.refreshIfPreviouslySynced()
        await serverSync.refresh()
    }

    /// 同步 `syncAppleHealthAndRefreshServer` 涉及的本地与远端数据，并保持展示状态一致。
    private func syncAppleHealthAndRefreshServer() async {
        // 用户主动同步时统一走同步协调器：绑定账号、读取并上传 HealthKit、随后刷新服务端趋势和评分。
        let accountScope = authManager.accountScope
        let didStart = await XAgeAppleHealthSyncFlow.synchronize(
            accountScope: accountScope,
            configureAccount: configureAppleHealthAccountScope,
            synchronizeHealth: { await appleHealthSync.requestAccessAndSync() },
            refreshServer: { await serverSync.refresh() }
        )
        if !didStart {
            appleHealthSync.status = .failed("无法确认当前账号，请重新登录后再同步 Apple 健康。")
        }
    }

    /// 更新 `configureAppleHealthAccountScope` 对应的配置或状态，并处理必要的联动。
    private func configureAppleHealthAccountScope(_ accountScope: String?) {
        // 账号没有变化时不重复启动后台协调器；变化时必须先停止旧账号任务，再切换两个 ViewModel 的数据作用域。
        guard !hasConfiguredAppleHealthAccountScope || configuredAppleHealthAccountScope != accountScope else {
            return
        }
        let coordinator = AppleHealthBackgroundSyncCoordinator.shared
        coordinator.stop()
        appleHealthSync.setAccountScope(accountScope)
        serverSync.setAccountScope(accountScope)
        coordinator.startIfEligible(accountScope: accountScope)
        configuredAppleHealthAccountScope = accountScope
        hasConfiguredAppleHealthAccountScope = true
    }

    /// 处理 `handlePendingExternalImportIfNeeded` 对应的用户操作或系统回调，并推进后续流程。
    private func handlePendingExternalImportIfNeeded() {
        // 先按 ID 标记已消费，再异步读取文件；即使读取失败，SwiftUI 重绘也不会重复处理同一个 URL。
        guard let item = externalReportImport.pendingImport else { return }
        externalReportImport.markHandled(item.id)
        Task { await prepareExternalReportImport(item.url) }
    }

    /// 准备 `prepareExternalReportImport` 后续流程所需的数据和页面状态。
    private func prepareExternalReportImport(_ url: URL) async {
        // 来自 Files 或其他 App 的 URL 可能受安全作用域保护，只在读取期间持有访问权限。
        let access = url.startAccessingSecurityScopedResource()
        defer {
            if access {
                url.stopAccessingSecurityScopedResource()
            }
        }

        do {
            let data = try Data(contentsOf: url)
            guard !data.isEmpty else {
                externalImportError = "文件为空，无法上传。"
                return
            }
            let fileName = url.lastPathComponent.isEmpty ? "外部导入报告" : url.lastPathComponent
            // 外部文件与相机/相册来源统一转换为待上传模型，后续复用相同的确认和上传界面。
            let file = XAgeReportUploadFile(data: data, fileName: fileName)
            pendingExternalUpload = XAgePendingReportUpload(
                title: "确认导入报告",
                source: "打开方式",
                files: [file]
            )
            selectedSection = .data
            selectedDataPanelCategory = .reports
        } catch {
            externalImportError = "无法读取该文件：\(error.localizedDescription)"
        }
    }

    /// 执行 `uploadExternalReports` 对应的文件上传，并衔接上传后的刷新或分析。
    private func uploadExternalReports(_ files: [XAgeReportUploadFile]) {
        // 外部导入按体检报告类型逐个上传；全部提交完成后刷新服务端快照，让报告数量和指标尽快更新。
        guard !files.isEmpty else { return }
        externalReportUploadVM.uploadDocType = "exam"
        Task {
            for file in files {
                _ = await externalReportUploadVM.uploadFile(data: file.data, fileName: file.fileName)
            }
            await serverSync.refresh()
        }
    }

    /// 读取 UI 测试启动参数决定初始分页，普通启动默认进入数据页。
    private static func initialSection() -> XAgeTopSection {
        #if DEBUG
        if let rawValue = ProcessInfo.processInfo.environment["XAGE_INITIAL_SECTION"] ?? launchArgumentValue(for: "XAGE_INITIAL_SECTION"),
           let section = XAgeTopSection.section(matching: rawValue) {
            return section
        }
        #endif
        return .data
    }

    #if DEBUG
    /// 计算 `launchArgumentValue` 对应的评分、状态或展示值。
    private static func launchArgumentValue(for key: String) -> String? {
        let arguments = ProcessInfo.processInfo.arguments
        for (index, argument) in arguments.enumerated() {
            if argument == key, arguments.indices.contains(index + 1) {
                return arguments[index + 1]
            }
            if argument.hasPrefix("\(key)=") {
                return String(argument.dropFirst(key.count + 1))
            }
        }
        return nil
    }
    #endif
}

#if DEBUG
private extension XAgeTopSection {
    /// 将外部字符串解析为对应的 XAGE 顶部分页，兼容名称与测试参数写法。
    static func section(matching value: String) -> XAgeTopSection? {
        switch value {
        case "data", "数据":
            return .data
        case "chat", "qa", "问答":
            return .chat
        case "xAge", "xage", "X年龄":
            return .xAge
        default:
            return nil
        }
    }
}
#endif

// MARK: - 顶部导航栏

private struct XAgeTopBar: View {
    @Binding var selected: XAgeTopSection
    @Binding var showMoreMenu: Bool
    let dataSortMode: Bool
    let onToggleDataSort: () -> Void
    let onOpenChatHistory: () -> Void
    let onOpenXAgeInfo: () -> Void

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
    var body: some View {
        HStack(spacing: 8) {
            Button {
                XAgeKeyboard.dismiss()
                showMoreMenu = true
            } label: {
                Image(systemName: "line.3.horizontal")
                    .font(.system(size: 18, weight: .semibold))
                    .frame(width: 44, height: 44)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .foregroundStyle(Color(hex: "173F64"))
            .accessibilityLabel("资料菜单")
            .accessibilityIdentifier("xage.more")

            HStack(spacing: 0) {
                ForEach(XAgeTopSection.allCases) { section in
                    Button {
                        XAgeKeyboard.dismiss()
                        withAnimation(.spring(response: 0.32, dampingFraction: 0.86)) {
                            selected = section
                        }
                    } label: {
                        Text(section.rawValue)
                            .font(.system(size: 15, weight: selected == section ? .bold : .medium))
                            .foregroundStyle(selected == section ? Color(hex: "1268BD") : Color(hex: "4E718E"))
                            .lineLimit(1)
                            .minimumScaleFactor(0.78)
                            .frame(maxWidth: .infinity)
                            .frame(height: 44)
                            .contentShape(Rectangle())
                    }
                    .accessibilityIdentifier("xage.segment.\(section.id)")
                    .accessibilityLabel(section.rawValue)
                    .xAgeAccessibilitySelected(selected == section)
                    .buttonStyle(.plain)
                    .background {
                        if selected == section {
                            RoundedRectangle(cornerRadius: 22, style: .continuous)
                                .fill(.white.opacity(0.72))
                                .overlay(
                                    RoundedRectangle(cornerRadius: 22, style: .continuous)
                                        .stroke(.white.opacity(0.92), lineWidth: 1)
                                )
                                .shadow(color: Color(hex: "2FB6E3").opacity(0.16), radius: 16, x: 0, y: 8)
                        }
                    }
                }
            }
            .frame(maxWidth: .infinity)
            .frame(height: 48)
            .background(
                RoundedRectangle(cornerRadius: 24, style: .continuous)
                    .fill(.white.opacity(0.48))
                    .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 24, style: .continuous))
                    .overlay(
                        RoundedRectangle(cornerRadius: 24, style: .continuous)
                            .stroke(.white.opacity(0.86), lineWidth: 1)
                    )
                    .shadow(color: Color(hex: "7CCAF5").opacity(0.16), radius: 22, x: 0, y: 10)
            )

            if selected == .xAge {
                Button {
                    onOpenXAgeInfo()
                } label: {
                    Image(systemName: "info.circle.fill")
                        .font(.system(size: 18, weight: .bold))
                        .frame(width: 44, height: 44)
                        .background(XAgeCapsuleFill())
                }
                .buttonStyle(.plain)
                .foregroundStyle(Color(hex: "18AFA7"))
                .accessibilityLabel("X年龄原理")
                .accessibilityIdentifier("xage.xage.info.top")
            } else {
                Button {
                    if selected == .data {
                        onToggleDataSort()
                    } else if selected == .chat {
                        onOpenChatHistory()
                    }
                } label: {
                    Group {
                        if selected == .data {
                            Text(dataSortMode ? "完成" : "排序")
                                .font(.system(size: 14, weight: .bold))
                                .frame(width: 52, height: 44)
                        } else {
                            Image(systemName: "clock.arrow.circlepath")
                                .font(.system(size: 18, weight: .bold))
                                .frame(width: 44, height: 44)
                        }
                    }
                    .background(
                        Capsule()
                            .fill(.white.opacity(0.48))
                            .overlay(Capsule().stroke(.white.opacity(0.86), lineWidth: 1))
                    )
                }
                .buttonStyle(.plain)
                .foregroundStyle(selected == .chat ? Color(hex: "173F64") : Color(hex: "2A79BB"))
                .accessibilityLabel(selected == .data ? (dataSortMode ? "完成排序" : "排序数据卡片") : "历史对话")
                .accessibilityIdentifier(selected == .data ? (dataSortMode ? "xage.data.sort.done" : "xage.data.sort") : "xage.chat.history")
            }
        }
    }
}


// MARK: - 数据首页与指标卡片

/// 数据分页的状态容器：展示综合评分、Apple Health 状态和用户置顶的指标卡片。
/// 本地样本、服务端趋势和账号偏好会在这里合并成最终可见的卡片列表。
private struct XAgeDataDashboardView: View {
    @Binding var sortMode: Bool
    @ObservedObject var appleHealthSync: AppleHealthSyncViewModel
    @ObservedObject var serverSync: XAgeServerSyncViewModel
    let scores: XAgeCompositeScores
    let accountScope: String?
    let onSyncAppleHealth: () async -> Void
    let onOpenMetricGuide: (XAgeDataKind) -> Void
    @State private var activeSheet: XAgeDataSheet?
    @State private var showsMetricManager = false
    @State private var metrics: [XAgeMetric]
    @State private var metricPreference: XAgeDataCardPreferenceSnapshot
    @State private var pendingMetricScrollID: String?
    @State private var isTodayStatusHidden = false

    /// 注入数据页依赖，并依据当前账号偏好建立首帧指标卡片顺序和占位状态。
    init(
        sortMode: Binding<Bool>,
        appleHealthSync: AppleHealthSyncViewModel,
        serverSync: XAgeServerSyncViewModel,
        scores: XAgeCompositeScores,
        accountScope: String?,
        onSyncAppleHealth: @escaping () async -> Void,
        onOpenMetricGuide: @escaping (XAgeDataKind) -> Void
    ) {
        self._sortMode = sortMode
        self.appleHealthSync = appleHealthSync
        self.serverSync = serverSync
        self.scores = scores
        self.accountScope = accountScope
        self.onSyncAppleHealth = onSyncAppleHealth
        self.onOpenMetricGuide = onOpenMetricGuide
        // 首帧先按账号偏好生成占位卡片，真实数据到达后保留顺序并替换占位值。
        self._metrics = State(initialValue: XAgeDataCardPreferences.initialMetrics(accountScope: accountScope))
        self._metricPreference = State(initialValue: XAgeDataCardPreferences.load(accountScope: accountScope))
    }

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
    var body: some View {
        VStack(spacing: 0) {
            stickyHeader
            metricsScroll
        }
        .safeAreaInset(edge: .bottom) { sortDoneInset }
        .onChange(of: appleHealthSync.samples) { _, samples in
            // HealthKit 样本变化时只合并匹配指标，不覆盖用户已经保存的卡片顺序。
            mergeAppleHealthSamples(samples)
        }
        .onReceive(serverSync.$metricCards) { cards in
            mergeServerMetrics(cards)
        }
        .onReceive(serverSync.$indicatorCatalogCards) { _ in
            restoreMetricPreferencesFromAvailableCatalog()
        }
        .onChange(of: accountScope) { _, newScope in
            // 账号切换时立即关闭详情和排序状态，并加载新账号自己的卡片布局。
            resetMetrics(for: newScope)
        }
        .task {
            await refreshAllData(includeAppleHealth: true)
        }
        .navigationDestination(isPresented: $showsMetricManager) {
            XAgeMetricManagerPage(
                pinnedMetrics: $metrics,
                catalogSections: metricCatalogSections,
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

    /// 构建 `stickyHeader` 对应的局部 SwiftUI 视图，并组合所需的展示状态与交互。
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

    /// 构建 `metricsScroll` 对应的局部 SwiftUI 视图，并组合所需的展示状态与交互。
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
            .onChange(of: sortMode) { _, isSorting in
                scrollToFirstMetricIfNeeded(isSorting: isSorting, proxy: proxy)
            }
        }
    }

    /// 构建 `metricList` 对应的局部 SwiftUI 视图，并组合所需的展示状态与交互。
    private var metricList: some View {
        LazyVStack(spacing: 12) {
            if !sortMode {
                XAgeAppleHealthSyncCard(
                    viewModel: appleHealthSync,
                    onSyncAppleHealth: onSyncAppleHealth
                )
                    .accessibilityIdentifier("xage.appleHealth.sync")

                metricLibraryEntries
            }

            if metrics.isEmpty {
                XAgeMetricEmptyRow(
                    title: "首页暂无数据卡片",
                    subtitle: "打开数据卡片管理，添加需要长期关注的指标。"
                )
                .accessibilityIdentifier("xage.data.metric.empty")
            }

            ForEach(Array(metrics.enumerated()), id: \.element.id) { index, card in
                metricCard(card, index: index)
            }
        }
        .padding(.horizontal, 24)
        .padding(.top, 10)
        .padding(.bottom, sortMode ? 112 : 32)
    }

    /// 构建 `metricLibraryEntries` 对应的局部 SwiftUI 视图，并组合所需的展示状态与交互。
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

    /// 构建单个指标卡片，并根据是否处于排序模式绑定详情或排序操作。
    private func metricCard(_ card: XAgeMetric, index: Int) -> some View {
        XAgeMetricCard(
            card: card,
            sortMode: sortMode,
            canMoveUp: index > metrics.startIndex,
            canMoveDown: index < metrics.index(before: metrics.endIndex),
            canPin: index > metrics.startIndex
        ) {
            activeSheet = .metricDetail(card)
        } onMoveUp: {
            moveMetric(index, -1)
        } onMoveDown: {
            moveMetric(index, 1)
        } onPin: {
            pinMetricToTop(index)
        } onDelete: {
            removeMetric(index)
        }
        .id(card.id)
        .accessibilityIdentifier("xage.data.metric.\(card.id)")
    }

    /// 构建 `sortDoneInset` 对应的局部 SwiftUI 视图，并组合所需的展示状态与交互。
    @ViewBuilder
    private var sortDoneInset: some View {
        if sortMode {
            XAgeSortDoneBar {
                withAnimation(.spring(response: 0.24, dampingFraction: 0.88)) {
                    sortMode = false
                }
            }
            .padding(.horizontal, 24)
            .padding(.bottom, 10)
            .transition(.move(edge: .bottom).combined(with: .opacity))
        }
    }

    /// 根据当前数据页 Sheet 类型选择指标详情、说明或手动录入等具体内容。
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

    /// 响应 `scrollToPendingMetric` 对应的页面选择、展示或交互状态切换。
    private func scrollToPendingMetric(with proxy: ScrollViewProxy) {
        guard let metricID = pendingMetricScrollID else { return }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.16) {
            withAnimation(.spring(response: 0.3, dampingFraction: 0.9)) {
                proxy.scrollTo(metricID, anchor: .top)
            }
            pendingMetricScrollID = nil
        }
    }

    /// 响应 `scrollToFirstMetricIfNeeded` 对应的页面选择、展示或交互状态切换。
    private func scrollToFirstMetricIfNeeded(isSorting: Bool, proxy: ScrollViewProxy) {
        guard isSorting, let firstMetricID = metrics.first?.id else { return }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.08) {
            withAnimation(.spring(response: 0.3, dampingFraction: 0.9)) {
                proxy.scrollTo(firstMetricID, anchor: .top)
            }
        }
    }

    /// 刷新 `refreshAllData` 对应的数据源，并同步页面所依赖的状态。
    private func refreshAllData(includeAppleHealth: Bool) async {
        // 下拉刷新可包含 Apple Health；手动指标保存后的刷新则跳过 HealthKit，减少不必要的权限和读取开销。
        if includeAppleHealth {
            await appleHealthSync.refreshIfPreviouslySynced()
        }
        await serverSync.refresh()
        mergeServerMetrics(serverSync.metricCards)
    }

    /// 更新 `updateTodayStatusVisibility` 对应的配置或状态，并处理必要的联动。
    private func updateTodayStatusVisibility(forOffset scrollOffset: CGFloat) {
        let offset = max(0, scrollOffset)
        let shouldHide = isTodayStatusHidden ? offset > 8 : offset > 28
        guard shouldHide != isTodayStatusHidden else { return }
        setTodayStatusHidden(shouldHide)
    }

    /// 更新 `setTodayStatusHidden` 对应的配置或状态，并处理必要的联动。
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

    /// 整理 `addMetric` 涉及的集合内容、顺序或去重结果。
    private func addMetric(_ metric: XAgeMetric) {
        guard !metrics.contains(where: { $0.id == metric.id }) else { return }
        pendingMetricScrollID = metric.id
        withAnimation(.spring(response: 0.26, dampingFraction: 0.88)) {
            metrics.append(metric)
        }
        persistMetricPreferences()
    }

    /// 整理 `moveMetric` 涉及的集合内容、顺序或去重结果。
    private func moveMetric(_ index: Int, _ direction: Int) {
        let target = index + direction
        guard metrics.indices.contains(index), metrics.indices.contains(target) else { return }
        withAnimation(.spring(response: 0.24, dampingFraction: 0.88)) {
            metrics.swapAt(index, target)
        }
        persistMetricPreferences()
    }

    /// 整理 `pinMetricToTop` 涉及的集合内容、顺序或去重结果。
    private func pinMetricToTop(_ index: Int) {
        guard metrics.indices.contains(index), index != metrics.startIndex else { return }
        withAnimation(.spring(response: 0.26, dampingFraction: 0.88)) {
            let metric = metrics.remove(at: index)
            pendingMetricScrollID = metric.id
            metrics.insert(metric, at: metrics.startIndex)
        }
        persistMetricPreferences()
    }

    /// 执行 `removeMetric` 对应的删除、撤销或退出操作，并处理关联状态。
    private func removeMetric(_ index: Int) {
        guard metrics.indices.contains(index) else { return }
        withAnimation(.spring(response: 0.24, dampingFraction: 0.88)) {
            _ = metrics.remove(at: index)
        }
        persistMetricPreferences()
    }

    /// 整理 `mergeAppleHealthSamples` 涉及的集合内容、顺序或去重结果。
    private func mergeAppleHealthSamples(_ samples: [AppleHealthSyncSample]) {
        // 已自定义布局时只按保存的 ID 取值；未自定义时允许新的 HealthKit 指标追加到默认卡片中。
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

    /// 整理 `mergeServerMetrics` 涉及的集合内容、顺序或去重结果。
    private func mergeServerMetrics(_ serverMetrics: [XAgeMetric]) {
        // 服务端趋势优先替换同 ID 卡片；用户未自定义布局时，新出现的服务端指标会插入首页前部。
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

    /// 整理 `restoreMetricPreferencesFromAvailableCatalog` 涉及的集合内容、顺序或去重结果。
    private func restoreMetricPreferencesFromAvailableCatalog() {
        guard metricPreference.isCustomized else { return }
        let restored = XAgeDataCardPreferences.orderedMetrics(
            for: metricPreference,
            from: serverSync.metricCards + metrics + metricCatalogSections.flatMap(\.metrics)
        )
        guard metricSnapshots(metrics) != metricSnapshots(restored) else { return }
        metrics = restored
    }

    /// 保存 `persistMetricPreferences` 对应的数据，并同步持久化后的页面状态。
    private func persistMetricPreferences() {
        // 这里只保存卡片 ID 和顺序，指标的数值、来源与时间不会进入 UserDefaults。
        metricPreference = XAgeDataCardPreferences.save(metrics: metrics, accountScope: accountScope)
    }

    /// 重置 `resetMetrics` 管理的缓存、偏好或临时状态。
    private func resetMetrics(for accountScope: String?) {
        activeSheet = nil
        showsMetricManager = false
        pendingMetricScrollID = nil
        isTodayStatusHidden = false
        sortMode = false
        metricPreference = XAgeDataCardPreferences.load(accountScope: accountScope)
        metrics = XAgeDataCardPreferences.placeholderMetrics(for: metricPreference)
    }

    /// 将指标数组转换为可比较的稳定快照，用于判断刷新前后是否发生实质变化。
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

    /// 整理 `dedupedMetrics` 涉及的集合内容、顺序或去重结果。
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

// MARK: - 服务端聚合快照

@MainActor
/// 并行拉取 XAGE 首页需要的多个业务接口，并合成为一个只读快照和指标卡片集合。
/// 所有发布状态均在主线程更新，并通过账号刷新闸门阻止跨账号的迟到响应写回。
private final class XAgeServerSyncViewModel: ObservableObject {
    @Published private(set) var snapshot = XAgeServerSyncSnapshot.placeholder
    @Published private(set) var metricCards: [XAgeMetric] = []
    @Published private(set) var indicatorCatalogCards: [XAgeMetric] = []
    @Published private(set) var isLoading = false

    private let api: APIServiceProtocol
    private var refreshGate = XAgeAccountScopedRefreshGate(accountScope: nil)

    /// 注入服务端 API 实现，默认使用应用共享的网络服务。
    init(api: APIServiceProtocol = APIService.shared) {
        self.api = api
    }

    /// 更新 `setAccountScope` 对应的配置或状态，并处理必要的联动。
    func setAccountScope(_ accountScope: String?) {
        // scope 变化时立即清空旧数据，避免新账号请求完成前短暂显示上一账号的健康信息。
        guard refreshGate.switchAccount(to: accountScope) else { return }
        snapshot = refreshGate.accountScope == nil ? .loggedOut : .placeholder
        metricCards = []
        indicatorCatalogCards = []
        isLoading = false
    }

    /// 刷新 `refresh` 对应的数据源，并同步页面所依赖的状态。
    func refresh() async {
        let auth = AuthManager.shared
        if auth.isUIValidationSession {
            setAccountScope(nil)
            snapshot = XAgeServerSyncSnapshot.placeholder
            metricCards = []
            indicatorCatalogCards = []
            return
        }

        guard auth.isLoggedIn, let startedAccountScope = auth.accountScope else {
            setAccountScope(nil)
            snapshot = .loggedOut
            metricCards = []
            indicatorCatalogCards = []
            return
        }
        // 记录请求启动时的账号和 generation，所有并发请求结束后还要再次校验。
        setAccountScope(startedAccountScope)
        let startedGeneration = refreshGate.generation

        isLoading = true
        defer {
            if refreshGate.accountScope == startedAccountScope,
               refreshGate.generation == startedGeneration {
                isLoading = false
            }
        }

        // 各接口彼此独立，使用 async let 并行请求，缩短首页整套快照的等待时间。
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

        // 第一轮接口结束后先检查账号；若用户已经退出或切换账号，当前批次结果整体作废。
        guard refreshGate.accepts(
            startedScope: startedAccountScope,
            generation: startedGeneration,
            currentScope: auth.accountScope
        ) else { return }

        let watchedNames = watched?.items.map(\.indicator_name) ?? []
        let indicatorItems = indicators?.indicators ?? []
        let trendNames = Self.trendRequestNames(watchedNames: watchedNames)
        // 趋势查询依赖前面得到的关注指标名，因此在基础请求完成后再按批次获取。
        let trendResponse = await fetchTrends(for: trendNames)
        let trends = trendResponse?.indicators ?? []

        guard !Task.isCancelled,
              refreshGate.accepts(
                startedScope: startedAccountScope,
                generation: startedGeneration,
                currentScope: auth.accountScope
              ) else { return }

        // 只有两次账号校验都通过，才将所有响应一次性折叠为页面快照，避免局部数据属于不同账号或不同刷新代次。
        snapshot = XAgeServerSyncSnapshot(
            isLoaded: true,
            isLoggedOut: false,
            summaryUpdatedAt: summary?.updated_at,
            hasSummary: !(summary?.summary_text?.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ?? true),
            recordCount: records?.items?.count ?? records?.total ?? 0,
            examCount: exams?.items?.count ?? exams?.total ?? 0,
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
    }

    /// 加载或请求 `getOptional` 所需的数据，并返回整理后的结果。
    private func getOptional<T: Decodable>(_ path: String) async -> T? {
        try? await api.get(path)
    }

    /// 加载或请求 `fetchTrends` 所需的数据，并返回整理后的结果。
    private func fetchTrends(for names: [String]) async -> IndicatorTrendResponse? {
        // 服务端单次查询最多处理 10 个名称，这里分批请求后再按规范化名称去重合并。
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

    /// 加载或请求 `fetchTrendBatch` 所需的数据，并返回整理后的结果。
    private func fetchTrendBatch(for names: [String]) async -> IndicatorTrendResponse? {
        let joined = names.joined(separator: ",")
        var allowed = CharacterSet.urlQueryAllowed
        allowed.remove(charactersIn: "+&=?")
        let encoded = joined.addingPercentEncoding(withAllowedCharacters: allowed) ?? joined
        return try? await api.get("/api/health-data/indicators/trend?names=\(encoded)")
    }

    /// 生成趋势接口的最终指标名列表，合并默认项目与用户关注项目并去重。
    private static func trendRequestNames(watchedNames: [String]) -> [String] {
        XAgeHealthTrendRequestContract.names(watchedNames: watchedNames)
    }

    /// 整理 `dedupedTrends` 涉及的集合内容、顺序或去重结果。
    private static func dedupedTrends(_ source: [IndicatorTrend]) -> [IndicatorTrend] {
        var seen = Set<String>()
        return source.filter { trend in
            seen.insert(trend.name.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()).inserted
        }
    }

    /// 将服务端趋势和健康概览转换为首页指标卡片，并过滤重复或无效项目。
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

    /// 从健康概览中提取血糖数据，并构造成统一的 XAGE 指标卡片。
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

    /// 将服务端指标目录转换为可添加到首页的卡片模型，并补齐分类与展示信息。
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

    /// 整理 `dedupedMetrics` 涉及的集合内容、顺序或去重结果。
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

    /// 从趋势点中选出测量时间最新且可用的记录，作为卡片当前值。
    private static func latestPoint(from points: [TrendPoint]) -> TrendPoint? {
        points.sorted {
            let lhs = XAgeServerSyncFormat.date(from: $0.measured_at ?? $0.source_local_date ?? $0.date) ?? .distantPast
            let rhs = XAgeServerSyncFormat.date(from: $1.measured_at ?? $1.source_local_date ?? $1.date) ?? .distantPast
            return lhs < rhs
        }.last
    }

    /// 根据指标来源、测量时间和有效期规则判断数据是否过期，并返回对应天数阈值。
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

    /// 计算 `freshnessLimitDays` 对应的评分、状态或展示值。
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

    /// 将 `sourceLabel` 的输入整理为页面可直接展示或使用的格式。
    private static func sourceLabel(_ source: String?) -> String {
        switch (source ?? "").lowercased() {
        case "apple_health": return "Apple 健康"
        case "manual": return "手动记录"
        case "device": return "设备同步"
        case "cgm": return "CGM"
        default: return "报告趋势"
        }
    }

    /// 判断指标名是否属于旧版合并血压字段，避免与新版收缩压和舒张压重复展示。
    private static func isLegacyCombinedBloodPressure(_ name: String) -> Bool {
        name.trimmingCharacters(in: .whitespacesAndNewlines) == "血压"
    }

    /// 将不同来源和旧版本的指标名称归一为同一个稳定指标 ID。
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

    /// 计算 `displayValue` 对应的评分、状态或展示值。
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

    /// 计算 `displayValue` 对应的评分、状态或展示值。
    private static func displayValue(_ point: TrendPoint, indicatorName: String) -> String {
        point.preferredDisplayValue ?? displayValue(point.value, indicatorName: indicatorName)
    }

    /// 汇总指标趋势、异常标记和文档数据，生成综合评分算法使用的趋势证据。
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

        for document in records + exams {
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

    /// 将报告异常标记转换为实验室指标趋势，保留数值、单位和报告日期。
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

    /// 从 CSV 表头和数据行识别实验室指标列，并转换为评分算法可用的趋势证据。
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

    /// 在规范化后的列名中寻找首个匹配关键字的列下标。
    private static func firstIndex(in columns: [String], matching needles: [String]) -> Int? {
        columns.firstIndex { column in
            needles.contains { column.contains($0) }
        }
    }

    /// 规范化 `parseNumericValue` 的输入值，并返回可安全参与后续计算的结果。
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

    /// 根据个人资料关键字段的填写情况计算资料完整度百分比。
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

    /// 合并病例与体检报告日期，并返回其中最新的一次记录时间。
    private static func latestDocumentDate(records: [HealthDocument], exams: [HealthDocument]) -> String? {
        (records + exams)
            .compactMap(\.doc_date)
            .sorted()
            .last
    }

}

private enum XAgeServerSyncFormat {
    /// 尝试使用支持的服务端日期格式解析字符串，无法解析时返回空值。
    static func date(from raw: String?) -> Date? {
        guard let raw, !raw.isEmpty else { return nil }
        return Utils.parseISO(raw) ?? dateOnlyFormatter.date(from: raw)
    }

    /// 将服务端日期转换为紧凑展示格式，解析失败时使用安全占位文本。
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

    /// 根据测量时间和数据来源生成指标卡片底部的时间说明。
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

private struct XAgeServerSyncSnapshot: Equatable {
    let isLoaded: Bool
    let isLoggedOut: Bool
    let summaryUpdatedAt: String?
    let hasSummary: Bool
    let recordCount: Int
    let examCount: Int
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

    /// 按数据面板分类返回对应的概览统计项，供分类详情页展示。
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
                XAgePanelStat(title: "评分", value: dashboardScore.map(String.init) ?? "--", unit: "")
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

    /// 规范化 `normalizedKey` 的输入值，并返回可安全参与后续计算的结果。
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

    /// 汇总用户资料、健康样本和服务端趋势，形成综合评分算法的统一输入上下文。
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

fileprivate extension XAgeAlgorithmContext {
    /// 将服务端聚合快照与 Apple Health 样本转换为评分算法可直接消费的上下文。
    init(snapshot: XAgeServerSyncSnapshot, samples: [AppleHealthSyncSample]) {
        self.init(
            userAge: snapshot.userAge,
            profileHeightCm: snapshot.profileHeightCm,
            profileWeightKg: snapshot.profileWeightKg,
            dashboardScore: snapshot.dashboardScore,
            trendPointCount: snapshot.trendPointCount,
            documentCount: snapshot.recordCount + snapshot.examCount,
            watchedIndicatorCount: snapshot.watchedIndicatorCount,
            samples: samples,
            serverTrends: snapshot.algorithmTrends
        )
    }
}

struct XAgeScoreField: Identifiable, Equatable {
    let title: String
    let value: String

    var id: String { "\(title)-\(value)" }
}

struct XAgeScoreDriver: Identifiable, Equatable {
    let title: String
    let value: String
    let note: String

    var id: String { "\(title)-\(value)-\(note)" }
}

struct XAgeMetricScore: Equatable {
    let value: Int
    let confidence: Int
    let isReady: Bool
    let badgeLabel: String
    let stateLabel: String
    let summary: String
    let simpleExplanation: String
    let explanation: String
    let nextAction: String
    let fields: [XAgeScoreField]
    let drivers: [XAgeScoreDriver]
    let isProxy: Bool

    var displayValue: String {
        isReady ? "\(value)" : "--"
    }
}

struct XAgeAgeScore: Equatable {
    let chronologicalAge: Double
    let ageValue: Double
    let isReady: Bool
    let age: String
    let delta: String
    let pace: Double
    let confidence: Int
    let status: String
    let summary: String
    let explanation: String
    let nextAction: String
    let drivers: [XAgeScoreDriver]
    let ageRange: String
}

// MARK: - XAGE 评分模型

/// 数据页三项健康分与 X年龄的统一结果。
/// `compute` 只依赖输入上下文，便于在服务端快照或 HealthKit 样本变化时重新计算而不产生副作用。
struct XAgeCompositeScores: Equatable {
    let pressure: XAgeMetricScore
    let recovery: XAgeMetricScore
    let inflammation: XAgeMetricScore
    let xAge: XAgeAgeScore

    var todaySummary: String {
        if !pressure.isReady || !recovery.isReady || !inflammation.isReady {
            return "数据还不够，先同步 Apple 健康或上传报告；达到评估门槛后再显示压力、恢复和炎症分。"
        }
        return "\(recovery.stateLabel)，\(pressure.stateLabel)；\(inflammation.stateLabel)。\(mostUsefulAction)"
    }

    /// 计算或构造 `compute` 对应的模型结果，供后续展示或判断使用。
    static func compute(context: XAgeAlgorithmContext) -> XAgeCompositeScores {
        // 先分别计算压力、恢复和炎症，再将三者共同作为 X年龄的输入，确保各卡片与 X年龄使用同一批证据。
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

    private var mostUsefulAction: String {
        if pressure.value >= 70 {
            return "先做 2 分钟延长呼气，再复看身体有没有回应。"
        }
        if recovery.value < 45 {
            return "今天把强度降一档，优先补水和午间短恢复。"
        }
        if inflammation.value >= 60 {
            return "记录体温、症状和睡眠；连续偏高时上传报告并复查。"
        }
        return "今天优先保持睡眠、补水和低强度活动的节律。"
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

    /// 计算或构造 `score` 对应的模型结果，供后续展示或判断使用。
    func score(for kind: XAgeDataKind) -> XAgeMetricScore {
        switch kind {
        case .pressure:
            return pressure
        case .recovery:
            return recovery
        case .inflammation:
            return inflammation
        }
    }

    /// 计算或构造 `makePressure` 对应的模型结果，供后续展示或判断使用。
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

    /// 计算或构造 `makeRecovery` 对应的模型结果，供后续展示或判断使用。
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

    /// 计算或构造 `makeInflammation` 对应的模型结果，供后续展示或判断使用。
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

    /// 计算或构造 `makeXAge` 对应的模型结果，供后续展示或判断使用。
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

    /// 按各评分证据的权重和置信度计算加权结果，并汇总有效权重与缺失原因。
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

    /// 从样本或趋势中提取指定指标证据，统一数值、置信度、来源和时间。
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

    /// 计算 `sampleConfidence` 对应的评分、状态或展示值。
    static func sampleConfidence(_ sample: AppleHealthSyncSample) -> Double {
        let days = max(0, Date().timeIntervalSince(sample.measuredAt) / 86_400)
        return clamp(0.9 * exp(-days / 21), 0.35, 0.9)
    }

    /// 计算 `serverTrendConfidence` 对应的评分、状态或展示值。
    static func serverTrendConfidence(_ trend: XAgeAlgorithmTrend) -> Double {
        guard let measuredAt = trend.measuredAt, let date = parseDate(measuredAt) else {
            return clamp(trend.confidence, 0.35, 0.86)
        }
        let days = max(0, Date().timeIntervalSince(date) / 86_400)
        let freshness = exp(-days / 120)
        return clamp(trend.confidence * freshness, 0.25, 0.86)
    }

    /// 规范化 `parseDate` 的输入值，并返回可安全参与后续计算的结果。
    static func parseDate(_ raw: String) -> Date? {
        if let date = isoFormatter.date(from: raw) { return date }
        return dateOnlyFormatter.date(from: raw)
    }

    /// 计算 `activityLoad` 对应的评分、状态或展示值。
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

    /// 计算 `activityGood` 对应的评分、状态或展示值。
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

    /// 计算 `stabilityGood` 对应的评分、状态或展示值。
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

    /// 计算 `sleepOrOverloadBad` 对应的评分、状态或展示值。
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

    /// 计算 `bodyCompositionGood` 对应的评分、状态或展示值。
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

    /// 计算 `estimatedValidDays` 对应的评分、状态或展示值。
    static func estimatedValidDays(_ context: XAgeAlgorithmContext) -> Int {
        let sampleDays = context.samples.isEmpty ? 0 : min(45, context.samples.count * 4)
        let documentDays = context.documentCount > 0 ? min(90, 25 + context.documentCount / 2) : 0
        return max(context.trendPointCount, sampleDays, documentDays)
    }

    /// 整理 `addConfidenceField` 涉及的集合内容、顺序或去重结果。
    static func addConfidenceField(_ fields: [XAgeScoreField], confidence: Int) -> [XAgeScoreField] {
        var merged = fields
        merged.append(XAgeScoreField(title: "置信度", value: "\(confidence)%"))
        return merged
    }

    /// 计算或构造 `scoreFields` 对应的模型结果，供后续展示或判断使用。
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

    /// 计算或构造 `scoreDrivers` 对应的模型结果，供后续展示或判断使用。
    static func scoreDrivers(_ drivers: [XAgeScoreDriver], isReady: Bool, title: String, note: String) -> [XAgeScoreDriver] {
        if isReady {
            return drivers
        }
        return [XAgeScoreDriver(title: title, value: "待补齐", note: note)] + drivers.prefix(2)
    }

    /// 规范化 `normalizedPercentValue` 的输入值，并返回可安全参与后续计算的结果。
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

    /// 校验 `credibleBloodWhiteCell` 对应的条件，决定数据或操作是否可以继续使用。
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

    /// 判断文本是否更像尿沉渣等非血液白细胞项目，防止实验室指标误归类。
    static func urineSedimentLike(_ text: String) -> Bool {
        let lower = text.lowercased()
        return lower.contains("/hp") || lower.contains("/lp") || lower.contains("个/hp") || lower.contains("个/lp")
    }

    /// 计算 `hrvGood` 对应的评分、状态或展示值。
    static func hrvGood(_ value: Double) -> Double {
        linear(value, low: 18, high: 65, minScore: 25, maxScore: 95)
    }

    /// 计算 `hrvSuppressionBad` 对应的评分、状态或展示值。
    static func hrvSuppressionBad(_ value: Double) -> Double {
        100 - hrvGood(value)
    }

    /// 计算 `rhrGood` 对应的评分、状态或展示值。
    static func rhrGood(_ value: Double) -> Double {
        if value <= 58 { return 92 }
        return 100 - linear(value, low: 58, high: 88, minScore: 18, maxScore: 88)
    }

    /// 计算 `rhrBad` 对应的评分、状态或展示值。
    static func rhrBad(_ value: Double) -> Double {
        100 - rhrGood(value)
    }

    /// 计算 `respirationBad` 对应的评分、状态或展示值。
    static func respirationBad(_ value: Double) -> Double {
        let deviation = abs(value - 16)
        return linear(deviation, low: 2, high: 8, minScore: 12, maxScore: 88)
    }

    /// 计算 `temperatureBad` 对应的评分、状态或展示值。
    static func temperatureBad(_ value: Double) -> Double {
        let deviation: Double
        if value > 30 {
            deviation = abs(value - 36.7)
        } else {
            deviation = abs(value)
        }
        return linear(deviation, low: 0.2, high: 1.1, minScore: 12, maxScore: 86)
    }

    /// 计算 `oxygenBad` 对应的评分、状态或展示值。
    static func oxygenBad(_ value: Double) -> Double {
        if value >= 97 { return 10 }
        if value >= 95 { return linear(97 - value, low: 0, high: 2, minScore: 16, maxScore: 38) }
        return linear(95 - value, low: 0, high: 6, minScore: 48, maxScore: 90)
    }

    /// 计算 `sleepGood` 对应的评分、状态或展示值。
    static func sleepGood(_ hours: Double) -> Double {
        if (7...9).contains(hours) { return 92 }
        if hours < 7 { return linear(hours, low: 4, high: 7, minScore: 28, maxScore: 88) }
        return clamp(92 - (hours - 9) * 16, 55, 92)
    }

    /// 计算 `sleepDebtBad` 对应的评分、状态或展示值。
    static func sleepDebtBad(_ hours: Double) -> Double {
        if hours >= 7 { return 14 }
        return linear(7 - hours, low: 0, high: 3, minScore: 18, maxScore: 88)
    }

    /// 计算 `hscrpBad` 对应的评分、状态或展示值。
    static func hscrpBad(_ value: Double) -> Double {
        if value < 1 { return 18 }
        if value < 3 { return linear(value, low: 1, high: 3, minScore: 35, maxScore: 58) }
        if value <= 10 { return linear(value, low: 3, high: 10, minScore: 62, maxScore: 92) }
        return 95
    }

    /// 计算 `wbcBad` 对应的评分、状态或展示值。
    static func wbcBad(_ value: Double) -> Double {
        if (4...10).contains(value) { return 20 }
        if value < 4 { return linear(4 - value, low: 0, high: 2, minScore: 32, maxScore: 72) }
        return linear(value, low: 10, high: 16, minScore: 42, maxScore: 88)
    }

    /// 计算 `nlrBad` 对应的评分、状态或展示值。
    static func nlrBad(_ value: Double) -> Double {
        if value < 2.5 { return 22 }
        return linear(value, low: 2.5, high: 5.5, minScore: 38, maxScore: 86)
    }

    /// 计算 `cytokineBad` 对应的评分、状态或展示值。
    static func cytokineBad(_ value: Double) -> Double {
        linear(value, low: 2, high: 10, minScore: 28, maxScore: 88)
    }

    /// 计算 `bmiGood` 对应的评分、状态或展示值。
    static func bmiGood(_ value: Double) -> Double {
        if (18.5...24.9).contains(value) { return 88 }
        if value < 18.5 { return linear(value, low: 16, high: 18.5, minScore: 52, maxScore: 82) }
        return 100 - linear(value, low: 25, high: 33, minScore: 18, maxScore: 72)
    }

    /// 计算 `bodyFatGood` 对应的评分、状态或展示值。
    static func bodyFatGood(_ value: Double) -> Double {
        if (16...28).contains(value) { return 84 }
        if value < 16 { return linear(value, low: 8, high: 16, minScore: 54, maxScore: 80) }
        return 100 - linear(value, low: 28, high: 42, minScore: 24, maxScore: 74)
    }

    /// 计算 `pressureBadge` 对应的评分、状态或展示值。
    static func pressureBadge(_ value: Int) -> String {
        if value >= 70 { return "压力偏高" }
        if value >= 40 { return "压力中等" }
        return "压力偏低"
    }

    /// 计算 `pressureState` 对应的评分、状态或展示值。
    static func pressureState(_ value: Int) -> String {
        value >= 70 ? "压力偏高" : (value >= 40 ? "压力中等" : "压力较低")
    }

    /// 计算 `pressureSummary` 对应的评分、状态或展示值。
    static func pressureSummary(_ value: Int) -> String {
        value >= 70 ? "压力输入处在高负荷区间；先降低刺激并复测。" : "压力负荷处在可管理区间。"
    }

    /// 计算 `recoveryBadge` 对应的评分、状态或展示值。
    static func recoveryBadge(_ value: Int) -> String {
        if value >= 67 { return "恢复良好" }
        if value >= 34 { return "恢复一般" }
        return "恢复偏低"
    }

    /// 计算 `recoveryState` 对应的评分、状态或展示值。
    static func recoveryState(_ value: Int) -> String {
        value >= 67 ? "恢复较好" : (value >= 34 ? "恢复一般" : "恢复偏低")
    }

    /// 计算 `recoverySummary` 对应的评分、状态或展示值。
    static func recoverySummary(_ value: Int) -> String {
        value >= 67 ? "恢复输入处在高分区间，可以承接适度挑战。" : "恢复输入处在保守区间，今天降低强度并补齐睡眠。"
    }

    /// 计算 `inflammationBadge` 对应的评分、状态或展示值。
    static func inflammationBadge(_ value: Int) -> String {
        if value >= 70 { return "小火苗高" }
        if value >= 40 { return "炎症关注" }
        return "小火苗低"
    }

    /// 计算 `inflammationState` 对应的评分、状态或展示值。
    static func inflammationState(_ value: Int, proxy: Bool) -> String {
        if value >= 70 { return proxy ? "小火苗偏高" : "炎症负荷偏高" }
        if value >= 40 { return proxy ? "小火苗中等" : "炎症负荷中等" }
        return proxy ? "小火苗较低" : "炎症负荷较低"
    }

    /// 计算 `inflammationSummary` 对应的评分、状态或展示值。
    static func inflammationSummary(_ value: Int, proxy: Bool) -> String {
        if proxy {
            return value >= 60 ? "代理信号处在高位，体温和症状记录会参与下一次重算。" : "代理信号处在低位，实验室数据会替代当前代理项。"
        }
        return value >= 60 ? "实验室和生理信号处在复核区间。" : "炎症负荷处于较低区间。"
    }

    /// 计算 `deltaLabel` 对应的评分、状态或展示值。
    static func deltaLabel(_ value: Double) -> String {
        if value <= -0.15 { return "年轻 \(String(format: "%.1f", abs(value))) 岁" }
        if value >= 0.15 { return "偏大 \(String(format: "%.1f", value)) 岁" }
        return "接近实际年龄"
    }

    /// 计算 `xAgeStatus` 对应的评分、状态或展示值。
    static func xAgeStatus(pace: Double, delta: Double, confidence: Int) -> String {
        if confidence < 35 { return "建立基线中" }
        if pace < 0.85 || delta < -0.5 { return "趋势变年轻" }
        if pace > 1.15 || delta > 0.5 { return "负荷略高" }
        return "稳定且健康"
    }

    /// 计算 `xAgeSummary` 对应的评分、状态或展示值。
    static func xAgeSummary(result: WeightedResult, pressure: XAgeMetricScore, recovery: XAgeMetricScore, inflammation: XAgeMetricScore, validDays: Int) -> String {
        if validDays < 30 {
            return "有效天数不足 30 天，算法启用低影响系数和低置信度区间。"
        }
        if let driver = result.drivers.first {
            return "\(driver.title) 是本周年龄差的最大贡献项；算法每周用压力、恢复、炎症和日常节律重算 X年龄。"
        }
        return "当前 X年龄由压力、恢复、炎症和日常节律共同决定。"
    }

    /// 规范化 `linear` 的输入值，并返回可安全参与后续计算的结果。
    static func linear(_ value: Double, low: Double, high: Double, minScore: Double, maxScore: Double) -> Double {
        guard high > low else { return minScore }
        let ratio = (value - low) / (high - low)
        return clamp(minScore + ratio * (maxScore - minScore))
    }

    /// 规范化 `clamp` 的输入值，并返回可安全参与后续计算的结果。
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

    /// 合并子视图上报的布局偏好值，供父视图统一消费。
    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) {
        value = nextValue()
    }
}

private struct XAgeDataScrollOffsetProbe: View {
    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
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

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
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

// MARK: - 数据评分展示

/// 数据页所有弹层的统一路由，确保同一时间只呈现一种详情，并可在指标详情与手动录入之间切换。
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

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
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

private enum XAgeDataKind: String, Identifiable {
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

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
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

    /// 构建 `ringControl` 对应的局部 SwiftUI 视图，并组合所需的展示状态与交互。
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

    /// 构建 `ringGraphic` 对应的局部 SwiftUI 视图，并组合所需的展示状态与交互。
    private var ringGraphic: some View {
        let lineWidth = max(7, ringSize * 0.1)
        return ZStack {
            Circle()
                .trim(from: 0.04, to: 0.9)
                .stroke(Color.white.opacity(0.52), style: StrokeStyle(lineWidth: lineWidth, lineCap: .round))
                .rotationEffect(.degrees(112))
            Circle()
                .trim(from: 0.04, to: 0.04 + 0.86 * CGFloat(metric.isReady ? metric.value : 0) / 100)
                .stroke(
                    AngularGradient(
                        colors: [kind.tint.opacity(0.35), kind.tint, Color.appAccent, kind.tint],
                        center: .center
                    ),
                    style: StrokeStyle(lineWidth: lineWidth, lineCap: .round)
                )
                .rotationEffect(.degrees(112))
                .opacity(metric.isReady ? 1 : 0.28)
                .shadow(color: kind.tint.opacity(metric.isReady ? 0.22 : 0.08), radius: 8, x: 0, y: 3)
            Text(metric.displayValue)
                .font(.system(size: metric.isReady ? (ringSize >= 80 ? 25 : 22) : 20, weight: .bold))
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

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
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

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
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
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 12 - 2 * compactProgress)
        .background(XAgeGlassCardBackground(cornerRadius: 24))
    }
}

// MARK: - 健康指标目录与展示模型

/// 指标管理页的目录分组；服务端指标和本地支持的 Apple Health 指标最终都会整理为这些分组。
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

    /// 计算或构造 `resolve` 对应的模型结果，供后续展示或判断使用。
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

    /// 创建统一的指标卡片模型，并保留数据来源、测量时间、占位和过期状态。
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

    /// 合并内置指标与服务端指标，并按健康分类生成指标库分组。
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

    /// 构造尚无实时数据的内置指标目录卡片，使用占位值等待后续录入或同步。
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

    /// 将服务端指标目录项转换为客户端统一卡片模型，并保留分类和单位。
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

    /// 整理 `deduped` 涉及的集合内容、顺序或去重结果。
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

    /// 将 Apple Health 同步样本转换为统一指标卡片，并补齐来源和测量时间。
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

    /// 计算 `appleHealthTimeLabel` 对应的评分、状态或展示值。
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

// MARK: - Apple Health 同步卡片

/// 数据页的显式 HealthKit 入口。状态和权限说明来自 ViewModel，点击同步仍回到根页面的统一同步链路。
private struct XAgeAppleHealthSyncCard: View {
    @ObservedObject var viewModel: AppleHealthSyncViewModel
    let onSyncAppleHealth: () async -> Void
    @Environment(\.openURL) private var openURL

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
    var body: some View {
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

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
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

    /// 将服务端问题代码转换为用户可理解的指标详情提示文案。
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

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
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

// MARK: - 首页指标卡片与排序

/// 单个健康指标卡片。在普通模式下打开详情，在排序模式下改为上移、下移、置顶和移除操作。
private struct XAgeMetricCard: View {
    let card: XAgeMetric
    let sortMode: Bool
    let canMoveUp: Bool
    let canMoveDown: Bool
    let canPin: Bool
    let onOpen: () -> Void
    let onMoveUp: () -> Void
    let onMoveDown: () -> Void
    let onPin: () -> Void
    let onDelete: () -> Void

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
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
                if !sortMode {
                    Image(systemName: "chevron.right")
                        .font(.system(size: 13, weight: .bold))
                        .foregroundStyle(Color(hex: "A0B1C0"))
                        .frame(width: 14)
                }
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

            if sortMode {
                HStack(spacing: 8) {
                    CapsuleButton(title: "上移", isEnabled: canMoveUp, action: onMoveUp)
                        .accessibilityLabel("上移\(card.title)")
                    CapsuleButton(title: "下移", isEnabled: canMoveDown, action: onMoveDown)
                        .accessibilityLabel("下移\(card.title)")
                    Spacer()
                    XAgeMetricSortActionButton(title: "置顶", icon: "pin.fill", isEnabled: canPin, action: onPin)
                        .accessibilityLabel("置顶\(card.title)")
                    XAgeMetricSortActionButton(title: "移出首页", icon: "rectangle.portrait.and.arrow.right", destructive: true, action: onDelete)
                        .accessibilityLabel("将\(card.title)移出首页")
                }
            }
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 16)
        .background(XAgeGlassCardBackground(cornerRadius: 24))
        .contentShape(RoundedRectangle(cornerRadius: 24, style: .continuous))
        .onTapGesture {
            guard !sortMode else { return }
            onOpen()
        }
        .xAgeMetricCardAccessibility(
            sortMode: sortMode,
            label: "\(card.title)，\(card.value) \(card.unit)，\(card.time)",
            hint: "打开指标详情"
        )
    }
}

private struct XAgeMetricSortActionButton: View {
    let title: String
    let icon: String
    var isEnabled = true
    var destructive = false
    let action: () -> Void

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
    var body: some View {
        Button(action: action) {
            HStack(spacing: 4) {
                Image(systemName: icon)
                    .font(.system(size: 11, weight: .bold))
                Text(title)
                    .font(.system(size: 12, weight: .bold))
            }
            .foregroundStyle(destructive ? Color(hex: "C84755") : Color(hex: "237FC4"))
            .frame(minWidth: 58)
            .padding(.horizontal, title.count > 2 ? 8 : 0)
            .frame(height: 44)
            .background {
                Capsule()
                    .fill(.white.opacity(0.54))
                    .background(.ultraThinMaterial, in: Capsule())
                    .overlay(Capsule().stroke(.white.opacity(0.86), lineWidth: 1))
                    .frame(height: 30)
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .disabled(!isEnabled)
        .opacity(isEnabled ? 1 : 0.42)
        .accessibilityLabel(title)
    }
}

private struct XAgeSortDoneBar: View {
    let onDone: () -> Void

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: "arrow.up.arrow.down")
                .font(.system(size: 15, weight: .bold))
                .foregroundStyle(Color(hex: "237FC4"))
                .frame(width: 32, height: 32)
                .background(Circle().fill(.white.opacity(0.52)))

            VStack(alignment: .leading, spacing: 2) {
                Text("正在排序")
                    .font(.system(size: 13, weight: .bold))
                    .foregroundStyle(Color(hex: "173F64"))
                Text("置顶、移出首页或调整顺序后点这里完成")
                    .font(.system(size: 11, weight: .medium))
                    .foregroundStyle(Color(hex: "5D7890"))
                    .lineLimit(1)
                    .minimumScaleFactor(0.82)
            }

            Spacer(minLength: 6)

            Button(action: onDone) {
                HStack(spacing: 5) {
                    Image(systemName: "checkmark")
                        .font(.system(size: 12, weight: .black))
                    Text("完成排序")
                        .font(.system(size: 13, weight: .bold))
                }
                .foregroundStyle(.white)
                .frame(width: 104, height: 36)
                .background(
                    Capsule()
                        .fill(LinearGradient(colors: [Color(hex: "238AD6"), Color(hex: "20CDB1")], startPoint: .topLeading, endPoint: .bottomTrailing))
                        .overlay(Capsule().stroke(.white.opacity(0.78), lineWidth: 1))
                )
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("xage.data.sort.bottomDone")
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 12)
        .background(XAgeGlassCardBackground(cornerRadius: 22))
        .shadow(color: Color(hex: "7CCAF5").opacity(0.18), radius: 18, x: 0, y: 10)
    }
}

private struct XAgeMetricLibraryEntryCard: View {
    let availableCount: Int
    let totalCount: Int
    let onManage: () -> Void

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
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

// MARK: - 指标卡片管理页

/// 集中管理数据页长期关注的指标。
/// 置顶列表与候选目录共享同一搜索条件，每次增删或换序后立即回调保存账号级偏好。
private struct XAgeMetricManagerPage: View {
    @Binding var pinnedMetrics: [XAgeMetric]
    let catalogSections: [XAgeMetricCatalogSection]
    let onMetricsChanged: () -> Void
    let onOpenMetric: (XAgeMetric) -> Void
    @State private var searchText = ""
    @FocusState private var searchFocused: Bool

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
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

    /// 整理 `filter` 涉及的集合内容、顺序或去重结果。
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

    /// 整理 `pin` 涉及的集合内容、顺序或去重结果。
    private func pin(_ metric: XAgeMetric) {
        // 候选项只按稳定 ID 加入一次，加入后立即从候选区消失并出现在置顶区。
        guard !pinnedMetrics.contains(where: { $0.id == metric.id }) else { return }
        withAnimation(.spring(response: 0.24, dampingFraction: 0.88)) {
            pinnedMetrics.append(metric)
        }
        onMetricsChanged()
    }

    /// 整理 `unpin` 涉及的集合内容、顺序或去重结果。
    private func unpin(_ metric: XAgeMetric) {
        guard let index = pinnedMetrics.firstIndex(where: { $0.id == metric.id }) else { return }
        withAnimation(.spring(response: 0.24, dampingFraction: 0.88)) {
            _ = pinnedMetrics.remove(at: index)
        }
        onMetricsChanged()
    }

    /// 整理 `moveMetric` 涉及的集合内容、顺序或去重结果。
    private func moveMetric(from index: Int, by delta: Int) {
        // 页面只允许相邻换位；边界校验避免无效下标，同时让动画与持久化顺序保持一致。
        let target = index + delta
        guard pinnedMetrics.indices.contains(index), pinnedMetrics.indices.contains(target) else { return }
        withAnimation(.spring(response: 0.24, dampingFraction: 0.88)) {
            pinnedMetrics.swapAt(index, target)
        }
        onMetricsChanged()
    }

    /// 响应 `openMetric` 对应的页面选择、展示或交互状态切换。
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

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
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

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
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

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
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

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
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

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
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

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
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

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
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

// MARK: - 指标详情与手动录入

/// 展示单个指标的当前值、来源、更新时间和可用状态，并提供进入手动录入流程的入口。
private struct XAgeMetricDetailSheet: View {
    let metric: XAgeMetric
    let onManualRecord: () -> Void
    @Environment(\.dismiss) private var dismiss

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
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

/// 手动指标录入页。表单先保存在本地状态中，提交成功后通知数据页重新拉取服务端趋势。
/// 指标名、数值、单位、备注或测量时间有变化时，会阻止直接下滑关闭并要求用户确认放弃。
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

    /// 根据所选指标初始化录入草稿，并保存取消与提交成功后的页面回调。
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

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
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
        // 同时兼容中文输入法产生的全角逗号，并在提交前统一解析为 Double。
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

    /// 整理 `moveFocus` 涉及的集合内容、顺序或去重结果。
    private func moveFocus(by offset: Int) {
        focusedField = offset < 0 ? previousField : nextField
    }

    /// 发起 `requestCancel` 对应的权限、关闭或状态变更请求。
    private func requestCancel() {
        // 先结束输入状态，再根据表单是否变化决定直接返回详情页还是弹出放弃确认。
        focusedField = nil
        XAgeKeyboard.dismiss()
        if hasUnsavedChanges {
            showDiscardConfirmation = true
        } else {
            onCancel()
        }
    }

    /// 保存 `save` 对应的数据，并同步持久化后的页面状态。
    private func save() async {
        // View 负责清理输入格式和空字符串，具体校验、请求与错误状态交给 ManualIndicatorViewModel。
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

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
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

private struct XAgeMetricDetailRow: View {
    let title: String
    let value: String

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
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

// MARK: - 资料中心分类与报告上传

/// 设置菜单中的四类资料入口。枚举集中定义标题、图标、说明和页面操作，保证菜单与详情页语义一致。
private enum XAgeDataPanelCategory: String, CaseIterable, Identifiable, Hashable {
    case reports = "报告"
    case daily = "日常"
    case medical = "就医"
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
        case .reports: return "报告入库"
        case .daily: return "日常同步"
        case .medical: return "就医整理"
        case .profile: return "健康画像"
        }
    }

    var subtitle: String {
        switch self {
        case .reports: return "体检、化验、影像"
        case .daily: return "睡眠、步数、HRV"
        case .medical: return "诊断、处方、随访"
        case .profile: return "基础、慢病、过敏"
        }
    }

    var actionTitle: String {
        switch self {
        case .reports: return "上传"
        case .daily: return "查看"
        case .medical: return "整理"
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
        case .reports: return "把体检、化验和影像资料先入库，小捷会在后台识别结构化字段，并提示缺失项。"
        case .daily: return "聚合睡眠、步数、HRV 和训练负荷，用来解释当天压力、恢复和炎症评分变化。"
        case .medical: return "把诊断、处方和随访整理成连续时间线，方便下一次问诊前快速回顾。"
        case .profile: return "维护基础资料、慢病、过敏和长期用药，让问答和计划生成更贴近个人状态。"
        }
    }

    var rows: [XAgePanelRow] {
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
                XAgePanelRow(icon: "list.clipboard.fill", title: "诊断摘要", subtitle: "按科室和时间整理病程"),
                XAgePanelRow(icon: "pills.fill", title: "处方核对", subtitle: "剂量、频次和注意事项"),
                XAgePanelRow(icon: "calendar.badge.clock", title: "随访提醒", subtitle: "复诊、复查和报告回传")
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
        case "诊断摘要": return "diagnosis"
        case "处方核对": return "prescription"
        case "随访提醒": return "follow-up"
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

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
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

    /// 构建 `glyph` 对应的局部 SwiftUI 视图，并组合所需的展示状态与交互。
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

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
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

private struct XAgeReportUploadFile: Identifiable, Equatable {
    let id = UUID()
    let data: Data
    let fileName: String

    var previewImage: UIImage? {
        UIImage(data: data)
    }
}

/// 用户选择文件后、真正上传前的暂存批次，统一承载来源、文件数和总体积，供确认页展示。
private struct XAgePendingReportUpload: Identifiable, Equatable {
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

/// 单个资料分类的全屏工作台。
/// “报告”分类处理上传和历史识别；其他分类展示同步、就医整理或画像维护等交互内容。
private struct XAgePanelDestinationView: View {
    let category: XAgeDataPanelCategory
    @ObservedObject var appleHealthSync: AppleHealthSyncViewModel
    let snapshot: XAgeServerSyncSnapshot
    let onSyncAppleHealth: () async -> Void
    var onClose: (() -> Void)?
    @Environment(\.dismiss) private var dismiss
    @StateObject private var reportUploadVM = HealthDataViewModel()
    @State private var selectedRowID: String?
    @State private var completedActionIDs: Set<String> = []
    @State private var selectedTagIDs: Set<String> = []
    @State private var primaryActionCount = 0
    @State private var showCamera = false
    @State private var showPhotoLibrary = false
    @State private var showDocumentPicker = false
    @State private var showReportUploadOptions = false
    @State private var showReportHistory = false
    @State private var pendingUpload: XAgePendingReportUpload?
    @State private var uploadQualityWarning: String?

    private var activeRow: XAgePanelRow {
        category.rows.first { $0.id == selectedRowID } ?? category.rows[0]
    }

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
    var body: some View {
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
                                    appleHealthSync: appleHealthSync,
                                    snapshot: snapshot,
                                    completedActionIDs: $completedActionIDs,
                                    selectedTagIDs: $selectedTagIDs,
                                    primaryActionCount: $primaryActionCount,
                                    onSyncAppleHealth: onSyncAppleHealth,
                                    onReportUploadAction: handleReportUploadAction,
                                    onReportHistoryAction: { showReportHistory = true }
                                )
                                .transition(.opacity.combined(with: .move(edge: .top)))
                            }
                        }
                    }

                    if category == .reports,
                       reportUploadVM.uploading || reportUploadVM.backgroundTaskHint != nil {
                        XAgeChatUploadStatusCard(
                            uploading: reportUploadVM.uploading,
                            title: reportUploadVM.uploading
                                ? (reportUploadVM.uploadStage.isEmpty ? "正在上传报告…" : reportUploadVM.uploadStage)
                                : "报告已上传，AI 正在识别",
                            subtitle: reportUploadVM.backgroundTaskHint ?? "完成后会继续写入用户端数据。"
                        )
                        .accessibilityIdentifier("xage.panel.reports.upload.status")
                    }

                }
                .padding(.horizontal, 24)
                .padding(.bottom, 18)
            }
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
                selectionLimit: 9,
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
                    uploadReports(upload.files)
                }
            )
            .presentationDetents([.medium, .large])
            .presentationDragIndicator(.visible)
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
        .alert("上传失败", isPresented: Binding(
            get: { reportUploadVM.errorMessage != nil },
            set: { if !$0 { reportUploadVM.errorMessage = nil } }
        )) {
            Button("确定", role: .cancel) {}
        } message: {
            Text(reportUploadVM.errorMessage ?? "")
        }
    }

    /// 构建 `primaryActionButton` 对应的局部 SwiftUI 视图，并组合所需的展示状态与交互。
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
        .accessibilityIdentifier("xage.panel.\(category.id).primary")
    }

    private var primaryButtonTitle: String {
        switch category {
        case .reports:
            switch activeRow.key {
            case "upload": return "开始入库"
            case "history": return "查看历史报告"
            case "recognition": return "刷新识别状态"
            default: return "确认并入库"
            }
        case .daily:
            return activeRow.title == "Apple Health" ? "同步日常数据" : "更新日常解释"
        case .medical:
            return activeRow.title == "随访提醒" ? "保存提醒" : "整理到时间线"
        case .profile:
            return activeRow.title == "安全信息" ? "保存安全信息" : "保存画像"
        }
    }

    /// 响应 `select` 对应的页面选择、展示或交互状态切换。
    private func select(_ row: XAgePanelRow) {
        // 这里只切换当前功能卡片；真正的上传、刷新或保存操作统一由主按钮执行。
        withAnimation(.spring(response: 0.24, dampingFraction: 0.88)) {
            selectedRowID = row.id
        }
    }

    /// 处理 `runPrimaryAction` 对应的用户操作或系统回调，并推进后续流程。
    private func runPrimaryAction() {
        // 先处理报告和 Apple Health 等需要系统页面或异步任务的特殊操作，其余分类记录当前交互的完成状态。
        let row = activeRow
        if category == .reports {
            switch row.key {
            case "upload":
                showReportUploadOptions = true
                return
            case "history":
                showReportHistory = true
                return
            case "recognition":
                Task { await reportUploadVM.fetchAll() }
            default:
                break
            }
        }

        if category == .daily && row.title == "Apple Health" {
            Task { await onSyncAppleHealth() }
            return
        }

        withAnimation(.spring(response: 0.24, dampingFraction: 0.88)) {
            completedActionIDs.insert("primary-\(category.id)-\(row.key)-\(primaryActionCount)")
            primaryActionCount += 1
        }
    }

    /// 处理 `runHeaderAction` 对应的用户操作或系统回调，并推进后续流程。
    private func runHeaderAction() {
        if category == .reports {
            showReportUploadOptions = true
            return
        }
        runPrimaryAction()
    }

    /// 处理 `handleReportUploadAction` 对应的用户操作或系统回调，并推进后续流程。
    private func handleReportUploadAction(_ action: XAgeReportUploadAction) {
        // 将统一的上传来源枚举映射为对应的系统选择器；非报告分类不会触发文件采集。
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

    /// 响应 `presentReportUploadActionFromOptions` 对应的页面选择、展示或交互状态切换。
    private func presentReportUploadActionFromOptions(_ action: XAgeReportUploadAction) {
        // 先关闭来源 Sheet，等待转场结束再呈现系统相机、相册或文件选择器，避免多层呈现冲突。
        showReportUploadOptions = false
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.28) {
            handleReportUploadAction(action)
        }
    }

    /// 准备 `preparePendingReportUpload` 后续流程所需的数据和页面状态。
    private func preparePendingReportUpload(files: [XAgeReportUploadFile], title: String, source: String) {
        // 上传前逐张进行基础质量检查；全部通过后才生成待确认批次，不会在用户确认前调用服务端。
        guard !files.isEmpty else { return }
        for file in files {
            if let warning = validateReportImageQuality(data: file.data, fileName: file.fileName) {
                uploadQualityWarning = "\(file.fileName)：\(warning)"
                return
            }
        }
        let upload = XAgePendingReportUpload(title: title, source: source, files: files)
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.25) {
            pendingUpload = upload
        }
    }

    /// 执行 `uploadReports` 对应的文件上传，并衔接上传后的刷新或分析。
    private func uploadReports(_ files: [XAgeReportUploadFile]) {
        // 按体检报告类型逐个提交；至少一个文件成功后才更新页面上的操作完成状态。
        guard !files.isEmpty else { return }
        reportUploadVM.uploadDocType = "exam"
        Task {
            var successCount = 0
            for file in files {
                if await reportUploadVM.uploadFile(data: file.data, fileName: file.fileName) != nil {
                    successCount += 1
                }
            }
            if successCount > 0 {
                withAnimation(.spring(response: 0.24, dampingFraction: 0.88)) {
                    completedActionIDs.insert("reports-upload-success-\(primaryActionCount)")
                    primaryActionCount += 1
                }
            }
        }
    }

    /// 校验 `validateReportImageQuality` 对应的条件，决定数据或操作是否可以继续使用。
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

    /// 构建 `header` 对应的局部 SwiftUI 视图，并组合所需的展示状态与交互。
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
    @ObservedObject var appleHealthSync: AppleHealthSyncViewModel
    let snapshot: XAgeServerSyncSnapshot
    @Binding var completedActionIDs: Set<String>
    @Binding var selectedTagIDs: Set<String>
    @Binding var primaryActionCount: Int
    let onSyncAppleHealth: () async -> Void
    let onReportUploadAction: (XAgeReportUploadAction) -> Void
    let onReportHistoryAction: () -> Void
    @Environment(\.openURL) private var openURL

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
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
                Text(primaryActionCount > 0 ? "已更新" : "可编辑")
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
            return "把可穿戴与日常信号转成今天的压力、恢复、炎症解释。"
        case .medical:
            return "把就医资料整理成时间线、处方核对和复查提醒。"
        case .profile:
            return "维护画像信息，让问答、计划和风险提示更贴近个人状态。"
        }
    }

    /// 构建 `content` 对应的局部 SwiftUI 视图，并组合所需的展示状态与交互。
    @ViewBuilder
    private var content: some View {
        switch category {
        case .reports:
            reportsContent
        case .daily:
            dailyContent
        case .medical:
            medicalContent
        case .profile:
            profileContent
        }
    }

    /// 构建 `reportsContent` 对应的局部 SwiftUI 视图，并组合所需的展示状态与交互。
    @ViewBuilder
    private var reportsContent: some View {
        if row.key == "upload" {
            HStack(spacing: 9) {
                chip("拍照", icon: "camera.fill") { onReportUploadAction(.camera) }
                chip("选 PDF", icon: "doc.fill") { onReportUploadAction(.document) }
                chip("相册", icon: "photo.fill") { onReportUploadAction(.photoLibrary) }
            }
            toggleRow("姓名与报告一致", subtitle: "未匹配时会进入人工确认", key: "name")
            toggleRow("最近报告 \(snapshot.latestDocumentLabel)", subtitle: "用于排列时间线和趋势", key: "date")
            toggleRow("\(snapshot.indicatorCount) 项指标已入库", subtitle: "新增报告确认后会继续写入用户端数据", key: "indicators")
        } else if row.key == "recognition" {
            progressLine("病历资料", value: progress(snapshot.recordCount, cap: 20), trailing: "\(snapshot.recordCount) 份")
            progressLine("体检化验", value: progress(snapshot.examCount, cap: 300), trailing: "\(snapshot.examCount) 份")
            progressLine("指标趋势", value: progress(snapshot.indicatorCount, cap: 300), trailing: "\(snapshot.indicatorCount) 项")
            HStack(spacing: 9) {
                chip("仅异常", icon: "exclamationmark.triangle.fill")
                chip("全部字段", icon: "list.bullet.rectangle")
            }
        } else if row.key == "history" {
            Button(action: onReportHistoryAction) {
                HStack(spacing: 10) {
                    Image(systemName: "clock.arrow.circlepath")
                        .font(.system(size: 15, weight: .bold))
                    VStack(alignment: .leading, spacing: 2) {
                        Text("打开历史报告")
                            .font(.system(size: 13, weight: .bold))
                        Text("查看已上传报告、病历和单份 AI 摘要")
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
            toggleRow("单份报告摘要", subtitle: "识别完成后显示关键指标、异常项和入库状态", key: "single-summary")
        } else {
            toggleRow(snapshot.primaryWatchedLabel, subtitle: "\(snapshot.trendPointCount) 个历史趋势点可用于复核", key: "watched")
            toggleRow("健康摘要", subtitle: snapshot.hasSummary ? "已生成，可作为问答上下文" : "暂无摘要，建议生成后再问答", key: "summary")
            toggleRow("报告日期 \(snapshot.latestDocumentLabel)", subtitle: "确认后会用于排序", key: "report-date")
        }
    }

    /// 构建 `dailyContent` 对应的局部 SwiftUI 视图，并组合所需的展示状态与交互。
    @ViewBuilder
    private var dailyContent: some View {
        if row.title == "Apple Health" {
            Text(appleHealthSync.statusSubtitle)
                .font(.system(size: 13))
                .foregroundStyle(Color(hex: "496A83"))
                .lineSpacing(3)
                .fixedSize(horizontal: false, vertical: true)
            XAgeAppleHealthSyncDetailDisclosure(viewModel: appleHealthSync)
            HStack(spacing: 8) {
                badge(appleHealthSync.statusTitle)
                badge("\(appleHealthSync.samples.count) 项")
                badge("只读授权")
            }
            Button {
                Task { await onSyncAppleHealth() }
            } label: {
                HStack(spacing: 8) {
                    if appleHealthSync.isWorking {
                        ProgressView()
                            .tint(.white)
                    } else {
                        Image(systemName: "arrow.triangle.2.circlepath")
                            .font(.system(size: 13, weight: .bold))
                    }
                    Text(appleHealthSync.isWorking ? "同步中" : "立即同步")
                        .font(.system(size: 13, weight: .bold))
                }
                .foregroundStyle(.white)
                .frame(maxWidth: .infinity)
                .frame(height: 38)
                .background(
                    Capsule()
                        .fill(LinearGradient(colors: category.gradient, startPoint: .leading, endPoint: .trailing))
                )
            }
            .buttonStyle(.plain)
            .disabled(appleHealthSync.isWorking)
            .accessibilityIdentifier("xage.panel.daily.detail.appleHealth.sync")
            if shouldShowAppleHealthSettings {
                Button {
                    guard let settingsURL = URL(string: UIApplication.openSettingsURLString) else { return }
                    openURL(settingsURL)
                } label: {
                    Label("管理或恢复 Apple 健康权限", systemImage: "gearshape.fill")
                        .font(.system(size: 12, weight: .bold))
                        .foregroundStyle(Color(hex: "347FB7"))
                        .frame(maxWidth: .infinity)
                        .frame(height: 36)
                        .background(XAgeCapsuleFill())
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("xage.panel.daily.detail.appleHealth.settings")
            }
        } else if row.title == "恢复信号" {
            progressLine("关注指标", value: progress(snapshot.watchedIndicatorCount, cap: 8), trailing: "\(snapshot.watchedIndicatorCount) 项")
            progressLine("历史趋势", value: progress(snapshot.trendPointCount, cap: 60), trailing: "\(snapshot.trendPointCount) 点")
            progressLine("今日目标", value: progress(snapshot.todayGoalCount, cap: 5), trailing: "\(snapshot.todayGoalCount) 条")
            HStack(spacing: 9) {
                chip("用于恢复", icon: "heart.fill")
                chip("加入压力解释", icon: "bolt.heart.fill")
            }
        } else {
            toggleRow("关注 \(snapshot.primaryWatchedLabel)", subtitle: "已同步服务端关注指标", key: "watched")
            toggleRow("趋势点 \(snapshot.trendPointCount)", subtitle: "用于解释日常变化与评分", key: "trend-points")
            toggleRow("健康摘要", subtitle: snapshot.hasSummary ? "已接入问答上下文" : "等待生成摘要", key: "daily-summary")
        }
    }

    private var shouldShowAppleHealthSettings: Bool {
        appleHealthSync.shouldOfferHealthSettingsRecovery
    }

    /// 构建 `medicalContent` 对应的局部 SwiftUI 视图，并组合所需的展示状态与交互。
    @ViewBuilder
    private var medicalContent: some View {
        if row.title == "诊断摘要" {
            timelineRow(snapshot.latestDocumentLabel, title: "最近报告", detail: "已同步 \(snapshot.recordCount + snapshot.examCount) 份文档")
            timelineRow("问答记录", title: "历史咨询", detail: "已同步 \(snapshot.conversationCount) 次对话")
            toggleRow("生成问诊前摘要", subtitle: snapshot.hasSummary ? "可直接引用健康摘要" : "建议先生成健康摘要", key: "visit-summary")
        } else if row.title == "处方核对" {
            toggleRow("健康计划 \(snapshot.planCount) 个", subtitle: "可用于核对执行和提醒", key: "plans")
            toggleRow("已入库指标 \(snapshot.indicatorCount) 项", subtitle: "处方核对时结合关键检验值", key: "medicine-indicators")
            toggleRow("提醒医生复核", subtitle: "结合最新报告和健康摘要", key: "dose-check")
        } else {
            HStack(spacing: 9) {
                chip("下周", icon: "calendar")
                chip("一月内", icon: "calendar.badge.clock")
                chip("报告回传", icon: "tray.and.arrow.up.fill")
            }
            toggleRow("最近报告 \(snapshot.latestDocumentLabel)", subtitle: "问诊前优先回看", key: "latest-report")
            toggleRow("把新报告带到问诊", subtitle: "上传后自动更新摘要和指标", key: "upload-next")
        }
    }

    /// 构建 `profileContent` 对应的局部 SwiftUI 视图，并组合所需的展示状态与交互。
    @ViewBuilder
    private var profileContent: some View {
        if row.title == "基础资料" {
            progressLine("资料完整度", value: CGFloat(snapshot.profileCompletion) / 100, trailing: "\(snapshot.profileCompletion)%")
            HStack(spacing: 9) {
                chip("减脂", icon: "target")
                chip("控糖", icon: "drop.fill")
                chip("提升睡眠", icon: "moon.fill")
            }
            toggleRow("同步体重到画像", subtitle: "来自 Apple 健康或手动记录", key: "weight")
        } else if row.title == "长期标签" {
            HStack(spacing: 9) {
                chip("\(snapshot.indicatorCount)项指标", icon: "tag.fill")
                chip("\(snapshot.watchedIndicatorCount)项关注", icon: "tag.fill")
                chip("\(snapshot.planCount)个计划", icon: "person.2.fill")
            }
            HStack(spacing: 9) {
                chip("历史报告", icon: "doc.text.fill")
                chip("问答上下文", icon: "brain.head.profile")
            }
        } else {
            toggleRow("健康摘要", subtitle: snapshot.hasSummary ? "已同步，可辅助风险提示" : "暂无摘要", key: "summary")
            toggleRow("长期用药提示", subtitle: "处方核对时避免冲突", key: "medicine")
            toggleRow("家庭共享需单独授权", subtitle: "默认不共享敏感健康资料", key: "family")
        }
    }

    /// 将当前值按上限换算为 0 到 1 的进度比例，并限制越界结果。
    private func progress(_ value: Int, cap: Int) -> CGFloat {
        guard cap > 0 else { return 0 }
        return min(1, CGFloat(value) / CGFloat(cap))
    }

    /// 构建带图标的胶囊标签；存在操作回调时提供点击能力。
    private func chip(_ title: String, icon: String, action: (() -> Void)? = nil) -> some View {
        let selected = action == nil && selectedTagIDs.contains(selectionKey(title))
        return Button {
            if let action {
                action()
            } else {
                toggleTag(title)
            }
        } label: {
            HStack(spacing: 5) {
                Image(systemName: icon)
                    .font(.system(size: 11, weight: .bold))
                Text(title)
                    .font(.system(size: 12, weight: .bold))
                    .lineLimit(1)
                    .minimumScaleFactor(0.8)
            }
            .foregroundStyle(selected ? .white : Color(hex: "347FB7"))
            .frame(maxWidth: .infinity)
            .frame(height: 34)
            .background(
                Capsule()
                    .fill(selected ? AnyShapeStyle(LinearGradient(colors: category.gradient, startPoint: .leading, endPoint: .trailing)) : AnyShapeStyle(Color.white.opacity(0.62)))
                    .overlay(Capsule().stroke(.white.opacity(0.78), lineWidth: 1))
            )
        }
        .buttonStyle(.plain)
    }

    /// 响应 `toggleRow` 对应的页面选择、展示或交互状态切换。
    private func toggleRow(_ title: String, subtitle: String, key: String) -> some View {
        let done = completedActionIDs.contains(actionKey(key))
        return Button {
            toggleAction(key)
        } label: {
            HStack(spacing: 10) {
                Image(systemName: done ? "checkmark.circle.fill" : "circle")
                    .font(.system(size: 18, weight: .bold))
                    .foregroundStyle(done ? category.gradient.last ?? Color(hex: "20CDB1") : Color(hex: "9BB6C9"))
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
                    .fill(.white.opacity(done ? 0.72 : 0.48))
                    .overlay(
                        RoundedRectangle(cornerRadius: 18, style: .continuous)
                            .stroke(done ? (category.gradient.last ?? Color(hex: "20CDB1")).opacity(0.35) : .white.opacity(0.7), lineWidth: 1)
                    )
            )
        }
        .buttonStyle(.plain)
    }

    /// 构建包含标题、进度条和尾部数值的状态行。
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

    /// 构建报告处理时间线中的单条节点，展示日期、阶段标题和说明。
    private func timelineRow(_ date: String, title: String, detail: String) -> some View {
        HStack(alignment: .top, spacing: 10) {
            VStack(spacing: 4) {
                Circle()
                    .fill(LinearGradient(colors: category.gradient, startPoint: .topLeading, endPoint: .bottomTrailing))
                    .frame(width: 12, height: 12)
                Rectangle()
                    .fill(Color(hex: "B9DDF2").opacity(0.6))
                    .frame(width: 2, height: 34)
            }
            VStack(alignment: .leading, spacing: 3) {
                Text(date)
                    .font(.system(size: 11, weight: .bold))
                    .foregroundStyle(Color(hex: "347FB7"))
                Text(title)
                    .font(.system(size: 13, weight: .bold))
                    .foregroundStyle(Color(hex: "173F64"))
                Text(detail)
                    .font(.system(size: 11))
                    .foregroundStyle(Color(hex: "6C8194"))
                    .lineLimit(2)
            }
            Spacer(minLength: 0)
        }
        .padding(12)
        .background(
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .fill(.white.opacity(0.48))
                .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous).stroke(.white.opacity(0.7), lineWidth: 1))
        )
    }

    /// 构建用于强调分类或状态的紧凑徽标视图。
    private func badge(_ title: String) -> some View {
        Text(title)
            .font(.system(size: 11, weight: .bold))
            .foregroundStyle(Color(hex: "347FB7"))
            .lineLimit(1)
            .minimumScaleFactor(0.76)
            .frame(maxWidth: .infinity)
            .frame(height: 28)
            .background(XAgeCapsuleFill())
    }

    /// 响应 `selectionKey` 对应的页面选择、展示或交互状态切换。
    private func selectionKey(_ value: String) -> String {
        "\(category.id)-\(row.key)-tag-\(value)"
    }

    /// 为报告处理动作生成稳定的本地状态键，避免不同选项相互覆盖。
    private func actionKey(_ value: String) -> String {
        "\(category.id)-\(row.key)-action-\(value)"
    }

    /// 响应 `toggleTag` 对应的页面选择、展示或交互状态切换。
    private func toggleTag(_ value: String) {
        let key = selectionKey(value)
        withAnimation(.spring(response: 0.22, dampingFraction: 0.88)) {
            var next = selectedTagIDs
            if next.contains(key) {
                next.remove(key)
            } else {
                next.insert(key)
            }
            selectedTagIDs = next
        }
    }

    /// 响应 `toggleAction` 对应的页面选择、展示或交互状态切换。
    private func toggleAction(_ value: String) {
        let key = actionKey(value)
        withAnimation(.spring(response: 0.22, dampingFraction: 0.88)) {
            var next = completedActionIDs
            if next.contains(key) {
                next.remove(key)
            } else {
                next.insert(key)
            }
            completedActionIDs = next
        }
    }
}

private struct XAgeReportUploadSourceSheet: View {
    let onCamera: () -> Void
    let onDocument: () -> Void
    let onPhotoLibrary: () -> Void

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
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

    /// 执行 `uploadSourceRow` 对应的文件上传，并衔接上传后的刷新或分析。
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

// MARK: - 报告历史与单份摘要

@MainActor
/// 同时读取体检报告和病例并分别保存，历史页使用同一筛选器在两类资料间切换。
private final class XAgeReportHistoryViewModel: ObservableObject {
    @Published var loading = false
    @Published var reports: [HealthDocument] = []
    @Published var records: [HealthDocument] = []
    @Published var selectedFilter: XAgeReportHistoryFilter = .reports
    @Published var selectedDocument: HealthDocument?
    @Published var errorMessage: String?

    private let repository: HealthDataRepositoryProtocol

    /// 注入健康资料仓库，供报告历史页面并行读取报告和病例。
    init(repository: HealthDataRepositoryProtocol = HealthDataRepository()) {
        self.repository = repository
    }

    var visibleDocuments: [HealthDocument] {
        switch selectedFilter {
        case .reports: return reports
        case .records: return records
        }
    }

    /// 加载或请求 `load` 所需的数据，并返回整理后的结果。
    func load() async {
        // 两类文档并行获取，等待全部结果后一次更新页面状态，减少列表在加载过程中的反复跳动。
        loading = true
        defer { loading = false }
        do {
            async let examDocs = repository.fetchDocuments(docType: "exam")
            async let recordDocs = repository.fetchDocuments(docType: "record")
            let loadedReports = try await examDocs
            let loadedRecords = try await recordDocs
            reports = loadedReports.sortedForXAgeHistory()
            records = loadedRecords.sortedForXAgeHistory()
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}

private enum XAgeReportHistoryFilter: String, CaseIterable, Identifiable {
    case reports = "报告"
    case records = "病历"

    var id: String { rawValue }
}

private struct XAgeReportHistorySheet: View {
    @StateObject private var vm = XAgeReportHistoryViewModel()
    @Environment(\.dismiss) private var dismiss

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
    var body: some View {
        ZStack {
            XAgeLiquidBackground()
                .ignoresSafeArea()

            VStack(alignment: .leading, spacing: 14) {
                HStack {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("历史报告")
                            .font(.system(size: 25, weight: .bold))
                            .foregroundStyle(Color(hex: "123E67"))
                        Text("识别完成后展示单份摘要、异常项和入库状态")
                            .font(.system(size: 13, weight: .medium))
                            .foregroundStyle(Color(hex: "5D7890"))
                    }
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
                    .buttonStyle(.plain)
                    .accessibilityLabel("关闭历史报告")
                }

                HStack(spacing: 8) {
                    ForEach(XAgeReportHistoryFilter.allCases) { filter in
                        Button {
                            withAnimation(.spring(response: 0.22, dampingFraction: 0.88)) {
                                vm.selectedFilter = filter
                            }
                        } label: {
                            Text("\(filter.rawValue) \(count(for: filter))")
                                .font(.system(size: 13, weight: .bold))
                                .foregroundStyle(vm.selectedFilter == filter ? .white : Color(hex: "347FB7"))
                                .frame(maxWidth: .infinity)
                                .frame(height: 36)
                                .background(
                                    Capsule()
                                        .fill(vm.selectedFilter == filter ? AnyShapeStyle(LinearGradient(colors: [Color(hex: "238AD6"), Color(hex: "20CDB1")], startPoint: .leading, endPoint: .trailing)) : AnyShapeStyle(Color.white.opacity(0.62)))
                                        .overlay(Capsule().stroke(.white.opacity(0.78), lineWidth: 1))
                                )
                        }
                        .buttonStyle(.plain)
                    }
                }

                Group {
                    if vm.loading && vm.visibleDocuments.isEmpty {
                        VStack(spacing: 10) {
                            ProgressView()
                                .tint(Color(hex: "18AFA7"))
                            Text("正在读取历史资料")
                                .font(.system(size: 13, weight: .medium))
                                .foregroundStyle(Color(hex: "5D7890"))
                        }
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                        .background(XAgeGlassCardBackground(cornerRadius: 24))
                    } else if vm.visibleDocuments.isEmpty {
                        XAgeReportHistoryEmptyState(filter: vm.selectedFilter)
                    } else {
                        ScrollView {
                            LazyVStack(spacing: 10) {
                                ForEach(vm.visibleDocuments) { document in
                                    Button {
                                        vm.selectedDocument = document
                                    } label: {
                                        XAgeReportHistoryRow(document: document, filter: vm.selectedFilter)
                                    }
                                    .buttonStyle(.plain)
                                }
                            }
                            .padding(2)
                        }
                        .scrollIndicators(.hidden)
                    }
                }
            }
            .padding(24)
        }
        .task { await vm.load() }
        .refreshable { await vm.load() }
        .sheet(item: $vm.selectedDocument) { document in
            XAgeReportDocumentSummarySheet(document: document)
                .presentationDetents([.large])
                .presentationDragIndicator(.visible)
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

    /// 返回指定历史筛选条件下的报告或病例数量。
    private func count(for filter: XAgeReportHistoryFilter) -> Int {
        switch filter {
        case .reports: return vm.reports.count
        case .records: return vm.records.count
        }
    }
}

private struct XAgeReportHistoryEmptyState: View {
    let filter: XAgeReportHistoryFilter

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
    var body: some View {
        VStack(spacing: 10) {
            Image(systemName: filter == .reports ? "doc.text.magnifyingglass" : "list.clipboard.fill")
                .font(.system(size: 28, weight: .bold))
                .foregroundStyle(Color(hex: "347FB7"))
            Text(filter == .reports ? "暂无历史报告" : "暂无历史病历")
                .font(.system(size: 17, weight: .bold))
                .foregroundStyle(Color(hex: "173F64"))
            Text(filter == .reports ? "上传体检、化验或影像资料后，这里会显示单份摘要。" : "上传病历资料后，这里会显示就医时间线摘要。")
                .font(.system(size: 12, weight: .medium))
                .foregroundStyle(Color(hex: "6C8194"))
                .multilineTextAlignment(.center)
                .lineSpacing(3)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(20)
        .background(XAgeGlassCardBackground(cornerRadius: 24))
    }
}

private struct XAgeReportHistoryRow: View {
    let document: HealthDocument
    let filter: XAgeReportHistoryFilter

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .top, spacing: 12) {
                ZStack {
                    Circle()
                        .fill(LinearGradient(colors: [Color(hex: "238AD6"), Color(hex: "20CDB1")], startPoint: .topLeading, endPoint: .bottomTrailing))
                    Image(systemName: filter == .reports ? "doc.text.fill" : "list.clipboard.fill")
                        .font(.system(size: 16, weight: .bold))
                        .foregroundStyle(.white)
                }
                .frame(width: 40, height: 40)

                VStack(alignment: .leading, spacing: 4) {
                    Text(document.xAgeDisplayTitle)
                        .font(.system(size: 16, weight: .bold))
                        .foregroundStyle(Color(hex: "173F64"))
                        .lineLimit(1)
                    Text(document.xAgeDateLabel)
                        .font(.system(size: 12, weight: .medium))
                        .foregroundStyle(Color(hex: "6C8194"))
                }

                Spacer(minLength: 0)

                Text(document.xAgeStatusLabel)
                    .font(.system(size: 11, weight: .bold))
                    .foregroundStyle(document.xAgeStatusColor)
                    .lineLimit(1)
                    .padding(.horizontal, 9)
                    .frame(height: 28)
                    .background(XAgeCapsuleFill())
            }

            Text(document.xAgeBriefSummary)
                .font(.system(size: 12))
                .foregroundStyle(Color(hex: "496A83"))
                .lineSpacing(3)
                .lineLimit(2)
                .fixedSize(horizontal: false, vertical: true)

            HStack(spacing: 8) {
                XAgeReportHistoryBadge(title: "\(document.xAgeAbnormalCount) 项异常", icon: "exclamationmark.triangle.fill")
                XAgeReportHistoryBadge(title: "\(document.xAgeIndicatorCount) 项指标", icon: "list.bullet.rectangle")
                Spacer(minLength: 0)
                Image(systemName: "chevron.right")
                    .font(.system(size: 12, weight: .bold))
                    .foregroundStyle(Color(hex: "7D9AB1"))
            }
        }
        .padding(14)
        .background(XAgeGlassCardBackground(cornerRadius: 22))
    }
}

private struct XAgeReportHistoryBadge: View {
    let title: String
    let icon: String

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
    var body: some View {
        HStack(spacing: 5) {
            Image(systemName: icon)
                .font(.system(size: 10, weight: .bold))
            Text(title)
                .font(.system(size: 11, weight: .bold))
                .lineLimit(1)
        }
        .foregroundStyle(Color(hex: "347FB7"))
        .padding(.horizontal, 9)
        .frame(height: 26)
        .background(XAgeCapsuleFill())
    }
}

private struct XAgeReportDocumentSummarySheet: View {
    let document: HealthDocument
    @Environment(\.dismiss) private var dismiss

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
    var body: some View {
        ZStack {
            XAgeLiquidBackground()
                .ignoresSafeArea()

            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    HStack(alignment: .top) {
                        VStack(alignment: .leading, spacing: 4) {
                            Text(document.xAgeDisplayTitle)
                                .font(.system(size: 24, weight: .bold))
                                .foregroundStyle(Color(hex: "123E67"))
                                .fixedSize(horizontal: false, vertical: true)
                            Text("\(document.xAgeDateLabel) · \(document.xAgeStatusLabel)")
                                .font(.system(size: 13, weight: .medium))
                                .foregroundStyle(Color(hex: "5D7890"))
                        }
                        Spacer()
                        Button {
                            dismiss()
                        } label: {
                            Image(systemName: "xmark")
                                .font(.system(size: 13, weight: .bold))
                                .foregroundStyle(Color(hex: "1268BD"))
                                .frame(width: 44, height: 44)
                                .background {
                                    XAgeCapsuleFill()
                                        .frame(width: 34, height: 34)
                                }
                                .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        .accessibilityLabel("关闭报告摘要")
                    }

                    VStack(alignment: .leading, spacing: 10) {
                        Text("此次报告汇总")
                            .font(.system(size: 17, weight: .bold))
                            .foregroundStyle(Color(hex: "173F64"))
                        Text(document.xAgeDetailedSummary)
                            .font(.system(size: 14))
                            .foregroundStyle(Color(hex: "496A83"))
                            .lineSpacing(4)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    .padding(16)
                    .background(XAgeGlassCardBackground(cornerRadius: 24))

                    VStack(alignment: .leading, spacing: 10) {
                        Text("异常项")
                            .font(.system(size: 17, weight: .bold))
                            .foregroundStyle(Color(hex: "173F64"))
                        if document.xAgeAbnormalFlags.isEmpty {
                            Text("当前资料未提取到异常项。")
                                .font(.system(size: 13, weight: .medium))
                                .foregroundStyle(Color(hex: "6C8194"))
                                .padding(12)
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .background(XAgeCapsuleFill())
                        } else {
                            ForEach(document.xAgeAbnormalFlags.prefix(8)) { flag in
                                HStack(alignment: .top, spacing: 10) {
                                    Image(systemName: "exclamationmark.triangle.fill")
                                        .font(.system(size: 12, weight: .bold))
                                        .foregroundStyle(Color(hex: "F39A34"))
                                        .frame(width: 18, height: 18)
                                    VStack(alignment: .leading, spacing: 2) {
                                        Text(flag.name ?? flag.field ?? "异常指标")
                                            .font(.system(size: 13, weight: .bold))
                                            .foregroundStyle(Color(hex: "173F64"))
                                        Text([flag.value, flag.unit, flag.ref_range].compactMap { $0 }.joined(separator: " "))
                                            .font(.system(size: 12))
                                            .foregroundStyle(Color(hex: "6C8194"))
                                    }
                                    Spacer(minLength: 0)
                                }
                                .padding(12)
                                .background(XAgeCapsuleFill())
                            }
                        }
                    }
                    .padding(16)
                    .background(XAgeGlassCardBackground(cornerRadius: 24))
                }
                .padding(24)
            }
            .scrollIndicators(.hidden)
        }
    }
}

private extension Array where Element == HealthDocument {
    /// 整理 `sortedForXAgeHistory` 涉及的集合内容、顺序或去重结果。
    func sortedForXAgeHistory() -> [HealthDocument] {
        sorted { lhs, rhs in
            (lhs.doc_date ?? lhs.id) > (rhs.doc_date ?? rhs.id)
        }
    }
}

private extension HealthDocument {
    var xAgeDisplayTitle: String {
        let title = (name ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        if !title.isEmpty { return title }
        let urlName = (file_url ?? "").split(separator: "/").last.map(String.init) ?? ""
        if !urlName.isEmpty { return urlName }
        return doc_type == "record" ? "未命名病历" : "未命名报告"
    }

    var xAgeDateLabel: String {
        if let doc_date, !doc_date.isEmpty {
            return Utils.formatDate(doc_date)
        }
        return "日期待确认"
    }

    var xAgeStatusLabel: String {
        switch extraction_status?.lowercased() {
        case "pending": return "识别中"
        case "failed": return "识别失败"
        case "done", "completed", "success": return "已完成"
        default: return "待确认"
        }
    }

    var xAgeStatusColor: Color {
        switch extraction_status?.lowercased() {
        case "pending": return Color(hex: "238AD6")
        case "failed": return Color(hex: "D85A66")
        case "done", "completed", "success": return Color(hex: "18AFA7")
        default: return Color(hex: "6C8194")
        }
    }

    var xAgeAbnormalFlags: [AbnormalFlag] {
        abnormal_flags ?? []
    }

    var xAgeAbnormalCount: Int {
        xAgeAbnormalFlags.count
    }

    var xAgeIndicatorCount: Int {
        csv_data?.rows?.count ?? 0
    }

    var xAgeBriefSummary: String {
        let candidates = [ai_brief, ai_summary]
        if let text = candidates.compactMap({ $0?.trimmingCharacters(in: .whitespacesAndNewlines) }).first(where: { !$0.isEmpty }) {
            return text
        }
        if extraction_status == "pending" {
            return "AI 正在识别这份资料，完成后会显示单份摘要。"
        }
        if xAgeIndicatorCount > 0 {
            return "已提取 \(xAgeIndicatorCount) 项指标，\(xAgeAbnormalCount) 项标记为异常。"
        }
        return "这份资料已入库，暂未生成摘要。"
    }

    var xAgeDetailedSummary: String {
        if let text = ai_summary?.trimmingCharacters(in: .whitespacesAndNewlines), !text.isEmpty {
            return ChatViewModel.cleanAnalysis(text) ?? text
        }
        if let text = ai_brief?.trimmingCharacters(in: .whitespacesAndNewlines), !text.isEmpty {
            return ChatViewModel.cleanAnalysis(text) ?? text
        }
        if extraction_status == "pending" {
            return "这份资料已进入 AI 识别队列。识别完成后，小捷会把可结构化的指标写入趋势，并在这里显示本次报告的关键结论。"
        }
        if xAgeIndicatorCount > 0 || xAgeAbnormalCount > 0 {
            return "本次资料已提取 \(xAgeIndicatorCount) 项指标，其中 \(xAgeAbnormalCount) 项被标记为异常。异常项用于报告复核和问答上下文，完整趋势以数据页最新有效测量时间为准。"
        }
        return "这份资料已保存在健康资料库中，暂未提取到可汇总的结构化内容。"
    }
}

private struct XAgePanelActionRow: View {
    let category: XAgeDataPanelCategory
    let row: XAgePanelRow
    var trailingTitle: String?
    var showsProgress: Bool = false
    var isSelected: Bool = false

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
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

/// 上传前最后确认页，仅展示本地待上传文件的信息；取消不会把文件保存到应用资料库。
private struct XAgeReportUploadConfirmSheet: View {
    let upload: XAgePendingReportUpload
    let isUploading: Bool
    let onCancel: () -> Void
    let onConfirm: () -> Void

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
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

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
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

// MARK: - 评分详情与缺失数据引导

/// 压力、恢复或炎症的详情页，展示指标构成、主要输入和专业依据，并在数据不足时引导补齐来源。
private struct XAgeDataDetailView: View {
    let kind: XAgeDataKind
    let metric: XAgeMetricScore
    let onSyncAppleHealth: () async -> Void
    let onOpenGuide: () -> Void
    @Environment(\.dismiss) private var dismiss

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
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
                            Text("置信度 \(metric.confidence)%")
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

                    if !metric.isReady {
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

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 10) {
                Image(systemName: "tray.and.arrow.up.fill")
                    .font(.system(size: 16, weight: .bold))
                    .foregroundStyle(kind.tint)
                    .frame(width: 34, height: 34)
                    .background(XAgeCapsuleFill())
                VStack(alignment: .leading, spacing: 3) {
                    Text("补齐后再评估")
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

    /// 构建指标说明页操作按钮的图标和标题，并根据样式决定前景色。
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

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
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
                            Text(metric.isReady ? (metric.isProxy ? "代理信号 · 置信度 \(metric.confidence)%" : "综合评分 · 置信度 \(metric.confidence)%") : "待评估 · 置信度 \(metric.confidence)%")
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

// MARK: - AI 健康问答

/// 新版问答分页的状态容器。
/// 它把消息会话、语音输入、报告附件上传、历史对话、详细分析和文献证据统一组织在同一个页面生命周期中。
private struct XAgeConversationSurface: View {
    private static let bottomAnchorID = "xage.chat.bottom"

    @Binding var selectedSection: XAgeTopSection
    let historyRequest: Int
    @StateObject private var vm = ChatViewModel()
    @StateObject private var reportUploadVM = HealthDataViewModel()
    @StateObject private var speechInput = XAgeSpeechInputManager()
    // 分析与证据分别用消息对象驱动 Sheet；附件来源和待确认上传则使用独立状态，避免多个弹层同时出现。
    @State private var selectedAnalysis: ChatMessageItem?
    @State private var selectedEvidence: ChatMessageItem?
    @State private var showCamera = false
    @State private var showPhotoLibrary = false
    @State private var showDocumentPicker = false
    @State private var showAttachmentMenu = false
    @State private var pendingUpload: XAgePendingReportUpload?
    @State private var uploadQualityWarning: String?
    @FocusState private var inputFocused: Bool

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
    var body: some View {
        ZStack(alignment: .bottomTrailing) {
            VStack(spacing: 0) {
                ScrollViewReader { proxy in
                    ScrollView {
                        LazyVStack(spacing: 12) {
                            if vm.messages.isEmpty {
                                XAgeChatWelcome(vm: vm)
                                    .padding(.top, 34)
                            }

                            ForEach(vm.messages) { msg in
                                // 每条消息保留重试、分析和证据三个独立动作，失败消息可直接复用原请求内容再次发送。
                                XAgeChatBubble(
                                    message: msg,
                                    onRetry: { Task { await vm.retryMessage(id: msg.id) } },
                                    onAnalysis: { selectedAnalysis = msg },
                                    onEvidence: { selectedEvidence = msg }
                                )
                                .id(msg.id)
                            }

                            if reportUploadVM.uploading || reportUploadVM.backgroundTaskHint != nil {
                                XAgeChatUploadStatusCard(
                                    uploading: reportUploadVM.uploading,
                                    title: reportUploadVM.uploading
                                        ? (reportUploadVM.uploadStage.isEmpty ? "正在上传报告…" : reportUploadVM.uploadStage)
                                        : "报告已上传，AI 正在识别",
                                    subtitle: reportUploadVM.backgroundTaskHint ?? "完成后会继续进入问答解读。"
                                )
                                .id("xage.upload.status")
                            }

                            if vm.sending {
                                // 请求进行中展示后端思考阶段，并随进度变化自动滚动到底部。
                                XAgeChatThinkingCard(
                                    currentHint: vm.thinkingHint.isEmpty ? "正在思考…" : vm.thinkingHint,
                                    steps: vm.thinkingProgressItems
                                )
                                .id("xage.chat.thinking")
                            }

                            Color.clear
                                .frame(height: 1)
                                .id(Self.bottomAnchorID)
                        }
                        .padding(.horizontal, 24)
                        .padding(.bottom, 96)
                    }
                    .scrollIndicators(.hidden)
                    .scrollDismissesKeyboard(.interactively)
                    .scrollBounceBehavior(.always, axes: .vertical)
                    .simultaneousGesture(
                        TapGesture().onEnded {
                            inputFocused = false
                        }
                    )
                    .background(
                        Color.clear
                            .contentShape(Rectangle())
                            .onTapGesture {
                                inputFocused = false
                            }
                    )
                    .background {
                        XAgeVerticalKeyboardDismissInstaller {
                            inputFocused = false
                            XAgeKeyboard.dismiss()
                        }
                        .frame(width: 0, height: 0)
                    }
                    .accessibilityIdentifier("xage.chat.scroll")
                    .onChange(of: vm.messages.count) { _, _ in
                        scrollToBottom(proxy)
                    }
                    .onChange(of: vm.sending) { _, _ in
                        scrollToBottom(proxy)
                    }
                    .onChange(of: vm.thinkingStepIndex) { _, _ in
                        scrollToBottom(proxy)
                    }
                    .onChange(of: reportUploadVM.uploading) { _, _ in
                        scrollToBottom(proxy)
                    }
                    .onChange(of: reportUploadVM.backgroundTaskHint ?? "") { _, _ in
                        scrollToBottom(proxy)
                    }
                }

                XAgeChatInputBar(
                    vm: vm,
                    isRecording: speechInput.isRecording,
                    isUploading: reportUploadVM.uploading,
                    inputFocused: $inputFocused,
                    onMicTap: toggleSpeechInput,
                    onPlusTap: {
                        inputFocused = false
                        XAgeKeyboard.dismiss()
                        withAnimation(.spring(response: 0.22, dampingFraction: 0.9)) {
                            showAttachmentMenu.toggle()
                        }
                    }
                )
                .padding(.horizontal, 24)
                .padding(.bottom, 20)
            }

            if showAttachmentMenu {
                attachmentMenuOverlay
                    .transition(.opacity)
                    .zIndex(5)
            }
        }
        .task { await vm.loadConversations(showErrors: false) }
        .onChange(of: historyRequest) { _, _ in
            // 顶栏通过递增请求计数触发历史页，不直接持有聊天子页面的 Sheet 状态。
            openHistorySheet()
        }
        .onChange(of: selectedSection) { _, section in
            guard section != .chat else { return }
            inputFocused = false
            showAttachmentMenu = false
        }
        .fullScreenCover(isPresented: $showCamera) {
            CameraImagePicker(
                onPick: { data, name in
                    preparePendingReportUpload(
                        files: [XAgeReportUploadFile(data: data, fileName: name)],
                        title: "确认数据上传",
                        source: "相机"
                    )
                },
                fileNamePrefix: "xage_report_camera"
            )
            .ignoresSafeArea()
        }
        .sheet(isPresented: $showPhotoLibrary) {
            MultiPhotoPicker(
                selectionLimit: 9,
                fileNamePrefix: "xage_report_album",
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
        .sheet(item: $pendingUpload) { upload in
            XAgeReportUploadConfirmSheet(
                upload: upload,
                isUploading: reportUploadVM.uploading,
                onCancel: { pendingUpload = nil },
                onConfirm: {
                    pendingUpload = nil
                    uploadReports(upload.files)
                }
            )
            .presentationDetents([.medium, .large])
            .presentationDragIndicator(.visible)
        }
        .sheet(isPresented: $vm.showHistory) {
            XAgeChatHistorySheet(vm: vm)
                .presentationDetents([.medium, .large])
                .presentationDragIndicator(.visible)
        }
        .sheet(item: $selectedAnalysis) { msg in
            XAgeAnalysisSheet(message: msg)
                .presentationDetents([.large])
                .presentationDragIndicator(.visible)
        }
        .sheet(item: $selectedEvidence) { msg in
            XAgeEvidenceSheet(message: msg)
                .presentationDetents([.large])
                .presentationDragIndicator(.visible)
        }
        .alert("语音输入", isPresented: Binding(
            get: { speechInput.errorMessage != nil },
            set: { if !$0 { speechInput.errorMessage = nil } }
        )) {
            Button("确定", role: .cancel) {}
        } message: {
            Text(speechInput.errorMessage ?? "")
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
        .alert("上传失败", isPresented: Binding(
            get: { reportUploadVM.errorMessage != nil },
            set: { if !$0 { reportUploadVM.errorMessage = nil } }
        )) {
            Button("确定", role: .cancel) {}
        } message: {
            Text(reportUploadVM.errorMessage ?? "")
        }
        .alert("开启 AI 健康问答", isPresented: $vm.showAIConsentPrompt) {
            // 首次需要读取健康档案时暂停原消息；明确同意后由 ViewModel 恢复并重试刚才的请求。
            Button("暂不开启", role: .cancel) { vm.declineAIConsent() }
            Button("同意并继续") { Task { await vm.grantAIConsentAndRetry() } }
        } message: {
            Text("小捷需要读取你已授权的健康档案和当前会话来生成个性化回答。只有你明确同意后才会继续处理这条消息。")
        }
        .alert("提示", isPresented: Binding(
            get: { vm.errorMessage != nil },
            set: { if !$0 { vm.errorMessage = nil } }
        )) {
            Button("确定", role: .cancel) {}
        } message: {
            Text(vm.errorMessage ?? "")
        }
    }

    /// 响应 `scrollToBottom` 对应的页面选择、展示或交互状态切换。
    private func scrollToBottom(_ proxy: ScrollViewProxy, animated: Bool = true) {
        // 消息、思考阶段和上传状态都可能改变内容高度，统一延迟到下一主线程周期再定位底部锚点。
        DispatchQueue.main.async {
            if animated {
                withAnimation(.easeOut(duration: 0.22)) {
                    proxy.scrollTo(Self.bottomAnchorID, anchor: .bottom)
                }
            } else {
                proxy.scrollTo(Self.bottomAnchorID, anchor: .bottom)
            }
        }
    }

    /// 构建 `attachmentMenuOverlay` 对应的局部 SwiftUI 视图，并组合所需的展示状态与交互。
    private var attachmentMenuOverlay: some View {
        ZStack(alignment: .bottomTrailing) {
            Color.black.opacity(0.001)
                .ignoresSafeArea()
                .onTapGesture {
                    withAnimation(.spring(response: 0.22, dampingFraction: 0.9)) {
                        showAttachmentMenu = false
                    }
                }

            XAgeAttachmentMenu(
                isNewChatEnabled: !vm.sending,
                onCamera: { presentAttachmentActionAfterMenu(.camera) },
                onDocument: { presentAttachmentActionAfterMenu(.documentPicker) },
                onPhotoLibrary: { presentAttachmentActionAfterMenu(.photoLibrary) },
                onNewChat: { presentAttachmentActionAfterMenu(.newChat) }
            )
            .padding(.trailing, 42)
            .padding(.bottom, 88)
        }
    }

    private enum XAgeAttachmentAction {
        case camera
        case documentPicker
        case photoLibrary
        case newChat
    }

    /// 响应 `presentAttachmentActionAfterMenu` 对应的页面选择、展示或交互状态切换。
    private func presentAttachmentActionAfterMenu(_ action: XAgeAttachmentAction) {
        // 先收起自定义附件菜单，待动画结束后再打开系统选择器，防止两种呈现层级发生冲突。
        showAttachmentMenu = false
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.35) {
            performAttachmentAction(action)
        }
    }

    /// 根据附件来源启动相机、相册或文件选择器，并在切换前收起键盘。
    private func performAttachmentAction(_ action: XAgeAttachmentAction) {
        switch action {
        case .camera:
            showCamera = true
        case .documentPicker:
            showDocumentPicker = true
        case .photoLibrary:
            showPhotoLibrary = true
        case .newChat:
            vm.newChat()
        }
    }

    /// 响应 `openHistorySheet` 对应的页面选择、展示或交互状态切换。
    private func openHistorySheet() {
        // 只允许在问答分页响应顶栏请求；打开前结束键盘与附件菜单，并刷新会话列表。
        guard selectedSection == .chat else { return }
        inputFocused = false
        XAgeKeyboard.dismiss()
        showAttachmentMenu = false
        vm.showHistory = true
        Task { await vm.loadConversations(showErrors: false) }
    }

    /// 响应 `toggleSpeechInput` 对应的页面选择、展示或交互状态切换。
    private func toggleSpeechInput() {
        // 再次点击麦克风表示停止；开始录音前收起文本键盘，识别结果直接回填输入框，仍由用户确认发送。
        if speechInput.isRecording {
            speechInput.stop()
            return
        }
        inputFocused = false
        XAgeKeyboard.dismiss()
        speechInput.start { recognizedText in
            vm.inputValue = recognizedText
        }
    }

    /// 准备 `preparePendingReportUpload` 后续流程所需的数据和页面状态。
    private func preparePendingReportUpload(files: [XAgeReportUploadFile], title: String, source: String) {
        // 问答附件沿用资料中心的质量检查和确认模型；通过确认前不会上传或自动发送聊天消息。
        guard !files.isEmpty else { return }
        for file in files {
            if let warning = validateReportImageQuality(data: file.data, fileName: file.fileName) {
                uploadQualityWarning = "\(file.fileName)：\(warning)"
                return
            }
        }
        let upload = XAgePendingReportUpload(title: title, source: source, files: files)
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.25) {
            pendingUpload = upload
        }
    }

    /// 执行 `uploadReports` 对应的文件上传，并衔接上传后的刷新或分析。
    private func uploadReports(_ files: [XAgeReportUploadFile]) {
        // 附件上传属于健康资料入库流程；页面只显示上传/后台识别状态，不把原始二进制直接塞入聊天文本。
        guard !files.isEmpty else { return }
        inputFocused = false
        XAgeKeyboard.dismiss()
        reportUploadVM.uploadDocType = "exam"
        Task {
            var uploaded: [(fileName: String, documentId: String)] = []
            for file in files {
                if let doc = await reportUploadVM.uploadFile(data: file.data, fileName: file.fileName) {
                    uploaded.append((file.fileName, doc.id))
                }
            }
            if !uploaded.isEmpty {
                let prompt = reportAnalysisPrompt(uploaded: uploaded)
                if vm.sending {
                    vm.inputValue = prompt
                } else {
                    await vm.sendText(prompt)
                }
            }
        }
    }

    /// 根据已上传文档 ID 生成发送给 AI 的报告分析提示词。
    private func reportAnalysisPrompt(uploaded: [(fileName: String, documentId: String)]) -> String {
        if uploaded.count == 1, let item = uploaded.first {
            return "我刚上传了一份体检/化验报告（\(item.fileName)，文档ID：\(item.documentId)）。请结合我的健康档案和这份报告的识别结果，帮我总结关键指标、异常项、趋势变化和下一步建议。若后台识别仍在进行，请先说明正在识别，并告诉我完成后应该重点关注哪些项目。"
        }
        let list = uploaded
            .map { "\($0.fileName)，文档ID：\($0.documentId)" }
            .joined(separator: "；")
        return "我刚上传了 \(uploaded.count) 张/份体检化验报告（\(list)）。请把这些报告作为同一批资料，结合我的健康档案总结关键指标、异常项、同批次之间的重复/互补信息和下一步建议。若后台识别仍在进行，请先说明正在识别，并告诉我完成后应该重点关注哪些项目。"
    }

    /// 校验 `validateReportImageQuality` 对应的条件，决定数据或操作是否可以继续使用。
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

}

private struct XAgeChatThinkingCard: View {
    let currentHint: String
    let steps: [String]

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            XAgeAssistantOrb()
                .frame(width: 34, height: 34)

            VStack(alignment: .leading, spacing: 9) {
                HStack(spacing: 7) {
                    ProgressView()
                        .controlSize(.small)
                        .tint(Color(hex: "18AFA7"))
                    Text(currentHint)
                        .font(.system(size: 13, weight: .bold))
                        .foregroundStyle(Color(hex: "173F64"))
                        .lineLimit(2)
                        .fixedSize(horizontal: false, vertical: true)
                }

                VStack(alignment: .leading, spacing: 6) {
                    ForEach(Array(steps.enumerated()), id: \.offset) { index, step in
                        HStack(alignment: .top, spacing: 7) {
                            Image(systemName: index == steps.count - 1 ? "ellipsis.circle.fill" : "checkmark.circle.fill")
                                .font(.system(size: 12, weight: .bold))
                                .foregroundStyle(index == steps.count - 1 ? Color(hex: "238AD6") : Color(hex: "20CDB1"))
                                .frame(width: 16, height: 16)
                            Text(step)
                                .font(.system(size: 12, weight: .medium))
                                .foregroundStyle(Color(hex: "5D7890"))
                                .lineLimit(2)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                }
            }
            .padding(14)
            .background(XAgeGlassCardBackground(cornerRadius: 22))

            Spacer(minLength: 0)
        }
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("xage.chat.thinking.card")
    }
}

private struct XAgeChatWelcome: View {
    @ObservedObject var vm: ChatViewModel

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 16) {
                XAgeAssistantOrb()
                    .frame(width: 40, height: 40)
                VStack(alignment: .leading, spacing: 4) {
                    Text("下午好，想问什么？")
                        .font(.system(size: 25, weight: .bold))
                        .foregroundStyle(Color(hex: "111827"))
                        .lineLimit(1)
                        .minimumScaleFactor(0.85)
                    Text("小捷先帮你问清关键问题。")
                        .font(.system(size: 12))
                        .foregroundStyle(Color(hex: "637083"))
                        .lineLimit(1)
                }
            }

            Spacer()
                .frame(height: 50)

            Text("你可以这样问")
                .font(.system(size: 21, weight: .bold))
                .foregroundStyle(Color(hex: "111827"))
                .lineLimit(1)

            Spacer()
                .frame(height: 28)

            Button {
                vm.inputValue = "帮我整理病史摘要"
                Task { await vm.sendMessage() }
            } label: {
                XAgeStarterRow(icon: "doc.text", title: "整理病史摘要", subtitle: "诊断、用药、过敏信息", primary: true)
            }
            .buttonStyle(.plain)
            .disabled(vm.sending)

            Spacer()
                .frame(height: 32)

            Button {
                vm.inputValue = "帮我分析最近报告趋势"
                Task { await vm.sendMessage() }
            } label: {
                XAgeStarterRow(icon: "chart.bar", title: "分析报告趋势", subtitle: nil, primary: false)
            }
            .buttonStyle(.plain)
            .disabled(vm.sending)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

private struct XAgeStarterRow: View {
    let icon: String
    let title: String
    let subtitle: String?
    let primary: Bool

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: icon)
                .font(.system(size: 19, weight: .semibold))
                .foregroundStyle(Color.appPrimary)
                .frame(width: 36, height: 36)
                .background(
                    Circle()
                        .fill(Color(hex: "E7FAFF").opacity(0.46))
                        .overlay(Circle().stroke(.white.opacity(0.62), lineWidth: 1))
                )
            VStack(alignment: .leading, spacing: 3) {
                Text(title)
                    .font(.system(size: 18, weight: .bold))
                    .foregroundStyle(Color(hex: "111827"))
                    .lineLimit(1)
                if let subtitle {
                    Text(subtitle)
                        .font(.system(size: 12))
                        .foregroundStyle(Color(hex: "637083"))
                        .lineLimit(1)
                }
            }
            Spacer(minLength: 8)
            Image(systemName: "chevron.right")
                .font(.system(size: 20, weight: .bold))
                .foregroundStyle(Color(hex: "6F7F91").opacity(0.72))
                .frame(width: 24, height: 24)
        }
        .padding(.horizontal, 18)
        .frame(height: primary ? 84 : 66)
        .background(XAgeGlassCardBackground(cornerRadius: primary ? 34 : 33))
    }
}

private struct XAgeAssistantOrb: View {
    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
    var body: some View {
        ZStack {
            Circle()
                .fill(.white.opacity(0.42))
                .shadow(color: Color(hex: "00C9A7").opacity(0.25), radius: 16, x: 0, y: 8)
            RoundedRectangle(cornerRadius: 9, style: .continuous)
                .fill(
                    LinearGradient(
                        colors: [Color(hex: "00C9A7"), Color(hex: "1565C0")],
                        startPoint: .topLeading,
                        endPoint: .bottomTrailing
                    )
                )
                .frame(width: 20, height: 20)
            Capsule()
                .fill(.white.opacity(0.26))
                .frame(width: 10, height: 28)
                .blur(radius: 1)
                .offset(x: 8, y: -4)
        }
    }
}

private struct XAgeChatBubble: View {
    let message: ChatMessageItem
    let onRetry: () -> Void
    let onAnalysis: () -> Void
    let onEvidence: () -> Void

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
    var body: some View {
        let isUser = message.role == "user"
        HStack {
            if isUser { Spacer(minLength: 44) }
            VStack(alignment: isUser ? .trailing : .leading, spacing: 8) {
                Group {
                    if isUser {
                        Text(message.content)
                    } else {
                        Text(renderedAssistantContent)
                    }
                }
                    .font(.system(size: 15, weight: isUser ? .semibold : .regular))
                    .foregroundStyle(isUser ? .white : Color(hex: "244E6D"))
                    .lineSpacing(2)
                    .padding(.horizontal, isUser ? 15 : 15)
                    .padding(.vertical, isUser ? 11 : 14)
                    .background(
                        RoundedRectangle(cornerRadius: isUser ? 24 : 20, style: .continuous)
                            .fill(isUser ? AnyShapeStyle(LinearGradient(colors: [Color(hex: "238AD6"), Color(hex: "20CDB1")], startPoint: .topLeading, endPoint: .bottomTrailing)) : AnyShapeStyle(.white.opacity(0.56)))
                            .overlay(
                                RoundedRectangle(cornerRadius: isUser ? 24 : 20, style: .continuous)
                                    .stroke(.white.opacity(0.72), lineWidth: 1)
                            )
                    )
                    .fixedSize(horizontal: false, vertical: true)

                if let status = message.status {
                    HStack(spacing: 8) {
                        Text(status.rawValue)
                            .font(.system(size: 11, weight: .medium))
                            .foregroundStyle(isUser ? .white.opacity(0.82) : Color(hex: "6C8194"))
                        if status == .failed {
                            Button("重试", action: onRetry)
                                .font(.system(size: 11, weight: .bold))
                        }
                    }
                }

                if !isUser {
                    HStack(spacing: 8) {
                        if message.hasDistinctAnalysis {
                            CapsuleButton(title: "查看分析", action: onAnalysis)
                        }
                        if !message.relevantCitations.isEmpty {
                            CapsuleButton(title: "证据展示", action: onEvidence)
                        }
                    }
                }
            }
            if !isUser { Spacer(minLength: 44) }
        }
    }

    private var renderedAssistantContent: AttributedString {
        (try? AttributedString(
            markdown: message.content,
            options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace)
        )) ?? AttributedString(message.content)
    }
}

/// 问答输入栏同时处理文本、麦克风、附件入口和发送状态；上传或发送期间会禁用可能造成重复请求的操作。
private struct XAgeChatInputBar: View {
    @ObservedObject var vm: ChatViewModel
    let isRecording: Bool
    let isUploading: Bool
    var inputFocused: FocusState<Bool>.Binding
    let onMicTap: () -> Void
    let onPlusTap: () -> Void

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
    var body: some View {
        HStack(alignment: .bottom, spacing: 8) {
            Button(action: onMicTap) {
                Image(systemName: isRecording ? "stop.circle.fill" : "mic.fill")
                    .frame(width: 32, height: 32)
            }
            .frame(width: 44, height: 44)
            .contentShape(Rectangle())
            .buttonStyle(.plain)
            .foregroundStyle(isRecording ? Color(hex: "12B59C") : Color(hex: "172033"))
            .accessibilityIdentifier("xage.chat.mic")
            .accessibilityLabel(isRecording ? "停止语音输入" : "语音输入")

            TextField("输入或长按说话", text: $vm.inputValue, axis: .vertical)
                .font(.system(size: 15))
                .textFieldStyle(.plain)
                .lineLimit(1...5)
                .padding(.vertical, 11)
                .frame(minHeight: 44)
                .focused(inputFocused)
                .submitLabel(.send)
                .onSubmit(sendCurrentInput)
                .accessibilityIdentifier("xage.chat.input")

            Button(action: onPlusTap) {
                Image(systemName: "plus")
                    .font(.system(size: 19, weight: .semibold))
                    .frame(width: 32, height: 32)
                    .background(
                        Circle()
                            .fill(.white.opacity(0.58))
                            .overlay(Circle().stroke(.white.opacity(0.7), lineWidth: 1))
                    )
            }
            .frame(width: 44, height: 44)
            .contentShape(Rectangle())
            .buttonStyle(.plain)
            .foregroundStyle(Color(hex: "172033"))
            .disabled(isUploading)
            .accessibilityIdentifier("xage.chat.plus")
            .accessibilityLabel("添加内容")

            Button {
                sendCurrentInput()
            } label: {
                Image(systemName: "paperplane.fill")
                    .font(.system(size: 17, weight: .bold))
                    .offset(x: -1, y: 1)
                    .frame(width: 36, height: 36)
                    .background(
                        Circle()
                            .fill(LinearGradient(colors: [Color(hex: "228DD8"), Color(hex: "1DC8AE")], startPoint: .topLeading, endPoint: .bottomTrailing))
                    )
                    .foregroundStyle(.white)
            }
            .frame(width: 44, height: 44)
            .contentShape(Rectangle())
            .buttonStyle(.plain)
            .disabled(vm.inputValue.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || vm.sending)
            .accessibilityIdentifier("xage.chat.send")
            .accessibilityLabel("发送")
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 7)
        .frame(minHeight: 58)
        .background(XAgeGlassCardBackground(cornerRadius: 29))
    }

    /// 读取当前输入并发送聊天消息，发送后清理输入状态并滚动到最新消息。
    private func sendCurrentInput() {
        // 先由 ViewModel 原子地取出可发送文本，随后让出一次主线程清理输入框，再执行异步发送，避免连点重复提交。
        guard let text = vm.consumeInputForSending() else { return }
        inputFocused.wrappedValue = false
        Task { @MainActor in
            await Task.yield()
            if vm.inputValue.trimmingCharacters(in: .whitespacesAndNewlines) == text {
                vm.inputValue = ""
            }
            await vm.sendText(text)
        }
    }
}

private struct XAgeAttachmentMenu: View {
    let isNewChatEnabled: Bool
    let onCamera: () -> Void
    let onDocument: () -> Void
    let onPhotoLibrary: () -> Void
    let onNewChat: () -> Void

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
    var body: some View {
        VStack(spacing: 8) {
            Text("添加内容")
                .font(.system(size: 13, weight: .bold))
                .foregroundStyle(Color(hex: "173F64"))
                .frame(maxWidth: .infinity)
                .padding(.bottom, 2)

            menuButton(
                title: "拍照采集报告",
                icon: "camera.fill",
                identifier: "xage.chat.attachment.camera",
                action: onCamera
            )
            menuButton(
                title: "数据上传 PDF / 图片",
                icon: "doc.badge.plus",
                identifier: "xage.chat.attachment.documents",
                action: onDocument
            )
            menuButton(
                title: "从相册上传报告",
                icon: "photo.on.rectangle.angled",
                identifier: "xage.chat.attachment.photos",
                action: onPhotoLibrary
            )
            menuButton(
                title: "新对话",
                icon: "plus.message.fill",
                identifier: "xage.chat.attachment.new",
                isEnabled: isNewChatEnabled,
                action: onNewChat
            )
        }
        .padding(12)
        .frame(width: 220)
        .background(XAgeGlassCardBackground(cornerRadius: 26))
        .shadow(color: Color(hex: "7CCAF5").opacity(0.22), radius: 22, x: 0, y: 10)
        .accessibilityElement(children: .contain)
    }

    /// 构建聊天附件菜单按钮，并统一图标、标题、可用状态和点击行为。
    private func menuButton(
        title: String,
        icon: String,
        identifier: String,
        isEnabled: Bool = true,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            HStack(spacing: 9) {
                Image(systemName: icon)
                    .font(.system(size: 13, weight: .bold))
                    .foregroundStyle(Color(hex: "237FC4"))
                    .frame(width: 22, height: 22)
                Text(title)
                    .font(.system(size: 14, weight: .bold))
                    .foregroundStyle(Color(hex: "173F64"))
                    .lineLimit(1)
                    .minimumScaleFactor(0.82)
                Spacer(minLength: 0)
            }
            .padding(.horizontal, 12)
            .frame(height: 44)
            .background(XAgeCapsuleFill())
        }
        .buttonStyle(.plain)
        .disabled(!isEnabled)
        .opacity(isEnabled ? 1 : 0.45)
        .accessibilityIdentifier(identifier)
    }
}

// MARK: - 历史对话与回答详情

/// 历史会话列表由现有 ChatViewModel 提供；选择会话后加载其消息并关闭 Sheet，回到同一个问答页面继续交流。
private struct XAgeChatHistorySheet: View {
    @ObservedObject var vm: ChatViewModel
    @Environment(\.dismiss) private var dismiss

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
    var body: some View {
        ZStack {
            XAgeLiquidBackground()
                .ignoresSafeArea()

            VStack(alignment: .leading, spacing: 18) {
                HStack {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("历史对话")
                            .font(.system(size: 24, weight: .bold))
                            .foregroundStyle(Color(hex: "173F64"))
                        Text("继续之前的健康问答")
                            .font(.system(size: 13, weight: .medium))
                            .foregroundStyle(Color(hex: "5D7890"))
                    }

                    Spacer()

                    Button {
                        vm.showHistory = false
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
                    .accessibilityIdentifier("xage.chat.history.close")
                    .accessibilityLabel("关闭历史对话")
                }

                ScrollView {
                    LazyVStack(spacing: 12) {
                        if vm.conversations.isEmpty {
                            emptyState
                        } else {
                            ForEach(vm.conversations) { conversation in
                                Button {
                                    Task {
                                        await vm.loadConversation(id: conversation.id)
                                        vm.showHistory = false
                                        dismiss()
                                    }
                                } label: {
                                    conversationRow(conversation)
                                }
                                .buttonStyle(.plain)
                                .accessibilityIdentifier("xage.chat.history.row.\(conversation.id)")
                            }

                            if vm.hasMoreConversations {
                                Button {
                                    Task { await vm.loadMoreConversations() }
                                } label: {
                                    HStack(spacing: 8) {
                                        Image(systemName: "arrow.down.circle.fill")
                                            .font(.system(size: 15, weight: .bold))
                                        Text("加载更多")
                                            .font(.system(size: 15, weight: .bold))
                                    }
                                    .foregroundStyle(Color(hex: "237FC4"))
                                    .frame(maxWidth: .infinity)
                                    .frame(height: 48)
                                    .background(XAgeCapsuleFill())
                                }
                                .buttonStyle(.plain)
                                .accessibilityIdentifier("xage.chat.history.more")
                            }
                        }
                    }
                    .padding(.bottom, 24)
                }
                .scrollIndicators(.hidden)
            }
            .padding(.horizontal, 24)
            .padding(.top, 24)
        }
        .accessibilityIdentifier("xage.chat.history.sheet")
    }

    /// 构建 `emptyState` 对应的局部 SwiftUI 视图，并组合所需的展示状态与交互。
    private var emptyState: some View {
        VStack(spacing: 12) {
            ZStack {
                Circle()
                    .fill(Color(hex: "6CD8DA").opacity(0.22))
                    .frame(width: 54, height: 54)
                Image(systemName: "clock.arrow.circlepath")
                    .font(.system(size: 24, weight: .bold))
                    .foregroundStyle(Color(hex: "237FC4"))
            }

            Text("暂无历史对话")
                .font(.system(size: 18, weight: .bold))
                .foregroundStyle(Color(hex: "173F64"))

            Text("登录并完成问答后，会在这里继续查看历史记录。")
                .font(.system(size: 13))
                .foregroundStyle(Color(hex: "5D7890"))
                .multilineTextAlignment(.center)
                .lineSpacing(3)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 34)
        .padding(.horizontal, 18)
        .background(XAgeGlassCardBackground(cornerRadius: 26))
    }

    /// 构建单条历史会话记录，并绑定加载会话和删除操作。
    private func conversationRow(_ conversation: ChatConversation) -> some View {
        HStack(spacing: 12) {
            ZStack {
                Circle()
                    .fill(Color(hex: "25C8BE").opacity(0.18))
                    .frame(width: 42, height: 42)
                Image(systemName: "bubble.left.and.bubble.right.fill")
                    .font(.system(size: 17, weight: .bold))
                    .foregroundStyle(Color(hex: "159D8F"))
            }

            VStack(alignment: .leading, spacing: 6) {
                Text(conversation.title ?? "健康问答")
                    .font(.system(size: 16, weight: .bold))
                    .foregroundStyle(Color(hex: "173F64"))
                    .lineLimit(2)

                HStack(spacing: 8) {
                    Text("\(conversation.message_count ?? 0) 条消息")
                    if let timestamp = conversation.updated_at ?? conversation.created_at {
                        Text("·")
                        Text(Self.formatTimestamp(timestamp))
                    }
                }
                .font(.system(size: 12, weight: .medium))
                .foregroundStyle(Color(hex: "6F879B"))
            }

            Spacer(minLength: 8)

            Image(systemName: "chevron.right")
                .font(.system(size: 13, weight: .bold))
                .foregroundStyle(Color(hex: "8BA6BA"))
        }
        .padding(16)
        .background(XAgeGlassCardBackground(cornerRadius: 24))
    }

    /// 将 `formatTimestamp` 的输入整理为页面可直接展示或使用的格式。
    private static func formatTimestamp(_ iso: String) -> String {
        let fractional = ISO8601DateFormatter()
        fractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        guard let date = fractional.date(from: iso) ?? ISO8601DateFormatter().date(from: iso) else {
            return String(iso.prefix(10))
        }

        let diff = Date().timeIntervalSince(date)
        if diff < 60 { return "刚刚" }
        if diff < 3600 { return "\(Int(diff / 60))分钟前" }
        if diff < 86400 { return "\(Int(diff / 3600))小时前" }
        if diff < 86400 * 7 { return "\(Int(diff / 86400))天前" }

        let formatter = DateFormatter()
        formatter.dateFormat = "MM-dd HH:mm"
        return formatter.string(from: date)
    }
}

private struct XAgeChatUploadStatusCard: View {
    let uploading: Bool
    let title: String
    let subtitle: String

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            ZStack {
                Circle()
                    .fill(.white.opacity(0.52))
                    .overlay(Circle().stroke(.white.opacity(0.7), lineWidth: 1))
                    .frame(width: 34, height: 34)
                if uploading {
                    ProgressView()
                        .controlSize(.small)
                } else {
                    Image(systemName: "sparkles")
                        .font(.system(size: 15, weight: .bold))
                        .foregroundStyle(Color(hex: "159D8F"))
                }
            }

            VStack(alignment: .leading, spacing: 4) {
                Text(title)
                    .font(.system(size: 14, weight: .bold))
                    .foregroundStyle(Color(hex: "173F64"))
                    .lineLimit(2)
                Text(subtitle)
                    .font(.system(size: 12))
                    .foregroundStyle(Color(hex: "5D7890"))
                    .lineLimit(3)
            }
            Spacer(minLength: 0)
        }
        .padding(14)
        .background(XAgeGlassCardBackground(cornerRadius: 22))
        .accessibilityIdentifier("xage.chat.upload.status")
    }
}

// MARK: - 语音输入

@MainActor
/// 中文语音转文字管理器。语音识别权限和麦克风权限均通过后才创建音频管线，识别结果只回填输入框。
private final class XAgeSpeechInputManager: NSObject, ObservableObject {
    @Published var isRecording = false
    @Published var errorMessage: String?

    private let recognizer = SFSpeechRecognizer(locale: Locale(identifier: "zh-CN"))
    private let audioEngine = AVAudioEngine()
    private var recognitionRequest: SFSpeechAudioBufferRecognitionRequest?
    private var recognitionTask: SFSpeechRecognitionTask?
    private var onResult: ((String) -> Void)?

    /// 启动当前服务或采集流程，并通过回调持续返回结果。
    func start(onResult: @escaping (String) -> Void) {
        // 权限按“语音识别 → 麦克风”顺序申请，任一权限被拒绝都会停止流程并给出可操作提示。
        guard !isRecording else { return }
        self.onResult = onResult
        SFSpeechRecognizer.requestAuthorization { [weak self] status in
            DispatchQueue.main.async {
                guard let self else { return }
                guard status == .authorized else {
                    self.errorMessage = "请在系统设置中允许语音识别权限。"
                    return
                }
                self.requestRecordPermission()
            }
        }
    }

    /// 发起 `requestRecordPermission` 对应的权限、关闭或状态变更请求。
    private func requestRecordPermission() {
        if #available(iOS 17.0, *) {
            AVAudioApplication.requestRecordPermission { [weak self] allowed in
                Task { @MainActor in
                    self?.handleRecordPermission(allowed)
                }
            }
        } else {
            AVAudioSession.sharedInstance().requestRecordPermission { [weak self] allowed in
                DispatchQueue.main.async {
                    self?.handleRecordPermission(allowed)
                }
            }
        }
    }

    /// 处理 `handleRecordPermission` 对应的用户操作或系统回调，并推进后续流程。
    private func handleRecordPermission(_ allowed: Bool) {
        guard allowed else {
            errorMessage = "请在系统设置中允许麦克风权限。"
            return
        }
        startRecording()
    }

    /// 停止当前服务或采集流程，并释放相关运行状态。
    func stop() {
        stopRecording(cancelTask: true)
    }

    /// 配置音频会话和识别请求后启动录音，将识别文本持续回传给输入框。
    private func startRecording() {
        // 每次启动前取消旧识别任务并重建 request，避免音频缓冲被前一次会话继续消费。
        guard recognizer?.isAvailable == true else {
            errorMessage = "当前设备语音识别暂不可用。"
            return
        }

#if targetEnvironment(simulator)
        errorMessage = "模拟器无法进行真实语音输入，请在真机上使用麦克风。"
        return
#else
        recognitionTask?.cancel()
        recognitionTask = nil
        recognitionRequest = SFSpeechAudioBufferRecognitionRequest()
        guard let recognitionRequest else { return }
        recognitionRequest.shouldReportPartialResults = true

        let session = AVAudioSession.sharedInstance()
        do {
            try session.setCategory(.record, mode: .measurement, options: .duckOthers)
            try session.setActive(true, options: .notifyOthersOnDeactivation)

            let inputNode = audioEngine.inputNode
            inputNode.removeTap(onBus: 0)
            let format = inputNode.outputFormat(forBus: 0)
            inputNode.installTap(onBus: 0, bufferSize: 1024, format: format) { [weak recognitionRequest] buffer, _ in
                recognitionRequest?.append(buffer)
            }

            audioEngine.prepare()
            try audioEngine.start()
            isRecording = true

            recognitionTask = recognizer?.recognitionTask(with: recognitionRequest) { [weak self] result, error in
                DispatchQueue.main.async {
                    guard let self else { return }
                    if let result {
                        self.onResult?(result.bestTranscription.formattedString)
                    }
                    if error != nil || result?.isFinal == true {
                        self.stopRecording(cancelTask: false)
                    }
                }
            }
        } catch {
            errorMessage = "语音输入启动失败：\(error.localizedDescription)"
            stopRecording(cancelTask: true)
        }
#endif
    }

    /// 结束 `stopRecording` 对应的交互或资源监听，并清理临时状态。
    private func stopRecording(cancelTask: Bool) {
        // 统一关闭音频引擎、移除 tap 并释放识别对象；主动停止时取消任务，错误或自然结束时可保留最终结果。
        if audioEngine.isRunning {
            audioEngine.stop()
            audioEngine.inputNode.removeTap(onBus: 0)
        }
        recognitionRequest?.endAudio()
        if cancelTask {
            recognitionTask?.cancel()
        }
        recognitionRequest = nil
        recognitionTask = nil
        isRecording = false
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }
}

/// 展示单条 AI 回答的详细分析文本，与聊天气泡的简短正文分离。
private struct XAgeAnalysisSheet: View {
    let message: ChatMessageItem
    @Environment(\.dismiss) private var dismiss

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
    var body: some View {
        ZStack {
            XAgeLiquidBackground().ignoresSafeArea()
            VStack(alignment: .leading, spacing: 14) {
                HStack {
                    Text("详细分析")
                        .font(.system(size: 24, weight: .bold))
                        .foregroundStyle(Color(hex: "123E67"))
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
                ScrollView {
                    MarkdownTextView(text: ChatViewModel.cleanAnalysis(message.analysis) ?? "当前回答没有额外分析。")
                        .padding(16)
                        .background(XAgeGlassCardBackground(cornerRadius: 22))
                }
                .scrollIndicators(.hidden)
            }
            .padding(24)
        }
    }
}

/// 展示回答关联的参考文献、适用人群和证据元信息；无引用时提供明确空状态。
private struct XAgeEvidenceSheet: View {
    let message: ChatMessageItem
    @Environment(\.dismiss) private var dismiss

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
    var body: some View {
        ZStack {
            XAgeLiquidBackground().ignoresSafeArea()
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    HStack {
                        Text("证据展示")
                            .font(.system(size: 24, weight: .bold))
                            .foregroundStyle(Color(hex: "123E67"))
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
                    ForEach(message.relevantCitationReferences) { reference in
                        VStack(alignment: .leading, spacing: 8) {
                            HStack {
                                Text("[\(reference.number)]")
                                    .font(.system(size: 13, weight: .bold))
                                    .foregroundStyle(Color.appPrimary)
                                Text(reference.citation.evidence_level)
                                    .font(.system(size: 12, weight: .bold))
                                    .foregroundStyle(Color.appAccent)
                                    .padding(.horizontal, 8)
                                    .padding(.vertical, 3)
                                    .background(Capsule().fill(Color.appAccent.opacity(0.12)))
                                Spacer()
                                Text(reference.citation.confidence)
                                    .font(.system(size: 12, weight: .medium))
                                    .foregroundStyle(Color(hex: "6C8194"))
                            }
                            Text(reference.citation.claim_text)
                                .font(.system(size: 14))
                                .foregroundStyle(Color(hex: "244E6D"))

                            Text("适用人群：\(populationText(for: reference.citation))")
                                .font(.system(size: 12, weight: .medium))
                                .foregroundStyle(Color(hex: "496A83"))
                                .lineSpacing(2)
                                .fixedSize(horizontal: false, vertical: true)
                                .padding(.horizontal, 10)
                                .padding(.vertical, 8)
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .background(XAgeCapsuleFill())

                            let studyMetadata = studyMetadata(for: reference.citation)
                            if !studyMetadata.isEmpty {
                                Text(studyMetadata.joined(separator: " · "))
                                    .font(.system(size: 12, weight: .medium))
                                    .foregroundStyle(Color(hex: "5D7890"))
                                    .lineSpacing(2)
                                    .fixedSize(horizontal: false, vertical: true)
                            }

                            if let shortReference = nonEmpty(reference.citation.short_ref) {
                                Text(shortReference)
                                    .font(.system(size: 12))
                                    .foregroundStyle(Color(hex: "6C8194"))
                                    .fixedSize(horizontal: false, vertical: true)
                            }
                        }
                        .padding(14)
                        .background(XAgeGlassCardBackground(cornerRadius: 20))
                    }
                    if message.relevantCitations.isEmpty {
                        Text("当前回答暂无文献引用。")
                            .font(.system(size: 14))
                            .foregroundStyle(Color(hex: "6C8194"))
                            .padding(16)
                            .background(XAgeGlassCardBackground(cornerRadius: 20))
                    }
                }
                .padding(24)
            }
        }
    }

    /// 将 `populationText` 的输入整理为页面可直接展示或使用的格式。
    private func populationText(for citation: Citation) -> String {
        nonEmpty(citation.population) ?? "文献未报告，需谨慎外推"
    }

    /// 将 `studyMetadata` 的输入整理为页面可直接展示或使用的格式。
    private func studyMetadata(for citation: Citation) -> [String] {
        var values: [String] = []
        if let studyDesign = citation.studyDesignDisplayText {
            values.append("研究类型：\(studyDesign)")
        }
        if let sampleSize = citation.sample_size, sampleSize > 0 {
            values.append("样本量：\(sampleSize)")
        }
        if let year = citation.year, year > 0 {
            values.append("年份：\(year)")
        }
        return values
    }

    /// 将 `nonEmpty` 的输入整理为页面可直接展示或使用的格式。
    private func nonEmpty(_ value: String?) -> String? {
        let normalized = value?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return normalized.isEmpty ? nil : normalized
    }
}

// MARK: - X年龄展示

/// X年龄页面单周的展示快照，将算法结果整理为日期范围、年龄区间、节奏和解释文案。
private struct XAgeSnapshot {
    let range: String
    let updateHint: String
    let isReady: Bool
    let age: String
    let ageRange: String
    let delta: String
    let pace: Double
    let confidence: Int
    let status: String
    let summary: String
    let explanation: String
    let nextAction: String
    let drivers: [XAgeScoreDriver]
}

/// X年龄原理页，集中解释当前结果、主要输入、置信度和下一步建议。
private struct XAgeInfoSheet: View {
    let snapshot: XAgeSnapshot
    @Environment(\.dismiss) private var dismiss

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
    var body: some View {
        ZStack {
            XAgeLiquidBackground()
                .ignoresSafeArea()

            VStack(alignment: .leading, spacing: 16) {
                HStack {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("X年龄原理")
                            .font(.system(size: 24, weight: .bold))
                            .foregroundStyle(Color(hex: "173F64"))
                        Text("\(snapshot.range) · 区间 \(snapshot.ageRange)")
                            .font(.system(size: 13, weight: .medium))
                            .foregroundStyle(Color(hex: "5D7890"))
                            .lineLimit(1)
                            .minimumScaleFactor(0.76)
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
                    .accessibilityIdentifier("xage.info.close")
                    .accessibilityLabel("关闭 X年龄原理")
                }

                ScrollView {
                    VStack(alignment: .leading, spacing: 14) {
                        HStack(spacing: 12) {
                            infoMetric(title: "当前", value: snapshot.age)
                            infoMetric(title: "差值", value: snapshot.delta)
                            infoMetric(title: "进度", value: snapshot.isReady ? String(format: "%.1fx", snapshot.pace) : "--")
                            infoMetric(title: "置信", value: "\(snapshot.confidence)%")
                        }

                        Text(snapshot.explanation)
                            .font(.system(size: 14))
                            .foregroundStyle(Color(hex: "496A83"))
                            .lineSpacing(4)
                            .fixedSize(horizontal: false, vertical: true)

                        Text(snapshot.summary)
                            .font(.system(size: 14, weight: .medium))
                            .foregroundStyle(Color(hex: "173F64"))
                            .lineSpacing(4)
                            .fixedSize(horizontal: false, vertical: true)
                            .padding(14)
                            .background(XAgeCapsuleFill())

                        VStack(alignment: .leading, spacing: 8) {
                            Text("主要输入")
                                .font(.system(size: 15, weight: .bold))
                                .foregroundStyle(Color(hex: "173F64"))
                            ForEach(snapshot.drivers.prefix(3)) { driver in
                                HStack {
                                    Text(driver.title)
                                        .font(.system(size: 12, weight: .bold))
                                        .foregroundStyle(Color(hex: "17324E"))
                                    Spacer()
                                    Text(driver.value)
                                        .font(.system(size: 12, weight: .bold))
                                        .foregroundStyle(Color(hex: "18AFA7"))
                                }
                                .padding(10)
                                .background(XAgeCapsuleFill())
                            }
                        }

                        Text(snapshot.nextAction)
                            .font(.system(size: 13, weight: .bold))
                            .foregroundStyle(Color(hex: "128F92"))
                            .lineSpacing(3)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    .padding(16)
                    .background(XAgeGlassCardBackground(cornerRadius: 26))
                    .padding(.bottom, 8)
                }
                .scrollIndicators(.hidden)
            }
            .padding(24)
        }
    }

    /// 构建 X年龄说明页中的标题—数值信息项。
    private func infoMetric(title: String, value: String) -> some View {
        VStack(spacing: 5) {
            Text(value)
                .font(.system(size: 16, weight: .bold))
                .foregroundStyle(Color(hex: "173F64"))
                .lineLimit(1)
                .minimumScaleFactor(0.72)
            Text(title)
                .font(.system(size: 11, weight: .medium))
                .foregroundStyle(Color(hex: "6F879B"))
        }
        .frame(maxWidth: .infinity)
        .frame(height: 58)
        .background(XAgeCapsuleFill())
    }
}

/// X年龄一级分页。
/// 当前算法结果生成一组周快照，左右按钮只切换展示索引，不会触发新的健康数据写入。
private struct XAgeHealthspanView: View {
    @Binding var selectedSection: XAgeTopSection
    let infoRequest: Int
    let scores: XAgeCompositeScores
    @State private var snapshotIndex = 0
    @State private var showInfo = false

    private var snapshots: [XAgeSnapshot] {
        // 周快照由同一份 X年龄评分派生，确保年龄、区间、速度和解释使用一致输入。
        weekSnapshots(from: scores.xAge)
    }

    private var snapshot: XAgeSnapshot {
        snapshots[min(snapshotIndex, snapshots.count - 1)]
    }

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
    var body: some View {
        ScrollView {
            VStack(spacing: 10) {
                Text("X年龄")
                    .font(.system(size: 24, weight: .bold))
                    .foregroundStyle(Color(hex: "123E67"))
                    .padding(.top, 12)
                Text(snapshot.updateHint)
                    .font(.system(size: 13))
                    .foregroundStyle(Color(hex: "5D7B95"))

                HStack(spacing: 10) {
                    Button {
                        selectSnapshot(snapshotIndex - 1)
                    } label: {
                        Image(systemName: "chevron.left")
                            .font(.system(size: 13, weight: .bold))
                            .frame(width: 26, height: 26)
                    }
                    .frame(width: 44, height: 44)
                    .contentShape(Rectangle())
                    .buttonStyle(.plain)
                    .disabled(snapshotIndex == snapshots.startIndex)
                    .opacity(snapshotIndex == snapshots.startIndex ? 0.35 : 1)
                    .accessibilityIdentifier("xage.week.previous")
                    .accessibilityLabel("上一周")

                    Text(snapshot.range)
                        .font(.system(size: 14, weight: .bold))

                    Button {
                        selectSnapshot(snapshotIndex + 1)
                    } label: {
                        Image(systemName: "chevron.right")
                            .font(.system(size: 13, weight: .bold))
                            .frame(width: 26, height: 26)
                    }
                    .frame(width: 44, height: 44)
                    .contentShape(Rectangle())
                    .buttonStyle(.plain)
                    .disabled(snapshotIndex == snapshots.index(before: snapshots.endIndex))
                    .opacity(snapshotIndex == snapshots.index(before: snapshots.endIndex) ? 0.35 : 1)
                    .accessibilityIdentifier("xage.week.next")
                    .accessibilityLabel("下一周")
                }
                .foregroundStyle(Color(hex: "347FB7"))
                .padding(.horizontal, 6)
                .frame(height: 44)
                .background(XAgeCapsuleFill())

                ZStack {
                    Circle()
                        .fill(
                            RadialGradient(colors: [Color(hex: "8EF7E6").opacity(0.24), Color(hex: "21B5FF").opacity(0.12), .clear], center: .center, startRadius: 20, endRadius: 170)
                        )
                        .frame(width: 272, height: 272)
                        .blur(radius: 7)
                    Image("x_age_particle_ring_blue_green")
                        .resizable()
                        .scaledToFit()
                        .frame(width: 254, height: 254)
                        .accessibilityIdentifier("xage.particle.ring")
                    Circle()
                        .fill(.white.opacity(0.54))
                        .background(.ultraThinMaterial, in: Circle())
                        .overlay(Circle().stroke(.white.opacity(0.78), lineWidth: 1))
                        .frame(width: 154, height: 154)
                    VStack(spacing: 4) {
                        Text(snapshot.age)
                            .font(.system(size: 44, weight: .bold))
                            .foregroundStyle(Color(hex: "12324F"))
                        HStack(alignment: .center, spacing: 5) {
                            Text("X年龄")
                                .font(.system(size: 15, weight: .bold))
                                .foregroundStyle(Color(hex: "45677F"))
                                .frame(height: 20)
                            Button {
                                showInfo = true
                            } label: {
                                Image(systemName: "info.circle.fill")
                                    .font(.system(size: 13, weight: .bold))
                                    .foregroundStyle(Color(hex: "18AFA7"))
                                    .frame(width: 20, height: 20)
                                    .background(
                                        Circle()
                                            .fill(.white.opacity(0.62))
                                            .overlay(Circle().stroke(.white.opacity(0.78), lineWidth: 1))
                                    )
                            }
                            .frame(width: 44, height: 44)
                            .contentShape(Rectangle())
                            .padding(.horizontal, -12)
                            .padding(.vertical, -12)
                            .buttonStyle(.plain)
                            .accessibilityIdentifier("xage.xage.info.inline")
                            .accessibilityLabel("X年龄原理")
                        }
                        Text(snapshot.delta)
                            .font(.system(size: 14, weight: .bold))
                            .foregroundStyle(Color(hex: "10A88E"))
                    }
                }
                .frame(height: 262)
                .padding(.top, 2)

                XAgePaceCard(pace: snapshot.pace, isReady: snapshot.isReady)

                VStack(alignment: .leading, spacing: 7) {
                    Text(snapshot.status)
                        .font(.system(size: 18, weight: .bold))
                        .foregroundStyle(Color(hex: "173F64"))
                    Text(snapshot.summary)
                        .font(.system(size: 12))
                        .foregroundStyle(Color(hex: "496A83"))
                        .lineSpacing(2)
                        .lineLimit(3)
                }
                .padding(14)
                .background(XAgeGlassCardBackground(cornerRadius: 26))
                .padding(.bottom, 20)
            }
            .padding(.horizontal, 24)
        }
        .scrollIndicators(.hidden)
        .onChange(of: infoRequest) { _, _ in
            // 顶栏信息按钮通过请求计数通知页面；只有当前确实位于 X年龄分页时才打开说明页。
            guard selectedSection == .xAge else { return }
            showInfo = true
        }
        .sheet(isPresented: $showInfo) {
            XAgeInfoSheet(snapshot: snapshot)
                .presentationDetents([.large])
                .presentationDragIndicator(.visible)
        }
    }

    /// 响应 `selectSnapshot` 对应的页面选择、展示或交互状态切换。
    private func selectSnapshot(_ index: Int) {
        // 索引被限制在已有周范围内，避免快速连点产生越界；切换仅更新本地展示状态。
        guard snapshots.indices.contains(index) else { return }
        withAnimation(.spring(response: 0.28, dampingFraction: 0.86)) {
            snapshotIndex = index
        }
    }

    /// 根据当前 X年龄评分生成前后周快照，用于周选择器和趋势展示。
    private func weekSnapshots(from score: XAgeAgeScore) -> [XAgeSnapshot] {
        [-1, 0].map { offset in
            let ageShift = Double(offset) * (score.pace - 1) * 0.18
            let shiftedAge = score.ageValue + ageShift
            let shiftedDelta = shiftedAge - score.chronologicalAge
            let isCurrentPrediction = offset == 0
            let canShowAge = score.isReady && !isCurrentPrediction
            return XAgeSnapshot(
                range: weekRange(offset: offset),
                updateHint: updateHint(offset: offset),
                isReady: canShowAge,
                age: canShowAge ? String(format: "%.1f", shiftedAge) : "--",
                ageRange: score.ageRange,
                delta: isCurrentPrediction ? "本周收集中" : (canShowAge ? deltaLabel(shiftedDelta) : "待评估"),
                pace: score.pace,
                confidence: score.confidence,
                status: isCurrentPrediction ? "本周预测中" : score.status,
                summary: isCurrentPrediction
                    ? "\(weekRange(offset: offset)) 的数据仍在收集中。小捷会先保留趋势输入，本周结束后再生成这一周的 X年龄。"
                    : score.summary,
                explanation: score.explanation,
                nextAction: score.nextAction,
                drivers: score.drivers
            )
        }
    }

    /// 计算 `deltaLabel` 对应的评分、状态或展示值。
    private func deltaLabel(_ value: Double) -> String {
        if value <= -0.15 { return "年轻 \(String(format: "%.1f", abs(value))) 岁" }
        if value >= 0.15 { return "偏大 \(String(format: "%.1f", value)) 岁" }
        return "接近实际年龄"
    }

    /// 更新 `updateHint` 对应的配置或状态，并处理必要的联动。
    private func updateHint(offset: Int) -> String {
        switch offset {
        case -1:
            return "已完成更新"
        case 0:
            return "预测中 · 本周结束后更新"
        default:
            return "预测中"
        }
    }

    /// 根据周偏移量计算对应自然周的起止日期文案。
    private func weekRange(offset: Int) -> String {
        var calendar = Calendar(identifier: .gregorian)
        calendar.locale = Locale(identifier: "zh_CN")
        calendar.firstWeekday = 2
        let today = Date()
        let weekStart = calendar.dateInterval(of: .weekOfYear, for: today)?.start ?? today
        let start = calendar.date(byAdding: .day, value: offset * 7, to: weekStart) ?? today
        let end = calendar.date(byAdding: .day, value: 6, to: start) ?? start
        return "\(Self.weekFormatter.string(from: start)) - \(Self.weekFormatter.string(from: end))"
    }

    private static let weekFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "zh_CN")
        formatter.dateFormat = "M月d日"
        return formatter
    }()
}

/// 将衰老速度映射到固定刻度区间；数据未达到评估门槛时显示占位状态而不是推断速度。
private struct XAgePaceCard: View {
    let pace: Double
    let isReady: Bool

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text("衰老进度")
                    .font(.system(size: 17, weight: .bold))
                    .foregroundStyle(Color(hex: "173F64"))
                Spacer()
                Text(isReady ? String(format: "%.1fx", pace) : "--")
                    .font(.system(size: 28, weight: .bold))
                    .foregroundStyle(Color(hex: "17324E"))
            }
            HStack {
                Text("慢")
                Spacer()
                Text("快")
            }
            .font(.system(size: 14, weight: .medium))
            .foregroundStyle(Color(hex: "6A8197"))

            ZStack(alignment: .leading) {
                HStack(spacing: 4) {
                    ForEach(0..<44, id: \.self) { i in
                        RoundedRectangle(cornerRadius: 1)
                            .fill(Color(hex: "577990").opacity(i % 10 == 0 ? 0.52 : 0.28))
                            .frame(width: 2, height: i % 10 == 0 ? 26 : 18)
                    }
                }
                RoundedRectangle(cornerRadius: 2)
                    .fill(LinearGradient(colors: [.white, Color(hex: "18C3B6")], startPoint: .top, endPoint: .bottom))
                    .frame(width: 4, height: 34)
                    .offset(x: markerOffset)
                    .opacity(isReady ? 1 : 0.28)
                    .shadow(color: Color(hex: "18B9D0").opacity(0.24), radius: 8, x: 0, y: 4)
            }
            .frame(height: 36)

            HStack {
                Text("-1.0x")
                Spacer()
                Text("1.0x")
                Spacer()
                Text("3.0x")
            }
            .font(.system(size: 12))
            .foregroundStyle(Color(hex: "6C8194"))
        }
        .padding(14)
        .background(XAgeGlassCardBackground(cornerRadius: 24))
    }

    private var markerOffset: CGFloat {
        guard isReady else { return 130 }
        let clamped = min(max(pace, -1), 3)
        return CGFloat((clamped + 1) / 4) * 260
    }
}

// MARK: - 设置、资料与账号管理

/// 新版 XAGE 的统一设置入口。
/// 资料分类和需要完整操作空间的功能使用全屏页面，帮助/关于等轻量内容使用 Sheet，危险账号操作要求二次确认。
private struct XAgeMoreMenu: View {
    @Binding var selectedCategory: XAgeDataPanelCategory
    @ObservedObject var appleHealthSync: AppleHealthSyncViewModel
    let snapshot: XAgeServerSyncSnapshot
    let onSyncAppleHealth: () async -> Void
    let onSelectCategory: (XAgeDataPanelCategory) -> Void
    let onClose: () -> Void
    @EnvironmentObject private var authManager: AuthManager
    @StateObject private var accountVM = XAgeAccountViewModel()
    @StateObject private var feedbackVM = SettingsViewModel()
    @State private var showFamilyMode = false
    @State private var showPersonalInfo = false
    @State private var showAccountSecurity = false
    @State private var showMedicationManagement = false
    @State private var showHelpFeedback = false
    @State private var showProblemFeedback = false
    @State private var showFeedbackSuccess = false
    @State private var showAbout = false
    @State private var showPrivacyPolicy = false
    @State private var showPermissionUsage = false
    @State private var showLogoutConfirm = false
    @State private var presentedCategory: XAgeDataPanelCategory?

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
    var body: some View {
        ZStack {
            XAgeLiquidBackground()
                .ignoresSafeArea()

            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    HStack {
                        Text("更多")
                            .font(.system(size: 28, weight: .bold))
                            .foregroundStyle(Color(hex: "123E67"))
                        Spacer()
                        Button {
                            onClose()
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
                        .accessibilityLabel("关闭")
                    }

                    VStack(alignment: .leading, spacing: 10) {
                        Text("资料")
                            .font(.system(size: 13, weight: .bold))
                            .foregroundStyle(Color(hex: "5D7890"))
                            .padding(.horizontal, 4)
                        ForEach(XAgeDataPanelCategory.allCases) { category in
                            XAgeAccountMenuRow(
                                icon: category.iconName,
                                title: category.rawValue,
                                subtitle: category.headline,
                                selected: selectedCategory == category
                            ) {
                                // 同时更新根页面选中的资料分类，并由当前设置页呈现对应的全屏工作台。
                                selectedCategory = category
                                onSelectCategory(category)
                                presentedCategory = category
                            }
                        }
                        XAgeAccountMenuRow(
                            icon: "pills.fill",
                            title: "用药管理",
                            subtitle: "用药记录、服药时间和本地提醒"
                        ) {
                            showMedicationManagement = true
                        }
                    }
                    .padding(14)
                    .background(XAgeGlassCardBackground(cornerRadius: 28))

                    VStack(alignment: .leading, spacing: 10) {
                        Text("账号管理")
                            .font(.system(size: 13, weight: .bold))
                            .foregroundStyle(Color(hex: "5D7890"))
                            .padding(.horizontal, 4)

                        XAgeAccountMenuRow(
                            icon: "person.text.rectangle.fill",
                            title: "个人信息与权限",
                            subtitle: "资料完整度、健康权限和隐私授权"
                        ) {
                            showPersonalInfo = true
                        }
                        XAgeAccountMenuRow(
                            icon: "person.badge.key.fill",
                            title: "账号与安全",
                            subtitle: "手机号、密码与账号注销"
                        ) {
                            showAccountSecurity = true
                        }
                        XAgeAccountMenuRow(
                            icon: "person.2.fill",
                            title: "关联用户",
                            subtitle: "家庭模式、邀请和授权"
                        ) {
                            showFamilyMode = true
                        }
                        XAgeAccountMenuRow(
                            icon: "rectangle.portrait.and.arrow.right",
                            title: "退出登录",
                            subtitle: "切换账号或重新登录"
                        ) {
                            showLogoutConfirm = true
                        }
//                        XAgeAccountMenuRow(
//                            icon: "person.crop.circle.badge.xmark",
//                            title: "注销账号",
//                            subtitle: "停用账号并清除登录态",
//                            destructive: true
//                        ) {
//                            showDeleteConfirm = true
//                        }
                    }
                    .padding(14)
                    .background(XAgeGlassCardBackground(cornerRadius: 28))

                    VStack(alignment: .leading, spacing: 10) {
                        Text("关于")
                            .font(.system(size: 13, weight: .bold))
                            .foregroundStyle(Color(hex: "5D7890"))
                            .padding(.horizontal, 4)

//                        XAgeAccountMenuRow(
//                            icon: "questionmark.bubble.fill",
//                            title: "帮助与反馈",
//                            subtitle: "提交问题、查看常见操作"
//                        ) {
//                            showHelpFeedback = true
//                        }
                        XAgeAccountMenuRow(
                            icon: "bubble.left.and.text.bubble.right.fill",
                            title: "问题反馈",
                            subtitle: "提交 APP 问题或改进建议"
                        ) {
                            showProblemFeedback = true
                        }
                        XAgeAccountMenuRow(
                            icon: "info.circle.fill",
                            title: "关于小捷",
                            subtitle: "版本说明"
                        ) {
                            showAbout = true
                        }
                        XAgeAccountMenuRow(
                            icon: "hand.raised.fill",
                            title: "隐私政策",
                            subtitle: "了解个人信息的收集、使用与保护"
                        ) {
                            showPrivacyPolicy = true
                        }
                        XAgeAccountMenuRow(
                            icon: "checkmark.shield.fill",
                            title: "权限申请与使用情况说明",
                            subtitle: "查看系统权限的用途与影响"
                        ) {
                            showPermissionUsage = true
                        }
                    }
                    .padding(14)
                    .background(XAgeGlassCardBackground(cornerRadius: 28))

                    Text("皖ICP备2026008853号-2")
                        .font(.system(size: 11, weight: .medium))
                        .foregroundStyle(Color(hex: "7D9AB1"))
                        .frame(maxWidth: .infinity)
                        .padding(.top, 2)
                }
                .padding(24)
            }
            .scrollIndicators(.hidden)
        }
        .fullScreenCover(isPresented: $showFamilyMode) {
            XAgeFamilyModeSheet()
        }
        .fullScreenCover(isPresented: $showPersonalInfo) {
            XAgePersonalInfoPermissionSheet(snapshot: snapshot, appleHealthSync: appleHealthSync)
        }
        .fullScreenCover(isPresented: $showAccountSecurity) {
            XAgeAccountSecurityView(
                accountVM: accountVM,
                onClose: { showAccountSecurity = false },
                onAccountDeleted: {
                    showAccountSecurity = false
                    onClose()
                }
            )
            .environmentObject(authManager)
        }
        .fullScreenCover(isPresented: $showMedicationManagement) {
            XAgeMedicationManagementView {
                showMedicationManagement = false
            }
        }
        .sheet(isPresented: $showHelpFeedback) {
            XAgeHelpFeedbackSheet()
                .presentationDetents([.medium, .large])
                .presentationDragIndicator(.visible)
        }
        .sheet(isPresented: $showProblemFeedback) {
            XAgeProblemFeedbackSheet(viewModel: feedbackVM) {
                showFeedbackSuccess = true
            }
            .presentationDetents([.large])
            .presentationDragIndicator(.visible)
        }
        .alert("反馈已提交", isPresented: $showFeedbackSuccess) {
            Button("好", role: .cancel) {}
        } message: {
            Text("感谢你的反馈，我们会认真查看并持续改进小捷。")
        }
        .sheet(isPresented: $showAbout) {
            XAgeAboutSheet()
                .presentationDetents([.medium, .large])
                .presentationDragIndicator(.visible)
        }
        .fullScreenCover(isPresented: $showPrivacyPolicy) {
            XAgePrivacyPolicyView(onClose: { showPrivacyPolicy = false })
        }
        .fullScreenCover(isPresented: $showPermissionUsage) {
            XAgePermissionUsageView(onClose: { showPermissionUsage = false })
        }
        .fullScreenCover(item: $presentedCategory) { category in
            XAgePanelDestinationView(
                category: category,
                appleHealthSync: appleHealthSync,
                snapshot: snapshot,
                onSyncAppleHealth: onSyncAppleHealth,
                onClose: {
                    presentedCategory = nil
                }
            )
        }
        .alert("确认退出", isPresented: $showLogoutConfirm) {
            Button("取消", role: .cancel) {}
            Button("退出", role: .destructive) {
                // 退出登录优先清除本地状态并返回登录页，服务端 token 撤销作为短超时后台请求执行。
                let accountToken = authManager.token
                onClose()
                authManager.logout(ifCurrentToken: accountToken)
                Task {
                    await accountVM.revokeLogoutToken(accountToken)
                }
            }
        } message: {
            Text("退出后会回到登录页，可使用其他账号登录。")
        }
        .alert("账号操作失败", isPresented: Binding(
            get: { accountVM.errorMessage != nil },
            set: { if !$0 { accountVM.errorMessage = nil } }
        )) {
            Button("知道了", role: .cancel) {}
        } message: {
            Text(accountVM.errorMessage ?? "")
        }
    }

}

/// 加载账号安全页所需的最小用户信息；失败时保留其他安全操作可用。
@MainActor
final class XAgeAccountSecurityViewModel: ObservableObject {
    @Published private(set) var phone = "暂未获取"
    @Published private(set) var isLoading = false
    @Published private(set) var loadErrorMessage: String?

    private let api: APIServiceProtocol

    /// 注入用户信息接口，便于页面复用生产服务并保持可测试性。
    init(api: APIServiceProtocol = APIService.shared) {
        self.api = api
    }

    /// 拉取当前账号并只保留脱敏后的手机号，避免原始号码进入页面状态。
    func loadAccount() async {
        isLoading = true
        loadErrorMessage = nil
        defer { isLoading = false }
        do {
            let user: UserInfo = try await api.get("/api/users/me")
            guard !Task.isCancelled else { return }
            phone = Utils.maskedPhone(user.phone)
        } catch {
            guard !Task.isCancelled else { return }
            phone = "暂未获取"
            loadErrorMessage = "暂时无法获取当前账号手机号，请稍后重试。"
        }
    }
}

/// 集中管理当前账号的手机号展示、密码修改与不可逆注销操作。
private struct XAgeAccountSecurityView: View {
    @EnvironmentObject private var authManager: AuthManager
    @ObservedObject var accountVM: XAgeAccountViewModel
    @StateObject private var viewModel = XAgeAccountSecurityViewModel()
    @State private var showChangePassword = false
    @State private var showDeleteConfirm = false
    let onClose: () -> Void
    let onAccountDeleted: () -> Void

    /// 组合账号安全页面，并让修改密码和注销弹层由当前子页面独立管理。
    var body: some View {
        pageContent
            .task { await viewModel.loadAccount() }
            .sheet(isPresented: $showChangePassword) {
                ChangePasswordSheet()
            }
            .sheet(isPresented: $showDeleteConfirm) {
                deleteConfirmation
            }
            .alert("账号操作失败", isPresented: accountErrorBinding) {
                Button("知道了", role: .cancel) {}
            } message: {
                Text(accountVM.errorMessage ?? "")
            }
    }

    /// 构建稳定的小型根表达式，避免把完整页面与多层弹窗写入同一个 SwiftUI 表达式。
    private var pageContent: some View {
        ZStack {
            XAgeLiquidBackground()
                .ignoresSafeArea()

            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    header
                    securityRows
                }
                .padding(24)
            }
            .scrollIndicators(.hidden)
            .accessibilityIdentifier("xage.account.security.page")
        }
    }

    /// 提供只关闭账号安全子页面的返回入口。
    private var header: some View {
        HStack {
            Button(action: onClose) {
                Image(systemName: "chevron.left")
                    .font(.system(size: 17, weight: .bold))
                    .foregroundStyle(Color(hex: "347FB7"))
                    .frame(width: 42, height: 34)
                    .background(XAgeCapsuleFill())
            }
            .frame(width: 44, height: 44)
            .contentShape(Rectangle())
            .buttonStyle(.plain)
            .accessibilityLabel("返回")

            Spacer()

            Text("账号与安全")
                .font(.system(size: 19, weight: .bold))
                .foregroundStyle(Color(hex: "123E67"))

            Spacer()

            Color.clear.frame(width: 44, height: 44)
        }
    }

    /// 按需求固定为手机号、修改密码、注销账号三个展示条。
    private var securityRows: some View {
        VStack(spacing: 12) {
            phoneRow
            passwordRow
            deleteRow
        }
        .padding(14)
        .background(XAgeGlassCardBackground(cornerRadius: 28))
    }

    /// 手机号条仅展示服务端返回号码的脱敏结果，不提供编辑行为。
    private var phoneRow: some View {
        HStack(spacing: 12) {
            securityIcon("iphone", destructive: false)

            VStack(alignment: .leading, spacing: 4) {
                Text("当前账号手机号")
                    .font(.system(size: 16, weight: .bold))
                    .foregroundStyle(Color(hex: "173F64"))
                if let loadErrorMessage = viewModel.loadErrorMessage {
                    Text(loadErrorMessage)
                        .font(.system(size: 11, weight: .medium))
                        .foregroundStyle(Color(hex: "B06A3A"))
                }
            }

            Spacer(minLength: 8)

            HStack(spacing: 8) {
                Text(viewModel.phone)
                    .font(.system(size: 15, weight: .semibold, design: .monospaced))
                    .foregroundStyle(Color(hex: "496A83"))
                    .accessibilityIdentifier("xage.account.security.phone")
                if viewModel.isLoading {
                    ProgressView()
                        .tint(Color(hex: "237FC4"))
                }
            }
        }
        .padding(.horizontal, 14)
        .frame(minHeight: 68)
        .background(XAgeGlassCardBackground(cornerRadius: 22))
        .accessibilityElement(children: .contain)
    }

    /// 修改密码复用既有表单和接口校验，不在账号页重复维护密码字段。
    private var passwordRow: some View {
        Button {
            showChangePassword = true
        } label: {
            actionRowLabel(
                icon: "lock.rotation",
                title: "修改密码",
                subtitle: "验证旧密码后设置新密码",
                destructive: false
            )
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("xage.account.security.password")
    }

    /// 注销入口使用危险色，并在下一层要求输入指定文字后才能真正提交。
    private var deleteRow: some View {
        Button {
            showDeleteConfirm = true
        } label: {
            actionRowLabel(
                icon: "person.crop.circle.badge.xmark",
                title: "注销账号",
                subtitle: "永久删除账号及相关数据",
                destructive: true
            )
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("xage.account.security.delete")
    }

    /// 复用原有注销确认页，并仅在服务端确认删除后清理对应登录态。
    private var deleteConfirmation: some View {
        XAgeDeleteAccountSheet(
            isWorking: accountVM.isWorking,
            onCancel: { showDeleteConfirm = false },
            onConfirm: {
                Task {
                    let accountToken = authManager.token
                    if await accountVM.deleteAccountOnServer() {
                        showDeleteConfirm = false
                        onAccountDeleted()
                        authManager.logout(ifCurrentToken: accountToken)
                    }
                }
            }
        )
        .presentationDetents([.medium, .large])
        .interactiveDismissDisabled(accountVM.isWorking)
    }

    /// 将账号请求错误映射为 SwiftUI Alert 的布尔绑定。
    private var accountErrorBinding: Binding<Bool> {
        Binding(
            get: { accountVM.errorMessage != nil },
            set: { if !$0 { accountVM.errorMessage = nil } }
        )
    }

    /// 生成账号安全操作条的统一布局，减少页面主表达式复杂度。
    private func actionRowLabel(
        icon: String,
        title: String,
        subtitle: String,
        destructive: Bool
    ) -> some View {
        HStack(spacing: 12) {
            securityIcon(icon, destructive: destructive)

            VStack(alignment: .leading, spacing: 3) {
                Text(title)
                    .font(.system(size: 16, weight: .bold))
                    .foregroundStyle(destructive ? Color(hex: "B43D4B") : Color(hex: "173F64"))
                Text(subtitle)
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(Color(hex: "6C8194"))
            }

            Spacer()

            Image(systemName: "chevron.right")
                .font(.system(size: 13, weight: .bold))
                .foregroundStyle(Color(hex: "7D9AB1"))
        }
        .padding(.horizontal, 14)
        .frame(height: 68)
        .background(XAgeGlassCardBackground(cornerRadius: 22))
    }

    /// 生成展示条左侧图标，并根据危险操作切换颜色。
    private func securityIcon(_ name: String, destructive: Bool) -> some View {
        Image(systemName: name)
            .font(.system(size: 16, weight: .bold))
            .foregroundStyle(destructive ? Color(hex: "D85A66") : Color(hex: "237FC4"))
            .frame(width: 38, height: 38)
            .background(
                Circle()
                    .fill(.white.opacity(0.6))
                    .overlay(Circle().stroke(.white.opacity(0.78), lineWidth: 1))
            )
    }
}

/// 本地政策页面的章节数据，分别承载正文段落和列表项。
private struct XAgeLegalSection: Identifiable {
    let id: String
    let title: String
    let paragraphs: [String]
    let bullets: [String]
}

/// 权限说明条目明确区分申请时机、用途和拒绝后的影响。
private struct XAgePermissionDescription: Identifiable {
    let id: String
    let icon: String
    let title: String
    let applicationMoment: String
    let purpose: String
    let denialImpact: String
}

/// 隐私政策和权限说明共用的顶部返回栏，返回仅关闭当前全屏子页面。
private struct XAgeLocalDocumentHeader: View {
    let title: String
    let onClose: () -> Void

    /// 构建带 44pt 点击区域的返回按钮和居中标题。
    var body: some View {
        HStack {
            Button(action: onClose) {
                Image(systemName: "chevron.left")
                    .font(.system(size: 17, weight: .bold))
                    .foregroundStyle(Color(hex: "347FB7"))
                    .frame(width: 42, height: 34)
                    .background(XAgeCapsuleFill())
            }
            .frame(width: 44, height: 44)
            .contentShape(Rectangle())
            .buttonStyle(.plain)
            .accessibilityLabel("返回")

            Spacer()

            Text(title)
                .font(.system(size: 19, weight: .bold))
                .foregroundStyle(Color(hex: "123E67"))
                .multilineTextAlignment(.center)

            Spacer()

            Color.clear.frame(width: 44, height: 44)
        }
    }
}

/// 将项目现有隐私政策原文转换为不依赖网络的本地 SwiftUI 页面。
private struct XAgePrivacyPolicyView: View {
    let onClose: () -> Void

    private static let sections = [
        XAgeLegalSection(
            id: "collection",
            title: "1. 信息收集",
            paragraphs: ["我们可能收集以下信息："],
            bullets: [
                "账户信息：手机号码，用于注册和登录。",
                "健康数据：您主动上传的体检报告、病例记录、血糖监测数据等。",
                "设备信息：设备型号、操作系统版本，用于优化应用体验。"
            ]
        ),
        XAgeLegalSection(
            id: "use",
            title: "2. 信息使用",
            paragraphs: ["我们使用您的信息用于："],
            bullets: [
                "为您提供健康数据管理和分析服务。",
                "通过 AI 技术帮助整理和解读您的健康报告。",
                "改善和优化我们的产品和服务。"
            ]
        ),
        XAgeLegalSection(
            id: "storage",
            title: "3. 信息存储与安全",
            paragraphs: [],
            bullets: [
                "您的数据存储在安全的云服务器上，采用加密传输（HTTPS/TLS）。",
                "我们采取合理的技术和管理措施保护您的个人信息安全。",
                "仅经授权的人员可以访问您的数据。"
            ]
        ),
        XAgeLegalSection(
            id: "sharing",
            title: "4. 信息共享",
            paragraphs: ["我们不会向任何第三方出售、出租或交换您的个人信息，除非："],
            bullets: [
                "获得您的明确同意。",
                "根据法律法规要求或政府部门的强制要求。"
            ]
        ),
        XAgeLegalSection(
            id: "ai",
            title: "5. AI 数据处理",
            paragraphs: ["我们使用人工智能技术处理您上传的健康文档，提取结构化数据并生成分析报告。AI 处理仅用于为您提供服务，不会将您的数据用于模型训练。"],
            bullets: []
        ),
        XAgeLegalSection(
            id: "rights",
            title: "6. 您的权利",
            paragraphs: ["您有权："],
            bullets: [
                "访问和查看您的个人数据。",
                "删除您的账户及相关数据。",
                "撤回数据处理的同意。"
            ]
        ),
        XAgeLegalSection(
            id: "contact",
            title: "7. 联系我们",
            paragraphs: [
                "如您对本隐私政策有任何疑问，请通过以下方式联系我们：",
                "邮箱：support@xjie-health.com"
            ],
            bullets: []
        ),
        XAgeLegalSection(
            id: "changes",
            title: "8. 政策变更",
            paragraphs: ["我们保留更新本隐私政策的权利。变更将在本页面发布，建议您定期查看。"],
            bullets: []
        )
    ]

    /// 组合本地政策内容，所有文字随 App 安装包提供并支持离线滚动查看。
    var body: some View {
        ZStack {
            XAgeLiquidBackground()
                .ignoresSafeArea()

            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    XAgeLocalDocumentHeader(title: "隐私政策", onClose: onClose)
                    introductionCard
                    ForEach(Self.sections) { section in
                        sectionCard(section)
                    }
                }
                .padding(24)
            }
            .scrollIndicators(.hidden)
            .accessibilityIdentifier("xage.privacy.policy.page")
        }
    }

    /// 展示政策更新时间和与现有 HTML 一致的开篇说明。
    private var introductionCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("最后更新日期：2026年4月9日")
                .font(.system(size: 12, weight: .semibold))
                .foregroundStyle(Color(hex: "6C8194"))
            Text("小捷健康（以下简称\"我们\"）非常重视您的隐私。本隐私政策说明我们如何收集、使用、存储和保护您的个人信息。")
                .font(.system(size: 15))
                .foregroundStyle(Color(hex: "496A83"))
                .lineSpacing(4)
        }
        .padding(18)
        .background(XAgeGlassCardBackground(cornerRadius: 24))
    }

    /// 分别渲染章节正文和列表项，保持政策结构清晰并利于 VoiceOver 阅读。
    private func sectionCard(_ section: XAgeLegalSection) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(section.title)
                .font(.system(size: 17, weight: .bold))
                .foregroundStyle(Color(hex: "173F64"))

            ForEach(section.paragraphs, id: \.self) { paragraph in
                Text(paragraph)
                    .font(.system(size: 14))
                    .foregroundStyle(Color(hex: "496A83"))
                    .lineSpacing(4)
            }

            ForEach(section.bullets, id: \.self) { bullet in
                HStack(alignment: .top, spacing: 8) {
                    Text("•")
                        .foregroundStyle(Color(hex: "238AD6"))
                    Text(bullet)
                        .font(.system(size: 14))
                        .foregroundStyle(Color(hex: "496A83"))
                        .lineSpacing(4)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(18)
        .background(XAgeGlassCardBackground(cornerRadius: 24))
    }
}

/// 说明当前版本声明的系统权限、申请场景以及用户拒绝后的实际影响。
private struct XAgePermissionUsageView: View {
    let onClose: () -> Void

    private static let permissions = [
        XAgePermissionDescription(
            id: "camera",
            icon: "camera.fill",
            title: "相机",
            applicationMoment: "拍摄膳食或体检报告时",
            purpose: "需要使用相机拍摄膳食/体检报告等照片，用于记录与上传分析。",
            denialImpact: "拒绝后仍可从相册或文件中选择已有资料。"
        ),
        XAgePermissionDescription(
            id: "photo-read",
            icon: "photo.on.rectangle",
            title: "相册读取",
            applicationMoment: "从相册选择资料时",
            purpose: "需要访问相册以选择膳食/体检报告等照片用于上传。",
            denialImpact: "拒绝后无法从相册选择，但仍可使用相机或文件导入。"
        ),
        XAgePermissionDescription(
            id: "photo-write",
            icon: "square.and.arrow.down.fill",
            title: "相册写入",
            applicationMoment: "选择保存拍摄照片时",
            purpose: "需要将拍摄的膳食照片保存到相册（可选）。",
            denialImpact: "该能力为可选；拒绝不会影响上传本次已拍摄内容。"
        ),
        XAgePermissionDescription(
            id: "microphone",
            icon: "mic.fill",
            title: "麦克风",
            applicationMoment: "使用助手小捷语音输入时",
            purpose: "需要使用麦克风进行助手小捷语音输入。",
            denialImpact: "拒绝后可以继续使用键盘输入。"
        ),
        XAgePermissionDescription(
            id: "speech",
            icon: "waveform",
            title: "语音识别",
            applicationMoment: "将语音输入转换成文字时",
            purpose: "需要使用语音识别将您的语音转换成文字消息。",
            denialImpact: "拒绝后可以继续使用键盘输入。"
        ),
        XAgePermissionDescription(
            id: "health-read",
            icon: "heart.text.square.fill",
            title: "Apple 健康读取",
            applicationMoment: "主动授权或开启 Apple 健康同步时",
            purpose: "在你选择授权后，小捷会只读 Apple 健康中的活动、身体测量、心脏与呼吸、睡眠、营养、血糖与胰岛素、声音环境，以及经期、排卵和性活动等生理记录，并在前台或后台同步到当前登录账号的健康趋势；未授权项目不会读取。",
            denialImpact: "拒绝或仅授权部分项目，不会影响手动记录和其他未依赖该数据的功能。"
        ),
        XAgePermissionDescription(
            id: "health-write",
            icon: "heart.badge.plus",
            title: "Apple 健康写入",
            applicationMoment: "当前版本不会申请",
            purpose: "小捷当前不会向 Apple 健康写入数据；未来如提供写入功能，会在操作前另行说明并再次请求你的授权。",
            denialImpact: "当前版本没有影响。"
        )
    ]

    /// 组合权限总说明与七个权限条目，内容完全本地可用。
    var body: some View {
        ZStack {
            XAgeLiquidBackground()
                .ignoresSafeArea()

            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    XAgeLocalDocumentHeader(title: "权限申请与使用情况说明", onClose: onClose)
                    overviewCard
                    ForEach(Self.permissions) { permission in
                        permissionCard(permission)
                    }
                }
                .padding(24)
            }
            .scrollIndicators(.hidden)
            .accessibilityIdentifier("xage.permissions.usage.page")
        }
    }

    /// 告知用户授权自愿、按场景触发，并可在系统设置中调整。
    private var overviewCard: some View {
        Text("以下权限仅在你使用对应功能时申请。是否授权由你决定，你可以随时前往 iOS“设置”中调整；未授权的项目不会被读取。")
            .font(.system(size: 14))
            .foregroundStyle(Color(hex: "496A83"))
            .lineSpacing(4)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(18)
            .background(XAgeGlassCardBackground(cornerRadius: 24))
    }

    /// 为单项权限展示名称、申请时机、用途和拒绝影响。
    private func permissionCard(_ permission: XAgePermissionDescription) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Label(permission.title, systemImage: permission.icon)
                .font(.system(size: 17, weight: .bold))
                .foregroundStyle(Color(hex: "173F64"))

            permissionDetail(label: "申请时机", value: permission.applicationMoment)
            permissionDetail(label: "使用目的", value: permission.purpose)
            permissionDetail(label: "拒绝影响", value: permission.denialImpact)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(18)
        .background(XAgeGlassCardBackground(cornerRadius: 24))
    }

    /// 使用独立文本层级展示权限字段，避免长说明挤压标题。
    private func permissionDetail(label: String, value: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(label)
                .font(.system(size: 12, weight: .bold))
                .foregroundStyle(Color(hex: "237FC4"))
            Text(value)
                .font(.system(size: 14))
                .foregroundStyle(Color(hex: "496A83"))
                .lineSpacing(4)
        }
    }
}

@MainActor
/// 封装退出和注销等账号请求，并保护进行中状态。
/// 退出允许网络失败时本地完成；注销则必须服务端成功，避免客户端误以为账号已经停用。
final class XAgeAccountViewModel: ObservableObject {
    @Published var isWorking = false
    @Published var errorMessage: String?

    private let api: APIServiceProtocol

    /// 注入账号相关 API 实现，供退出登录和注销账号流程复用。
    init(api: APIServiceProtocol = APIService.shared) {
        self.api = api
    }

    /// 执行 `logout` 对应的删除、撤销或退出操作，并处理关联状态。
    func logout(authManager: AuthManager) async {
        let accountToken = authManager.token
        isWorking = true
        defer { isWorking = false }
        do {
            try await api.postVoid("/api/auth/logout")
        } catch {
            // 退出登录必须允许本地完成，避免网络错误把用户锁在当前账号。
        }
        authManager.logout(ifCurrentToken: accountToken)
    }

    /// 执行 `revokeLogoutToken` 对应的删除、撤销或退出操作，并处理关联状态。
    func revokeLogoutToken(_ token: String) async {
        // 使用捕获的旧 token 直接发短超时请求，因为本地 logout 后 AuthManager 已不再保存该 token。
        guard !token.isEmpty,
              let url = URL(string: AppEnvironment.apiBaseURL + "/api/auth/logout")
        else { return }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.timeoutInterval = 4
        _ = try? await URLSession.shared.data(for: request)
    }

    /// 执行 `deleteAccount` 对应的删除、撤销或退出操作，并处理关联状态。
    func deleteAccount(authManager: AuthManager) async {
        let accountToken = authManager.token
        if await deleteAccountOnServer() {
            authManager.logout(ifCurrentToken: accountToken)
        }
    }

    /// 执行 `deleteAccountOnServer` 对应的删除、撤销或退出操作，并处理关联状态。
    func deleteAccountOnServer() async -> Bool {
        isWorking = true
        defer { isWorking = false }
        do {
            try await api.deleteVoid("/api/users/me")
            return true
        } catch {
            errorMessage = error.localizedDescription
            return false
        }
    }
}

private struct XAgeMoreMenuRow: View {
    let identifier: String
    let icon: String
    let title: String
    let subtitle: String
    let selected: Bool
    let action: () -> Void

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
    var body: some View {
        Button(action: action) {
            HStack(spacing: 12) {
                Image(systemName: icon)
                    .font(.system(size: 17, weight: .bold))
                    .foregroundStyle(.white)
                    .frame(width: 38, height: 38)
                    .background(
                        Circle()
                            .fill(
                                LinearGradient(
                                    colors: selected ? [Color(hex: "238AD6"), Color(hex: "20CDB1")] : [Color(hex: "7ABBE7"), Color(hex: "92DDCE")],
                                    startPoint: .topLeading,
                                    endPoint: .bottomTrailing
                                )
                            )
                    )

                VStack(alignment: .leading, spacing: 3) {
                    Text(title)
                        .font(.system(size: 18, weight: .bold))
                        .foregroundStyle(Color(hex: "173F64"))
                    Text(subtitle)
                        .font(.system(size: 12, weight: .medium))
                        .foregroundStyle(Color(hex: "6C8194"))
                        .lineLimit(1)
                }

                Spacer()

                Image(systemName: "chevron.right")
                    .font(.system(size: 13, weight: .bold))
                    .foregroundStyle(Color(hex: "7D9AB1"))
            }
            .padding(.horizontal, 14)
            .frame(height: 64)
            .background(XAgeGlassCardBackground(cornerRadius: 22))
        }
        .buttonStyle(.plain)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(title)、\(subtitle)")
        .accessibilityValue(selected ? "已选中" : "")
        .xAgeAccessibilitySelected(selected)
        .accessibilityIdentifier("xage.more.category.\(identifier)")
    }
}

private struct XAgeAccountMenuRow: View {
    let icon: String
    let title: String
    let subtitle: String
    var destructive = false
    var selected = false
    let action: () -> Void

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
    var body: some View {
        Button(action: action) {
            HStack(spacing: 12) {
                Image(systemName: icon)
                    .font(.system(size: 16, weight: .bold))
                    .foregroundStyle(destructive ? Color(hex: "D85A66") : Color(hex: "237FC4"))
                    .frame(width: 38, height: 38)
                    .background(Circle().fill(.white.opacity(0.6)).overlay(Circle().stroke(.white.opacity(0.78), lineWidth: 1)))

                VStack(alignment: .leading, spacing: 3) {
                    Text(title)
                        .font(.system(size: 16, weight: .bold))
                        .foregroundStyle(destructive ? Color(hex: "B43D4B") : Color(hex: "173F64"))
                    Text(subtitle)
                        .font(.system(size: 12, weight: .medium))
                        .foregroundStyle(Color(hex: "6C8194"))
                        .lineLimit(1)
                }

                Spacer()
                Image(systemName: "chevron.right")
                    .font(.system(size: 13, weight: .bold))
                    .foregroundStyle(Color(hex: "7D9AB1"))
            }
            .padding(.horizontal, 14)
            .frame(height: 62)
            .background(XAgeGlassCardBackground(cornerRadius: 22))
            .overlay(
                RoundedRectangle(cornerRadius: 22, style: .continuous)
                    .stroke(Color(hex: "238AD6").opacity(selected ? 0.58 : 0), lineWidth: selected ? 1.5 : 0)
            )
        }
        .buttonStyle(.plain)
        .accessibilityValue(selected ? "当前资料分类" : "")
        .xAgeAccessibilitySelected(selected)
        .accessibilityIdentifier("xage.account.\(title)")
    }
}

/// 注销确认页要求输入指定文字后才启用最终按钮，降低误触发不可逆账号操作的风险。
private struct XAgeDeleteAccountSheet: View {
    let isWorking: Bool
    let onCancel: () -> Void
    let onConfirm: () -> Void
    @State private var confirmText = ""
    @FocusState private var confirmFocused: Bool

    private var canConfirm: Bool {
        confirmText.trimmingCharacters(in: .whitespacesAndNewlines) == "注销"
    }

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
    var body: some View {
        ZStack {
            XAgeLiquidBackground()
                .ignoresSafeArea()

            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                HStack(spacing: 12) {
                    Image(systemName: "person.crop.circle.badge.xmark")
                        .font(.system(size: 24, weight: .bold))
                        .foregroundStyle(Color(hex: "D85A66"))
                        .frame(width: 52, height: 52)
                        .background(XAgeCapsuleFill())
                    VStack(alignment: .leading, spacing: 4) {
                        Text("注销账号")
                            .font(.system(size: 24, weight: .bold))
                            .foregroundStyle(Color(hex: "123E67"))
                        Text("账号停用后会立即退出登录")
                            .font(.system(size: 13, weight: .medium))
                            .foregroundStyle(Color(hex: "5D7890"))
                    }
                }

                Text("系统会停用当前账号并清除本机登录态。为避免误触，请输入“注销”后再确认。")
                    .font(.system(size: 13))
                    .foregroundStyle(Color(hex: "496A83"))
                    .lineSpacing(3)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(14)
                    .background(XAgeCapsuleFill())

                TextField("输入：注销", text: $confirmText)
                    .font(.system(size: 16, weight: .bold))
                    .textInputAutocapitalization(.never)
                    .disableAutocorrection(true)
                    .padding(.horizontal, 14)
                    .frame(height: 48)
                    .background(XAgeGlassCardBackground(cornerRadius: 22))
                    .focused($confirmFocused)
                    .submitLabel(.done)
                    .onSubmit {
                        confirmFocused = false
                        XAgeKeyboard.dismiss()
                    }
                    .accessibilityIdentifier("xage.account.delete.input")

                HStack(spacing: 10) {
                    Button {
                        confirmFocused = false
                        XAgeKeyboard.dismiss()
                        onCancel()
                    } label: {
                        Text("取消")
                            .font(.system(size: 15, weight: .bold))
                            .foregroundStyle(Color(hex: "365F80"))
                            .frame(maxWidth: .infinity)
                            .frame(height: 46)
                            .background(XAgeCapsuleFill())
                    }
                    .buttonStyle(.plain)
                    .disabled(isWorking)

                    Button {
                        confirmFocused = false
                        XAgeKeyboard.dismiss()
                        onConfirm()
                    } label: {
                        HStack(spacing: 8) {
                            if isWorking {
                                ProgressView()
                                    .tint(.white)
                            }
                            Text(isWorking ? "处理中" : "确认注销")
                                .font(.system(size: 15, weight: .bold))
                        }
                        .foregroundStyle(.white)
                        .frame(maxWidth: .infinity)
                        .frame(height: 46)
                        .background(
                            Capsule()
                                .fill(canConfirm ? AnyShapeStyle(Color(hex: "D85A66")) : AnyShapeStyle(Color(hex: "AEBFCD")))
                        )
                    }
                    .buttonStyle(.plain)
                    .disabled(!canConfirm || isWorking)
                    .accessibilityIdentifier("xage.account.delete.confirm")
                }
                }
                .padding(24)
            }
            .scrollIndicators(.hidden)
            .scrollDismissesKeyboard(.interactively)
        }
        .toolbar {
            ToolbarItemGroup(placement: .keyboard) {
                Spacer()
                Button("完成") {
                    confirmFocused = false
                    XAgeKeyboard.dismiss()
                }
            }
        }
    }
}

/// 个人信息与权限概览，汇总资料完整度、Apple Health 状态和隐私授权说明，不在此页直接修改健康数据。
private struct XAgePersonalInfoPermissionSheet: View {
    let snapshot: XAgeServerSyncSnapshot
    @ObservedObject var appleHealthSync: AppleHealthSyncViewModel
    @Environment(\.dismiss) private var dismiss

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
    var body: some View {
        XAgeSettingsInfoSheetScaffold(
            title: "个人信息与权限",
            subtitle: "查看资料完整度和健康数据授权",
            icon: "person.text.rectangle.fill",
            onClose: { dismiss() }
        ) {
            XAgeMetricDetailRow(title: "资料完整度", value: "\(snapshot.profileCompletion)%")
            XAgeMetricDetailRow(title: "身高", value: snapshot.profileHeightCm.map { "\(Int($0.rounded())) cm" } ?? "待补充")
            XAgeMetricDetailRow(title: "体重", value: snapshot.profileWeightKg.map { String(format: "%.1f kg", $0) } ?? "待补充")
            XAgeMetricDetailRow(title: "Apple 健康", value: appleHealthSync.lastSyncedAt == nil ? "未同步" : appleHealthSync.statusTitle)
            XAgeMetricDetailRow(title: "健康资料", value: "\(snapshot.recordCount + snapshot.examCount) 份")
            Text("家庭共享、Apple 健康和报告资料都需要单独授权。小捷只在你允许后读取数据，并按来源和测量时间写入用户端趋势。")
                .font(.system(size: 13))
                .foregroundStyle(Color(hex: "496A83"))
                .lineSpacing(3)
                .fixedSize(horizontal: false, vertical: true)
                .padding(14)
                .background(XAgeCapsuleFill())
        }
    }
}

private struct XAgeHelpFeedbackSheet: View {
    @Environment(\.dismiss) private var dismiss

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
    var body: some View {
        XAgeSettingsInfoSheetScaffold(
            title: "帮助与反馈",
            subtitle: "常见操作和问题反馈入口",
            icon: "questionmark.bubble.fill",
            onClose: { dismiss() }
        ) {
            XAgeMetricDetailRow(title: "上传报告", value: "资料 > 报告")
            XAgeMetricDetailRow(title: "补录指标", value: "数据卡片 > 手动记录")
            XAgeMetricDetailRow(title: "同步日常", value: "资料 > 日常")
            Text("遇到识别失败、数据不同步或评分异常时，可以把问题截图和发生时间发给小捷团队。后续版本会把反馈入口接入线上工单。")
                .font(.system(size: 13))
                .foregroundStyle(Color(hex: "496A83"))
                .lineSpacing(3)
                .fixedSize(horizontal: false, vertical: true)
                .padding(14)
                .background(XAgeCapsuleFill())
        }
    }
}

/// 收集用户对 APP 的问题或改进建议，并复用设置模块的反馈接口提交到服务端。
private struct XAgeProblemFeedbackSheet: View {
    @Environment(\.dismiss) private var dismiss
    @ObservedObject var viewModel: SettingsViewModel
    let onSubmitted: () -> Void

    @State private var content = ""
    @State private var submitting = false

    private var trimmedContent: String {
        content.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private var canSubmit: Bool {
        (2...2000).contains(trimmedContent.count) && !submitting
    }

    var body: some View {
        XAgeSettingsInfoSheetScaffold(
            title: "问题反馈",
            subtitle: "告诉我们遇到的问题或改进建议",
            icon: "bubble.left.and.text.bubble.right.fill",
            onClose: {
                guard !submitting else { return }
                dismiss()
            }
        ) {
            feedbackEditor

            XAgeMetricDetailRow(title: "联系我们", value: "jianjieaitech@163.com")
                .accessibilityIdentifier("xage.feedback.email")

            submitButton
        }
        .interactiveDismissDisabled(submitting)
        .accessibilityIdentifier("xage.feedback.page")
        .alert("提交失败", isPresented: Binding(
            get: { viewModel.errorMessage != nil },
            set: { if !$0 { viewModel.errorMessage = nil } }
        )) {
            Button("知道了", role: .cancel) {}
        } message: {
            Text(viewModel.errorMessage ?? "")
        }
    }

    private var feedbackEditor: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("反馈内容")
                .font(.system(size: 13, weight: .bold))
                .foregroundStyle(Color(hex: "5D7890"))
            TextEditor(text: $content)
                .frame(minHeight: 180)
                .padding(10)
                .scrollContentBackground(.hidden)
                .background(XAgeRoundedFieldBackground())
                .accessibilityIdentifier("xage.feedback.content")
            Text("\(trimmedContent.count)/2000")
                .font(.system(size: 12, weight: .semibold))
                .foregroundStyle(trimmedContent.count > 2000 ? .red : Color(hex: "7D9AB1"))
                .frame(maxWidth: .infinity, alignment: .trailing)
        }
    }

    private var submitButton: some View {
        Button {
            submit()
        } label: {
            XAgeGradientActionLabel(
                title: submitting ? "提交中…" : "提交反馈",
                icon: "paperplane.fill"
            )
        }
        .buttonStyle(.plain)
        .disabled(!canSubmit)
        .opacity(canSubmit ? 1 : 0.5)
        .accessibilityIdentifier("xage.feedback.submit")
    }

    private func submit() {
        guard canSubmit else { return }
        submitting = true
        viewModel.errorMessage = nil
        Task {
            let ok = await viewModel.submitFeedback(
                category: "general",
                content: trimmedContent,
                contact: nil
            )
            submitting = false
            if ok {
                dismiss()
                onSubmitted()
            }
        }
    }
}

private struct XAgeAboutSheet: View {
    @Environment(\.dismiss) private var dismiss

    private var versionText: String {
        let info = Bundle.main.infoDictionary
        let version = info?["CFBundleShortVersionString"] as? String ?? "1.0"
        let build = info?["CFBundleVersion"] as? String ?? "-"
        return "\(version)(\(build))"
    }

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
    var body: some View {
        XAgeSettingsInfoSheetScaffold(
            title: "关于小捷",
            subtitle: "版本说明",
            icon: "info.circle.fill",
            onClose: { dismiss() }
        ) {
            XAgeMetricDetailRow(title: "当前版本", value: versionText)
            XAgeMetricDetailRow(title: "应用名称", value: "小捷")
            XAgeMetricDetailRow(title: "备案信息", value: "皖ICP备2026008853号-2")
            Text("本版本聚焦 XAGE 数据、问答和 X年龄体验：健康数据按来源和测量时间同步，报告上传进入 AI 识别队列，评分在数据不足时先显示待评估。")
                .font(.system(size: 13))
                .foregroundStyle(Color(hex: "496A83"))
                .lineSpacing(3)
                .fixedSize(horizontal: false, vertical: true)
                .padding(14)
                .background(XAgeCapsuleFill())
        }
    }
}

/// 帮助、关于等说明页共用的容器，统一背景、标题、关闭按钮和内容卡片样式。
private struct XAgeSettingsInfoSheetScaffold<Content: View>: View {
    let title: String
    let subtitle: String
    let icon: String
    let onClose: () -> Void
    let content: () -> Content

    /// 注入说明页标题、图标、关闭动作与自定义内容构建闭包。
    init(
        title: String,
        subtitle: String,
        icon: String,
        onClose: @escaping () -> Void,
        @ViewBuilder content: @escaping () -> Content
    ) {
        self.title = title
        self.subtitle = subtitle
        self.icon = icon
        self.onClose = onClose
        self.content = content
    }

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
    var body: some View {
        ZStack {
            XAgeLiquidBackground()
                .ignoresSafeArea()

            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    HStack(spacing: 12) {
                        Image(systemName: icon)
                            .font(.system(size: 22, weight: .bold))
                            .foregroundStyle(Color(hex: "237FC4"))
                            .frame(width: 52, height: 52)
                            .background(XAgeCapsuleFill())
                        VStack(alignment: .leading, spacing: 4) {
                            Text(title)
                                .font(.system(size: 24, weight: .bold))
                                .foregroundStyle(Color(hex: "123E67"))
                            Text(subtitle)
                                .font(.system(size: 13, weight: .medium))
                                .foregroundStyle(Color(hex: "5D7890"))
                        }
                        Spacer()
                        Button(action: onClose) {
                            Image(systemName: "xmark")
                                .font(.system(size: 13, weight: .bold))
                                .foregroundStyle(Color(hex: "1268BD"))
                                .frame(width: 34, height: 34)
                                .background(XAgeCapsuleFill())
                        }
                        .frame(width: 44, height: 44)
                        .contentShape(Rectangle())
                        .buttonStyle(.plain)
                        .accessibilityLabel("关闭")
                    }

                    VStack(alignment: .leading, spacing: 10) {
                        content()
                    }
                    .padding(16)
                    .background(XAgeGlassCardBackground(cornerRadius: 26))
                }
                .padding(24)
            }
            .scrollIndicators(.hidden)
        }
    }
}

private enum XAgeFamilyField: Int, CaseIterable {
    case phone
    case relation
    case inviteCode
    case displayName
}

// MARK: - 家庭关联与逐项授权

/// 新版家庭模式页面，包含生成邀请码、接受邀请和成员权限管理三部分。
/// 邀请相关输入只保存在当前页面；关闭时如有未提交内容，会先要求确认放弃。
private struct XAgeFamilyModeSheet: View {
    @Environment(\.dismiss) private var dismiss
    @StateObject private var vm = FamilyViewModel()
    @State private var invitePhone = ""
    @State private var inviteRelation = ""
    @State private var inviteCode = ""
    @State private var displayName = ""
    @State private var showDiscardConfirmation = false
    @State private var submitting = false
    @FocusState private var focusedField: XAgeFamilyField?

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
    var body: some View {
        ZStack {
            XAgeLiquidBackground()
                .ignoresSafeArea()

            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    HStack {
                        VStack(alignment: .leading, spacing: 4) {
                            Text("关联用户")
                                .font(.system(size: 28, weight: .bold))
                                .foregroundStyle(Color(hex: "123E67"))
                            Text("家庭模式需要逐项授权，敏感健康资料默认不共享。")
                                .font(.system(size: 13, weight: .medium))
                                .foregroundStyle(Color(hex: "5D7890"))
                        }
                        Spacer()
                        Button {
                            requestClose()
                        } label: {
                            Image(systemName: "xmark")
                                .font(.system(size: 13, weight: .bold))
                                .foregroundStyle(Color(hex: "1268BD"))
                                .frame(width: 44, height: 44)
                                .background {
                                    XAgeCapsuleFill()
                                        .frame(width: 34, height: 34)
                                }
                                .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        .disabled(isBusy)
                        .accessibilityLabel("返回设置")
                    }
                    .padding(.top, 10)

                    inviteCard
                    acceptCard
                    membersCard
                }
                .padding(24)
            }
            .scrollIndicators(.hidden)
            .scrollDismissesKeyboard(.interactively)
            .accessibilityHidden(isBusy)

            if isBusy {
                Color.black.opacity(0.03)
                    .ignoresSafeArea()
                    .contentShape(Rectangle())
                ProgressView()
                    .controlSize(.large)
                    .padding(18)
                    .background(XAgeGlassCardBackground(cornerRadius: 22))
            }
        }
        .toolbar {
            ToolbarItemGroup(placement: .keyboard) {
                Spacer()
                Button("完成") {
                    focusedField = nil
                    XAgeKeyboard.dismiss()
                }
            }
        }
        .task { await vm.load() }
        // 页面首次出现时统一加载当前用户、成员、邀请码和权限状态，后续开关直接通过同一 ViewModel 更新。
        .alert("家庭模式提示", isPresented: Binding(
            get: { vm.message != nil },
            set: { if !$0 { vm.message = nil } }
        )) {
            Button("知道了", role: .cancel) {}
        } message: {
            Text(vm.message ?? "")
        }
        .alert("家庭模式错误", isPresented: Binding(
            get: { vm.errorMessage != nil },
            set: { if !$0 { vm.errorMessage = nil } }
        )) {
            Button("知道了", role: .cancel) {}
        } message: {
            Text(vm.errorMessage ?? "")
        }
        .alert("放弃未提交的内容？", isPresented: $showDiscardConfirmation) {
            Button("继续编辑", role: .cancel) {}
            Button("放弃修改", role: .destructive) {
                focusedField = nil
                XAgeKeyboard.dismiss()
                dismiss()
            }
        } message: {
            Text("已填写的邀请码、手机号或关系不会保存。")
        }
    }

    private var hasUnsavedInput: Bool {
        !invitePhone.isEmpty || !inviteRelation.isEmpty || !inviteCode.isEmpty || !displayName.isEmpty
    }

    private var isBusy: Bool {
        vm.loading || submitting
    }

    /// 发起 `requestClose` 对应的权限、关闭或状态变更请求。
    private func requestClose() {
        // 先退出键盘，再根据是否有未提交的邀请码/关系信息决定直接关闭或弹出确认。
        focusedField = nil
        XAgeKeyboard.dismiss()
        if hasUnsavedInput {
            showDiscardConfirmation = true
        } else {
            dismiss()
        }
    }

    /// 构建 `inviteCard` 对应的局部 SwiftUI 视图，并组合所需的展示状态与交互。
    private var inviteCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            XAgeSectionHeader(title: "邀请家人", subtitle: "生成 7 天有效的邀请码")
            HStack(spacing: 8) {
                XAgeGlassTextField(
                    placeholder: "手机号（可选）",
                    text: $invitePhone,
                    keyboardType: .phonePad,
                    field: .phone,
                    focusedField: $focusedField,
                    contentType: .telephoneNumber,
                    capitalization: .never,
                    submitLabel: .next,
                    nextField: .relation
                )
                .accessibilityIdentifier("xage.family.phone")
                XAgeGlassTextField(
                    placeholder: "关系",
                    text: $inviteRelation,
                    field: .relation,
                    focusedField: $focusedField,
                    capitalization: .words,
                    submitLabel: .next,
                    nextField: .inviteCode
                )
                .accessibilityIdentifier("xage.family.relation")
            }
            Button {
                // 生成成功后清空本次邀请输入，最新邀请码由 ViewModel 返回并显示在同一卡片中。
                guard !isBusy else { return }
                focusedField = nil
                XAgeKeyboard.dismiss()
                submitting = true
                Task {
                    defer { submitting = false }
                    vm.errorMessage = nil
                    await vm.createInvite(targetPhone: invitePhone, relation: inviteRelation)
                    if vm.errorMessage == nil {
                        invitePhone = ""
                        inviteRelation = ""
                    }
                }
            } label: {
                XAgeGradientActionLabel(title: "生成邀请码", icon: "person.badge.plus")
            }
            .buttonStyle(.plain)
            .disabled(isBusy)
            .opacity(isBusy ? 0.55 : 1)
            .accessibilityIdentifier("xage.family.createInvite")

            if let invite = vm.latestInvite {
                HStack {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(invite.invite_code)
                            .font(.system(size: 26, weight: .bold, design: .monospaced))
                            .foregroundStyle(Color(hex: "12324F"))
                        Text("家人在自己的账号中输入后加入")
                            .font(.system(size: 12))
                            .foregroundStyle(Color(hex: "6C8194"))
                    }
                    Spacer()
                    Text("7天有效")
                        .font(.system(size: 11, weight: .bold))
                        .foregroundStyle(Color(hex: "347FB7"))
                        .padding(.horizontal, 10)
                        .frame(height: 28)
                        .background(XAgeCapsuleFill())
                }
                .padding(14)
                .background(XAgeCapsuleFill())
            }
        }
        .padding(16)
        .background(XAgeGlassCardBackground(cornerRadius: 26))
    }

    /// 构建 `acceptCard` 对应的局部 SwiftUI 视图，并组合所需的展示状态与交互。
    private var acceptCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            XAgeSectionHeader(title: "加入家庭", subtitle: "输入对方分享的邀请码")
            XAgeGlassTextField(
                placeholder: "邀请码",
                text: $inviteCode,
                field: .inviteCode,
                focusedField: $focusedField,
                capitalization: .characters,
                submitLabel: .next,
                nextField: .displayName
            )
            .accessibilityIdentifier("xage.family.inviteCode")
            XAgeGlassTextField(
                placeholder: "我的显示名（可选）",
                text: $displayName,
                field: .displayName,
                focusedField: $focusedField,
                capitalization: .words,
                submitLabel: .done,
                nextField: nil
            )
            .accessibilityIdentifier("xage.family.displayName")
            Button {
                // 邀请码统一转为大写提交；成功加入后清空输入并由 ViewModel 刷新成员关系。
                guard !isBusy else { return }
                focusedField = nil
                XAgeKeyboard.dismiss()
                submitting = true
                Task {
                    defer { submitting = false }
                    vm.errorMessage = nil
                    await vm.acceptInvite(code: inviteCode.uppercased(), displayName: displayName)
                    if vm.errorMessage == nil {
                        inviteCode = ""
                        displayName = ""
                    }
                }
            } label: {
                XAgeGradientActionLabel(title: "确认加入", icon: "number.square")
            }
            .buttonStyle(.plain)
            .disabled(inviteCode.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || isBusy)
            .opacity(inviteCode.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || isBusy ? 0.55 : 1)
            .accessibilityIdentifier("xage.family.acceptInvite")
        }
        .padding(16)
        .background(XAgeGlassCardBackground(cornerRadius: 26))
    }

    /// 构建 `membersCard` 对应的局部 SwiftUI 视图，并组合所需的展示状态与交互。
    private var membersCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            XAgeSectionHeader(title: "授权管理", subtitle: "家人加入后才会出现在这里")
            let members = vm.members.filter { $0.user_id != vm.currentUserId }
            if members.isEmpty {
                Text("暂无关联用户。邀请或加入家庭后，可以在这里给家人单独开启查看权限。")
                    .font(.system(size: 13))
                    .foregroundStyle(Color(hex: "6C8194"))
                    .lineSpacing(3)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(14)
                    .background(XAgeCapsuleFill())
            } else {
                ForEach(members) { member in
                    XAgeFamilyMemberCard(member: member, vm: vm)
                }
            }
        }
        .padding(16)
        .background(XAgeGlassCardBackground(cornerRadius: 26))
    }
}

/// 单个家庭成员的权限卡片。每个 Toggle 对应独立权限字段，修改后立即向服务端提交该成员的授权值。
private struct XAgeFamilyMemberCard: View {
    let member: FamilyMember
    @ObservedObject var vm: FamilyViewModel

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                VStack(alignment: .leading, spacing: 3) {
                    Text(member.bestName)
                        .font(.system(size: 16, weight: .bold))
                        .foregroundStyle(Color(hex: "173F64"))
                    Text(member.relation ?? member.role)
                        .font(.system(size: 12, weight: .medium))
                        .foregroundStyle(Color(hex: "6C8194"))
                }
                Spacer()
                Text(member.status == "active" ? "已关联" : "待加入")
                    .font(.system(size: 11, weight: .bold))
                    .foregroundStyle(Color(hex: "347FB7"))
                    .frame(width: 58, height: 28)
                    .background(XAgeCapsuleFill())
            }

            ForEach(FamilyPermissionField.allCases) { field in
                Toggle(isOn: Binding(
                    get: { vm.value(for: member.user_id, field: field) },
                    set: { value in
                        Task { await vm.togglePermission(viewerUserId: member.user_id, field: field, value: value) }
                    }
                )) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(field.title)
                            .font(.system(size: 13, weight: .bold))
                            .foregroundStyle(Color(hex: "173F64"))
                        Text(field.subtitle)
                            .font(.system(size: 11))
                            .foregroundStyle(Color(hex: "6C8194"))
                    }
                }
                .tint(Color(hex: "20CDB1"))
            }
        }
        .padding(14)
        .background(XAgeCapsuleFill())
    }
}

private struct XAgeSectionHeader: View {
    let title: String
    let subtitle: String

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(title)
                .font(.system(size: 18, weight: .bold))
                .foregroundStyle(Color(hex: "173F64"))
            Text(subtitle)
                .font(.system(size: 12, weight: .medium))
                .foregroundStyle(Color(hex: "6C8194"))
        }
    }
}

private struct CapsuleButton: View {
    let title: String
    var isEnabled = true
    let action: () -> Void

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
    var body: some View {
        Button(action: action) {
            Text(title)
                .font(.system(size: 12, weight: .bold))
                .foregroundStyle(Color(hex: "365F80"))
                .frame(width: 56, height: 44)
                .background {
                    XAgeCapsuleFill()
                        .frame(height: 30)
                }
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .disabled(!isEnabled)
        .opacity(isEnabled ? 1 : 0.42)
    }
}
