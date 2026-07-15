import Foundation
import Combine

enum MedicationClientContractError: LocalizedError, Equatable {
    case accountUnavailable
    case accountChanged
    case subjectMismatch
    case invalidTrustedResponse(String)
    case invalidDraft(String)

    var errorDescription: String? {
        switch self {
        case .accountUnavailable: return "无法确认当前登录账号，已停止读取用药信息。"
        case .accountChanged: return "登录账号已变化，已停止本次用药操作。"
        case .subjectMismatch: return "用药数据主体不一致，已拒绝显示或提交。"
        case .invalidTrustedResponse(let reason): return "服务端用药状态未通过可信校验：\(reason)"
        case .invalidDraft(let reason): return reason
        }
    }
}

@MainActor
final class MedicationViewModel: ObservableObject {
    @Published private(set) var today: MedicationTodaySummary?
    @Published private(set) var plans: [TrustedMedicationPlan] = []
    @Published private(set) var prefillCandidates: [MedicationPrefillCandidate] = []
    @Published private(set) var reactions: [MedicationReaction] = []
    @Published private(set) var legacyRecords: [Medication] = []
    @Published private(set) var reminderSettingsByPlanID: [Int: MedicationReminderSettings] = [:]
    @Published private(set) var reminderPermission: MedicationReminderPermissionState = .unknown
    @Published private(set) var confirmationInsights: MedicationConfirmationInsights = .unavailable
    @Published private(set) var loading = false
    @Published private(set) var mutating = false
    @Published var errorMessage: String?
    @Published var infoMessage: String?

    private enum PendingMutation: Equatable {
        case recognize(MedicationRecognitionBody, String)
        case confirm(MedicationPlanConfirmRequest, String)
        case revise(Int, MedicationPlanReviseRequest, String)
        case status(Int, MedicationPlanStatusRequest, String)
        case reject(Int, MedicationPrefillRejectRequest, String)
        case dose(MedicationDoseActionRequest, String)
        case createReaction(MedicationReactionCreateRequest, String)
        case correctReaction(String, MedicationReactionCorrectRequest, String)
        case retractReaction(String, MedicationReactionRetractRequest, String)

        var clientEventID: String {
            switch self {
            case .recognize(let request, _): return request.client_event_id
            case .confirm(let request, _): return request.client_event_id
            case .revise(_, let request, _): return request.client_event_id
            case .status(_, let request, _): return request.client_event_id
            case .reject(_, let request, _): return request.client_event_id
            case .dose(let request, _): return request.client_event_id
            case .createReaction(let request, _): return request.client_event_id
            case .correctReaction(_, let request, _): return request.client_event_id
            case .retractReaction(_, let request, _): return request.client_event_id
            }
        }

        var subjectUserID: Int {
            switch self {
            case .recognize(let request, _): return request.subject_user_id
            case .confirm(let request, _): return request.subject_user_id
            case .revise(_, let request, _): return request.subject_user_id
            case .status(_, let request, _): return request.subject_user_id
            case .reject(_, let request, _): return request.subject_user_id
            case .dose(let request, _): return request.subject_user_id
            case .createReaction(let request, _): return request.subject_user_id
            case .correctReaction(_, let request, _): return request.subject_user_id
            case .retractReaction(_, let request, _): return request.subject_user_id
            }
        }

        var accountScope: String {
            switch self {
            case .recognize(_, let scope), .confirm(_, let scope), .revise(_, _, let scope),
                    .status(_, _, let scope), .reject(_, _, let scope), .dose(_, let scope),
                    .createReaction(_, let scope), .correctReaction(_, _, let scope),
                    .retractReaction(_, _, let scope):
                return scope
            }
        }
    }

    private let repository: MedicationRepositoryProtocol
    private let reminderStore: MedicationReminderStoreProtocol
    private let reminderCoordinator: MedicationReminderCoordinating
    private let currentAccountScope: @MainActor () -> String?
    private let makeClientEventID: () -> String
    private let localDate: () -> String
    private let timezoneOffsetMinutes: () -> Int
    private let currentTimezone: () -> TimeZone
    private let now: () -> Date
    private var activeAccountScope: String?
    private var activeSubjectUserID: Int?
    private var pendingMutation: PendingMutation?
    private var loadGeneration = UUID()
    private var confirmationTask: Task<Void, Never>?

    init(
        repository: MedicationRepositoryProtocol = MedicationRepository(),
        reminderStore: MedicationReminderStoreProtocol? = nil,
        reminderCoordinator: MedicationReminderCoordinating? = nil,
        currentAccountScope: @escaping @MainActor () -> String? = { AuthManager.shared.accountScope },
        makeClientEventID: @escaping () -> String = { UUID().uuidString.lowercased() },
        localDate: @escaping () -> String = {
            let formatter = DateFormatter()
            formatter.calendar = Calendar(identifier: .gregorian)
            formatter.locale = Locale(identifier: "en_US_POSIX")
            formatter.timeZone = .current
            formatter.dateFormat = "yyyy-MM-dd"
            return formatter.string(from: Date())
        },
        timezoneOffsetMinutes: @escaping () -> Int = {
            TimeZone.current.secondsFromGMT() / 60
        },
        currentTimezone: @escaping () -> TimeZone = { .current },
        now: @escaping () -> Date = { Date() }
    ) {
        self.repository = repository
        self.reminderStore = reminderStore ?? MedicationReminderStore()
        self.reminderCoordinator = reminderCoordinator ?? MedicationReminderCoordinator()
        self.currentAccountScope = currentAccountScope
        self.makeClientEventID = makeClientEventID
        self.localDate = localDate
        self.timezoneOffsetMinutes = timezoneOffsetMinutes
        self.currentTimezone = currentTimezone
        self.now = now
    }

