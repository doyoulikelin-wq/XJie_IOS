import Foundation

@MainActor
final class LoginViewModel: ObservableObject {
    enum LoginMode { case subject, email }

    @Published var mode: LoginMode = .email
    @Published var subjects: [SubjectItem] = []
    @Published var loading = false
    @Published var selectedSubject = ""
    @Published var phone = ""
    @Published var username = ""
    @Published var password = ""
    @Published var sex = "female"
    @Published var age = "30"
    @Published var heightCm = "165"
    @Published var weightKg = "55"
    @Published var onboardingTarget = "控糖稳定"
    @Published var onboardingContents: Set<String> = ["fitness", "diet_control"]
    @Published var onboardingGeneratePlan = true
    @Published var medicationNeeded = false
    @Published var isSignup = false
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
        guard !phone.isEmpty, !password.isEmpty else {
            alertMessage = "请填写手机号和密码"; showAlert = true; return
        }
        guard password.count >= 8 else {
            alertMessage = "密码至少 8 位"; showAlert = true; return
        }
        if isSignup && username.isEmpty {
            alertMessage = "请填写用户名"; showAlert = true; return
        }
        let ageValue = Int(age)
        let heightValue = Double(heightCm)
        let weightValue = Double(weightKg)
        if isSignup && (ageValue == nil || heightValue == nil || weightValue == nil) {
            alertMessage = "请完整填写年龄、身高和体重"; showAlert = true; return
        }
        loading = true
        defer { loading = false }
        do {
            let path = isSignup ? "/api/auth/signup" : "/api/auth/login"
            let body = LoginPhoneBody(
                phone: phone,
                username: isSignup ? username : phone,
                password: password,
                sex: isSignup ? sex : nil,
                age: isSignup ? ageValue : nil,
                height_cm: isSignup ? heightValue : nil,
                weight_kg: isSignup ? weightValue : nil
            )
            let res: AuthResponse = try await api.post(path, body: body)
            authManager.setAuth(accessToken: res.access_token, refreshToken: res.refresh_token ?? "")
            // 自动开启 AI 聊天授权
            let _: ConsentResponse? = try? await api.patch("/api/users/consent", body: ConsentUpdate(allow_ai_chat: true))
            if isSignup {
                let contents = Array(onboardingContents).sorted()
                try? await api.putVoid(
                    "/api/users/onboarding",
                    body: OnboardingNeedsRequest(
                        target: onboardingTarget,
                        contents: contents,
                        generate_plan: onboardingGeneratePlan,
                        completed: true
                    )
                )
                if onboardingGeneratePlan {
                    let request = HealthPlanQuestionnaireRequest(
                        target: onboardingTarget,
                        duration_days: 7,
                        frequency: "daily",
                        contents: contents.filter { $0 != "glucose" && $0 != "weight" && $0 != "blood_pressure" },
                        medication_needed: contents.contains("medication") && medicationNeeded,
                        notes: "注册末步生成的首个健康计划",
                        title: "\(onboardingTarget)健康计划"
                    )
                    let _: HealthPlanDetail? = try? await api.post("/api/health-plans/questionnaire", body: request)
                }
            }
        } catch {
            alertMessage = error.localizedDescription; showAlert = true
        }
    }
}
