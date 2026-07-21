import SwiftUI

private enum HealthReportManualField: Hashable {
    case name
    case value
    case unit
    case referenceLow
    case referenceHigh
    case referenceText
}

struct HealthReportReviewView: View {
    @Environment(\.dismiss) private var dismiss
    @StateObject private var viewModel: HealthReportReviewViewModel
    @FocusState private var focusedCandidateID: Int?
    @FocusState private var focusedManualField: HealthReportManualField?
    @State private var showDiscardConfirmation = false
    @State private var showManualDiscardConfirmation = false
    @State private var showInterpretation = false

    private let documentTitle: String

    init(
        route: HealthReportWorkflowRoute,
        accountScope: String?,
        documentTitle: String,
        repository: HealthReportReviewRepositoryProtocol = HealthDataRepository()
    ) {
        self.documentTitle = documentTitle
        _viewModel = StateObject(
            wrappedValue: HealthReportReviewViewModel(
                route: route,
                accountScope: accountScope,
                repository: repository
            )
        )
    }

    var body: some View {
        ZStack {
            XAgeLiquidBackground()
                .ignoresSafeArea()

            Color.clear
                .frame(width: 1, height: 1)
                .accessibilityElement(children: .ignore)
                .accessibilityIdentifier("xage.report.review.root")
                .allowsHitTesting(false)

            VStack(spacing: 0) {
                header
                    .padding(.horizontal, 20)
                    .padding(.top, 10)

                ScrollView {
                    // This is a bounded interactive form. Keeping its Toggle/FocusState
                    // controls eagerly mounted avoids SwiftUI's lazy trait/layout feedback
                    // loop when the page is scrolled or snapshotted for accessibility.
                    VStack(alignment: .leading, spacing: 14) {
                        statusCard

                        if viewModel.loading && viewModel.review == nil {
                            loadingCard
                        } else if let review = viewModel.review {
                            candidateSummary(review)
                            candidateList(review)
                            if viewModel.manualEntryAvailable {
                                manualEntryCard
                            }
                            if review.status == .awaitingConfirmation {
                                reportConfirmationCard
                            }
                        } else {
                            unavailableCard
                        }
                    }
                    .padding(.horizontal, 20)
                    .padding(.top, 14)
                    .padding(.bottom, 24)
                }
                .accessibilityIdentifier("xage.report.review.scroll")
                .scrollDismissesKeyboard(.interactively)
                .refreshable { await viewModel.load() }
                .background(
                    Color.clear
                        .contentShape(Rectangle())
                        .onTapGesture {
                            focusedCandidateID = nil
                            focusedManualField = nil
                        }
                )
            }
        }
        .safeAreaInset(edge: .bottom) {
            primaryAction
                .padding(.horizontal, 20)
                .padding(.top, 10)
                .padding(.bottom, 12)
                .background(.ultraThinMaterial)
        }
        .toolbar {
            ToolbarItemGroup(placement: .keyboard) {
                Spacer()
                Button("完成") {
                    focusedCandidateID = nil
                    focusedManualField = nil
                }
                    .accessibilityIdentifier("xage.report.review.keyboard.done")
            }
        }
        .navigationBarBackButtonHidden(true)
        .interactiveDismissDisabled(viewModel.hasUnsavedChanges)
        .task { await viewModel.load() }
        .navigationDestination(isPresented: $showInterpretation) {
            HealthReportInterpretationView(
                viewModel: viewModel,
                documentTitle: documentTitle
            )
        }
        .confirmationDialog(
            "放弃报告复核修改？",
            isPresented: $showDiscardConfirmation,
            titleVisibility: .visible
        ) {
            Button("放弃修改并返回", role: .destructive) {
                viewModel.discardUnsavedChanges()
                dismiss()
            }
            Button("继续复核", role: .cancel) {}
        } message: {
            Text("已选择的字段处理方式、修正值和整份报告勾选尚未提交，离开后需要重新核对。")
        }
        .confirmationDialog(
            "放弃手动补录？",
            isPresented: $showManualDiscardConfirmation,
            titleVisibility: .visible
        ) {
            Button("放弃这次补录", role: .destructive) {
                viewModel.cancelManualEntry()
            }
            Button("继续填写", role: .cancel) {}
        } message: {
            Text("指标名称、数值、单位和参考范围尚未加入待复核列表。")
        }
        .alert(
            viewModel.hasPendingManualCandidateRetry ? "手动补录未完成" : "报告确认未完成",
            isPresented: Binding(
            get: { viewModel.errorMessage != nil },
            set: { if !$0 { viewModel.errorMessage = nil } }
        )) {
            if viewModel.hasPendingManualCandidateRetry {
                Button("同一补录请求重试") {
                    Task { await viewModel.submitManualCandidate() }
                }
                Button("返回修改补录内容") {
                    viewModel.editManualCandidateAgain()
                }
            } else if viewModel.hasPendingRetry {
                Button(viewModel.status == .committing ? "继续完成入库" : "同一请求重试") {
                    Task { await viewModel.submitReportConfirmation() }
                }
                Button("重新读取后修改") {
                    Task { await viewModel.reloadBeforeEditingAgain() }
                }
            } else {
                Button("重新读取") { Task { await viewModel.load() } }
            }
            Button("取消", role: .cancel) {}
        } message: {
            Text(viewModel.errorMessage ?? "")
        }
    }

