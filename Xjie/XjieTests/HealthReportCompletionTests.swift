import Foundation
import UIKit
import XCTest
@testable import Xjie

@MainActor
final class HealthReportCompletionTests: XCTestCase {
    func testOriginalFilePayloadAcceptsImageAndPDFAndRejectsCorruptData() throws {
        let imageData = UIGraphicsImageRenderer(size: CGSize(width: 8, height: 8)).pngData { context in
            UIColor.systemTeal.setFill()
            context.fill(CGRect(x: 0, y: 0, width: 8, height: 8))
        }
        guard case .image = OriginalFilePayload.decode(imageData) else {
            return XCTFail("有效图片原件应被识别")
        }

        let pdfData = UIGraphicsPDFRenderer(bounds: CGRect(x: 0, y: 0, width: 100, height: 140)).pdfData { context in
            context.beginPage()
            ("报告原件" as NSString).draw(at: CGPoint(x: 10, y: 10), withAttributes: nil)
        }
        guard case .pdf(let document) = OriginalFilePayload.decode(pdfData) else {
            return XCTFail("有效 PDF 原件应被识别")
        }
        XCTAssertEqual(document.pageCount, 1)

        guard case .unsupported = OriginalFilePayload.decode(Data("broken-file".utf8)) else {
            return XCTFail("损坏原件不得被误识别为图片或 PDF")
        }
    }

    func testRuntimeUsesServerOwnedStateAndPrimaryAction() throws {
        let data = Data(
            #"{"workflow_id":42,"subject_user_id":7,"workflow_version":3,"state":"awaiting_duplicate_decision","workflow_status":"awaiting_confirmation","failure_code":null,"primary_action":{"code":"resolve_duplicate","enabled":true,"pending_count":1,"target_workflow_id":11}}"#.utf8
        )

        let runtime = try JSONDecoder().decode(HealthReportRuntime.self, from: data)

        XCTAssertEqual(runtime.state, "awaiting_duplicate_decision")
        XCTAssertEqual(runtime.workflow_version, 3)
        XCTAssertEqual(runtime.primary_action?.code, "resolve_duplicate")
        XCTAssertEqual(runtime.primary_action?.target_workflow_id, 11)
        XCTAssertEqual(runtime.route.workflowID, 42)
        XCTAssertEqual(runtime.route.subjectUserID, 7)
        XCTAssertEqual(runtime.route.status, .awaitingConfirmation)
        XCTAssertTrue(runtime.route.isDuplicate)
    }

    func testUploadSessionPreservesExpectedOrderedAssetCount() throws {
        let data = Data(
            #"{"asset_set_id":91,"subject_user_id":7,"status":"open","media_kind":"photo_library","expected_page_count":3,"received_asset_count":0,"aggregate_sha256":null}"#.utf8
        )

        let session = try JSONDecoder().decode(HealthReportUploadSession.self, from: data)

        XCTAssertEqual(session.expected_page_count, 3)
        XCTAssertEqual(session.received_asset_count, 0)
        XCTAssertEqual(session.media_kind, HealthReportUploadMediaKind.photoLibrary.rawValue)
    }

