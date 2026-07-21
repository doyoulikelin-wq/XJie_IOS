import AVFoundation
import Speech
import SwiftUI
import UIKit
import UniformTypeIdentifiers

/// 数据页业务面板模块。
///
/// 负责报告、日常、就医、用药等快捷入口的内容页面，以及报告选择、预览、确认和历史记录。
/// 文件只承载面板与报告工作流，不管理首页数据卡片的排序、同步或评分计算。
enum XAgeDataPanelCategory: String, CaseIterable, Identifiable, Hashable {
    case reports = "报告"
    case daily = "日常"
    case medical = "就医助手"
    case profile = "画像"

    var id: String {
        switch self {
        case .reports: return "reports"
        case .daily: return "daily"
        case .medical: return "medical"
        case .profile: return "profile"
        }
    }

    var headline: String {
        switch self {
        case .reports: return "报告管理"
        case .daily: return "日常同步"
        case .medical: return "就医助手"
        case .profile: return "健康画像"
        }
    }

    var subtitle: String {
        switch self {
        case .reports: return "体检、化验、影像"
        case .daily: return "睡眠、步数、HRV"
        case .medical: return "上传、列表、详情"
        case .profile: return "基础、慢病、过敏"
        }
    }

    var actionTitle: String {
        switch self {
        case .reports: return "上传"
        case .daily: return "查看"
        case .medical: return "查看"
        case .profile: return "完善"
        }
    }

    var iconName: String {
        switch self {
        case .reports: return "doc.text.fill"
        case .daily: return "waveform.path.ecg"
        case .medical: return "cross.case.fill"
        case .profile: return "person.text.rectangle.fill"
        }
    }

    var gradient: [Color] {
        switch self {
        case .reports: return [Color(hex: "238AD6"), Color(hex: "20CDB1")]
        case .daily: return [Color(hex: "18B7D6"), Color(hex: "34D6A6")]
        case .medical: return [Color(hex: "4E8FE9"), Color(hex: "7BD5F1")]
        case .profile: return [Color(hex: "2A79C7"), Color(hex: "6EE4C6")]
        }
    }

    var detailSummary: String {
        switch self {
        case .reports: return "上传体检、化验和影像资料后，先检查识别候选并确认整份报告，再纳入可信健康数据。"
        case .daily: return "聚合睡眠、步数、HRV 和训练负荷，用来解释当天压力、恢复和炎症评分变化。"
        case .medical: return "管理你主动上传的真实就医资料，并在详情中查看原件和资料整理；不替代医生判断。"
        case .profile: return "维护基础资料、慢病、过敏和长期用药，让问答和计划生成更贴近个人状态。"
        }
    }

    fileprivate var rows: [XAgePanelRow] {
        switch self {
        case .reports:
            return [
                XAgePanelRow(icon: "arrow.up.doc.fill", title: "数据上传", subtitle: "体检报告、化验单、影像截图"),
                XAgePanelRow(icon: "doc.text.magnifyingglass", title: "AI 识别队列", subtitle: "抽取指标、异常值和参考范围"),
                XAgePanelRow(icon: "clock.arrow.circlepath", title: "历史报告", subtitle: "单份摘要、异常项和原始资料"),
                XAgePanelRow(icon: "checkmark.seal.fill", title: "需要确认", subtitle: "核对姓名、日期和关键指标")
            ]
        case .daily:
            return [
                XAgePanelRow(icon: "heart.text.square.fill", title: "Apple Health", subtitle: "同步睡眠、步数、静息心率"),
                XAgePanelRow(icon: "waveform.path.ecg", title: "恢复信号", subtitle: "HRV、呼吸率和训练负荷"),
                XAgePanelRow(icon: "chart.line.uptrend.xyaxis", title: "趋势解释", subtitle: "连接日常变化与三项评分")
            ]
        case .medical:
            return [
                XAgePanelRow(icon: "list.clipboard.fill", title: "真实就医资料", subtitle: "上传、列表、详情和原件查看")
            ]
        case .profile:
            return [
                XAgePanelRow(icon: "person.fill", title: "基础资料", subtitle: "年龄、身高、体重和目标"),
                XAgePanelRow(icon: "tag.fill", title: "长期标签", subtitle: "慢病、家族史和风险因素"),
                XAgePanelRow(icon: "exclamationmark.shield.fill", title: "安全信息", subtitle: "过敏、禁忌和长期用药")
            ]
        }
    }
}

/// 业务面板顶部的单项统计展示模型。
struct XAgePanelStat: Identifiable {
    var id: String { title }
    let title: String
    let value: String
    let unit: String
}

private struct XAgePanelRow: Identifiable {
    var id: String { title }
    let icon: String
    let title: String
    let subtitle: String

    var key: String {
        switch title {
        case "数据上传", "拍照上传": return "upload"
        case "AI 识别队列": return "recognition"
        case "历史报告": return "history"
        case "需要确认": return "confirm"
        case "Apple Health": return "apple-health"
        case "恢复信号": return "recovery"
        case "趋势解释": return "trend"
        case "真实就医资料": return "medical-documents"
        case "基础资料": return "basic"
        case "长期标签": return "tags"
        case "安全信息": return "safety"
        default: return title
        }
    }
}

private struct XAgePanelCategoryGlyph: View {
    let category: XAgeDataPanelCategory
    let selected: Bool

    var body: some View {
        ZStack {
            Circle()
                .fill(
                    selected
                    ? AnyShapeStyle(LinearGradient(colors: category.gradient, startPoint: .topLeading, endPoint: .bottomTrailing))
                    : AnyShapeStyle(Color(hex: "B8DFF5").opacity(0.3))
                )
                .overlay(Circle().stroke(.white.opacity(selected ? 0.84 : 0.58), lineWidth: 0.8))

            glyph
                .foregroundStyle(selected ? .white : Color(hex: "347FB7"))
        }
        .accessibilityHidden(true)
    }

    @ViewBuilder
    private var glyph: some View {
        switch category {
        case .reports:
            VStack(spacing: 1.6) {
                ForEach([8.0, 5.8, 7.2], id: \.self) { width in
                    RoundedRectangle(cornerRadius: 1.2, style: .continuous)
                        .frame(width: width, height: 1.8)
                }
            }
        case .daily:
            HStack(alignment: .bottom, spacing: 1.5) {
                ForEach([5.0, 9.0, 6.0, 11.0], id: \.self) { height in
                    RoundedRectangle(cornerRadius: 1.2, style: .continuous)
                        .frame(width: 2, height: height)
                }
            }
        case .medical:
            Image(systemName: "cross.fill")
                .font(.system(size: 8.5, weight: .bold))
        case .profile:
            Image(systemName: "checkmark")
                .font(.system(size: 8.5, weight: .bold))
        }
    }
}

private struct XAgePanelHeroAsset: View {
    let category: XAgeDataPanelCategory

    var body: some View {
        ZStack {
            Circle()
                .fill(LinearGradient(colors: category.gradient, startPoint: .topLeading, endPoint: .bottomTrailing))
                .shadow(color: category.gradient.last?.opacity(0.24) ?? Color(hex: "20CDB1").opacity(0.24), radius: 12, x: 0, y: 7)
            Circle()
                .stroke(.white.opacity(0.42), lineWidth: 1)
                .frame(width: 34, height: 34)
            XAgePanelCategoryGlyph(category: category, selected: true)
                .frame(width: 24, height: 24)
            Image(systemName: category.iconName)
                .font(.system(size: 9, weight: .black))
                .foregroundStyle(.white.opacity(0.92))
                .offset(x: 12, y: -12)
        }
        .frame(width: 48, height: 48)
        .accessibilityHidden(true)
    }
}

private enum XAgeReportUploadAction {
    case camera
    case document
    case photoLibrary
}

struct XAgeReportUploadFile: Identifiable, Equatable {
    let id = UUID()
    let data: Data
    let fileName: String

    var previewImage: UIImage? {
        UIImage(data: data)
    }
}

struct XAgePendingReportUpload: Identifiable, Equatable {
    let id = UUID()
    let title: String
    let source: String
    let files: [XAgeReportUploadFile]

    var totalSizeText: String {
        let totalBytes = files.reduce(0) { $0 + $1.data.count }
        let formatter = ByteCountFormatter()
        formatter.allowedUnits = totalBytes >= 1_000_000 ? [.useMB] : [.useKB]
        formatter.countStyle = .file
        return formatter.string(fromByteCount: Int64(totalBytes))
    }
}

/// 首页业务快捷入口的统一目标页面。
struct XAgePanelDestinationView: View {
    /// 报告、日常、就医或画像分类。
    let category: XAgeDataPanelCategory
    /// 日常页面需要展示的 Apple 健康状态。
    @ObservedObject var appleHealthSync: AppleHealthSyncViewModel
    /// 当前账号的首页服务端只读快照。
    let snapshot: XAgeServerSyncSnapshot
    /// 用户主动同步 Apple 健康的异步动作。
    let onSyncAppleHealth: () async -> Void
    /// 外部容器需要接管关闭行为时提供；为空时使用系统 dismiss。
    var onClose: (() -> Void)?
    @Environment(\.dismiss) private var dismiss
    @EnvironmentObject private var authManager: AuthManager
    @StateObject private var reportUploadVM = HealthReportCompletionViewModel()
    @State private var selectedRowID: String?
    @State private var showCamera = false
    @State private var showPhotoLibrary = false
    @State private var showDocumentPicker = false
    @State private var showReportUploadOptions = false
    @State private var showReportHistory = false
    @State private var pendingUpload: XAgePendingReportUpload?
    @State private var recoveryAssetIndex: Int?
    @State private var uploadQualityWarning: String?
    @State private var reportReviewRoute: HealthReportWorkflowRoute?

