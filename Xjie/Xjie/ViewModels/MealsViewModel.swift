import Foundation
import SwiftUI

enum DietaryLoadState: Equatable {
    case idle
    case loading
    case loaded
    case empty
    case failed
}

@MainActor
final class MealsViewModel: ObservableObject {
    @Published private(set) var loadState: DietaryLoadState = .idle
    @Published private(set) var records: [DietaryMealRecord] = []
    @Published private(set) var pendingDrafts: [DietaryMealDraft] = []
    @Published private(set) var selectedDaySummary: DietaryDailySummary?
    @Published private(set) var displayedSummary: DietaryDailySummary?
    @Published private(set) var weeklyReview: DietaryWeeklyReview?
    @Published private(set) var dayState: DietaryDayState = .open
    @Published private(set) var recordedMealCount = 0
    @Published private(set) var pendingCount = 0
    @Published private(set) var streakDays = 0
    @Published private(set) var isSelectedToday = true
    @Published private(set) var activeDraft: DietaryMealDraft?
    @Published private(set) var recentRecords: [DietaryMealRecord] = []
    @Published private(set) var isMutating = false
    @Published private(set) var lastCompletionAccepted = false
    @Published private(set) var isOffline = false
    @Published private(set) var preservedDraftInput = ""
    @Published var errorMessage: String?
    @Published var selectedDate: Date

    private let api: APIServiceProtocol
    private let now: () -> Date
    private var calendar: Calendar
    private let timeZoneIdentifier: () -> String
    private var activeTimeZoneIdentifier: String
    private let currentAccountScope: @MainActor () -> String?
    private let currentSubjectUserID: @MainActor () -> Int?
    private let makeID: () -> String
    private var authoritativeSubjectUserID: Int?
    private var loadGeneration = 0
    private var pendingDescription: PendingDescription?
    private var pendingPhoto: PendingPhoto?
    private var pendingMutationSnapshots: [String: PendingMutationSnapshot] = [:]
    private var lastObservedTodayKey: String
    private var followsCurrentDietDay = true
    private var dateSelectionGeneration = 0

    private struct PendingDescription {
        let text: String
        let source: DietaryEntrySource
        let eventID: String
        let dietDate: String
        let timezone: String
        let mealType: DietaryMealType
        let eatenAt: String
    }

    private struct PendingPhoto {
        let data: Data
        let fileName: String
        let source: DietaryEntrySource
        let eventID: String
        let dietDate: String
        let timezone: String
        let mealType: DietaryMealType
        let eatenAt: String
    }

    /// One immutable wire operation retained only while delivery is ambiguous.
    /// The typed request is kept alongside its encoded bytes so a retry cannot
    /// silently rebuild the same event with a different payload.
    private struct PendingMutationSnapshot {
        let scope: String
        let operation: String
        let intentFingerprint: Data
        let eventID: String
        let payload: Data
        let request: Any
        let reconciliation: MutationReconciliationSnapshot?
    }

    private struct PreparedMutation<Request> {
        let operation: String
        let request: Request
        let reconciliation: MutationReconciliationSnapshot?
    }

    private struct MutationReconciliationSnapshot {
        let originalDietDate: String
        let removedDraftID: String?
    }

    init(
        api: APIServiceProtocol = APIService.shared,
        now: @escaping () -> Date = Date.init,
        calendar: Calendar = .current,
        timeZoneIdentifier: @escaping () -> String = { TimeZone.current.identifier },
        currentAccountScope: @escaping @MainActor () -> String? = { AuthManager.shared.accountScope },
        currentSubjectUserID: @escaping @MainActor () -> Int? = {
            guard let raw = AuthManager.shared.userInfo?.id else { return nil }
            return Int(raw)
        },
        makeID: @escaping () -> String = { UUID().uuidString.lowercased() }
    ) {
        let initialTimeZoneIdentifier = timeZoneIdentifier()
        var initialCalendar = calendar
        if let initialTimeZone = TimeZone(identifier: initialTimeZoneIdentifier) {
            initialCalendar.timeZone = initialTimeZone
        }
        self.api = api
        self.now = now
        self.calendar = initialCalendar
        self.timeZoneIdentifier = timeZoneIdentifier
        activeTimeZoneIdentifier = initialCalendar.timeZone.identifier
        self.currentAccountScope = currentAccountScope
        self.currentSubjectUserID = currentSubjectUserID
        self.makeID = makeID
        let initialNow = now()
        selectedDate = DietaryDayBoundary.dietDate(for: initialNow, calendar: initialCalendar)
        lastObservedTodayKey = DietaryDayBoundary.dateKey(for: initialNow, calendar: initialCalendar)
    }

    var loading: Bool { loadState == .loading }
    var hasContent: Bool {
        !records.isEmpty || !pendingDrafts.isEmpty || selectedDaySummary != nil || displayedSummary != nil || weeklyReview != nil
    }

    var selectedDateKey: String {
        DietaryDayBoundary.calendarDateKey(for: selectedDate, calendar: calendar)
    }

