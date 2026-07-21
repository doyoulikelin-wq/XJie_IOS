import AVFoundation
import Speech
import SwiftUI
import UIKit

struct XAgeMainView: View {
    @Environment(\.scenePhase) private var scenePhase
    @EnvironmentObject private var externalReportImport: XAgeExternalReportImportRouter
    @EnvironmentObject private var authManager: AuthManager
    @StateObject private var appleHealthSync = AppleHealthSyncViewModel()
    @StateObject private var serverSync = XAgeServerSyncViewModel()
    @StateObject private var externalReportUploadVM = HealthReportCompletionViewModel()
    @State private var selectedSection: XAgeTopSection = Self.initialSection()
    @State private var selectedDataPanelCategory: XAgeDataPanelCategory = .reports
    @State private var showMoreMenu = false
    @State private var dataManagerRequest = 0
    @State private var presentedQuickActionID: String?
    @State private var conversationModuleHandoff: XAgeConversationModuleHandoff?
    @State private var chatHistoryRequest = 0
    @State private var xAgeInfoRequest = 0
    @State private var pendingExternalUpload: XAgePendingReportUpload?
    @State private var externalReportReviewRoute: HealthReportWorkflowRoute?
    @State private var externalImportError: String?
    @State private var configuredAppleHealthAccountScope: String?
    @State private var hasConfiguredAppleHealthAccountScope = false

