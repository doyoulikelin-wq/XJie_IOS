import Foundation

struct HealthReportDuplicatePrompt: Identifiable, Equatable, Sendable {
    let workflowID: Int
    let matchedWorkflowID: Int
    let workflowVersion: Int

    var id: Int { workflowID }
}

struct HealthReportUploadRecovery: Identifiable, Equatable, Sendable {
    let assetSetID: Int
    let failureCode: String
    let actionCode: String
    let problemAssetIndices: [Int]
    let missingPageIndices: [Int]

    var id: Int { assetSetID }

    var nextAssetIndex: Int? {
        missingPageIndices.first ?? problemAssetIndices.first
    }
}

private struct HealthReportPendingRecoveryContext: Sendable {
    let assetSetID: Int
    let subjectUserID: Int
    let accountScope: String
    let clientRequestID: String
    let sealRequest: HealthReportSealRequest
}

@MainActor
final class HealthReportCompletionViewModel: ObservableObject {
    @Published private(set) var uploading = false
    @Published private(set) var uploadProgress: Double = 0
    @Published private(set) var uploadStage = ""
    @Published private(set) var backgroundTaskHint: String?
    @Published private(set) var activeReportWorkflow: HealthReportWorkflowRoute?
    @Published private(set) var activeReportTitle = "报告"
    @Published private(set) var activeRuntime: HealthReportRuntime?
    @Published private(set) var duplicatePrompt: HealthReportDuplicatePrompt?
    @Published private(set) var uploadRecovery: HealthReportUploadRecovery?
    @Published var errorMessage: String?
    @Published var infoMessage: String?

    private let repository: any HealthReportCompletionRepositoryProtocol
    private let currentAccountScope: @MainActor @Sendable () -> String?
    private let makeID: @Sendable () -> String
    private let pollDelay: @Sendable () async throws -> Void
    private var pollTask: Task<Void, Never>?
    private var activeAccountScope: String?
    private var pendingRecoveryContext: HealthReportPendingRecoveryContext?

    init(
        repository: any HealthReportCompletionRepositoryProtocol,
        currentAccountScope: @escaping @MainActor @Sendable () -> String? = {
            AuthManager.shared.accountScope
        },
        makeID: @escaping @Sendable () -> String = { UUID().uuidString },
        pollDelay: @escaping @Sendable () async throws -> Void = {
            try await Task.sleep(for: .seconds(2))
        }
    ) {
        self.repository = repository
        self.currentAccountScope = currentAccountScope
        self.makeID = makeID
        self.pollDelay = pollDelay
    }

    convenience init() {
        self.init(repository: HealthReportCompletionRepository())
    }

    deinit {
        pollTask?.cancel()
    }

