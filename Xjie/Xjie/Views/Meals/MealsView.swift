import ImageIO
import PhotosUI
import SwiftUI
import UIKit

/// Trusted dietary-record surface. Every input source creates a pending draft;
/// only the explicit confirmation sheet can create a formal record.
@MainActor
struct MealsView: View {
    @StateObject private var viewModel: MealsViewModel
    @Environment(\.scenePhase) private var scenePhase
    private let initialEntry: DietaryEntryHandoff?
    @State private var presentedSheet: DietarySheet?
    @State private var queuedSheet: DietarySheet?
    @State private var showCamera = false
    @State private var photoPickerPresented = false
    @State private var selectedPhoto: PhotosPickerItem?
    @State private var pendingCameraDraft: DietaryMealDraft?
    @State private var pendingPickerLaunch: DietaryPickerLaunch?
    @State private var cameraCoverDidDismiss = true
    @State private var didApplyInitialEntry = false

    init() {
        initialEntry = nil
        _viewModel = StateObject(wrappedValue: MealsViewModel())
    }

    init(initialEntry: DietaryEntryHandoff) {
        self.initialEntry = initialEntry
        _viewModel = StateObject(wrappedValue: MealsViewModel())
    }

    init(viewModel: MealsViewModel) {
        initialEntry = nil
        _viewModel = StateObject(wrappedValue: viewModel)
    }

    var body: some View {
        ScrollView {
            LazyVStack(spacing: 16) {
                pageHeader
                overviewCards
                dateSwitcher
                stateBanner
                summaryCard
                selectedDaySummaryCard
                mealsCard
                weeklyReviewCard
            }
            .padding(.horizontal, 16)
            .padding(.top, 12)
            .padding(.bottom, 24)
        }
        .scrollDismissesKeyboard(.interactively)
        .background(Color.appBackground.ignoresSafeArea())
        .navigationTitle(String(localized: "dietary.title", defaultValue: "膳食记录"))
        .navigationBarTitleDisplayMode(.inline)
        .safeAreaInset(edge: .bottom, spacing: 0) {
            recordMealButton
        }
        .overlay {
            if viewModel.loading && !viewModel.hasContent {
                ProgressView(String(localized: "common.loading", defaultValue: "加载中..."))
                    .padding(22)
                    .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
                    .accessibilityIdentifier("dietary.loading")
            }
        }
        .task {
            await viewModel.fetchData()
            presentInitialEntryIfNeeded()
        }
        .onChange(of: scenePhase) { _, phase in
            guard phase == .active else { return }
            Task { await viewModel.fetchData() }
        }
        .refreshable { await viewModel.fetchData() }
        .photosPicker(
            isPresented: $photoPickerPresented,
            selection: $selectedPhoto,
            matching: .images
        )
        .onChange(of: selectedPhoto) { _, item in
            guard let item else { return }
            Task {
                defer { selectedPhoto = nil }
                guard let data = try? await item.loadTransferable(type: Data.self) else {
                    viewModel.errorMessage = String(
                        localized: "dietary.error.photoRequired",
                        defaultValue: "没有读取到可用的餐食照片"
                    )
                    return
                }
                if let draft = await viewModel.createPhotoDraft(
                    data,
                    fileName: "meal-library-source",
                    source: .photoLibrary
                ) {
                    presentedSheet = .draft(draft)
                }
            }
        }
        .sheet(item: $presentedSheet, onDismiss: presentQueuedSheet) { sheet in
            sheetContent(sheet)
        }
        .fullScreenCover(isPresented: $showCamera, onDismiss: {
            cameraCoverDidDismiss = true
            presentCameraDraftIfNeeded()
        }) {
            CameraImagePicker(
                onPick: { data, name in
                    showCamera = false
                    Task {
                        let draft = await viewModel.createPhotoDraft(
                            data,
                            fileName: name,
                            source: .camera
                        )
                        if let draft {
                            pendingCameraDraft = draft
                            presentCameraDraftIfNeeded()
                        }
                    }
                },
                onCancel: { showCamera = false }
            )
            .ignoresSafeArea()
        }
        .alert(
            String(localized: "common.error", defaultValue: "错误"),
            isPresented: Binding(
                get: { viewModel.errorMessage != nil },
                set: { if !$0 { viewModel.clearError() } }
            )
        ) {
            Button(String(localized: "common.ok", defaultValue: "确定"), role: .cancel) {
                viewModel.clearError()
            }
        } message: {
            Text(viewModel.errorMessage ?? "")
        }
    }

