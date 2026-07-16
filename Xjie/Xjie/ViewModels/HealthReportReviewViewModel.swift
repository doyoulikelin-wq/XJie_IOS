import Foundation

struct HealthReportCandidateDraft: Equatable {
    var action: HealthReportDecisionAction?
    var correctedValue: String
    var correctedUnit: String

    static let empty = HealthReportCandidateDraft(
        action: nil,
        correctedValue: "",
        correctedUnit: ""
    )
}

struct HealthReportManualCandidateDraft: Equatable {
    var name = ""
    var value = ""
    var unit = ""
    var referenceLow = ""
    var referenceHigh = ""
    var referenceText = ""

    static let empty = HealthReportManualCandidateDraft()

    var hasChanges: Bool {
        [name, value, unit, referenceLow, referenceHigh, referenceText].contains {
            !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        }
    }
}

@MainActor
final class HealthReportReviewViewModel: ObservableObject {
    @Published private(set) var review: HealthReportReview?
    @Published private(set) var interpretation: HealthReportInterpretation?
    @Published private(set) var loading = false
    @Published private(set) var loadingInterpretation = false
    @Published private(set) var submitting = false
    @Published private(set) var addingManualCandidate = false
    @Published private(set) var drafts: [Int: HealthReportCandidateDraft] = [:]
    @Published var reportAcknowledged = false
    @Published var manualEntryExpanded = false
    @Published var manualDraft = HealthReportManualCandidateDraft.empty
    @Published var errorMessage: String?
    @Published var interpretationErrorMessage: String?

    let route: HealthReportWorkflowRoute

    private let accountScope: String?
    private let repository: HealthReportReviewRepositoryProtocol
    private let currentAccountScope: @MainActor () -> String?
    private let makeClientEventID: () -> String
    private var pendingConfirmationRequest: HealthReportConfirmationRequest?
    private var pendingManualCandidateRequest: HealthReportManualCandidateRequest?

    init(
        route: HealthReportWorkflowRoute,
        accountScope: String?,
        repository: HealthReportReviewRepositoryProtocol = HealthDataRepository(),
        currentAccountScope: @escaping @MainActor () -> String? = { AuthManager.shared.accountScope },
        makeClientEventID: @escaping () -> String = { UUID().uuidString.lowercased() }
    ) {
        self.route = route
        self.accountScope = accountScope
        self.repository = repository
        self.currentAccountScope = currentAccountScope
        self.makeClientEventID = makeClientEventID
    }

    var status: HealthReportWorkflowStatus {
        review?.status ?? route.status
    }

    var pendingClientEventID: String? {
        pendingConfirmationRequest?.client_event_id
    }

    var hasPendingRetry: Bool {
        pendingConfirmationRequest != nil && !submitting
    }

    var pendingManualCandidateClientEventID: String? {
        pendingManualCandidateRequest?.client_event_id
    }

    var hasPendingManualCandidateRetry: Bool {
        pendingManualCandidateRequest != nil && !addingManualCandidate
    }

    /// Only editable, not-yet-submitted choices are considered dirty. A request
    /// already submitted (including an idempotent retry) and terminal workflows
    /// must never be mistaken for disposable local edits.
    var hasUnsavedChanges: Bool {
        let reportDraftChanged = status == .awaitingConfirmation
            && pendingConfirmationRequest == nil
            && !submitting
            && (reportAcknowledged || drafts.values.contains { draft in
            draft.action != nil
                || !draft.correctedValue.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                || !draft.correctedUnit.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            })
        return reportDraftChanged || manualDraft.hasChanges
    }

    var manualEntryAvailable: Bool {
        guard let review else { return false }
        return review.status == .awaitingConfirmation
            || review.failure_recovery?.allows_manual_candidate == true
    }

    var manualEntryLocked: Bool {
        addingManualCandidate || pendingManualCandidateRequest != nil || submitting
    }

