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

/// 全 App 共用的报告上传单飞锁。
///
/// 报告页、聊天附件和系统“打开方式”各自可以持有独立 ViewModel，但同一时刻只能有一个入口
/// 创建或补传报告会话，避免重复任务以及多个上传弹窗争抢展示。所有调用都发生在主线程。
@MainActor
final class HealthReportUploadSingleFlight {
    static let shared = HealthReportUploadSingleFlight()

    private var holder: UUID?

    /// 尝试取得上传租约；任何未结束的上传都拒绝重入，包括同一入口的再次点击。
    /// - Parameter token: 本次上传操作唯一的租约标识；每次重试都必须重新生成。
    /// - Returns: 是否允许本次上传继续。
    func acquire(token: UUID) -> Bool {
        guard holder == nil else { return false }
        holder = token
        return true
    }

    /// 释放当前入口持有的上传租约；其他入口无权释放。
    /// - Parameter token: 取得租约时使用的同一个操作标识；旧任务不得释放后续操作。
    func release(token: UUID) {
        guard holder == token else { return }
        holder = nil
    }
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
    private let uploadSingleFlight: HealthReportUploadSingleFlight
    private var activeUploadLeaseToken: UUID?
    private var pollTask: Task<Void, Never>?
    private var abandonTask: Task<Void, Never>?
    private var sessionGeneration: UInt64 = 0
    private var activeAccountScope: String?
    private var activeSubjectUserID: Int?
    private var pendingRecoveryContext: HealthReportPendingRecoveryContext?
    private var announcedRuntimeNoticeKeys: Set<String> = []
    #if DEBUG
    private var supersededPollTasksForTesting: [Task<Void, Never>] = []
    #endif

    init(
        repository: any HealthReportCompletionRepositoryProtocol,
        currentAccountScope: @escaping @MainActor @Sendable () -> String? = {
            AuthManager.shared.accountScope
        },
        makeID: @escaping @Sendable () -> String = { UUID().uuidString },
        pollDelay: @escaping @Sendable () async throws -> Void = {
            try await Task.sleep(for: .seconds(2))
        },
        uploadSingleFlight: HealthReportUploadSingleFlight? = nil
    ) {
        self.repository = repository
        self.currentAccountScope = currentAccountScope
        self.makeID = makeID
        self.pollDelay = pollDelay
        self.uploadSingleFlight = uploadSingleFlight ?? .shared
    }

    convenience init() {
        self.init(repository: HealthReportCompletionRepository())
    }

