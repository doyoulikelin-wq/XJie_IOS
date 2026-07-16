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
    @Published private(set) var activeReportWorkflow: HealthReportWorkflowRoute?
    @Published private(set) var activeReportTitle = "报告"
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
            if Utils.parseISO(updatedAt) != nil {
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

    @discardableResult
    func uploadFile(data: Data, fileName: String) async -> HealthDocument? {
        uploading = true
        uploadStage = "正在上传文件…"
        backgroundTaskHint = nil
        do {
            let doc = try await repository.uploadDocument(data: data, fileName: fileName, docType: uploadDocType)
            uploading = false
            uploadStage = ""
            activeReportTitle = fileName
            applyUploadState(doc, fileName: fileName)
            if shouldPoll(doc) {
                // 轮询只更新识别/确认状态；任何 OCR 完成状态都不等同于可信入库。
                Task { @MainActor [weak self] in
                    guard let self else { return }
                    let refreshed = await self.pollDoc(id: doc.id)
                    if let refreshed {
                        self.applyUploadState(refreshed, fileName: fileName)
                    } else {
                        self.backgroundTaskHint = "报告仍在处理；确认前不会进入趋势、画像、评分或 AI 上下文。可稍后到历史报告继续查看。"
                        self.infoMessage = "报告仍在处理，可稍后继续查看。"
                    }
                    await self.fetchAll()
                }
            } else {
                await fetchAll()
            }
            return doc
        } catch {
            uploading = false
            uploadStage = ""
            backgroundTaskHint = nil
            errorMessage = error.localizedDescription
            return nil
        }
    }

    private func shouldPoll(_ document: HealthDocument) -> Bool {
        if let route = document.reportWorkflowRoute {
            return route.status == .draft || route.status == .uploading || route.status == .recognizing
        }
        return document.extraction_status?.lowercased() == "pending"
    }

    /// 仅用于 UI 轮询；超时代表后端可能仍在处理，不按失败或入库处理。
    private func pollDoc(id: String) async -> HealthDocument? {
        for _ in 0..<45 {
            try? await Task.sleep(for: .seconds(2))
            if Task.isCancelled { return nil }
            if let document = try? await repository.fetchDocument(id: id) {
                if let route = document.reportWorkflowRoute {
                    activeReportWorkflow = route
                    if route.status != .draft,
                       route.status != .uploading,
                       route.status != .recognizing {
                        return document
                    }
                } else if document.extraction_status?.lowercased() != "pending" {
                    return document
                }
            }
        }
        return nil
    }

    private func applyUploadState(_ document: HealthDocument, fileName: String) {
        if let route = document.reportWorkflowRoute {
            activeReportWorkflow = route
            let duplicatePrefix = route.isDuplicate ? "检测到同一份报告，已恢复原任务。" : ""
            switch route.status {
            case .draft, .uploading, .recognizing:
                backgroundTaskHint = "\(duplicatePrefix)正在识别候选字段；确认前不会进入趋势、画像、评分或 AI 上下文。"
                infoMessage = "\(duplicatePrefix)报告已上传，正在识别。"
            case .awaitingConfirmation:
                backgroundTaskHint = "\(duplicatePrefix)识别完成，等待你检查字段并确认整份报告。确认前不会作为可信健康数据使用。"
                infoMessage = "\(duplicatePrefix)识别完成，请到报告页面检查并确认。"
                Task { await NotificationScheduler.shared.scheduleReportRecognitionComplete(fileName: fileName) }
            case .committing:
                backgroundTaskHint = "报告确认请求正在处理，请勿重复提交。"
                infoMessage = "报告正在按确认结果入库。"
            case .completedScorePending:
                backgroundTaskHint = "报告已确认入库，评分仍在更新。"
                infoMessage = "报告已确认；评分待更新。"
            case .completed:
                backgroundTaskHint = nil
                infoMessage = "报告已确认入库，评分流程已完成。"
            case .failed:
                backgroundTaskHint = nil
                errorMessage = "报告识别失败，请确认文件清晰完整后重试。"
            case .unknown:
                backgroundTaskHint = "报告已上传，但状态暂时无法识别；确认前不会作为可信健康数据使用。"
                infoMessage = "报告状态待刷新。"
            }
            return
        }

        activeReportWorkflow = nil
        if document.extraction_status?.lowercased() == "pending" {
            backgroundTaskHint = "报告已上传，正在进行历史兼容识别；该流程没有报告级确认，结果不会作为可信趋势、评分或 AI 上下文。"
            infoMessage = "报告已上传，正在识别。"
        } else if document.extraction_status?.lowercased() == "failed" {
            backgroundTaskHint = nil
            errorMessage = "报告识别失败，请确认文件清晰完整后重试。"
        } else {
            backgroundTaskHint = "识别已结束，但这是历史未验证流程，不能标为已入库或用于 AI/评分。"
            infoMessage = "识别已结束；这份报告仍需新版报告级确认。"
        }
    }

    /// 用户手动关闭后台提示。
    func dismissBackgroundHint() { backgroundTaskHint = nil }
}
