import Foundation
import UIKit
import XCTest
@testable import Xjie

@MainActor
final class DietaryRecordsTests: XCTestCase {
    private let dashboardPath = "/api/dietary-records/dashboard?diet_date=2026-07-15&timezone=Asia/Shanghai"

    func testDietaryDayBoundaryUsesLocalFourAMAndNeverAllowsFutureSelection() async throws {
        let calendar = shanghaiCalendar()
        let beforeBoundary = try XCTUnwrap(Self.iso.date(from: "2026-07-15T03:59:59+08:00"))
        let atBoundary = try XCTUnwrap(Self.iso.date(from: "2026-07-15T04:00:00+08:00"))
        let today = try XCTUnwrap(Self.iso.date(from: "2026-07-15T18:00:00+08:00"))

        XCTAssertEqual(DietaryDayBoundary.dateKey(for: beforeBoundary, calendar: calendar), "2026-07-14")
        XCTAssertEqual(DietaryDayBoundary.dateKey(for: atBoundary, calendar: calendar), "2026-07-15")
        XCTAssertEqual(
            DietaryDayBoundary.clampedSelection(
                calendar.date(byAdding: .day, value: 1, to: today) ?? today,
                now: today,
                calendar: calendar
            ),
            calendar.startOfDay(for: today),
            "日期切换不能进入未来"
        )

        let beforePath = "/api/dietary-records/dashboard?diet_date=2026-07-14&timezone=Asia/Shanghai"
        let beforeMock = MockAPIService()
        await beforeMock.setRawResponse(
            for: beforePath,
            data: dashboardData(selectedDate: "2026-07-14", isToday: true, summaryDate: "2026-07-13")
        )
        var mutableNow = beforeBoundary
        let beforeViewModel = makeViewModel(api: beforeMock, nowProvider: { mutableNow })
        XCTAssertEqual(beforeViewModel.selectedDateKey, "2026-07-14")
        XCTAssertEqual(beforeViewModel.todayKey, "2026-07-14")
        XCTAssertFalse(beforeViewModel.canMoveForward)
        await beforeViewModel.fetchData()
        XCTAssertTrue(beforeViewModel.isSelectedToday)
        var beforePaths = await beforeMock.requestedPaths
        XCTAssertEqual(beforePaths, [beforePath], "03:59 的 dashboard query 必须仍属于前一饮食日")

        await beforeViewModel.selectDate(
            try XCTUnwrap(Self.iso.date(from: "2026-07-15T12:00:00+08:00"))
        )
        beforePaths = await beforeMock.requestedPaths
        XCTAssertEqual(beforeViewModel.selectedDateKey, "2026-07-14")
        XCTAssertEqual(beforePaths, [beforePath], "03:59 不能前进到尚未开始的下一饮食日")

        let rolledDashboardPath = "\(dashboardPath)&subject_user_id=1"
        await beforeMock.setRawResponse(
            for: rolledDashboardPath,
            data: dashboardData(selectedDate: "2026-07-15", isToday: true, summaryDate: "2026-07-14")
        )
        await beforeMock.setRawResponse(for: "/api/dietary-records/drafts", data: draftData())
        mutableNow = atBoundary
        await beforeViewModel.fetchData()
        XCTAssertEqual(beforeViewModel.selectedDateKey, "2026-07-15", "同一实例跨过 04:00 后必须自动推进饮食日")
        let rolloverDraft = await beforeViewModel.createDescriptionDraft("鸡蛋和牛奶", source: .text)
        XCTAssertNotNil(rolloverDraft)
        let rolloverBody = await beforeMock.requestBodyJSON(for: "/api/dietary-records/drafts")
        XCTAssertEqual(rolloverBody?["diet_date"] as? String, "2026-07-15")
        let rolloverPhotoData = UIGraphicsImageRenderer(size: CGSize(width: 8, height: 8)).pngData { context in
            UIColor.systemOrange.setFill()
            context.fill(CGRect(x: 0, y: 0, width: 8, height: 8))
        }
        await beforeMock.setRawResponse(
            for: "/api/dietary-records/drafts/photo",
            data: draftData(source: "photo_library")
        )
        let rolloverPhoto = await beforeViewModel.createPhotoDraft(
            rolloverPhotoData,
            fileName: "rollover.png",
            source: .photoLibrary
        )
        XCTAssertNotNil(rolloverPhoto)
        let rolloverUploads = await beforeMock.accountBoundFileUploads()
        let rolloverUpload = try XCTUnwrap(rolloverUploads.last)
        XCTAssertEqual(rolloverUpload.formData["diet_date"], "2026-07-15")
        XCTAssertEqual(rolloverUpload.formData["timezone"], "Asia/Shanghai")

        let recentRecord = try JSONDecoder().decode(
            DietaryMealRecord.self,
            from: recordData(status: "user_confirmed", version: 3)
        )
        await beforeMock.setRawResponse(
            for: "/api/dietary-records/records/1/reuse",
            data: draftData(id: 3, source: "recent")
        )
        let rolloverReuse = await beforeViewModel.reuseRecord(recentRecord)
        XCTAssertNotNil(rolloverReuse)
        let rolloverReuseBody = await beforeMock.requestBodyJSON(for: "/api/dietary-records/records/1/reuse")
        XCTAssertEqual(rolloverReuseBody?["diet_date"] as? String, "2026-07-15")
        XCTAssertEqual(rolloverReuseBody?["timezone"] as? String, "Asia/Shanghai")
        beforePaths = await beforeMock.requestedPaths
        XCTAssertEqual(beforePaths, [
            beforePath,
            rolledDashboardPath,
            "/api/dietary-records/drafts",
            "/api/dietary-records/drafts/photo",
            "/api/dietary-records/records/1/reuse",
        ])

        let historyMock = MockAPIService()
        var historyNow = beforeBoundary
        let historyViewModel = makeViewModel(api: historyMock, nowProvider: { historyNow })
        let historyPath = "/api/dietary-records/dashboard?diet_date=2026-07-13&timezone=Asia/Shanghai&subject_user_id=1"
        await historyMock.setRawResponse(
            for: beforePath,
            data: dashboardData(selectedDate: "2026-07-14", isToday: true, summaryDate: "2026-07-13")
        )
        await historyMock.setRawResponse(
            for: historyPath,
            data: dashboardData(selectedDate: "2026-07-13", isToday: false, summaryDate: "2026-07-13")
        )
        await historyViewModel.fetchData()
        await historyViewModel.selectDate(try XCTUnwrap(Self.iso.date(from: "2026-07-13T12:00:00+08:00")))
        historyNow = atBoundary
        await historyViewModel.fetchData()
        XCTAssertEqual(historyViewModel.selectedDateKey, "2026-07-13", "用户主动查看历史时，04:00 rollover 不得抢回今天")
        await historyMock.setRawResponse(
            for: "/api/dietary-records/records/1/reuse",
            data: draftData(id: 4, source: "recent", dietDate: "2026-07-13")
        )
        let historyReuse = await historyViewModel.reuseRecord(recentRecord)
        XCTAssertEqual(historyReuse?.dietDate, "2026-07-13")
        let historyReuseBody = await historyMock.requestBodyJSON(for: "/api/dietary-records/records/1/reuse")
        XCTAssertEqual(historyReuseBody?["diet_date"] as? String, "2026-07-13")
        let historyPaths = await historyMock.requestedPaths
        XCTAssertEqual(historyPaths, [beforePath, historyPath, historyPath, "/api/dietary-records/records/1/reuse"])

        let travelMock = MockAPIService()
        var travelZone = "Asia/Shanghai"
        let travelViewModel = makeViewModel(
            api: travelMock,
            nowProvider: { atBoundary },
            timeZoneProvider: { travelZone }
        )
        XCTAssertEqual(travelViewModel.selectedDateKey, "2026-07-15")
        travelZone = "America/Los_Angeles"
        await travelMock.setRawResponse(
            for: "/api/dietary-records/drafts",
            data: draftData(
                dietDate: "2026-07-14",
                timezone: "America/Los_Angeles",
                eatenAt: "2026-07-14T13:00:00-07:00"
            )
        )
        let travelDraft = await travelViewModel.createDescriptionDraft("跨时区午餐", source: .text)
        XCTAssertEqual(travelViewModel.selectedDateKey, "2026-07-14")
        XCTAssertEqual(travelDraft?.dietDate, "2026-07-14")
        let travelBody = await travelMock.requestBodyJSON(for: "/api/dietary-records/drafts")
        XCTAssertEqual(travelBody?["timezone"] as? String, "America/Los_Angeles")
        XCTAssertEqual(travelBody?["diet_date"] as? String, "2026-07-14")
        XCTAssertEqual(travelBody?["eaten_at"] as? String, "2026-07-14T13:00:00-07:00")
        XCTAssertEqual(travelBody?["meal_type"] as? String, "lunch")

        let rolloverFailureMock = MockAPIService()
        await rolloverFailureMock.setRawResponse(
            for: beforePath,
            data: try dashboardWithContentData(
                selectedDate: "2026-07-14",
                isToday: true,
                summaryDate: "2026-07-13"
            )
        )
        var rolloverFailureNow = beforeBoundary
        let rolloverFailureViewModel = makeViewModel(
            api: rolloverFailureMock,
            nowProvider: { rolloverFailureNow }
        )
        await rolloverFailureViewModel.fetchData()
        XCTAssertEqual(rolloverFailureViewModel.records.count, 1)
        XCTAssertEqual(rolloverFailureViewModel.pendingDrafts.count, 1)
        XCTAssertNotNil(rolloverFailureViewModel.displayedSummary)
        XCTAssertNotNil(rolloverFailureViewModel.weeklyReview)
        XCTAssertEqual(rolloverFailureViewModel.recordedMealCount, 1)
        XCTAssertEqual(rolloverFailureViewModel.pendingCount, 1)

        rolloverFailureNow = atBoundary
        await rolloverFailureMock.setError(URLError(.notConnectedToInternet))
        let rolloverFailureDraft = await rolloverFailureViewModel.createDescriptionDraft(
            "跨界后的第一餐",
            source: .text
        )
        XCTAssertNil(rolloverFailureDraft)
        XCTAssertEqual(rolloverFailureViewModel.selectedDateKey, "2026-07-15")
        XCTAssertTrue(rolloverFailureViewModel.records.isEmpty)
        XCTAssertTrue(rolloverFailureViewModel.pendingDrafts.isEmpty)
        XCTAssertNil(rolloverFailureViewModel.selectedDaySummary)
        XCTAssertNil(
            rolloverFailureViewModel.displayedSummary,
            "04:00 后即使新请求失败，也不能在新日期标题下显示旧日结论"
        )
        XCTAssertNil(rolloverFailureViewModel.weeklyReview)
        XCTAssertEqual(rolloverFailureViewModel.recordedMealCount, 0)
        XCTAssertEqual(rolloverFailureViewModel.pendingCount, 0)
        XCTAssertEqual(rolloverFailureViewModel.streakDays, 0)
        XCTAssertEqual(rolloverFailureViewModel.dayState, .unknown)
        XCTAssertEqual(rolloverFailureViewModel.loadState, .idle)
        let rolloverFailurePaths = await rolloverFailureMock.requestedPaths
        XCTAssertEqual(rolloverFailurePaths, [beforePath, "/api/dietary-records/drafts"])

        let boundaryMock = MockAPIService()
        await boundaryMock.setRawResponse(
            for: dashboardPath,
            data: dashboardData(selectedDate: "2026-07-15", isToday: true, summaryDate: "2026-07-14")
        )
        let boundaryViewModel = makeViewModel(api: boundaryMock, now: atBoundary)
        XCTAssertEqual(boundaryViewModel.selectedDateKey, "2026-07-15")
        XCTAssertEqual(boundaryViewModel.todayKey, "2026-07-15")
        await boundaryViewModel.fetchData()
        XCTAssertTrue(boundaryViewModel.isSelectedToday)
        let boundaryPaths = await boundaryMock.requestedPaths
        XCTAssertEqual(boundaryPaths, [dashboardPath], "04:00 起 dashboard query 必须切到新饮食日")
    }

