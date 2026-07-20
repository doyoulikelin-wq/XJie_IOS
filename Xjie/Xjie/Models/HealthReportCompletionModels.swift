import Foundation

// MARK: - Ordered report upload

/// One user-selected source asset. The array order is the report page order and
/// must be preserved all the way to the server-owned asset manifest.
struct HealthReportUploadAssetInput: Equatable, Sendable {
    let data: Data
    let fileName: String
}

enum HealthReportUploadMediaKind: String, Codable, Sendable {
    case camera
    case photoLibrary = "photo_library"
    case pdf
    case csv
    case legacy
}

struct HealthReportUploadSessionRequest: Encodable, Equatable, Sendable {
    let subject_user_id: Int
    let client_request_id: String
    let media_kind: HealthReportUploadMediaKind
    let expected_page_count: Int?
}

struct HealthReportUploadSession: Decodable, Equatable, Sendable {
    let asset_set_id: Int
    let subject_user_id: Int
    let status: String
    let media_kind: String
    let expected_page_count: Int?
    let received_asset_count: Int
    let aggregate_sha256: String?
}

struct HealthReportUploadedAsset: Decodable, Equatable, Sendable {
    let asset_id: Int
    let asset_index: Int
    let client_asset_id: String
    let filename: String
    let mime_type: String
    let byte_size: Int
    let sha256: String
}

struct HealthReportSealRequest: Encodable, Equatable, Sendable {
    let subject_user_id: Int
    let report_type: String
    let title: String
    let hospital: String?
    let report_date: String?
}

struct HealthReportSealResult: Decodable, Equatable, Sendable {
    let asset_set_id: Int
    let status: String
    let workflow_id: Int?
    let duplicate: Bool
    let failure_code: String?
    let recovery_action: String?
    let problem_asset_indices: [Int]?
    let missing_page_indices: [Int]?

    init(
        asset_set_id: Int,
        status: String,
        workflow_id: Int?,
        duplicate: Bool,
        failure_code: String?,
        recovery_action: String? = nil,
        problem_asset_indices: [Int]? = nil,
        missing_page_indices: [Int]? = nil
    ) {
        self.asset_set_id = asset_set_id
        self.status = status
        self.workflow_id = workflow_id
        self.duplicate = duplicate
        self.failure_code = failure_code
        self.recovery_action = recovery_action
        self.problem_asset_indices = problem_asset_indices
        self.missing_page_indices = missing_page_indices
    }
}

struct HealthReportRecoveredAsset: Decodable, Equatable, Sendable {
    let asset_id: Int
    let asset_index: Int
    let client_asset_id: String
    let filename: String
    let mime_type: String
    let byte_size: Int
    let sha256: String
    let asset_set_id: Int
    let session_status: String
    let received_asset_count: Int
}

// MARK: - Server-owned state and action

struct HealthReportPrimaryAction: Decodable, Equatable, Sendable {
    let code: String
    let enabled: Bool
    let pending_count: Int
    let target_workflow_id: Int?
}

struct HealthReportRuntime: Decodable, Equatable, Sendable {
    let workflow_id: Int
    let subject_user_id: Int
    let workflow_version: Int?
    let state: String
    let workflow_status: String
    let failure_code: String?
    let primary_action: HealthReportPrimaryAction?

    var route: HealthReportWorkflowRoute {
        HealthReportWorkflowRoute(
            workflowID: workflow_id,
            subjectUserID: subject_user_id,
            status: HealthReportWorkflowStatus(rawValue: workflow_status),
            isDuplicate: state == "awaiting_duplicate_decision" || state == "duplicate_reused"
        )
    }
}

struct HealthReportDuplicateDecisionRequest: Encodable, Equatable, Sendable {
    let subject_user_id: Int
    let workflow_version: Int
    let client_event_id: String
    let action: String
}

struct HealthReportDuplicateDecisionResult: Decodable, Equatable, Sendable {
    let workflow_id: Int
    let matched_workflow_id: Int
    let decision_status: String
    let similarity: Double
    let workflow_version: Int
}

// MARK: - History, trace and score recovery

