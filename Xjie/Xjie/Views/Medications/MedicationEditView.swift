import SwiftUI

/// 用药新增/编辑（手动填写）。
struct MedicationEditView: View {
    let editing: Medication?
    let onSubmit: (MedicationBody) async -> Void

    @Environment(\.dismiss) private var dismiss

    @State private var name: String = ""
    @State private var dosage: String = ""
    @State private var frequency: String = ""
    @State private var instructions: String = ""
    @State private var scheduleTimes: [String] = []
    @State private var courseStart: Date? = nil
    @State private var courseEnd: Date? = nil
    @State private var enabled: Bool = true

    @State private var showAddTime = false
    @State private var newTime = Date()

    var body: some View {
        NavigationStack {
            Form {
                Section("药品信息") {
                    TextField("药品名称", text: $name)
                    TextField("剂量（如 5mg / 1片）", text: $dosage)
                    TextField("频次（如 每日3次）", text: $frequency)
                    TextField("使用说明（饭后/空腹等）", text: $instructions, axis: .vertical)
                        .lineLimit(2...5)
                }

                Section("提醒时间") {
                    if scheduleTimes.isEmpty {
                        Text("还没有提醒时间").foregroundColor(.appMuted).font(.subheadline)
                    } else {
                        ForEach(scheduleTimes, id: \.self) { t in
                            HStack {
                                Image(systemName: "bell.fill").foregroundColor(.appPrimary)
                                Text(t).font(.system(.body, design: .monospaced))
                                Spacer()
                                Button(role: .destructive) {
                                    scheduleTimes.removeAll { $0 == t }
                                } label: { Image(systemName: "minus.circle.fill").foregroundColor(.red) }
                                    .buttonStyle(.plain)
                            }
                        }
                    }
                    Button {
                        newTime = Date()
                        showAddTime = true
                    } label: {
                        Label("添加提醒时间", systemImage: "plus.circle.fill")
                    }
                }

                Section("疗程窗口（可选）") {
                    Toggle("启用提醒", isOn: $enabled)
                    DatePicker("开始日期", selection: Binding(
                        get: { courseStart ?? Date() },
                        set: { courseStart = $0 }
                    ), displayedComponents: .date)
                    DatePicker("结束日期", selection: Binding(
                        get: { courseEnd ?? Date() },
                        set: { courseEnd = $0 }
                    ), displayedComponents: .date)
                }
            }
            .navigationTitle(editing == nil ? "添加用药" : "编辑用药")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("取消") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("保存") { Task { await submit() } }
                        .disabled(name.trimmingCharacters(in: .whitespaces).isEmpty)
                }
            }
            .sheet(isPresented: $showAddTime) {
                NavigationStack {
                    DatePicker("选择时间", selection: $newTime, displayedComponents: .hourAndMinute)
                        .datePickerStyle(.wheel)
                        .labelsHidden()
                        .padding()
                        .navigationTitle("添加提醒时间")
                        .navigationBarTitleDisplayMode(.inline)
                        .toolbar {
                            ToolbarItem(placement: .cancellationAction) {
                                Button("取消") { showAddTime = false }
                            }
                            ToolbarItem(placement: .confirmationAction) {
                                Button("添加") {
                                    let comp = Calendar.current.dateComponents([.hour, .minute], from: newTime)
                                    let s = String(format: "%02d:%02d", comp.hour ?? 0, comp.minute ?? 0)
                                    if !scheduleTimes.contains(s) { scheduleTimes.append(s); scheduleTimes.sort() }
                                    showAddTime = false
                                }
                            }
                        }
                }
                .presentationDetents([.medium])
            }
            .onAppear(perform: loadFromEditing)
        }
    }

    // MARK: - Logic

    private func loadFromEditing() {
        guard let m = editing else { return }
        name = m.name
        dosage = m.dosage ?? ""
        frequency = m.frequency ?? ""
        instructions = m.instructions ?? ""
        scheduleTimes = m.schedule_times
        enabled = m.enabled
        let df = DateFormatter(); df.dateFormat = "yyyy-MM-dd"
        courseStart = m.course_start.flatMap { df.date(from: $0) }
        courseEnd = m.course_end.flatMap { df.date(from: $0) }
    }

    private func submit() async {
        let df = DateFormatter(); df.dateFormat = "yyyy-MM-dd"
        let body = MedicationBody(
            name: name.trimmingCharacters(in: .whitespaces),
            dosage: dosage.isEmpty ? nil : dosage,
            frequency: frequency.isEmpty ? nil : frequency,
            instructions: instructions.isEmpty ? nil : instructions,
            schedule_times: scheduleTimes,
            course_start: courseStart.map { df.string(from: $0) },
            course_end: courseEnd.map { df.string(from: $0) },
            photo_url: nil,
            enabled: enabled
        )
        await onSubmit(body)
    }
}
