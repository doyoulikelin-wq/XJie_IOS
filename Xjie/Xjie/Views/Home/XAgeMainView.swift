import AVFoundation
import Speech
import SwiftUI
import UIKit

struct XAgeMainView: View { // MARK: 全局环境与长生命周期状态：根页面只负责装配共享依赖、页面状态与各业务模块，不在此重复实现子模块业务。
    @Environment(\.scenePhase) private var scenePhase // 监听 App 前后台切换；重新回到 active 时刷新健康数据与服务端快照。
    @EnvironmentObject private var externalReportImport: XAgeExternalReportImportRouter // 接收 App 根入口暂存的“用小捷打开”外部报告文件。
    @EnvironmentObject private var authManager: AuthManager // 提供当前登录主体、数值用户 ID 和账号隔离 scope；所有健康/报告请求都以它为边界。
    @StateObject private var appleHealthSync = AppleHealthSyncViewModel() // 本页面拥有 Apple 健康授权、读取、上传和同步状态，页面重绘时实例不会重建。
    @StateObject private var serverSync = XAgeServerSyncViewModel() // 保存服务端 XAGE 数据快照；数据页、更多菜单和报告流程共享同一份结果。
    @StateObject private var externalReportUploadVM = HealthReportCompletionViewModel() // 管理外部报告上传、重复报告判断、确认流程、恢复提示与最终审核路由。
    @State private var selectedSection: XAgeTopSection = Self.initialSection() // 当前主模块：数据、问答或 X 年龄；TabView 与顶部栏双向绑定此状态。
    @State private var selectedDataPanelCategory: XAgeDataPanelCategory = .reports // 更多菜单/数据面板当前分类，指标说明与恢复上传会主动切换它。
    @State private var showMoreMenu = false // true 时由下方 sheet 展示 XAgeMoreMenu；菜单关闭后恢复为 false。
    @State private var dataManagerRequest = 0 // 事件计数器：每次点击“管理”递增，即使连续点击相同入口也能触发子视图 onChange。
    @State private var presentedQuickActionID: String? // 当前全屏快捷功能的稳定 ID；非空即打开 fullScreenCover，置空即关闭。
    @State private var conversationModuleHandoff: XAgeConversationModuleHandoff? // 从问答模块跳转膳食/报告等页面时携带的可选上下文数据。
    @State private var chatHistoryRequest = 0 // 问答页历史入口事件计数器，由顶部栏点击递增并交给对话子页面处理。
    @State private var xAgeInfoRequest = 0 // X 年龄说明入口事件计数器，避免仅靠 Bool 难以区分重复点击。
    @State private var pendingExternalUpload: XAgePendingReportUpload? // 外部文件读取成功后生成的待确认上传任务；非空时显示确认 sheet。
    @State private var externalReportReviewRoute: HealthReportWorkflowRoute? // 报告进入待确认/评分中/完成状态后，驱动 NavigationStack 打开审核页。
    @State private var externalImportError: String? // 外部文件读取失败文案；非空时显示“导入失败”提示。
    @State private var configuredAppleHealthAccountScope: String? // 记录最近一次已配置的账号 scope，用于识别是否需要停止旧账号协调器并重绑。
    @State private var hasConfiguredAppleHealthAccountScope = false // 区分“从未配置”与“已配置为 nil”，保证首次退出态也执行一次完整初始化。