    func testFiveInputSourcesCreatePendingDraftAndFormalSaveRequiresExplicitConfirmation() async throws {
        XCTAssertEqual(
            DietaryEntrySource.userFacingSources,
            [.camera, .photoLibrary, .text, .voice, .recent],
            "记录一餐必须统一提供五种录入来源"
        )
        let chatDraft = "午餐吃了番茄炒蛋，我还要补充份量"
        let mealAction = try XCTUnwrap(
            XAgeConversationNavigationAction.available.first(where: { $0.destination == .meals })
        )
        let handoff = mealAction.handoff(preserving: chatDraft)
        XCTAssertEqual(handoff.dietaryEntry, DietaryEntryHandoff(source: .chat, draftText: chatDraft))
        XCTAssertNil(mealAction.handoff(preserving: "  \n ").dietaryEntry, "空对话草稿只导航，不伪造膳食输入")

        let mock = MockAPIService()
        let prefilledRequestPaths = await mock.requestedPaths
        XCTAssertTrue(prefilledRequestPaths.isEmpty, "typed handoff 只能预填，不能自动创建服务器草稿")
        await mock.setRawResponse(for: "/api/dietary-records/drafts", data: draftData())
        await mock.setRawResponse(
            for: "/api/dietary-records/drafts/1/confirm",
            data: recordData(status: "user_confirmed", version: 1)
        )
        let viewModel = makeViewModel(api: mock)

        let draft = await viewModel.createDescriptionDraft(
            "番茄炒蛋一碗、米饭半碗",
            source: .text
        )

        XCTAssertEqual(draft?.status, .pendingConfirmation)
        XCTAssertEqual(draft?.requiresUserConfirmation, true)
        var paths = await mock.requestedPaths
        XCTAssertEqual(paths, ["/api/dietary-records/drafts"])
        XCTAssertFalse(paths.contains(where: { $0 == "/api/meals" || $0.contains("/confirm") }))
        let createDraftBody = await mock.requestBodyJSON(for: "/api/dietary-records/drafts")
        XCTAssertEqual(createDraftBody?["raw_input"] as? String, "番茄炒蛋一碗、米饭半碗")
        XCTAssertEqual((createDraftBody?["food_items"] as? [[String: Any]])?.count, 0, "客户端不能把整句伪装成食物名")

        var editable = try XCTUnwrap(draft.map(DietaryEditableDraft.init))
        editable.foodItems[0].portionText = "1 小碗"
        let saved = await viewModel.confirmDraft(editable)

        XCTAssertEqual(saved?.status, .userConfirmed)
        paths = await mock.requestedPaths
        XCTAssertEqual(paths.last, "/api/dietary-records/drafts/1/confirm")
        XCTAssertFalse(paths.contains("/api/meals"), "新膳食链不得回写旧正式 Meal 接口")
        let body = await mock.requestBodyJSON(for: "/api/dietary-records/drafts/1/confirm")
        XCTAssertEqual(body?["subject_user_id"] as? Int, 1)
        XCTAssertEqual(body?["expected_version"] as? Int, 1)
        XCTAssertEqual(body?["client_event_id"] as? String, "event-1")
        XCTAssertEqual(body?["timezone"] as? String, "Asia/Shanghai")
        XCTAssertEqual((body?["field_confidences"] as? [String: Any])?["food_items"] as? Double, 0.62)
        XCTAssertEqual(body?["recognition_confidence"] as? Double, 0.62)
        XCTAssertEqual(
            ((body?["food_items"] as? [[String: Any]])?.first)?["portion_text"] as? String,
            "1 小碗"
        )

        // A lost response must replay the exact first wire snapshot. Neither a
        // time-zone change nor an edit may overwrite an unresolved event. Once
        // an explicit 4xx rejection clears it, the edit becomes a new event.
        let immutableRetryMock = MockAPIService()
        await immutableRetryMock.setError(URLError(.networkConnectionLost))
        var retryZone = "Asia/Shanghai"
        var retryEventSequence = 0
        let immutableRetryViewModel = makeViewModel(
            api: immutableRetryMock,
            nowProvider: { Self.iso.date(from: "2026-07-15T18:00:00+08:00")! },
            timeZoneProvider: { retryZone },
            makeID: {
                retryEventSequence += 1
                return "immutable-confirm-\(retryEventSequence)"
            }
        )
        let retryDraft = try JSONDecoder().decode(DietaryMealDraft.self, from: draftData())
        var retryEditable = DietaryEditableDraft(retryDraft)
        retryEditable.foodItems[0].portionText = "一小碗"
        let firstRetry = await immutableRetryViewModel.confirmDraft(retryEditable)
        XCTAssertNil(firstRetry)
        let firstRetryBody = await immutableRetryMock.requestBodyJSON(
            for: "/api/dietary-records/drafts/1/confirm"
        )

        retryZone = "America/Los_Angeles"
        let zoneChangedRetry = await immutableRetryViewModel.confirmDraft(retryEditable)
        XCTAssertNil(zoneChangedRetry)
        let zoneChangedRetryBody = await immutableRetryMock.requestBodyJSON(
            for: "/api/dietary-records/drafts/1/confirm"
        )
        XCTAssertEqual(
            try canonicalJSON(zoneChangedRetryBody),
            try canonicalJSON(firstRetryBody),
            "响应丢失后即使系统时区变化，也必须逐字节重放原 confirm 请求"
        )
        XCTAssertEqual(zoneChangedRetryBody?["timezone"] as? String, "Asia/Shanghai")

        retryEditable.foodItems[0].portionText = "两小碗"
        let unresolvedEditedRetry = await immutableRetryViewModel.confirmDraft(retryEditable)
        XCTAssertNil(unresolvedEditedRetry)
        let unresolvedEditedBody = await immutableRetryMock.requestBodyJSON(
            for: "/api/dietary-records/drafts/1/confirm"
        )
        XCTAssertEqual(
            try canonicalJSON(unresolvedEditedBody),
            try canonicalJSON(firstRetryBody),
            "旧事件结果未确定前，用户编辑也不能覆盖原 wire snapshot"
        )

        await immutableRetryMock.setError(APIError.httpErrorResponse(409, "version conflict", Data()))
        let rejectedOldEvent = await immutableRetryViewModel.confirmDraft(retryEditable)
        XCTAssertNil(rejectedOldEvent)
        let rejectedOldBody = await immutableRetryMock.requestBodyJSON(
            for: "/api/dietary-records/drafts/1/confirm"
        )
        XCTAssertEqual(try canonicalJSON(rejectedOldBody), try canonicalJSON(firstRetryBody))

        await immutableRetryMock.setError(URLError(.networkConnectionLost))
        let firstEditedAttempt = await immutableRetryViewModel.confirmDraft(retryEditable)
        XCTAssertNil(firstEditedAttempt)
        let editedRetryBody = await immutableRetryMock.requestBodyJSON(
            for: "/api/dietary-records/drafts/1/confirm"
        )
        XCTAssertNotEqual(
            editedRetryBody?["client_event_id"] as? String,
            firstRetryBody?["client_event_id"] as? String,
            "明确 4xx 已解决旧事件后，用户编辑必须创建新事件"
        )
        XCTAssertEqual(editedRetryBody?["timezone"] as? String, "America/Los_Angeles")
        XCTAssertEqual(
            ((editedRetryBody?["food_items"] as? [[String: Any]])?.first)?["portion_text"] as? String,
            "两小碗"
        )

        retryZone = "Asia/Shanghai"
        await immutableRetryMock.setRawResponse(
            for: "/api/dietary-records/drafts/1/confirm",
            data: recordData(status: "user_confirmed", version: 1)
        )
        await immutableRetryMock.setError(nil)
        let successfulReplay = await immutableRetryViewModel.confirmDraft(retryEditable)
        XCTAssertNotNil(successfulReplay)
        let successfulReplayBody = await immutableRetryMock.requestBodyJSON(
            for: "/api/dietary-records/drafts/1/confirm"
        )
        XCTAssertEqual(
            try canonicalJSON(successfulReplayBody),
            try canonicalJSON(editedRetryBody),
            "成功前的最后一次重试必须继续发送已缓存的新编辑快照"
        )

        let afterSuccess = await immutableRetryViewModel.confirmDraft(retryEditable)
        XCTAssertNotNil(afterSuccess)
        let afterSuccessBody = await immutableRetryMock.requestBodyJSON(
            for: "/api/dietary-records/drafts/1/confirm"
        )
        XCTAssertNotEqual(
            afterSuccessBody?["client_event_id"] as? String,
            successfulReplayBody?["client_event_id"] as? String,
            "成功后必须清除 pending mutation，下一次操作不得复用旧事件"
        )

        let longMock = MockAPIService()
        await longMock.setRawResponse(for: "/api/dietary-records/drafts", data: draftData(source: "chat"))
        let longViewModel = makeViewModel(api: longMock)
        let longText = String(repeating: "一次记录里可能包含很多需要继续调整的内容。", count: 12)
        XCTAssertGreaterThan(longText.count, DietaryFoodItem.maximumNameLength)
        let longDraft = await longViewModel.createDescriptionDraft(longText, source: .chat)
        XCTAssertNotNil(longDraft)
        let longBody = await longMock.requestBodyJSON(for: "/api/dietary-records/drafts")
        XCTAssertEqual(longBody?["raw_input"] as? String, longText, "长对话原文必须完整保留")
        XCTAssertEqual((longBody?["food_items"] as? [[String: Any]])?.count, 0, "长文本必须由服务端语义提取，不能按字符生切")

        let tooLong = String(repeating: "问", count: DietaryFoodItem.maximumDescriptionLength + 1)
        let rejectedLongDraft = await longViewModel.createDescriptionDraft(tooLong, source: .text)
        XCTAssertNil(rejectedLongDraft)
        XCTAssertEqual(longViewModel.preservedDraftInput, tooLong, "超限时也要保留输入供用户删减")
        let longPaths = await longMock.requestedPaths
        XCTAssertEqual(longPaths.count, 1, "客户端必须在发出无效请求前阻止超过后端上限的输入")
    }