    private var pageHeader: some View {
        HStack(spacing: 14) {
            ZStack {
                Circle()
                    .fill(
                        LinearGradient(
                            colors: [Color.appGradientStart, Color.appGradientEnd],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        )
                    )
                    .frame(width: 58, height: 58)
                Image(systemName: "fork.knife")
                    .font(.title2.weight(.bold))
                    .foregroundStyle(.white)
            }
            .accessibilityHidden(true)

            VStack(alignment: .leading, spacing: 4) {
                Text(String(localized: "dietary.title", defaultValue: "膳食记录"))
                    .font(.title2.bold())
                    .foregroundStyle(.primary)
                Text(String(localized: "dietary.subtitle", defaultValue: "记录餐食，了解每天的饮食结构"))
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 0)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("dietary.header")
    }

    private var overviewCards: some View {
        ViewThatFits(in: .horizontal) {
            HStack(spacing: 10) { overviewCardContents }
            VStack(spacing: 10) { overviewCardContents }
        }
        .accessibilityIdentifier("dietary.overview")
    }

    @ViewBuilder
    private var overviewCardContents: some View {
        DietaryOverviewCard(
            title: String(localized: "dietary.overview.recorded", defaultValue: "今日已记录"),
            value: "\(viewModel.recordedMealCount) 餐",
            symbol: "checkmark.circle.fill",
            tint: .appSuccess
        )
        DietaryOverviewCard(
            title: String(localized: "dietary.overview.pending", defaultValue: "待确认"),
            value: "\(viewModel.pendingCount) 项",
            symbol: "exclamationmark.circle.fill",
            tint: viewModel.pendingCount > 0 ? .appWarning : .secondary
        )
        DietaryOverviewCard(
            title: String(localized: "dietary.overview.streak", defaultValue: "连续记录"),
            value: "\(viewModel.streakDays) 天",
            symbol: "calendar.badge.checkmark",
            tint: .appPrimary
        )
    }

    private var dateSwitcher: some View {
        HStack(spacing: 12) {
            Button {
                Task { await viewModel.moveDate(by: -1) }
            } label: {
                Image(systemName: "chevron.left")
                    .frame(width: 44, height: 44)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel(String(localized: "dietary.date.previous", defaultValue: "前一天"))

            VStack(spacing: 2) {
                Text(viewModel.selectedDateDisplayText)
                    .font(.headline)
                    .multilineTextAlignment(.center)
                Text(String(localized: "dietary.date.hint", defaultValue: "凌晨 4 点前默认归入前一饮食日"))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
            }
            .frame(maxWidth: .infinity)

            Button {
                Task { await viewModel.moveDate(by: 1) }
            } label: {
                Image(systemName: "chevron.right")
                    .frame(width: 44, height: 44)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .disabled(!viewModel.canMoveForward)
            .accessibilityLabel(String(localized: "dietary.date.next", defaultValue: "后一天"))
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 8)
        .dietaryCard()
        .accessibilityIdentifier("dietary.dateSwitcher")
    }

    @ViewBuilder
    private var stateBanner: some View {
        if viewModel.isOffline {
            DietaryStatusBanner(
                symbol: "wifi.slash",
                title: String(localized: "dietary.state.offline", defaultValue: "网络暂不可用"),
                detail: String(localized: "dietary.state.offlineDetail", defaultValue: "输入和草稿已保留，恢复网络后可重试。"),
                tint: .appWarning,
                actionTitle: String(localized: "common.retry", defaultValue: "重试")
            ) {
                Task { await viewModel.fetchData() }
            }
        } else if viewModel.dayState == .waitingConfirmation || viewModel.pendingCount > 0 {
            DietaryStatusBanner(
                symbol: "exclamationmark.bubble.fill",
                title: String(localized: "dietary.state.waiting", defaultValue: "有餐食等待确认"),
                detail: String(localized: "dietary.state.waitingDetail", defaultValue: "未确认内容不会进入正式记录和总结。"),
                tint: .appWarning
            )
        } else if viewModel.dayState == .stale || viewModel.dayState == .recalculating {
            DietaryStatusBanner(
                symbol: "arrow.triangle.2.circlepath",
                title: String(localized: "dietary.state.recalculating", defaultValue: "总结需要更新"),
                detail: String(localized: "dietary.state.recalculatingDetail", defaultValue: "历史记录已修改，正在按固定规则重新计算。"),
                tint: .appPrimary
            )
        } else if viewModel.loadState == .failed {
            DietaryStatusBanner(
                symbol: "exclamationmark.triangle.fill",
                title: String(localized: "dietary.state.failed", defaultValue: "暂时无法读取膳食记录"),
                detail: viewModel.errorMessage ?? String(localized: "dietary.error.generic", defaultValue: "请稍后重试"),
                tint: .appDanger,
                actionTitle: String(localized: "common.retry", defaultValue: "重试")
            ) {
                Task { await viewModel.fetchData() }
            }
        }
    }

    private var summaryCard: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Label(viewModel.summaryTitle, systemImage: "chart.bar.doc.horizontal.fill")
                    .font(.headline)
                Spacer()
                if let summary = viewModel.displayedSummary {
                    Text(summary.dietDate)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }

            if let summary = viewModel.displayedSummary, summary.summaryState.canDisplayConclusion {
                if summary.summaryState == .stale || summary.summaryState == .recalculating {
                    Label(
                        String(localized: "dietary.summary.updating", defaultValue: "记录已修改，当前内容正在更新"),
                        systemImage: "arrow.triangle.2.circlepath"
                    )
                    .font(.caption)
                    .foregroundStyle(Color.appWarning)
                }

                VStack(alignment: .leading, spacing: 6) {
                    Text(String(localized: "dietary.summary.structure", defaultValue: "饮食结构"))
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.secondary)
                    Text(summary.structureConclusion ?? String(localized: "dietary.summary.noConclusion", defaultValue: "暂无结构结论"))
                        .font(.body.weight(.semibold))
                        .fixedSize(horizontal: false, vertical: true)
                }

                if let suggestion = summary.actionSuggestion, !suggestion.isEmpty {
                    HStack(alignment: .top, spacing: 10) {
                        Image(systemName: "leaf.fill")
                            .foregroundStyle(Color.appSuccess)
                        VStack(alignment: .leading, spacing: 3) {
                            Text(String(localized: "dietary.summary.todayAction", defaultValue: "今天可以做"))
                                .font(.caption.weight(.semibold))
                                .foregroundStyle(.secondary)
                            Text(suggestion)
                                .font(.body)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                    .padding(12)
                    .background(Color.appSuccess.opacity(0.09), in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                }

                HStack {
                    Label(
                        confidenceText(summary.summaryConfidence),
                        systemImage: "checkmark.seal"
                    )
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    Spacer()
                    Button(String(localized: "dietary.summary.evidence", defaultValue: "查看依据")) {
                        presentedSheet = .evidence(summary)
                    }
                    .font(.subheadline.weight(.semibold))
                    .frame(minHeight: 44)
                }
            } else {
                let message = summaryEmptyMessage
                HStack(alignment: .top, spacing: 12) {
                    Image(systemName: message.symbol)
                        .foregroundStyle(message.tint)
                    VStack(alignment: .leading, spacing: 4) {
                        Text(message.title)
                            .font(.body.weight(.semibold))
                        Text(message.detail)
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                .padding(.vertical, 4)
            }
        }
        .padding(16)
        .dietaryCard()
        .accessibilityIdentifier("dietary.summary")
    }

    @ViewBuilder
    private var selectedDaySummaryCard: some View {
        if viewModel.isSelectedToday,
           let summary = viewModel.selectedDaySummary,
           summary.summaryState.canDisplayConclusion {
            VStack(alignment: .leading, spacing: 12) {
                Label(
                    String(localized: "dietary.summary.todayCompleted", defaultValue: "今日已完成总结"),
                    systemImage: "checkmark.seal.fill"
                )
                .font(.headline)
                .foregroundStyle(Color.appSuccess)

                Text(summary.conclusion)
                    .font(.body.weight(.semibold))
                    .fixedSize(horizontal: false, vertical: true)

                if !summary.todaySuggestion.isEmpty {
                    Text(summary.todaySuggestion)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }

                HStack {
                    Label(confidenceText(summary.summaryConfidence), systemImage: "checkmark.seal")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Spacer()
                    Button(String(localized: "dietary.summary.evidence", defaultValue: "查看依据")) {
                        presentedSheet = .evidence(summary)
                    }
                    .font(.subheadline.weight(.semibold))
                    .frame(minHeight: 44)
                }
            }
            .padding(16)
            .dietaryCard()
            .accessibilityIdentifier("dietary.selectedDaySummary")
        }
    }

    private var mealsCard: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Label(
                    viewModel.isSelectedToday
                        ? String(localized: "dietary.meals.today", defaultValue: "今日餐食")
                        : String(localized: "dietary.meals.selected", defaultValue: "当日餐食"),
                    systemImage: "fork.knife"
                )
                .font(.headline)
                Spacer()
                Text("\(viewModel.recordedMealCount) 餐")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
            }

            ForEach(visibleMealTypes, id: \.rawValue) { type in
                mealTypeSection(type)
                if type != visibleMealTypes.last { Divider() }
            }

            if viewModel.isSelectedToday {
                Button {
                    presentedSheet = .completion
                } label: {
                    Label(
                        String(localized: "dietary.complete.title", defaultValue: "完成今天记录"),
                        systemImage: "checkmark.circle"
                    )
                    .font(.subheadline.weight(.semibold))
                    .frame(minHeight: 44)
                }
                .buttonStyle(.plain)
                .foregroundStyle(Color.appPrimary)
                .disabled(viewModel.recordedMealCount == 0 || viewModel.isMutating)
                .accessibilityHint(String(localized: "dietary.complete.hint", defaultValue: "只汇总已经确认的餐食"))
                .accessibilityIdentifier("dietary.completeDay")
            }
        }
        .padding(16)
        .dietaryCard()
        .accessibilityIdentifier("dietary.meals")
    }

    private var weeklyReviewCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            Label(String(localized: "dietary.weekly.title", defaultValue: "本周饮食回顾"), systemImage: "calendar")
                .font(.headline)

            if let review = viewModel.weeklyReview {
                Text(String(format: String(localized: "dietary.weekly.completeness", defaultValue: "最近 7 天有 %d 天记录完整"), review.completeDays))
                    .font(.body.weight(.semibold))
                ForEach(review.insights, id: \.self) { insight in
                    Label(insight, systemImage: "circle.fill")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                        .symbolRenderingMode(.monochrome)
                }
            } else {
                Text(String(localized: "dietary.weekly.empty", defaultValue: "记录几天后，这里会按结构趋势回顾，不做综合好坏评分。"))
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(16)
        .dietaryCard()
        .accessibilityIdentifier("dietary.weekly")
    }

    private var recordMealButton: some View {
        Button {
            presentedSheet = .sources
        } label: {
            Label(String(localized: "dietary.record", defaultValue: "记录一餐"), systemImage: "plus.circle.fill")
                .font(.headline)
                .frame(maxWidth: .infinity, minHeight: 52)
                .foregroundStyle(.white)
                .background(
                    LinearGradient(
                        colors: [Color.appGradientStart, Color.appGradientEnd],
                        startPoint: .leading,
                        endPoint: .trailing
                    ),
                    in: RoundedRectangle(cornerRadius: 16, style: .continuous)
                )
                .contentShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
        }
        .buttonStyle(.plain)
        .disabled(viewModel.isMutating)
        .padding(.horizontal, 16)
        .padding(.top, 10)
        .padding(.bottom, 8)
        .background(.ultraThinMaterial)
        .accessibilityIdentifier("dietary.recordMeal")
    }

    @ViewBuilder
    private func mealTypeSection(_ type: DietaryMealType) -> some View {
        let records = viewModel.records.filter { $0.mealType == type }
        let drafts = viewModel.pendingDrafts.filter { $0.mealType == type }
        VStack(alignment: .leading, spacing: 10) {
            Label(type.title, systemImage: type.symbol)
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(.primary)

            if records.isEmpty && drafts.isEmpty {
                Text(String(localized: "dietary.meals.unrecorded", defaultValue: "尚未记录"))
                    .font(.subheadline)
                    .foregroundStyle(.tertiary)
                    .padding(.leading, 2)
            } else {
                ForEach(records) { record in
                    Button {
                        presentedSheet = .record(record)
                    } label: {
                        DietaryRecordRow(record: record)
                    }
                    .buttonStyle(.plain)
                    .frame(minHeight: 52)
                    .accessibilityIdentifier("dietary.record.\(record.recordID)")
                }
                ForEach(drafts) { draft in
                    Button {
                        viewModel.activateDraft(draft)
                        presentedSheet = .draft(draft)
                    } label: {
                        DietaryDraftRow(draft: draft)
                    }
                    .buttonStyle(.plain)
                    .frame(minHeight: 52)
                    .accessibilityIdentifier("dietary.draft.\(draft.draftID)")
                }
            }
        }
    }

    private var visibleMealTypes: [DietaryMealType] {
        var types: [DietaryMealType] = [.breakfast, .lunch, .dinner]
        if viewModel.records.contains(where: { $0.mealType == .snack })
            || viewModel.pendingDrafts.contains(where: { $0.mealType == .snack }) {
            types.append(.snack)
        }
        return types
    }

    private var summaryEmptyMessage: (symbol: String, title: String, detail: String, tint: Color) {
        if viewModel.displayedSummary?.summaryState == .waitingConfirmation || viewModel.dayState == .waitingConfirmation {
            return (
                "hourglass",
                String(localized: "dietary.summary.waiting", defaultValue: "等待餐食确认"),
                String(localized: "dietary.summary.waitingDetail", defaultValue: "处理待确认项后才会生成总结；未确认内容不会被推断。"),
                .appWarning
            )
        }
        return (
            "doc.text.magnifyingglass",
            String(localized: "dietary.summary.insufficient", defaultValue: "记录不足，暂不生成结论"),
            String(localized: "dietary.summary.insufficientDetail", defaultValue: "自动结束至少需要两个不同餐次；也可以手动按已确认内容完成。"),
            .secondary
        )
    }

    @ViewBuilder
    private func sheetContent(_ sheet: DietarySheet) -> some View {
        switch sheet {
        case .sources:
            DietarySourcePicker { source in
                switch source {
                case .camera:
                    queuePickerLaunch(.camera)
                case .photoLibrary:
                    queuePickerLaunch(.photoLibrary)
                case .text, .voice:
                    transitionFromSheet(to: .description(source, initialText: nil))
                case .recent:
                    transitionFromSheet(to: .recent)
                default:
                    break
                }
            }
        case .description(let source, let initialText):
            DietaryDescriptionEntryView(
                source: source,
                initialText: initialText ?? viewModel.preservedDraftInput
            ) { text in
                let draft = await viewModel.createDescriptionDraft(text, source: source)
                if let draft { transitionFromSheet(to: .draft(draft)) }
                return draft != nil
            }
        case .draft(let draft):
            DietaryDraftEditorView(
                draft: draft,
                onRetryRecognition: { currentDraft in
                    await viewModel.retryRecognition(currentDraft)
                },
                onConfirm: { editable in
                    let record = await viewModel.confirmDraft(editable)
                    if record != nil { presentedSheet = nil }
                    return record != nil
                }
            )
        case .record(let record):
            DietaryRecordEditorView(
                record: record,
                onSave: { editable in
                    let updated = await viewModel.updateRecord(editable)
                    if updated != nil { presentedSheet = nil }
                    return updated != nil
                },
                onReuse: {
                    let draft = await viewModel.reuseRecord(record)
                    if let draft { transitionFromSheet(to: .draft(draft)) }
                    return draft != nil
                },
                onDelete: {
                    let deleted = await viewModel.deleteRecord(record)
                    if deleted { presentedSheet = nil }
                    return deleted
                }
            )
        case .completion:
            DietaryCompletionView(
                records: viewModel.records,
                drafts: viewModel.pendingDrafts
            ) {
                _ = await viewModel.completeSelectedDayWithConfirmedRecords()
                if viewModel.lastCompletionAccepted { presentedSheet = nil }
                return viewModel.lastCompletionAccepted
            }
        case .recent:
            DietaryRecentMealsView(
                records: viewModel.recentRecords,
                isLoading: viewModel.isMutating,
                onLoad: { await viewModel.fetchRecentRecords() },
                onSelect: { record in
                    let draft = await viewModel.reuseRecord(record)
                    if let draft { transitionFromSheet(to: .draft(draft)) }
                }
            )
        case .evidence(let summary):
            DietaryEvidenceView(summary: summary)
        }
    }

    private func transitionFromSheet(to next: DietarySheet? = nil, action: (() -> Void)? = nil) {
        queuedSheet = next
        presentedSheet = nil
        action?()
    }

    private func presentQueuedSheet() {
        if let queuedSheet {
            self.queuedSheet = nil
            presentedSheet = queuedSheet
            return
        }
        if let pendingPickerLaunch {
            self.pendingPickerLaunch = nil
            switch pendingPickerLaunch {
            case .camera:
                cameraCoverDidDismiss = false
                showCamera = true
            case .photoLibrary:
                photoPickerPresented = true
            }
            return
        }
        presentCameraDraftIfNeeded()
    }

    private func presentCameraDraftIfNeeded() {
        guard DietaryCameraDraftPresentationGate.canPresent(
            coverDidDismiss: cameraCoverDidDismiss,
            hasPendingDraft: pendingCameraDraft != nil,
            hasActiveSheet: presentedSheet != nil
        ), let pendingCameraDraft else { return }
        self.pendingCameraDraft = nil
        presentedSheet = .draft(pendingCameraDraft)
    }

    private func queuePickerLaunch(_ launch: DietaryPickerLaunch) {
        pendingPickerLaunch = launch
        presentedSheet = nil
    }

    private func presentInitialEntryIfNeeded() {
        guard !didApplyInitialEntry, let initialEntry else { return }
        didApplyInitialEntry = true
        presentedSheet = .description(initialEntry.source, initialText: initialEntry.draftText)
    }

    private func confidenceText(_ confidence: Double?) -> String {
        guard let confidence else {
            return String(localized: "dietary.confidence.unavailable", defaultValue: "置信度待补充")
        }
        return String(
            format: String(localized: "dietary.confidence.value", defaultValue: "总结置信度 %.0f%%"),
            confidence * 100
        )
    }
}

struct DietaryPhotoUploadPayload: Equatable, Sendable {
    let data: Data
    let fileName: String
    let mimeType: String
}

enum DietaryPhotoUploadNormalizer {
    static let maximumUploadBytes = 9 * 1024 * 1024

    /// PhotosPicker may return HEIC/HEIF or PNG bytes. The dietary multipart
    /// contract currently sends JPEG, so the bytes, extension, and MIME must
    /// be normalized together instead of relabelling the original asset.
    static func prepare(_ sourceData: Data) -> DietaryPhotoUploadPayload? {
        guard let source = CGImageSourceCreateWithData(sourceData as CFData, nil) else { return nil }
        for maximumPixelSize in [4_096, 3_072, 2_048] {
            let options: [CFString: Any] = [
                kCGImageSourceCreateThumbnailFromImageAlways: true,
                kCGImageSourceCreateThumbnailWithTransform: true,
                kCGImageSourceThumbnailMaxPixelSize: maximumPixelSize,
                kCGImageSourceShouldCacheImmediately: true,
            ]
            guard let thumbnail = CGImageSourceCreateThumbnailAtIndex(source, 0, options as CFDictionary) else {
                continue
            }
            let image = UIImage(cgImage: thumbnail)
            for quality in [0.9, 0.78, 0.66, 0.54] {
                guard let jpeg = image.jpegData(compressionQuality: quality) else { continue }
                if jpeg.count <= maximumUploadBytes {
                    return DietaryPhotoUploadPayload(
                        data: jpeg,
                        fileName: "meal-library.jpg",
                        mimeType: "image/jpeg"
                    )
                }
            }
        }
        return nil
    }
}

private enum DietarySheet: Identifiable {
    case sources
    case description(DietaryEntrySource, initialText: String?)
    case draft(DietaryMealDraft)
    case record(DietaryMealRecord)
    case completion
    case recent
    case evidence(DietaryDailySummary)

    var id: String {
        switch self {
        case .sources: return "sources"
        case .description(let source, _): return "description-\(source.rawValue)"
        case .draft(let draft): return "draft-\(draft.draftID)"
        case .record(let record): return "record-\(record.recordID)"
        case .completion: return "completion"
        case .recent: return "recent"
        case .evidence(let summary): return "evidence-\(summary.dietDate)"
        }
    }
}

private enum DietaryPickerLaunch {
    case camera
    case photoLibrary
}

private struct DietaryOverviewCard: View {
    let title: String
    let value: String
    let symbol: String
    let tint: Color

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: symbol)
                .foregroundStyle(tint)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Text(value)
                    .font(.headline)
                    .foregroundStyle(.primary)
            }
            Spacer(minLength: 0)
        }
        .padding(12)
        .frame(maxWidth: .infinity, minHeight: 68)
        .dietaryCard()
        .accessibilityElement(children: .combine)
    }
}

