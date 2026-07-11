import UIKit
import UserNotifications

/// AppDelegate to handle APNs device token registration callbacks.
class AppDelegate: NSObject, UIApplicationDelegate, UNUserNotificationCenterDelegate {
    static var shouldStartAppleHealthBackgroundSync: Bool {
        NSClassFromString("XCTestCase") == nil
    }

    func application(
        _ application: UIApplication,
        didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil
    ) -> Bool {
        // 关键：注册 UNUserNotificationCenter 代理，让 app 在前台时也能弹横幅 + 出声
        UNUserNotificationCenter.current().delegate = self
        if Self.shouldStartAppleHealthBackgroundSync {
            Task { @MainActor in
                AppleHealthBackgroundSyncCoordinator.shared.startIfEligible(
                    accountScope: AuthManager.shared.accountScope
                )
            }
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