    @discardableResult
    func uploadReport(
        files: [HealthReportUploadAssetInput],
        source: String,
        subjectUserID: Int?,
        accountScope: String?
    ) async -> HealthReportWorkflowRoute? {
        guard !uploading else { return nil }
        guard !files.isEmpty else {
            errorMessage = "请选择至少一页报告。"
            return nil
        }
        guard files.count <= 100 else {
            errorMessage = "单份报告最多支持 100 页，请拆分后上传。"
            return nil
        }
        guard files.allSatisfy({ !$0.data.isEmpty }) else {
            errorMessage = "报告中有空文件，请重新选择。"
            return nil
        }
        guard let subjectUserID, let accountScope,
              !accountScope.isEmpty,
              currentAccountScope() == accountScope else {
            errorMessage = "当前登录信息不完整，请重新登录后上传。"
            return nil
        }

        pollTask?.cancel()
        uploading = true
        uploadProgress = 0
        uploadStage = "正在创建报告任务…"
        backgroundTaskHint = nil
        activeReportWorkflow = nil
        activeRuntime = nil
        duplicatePrompt = nil
        uploadRecovery = nil
        errorMessage = nil
        infoMessage = nil
        let requestID = makeID()
        activeAccountScope = accountScope
        activeReportTitle = Self.reportTitle(files)

        do {
            let mediaKind = Self.mediaKind(source: source, files: files)
            let expectedPageCount = mediaKind == .pdf ? nil : files.count
            let session = try await repository.startUploadSession(
                HealthReportUploadSessionRequest(
                    subject_user_id: subjectUserID,
                    client_request_id: requestID,
                    media_kind: mediaKind,
                    expected_page_count: expectedPageCount
                ),
                expectedAccountScope: accountScope
            )
            try validateAccount(accountScope)

            for (offset, input) in files.enumerated() {
                try Task.checkCancellation()
                try validateAccount(accountScope)
                uploadStage = "正在上传第 \(offset + 1)/\(files.count) 页…"
                _ = try await repository.uploadAsset(
                    assetSetID: session.asset_set_id,
                    assetIndex: offset + 1,
                    subjectUserID: subjectUserID,
                    input: input,
                    clientAssetID: "\(requestID)-asset-\(offset + 1)",
                    expectedAccountScope: accountScope
                )
                try validateAccount(accountScope)
                uploadProgress = Double(offset + 1) / Double(files.count + 1)
            }

            let sealRequest = HealthReportSealRequest(
                subject_user_id: subjectUserID,
                report_type: "exam",
                title: Self.reportTitle(files),
                hospital: nil,
                report_date: nil
            )
            let recoveryContext = HealthReportPendingRecoveryContext(
                assetSetID: session.asset_set_id,
                subjectUserID: subjectUserID,
                accountScope: accountScope,
                clientRequestID: requestID,
                sealRequest: sealRequest
            )
            uploadStage = "正在检查完整度和清晰度…"
            let seal = try await repository.sealUploadSession(
                assetSetID: session.asset_set_id,
                request: sealRequest,
                expectedAccountScope: accountScope
            )
            try validateAccount(accountScope)
            return try await finishSeal(seal, context: recoveryContext)
        } catch is CancellationError {
            uploading = false
            uploadStage = ""
            backgroundTaskHint = nil
            return nil
        } catch {
            uploading = false
            uploadStage = ""
            uploadProgress = 0
            backgroundTaskHint = nil
            errorMessage = Self.userFacingError(error)
            return nil
        }
    }

    @discardableResult
    func recoverReportAsset(
        input: HealthReportUploadAssetInput,
        assetIndex: Int
    ) async -> HealthReportWorkflowRoute? {
        guard !uploading else { return nil }
        guard !input.data.isEmpty else {
            errorMessage = "替换文件为空，请重新选择。"
            return nil
        }
        guard let recovery = uploadRecovery,
              recovery.nextAssetIndex == assetIndex
                || recovery.problemAssetIndices.contains(assetIndex)
                || recovery.missingPageIndices.contains(assetIndex),
              let context = pendingRecoveryContext,
              context.assetSetID == recovery.assetSetID,
              currentAccountScope() == context.accountScope else {
            errorMessage = "报告恢复任务已变化，请重新上传整份报告。"
            return nil
        }

        uploading = true
        uploadProgress = 0.2
        uploadStage = recovery.missingPageIndices.contains(assetIndex)
            ? "正在补传第 \(assetIndex) 页…"
            : "正在替换第 \(assetIndex) 页…"
        errorMessage = nil
        infoMessage = nil
        do {
            try validateAccount(context.accountScope)
            _ = try await repository.recoverAsset(
                assetSetID: context.assetSetID,
                assetIndex: assetIndex,
                subjectUserID: context.subjectUserID,
                input: input,
                clientAssetID: Self.recoveryClientAssetID(
                    requestID: context.clientRequestID,
                    assetIndex: assetIndex
                ),
                expectedAccountScope: context.accountScope
            )
            try validateAccount(context.accountScope)
            uploadProgress = 0.65
            uploadStage = "正在重新检查完整度和清晰度…"
            let seal = try await repository.sealUploadSession(
                assetSetID: context.assetSetID,
                request: context.sealRequest,
                expectedAccountScope: context.accountScope
            )
            try validateAccount(context.accountScope)
            return try await finishSeal(seal, context: context)
        } catch is CancellationError {
            uploading = false
            uploadStage = ""
            return nil
        } catch {
            uploading = false
            uploadProgress = 0
            uploadStage = ""
            errorMessage = Self.userFacingError(error)
            return nil
        }
    }

