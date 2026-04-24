import Foundation

/// 代谢组学分析结果
struct MetabolomicsAnalysis: Codable {
    let summary: String
    let analysis: String
    let riskLevel: String       // "低风险" / "中风险" / "高风险"
    let metabolites: [MetaboliteResult]?

    enum CodingKeys: String, CodingKey {
        case summary, analysis
        case riskLevel = "risk_level"
        case metabolites
    }
}

struct MetaboliteResult: Codable, Identifiable {
    var id: String { name }
    let name: String
    let value: Double?
    let unit: String?
    let status: String?     // "normal" / "high" / "low"
}

/// 模型分析结果占位
struct ModelAnalysisResult: Codable {
    let taskId: String
    let status: String          // "pending" / "running" / "completed" / "failed"
    let result: ModelResultData?

    enum CodingKeys: String, CodingKey {
        case taskId = "task_id"
        case status, result
    }
}

struct ModelResultData: Codable {
    let pathways: [String]?
    let biomarkers: [String]?
    let riskScore: Double?

    enum CodingKeys: String, CodingKey {
        case pathways, biomarkers
        case riskScore = "risk_score"
    }
}

@MainActor
final class OmicsViewModel: ObservableObject {
    @Published var showFilePicker = false
    @Published var uploadedFileName: String?
    @Published var analyzing = false
    @Published var analysisResult: MetabolomicsAnalysis?
    @Published var errorMessage: String?

    // ── Demo 数据 ─────────────────────────────────────
    @Published var demoMetabolomics: MetabolomicsDemoPanel?
    @Published var demoProteomics: ProteomicsDemoPanel?
    @Published var demoGenomics: GenomicsDemoPanel?
    @Published var demoMicrobiome: MicrobiomeDemoPanel?
    @Published var demoTriad: OmicsTriadInsight?
    @Published var demoLoading = false

    /// 根据代谢物/蛋白/菌名称从 /api/literature/retrieve 查询文献
    @Published var citationsCache: [String: [Citation]] = [:]

    private var pickedFileData: Data?
    private var pickedMimeType: String = "text/csv"
    private let api: APIServiceProtocol

    init(api: APIServiceProtocol = APIService.shared) {
        self.api = api
    }

    // MARK: - 加载 demo 数据

    func loadDemoIfNeeded() async {
        if demoMetabolomics != nil && demoProteomics != nil && demoGenomics != nil
            && demoMicrobiome != nil && demoTriad != nil {
            return
        }
        demoLoading = true
        defer { demoLoading = false }
        async let m: MetabolomicsDemoPanel? = try? api.get("/api/omics/demo/metabolomics")
        async let p: ProteomicsDemoPanel? = try? api.get("/api/omics/demo/proteomics")
        async let g: GenomicsDemoPanel? = try? api.get("/api/omics/demo/genomics")
        async let mi: MicrobiomeDemoPanel? = try? api.get("/api/omics/demo/microbiome")
        async let tr: OmicsTriadInsight? = try? api.get("/api/omics/demo/triad")
        let (mv, pv, gv, miv, trv) = await (m, p, g, mi, tr)
        self.demoMetabolomics = mv
        self.demoProteomics = pv
        self.demoGenomics = gv
        self.demoMicrobiome = miv
        self.demoTriad = trv
    }

    // MARK: - 查询文献引用

    func citations(for keyword: String) async -> [Citation] {
        if let cached = citationsCache[keyword] { return cached }
        struct Req: Encodable {
            let query: String
            let topics: [String]
            let top_k: Int
        }
        struct Resp: Decodable {
            let matches: [Citation]
            let used_fallback: Bool
        }
        do {
            let resp: Resp = try await api.post(
                "/api/literature/retrieve",
                body: Req(query: keyword, topics: ["omics"], top_k: 3),
                timeout: nil
            )
            citationsCache[keyword] = resp.matches
            return resp.matches
        } catch {
            return []
        }
    }

    func handlePickedFile(_ url: URL) {
        guard let data = try? Data(contentsOf: url) else {
            errorMessage = "无法读取文件"
            return
        }
        let ext = url.pathExtension.lowercased()
        pickedMimeType = switch ext {
        case "csv": "text/csv"
        case "xlsx", "xls": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        case "pdf": "application/pdf"
        default: "application/octet-stream"
        }
        pickedFileData = data
        uploadedFileName = url.lastPathComponent
        Task { await uploadAndAnalyze() }
    }

    func clearUpload() {
        uploadedFileName = nil
        pickedFileData = nil
        analysisResult = nil
    }

    private func uploadAndAnalyze() async {
        guard let data = pickedFileData, let name = uploadedFileName else { return }
        analyzing = true
        defer { analyzing = false }

        do {
            let responseData = try await api.uploadFile(
                "/api/omics/metabolomics/upload",
                fileData: data,
                fileName: name,
                mimeType: pickedMimeType,
                formData: [:]
            )
            let result = try JSONDecoder().decode(MetabolomicsAnalysis.self, from: responseData)
            analysisResult = result
        } catch {
            errorMessage = "分析失败: \(error.localizedDescription)"
        }
    }
}
