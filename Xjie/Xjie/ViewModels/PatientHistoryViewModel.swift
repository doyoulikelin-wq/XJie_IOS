import Foundation

struct HealthProfileEditorDraft: Equatable {
    let definition: HealthProfileFieldDefinition
    let originalState: HealthProfileResponseState
    let originalValue: String
    var responseState: HealthProfileResponseState
    var value: String

    var isDirty: Bool {
        responseState != originalState
            || value.trimmingCharacters(in: .whitespacesAndNewlines)
                != originalValue.trimmingCharacters(in: .whitespacesAndNewlines)
    }
}

struct HealthProfileGoalEditorDraft: Equatable {
    let goalID: Int?
    let expectedVersion: Int?
    let originalName: String
    let originalStartedOn: String
    let originalMetricsText: String
    var name: String
    var startedOn: String
    var metricsText: String

    init(goal: HealthProfileGoal? = nil) {
        goalID = goal?.goal_id
        expectedVersion = goal?.version
        originalName = goal?.name ?? ""
        originalStartedOn = goal?.started_on ?? ""
        originalMetricsText = goal?.metrics.map(\.title).joined(separator: "、") ?? ""
        name = originalName
        startedOn = originalStartedOn
        metricsText = originalMetricsText
    }

    var isCreating: Bool { goalID == nil }
    var isDirty: Bool {
        isCreating
            ? !name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                || !startedOn.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                || !metricsText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            : name.trimmingCharacters(in: .whitespacesAndNewlines)
                != originalName.trimmingCharacters(in: .whitespacesAndNewlines)
                || startedOn.trimmingCharacters(in: .whitespacesAndNewlines)
                    != originalStartedOn.trimmingCharacters(in: .whitespacesAndNewlines)
                || metricsText.trimmingCharacters(in: .whitespacesAndNewlines)
                    != originalMetricsText.trimmingCharacters(in: .whitespacesAndNewlines)
    }
}

@MainActor
final class PatientHistoryViewModel: ObservableObject {
    @Published private(set) var profile: HealthProfileTrustResponse?
    @Published private(set) var longTermMedications: [HealthProfileLongTermMedicationSummaryItem] = []
    @Published private(set) var medicationSummaryLoading = false
    @Published private(set) var medicationSummaryError: String?
    @Published private(set) var loading = false
    @Published private(set) var mutating = false
    @Published private(set) var editor: HealthProfileEditorDraft?
    @Published private(set) var goalEditor: HealthProfileGoalEditorDraft?
    @Published private(set) var historyTarget: HealthProfileHistoryTarget?
    @Published private(set) var revisionHistory: HealthProfileRevisionList?
    @Published private(set) var historyLoading = false
    @Published private(set) var historyError: String?
    @Published var errorMessage: String?
    @Published var infoMessage: String?

    private enum PendingMutation: Equatable {
        case candidate(Int, HealthProfileCandidateReviewRequest, String)
        case upsert(HealthProfileFactUpsertRequest, String)
        case retract(Int, HealthProfileFactRetractRequest, String)
        case createGoal(HealthProfileGoalCreateRequest, String)
        case updateGoal(Int, HealthProfileGoalUpdateRequest, String)
        case goalStatus(Int, HealthProfileGoalStatusRequest, String)

        var clientEventID: String {
            switch self {
            case .candidate(_, let request, _): return request.client_event_id
            case .upsert(let request, _): return request.client_event_id
            case .retract(_, let request, _): return request.client_event_id
            case .createGoal(let request, _): return request.client_event_id
            case .updateGoal(_, let request, _): return request.client_event_id
            case .goalStatus(_, let request, _): return request.client_event_id
            }
        }
    }

    private let repository: PatientHistoryRepositoryProtocol
    private let currentAccountScope: @MainActor () -> String?
    private let makeClientEventID: () -> String
    private var activeAccountScope: String?
    private var loadGeneration = UUID()
    private var pendingMutation: PendingMutation?

    init(
        repository: PatientHistoryRepositoryProtocol = PatientHistoryRepository(),
        currentAccountScope: @escaping @MainActor () -> String? = { AuthManager.shared.accountScope },
        makeClientEventID: @escaping () -> String = { UUID().uuidString.lowercased() }
    ) {
        self.repository = repository
        self.currentAccountScope = currentAccountScope
        self.makeClientEventID = makeClientEventID
    }

