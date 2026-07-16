import SwiftUI
import UIKit

struct XAgeMedicationManagementView: View {
    var onClose: (() -> Void)?

    @Environment(\.dismiss) private var dismiss
    @Environment(\.scenePhase) private var scenePhase
    @ObservedObject private var authManager = AuthManager.shared
    @StateObject private var vm = MedicationViewModel()
    @State private var planEditor: MedicationPlanEditorContext?
    @State private var reminderPlan: TrustedMedicationPlan?
    @State private var showAddSources = false
    @State private var pendingAddDestination: MedicationAddDestination?
    @State private var showRecognition = false
    @State private var snoozeTask: MedicationTodayTask?
    @State private var skipTask: MedicationTodayTask?
    @State private var correctionTask: MedicationTodayTask?
    @State private var reactionEditor: MedicationReactionEditorContext?
    @State private var confirmingTakenTask: MedicationTodayTask?
    @State private var planStatusConfirmation: MedicationPlanStatusConfirmation?
    @State private var showPendingRetryExit = false
    @State private var scrollTarget: String?

    var body: some View {
        ZStack {
            XAgeMedicationLiquidBackground()
                .ignoresSafeArea()

            ScrollViewReader { proxy in
                ScrollView {
                    VStack(alignment: .leading, spacing: 16) {
                        header

                        if let errorMessage = vm.errorMessage {
                            errorCard(errorMessage)
                        }
                        if let infoMessage = vm.infoMessage {
                            infoCard(infoMessage)
                        }

                        if vm.loading && vm.today == nil {
                            XAgeMedicationLoadingCard()
                        } else {
                            todayOverview
                            if let task = vm.today?.next_task {
                                currentTaskCard(task)
                            }
                            pendingPrefillsSection
                            plansSection
                            doseRecordsSection
                                .id("medication-records")
                            confirmationInsightsSection
                            reactionsSection
                            legacyMigrationSection
                            safetyBoundary
                        }
                    }
                    .padding(.horizontal, 20)
                    .padding(.top, 12)
                    .padding(.bottom, 32)
                }
                .scrollDismissesKeyboard(.interactively)
                .scrollIndicators(.hidden)
                // Keep the established UI-test/accessibility contract while the
                // implementation behind it moves to the trusted medication loop.
                .accessibilityIdentifier("xage.medication.root")
                .onChange(of: scrollTarget) { _, target in
                    guard let target else { return }
                    withAnimation(.easeInOut(duration: 0.25)) {
                        proxy.scrollTo(target, anchor: .top)
                    }
                    scrollTarget = nil
                }
            }
        }
        .toolbar(.hidden, for: .navigationBar)
        .interactiveDismissDisabled(vm.hasPendingRetry || vm.mutating)
        .task(id: authManager.accountScope) {
            await vm.load(accountScope: authManager.accountScope)
        }
        .refreshable { await vm.reload() }
        .sheet(item: $planEditor) { context in
            XAgeMedicationPlanEditor(
                context: context,
                onSave: { draft in
                    if let plan = context.plan {
                        await vm.revisePlan(plan, draft: draft)
                    } else {
                        await vm.confirmPlan(
                            draft: draft,
                            candidate: context.candidate,
                            sourceType: context.sourceType,
                            sourceRef: context.sourceRef
                        )
                    }
                    return !vm.hasPendingRetry && vm.errorMessage == nil
                },
                onReject: context.candidate.map { candidate in
                    {
                        await vm.rejectPrefill(candidate)
                        return !vm.hasPendingRetry && vm.errorMessage == nil
                    }
                }
            )
        }
        .sheet(isPresented: $showRecognition) {
            XAgeMedicationRecognitionSheet { rawText in
                await vm.recognize(rawText: rawText)
                return !vm.hasPendingRetry && vm.errorMessage == nil
            }
        }
        .sheet(isPresented: $showAddSources, onDismiss: openPendingAddDestination) {
            MedicationAddSourceView(
                prescriptionCandidates: vm.prescriptionImportCandidates,
                legacyRecords: vm.legacyRecords,
                onPrescription: { candidate in
                    pendingAddDestination = .candidate(candidate)
                    showAddSources = false
                },
                onOCRText: {
                    pendingAddDestination = .ocrText
                    showAddSources = false
                },
                onHistory: { medication in
                    pendingAddDestination = .legacy(medication)
                    showAddSources = false
                },
                onManual: {
                    pendingAddDestination = .manual
                    showAddSources = false
                }
            )
        }
        .sheet(item: $reminderPlan) { plan in
            MedicationReminderEditorView(
                plan: plan,
                settings: vm.reminderSettings(for: plan),
                permission: vm.reminderPermission,
                onSave: { settings in
                    await vm.saveReminderSettings(settings, for: plan)
                }
            )
        }
        .sheet(item: $snoozeTask) { task in
            XAgeMedicationSnoozeSheet(
                task: task,
                defaultMinutes: vm.snoozeMinutes(for: task)
            ) { date in
                await vm.snooze(task, until: date)
                return !vm.hasPendingRetry && vm.errorMessage == nil
            }
        }
        .sheet(item: $skipTask) { task in
            XAgeMedicationSkipSheet(task: task) { reason in
                await vm.skip(task, reason: reason)
                return !vm.hasPendingRetry && vm.errorMessage == nil
            }
        }
        .sheet(item: $correctionTask) { task in
            XAgeMedicationCorrectionSheet(task: task) { status, date, reason in
                await vm.correct(task, to: status, snoozedUntil: date, reason: reason)
                return !vm.hasPendingRetry && vm.errorMessage == nil
            }
        }
        .sheet(item: $reactionEditor) { context in
            XAgeMedicationReactionEditor(
                context: context,
                plans: vm.activePlans,
                onSave: { fields in
                    if let reaction = context.reaction {
                        await vm.correctReaction(reaction, fields: fields)
                    } else {
                        await vm.createReaction(fields)
                    }
                    return !vm.hasPendingRetry && vm.errorMessage == nil
                }
            )
        }
        .alert(
            "确认已经服用？",
            isPresented: Binding(
                get: { confirmingTakenTask != nil },
                set: { if !$0 { confirmingTakenTask = nil } }
            ),
            presenting: confirmingTakenTask
        ) { task in
            Button("取消", role: .cancel) {}
            Button("确认已服用") {
                confirmingTakenTask = nil
                Task { await vm.confirmTaken(task) }
            }
        } message: { task in
            Text("将按你的明确确认记录 \(task.displayName) \(task.dose_text ?? "")。提醒时间经过本身不会产生这条记录。")
        }
        .confirmationDialog(
            planStatusConfirmation?.title ?? "更新计划状态",
            isPresented: Binding(
                get: { planStatusConfirmation != nil },
                set: { if !$0 { planStatusConfirmation = nil } }
            ),
            presenting: planStatusConfirmation
        ) { confirmation in
            Button(confirmation.confirmTitle, role: confirmation.isDestructive ? .destructive : nil) {
                planStatusConfirmation = nil
                Task {
                    await vm.updatePlanStatus(
                        confirmation.plan,
                        action: confirmation.action,
                        reason: confirmation.reason
                    )
                }
            }
            Button("取消", role: .cancel) {}
        } message: { confirmation in
            Text(confirmation.message)
        }
        .alert("仍有失败操作可以安全重试", isPresented: $showPendingRetryExit) {
            Button("留在页面", role: .cancel) {}
            Button("放弃本次重试", role: .destructive) {
                vm.discardPendingRetry()
                closePage()
            }
        } message: {
            Text("退出会放弃当前客户端保存的稳定事件；留在页面可用同一事件重试，避免重复记录。")
        }
        .onChange(of: scenePhase) { _, phase in
            guard phase == .active else { return }
            Task { await vm.refreshReminderPermission() }
        }
    }