private struct DietaryStatusBanner: View {
    let symbol: String
    let title: String
    let detail: String
    let tint: Color
    var actionTitle: String?
    var action: (() -> Void)?

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: symbol)
                .foregroundStyle(tint)
                .frame(width: 24, height: 24)
            VStack(alignment: .leading, spacing: 4) {
                Text(title).font(.subheadline.weight(.semibold))
                Text(detail)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 4)
            if let actionTitle, let action {
                Button(actionTitle, action: action)
                    .font(.subheadline.weight(.semibold))
                    .frame(minHeight: 44)
            }
        }
        .padding(14)
        .background(tint.opacity(0.09), in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous).stroke(tint.opacity(0.18)))
    }
}

private struct DietaryRecordRow: View {
    let record: DietaryMealRecord

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: record.mealType.symbol)
                .foregroundStyle(Color.appPrimary)
                .frame(width: 36, height: 36)
                .background(Color.appPrimary.opacity(0.1), in: Circle())
            VStack(alignment: .leading, spacing: 4) {
                Text(record.foodSummary.isEmpty
                    ? String(localized: "dietary.food.unnamed", defaultValue: "未命名餐食")
                    : record.foodSummary)
                    .font(.subheadline.weight(.semibold))
                    .lineLimit(2)
                HStack(spacing: 6) {
                    Text(DietaryDateText.time(record.eatenAt))
                    Text("·")
                    Text(record.status.title)
                }
                .font(.caption)
                .foregroundStyle(.secondary)
            }
            Spacer(minLength: 4)
            Image(systemName: "chevron.right")
                .font(.caption.weight(.semibold))
                .foregroundStyle(.tertiary)
        }
        .contentShape(Rectangle())
        .accessibilityElement(children: .combine)
        .accessibilityHint(String(localized: "dietary.record.detailHint", defaultValue: "查看、修改、删除或复用这餐"))
    }
}

