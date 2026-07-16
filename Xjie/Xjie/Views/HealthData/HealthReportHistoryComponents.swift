import SwiftUI

struct XAgeReportTraceSelection: Identifiable {
    let item: HealthReportHistoryItem
    let trace: HealthReportTrace
    let subjectUserID: Int
    let accountScope: String

    var id: Int { trace.workflow.id }
}

enum XAgeReportHistoryReportType: String, CaseIterable, Identifiable {
    case all = ""
    case exam
    case lab
    case imaging
    case medicalRecord = "medical_record"
    case other
    case unknown

    var id: String { rawValue }

    var title: String {
        switch self {
        case .all: return "全部类型"
        case .exam: return "体检报告"
        case .lab: return "化验报告"
        case .imaging: return "影像报告"
        case .medicalRecord: return "病历"
        case .other: return "其他报告"
        case .unknown: return "类型待确认"
        }
    }
}

struct XAgeReportHistoryEmptyState: View {
    let filtered: Bool

    var body: some View {
        VStack(spacing: 10) {
            Image(systemName: "doc.text.magnifyingglass")
                .font(.system(size: 28, weight: .bold))
                .foregroundStyle(Color(hex: "347FB7"))
            Text(filtered ? "没有符合条件的报告" : "暂无历史报告")
                .font(.system(size: 17, weight: .bold))
                .foregroundStyle(Color(hex: "173F64"))
            Text(filtered ? "调整或清除筛选条件后再试。" : "上传并建立服务器工作流后，报告会显示在这里。")
                .font(.system(size: 12, weight: .medium))
                .foregroundStyle(Color(hex: "6C8194"))
                .multilineTextAlignment(.center)
                .lineSpacing(3)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(20)
        .background(XAgeGlassCardBackground(cornerRadius: 24))
    }
}

struct XAgeReportHistoryRow: View {
    let item: HealthReportHistoryItem
    let loadingTrace: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .top, spacing: 12) {
                ZStack {
                    Circle()
                        .fill(LinearGradient(colors: [Color(hex: "238AD6"), Color(hex: "20CDB1")], startPoint: .topLeading, endPoint: .bottomTrailing))
                    Image(systemName: item.report_type == "medical_record" ? "list.clipboard.fill" : "doc.text.fill")
                        .font(.system(size: 16, weight: .bold))
                        .foregroundStyle(.white)
                }
                .frame(width: 40, height: 40)

                VStack(alignment: .leading, spacing: 4) {
                    Text(item.title)
                        .font(.system(size: 16, weight: .bold))
                        .foregroundStyle(Color(hex: "173F64"))
                        .lineLimit(1)
                    Text(item.xAgeHistoryMetadataLabel)
                        .font(.system(size: 12, weight: .medium))
                        .foregroundStyle(Color(hex: "6C8194"))
                }
                Spacer(minLength: 0)
                Text(item.xAgeWorkflowStatusLabel)
                    .font(.system(size: 11, weight: .bold))
                    .foregroundStyle(item.xAgeWorkflowStatusColor)
                    .lineLimit(1)
                    .padding(.horizontal, 9)
                    .frame(height: 28)
                    .background(XAgeCapsuleFill())
            }

            HStack(spacing: 8) {
                XAgeReportHistoryBadge(title: item.xAgeReportTypeLabel, icon: "tag.fill")
                XAgeReportHistoryBadge(title: "工作流 #\(item.workflow_id)", icon: "point.3.connected.trianglepath.dotted")
                Spacer(minLength: 0)
                if loadingTrace {
                    ProgressView().controlSize(.small).tint(Color(hex: "18AFA7"))
                } else {
                    Image(systemName: "chevron.right")
                        .font(.system(size: 12, weight: .bold))
                        .foregroundStyle(Color(hex: "7D9AB1"))
                }
            }
        }
        .padding(14)
        .background(XAgeGlassCardBackground(cornerRadius: 22))
    }
}

private struct XAgeReportHistoryBadge: View {
    let title: String
    let icon: String

    var body: some View {
        HStack(spacing: 5) {
            Image(systemName: icon).font(.system(size: 10, weight: .bold))
            Text(title).font(.system(size: 11, weight: .bold)).lineLimit(1)
        }
        .foregroundStyle(Color(hex: "347FB7"))
        .padding(.horizontal, 9)
        .frame(height: 26)
        .background(XAgeCapsuleFill())
    }
}

struct XAgeReportTraceSheet: View {
    let selection: XAgeReportTraceSelection
    @Environment(\.dismiss) private var dismiss
    @EnvironmentObject private var authManager: AuthManager
    @State private var expandedAssetID: Int?
    @State private var reviewRoute: HealthReportWorkflowRoute?