    private var activeRow: XAgePanelRow {
        category.rows.first { $0.id == selectedRowID } ?? category.rows[0]
    }

    @ViewBuilder
    var body: some View {
        NavigationStack {
            if category == .profile {
                PatientHistoryView(onClose: onClose)
            } else if category == .medical {
                MedicalRecordListView()
            } else {
                genericPanel
            }
        }
    }

    private var genericPanel: some View {
        ZStack {
            XAgeLiquidBackground()
                .ignoresSafeArea()

            ScrollView {
                VStack(spacing: 16) {
                    header
                        .padding(.top, 18)

                    VStack(alignment: .leading, spacing: 16) {
                        HStack(spacing: 14) {
                            XAgePanelHeroAsset(category: category)
                                .frame(width: 62, height: 62)
                            VStack(alignment: .leading, spacing: 5) {
                                Text(category.headline)
                                    .font(.system(size: 27, weight: .bold))
                                    .foregroundStyle(Color(hex: "123E67"))
                                    .lineLimit(1)
                                    .minimumScaleFactor(0.82)
                                Text(category.subtitle)
                                    .font(.system(size: 14, weight: .semibold))
                                    .foregroundStyle(Color(hex: "5D7890"))
                                    .lineLimit(1)
                            }
                            Spacer(minLength: 0)
                        }

                        Text(category.detailSummary)
                            .font(.system(size: 14))
                            .foregroundStyle(Color(hex: "496A83"))
                            .lineSpacing(3)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    .padding(18)
                    .background(XAgeGlassCardBackground(cornerRadius: 28))

                    HStack(spacing: 9) {
                        ForEach(snapshot.stats(for: category)) { stat in
                            VStack(spacing: 5) {
                                Text(stat.title)
                                    .font(.system(size: 11, weight: .bold))
                                    .foregroundStyle(Color(hex: "6C8194"))
                                    .lineLimit(1)
                                HStack(alignment: .firstTextBaseline, spacing: 2) {
                                    Text(stat.value)
                                        .font(.system(size: 20, weight: .bold))
                                        .foregroundStyle(Color(hex: "12324F"))
                                        .lineLimit(1)
                                        .minimumScaleFactor(0.76)
                                    if !stat.unit.isEmpty {
                                        Text(stat.unit)
                                            .font(.system(size: 10, weight: .semibold))
                                            .foregroundStyle(Color(hex: "6C8194"))
                                    }
                                }
                            }
                            .frame(maxWidth: .infinity)
                            .frame(height: 70)
                            .background(XAgeGlassCardBackground(cornerRadius: 22))
                        }
                    }

                    VStack(spacing: 10) {
                        ForEach(category.rows) { row in
                            let isSelected = activeRow.id == row.id
                            if category == .daily && row.title == "Apple Health" {
                                Button {
                                    select(row)
                                    Task { await onSyncAppleHealth() }
                                } label: {
                                    XAgePanelActionRow(
                                        category: category,
                                        row: row,
                                        trailingTitle: appleHealthSync.isWorking ? nil : appleHealthSync.statusTitle,
                                        showsProgress: appleHealthSync.isWorking,
                                        isSelected: isSelected
                                    )
                                }
                                .buttonStyle(.plain)
                                .disabled(appleHealthSync.isWorking)
                                .accessibilityIdentifier("xage.appleHealth.destination.sync")
                            } else {
                                Button {
                                    select(row)
                                } label: {
                                    XAgePanelActionRow(
                                        category: category,
                                        row: row,
                                        trailingTitle: isSelected ? "查看中" : nil,
                                        isSelected: isSelected
                                    )
                                }
                                .buttonStyle(.plain)
                                .accessibilityIdentifier("xage.panel.\(category.id).row.\(row.key)")
                            }

                            if isSelected {
                                XAgePanelInteractiveDetail(
                                    category: category,
                                    row: activeRow,
                                    snapshot: snapshot,
                                    onReportUploadAction: handleReportUploadAction,
                                    onReportHistoryAction: { showReportHistory = true }
                                )
                                .transition(.opacity.combined(with: .move(edge: .top)))
                            }
                        }
                    }

                    if category == .reports,
                       reportUploadVM.uploading || reportUploadVM.backgroundTaskHint != nil {
                        Button {
                            reportReviewRoute = reportUploadVM.activeReportWorkflow
                        } label: {
                            XAgeChatUploadStatusCard(
                                uploading: reportUploadVM.uploading,
                                title: reportUploadVM.uploading
                                    ? (reportUploadVM.uploadStage.isEmpty ? "正在上传报告…" : reportUploadVM.uploadStage)
                                    : reportUploadVM.activeReportWorkflow == nil ? "报告处理状态" : "查看报告确认任务",
                                subtitle: reportUploadVM.backgroundTaskHint ?? "识别完成后仍需检查字段并确认整份报告。"
                            )
                        }
                        .buttonStyle(.plain)
                        .disabled(reportUploadVM.activeReportWorkflow == nil)
                        .accessibilityIdentifier("xage.panel.reports.upload.status")
                    }

                }
                .padding(.horizontal, 24)
                .padding(.bottom, 18)
            }
            .accessibilityIdentifier("xage.panel.\(category.id).scroll")
            .safeAreaInset(edge: .bottom) {
                primaryActionButton
                    .padding(.horizontal, 24)
                    .padding(.top, 8)
                    .padding(.bottom, 12)
                    .background(
                        LinearGradient(
                            colors: [
                                Color(hex: "E9F8FF").opacity(0),
                                Color(hex: "E9F8FF").opacity(0.92)
                            ],
                            startPoint: .top,
                            endPoint: .bottom
                        )
                        .ignoresSafeArea()
                    )
            }
        }
        .navigationBarBackButtonHidden(true)
        .toolbar(.hidden, for: .navigationBar)
        .fullScreenCover(isPresented: $showCamera) {
            CameraImagePicker(
                onPick: { data, name in
                    preparePendingReportUpload(
                        files: [XAgeReportUploadFile(data: data, fileName: name)],
                        title: "确认数据上传",
                        source: "相机"
                    )
                },
                fileNamePrefix: "xage_panel_report_camera"
            )
            .ignoresSafeArea()
        }
        .sheet(isPresented: $showPhotoLibrary) {
            MultiPhotoPicker(
                selectionLimit: recoveryAssetIndex == nil ? 9 : 1,
                fileNamePrefix: "xage_panel_report_album",
                onPick: { photos in
                    preparePendingReportUpload(
                        files: photos.map { XAgeReportUploadFile(data: $0.data, fileName: $0.fileName) },
                        title: photos.count > 1 ? "确认上传 \(photos.count) 张照片" : "确认相册上传",
                        source: "相册"
                    )
                },
                onError: { message in
                    reportUploadVM.errorMessage = message
                }
            )
        }
        .sheet(isPresented: $showDocumentPicker) {
            DocumentPickerView(
                onPick: { data, fileName in
                    preparePendingReportUpload(
                        files: [XAgeReportUploadFile(data: data, fileName: fileName)],
                        title: "确认上传文件",
                        source: "文件"
                    )
                },
                onError: { message in
                    reportUploadVM.errorMessage = message
                }
            )
        }
        .sheet(isPresented: $showReportUploadOptions) {
            XAgeReportUploadSourceSheet(
                onCamera: { presentReportUploadActionFromOptions(.camera) },
                onDocument: { presentReportUploadActionFromOptions(.document) },
                onPhotoLibrary: { presentReportUploadActionFromOptions(.photoLibrary) }
            )
            .presentationDetents([.height(330)])
            .presentationDragIndicator(.visible)
        }
        .sheet(isPresented: $showReportHistory) {
            XAgeReportHistorySheet()
                .presentationDetents([.large])
                .presentationDragIndicator(.visible)
        }
        .sheet(item: $pendingUpload) { upload in
            XAgeReportUploadConfirmSheet(
                upload: upload,
                isUploading: reportUploadVM.uploading,
                onCancel: { pendingUpload = nil },
                onConfirm: {
                    pendingUpload = nil
                    uploadReports(upload.files, source: upload.source)
                }
            )
            .presentationDetents([.medium, .large])
            .presentationDragIndicator(.visible)
        }
        .navigationDestination(item: $reportReviewRoute) { route in
            HealthReportReviewView(
                route: route,
                accountScope: authManager.accountScope,
                documentTitle: reportUploadVM.activeReportTitle
            )
        }
        .confirmationDialog(
            "检测到可能重复的报告",
            isPresented: Binding(
                get: { reportUploadVM.duplicatePrompt != nil },
                set: { if !$0 { reportUploadVM.deferDuplicateDecision() } }
            ),
            titleVisibility: .visible
        ) {
            Button("使用已有报告") {
                if let prompt = reportUploadVM.duplicatePrompt {
                    Task { await reportUploadVM.decideDuplicate(.useExisting, prompt: prompt) }
                }
            }
            Button("继续新建报告") {
                if let prompt = reportUploadVM.duplicatePrompt {
                    Task { await reportUploadVM.decideDuplicate(.continueNew, prompt: prompt) }
                }
            }
            Button("稍后处理", role: .cancel) {
                reportUploadVM.deferDuplicateDecision()
            }
        } message: {
            Text("系统只提示最相近的一份报告，不会自动覆盖。请选择是否复用已有报告。")
        }
        .alert("拍摄质量不足", isPresented: Binding(
            get: { uploadQualityWarning != nil },
            set: { if !$0 { uploadQualityWarning = nil } }
        )) {
            Button("重新拍摄") { uploadQualityWarning = nil; showCamera = true }
            Button("取消", role: .cancel) { uploadQualityWarning = nil }
        } message: {
            Text(uploadQualityWarning ?? "")
        }
        .alert("上传提示", isPresented: Binding(
            get: { reportUploadVM.infoMessage != nil },
            set: { if !$0 { reportUploadVM.infoMessage = nil } }
        )) {
            Button("知道了", role: .cancel) {}
        } message: {
            Text(reportUploadVM.infoMessage ?? "")
        }
        .alert(reportUploadVM.uploadRecovery == nil ? "上传失败" : "报告需要补传", isPresented: Binding(
            get: { reportUploadVM.errorMessage != nil },
            set: { if !$0 { reportUploadVM.errorMessage = nil } }
        )) {
            if let recovery = reportUploadVM.uploadRecovery,
               let index = recovery.nextAssetIndex {
                Button(recovery.actionCode == "upload_missing_pages" ? "拍照补第 \(index) 页" : "拍照替换第 \(index) 页") {
                    beginReportRecovery(assetIndex: index, useCamera: true)
                }
                Button(recovery.actionCode == "upload_missing_pages" ? "从相册补第 \(index) 页" : "从相册替换第 \(index) 页") {
                    beginReportRecovery(assetIndex: index, useCamera: false)
                }
                Button("重新上传整份", role: .destructive) {
                    reportUploadVM.abandonUploadRecovery()
                    recoveryAssetIndex = nil
                    showReportUploadOptions = true
                }
                Button("稍后处理", role: .cancel) {}
            } else if reportUploadVM.uploadRecovery != nil {
                Button("重新上传整份") {
                    reportUploadVM.abandonUploadRecovery()
                    recoveryAssetIndex = nil
                    showReportUploadOptions = true
                }
                Button("稍后处理", role: .cancel) {}
            } else {
                Button("确定", role: .cancel) {}
            }
        } message: {
            Text(reportUploadVM.errorMessage ?? "")
        }
        .onChange(of: reportUploadVM.activeReportWorkflow) { _, route in
            guard let route else { return }
            if [.awaitingConfirmation, .completedScorePending, .completed].contains(route.status) {
                reportReviewRoute = route
            }
        }
        .onChange(of: authManager.accountScope) { _, scope in
            reportUploadVM.accountDidChange(to: scope)
            reportReviewRoute = nil
        }
    }

    private var primaryActionButton: some View {
        Button {
            runPrimaryAction()
        } label: {
            Text(primaryButtonTitle)
                .font(.system(size: 15, weight: .bold))
                .foregroundStyle(.white)
                .frame(maxWidth: .infinity)
                .frame(height: 46)
                .background(
                    Capsule()
                        .fill(LinearGradient(colors: category.gradient, startPoint: .topLeading, endPoint: .bottomTrailing))
                        .shadow(color: (category.gradient.last ?? Color(hex: "20CDB1")).opacity(0.22), radius: 12, x: 0, y: 7)
                )
        }
        .buttonStyle(.plain)
        .disabled(category != .reports)
        .accessibilityIdentifier("xage.panel.\(category.id).primary")
    }

    private var primaryButtonTitle: String {
        switch category {
        case .reports:
            switch activeRow.key {
            case "upload": return "选择报告"
            case "history": return "查看历史报告"
            case "recognition": return "刷新识别状态"
            default: return "打开待确认报告"
            }
        case .daily:
            return "请从数据页同步 Apple Health"
        case .medical:
            return "打开就医助手"
        case .profile:
            return "打开可信健康画像"
        }
    }

    private func select(_ row: XAgePanelRow) {
        withAnimation(.spring(response: 0.24, dampingFraction: 0.88)) {
            selectedRowID = row.id
        }
    }

    private func runPrimaryAction() {
        guard category == .reports else { return }
        let row = activeRow
        switch row.key {
        case "upload":
            showReportUploadOptions = true
        case "history":
            showReportHistory = true
        case "recognition":
            Task { await reportUploadVM.refreshActiveRuntime() }
        default:
            showReportHistory = true
        }
    }

    private func runHeaderAction() {
        if category == .reports {
            showReportUploadOptions = true
            return
        }
        runPrimaryAction()
    }

    private func handleReportUploadAction(_ action: XAgeReportUploadAction) {
        guard category == .reports else { return }
        switch action {
        case .camera:
            showCamera = true
        case .document:
            showDocumentPicker = true
        case .photoLibrary:
            showPhotoLibrary = true
        }
    }

    private func presentReportUploadActionFromOptions(_ action: XAgeReportUploadAction) {
        showReportUploadOptions = false
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.28) {
            handleReportUploadAction(action)
        }
    }