    func testTraceDecodesOriginalAssetPageAndLocatorChain() async throws {
        let historyData = Data(#"{"items":[{"workflow_id":42,"status":"completed","report_type":"lab","title":"血常规","hospital":"协和医院","report_date":"2026-07-15","created_at":"2026-07-15T08:00:00Z"},{"workflow_id":41,"status":"server_future","report_type":"exam","title":"体检报告","hospital":null,"report_date":null,"created_at":"2026-07-14T08:00:00Z"}]}"#.utf8)
        let traceData = Data(
            #"{"workflow":{"id":42,"status":"completed","version":3},"assets":[{"id":5,"index":1,"filename":"page-1.jpg","sha256":"abc"}],"pages":[{"id":6,"page_index":1,"asset_id":5}],"locators":[{"candidate_id":8,"page_id":6,"role":"value","bbox":[0.1,0.2,0.3,0.4]}],"candidates":[{"id":8,"name":"血红蛋白","status":"confirmed","version":2}],"confirmation_events":[{"id":9,"candidate_id":8,"event_type":"correct"},{"id":11,"candidate_id":8,"event_type":"confirm"}],"observations":[{"id":10,"candidate_id":8,"name":"血红蛋白","status":"active"}],"score_jobs":[{"id":12,"status":"completed","input_revision":4,"manifest_digest":"digest-12"}],"score_items":[{"id":13,"job_id":12,"kind":"stress","status":"completed"}],"score_snapshots":[{"id":14,"kind":"stress","algorithm_version":"2026.07","status":"completed"}],"follow_ups":[{"id":15,"code":"repeat_lab","rule_version":"v2","status":"active"}]}"#.utf8
        )
        let transport = HealthReportHistoryTransportSpy(
            historyData: historyData,
            traceData: traceData
        )
        let repository = HealthReportCompletionRepository(transport: transport)

        let history = try await repository.fetchHistory(
            subjectUserID: 7,
            dateFrom: " 2026-07-01 ",
            dateTo: "2026-07-31\n",
            hospital: " 协和医院 ",
            reportType: " lab "
        )
        let trace = try await repository.fetchTrace(workflowID: 42, subjectUserID: 7)
        let paths = await transport.snapshot()

        XCTAssertEqual(paths.count, 2)
        XCTAssertEqual(history.items.map(\.workflow_id), [42, 41], "客户端必须保留服务器顺序")
        XCTAssertEqual(HealthReportWorkflowStatus(rawValue: history.items[1].status), .unknown("server_future"))
        let historyPath = try XCTUnwrap(paths.first)
        let historyComponents = try XCTUnwrap(
            URLComponents(string: "https://report.test\(historyPath)")
        )
        let query = Dictionary(uniqueKeysWithValues: (historyComponents.queryItems ?? []).compactMap {
            item in item.value.map { (item.name, $0) }
        })
        XCTAssertEqual(query, [
            "subject_user_id": "7",
            "date_from": "2026-07-01",
            "date_to": "2026-07-31",
            "hospital": "协和医院",
            "report_type": "lab",
        ])
        XCTAssertEqual(paths.last, "/api/health-data/report-workflows/42/trace?subject_user_id=7")
        XCTAssertEqual(trace.assets.first?.id, 5)
        XCTAssertEqual(trace.pages.first?.asset_id, 5)
        XCTAssertEqual(trace.locators.first?.candidate_id, 8)
        XCTAssertEqual(trace.observations.first?.candidate_id, 8)
        XCTAssertEqual(trace.confirmation_events.map(\.event_type), ["correct", "confirm"])
        XCTAssertEqual(trace.score_jobs.first?.manifest_digest, "digest-12")
        XCTAssertEqual(trace.score_items.first?.job_id, 12)
        XCTAssertEqual(trace.score_snapshots.first?.algorithm_version, "2026.07")
        XCTAssertEqual(trace.follow_ups.first?.rule_version, "v2")

        XCTAssertEqual(HealthReportHistoryQuery(hospital: " \n "), .empty)
        XCTAssertEqual(
            HealthReportHistoryQuery(dateFrom: "2026-07-01", hospital: "协和医院").activeFilterCount,
            2
        )
    }

    func testMultiPhotoUploadCreatesOneOrderedAssetSetAndOneWorkflow() async throws {
        let runtime = makeRuntime(
            workflowID: 42,
            state: "awaiting_confirmation",
            status: "awaiting_confirmation",
            action: HealthReportPrimaryAction(
                code: "review_fields",
                enabled: true,
                pending_count: 3,
                target_workflow_id: nil
            )
        )
        let repository = HealthReportCompletionRepositorySpy(
            sealResult: HealthReportSealResult(
                asset_set_id: 91,
                status: "attached",
                workflow_id: 42,
                duplicate: false,
                failure_code: nil
            ),
            runtimes: [runtime]
        )
        let scope = HealthReportTestAccountScope("account-a")
        let viewModel = HealthReportCompletionViewModel(
            repository: repository,
            currentAccountScope: { scope.value },
            makeID: { "request-1" },
            pollDelay: { throw CancellationError() }
        )
        let files = (1...3).map {
            HealthReportUploadAssetInput(
                data: Data("page-\($0)".utf8),
                fileName: "page-\($0).jpg"
            )
        }

        let route = await viewModel.uploadReport(
            files: files,
            source: "相册",
            subjectUserID: 7,
            accountScope: "account-a"
        )
        let snapshot = await repository.snapshot()

        XCTAssertEqual(snapshot.sessionRequests.count, 1)
        XCTAssertEqual(snapshot.sessionRequests.first?.expected_page_count, 3)
        XCTAssertEqual(
            snapshot.sessionRequests.first?.media_kind,
            .photoLibrary
        )
        XCTAssertEqual(snapshot.assetIndexes, [1, 2, 3])
        XCTAssertEqual(snapshot.assetNames, ["page-1.jpg", "page-2.jpg", "page-3.jpg"])
        XCTAssertEqual(snapshot.sealRequests.count, 1)
        XCTAssertEqual(snapshot.sealRequests.first?.title, "page-1 等 3 页")
        XCTAssertEqual(route?.workflowID, 42)
        XCTAssertEqual(route?.status, .awaitingConfirmation)
        XCTAssertEqual(viewModel.uploadProgress, 1)
        XCTAssertEqual(viewModel.infoMessage, "报告字段等待复核。")
    }

    func testQualityFailureKeepsAssetSetRecoverableAndDoesNotInventWorkflow() async {
        let repository = HealthReportCompletionRepositorySpy(
            sealResult: HealthReportSealResult(
                asset_set_id: 92,
                status: "rejected",
                workflow_id: nil,
                duplicate: false,
                failure_code: "missing_page"
            ),
            runtimes: []
        )
        let scope = HealthReportTestAccountScope("account-a")
        let viewModel = HealthReportCompletionViewModel(
            repository: repository,
            currentAccountScope: { scope.value },
            makeID: { "request-2" },
            pollDelay: { throw CancellationError() }
        )

        let route = await viewModel.uploadReport(
            files: [
                HealthReportUploadAssetInput(data: Data("page".utf8), fileName: "page.jpg")
            ],
            source: "相机",
            subjectUserID: 7,
            accountScope: "account-a"
        )
        let snapshot = await repository.snapshot()

        XCTAssertNil(route)
        XCTAssertEqual(snapshot.runtimeWorkflowIDs, [])
        XCTAssertEqual(viewModel.uploadRecovery?.assetSetID, 92)
        XCTAssertEqual(viewModel.uploadRecovery?.actionCode, "upload_missing_pages")
        XCTAssertEqual(viewModel.errorMessage, "报告页码不完整，请补齐缺失页后再提交。")
    }

    func testDuplicateDecisionSubmitsServerWorkflowVersionWithoutGuessing() async throws {
        let duplicateRuntime = makeRuntime(
            workflowID: 42,
            version: 4,
            state: "awaiting_duplicate_decision",
            status: "awaiting_confirmation",
            action: HealthReportPrimaryAction(
                code: "resolve_duplicate",
                enabled: true,
                pending_count: 1,
                target_workflow_id: 11
            )
        )
        let existingRuntime = makeRuntime(
            workflowID: 11,
            version: 8,
            state: "completed",
            status: "completed",
            action: HealthReportPrimaryAction(
                code: "view_interpretation",
                enabled: true,
                pending_count: 0,
                target_workflow_id: nil
            )
        )
        let repository = HealthReportCompletionRepositorySpy(
            sealResult: HealthReportSealResult(
                asset_set_id: 93,
                status: "attached",
                workflow_id: 42,
                duplicate: false,
                failure_code: nil
            ),
            runtimes: [duplicateRuntime, existingRuntime],
            duplicateResult: HealthReportDuplicateDecisionResult(
                workflow_id: 42,
                matched_workflow_id: 11,
                decision_status: "use_existing",
                similarity: 0.97,
                workflow_version: 5
            )
        )
        let scope = HealthReportTestAccountScope("account-a")
        let ids = HealthReportTestIDSequence(["request-3", "decision-3"])
        let viewModel = HealthReportCompletionViewModel(
            repository: repository,
            currentAccountScope: { scope.value },
            makeID: { ids.next() },
            pollDelay: { throw CancellationError() }
        )

        _ = await viewModel.uploadReport(
            files: [
                HealthReportUploadAssetInput(data: Data("page".utf8), fileName: "page.jpg")
            ],
            source: "相册",
            subjectUserID: 7,
            accountScope: "account-a"
        )
        let prompt = try XCTUnwrap(viewModel.duplicatePrompt)
        await viewModel.decideDuplicate(.useExisting, prompt: prompt)
        let snapshot = await repository.snapshot()

        XCTAssertEqual(snapshot.duplicateRequests.count, 1)
        XCTAssertEqual(snapshot.duplicateRequests.first?.workflow_version, 4)
        XCTAssertEqual(snapshot.duplicateRequests.first?.client_event_id, "decision-3")
        XCTAssertEqual(snapshot.duplicateRequests.first?.action, "use_existing")
        XCTAssertEqual(snapshot.runtimeWorkflowIDs, [42, 11])
        XCTAssertEqual(viewModel.activeReportWorkflow?.workflowID, 11)
        XCTAssertEqual(viewModel.activeReportWorkflow?.status, .completed)
    }

    func testMissingPageRecoveryUploadsOnlyRequestedIndexAndResealsSameAssetSet() async {
        let repository = HealthReportCompletionRepositorySpy(
            sealResults: [
                HealthReportSealResult(
                    asset_set_id: 94,
                    status: "rejected",
                    workflow_id: nil,
                    duplicate: false,
                    failure_code: "missing_page",
                    recovery_action: "upload_missing_pages",
                    problem_asset_indices: [],
                    missing_page_indices: [2]
                ),
                HealthReportSealResult(
                    asset_set_id: 94,
                    status: "attached",
                    workflow_id: 44,
                    duplicate: false,
                    failure_code: nil
                ),
            ],
            runtimes: [
                makeRuntime(
                    workflowID: 44,
                    state: "awaiting_confirmation",
                    status: "awaiting_confirmation",
                    action: HealthReportPrimaryAction(
                        code: "review_fields",
                        enabled: true,
                        pending_count: 1,
                        target_workflow_id: nil
                    )
                )
            ]
        )
        let scope = HealthReportTestAccountScope("account-a")
        let viewModel = HealthReportCompletionViewModel(
            repository: repository,
            currentAccountScope: { scope.value },
            makeID: { "request-4" },
            pollDelay: { throw CancellationError() }
        )

        _ = await viewModel.uploadReport(
            files: [
                HealthReportUploadAssetInput(data: Data("page-1".utf8), fileName: "page-1.jpg")
            ],
            source: "相册",
            subjectUserID: 7,
            accountScope: "account-a"
        )
        XCTAssertEqual(viewModel.uploadRecovery?.nextAssetIndex, 2)

        let route = await viewModel.recoverReportAsset(
            input: HealthReportUploadAssetInput(
                data: Data("page-2".utf8),
                fileName: "page-2.jpg"
            ),
            assetIndex: 2
        )
        let snapshot = await repository.snapshot()

        XCTAssertEqual(snapshot.recoveredAssetIndexes, [2])
        XCTAssertEqual(snapshot.recoveredAssetSetIDs, [94])
        XCTAssertEqual(snapshot.sealRequests.count, 2)
        XCTAssertEqual(route?.workflowID, 44)
        XCTAssertNil(viewModel.uploadRecovery)
    }

    func testProblemPageRecoveryUsesReplacementEndpointAndAccountBoundForm() async throws {
        let transport = HealthReportCompletionTransportSpy()
        let repository = HealthReportCompletionRepository(transport: transport)
        let input = HealthReportUploadAssetInput(
            data: Data("clear-page".utf8),
            fileName: "page-2.jpg"
        )

        let recovered = try await repository.recoverAsset(
            assetSetID: 94,
            assetIndex: 2,
            subjectUserID: 7,
            input: input,
            clientAssetID: "request-4-recovery-2",
            expectedAccountScope: "account-a"
        )
        let recordedRequest = await transport.snapshot()
        let request = try XCTUnwrap(recordedRequest)

        XCTAssertEqual(
            request.path,
            "/api/health-data/report-upload-sessions/94/assets/2/replacement"
        )
        XCTAssertEqual(request.fileData, input.data)
        XCTAssertEqual(request.fileName, "page-2.jpg")
        XCTAssertEqual(request.mimeType, "image/jpeg")
        XCTAssertEqual(request.formData["subject_user_id"], "7")
        XCTAssertEqual(request.formData["client_asset_id"], "request-4-recovery-2")
        XCTAssertEqual(request.expectedAccountScope, "account-a")
        XCTAssertEqual(recovered.asset_set_id, 94)
        XCTAssertEqual(recovered.asset_index, 2)
    }

    func testRecoveryRejectsAccountSwitchBeforeReseal() async {
        let repository = HealthReportCompletionRepositorySpy(
            sealResult: HealthReportSealResult(
                asset_set_id: 96,
                status: "rejected",
                workflow_id: nil,
                duplicate: false,
                failure_code: "blur",
                recovery_action: "replace_problem_pages",
                problem_asset_indices: [1],
                missing_page_indices: []
            ),
            runtimes: []
        )
        let scope = HealthReportTestAccountScope("account-a")
        let viewModel = HealthReportCompletionViewModel(
            repository: repository,
            currentAccountScope: { scope.value },
            makeID: { "request-6" },
            pollDelay: { throw CancellationError() }
        )

        _ = await viewModel.uploadReport(
            files: [HealthReportUploadAssetInput(data: Data("blur".utf8), fileName: "page.jpg")],
            source: "相册",
            subjectUserID: 7,
            accountScope: "account-a"
        )
        scope.value = "account-b"
        let route = await viewModel.recoverReportAsset(
            input: HealthReportUploadAssetInput(
                data: Data("clear".utf8),
                fileName: "page.jpg"
            ),
            assetIndex: 1
        )
        let snapshot = await repository.snapshot()

        XCTAssertNil(route)
        XCTAssertEqual(snapshot.recoveredAssetIndexes, [])
        XCTAssertEqual(snapshot.sealRequests.count, 1)
        XCTAssertEqual(viewModel.errorMessage, "报告恢复任务已变化，请重新上传整份报告。")
    }

    func testRepeatedRecoveryForSamePageReusesStableClientAssetID() async {
        let rejected = HealthReportSealResult(
            asset_set_id: 95,
            status: "rejected",
            workflow_id: nil,
            duplicate: false,
            failure_code: "blur",
            recovery_action: "replace_problem_pages",
            problem_asset_indices: [1],
            missing_page_indices: []
        )
        let repository = HealthReportCompletionRepositorySpy(
            sealResults: [
                rejected,
                rejected,
                HealthReportSealResult(
                    asset_set_id: 95,
                    status: "attached",
                    workflow_id: 45,
                    duplicate: false,
                    failure_code: nil
                ),
            ],
            runtimes: [
                makeRuntime(
                    workflowID: 45,
                    state: "awaiting_confirmation",
                    status: "awaiting_confirmation",
                    action: HealthReportPrimaryAction(
                        code: "review_fields",
                        enabled: true,
                        pending_count: 1,
                        target_workflow_id: nil
                    )
                )
            ]
        )
        let scope = HealthReportTestAccountScope("account-a")
        let viewModel = HealthReportCompletionViewModel(
            repository: repository,
            currentAccountScope: { scope.value },
            makeID: { "request-5" },
            pollDelay: { throw CancellationError() }
        )
        let replacement = HealthReportUploadAssetInput(
            data: Data("clearer-page-1".utf8),
            fileName: "page-1.jpg"
        )

        _ = await viewModel.uploadReport(
            files: [HealthReportUploadAssetInput(data: Data("blur".utf8), fileName: "page-1.jpg")],
            source: "相册",
            subjectUserID: 7,
            accountScope: "account-a"
        )
        _ = await viewModel.recoverReportAsset(input: replacement, assetIndex: 1)
        let route = await viewModel.recoverReportAsset(input: replacement, assetIndex: 1)
        let snapshot = await repository.snapshot()

        XCTAssertEqual(
            snapshot.recoveredClientAssetIDs,
            ["request-5-recovery-1", "request-5-recovery-1"]
        )
        XCTAssertEqual(snapshot.recoveredAssetSetIDs, [95, 95])
        XCTAssertEqual(snapshot.sealRequests.count, 3)
        XCTAssertEqual(route?.workflowID, 45)
    }

    private func makeRuntime(
        workflowID: Int,
        version: Int = 3,
        state: String,
        status: String,
        action: HealthReportPrimaryAction
    ) -> HealthReportRuntime {
        HealthReportRuntime(
            workflow_id: workflowID,
            subject_user_id: 7,
            workflow_version: version,
            state: state,
            workflow_status: status,
            failure_code: nil,
            primary_action: action
        )
    }
}

private actor HealthReportCompletionTransportSpy: HealthReportCompletionTransport {
    struct PutRequest: Sendable {
        let path: String
        let fileData: Data
        let fileName: String
        let mimeType: String
        let formData: [String: String]
        let expectedAccountScope: String
    }

    private var putRequest: PutRequest?

    func get<T: Decodable>(_ path: String, timeout: TimeInterval?) async throws -> T {
        throw HealthReportCompletionTestError.unexpectedCall
    }

    func postAccountBound<T: Decodable>(
        _ path: String,
        body: Encodable?,
        expectedAccountScope: String,
        timeout: TimeInterval?
    ) async throws -> T {
        throw HealthReportCompletionTestError.unexpectedCall
    }

    func putFileAccountBound(
        _ path: String,
        fileData: Data,
        fileName: String,
        mimeType: String,
        formData: [String: String],
        expectedAccountScope: String
    ) async throws -> Data {
        putRequest = PutRequest(
            path: path,
            fileData: fileData,
            fileName: fileName,
            mimeType: mimeType,
            formData: formData,
            expectedAccountScope: expectedAccountScope
        )
        return Data(
            #"{"asset_id":102,"asset_index":2,"client_asset_id":"request-4-recovery-2","filename":"page-2.jpg","mime_type":"image/jpeg","byte_size":10,"sha256":"replacement-2","asset_set_id":94,"session_status":"open","received_asset_count":2}"#.utf8
        )
    }

    func snapshot() -> PutRequest? {
        putRequest
    }
}

private final class HealthReportTestIDSequence: @unchecked Sendable {
    private let lock = NSLock()
    private var values: [String]