private struct DietaryDraftRow: View {
    let draft: DietaryMealDraft

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: draft.recognitionFailed ? "exclamationmark.triangle.fill" : "hourglass")
                .foregroundStyle(Color.appWarning)
                .frame(width: 36, height: 36)
                .background(Color.appWarning.opacity(0.1), in: Circle())
            VStack(alignment: .leading, spacing: 4) {
                Text(draft.foodItems.map(\.name).filter { !$0.isEmpty }.joined(separator: "、").nilIfEmpty
                    ?? String(localized: "dietary.draft.manualFill", defaultValue: "识别未完成，请手动补充"))
                    .font(.subheadline.weight(.semibold))
                    .lineLimit(2)
                Text(String(localized: "dietary.status.pending", defaultValue: "待确认 · 不会进入正式记录"))
                    .font(.caption)
                    .foregroundStyle(Color.appWarning)
            }
            Spacer(minLength: 4)
            Image(systemName: "chevron.right")
                .font(.caption.weight(.semibold))
                .foregroundStyle(.tertiary)
        }
        .contentShape(Rectangle())
        .accessibilityElement(children: .combine)
    }
}

private struct DietarySourcePicker: View {
    let onSelect: (DietaryEntrySource) -> Void
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 12) {
                    Text(String(localized: "dietary.source.help", defaultValue: "无论从哪里开始，都要先核对日期、餐次、食物和份量，确认后才会保存。"))
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.bottom, 4)

                    ForEach(DietaryEntrySource.userFacingSources, id: \.rawValue) { source in
                        Button {
                            onSelect(source)
                        } label: {
                            HStack(spacing: 14) {
                                Image(systemName: source.symbol)
                                    .font(.title3.weight(.semibold))
                                    .foregroundStyle(Color.appPrimary)
                                    .frame(width: 44, height: 44)
                                    .background(Color.appPrimary.opacity(0.1), in: Circle())
                                Text(source.title)
                                    .font(.body.weight(.semibold))
                                    .foregroundStyle(.primary)
                                Spacer()
                                Image(systemName: "chevron.right")
                                    .foregroundStyle(.tertiary)
                            }
                            .padding(.horizontal, 14)
                            .frame(minHeight: 64)
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        .dietaryCard()
                        .accessibilityIdentifier("dietary.source.\(source.rawValue)")
                    }
                }
                .padding(16)
            }
            .background(Color.appBackground)
            .navigationTitle(String(localized: "dietary.record", defaultValue: "记录一餐"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(String(localized: "common.cancel", defaultValue: "取消")) { dismiss() }
                }
            }
        }
        .presentationDetents([.medium, .large])
    }
}