    private var header: some View {
        HStack(spacing: 12) {
            Button(action: requestClose) {
                Image(systemName: "chevron.left")
                    .font(.body.bold())
                    .foregroundStyle(Color(hex: "1268BD"))
                    .frame(width: 44, height: 44)
                    .background(XAgeMedicationCapsuleFill())
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .disabled(vm.mutating)
            .accessibilityLabel("返回")

            VStack(alignment: .leading, spacing: 2) {
                Text("用药记录")
                    .font(.title.bold())
                    .foregroundStyle(Color(hex: "123E67"))
                Text("只使用你明确确认的计划与服药记录")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(Color(hex: "5D7890"))
            }
            .minimumScaleFactor(0.82)

            Spacer(minLength: 4)

            Button {
                showAddSources = true
            } label: {
                Image(systemName: "plus")
                    .font(.body.bold())
                    .foregroundStyle(Color(hex: "1268BD"))
                    .frame(width: 44, height: 44)
                    .background(XAgeMedicationCapsuleFill())
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .disabled(vm.mutating || vm.today == nil)
            .accessibilityLabel("新增用药方式")
            .accessibilityIdentifier("xage.medication.add")
        }
    }

    private var todayOverview: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .top, spacing: 12) {
                ZStack {
                    Circle()
                        .fill(LinearGradient(
                            colors: [Color(hex: "22D4BF"), Color(hex: "1E8BE3")],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        ))
                    Image(systemName: "pills.fill")
                        .font(.title3.bold())
                        .foregroundStyle(.white)
                }
                .frame(width: 52, height: 52)

                VStack(alignment: .leading, spacing: 4) {
                    Text("今日用药概况")
                        .font(.title3.bold())
                        .foregroundStyle(Color(hex: "123E67"))
                    Text(todaySubtitle)
                        .font(.subheadline)
                        .foregroundStyle(Color(hex: "496A83"))
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: 0)
            }

            if let today = vm.today {
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 72), spacing: 8)], spacing: 8) {
                    XAgeMedicationCount(title: "计划", value: today.planned_count)
                    XAgeMedicationCount(title: "已服", value: today.taken_count)
                    XAgeMedicationCount(title: "待确认", value: today.awaiting_confirmation_count)
                    XAgeMedicationCount(title: "可能漏服", value: today.possibly_missed_count)
                    XAgeMedicationCount(title: "跳过", value: today.skipped_count)
                    XAgeMedicationCount(title: "不适", value: today.adverse_reaction_count)
                }
            }

            Button(action: performPrimaryAction) {
                XAgeMedicationPrimaryActionLabel(
                    title: primaryActionTitle,
                    icon: primaryActionIcon
                )
            }
            .buttonStyle(.plain)
            .disabled(vm.today == nil || vm.mutating)
            .accessibilityIdentifier("xage.medication.primaryAction")
        }
        .padding(18)
        .background(XAgeMedicationGlassCard(cornerRadius: 28))
    }

    private func currentTaskCard(_ task: MedicationTodayTask) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 4) {
                    Text("当前服药任务")
                        .font(.headline)
                        .foregroundStyle(Color(hex: "123E67"))
                    Text("\(task.scheduled_time) · \(task.displayName)")
                        .font(.title3.bold())
                        .foregroundStyle(Color(hex: "123E67"))
                        .fixedSize(horizontal: false, vertical: true)
                    if let dose = task.dose_text, !dose.isEmpty {
                        Text(dose)
                            .font(.subheadline.weight(.semibold))
                            .foregroundStyle(Color(hex: "496A83"))
                    }
                }
                Spacer(minLength: 8)
                Text(task.status.title)
                    .font(.caption.bold())
                    .foregroundStyle(task.status == .possiblyMissed ? Color.orange : Color(hex: "1268BD"))
                    .padding(.horizontal, 10)
                    .padding(.vertical, 7)
                    .background(XAgeMedicationCapsuleFill())
                    .fixedSize(horizontal: false, vertical: true)
            }

            if task.status == .possiblyMissed {
                Label(
                    "提醒时间已过不等于确认漏服；这次仍等你确认，也不要自行在下一次加倍。",
                    systemImage: "clock.badge.exclamationmark"
                )
                .font(.caption)
                .foregroundStyle(Color.orange)
                .fixedSize(horizontal: false, vertical: true)
            }

            HStack(spacing: 8) {
                Button("已服用") { confirmingTakenTask = task }
                    .buttonStyle(XAgeMedicationCompactButtonStyle(prominent: true))
                Button("稍后提醒") { snoozeTask = task }
                    .buttonStyle(XAgeMedicationCompactButtonStyle())
                Button("本次跳过") { skipTask = task }
                    .buttonStyle(XAgeMedicationCompactButtonStyle())
            }
            .disabled(vm.mutating)

            Button {
                reactionEditor = .new(planID: task.plan_id, occurrenceKey: task.occurrence_key)
            } label: {
                Label("记录服药后的不适", systemImage: "heart.text.square")
                    .font(.subheadline.bold())
                    .frame(maxWidth: .infinity, minHeight: 44)
            }
            .buttonStyle(.plain)
            .foregroundStyle(Color(hex: "1268BD"))
            .background(XAgeMedicationCapsuleFill())
            .disabled(vm.mutating)
        }
        .padding(18)
        .background(XAgeMedicationGlassCard(cornerRadius: 28))
    }

    @ViewBuilder
    private var pendingPrefillsSection: some View {
        if !vm.pendingPrefills.isEmpty {
            VStack(alignment: .leading, spacing: 12) {
                sectionTitle("待确认的识别结果", icon: "checklist.checked")
                Text("这些内容只是 OCR / 处方预填，不是当前用药，也不会在确认前进入 AI。")
                    .font(.caption)
                    .foregroundStyle(Color(hex: "5D7890"))
                    .fixedSize(horizontal: false, vertical: true)
                ForEach(vm.pendingPrefills) { candidate in
                    VStack(alignment: .leading, spacing: 9) {
                        HStack {
                            Text(candidate.extracted_data["name"]?.text ?? "未识别药名")
                                .font(.headline)
                                .foregroundStyle(Color(hex: "123E67"))
                            Spacer()
                            Text("v\(candidate.version)")
                                .font(.caption.monospacedDigit())
                                .foregroundStyle(Color(hex: "6D8498"))
                        }
                        if !candidate.low_confidence_fields.isEmpty {
                            Label(
                                "低置信字段：\(candidate.low_confidence_fields.map(MedicationDisplay.fieldName).joined(separator: "、"))",
                                systemImage: "exclamationmark.triangle.fill"
                            )
                            .font(.caption.bold())
                            .foregroundStyle(Color.orange)
                            .fixedSize(horizontal: false, vertical: true)
                        }
                        Button("检查药物信息") {
                            planEditor = .candidate(candidate)
                        }
                        .buttonStyle(XAgeMedicationCompactButtonStyle(prominent: true))
                        .disabled(vm.mutating)
                    }
                    .padding(14)
                    .background(Color.white.opacity(0.42), in: RoundedRectangle(cornerRadius: 18))
                }
            }
            .padding(18)
            .background(XAgeMedicationGlassCard(cornerRadius: 28))
        }
    }

    private var plansSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            sectionTitle("当前用药计划", icon: "list.bullet.clipboard")
            if vm.plans.filter({ $0.status != .retracted }).isEmpty {
                Text("还没有经过你确认的用药计划。可从已确认处方导入、粘贴 OCR 文字后复核，或手动添加。")
                    .font(.subheadline)
                    .foregroundStyle(Color(hex: "496A83"))
                    .fixedSize(horizontal: false, vertical: true)
            } else {
                ForEach(vm.plans.filter { $0.status != .retracted }) { plan in
                    XAgeMedicationPlanCard(
                        plan: plan,
                        localDate: vm.today?.local_date,
                        confirmationMetric: vm.courseConfirmationMetric(for: plan),
                        reminderEnabled: vm.isReminderEnabled(for: plan),
                        reminderNeedsReview: vm.reminderSettingsByPlanID[plan.plan_id].map {
                            $0.planVersion != plan.version
                        } ?? false,
                        onEdit: { planEditor = .plan(plan) },
                        onReminder: { reminderPlan = plan },
                        onPauseOrResume: {
                            let action: MedicationPlanStatusRequest.Action = plan.status == .paused ? .resume : .pause
                            Task { await vm.updatePlanStatus(plan, action: action) }
                        },
                        onComplete: {
                            planStatusConfirmation = .complete(plan)
                        },
                        onRetract: {
                            planStatusConfirmation = .retract(plan)
                        }
                    )
                    .disabled(vm.mutating)
                }
            }
        }
        .padding(18)
        .background(XAgeMedicationGlassCard(cornerRadius: 28))
    }

    private var doseRecordsSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            sectionTitle("今日服药记录", icon: "clock.arrow.circlepath")
            Text("统计只依据你的明确操作；“可能漏服”仍是待确认状态。误操作可以按版本纠正。")
                .font(.caption)
                .foregroundStyle(Color(hex: "5D7890"))
                .fixedSize(horizontal: false, vertical: true)
            if vm.today?.tasks.isEmpty != false {
                Text("今天没有计划剂次。")
                    .font(.subheadline)
                    .foregroundStyle(Color(hex: "6D8498"))
            } else {
                ForEach(vm.today?.tasks ?? []) { task in
                    XAgeMedicationDoseRecordRow(
                        task: task,
                        onCorrect: { correctionTask = task }
                    )
                }
            }
        }
        .padding(18)
        .background(XAgeMedicationGlassCard(cornerRadius: 28))
    }

    private var confirmationInsightsSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            sectionTitle("已确认率", icon: "chart.bar.doc.horizontal")
            Text("只统计你明确选择“已服用”或“本次跳过”的剂次；待确认、稍后和可能漏服不会被冒充为已确认。")
                .font(.caption)
                .foregroundStyle(Color(hex: "5D7890"))
                .fixedSize(horizontal: false, vertical: true)
            HStack(spacing: 10) {
                MedicationConfirmationMetricCard(
                    title: "今日",
                    metric: vm.confirmationInsights.today
                )
                MedicationConfirmationMetricCard(
                    title: "近 7 日",
                    metric: vm.confirmationInsights.sevenDay
                )
            }
            Text("完整疗程按每项计划分别核对；服务端历史窗口不足时会明确显示不可用，不用近七日代替。")
                .font(.caption2)
                .foregroundStyle(Color(hex: "6D8498"))
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(18)
        .background(XAgeMedicationGlassCard(cornerRadius: 28))
    }

    private var reactionsSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                sectionTitle("不适与反应", icon: "waveform.path.ecg.rectangle")
                Spacer()
                if let firstPlan = vm.activePlans.first {
                    Button("记录不适") {
                        reactionEditor = .new(planID: firstPlan.plan_id, occurrenceKey: nil)
                    }
                    .font(.caption.bold())
                    .frame(minHeight: 44)
                    .disabled(vm.mutating)
                }
            }
            Text("这里只记录症状与服药时间接近，不能据此认定由药物导致。")
                .font(.caption)
                .foregroundStyle(Color(hex: "5D7890"))
                .fixedSize(horizontal: false, vertical: true)
            if vm.reactions.isEmpty {
                Text("暂无不适记录。")
                    .font(.subheadline)
                    .foregroundStyle(Color(hex: "6D8498"))
            } else {
                ForEach(vm.reactions) { reaction in
                    VStack(alignment: .leading, spacing: 8) {
                        HStack {
                            Text(reaction.symptoms)
                                .font(.headline)
                                .foregroundStyle(Color(hex: "123E67"))
                            Spacer()
                            Text(reaction.severity.title)
                                .font(.caption.bold())
                                .foregroundStyle(reaction.severity == .severe ? Color.red : Color.orange)
                        }
                        Text("发生时间：\(MedicationDisplay.dateTime(reaction.onset_at))")
                            .font(.caption)
                            .foregroundStyle(Color(hex: "5D7890"))
                        Text(reaction.user_facing_causality)
                            .font(.caption)
                            .foregroundStyle(Color(hex: "496A83"))
                            .fixedSize(horizontal: false, vertical: true)
                        if reaction.severity == .severe {
                            Label(reaction.safety_guidance, systemImage: "cross.case.fill")
                                .font(.caption.bold())
                                .foregroundStyle(Color.red)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                        HStack {
                            Button("修正") { reactionEditor = .existing(reaction) }
                            Spacer()
                            Button("撤回", role: .destructive) {
                                Task { await vm.retractReaction(reaction) }
                            }
                        }
                        .font(.caption.bold())
                        .frame(minHeight: 44)
                        .disabled(vm.mutating)
                    }
                    .padding(14)
                    .background(Color.white.opacity(0.42), in: RoundedRectangle(cornerRadius: 18))
                }
            }
        }
        .padding(18)
        .background(XAgeMedicationGlassCard(cornerRadius: 28))
    }

    @ViewBuilder
    private var legacyMigrationSection: some View {
        if !vm.legacyRecords.isEmpty {
            VStack(alignment: .leading, spacing: 10) {
                sectionTitle("待迁移的旧记录", icon: "archivebox")
                Text("以下旧记录没有主体版本、显式确认和剂次证据，因此只读展示，不是可信计划，也不会作为当前用药进入 AI。请重新核对后手动建立计划。")
                    .font(.caption)
                    .foregroundStyle(Color.orange)
                    .fixedSize(horizontal: false, vertical: true)
                ForEach(vm.legacyRecords) { medication in
                    HStack(alignment: .top) {
                        VStack(alignment: .leading, spacing: 3) {
                            Text(medication.name).font(.subheadline.bold())
                            Text([medication.dosage, medication.frequency].compactMap { $0 }.joined(separator: " · "))
                                .font(.caption)
                                .foregroundStyle(Color(hex: "5D7890"))
                        }
                        Spacer()
                        Text("只读")
                            .font(.caption2.bold())
                            .foregroundStyle(Color.orange)
                    }
                    .padding(12)
                    .background(Color.white.opacity(0.35), in: RoundedRectangle(cornerRadius: 16))
                }
            }
            .padding(18)
            .background(XAgeMedicationGlassCard(cornerRadius: 28))
        }
    }

    private var safetyBoundary: some View {
        Label(
            "小捷记录和提醒你已确认的计划，不提供自行加药、减量或停药建议。涉及处方调整请联系医生或药师。",
            systemImage: "shield.lefthalf.filled"
        )
        .font(.footnote)
        .foregroundStyle(Color(hex: "496A83"))
        .fixedSize(horizontal: false, vertical: true)
        .padding(16)
        .background(XAgeMedicationGlassCard(cornerRadius: 24))
    }

    private func errorCard(_ message: String) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Label("用药操作未完成", systemImage: "exclamationmark.triangle.fill")
                .font(.headline)
                .foregroundStyle(Color.orange)
            Text(message)
                .font(.subheadline)
                .foregroundStyle(Color(hex: "496A83"))
                .fixedSize(horizontal: false, vertical: true)
            HStack {
                if vm.hasPendingRetry {
                    Button(vm.mutating ? "重试中…" : "使用同一请求重试") {
                        Task { await vm.retryPendingMutation() }
                    }
                    .buttonStyle(XAgeMedicationCompactButtonStyle(prominent: true))
                    .disabled(vm.mutating)
                } else {
                    Button("重新加载") { Task { await vm.reload() } }
                        .buttonStyle(XAgeMedicationCompactButtonStyle(prominent: true))
                        .disabled(vm.loading)
                }
            }
        }
        .padding(16)
        .background(XAgeMedicationGlassCard(cornerRadius: 24))
        .accessibilityIdentifier("xage.medication.error")
    }

    private func infoCard(_ message: String) -> some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: "checkmark.shield.fill")
                .foregroundStyle(Color(hex: "13A98F"))
            Text(message)
                .font(.subheadline)
                .foregroundStyle(Color(hex: "496A83"))
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 0)
            Button {
                vm.infoMessage = nil
            } label: {
                Image(systemName: "xmark")
                    .frame(width: 44, height: 44)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel("关闭提示")
        }
        .padding(14)
        .background(XAgeMedicationGlassCard(cornerRadius: 22))
    }

    private func sectionTitle(_ title: String, icon: String) -> some View {
        Label(title, systemImage: icon)
            .font(.headline)
            .foregroundStyle(Color(hex: "123E67"))
    }

    private var todaySubtitle: String {
        guard let today = vm.today else { return "正在读取服务端可信状态…" }
        if let task = today.next_task {
            return "下一次：\(task.scheduled_time) · \(task.displayName) \(task.dose_text ?? "")"
        }
        return today.empty_state ?? "今天的计划剂次已经处理，可继续查看记录。"
    }

    private var primaryActionTitle: String {
        switch vm.primaryAction {
        case .addFirstMedication: return "添加第一种药物"
        case .reviewPrefill: return "检查药物信息"
        case .confirmDose: return "确认本次服药"
        case .viewMedicationRecord: return "查看用药记录"
        }
    }

    private var primaryActionIcon: String {
        switch vm.primaryAction {
        case .addFirstMedication: return "plus"
        case .reviewPrefill: return "checklist"
        case .confirmDose: return "checkmark.circle.fill"
        case .viewMedicationRecord: return "clock.arrow.circlepath"
        }
    }

    private func performPrimaryAction() {
        switch vm.primaryAction {
        case .addFirstMedication:
            showAddSources = true
        case .reviewPrefill(let candidateID):
            if let candidate = vm.pendingPrefills.first(where: { $0.candidate_id == candidateID }) {
                planEditor = .candidate(candidate)
            }
        case .confirmDose(let occurrenceKey):
            confirmingTakenTask = vm.today?.tasks.first { $0.occurrence_key == occurrenceKey }
        case .viewMedicationRecord:
            scrollTarget = "medication-records"
        }
    }

    private func openPendingAddDestination() {
        guard let destination = pendingAddDestination else { return }
        pendingAddDestination = nil
        switch destination {
        case .manual:
            planEditor = .manual()
        case .candidate(let candidate):
            planEditor = .candidate(candidate)
        case .legacy(let medication):
            planEditor = .legacy(medication)
        case .ocrText:
            showRecognition = true
        }
    }

    private func requestClose() {
        UIApplication.shared.sendAction(
            #selector(UIResponder.resignFirstResponder),
            to: nil,
            from: nil,
            for: nil
        )
        guard !vm.mutating else { return }
        if vm.hasPendingRetry {
            showPendingRetryExit = true
        } else {
            closePage()
        }
    }

    private func closePage() {
        if let onClose { onClose() } else { dismiss() }
    }
}

