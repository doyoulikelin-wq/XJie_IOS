import Foundation

@MainActor
final class MedicalAssistantViewModel: ObservableObject {
    @Published private(set) var overview: MedicalAssistantOverview?
    @Published private(set) var loading = false
    @Published private(set) var generating = false
    @Published var errorMessage: String?
    @Published var noticeMessage: String?

    private let repository: MedicalAssistantRepositoryProtocol
    private let currentAccountScope: @MainActor () -> String?
    private var activeAccountScope: String?
    private var loadGeneration = UUID()

    /// - Parameters:
    ///   - repository: 概况读取与生成的数据仓库，测试可注入确定性实现。
    ///   - currentAccountScope: 返回当前登录账号范围，用来拒绝账号切换后的迟到响应。
    init(
        repository: MedicalAssistantRepositoryProtocol = MedicalAssistantRepository(),
        currentAccountScope: @escaping @MainActor () -> String? = {
            AuthManager.shared.accountScope
        }
    ) {
        self.repository = repository
        self.currentAccountScope = currentAccountScope
    }

    /// 加载最新服务端快照。
    /// - Parameter accountScope: 页面出现时捕获的登录账号范围。
    func load(accountScope: String?) async {
        loadGeneration = UUID()
        let generation = loadGeneration
        activeAccountScope = accountScope
        errorMessage = nil
        noticeMessage = nil

        guard let accountScope, currentAccountScope() == accountScope else {
            overview = nil
            errorMessage = "无法确认当前登录账号，已停止读取病人概况。"
            return
        }

        loading = true
        defer {
            if loadGeneration == generation { loading = false }
        }
        do {
            let response = try await repository.fetchOverview()
            guard loadGeneration == generation,
                  activeAccountScope == accountScope,
                  currentAccountScope() == accountScope,
                  response.subject_user_id > 0 else { return }
            overview = response
        } catch {
            guard loadGeneration == generation,
                  currentAccountScope() == accountScope else { return }
            errorMessage = error.localizedDescription
        }
    }

    /// 让服务端原子判断是否有更新并生成概况。
    /// - Parameter accountScope: 用户点击按钮时的登录账号范围。
    func generate(accountScope: String?) async {
        guard !generating,
              let accountScope,
              activeAccountScope == accountScope,
              currentAccountScope() == accountScope else {
            errorMessage = "登录账号已变化，请返回后重新打开就医助手。"
            return
        }

        generating = true
        errorMessage = nil
        noticeMessage = nil
        defer { generating = false }
        do {
            let response = try await repository.generateOverview(
                expectedAccountScope: accountScope
            )
            guard activeAccountScope == accountScope,
                  currentAccountScope() == accountScope,
                  response.subject_user_id > 0 else { return }
            overview = response
            switch response.generationResult {
            case .generated:
                noticeMessage = "病人概况已更新"
            case .noInformationUpdate:
                noticeMessage = "无信息更新"
            case .noReports:
                noticeMessage = "还没有可用于生成概况的报告"
            case .reportProcessing:
                noticeMessage = "最新报告尚未完成确认或入库"
            case .loaded:
                break
            case .unknown:
                errorMessage = "服务端返回了无法识别的生成状态，请稍后重试。"
            }
        } catch {
            guard currentAccountScope() == accountScope else { return }
            errorMessage = error.localizedDescription
        }
    }
}