    var subjectUserID: Int? { activeSubjectUserID }
    var pendingPrefills: [MedicationPrefillCandidate] { prefillCandidates.filter(\.isPendingReview) }
    var activePlans: [TrustedMedicationPlan] { plans.filter { $0.status == .active || $0.status == .paused } }
    var hasPendingRetry: Bool { pendingMutation != nil && !mutating }
    var pendingClientEventID: String? { pendingMutation?.clientEventID }
    var prescriptionImportCandidates: [MedicationPrefillCandidate] {
        pendingPrefills.filter { $0.source_type == .prescriptionImport }
    }
    var primaryAction: MedicationPrimaryAction {
        MedicationTrustPolicy.primaryAction(
            today: today,
            plans: plans,
            pendingPrefills: pendingPrefills
        )
    }

    func reminderSettings(for plan: TrustedMedicationPlan) -> MedicationReminderSettings {
        if var existing = reminderSettingsByPlanID[plan.plan_id] {
            if existing.planVersion != plan.version || existing.subjectUserID != plan.subject_user_id {
                existing.planVersion = plan.version
                existing.enabled = false
                existing.mealRelation = plan.meal_relation
                existing.courseEnd = plan.course_end
                existing.timezoneIdentifier = currentTimezone().identifier
                existing.updatedAt = Self.isoString(now())
            }
            return existing
        }
        return MedicationReminderSettings.defaultValue(
            for: plan,
            localDate: localDate(),
            timezoneIdentifier: currentTimezone().identifier
        )
    }

    func isReminderEnabled(for plan: TrustedMedicationPlan) -> Bool {
        guard let settings = reminderSettingsByPlanID[plan.plan_id] else { return false }
        return settings.enabled
            && reminderPermission == .allowed
            && MedicationReminderPolicy.isVersionCompatible(settings, with: plan)
    }

    func snoozeMinutes(for task: MedicationTodayTask) -> Int {
        reminderSettingsByPlanID[task.plan_id]?.snoozeMinutes ?? 15
    }

    func courseConfirmationMetric(for plan: TrustedMedicationPlan) -> MedicationConfirmationMetric {
        confirmationInsights.courseByPlanID[plan.plan_id]
            ?? .unavailable("服务端尚未提供这项计划的完整疗程历史。")
    }

    func saveReminderSettings(
        _ settings: MedicationReminderSettings,
        for plan: TrustedMedicationPlan
    ) async -> Bool {
        guard plan.subject_user_id == activeSubjectUserID,
              let scope = mutationScope() else { return false }
        var candidate = settings
        candidate.planVersion = plan.version
        candidate.mealRelation = plan.meal_relation
        candidate.courseEnd = plan.course_end
        candidate.timezoneIdentifier = currentTimezone().identifier
        candidate.updatedAt = Self.isoString(now())
        if let issue = MedicationReminderPolicy.validationIssue(for: candidate, plan: plan) {
            errorMessage = issue
            return false
        }
        if candidate.enabled {
            reminderPermission = await reminderCoordinator.requestPermission()
            guard reminderPermission == .allowed else {
                errorMessage = reminderPermission == .denied
                    ? "通知权限已关闭。请打开系统设置恢复权限，再回到本页保存提醒。"
                    : "当前环境无法开启真实通知，提醒没有被标记为已安排。"
                return false
            }
        }
        var values = reminderSettingsByPlanID
        values[plan.plan_id] = candidate
        do {
            try reminderStore.save(
                Array(values.values),
                accountScope: scope,
                subjectUserID: plan.subject_user_id
            )
        } catch {
            errorMessage = "提醒设置未能安全保存：\(error.localizedDescription)"
            return false
        }
        reminderSettingsByPlanID = values
        let result = await reconcileReminders(scope: scope)
        guard !candidate.enabled || (result.permission == .allowed && result.scheduledCount > 0) else {
            var disabled = candidate
            disabled.enabled = false
            reminderSettingsByPlanID[plan.plan_id] = disabled
            try? reminderStore.save(
                Array(reminderSettingsByPlanID.values),
                accountScope: scope,
                subjectUserID: plan.subject_user_id
            )
            errorMessage = result.detail ?? "没有成功安排任何本机提醒，设置已保持关闭。"
            return false
        }
        errorMessage = nil
        infoMessage = candidate.enabled
            ? "已按当前计划版本安排 \(result.scheduledCount) 次最近提醒。\(result.detail ?? "")"
            : "本机提醒已关闭；可信用药计划和历史记录不受影响。"
        return true
    }

