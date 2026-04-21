import Foundation

// MARK: - Demo 多组学数据模型（与后端 /api/omics/demo/* 对应）

struct OmicsDemoItem: Codable, Identifiable, Hashable {
    let name: String
    let key: String
    let value: Double
    let unit: String
    let status: String      // normal | high | low | borderline
    let reference: String
    let story_zh: String
    let relevance: [String]

    var id: String { key }
}

struct MetabolomicsDemoPanel: Codable {
    let is_demo: Bool
    let metabolic_age_delta_years: Double
    let overall_risk: String
    let summary: String
    let items: [OmicsDemoItem]
}

struct ProteomicsDemoPanel: Codable {
    let is_demo: Bool
    let inflammation_score: Double
    let summary: String
    let items: [OmicsDemoItem]
}

struct GeneVariant: Codable, Identifiable, Hashable {
    let name: String
    let key: String
    let genotype: String
    let risk_level: String          // 低 / 中 / 较高
    let relevance: [String]
    let story_zh: String

    var id: String { key }
}

struct GenomicsDemoPanel: Codable {
    let is_demo: Bool
    let prs: PRSScores
    let summary: String
    let variants: [GeneVariant]
}

struct PRSScores: Codable, Hashable {
    let t2d: Double
    let cvd: Double
    let masld: Double
}

struct MicrobiomeTaxon: Codable, Identifiable, Hashable {
    let name: String
    let key: String
    let relative_abundance: Double
    let reference: String
    let status: String
    let relevance: [String]
    let story_zh: String

    var id: String { key }
}

struct MicrobiomeDemoPanel: Codable {
    let is_demo: Bool
    let shannon: Double
    let scfa_producer_pct: Double
    let summary: String
    let taxa: [MicrobiomeTaxon]
}

struct OmicsTriadInsight: Codable {
    let is_demo: Bool
    let metabolomics_score: Double
    let cgm_score: Double
    let heart_score: Double
    let overlap_score: Double
    let insights: [String]
}
