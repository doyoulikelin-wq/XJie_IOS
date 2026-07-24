import SwiftUI

/// 用药首页的次级模块。首页只负责今天与下一剂，复杂信息进入对应详情页。
enum MedicationDashboardDestination: String, Identifiable, CaseIterable {
    case plans
    case records
    case reactions
    case course

    var id: String { rawValue }

    var title: String {
        switch self {
        case .plans: return "当前用药计划"
        case .records: return "服药记录"
        case .reactions: return "不适与反应"
        case .course: return "疗程与余量"
        }
    }

    var subtitle: String {
        switch self {
        case .plans: return "查看、编辑计划与本机提醒"
        case .records: return "查看每日剂次与已确认率"
        case .reactions: return "记录与服药时间接近的身体感受"
        case .course: return "查看疗程进度与预计剩余"
        }
    }

    var icon: String {
        switch self {
        case .plans: return "list.clipboard.fill"
        case .records: return "doc.text.fill"
        case .reactions: return "heart.text.square.fill"
        case .course: return "shippingbox.fill"
        }
    }
}

/// 把服务端可信状态转换成首页有限状态，避免 SwiftUI 各分支自行猜测“下一次用药”。
enum MedicationDashboardHeroState: Equatable {
    case loading
    case noMedication
    case nextDose(MedicationTodayTask)
    case allHandled(String)

    /// - Parameters:
    ///   - today: 服务端返回的当日可信剂次汇总。
    ///   - plans: 当前主体的已确认用药计划。
    ///   - isLoading: 当前是否仍在首次加载。
    static func resolve(
        today: MedicationTodaySummary?,
        plans: [TrustedMedicationPlan],
        isLoading: Bool
    ) -> Self {
        if isLoading && today == nil { return .loading }
        let visiblePlans = plans.filter { $0.status != .retracted }
        guard !visiblePlans.isEmpty else { return .noMedication }
        if let next = today?.next_task {
            return .nextDose(next)
        }
        return .allHandled(today?.empty_state ?? "今天的用药已全部处理")
    }
}

enum MedicationDashboardReminderTone: Equatable {
    case active
    case neutral
    case warning
}

/// 下一剂卡片展示的真实本机通知状态；只有协调器确实排期后才显示“已安排”。
struct MedicationDashboardReminderState: Equatable {
    let title: String
    let compactTitle: String
    let detail: String
    let icon: String
    let tone: MedicationDashboardReminderTone

    /// - Parameters:
    ///   - task: 当前下一剂任务，用于绑定对应计划。
    ///   - plans: 服务端已确认计划。
    ///   - settings: 当前账号和主体隔离后的本地提醒设置。
    ///   - permission: iOS 通知权限真实状态。
    ///   - scheduledCount: 协调器本轮成功安排的通知总数。
    static func resolve(
        task: MedicationTodayTask,
        plans: [TrustedMedicationPlan],
        settings: [Int: MedicationReminderSettings],
        permission: MedicationReminderPermissionState,
        scheduledCount: Int
    ) -> Self {
        guard let plan = plans.first(where: { $0.plan_id == task.plan_id }) else {
            return Self(
                title: "提醒信息暂不可用",
                compactTitle: "提醒不可用",
                detail: "当前剂次没有匹配到已确认计划",
                icon: "bell.slash.fill",
                tone: .warning
            )
        }
        let reminder = settings[task.plan_id]
        let versionMatches = reminder.map {
            MedicationReminderPolicy.isVersionCompatible($0, with: plan)
        } == true

        switch permission {
        case .denied:
            return Self(
                title: "通知权限已关闭",
                compactTitle: "权限已关闭",
                detail: "打开提醒设置可前往系统设置恢复",
                icon: "bell.slash.fill",
                tone: .warning
            )
        case .unavailable:
            return Self(
                title: "当前环境不能使用系统通知",
                compactTitle: "通知不可用",
                detail: "提醒没有被冒充为已安排",
                icon: "bell.slash.fill",
                tone: .warning
            )
        case .unknown:
            return Self(
                title: "正在检查提醒状态",
                compactTitle: "检查提醒",
                detail: "稍后会按当前账号与计划版本核对",
                icon: "bell.badge.fill",
                tone: .neutral
            )
        case .notDetermined, .allowed:
            break
        }

        if reminder?.enabled == true,
           versionMatches,
           permission == .allowed,
           scheduledCount > 0 {
            return Self(
                title: "下一次用药提醒已安排",
                compactTitle: "提醒已安排",
                detail: "通知只负责提醒，仍需你在应用内确认",
                icon: "bell.badge.fill",
                tone: .active
            )
        }
        if reminder?.enabled == true, !versionMatches {
            return Self(
                title: "计划已更新，请重新确认提醒",
                compactTitle: "需重设提醒",
                detail: "旧版本通知已停止",
                icon: "bell.badge.fill",
                tone: .warning
            )
        }
        return Self(
            title: "下一次用药提醒未开启",
            compactTitle: "设置提醒",
            detail: permission == .notDetermined
                ? "点此设置；保存时才会请求通知权限"
                : "点此设置提醒时间、声音与锁屏隐私",
            icon: "bell.fill",
            tone: .neutral
        )
    }
}

