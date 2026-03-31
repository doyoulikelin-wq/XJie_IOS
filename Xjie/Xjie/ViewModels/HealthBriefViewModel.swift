import Foundation

@MainActor
final class HealthBriefViewModel: ObservableObject {
    @Published var loading = false
    @Published var briefing: TodayBriefing?
    @Published var reports: HealthReports?
    @Published var aiSummary = ""
    @Published var summaryLoading = false
    @Published var errorMessage: String?

    private let api: APIServiceProtocol

    init(api: APIServiceProtocol = APIService.shared) {
        self.api = api
    }

    func fetchData() async {
        loading = true
        defer { loading = false }
        async let b: TodayBriefing? = try? await api.get("/api/agent/today")
        async let r: HealthReports? = try? await api.get("/api/health-reports")
        async let s: HealthDataSummary? = try? await api.get("/api/health-data/summary")
        let fetchedBriefing = await b
        let fetchedReports = await r
        let fetchedSummary = await s
        guard !Task.isCancelled else { return }
        briefing = fetchedBriefing
        reports = fetchedReports
        if let text = fetchedSummary?.summary_text, !text.isEmpty {
            aiSummary = text
        }
    }

    func loadAISummary() async {
        summaryLoading = true
        defer { summaryLoading = false }
        do {
            let res: HealthDataSummary = try await api.post("/api/health-data/summary/generate")
            guard !Task.isCancelled else { return }
            aiSummary = res.summary_text ?? "暂无摘要"
        } catch {
            guard !Task.isCancelled else { return }
            aiSummary = "获取失败，请重试"
            errorMessage = error.localizedDescription
        }
    }
}