    private func preparePendingReportUpload(files: [XAgeReportUploadFile], title: String, source: String) {
        guard !files.isEmpty else { return }
        for file in files {
            if let warning = validateReportImageQuality(data: file.data, fileName: file.fileName) {
                uploadQualityWarning = "\(file.fileName)：\(warning)"
                return
            }
        }
        if let assetIndex = recoveryAssetIndex {
            guard let file = files.first, files.count == 1 else {
                reportUploadVM.errorMessage = "补传时每次只能选择一页。"
                return
            }
            recoveryAssetIndex = nil
            Task {
                let route = await reportUploadVM.recoverReportAsset(
                    input: HealthReportUploadAssetInput(
                        data: file.data,
                        fileName: file.fileName
                    ),
                    assetIndex: assetIndex
                )
                if let route,
                   [.awaitingConfirmation, .completedScorePending, .completed].contains(route.status) {
                    reportReviewRoute = route
                }
            }
            return
        }
        let upload = XAgePendingReportUpload(title: title, source: source, files: files)
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.25) {
            pendingUpload = upload
        }
    }

    private func beginReportRecovery(assetIndex: Int, useCamera: Bool) {
        reportUploadVM.errorMessage = nil
        recoveryAssetIndex = assetIndex
        Task { @MainActor in
            await Task.yield()
            if useCamera {
                showCamera = true
            } else {
                showPhotoLibrary = true
            }
        }
    }

    private func uploadReports(_ files: [XAgeReportUploadFile], source: String) {
        guard !files.isEmpty else { return }
        Task {
            let route = await reportUploadVM.uploadReport(
                files: files.map {
                    HealthReportUploadAssetInput(data: $0.data, fileName: $0.fileName)
                },
                source: source,
                subjectUserID: authManager.authenticatedNumericUserID,
                accountScope: authManager.accountScope
            )
            if let route,
               [.awaitingConfirmation, .completedScorePending, .completed].contains(route.status) {
                reportReviewRoute = route
            }
        }
    }

    private func validateReportImageQuality(data: Data, fileName: String) -> String? {
        let lower = fileName.lowercased()
        let isImage = [".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".tif", ".tiff"].contains { lower.hasSuffix($0) }
        guard isImage else { return nil }
        if data.count < 30 * 1024 {
            return "图片过小（小于 30KB），可能不是完整报告。请重新拍摄。"
        }
        if let img = UIImage(data: data) {
            let shortEdge = min(img.size.width, img.size.height) * img.scale
            if shortEdge < 600 {
                return "图片分辨率过低（短边 \(Int(shortEdge))px），识别可能失败。请重新拍摄。"
            }
        } else {
            return "未能读取图片数据，请重新拍摄或选择 PDF。"
        }
        return nil
    }

    private var header: some View {
        HStack {
            Button {
                if let onClose {
                    onClose()
                } else {
                    dismiss()
                }
            } label: {
                Image(systemName: "chevron.left")
                    .font(.system(size: 17, weight: .bold))
                    .foregroundStyle(Color(hex: "347FB7"))
                    .frame(width: 42, height: 34)
                    .background(XAgeCapsuleFill())
            }
            .buttonStyle(.plain)
            .accessibilityLabel("返回")

            Spacer()

            Text(category.rawValue)
                .font(.system(size: 17, weight: .bold))
                .foregroundStyle(Color(hex: "123E67"))
                .frame(height: 34)
                .padding(.horizontal, 18)
                .background(XAgeCapsuleFill())

            Spacer()

//            Button {
//                runHeaderAction()
//            } label: {
//                Image(systemName: category.iconName)
//                    .font(.system(size: 14, weight: .bold))
//                    .foregroundStyle(.white)
//                    .frame(width: 42, height: 34)
//                    .background(
//                        Capsule()
//                            .fill(LinearGradient(colors: category.gradient, startPoint: .topLeading, endPoint: .bottomTrailing))
//                            .overlay(Capsule().stroke(.white.opacity(0.72), lineWidth: 1))
//                    )
//            }
//            .buttonStyle(.plain)
//            .accessibilityLabel(category == .reports ? "上传报告" : "\(category.rawValue)快捷操作")
        }
    }
}