    var body: some View {
        NavigationStack {
            ZStack {
                XAgeLiquidBackground()
                    .ignoresSafeArea()

                VStack(spacing: 0) {
                    XAgeTopBar(
                        selected: $selectedSection,
                        showMoreMenu: $showMoreMenu,
                        onOpenDataManager: {
                            dataManagerRequest += 1
                        },
                        onOpenChatHistory: {
                            chatHistoryRequest += 1
                        },
                        onOpenXAgeInfo: {
                            xAgeInfoRequest += 1
                        }
                    )
                    .padding(.top, 12)
                    .padding(.horizontal, 24)
                    .zIndex(2)

                    TabView(selection: $selectedSection) {
                        XAgeDataDashboardView(
                            managerRequest: dataManagerRequest,
                            appleHealthSync: appleHealthSync,
                            serverSync: serverSync,
                            scores: compositeScores,
                            accountScope: authManager.accountScope,
                            onSyncAppleHealth: syncAppleHealthAndRefreshServer,
                            onOpenMetricGuide: openMetricGuide,
                            onOpenQuickAction: presentQuickAction
                        )
                            .id(authManager.accountScope ?? "logged-out")
                            .tag(XAgeTopSection.data)

                        XAgeConversationSurface(
                            selectedSection: $selectedSection,
                            historyRequest: chatHistoryRequest
                        )
                            .tag(XAgeTopSection.chat)

                        XAgeHealthspanView(
                            selectedSection: $selectedSection,
                            infoRequest: xAgeInfoRequest
                        )
                            .tag(XAgeTopSection.xAge)
                    }
                    .tabViewStyle(.page(indexDisplayMode: .never))
                    .accessibilityIdentifier("xage.section.content")
                    .environment(\.xAgeOpenConversationModule) { presentConversationModule($0) }
                }

#if DEBUG
                if UIAutomationMode.isEnabled(arguments: ProcessInfo.processInfo.arguments) {
                    Text("可信评分展示审计")
                        .font(.system(size: 1))
                        .frame(width: 1, height: 1)
                        .opacity(0.01)
                        .accessibilityIdentifier("xage.score.trust.audit")
                        .accessibilityValue(XAgeTrustedScorePresentationPolicy.debugAuditValue())
                }
#endif
            }
            .navigationBarHidden(true)
            .sheet(isPresented: $showMoreMenu) {
                XAgeMoreMenu(
                    selectedCategory: $selectedDataPanelCategory,
                    appleHealthSync: appleHealthSync,
                    snapshot: serverSync.snapshot,
                    onSyncAppleHealth: syncAppleHealthAndRefreshServer,
                    onSelectCategory: selectPanelCategory,
                    onClose: { showMoreMenu = false }
                )
                    .presentationDetents([.large])
            }
            .fullScreenCover(isPresented: Binding(
                get: { presentedQuickActionID != nil },
                set: { if !$0 { closeQuickAction() } }
            )) {
                quickActionDestination
            }
            .sheet(item: $pendingExternalUpload) { upload in
                XAgeReportUploadConfirmSheet(
                    upload: upload,
                    isUploading: externalReportUploadVM.uploading,
                    onCancel: { pendingExternalUpload = nil },
                    onConfirm: {
                        pendingExternalUpload = nil
                        uploadExternalReports(upload.files, source: upload.source)
                    }
                )
                .presentationDetents([.medium, .large])
                .presentationDragIndicator(.visible)
            }
            .navigationDestination(item: $externalReportReviewRoute) { route in
                HealthReportReviewView(
                    route: route,
                    accountScope: authManager.accountScope,
                    documentTitle: externalReportUploadVM.activeReportTitle
                )
            }
            .confirmationDialog(
                "检测到可能重复的报告",
                isPresented: Binding(
                    get: { externalReportUploadVM.duplicatePrompt != nil },
                    set: { if !$0 { externalReportUploadVM.deferDuplicateDecision() } }
                ),
                titleVisibility: .visible
            ) {
                Button("使用已有报告") {
                    if let prompt = externalReportUploadVM.duplicatePrompt {
                        Task {
                            await externalReportUploadVM.decideDuplicate(.useExisting, prompt: prompt)
                        }
                    }
                }
                Button("继续新建报告") {
                    if let prompt = externalReportUploadVM.duplicatePrompt {
                        Task {
                            await externalReportUploadVM.decideDuplicate(.continueNew, prompt: prompt)
                        }
                    }
                }
                Button("稍后处理", role: .cancel) {
                    externalReportUploadVM.deferDuplicateDecision()
                }
            } message: {
                Text("系统只提示最相近的一份报告，不会自动覆盖。请选择是否复用已有报告。")
            }
            .alert("导入失败", isPresented: Binding(
                get: { externalImportError != nil },
                set: { if !$0 { externalImportError = nil } }
            )) {
                Button("知道了", role: .cancel) {}
            } message: {
                Text(externalImportError ?? "")
            }
            .alert("上传提示", isPresented: Binding(
                get: { externalReportUploadVM.infoMessage != nil },
                set: { if !$0 { externalReportUploadVM.infoMessage = nil } }
            )) {
                Button("知道了", role: .cancel) {}
            } message: {
                Text(externalReportUploadVM.infoMessage ?? "")
            }
            .alert(externalReportUploadVM.uploadRecovery == nil ? "上传失败" : "报告需要重新导入", isPresented: Binding(
                get: { externalReportUploadVM.errorMessage != nil },
                set: { if !$0 { externalReportUploadVM.errorMessage = nil } }
            )) {
                if externalReportUploadVM.uploadRecovery != nil {
                    Button("前往报告页重新上传") {
                        externalReportUploadVM.abandonUploadRecovery()
                        selectedDataPanelCategory = .reports
                        selectedSection = .data
                        presentedQuickActionID = "reports"
                    }
                    Button("稍后处理", role: .cancel) {}
                } else {
                    Button("确定", role: .cancel) {}
                }
            } message: {
                Text(externalReportUploadVM.errorMessage ?? "")
            }
            .onAppear {
                configureAppleHealthAccountScope(authManager.accountScope)
                handlePendingExternalImportIfNeeded()
                Task { await refreshXAgeDataFromAppLifecycle() }
            }
            .onChange(of: scenePhase) { _, phase in
                guard phase == .active else { return }
                Task { await refreshXAgeDataFromAppLifecycle() }
            }
            .onChange(of: externalReportImport.pendingImport) { _, _ in
                handlePendingExternalImportIfNeeded()
            }
            .onChange(of: selectedSection) { _, _ in
                XAgeKeyboard.dismiss()
            }
            .onChange(of: showMoreMenu) { _, isPresented in
                if isPresented {
                    XAgeKeyboard.dismiss()
                }
            }
            .onChange(of: authManager.accountScope) { _, accountScope in
                configureAppleHealthAccountScope(accountScope)
                externalReportUploadVM.accountDidChange(to: accountScope)
                externalReportReviewRoute = nil
                Task { await refreshXAgeDataFromAppLifecycle() }
            }
            .onChange(of: externalReportUploadVM.activeReportWorkflow) { _, route in
                guard let route,
                      [.awaitingConfirmation, .completedScorePending, .completed].contains(route.status)
                else { return }
                externalReportReviewRoute = route
            }
        }
    }