private enum MedicationAddDestination {
    case manual
    case candidate(MedicationPrefillCandidate)
    case legacy(Medication)
    case ocrText
}

// MARK: - Main-page cards

private struct XAgeMedicationCount: View {
    let title: String
    let value: Int

    var body: some View {
        VStack(spacing: 3) {
            Text("\(value)")
                .font(.title3.bold().monospacedDigit())
                .foregroundStyle(Color(hex: "123E67"))
            Text(title)
                .font(.caption2.weight(.semibold))
                .foregroundStyle(Color(hex: "5D7890"))
        }
        .frame(maxWidth: .infinity, minHeight: 58)
        .background(Color.white.opacity(0.38), in: RoundedRectangle(cornerRadius: 16))
        .accessibilityElement(children: .combine)
    }
}

private struct MedicationConfirmationMetricCard: View {
    let title: String
    let metric: MedicationConfirmationMetric

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(title)
                .font(.caption.bold())
                .foregroundStyle(Color(hex: "5D7890"))
            if let percentage = metric.percentage {
                Text("\(percentage)%")
                    .font(.title2.bold().monospacedDigit())
                    .foregroundStyle(Color(hex: "123E67"))
                Text("\(metric.confirmedCount) / \(metric.plannedCount) 次")
                    .font(.caption2)
                    .foregroundStyle(Color(hex: "6D8498"))
            } else if metric.isAvailable {
                Text("无计划")
                    .font(.headline)
                    .foregroundStyle(Color(hex: "123E67"))
            } else {
                Text("暂不可用")
                    .font(.headline)
                    .foregroundStyle(Color.orange)
                Text(metric.unavailableReason ?? "数据不足")
                    .font(.caption2)
                    .foregroundStyle(Color(hex: "6D8498"))
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .frame(maxWidth: .infinity, minHeight: 92, alignment: .topLeading)
        .padding(12)
        .background(Color.white.opacity(0.4), in: RoundedRectangle(cornerRadius: 16))
        .accessibilityElement(children: .combine)
    }
}