private struct XAgePanelInteractiveDetail: View {
    let category: XAgeDataPanelCategory
    let row: XAgePanelRow
    let snapshot: XAgeServerSyncSnapshot
    let onReportUploadAction: (XAgeReportUploadAction) -> Void
    let onReportHistoryAction: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 13) {
            HStack {
                VStack(alignment: .leading, spacing: 4) {
                    Text(row.title)
                        .font(.system(size: 18, weight: .bold))
                        .foregroundStyle(Color(hex: "173F64"))
                    Text(detailSubtitle)
                        .font(.system(size: 12))
                        .foregroundStyle(Color(hex: "6C8194"))
                        .lineLimit(2)
                }
                Spacer(minLength: 10)
                Text(category == .reports ? "可信链路" : "入口停用")
                    .font(.system(size: 11, weight: .bold))
                    .foregroundStyle(Color(hex: "347FB7"))
                    .frame(width: 62, height: 28)
                    .background(XAgeCapsuleFill())
            }

            content
        }
        .padding(16)
        .background(XAgeGlassCardBackground(cornerRadius: 24))
        .accessibilityIdentifier("xage.panel.\(category.id).detail.\(row.key)")
    }

    private var detailSubtitle: String {
        switch category {
        case .reports:
            return "选择入口、检查识别队列，并确认关键报告字段。"
        case .daily:
            return "请从数据页的 Apple Health 入口执行真实同步。"
        case .medical:
            return "仅展示真实上传、列表、详情和原件查看能力。"
        case .profile:
            return "健康画像由服务端事实、来源和版本统一管理。"
        }
    }

    @ViewBuilder
    private var content: some View {
        switch category {
        case .reports:
            reportsContent
        case .daily, .medical:
            disabledContent
        case .profile:
            EmptyView()
        }
    }

    @ViewBuilder
    private var reportsContent: some View {
        if row.key == "upload" {
            HStack(spacing: 9) {
                actionChip("拍照", icon: "camera.fill") { onReportUploadAction(.camera) }
                actionChip("PDF", icon: "doc.fill") { onReportUploadAction(.document) }
                actionChip("相册", icon: "photo.fill") { onReportUploadAction(.photoLibrary) }
            }
            infoRow("姓名与报告一致", subtitle: "未匹配时会进入人工确认")
            infoRow("最近报告 \(snapshot.latestDocumentLabel)", subtitle: "报告级确认后才能用于可信趋势")
            infoRow("\(snapshot.trustedDocumentCount) 份可信报告", subtitle: "未确认报告不会进入画像、评分或 AI")
        } else if row.key == "recognition" {
            progressLine("病历资料", value: progress(snapshot.recordCount, cap: 20), trailing: "\(snapshot.recordCount) 份")
            progressLine("体检化验", value: progress(snapshot.examCount, cap: 300), trailing: "\(snapshot.examCount) 份")
            progressLine("指标趋势", value: progress(snapshot.indicatorCount, cap: 300), trailing: "\(snapshot.indicatorCount) 项")
            HStack(spacing: 9) {
                infoBadge("异常项需复核", icon: "exclamationmark.triangle.fill")
                infoBadge("全部字段可追溯", icon: "list.bullet.rectangle")
            }
        } else if row.key == "history" {
            Button(action: onReportHistoryAction) {
                HStack(spacing: 10) {
                    Image(systemName: "clock.arrow.circlepath")
                        .font(.system(size: 15, weight: .bold))
                    VStack(alignment: .leading, spacing: 2) {
                        Text("打开历史报告")
                            .font(.system(size: 13, weight: .bold))
                        Text("查看识别状态、可信状态和待确认字段")
                            .font(.system(size: 11, weight: .medium))
                    }
                    Spacer()
                    Image(systemName: "chevron.right")
                        .font(.system(size: 12, weight: .bold))
                }
                .foregroundStyle(Color(hex: "347FB7"))
                .padding(.horizontal, 12)
                .frame(height: 52)
                .background(XAgeCapsuleFill())
            }
            .buttonStyle(.plain)
            progressLine("历史报告", value: progress(snapshot.examCount, cap: 30), trailing: "\(snapshot.examCount) 份")
            progressLine("历史病历", value: progress(snapshot.recordCount, cap: 20), trailing: "\(snapshot.recordCount) 份")
            infoRow("单份报告复核", subtitle: "检查原值、候选值、单位、异常和来源")
        } else {
            infoRow(snapshot.primaryWatchedLabel, subtitle: "\(snapshot.trendPointCount) 个历史趋势点可用于复核")
            infoRow("健康摘要", subtitle: snapshot.hasSummary ? "已生成，可作为问答上下文" : "暂无摘要，建议生成后再问答")
            infoRow("报告日期 \(snapshot.latestDocumentLabel)", subtitle: "确认后会用于排序")
        }
    }

    private var disabledContent: some View {
        Label("该快捷入口尚未接入服务端，已停用本地模拟操作。", systemImage: "nosign")
            .font(.system(size: 13, weight: .semibold))
            .foregroundStyle(Color(hex: "8B5B35"))
            .fixedSize(horizontal: false, vertical: true)
            .padding(12)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Color(hex: "FFF1E9").opacity(0.82), in: RoundedRectangle(cornerRadius: 18))
    }

    private func progress(_ value: Int, cap: Int) -> CGFloat {
        guard cap > 0 else { return 0 }
        return min(1, CGFloat(value) / CGFloat(cap))
    }

    private func actionChip(_ title: String, icon: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: 5) {
                Image(systemName: icon)
                    .font(.system(size: 11, weight: .bold))
                Text(title)
                    .font(.system(size: 12, weight: .bold))
                    .lineLimit(1)
                    .minimumScaleFactor(0.8)
            }
            .foregroundStyle(Color(hex: "347FB7"))
            .frame(maxWidth: .infinity)
            .frame(height: 34)
            .background(
                Capsule()
                    .fill(Color.white.opacity(0.62))
                    .overlay(Capsule().stroke(.white.opacity(0.78), lineWidth: 1))
            )
        }
        .buttonStyle(.plain)
    }

    private func infoRow(_ title: String, subtitle: String) -> some View {
        HStack(spacing: 10) {
                Image(systemName: "info.circle.fill")
                    .font(.system(size: 18, weight: .bold))
                    .foregroundStyle(Color(hex: "347FB7"))
                VStack(alignment: .leading, spacing: 2) {
                    Text(title)
                        .font(.system(size: 13, weight: .bold))
                        .foregroundStyle(Color(hex: "173F64"))
                        .lineLimit(1)
                        .minimumScaleFactor(0.82)
                    Text(subtitle)
                        .font(.system(size: 11))
                        .foregroundStyle(Color(hex: "6C8194"))
                        .lineLimit(1)
                        .minimumScaleFactor(0.78)
                }
                Spacer(minLength: 6)
            }
            .padding(.horizontal, 12)
            .frame(height: 52)
            .background(
                RoundedRectangle(cornerRadius: 18, style: .continuous)
                    .fill(.white.opacity(0.48))
                    .overlay(
                        RoundedRectangle(cornerRadius: 18, style: .continuous)
                            .stroke(.white.opacity(0.7), lineWidth: 1)
                    )
            )
    }

    private func infoBadge(_ title: String, icon: String) -> some View {
        Label(title, systemImage: icon)
            .font(.system(size: 11, weight: .bold))
            .foregroundStyle(Color(hex: "347FB7"))
            .lineLimit(1)
            .minimumScaleFactor(0.76)
            .frame(maxWidth: .infinity)
            .frame(height: 34)
            .background(XAgeCapsuleFill())
    }

    private func progressLine(_ title: String, value: CGFloat, trailing: String) -> some View {
        VStack(alignment: .leading, spacing: 7) {
            HStack {
                Text(title)
                    .font(.system(size: 12, weight: .bold))
                    .foregroundStyle(Color(hex: "173F64"))
                Spacer()
                Text(trailing)
                    .font(.system(size: 12, weight: .bold))
                    .foregroundStyle(Color(hex: "347FB7"))
            }
            GeometryReader { proxy in
                ZStack(alignment: .leading) {
                    Capsule()
                        .fill(.white.opacity(0.54))
                    Capsule()
                        .fill(LinearGradient(colors: category.gradient, startPoint: .leading, endPoint: .trailing))
                        .frame(width: max(14, proxy.size.width * min(max(value, 0), 1)))
                }
            }
            .frame(height: 8)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
        .background(
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .fill(.white.opacity(0.48))
                .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous).stroke(.white.opacity(0.7), lineWidth: 1))
        )
    }

}

private struct XAgeReportUploadSourceSheet: View {
    let onCamera: () -> Void
    let onDocument: () -> Void
    let onPhotoLibrary: () -> Void

