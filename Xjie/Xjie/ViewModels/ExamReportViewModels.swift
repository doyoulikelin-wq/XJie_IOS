import Foundation

/// 按日期分组的体检数据
struct ExamDateGroup: Identifiable {
    let id: String          // date string as key
    let displayDate: String // formatted display date
    let items: [HealthDocument]
}

@MainActor
final class ExamReportListViewModel: ObservableObject {
    @Published var loading = false
    @Published var uploading = false
    @Published var uploadStage: String = ""
    @Published var groupedItems: [ExamDateGroup] = []
    @Published var showDocumentPicker = false
    @Published var showDeleteAlert = false
    @Published var deleteId: String?
    @Published var errorMessage: String?
    @Published var successMessage: String?

    private let repository: HealthDataRepositoryProtocol

    init(repository: HealthDataRepositoryProtocol = HealthDataRepository()) {
        self.repository = repository
    }

    func fetchList() async {
        loading = true
        defer { loading = false }
        do {
            let fetched = try await repository.fetchDocuments(docType: "exam")
            guard !Task.isCancelled else { return }
            groupedItems = Self.groupByDate(fetched)
        } catch {
            guard !Task.isCancelled else { return }
            errorMessage = error.localizedDescription
        }
    }

    func uploadExam(data: Data, fileName: String) async {
        uploading = true
        uploadStage = "正在上传文件…"
        defer { uploading = false; uploadStage = "" }
        do {
            let doc = try await repository.uploadDocument(data: data, fileName: fileName, docType: "exam")

            if doc.extraction_status == "pending" {
                uploadStage = "AI 正在识别内容…"
                let result = await pollUntilDone(docId: doc.id)
                if result == "failed" {
                    errorMessage = "AI 无法识别该文件，请确认上传的是有效体检报告照片"
                    await fetchList()
                    return
                }
            }

            successMessage = "体检报告上传成功"
            await fetchList()
        } catch {
            if error.localizedDescription.contains("无法识别") {
                errorMessage = "上传的文件不是有效的体检报告，请重新选择"
            } else {
                errorMessage = error.localizedDescription
            }
        }
    }

    /// Poll document status every 2s, up to 90s
    private func pollUntilDone(docId: String) async -> String {
        let maxAttempts = 45
        for _ in 0..<maxAttempts {
            try? await Task.sleep(nanoseconds: 2_000_000_000)
            guard !Task.isCancelled else { return "failed" }
            do {
                let doc = try await repository.fetchDocument(id: docId)
                if doc.extraction_status != "pending" {
                    return doc.extraction_status ?? "done"
                }
            } catch {
                continue
            }
        }
        return "failed" // timeout
    }

    func deleteItem(id: String) {
        deleteId = id
        showDeleteAlert = true
    }

    func confirmDelete() async {
        guard let id = deleteId else { return }
        do {
            try await repository.deleteDocument(id: id)
            await fetchList()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    // MARK: - Grouping

    private static func groupByDate(_ docs: [HealthDocument]) -> [ExamDateGroup] {
        var groups: [String: [HealthDocument]] = [:]
        let dateFormatter = DateFormatter()
        dateFormatter.dateFormat = "yyyy-MM-dd"

        for doc in docs {
            let key: String
            if let dateStr = doc.doc_date, let date = parseDate(dateStr) {
                key = dateFormatter.string(from: date)
            } else {
                key = "未知日期"
            }
            groups[key, default: []].append(doc)
        }

        return groups
            .sorted { $0.key > $1.key }       // newest date first
            .map { ExamDateGroup(id: $0.key, displayDate: $0.key, items: $0.value) }
    }

    private static func parseDate(_ str: String) -> Date? {
        let fmts = ["yyyy-MM-dd'T'HH:mm:ss", "yyyy-MM-dd'T'HH:mm:ss.SSSSSS", "yyyy-MM-dd"]
        for fmt in fmts {
            let df = DateFormatter()
            df.dateFormat = fmt
            df.locale = Locale(identifier: "en_US_POSIX")
            if let d = df.date(from: str) { return d }
        }
        return nil
    }
}