    var todayKey: String {
        DietaryDayBoundary.dateKey(for: now(), calendar: calendar)
    }

    var canMoveForward: Bool { selectedDateKey < todayKey }
    var summaryTitle: String {
        isSelectedToday
            ? String(localized: "dietary.summary.yesterday", defaultValue: "昨日饮食总结")
            : String(localized: "dietary.summary.selected", defaultValue: "当日饮食总结")
    }

    var shouldShowCurrentDayConclusion: Bool {
        selectedDaySummary?.summaryState.canDisplayConclusion == true
    }

    var selectedDateDisplayText: String {
        let formatter = DateFormatter()
        formatter.calendar = calendar
        formatter.locale = Locale.current
        formatter.timeZone = calendar.timeZone
        formatter.dateFormat = isSelectedToday ? "M月d日 · '今天'" : "yyyy年M月d日 EEEE"
        return formatter.string(from: selectedDate)
    }

    func fetchData() async {
        synchronizeTemporalContext()
        loadGeneration &+= 1
        let generation = loadGeneration
        guard let scope = currentAccountScope() else {
            applyError(APIError.notLoggedIn, state: .failed)
            return
        }

        loadState = .loading
        errorMessage = nil
        isOffline = false
        let path = dashboardPath()
        do {
            let response: DietaryDashboardResponse = try await api.get(path)
            guard generation == loadGeneration, currentAccountScope() == scope else { return }
            try validateDashboard(response)
            authoritativeSubjectUserID = response.subjectUserID
            records = response.records
            pendingDrafts = response.pendingDrafts
            selectedDaySummary = response.selectedDaySummary
            displayedSummary = response.displayedSummary
            weeklyReview = response.weeklyReview
            dayState = response.dayState
            recordedMealCount = response.recordedMealCount
            pendingCount = response.pendingCount
            streakDays = response.streakDays
            isSelectedToday = response.selectedDate == todayKey
            loadState = hasContent ? .loaded : .empty
        } catch {
            guard generation == loadGeneration else { return }
            applyError(error, state: .failed)
        }
    }

    func selectDate(_ date: Date) async {
        let referenceDate = synchronizeTemporalContext()
        let selected = DietaryDayBoundary.clampedSelection(date, now: referenceDate, calendar: calendar)
        followsCurrentDietDay = DietaryDayBoundary.calendarDateKey(for: selected, calendar: calendar) == todayKey
        lastObservedTodayKey = todayKey
        guard !calendar.isDate(selected, inSameDayAs: selectedDate) else { return }
        dateSelectionGeneration &+= 1
        selectedDate = selected
        invalidateDashboardForTemporalChange()
        await fetchData()
    }

    func moveDate(by days: Int) async {
        guard let proposed = calendar.date(byAdding: .day, value: days, to: selectedDate) else { return }
        await selectDate(proposed)
    }

    @discardableResult
    func createDescriptionDraft(
        _ rawText: String,
        source: DietaryEntrySource
    ) async -> DietaryMealDraft? {
        let timestamp = synchronizeTemporalContext()
        let text = rawText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, [.text, .voice, .chat, .manual].contains(source) else {
            errorMessage = String(localized: "dietary.error.descriptionRequired", defaultValue: "请先描述这餐吃了什么")
            return nil
        }
        preservedDraftInput = text
        guard text.count <= DietaryFoodItem.maximumDescriptionLength else {
            errorMessage = String(
                localized: "dietary.error.descriptionTooLong",
                defaultValue: "一次最多输入 4000 个字符，请删减后再试"
            )
            return nil
        }
        guard let scope = mutationScope() else { return nil }

        let requestContext: PendingDescription
        if let pendingDescription,
           pendingDescription.text == text,
           pendingDescription.source == source {
            requestContext = pendingDescription
        } else {
            requestContext = PendingDescription(
                text: text,
                source: source,
                eventID: makeID(),
                dietDate: selectedDateKey,
                timezone: activeTimeZoneIdentifier,
                mealType: DietaryMealType.inferred(at: timestamp, calendar: calendar),
                eatenAt: localTimestamp(timestamp)
            )
            pendingDescription = requestContext
        }
        isMutating = true
        defer { isMutating = false }

        let request = DietaryDraftCreateRequest(
            subject_user_id: subjectForMutation(),
            client_event_id: requestContext.eventID,
            source_type: source,
            diet_date: requestContext.dietDate,
            timezone: requestContext.timezone,
            meal_type: requestContext.mealType,
            eaten_at: requestContext.eatenAt,
            // Raw text is evidence for the server-side dietary extractor.
            // Arbitrary sentences must never be relabelled as food names.
            food_items: [],
            portion_text: nil,
            structure: [:],
            estimated_nutrition: [:],
            field_confidences: [:],
            recognition_confidence: nil,
            source_ref: nil,
            raw_input: text
        )

        do {
            let draft: DietaryMealDraft = try await api.postAccountBound(
                "/api/dietary-records/drafts",
                body: request,
                expectedAccountScope: scope
            )
            try validateDraft(draft)
            guard draft.sourceType == source,
                  draft.dietDate == requestContext.dietDate,
                  draft.timezone == requestContext.timezone
            else { throw DietaryClientError.staleResponse }
            guard currentAccountScope() == scope else { throw APIError.accountScopeChanged }
            pendingDescription = nil
            preservedDraftInput = ""
            acceptDraft(draft)
            return draft
        } catch {
            applyError(error)
            return nil
        }
    }