    func refreshReminderPermission() async {
        reminderPermission = await reminderCoordinator.permissionState()
        guard let scope = activeAccountScope,
              activeSubjectUserID != nil,
              validateAccount(scope) else { return }
        _ = await reconcileReminders(scope: scope)
    }

    func load(accountScope: String?) async {
        loadGeneration = UUID()
        let generation = loadGeneration
        reset(for: accountScope)
        // Account/subject changes fail closed: remove every pending medication
        // notification before a new trusted subject has been established. A
        // successful refresh below recreates only the new account's reminders.
        await reminderCoordinator.clearAllMedicationNotifications()
        guard generation == loadGeneration else { return }
        reminderPermission = await reminderCoordinator.permissionState()
        guard generation == loadGeneration else { return }
        guard let accountScope, currentAccountScope() == accountScope else {
            errorMessage = MedicationClientContractError.accountUnavailable.localizedDescription
            return
        }
        loading = true
        defer {
            if generation == loadGeneration { loading = false }
        }
        await refresh(generation: generation, bootstrapSubject: true)
    }

    func reload() async {
        guard let scope = mutationScope() else { return }
        loadGeneration = UUID()
        let generation = loadGeneration
        activeAccountScope = scope
        loading = true
        defer {
            if generation == loadGeneration { loading = false }
        }
        await refresh(generation: generation, bootstrapSubject: activeSubjectUserID == nil)
    }

    #if DEBUG
    func waitForConfirmationInsightsForTesting() async {
        let task = confirmationTask
        await task?.value
    }
    #endif

    func recognize(rawText: String) async {
        let normalized = rawText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !normalized.isEmpty else {
            errorMessage = "请先粘贴或输入处方、药盒的 OCR 文字。"
            return
        }
        guard let subject = activeSubjectUserID, let scope = mutationScope() else { return }
        let request = MedicationRecognitionBody(
            raw_text: normalized,
            subject_user_id: subject,
            client_event_id: newClientEventID()
        )
        await start(.recognize(request, scope))
    }

    func confirmPlan(
        draft: MedicationPlanDraft,
        candidate: MedicationPrefillCandidate?,
        sourceType: MedicationSourceType = .manual,
        sourceRef: String? = nil
    ) async {
        guard draft.isValid else {
            errorMessage = draft.validationIssue ?? "请检查用药表单。"
            return
        }
        guard let subject = activeSubjectUserID, let scope = mutationScope() else { return }
        if let candidate, candidate.subject_user_id != subject || !candidate.isPendingReview {
            errorMessage = "这条识别候选已失效或不属于当前用药主体。"
            return
        }
        let event = newClientEventID()
        let request = MedicationPlanConfirmRequest(
            subject_user_id: subject,
            client_request_id: event,
            client_event_id: event,
            candidate_id: candidate?.candidate_id,
            candidate_version: candidate?.version,
            generic_name: draft.genericName.trimmed,
            brand_name: draft.brandName.trimmedNil,
            strength: draft.strength.trimmedNil,
            dose_text: draft.doseText.trimmedNil,
            dose_quantity: draft.doseQuantity.trimmedDouble,
            frequency: draft.frequency.trimmedNil,
            schedule_times: draft.scheduleTimes,
            meal_relation: draft.mealRelation,
            instructions: draft.instructions.trimmedNil,
            course_start: draft.courseStart.trimmedNil,
            course_end: draft.courseEnd.trimmedNil,
            prescriber: draft.prescriber.trimmedNil,
            initial_quantity: draft.initialQuantity.trimmedDouble,
            inventory_unit: draft.inventoryUnit.trimmedNil,
            is_long_term: draft.isLongTerm,
            source_type: candidate?.source_type ?? sourceType,
            source_ref: candidate?.source_ref ?? sourceRef ?? "manual-entry:\(event)"
        )
        await start(.confirm(request, scope))
    }

    func revisePlan(_ plan: TrustedMedicationPlan, draft: MedicationPlanDraft) async {
        guard plan.subject_user_id == activeSubjectUserID, draft.isValid,
              let scope = mutationScope() else {
            errorMessage = draft.validationIssue ?? "计划已变化，请刷新后重试。"
            return
        }
        let request = MedicationPlanReviseRequest(
            subject_user_id: plan.subject_user_id,
            client_event_id: newClientEventID(),
            expected_version: plan.version,
            generic_name: draft.genericName.trimmed,
            brand_name: draft.brandName.trimmedNil,
            strength: draft.strength.trimmedNil,
            dose_text: draft.doseText.trimmedNil,
            dose_quantity: draft.doseQuantity.trimmedDouble,
            frequency: draft.frequency.trimmedNil,
            schedule_times: draft.scheduleTimes,
            meal_relation: draft.mealRelation,
            instructions: draft.instructions.trimmedNil,
            course_start: draft.courseStart.trimmedNil,
            course_end: draft.courseEnd.trimmedNil,
            prescriber: draft.prescriber.trimmedNil,
            initial_quantity: draft.initialQuantity.trimmedDouble,
            inventory_unit: draft.inventoryUnit.trimmedNil,
            is_long_term: draft.isLongTerm,
            source_type: plan.source_type,
            source_ref: plan.source_ref
        )
        await start(.revise(plan.plan_id, request, scope))
    }