private struct DietaryDescriptionEntryView: View {
    let source: DietaryEntrySource
    let onRecognize: (String) async -> Bool
    @State private var text: String
    @State private var isSubmitting = false
    @FocusState private var focused: Bool
    @Environment(\.dismiss) private var dismiss

    init(
        source: DietaryEntrySource,
        initialText: String,
        onRecognize: @escaping (String) async -> Bool
    ) {
        self.source = source
        self.onRecognize = onRecognize
        _text = State(initialValue: initialText)
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    if source == .voice {
                        Label(
                            String(localized: "dietary.voice.systemDictation", defaultValue: "点击系统键盘上的麦克风说话，识别文字可继续修改。"),
                            systemImage: "waveform"
                        )
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                        .padding(12)
                        .background(Color.appPrimary.opacity(0.08), in: RoundedRectangle(cornerRadius: 14))
                    }

                    Text(String(localized: "dietary.description.label", defaultValue: "这餐吃了什么"))
                        .font(.headline)
                    TextEditor(text: $text)
                        .focused($focused)
                        .font(.body)
                        .frame(minHeight: 150, maxHeight: 260)
                        .padding(10)
                        .background(Color(.secondarySystemBackground), in: RoundedRectangle(cornerRadius: 14))
                        .overlay(RoundedRectangle(cornerRadius: 14).stroke(Color(.separator).opacity(0.35)))
                        .accessibilityLabel(String(localized: "dietary.description.placeholder", defaultValue: "例如：午餐吃了番茄炒蛋、半碗米饭和一份青菜"))
                        .accessibilityIdentifier("dietary.description.input")

                    Text(String(localized: "dietary.description.estimateNotice", defaultValue: "下一步会形成可编辑的识别草稿；估算内容会明确标注，未经确认不会保存。"))
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)

                    Button {
                        focused = false
                        isSubmitting = true
                        Task {
                            let succeeded = await onRecognize(text)
                            isSubmitting = false
                            if succeeded { dismiss() }
                        }
                    } label: {
                        HStack {
                            if isSubmitting { ProgressView().tint(.white) }
                            Text(String(localized: "dietary.description.review", defaultValue: "识别并核对"))
                                .font(.headline)
                        }
                        .frame(maxWidth: .infinity, minHeight: 50)
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(Color.appPrimary)
                    .disabled(text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || isSubmitting)
                    .accessibilityIdentifier("dietary.description.review")
                }
                .padding(16)
            }
            .scrollDismissesKeyboard(.interactively)
            .navigationTitle(source.title)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(String(localized: "common.cancel", defaultValue: "取消")) {
                        focused = false
                        dismiss()
                    }
                }
                ToolbarItemGroup(placement: .keyboard) {
                    Spacer()
                    Button(String(localized: "common.done", defaultValue: "完成")) { focused = false }
                }
            }
        }
        .interactiveDismissDisabled(isSubmitting)
        .onDisappear { focused = false }
    }
}