    func testPhotoRecognitionCreatesAccountBoundDraftWithoutCallingLegacyMealEndpoints() async throws {
        XCTAssertFalse(DietaryCameraDraftPresentationGate.canPresent(
            coverDidDismiss: false,
            hasPendingDraft: true,
            hasActiveSheet: false
        ), "相机全屏页退场前不得抢先展示确认 sheet")
        XCTAssertTrue(DietaryCameraDraftPresentationGate.canPresent(
            coverDidDismiss: true,
            hasPendingDraft: true,
            hasActiveSheet: false
        ))
        XCTAssertFalse(DietaryCameraDraftPresentationGate.canPresent(
            coverDidDismiss: true,
            hasPendingDraft: true,
            hasActiveSheet: true
        ), "已有 sheet 时必须继续排队，不能双重展示")
        let mock = MockAPIService()
        await mock.setRawResponse(
            for: "/api/dietary-records/drafts/photo",
            data: draftData(source: "photo_library")
        )
        let viewModel = makeViewModel(api: mock)

        let sourcePNG = UIGraphicsImageRenderer(size: CGSize(width: 4, height: 4)).pngData { context in
            UIColor.systemGreen.setFill()
            context.fill(CGRect(x: 0, y: 0, width: 4, height: 4))
        }
        let normalized = try XCTUnwrap(DietaryPhotoUploadNormalizer.prepare(sourcePNG))
        XCTAssertEqual(normalized.fileName, "meal-library.jpg")
        XCTAssertEqual(normalized.mimeType, "image/jpeg")
        XCTAssertLessThanOrEqual(normalized.data.count, DietaryPhotoUploadNormalizer.maximumUploadBytes)
        XCTAssertEqual(Array(normalized.data.prefix(2)), [0xFF, 0xD8], "上传扩展名和 MIME 为 JPEG 时，字节也必须是真 JPEG")

        let draft = await viewModel.createPhotoDraft(
            sourcePNG,
            fileName: "picked-image.png",
            source: .photoLibrary
        )

        XCTAssertEqual(draft?.status, .pendingConfirmation)
        let uploads = await mock.accountBoundFileUploads()
        XCTAssertEqual(uploads.count, 1)
        let libraryUpload = try XCTUnwrap(uploads.first)
        XCTAssertEqual(libraryUpload.path, "/api/dietary-records/drafts/photo")
        XCTAssertEqual(libraryUpload.fileName, normalized.fileName)
        XCTAssertEqual(libraryUpload.mimeType, normalized.mimeType)
        XCTAssertLessThanOrEqual(
            libraryUpload.fileData.count,
            DietaryPhotoUploadNormalizer.maximumUploadBytes
        )
        XCTAssertEqual(Array(libraryUpload.fileData.prefix(2)), [0xFF, 0xD8])
        XCTAssertEqual(libraryUpload.expectedAccountScope, "account-a")
        XCTAssertEqual(libraryUpload.formData["subject_user_id"], "1")
        XCTAssertEqual(libraryUpload.formData["source"], "photo_library")
        XCTAssertEqual(libraryUpload.formData["client_event_id"], "event-1")
        let photoPaths = await mock.requestedPaths
        XCTAssertFalse(photoPaths.contains("/api/meals/photo/complete"))
        XCTAssertFalse(photoPaths.contains("/api/meals"))

        let retryMock = MockAPIService()
        let retryPath = "/api/dietary-records/drafts/1/retry-recognition"
        await retryMock.setRawResponse(
            for: "/api/dietary-records/drafts/photo",
            data: failedPhotoDraftData()
        )
        await retryMock.setRawResponse(
            for: retryPath,
            data: draftData(source: "camera", version: 2)
        )
        let retryViewModel = makeViewModel(api: retryMock)
        let oversizedCameraPNG = try noisyPNG()
        XCTAssertGreaterThan(oversizedCameraPNG.count, 10 * 1024 * 1024, "相机回归夹具必须真实超过后端上限")
        let failedDraftResult = await retryViewModel.createPhotoDraft(
            oversizedCameraPNG,
            fileName: "camera-48mp.png",
            source: .camera
        )
        let failedDraft = try XCTUnwrap(failedDraftResult)
        XCTAssertTrue(failedDraft.recognitionFailed)
        XCTAssertTrue(failedDraft.canRetryRecognition)
        XCTAssertTrue(failedDraft.isEditable)
        XCTAssertFalse(failedDraft.formalRecordCreated)
        let cameraUploads = await retryMock.accountBoundFileUploads()
        let cameraUpload = try XCTUnwrap(cameraUploads.first)
        XCTAssertEqual(cameraUpload.mimeType, "image/jpeg")
        XCTAssertEqual(cameraUpload.fileName, "meal-library.jpg")
        XCTAssertLessThanOrEqual(cameraUpload.fileData.count, DietaryPhotoUploadNormalizer.maximumUploadBytes)
        XCTAssertEqual(Array(cameraUpload.fileData.prefix(2)), [0xFF, 0xD8], "相机也必须经过统一 JPEG 正规化")

        let retried = await retryViewModel.retryRecognition(failedDraft)

        XCTAssertEqual(retried?.draftID, failedDraft.draftID, "重试必须更新原草稿，不能创建另一份任务")
        XCTAssertEqual(retried?.version, 2)
        XCTAssertEqual(retried?.recognitionStatus, "completed")
        XCTAssertFalse(retried?.formalRecordCreated ?? true)
        XCTAssertEqual(retryViewModel.pendingDrafts.map(\.draftID), [failedDraft.draftID])

        let recognizedDraft = try XCTUnwrap(retried)
        var manuallyEdited = DietaryEditableDraft(failedDraft)
        manuallyEdited.foodItems = [DietaryFoodItem(name: "豆腐饭", portionText: "半碗")]
        manuallyEdited.portionText = "用户手填份量"
        manuallyEdited.structure = ["manual": .bool(true)]
        let mergedSuccess = manuallyEdited.mergingRecognitionRetry(recognizedDraft)
        XCTAssertEqual(mergedSuccess.original.version, 2, "合并后必须采用服务端的新版本")
        XCTAssertEqual(mergedSuccess.foodItems.map(\.name), ["豆腐饭"], "识别成功也不能覆盖用户已手填食物")
        XCTAssertEqual(mergedSuccess.portionText, "用户手填份量")
        XCTAssertEqual(mergedSuccess.structure, ["manual": .bool(true)])

        let untouched = DietaryEditableDraft(failedDraft).mergingRecognitionRetry(recognizedDraft)
        XCTAssertEqual(untouched.foodItems.map(\.name), ["番茄炒蛋"], "未编辑字段应采用新的识别建议")
        let failedAgain = try JSONDecoder().decode(
            DietaryMealDraft.self,
            from: failedPhotoDraftData(version: 2)
        )
        let mergedFailure = manuallyEdited.mergingRecognitionRetry(failedAgain)
        XCTAssertEqual(mergedFailure.original.version, 2)
        XCTAssertEqual(mergedFailure.foodItems.map(\.name), ["豆腐饭"], "再次失败也必须保留手动内容")

        let retryBody = await retryMock.requestBodyJSON(for: retryPath)
        XCTAssertEqual(retryBody?["subject_user_id"] as? Int, 1)
        XCTAssertEqual(retryBody?["expected_version"] as? Int, 1)
        XCTAssertEqual(retryBody?["client_event_id"] as? String, "event-1")
        let retryPaths = await retryMock.requestedPaths
        XCTAssertEqual(retryPaths, ["/api/dietary-records/drafts/photo", retryPath])
        XCTAssertFalse(retryPaths.contains(where: { $0.contains("/confirm") || $0 == "/api/meals" }))

        let stablePhotoMock = MockAPIService()
        await stablePhotoMock.setError(URLError(.networkConnectionLost))
        var stablePhotoNow = try XCTUnwrap(Self.iso.date(from: "2026-07-15T03:59:59+08:00"))
        let stablePhotoViewModel = makeViewModel(
            api: stablePhotoMock,
            nowProvider: { stablePhotoNow }
        )
        let firstPhotoAttempt = await stablePhotoViewModel.createPhotoDraft(
            sourcePNG,
            fileName: "boundary-camera.png",
            source: .camera
        )
        XCTAssertNil(firstPhotoAttempt)
        let firstBoundaryUploads = await stablePhotoMock.accountBoundFileUploads()
        let firstBoundaryUpload = try XCTUnwrap(firstBoundaryUploads.first)
        XCTAssertEqual(firstBoundaryUpload.formData["diet_date"], "2026-07-14")

        await stablePhotoMock.setRawResponse(
            for: "/api/dietary-records/drafts/photo",
            data: failedPhotoDraftData(
                dietDate: "2026-07-14",
                eatenAt: "2026-07-15T03:59:59+08:00"
            )
        )
        await stablePhotoMock.setError(nil)
        stablePhotoNow = try XCTUnwrap(Self.iso.date(from: "2026-07-15T04:00:01+08:00"))
        let recoveredPhoto = await stablePhotoViewModel.createPhotoDraft(
            sourcePNG,
            fileName: "boundary-camera.png",
            source: .camera
        )
        XCTAssertEqual(stablePhotoViewModel.selectedDateKey, "2026-07-15")
        XCTAssertEqual(recoveredPhoto?.dietDate, "2026-07-14")
        XCTAssertTrue(stablePhotoViewModel.pendingDrafts.isEmpty)
        let boundaryUploads = await stablePhotoMock.accountBoundFileUploads()
        XCTAssertEqual(boundaryUploads.count, 2)
        XCTAssertEqual(boundaryUploads[1].formData, firstBoundaryUpload.formData, "照片网络重放不能改变时间快照")
        XCTAssertEqual(boundaryUploads[1].fileData, firstBoundaryUpload.fileData)
    }