    var hasPendingRetry: Bool { pendingMutation != nil && !mutating }
    var pendingClientEventID: String? { pendingMutation?.clientEventID }
    var hasUnsavedEditorChanges: Bool {
        editor?.isDirty == true || goalEditor?.isDirty == true
    }

    var factsByCategory: [(HealthProfileCategory, [HealthProfileFact])] {
        guard let profile else { return [] }
        return HealthProfileCategory.allCases.compactMap { category in
            let facts = profile.facts.filter { $0.typedCategory == category }
            return facts.isEmpty ? nil : (category, facts)
        }
    }

    #if DEBUG
    /// Canvas-only deterministic state. Preview hosts opt in explicitly, so a
    /// normal Debug run still follows the real account and network boundaries.
    func loadPreviewFixture() {
        loadGeneration = UUID()
        activeAccountScope = nil
        loading = false
        mutating = false
        editor = nil
        goalEditor = nil
        historyTarget = nil
        revisionHistory = nil
        pendingMutation = nil
        errorMessage = nil
        infoMessage = nil
        medicationSummaryError = nil
        medicationSummaryLoading = false
        profile = Self.previewProfile
        longTermMedications = [
            HealthProfileLongTermMedicationSummaryItem(
                medication_name: "二甲双胍",
                purpose: "血糖管理",
                started_on: "2025-01-01",
                is_still_taking: true,
                source: "prescription",
                last_confirmed_at: "2026-07-20T08:00:00Z"
            ),
            HealthProfileLongTermMedicationSummaryItem(
                medication_name: "阿托伐他汀钙片",
                purpose: "血脂管理",
                started_on: "2026-03-10",
                is_still_taking: true,
                source: "manual",
                last_confirmed_at: "2026-07-19T08:00:00Z"
            )
        ]
    }

    static let previewProfile = HealthProfileTrustResponse(
        subject_user_id: 1,
        profile_status: "needs_attention",
        overview: HealthProfileOverview(
            completeness_percent: 72,
            resolved_required_weight: 11,
            total_required_weight: 15,
            missing_required_fact_keys: ["safety.contraindication"],
            pending_update_count: 2,
            independent_source_count: 12,
            primary_action: HealthProfilePrimaryAction(
                kind: "review_updates",
                item_count: 2,
                localization_key: "health_profile.primary_action.review_updates",
                route: "profile_updates"
            )
        ),
        facts: [
            HealthProfileFact(
                fact_id: 201,
                fact_key: "basic.height",
                category: "basic",
                value_data: ["response_state": .string("value"), "value": .string("168 cm")],
                is_safety_critical: false,
                confirmation_method: "user",
                version: 1,
                confirmed_at: "2026-07-18T08:00:00Z",
                updated_at: "2026-07-18T08:00:00Z",
                sources: []
            ),
            HealthProfileFact(
                fact_id: 202,
                fact_key: "long_term_health.diagnoses",
                category: "long_term_health",
                value_data: ["response_state": .string("value"), "value": .string("2 型糖尿病")],
                is_safety_critical: false,
                confirmation_method: "user",
                version: 1,
                confirmed_at: "2026-07-18T08:00:00Z",
                updated_at: "2026-07-18T08:00:00Z",
                sources: []
            )
        ],
        candidates: [
            HealthProfileCandidate(
                candidate_id: 301,
                fact_key: "long_term_health.recent_findings",
                category: "long_term_health",
                proposed_value: ["value": .string("近期 3 份报告出现血脂异常")],
                is_safety_critical: false,
                review_status: "pending_review",
                conflict_with_fact_id: nil,
                confidence: 0.91,
                version: 1,
                created_at: "2026-07-20T08:00:00Z",
                updated_at: "2026-07-20T08:00:00Z",
                sources: []
            )
        ],
        goals: [
            HealthProfileGoal(
                goal_id: 701,
                name: "改善睡眠规律",
                status: .active,
                started_on: "2026-07-01",
                version: 1,
                confirmed_at: "2026-07-01T08:00:00Z",
                metrics: [.init(metric_key: "sleep_duration", display_label: "睡眠时长")]
            )
        ],
        management_plans: [
            HealthProfileManagementPlan(
                plan_id: 801,
                title: "七天稳糖计划",
                goal: "稳定餐后血糖",
                start_date: "2026-07-15",
                end_date: "2026-07-21",
                status: "active",
                created_by: "questionnaire",
                updated_at: "2026-07-20T08:00:00Z",
                task_count: 7,
                completed_task_count: 3
            )
        ]
    )
    #endif