    @discardableResult
    func createPhotoDraft(
        _ data: Data,
        fileName _: String,
        source: DietaryEntrySource
    ) async -> DietaryMealDraft? {
        let timestamp = synchronizeTemporalContext()
        guard !data.isEmpty,
              source == .camera || source == .photoLibrary,
              let upload = DietaryPhotoUploadNormalizer.prepare(data) else {
            errorMessage = String(localized: "dietary.error.photoRequired", defaultValue: "没有读取到可用的餐食照片")
            return nil
        }
        guard let scope = mutationScope() else { return nil }

        let requestContext: PendingPhoto
        if let pendingPhoto,
           pendingPhoto.data == upload.data,
           pendingPhoto.fileName == upload.fileName,
           pendingPhoto.source == source {
            requestContext = pendingPhoto
        } else {
            requestContext = PendingPhoto(
                data: upload.data,
                fileName: upload.fileName,
                source: source,
                eventID: makeID(),
                dietDate: selectedDateKey,
                timezone: activeTimeZoneIdentifier,
                mealType: DietaryMealType.inferred(at: timestamp, calendar: calendar),
                eatenAt: localTimestamp(timestamp)
            )
            pendingPhoto = requestContext
        }

        var formData = [
            "client_event_id": requestContext.eventID,
            "diet_date": requestContext.dietDate,
            "meal_type": requestContext.mealType.rawValue,
            "eaten_at": requestContext.eatenAt,
            "source": source.rawValue,
            "timezone": requestContext.timezone,
        ]
        if let subject = subjectForMutation() {
            formData["subject_user_id"] = String(subject)
        }

        isMutating = true
        defer { isMutating = false }
        do {
            let response = try await api.putFileAccountBound(
                "/api/dietary-records/drafts/photo",
                fileData: requestContext.data,
                fileName: requestContext.fileName,
                mimeType: upload.mimeType,
                formData: formData,
                expectedAccountScope: scope
            )
            let draft = try JSONDecoder().decode(DietaryMealDraft.self, from: response)
            try validateDraft(draft)
            guard draft.sourceType == source,
                  draft.dietDate == requestContext.dietDate,
                  draft.timezone == requestContext.timezone
            else { throw DietaryClientError.staleResponse }
            guard currentAccountScope() == scope else { throw APIError.accountScopeChanged }
            pendingPhoto = nil
            acceptDraft(draft)
            return draft
        } catch {
            applyError(error)
            return nil
        }
    }

    /// Retries recognition against the original, server-held image while
    /// keeping the draft pending. A successful HTTP replay uses the same
    /// event ID; no formal record can be created by this operation.
    @discardableResult
    func retryRecognition(_ draft: DietaryMealDraft) async -> DietaryMealDraft? {
        guard draft.canRetryRecognition else {
            errorMessage = String(
                localized: "dietary.error.retryUnavailable",
                defaultValue: "这份草稿不能重新识别，请直接手动补充"
            )
            return nil
        }
        guard let scope = mutationScope(),
              let subject = matchingSubject(draft.subjectUserID) else { return nil }

        let eventKey = "retry-recognition:\(draft.draftID):\(draft.version)"
        let intent = DietaryDraftRetryRecognitionRequest(
            subject_user_id: subject,
            client_event_id: "",
            expected_version: draft.version
        )
        guard let mutation = prepareMutation(
            scope: scope,
            eventKey: eventKey,
            intent: intent,
            operation: { "/api/dietary-records/drafts/\(draft.draftID)/retry-recognition" },
            request: { eventID in
                DietaryDraftRetryRecognitionRequest(
                    subject_user_id: subject,
                    client_event_id: eventID,
                    expected_version: draft.version
                )
            }
        ) else { return nil }

        return await performMutation(scope: scope, eventKey: eventKey) {
            let retried: DietaryMealDraft = try await api.postAccountBound(
                mutation.operation,
                body: mutation.request,
                expectedAccountScope: scope
            )
            try validateDraft(retried)
            guard retried.draftID == draft.draftID,
                  retried.sourceType == draft.sourceType,
                  retried.version > draft.version,
                  retried.recognitionStatus == "completed" || retried.recognitionFailed
            else { throw DietaryClientError.staleResponse }
            acceptDraft(retried)
            return retried
        }
    }