    var body: some View { // MARK: 页面骨架与三大主模块：NavigationStack 管纵向页面，ZStack 放背景，VStack 放顶部栏和可横滑 TabView。
        NavigationStack { // 根导航栈承接报告审核等 push 路由；快捷功能使用独立全屏导航栈，互不污染返回路径。
            ZStack { // 底层液态背景与上层页面内容叠放，Debug UI 自动化审计节点也挂在这一层。
                XAgeLiquidBackground() // XAGE 全屏统一背景，不参与点击事件。
                    .ignoresSafeArea()

                VStack(spacing: 0) { // 顶部栏固定在上，TabView 占用剩余空间；spacing=0 保证两部分视觉连续。
                    XAgeTopBar( // 子组件只报告点击意图，实际页面状态仍由 XAgeMainView 统一拥有。
                        selected: $selectedSection,
                        showMoreMenu: $showMoreMenu,
                        onOpenDataManager: { // Canvas 点击数据页“管理”后从这里进入：递增请求值，由数据面板观察并打开卡片管理。
                            dataManagerRequest += 1 // 使用计数而非 Bool，关闭后再次点击仍一定产生新值。
                        },
                        onOpenChatHistory: { // Canvas 点击问答页历史图标后，通知 XAgeConversationSurface 打开历史记录。
                            chatHistoryRequest += 1
                        },
                        onOpenXAgeInfo: { // Canvas 点击 X 年龄信息图标后，通知健康跨度页面展示原理说明。
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
            .navigationBarHidden(true) // MARK: 模态、导航与错误反馈出口：根页面隐藏系统栏，所有出口由下面状态集中驱动。
            .sheet(isPresented: $showMoreMenu) { // showMoreMenu=true 时打开“更多”；onClose 只关闭此 sheet，不影响主 Tab。
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
            .fullScreenCover(isPresented: Binding( // presentedQuickActionID 非空即展示快捷功能；系统手势关闭时统一调用 closeQuickAction 清上下文。
                get: { presentedQuickActionID != nil },
                set: { if !$0 { closeQuickAction() } }
            )) {
                quickActionDestination
            }
            .sheet(item: $pendingExternalUpload) { upload in // 外部文件读取成功后先让用户确认，确认前不会直接上传。
                XAgeReportUploadConfirmSheet(
                    upload: upload,
                    isUploading: externalReportUploadVM.uploading,
                    onCancel: { pendingExternalUpload = nil }, // 取消只丢弃本次待上传任务，不删除原文件。
                    onConfirm: {
                        pendingExternalUpload = nil
                        uploadExternalReports(upload.files, source: upload.source)
                    }
                )
                .presentationDetents([.medium, .large])
                .presentationDragIndicator(.visible)
            }
            .navigationDestination(item: $externalReportReviewRoute) { route in // 上传工作流达到可审核状态后 push 报告确认/评分页面。
                HealthReportReviewView(
                    route: route,
                    accountScope: authManager.accountScope,
                    documentTitle: externalReportUploadVM.activeReportTitle
                )
            }
            .confirmationDialog( // 重复检测只提供最相近报告，由用户明确选择复用或继续新建，系统不自动覆盖。
                "检测到可能重复的报告",
                isPresented: Binding(
                    get: { externalReportUploadVM.duplicatePrompt != nil },
                    set: { if !$0 { externalReportUploadVM.deferDuplicateDecision() } }
                ),
                titleVisibility: .visible
            ) {
                Button("使用已有报告") { // 复用已有报告：异步提交 useExisting 决策，VM 继续后续工作流。
                    if let prompt = externalReportUploadVM.duplicatePrompt {
                        Task {
                            await externalReportUploadVM.decideDuplicate(.useExisting, prompt: prompt)
                        }
                    }
                }
                Button("继续新建报告") { // 用户确认不是重复项：继续生成新的报告记录。
                    if let prompt = externalReportUploadVM.duplicatePrompt {
                        Task {
                            await externalReportUploadVM.decideDuplicate(.continueNew, prompt: prompt)
                        }
                    }
                }
                Button("稍后处理", role: .cancel) { // 暂停当前重复决策，保留可恢复状态而不隐式选择任一分支。
                    externalReportUploadVM.deferDuplicateDecision()
                }
            } message: {
                Text("系统只提示最相近的一份报告，不会自动覆盖。请选择是否复用已有报告。")
            }
            .alert("导入失败", isPresented: Binding( // externalImportError 非空时显示本地文件读取错误，关闭后同步清空错误状态。
                get: { externalImportError != nil },
                set: { if !$0 { externalImportError = nil } }
            )) {
                Button("知道了", role: .cancel) {}
            } message: {
                Text(externalImportError ?? "")
            }
            .alert("上传提示", isPresented: Binding( // 展示 VM 产生的非致命说明，例如工作流状态提示。
                get: { externalReportUploadVM.infoMessage != nil },
                set: { if !$0 { externalReportUploadVM.infoMessage = nil } }
            )) {
                Button("知道了", role: .cancel) {}
            } message: {
                Text(externalReportUploadVM.infoMessage ?? "")
            }
            .alert(externalReportUploadVM.uploadRecovery == nil ? "上传失败" : "报告需要重新导入", isPresented: Binding( // 可恢复失败提供返回报告页入口，普通失败只确认关闭。
                get: { externalReportUploadVM.errorMessage != nil },
                set: { if !$0 { externalReportUploadVM.errorMessage = nil } }
            )) {
                if externalReportUploadVM.uploadRecovery != nil {
                    Button("前往报告页重新上传") { // 清理旧恢复状态并切到数据/报告模块，再用 reports 快捷页引导重新选文件。
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
            .onAppear { // MARK: 生命周期与账号状态联动：首次出现先配置账号边界、消费外部文件，再异步刷新本地与服务端数据。
                configureAppleHealthAccountScope(authManager.accountScope) // 先绑定 scope，防止刷新读到上一账号的缓存或后台协调器。
                handlePendingExternalImportIfNeeded() // App 若由“打开方式”进入，这里消费根路由暂存的文件。
                Task { await refreshXAgeDataFromAppLifecycle() } // 不阻塞首屏绘制；实际刷新逻辑集中在同一 async 方法。
            }
            .onChange(of: scenePhase) { _, phase in // 从后台回到前台时补刷新；inactive/background 不发起重复请求。
                guard phase == .active else { return }
                Task { await refreshXAgeDataFromAppLifecycle() }
            }
            .onChange(of: externalReportImport.pendingImport) { _, _ in // App 已在前台时收到新外部文件，也走同一消费入口。
                handlePendingExternalImportIfNeeded()
            }
            .onChange(of: selectedSection) { _, _ in // 顶部点击或横滑切页都关闭键盘，避免输入框跨模块残留焦点。
                XAgeKeyboard.dismiss()
            }
            .onChange(of: showMoreMenu) { _, isPresented in // 打开更多菜单前关闭键盘；关闭菜单不额外改变当前模块。
                if isPresented {
                    XAgeKeyboard.dismiss()
                }
            }
            .onChange(of: authManager.accountScope) { _, accountScope in // 登录、退出或切换账号时同时重置健康、上传与审核三条数据链。
                configureAppleHealthAccountScope(accountScope) // 停止旧账号后台任务并重绑两个同步 ViewModel。
                externalReportUploadVM.accountDidChange(to: accountScope) // 丢弃不应跨账号延续的报告上传工作流。
                externalReportReviewRoute = nil // 关闭旧账号可能仍展示的审核页面。
                Task { await refreshXAgeDataFromAppLifecycle() } // 新账号有效时重新获取数据；退出态会在方法内安全返回。
            }
            .onChange(of: externalReportUploadVM.activeReportWorkflow) { _, route in // 仅在需要用户确认或可查看结果的阶段打开审核页。
                guard let route,
                      [.awaitingConfirmation, .completedScorePending, .completed].contains(route.status)
                else { return }
                externalReportReviewRoute = route
            }
        }
    }

    private var compositeScores: XAgeCompositeScores { // 首页三项评分使用设备与服务端同步输入按本地算法实时计算；X 年龄仍走独立关闭策略。
        XAgeCompositeScores.compute(
            context: XAgeAlgorithmContext(snapshot: serverSync.snapshot, samples: appleHealthSync.samples)
        )
    }

    private func selectPanelCategory(_ category: XAgeDataPanelCategory) { // 更多菜单选择资料分类后保存分类，并以动画回到数据主模块。
        selectedDataPanelCategory = category // 数据面板观察此绑定，决定报告/日常/画像等实际内容。
        withAnimation(.spring(response: 0.3, dampingFraction: 0.86)) {
            selectedSection = .data
        }
    }

    private func openMetricGuide(_ kind: XAgeDataKind) { // 指标卡点击说明：炎症归入报告，其余指标归入日常，然后打开更多菜单。
        selectedDataPanelCategory = kind == .inflammation ? .reports : .daily
        showMoreMenu = true
    }

    private func presentQuickAction(_ identifier: String) { // MARK: 快捷入口与对话模块路由：只允许首页已登记且 destination 与 ID 一致的固定入口。
        guard XAgeDataPanelCategory.homeQuickActions.contains(where: {
            $0.id == identifier && $0.destination == identifier
        }) else { return }
        conversationModuleHandoff = nil // 普通首页点击不携带聊天上下文，先清理上一次 handoff 防止数据串入。
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

    private func quickActionNavigation<Content: View>(@ViewBuilder content: () -> Content) -> some View { // 为普通快捷子页统一提供独立导航栈和左上角关闭按钮。
        NavigationStack {
            content()
                .toolbar {
                    ToolbarItem(placement: .topBarLeading) {
                        Button(action: closeQuickAction) { // Canvas 点击 xmark 后调用 closeQuickAction，而不是修改更多菜单或主 Tab 状态。
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

    private func closeQuickAction() { // 清理“页面 ID + 可选上下文”这一对状态；fullScreenCover 观察 ID 变 nil 后关闭。
        presentedQuickActionID = nil
        conversationModuleHandoff = nil // 同时释放聊天传入的预填数据，避免下次普通入口复用。
    }

    private func refreshXAgeDataFromAppLifecycle() async { // 前台/首次出现/账号切换共用的温和刷新：只刷新曾同步的健康数据，再拉服务端快照。
        let accountScope = authManager.accountScope // 在异步开始前捕获当前 scope，并同步配置两个 ViewModel。
        configureAppleHealthAccountScope(accountScope)
        guard accountScope != nil else { return } // 未登录时不触发任何账号请求。
        await appleHealthSync.refreshIfPreviouslySynced() // 不主动弹授权；只有用户以前同步过才刷新 Apple 健康。
        await serverSync.refresh() // 最后获取服务端聚合结果，让数据页看到最新同步状态。
    }

    private func syncAppleHealthAndRefreshServer() async { // 用户主动点击同步时才允许进入授权/同步流程，并在成功链末刷新服务端。
        let accountScope = authManager.accountScope
        let didStart = await XAgeAppleHealthSyncFlow.synchronize(
            accountScope: accountScope,
            configureAccount: configureAppleHealthAccountScope,
            synchronizeHealth: { await appleHealthSync.requestAccessAndSync() },
            refreshServer: { await serverSync.refresh() }
        )
        if !didStart { // 无有效账号时流程不会开始，向 UI 暴露明确失败而不是静默无响应。
            appleHealthSync.status = .failed("无法确认当前账号，请重新登录后再同步 Apple 健康。")
        }
    }

    private func configureAppleHealthAccountScope(_ accountScope: String?) { // MARK: Apple 健康账号隔离与同步：scope 改变时停止旧后台任务并原子重绑全部数据拥有者。
        guard !hasConfiguredAppleHealthAccountScope || configuredAppleHealthAccountScope != accountScope else {
            return
        }
        let coordinator = AppleHealthBackgroundSyncCoordinator.shared // 全局后台协调器一次只能服务当前账号。
        coordinator.stop() // 先停旧观察任务，阻止账号切换期间的迟到回调写入新账号。
        appleHealthSync.setAccountScope(accountScope) // 重置/切换本地健康同步缓存边界。
        serverSync.setAccountScope(accountScope) // 重置/切换服务端快照边界。
        coordinator.startIfEligible(accountScope: accountScope) // 新 scope 有效且满足条件时再恢复后台同步。
        configuredAppleHealthAccountScope = accountScope
        hasConfiguredAppleHealthAccountScope = true
    }

    private func handlePendingExternalImportIfNeeded() { // MARK: 外部报告导入与上传：单槽路由先按 ID 标记已消费，再异步读取安全作用域文件。
        guard let item = externalReportImport.pendingImport else { return }
        externalReportImport.markHandled(item.id) // 先清空同一任务，避免 View 生命周期重入造成重复弹确认页。
        Task { await prepareExternalReportImport(item.url) } // 文件 IO 与安全作用域处理在异步任务中完成。
    }

    private func prepareExternalReportImport(_ url: URL) async { // 获取系统授予的临时文件访问权，读取后无论成功失败都配对释放。
        let access = url.startAccessingSecurityScopedResource() // 普通本地 URL 可能返回 false，但仍可由受控 loader 判断是否可读。
        defer {
            if access {
                url.stopAccessingSecurityScopedResource()
            }
        }

        do {
            let data = try LocalFileDataLoader.read(url) // 唯一允许的本地 Foundation 读取入口会先验证 url.isFileURL。
            guard !data.isEmpty else {
                externalImportError = "文件为空，无法上传。"
                return
            }
            let fileName = url.lastPathComponent.isEmpty ? "外部导入报告" : url.lastPathComponent
            let file = XAgeReportUploadFile(data: data, fileName: fileName)
            pendingExternalUpload = XAgePendingReportUpload( // 只创建待确认模型；真正上传必须等用户在 sheet 点击确认。
                title: "确认导入报告",
                source: "打开方式",
                files: [file]
            )
            selectedSection = .data // 将主界面切到数据模块，为后续报告审核保持一致上下文。
            selectedDataPanelCategory = .reports // 资料菜单/数据目标默认指向报告分类。
        } catch {
            externalImportError = "无法读取该文件：\(error.localizedDescription)"
        }
    }

    private func uploadExternalReports(_ files: [XAgeReportUploadFile], source: String) { // 把确认后的文件映射为上传输入，并绑定当前用户 ID 与 account scope。
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
            await serverSync.refresh() // 上传调用自行报告成功/失败；结束后刷新快照以反映新报告或后台处理状态。
        }
    }

    private static func initialSection() -> XAgeTopSection { // Release 固定从数据页进入；Debug/UI 自动化可用显式参数稳定选择初始模块。
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

private struct XAgeTopBar: View { // MARK: 顶部导航栏交互：只修改父页面 Binding 或回调，不自行持有导航状态。
    @Binding var selected: XAgeTopSection // 与根 TabView.selection 共享，按钮点击会驱动页面切换，横滑也会反向更新选中样式。
    @Binding var showMoreMenu: Bool // 左侧资料按钮设为 true，根页面对应 sheet 才是实际展示 XAgeMoreMenu 的位置。
    let onOpenDataManager: () -> Void // 数据模块右侧“管理”点击事件，由父页面转换为递增请求。
    let onOpenChatHistory: () -> Void // 问答模块右侧历史按钮点击事件。
    let onOpenXAgeInfo: () -> Void // X 年龄模块右侧信息按钮点击事件。

    var body: some View { // 横向排列：左侧资料菜单、中间三段切换器、右侧随当前模块变化的上下文按钮。
        HStack(spacing: 8) {
            Button { // Canvas 点击左侧三横线时从此 action 开始调试。
                XAgeKeyboard.dismiss() // 菜单出现前主动释放聊天/表单焦点，避免键盘覆盖 sheet。
                showMoreMenu = true // 根页面 sheet 监听此 Binding 并展示更多菜单；这里本身不创建页面。
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

            HStack(spacing: 0) { // 中央胶囊是自定义 segmented control，每个枚举 case 占相同宽度。
                ForEach(XAgeTopSection.allCases) { section in
                    Button { // 点击某一段先收键盘，再以弹簧动画更新 selection；TabView 根据相同 tag 切页。
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
                    .background { // 仅选中项绘制半透明高亮层，未选中项保持透明以共享外层胶囊背景。
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

            if selected == .xAge { // 右侧按钮语义随模块变化：X 年龄显示原理说明，其余显示管理或历史。
                Button {
                    onOpenXAgeInfo() // 父页面递增 xAgeInfoRequest，XAgeHealthspanView 观察并展示说明。
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
                Button { // 数据页触发卡片管理；问答页触发历史记录。当前枚举保证不会进入第三种分支。
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
} // Canvas 预览依赖见下方 DEBUG 宿主；正式页面仍由 App 根入口注入真实环境对象。

#if DEBUG
/// 为 Canvas 单独持有 XAGE 主页面所需的环境对象，避免在 `#Preview` 中构造过长的泛型表达式。
private struct XAgeMainPreviewHost: View {
    @StateObject private var authManager = AuthManager.makeTestingInstance()
    @StateObject private var externalReportImport = XAgeExternalReportImportRouter()

    var body: some View {
        XAgeMainView()
            .environmentObject(authManager)
            .environmentObject(externalReportImport)
            .environment(\.healthProfilePreviewFixtureEnabled, true)
    }
}

#Preview("XAGE 主页面") {
    XAgeMainPreviewHost()
}
#endif