    private var trace: HealthReportTrace { selection.trace }

    var body: some View {
        NavigationStack {
            ZStack {
                XAgeLiquidBackground().ignoresSafeArea()
                Color.clear
                    .frame(width: 1, height: 1)
                    .accessibilityElement(children: .ignore)
                    .accessibilityIdentifier("xage.report.trace.root")
                    .allowsHitTesting(false)

                ScrollView {
                    VStack(alignment: .leading, spacing: 14) {
                        header
                        originalCard
                        candidatesCard
                        eventsCard
                        observationsCard
                        interpretationCard
                        scoresCard
                    }
                    .padding(24)
                }
                .scrollIndicators(.hidden)
                .accessibilityIdentifier("xage.report.trace.scroll")
            }
            .navigationDestination(item: $reviewRoute) { route in
                HealthReportReviewView(
                    route: route,
                    accountScope: selection.accountScope,
                    documentTitle: selection.item.title
                )
            }
            .onChange(of: authManager.accountScope) { _, scope in
                if scope != selection.accountScope { dismiss() }
            }
        }
    }

    private var header: some View {
        HStack(alignment: .top) {
            VStack(alignment: .leading, spacing: 4) {
                Text(selection.item.title)
                    .font(.system(size: 24, weight: .bold))
                    .foregroundStyle(Color(hex: "123E67"))
                Text("\(selection.item.xAgeHistoryMetadataLabel) · \(trace.workflow.xAgeStatusLabel)")
                    .font(.system(size: 13, weight: .medium))
                    .foregroundStyle(Color(hex: "5D7890"))
                Text("服务器工作流 #\(trace.workflow.id) · 版本 \(trace.workflow.version)")
                    .font(.caption.monospaced())
                    .foregroundStyle(Color(hex: "6C8194"))
            }
            Spacer()
            Button { dismiss() } label: {
                Image(systemName: "xmark")
                    .font(.system(size: 13, weight: .bold))
                    .foregroundStyle(Color(hex: "1268BD"))
                    .frame(width: 44, height: 44)
                    .background { XAgeCapsuleFill().frame(width: 34, height: 34) }
            }
            .buttonStyle(.plain)
            .accessibilityLabel("关闭报告追踪")
        }
    }

    private var originalCard: some View {
        traceCard("原件与页码", id: "xage.report.trace.original") {
            if trace.assets.isEmpty { traceEmpty("服务器未返回原件记录。") }
            ForEach(trace.assets) { asset in
                let pages = trace.pages.filter { $0.asset_id == asset.id }
                let pageDescription = pages.isEmpty
                    ? "服务器未返回页记录"
                    : pages.map { "页索引 \($0.page_index)" }.joined(separator: "、")
                VStack(alignment: .leading, spacing: 6) {
                    HStack {
                        Text(asset.filename).font(.subheadline.weight(.bold))
                        Spacer()
                        Button(expandedAssetID == asset.id ? "收起原件" : "查看原件") {
                            expandedAssetID = expandedAssetID == asset.id ? nil : asset.id
                        }
                        .frame(minHeight: 44)
                        .font(.caption.weight(.bold))
                        .accessibilityIdentifier("xage.report.trace.asset.\(asset.id).toggle")
                    }
                    Text("顺序 \(asset.index) · 资源 #\(asset.id) · \(pageDescription)")
                    Text("SHA-256：\(asset.sha256)").textSelection(.enabled)
                    if expandedAssetID == asset.id {
                        OriginalFileView(fileUrl: assetURL(asset.id))
                    }
                }
                .font(.caption)
                .foregroundStyle(Color(hex: "496A83"))
                .padding(12)
                .background(XAgeCapsuleFill())
            }
        }
    }

    private var candidatesCard: some View {
        traceCard("识别候选与原件定位", id: "xage.report.trace.candidates") {
            if trace.candidates.isEmpty { traceEmpty("服务器未返回识别候选。") }
            ForEach(trace.candidates) { candidate in
                VStack(alignment: .leading, spacing: 5) {
                    traceRow(candidate.name, "候选 #\(candidate.id) · 版本 \(candidate.version) · \(xAgeServerCodeLabel(candidate.status))")
                    let locators = trace.locators.filter { $0.candidate_id == candidate.id }
                    if locators.isEmpty { traceEmpty("服务器未返回该候选的定位。") }
                    ForEach(Array(locators.enumerated()), id: \.offset) { _, locator in
                        Text(locatorText(locator))
                            .font(.caption)
                            .foregroundStyle(Color(hex: "496A83"))
                    }
                }
                .padding(12)
                .background(XAgeCapsuleFill())
            }
        }
    }

