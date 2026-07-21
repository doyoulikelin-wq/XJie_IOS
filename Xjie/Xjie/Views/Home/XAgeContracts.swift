import AVFoundation
import Speech
import SwiftUI
import UIKit

enum XAgeTopSection: String, CaseIterable, Identifiable {
    case data = "数据"
    case chat = "问答"
    case xAge = "X年龄"

    var id: String { rawValue }
}

typealias XAgeQuickActionSpec = (id: String, title: String, systemImage: String, destination: String?)

enum XAgeConversationModuleDestination: String, Equatable, Sendable {
    case meals
    case reports
    case medications
    case profile
}

struct XAgeConversationNavigationAction: Identifiable, Equatable, Sendable {
    let destination: XAgeConversationModuleDestination
    let title: String
    let systemImage: String

    var id: String { destination.rawValue }

    static let available: [Self] = [
        .init(destination: .meals, title: "膳食", systemImage: "fork.knife"),
        .init(destination: .reports, title: "报告", systemImage: "doc.text.fill"),
        .init(destination: .medications, title: "用药", systemImage: "pills.fill"),
        .init(destination: .profile, title: "画像", systemImage: "person.text.rectangle.fill")
    ]

    @discardableResult
    func open(preserving draft: String, navigate: (Self) -> Void) -> String {
        navigate(self); return draft
    }

    func handoff(preserving draft: String) -> XAgeConversationModuleHandoff {
        XAgeConversationModuleHandoff(
            action: self,
            dietaryEntry: destination == .meals ? DietaryEntryHandoff.chatCopy(draft) : nil
        )
    }
}

struct XAgeConversationModuleHandoff: Equatable, Sendable {
    let action: XAgeConversationNavigationAction
    let dietaryEntry: DietaryEntryHandoff?
}

private struct XAgeConversationModuleOpenKey: EnvironmentKey { static let defaultValue: (XAgeConversationModuleHandoff) -> Void = { _ in } }

extension EnvironmentValues {
    var xAgeOpenConversationModule: (XAgeConversationModuleHandoff) -> Void { get { self[XAgeConversationModuleOpenKey.self] } set { self[XAgeConversationModuleOpenKey.self] = newValue } }
}

enum XAgeDevicePageState: Equatable, Sendable { case loading, empty, unsupported }

struct XAgeDeviceManagementContract {
    static let destinationID = "device-management", unsupportedTitle = "首批设备协议尚未开放"
    static let currentProtocolAvailable = false
    static let availableMutationIDs: [String] = []

    static func state(isLoading: Bool, protocolAvailable: Bool = currentProtocolAvailable) -> XAgeDevicePageState {
        isLoading ? .loading : protocolAvailable ? .empty : .unsupported
    }
}

extension XAgeDataPanelCategory {
    /// The single source of truth for the horizontally scrolling home shortcuts.
    /// Every item resolves to a real destination or a local editor owned by the
    /// data page; data-card management is exposed separately in the top toolbar.
    static let homeQuickActions: [XAgeQuickActionSpec] = [
        ("meals", "饮食", "fork.knife", "meals"),
//        ("mood", "感受", "face.smiling", "mood"),
        ("weight", "体重", "scalemass.fill", "weight"),
        ("reports", "报告", "doc.text.fill", "reports"),
        ("medications", "用药", "pills.fill", "medications"),
        //临时注释健康计划按钮，待页面重新设计再放出。
//        ("health-plan", "健康计划", "checklist", "health-plan"),
        ("medical", "就医助手", "cross.case.fill", "medical")
    ]

    /// “更多” is an account/support surface. Business shortcuts must not be
    /// duplicated here; profile is its only health-data entry, while hardware status is separate.
    static let moreProfileCategories: [XAgeDataPanelCategory] = [.profile]
}

/// 首页快捷功能只保存稳定 ID 的排列，不复制标题、图标或路由，避免版本升级后读取旧配置
/// 覆盖新的产品定义。未知/重复 ID 会被过滤，新版本增加的入口会自动追加到末尾。
enum XAgeQuickActionPreferences {
    private static let orderKey = "xage.home.quick-action.order.v1"
    #if DEBUG
    private static let resetArgument = "XJIE_UI_TEST_RESET_QUICK_ACTIONS"
    private static let resetMarkerKeyPrefix = "xage.home.quick-action.ui-test-reset."
    #endif

    static func load(userDefaults: UserDefaults = .standard) -> [XAgeQuickActionSpec] {
        #if DEBUG
        resetForUITestIfNeeded(userDefaults: userDefaults)
        #endif
        return orderedActions(savedIDs: userDefaults.stringArray(forKey: orderKey))
    }

    static func save(
        _ actions: [XAgeQuickActionSpec],
        userDefaults: UserDefaults = .standard
    ) {
        userDefaults.set(actions.map(\.id), forKey: orderKey)
    }

