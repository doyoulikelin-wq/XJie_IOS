import SwiftUI

/// 健康报告首页明确区分处理中、待确认、已完成和失败，失败不得伪装成“解析中”。
enum HealthReportDashboardState: Equatable {
    case processing
    case awaiting
    case committing
    case completed
    case failed
    case unknown

    init(workflowStatus: HealthReportWorkflowStatus) {
        switch workflowStatus {
        case .completed, .completedScorePending:
            self = .completed
        case .awaitingConfirmation:
            self = .awaiting
        case .failed:
            self = .failed
        case .unknown:
            self = .unknown
        case .committing:
            self = .committing
        case .draft, .uploading, .recognizing:
            self = .processing
        }
    }

    var title: String {
        switch self {
        case .processing: return "原件已保存 · 解析中"
        case .awaiting: return "识别完成 · 待确认"
        case .committing: return "确认完成 · 入库中"
        case .completed: return "已完成解析"
        case .failed: return "解析未完成"
        case .unknown: return "报告状态待确认"
        }
    }

    var icon: String {
        switch self {
        case .processing: return "clock.badge.checkmark.fill"
        case .awaiting: return "person.crop.circle.badge.questionmark"
        case .committing: return "tray.and.arrow.down.fill"
        case .completed: return "checkmark.seal.fill"
        case .failed: return "exclamationmark.triangle.fill"
        case .unknown: return "questionmark.circle.fill"
        }
    }

    var color: Color {
        switch self {
        case .processing: return Color(hex: "2B78C5")
        case .awaiting: return Color(hex: "C57A27")
        case .committing: return Color(hex: "287F9E")
        case .completed: return Color(hex: "149C8F")
        case .failed: return Color(hex: "C84E5E")
        case .unknown: return Color(hex: "627D94")
        }
    }
}

/// 首页内容状态由一个共享状态机决定，读取失败不能被空列表分支误写成“暂无报告”。
enum HealthReportDashboardContentState: Equatable {
    case loading
    case available
    case failed
    case empty

    init(loading: Bool, hasReport: Bool, hasError: Bool) {
        if hasReport {
            self = .available
        } else if loading {
            self = .loading
        } else if hasError {
            self = .failed
        } else {
            self = .empty
        }
    }
}

/// 聚合报告 history、trace 与 interpretation，避免 SwiftUI 页面自行推断服务端状态。
@MainActor
final class HealthReportDashboardViewModel: ObservableObject {
    @Published private(set) var loading = false
    @Published private(set) var traceLoadingWorkflowID: Int?
    @Published private(set) var items: [HealthReportHistoryItem] = []
    @Published private(set) var latestTrace: HealthReportTrace?
    @Published private(set) var latestInterpretation: HealthReportInterpretation?
    @Published private(set) var latestLocalOriginals: [HealthReportLocalOriginalMetadata] = []
    @Published private(set) var errorMessage: String?
    @Published private(set) var detailWarning: String?
    @Published var selectedTrace: XAgeReportTraceSelection?

    private let reportRepository: any HealthReportCompletionRepositoryProtocol
    private let reviewRepository: any HealthReportReviewRepositoryProtocol
    private let localOriginalStore: any HealthReportLocalOriginalStoreProtocol
    private let currentAccountScope: @MainActor () -> String?
    private let now: @MainActor () -> Date
    private let calendar: Calendar
    private var context: Context?
    private var generation = 0
    private var openGeneration = 0
    private var localOriginalAcknowledgementTask: Task<Void, Never>?
    #if DEBUG
    private var supersededLocalOriginalAcknowledgementTasks: [Task<Void, Never>] = []
    #endif

