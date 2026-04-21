import SwiftUI

/// 登录页面 — 对应小程序 pages/login/login
struct LoginView: View {
    @EnvironmentObject var authManager: AuthManager
    @StateObject private var vm = LoginViewModel()

    var body: some View {
        ScrollView {
            VStack(spacing: 24) {
                // Logo 区域
                logoArea

                // 受试者 ID 登录（科研内测专用）
                // 注: iOS 版仅支持受试者 ID 与邮箱两种登录方式
                modeSwitch

                if vm.mode == .subject {
                    subjectSection
                } else {
                    emailSection
                }
            }
            .padding(24)
        }
        .background(Color.appBackground)
        .task { await vm.loadSubjects() }
        .alert("提示", isPresented: $vm.showAlert) {
            Button("确定", role: .cancel) {}
        } message: {
            Text(vm.alertMessage)
        }
    }

    // MARK: - Logo

    private var logoArea: some View {
        VStack(spacing: 12) {
            ZStack {
                Circle()
                    .fill(
                        LinearGradient(
                            colors: [Color.appGradientStart, Color.appGradientEnd],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        )
                    )
                    .frame(width: 80, height: 80)
                Text("XJ+")
                    .font(.system(size: 28, weight: .bold))
                    .foregroundColor(.white)
            }
            Text("Xjie")
                .font(.title).bold()
            Text("智能代谢健康管理")
                .font(.subheadline)
                .foregroundColor(.appMuted)
        }
        .padding(.top, 40)
    }

    // MARK: - 模式切换

    private var modeSwitch: some View {
        VStack(spacing: 12) {
            Divider()
            Button {
                vm.mode = vm.mode == .subject ? .email : .subject
            } label: {
                Text(vm.mode == .subject ? "使用手机号登录" : "使用受试者 ID 登录")
                    .foregroundColor(.appPrimary)
                    .font(.subheadline)
            }
        }
    }

    // MARK: - 受试者登录

    private var subjectSection: some View {
        VStack(spacing: 16) {
            Text("选择受试者")
                .font(.headline)
                .frame(maxWidth: .infinity, alignment: .leading)

            if vm.subjects.isEmpty {
                Text("暂无可用受试者")
                    .foregroundColor(.appMuted)
                    .font(.subheadline)
            } else {
                ScrollView {
                    VStack(spacing: 8) {
                        ForEach(vm.subjects) { subject in
                            Button {
                                vm.selectedSubject = subject.subject_id
                            } label: {
                                HStack {
                                    Text(subject.subject_id)
                                        .foregroundColor(.appText)
                                    Spacer()
                                    Text(subject.cohort == "cgm" ? "CGM" : "肝脏")
                                        .font(.caption)
                                        .padding(.horizontal, 8)
                                        .padding(.vertical, 4)
                                        .background(subject.cohort == "cgm" ? Color.appPrimary.opacity(0.1) : Color.appSuccess.opacity(0.1))
                                        .foregroundColor(subject.cohort == "cgm" ? .appPrimary : .appSuccess)
                                        .cornerRadius(4)
                                }
                                .padding(12)
                                .background(
                                    RoundedRectangle(cornerRadius: 8)
                                        .stroke(vm.selectedSubject == subject.subject_id ? Color.appPrimary : Color.gray.opacity(0.2), lineWidth: vm.selectedSubject == subject.subject_id ? 2 : 1)
                                )
                            }
                        }
                    }
                }
                .frame(maxHeight: 250)
            }

            Button {
                Task { await vm.loginSubject(authManager: authManager) }
            } label: {
                Text("登录")
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 14)
                    .background(
                        LinearGradient(colors: [Color.appGradientStart, Color.appGradientEnd], startPoint: .topLeading, endPoint: .bottomTrailing)
                    )
                    .foregroundColor(.white)
                    .cornerRadius(8)
            }
            .disabled(vm.selectedSubject.isEmpty || vm.loading)
            .opacity(vm.selectedSubject.isEmpty ? 0.5 : 1)
        }
    }

    // MARK: - 手机号登录

    private var emailSection: some View {
        VStack(spacing: 16) {
            VStack(alignment: .leading, spacing: 6) {
                Text("手机号").font(.subheadline).foregroundColor(.appMuted)
                TextField("请输入手机号", text: $vm.phone)
                    .textFieldStyle(.roundedBorder)
                    .keyboardType(.phonePad)
                    .textContentType(.telephoneNumber)
                    .textInputAutocapitalization(.never)
            }

            if vm.isSignup {
                VStack(alignment: .leading, spacing: 6) {
                    Text("用户名").font(.subheadline).foregroundColor(.appMuted)
                    TextField("请输入用户名", text: $vm.username)
                        .textFieldStyle(.roundedBorder)
                        .textContentType(.username)
                        .textInputAutocapitalization(.never)
                }
            }

            VStack(alignment: .leading, spacing: 6) {
                Text("密码").font(.subheadline).foregroundColor(.appMuted)
                SecureField("至少 8 位", text: $vm.password)
                    .textFieldStyle(.roundedBorder)
                    .textContentType(vm.isSignup ? .newPassword : .password)
            }

            Button {
                Task { await vm.loginPhone(authManager: authManager) }
            } label: {
                HStack {
                    if vm.loading { ProgressView().tint(.white) }
                    Text(vm.isSignup ? "注册" : "登录")
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 14)
                .background(
                    LinearGradient(colors: [Color.appGradientStart, Color.appGradientEnd], startPoint: .topLeading, endPoint: .bottomTrailing)
                )
                .foregroundColor(.white)
                .cornerRadius(8)
            }
            .disabled(vm.loading)

            Button {
                vm.isSignup.toggle()
            } label: {
                Text(vm.isSignup ? "已有账号？去登录" : "没有账号？去注册")
                    .foregroundColor(.appPrimary)
                    .font(.subheadline)
            }
        }
    }
}

