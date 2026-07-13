import UIKit
import UserNotifications

/// AppDelegate to handle APNs device token registration callbacks.
class AppDelegate: NSObject, UIApplicationDelegate, UNUserNotificationCenterDelegate {
    static func shouldConfigureSystemServices(
        arguments: [String],
        isUnitTestHost: Bool
    ) -> Bool {
        guard !isUnitTestHost else { return false }
        #if DEBUG
        return !UIAutomationMode.isEnabled(arguments: arguments)
        #else
        return true
        #endif
    }

    static var shouldStartAppleHealthBackgroundSync: Bool {
        shouldConfigureSystemServices(
            arguments: ProcessInfo.processInfo.arguments,
            isUnitTestHost: NSClassFromString("XCTestCase") != nil
        )
    }

    func application(
        _ application: UIApplication,
        didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil
    ) -> Bool {
        guard Self.shouldStartAppleHealthBackgroundSync else { return true }
        // 关键：注册通知代理；UI 自动化和单元测试在边界内直接禁用系统副作用。
        PushNotificationManager.notificationCenter()?.delegate = self
        Task { @MainActor in
            AppleHealthBackgroundSyncCoordinator.shared.startIfEligible(
                accountScope: AuthManager.shared.accountScope
            )
        }
        return true
    }

    func application(
        _ application: UIApplication,
        didRegisterForRemoteNotificationsWithDeviceToken deviceToken: Data
    ) {
        Task { @MainActor in
            PushNotificationManager.shared.didRegisterForRemoteNotifications(deviceToken: deviceToken)
        }
    }

    func application(
        _ application: UIApplication,
        didFailToRegisterForRemoteNotificationsWithError error: Error
    ) {
        Task { @MainActor in
            PushNotificationManager.shared.didFailToRegisterForRemoteNotifications(error: error)
        }
    }

    // MARK: - UNUserNotificationCenterDelegate

    /// app 在前台时收到本地/远程通知，仍然展示横幅 + 声音 + 角标。
    func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        willPresent notification: UNNotification,
        withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void
    ) {
        completionHandler([.banner, .list, .sound, .badge])
    }

    /// 用户点击通知时的处理（保留默认即可）。
    func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        didReceive response: UNNotificationResponse,
        withCompletionHandler completionHandler: @escaping () -> Void
    ) {
        completionHandler()
    }
}