    func load(accountScope: String?) async {
        loadGeneration = UUID()
        let generation = loadGeneration
        activeAccountScope = accountScope
        profile = nil
        longTermMedications = []
        medicationSummaryError = nil
        editor = nil
        goalEditor = nil
        historyTarget = nil
        revisionHistory = nil
        historyError = nil
        pendingMutation = nil
        errorMessage = nil

        guard let accountScope, currentAccountScope() == accountScope else {
            errorMessage = "无法确认当前登录账号，已停止读取健康画像。"
            return
        }
        loading = true
        defer {
            if loadGeneration == generation { loading = false }
        }
        do {
            let response = try await repository.fetchProfile()
            guard loadGeneration == generation,
                  validateAccount(accountScope),
                  response.subject_user_id > 0 else { return }
            profile = response
            medicationSummaryLoading = true
            defer {
                if loadGeneration == generation { medicationSummaryLoading = false }
            }
            do {
                let summary = try await repository.fetchLongTermMedicationSummary(
                    subjectUserID: response.subject_user_id
                )
                guard loadGeneration == generation,
                      validateAccount(accountScope),
                      summary.subject_user_id == response.subject_user_id else { return }
                longTermMedications = summary.items
            } catch {
                guard loadGeneration == generation, validateAccount(accountScope) else { return }
                medicationSummaryError = "长期用药摘要暂时无法读取：\(error.localizedDescription)"
            }
        } catch {
            guard loadGeneration == generation, validateAccount(accountScope) else { return }
            errorMessage = error.localizedDescription
        }
    }

    func beginEditing(_ definition: HealthProfileFieldDefinition) {
        guard !mutating, pendingMutation == nil, definition.category != .goal else {
            if definition.category == .goal {
                errorMessage = "健康目标必须通过多目标列表主动添加，不能写入单个画像事实。"
            }
            return
        }
        let fact = profile?.facts.first { $0.fact_key == definition.key }
        let state = fact?.responseState ?? .value
        let value: String
        if case .string(let raw)? = fact?.value_data["value"] {
            value = raw
        } else if state == .value, let fact {
            value = HealthProfileDisplayFormatter.value(fact.value_data)
        } else {
            value = ""
        }
        editor = HealthProfileEditorDraft(
            definition: definition,
            originalState: state,
            originalValue: value,
            responseState: state,
            value: value
        )
        goalEditor = nil
    }

    func updateEditorValue(_ value: String) {
        guard var editor else { return }
        editor.value = value
        if editor.definition.category == .longTermHealth,
           !value.isEmpty,
           editor.responseState != .value {
            editor.responseState = .value
        }
        self.editor = editor
    }

    func updateEditorState(_ state: HealthProfileResponseState) {
        guard var editor else { return }
        editor.responseState = state
        if state != .value { editor.value = "" }
        self.editor = editor
    }

    func cancelEditing() {
        guard !mutating else { return }
        editor = nil
    }

    func beginCreatingGoal() {
        guard !mutating, pendingMutation == nil else { return }
        editor = nil
        goalEditor = HealthProfileGoalEditorDraft()
    }

    func beginEditingGoal(_ goal: HealthProfileGoal) {
        guard !mutating, pendingMutation == nil, goal.status != .archived else { return }
        editor = nil
        goalEditor = HealthProfileGoalEditorDraft(goal: goal)
    }

    func updateGoalName(_ value: String) {
        guard var goalEditor else { return }
        goalEditor.name = value
        self.goalEditor = goalEditor
    }

    func updateGoalStartedOn(_ value: String) {
        guard var goalEditor else { return }
        goalEditor.startedOn = value
        self.goalEditor = goalEditor
    }