/// 参考图对应的用药首页内容。所有按钮只通过回调触发父页面已有的可信操作。
struct MedicationDashboardView: View {
    let screenHeight: CGFloat
    let today: MedicationTodaySummary?
    let plans: [TrustedMedicationPlan]
    let reactionCount: Int
    let reminderSettings: [Int: MedicationReminderSettings]
    let reminderPermission: MedicationReminderPermissionState
    let scheduledReminderCount: Int
    let isLoading: Bool
    let isMutating: Bool
    let onClose: () -> Void
    let onAdd: () -> Void
    let onConfirm: (MedicationTodayTask) -> Void
    let onSnooze: (MedicationTodayTask) -> Void
    let onSkip: (MedicationTodayTask) -> Void
    let onReaction: (MedicationTodayTask) -> Void
    let onReminder: (TrustedMedicationPlan) -> Void
    let onTask: (MedicationTodayTask) -> Void
    let onDestination: (MedicationDashboardDestination) -> Void

    private var heroState: MedicationDashboardHeroState {
        .resolve(today: today, plans: plans, isLoading: isLoading)
    }

    private var visiblePlans: [TrustedMedicationPlan] {
        plans.filter { $0.status != .retracted }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            header
            summaryCards
            nextDoseCard
            if !visiblePlans.isEmpty {
                todayMedicationCard
                secondaryFunctions
            }
        }
    }

    private var header: some View {
        HStack(spacing: 12) {
            Button(action: onClose) {
                Image(systemName: "chevron.left")
                    .font(.body.bold())
                    .foregroundStyle(Color(hex: "1268BD"))
                    .frame(width: 44, height: 44)
                    .background(.white.opacity(0.58), in: Circle())
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .disabled(isMutating)
            .accessibilityLabel("返回")

            ZStack {
                Circle()
                    .fill(
                        LinearGradient(
                            colors: [Color(hex: "1A73E8"), Color(hex: "48D4C3")],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        )
                    )
                Image(systemName: "pills.fill")
                    .font(.title2.bold())
                    .foregroundStyle(.white)
            }
            .frame(width: 54, height: 54)
            .accessibilityHidden(true)

            VStack(alignment: .leading, spacing: 2) {
                Text("用药记录")
                    .font(.title.bold())
                    .foregroundStyle(Color(hex: "0C315C"))
                    .accessibilityIdentifier("xage.medication.title")
                Text("药物、提醒与疗程")
                    .font(.subheadline.weight(.medium))
                    .foregroundStyle(Color(hex: "5D7890"))
            }

            Spacer(minLength: 4)

            Button(action: onAdd) {
                Image(systemName: "plus")
                    .font(.title3.weight(.medium))
                    .foregroundStyle(Color(hex: "0D3C6E"))
                    .frame(width: 48, height: 48)
                    .background(.white.opacity(0.48), in: Circle())
                    .overlay(Circle().stroke(Color(hex: "6AA7E8").opacity(0.55)))
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .disabled(isMutating || today == nil)
            .accessibilityLabel("新增用药方式")
            .accessibilityIdentifier("xage.medication.add")
        }
    }

    private var summaryCards: some View {
        HStack(spacing: 10) {
            MedicationDashboardCountCard(
                title: "今日计划",
                value: today?.planned_count ?? 0,
                icon: "calendar",
                color: Color(hex: "1670D2"),
                accessibilityID: "xage.medication.summary.planned"
            )
            MedicationDashboardCountCard(
                title: "已服用",
                value: today?.taken_count ?? 0,
                icon: "checkmark",
                color: Color(hex: "20B9A5"),
                accessibilityID: "xage.medication.summary.taken"
            )
            MedicationDashboardCountCard(
                title: "待确认",
                value: pendingCount,
                icon: "clock.fill",
                color: Color(hex: "1670D2"),
                accessibilityID: "xage.medication.summary.pending"
            )
        }
    }

    private var pendingCount: Int {
        guard let today else { return 0 }
        return today.awaiting_confirmation_count
            + today.possibly_missed_count
            + today.snoozed_count
    }

    @ViewBuilder
    private var nextDoseCard: some View {
        switch heroState {
        case .loading:
            MedicationDashboardLoadingHero(minimumHeight: heroMinimumHeight)
        case .noMedication:
            emptyHero
        case .nextDose(let task):
            nextDoseHero(task)
        case .allHandled(let message):
            handledHero(message)
        }
    }

    private var heroMinimumHeight: CGFloat {
        max(screenHeight / 3, 270)
    }

    private var emptyHero: some View {
        VStack(spacing: 18) {
            Spacer(minLength: 0)
            Image(systemName: "pills.circle")
                .font(.system(size: 54, weight: .medium))
                .foregroundStyle(Color(hex: "438EDB"))
            Text("还没有添加用药提醒哦，\n快去添加第一条用药提醒吧")
                .font(.title3.bold())
                .foregroundStyle(Color(hex: "0C315C"))
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
                .accessibilityIdentifier("xage.medication.hero.empty")
            Button(action: onAdd) {
                Label("添加第一条用药提醒", systemImage: "plus.circle.fill")
                    .font(.headline)
                    .frame(maxWidth: .infinity, minHeight: 50)
            }
            .buttonStyle(MedicationDashboardGradientButtonStyle())
            .disabled(isMutating)
            Spacer(minLength: 0)
        }
        .padding(22)
        .frame(maxWidth: .infinity, minHeight: heroMinimumHeight)
        .background(MedicationDashboardHeroBackground())
    }

    private func handledHero(_ message: String) -> some View {
        VStack(spacing: 16) {
            Spacer(minLength: 0)
            Image(systemName: "checkmark.circle.fill")
                .font(.system(size: 54, weight: .medium))
                .foregroundStyle(Color(hex: "20B9A5"))
            Text("今天的用药已处理")
                .font(.title2.bold())
                .foregroundStyle(Color(hex: "0C315C"))
            Text(message)
                .font(.subheadline)
                .foregroundStyle(Color(hex: "5D7890"))
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 0)
        }
        .padding(22)
        .frame(maxWidth: .infinity, minHeight: heroMinimumHeight)
        .background(MedicationDashboardHeroBackground())
        .accessibilityIdentifier("xage.medication.hero.handled")
    }

    private func nextDoseHero(_ task: MedicationTodayTask) -> some View {
        let plan = plans.first { $0.plan_id == task.plan_id }
        let reminder = MedicationDashboardReminderState.resolve(
            task: task,
            plans: plans,
            settings: reminderSettings,
            permission: reminderPermission,
            scheduledCount: scheduledReminderCount
        )
        return VStack(alignment: .leading, spacing: 7) {
            HStack(spacing: 8) {
                Label("下一次服药", systemImage: "clock.fill")
                    .font(.title3.bold())
                Spacer(minLength: 0)
                Button {
                    if let plan { onReminder(plan) }
                } label: {
                    Label(reminder.compactTitle, systemImage: reminder.icon)
                        .font(.caption.bold())
                        .lineLimit(1)
                        .minimumScaleFactor(0.75)
                }
                .buttonStyle(.plain)
                .disabled(plan == nil || isMutating)
                .accessibilityLabel(reminder.title)
                .accessibilityValue(reminder.detail)
                .accessibilityIdentifier("xage.medication.hero.reminder")
            }
            .foregroundStyle(reminderColor(reminder.tone))

            HStack(alignment: .center, spacing: 12) {
                VStack(alignment: .leading, spacing: 3) {
                    Text(task.scheduled_time)
                        .font(.system(size: 42, weight: .bold, design: .rounded))
                        .monospacedDigit()
                        .foregroundStyle(Color(hex: "092E57"))
                        .minimumScaleFactor(0.72)
                    Text([task.displayName, task.dose_text].compactMap { $0 }.joined(separator: " "))
                        .font(.headline)
                        .foregroundStyle(Color(hex: "0C315C"))
                        .fixedSize(horizontal: false, vertical: true)
                    if let instruction = doseInstruction(plan) {
                        Label(instruction, systemImage: "takeoutbag.and.cup.and.straw.fill")
                            .font(.subheadline)
                            .foregroundStyle(Color(hex: "5D7890"))
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                Spacer(minLength: 0)
                ZStack {
                    Circle()
                        .fill(Color(hex: "DDEEFF").opacity(0.9))
                    Image(systemName: "pills.fill")
                        .font(.system(size: 36, weight: .semibold))
                        .foregroundStyle(
                            LinearGradient(
                                colors: [.white, Color(hex: "9BC7F5")],
                                startPoint: .topLeading,
                                endPoint: .bottomTrailing
                            )
                        )
                        .shadow(color: Color(hex: "4B8FD2").opacity(0.24), radius: 6, y: 4)
                }
                .frame(width: 64, height: 64)
                .accessibilityHidden(true)
            }

            if task.status == .possiblyMissed {
                Label(
                    "提醒时间已过，仍需你确认；请勿自行在下一次加倍。",
                    systemImage: "exclamationmark.triangle.fill"
                )
                .font(.caption.weight(.semibold))
                .foregroundStyle(Color.orange)
                .fixedSize(horizontal: false, vertical: true)
            }

            Button { onConfirm(task) } label: {
                Label("确认已服用", systemImage: "checkmark.circle.fill")
                    .font(.headline)
                    .frame(maxWidth: .infinity, minHeight: 46)
            }
            .buttonStyle(MedicationDashboardGradientButtonStyle())
            .disabled(isMutating)
            .accessibilityIdentifier("xage.medication.hero.confirm")

            HStack(spacing: 10) {
                MedicationDashboardOutlineButton(
                    title: "稍后提醒",
                    icon: "clock.arrow.circlepath",
                    accessibilityID: "xage.medication.hero.snooze"
                ) {
                    onSnooze(task)
                }
                MedicationDashboardOutlineButton(
                    title: "本次跳过",
                    icon: "nosign",
                    accessibilityID: "xage.medication.hero.skip"
                ) {
                    onSkip(task)
                }
            }
            .disabled(isMutating)

            Button { onReaction(task) } label: {
                Label("记录不适", systemImage: "note.text.badge.plus")
                    .font(.subheadline.bold())
                    .frame(maxWidth: .infinity, minHeight: 34)
            }
            .buttonStyle(.plain)
            .foregroundStyle(Color(hex: "1268BD"))
            .disabled(isMutating)
            .accessibilityIdentifier("xage.medication.hero.reaction")
        }
        .padding(16)
        .frame(maxWidth: .infinity, minHeight: heroMinimumHeight, alignment: .topLeading)
        .background {
            // 主卡背景作为独立的尺寸探针；不能把标识挂在含按钮的父容器上，
            // 否则 SwiftUI 会合并无障碍树，确认、稍后提醒等子按钮将无法单独访问。
            MedicationDashboardHeroBackground()
                .accessibilityElement(children: .ignore)
                .accessibilityLabel("下一次服药卡片")
                .accessibilityIdentifier("xage.medication.hero.next")
        }
    }

    private func doseInstruction(_ plan: TrustedMedicationPlan?) -> String? {
        if let instruction = plan?.instructions?.trimmingCharacters(in: .whitespacesAndNewlines),
           !instruction.isEmpty {
            return instruction
        }
        guard let plan, plan.meal_relation != .unspecified else { return nil }
        return plan.meal_relation.title
    }

    private func reminderColor(_ tone: MedicationDashboardReminderTone) -> Color {
        switch tone {
        case .active: return Color(hex: "0B9E89")
        case .neutral: return Color(hex: "496A83")
        case .warning: return .orange
        }
    }

    private var todayMedicationCard: some View {
        VStack(alignment: .leading, spacing: 2) {
            Label("今日用药", systemImage: "list.bullet")
                .font(.title3.bold())
                .foregroundStyle(Color(hex: "0C315C"))
                .padding(.bottom, 6)
                .accessibilityIdentifier("xage.medication.today")

            if today?.tasks.isEmpty != false {
                Text("今天没有计划剂次")
                    .font(.subheadline)
                    .foregroundStyle(Color(hex: "6D8498"))
                    .padding(.vertical, 14)
            } else {
                ForEach(Array((today?.tasks ?? []).prefix(3))) { task in
                    Button { onTask(task) } label: {
                        MedicationDashboardTaskRow(task: task)
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("xage.medication.today.\(task.occurrence_key)")
                    if task.id != Array((today?.tasks ?? []).prefix(3)).last?.id {
                        Divider().opacity(0.45)
                    }
                }
            }
        }
        .padding(16)
        .background(MedicationDashboardCardBackground())
    }

    private var secondaryFunctions: some View {
        VStack(spacing: 0) {
            ForEach(MedicationDashboardDestination.allCases) { destination in
                Button { onDestination(destination) } label: {
                    HStack(spacing: 12) {
                        Image(systemName: destination.icon)
                            .font(.headline)
                            .foregroundStyle(.white)
                            .frame(width: 42, height: 42)
                            .background(
                                LinearGradient(
                                    colors: [Color(hex: "22C8B4"), Color(hex: "309CD1")],
                                    startPoint: .topLeading,
                                    endPoint: .bottomTrailing
                                ),
                                in: Circle()
                            )
                        VStack(alignment: .leading, spacing: 2) {
                            Text(destination.title)
                                .font(.headline)
                                .foregroundStyle(Color(hex: "0C315C"))
                            Text(secondarySubtitle(destination))
                                .font(.caption)
                                .foregroundStyle(Color(hex: "6D8498"))
                                .lineLimit(2)
                        }
                        Spacer(minLength: 4)
                        Image(systemName: "chevron.right")
                            .font(.subheadline.bold())
                            .foregroundStyle(Color(hex: "6F8BA5"))
                    }
                    .frame(maxWidth: .infinity, minHeight: 62)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("xage.medication.destination.\(destination.rawValue)")
                if destination != MedicationDashboardDestination.allCases.last {
                    Divider().opacity(0.45)
                }
            }
        }
        .padding(.horizontal, 14)
        .background(MedicationDashboardCardBackground())
    }

    private func secondarySubtitle(_ destination: MedicationDashboardDestination) -> String {
        switch destination {
        case .plans:
            return visiblePlans.isEmpty ? "暂无已确认计划" : "\(visiblePlans.count) 种药物正在管理"
        case .records:
            return today?.planned_count == 0 ? "查看每日与疗程记录" : "今天已确认 \(today?.taken_count ?? 0) 次"
        case .reactions:
            return reactionCount == 0 ? destination.subtitle : "\(reactionCount) 条记录，可继续补充或修正"
        case .course:
            return courseSubtitle
        }
    }

    private var courseSubtitle: String {
        guard let localDate = today?.local_date else {
            return MedicationDashboardDestination.course.subtitle
        }
        let endingSoon = visiblePlans.filter {
            MedicationCoursePolicy.progress(plan: $0, on: localDate).endsSoon
        }.count
        return endingSoon > 0 ? "\(endingSoon) 种药物将在 7 天内结束" : "查看疗程进度与预计剩余"
    }
}

struct MedicationDashboardBottomAction: View {
    let title: String
    let icon: String
    let disabled: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 9) {
                Image(systemName: icon)
                Text(title)
            }
                .font(.title3.bold())
                .foregroundStyle(.white)
                .frame(maxWidth: .infinity, minHeight: 54)
                .background(
                    LinearGradient(
                        colors: [Color(hex: "0E72DF"), Color(hex: "25B5CA"), Color(hex: "42D1B7")],
                        startPoint: .leading,
                        endPoint: .trailing
                    ),
                    in: Capsule()
                )
                .contentShape(Capsule())
        }
        .buttonStyle(.plain)
        .disabled(disabled)
        .opacity(disabled ? 0.56 : 1)
        .padding(.horizontal, 20)
        .padding(.top, 8)
        .padding(.bottom, 4)
        .background(.ultraThinMaterial)
        .accessibilityIdentifier("xage.medication.bottomAction")
    }
}

/// 次级页面统一容器，保证返回、滚动和安全区行为一致。
struct MedicationDashboardDetailShell<Content: View>: View {
    let destination: MedicationDashboardDestination
    let onClose: () -> Void
    @ViewBuilder let content: () -> Content

    var body: some View {
        ZStack {
            LinearGradient(
                colors: [Color(hex: "EAF7FF"), Color(hex: "F8FCFF"), Color(hex: "EAFBF7")],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )
            .ignoresSafeArea()

            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    HStack(alignment: .top, spacing: 12) {
                        Button(action: onClose) {
                            Image(systemName: "chevron.left")
                                .frame(width: 44, height: 44)
                                .background(.white.opacity(0.6), in: Circle())
                                .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        .accessibilityLabel("返回用药记录")
                        .accessibilityIdentifier("xage.medication.detail.close")

                        VStack(alignment: .leading, spacing: 3) {
                            Text(destination.title)
                                .font(.title.bold())
                                .foregroundStyle(Color(hex: "0C315C"))
                            Text(destination.subtitle)
                                .font(.subheadline)
                                .foregroundStyle(Color(hex: "5D7890"))
                        }
                    }
                    content()
                }
                .padding(20)
                .padding(.bottom, 24)
            }
            .scrollDismissesKeyboard(.interactively)
            .accessibilityIdentifier("xage.medication.detail.\(destination.rawValue)")
        }
    }
}

