import SwiftUI
#if canImport(ActivityKit)
import ActivityKit
#endif

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
            updateLiveActivity()
        }
        .refreshable {
            await vm.fetchData()
            await trendVM.fetchIndicators()
            updateLiveActivity()
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

    // MARK: - 灵动岛数据

    private func updateLiveActivity() {
        #if canImport(ActivityKit)
        if #available(iOS 16.2, *) {
            let glucose = vm.briefing?.glucose_status?.current_mgdl.map { Utils.formatGlucose($0) } ?? "血糖暂无"
            let plan = vm.briefing?.daily_plan?.payload.title ?? "每日计划"
            let care = vm.briefing?.daily_plan?.payload.today_goals?.first ?? "关心今日状态"
            XjieLiveActivityManager.shared.update(
                leftItems: [glucose, plan, care],
                treeStage: "健康树",
                treeAssetName: "growth_tree_seed_0"
            )
        }
        #endif
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

#if canImport(ActivityKit)
@available(iOS 16.2, *)
struct XjieLiveActivityAttributes: ActivityAttributes {
    struct ContentState: Codable, Hashable {
        let leftItems: [String]
        let rotationIndex: Int
        let treeStage: String
        let treeAssetName: String
    }

    let title: String
}

@available(iOS 16.2, *)
@MainActor
final class XjieLiveActivityManager {
    static let shared = XjieLiveActivityManager()

    private init() {}

    func update(leftItems: [String], treeStage: String, treeAssetName: String) {
        guard ActivityAuthorizationInfo().areActivitiesEnabled else { return }
        let normalizedItems = leftItems
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
        let items = normalizedItems.isEmpty ? ["今日计划"] : Array(normalizedItems.prefix(3))
        let state = XjieLiveActivityAttributes.ContentState(
            leftItems: items,
            rotationIndex: Calendar.current.component(.minute, from: Date()) % max(items.count, 1),
            treeStage: treeStage,
            treeAssetName: treeAssetName
        )
        let content = ActivityContent(state: state, staleDate: Date().addingTimeInterval(15 * 60))

        Task {
            if let activity = Activity<XjieLiveActivityAttributes>.activities.first {
                await activity.update(content)
                return
            }
            do {
                _ = try Activity<XjieLiveActivityAttributes>.request(
                    attributes: XjieLiveActivityAttributes(title: "小捷健康树"),
                    content: content,
                    pushType: nil
                )
            } catch {
                // Live Activity can be disabled by device settings; app UI continues normally.
            }
        }
    }
}
#endif

// MARK: - 健康计划与试管式执行入口

struct HealthPlanView: View {
    @StateObject private var vm = HealthPlanViewModel()
    @State private var showPlanQuestionnaire = false

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 14) {
                    if let week = vm.week {
                        HealthTreeWeekCard(
                            week: week,
                            isViewingCurrentWeek: vm.isViewingCurrentWeek,
                            completingType: vm.completingType,
                            recentEffect: vm.lastCompletedType,
                            onPreviousWeek: { Task { await vm.previousWeek() } },
                            onNextWeek: { Task { await vm.nextWeek() } },
                            onThisWeek: { Task { await vm.backToThisWeek() } },
                            onComplete: { type in Task { await vm.completeToday(taskType: type) } },
                            onEffectFinished: { vm.clearCompletionEffect() },
                            onGeneratePlan: { showPlanQuestionnaire = true }
                        )
                    }

                    planOverview
                    planDetail

                    if vm.plans.isEmpty && !vm.loading {
                        EmptyStateView(
                            icon: "list.clipboard",
                            title: "暂无健康计划",
                            subtitle: "在助手小捷生成饮食、运动、用药方案后，点击「保存为健康计划」。"
                        )
                    }
                }
                .padding(.horizontal, 16)
                .padding(.top, 10)
                .padding(.bottom, 24)
            }
            .background(Color.appBackground)
            .navigationTitle("健康计划")
            .navigationBarTitleDisplayMode(.inline)
            .task { await vm.refresh() }
            .refreshable { await vm.refresh() }
            .overlay { if vm.loading { ProgressView("加载中...") } }
            .sheet(isPresented: $showPlanQuestionnaire) {
                HealthPlanQuestionnaireSheet(isSaving: vm.creatingPlan) { request in
                    await vm.createPlan(from: request)
                }
            }
            .sheet(item: $vm.revisionProposal) { proposal in
                PlanRevisionComparisonSheet(
                    proposal: proposal,
                    isApplying: vm.revisionApplying,
                    onApply: { keys, acceptAll, rejectAll in
                        await vm.applyAIRevision(acceptedKeys: keys, acceptAll: acceptAll, rejectAll: rejectAll)
                    }
                )
            }
            .alert("提示", isPresented: Binding(
                get: { vm.errorMessage != nil },
                set: { if !$0 { vm.errorMessage = nil } }
            )) {
                Button("好", role: .cancel) {}
            } message: {
                Text(vm.errorMessage ?? "")
            }
        }
    }

    private var planOverview: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Label("健康计划", systemImage: "calendar.badge.checkmark")
                    .font(.headline)
                Spacer()
                Button { showPlanQuestionnaire = true } label: {
                    Label("生成计划", systemImage: "sparkles")
                        .font(.caption.bold())
                }
                .buttonStyle(.borderedProminent)
                .tint(.appPrimary)
                Text("\(vm.plans.count) 个")
                    .font(.caption.bold())
                    .foregroundColor(.appPrimary)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 4)
                    .background(Color.appPrimary.opacity(0.1))
                    .cornerRadius(6)
            }

            if !vm.plans.isEmpty {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 10) {
                        ForEach(vm.plans) { plan in
                            Button {
                                Task { await vm.selectPlan(plan) }
                            } label: {
                                VStack(alignment: .leading, spacing: 6) {
                                    Text(plan.plan_code.map { "计划 \($0)" } ?? "计划")
                                        .font(.caption2.bold())
                                        .foregroundColor(.appPrimary)
                                    Text(plan.title)
                                        .font(.subheadline.bold())
                                        .foregroundColor(.appText)
                                        .lineLimit(2)
                                        .frame(width: 180, alignment: .leading)
                                    Text("\(short(plan.start_date)) - \(short(plan.end_date))")
                                        .font(.caption)
                                        .foregroundColor(.appMuted)
                                    ProgressView(
                                        value: Double(plan.completed_task_count),
                                        total: Double(max(plan.task_count, 1))
                                    )
                                    .tint(.appPrimary)
                                }
                                .padding(12)
                                .frame(width: 208, alignment: .leading)
                                .background(Color.appPrimary.opacity(vm.selectedPlan?.id == plan.id ? 0.12 : 0.05))
                                .cornerRadius(10)
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }
            }
        }
        .cardStyle()
    }

    private struct HealthPlanQuestionnaireSheet: View {
        let isSaving: Bool
        let onSubmit: (HealthPlanQuestionnaireRequest) async -> Bool
        @Environment(\.dismiss) private var dismiss
        @State private var target = "控糖稳定"
        @State private var durationDays = 7
        @State private var frequency = "daily"
        @State private var selectedContents: Set<String> = ["fitness", "diet_control"]
        @State private var medicationNeeded = false
        @State private var notes = ""

        private let targets = ["控糖稳定", "减重控脂", "提升体能", "改善睡眠", "饮食规律", "综合健康"]
        private let durations = [(7, "7 天"), (14, "14 天"), (30, "30 天"), (60, "60 天")]
        private let frequencies = [
            ("daily", "每天"),
            ("three_per_week", "每周 3 次"),
            ("five_per_week", "每周 5 次"),
            ("weekdays", "工作日"),
        ]
        private let contents = [
            ("fitness", "健身"),
            ("diet_control", "饮食控制"),
            ("sleep", "睡眠"),
            ("hydration", "饮水"),
            ("medication", "用药"),
        ]

        var body: some View {
            NavigationStack {
                ScrollView {
                    VStack(alignment: .leading, spacing: 18) {
                        optionSection("目标") {
                            flowOptions(targets, selected: target) { target = $0 }
                        }
                        optionSection("时间") {
                            flowOptions(durations.map(\.1), selected: durationLabel(durationDays)) { label in
                                durationDays = durations.first(where: { $0.1 == label })?.0 ?? 7
                            }
                        }
                        optionSection("频次") {
                            flowOptions(frequencies.map(\.1), selected: frequencyLabel(frequency)) { label in
                                frequency = frequencies.first(where: { $0.1 == label })?.0 ?? "daily"
                            }
                        }
                        optionSection("涉及内容") {
                            LazyVGrid(columns: [GridItem(.adaptive(minimum: 104), spacing: 8)], spacing: 8) {
                                ForEach(contents, id: \.0) { key, label in
                                    Button {
                                        toggleContent(key)
                                    } label: {
                                        HStack(spacing: 6) {
                                            Image(systemName: selectedContents.contains(key) ? "checkmark.circle.fill" : "circle")
                                            Text(label)
                                        }
                                        .font(.caption.bold())
                                        .frame(maxWidth: .infinity)
                                        .padding(.vertical, 9)
                                    }
                                    .buttonStyle(.plain)
                                    .foregroundColor(selectedContents.contains(key) ? .appPrimary : .appMuted)
                                    .background(selectedContents.contains(key) ? Color.appPrimary.opacity(0.10) : Color.appCardBg)
                                    .clipShape(RoundedRectangle(cornerRadius: 10))
                                }
                            }
                        }

                        if selectedContents.contains("medication") {
                            Button {
                                medicationNeeded.toggle()
                            } label: {
                                HStack(alignment: .top, spacing: 10) {
                                    Image(systemName: medicationNeeded ? "checkmark.square.fill" : "square")
                                        .foregroundColor(medicationNeeded ? .appPrimary : .appMuted)
                                    VStack(alignment: .leading, spacing: 3) {
                                        Text("确认有用药需求")
                                            .font(.subheadline.bold())
                                            .foregroundColor(.appText)
                                        Text("勾选后才会生成用药任务；未确认时只保存问卷选择，不自动安排用药。")
                                            .font(.caption)
                                            .foregroundColor(.appMuted)
                                    }
                                    Spacer()
                                }
                                .padding(12)
                                .background(Color.appWarning.opacity(0.08))
                                .clipShape(RoundedRectangle(cornerRadius: 10))
                            }
                            .buttonStyle(.plain)
                        }

                        VStack(alignment: .leading, spacing: 8) {
                            Text("补充说明")
                                .font(.subheadline.bold())
                            TextEditor(text: $notes)
                                .frame(minHeight: 84)
                                .padding(8)
                                .background(Color.appCardBg)
                                .clipShape(RoundedRectangle(cornerRadius: 10))
                        }
                    }
                    .padding(16)
                }
                .background(Color.appBackground)
                .navigationTitle("生成健康计划")
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) {
                        Button("取消") { dismiss() }
                    }
                    ToolbarItem(placement: .confirmationAction) {
                        Button {
                            Task {
                                let request = HealthPlanQuestionnaireRequest(
                                    target: target,
                                    duration_days: durationDays,
                                    frequency: frequency,
                                    contents: Array(selectedContents),
                                    medication_needed: selectedContents.contains("medication") && medicationNeeded,
                                    notes: notes.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? nil : notes,
                                    title: "\(target)健康计划"
                                )
                                if await onSubmit(request) {
                                    dismiss()
                                }
                            }
                        } label: {
                            if isSaving {
                                ProgressView()
                            } else {
                                Text("保存")
                            }
                        }
                        .disabled(isSaving)
                    }
                }
            }
        }

        @ViewBuilder
        private func optionSection<Content: View>(_ title: String, @ViewBuilder content: () -> Content) -> some View {
            VStack(alignment: .leading, spacing: 8) {
                Text(title)
                    .font(.subheadline.bold())
                content()
            }
        }

        private func flowOptions(_ options: [String], selected: String, onPick: @escaping (String) -> Void) -> some View {
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 92), spacing: 8)], spacing: 8) {
                ForEach(options, id: \.self) { option in
                    Button { onPick(option) } label: {
                        Text(option)
                            .font(.caption.bold())
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 9)
                    }
                    .buttonStyle(.plain)
                    .foregroundColor(option == selected ? .appPrimary : .appMuted)
                    .background(option == selected ? Color.appPrimary.opacity(0.10) : Color.appCardBg)
                    .clipShape(RoundedRectangle(cornerRadius: 10))
                }
            }
        }

        private func toggleContent(_ key: String) {
            if selectedContents.contains(key) {
                selectedContents.remove(key)
                if key == "medication" { medicationNeeded = false }
            } else {
                selectedContents.insert(key)
            }
        }

        private func durationLabel(_ days: Int) -> String {
            durations.first(where: { $0.0 == days })?.1 ?? "\(days) 天"
        }

        private func frequencyLabel(_ key: String) -> String {
            frequencies.first(where: { $0.0 == key })?.1 ?? "每天"
        }
    }

    private var planDetail: some View {
        PlanDetailCard(
            plan: vm.selectedPlan,
            isRevisionLoading: vm.revisionLoading,
            onEditTask: { task, request in
                await vm.updateTask(task, request: request)
            },
            onAIRevision: {
                await vm.generateAIRevision()
            }
        )
    }

    private func statPill(_ value: String, _ label: String) -> some View {
        VStack(spacing: 2) {
            Text(value).font(.subheadline.bold())
            Text(label).font(.caption2).foregroundColor(.appMuted)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 8)
        .background(Color.appCardBg)
        .cornerRadius(8)
    }

    private func short(_ day: String) -> String {
        String(day.suffix(5))
    }
}

