import Foundation
import UIKit
import UserNotifications

/// Manages APNs push notification registration and device token handling.
@MainActor
final class PushNotificationManager: NSObject, ObservableObject {
    static let shared = PushNotificationManager()

    @Published var deviceToken: String?
    @Published var permissionGranted = false

    private override init() {
        super.init()
    }

    static func shouldUseNotificationCenter(arguments: [String]) -> Bool {
        #if DEBUG
        !UIAutomationMode.isEnabled(arguments: arguments)
        #else
        true
        #endif
    }

    static func notificationCenter(
        arguments: [String] = ProcessInfo.processInfo.arguments
    ) -> UNUserNotificationCenter? {
        guard shouldUseNotificationCenter(arguments: arguments) else { return nil }
        return UNUserNotificationCenter.current()
    }

    /// Request notification permission and register for remote notifications.
    func requestPermission(arguments: [String] = ProcessInfo.processInfo.arguments) {
        guard let center = Self.notificationCenter(arguments: arguments) else {
            permissionGranted = false
            return
        }
        center.requestAuthorization(options: [.alert, .badge, .sound]) { granted, error in
            Task { @MainActor in
                self.permissionGranted = granted
                if granted {
                    UIApplication.shared.registerForRemoteNotifications()
                }
                if let error {
                    AppLogger.auth.error("Push permission error: \(error.localizedDescription)")
                }
            }
        }
    }

    /// Called from AppDelegate when APNs returns a device token.
    func didRegisterForRemoteNotifications(deviceToken data: Data) {
        let token = data.map { String(format: "%02x", $0) }.joined()
        self.deviceToken = token
        AppLogger.auth.info("APNs device token: \(token.prefix(20))...")

        // Send to backend
        Task {
            await sendTokenToBackend(token)
        }
    }

    /// Called from AppDelegate on registration failure.
    func didFailToRegisterForRemoteNotifications(error: Error) {
        AppLogger.auth.error("APNs registration failed: \(error.localizedDescription)")
    }

    /// Send the device token to our backend.
    func sendTokenToBackend(_ token: String) async {
        guard Self.shouldUseNotificationCenter(arguments: ProcessInfo.processInfo.arguments) else { return }
        do {
            let body = RegisterDeviceTokenBody(token: token, platform: "ios")
            try await APIService.shared.postVoid("/api/push/device-token", body: body)
            AppLogger.auth.info("Device token registered with backend")
        } catch {
            AppLogger.auth.error("Failed to register device token: \(error.localizedDescription)")
        }
    }

    /// Deactivate token on logout.
    func unregisterToken() async {
        guard Self.shouldUseNotificationCenter(arguments: ProcessInfo.processInfo.arguments) else { return }
        guard let token = deviceToken else { return }
        do {
            try await APIService.shared.deleteVoid("/api/push/device-token?token=\(token)")
            AppLogger.auth.info("Device token unregistered")
        } catch {
            // Best effort
        }
    }
}

// MARK: - Request/Response

struct RegisterDeviceTokenBody: Encodable {
    let token: String
    let platform: String
}