    var body: some View {
        ZStack {
            XAgeLiquidBackground()
                .ignoresSafeArea()

            VStack(alignment: .leading, spacing: 14) {
                HStack(spacing: 12) {
                    ZStack {
                        Circle()
                            .fill(LinearGradient(colors: [Color(hex: "238AD6"), Color(hex: "20CDB1")], startPoint: .topLeading, endPoint: .bottomTrailing))
                        Image(systemName: "arrow.up.doc.fill")
                            .font(.system(size: 22, weight: .bold))
                            .foregroundStyle(.white)
                    }
                    .frame(width: 52, height: 52)

                    VStack(alignment: .leading, spacing: 3) {
                        Text("数据上传")
                            .font(.system(size: 24, weight: .bold))
                            .foregroundStyle(Color(hex: "123E67"))
                        Text("选择报告、化验单或影像截图来源")
                            .font(.system(size: 13, weight: .medium))
                            .foregroundStyle(Color(hex: "5D7890"))
                    }
                }

                uploadSourceRow(title: "拍照采集", subtitle: "拍摄纸质报告或检查单", icon: "camera.fill", action: onCamera)
                uploadSourceRow(title: "PDF / 图片", subtitle: "从文件中上传报告、病历或扫描件", icon: "doc.badge.plus", action: onDocument)
                uploadSourceRow(title: "从相册选择", subtitle: "一次可选择多张报告图片", icon: "photo.on.rectangle.angled", action: onPhotoLibrary)
            }
            .padding(24)
        }
    }

    private func uploadSourceRow(title: String, subtitle: String, icon: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: 12) {
                Image(systemName: icon)
                    .font(.system(size: 16, weight: .bold))
                    .foregroundStyle(.white)
                    .frame(width: 38, height: 38)
                    .background(
                        Circle()
                            .fill(LinearGradient(colors: [Color(hex: "238AD6"), Color(hex: "20CDB1")], startPoint: .topLeading, endPoint: .bottomTrailing))
                    )
                VStack(alignment: .leading, spacing: 3) {
                    Text(title)
                        .font(.system(size: 16, weight: .bold))
                        .foregroundStyle(Color(hex: "173F64"))
                    Text(subtitle)
                        .font(.system(size: 12, weight: .medium))
                        .foregroundStyle(Color(hex: "6C8194"))
                        .lineLimit(1)
                }
                Spacer()
                Image(systemName: "chevron.right")
                    .font(.system(size: 12, weight: .bold))
                    .foregroundStyle(Color(hex: "7D9AB1"))
            }
            .padding(.horizontal, 14)
            .frame(height: 62)
            .background(XAgeGlassCardBackground(cornerRadius: 22))
        }
        .buttonStyle(.plain)
    }
}

@MainActor
private final class XAgeReportHistoryViewModel: ObservableObject {
    @Published private(set) var loading = false
    @Published private(set) var traceLoadingWorkflowID: Int?
    @Published private(set) var items: [HealthReportHistoryItem] = []
    @Published private(set) var activeQuery = HealthReportHistoryQuery.empty
    @Published var selectedTrace: XAgeReportTraceSelection?
    @Published var errorMessage: String?

    private let repository: any HealthReportCompletionRepositoryProtocol
    private let currentAccountScope: @MainActor () -> String?
    private var activeContext: XAgeReportHistoryContext?
    private var loadGeneration = 0
    private var traceGeneration = 0

    init(
        repository: any HealthReportCompletionRepositoryProtocol = HealthReportCompletionRepository(),
        currentAccountScope: @escaping @MainActor () -> String? = { AuthManager.shared.accountScope }
    ) {
        self.repository = repository
        self.currentAccountScope = currentAccountScope
    }

    func load(
        subjectUserID: Int?,
        accountScope: String?,
        query: HealthReportHistoryQuery? = nil
    ) async {
        loadGeneration &+= 1
        let generation = loadGeneration
        guard let subjectUserID,
              let accountScope,
              !accountScope.isEmpty,
              currentAccountScope() == accountScope else {
            resetForUnavailableAccount()
            errorMessage = "当前账号无法读取报告历史，请重新登录后重试。"
            return
        }

        let context = XAgeReportHistoryContext(
            accountScope: accountScope,
            subjectUserID: subjectUserID
        )
        if activeContext != context {
            activeContext = context
            items = []
            selectedTrace = nil
            activeQuery = .empty
        }
        let requestedQuery = query ?? activeQuery
        activeQuery = requestedQuery
        errorMessage = nil
        loading = true
        defer {
            if loadGeneration == generation {
                loading = false
            }
        }
        do {
            let response = try await repository.fetchHistory(
                subjectUserID: subjectUserID,
                dateFrom: requestedQuery.dateFrom,
                dateTo: requestedQuery.dateTo,
                hospital: requestedQuery.hospital,
                reportType: requestedQuery.reportType
            )
            guard loadGeneration == generation,
                  activeContext == context,
                  currentAccountScope() == accountScope else { return }
            // The server owns ordering and workflow status; never re-sort or infer here.
            items = response.items
        } catch {
            guard loadGeneration == generation,
                  activeContext == context,
                  currentAccountScope() == accountScope else { return }
            errorMessage = error.localizedDescription
        }
    }

    func openTrace(
        for item: HealthReportHistoryItem,
        subjectUserID: Int?,
        accountScope: String?
    ) async {
        traceGeneration &+= 1
        let generation = traceGeneration
        guard let subjectUserID,
              let accountScope,
              !accountScope.isEmpty,
              currentAccountScope() == accountScope,
              activeContext == XAgeReportHistoryContext(
                accountScope: accountScope,
                subjectUserID: subjectUserID
              ) else {
            errorMessage = "账号已切换，请重新打开报告历史。"
            return
        }

        errorMessage = nil
        traceLoadingWorkflowID = item.workflow_id
        defer {
            if traceGeneration == generation {
                traceLoadingWorkflowID = nil
            }
        }
        do {
            let trace = try await repository.fetchTrace(
                workflowID: item.workflow_id,
                subjectUserID: subjectUserID
            )
            guard traceGeneration == generation,
                  currentAccountScope() == accountScope else { return }
            guard trace.workflow.id == item.workflow_id else {
                errorMessage = "服务器返回的追踪记录与所选报告不一致，请刷新后重试。"
                return
            }
            selectedTrace = XAgeReportTraceSelection(
                item: item,
                trace: trace,
                subjectUserID: subjectUserID,
                accountScope: accountScope
            )
        } catch {
            guard traceGeneration == generation,
                  currentAccountScope() == accountScope else { return }
            errorMessage = error.localizedDescription
        }
    }

    func presentError(_ message: String) {
        errorMessage = message
    }

    private func resetForUnavailableAccount() {
        loading = false
        traceLoadingWorkflowID = nil
        activeContext = nil
        activeQuery = .empty
        items = []
        selectedTrace = nil
    }
}

private struct XAgeReportHistoryContext: Equatable {
    let accountScope: String
    let subjectUserID: Int
}

private struct XAgeReportHistorySheet: View {
    @StateObject private var vm = XAgeReportHistoryViewModel()
    @Environment(\.dismiss) private var dismiss
    @EnvironmentObject private var authManager: AuthManager
    @FocusState private var hospitalFieldFocused: Bool
    @State private var filtersExpanded = false
    @State private var usesDateFrom = false
    @State private var usesDateTo = false
    @State private var dateFrom = Date().addingTimeInterval(-90 * 24 * 60 * 60)
    @State private var dateTo = Date()
    @State private var hospital = ""
    @State private var reportType = XAgeReportHistoryReportType.all

    var body: some View {
        ZStack {
            XAgeLiquidBackground()
                .ignoresSafeArea()

            VStack(spacing: 14) {
                header
                ScrollView {
                    LazyVStack(spacing: 12) {
                        filterSummary
                        if filtersExpanded {
                            filterCard
                                .transition(.opacity.combined(with: .move(edge: .top)))
                        }
                        historyContent
                    }
                    .padding(2)
                }
                .scrollDismissesKeyboard(.interactively)
                .scrollIndicators(.hidden)
                .refreshable { await loadActiveQuery() }
                .background(
                    Color.clear
                        .contentShape(Rectangle())
                        .onTapGesture { hospitalFieldFocused = false }
                )
            }
            .padding(24)
        }
        .task(id: authManager.accountScope) {
            resetFilterInputs()
            await vm.load(
                subjectUserID: authManager.authenticatedNumericUserID,
                accountScope: authManager.accountScope,
                query: .empty
            )
        }
        .sheet(item: $vm.selectedTrace) { selection in
            XAgeReportTraceSheet(selection: selection)
                .presentationDetents([.large])
                .presentationDragIndicator(.visible)
        }
        .xAgeKeyboardDoneAccessory(
            isPresented: hospitalFieldFocused,
            accessibilityIdentifier: "xage.report.history.keyboard.done"
        ) {
            hospitalFieldFocused = false
        }
        .alert("读取失败", isPresented: Binding(
            get: { vm.errorMessage != nil },
            set: { if !$0 { vm.errorMessage = nil } }
        )) {
            Button("知道了", role: .cancel) {}
        } message: {
            Text(vm.errorMessage ?? "")
        }
    }