/// 疗程与预计余量详情，只显示服务端提供的范围和估算，不推断续药资格。
struct MedicationCourseInventoryView: View {
    let plans: [TrustedMedicationPlan]
    let localDate: String?
    let confirmationMetric: (TrustedMedicationPlan) -> MedicationConfirmationMetric

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            if plans.isEmpty {
                Text("暂无可展示的已确认用药计划。")
                    .font(.subheadline)
                    .foregroundStyle(Color(hex: "6D8498"))
            } else {
                ForEach(plans.filter { $0.status != .retracted }) { plan in
                    courseCard(plan)
                }
            }
            Label(
                "预计余量只按你明确确认的服药记录计算，不代表实际库存；续配与调整请联系医生或药师。",
                systemImage: "checkmark.shield.fill"
            )
            .font(.caption)
            .foregroundStyle(Color(hex: "5D7890"))
            .fixedSize(horizontal: false, vertical: true)
        }
        .padding(16)
        .background(MedicationDashboardCardBackground())
    }

    private func courseCard(_ plan: TrustedMedicationPlan) -> some View {
        let progress = localDate.map { MedicationCoursePolicy.progress(plan: plan, on: $0) }
        let metric = confirmationMetric(plan)
        return VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 3) {
                    Text(plan.displayName)
                        .font(.headline)
                        .foregroundStyle(Color(hex: "0C315C"))
                    Text([plan.dose_text, plan.frequency].compactMap { $0 }.joined(separator: " · "))
                        .font(.caption)
                        .foregroundStyle(Color(hex: "5D7890"))
                }
                Spacer()
                Text(plan.status.title)
                    .font(.caption.bold())
                    .foregroundStyle(Color(hex: "1268BD"))
            }
            detail("疗程", MedicationDisplay.course(plan.course_start, plan.course_end))
            if let progress {
                detail(
                    "进度",
                    [
                        progress.elapsedDays.map { "已进行 \($0) 天" },
                        progress.totalDays.map { "共 \($0) 天" },
                        progress.remainingDays.map { "剩余 \($0) 天" }
                    ].compactMap { $0 }.joined(separator: " · ")
                )
                if progress.endsSoon {
                    Label("疗程将在 7 天内结束，请按原处方安排复诊或咨询。", systemImage: "calendar.badge.exclamationmark")
                        .font(.caption.bold())
                        .foregroundStyle(Color.orange)
                }
            }
            detail(
                plan.inventory.label,
                inventoryText(plan.inventory)
            )
            detail(
                "疗程已确认率",
                metric.percentage.map {
                    "\($0)%（\(metric.confirmedCount)/\(metric.plannedCount) 次）"
                } ?? metric.unavailableReason ?? "当前疗程无计划剂次"
            )
        }
        .padding(14)
        .background(.white.opacity(0.48), in: RoundedRectangle(cornerRadius: 20))
        .accessibilityElement(children: .combine)
    }

    private func inventoryText(_ inventory: MedicationInventoryEstimate) -> String {
        guard let remaining = inventory.estimated_remaining,
              let unit = inventory.inventory_unit else {
            return inventory.unavailable_reason ?? "缺少初始数量，暂不可估算"
        }
        return "\(MedicationDisplay.number(remaining)) \(unit)"
    }

    private func detail(_ label: String, _ value: String) -> some View {
        HStack(alignment: .top, spacing: 10) {
            Text(label)
                .font(.caption.bold())
                .foregroundStyle(Color(hex: "5D7890"))
                .frame(width: 80, alignment: .leading)
            Text(value.isEmpty ? "未填写" : value)
                .font(.caption)
                .foregroundStyle(Color(hex: "0C315C"))
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 0)
        }
    }
}

