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
    private let operationSession: HealthDataOperationSession

    init(
        repository: HealthDataRepositoryProtocol = HealthDataRepository(),
        currentAccountScope: @escaping @MainActor @Sendable () -> String? = {
            AuthManager.shared.accountScope
        }
    ) {
        self.repository = repository
        self.operationSession = HealthDataOperationSession(
            currentAccountScope: currentAccountScope
        )
    }

    func fetchList() async {
        guard let token = operationSession.currentToken() else { return }
        await fetchList(token: token)
    }

    private func fetchList(token: HealthDataOperationSession.Token) async {
        loading = true
        defer {
            if operationSession.isCurrent(token) { loading = false }
        }
        do {
            let fetched = try await repository.fetchDocuments(docType: "record")
            try operationSession.validate(token)
            items = fetched
        } catch is CancellationError {
            return
        } catch {
            guard operationSession.isCurrent(token) else { return }
            errorMessage = error.localizedDescription
        }
    }

    func uploadRecord(data: Data, fileName: String) async {
        guard let token = operationSession.beginExclusiveOperation() else {
            errorMessage = "当前登录信息不完整，请重新登录后上传。"
            return
        }
        loading = false
        uploading = true
        uploadStage = "正在上传文件…"
        defer {
            if operationSession.isCurrent(token) {
                uploading = false
                uploadStage = ""
            }
        }
        do {
            let doc = try await repository.uploadDocument(
                data: data,
                fileName: fileName,
                docType: "record",
                expectedAccountScope: token.accountScope
            )
            try operationSession.validate(token)
            if case .workflow(.failed) = doc.reportTrustState {
                errorMessage = doc.reportUploadNotice
            } else {
                successMessage = doc.reportUploadNotice
            }
            await fetchList(token: token)
        } catch is CancellationError {
            return
        } catch {
            guard operationSession.isCurrent(token) else { return }
            if error.localizedDescription.contains("无法识别") {
                errorMessage = "上传的文件不是有效的病例文档，请重新选择"
            } else {
                errorMessage = error.localizedDescription
            }
        }
    }

    func accountDidChange(to accountScope: String?) {
        guard operationSession.accountDidChange(to: accountScope) else { return }
        loading = false
        uploading = false
        uploadStage = ""
        items = []
        showDeleteAlert = false
        deleteId = nil
        errorMessage = nil
        successMessage = nil
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