    func testDashboardSeparatesYesterdaySummaryFromOpenTodayAndHistorySummary() async throws {
        let mock = MockAPIService()
        await mock.setRawResponse(for: dashboardPath, data: dashboardData(
            selectedDate: "2026-07-15",
            isToday: true,
            summaryDate: "2026-07-14"
        ))
        let viewModel = makeViewModel(api: mock)

        await viewModel.fetchData()

        XCTAssertEqual(viewModel.dayState, .open)
        XCTAssertTrue(viewModel.isSelectedToday)
        XCTAssertEqual(viewModel.displayedSummary?.dietDate, "2026-07-14")
        let expectedYesterdayTitle = String(
            localized: "dietary.summary.yesterday",
            defaultValue: "__missing_dietary_summary_yesterday__"
        )
        XCTAssertNotEqual(expectedYesterdayTitle, "__missing_dietary_summary_yesterday__")
        XCTAssertEqual(viewModel.summaryTitle, expectedYesterdayTitle)
        XCTAssertEqual(viewModel.displayedSummary?.structureConclusion, "三餐结构较规律")
        XCTAssertFalse(viewModel.shouldShowCurrentDayConclusion, "开放中的今天不能生成当天结论")

        let historyPath = "/api/dietary-records/dashboard?diet_date=2026-07-13&timezone=Asia/Shanghai&subject_user_id=1"
        await mock.setRawResponse(for: historyPath, data: dashboardData(
            selectedDate: "2026-07-13",
            isToday: false,
            summaryDate: "2026-07-13"
        ))
        await viewModel.selectDate(
            try XCTUnwrap(Self.iso.date(from: "2026-07-13T12:00:00+08:00"))
        )

        XCTAssertFalse(viewModel.isSelectedToday)
        XCTAssertEqual(viewModel.displayedSummary?.dietDate, "2026-07-13")
        let expectedSelectedTitle = String(
            localized: "dietary.summary.selected",
            defaultValue: "__missing_dietary_summary_selected__"
        )
        XCTAssertNotEqual(expectedSelectedTitle, "__missing_dietary_summary_selected__")
        XCTAssertEqual(viewModel.summaryTitle, expectedSelectedTitle)
    }