struct HealthReportHistoryItem: Decodable, Equatable, Identifiable, Sendable {
    let workflow_id: Int
    let status: String
    let report_type: String
    let title: String
    let hospital: String?
    let report_date: String?
    let created_at: String

    var id: Int { workflow_id }
}

struct HealthReportHistoryResponse: Decodable, Equatable, Sendable {
    let items: [HealthReportHistoryItem]
}

/// Canonical history query shared by UI and repository code. Optional text is
/// normalized once so blank filters never become a different server request.
struct HealthReportHistoryQuery: Equatable, Sendable {
    let dateFrom: String?
    let dateTo: String?
    let hospital: String?
    let reportType: String?

    static let empty = HealthReportHistoryQuery()

    init(
        dateFrom: String? = nil,
        dateTo: String? = nil,
        hospital: String? = nil,
        reportType: String? = nil
    ) {
        self.dateFrom = Self.normalized(dateFrom)
        self.dateTo = Self.normalized(dateTo)
        self.hospital = Self.normalized(hospital)
        self.reportType = Self.normalized(reportType)
    }

    var isEmpty: Bool { activeFilterCount == 0 }

    var activeFilterCount: Int {
        [dateFrom, dateTo, hospital, reportType].compactMap { $0 }.count
    }

    private static func normalized(_ value: String?) -> String? {
        let trimmed = value?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return trimmed.isEmpty ? nil : trimmed
    }
}

struct HealthReportTraceAsset: Decodable, Equatable, Identifiable, Sendable {
    let id: Int
    let index: Int
    let filename: String
    let sha256: String
}

struct HealthReportTracePage: Decodable, Equatable, Identifiable, Sendable {
    let id: Int
    let page_index: Int
    let asset_id: Int
}

struct HealthReportTraceLocator: Decodable, Equatable, Sendable {
    let candidate_id: Int
    let page_id: Int
    let role: String
    let bbox: [Double]
}

struct HealthReportTraceCandidate: Decodable, Equatable, Identifiable, Sendable {
    let id: Int
    let name: String
    let status: String
    let version: Int
}

struct HealthReportTraceEvent: Decodable, Equatable, Identifiable, Sendable {
    let id: Int
    let candidate_id: Int
    let event_type: String
}

struct HealthReportTraceObservation: Decodable, Equatable, Identifiable, Sendable {
    let id: Int
    let candidate_id: Int
    let name: String
    let status: String
}

struct HealthReportTraceScoreJob: Decodable, Equatable, Identifiable, Sendable {
    let id: Int
    let status: String
    let input_revision: Int
    let manifest_digest: String
}

struct HealthReportTraceScoreItem: Decodable, Equatable, Identifiable, Sendable {
    let id: Int
    let job_id: Int
    let kind: String
    let status: String
}

struct HealthReportTraceScoreSnapshot: Decodable, Equatable, Identifiable, Sendable {
    let id: Int
    let kind: String
    let algorithm_version: String
    let status: String
}

struct HealthReportTraceFollowUp: Decodable, Equatable, Identifiable, Sendable {
    let id: Int
    let code: String
    let rule_version: String
    let status: String
}

struct HealthReportTraceWorkflow: Decodable, Equatable, Sendable {
    let id: Int
    let status: String
    let version: Int
}

struct HealthReportTrace: Decodable, Equatable, Sendable {
    let workflow: HealthReportTraceWorkflow
    let assets: [HealthReportTraceAsset]
    let pages: [HealthReportTracePage]
    let locators: [HealthReportTraceLocator]
    let candidates: [HealthReportTraceCandidate]
    let confirmation_events: [HealthReportTraceEvent]
    let observations: [HealthReportTraceObservation]
    let score_jobs: [HealthReportTraceScoreJob]
    let score_items: [HealthReportTraceScoreItem]
    let score_snapshots: [HealthReportTraceScoreSnapshot]
    let follow_ups: [HealthReportTraceFollowUp]
}

struct HealthReportScoreRetryResult: Decodable, Equatable, Sendable {
    let job_id: Int
    let status: String
}

enum HealthReportDuplicateChoice: String, Sendable {
    case useExisting = "use_existing"
    case continueNew = "continue_new"
}