    func updateGoalMetricsText(_ value: String) {
        guard var goalEditor else { return }
        goalEditor.metricsText = value
        self.goalEditor = goalEditor
    }

    func cancelGoalEditing() {
        guard !mutating else { return }
        goalEditor = nil
    }

    func saveEditor(safetyConfirmed: Bool) async {
        guard let editor, editor.isDirty, let profile else { return }
        let definition = editor.definition
        if definition.isSafetyCritical && !safetyConfirmed {
            errorMessage = "安全信息必须由你再次确认后才能保存。"
            return
        }
        if definition.category == .goal {
            errorMessage = "健康目标必须通过多目标列表主动添加。"
            return
        }
        let trimmed = editor.value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard editor.responseState != .value || !trimmed.isEmpty else {
            errorMessage = "请填写内容，或选择“明确没有 / 不适用 / 暂不回答”。"
            return
        }
        guard let scope = mutationScope() else { return }
        let currentFact = profile.facts.first { $0.fact_key == definition.key }
        let confirmedValue: HealthReportJSONValue? = if editor.responseState != .value {
            nil
        } else {
            .string(trimmed)
        }
        let request = HealthProfileFactUpsertRequest(
            subject_user_id: profile.subject_user_id,
            client_event_id: newClientEventID(),
            fact_key: definition.key,
            category: definition.category,
            response_state: editor.responseState,
            value: confirmedValue,
            is_safety_critical: definition.isSafetyCritical,
            expected_version: currentFact?.version
        )
        await start(.upsert(request, scope))
    }

    func saveGoalEditor() async {
        guard let draft = goalEditor, draft.isDirty, let profile else { return }
        let name = draft.name.trimmingCharacters(in: .whitespacesAndNewlines)
        let startedOn = draft.startedOn.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty else {
            errorMessage = "请填写目标名称。"
            return
        }
        guard HealthProfileGoalInputParser.isValidDate(startedOn) else {
            errorMessage = "开始时间必须是有效日期（YYYY-MM-DD）。"
            return
        }
        guard let metrics = Self.goalMetricRequests(from: draft.metricsText), !metrics.isEmpty else {
            errorMessage = "请至少关联一个指标；可填写睡眠时长、HRV、体重、步数、血压、血糖或英文指标键。"
            return
        }
        guard let scope = mutationScope() else { return }
        if let goalID = draft.goalID, let expectedVersion = draft.expectedVersion {
            let request = HealthProfileGoalUpdateRequest(
                subject_user_id: profile.subject_user_id,
                client_event_id: newClientEventID(),
                expected_version: expectedVersion,
                name: name,
                started_on: startedOn,
                metrics: metrics
            )
            await start(.updateGoal(goalID, request, scope))
        } else {
            let request = HealthProfileGoalCreateRequest(
                subject_user_id: profile.subject_user_id,
                client_event_id: newClientEventID(),
                name: name,
                started_on: startedOn,
                metrics: metrics
            )
            await start(.createGoal(request, scope))
        }
    }

    func changeGoalStatus(_ goal: HealthProfileGoal, action: HealthProfileGoalAction) async {
        guard let profile,
              profile.goals.contains(where: { $0.goal_id == goal.goal_id && $0.version == goal.version }),
              Self.allows(action: action, from: goal.status),
              let scope = mutationScope() else {
            errorMessage = "目标状态已变化或当前操作不受支持，请刷新后重试。"
            return
        }
        let request = HealthProfileGoalStatusRequest(
            subject_user_id: profile.subject_user_id,
            client_event_id: newClientEventID(),
            expected_version: goal.version,
            action: action
        )
        await start(.goalStatus(goal.goal_id, request, scope))
    }