private struct XAgeMedicationPlanCard: View {
    let plan: TrustedMedicationPlan
    let localDate: String?
    let confirmationMetric: MedicationConfirmationMetric
    let reminderEnabled: Bool
    let reminderNeedsReview: Bool
    let onEdit: () -> Void
    let onReminder: () -> Void
    let onPauseOrResume: () -> Void
    let onComplete: () -> Void
    let onRetract: () -> Void
    @State private var isExpanded = false

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Button {
                withAnimation(.easeInOut(duration: 0.2)) {
                    isExpanded.toggle()
                }
            } label: {
                HStack(alignment: .top, spacing: 10) {
                    Image(systemName: plan.status == .active ? "pills.fill" : "pause.circle.fill")
                        .foregroundStyle(plan.status == .active ? Color(hex: "13A98F") : Color.orange)
                        .frame(width: 32, height: 32)
                    VStack(alignment: .leading, spacing: 3) {
                        Text(plan.displayName)
                            .font(.headline)
                            .foregroundStyle(Color(hex: "123E67"))
                            .fixedSize(horizontal: false, vertical: true)
                        Text([plan.dose_text, plan.frequency].compactMap { $0 }.joined(separator: " · "))
                            .font(.caption)
                            .foregroundStyle(Color(hex: "5D7890"))
                    }
                    Spacer(minLength: 4)
                    Text(plan.status.title)
                        .font(.caption2.bold())
                        .foregroundStyle(Color(hex: "1268BD"))
                    Image(systemName: isExpanded ? "chevron.up" : "chevron.down")
                        .font(.caption.bold())
                        .foregroundStyle(Color(hex: "1268BD"))
                        .frame(minWidth: 24, minHeight: 32)
                        .accessibilityHidden(true)
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("xage.medication.plan.\(plan.plan_id)")
            .accessibilityLabel("\(plan.displayName)，\(plan.status.title)")
            .accessibilityValue(isExpanded ? "已展开" : "已折叠")

            if isExpanded {
                planDetails
                    .padding(.top, 10)
            }
        }
        .tint(Color(hex: "1268BD"))
        .padding(14)
        .background(Color.white.opacity(0.42), in: RoundedRectangle(cornerRadius: 18))
    }

    private var planDetails: some View {
        VStack(alignment: .leading, spacing: 9) {
            detail("规格 / 单次剂量", [plan.strength, plan.dose_text].compactMap { $0 }.joined(separator: " · "))
            detail("频次 / 时间", [plan.frequency, plan.schedule_times.joined(separator: "、")].compactMap { $0 }.filter { !$0.isEmpty }.joined(separator: " · "))
            detail("进餐关系", plan.meal_relation.title)
            detail("疗程", MedicationDisplay.course(plan.course_start, plan.course_end))
            courseProgressRows
            detail("处方 / 来源", [plan.prescriber, plan.source_type.title].compactMap { $0 }.joined(separator: " · "))
            if let instructions = plan.instructions, !instructions.isEmpty {
                detail("服用要求", instructions)
            }
            inventoryRow
            Label(
                reminderNeedsReview
                    ? "计划版本已变化，旧提醒已停用，请重新确认。"
                    : reminderEnabled
                        ? "本机提醒已主动开启；通知不等于服药确认。"
                        : "提醒默认关闭；服务端不会自动开启通知。",
                systemImage: reminderEnabled ? "bell.badge.fill" : "bell.slash.fill"
            )
            .font(.caption)
            .foregroundStyle(reminderNeedsReview ? Color.orange : Color(hex: "5D7890"))
            .fixedSize(horizontal: false, vertical: true)

            Button(action: onReminder) {
                Label(reminderEnabled ? "管理提醒" : "设置提醒", systemImage: "bell")
                    .font(.caption.bold())
                    .frame(maxWidth: .infinity, minHeight: 44)
            }
            .buttonStyle(XAgeMedicationCompactButtonStyle())
            .accessibilityIdentifier("xage.medication.reminder.open.\(plan.plan_id)")

            HStack(spacing: 8) {
                Button("编辑") { onEdit() }
                    .buttonStyle(XAgeMedicationCompactButtonStyle())
                    .accessibilityIdentifier("xage.medication.plan.edit.\(plan.plan_id)")
                Button(plan.status == .paused ? "恢复" : "暂停") { onPauseOrResume() }
                    .buttonStyle(XAgeMedicationCompactButtonStyle())
                    .accessibilityIdentifier("xage.medication.plan.status.\(plan.plan_id)")
                Menu {
                    Button("结束疗程", action: onComplete)
                    Button("撤回计划", role: .destructive, action: onRetract)
                } label: {
                    Label("更多", systemImage: "ellipsis")
                        .font(.caption.bold())
                        .frame(minWidth: 62, minHeight: 44)
                }
                .accessibilityIdentifier("xage.medication.plan.more.\(plan.plan_id)")
            }
        }
    }

    private var inventoryRow: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(plan.inventory.label)
                .font(.caption.bold())
                .foregroundStyle(Color(hex: "5D7890"))
            if let remaining = plan.inventory.estimated_remaining,
               let unit = plan.inventory.inventory_unit {
                Text("\(MedicationDisplay.number(remaining)) \(unit)")
                    .font(.headline)
                    .foregroundStyle(Color(hex: "123E67"))
                Text("只根据每个剂次最新的“已服用”确认估算，不代表准确库存。")
                    .font(.caption2)
                    .foregroundStyle(Color(hex: "6D8498"))
                if let dose = plan.dose_quantity, remaining < dose {
                    Label(
                        "预计余量不足一次用量，请核对实际库存并联系医生或药师；估算不会阻止记录真实服用。",
                        systemImage: "exclamationmark.triangle.fill"
                    )
                    .font(.caption2.bold())
                    .foregroundStyle(Color.orange)
                    .fixedSize(horizontal: false, vertical: true)
                }
            } else {
                Text(plan.inventory.unavailable_reason ?? "缺少初始数量，暂时无法估算。")
                    .font(.caption)
                    .foregroundStyle(Color(hex: "6D8498"))
            }
        }
        .padding(10)
        .background(Color.white.opacity(0.38), in: RoundedRectangle(cornerRadius: 14))
    }

    @ViewBuilder
    private var courseProgressRows: some View {
        if let localDate {
            let progress = MedicationCoursePolicy.progress(plan: plan, on: localDate)
            if let elapsed = progress.elapsedDays {
                detail(
                    "疗程进度",
                    [
                        "已进行 \(elapsed) 天",
                        progress.totalDays.map { "共 \($0) 天" },
                        progress.remainingDays.map { "剩余 \($0) 天" }
                    ].compactMap { $0 }.joined(separator: " · ")
                )
                if progress.endsSoon {
                    Label("疗程将在 7 天内结束，请按原处方安排复诊或咨询。", systemImage: "calendar.badge.exclamationmark")
                        .font(.caption2.bold())
                        .foregroundStyle(Color.orange)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
        if confirmationMetric.isAvailable {
            detail(
                "疗程已确认率",
                confirmationMetric.percentage.map {
                    "\($0)%（\(confirmationMetric.confirmedCount)/\(confirmationMetric.plannedCount) 次）"
                } ?? "当前疗程无计划剂次"
            )
        } else {
            detail("疗程已确认率", confirmationMetric.unavailableReason ?? "暂不可用")
        }
        detail("续配资格", "服务端暂未提供；请查看原处方或联系开方机构。")
    }

    private func detail(_ label: String, _ value: String) -> some View {
        HStack(alignment: .top, spacing: 8) {
            Text(label)
                .font(.caption.bold())
                .foregroundStyle(Color(hex: "5D7890"))
                .frame(width: 88, alignment: .leading)
            Text(value.isEmpty ? "未填写" : value)
                .font(.caption)
                .foregroundStyle(Color(hex: "123E67"))
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 0)
        }
    }
}

private struct XAgeMedicationDoseRecordRow: View {
    let task: MedicationTodayTask
    let onCorrect: () -> Void

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            VStack(alignment: .leading, spacing: 3) {
                Text("\(task.scheduled_time) · \(task.displayName)")
                    .font(.subheadline.bold())
                    .foregroundStyle(Color(hex: "123E67"))
                Text(task.status.title)
                    .font(.caption)
                    .foregroundStyle(task.status == .possiblyMissed ? Color.orange : Color(hex: "5D7890"))
                if let confirmed = task.confirmed_at {
                    Text("确认时间：\(MedicationDisplay.dateTime(confirmed))")
                        .font(.caption2)
                        .foregroundStyle(Color(hex: "6D8498"))
                }
            }
            Spacer(minLength: 8)
            if task.latest_event_id != nil {
                Button("纠正", action: onCorrect)
                    .font(.caption.bold())
                    .frame(minWidth: 54, minHeight: 44)
            }
        }
        .padding(12)
        .background(Color.white.opacity(0.38), in: RoundedRectangle(cornerRadius: 16))
    }
}