    func abandonUploadRecovery() {
        uploadRecovery = nil
        pendingRecoveryContext = nil
        errorMessage = nil
    }

    func decideDuplicate(
        _ choice: HealthReportDuplicateChoice,
        prompt explicitPrompt: HealthReportDuplicatePrompt? = nil
    ) async {
        guard let prompt = explicitPrompt ?? duplicatePrompt,
              let runtime = activeRuntime,
              let scope = currentAccountScope(),
              activeAccountScope == scope else {
            errorMessage = "报告任务已变化，请刷新后重试。"
            return
        }
        duplicatePrompt = nil
        do {
            let result = try await repository.decideDuplicate(
                workflowID: prompt.workflowID,
                request: HealthReportDuplicateDecisionRequest(
                    subject_user_id: runtime.subject_user_id,
                    workflow_version: prompt.workflowVersion,
                    client_event_id: makeID(),
                    action: choice.rawValue
                ),
                expectedAccountScope: scope
            )
            try validateAccount(scope)
            let targetID = choice == .useExisting
                ? result.matched_workflow_id
                : result.workflow_id
            let refreshed = try await repository.fetchRuntime(
                workflowID: targetID,
                subjectUserID: runtime.subject_user_id
            )
            try validateAccount(scope)
            applyRuntime(refreshed, duplicate: choice == .useExisting)
            if Self.shouldPoll(refreshed) {
                startPolling(
                    workflowID: targetID,
                    subjectUserID: runtime.subject_user_id,
                    accountScope: scope
                )
            }
        } catch {
            errorMessage = Self.userFacingError(error)
        }
    }

    func dismissBackgroundHint() {
        backgroundTaskHint = nil
    }

    func refreshActiveRuntime() async {
        guard let runtime = activeRuntime,
              let scope = activeAccountScope,
              currentAccountScope() == scope else {
            infoMessage = "当前没有正在处理的报告任务。"
            return
        }
        do {
            let refreshed = try await repository.fetchRuntime(
                workflowID: runtime.workflow_id,
                subjectUserID: runtime.subject_user_id
            )
            try validateAccount(scope)
            applyRuntime(refreshed, duplicate: false)
            if Self.shouldPoll(refreshed) {
                startPolling(
                    workflowID: refreshed.workflow_id,
                    subjectUserID: refreshed.subject_user_id,
                    accountScope: scope
                )
            }
        } catch {
            errorMessage = Self.userFacingError(error)
        }
    }

    func deferDuplicateDecision() {
        duplicatePrompt = nil
        infoMessage = "已保留报告任务，可稍后从历史报告继续处理重复确认。"
    }

    func accountDidChange(to accountScope: String?) {
        guard accountScope != activeAccountScope else { return }
        pollTask?.cancel()
        pollTask = nil
        activeAccountScope = accountScope
        uploading = false
        uploadProgress = 0
        uploadStage = ""
        backgroundTaskHint = nil
        activeReportWorkflow = nil
        activeReportTitle = "报告"
        activeRuntime = nil
        duplicatePrompt = nil
        uploadRecovery = nil
        pendingRecoveryContext = nil
        errorMessage = nil
        infoMessage = nil
    }