    func reviewCandidate(
        _ candidate: HealthProfileCandidate,
        action: HealthProfileCandidateAction,
        safetyConfirmed: Bool
    ) async {
        let actionIsAllowed = action == .accept
            ? candidate.isReviewable
            : candidate.canReview(.reject)
        guard let profile,
              actionIsAllowed,
              profile.candidates.contains(where: { $0.candidate_id == candidate.candidate_id }) else {
            errorMessage = "这项候选更新已失效或不允许在画像中确认。"
            return
        }
        if candidate.typedCategory == .goal {
            errorMessage = "AI 或报告不能自动创建健康目标。"
            return
        }
        if candidate.is_safety_critical && action == .accept && !safetyConfirmed {
            errorMessage = "安全候选必须由你再次确认后才能加入画像。"
            return
        }
        guard let scope = mutationScope() else { return }
        let request = HealthProfileCandidateReviewRequest(
            subject_user_id: profile.subject_user_id,
            client_event_id: newClientEventID(),
            candidate_version: candidate.version,
            action: action
        )
        await start(.candidate(candidate.candidate_id, request, scope))
    }

    func retract(_ fact: HealthProfileFact, confirmed: Bool) async {
        guard confirmed else {
            errorMessage = "删除画像事实前必须再次确认。"
            return
        }
        guard let profile,
              profile.facts.contains(where: { $0.fact_id == fact.fact_id }),
              let scope = mutationScope() else { return }
        let request = HealthProfileFactRetractRequest(
            subject_user_id: profile.subject_user_id,
            client_event_id: newClientEventID(),
            expected_version: fact.version
        )
        await start(.retract(fact.fact_id, request, scope))
    }

    func openHistory(_ target: HealthProfileHistoryTarget) async {
        guard let profile,
              (target.kind == .fact
                ? profile.facts.contains(where: { $0.fact_id == target.id })
                : profile.goals.contains(where: { $0.goal_id == target.id })),
              let scope = activeAccountScope,
              validateAccount(scope) else {
            errorMessage = "无法确认这项历史记录的主体，已停止读取。"
            return
        }
        historyTarget = target
        revisionHistory = nil
        historyError = nil
        await loadHistoryPage(afterRevisionID: nil, append: false)
    }

    func loadMoreHistory() async {
        guard let next = revisionHistory?.next_after_revision_id else { return }
        await loadHistoryPage(afterRevisionID: next, append: true)
    }

    func closeHistory() {
        historyTarget = nil
        revisionHistory = nil
        historyError = nil
    }

    private func loadHistoryPage(afterRevisionID: Int?, append: Bool) async {
        guard !historyLoading,
              let target = historyTarget,
              let subject = profile?.subject_user_id,
              let scope = activeAccountScope,
              validateAccount(scope) else { return }
        historyLoading = true
        defer { historyLoading = false }
        do {
            let response: HealthProfileRevisionList
            switch target.kind {
            case .fact:
                response = try await repository.fetchFactRevisions(
                    factID: target.id,
                    subjectUserID: subject,
                    afterRevisionID: afterRevisionID
                )
            case .goal:
                response = try await repository.fetchGoalRevisions(
                    goalID: target.id,
                    subjectUserID: subject,
                    afterRevisionID: afterRevisionID
                )
            }
            guard validateAccount(scope),
                  response.subject_user_id == subject,
                  response.target_kind == target.kind,
                  response.target_id == target.id else {
                historyError = "历史记录主体或目标不匹配，已拒绝显示。"
                return
            }
            if append, let current = revisionHistory {
                let knownIDs = Set(current.items.map(\.revision_id))
                revisionHistory = HealthProfileRevisionList(
                    subject_user_id: response.subject_user_id,
                    target_kind: response.target_kind,
                    target_id: response.target_id,
                    items: current.items + response.items.filter { !knownIDs.contains($0.revision_id) },
                    next_after_revision_id: response.next_after_revision_id
                )
            } else {
                revisionHistory = response
            }
        } catch {
            guard validateAccount(scope) else { return }
            historyError = "历史记录读取失败：\(error.localizedDescription)"
        }
    }

    func retryPendingMutation() async {
        guard let pendingMutation, !mutating else { return }
        await perform(pendingMutation)
    }

    private func start(_ mutation: PendingMutation) async {
        guard pendingMutation == nil, !mutating else {
            errorMessage = "上一项修改结果尚未确认，请使用同一请求重试。"
            return
        }
        pendingMutation = mutation
        await perform(mutation)
    }