// MARK: - Editor contexts

private struct MedicationPlanEditorContext: Identifiable {
    let id: String
    let candidate: MedicationPrefillCandidate?
    let plan: TrustedMedicationPlan?
    let initialDraft: MedicationPlanDraft
    let sourceType: MedicationSourceType
    let sourceRef: String?

    static func manual() -> Self {
        Self(
            id: "manual-\(UUID().uuidString)",
            candidate: nil,
            plan: nil,
            initialDraft: MedicationPlanDraft(),
            sourceType: .manual,
            sourceRef: nil
        )
    }

    static func candidate(_ candidate: MedicationPrefillCandidate) -> Self {
        Self(
            id: "candidate-\(candidate.candidate_id)-v\(candidate.version)",
            candidate: candidate,
            plan: nil,
            initialDraft: MedicationPlanDraft(candidate: candidate),
            sourceType: candidate.source_type,
            sourceRef: candidate.source_ref
        )
    }

    static func plan(_ plan: TrustedMedicationPlan) -> Self {
        Self(
            id: "plan-\(plan.plan_id)-v\(plan.version)",
            candidate: nil,
            plan: plan,
            initialDraft: MedicationPlanDraft(plan: plan),
            sourceType: plan.source_type,
            sourceRef: plan.source_ref
        )
    }

    static func legacy(_ medication: Medication) -> Self {
        Self(
            id: "legacy-\(medication.id)-\(UUID().uuidString)",
            candidate: nil,
            plan: nil,
            initialDraft: MedicationPlanDraft(legacy: medication),
            sourceType: .history,
            sourceRef: "legacy-medication:\(medication.id)"
        )
    }
}

private struct MedicationReactionEditorContext: Identifiable {
    let id: String
    let reaction: MedicationReaction?
    let preferredPlanID: Int?
    let occurrenceKey: String?

    static func new(planID: Int, occurrenceKey: String?) -> Self {
        Self(
            id: "new-reaction-\(UUID().uuidString)",
            reaction: nil,
            preferredPlanID: planID,
            occurrenceKey: occurrenceKey
        )
    }

    static func existing(_ reaction: MedicationReaction) -> Self {
        Self(
            id: "reaction-\(reaction.reaction_key)-v\(reaction.reaction_version)",
            reaction: reaction,
            preferredPlanID: reaction.plan_id,
            occurrenceKey: reaction.related_occurrence_key
        )
    }
}

private struct MedicationPlanStatusConfirmation: Identifiable {
    let id = UUID()
    let plan: TrustedMedicationPlan
    let action: MedicationPlanStatusRequest.Action
    let title: String
    let confirmTitle: String
    let message: String
    let reason: String
    let isDestructive: Bool

    static func complete(_ plan: TrustedMedicationPlan) -> Self {
        Self(
            plan: plan,
            action: .complete,
            title: "结束这项疗程？",
            confirmTitle: "确认结束",
            message: "结束后不再生成新的今日任务，已有确认记录仍会保留。",
            reason: "user_completed_course",
            isDestructive: false
        )
    }

    static func retract(_ plan: TrustedMedicationPlan) -> Self {
        Self(
            plan: plan,
            action: .retract,
            title: "撤回这项计划？",
            confirmTitle: "确认撤回",
            message: "撤回会停止该计划；历史确认和修订轨迹仍会保留。",
            reason: "user_retracted_plan",
            isDestructive: true
        )
    }
}

// MARK: - Plan editor

private struct XAgeMedicationPlanEditor: View {
    let context: MedicationPlanEditorContext
    let onSave: (MedicationPlanDraft) async -> Bool
    let onReject: (() async -> Bool)?

    @Environment(\.dismiss) private var dismiss
    @State private var draft: MedicationPlanDraft
    @State private var initialDraft: MedicationPlanDraft
    @State private var scheduleText: String
    @State private var initialScheduleText: String
    @State private var saving = false
    @State private var showDiscard = false
    @State private var showReject = false
    @FocusState private var focusedField: Field?

    private enum Field: Hashable {
        case genericName, brandName, strength, doseText, doseQuantity, frequency
        case schedule, instructions, courseStart, courseEnd, prescriber, initialQuantity, inventoryUnit
    }

    init(
        context: MedicationPlanEditorContext,
        onSave: @escaping (MedicationPlanDraft) async -> Bool,
        onReject: (() async -> Bool)?
    ) {
        self.context = context
        self.onSave = onSave
        self.onReject = onReject
        let value = context.initialDraft
        _draft = State(initialValue: value)
        _initialDraft = State(initialValue: value)
        let schedule = value.scheduleTimes.joined(separator: "、")
        _scheduleText = State(initialValue: schedule)
        _initialScheduleText = State(initialValue: schedule)
    }