private struct PlanDetailCard: View {
    let plan: HealthPlanDetail?
    let isRevisionLoading: Bool
    let onEditTask: (PlanTask, PlanTaskUpdateRequest) async -> Bool
    let onAIRevision: () async -> Void
    @State private var selectedDay: PlanDaySummary?
    @State private var editingTask: PlanTask?

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Label("计划详情", systemImage: "doc.text.magnifyingglass")
                .font(.headline)

            if let plan {
                let days = planDaySummaries(for: plan)
                let templates = planTaskTemplates(from: plan.tasks)

                VStack(alignment: .leading, spacing: 6) {
                    if let code = plan.plan_code {
                        Text("计划 \(code)")
                            .font(.caption.bold())
                            .foregroundColor(.appPrimary)
                    }
                    Text(plan.title)
                        .font(.title3.bold())
                        .foregroundColor(.appText)
                    Text("\(shortDate(plan.start_date)) - \(shortDate(plan.end_date))")
                        .font(.caption.bold())
                        .foregroundColor(.appPrimary)
                    if let summary = compactPlanSummary(plan), !summary.isEmpty {
                        Text(summary)
                            .font(.subheadline)
                            .foregroundColor(.appMuted)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }

                if !templates.isEmpty {
                    VStack(alignment: .leading, spacing: 8) {
                        HStack {
                            Text("每日执行")
                                .font(.subheadline.bold())
                                .foregroundColor(.appText)
                            Spacer()
                            Button {
                                Task { await onAIRevision() }
                            } label: {
                                HStack(spacing: 5) {
                                    if isRevisionLoading {
                                        ProgressView()
                                            .controlSize(.small)
                                            .tint(.appPrimary)
                                    } else {
                                        Image(systemName: "sparkles")
                                    }
                                    Text(isRevisionLoading ? "Thinking..." : "AI 辅助修正")
                                }
                                .font(.caption.bold())
                            }
                            .buttonStyle(.bordered)
                            .tint(.appPrimary)
                            .disabled(isRevisionLoading)
                        }
                        ForEach(templates.prefix(6)) { task in
                            PlanTemplateRow(task: task) {
                                editingTask = task
                            }
                        }
                    }
                }

                Divider()

                PlanCalendarView(days: days) { day in
                    selectedDay = day
                }
            } else {
                Text("保存计划后，这里会展示目标、周期和每日任务。")
                    .font(.subheadline)
                    .foregroundColor(.appMuted)
            }
        }
        .cardStyle()
        .sheet(item: $selectedDay) { day in
            PlanDayDetailSheet(day: day)
        }
        .sheet(item: $editingTask) { task in
            PlanTaskEditSheet(task: task) { request in
                await onEditTask(task, request)
            }
        }
    }
}

private struct PlanTemplateRow: View {
    let task: PlanTask
    let onTap: () -> Void

    var body: some View {
        Button(action: onTap) {
            HStack(alignment: .top, spacing: 10) {
                Image(systemName: iconName(for: planTaskKind(task)))
                    .foregroundColor(color(for: planTaskKind(task)))
                    .frame(width: 22)
                VStack(alignment: .leading, spacing: 3) {
                    HStack(alignment: .firstTextBaseline) {
                        Text(planTaskDisplayTitle(task))
                            .font(.subheadline.bold())
                            .foregroundColor(.appText)
                        Spacer()
                        Text(planTaskTargetText(task))
                            .font(.caption.bold())
                            .foregroundColor(color(for: planTaskKind(task)))
                    }
                    if let detail = planTaskDetailText(task), !detail.isEmpty {
                        Text(detail)
                            .font(.caption)
                            .foregroundColor(.appMuted)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                Image(systemName: "pencil")
                    .font(.caption)
                    .foregroundColor(.appMuted)
            }
            .padding(10)
            .background(Color.appCardBg)
            .cornerRadius(10)
        }
        .buttonStyle(.plain)
    }
}

private struct PlanTaskEditSheet: View {
    let task: PlanTask
    let onSave: (PlanTaskUpdateRequest) async -> Bool
    @Environment(\.dismiss) private var dismiss
    @State private var title: String
    @State private var description: String
    @State private var targetCount: String
    @State private var targetValue: String
    @State private var unit: String
    @State private var reminderTime: String
    @State private var saving = false

    init(task: PlanTask, onSave: @escaping (PlanTaskUpdateRequest) async -> Bool) {
        self.task = task
        self.onSave = onSave
        _title = State(initialValue: stripPlanDayPrefix(task.title))
        _description = State(initialValue: task.description ?? "")
        _targetCount = State(initialValue: "\(max(task.target_count, 1))")
        _targetValue = State(initialValue: task.target_value.map(formatPlanNumber) ?? "")
        _unit = State(initialValue: task.unit ?? "")
        _reminderTime = State(initialValue: task.reminder_time ?? "")
    }

    var body: some View {
        NavigationStack {
            Form {
                Section("执行项目") {
                    TextField("标题", text: $title)
                    TextField("说明", text: $description, axis: .vertical)
                        .lineLimit(3...6)
                }
                Section("目标") {
                    TextField("次数", text: $targetCount)
                        .keyboardType(.numberPad)
                    TextField("目标值", text: $targetValue)
                        .keyboardType(.decimalPad)
                    TextField("单位", text: $unit)
                    TextField("提醒时间，例如 22:30", text: $reminderTime)
                }
            }
            .navigationTitle("编辑每日执行")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("取消") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(saving ? "保存中..." : "保存") {
                        Task {
                            saving = true
                            let ok = await onSave(PlanTaskUpdateRequest(
                                title: title.trimmingCharacters(in: .whitespacesAndNewlines),
                                description: description.trimmingCharacters(in: .whitespacesAndNewlines),
                                target_count: Int(targetCount),
                                target_value: Double(targetValue),
                                unit: unit.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? nil : unit.trimmingCharacters(in: .whitespacesAndNewlines),
                                reminder_time: reminderTime.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? nil : reminderTime.trimmingCharacters(in: .whitespacesAndNewlines)
                            ))
                            saving = false
                            if ok { dismiss() }
                        }
                    }
                    .disabled(saving || title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
            }
        }
    }
}

private struct PlanRevisionComparisonSheet: View {
    let proposal: PlanRevisionProposal
    let isApplying: Bool
    let onApply: ([String], Bool, Bool) async -> Bool
    @Environment(\.dismiss) private var dismiss
    @State private var acceptedKeys: Set<String>

    init(
        proposal: PlanRevisionProposal,
        isApplying: Bool,
        onApply: @escaping ([String], Bool, Bool) async -> Bool
    ) {
        self.proposal = proposal
        self.isApplying = isApplying
        self.onApply = onApply
        _acceptedKeys = State(initialValue: Set(proposal.revised_items.map(\.task_key)))
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    if proposal.daily_limit_used {
                        Text("今日已使用过一次 AI 辅助修正，当前显示今天已生成的建议。")
                            .font(.caption)
                            .foregroundColor(.appWarning)
                            .padding(10)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .background(Color.appWarning.opacity(0.08))
                            .cornerRadius(10)
                    }

                    ForEach(proposal.revised_items) { revised in
                        let original = proposal.original_items.first(where: { $0.task_key == revised.task_key })
                        PlanRevisionCompareRow(
                            original: original,
                            revised: revised,
                            reason: proposal.reasons.first(where: { $0.task_key == revised.task_key }),
                            accepted: acceptedKeys.contains(revised.task_key),
                            onToggle: {
                                if acceptedKeys.contains(revised.task_key) {
                                    acceptedKeys.remove(revised.task_key)
                                } else {
                                    acceptedKeys.insert(revised.task_key)
                                }
                            }
                        )
                    }
                }
                .padding(16)
            }
            .navigationTitle("AI 辅助修正")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("保留原版") {
                        Task {
                            if await onApply([], false, true) { dismiss() }
                        }
                    }
                    .disabled(isApplying)
                }
                ToolbarItem(placement: .confirmationAction) {
                    Menu {
                        Button("接受勾选") {
                            Task {
                                if await onApply(Array(acceptedKeys), false, false) { dismiss() }
                            }
                        }
                        Button("全部接受") {
                            Task {
                                if await onApply([], true, false) { dismiss() }
                            }
                        }
                    } label: {
                        if isApplying {
                            ProgressView()
                        } else {
                            Text("应用")
                        }
                    }
                    .disabled(isApplying)
                }
            }
        }
    }
}

