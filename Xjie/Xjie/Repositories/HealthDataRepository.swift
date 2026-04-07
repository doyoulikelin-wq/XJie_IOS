import Foundation

/// 健康数据仓库协议 — ARCH-05: 统一管理 documents/summary 的数据获取
/// TODO: 未来可添加本地缓存层
protocol HealthDataRepositoryProtocol: Sendable {
    func fetchDocuments(docType: String) async throws -> [HealthDocument]
    func fetchDocument(id: String) async throws -> HealthDocument
    func uploadDocument(data: Data, fileName: String, docType: String) async throws -> HealthDocument
    func deleteDocument(id: String) async throws
    func fetchSummary() async throws -> HealthDataSummary
    func generateSummary() async throws -> HealthDataSummary
    func generateSummaryAsync() async throws -> SummaryTaskResponse
    func getSummaryTask(taskId: String) async throws -> SummaryTaskResponse
}

/// 健康数据仓库 — 通过 APIService 访问后端
actor HealthDataRepository: HealthDataRepositoryProtocol {
    private let api: APIServiceProtocol

    init(api: APIServiceProtocol = APIService.shared) {
        self.api = api
    }

    func fetchDocuments(docType: String) async throws -> [HealthDocument] {
        let path = URLBuilder.path("/api/health-data/documents", queryItems: [
            URLQueryItem(name: "doc_type", value: docType)
        ])
        let res: DocumentListResponse = try await api.get(path)
        return res.items ?? []
    }

    func fetchDocument(id: String) async throws -> HealthDocument {
        try await api.get("/api/health-data/documents/\(id)")
    }

    func uploadDocument(data: Data, fileName: String, docType: String) async throws -> HealthDocument {
        let mimeType = MIMETypeHelper.mimeType(forFileName: fileName)
        let responseData = try await api.uploadFile(
            "/api/health-data/upload",
            fileData: data, fileName: fileName, mimeType: mimeType,
            formData: ["doc_type": docType, "name": ""]
        )
        return try JSONDecoder().decode(HealthDocument.self, from: responseData)
    }

    func deleteDocument(id: String) async throws {
        try await api.deleteVoid("/api/health-data/documents/\(id)")
    }

    func fetchSummary() async throws -> HealthDataSummary {
        try await api.get("/api/health-data/summary")
    }

    func generateSummary() async throws -> HealthDataSummary {
        try await api.post("/api/health-data/summary/generate", body: nil)
    }

    func generateSummaryAsync() async throws -> SummaryTaskResponse {
        try await api.post("/api/health-data/summary/generate-async")
    }

    func getSummaryTask(taskId: String) async throws -> SummaryTaskResponse {
        try await api.get("/api/health-data/summary/task/\(taskId)")
    }
}