    var body: some View {
        ZStack {
            XAgeMedicationLiquidBackground()
                .ignoresSafeArea()
                .onTapGesture { focusedField = nil }
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    editorHeader
                    trustNotice
                    medicineFields
                    scheduleFields
                    courseAndInventoryFields
                    saveButton
                    if onReject != nil {
                        Button("拒绝这条识别候选", role: .destructive) {
                            focusedField = nil
                            showReject = true
                        }
                        .font(.subheadline.bold())
                        .frame(maxWidth: .infinity, minHeight: 48)
                        .disabled(saving)
                    }
                }
                .padding(20)
                .xAgeDismissKeyboardOnDownwardPull {
                    focusedField = nil
                }
            }
            .scrollDismissesKeyboard(.interactively)
        }
        .interactiveDismissDisabled(hasChanges || saving)
        .presentationDragIndicator(hasChanges || saving ? .hidden : .visible)
        .xAgeKeyboardDoneAccessory(
            isPresented: focusedField != nil,
            accessibilityIdentifier: "xage.medication.plan.keyboard.done"
        ) {
            focusedField = nil
        }
        .alert("放弃未保存的用药信息？", isPresented: $showDiscard) {
            Button("继续编辑", role: .cancel) {}
            Button("放弃修改", role: .destructive) { dismiss() }
        } message: {
            Text("当前字段尚未确认保存，放弃后不会创建或修改用药计划。")
        }
        .alert("拒绝识别候选？", isPresented: $showReject) {
            Button("继续检查", role: .cancel) {}
            Button("确认拒绝", role: .destructive) {
                saving = true
                Task {
                    let succeeded = await onReject?() ?? false
                    await MainActor.run {
                        saving = false
                        if succeeded { dismiss() }
                    }
                }
            }
        } message: {
            Text("拒绝不会创建计划，OCR 预填也不会进入 AI。")
        }
    }

    private var editorHeader: some View {
        HStack(alignment: .top) {
            VStack(alignment: .leading, spacing: 3) {
                Text(context.plan != nil ? "修正用药计划" : context.candidate != nil ? "检查药物信息" : "手动添加用药")
                    .font(.title.bold())
                    .foregroundStyle(Color(hex: "123E67"))
                Text(context.plan == nil ? "确认后才会建立可信计划" : "修改将产生新的计划版本")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(Color(hex: "5D7890"))
            }
            Spacer(minLength: 8)
            Button(action: requestClose) {
                Image(systemName: "xmark")
                    .font(.body.bold())
                    .frame(width: 44, height: 44)
                    .background(XAgeMedicationCapsuleFill())
            }
            .buttonStyle(.plain)
            .disabled(saving)
            .accessibilityLabel("关闭用药编辑")
        }
    }

    private var trustNotice: some View {
        VStack(alignment: .leading, spacing: 7) {
            Label(
                context.candidate == nil
                    ? "这是你的显式确认，不是 AI 自动建计划。"
                    : "橙色字段置信度较低，需要重点核对。",
                systemImage: "checkmark.shield.fill"
            )
            .font(.subheadline.bold())
            .foregroundStyle(Color(hex: "1268BD"))
            Text("提醒默认关闭并由本机管理；保存计划不会自动请求通知权限，也不会自动安排服务端通知。")
                .font(.caption)
                .foregroundStyle(Color(hex: "5D7890"))
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(14)
        .background(XAgeMedicationGlassCard(cornerRadius: 22))
    }

    private var medicineFields: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("药品与剂量")
                .font(.headline)
                .foregroundStyle(Color(hex: "123E67"))
            textField("药品通用名（必填）", text: $draft.genericName, field: .genericName, confidenceKey: "name")
            textField("商品名", text: $draft.brandName, field: .brandName, confidenceKey: "brand_name")
            textField("规格", text: $draft.strength, field: .strength, confidenceKey: "strength")
            textField("单次剂量", text: $draft.doseText, field: .doseText, confidenceKey: "dosage")
            quickFillRow(title: "常用剂量", phrases: MedicationQuickFill.dosePhrases) { phrase in
                draft.doseText = MedicationQuickFill.appending(phrase, to: draft.doseText)
            }
            textField("每次消耗数量（与余量同单位）", text: $draft.doseQuantity, field: .doseQuantity, confidenceKey: "dose_quantity", keyboard: .decimalPad)
            textField("每日频次", text: $draft.frequency, field: .frequency, confidenceKey: "frequency")
            quickFillRow(title: "常用频次", phrases: MedicationQuickFill.frequencyPhrases) { phrase in
                draft.frequency = MedicationQuickFill.appending(phrase, to: draft.frequency)
            }
            Picker("进餐关系", selection: $draft.mealRelation) {
                ForEach(MedicationMealRelation.allCases, id: \.self) { relation in
                    Text(relation.title).tag(relation)
                }
            }
            .pickerStyle(.segmented)
            Toggle("长期用药", isOn: $draft.isLongTerm)
                .tint(Color(hex: "20CDB1"))
        }
        .padding(16)
        .background(XAgeMedicationGlassCard(cornerRadius: 24))
    }

    private var scheduleFields: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("频次、提醒与说明")
                .font(.headline)
                .foregroundStyle(Color(hex: "123E67"))
            textField(
                "服用时间（如 08:00、20:00）",
                text: $scheduleText,
                field: .schedule,
                confidenceKey: "schedule_times"
            )
            textField(
                "服用要求 / 说明",
                text: $draft.instructions,
                field: .instructions,
                confidenceKey: "instructions",
                axis: .vertical
            )
            quickFillRow(title: "常用说明", phrases: MedicationQuickFill.instructionPhrases) { phrase in
                draft.instructions = MedicationQuickFill.appending(phrase, to: draft.instructions)
            }
            textField("处方医生或资料来源", text: $draft.prescriber, field: .prescriber, confidenceKey: "prescriber")
        }
        .padding(16)
        .background(XAgeMedicationGlassCard(cornerRadius: 24))
    }

    private var courseAndInventoryFields: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("疗程与预计余量")
                .font(.headline)
                .foregroundStyle(Color(hex: "123E67"))
            textField("开始日期 YYYY-MM-DD", text: $draft.courseStart, field: .courseStart, confidenceKey: "course_start")
            textField("结束日期 YYYY-MM-DD", text: $draft.courseEnd, field: .courseEnd, confidenceKey: "course_end")
            textField("初始数量", text: $draft.initialQuantity, field: .initialQuantity, confidenceKey: "initial_quantity", keyboard: .decimalPad)
            textField("余量单位（如 片）", text: $draft.inventoryUnit, field: .inventoryUnit, confidenceKey: "inventory_unit")
            Text("预计余量只由服务端基于你确认的“已服用”记录计算；计划提醒不会自动扣减。")
                .font(.caption)
                .foregroundStyle(Color(hex: "5D7890"))
                .fixedSize(horizontal: false, vertical: true)
            Text("填写初始数量时，每次消耗数量使用同一个余量单位；初始数量不足一次用量会阻止保存。")
                .font(.caption)
                .foregroundStyle(Color(hex: "5D7890"))
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(16)
        .background(XAgeMedicationGlassCard(cornerRadius: 24))
    }

    private var saveButton: some View {
        Button {
            focusedField = nil
            draft.scheduleTimes = MedicationReminderPolicy.normalizedTimes(scheduleText)
            saving = true
            Task {
                let succeeded = await onSave(draft)
                await MainActor.run {
                    saving = false
                    if succeeded { dismiss() }
                }
            }
        } label: {
            XAgeMedicationPrimaryActionLabel(
                title: saving ? "保存中…" : context.plan == nil ? "确认并创建计划" : "确认计划修改",
                icon: "checkmark"
            )
        }
        .buttonStyle(.plain)
        .disabled(draftValidationIssue != nil || saving)
        .opacity(draftValidationIssue == nil ? 1 : 0.5)
        .overlay(alignment: .topLeading) {
            if let issue = draftValidationIssue {
                Text(issue)
                    .font(.caption)
                    .foregroundStyle(Color.orange)
                    .fixedSize(horizontal: false, vertical: true)
                    .offset(y: -30)
            }
        }
        .padding(.top, draftValidationIssue == nil ? 0 : 30)
    }

    private func textField(
        _ title: String,
        text: Binding<String>,
        field: Field,
        confidenceKey: String,
        keyboard: UIKeyboardType = .default,
        axis: Axis = .horizontal
    ) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack {
                Text(title)
                    .font(.caption.bold())
                    .foregroundStyle(Color(hex: "5D7890"))
                if isLowConfidence(confidenceKey) {
                    Text("低置信，重点核对")
                        .font(.caption2.bold())
                        .foregroundStyle(Color.orange)
                }
            }
            TextField(title, text: text, axis: axis)
                .focused($focusedField, equals: field)
                .keyboardType(keyboard)
                .lineLimit(axis == .vertical ? 2...5 : 1...1)
                .padding(.horizontal, 13)
                .padding(.vertical, 11)
                .background(
                    isLowConfidence(confidenceKey) ? Color.orange.opacity(0.12) : Color.white.opacity(0.54),
                    in: RoundedRectangle(cornerRadius: 14)
                )
                .overlay {
                    RoundedRectangle(cornerRadius: 14)
                        .stroke(isLowConfidence(confidenceKey) ? Color.orange : Color.white.opacity(0.75), lineWidth: 1)
                }
        }
    }

    private func quickFillRow(
        title: String,
        phrases: [String],
        action: @escaping (String) -> Void
    ) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            Text("\(title)（只追加，不覆盖已填内容）")
                .font(.caption2)
                .foregroundStyle(Color(hex: "6D8498"))
            ScrollView(.horizontal) {
                HStack(spacing: 8) {
                    ForEach(phrases, id: \.self) { phrase in
                        Button(phrase) { action(phrase) }
                            .font(.caption.bold())
                            .frame(minHeight: 36)
                            .padding(.horizontal, 11)
                            .background(Color.white.opacity(0.58), in: Capsule())
                            .buttonStyle(.plain)
                    }
                }
            }
            .scrollIndicators(.hidden)
        }
    }

    private var hasChanges: Bool {
        draft != initialDraft || scheduleText != initialScheduleText
    }

    private var draftValidationIssue: String? {
        var candidate = draft
        candidate.scheduleTimes = MedicationReminderPolicy.normalizedTimes(scheduleText)
        return candidate.validationIssue
    }

    private func isLowConfidence(_ field: String) -> Bool {
        context.candidate?.low_confidence_fields.contains(field) == true
    }

    private func requestClose() {
        focusedField = nil
        guard !saving else { return }
        if hasChanges { showDiscard = true } else { dismiss() }
    }
}

// MARK: - OCR text intake

private struct XAgeMedicationRecognitionSheet: View {
    let onRecognize: (String) async -> Bool

    @Environment(\.dismiss) private var dismiss
    @State private var rawText = ""
    @State private var submitting = false
    @State private var showDiscard = false
    @FocusState private var focused: Bool

    var body: some View {
        ZStack {
            XAgeMedicationLiquidBackground()
                .ignoresSafeArea()
                .onTapGesture { focused = false }
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    HStack(alignment: .top) {
                        VStack(alignment: .leading, spacing: 3) {
                            Text("识别药品文字")
                                .font(.title.bold())
                                .foregroundStyle(Color(hex: "123E67"))
                            Text("客户端只发送 OCR 文字，不把图片冒充已确认计划")
                                .font(.caption)
                                .foregroundStyle(Color(hex: "5D7890"))
                        }
                        Spacer()
                        Button(action: requestClose) {
                            Image(systemName: "xmark")
                                .frame(width: 44, height: 44)
                                .background(XAgeMedicationCapsuleFill())
                        }
                        .buttonStyle(.plain)
                        .disabled(submitting)
                    }
                    VStack(alignment: .leading, spacing: 8) {
                        Label("粘贴相机或相册 OCR 得到的文字", systemImage: "text.viewfinder")
                            .font(.headline)
                        TextEditor(text: $rawText)
                            .focused($focused)
                            .frame(minHeight: 180)
                            .padding(10)
                            .scrollContentBackground(.hidden)
                            .background(Color.white.opacity(0.55), in: RoundedRectangle(cornerRadius: 16))
                        Text("服务器只生成未确认预填；药名、剂量、频次等低置信字段会单独标出。必须再次确认才创建计划。")
                            .font(.caption)
                            .foregroundStyle(Color(hex: "5D7890"))
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    .padding(16)
                    .background(XAgeMedicationGlassCard(cornerRadius: 24))
                    Button {
                        focused = false
                        submitting = true
                        Task {
                            let succeeded = await onRecognize(rawText)
                            await MainActor.run {
                                submitting = false
                                if succeeded { dismiss() }
                            }
                        }
                    } label: {
                        XAgeMedicationPrimaryActionLabel(
                            title: submitting ? "识别中…" : "生成待确认预填",
                            icon: "text.viewfinder"
                        )
                    }
                    .buttonStyle(.plain)
                    .disabled(rawText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || submitting)
                }
                .padding(20)
                .xAgeDismissKeyboardOnDownwardPull {
                    focused = false
                }
            }
            .scrollDismissesKeyboard(.interactively)
        }
        .interactiveDismissDisabled(!rawText.isEmpty || submitting)
        .presentationDragIndicator(rawText.isEmpty && !submitting ? .visible : .hidden)
        .xAgeKeyboardDoneAccessory(
            isPresented: focused,
            accessibilityIdentifier: "xage.medication.recognition.keyboard.done"
        ) {
            focused = false
        }
        .alert("放弃未提交的 OCR 文字？", isPresented: $showDiscard) {
            Button("继续编辑", role: .cancel) {}
            Button("放弃", role: .destructive) { dismiss() }
        }
    }

    private func requestClose() {
        focused = false
        guard !submitting else { return }
        if rawText.isEmpty { dismiss() } else { showDiscard = true }
    }
}