    init(
        reportRepository: any HealthReportCompletionRepositoryProtocol = HealthReportCompletionRepository(),
        reviewRepository: any HealthReportReviewRepositoryProtocol = HealthDataRepository(),
        localOriginalStore: any HealthReportLocalOriginalStoreProtocol = HealthReportLocalOriginalStore.shared,
        currentAccountScope: @escaping @MainActor () -> String? = { AuthManager.shared.accountScope },
        now: @escaping @MainActor () -> Date = Date.init,
        calendar: Calendar = .current
    ) {
        self.reportRepository = reportRepository
        self.reviewRepository = reviewRepository
        self.localOriginalStore = localOriginalStore
        self.currentAccountScope = currentAccountScope
        self.now = now
        self.calendar = calendar
    }

    var latestItem: HealthReportHistoryItem? { items.first }
    var recentItems: [HealthReportHistoryItem] { Array(items.prefix(3)) }

    var contentState: HealthReportDashboardContentState {
        HealthReportDashboardContentState(
            loading: loading,
            hasReport: latestItem != nil,
            hasError: errorMessage != nil
        )
    }

    var dashboardState: HealthReportDashboardState {
        guard let latestItem else { return .processing }
        return HealthReportDashboardState(
            workflowStatus: HealthReportWorkflowStatus(rawValue: latestItem.status)
        )
    }

    var originalFileCount: Int { latestTrace?.assets.count ?? latestLocalOriginals.count }

    var indicatorCount: Int {
        if let latestInterpretation { return latestInterpretation.structured_additions.count }
        return latestTrace?.candidates.count ?? 0
    }

    var abnormalCount: Int { latestInterpretation?.major_abnormalities.count ?? 0 }

    var summary: String {
        guard let latestItem else { return "上传报告后，这里会显示最新解析状态和指标汇总。" }
        let status = HealthReportWorkflowStatus(rawValue: latestItem.status)
        switch status {
        case .completed, .completedScorePending:
            if indicatorCount == 0 {
                return "报告已经完成解析，当前没有可展示的已确认结构化指标。"
            }
            return "已完成 \(indicatorCount) 项指标解析，其中 \(abnormalCount) 项需要关注；原始文件和确认记录均可回看。"
        case .awaitingConfirmation:
            return "字段识别已经完成，等待你核对后正式写入可信健康数据。"
        case .committing:
            return "报告字段已经确认，系统正在写入可信健康数据和确认记录。"
        case .failed:
            return "原始文件已保存，但本次解析未完成。打开报告可查看原因并继续处理。"
        case .unknown:
            return "报告原件已保存，当前处理状态暂时无法确认；可稍后刷新或先查看本机原件。"
        default:
            return "原始文件已安全保存，系统正在解析指标、单位和参考范围。"
        }
    }

    var latestActionTitle: String {
        switch dashboardState {
        case .processing: return "查看解析进度"
        case .awaiting: return "核对报告字段"
        case .committing: return "查看入库进度"
        case .completed: return "查看报告解读"
        case .failed: return "查看问题与原件"
        case .unknown: return "查看报告与原件"
        }
    }

    /// 读取最近一年报告；服务端返回顺序是最新报告的唯一权威顺序。
    func load(subjectUserID: Int?, accountScope: String?) async {
        generation &+= 1
        invalidateLocalOriginalAcknowledgementRetry()
        let requestedGeneration = generation
        guard let subjectUserID,
              let accountScope,
              !accountScope.isEmpty,
              currentAccountScope() == accountScope else {
            reset()
            errorMessage = "当前账号无法读取健康报告，请重新登录后重试。"
            return
        }

        let requestedContext = Context(subjectUserID: subjectUserID, accountScope: accountScope)
        if context != requestedContext {
            reset()
            context = requestedContext
        }
        loading = true
        errorMessage = nil
        detailWarning = nil
        defer {
            if generation == requestedGeneration { loading = false }
        }

        do {
            let today = now()
            let from = calendar.date(byAdding: .year, value: -1, to: today) ?? today
            let history = try await reportRepository.fetchHistory(
                subjectUserID: subjectUserID,
                dateFrom: Self.dayString(from),
                dateTo: Self.dayString(today),
                hospital: nil,
                reportType: nil,
                expectedAccountScope: accountScope
            )
            guard isCurrent(requestedGeneration, requestedContext) else { return }
            items = history.items
            latestTrace = nil
            latestInterpretation = nil
            latestLocalOriginals = []
            startLocalOriginalAcknowledgementRetry(
                history.items,
                context: requestedContext,
                requestedGeneration: requestedGeneration
            )

            guard let latest = history.items.first else { return }
            await loadLatestDetails(
                latest,
                context: requestedContext,
                requestedGeneration: requestedGeneration
            )
        } catch {
            guard isCurrent(requestedGeneration, requestedContext) else { return }
            errorMessage = error.localizedDescription
        }
    }