    private var eventsCard: some View {
        traceCard("修正与确认事件", id: "xage.report.trace.events") {
            if trace.confirmation_events.isEmpty { traceEmpty("服务器尚未返回修正或确认事件。") }
            ForEach(trace.confirmation_events) { event in
                let name = trace.candidates.first { $0.id == event.candidate_id }?.name ?? "候选 #\(event.candidate_id)"
                traceRow(xAgeServerCodeLabel(event.event_type), "\(name) · 事件 #\(event.id)")
            }
        }
    }

    private var observationsCard: some View {
        traceCard("结构化 Observation", id: "xage.report.trace.observations") {
            if trace.observations.isEmpty { traceEmpty("服务器尚未返回已写入的 Observation。") }
            ForEach(trace.observations) { observation in
                traceRow(observation.name, "Observation #\(observation.id) · 候选 #\(observation.candidate_id) · \(xAgeServerCodeLabel(observation.status))")
            }
        }
    }

    private var interpretationCard: some View {
        traceCard("报告解读与字段详情", id: "xage.report.trace.interpretation") {
            Text("进入服务器报告详情，可查看原始值、修正值、确认结果和可用解读。")
                .font(.caption)
                .foregroundStyle(Color(hex: "6C8194"))
            Button { openReview() } label: {
                Label("进入服务器报告详情", systemImage: "checklist")
                    .font(.body.weight(.bold))
                    .foregroundStyle(.white)
                    .frame(maxWidth: .infinity, minHeight: 50)
                    .background(Capsule().fill(LinearGradient(colors: [Color(hex: "238AD6"), Color(hex: "20CDB1")], startPoint: .leading, endPoint: .trailing)))
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("xage.report.review.open")
        }
    }

    private var scoresCard: some View {
        traceCard("评分与随访追踪", id: "xage.report.trace.scores") {
            if trace.score_jobs.isEmpty { traceEmpty("服务器未返回评分任务。") }
            ForEach(trace.score_jobs) { job in
                traceRow("评分任务 #\(job.id) · \(xAgeServerCodeLabel(job.status))", "输入版本 \(job.input_revision) · manifest \(job.manifest_digest)")
            }
            if trace.score_items.isEmpty { traceEmpty("服务器未返回评分项。") }
            ForEach(trace.score_items) { item in
                traceRow("评分项 \(item.kind) · \(xAgeServerCodeLabel(item.status))", "#\(item.id) · 任务 #\(item.job_id)")
            }
            if trace.score_snapshots.isEmpty { traceEmpty("服务器未返回评分快照。") }
            ForEach(trace.score_snapshots) { snapshot in
                traceRow("快照 \(snapshot.kind) · \(xAgeServerCodeLabel(snapshot.status))", "#\(snapshot.id) · 算法 \(snapshot.algorithm_version)")
            }
            if trace.follow_ups.isEmpty { traceEmpty("服务器未返回随访记录。") }
            ForEach(trace.follow_ups) { followUp in
                traceRow("随访 \(followUp.code) · \(xAgeServerCodeLabel(followUp.status))", "#\(followUp.id) · 规则 \(followUp.rule_version)")
            }
        }
    }

    private func traceCard<Content: View>(_ title: String, id: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(title).font(.system(size: 17, weight: .bold)).foregroundStyle(Color(hex: "173F64"))
            content()
        }
        .padding(16)
        .background(XAgeGlassCardBackground(cornerRadius: 24))
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier(id)
    }

    private func traceRow(_ title: String, _ detail: String) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(title).font(.subheadline.weight(.bold))
            Text(detail).font(.caption)
        }
        .foregroundStyle(Color(hex: "496A83"))
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(XAgeCapsuleFill())
    }

    private func traceEmpty(_ text: String) -> some View {
        Text(text)
            .font(.caption)
            .foregroundStyle(Color(hex: "6C8194"))
            .padding(12)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(XAgeCapsuleFill())
    }

    private func openReview() {
        // Child counts never derive workflow status; trace.workflow is authoritative.
        reviewRoute = HealthReportWorkflowRoute(
            workflowID: trace.workflow.id,
            subjectUserID: selection.subjectUserID,
            status: HealthReportWorkflowStatus(rawValue: trace.workflow.status),
            isDuplicate: false
        )
    }

    private func assetURL(_ assetID: Int) -> String {
        URLBuilder.path(
            "/api/health-data/report-workflows/\(trace.workflow.id)/assets/\(assetID)/content",
            queryItems: [URLQueryItem(name: "subject_user_id", value: String(selection.subjectUserID))]
        )
    }

    private func locatorText(_ locator: HealthReportTraceLocator) -> String {
        let page = trace.pages.first { $0.id == locator.page_id }
        let asset = page.flatMap { value in trace.assets.first { $0.id == value.asset_id } }
        let source = [asset?.filename, page.map { "页索引 \($0.page_index)" }, "角色 \(locator.role)"].compactMap { $0 }.joined(separator: " · ")
        return "\(source) · bbox [\(locator.bbox.map { String(format: "%.3f", $0) }.joined(separator: ", "))]"
    }
}

