import Foundation

@MainActor
final class MedicalRecordListViewModel: ObservableObject {
    @Published var loading = false
    @Published var uploading = false
    @Published var uploadStage: String = ""
    @Published var items: [HealthDocument] = []
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
            let fetched = try await repository.fetchDocuments(docType: "record")
            guard !Task.isCancelled else { return }
            items = fetched
        } catch {
            guard !Task.isCancelled else { return }
            errorMessage = error.localizedDescription
        }
    }

    func uploadRecord(data: Data, fileName: String) async {
        uploading = true
        uploadStage = "正在上传文件…"
        defer { uploading = false; uploadStage = "" }
        do {
            let doc = try await repository.uploadDocument(data: data, fileName: fileName, docType: "record")

            if doc.extraction_status == "pending" {
                uploadStage = "AI 正在识别内容…"
                let result = await pollUntilDone(docId: doc.id)
                if result == "failed" {
                    errorMessage = "AI 无法识别该文件，请确认上传的是有效病例照片"
                    await fetchList()
                    return
                }
            }

            successMessage = "病例上传成功"
            await fetchList()
        } catch {
            if error.localizedDescription.contains("无法识别") {
                errorMessage = "上传的文件不是有效的病例文档，请重新选择"
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
}

/// 文档详情 ViewModel — 病例详情 & 体检详情共用
@MainActor
final class DocumentDetailViewModel: ObservableObject {
    @Published var loading = false
    @Published var doc: HealthDocument?
    @Published var errorMessage: String?

    private let api: APIServiceProtocol

    init(api: APIServiceProtocol = APIService.shared) {
        self.api = api
    }

    func fetchDetail(id: String) async {
        loading = true
        defer { loading = false }
        do {
            doc = try await api.get("/api/health-data/documents/\(id)")
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