private struct PlanRevisionCompareRow: View {
    let original: PlanRevisionItem?
    let revised: PlanRevisionItem
    let reason: PlanRevisionReason?
    let accepted: Bool
    let onToggle: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Button(action: onToggle) {
                HStack {
                    Image(systemName: accepted ? "checkmark.square.fill" : "square")
                        .foregroundColor(accepted ? .appPrimary : .appMuted)
                    Text(revised.label)
                        .font(.headline)
                        .foregroundColor(.appText)
                    if !revised.plan_codes.isEmpty {
                        Text("计划 \(revised.plan_codes.joined(separator: "/"))")
                            .font(.caption.bold())
                            .foregroundColor(.appPrimary)
                    }
                    Spacer()
                }
            }
            .buttonStyle(.plain)

            HStack(alignment: .top, spacing: 10) {
                revisionItemColumn(title: "原计划", item: original, tint: .appMuted)
                revisionItemColumn(title: "修改后", item: revised, tint: .appPrimary)
            }

            if let reason {
                VStack(alignment: .leading, spacing: 4) {
                    Text("为什么这样修改")
                        .font(.caption.bold())
                        .foregroundColor(.appText)
                    Text(reason.reason)
                        .font(.caption)
                        .foregroundColor(.appMuted)
                        .fixedSize(horizontal: false, vertical: true)
                    if let evidence = reason.evidence, !evidence.isEmpty {
                        Text("依据：\(evidence)")
                            .font(.caption2)
                            .foregroundColor(.appPrimary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
            }
        }
        .padding(12)
        .background(Color.appCardBg)
        .cornerRadius(12)
    }

    private func revisionItemColumn(title: String, item: PlanRevisionItem?, tint: Color) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(title)
                .font(.caption.bold())
                .foregroundColor(tint)
            Text(item?.title ?? "-")
                .font(.subheadline.bold())
                .foregroundColor(.appText)
            Text(revisionTargetText(item))
                .font(.caption.bold())
                .foregroundColor(tint)
            if let description = item?.description, !description.isEmpty {
                Text(description)
                    .font(.caption)
                    .foregroundColor(.appMuted)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(10)
        .background(Color.white.opacity(0.7))
        .cornerRadius(10)
    }

    private func revisionTargetText(_ item: PlanRevisionItem?) -> String {
        guard let item else { return "-" }
        if let target = item.target_value {
            return "目标 \(formatPlanNumber(target))\(item.unit.map { " \($0)" } ?? "")"
        }
        return "每日 \(item.target_count) 次"
    }
}

private struct PlanCalendarView: View {
    let days: [PlanDaySummary]
    let onSelect: (PlanDaySummary) -> Void

    private let columns = Array(repeating: GridItem(.flexible(), spacing: 6), count: 7)
    private let weekdayLabels = ["一", "二", "三", "四", "五", "六", "日"]

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Label("执行日历", systemImage: "calendar")
                    .font(.subheadline.bold())
                Spacer()
                if let first = days.first, let last = days.last {
                    Text("\(shortDate(first.date)) - \(shortDate(last.date))")
                        .font(.caption.bold())
                        .foregroundColor(.appMuted)
                }
            }

            LazyVGrid(columns: columns, spacing: 6) {
                ForEach(weekdayLabels, id: \.self) { label in
                    Text(label)
                        .font(.caption2.bold())
                        .foregroundColor(.appMuted)
                        .frame(maxWidth: .infinity)
                }
                ForEach(planCalendarSlots(days)) { slot in
                    if let day = slot.day {
                        Button { onSelect(day) } label: {
                            VStack(spacing: 2) {
                                Text(dayNumber(day.date))
                                    .font(.caption.bold())
                                Text(day.status.symbol)
                                    .font(.caption.bold())
                            }
                            .frame(maxWidth: .infinity, minHeight: 44)
                            .foregroundColor(day.status.foreground)
                            .background(day.status.background)
                            .clipShape(RoundedRectangle(cornerRadius: 10))
                        }
                        .buttonStyle(.plain)
                    } else {
                        Color.clear
                            .frame(minHeight: 44)
                    }
                }
            }

            HStack(spacing: 10) {
                PlanCalendarLegend(symbol: "✓", label: "完成", color: .appSuccess)
                PlanCalendarLegend(symbol: "◐", label: "部分", color: .appWarning)
                PlanCalendarLegend(symbol: "×", label: "未完成", color: .appDanger)
                PlanCalendarLegend(symbol: "–", label: "未到", color: .appMuted)
            }
            .font(.caption2)
        }
    }
}

private struct PlanCalendarLegend: View {
    let symbol: String
    let label: String
    let color: Color

    var body: some View {
        HStack(spacing: 3) {
            Text(symbol).font(.caption.bold()).foregroundColor(color)
            Text(label).foregroundColor(.appMuted)
        }
    }
}

private struct PlanDayDetailSheet: View {
    let day: PlanDaySummary
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(day.date)
                            .font(.title3.bold())
                        HStack(spacing: 6) {
                            Text(day.status.symbol)
                                .foregroundColor(day.status.foreground)
                                .font(.headline.bold())
                            Text(day.status.label)
                                .font(.subheadline)
                                .foregroundColor(.appMuted)
                        }
                    }

                    if day.tasks.isEmpty {
                        Text("这一天没有安排具体任务。")
                            .font(.subheadline)
                            .foregroundColor(.appMuted)
                            .padding(12)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .background(Color.appCardBg)
                            .cornerRadius(10)
                    } else {
                        ForEach(Array(day.tasks.enumerated()), id: \.element.id) { index, task in
                            PlanDayTaskRow(index: index + 1, task: task)
                        }
                    }
                }
                .padding(16)
            }
            .navigationTitle("完成情况")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button("完成") { dismiss() }
                }
            }
        }
    }
}

private struct PlanDayTaskRow: View {
    let index: Int
    let task: PlanTask
    @State private var expanded = false

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Button {
                if planTaskKind(task) == "medication" { expanded.toggle() }
            } label: {
                HStack(alignment: .top, spacing: 10) {
                    Image(systemName: iconName(for: planTaskKind(task)))
                        .foregroundColor(color(for: planTaskKind(task)))
                        .frame(width: 22)
                    VStack(alignment: .leading, spacing: 3) {
                        Text("\(index). \(planTaskDisplayTitle(task))")
                            .font(.subheadline.bold())
                            .foregroundColor(.appText)
                        Text(planTaskProgressText(task))
                            .font(.caption.bold())
                            .foregroundColor(color(for: planTaskKind(task)))
                        if let detail = planTaskDetailText(task), !detail.isEmpty {
                            Text(detail)
                                .font(.caption)
                                .foregroundColor(.appMuted)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                    Spacer()
                    if planTaskKind(task) == "medication" {
                        Image(systemName: expanded ? "chevron.up" : "chevron.down")
                            .font(.caption.bold())
                            .foregroundColor(.appMuted)
                    }
                }
            }
            .buttonStyle(.plain)

            if expanded && planTaskKind(task) == "medication" {
                MedicationTaskEditor(task: task)
                    .padding(.leading, 32)
            }
        }
        .padding(12)
        .background(Color.appCardBg)
        .cornerRadius(12)
    }
}

private struct MedicationTaskEditor: View {
    let task: PlanTask
    @State private var medicationName = ""
    @State private var selectedSlots: Set<String> = []

