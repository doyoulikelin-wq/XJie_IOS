import Foundation

/// 病史整理仓库 — 对接 /api/health-data/patient-history
protocol PatientHistoryRepositoryProtocol: Sendable {
    func fetch() async throws -> PatientHistoryProfile
    func save(_ profile: PatientHistoryProfileIn) async throws -> PatientHistoryProfile
}

actor PatientHistoryRepository: PatientHistoryRepositoryProtocol {
    private let api: APIServiceProtocol

    init(api: APIServiceProtocol = APIService.shared) {
        self.api = api
    }

    func fetch() async throws -> PatientHistoryProfile {
        try await api.get("/api/health-data/patient-history")
    }

    func save(_ profile: PatientHistoryProfileIn) async throws -> PatientHistoryProfile {
        try await api.put("/api/health-data/patient-history", body: profile)
    }
}