    func testManualCompletionUsesConfirmedRecordsOnlyAndDoesNotRequireThreeMeals() async throws {
        let mock = MockAPIService()
        await mock.setRawResponse(
            for: "/api/dietary-records/days/2026-07-15/complete",
            data: summaryData(date: "2026-07-15")
        )
        let viewModel = makeViewModel(api: mock)
        viewModel.adoptAuthoritativeSubjectForTesting(1)

        let summary = await viewModel.completeSelectedDayWithConfirmedRecords()

        XCTAssertEqual(summary?.completionMode, .manual)
        let body = await mock.requestBodyJSON(for: "/api/dietary-records/days/2026-07-15/complete")
        XCTAssertEqual(body?["complete_with_confirmed_only"] as? Bool, true)
        XCTAssertEqual(body?["subject_user_id"] as? Int, 1)
        XCTAssertNil(body?["required_meal_count"], "手动结束不能强制三餐")
        let completionPaths = await mock.requestedPaths
        XCTAssertFalse(completionPaths.contains("/api/meals"))

        let incompleteMock = MockAPIService()
        await incompleteMock.setRawResponse(
            for: "/api/dietary-records/days/2026-07-15/complete",
            data: incompleteCompletionData(date: "2026-07-15")
        )
        let incompleteViewModel = makeViewModel(api: incompleteMock)
        incompleteViewModel.adoptAuthoritativeSubjectForTesting(1)
        let absentSummary = await incompleteViewModel.completeSelectedDayWithConfirmedRecords()
        XCTAssertNil(absentSummary)
        XCTAssertTrue(incompleteViewModel.lastCompletionAccepted, "服务端接受但尚无总结时不能误报为请求失败")
        XCTAssertEqual(incompleteViewModel.dayState, .incomplete)
        XCTAssertNil(incompleteViewModel.errorMessage)

        // Complete caches both its original date path and body. A 5xx, an
        // undecodable 2xx body, cancellation and a time-zone rollover are all
        // ambiguous delivery states and must retain that exact snapshot.
        let replayMock = MockAPIService()
        let originalCompletePath = "/api/dietary-records/days/2026-07-15/complete"
        var replayZone = "Asia/Shanghai"
        var completionEventSequence = 0
        let replayViewModel = makeViewModel(
            api: replayMock,
            nowProvider: { Self.iso.date(from: "2026-07-15T18:00:00+08:00")! },
            timeZoneProvider: { replayZone },
            makeID: {
                completionEventSequence += 1
                return "immutable-complete-\(completionEventSequence)"
            }
        )
        replayViewModel.adoptAuthoritativeSubjectForTesting(1)
        await replayMock.setError(APIError.httpErrorResponse(503, "upstream lost response", Data()))
        let failed503 = await replayViewModel.completeSelectedDayWithConfirmedRecords()
        XCTAssertNil(failed503)
        let firstCompleteBody = await replayMock.requestBodyJSON(for: originalCompletePath)

        replayZone = "America/Los_Angeles"
        await replayMock.setRawResponse(for: originalCompletePath, data: Data("{}".utf8))
        await replayMock.setError(nil)
        let undecodableResponse = await replayViewModel.completeSelectedDayWithConfirmedRecords()
        XCTAssertNil(undecodableResponse)
        let decodeRetryBody = await replayMock.requestBodyJSON(for: originalCompletePath)
        XCTAssertEqual(try canonicalJSON(decodeRetryBody), try canonicalJSON(firstCompleteBody))
        XCTAssertEqual(decodeRetryBody?["timezone"] as? String, "Asia/Shanghai")

        await replayMock.setError(URLError(.cancelled))
        let cancelledResponse = await replayViewModel.completeSelectedDayWithConfirmedRecords()
        XCTAssertNil(cancelledResponse)
        let cancelledRetryBody = await replayMock.requestBodyJSON(for: originalCompletePath)
        XCTAssertEqual(
            try canonicalJSON(cancelledRetryBody),
            try canonicalJSON(firstCompleteBody),
            "URLSession 取消也不能换 event 或自动改成新时区的日期"
        )

        let losAngelesDashboardPath = "/api/dietary-records/dashboard?diet_date=2026-07-14&timezone=America/Los_Angeles&subject_user_id=1"
        await replayMock.setRawResponse(for: originalCompletePath, data: summaryData(date: "2026-07-15"))
        await replayMock.setRawResponse(
            for: losAngelesDashboardPath,
            data: dashboardWithoutSummaryData(selectedDate: "2026-07-14", isToday: true)
        )
        await replayMock.setError(nil)
        let recoveredSummary = await replayViewModel.completeSelectedDayWithConfirmedRecords()
        XCTAssertEqual(recoveredSummary?.dietDate, "2026-07-15")
        let recoveredCompleteBody = await replayMock.requestBodyJSON(for: originalCompletePath)
        XCTAssertEqual(try canonicalJSON(recoveredCompleteBody), try canonicalJSON(firstCompleteBody))

        let currentCompletePath = "/api/dietary-records/days/2026-07-14/complete"
        await replayMock.setRawResponse(for: currentCompletePath, data: summaryData(date: "2026-07-14"))
        let currentDaySummary = await replayViewModel.completeSelectedDayWithConfirmedRecords()
        XCTAssertEqual(currentDaySummary?.dietDate, "2026-07-14")
        let currentCompleteBody = await replayMock.requestBodyJSON(for: currentCompletePath)
        XCTAssertNotEqual(
            currentCompleteBody?["client_event_id"] as? String,
            recoveredCompleteBody?["client_event_id"] as? String,
            "成功后旧 snapshot 必须清除，下一次 complete 应采用当前日期和新事件"
        )
        XCTAssertEqual(currentCompleteBody?["timezone"] as? String, "America/Los_Angeles")
        let replayPaths = await replayMock.requestedPaths
        XCTAssertEqual(replayPaths, [
            originalCompletePath,
            originalCompletePath,
            originalCompletePath,
            originalCompletePath,
            losAngelesDashboardPath,
            currentCompletePath,
        ])
    }

    func testDraftFailurePreservesRawInputAndDoesNotWriteFormalRecord() async throws {
        let dashboardMock = MockAPIService()
        await dashboardMock.setError(APIError.httpError(404, "Not Found"))
        let unavailableViewModel = makeViewModel(api: dashboardMock)

        await unavailableViewModel.fetchData()

        XCTAssertEqual(unavailableViewModel.loadState, .failed, "404 不能被伪装成无数据或成功状态")
        XCTAssertEqual(unavailableViewModel.errorMessage, "膳食记录服务暂不可用，请稍后再试")
        XCTAssertFalse(unavailableViewModel.errorMessage?.contains("Not Found") == true)
        XCTAssertFalse(unavailableViewModel.shouldPresentErrorAlert, "首次加载错误已有页面状态卡，不应重复弹窗")

        let mock = MockAPIService()
        await mock.setError(URLError(.notConnectedToInternet))
        var mutableNow = try XCTUnwrap(Self.iso.date(from: "2026-07-15T03:59:59+08:00"))
        let viewModel = makeViewModel(api: mock, nowProvider: { mutableNow })

        let result = await viewModel.createDescriptionDraft("豆浆和全麦面包", source: .voice)

        XCTAssertNil(result)
        XCTAssertTrue(viewModel.shouldPresentErrorAlert, "用户主动创建草稿失败仍应通过 Alert 及时反馈")
        XCTAssertEqual(viewModel.preservedDraftInput, "豆浆和全麦面包")
        XCTAssertTrue(viewModel.isOffline)
        let paths = await mock.requestedPaths
        XCTAssertEqual(paths, ["/api/dietary-records/drafts"])
        XCTAssertFalse(paths.contains("/api/meals"))
        let createBody = await mock.requestBodyJSON(for: "/api/dietary-records/drafts")
        XCTAssertEqual(createBody?["raw_input"] as? String, "豆浆和全麦面包")
        XCTAssertNil(createBody?["raw_text"], "后端 extra=forbid，客户端不得发送旧字段 raw_text")
        XCTAssertEqual(createBody?["diet_date"] as? String, "2026-07-14")
        XCTAssertEqual(createBody?["eaten_at"] as? String, "2026-07-15T03:59:59+08:00")

        await mock.setRawResponse(
            for: "/api/dietary-records/drafts",
            data: draftData(
                source: "voice",
                dietDate: "2026-07-14",
                eatenAt: "2026-07-15T03:59:59+08:00"
            )
        )
        await mock.setError(nil)
        mutableNow = try XCTUnwrap(Self.iso.date(from: "2026-07-15T04:00:01+08:00"))
        let recovered = await viewModel.createDescriptionDraft("豆浆和全麦面包", source: .voice)
        XCTAssertEqual(viewModel.selectedDateKey, "2026-07-15")
        XCTAssertEqual(recovered?.dietDate, "2026-07-14", "网络重放必须保持原任务的饮食日")
        XCTAssertTrue(viewModel.pendingDrafts.isEmpty, "上一饮食日草稿不能污染当前页待确认计数")
        let replayBody = await mock.requestBodyJSON(for: "/api/dietary-records/drafts")
        XCTAssertEqual(replayBody?["client_event_id"] as? String, createBody?["client_event_id"] as? String)
        XCTAssertEqual(replayBody?["diet_date"] as? String, "2026-07-14")
        XCTAssertEqual(replayBody?["timezone"] as? String, "Asia/Shanghai")
        XCTAssertEqual(replayBody?["eaten_at"] as? String, "2026-07-15T03:59:59+08:00")
        let replayPaths = await mock.requestedPaths
        XCTAssertEqual(replayPaths, ["/api/dietary-records/drafts", "/api/dietary-records/drafts"])
        XCTAssertFalse(replayPaths.contains("/api/meals"))
    }