    private var compositeScores: XAgeCompositeScores {
        XAgeTrustedScorePresentationPolicy.currentPresentation()
    }

    private func selectPanelCategory(_ category: XAgeDataPanelCategory) {
        selectedDataPanelCategory = category
        withAnimation(.spring(response: 0.3, dampingFraction: 0.86)) {
            selectedSection = .data
        }
    }

    private func openMetricGuide(_ kind: XAgeDataKind) {
        selectedDataPanelCategory = kind == .inflammation ? .reports : .daily
        showMoreMenu = true
    }

    private func presentQuickAction(_ identifier: String) {
        guard XAgeDataPanelCategory.homeQuickActions.contains(where: {
            $0.id == identifier && $0.destination == identifier
        }) else { return }
        conversationModuleHandoff = nil
        presentedQuickActionID = identifier
    }

    private func presentConversationModule(_ handoff: XAgeConversationModuleHandoff) {
        guard XAgeConversationNavigationAction.available.contains(handoff.action) else { return }
        conversationModuleHandoff = handoff
        presentedQuickActionID = handoff.action.id
    }

    @ViewBuilder
    private var quickActionDestination: some View {
        switch presentedQuickActionID {
        case "meals":
            quickActionNavigation {
                if let entry = conversationModuleHandoff?.dietaryEntry {
                    MealsView(initialEntry: entry)
                } else {
                    MealsView()
                }
            }
        case "mood":
            quickActionNavigation { MoodLogView() }
        case "reports", "profile":
            XAgePanelDestinationView(
                category: presentedQuickActionID == "profile" ? .profile : .reports,
                appleHealthSync: appleHealthSync,
                snapshot: serverSync.snapshot,
                onSyncAppleHealth: syncAppleHealthAndRefreshServer,
                onClose: closeQuickAction
            )
        case "medications":
            XAgeMedicationManagementView(onClose: closeQuickAction)
        case "health-plan":
            quickActionNavigation { HealthPlanView() }
        case "medical":
            quickActionNavigation { MedicalRecordListView() }
        default:
            XAgeLiquidBackground()
                .ignoresSafeArea()
                .task { closeQuickAction() }
        }
    }