    static func orderedActions(savedIDs: [String]?) -> [XAgeQuickActionSpec] {
        let available = XAgeDataPanelCategory.homeQuickActions
        guard let savedIDs, !savedIDs.isEmpty else { return available }
        let actionsByID = Dictionary(uniqueKeysWithValues: available.map { ($0.id, $0) })
        var seen = Set<String>()
        let restored = savedIDs.compactMap { identifier -> XAgeQuickActionSpec? in
            guard seen.insert(identifier).inserted else { return nil }
            return actionsByID[identifier]
        }
        return restored + available.filter { seen.insert($0.id).inserted }
    }

    static func reordered(
        _ actions: [XAgeQuickActionSpec],
        draggedID: String,
        targetID: String
    ) -> [XAgeQuickActionSpec] {
        guard draggedID != targetID,
              let sourceIndex = actions.firstIndex(where: { $0.id == draggedID }),
              let targetIndex = actions.firstIndex(where: { $0.id == targetID }) else {
            return actions
        }
        var reordered = actions
        reordered.move(
            fromOffsets: IndexSet(integer: sourceIndex),
            toOffset: targetIndex > sourceIndex ? targetIndex + 1 : targetIndex
        )
        return reordered
    }

    #if DEBUG
    /// 每个 UI 测试进程只清理一次持久化顺序，让拖拽断言始终从产品默认排列开始；
    /// 使用进程号作为标记可避免页面重建时再次清理用户刚在本次测试中完成的排序。
    private static func resetForUITestIfNeeded(userDefaults: UserDefaults) {
        guard ProcessInfo.processInfo.arguments.contains(resetArgument) else { return }
        let markerKey = resetMarkerKeyPrefix + String(ProcessInfo.processInfo.processIdentifier)
        guard !userDefaults.bool(forKey: markerKey) else { return }
        userDefaults.removeObject(forKey: orderKey)
        userDefaults.set(true, forKey: markerKey)
    }
    #endif
}

extension View {
    @ViewBuilder
    func xAgeAccessibilitySelected(_ isSelected: Bool) -> some View {
        if isSelected {
            accessibilityAddTraits(.isSelected)
        } else {
            self
        }
    }

    @ViewBuilder
    func xAgeAccessibilityButton(_ isButton: Bool) -> some View {
        if isButton {
            accessibilityAddTraits(.isButton)
        } else {
            self
        }
    }

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
enum XAgeKeyboard {
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
struct XAgeVerticalKeyboardDismissInstaller: UIViewRepresentable {
    let onDismiss: () -> Void

    func makeCoordinator() -> Coordinator {
        Coordinator(onDismiss: onDismiss)
    }

    func makeUIView(context: Context) -> UIView {
        let view = UIView(frame: .zero)
        view.isUserInteractionEnabled = false
        context.coordinator.install(from: view)
        return view
    }

    func updateUIView(_ uiView: UIView, context: Context) {
        context.coordinator.onDismiss = onDismiss
        context.coordinator.install(from: uiView)
    }

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

        init(onDismiss: @escaping () -> Void) {
            self.onDismiss = onDismiss
        }

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

        func detach() {
            installedScrollView?.removeGestureRecognizer(panGesture)
            installedScrollView = nil
        }

        func invalidate() {
            isActive = false
            detach()
        }

        func gestureRecognizerShouldBegin(_ gestureRecognizer: UIGestureRecognizer) -> Bool {
            guard let pan = gestureRecognizer as? UIPanGestureRecognizer else { return false }
            let velocity = pan.velocity(in: pan.view)
            return velocity.y > 0 && abs(velocity.y) > abs(velocity.x) * 1.2
        }

        func gestureRecognizer(
            _ gestureRecognizer: UIGestureRecognizer,
            shouldRecognizeSimultaneouslyWith otherGestureRecognizer: UIGestureRecognizer
        ) -> Bool {
            true
        }

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

@MainActor
private struct XAgeDownwardKeyboardDismissModifier: ViewModifier {
    let verificationIdentifier: String?
    let onDismiss: () -> Void

    func body(content: Content) -> some View {
        content
            .background {
                XAgeVerticalKeyboardDismissInstaller {
                    dismissKeyboard()
                }
                .frame(width: 0, height: 0)
            }
            .overlay(alignment: .topLeading) {
                #if DEBUG
                if let verificationIdentifier {
                    Color.clear
                        .frame(width: 1, height: 1)
                        .accessibilityElement(children: .ignore)
                        .accessibilityIdentifier(verificationIdentifier)
                        .allowsHitTesting(false)
                }
                #endif
            }
    }

