import Foundation

@MainActor
final class LoginViewModel: ObservableObject {
    enum LoginMode { case subject, email }

    @Published var mode: LoginMode = .subject
    @Published var subjects: [SubjectItem] = []
    @Published var loading = false
    @Published var selectedSubject = ""
    @Published var phone = ""
    @Published var username = ""
    @Published var password = ""
    @Published var isSignup = true
    @Published var showAlert = false
    @Published var alertMessage = ""
    @Published var errorMessage: String?

    private let api: APIServiceProtocol

    init(api: APIServiceProtocol = APIService.shared) {
        self.api = api
    }

    func loadSubjects() async {
        do {
            subjects = try await api.get("/api/auth/subjects")
        } catch {
            // 后端未启动时静默处理，不弹窗
            errorMessage = error.localizedDescription
        }
    }

    func loginSubject(authManager: AuthManager) async {
        guard !selectedSubject.isEmpty else {
            alertMessage = "请选择受试者"; showAlert = true; return
        }
        loading = true
        defer { loading = false }
        do {
            let res: AuthResponse = try await api.post(
                "/api/auth/login-subject",
                body: LoginSubjectBody(subject_id: selectedSubject)
            )
            authManager.setAuth(accessToken: res.access_token, refreshToken: res.refresh_token ?? "")
            authManager.setSubject(selectedSubject)
        } catch {
            alertMessage = error.localizedDescription; showAlert = true
        }
    }

    func loginPhone(authManager: AuthManager) async {
        phone = phone.replacingOccurrences(of: " ", with: "")
        guard !phone.isEmpty, !password.isEmpty else {
            alertMessage = "请填写手机号和密码"; showAlert = true; return
        }
        guard !password.contains(" ") else {
            alertMessage = "请勿输入空格等特殊字符"; showAlert = true; return
        }
        guard password.count >= 8 else {
            alertMessage = "密码至少 8 位"; showAlert = true; return
        }
        if isSignup && username.isEmpty {
            alertMessage = "请填写用户名"; showAlert = true; return
        }
        loading = true
        defer { loading = false }
        do {
            let path = isSignup ? "/api/auth/signup" : "/api/auth/login"
            let body = LoginPhoneBody(phone: phone, username: isSignup ? username : phone, password: password)
            let res: AuthResponse = try await api.post(path, body: body)
            authManager.setAuth(accessToken: res.access_token, refreshToken: res.refresh_token ?? "")
            // 自动开启 AI 聊天授权
            let _: ConsentResponse? = try? await api.patch("/api/users/consent", body: ConsentUpdate(allow_ai_chat: true))
        } catch {
            alertMessage = error.localizedDescription; showAlert = true
        }
    }
}