    func testRecordEditDeleteAndReuseAreVersionedAndReuseStaysPending() async throws {
        let mock = MockAPIService()
        await mock.setRawResponse(
            for: "/api/dietary-records/records/1",
            data: recordData(status: "modified", version: 4)
        )
        await mock.setRawResponse(
            for: "/api/dietary-records/records/1/reuse",
            data: draftData(id: 2, source: "recent")
        )
        let viewModel = makeViewModel(api: mock)
        viewModel.adoptAuthoritativeSubjectForTesting(1)
        var editable = DietaryEditableRecord(record: try JSONDecoder().decode(
            DietaryMealRecord.self,
            from: recordData(status: "user_confirmed", version: 3)
        ))
        editable.foodItems[0].portionText = "半碗"

        let updated = await viewModel.updateRecord(editable)
        XCTAssertEqual(updated?.status, .modified)
        let editBody = await mock.requestBodyJSON(for: "/api/dietary-records/records/1")
        XCTAssertEqual(editBody?["expected_version"] as? Int, 3)
        XCTAssertEqual(editBody?["client_event_id"] as? String, "event-1")
        XCTAssertEqual(editBody?["timezone"] as? String, "Asia/Shanghai")
        XCTAssertEqual((editBody?["field_confidences"] as? [String: Any])?["food_items"] as? Double, 0.9)
        XCTAssertEqual(editBody?["recognition_confidence"] as? Double, 0.9)

        let reused = await viewModel.reuseRecord(updated ?? editable.original)
        XCTAssertEqual(reused?.status, .pendingConfirmation)
        let reuseBody = await mock.requestBodyJSON(for: "/api/dietary-records/records/1/reuse")
        XCTAssertEqual(reuseBody?["expected_version"] as? Int, 4)
        XCTAssertEqual(reuseBody?["timezone"] as? String, "Asia/Shanghai")
        XCTAssertEqual(reuseBody?["diet_date"] as? String, "2026-07-15")
        XCTAssertEqual(reuseBody?["meal_type"] as? String, "lunch")
        XCTAssertEqual(reuseBody?["eaten_at"] as? String, "2026-07-15T18:00:00+08:00")

        let authoritativeDashboardPath = "\(dashboardPath)&subject_user_id=1"
        await mock.setRawResponse(
            for: authoritativeDashboardPath,
            data: dashboardData(
                selectedDate: "2026-07-15",
                isToday: true,
                summaryDate: "2026-07-15",
                recordedMealCount: 1,
                dayState: "ready"
            )
        )
        await viewModel.fetchData()
        XCTAssertEqual(viewModel.dayState, .ready)
        XCTAssertEqual(viewModel.displayedSummary?.dietDate, "2026-07-15")
        await mock.setRawResponse(
            for: authoritativeDashboardPath,
            data: dashboardWithoutSummaryData(selectedDate: "2026-07-15", isToday: true)
        )
        let deleted = await viewModel.deleteRecord(updated ?? editable.original)
        XCTAssertTrue(deleted)
        XCTAssertTrue(viewModel.records.isEmpty)
        XCTAssertNil(viewModel.selectedDaySummary)
        XCTAssertNil(viewModel.displayedSummary, "删除后必须采用 dashboard 权威结果移除旧结论")
        XCTAssertEqual(viewModel.dayState, .open)
        XCTAssertEqual(viewModel.recordedMealCount, 0)
        XCTAssertEqual(viewModel.pendingCount, 0)
        let paths = await mock.requestedPaths
        XCTAssertEqual(paths, [
            "/api/dietary-records/records/1",
            "/api/dietary-records/records/1/reuse",
            authoritativeDashboardPath,
            "/api/dietary-records/records/1",
            authoritativeDashboardPath,
        ])
        let scopes = await mock.requestedAccountScopes
        XCTAssertEqual(scopes, ["account-a", "account-a", "account-a"])

        let movedMock = MockAPIService()
        await movedMock.setRawResponse(
            for: "/api/dietary-records/records/1",
            data: recordData(status: "modified", version: 4, dietDate: "2026-07-17")
        )
        await movedMock.setRawResponse(
            for: "\(dashboardPath)&subject_user_id=1",
            data: dashboardData(
                selectedDate: "2026-07-15",
                isToday: true,
                summaryDate: "2026-07-14",
                recordedMealCount: 0
            )
        )
        let movedViewModel = makeViewModel(api: movedMock)
        movedViewModel.adoptAuthoritativeSubjectForTesting(1)
        var movedEditable = DietaryEditableRecord(record: try JSONDecoder().decode(
            DietaryMealRecord.self,
            from: recordData(status: "user_confirmed", version: 3)
        ))
        movedEditable.dietDate = "2026-07-17"

        let moved = await movedViewModel.updateRecord(movedEditable)
        XCTAssertEqual(moved?.dietDate, "2026-07-17")
        XCTAssertTrue(movedViewModel.records.isEmpty, "移到其他日期的记录不能残留在当前页")
        XCTAssertEqual(movedViewModel.recordedMealCount, 0)
        let movedPaths = await movedMock.requestedPaths
        XCTAssertEqual(
            movedPaths,
            ["/api/dietary-records/records/1", "\(dashboardPath)&subject_user_id=1"],
            "跨日 mutation 必须重新读取当前饮食日的服务端权威状态"
        )

        let immutableMutationMock = MockAPIService()
        var mutationZone = "Asia/Shanghai"
        var mutationScope = "account-a"
        var mutationEventSequence = 0
        let immutableMutationViewModel = makeViewModel(
            api: immutableMutationMock,
            nowProvider: { Self.iso.date(from: "2026-07-15T18:00:00+08:00")! },
            timeZoneProvider: { mutationZone },
            accountScopeProvider: { mutationScope },
            makeID: {
                mutationEventSequence += 1
                return "immutable-record-\(mutationEventSequence)"
            }
        )
        immutableMutationViewModel.adoptAuthoritativeSubjectForTesting(1)
        let immutableOriginal = try JSONDecoder().decode(
            DietaryMealRecord.self,
            from: recordData(status: "user_confirmed", version: 3)
        )
        var immutableEditable = DietaryEditableRecord(record: immutableOriginal)
        immutableEditable.foodItems[0].portionText = "一小碗"
        await immutableMutationMock.setError(APIError.httpErrorResponse(503, "response lost", Data()))
        let firstUpdateFailure = await immutableMutationViewModel.updateRecord(immutableEditable)
        XCTAssertNil(firstUpdateFailure)
        let firstUpdateBody = await immutableMutationMock.requestBodyJSON(
            for: "/api/dietary-records/records/1"
        )

        mutationZone = "America/Los_Angeles"
        await immutableMutationMock.setError(URLError(.cancelled))
        let cancelledUpdate = await immutableMutationViewModel.updateRecord(immutableEditable)
        XCTAssertNil(cancelledUpdate)
        let cancelledUpdateBody = await immutableMutationMock.requestBodyJSON(
            for: "/api/dietary-records/records/1"
        )
        XCTAssertEqual(
            try canonicalJSON(cancelledUpdateBody),
            try canonicalJSON(firstUpdateBody),
            "update 的 cancelled/timezone retry 必须逐字节保持首个请求"
        )

        immutableEditable.foodItems[0].portionText = "两小碗"
        let editedWhilePending = await immutableMutationViewModel.updateRecord(immutableEditable)
        XCTAssertNil(editedWhilePending)
        let editedWhilePendingBody = await immutableMutationMock.requestBodyJSON(
            for: "/api/dietary-records/records/1"
        )
        XCTAssertEqual(
            try canonicalJSON(editedWhilePendingBody),
            try canonicalJSON(firstUpdateBody),
            "update 旧事件未解决前不能被本地编辑覆盖"
        )

        await immutableMutationMock.setError(APIError.httpErrorResponse(409, "version conflict", Data()))
        let rejectedUpdate = await immutableMutationViewModel.updateRecord(immutableEditable)
        XCTAssertNil(rejectedUpdate)
        await immutableMutationMock.setError(URLError(.networkConnectionLost))
        let newEditedUpdate = await immutableMutationViewModel.updateRecord(immutableEditable)
        XCTAssertNil(newEditedUpdate)
        let newEditedUpdateBody = await immutableMutationMock.requestBodyJSON(
            for: "/api/dietary-records/records/1"
        )
        XCTAssertNotEqual(
            newEditedUpdateBody?["client_event_id"] as? String,
            firstUpdateBody?["client_event_id"] as? String
        )
        XCTAssertEqual(newEditedUpdateBody?["timezone"] as? String, "America/Los_Angeles")
        XCTAssertEqual(
            ((newEditedUpdateBody?["food_items"] as? [[String: Any]])?.first)?["portion_text"] as? String,
            "两小碗"
        )

        mutationZone = "Asia/Shanghai"
        await immutableMutationMock.setRawResponse(
            for: "/api/dietary-records/records/1",
            data: recordData(status: "modified", version: 4)
        )
        await immutableMutationMock.setError(nil)
        let recoveredUpdate = await immutableMutationViewModel.updateRecord(immutableEditable)
        XCTAssertEqual(recoveredUpdate?.version, 4)
        let recoveredUpdateBody = await immutableMutationMock.requestBodyJSON(
            for: "/api/dietary-records/records/1"
        )
        XCTAssertEqual(try canonicalJSON(recoveredUpdateBody), try canonicalJSON(newEditedUpdateBody))

        // An account boundary discards an unresolved snapshot even when the
        // subject/entity IDs happen to be identical in the new account.
        await immutableMutationMock.setError(URLError(.networkConnectionLost))
        let accountAUpdate = await immutableMutationViewModel.updateRecord(immutableEditable)
        XCTAssertNil(accountAUpdate)
        let accountABody = await immutableMutationMock.requestBodyJSON(for: "/api/dietary-records/records/1")
        mutationScope = "account-b"
        let accountBUpdate = await immutableMutationViewModel.updateRecord(immutableEditable)
        XCTAssertNil(accountBUpdate)
        let accountBBody = await immutableMutationMock.requestBodyJSON(for: "/api/dietary-records/records/1")
        XCTAssertNotEqual(
            accountBBody?["client_event_id"] as? String,
            accountABody?["client_event_id"] as? String,
            "账号 scope 变化必须丢弃旧账号的 mutation snapshot"
        )

        let immutableUpdated = try JSONDecoder().decode(
            DietaryMealRecord.self,
            from: recordData(status: "modified", version: 4)
        )
        await immutableMutationMock.setError(APIError.httpErrorResponse(503, "reuse response lost", Data()))
        let firstReuseFailure = await immutableMutationViewModel.reuseRecord(immutableUpdated)
        XCTAssertNil(firstReuseFailure)
        let reusePath = "/api/dietary-records/records/1/reuse"
        let firstReuseBody = await immutableMutationMock.requestBodyJSON(for: reusePath)

        mutationZone = "America/Los_Angeles"
        await immutableMutationMock.setError(URLError(.cancelled))
        let movedDayReuseFailure = await immutableMutationViewModel.reuseRecord(immutableUpdated)
        XCTAssertNil(movedDayReuseFailure)
        let movedDayReuseBody = await immutableMutationMock.requestBodyJSON(for: reusePath)
        XCTAssertEqual(
            try canonicalJSON(movedDayReuseBody),
            try canonicalJSON(firstReuseBody),
            "reuse 自动跨时区/跨饮食日后仍必须重放旧 event、date、timezone 和 eaten_at"
        )
        XCTAssertEqual(firstReuseBody?["diet_date"] as? String, "2026-07-15")
        XCTAssertEqual(movedDayReuseBody?["diet_date"] as? String, "2026-07-15")

        await immutableMutationMock.setRawResponse(
            for: reusePath,
            data: draftData(id: 8, source: "recent", dietDate: "2026-07-15", timezone: "Asia/Shanghai")
        )
        await immutableMutationMock.setError(nil)
        let recoveredReuse = await immutableMutationViewModel.reuseRecord(immutableUpdated)
        XCTAssertEqual(recoveredReuse?.draftID, "8")
        let recoveredReuseBody = await immutableMutationMock.requestBodyJSON(for: reusePath)
        XCTAssertEqual(try canonicalJSON(recoveredReuseBody), try canonicalJSON(firstReuseBody))

        let failedRefreshMock = MockAPIService()
        await failedRefreshMock.setRawResponse(
            for: authoritativeDashboardPath,
            data: dashboardData(
                selectedDate: "2026-07-15",
                isToday: true,
                summaryDate: "2026-07-15",
                recordedMealCount: 1,
                dayState: "ready"
            )
        )
        let failedRefreshViewModel = makeViewModel(api: failedRefreshMock)
        failedRefreshViewModel.adoptAuthoritativeSubjectForTesting(1)
        await failedRefreshViewModel.fetchData()
        XCTAssertEqual(failedRefreshViewModel.displayedSummary?.dietDate, "2026-07-15")
        await failedRefreshMock.setRawResponse(for: authoritativeDashboardPath, data: Data("{}".utf8))
        let deleteWithFailedRefresh = await failedRefreshViewModel.deleteRecord(editable.original)
        XCTAssertTrue(deleteWithFailedRefresh, "服务端删除成功不能被后续 dashboard 解码失败改写")
        XCTAssertNil(
            failedRefreshViewModel.displayedSummary,
            "closed-day 删除后的回读即使失败，也绝不能继续显示旧 summary/conclusion"
        )
        XCTAssertNil(failedRefreshViewModel.selectedDaySummary)
        XCTAssertEqual(failedRefreshViewModel.dayState, .stale)
        XCTAssertNotNil(failedRefreshViewModel.errorMessage)
        let failedRefreshPaths = await failedRefreshMock.requestedPaths
        XCTAssertEqual(failedRefreshPaths, [
            authoritativeDashboardPath,
            "/api/dietary-records/records/1",
            authoritativeDashboardPath,
        ])
    }