    private func dismissKeyboard() {
        onDismiss()
        XAgeKeyboard.dismiss()
    }
}

extension View {
    @MainActor
    func xAgeDismissKeyboardOnDownwardPull(
        verificationIdentifier: String? = nil,
        _ onDismiss: @escaping () -> Void
    ) -> some View {
        modifier(
            XAgeDownwardKeyboardDismissModifier(
                verificationIdentifier: verificationIdentifier,
                onDismiss: onDismiss
            )
        )
    }
}

struct XAgeDataCardPreferenceSnapshot {
    var isCustomized: Bool
    var ids: [String]
}

@MainActor
enum XAgeDataCardPreferences {
    private static let idsKey = "xage.data.card.ids.v1"
    private static let customizedKey = "xage.data.card.customized.v1"
    private static let scopedIDsKeyPrefix = "xage.data.card.ids.v2."
    private static let scopedCustomizedKeyPrefix = "xage.data.card.customized.v2."
    #if DEBUG
    private static let resetArgument = "XJIE_UI_TEST_RESET_DATA_CARDS"
    private static var didApplyUITestReset = false
    #endif

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

        // The legacy global preference stores layout IDs only, never metric values.
        // Copying it once preserves the user's layout without carrying account data.
        let legacy = XAgeDataCardPreferenceSnapshot(
            isCustomized: UserDefaults.standard.bool(forKey: customizedKey),
            ids: UserDefaults.standard.stringArray(forKey: idsKey) ?? []
        )
        if legacy.isCustomized {
            UserDefaults.standard.set(dedupedIDs(legacy.ids), forKey: scopedIDsKey)
            UserDefaults.standard.set(true, forKey: scopedCustomizedKey)
        }
        // Legacy layout migration is single-use. A later account must start with its
        // own layout instead of inheriting the first account's global preference.
        UserDefaults.standard.removeObject(forKey: idsKey)
        UserDefaults.standard.removeObject(forKey: customizedKey)
        return legacy
    }

    static func initialMetrics(accountScope: String?) -> [XAgeMetric] {
        let snapshot = load(accountScope: accountScope)
        return placeholderMetrics(for: snapshot)
    }

    static func placeholderMetrics(for snapshot: XAgeDataCardPreferenceSnapshot) -> [XAgeMetric] {
        guard snapshot.isCustomized else { return XAgeMetric.defaultCards }
        return orderedMetrics(for: snapshot, from: XAgeMetric.catalogSections(serverMetrics: []).flatMap(\.metrics))
    }

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

    static func orderedMetrics(for snapshot: XAgeDataCardPreferenceSnapshot, from source: [XAgeMetric]) -> [XAgeMetric] {
        guard snapshot.isCustomized else { return dedupedMetrics(source) }
        let lookup = firstMetricByID(from: source)
        return snapshot.ids.compactMap { lookup[$0] }
    }

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

    private static func dedupedIDs(_ ids: [String]) -> [String] {
        var seen = Set<String>()
        return ids.filter { seen.insert($0).inserted }
    }

    #if DEBUG
    private static func shouldResetForUITest() -> Bool {
        let environment = ProcessInfo.processInfo.environment
        if let value = environment[resetArgument], ["1", "true", "YES", "yes"].contains(value) {
            return true
        }
        return ProcessInfo.processInfo.arguments.contains(resetArgument)
    }
    #endif

    private static func reset() {
        UserDefaults.standard.removeObject(forKey: idsKey)
        UserDefaults.standard.removeObject(forKey: customizedKey)
        for key in UserDefaults.standard.dictionaryRepresentation().keys
            where key.hasPrefix(scopedIDsKeyPrefix) || key.hasPrefix(scopedCustomizedKeyPrefix) {
            UserDefaults.standard.removeObject(forKey: key)
        }
    }

    private static func storageToken(for accountScope: String) -> String {
        Data(accountScope.utf8).base64EncodedString()
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "=", with: "")
    }

    #if DEBUG
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
    nonisolated static func shouldShowHomeAuthorization(hasSuccessfulSync: Bool) -> Bool {
        !hasSuccessfulSync
    }

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

enum XAgeHealthTrendRequestContract {
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

    static func metricID(forIndicatorName indicatorName: String) -> String? {
        identifierByIndicatorName[normalize(indicatorName)]
    }

    static func categoryDisplayValue(forIndicatorName indicatorName: String, value: Double) -> String? {
        guard value.isFinite,
              value.rounded() == value,
              let metricID = metricID(forIndicatorName: indicatorName),
              categoryMetricIDs.contains(metricID) else {
            return nil
        }
        return AppleHealthStore.categoryDisplayValue(metricID: metricID, value: Int(value))
    }

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

    private static func normalize(_ value: String) -> String {
        value.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    }
}

struct XAgeAccountScopedRefreshGate: Equatable {
    private(set) var accountScope: String?
    private(set) var generation = 0

    @discardableResult
    mutating func switchAccount(to scope: String?) -> Bool {
        let normalized = Self.normalize(scope)
        guard normalized != accountScope else { return false }
        accountScope = normalized
        generation += 1
        return true
    }

    func accepts(startedScope: String, generation startedGeneration: Int, currentScope: String?) -> Bool {
        accountScope == startedScope
            && generation == startedGeneration
            && Self.normalize(currentScope) == startedScope
    }

    private static func normalize(_ scope: String?) -> String? {
        guard let value = scope?.trimmingCharacters(in: .whitespacesAndNewlines),
              !value.isEmpty else {
            return nil
        }
        return value
    }
}