    var canSubmitManualCandidate: Bool {
        manualEntryAvailable
            && !manualEntryLocked
            && !manualDraft.name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && !manualDraft.value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && accountScope != nil
            && currentAccountScope() == accountScope
    }

    var requiredCandidates: [HealthReportFieldCandidate] {
        (review?.candidates ?? []).filter {
            $0.requires_review && $0.review_status == .pendingReview
        }
    }

    var unresolvedCandidateCount: Int {
        requiredCandidates.reduce(into: 0) { count, candidate in
            guard let draft = drafts[candidate.candidate_id],
                  let action = draft.action else {
                count += 1
                return
            }
            if action == .correct,
               draft.correctedValue.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                count += 1
            }
        }
    }

    var canSubmitReportConfirmation: Bool {
        guard let review,
              status == .awaitingConfirmation,
              review.can_confirm,
              review.requires_report_confirmation,
              reportAcknowledged,
              unresolvedCandidateCount == 0,
              !submitting,
              pendingConfirmationRequest == nil,
              accountScope != nil,
              currentAccountScope() == accountScope else { return false }
        return true
    }

    var canOpenInterpretation: Bool {
        guard status == .completed || status == .completedScorePending else { return false }
        return !loadingInterpretation
            && accountScope != nil
            && currentAccountScope() == accountScope
    }

    var editingLocked: Bool {
        submitting || addingManualCandidate || pendingConfirmationRequest != nil || status != .awaitingConfirmation
    }

    var canReloadStatusFromPrimary: Bool {
        guard !loading, !submitting, !addingManualCandidate else { return false }
        if review == nil { return true }
        switch status {
        case .failed, .unknown:
            return true
        default:
            return false
        }
    }

    var statusTitle: String {
        switch status {
        case .draft: return "未上传"
        case .uploading: return "上传中"
        case .recognizing: return "识别中"
        case .awaitingConfirmation: return "待确认"
        case .committing: return "入库中"
        case .completedScorePending: return "已确认 · 评分待更新"
        case .completed: return "已完成"
        case .failed: return "识别失败"
        case .unknown: return "状态待刷新"
        }
    }

    var statusDetail: String {
        switch status {
        case .draft:
            return "报告尚未进入上传流程。"
        case .uploading:
            return "正在上传原始文件，尚未开始字段识别。"
        case .recognizing:
            return "系统正在生成候选字段；确认前不会进入趋势、画像、评分或 AI 上下文。"
        case .awaitingConfirmation:
            return "请检查异常、低置信度或冲突字段。字段自动通过不等于整份报告已确认。"
        case .committing:
            return "正在按你的确认结果写入结构化观察，请勿重复提交。"
        case .completedScorePending:
            return "结构化数据已确认入库；评分服务仍在更新，当前不展示虚构变化。"
        case .completed:
            return "报告已确认入库，评分流程已完成。"
        case .failed:
            return failureRecoveryDetail
        case .unknown:
            return "服务器返回了当前版本尚未识别的状态，请刷新后再操作。"
        }
    }

    var primaryButtonTitle: String {
        if submitting { return "正在确认报告…" }
        if hasPendingRetry {
            return status == .committing ? "继续完成入库" : "使用同一确认请求重试"
        }
        switch status {
        case .recognizing, .uploading, .draft:
            return "正在处理报告"
        case .awaitingConfirmation:
            if unresolvedCandidateCount > 0 {
                return "还需检查 \(unresolvedCandidateCount) 项"
            }
            if !reportAcknowledged { return "请先完成报告级核对" }
            return "确认整份报告并入库"
        case .committing:
            return "报告正在入库"
        case .completedScorePending:
            return "查看本次解读"
        case .completed:
            return "查看本次解读"
        case .failed:
            return "重新读取失败原因"
        case .unknown:
            return "刷新报告状态"
        }
    }

    func load() async {
        guard !submitting, !addingManualCandidate, validateAccountScope() else { return }
        loading = true
        errorMessage = nil
        defer { loading = false }
        do {
            let response = try await repository.fetchReportReview(
                workflowID: route.workflowID,
                subjectUserID: route.subjectUserID
            )
            guard validateAccountScope(), validate(response: response) else { return }
            apply(response)
        } catch {
            guard validateAccountScope() else { return }
            errorMessage = error.localizedDescription
        }
    }

    func loadInterpretation(force: Bool = false) async {
        guard canOpenInterpretation, validateAccountScope() else { return }
        if interpretation != nil, !force { return }
        loadingInterpretation = true
        interpretationErrorMessage = nil
        defer { loadingInterpretation = false }
        do {
            let response = try await repository.fetchReportInterpretation(
                workflowID: route.workflowID,
                subjectUserID: route.subjectUserID
            )
            guard validateAccountScope(), validate(interpretation: response) else { return }
            interpretation = response
        } catch {
            guard validateAccountScope() else { return }
            interpretationErrorMessage = "本次解读读取失败：\(error.localizedDescription)"
        }
    }

    func choose(_ action: HealthReportDecisionAction, for candidateID: Int) {
        guard !editingLocked, requiredCandidates.contains(where: { $0.candidate_id == candidateID }) else {
            return
        }
        var draft = drafts[candidateID] ?? .empty
        draft.action = action
        if action != .correct {
            draft.correctedValue = ""
            draft.correctedUnit = ""
        }
        drafts[candidateID] = draft
        reportAcknowledged = false
    }

    func updateCorrection(candidateID: Int, value: String, unit: String) {
        guard !editingLocked, requiredCandidates.contains(where: { $0.candidate_id == candidateID }) else {
            return
        }
        drafts[candidateID] = HealthReportCandidateDraft(
            action: .correct,
            correctedValue: value,
            correctedUnit: unit
        )
        reportAcknowledged = false
    }

    func beginManualEntry() {
        guard manualEntryAvailable, !manualEntryLocked else { return }
        manualEntryExpanded = true
    }

    func cancelManualEntry() {
        guard !addingManualCandidate else { return }
        pendingManualCandidateRequest = nil
        manualDraft = .empty
        manualEntryExpanded = false
    }

    func editManualCandidateAgain() {
        guard !addingManualCandidate else { return }
        pendingManualCandidateRequest = nil
        errorMessage = nil
        manualEntryExpanded = true
    }

    func submitManualCandidate() async {
        guard !addingManualCandidate, !submitting else { return }
        if pendingManualCandidateRequest == nil {
            guard canSubmitManualCandidate else { return }
            guard let request = buildManualCandidateRequest() else { return }
            pendingManualCandidateRequest = request
        }
        guard let request = pendingManualCandidateRequest,
              let accountScope,
              validateAccountScope() else { return }

        addingManualCandidate = true
        errorMessage = nil
        defer { addingManualCandidate = false }
        do {
            let response = try await repository.addManualReportCandidate(
                workflowID: route.workflowID,
                request: request,
                expectedAccountScope: accountScope
            )
            guard validateAccountScope(), validate(response: response) else { return }
            apply(response)
        } catch {
            guard validateAccountScope() else { return }
            errorMessage = "手动补录尚未加入待复核列表：\(error.localizedDescription)。可使用同一请求安全重试。"
        }
    }

    func submitReportConfirmation() async {
        guard !submitting else { return }
        if pendingConfirmationRequest == nil {
            guard canSubmitReportConfirmation, let request = buildConfirmationRequest() else { return }
            pendingConfirmationRequest = request
        }
        guard let request = pendingConfirmationRequest,
              let accountScope,
              validateAccountScope() else { return }

        submitting = true
        errorMessage = nil
        defer { submitting = false }
        do {
            let response = try await repository.confirmReport(
                workflowID: route.workflowID,
                request: request,
                expectedAccountScope: accountScope
            )
            guard validateAccountScope(), validate(response: response) else { return }
            apply(response)
        } catch {
            guard validateAccountScope() else { return }
            errorMessage = "确认没有完成：\(error.localizedDescription)。可使用同一确认请求安全重试。"
        }
    }

    func reloadBeforeEditingAgain() async {
        await load()
        guard errorMessage == nil, status == .awaitingConfirmation else { return }
        pendingConfirmationRequest = nil
        reportAcknowledged = false
    }

    func discardUnsavedChanges() {
        guard hasUnsavedChanges, !submitting, !addingManualCandidate else { return }
        reportAcknowledged = false
        drafts = Dictionary(uniqueKeysWithValues: requiredCandidates.map {
            ($0.candidate_id, HealthReportCandidateDraft.empty)
        })
        pendingManualCandidateRequest = nil
        manualDraft = .empty
        manualEntryExpanded = false
    }

    private func apply(_ response: HealthReportReview) {
        let previous = review
        let revisionChanged = previous.map { !Self.sameRevision($0, response) } ?? true
        if revisionChanged {
            // A draft is meaningful only for the exact workflow and candidate
            // versions the user saw. Reusing it after a refresh could confirm a
            // different server value with an old local choice.
            drafts = [:]
            reportAcknowledged = false
            pendingConfirmationRequest = nil
            pendingManualCandidateRequest = nil
            manualDraft = .empty
            manualEntryExpanded = false
            interpretation = nil
            interpretationErrorMessage = nil
        }
        review = response
        if response.status == .committing,
           pendingConfirmationRequest == nil,
           let eventID = response.confirmation_client_event_id?.trimmingCharacters(in: .whitespacesAndNewlines),
           !eventID.isEmpty {
            // App 可能在首次确认提交后被终止。服务端已持久化 decisions；
            // 这里只能复用原 event id 续交，绝不能生成第二个确认事件。
            pendingConfirmationRequest = HealthReportConfirmationRequest(
                subject_user_id: response.subject_user_id,
                client_event_id: eventID,
                workflow_version: response.version,
                decisions: []
            )
        } else if response.status == .completed || response.status == .completedScorePending {
            pendingConfirmationRequest = nil
        }
        let candidateIDs = Set(response.candidates.map(\.candidate_id))
        drafts = drafts.filter { candidateIDs.contains($0.key) }
        for candidate in response.candidates where candidate.requires_review && drafts[candidate.candidate_id] == nil {
            drafts[candidate.candidate_id] = .empty
        }
        if response.status != .awaitingConfirmation {
            reportAcknowledged = false
        }
    }

    static func sameRevision(_ lhs: HealthReportReview, _ rhs: HealthReportReview) -> Bool {
        guard lhs.workflow_id == rhs.workflow_id,
              lhs.subject_user_id == rhs.subject_user_id,
              lhs.version == rhs.version else { return false }
        let lhsCandidates = Dictionary(uniqueKeysWithValues: lhs.candidates.map {
            ($0.candidate_id, $0.version)
        })
        let rhsCandidates = Dictionary(uniqueKeysWithValues: rhs.candidates.map {
            ($0.candidate_id, $0.version)
        })
        return lhsCandidates == rhsCandidates
    }

    private func buildConfirmationRequest() -> HealthReportConfirmationRequest? {
        guard let review else { return nil }
        var decisions: [HealthReportConfirmationDecision] = []
        for candidate in requiredCandidates {
            guard let draft = drafts[candidate.candidate_id], let action = draft.action else { return nil }
            let corrected = draft.correctedValue.trimmingCharacters(in: .whitespacesAndNewlines)
            let unit = draft.correctedUnit.trimmingCharacters(in: .whitespacesAndNewlines)
            let numeric = action == .correct ? Double(corrected) : nil
            let text = action == .correct && numeric == nil ? corrected : nil
            decisions.append(
                HealthReportConfirmationDecision(
                    candidate_id: candidate.candidate_id,
                    candidate_version: candidate.version,
                    action: action,
                    value_numeric: numeric,
                    value_text: text,
                    unit: action == .correct && !unit.isEmpty ? unit : nil
                )
            )
        }
        let clientEventID = makeClientEventID()
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .prefix(80)
        guard !clientEventID.isEmpty else { return nil }
        return HealthReportConfirmationRequest(
            subject_user_id: review.subject_user_id,
            client_event_id: String(clientEventID),
            workflow_version: review.version,
            decisions: decisions
        )
    }

    private func buildManualCandidateRequest() -> HealthReportManualCandidateRequest? {
        guard let review else { return nil }
        let name = manualDraft.name.trimmingCharacters(in: .whitespacesAndNewlines)
        let rawValue = manualDraft.value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty, !rawValue.isEmpty else { return nil }

        let numericValue = Double(rawValue).flatMap { $0.isFinite ? $0 : nil }
        let referenceLow = parseOptionalFiniteNumber(manualDraft.referenceLow, fieldName: "参考下限")
        guard referenceLow.valid else { return nil }
        let referenceHigh = parseOptionalFiniteNumber(manualDraft.referenceHigh, fieldName: "参考上限")
        guard referenceHigh.valid else { return nil }
        if let low = referenceLow.value, let high = referenceHigh.value, low > high {
            errorMessage = "参考下限不能大于参考上限。"
            return nil
        }
        let clientEventID = makeClientEventID()
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .prefix(80)
        guard !clientEventID.isEmpty else { return nil }
        let unit = manualDraft.unit.trimmingCharacters(in: .whitespacesAndNewlines)
        let referenceText = manualDraft.referenceText.trimmingCharacters(in: .whitespacesAndNewlines)
        return HealthReportManualCandidateRequest(
            subject_user_id: review.subject_user_id,
            workflow_version: review.version,
            client_event_id: String(clientEventID),
            canonical_code: nil,
            canonical_name: name,
            raw_name: name,
            value_numeric: numericValue,
            value_text: numericValue == nil ? rawValue : nil,
            unit: unit.isEmpty ? nil : unit,
            reference_low: referenceLow.value,
            reference_high: referenceHigh.value,
            reference_text: referenceText.isEmpty ? nil : referenceText,
            effective_at: nil
        )
    }

    private func parseOptionalFiniteNumber(
        _ raw: String,
        fieldName: String
    ) -> (valid: Bool, value: Double?) {
        let normalized = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !normalized.isEmpty else { return (true, nil) }
        guard let value = Double(normalized), value.isFinite else {
            errorMessage = "\(fieldName)必须是有效数字。"
            return (false, nil)
        }
        return (true, value)
    }

    private var failureRecoveryDetail: String {
        switch review?.failure_recovery?.recovery_action {
        case "retake_image":
            return "图片可能模糊。请重新拍摄，确保四角完整、文字清晰。"
        case "upload_missing_pages":
            return "报告可能缺页。请补齐所有页面后重新上传。"
        case "manual_entry_or_reupload":
            return "没有识别到可复核字段。你可以手动补录，或换一张更清晰的报告重新上传。"
        case "reupload_report":
            return "识别没有完成。请检查文件后重新上传。"
        case "retry_processing":
            return "处理暂时失败。请稍后刷新状态；若仍失败，请重新上传。"
        case "open_existing_report":
            return "这份报告已存在，请打开原报告继续处理，避免重复入库。"
        case "none":
            return "这份任务当前不能继续处理。"
        default:
            return "识别没有完成。请刷新状态、重新上传，或在允许时手动补录。"
        }
    }

    private func validateAccountScope() -> Bool {
        guard let accountScope, currentAccountScope() == accountScope else {
            errorMessage = "登录账号已变化，已停止读取或确认这份报告。"
            return false
        }
        return true
    }

    private func validate(response: HealthReportReview) -> Bool {
        guard response.workflow_id == route.workflowID,
              response.subject_user_id == route.subjectUserID else {
            errorMessage = "报告主体或任务标识不匹配，已拒绝显示这次响应。"
            return false
        }
        return true
    }

    private func validate(interpretation response: HealthReportInterpretation) -> Bool {
        guard response.workflow_id == route.workflowID,
              response.subject_user_id == route.subjectUserID else {
            interpretationErrorMessage = "报告主体或任务标识不匹配，已拒绝显示这次解读。"
            return false
        }
        return true
    }
}