private struct DietaryDraftEditorView: View {
    let onRetryRecognition: (DietaryMealDraft) async -> DietaryMealDraft?
    let onConfirm: (DietaryEditableDraft) async -> Bool
    @State private var editable: DietaryEditableDraft
    @State private var dietDate: Date
    @State private var eatenAt: Date
    @State private var isSubmitting = false
    @State private var isRetrying = false
    @State private var recognitionRetryMessage: String?
    @State private var showDiscard = false
    @FocusState private var focused: Bool
    @Environment(\.dismiss) private var dismiss

    init(
        draft: DietaryMealDraft,
        onRetryRecognition: @escaping (DietaryMealDraft) async -> DietaryMealDraft?,
        onConfirm: @escaping (DietaryEditableDraft) async -> Bool
    ) {
        self.onRetryRecognition = onRetryRecognition
        self.onConfirm = onConfirm
        let editable = DietaryEditableDraft(draft)
        _editable = State(initialValue: editable)
        _dietDate = State(initialValue: DietaryDateText.date(editable.dietDate) ?? Date())
        _eatenAt = State(initialValue: DietaryDateText.timestamp(editable.eatenAt) ?? Date())
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    Label(
                        String(localized: "dietary.confirm.notice", defaultValue: "确认前不会写入正式餐食记录"),
                        systemImage: "checkmark.shield"
                    )
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(Color.appPrimary)

                    if editable.original.recognitionFailed {
                        VStack(alignment: .leading, spacing: 10) {
                            Label(
                                String(localized: "dietary.recognition.failed", defaultValue: "自动识别未完成"),
                                systemImage: "exclamationmark.triangle.fill"
                            )
                            .font(.subheadline.weight(.semibold))
                            .foregroundStyle(Color.appWarning)

                            Text(editable.original.canRetryRecognition
                                ? String(
                                    localized: "dietary.recognition.failedDetail",
                                    defaultValue: "可以重新识别，也可以直接在下方手动填写。草稿不会自动进入正式记录。"
                                )
                                : String(
                                    localized: "dietary.recognition.manualDetail",
                                    defaultValue: "原始描述已经保留，请直接在下方手动填写。草稿不会自动进入正式记录。"
                                ))
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)

                            if editable.original.canRetryRecognition {
                                Button {
                                    focused = false
                                    isRetrying = true
                                    recognitionRetryMessage = nil
                                    Task {
                                        let retried = await onRetryRecognition(editable.original)
                                        isRetrying = false
                                        guard let retried else {
                                            recognitionRetryMessage = String(
                                                localized: "dietary.recognition.retryPreserved",
                                                defaultValue: "重新识别未完成，草稿和手动内容仍已保留。"
                                            )
                                            return
                                        }

                                        let next = editable.mergingRecognitionRetry(retried)
                                        if retried.recognitionFailed {
                                            recognitionRetryMessage = String(
                                                localized: "dietary.recognition.retryPreserved",
                                                defaultValue: "重新识别未完成，草稿和手动内容仍已保留。"
                                            )
                                        }
                                        editable = next
                                    }
                                } label: {
                                    HStack(spacing: 8) {
                                        if isRetrying { ProgressView() }
                                        Text(String(localized: "dietary.recognition.retry", defaultValue: "重新识别"))
                                    }
                                    .frame(minHeight: 44)
                                }
                                .buttonStyle(.bordered)
                                .disabled(isRetrying || isSubmitting)
                                .accessibilityIdentifier("dietary.recognition.retry")
                            }

                            if let recognitionRetryMessage {
                                Text(recognitionRetryMessage)
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                                    .fixedSize(horizontal: false, vertical: true)
                                    .accessibilityIdentifier("dietary.recognition.retryMessage")
                            }
                        }
                        .padding(14)
                        .background(Color.appWarning.opacity(0.08), in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                        .overlay(
                            RoundedRectangle(cornerRadius: 14, style: .continuous)
                                .stroke(Color.appWarning.opacity(0.22))
                        )
                    }

                    DietaryMealFieldsForm(
                        dietDate: $dietDate,
                        mealType: $editable.mealType,
                        eatenAt: $eatenAt,
                        foodItems: $editable.foodItems,
                        portionText: $editable.portionText,
                        focused: $focused
                    )

                    if editable.original.recognitionCacheReused {
                        Label(String(localized: "dietary.cache.reused", defaultValue: "已复用同一图片的识别结果"), systemImage: "bolt.horizontal.circle")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }

                    Button {
                        focused = false
                        editable.dietDate = DietaryDateText.dateKey(dietDate)
                        editable.eatenAt = DietaryDateText.timestampString(eatenAt)
                        isSubmitting = true
                        Task {
                            let succeeded = await onConfirm(editable)
                            isSubmitting = false
                            if succeeded { dismiss() }
                        }
                    } label: {
                        HStack {
                            if isSubmitting { ProgressView().tint(.white) }
                            Text(String(localized: "dietary.confirm.save", defaultValue: "确认并保存"))
                                .font(.headline)
                        }
                        .frame(maxWidth: .infinity, minHeight: 50)
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(Color.appPrimary)
                    .disabled(!isValid || isSubmitting || isRetrying)
                    .accessibilityIdentifier("dietary.confirm.save")
                }
                .padding(16)
            }
            .scrollDismissesKeyboard(.interactively)
            .navigationTitle(String(localized: "dietary.confirm.title", defaultValue: "核对餐食"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(String(localized: "common.cancel", defaultValue: "取消")) { showDiscard = true }
                }
                ToolbarItemGroup(placement: .keyboard) {
                    Spacer()
                    Button(String(localized: "common.done", defaultValue: "完成")) { focused = false }
                }
            }
        }
        .interactiveDismissDisabled()
        .alert(String(localized: "dietary.discard.title", defaultValue: "放弃这份草稿？"), isPresented: $showDiscard) {
            Button(String(localized: "common.cancel", defaultValue: "取消"), role: .cancel) {}
            Button(String(localized: "dietary.discard.action", defaultValue: "放弃编辑"), role: .destructive) { dismiss() }
        } message: {
            Text(String(localized: "dietary.discard.message", defaultValue: "草稿仍会保留在待确认列表中，之后可以继续核对。"))
        }
        .onDisappear { focused = false }
    }

    private var isValid: Bool {
        editable.mealType != .unknown
            && editable.foodItems.contains { !$0.name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
    }
}

private struct DietaryRecordEditorView: View {
    let onSave: (DietaryEditableRecord) async -> Bool
    let onReuse: () async -> Bool
    let onDelete: () async -> Bool
    @State private var editable: DietaryEditableRecord
    @State private var dietDate: Date
    @State private var eatenAt: Date
    @State private var isSubmitting = false
    @State private var showDelete = false
    @FocusState private var focused: Bool
    @Environment(\.dismiss) private var dismiss

