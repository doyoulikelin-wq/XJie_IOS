import SwiftUI

/// 将服务端报告数据收敛为普通用户可读文案。
///
/// Release 页面只能使用这里的白名单字段与兜底文案，不能直接展示 schema key、
/// 原始 JSON、算法代码或失败代码；Debug 诊断信息由页面单独放在条件编译块中。
enum HealthReportInterpretationUserPresentation {
    struct ProfileCandidate: Equatable {
        let title: String
        let summary: String
    }

    struct ScoreSnapshot: Equatable {
        let kindTitle: String
        let directionSummary: String?
        let methodSummary: String?
        let inputBasisSummary: String?
        let evidenceSummary: String?
        let missingInputsSummary: String?
        let failureSummary: String?
    }

    /// 生成健康画像候选的用户标题和摘要；未知字典键一律不会进入结果。
    static func profileCandidate(
        for impact: HealthReportProfileImpact
    ) -> ProfileCandidate {
        let serverTitle = safeServerText(
            impact.proposed_value["canonical_name"]?.stringValue
        )
        let title = serverTitle.map(candidateTitle) ?? categoryTitle(impact.category)

        let value = scalarValue(
            impact.proposed_value["latest_value_numeric"]
                ?? impact.proposed_value["latest_value_text"]
                ?? impact.proposed_value["value_numeric"]
                ?? impact.proposed_value["value_text"]
        )
        let unit = scalarValue(impact.proposed_value["unit"])
        let summary: String
        if let value {
            let valueAndUnit = [value, unit]
                .compactMap { $0 }
                .joined(separator: " ")
            summary = "待复核候选值：\(valueAndUnit)"
        } else if let count = scalarValue(impact.proposed_value["occurrence_count"]) {
            summary = "本次报告中共有 \(count) 条相关记录，等待复核。"
        } else {
            summary = "已生成一项待复核的画像候选。"
        }

        return ProfileCandidate(title: title, summary: summary)
    }

    /// 生成评分快照的用户文案；证据与缺失输入仅显示状态，不显示原始字典。
    static func scoreSnapshot(
        for snapshot: HealthReportScoreSnapshot
    ) -> ScoreSnapshot {
        let method = safeServerText(
            snapshot.method_summary?["text"]?.stringValue
        ).map { "方法：\($0)" }

        let inputLabels = (snapshot.input_basis ?? []).compactMap { item in
            safeServerText(item["label"]?.objectValue?["text"]?.stringValue)
        }
        let inputSummary: String?
        if !inputLabels.isEmpty {
            inputSummary = "输入依据：\(inputLabels.joined(separator: "、"))"
        } else if let inputBasis = snapshot.input_basis, !inputBasis.isEmpty {
            inputSummary = "输入依据：本次报告中已确认的数据"
        } else {
            inputSummary = nil
        }

        let safeFailure = safeServerText(
            snapshot.failure?["message"]?.objectValue?["text"]?.stringValue
        )
        let failureSummary: String?
        if let safeFailure {
            failureSummary = "未完成原因：\(safeFailure)"
        } else if snapshot.calculation_status == "failed"
                    || !(snapshot.failure_code?.isEmpty ?? true)
                    || !(snapshot.failure?.isEmpty ?? true) {
            failureSummary = "本项评分暂未完成，请稍后再查看。"
        } else {
            failureSummary = nil
        }

        return ScoreSnapshot(
            kindTitle: scoreKindTitle(snapshot.score_kind),
            directionSummary: scoreDirectionSummary(snapshot.score_direction),
            methodSummary: method,
            inputBasisSummary: inputSummary,
            evidenceSummary: snapshot.evidence.isEmpty
                ? nil
                : "已依据本次报告中已确认的数据进行计算。",
            missingInputsSummary: snapshot.missing_inputs.isEmpty
                ? nil
                : "部分必要信息尚未确认，本项暂不计算。",
            failureSummary: failureSummary
        )
    }

    /// 服务端随访文案缺失或疑似内部代码时，使用稳定的用户兜底文案。
    static func followUpTitle(for detail: HealthReportFollowUpDetail) -> String {
        safeServerText(detail.message["text"]?.stringValue) ?? "请查看本次随访建议"
    }

    /// 清理旧版随访字符串；无法确认是用户文案的条目不会直接展示。
    static func followUpItems(_ items: [String]) -> [String] {
        items.compactMap(safeServerText)
    }

    static func unavailableReason(_ reason: String?, fallback: String) -> String {
        safeServerText(reason) ?? fallback
    }

    static func notice(_ notice: String) -> String {
        safeServerText(notice) ?? "本解读仅供健康管理参考，不构成诊断或治疗建议。"
    }

    static func eventTitle(_ type: String) -> String {
        switch type {
        case "confirm": return "确认"
        case "correct": return "修正"
        case "reject": return "未采用"
        case "manual_add": return "手动补录"
        default: return "状态已更新"
        }
    }

