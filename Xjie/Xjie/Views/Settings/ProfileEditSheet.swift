import SwiftUI

/// 个人资料编辑：性别 / 年龄 / 身高 / 体重 / 昵称。
/// 使用 SwiftUI 原生 Picker / Stepper，保存后通过 PATCH /api/users/profile 同步服务器。
struct ProfileEditSheet: View {
    @Environment(\.dismiss) private var dismiss
    @ObservedObject var vm: SettingsViewModel

    @State private var sex: String = "female"
    @State private var age: Int = 30
    @State private var heightCm: Int = 165
    @State private var weightKg: Int = 55
    @State private var displayName: String = ""
    @State private var saving = false
    @State private var errMsg: String?

    private let sexOptions: [(String, String)] = [
        ("female", "女"), ("male", "男"), ("other", "其他"),
    ]

    var body: some View {
        NavigationStack {
            Form {
                Section("基本信息") {
                    Picker("性别", selection: $sex) {
                        ForEach(sexOptions, id: \.0) { Text($0.1).tag($0.0) }
                    }
                    Stepper("年龄：\(age) 岁", value: $age, in: 1...120)
                    Stepper("身高：\(heightCm) cm", value: $heightCm, in: 80...230)
                    Stepper("体重：\(weightKg) kg", value: $weightKg, in: 20...250)
                }
                Section("昵称") {
                    TextField("可选，最多 32 字", text: $displayName)
                        .textInputAutocapitalization(.never)
                }
                if let err = errMsg {
                    Section { Text(err).foregroundColor(.appDanger) }
                }
            }
            .navigationTitle("修改个人资料")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("取消") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(saving ? "保存中…" : "保存") { Task { await save() } }
                        .disabled(saving)
                }
            }
            .onAppear { hydrateFromVM() }
        }
    }

    private func hydrateFromVM() {
        let p = vm.user?.profile
        let raw = (p?.sex ?? "female").lowercased()
        sex = sexOptions.contains { $0.0 == raw } ? raw : "female"
        age = p?.age ?? 30
        heightCm = Int(p?.height_cm ?? 165)
        weightKg = Int(p?.weight_kg ?? 55)
        displayName = p?.display_name ?? ""
    }

    private func save() async {
        saving = true
        defer { saving = false }
        let name = displayName.trimmingCharacters(in: .whitespacesAndNewlines)
        let ok = await vm.updateProfile(
            sex: sex,
            age: age,
            heightCm: Double(heightCm),
            weightKg: Double(weightKg),
            displayName: name.isEmpty ? nil : name
        )
        if ok {
            dismiss()
        } else {
            errMsg = vm.errorMessage ?? "保存失败"
        }
    }
}