    @discardableResult
    func confirmDraft(_ editable: DietaryEditableDraft) async -> DietaryMealRecord? {
        synchronizeTemporalContext()
        guard editable.isValid, editable.original.requiresUserConfirmation else {
            errorMessage = String(localized: "dietary.error.confirmFields", defaultValue: "请确认日期、餐次、食物和大致份量")
            return nil
        }
        guard let scope = mutationScope(),
              let subject = matchingSubject(editable.original.subjectUserID) else { return nil }
        let eventKey = "confirm:\(editable.original.draftID):\(editable.original.version)"
        let foodItems = sanitized(editable.foodItems)
        let intent = DietaryDraftConfirmRequest(
            subject_user_id: subject,
            client_event_id: "",
            expected_version: editable.original.version,
            // A system time-zone change is not a user edit. The first full
            // request retains its original zone until delivery is certain.
            timezone: "",
            diet_date: editable.dietDate,
            meal_type: editable.mealType,
            eaten_at: editable.eatenAt,
            food_items: foodItems,
            portion_text: nilIfBlank(editable.portionText),
            structure: editable.structure,
            estimated_nutrition: editable.estimatedNutrition,
            field_confidences: editable.original.fieldConfidences,
            recognition_confidence: editable.original.recognitionConfidence
        )
        guard let mutation = prepareMutation(
            scope: scope,
            eventKey: eventKey,
            intent: intent,
            reconciliation: MutationReconciliationSnapshot(
                originalDietDate: editable.original.dietDate,
                removedDraftID: editable.original.draftID
            ),
            operation: { "/api/dietary-records/drafts/\(editable.original.draftID)/confirm" },
            request: { eventID in
                DietaryDraftConfirmRequest(
                    subject_user_id: subject,
                    client_event_id: eventID,
                    expected_version: editable.original.version,
                    timezone: activeTimeZoneIdentifier,
                    diet_date: editable.dietDate,
                    meal_type: editable.mealType,
                    eaten_at: editable.eatenAt,
                    food_items: foodItems,
                    portion_text: nilIfBlank(editable.portionText),
                    structure: editable.structure,
                    estimated_nutrition: editable.estimatedNutrition,
                    field_confidences: editable.original.fieldConfidences,
                    recognition_confidence: editable.original.recognitionConfidence
                )
            }
        ) else { return nil }

        return await performMutation(scope: scope, eventKey: eventKey) {
            let record: DietaryMealRecord = try await api.postAccountBound(
                mutation.operation,
                body: mutation.request,
                expectedAccountScope: scope
            )
            try validateRecord(record, expectedSubject: subject)
            guard record.version >= 1 else { throw DietaryClientError.staleResponse }
            guard let reconciliation = mutation.reconciliation else {
                throw DietaryClientError.staleResponse
            }
            await reconcileAfterMutation(
                record: record,
                originalDietDate: reconciliation.originalDietDate,
                removedDraftID: reconciliation.removedDraftID
            )
            activeDraft = nil
            return record
        }
    }

    @discardableResult
    func updateRecord(_ editable: DietaryEditableRecord) async -> DietaryMealRecord? {
        synchronizeTemporalContext()
        guard editable.isValid,
              let scope = mutationScope(),
              let subject = matchingSubject(editable.original.subjectUserID) else {
            if !editable.isValid {
                errorMessage = String(localized: "dietary.error.confirmFields", defaultValue: "请确认日期、餐次、食物和大致份量")
            }
            return nil
        }
        let eventKey = "update:\(editable.original.recordID):\(editable.original.version)"
        let foodItems = sanitized(editable.foodItems)
        let intent = DietaryRecordUpdateRequest(
            subject_user_id: subject,
            client_event_id: "",
            expected_version: editable.original.version,
            timezone: "",
            diet_date: editable.dietDate,
            meal_type: editable.mealType,
            eaten_at: editable.eatenAt,
            food_items: foodItems,
            portion_text: nilIfBlank(editable.portionText),
            structure: editable.structure,
            estimated_nutrition: editable.estimatedNutrition,
            field_confidences: editable.original.fieldConfidences,
            recognition_confidence: editable.original.confidence
        )
        guard let mutation = prepareMutation(
            scope: scope,
            eventKey: eventKey,
            intent: intent,
            reconciliation: MutationReconciliationSnapshot(
                originalDietDate: editable.original.dietDate,
                removedDraftID: nil
            ),
            operation: { "/api/dietary-records/records/\(editable.original.recordID)" },
            request: { eventID in
                DietaryRecordUpdateRequest(
                    subject_user_id: subject,
                    client_event_id: eventID,
                    expected_version: editable.original.version,
                    timezone: activeTimeZoneIdentifier,
                    diet_date: editable.dietDate,
                    meal_type: editable.mealType,
                    eaten_at: editable.eatenAt,
                    food_items: foodItems,
                    portion_text: nilIfBlank(editable.portionText),
                    structure: editable.structure,
                    estimated_nutrition: editable.estimatedNutrition,
                    field_confidences: editable.original.fieldConfidences,
                    recognition_confidence: editable.original.confidence
                )
            }
        ) else { return nil }

        return await performMutation(scope: scope, eventKey: eventKey) {
            let record: DietaryMealRecord = try await api.patchAccountBound(
                mutation.operation,
                body: mutation.request,
                expectedAccountScope: scope
            )
            try validateRecord(record, expectedSubject: subject)
            guard record.version > editable.original.version else { throw DietaryClientError.staleResponse }
            guard let reconciliation = mutation.reconciliation else {
                throw DietaryClientError.staleResponse
            }
            await reconcileAfterMutation(
                record: record,
                originalDietDate: reconciliation.originalDietDate
            )
            return record
        }
    }