    private static func scoreKindTitle(_ kind: String) -> String {
        switch kind {
        case "stress": return "压力"
        case "recovery": return "恢复"
        case "inflammation": return "炎症"
        default: return "其他健康评分"
        }
    }

    private static func scoreDirectionSummary(_ direction: String?) -> String? {
        guard let direction = direction?.trimmingCharacters(in: .whitespacesAndNewlines),
              !direction.isEmpty else {
            return nil
        }
        switch direction {
        case "higher_is_better": return "服务端定义：数值越高越好"
        case "lower_is_better": return "服务端定义：数值越低越好"
        default: return "评分方向暂无法确认"
        }
    }

    private static func categoryTitle(_ category: String) -> String {
        switch category {
        case "basic": return "基本健康信息候选"
        case "safety": return "健康安全信息候选"
        case "long_term_health": return "长期健康趋势候选"
        case "goals": return "健康目标候选"
        case "medication": return "用药信息候选"
        default: return "健康画像候选"
        }
    }

    private static func candidateTitle(_ title: String) -> String {
        title.hasSuffix("候选") ? title : "\(title)候选"
    }

    /// 将 JSON 值投影为安全标量；对象、数组与疑似内部代码全部拒绝。
    static func scalarValue(_ value: HealthReportJSONValue?) -> String? {
        guard let value else { return nil }
        switch value {
        case .string(let value):
            return safeServerText(value)
        case .number(let value):
            if value.rounded() == value { return String(Int(value)) }
            return String(format: "%.4f", value)
                .replacingOccurrences(
                    of: #"\.?0+$"#,
                    with: "",
                    options: .regularExpression
                )
        case .bool(let value):
            return value ? "是" : "否"
        case .object, .array, .null:
            return nil
        }
    }

    /// 仅接受像自然语言的短文案，拒绝 schema 名、JSON 片段和点号/下划线代码。
    private static func safeServerText(_ value: String?) -> String? {
        guard let value else { return nil }
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }

        let lowercased = trimmed.lowercased()
        let internalFragments = [
            "fact_key",
            "proposed_value",
            "evidence",
            "missing_inputs",
            "failure_code",
            "snapshot_id",
            "workflow_id",
            "observation_ids",
            "item_code",
            "algorithm_id",
            "algorithm_version",
        ]
        guard !internalFragments.contains(where: lowercased.contains) else { return nil }
        let internalTokens: Set<String> = [
            "accepted",
            "completed",
            "conflict",
            "failed",
            "null",
            "pending",
            "pending_review",
            "processing",
            "recognizing",
            "rejected",
            "superseded",
        ]
        guard !internalTokens.contains(lowercased) else { return nil }
        guard !trimmed.contains("{") && !trimmed.contains("}")
                && !trimmed.contains("\"") && !trimmed.contains("[")
                && !trimmed.contains("]") else {
            return nil
        }

        let hasHanCharacter = trimmed.range(
            of: #"\p{Han}"#,
            options: .regularExpression
        ) != nil
        let containsWhitespace = trimmed.rangeOfCharacter(from: .whitespacesAndNewlines) != nil
        if !hasHanCharacter,
           !containsWhitespace,
           trimmed.contains(where: { $0 == "_" || $0 == "." }) {
            return nil
        }
        return trimmed
    }
}

struct HealthReportInterpretationView: View {
    @Environment(\.dismiss) private var dismiss
    @ObservedObject var viewModel: HealthReportReviewViewModel
    let documentTitle: String
    @State private var localOriginals: [HealthReportLocalOriginalMetadata] = []
    @State private var expandedLocalAssetIndex: Int?

    var body: some View {
        ZStack {
            XAgeLiquidBackground()
                .ignoresSafeArea()

            VStack(spacing: 0) {
                header
                    .padding(.horizontal, 20)
                    .padding(.top, 10)

                ScrollView {
                    VStack(alignment: .leading, spacing: 14) {
                        if viewModel.loadingInterpretation,
                           viewModel.interpretation == nil {
                            loadingCard
                        } else if let message = viewModel.interpretationErrorMessage,
                                  viewModel.interpretation == nil {
                            errorCard(message)
                        } else if let interpretation = viewModel.interpretation {
                            noticeCard(interpretation)
                            if interpretation.available {
                                abnormalitiesCard(interpretation)
                                followUpCard(interpretation)
                                scoreCard(interpretation)
                                profileCard(interpretation)
                                additionsCard(interpretation)
                                provenanceCard(interpretation)
                                originalCard(interpretation)
                            } else {
                                unavailableCard(interpretation)
                            }
                        } else {
                            errorCard("尚未读取到本次解读。下拉刷新后重试。")
                        }
                    }
                    .padding(.horizontal, 20)
                    .padding(.top, 14)
                    .padding(.bottom, 32)
                }
                .accessibilityIdentifier("xage.report.interpretation.scroll")
                .refreshable { await viewModel.loadInterpretation(force: true) }
            }
        }
        .navigationBarBackButtonHidden(true)
        .task { await viewModel.loadInterpretation() }
        .task { await loadLocalOriginals() }
    }

