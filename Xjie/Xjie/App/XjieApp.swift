import SwiftUI

@main
struct XjieApp: App {
    @UIApplicationDelegateAdaptor(AppDelegate.self) var appDelegate
    @StateObject private var authManager = AuthManager.shared
    @StateObject private var networkMonitor = NetworkMonitor.shared
    @StateObject private var pushManager = PushNotificationManager.shared
    @StateObject private var appUpdate = AppUpdateService.shared
    @Environment(\.openURL) private var openURL
    @State private var showSplash = true
    @State private var didRequestPushPermission = false

    var body: some Scene {
        WindowGroup {
            ZStack {
                Group {
                    if authManager.isLoggedIn {
                        MainTabView()
                            .onAppear {
                                Task { await FeatureFlagService.shared.fetchIfNeeded() }
                            }
                    } else {
                        LoginView()
                    }
                }
                .environmentObject(authManager)
                .environmentObject(networkMonitor)

                if showSplash {
                    SplashView { showSplash = false }
                        .transition(.opacity)
                        .zIndex(1)
                }
            }
            .onChange(of: showSplash) { _, visible in
                requestPushPermissionAfterSplashIfNeeded(splashVisible: visible)
            }
            .onChange(of: authManager.isLoggedIn) { _, _ in
                requestPushPermissionAfterSplashIfNeeded(splashVisible: showSplash)
            }
            .task {
                await appUpdate.checkIfNeeded()
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

    private func requestPushPermissionAfterSplashIfNeeded(splashVisible: Bool) {
        guard !splashVisible, authManager.isLoggedIn, !didRequestPushPermission else { return }
        didRequestPushPermission = true
        pushManager.requestPermission()
    }

    private func updateMessage(_ info: AppUpdateCheck) -> String {
        let versionLine = "最新版本：\(info.latest_version)(\(info.latest_build))"
        let body = [info.message, info.changelog].filter { !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
        return ([versionLine] + body).joined(separator: "\n\n")
    }
}