    @discardableResult
    func reuseRecord(_ record: DietaryMealRecord) async -> DietaryMealDraft? {
        let referenceDate = synchronizeTemporalContext()
        guard let scope = mutationScope(),
              let subject = matchingSubject(record.subjectUserID) else { return nil }
        let eventKey = "reuse:\(record.recordID):\(record.version):\(dateSelectionGeneration)"
        let intent = [
            "record_id": record.recordID,
            "record_version": String(record.version),
            "selection_generation": String(dateSelectionGeneration),
            "subject_user_id": String(subject),
        ]
        guard let mutation = prepareMutation(
            scope: scope,
            eventKey: eventKey,
            intent: intent,
            operation: { "/api/dietary-records/records/\(record.recordID)/reuse" },
            request: { eventID in
                let targetTimestamp = timestampForSelectedDay(referenceDate: referenceDate)
                return DietaryRecordReuseRequest(
                    subject_user_id: subject,
                    client_event_id: eventID,
                    expected_version: record.version,
                    timezone: activeTimeZoneIdentifier,
                    diet_date: selectedDateKey,
                    meal_type: record.mealType == .unknown
                        ? DietaryMealType.inferred(at: targetTimestamp, calendar: calendar)
                        : record.mealType,
                    eaten_at: localTimestamp(targetTimestamp)
                )
            }
        ) else { return nil }
        return await performMutation(scope: scope, eventKey: eventKey) {
            let draft: DietaryMealDraft = try await api.postAccountBound(
                mutation.operation,
                body: mutation.request,
                expectedAccountScope: scope
            )
            try validateDraft(draft)
            guard draft.sourceType == .recent,
                  draft.dietDate == mutation.request.diet_date,
                  draft.timezone == mutation.request.timezone
            else { throw DietaryClientError.staleResponse }
            acceptDraft(draft)
            return draft
        }
    }

    @discardableResult
    func deleteRecord(_ record: DietaryMealRecord) async -> Bool {
        guard let scope = mutationScope(),
              let subject = matchingSubject(record.subjectUserID) else { return false }
        let eventKey = "delete:\(record.recordID):\(record.version)"
        let intent = DietaryMutationRequest(
            subject_user_id: subject,
            client_event_id: "",
            expected_version: record.version
        )
        guard let mutation = prepareMutation(
            scope: scope,
            eventKey: eventKey,
            intent: intent,
            operation: { "/api/dietary-records/records/\(record.recordID)" },
            request: { eventID in
                DietaryMutationRequest(
                    subject_user_id: subject,
                    client_event_id: eventID,
                    expected_version: record.version
                )
            }
        ) else { return false }
        let result: Bool? = await performMutation(scope: scope, eventKey: eventKey) {
            try await api.deleteVoidAccountBound(
                mutation.operation,
                body: mutation.request,
                expectedAccountScope: scope
            )
            await reconcileAfterDeletion(record)
            return true
        }
        return result == true
    }

    @discardableResult
    func completeSelectedDayWithConfirmedRecords() async -> DietaryDailySummary? {
        synchronizeTemporalContext()
        lastCompletionAccepted = false
        guard let scope = mutationScope(), let subject = subjectForMutation() else { return nil }
        let eventKey = "complete:\(dateSelectionGeneration)"
        let intent = [
            "selection_generation": String(dateSelectionGeneration),
            "subject_user_id": String(subject),
            "complete_with_confirmed_only": "true",
        ]
        guard let mutation = prepareMutation(
            scope: scope,
            eventKey: eventKey,
            intent: intent,
            operation: { "/api/dietary-records/days/\(selectedDateKey)/complete" },
            request: { eventID in
                DietaryDayCompleteRequest(
                    timezone: activeTimeZoneIdentifier,
                    subject_user_id: subject,
                    client_event_id: eventID,
                    complete_with_confirmed_only: true
                )
            }
        ) else { return nil }
        let response: DietaryDayCompletionResponse? = await performMutation(scope: scope, eventKey: eventKey) {
            let response: DietaryDayCompletionResponse = try await api.postAccountBound(
                mutation.operation,
                body: mutation.request,
                expectedAccountScope: scope
            )
            guard response.subjectUserID == subject,
                  mutation.operation == "/api/dietary-records/days/\(response.dietDate)/complete",
                  response.summary.map({ $0.subjectUserID == subject && $0.dietDate == response.dietDate }) ?? true
            else {
                throw DietaryClientError.subjectOrDateMismatch
            }
            if response.dietDate == selectedDateKey {
                dayState = response.state
                recordedMealCount = response.confirmedMealCount
                pendingCount = response.pendingCount
                selectedDaySummary = response.summary
                if !isSelectedToday, let summary = response.summary { displayedSummary = summary }
            } else {
                await fetchData()
            }
            lastCompletionAccepted = true
            return response
        }
        return response?.summary
    }