    private var header: some View {
        HStack(alignment: .center, spacing: 12) {
            Button { dismiss() } label: {
                Image(systemName: "chevron.left")
                    .font(.headline.weight(.bold))
                    .foregroundStyle(Color(hex: "347FB7"))
                    .frame(width: 44, height: 44)
                    .background(XAgeCapsuleFill())
            }
            .buttonStyle(.plain)
            .accessibilityLabel("返回报告复核")
            .accessibilityIdentifier("xage.report.interpretation.back")

            VStack(alignment: .leading, spacing: 2) {
                Text("本次报告解读")
                    .font(.headline.weight(.bold))
                    .foregroundStyle(Color(hex: "123E67"))
                    .accessibilityIdentifier("xage.report.interpretation.root")
                Text(documentTitle)
                    .font(.caption)
                    .foregroundStyle(Color(hex: "5D7890"))
                    .lineLimit(2)
            }
            Spacer(minLength: 8)
        }
    }

    private var loadingCard: some View {
        HStack(spacing: 12) {
            ProgressView()
                .tint(Color(hex: "18AFA7"))
            Text("正在读取已确认字段、来源和评分快照…")
                .font(.subheadline.weight(.medium))
                .foregroundStyle(Color(hex: "5D7890"))
        }
        .frame(maxWidth: .infinity, minHeight: 112)
        .padding(16)
        .background(XAgeGlassCardBackground(cornerRadius: 24))
    }

    private func errorCard(_ message: String) -> some View {
        sectionCard(title: "暂时无法读取", icon: "exclamationmark.triangle.fill") {
            Text(message)
                .font(.subheadline)
                .foregroundStyle(Color(hex: "6C8194"))
                .fixedSize(horizontal: false, vertical: true)
            Text("可下拉刷新；读取失败不会生成或猜测报告结论。")
                .font(.caption)
                .foregroundStyle(Color(hex: "6C8194"))
        }
        .accessibilityIdentifier("xage.report.interpretation.error")
    }

    private func noticeCard(_ interpretation: HealthReportInterpretation) -> some View {
        sectionCard(title: "解读边界", icon: "checkmark.shield.fill") {
            Text(HealthReportInterpretationUserPresentation.notice(
                interpretation.non_diagnostic_notice
            ))
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(Color(hex: "173F64"))
                .fixedSize(horizontal: false, vertical: true)
            Text("只展示你已确认的结构化数据和实际记录；没有证据的影响不会补写。")
                .font(.caption)
                .foregroundStyle(Color(hex: "6C8194"))
                .fixedSize(horizontal: false, vertical: true)
        }
        .accessibilityIdentifier("xage.report.interpretation.notice")
    }

    private func unavailableCard(_ interpretation: HealthReportInterpretation) -> some View {
        sectionCard(title: "解读尚不可用", icon: "clock.badge.exclamationmark") {
            Text(HealthReportInterpretationUserPresentation.unavailableReason(
                interpretation.unavailable_reason,
                fallback: "报告尚未完成确认。"
            ))
                .font(.subheadline)
                .foregroundStyle(Color(hex: "6C8194"))
                .fixedSize(horizontal: false, vertical: true)
        }
        .accessibilityIdentifier("xage.report.interpretation.unavailable")
    }

    private func abnormalitiesCard(_ interpretation: HealthReportInterpretation) -> some View {
        sectionCard(title: "已确认的异常项", icon: "exclamationmark.triangle.fill") {
            if interpretation.major_abnormalities.isEmpty {
                Text("本次已确认字段中，没有服务端标记为异常的项目。这不等同于排除其他健康问题。")
                    .font(.subheadline)
                    .foregroundStyle(Color(hex: "6C8194"))
                    .fixedSize(horizontal: false, vertical: true)
            } else {
                ForEach(interpretation.major_abnormalities) { observation in
                    observationRow(observation, showsProvenance: true)
                }
            }
        }
        .accessibilityIdentifier("xage.report.interpretation.abnormalities")
    }

