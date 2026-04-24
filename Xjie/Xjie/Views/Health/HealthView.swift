import SwiftUI

/// 每日健康简报 — 对应小程序 pages/health/health
struct HealthView: View {
    @StateObject private var vm = HealthBriefViewModel()
    @StateObject private var trendVM = IndicatorTrendViewModel()

    var body: some View {
        ScrollView {
            VStack(spacing: 12) {
                // 血糖状态
                if let status = vm.briefing?.glucose_status {
                    glucoseStatusCard(status)
                }

                // 每日计划
                if let plan = vm.briefing?.daily_plan {
                    dailyPlanCard(plan)
                }

                // 待处理救援
                if let rescues = vm.briefing?.pending_rescues, !rescues.isEmpty {
                    rescueCard(rescues)
                }

                // 最近操作
                if let actions = vm.briefing?.recent_actions, !actions.isEmpty {
                    actionsCard(actions)
                }

                // AI 健康总结 + 健康报告
                healthSummaryCard

                // 关注指标趋势
                IndicatorTrendSection(vm: trendVM)
                    .cardStyle()

                // 情绪日记入口（C4）
                NavigationLink {
                    MoodLogView()
                } label: {
                    HStack {
                        Label("情绪日记", systemImage: "face.smiling")
                            .font(.subheadline.bold())
                        Spacer()
                        Text("打卡 / 看曲线")
                            .font(.caption)
                            .foregroundColor(.appMuted)
                        Image(systemName: "chevron.right")
                            .font(.caption)
                            .foregroundColor(.appMuted)
                    }
                }
                .buttonStyle(.plain)
                .cardStyle()

                if vm.briefing == nil && vm.reports == nil && !vm.loading {
                    EmptyStateView(
                        icon: "heart.text.square",
                        title: "暂无健康数据",
                        subtitle: "下拉刷新获取最新数据"
                    )
                }
            }
            .padding(.horizontal, 16)
            .padding(.top, 8)
        }
        .background(Color.appBackground)
        .navigationTitle("今日简报")
        .navigationBarTitleDisplayMode(.inline)
        .task {
            await vm.fetchData()
            await trendVM.fetchIndicators()
        }
        .refreshable {
            await vm.fetchData()
            await trendVM.fetchIndicators()
        }
        .overlay { if vm.loading { ProgressView("加载中...") } }
        .alert("错误", isPresented: Binding(
            get: { vm.errorMessage != nil },
            set: { if !$0 { vm.errorMessage = nil } }
        )) {
            Button("好", role: .cancel) {}
        } message: {
            Text(vm.errorMessage ?? "")
        }
    }

    // MARK: - 血糖状态

    private func glucoseStatusCard(_ s: GlucoseStatus) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Label("当前血糖状态", systemImage: "chart.bar").font(.headline)
            HStack(spacing: 8) {
                if let val = s.current_mgdl {
                    Text(Utils.formatGlucose(val))
                        .font(.title).bold()
                }
                if let trend = s.trend {
                    Text(trend)
                        .font(.caption)
                        .padding(.horizontal, 8).padding(.vertical, 4)
                        .background(Color.appPrimary.opacity(0.1))
                        .foregroundColor(.appPrimary)
                        .cornerRadius(4)
                }
            }
            if let tir = s.tir_24h {
                Text("24h TIR: \(Utils.toFixed(tir))%")
                    .font(.caption)
                    .foregroundColor(.appMuted)
            }
        }
        .cardStyle()
    }

    // MARK: - 每日计划

    private func dailyPlanCard(_ plan: DailyPlan) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Label("\(plan.payload.title ?? "今日计划")", systemImage: "list.bullet.clipboard")
                .font(.headline)

            if let windows = plan.payload.risk_windows, !windows.isEmpty {
                Label("风险窗口", systemImage: "exclamationmark.triangle").font(.subheadline).bold()
                ForEach(windows) { w in
                    HStack {
                        Text("\(w.start ?? "") - \(w.end ?? "")")
                            .font(.subheadline)
                        Spacer()
                        Text(w.risk ?? "")
                            .font(.caption)
                            .padding(.horizontal, 6).padding(.vertical, 2)
                            .background(w.risk == "high" ? Color.appDanger.opacity(0.1) : Color.appWarning.opacity(0.1))
                            .foregroundColor(w.risk == "high" ? .appDanger : .appWarning)
                            .cornerRadius(4)
                    }
                }
            }

            if let goals = plan.payload.today_goals, !goals.isEmpty {
                Label("目标", systemImage: "target").font(.subheadline).bold()
                    .padding(.top, 4)
                ForEach(goals, id: \.self) { goal in
                    Text("• \(goal)")
                        .font(.subheadline)
                }
            }
        }
        .cardStyle()
    }

    // MARK: - 救援

    private func rescueCard(_ rescues: [RescueItem]) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Label("待处理救援", systemImage: "light.beacon.max")
                .font(.headline)
                .foregroundColor(.appDanger)
            ForEach(rescues) { rescue in
                HStack {
                    Text(rescue.payload?.title ?? "")
                        .font(.subheadline)
                    Spacer()
                    Text(rescue.payload?.risk_level ?? "")
                        .font(.caption)
                        .foregroundColor(.appMuted)
                }
                Divider()
            }
        }
        .cardStyle()
    }

    // MARK: - 最近操作

    private func actionsCard(_ actions: [ActionItem]) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Label("最近操作", systemImage: "note.text").font(.headline)
            ForEach(actions) { action in
                HStack {
                    Text(action.action_type ?? "")
                        .font(.caption)
                        .padding(.horizontal, 6).padding(.vertical, 2)
                        .background(Color.appPrimary.opacity(0.1))
                        .foregroundColor(.appPrimary)
                        .cornerRadius(4)
                    Text(Utils.formatDate(action.created_ts))
                        .font(.caption)
                        .foregroundColor(.appMuted)
                }
            }
        }
        .cardStyle()
    }

    // MARK: - AI 健康总结

    private var healthSummaryCard: some View {
        VStack(alignment: .leading, spacing: 8) {
            Label("AI 健康总结", systemImage: "brain.head.profile").font(.headline)

            if !vm.aiSummary.isEmpty {
                MarkdownTextView(text: vm.aiSummary)
                    .padding(12)
                    .background(Color.appPrimary.opacity(0.05))
                    .cornerRadius(8)
            }

            // Progress bar during generation
            if vm.summaryLoading {
                VStack(alignment: .leading, spacing: 4) {
                    ProgressView(value: vm.summaryProgress, total: 1.0)
                        .tint(.appPrimary)
                    HStack {
                        Text(vm.summaryStage)
                            .font(.caption)
                            .foregroundColor(.secondary)
                        Spacer()
                        Text("\(Int(vm.summaryProgress * 100))%")
                            .font(.caption.monospacedDigit())
                            .foregroundColor(.appPrimary)
                    }
                }
                .padding(.vertical, 4)
            }

            Button {
                Task { await vm.loadAISummary() }
            } label: {
                HStack {
                    if vm.summaryLoading {
                        ProgressView()
                            .controlSize(.small)
                            .tint(.appPrimary)
                    }
                    Text(vm.aiSummary.isEmpty ? "生成 AI 健康总结" : "重新生成")
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 10)
                .background(
                    RoundedRectangle(cornerRadius: 8)
                        .stroke(Color.appPrimary, lineWidth: 1)
                )
                .foregroundColor(.appPrimary)
            }
            .disabled(vm.summaryLoading)
        }
        .cardStyle()
    }
}