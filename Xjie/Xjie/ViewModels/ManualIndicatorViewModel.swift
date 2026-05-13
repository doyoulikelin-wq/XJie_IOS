import Foundation

@MainActor
final class ManualIndicatorViewModel: ObservableObject {
    @Published var query: String = ""
    @Published var searching = false
    @Published var results: [IndicatorSearchItem] = []
    @Published var selected: IndicatorSearchItem?
    @Published var saving = false
    @Published var savedOk = false
    @Published var errorMessage: String?

    private let api: APIServiceProtocol
    private var searchTask: Task<Void, Never>?

    init(api: APIServiceProtocol = APIService.shared) {
        self.api = api
    }

    func updateQuery(_ q: String) {
        query = q
        searchTask?.cancel()
        let trimmed = q.trimmingCharacters(in: .whitespaces)
        guard !trimmed.isEmpty else {
            results = []
            return
        }
        searchTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 280_000_000)
            guard !Task.isCancelled, let self else { return }
            await self.runSearch(trimmed)
        }
    }

    private func runSearch(_ q: String) async {
        searching = true
        defer { searching = false }
        do {
            let encoded = q.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? q
            let resp: IndicatorSearchResponse = try await api.get("/api/health-data/indicators/search?q=\(encoded)&limit=20")
            guard !Task.isCancelled else { return }
            results = resp.items
        } catch {
            guard !Task.isCancelled else { return }
            // 静默
        }
    }

    func submit(indicatorName: String, value: Double, unit: String?, measuredAt: Date, notes: String?) async {
        saving = true
        defer { saving = false }
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        let body = ManualIndicatorBody(
            indicator_name: indicatorName,
            value: value,
            unit: (unit?.isEmpty ?? true) ? nil : unit,
            measured_at: formatter.string(from: measuredAt),
            notes: (notes?.isEmpty ?? true) ? nil : notes
        )
        do {
            let _: ManualIndicatorItem = try await api.post("/api/health-data/indicators/manual", body: body, timeout: nil)
            savedOk = true
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