    private let slots = ["早", "中", "晚"]

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if let detail = planTaskDetailText(task), !detail.isEmpty {
                Text("药物信息：\(detail)")
                    .font(.caption)
                    .foregroundColor(.appMuted)
            } else {
                Text("暂无药物信息，可先手动补充。")
                    .font(.caption)
                    .foregroundColor(.appWarning)
            }

            TextField("药物名称", text: $medicationName)
                .textFieldStyle(.roundedBorder)
                .font(.subheadline)

            HStack(spacing: 8) {
                ForEach(slots, id: \.self) { slot in
                    Button {
                        if selectedSlots.contains(slot) {
                            selectedSlots.remove(slot)
                        } else {
                            selectedSlots.insert(slot)
                        }
                    } label: {
                        Text(slot)
                            .font(.caption.bold())
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 7)
                    }
                    .buttonStyle(.plain)
                    .foregroundColor(selectedSlots.contains(slot) ? .white : .appPrimary)
                    .background(selectedSlots.contains(slot) ? Color.appPrimary : Color.appPrimary.opacity(0.10))
                    .clipShape(RoundedRectangle(cornerRadius: 9))
                }
            }

            if let reminder = task.reminder_time, !reminder.isEmpty {
                Text("原提醒时间：\(reminder)")
                    .font(.caption2)
                    .foregroundColor(.appMuted)
            }
        }
    }
}

private struct PlanDaySummary: Identifiable {
    let date: String
    let tasks: [PlanTask]
    let status: PlanDayStatus

    var id: String { date }
}

private struct PlanCalendarSlot: Identifiable {
    let id: String
    let day: PlanDaySummary?
}

private enum PlanDayStatus {
    case future
    case completed
    case partial
    case missed
    case empty

    var symbol: String {
        switch self {
        case .completed: return "✓"
        case .partial: return "◐"
        case .missed: return "×"
        case .future, .empty: return "–"
        }
    }

    var label: String {
        switch self {
        case .completed: return "已完成"
        case .partial: return "完成一部分"
        case .missed: return "未完成"
        case .future: return "未到日期"
        case .empty: return "未安排任务"
        }
    }

    var foreground: Color {
        switch self {
        case .completed: return .appSuccess
        case .partial: return .appWarning
        case .missed: return .appDanger
        case .future, .empty: return .appMuted
        }
    }

    var background: Color {
        switch self {
        case .completed: return Color.appSuccess.opacity(0.12)
        case .partial: return Color.appWarning.opacity(0.12)
        case .missed: return Color.appDanger.opacity(0.10)
        case .future, .empty: return Color.appCardBg
        }
    }
}

private func planDaySummaries(for plan: HealthPlanDetail) -> [PlanDaySummary] {
    let grouped = Dictionary(grouping: plan.tasks, by: \.date)
    guard let start = growthDateFormatter.date(from: plan.start_date),
          let end = growthDateFormatter.date(from: plan.end_date),
          start <= end else {
        return grouped.keys.sorted().map { date in
            PlanDaySummary(date: date, tasks: grouped[date] ?? [], status: planDayStatus(date: date, tasks: grouped[date] ?? []))
        }
    }

    var days: [PlanDaySummary] = []
    var cursor = start
    var guardCount = 0
    while cursor <= end && guardCount < 370 {
        let date = growthDateFormatter.string(from: cursor)
        let tasks = (grouped[date] ?? []).sorted { $0.id < $1.id }
        days.append(PlanDaySummary(date: date, tasks: tasks, status: planDayStatus(date: date, tasks: tasks)))
        cursor = Calendar.current.date(byAdding: .day, value: 1, to: cursor) ?? end.addingTimeInterval(86400)
        guardCount += 1
    }
    return days
}

private func planDayStatus(date: String, tasks: [PlanTask]) -> PlanDayStatus {
    if let dayDate = growthDateFormatter.date(from: date),
       Calendar.current.startOfDay(for: dayDate) > Calendar.current.startOfDay(for: Date()) {
        return .future
    }
    guard !tasks.isEmpty else { return .empty }
    let ratios = tasks.map(planTaskCompletionRatio)
    if ratios.allSatisfy({ $0 >= 1 }) { return .completed }
    if ratios.contains(where: { $0 > 0 }) { return .partial }
    return .missed
}

private func planCalendarSlots(_ days: [PlanDaySummary]) -> [PlanCalendarSlot] {
    guard let first = days.first,
          let firstDate = growthDateFormatter.date(from: first.date) else {
        return days.map { PlanCalendarSlot(id: $0.date, day: $0) }
    }
    let offset = (Calendar.current.component(.weekday, from: firstDate) + 5) % 7
    let blanks = (0..<offset).map { PlanCalendarSlot(id: "blank-\($0)", day: nil) }
    return blanks + days.map { PlanCalendarSlot(id: $0.date, day: $0) }
}

private func planTaskTemplates(from tasks: [PlanTask]) -> [PlanTask] {
    var seen: Set<String> = []
    return tasks.sorted { lhs, rhs in
        let leftOrder = planTaskSortOrder(planTaskKind(lhs))
        let rightOrder = planTaskSortOrder(planTaskKind(rhs))
        if leftOrder != rightOrder { return leftOrder < rightOrder }
        return planTaskDisplayTitle(lhs) < planTaskDisplayTitle(rhs)
    }.filter { task in
        let key = "\(planTaskKind(task))|\(planTaskDisplayTitle(task))|\(planTaskTargetText(task))"
        if seen.contains(key) { return false }
        seen.insert(key)
        return true
    }
}

private func planTaskKind(_ task: PlanTask) -> String {
    let text = "\(task.task_type) \(task.title) \(task.description ?? "") \(task.source_ref)".lowercased()
    if text.contains("sleep") || text.contains("睡") { return "sleep" }
    if text.contains("hydration") || text.contains("饮水") || text.contains("喝水") { return "hydration" }
    if task.task_type == "measurement" { return "record" }
    return task.task_type
}

private func planTaskDisplayTitle(_ task: PlanTask) -> String {
    let raw = task.title.trimmingCharacters(in: .whitespacesAndNewlines)
    let cleaned = stripPlanDayPrefix(raw)
    if !cleaned.isEmpty { return cleaned }
    switch planTaskKind(task) {
    case "exercise": return "运动"
    case "medication": return "按时吃药"
    case "diet": return "饮食"
    case "sleep": return "按时睡觉"
    case "hydration": return "饮水"
    default: return "健康任务"
    }
}

private func planTaskTargetText(_ task: PlanTask) -> String {
    if let target = task.target_value, target > 0 {
        return "每日 \(formatPlanNumber(target))\(task.unit.map { " \($0)" } ?? "")"
    }
    return "每日 \(max(task.target_count, 1)) 次"
}

private func planTaskProgressText(_ task: PlanTask) -> String {
    if let target = task.target_value, target > 0 {
        let completed = max(task.completed_value ?? 0, 0)
        return "\(formatPlanNumber(completed))/\(formatPlanNumber(target))\(task.unit.map { " \($0)" } ?? "")"
    }
    return "\(max(task.completed_count, 0))/\(max(task.target_count, 1))"
}

private func planTaskDetailText(_ task: PlanTask) -> String? {
    var parts: [String] = []
    if let description = task.description?.trimmingCharacters(in: .whitespacesAndNewlines), !description.isEmpty {
        parts.append(description)
    }
    if planTaskKind(task) == "sleep", let reminder = task.reminder_time, !reminder.isEmpty {
        parts.append("睡觉时间 \(reminder)")
    } else if planTaskKind(task) == "medication", let reminder = task.reminder_time, !reminder.isEmpty {
        parts.append("提醒 \(reminder)")
    }
    return parts.isEmpty ? nil : parts.joined(separator: " · ")
}

private func planTaskCompletionRatio(_ task: PlanTask) -> Double {
    if task.status == "completed" { return 1 }
    if let target = task.target_value, target > 0 {
        return min(max((task.completed_value ?? 0) / target, 0), 1)
    }
    let target = max(task.target_count, 1)
    return min(max(Double(task.completed_count) / Double(target), 0), 1)
}

private func compactPlanSummary(_ plan: HealthPlanDetail) -> String? {
    let text = (plan.goal?.isEmpty == false ? plan.goal : plan.background) ?? plan.raw_content
    let normalized = text?
        .replacingOccurrences(of: "\n", with: " ")
        .replacingOccurrences(of: "  ", with: " ")
        .trimmingCharacters(in: .whitespacesAndNewlines)
    guard let normalized, !normalized.isEmpty else { return nil }
    return normalized
}

private func planTaskSortOrder(_ kind: String) -> Int {
    switch kind {
    case "exercise": return 0
    case "medication": return 1
    case "diet": return 2
    case "sleep": return 3
    case "hydration": return 4
    default: return 5
    }
}

private func dayNumber(_ date: String) -> String {
    guard let date = growthDateFormatter.date(from: date) else { return String(date.suffix(2)) }
    return "\(Calendar.current.component(.day, from: date))"
}

private func formatPlanNumber(_ value: Double) -> String {
    value.rounded() == value ? "\(Int(value))" : String(format: "%.1f", value)
}

private func stripPlanDayPrefix(_ text: String) -> String {
    text.replacingOccurrences(
        of: #"第\s*\d+\s*天\s*"#,
        with: "",
        options: .regularExpression
    ).trimmingCharacters(in: .whitespacesAndNewlines)
}

private struct HealthTreeWeekCard: View {
    let week: TubeWeek
    let isViewingCurrentWeek: Bool
    let completingType: String?
    let recentEffect: String?
    let onPreviousWeek: () -> Void
    let onNextWeek: () -> Void
    let onThisWeek: () -> Void
    let onComplete: (String) -> Void
    let onEffectFinished: () -> Void
    let onGeneratePlan: () -> Void
    @State private var selectedDate: String?
    @State private var showMedicationNeed = false
    @State private var showPlanSheet = false
    @State private var showGrowthPath = false