    private var header: some View {
        HStack(alignment: .center, spacing: 12) {
            Button {
                focusedCandidateID = nil
                focusedManualField = nil
                if viewModel.hasUnsavedChanges {
                    showDiscardConfirmation = true
                } else {
                    dismiss()
                }
            } label: {
                Image(systemName: "chevron.left")
                    .font(.headline.weight(.bold))
                    .foregroundStyle(Color(hex: "347FB7"))
                    .frame(width: 44, height: 44)
                    .background(XAgeCapsuleFill())
            }
            .buttonStyle(.plain)
            .accessibilityLabel("返回报告列表")
            .accessibilityIdentifier("xage.report.review.back")

            VStack(alignment: .leading, spacing: 2) {
                Text("报告字段复核")
                    .font(.headline.weight(.bold))
                    .foregroundStyle(Color(hex: "123E67"))
                Text(documentTitle)
                    .font(.caption)
                    .foregroundStyle(Color(hex: "5D7890"))
                    .lineLimit(2)
            }

            Spacer(minLength: 8)

            Text(viewModel.statusTitle)
                .font(.caption.weight(.bold))
                .foregroundStyle(statusColor)
                .padding(.horizontal, 10)
                .padding(.vertical, 7)
                .background(XAgeCapsuleFill())
                .accessibilityIdentifier("xage.report.review.status")
        }
    }

    private var statusCard: some View {
        VStack(alignment: .leading, spacing: 8) {
            Label(viewModel.statusTitle, systemImage: statusIcon)
                .font(.headline.weight(.bold))
                .foregroundStyle(statusColor)
            Text(viewModel.statusDetail)
                .font(.subheadline)
                .foregroundStyle(Color(hex: "496A83"))
                .lineSpacing(3)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(16)
        .background(XAgeGlassCardBackground(cornerRadius: 24))
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("xage.report.review.statusCard")
    }

    private var loadingCard: some View {
        HStack(spacing: 12) {
            ProgressView()
                .tint(Color(hex: "18AFA7"))
            Text("正在读取识别候选和确认状态…")
                .font(.subheadline.weight(.medium))
                .foregroundStyle(Color(hex: "5D7890"))
        }
        .frame(maxWidth: .infinity, minHeight: 100)
        .padding(16)
        .background(XAgeGlassCardBackground(cornerRadius: 24))
    }

    private var unavailableCard: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("暂时无法读取报告任务")
                .font(.headline.weight(.bold))
                .foregroundStyle(Color(hex: "173F64"))
            Text("下拉刷新或点击底部按钮重试。未读取成功前不会把这份报告标为已入库。")
                .font(.subheadline)
                .foregroundStyle(Color(hex: "6C8194"))
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(16)
        .background(XAgeGlassCardBackground(cornerRadius: 24))
    }