    /// 打开一份历史报告的服务器追踪详情；账号变化时结果直接丢弃。
    func open(_ item: HealthReportHistoryItem) async {
        guard let context, currentAccountScope() == context.accountScope else {
            errorMessage = "账号已切换，请重新打开健康报告。"
            return
        }
        openGeneration &+= 1
        let requestedOpenGeneration = openGeneration
        let requestedLoadGeneration = generation
        traceLoadingWorkflowID = item.workflow_id
        defer {
            if isCurrentOpen(
                item: item,
                context: context,
                loadGeneration: requestedLoadGeneration,
                openGeneration: requestedOpenGeneration
            ) {
                traceLoadingWorkflowID = nil
            }
        }
        do {
            let trace: HealthReportTrace
            if item.workflow_id == latestItem?.workflow_id, let latestTrace {
                trace = latestTrace
            } else {
                trace = try await reportRepository.fetchTrace(
                    workflowID: item.workflow_id,
                    subjectUserID: context.subjectUserID,
                    expectedAccountScope: context.accountScope
                )
            }
            guard isCurrentOpen(
                      item: item,
                      context: context,
                      loadGeneration: requestedLoadGeneration,
                      openGeneration: requestedOpenGeneration
                  ),
                  trace.workflow.id == item.workflow_id else { return }
            selectedTrace = XAgeReportTraceSelection(
                item: item,
                trace: trace,
                subjectUserID: context.subjectUserID,
                accountScope: context.accountScope
            )
        } catch {
            let serverError = error
            guard isCurrentOpen(
                item: item,
                context: context,
                loadGeneration: requestedLoadGeneration,
                openGeneration: requestedOpenGeneration
            ) else { return }
            do {
                let originals = try await localOriginalStore.listAssets(
                    workflowID: item.workflow_id,
                    accountScope: context.accountScope,
                    subjectUserID: context.subjectUserID
                )
                guard isCurrentOpen(
                    item: item,
                    context: context,
                    loadGeneration: requestedLoadGeneration,
                    openGeneration: requestedOpenGeneration
                ) else { return }
                guard !originals.isEmpty else {
                    errorMessage = serverError.localizedDescription
                    return
                }
                selectedTrace = .localOriginal(
                    item: item,
                    assets: originals,
                    subjectUserID: context.subjectUserID,
                    accountScope: context.accountScope
                )
                errorMessage = nil
            } catch {
                guard isCurrentOpen(
                    item: item,
                    context: context,
                    loadGeneration: requestedLoadGeneration,
                    openGeneration: requestedOpenGeneration
                ) else { return }
                errorMessage = serverError.localizedDescription
            }
        }
    }

