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

    func testReportDashboardLoadsOneYearLatestDetailsAndMapsOnlyTwoSummaryStates() async throws {
        let now = try XCTUnwrap(
            ISO8601DateFormatter().date(from: "2026-07-23T12:00:00Z")
        )
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = try XCTUnwrap(TimeZone(secondsFromGMT: 0))
        let completedHistory = HealthReportHistoryResponse(items: [
            HealthReportHistoryItem(
                workflow_id: 42,
                status: "completed",
                report_type: "exam",
                title: "2026年度体检报告",
                hospital: "市第一人民医院",
                report_date: "2026-07-22",
                created_at: "2026-07-22T06:32:00Z"
            ),
            HealthReportHistoryItem(
                workflow_id: 41,
                status: "recognizing",
                report_type: "lab",
                title: "血常规",
                hospital: nil,
                report_date: "2026-06-18",
                created_at: "2026-06-18T02:00:00Z"
            ),
        ])
        let trace = HealthReportTrace(
            workflow: HealthReportTraceWorkflow(id: 42, status: "completed", version: 3),
            assets: [
                HealthReportTraceAsset(id: 10, index: 1, filename: "page-1.jpg", sha256: "one"),
                HealthReportTraceAsset(id: 11, index: 2, filename: "page-2.jpg", sha256: "two"),
            ],
            pages: [],
            locators: [],
            candidates: [
                HealthReportTraceCandidate(id: 20, name: "LDL-C", status: "confirmed", version: 1),
            ],
            confirmation_events: [],
            observations: [],
            score_jobs: [],
            score_items: [],
            score_snapshots: [],
            follow_ups: []
        )
        let interpretation = try JSONDecoder().decode(
            HealthReportInterpretation.self,
            from: Data(
                #"{"workflow_id":42,"subject_user_id":7,"status":"completed","available":true,"unavailable_reason":null,"non_diagnostic_notice":"仅供健康管理参考","document":{"file_url":"/api/reports/42/file"},"candidates":[],"confirmation_events":[],"structured_additions":[{"observation_id":100,"source_candidate_id":20,"confirmation_event_id":30,"canonical_code":"hscrp","canonical_name":"hsCRP","value_numeric":4.8,"value_text":null,"unit":"mg/L","reference_low":null,"reference_high":3.0,"reference_text":null,"abnormal_state":"high","effective_at":"2026-07-22","confirmed_at":"2026-07-23"},{"observation_id":101,"source_candidate_id":21,"confirmation_event_id":31,"canonical_code":"ldlc","canonical_name":"LDL-C","value_numeric":3.7,"value_text":null,"unit":"mmol/L","reference_low":null,"reference_high":3.4,"reference_text":null,"abnormal_state":"high","effective_at":"2026-07-22","confirmed_at":"2026-07-23"}],"major_abnormalities":[{"observation_id":100,"source_candidate_id":20,"confirmation_event_id":30,"canonical_code":"hscrp","canonical_name":"hsCRP","value_numeric":4.8,"value_text":null,"unit":"mg/L","reference_low":null,"reference_high":3.0,"reference_text":null,"abnormal_state":"high","effective_at":"2026-07-22","confirmed_at":"2026-07-23"}],"follow_up":{"available":false,"items":[],"details":null,"unavailable_reason":null},"profile_impacts":[],"score_state":"completed","score_pending":false,"score_snapshots":[]}"#.utf8
            )
        )
        let scope = HealthReportTestAccountScope("account-a")
        let completedRepository = HealthReportDashboardRepositorySpy(
            history: completedHistory,
            trace: trace
        )
        let completedReviewRepository = HealthReportDashboardReviewRepositorySpy(
            interpretation: interpretation
        )
        let completedViewModel = HealthReportDashboardViewModel(
            reportRepository: completedRepository,
            reviewRepository: completedReviewRepository,
            currentAccountScope: { scope.value },
            now: { now },
            calendar: calendar
        )

        await completedViewModel.load(subjectUserID: 7, accountScope: "account-a")
        let recordedQueries = await completedRepository.queries()
        let query = try XCTUnwrap(recordedQueries.first)

        XCTAssertEqual(query.subjectUserID, 7)
        XCTAssertEqual(query.dateFrom, "2025-07-23")
        XCTAssertEqual(query.dateTo, "2026-07-23")
        XCTAssertEqual(completedViewModel.items.map(\.workflow_id), [42, 41], "最新报告必须沿用服务器顺序")
        XCTAssertEqual(completedViewModel.dashboardState, .completed)
        XCTAssertEqual(completedViewModel.originalFileCount, 2)
        XCTAssertEqual(completedViewModel.indicatorCount, 2)
        XCTAssertEqual(completedViewModel.abnormalCount, 1)
        XCTAssertTrue(completedViewModel.summary.contains("2 项指标解析"))

        let parsingRepository = HealthReportDashboardRepositorySpy(
            history: HealthReportHistoryResponse(items: [
                HealthReportHistoryItem(
                    workflow_id: 42,
                    status: "awaiting_confirmation",
                    report_type: "exam",
                    title: "2026年度体检报告",
                    hospital: "市第一人民医院",
                    report_date: "2026-07-22",
                    created_at: "2026-07-22T06:32:00Z"
                )
            ]),
            trace: HealthReportTrace(
                workflow: HealthReportTraceWorkflow(id: 42, status: "awaiting_confirmation", version: 2),
                assets: trace.assets,
                pages: [],
                locators: [],
                candidates: trace.candidates,
                confirmation_events: [],
                observations: [],
                score_jobs: [],
                score_items: [],
                score_snapshots: [],
                follow_ups: []
            )
        )
        let parsingReviewRepository = HealthReportDashboardReviewRepositorySpy(
            interpretation: interpretation
        )
        let parsingViewModel = HealthReportDashboardViewModel(
            reportRepository: parsingRepository,
            reviewRepository: parsingReviewRepository,
            currentAccountScope: { scope.value },
            now: { now },
            calendar: calendar
        )

        await parsingViewModel.load(subjectUserID: 7, accountScope: "account-a")

        XCTAssertEqual(parsingViewModel.dashboardState, .parsing)
        XCTAssertEqual(parsingViewModel.indicatorCount, 1)
        XCTAssertTrue(parsingViewModel.summary.contains("等待你核对"))
        let interpretationRequestCount = await parsingReviewRepository.interpretationRequestCount()
        XCTAssertEqual(interpretationRequestCount, 0, "未完成报告不得提前请求解读")
        XCTAssertEqual(
            HealthReportDashboardState(workflowStatus: .completedScorePending),
            .completed
        )
        XCTAssertEqual(
            HealthReportDashboardState(workflowStatus: .failed),
            .parsing
        )
    }

    func testReportDashboardLateOpenCannotRestoreOldTraceAfterAccountABA() async {
        let latest = HealthReportHistoryItem(
            workflow_id: 70,
            status: "recognizing",
            report_type: "exam",
            title: "当前报告",
            hospital: nil,
            report_date: "2026-07-30",
            created_at: "2026-07-30T08:00:00Z"
        )
        let older = HealthReportHistoryItem(
            workflow_id: 69,
            status: "completed",
            report_type: "exam",
            title: "旧报告",
            hospital: nil,
            report_date: "2026-06-30",
            created_at: "2026-06-30T08:00:00Z"
        )
        let latestTrace = makeTrace(workflowID: 70, status: "recognizing")
        let staleTrace = makeTrace(workflowID: 69, status: "completed")
        let openGate = HealthReportRuntimeFetchGate(blockedFetchOrdinal: 2)
        let repository = HealthReportDashboardRepositorySpy(
            history: HealthReportHistoryResponse(items: [latest, older]),
            traces: [latestTrace, staleTrace, latestTrace],
            traceGate: openGate
        )
        let reviewRepository = HealthReportDashboardReviewRepositorySpy(
            interpretation: makeEmptyInterpretation(workflowID: 70)
        )
        let scope = HealthReportTestAccountScope("account-a")
        let viewModel = HealthReportDashboardViewModel(
            reportRepository: repository,
            reviewRepository: reviewRepository,
            currentAccountScope: { scope.value }
        )
        await viewModel.load(subjectUserID: 7, accountScope: "account-a")

        let staleOpen = Task { @MainActor in await viewModel.open(older) }
        await openGate.waitUntilBlocked()
        scope.value = "account-b"
        await viewModel.load(subjectUserID: nil, accountScope: "account-b")
        scope.value = "account-a"
        await viewModel.load(subjectUserID: 7, accountScope: "account-a")
        await openGate.release()
        await staleOpen.value

        XCTAssertNil(viewModel.selectedTrace, "账号 ABA 后旧 open 结果不得重新打开旧报告")
        XCTAssertNil(viewModel.traceLoadingWorkflowID, "旧 defer 不得清理或篡改新会话 spinner")
        XCTAssertEqual(viewModel.latestItem?.workflow_id, 70)
    }

    func testReportHistoryLateOpenCannotRestoreOldTraceAfterAccountABA() async {
        let item = HealthReportHistoryItem(
            workflow_id: 71,
            status: "completed",
            report_type: "exam",
            title: "旧历史报告",
            hospital: nil,
            report_date: "2026-05-30",
            created_at: "2026-05-30T08:00:00Z"
        )
        let traceGate = HealthReportRuntimeFetchGate(blockedFetchOrdinal: 1)
        let repository = HealthReportDashboardRepositorySpy(
            history: HealthReportHistoryResponse(items: [item]),
            traces: [makeTrace(workflowID: 71, status: "completed")],
            traceGate: traceGate
        )
        let scope = HealthReportTestAccountScope("account-a")
        let viewModel = XAgeReportHistoryViewModel(
            repository: repository,
            currentAccountScope: { scope.value }
        )
        await viewModel.load(subjectUserID: 7, accountScope: "account-a")

        let staleOpen = Task { @MainActor in
            await viewModel.openTrace(
                for: item,
                subjectUserID: 7,
                accountScope: "account-a"
            )
        }
        await traceGate.waitUntilBlocked()
        scope.value = "account-b"
        await viewModel.load(subjectUserID: nil, accountScope: "account-b")
        scope.value = "account-a"
        await viewModel.load(subjectUserID: 7, accountScope: "account-a")
        await traceGate.release()
        await staleOpen.value

        XCTAssertNil(viewModel.selectedTrace, "账号 ABA 后旧历史 trace 不得重新打开 sheet")
        XCTAssertNil(viewModel.traceLoadingWorkflowID, "旧 trace defer 不得清理新会话加载状态")
        XCTAssertEqual(viewModel.items.map(\.workflow_id), [71])
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
            reportType: " lab ",
            expectedAccountScope: "account-a"
        )
        let trace = try await repository.fetchTrace(
            workflowID: 42,
            subjectUserID: 7,
            expectedAccountScope: "account-a"
        )
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

    func testRecognizingPollDoesNotRearmDismissedUploadNotice() async {
        let recognizingAction = HealthReportPrimaryAction(
            code: "recognizing",
            enabled: false,
            pending_count: 0,
            target_workflow_id: nil
        )
        let repository = HealthReportCompletionRepositorySpy(
            sealResult: HealthReportSealResult(
                asset_set_id: 97,
                status: "attached",
                workflow_id: 47,
                duplicate: false,
                failure_code: nil
            ),
            runtimes: [
                makeRuntime(
                    workflowID: 47,
                    version: 3,
                    state: "uploading",
                    status: "recognizing",
                    action: HealthReportPrimaryAction(
                        code: "uploading",
                        enabled: false,
                        pending_count: 0,
                        target_workflow_id: nil
                    )
                ),
                makeRuntime(
                    workflowID: 47,
                    version: 4,
                    state: "recognizing",
                    status: "recognizing",
                    action: recognizingAction
                ),
            ]
        )
        let pollGate = HealthReportSinglePollGate()
        let scope = HealthReportTestAccountScope("account-a")
        let viewModel = HealthReportCompletionViewModel(
            repository: repository,
            currentAccountScope: { scope.value },
            makeID: { "request-recognizing" },
            pollDelay: { try await pollGate.wait() }
        )

        _ = await viewModel.uploadReport(
            files: [
                HealthReportUploadAssetInput(data: Data("page".utf8), fileName: "page.jpg")
            ],
            source: "相册",
            subjectUserID: 7,
            accountScope: "account-a"
        )
        XCTAssertEqual(viewModel.infoMessage, "上传完成，正在后台识别。")

        viewModel.infoMessage = nil
        await pollGate.release()
        await viewModel.waitForCurrentPollForTesting()
        let snapshot = await repository.snapshot()

        XCTAssertEqual(viewModel.activeRuntime?.workflow_version, 4)
        XCTAssertNil(viewModel.infoMessage, "上传中切换为识别中仍属于同一处理阶段，不得重新弹出已关闭提示")
        XCTAssertNotNil(viewModel.backgroundTaskHint, "非模态识别进度必须继续更新")
        XCTAssertEqual(snapshot.runtimeWorkflowIDs, [47, 47])
    }

    func testCancelledABAPollCannotOverwriteNewWorkflowOrRearmNotice() async {
        let processingAction = HealthReportPrimaryAction(
            code: "uploading",
            enabled: false,
            pending_count: 0,
            target_workflow_id: nil
        )
        let staleAction = HealthReportPrimaryAction(
            code: "confirm_and_update_scores",
            enabled: true,
            pending_count: 0,
            target_workflow_id: nil
        )
        let currentAction = HealthReportPrimaryAction(
            code: "review_fields",
            enabled: true,
            pending_count: 1,
            target_workflow_id: nil
        )
        let staleFetchGate = HealthReportRuntimeFetchGate(blockedFetchOrdinal: 2)
        let repository = HealthReportCompletionRepositorySpy(
            sealResults: [
                HealthReportSealResult(
                    asset_set_id: 97,
                    status: "attached",
                    workflow_id: 47,
                    duplicate: false,
                    failure_code: nil
                ),
                HealthReportSealResult(
                    asset_set_id: 98,
                    status: "attached",
                    workflow_id: 48,
                    duplicate: false,
                    failure_code: nil
                ),
            ],
            runtimes: [
                makeRuntime(
                    workflowID: 47,
                    version: 3,
                    state: "uploading",
                    status: "recognizing",
                    action: processingAction
                ),
                makeRuntime(
                    workflowID: 47,
                    version: 4,
                    state: "awaiting_report_confirmation",
                    status: "awaiting_confirmation",
                    action: staleAction
                ),
                makeRuntime(
                    workflowID: 48,
                    version: 10,
                    state: "awaiting_field_review",
                    status: "awaiting_confirmation",
                    action: currentAction
                ),
            ],
            runtimeFetchGate: staleFetchGate
        )
        let scope = HealthReportTestAccountScope("account-a")
        let ids = HealthReportTestIDSequence(["request-old", "request-current"])
        let viewModel = HealthReportCompletionViewModel(
            repository: repository,
            currentAccountScope: { scope.value },
            makeID: { ids.next() },
            pollDelay: {}
        )

        _ = await viewModel.uploadReport(
            files: [
                HealthReportUploadAssetInput(data: Data("old".utf8), fileName: "old.jpg")
            ],
            source: "相册",
            subjectUserID: 7,
            accountScope: "account-a"
        )
        await staleFetchGate.waitUntilBlocked()

        scope.value = "account-b"
        viewModel.accountDidChange(to: "account-b")
        scope.value = "account-a"
        viewModel.accountDidChange(to: "account-a")
        _ = await viewModel.uploadReport(
            files: [
                HealthReportUploadAssetInput(data: Data("current".utf8), fileName: "current.jpg")
            ],
            source: "相册",
            subjectUserID: 7,
            accountScope: "account-a"
        )
        XCTAssertEqual(viewModel.activeRuntime?.workflow_id, 48)
        XCTAssertEqual(viewModel.activeRuntime?.workflow_version, 10)
        viewModel.infoMessage = nil

        await staleFetchGate.release()
        await viewModel.waitForSupersededPollsForTesting()
        let snapshot = await repository.snapshot()

        XCTAssertEqual(snapshot.runtimeWorkflowIDs, [47, 47, 48])
        XCTAssertEqual(viewModel.activeRuntime?.workflow_id, 48)
        XCTAssertEqual(viewModel.activeRuntime?.workflow_version, 10)
        XCTAssertNil(viewModel.infoMessage, "被取消的旧轮询不得在账号 ABA 后回写或重新弹窗")
    }

    func testLateUploadRuntimeCannotOverwriteNewWorkflowAfterAccountABA() async {
        let staleFetchGate = HealthReportRuntimeFetchGate(blockedFetchOrdinal: 1)
        let repository = HealthReportCompletionRepositorySpy(
            sealResults: [
                HealthReportSealResult(
                    asset_set_id: 101,
                    status: "attached",
                    workflow_id: 51,
                    duplicate: false,
                    failure_code: nil
                ),
                HealthReportSealResult(
                    asset_set_id: 102,
                    status: "attached",
                    workflow_id: 52,
                    duplicate: false,
                    failure_code: nil
                ),
            ],
            runtimes: [
                makeRuntime(
                    workflowID: 51,
                    version: 4,
                    state: "awaiting_report_confirmation",
                    status: "awaiting_confirmation",
                    action: HealthReportPrimaryAction(
                        code: "confirm_and_update_scores",
                        enabled: true,
                        pending_count: 0,
                        target_workflow_id: nil
                    )
                ),
                makeRuntime(
                    workflowID: 52,
                    version: 8,
                    state: "awaiting_field_review",
                    status: "awaiting_confirmation",
                    action: HealthReportPrimaryAction(
                        code: "review_fields",
                        enabled: true,
                        pending_count: 1,
                        target_workflow_id: nil
                    )
                ),
            ],
            runtimeFetchGate: staleFetchGate
        )
        let scope = HealthReportTestAccountScope("account-a")
        let ids = HealthReportTestIDSequence(["upload-old", "upload-current"])
        let viewModel = HealthReportCompletionViewModel(
            repository: repository,
            currentAccountScope: { scope.value },
            makeID: { ids.next() },
            pollDelay: { throw CancellationError() }
        )

        let staleUpload = Task { @MainActor in
            await viewModel.uploadReport(
                files: [
                    HealthReportUploadAssetInput(data: Data("old".utf8), fileName: "old.jpg")
                ],
                source: "相册",
                subjectUserID: 7,
                accountScope: "account-a"
            )
        }
        await staleFetchGate.waitUntilBlocked()
        performAccountABA(scope: scope, viewModel: viewModel)

        _ = await viewModel.uploadReport(
            files: [
                HealthReportUploadAssetInput(data: Data("current".utf8), fileName: "current.jpg")
            ],
            source: "相册",
            subjectUserID: 7,
            accountScope: "account-a"
        )
        viewModel.infoMessage = nil
        await staleFetchGate.release()
        _ = await staleUpload.value

        XCTAssertEqual(viewModel.activeRuntime?.workflow_id, 52)
        XCTAssertEqual(viewModel.activeRuntime?.workflow_version, 8)
        XCTAssertNil(viewModel.infoMessage, "旧上传的晚到 runtime 不得覆盖新会话或重弹提示")
    }

    func testLateRecoveryRuntimeCannotOverwriteNewWorkflowAfterAccountABA() async {
        let staleFetchGate = HealthReportRuntimeFetchGate(blockedFetchOrdinal: 1)
        let repository = HealthReportCompletionRepositorySpy(
            sealResults: [
                HealthReportSealResult(
                    asset_set_id: 103,
                    status: "rejected",
                    workflow_id: nil,
                    duplicate: false,
                    failure_code: "missing_page",
                    recovery_action: "upload_missing_pages",
                    problem_asset_indices: [],
                    missing_page_indices: [2]
                ),
                HealthReportSealResult(
                    asset_set_id: 103,
                    status: "attached",
                    workflow_id: 53,
                    duplicate: false,
                    failure_code: nil
                ),
                HealthReportSealResult(
                    asset_set_id: 104,
                    status: "attached",
                    workflow_id: 54,
                    duplicate: false,
                    failure_code: nil
                ),
            ],
            runtimes: [
                makeRuntime(
                    workflowID: 53,
                    version: 4,
                    state: "awaiting_report_confirmation",
                    status: "awaiting_confirmation",
                    action: HealthReportPrimaryAction(
                        code: "confirm_and_update_scores",
                        enabled: true,
                        pending_count: 0,
                        target_workflow_id: nil
                    )
                ),
                makeRuntime(
                    workflowID: 54,
                    version: 9,
                    state: "awaiting_field_review",
                    status: "awaiting_confirmation",
                    action: HealthReportPrimaryAction(
                        code: "review_fields",
                        enabled: true,
                        pending_count: 1,
                        target_workflow_id: nil
                    )
                ),
            ],
            runtimeFetchGate: staleFetchGate
        )
        let scope = HealthReportTestAccountScope("account-a")
        let ids = HealthReportTestIDSequence(["recovery-base", "recovery-current"])
        let viewModel = HealthReportCompletionViewModel(
            repository: repository,
            currentAccountScope: { scope.value },
            makeID: { ids.next() },
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

        let staleRecovery = Task { @MainActor in
            await viewModel.recoverReportAsset(
                input: HealthReportUploadAssetInput(
                    data: Data("page-2".utf8),
                    fileName: "page-2.jpg"
                ),
                assetIndex: 2
            )
        }
        await staleFetchGate.waitUntilBlocked()
        performAccountABA(scope: scope, viewModel: viewModel)
        _ = await viewModel.uploadReport(
            files: [
                HealthReportUploadAssetInput(data: Data("current".utf8), fileName: "current.jpg")
            ],
            source: "相册",
            subjectUserID: 7,
            accountScope: "account-a"
        )
        viewModel.infoMessage = nil
        await staleFetchGate.release()
        _ = await staleRecovery.value

        XCTAssertEqual(viewModel.activeRuntime?.workflow_id, 54)
        XCTAssertEqual(viewModel.activeRuntime?.workflow_version, 9)
        XCTAssertNil(viewModel.infoMessage, "旧恢复请求不得在账号 ABA 后覆盖新报告")
    }

    func testLateDuplicateDecisionCannotOverwriteNewWorkflowAfterAccountABA() async throws {
        let staleFetchGate = HealthReportRuntimeFetchGate(blockedFetchOrdinal: 2)
        let repository = HealthReportCompletionRepositorySpy(
            sealResults: [
                HealthReportSealResult(
                    asset_set_id: 105,
                    status: "attached",
                    workflow_id: 55,
                    duplicate: false,
                    failure_code: nil
                ),
                HealthReportSealResult(
                    asset_set_id: 106,
                    status: "attached",
                    workflow_id: 56,
                    duplicate: false,
                    failure_code: nil
                ),
            ],
            runtimes: [
                makeRuntime(
                    workflowID: 55,
                    version: 3,
                    state: "awaiting_duplicate_decision",
                    status: "awaiting_confirmation",
                    action: HealthReportPrimaryAction(
                        code: "resolve_duplicate",
                        enabled: true,
                        pending_count: 1,
                        target_workflow_id: 11
                    )
                ),
                makeRuntime(
                    workflowID: 11,
                    version: 7,
                    state: "completed",
                    status: "completed",
                    action: HealthReportPrimaryAction(
                        code: "view_interpretation",
                        enabled: true,
                        pending_count: 0,
                        target_workflow_id: nil
                    )
                ),
                makeRuntime(
                    workflowID: 56,
                    version: 10,
                    state: "awaiting_field_review",
                    status: "awaiting_confirmation",
                    action: HealthReportPrimaryAction(
                        code: "review_fields",
                        enabled: true,
                        pending_count: 1,
                        target_workflow_id: nil
                    )
                ),
            ],
            duplicateResult: HealthReportDuplicateDecisionResult(
                workflow_id: 55,
                matched_workflow_id: 11,
                decision_status: "use_existing",
                similarity: 0.98,
                workflow_version: 4
            ),
            runtimeFetchGate: staleFetchGate
        )
        let scope = HealthReportTestAccountScope("account-a")
        let ids = HealthReportTestIDSequence(
            ["duplicate-base", "duplicate-decision", "duplicate-current"]
        )
        let viewModel = HealthReportCompletionViewModel(
            repository: repository,
            currentAccountScope: { scope.value },
            makeID: { ids.next() },
            pollDelay: { throw CancellationError() }
        )
        _ = await viewModel.uploadReport(
            files: [
                HealthReportUploadAssetInput(data: Data("base".utf8), fileName: "base.jpg")
            ],
            source: "相册",
            subjectUserID: 7,
            accountScope: "account-a"
        )
        let prompt = try XCTUnwrap(viewModel.duplicatePrompt)

        let staleDecision = Task { @MainActor in
            await viewModel.decideDuplicate(.useExisting, prompt: prompt)
        }
        await staleFetchGate.waitUntilBlocked()
        performAccountABA(scope: scope, viewModel: viewModel)
        _ = await viewModel.uploadReport(
            files: [
                HealthReportUploadAssetInput(data: Data("current".utf8), fileName: "current.jpg")
            ],
            source: "相册",
            subjectUserID: 7,
            accountScope: "account-a"
        )
        viewModel.infoMessage = nil
        await staleFetchGate.release()
        await staleDecision.value

        XCTAssertEqual(viewModel.activeRuntime?.workflow_id, 56)
        XCTAssertEqual(viewModel.activeRuntime?.workflow_version, 10)
        XCTAssertNil(viewModel.infoMessage, "旧重复决策不得在账号 ABA 后打开旧报告")
    }

    func testLateManualRefreshCannotOverwriteNewWorkflowAfterAccountABA() async {
        let staleFetchGate = HealthReportRuntimeFetchGate(blockedFetchOrdinal: 2)
        let repository = HealthReportCompletionRepositorySpy(
            sealResults: [
                HealthReportSealResult(
                    asset_set_id: 107,
                    status: "attached",
                    workflow_id: 57,
                    duplicate: false,
                    failure_code: nil
                ),
                HealthReportSealResult(
                    asset_set_id: 108,
                    status: "attached",
                    workflow_id: 58,
                    duplicate: false,
                    failure_code: nil
                ),
            ],
            runtimes: [
                makeRuntime(
                    workflowID: 57,
                    version: 3,
                    state: "awaiting_field_review",
                    status: "awaiting_confirmation",
                    action: HealthReportPrimaryAction(
                        code: "review_fields",
                        enabled: true,
                        pending_count: 1,
                        target_workflow_id: nil
                    )
                ),
                makeRuntime(
                    workflowID: 57,
                    version: 4,
                    state: "awaiting_report_confirmation",
                    status: "awaiting_confirmation",
                    action: HealthReportPrimaryAction(
                        code: "confirm_and_update_scores",
                        enabled: true,
                        pending_count: 0,
                        target_workflow_id: nil
                    )
                ),
                makeRuntime(
                    workflowID: 58,
                    version: 11,
                    state: "awaiting_field_review",
                    status: "awaiting_confirmation",
                    action: HealthReportPrimaryAction(
                        code: "review_fields",
                        enabled: true,
                        pending_count: 1,
                        target_workflow_id: nil
                    )
                ),
            ],
            runtimeFetchGate: staleFetchGate
        )
        let scope = HealthReportTestAccountScope("account-a")
        let ids = HealthReportTestIDSequence(["refresh-base", "refresh-current"])
        let viewModel = HealthReportCompletionViewModel(
            repository: repository,
            currentAccountScope: { scope.value },
            makeID: { ids.next() },
            pollDelay: { throw CancellationError() }
        )
        _ = await viewModel.uploadReport(
            files: [
                HealthReportUploadAssetInput(data: Data("base".utf8), fileName: "base.jpg")
            ],
            source: "相册",
            subjectUserID: 7,
            accountScope: "account-a"
        )

        let staleRefresh = Task { @MainActor in
            await viewModel.refreshActiveRuntime()
        }
        await staleFetchGate.waitUntilBlocked()
        performAccountABA(scope: scope, viewModel: viewModel)
        _ = await viewModel.uploadReport(
            files: [
                HealthReportUploadAssetInput(data: Data("current".utf8), fileName: "current.jpg")
            ],
            source: "相册",
            subjectUserID: 7,
            accountScope: "account-a"
        )
        viewModel.infoMessage = nil
        await staleFetchGate.release()
        await staleRefresh.value

        XCTAssertEqual(viewModel.activeRuntime?.workflow_id, 58)
        XCTAssertEqual(viewModel.activeRuntime?.workflow_version, 11)
        XCTAssertNil(viewModel.infoMessage, "旧手动刷新不得在账号 ABA 后覆盖新报告")
    }

    func testLegacyHealthDocumentUploadUsesAccountBoundMultipartTransport() async throws {
        let api = MockAPIService()
        await api.setRawResponse(
            for: "/api/health-data/upload",
            data: Data(
                #"{"id":"bound-upload","name":"bound.jpg","doc_type":"exam","extraction_status":"pending","report_workflow_id":61,"report_workflow_status":"recognizing","report_subject_user_id":7,"report_duplicate":false}"#.utf8
            )
        )
        let repository = HealthDataRepository(api: api)

        _ = try await repository.uploadDocument(
            data: Data("report".utf8),
            fileName: "report.jpg",
            docType: "exam",
            expectedAccountScope: "account-a"
        )
        let uploads = await api.accountBoundFileUploads()

        XCTAssertEqual(uploads.count, 1)
        XCTAssertEqual(uploads.first?.path, "/api/health-data/upload")
        XCTAssertEqual(uploads.first?.expectedAccountScope, "account-a")
        XCTAssertEqual(uploads.first?.formData["doc_type"], "exam")
        XCTAssertEqual(uploads.first?.fileData, Data("report".utf8))
    }

    func testHealthDataLegacyPollCannotOverwriteNewUploadAfterAccountABA() async {
        let staleDocumentGate = HealthDataRepositoryCallGate(blockedCallOrdinal: 1)
        let repository = HealthDataUploadRepositorySpy(
            uploadDocuments: [
                makeHealthDocument(
                    id: "legacy-old",
                    name: "old.jpg",
                    docType: "exam",
                    extractionStatus: "pending",
                    workflowID: 62,
                    workflowStatus: "recognizing"
                ),
                makeHealthDocument(
                    id: "legacy-current",
                    name: "current.jpg",
                    docType: "exam",
                    extractionStatus: "done",
                    workflowID: 63,
                    workflowStatus: "awaiting_confirmation"
                ),
            ],
            fetchedDocuments: [
                makeHealthDocument(
                    id: "legacy-old",
                    name: "old.jpg",
                    docType: "exam",
                    extractionStatus: "done",
                    workflowID: 62,
                    workflowStatus: "awaiting_confirmation"
                )
            ],
            fetchDocumentGate: staleDocumentGate
        )
        let scope = HealthReportTestAccountScope("account-a")
        let notifications = HealthReportNotificationRecorder()
        let viewModel = HealthDataViewModel(
            repository: repository,
            currentAccountScope: { scope.value },
            pollDelay: {},
            scheduleRecognitionComplete: { await notifications.record(fileName: $0) }
        )

        _ = await viewModel.uploadFile(data: Data("old".utf8), fileName: "old.jpg")
        await staleDocumentGate.waitUntilBlocked()
        scope.value = "account-b"
        viewModel.accountDidChange(to: "account-b")
        scope.value = "account-a"
        viewModel.accountDidChange(to: "account-a")
        _ = await viewModel.uploadFile(
            data: Data("current".utf8),
            fileName: "current.jpg"
        )
        viewModel.infoMessage = nil
        await staleDocumentGate.release()
        await viewModel.waitForSupersededPollsForTesting()
        await viewModel.waitForNotificationForTesting()
        let notificationFiles = await notifications.fileNames()

        XCTAssertEqual(viewModel.activeReportWorkflow?.workflowID, 63)
        XCTAssertEqual(viewModel.activeReportTitle, "current.jpg")
        XCTAssertNil(viewModel.errorMessage)
        XCTAssertNil(viewModel.infoMessage, "旧 legacy 轮询不得覆盖新上传或重弹提示")
        XCTAssertEqual(notificationFiles, ["current.jpg"], "旧账号轮询不得安排旧文件完成通知")
    }

    func testMedicalRecordLateUploadCannotShowSuccessOrErrorAfterAccountABA() async {
        let staleUploadGate = HealthDataRepositoryCallGate(blockedCallOrdinal: 1)
        let repository = HealthDataUploadRepositorySpy(
            uploadDocuments: [
                makeHealthDocument(
                    id: "record-old",
                    name: "old.pdf",
                    docType: "record",
                    extractionStatus: "failed",
                    workflowID: 64,
                    workflowStatus: "failed"
                ),
                makeHealthDocument(
                    id: "record-current",
                    name: "current.pdf",
                    docType: "record",
                    extractionStatus: "pending",
                    workflowID: 65,
                    workflowStatus: "recognizing"
                ),
            ],
            uploadGate: staleUploadGate
        )
        let scope = HealthReportTestAccountScope("account-a")
        let viewModel = MedicalRecordListViewModel(
            repository: repository,
            currentAccountScope: { scope.value }
        )

        let staleUpload = Task { @MainActor in
            await viewModel.uploadRecord(data: Data("old".utf8), fileName: "old.pdf")
        }
        await staleUploadGate.waitUntilBlocked()
        scope.value = "account-b"
        viewModel.accountDidChange(to: "account-b")
        scope.value = "account-a"
        viewModel.accountDidChange(to: "account-a")
        await viewModel.uploadRecord(
            data: Data("current".utf8),
            fileName: "current.pdf"
        )
        let currentSuccess = viewModel.successMessage
        await staleUploadGate.release()
        await staleUpload.value

        XCTAssertNotNil(currentSuccess)
        XCTAssertEqual(viewModel.successMessage, currentSuccess)
        XCTAssertNil(viewModel.errorMessage, "旧病例上传失败结果不得污染新账号状态")
    }

    func testExamReportLateUploadCannotShowSuccessOrErrorAfterAccountABA() async {
        let staleUploadGate = HealthDataRepositoryCallGate(blockedCallOrdinal: 1)
        let repository = HealthDataUploadRepositorySpy(
            uploadDocuments: [
                makeHealthDocument(
                    id: "exam-old",
                    name: "old.pdf",
                    docType: "exam",
                    extractionStatus: "failed",
                    workflowID: 66,
                    workflowStatus: "failed"
                ),
                makeHealthDocument(
                    id: "exam-current",
                    name: "current.pdf",
                    docType: "exam",
                    extractionStatus: "pending",
                    workflowID: 67,
                    workflowStatus: "recognizing"
                ),
            ],
            uploadGate: staleUploadGate
        )
        let scope = HealthReportTestAccountScope("account-a")
        let viewModel = ExamReportListViewModel(
            repository: repository,
            currentAccountScope: { scope.value }
        )

        let staleUpload = Task { @MainActor in
            await viewModel.uploadExam(data: Data("old".utf8), fileName: "old.pdf")
        }
        await staleUploadGate.waitUntilBlocked()
        scope.value = "account-b"
        viewModel.accountDidChange(to: "account-b")
        scope.value = "account-a"
        viewModel.accountDidChange(to: "account-a")
        await viewModel.uploadExam(
            data: Data("current".utf8),
            fileName: "current.pdf"
        )
        let currentSuccess = viewModel.successMessage
        await staleUploadGate.release()
        await staleUpload.value

        XCTAssertNotNil(currentSuccess)
        XCTAssertEqual(viewModel.successMessage, currentSuccess)
        XCTAssertNil(viewModel.errorMessage, "旧体检上传失败结果不得污染新账号状态")
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

    func testSharedUploadCoordinatorSurvivesPanelRecreationBlocksConcurrentEntriesAndRejectsWrongSubject() async {
        let runtimeGate = HealthReportRuntimeFetchGate(blockedFetchOrdinal: 1)
        let firstRepository = HealthReportCompletionRepositorySpy(
            sealResult: HealthReportSealResult(
                asset_set_id: 120,
                status: "attached",
                workflow_id: 70,
                duplicate: false,
                failure_code: nil
            ),
            runtimes: [
                makeRuntime(
                    workflowID: 70,
                    state: "awaiting_confirmation",
                    status: "awaiting_confirmation",
                    action: HealthReportPrimaryAction(
                        code: "review_fields",
                        enabled: true,
                        pending_count: 1,
                        target_workflow_id: nil
                    )
                )
            ],
            runtimeFetchGate: runtimeGate
        )
        let secondRepository = HealthReportCompletionRepositorySpy(
            sealResult: HealthReportSealResult(
                asset_set_id: 121,
                status: "attached",
                workflow_id: 71,
                duplicate: false,
                failure_code: nil
            ),
            runtimes: []
        )
        let scope = HealthReportTestAccountScope("account-a")
        let singleFlight = HealthReportUploadSingleFlight()
        let panelViewModel = HealthReportCompletionViewModel(
            repository: firstRepository,
            currentAccountScope: { scope.value },
            makeID: { "panel-upload" },
            pollDelay: { throw CancellationError() },
            uploadSingleFlight: singleFlight
        )
        let externalEntryViewModel = HealthReportCompletionViewModel(
            repository: secondRepository,
            currentAccountScope: { scope.value },
            makeID: { "external-upload" },
            pollDelay: { throw CancellationError() },
            uploadSingleFlight: singleFlight
        )

        let panelUpload = Task { @MainActor in
            await panelViewModel.uploadReport(
                files: [
                    HealthReportUploadAssetInput(data: Data("page".utf8), fileName: "page.jpg")
                ],
                source: "相册",
                subjectUserID: 7,
                accountScope: "account-a"
            )
        }
        await runtimeGate.waitUntilBlocked()

        XCTAssertTrue(
            panelViewModel.ownsActiveSession(subjectUserID: 7, accountScope: "account-a"),
            "页面关闭重建后应继续用根层 ViewModel 识别同一报告会话"
        )
        XCTAssertFalse(panelViewModel.ownsActiveSession(subjectUserID: 8, accountScope: "account-a"))
        XCTAssertFalse(panelViewModel.ownsActiveSession(subjectUserID: 7, accountScope: "account-b"))
        XCTAssertTrue(panelViewModel.uploading, "读取服务端运行态完成前仍必须保持上传单飞状态")

        let reentrantRoute = await panelViewModel.uploadReport(
            files: [
                HealthReportUploadAssetInput(data: Data("again".utf8), fileName: "again.jpg")
            ],
            source: "相册",
            subjectUserID: 7,
            accountScope: "account-a"
        )
        let firstSnapshotWhileBlocked = await firstRepository.snapshot()
        XCTAssertNil(reentrantRoute)
        XCTAssertEqual(firstSnapshotWhileBlocked.sessionRequests.count, 1, "同一入口不得在封存后重入")

        let concurrentRoute = await externalEntryViewModel.uploadReport(
            files: [
                HealthReportUploadAssetInput(data: Data("other".utf8), fileName: "other.jpg")
            ],
            source: "文件",
            subjectUserID: 7,
            accountScope: "account-a"
        )
        let secondSnapshot = await secondRepository.snapshot()
        XCTAssertNil(concurrentRoute)
        XCTAssertEqual(externalEntryViewModel.errorMessage, "另一份报告正在上传，请等待完成后再试。")
        XCTAssertEqual(secondSnapshot.sessionRequests.count, 0, "其他入口不得创建第二个上传会话")

        await runtimeGate.release()
        let route = await panelUpload.value
        XCTAssertEqual(route?.workflowID, 70)
        XCTAssertTrue(panelViewModel.ownsActiveSession(subjectUserID: 7, accountScope: "account-a"))

        scope.value = "account-b"
        panelViewModel.accountDidChange(to: "account-b")
        XCTAssertFalse(panelViewModel.ownsActiveSession(subjectUserID: 7, accountScope: "account-a"))

        scope.value = "account-a"
        let mismatchedRepository = HealthReportCompletionRepositorySpy(
            sealResult: HealthReportSealResult(
                asset_set_id: 122,
                status: "attached",
                workflow_id: 72,
                duplicate: false,
                failure_code: nil
            ),
            runtimes: [
                makeRuntime(
                    workflowID: 72,
                    subjectUserID: 8,
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
        let mismatchedViewModel = HealthReportCompletionViewModel(
            repository: mismatchedRepository,
            currentAccountScope: { scope.value },
            makeID: { "wrong-subject" },
            pollDelay: { throw CancellationError() },
            uploadSingleFlight: singleFlight
        )
        let mismatchedRoute = await mismatchedViewModel.uploadReport(
            files: [
                HealthReportUploadAssetInput(data: Data("wrong".utf8), fileName: "wrong.jpg")
            ],
            source: "文件",
            subjectUserID: 7,
            accountScope: "account-a"
        )
        XCTAssertNil(mismatchedRoute)
        XCTAssertNil(mismatchedViewModel.activeRuntime)
        XCTAssertEqual(mismatchedViewModel.errorMessage, "服务器响应异常")
        XCTAssertFalse(
            mismatchedViewModel.ownsActiveSession(subjectUserID: 7, accountScope: "account-a")
        )
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
        XCTAssertTrue(
            viewModel.ownsActiveSession(subjectUserID: 7, accountScope: "account-a"),
            "报告页关闭重开后，重复决策必须依赖根层会话归属而不是旧页面 UUID"
        )
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

    func testAbandonUploadRecoveryDeletesServerSessionWithCapturedAccountScope() async {
        let repository = HealthReportCompletionRepositorySpy(
            sealResult: HealthReportSealResult(
                asset_set_id: 97,
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
            makeID: { "request-abandon" },
            pollDelay: { throw CancellationError() }
        )

        _ = await viewModel.uploadReport(
            files: [
                HealthReportUploadAssetInput(
                    data: Data("blur".utf8),
                    fileName: "page.jpg"
                )
            ],
            source: "相册",
            subjectUserID: 7,
            accountScope: "account-a"
        )
        XCTAssertEqual(viewModel.uploadRecovery?.assetSetID, 97)

        viewModel.abandonUploadRecovery()
        await repository.waitUntilAbandonRequested()
        let snapshot = await repository.snapshot()

        XCTAssertNil(viewModel.uploadRecovery)
        XCTAssertEqual(snapshot.abandonedAssetSetIDs, [97])
        XCTAssertEqual(snapshot.abandonedSubjectUserIDs, [7])
        XCTAssertEqual(snapshot.abandonedAccountScopes, ["account-a"])
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

    private func performAccountABA(
        scope: HealthReportTestAccountScope,
        viewModel: HealthReportCompletionViewModel
    ) {
        scope.value = "account-b"
        viewModel.accountDidChange(to: "account-b")
        scope.value = "account-a"
        viewModel.accountDidChange(to: "account-a")
    }

    private func makeHealthDocument(
        id: String,
        name: String,
        docType: String,
        extractionStatus: String,
        workflowID: Int,
        workflowStatus: String
    ) -> HealthDocument {
        let object: [String: Any] = [
            "id": id,
            "name": name,
            "doc_type": docType,
            "extraction_status": extractionStatus,
            "report_workflow_id": workflowID,
            "report_workflow_status": workflowStatus,
            "report_subject_user_id": 7,
            "report_duplicate": false,
        ]
        let data = try! JSONSerialization.data(withJSONObject: object)
        return try! JSONDecoder().decode(HealthDocument.self, from: data)
    }

    private func makeTrace(workflowID: Int, status: String) -> HealthReportTrace {
        HealthReportTrace(
            workflow: HealthReportTraceWorkflow(id: workflowID, status: status, version: 1),
            assets: [],
            pages: [],
            locators: [],
            candidates: [],
            confirmation_events: [],
            observations: [],
            score_jobs: [],
            score_items: [],
            score_snapshots: [],
            follow_ups: []
        )
    }

    private func makeEmptyInterpretation(workflowID: Int) -> HealthReportInterpretation {
        try! JSONDecoder().decode(
            HealthReportInterpretation.self,
            from: Data(
                """
                {"workflow_id":\(workflowID),"subject_user_id":7,"status":"recognizing","available":false,"unavailable_reason":"processing","non_diagnostic_notice":"仅供健康管理参考","document":null,"candidates":[],"confirmation_events":[],"structured_additions":[],"major_abnormalities":[],"follow_up":{"available":false,"items":[],"details":null,"unavailable_reason":"processing"},"profile_impacts":[],"score_state":"pending","score_pending":true,"score_snapshots":[]}
                """.utf8
            )
        )
    }

    private func makeRuntime(
        workflowID: Int,
        subjectUserID: Int = 7,
        version: Int = 3,
        state: String,
        status: String,
        action: HealthReportPrimaryAction
    ) -> HealthReportRuntime {
        HealthReportRuntime(
            workflow_id: workflowID,
            subject_user_id: subjectUserID,
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

    func getAccountBound<T: Decodable>(
        _ path: String,
        expectedAccountScope: String,
        timeout: TimeInterval?
    ) async throws -> T {
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

    func deleteVoidAccountBound(
        _ path: String,
        expectedAccountScope: String
    ) async throws {
        throw HealthReportCompletionTestError.unexpectedCall
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

private actor HealthReportSinglePollGate {
    private var continuation: CheckedContinuation<Void, Never>?
    private var released = false
    private var callCount = 0

    func wait() async throws {
        callCount += 1
        guard callCount == 1 else { throw CancellationError() }
        guard !released else { return }
        await withCheckedContinuation { continuation = $0 }
    }

    func release() {
        released = true
        continuation?.resume()
        continuation = nil
    }
}

private actor HealthReportRuntimeFetchGate {
    private let blockedFetchOrdinal: Int
    private var blocked = false
    private var released = false
    private var blockedWaiters: [CheckedContinuation<Void, Never>] = []
    private var releaseContinuation: CheckedContinuation<Void, Never>?

    init(blockedFetchOrdinal: Int) {
        self.blockedFetchOrdinal = blockedFetchOrdinal
    }

    func intercept(fetchOrdinal: Int) async {
        guard fetchOrdinal == blockedFetchOrdinal else { return }
        blocked = true
        let waiters = blockedWaiters
        blockedWaiters.removeAll()
        waiters.forEach { $0.resume() }
        guard !released else { return }
        await withCheckedContinuation { releaseContinuation = $0 }
    }

    func waitUntilBlocked() async {
        guard !blocked else { return }
        await withCheckedContinuation { blockedWaiters.append($0) }
    }

    func release() {
        released = true
        releaseContinuation?.resume()
        releaseContinuation = nil
    }
}

private actor HealthDataRepositoryCallGate {
    private let blockedCallOrdinal: Int
    private var blocked = false
    private var released = false
    private var blockedWaiters: [CheckedContinuation<Void, Never>] = []
    private var releaseContinuation: CheckedContinuation<Void, Never>?

    init(blockedCallOrdinal: Int) {
        self.blockedCallOrdinal = blockedCallOrdinal
    }

    func intercept(callOrdinal: Int) async {
        guard callOrdinal == blockedCallOrdinal else { return }
        blocked = true
        let waiters = blockedWaiters
        blockedWaiters.removeAll()
        waiters.forEach { $0.resume() }
        guard !released else { return }
        await withCheckedContinuation { releaseContinuation = $0 }
    }

    func waitUntilBlocked() async {
        guard !blocked else { return }
        await withCheckedContinuation { blockedWaiters.append($0) }
    }

    func release() {
        released = true
        releaseContinuation?.resume()
        releaseContinuation = nil
    }
}

private actor HealthDataUploadRepositorySpy: HealthDataRepositoryProtocol {
    private var uploadDocuments: [HealthDocument]
    private var fetchedDocuments: [HealthDocument]
    private let uploadGate: HealthDataRepositoryCallGate?
    private let fetchDocumentGate: HealthDataRepositoryCallGate?
    private var uploadCallCount = 0
    private var fetchDocumentCallCount = 0
    private var latestReturnedDocument: HealthDocument?
    private var expectedAccountScopes: [String] = []

    init(
        uploadDocuments: [HealthDocument],
        fetchedDocuments: [HealthDocument] = [],
        uploadGate: HealthDataRepositoryCallGate? = nil,
        fetchDocumentGate: HealthDataRepositoryCallGate? = nil
    ) {
        self.uploadDocuments = uploadDocuments
        self.fetchedDocuments = fetchedDocuments
        self.uploadGate = uploadGate
        self.fetchDocumentGate = fetchDocumentGate
    }

    func fetchDocuments(docType: String) async throws -> [HealthDocument] {
        latestReturnedDocument.map { [$0] } ?? []
    }

    func fetchDocument(id: String) async throws -> HealthDocument {
        fetchDocumentCallCount += 1
        guard !fetchedDocuments.isEmpty else {
            throw HealthReportCompletionTestError.unexpectedCall
        }
        let document = fetchedDocuments.removeFirst()
        await fetchDocumentGate?.intercept(callOrdinal: fetchDocumentCallCount)
        return document
    }

    func uploadDocument(
        data: Data,
        fileName: String,
        docType: String,
        expectedAccountScope: String
    ) async throws -> HealthDocument {
        uploadCallCount += 1
        expectedAccountScopes.append(expectedAccountScope)
        guard !uploadDocuments.isEmpty else {
            throw HealthReportCompletionTestError.unexpectedCall
        }
        let document = uploadDocuments.removeFirst()
        await uploadGate?.intercept(callOrdinal: uploadCallCount)
        latestReturnedDocument = document
        return document
    }

    func deleteDocument(id: String) async throws {}

    func fetchSummary() async throws -> HealthDataSummary {
        try JSONDecoder().decode(
            HealthDataSummary.self,
            from: Data(#"{"summary_text":"","updated_at":null}"#.utf8)
        )
    }

    func generateSummary() async throws -> HealthDataSummary {
        throw HealthReportCompletionTestError.unexpectedCall
    }

    func generateSummaryAsync() async throws -> SummaryTaskResponse {
        throw HealthReportCompletionTestError.unexpectedCall
    }

    func getSummaryTask(taskId: String) async throws -> SummaryTaskResponse {
        throw HealthReportCompletionTestError.unexpectedCall
    }
}

private actor HealthReportNotificationRecorder {
    private var recordedFileNames: [String] = []

    func record(fileName: String) {
        recordedFileNames.append(fileName)
    }

    func fileNames() -> [String] {
        recordedFileNames
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
        let abandonedAssetSetIDs: [Int]
        let abandonedSubjectUserIDs: [Int]
        let abandonedAccountScopes: [String]
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
    private var abandonedAssetSetIDs: [Int] = []
    private var abandonedSubjectUserIDs: [Int] = []
    private var abandonedAccountScopes: [String] = []
    private var abandonWaiters: [CheckedContinuation<Void, Never>] = []
    private let runtimeFetchGate: HealthReportRuntimeFetchGate?

    init(
        sealResult: HealthReportSealResult,
        runtimes: [HealthReportRuntime],
        duplicateResult: HealthReportDuplicateDecisionResult = HealthReportDuplicateDecisionResult(
            workflow_id: 1,
            matched_workflow_id: 1,
            decision_status: "continue_new",
            similarity: 0,
            workflow_version: 1
        ),
        runtimeFetchGate: HealthReportRuntimeFetchGate? = nil
    ) {
        self.sealResults = [sealResult]
        self.runtimes = runtimes
        self.duplicateResult = duplicateResult
        self.runtimeFetchGate = runtimeFetchGate
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
        ),
        runtimeFetchGate: HealthReportRuntimeFetchGate? = nil
    ) {
        precondition(!sealResults.isEmpty)
        self.sealResults = sealResults
        self.runtimes = runtimes
        self.duplicateResult = duplicateResult
        self.runtimeFetchGate = runtimeFetchGate
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

    func abandonUploadSession(
        assetSetID: Int,
        subjectUserID: Int,
        expectedAccountScope: String
    ) async throws {
        abandonedAssetSetIDs.append(assetSetID)
        abandonedSubjectUserIDs.append(subjectUserID)
        abandonedAccountScopes.append(expectedAccountScope)
        let waiters = abandonWaiters
        abandonWaiters.removeAll()
        waiters.forEach { $0.resume() }
    }

    func fetchRuntime(
        workflowID: Int,
        subjectUserID: Int,
        expectedAccountScope: String
    ) async throws -> HealthReportRuntime {
        runtimeWorkflowIDs.append(workflowID)
        guard !runtimes.isEmpty else { throw HealthReportCompletionTestError.unexpectedCall }
        let runtime = runtimes.removeFirst()
        await runtimeFetchGate?.intercept(fetchOrdinal: runtimeWorkflowIDs.count)
        return runtime
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
        reportType: String?,
        expectedAccountScope: String
    ) async throws -> HealthReportHistoryResponse {
        HealthReportHistoryResponse(items: [])
    }

    func fetchTrace(
        workflowID: Int,
        subjectUserID: Int,
        expectedAccountScope: String
    ) async throws -> HealthReportTrace {
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
            recoveredClientAssetIDs: recoveredClientAssetIDs,
            abandonedAssetSetIDs: abandonedAssetSetIDs,
            abandonedSubjectUserIDs: abandonedSubjectUserIDs,
            abandonedAccountScopes: abandonedAccountScopes
        )
    }

    func waitUntilAbandonRequested() async {
        guard abandonedAssetSetIDs.isEmpty else { return }
        await withCheckedContinuation { abandonWaiters.append($0) }
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

    func getAccountBound<T: Decodable>(
        _ path: String,
        expectedAccountScope: String,
        timeout: TimeInterval?
    ) async throws -> T {
        guard expectedAccountScope == "account-a" else {
            throw HealthReportCompletionTestError.unexpectedCall
        }
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

    func deleteVoidAccountBound(
        _ path: String,
        expectedAccountScope: String
    ) async throws {
        throw HealthReportCompletionTestError.unexpectedCall
    }

    func snapshot() -> [String] { paths }
}

private actor HealthReportDashboardRepositorySpy: HealthReportCompletionRepositoryProtocol {
    struct Query: Sendable {
        let subjectUserID: Int
        let dateFrom: String?
        let dateTo: String?
        let hospital: String?
        let reportType: String?
    }

    private let history: HealthReportHistoryResponse
    private var traces: [HealthReportTrace]
    private let traceGate: HealthReportRuntimeFetchGate?
    private var recordedQueries: [Query] = []
    private var traceRequestCount = 0

    init(history: HealthReportHistoryResponse, trace: HealthReportTrace) {
        self.history = history
        self.traces = [trace]
        self.traceGate = nil
    }

    init(
        history: HealthReportHistoryResponse,
        traces: [HealthReportTrace],
        traceGate: HealthReportRuntimeFetchGate? = nil
    ) {
        precondition(!traces.isEmpty)
        self.history = history
        self.traces = traces
        self.traceGate = traceGate
    }

    func fetchHistory(
        subjectUserID: Int,
        dateFrom: String?,
        dateTo: String?,
        hospital: String?,
        reportType: String?,
        expectedAccountScope: String
    ) async throws -> HealthReportHistoryResponse {
        recordedQueries.append(
            Query(
                subjectUserID: subjectUserID,
                dateFrom: dateFrom,
                dateTo: dateTo,
                hospital: hospital,
                reportType: reportType
            )
        )
        return history
    }

    func fetchTrace(
        workflowID: Int,
        subjectUserID: Int,
        expectedAccountScope: String
    ) async throws -> HealthReportTrace {
        traceRequestCount += 1
        guard !traces.isEmpty else {
            throw HealthReportCompletionTestError.unexpectedCall
        }
        let trace = traces.count == 1 ? traces[0] : traces.removeFirst()
        await traceGate?.intercept(fetchOrdinal: traceRequestCount)
        guard workflowID == trace.workflow.id else {
            throw HealthReportCompletionTestError.unexpectedCall
        }
        return trace
    }

    func startUploadSession(
        _ request: HealthReportUploadSessionRequest,
        expectedAccountScope: String
    ) async throws -> HealthReportUploadSession {
        throw HealthReportCompletionTestError.unexpectedCall
    }

    func uploadAsset(
        assetSetID: Int,
        assetIndex: Int,
        subjectUserID: Int,
        input: HealthReportUploadAssetInput,
        clientAssetID: String,
        expectedAccountScope: String
    ) async throws -> HealthReportUploadedAsset {
        throw HealthReportCompletionTestError.unexpectedCall
    }

    func recoverAsset(
        assetSetID: Int,
        assetIndex: Int,
        subjectUserID: Int,
        input: HealthReportUploadAssetInput,
        clientAssetID: String,
        expectedAccountScope: String
    ) async throws -> HealthReportRecoveredAsset {
        throw HealthReportCompletionTestError.unexpectedCall
    }

    func sealUploadSession(
        assetSetID: Int,
        request: HealthReportSealRequest,
        expectedAccountScope: String
    ) async throws -> HealthReportSealResult {
        throw HealthReportCompletionTestError.unexpectedCall
    }

    func abandonUploadSession(
        assetSetID: Int,
        subjectUserID: Int,
        expectedAccountScope: String
    ) async throws {
        throw HealthReportCompletionTestError.unexpectedCall
    }

    func fetchRuntime(
        workflowID: Int,
        subjectUserID: Int,
        expectedAccountScope: String
    ) async throws -> HealthReportRuntime {
        throw HealthReportCompletionTestError.unexpectedCall
    }

    func decideDuplicate(
        workflowID: Int,
        request: HealthReportDuplicateDecisionRequest,
        expectedAccountScope: String
    ) async throws -> HealthReportDuplicateDecisionResult {
        throw HealthReportCompletionTestError.unexpectedCall
    }

    func retryScores(
        workflowID: Int,
        subjectUserID: Int,
        expectedAccountScope: String
    ) async throws -> HealthReportScoreRetryResult {
        throw HealthReportCompletionTestError.unexpectedCall
    }

    func queries() -> [Query] { recordedQueries }
}

private actor HealthReportDashboardReviewRepositorySpy: HealthReportReviewRepositoryProtocol {
    private let interpretation: HealthReportInterpretation
    private var interpretationRequests = 0

    init(interpretation: HealthReportInterpretation) {
        self.interpretation = interpretation
    }

    func fetchReportInterpretation(
        workflowID: Int,
        subjectUserID: Int
    ) async throws -> HealthReportInterpretation {
        interpretationRequests += 1
        return interpretation
    }

    func fetchReportReview(workflowID: Int, subjectUserID: Int) async throws -> HealthReportReview {
        throw HealthReportCompletionTestError.unexpectedCall
    }

    func confirmReport(
        workflowID: Int,
        request: HealthReportConfirmationRequest,
        expectedAccountScope: String
    ) async throws -> HealthReportReview {
        throw HealthReportCompletionTestError.unexpectedCall
    }

    func addManualReportCandidate(
        workflowID: Int,
        request: HealthReportManualCandidateRequest,
        expectedAccountScope: String
    ) async throws -> HealthReportReview {
        throw HealthReportCompletionTestError.unexpectedCall
    }

    func interpretationRequestCount() -> Int { interpretationRequests }
}

private enum HealthReportCompletionTestError: Error {
    case unexpectedCall
}