    private var today: TubeDay? {
        week.days.first(where: { $0.is_today })
    }

    private var activeDay: TubeDay? {
        if let selectedDate,
           let selected = week.days.first(where: { $0.date == selectedDate }) {
            return selected
        }
        return today ?? week.days.first
    }

    private var activeDateLabel: String {
        guard let day = activeDay else { return "未选择日期" }
        return "\(planRelativeLabel(for: day, today: week.today)) · \(day.date)"
    }

    private var growthProgress: GrowthTreeProgress {
        growthTreeProgress(for: week)
    }

    private func visibleTasks(for day: TubeDay) -> [TubeTaskProgress] {
        day.tasks.filter { showMedicationNeed || $0.task_type != "medication" }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                VStack(alignment: .leading, spacing: 3) {
                    Text("健康树计划养成")
                        .font(.headline)
                    Text("\(week.week_start) - \(week.week_end)")
                        .font(.caption)
                        .foregroundColor(.appMuted)
                }
                Spacer()
                Text("\(growthProgress.exp)/\(GrowthTreeProgress.maxExp) EXP")
                    .font(.caption.bold())
                    .foregroundColor(.appPrimary)
                    .padding(.horizontal, 9)
                    .padding(.vertical, 5)
                    .background(Color.appPrimary.opacity(0.1))
                    .cornerRadius(8)
                Button(action: onPreviousWeek) {
                    Image(systemName: "chevron.left")
                        .font(.caption.bold())
                        .frame(width: 30, height: 30)
                        .background(Color.appPrimary.opacity(0.08))
                        .clipShape(Circle())
                }
                .accessibilityLabel("上周")
                if !isViewingCurrentWeek {
                    Button("本周", action: onThisWeek)
                        .font(.caption.bold())
                        .foregroundColor(.appPrimary)
                }
                Button(action: onNextWeek) {
                    Image(systemName: "chevron.right")
                        .font(.caption.bold())
                        .frame(width: 30, height: 30)
                        .background(Color.appPrimary.opacity(0.08))
                        .clipShape(Circle())
                }
                .accessibilityLabel("下周")
            }

            HStack(spacing: 10) {
                Button {
                    showPlanSheet = true
                } label: {
                    Label("我的计划", systemImage: "doc.text.magnifyingglass")
                        .font(.caption.bold())
                }
                .buttonStyle(.bordered)
                .tint(.appPrimary)

                Button(action: onGeneratePlan) {
                    Label("生成计划", systemImage: "sparkles")
                        .font(.caption.bold())
                }
                .buttonStyle(.borderedProminent)
                .tint(.appPrimary)

                Button {
                    showGrowthPath = true
                } label: {
                    Label("成长路径", systemImage: "map")
                        .font(.caption.bold())
                }
                .buttonStyle(.bordered)
                .tint(.appPrimary)
            }

            HealthTreeStageView(
                progress: growthProgress,
                today: today,
                isActiveDayToday: activeDay?.is_today == true,
                recentEffect: recentEffect,
                onBackToToday: {
                    selectedDate = nil
                    if !isViewingCurrentWeek {
                        onThisWeek()
                    }
                },
                onEffectFinished: onEffectFinished
            )
            .frame(maxWidth: .infinity)

            HealthTreeActionRow(
                day: activeDay,
                showMedicationNeed: showMedicationNeed,
                completingType: completingType,
                onComplete: onComplete
            )

            HealthTreePlanPreview(
                title: "\(planRelativeLabel(for: activeDay, today: week.today))计划",
                dateLabel: activeDateLabel,
                day: activeDay,
                showMedicationNeed: $showMedicationNeed,
                completingType: completingType,
                onComplete: onComplete,
                onOpenDetail: { showPlanSheet = true },
                onGeneratePlan: onGeneratePlan
            )
        }
        .cardStyle()
        .onChange(of: week.week_start) { _, _ in
            selectedDate = nil
            showMedicationNeed = week.has_medication_need ?? false
        }
        .onAppear {
            showMedicationNeed = week.has_medication_need ?? false
        }
        .sheet(isPresented: $showPlanSheet) {
            HealthTreePlanSheet(
                day: activeDay,
                tasks: activeDay.map { visibleTasks(for: $0) } ?? [],
                showMedicationNeed: $showMedicationNeed,
                onGeneratePlan: onGeneratePlan
            )
        }
        .sheet(isPresented: $showGrowthPath) {
            HealthTreeGrowthPathSheet(progress: growthProgress)
        }
    }
}

private struct HealthTreeStageView: View {
    let progress: GrowthTreeProgress
    let today: TubeDay?
    let isActiveDayToday: Bool
    let recentEffect: String?
    let onBackToToday: () -> Void
    let onEffectFinished: () -> Void

    var body: some View {
        ZStack(alignment: .top) {
            RoundedRectangle(cornerRadius: 18)
                .fill(
                    LinearGradient(
                        colors: [
                            Color(hex: "F6FBF8"),
                            Color(hex: "E8F5EE"),
                            Color(hex: "F8FBFF")
                        ],
                        startPoint: .topLeading,
                        endPoint: .bottomTrailing
                    )
                )

            VStack(spacing: 10) {
                GrowthTreeImage(stage: progress.stage)
                    .frame(width: 190, height: 190)
                    .scaleEffect(recentEffect == nil ? 1 : 1.04, anchor: .bottom)
                    .shadow(color: Color.appPrimary.opacity(0.13), radius: 10, x: 0, y: 7)
                    .animation(.easeInOut(duration: 0.28), value: recentEffect)

                VStack(spacing: 3) {
                    Text("今日")
                        .font(.headline.bold())
                        .foregroundColor(.appText)
                    Text(today?.date ?? "未同步日期")
                        .font(.caption)
                        .foregroundColor(.appMuted)
                    Text(growthTreeStageLabel(progress.stage))
                        .font(.caption.bold())
                        .foregroundColor(.appPrimary)
                }

                VStack(alignment: .leading, spacing: 7) {
                    HStack {
                        Text("Lv.\(progress.stage)")
                            .font(.caption.bold())
                            .foregroundColor(.appPrimary)
                        Spacer()
                        Text(progress.isMaxStage ? "已进入结果期" : "距下一阶段 \(progress.expToNextStage) EXP")
                            .font(.caption2.bold())
                            .foregroundColor(.appMuted)
                    }
                    ProgressView(value: progress.stageProgress)
                        .tint(.appPrimary)
                    Text("健康问答、添加病例/健康数据、持续佩戴血糖仪都会累积成长经验。")
                        .font(.caption2)
                        .foregroundColor(.appMuted)
                        .lineLimit(2)
                        .minimumScaleFactor(0.82)
                }
                .padding(.horizontal, 8)
            }
            .padding(12)

            if let recentEffect {
                HealthTreeEffectOverlay(type: recentEffect, onFinished: onEffectFinished)
            }

            if !isActiveDayToday {
                Button(action: onBackToToday) {
                    Label("回到今天", systemImage: "calendar.badge.clock")
                        .font(.caption.bold())
                        .foregroundColor(.appPrimary)
                        .padding(.horizontal, 10)
                        .padding(.vertical, 7)
                        .background(Color.white.opacity(0.93))
                        .clipShape(Capsule())
                        .shadow(color: Color.black.opacity(0.08), radius: 5, x: 0, y: 3)
                }
                .buttonStyle(.plain)
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottomLeading)
                .padding(.leading, 12)
                .padding(.bottom, 12)
            }
        }
        .frame(height: 350)
        .clipShape(RoundedRectangle(cornerRadius: 18))
        .overlay(
            RoundedRectangle(cornerRadius: 18)
                .stroke(Color.appPrimary.opacity(0.12), lineWidth: 1)
        )
    }
}

private struct GrowthTreeImage: View {
    let stage: Int

    var body: some View {
        Image(growthTreePrimaryAsset(stage))
            .resizable()
            .interpolation(.none)
            .scaledToFit()
    }
}

private struct GrowthPlanDaySelector: View {
    let choices: [GrowthPlanDayChoice]
    let selectedDate: String?
    let onSelect: (TubeDay) -> Void

    var body: some View {
        HStack(spacing: 7) {
            ForEach(choices) { choice in
                Button {
                    if let day = choice.day {
                        onSelect(day)
                    }
                } label: {
                    VStack(spacing: 4) {
                        Text(choice.label)
                            .font(.system(size: 12, weight: .bold))
                        Text(choice.day.map { shortDate($0.date) } ?? "--")
                            .font(.system(size: 10, weight: .semibold))
                    }
                    .lineLimit(1)
                    .minimumScaleFactor(0.75)
                    .foregroundColor(choice.day?.date == selectedDate ? .white : (choice.day == nil ? .appMuted.opacity(0.5) : .appText))
                    .frame(maxWidth: .infinity)
                    .frame(height: 48)
                    .background(choice.day?.date == selectedDate ? Color.appPrimary : Color.appPrimary.opacity(0.06))
                    .cornerRadius(12)
                }
                .buttonStyle(.plain)
                .disabled(choice.day == nil)
            }
        }
    }
}

