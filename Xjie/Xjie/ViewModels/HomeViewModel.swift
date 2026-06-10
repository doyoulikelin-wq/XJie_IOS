import Foundation

/// 首页 ViewModel — ARCH-02: 依赖注入 APIServiceProtocol
/// NET-03: 离线缓存支持
@MainActor
final class HomeViewModel: ObservableObject {
    @Published var loading = false
    @Published var dashboard: DashboardHealth?
    @Published var treeSummary: HealthTreeSummary?
    @Published var contextPrecision = ContextPrecisionSummary.empty
    @Published var errorMessage: String?
    @Published var isOfflineData = false

    private let api: APIServiceProtocol
    private let cache = OfflineCacheManager.shared
    private let dashboardCacheKey = "dashboard_health"

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
        treeSummary = try? await api.get("/api/health-plans/tree-summary")
        contextPrecision = await fetchContextPrecision()
    }

    private func fetchContextPrecision() async -> ContextPrecisionSummary {
        async let recordsReq: DocumentListResponse? = try? api.get("/api/health-data/documents?doc_type=record")
        async let examsReq: DocumentListResponse? = try? api.get("/api/health-data/documents?doc_type=exam")
        async let summaryReq: HealthDataSummary? = try? api.get("/api/health-data/summary")
        async let indicatorsReq: IndicatorListResponse? = try? api.get("/api/health-data/indicators")
        async let historyReq: ElderlyCheckinList? = try? api.get("/api/elderly?limit=100&days=30")

        let records = await recordsReq?.items?.count ?? 0
        let exams = await examsReq?.items?.count ?? 0
        let hasSummary = await !(summaryReq?.summary_text?.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ?? true)
        let indicators = await indicatorsReq?.indicators.count ?? 0
        let history = await historyReq?.items ?? []
        let moodCount = history.filter { ($0.mood ?? "").isEmpty == false }.count
        let bodyCount = history.filter { ($0.body_feeling ?? "").isEmpty == false }.count

        return ContextPrecisionSummary(
            healthRecordCount: records,
            healthExamCount: exams,
            healthIndicatorCount: indicators,
            hasHealthSummary: hasSummary,
            historyFeedbackCount: history.count,
            historyMoodCount: moodCount,
            historyBodyCount: bodyCount,
            omicsCategoryCount: 0,
            omicsItemCount: 0
        )
    }
}

struct ContextPrecisionSummary: Equatable {
    let healthRecordCount: Int
    let healthExamCount: Int
    let healthIndicatorCount: Int
    let hasHealthSummary: Bool
    let historyFeedbackCount: Int
    let historyMoodCount: Int
    let historyBodyCount: Int
    let omicsCategoryCount: Int
    let omicsItemCount: Int

    static let empty = ContextPrecisionSummary(
        healthRecordCount: 0,
        healthExamCount: 0,
        healthIndicatorCount: 0,
        hasHealthSummary: false,
        historyFeedbackCount: 0,
        historyMoodCount: 0,
        historyBodyCount: 0,
        omicsCategoryCount: 0,
        omicsItemCount: 0
    )

    var score: Int {
        let healthScore = min(40, healthRecordCount * 8 + healthExamCount * 8 + healthIndicatorCount * 2 + (hasHealthSummary ? 6 : 0))
        let historyScore = min(30, historyFeedbackCount * 4 + historyMoodCount * 2 + historyBodyCount * 2)
        let omicsScore = min(30, omicsCategoryCount * 6 + min(omicsItemCount, 18))
        return min(100, healthScore + historyScore + omicsScore)
    }

    var healthDataDescription: String {
        "病例 \(healthRecordCount) 份 · 体检 \(healthExamCount) 份 · 指标 \(healthIndicatorCount) 项"
    }

    var historyDescription: String {
        "反馈 \(historyFeedbackCount) 条 · 心情 \(historyMoodCount) 条 · 身体状态 \(historyBodyCount) 条"
    }

    var omicsDescription: String {
        omicsCategoryCount > 0 ? "\(omicsCategoryCount) 类 · \(omicsItemCount) 项特征" : "暂无真实多组学上传"
    }
}
