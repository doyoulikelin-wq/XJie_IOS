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
            try request("/api/chat/conversations?limit=0&offset=0"),
            try request("/api/chat/conversations?limit=-1"),
            try request("/api/chat/conversations?limit=abc"),
            try request("/api/chat/conversations?limit=20&limit=10"),
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

    func testAccountBoundNetworkAndServerRetriesRequireSameAccountBeforeAndAfterBackoff() {
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

}
