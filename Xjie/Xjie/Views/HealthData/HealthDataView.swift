import SwiftUI
import UniformTypeIdentifiers
import UIKit

/// 健康数据中心 — 对应小程序 pages/health-data/health-data
struct HealthDataView: View {
    @StateObject private var vm = HealthDataViewModel()
    @StateObject private var trendVM = IndicatorTrendViewModel()
    /// 跨页面 focus 高亮参数：records / exams / upload / indicator
    var focus: String? = nil
    @State private var highlightedFocus: String? = nil
    @State private var showCamera = false
    @State private var qualityWarning: String? = nil

    var body: some View {
        NavigationStack {
            ScrollViewReader { proxy in
            ScrollView {
                VStack(spacing: 12) {
                    // 上传进度横幅
                    if vm.uploading {
                        VStack(alignment: .leading, spacing: 6) {
                            HStack(spacing: 8) {
                                ProgressView()
                                Text(vm.uploadStage.isEmpty ? "正在上传…" : vm.uploadStage)
                                    .font(.subheadline)
                                    .fontWeight(.semibold)
                            }
                            ProgressView(value: 0.5).progressViewStyle(.linear)
                            Text("上传完成后会转入后台识别，您可以随时离开此页。")
                                .font(.caption2)
                                .foregroundColor(.appMuted)
                        }
                        .cardStyle()
                    }

                    // AI 后台识别提示条
                    if let hint = vm.backgroundTaskHint {
                        HStack(alignment: .top, spacing: 8) {
                            Image(systemName: "sparkles")
                                .foregroundColor(.appPrimary)
                            Text(hint)
                                .font(.caption)
                                .foregroundColor(.appText)
                                .frame(maxWidth: .infinity, alignment: .leading)
                            Button {
                                vm.dismissBackgroundHint()
                            } label: {
                                Image(systemName: "xmark")
                                    .font(.caption2)
                                    .foregroundColor(.appMuted)
                            }
                        }
                        .padding(.horizontal, 12)
                        .padding(.vertical, 10)
                        .background(Color.appPrimary.opacity(0.08))
                        .overlay(
                            RoundedRectangle(cornerRadius: 10)
                                .stroke(Color.appPrimary.opacity(0.25), lineWidth: 1)
                        )
                        .clipShape(RoundedRectangle(cornerRadius: 10))
                    }

                    // AI 总结卡片
                    aiSummaryCard

                    // 病史整理入口
                    NavigationLink(destination: PatientHistoryView()) {
                        patientHistoryEntry
                    }

                    // 指标趋势图表
                    IndicatorTrendSection(vm: trendVM)
                        .cardStyle()
                        .id("focus-indicator")
                        .overlay(focusBorder(for: "indicator"))

                    // 历史病例
                    NavigationLink(destination: MedicalRecordListView()) {
                        sectionCard(icon: "list.clipboard", title: "历史病例", count: vm.recordCount)
                    }
                    .id("focus-records")
                    .overlay(focusBorder(for: "records"))

                    // 历史体检
                    NavigationLink(destination: ExamReportListView()) {
                        sectionCard(icon: "flask", title: "历史体检", count: vm.examCount)
                    }
                    .id("focus-exams")
                    .overlay(focusBorder(for: "exams"))

                    // 快捷上传
                    Button { vm.showUploadSheet = true } label: {
                        HStack {
                            Image(systemName: "camera")
                            Text("拍照 / 文件上传")
                                .foregroundColor(.appText)
                        }
                        .frame(maxWidth: .infinity)
                        .padding()
                        .background(Color.appPrimary.opacity(0.1))
                        .cornerRadius(10)
                    }
                    .id("focus-upload")
                    .overlay(focusBorder(for: "upload"))
                }
                .padding(.horizontal, 16)
                .padding(.top, 8)
            }
            .onAppear {
                if let f = focus {
                    highlightedFocus = f
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.4) {
                        withAnimation { proxy.scrollTo("focus-\(f)", anchor: .top) }
                    }
                    DispatchQueue.main.asyncAfter(deadline: .now() + 3.5) {
                        withAnimation { highlightedFocus = nil }
                    }
                }
            }
            }
            .background(Color.appBackground)
            .navigationTitle("健康数据")
            .navigationBarTitleDisplayMode(.inline)
            .refreshable {
                await vm.fetchAll()
                await trendVM.fetchIndicators()
            }
            .task {
                await vm.fetchAll()
                await trendVM.fetchIndicators()
            }
            .overlay {
                if vm.loading { ProgressView("加载中...") }
            }
            .confirmationDialog("选择上传类型", isPresented: $vm.showUploadSheet) {
                Button("上传病例") { vm.uploadDocType = "record"; vm.showDocumentPicker = true }
                Button("上传体检报告") { vm.uploadDocType = "exam"; vm.showDocumentPicker = true }
                Button("拍照上传病例") { vm.uploadDocType = "record"; showCamera = true }
                Button("拍照上传报告") { vm.uploadDocType = "exam"; showCamera = true }
                Button("取消", role: .cancel) {}
            }
            .sheet(isPresented: $vm.showDocumentPicker) {
                DocumentPickerView { data, fileName in
                    handleUpload(data: data, fileName: fileName)
                }
            }
            .fullScreenCover(isPresented: $showCamera) {
                CameraImagePicker { data, name in
                    handleUpload(data: data, fileName: name)
                }
                .ignoresSafeArea()
            }
            .alert("拍摄质量不足", isPresented: Binding(
                get: { qualityWarning != nil },
                set: { if !$0 { qualityWarning = nil } }
            )) {
                Button("重新拍摄") { qualityWarning = nil; showCamera = true }
                Button("取消", role: .cancel) { qualityWarning = nil }
            } message: { Text(qualityWarning ?? "") }
            .alert("提示", isPresented: Binding(
                get: { vm.infoMessage != nil },
                set: { if !$0 { vm.infoMessage = nil } }
            )) {
                Button("知道了", role: .cancel) {}
            } message: {
                Text(vm.infoMessage ?? "")
            }
            .alert("错误", isPresented: Binding(
                get: { vm.errorMessage != nil },
                set: { if !$0 { vm.errorMessage = nil } }
            )) {
                Button("确定", role: .cancel) {}
            } message: {
                Text(vm.errorMessage ?? "")
            }
        }
    }

    // MARK: - 上传质量验证 + 代理
    private func handleUpload(data: Data, fileName: String) {
        if let warn = validateImageQuality(data: data, fileName: fileName) {
            qualityWarning = warn
            return
        }
        Task { await vm.uploadFile(data: data, fileName: fileName) }
    }

    /// 验证图片质量：限制最小字节数与短边像素。返回 nil 表示通过。
    private func validateImageQuality(data: Data, fileName: String) -> String? {
        let lower = fileName.lowercased()
        let isImage = lower.hasSuffix(".jpg") || lower.hasSuffix(".jpeg") || lower.hasSuffix(".png") || lower.hasSuffix(".heic")
        guard isImage else { return nil }
        if data.count < 30 * 1024 {
            return "图片过小（小于 30KB），可能不是报告/病例。请重新拍摄。"
        }
        if let img = UIImage(data: data) {
            let shortEdge = min(img.size.width, img.size.height) * img.scale
            if shortEdge < 600 {
                return "图片分辨率过低（短边 \(Int(shortEdge))px），识别可能失败。请重新拍摄。"
            }
        } else {
            return "未能读取图片数据，请重新拍摄。"
        }
        return nil
    }

    // MARK: - AI 总结

    private var aiSummaryCard: some View {
        Button { Task { await vm.generateSummary() } } label: {
            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    Image("Logo")
                        .resizable()
                        .scaledToFit()
                        .frame(width: 20, height: 20)
                        .foregroundColor(.appPrimary)
                    Text("AI 健康总结").font(.headline).foregroundColor(.appText)
                    Spacer()
                    if vm.generatingSummary {
                        ProgressView()
                    } else {
                        Image(systemName: "arrow.triangle.2.circlepath")
                            .foregroundColor(.appPrimary)
                    }
                }

                if vm.generatingSummary {
                    VStack(spacing: 6) {
                        ProgressView(value: vm.summaryProgress)
                            .tint(.appPrimary)
                        Text(vm.summaryStage)
                            .font(.caption)
                            .foregroundColor(.appMuted)
                    }
                } else if !vm.summary.isEmpty {
                    MarkdownTextView(text: vm.summary)
                    if !vm.summaryUpdatedAt.isEmpty {
                        Text("更新于 \(vm.summaryUpdatedAt)")
                            .font(.caption2)
                            .foregroundColor(.appMuted)
                    }
                } else {
                    VStack(spacing: 4) {
                        Text("点击生成 AI 健康总结")
                            .font(.subheadline)
                            .foregroundColor(.appMuted)
                        Text("将综合您的所有病例和体检数据进行分析")
                            .font(.caption)
                            .foregroundColor(.appMuted)
                    }
                }
            }
            .cardStyle()
        }
    }

    // MARK: - 病史整理入口（与 Android 对齐）
    private var patientHistoryEntry: some View {
        HStack(spacing: 12) {
            Image(systemName: "stethoscope")
                .font(.title2)
                .foregroundColor(.appPrimary)
            VStack(alignment: .leading, spacing: 2) {
                Text("病史整理").font(.headline).foregroundColor(.appText)
                Text("把诊断、用药、过敏和异常检查整理成给医生看的摘要")
                    .font(.caption)
                    .foregroundColor(.appMuted)
                    .multilineTextAlignment(.leading)
            }
            Spacer()
            Image(systemName: "chevron.right")
                .foregroundColor(.appMuted)
                .font(.caption)
        }
        .cardStyle()
    }

    @ViewBuilder
    private func focusBorder(for key: String) -> some View {
        if highlightedFocus == key {
            RoundedRectangle(cornerRadius: 12)
                .stroke(Color.appPrimary, lineWidth: 2)
        }
    }

    // MARK: - 板块卡片

    private func sectionCard(icon: String, title: String, count: Int) -> some View {
        HStack {
            HStack(spacing: 12) {
                Image(systemName: icon)
                    .font(.title2)
                    .foregroundColor(.appPrimary)
                VStack(alignment: .leading) {
                    Text(title).font(.headline).foregroundColor(.appText)
                    Text("\(count) 份记录").font(.caption).foregroundColor(.appMuted)
                }
            }
            Spacer()
            HStack(spacing: 4) {
                Text("可上传")
                    .font(.caption2)
                    .padding(.horizontal, 6)
                    .padding(.vertical, 2)
                    .background(Color.appPrimary.opacity(0.1))
                    .foregroundColor(.appPrimary)
                    .cornerRadius(4)
                Image(systemName: "chevron.right")
                    .foregroundColor(.appMuted)
                    .font(.caption)
            }
        }
        .cardStyle()
    }
}

// MARK: - 文件选择器

struct DocumentPickerView: UIViewControllerRepresentable {
    let onPick: (Data, String) -> Void

    func makeUIViewController(context: Context) -> UIDocumentPickerViewController {
        let types: [UTType] = [.jpeg, .png, .commaSeparatedText, .pdf]
        let picker = UIDocumentPickerViewController(forOpeningContentTypes: types)
        picker.delegate = context.coordinator
        return picker
    }

    func updateUIViewController(_ uiViewController: UIDocumentPickerViewController, context: Context) {}

    func makeCoordinator() -> Coordinator { Coordinator(onPick: onPick) }

    class Coordinator: NSObject, UIDocumentPickerDelegate {
        let onPick: (Data, String) -> Void
        init(onPick: @escaping (Data, String) -> Void) { self.onPick = onPick }

        func documentPicker(_ controller: UIDocumentPickerViewController, didPickDocumentsAt urls: [URL]) {
            guard let url = urls.first else { return }
            _ = url.startAccessingSecurityScopedResource()
            defer { url.stopAccessingSecurityScopedResource() }
            guard let data = try? Data(contentsOf: url) else { return }
            onPick(data, url.lastPathComponent)
        }
    }
}

