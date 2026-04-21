import Foundation

@MainActor
final class MoodViewModel: ObservableObject {
    @Published var days: [MoodDay] = []
    @Published var correlation: MoodGlucoseCorrelation?
    @Published var loading = false
    @Published var saving = false
    @Published var errorMessage: String?
    @Published var lookbackDays: Int = 7

    private let api: APIServiceProtocol

    init(api: APIServiceProtocol = APIService.shared) {
        self.api = api
    }

    /// Today's snapshot for the 5 segments — drawn from `days.last` if it
    /// matches today, else returns nil for every segment.
    var today: MoodDay? {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd"
        f.timeZone = .current
        let key = f.string(from: Date())
        return days.first(where: { $0.date == key })
    }

    func refresh() async {
        loading = true
        defer { loading = false }
        do {
            async let daysReq: [MoodDay] = api.get("/api/mood/days?days=\(lookbackDays)")
            async let corrReq: MoodGlucoseCorrelation = api.get("/api/mood/correlation?days=\(max(lookbackDays, 7))")
            days = try await daysReq
            correlation = try? await corrReq
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func checkIn(segment: MoodSegment, level: MoodLevel) async {
        saving = true
        defer { saving = false }
        let iso = ISO8601DateFormatter()
        iso.formatOptions = [.withInternetDateTime]
        let payload = MoodLogIn(
            ts: iso.string(from: Date()),
            segment: segment.rawValue,
            mood_level: level.rawValue,
            note: nil
        )
        do {
            let _: MoodLogOut = try await api.post("/api/mood/logs", body: payload, timeout: nil)
            await refresh()
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
