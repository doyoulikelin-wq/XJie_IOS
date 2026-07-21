import SwiftUI

/// Trusted health profile. The historical name is retained only so every old
/// entry point converges on this page instead of maintaining a second editor.
struct PatientHistoryView: View {
    private enum ProfileForm: String, Identifiable {
        case basic
        case longTermHealth
        case safety

        var id: String { rawValue }
        var category: HealthProfileCategory {
            switch self {
            case .basic: return .basic
            case .longTermHealth: return .longTermHealth
            case .safety: return .safety
            }
        }
    }

    private enum Confirmation: Identifiable {
        case candidate(HealthProfileCandidate, HealthProfileCandidateAction)
        case saveSafety
        case delete(HealthProfileFact)
        case goalStatus(HealthProfileGoal, HealthProfileGoalAction)
        case discardEditor(closePage: Bool)

        var id: String {
            switch self {
            case .candidate(let candidate, let action): return "candidate-\(candidate.id)-\(action.rawValue)"
            case .saveSafety: return "save-safety"
            case .delete(let fact): return "delete-\(fact.id)"
            case .goalStatus(let goal, let action): return "goal-\(goal.id)-\(action.rawValue)"
            case .discardEditor(let close): return "discard-\(close)"
            }
        }
    }

    @Environment(\.dismiss) private var dismiss
    @EnvironmentObject private var authManager: AuthManager
    @StateObject private var vm = PatientHistoryViewModel()
    @State private var confirmation: Confirmation?
    @State private var activeForm: ProfileForm?
    @FocusState private var editorFocused: Bool