    private func loadLatestDetails(
        _ item: HealthReportHistoryItem,
        context: Context,
        requestedGeneration: Int
    ) async {
        do {
            let trace = try await reportRepository.fetchTrace(
                workflowID: item.workflow_id,
                subjectUserID: context.subjectUserID,
                expectedAccountScope: context.accountScope
            )
            guard isCurrent(requestedGeneration, context), trace.workflow.id == item.workflow_id else { return }
            latestTrace = trace
        } catch {
            guard isCurrent(requestedGeneration, context) else { return }
            do {
                let originals = try await localOriginalStore.listAssets(
                    workflowID: item.workflow_id,
                    accountScope: context.accountScope,
                    subjectUserID: context.subjectUserID
                )
                guard isCurrent(requestedGeneration, context) else { return }
                latestLocalOriginals = originals
                detailWarning = originals.isEmpty
                    ? "报告详情暂时无法读取，下拉即可重试。"
                    : "报告详情暂时无法读取，本机原件仍可查看。"
            } catch {
                guard isCurrent(requestedGeneration, context) else { return }
                detailWarning = "报告详情暂时无法读取，下拉即可重试。"
            }
        }

        let status = HealthReportWorkflowStatus(rawValue: item.status)
        guard status == .completed || status == .completedScorePending else { return }
        do {
            let interpretation = try await reviewRepository.fetchReportInterpretation(
                workflowID: item.workflow_id,
                subjectUserID: context.subjectUserID
            )
            guard isCurrent(requestedGeneration, context),
                  interpretation.workflow_id == item.workflow_id,
                  interpretation.subject_user_id == context.subjectUserID else { return }
            latestInterpretation = interpretation
        } catch {
            guard isCurrent(requestedGeneration, context) else { return }
            detailWarning = latestLocalOriginals.isEmpty
                ? "报告已完成，但解读摘要暂时无法读取，下拉即可重试。"
                : "报告解读暂时无法读取，本机原件仍可查看。"
        }
    }

    /// 后台重试本机原件 ACK；读取报告列表和页面加载均不等待该任务。
    ///
    /// 只有同时存在于当前历史列表及本机 workflow 绑定中的报告才会发送。每次跨 actor
    /// 等待后都重新校验账号、主体和加载代次，阻断账号切换及 ABA 后的旧请求。
    private func startLocalOriginalAcknowledgementRetry(
        _ historyItems: [HealthReportHistoryItem],
        context: Context,
        requestedGeneration: Int
    ) {
        guard !historyItems.isEmpty else { return }
        localOriginalAcknowledgementTask = Task { @MainActor [weak self] in
            guard let self else { return }
            var visitedWorkflowIDs: Set<Int> = []
            for item in historyItems where visitedWorkflowIDs.insert(item.workflow_id).inserted {
                guard self.isCurrentAcknowledgementRetry(requestedGeneration, context) else {
                    return
                }

                let proof: HealthReportLocalOriginalBindingProof
                do {
                    proof = try await self.localOriginalStore.bindingProof(
                        workflowID: item.workflow_id,
                        accountScope: context.accountScope,
                        subjectUserID: context.subjectUserID
                    )
                } catch {
                    // 没有本机绑定证明的历史报告不发送 ACK，也不影响正常页面展示。
                    continue
                }
                guard self.isCurrentAcknowledgementRetry(requestedGeneration, context) else {
                    return
                }

                do {
                    let result = try await self.reportRepository.acknowledgeLocalOriginal(
                        workflowID: item.workflow_id,
                        request: HealthReportLocalOriginalAcknowledgementRequest(
                            subject_user_id: context.subjectUserID,
                            client_request_id: proof.clientRequestID,
                            contract_version: proof.contractVersion,
                            asset_count: proof.assetCount,
                            aggregate_sha256: proof.aggregateSHA256
                        ),
                        expectedAccountScope: context.accountScope
                    )
                    guard self.isCurrentAcknowledgementRetry(requestedGeneration, context) else {
                        return
                    }
                    guard result.workflow_id == item.workflow_id,
                          result.contract_version == proof.contractVersion,
                          result.accepted else {
                        continue
                    }
                } catch let APIError.httpError(statusCode, _) where statusCode == 409 {
                    // 精确重复 workflow 不具备服务器原件退休资格；保留服务器副本且不污染 UI。
                    continue
                } catch let APIError.httpErrorResponse(statusCode, _, _) where statusCode == 409 {
                    // 兼容包含响应正文的 409 表达，处理语义与普通 409 一致。
                    continue
                } catch is CancellationError {
                    return
                } catch {
                    // 网络、旧后端或其他临时失败均保持 fail-safe：服务器继续保存原件，下次加载再试。
                    continue
                }
            }
        }
    }