    private func perform(_ mutation: PendingMutation) async {
        guard let subject = profile?.subject_user_id else { return }
        mutating = true
        errorMessage = nil
        defer { mutating = false }
        do {
            let response: HealthProfileTrustResponse
            switch mutation {
            case .candidate(let candidateID, let request, let scope):
                guard validateMutation(subject: subject, scope: scope) else { return }
                response = try await repository.reviewCandidate(
                    candidateID: candidateID,
                    request: request,
                    expectedAccountScope: scope
                )
            case .upsert(let request, let scope):
                guard validateMutation(subject: subject, scope: scope) else { return }
                response = try await repository.upsertFact(request, expectedAccountScope: scope)
            case .retract(let factID, let request, let scope):
                guard validateMutation(subject: subject, scope: scope) else { return }
                response = try await repository.retractFact(
                    factID: factID,
                    request: request,
                    expectedAccountScope: scope
                )
            case .createGoal(let request, let scope):
                guard validateMutation(subject: subject, scope: scope) else { return }
                response = try await repository.createGoal(
                    request,
                    expectedAccountScope: scope
                )
            case .updateGoal(let goalID, let request, let scope):
                guard validateMutation(subject: subject, scope: scope) else { return }
                response = try await repository.updateGoal(
                    goalID: goalID,
                    request: request,
                    expectedAccountScope: scope
                )
            case .goalStatus(let goalID, let request, let scope):
                guard validateMutation(subject: subject, scope: scope) else { return }
                response = try await repository.updateGoalStatus(
                    goalID: goalID,
                    request: request,
                    expectedAccountScope: scope
                )
            }
            guard let scope = activeAccountScope,
                  validateAccount(scope),
                  response.subject_user_id == subject else {
                errorMessage = "画像主体或登录账号已变化，已拒绝显示这次响应。"
                return
            }
            profile = response
            pendingMutation = nil
            editor = nil
            goalEditor = nil
            infoMessage = "健康画像已更新"
        } catch {
            guard let scope = activeAccountScope, validateAccount(scope) else { return }
            errorMessage = "\(error.localizedDescription) 可使用同一请求重试，避免重复写入。"
        }
    }

    private func mutationScope() -> String? {
        guard let scope = activeAccountScope, validateAccount(scope), pendingMutation == nil else {
            if pendingMutation != nil {
                errorMessage = "上一项修改结果尚未确认，请先重试。"
            }
            return nil
        }
        return scope
    }

    private func validateMutation(subject: Int, scope: String) -> Bool {
        guard profile?.subject_user_id == subject, validateAccount(scope) else {
            errorMessage = "画像主体或登录账号已变化，已停止本次修改。"
            return false
        }
        return true
    }

    private func validateAccount(_ expected: String) -> Bool {
        guard activeAccountScope == expected, currentAccountScope() == expected else {
            errorMessage = "登录账号已变化，已停止读取或修改健康画像。"
            return false
        }
        return true
    }

    private static func goalMetricRequests(
        from raw: String
    ) -> [HealthProfileGoalMetricRequest]? {
        let known: [String: String] = [
            "睡眠时长": "sleep_duration",
            "hrv": "hrv",
            "体重": "weight",
            "步数": "steps",
            "血压": "blood_pressure",
            "血糖": "glucose"
        ]
        let values = HealthProfileGoalInputParser.splitMetrics(raw)
        var seen = Set<String>()
        var result: [HealthProfileGoalMetricRequest] = []
        for value in values {
            let normalized = value.lowercased()
            let key = known[value] ?? known[normalized] ?? normalized
            guard key.range(of: #"^[a-z0-9_.:-]+$"#, options: .regularExpression) != nil,
                  seen.insert(key).inserted else { return nil }
            result.append(.init(metric_key: key, display_label: value))
        }
        return result
    }

    static func allows(
        action: HealthProfileGoalAction,
        from status: HealthProfileGoalStatus
    ) -> Bool {
        switch (status, action) {
        case (.active, .pause),
             (.paused, .resume),
             (.active, .complete),
             (.paused, .complete),
             (.active, .archive),
             (.paused, .archive),
             (.completed, .archive):
            return true
        default:
            return false
        }
    }

    private func newClientEventID() -> String {
        let normalized = makeClientEventID().trimmingCharacters(in: .whitespacesAndNewlines)
        return String((normalized.isEmpty ? UUID().uuidString.lowercased() : normalized).prefix(80))
    }
}
