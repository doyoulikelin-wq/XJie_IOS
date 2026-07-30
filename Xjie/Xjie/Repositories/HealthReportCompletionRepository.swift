import Foundation

/// Narrow transport surface for the report trust vertical. Every protected
/// report request is account-bound, including reads, so a late response cannot
/// cross an account switch.
protocol HealthReportCompletionTransport: Sendable {
    func getAccountBound<T: Decodable>(
        _ path: String,
        expectedAccountScope: String,
        timeout: TimeInterval?
    ) async throws -> T
    func postAccountBound<T: Decodable>(
        _ path: String,
        body: Encodable?,
        expectedAccountScope: String,
        timeout: TimeInterval?
    ) async throws -> T
    func putFileAccountBound(
        _ path: String,
        fileData: Data,
        fileName: String,
        mimeType: String,
        formData: [String: String],
        expectedAccountScope: String
    ) async throws -> Data
    func deleteVoidAccountBound(
        _ path: String,
        expectedAccountScope: String
    ) async throws
}

extension HealthReportCompletionTransport {
    func getAccountBound<T: Decodable>(
        _ path: String,
        expectedAccountScope: String
    ) async throws -> T {
        try await getAccountBound(
            path,
            expectedAccountScope: expectedAccountScope,
            timeout: nil
        )
    }

    func postAccountBound<T: Decodable>(
        _ path: String,
        body: Encodable? = nil,
        expectedAccountScope: String
    ) async throws -> T {
        try await postAccountBound(
            path,
            body: body,
            expectedAccountScope: expectedAccountScope,
            timeout: nil
        )
    }
}

private struct HealthReportCompletionAPITransport: HealthReportCompletionTransport {
    let base: any APIServiceProtocol

    func getAccountBound<T: Decodable>(
        _ path: String,
        expectedAccountScope: String,
        timeout: TimeInterval?
    ) async throws -> T {
        try await base.getAccountBound(
            path,
            expectedAccountScope: expectedAccountScope,
            timeout: timeout
        )
    }

    func postAccountBound<T: Decodable>(
        _ path: String,
        body: Encodable?,
        expectedAccountScope: String,
        timeout: TimeInterval?
    ) async throws -> T {
        try await base.postAccountBound(
            path,
            body: body,
            expectedAccountScope: expectedAccountScope,
            timeout: timeout
        )
    }

    func putFileAccountBound(
        _ path: String,
        fileData: Data,
        fileName: String,
        mimeType: String,
        formData: [String: String],
        expectedAccountScope: String
    ) async throws -> Data {
        try await base.putFileAccountBound(
            path,
            fileData: fileData,
            fileName: fileName,
            mimeType: mimeType,
            formData: formData,
            expectedAccountScope: expectedAccountScope
        )
    }

    func deleteVoidAccountBound(
        _ path: String,
        expectedAccountScope: String
    ) async throws {
        try await base.deleteVoidAccountBound(
            path,
            body: nil,
            expectedAccountScope: expectedAccountScope,
            timeout: nil
        )
    }
}

protocol HealthReportCompletionRepositoryProtocol: Sendable {
    func startUploadSession(
        _ request: HealthReportUploadSessionRequest,
        expectedAccountScope: String
    ) async throws -> HealthReportUploadSession
    func uploadAsset(
        assetSetID: Int,
        assetIndex: Int,
        subjectUserID: Int,
        input: HealthReportUploadAssetInput,
        clientAssetID: String,
        expectedAccountScope: String
    ) async throws -> HealthReportUploadedAsset
    func recoverAsset(
        assetSetID: Int,
        assetIndex: Int,
        subjectUserID: Int,
        input: HealthReportUploadAssetInput,
        clientAssetID: String,
        expectedAccountScope: String
    ) async throws -> HealthReportRecoveredAsset
    func sealUploadSession(
        assetSetID: Int,
        request: HealthReportSealRequest,
        expectedAccountScope: String
    ) async throws -> HealthReportSealResult
    func abandonUploadSession(
        assetSetID: Int,
        subjectUserID: Int,
        expectedAccountScope: String
    ) async throws
    func fetchRuntime(
        workflowID: Int,
        subjectUserID: Int,
        expectedAccountScope: String
    ) async throws -> HealthReportRuntime
    func decideDuplicate(
        workflowID: Int,
        request: HealthReportDuplicateDecisionRequest,
        expectedAccountScope: String
    ) async throws -> HealthReportDuplicateDecisionResult
    func fetchHistory(
        subjectUserID: Int,
        dateFrom: String?,
        dateTo: String?,
        hospital: String?,
        reportType: String?,
        expectedAccountScope: String
    ) async throws -> HealthReportHistoryResponse
    func fetchTrace(
        workflowID: Int,
        subjectUserID: Int,
        expectedAccountScope: String
    ) async throws -> HealthReportTrace
    func retryScores(
        workflowID: Int,
        subjectUserID: Int,
        expectedAccountScope: String
    ) async throws -> HealthReportScoreRetryResult
}