    private func isCurrentAcknowledgementRetry(
        _ requestedGeneration: Int,
        _ requestedContext: Context
    ) -> Bool {
        !Task.isCancelled && isCurrent(requestedGeneration, requestedContext)
    }

    private func invalidateLocalOriginalAcknowledgementRetry() {
        guard let task = localOriginalAcknowledgementTask else { return }
        task.cancel()
        #if DEBUG
        supersededLocalOriginalAcknowledgementTasks.append(task)
        #endif
        localOriginalAcknowledgementTask = nil
    }

    #if DEBUG
    /// 测试专用：确定性等待本次 Dashboard 启动的 ACK 重试退出。
    func waitForLocalOriginalAcknowledgementRetryForTesting() async {
        await localOriginalAcknowledgementTask?.value
    }

    /// 测试专用：等待账号或加载代次切换前启动的 ACK 重试真正退出。
    func waitForSupersededLocalOriginalAcknowledgementRetriesForTesting() async {
        let tasks = supersededLocalOriginalAcknowledgementTasks
        supersededLocalOriginalAcknowledgementTasks.removeAll()
        for task in tasks {
            await task.value
        }
    }
    #endif

    private func isCurrent(_ requestedGeneration: Int, _ requestedContext: Context) -> Bool {
        generation == requestedGeneration
            && context == requestedContext
            && currentAccountScope() == requestedContext.accountScope
    }

    private func isCurrentOpen(
        item: HealthReportHistoryItem,
        context: Context,
        loadGeneration: Int,
        openGeneration: Int
    ) -> Bool {
        generation == loadGeneration
            && self.openGeneration == openGeneration
            && self.context == context
            && traceLoadingWorkflowID == item.workflow_id
            && currentAccountScope() == context.accountScope
    }

    private func reset() {
        openGeneration &+= 1
        loading = false
        traceLoadingWorkflowID = nil
        items = []
        latestTrace = nil
        latestInterpretation = nil
        latestLocalOriginals = []
        selectedTrace = nil
        detailWarning = nil
        context = nil
    }

    private static func dayString(_ date: Date) -> String {
        let formatter = DateFormatter()
        formatter.calendar = Calendar(identifier: .gregorian)
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = .current
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter.string(from: date)
    }

    private struct Context: Equatable {
        let subjectUserID: Int
        let accountScope: String
    }
}

/// 参考健康报告设计稿实现的单页仪表板；上传只能从底部唯一按钮触发。
struct XAgeHealthReportDashboardView: View {
    @ObservedObject var viewModel: HealthReportDashboardViewModel
    let subjectUserID: Int?
    let accountScope: String?
    let uploading: Bool
    let uploadStage: String
    let onClose: () -> Void
    let onUpload: () -> Void
    let onShowAllHistory: () -> Void

    var body: some View {
        ZStack {
            XAgeLiquidBackground().ignoresSafeArea()

            ScrollView {
                LazyVStack(alignment: .leading, spacing: 16) {
                    header
                    latestReportSection
                    attentionSection
                    historySection
                }
                .padding(.horizontal, 20)
                .padding(.top, 10)
                .padding(.bottom, 16)
            }
            .scrollIndicators(.hidden)
            .refreshable { await reload() }
            .accessibilityIdentifier("xage.panel.reports.scroll")
        }
        .safeAreaInset(edge: .bottom) {
            uploadButton
                .padding(.horizontal, 20)
                .padding(.top, 8)
                .padding(.bottom, 10)
                .background(.ultraThinMaterial)
        }
        .task(id: reloadIdentity) { await reload() }
    }

