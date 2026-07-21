import Foundation

protocol MedicationRepositoryProtocol: Sendable {
    func fetchToday(
        subjectUserID: Int?,
        localDate: String,
        timezoneOffsetMinutes: Int
    ) async throws -> MedicationTodaySummary
    func fetchPlans(subjectUserID: Int) async throws -> TrustedMedicationPlanList
    func fetchPrefillCandidates(subjectUserID: Int) async throws -> MedicationPrefillList
    func fetchReactions(subjectUserID: Int) async throws -> MedicationReactionList
    func fetchLegacyReadOnly() async throws -> [Medication]

    func recognize(
        _ request: MedicationRecognitionBody,
        expectedAccountScope: String
    ) async throws -> MedicationRecognitionResult
    func confirmPlan(
        _ request: MedicationPlanConfirmRequest,
        expectedAccountScope: String
    ) async throws -> TrustedMedicationPlan
    func revisePlan(
        planID: Int,
        request: MedicationPlanReviseRequest,
        expectedAccountScope: String
    ) async throws -> TrustedMedicationPlan
    func updatePlanStatus(
        planID: Int,
        request: MedicationPlanStatusRequest,
        expectedAccountScope: String
    ) async throws -> TrustedMedicationPlan
    func rejectPrefill(
        candidateID: Int,
        request: MedicationPrefillRejectRequest,
        expectedAccountScope: String
    ) async throws -> MedicationPrefillCandidate
    func recordDose(
        _ request: MedicationDoseActionRequest,
        expectedAccountScope: String
    ) async throws -> MedicationDoseEvent
    func createReaction(
        _ request: MedicationReactionCreateRequest,
        expectedAccountScope: String
    ) async throws -> MedicationReaction
    func correctReaction(
        reactionKey: String,
        request: MedicationReactionCorrectRequest,
        expectedAccountScope: String
    ) async throws -> MedicationReaction
    func retractReaction(
        reactionKey: String,
        request: MedicationReactionRetractRequest,
        expectedAccountScope: String
    ) async throws -> MedicationReaction
}

actor MedicationRepository: MedicationRepositoryProtocol {
    private let api: APIServiceProtocol

    init(api: APIServiceProtocol = APIService.shared) {
        self.api = api
    }

    func fetchToday(
        subjectUserID: Int?,
        localDate: String,
        timezoneOffsetMinutes: Int
    ) async throws -> MedicationTodaySummary {
        var query = ["local_date=\(localDate)", "timezone_offset_minutes=\(timezoneOffsetMinutes)"]
        if let subjectUserID {
            query.insert("subject_user_id=\(subjectUserID)", at: 0)
        }
        return try await api.get("/api/medications/trust/today?\(query.joined(separator: "&"))")
    }

    func fetchPlans(subjectUserID: Int) async throws -> TrustedMedicationPlanList {
        try await api.get("/api/medications/trust/plans?subject_user_id=\(subjectUserID)")
    }

    func fetchPrefillCandidates(subjectUserID: Int) async throws -> MedicationPrefillList {
        try await api.get("/api/medications/trust/prefill-candidates?subject_user_id=\(subjectUserID)")
    }

    func fetchReactions(subjectUserID: Int) async throws -> MedicationReactionList {
        try await api.get("/api/medications/trust/reactions?subject_user_id=\(subjectUserID)")
    }

    func fetchLegacyReadOnly() async throws -> [Medication] {
        let response: MedicationListResponse = try await api.get("/api/medications")
        return response.items
    }

    func recognize(
        _ request: MedicationRecognitionBody,
        expectedAccountScope: String
    ) async throws -> MedicationRecognitionResult {
        try await api.postAccountBound(
            "/api/medications/recognize",
            body: request,
            expectedAccountScope: expectedAccountScope
        )
    }

    func confirmPlan(
        _ request: MedicationPlanConfirmRequest,
        expectedAccountScope: String
    ) async throws -> TrustedMedicationPlan {
        try await api.postAccountBound(
            "/api/medications/trust/plans/confirm",
            body: request,
            expectedAccountScope: expectedAccountScope
        )
    }

    func revisePlan(
        planID: Int,
        request: MedicationPlanReviseRequest,
        expectedAccountScope: String
    ) async throws -> TrustedMedicationPlan {
        try await api.postAccountBound(
            "/api/medications/trust/plans/\(planID)/revise",
            body: request,
            expectedAccountScope: expectedAccountScope
        )
    }

    func updatePlanStatus(
        planID: Int,
        request: MedicationPlanStatusRequest,
        expectedAccountScope: String
    ) async throws -> TrustedMedicationPlan {
        try await api.postAccountBound(
            "/api/medications/trust/plans/\(planID)/status",
            body: request,
            expectedAccountScope: expectedAccountScope
        )
    }

    func rejectPrefill(
        candidateID: Int,
        request: MedicationPrefillRejectRequest,
        expectedAccountScope: String
    ) async throws -> MedicationPrefillCandidate {
        try await api.postAccountBound(
            "/api/medications/trust/prefill-candidates/\(candidateID)/reject",
            body: request,
            expectedAccountScope: expectedAccountScope
        )
    }

    func recordDose(
        _ request: MedicationDoseActionRequest,
        expectedAccountScope: String
    ) async throws -> MedicationDoseEvent {
        try await api.postAccountBound(
            "/api/medications/trust/dose-events",
            body: request,
            expectedAccountScope: expectedAccountScope
        )
    }

    func createReaction(
        _ request: MedicationReactionCreateRequest,
        expectedAccountScope: String
    ) async throws -> MedicationReaction {
        try await api.postAccountBound(
            "/api/medications/trust/reactions",
            body: request,
            expectedAccountScope: expectedAccountScope
        )
    }

    func correctReaction(
        reactionKey: String,
        request: MedicationReactionCorrectRequest,
        expectedAccountScope: String
    ) async throws -> MedicationReaction {
        try await api.postAccountBound(
            "/api/medications/trust/reactions/\(reactionKey)/correct",
            body: request,
            expectedAccountScope: expectedAccountScope
        )
    }

    func retractReaction(
        reactionKey: String,
        request: MedicationReactionRetractRequest,
        expectedAccountScope: String
    ) async throws -> MedicationReaction {
        try await api.postAccountBound(
            "/api/medications/trust/reactions/\(reactionKey)/retract",
            body: request,
            expectedAccountScope: expectedAccountScope
        )
    }
}