    func fetchRecentRecords(limit: Int = 12) async {
        guard let scope = mutationScope() else { return }
        var items = [URLQueryItem(name: "limit", value: String(max(1, min(limit, 30))))]
        if let subject = subjectForMutation() {
            items.append(URLQueryItem(name: "subject_user_id", value: String(subject)))
        }
        do {
            let response: DietaryRecentResponse = try await api.get(
                URLBuilder.path("/api/dietary-records/recent", queryItems: items)
            )
            guard currentAccountScope() == scope else { throw APIError.accountScopeChanged }
            if let expected = subjectForMutation(), response.subjectUserID != expected {
                throw DietaryClientError.subjectOrDateMismatch
            }
            authoritativeSubjectUserID = response.subjectUserID
            recentRecords = response.items.filter { $0.subjectUserID == response.subjectUserID }
        } catch {
            applyError(error)
        }
    }

    func activateDraft(_ draft: DietaryMealDraft) {
        guard draft.subjectUserID == subjectForMutation(), draft.isEditable else { return }
        activeDraft = draft
    }

    func dismissDraftEditor() {
        activeDraft = nil
    }

    func clearError() {
        errorMessage = nil
        isOffline = false
    }

    #if DEBUG
    func adoptAuthoritativeSubjectForTesting(_ subjectUserID: Int) {
        authoritativeSubjectUserID = subjectUserID
    }
    #endif

    private func dashboardPath() -> String {
        var items = [
            URLQueryItem(name: "diet_date", value: selectedDateKey),
            URLQueryItem(name: "timezone", value: activeTimeZoneIdentifier),
        ]
        if let subject = authoritativeSubjectUserID {
            items.append(URLQueryItem(name: "subject_user_id", value: String(subject)))
        }
        return URLBuilder.path("/api/dietary-records/dashboard", queryItems: items)
    }

    /// Captures one time-zone/clock snapshot for an operation. When the system
    /// zone changes, both the calendar and wire `timezone` move together;
    /// history keeps its logical YYYY-MM-DD while a view following "today"
    /// moves to the new zone's 04:00-based dietary day.
    @discardableResult
    private func synchronizeTemporalContext() -> Date {
        let referenceDate = now()
        let previousTimeZoneIdentifier = activeTimeZoneIdentifier
        let previousDietDate = selectedDateKey
        let requestedIdentifier = timeZoneIdentifier()
        if requestedIdentifier != activeTimeZoneIdentifier,
           let requestedTimeZone = TimeZone(identifier: requestedIdentifier) {
            let historicalDateKey = selectedDateKey
            calendar.timeZone = requestedTimeZone
            activeTimeZoneIdentifier = requestedIdentifier
            if followsCurrentDietDay {
                selectedDate = DietaryDayBoundary.dietDate(for: referenceDate, calendar: calendar)
                activeDraft = nil
            } else if let pinnedDate = DietaryDayBoundary.date(from: historicalDateKey, calendar: calendar) {
                selectedDate = pinnedDate
            }
        }
        synchronizeDietDayIfNeeded(referenceDate: referenceDate)
        if previousTimeZoneIdentifier != activeTimeZoneIdentifier || previousDietDate != selectedDateKey {
            invalidateDashboardForTemporalChange()
        }
        return referenceDate
    }

    /// A new logical day or time zone has a different dashboard identity.
    /// Clear every derived field synchronously so a failed refresh or a first
    /// mutation after rollover cannot mix the new title/date with old content.
    private func invalidateDashboardForTemporalChange() {
        loadGeneration &+= 1
        records = []
        pendingDrafts = []
        selectedDaySummary = nil
        displayedSummary = nil
        weeklyReview = nil
        dayState = .unknown
        recordedMealCount = 0
        pendingCount = 0
        streakDays = 0
        isSelectedToday = selectedDateKey == todayKey
        activeDraft = nil
        lastCompletionAccepted = false
        loadState = .idle
    }

    /// The dietary day rolls over at 04:00 local time. A view model following
    /// "today" advances without reconstruction; intentional history browsing
    /// remains pinned to the user's selected day.
    private func synchronizeDietDayIfNeeded(referenceDate: Date) {
        let currentTodayKey = DietaryDayBoundary.dateKey(for: referenceDate, calendar: calendar)
        defer { lastObservedTodayKey = currentTodayKey }
        guard currentTodayKey != lastObservedTodayKey, followsCurrentDietDay else { return }
        selectedDate = DietaryDayBoundary.dietDate(for: referenceDate, calendar: calendar)
        activeDraft = nil
    }

    private func mutationScope() -> String? {
        guard let scope = currentAccountScope(), !scope.isEmpty else {
            pendingMutationSnapshots.removeAll()
            applyError(APIError.notLoggedIn)
            return nil
        }
        pendingMutationSnapshots = pendingMutationSnapshots.filter { $0.value.scope == scope }
        return scope
    }

    private func subjectForMutation() -> Int? {
        authoritativeSubjectUserID ?? currentSubjectUserID()
    }

