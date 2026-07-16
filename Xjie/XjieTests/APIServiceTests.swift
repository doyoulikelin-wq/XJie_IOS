import Foundation
import XCTest
@testable import Xjie

final class APIServiceTests: XCTestCase {
    #if DEBUG
    func testUIAutomationChatTransportRequiresExactExplicitDebugFlag() {
        XCTAssertTrue(UIAutomationChatAPIService.isEnabled(arguments: [
            "XJIE_DISABLE_APP_UPDATE_CHECK",
            UIAutomationChatAPIService.launchArgument
        ]))
        XCTAssertFalse(UIAutomationChatAPIService.isEnabled(arguments: []))
        XCTAssertFalse(UIAutomationChatAPIService.isEnabled(arguments: [
            "XJIE_UI_TEST_STUB_CHAT_EXTRA"
        ]))
    }

    func testUIAutomationChatTransportReturnsPromptBoundResponseWithoutNetwork() async throws {
        let service = UIAutomationChatAPIService()
        let request = ChatRequest(
            message: "帮我整理病史摘要",
            thread_id: nil,
            client_message_id: "message-123"
        )

        let before = UIAutomationNetworkAudit.shared.snapshot()
        let stream = try await service.postChatStream(request, timeout: 0.01)
        var events: [ChatStreamEvent] = []
        for try await event in stream {
            events.append(event)
        }

        XCTAssertEqual(events.count, 1)
        guard case .done(let response) = try XCTUnwrap(events.first) else {
            return XCTFail("UI 自动化传输应直接结束为 done 响应")
        }
        XCTAssertEqual(response.summary, "UI 自动化回复：帮我整理病史摘要")
        XCTAssertEqual(response.thread_id, "ui-automation-thread")
        XCTAssertEqual(response.message_id, "ui-automation-message-123")
        XCTAssertEqual(response.response_state, "complete")
        let after = UIAutomationNetworkAudit.shared.snapshot()
        XCTAssertEqual(after.intercepted, before.intercepted + 1)
        XCTAssertEqual(after.unhandled, before.unhandled)
    }

    func testUIAutomationChatTransportAuditsExactRoutesAndFailsClosed() async throws {
        let service = UIAutomationChatAPIService()
        let before = UIAutomationNetworkAudit.shared.snapshot()

        let conversations: [ChatConversation] = try await service.get(
            "/api/chat/conversations?limit=20&offset=0",
            timeout: 0.01
        )
        XCTAssertTrue(conversations.isEmpty)
        let detailMessages: [ChatMessage] = try await service.get(
            "/api/chat/conversations/thread-1",
            timeout: 0.01
        )
        XCTAssertTrue(detailMessages.isEmpty)
        XCTAssertTrue(UIAutomationChatAPIService.isSupportedConversationGET(
            "/api/chat/conversations/thread-1"
        ))
        XCTAssertFalse(UIAutomationChatAPIService.isSupportedConversationGET(
            "/api/chat/conversations-unknown"
        ))
        for invalidPath in [
            "/api/chat/conversations?",
            "/api/chat/conversations?limit=-1",
            "/api/chat/conversations?limit=abc",
            "/api/chat/conversations?limit=20&limit=10",
            "/api/chat/conversations?offset",
            "/api/chat/conversations/thread-1?limit=20"
        ] {
            XCTAssertFalse(
                UIAutomationChatAPIService.isSupportedConversationGET(invalidPath),
                "聊天 UI 替身必须拒绝非法分页或详情查询：\(invalidPath)"
            )
        }

        let afterHandled = UIAutomationNetworkAudit.shared.snapshot()
        XCTAssertEqual(afterHandled.intercepted, before.intercepted + 2)
        XCTAssertEqual(afterHandled.unhandled, before.unhandled)

        do {
            let _: [ChatConversation] = try await service.get(
                "/api/chat/conversations-unknown",
                timeout: 0.01
            )
            XCTFail("同前缀的未知聊天路由必须失败")
        } catch {
            XCTAssertTrue(error.localizedDescription.contains("unsupported request"))
        }
        let afterUnknownGet = UIAutomationNetworkAudit.shared.snapshot()
        XCTAssertEqual(afterUnknownGet.intercepted, afterHandled.intercepted + 1)
        XCTAssertEqual(afterUnknownGet.unhandled, afterHandled.unhandled + 1)

        let swallowed: [ChatConversation]? = try? await service.post(
            "/api/chat/conversations",
            body: nil,
            timeout: 0.01
        )
        XCTAssertNil(swallowed)
        let afterSwallowedError = UIAutomationNetworkAudit.shared.snapshot()
        XCTAssertEqual(afterSwallowedError.intercepted, afterUnknownGet.intercepted + 1)
        XCTAssertEqual(afterSwallowedError.unhandled, afterUnknownGet.unhandled + 1)
    }

    func testUIAutomationNetworkStubRequiresExactExplicitDebugFlag() {
        XCTAssertTrue(UIAutomationNetworkStubURLProtocol.isEnabled(arguments: [
            "XJIE_DISABLE_APP_UPDATE_CHECK",
            UIAutomationNetworkStubURLProtocol.launchArgument
        ]))
        XCTAssertFalse(UIAutomationNetworkStubURLProtocol.isEnabled(arguments: []))
        XCTAssertFalse(UIAutomationNetworkStubURLProtocol.isEnabled(arguments: [
            "XJIE_UI_TEST_STUB_NETWORK_EXTRA"
        ]))

        let productionRequest = URLRequest(
            url: URL(string: "https://www.jianjieaitech.com/api/feature-flags")!
        )
        XCTAssertTrue(UIAutomationNetworkStubURLProtocol.shouldIntercept(
            productionRequest,
            arguments: [UIAutomationNetworkStubURLProtocol.launchArgument]
        ))
        XCTAssertFalse(UIAutomationNetworkStubURLProtocol.shouldIntercept(
            productionRequest,
            arguments: []
        ))
        for rawURL in [
            "ftp://example.invalid/private",
            "file:///tmp/ui-automation-private",
            "custom-scheme://example.invalid/private",
            "wss://example.invalid/socket"
        ] {
            let request = URLRequest(url: URL(string: rawURL)!)
            XCTAssertTrue(UIAutomationNetworkStubURLProtocol.canInit(with: request))
            XCTAssertTrue(UIAutomationNetworkStubURLProtocol.shouldIntercept(
                request,
                arguments: [UIAutomationNetworkStubURLProtocol.launchArgument]
            ))
            XCTAssertFalse(UIAutomationNetworkStubURLProtocol.shouldIntercept(
                request,
                arguments: []
            ))
            XCTAssertFalse(UIAutomationNetworkStubURLProtocol.stubbedResponse(for: request).handled)
        }

        let stubbedClasses = APIService.makeSessionConfiguration(
            arguments: [UIAutomationMode.launchArgument]
        ).protocolClasses ?? []
        XCTAssertTrue(stubbedClasses.contains {
            ObjectIdentifier($0) == ObjectIdentifier(UIAutomationNetworkStubURLProtocol.self)
        })

        let productionClasses = APIService.makeSessionConfiguration(arguments: []).protocolClasses ?? []
        XCTAssertFalse(productionClasses.contains {
            ObjectIdentifier($0) == ObjectIdentifier(UIAutomationNetworkStubURLProtocol.self)
        })
    }

