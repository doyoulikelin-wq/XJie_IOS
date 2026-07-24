import Foundation

/// 就医助手的数据边界；生成动作必须绑定发起时的账号范围。
protocol MedicalAssistantRepositoryProtocol: Sendable {
    /// 获取最近一次概况和报告时间。
    func fetchOverview() async throws -> MedicalAssistantOverview
    /// 请求服务端判断新鲜度并生成概况。
    /// - Parameter expectedAccountScope: 点击按钮时的登录账号范围，刷新 token 后仍必须保持一致。
    func generateOverview(expectedAccountScope: String) async throws -> MedicalAssistantOverview
}

actor MedicalAssistantRepository: MedicalAssistantRepositoryProtocol {
    private let api: APIServiceProtocol

    /// - Parameter api: 可注入的网络服务；生产环境默认使用共享 APIService。
    init(api: APIServiceProtocol = APIService.shared) {
        self.api = api
    }

    func fetchOverview() async throws -> MedicalAssistantOverview {
        try await api.get("/api/health-data/medical-assistant/overview")
    }

    func generateOverview(expectedAccountScope: String) async throws -> MedicalAssistantOverview {
        try await api.postAccountBound(
            "/api/health-data/medical-assistant/overview/generate",
            body: nil,
            expectedAccountScope: expectedAccountScope
        )
    }
}