extension HealthReportHistoryItem {
    var xAgeReportTypeLabel: String {
        XAgeReportHistoryReportType(rawValue: report_type)?.title ?? "服务器类型：\(report_type)"
    }

    var xAgeHistoryMetadataLabel: String {
        let date = report_date ?? String(created_at.prefix(10))
        let hospitalName = hospital?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return [date.isEmpty ? "日期待确认" : date, hospitalName.isEmpty ? "医院待确认" : hospitalName, xAgeReportTypeLabel].joined(separator: " · ")
    }

    var xAgeWorkflowStatusLabel: String { HealthReportWorkflowStatus(rawValue: status).xAgeHistoryLabel }
    var xAgeWorkflowStatusColor: Color { HealthReportWorkflowStatus(rawValue: status).xAgeHistoryColor }
}

private extension HealthReportTraceWorkflow {
    var xAgeStatusLabel: String { HealthReportWorkflowStatus(rawValue: status).xAgeHistoryLabel }
}

private extension HealthReportWorkflowStatus {
    var xAgeHistoryLabel: String {
        switch self {
        case .draft: return "草稿"
        case .uploading: return "上传中"
        case .recognizing: return "识别中"
        case .awaitingConfirmation: return "待确认"
        case .committing: return "入库中"
        case .completedScorePending: return "已确认 · 评分待更新"
        case .completed: return "可信完成"
        case .failed: return "处理失败"
        case .unknown(let value): return "服务器状态：\(value)"
        }
    }

    var xAgeHistoryColor: Color {
        switch self {
        case .completed: return Color(hex: "18AFA7")
        case .completedScorePending: return Color(hex: "C57A27")
        case .failed: return Color(hex: "D85A66")
        default: return Color(hex: "238AD6")
        }
    }
}

private func xAgeServerCodeLabel(_ rawValue: String) -> String {
    switch rawValue.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() {
    case "pending", "pending_review": return "待处理"
    case "confirmed", "confirm": return "已确认"
    case "corrected", "correct": return "已修正"
    case "rejected", "reject": return "已拒绝"
    case "active": return "有效"
    case "queued": return "排队中"
    case "running": return "处理中"
    case "completed", "succeeded": return "已完成"
    case "failed": return "失败"
    default: return "服务器值：\(rawValue)"
    }
}

extension Array where Element == HealthDocument {
    func sortedForXAgeHistory() -> [HealthDocument] {
        sorted { lhs, rhs in
            if lhs.xAgeHistorySortKey == rhs.xAgeHistorySortKey { return lhs.id > rhs.id }
            return lhs.xAgeHistorySortKey > rhs.xAgeHistorySortKey
        }
    }
}

extension HealthDocument {
    var xAgeDateLabel: String {
        if let date = Self.nonEmptyHistoryValue(doc_date) { return Utils.formatDate(date) }
        if let date = Self.nonEmptyHistoryValue(created_at) { return Utils.formatDate(date) }
        return "日期待确认"
    }

    var xAgeHistoryMetadataLabel: String {
        "\(xAgeDateLabel) · \(xAgeHospitalLabel) · \(xAgeDocumentTypeLabel)"
    }

    fileprivate var xAgeHistorySortKey: String {
        Self.nonEmptyHistoryValue(doc_date) ?? Self.nonEmptyHistoryValue(created_at) ?? ""
    }

    private var xAgeHospitalLabel: String {
        Self.nonEmptyHistoryValue(hospital) ?? "医院待确认"
    }

    private var xAgeDocumentTypeLabel: String {
        switch Self.nonEmptyHistoryValue(doc_type)?.lowercased() {
        case "exam": return "体检报告"
        case "record": return "病历"
        case "report": return "检查报告"
        case "lab": return "化验报告"
        case "imaging": return "影像报告"
        case "prescription": return "处方"
        case .some: return "其他健康资料"
        case nil: return "类型待确认"
        }
    }

    private static func nonEmptyHistoryValue(_ value: String?) -> String? {
        let trimmed = value?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return trimmed.isEmpty ? nil : trimmed
    }
}
