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

// MARK: - 健康计划与试管式执行入口

struct HealthPlanView: View {
    @StateObject private var vm = HealthPlanViewModel()

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
                            onEffectFinished: { vm.clearCompletionEffect() }
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

    private var planDetail: some View {
        VStack(alignment: .leading, spacing: 10) {
            Label("计划详情", systemImage: "doc.text.magnifyingglass")
                .font(.headline)

            if let plan = vm.selectedPlan {
                Text(plan.title)
                    .font(.title3.bold())
                    .foregroundColor(.appText)
                if let goal = plan.goal, !goal.isEmpty {
                    Text(goal)
                        .font(.subheadline)
                        .foregroundColor(.appMuted)
                        .fixedSize(horizontal: false, vertical: true)
                }
                HStack(spacing: 8) {
                    statPill("\(plan.task_count)", "任务")
                    statPill("\(plan.completed_task_count)", "完成")
                    statPill("\(short(plan.start_date))", "开始")
                }

                Divider()

                ForEach(plan.tasks.prefix(8)) { task in
                    HStack(alignment: .top, spacing: 10) {
                        Image(systemName: iconName(for: task.task_type))
                            .foregroundColor(color(for: task.task_type))
                            .frame(width: 22)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(task.title)
                                .font(.subheadline.bold())
                            Text("\(short(task.date)) · \(task.completed_count)/\(max(task.target_count, 1))")
                                .font(.caption)
                                .foregroundColor(.appMuted)
                        }
                        Spacer()
                        if task.status == "completed" {
                            Image(systemName: "checkmark.circle.fill")
                                .foregroundColor(.appSuccess)
                        }
                    }
                    .padding(.vertical, 4)
                }
            } else {
                Text("保存计划后，这里会展示目标、周期和每日任务。")
                    .font(.subheadline)
                    .foregroundColor(.appMuted)
            }
        }
        .cardStyle()
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

private let healthTreeTaskTypes = ["exercise", "medication", "diet"]

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
    @State private var selectedDate: String?

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

    private var activeRatio: Double {
        activeDay?.completion_ratio ?? 0
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
                Text("\(Int((activeRatio * 100).rounded()))%")
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

            HealthTreeStageView(
                stage: healthTreeStage(for: activeRatio),
                completionRatio: activeRatio,
                day: activeDay,
                hasOmicsData: week.has_omics_data ?? false,
                completingType: completingType,
                recentEffect: recentEffect,
                onComplete: onComplete,
                onEffectFinished: onEffectFinished
            )
            .frame(maxWidth: .infinity)

            HealthTreeWeekStrip(
                days: week.days,
                selectedDate: activeDay?.date,
                onSelect: { selectedDate = $0.date }
            )
        }
        .cardStyle()
        .onChange(of: week.week_start) { _, _ in
            selectedDate = nil
        }
        .gesture(
            DragGesture(minimumDistance: 24)
                .onEnded { value in
                    if value.translation.width > 48 { onPreviousWeek() }
                    if value.translation.width < -48 { onNextWeek() }
                }
        )
    }
}

private struct HealthTreeStageView: View {
    let stage: Int
    let completionRatio: Double
    let day: TubeDay?
    let hasOmicsData: Bool
    let completingType: String?
    let recentEffect: String?
    let onComplete: (String) -> Void
    let onEffectFinished: () -> Void
    @State private var sway = false

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

            VStack(spacing: 12) {
                HealthTreeActionRow(
                    day: day,
                    completingType: completingType,
                    onComplete: onComplete
                )

                ZStack(alignment: .bottom) {
                    if hasOmicsData {
                        Image("healthtree_pot_rich_soil")
                            .resizable()
                            .interpolation(.none)
                            .scaledToFit()
                            .frame(width: 88, height: 46)
                            .offset(y: -8)
                            .opacity(0.92)
                    }

                    Image(healthTreeStageAsset(stage))
                        .resizable()
                        .interpolation(.none)
                        .scaledToFit()
                        .frame(width: 148, height: 148)
                        .offset(y: -8)
                        .rotationEffect(.degrees(sway ? 1.2 : -1.2), anchor: .bottom)
                        .shadow(color: Color.appPrimary.opacity(0.13), radius: 10, x: 0, y: 7)
                        .onAppear {
                            withAnimation(.easeInOut(duration: 2.6).repeatForever(autoreverses: true)) {
                                sway.toggle()
                            }
                        }
                }
                .frame(height: 166)

                Text(healthTreeStageLabel(stage))
                    .font(.caption.bold())
                    .foregroundColor(.appPrimary)
                    .padding(.bottom, 4)
            }
            .padding(12)

