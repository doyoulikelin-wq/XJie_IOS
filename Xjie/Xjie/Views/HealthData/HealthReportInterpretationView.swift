import SwiftUI

struct HealthReportInterpretationView: View {
    @Environment(\.dismiss) private var dismiss
    @ObservedObject var viewModel: HealthReportReviewViewModel
    let documentTitle: String

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
            Text(interpretation.non_diagnostic_notice)
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(Color(hex: "173F64"))
                .fixedSize(horizontal: false, vertical: true)
            Text("只展示你已确认的结构化数据和服务端实际记录；没有证据的影响不会补写。")
                .font(.caption)
                .foregroundStyle(Color(hex: "6C8194"))
                .fixedSize(horizontal: false, vertical: true)
        }
        .accessibilityIdentifier("xage.report.interpretation.notice")
    }

    private func unavailableCard(_ interpretation: HealthReportInterpretation) -> some View {
        sectionCard(title: "解读尚不可用", icon: "clock.badge.exclamationmark") {
            Text(interpretation.unavailable_reason ?? "报告尚未完成确认。")
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
                                detail.message["text"]?.stringValue ?? detail.item_code,
                                systemImage: "checkmark.seal.fill"
                            )
                            .font(.subheadline.weight(.semibold))
                            .foregroundStyle(Color(hex: "173F64"))
                            if let dueAt = detail.due_at, !dueAt.isEmpty {
                                Text("建议时间：\(dueAt)")
                                    .font(.caption)
                                    .foregroundStyle(Color(hex: "6C8194"))
                            }
                            Text("服务端依据：\(detail.evidence.count) 条已确认证据")
                                .font(.caption2)
                                .foregroundStyle(Color(hex: "7890A4"))
                        }
                        .padding(12)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(Color.white.opacity(0.42), in: RoundedRectangle(cornerRadius: 16))
                    }
                } else if !interpretation.follow_up.items.isEmpty {
                    ForEach(interpretation.follow_up.items, id: \.self) { item in
                        Label(item, systemImage: "circle.fill")
                            .font(.subheadline)
                            .foregroundStyle(Color(hex: "173F64"))
                    }
                } else {
                    Text("当前没有可展示的已确认随访信息。")
                        .font(.subheadline)
                        .foregroundStyle(Color(hex: "6C8194"))
                }
            } else {
                Text(interpretation.follow_up.unavailable_reason ?? "没有经过确认的随访信息。")
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
                Text("当前没有可展示的服务端评分快照，因此不会显示虚构的分数变化。")
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
                    VStack(alignment: .leading, spacing: 5) {
                        HStack {
                            Text(group.impact.fact_key)
                                .font(.subheadline.weight(.bold))
                                .foregroundStyle(Color(hex: "173F64"))
                            Spacer()
                            Text(profileStatusLabel(group.impact.review_status))
                                .font(.caption.weight(.bold))
                                .foregroundStyle(Color(hex: "347FB7"))
                        }
                        Text(dictionaryDisplay(group.impact.proposed_value))
                            .font(.caption)
                            .foregroundStyle(Color(hex: "496A83"))
                            .textSelection(.enabled)
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
                        Text("候选 #\(candidate.candidate_id) · \(candidate.sourceLocationLabel)")
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
                Text("不可变确认事件")
                    .font(.caption.weight(.bold))
                    .foregroundStyle(Color(hex: "6C8194"))
                ForEach(interpretation.confirmation_events) { event in
                    Text("#\(event.event_id) · 候选 #\(event.candidate_id) · \(eventLabel(event.event_type)) · \(eventChangeLabel(event))")
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
        if let fileURL = interpretation.originalFileURL,
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
                Text("服务端未提供可访问的原件地址；已确认字段和来源记录仍保留。")
                    .font(.subheadline)
                    .foregroundStyle(Color(hex: "6C8194"))
                    .fixedSize(horizontal: false, vertical: true)
            }
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
                Text("观测 #\(observation.observation_id) · 候选 #\(observation.source_candidate_id) · 确认事件 #\(observation.confirmation_event_id)")
                    .font(.caption2)
                    .foregroundStyle(Color(hex: "7890A4"))
            }
        }
        .padding(12)
        .background(Color.white.opacity(0.42), in: RoundedRectangle(cornerRadius: 16))
    }

    private func scoreSnapshotRow(_ snapshot: HealthReportScoreSnapshot) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack {
                Text(scoreKindLabel(snapshot.score_kind))
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
                Text("服务端语义：\(semanticOutcomeLabel(outcome))")
                    .font(.caption)
                    .foregroundStyle(Color(hex: "496A83"))
            }
            if let confidence = scoreConfidenceLabel(snapshot) {
                Text("置信度：\(confidence)")
                    .font(.caption)
                    .foregroundStyle(Color(hex: "6C8194"))
                    .textSelection(.enabled)
            }
            if let direction = snapshot.score_direction, !direction.isEmpty {
                Text(scoreDirectionLabel(direction))
                    .font(.caption2)
                    .foregroundStyle(Color(hex: "6C8194"))
            }
            Text("算法：\(snapshot.algorithm_id) · \(snapshot.algorithm_version)")
                .font(.caption2)
                .foregroundStyle(Color(hex: "6C8194"))
                .textSelection(.enabled)
            if let method = snapshot.method_summary?["text"]?.stringValue,
               !method.isEmpty {
                Text("方法：\(method)")
                    .font(.caption)
                    .foregroundStyle(Color(hex: "496A83"))
                    .fixedSize(horizontal: false, vertical: true)
            }
            if let inputBasis = snapshot.input_basis, !inputBasis.isEmpty {
                let labels = inputBasis.compactMap {
                    $0["label"]?.objectValue?["text"]?.stringValue
                }
                if !labels.isEmpty {
                    Text("输入依据：\(labels.joined(separator: "、"))")
                        .font(.caption2)
                        .foregroundStyle(Color(hex: "6C8194"))
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            if !snapshot.evidence.isEmpty {
                Text("证据：\(dictionaryDisplay(snapshot.evidence))")
                    .font(.caption2)
                    .foregroundStyle(Color(hex: "6C8194"))
                    .fixedSize(horizontal: false, vertical: true)
            }
            if !snapshot.missing_inputs.isEmpty {
                Text("缺失输入：\(dictionaryDisplay(snapshot.missing_inputs))")
                    .font(.caption2)
                    .foregroundStyle(Color(hex: "C57A27"))
                    .fixedSize(horizontal: false, vertical: true)
            }
            if let failureText = snapshot.failure?["message"]?.objectValue?["text"]?.stringValue,
               !failureText.isEmpty {
                Text("未完成原因：\(failureText)")
                    .font(.caption2)
                    .foregroundStyle(Color(hex: "C57A27"))
                    .fixedSize(horizontal: false, vertical: true)
            } else if let failure = snapshot.failure_code, !failure.isEmpty {
                Text("未完成原因：\(failure)")
                    .font(.caption2)
                    .foregroundStyle(Color(hex: "C57A27"))
            }
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

    private func scoreDirectionLabel(_ direction: String) -> String {
        switch direction {
        case "higher_is_better": return "服务端定义：数值越高越好"
        case "lower_is_better": return "服务端定义：数值越低越好"
        default: return "服务端方向：\(direction)"
        }
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
        let value = data["value_numeric"]?.reportDisplayText
            ?? data["value_text"]?.reportDisplayText
        let unit = data["unit"]?.reportDisplayText
        return [value, unit]
            .compactMap { value in
                guard let value, !value.isEmpty, value != "null" else { return nil }
                return value
            }
            .joined(separator: " ")
            .nilIfBlank ?? "未记录"
    }

    private func dictionaryDisplay(_ dictionary: [String: HealthReportJSONValue]) -> String {
        guard !dictionary.isEmpty else { return "未记录" }
        return dictionary.keys.sorted().map { key in
            "\(key)：\(dictionary[key]?.reportDisplayText ?? "null")"
        }.joined(separator: "；")
    }

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

    private func scoreKindLabel(_ kind: String) -> String {
        switch kind {
        case "stress": return "压力"
        case "recovery": return "恢复"
        case "inflammation": return "炎症"
        default: return kind
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
        switch type {
        case "confirm": return "确认"
        case "correct": return "修正"
        case "reject": return "未采用"
        case "manual_add": return "手动补录"
        default: return type
        }
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

    var reportDisplayText: String {
        switch self {
        case .string(let value): return value
        case .number(let value):
            if value.rounded() == value { return String(Int(value)) }
            return String(value)
        case .bool(let value): return value ? "是" : "否"
        case .object(let value):
            return value.keys.sorted().map {
                "\($0)：\(value[$0]?.reportDisplayText ?? "null")"
            }.joined(separator: "；")
        case .array(let value): return value.map(\.reportDisplayText).joined(separator: "、")
        case .null: return "null"
        }
    }
}

private extension String {
    var nilIfBlank: String? { isEmpty ? nil : self }
}
