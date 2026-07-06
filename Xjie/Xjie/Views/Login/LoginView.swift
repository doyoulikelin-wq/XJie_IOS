import SwiftUI
import UIKit

/// 登录页面 — 对应小程序 pages/login/login
struct LoginView: View {
    @EnvironmentObject var authManager: AuthManager
    @StateObject private var vm = LoginViewModel()
    @State private var showReset = false

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
        .sheet(isPresented: $showReset) {
            PasswordResetSheet()
        }
    }

    // MARK: - Logo

    private var logoArea: some View {
        VStack(spacing: 12) {
            Image("Logo")
                .resizable()
                .scaledToFill()
                .frame(width: 96, height: 96)
                .clipShape(Circle())
                .accessibilityLabel("小捷 Logo")

            Text("小捷")
                .font(.title).bold()
                .foregroundColor(.appText)

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

                signupProfileSection
            }

            VStack(alignment: .leading, spacing: 6) {
                Text("密码").font(.subheadline).foregroundColor(.appMuted)
                PasswordRevealField(
                    "至少 8 位",
                    text: $vm.password,
                    textContentType: vm.isSignup ? .newPassword : .password
                )
            }

            if vm.isSignup {
                onboardingNeedsSection
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

            if !vm.isSignup {
                Button { showReset = true } label: {
                    Text("忘记密码？")
                        .foregroundColor(.appPrimary)
                        .font(.caption)
                }
            }
        }
    }

    private var signupProfileSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("基本数据").font(.subheadline.bold()).foregroundColor(.appText)
            Picker("性别", selection: $vm.sex) {
                Text("女").tag("female")
                Text("男").tag("male")
                Text("其他").tag("other")
            }
            .pickerStyle(.segmented)
            HStack(spacing: 8) {
                TextField("年龄", text: $vm.age)
                    .keyboardType(.numberPad)
                TextField("身高 cm", text: $vm.heightCm)
                    .keyboardType(.decimalPad)
                TextField("体重 kg", text: $vm.weightKg)
                    .keyboardType(.decimalPad)
            }
            .textFieldStyle(.roundedBorder)
        }
    }

    private var onboardingNeedsSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("最后一步：健康需求").font(.subheadline.bold()).foregroundColor(.appText)
            Picker("目标", selection: $vm.onboardingTarget) {
                ForEach(["控糖稳定", "减重控脂", "改善睡眠", "提升体能", "综合健康"], id: \.self) { item in
                    Text(item).tag(item)
                }
            }
            .pickerStyle(.menu)

            LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 8) {
                onboardingChip("fitness", "健身")
                onboardingChip("diet_control", "饮食控制")
                onboardingChip("sleep", "睡眠")
                onboardingChip("hydration", "饮水")
                onboardingChip("medication", "用药")
                onboardingChip("glucose", "血糖追踪")
            }

            if vm.onboardingContents.contains("medication") {
                Toggle("确认有用药需求", isOn: $vm.medicationNeeded)
                    .font(.caption)
            }
            Toggle("注册后帮我生成首个健康计划", isOn: $vm.onboardingGeneratePlan)
                .font(.caption)
            Text("这些选择会保存到账号中，用于首页代谢状态、计划生成和后续 Agent 干预。")
                .font(.caption)
                .foregroundColor(.appMuted)
        }
        .padding(12)
        .background(Color.appCardBg)
        .clipShape(RoundedRectangle(cornerRadius: 12))
    }

    private func onboardingChip(_ key: String, _ label: String) -> some View {
        let selected = vm.onboardingContents.contains(key)
        return Button {
            if selected {
                vm.onboardingContents.remove(key)
                if key == "medication" { vm.medicationNeeded = false }
            } else {
                vm.onboardingContents.insert(key)
            }
        } label: {
            Text(label)
                .font(.caption.bold())
                .frame(maxWidth: .infinity)
                .padding(.vertical, 8)
                .background(selected ? Color.appPrimary.opacity(0.14) : Color.gray.opacity(0.08))
                .foregroundColor(selected ? .appPrimary : .appText)
                .clipShape(RoundedRectangle(cornerRadius: 8))
        }
        .buttonStyle(.plain)
    }
}

struct PasswordRevealField: View {
    let placeholder: String
    @Binding var text: String
    var textContentType: UITextContentType?
    @State private var isVisible = false

    init(_ placeholder: String, text: Binding<String>, textContentType: UITextContentType? = nil) {
        self.placeholder = placeholder
        self._text = text
        self.textContentType = textContentType
    }

    var body: some View {
        HStack(spacing: 8) {
            Group {
                if isVisible {
                    TextField(placeholder, text: $text)
                } else {
                    SecureField(placeholder, text: $text)
                }
            }
            .textContentType(textContentType)
            .textInputAutocapitalization(.never)
            .autocorrectionDisabled()

            Button(isVisible ? "隐藏" : "显示密码") {
                isVisible.toggle()
            }
            .font(.caption2.bold())
            .foregroundColor(.appPrimary)
            .buttonStyle(.borderless)
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 8)
        .background(Color(.systemBackground))
        .overlay(
            RoundedRectangle(cornerRadius: 7)
                .stroke(Color(.separator).opacity(0.45), lineWidth: 1)
        )
        .clipShape(RoundedRectangle(cornerRadius: 7))
    }
}