    func updatePlanStatus(
        _ plan: TrustedMedicationPlan,
        action: MedicationPlanStatusRequest.Action,
        reason: String? = nil
    ) async {
        guard plan.subject_user_id == activeSubjectUserID, let scope = mutationScope() else { return }
        let request = MedicationPlanStatusRequest(
            subject_user_id: plan.subject_user_id,
            client_event_id: newClientEventID(),
            expected_version: plan.version,
            action: action,
            reason: reason?.trimmedNil
        )
        await start(.status(plan.plan_id, request, scope))
    }

    func rejectPrefill(_ candidate: MedicationPrefillCandidate) async {
        guard candidate.subject_user_id == activeSubjectUserID, candidate.isPendingReview,
              let scope = mutationScope() else { return }
        let request = MedicationPrefillRejectRequest(
            subject_user_id: candidate.subject_user_id,
            client_event_id: newClientEventID(),
            expected_version: candidate.version
        )
        await start(.reject(candidate.candidate_id, request, scope))
    }

    func confirmTaken(_ task: MedicationTodayTask, quantity: Double? = nil) async {
        await recordDose(task, action: .taken, takenQuantity: quantity)
    }

    func snooze(_ task: MedicationTodayTask, until: Date) async {
        guard until > now() else {
            errorMessage = "稍后提醒时间必须晚于当前时间。"
            return
        }
        await recordDose(task, action: .snooze, snoozedUntil: Self.isoString(until))
    }

    func skip(_ task: MedicationTodayTask, reason: String?) async {
        await recordDose(task, action: .skip, reason: reason)
    }

    func correct(
        _ task: MedicationTodayTask,
        to correctedStatus: MedicationDoseActionRequest.CorrectedStatus,
        snoozedUntil: Date? = nil,
        reason: String?
    ) async {
        guard let latestEventID = task.latest_event_id else {
            errorMessage = "这次服药还没有可纠正的用户确认记录。"
            return
        }
        let snoozeValue = correctedStatus == .snoozed ? snoozedUntil.map(Self.isoString) : nil
        if correctedStatus == .snoozed, snoozeValue == nil {
            errorMessage = "请设置新的稍后提醒时间。"
            return
        }
        await recordDose(
            task,
            action: .correct,
            correctedStatus: correctedStatus,
            correctionOfEventID: latestEventID,
            snoozedUntil: snoozeValue,
            reason: reason
        )
    }

    func createReaction(_ fields: MedicationReactionFields) async {
        guard plans.contains(where: { $0.plan_id == fields.plan_id && $0.status == .active }),
              let subject = activeSubjectUserID, let scope = mutationScope() else {
            errorMessage = "只能为当前已确认且服用中的计划记录不适。"
            return
        }
        let event = newClientEventID()
        let request = MedicationReactionCreateRequest(
            subject_user_id: subject,
            client_event_id: event,
            reaction_key: "reaction-\(event)",
            plan_id: fields.plan_id,
            symptoms: fields.symptoms.trimmed,
            onset_at: fields.onset_at,
            severity: fields.severity,
            duration_minutes: fields.duration_minutes,
            related_occurrence_key: fields.related_occurrence_key,
            notes: fields.notes?.trimmedNil
        )
        guard !request.symptoms.isEmpty else {
            errorMessage = "请填写不适症状。"
            return
        }
        await start(.createReaction(request, scope))
    }

    func correctReaction(_ reaction: MedicationReaction, fields: MedicationReactionFields) async {
        guard let subject = activeSubjectUserID, let scope = mutationScope() else { return }
        let request = MedicationReactionCorrectRequest(
            subject_user_id: subject,
            client_event_id: newClientEventID(),
            expected_version: reaction.reaction_version,
            plan_id: fields.plan_id,
            symptoms: fields.symptoms.trimmed,
            onset_at: fields.onset_at,
            severity: fields.severity,
            duration_minutes: fields.duration_minutes,
            related_occurrence_key: fields.related_occurrence_key,
            notes: fields.notes?.trimmedNil
        )
        guard !request.symptoms.isEmpty else {
            errorMessage = "请填写不适症状。"
            return
        }
        await start(.correctReaction(reaction.reaction_key, request, scope))
    }

    func retractReaction(_ reaction: MedicationReaction) async {
        guard let subject = activeSubjectUserID, let scope = mutationScope() else { return }
        let request = MedicationReactionRetractRequest(
            subject_user_id: subject,
            client_event_id: newClientEventID(),
            expected_version: reaction.reaction_version
        )
        await start(.retractReaction(reaction.reaction_key, request, scope))
    }

    func retryPendingMutation() async {
        guard let pendingMutation, !mutating else { return }
        await perform(pendingMutation)
    }

    func discardPendingRetry() {
        guard !mutating else { return }
        pendingMutation = nil
        errorMessage = nil
    }