    private func startPolling(workflowID: Int, subjectUserID: Int, accountScope: String) {
        pollTask?.cancel()
        pollTask = Task { [weak self] in
            guard let self else { return }
            for _ in 0..<45 {
                do {
                    try await self.pollDelay()
                    try Task.checkCancellation()
                    try self.validateAccount(accountScope)
                    let runtime = try await self.repository.fetchRuntime(
                        workflowID: workflowID,
                        subjectUserID: subjectUserID
                    )
                    try self.validateAccount(accountScope)
                    self.applyRuntime(runtime, duplicate: false)
                    if !Self.shouldPoll(runtime) { return }
                } catch is CancellationError {
                    return
                } catch APIError.accountScopeChanged {
                    return
                } catch {
                    // A transient read failure must not turn a valid server job
                    // into a failed report. Keep the user on the recoverable state.
                    self.backgroundTaskHint = "报告仍在后台处理，可稍后到历史报告继续查看。"
                }
            }
            self.backgroundTaskHint = "报告仍在后台处理；确认前不会进入趋势、画像、评分或 AI 上下文。"
        }
    }

    private func applyRuntime(_ runtime: HealthReportRuntime, duplicate: Bool) {
        activeRuntime = runtime
        activeReportWorkflow = runtime.route
        switch runtime.primary_action?.code {
        case "resolve_duplicate":
            if let target = runtime.primary_action?.target_workflow_id,
               let version = runtime.workflow_version {
                duplicatePrompt = HealthReportDuplicatePrompt(
                    workflowID: runtime.workflow_id,
                    matchedWorkflowID: target,
                    workflowVersion: version
                )
                backgroundTaskHint = "检测到可能重复的报告，请选择使用已有报告或继续新建。"
                infoMessage = "需要确认报告是否重复。"
            } else {
                errorMessage = "重复报告任务缺少版本信息，请刷新后重试。"
            }
        case "review_fields":
            backgroundTaskHint = "识别完成，请检查 \(runtime.primary_action?.pending_count ?? 0) 个字段；确认前不会作为可信数据使用。"
            infoMessage = "报告字段等待复核。"
        case "confirm_and_update_scores":
            backgroundTaskHint = "字段已检查，等待确认整份报告后入库并更新评分。"
            infoMessage = "请确认整份报告。"
        case "view_interpretation":
            backgroundTaskHint = runtime.state == "completed_score_pending"
                ? "报告已确认入库，评分仍在更新。"
                : nil
            infoMessage = runtime.state == "completed_score_pending"
                ? "报告已入库；评分待更新。"
                : "报告已确认入库。"
        case "uploading", "recognizing":
            backgroundTaskHint = "正在识别 \(duplicate ? "重复" : "")报告；确认前不会进入趋势、画像、评分或 AI 上下文。"
            infoMessage = "上传完成，正在后台识别。"
        case "open_existing_report":
            backgroundTaskHint = nil
            infoMessage = "已打开已有报告，没有重复入库。"
        case let action?:
            backgroundTaskHint = nil
            let failure = runtime.failure_code ?? action
            errorMessage = Self.failureMessage(failure)
        case nil:
            backgroundTaskHint = "报告状态待刷新；确认前不会作为可信数据使用。"
        }
    }

    private func finishSeal(
        _ seal: HealthReportSealResult,
        context: HealthReportPendingRecoveryContext
    ) async throws -> HealthReportWorkflowRoute? {
        uploadProgress = 1
        uploading = false
        uploadStage = ""
        if let failureCode = seal.failure_code {
            applyPreWorkflowFailure(seal, fallbackCode: failureCode, context: context)
            return nil
        }
        pendingRecoveryContext = nil
        uploadRecovery = nil
        guard let workflowID = seal.workflow_id else {
            throw HealthReportCompletionViewModelError.missingWorkflow
        }
        let runtime = try await repository.fetchRuntime(
            workflowID: workflowID,
            subjectUserID: context.subjectUserID
        )
        try validateAccount(context.accountScope)
        applyRuntime(runtime, duplicate: seal.duplicate)
        if Self.shouldPoll(runtime) {
            startPolling(
                workflowID: workflowID,
                subjectUserID: context.subjectUserID,
                accountScope: context.accountScope
            )
        }
        return activeReportWorkflow
    }