extension HealthReportFieldCandidate {
    var originalValueLabel: String {
        let value = raw_value?.trimmingCharacters(in: .whitespacesAndNewlines)
        return [value, raw_unit].compactMap { item in
            guard let item, !item.isEmpty else { return nil }
            return item
        }.joined(separator: " ").nilIfEmpty ?? "原始值未识别"
    }

    var candidateValueLabel: String {
        let value: String?
        if let normalized_value {
            value = Self.format(normalized_value)
        } else {
            value = normalized_text?.trimmingCharacters(in: .whitespacesAndNewlines)
        }
        return [value, normalized_unit].compactMap { item in
            guard let item, !item.isEmpty else { return nil }
            return item
        }.joined(separator: " ").nilIfEmpty ?? "候选值待补录"
    }

    var referenceLabel: String {
        if let text = reference_text?.trimmingCharacters(in: .whitespacesAndNewlines), !text.isEmpty {
            return text
        }
        let low = reference_low.map(Self.format)
        let high = reference_high.map(Self.format)
        switch (low, high) {
        case let (low?, high?): return "\(low)–\(high)"
        case let (low?, nil): return "≥ \(low)"
        case let (nil, high?): return "≤ \(high)"
        default: return "参考范围未识别"
        }
    }

    var confidenceLabel: String {
        guard let confidence else { return "置信度未提供" }
        return "识别置信度 \(Int((confidence * 100).rounded()))%"
    }

