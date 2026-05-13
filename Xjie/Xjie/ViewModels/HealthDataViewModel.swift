import Foundation

@MainActor
final class HealthDataViewModel: ObservableObject {
    @Published var loading = false
    @Published var summary = ""
    @Published var summaryUpdatedAt = ""
    @Published var generatingSummary = false
    @Published var summaryProgress: Double = 0
    @Published var summaryStage: String = ""
    @Published var recordCount = 0
    @Published var examCount = 0
    @Published var showUploadSheet = false
    @Published var showDocumentPicker = false
    @Published var uploadDocType = "record"
    @Published var uploading = false
    @Published var uploadStage = ""
    /// 上传完成后「AI 后台识别中」提示（可被用户手动关闭）。
    @Published var backgroundTaskHint: String? = nil
    @Published var errorMessage: String?
    @Published var infoMessage: String?

    private let repository: HealthDataRepositoryProtocol

    init(repository: HealthDataRepositoryProtocol = HealthDataRepository()) {
        self.repository = repository
    }

    func fetchAll() async {
        loading = true
        defer { loading = false }

        let summaryRes = try? await repository.fetchSummary()
        guard !Task.isCancelled else { return }
        summary = summaryRes?.summary_text ?? ""
        if let updatedAt = summaryRes?.updated_at {
            if let date = Utils.parseISO(updatedAt) {
                summaryUpdatedAt = Utils.formatDate(updatedAt)
            }
        }
        recordCount = (try? await repository.fetchDocuments(docType: "record"))?.count ?? 0
        examCount = (try? await repository.fetchDocuments(docType: "exam"))?.count ?? 0
    }

    func generateSummary() async {
        guard !generatingSummary else { return }
        generatingSummary = true
        summaryProgress = 0
        summaryStage = "提交任务..."
        infoMessage = "AI 报告生成已开始，您可以继续使用其他功能。"
        defer { generatingSummary = false; summaryStage = "" }
        do {
            let task = try await repository.generateSummaryAsync()
            let taskId = task.task_id

            while !Task.isCancelled {
                try await Task.sleep(for: .seconds(3))
                guard !Task.isCancelled else { return }

                let status = try await repository.getSummaryTask(taskId: taskId)
                summaryProgress = status.progress_pct ?? 0

                switch status.stage {
                case "l1":
                    summaryStage = "分析第 \(status.stage_current ?? 0)/\(status.stage_total ?? 0) 次检查..."
                case "l2":
                    summaryStage = "汇总第 \(status.stage_current ?? 0)/\(status.stage_total ?? 0) 年趋势..."
                case "l3":
                    summaryStage = "生成最终报告..."
                default:
                    summaryStage = "准备中..."
                }

                if status.status == "done" {
                    let result = try await repository.fetchSummary()
                    guard !Task.isCancelled else { return }
                    summary = result.summary_text ?? ""
                    summaryProgress = 1.0
                    return
                }

                if status.status == "failed" {
                    errorMessage = "生成失败: \(status.error_message ?? "未知错误")"
                    return
                }
            }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func uploadFile(data: Data, fileName: String) async {
        uploading = true
        uploadStage = "正在上传文件…"
        backgroundTaskHint = nil
        do {
            let doc = try await repository.uploadDocument(data: data, fileName: fileName, docType: uploadDocType)
            uploading = false
            uploadStage = ""
            if doc.extraction_status == "pending" {
                backgroundTaskHint = "AI 正在后台识别文件内容，您可以离开此页继续使用。识别完成后会自动出现在「关注指标趋势」中。"
                infoMessage = "上传成功，AI 正在后台识别。"
                // 后台轮询：不阻塞 UI，完成后自动清除提示并刷新计数
                Task { @MainActor [weak self] in
                    guard let self else { return }
                    let status = await self.pollDoc(id: doc.id)
                    if status == "failed" {
                        self.errorMessage = "AI 无法识别该文件，请重新拍照或换张更清晰的图片。"
                    } else {
                        self.infoMessage = "AI 识别完成"
                    }
                    self.backgroundTaskHint = nil
                    await self.fetchAll()
                }
            } else {
                infoMessage = "上传成功"
                await fetchAll()
            }
        } catch {
            uploading = false
            uploadStage = ""
            backgroundTaskHint = nil
            errorMessage = error.localizedDescription
        }
    }

    /// 仅用于 UI 轮询，如果超过 90 秒返回 failed。但后端可能仍在进行。
    private func pollDoc(id: String) async -> String {
        for _ in 0..<45 {
            try? await Task.sleep(for: .seconds(2))
            if Task.isCancelled { return "cancelled" }
            if let d = try? await repository.fetchDocument(id: id),
               d.extraction_status != "pending" {
                return d.extraction_status ?? "done"
            }
        }
        return "failed"
    }

    /// 用户手动关闭后台提示。
    func dismissBackgroundHint() { backgroundTaskHint = nil }
}
