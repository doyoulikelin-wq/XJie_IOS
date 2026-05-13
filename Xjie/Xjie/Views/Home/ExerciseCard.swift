import SwiftUI

/// 首页"今日锻炼"卡片
struct ExerciseCard: View {
    @StateObject private var vm = ExerciseViewModel()

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Label("今日锻炼", systemImage: "figure.run")
                    .font(.headline)
                Spacer()
                Button { vm.showAdd = true } label: {
                    Label("记录", systemImage: "plus.circle")
                        .font(.subheadline)
                        .foregroundColor(.appPrimary)
                }
            }

            HStack(spacing: 16) {
                VStack(alignment: .leading, spacing: 2) {
                    Text("\(vm.totalMinutes)").font(.title2).bold()
                    Text("分钟").font(.caption).foregroundColor(.appMuted)
                }
                VStack(alignment: .leading, spacing: 2) {
                    Text(String(format: "%.0f", vm.totalKcal)).font(.title2).bold()
                    Text("kcal").font(.caption).foregroundColor(.appMuted)
                }
                VStack(alignment: .leading, spacing: 2) {
                    Text("\(vm.items.count)").font(.title2).bold()
                    Text("项").font(.caption).foregroundColor(.appMuted)
                }
                Spacer()
            }

            if vm.items.isEmpty && !vm.loading {
                Text("点击「记录」添加今日锻炼")
                    .font(.caption)
                    .foregroundColor(.appMuted)
            } else {
                ForEach(vm.items.prefix(5)) { item in
                    ExerciseRow(item: item) {
                        Task { await vm.delete(item.id) }
                    }
                }
                if vm.items.count > 5 {
                    Text("还有 \(vm.items.count - 5) 项…")
                        .font(.caption2)
                        .foregroundColor(.appMuted)
                }
            }
        }
        .cardStyle()
        .task { await vm.load() }
        .sheet(isPresented: $vm.showAdd) {
            AddExerciseSheet { body in
                Task { await vm.add(body) }
            }
        }
        .alert("错误", isPresented: Binding(
            get: { vm.errorMessage != nil },
            set: { if !$0 { vm.errorMessage = nil } }
        )) {
            Button("确定", role: .cancel) {}
        } message: { Text(vm.errorMessage ?? "") }
    }
}

private struct ExerciseRow: View {
    let item: ExerciseItem
    let onDelete: () -> Void

    var body: some View {
        HStack(spacing: 8) {
            Text(activityLabel(item.activity_type))
                .font(.subheadline)
            if let intensity = item.intensity, !intensity.isEmpty {
                Text(intensityLabel(intensity))
                    .font(.caption2)
                    .padding(.horizontal, 6).padding(.vertical, 2)
                    .background(Color.appPrimary.opacity(0.1))
                    .foregroundColor(.appPrimary)
                    .cornerRadius(4)
            }
            Spacer()
            Text("\(item.duration_minutes) 分钟")
                .font(.caption)
                .foregroundColor(.appMuted)
            if let kcal = item.calories_kcal, kcal > 0 {
                Text(String(format: "%.0f kcal", kcal))
                    .font(.caption)
                    .foregroundColor(.appMuted)
            }
            Button(action: onDelete) {
                Image(systemName: "trash").font(.caption2).foregroundColor(.appDanger)
            }
        }
        .padding(.vertical, 4)
    }
}

// MARK: - 选项

let ACTIVITY_OPTIONS: [(String, String)] = [
    ("walking", "散步/快走"),
    ("running", "跑步"),
    ("cycling", "骑行"),
    ("swimming", "游泳"),
    ("yoga", "瑜伽"),
    ("strength", "力量训练"),
    ("hiit", "HIIT"),
    ("stretching", "拉伸"),
    ("dancing", "舞蹈"),
    ("ball", "球类运动"),
    ("hiking", "徒步登山"),
    ("other", "其他"),
]

let INTENSITY_OPTIONS: [(String, String)] = [
    ("low", "轻度"),
    ("medium", "中度"),
    ("high", "高强度"),
]

func activityLabel(_ code: String) -> String {
    ACTIVITY_OPTIONS.first { $0.0 == code }?.1 ?? code
}

func intensityLabel(_ code: String) -> String {
    INTENSITY_OPTIONS.first { $0.0 == code }?.1 ?? code
}

// MARK: - 添加 Sheet

struct AddExerciseSheet: View {
    let onSubmit: (ExerciseBody) -> Void
    @Environment(\.dismiss) private var dismiss

    @State private var activityType: String = "walking"
    @State private var customType: String = ""
    @State private var minutes: String = "30"
    @State private var intensity: String = "medium"
    @State private var calories: String = ""
    @State private var notes: String = ""

    var body: some View {
        NavigationStack {
            Form {
                Section("运动类型") {
                    Picker("类型", selection: $activityType) {
                        ForEach(ACTIVITY_OPTIONS, id: \.0) { code, label in
                            Text(label).tag(code)
                        }
                    }
                    if activityType == "other" {
                        TextField("自定义类型", text: $customType)
                    }
                }
                Section("时长 / 强度") {
                    HStack {
                        Text("分钟")
                        Spacer()
                        TextField("0", text: $minutes)
                            .keyboardType(.numberPad)
                            .multilineTextAlignment(.trailing)
                            .frame(width: 80)
                    }
                    Picker("强度", selection: $intensity) {
                        ForEach(INTENSITY_OPTIONS, id: \.0) { code, label in
                            Text(label).tag(code)
                        }
                    }
                    .pickerStyle(.segmented)
                }
                Section("可选") {
                    HStack {
                        Text("热量 kcal")
                        Spacer()
                        TextField("可选", text: $calories)
                            .keyboardType(.decimalPad)
                            .multilineTextAlignment(.trailing)
                            .frame(width: 100)
                    }
                    TextField("备注", text: $notes, axis: .vertical)
                        .lineLimit(2...4)
                }
            }
            .navigationTitle("记录锻炼")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("取消") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("保存") { submit() }
                        .disabled(!canSubmit)
                }
            }
        }
    }

    private var canSubmit: Bool {
        Int(minutes) ?? 0 > 0
    }

    private func submit() {
        let mins = Int(minutes) ?? 0
        guard mins > 0 else { return }
        var finalNotes = notes
        if activityType == "other" && !customType.trimmingCharacters(in: .whitespaces).isEmpty {
            let custom = customType.trimmingCharacters(in: .whitespaces)
            finalNotes = finalNotes.isEmpty ? "[自定义:\(custom)]" : "\(finalNotes) [自定义:\(custom)]"
        }
        let kcal = Double(calories.trimmingCharacters(in: .whitespaces))
        let body = ExerciseBody(
            activity_type: activityType,
            duration_minutes: mins,
            intensity: intensity,
            calories_kcal: kcal,
            notes: finalNotes.isEmpty ? nil : finalNotes,
            started_at: nil
        )
        onSubmit(body)
        dismiss()
    }
}
