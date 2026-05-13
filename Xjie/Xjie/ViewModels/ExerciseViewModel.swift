import Foundation

@MainActor
final class ExerciseViewModel: ObservableObject {
    @Published var loading = false
    @Published var items: [ExerciseItem] = []
    @Published var totalMinutes: Int = 0
    @Published var totalKcal: Double = 0
    @Published var showAdd = false
    @Published var errorMessage: String?

    private let api: APIServiceProtocol

    init(api: APIServiceProtocol = APIService.shared) {
        self.api = api
    }

    func load() async {
        loading = true
        defer { loading = false }
        do {
            let resp: ExerciseListResponse = try await api.get("/api/exercise")
            guard !Task.isCancelled else { return }
            items = resp.items
            totalMinutes = resp.total_minutes
            totalKcal = resp.total_kcal
        } catch {
            guard !Task.isCancelled else { return }
            errorMessage = error.localizedDescription
        }
    }

    func add(_ body: ExerciseBody) async {
        do {
            let _: ExerciseItem = try await api.post("/api/exercise", body: body, timeout: nil)
            showAdd = false
            await load()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func delete(_ id: Int) async {
        do {
            try await api.deleteVoid("/api/exercise/\(id)")
            await load()
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