    private func recordDose(
        _ task: MedicationTodayTask,
        action: MedicationDoseActionRequest.Action,
        correctedStatus: MedicationDoseActionRequest.CorrectedStatus? = nil,
        correctionOfEventID: Int? = nil,
        snoozedUntil: String? = nil,
        takenQuantity: Double? = nil,
        reason: String? = nil
    ) async {
        guard today?.tasks.contains(where: { $0.occurrence_key == task.occurrence_key }) == true,
              let subject = activeSubjectUserID, let scope = mutationScope() else { return }
        if task.status == .possiblyMissed,
           !task.possibly_missed_is_not_confirmation || task.status_assertion != "schedule_derived" {
            errorMessage = MedicationClientContractError.invalidTrustedResponse(
                "可能漏服被错误标成确认事实"
            ).localizedDescription
            return
        }
        let request = MedicationDoseActionRequest(
            subject_user_id: subject,
            plan_id: task.plan_id,
            expected_plan_version: task.plan_version,
            client_event_id: newClientEventID(),
            scheduled_local_date: task.scheduled_local_date,
            scheduled_time: task.scheduled_time,
            expected_occurrence_version: task.occurrence_version,
            action: action,
            corrected_status: correctedStatus,
            correction_of_event_id: correctionOfEventID,
            snoozed_until: snoozedUntil,
            taken_quantity: takenQuantity,
            reason: reason?.trimmedNil
        )
        await start(.dose(request, scope))
    }

    private func start(_ mutation: PendingMutation) async {
        guard pendingMutation == nil, !mutating else {
            errorMessage = "上一项用药操作结果尚未确认，请先使用同一请求重试。"
            return
        }
        pendingMutation = mutation
        await perform(mutation)
    }

    private func perform(_ mutation: PendingMutation) async {
        guard validate(mutation) else { return }
        mutating = true
        errorMessage = nil
        defer { mutating = false }
        do {
            switch mutation {
            case .recognize(let request, let scope):
                let result = try await repository.recognize(request, expectedAccountScope: scope)
                guard result.client_event_id == request.client_event_id,
                      result.isUnconfirmedPrefill else {
                    throw MedicationClientContractError.invalidTrustedResponse(
                        "OCR 结果没有保持未确认候选状态"
                    )
                }
                infoMessage = "识别结果已进入待确认区；确认前不会创建计划或进入 AI。"
            case .confirm(let request, let scope):
                let result = try await repository.confirmPlan(request, expectedAccountScope: scope)
                try Self.validate(plan: result, subject: request.subject_user_id)
                infoMessage = "用药计划已由你确认；提醒默认关闭并由本机管理。"
            case .revise(let planID, let request, let scope):
                let result = try await repository.revisePlan(
                    planID: planID,
                    request: request,
                    expectedAccountScope: scope
                )
                try Self.validate(plan: result, subject: request.subject_user_id)
                infoMessage = "计划修改已保存并保留版本记录。"
            case .status(let planID, let request, let scope):
                let result = try await repository.updatePlanStatus(
                    planID: planID,
                    request: request,
                    expectedAccountScope: scope
                )
                try Self.validate(plan: result, subject: request.subject_user_id)
                infoMessage = "计划状态已更新。"
            case .reject(let candidateID, let request, let scope):
                let result = try await repository.rejectPrefill(
                    candidateID: candidateID,
                    request: request,
                    expectedAccountScope: scope
                )
                guard result.subject_user_id == request.subject_user_id,
                      result.review_status == "rejected", !result.plan_created else {
                    throw MedicationClientContractError.invalidTrustedResponse("候选拒绝状态异常")
                }
                infoMessage = "识别候选已拒绝，没有创建用药计划。"
            case .dose(let request, let scope):
                let result = try await repository.recordDose(request, expectedAccountScope: scope)
                guard result.trust_state == "user_confirmed" else {
                    throw MedicationClientContractError.invalidTrustedResponse("剂次结果缺少用户确认")
                }
                var snoozeScheduled: Bool?
                if let task = today?.tasks.first(where: { $0.occurrence_key == result.occurrence_key }),
                   let plan = plans.first(where: { $0.plan_id == task.plan_id }) {
                    if result.effective_status == "snoozed",
                       let raw = result.snoozed_until,
                       let date = Self.isoDate(raw), date > now() {
                        snoozeScheduled = await reminderCoordinator.scheduleSnooze(
                            eventID: result.event_id,
                            task: task,
                            plan: plan,
                            settings: reminderSettingsByPlanID[plan.plan_id],
                            at: date
                        )
                    } else {
                        // Taken, skipped and every non-snoozed correction resolve
                        // the occurrence and must cancel its previous snooze.
                        await reminderCoordinator.cancelSnooze(task: task, plan: plan)
                        if result.effective_status == "snoozed" { snoozeScheduled = false }
                    }
                }
                if snoozeScheduled == false {
                    reminderPermission = await reminderCoordinator.permissionState()
                    infoMessage = "稍后状态已按你的选择保存，但本机通知没有安排；请在提醒设置中恢复通知权限。"
                } else {
                    infoMessage = result.effective_status == "taken"
                        ? "本次服药已按你的确认记录。"
                        : "本次用药状态已按你的选择记录。"
                }
            case .createReaction(let request, let scope):
                let result = try await repository.createReaction(request, expectedAccountScope: scope)
                try Self.validate(reaction: result, subjectPlanIDs: Set(plans.map(\.plan_id)))
                infoMessage = result.safety_guidance
            case .correctReaction(let key, let request, let scope):
                let result = try await repository.correctReaction(
                    reactionKey: key,
                    request: request,
                    expectedAccountScope: scope
                )
                try Self.validate(reaction: result, subjectPlanIDs: Set(plans.map(\.plan_id)))
                infoMessage = "不适记录已修正；仍只表示时间关联。"
            case .retractReaction(let key, let request, let scope):
                let result = try await repository.retractReaction(
                    reactionKey: key,
                    request: request,
                    expectedAccountScope: scope
                )
                guard result.status == "retracted" else {
                    throw MedicationClientContractError.invalidTrustedResponse("不适记录撤回状态异常")
                }
                infoMessage = "不适记录已撤回并保留修订轨迹。"
            }
            pendingMutation = nil
            await refresh(generation: loadGeneration, bootstrapSubject: false)
        } catch {
            guard validate(mutation) else { return }
            errorMessage = "\(error.localizedDescription) 你可以使用同一请求重试，避免重复记录。"
        }
    }

