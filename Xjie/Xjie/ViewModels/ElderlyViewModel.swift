import Foundation

@MainActor
final class ElderlyViewModel: ObservableObject {
    @Published var status: ElderlyTodayStatus?
    @Published var history: [ElderlyCheckin] = []
    @Published var loading = false
    @Published var submitting = false
    @Published var errorMessage: String?

    private let api: APIServiceProtocol

    init(api: APIServiceProtocol = APIService.shared) {
        self.api = api
    }

    var isEnabled: Bool { status?.enabled ?? false }
    var shouldPrompt: Bool { status?.should_prompt ?? false }

    func fetchStatus() async {
        do {
            let s: ElderlyTodayStatus = try await api.get("/api/elderly/today")
            status = s
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func fetchHistory(days: Int = 30, limit: Int = 50) async {
        loading = true
        defer { loading = false }
        do {
            let list: ElderlyCheckinList = try await api.get("/api/elderly?limit=\(limit)&days=\(days)")
            history = list.items
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func submit(
        activity: String?,
        bodyFeeling: BodyFeeling?,
        mood: MoodChoice?,
        note: String?,
        source: String = "auto_prompt"
    ) async -> Bool {
        submitting = true
        defer { submitting = false }
        let body = ElderlyCheckinBody(
            activity: activity?.trimmingCharacters(in: .whitespaces).nonEmpty,
            body_feeling: bodyFeeling?.rawValue,
            mood: mood?.rawValue,
            note: note?.trimmingCharacters(in: .whitespaces).nonEmpty,
            source: source
        )
        if body.activity == nil && body.body_feeling == nil && body.mood == nil && body.note == nil {
            errorMessage = "请至少填写一项"
            return false
        }
        do {
            let saved: ElderlyCheckin = try await api.post("/api/elderly/checkin", body: body, timeout: nil)
            history.insert(saved, at: 0)
            await fetchStatus()
            return true
        } catch {
            errorMessage = error.localizedDescription
            return false
        }
    }

    func delete(_ id: Int) async {
        do {
            try await api.deleteVoid("/api/elderly/\(id)")
            history.removeAll { $0.id == id }
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}

private extension String {
    var nonEmpty: String? { isEmpty ? nil : self }
}