    deinit {
        pollTask?.cancel()
        abandonTask?.cancel()
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
        let leaseToken = UUID()
        guard uploadSingleFlight.acquire(token: leaseToken) else {
            errorMessage = "另一份报告正在上传，请等待完成后再试。"
            return nil
        }
        activeUploadLeaseToken = leaseToken
        defer {
            uploadSingleFlight.release(token: leaseToken)
            if activeUploadLeaseToken == leaseToken {
                activeUploadLeaseToken = nil
            }
        }

        let generation = beginSession(accountScope: accountScope)
        activeSubjectUserID = subjectUserID
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
        announcedRuntimeNoticeKeys.removeAll()
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
            try validateSession(generation: generation, accountScope: accountScope)
            guard session.subject_user_id == subjectUserID else {
                throw APIError.invalidResponse
            }

            for (offset, input) in files.enumerated() {
                try validateSession(generation: generation, accountScope: accountScope)
                uploadStage = "正在上传第 \(offset + 1)/\(files.count) 页…"
                _ = try await repository.uploadAsset(
                    assetSetID: session.asset_set_id,
                    assetIndex: offset + 1,
                    subjectUserID: subjectUserID,
                    input: input,
                    clientAssetID: "\(requestID)-asset-\(offset + 1)",
                    expectedAccountScope: accountScope
                )
                try validateSession(generation: generation, accountScope: accountScope)
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
            try validateSession(generation: generation, accountScope: accountScope)
            return try await finishSeal(
                seal,
                context: recoveryContext,
                generation: generation
            )
        } catch is CancellationError {
            guard isCurrentSessionIdentity(
                generation: generation,
                accountScope: accountScope
            ) else { return nil }
            uploading = false
            activeSubjectUserID = nil
            uploadStage = ""
            backgroundTaskHint = nil
            return nil
        } catch {
            guard isCurrentSessionIdentity(
                generation: generation,
                accountScope: accountScope
            ) else { return nil }
            uploading = false
            activeSubjectUserID = nil
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
        let leaseToken = UUID()
        guard uploadSingleFlight.acquire(token: leaseToken) else {
            errorMessage = "另一份报告正在上传，请等待完成后再试。"
            return nil
        }
        activeUploadLeaseToken = leaseToken
        defer {
            uploadSingleFlight.release(token: leaseToken)
            if activeUploadLeaseToken == leaseToken {
                activeUploadLeaseToken = nil
            }
        }

        let generation = beginSession(accountScope: context.accountScope)
        activeSubjectUserID = context.subjectUserID
        uploading = true
        uploadProgress = 0.2
        uploadStage = recovery.missingPageIndices.contains(assetIndex)
            ? "正在补传第 \(assetIndex) 页…"
            : "正在替换第 \(assetIndex) 页…"
        errorMessage = nil
        infoMessage = nil
        do {
            try validateSession(
                generation: generation,
                accountScope: context.accountScope
            )
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
            try validateSession(
                generation: generation,
                accountScope: context.accountScope
            )
            uploadProgress = 0.65
            uploadStage = "正在重新检查完整度和清晰度…"
            let seal = try await repository.sealUploadSession(
                assetSetID: context.assetSetID,
                request: context.sealRequest,
                expectedAccountScope: context.accountScope
            )
            try validateSession(
                generation: generation,
                accountScope: context.accountScope
            )
            return try await finishSeal(
                seal,
                context: context,
                generation: generation
            )
        } catch is CancellationError {
            guard isCurrentSessionIdentity(
                generation: generation,
                accountScope: context.accountScope
            ) else { return nil }
            uploading = false
            uploadStage = ""
            return nil
        } catch {
            guard isCurrentSessionIdentity(
                generation: generation,
                accountScope: context.accountScope
            ) else { return nil }
            uploading = false
            uploadProgress = 0
            uploadStage = ""
            errorMessage = Self.userFacingError(error)
            return nil
        }
    }

    func abandonUploadRecovery() {
        guard let context = pendingRecoveryContext,
              currentAccountScope() == context.accountScope else {
            invalidateSession()
            uploadRecovery = nil
            pendingRecoveryContext = nil
            errorMessage = nil
            return
        }
        abandonTask?.cancel()
        let generation = beginSession(accountScope: context.accountScope)
        uploadRecovery = nil
        pendingRecoveryContext = nil
        errorMessage = nil
        abandonTask = Task { [weak self] in
            guard let self else { return }
            defer {
                if self.isCurrentSessionIdentity(
                    generation: generation,
                    accountScope: context.accountScope
                ) {
                    self.abandonTask = nil
                }
            }
            do {
                try await self.repository.abandonUploadSession(
                    assetSetID: context.assetSetID,
                    subjectUserID: context.subjectUserID,
                    expectedAccountScope: context.accountScope
                )
                try self.validateSession(
                    generation: generation,
                    accountScope: context.accountScope
                )
            } catch is CancellationError {
                return
            } catch APIError.accountScopeChanged {
                return
            } catch {
                guard self.isCurrentSessionIdentity(
                    generation: generation,
                    accountScope: context.accountScope
                ) else { return }
                self.errorMessage = "旧报告上传会话暂未清理，系统会自动重试。你仍可重新上传整份报告。"
            }
        }
    }

    func decideDuplicate(
        _ choice: HealthReportDuplicateChoice,
        prompt explicitPrompt: HealthReportDuplicatePrompt? = nil
    ) async {
        guard let prompt = explicitPrompt ?? duplicatePrompt,
              let runtime = activeRuntime,
              let scope = currentAccountScope(),
              activeAccountScope == scope,
              activeSubjectUserID == runtime.subject_user_id else {
            errorMessage = "报告任务已变化，请刷新后重试。"
            return
        }
        let generation = beginSession(accountScope: scope)
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
            try validateSession(generation: generation, accountScope: scope)
            let targetID = choice == .useExisting
                ? result.matched_workflow_id
                : result.workflow_id
            let refreshed = try await repository.fetchRuntime(
                workflowID: targetID,
                subjectUserID: runtime.subject_user_id,
                expectedAccountScope: scope
            )
            try validateSession(generation: generation, accountScope: scope)
            try validateRuntime(
                refreshed,
                workflowID: targetID,
                subjectUserID: runtime.subject_user_id
            )
            applyRuntime(refreshed, duplicate: choice == .useExisting)
            if Self.shouldPoll(refreshed) {
                startPolling(
                    workflowID: targetID,
                    subjectUserID: runtime.subject_user_id,
                    accountScope: scope
                )
            }
        } catch is CancellationError {
            return
        } catch {
            guard isCurrentSessionIdentity(
                generation: generation,
                accountScope: scope
            ) else { return }
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
        let generation = beginSession(accountScope: scope)
        do {
            let refreshed = try await repository.fetchRuntime(
                workflowID: runtime.workflow_id,
                subjectUserID: runtime.subject_user_id,
                expectedAccountScope: scope
            )
            try validateSession(generation: generation, accountScope: scope)
            try validateRuntime(
                refreshed,
                workflowID: runtime.workflow_id,
                subjectUserID: runtime.subject_user_id
            )
            applyRuntime(refreshed, duplicate: false)
            if Self.shouldPoll(refreshed) {
                startPolling(
                    workflowID: refreshed.workflow_id,
                    subjectUserID: refreshed.subject_user_id,
                    accountScope: scope
                )
            }
        } catch is CancellationError {
            return
        } catch {
            guard isCurrentSessionIdentity(
                generation: generation,
                accountScope: scope
            ) else { return }
            errorMessage = Self.userFacingError(error)
        }
    }

    func deferDuplicateDecision() {
        invalidateSession()
        duplicatePrompt = nil
        infoMessage = "已保留报告任务，可稍后从历史报告继续处理重复确认。"
    }

    /// 判断当前可见入口是否仍属于这个 ViewModel 持有的报告会话。
    ///
    /// 页面关闭重开后不依赖页面局部 UUID；账号 scope 与数字主体必须同时匹配，账号切换或家庭主体
    /// 变化时立即失败关闭。
    /// - Parameters:
    ///   - subjectUserID: 当前登录主体的数字用户 ID。
    ///   - accountScope: 当前 JWT 派生的账号作用域。
    /// - Returns: 当前入口是否可以展示、跳转或处理该报告会话。
    func ownsActiveSession(subjectUserID: Int?, accountScope: String?) -> Bool {
        guard let subjectUserID,
              let accountScope,
              !accountScope.isEmpty else { return false }
        return activeSubjectUserID == subjectUserID
            && activeAccountScope == accountScope
            && currentAccountScope() == accountScope
    }

    func accountDidChange(to accountScope: String?) {
        guard accountScope != activeAccountScope else { return }
        if let activeUploadLeaseToken {
            uploadSingleFlight.release(token: activeUploadLeaseToken)
            self.activeUploadLeaseToken = nil
        }
        abandonTask?.cancel()
        abandonTask = nil
        invalidateSession()
        activeAccountScope = accountScope
        uploading = false
        uploadProgress = 0
        uploadStage = ""
        backgroundTaskHint = nil
        activeReportWorkflow = nil
        activeReportTitle = "报告"
        activeRuntime = nil
        activeSubjectUserID = nil
        duplicatePrompt = nil
        uploadRecovery = nil
        pendingRecoveryContext = nil
        errorMessage = nil
        infoMessage = nil
        announcedRuntimeNoticeKeys.removeAll()
    }

    private func startPolling(workflowID: Int, subjectUserID: Int, accountScope: String) {
        guard activeAccountScope == accountScope,
              currentAccountScope() == accountScope else { return }
        // 每次重启轮询都切换会话代次，旧请求即使忽略取消并晚到，也不能回写当前账号或任务。
        invalidateSession()
        let generation = sessionGeneration
        pollTask = Task { [weak self] in
            guard let self else { return }
            defer {
                if self.sessionGeneration == generation {
                    self.pollTask = nil
                }
            }
            for _ in 0..<45 {
                do {
                    guard self.isCurrentPoll(
                        generation: generation,
                        accountScope: accountScope
                    ) else { return }
                    try await self.pollDelay()
                    guard self.isCurrentPoll(
                        generation: generation,
                        accountScope: accountScope
                    ) else { return }
                    let runtime = try await self.repository.fetchRuntime(
                        workflowID: workflowID,
                        subjectUserID: subjectUserID,
                        expectedAccountScope: accountScope
                    )
                    guard self.isCurrentPoll(
                        generation: generation,
                        accountScope: accountScope
                    ) else { return }
                    try self.validateRuntime(
                        runtime,
                        workflowID: workflowID,
                        subjectUserID: subjectUserID
                    )
                    self.applyRuntime(runtime, duplicate: false)
                    if !Self.shouldPoll(runtime) { return }
                } catch is CancellationError {
                    return
                } catch APIError.accountScopeChanged {
                    return
                } catch {
                    guard self.isCurrentPoll(
                        generation: generation,
                        accountScope: accountScope
                    ) else { return }
                    // A transient read failure must not turn a valid server job
                    // into a failed report. Keep the user on the recoverable state.
                    self.backgroundTaskHint = "报告仍在后台处理，可稍后到历史报告继续查看。"
                }
            }
            guard self.isCurrentPoll(
                generation: generation,
                accountScope: accountScope
            ) else { return }
            self.backgroundTaskHint = "报告仍在后台处理；确认前不会进入趋势、画像、评分或 AI 上下文。"
        }
    }

    /// 开启新的异步会话；上传、恢复、决策、刷新与轮询共用同一代次约束。
    private func beginSession(accountScope: String) -> UInt64 {
        invalidateSession()
        activeAccountScope = accountScope
        return sessionGeneration
    }

    /// 取消当前轮询并推进会话代次；代次可阻断账号切换后又切回原值产生的 ABA 晚到回写。
    private func invalidateSession() {
        sessionGeneration &+= 1
        guard let pollTask else { return }
        pollTask.cancel()
        #if DEBUG
        supersededPollTasksForTesting.append(pollTask)
        #endif
        self.pollTask = nil
    }

    /// 不含任务取消状态的身份检查，用于只清理由当前会话启动的加载状态。
    private func isCurrentSessionIdentity(
        generation: UInt64,
        accountScope: String
    ) -> Bool {
        sessionGeneration == generation
            && activeAccountScope == accountScope
            && currentAccountScope() == accountScope
    }

    /// 所有异步结果回写前都必须同时通过取消、会话代次与账号作用域校验。
    private func validateSession(generation: UInt64, accountScope: String) throws {
        try Task.checkCancellation()
        guard isCurrentSessionIdentity(
            generation: generation,
            accountScope: accountScope
        ) else {
            throw APIError.accountScopeChanged
        }
    }

    /// 校验运行态响应仍属于请求的工作流和数字主体，串号响应不得进入任何报告 UI。
    private func validateRuntime(
        _ runtime: HealthReportRuntime,
        workflowID: Int,
        subjectUserID: Int
    ) throws {
        guard runtime.workflow_id == workflowID,
              runtime.subject_user_id == subjectUserID else {
            throw APIError.invalidResponse
        }
    }

    private func isCurrentPoll(generation: UInt64, accountScope: String) -> Bool {
        !Task.isCancelled
            && isCurrentSessionIdentity(
                generation: generation,
                accountScope: accountScope
            )
    }

    #if DEBUG
    /// 测试专用：确定性等待当前轮询结束，避免依赖固定次数的调度让步。
    func waitForCurrentPollForTesting() async {
        let task = pollTask
        await task?.value
    }

    /// 测试专用：等待所有已被新代次取代的轮询真正退出。
    func waitForSupersededPollsForTesting() async {
        let tasks = supersededPollTasksForTesting
        supersededPollTasksForTesting.removeAll()
        for task in tasks {
            await task.value
        }
    }
    #endif

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
                announceRuntimeInfo("需要确认报告是否重复。", for: runtime)
            } else {
                errorMessage = "重复报告任务缺少版本信息，请刷新后重试。"
            }
        case "review_fields":
            backgroundTaskHint = "识别完成，请检查 \(runtime.primary_action?.pending_count ?? 0) 个字段；确认前不会作为可信数据使用。"
            announceRuntimeInfo("报告字段等待复核。", for: runtime)
        case "confirm_and_update_scores":
            backgroundTaskHint = "字段已检查，等待确认整份报告后入库并更新评分。"
            announceRuntimeInfo("请确认整份报告。", for: runtime)
        case "view_interpretation":
            backgroundTaskHint = runtime.state == "completed_score_pending"
                ? "报告已确认入库，评分仍在更新。"
                : nil
            announceRuntimeInfo(
                runtime.state == "completed_score_pending"
                    ? "报告已入库；评分待更新。"
                    : "报告已确认入库。",
                for: runtime
            )
        case "uploading", "recognizing":
            backgroundTaskHint = "正在识别 \(duplicate ? "重复" : "")报告；确认前不会进入趋势、画像、评分或 AI 上下文。"
            announceRuntimeInfo("上传完成，正在后台识别。", for: runtime)
        case "open_existing_report":
            backgroundTaskHint = nil
            announceRuntimeInfo("已打开已有报告，没有重复入库。", for: runtime)
        case let action?:
            backgroundTaskHint = nil
            let failure = runtime.failure_code ?? action
            errorMessage = Self.failureMessage(failure)
        case nil:
            backgroundTaskHint = "报告状态待刷新；确认前不会作为可信数据使用。"
        }
    }

    /// 同一工作流的同一服务端状态只发布一次模态提示；轮询仍可持续刷新非模态进度。
    private func announceRuntimeInfo(_ message: String, for runtime: HealthReportRuntime) {
        let action = runtime.primary_action?.code ?? "none"
        let phase = action == "uploading" || action == "recognizing"
            ? "processing"
            : "\(runtime.state):\(action)"
        let key = "\(runtime.workflow_id):\(phase)"
        guard announcedRuntimeNoticeKeys.insert(key).inserted else { return }
        infoMessage = message
    }

    private func finishSeal(
        _ seal: HealthReportSealResult,
        context: HealthReportPendingRecoveryContext,
        generation: UInt64
    ) async throws -> HealthReportWorkflowRoute? {
        try validateSession(
            generation: generation,
            accountScope: context.accountScope
        )
        guard seal.asset_set_id == context.assetSetID else {
            throw APIError.invalidResponse
        }
        uploadProgress = 1
        if let failureCode = seal.failure_code {
            uploading = false
            uploadStage = ""
            applyPreWorkflowFailure(seal, fallbackCode: failureCode, context: context)
            return nil
        }
        pendingRecoveryContext = nil
        uploadRecovery = nil
        guard let workflowID = seal.workflow_id else {
            throw HealthReportCompletionViewModelError.missingWorkflow
        }
        uploadStage = "正在确认报告处理状态…"
        let runtime = try await repository.fetchRuntime(
            workflowID: workflowID,
            subjectUserID: context.subjectUserID,
            expectedAccountScope: context.accountScope
        )
        try validateSession(
            generation: generation,
            accountScope: context.accountScope
        )
        try validateRuntime(
            runtime,
            workflowID: workflowID,
            subjectUserID: context.subjectUserID
        )
        uploading = false
        uploadStage = ""
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
        case "report_ocr_storage_unavailable":
            return "报告原件暂时无法读取，请重新上传同一份报告以恢复处理。"
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
