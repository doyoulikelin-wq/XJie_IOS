import SwiftUI
import UIKit

private enum LoginFocusField: Hashable {
    case phone
    case username
    case age
    case height
    case weight
    case password
}

/// 登录页面 — 对应小程序 pages/login/login
struct LoginView: View {
    @EnvironmentObject var authManager: AuthManager
    @StateObject private var vm = LoginViewModel()
    @State private var showReset = false
    @State private var isSubmittingCredentials = false
    @State private var isSubmittingSubject = false
    @FocusState private var focusedField: LoginFocusField?

    var body: some View {
        ScrollView {
            VStack(spacing: 24) {
                // Logo 区域
                logoArea

                #if DEBUG
                debugValidationEntry
                #endif

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
        .scrollDismissesKeyboard(.interactively)
        .background(Color.appBackground)
        .toolbar {
            ToolbarItemGroup(placement: .keyboard) {
                Button("上一项") { moveFocus(by: -1) }
                    .disabled(!canMoveFocus(by: -1))
                Button("下一项") { moveFocus(by: 1) }
                    .disabled(!canMoveFocus(by: 1))
                Spacer()
                Button("完成") { dismissKeyboard() }
            }
        }
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
                dismissKeyboard()
                vm.mode = vm.mode == .subject ? .email : .subject
            } label: {
                Text(vm.mode == .subject ? "使用手机号登录" : "使用受试者 ID 登录")
                    .foregroundColor(.appPrimary)
                    .font(.subheadline)
            }
            .accessibilityIdentifier("login.mode.switch")
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
                guard !vm.loading, !isSubmittingSubject else { return }
                isSubmittingSubject = true
                Task {
                    await vm.loginSubject(authManager: authManager)
                    isSubmittingSubject = false
                }
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
            .disabled(vm.selectedSubject.isEmpty || vm.loading || isSubmittingSubject)
            .opacity(vm.selectedSubject.isEmpty ? 0.5 : 1)
        }
    }