private struct HealthTreePlanPreview: View {
    let title: String
    let dateLabel: String
    let day: TubeDay?
    @Binding var showMedicationNeed: Bool
    let completingType: String?
    let onComplete: (String) -> Void
    let onOpenDetail: () -> Void
    let onGeneratePlan: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .center, spacing: 10) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(title)
                        .font(.subheadline.bold())
                    Text(dateLabel)
                        .font(.caption)
                        .foregroundColor(.appMuted)
                }
                Spacer()
                Button("详情", action: onOpenDetail)
                    .font(.caption.bold())
                    .buttonStyle(.bordered)
                    .tint(.appPrimary)
            }

            Button {
                showMedicationNeed.toggle()
            } label: {
                HStack(spacing: 7) {
                    Image(systemName: showMedicationNeed ? "checkmark.square.fill" : "square")
                    VStack(alignment: .leading, spacing: 1) {
                        Text("有用药需求")
                            .font(.caption.bold())
                        Text("勾选后显示用药计划")
                            .font(.caption2)
                            .foregroundColor(.appMuted)
                    }
                    Spacer()
                }
                .foregroundColor(showMedicationNeed ? .appPrimary : .appMuted)
                .padding(10)
                .background(Color.appCardBg)
                .cornerRadius(10)
            }
            .buttonStyle(.plain)

            if day?.is_today != true {
                Text("仅今日计划支持点击完成；前后日期用于查看安排。")
                    .font(.caption2)
                    .foregroundColor(.appMuted)
            }

            if day?.tasks.isEmpty ?? true {
                Button(action: onGeneratePlan) {
                    Label("生成计划", systemImage: "sparkles")
                        .font(.caption.bold())
                }
                .buttonStyle(.borderedProminent)
                .tint(.appPrimary)
            }
        }
        .padding(12)
        .background(Color.appCardBg.opacity(0.78))
        .cornerRadius(14)
    }
}

private struct HealthTreeGrowthPathSheet: View {
    let progress: GrowthTreeProgress
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    VStack(alignment: .leading, spacing: 6) {
                        Text("成长路径")
                            .font(.title3.bold())
                        Text("当前 \(growthTreeStageLabel(progress.stage)) · \(progress.exp)/\(GrowthTreeProgress.maxExp) EXP")
                            .font(.caption)
                            .foregroundColor(.appMuted)
                    }

                    VStack(spacing: 10) {
                        ForEach(growthStageMilestones) { item in
                            HStack(spacing: 12) {
                                Image(growthTreeFrameAssets(item.stage).first ?? "growth_tree_seed_0")
                                    .resizable()
                                    .interpolation(.none)
                                    .scaledToFit()
                                    .frame(width: 46, height: 46)
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(item.title)
                                        .font(.subheadline.bold())
                                    Text(item.description)
                                        .font(.caption)
                                        .foregroundColor(.appMuted)
                                }
                                Spacer()
                                Text("\(item.requiredExp)+")
                                    .font(.caption.bold())
                                    .foregroundColor(item.stage <= progress.stage ? .appPrimary : .appMuted)
                            }
                            .padding(12)
                            .background(item.stage == progress.stage ? Color.appPrimary.opacity(0.1) : Color.appCardBg)
                            .cornerRadius(12)
                        }
                    }

                    VStack(alignment: .leading, spacing: 8) {
                        Text("经验来源设计")
                            .font(.subheadline.bold())
                        Text("健康相关问答 +5 EXP；添加病例或健康数据 +15 EXP；持续佩戴血糖仪每日 +30 EXP；完成今日计划任务 +10 EXP。真实持久经验值接口接入后沿用此界面。")
                            .font(.caption)
                            .foregroundColor(.appMuted)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    .padding(12)
                    .background(Color.appCardBg)
                    .cornerRadius(12)
                }
                .padding(16)
            }
            .navigationTitle("成长路径")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button("完成") { dismiss() }
                }
            }
        }
    }
}

private struct HealthTreeEffectOverlay: View {
    let type: String
    let onFinished: () -> Void
    @State private var animate = false

    var body: some View {
        VStack(spacing: 3) {
            Image(healthTreeActionAsset(type))
                .resizable()
                .interpolation(.none)
                .scaledToFit()
                .frame(width: 48, height: 48)
            Text("+10 EXP")
                .font(.caption2.bold())
                .foregroundColor(.appPrimary)
                .padding(.horizontal, 8)
                .padding(.vertical, 3)
                .background(Color.white.opacity(0.9))
                .clipShape(Capsule())
        }
        .scaleEffect(animate ? 1.08 : 0.82)
        .offset(y: animate ? 72 : 10)
        .opacity(animate ? 0 : 1)
        .onAppear {
            withAnimation(.easeOut(duration: 0.95)) {
                animate = true
            }
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.05) {
                onFinished()
            }
        }
    }
}

private struct GrowthTreeProgress {
    static let maxExp = 500
    let exp: Int

    var stage: Int {
        min(5, max(1, exp / 100 + 1))
    }

    var stageProgress: Double {
        isMaxStage ? 1 : Double(exp % 100) / 100.0
    }

    var expToNextStage: Int {
        isMaxStage ? 0 : max(0, stage * 100 - exp)
    }

    var isMaxStage: Bool {
        stage >= 5
    }
}

private struct GrowthPlanDayChoice: Identifiable {
    let offset: Int
    let label: String
    let day: TubeDay?

    var id: Int { offset }
}

private struct GrowthStageMilestone: Identifiable {
    let stage: Int
    let title: String
    let description: String
    let requiredExp: Int

    var id: Int { stage }
}

private let growthStageMilestones: [GrowthStageMilestone] = [
    GrowthStageMilestone(stage: 1, title: "种子期", description: "开始记录健康目标，完成第一次互动。", requiredExp: 0),
    GrowthStageMilestone(stage: 2, title: "发芽期", description: "持续完成计划，小苗从土壤里冒出。", requiredExp: 100),
    GrowthStageMilestone(stage: 3, title: "树苗期", description: "病例、健康数据和问答逐步形成个人上下文。", requiredExp: 200),
    GrowthStageMilestone(stage: 4, title: "成长期", description: "连续数据让计划更稳定，树冠开始展开。", requiredExp: 300),
    GrowthStageMilestone(stage: 5, title: "结果期", description: "长期坚持后结出果实，记录阶段性成果。", requiredExp: 400)
]

private func growthTreeProgress(for week: TubeWeek) -> GrowthTreeProgress {
    let tasks = week.days.flatMap(\.tasks)
    guard !tasks.isEmpty else { return GrowthTreeProgress(exp: 0) }

    let planExp = min(120, tasks.count * 5)
    let ratioSum = tasks.map { min(max($0.ratio, 0), 1) }.reduce(0, +)
    let completionExp = Int((ratioSum / Double(max(tasks.count, 1))) * 260)
    let completedUnitExp = min(120, tasks.reduce(0) { partial, task in
        partial + min(task.completed, max(task.target, 1)) * 8
    })
    let exp = min(GrowthTreeProgress.maxExp - 1, planExp + completionExp + completedUnitExp)
    return GrowthTreeProgress(exp: max(0, exp))
}

private func growthPlanChoices(in week: TubeWeek) -> [GrowthPlanDayChoice] {
    let offsets = [(-2, "前天"), (-1, "昨天"), (0, "今日"), (1, "明天"), (2, "后天")]
    guard let today = growthDateFormatter.date(from: week.today) else {
        return offsets.map { GrowthPlanDayChoice(offset: $0.0, label: $0.1, day: $0.0 == 0 ? week.days.first(where: { $0.is_today }) : nil) }
    }
    return offsets.map { offset, label in
        let date = Calendar.current.date(byAdding: .day, value: offset, to: today) ?? today
        let key = growthDateFormatter.string(from: date)
        return GrowthPlanDayChoice(offset: offset, label: label, day: week.days.first(where: { $0.date == key }))
    }
}

private let growthDateFormatter: DateFormatter = {
    let formatter = DateFormatter()
    formatter.calendar = Calendar(identifier: .gregorian)
    formatter.locale = Locale(identifier: "en_US_POSIX")
    formatter.dateFormat = "yyyy-MM-dd"
    return formatter
}()

private func planRelativeLabel(for day: TubeDay?, today: String) -> String {
    guard let day else { return "今日" }
    if day.is_today { return "今日" }
    guard let todayDate = growthDateFormatter.date(from: today),
          let dayDate = growthDateFormatter.date(from: day.date) else {
        return weekdayName(day.weekday)
    }
    let diff = Calendar.current.dateComponents([.day], from: todayDate, to: dayDate).day ?? 0
    switch diff {
    case -2: return "前天"
    case -1: return "昨天"
    case 1: return "明天"
    case 2: return "后天"
    default: return weekdayName(day.weekday)
    }
}

private func shortDate(_ date: String) -> String {
    String(date.suffix(5))
}

private func growthTreeFrameAssets(_ stage: Int) -> [String] {
    switch stage {
    case 1:
        return ["growth_tree_seed_0", "growth_tree_seed_1", "growth_tree_seed_2", "growth_tree_seed_3"]
    case 2:
        return ["growth_tree_sprout_0", "growth_tree_sprout_1", "growth_tree_sprout_2", "growth_tree_sprout_3"]
    case 3:
        return ["growth_tree_sapling_0", "growth_tree_sapling_1", "growth_tree_sapling_2", "growth_tree_sapling_3", "growth_tree_sapling_4"]
    case 4:
        return ["growth_tree_tree_0", "growth_tree_tree_1", "growth_tree_tree_2", "growth_tree_tree_3", "growth_tree_tree_4", "growth_tree_tree_5"]
    default:
        return ["growth_tree_fruit_0", "growth_tree_fruit_1", "growth_tree_fruit_2", "growth_tree_fruit_3"]
    }
}

private func growthTreePrimaryAsset(_ stage: Int) -> String {
    growthTreeFrameAssets(stage).first ?? "growth_tree_seed_0"
}

private func growthTreeStageLabel(_ stage: Int) -> String {
    switch stage {
    case 1: return "种子期"
    case 2: return "发芽期"
    case 3: return "树苗期"
    case 4: return "成长期"
    default: return "结果期"
    }
}

private struct HealthTreeActionRow: View {
    let day: TubeDay?
    let showMedicationNeed: Bool
    let completingType: String?
    let onComplete: (String) -> Void