actor HealthReportCompletionRepository: HealthReportCompletionRepositoryProtocol {
    private let transport: any HealthReportCompletionTransport

    init(transport: any HealthReportCompletionTransport) {
        self.transport = transport
    }

    init() {
        self.transport = HealthReportCompletionAPITransport(base: APIService.shared)
    }

    func startUploadSession(
        _ request: HealthReportUploadSessionRequest,
        expectedAccountScope: String
    ) async throws -> HealthReportUploadSession {
        try await transport.postAccountBound(
            "/api/health-data/report-upload-sessions",
            body: request,
            expectedAccountScope: expectedAccountScope
        )
    }

    func uploadAsset(
        assetSetID: Int,
        assetIndex: Int,
        subjectUserID: Int,
        input: HealthReportUploadAssetInput,
        clientAssetID: String,
        expectedAccountScope: String
    ) async throws -> HealthReportUploadedAsset {
        let data = try await transport.putFileAccountBound(
            "/api/health-data/report-upload-sessions/\(assetSetID)/assets/\(assetIndex)",
            fileData: input.data,
            fileName: input.fileName,
            mimeType: MIMETypeHelper.mimeType(forFileName: input.fileName),
            formData: [
                "subject_user_id": String(subjectUserID),
                "client_asset_id": clientAssetID,
            ],
            expectedAccountScope: expectedAccountScope
        )
        return try JSONDecoder().decode(HealthReportUploadedAsset.self, from: data)
    }

    func recoverAsset(
        assetSetID: Int,
        assetIndex: Int,
        subjectUserID: Int,
        input: HealthReportUploadAssetInput,
        clientAssetID: String,
        expectedAccountScope: String
    ) async throws -> HealthReportRecoveredAsset {
        let data = try await transport.putFileAccountBound(
            "/api/health-data/report-upload-sessions/\(assetSetID)/assets/\(assetIndex)/replacement",
            fileData: input.data,
            fileName: input.fileName,
            mimeType: MIMETypeHelper.mimeType(forFileName: input.fileName),
            formData: [
                "subject_user_id": String(subjectUserID),
                "client_asset_id": clientAssetID,
            ],
            expectedAccountScope: expectedAccountScope
        )
        return try JSONDecoder().decode(HealthReportRecoveredAsset.self, from: data)
    }

    func sealUploadSession(
        assetSetID: Int,
        request: HealthReportSealRequest,
        expectedAccountScope: String
    ) async throws -> HealthReportSealResult {
        try await transport.postAccountBound(
            "/api/health-data/report-upload-sessions/\(assetSetID)/seal",
            body: request,
            expectedAccountScope: expectedAccountScope
        )
    }

    func abandonUploadSession(
        assetSetID: Int,
        subjectUserID: Int,
        expectedAccountScope: String
    ) async throws {
        let path = URLBuilder.path(
            "/api/health-data/report-upload-sessions/\(assetSetID)",
            queryItems: [
                URLQueryItem(
                    name: "subject_user_id",
                    value: String(subjectUserID)
                )
            ]
        )
        try await transport.deleteVoidAccountBound(
            path,
            expectedAccountScope: expectedAccountScope
        )
    }

    func fetchRuntime(
        workflowID: Int,
        subjectUserID: Int,
        expectedAccountScope: String
    ) async throws -> HealthReportRuntime {
        let path = URLBuilder.path(
            "/api/health-data/report-workflows/\(workflowID)/runtime",
            queryItems: [URLQueryItem(name: "subject_user_id", value: String(subjectUserID))]
        )
        return try await transport.getAccountBound(
            path,
            expectedAccountScope: expectedAccountScope
        )
    }

    func decideDuplicate(
        workflowID: Int,
        request: HealthReportDuplicateDecisionRequest,
        expectedAccountScope: String
    ) async throws -> HealthReportDuplicateDecisionResult {
        try await transport.postAccountBound(
            "/api/health-data/report-workflows/\(workflowID)/duplicate-decision",
            body: request,
            expectedAccountScope: expectedAccountScope
        )
    }

    func fetchHistory(
        subjectUserID: Int,
        dateFrom: String?,
        dateTo: String?,
        hospital: String?,
        reportType: String?,
        expectedAccountScope: String
    ) async throws -> HealthReportHistoryResponse {
        let query = HealthReportHistoryQuery(
            dateFrom: dateFrom,
            dateTo: dateTo,
            hospital: hospital,
            reportType: reportType
        )
        let values: [(String, String?)] = [
            ("subject_user_id", String(subjectUserID)),
            ("date_from", query.dateFrom),
            ("date_to", query.dateTo),
            ("hospital", query.hospital),
            ("report_type", query.reportType),
        ]
        let path = URLBuilder.path(
            "/api/health-data/report-workflows",
            queryItems: values.compactMap { key, value in
                guard let value, !value.isEmpty else { return nil }
                return URLQueryItem(name: key, value: value)
            }
        )
        return try await transport.getAccountBound(
            path,
            expectedAccountScope: expectedAccountScope
        )
    }

    func fetchTrace(
        workflowID: Int,
        subjectUserID: Int,
        expectedAccountScope: String
    ) async throws -> HealthReportTrace {
        let path = URLBuilder.path(
            "/api/health-data/report-workflows/\(workflowID)/trace",
            queryItems: [URLQueryItem(name: "subject_user_id", value: String(subjectUserID))]
        )
        return try await transport.getAccountBound(
            path,
            expectedAccountScope: expectedAccountScope
        )
    }

    func retryScores(
        workflowID: Int,
        subjectUserID: Int,
        expectedAccountScope: String
    ) async throws -> HealthReportScoreRetryResult {
        let path = URLBuilder.path(
            "/api/health-data/report-workflows/\(workflowID)/score-jobs/retry",
            queryItems: [URLQueryItem(name: "subject_user_id", value: String(subjectUserID))]
        )
        return try await transport.postAccountBound(
            path,
            body: nil,
            expectedAccountScope: expectedAccountScope
        )
    }
}