    #if DEBUG
    private var debugValidationEntry: some View {
        Button {
            authManager.startUIValidationSession()
        } label: {
            Text("UI 验证入口")
                .font(.subheadline.bold())
                .frame(maxWidth: .infinity)
                .padding(.vertical, 12)
                .background(
                    LinearGradient(colors: [Color.appGradientStart.opacity(0.88), Color.appGradientEnd.opacity(0.88)], startPoint: .topLeading, endPoint: .bottomTrailing)
                )
                .foregroundColor(.white)
                .cornerRadius(10)
        }
        .accessibilityIdentifier("xjie.debug.uiValidationLogin")
    }
    #endif

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
                    .focused($focusedField, equals: .phone)
                    .submitLabel(.next)
                    .onSubmit { moveFocus(by: 1) }
                    .accessibilityIdentifier("login.phone")
            }

            if vm.isSignup {
                VStack(alignment: .leading, spacing: 6) {
                    Text("用户名").font(.subheadline).foregroundColor(.appMuted)
                    TextField("请输入用户名", text: $vm.username)
                        .textFieldStyle(.roundedBorder)
                        .textContentType(.username)
                        .textInputAutocapitalization(.never)
                        .focused($focusedField, equals: .username)
                        .submitLabel(.next)
                        .onSubmit { moveFocus(by: 1) }
                        .accessibilityIdentifier("login.username")
                }

                signupProfileSection
            }

            VStack(alignment: .leading, spacing: 6) {
                Text("密码").font(.subheadline).foregroundColor(.appMuted)
                PasswordRevealField(
                    "至少 8 位",
                    text: $vm.password,
                    textContentType: vm.isSignup ? .newPassword : .password,
                    focus: passwordFocusBinding,
                    submitLabel: vm.isSignup ? .done : .go,
                    onSubmit: submitCredentials
                )
                .accessibilityIdentifier("login.password")
            }

            if vm.isSignup {
                onboardingNeedsSection
            }

            Button {
                submitCredentials()
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
            .accessibilityIdentifier("login.submit")
            .disabled(vm.loading || isSubmittingCredentials)

            Button {
                dismissKeyboard()
                vm.isSignup.toggle()
            } label: {
                Text(vm.isSignup ? "已有账号？去登录" : "没有账号？去注册")
                    .foregroundColor(.appPrimary)
                    .font(.subheadline)
            }
            .accessibilityIdentifier("login.signup.toggle")

            if !vm.isSignup {
                Button {
                    dismissKeyboard()
                    showReset = true
                } label: {
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
                    .focused($focusedField, equals: .age)
                    .submitLabel(.next)
                    .onSubmit { moveFocus(by: 1) }
                    .accessibilityIdentifier("login.age")
                TextField("身高 cm", text: $vm.heightCm)
                    .keyboardType(.decimalPad)
                    .focused($focusedField, equals: .height)
                    .submitLabel(.next)
                    .onSubmit { moveFocus(by: 1) }
                    .accessibilityIdentifier("login.height")
                TextField("体重 kg", text: $vm.weightKg)
                    .keyboardType(.decimalPad)
                    .focused($focusedField, equals: .weight)
                    .submitLabel(.next)
                    .onSubmit { moveFocus(by: 1) }
                    .accessibilityIdentifier("login.weight")
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

    private var focusOrder: [LoginFocusField] {
        if vm.mode == .subject {
            return []
        }
        if vm.isSignup {
            return [.phone, .username, .age, .height, .weight, .password]
        }
        return [.phone, .password]
    }

    private var passwordFocusBinding: Binding<Bool> {
        Binding(
            get: { focusedField == .password },
            set: { isFocused in
                if isFocused {
                    focusedField = .password
                } else if focusedField == .password {
                    focusedField = nil
                }
            }
        )
    }

    private func canMoveFocus(by offset: Int) -> Bool {
        guard let focusedField,
              let currentIndex = focusOrder.firstIndex(of: focusedField)
        else { return false }
        return focusOrder.indices.contains(currentIndex + offset)
    }

    private func moveFocus(by offset: Int) {
        guard let focusedField,
              let currentIndex = focusOrder.firstIndex(of: focusedField)
        else {
            self.focusedField = focusOrder.first
            return
        }

        let targetIndex = currentIndex + offset
        guard focusOrder.indices.contains(targetIndex) else {
            dismissKeyboard()
            return
        }
        self.focusedField = focusOrder[targetIndex]
    }

    private func dismissKeyboard() {
        focusedField = nil
        UIApplication.shared.sendAction(
            #selector(UIResponder.resignFirstResponder),
            to: nil,
            from: nil,
            for: nil
        )
    }

    private func submitCredentials() {
        guard !vm.loading, !isSubmittingCredentials else { return }
        isSubmittingCredentials = true
        dismissKeyboard()
        Task {
            await vm.loginPhone(authManager: authManager)
            isSubmittingCredentials = false
        }
    }
}

struct PasswordRevealField: View {
    private enum FocusTarget: Hashable {
        case secure
        case visible
    }

    let placeholder: String
    @Binding var text: String
    var textContentType: UITextContentType?
    private var externalFocus: Binding<Bool>?
    private var submitLabel: SubmitLabel
    private var onSubmit: (() -> Void)?
    @State private var isVisible = false
    @State private var isSwitchingVisibility = false
    @FocusState private var localFocus: FocusTarget?

    init(
        _ placeholder: String,
        text: Binding<String>,
        textContentType: UITextContentType? = nil,
        focus: Binding<Bool>? = nil,
        submitLabel: SubmitLabel = .done,
        onSubmit: (() -> Void)? = nil
    ) {
        self.placeholder = placeholder
        self._text = text
        self.textContentType = textContentType
        self.externalFocus = focus
        self.submitLabel = submitLabel
        self.onSubmit = onSubmit
    }

    var body: some View {
        HStack(spacing: 8) {
            ZStack {
                SecureField(placeholder, text: $text)
                    .focused($localFocus, equals: .secure)
                    .textContentType(isVisible ? nil : textContentType)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .submitLabel(submitLabel)
                    .onSubmit { onSubmit?() }
                    .opacity(isVisible ? 0 : 1)
                    .allowsHitTesting(!isVisible)
                    .accessibilityHidden(isVisible)

                TextField(placeholder, text: $text)
                    .focused($localFocus, equals: .visible)
                    .textContentType(isVisible ? textContentType : nil)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .submitLabel(submitLabel)
                    .onSubmit { onSubmit?() }
                    .opacity(isVisible ? 1 : 0)
                    .allowsHitTesting(isVisible)
                    .accessibilityHidden(!isVisible)
            }

            Button {
                toggleVisibility()
            } label: {
                Text(isVisible ? "隐藏" : "显示密码")
                    .font(.caption2.bold())
                    .foregroundColor(.appPrimary)
                    .frame(minWidth: 44, minHeight: 44)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.borderless)
            .disabled(isSwitchingVisibility)
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 8)
        .background(Color(.systemBackground))
        .overlay(
            RoundedRectangle(cornerRadius: 7)
                .stroke(Color(.separator).opacity(0.45), lineWidth: 1)
        )
        .clipShape(RoundedRectangle(cornerRadius: 7))
        .onAppear {
            syncLocalFocus(with: externalFocusValue)
        }
        .onChange(of: externalFocusValue) { _, shouldFocus in
            syncLocalFocus(with: shouldFocus)
        }
        .onChange(of: localFocus) { _, target in
            if target == nil, isSwitchingVisibility {
                return
            }
            externalFocus?.wrappedValue = target != nil
        }
    }

    private var externalFocusValue: Bool {
        externalFocus?.wrappedValue ?? false
    }

    private func syncLocalFocus(with shouldFocus: Bool) {
        if shouldFocus {
            let target: FocusTarget = isVisible ? .visible : .secure
            if localFocus != target {
                localFocus = target
            }
        } else if localFocus != nil {
            localFocus = nil
        }
    }

    private func toggleVisibility() {
        let shouldRestoreFocus = localFocus != nil || externalFocusValue
        isSwitchingVisibility = shouldRestoreFocus
        isVisible.toggle()

        guard shouldRestoreFocus else { return }
        let target: FocusTarget = isVisible ? .visible : .secure
        localFocus = target
        externalFocus?.wrappedValue = true
        Task { @MainActor in
            await Task.yield()
            localFocus = target
            externalFocus?.wrappedValue = true
            isSwitchingVisibility = false
        }
    }
}