    private func quickActionNavigation<Content: View>(@ViewBuilder content: () -> Content) -> some View {
        NavigationStack {
            content()
                .toolbar {
                    ToolbarItem(placement: .topBarLeading) {
                        Button(action: closeQuickAction) {
                            Image(systemName: "xmark")
                                .font(.system(size: 13, weight: .bold))
                                .foregroundStyle(Color(hex: "1268BD"))
                                .frame(width: 44, height: 44)
                                .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        .accessibilityLabel("关闭并返回数据页")
                        .accessibilityIdentifier("xage.quickAction.close")
                    }
                }
            }
    }

    private func closeQuickAction() {
        presentedQuickActionID = nil
        conversationModuleHandoff = nil
    }

    private func refreshXAgeDataFromAppLifecycle() async {
        let accountScope = authManager.accountScope
        configureAppleHealthAccountScope(accountScope)
        guard accountScope != nil else { return }
        await appleHealthSync.refreshIfPreviouslySynced()
        await serverSync.refresh()
    }

    private func syncAppleHealthAndRefreshServer() async {
        let accountScope = authManager.accountScope
        let didStart = await XAgeAppleHealthSyncFlow.synchronize(
            accountScope: accountScope,
            configureAccount: configureAppleHealthAccountScope,
            synchronizeHealth: { await appleHealthSync.requestAccessAndSync() },
            refreshServer: { await serverSync.refresh() }
        )
        if !didStart {
            appleHealthSync.status = .failed("无法确认当前账号，请重新登录后再同步 Apple 健康。")
        }
    }

    private func configureAppleHealthAccountScope(_ accountScope: String?) {
        guard !hasConfiguredAppleHealthAccountScope || configuredAppleHealthAccountScope != accountScope else {
            return
        }
        let coordinator = AppleHealthBackgroundSyncCoordinator.shared
        coordinator.stop()
        appleHealthSync.setAccountScope(accountScope)
        serverSync.setAccountScope(accountScope)
        coordinator.startIfEligible(accountScope: accountScope)
        configuredAppleHealthAccountScope = accountScope
        hasConfiguredAppleHealthAccountScope = true
    }

    private func handlePendingExternalImportIfNeeded() {
        guard let item = externalReportImport.pendingImport else { return }
        externalReportImport.markHandled(item.id)
        Task { await prepareExternalReportImport(item.url) }
    }

    private func prepareExternalReportImport(_ url: URL) async {
        let access = url.startAccessingSecurityScopedResource()
        defer {
            if access {
                url.stopAccessingSecurityScopedResource()
            }
        }

        do {
            let data = try LocalFileDataLoader.read(url)
            guard !data.isEmpty else {
                externalImportError = "文件为空，无法上传。"
                return
            }
            let fileName = url.lastPathComponent.isEmpty ? "外部导入报告" : url.lastPathComponent
            let file = XAgeReportUploadFile(data: data, fileName: fileName)
            pendingExternalUpload = XAgePendingReportUpload(
                title: "确认导入报告",
                source: "打开方式",
                files: [file]
            )
            selectedSection = .data
            selectedDataPanelCategory = .reports
        } catch {
            externalImportError = "无法读取该文件：\(error.localizedDescription)"
        }
    }

    private func uploadExternalReports(_ files: [XAgeReportUploadFile], source: String) {
        guard !files.isEmpty else { return }
        Task {
            _ = await externalReportUploadVM.uploadReport(
                files: files.map {
                    HealthReportUploadAssetInput(data: $0.data, fileName: $0.fileName)
                },
                source: source,
                subjectUserID: authManager.authenticatedNumericUserID,
                accountScope: authManager.accountScope
            )
            await serverSync.refresh()
        }
    }

    private static func initialSection() -> XAgeTopSection {
        #if DEBUG
        if let rawValue = ProcessInfo.processInfo.environment["XAGE_INITIAL_SECTION"] ?? launchArgumentValue(for: "XAGE_INITIAL_SECTION"),
           let section = XAgeTopSection.section(matching: rawValue) {
            return section
        }
        #endif
        return .data
    }

    #if DEBUG
    private static func launchArgumentValue(for key: String) -> String? {
        let arguments = ProcessInfo.processInfo.arguments
        for (index, argument) in arguments.enumerated() {
            if argument == key, arguments.indices.contains(index + 1) {
                return arguments[index + 1]
            }
            if argument.hasPrefix("\(key)=") {
                return String(argument.dropFirst(key.count + 1))
            }
        }
        return nil
    }
    #endif
}

#if DEBUG
private extension XAgeTopSection {
    static func section(matching value: String) -> XAgeTopSection? {
        switch value {
        case "data", "数据":
            return .data
        case "chat", "qa", "问答":
            return .chat
        case "xAge", "xage", "X年龄":
            return .xAge
        default:
            return nil
        }
    }
}
#endif

private struct XAgeTopBar: View {
    @Binding var selected: XAgeTopSection
    @Binding var showMoreMenu: Bool
    let onOpenDataManager: () -> Void
    let onOpenChatHistory: () -> Void
    let onOpenXAgeInfo: () -> Void

