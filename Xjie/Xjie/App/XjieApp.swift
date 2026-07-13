import SwiftUI

@main
/// App 的总入口。这里持有需要贯穿整个进程的服务对象，并根据登录态决定展示登录页还是新版 XAGE 主界面。
/// 启动动画、版本更新、推送权限和外部文件导入都放在根层处理，避免它们随业务页面切换而重复创建。
struct XjieApp: App {
    // UIApplication 生命周期代理，以及需要在多个页面间共享的全局服务。
    // 使用 StateObject 可确保 SwiftUI 重算根视图时仍保留同一实例和已有状态。
    @UIApplicationDelegateAdaptor(AppDelegate.self) var appDelegate
    @StateObject private var authManager = AuthManager.shared
    @StateObject private var networkMonitor = NetworkMonitor.shared
    @StateObject private var pushManager = PushNotificationManager.shared
    @StateObject private var appUpdate = AppUpdateService.shared
    @StateObject private var externalReportImport = XAgeExternalReportImportRouter()
    @Environment(\.openURL) private var openURL
    @State private var showSplash = true
    @State private var didRequestPushPermission = false

    var body: some Scene {
        WindowGroup {
            ZStack {
                // 登录态是根页面分流的唯一依据：登录成功后进入 XAGE，退出或注销后立即回到登录页。
                Group {
                    if authManager.isLoggedIn {
                        MainTabView()
                            .onAppear {
                                guard !Self.isRunningUnitTests else { return }
                                Task { await FeatureFlagService.shared.fetchIfNeeded() }
                            }
                    } else {
                        LoginView()
                    }
                }
                // 通过环境对象向下传递账号、网络和外部导入状态，子页面无需自行创建或层层传参。
                .environmentObject(authManager)
                .environmentObject(networkMonitor)
                .environmentObject(externalReportImport)

                // Splash 作为最高层覆盖视图；结束后仅移除覆盖层，不会重建下方已经选定的业务根页面。
                if showSplash {
                    SplashView { showSplash = false }
                        .transition(.opacity)
                        .zIndex(1)
                }
            }
            .preferredColorScheme(.light)
            // 推送授权延后到 Splash 消失且用户已登录之后，避免系统弹窗打断启动体验或出现在登录页。
            .onChange(of: showSplash) { _, visible in
                requestPushPermissionAfterSplashIfNeeded(splashVisible: visible)
            }
            .onChange(of: authManager.isLoggedIn) { _, _ in
                requestPushPermissionAfterSplashIfNeeded(splashVisible: showSplash)
            }
            .task {
                // 更新检查属于 App 生命周期任务。单元测试和显式关闭该能力的 Debug 场景会跳过网络请求。
                #if DEBUG
                guard !Self.isRunningUnitTests,
                      !Self.debugFlag("XJIE_DISABLE_APP_UPDATE_CHECK")
                else { return }
                #endif
                await appUpdate.checkIfNeeded()
            }
            .onOpenURL { url in
                // 系统“用小捷打开”只负责把 URL 交给路由暂存；实际读取、确认和上传由 XAgeMainView 完成。
                externalReportImport.receive(url)
            }
            .alert(item: $appUpdate.pendingUpdate) { info in
                if info.shouldForce {
                    return Alert(
                        title: Text(info.title),
                        message: Text(updateMessage(info)),
                        dismissButton: .default(Text("立即更新")) {
                            appUpdate.openUpdate(info, openURL: openURL)
                            appUpdate.pendingUpdate = info
                        }
                    )
                }
                return Alert(
                    title: Text(info.title),
                    message: Text(updateMessage(info)),
                    primaryButton: .default(Text("立即更新")) {
                        appUpdate.openUpdate(info, openURL: openURL)
                    },
                    secondaryButton: .cancel(Text("稍后")) {
                        appUpdate.dismiss(info)
                    }
                )
            }
        }
    }

    private static var isRunningUnitTests: Bool {
        #if DEBUG
        NSClassFromString("XCTestCase") != nil
        #else
        false
        #endif
    }

    /// 在启动遮罩结束后按需请求推送权限，避免权限弹窗与启动动画重叠。
    private func requestPushPermissionAfterSplashIfNeeded(splashVisible: Bool) {
        #if DEBUG
        guard !Self.isRunningUnitTests,
              !Self.debugFlag("XJIE_DISABLE_PUSH_PERMISSION")
        else { return }
        #endif
        // 三个条件同时满足才发起请求，并用本地标记保证本次 App 生命周期内最多触发一次。
        guard !splashVisible, authManager.isLoggedIn, !didRequestPushPermission else { return }
        didRequestPushPermission = true
        pushManager.requestPermission()
    }

    /// 根据版本检查结果拼装面向用户的更新提示文案。
    private func updateMessage(_ info: AppUpdateCheck) -> String {
        let versionLine = "最新版本：\(info.latest_version)(\(info.latest_build))"
        let body = [info.message, info.changelog].filter { !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
        return ([versionLine] + body).joined(separator: "\n\n")
    }

    #if DEBUG
    /// 读取启动参数中的调试开关，并兼容显式布尔值写法。
    private static func debugFlag(_ key: String) -> Bool {
        if let value = ProcessInfo.processInfo.environment[key], ["1", "true", "YES", "yes"].contains(value) {
            return true
        }
        return ProcessInfo.processInfo.arguments.contains(key)
    }
    #endif
}

struct XAgeExternalReportImport: Identifiable, Equatable {
    let id = UUID()
    let url: URL
}

@MainActor
/// 外部报告导入的单槽路由。
/// 根入口写入待处理 URL，XAGE 页面消费后按 ID 清空，避免 SwiftUI 生命周期切换导致同一文件重复弹出确认页。
final class XAgeExternalReportImportRouter: ObservableObject {
    @Published private(set) var pendingImport: XAgeExternalReportImport?

    /// 接收外部文件 URL，并将其封装为等待 XAGE 页面消费的导入任务。
    func receive(_ url: URL) {
        pendingImport = XAgeExternalReportImport(url: url)
    }

    /// 在指定导入任务处理完成后清空暂存状态，避免同一文件被重复消费。
    func markHandled(_ importID: UUID) {
        // 只有当前仍指向同一导入任务时才清空，防止较早任务的异步回调误删后来收到的新文件。
        guard pendingImport?.id == importID else { return }
        pendingImport = nil
    }
}
