import SwiftUI

/// 首页 — 对应小程序 pages/index/index
struct HomeView: View {
    @EnvironmentObject var authManager: AuthManager
    @StateObject private var vm = HomeViewModel()
    @State private var showPrecisionDetails = false

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 12) {
                    // 顶部欢迎栏
                    welcomeBar

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
        VStack(alignment: .leading, spacing: 8) {
            Label("今日血糖", systemImage: "chart.bar")
                .font(.headline)
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