    private var header: some View {
        HStack {
            VStack(alignment: .leading, spacing: 4) {
                Text("历史报告")
                    .font(.system(size: 25, weight: .bold))
                    .foregroundStyle(Color(hex: "123E67"))
                Text("列表、状态和追踪链均以服务器记录为准")
                    .font(.system(size: 13, weight: .medium))
                    .foregroundStyle(Color(hex: "5D7890"))
            }
            Spacer()
            Button {
                hospitalFieldFocused = false
                dismiss()
            } label: {
                Image(systemName: "xmark")
                    .font(.system(size: 13, weight: .bold))
                    .foregroundStyle(Color(hex: "1268BD"))
                    .frame(width: 34, height: 34)
                    .background(XAgeCapsuleFill())
            }
            .frame(width: 44, height: 44)
            .contentShape(Rectangle())
            .buttonStyle(.plain)
            .accessibilityLabel("关闭历史报告")
        }
    }

    private var filterSummary: some View {
        HStack(spacing: 10) {
            Button {
                hospitalFieldFocused = false
                withAnimation(.spring(response: 0.24, dampingFraction: 0.9)) {
                    filtersExpanded.toggle()
                }
            } label: {
                HStack(spacing: 8) {
                    Image(systemName: "line.3.horizontal.decrease.circle.fill")
                    Text(filtersExpanded ? "收起筛选" : "筛选报告")
                    if vm.activeQuery.activeFilterCount > 0 {
                        Text("\(vm.activeQuery.activeFilterCount)")
                            .font(.caption2.weight(.bold))
                            .foregroundStyle(.white)
                            .frame(minWidth: 22, minHeight: 22)
                            .background(Circle().fill(Color(hex: "238AD6")))
                    }
                }
                .font(.system(size: 14, weight: .bold))
                .foregroundStyle(Color(hex: "347FB7"))
                .frame(maxWidth: .infinity, minHeight: 44)
                .background(XAgeCapsuleFill())
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("xage.report.history.filters.toggle")

            if !vm.activeQuery.isEmpty {
                Button("清除") { clearFilters() }
                    .font(.system(size: 13, weight: .bold))
                    .foregroundStyle(Color(hex: "D85A66"))
                    .frame(minWidth: 64, minHeight: 44)
                    .background(XAgeCapsuleFill())
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("xage.report.history.clear")
            }
        }
    }

    private var filterCard: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("按服务器字段筛选")
                .font(.system(size: 16, weight: .bold))
                .foregroundStyle(Color(hex: "173F64"))
            dateFilterRow(title: "开始日期", enabled: $usesDateFrom, date: $dateFrom, identifier: "dateFrom")
            dateFilterRow(title: "结束日期", enabled: $usesDateTo, date: $dateTo, identifier: "dateTo")

            VStack(alignment: .leading, spacing: 6) {
                Text("医院")
                    .font(.caption.weight(.bold))
                    .foregroundStyle(Color(hex: "5D7890"))
                TextField("输入医院名称", text: $hospital)
                    .textInputAutocapitalization(.never)
                    .submitLabel(.done)
                    .focused($hospitalFieldFocused)
                    .onSubmit { hospitalFieldFocused = false }
                    .padding(.horizontal, 14)
                    .frame(minHeight: 44)
                    .background(XAgeCapsuleFill())
                    .accessibilityIdentifier("xage.report.history.hospital")
            }

            HStack {
                Text("报告类型")
                    .font(.system(size: 14, weight: .bold))
                    .foregroundStyle(Color(hex: "173F64"))
                Spacer()
                Picker("报告类型", selection: $reportType) {
                    ForEach(XAgeReportHistoryReportType.allCases) { type in
                        Text(type.title).tag(type)
                    }
                }
                .pickerStyle(.menu)
                .accessibilityIdentifier("xage.report.history.reportType")
            }
            .frame(minHeight: 44)

            HStack(spacing: 10) {
                Button("清除筛选") { clearFilters() }
                    .font(.system(size: 14, weight: .bold))
                    .foregroundStyle(Color(hex: "347FB7"))
                    .frame(maxWidth: .infinity, minHeight: 46)
                    .background(XAgeCapsuleFill())
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("xage.report.history.filters.clear")
                Button("应用筛选") { applyFilters() }
                    .font(.system(size: 14, weight: .bold))
                    .foregroundStyle(.white)
                    .frame(maxWidth: .infinity, minHeight: 46)
                    .background(
                        Capsule().fill(
                            LinearGradient(
                                colors: [Color(hex: "238AD6"), Color(hex: "20CDB1")],
                                startPoint: .leading,
                                endPoint: .trailing
                            )
                        )
                    )
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("xage.report.history.filters.apply")
            }
        }
        .padding(16)
        .background(XAgeGlassCardBackground(cornerRadius: 24))
    }

    @ViewBuilder
    private var historyContent: some View {
        if vm.loading && vm.items.isEmpty {
            VStack(spacing: 10) {
                ProgressView().tint(Color(hex: "18AFA7"))
                Text("正在读取服务器报告历史")
                    .font(.system(size: 13, weight: .medium))
                    .foregroundStyle(Color(hex: "5D7890"))
            }
            .frame(maxWidth: .infinity, minHeight: 300)
            .background(XAgeGlassCardBackground(cornerRadius: 24))
        } else if vm.items.isEmpty {
            XAgeReportHistoryEmptyState(filtered: !vm.activeQuery.isEmpty)
                .frame(minHeight: 300)
        } else {
            ForEach(vm.items) { item in
                Button {
                    hospitalFieldFocused = false
                    Task {
                        await vm.openTrace(
                            for: item,
                            subjectUserID: authManager.authenticatedNumericUserID,
                            accountScope: authManager.accountScope
                        )
                    }
                } label: {
                    XAgeReportHistoryRow(
                        item: item,
                        loadingTrace: vm.traceLoadingWorkflowID == item.workflow_id
                    )
                }
                .buttonStyle(.plain)
                .disabled(vm.traceLoadingWorkflowID != nil)
                .accessibilityIdentifier("xage.report.history.workflow.\(item.workflow_id)")
                .accessibilityLabel("\(item.title)，\(item.xAgeHistoryMetadataLabel)，\(item.xAgeWorkflowStatusLabel)")
            }
        }
    }

    private func dateFilterRow(
        title: String,
        enabled: Binding<Bool>,
        date: Binding<Date>,
        identifier: String
    ) -> some View {
        VStack(spacing: 6) {
            Toggle(title, isOn: enabled)
                .font(.system(size: 14, weight: .bold))
                .foregroundStyle(Color(hex: "173F64"))
                .frame(minHeight: 44)
                .accessibilityIdentifier("xage.report.history.\(identifier).enabled")
            if enabled.wrappedValue {
                DatePicker(title, selection: date, displayedComponents: .date)
                    .datePickerStyle(.compact)
                    .labelsHidden()
                    .frame(maxWidth: .infinity, alignment: .trailing)
                    .accessibilityIdentifier("xage.report.history.\(identifier).value")
            }
        }
    }

    private func applyFilters() {
        hospitalFieldFocused = false
        if usesDateFrom, usesDateTo, dateFrom > dateTo {
            vm.presentError("开始日期不能晚于结束日期。")
            return
        }
        let query = HealthReportHistoryQuery(
            dateFrom: usesDateFrom ? serverDate(dateFrom) : nil,
            dateTo: usesDateTo ? serverDate(dateTo) : nil,
            hospital: hospital,
            reportType: reportType == .all ? nil : reportType.rawValue
        )
        Task {
            await vm.load(
                subjectUserID: authManager.authenticatedNumericUserID,
                accountScope: authManager.accountScope,
                query: query
            )
        }
    }

    private func clearFilters() {
        hospitalFieldFocused = false
        resetFilterInputs()
        Task {
            await vm.load(
                subjectUserID: authManager.authenticatedNumericUserID,
                accountScope: authManager.accountScope,
                query: .empty
            )
        }
    }

    private func loadActiveQuery() async {
        await vm.load(
            subjectUserID: authManager.authenticatedNumericUserID,
            accountScope: authManager.accountScope
        )
    }

    private func resetFilterInputs() {
        usesDateFrom = false
        usesDateTo = false
        dateFrom = Date().addingTimeInterval(-90 * 24 * 60 * 60)
        dateTo = Date()
        hospital = ""
        reportType = .all
    }

    private func serverDate(_ date: Date) -> String {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = .current
        let parts = calendar.dateComponents([.year, .month, .day], from: date)
        return String(format: "%04d-%02d-%02d", parts.year ?? 0, parts.month ?? 0, parts.day ?? 0)
    }
}