    private var tasks: [TubeTaskProgress] {
        (day?.tasks ?? [])
            .filter { showMedicationNeed || $0.task_type != "medication" }
            .sorted {
                let left = planTaskSortOrder($0.task_type)
                let right = planTaskSortOrder($1.task_type)
                if left != right { return left < right }
                return $0.label < $1.label
            }
    }

    var body: some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 104), spacing: 8)], spacing: 8) {
            ForEach(tasks) { task in
                let type = task.task_type
                HealthTreeActionChip(
                    type: type,
                    task: task,
                    isActiveDay: day?.is_today == true,
                    isCompleting: completingType == type,
                    isBusy: completingType != nil,
                    onComplete: onComplete
                )
                .frame(maxWidth: .infinity)
            }
            if tasks.isEmpty {
                Text("今天暂无执行任务")
                    .font(.caption)
                    .foregroundColor(.appMuted)
                    .frame(maxWidth: .infinity, minHeight: 58)
                    .background(Color.white.opacity(0.72))
                    .cornerRadius(12)
            }
        }
    }
}

private struct HealthTreeActionChip: View {
    let type: String
    let task: TubeTaskProgress?
    let isActiveDay: Bool
    let isCompleting: Bool
    let isBusy: Bool
    let onComplete: (String) -> Void

    private var isDone: Bool {
        (task?.ratio ?? 0) >= 1
    }

    var body: some View {
        Button {
            onComplete(type)
        } label: {
            HStack(spacing: 6) {
                ZStack {
                    Circle()
                        .fill(color(for: type).opacity(0.12))
                    if isCompleting {
                        ProgressView()
                            .controlSize(.small)
                            .tint(color(for: type))
                    } else {
                        Image(healthTreeActionAsset(type))
                            .resizable()
                            .interpolation(.none)
                            .scaledToFit()
                            .padding(3)
                    }
                }
                .frame(width: 34, height: 34)

                VStack(alignment: .leading, spacing: 1) {
                    Text(careLabel(for: type))
                        .font(.caption2.bold())
                        .foregroundColor(.appText)
                    if let codes = task?.plan_codes, !codes.isEmpty {
                        Text("计划 \(codes.joined(separator: "/"))")
                            .font(.system(size: 8, weight: .bold))
                            .foregroundColor(.appPrimary)
                            .lineLimit(1)
                    }
                    if let title = task?.title, !title.isEmpty {
                        Text(stripPlanDayPrefix(title))
                            .font(.system(size: 9, weight: .medium))
                            .foregroundColor(.appMuted)
                            .lineLimit(1)
                            .minimumScaleFactor(0.72)
                    }
                    Text(task?.summary ?? healthTreeProgressText(task))
                        .font(.system(size: 10, weight: .semibold))
                        .foregroundColor(color(for: type))
                        .lineLimit(1)
                        .minimumScaleFactor(0.7)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .padding(.horizontal, 8)
            .frame(height: 58)
            .background(Color.white.opacity(0.86))
            .overlay(
                RoundedRectangle(cornerRadius: 12)
                    .stroke(color(for: type).opacity(isActiveDay ? 0.24 : 0.1), lineWidth: 1)
            )
            .cornerRadius(12)
        }
        .buttonStyle(.plain)
        .disabled(!isActiveDay || isDone || isBusy)
        .opacity(isDone ? 0.56 : (isActiveDay ? 1 : 0.68))
    }
}

private struct HealthTreePlanSheet: View {
    let day: TubeDay?
    let tasks: [TubeTaskProgress]
    @Binding var showMedicationNeed: Bool
    let onGeneratePlan: () -> Void
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    VStack(alignment: .leading, spacing: 6) {
                        Text("我的计划")
                            .font(.title3.bold())
                        Text(day?.date ?? "未选择日期")
                            .font(.caption)
                            .foregroundColor(.appMuted)
                    }

                    Button {
                        showMedicationNeed.toggle()
                    } label: {
                        HStack(spacing: 8) {
                            Image(systemName: showMedicationNeed ? "checkmark.square.fill" : "square")
                                .foregroundColor(showMedicationNeed ? .appPrimary : .appMuted)
                            VStack(alignment: .leading, spacing: 2) {
                                Text("有用药需求")
                                    .font(.subheadline.bold())
                                    .foregroundColor(.appText)
                                Text("勾选后才显示用药计划；没有医生或本人确认时不默认展示。")
                                    .font(.caption)
                                    .foregroundColor(.appMuted)
                            }
                            Spacer()
                        }
                        .padding(12)
                        .background(Color.appCardBg)
                        .cornerRadius(10)
                    }
                    .buttonStyle(.plain)

                    if tasks.isEmpty {
                        Text("当前日期暂无可执行计划。")
                            .font(.subheadline)
                            .foregroundColor(.appMuted)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(14)
                            .background(Color.appCardBg)
                            .cornerRadius(10)
                    } else {
                        ForEach(tasks) { task in
                            HealthTreePlanTaskRow(task: task)
                        }
                    }

                    if showMedicationNeed && day?.tasks.contains(where: { $0.task_type == "medication" }) != true {
                        Text("当前计划没有用药任务；如需要，请在生成计划时明确说明用药需求，或先完善用药记录。")
                            .font(.caption)
                            .foregroundColor(.appWarning)
                            .padding(12)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .background(Color.appWarning.opacity(0.08))
                            .cornerRadius(10)
                    }

                    Button {
                        dismiss()
                        onGeneratePlan()
                    } label: {
                        Label("生成计划", systemImage: "sparkles")
                            .font(.headline)
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 12)
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(.appPrimary)
                }
                .padding(16)
            }
            .navigationTitle("计划详情")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button("完成") { dismiss() }
                }
            }
        }
    }
}

private struct HealthTreePlanTaskRow: View {
    let task: TubeTaskProgress

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 10) {
                Image(healthTreeActionAsset(task.task_type))
                    .resizable()
                    .interpolation(.none)
                    .scaledToFit()
                    .frame(width: 34, height: 34)
                    .padding(5)
                    .background(color(for: task.task_type).opacity(0.12))
                    .clipShape(Circle())

                VStack(alignment: .leading, spacing: 2) {
                    Text(stripPlanDayPrefix(task.title ?? task.label))
                        .font(.subheadline.bold())
                    Text(task.summary ?? healthTreeProgressText(task))
                        .font(.caption.bold())
                        .foregroundColor(color(for: task.task_type))
                }
                Spacer()
            }

            if let description = task.description, !description.isEmpty {
                Text(description)
                    .font(.caption)
                    .foregroundColor(.appMuted)
                    .fixedSize(horizontal: false, vertical: true)
            }

            ForEach(task.details ?? [], id: \.self) { detail in
                Text("• \(stripPlanDayPrefix(detail))")
                    .font(.caption)
                    .foregroundColor(.appText)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(12)
        .background(Color.appCardBg)
        .cornerRadius(10)
    }
}

private struct HealthTreeWeekStrip: View {
    let days: [TubeDay]
    let selectedDate: String?
    let onSelect: (TubeDay) -> Void

    var body: some View {
        HStack(spacing: 6) {
            ForEach(days) { day in
                HealthTreeDayMarker(
                    day: day,
                    isSelected: day.date == selectedDate,
                    onSelect: { onSelect(day) }
                )
                    .frame(maxWidth: .infinity)
            }
        }
    }
}

private struct HealthTreeDayMarker: View {
    let day: TubeDay
    let isSelected: Bool
    let onSelect: () -> Void

    var body: some View {
        Button(action: onSelect) {
            VStack(spacing: 4) {
                Image(healthTreeStageAsset(day.is_future ? 1 : healthTreeStage(for: day.completion_ratio), date: day.date))
                    .resizable()
                    .interpolation(.none)
                    .scaledToFit()
                    .frame(width: 32, height: 32)
                    .opacity(day.is_future ? 0.36 : 1)
                Text(weekdayName(day.weekday))
                    .font(.system(size: 11, weight: .bold))
                    .foregroundColor(isSelected ? .white : .appText)
                    .frame(width: 42, height: 24)
                    .background(isSelected ? Color.appPrimary : Color.clear)
                    .clipShape(Capsule())
                Text(day.is_today ? "今天" : "\(Int((day.completion_ratio * 100).rounded()))%")
                    .font(.system(size: 9, weight: .semibold))
                    .foregroundColor(isSelected ? .appPrimary : .appMuted)
                    .lineLimit(1)
                    .minimumScaleFactor(0.7)
            }
            .padding(.vertical, 6)
            .frame(maxWidth: .infinity)
            .background(isSelected ? Color.appPrimary.opacity(0.08) : Color.clear)
            .cornerRadius(9)
        }
        .buttonStyle(.plain)
    }
}

private struct TubeWeekCard: View {
    let week: TubeWeek
    let isViewingCurrentWeek: Bool
    let completingType: String?
    let onPreviousWeek: () -> Void
    let onNextWeek: () -> Void
    let onThisWeek: () -> Void
    let onComplete: (String) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                VStack(alignment: .leading, spacing: 3) {
                    Text("试管式计划执行")
                        .font(.headline)
                    Text("\(week.week_start) - \(week.week_end)")
                        .font(.caption)
                        .foregroundColor(.appMuted)
                }
                Spacer()
                if !isViewingCurrentWeek {
                    Button("本周", action: onThisWeek)
                        .font(.caption.bold())
                        .foregroundColor(.appPrimary)
                }
            }

            HStack {
                Button(action: onPreviousWeek) {
                    Label("上周", systemImage: "chevron.left")
                        .labelStyle(.iconOnly)
                        .frame(width: 38, height: 38)
                        .background(Color.appPrimary.opacity(0.08))
                        .clipShape(Circle())
                }
                .accessibilityLabel("上周")

                weeklyTubes

                Button(action: onNextWeek) {
                    Label("下周", systemImage: "chevron.right")
                        .labelStyle(.iconOnly)
                        .frame(width: 38, height: 38)
                        .background(Color.appPrimary.opacity(0.08))
                        .clipShape(Circle())
                }
                .accessibilityLabel("下周")
            }

            Text("点击今天上方图标完成任务，试管液位会按运动、用药、饮食分层上升。")
                .font(.caption)
                .foregroundColor(.appMuted)
        }
        .cardStyle()
    }

    private var weeklyTubes: some View {
        HStack(alignment: .bottom, spacing: 0) {
            ForEach(week.days) { day in
                TubeDayColumn(
                    day: day,
                    completingType: completingType,
                    onComplete: onComplete
                )
                .frame(maxWidth: .infinity)
            }
        }
        .frame(height: 250)
    }
}