    private func refresh(generation: UUID, bootstrapSubject: Bool) async {
        guard let scope = activeAccountScope, validateAccount(scope) else { return }
        do {
            let subjectForRequest = bootstrapSubject ? nil : activeSubjectUserID
            let summary = try await repository.fetchToday(
                subjectUserID: subjectForRequest,
                localDate: localDate(),
                timezoneOffsetMinutes: timezoneOffsetMinutes()
            )
            guard generation == loadGeneration, validateAccount(scope), summary.subject_user_id > 0 else { return }
            try Self.validate(today: summary)
            if let activeSubjectUserID, activeSubjectUserID != summary.subject_user_id {
                throw MedicationClientContractError.subjectMismatch
            }
            let subject = summary.subject_user_id
            activeSubjectUserID = subject

            async let plansResponse = repository.fetchPlans(subjectUserID: subject)
            async let candidatesResponse = repository.fetchPrefillCandidates(subjectUserID: subject)
            async let reactionsResponse = repository.fetchReactions(subjectUserID: subject)
            let fetchedPlans = try await plansResponse
            let fetchedCandidates = try await candidatesResponse
            let fetchedReactions = try await reactionsResponse
            guard generation == loadGeneration, validateAccount(scope) else { return }
            guard fetchedPlans.subject_user_id == subject,
                  fetchedCandidates.subject_user_id == subject,
                  fetchedReactions.subject_user_id == subject,
                  fetchedPlans.items.allSatisfy({ $0.subject_user_id == subject }),
                  fetchedCandidates.items.allSatisfy({ $0.subject_user_id == subject }) else {
                throw MedicationClientContractError.subjectMismatch
            }
            try fetchedPlans.items.forEach { try Self.validate(plan: $0, subject: subject) }
            try fetchedCandidates.items.forEach(Self.validate(candidate:))
            let planIDs = Set(fetchedPlans.items.map(\.plan_id))
            try fetchedReactions.items.forEach { try Self.validate(reaction: $0, subjectPlanIDs: planIDs) }

            today = summary
            plans = fetchedPlans.items
            prefillCandidates = fetchedCandidates.items
            reactions = fetchedReactions.items.filter { $0.status == "active" }
            // Today and confirmed plans are the primary path. Historical
            // insights begin in an explicit unavailable state and load
            // independently so six extra RTTs never hold the main screen.
            confirmationInsights = makeConfirmationInsights(
                current: summary,
                recentSummaries: nil,
                plans: fetchedPlans.items
            )
            scheduleConfirmationInsights(
                current: summary,
                subjectUserID: subject,
                plans: fetchedPlans.items,
                generation: generation,
                accountScope: scope
            )
            legacyRecords = (try? await repository.fetchLegacyReadOnly()) ?? []
            await restoreAndReconcileReminders(
                accountScope: scope,
                subjectUserID: subject,
                plans: fetchedPlans.items
            )
            if generation == loadGeneration, validateAccount(scope), errorMessage?.contains("同一请求重试") != true {
                errorMessage = nil
            }
        } catch {
            guard generation == loadGeneration, validateAccount(scope) else { return }
            errorMessage = error.localizedDescription
        }
    }