private struct MedicationDashboardCountCard: View {
    let title: String
    let value: Int
    let icon: String
    let color: Color
    let accessibilityID: String

    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            HStack(spacing: 7) {
                Image(systemName: icon)
                    .font(.caption.bold())
                    .foregroundStyle(color)
                    .frame(width: 28, height: 28)
                    .background(color.opacity(0.11), in: Circle())
                Text(title)
                    .font(.caption.weight(.medium))
                    .foregroundStyle(Color(hex: "5D7890"))
                    .lineLimit(1)
                    .minimumScaleFactor(0.8)
            }
            Text("\(value)次")
                .font(.title2.bold().monospacedDigit())
                .foregroundStyle(Color(hex: "0C315C"))
        }
        .frame(maxWidth: .infinity, minHeight: 86, alignment: .leading)
        .padding(.horizontal, 12)
        .background(MedicationDashboardCardBackground())
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier(accessibilityID)
    }
}

private struct MedicationDashboardTaskRow: View {
    let task: MedicationTodayTask

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: task.status == .taken ? "checkmark" : "clock.fill")
                .font(.subheadline.bold())
                .foregroundStyle(task.status == .taken ? Color(hex: "16A98F") : Color(hex: "1268BD"))
                .frame(width: 34, height: 34)
                .background(
                    (task.status == .taken ? Color(hex: "16A98F") : Color(hex: "1268BD")).opacity(0.11),
                    in: Circle()
                )
            VStack(alignment: .leading, spacing: 2) {
                Text([task.displayName, task.dose_text].compactMap { $0 }.joined(separator: " "))
                    .font(.subheadline.bold())
                    .foregroundStyle(Color(hex: "0C315C"))
                    .lineLimit(2)
                Text("\(task.scheduled_time) · \(task.status.title)")
                    .font(.caption)
                    .foregroundStyle(Color(hex: "6D8498"))
            }
            Spacer(minLength: 4)
            Text(task.status == .taken ? "已服用" : "待确认")
                .font(.caption.bold())
                .foregroundStyle(task.status == .taken ? Color(hex: "159B82") : Color(hex: "1268BD"))
            Image(systemName: "chevron.right")
                .font(.caption.bold())
                .foregroundStyle(Color(hex: "7891A8"))
        }
        .frame(maxWidth: .infinity, minHeight: 62)
        .contentShape(Rectangle())
    }
}