extension HealthDocument {
    var xAgeDisplayTitle: String {
        let title = (name ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        if !title.isEmpty { return title }
        let urlName = (file_url ?? "").split(separator: "/").last.map(String.init) ?? ""
        if !urlName.isEmpty { return urlName }
        return doc_type == "record" ? "未命名病历" : "未命名报告"
    }

    var xAgeStatusLabel: String {
        switch reportTrustState {
        case .workflow(let status):
            switch status {
            case .draft, .uploading: return "上传中"
            case .recognizing: return "识别中"
            case .awaitingConfirmation: return "待确认"
            case .committing: return "入库中"
            case .completedScorePending: return "已确认 · 评分待更新"
            case .completed: return "可信完成"
            case .failed: return "识别失败"
            case .unknown: return "状态待刷新"
            }
        case .legacyRecognizing:
            return "识别中"
        case .legacyUnverified:
            return "历史未验证"
        }
    }

    var xAgeStatusColor: Color {
        switch reportTrustState {
        case .workflow(.completed): return Color(hex: "18AFA7")
        case .workflow(.completedScorePending): return Color(hex: "C57A27")
        case .workflow(.failed): return Color(hex: "D85A66")
        case .workflow, .legacyRecognizing: return Color(hex: "238AD6")
        case .legacyUnverified: return Color(hex: "8B5B35")
        }
    }

    var xAgeReviewActionTitle: String {
        switch reportTrustState {
        case .workflow(.awaitingConfirmation): return "检查字段并确认整份报告"
        case .workflow(.recognizing), .workflow(.uploading), .workflow(.draft): return "查看识别进度"
        case .workflow(.committing): return "查看入库状态"
        case .workflow(.completedScorePending): return "查看已确认字段和评分状态"
        case .workflow(.completed): return "查看已确认字段"
        case .workflow(.failed): return "查看失败原因"
        case .workflow(.unknown): return "刷新报告状态"
        case .legacyRecognizing, .legacyUnverified: return "查看报告状态"
        }
    }

}

private struct XAgePanelActionRow: View {
    let category: XAgeDataPanelCategory
    let row: XAgePanelRow
    var trailingTitle: String?
    var showsProgress: Bool = false
    var isSelected: Bool = false

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: row.icon)
                .font(.system(size: 16, weight: .bold))
                .foregroundStyle(.white)
                .frame(width: 38, height: 38)
                .background(
                    Circle()
                        .fill(LinearGradient(colors: category.gradient, startPoint: .topLeading, endPoint: .bottomTrailing))
                        .shadow(color: (category.gradient.last ?? Color(hex: "20CDB1")).opacity(0.18), radius: 10, x: 0, y: 5)
                )
            VStack(alignment: .leading, spacing: 3) {
                Text(row.title)
                    .font(.system(size: 16, weight: .bold))
                    .foregroundStyle(Color(hex: "173F64"))
                    .lineLimit(1)
                Text(row.subtitle)
                    .font(.system(size: 12))
                    .foregroundStyle(Color(hex: "6C8194"))
                    .lineLimit(1)
                    .minimumScaleFactor(0.82)
            }
            Spacer(minLength: 8)
            if showsProgress {
                ProgressView()
                    .controlSize(.small)
                    .frame(width: 52, height: 30)
            } else if let trailingTitle {
                Text(trailingTitle)
                    .font(.system(size: 11, weight: .bold))
                    .foregroundStyle(Color(hex: "347FB7"))
                    .lineLimit(1)
                    .minimumScaleFactor(0.74)
                    .frame(width: 72, height: 30)
                    .background(XAgeCapsuleFill())
            } else {
                Image(systemName: "chevron.right")
                    .font(.system(size: 13, weight: .bold))
                    .foregroundStyle(Color(hex: "7D9AB1"))
            }
        }
        .padding(.horizontal, 14)
        .frame(height: 66)
        .background(XAgeGlassCardBackground(cornerRadius: 22))
        .overlay(
            RoundedRectangle(cornerRadius: 22, style: .continuous)
                .stroke(isSelected ? (category.gradient.last ?? Color(hex: "20CDB1")).opacity(0.58) : .clear, lineWidth: 1.2)
        )
    }
}

/// 报告文件真正离开设备前的最终确认页。
struct XAgeReportUploadConfirmSheet: View {
    /// 待上传文件、来源和总大小。
    let upload: XAgePendingReportUpload
    /// 是否正在上传；用于禁用重复确认和取消动作。
    let isUploading: Bool
    /// 用户取消且不保存文件的回调。
    let onCancel: () -> Void
    /// 用户明确同意上传后的回调。
    let onConfirm: () -> Void

    var body: some View {
        ZStack {
            XAgeLiquidBackground()
                .ignoresSafeArea()

            VStack(alignment: .leading, spacing: 16) {
                HStack(alignment: .top, spacing: 12) {
                    ZStack {
                        Circle()
                            .fill(
                                LinearGradient(
                                    colors: [Color(hex: "238AD6"), Color(hex: "20CDB1")],
                                    startPoint: .topLeading,
                                    endPoint: .bottomTrailing
                                )
                            )
                        Image(systemName: upload.files.count > 1 ? "photo.stack.fill" : "arrow.up.doc.fill")
                            .font(.system(size: 22, weight: .bold))
                            .foregroundStyle(.white)
                    }
                    .frame(width: 54, height: 54)

                    VStack(alignment: .leading, spacing: 4) {
                        Text(upload.title)
                            .font(.system(size: 24, weight: .bold))
                            .foregroundStyle(Color(hex: "123E67"))
                            .fixedSize(horizontal: false, vertical: true)
                        Text("\(upload.source) · \(upload.files.count) 个文件 · \(upload.totalSizeText)")
                            .font(.system(size: 13, weight: .medium))
                            .foregroundStyle(Color(hex: "5D7890"))
                    }

                    Spacer(minLength: 0)
                }

                Text("确认后才会上传到你的健康资料库，并进入 AI 识别队列。取消不会保存这些图片或文件。")
                    .font(.system(size: 13))
                    .foregroundStyle(Color(hex: "496A83"))
                    .lineSpacing(3)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(14)
                    .background(XAgeCapsuleFill())

                ScrollView {
                    LazyVGrid(columns: [GridItem(.adaptive(minimum: 92), spacing: 10)], spacing: 10) {
                        ForEach(upload.files) { file in
                            XAgeReportUploadPreviewCell(file: file)
                        }
                    }
                    .padding(2)
                }
                .scrollIndicators(.hidden)
                .frame(maxHeight: 230)

                HStack(spacing: 10) {
                    Button(action: onCancel) {
                        Text("取消")
                            .font(.system(size: 15, weight: .bold))
                            .foregroundStyle(Color(hex: "365F80"))
                            .frame(maxWidth: .infinity)
                            .frame(height: 46)
                            .background(XAgeCapsuleFill())
                    }
                    .buttonStyle(.plain)
                    .disabled(isUploading)

                    Button(action: onConfirm) {
                        HStack(spacing: 8) {
                            if isUploading {
                                ProgressView()
                                    .tint(.white)
                            }
                            Text(isUploading ? "上传中" : "确认上传")
                                .font(.system(size: 15, weight: .bold))
                        }
                        .foregroundStyle(.white)
                        .frame(maxWidth: .infinity)
                        .frame(height: 46)
                        .background(
                            Capsule()
                                .fill(
                                    LinearGradient(
                                        colors: [Color(hex: "238AD6"), Color(hex: "20CDB1")],
                                        startPoint: .topLeading,
                                        endPoint: .bottomTrailing
                                    )
                                )
                        )
                    }
                    .buttonStyle(.plain)
                    .disabled(isUploading)
                    .accessibilityIdentifier("xage.reportUpload.confirm")
                }
            }
            .padding(24)
        }
    }
}

private struct XAgeReportUploadPreviewCell: View {
    let file: XAgeReportUploadFile

    var body: some View {
        VStack(spacing: 8) {
            ZStack {
                RoundedRectangle(cornerRadius: 18, style: .continuous)
                    .fill(.white.opacity(0.54))
                    .overlay(
                        RoundedRectangle(cornerRadius: 18, style: .continuous)
                            .stroke(.white.opacity(0.74), lineWidth: 1)
                    )
                if let image = file.previewImage {
                    Image(uiImage: image)
                        .resizable()
                        .scaledToFill()
                        .frame(height: 86)
                        .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
                } else {
                    Image(systemName: "doc.fill")
                        .font(.system(size: 25, weight: .bold))
                        .foregroundStyle(Color(hex: "347FB7"))
                }
            }
            .frame(height: 86)

            Text(file.fileName)
                .font(.system(size: 10, weight: .medium))
                .foregroundStyle(Color(hex: "5D7890"))
                .lineLimit(2)
                .multilineTextAlignment(.center)
                .frame(height: 28)
        }
        .padding(8)
        .background(XAgeGlassCardBackground(cornerRadius: 22))
    }
}