    init(
        record: DietaryMealRecord,
        onSave: @escaping (DietaryEditableRecord) async -> Bool,
        onReuse: @escaping () async -> Bool,
        onDelete: @escaping () async -> Bool
    ) {
        self.onSave = onSave
        self.onReuse = onReuse
        self.onDelete = onDelete
        let editable = DietaryEditableRecord(record: record)
        _editable = State(initialValue: editable)
        _dietDate = State(initialValue: DietaryDateText.date(editable.dietDate) ?? Date())
        _eatenAt = State(initialValue: DietaryDateText.timestamp(editable.eatenAt) ?? Date())
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    HStack {
                        Label(editable.original.sourceType.title, systemImage: editable.original.sourceType.symbol)
                        Spacer()
                        Text(editable.original.status.title)
                    }
                    .font(.subheadline)
                    .foregroundStyle(.secondary)

                    DietaryMealFieldsForm(
                        dietDate: $dietDate,
                        mealType: $editable.mealType,
                        eatenAt: $eatenAt,
                        foodItems: $editable.foodItems,
                        portionText: $editable.portionText,
                        focused: $focused
                    )

                    Button {
                        focused = false
                        editable.dietDate = DietaryDateText.dateKey(dietDate)
                        editable.eatenAt = DietaryDateText.timestampString(eatenAt)
                        isSubmitting = true
                        Task {
                            let succeeded = await onSave(editable)
                            isSubmitting = false
                            if succeeded { dismiss() }
                        }
                    } label: {
                        Text(String(localized: "common.save", defaultValue: "保存修改"))
                            .font(.headline)
                            .frame(maxWidth: .infinity, minHeight: 50)
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(Color.appPrimary)
                    .disabled(!isValid || isSubmitting)

                    Button {
                        isSubmitting = true
                        Task {
                            let succeeded = await onReuse()
                            isSubmitting = false
                            if succeeded { dismiss() }
                        }
                    } label: {
                        Label(String(localized: "dietary.record.reuse", defaultValue: "复用为新草稿"), systemImage: "arrow.clockwise")
                            .frame(maxWidth: .infinity, minHeight: 46)
                    }
                    .buttonStyle(.bordered)
                    .disabled(isSubmitting)

                    Button(role: .destructive) { showDelete = true } label: {
                        Label(String(localized: "common.delete", defaultValue: "删除"), systemImage: "trash")
                            .frame(maxWidth: .infinity, minHeight: 46)
                    }
                    .buttonStyle(.bordered)
                    .disabled(isSubmitting)
                }
                .padding(16)
            }
            .scrollDismissesKeyboard(.interactively)
            .navigationTitle(String(localized: "dietary.record.detail", defaultValue: "餐食详情"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(String(localized: "common.close", defaultValue: "关闭")) {
                        focused = false
                        dismiss()
                    }
                }
                ToolbarItemGroup(placement: .keyboard) {
                    Spacer()
                    Button(String(localized: "common.done", defaultValue: "完成")) { focused = false }
                }
            }
        }
        .alert(String(localized: "dietary.delete.title", defaultValue: "删除这条餐食记录？"), isPresented: $showDelete) {
            Button(String(localized: "common.cancel", defaultValue: "取消"), role: .cancel) {}
            Button(String(localized: "common.delete", defaultValue: "删除"), role: .destructive) {
                isSubmitting = true
                Task {
                    let succeeded = await onDelete()
                    isSubmitting = false
                    if succeeded { dismiss() }
                }
            }
        } message: {
            Text(String(localized: "dietary.delete.message", defaultValue: "已结束日期的总结会标记为需要更新。"))
        }
        .interactiveDismissDisabled(isSubmitting)
        .onDisappear { focused = false }
    }

    private var isValid: Bool {
        editable.mealType != .unknown
            && editable.foodItems.contains { !$0.name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
    }
}

private struct DietaryMealFieldsForm: View {
    @Binding var dietDate: Date
    @Binding var mealType: DietaryMealType
    @Binding var eatenAt: Date
    @Binding var foodItems: [DietaryFoodItem]
    @Binding var portionText: String
    var focused: FocusState<Bool>.Binding

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Group {
                DatePicker(
                    String(localized: "dietary.field.date", defaultValue: "归属日期"),
                    selection: $dietDate,
                    displayedComponents: .date
                )
                Picker(String(localized: "dietary.field.mealType", defaultValue: "餐次"), selection: $mealType) {
                    ForEach(DietaryMealType.allCases.filter { $0 != .unknown }, id: \.rawValue) { type in
                        Text(type.title).tag(type)
                    }
                }
                DatePicker(
                    String(localized: "dietary.field.time", defaultValue: "进食时间"),
                    selection: $eatenAt,
                    displayedComponents: .hourAndMinute
                )
            }
            .frame(minHeight: 44)

            Divider()
            HStack {
                Text(String(localized: "dietary.field.foods", defaultValue: "食物与份量"))
                    .font(.headline)
                Spacer()
                Button {
                    foodItems.append(DietaryFoodItem(name: ""))
                } label: {
                    Label(String(localized: "dietary.food.add", defaultValue: "添加食物"), systemImage: "plus")
                        .frame(minHeight: 44)
                }
                .font(.subheadline.weight(.semibold))
            }

            ForEach(foodItems.indices, id: \.self) { index in
                VStack(alignment: .leading, spacing: 8) {
                    HStack(spacing: 8) {
                        TextField(String(localized: "dietary.food.name", defaultValue: "食物名称"), text: $foodItems[index].name, axis: .vertical)
                            .lineLimit(1...3)
                            .focused(focused)
                            .textInputAutocapitalization(.never)
                        if foodItems.count > 1 {
                            Button(role: .destructive) {
                                foodItems.remove(at: index)
                            } label: {
                                Image(systemName: "minus.circle.fill")
                                    .frame(width: 44, height: 44)
                                    .contentShape(Rectangle())
                            }
                            .accessibilityLabel(String(localized: "dietary.food.remove", defaultValue: "移除食物"))
                        }
                    }
                    TextField(
                        String(localized: "dietary.food.portion", defaultValue: "大致份量，例如 1 小碗"),
                        text: Binding(
                            get: { foodItems[index].portionText ?? "" },
                            set: { foodItems[index].portionText = $0 }
                        )
                    )
                    .focused(focused)

                    HStack(spacing: 8) {
                        if foodItems[index].isLowConfidence {
                            Label(String(localized: "dietary.confidence.low", defaultValue: "低置信度，请核对"), systemImage: "exclamationmark.triangle.fill")
                                .foregroundStyle(Color.appWarning)
                        }
                        if foodItems[index].isEstimated {
                            Text(String(localized: "dietary.estimated", defaultValue: "估算"))
                                .foregroundStyle(.secondary)
                        }
                    }
                    .font(.caption)
                }
                .padding(12)
                .background(Color(.secondarySystemBackground), in: RoundedRectangle(cornerRadius: 14))
            }

