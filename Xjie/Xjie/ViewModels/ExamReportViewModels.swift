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
            let fetched = try await repository.fetchDocuments(docType: "exam")
            try operationSession.validate(token)
            groupedItems = Self.groupByDate(fetched)
        } catch is CancellationError {
            return
        } catch {
            guard operationSession.isCurrent(token) else { return }
            errorMessage = error.localizedDescription
        }
    }

    func uploadExam(data: Data, fileName: String) async {
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
                docType: "exam",
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
                errorMessage = "上传的文件不是有效的体检报告，请重新选择"
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
        groupedItems = []
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
