import Foundation

protocol MedicationRepositoryProtocol: Sendable {
    func list() async throws -> [Medication]
    func create(_ body: MedicationBody) async throws -> Medication
    func update(id: Int, body: MedicationBody) async throws -> Medication
    func delete(id: Int) async throws
    func recognize(rawText: String) async throws -> MedicationRecognizeResult
}

actor MedicationRepository: MedicationRepositoryProtocol {
    private let api: APIServiceProtocol
    init(api: APIServiceProtocol = APIService.shared) { self.api = api }

    func list() async throws -> [Medication] {
        let r: MedicationListResponse = try await api.get("/api/medications")
        return r.items
    }

    func create(_ body: MedicationBody) async throws -> Medication {
        try await api.post("/api/medications", body: body)
    }

    func update(id: Int, body: MedicationBody) async throws -> Medication {
        try await api.patch("/api/medications/\(id)", body: body)
    }

    func delete(id: Int) async throws {
        try await api.deleteVoid("/api/medications/\(id)")
    }

    func recognize(rawText: String) async throws -> MedicationRecognizeResult {
        try await api.post("/api/medications/recognize", body: MedicationRecognizeBody(raw_text: rawText))
    }
}