private struct TubeDayColumn: View {
    let day: TubeDay
    let completingType: String?
    let onComplete: (String) -> Void

    var body: some View {
        VStack(spacing: 6) {
            if day.is_today {
                TodayTaskButtons(
                    tasks: day.tasks,
                    completingType: completingType,
                    onComplete: onComplete
                )
                .frame(height: 92)
            } else {
                Spacer().frame(height: 92)
            }

            TubeGlassView(tasks: day.tasks, isToday: day.is_today, isFuture: day.is_future)
                .frame(width: 34, height: 112)
                .opacity(day.is_future ? 0.42 : 1)

            Text(weekdayName(day.weekday))
                .font(.system(size: 11, weight: .bold))
                .foregroundColor(day.is_today ? .white : .appText)
                .frame(width: 42, height: 24)
                .background(day.is_today ? Color.appPrimary : Color.clear)
                .clipShape(Capsule())

            if day.is_today {
                Image(systemName: "arrowtriangle.up.fill")
                    .font(.title3)
                    .foregroundColor(.appPrimary)
                Text("今天")
                    .font(.caption2.bold())
                    .foregroundColor(.appPrimary)
            } else {
                Spacer().frame(height: 30)
            }
        }
    }
}

private struct TodayTaskButtons: View {
    let tasks: [TubeTaskProgress]
    let completingType: String?
    let onComplete: (String) -> Void

    var body: some View {
        VStack(spacing: 5) {
            ForEach(["exercise", "medication", "diet"], id: \.self) { type in
                if let task = tasks.first(where: { $0.task_type == type }) {
                    Button {
                        onComplete(type)
                    } label: {
                        HStack(spacing: 4) {
                            if completingType == type {
                                ProgressView()
                                    .controlSize(.small)
                                    .tint(color(for: type))
                            } else {
                                Image(systemName: iconName(for: type))
                                    .font(.caption)
                            }
                            Text(progressText(task))
                                .font(.system(size: 10, weight: .semibold))
                                .lineLimit(1)
                                .minimumScaleFactor(0.7)
                        }
                        .frame(width: 58, height: 25)
                        .background(Color.white)
                        .overlay(
                            RoundedRectangle(cornerRadius: 8)
                                .stroke(color(for: type).opacity(0.35), lineWidth: 1)
                        )
                        .foregroundColor(color(for: type))
                        .cornerRadius(8)
                    }
                    .buttonStyle(.plain)
                    .disabled(task.ratio >= 1 || completingType != nil)
                    .opacity(task.ratio >= 1 ? 0.72 : 1)
                }
            }
        }
    }

    private func progressText(_ task: TubeTaskProgress) -> String {
        if let completed = task.completed_value,
           let target = task.target_value,
           task.unit == "kcal",
           completed > 0 {
            return "\(Int(completed))/\(Int(target))"
        }
        return "\(task.completed)/\(max(task.target, 1))"
    }
}

private struct TubeGlassView: View {
    let tasks: [TubeTaskProgress]
    let isToday: Bool
    let isFuture: Bool

    var body: some View {
        GeometryReader { geo in
            let innerHeight = geo.size.height - 12
            ZStack(alignment: .bottom) {
                RoundedRectangle(cornerRadius: 17)
                    .fill(Color.white.opacity(0.82))

                VStack(spacing: 0) {
                    Spacer(minLength: 0)
                    ForEach(layerTasks(), id: \.task_type) { task in
                        color(for: task.task_type)
                            .frame(height: max(0, innerHeight * CGFloat(min(max(task.ratio, 0), 1)) / 3))
                    }
                }
                .clipShape(RoundedRectangle(cornerRadius: 16))
                .opacity(isFuture ? 0 : 1)

                VStack(spacing: 10) {
                    ForEach(0..<5, id: \.self) { _ in
                        Rectangle()
                            .fill(Color.appPrimary.opacity(0.22))
                            .frame(width: 8, height: 1)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(.leading, 7)
                    }
                    Spacer()
                }
                .padding(.top, 26)

                RoundedRectangle(cornerRadius: 17)
                    .stroke(isToday ? Color.appPrimary : Color.appPrimary.opacity(0.45), lineWidth: isToday ? 2 : 1.4)

                Capsule()
                    .stroke(isToday ? Color.appPrimary : Color.appPrimary.opacity(0.5), lineWidth: isToday ? 2 : 1.4)
                    .frame(height: 11)
                    .offset(y: -geo.size.height / 2 + 4)
            }
            .shadow(color: isToday ? Color.appPrimary.opacity(0.16) : .black.opacity(0.05), radius: 8, x: 0, y: 5)
        }
    }

    private func layerTasks() -> [TubeTaskProgress] {
        ["diet", "medication", "exercise"].compactMap { type in
            tasks.first(where: { $0.task_type == type })
        }
    }
}

private func weekdayName(_ weekday: Int) -> String {
    switch weekday {
    case 1: return "周一"
    case 2: return "周二"
    case 3: return "周三"
    case 4: return "周四"
    case 5: return "周五"
    case 6: return "周六"
    default: return "周日"
    }
}

private func iconName(for type: String) -> String {
    switch type {
    case "exercise": return "figure.walk"
    case "medication": return "pills.fill"
    case "diet": return "fork.knife"
    case "sleep": return "moon.zzz.fill"
    case "hydration": return "drop.fill"
    case "record": return "waveform.path.ecg.rectangle"
    default: return "checkmark.circle"
    }
}

private func color(for type: String) -> Color {
    switch type {
    case "exercise": return Color(hex: "75C043")
    case "medication": return Color(hex: "2F80ED")
    case "diet": return Color(hex: "FF8A1F")
    case "sleep": return Color(hex: "6B6FD6")
    case "hydration": return Color(hex: "21A7C7")
    default: return .appPrimary
    }
}

private func healthTreeStage(for ratio: Double) -> Int {
    let value = min(max(ratio, 0), 1)
    switch value {
    case ..<0.12: return 1
    case ..<0.28: return 2
    case ..<0.48: return 3
    case ..<0.72: return 4
    case ..<0.92: return 5
    default: return 6
    }
}

private func healthTreeStageAsset(_ stage: Int, date: String? = nil) -> String {
    switch stage {
    case 1: return "healthtree_tree_01_seed"
    case 2: return "healthtree_tree_02_sprout"
    case 3: return "healthtree_tree_03_seedling"
    case 4: return "healthtree_tree_04_young_tree"
    case 5: return "healthtree_tree_05_flowering"
    default: return healthTreeFruitingAsset(date: date)
    }
}

private func healthTreeFruitingAsset(date: String?) -> String {
    let seed = stableTreeSkinSeed(date ?? "")
    switch seed {
    case 0..<20:
        return "healthtree_tree_06_fruiting"
    case 20..<40:
        return "healthtree_tree_06_apple"
    case 40..<60:
        return "healthtree_tree_06_pear"
    case 60..<75:
        return "healthtree_tree_06_golden"
    case 75..<90:
        return "healthtree_tree_06_yuanbao"
    default:
        return "healthtree_tree_06_peach_immortal"
    }
}

private func stableTreeSkinSeed(_ text: String) -> Int {
    var value = 0
    for (idx, scalar) in text.unicodeScalars.enumerated() {
        value = (value + Int(scalar.value) * (idx + 17)) % 100
    }
    return value
}

private func healthTreeStageLabel(_ stage: Int) -> String {
    switch stage {
    case 1: return "种子期"
    case 2: return "发芽期"
    case 3: return "幼苗期"
    case 4: return "成长中"
    case 5: return "开花期"
    default: return "结果期"
    }
}

private func healthTreeIconAsset(_ type: String) -> String {
    switch type {
    case "exercise": return "healthtree_icon_exercise_sun"
    case "diet": return "healthtree_icon_diet_water"
    case "medication": return "healthtree_icon_medication_dew"
    case "hydration": return "healthtree_icon_diet_water"
    case "sleep": return "healthtree_icon_record_data_light"
    default: return "healthtree_icon_multiomics_precision"
    }
}

private func healthTreeActionAsset(_ type: String) -> String {
    switch type {
    case "exercise": return "healthtree_env_sun"
    case "medication": return "healthtree_env_medkit"
    case "diet": return "healthtree_env_watercan"
    case "hydration": return "healthtree_env_watercan"
    case "sleep": return "healthtree_icon_record_data_light"
    default: return healthTreeIconAsset(type)
    }
}

private func careLabel(for type: String) -> String {
    switch type {
    case "exercise": return "运动"
    case "diet": return "饮食"
    case "medication": return "用药"
    case "hydration": return "饮水"
    case "sleep": return "睡眠"
    default: return "照护"
    }
}

private func healthTreeProgressText(_ task: TubeTaskProgress?) -> String {
    guard let task else { return "0/1" }
    if let completed = task.completed_value,
       let target = task.target_value,
       task.unit == "kcal",
       completed > 0 {
        return "\(Int(completed))/\(Int(target)) kcal"
    }
    return "\(task.completed)/\(max(task.target, 1))"
}