    var body: some View {
        HStack(spacing: 8) {
            Button {
                XAgeKeyboard.dismiss()
                showMoreMenu = true
            } label: {
                Image(systemName: "line.3.horizontal")
                    .font(.system(size: 18, weight: .semibold))
                    .frame(width: 44, height: 44)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .foregroundStyle(Color(hex: "173F64"))
            .accessibilityLabel("资料菜单")
            .accessibilityIdentifier("xage.more")

            HStack(spacing: 0) {
                ForEach(XAgeTopSection.allCases) { section in
                    Button {
                        XAgeKeyboard.dismiss()
                        withAnimation(.spring(response: 0.32, dampingFraction: 0.86)) {
                            selected = section
                        }
                    } label: {
                        Text(section.rawValue)
                            .font(.system(size: 15, weight: selected == section ? .bold : .medium))
                            .foregroundStyle(selected == section ? Color(hex: "1268BD") : Color(hex: "4E718E"))
                            .lineLimit(1)
                            .minimumScaleFactor(0.78)
                            .frame(maxWidth: .infinity)
                            .frame(height: 44)
                            .contentShape(Rectangle())
                    }
                    .accessibilityIdentifier("xage.segment.\(section.id)")
                    .accessibilityLabel(section.rawValue)
                    .xAgeAccessibilitySelected(selected == section)
                    .buttonStyle(.plain)
                    .background {
                        if selected == section {
                            RoundedRectangle(cornerRadius: 22, style: .continuous)
                                .fill(.white.opacity(0.72))
                                .overlay(
                                    RoundedRectangle(cornerRadius: 22, style: .continuous)
                                        .stroke(.white.opacity(0.92), lineWidth: 1)
                                )
                                .shadow(color: Color(hex: "2FB6E3").opacity(0.16), radius: 16, x: 0, y: 8)
                        }
                    }
                }
            }
            .frame(maxWidth: .infinity)
            .frame(height: 48)
            .background(
                RoundedRectangle(cornerRadius: 24, style: .continuous)
                    .fill(.white.opacity(0.48))
                    .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 24, style: .continuous))
                    .overlay(
                        RoundedRectangle(cornerRadius: 24, style: .continuous)
                            .stroke(.white.opacity(0.86), lineWidth: 1)
                    )
                    .shadow(color: Color(hex: "7CCAF5").opacity(0.16), radius: 22, x: 0, y: 10)
            )

            if selected == .xAge {
                Button {
                    onOpenXAgeInfo()
                } label: {
                    Image(systemName: "info.circle.fill")
                        .font(.system(size: 18, weight: .bold))
                        .frame(width: 44, height: 44)
                        .background(XAgeCapsuleFill())
                }
                .buttonStyle(.plain)
                .foregroundStyle(Color(hex: "18AFA7"))
                .accessibilityLabel("X年龄原理")
                .accessibilityIdentifier("xage.xage.info.top")
            } else {
                Button {
                    if selected == .data {
                        onOpenDataManager()
                    } else if selected == .chat {
                        onOpenChatHistory()
                    }
                } label: {
                    Group {
                        if selected == .data {
                            Text("管理")
                                .font(.system(size: 14, weight: .bold))
                                .frame(width: 52, height: 44)
                        } else {
                            Image(systemName: "clock.arrow.circlepath")
                                .font(.system(size: 18, weight: .bold))
                                .frame(width: 44, height: 44)
                        }
                    }
                    .background(
                        Capsule()
                            .fill(.white.opacity(0.48))
                            .overlay(Capsule().stroke(.white.opacity(0.86), lineWidth: 1))
                    )
                }
                .buttonStyle(.plain)
                .foregroundStyle(selected == .chat ? Color(hex: "173F64") : Color(hex: "2A79BB"))
                .accessibilityLabel(selected == .data ? "管理数据卡片" : "历史对话")
                .accessibilityIdentifier(selected == .data ? "xage.data.manage" : "xage.chat.history")
            }
        }
    }
}
