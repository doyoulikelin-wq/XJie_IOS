import Foundation
import SwiftUI

@MainActor
final class AppUpdateService: ObservableObject {
    static let shared = AppUpdateService()

    @Published var pendingUpdate: AppUpdateCheck?

    private let api: APIServiceProtocol
    private var checkedThisLaunch = false
    private let dismissedBuildKey = "app_update.dismissed_ios_build"

    init(api: APIServiceProtocol = APIService.shared) {
        self.api = api
    }

    func checkIfNeeded() async {
        guard !checkedThisLaunch else { return }
        checkedThisLaunch = true
        await check()
    }

    func check() async {
        do {
            let version = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "0"
            let buildString = Bundle.main.infoDictionary?["CFBundleVersion"] as? String ?? "0"
            let build = Int(buildString) ?? 0
            let path = "/api/app-version?platform=ios&version=\(version)&build=\(build)"
            let info: AppUpdateCheck = try await api.get(path)
            guard info.update_available || info.shouldForce else { return }
            if !info.shouldForce,
               UserDefaults.standard.integer(forKey: dismissedBuildKey) == info.latest_build {
                return
            }
            pendingUpdate = info
        } catch {
            print("[AppUpdateService] check failed: \(error.localizedDescription)")
        }
    }

    func dismiss(_ info: AppUpdateCheck) {
        guard !info.shouldForce else { return }
        UserDefaults.standard.set(info.latest_build, forKey: dismissedBuildKey)
        pendingUpdate = nil
    }

    func openUpdate(_ info: AppUpdateCheck, openURL: OpenURLAction) {
        guard let raw = info.updateURLString, let url = URL(string: raw) else { return }
        openURL(url)
    }
}
