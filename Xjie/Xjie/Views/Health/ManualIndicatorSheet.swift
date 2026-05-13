import SwiftUI

/// 手动录入指标 Sheet — 支持中英文/别名搜索
struct ManualIndicatorSheet: View {
    let onSaved: () -> Void
    @Environment(\.dismiss) private var dismiss
    @StateObject private var vm = ManualIndicatorViewModel()

    @State private var valueText: String = ""
    @State private var unitText: String = ""
    @State private var measuredAt: Date = Date()
    @State private var notes: String = ""
    @State private var customName: String = ""

    var body: some View {
        NavigationStack {
            Form {
                Section("搜索指标（中英文/别名）") {
                    TextField("如：血糖 / FBG / HbA1c", text: Binding(
                        get: { vm.query },
                        set: { vm.updateQuery($0) }
                    ))
                    .autocorrectionDisabled()
                    .textInputAutocapitalization(.never)

                    if vm.searching {
                        HStack { ProgressView().controlSize(.small); Text("搜索中…").font(.caption) }
                    } else if !vm.results.isEmpty {
                        ForEach(vm.results) { item in
                            Button {
                                vm.selected = item
                                if let u = item.unit, !u.isEmpty, unitText.isEmpty { unitText = u }
                            } label: {
                                HStack(alignment: .top) {
                                    VStack(alignment: .leading, spacing: 2) {
                                        Text(item.name).font(.subheadline).foregroundColor(.appText)
                                        if let alias = item.alias, !alias.isEmpty {
                                            Text(alias).font(.caption2).foregroundColor(.appMuted)
                                        }
                                    }
                                    Spacer()
                                    if let cat = item.category {
                                        Text(cat).font(.caption2)
                                            .padding(.horizontal, 6).padding(.vertical, 2)
                                            .background(Color.appPrimary.opacity(0.1))
                                            .foregroundColor(.appPrimary)
                                            .cornerRadius(4)
                                    }
                                    if vm.selected?.name == item.name {
                                        Image(systemName: "checkmark.circle.fill").foregroundColor(.appPrimary)
                                    }
                                }
                            }
                        }
                    } else if !vm.query.isEmpty {
                        Text("无匹配结果，可手动输入指标名后保存")
                            .font(.caption).foregroundColor(.appMuted)
                        TextField("自定义指标名", text: $customName)
                    }
                }

                Section("数值与单位") {
                    HStack {
                        Text("数值")
                        Spacer()
                        TextField("如 5.6", text: $valueText)
                            .keyboardType(.decimalPad)
                            .multilineTextAlignment(.trailing)
                            .frame(width: 100)
                    }
                    HStack {
                        Text("单位")
                        Spacer()
                        TextField("可选", text: $unitText)
                            .multilineTextAlignment(.trailing)
                            .frame(width: 120)
                    }
                    DatePicker("测量时间", selection: $measuredAt, displayedComponents: [.date, .hourAndMinute])
                    TextField("备注", text: $notes, axis: .vertical)
                        .lineLimit(2...4)
                }
            }
            .navigationTitle("手动录入指标")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("取消") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(vm.saving ? "保存中…" : "保存") { Task { await save() } }
                        .disabled(!canSave || vm.saving)
                }
            }
            .onChange(of: vm.savedOk) { _, ok in
                if ok { onSaved(); dismiss() }
            }
            .alert("错误", isPresented: Binding(
                get: { vm.errorMessage != nil },
                set: { if !$0 { vm.errorMessage = nil } }
            )) {
                Button("确定", role: .cancel) {}
            } message: { Text(vm.errorMessage ?? "") }
        }
    }

    private var indicatorName: String {
        vm.selected?.name ?? customName.trimmingCharacters(in: .whitespaces)
    }

    private var canSave: Bool {
        !indicatorName.isEmpty && Double(valueText) != nil
    }

    private func save() async {
        guard let v = Double(valueText), !indicatorName.isEmpty else { return }
        await vm.submit(
            indicatorName: indicatorName,
            value: v,
            unit: unitText.isEmpty ? nil : unitText,
            measuredAt: measuredAt,
            notes: notes.isEmpty ? nil : notes
        )
    }
}