    private func makeViewModel(
        api: MockAPIService,
        now: Date? = nil,
        accountScopeProvider: @escaping @MainActor () -> String? = { "account-a" },
        makeID: @escaping () -> String = { "event-1" }
    ) -> MealsViewModel {
        let resolvedNow = now ?? Self.iso.date(from: "2026-07-15T18:00:00+08:00")!
        return MealsViewModel(
            api: api,
            now: { resolvedNow },
            calendar: shanghaiCalendar(),
            timeZoneIdentifier: { "Asia/Shanghai" },
            currentAccountScope: accountScopeProvider,
            currentSubjectUserID: { 1 },
            makeID: makeID
        )
    }

    private func makeViewModel(
        api: MockAPIService,
        nowProvider: @escaping () -> Date,
        calendar: Calendar? = nil,
        timeZoneProvider: @escaping () -> String = { "Asia/Shanghai" },
        accountScopeProvider: @escaping @MainActor () -> String? = { "account-a" },
        makeID: @escaping () -> String = { "event-1" }
    ) -> MealsViewModel {
        MealsViewModel(
            api: api,
            now: nowProvider,
            calendar: calendar ?? shanghaiCalendar(),
            timeZoneIdentifier: timeZoneProvider,
            currentAccountScope: accountScopeProvider,
            currentSubjectUserID: { 1 },
            makeID: makeID
        )
    }

    private func canonicalJSON(_ object: [String: Any]?) throws -> Data {
        try JSONSerialization.data(
            withJSONObject: try XCTUnwrap(object),
            options: [.sortedKeys]
        )
    }

    private func shanghaiCalendar() -> Calendar {
        var calendar = Calendar(identifier: .gregorian)
        calendar.locale = Locale(identifier: "en_US_POSIX")
        calendar.timeZone = TimeZone(identifier: "Asia/Shanghai")!
        return calendar
    }

    private func noisyPNG(width: Int = 2_048, height: Int = 2_048) throws -> Data {
        var pixels = [UInt8](repeating: 0, count: width * height * 4)
        var state: UInt32 = 0x715B_2026
        for offset in stride(from: 0, to: pixels.count, by: 4) {
            state ^= state << 13
            state ^= state >> 17
            state ^= state << 5
            pixels[offset] = UInt8(truncatingIfNeeded: state >> 24)
            state ^= state << 13
            state ^= state >> 17
            state ^= state << 5
            pixels[offset + 1] = UInt8(truncatingIfNeeded: state >> 24)
            state ^= state << 13
            state ^= state >> 17
            state ^= state << 5
            pixels[offset + 2] = UInt8(truncatingIfNeeded: state >> 24)
            pixels[offset + 3] = 255
        }
        let provider = try XCTUnwrap(CGDataProvider(data: Data(pixels) as CFData))
        let bitmapInfo = CGBitmapInfo.byteOrder32Big.union(
            CGBitmapInfo(rawValue: CGImageAlphaInfo.noneSkipLast.rawValue)
        )
        let image = try XCTUnwrap(CGImage(
            width: width,
            height: height,
            bitsPerComponent: 8,
            bitsPerPixel: 32,
            bytesPerRow: width * 4,
            space: CGColorSpaceCreateDeviceRGB(),
            bitmapInfo: bitmapInfo,
            provider: provider,
            decode: nil,
            shouldInterpolate: false,
            intent: .defaultIntent
        ))
        return try XCTUnwrap(UIImage(cgImage: image).pngData())
    }

