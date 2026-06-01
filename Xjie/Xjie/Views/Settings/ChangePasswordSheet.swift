import SwiftUI

struct ChangePasswordSheet: View {
    @Environment(\.dismiss) private var dismiss
    @StateObject private var vm = ChangePasswordViewModel()

    var body: some View {
        NavigationStack {
            Form {
                Section("修改密码") {
                    PasswordRevealField("旧密码", text: $vm.oldPassword, textContentType: .password)
                    PasswordRevealField("新密码（至少 8 位）", text: $vm.newPassword, textContentType: .newPassword)
                    PasswordRevealField("确认新密码", text: $vm.confirmPassword, textContentType: .newPassword)
                }
            }
            .navigationTitle("修改密码")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("取消") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(vm.loading ? "提交中…" : "保存") { Task { await vm.submit() } }
                        .disabled(vm.loading)
                }
            }
            .onChange(of: vm.savedOk) { _, ok in
                if ok { dismiss() }
            }
            .alert("错误", isPresented: Binding(
                get: { vm.errorMessage != nil },
                set: { if !$0 { vm.errorMessage = nil } }
            )) { Button("确定", role: .cancel) {} } message: { Text(vm.errorMessage ?? "") }
        }
    }
}