    private var header: some View {
        HStack(alignment: .top, spacing: 12) {
            Button(action: onClose) {
                Image(systemName: "chevron.left")
                    .font(.headline.weight(.bold))
            }
            .buttonStyle(.bordered)
            .buttonBorderShape(.circle)
            .accessibilityLabel("返回")

            VStack(alignment: .leading, spacing: 4) {
                Text("健康报告")
                    .font(.largeTitle.weight(.bold))
                    .foregroundStyle(Color(hex: "123E67"))
                Text("上传、整理与查看")
                    .font(.title3)
                    .foregroundStyle(Color(hex: "5D7890"))
            }
            Spacer(minLength: 0)
        }
    }

    @ViewBuilder
    private var latestReportSection: some View {
        switch viewModel.contentState {
        case .loading:
            reportCard {
                HStack(spacing: 12) {
                    ProgressView()
                    Text("正在读取最新报告…")
                        .font(.body.weight(.semibold))
                        .foregroundStyle(Color(hex: "496A83"))
                }
                .frame(maxWidth: .infinity, minHeight: 150)
            }
        case .available:
            if let item = viewModel.latestItem {
                reportCard {
                    latestHeader(item)
                    summaryMetrics
                    Text(viewModel.summary)
                        .font(.subheadline)
                        .foregroundStyle(Color(hex: "5D7890"))
                        .fixedSize(horizontal: false, vertical: true)

                    if let warning = viewModel.detailWarning {
                        Label(warning, systemImage: "exclamationmark.triangle.fill")
                            .font(.caption)
                            .foregroundStyle(Color(hex: "B46B25"))
                    }

                    Button {
                        Task { await viewModel.open(item) }
                    } label: {
                        HStack {
                            if viewModel.traceLoadingWorkflowID == item.workflow_id {
                                ProgressView().tint(.white)
                            }
                            Text(viewModel.latestActionTitle)
                            Image(systemName: "chevron.right")
                        }
                        .font(.body.weight(.bold))
                        .foregroundStyle(.white)
                        .frame(maxWidth: .infinity, minHeight: 50)
                        .background(reportGradient, in: Capsule())
                    }
                    .buttonStyle(.plain)
                    .disabled(viewModel.traceLoadingWorkflowID != nil)
                    .accessibilityIdentifier("xage.report.dashboard.latest.open")
                }
                .accessibilityElement(children: .contain)
                .accessibilityIdentifier("xage.report.dashboard.latest")
            }
        case .failed:
            reportCard {
                ContentUnavailableView(
                    "健康报告暂时无法读取",
                    systemImage: "exclamationmark.arrow.triangle.2.circlepath",
                    description: Text("请检查网络后重试；读取失败不代表账号中没有报告。")
                )
                .frame(maxWidth: .infinity, minHeight: 170)
            }
        case .empty:
            reportCard {
                ContentUnavailableView(
                    "暂无健康报告",
                    systemImage: "doc.text.magnifyingglass",
                    description: Text("点击底部“上传新报告”，开始保存和解析报告。")
                )
                .frame(maxWidth: .infinity, minHeight: 170)
            }
        }

        if let error = viewModel.errorMessage {
            Button { Task { await reload() } } label: {
                Label("读取失败，点击重试：\(error)", systemImage: "arrow.clockwise.circle.fill")
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(Color(hex: "B94E61"))
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding()
                    .background(Color(hex: "FFF0F3").opacity(0.86), in: RoundedRectangle(cornerRadius: 18))
            }
            .buttonStyle(.plain)
        }
    }