    /// Mirrors `DietaryDraftOut` from the backend TestClient, including numeric IDs.
    private func draftData(
        id: Int = 1,
        source: String = "text",
        version: Int = 1,
        dietDate: String = "2026-07-15",
        timezone: String = "Asia/Shanghai",
        eatenAt: String = "2026-07-15T04:20:00Z"
    ) -> Data {
        Data(#"""
        {
          "draft_id":\#(id),"subject_user_id":1,"source_type":"\#(source)","source_ref":null,
          "diet_date":"\#(dietDate)","timezone":"\#(timezone)",
          "meal_type":"lunch","eaten_at":"\#(eatenAt)",
          "food_items":[{"item_id":"food-1","name":"番茄炒蛋","portion_text":"约一碗","categories":["protein","vegetable"],"confidence":0.62,"is_estimated":true}],
          "portion_text":"约一碗","structure":{"protein":"moderate"},
          "estimated_nutrition":{"energy_kcal_range":[350,500]},
          "field_confidences":{"food_items":0.62,"portion_text":0.55},
          "recognition_confidence":0.62,"recognition_status":"completed","recognition_cache_reused":false,
          "low_confidence_fields":["portion_text"],
          "status":"pending_confirmation","version":\#(version),"requires_user_confirmation":true,
          "formal_record_created":false,
          "created_at":"2026-07-15T04:21:00Z","updated_at":"2026-07-15T04:21:00Z"
        }
        """#.utf8)
    }

    private func failedPhotoDraftData(
        version: Int = 1,
        dietDate: String = "2026-07-15",
        timezone: String = "Asia/Shanghai",
        eatenAt: String = "2026-07-15T04:20:00Z"
    ) -> Data {
        Data(#"""
        {
          "draft_id":1,"subject_user_id":1,"source_type":"camera","source_ref":"sha256:abc123",
          "diet_date":"\#(dietDate)","timezone":"\#(timezone)",
          "meal_type":"lunch","eaten_at":"\#(eatenAt)",
          "food_items":[],"portion_text":null,"structure":{},"estimated_nutrition":{},
          "field_confidences":{},"recognition_confidence":null,
          "recognition_status":"failed_manual_entry_available","recognition_cache_reused":false,
          "low_confidence_fields":[],"status":"pending_confirmation","version":\#(version),
          "requires_user_confirmation":true,"formal_record_created":false,
          "created_at":"2026-07-15T04:21:00Z","updated_at":"2026-07-15T04:21:00Z"
        }
        """#.utf8)
    }

    private func recordData(status: String, version: Int, dietDate: String = "2026-07-15") -> Data {
        Data(#"""
        {
          "record_id":1,"source_draft_id":1,"subject_user_id":1,"diet_date":"\#(dietDate)",
          "timezone":"Asia/Shanghai","meal_type":"lunch","eaten_at":"2026-07-15T04:20:00Z",
          "source_type":"text","source_ref":"draft:1",
          "food_items":[{"item_id":"food-1","name":"番茄炒蛋","portion_text":"1 碗","categories":["protein","vegetable"],"confidence":0.9,"is_estimated":true}],
          "portion_text":"1 碗","structure":{"protein":"moderate"},
          "estimated_nutrition":{"energy_kcal_range":[350,500]},
          "field_confidences":{"food_items":0.9},
          "confidence":0.9,"status":"\#(status)","version":\#(version),
          "trust_state":"user_confirmed","confirmed_at":"2026-07-15T04:25:00Z",
          "created_at":"2026-07-15T04:21:00Z","updated_at":"2026-07-15T04:25:00Z"
        }
        """#.utf8)
    }

    private func dashboardData(
        selectedDate: String,
        isToday: Bool,
        summaryDate: String,
        recordedMealCount: Int = 2,
        dayState: String = "open"
    ) -> Data {
        Data(#"""
        {
          "subject_user_id":1,"selected_date":"\#(selectedDate)","is_today":\#(isToday),
          "recorded_meal_count":\#(recordedMealCount),"pending_count":0,"streak_days":5,"day_state":"\#(dayState)",
          "records":[],"pending_drafts":[],"selected_day_summary":null,
          "displayed_summary":{
            "summary_id":9,"subject_user_id":1,"diet_date":"\#(summaryDate)","close_method":"automatic",
            "record_complete":true,"confirmed_meal_count":3,"pending_count":0,
            "structure_summary":{"protein":"moderate"},
            "conclusion":"三餐结构较规律","today_suggestion":"今天午餐增加一份蔬菜",
            "confidence":0.86,
            "evidence":{"included_record_ids":[1,2,3],"excluded_pending_draft_ids":[],"pending_records_excluded":false,"natural_language_generated_by_model":false},
            "rule_version":"dietary-rules-v1","template_version":"dietary-template-v1","record_version":3,
            "recalculated_after_edit":false,"generated_at":"2026-07-14T20:05:00Z"
          },
          "displayed_summary_date":"\#(summaryDate)",
          "weekly_review":{"window_start":"2026-07-09","window_end":"2026-07-15","recorded_day_count":6,"complete_day_count":5,"protein_low_days":3,"vegetables_adequate_days":4,"uses_score":false}
        }
        """#.utf8)
    }

    private func dashboardWithoutSummaryData(
        selectedDate: String,
        isToday: Bool,
        dayState: String = "open"
    ) -> Data {
        Data(#"""
        {
          "subject_user_id":1,"selected_date":"\#(selectedDate)","is_today":\#(isToday),
          "recorded_meal_count":0,"pending_count":0,"streak_days":0,"day_state":"\#(dayState)",
          "records":[],"pending_drafts":[],"selected_day_summary":null,
          "displayed_summary":null,"displayed_summary_date":"\#(selectedDate)","weekly_review":null
        }
        """#.utf8)
    }

    private func dashboardWithContentData(
        selectedDate: String,
        isToday: Bool,
        summaryDate: String
    ) throws -> Data {
        let base = try XCTUnwrap(
            try JSONSerialization.jsonObject(
                with: dashboardData(
                    selectedDate: selectedDate,
                    isToday: isToday,
                    summaryDate: summaryDate
                )
            ) as? [String: Any]
        )
        let record = try XCTUnwrap(
            try JSONSerialization.jsonObject(
                with: recordData(status: "user_confirmed", version: 3, dietDate: selectedDate)
            ) as? [String: Any]
        )
        let draft = try XCTUnwrap(
            try JSONSerialization.jsonObject(
                with: draftData(id: 7, source: "text", dietDate: selectedDate)
            ) as? [String: Any]
        )
        var result = base
        result["recorded_meal_count"] = 1
        result["pending_count"] = 1
        result["day_state"] = "waiting_confirmation"
        result["records"] = [record]
        result["pending_drafts"] = [draft]
        return try JSONSerialization.data(withJSONObject: result, options: [.sortedKeys])
    }

    private func summaryData(date: String) -> Data {
        Data(#"""
        {
          "subject_user_id":1,"diet_date":"\#(date)","state":"ready","record_version":2,
          "close_method":"manual","record_complete":true,"confirmed_meal_count":1,"pending_count":1,
          "summary":{
            "summary_id":10,"subject_user_id":1,"diet_date":"\#(date)","close_method":"manual",
            "record_complete":true,"confirmed_meal_count":1,"pending_count":1,
            "structure_summary":{"protein":"moderate"},
            "conclusion":"已按确认记录汇总","today_suggestion":"明天继续记录主要餐次",
            "confidence":0.58,
            "evidence":{"included_record_ids":[1],"excluded_pending_draft_ids":[2],"pending_records_excluded":true,"natural_language_generated_by_model":false},
            "rule_version":"dietary-rules-v1","template_version":"dietary-template-v1","record_version":2,
            "recalculated_after_edit":false,"generated_at":"2026-07-15T12:00:00Z"
          }
        }
        """#.utf8)
    }

    private func incompleteCompletionData(date: String) -> Data {
        Data(#"""
        {
          "subject_user_id":1,"diet_date":"\#(date)","state":"incomplete","record_version":0,
          "close_method":"manual","record_complete":false,"confirmed_meal_count":0,"pending_count":0,
          "summary":null
        }
        """#.utf8)
    }

    private static let iso: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        return formatter
    }()
}
