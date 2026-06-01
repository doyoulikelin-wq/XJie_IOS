import Foundation

@MainActor
final class GlucoseViewModel: ObservableObject {
    @Published var loading = false
    @Published var window = "24h"
    @Published var points: [GlucosePoint] = []
    /// PERF-02: 预计算的图表数据，避免 Canvas 每帧解析日期
    @Published var chartData: [(date: Date, value: Double)] = []
    @Published var summary: GlucoseSummary?
    @Published var cgmQuality: CGMQuality?
    @Published var range: GlucoseRange?
    @Published var errorMessage: String?

    private let api: APIServiceProtocol
    /// PERF-04: 切换窗口时取消上一次请求
    private var pointsTask: Task<Void, Never>?

    init(api: APIServiceProtocol = APIService.shared) {
        self.api = api
    }

    func cancelTasks() { pointsTask?.cancel(); pointsTask = nil }

    func fetchRange() async {
        do {
            range = try await api.get("/api/glucose/range")
        } catch {
            guard !Task.isCancelled else { return }
            errorMessage = error.localizedDescription
        }
        await fetchPoints()
    }

    func fetchPoints() async {
        pointsTask?.cancel()
        let task = Task { @MainActor [weak self] in
            guard let self else { return }
            loading = true
            defer { loading = false }

            let now = Date()
            let from: Date
            switch window {
            case "24h": from = now.addingTimeInterval(-24 * 3600)
            case "7d": from = now.addingTimeInterval(-7 * 24 * 3600)
            default:
                if let minTs = range?.min_ts {
                    from = Utils.parseISO(minTs) ?? now.addingTimeInterval(-30 * 24 * 3600)
                } else {
                    from = now.addingTimeInterval(-30 * 24 * 3600)
                }
            }

            let fromStr = ISO8601DateFormatter().string(from: from)
            let toStr = ISO8601DateFormatter().string(from: now)

            let path = URLBuilder.path("/api/glucose", queryItems: [
                URLQueryItem(name: "from", value: fromStr),
                URLQueryItem(name: "to", value: toStr),
                URLQueryItem(name: "limit", value: "2000"),
            ])

            do {
                let fetched: [GlucosePoint] = try await api.get(path)
                guard !Task.isCancelled else { return }
                points = fetched
                chartData = fetched.compactMap { pt in
                    guard let date = Utils.parseISO(pt.ts) else { return nil }
                    return (date: date, value: pt.glucose_mgdl)
                }
            } catch {
                guard !Task.isCancelled else { return }
                errorMessage = error.localizedDescription
            }

            guard !Task.isCancelled else { return }
            let dashboard: DashboardHealth? = try? await api.get("/api/dashboard/health")
            guard !Task.isCancelled else { return }
            cgmQuality = dashboard?.cgm_quality
            summary = window == "24h"
                ? dashboard?.glucose?.last_24h
                : dashboard?.glucose?.last_7d
        }
        pointsTask = task
        await task.value
    }
}