    private func candidateSummary(_ review: HealthReportReview) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("识别结果")
                .font(.headline.weight(.bold))
                .foregroundStyle(Color(hex: "173F64"))
            ViewThatFits(in: .horizontal) {
                HStack(spacing: 8) {
                    summaryBadge("待检查 \(review.pending_review_count)", icon: "exclamationmark.circle.fill")
                    summaryBadge("自动通过 \(review.auto_accepted_count)", icon: "checkmark.circle.fill")
                    summaryBadge("已入库 \(review.admitted_observation_count)", icon: "tray.full.fill")
                }
                VStack(alignment: .leading, spacing: 8) {
                    summaryBadge("待检查 \(review.pending_review_count)", icon: "exclamationmark.circle.fill")
                    summaryBadge("自动通过 \(review.auto_accepted_count)", icon: "checkmark.circle.fill")
                    summaryBadge("已入库 \(review.admitted_observation_count)", icon: "tray.full.fill")
                }
            }
            Text("高置信度正常项可以自动通过字段检查，但整份报告仍需你明确确认。")
                .font(.caption)
                .foregroundStyle(Color(hex: "6C8194"))
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(16)
        .background(XAgeGlassCardBackground(cornerRadius: 24))
    }

    @ViewBuilder
    private func candidateList(_ review: HealthReportReview) -> some View {
        if review.candidates.isEmpty {
            VStack(alignment: .leading, spacing: 8) {
                Text("尚未识别到字段")
                    .font(.headline.weight(.bold))
                    .foregroundStyle(Color(hex: "173F64"))
                Text("如果原图清晰但仍为空，请重新上传或手动补录；不要确认一份没有候选字段的报告。")
                    .font(.subheadline)
                    .foregroundStyle(Color(hex: "6C8194"))
                    .fixedSize(horizontal: false, vertical: true)
            }
            .padding(16)
            .background(XAgeGlassCardBackground(cornerRadius: 24))
        } else {
            ForEach(review.candidates) { candidate in
                HealthReportCandidateReviewCard(
                    candidate: candidate,
                    draft: viewModel.drafts[candidate.candidate_id] ?? .empty,
                    editingLocked: viewModel.editingLocked,
                    focusedCandidateID: $focusedCandidateID,
                    onChoose: { viewModel.choose($0, for: candidate.candidate_id) },
                    onCorrection: { value, unit in
                        viewModel.updateCorrection(
                            candidateID: candidate.candidate_id,
                            value: value,
                            unit: unit
                        )
                    }
                )
            }
        }
    }

    private var reportConfirmationCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("报告级确认")
                .font(.headline.weight(.bold))
                .foregroundStyle(Color(hex: "173F64"))
            Text("这一步确认的是整份报告，而不只是单个字段。确认后才允许把采纳字段写入结构化健康数据。")
                .font(.subheadline)
                .foregroundStyle(Color(hex: "496A83"))
                .fixedSize(horizontal: false, vertical: true)
            Toggle("我已核对原始值、候选/修正值、单位和需要复核的标记", isOn: $viewModel.reportAcknowledged)
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(Color(hex: "173F64"))
                .disabled(viewModel.editingLocked || viewModel.unresolvedCandidateCount > 0)
                .accessibilityIdentifier("xage.report.review.reportAcknowledgement")
            if viewModel.unresolvedCandidateCount > 0 {
                Text("还有 \(viewModel.unresolvedCandidateCount) 项需要选择“确认此值”“修改”或“不采用”。")
                    .font(.caption)
                    .foregroundStyle(Color(hex: "C56A25"))
            }
        }
        .padding(16)
        .background(XAgeGlassCardBackground(cornerRadius: 24))
    }

    private var manualEntryCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .top, spacing: 10) {
                VStack(alignment: .leading, spacing: 4) {
                    Text("手动补录未识别字段")
                        .font(.headline.weight(.bold))
                        .foregroundStyle(Color(hex: "173F64"))
                    Text("补录后仍只是待复核候选，必须逐项检查并确认整份报告后才会入库。")
                        .font(.caption)
                        .foregroundStyle(Color(hex: "6C8194"))
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: 8)
                if !viewModel.manualEntryExpanded {
                    Button("补录") { viewModel.beginManualEntry() }
                        .buttonStyle(.bordered)
                        .accessibilityIdentifier("xage.report.manual.open")
                }
            }

            if viewModel.manualEntryExpanded {
                TextField("指标名称，例如：空腹血糖", text: $viewModel.manualDraft.name)
                    .textFieldStyle(.roundedBorder)
                    .focused($focusedManualField, equals: .name)
                    .disabled(viewModel.manualEntryLocked)
                    .accessibilityIdentifier("xage.report.manual.name")

                TextField("报告中的数值或文字", text: $viewModel.manualDraft.value)
                    .textFieldStyle(.roundedBorder)
                    .focused($focusedManualField, equals: .value)
                    .disabled(viewModel.manualEntryLocked)
                    .accessibilityIdentifier("xage.report.manual.value")

                TextField("单位（可选）", text: $viewModel.manualDraft.unit)
                    .textFieldStyle(.roundedBorder)
                    .focused($focusedManualField, equals: .unit)
                    .disabled(viewModel.manualEntryLocked)
                    .accessibilityIdentifier("xage.report.manual.unit")

                TextField("参考下限（可选数字）", text: $viewModel.manualDraft.referenceLow)
                    .textFieldStyle(.roundedBorder)
                    .keyboardType(.decimalPad)
                    .focused($focusedManualField, equals: .referenceLow)
                    .disabled(viewModel.manualEntryLocked)
                    .accessibilityIdentifier("xage.report.manual.referenceLow")

                TextField("参考上限（可选数字）", text: $viewModel.manualDraft.referenceHigh)
                    .textFieldStyle(.roundedBorder)
                    .keyboardType(.decimalPad)
                    .focused($focusedManualField, equals: .referenceHigh)
                    .disabled(viewModel.manualEntryLocked)
                    .accessibilityIdentifier("xage.report.manual.referenceHigh")

                TextField("其他参考范围说明（可选）", text: $viewModel.manualDraft.referenceText)
                    .textFieldStyle(.roundedBorder)
                    .focused($focusedManualField, equals: .referenceText)
                    .disabled(viewModel.manualEntryLocked)
                    .accessibilityIdentifier("xage.report.manual.referenceText")

                if viewModel.hasPendingManualCandidateRetry {
                    Text("上次请求未确认成功。内容已锁定，重试会复用同一个事件，不会重复生成候选。")
                        .font(.caption)
                        .foregroundStyle(Color(hex: "C56A25"))
                        .fixedSize(horizontal: false, vertical: true)
                }

                HStack(spacing: 10) {
                    Button {
                        focusedManualField = nil
                        Task { await viewModel.submitManualCandidate() }
                    } label: {
                        if viewModel.addingManualCandidate {
                            ProgressView()
                        } else {
                            Text(viewModel.hasPendingManualCandidateRetry ? "同一请求重试" : "加入待复核列表")
                        }
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(!viewModel.canSubmitManualCandidate && !viewModel.hasPendingManualCandidateRetry)
                    .accessibilityIdentifier("xage.report.manual.submit")

                    Button("取消") {
                        focusedManualField = nil
                        if viewModel.manualDraft.hasChanges {
                            showManualDiscardConfirmation = true
                        } else {
                            viewModel.cancelManualEntry()
                        }
                    }
                    .buttonStyle(.bordered)
                    .disabled(viewModel.addingManualCandidate)
                    .accessibilityIdentifier("xage.report.manual.cancel")
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(16)
        .background(XAgeGlassCardBackground(cornerRadius: 24))
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("xage.report.manual.card")
    }

    private var primaryAction: some View {
        Button {
            focusedCandidateID = nil
            focusedManualField = nil
            if viewModel.hasPendingRetry || viewModel.canSubmitReportConfirmation {
                Task { await viewModel.submitReportConfirmation() }
            } else if viewModel.canOpenInterpretation {
                showInterpretation = true
            } else if viewModel.canReloadStatusFromPrimary {
                Task { await viewModel.load() }
            }
        } label: {
            HStack(spacing: 8) {
                if viewModel.submitting {
                    ProgressView()
                        .tint(.white)
                }
                Text(viewModel.primaryButtonTitle)
                    .font(.body.weight(.bold))
                    .multilineTextAlignment(.center)
            }
            .foregroundStyle(.white)
            .frame(maxWidth: .infinity)
            .frame(minHeight: 50)
            .padding(.horizontal, 14)
            .background(
                Capsule()
                    .fill(
                        primaryActionEnabled
                            ? AnyShapeStyle(LinearGradient(colors: [Color(hex: "238AD6"), Color(hex: "20CDB1")], startPoint: .leading, endPoint: .trailing))
                            : AnyShapeStyle(Color(hex: "9BB6C9"))
                    )
            )
        }
        .buttonStyle(.plain)
        .disabled(!primaryActionEnabled)
        .accessibilityIdentifier("xage.report.review.primary")
    }

    private var primaryActionEnabled: Bool {
        viewModel.hasPendingRetry
            || viewModel.canSubmitReportConfirmation
            || viewModel.canOpenInterpretation
            || viewModel.canReloadStatusFromPrimary
    }

    private var statusIcon: String {
        switch viewModel.status {
        case .recognizing, .uploading, .draft: return "doc.text.magnifyingglass"
        case .awaitingConfirmation: return "checklist"
        case .committing: return "tray.and.arrow.down.fill"
        case .completedScorePending: return "clock.badge.checkmark"
        case .completed: return "checkmark.seal.fill"
        case .failed: return "exclamationmark.triangle.fill"
        case .unknown: return "questionmark.circle.fill"
        }
    }

    private var statusColor: Color {
        switch viewModel.status {
        case .failed: return Color(hex: "D85A66")
        case .completed: return Color(hex: "18AFA7")
        case .completedScorePending: return Color(hex: "C57A27")
        default: return Color(hex: "347FB7")
        }
    }

    private func summaryBadge(_ title: String, icon: String) -> some View {
        Label(title, systemImage: icon)
            .font(.caption.weight(.bold))
            .foregroundStyle(Color(hex: "347FB7"))
            .padding(.horizontal, 10)
            .frame(minHeight: 32)
            .background(XAgeCapsuleFill())
    }
}

private struct HealthReportCandidateReviewCard: View {
    let candidate: HealthReportFieldCandidate
    let draft: HealthReportCandidateDraft
    let editingLocked: Bool
    var focusedCandidateID: FocusState<Int?>.Binding
    let onChoose: (HealthReportDecisionAction) -> Void
    let onCorrection: (String, String) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .top, spacing: 10) {
                VStack(alignment: .leading, spacing: 3) {
                    Text(candidate.canonical_name)
                        .font(.headline.weight(.bold))
                        .foregroundStyle(Color(hex: "173F64"))
                    if let rawName = candidate.raw_name,
                       rawName.trimmingCharacters(in: .whitespacesAndNewlines) != candidate.canonical_name {
                        Text("原图名称：\(rawName)")
                            .font(.caption)
                            .foregroundStyle(Color(hex: "6C8194"))
                    }
                }
                Spacer(minLength: 8)
                reviewStatusBadge
            }

            badges

            valueBlock(title: "原始识别", value: candidate.originalValueLabel)
            valueBlock(title: "候选结果", value: candidate.candidateValueLabel)
            valueBlock(title: "参考范围", value: candidate.referenceLabel)
            valueBlock(title: "来源", value: candidate.sourceLocationLabel)

            if !candidate.conflictReasonLabels.isEmpty {
                VStack(alignment: .leading, spacing: 4) {
                    Text("冲突说明")
                        .font(.caption.weight(.bold))
                        .foregroundStyle(Color(hex: "B45B39"))
                    ForEach(candidate.conflictReasonLabels, id: \.self) { reason in
                        Text("• \(reason)")
                            .font(.caption)
                            .foregroundStyle(Color(hex: "6C4A3D"))
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                .padding(10)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(Color(hex: "FFF1E9").opacity(0.82), in: RoundedRectangle(cornerRadius: 14))
            }

            if candidate.requires_review && candidate.review_status == .pendingReview {
                reviewControls
            } else if candidate.review_status == .autoAccepted {
                Text("该字段为服务端判定的高置信度正常项，已自动通过字段检查；仍需完成整份报告确认。")
                    .font(.caption)
                    .foregroundStyle(Color(hex: "496A83"))
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(16)
        .background(XAgeGlassCardBackground(cornerRadius: 24))
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("xage.report.candidate.\(candidate.candidate_id)")
    }

    private var badges: some View {
        ViewThatFits(in: .horizontal) {
            HStack(spacing: 7) { badgeItems }
            VStack(alignment: .leading, spacing: 7) { badgeItems }
        }
    }

    @ViewBuilder
    private var badgeItems: some View {
        if candidate.abnormal_state.lowercased() == "abnormal" {
            flagBadge("异常", icon: "exclamationmark.triangle.fill", color: Color(hex: "C56A25"))
        } else if candidate.abnormal_state.lowercased() == "normal" {
            flagBadge("正常", icon: "checkmark.circle.fill", color: Color(hex: "18AFA7"))
        }
        if candidate.isLowConfidence {
            flagBadge("低置信度", icon: "waveform.badge.exclamationmark", color: Color(hex: "C56A25"))
        }
        if candidate.hasConflict {
            flagBadge("冲突", icon: "arrow.triangle.branch", color: Color(hex: "B45B39"))
        }
        flagBadge(candidate.confidenceLabel, icon: "scope", color: Color(hex: "347FB7"))
    }

    private var reviewStatusBadge: some View {
        Text(reviewStatusTitle)
            .font(.caption2.weight(.bold))
            .foregroundStyle(Color(hex: "347FB7"))
            .padding(.horizontal, 9)
            .frame(minHeight: 28)
            .background(XAgeCapsuleFill())
    }

    private var reviewStatusTitle: String {
        switch candidate.review_status {
        case .pendingReview: return "待检查"
        case .autoAccepted: return "自动通过"
        case .confirmed: return "已确认"
        case .corrected: return "已修正"
        case .rejected: return "未采用"
        case .unknown: return "状态待刷新"
        }
    }

    private var reviewControls: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("选择这项的处理方式")
                .font(.subheadline.weight(.bold))
                .foregroundStyle(Color(hex: "173F64"))

            ViewThatFits(in: .horizontal) {
                HStack(spacing: 8) { decisionButtons }
                VStack(spacing: 8) { decisionButtons }
            }

            if draft.action == .correct {
                ViewThatFits(in: .horizontal) {
                    HStack(spacing: 8) { correctionFields }
                    VStack(spacing: 8) { correctionFields }
                }
            }
        }
    }

    @ViewBuilder
    private var decisionButtons: some View {
        decisionButton("确认此值", action: .confirm, icon: "checkmark")
        decisionButton("修改", action: .correct, icon: "pencil")
        decisionButton("不采用", action: .reject, icon: "xmark")
    }

    @ViewBuilder
    private var correctionFields: some View {
        TextField("修正后的值", text: Binding(
            get: { draft.correctedValue },
            set: { onCorrection($0, draft.correctedUnit) }
        ))
        .textFieldStyle(.plain)
        .font(.body)
        .padding(.horizontal, 12)
        .frame(maxWidth: .infinity, minHeight: 46)
        .background(XAgeCapsuleFill())
        .focused(focusedCandidateID, equals: candidate.candidate_id)
        .disabled(editingLocked)
        .accessibilityIdentifier("xage.report.candidate.\(candidate.candidate_id).correctedValue")

        TextField("单位", text: Binding(
            get: { draft.correctedUnit },
            set: { onCorrection(draft.correctedValue, $0) }
        ))
        .textFieldStyle(.plain)
        .font(.body)
        .padding(.horizontal, 12)
        .frame(minWidth: 100, minHeight: 46)
        .background(XAgeCapsuleFill())
        .disabled(editingLocked)
        .accessibilityIdentifier("xage.report.candidate.\(candidate.candidate_id).correctedUnit")
    }

    private func valueBlock(title: String, value: String) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(title)
                .font(.caption.weight(.bold))
                .foregroundStyle(Color(hex: "6C8194"))
            Text(value)
                .font(.body.weight(.semibold))
                .foregroundStyle(Color(hex: "173F64"))
                .textSelection(.enabled)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(10)
        .background(Color.white.opacity(0.42), in: RoundedRectangle(cornerRadius: 14))
    }

    private func flagBadge(_ title: String, icon: String, color: Color) -> some View {
        Label(title, systemImage: icon)
            .font(.caption2.weight(.bold))
            .foregroundStyle(color)
            .padding(.horizontal, 8)
            .frame(minHeight: 28)
            .background(Color.white.opacity(0.5), in: Capsule())
    }

    private func decisionButton(
        _ title: String,
        action: HealthReportDecisionAction,
        icon: String
    ) -> some View {
        let selected = draft.action == action
        return Button {
            onChoose(action)
        } label: {
            Label(title, systemImage: icon)
                .font(.caption.weight(.bold))
                .foregroundStyle(selected ? .white : Color(hex: "347FB7"))
                .frame(maxWidth: .infinity, minHeight: 44)
                .padding(.horizontal, 8)
                .background(
                    Capsule()
                        .fill(
                            selected
                                ? AnyShapeStyle(LinearGradient(colors: [Color(hex: "238AD6"), Color(hex: "20CDB1")], startPoint: .leading, endPoint: .trailing))
                                : AnyShapeStyle(Color.white.opacity(0.52))
                        )
                )
        }
        .buttonStyle(.plain)
        .disabled(editingLocked)
        .accessibilityIdentifier("xage.report.candidate.\(candidate.candidate_id).\(action.rawValue)")
    }
}
