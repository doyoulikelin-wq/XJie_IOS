import Foundation

@MainActor
final class ChangePasswordViewModel: ObservableObject {
    @Published var oldPassword = ""
    @Published var newPassword = ""
    @Published var confirmPassword = ""
    @Published var loading = false
    @Published var savedOk = false
    @Published var errorMessage: String?

    private let api: APIServiceProtocol

    init(api: APIServiceProtocol = APIService.shared) {
        self.api = api
    }

    func submit() async {
        guard !oldPassword.isEmpty else { errorMessage = "请输入旧密码"; return }
        guard newPassword.count >= 8 else { errorMessage = "新密码至少 8 位"; return }
        guard newPassword == confirmPassword else { errorMessage = "两次输入的新密码不一致"; return }
        guard newPassword != oldPassword else { errorMessage = "新密码不能与旧密码相同"; return }
        loading = true
        defer { loading = false }
        do {
            try await api.postVoid("/api/auth/password/change",
                                   body: PasswordChangeBody(old_password: oldPassword, new_password: newPassword))
            savedOk = true
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}

@MainActor
final class PasswordResetViewModel: ObservableObject {
    @Published var phone = ""
    @Published var code = ""
    @Published var newPassword = ""
    @Published var sending = false
    @Published var loading = false
    @Published var resetOk = false
    @Published var infoMessage: String?
    @Published var errorMessage: String?

    private let api: APIServiceProtocol

    init(api: APIServiceProtocol = APIService.shared) {
        self.api = api
    }

    func requestCode() async {
        guard phone.count == 11 else { errorMessage = "请输入 11 位手机号"; return }
        sending = true
        defer { sending = false }
        do {
            let _: SimpleOk = try await api.post(
                "/api/auth/password/reset/request",
                body: PasswordResetRequestBody(phone: phone),
                timeout: nil
            )
            infoMessage = "验证码已发送（演示环境会在控制台输出）"
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func confirm() async {
        guard phone.count == 11 else { errorMessage = "请输入 11 位手机号"; return }
        guard code.count >= 4 else { errorMessage = "请输入验证码"; return }
        guard newPassword.count >= 8 else { errorMessage = "新密码至少 8 位"; return }
        loading = true
        defer { loading = false }
        do {
            let _: SimpleOk = try await api.post(
                "/api/auth/password/reset/confirm",
                body: PasswordResetConfirmBody(phone: phone, code: code, new_password: newPassword),
                timeout: nil
            )
            resetOk = true
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