    private func fetchRecentSummaries(
        subjectUserID: Int,
        current: MedicationTodaySummary
    ) async -> [MedicationTodaySummary]? {
        let dates = MedicationDateWindow.recentDates(ending: current.local_date, count: 7)
        guard dates.count == 7 else { return nil }
        let historicalDates = dates.filter { $0 != current.local_date }
        let repository = repository
        let offset = timezoneOffsetMinutes()
        let fetchedByDate = await withTaskGroup(
            of: (String, MedicationTodaySummary?).self,
            returning: [String: MedicationTodaySummary?].self
        ) { group in
            for date in historicalDates {
                group.addTask {
                    do {
                        let summary = try await repository.fetchToday(
                            subjectUserID: subjectUserID,
                            localDate: date,
                            timezoneOffsetMinutes: offset
                        )
                        return (date, summary)
                    } catch {
                        return (date, nil)
                    }
                }
            }
            var values: [String: MedicationTodaySummary?] = [:]
            for await (date, summary) in group {
                values[date] = summary
            }
            return values
        }
        guard !Task.isCancelled else { return nil }
        var summaries: [MedicationTodaySummary] = []
        for date in dates {
            if date == current.local_date {
                summaries.append(current)
                continue
            }
            guard let wrapped = fetchedByDate[date], let summary = wrapped,
                  summary.subject_user_id == subjectUserID,
                  summary.local_date == date else { return nil }
            do { try Self.validate(today: summary) } catch { return nil }
            summaries.append(summary)
        }
        return summaries
    }

    private func scheduleConfirmationInsights(
        current: MedicationTodaySummary,
        subjectUserID: Int,
        plans: [TrustedMedicationPlan],
        generation: UUID,
        accountScope: String
    ) {
        confirmationTask?.cancel()
        confirmationTask = Task { [weak self] in
            guard let self else { return }
            let recent = await self.fetchRecentSummaries(
                subjectUserID: subjectUserID,
                current: current
            )
            guard !Task.isCancelled,
                  generation == self.loadGeneration,
                  self.activeSubjectUserID == subjectUserID,
                  self.validateAccount(accountScope) else { return }
            self.confirmationInsights = self.makeConfirmationInsights(
                current: current,
                recentSummaries: recent,
                plans: plans
            )
        }
    }

    private func makeConfirmationInsights(
        current: MedicationTodaySummary,
        recentSummaries: [MedicationTodaySummary]?,
        plans: [TrustedMedicationPlan]
    ) -> MedicationConfirmationInsights {
        let todayMetric = MedicationConfirmationPolicy.metric(summaries: [current])
        guard let recentSummaries else {
            return MedicationConfirmationInsights(
                today: todayMetric,
                sevenDay: .unavailable("近七日数据没有完整返回，本页不会用局部数据计算已确认率。"),
                courseByPlanID: Dictionary(uniqueKeysWithValues: plans.map {
                    ($0.plan_id, .unavailable("服务端尚未提供这项计划的完整疗程历史。"))
                })
            )
        }
        let expectedDates = MedicationDateWindow.recentDates(ending: current.local_date, count: 7)
        let course = Dictionary(uniqueKeysWithValues: plans.map { plan in
            (
                plan.plan_id,
                MedicationConfirmationPolicy.course(
                    plan: plan,
                    summaries: recentSummaries,
                    through: current.local_date
                )
            )
        })
        return MedicationConfirmationInsights(
            today: todayMetric,
            sevenDay: MedicationConfirmationPolicy.sevenDay(
                summaries: recentSummaries,
                expectedLocalDates: expectedDates
            ),
            courseByPlanID: course
        )
    }

    private func restoreAndReconcileReminders(
        accountScope: String,
        subjectUserID: Int,
        plans: [TrustedMedicationPlan]
    ) async {
        guard validateAccount(accountScope) else { return }
        let timezone = currentTimezone()
        let planByID = Dictionary(uniqueKeysWithValues: plans.map { ($0.plan_id, $0) })
        var changed = false
        let stored = reminderStore.load(
            accountScope: accountScope,
            subjectUserID: subjectUserID
        ).reduce(into: [Int: MedicationReminderSettings]()) { result, setting in
            guard let plan = planByID[setting.planID],
                  setting.subjectUserID == subjectUserID else { return }
            var setting = setting
            if setting.planVersion != plan.version || plan.status != .active {
                if setting.enabled { changed = true }
                setting.enabled = false
            }
            if setting.timezoneIdentifier != timezone.identifier {
                setting.timezoneIdentifier = timezone.identifier
                setting.updatedAt = Self.isoString(now())
                changed = true
            }
            setting.mealRelation = plan.meal_relation
            setting.courseEnd = plan.course_end
            result[setting.planID] = setting
        }
        if changed {
            do {
                try reminderStore.save(
                    Array(stored.values),
                    accountScope: accountScope,
                    subjectUserID: subjectUserID
                )
            } catch {
                infoMessage = "计划或时区已变化，本次已停止旧提醒，但新设置尚未持久化：\(error.localizedDescription)"
            }
        }
        guard validateAccount(accountScope) else { return }
        reminderSettingsByPlanID = stored
        _ = await reconcileReminders(scope: accountScope)
    }

