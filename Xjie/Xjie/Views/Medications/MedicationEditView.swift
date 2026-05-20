import SwiftUI
import PhotosUI
import Vision
import UIKit

/// 用药新增/编辑。支持拍照/相册 → 端侧 Vision OCR → 后端 LLM 结构化 → 自动填充。
struct MedicationEditView: View {
    let editing: Medication?
    let onSubmit: (MedicationBody) async -> Void

    @StateObject private var vm = MedicationViewModel()
    @Environment(\.dismiss) private var dismiss

    @State private var name: String = ""
    @State private var dosage: String = ""
    @State private var frequency: String = ""
    @State private var instructions: String = ""
    @State private var scheduleTimes: [String] = []
    @State private var courseStart: Date? = nil
    @State private var courseEnd: Date? = nil
    @State private var enabled: Bool = true

    @State private var showImageSource = false
    @State private var showCamera = false
    @State private var showPhotoPicker = false
    @State private var pickedPhoto: PhotosPickerItem? = nil
    @State private var recognizing = false
    @State private var recognizeBanner: String? = nil

    @State private var showAddTime = false
    @State private var newTime = Date()

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Button {
                        showImageSource = true
                    } label: {
                        HStack {
                            Image(systemName: "camera.fill")
                            Text(recognizing ? "识别中…" : "拍照/相册识别药品")
                                .fontWeight(.semibold)
                            Spacer()
                            if recognizing { ProgressView() }
                        }
                    }
                    .disabled(recognizing)
                    if let banner = recognizeBanner {
                        Text(banner).font(.caption).foregroundColor(.appMuted)
                    }
                }

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
            .confirmationDialog("选择来源", isPresented: $showImageSource) {
                Button("拍照") { showCamera = true }
                Button("从相册选择") { showPhotoPicker = true }
                Button("取消", role: .cancel) {}
            }
            .sheet(isPresented: $showCamera) {
                CameraPicker { img in
                    showCamera = false
                    if let img { Task { await recognize(img) } }
                }
            }
            .photosPicker(isPresented: $showPhotoPicker, selection: $pickedPhoto, matching: .images)
            .onChange(of: pickedPhoto) { _, item in
                guard let item else { return }
                Task {
                    if let data = try? await item.loadTransferable(type: Data.self),
                       let img = UIImage(data: data) {
                        await recognize(img)
                    }
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

    /// 端侧 Vision OCR → 后端 LLM 结构化。
    private func recognize(_ image: UIImage) async {
        recognizing = true
        recognizeBanner = nil
        defer { recognizing = false }

        let text = await Self.runOCR(image)
        guard !text.isEmpty else {
            recognizeBanner = "未识别到文字，请确认拍摄清晰"
            return
        }

        if let r = await vm.recognize(rawText: text) {
            if let n = r.name, !n.isEmpty, name.isEmpty { name = n }
            if let d = r.dosage, !d.isEmpty, dosage.isEmpty { dosage = d }
            if let f = r.frequency, !f.isEmpty, frequency.isEmpty { frequency = f }
            if let i = r.instructions, !i.isEmpty, instructions.isEmpty { instructions = i }
            if scheduleTimes.isEmpty && !r.schedule_times.isEmpty {
                scheduleTimes = r.schedule_times.sorted()
            }
            recognizeBanner = "已自动填充，请核对"
        } else {
            recognizeBanner = "结构化失败，可手动填写"
        }
    }

    static func runOCR(_ image: UIImage) async -> String {
        await withCheckedContinuation { cont in
            guard let cgImage = image.cgImage else { cont.resume(returning: ""); return }
            let request = VNRecognizeTextRequest { req, _ in
                let observations = req.results as? [VNRecognizedTextObservation] ?? []
                let text = observations
                    .compactMap { $0.topCandidates(1).first?.string }
                    .joined(separator: "\n")
                cont.resume(returning: text)
            }
            request.recognitionLevel = .accurate
            request.recognitionLanguages = ["zh-Hans", "en-US"]
            request.usesLanguageCorrection = true
            DispatchQueue.global(qos: .userInitiated).async {
                let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
                try? handler.perform([request])
            }
        }
    }
}

// MARK: - Camera

struct CameraPicker: UIViewControllerRepresentable {
    let onPick: (UIImage?) -> Void
    func makeCoordinator() -> Coordinator { Coordinator(onPick: onPick) }
    func makeUIViewController(context: Context) -> UIImagePickerController {
        let picker = UIImagePickerController()
        picker.sourceType = UIImagePickerController.isSourceTypeAvailable(.camera) ? .camera : .photoLibrary
        picker.delegate = context.coordinator
        return picker
    }
    func updateUIViewController(_ uiViewController: UIImagePickerController, context: Context) {}

    final class Coordinator: NSObject, UIImagePickerControllerDelegate, UINavigationControllerDelegate {
        let onPick: (UIImage?) -> Void
        init(onPick: @escaping (UIImage?) -> Void) { self.onPick = onPick }
        func imagePickerController(_ picker: UIImagePickerController, didFinishPickingMediaWithInfo info: [UIImagePickerController.InfoKey : Any]) {
            onPick(info[.originalImage] as? UIImage)
        }
        func imagePickerControllerDidCancel(_ picker: UIImagePickerController) { onPick(nil) }
    }
}
