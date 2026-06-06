import SwiftUI

/// 首页 — 对应小程序 pages/index/index
struct HomeView: View {
    @EnvironmentObject var authManager: AuthManager
    @StateObject private var vm = HomeViewModel()
    @State private var showPrecisionDetails = false
    @State private var showMetabolicOverview = false

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 12) {
                    // 顶部欢迎栏
                    welcomeBar

                    metabolicTopRow

                    if vm.elderlyMode {
                        // 老年模式：用“关怀复查”卡片替代主动提醒 + 干预滑块
                        ElderlyCareCard()
                    } else {
                        // 主动消息卡片
                        if let proactive = vm.proactive, let msg = proactive.message, !msg.isEmpty {
                            proactiveCard(proactive)
                        }

                        // 主动交互级别滑块
                        interventionSlider
                    }

                    // 血糖概览
                    if let glucose = vm.dashboard?.glucose?.last_24h {
                        glucoseCard(glucose)
                    }

                    treeSummaryCard(
                        vm.treeSummary ?? HealthTreeSummary(trees_grown: 0, fruiting_count: 0, active_plan_count: 0),
                        precision: vm.contextPrecision,
                        isLive: vm.treeSummary != nil
                    )

                    // 今日膳食
                    mealsCard

                    // 今日锻炼
                    ExerciseCard()

                    // 快捷入口
                    quickGrid
                }
                .padding(.horizontal, 16)
                .padding(.top, 8)
            }
            .background(Color.appBackground)
            .refreshable { await vm.fetchData() }
            .task { await vm.fetchData() }
            .onReceive(NotificationCenter.default.publisher(for: .healthTreeDidChange)) { _ in
                Task { await vm.fetchData() }
            }
            .onAppear {
                Task { await vm.fetchData() }
            }
            .overlay {
                if vm.loading {
                    ProgressView("加载中...")
                }
            }
            .alert("错误", isPresented: Binding(
                get: { vm.errorMessage != nil },
                set: { if !$0 { vm.errorMessage = nil } }
            )) {
                Button("确定", role: .cancel) {}
            } message: {
                Text(vm.errorMessage ?? "")
            }
            .sheet(isPresented: $showPrecisionDetails) {
                contextPrecisionSheet(vm.contextPrecision)
            }
            .sheet(isPresented: $showMetabolicOverview) {
                metabolicOverviewSheet(vm.dashboard?.metabolic_state)
            }
        }
    }

    // MARK: - 子视图

    private var welcomeBar: some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Label("你好", systemImage: "hand.wave")
                    .font(.title2).bold()
                if !authManager.subjectId.isEmpty {
                    Text(authManager.subjectId)
                        .font(.caption)
                        .foregroundColor(.appMuted)
                }
            }
            Spacer()
            NavigationLink(destination: SettingsView()) {
                Image(systemName: "gearshape.fill")
                    .font(.title3)
                    .foregroundColor(.appMuted)
            }
        }
        .padding(.vertical, 8)
    }

    private var metabolicTopRow: some View {
        HStack(spacing: 10) {
            metabolicStateCard(vm.dashboard?.metabolic_state)
                .frame(maxWidth: .infinity)
            weeklyValidationCard(vm.dashboard?.weekly_validation)
                .frame(maxWidth: .infinity)
        }
    }

    private func metabolicStateCard(_ state: MetabolicState?) -> some View {
        Button {
            showMetabolicOverview = true
        } label: {
            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    Label(state?.title ?? "今日健康状态", systemImage: "waveform.path.ecg")
                        .font(.subheadline.bold())
                    Spacer()
                    Text("\(state?.score ?? 0)")
                        .font(.caption.bold())
                        .foregroundColor(metabolicColor(state?.level))
                }
                Text(state?.headline ?? "先建立今天的健康基线")
                    .font(.headline)
                    .foregroundColor(.appText)
                    .lineLimit(2)
                Text(state?.action ?? "记录一餐、完成一次计划或上传健康资料，小捷就能给出今天的最小行动。")
                    .font(.caption)
                    .foregroundColor(.appMuted)
                    .lineLimit(2)
                Text("依据：\(sourceSummary(state?.data_sources)) · \(confidenceText(state))")
                    .font(.caption2)
                    .foregroundColor(.appMuted)
                    .lineLimit(1)
                    .minimumScaleFactor(0.85)
                HStack {
                    Text("总览")
                        .font(.caption.bold())
                    Spacer()
                    Image(systemName: "chevron.right")
                        .font(.caption.bold())
                }
                .foregroundColor(.appPrimary)
            }
            .padding(12)
            .frame(minHeight: 150, alignment: .top)
            .background(Color.appCardBg)
            .clipShape(RoundedRectangle(cornerRadius: 12))
            .shadow(color: .black.opacity(0.04), radius: 8, x: 0, y: 2)
        }
        .buttonStyle(.plain)
    }

    private func weeklyValidationCard(_ weekly: WeeklyValidation?) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Label("周验证", systemImage: "checkmark.seal")
                    .font(.subheadline.bold())
                Spacer()
                Text("\(weekly?.adherence_pct ?? 0)%")
                    .font(.caption.bold())
                    .foregroundColor(.appSuccess)
            }
            Text(weekly?.headline ?? "等待本周验证")
                .font(.headline)
                .foregroundColor(.appText)
                .lineLimit(2)
            Text(weekly?.summary ?? "完成计划后，小捷会对比执行率和血糖变化。")
                .font(.caption)
                .foregroundColor(.appMuted)
                .lineLimit(3)
            HStack(spacing: 6) {
                metricChip("\(weekly?.completed_actions ?? 0)/\(weekly?.total_actions ?? 0)", "执行")
                metricChip(deltaText(weekly?.tir_delta_pct), "TIR")
            }
        }
        .padding(12)
        .frame(minHeight: 150, alignment: .top)
        .background(Color.appCardBg)
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .shadow(color: .black.opacity(0.04), radius: 8, x: 0, y: 2)
    }

    private func metricChip(_ value: String, _ label: String) -> some View {
        VStack(spacing: 1) {
            Text(value)
                .font(.caption.bold())
                .foregroundColor(.appPrimary)
            Text(label)
                .font(.caption2)
                .foregroundColor(.appMuted)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 5)
        .background(Color.appPrimary.opacity(0.07))
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }

    private func metabolicOverviewSheet(_ state: MetabolicState?) -> some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    Text("7 天健康状态总览")
                        .font(.title3.bold())
                    Text("有 CGM 时优先结合连续血糖；没有 CGM 时根据饮食、计划、运动、健康资料和状态反馈生成低负担行动。")
                        .font(.caption)
                        .foregroundColor(.appMuted)
                    ForEach(state?.overview ?? []) { day in
                        HStack(alignment: .top, spacing: 10) {
                            Circle()
                                .fill(metabolicColor(day.level))
                                .frame(width: 10, height: 10)
                                .padding(.top, 5)
                            VStack(alignment: .leading, spacing: 4) {
                                HStack {
                                    Text(shortDate(day.date))
                                        .font(.subheadline.bold())
                                    Text(day.headline)
                                        .font(.subheadline)
                                        .foregroundColor(.appText)
                                    Spacer()
                                    Text("\(day.score)")
                                        .font(.caption.bold())
                                        .foregroundColor(metabolicColor(day.level))
                                }
                                Text(day.reason)
                                    .font(.caption)
                                    .foregroundColor(.appMuted)
                                Text("行动：\(day.action)")
                                    .font(.caption.bold())
                                    .foregroundColor(.appPrimary)
                                Text("依据：\(sourceSummary(day.data_sources)) · \(confidenceText(day.confidence))")
                                    .font(.caption2)
                                    .foregroundColor(.appMuted)
                            }
                        }
                        .padding(12)
                        .background(Color.appCardBg)
                        .clipShape(RoundedRectangle(cornerRadius: 12))
                    }
                }
                .padding(16)
            }
            .background(Color.appBackground)
            .navigationTitle("健康状态总览")
            .navigationBarTitleDisplayMode(.inline)
        }
        .presentationDetents([.medium, .large])
    }

    private func sourceSummary(_ sources: [String]?) -> String {
        let values = (sources ?? []).filter { !$0.isEmpty }
        guard !values.isEmpty else { return "待补数据" }
        return values.prefix(3).joined(separator: "/")
    }

    private func confidenceText(_ state: MetabolicState?) -> String {
        if let label = state?.confidence_label, !label.isEmpty { return label }
        return confidenceText(state?.confidence)
    }

    private func confidenceText(_ confidence: String?) -> String {
        switch confidence {
        case "high": return "依据充分"
        case "medium": return "依据一般"
        default: return "信息较少"
        }
    }

    private func metabolicColor(_ level: String?) -> Color {
        switch level {
        case "stable": return .appSuccess
        case "watch": return .orange
        case "risk": return .appDanger
        default: return .appMuted
        }
    }

    private func deltaText(_ value: Double?) -> String {
        guard let value else { return "--" }
        return "\(value >= 0 ? "+" : "")\(Utils.toFixed(value))%"
    }

    private func shortDate(_ date: String) -> String {
        String(date.suffix(5))
    }

    private func proactiveCard(_ p: ProactiveMessage) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                AssistantAvatar(size: 36)
                Text(p.message ?? "")
                    .font(.subheadline)
            }
            if p.has_rescue == true {
                NavigationLink(destination: ChatView(isEmbedded: true)) {
                    Label("有待处理的救援建议", systemImage: "exclamationmark.triangle")
                        .font(.caption)
                        .foregroundColor(.appDanger)
                }
            }
        }
        .cardStyle()
    }

    private var interventionSlider: some View {
        let levelLabels = ["温和", "标准", "积极", "强化", "全场景"]
        let levelDescs = [
            "仅高风险时提醒（1条/日）",
            "高风险提醒 + 每日复查（2条/日）",
            "中风险提醒 + 餐后建议（4条/日）",
            "低风险提醒 + 餐后复查 + 运动提醒（6条/日）",
            "错餐推送 + 夜间安眠 + 服药提醒（10条/日）",
        ]
        let idx = max(0, min(4, Int(vm.interventionLevel.rounded())))

        return VStack(alignment: .leading, spacing: 8) {
            HStack {
                Label("主动交互", systemImage: "bell.badge")
                    .font(.headline)
                Spacer()
                Text(levelLabels[idx])
                    .font(.subheadline).bold()
                    .foregroundColor(.appPrimary)
            }

            Slider(value: $vm.interventionLevel, in: 0...4, step: 1) {
                Text("干预级别")
            } onEditingChanged: { editing in
                if !editing {
                    Task { await vm.updateInterventionLevel(vm.interventionLevel) }
                }
            }
            .tint(.appPrimary)

            HStack(spacing: 0) {
                ForEach(0..<5, id: \.self) { i in
                    Text(levelLabels[i])
                        .font(.caption2)
                        .foregroundColor(i == idx ? .appPrimary : .appMuted)
                        .frame(maxWidth: .infinity)
                }
            }
            .padding(.horizontal, 2)

            Text(levelDescs[idx])
                .font(.caption)
                .foregroundColor(.appMuted)
        }
        .cardStyle()
    }

    private func glucoseCard(_ g: GlucoseSummary) -> some View {
        NavigationLink(destination: GlucoseView()) {
            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    Label("今日血糖", systemImage: "chart.bar")
                        .font(.headline)
                    Spacer()
                    Image(systemName: "chevron.right")
                        .font(.caption.bold())
                        .foregroundColor(.appMuted)
                }
                HStack {
                    MetricItemView(value: Utils.formatGlucose(g.avg, withUnit: false), label: "平均 \(Utils.glucoseUnitLabel)")
                    Spacer()
                    MetricItemView(
                        value: g.tir_70_180_pct != nil ? Utils.toFixed(g.tir_70_180_pct) + "%" : "--",
                        label: "TIR",
                        color: .appSuccess
                    )
                    Spacer()
                    MetricItemView(
                        value: "\(Utils.glucoseThreshold(g.min ?? 0)) - \(Utils.glucoseThreshold(g.max ?? 0))",
                        label: "范围"
                    )
                }
            }
            .cardStyle()
        }
        .buttonStyle(.plain)
    }

    private func treeSummaryCard(_ summary: HealthTreeSummary, precision: ContextPrecisionSummary, isLive: Bool) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Label("健康树", systemImage: "leaf.fill")
                    .font(.headline)
                Spacer()
                if !isLive {
                    Text("同步中")
                        .font(.caption2.bold())
                        .foregroundColor(.appMuted)
                }
            }
            HStack {
                MetricItemView(value: "\(summary.trees_grown)", label: "已养成")
                Spacer()
                MetricItemView(value: "\(summary.fruiting_count)", label: "结果次数", color: .appSuccess)
                Spacer()
                Button {
                    showPrecisionDetails = true
                } label: {
                    MetricItemView(value: "\(precision.score)%", label: "精准度", color: .appPrimary)
                }
                .buttonStyle(.plain)
            }
        }
        .cardStyle()
    }

    private func contextPrecisionSheet(_ precision: ContextPrecisionSummary) -> some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: 14) {
                VStack(alignment: .leading, spacing: 6) {
                    Text("精准度 \(precision.score)%")
                        .font(.title2.bold())
                    Text("根据已上传健康资料、通知反馈和多组学特征估算。资料越完整，小捷给出的计划和建议越贴近个人情况。")
                        .font(.caption)
                        .foregroundColor(.appMuted)
                }
                .padding(.bottom, 4)

                NavigationLink(destination: HealthDataView()) {
                    precisionRow(
                        icon: "heart.text.square.fill",
                        title: "健康数据",
                        subtitle: precision.healthDataDescription,
                        value: "\(precision.healthRecordCount + precision.healthExamCount) 份"
                    )
                }
                NavigationLink(destination: ElderlyHistoryView()) {
                    precisionRow(
                        icon: "clock.arrow.circlepath",
                        title: "历史记录",
                        subtitle: precision.historyDescription,
                        value: "\(precision.historyFeedbackCount) 条"
                    )
                }
                NavigationLink(destination: OmicsView()) {
                    precisionRow(
                        icon: "atom",
                        title: "多组学数据",
                        subtitle: precision.omicsDescription,
                        value: "\(precision.omicsCategoryCount) 类"
                    )
                }
                Spacer(minLength: 0)
            }
            .padding(18)
            .background(Color.appBackground)
            .navigationTitle("数据精准度")
            .navigationBarTitleDisplayMode(.inline)
        }
        .presentationDetents([.medium, .large])
    }

    private func precisionRow(icon: String, title: String, subtitle: String, value: String) -> some View {
        HStack(spacing: 12) {
            Image(systemName: icon)
                .font(.title3)
                .foregroundColor(.appPrimary)
                .frame(width: 34, height: 34)
                .background(Color.appPrimary.opacity(0.09))
                .clipShape(RoundedRectangle(cornerRadius: 10))
            VStack(alignment: .leading, spacing: 3) {
                Text(title)
                    .font(.subheadline.bold())
                    .foregroundColor(.appText)
                Text(subtitle)
                    .font(.caption)
                    .foregroundColor(.appMuted)
                    .lineLimit(2)
            }
            Spacer()
            Text(value)
                .font(.subheadline.bold())
                .foregroundColor(.appPrimary)
        }
        .padding(12)
        .background(Color.appCardBg)
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .shadow(color: .black.opacity(0.04), radius: 8, x: 0, y: 2)
    }

    private var mealsCard: some View {
        VStack(alignment: .leading, spacing: 8) {
            Label("今日膳食", systemImage: "fork.knife")
                .font(.headline)
            HStack {
                Text("\(Int(vm.dashboard?.kcal_today ?? 0)) kcal")
                    .font(.title2).bold()
                Spacer()
                Text("\(vm.dashboard?.meals_today?.count ?? 0) 餐")
                    .foregroundColor(.appMuted)
                    .font(.caption)
            }
        }
        .cardStyle()
    }

    private var quickGrid: some View {
        LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 12) {
            NavigationLink(destination: GlucoseView()) {
                quickItem(icon: "chart.xyaxis.line", label: "血糖曲线")
            }
            NavigationLink(destination: MealsView()) {
                quickItem(icon: "camera", label: "记录膳食")
            }
            NavigationLink(destination: ChatView(isEmbedded: true)) {
                quickItem(icon: "bubble.left.and.text.bubble.right", label: "助手小捷")
            }
            NavigationLink(destination: HealthView()) {
                quickItem(icon: "list.clipboard", label: "健康数据")
            }
        }
    }

    private func quickItem(icon: String, label: String) -> some View {
        VStack(spacing: 8) {
            Image(systemName: icon)
                .font(.title)
                .foregroundColor(.appPrimary)
            Text(label).font(.caption).foregroundColor(.appText)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 16)
        .background(Color.appCardBg)
        .cornerRadius(10)
        .shadow(color: .black.opacity(0.04), radius: 8, x: 0, y: 2)
    }
}
