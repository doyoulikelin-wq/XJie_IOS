import Foundation

/// Server-authoritative health-profile repository.
///
/// GET intentionally omits `subject_user_id`; the authenticated backend returns
/// the canonical subject. Every mutation is versioned, idempotent and bound to
/// the account scope that initiated it.
protocol PatientHistoryRepositoryProtocol: Sendable {
    func fetchProfile() async throws -> HealthProfileTrustResponse
    func fetchLongTermMedicationSummary(
        subjectUserID: Int
    ) async throws -> HealthProfileLongTermMedicationSummary
    func fetchFactRevisions(
        factID: Int,
        subjectUserID: Int,
        afterRevisionID: Int?
    ) async throws -> HealthProfileRevisionList
    func fetchGoalRevisions(
        goalID: Int,
        subjectUserID: Int,
        afterRevisionID: Int?
    ) async throws -> HealthProfileRevisionList
    func reviewCandidate(
        candidateID: Int,
        request: HealthProfileCandidateReviewRequest,
        expectedAccountScope: String
    ) async throws -> HealthProfileTrustResponse
    func upsertFact(
        _ request: HealthProfileFactUpsertRequest,
        expectedAccountScope: String
    ) async throws -> HealthProfileTrustResponse
    func retractFact(
        factID: Int,
        request: HealthProfileFactRetractRequest,
        expectedAccountScope: String
    ) async throws -> HealthProfileTrustResponse
    func createGoal(
        _ request: HealthProfileGoalCreateRequest,
        expectedAccountScope: String
    ) async throws -> HealthProfileTrustResponse
    func updateGoal(
        goalID: Int,
        request: HealthProfileGoalUpdateRequest,
        expectedAccountScope: String
    ) async throws -> HealthProfileTrustResponse
    func updateGoalStatus(
        goalID: Int,
        request: HealthProfileGoalStatusRequest,
        expectedAccountScope: String
    ) async throws -> HealthProfileTrustResponse
}

actor PatientHistoryRepository: PatientHistoryRepositoryProtocol {
    private let api: APIServiceProtocol

    init(api: APIServiceProtocol = APIService.shared) {
        self.api = api
    }

    func fetchProfile() async throws -> HealthProfileTrustResponse {
        try await api.get("/api/health-data/profile-trust")
    }

    func fetchLongTermMedicationSummary(
        subjectUserID: Int
    ) async throws -> HealthProfileLongTermMedicationSummary {
        try await api.get(
            "/api/medications/trust/long-term-summary?subject_user_id=\(subjectUserID)"
        )
    }

    func fetchFactRevisions(
        factID: Int,
        subjectUserID: Int,
        afterRevisionID: Int?
    ) async throws -> HealthProfileRevisionList {
        try await api.get(
            revisionPath(
                "/api/health-data/profile-trust/facts/\(factID)/revisions",
                subjectUserID: subjectUserID,
                afterRevisionID: afterRevisionID
            )
        )
    }

    func fetchGoalRevisions(
        goalID: Int,
        subjectUserID: Int,
        afterRevisionID: Int?
    ) async throws -> HealthProfileRevisionList {
        try await api.get(
            revisionPath(
                "/api/health-data/profile-trust/goals/\(goalID)/revisions",
                subjectUserID: subjectUserID,
                afterRevisionID: afterRevisionID
            )
        )
    }

    func reviewCandidate(
        candidateID: Int,
        request: HealthProfileCandidateReviewRequest,
        expectedAccountScope: String
    ) async throws -> HealthProfileTrustResponse {
        try await api.postAccountBound(
            "/api/health-data/profile-trust/candidates/\(candidateID)/review",
            body: request,
            expectedAccountScope: expectedAccountScope
        )
    }

    func upsertFact(
        _ request: HealthProfileFactUpsertRequest,
        expectedAccountScope: String
    ) async throws -> HealthProfileTrustResponse {
        try await api.postAccountBound(
            "/api/health-data/profile-trust/facts",
            body: request,
            expectedAccountScope: expectedAccountScope
        )
    }

    func retractFact(
        factID: Int,
        request: HealthProfileFactRetractRequest,
        expectedAccountScope: String
    ) async throws -> HealthProfileTrustResponse {
        try await api.postAccountBound(
            "/api/health-data/profile-trust/facts/\(factID)/retract",
            body: request,
            expectedAccountScope: expectedAccountScope
        )
    }

    func createGoal(
        _ request: HealthProfileGoalCreateRequest,
        expectedAccountScope: String
    ) async throws -> HealthProfileTrustResponse {
        try await api.postAccountBound(
            "/api/health-data/profile-trust/goals",
            body: request,
            expectedAccountScope: expectedAccountScope
        )
    }

    func updateGoal(
        goalID: Int,
        request: HealthProfileGoalUpdateRequest,
        expectedAccountScope: String
    ) async throws -> HealthProfileTrustResponse {
        try await api.patchAccountBound(
            "/api/health-data/profile-trust/goals/\(goalID)",
            body: request,
            expectedAccountScope: expectedAccountScope
        )
    }

    func updateGoalStatus(
        goalID: Int,
        request: HealthProfileGoalStatusRequest,
        expectedAccountScope: String
    ) async throws -> HealthProfileTrustResponse {
        try await api.postAccountBound(
            "/api/health-data/profile-trust/goals/\(goalID)/status",
            body: request,
            expectedAccountScope: expectedAccountScope
        )
    }

    private func revisionPath(
        _ base: String,
        subjectUserID: Int,
        afterRevisionID: Int?
    ) -> String {
        var query = ["subject_user_id=\(subjectUserID)", "limit=50"]
        if let afterRevisionID {
            query.append("after_revision_id=\(afterRevisionID)")
        }
        return "\(base)?\(query.joined(separator: "&"))"
    }
}
