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
    @State private var showPhotoLibrary = false
    @State private var qualityWarning: String? = nil
    @State private var showDetailedSummary = false

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

                    // 资料完整度工作台
                    dataReadinessCard

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
                Button("从相册上传病例") { vm.uploadDocType = "record"; showPhotoLibrary = true }
                Button("从相册上传报告") { vm.uploadDocType = "exam"; showPhotoLibrary = true }
                Button("取消", role: .cancel) {}
            }
            .sheet(isPresented: $vm.showDocumentPicker) {
                DocumentPickerView(
                    onPick: { data, fileName in
                        handleUpload(data: data, fileName: fileName)
                    },
                    onError: { message in
                        vm.errorMessage = message
                    }
                )
            }
            .fullScreenCover(isPresented: $showCamera) {
                CameraImagePicker(
                    onPick: { data, name in
                        handleUpload(data: data, fileName: name)
                    },
                    fileNamePrefix: "health_camera"
                )
                .ignoresSafeArea()
            }
            .sheet(isPresented: $showPhotoLibrary) {
                CameraImagePicker(
                    onPick: { data, name in
                        handleUpload(data: data, fileName: name)
                    },
                    sourceType: .photoLibrary,
                    fileNamePrefix: "health_album"
                )
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

    // MARK: - 资料完整度

    private var dataReadiness: Double {
        var score = 0.18
        if vm.recordCount > 0 { score += 0.24 }
        if vm.examCount > 0 { score += 0.24 }
        if !vm.summary.isEmpty { score += 0.18 }
        if trendVM.trends.contains(where: { !$0.points.isEmpty }) { score += 0.16 }
        return min(score, 1)
    }

    private var readinessText: String {
        switch dataReadiness {
        case 0.75...: return "资料较完整，可以整理给医生看的摘要"
        case 0.45..<0.75: return "已有基础资料，建议补齐体检或病例"
        default: return "先上传病例/体检，小捷才能做有效分析"
        }
    }

    private var dataReadinessCard: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .top, spacing: 12) {
                ZStack {
                    Circle()
                        .fill(
                            LinearGradient(
                                colors: [Color.appGradientStart, Color.appGradientEnd],
                                startPoint: .topLeading,
                                endPoint: .bottomTrailing
                            )
                        )
                        .frame(width: 48, height: 48)
                    Image(systemName: "heart.text.square.fill")
                        .foregroundColor(.white)
                        .font(.title3.bold())
                }
                VStack(alignment: .leading, spacing: 4) {
                    Text("健康资料完整度")
                        .font(.headline)
                        .foregroundColor(.appText)
                    Text(readinessText)
                        .font(.caption)
                        .foregroundColor(.appMuted)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer()
                Text("\(Int(dataReadiness * 100))%")
                    .font(.title3.bold())
                    .foregroundColor(.appPrimary)
            }

            ProgressView(value: dataReadiness)
                .tint(.appPrimary)

            HStack(spacing: 8) {
                readinessMetric(title: "病例", value: "\(vm.recordCount)", icon: "doc.text")
                readinessMetric(title: "体检", value: "\(vm.examCount)", icon: "cross.case")
                readinessMetric(title: "趋势", value: "\(trendVM.trends.count)", icon: "chart.xyaxis.line")
            }

            HStack(spacing: 10) {
                Button {
                    vm.showUploadSheet = true
                } label: {
                    Label("上传资料", systemImage: "arrow.up.doc.fill")
                }
                .primaryGradientButtonStyle()

                Button {
                    Task { await vm.generateSummary() }
                } label: {
                    Label(vm.summary.isEmpty ? "生成总结" : "重新总结", systemImage: "sparkles")
                        .font(.subheadline.bold())
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 12)
                }
                .buttonStyle(.bordered)
                .tint(.appPrimary)
            }
        }
        .cardStyle()
    }

    private func readinessMetric(title: String, value: String, icon: String) -> some View {
        HStack(spacing: 8) {
            Image(systemName: icon)
                .font(.caption.bold())
                .foregroundColor(.appPrimary)
            VStack(alignment: .leading, spacing: 1) {
                Text(value)
                    .font(.subheadline.bold())
                    .foregroundColor(.appText)
                Text(title)
                    .font(.caption2)
                    .foregroundColor(.appMuted)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(10)
        .background(Color.appPrimary.opacity(0.06))
        .clipShape(RoundedRectangle(cornerRadius: 10))
    }

    // MARK: - AI 总结

    private var aiSummaryCard: some View {
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
                    Button {
                        Task { await vm.generateSummary() }
                    } label: {
                        Image(systemName: "arrow.triangle.2.circlepath")
                            .foregroundColor(.appPrimary)
                    }
                    .buttonStyle(.plain)
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
                let brief = healthSummaryBrief(from: vm.summary)
                VStack(alignment: .leading, spacing: 10) {
                    AISummaryBriefGroup(title: "最重要指标", items: brief.indicators)
                    AISummaryBriefGroup(title: "最重要建议", items: brief.suggestions)
                }
                .padding(12)
                .background(Color.appPrimary.opacity(0.06))
                .overlay(
                    RoundedRectangle(cornerRadius: 12)
                        .stroke(Color.appPrimary.opacity(0.18), lineWidth: 1)
                )
                .clipShape(RoundedRectangle(cornerRadius: 12))

                Button {
                    withAnimation(.easeInOut(duration: 0.18)) {
                        showDetailedSummary.toggle()
                    }
                } label: {
                    HStack(spacing: 4) {
                        Text(showDetailedSummary ? "收起详细分析" : "查看详细分析")
                        Image(systemName: showDetailedSummary ? "chevron.up" : "chevron.down")
                    }
                    .font(.caption.bold())
                    .foregroundColor(.appPrimary)
                    .padding(.vertical, 4)
                }
                .buttonStyle(.plain)

                if showDetailedSummary {
                    Divider()
                    MarkdownTextView(text: vm.summary)
                }

                if !vm.summaryUpdatedAt.isEmpty {
                    Text("更新于 \(vm.summaryUpdatedAt)")
                        .font(.caption2)
                        .foregroundColor(.appMuted)
                }
            } else {
                Button {
                    Task { await vm.generateSummary() }
                } label: {
                    VStack(spacing: 4) {
                        Text("点击生成 AI 健康总结")
                            .font(.subheadline)
                            .foregroundColor(.appPrimary)
                        Text("将综合您的所有病例和体检数据进行分析")
                            .font(.caption)
                            .foregroundColor(.appMuted)
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 6)
                }
                .buttonStyle(.plain)
            }
        }
        .cardStyle()
    }

    // MARK: - 病史整理入口（与 Android 对齐）
    private var patientHistoryEntry: some View {
        HStack(spacing: 12) {
            ZStack {
                RoundedRectangle(cornerRadius: 14)
                    .fill(Color.appPrimary.opacity(0.10))
                    .frame(width: 46, height: 46)
                Image(systemName: "stethoscope")
                    .font(.title3.bold())
                    .foregroundColor(.appPrimary)
            }
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 6) {
                    Text("病史整理")
                        .font(.headline)
                        .foregroundColor(.appText)
                    Text("就诊前")
                        .font(.caption2.bold())
                        .padding(.horizontal, 7)
                        .padding(.vertical, 3)
                        .background(Color.appAccent.opacity(0.12))
                        .foregroundColor(.appAccent)
                        .clipShape(Capsule())
                }
                Text("把诊断、用药、过敏和异常检查整理成医生可读摘要")
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

private struct AISummaryBrief {
    let indicators: [String]
    let suggestions: [String]
}

private struct AISummaryBriefGroup: View {
    let title: String
    let items: [String]

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title)
                .font(.caption.bold())
                .foregroundColor(.appPrimary)
            ForEach(Array(items.prefix(3).enumerated()), id: \.offset) { idx, item in
                HStack(alignment: .top, spacing: 8) {
                    Text("\(idx + 1)")
                        .font(.caption2.bold())
                        .foregroundColor(.white)
                        .frame(width: 18, height: 18)
                        .background(Color.appPrimary)
                        .clipShape(Circle())
                    Text(item)
                        .font(.caption)
                        .foregroundColor(.appText)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
    }
}

private func healthSummaryBrief(from full: String) -> AISummaryBrief {
    let cleaned = full
        .components(separatedBy: .newlines)
        .map(cleanSummaryLine)
        .filter { !$0.isEmpty && !$0.hasPrefix("#") }

    let indicatorKeywords = [
        "血糖", "糖化", "HbA1c", "血压", "血脂", "胆固醇", "甘油三酯",
        "BMI", "尿酸", "肌酐", "指标", "异常", "风险", "偏高", "偏低", "升高", "降低"
    ]
    let suggestionKeywords = [
        "建议", "应", "需要", "需", "控制", "复查", "监测", "调整", "保持",
        "避免", "增加", "减少", "咨询", "就医", "随访", "记录"
    ]

    let indicators = uniqueLines(cleaned.filter { containsAny($0, indicatorKeywords) })
    let suggestions = uniqueLines(cleaned.filter { containsAny($0, suggestionKeywords) })
    let fallback = uniqueLines(cleaned)

    let finalIndicators = Array((indicators.isEmpty ? fallback : indicators).prefix(3))
    let remainingFallback = fallback.filter { !finalIndicators.contains($0) }
    let finalSuggestions = Array((suggestions.isEmpty ? remainingFallback : suggestions).prefix(3))
    return AISummaryBrief(
        indicators: finalIndicators.isEmpty ? ["暂无可提炼的关键指标"] : finalIndicators,
        suggestions: finalSuggestions.isEmpty ? ["暂无可提炼的重点建议"] : finalSuggestions
    )
}

private func cleanSummaryLine(_ raw: String) -> String {
    var line = raw.trimmingCharacters(in: .whitespacesAndNewlines)
    while line.hasPrefix("-") || line.hasPrefix("•") || line.hasPrefix("*") {
        line.removeFirst()
        line = line.trimmingCharacters(in: .whitespacesAndNewlines)
    }
    if let range = line.range(of: #"^\d+[\.\)、]\s*"#, options: .regularExpression) {
        line.removeSubrange(range)
    }
    line = line
        .replacingOccurrences(of: "**", with: "")
        .replacingOccurrences(of: "__", with: "")
        .replacingOccurrences(of: "`", with: "")
        .trimmingCharacters(in: .whitespacesAndNewlines)
    return line
}

private func containsAny(_ text: String, _ keywords: [String]) -> Bool {
    keywords.contains { text.localizedCaseInsensitiveContains($0) }
}

private func uniqueLines(_ lines: [String]) -> [String] {
    var seen = Set<String>()
    var result: [String] = []
    for line in lines {
        let key = line.replacingOccurrences(of: " ", with: "")
        guard !seen.contains(key) else { continue }
        seen.insert(key)
        result.append(line)
    }
    return result
}

// MARK: - 文件选择器

struct DocumentPickerView: UIViewControllerRepresentable {
    let onPick: (Data, String) -> Void
    var onError: ((String) -> Void)? = nil

    func makeUIViewController(context: Context) -> UIDocumentPickerViewController {
        let types: [UTType] = [.pdf, .image, .jpeg, .png, .heic, .commaSeparatedText]
        let picker = UIDocumentPickerViewController(forOpeningContentTypes: types, asCopy: true)
        picker.delegate = context.coordinator
        return picker
    }

    func updateUIViewController(_ uiViewController: UIDocumentPickerViewController, context: Context) {}

    func makeCoordinator() -> Coordinator {
        Coordinator(onPick: onPick, onError: onError)
    }

    class Coordinator: NSObject, UIDocumentPickerDelegate {
        let onPick: (Data, String) -> Void
        let onError: ((String) -> Void)?

        init(onPick: @escaping (Data, String) -> Void, onError: ((String) -> Void)?) {
            self.onPick = onPick
            self.onError = onError
        }

        func documentPicker(_ controller: UIDocumentPickerViewController, didPickDocumentsAt urls: [URL]) {
            guard let url = urls.first else { return }
            let didAccess = url.startAccessingSecurityScopedResource()
            defer {
                if didAccess {
                    url.stopAccessingSecurityScopedResource()
                }
            }
            do {
                let data = try LocalFileDataLoader.read(url, options: .mappedIfSafe)
                onPick(data, url.lastPathComponent)
            } catch {
                onError?("无法读取所选文件：\(error.localizedDescription)")
            }
        }
    }
}
