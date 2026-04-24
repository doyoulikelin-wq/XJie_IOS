import Foundation

@MainActor
final class SettingsViewModel: ObservableObject {
    @Published var loading = false
    @Published var user: UserInfo?
    @Published var settings: UserSettings?
    @Published var showLogoutAlert = false
    @Published var errorMessage: String?

    private let api: APIServiceProtocol

    init(api: APIServiceProtocol = APIService.shared) {
        self.api = api
    }

    func fetchData() async {
        loading = true
        defer { loading = false }
        async let u: UserInfo? = try? await api.get("/api/users/me")
        async let s: UserSettings? = try? await api.get("/api/users/settings")
        let fetchedUser = await u
        let fetchedSettings = await s
        guard !Task.isCancelled else { return }
        user = fetchedUser
        settings = fetchedSettings
        // 同步血糖单位到本地全局偏好
        if let raw = fetchedSettings?.glucose_unit,
           let unit = GlucoseUnit(rawValue: raw),
           UnitsSettings.shared.glucoseUnit != unit {
            UnitsSettings.shared.glucoseUnit = unit
        }
    }

    func updateGlucoseUnit(_ unit: GlucoseUnit) async {
        // 乐观更新本地，后台失败不回滚（单位切换是纯显示偏好）
        UnitsSettings.shared.glucoseUnit = unit
        do {
            try await api.patchVoid(
                "/api/users/settings",
                body: UpdateSettingsBody(intervention_level: nil, glucose_unit: unit.rawValue)
            )
            await fetchData()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func updateLevel(_ level: String) async {
        do {
            try await api.patchVoid("/api/users/settings", body: UpdateSettingsBody(intervention_level: level))
            await fetchData()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func toggleAiChat() async {
        let current = user?.consent?.allow_ai_chat ?? false
        do {
            try await api.patchVoid("/api/users/consent", body: UpdateConsentBody(allow_ai_chat: !current, allow_data_upload: nil))
            await fetchData()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func toggleDataUpload() async {
        let current = user?.consent?.allow_data_upload ?? false
        do {
            try await api.patchVoid("/api/users/consent", body: UpdateConsentBody(allow_ai_chat: nil, allow_data_upload: !current))
            await fetchData()
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