    private func matchingSubject(_ expected: Int) -> Int? {
        guard let current = subjectForMutation(), current == expected else {
            applyError(DietaryClientError.subjectOrDateMismatch)
            return nil
        }
        return current
    }

    private func validateDashboard(_ response: DietaryDashboardResponse) throws {
        let expectedIsToday = response.selectedDate == todayKey
        guard response.subjectUserID > 0,
              response.selectedDate == selectedDateKey,
              response.isToday == expectedIsToday,
              response.records.allSatisfy({ $0.subjectUserID == response.subjectUserID }),
              response.pendingDrafts.allSatisfy({ $0.subjectUserID == response.subjectUserID }),
              response.selectedDaySummary.map({ $0.subjectUserID == response.subjectUserID }) ?? true,
              response.displayedSummary.map({ $0.subjectUserID == response.subjectUserID }) ?? true
        else { throw DietaryClientError.subjectOrDateMismatch }
        if let expected = authoritativeSubjectUserID ?? currentSubjectUserID(), expected != response.subjectUserID {
            throw DietaryClientError.subjectOrDateMismatch
        }
    }

    private func validateDraft(_ draft: DietaryMealDraft) throws {
        guard draft.subjectUserID > 0,
              draft.isEditable,
              let expected = subjectForMutation(),
              draft.subjectUserID == expected
        else { throw DietaryClientError.unconfirmedDraftContract }
        authoritativeSubjectUserID = draft.subjectUserID
    }

    private func validateRecord(_ record: DietaryMealRecord, expectedSubject: Int) throws {
        guard record.subjectUserID == expectedSubject,
              record.status == .userConfirmed || record.status == .modified
        else { throw DietaryClientError.unconfirmedDraftContract }
    }

    private func acceptDraft(_ draft: DietaryMealDraft) {
        authoritativeSubjectUserID = draft.subjectUserID
        pendingDrafts.removeAll { $0.draftID == draft.draftID }
        if draft.dietDate == selectedDateKey {
            pendingDrafts.insert(draft, at: 0)
        }
        pendingCount = pendingDrafts.count
        activeDraft = draft
    }

    private func upsert(_ record: DietaryMealRecord) {
        records.removeAll { $0.recordID == record.recordID }
        records.append(record)
        records.sort { $0.eatenAt < $1.eatenAt }
    }

    private func reconcileAfterMutation(
        record: DietaryMealRecord,
        originalDietDate: String,
        removedDraftID: String? = nil
    ) async {
        if let removedDraftID {
            pendingDrafts.removeAll { $0.draftID == removedDraftID }
        }
        records.removeAll { $0.recordID == record.recordID }
        if record.dietDate == selectedDateKey {
            upsert(record)
        }
        pendingCount = pendingDrafts.count
        recordedMealCount = records.count

        let movedAcrossDays = originalDietDate != record.dietDate
        let selectedDayWasClosedOrDerived = dayState != .open
        let selectedDayIsOutsideMutation = selectedDateKey != originalDietDate && selectedDateKey != record.dietDate
        if movedAcrossDays || selectedDayWasClosedOrDerived || selectedDayIsOutsideMutation {
            await fetchData()
        }
    }

    /// Clears locally derived values first so a failed dashboard refresh can
    /// never leave the deleted record's old closed-day conclusion on screen.
    /// The successful delete is then reconciled from the authoritative
    /// dashboard in one MainActor update (records, summaries, state, counts).
    private func reconcileAfterDeletion(_ record: DietaryMealRecord) async {
        records.removeAll { $0.recordID == record.recordID }
        recordedMealCount = records.count
        if selectedDaySummary?.dietDate == record.dietDate {
            selectedDaySummary = nil
        }
        if displayedSummary?.dietDate == record.dietDate {
            displayedSummary = nil
        }
        if selectedDateKey == record.dietDate {
            dayState = .stale
        }
        await fetchData()
    }

    /// Captures operation, event ID and the exact encoded request before the
    /// first suspension point. Once delivery is ambiguous, even a local edit
    /// must replay the pending snapshot until success or an explicit rejection
    /// resolves it. Only then may the edited intent create a fresh event.
    private func prepareMutation<Request: Encodable, Intent: Encodable>(
        scope: String,
        eventKey: String,
        intent: Intent,
        reconciliation: MutationReconciliationSnapshot? = nil,
        operation: () -> String,
        request: (String) -> Request
    ) -> PreparedMutation<Request>? {
        // Account changes must not carry any idempotency state into the next
        // signed-in subject, even if an entity happens to reuse the same ID.
        pendingMutationSnapshots = pendingMutationSnapshots.filter { $0.value.scope == scope }

        guard let intentFingerprint = encodeMutationValue(intent) else {
            applyError(DietaryClientError.requestEncodingFailed)
            return nil
        }
        if let existing = pendingMutationSnapshots[eventKey] {
            guard existing.scope == scope,
                  let typedRequest = existing.request as? Request,
                  encodeMutationValue(typedRequest) == existing.payload
            else {
                applyError(DietaryClientError.requestEncodingFailed)
                return nil
            }
            return PreparedMutation(
                operation: existing.operation,
                request: typedRequest,
                reconciliation: existing.reconciliation
            )
        }

        let eventID = makeID()
        let immutableOperation = operation()
        let immutableRequest = request(eventID)
        guard !eventID.isEmpty,
              !immutableOperation.isEmpty,
              let payload = encodeMutationValue(immutableRequest)
        else {
            pendingMutationSnapshots.removeValue(forKey: eventKey)
            applyError(DietaryClientError.requestEncodingFailed)
            return nil
        }
        pendingMutationSnapshots[eventKey] = PendingMutationSnapshot(
            scope: scope,
            operation: immutableOperation,
            intentFingerprint: intentFingerprint,
            eventID: eventID,
            payload: payload,
            request: immutableRequest,
            reconciliation: reconciliation
        )
        return PreparedMutation(
            operation: immutableOperation,
            request: immutableRequest,
            reconciliation: reconciliation
        )
    }