// MARK: - Dose action sheets

private struct XAgeMedicationSnoozeSheet: View {
    let task: MedicationTodayTask
    let defaultMinutes: Int
    let onSave: (Date) async -> Bool
    @Environment(\.dismiss) private var dismiss
    @State private var date: Date
    @State private var saving = false

    init(
        task: MedicationTodayTask,
        defaultMinutes: Int,
        onSave: @escaping (Date) async -> Bool
    ) {
        self.task = task
        self.defaultMinutes = defaultMinutes
        self.onSave = onSave
        _date = State(initialValue: Date().addingTimeInterval(TimeInterval(defaultMinutes * 60)))
    }

    var body: some View {
        XAgeMedicationSheetContainer(
            title: "稍后提醒",
            subtitle: "\(task.displayName) · \(task.scheduled_time)",
            closeDisabled: saving,
            onClose: { dismiss() }
        ) {
            DatePicker("新的提醒时间", selection: $date, in: Date()..., displayedComponents: [.date, .hourAndMinute])
                .datePickerStyle(.graphical)
                .padding(14)
                .background(XAgeMedicationGlassCard(cornerRadius: 22))
            Text("稍后提醒是你的明确选择；如通知权限关闭，请到“系统设置 → 小捷 → 通知”恢复权限。")
                .font(.caption)
                .foregroundStyle(Color(hex: "5D7890"))
                .fixedSize(horizontal: false, vertical: true)
            Button {
                saving = true
                Task {
                    let succeeded = await onSave(date)
                    await MainActor.run { saving = false; if succeeded { dismiss() } }
                }
            } label: {
                XAgeMedicationPrimaryActionLabel(title: saving ? "保存中…" : "确认稍后提醒", icon: "clock.badge.checkmark")
            }
            .buttonStyle(.plain)
            .disabled(date <= Date() || saving)
        }
        .interactiveDismissDisabled(saving)
    }
}

private struct XAgeMedicationSkipSheet: View {
    let task: MedicationTodayTask
    let onSave: (String?) async -> Bool
    @Environment(\.dismiss) private var dismiss
    @State private var reason = ""
    @State private var saving = false
    @State private var showDiscard = false
    @FocusState private var focused: Bool

    var body: some View {
        XAgeMedicationSheetContainer(
            title: "本次跳过",
            subtitle: "系统只记录你的选择，不评价是否正确。",
            closeDisabled: saving,
            onClose: requestClose,
            onKeyboardDismiss: { focused = false }
        ) {
            TextField("原因（可选）", text: $reason, axis: .vertical)
                .focused($focused)
                .lineLimit(2...5)
                .padding(14)
                .background(Color.white.opacity(0.55), in: RoundedRectangle(cornerRadius: 16))
            Button {
                focused = false
                saving = true
                Task {
                    let succeeded = await onSave(reason.trimmingCharacters(in: .whitespacesAndNewlines).nilIfEmpty)
                    await MainActor.run { saving = false; if succeeded { dismiss() } }
                }
            } label: {
                XAgeMedicationPrimaryActionLabel(title: saving ? "保存中…" : "确认本次跳过", icon: "forward.end.fill")
            }
            .buttonStyle(.plain)
            .disabled(saving)
        }
        .interactiveDismissDisabled(!reason.isEmpty || saving)
        .xAgeKeyboardDoneAccessory(
            isPresented: focused,
            accessibilityIdentifier: "xage.medication.skip.keyboard.done"
        ) {
            focused = false
        }
        .alert("放弃未保存的原因？", isPresented: $showDiscard) {
            Button("继续编辑", role: .cancel) {}
            Button("放弃", role: .destructive) { dismiss() }
        }
    }

    private func requestClose() {
        focused = false
        guard !saving else { return }
        if reason.isEmpty { dismiss() } else { showDiscard = true }
    }
}

private struct XAgeMedicationCorrectionSheet: View {
    let task: MedicationTodayTask
    let onSave: (MedicationDoseActionRequest.CorrectedStatus, Date?, String?) async -> Bool
    @Environment(\.dismiss) private var dismiss
    @State private var status: MedicationDoseActionRequest.CorrectedStatus = .pending
    @State private var snoozeDate = Date().addingTimeInterval(15 * 60)
    @State private var reason = ""
    @State private var saving = false
    @State private var showDiscard = false
    @FocusState private var focused: Bool

    var body: some View {
        XAgeMedicationSheetContainer(
            title: "纠正服药记录",
            subtitle: "纠正会保留上一版本，不会覆盖审计轨迹。",
            closeDisabled: saving,
            onClose: requestClose,
            onKeyboardDismiss: { focused = false }
        ) {
            Picker("正确状态", selection: $status) {
                Text("已服用").tag(MedicationDoseActionRequest.CorrectedStatus.taken)
                Text("稍后提醒").tag(MedicationDoseActionRequest.CorrectedStatus.snoozed)
                Text("本次跳过").tag(MedicationDoseActionRequest.CorrectedStatus.skipped)
                Text("恢复待确认").tag(MedicationDoseActionRequest.CorrectedStatus.pending)
            }
            .pickerStyle(.menu)
            .padding(14)
            .background(XAgeMedicationGlassCard(cornerRadius: 22))
            if status == .snoozed {
                DatePicker("新的提醒时间", selection: $snoozeDate, in: Date()...)
                    .datePickerStyle(.compact)
                    .padding(14)
                    .background(XAgeMedicationGlassCard(cornerRadius: 22))
            }
            TextField("纠正原因（可选）", text: $reason, axis: .vertical)
                .focused($focused)
                .lineLimit(2...5)
                .padding(14)
                .background(Color.white.opacity(0.55), in: RoundedRectangle(cornerRadius: 16))
            Button {
                focused = false
                saving = true
                Task {
                    let succeeded = await onSave(
                        status,
                        status == .snoozed ? snoozeDate : nil,
                        reason.trimmingCharacters(in: .whitespacesAndNewlines).nilIfEmpty
                    )
                    await MainActor.run { saving = false; if succeeded { dismiss() } }
                }
            } label: {
                XAgeMedicationPrimaryActionLabel(title: saving ? "保存中…" : "确认纠正", icon: "arrow.uturn.backward.circle.fill")
            }
            .buttonStyle(.plain)
            .disabled(saving)
        }
        .interactiveDismissDisabled(hasChanges || saving)
        .xAgeKeyboardDoneAccessory(
            isPresented: focused,
            accessibilityIdentifier: "xage.medication.correction.keyboard.done"
        ) {
            focused = false
        }
        .alert("放弃未保存的纠正？", isPresented: $showDiscard) {
            Button("继续编辑", role: .cancel) {}
            Button("放弃", role: .destructive) { dismiss() }
        }
    }

    private var hasChanges: Bool { status != .pending || !reason.isEmpty }
    private func requestClose() {
        focused = false
        guard !saving else { return }
        if hasChanges { showDiscard = true } else { dismiss() }
    }
}

// MARK: - Reaction editor

private struct XAgeMedicationReactionEditor: View {
    let context: MedicationReactionEditorContext
    let plans: [TrustedMedicationPlan]
    let onSave: (MedicationReactionFields) async -> Bool

    @Environment(\.dismiss) private var dismiss
    @State private var planID: Int
    @State private var symptoms: String
    @State private var onset: Date
    @State private var severity: MedicationReactionSeverity
    @State private var duration: String
    @State private var notes: String
    @State private var initialSnapshot: Snapshot
    @State private var saving = false
    @State private var showDiscard = false
    @FocusState private var focused: Field?

    private enum Field: Hashable { case symptoms, duration, notes }
    private struct Snapshot: Equatable {
        let planID: Int
        let symptoms: String
        let onset: Date
        let severity: MedicationReactionSeverity
        let duration: String
        let notes: String
    }

    init(
        context: MedicationReactionEditorContext,
        plans: [TrustedMedicationPlan],
        onSave: @escaping (MedicationReactionFields) async -> Bool
    ) {
        self.context = context
        self.plans = plans
        self.onSave = onSave
        let reaction = context.reaction
        let selectedPlan = context.preferredPlanID ?? plans.first?.plan_id ?? 0
        let initialOnset = reaction.flatMap { MedicationViewModel.isoDate($0.onset_at) } ?? Date()
        let snapshot = Snapshot(
            planID: selectedPlan,
            symptoms: reaction?.symptoms ?? "",
            onset: initialOnset,
            severity: reaction?.severity ?? .mild,
            duration: reaction?.duration_minutes.map(String.init) ?? "",
            notes: reaction?.notes ?? ""
        )
        _planID = State(initialValue: snapshot.planID)
        _symptoms = State(initialValue: snapshot.symptoms)
        _onset = State(initialValue: snapshot.onset)
        _severity = State(initialValue: snapshot.severity)
        _duration = State(initialValue: snapshot.duration)
        _notes = State(initialValue: snapshot.notes)
        _initialSnapshot = State(initialValue: snapshot)
    }