    var onClose: (() -> Void)?

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(spacing: 14) {
                    statusMessages
                    if let profile = vm.profile {
                        profileHero
                            .id("health-profile-overview")
                        profileStats(profile)
                        pendingCandidates(profile)
                        profileModuleList(profile)
                        usageNotice
                    } else if vm.loading {
                        ProgressView("正在读取可信画像…")
                            .frame(maxWidth: .infinity, minHeight: 220)
                            .accessibilityIdentifier("healthProfile.loading")
                    } else {
                        unavailableCard
                    }
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 12)
                .xAgeDismissKeyboardOnDownwardPull(
                    verificationIdentifier: "healthProfile.pullDismiss.ready"
                ) {
                    editorFocused = false
                }
            }
            .background(XAgeLiquidBackground().ignoresSafeArea())
            .scrollDismissesKeyboard(.interactively)
            .navigationTitle("健康画像")
            .navigationBarTitleDisplayMode(.inline)
            .navigationBarBackButtonHidden(true)
            .toolbar(.hidden, for: .tabBar)
            .toolbar {
                ToolbarItem(placement: .navigationBarLeading) {
                    Button(action: attemptClose) {
                        Label("返回", systemImage: "chevron.left")
                    }
                    .accessibilityIdentifier("healthProfile.close")
                }
                ToolbarItemGroup(placement: .keyboard) {
                    Spacer()
                    Button("完成") { editorFocused = false }
                }
            }
            .task(id: authManager.accountScope) {
                editorFocused = false
                await vm.load(accountScope: authManager.accountScope)
            }
            .refreshable {
                guard !vm.hasUnsavedEditorChanges, !vm.hasPendingRetry else { return }
                await vm.load(accountScope: authManager.accountScope)
            }
            .onDisappear { editorFocused = false }
            .confirmationDialog(
                confirmationTitle,
                isPresented: Binding(
                    get: { confirmation != nil },
                    set: { if !$0 { confirmation = nil } }
                ),
                titleVisibility: .visible
            ) {
                confirmationActions {
                    withAnimation {
                        proxy.scrollTo("health-profile-overview", anchor: .top)
                    }
                }
            } message: {
                Text(confirmationMessage)
            }
            .sheet(
                item: Binding(
                    get: { vm.historyTarget },
                    set: { if $0 == nil { vm.closeHistory() } }
                )
            ) { target in
                revisionHistoryPage(target)
                    .presentationDetents([.medium, .large])
                    .presentationDragIndicator(.visible)
            }
            .sheet(item: $activeForm) { form in
                profileFormSheet(form)
                    .interactiveDismissDisabled(vm.hasUnsavedEditorChanges || vm.mutating)
            }
            .accessibilityIdentifier("healthProfile.root")
        }
    }

    private var profileHero: some View {
        HStack(spacing: 16) {
            ZStack {
                Circle()
                    .fill(LinearGradient(
                        colors: [Color(hex: "2489DA"), Color(hex: "43D6BD")],
                        startPoint: .topLeading,
                        endPoint: .bottomTrailing
                    ))
                Circle().stroke(.white.opacity(0.5), lineWidth: 1).padding(8)
                Image(systemName: "person.crop.circle.badge.checkmark")
                    .font(.system(size: 31, weight: .medium))
                    .foregroundStyle(.white)
            }
            .frame(width: 70, height: 70)

            VStack(alignment: .leading, spacing: 5) {
                Text("健康画像")
                    .font(.system(size: 30, weight: .bold))
                    .foregroundStyle(Color(hex: "123E67"))
                Text("持续更新的个人健康模型")
                    .font(.system(size: 15, weight: .medium))
                    .foregroundStyle(Color(hex: "6C8194"))
            }
            Spacer()
        }
        .accessibilityIdentifier("healthProfile.overview")
    }

    private func profileStats(_ profile: HealthProfileTrustResponse) -> some View {
        HStack(spacing: 10) {
            profileStatCard(
                title: "画像完整度",
                value: "\(profile.overview.completeness_percent)%",
                icon: "chart.donut",
                accent: Color(hex: "20B6C7")
            )
            profileStatCard(
                title: "待确认更新",
                value: "\(profile.overview.pending_update_count) 项",
                icon: "doc.text.fill",
                accent: profile.overview.pending_update_count > 0 ? Color(hex: "EF7548") : Color(hex: "20B6C7")
            )
            profileStatCard(
                title: "数据来源",
                value: "\(profile.overview.independent_source_count) 个",
                icon: "square.3.layers.3d",
                accent: Color(hex: "2789D8")
            )
        }
    }

    private func profileStatCard(title: String, value: String, icon: String, accent: Color) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Label(title, systemImage: icon)
                .font(.system(size: 11, weight: .bold))
                .foregroundStyle(Color(hex: "68829A"))
                .lineLimit(1)
                .minimumScaleFactor(0.75)
            Text(value)
                .font(.system(size: 22, weight: .bold))
                .foregroundStyle(Color(hex: "123E67"))
                .lineLimit(1)
            Capsule().fill(accent.opacity(0.82)).frame(height: 4)
        }
        .frame(maxWidth: .infinity, minHeight: 104, alignment: .leading)
        .padding(12)
        .background(XAgeGlassCardBackground(cornerRadius: 22))
    }

    private func profileModuleList(_ profile: HealthProfileTrustResponse) -> some View {
        VStack(spacing: 0) {
            profileModuleButton(
                icon: "person.fill",
                title: "基础资料",
                subtitle: "身高、体重与基础信息",
                status: moduleStatus(profile, category: .basic),
                identifier: "healthProfile.module.basic"
            ) { activeForm = .basic }
            moduleDivider
            profileModuleButton(
                icon: "tag.fill",
                title: "长期健康标签",
                subtitle: "慢病、家族史和长期关注",
                status: moduleStatus(profile, category: .longTermHealth),
                identifier: "healthProfile.module.longTermHealth"
            ) { activeForm = .longTermHealth }
            moduleDivider
            profileModuleButton(
                icon: "exclamationmark.shield.fill",
                title: "安全信息",
                subtitle: "过敏、禁忌和重要限制",
                status: moduleStatus(profile, category: .safety),
                statusColor: missingCount(profile, category: .safety) > 0 ? Color(hex: "EF8B35") : Color(hex: "20B69F"),
                identifier: "healthProfile.module.safety"
            ) { activeForm = .safety }
            moduleDivider
            NavigationLink {
                XAgeMedicationManagementView()
            } label: {
                profileModuleLabel(
                    icon: "pills.fill",
                    title: "长期用药",
                    subtitle: "当前长期服用的药物",
                    status: vm.medicationSummaryLoading ? "同步中" : "\(vm.longTermMedications.count) 种",
                    statusColor: Color(hex: "2789D8")
                )
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("healthProfile.medication.open")
            moduleDivider
            NavigationLink {
                HealthPlanView()
            } label: {
                profileModuleLabel(
                    icon: "target",
                    title: "健康目标与计划",
                    subtitle: "目标、任务与指标管理",
                    status: "\(profile.goals.count + profile.management_plans.count) 项",
                    statusColor: Color(hex: "2789D8")
                )
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("healthProfile.managementPlan.open")
        }
        .padding(.horizontal, 14)
        .background(XAgeGlassCardBackground(cornerRadius: 26))
        .accessibilityIdentifier("healthProfile.modules")
    }

    private func profileModuleButton(
        icon: String,
        title: String,
        subtitle: String,
        status: String,
        statusColor: Color = Color(hex: "2789D8"),
        identifier: String,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            profileModuleLabel(
                icon: icon,
                title: title,
                subtitle: subtitle,
                status: status,
                statusColor: statusColor
            )
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier(identifier)
    }

    private func profileModuleLabel(
        icon: String,
        title: String,
        subtitle: String,
        status: String,
        statusColor: Color
    ) -> some View {
        HStack(spacing: 13) {
            Image(systemName: icon)
                .font(.system(size: 21, weight: .bold))
                .foregroundStyle(.white)
                .frame(width: 48, height: 48)
                .background(Circle().fill(LinearGradient(
                    colors: [Color(hex: "2AB9C5"), Color(hex: "54D6BE")],
                    startPoint: .topLeading,
                    endPoint: .bottomTrailing
                )))
            VStack(alignment: .leading, spacing: 4) {
                Text(title)
                    .font(.system(size: 16, weight: .bold))
                    .foregroundStyle(Color(hex: "123E67"))
                Text(subtitle)
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(Color(hex: "72889C"))
                    .lineLimit(1)
            }
            Spacer(minLength: 6)
            Text(status)
                .font(.system(size: 13, weight: .bold))
                .foregroundStyle(statusColor)
                .lineLimit(1)
            Image(systemName: "chevron.right")
                .font(.system(size: 14, weight: .bold))
                .foregroundStyle(Color(hex: "91A7B9"))
        }
        .frame(minHeight: 74)
        .contentShape(Rectangle())
    }

    private var moduleDivider: some View {
        Divider().overlay(Color(hex: "DCE9F1")).padding(.leading, 61)
    }

    private func moduleStatus(_ profile: HealthProfileTrustResponse, category: HealthProfileCategory) -> String {
        let facts = profile.facts.filter { $0.typedCategory == category }.count
        if missingCount(profile, category: category) > 0 { return "待完善" }
        return facts == 0 ? "未填写" : "\(facts) 项"
    }

    private func missingCount(_ profile: HealthProfileTrustResponse, category: HealthProfileCategory) -> Int {
        profile.overview.missing_required_fact_keys
            .compactMap(HealthProfileFieldCatalog.definition(for:))
            .filter { $0.category == category }
            .count
    }

    private func profileFormSheet(_ form: ProfileForm) -> some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    Text(form.category == .safety
                         ? "安全信息必须由你本人确认，系统不会从 AI 候选自动写入。"
                         : "选择项目后填写或更新，保存结果会同步到可信健康画像。")
                        .font(.system(size: 13))
                        .foregroundStyle(Color(hex: "6C8194"))
                        .fixedSize(horizontal: false, vertical: true)

                    ForEach(HealthProfileFieldCatalog.definitions(for: form.category)) { definition in
                        let fact = vm.profile?.facts.first { $0.fact_key == definition.key }
                        Button {
                            editorFocused = false
                            vm.beginEditing(definition)
                        } label: {
                            HStack(spacing: 12) {
                                VStack(alignment: .leading, spacing: 4) {
                                    Text(definition.title)
                                        .font(.system(size: 15, weight: .bold))
                                        .foregroundStyle(Color(hex: "173F64"))
                                    Text(fact.map { HealthProfileDisplayFormatter.value($0.value_data) } ?? "待填写")
                                        .font(.system(size: 12))
                                        .foregroundStyle(Color(hex: "72889C"))
                                        .lineLimit(2)
                                }
                                Spacer()
                                Image(systemName: "square.and.pencil")
                                    .foregroundStyle(Color(hex: "2789D8"))
                            }
                            .padding(14)
                            .background(XAgeGlassCardBackground(cornerRadius: 16))
                        }
                        .buttonStyle(.plain)
                        .disabled(vm.mutating || vm.hasPendingRetry)
                        .accessibilityIdentifier("healthProfile.edit.\(definition.key)")

                        if let editor = vm.editor, editor.definition.key == definition.key {
                            editorCard(editor)
                                .padding(14)
                                .background(XAgeGlassCardBackground(cornerRadius: 16))
                        }
                    }
                }
                .padding(16)
            }
            .accessibilityIdentifier("healthProfile.form.scroll")
            .background(XAgeLiquidBackground().ignoresSafeArea())
            .scrollDismissesKeyboard(.interactively)
            .navigationTitle(form.category.title)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("完成") {
                        guard !vm.hasUnsavedEditorChanges else { return }
                        vm.cancelEditing()
                        activeForm = nil
                    }
                    .disabled(vm.hasUnsavedEditorChanges || vm.mutating)
                    .accessibilityIdentifier("healthProfile.form.close")
                }
            }
            .confirmationDialog(
                confirmationTitle,
                isPresented: Binding(
                    get: { confirmation != nil },
                    set: { if !$0 { confirmation = nil } }
                ),
                titleVisibility: .visible
            ) {
                confirmationActions(onMutationCompleted: {})
            } message: {
                Text(confirmationMessage)
            }
        }
    }

    @ViewBuilder
    private var statusMessages: some View {
        if let error = vm.errorMessage {
            messageCard(error, icon: "exclamationmark.triangle.fill", color: .appWarning) {
                vm.errorMessage = nil
            }
        }
        if vm.hasPendingRetry {
            VStack(alignment: .leading, spacing: 10) {
                Label("修改结果尚未确认", systemImage: "arrow.clockwise.circle.fill")
                    .font(.headline)
                    .foregroundColor(.appWarning)
                Text("请使用同一幂等请求重试，避免重复写入。")
                    .font(.caption)
                    .foregroundColor(.appMuted)
                Button(vm.mutating ? "正在重试…" : "重试上次修改") {
                    Task { await vm.retryPendingMutation() }
                }
                .buttonStyle(.borderedProminent)
                .disabled(vm.mutating)
                .accessibilityIdentifier("healthProfile.retry")
            }
            .cardStyle()
        }
        if let info = vm.infoMessage {
            messageCard(info, icon: "checkmark.seal.fill", color: .appSuccess) {
                vm.infoMessage = nil
            }
        }
    }

    private func overview(
        _ profile: HealthProfileTrustResponse,
        proxy: ScrollViewProxy
    ) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 4) {
                    Text("持续更新的个人健康模型")
                        .font(.headline)
                        .accessibilityIdentifier("healthProfile.overview")
                    Text("完整度只表示资料是否齐全，不代表健康好坏。")
                        .font(.caption)
                        .foregroundColor(.appMuted)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: 12)
                Image(systemName: "person.crop.circle.badge.checkmark")
                    .font(.title2)
                    .foregroundColor(.appPrimary)
            }
            HStack(spacing: 8) {
                overviewTile("画像完整度", "\(profile.overview.completeness_percent)%")
                overviewTile("待确认更新", "\(profile.overview.pending_update_count) 项")
                overviewTile("独立来源", "\(profile.overview.independent_source_count) 个")
            }
            ProgressView(value: Double(profile.overview.completeness_percent), total: 100)
                .tint(.appPrimary)
            Text(profile.overview.primary_action?.statusText ?? "服务端暂未返回可执行的画像状态")
                .font(.subheadline.bold())
                .foregroundColor(profile.overview.primary_action?.kind == "review_updates" ? .appWarning : .appPrimary)
            Button(profile.overview.primary_action?.title ?? "画像状态暂不可用") {
                performPrimaryAction(profile, proxy: proxy)
            }
            .buttonStyle(.borderedProminent)
            .frame(maxWidth: .infinity)
            .disabled(
                vm.mutating
                    || vm.hasPendingRetry
                    || profile.overview.primary_action?.isSupported != true
            )
            .accessibilityIdentifier("healthProfile.primaryAction")
        }
        .cardStyle()
    }

    private func overviewTile(_ title: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title)
                .font(.caption2)
                .foregroundColor(.appMuted)
                .lineLimit(2)
            Text(value)
                .font(.headline.bold())
                .foregroundColor(.appText)
                .minimumScaleFactor(0.75)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(9)
        .background(Color.appPrimary.opacity(0.07))
        .clipShape(RoundedRectangle(cornerRadius: 10))
    }

    @ViewBuilder
    private func pendingCandidates(_ profile: HealthProfileTrustResponse) -> some View {
        if !profile.candidates.isEmpty {
            VStack(alignment: .leading, spacing: 12) {
                Label("候选更新", systemImage: "doc.badge.clock")
                    .font(.headline)
                    .foregroundColor(.appPrimary)
                    .accessibilityIdentifier("healthProfile.candidates")
                Text("这些内容只来自已确认报告的候选分析，目前不是画像事实，也不会因为上传或识别完成而自动加入。")
                    .font(.caption)
                    .foregroundColor(.appMuted)
                    .fixedSize(horizontal: false, vertical: true)
                ForEach(profile.candidates) { candidate in
                    candidateCard(candidate)
                }
            }
            .cardStyle()
            .id("health-profile-candidates")
        }
    }

    private func candidateCard(_ candidate: HealthProfileCandidate) -> some View {
        let canAccept = candidate.isReviewable
        let canReject = candidate.canReview(.reject)
        return VStack(alignment: .leading, spacing: 9) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 3) {
                    Text(HealthProfileFieldCatalog.label(for: candidate.fact_key))
                        .font(.subheadline.bold())
                    Text(candidate.review_status == "conflict" ? "与现有事实冲突 · 需要确认" : "报告候选 · 尚未确认")
                        .font(.caption2.bold())
                        .foregroundColor(.appWarning)
                }
                Spacer()
                Text("v\(candidate.version)")
                    .font(.caption2.monospacedDigit())
                    .foregroundColor(.appMuted)
            }
            Text(HealthProfileDisplayFormatter.value(candidate.proposed_value))
                .font(.subheadline)
                .foregroundColor(.appText)
                .fixedSize(horizontal: false, vertical: true)
            provenance(candidate.sources, updatedAt: candidate.updated_at, version: candidate.version)
            if candidate.typedCategory == .goal || candidate.typedCategory == .safety || candidate.is_safety_critical {
                Text(candidate.typedCategory == .goal
                     ? "健康目标只能由你主动创建；可以忽略此候选，但不能接受为目标。"
                     : "安全信息不能从候选直接加入；可以忽略此候选，确认内容请手动填写。")
                    .font(.caption)
                    .foregroundColor(.appMuted)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if canAccept || canReject {
                HStack(spacing: 10) {
                    if canReject {
                        Button("暂不加入", role: .destructive) {
                            confirmation = .candidate(candidate, .reject)
                        }
                        .buttonStyle(.bordered)
                        .accessibilityIdentifier("healthProfile.candidate.\(candidate.id).reject")
                    }
                    if canAccept {
                        Button("确认加入") {
                            confirmation = .candidate(candidate, .accept)
                        }
                        .buttonStyle(.borderedProminent)
                        .accessibilityIdentifier("healthProfile.candidate.\(candidate.id).accept")
                    }
                }
                .disabled(vm.mutating || vm.hasPendingRetry)
            } else {
                Text("服务端返回了不受支持的候选状态，已禁止操作。")
                    .font(.caption)
                    .foregroundColor(.appWarning)
            }
        }
        .padding(12)
        .background(Color.appBackground)
        .clipShape(RoundedRectangle(cornerRadius: 12))
    }

    @ViewBuilder
    private func missingInformation(
        _ profile: HealthProfileTrustResponse,
        proxy: ScrollViewProxy
    ) -> some View {
        let missing = profile.overview.missing_required_fact_keys
            .compactMap(HealthProfileFieldCatalog.definition(for:))
            .filter { $0.category != .goal }
        if !missing.isEmpty || vm.editor != nil {
            VStack(alignment: .leading, spacing: 12) {
                Label("完善画像资料", systemImage: "square.and.pencil")
                    .font(.headline)
                    .accessibilityIdentifier("healthProfile.missing")
                if !missing.isEmpty {
                    Text("缺失项目必须由你选择填写；安全信息不会由 AI 自动写入。")
                        .font(.caption)
                        .foregroundColor(.appMuted)
                    ForEach(missing) { definition in
                        Button {
                            editorFocused = false
                            vm.beginEditing(definition)
                            Task { @MainActor in
                                await Task.yield()
                                withAnimation {
                                    proxy.scrollTo("health-profile-editor", anchor: .center)
                                }
                            }
                        } label: {
                            HStack {
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(definition.title).font(.subheadline.bold())
                                    Text(definition.category.title).font(.caption2).foregroundColor(.appMuted)
                                }
                                Spacer()
                                Text("完善").font(.caption.bold()).foregroundColor(.appPrimary)
                                Image(systemName: "chevron.right").font(.caption).foregroundColor(.appMuted)
                            }
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        .disabled(vm.mutating || vm.hasPendingRetry)
                        .accessibilityIdentifier("healthProfile.edit.\(definition.key)")
                    }
                }
                if let editor = vm.editor {
                    editorCard(editor)
                        .id("health-profile-editor")
                }
            }
            .cardStyle()
            .id("health-profile-missing")
        }
    }

    private func editorCard(_ editor: HealthProfileEditorDraft) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Divider()
            HStack {
                Text("编辑：\(editor.definition.title)")
                    .font(.subheadline.bold())
                Spacer()
                Text(editor.definition.category.title)
                    .font(.caption2)
                    .foregroundColor(editor.definition.isSafetyCritical ? .appWarning : .appMuted)
            }
            Picker("回答状态", selection: Binding(
                get: { editor.responseState },
                set: vm.updateEditorState
            )) {
                ForEach(HealthProfileResponseState.allCases, id: \.self) { state in
                    Text(state.title).tag(state)
                }
            }
            .pickerStyle(.menu)
            .accessibilityIdentifier("healthProfile.editor.state")
            if editor.responseState == .value {
                TextEditor(text: Binding(
                    get: { editor.value },
                    set: vm.updateEditorValue
                ))
                .frame(minHeight: 96, maxHeight: 180)
                .padding(8)
                .background(Color.appBackground)
                .overlay(RoundedRectangle(cornerRadius: 10).stroke(Color.appStroke))
                .focused($editorFocused)
                .accessibilityLabel(editor.definition.placeholder)
                .accessibilityIdentifier("healthProfile.editor.value")
            }
            if editor.definition.isSafetyCritical {
                Label("保存时会再次确认；修改记录和版本由服务器保留。", systemImage: "exclamationmark.shield.fill")
                    .font(.caption)
                    .foregroundColor(.appWarning)
            }
            HStack {
                Button("取消") {
                    editorFocused = false
                    confirmation = editor.isDirty ? .discardEditor(closePage: false) : nil
                    if !editor.isDirty { vm.cancelEditing() }
                }
                .buttonStyle(.bordered)
                Spacer()
                Button(vm.mutating ? "保存中…" : "保存修改") {
                    editorFocused = false
                    if editor.definition.isSafetyCritical {
                        confirmation = .saveSafety
                    } else {
                        Task { await vm.saveEditor(safetyConfirmed: false) }
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(!editor.isDirty || vm.mutating || vm.hasPendingRetry)
                .accessibilityIdentifier("healthProfile.editor.save")
            }
        }
    }

    private func confirmedFacts(_ profile: HealthProfileTrustResponse) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Label("已确认画像事实", systemImage: "checkmark.seal.fill")
                .font(.headline)
                .accessibilityIdentifier("healthProfile.facts")
            if profile.facts.isEmpty {
                Text("暂无已确认画像事实。报告识别结果不会在你确认前出现在这里。")
                    .font(.caption)
                    .foregroundColor(.appMuted)
            }
            ForEach(
                [HealthProfileCategory.basic, .longTermHealth, .safety],
                id: \.self
            ) { category in
                let facts = profile.facts.filter { $0.typedCategory == category }
                if !facts.isEmpty || category == .basic {
                    categoryFacts(category, facts: facts, allFacts: profile.facts)
                }
            }
        }
        .cardStyle()
        .id("health-profile-facts")
    }

    private func categoryFacts(
        _ category: HealthProfileCategory,
        facts: [HealthProfileFact],
        allFacts: [HealthProfileFact]
    ) -> some View {
        VStack(alignment: .leading, spacing: 9) {
            Divider()
            Text(category.title)
                .font(.subheadline.bold())
                .foregroundColor(category == .safety ? .appWarning : .appPrimary)
            ForEach(facts) { fact in
                factCard(fact)
            }
            if category == .basic {
                derivedBMICard(HealthProfileDerivedMetrics.bodyMassIndex(from: allFacts))
            }
        }
    }

    private func factCard(_ fact: HealthProfileFact) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(HealthProfileFieldCatalog.label(for: fact.fact_key))
                        .font(.subheadline.bold())
                    Text(HealthProfileDisplayFormatter.value(fact.value_data))
                        .font(.subheadline)
                        .foregroundColor(.appText)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: 8)
                Text("v\(fact.version)")
                    .font(.caption2.monospacedDigit())
                    .foregroundColor(.appMuted)
            }
            provenance(fact.sources, updatedAt: fact.updated_at, version: fact.version)
            HStack {
                if let definition = HealthProfileFieldCatalog.definition(for: fact.fact_key),
                   definition.category != .goal {
                    Button("编辑") {
                        editorFocused = false
                        vm.beginEditing(definition)
                    }
                    .buttonStyle(.bordered)
                    .accessibilityIdentifier("healthProfile.fact.\(fact.id).edit")
                }
                Button("来源与历史") {
                    editorFocused = false
                    Task {
                        await vm.openHistory(.init(
                            kind: .fact,
                            id: fact.fact_id,
                            title: HealthProfileFieldCatalog.label(for: fact.fact_key)
                        ))
                    }
                }
                .buttonStyle(.bordered)
                .accessibilityIdentifier("healthProfile.fact.\(fact.id).history")
                Spacer()
                Button("删除", role: .destructive) {
                    editorFocused = false
                    confirmation = .delete(fact)
                }
                .buttonStyle(.bordered)
                .accessibilityIdentifier("healthProfile.fact.\(fact.id).delete")
            }
            .disabled(vm.mutating || vm.hasPendingRetry)
        }
        .padding(11)
        .background(Color.appBackground)
        .clipShape(RoundedRectangle(cornerRadius: 11))
    }

    private func provenance(
        _ sources: [HealthProfileSource],
        updatedAt: String,
        version: Int? = nil
    ) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Text("更新：\(HealthProfileDisplayFormatter.timestamp(updatedAt))")
            if sources.isEmpty {
                Text("来源：服务端未返回可展示来源")
            } else {
                ForEach(sources) { source in
                    Text("来源：\(HealthProfileDisplayFormatter.source(source)) · \(HealthProfileDisplayFormatter.timestamp(source.created_at))")
                }
            }
            if let version {
                Text("当前版本：v\(version)；可通过“来源与历史”查看服务端修订记录。")
            }
        }
        .font(.caption2)
        .foregroundColor(.appMuted)
        .fixedSize(horizontal: false, vertical: true)
    }

    private func derivedBMICard(_ bmi: HealthProfileDerivedBMI) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text("BMI").font(.subheadline.bold())
                Spacer()
                Text(bmi.valueDescription)
                    .font(.headline.monospacedDigit())
                    .foregroundColor(bmi.value == nil ? .appMuted : .appPrimary)
            }
            Text(bmi.sourceDescription)
                .font(.caption)
                .foregroundColor(.appMuted)
                .fixedSize(horizontal: false, vertical: true)
            Text("更新：\(HealthProfileDisplayFormatter.timestamp(bmi.updatedAt))")
                .font(.caption2)
                .foregroundColor(.appMuted)
        }
        .padding(11)
        .background(Color.appBackground)
        .clipShape(RoundedRectangle(cornerRadius: 11))
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("healthProfile.basic.derivedBMI")
    }

    private var medicationSummary: some View {
        VStack(alignment: .leading, spacing: 12) {
            Label("长期用药摘要", systemImage: "pills.fill")
                .font(.headline)
                .foregroundColor(.appPrimary)
                .accessibilityIdentifier("healthProfile.medication")
            Text("画像只展示已确认的必要摘要。剂量、提醒和服药操作请进入用药管理。")
                .font(.caption)
                .foregroundColor(.appMuted)
                .fixedSize(horizontal: false, vertical: true)
            if vm.medicationSummaryLoading {
                ProgressView("正在读取长期用药摘要…")
                    .frame(maxWidth: .infinity, alignment: .leading)
            } else if let error = vm.medicationSummaryError {
                Label(error, systemImage: "exclamationmark.triangle.fill")
                    .font(.caption)
                    .foregroundColor(.appWarning)
                    .fixedSize(horizontal: false, vertical: true)
            } else if vm.longTermMedications.isEmpty {
                Text("暂无已确认的长期用药。")
                    .font(.caption)
                    .foregroundColor(.appMuted)
            } else {
                ForEach(vm.longTermMedications) { item in
                    VStack(alignment: .leading, spacing: 8) {
                        ForEach(item.displayFields) { field in
                            HStack(alignment: .firstTextBaseline, spacing: 10) {
                                Text(field.title)
                                    .font(.caption)
                                    .foregroundColor(.appMuted)
                                    .frame(width: 76, alignment: .leading)
                                Text(field.value)
                                    .font(field.key == .medicationName ? .subheadline.bold() : .caption)
                                    .foregroundColor(.appText)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                                    .fixedSize(horizontal: false, vertical: true)
                            }
                        }
                    }
                    .padding(11)
                    .background(Color.appBackground)
                    .clipShape(RoundedRectangle(cornerRadius: 11))
                    .accessibilityElement(children: .combine)
                }
            }
            NavigationLink {
                MedicationListView()
            } label: {
                HStack {
                    Text("进入用药管理")
                    Spacer()
                    Image(systemName: "chevron.right")
                }
            }
            .buttonStyle(.bordered)
            .accessibilityIdentifier("healthProfile.medication.open")
        }
        .cardStyle()
        .id("health-profile-medication")
    }

    private func healthGoals(_ profile: HealthProfileTrustResponse) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Label("健康目标与计划", systemImage: "target")
                    .font(.headline)
                    .foregroundColor(.appPrimary)
                Spacer()
                if vm.goalEditor == nil {
                    Button {
                        editorFocused = false
                        vm.beginCreatingGoal()
                    } label: {
                        Label("添加", systemImage: "plus")
                    }
                    .buttonStyle(.bordered)
                    .disabled(vm.mutating || vm.hasPendingRetry)
                    .accessibilityIdentifier("healthProfile.goal.add")
                }
            }
            .accessibilityIdentifier("healthProfile.goals")
            Text("目标只能由你主动创建；AI 和报告候选不能自动替你设定。支持同时管理多个目标。")
                .font(.caption)
                .foregroundColor(.appMuted)
                .fixedSize(horizontal: false, vertical: true)
            Text("健康计划模块同步")
                .font(.subheadline.bold())
                .foregroundColor(.appText)
            if profile.management_plans.isEmpty {
                Text("暂无进行中的健康计划。")
                    .font(.caption)
                    .foregroundColor(.appMuted)
            } else {
                ForEach(profile.management_plans) { plan in
                    managementPlanCard(plan)
                }
            }
            NavigationLink {
                HealthPlanView()
            } label: {
                HStack {
                    Text("进入健康计划")
                    Spacer()
                    Image(systemName: "chevron.right")
                }
            }
            .buttonStyle(.bordered)
            .accessibilityIdentifier("healthProfile.managementPlan.open")
            if profile.goals.isEmpty, vm.goalEditor == nil {
                Text("尚未添加健康目标。")
                    .font(.caption)
                    .foregroundColor(.appMuted)
            }
            ForEach(profile.goals) { goal in
                goalCard(goal)
            }
            if let draft = vm.goalEditor {
                goalEditorCard(draft)
                    .id("health-profile-goal-editor")
            }
        }
        .cardStyle()
        .id("health-profile-goals")
    }

    private func managementPlanCard(_ plan: HealthProfileManagementPlan) -> some View {
        VStack(alignment: .leading, spacing: 7) {
            HStack(alignment: .firstTextBaseline) {
                Text(plan.title)
                    .font(.subheadline.bold())
                Spacer()
                Text("\(plan.completed_task_count)/\(plan.task_count)")
                    .font(.caption.monospacedDigit())
                    .foregroundColor(.appMuted)
            }
            if let goal = plan.goal?.trimmingCharacters(in: .whitespacesAndNewlines), !goal.isEmpty {
                Text(goal)
                    .font(.caption)
                    .foregroundColor(.appText)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Label("\(plan.start_date) 至 \(plan.end_date)", systemImage: "calendar")
                .font(.caption2)
                .foregroundColor(.appMuted)
        }
        .padding(11)
        .background(Color.appBackground)
        .clipShape(RoundedRectangle(cornerRadius: 11))
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("healthProfile.managementPlan.\(plan.id)")
    }

    private func goalCard(_ goal: HealthProfileGoal) -> some View {
        VStack(alignment: .leading, spacing: 9) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 3) {
                    Text(goal.name)
                        .font(.subheadline.bold())
                    Text(goal.status.title)
                        .font(.caption2.bold())
                        .foregroundColor(goal.status == .active ? .appSuccess : .appMuted)
                }
                Spacer()
                Text("v\(goal.version)")
                    .font(.caption2.monospacedDigit())
                    .foregroundColor(.appMuted)
            }
            Label("开始：\(goal.started_on)", systemImage: "calendar")
                .font(.caption)
                .foregroundColor(.appMuted)
            Text("关联指标：\(goal.metrics.map(\.title).joined(separator: "、"))")
                .font(.caption)
                .foregroundColor(.appText)
                .fixedSize(horizontal: false, vertical: true)
            Text("最近确认：\(HealthProfileDisplayFormatter.timestamp(goal.confirmed_at))")
                .font(.caption2)
                .foregroundColor(.appMuted)
            HStack(spacing: 8) {
                if goal.status != .archived {
                    Button("编辑") {
                        editorFocused = false
                        vm.beginEditingGoal(goal)
                    }
                    .buttonStyle(.bordered)
                    .accessibilityIdentifier("healthProfile.goal.\(goal.id).edit")
                }
                Button("历史") {
                    editorFocused = false
                    Task {
                        await vm.openHistory(.init(kind: .goal, id: goal.goal_id, title: goal.name))
                    }
                }
                .buttonStyle(.bordered)
                .accessibilityIdentifier("healthProfile.goal.\(goal.id).history")
                Spacer()
                if goal.status != .archived {
                    Menu("状态") {
                        if PatientHistoryViewModel.allows(action: .pause, from: goal.status) {
                            Button("暂停") { confirmation = .goalStatus(goal, .pause) }
                        }
                        if PatientHistoryViewModel.allows(action: .resume, from: goal.status) {
                            Button("继续") { confirmation = .goalStatus(goal, .resume) }
                        }
                        if PatientHistoryViewModel.allows(action: .complete, from: goal.status) {
                            Button("标记完成") { confirmation = .goalStatus(goal, .complete) }
                        }
                        if PatientHistoryViewModel.allows(action: .archive, from: goal.status) {
                            Button("归档删除", role: .destructive) {
                                confirmation = .goalStatus(goal, .archive)
                            }
                        }
                    }
                    .buttonStyle(.bordered)
                    .accessibilityIdentifier("healthProfile.goal.\(goal.id).status")
                }
            }
            .disabled(vm.mutating || vm.hasPendingRetry)
        }
        .padding(11)
        .background(Color.appBackground)
        .clipShape(RoundedRectangle(cornerRadius: 11))
        .accessibilityIdentifier("healthProfile.goal.\(goal.id)")
    }

    private func goalEditorCard(_ draft: HealthProfileGoalEditorDraft) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Divider()
            Text(draft.isCreating ? "添加健康目标" : "编辑健康目标")
                .font(.subheadline.bold())
            TextField("例如：改善睡眠规律", text: Binding(
                get: { draft.name },
                set: vm.updateGoalName
            ))
            .textFieldStyle(.roundedBorder)
            .focused($editorFocused)
            .accessibilityIdentifier("healthProfile.goal.editor.name")
            TextField("开始日期（YYYY-MM-DD）", text: Binding(
                get: { draft.startedOn },
                set: vm.updateGoalStartedOn
            ))
            .textFieldStyle(.roundedBorder)
            .keyboardType(.numbersAndPunctuation)
            .focused($editorFocused)
            .accessibilityIdentifier("healthProfile.goal.editor.startedOn")
            Text("关联指标（用逗号、顿号或换行分隔）")
                .font(.caption)
                .foregroundColor(.appMuted)
            TextEditor(text: Binding(
                get: { draft.metricsText },
                set: vm.updateGoalMetricsText
            ))
            .frame(minHeight: 76, maxHeight: 140)
            .padding(8)
            .background(Color.appBackground)
            .overlay(RoundedRectangle(cornerRadius: 10).stroke(Color.appStroke))
            .focused($editorFocused)
            .accessibilityIdentifier("healthProfile.goal.editor.metrics")
            HStack {
                Button("取消") {
                    editorFocused = false
                    confirmation = draft.isDirty ? .discardEditor(closePage: false) : nil
                    if !draft.isDirty { vm.cancelGoalEditing() }
                }
                .buttonStyle(.bordered)
                Spacer()
                Button(vm.mutating ? "保存中…" : "保存目标") {
                    editorFocused = false
                    Task { await vm.saveGoalEditor() }
                }
                .buttonStyle(.borderedProminent)
                .disabled(!draft.isDirty || vm.mutating || vm.hasPendingRetry)
                .accessibilityIdentifier("healthProfile.goal.editor.save")
            }
        }
    }

    private func revisionHistoryPage(_ target: HealthProfileHistoryTarget) -> some View {
        NavigationStack {
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 12) {
                    if vm.historyLoading, vm.revisionHistory == nil {
                        ProgressView("正在读取修订记录…")
                            .frame(maxWidth: .infinity, minHeight: 160)
                    } else if let error = vm.historyError {
                        Label(error, systemImage: "exclamationmark.triangle.fill")
                            .font(.caption)
                            .foregroundColor(.appWarning)
                            .cardStyle()
                    } else if vm.revisionHistory?.items.isEmpty != false {
                        Text("暂无可展示的修订记录。")
                            .font(.caption)
                            .foregroundColor(.appMuted)
                            .frame(maxWidth: .infinity, minHeight: 160)
                    } else if let history = vm.revisionHistory {
                        ForEach(history.items) { revision in
                            revisionCard(revision)
                        }
                        if history.next_after_revision_id != nil {
                            Button(vm.historyLoading ? "正在加载…" : "加载更多") {
                                Task { await vm.loadMoreHistory() }
                            }
                            .buttonStyle(.bordered)
                            .disabled(vm.historyLoading)
                            .frame(maxWidth: .infinity)
                            .accessibilityIdentifier("healthProfile.history.loadMore")
                        }
                    }
                }
                .padding(16)
            }
            .background(Color.appBackground.ignoresSafeArea())
            .navigationTitle(target.title)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("完成") { vm.closeHistory() }
                }
            }
            .accessibilityIdentifier("healthProfile.history")
        }
    }

    private func revisionCard(_ revision: HealthProfileRevisionItem) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text(revisionEventTitle(revision.event_type))
                    .font(.subheadline.bold())
                Spacer()
                Text("v\(revision.target_version)")
                    .font(.caption2.monospacedDigit())
                    .foregroundColor(.appMuted)
            }
            Text(HealthProfileDisplayFormatter.timestamp(revision.created_at))
                .font(.caption2)
                .foregroundColor(.appMuted)
            if !revision.before_data.isEmpty {
                Text("修改前：\(HealthProfileDisplayFormatter.value(revision.before_data))")
                    .font(.caption)
                    .foregroundColor(.appMuted)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if !revision.after_data.isEmpty {
                Text("修改后：\(HealthProfileDisplayFormatter.value(revision.after_data))")
                    .font(.caption)
                    .foregroundColor(.appText)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .cardStyle()
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("healthProfile.history.revision.\(revision.id)")
    }

    private func revisionEventTitle(_ eventType: String) -> String {
        switch eventType {
        case "created", "create": return "已创建"
        case "updated", "update": return "已修改"
        case "retracted", "retract": return "已删除"
        case "status_changed", "status": return "状态已变更"
        default: return eventType.replacingOccurrences(of: "_", with: " ")
        }
    }

    private func performPrimaryAction(
        _ profile: HealthProfileTrustResponse,
        proxy: ScrollViewProxy
    ) {
        editorFocused = false
        guard let action = profile.overview.primary_action, action.isSupported else { return }
        switch (action.kind, action.route) {
        case ("review_updates", "profile_updates"):
            withAnimation { proxy.scrollTo("health-profile-candidates", anchor: .top) }
        case ("complete_profile", "profile_safety_editor"):
            let missingSafety = profile.overview.missing_required_fact_keys
                .compactMap(HealthProfileFieldCatalog.definition(for:))
                .first { $0.category == .safety }
            if let missingSafety {
                vm.beginEditing(missingSafety)
                Task { @MainActor in
                    await Task.yield()
                    withAnimation { proxy.scrollTo("health-profile-editor", anchor: .center) }
                }
            } else {
                withAnimation { proxy.scrollTo("health-profile-missing", anchor: .top) }
            }
        case ("complete_profile", "profile_editor"):
            let hasMissingFact = profile.overview.missing_required_fact_keys.contains {
                HealthProfileFieldCatalog.definition(for: $0)?.category != .goal
            }
            withAnimation {
                proxy.scrollTo(
                    hasMissingFact ? "health-profile-missing" : "health-profile-goals",
                    anchor: .top
                )
            }
        case ("edit_profile", "profile_editor"):
            withAnimation { proxy.scrollTo("health-profile-facts", anchor: .top) }
        default:
            break
        }
    }

    private var usageNotice: some View {
        VStack(alignment: .leading, spacing: 9) {
            Label("画像使用范围", systemImage: "lock.shield.fill")
                .font(.headline)
            Text("已确认事实可用于健康问答、建议、风险提示和长期趋势解释；候选更新不会进入这些场景。")
                .font(.caption)
                .foregroundColor(.appMuted)
            Label("X年龄暂不消费健康画像；待服务端评分版本和验证契约完成后再接入。", systemImage: "xmark.circle")
                .font(.caption.bold())
                .foregroundColor(.appWarning)
                .fixedSize(horizontal: false, vertical: true)
                .accessibilityIdentifier("healthProfile.xage.notConsumed")
        }
        .cardStyle()
    }

    private var unavailableCard: some View {
        VStack(spacing: 10) {
            Image(systemName: "person.crop.circle.badge.exclamationmark")
                .font(.largeTitle)
                .foregroundColor(.appMuted)
            Text("暂时无法读取健康画像").font(.headline)
            Button("重新读取") {
                Task { await vm.load(accountScope: authManager.accountScope) }
            }
            .buttonStyle(.borderedProminent)
        }
        .frame(maxWidth: .infinity, minHeight: 220)
        .cardStyle()
    }

    private func messageCard(_ text: String, icon: String, color: Color, dismiss: @escaping () -> Void) -> some View {
        HStack(alignment: .top, spacing: 9) {
            Image(systemName: icon).foregroundColor(color)
            Text(text)
                .font(.caption)
                .foregroundColor(.appText)
                .frame(maxWidth: .infinity, alignment: .leading)
            Button(action: dismiss) {
                Image(systemName: "xmark").font(.caption)
            }
            .buttonStyle(.plain)
        }
        .cardStyle()
    }

    private func attemptClose() {
        editorFocused = false
        if vm.hasUnsavedEditorChanges {
            confirmation = .discardEditor(closePage: true)
        } else {
            closePage()
        }
    }

    private func closePage() {
        if let onClose { onClose() } else { dismiss() }
    }

    private var confirmationTitle: String {
        switch confirmation {
        case .candidate(_, .accept): return "确认加入健康画像？"
        case .candidate(_, .reject): return "确认暂不加入？"
        case .saveSafety: return "再次确认安全信息"
        case .delete: return "确认删除画像事实？"
        case .goalStatus(_, .pause): return "确认暂停这个目标？"
        case .goalStatus(_, .resume): return "确认继续这个目标？"
        case .goalStatus(_, .complete): return "确认目标已完成？"
        case .goalStatus(_, .archive): return "确认归档删除这个目标？"
        case .discardEditor: return "放弃未保存修改？"
        case nil: return "请确认"
        }
    }

    private var confirmationMessage: String {
        switch confirmation {
        case .candidate(let candidate, .accept):
            return "确认后“\(HealthProfileFieldCatalog.label(for: candidate.fact_key))”才会成为画像事实，并保留报告来源和版本。"
        case .candidate(_, .reject): return "候选会从待确认列表移除，现有画像事实不会被覆盖。"
        case .saveSafety: return "安全信息会影响后续建议。请确认内容准确且由你本人主动提供。"
        case .delete: return "删除后服务器会保留修订记录；该事实不再进入问答与建议上下文。"
        case .goalStatus(let goal, .pause): return "“\(goal.name)”会停止作为进行中目标展示，可随时继续。"
        case .goalStatus(let goal, .resume): return "“\(goal.name)”会恢复为进行中。"
        case .goalStatus(let goal, .complete): return "“\(goal.name)”会标记为已完成，并保留修订记录。"
        case .goalStatus(let goal, .archive): return "“\(goal.name)”会从常用目标中归档；服务器仍保留修订记录。"
        case .discardEditor: return "当前编辑内容只保存在本页内，放弃后无法恢复。"
        case nil: return ""
        }
    }

    @ViewBuilder
    private func confirmationActions(
        onMutationCompleted: @escaping @MainActor () -> Void
    ) -> some View {
        switch confirmation {
        case .candidate(let candidate, let action):
            Button(action == .accept ? "确认加入" : "暂不加入", role: action == .reject ? .destructive : nil) {
                confirmation = nil
                Task {
                    await vm.reviewCandidate(candidate, action: action, safetyConfirmed: true)
                    onMutationCompleted()
                }
            }
            Button("取消", role: .cancel) { confirmation = nil }
        case .saveSafety:
            Button("确认并保存") {
                confirmation = nil
                Task {
                    await vm.saveEditor(safetyConfirmed: true)
                    onMutationCompleted()
                }
            }
            Button("取消", role: .cancel) { confirmation = nil }
        case .delete(let fact):
            Button("确认删除", role: .destructive) {
                confirmation = nil
                Task {
                    await vm.retract(fact, confirmed: true)
                    onMutationCompleted()
                }
            }
            Button("取消", role: .cancel) { confirmation = nil }
        case .goalStatus(let goal, let action):
            Button(goalActionTitle(action), role: action == .archive ? .destructive : nil) {
                confirmation = nil
                Task {
                    await vm.changeGoalStatus(goal, action: action)
                    onMutationCompleted()
                }
            }
            Button("取消", role: .cancel) { confirmation = nil }
        case .discardEditor(let closePage):
            Button("放弃修改", role: .destructive) {
                confirmation = nil
                vm.cancelEditing()
                vm.cancelGoalEditing()
                if closePage { self.closePage() }
            }
            Button("继续编辑", role: .cancel) { confirmation = nil }
        case nil:
            Button("取消", role: .cancel) {}
        }
    }

    private func goalActionTitle(_ action: HealthProfileGoalAction) -> String {
        switch action {
        case .pause: return "确认暂停"
        case .resume: return "确认继续"
        case .complete: return "确认完成"
        case .archive: return "归档删除"
        }
    }
}

#Preview {
    NavigationStack { PatientHistoryView() }
        .environmentObject(AuthManager.shared)
}