    private func encodeMutationValue<Value: Encodable>(_ value: Value) -> Data? {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        return try? encoder.encode(value)
    }

    /// Fail-safe classification: clear only when the request is known not to
    /// have been sent or the server explicitly rejected it. Cancellation,
    /// transport errors, 5xx, invalid/undecodable 2xx bodies and post-response
    /// contract validation are all ambiguous and must retain the exact event.
    private func isDefinitiveMutationFailure(_ error: Error) -> Bool {
        guard let apiError = error as? APIError else { return false }
        switch apiError {
        case .notLoggedIn, .accountScopeChanged, .unsupportedOperation,
             .invalidMultipartForm, .invalidURL:
            return true
        case let .httpError(status, _), let .httpErrorResponse(status, _, _):
            return (400 ..< 500).contains(status) && status != 408
        case .invalidResponse:
            return false
        }
    }

    private func performMutation<T>(
        scope: String,
        eventKey: String,
        operation: () async throws -> T
    ) async -> T? {
        isMutating = true
        errorMessage = nil
        isOffline = false
        defer { isMutating = false }
        do {
            let result = try await operation()
            guard currentAccountScope() == scope else { throw APIError.accountScopeChanged }
            pendingMutationSnapshots.removeValue(forKey: eventKey)
            return result
        } catch {
            if currentAccountScope() != scope || isDefinitiveMutationFailure(error) {
                pendingMutationSnapshots.removeValue(forKey: eventKey)
            }
            applyError(error)
            return nil
        }
    }

    private func applyError(_ error: Error, state: DietaryLoadState? = nil) {
        if let state { loadState = state }
        if let urlError = error as? URLError {
            isOffline = [.notConnectedToInternet, .networkConnectionLost, .timedOut].contains(urlError.code)
        } else {
            isOffline = false
        }
        errorMessage = isOffline
            ? String(localized: "dietary.error.offline", defaultValue: "网络暂不可用，已保留输入，请恢复网络后重试")
            : (error as? LocalizedError)?.errorDescription
                ?? String(localized: "dietary.error.generic", defaultValue: "膳食记录暂时无法更新，请稍后重试")
    }

    private func sanitized(_ items: [DietaryFoodItem]) -> [DietaryFoodItem] {
        items.compactMap { item in
            let name = item.name.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !name.isEmpty else { return nil }
            var copy = item
            copy.name = name
            copy.portionText = copy.portionText.flatMap { nilIfBlank($0) }
            return copy
        }
    }

    private func nilIfBlank(_ value: String) -> String? {
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed
    }

    private func localTimestamp(_ date: Date) -> String {
        let formatter = DateFormatter()
        formatter.calendar = calendar
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = calendar.timeZone
        formatter.dateFormat = "yyyy-MM-dd'T'HH:mm:ssXXX"
        return formatter.string(from: date)
    }

    private func timestampForSelectedDay(referenceDate current: Date) -> Date {
        var day = calendar.dateComponents([.year, .month, .day], from: selectedDate)
        let clock = calendar.dateComponents([.hour, .minute, .second], from: current)
        day.hour = clock.hour
        day.minute = clock.minute
        day.second = clock.second
        return calendar.date(from: day) ?? current
    }
}

private enum DietaryClientError: LocalizedError {
    case subjectOrDateMismatch
    case unconfirmedDraftContract
    case staleResponse
    case requestEncodingFailed

    var errorDescription: String? {
        switch self {
        case .subjectOrDateMismatch:
            return String(localized: "dietary.error.accountChanged", defaultValue: "账号或记录对象已变化，请刷新后重试")
        case .unconfirmedDraftContract:
            return String(localized: "dietary.error.confirmationContract", defaultValue: "服务器没有返回可确认的膳食草稿")
        case .staleResponse:
            return String(localized: "dietary.error.stale", defaultValue: "记录已经更新，请刷新后再修改")
        case .requestEncodingFailed:
            return String(localized: "dietary.error.encoding", defaultValue: "无法准备本次膳食请求，请重新操作")
        }
    }
}