    var sourceLocationLabel: String {
        var parts: [String] = []
        if let source = source_locator["source_type"]?.stringValue, !source.isEmpty {
            parts.append(Self.sourceTypeLabel(source))
        }
        if let page = source_locator["page"]?.intValue {
            parts.append("第 \(page) 页")
        }
        if let row = source_locator["row_index"]?.intValue {
            parts.append("数据区第 \(row + 1) 行")
        }
        if parts.isEmpty { return "来源位置未提供" }
        return parts.joined(separator: " · ")
    }

    var conflictReasonLabels: [String] {
        (conflict_reasons ?? []).map { reason in
            switch reason.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() {
            case "unit_conflict": return "识别单位与报告中的其他信息不一致"
            case "unit_missing": return "没有识别到单位，需要对照原件补充"
            case "reference_range_conflict": return "参考范围与识别结果存在冲突"
            case "duplicate_value_conflict": return "同一指标识别出相互冲突的多个值"
            case "invalid_reference_range": return "参考范围格式或上下限无效"
            default:
                return reason.contains("_")
                    ? "服务端标记了需要人工核对的字段冲突"
                    : reason
            }
        }
    }

    private static func format(_ value: Double) -> String {
        if value.rounded() == value { return String(Int(value)) }
        return String(format: "%.4f", value)
            .replacingOccurrences(of: #"\.?0+$"#, with: "", options: .regularExpression)
    }

    private static func sourceTypeLabel(_ source: String) -> String {
        switch source.lowercased() {
        case "pdf": return "PDF 原件"
        case "image", "photo": return "图片原件"
        case "camera": return "拍照原件"
        default: return source
        }
    }
}

private extension String {
    var nilIfEmpty: String? { isEmpty ? nil : self }
}