    init(_ values: [String]) {
        self.values = values
    }

    func next() -> String {
        lock.lock()
        defer { lock.unlock() }
        precondition(!values.isEmpty)
        return values.removeFirst()
    }
}

@MainActor
private final class HealthReportTestAccountScope {
    var value: String?

    init(_ value: String?) {
        self.value = value
    }
}

private actor HealthReportCompletionRepositorySpy: HealthReportCompletionRepositoryProtocol {
    struct Snapshot: Sendable {
        let sessionRequests: [HealthReportUploadSessionRequest]
        let assetIndexes: [Int]
        let assetNames: [String]
        let sealRequests: [HealthReportSealRequest]
        let runtimeWorkflowIDs: [Int]
        let duplicateRequests: [HealthReportDuplicateDecisionRequest]
        let recoveredAssetIndexes: [Int]
        let recoveredAssetSetIDs: [Int]
        let recoveredClientAssetIDs: [String]
    }

    private var sealResults: [HealthReportSealResult]
    private var runtimes: [HealthReportRuntime]
    private let duplicateResult: HealthReportDuplicateDecisionResult
    private var sessionRequests: [HealthReportUploadSessionRequest] = []
    private var assetIndexes: [Int] = []
    private var assetNames: [String] = []
    private var sealRequests: [HealthReportSealRequest] = []
    private var runtimeWorkflowIDs: [Int] = []
    private var duplicateRequests: [HealthReportDuplicateDecisionRequest] = []
    private var recoveredAssetIndexes: [Int] = []
    private var recoveredAssetSetIDs: [Int] = []
    private var recoveredClientAssetIDs: [String] = []

    init(
        sealResult: HealthReportSealResult,
        runtimes: [HealthReportRuntime],
        duplicateResult: HealthReportDuplicateDecisionResult = HealthReportDuplicateDecisionResult(
            workflow_id: 1,
            matched_workflow_id: 1,
            decision_status: "continue_new",
            similarity: 0,
            workflow_version: 1
        )
    ) {
        self.sealResults = [sealResult]
        self.runtimes = runtimes
        self.duplicateResult = duplicateResult
    }

    init(
        sealResults: [HealthReportSealResult],
        runtimes: [HealthReportRuntime],
        duplicateResult: HealthReportDuplicateDecisionResult = HealthReportDuplicateDecisionResult(
            workflow_id: 1,
            matched_workflow_id: 1,
            decision_status: "continue_new",
            similarity: 0,
            workflow_version: 1
        )
    ) {
        precondition(!sealResults.isEmpty)
        self.sealResults = sealResults
        self.runtimes = runtimes
        self.duplicateResult = duplicateResult
    }

    func startUploadSession(
        _ request: HealthReportUploadSessionRequest,
        expectedAccountScope: String
    ) async throws -> HealthReportUploadSession {
        sessionRequests.append(request)
        return HealthReportUploadSession(
            asset_set_id: sealResults[0].asset_set_id,
            subject_user_id: request.subject_user_id,
            status: "open",
            media_kind: request.media_kind.rawValue,
            expected_page_count: request.expected_page_count,
            received_asset_count: 0,
            aggregate_sha256: nil
        )
    }

    func recoverAsset(
        assetSetID: Int,
        assetIndex: Int,
        subjectUserID: Int,
        input: HealthReportUploadAssetInput,
        clientAssetID: String,
        expectedAccountScope: String
    ) async throws -> HealthReportRecoveredAsset {
        recoveredAssetSetIDs.append(assetSetID)
        recoveredAssetIndexes.append(assetIndex)
        recoveredClientAssetIDs.append(clientAssetID)
        return HealthReportRecoveredAsset(
            asset_id: 100 + assetIndex,
            asset_index: assetIndex,
            client_asset_id: clientAssetID,
            filename: input.fileName,
            mime_type: "image/jpeg",
            byte_size: input.data.count,
            sha256: "replacement-\(assetIndex)",
            asset_set_id: assetSetID,
            session_status: "open",
            received_asset_count: assetIndex
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
        assetIndexes.append(assetIndex)
        assetNames.append(input.fileName)
        return HealthReportUploadedAsset(
            asset_id: assetIndex,
            asset_index: assetIndex,
            client_asset_id: clientAssetID,
            filename: input.fileName,
            mime_type: "image/jpeg",
            byte_size: input.data.count,
            sha256: "sha-\(assetIndex)"
        )
    }

    func sealUploadSession(
        assetSetID: Int,
        request: HealthReportSealRequest,
        expectedAccountScope: String
    ) async throws -> HealthReportSealResult {
        sealRequests.append(request)
        guard !sealResults.isEmpty else {
            throw HealthReportCompletionTestError.unexpectedCall
        }
        if sealResults.count == 1 {
            return sealResults[0]
        }
        return sealResults.removeFirst()
    }

    func fetchRuntime(workflowID: Int, subjectUserID: Int) async throws -> HealthReportRuntime {
        runtimeWorkflowIDs.append(workflowID)
        guard !runtimes.isEmpty else { throw HealthReportCompletionTestError.unexpectedCall }
        return runtimes.removeFirst()
    }

    func decideDuplicate(
        workflowID: Int,
        request: HealthReportDuplicateDecisionRequest,
        expectedAccountScope: String
    ) async throws -> HealthReportDuplicateDecisionResult {
        duplicateRequests.append(request)
        return duplicateResult
    }

    func fetchHistory(
        subjectUserID: Int,
        dateFrom: String?,
        dateTo: String?,
        hospital: String?,
        reportType: String?
    ) async throws -> HealthReportHistoryResponse {
        HealthReportHistoryResponse(items: [])
    }

    func fetchTrace(workflowID: Int, subjectUserID: Int) async throws -> HealthReportTrace {
        throw HealthReportCompletionTestError.unexpectedCall
    }

    func retryScores(
        workflowID: Int,
        subjectUserID: Int,
        expectedAccountScope: String
    ) async throws -> HealthReportScoreRetryResult {
        throw HealthReportCompletionTestError.unexpectedCall
    }

    func snapshot() -> Snapshot {
        Snapshot(
            sessionRequests: sessionRequests,
            assetIndexes: assetIndexes,
            assetNames: assetNames,
            sealRequests: sealRequests,
            runtimeWorkflowIDs: runtimeWorkflowIDs,
            duplicateRequests: duplicateRequests,
            recoveredAssetIndexes: recoveredAssetIndexes,
            recoveredAssetSetIDs: recoveredAssetSetIDs,
            recoveredClientAssetIDs: recoveredClientAssetIDs
        )
    }
}

private actor HealthReportHistoryTransportSpy: HealthReportCompletionTransport {
    private let historyData: Data
    private let traceData: Data
    private var paths: [String] = []

    init(historyData: Data, traceData: Data) {
        self.historyData = historyData
        self.traceData = traceData
    }

    func get<T: Decodable>(_ path: String, timeout: TimeInterval?) async throws -> T {
        paths.append(path)
        let data = path.contains("/trace") ? traceData : historyData
        return try JSONDecoder().decode(T.self, from: data)
    }

    func postAccountBound<T: Decodable>(
        _ path: String,
        body: Encodable?,
        expectedAccountScope: String,
        timeout: TimeInterval?
    ) async throws -> T {
        throw HealthReportCompletionTestError.unexpectedCall
    }

    func putFileAccountBound(
        _ path: String,
        fileData: Data,
        fileName: String,
        mimeType: String,
        formData: [String: String],
        expectedAccountScope: String
    ) async throws -> Data {
        throw HealthReportCompletionTestError.unexpectedCall
    }

    func snapshot() -> [String] { paths }
}

private enum HealthReportCompletionTestError: Error {
    case unexpectedCall
}
