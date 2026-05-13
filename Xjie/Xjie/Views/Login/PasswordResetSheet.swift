import SwiftUI

struct PasswordResetSheet: View {
    @Environment(\.dismiss) private var dismiss
    @StateObject private var vm = PasswordResetViewModel()

    var body: some View {
        NavigationStack {
            Form {
                Section("找回密码") {
                    TextField("手机号", text: $vm.phone)
                        .keyboardType(.phonePad)
                        .textContentType(.telephoneNumber)
                    HStack {
                        TextField("验证码", text: $vm.code)
                            .keyboardType(.numberPad)
                        Button(vm.sending ? "发送中…" : "获取验证码") {
                            Task { await vm.requestCode() }
                        }
                        .disabled(vm.phone.count != 11 || vm.sending)
                        .font(.caption)
                    }
                    SecureField("新密码（至少 8 位）", text: $vm.newPassword)
                        .textContentType(.newPassword)
                }
                if let info = vm.infoMessage {
                    Section { Text(info).font(.caption).foregroundColor(.appPrimary) }
                }
            }
            .navigationTitle("找回密码")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("取消") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(vm.loading ? "提交中…" : "重置") { Task { await vm.confirm() } }
                        .disabled(vm.loading)
                }
            }
            .onChange(of: vm.resetOk) { _, ok in
                if ok { dismiss() }
            }
            .alert("错误", isPresented: Binding(
                get: { vm.errorMessage != nil },
                set: { if !$0 { vm.errorMessage = nil } }
            )) { Button("确定", role: .cancel) {} } message: { Text(vm.errorMessage ?? "") }
        }
    }
}
