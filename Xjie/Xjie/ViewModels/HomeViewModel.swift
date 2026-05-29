import Foundation

/// 首页 ViewModel — ARCH-02: 依赖注入 APIServiceProtocol
/// NET-03: 离线缓存支持
@MainActor
final class HomeViewModel: ObservableObject {
    @Published var loading = false
    @Published var dashboard: DashboardHealth?
    @Published var proactive: ProactiveMessage?
    @Published var treeSummary: HealthTreeSummary?
    @Published var errorMessage: String?
    @Published var isOfflineData = false
    @Published var interventionLevel: Double = 1  // 0..4 对应 L1..L5
    @Published var elderlyMode: Bool = false

    private let api: APIServiceProtocol
    private let cache = OfflineCacheManager.shared
    private let dashboardCacheKey = "dashboard_health"

    private static let levelMap: [Int: String] = [0: "L1", 1: "L2", 2: "L3", 3: "L4", 4: "L5"]
    private static let reverseLevelMap: [String: Double] = ["L1": 0, "L2": 1, "L3": 2, "L4": 3, "L5": 4]

    init(api: APIServiceProtocol = APIService.shared) {
        self.api = api
    }

    func fetchData() async {
        loading = true
        defer { loading = false }
        do {
            let d: DashboardHealth = try await api.get("/api/dashboard/health")
            guard !Task.isCancelled else { return }
            dashboard = d
            isOfflineData = false
            cache.save(d, for: dashboardCacheKey)
        } catch {
            guard !Task.isCancelled else { return }
            // NET-03: 失败时加载离线缓存
            if let cached: DashboardHealth = cache.load(for: dashboardCacheKey) {
                dashboard = cached
                isOfflineData = true
            } else {
                errorMessage = error.localizedDescription
            }
        }
        guard !Task.isCancelled else { return }
        proactive = try? await api.get("/api/agent/proactive")
        treeSummary = try? await api.get("/api/health-plans/tree-summary")

        // Fetch current intervention level
        if let settings: UserSettings = try? await api.get("/api/users/settings") {
            interventionLevel = Self.reverseLevelMap[settings.intervention_level ?? "L2"] ?? 1
            elderlyMode = settings.elderly_mode ?? false
        }
    }

    func updateInterventionLevel(_ value: Double) async {
        let idx = Int(value.rounded())
        guard let level = Self.levelMap[idx] else { return }
        do {
            try await api.patchVoid("/api/users/settings", body: UpdateSettingsBody(intervention_level: level))
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