            TextField(
                String(localized: "dietary.field.overallPortion", defaultValue: "整餐份量说明（可选）"),
                text: $portionText,
                axis: .vertical
            )
            .lineLimit(1...4)
            .focused(focused)
            .padding(12)
            .background(Color(.secondarySystemBackground), in: RoundedRectangle(cornerRadius: 14))
        }
    }
}

private struct DietaryCompletionView: View {
    let records: [DietaryMealRecord]
    let drafts: [DietaryMealDraft]
    let onComplete: () async -> Bool
    @State private var submitting = false
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    Text(String(localized: "dietary.complete.question", defaultValue: "今天已经记录完整了吗？"))
                        .font(.title3.bold())
                    Text(String(localized: "dietary.complete.explain", defaultValue: "手动结束适合只吃一餐、轻断食或特殊作息，不要求三餐齐全。"))
                        .font(.subheadline)
                        .foregroundStyle(.secondary)

                    Label("\(records.count) 个已确认餐次将纳入总结", systemImage: "checkmark.circle.fill")
                        .foregroundStyle(Color.appSuccess)
                    if !drafts.isEmpty {
                        Label("\(drafts.count) 个待确认项不会纳入总结，置信度会相应降低", systemImage: "exclamationmark.triangle.fill")
                            .foregroundStyle(Color.appWarning)
                            .fixedSize(horizontal: false, vertical: true)
                    }

                    ForEach(records) { record in
                        HStack {
                            Text(record.mealType.title).fontWeight(.semibold)
                            Spacer()
                            Text(record.foodSummary).foregroundStyle(.secondary).lineLimit(2)
                        }
                        .padding(12)
                        .dietaryCard()
                    }

                    Button {
                        submitting = true
                        Task {
                            let succeeded = await onComplete()
                            submitting = false
                            if succeeded { dismiss() }
                        }
                    } label: {
                        HStack {
                            if submitting { ProgressView().tint(.white) }
                            Text(String(localized: "dietary.complete.confirmedOnly", defaultValue: "按已确认记录完成"))
                                .font(.headline)
                        }
                        .frame(maxWidth: .infinity, minHeight: 50)
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(Color.appPrimary)
                    .disabled(records.isEmpty || submitting)
                }
                .padding(16)
            }
            .navigationTitle(String(localized: "dietary.complete.title", defaultValue: "完成今天记录"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(String(localized: "common.cancel", defaultValue: "取消")) { dismiss() }
                }
            }
        }
        .interactiveDismissDisabled(submitting)
    }
}

private struct DietaryRecentMealsView: View {
    let records: [DietaryMealRecord]
    let isLoading: Bool
    let onLoad: () async -> Void
    let onSelect: (DietaryMealRecord) async -> Void
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            Group {
                if records.isEmpty && isLoading {
                    ProgressView(String(localized: "common.loading", defaultValue: "加载中..."))
                } else if records.isEmpty {
                    ContentUnavailableView(
                        String(localized: "dietary.recent.empty", defaultValue: "暂无最近餐食"),
                        systemImage: "clock.arrow.circlepath",
                        description: Text(String(localized: "dietary.recent.emptyDetail", defaultValue: "确认过的餐食会出现在这里，复用时仍需再次核对。"))
                    )
                } else {
                    List(records) { record in
                        Button {
                            Task { await onSelect(record) }
                        } label: {
                            DietaryRecordRow(record: record)
                        }
                        .buttonStyle(.plain)
                        .frame(minHeight: 52)
                    }
                    .listStyle(.plain)
                }
            }
            .navigationTitle(String(localized: "dietary.source.recent", defaultValue: "最近餐食"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(String(localized: "common.cancel", defaultValue: "取消")) { dismiss() }
                }
            }
            .task { await onLoad() }
        }
    }
}

private struct DietaryEvidenceView: View {
    let summary: DietaryDailySummary
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            List {
                Section(String(localized: "dietary.summary.completeness", defaultValue: "记录完整度")) {
                    LabeledContent(String(localized: "dietary.summary.confirmedMeals", defaultValue: "已确认餐次"), value: "\(summary.confirmedMealCount)")
                    LabeledContent(String(localized: "dietary.overview.pending", defaultValue: "待确认"), value: "\(summary.pendingCount)")
                    LabeledContent(String(localized: "dietary.summary.version", defaultValue: "记录版本"), value: "\(summary.recordVersion)")
                }
                Section(String(localized: "dietary.summary.evidence", defaultValue: "查看依据")) {
                    if summary.evidenceItems.isEmpty {
                        Text(String(localized: "dietary.summary.noEvidence", defaultValue: "暂无可展示依据"))
                            .foregroundStyle(.secondary)
                    } else {
                        ForEach(summary.evidenceItems, id: \.self) { item in
                            Label(item, systemImage: "checkmark.circle")
                        }
                    }
                }
                Section {
                    Text(String(localized: "dietary.summary.rulesNotice", defaultValue: "日常总结由经过审核的固定规则与模板生成，默认不调用大模型。"))
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
            }
            .navigationTitle(String(localized: "dietary.summary.evidence", defaultValue: "总结依据"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button(String(localized: "common.done", defaultValue: "完成")) { dismiss() }
                }
            }
        }
    }
}

private enum DietaryDateText {
    static func date(_ value: String) -> Date? {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.calendar = Calendar(identifier: .gregorian)
        formatter.timeZone = TimeZone.current
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter.date(from: value)
    }

    static func timestamp(_ value: String) -> Date? {
        ISO8601DateFormatter().date(from: value)
    }

    static func dateKey(_ date: Date) -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.calendar = Calendar(identifier: .gregorian)
        formatter.timeZone = TimeZone.current
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter.string(from: date)
    }

    static func timestampString(_ date: Date) -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.calendar = Calendar(identifier: .gregorian)
        formatter.timeZone = TimeZone.current
        formatter.dateFormat = "yyyy-MM-dd'T'HH:mm:ssXXX"
        return formatter.string(from: date)
    }

    static func time(_ value: String) -> String {
        guard let date = timestamp(value) else { return "--:--" }
        let formatter = DateFormatter()
        formatter.locale = Locale.current
        formatter.dateFormat = "HH:mm"
        return formatter.string(from: date)
    }
}

private extension View {
    func dietaryCard() -> some View {
        background(
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .fill(Color(.secondarySystemBackground))
                .overlay(
                    RoundedRectangle(cornerRadius: 18, style: .continuous)
                        .stroke(Color(.separator).opacity(0.18), lineWidth: 0.5)
                )
        )
    }
}

private extension String {
    var nilIfEmpty: String? { isEmpty ? nil : self }
}