    private func applyPreWorkflowFailure(
        _ seal: HealthReportSealResult,
        fallbackCode code: String,
        context: HealthReportPendingRecoveryContext
    ) {
        let action = seal.recovery_action ?? {
            switch code {
            case "missing_page", "invalid_page_manifest": return "upload_missing_pages"
            case "blur", "blurry_image", "blank_page", "low_resolution", "unreadable_image":
                return "replace_problem_pages"
            default: return "retry_upload"
            }
        }()
        pendingRecoveryContext = context
        uploadRecovery = HealthReportUploadRecovery(
            assetSetID: seal.asset_set_id,
            failureCode: code,
            actionCode: action,
            problemAssetIndices: seal.problem_asset_indices ?? [],
            missingPageIndices: seal.missing_page_indices ?? []
        )
        errorMessage = Self.failureMessage(code)
    }

    private func validateAccount(_ expected: String) throws {
        guard currentAccountScope() == expected else {
            throw APIError.accountScopeChanged
        }
    }

    private static func shouldPoll(_ runtime: HealthReportRuntime) -> Bool {
        switch runtime.primary_action?.code {
        case "uploading", "recognizing": return true
        default: return false
        }
    }

    private static func recoveryClientAssetID(requestID: String, assetIndex: Int) -> String {
        "\(requestID.prefix(60))-recovery-\(assetIndex)"
    }

    private static func mediaKind(
        source: String,
        files: [HealthReportUploadAssetInput]
    ) -> HealthReportUploadMediaKind {
        if files.count == 1 {
            let lower = files[0].fileName.lowercased()
            if lower.hasSuffix(".pdf") { return .pdf }
            if lower.hasSuffix(".csv") { return .csv }
        }
        switch source {
        case "相机": return .camera
        case "相册": return .photoLibrary
        default: return .legacy
        }
    }

    private static func reportTitle(_ files: [HealthReportUploadAssetInput]) -> String {
        guard let first = files.first else { return "健康报告" }
        if files.count == 1 { return first.fileName }
        let stem = (first.fileName as NSString).deletingPathExtension
        return "\(stem) 等 \(files.count) 页"
    }

    private static func userFacingError(_ error: Error) -> String {
        if let apiError = error as? APIError {
            return apiError.localizedDescription
        }
        if let error = error as? LocalizedError,
           let description = error.errorDescription {
            return description
        }
        return "报告上传未完成，请稍后重试。"
    }

    private static func failureMessage(_ code: String) -> String {
        switch code {
        case "missing_page": return "报告页码不完整，请补齐缺失页后再提交。"
        case "invalid_page_manifest": return "报告页序有冲突，请重新整理页序。"
        case "blur", "blurry_image": return "报告中有模糊页面，请重拍对应页。"
        case "blank_page": return "报告中有空白页面，请替换后重试。"
        case "low_resolution": return "报告图片分辨率过低，请重拍对应页。"
        case "unreadable_image", "unreadable_pdf": return "报告文件无法读取，请替换原文件。"
        case "asset_too_large", "file_too_large": return "单页文件过大，请压缩或重新导出后上传。"
        case "too_many_pages": return "PDF 页数超过 100 页，请拆分后上传。"
        case "quality_component_unavailable", "pdf_component_unavailable":
            return "报告检查服务暂时不可用，请稍后重试。"
        default: return "报告处理未完成（\(code)），请重试或联系客服。"
        }
    }
}

private enum HealthReportCompletionViewModelError: LocalizedError {
    case missingWorkflow

    var errorDescription: String? {
        switch self {
        case .missingWorkflow: return "服务端没有返回报告任务，请重新上传。"
        }
    }
}

extension AuthManager {
    var authenticatedNumericUserID: Int? {
        if let raw = userInfo?.id?.trimmingCharacters(in: .whitespacesAndNewlines),
           let value = Int(raw) {
            return value
        }
        if let value = Int(subjectId.trimmingCharacters(in: .whitespacesAndNewlines)) {
            return value
        }
        #if DEBUG
        if isUIValidationSession { return 1 }
        #endif
        return nil
    }
}