    func testUIAutomationNetworkStubReturnsDeterministicKnownFixturesAndFailsClosed() async throws {
        func request(
            _ path: String,
            origin: String = "https://www.jianjieaitech.com",
            method: String = "GET",
            authorization: String? = "Bearer \(AuthManager.uiValidationToken)"
        ) throws -> URLRequest {
            var request = URLRequest(url: try XCTUnwrap(URL(string: "\(origin)\(path)")))
            request.httpMethod = method
            if let authorization {
                request.setValue(authorization, forHTTPHeaderField: "Authorization")
            }
            return request
        }

        func fixture(_ path: String) throws -> UIAutomationNetworkStubURLProtocol.StubbedResponse {
            UIAutomationNetworkStubURLProtocol.stubbedResponse(for: try request(path))
        }

        let medication = try fixture("/api/medications")
        XCTAssertEqual(medication.statusCode, 200)
        XCTAssertTrue(medication.handled)
        XCTAssertEqual(
            try JSONDecoder().decode(MedicationListResponse.self, from: medication.data).items,
            []
        )
        let medicationToday = try JSONDecoder().decode(
            MedicationTodaySummary.self,
            from: fixture(
                "/api/medications/trust/today?local_date=2026-07-15&timezone_offset_minutes=480"
            ).data
        )
        XCTAssertEqual(medicationToday.subject_user_id, 1)
        XCTAssertEqual(medicationToday.local_date, "2026-07-15")
        XCTAssertEqual(medicationToday.tasks, [])
        XCTAssertEqual(medicationToday.missed_assertion_policy, "elapsed_time_never_confirms_missed")
        let subjectBoundMedicationToday = try JSONDecoder().decode(
            MedicationTodaySummary.self,
            from: fixture(
                "/api/medications/trust/today?subject_user_id=1&local_date=2026-07-15&timezone_offset_minutes=-420"
            ).data
        )
        XCTAssertEqual(subjectBoundMedicationToday.subject_user_id, 1)
        let medicationPlans = try JSONDecoder().decode(
            TrustedMedicationPlanList.self,
            from: fixture("/api/medications/trust/plans?subject_user_id=1").data
        )
        XCTAssertEqual(medicationPlans.subject_user_id, 1)
        XCTAssertEqual(medicationPlans.items.count, 1)
        XCTAssertEqual(medicationPlans.items.first?.plan_id, 7)
        XCTAssertEqual(medicationPlans.items.first?.trust_state, "user_confirmed")
        XCTAssertEqual(medicationPlans.items.first?.reminder_management, "client_managed")
        XCTAssertEqual(medicationPlans.items.first?.reminder_default_enabled, false)
        XCTAssertEqual(medicationPlans.items.first?.server_notification_scheduled, false)
        XCTAssertEqual(
            try JSONDecoder().decode(
                MedicationPrefillList.self,
                from: fixture("/api/medications/trust/prefill-candidates?subject_user_id=1").data
            ),
            MedicationPrefillList(subject_user_id: 1, items: [])
        )
        XCTAssertEqual(
            try JSONDecoder().decode(
                MedicationReactionList.self,
                from: fixture("/api/medications/trust/reactions?subject_user_id=1").data
            ),
            MedicationReactionList(subject_user_id: 1, items: [])
        )

        let anonymousSubjects = UIAutomationNetworkStubURLProtocol.stubbedResponse(
            for: try request("/api/auth/subjects", authorization: nil)
        )
        XCTAssertEqual(anonymousSubjects.statusCode, 200)
        XCTAssertTrue(anonymousSubjects.handled)
        XCTAssertEqual(
            try JSONDecoder().decode([SubjectItem].self, from: anonymousSubjects.data).count,
            0
        )
        XCTAssertEqual(
            try JSONDecoder().decode(
                FeatureFlagClientResponse.self,
                from: fixture("/api/feature-flags").data
            ).flags,
            [:]
        )
        let probe = UIAutomationNetworkStubURLProtocol.stubbedResponse(
            for: try request(
                "/api/feature-flags",
                origin: "https://ui-automation.invalid",
                authorization: nil
            )
        )
        XCTAssertEqual(probe.statusCode, 200)
        XCTAssertTrue(probe.handled)
        XCTAssertEqual(
            try JSONDecoder().decode(UserInfo.self, from: fixture("/api/users/me").data).id,
            "1"
        )
        XCTAssertEqual(
            try JSONDecoder().decode(
                [FamilyGroup].self,
                from: fixture("/api/family/groups").data
            ).count,
            0
        )
        XCTAssertEqual(
            try JSONDecoder().decode(
                [FamilyMember].self,
                from: fixture("/api/family/members").data
            ).count,
            0
        )
        XCTAssertEqual(
            try JSONDecoder().decode(
                [FamilySubject].self,
                from: fixture("/api/family/subjects").data
            ).count,
            0
        )
        XCTAssertEqual(
            try JSONDecoder().decode(
                [ChatConversation].self,
                from: fixture("/api/chat/conversations?limit=20&offset=0").data
            ).count,
            0
        )
        let reportHistory = try JSONDecoder().decode(
            HealthReportHistoryResponse.self,
            from: fixture(
                "/api/health-data/report-workflows?subject_user_id=1&date_from=2026-07-01&date_to=2026-07-31&hospital=%E5%8D%8F%E5%92%8C%E5%8C%BB%E9%99%A2&report_type=exam"
            ).data
        )
        XCTAssertEqual(reportHistory.items.map(\.workflow_id), [4242])
        XCTAssertEqual(reportHistory.items.first?.status, "awaiting_confirmation")
        let reportTrace = try JSONDecoder().decode(
            HealthReportTrace.self,
            from: fixture(
                "/api/health-data/report-workflows/4242/trace?subject_user_id=1"
            ).data
        )
        XCTAssertEqual(reportTrace.workflow.status, "awaiting_confirmation")
        XCTAssertEqual(reportTrace.assets.map(\.id), [5])
        XCTAssertEqual(reportTrace.locators.map(\.candidate_id), [101])
        XCTAssertTrue(reportTrace.confirmation_events.isEmpty, "待确认 fixture 不得伪造未来确认事件")
        let traceAsset = try fixture(
            "/api/health-data/report-workflows/4242/assets/5/content?subject_user_id=1"
        )
        XCTAssertTrue(traceAsset.handled)
        XCTAssertGreaterThan(traceAsset.data.count, 8)
        let reportDocuments = try JSONDecoder().decode(
            DocumentListResponse.self,
            from: fixture("/api/health-data/documents?doc_type=exam").data
        )
        XCTAssertEqual(reportDocuments.items?.count, 2)
        XCTAssertEqual(reportDocuments.items?.first?.reportWorkflowRoute?.workflowID, 4242)
        let workflowDocument = try XCTUnwrap(reportDocuments.items?.first)
        guard case .review(let medicalRoute) = MedicalAssistantRoutingContract.destination(for: workflowDocument) else {
            return XCTFail("有 workflow 的就医资料必须进入字段复核，而不是 legacy 详情")
        }
        XCTAssertEqual(medicalRoute.workflowID, 4242)
        let legacyDocument = try XCTUnwrap(reportDocuments.items?.last)
        XCTAssertEqual(
            MedicalAssistantRoutingContract.destination(for: legacyDocument),
            .legacyDetail(documentID: legacyDocument.id)
        )
        XCTAssertEqual(MedicalAssistantRoutingContract.title, "就医助手")
        XCTAssertEqual(reportDocuments.items?.first?.hospital, "协和医院")
        XCTAssertEqual(reportDocuments.items?.first?.created_at, "2026-07-15T08:00:00Z")
        XCTAssertEqual(reportDocuments.items?.last?.reportTrustState, .legacyUnverified)
        let reportReview = try JSONDecoder().decode(
            HealthReportReview.self,
            from: fixture("/api/health-data/report-workflows/4242/review?subject_user_id=1").data
        )
        XCTAssertEqual(reportReview.status, .awaitingConfirmation)
        XCTAssertEqual(reportReview.candidates.first?.conflict_reasons, ["unit_conflict"])
        let reportInterpretation = try JSONDecoder().decode(
            HealthReportInterpretation.self,
            from: fixture(
                "/api/health-data/report-workflows/4242/interpretation?subject_user_id=1"
            ).data
        )
        XCTAssertTrue(reportInterpretation.available)
        XCTAssertTrue(reportInterpretation.score_pending)
        XCTAssertEqual(reportInterpretation.score_state, "partial_failed")
        XCTAssertEqual(reportInterpretation.major_abnormalities.map(\.canonical_name), ["空腹血糖"])
        XCTAssertEqual(reportInterpretation.profile_impacts.map(\.profile_candidate_id), [301, 301])
        XCTAssertEqual(reportInterpretation.score_snapshots.first?.before_value, 58)
        XCTAssertEqual(reportInterpretation.score_snapshots.first?.after_value, 54)
        XCTAssertTrue(reportInterpretation.follow_up.items.isEmpty)
        XCTAssertTrue(reportInterpretation.follow_up.unavailable_reason?.contains("不会") == true)
        XCTAssertEqual(
            reportInterpretation.originalFileURL,
            "/api/health-data/documents/4242/file"
        )
        let originalFixture = try fixture("/api/health-data/documents/4242/file")
        XCTAssertTrue(originalFixture.handled)
        XCTAssertGreaterThan(originalFixture.data.count, 8)
        let profile = try JSONDecoder().decode(
            HealthProfileTrustResponse.self,
            from: fixture("/api/health-data/profile-trust").data
        )
        XCTAssertEqual(profile.subject_user_id, 1)
        XCTAssertEqual(profile.overview.pending_update_count, 1)
        XCTAssertEqual(profile.candidates.first?.version, 2)
        XCTAssertEqual(profile.facts.first?.sources.first?.source_type, "manual")
        XCTAssertEqual(profile.overview.primary_action?.kind, "review_updates")
        XCTAssertEqual(profile.overview.primary_action?.item_count, 1)
        XCTAssertEqual(profile.overview.primary_action?.route, "profile_updates")
        XCTAssertEqual(profile.goals.map(\.goal_id), [701])
        XCTAssertEqual(profile.goals.first?.metrics.map(\.metric_key), ["sleep_duration", "hrv"])

        let medicationSummary = try JSONDecoder().decode(
            HealthProfileLongTermMedicationSummary.self,
            from: fixture(
                "/api/medications/trust/long-term-summary?subject_user_id=1"
            ).data
        )
        let summaryItem = try XCTUnwrap(medicationSummary.items.first)
        XCTAssertEqual(
            summaryItem.displayFields.map(\.key),
            HealthProfileMedicationSummaryFieldKey.allCases,
            "画像长期用药摘要必须只渲染服务端批准的六个字段"
        )
        XCTAssertFalse(
            summaryItem.displayFields.map(\.key.rawValue).contains(where: {
                ["dose", "dose_text", "reminder", "schedule_times"].contains($0)
            })
        )
        let factHistory = try JSONDecoder().decode(
            HealthProfileRevisionList.self,
            from: fixture(
                "/api/health-data/profile-trust/facts/201/revisions?subject_user_id=1&limit=50"
            ).data
        )
        XCTAssertEqual(factHistory.target_kind, .fact)
        XCTAssertEqual(factHistory.items.map(\.target_version), [2])
        let goalHistory = try JSONDecoder().decode(
            HealthProfileRevisionList.self,
            from: fixture(
                "/api/health-data/profile-trust/goals/701/revisions?subject_user_id=1&limit=50"
            ).data
        )
        XCTAssertEqual(goalHistory.target_kind, .goal)
        XCTAssertEqual(goalHistory.items.map(\.event_type), ["created"])

        var createGoalRequest = try request(
            "/api/health-data/profile-trust/goals",
            method: "POST"
        )
        createGoalRequest.httpBody = Data(#"{"subject_user_id":1,"client_event_id":"goal-create-1","name":"提高日均步数","started_on":"2026-07-15","metrics":[{"metric_key":"steps","display_label":"步数"}]}"#.utf8)
        let createdGoalResponse = UIAutomationNetworkStubURLProtocol.stubbedResponse(
            for: createGoalRequest
        )
        XCTAssertTrue(createdGoalResponse.handled)
        XCTAssertEqual(
            try JSONDecoder().decode(
                HealthProfileTrustResponse.self,
                from: createdGoalResponse.data
            ).goals.map(\.goal_id),
            [701, 702],
            "专用目标端点必须支持多个并存的用户目标"
        )

        var updateGoalRequest = try request(
            "/api/health-data/profile-trust/goals/701",
            method: "PATCH"
        )
        updateGoalRequest.httpBody = Data(#"{"subject_user_id":1,"client_event_id":"goal-update-1","expected_version":3,"name":"改善睡眠质量","started_on":"2026-07-01","metrics":[{"metric_key":"sleep_duration","display_label":"睡眠时长"},{"metric_key":"hrv","display_label":"HRV"}]}"#.utf8)
        let updatedGoalResponse = UIAutomationNetworkStubURLProtocol.stubbedResponse(
            for: updateGoalRequest
        )
        XCTAssertTrue(updatedGoalResponse.handled)
        XCTAssertEqual(
            try JSONDecoder().decode(
                HealthProfileTrustResponse.self,
                from: updatedGoalResponse.data
            ).goals.first?.version,
            4
        )

        var goalStatusRequest = try request(
            "/api/health-data/profile-trust/goals/701/status",
            method: "POST"
        )
        goalStatusRequest.httpBody = Data(#"{"subject_user_id":1,"client_event_id":"goal-pause-1","expected_version":3,"action":"pause"}"#.utf8)
        XCTAssertTrue(
            UIAutomationNetworkStubURLProtocol.stubbedResponse(for: goalStatusRequest).handled
        )

        var validConfirmation = try request(
            "/api/health-data/report-workflows/4242/confirm",
            method: "POST"
        )
        let validConfirmationBody = Data(#"{"subject_user_id":1,"client_event_id":"ui-test-event","workflow_version":3,"decisions":[{"candidate_id":101,"candidate_version":1,"action":"confirm"}]}"#.utf8)
        validConfirmation.httpBody = validConfirmationBody
        let confirmedFixture = UIAutomationNetworkStubURLProtocol.stubbedResponse(for: validConfirmation)
        XCTAssertTrue(confirmedFixture.handled)
        XCTAssertEqual(
            try JSONDecoder().decode(HealthReportReview.self, from: confirmedFixture.data).status,
            .completedScorePending
        )
        var streamedConfirmation = try request(
            "/api/health-data/report-workflows/4242/confirm",
            method: "POST"
        )
        streamedConfirmation.httpBodyStream = InputStream(data: validConfirmationBody)
        let streamedConfirmationFixture = UIAutomationNetworkStubURLProtocol.stubbedResponse(for: streamedConfirmation)
        XCTAssertTrue(
            streamedConfirmationFixture.handled,
            "URLProtocol may expose a valid JSON body as httpBodyStream; the deterministic stub must validate it without allowing unknown payloads"
        )

        let unknown = try fixture("/api/unexpected")
        XCTAssertEqual(unknown.statusCode, 418)
        XCTAssertFalse(unknown.handled)
        let detail = try JSONDecoder().decode([String: String].self, from: unknown.data)["detail"]
        XCTAssertEqual(
            detail,
            "Unstubbed UI automation request: GET https://www.jianjieaitech.com/api/unexpected"
        )

        var probeWithBody = try request(
            "/api/feature-flags",
            origin: "https://ui-automation.invalid",
            authorization: nil
        )
        probeWithBody.httpBody = Data("unexpected".utf8)
        var anonymousSubjectsWithBody = try request(
            "/api/auth/subjects",
            authorization: nil
        )
        anonymousSubjectsWithBody.httpBody = Data("unexpected".utf8)
        var anonymousSubjectsWithBodyStream = try request(
            "/api/auth/subjects",
            authorization: nil
        )
        anonymousSubjectsWithBodyStream.httpBodyStream = InputStream(
            data: Data("unexpected".utf8)
        )
        var medicationTodayWithBody = try request(
            "/api/medications/trust/today?local_date=2026-07-15&timezone_offset_minutes=480"
        )
        medicationTodayWithBody.httpBody = Data("unexpected".utf8)
        var medicationPlansWithBodyStream = try request(
            "/api/medications/trust/plans?subject_user_id=1"
        )
        medicationPlansWithBodyStream.httpBodyStream = InputStream(data: Data("unexpected".utf8))
        var reportHistoryWithBody = try request(
            "/api/health-data/report-workflows?subject_user_id=1"
        )
        reportHistoryWithBody.httpBody = Data("unexpected".utf8)
        var reportTraceWithBody = try request(
            "/api/health-data/report-workflows/4242/trace?subject_user_id=1"
        )
        reportTraceWithBody.httpBody = Data("unexpected".utf8)
        var reportAssetWithBody = try request(
            "/api/health-data/report-workflows/4242/assets/5/content?subject_user_id=1"
        )
        reportAssetWithBody.httpBody = Data("unexpected".utf8)
        let malformedKnownRequests = [
            try request("/api/medications", origin: "https://wrong.example"),
            try request("/api/medications", origin: "http://www.jianjieaitech.com"),
            try request("/api/medications", authorization: nil),
            try request("/api/medications", authorization: "Bearer   "),
            try request("/api/medications", authorization: "Bearer wrong-token"),
            try request(
                "/api/medications",
                authorization: "Bearer \(AuthManager.uiValidationToken) "
            ),
            try request("/api/auth/subjects"),
            try request("/api/auth/subjects?unexpected=1", authorization: nil),
            try request("/api/auth/subjects", method: "POST", authorization: nil),
            anonymousSubjectsWithBody,
            anonymousSubjectsWithBodyStream,
            try request("/api/medications?unexpected=1"),
            try request("/api/medications", method: "POST"),
            try request("/api/medications/trust/today"),
            try request("/api/medications/trust/today?local_date=2026-07-15"),
            try request("/api/medications/trust/today?timezone_offset_minutes=480"),
            try request(
                "/api/medications/trust/today?local_date=2026-02-30&timezone_offset_minutes=480"
            ),
            try request(
                "/api/medications/trust/today?local_date=2026-07-15&timezone_offset_minutes=841"
            ),
            try request(
                "/api/medications/trust/today?local_date=2026-07-15&timezone_offset_minutes=abc"
            ),
            try request(
                "/api/medications/trust/today?subject_user_id=2&local_date=2026-07-15&timezone_offset_minutes=480"
            ),
            try request(
                "/api/medications/trust/today?subject_user_id=1&subject_user_id=1&local_date=2026-07-15&timezone_offset_minutes=480"
            ),
            try request(
                "/api/medications/trust/today?local_date=2026-07-15&timezone_offset_minutes=480&unexpected=1"
            ),
            medicationTodayWithBody,
            try request("/api/medications/trust/plans"),
            try request("/api/medications/trust/plans?subject_user_id=2"),
            try request("/api/medications/trust/plans?subject_user_id=1&unexpected=1"),
            medicationPlansWithBodyStream,
            try request("/api/medications/trust/prefill-candidates"),
            try request("/api/medications/trust/prefill-candidates?subject_user_id=2"),
            try request("/api/medications/trust/reactions"),
            try request("/api/medications/trust/reactions?subject_user_id=2"),
            try request("/api/medications/trust/long-term-summary"),
            try request("/api/medications/trust/long-term-summary?subject_user_id=2"),
            try request("/api/chat/conversations?limit=0&offset=0"),
            try request("/api/chat/conversations?limit=-1"),
            try request("/api/chat/conversations?limit=abc"),
            try request("/api/chat/conversations?limit=20&limit=10"),
            try request("/api/health-data/documents"),
            try request("/api/health-data/documents?doc_type=other"),
            try request("/api/health-data/documents?doc_type=exam&doc_type=record"),
            try request("/api/health-data/report-workflows"),
            try request("/api/health-data/report-workflows?subject_user_id=2"),
            try request("/api/health-data/report-workflows?subject_user_id=1&subject_user_id=1"),
            try request("/api/health-data/report-workflows?subject_user_id=1&date_from=2026-02-30"),
            try request("/api/health-data/report-workflows?subject_user_id=1&date_from=2026-07-31&date_to=2026-07-01"),
            try request("/api/health-data/report-workflows?subject_user_id=1&hospital=%20%20"),
            try request("/api/health-data/report-workflows?subject_user_id=1&report_type=diagnosis"),
            try request("/api/health-data/report-workflows?subject_user_id=1&unexpected=1"),
            reportHistoryWithBody,
            try request("/api/health-data/report-workflows/4242/trace"),
            try request("/api/health-data/report-workflows/4242/trace?subject_user_id=2"),
            try request("/api/health-data/report-workflows/4243/trace?subject_user_id=1"),
            reportTraceWithBody,
            try request("/api/health-data/report-workflows/4242/assets/5/content"),
            try request("/api/health-data/report-workflows/4242/assets/5/content?subject_user_id=2"),
            try request("/api/health-data/report-workflows/4242/assets/6/content?subject_user_id=1"),
            reportAssetWithBody,
            try request("/api/health-data/report-workflows/4242/review?subject_user_id=2"),
            try request("/api/health-data/report-workflows/4242/review"),
            try request("/api/health-data/report-workflows/4243/review?subject_user_id=1"),
            try request("/api/health-data/report-workflows/4242/interpretation?subject_user_id=2"),
            try request("/api/health-data/report-workflows/4242/interpretation"),
            try request("/api/health-data/report-workflows/4243/interpretation?subject_user_id=1"),
            try request("/api/health-data/profile-trust?subject_user_id=1"),
            try request("/api/health-data/profile-trust/candidates/302/review", method: "POST"),
            try request("/api/health-data/profile-trust/facts/202/retract", method: "POST"),
            try request("/api/health-data/profile-trust/facts/201/revisions"),
            try request(
                "/api/health-data/profile-trust/facts/201/revisions?subject_user_id=1&limit=0"
            ),
            try request(
                "/api/health-data/profile-trust/goals/701/revisions?subject_user_id=2&limit=50"
            ),
            try request(
                "/api/health-data/profile-trust/goals/701/revisions?subject_user_id=1&limit=50&after_revision_id=0"
            ),
            try request(
                "/api/feature-flags",
                origin: "https://ui-automation.invalid",
                authorization: "Bearer \(AuthManager.uiValidationToken)"
            ),
            probeWithBody,
            try request(
                "/api/feature-flags?unexpected=1",
                origin: "https://ui-automation.invalid",
                authorization: nil
            )
        ]
        for malformed in malformedKnownRequests {
            let response = UIAutomationNetworkStubURLProtocol.stubbedResponse(for: malformed)
            XCTAssertEqual(response.statusCode, 418)
            XCTAssertFalse(response.handled)
        }

        let session = URLSession(configuration: APIService.makeSessionConfiguration(
            arguments: [UIAutomationMode.launchArgument]
        ))
        defer { session.invalidateAndCancel() }
        let beforeKnownRequest = UIAutomationNetworkAudit.shared.snapshot()
        let (interceptedData, interceptedResponse) = try await session.data(
            for: try request("/api/medications")
        )
        XCTAssertEqual((interceptedResponse as? HTTPURLResponse)?.statusCode, 200)
        XCTAssertEqual(
            try JSONDecoder().decode(MedicationListResponse.self, from: interceptedData).items,
            []
        )
        let afterKnownRequest = UIAutomationNetworkAudit.shared.snapshot()
        XCTAssertEqual(afterKnownRequest.intercepted, beforeKnownRequest.intercepted + 1)
        XCTAssertEqual(afterKnownRequest.unhandled, beforeKnownRequest.unhandled)

        let (_, unexpectedResponse) = try await session.data(
            for: try request("/api/unexpected")
        )
        XCTAssertEqual((unexpectedResponse as? HTTPURLResponse)?.statusCode, 418)
        let afterUnexpectedRequest = UIAutomationNetworkAudit.shared.snapshot()
        XCTAssertEqual(afterUnexpectedRequest.intercepted, afterKnownRequest.intercepted + 1)
        XCTAssertEqual(afterUnexpectedRequest.unhandled, afterKnownRequest.unhandled + 1)
    }

    @MainActor
    func testUIAutomationModeDisablesNondeterministicSystemDependencies() {
        let enabled = [UIAutomationMode.launchArgument]
        XCTAssertFalse(NotificationScheduler.shouldUseNotificationCenter(arguments: enabled))
        XCTAssertFalse(NotificationScheduler.shouldRequestPermission(arguments: enabled))
        XCTAssertFalse(PushNotificationManager.shouldUseNotificationCenter(arguments: enabled))
        XCTAssertNil(PushNotificationManager.notificationCenter(arguments: enabled))
        XCTAssertFalse(AppDelegate.shouldConfigureSystemServices(
            arguments: enabled,
            isUnitTestHost: false
        ))
        XCTAssertFalse(AppDelegate.shouldConfigureSystemServices(
            arguments: [],
            isUnitTestHost: true
        ))
        XCTAssertFalse(NetworkMonitor.shouldStartPathMonitor(arguments: enabled))
        XCTAssertFalse(AppleHealthSyncViewModel.shouldUseHealthKit(arguments: enabled))

        XCTAssertTrue(NotificationScheduler.shouldUseNotificationCenter(arguments: []))
        XCTAssertTrue(NotificationScheduler.shouldRequestPermission(arguments: []))
        XCTAssertTrue(PushNotificationManager.shouldUseNotificationCenter(arguments: []))
        XCTAssertTrue(AppDelegate.shouldConfigureSystemServices(
            arguments: [],
            isUnitTestHost: false
        ))
        XCTAssertTrue(NetworkMonitor.shouldStartPathMonitor(arguments: []))
        XCTAssertTrue(AppleHealthSyncViewModel.shouldUseHealthKit(arguments: []))

        let localURL = FileManager.default.temporaryDirectory
            .appendingPathComponent("xjie-local-file-loader-\(UUID().uuidString)")
        let localPayload = Data("local-only".utf8)
        defer { try? FileManager.default.removeItem(at: localURL) }
        do {
            try localPayload.write(to: localURL, options: .atomic)
            XCTAssertEqual(try LocalFileDataLoader.read(localURL), localPayload)
        } catch {
            XCTFail("Local file loader should read a real file URL: \(error)")
        }
        let remoteURL = try! XCTUnwrap(URL(string: "https://example.invalid/not-a-file"))
        XCTAssertThrowsError(try LocalFileDataLoader.read(remoteURL)) { error in
            XCTAssertEqual((error as? URLError)?.code, .unsupportedURL)
        }
    }
    #endif

    func testForegroundSessionDoesNotWaitIndefinitelyForConnectivity() {
        XCTAssertFalse(APIService.shared.trustedSession.configuration.waitsForConnectivity)
    }

    func testAuth401DoesNotAttemptTokenRefresh() {
        XCTAssertFalse(APIService.shouldAttemptTokenRefresh(path: "/api/auth/login", statusCode: 401, retried: false))
        XCTAssertFalse(APIService.shouldAttemptTokenRefresh(path: "/api/auth/signup", statusCode: 401, retried: false))
        XCTAssertFalse(APIService.shouldAttemptTokenRefresh(path: "/api/auth/password/reset/request", statusCode: 401, retried: false))
        XCTAssertFalse(APIService.shouldAttemptTokenRefresh(path: "/api/auth/login?source=ios", statusCode: 401, retried: false))
    }

    func testProtected401AttemptsTokenRefreshOnce() {
        XCTAssertTrue(APIService.shouldAttemptTokenRefresh(path: "/api/health-data/summary", statusCode: 401, retried: false))
        XCTAssertTrue(APIService.shouldAttemptTokenRefresh(path: "/api/auth/password/change", statusCode: 401, retried: false))
        XCTAssertFalse(APIService.shouldAttemptTokenRefresh(path: "/api/health-data/summary", statusCode: 401, retried: true))
    }

    func testNon401DoesNotAttemptTokenRefresh() {
        XCTAssertFalse(APIService.shouldAttemptTokenRefresh(path: "/api/health-data/summary", statusCode: 400, retried: false))
        XCTAssertFalse(APIService.shouldAttemptTokenRefresh(path: "/api/health-data/summary", statusCode: 500, retried: false))
    }

    func testAccountBoundRetryNeverAdoptsTokenFromAnotherAccount() {
        let decision = APIService.accountBoundRetryDecision(
            expectedAccountScope: "account-a",
            originalToken: "old-a-token",
            current: APIService.AccountBoundAuthSnapshot(
                token: "new-b-token",
                accountScope: "account-b"
            )
        )

        XCTAssertEqual(decision, .abort)
        XCTAssertFalse(APIService.shouldContinueAccountBoundRequest(
            expectedAccountScope: "account-a",
            currentAccountScope: "account-b"
        ))
        XCTAssertFalse(APIService.shouldContinueAccountBoundRequest(
            expectedAccountScope: "account-a",
            currentAccountScope: nil
        ))
    }

    func testAccountBoundRetryCanUseRefreshedTokenOnlyWithinSameAccount() {
        let refreshed = APIService.accountBoundRetryDecision(
            expectedAccountScope: "account-a",
            originalToken: "old-a-token",
            current: APIService.AccountBoundAuthSnapshot(
                token: "new-a-token",
                accountScope: "account-a"
            )
        )
        let needsRefresh = APIService.accountBoundRetryDecision(
            expectedAccountScope: "account-a",
            originalToken: "old-a-token",
            current: APIService.AccountBoundAuthSnapshot(
                token: "old-a-token",
                accountScope: "account-a"
            )
        )

        XCTAssertEqual(refreshed, .retry("new-a-token"))
        XCTAssertEqual(needsRefresh, .refresh)
    }

    func testAccountBoundNetworkAndServerRetriesRequireSameAccountBeforeAndAfterBackoff() throws {
        XCTAssertTrue(APIService.shouldRetryAccountBoundTransport(
            expectedAccountScope: "account-a",
            currentAccountScope: "account-a",
            retryCount: 0
        ))
        XCTAssertFalse(APIService.shouldRetryAccountBoundTransport(
            expectedAccountScope: "account-a",
            currentAccountScope: "account-b",
            retryCount: 0
        ))
        XCTAssertFalse(APIService.shouldRetryAccountBoundTransport(
            expectedAccountScope: "account-a",
            currentAccountScope: nil,
            retryCount: 0
        ))
        XCTAssertFalse(APIService.shouldRetryAccountBoundTransport(
            expectedAccountScope: "account-a",
            currentAccountScope: "account-a",
            retryCount: APIConstants.maxRetries
        ))
        let boundary = "xjie-account-bound-test"
        let multipart = try APIService.makeMultipartBody(
            fileData: Data("ordered-assets".utf8),
            fileName: "page-1.png",
            mimeType: "image/png",
            formData: ["subject_user_id": "1", "page_index": "0"],
            boundary: boundary
        )
        let multipartText = String(decoding: multipart, as: UTF8.self)
        XCTAssertTrue(multipartText.contains("filename=\"page-1.png\""))
        XCTAssertTrue(multipartText.contains("Content-Type: image/png"))
        XCTAssertTrue(multipartText.contains("ordered-assets"))
        XCTAssertTrue(multipartText.hasSuffix("--\(boundary)--\r\n"))
        XCTAssertThrowsError(
            try APIService.makeMultipartBody(
                fileData: Data(),
                fileName: "unsafe\u{0000}name.png",
                mimeType: "image/png",
                formData: [:],
                boundary: boundary
            )
        )
    }

    func testMixedStructuredErrorDetailKeepsMessage() {
        let data = Data(#"{"detail":{"code":"all_values_rejected","message":"没有可写入的设备健康样本","total":2,"issues":[{"index":0,"code":"invalid_value"}]}}"#.utf8)

        XCTAssertEqual(
            APIService.errorMessage(from: data, fallback: "请求失败"),
            "没有可写入的设备健康样本"
        )
    }

    func testAccountBoundHTTPErrorPreservesStructuredResponseBody() {
        let data = Data(#"{"detail":{"code":"all_values_rejected","message":"没有可写入的设备健康样本","total":1,"inserted":0,"updated":0,"unchanged":0,"rejected":1,"skipped":1,"issues":[{"index":0,"code":"invalid_value"}]}}"#.utf8)
        let error = APIError.httpErrorResponse(422, "没有可写入的设备健康样本", data)

        guard case .httpErrorResponse(let statusCode, let message, let body) = error else {
            return XCTFail("account-bound error must preserve its response body")
        }
        XCTAssertEqual(statusCode, 422)
        XCTAssertEqual(message, "没有可写入的设备健康样本")
        XCTAssertEqual(body, data)

        let rejection = DeviceIndicatorSyncRejection.decode(from: body)
        XCTAssertEqual(rejection?.code, "all_values_rejected")
        XCTAssertEqual(rejection?.response.rejected, 1)
        XCTAssertEqual(rejection?.response.issues, [
            DeviceIndicatorSyncIssue(index: 0, code: "invalid_value")
        ])
    }

    func testTrendPointDecodesLegacyResponseWithoutSourceIdentity() throws {
        let data = Data(#"{"indicators":[{"name":"步数","unit":"步","ref_low":null,"ref_high":null,"points":[{"date":"2026-07-11","value":8200,"abnormal":false,"source":"apple_health","measured_at":"2026-07-11T08:00:00Z"}]}]}"#.utf8)

        let response = try JSONDecoder().decode(IndicatorTrendResponse.self, from: data)
        let point = try XCTUnwrap(response.indicators.first?.points.first)

        XCTAssertNil(point.source_metric)
        XCTAssertNil(point.source_id)
        XCTAssertNil(point.value_kind)
        XCTAssertNil(point.display_value)
        XCTAssertNil(point.source_local_date)
        XCTAssertNil(point.timezone_offset_minutes)
        XCTAssertEqual(point.displayDate, "2026-07-11")
        XCTAssertNil(point.preferredDisplayValue)
        XCTAssertFalse(point.isCategoricalValue)
        XCTAssertTrue(IndicatorTrendPresentationContract.shouldDrawContinuousLine(for: response.indicators[0]))
        XCTAssertEqual(point.id, "2026-07-11-apple_health-2026-07-11T08:00:00Z")

        let trend = try XCTUnwrap(response.indicators.first)
        let interactiveSamples = XAgeMetricTrendContract.samples(from: trend)
        XCTAssertEqual(interactiveSamples.count, 1)
        XCTAssertEqual(interactiveSamples.first?.dateLabel, "2026年7月11日")
        XCTAssertEqual(interactiveSamples.first?.displayValue, "8200")
        XCTAssertEqual(XAgeMetricTrendContract.chartWidth(pointCount: 1, viewportWidth: 320), 320)
        XCTAssertGreaterThan(
            XAgeMetricTrendContract.chartWidth(pointCount: 30, viewportWidth: 320),
            320,
            "密集趋势必须获得可横向滚动的内容宽度"
        )
        XCTAssertEqual(
            XAgeMetricTrendContract.nearestIndex(to: interactiveSamples[0].date, in: interactiveSamples),
            0
        )
        XCTAssertEqual(XAgeMetricTrendContract.steppedIndex(currentIndex: 0, pointCount: 3, delta: -1), 0)
        XCTAssertEqual(XAgeMetricTrendContract.steppedIndex(currentIndex: 0, pointCount: 3, delta: 1), 1)
        XCTAssertEqual(XAgeMetricTrendContract.steppedIndex(currentIndex: 2, pointCount: 3, delta: 1), 2)
        XCTAssertNil(XAgeMetricTrendContract.steppedIndex(currentIndex: nil, pointCount: 0, delta: 1))
    }

    func testPatientHistoryLegacyKeysMigrateWithoutSilentDataLoss() throws {
        let legacyProfileData = Data(#"""
        {
          "doctor_summary":"旧资料兼容",
          "sections":{
            "recent_findings":{"value":"HbA1c 7.6%","status":"documented","source_type":"document","source_ref":"report-new","verified_by_user":false},
            "abnormal_findings":{"value":"肝脏脂肪变性","status":"confirmed","source_type":"user","source_ref":"legacy-user","verified_by_user":true},
            "care_goals":{"value":"","status":"documented","source_type":"document","source_ref":"report-empty","verified_by_user":false},
            "current_focus":{"value":"关注餐后血糖","status":"confirmed","source_type":"user","source_ref":null,"verified_by_user":true}
          },
          "key_metrics":[],
          "evidence_overview":{"record_count":0,"exam_count":0},
          "missing_sections":[
            {"key":"current_focus","label":"本次就诊重点关注"},
            {"key":"care_goals","label":"本次就诊重点关注"}
          ],
          "completeness":0.5
        }
        """#.utf8)
        let legacyProfile = try JSONDecoder().decode(PatientHistoryProfile.self, from: legacyProfileData)
        XCTAssertNil(legacyProfile.sections["abnormal_findings"])
        XCTAssertNil(legacyProfile.sections["current_focus"])
        let mergedFindings = try XCTUnwrap(legacyProfile.sections["recent_findings"])
        XCTAssertTrue(mergedFindings.value.contains("HbA1c 7.6%"))
        XCTAssertTrue(mergedFindings.value.contains("肝脏脂肪变性"), "新旧键同时存在时不得静默丢弃旧内容")
        XCTAssertEqual(mergedFindings.status, "pending_review")
        XCTAssertEqual(mergedFindings.source_type, "both")
        XCTAssertFalse(mergedFindings.verified_by_user)
        XCTAssertEqual(legacyProfile.sections["care_goals"]?.value, "关注餐后血糖")
        XCTAssertEqual(legacyProfile.missing_sections.map(\.key), ["care_goals"])
        XCTAssertEqual(PatientHistorySectionCatalog.label(forKey: "current_focus"), "本次就诊重点关注")
        XCTAssertFalse(PatientHistorySectionCatalog.all.map(\.key).contains("abnormal_findings"))
        XCTAssertFalse(PatientHistorySectionCatalog.all.map(\.key).contains("current_focus"))

        let explicitNoneConflict = PatientHistorySectionCatalog.migrateLegacySections([
            "care_goals": PatientHistoryField(status: "none"),
            "current_focus": PatientHistoryField(value: "希望控制餐后血糖", status: "confirmed")
        ])
        XCTAssertEqual(explicitNoneConflict["care_goals"]?.value, "希望控制餐后血糖")
        XCTAssertEqual(explicitNoneConflict["care_goals"]?.status, "pending_review")
        XCTAssertEqual(explicitNoneConflict["care_goals"]?.source_type, "both")

        let writePayload = PatientHistoryProfileIn(
            doctor_summary: legacyProfile.doctor_summary,
            sections: legacyProfile.sections,
            verified_at: legacyProfile.verified_at
        )
        let encodedPayload = try JSONEncoder().encode(writePayload)
        let payloadObject = try XCTUnwrap(JSONSerialization.jsonObject(with: encodedPayload) as? [String: Any])
        let encodedSections = try XCTUnwrap(payloadObject["sections"] as? [String: Any])
        XCTAssertNotNil(encodedSections["recent_findings"])
        XCTAssertNotNil(encodedSections["care_goals"])
        XCTAssertNil(encodedSections["abnormal_findings"], "保存请求不得继续向后端发送旧字段键")
        XCTAssertNil(encodedSections["current_focus"], "保存请求不得继续向后端发送旧字段键")
    }

    func testTrendPointUsesSourceIdentityForSameTimestampSamples() throws {
        let data = Data(#"{"indicators":[{"name":"心率","unit":"bpm","ref_low":null,"ref_high":null,"points":[{"date":"2026-07-11","value":68,"abnormal":false,"source":"apple_health","measured_at":"2026-07-11T08:00:00Z","source_metric":"heartRate","source_id":"sample-a"},{"date":"2026-07-11","value":72,"abnormal":false,"source":"apple_health","measured_at":"2026-07-11T08:00:00Z","source_metric":"heartRate","source_id":"sample-b"}]}]}"#.utf8)

        let response = try JSONDecoder().decode(IndicatorTrendResponse.self, from: data)
        let points = try XCTUnwrap(response.indicators.first?.points)

        XCTAssertEqual(points.map(\.source_metric), ["heartRate", "heartRate"])
        XCTAssertEqual(points.map(\.source_id), ["sample-a", "sample-b"])
        XCTAssertEqual(points.map(\.id), ["apple_health-sample-a", "apple_health-sample-b"])
        XCTAssertEqual(Set(points.map(\.id)).count, 2)
    }

    func testTrendPointDecodesCategoricalDisplayAndSourceLocalDay() throws {
        let data = Data(#"{"indicators":[{"name":"经期","unit":null,"ref_low":null,"ref_high":null,"points":[{"date":"2026-07-10","value":3,"abnormal":false,"source":"apple_health","measured_at":"2026-07-10T16:30:00Z","source_metric":"menstrualFlow","source_id":"sample-period-a","value_kind":"category","display_value":"经量较多","source_local_date":"2026-07-11","timezone_offset_minutes":480}]}]}"#.utf8)

        let response = try JSONDecoder().decode(IndicatorTrendResponse.self, from: data)
        let trend = try XCTUnwrap(response.indicators.first)
        let point = try XCTUnwrap(trend.points.first)

        XCTAssertEqual(point.value_kind, "category")
        XCTAssertEqual(point.display_value, "经量较多")
        XCTAssertEqual(point.source_local_date, "2026-07-11")
        XCTAssertEqual(point.timezone_offset_minutes, 480)
        XCTAssertEqual(point.displayDate, "2026-07-11")
        XCTAssertEqual(point.preferredDisplayValue, "经量较多")
        XCTAssertTrue(point.isCategoricalValue)
        XCTAssertEqual(point.id, "apple_health-sample-period-a")
        XCTAssertFalse(IndicatorTrendPresentationContract.shouldDrawContinuousLine(for: trend))
        XCTAssertEqual(
            IndicatorTrendPresentationContract.displayValue(for: point, indicatorName: trend.name),
            "经量较多"
        )
    }

    @MainActor
    func testReportTrustStateKeepsLegacyDoneUnverifiedAndScorePendingDistinct() async throws {
        let documents = try JSONDecoder().decode([HealthDocument].self, from: Data(#"""
        [
          {"id":"legacy","extraction_status":"done"},
          {"id":"pending-score","extraction_status":"done","report_workflow_id":11,"report_workflow_status":"completed_score_pending","report_subject_user_id":1},
          {"id":"complete","extraction_status":"done","report_workflow_id":12,"report_workflow_status":"completed","report_subject_user_id":1}
        ]
        """#.utf8))

        XCTAssertEqual(documents[0].reportTrustState, .legacyUnverified)
        XCTAssertFalse(documents[0].isAdmittedTrustedReport)
        XCTAssertFalse(documents[0].isTrustedForScoreInputs)
        XCTAssertEqual(documents[1].reportTrustState, .workflow(.completedScorePending))
        XCTAssertTrue(documents[1].isAdmittedTrustedReport)
        XCTAssertFalse(documents[1].isTrustedForScoreInputs, "评分待更新不能伪装成评分流程已完成")
        XCTAssertEqual(documents[2].reportTrustState, .workflow(.completed))
        XCTAssertTrue(documents[2].isAdmittedTrustedReport)
        XCTAssertTrue(documents[2].isTrustedForScoreInputs)

        let historyDocuments = try JSONDecoder().decode([HealthDocument].self, from: Data(#"""
        [
          {"id":"confirmed-date","doc_type":"exam","hospital":"协和医院","doc_date":"2026-07-14","created_at":"2026-07-15T10:00:00Z"},
          {"id":"created-fallback","doc_type":"record","hospital":"协和医院","created_at":"2026-07-15T09:00:00Z"},
          {"id":"unknown-metadata","doc_type":"record","hospital":"   "}
        ]
        """#.utf8))
        let sortedHistory = historyDocuments.sortedForXAgeHistory()
        XCTAssertEqual(sortedHistory.map(\.id), ["created-fallback", "confirmed-date", "unknown-metadata"])
        XCTAssertEqual(
            sortedHistory[0].xAgeHistoryMetadataLabel,
            "\(Utils.formatDate("2026-07-15T09:00:00Z")) · 协和医院 · 病历"
        )
        XCTAssertEqual(sortedHistory[2].xAgeHistoryMetadataLabel, "日期待确认 · 医院待确认 · 病历")

        let conflict = makeHealthReportCandidate(conflictReasons: ["unit_conflict"])
        XCTAssertEqual(conflict.conflictReasonLabels, ["识别单位与报告中的其他信息不一致"])
        XCTAssertFalse(conflict.conflictReasonLabels[0].contains("unit_conflict"))

        let unknownReview = makeHealthReportReview(
            status: .unknown("future_server_state"),
            requiresConfirmation: false,
            canConfirm: false
        )
        let repository = HealthReportReviewRepositorySpy(
            fetchResponse: unknownReview,
            confirmResponse: unknownReview
        )
        let unknownViewModel = HealthReportReviewViewModel(
            route: HealthReportWorkflowRoute(
                workflowID: 4242,
                subjectUserID: 1,
                status: .unknown("future_server_state"),
                isDuplicate: false
            ),
            accountScope: "account-a",
            repository: repository,
            currentAccountScope: { "account-a" }
        )
        await unknownViewModel.load()
        XCTAssertEqual(unknownViewModel.primaryButtonTitle, "刷新报告状态")
        XCTAssertTrue(unknownViewModel.canReloadStatusFromPrimary, "未知服务端状态的刷新主按钮必须可操作")
    }

    @MainActor
    func testReportConfirmationRetryReusesClientEventAndDoesNotDuplicateSubmission() async throws {
        let awaiting = makeHealthReportReview(status: .awaitingConfirmation)
        let completed = makeHealthReportReview(
            status: .completedScorePending,
            version: 4,
            pendingCount: 0,
            requiresConfirmation: false,
            canConfirm: false,
            candidateStatus: .confirmed,
            candidateRequiresReview: false
        )
        let repository = HealthReportReviewRepositorySpy(
            fetchResponse: awaiting,
            confirmResponse: completed,
            failuresRemaining: 1,
            confirmDelayNanoseconds: 50_000_000
        )
        var generatedEventCount = 0
        let viewModel = HealthReportReviewViewModel(
            route: HealthReportWorkflowRoute(
                workflowID: 4242,
                subjectUserID: 1,
                status: .awaitingConfirmation,
                isDuplicate: false
            ),
            accountScope: "account-a",
            repository: repository,
            currentAccountScope: { "account-a" },
            makeClientEventID: {
                generatedEventCount += 1
                return "report-confirm-event-1"
            }
        )

        await viewModel.load()
        viewModel.choose(.confirm, for: 101)
        viewModel.reportAcknowledged = true
        await viewModel.submitReportConfirmation()
        XCTAssertTrue(viewModel.hasPendingRetry)
        XCTAssertEqual(viewModel.pendingClientEventID, "report-confirm-event-1")

        let retry = Task { @MainActor in await viewModel.submitReportConfirmation() }
        await Task.yield()
        let duplicateTap = Task { @MainActor in await viewModel.submitReportConfirmation() }
        await retry.value
        await duplicateTap.value

        let requests = await repository.confirmationRequests()
        XCTAssertEqual(requests.count, 2, "失败后只允许一次同 event 重试，并行重复点击不得产生第三次请求")
        XCTAssertEqual(Set(requests.map(\.client_event_id)), ["report-confirm-event-1"])
        XCTAssertEqual(generatedEventCount, 1)
        XCTAssertEqual(viewModel.status, .completedScorePending)
        XCTAssertFalse(viewModel.hasPendingRetry)
        XCTAssertEqual(viewModel.primaryButtonTitle, "查看本次解读")
        XCTAssertTrue(viewModel.canOpenInterpretation)
        await viewModel.loadInterpretation()
        XCTAssertTrue(viewModel.interpretation?.available == true)
        XCTAssertTrue(viewModel.interpretation?.score_pending == true)
        XCTAssertEqual(viewModel.interpretation?.score_snapshots.first?.before_value, 58)
        XCTAssertEqual(viewModel.interpretation?.score_snapshots.first?.after_value, 54)
        XCTAssertEqual(
            Set(viewModel.interpretation?.profile_impacts.map(\.profile_candidate_id) ?? []),
            [301],
            "同一画像候选的多来源必须保持同一 candidate id，供 UI 聚合而不是重复计数"
        )
        await viewModel.submitReportConfirmation()
        let requestsAfterFinalTap = await repository.confirmationRequests()
        XCTAssertEqual(requestsAfterFinalTap.count, 2)
    }

    @MainActor
    func testReportConfirmationRelaunchRecoversCommittingEventWithoutCreatingNewEvent() async throws {
        let committing = makeHealthReportReview(
            status: .committing,
            confirmationClientEventID: "persisted-confirm-event",
            requiresConfirmation: false,
            canConfirm: false
        )
        let completed = makeHealthReportReview(
            status: .completedScorePending,
            version: 4,
            confirmationClientEventID: "persisted-confirm-event",
            pendingCount: 0,
            requiresConfirmation: false,
            canConfirm: false,
            candidateStatus: .confirmed,
            candidateRequiresReview: false
        )
        let repository = HealthReportReviewRepositorySpy(
            fetchResponse: committing,
            confirmResponse: completed
        )
        var generatedEventCount = 0
        let relaunchedViewModel = HealthReportReviewViewModel(
            route: HealthReportWorkflowRoute(
                workflowID: 4242,
                subjectUserID: 1,
                status: .committing,
                isDuplicate: false
            ),
            accountScope: "account-a",
            repository: repository,
            currentAccountScope: { "account-a" },
            makeClientEventID: {
                generatedEventCount += 1
                return "must-not-be-created"
            }
        )

        await relaunchedViewModel.load()
        XCTAssertTrue(relaunchedViewModel.hasPendingRetry)
        XCTAssertEqual(relaunchedViewModel.pendingClientEventID, "persisted-confirm-event")
        XCTAssertEqual(relaunchedViewModel.primaryButtonTitle, "继续完成入库")
        await relaunchedViewModel.submitReportConfirmation()

        let recoveredRequests = await repository.confirmationRequests()
        let request = try XCTUnwrap(recoveredRequests.first)
        XCTAssertEqual(request.client_event_id, "persisted-confirm-event")
        XCTAssertTrue(request.decisions.isEmpty, "重启恢复只复用服务端已持久化 decisions，不重建或篡改字段决定")
        XCTAssertEqual(generatedEventCount, 0)
        XCTAssertEqual(relaunchedViewModel.status, .completedScorePending)
    }

    @MainActor
    func testReloadInvalidatesDraftsAndAcknowledgementWhenWorkflowRevisionChanges() async throws {
        let initial = makeHealthReportReview(
            status: .awaitingConfirmation,
            version: 3,
            candidateVersion: 1
        )
        let repository = HealthReportReviewRepositorySpy(
            fetchResponse: initial,
            confirmResponse: initial
        )
        let viewModel = HealthReportReviewViewModel(
            route: HealthReportWorkflowRoute(
                workflowID: 4242,
                subjectUserID: 1,
                status: .awaitingConfirmation,
                isDuplicate: false
            ),
            accountScope: "account-a",
            repository: repository,
            currentAccountScope: { "account-a" }
        )

        await viewModel.load()
        viewModel.updateCorrection(candidateID: 101, value: "7.1", unit: "mmol/L")
        viewModel.reportAcknowledged = true
        XCTAssertTrue(viewModel.hasUnsavedChanges)

        await repository.setFetchResponse(makeHealthReportReview(
            status: .awaitingConfirmation,
            version: 4,
            candidateVersion: 2
        ))
        await viewModel.load()

        XCTAssertEqual(viewModel.drafts[101], .empty)
        XCTAssertFalse(viewModel.reportAcknowledged)
        XCTAssertNil(viewModel.pendingClientEventID)
        XCTAssertEqual(viewModel.unresolvedCandidateCount, 1)
        XCTAssertFalse(viewModel.hasUnsavedChanges)

        viewModel.choose(.confirm, for: 101)
        viewModel.reportAcknowledged = true
        await viewModel.load()
        XCTAssertEqual(viewModel.drafts[101]?.action, .confirm, "同一服务端修订刷新不得吞掉用户草稿")
        XCTAssertTrue(viewModel.reportAcknowledged)

        await repository.setFetchResponse(makeHealthReportReview(
            status: .completed,
            version: 5,
            pendingCount: 0,
            requiresConfirmation: false,
            canConfirm: false,
            candidateStatus: .confirmed,
            candidateRequiresReview: false,
            candidateVersion: 2
        ))
        await viewModel.load()
        XCTAssertEqual(viewModel.status, .completed)
        XCTAssertFalse(viewModel.hasUnsavedChanges, "终态页面不得被误判为有未保存修改而阻止返回")
    }

    @MainActor
    func testManualReportCandidateRecoveryStaysPendingAndReusesStableEventAcrossRetry() async throws {
        let failed = makeHealthReportReview(
            status: .failed,
            failureRecovery: HealthReportFailureRecovery(
                failure_code: "no_reviewable_candidates",
                recovery_action: "manual_entry_or_reupload",
                retryable: true,
                allows_manual_candidate: true
            )
        )
        let awaiting = makeHealthReportReview(
            status: .awaitingConfirmation,
            version: 4,
            pendingCount: 1,
            requiresConfirmation: true,
            canConfirm: true,
            candidateVersion: 2
        )
        let repository = HealthReportReviewRepositorySpy(
            fetchResponse: failed,
            confirmResponse: awaiting,
            manualFailuresRemaining: 1
        )
        var generatedEventCount = 0
        let viewModel = HealthReportReviewViewModel(
            route: HealthReportWorkflowRoute(
                workflowID: 4242,
                subjectUserID: 1,
                status: .failed,
                isDuplicate: false
            ),
            accountScope: "account-a",
            repository: repository,
            currentAccountScope: { "account-a" },
            makeClientEventID: {
                generatedEventCount += 1
                return "manual-report-event-1"
            }
        )

        await viewModel.load()
        XCTAssertTrue(viewModel.manualEntryAvailable)
        XCTAssertTrue(viewModel.statusDetail.contains("手动补录"))
        viewModel.beginManualEntry()
        viewModel.manualDraft.name = "空腹血糖"
        viewModel.manualDraft.value = "8.2"
        viewModel.manualDraft.unit = "mmol/L"
        viewModel.manualDraft.referenceLow = "3.9"
        viewModel.manualDraft.referenceHigh = "6.1"

        await viewModel.submitManualCandidate()
        XCTAssertTrue(viewModel.hasPendingManualCandidateRetry)
        XCTAssertEqual(viewModel.pendingManualCandidateClientEventID, "manual-report-event-1")
        XCTAssertTrue(viewModel.hasUnsavedChanges, "失败的手动补录必须保留退出保护")

        await repository.setFetchResponse(awaiting)
        await viewModel.submitManualCandidate()

        let requests = await repository.manualCandidateRequests()
        XCTAssertEqual(requests.count, 2)
        XCTAssertEqual(Set(requests.map(\.client_event_id)), ["manual-report-event-1"])
        XCTAssertEqual(requests.first?.workflow_version, 3)
        XCTAssertEqual(requests.first?.subject_user_id, 1)
        XCTAssertEqual(requests.first?.canonical_name, "空腹血糖")
        XCTAssertEqual(requests.first?.value_numeric, 8.2)
        XCTAssertNil(requests.first?.value_text)
        XCTAssertEqual(generatedEventCount, 1)
        XCTAssertEqual(viewModel.status, .awaitingConfirmation)
        XCTAssertFalse(viewModel.hasPendingManualCandidateRetry)
        XCTAssertFalse(viewModel.manualDraft.hasChanges)
        XCTAssertFalse(viewModel.reportAcknowledged)
    }

    func testReportReviewRepositoryUsesSubjectBoundPathAndConfirmationBody() async throws {
        let api = MockAPIService()
        let review = makeHealthReportReview(status: .awaitingConfirmation)
        let getPath = "/api/health-data/report-workflows/4242/review?subject_user_id=1"
        let interpretationPath = "/api/health-data/report-workflows/4242/interpretation?subject_user_id=1"
        let confirmPath = "/api/health-data/report-workflows/4242/confirm"
        let manualPath = "/api/health-data/report-workflows/4242/manual-candidates"
        try await api.setResponse(for: getPath, value: review)
        try await api.setResponse(for: interpretationPath, value: makeHealthReportInterpretation())
        try await api.setResponse(for: confirmPath, value: review)
        try await api.setResponse(for: manualPath, value: review)
        let repository = HealthDataRepository(api: api)

        _ = try await repository.fetchReportReview(workflowID: 4242, subjectUserID: 1)
        let interpretation = try await repository.fetchReportInterpretation(
            workflowID: 4242,
            subjectUserID: 1
        )
        XCTAssertTrue(interpretation.score_pending)
        let request = HealthReportConfirmationRequest(
            subject_user_id: 1,
            client_event_id: "event-1",
            workflow_version: 3,
            decisions: [
                HealthReportConfirmationDecision(
                    candidate_id: 101,
                    candidate_version: 1,
                    action: .confirm,
                    value_numeric: nil,
                    value_text: nil,
                    unit: nil
                )
            ]
        )
        _ = try await repository.confirmReport(
            workflowID: 4242,
            request: request,
            expectedAccountScope: "account-a"
        )
        _ = try await repository.addManualReportCandidate(
            workflowID: 4242,
            request: HealthReportManualCandidateRequest(
                subject_user_id: 1,
                workflow_version: 3,
                client_event_id: "manual-event-1",
                canonical_code: nil,
                canonical_name: "空腹血糖",
                raw_name: "空腹血糖",
                value_numeric: 8.2,
                value_text: nil,
                unit: "mmol/L",
                reference_low: 3.9,
                reference_high: 6.1,
                reference_text: nil,
                effective_at: nil
            ),
            expectedAccountScope: "account-a"
        )

        let requestedPaths = await api.requestedPaths
        let requestedScopes = await api.requestedAccountScopes
        XCTAssertEqual(requestedPaths, [getPath, interpretationPath, confirmPath, manualPath])
        XCTAssertEqual(requestedScopes, ["account-a", "account-a"])
        let body = await api.requestBodyJSON(for: confirmPath)
        XCTAssertEqual(body?["subject_user_id"] as? Int, 1)
        XCTAssertEqual(body?["client_event_id"] as? String, "event-1")
        XCTAssertEqual(body?["workflow_version"] as? Int, 3)
        let manualBody = await api.requestBodyJSON(for: manualPath)
        XCTAssertEqual(manualBody?["subject_user_id"] as? Int, 1)
        XCTAssertEqual(manualBody?["workflow_version"] as? Int, 3)
        XCTAssertEqual(manualBody?["client_event_id"] as? String, "manual-event-1")
        XCTAssertEqual(manualBody?["canonical_name"] as? String, "空腹血糖")
        XCTAssertNil(manualBody?["review_status"])
        XCTAssertNil(manualBody?["admitted_observation_count"])
    }

    @MainActor
    func testHealthProfileTrustUsesServerSubjectExplicitVersionedConfirmationAndIdempotentRetry() async throws {
        let initial = makeHealthProfileTrustResponse()
        let accepted = makeHealthProfileTrustResponse(includeCandidate: false, includeAcceptedFact: true)

        let api = MockAPIService()
        let getPath = "/api/health-data/profile-trust"
        let reviewPath = "/api/health-data/profile-trust/candidates/301/review"
        let upsertPath = "/api/health-data/profile-trust/facts"
        let retractPath = "/api/health-data/profile-trust/facts/201/retract"
        let medicationSummaryPath = "/api/medications/trust/long-term-summary?subject_user_id=1"
        let factHistoryPath = "/api/health-data/profile-trust/facts/201/revisions?subject_user_id=1&limit=50"
        let goalHistoryPath = "/api/health-data/profile-trust/goals/701/revisions?subject_user_id=1&limit=50"
        let createGoalPath = "/api/health-data/profile-trust/goals"
        let updateGoalPath = "/api/health-data/profile-trust/goals/701"
        let goalStatusPath = "/api/health-data/profile-trust/goals/701/status"
        try await api.setResponse(for: getPath, value: initial)
        try await api.setResponse(for: reviewPath, value: accepted)
        try await api.setResponse(for: upsertPath, value: accepted)
        try await api.setResponse(for: retractPath, value: accepted)
        try await api.setResponse(
            for: medicationSummaryPath,
            value: HealthProfileLongTermMedicationSummary(subject_user_id: 1, items: [])
        )
        try await api.setResponse(
            for: factHistoryPath,
            value: HealthProfileRevisionList(
                subject_user_id: 1,
                target_kind: .fact,
                target_id: 201,
                items: [],
                next_after_revision_id: nil
            )
        )
        try await api.setResponse(
            for: goalHistoryPath,
            value: HealthProfileRevisionList(
                subject_user_id: 1,
                target_kind: .goal,
                target_id: 701,
                items: [],
                next_after_revision_id: nil
            )
        )
        try await api.setResponse(for: createGoalPath, value: accepted)
        try await api.setResponse(for: updateGoalPath, value: accepted)
        try await api.setResponse(for: goalStatusPath, value: accepted)
        let repository = PatientHistoryRepository(api: api)

        let fetched = try await repository.fetchProfile()
        XCTAssertEqual(fetched.subject_user_id, 1, "GET 应省略 subject 参数并以服务端响应主体为准")
        XCTAssertEqual(fetched.management_plans.map(\.title), ["七天稳糖计划"])
        XCTAssertEqual(fetched.management_plans.first?.completed_task_count, 3)
        let candidate = try XCTUnwrap(fetched.candidates.first)
        let reviewRequest = HealthProfileCandidateReviewRequest(
            subject_user_id: fetched.subject_user_id,
            client_event_id: "profile-review-1",
            candidate_version: candidate.version,
            action: .accept
        )
        _ = try await repository.reviewCandidate(
            candidateID: candidate.candidate_id,
            request: reviewRequest,
            expectedAccountScope: "account-a"
        )
        let upsertRequest = HealthProfileFactUpsertRequest(
            subject_user_id: 1,
            client_event_id: "profile-upsert-1",
            fact_key: "safety.medication_allergy",
            category: .safety,
            response_state: .value,
            value: .string("青霉素过敏"),
            is_safety_critical: true,
            expected_version: nil
        )
        _ = try await repository.upsertFact(upsertRequest, expectedAccountScope: "account-a")
        _ = try await repository.retractFact(
            factID: 201,
            request: HealthProfileFactRetractRequest(
                subject_user_id: 1,
                client_event_id: "profile-retract-1",
                expected_version: 2
            ),
            expectedAccountScope: "account-a"
        )
        _ = try await repository.fetchLongTermMedicationSummary(subjectUserID: 1)
        _ = try await repository.fetchFactRevisions(
            factID: 201,
            subjectUserID: 1,
            afterRevisionID: nil
        )
        _ = try await repository.fetchGoalRevisions(
            goalID: 701,
            subjectUserID: 1,
            afterRevisionID: nil
        )
        let goalMetrics = [
            HealthProfileGoalMetricRequest(metric_key: "sleep_duration", display_label: "睡眠时长")
        ]
        _ = try await repository.createGoal(
            HealthProfileGoalCreateRequest(
                subject_user_id: 1,
                client_event_id: "profile-goal-create-1",
                name: "改善睡眠规律",
                started_on: "2026-07-15",
                metrics: goalMetrics
            ),
            expectedAccountScope: "account-a"
        )
        _ = try await repository.updateGoal(
            goalID: 701,
            request: HealthProfileGoalUpdateRequest(
                subject_user_id: 1,
                client_event_id: "profile-goal-update-1",
                expected_version: 3,
                name: "改善睡眠质量",
                started_on: "2026-07-15",
                metrics: goalMetrics
            ),
            expectedAccountScope: "account-a"
        )
        _ = try await repository.updateGoalStatus(
            goalID: 701,
            request: HealthProfileGoalStatusRequest(
                subject_user_id: 1,
                client_event_id: "profile-goal-pause-1",
                expected_version: 3,
                action: .pause
            ),
            expectedAccountScope: "account-a"
        )

        let repositoryPaths = await api.requestedPaths
        let repositoryScopes = await api.requestedAccountScopes
        let reviewBody = await api.requestBodyJSON(for: reviewPath)
        let upsertBody = await api.requestBodyJSON(for: upsertPath)
        let retractBody = await api.requestBodyJSON(for: retractPath)
        XCTAssertEqual(
            repositoryPaths,
            [
                getPath,
                reviewPath,
                upsertPath,
                retractPath,
                medicationSummaryPath,
                factHistoryPath,
                goalHistoryPath,
                createGoalPath,
                updateGoalPath,
                goalStatusPath
            ]
        )
        XCTAssertEqual(
            repositoryScopes,
            ["account-a", "account-a", "account-a", "account-a", "account-a", "account-a"]
        )
        XCTAssertEqual(reviewBody?["candidate_version"] as? Int, 2)
        XCTAssertEqual(upsertBody?["is_safety_critical"] as? Bool, true)
        XCTAssertEqual(retractBody?["expected_version"] as? Int, 2)
        let createGoalBody = await api.requestBodyJSON(for: createGoalPath)
        let updateGoalBody = await api.requestBodyJSON(for: updateGoalPath)
        let goalStatusBody = await api.requestBodyJSON(for: goalStatusPath)
        XCTAssertEqual(createGoalBody?["name"] as? String, "改善睡眠规律")
        XCTAssertEqual(updateGoalBody?["expected_version"] as? Int, 3)
        XCTAssertEqual(goalStatusBody?["action"] as? String, "pause")

        let uploadAPI = MockAPIService()
        let orderedAssetPath = "/api/health-data/report-workflows/4242/assets/0"
        let uploadResponse = Data(#"{"asset_id":81}"#.utf8)
        await uploadAPI.setRawResponse(for: orderedAssetPath, data: uploadResponse)
        let receivedUploadResponse = try await uploadAPI.putFileAccountBound(
            orderedAssetPath,
            fileData: Data("page-image".utf8),
            fileName: "page-1.png",
            mimeType: "image/png",
            formData: ["subject_user_id": "1", "page_index": "0"],
            expectedAccountScope: "account-a"
        )
        XCTAssertEqual(receivedUploadResponse, uploadResponse)
        let recordedUploads = await uploadAPI.accountBoundFileUploads()
        XCTAssertEqual(recordedUploads.first?.path, orderedAssetPath)
        XCTAssertEqual(recordedUploads.first?.expectedAccountScope, "account-a")
        XCTAssertEqual(recordedUploads.first?.formData["page_index"], "0")

        let spy = HealthProfileTrustRepositorySpy(
            fetched: initial,
            mutationResponse: accepted,
            candidateFailuresRemaining: 1
        )
        var scope = "account-a"
        var generatedEventCount = 0
        let viewModel = PatientHistoryViewModel(
            repository: spy,
            currentAccountScope: { scope },
            makeClientEventID: {
                generatedEventCount += 1
                return "profile-event-\(generatedEventCount)"
            }
        )
        await viewModel.load(accountScope: scope)
        XCTAssertEqual(viewModel.profile?.subject_user_id, 1)
        await viewModel.reviewCandidate(candidate, action: .accept, safetyConfirmed: false)
        XCTAssertTrue(viewModel.hasPendingRetry)
        XCTAssertEqual(viewModel.pendingClientEventID, "profile-event-1")
        await viewModel.retryPendingMutation()
        XCTAssertFalse(viewModel.hasPendingRetry)
        XCTAssertEqual(generatedEventCount, 1, "失败重试必须复用同一个 client_event_id")
        let reviews = await spy.candidateRequests()
        XCTAssertEqual(reviews.count, 2)
        XCTAssertEqual(Set(reviews.map(\.client_event_id)), ["profile-event-1"])
        XCTAssertEqual(Set(reviews.map(\.candidate_version)), [2])

        let safety = try XCTUnwrap(
            HealthProfileFieldCatalog.definition(for: "safety.medication_allergy")
        )
        viewModel.beginEditing(safety)
        viewModel.updateEditorValue("青霉素过敏")
        await viewModel.saveEditor(safetyConfirmed: false)
        XCTAssertTrue(viewModel.errorMessage?.contains("再次确认") == true)
        let upsertsBeforeConfirmation = await spy.upsertRequests()
        XCTAssertEqual(upsertsBeforeConfirmation.count, 0, "安全信息未经二次确认不得出站")
        await viewModel.saveEditor(safetyConfirmed: true)
        let safetyUpserts = await spy.upsertRequests()
        let savedSafety = try XCTUnwrap(safetyUpserts.first)
        XCTAssertEqual(savedSafety.category, .safety)
        XCTAssertTrue(savedSafety.is_safety_critical)
        XCTAssertEqual(savedSafety.expected_version, nil)

        let goalCandidate = HealthProfileCandidate(
            candidate_id: 999,
            fact_key: "goal.primary",
            category: "goal",
            proposed_value: ["value": .string("AI 自动目标")],
            is_safety_critical: false,
            review_status: "pending_review",
            conflict_with_fact_id: nil,
            confidence: 0.9,
            version: 1,
            created_at: "2026-07-15T08:00:00Z",
            updated_at: "2026-07-15T08:00:00Z",
            sources: []
        )
        XCTAssertFalse(goalCandidate.isReviewable, "健康目标只能由用户主动创建")
        XCTAssertFalse(goalCandidate.canReview(.accept))
        XCTAssertTrue(goalCandidate.canReview(.reject), "AI 目标候选仍应允许用户忽略")
        let safetyCandidate = HealthProfileCandidate(
            candidate_id: 998,
            fact_key: "safety.medication_allergy",
            category: "safety",
            proposed_value: ["value": .string("候选过敏")],
            is_safety_critical: false,
            review_status: "pending_review",
            conflict_with_fact_id: nil,
            confidence: 0.9,
            version: 1,
            created_at: "2026-07-15T08:00:00Z",
            updated_at: "2026-07-15T08:00:00Z",
            sources: []
        )
        XCTAssertFalse(safetyCandidate.canReview(.accept), "安全类别即使服务端标志漂移也不能直接接受")
        XCTAssertTrue(safetyCandidate.canReview(.reject))

        let requiredLongTermKeys = Set([
            "long_term_health.diagnoses",
            "long_term_health.family_history",
            "long_term_health.recent_findings",
            "long_term_health.risk_factor",
            "long_term_health.active_concern",
            "long_term_health.linked_plan"
        ])
        XCTAssertTrue(
            requiredLongTermKeys.isSubset(of: Set(HealthProfileFieldCatalog.editable.map(\.key))),
            "画像文档定义的慢病、家族史、长期异常、风险、主动关注和关联计划必须由同一字段目录覆盖"
        )
        let serverAction = HealthProfilePrimaryAction(
            kind: "review_updates",
            item_count: 7,
            localization_key: "health_profile.primary_action.review_updates",
            route: "profile_updates"
        )
        XCTAssertEqual(serverAction.title, "检查 7 项更新")
        XCTAssertNotEqual(
            serverAction.item_count,
            initial.overview.pending_update_count,
            "主操作数量必须能与本地数组数量不同，客户端不得重新推导覆盖服务端决定"
        )
        XCTAssertEqual(initial.overview.independent_source_count, 9)
        XCTAssertNotEqual(
            initial.overview.independent_source_count,
            Set(initial.facts.flatMap(\.sources).map(\.source_id)).count,
            "独立来源数必须能与本地可见来源不同，客户端不得重新计数覆盖服务端值"
        )

        viewModel.beginCreatingGoal()
        viewModel.updateGoalName("改善睡眠")
        viewModel.updateGoalStartedOn("2026-07-15")
        await viewModel.saveGoalEditor()
        XCTAssertTrue(viewModel.errorMessage?.contains("指标") == true)
        let createsBeforeMetrics = await spy.goalCreateRequests()
        XCTAssertTrue(createsBeforeMetrics.isEmpty, "不完整目标不得出站")
        viewModel.updateGoalMetricsText("睡眠时长、HRV")
        await viewModel.saveGoalEditor()
        let goalCreates = await spy.goalCreateRequests()
        let goalCreate = try XCTUnwrap(goalCreates.first)
        XCTAssertEqual(goalCreate.name, "改善睡眠")
        XCTAssertEqual(goalCreate.started_on, "2026-07-15")
        XCTAssertEqual(goalCreate.metrics.map(\.metric_key), ["sleep_duration", "hrv"])
        XCTAssertEqual(goalCreate.metrics.map(\.display_label), ["睡眠时长", "HRV"])

        let appleSource = HealthProfileSource(
            source_id: 700,
            source_type: "device",
            source_ref: "apple-health:body-mass",
            confidence: 1,
            source_snapshot: [:],
            created_at: "2026-07-15T09:00:00Z"
        )
        let height = HealthProfileFact(
            fact_id: 701,
            fact_key: "basic.height",
            category: "basic",
            value_data: ["response_state": .string("value"), "value": .string("170 cm")],
            is_safety_critical: false,
            confirmation_method: "user",
            version: 1,
            confirmed_at: "2026-07-15T09:00:00Z",
            updated_at: "2026-07-15T09:00:00Z",
            sources: [appleSource]
        )
        let weight = HealthProfileFact(
            fact_id: 702,
            fact_key: "basic.weight",
            category: "basic",
            value_data: ["response_state": .string("value"), "value": .string("65 kg")],
            is_safety_critical: false,
            confirmation_method: "user",
            version: 3,
            confirmed_at: "2026-07-15T10:00:00Z",
            updated_at: "2026-07-15T10:00:00Z",
            sources: [appleSource]
        )
        let bmi = HealthProfileDerivedMetrics.bodyMassIndex(from: [height, weight])
        XCTAssertEqual(try XCTUnwrap(bmi.value), 22.49, accuracy: 0.01)
        XCTAssertEqual(bmi.updatedAt, weight.updated_at)
        XCTAssertTrue(bmi.sourceDescription.contains("Apple Health"))
        XCTAssertTrue(bmi.sourceDescription.contains("不是用户单独填写项"))
        let unitlessWeight = HealthProfileFact(
            fact_id: 703,
            fact_key: "basic.weight",
            category: "basic",
            value_data: ["response_state": .string("value"), "value": .string("65")],
            is_safety_critical: false,
            confirmation_method: "user",
            version: 1,
            confirmed_at: nil,
            updated_at: "2026-07-15T10:00:00Z",
            sources: []
        )
        XCTAssertNil(
            HealthProfileDerivedMetrics.bodyMassIndex(from: [height, unitlessWeight]).value,
            "没有单位时必须显示待补充，不能猜测 BMI"
        )
        let automaticHeight = HealthProfileFact(
            fact_id: height.fact_id,
            fact_key: height.fact_key,
            category: height.category,
            value_data: height.value_data,
            is_safety_critical: height.is_safety_critical,
            confirmation_method: "automatic",
            version: height.version,
            confirmed_at: height.confirmed_at,
            updated_at: height.updated_at,
            sources: height.sources
        )
        XCTAssertNil(
            HealthProfileDerivedMetrics.bodyMassIndex(from: [automaticHeight, weight]).value,
            "未经用户、医生或可信来源确认的测量不得参与 BMI"
        )
        XCTAssertEqual(
            HealthProfileDisplayFormatter.source(type: "report_observation", reference: "report:1"),
            "已确认报告"
        )

        scope = "account-b"
        let fact = try XCTUnwrap(viewModel.profile?.facts.first)
        await viewModel.retract(fact, confirmed: true)
        XCTAssertTrue(viewModel.errorMessage?.contains("账号已变化") == true)
        let retractions = await spy.retractionRequests()
        XCTAssertEqual(retractions.count, 0, "账号切换后不得继续使用旧画像主体写入")
        XCTAssertTrue(
            HealthProfileDisplayFormatter.value(
                ["value": .object(["name": .string("药品"), "dose": .string("不得在画像展示")])],
                medicationSummaryOnly: true
            ).contains("剂量") == false,
            "画像中的长期用药只允许摘要字段"
        )
    }

    @MainActor
    func testMedicationTrustModelsKeepPossiblyMissedUnconfirmedAndInventoryEstimated() throws {
        let task = makeMedicationTodayTask(status: .possiblyMissed)
        let summary = makeMedicationTodaySummary(task: task)
        let plan = makeTrustedMedicationPlan()
        let candidate = makeMedicationPrefillCandidate()

        XCTAssertTrue(task.possibly_missed_is_not_confirmation)
        XCTAssertEqual(task.status_assertion, "schedule_derived")
        XCTAssertNil(task.confirmed_at)
        XCTAssertFalse(
            MedicationTrustPolicy.acceptsPossiblyMissedAsConfirmed(task),
            "提醒时间经过只能形成可能漏服，不能冒充用户确认"
        )
        XCTAssertEqual(summary.missed_assertion_policy, "elapsed_time_never_confirms_missed")
        XCTAssertTrue(MedicationTrustPolicy.isServerInventoryEstimate(plan.inventory))
        XCTAssertEqual(plan.inventory.label, "预计剩余")
        XCTAssertEqual(plan.inventory.basis, "user_confirmed_taken_events_only")
        XCTAssertTrue(candidate.isPendingReview)
        XCTAssertEqual(
            MedicationTrustPolicy.primaryAction(
                today: summary,
                plans: [plan],
                pendingPrefills: [candidate]
            ),
            .reviewPrefill(candidate.candidate_id),
            "待确认处方只能进入复核主动作，不能直接成为当前计划"
        )

        let oversizedEvent = String(repeating: "event", count: 30)
        XCTAssertEqual(
            MedicationViewModel.boundedClientEventID(oversizedEvent, fallback: "unused"),
            String(oversizedEvent.prefix(80)),
            "客户端事件必须满足服务端 1...80 字符契约"
        )
        XCTAssertEqual(
            MedicationViewModel.boundedClientEventID("   ", fallback: "fallback-event"),
            "fallback-event",
            "空事件生成器必须显式落到可测试的稳定 fallback"
        )
        XCTAssertEqual(
            MedicationViewModel.boundedClientEventID("", fallback: ""),
            "client-event"
        )
        let compoundEmojiEvent = String(repeating: "👨‍👩‍👧‍👦", count: 30)
        XCTAssertLessThanOrEqual(
            MedicationViewModel.boundedClientEventID(
                compoundEmojiEvent,
                fallback: "unused"
            ).unicodeScalars.count,
            80,
            "服务端按 Unicode code point 校验 max_length，组合 emoji 也不能越界"
        )

        var draft = MedicationPlanDraft()
        draft.genericName = "二甲双胍"
        draft.doseQuantity = "0.5"
        XCTAssertTrue(draft.isValid)
        draft.doseQuantity = String(Double.infinity)
        XCTAssertFalse(draft.isValid, "单次剂量不得接受正无穷")
        draft.doseQuantity = String(-Double.infinity)
        XCTAssertFalse(draft.isValid, "单次剂量不得接受负无穷")
        draft.doseQuantity = String(Double.nan)
        XCTAssertFalse(draft.isValid, "单次剂量不得接受 NaN")
        draft.doseQuantity = "1"
        draft.initialQuantity = String(Double.infinity)
        draft.inventoryUnit = "片"
        XCTAssertFalse(draft.isValid, "初始数量不得接受正无穷")
        draft.initialQuantity = String(-Double.infinity)
        XCTAssertFalse(draft.isValid, "初始数量不得接受负无穷")
        draft.initialQuantity = String(Double.nan)
        XCTAssertFalse(draft.isValid, "初始数量不得接受 NaN")
        draft.initialQuantity = "0.5"
        XCTAssertFalse(draft.isValid, "初始数量不足一次用量时不得创建计划")
        draft.initialQuantity = "30"
        XCTAssertTrue(draft.isValid)

        draft.scheduleTimes = ["8:00"]
        XCTAssertFalse(draft.isValid, "服药时间必须使用可稳定解析的 HH:mm")
        draft.scheduleTimes = ["08:00", "20:00"]
        XCTAssertTrue(draft.isValid)
        draft.courseStart = "2026-07-16"
        draft.courseEnd = "2026-07-15"
        XCTAssertFalse(draft.isValid, "疗程结束日不能早于开始日")
        draft.courseStart = "2026-07-15"
        draft.courseEnd = "2026-07-31"
        XCTAssertTrue(draft.isValid)
        XCTAssertEqual(MedicationQuickFill.appending("饭后", to: "遵医嘱"), "遵医嘱；饭后")
        XCTAssertEqual(
            MedicationQuickFill.appending("饭后", to: "遵医嘱；饭后"),
            "遵医嘱；饭后",
            "快捷短语只能追加且不得重复或覆盖用户原文"
        )

        let timezone = try XCTUnwrap(TimeZone(identifier: "Asia/Shanghai"))
        let now = try XCTUnwrap(
            ISO8601DateFormatter().date(from: "2026-07-15T07:00:00+08:00")
        )
        var reminder = MedicationReminderSettings.defaultValue(
            for: plan,
            localDate: "2026-07-15",
            timezoneIdentifier: timezone.identifier
        )
        XCTAssertFalse(reminder.enabled, "保存计划不得默认开启通知")
        reminder.enabled = true
        reminder.cadence = .everyOtherDay
        reminder.times = ["08:00"]
        let occurrences = MedicationReminderPolicy.occurrences(
            settings: reminder,
            plan: plan,
            now: now,
            currentTimezone: timezone
        )
        XCTAssertGreaterThanOrEqual(occurrences.count, 2)
        XCTAssertTrue(occurrences[0].id.contains(".20260715."))
        XCTAssertTrue(occurrences[1].id.contains(".20260717."))
        XCTAssertEqual(occurrences[0].subjectUserID, plan.subject_user_id)
        XCTAssertEqual(occurrences[0].planVersion, plan.version)
        XCTAssertEqual(
            MedicationReminderPolicy.snoozeIdentifier(
                task: makeMedicationTodayTask(),
                plan: plan
            ),
            "trusted.med.snooze.1.7.v4.20260715.2000",
            "同一剂次重复稍后必须复用稳定 ID 以替换旧通知"
        )
        XCTAssertEqual(MedicationReminderPolicy.ordinaryRequestBudget(preservedSnoozeCount: 0), 60)
        XCTAssertEqual(MedicationReminderPolicy.ordinaryRequestBudget(preservedSnoozeCount: 4), 56)
        XCTAssertEqual(MedicationReminderPolicy.ordinaryRequestBudget(preservedSnoozeCount: 80), 0)
        var staleReminder = reminder
        staleReminder.planVersion -= 1
        XCTAssertTrue(
            MedicationReminderPolicy.occurrences(
                settings: staleReminder,
                plan: plan,
                now: now,
                currentTimezone: timezone
            ).isEmpty,
            "计划版本变化后旧提醒必须失效"
        )

        let recentDates = MedicationDateWindow.recentDates(ending: "2026-07-15", count: 7)
        let recentStatuses: [MedicationTaskStatus] = [
            .taken, .taken, .skipped, .awaitingConfirmation, .taken, .possiblyMissed, .taken
        ]
        let recentSummaries = zip(recentDates, recentStatuses).map { date, status in
            makeMedicationTodaySummary(
                task: makeMedicationTodayTask(status: status, localDate: date),
                localDate: date
            )
        }
        let sevenDay = MedicationConfirmationPolicy.sevenDay(
            summaries: recentSummaries,
            expectedLocalDates: recentDates
        )
        XCTAssertEqual(sevenDay.confirmedCount, 5)
        XCTAssertEqual(sevenDay.plannedCount, 7)
        XCTAssertEqual(sevenDay.percentage, 71)
        XCTAssertFalse(
            MedicationConfirmationPolicy.sevenDay(
                summaries: Array(recentSummaries.dropLast()),
                expectedLocalDates: recentDates
            ).isAvailable,
            "近七日缺一天也不得用局部数据冒充完整统计"
        )
        let boundedCoursePlan = makeTrustedMedicationPlan(
            courseStart: try XCTUnwrap(recentDates.first),
            courseEnd: try XCTUnwrap(recentDates.last)
        )
        XCTAssertEqual(
            MedicationConfirmationPolicy.course(
                plan: boundedCoursePlan,
                summaries: recentSummaries,
                through: "2026-07-15"
            ).percentage,
            71
        )
        XCTAssertFalse(
            MedicationConfirmationPolicy.course(
                plan: plan,
                summaries: recentSummaries,
                through: "2026-07-15"
            ).isAvailable,
            "仅有近七日时不得声称得到完整疗程已确认率"
        )

        let suiteName = "MedicationReminderStoreTests.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suiteName))
        defer { defaults.removePersistentDomain(forName: suiteName) }
        let store = MedicationReminderStore(defaults: defaults)
        try store.save([reminder], accountScope: "account-a", subjectUserID: 1)
        XCTAssertEqual(store.load(accountScope: "account-a", subjectUserID: 1), [reminder])
        XCTAssertTrue(
            store.load(accountScope: "account-b", subjectUserID: 1).isEmpty,
            "提醒持久化必须按账号隔离"
        )
    }

    func testMedicationTrustRepositoryBindsSubjectVersionsAndAccountScopedMutationPaths() async throws {
        let api = MockAPIService()
        let repository = MedicationRepository(api: api)
        let plan = makeTrustedMedicationPlan()
        let today = makeMedicationTodaySummary(task: makeMedicationTodayTask())
        let recognition = makeMedicationRecognitionResult()
        let doseEvent = makeMedicationDoseEvent()
        let todayPath = "/api/medications/trust/today?local_date=2026-07-15&timezone_offset_minutes=480"
        let recognizePath = "/api/medications/recognize"
        let confirmPath = "/api/medications/trust/plans/confirm"
        let dosePath = "/api/medications/trust/dose-events"
        try await api.setResponse(for: todayPath, value: today)
        try await api.setResponse(for: recognizePath, value: recognition)
        try await api.setResponse(for: confirmPath, value: plan)
        try await api.setResponse(for: dosePath, value: doseEvent)

        let fetchedToday = try await repository.fetchToday(
            subjectUserID: nil,
            localDate: "2026-07-15",
            timezoneOffsetMinutes: 480
        )
        XCTAssertEqual(fetchedToday.subject_user_id, 1, "空状态也必须由 today 返回认证主体")

        _ = try await repository.recognize(
            MedicationRecognitionBody(
                raw_text: "阿托伐他汀钙片 20mg 每晚一次",
                subject_user_id: fetchedToday.subject_user_id,
                client_event_id: "ocr-event-1"
            ),
            expectedAccountScope: "account-a"
        )
        let confirm = makeMedicationConfirmRequest(clientEventID: "plan-event-1")
        _ = try await repository.confirmPlan(confirm, expectedAccountScope: "account-a")
        let task = try XCTUnwrap(today.next_task)
        let dose = MedicationDoseActionRequest(
            subject_user_id: fetchedToday.subject_user_id,
            plan_id: task.plan_id,
            expected_plan_version: task.plan_version,
            client_event_id: "dose-event-1",
            scheduled_local_date: task.scheduled_local_date,
            scheduled_time: task.scheduled_time,
            expected_occurrence_version: task.occurrence_version,
            action: .taken,
            corrected_status: nil,
            correction_of_event_id: nil,
            snoozed_until: nil,
            taken_quantity: nil,
            reason: nil
        )
        _ = try await repository.recordDose(dose, expectedAccountScope: "account-a")

        let requestedPaths = await api.requestedPaths
        let requestedScopes = await api.requestedAccountScopes
        XCTAssertEqual(requestedPaths, [todayPath, recognizePath, confirmPath, dosePath])
        XCTAssertEqual(requestedScopes, ["account-a", "account-a", "account-a"])
        let ocrBody = await api.requestBodyJSON(for: recognizePath)
        XCTAssertEqual(ocrBody?["raw_text"] as? String, "阿托伐他汀钙片 20mg 每晚一次")
        XCTAssertEqual(ocrBody?["subject_user_id"] as? Int, 1)
        XCTAssertNil(ocrBody?["image"])
        XCTAssertNil(ocrBody?["photo_url"])
        let planBody = await api.requestBodyJSON(for: confirmPath)
        XCTAssertEqual(planBody?["candidate_id"] as? Int, 41)
        XCTAssertEqual(planBody?["candidate_version"] as? Int, 3)
        XCTAssertEqual(planBody?["client_event_id"] as? String, "plan-event-1")
        XCTAssertEqual(planBody?["subject_user_id"] as? Int, 1)
        XCTAssertNil(planBody?["reminder_default_enabled"])
        let doseBody = await api.requestBodyJSON(for: dosePath)
        XCTAssertEqual(doseBody?["expected_plan_version"] as? Int, 4)
        XCTAssertEqual(doseBody?["expected_occurrence_version"] as? Int, 2)
        XCTAssertEqual(doseBody?["client_event_id"] as? String, "dose-event-1")
    }

    @MainActor
    func testMedicationTrustViewModelRetriesStableDoseEventAndStopsOnAccountChange() async throws {
        let repository = MedicationTrustRepositorySpy(doseFailuresRemaining: 1)
        var currentScope: String? = "account-a"
        var generatedEventCount = 0
        let suiteName = "MedicationViewModelReminderTests.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suiteName))
        defer { defaults.removePersistentDomain(forName: suiteName) }
        let reminderStore = MedicationReminderStore(defaults: defaults)
        let reminderCoordinator = MedicationReminderCoordinatorSpy()
        let timezone = try XCTUnwrap(TimeZone(identifier: "Asia/Shanghai"))
        let now = try XCTUnwrap(
            ISO8601DateFormatter().date(from: "2026-07-15T07:00:00+08:00")
        )
        let viewModel = MedicationViewModel(
            repository: repository,
            reminderStore: reminderStore,
            reminderCoordinator: reminderCoordinator,
            currentAccountScope: { currentScope },
            makeClientEventID: {
                generatedEventCount += 1
                return "medication-event-\(generatedEventCount)"
            },
            localDate: { "2026-07-15" },
            timezoneOffsetMinutes: { 480 },
            currentTimezone: { timezone },
            now: { now }
        )

        await viewModel.load(accountScope: currentScope)
        XCTAssertEqual(viewModel.subjectUserID, 1)
        await viewModel.waitForConfirmationInsightsForTesting()
        XCTAssertEqual(viewModel.confirmationInsights.sevenDay.percentage, 86)
        let fetchedDates = await repository.fetchedTodayDates()
        XCTAssertEqual(fetchedDates.count, 7)
        XCTAssertEqual(Set(fetchedDates), Set(MedicationDateWindow.recentDates(ending: "2026-07-15", count: 7)))

        let plan = try XCTUnwrap(viewModel.plans.first)
        var reminder = viewModel.reminderSettings(for: plan)
        reminder.enabled = true
        reminder.times = ["08:00", "20:00"]
        let reminderSaved = await viewModel.saveReminderSettings(reminder, for: plan)
        XCTAssertTrue(reminderSaved)
        XCTAssertTrue(viewModel.isReminderEnabled(for: plan))
        XCTAssertEqual(
            reminderStore.load(accountScope: "account-a", subjectUserID: 1).first?.planVersion,
            plan.version
        )
        XCTAssertEqual(reminderCoordinator.latestSettings.first?.subjectUserID, 1)
        XCTAssertEqual(reminderCoordinator.latestSettings.first?.planVersion, plan.version)

        let task = try XCTUnwrap(viewModel.today?.next_task)
        await viewModel.confirmTaken(task)
        XCTAssertTrue(viewModel.hasPendingRetry)
        XCTAssertEqual(viewModel.pendingClientEventID, "medication-event-1")

        await viewModel.retryPendingMutation()
        XCTAssertFalse(viewModel.hasPendingRetry)
        XCTAssertEqual(generatedEventCount, 1)
        let doseRequests = await repository.doseRequests()
        XCTAssertEqual(doseRequests.count, 2)
        XCTAssertEqual(Set(doseRequests.map(\.client_event_id)), ["medication-event-1"])
        XCTAssertEqual(Set(doseRequests.map(\.subject_user_id)), [1])
        XCTAssertEqual(Set(doseRequests.map(\.expected_plan_version)), [4])
        XCTAssertEqual(Set(doseRequests.map(\.expected_occurrence_version)), [2])

        await repository.setHistoricalRequestsFail(true)
        await viewModel.reload()
        XCTAssertEqual(viewModel.today?.local_date, "2026-07-15")
        XCTAssertEqual(viewModel.plans.map(\.plan_id), [7])
        XCTAssertFalse(viewModel.loading)
        XCTAssertFalse(
            viewModel.confirmationInsights.sevenDay.isAvailable,
            "历史日期失败只能降级已确认率，不能抹掉今日任务或计划"
        )
        await repository.setHistoricalRequestsFail(false)

        let firstSnooze = now.addingTimeInterval(60 * 30)
        await viewModel.snooze(task, until: firstSnooze)
        XCTAssertEqual(reminderCoordinator.pendingSnoozeIdentifiers.count, 1)
        await viewModel.reload()
        XCTAssertEqual(
            reminderCoordinator.pendingSnoozeIdentifiers.count,
            1,
            "普通提醒重建不得删除仍匹配主体和计划版本的稍后提醒"
        )
        await viewModel.snooze(task, until: firstSnooze.addingTimeInterval(60 * 10))
        XCTAssertEqual(
            reminderCoordinator.pendingSnoozeIdentifiers.count,
            1,
            "同一剂次重复稍后必须替换而不是累积"
        )
        await viewModel.confirmTaken(task)
        XCTAssertTrue(
            reminderCoordinator.pendingSnoozeIdentifiers.isEmpty,
            "剂次已服用、跳过或纠正为非稍后状态时必须取消旧 snooze"
        )

        currentScope = "account-b"
        await viewModel.confirmTaken(task)
        XCTAssertTrue(viewModel.errorMessage?.contains("账号已变化") == true)
        let requestsAfterAccountChange = await repository.doseRequests()
        XCTAssertEqual(requestsAfterAccountChange.count, 5)

        await viewModel.load(accountScope: currentScope)
        XCTAssertTrue(viewModel.reminderSettingsByPlanID.isEmpty)
        XCTAssertTrue(reminderCoordinator.latestSettings.isEmpty)
        XCTAssertTrue(reminderCoordinator.pendingSnoozeIdentifiers.isEmpty)
        XCTAssertGreaterThanOrEqual(reminderCoordinator.clearAllCallCount, 2)
        XCTAssertTrue(
            reminderStore.load(accountScope: "account-b", subjectUserID: 1).isEmpty,
            "账号切换后不得加载上一账号的本机提醒"
        )
    }

}

private actor MedicationTrustRepositorySpy: MedicationRepositoryProtocol {
    private var failuresRemaining: Int
    private var recordedDoseRequests: [MedicationDoseActionRequest] = []
    private var recordedTodayDates: [String] = []
    private var historicalRequestsFail = false

    init(doseFailuresRemaining: Int) {
        failuresRemaining = doseFailuresRemaining
    }

    func fetchToday(
        subjectUserID: Int?,
        localDate: String,
        timezoneOffsetMinutes: Int
    ) async throws -> MedicationTodaySummary {
        XCTAssertTrue(subjectUserID == nil || subjectUserID == 1)
        XCTAssertTrue(
            MedicationDateWindow.recentDates(ending: "2026-07-15", count: 7).contains(localDate)
        )
        XCTAssertEqual(timezoneOffsetMinutes, 480)
        recordedTodayDates.append(localDate)
        if historicalRequestsFail, localDate != "2026-07-15" {
            throw URLError(.timedOut)
        }
        let status: MedicationTaskStatus = localDate == "2026-07-15" ? .awaitingConfirmation : .taken
        return makeMedicationTodaySummary(
            task: makeMedicationTodayTask(status: status, localDate: localDate),
            localDate: localDate
        )
    }

    func fetchPlans(subjectUserID: Int) async throws -> TrustedMedicationPlanList {
        TrustedMedicationPlanList(subject_user_id: subjectUserID, items: [makeTrustedMedicationPlan()])
    }

    func fetchPrefillCandidates(subjectUserID: Int) async throws -> MedicationPrefillList {
        MedicationPrefillList(subject_user_id: subjectUserID, items: [])
    }

    func fetchReactions(subjectUserID: Int) async throws -> MedicationReactionList {
        MedicationReactionList(subject_user_id: subjectUserID, items: [])
    }

    func fetchLegacyReadOnly() async throws -> [Medication] { [] }

    func recognize(
        _ request: MedicationRecognitionBody,
        expectedAccountScope: String
    ) async throws -> MedicationRecognitionResult {
        makeMedicationRecognitionResult(clientEventID: request.client_event_id)
    }

    func confirmPlan(
        _ request: MedicationPlanConfirmRequest,
        expectedAccountScope: String
    ) async throws -> TrustedMedicationPlan {
        makeTrustedMedicationPlan()
    }

    func revisePlan(
        planID: Int,
        request: MedicationPlanReviseRequest,
        expectedAccountScope: String
    ) async throws -> TrustedMedicationPlan {
        makeTrustedMedicationPlan()
    }

    func updatePlanStatus(
        planID: Int,
        request: MedicationPlanStatusRequest,
        expectedAccountScope: String
    ) async throws -> TrustedMedicationPlan {
        makeTrustedMedicationPlan()
    }

    func rejectPrefill(
        candidateID: Int,
        request: MedicationPrefillRejectRequest,
        expectedAccountScope: String
    ) async throws -> MedicationPrefillCandidate {
        let candidate = makeMedicationPrefillCandidate()
        return MedicationPrefillCandidate(
            candidate_id: candidate.candidate_id,
            subject_user_id: candidate.subject_user_id,
            client_event_id: candidate.client_event_id,
            source_type: candidate.source_type,
            source_ref: candidate.source_ref,
            extracted_data: candidate.extracted_data,
            field_confidences: candidate.field_confidences,
            low_confidence_fields: candidate.low_confidence_fields,
            review_status: "rejected",
            version: candidate.version + 1,
            trust_state: candidate.trust_state,
            requires_user_confirmation: true,
            plan_created: false,
            confirmation_endpoint: candidate.confirmation_endpoint
        )
    }

    func recordDose(
        _ request: MedicationDoseActionRequest,
        expectedAccountScope: String
    ) async throws -> MedicationDoseEvent {
        XCTAssertEqual(expectedAccountScope, "account-a")
        recordedDoseRequests.append(request)
        if failuresRemaining > 0 {
            failuresRemaining -= 1
            throw URLError(.timedOut)
        }
        return makeMedicationDoseEvent(clientEventRequest: request)
    }

    func createReaction(
        _ request: MedicationReactionCreateRequest,
        expectedAccountScope: String
    ) async throws -> MedicationReaction {
        makeMedicationReaction()
    }

    func correctReaction(
        reactionKey: String,
        request: MedicationReactionCorrectRequest,
        expectedAccountScope: String
    ) async throws -> MedicationReaction {
        makeMedicationReaction(version: request.expected_version + 1)
    }

    func retractReaction(
        reactionKey: String,
        request: MedicationReactionRetractRequest,
        expectedAccountScope: String
    ) async throws -> MedicationReaction {
        let reaction = makeMedicationReaction(version: request.expected_version + 1)
        return MedicationReaction(
            reaction_key: reaction.reaction_key,
            reaction_version: reaction.reaction_version,
            plan_id: reaction.plan_id,
            symptoms: reaction.symptoms,
            onset_at: reaction.onset_at,
            severity: reaction.severity,
            duration_minutes: reaction.duration_minutes,
            related_occurrence_key: reaction.related_occurrence_key,
            notes: reaction.notes,
            status: "retracted",
            causal_attribution: reaction.causal_attribution,
            user_facing_causality: reaction.user_facing_causality,
            safety_guidance: reaction.safety_guidance,
            confirmed_at: reaction.confirmed_at
        )
    }

    func doseRequests() -> [MedicationDoseActionRequest] { recordedDoseRequests }
    func fetchedTodayDates() -> [String] { recordedTodayDates }
    func setHistoricalRequestsFail(_ value: Bool) { historicalRequestsFail = value }
}

@MainActor
private final class MedicationReminderCoordinatorSpy: MedicationReminderCoordinating {
    private(set) var snapshots: [[MedicationReminderSettings]] = []
    private(set) var pendingSnoozeIdentifiers: Set<String> = []
    private(set) var clearAllCallCount = 0
    var latestSettings: [MedicationReminderSettings] { snapshots.last ?? [] }

    func permissionState() async -> MedicationReminderPermissionState { .allowed }
    func requestPermission() async -> MedicationReminderPermissionState { .allowed }

    func reconcile(
        settings: [MedicationReminderSettings],
        plans: [TrustedMedicationPlan],
        now: Date,
        timezone: TimeZone
    ) async -> MedicationReminderReconcileResult {
        snapshots.append(settings)
        let scheduled = settings.filter(\.enabled).count
        return MedicationReminderReconcileResult(
            permission: .allowed,
            scheduledCount: scheduled,
            detail: nil
        )
    }

    func clearAllMedicationNotifications() async {
        clearAllCallCount += 1
        pendingSnoozeIdentifiers.removeAll()
    }

    func cancelSnooze(task: MedicationTodayTask, plan: TrustedMedicationPlan) async {
        pendingSnoozeIdentifiers.remove(
            MedicationReminderPolicy.snoozeIdentifier(task: task, plan: plan)
        )
    }

    func scheduleSnooze(
        eventID: Int,
        task: MedicationTodayTask,
        plan: TrustedMedicationPlan,
        settings: MedicationReminderSettings?,
        at date: Date
    ) async -> Bool {
        pendingSnoozeIdentifiers.insert(
            MedicationReminderPolicy.snoozeIdentifier(task: task, plan: plan)
        )
        return true
    }
}

private func makeMedicationTodayTask(
    status: MedicationTaskStatus = .awaitingConfirmation,
    localDate: String = "2026-07-15"
) -> MedicationTodayTask {
    MedicationTodayTask(
        occurrence_key: "plan-7:\(localDate):20:00",
        plan_id: 7,
        plan_version: 4,
        generic_name: "阿托伐他汀钙片",
        brand_name: "立普妥",
        dose_text: "20mg，晚饭后服用",
        scheduled_local_date: localDate,
        scheduled_time: "20:00",
        scheduled_at: "\(localDate)T20:00:00+08:00",
        status: status,
        status_label: status.title,
        status_assertion: status == .taken || status == .skipped ? "user_confirmed" : "schedule_derived",
        occurrence_version: 2,
        latest_event_id: status == .taken || status == .skipped ? 91 : nil,
        snoozed_until: nil,
        confirmed_at: status == .taken || status == .skipped ? "2026-07-15T20:05:00+08:00" : nil,
        possibly_missed_is_not_confirmation: status == .possiblyMissed,
        notification_schedule_status: "client_managed"
    )
}

private func makeMedicationTodaySummary(
    task: MedicationTodayTask?,
    localDate: String = "2026-07-15"
) -> MedicationTodaySummary {
    MedicationTodaySummary(
        subject_user_id: 1,
        local_date: localDate,
        planned_count: task == nil ? 0 : 1,
        taken_count: task?.status == .taken ? 1 : 0,
        awaiting_confirmation_count: task?.status == .awaitingConfirmation ? 1 : 0,
        possibly_missed_count: task?.status == .possiblyMissed ? 1 : 0,
        skipped_count: task?.status == .skipped ? 1 : 0,
        snoozed_count: task?.status == .snoozed ? 1 : 0,
        adverse_reaction_count: 0,
        next_task: task,
        tasks: task.map { [$0] } ?? [],
        empty_state: task == nil ? "今天没有用药计划" : nil,
        missed_assertion_policy: "elapsed_time_never_confirms_missed"
    )
}

private func makeTrustedMedicationPlan(
    courseStart: String? = "2026-07-01",
    courseEnd: String? = nil
) -> TrustedMedicationPlan {
    TrustedMedicationPlan(
        plan_id: 7,
        subject_user_id: 1,
        generic_name: "阿托伐他汀钙片",
        brand_name: "立普妥",
        strength: "20mg/片",
        dose_text: "20mg",
        dose_quantity: 1,
        frequency: "每日一次",
        schedule_times: ["20:00"],
        meal_relation: .afterMeal,
        instructions: "晚饭后服用",
        course_start: courseStart,
        course_end: courseEnd,
        prescriber: "测试医生",
        initial_quantity: 30,
        inventory_unit: "片",
        is_long_term: true,
        source_type: .ocr,
        source_ref: "ocr:41:v3",
        status: .active,
        version: 4,
        confirmed_at: "2026-07-15T08:00:00Z",
        trust_state: "user_confirmed",
        reminder_management: "client_managed",
        reminder_default_enabled: false,
        server_notification_scheduled: false,
        inventory: MedicationInventoryEstimate(
            is_estimate: true,
            label: "预计剩余",
            estimated_remaining: 28,
            estimated_consumed: 2,
            inventory_unit: "片",
            basis: "user_confirmed_taken_events_only",
            unavailable_reason: nil
        )
    )
}

private func makeMedicationPrefillCandidate() -> MedicationPrefillCandidate {
    MedicationPrefillCandidate(
        candidate_id: 41,
        subject_user_id: 1,
        client_event_id: "ocr-event-1",
        source_type: .ocr,
        source_ref: "ocr:41",
        extracted_data: [
            "name": .string("阿托伐他汀钙片"),
            "dosage": .string("20mg"),
            "frequency": .string("每日一次"),
            "schedule_times": .array([.string("20:00")])
        ],
        field_confidences: ["name": 0.98, "dosage": 0.52],
        low_confidence_fields: ["dosage"],
        review_status: "pending_review",
        version: 3,
        trust_state: "unconfirmed_prefill",
        requires_user_confirmation: true,
        plan_created: false,
        confirmation_endpoint: "/api/medications/trust/plans/confirm"
    )
}

private func makeMedicationRecognitionResult(
    clientEventID: String = "ocr-event-1"
) -> MedicationRecognitionResult {
    MedicationRecognitionResult(
        name: "阿托伐他汀钙片",
        dosage: "20mg",
        frequency: "每日一次",
        instructions: "晚饭后服用",
        schedule_times: ["20:00"],
        candidate_id: 41,
        candidate_version: 3,
        client_event_id: clientEventID,
        field_confidences: ["name": 0.98, "dosage": 0.52],
        low_confidence_fields: ["dosage"],
        trust_state: "unconfirmed_prefill",
        requires_user_confirmation: true,
        plan_created: false,
        confirmation_endpoint: "/api/medications/trust/plans/confirm"
    )
}

private func makeMedicationConfirmRequest(
    clientEventID: String
) -> MedicationPlanConfirmRequest {
    MedicationPlanConfirmRequest(
        subject_user_id: 1,
        client_request_id: clientEventID,
        client_event_id: clientEventID,
        candidate_id: 41,
        candidate_version: 3,
        generic_name: "阿托伐他汀钙片",
        brand_name: "立普妥",
        strength: "20mg/片",
        dose_text: "20mg",
        dose_quantity: 1,
        frequency: "每日一次",
        schedule_times: ["20:00"],
        meal_relation: .afterMeal,
        instructions: "晚饭后服用",
        course_start: "2026-07-01",
        course_end: nil,
        prescriber: "测试医生",
        initial_quantity: 30,
        inventory_unit: "片",
        is_long_term: true,
        source_type: .ocr,
        source_ref: "ocr:41"
    )
}

private func makeMedicationDoseEvent(
    clientEventRequest: MedicationDoseActionRequest? = nil
) -> MedicationDoseEvent {
    let effectiveStatus: String
    switch clientEventRequest?.action {
    case .snooze: effectiveStatus = "snoozed"
    case .skip: effectiveStatus = "skipped"
    case .correct: effectiveStatus = clientEventRequest?.corrected_status?.rawValue ?? "pending"
    case .taken, .none: effectiveStatus = "taken"
    }
    return MedicationDoseEvent(
        event_id: 91,
        occurrence_key: "plan-7:2026-07-15:20:00",
        occurrence_version: 3,
        action: clientEventRequest?.action.rawValue ?? "taken",
        effective_status: effectiveStatus,
        supersedes_event_id: nil,
        snoozed_until: clientEventRequest?.snoozed_until,
        taken_quantity: clientEventRequest?.taken_quantity,
        reason: clientEventRequest?.reason,
        confirmed_at: "2026-07-15T20:05:00+08:00",
        trust_state: "user_confirmed",
        notification_schedule_status: "not_requested",
        reminder_management: "client_managed"
    )
}

private func makeMedicationReaction(version: Int = 1) -> MedicationReaction {
    MedicationReaction(
        reaction_key: "reaction-1",
        reaction_version: version,
        plan_id: 7,
        symptoms: "头晕",
        onset_at: "2026-07-15T21:00:00+08:00",
        severity: .mild,
        duration_minutes: 20,
        related_occurrence_key: "plan-7:2026-07-15:20:00",
        notes: nil,
        status: "active",
        causal_attribution: "temporal_association_only",
        user_facing_causality: "该症状发生在服药后，不能据此认定由药物导致",
        safety_guidance: "如症状持续、加重或影响日常活动，请及时联系医生或药师。",
        confirmed_at: "2026-07-15T21:10:00+08:00"
    )
}

private actor HealthProfileTrustRepositorySpy: PatientHistoryRepositoryProtocol {
    private let fetched: HealthProfileTrustResponse
    private let mutationResponse: HealthProfileTrustResponse
    private var candidateFailuresRemaining: Int
    private var reviews: [HealthProfileCandidateReviewRequest] = []
    private var upserts: [HealthProfileFactUpsertRequest] = []
    private var retractions: [HealthProfileFactRetractRequest] = []
    private var goalCreates: [HealthProfileGoalCreateRequest] = []
    private var goalUpdates: [HealthProfileGoalUpdateRequest] = []
    private var goalStatuses: [HealthProfileGoalStatusRequest] = []

    init(
        fetched: HealthProfileTrustResponse,
        mutationResponse: HealthProfileTrustResponse,
        candidateFailuresRemaining: Int = 0
    ) {
        self.fetched = fetched
        self.mutationResponse = mutationResponse
        self.candidateFailuresRemaining = candidateFailuresRemaining
    }

    func fetchProfile() async throws -> HealthProfileTrustResponse {
        fetched
    }

    func fetchLongTermMedicationSummary(
        subjectUserID: Int
    ) async throws -> HealthProfileLongTermMedicationSummary {
        HealthProfileLongTermMedicationSummary(subject_user_id: subjectUserID, items: [])
    }

    func fetchFactRevisions(
        factID: Int,
        subjectUserID: Int,
        afterRevisionID: Int?
    ) async throws -> HealthProfileRevisionList {
        HealthProfileRevisionList(
            subject_user_id: subjectUserID,
            target_kind: .fact,
            target_id: factID,
            items: [],
            next_after_revision_id: nil
        )
    }

    func fetchGoalRevisions(
        goalID: Int,
        subjectUserID: Int,
        afterRevisionID: Int?
    ) async throws -> HealthProfileRevisionList {
        HealthProfileRevisionList(
            subject_user_id: subjectUserID,
            target_kind: .goal,
            target_id: goalID,
            items: [],
            next_after_revision_id: nil
        )
    }

    func reviewCandidate(
        candidateID: Int,
        request: HealthProfileCandidateReviewRequest,
        expectedAccountScope: String
    ) async throws -> HealthProfileTrustResponse {
        reviews.append(request)
        if candidateFailuresRemaining > 0 {
            candidateFailuresRemaining -= 1
            throw URLError(.timedOut)
        }
        return mutationResponse
    }

    func upsertFact(
        _ request: HealthProfileFactUpsertRequest,
        expectedAccountScope: String
    ) async throws -> HealthProfileTrustResponse {
        upserts.append(request)
        return mutationResponse
    }

    func retractFact(
        factID: Int,
        request: HealthProfileFactRetractRequest,
        expectedAccountScope: String
    ) async throws -> HealthProfileTrustResponse {
        retractions.append(request)
        return mutationResponse
    }

    func createGoal(
        _ request: HealthProfileGoalCreateRequest,
        expectedAccountScope: String
    ) async throws -> HealthProfileTrustResponse {
        goalCreates.append(request)
        return mutationResponse
    }

    func updateGoal(
        goalID: Int,
        request: HealthProfileGoalUpdateRequest,
        expectedAccountScope: String
    ) async throws -> HealthProfileTrustResponse {
        goalUpdates.append(request)
        return mutationResponse
    }

    func updateGoalStatus(
        goalID: Int,
        request: HealthProfileGoalStatusRequest,
        expectedAccountScope: String
    ) async throws -> HealthProfileTrustResponse {
        goalStatuses.append(request)
        return mutationResponse
    }

    func candidateRequests() -> [HealthProfileCandidateReviewRequest] { reviews }
    func upsertRequests() -> [HealthProfileFactUpsertRequest] { upserts }
    func retractionRequests() -> [HealthProfileFactRetractRequest] { retractions }
    func goalCreateRequests() -> [HealthProfileGoalCreateRequest] { goalCreates }
    func goalUpdateRequests() -> [HealthProfileGoalUpdateRequest] { goalUpdates }
    func goalStatusRequests() -> [HealthProfileGoalStatusRequest] { goalStatuses }
}

private func makeHealthProfileTrustResponse(
    includeCandidate: Bool = true,
    includeAcceptedFact: Bool = false
) -> HealthProfileTrustResponse {
    let source = HealthProfileSource(
        source_id: 501,
        source_type: "report",
        source_ref: "report-1001",
        confidence: 0.91,
        source_snapshot: ["workflow_id": .number(1001)],
        created_at: "2026-07-15T07:00:00Z"
    )
    var facts = [
        HealthProfileFact(
            fact_id: 201,
            fact_key: "basic.birth_date",
            category: "basic",
            value_data: ["response_state": .string("value"), "value": .string("1985-06-18")],
            is_safety_critical: false,
            confirmation_method: "user",
            version: 2,
            confirmed_at: "2026-07-14T08:00:00Z",
            updated_at: "2026-07-15T08:00:00Z",
            sources: [source]
        )
    ]
    if includeAcceptedFact {
        facts.append(
            HealthProfileFact(
                fact_id: 203,
                fact_key: "long_term_health.repeated_abnormal.uric_acid",
                category: "long_term_health",
                value_data: ["canonical_name": .string("尿酸"), "occurrence_count": .number(3)],
                is_safety_critical: false,
                confirmation_method: "user",
                version: 1,
                confirmed_at: "2026-07-15T08:05:00Z",
                updated_at: "2026-07-15T08:05:00Z",
                sources: [source]
            )
        )
    }
    let candidates = includeCandidate ? [
        HealthProfileCandidate(
            candidate_id: 301,
            fact_key: "long_term_health.repeated_abnormal.uric_acid",
            category: "long_term_health",
            proposed_value: ["canonical_name": .string("尿酸"), "occurrence_count": .number(3)],
            is_safety_critical: false,
            review_status: "pending_review",
            conflict_with_fact_id: nil,
            confidence: 0.91,
            version: 2,
            created_at: "2026-07-15T07:00:00Z",
            updated_at: "2026-07-15T08:00:00Z",
            sources: [source]
        )
    ] : []
    return HealthProfileTrustResponse(
        subject_user_id: 1,
        profile_status: "needs_attention",
        overview: HealthProfileOverview(
            completeness_percent: 40,
            resolved_required_weight: 6,
            total_required_weight: 15,
            missing_required_fact_keys: ["basic.height", "safety.medication_allergy", "goal.primary"],
            pending_update_count: candidates.count,
            independent_source_count: 9,
            primary_action: HealthProfilePrimaryAction(
                kind: includeCandidate ? "review_updates" : "complete_profile",
                item_count: includeCandidate ? 1 : 3,
                localization_key: includeCandidate
                    ? "health_profile.primary_action.review_updates"
                    : "health_profile.primary_action.complete_profile",
                route: includeCandidate ? "profile_updates" : "profile_editor"
            )
        ),
        facts: facts,
        candidates: candidates,
        goals: [],
        management_plans: [
            HealthProfileManagementPlan(
                plan_id: 801,
                title: "七天稳糖计划",
                goal: "稳定餐后血糖",
                start_date: "2026-07-15",
                end_date: "2026-07-21",
                status: "active",
                created_by: "questionnaire",
                updated_at: "2026-07-15T08:00:00Z",
                task_count: 7,
                completed_task_count: 3
            )
        ]
    )
}

private actor HealthReportReviewRepositorySpy: HealthReportReviewRepositoryProtocol {
    private var fetchResponse: HealthReportReview
    private let confirmResponse: HealthReportReview
    private var failuresRemaining: Int
    private var manualFailuresRemaining: Int
    private let confirmDelayNanoseconds: UInt64
    private var requests: [HealthReportConfirmationRequest] = []
    private var manualRequests: [HealthReportManualCandidateRequest] = []

    init(
        fetchResponse: HealthReportReview,
        confirmResponse: HealthReportReview,
        failuresRemaining: Int = 0,
        manualFailuresRemaining: Int = 0,
        confirmDelayNanoseconds: UInt64 = 0
    ) {
        self.fetchResponse = fetchResponse
        self.confirmResponse = confirmResponse
        self.failuresRemaining = failuresRemaining
        self.manualFailuresRemaining = manualFailuresRemaining
        self.confirmDelayNanoseconds = confirmDelayNanoseconds
    }

    func fetchReportReview(workflowID: Int, subjectUserID: Int) async throws -> HealthReportReview {
        fetchResponse
    }

    func fetchReportInterpretation(
        workflowID: Int,
        subjectUserID: Int
    ) async throws -> HealthReportInterpretation {
        makeHealthReportInterpretation()
    }

    func setFetchResponse(_ response: HealthReportReview) {
        fetchResponse = response
    }

    func confirmReport(
        workflowID: Int,
        request: HealthReportConfirmationRequest,
        expectedAccountScope: String
    ) async throws -> HealthReportReview {
        requests.append(request)
        if confirmDelayNanoseconds > 0 {
            try await Task.sleep(nanoseconds: confirmDelayNanoseconds)
        }
        if failuresRemaining > 0 {
            failuresRemaining -= 1
            throw URLError(.timedOut)
        }
        return confirmResponse
    }

    func confirmationRequests() -> [HealthReportConfirmationRequest] {
        requests
    }

    func addManualReportCandidate(
        workflowID: Int,
        request: HealthReportManualCandidateRequest,
        expectedAccountScope: String
    ) async throws -> HealthReportReview {
        manualRequests.append(request)
        if manualFailuresRemaining > 0 {
            manualFailuresRemaining -= 1
            throw URLError(.timedOut)
        }
        return fetchResponse
    }

    func manualCandidateRequests() -> [HealthReportManualCandidateRequest] {
        manualRequests
    }
}

private func makeHealthReportCandidate(
    reviewStatus: HealthReportCandidateReviewStatus = .pendingReview,
    requiresReview: Bool = true,
    conflictReasons: [String] = [],
    version: Int = 1
) -> HealthReportFieldCandidate {
    HealthReportFieldCandidate(
        candidate_id: 101,
        candidate_key: "glucose-101",
        version: version,
        canonical_code: "glucose",
        canonical_name: "空腹血糖",
        raw_name: "葡萄糖",
        raw_value: "8.2",
        raw_unit: "mmol/L",
        normalized_value: 8.2,
        normalized_text: nil,
        normalized_unit: "mmol/L",
        reference_low: 3.9,
        reference_high: 6.1,
        reference_text: "3.9–6.1 mmol/L",
        abnormal_state: "abnormal",
        confidence: 0.61,
        low_confidence: true,
        conflict_reasons: conflictReasons,
        effective_at: "2026-07-15T00:00:00Z",
        source_locator: [
            "source_type": .string("pdf"),
            "page": .number(2),
            "row_index": .number(3)
        ],
        model_version: "fixture-v1",
        review_status: reviewStatus,
        requires_review: requiresReview
    )
}

private func makeHealthReportReview(
    status: HealthReportWorkflowStatus,
    version: Int = 3,
    confirmationClientEventID: String? = nil,
    pendingCount: Int = 1,
    requiresConfirmation: Bool = true,
    canConfirm: Bool = true,
    failureRecovery: HealthReportFailureRecovery? = nil,
    candidateStatus: HealthReportCandidateReviewStatus = .pendingReview,
    candidateRequiresReview: Bool = true,
    candidateVersion: Int = 1
) -> HealthReportReview {
    HealthReportReview(
        workflow_id: 4242,
        legacy_document_id: 4242,
        subject_user_id: 1,
        status: status,
        version: version,
        report_type: "exam",
        document_fingerprint: "fixture-sha256",
        recognized_at: "2026-07-15T08:00:00Z",
        confirmed_at: nil,
        completed_at: nil,
        confirmation_client_event_id: confirmationClientEventID,
        failure_code: nil,
        failure_detail: nil,
        failure_recovery: failureRecovery,
        pending_review_count: pendingCount,
        auto_accepted_count: 0,
        admitted_observation_count: status == .completed || status == .completedScorePending ? 1 : 0,
        requires_report_confirmation: requiresConfirmation,
        can_confirm: canConfirm,
        document: nil,
        candidates: [
            makeHealthReportCandidate(
                reviewStatus: candidateStatus,
                requiresReview: candidateRequiresReview,
                version: candidateVersion
            )
        ]
    )
}

private func makeHealthReportInterpretation() -> HealthReportInterpretation {
    let candidate = makeHealthReportCandidate(
        reviewStatus: .confirmed,
        requiresReview: false,
        version: 2
    )
    let observation = HealthReportObservation(
        observation_id: 801,
        source_candidate_id: candidate.candidate_id,
        confirmation_event_id: 901,
        canonical_code: candidate.canonical_code,
        canonical_name: candidate.canonical_name,
        value_numeric: candidate.normalized_value,
        value_text: candidate.normalized_text,
        unit: candidate.normalized_unit,
        reference_low: candidate.reference_low,
        reference_high: candidate.reference_high,
        reference_text: candidate.reference_text,
        abnormal_state: "abnormal",
        effective_at: "2026-07-15T00:00:00Z",
        confirmed_at: "2026-07-15T08:05:00Z"
    )
    let profileImpact = HealthReportProfileImpact(
        profile_candidate_id: 301,
        source_id: 501,
        source_observation_id: observation.observation_id,
        fact_key: "long_term_health.glucose",
        category: "long_term_health",
        proposed_value: ["latest_value_numeric": .string("8.2")],
        review_status: "pending_review",
        confidence: 0.61
    )
    return HealthReportInterpretation(
        workflow_id: 4242,
        subject_user_id: 1,
        status: .completedScorePending,
        available: true,
        unavailable_reason: nil,
        non_diagnostic_notice: "本解读仅依据已确认数据，不构成诊断或治疗建议。",
        document: ["file_url": .string("/api/health-data/documents/4242/file")],
        candidates: [candidate],
        confirmation_events: [
            HealthReportConfirmationEvent(
                event_id: 901,
                candidate_id: candidate.candidate_id,
                event_type: "confirm",
                candidate_version: 1,
                before_data: ["value_numeric": .string("8.2")],
                after_data: ["value_numeric": .string("8.2")],
                created_at: "2026-07-15T08:05:00Z"
            )
        ],
        structured_additions: [observation],
        major_abnormalities: [observation],
        follow_up: HealthReportFollowUp(
            available: false,
            items: [],
            unavailable_reason: "没有经过确认的随访信息；系统不会自行推断。"
        ),
        profile_impacts: [
            profileImpact,
            HealthReportProfileImpact(
                profile_candidate_id: profileImpact.profile_candidate_id,
                source_id: 502,
                source_observation_id: 802,
                fact_key: profileImpact.fact_key,
                category: profileImpact.category,
                proposed_value: profileImpact.proposed_value,
                review_status: profileImpact.review_status,
                confidence: profileImpact.confidence
            )
        ],
        score_state: "partial_failed",
        score_pending: true,
        score_snapshots: [
            HealthReportScoreSnapshot(
                snapshot_id: 701,
                score_kind: "stress",
                algorithm_id: "trusted-score",
                algorithm_version: "2026.07",
                before_value: 58,
                after_value: 54,
                before_confidence: 0.8,
                after_confidence: 0.85,
                score_direction: "lower_is_better",
                semantic_outcome: "improved",
                calculation_status: "completed",
                evidence: ["observation_ids": .array([.number(801)])],
                missing_inputs: [:],
                failure_code: nil,
                computed_at: "2026-07-15T08:06:00Z"
            ),
            HealthReportScoreSnapshot(
                snapshot_id: 702,
                score_kind: "inflammation",
                algorithm_id: "trusted-score",
                algorithm_version: "2026.07",
                before_value: nil,
                after_value: nil,
                before_confidence: nil,
                after_confidence: nil,
                score_direction: nil,
                semantic_outcome: nil,
                calculation_status: "failed",
                evidence: [:],
                missing_inputs: ["required": .array([.string("hs_crp")])],
                failure_code: "insufficient_evidence",
                computed_at: "2026-07-15T08:06:00Z"
            )
        ]
    )
}