    private func latestHeader(_ item: HealthReportHistoryItem) -> some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: "doc.text.fill")
                .font(.title2.weight(.bold))
                .foregroundStyle(.white)
                .frame(width: 48, height: 48)
                .background(reportGradient, in: Circle())

            VStack(alignment: .leading, spacing: 4) {
                Text(item.title)
                    .font(.title3.weight(.bold))
                    .foregroundStyle(Color(hex: "173F64"))
                    .lineLimit(2)
                Text(item.xAgeHistoryMetadataLabel)
                    .font(.subheadline)
                    .foregroundStyle(Color(hex: "6C8194"))
                    .lineLimit(2)
            }
            Spacer(minLength: 4)
            Label(viewModel.dashboardState.title, systemImage: viewModel.dashboardState.icon)
                .font(.caption.weight(.bold))
                .foregroundStyle(viewModel.dashboardState.color)
                .padding(.horizontal, 10)
                .frame(minHeight: 30)
                .background(XAgeCapsuleFill())
                .labelStyle(.titleAndIcon)
        }
    }

    private var summaryMetrics: some View {
        HStack(spacing: 8) {
            metricCell(value: "\(viewModel.originalFileCount)", label: "原始文件")
            metricCell(value: "\(viewModel.indicatorCount)", label: viewModel.dashboardState == .completed ? "已解析指标" : "识别候选")
            metricCell(value: "\(viewModel.abnormalCount)", label: "需要关注", emphasized: viewModel.abnormalCount > 0)
        }
    }

    @ViewBuilder
    private var attentionSection: some View {
        if viewModel.dashboardState == .completed {
            reportCard {
                Text("需要关注")
                    .font(.title3.weight(.bold))
                    .foregroundStyle(Color(hex: "173F64"))
                let abnormalities = viewModel.latestInterpretation?.major_abnormalities ?? []
                if abnormalities.isEmpty {
                    Label("当前没有需要关注的已确认指标", systemImage: "checkmark.circle.fill")
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(Color(hex: "149C8F"))
                        .padding(.vertical, 8)
                } else {
                    ForEach(abnormalities.prefix(3)) { item in
                        HStack(spacing: 10) {
                            Image(systemName: "exclamationmark.circle.fill")
                                .foregroundStyle(Color(hex: "F58A2A"))
                            VStack(alignment: .leading, spacing: 2) {
                                Text(item.canonical_name).font(.body.weight(.semibold))
                                Text(observationValue(item)).font(.caption).foregroundStyle(.secondary)
                            }
                            Spacer()
                            Text("需关注")
                                .font(.caption.weight(.bold))
                                .foregroundStyle(Color(hex: "D76A18"))
                        }
                        .padding(.vertical, 7)
                    }
                }
            }
        }
    }

    private var historySection: some View {
        reportCard {
            HStack {
                VStack(alignment: .leading, spacing: 3) {
                    Text("历史报告")
                        .font(.title3.weight(.bold))
                        .foregroundStyle(Color(hex: "173F64"))
                    Text("近一年 · 共 \(viewModel.items.count) 份")
                        .font(.caption)
                        .foregroundStyle(Color(hex: "6C8194"))
                }
                Spacer()
            }

            if viewModel.items.isEmpty {
                Text("暂无近一年报告记录")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, minHeight: 70)
            } else {
                ForEach(viewModel.recentItems) { item in
                    Button {
                        Task { await viewModel.open(item) }
                    } label: {
                        HStack(spacing: 12) {
                            Image(systemName: "doc.text.fill")
                                .font(.body.weight(.bold))
                                .foregroundStyle(Color(hex: "2F86E5"))
                                .frame(width: 34, height: 34)
                                .background(Color(hex: "EAF4FF"), in: RoundedRectangle(cornerRadius: 10))
                            VStack(alignment: .leading, spacing: 3) {
                                Text(item.title)
                                    .font(.body.weight(.semibold))
                                    .foregroundStyle(Color(hex: "173F64"))
                                    .lineLimit(1)
                                Text(item.xAgeHistoryMetadataLabel)
                                    .font(.caption)
                                    .foregroundStyle(Color(hex: "6C8194"))
                                    .lineLimit(1)
                            }
                            Spacer(minLength: 4)
                            if viewModel.traceLoadingWorkflowID == item.workflow_id {
                                ProgressView().controlSize(.small)
                            } else {
                                Image(systemName: "chevron.right")
                                    .font(.caption.weight(.bold))
                                    .foregroundStyle(Color(hex: "7D9AB1"))
                            }
                        }
                        .contentShape(Rectangle())
                        .frame(minHeight: 54)
                    }
                    .buttonStyle(.plain)
                    .disabled(viewModel.traceLoadingWorkflowID != nil)
                    .accessibilityIdentifier("xage.report.dashboard.history.workflow.\(item.workflow_id)")
                }

                Button(action: onShowAllHistory) {
                    HStack(spacing: 6) {
                        Text("查看全部 \(viewModel.items.count) 份")
                        Image(systemName: "chevron.right")
                    }
                    .font(.body.weight(.semibold))
                    .foregroundStyle(Color(hex: "1675D1"))
                    .frame(maxWidth: .infinity, minHeight: 44)
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("xage.report.dashboard.history.all")
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("xage.report.dashboard.history")
    }

    private var uploadButton: some View {
        Button(action: onUpload) {
            HStack(spacing: 10) {
                if uploading { ProgressView().tint(.white) }
                Image(systemName: uploading ? "arrow.up.doc.fill" : "doc.badge.plus")
                Text(uploading ? (uploadStage.isEmpty ? "正在上传…" : uploadStage) : "上传新报告")
                    .lineLimit(1)
                    .minimumScaleFactor(0.78)
            }
            .font(.title3.weight(.bold))
            .foregroundStyle(.white)
            .frame(maxWidth: .infinity, minHeight: 56)
            .background(reportGradient, in: Capsule())
            .shadow(color: Color(hex: "20CDB1").opacity(0.24), radius: 14, y: 7)
        }
        .buttonStyle(.plain)
        .disabled(uploading)
        .accessibilityIdentifier("xage.panel.reports.primary")
    }

    private func reportCard<Content: View>(@ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 14, content: content)
            .padding(18)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(XAgeGlassCardBackground(cornerRadius: 26))
    }

    private func metricCell(value: String, label: String, emphasized: Bool = false) -> some View {
        VStack(spacing: 3) {
            Text(value)
                .font(.title2.weight(.bold))
                .foregroundStyle(emphasized ? Color(hex: "F07D22") : Color(hex: "1675D1"))
            Text(label)
                .font(.caption)
                .foregroundStyle(Color(hex: "6C8194"))
                .lineLimit(1)
                .minimumScaleFactor(0.78)
        }
        .frame(maxWidth: .infinity, minHeight: 66)
        .background(Color.white.opacity(0.5), in: RoundedRectangle(cornerRadius: 18))
    }

    private func observationValue(_ item: HealthReportObservation) -> String {
        if let value = item.value_numeric {
            return "\(value.formatted()) \(item.unit ?? "")".trimmingCharacters(in: .whitespaces)
        }
        return item.value_text ?? item.reference_text ?? "已确认异常"
    }

    private var reportGradient: LinearGradient {
        LinearGradient(
            colors: [Color(hex: "1677EA"), Color(hex: "28C9B6")],
            startPoint: .leading,
            endPoint: .trailing
        )
    }

    /// 家庭成员切换可能不改变登录账号，因此账号和报告主体必须共同驱动重新加载与代次失效。
    private var reloadIdentity: ReloadIdentity {
        ReloadIdentity(subjectUserID: subjectUserID, accountScope: accountScope)
    }

    private func reload() async {
        await viewModel.load(subjectUserID: subjectUserID, accountScope: accountScope)
    }

    private struct ReloadIdentity: Equatable {
        let subjectUserID: Int?
        let accountScope: String?
    }
}