    var body: some View {
        XAgeMedicationSheetContainer(
            title: context.reaction == nil ? "记录不适" : "修正不适记录",
            subtitle: "只记录时间关联，不做药物因果判断。",
            closeDisabled: saving,
            onClose: requestClose,
            onKeyboardDismiss: { focused = nil }
        ) {
            VStack(alignment: .leading, spacing: 12) {
                Picker("相关用药计划", selection: $planID) {
                    ForEach(plans) { plan in
                        Text(plan.displayName).tag(plan.plan_id)
                    }
                }
                .pickerStyle(.menu)
                TextField("不适症状", text: $symptoms, axis: .vertical)
                    .focused($focused, equals: .symptoms)
                    .lineLimit(2...5)
                DatePicker("出现时间", selection: $onset)
                Picker("严重程度", selection: $severity) {
                    ForEach(MedicationReactionSeverity.allCases, id: \.self) { item in
                        Text(item.title).tag(item)
                    }
                }
                .pickerStyle(.segmented)
                TextField("持续分钟数（可选）", text: $duration)
                    .keyboardType(.numberPad)
                    .focused($focused, equals: .duration)
                TextField("备注（可选）", text: $notes, axis: .vertical)
                    .focused($focused, equals: .notes)
                    .lineLimit(2...5)
            }
            .textFieldStyle(.roundedBorder)
            .padding(16)
            .background(XAgeMedicationGlassCard(cornerRadius: 24))
            if severity == .severe {
                Label(
                    "症状较重，请尽快联系医生、药师；如出现呼吸困难、意识异常或快速加重，请立即联系急救服务。",
                    systemImage: "cross.case.fill"
                )
                .font(.caption.bold())
                .foregroundStyle(Color.red)
                .fixedSize(horizontal: false, vertical: true)
                .padding(14)
                .background(XAgeMedicationGlassCard(cornerRadius: 22))
            }
            Button {
                focused = nil
                saving = true
                let fields = MedicationReactionFields(
                    plan_id: planID,
                    symptoms: symptoms,
                    onset_at: MedicationViewModel.isoString(onset),
                    severity: severity,
                    duration_minutes: Int(duration),
                    related_occurrence_key: context.occurrenceKey,
                    notes: notes.trimmingCharacters(in: .whitespacesAndNewlines).nilIfEmpty
                )
                Task {
                    let succeeded = await onSave(fields)
                    await MainActor.run { saving = false; if succeeded { dismiss() } }
                }
            } label: {
                XAgeMedicationPrimaryActionLabel(title: saving ? "保存中…" : "确认记录", icon: "heart.text.square.fill")
            }
            .buttonStyle(.plain)
            .disabled(symptoms.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || planID <= 0 || saving)
        }
        .interactiveDismissDisabled(hasChanges || saving)
        .xAgeKeyboardDoneAccessory(
            isPresented: focused != nil,
            accessibilityIdentifier: "xage.medication.reaction.keyboard.done"
        ) {
            focused = nil
        }
        .alert("放弃未保存的不适记录？", isPresented: $showDiscard) {
            Button("继续编辑", role: .cancel) {}
            Button("放弃", role: .destructive) { dismiss() }
        }
    }

    private var snapshot: Snapshot {
        Snapshot(
            planID: planID,
            symptoms: symptoms,
            onset: onset,
            severity: severity,
            duration: duration,
            notes: notes
        )
    }
    private var hasChanges: Bool { snapshot != initialSnapshot }
    private func requestClose() {
        focused = nil
        guard !saving else { return }
        if hasChanges { showDiscard = true } else { dismiss() }
    }
}

// MARK: - Shared medication presentation

private struct XAgeMedicationSheetContainer<Content: View>: View {
    let title: String
    let subtitle: String
    let closeDisabled: Bool
    let onClose: () -> Void
    let onKeyboardDismiss: () -> Void
    let content: Content

    init(
        title: String,
        subtitle: String,
        closeDisabled: Bool,
        onClose: @escaping () -> Void,
        onKeyboardDismiss: @escaping () -> Void = {},
        @ViewBuilder content: () -> Content
    ) {
        self.title = title
        self.subtitle = subtitle
        self.closeDisabled = closeDisabled
        self.onClose = onClose
        self.onKeyboardDismiss = onKeyboardDismiss
        self.content = content()
    }

    var body: some View {
        ZStack {
            XAgeMedicationLiquidBackground().ignoresSafeArea()
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    HStack(alignment: .top) {
                        VStack(alignment: .leading, spacing: 3) {
                            Text(title)
                                .font(.title.bold())
                                .foregroundStyle(Color(hex: "123E67"))
                            Text(subtitle)
                                .font(.caption)
                                .foregroundStyle(Color(hex: "5D7890"))
                                .fixedSize(horizontal: false, vertical: true)
                        }
                        Spacer()
                        Button(action: onClose) {
                            Image(systemName: "xmark")
                                .frame(width: 44, height: 44)
                                .background(XAgeMedicationCapsuleFill())
                        }
                        .buttonStyle(.plain)
                        .disabled(closeDisabled)
                    }
                    content
                }
                .padding(20)
                .xAgeDismissKeyboardOnDownwardPull {
                    onKeyboardDismiss()
                }
            }
            .scrollDismissesKeyboard(.interactively)
        }
    }
}

private struct XAgeMedicationCompactButtonStyle: ButtonStyle {
    var prominent = false

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.caption.bold())
            .foregroundStyle(prominent ? Color.white : Color(hex: "1268BD"))
            .frame(maxWidth: .infinity, minHeight: 44)
            .padding(.horizontal, 6)
            .background(
                prominent
                    ? AnyShapeStyle(LinearGradient(
                        colors: [Color(hex: "22D4BF"), Color(hex: "1F8EEA")],
                        startPoint: .leading,
                        endPoint: .trailing
                    ))
                    : AnyShapeStyle(Color.white.opacity(0.58)),
                in: Capsule()
            )
            .overlay(Capsule().stroke(Color.white.opacity(0.74), lineWidth: 1))
            .opacity(configuration.isPressed ? 0.72 : 1)
    }
}

private struct XAgeMedicationPrimaryActionLabel: View {
    let title: String
    let icon: String

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: icon)
                .font(.body.bold())
            Text(title)
                .font(.headline)
                .multilineTextAlignment(.center)
        }
        .foregroundStyle(.white)
        .frame(maxWidth: .infinity, minHeight: 56)
        .padding(.horizontal, 12)
        .background(
            LinearGradient(
                colors: [Color(hex: "22D4BF"), Color(hex: "1F8EEA")],
                startPoint: .leading,
                endPoint: .trailing
            ),
            in: Capsule()
        )
        .shadow(color: Color(hex: "20CDB1").opacity(0.22), radius: 14, y: 8)
    }
}

private struct XAgeMedicationLoadingCard: View {
    var body: some View {
        HStack(spacing: 12) {
            ProgressView().tint(Color(hex: "20CDB1"))
            Text("正在读取可信用药计划与今日任务…")
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(Color(hex: "496A83"))
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(18)
        .background(XAgeMedicationGlassCard(cornerRadius: 26))
    }
}

private struct XAgeMedicationGlassCard: View {
    var cornerRadius: CGFloat
    var body: some View {
        RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
            .fill(.white.opacity(0.58))
            .overlay {
                RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                    .stroke(.white.opacity(0.76), lineWidth: 1)
            }
            .shadow(color: Color(hex: "78BCE8").opacity(0.12), radius: 20, y: 9)
    }
}

private struct XAgeMedicationCapsuleFill: View {
    var body: some View {
        Capsule()
            .fill(.white.opacity(0.62))
            .overlay(Capsule().stroke(.white.opacity(0.72), lineWidth: 1))
            .shadow(color: Color(hex: "78BCE8").opacity(0.10), radius: 9, y: 4)
    }
}

private struct XAgeMedicationLiquidBackground: View {
    var body: some View {
        LinearGradient(
            colors: [Color(hex: "D9F5FF"), Color(hex: "EAF9FF"), Color(hex: "F8FCFF")],
            startPoint: .topLeading,
            endPoint: .bottomTrailing
        )
    }
}

private enum MedicationDisplay {
    static func fieldName(_ field: String) -> String {
        switch field {
        case "name": return "药名"
        case "brand_name": return "商品名"
        case "strength": return "规格"
        case "dosage", "dose_text": return "剂量"
        case "dose_quantity": return "每次消耗数量"
        case "frequency": return "频次"
        case "schedule_times": return "服用时间"
        case "instructions": return "服用说明"
        case "course_start": return "开始日期"
        case "course_end": return "结束日期"
        case "prescriber": return "处方医生"
        default: return field
        }
    }

    static func parseSchedule(_ raw: String) -> [String] {
        raw.components(separatedBy: CharacterSet(charactersIn: "、,，;； \n\t"))
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
            .reduce(into: [String]()) { result, value in
                if !result.contains(value) { result.append(value) }
            }
            .sorted()
    }

    static func course(_ start: String?, _ end: String?) -> String {
        switch (start, end) {
        case let (start?, end?): return "\(start) 至 \(end)"
        case let (start?, nil): return "\(start) 起"
        case let (nil, end?): return "截至 \(end)"
        default: return "未设置结束日期"
        }
    }

    static func dateTime(_ raw: String) -> String {
        guard let date = MedicationViewModel.isoDate(raw) else { return raw }
        return date.formatted(date: .abbreviated, time: .shortened)
    }

    static func number(_ value: Double) -> String {
        value.rounded() == value ? String(Int(value)) : String(format: "%.1f", value)
    }
}

private extension String {
    var nilIfEmpty: String? { isEmpty ? nil : self }
}