            if let recentEffect {
                HealthTreeEffectOverlay(type: recentEffect, onFinished: onEffectFinished)
            }
        }
        .frame(height: 300)
        .clipShape(RoundedRectangle(cornerRadius: 18))
        .overlay(
            RoundedRectangle(cornerRadius: 18)
                .stroke(Color.appPrimary.opacity(0.12), lineWidth: 1)
        )
    }
}

private struct HealthTreeEffectOverlay: View {
    let type: String
    let onFinished: () -> Void
    @State private var animate = false

    var body: some View {
        Image(healthTreeActionAsset(type))
            .resizable()
            .interpolation(.none)
            .scaledToFit()
            .frame(width: 48, height: 48)
            .scaleEffect(animate ? 1.08 : 0.82)
            .offset(y: animate ? 68 : 8)
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

private struct HealthTreeActionRow: View {
    let day: TubeDay?
    let completingType: String?
    let onComplete: (String) -> Void

    var body: some View {
        HStack(spacing: 8) {
            ForEach(healthTreeTaskTypes, id: \.self) { type in
                let task = day?.tasks.first(where: { $0.task_type == type })
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
                    Text(healthTreeProgressText(task))
                        .font(.system(size: 10, weight: .semibold))
                        .foregroundColor(color(for: type))
                        .lineLimit(1)
                        .minimumScaleFactor(0.7)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .padding(.horizontal, 8)
            .frame(height: 48)
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
                Image(healthTreeStageAsset(day.is_future ? 1 : healthTreeStage(for: day.completion_ratio)))
                    .resizable()
                    .interpolation(.none)
                    .scaledToFit()
                    .frame(width: 32, height: 32)
                    .opacity(day.is_future ? 0.36 : 1)
                Text(weekdayName(day.weekday))
                    .font(.caption.bold())
                    .foregroundColor(isSelected ? .white : .appText)
                    .frame(width: 26, height: 24)
                    .background(isSelected ? Color.appPrimary : Color.clear)
                    .clipShape(Circle())
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
        .gesture(
            DragGesture(minimumDistance: 24)
                .onEnded { value in
                    if value.translation.width > 48 { onPreviousWeek() }
                    if value.translation.width < -48 { onNextWeek() }
                }
        )
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
                .font(.caption.bold())
                .foregroundColor(day.is_today ? .white : .appText)
                .frame(width: 30, height: 24)
                .background(day.is_today ? Color.appPrimary : Color.clear)
                .clipShape(Circle())

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
    case 1: return "一"
    case 2: return "二"
    case 3: return "三"
    case 4: return "四"
    case 5: return "五"
    case 6: return "六"
    default: return "日"
    }
}

private func iconName(for type: String) -> String {
    switch type {
    case "exercise": return "figure.walk"
    case "medication": return "pills.fill"
    case "diet": return "fork.knife"
    case "record": return "waveform.path.ecg.rectangle"
    default: return "checkmark.circle"
    }
}

private func color(for type: String) -> Color {
    switch type {
    case "exercise": return Color(hex: "75C043")
    case "medication": return Color(hex: "2F80ED")
    case "diet": return Color(hex: "FF8A1F")
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

private func healthTreeStageAsset(_ stage: Int) -> String {
    switch stage {
    case 1: return "healthtree_tree_01_seed"
    case 2: return "healthtree_tree_02_sprout"
    case 3: return "healthtree_tree_03_seedling"
    case 4: return "healthtree_tree_04_young_tree"
    case 5: return "healthtree_tree_05_flowering"
    default: return "healthtree_tree_06_fruiting"
    }
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
    default: return "healthtree_icon_multiomics_precision"
    }
}

private func healthTreeActionAsset(_ type: String) -> String {
    switch type {
    case "exercise": return "healthtree_env_sun"
    case "medication": return "healthtree_env_medkit"
    case "diet": return "healthtree_env_watercan"
    default: return healthTreeIconAsset(type)
    }
}

private func careLabel(for type: String) -> String {
    switch type {
    case "exercise": return "运动"
    case "diet": return "饮食"
    case "medication": return "用药"
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