struct XAgeDataDetailView: View {
    let kind: XAgeDataKind
    let metric: XAgeMetricScore
    let onSyncAppleHealth: () async -> Void
    let onOpenGuide: () -> Void
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        ZStack {
            XAgeLiquidBackground()
                .ignoresSafeArea()
            ScrollView {
                VStack(spacing: 16) {
                    ZStack {
                        VStack(spacing: 3) {
                            Text(kind.rawValue)
                                .font(.system(size: 28, weight: .bold))
                                .foregroundStyle(Color(hex: "123E67"))
                            Text(metric.isReady ? "置信度 \(metric.confidence)%" : "评分待更新")
                                .font(.system(size: 12, weight: .bold))
                                .foregroundStyle(kind.tint)
                                .padding(.horizontal, 10)
                                .padding(.vertical, 4)
                                .background(XAgeCapsuleFill())
                        }

                        HStack {
                            Spacer()
                            Button {
                                dismiss()
                            } label: {
                                Image(systemName: "xmark")
                                    .font(.system(size: 13, weight: .bold))
                                    .foregroundStyle(Color(hex: "1268BD"))
                                    .frame(width: 34, height: 34)
                                    .background(XAgeCapsuleFill())
                            }
                            .frame(width: 44, height: 44)
                            .contentShape(Rectangle())
                            .accessibilityLabel("关闭")
                        }
                    }
                    .padding(.top, 14)

                    XAgeScoreRing(kind: kind, metric: metric)
                        .frame(width: 150)
                        .padding(.vertical, 10)

                    if !metric.isReady {
                        XAgeMissingDataGuideCard(
                            kind: kind,
                            metric: metric,
                            onSyncAppleHealth: onSyncAppleHealth,
                            onOpenGuide: onOpenGuide
                        )
                    }

                    VStack(alignment: .leading, spacing: 12) {
                        Text("指标构成")
                            .font(.system(size: 18, weight: .bold))
                            .foregroundStyle(Color(hex: "173F64"))
                        ForEach(metric.fields) { field in
                            HStack {
                                Text(field.title)
                                    .font(.system(size: 14, weight: .medium))
                                    .foregroundStyle(Color(hex: "496A83"))
                                Spacer()
                                Text(field.value)
                                    .font(.system(size: 14, weight: .bold))
                                    .foregroundStyle(Color(hex: "17324E"))
                            }
                            Divider().opacity(0.24)
                        }
                    }
                    .padding(18)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(XAgeGlassCardBackground(cornerRadius: 26))

                    VStack(alignment: .leading, spacing: 10) {
                        Text("主要输入")
                            .font(.system(size: 18, weight: .bold))
                            .foregroundStyle(Color(hex: "173F64"))
                        ForEach(metric.drivers.prefix(3)) { driver in
                            HStack(alignment: .top, spacing: 10) {
                                Circle()
                                    .fill(kind.tint)
                                    .frame(width: 7, height: 7)
                                    .padding(.top, 6)
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(driver.title)
                                        .font(.system(size: 14, weight: .bold))
                                        .foregroundStyle(Color(hex: "17324E"))
                                    Text(driver.note)
                                        .font(.system(size: 12))
                                        .foregroundStyle(Color(hex: "5D7890"))
                                        .lineSpacing(2)
                                }
                            }
                        }
                    }
                    .padding(18)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(XAgeGlassCardBackground(cornerRadius: 26))

                    VStack(alignment: .leading, spacing: 8) {
                        Text("先看结论")
                            .font(.system(size: 18, weight: .bold))
                            .foregroundStyle(Color(hex: "173F64"))
                        Text(metric.simpleExplanation)
                            .font(.system(size: 14))
                            .foregroundStyle(Color(hex: "496A83"))
                            .lineSpacing(3)
                        DisclosureGroup {
                            Text(metric.explanation)
                                .font(.system(size: 13))
                                .foregroundStyle(Color(hex: "5D7890"))
                                .lineSpacing(3)
                                .fixedSize(horizontal: false, vertical: true)
                                .padding(.top, 6)
                        } label: {
                            Text("专业依据")
                                .font(.system(size: 13, weight: .bold))
                                .foregroundStyle(kind.tint)
                        }
                        .tint(kind.tint)

                        Text(metric.nextAction)
                            .font(.system(size: 13, weight: .bold))
                            .foregroundStyle(kind.tint)
                            .lineSpacing(3)
                            .padding(12)
                            .background(XAgeCapsuleFill())
                    }
                    .padding(18)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(XAgeGlassCardBackground(cornerRadius: 26))
                }
                .padding(24)
            }
        }
    }
}

private struct XAgeMissingDataGuideCard: View {
    let kind: XAgeDataKind
    let metric: XAgeMetricScore
    let onSyncAppleHealth: () async -> Void
    let onOpenGuide: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 10) {
                Image(systemName: "tray.and.arrow.up.fill")
                    .font(.system(size: 16, weight: .bold))
                    .foregroundStyle(kind.tint)
                    .frame(width: 34, height: 34)
                    .background(XAgeCapsuleFill())
                VStack(alignment: .leading, spacing: 3) {
                    Text("等待可信评分")
                        .font(.system(size: 17, weight: .bold))
                        .foregroundStyle(Color(hex: "173F64"))
                    Text(metric.summary)
                        .font(.system(size: 12))
                        .foregroundStyle(Color(hex: "5D7890"))
                        .lineLimit(2)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }

            HStack(spacing: 10) {
                Button {
                    Task { await onSyncAppleHealth() }
                } label: {
                    guideButtonTitle("同步 Apple 健康", icon: "heart.text.square.fill", filled: true)
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("xage.score.missing.syncAppleHealth")

                Button(action: onOpenGuide) {
                    guideButtonTitle(kind == .inflammation ? "上传报告" : "打开指标", icon: kind == .inflammation ? "arrow.up.doc.fill" : "list.bullet.rectangle", filled: false)
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("xage.score.missing.openGuide")
            }
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(XAgeGlassCardBackground(cornerRadius: 26))
    }

    private func guideButtonTitle(_ title: String, icon: String, filled: Bool) -> some View {
        HStack(spacing: 6) {
            Image(systemName: icon)
                .font(.system(size: 12, weight: .bold))
            Text(title)
                .font(.system(size: 13, weight: .bold))
                .lineLimit(1)
                .minimumScaleFactor(0.82)
        }
        .foregroundStyle(filled ? .white : kind.tint)
        .frame(maxWidth: .infinity)
        .frame(height: 38)
        .background(
            Capsule()
                .fill(filled ? AnyShapeStyle(LinearGradient(colors: [kind.tint, Color(hex: "20CDB1")], startPoint: .leading, endPoint: .trailing)) : AnyShapeStyle(Color.white.opacity(0.62)))
                .overlay(Capsule().stroke(.white.opacity(0.8), lineWidth: 1))
        )
    }
}

struct XAgeScoreInfoSheet: View {
    let kind: XAgeDataKind
    let metric: XAgeMetricScore
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        ZStack {
            XAgeLiquidBackground()
                .ignoresSafeArea()

            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    HStack(spacing: 12) {
                        Image(systemName: "info.circle.fill")
                            .font(.system(size: 22, weight: .bold))
                            .foregroundStyle(kind.tint)
                        VStack(alignment: .leading, spacing: 3) {
                            Text("\(kind.rawValue)原理")
                                .font(.system(size: 24, weight: .bold))
                                .foregroundStyle(Color(hex: "173F64"))
                            Text(metric.isReady ? (metric.isProxy ? "代理信号 · 置信度 \(metric.confidence)%" : "综合评分 · 置信度 \(metric.confidence)%") : "待评估 · 置信度 \(metric.confidence)%")
                                .font(.system(size: 13, weight: .medium))
                                .foregroundStyle(Color(hex: "5D7890"))
                        }
                        Spacer()
                        Button {
                            dismiss()
                        } label: {
                            Image(systemName: "xmark")
                                .font(.system(size: 14, weight: .bold))
                                .foregroundStyle(Color(hex: "2A79BB"))
                                .frame(width: 36, height: 36)
                                .background(XAgeCapsuleFill())
                        }
                        .frame(width: 44, height: 44)
                        .contentShape(Rectangle())
                        .buttonStyle(.plain)
                        .accessibilityLabel("关闭\(kind.rawValue)原理")
                    }

                    VStack(alignment: .leading, spacing: 10) {
                        Text("先看结论")
                            .font(.system(size: 17, weight: .bold))
                            .foregroundStyle(Color(hex: "173F64"))
                        Text(metric.simpleExplanation)
                            .font(.system(size: 14))
                            .foregroundStyle(Color(hex: "496A83"))
                            .lineSpacing(4)
                            .fixedSize(horizontal: false, vertical: true)
                        DisclosureGroup {
                            Text(metric.explanation)
                                .font(.system(size: 13))
                                .foregroundStyle(Color(hex: "5D7890"))
                                .lineSpacing(4)
                                .fixedSize(horizontal: false, vertical: true)
                                .padding(.top, 6)
                        } label: {
                            Text("专业依据")
                                .font(.system(size: 13, weight: .bold))
                                .foregroundStyle(kind.tint)
                        }
                        .tint(kind.tint)
                    }
                    .padding(16)
                    .background(XAgeGlassCardBackground(cornerRadius: 24))

                    VStack(alignment: .leading, spacing: 10) {
                        Text("主要输入")
                            .font(.system(size: 17, weight: .bold))
                            .foregroundStyle(Color(hex: "173F64"))
                        ForEach(metric.drivers.prefix(3)) { driver in
                            HStack {
                                Text(driver.title)
                                    .font(.system(size: 13, weight: .bold))
                                    .foregroundStyle(Color(hex: "17324E"))
                                Spacer()
                                Text(driver.value)
                                    .font(.system(size: 13, weight: .bold))
                                    .foregroundStyle(kind.tint)
                            }
                            .padding(11)
                            .background(XAgeCapsuleFill())
                        }
                    }
                    .padding(16)
                    .background(XAgeGlassCardBackground(cornerRadius: 24))

                    Text(metric.nextAction)
                        .font(.system(size: 13, weight: .bold))
                        .foregroundStyle(kind.tint)
                        .lineSpacing(3)
                        .fixedSize(horizontal: false, vertical: true)
                        .padding(14)
                        .background(XAgeCapsuleFill())
                }
                .padding(24)
            }
            .scrollIndicators(.hidden)
        }
    }
}