    private func followUpCard(_ interpretation: HealthReportInterpretation) -> some View {
        sectionCard(title: "随访与复查信息", icon: "calendar.badge.clock") {
            if interpretation.follow_up.available {
                let details = interpretation.follow_up.details ?? []
                if !details.isEmpty {
                    ForEach(details) { detail in
                        VStack(alignment: .leading, spacing: 5) {
                            Label(
                                HealthReportInterpretationUserPresentation.followUpTitle(
                                    for: detail
                                ),
                                systemImage: "checkmark.seal.fill"
                            )
                            .font(.subheadline.weight(.semibold))
                            .foregroundStyle(Color(hex: "173F64"))
                            if let dueAt = detail.due_at, !dueAt.isEmpty {
                                Text("建议时间：\(dueAt)")
                                    .font(.caption)
                                    .foregroundStyle(Color(hex: "6C8194"))
                            }
                            Text("依据：\(detail.evidence.count) 条已确认证据")
                                .font(.caption2)
                                .foregroundStyle(Color(hex: "7890A4"))
                        }
                        .padding(12)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(Color.white.opacity(0.42), in: RoundedRectangle(cornerRadius: 16))
                    }
                } else if !interpretation.follow_up.items.isEmpty {
                    let items = HealthReportInterpretationUserPresentation.followUpItems(
                        interpretation.follow_up.items
                    )
                    if items.isEmpty {
                        Text("当前没有可展示的已确认随访信息。")
                            .font(.subheadline)
                            .foregroundStyle(Color(hex: "6C8194"))
                    } else {
                        ForEach(items, id: \.self) { item in
                            Label(item, systemImage: "circle.fill")
                                .font(.subheadline)
                                .foregroundStyle(Color(hex: "173F64"))
                        }
                    }
                } else {
                    Text("当前没有可展示的已确认随访信息。")
                        .font(.subheadline)
                        .foregroundStyle(Color(hex: "6C8194"))
                }
            } else {
                Text(HealthReportInterpretationUserPresentation.unavailableReason(
                    interpretation.follow_up.unavailable_reason,
                    fallback: "没有经过确认的随访信息。"
                ))
                    .font(.subheadline)
                    .foregroundStyle(Color(hex: "6C8194"))
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .accessibilityIdentifier("xage.report.interpretation.followUp")
    }

    private func scoreCard(_ interpretation: HealthReportInterpretation) -> some View {
        sectionCard(title: "压力、恢复与炎症评分", icon: "gauge.with.dots.needle.67percent") {
            Text(scoreHeadline(interpretation))
                .font(.subheadline.weight(.bold))
                .foregroundStyle(interpretation.score_pending ? Color(hex: "C57A27") : Color(hex: "173F64"))
                .fixedSize(horizontal: false, vertical: true)

            if interpretation.score_snapshots.isEmpty {
                Text("当前没有可展示的评分快照，因此不会显示推测的分数变化。")
                    .font(.caption)
                    .foregroundStyle(Color(hex: "6C8194"))
                    .fixedSize(horizontal: false, vertical: true)
            } else {
                ForEach(interpretation.score_snapshots) { snapshot in
                    scoreSnapshotRow(snapshot)
                }
            }
        }
        .accessibilityIdentifier("xage.report.interpretation.scores")
    }

    private func profileCard(_ interpretation: HealthReportInterpretation) -> some View {
        sectionCard(
            title: "健康画像候选",
            icon: "person.text.rectangle.fill",
            staticTitleIdentifier: "xage.report.interpretation.profile"
        ) {
            let groups = profileImpactGroups(interpretation.profile_impacts)
            if groups.isEmpty {
                Text("本次报告没有生成可追溯的画像候选；系统不会据此宣称画像已改变。")
                    .font(.subheadline)
                    .foregroundStyle(Color(hex: "6C8194"))
                    .fixedSize(horizontal: false, vertical: true)
            } else {
                ForEach(groups) { group in
                    let presentation = HealthReportInterpretationUserPresentation.profileCandidate(
                        for: group.impact
                    )
                    VStack(alignment: .leading, spacing: 5) {
                        HStack {
                            Text(presentation.title)
                                .font(.subheadline.weight(.bold))
                                .foregroundStyle(Color(hex: "173F64"))
                            Spacer()
                            Text(profileStatusLabel(group.impact.review_status))
                                .font(.caption.weight(.bold))
                                .foregroundStyle(Color(hex: "347FB7"))
                        }
                        Text(presentation.summary)
                            .font(.caption)
                            .foregroundStyle(Color(hex: "496A83"))
                            .textSelection(.enabled)
                        #if DEBUG
                        Text("调试字段：\(group.impact.fact_key)")
                            .font(.caption2)
                            .foregroundStyle(Color(hex: "7890A4"))
                            .textSelection(.enabled)
                        Text("调试候选值：\(debugDictionaryDisplay(group.impact.proposed_value))")
                            .font(.caption2)
                            .foregroundStyle(Color(hex: "7890A4"))
                            .textSelection(.enabled)
                        #endif
                        Text("\(group.sourceObservationIDs.count) 条观测来源 · 候选只计为 1 项")
                            .font(.caption2)
                            .foregroundStyle(Color(hex: "6C8194"))
                    }
                    .padding(12)
                    .background(Color.white.opacity(0.42), in: RoundedRectangle(cornerRadius: 16))
                    .accessibilityElement(children: .contain)
                    .accessibilityIdentifier(
                        "xage.report.interpretation.profileCandidate.\(group.id)"
                    )
                }
                Text("画像候选需要按其复核状态处理；未接受的候选不代表画像事实已经更新。")
                    .font(.caption)
                    .foregroundStyle(Color(hex: "6C8194"))
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private func additionsCard(_ interpretation: HealthReportInterpretation) -> some View {
        sectionCard(title: "本次加入的结构化数据", icon: "tray.and.arrow.down.fill") {
            if interpretation.structured_additions.isEmpty {
                Text("没有处于有效状态的已确认观测。")
                    .font(.subheadline)
                    .foregroundStyle(Color(hex: "6C8194"))
            } else {
                ForEach(interpretation.structured_additions) { observation in
                    observationRow(observation, showsProvenance: false)
                }
            }
        }
        .accessibilityIdentifier("xage.report.interpretation.additions")
    }

    private func provenanceCard(_ interpretation: HealthReportInterpretation) -> some View {
        sectionCard(
            title: "识别、修正与确认记录",
            icon: "point.3.connected.trianglepath.dotted",
            staticTitleIdentifier: "xage.report.interpretation.provenance"
        ) {
            if interpretation.candidates.isEmpty {
                Text("没有候选字段记录。")
                    .font(.subheadline)
                    .foregroundStyle(Color(hex: "6C8194"))
            } else {
                ForEach(interpretation.candidates) { candidate in
                    VStack(alignment: .leading, spacing: 4) {
                        Text(candidate.canonical_name)
                            .font(.subheadline.weight(.bold))
                            .foregroundStyle(Color(hex: "173F64"))
                        Text("原始：\(candidate.originalValueLabel)")
                            .font(.caption)
                            .foregroundStyle(Color(hex: "6C8194"))
                        Text("确认后：\(candidate.candidateValueLabel) · \(candidateReviewLabel(candidate.review_status))")
                            .font(.caption)
                            .foregroundStyle(Color(hex: "496A83"))
                        let sourceDescription = {
                            #if DEBUG
                            return "候选 #\(candidate.candidate_id) · \(candidate.sourceLocationLabel)"
                            #else
                            return candidate.sourceLocationLabel
                            #endif
                        }()
                        Text(sourceDescription)
                            .font(.caption2)
                            .foregroundStyle(Color(hex: "7890A4"))
                    }
                    .padding(10)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(Color.white.opacity(0.42), in: RoundedRectangle(cornerRadius: 14))
                }
            }

            if !interpretation.confirmation_events.isEmpty {
                Divider()
                Text("确认记录")
                    .font(.caption.weight(.bold))
                    .foregroundStyle(Color(hex: "6C8194"))
                ForEach(interpretation.confirmation_events) { event in
                    let eventDescription = {
                        #if DEBUG
                        return "#\(event.event_id) · 候选 #\(event.candidate_id) · \(eventLabel(event.event_type)) · \(eventChangeLabel(event))"
                        #else
                        return "\(eventLabel(event.event_type)) · \(eventChangeLabel(event))"
                        #endif
                    }()
                    Text(eventDescription)
                        .font(.caption)
                        .foregroundStyle(Color(hex: "496A83"))
                        .textSelection(.enabled)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
    }

    @ViewBuilder
    private func originalCard(_ interpretation: HealthReportInterpretation) -> some View {
        if !localOriginals.isEmpty,
           let accountScope = viewModel.localOriginalAccountScope {
            sectionCard(
                title: "报告原件",
                icon: "doc.richtext.fill",
                staticTitleIdentifier: "xage.report.interpretation.original"
            ) {
                ForEach(localOriginals) { asset in
                    VStack(alignment: .leading, spacing: 8) {
                        HStack {
                            Text(asset.fileName)
                                .font(.subheadline.weight(.semibold))
                                .lineLimit(2)
                            Spacer(minLength: 8)
                            Button(
                                expandedLocalAssetIndex == asset.assetIndex ? "收起" : "查看原件"
                            ) {
                                expandedLocalAssetIndex = expandedLocalAssetIndex == asset.assetIndex
                                    ? nil
                                    : asset.assetIndex
                            }
                            .buttonStyle(.bordered)
                        }
                        Text("第 \(asset.assetIndex) 页 · 本机保存")
                            .font(.caption)
                            .foregroundStyle(Color(hex: "6C8194"))
                        if expandedLocalAssetIndex == asset.assetIndex {
                            OriginalFileView(
                                workflowID: viewModel.route.workflowID,
                                assetIndex: asset.assetIndex,
                                fileUrl: nil,
                                accountScope: accountScope,
                                subjectUserID: viewModel.route.subjectUserID
                            )
                        }
                    }
                    .padding(12)
                    .background(Color.white.opacity(0.42), in: RoundedRectangle(cornerRadius: 16))
                }
            }
        } else if let fileURL = interpretation.originalFileURL,
           !fileURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            sectionCard(
                title: "原始报告",
                icon: "doc.richtext.fill",
                staticTitleIdentifier: "xage.report.interpretation.original"
            ) {
                OriginalFileView(fileUrl: fileURL)
            }
        } else {
            sectionCard(
                title: "原始报告",
                icon: "doc.richtext.fill",
                staticTitleIdentifier: "xage.report.interpretation.originalUnavailable"
            ) {
                Text("这份报告在本机没有可读取的原件；已确认字段和来源记录仍保留。")
                    .font(.subheadline)
                    .foregroundStyle(Color(hex: "6C8194"))
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    /// 只读取本机轻量 manifest；失败不会影响已确认解读，也不会回退成跨账号网络请求。
    @MainActor
    private func loadLocalOriginals() async {
        guard let accountScope = viewModel.localOriginalAccountScope,
              AuthManager.shared.accountScope == accountScope else {
            localOriginals = []
            return
        }
        do {
            localOriginals = try await HealthReportLocalOriginalStore.shared.listAssets(
                workflowID: viewModel.route.workflowID,
                accountScope: accountScope,
                subjectUserID: viewModel.route.subjectUserID
            )
        } catch {
            localOriginals = []
        }
    }

    private func observationRow(
        _ observation: HealthReportObservation,
        showsProvenance: Bool
    ) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack(alignment: .firstTextBaseline) {
                Text(observation.canonical_name)
                    .font(.subheadline.weight(.bold))
                    .foregroundStyle(Color(hex: "173F64"))
                Spacer(minLength: 8)
                Text(observation.abnormal_state == "abnormal" ? "异常" : "已确认")
                    .font(.caption.weight(.bold))
                    .foregroundStyle(observation.abnormal_state == "abnormal" ? Color(hex: "C56A25") : Color(hex: "18AFA7"))
            }
            Text(observationValue(observation))
                .font(.body.weight(.semibold))
                .foregroundStyle(Color(hex: "173F64"))
                .textSelection(.enabled)
            Text("参考：\(observationReference(observation))")
                .font(.caption)
                .foregroundStyle(Color(hex: "6C8194"))
            if showsProvenance {
                #if DEBUG
                Text("观测 #\(observation.observation_id) · 候选 #\(observation.source_candidate_id) · 确认事件 #\(observation.confirmation_event_id)")
                    .font(.caption2)
                    .foregroundStyle(Color(hex: "7890A4"))
                #else
                Text("来源：本报告中已经核对确认的字段")
                    .font(.caption2)
                    .foregroundStyle(Color(hex: "7890A4"))
                #endif
            }
        }
        .padding(12)
        .background(Color.white.opacity(0.42), in: RoundedRectangle(cornerRadius: 16))
    }

    private func scoreSnapshotRow(_ snapshot: HealthReportScoreSnapshot) -> some View {
        let presentation = HealthReportInterpretationUserPresentation.scoreSnapshot(
            for: snapshot
        )
        return VStack(alignment: .leading, spacing: 5) {
            HStack {
                Text(presentation.kindTitle)
                    .font(.subheadline.weight(.bold))
                    .foregroundStyle(Color(hex: "173F64"))
                Spacer()
                Text(scoreStatusLabel(snapshot.calculation_status))
                    .font(.caption.weight(.bold))
                    .foregroundStyle(snapshot.calculation_status == "completed" ? Color(hex: "18AFA7") : Color(hex: "C57A27"))
            }
            Text(scoreValueLabel(snapshot))
                .font(.body.weight(.semibold))
                .foregroundStyle(Color(hex: "173F64"))
                .textSelection(.enabled)
            if let outcome = snapshot.semantic_outcome {
                Text("结果：\(semanticOutcomeLabel(outcome))")
                    .font(.caption)
                    .foregroundStyle(Color(hex: "496A83"))
            }
            if let confidence = scoreConfidenceLabel(snapshot) {
                Text("置信度：\(confidence)")
                    .font(.caption)
                    .foregroundStyle(Color(hex: "6C8194"))
                    .textSelection(.enabled)
            }
            if let direction = presentation.directionSummary {
                Text(direction)
                    .font(.caption2)
                    .foregroundStyle(Color(hex: "6C8194"))
            }
            #if DEBUG
            Text("算法：\(snapshot.algorithm_id) · \(snapshot.algorithm_version)")
                .font(.caption2)
                .foregroundStyle(Color(hex: "6C8194"))
                .textSelection(.enabled)
            if let direction = snapshot.score_direction, !direction.isEmpty {
                Text("调试方向代码：\(direction)")
                    .font(.caption2)
                    .foregroundStyle(Color(hex: "7890A4"))
                    .textSelection(.enabled)
            }
            #endif
            if let method = presentation.methodSummary {
                Text(method)
                    .font(.caption)
                    .foregroundStyle(Color(hex: "496A83"))
                    .fixedSize(horizontal: false, vertical: true)
            }
            if let inputBasis = presentation.inputBasisSummary {
                Text(inputBasis)
                    .font(.caption2)
                    .foregroundStyle(Color(hex: "6C8194"))
                    .fixedSize(horizontal: false, vertical: true)
            }
            if let evidence = presentation.evidenceSummary {
                Text(evidence)
                    .font(.caption2)
                    .foregroundStyle(Color(hex: "6C8194"))
                    .fixedSize(horizontal: false, vertical: true)
            }
            if let missingInputs = presentation.missingInputsSummary {
                Text(missingInputs)
                    .font(.caption2)
                    .foregroundStyle(Color(hex: "C57A27"))
                    .fixedSize(horizontal: false, vertical: true)
            }
            if let failure = presentation.failureSummary {
                Text(failure)
                    .font(.caption2)
                    .foregroundStyle(Color(hex: "C57A27"))
                    .fixedSize(horizontal: false, vertical: true)
            }
            #if DEBUG
            if !snapshot.evidence.isEmpty {
                Text("调试证据：\(debugDictionaryDisplay(snapshot.evidence))")
                    .font(.caption2)
                    .foregroundStyle(Color(hex: "7890A4"))
                    .fixedSize(horizontal: false, vertical: true)
            }
            if !snapshot.missing_inputs.isEmpty {
                Text("调试缺失输入：\(debugDictionaryDisplay(snapshot.missing_inputs))")
                    .font(.caption2)
                    .foregroundStyle(Color(hex: "7890A4"))
                    .fixedSize(horizontal: false, vertical: true)
            }
            if let failureCode = snapshot.failure_code, !failureCode.isEmpty {
                Text("调试失败代码：\(failureCode)")
                    .font(.caption2)
                    .foregroundStyle(Color(hex: "7890A4"))
                    .textSelection(.enabled)
            }
            #endif
        }
        .padding(12)
        .background(Color.white.opacity(0.42), in: RoundedRectangle(cornerRadius: 16))
    }

    private func scoreConfidenceLabel(_ snapshot: HealthReportScoreSnapshot) -> String? {
        switch (snapshot.before_confidence, snapshot.after_confidence) {
        case let (before?, after?):
            return "\(confidencePercent(before)) → \(confidencePercent(after))"
        case let (nil, after?):
            return "本次 \(confidencePercent(after))"
        case let (before?, nil):
            return "前值 \(confidencePercent(before))（本次未提供）"
        case (nil, nil):
            return nil
        }
    }

    private func confidencePercent(_ value: Double) -> String {
        "\(Int((value * 100).rounded()))%"
    }

    private func scoreHeadline(_ interpretation: HealthReportInterpretation) -> String {
        if interpretation.score_pending {
            let completedCount = interpretation.score_snapshots.filter {
                $0.calculation_status == "completed"
            }.count
            return completedCount > 0
                ? "评分仍待更新；已有 \(completedCount) 项可核验快照，其余尚未收口。"
                : "评分待更新；报告已入库，但当前没有完整评分结果。"
        }
        switch interpretation.score_state {
        case "completed": return "评分流程已完成；以下仅展示服务端实际快照。"
        case "partial_failed": return "评分部分完成；失败项不会显示推测结果。"
        case "failed": return "评分更新未完成；报告入库结果不受影响。"
        default: return "当前没有可核验的评分快照。"
        }
    }

    private func scoreValueLabel(_ snapshot: HealthReportScoreSnapshot) -> String {
        guard snapshot.calculation_status == "completed",
              let after = snapshot.after_value else {
            return snapshot.calculation_status == "failed" ? "本项未更新" : "本项仍在计算"
        }
        if let before = snapshot.before_value {
            return "\(format(before)) → \(format(after))"
        }
        return "本次结果 \(format(after))（无可比前值）"
    }

    private func observationValue(_ observation: HealthReportObservation) -> String {
        let value = observation.value_numeric.map(format) ?? observation.value_text ?? "未记录"
        return [value, observation.unit]
            .compactMap { value in
                guard let value, !value.isEmpty else { return nil }
                return value
            }
            .joined(separator: " ")
    }

    private func observationReference(_ observation: HealthReportObservation) -> String {
        if let text = observation.reference_text, !text.isEmpty { return text }
        switch (observation.reference_low, observation.reference_high) {
        case let (low?, high?): return "\(format(low))–\(format(high))"
        case let (low?, nil): return "≥ \(format(low))"
        case let (nil, high?): return "≤ \(format(high))"
        default: return "未记录"
        }
    }

    private func profileImpactGroups(
        _ impacts: [HealthReportProfileImpact]
    ) -> [HealthReportProfileImpactGroup] {
        Dictionary(grouping: impacts, by: \.profile_candidate_id)
            .values
            .compactMap { rows in
                guard let impact = rows.first else { return nil }
                return HealthReportProfileImpactGroup(
                    impact: impact,
                    sourceObservationIDs: Array(Set(rows.map(\.source_observation_id))).sorted()
                )
            }
            .sorted { $0.id < $1.id }
    }

    private func eventChangeLabel(_ event: HealthReportConfirmationEvent) -> String {
        let before = eventValue(event.before_data)
        let after = eventValue(event.after_data)
        if before == "未记录" { return after }
        if before == after { return after }
        return "\(before) → \(after)"
    }

    private func eventValue(_ data: [String: HealthReportJSONValue]) -> String {
        let value = HealthReportInterpretationUserPresentation.scalarValue(
            data["value_numeric"] ?? data["value_text"]
        )
        let unit = HealthReportInterpretationUserPresentation.scalarValue(data["unit"])
        return [value, unit]
            .compactMap { value in
                guard let value, !value.isEmpty, value != "null" else { return nil }
                return value
            }
            .joined(separator: " ")
            .nilIfBlank ?? "未记录"
    }

    #if DEBUG
    private func debugDictionaryDisplay(
        _ dictionary: [String: HealthReportJSONValue]
    ) -> String {
        guard !dictionary.isEmpty else { return "未记录" }
        return dictionary.keys.sorted().map { key in
            "\(key)：\(dictionary[key]?.debugDisplayText ?? "null")"
        }.joined(separator: "；")
    }
    #endif

    private func candidateReviewLabel(_ status: HealthReportCandidateReviewStatus) -> String {
        switch status {
        case .pendingReview: return "待检查"
        case .autoAccepted: return "自动通过"
        case .confirmed: return "已确认"
        case .corrected: return "已修正"
        case .rejected: return "未采用"
        case .unknown: return "状态待刷新"
        }
    }

    private func profileStatusLabel(_ status: String) -> String {
        switch status {
        case "pending_review": return "待复核"
        case "accepted": return "已接受"
        case "rejected": return "未采用"
        case "superseded": return "已被替代"
        case "conflict": return "存在冲突"
        default: return "状态待刷新"
        }
    }

    private func scoreStatusLabel(_ status: String) -> String {
        switch status {
        case "completed": return "已完成"
        case "failed": return "未完成"
        default: return "待更新"
        }
    }

    private func semanticOutcomeLabel(_ outcome: String) -> String {
        switch outcome {
        case "improved": return "改善"
        case "worsened": return "变差"
        case "unchanged": return "未变化"
        default: return "无法判断"
        }
    }

    private func eventLabel(_ type: String) -> String {
        HealthReportInterpretationUserPresentation.eventTitle(type)
    }

    private func format(_ value: Double) -> String {
        if value.rounded() == value { return String(Int(value)) }
        return String(format: "%.4f", value)
            .replacingOccurrences(of: #"\.?0+$"#, with: "", options: .regularExpression)
    }

    private func sectionCard<Content: View>(
        title: String,
        icon: String,
        staticTitleIdentifier: String? = nil,
        @ViewBuilder content: () -> Content
    ) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            sectionTitle(
                title,
                icon: icon,
                staticTitleIdentifier: staticTitleIdentifier
            )
            content()
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(16)
        .background(XAgeGlassCardBackground(cornerRadius: 24))
    }

    @ViewBuilder
    private func sectionTitle(
        _ title: String,
        icon: String,
        staticTitleIdentifier: String?
    ) -> some View {
        if let staticTitleIdentifier {
            Label(title, systemImage: icon)
                .font(.headline.weight(.bold))
                .foregroundStyle(Color(hex: "173F64"))
                .accessibilityIdentifier(staticTitleIdentifier)
        } else {
            Label(title, systemImage: icon)
                .font(.headline.weight(.bold))
                .foregroundStyle(Color(hex: "173F64"))
        }
    }
}

private struct HealthReportProfileImpactGroup: Identifiable {
    let impact: HealthReportProfileImpact
    let sourceObservationIDs: [Int]

    var id: Int { impact.profile_candidate_id }
}

private extension HealthReportJSONValue {
    var objectValue: [String: HealthReportJSONValue]? {
        guard case .object(let value) = self else { return nil }
        return value
    }

    #if DEBUG
    var debugDisplayText: String {
        switch self {
        case .string(let value): return value
        case .number(let value):
            if value.rounded() == value { return String(Int(value)) }
            return String(value)
        case .bool(let value): return value ? "是" : "否"
        case .object(let value):
            return value.keys.sorted().map {
                "\($0)：\(value[$0]?.debugDisplayText ?? "null")"
            }.joined(separator: "；")
        case .array(let value): return value.map(\.debugDisplayText).joined(separator: "、")
        case .null: return "null"
        }
    }
    #endif
}

private extension String {
    var nilIfBlank: String? { isEmpty ? nil : self }
}