    private func reconcileReminders(scope: String) async -> MedicationReminderReconcileResult {
        guard validateAccount(scope) else {
            return MedicationReminderReconcileResult(
                permission: .unavailable,
                scheduledCount: 0,
                detail: MedicationClientContractError.accountChanged.localizedDescription
            )
        }
        let result = await reminderCoordinator.reconcile(
            settings: Array(reminderSettingsByPlanID.values),
            plans: plans,
            now: now(),
            timezone: currentTimezone()
        )
        guard validateAccount(scope) else {
            return MedicationReminderReconcileResult(
                permission: .unavailable,
                scheduledCount: 0,
                detail: MedicationClientContractError.accountChanged.localizedDescription
            )
        }
        reminderPermission = result.permission
        return result
    }

    private func reset(for accountScope: String?) {
        confirmationTask?.cancel()
        confirmationTask = nil
        activeAccountScope = accountScope
        activeSubjectUserID = nil
        today = nil
        plans = []
        prefillCandidates = []
        reactions = []
        legacyRecords = []
        reminderSettingsByPlanID = [:]
        reminderPermission = .unknown
        confirmationInsights = .unavailable
        pendingMutation = nil
        errorMessage = nil
        infoMessage = nil
    }

    private func mutationScope() -> String? {
        guard let activeAccountScope, validateAccount(activeAccountScope) else {
            errorMessage = MedicationClientContractError.accountChanged.localizedDescription
            return nil
        }
        return activeAccountScope
    }

    private func validate(_ mutation: PendingMutation) -> Bool {
        guard activeSubjectUserID == mutation.subjectUserID,
              activeAccountScope == mutation.accountScope,
              currentAccountScope() == mutation.accountScope else {
            pendingMutation = nil
            errorMessage = MedicationClientContractError.accountChanged.localizedDescription
            return false
        }
        return true
    }

    private func validateAccount(_ scope: String) -> Bool {
        activeAccountScope == scope && currentAccountScope() == scope
    }

    private func newClientEventID() -> String {
        Self.boundedClientEventID(
            makeClientEventID(),
            fallback: UUID().uuidString.lowercased()
        )
    }

    nonisolated static func boundedClientEventID(
        _ candidate: String,
        fallback: String
    ) -> String {
        let candidate = candidate.trimmingCharacters(in: .whitespacesAndNewlines)
        let fallback = fallback.trimmingCharacters(in: .whitespacesAndNewlines)
        let resolved = candidate.isEmpty ? fallback : candidate
        // Production supplies a UUID fallback. The final literal keeps this
        // helper total and testable even if a future injected fallback is empty.
        // Pydantic applies max_length to Unicode code points, so bound scalars
        // instead of Swift grapheme clusters (one emoji may contain many scalars).
        return String((resolved.isEmpty ? "client-event" : resolved).unicodeScalars.prefix(80))
    }

    private static func validate(today: MedicationTodaySummary) throws {
        guard today.missed_assertion_policy == "elapsed_time_never_confirms_missed" else {
            throw MedicationClientContractError.invalidTrustedResponse("漏服断言策略异常")
        }
        for task in today.tasks where task.status == .possiblyMissed {
            guard task.possibly_missed_is_not_confirmation,
                  task.status_assertion == "schedule_derived",
                  task.confirmed_at == nil else {
                throw MedicationClientContractError.invalidTrustedResponse(
                    "可能漏服只能是待确认的时间推导状态"
                )
            }
        }
    }

    private static func validate(plan: TrustedMedicationPlan, subject: Int) throws {
        guard plan.subject_user_id == subject,
              plan.trust_state == "user_confirmed",
              plan.reminder_management == "client_managed",
              !plan.reminder_default_enabled,
              !plan.server_notification_scheduled,
              MedicationTrustPolicy.isServerInventoryEstimate(plan.inventory) else {
            throw MedicationClientContractError.invalidTrustedResponse(
                "计划确认、提醒或预计余量边界异常"
            )
        }
    }

    private static func validate(candidate: MedicationPrefillCandidate) throws {
        if candidate.review_status == "pending_review" {
            guard candidate.isPendingReview else {
                throw MedicationClientContractError.invalidTrustedResponse(
                    "待确认候选被错误标为已建计划"
                )
            }
        }
    }

    private static func validate(
        reaction: MedicationReaction,
        subjectPlanIDs: Set<Int>
    ) throws {
        guard subjectPlanIDs.contains(reaction.plan_id),
              reaction.causal_attribution == "temporal_association_only",
              reaction.user_facing_causality.contains("不能据此认定由药物导致") else {
            throw MedicationClientContractError.invalidTrustedResponse(
                "不适记录缺少时间关联非因果边界"
            )
        }
    }

    nonisolated static func isoString(_ date: Date) -> String {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter.string(from: date)
    }

    nonisolated static func isoDate(_ value: String) -> Date? {
        let fractional = ISO8601DateFormatter()
        fractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = fractional.date(from: value) { return date }
        return ISO8601DateFormatter().date(from: value)
    }
}

private extension String {
    var trimmed: String { trimmingCharacters(in: .whitespacesAndNewlines) }
    var trimmedNil: String? {
        let value = trimmed
        return value.isEmpty ? nil : value
    }
    var trimmedDouble: Double? {
        guard let value = trimmedNil else { return nil }
        guard let number = Double(value), number.isFinite else { return nil }
        return number
    }
}