private struct MedicationDashboardOutlineButton: View {
    let title: String
    let icon: String
    let accessibilityID: String
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Label(title, systemImage: icon)
                .font(.subheadline.bold())
                .lineLimit(1)
                .minimumScaleFactor(0.82)
                .frame(maxWidth: .infinity, minHeight: 40)
        }
        .buttonStyle(.plain)
        .foregroundStyle(Color(hex: "547493"))
        .overlay(
            Capsule()
                .stroke(Color(hex: "62A2E8").opacity(0.7), lineWidth: 1)
        )
        .accessibilityIdentifier(accessibilityID)
    }
}

private struct MedicationDashboardLoadingHero: View {
    let minimumHeight: CGFloat

    var body: some View {
        VStack(spacing: 14) {
            ProgressView()
                .controlSize(.large)
            Text("正在读取下一次用药…")
                .font(.headline)
                .foregroundStyle(Color(hex: "496A83"))
        }
        .frame(maxWidth: .infinity, minHeight: minimumHeight)
        .background(MedicationDashboardHeroBackground())
        .accessibilityIdentifier("xage.medication.hero.loading")
    }
}

private struct MedicationDashboardGradientButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .foregroundStyle(.white)
            .background(
                LinearGradient(
                    colors: [Color(hex: "0E72DF"), Color(hex: "25B5CA"), Color(hex: "42D1B7")],
                    startPoint: .leading,
                    endPoint: .trailing
                ),
                in: Capsule()
            )
            .opacity(configuration.isPressed ? 0.78 : 1)
            .scaleEffect(configuration.isPressed ? 0.99 : 1)
    }
}

private struct MedicationDashboardCardBackground: View {
    var body: some View {
        RoundedRectangle(cornerRadius: 24, style: .continuous)
            .fill(.white.opacity(0.68))
            .overlay(
                RoundedRectangle(cornerRadius: 24, style: .continuous)
                    .stroke(.white.opacity(0.82), lineWidth: 0.8)
            )
            .shadow(color: Color(hex: "276693").opacity(0.08), radius: 12, y: 5)
    }
}

private struct MedicationDashboardHeroBackground: View {
    var body: some View {
        RoundedRectangle(cornerRadius: 28, style: .continuous)
            .fill(.white.opacity(0.54))
            .overlay(
                RoundedRectangle(cornerRadius: 28, style: .continuous)
                    .stroke(Color(hex: "70B0EF").opacity(0.7), lineWidth: 1)
            )
            .shadow(color: Color(hex: "276693").opacity(0.09), radius: 14, y: 6)
    }
}
