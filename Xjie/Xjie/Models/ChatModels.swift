import Foundation

// MARK: - 文献引用

/// 与后端 schemas/literature.py CitationBundle 对应
struct Citation: Codable, Identifiable, Hashable, Equatable, Sendable {
    let claim_id: Int
    let literature_id: Int
    let claim_text: String
    let evidence_level: String      // L1 / L2 / L3 / L4
    let short_ref: String           // e.g. "Segal et al., Cell 2015"
    let journal: String?
    let year: Int?
    let sample_size: Int?
    let population: String?
    let study_design: String?
    let confidence: String          // high / medium / low
    let score: Double?

    var id: Int { claim_id }

    var studyDesignDisplayText: String? {
        guard let rawValue = study_design?.trimmingCharacters(in: .whitespacesAndNewlines),
              !rawValue.isEmpty else { return nil }
        if Self.containsChineseText(rawValue) { return rawValue }

        let normalized = rawValue
            .lowercased()
            .replacingOccurrences(
                of: #"[^a-z0-9]+"#,
                with: "_",
                options: .regularExpression
            )
            .trimmingCharacters(in: CharacterSet(charactersIn: "_"))

        switch normalized {
        case "systematic_review_meta_analysis", "systematic_review_and_meta_analysis", "meta_analysis":
            return "系统综述与荟萃分析"
        case "systematic_review":
            return "系统综述"
        case "systematic_review_of_observational_studies":
            return "观察性研究系统综述"
        case "mechanistic_observational_study":
            return "机制性观察研究"
        case "clinical_practice_guideline", "practice_guideline", "guideline":
            return "临床实践指南"
        case "rct", "randomized_controlled_trial", "randomised_controlled_trial",
             "randomized_clinical_trial", "randomised_clinical_trial", "randomized_trial":
            return "随机对照试验"
        case "prospective_cohort", "prospective_cohort_study":
            return "前瞻性队列研究"
        case "retrospective_cohort", "retrospective_cohort_study":
            return "回顾性队列研究"
        case "cohort", "cohort_study":
            return "队列研究"
        case "observational_cohort", "observational_cohort_study":
            return "观察性队列研究"
        case "case_control", "case_control_study":
            return "病例对照研究"
        case "cross_sectional", "cross_sectional_study":
            return "横断面研究"
        case "observational", "observational_study":
            return "观察性研究"
        case "clinical_trial", "controlled_clinical_trial":
            return "临床试验"
        case "case_series":
            return "病例系列"
        case "case_report":
            return "病例报告"
        case "mechanism", "mechanistic_study":
            return "机制研究"
        default:
            return "其他研究设计"
        }
    }

    init(
        claim_id: Int,
        literature_id: Int,
        claim_text: String,
        evidence_level: String,
        short_ref: String,
        journal: String?,
        year: Int?,
        sample_size: Int?,
        population: String? = nil,
        study_design: String? = nil,
        confidence: String,
        score: Double?
    ) {
        self.claim_id = claim_id
        self.literature_id = literature_id
        self.claim_text = claim_text
        self.evidence_level = evidence_level
        self.short_ref = short_ref
        self.journal = journal
        self.year = year
        self.sample_size = sample_size
        self.population = population
        self.study_design = study_design
        self.confidence = confidence
        self.score = score
    }

    private static func containsChineseText(_ value: String) -> Bool {
        value.unicodeScalars.contains { scalar in
            (0x3400...0x9FFF).contains(scalar.value) ||
                (0xF900...0xFAFF).contains(scalar.value)
        }
    }
}

// MARK: - 聊天

struct ChatConversation: Codable, Identifiable {
    let id: String
    let title: String?
    let message_count: Int?
    let updated_at: String?
    let created_at: String?
}

/// BUG-01 FIX: id 改为存储属性，避免 computed property 每次访问生成新 UUID
/// 导致 SwiftUI ForEach 无限刷新
struct ChatMessage: Decodable, Identifiable {
    let id: String
    let role: String
    let content: String
    let analysis: String?
    let created_at: String?
    let citations: [Citation]

    enum CodingKeys: String, CodingKey {
        case id, role, content, analysis, created_at, citations
    }

    init(id: String = UUID().uuidString, role: String, content: String, analysis: String? = nil, created_at: String? = nil, citations: [Citation] = []) {
        self.id = id
        self.role = role
        self.content = content
        self.analysis = analysis
        self.created_at = created_at
        self.citations = citations
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        self.id = (try? container.decode(String.self, forKey: .id)) ?? UUID().uuidString
        self.role = try container.decode(String.self, forKey: .role)
        self.content = try container.decode(String.self, forKey: .content)
        self.analysis = try? container.decode(String.self, forKey: .analysis)
        self.created_at = try? container.decode(String.self, forKey: .created_at)
        self.citations = (try? container.decode([Citation].self, forKey: .citations)) ?? []
    }
}

struct ChatRequest: Encodable, Sendable {
    let message: String
    let thread_id: String?
    let client_message_id: String?

    init(message: String, thread_id: String?, client_message_id: String? = nil) {
        self.message = message
        self.thread_id = thread_id
        self.client_message_id = client_message_id
    }
}

struct ChatInteractionRoute: Codable, Equatable, Sendable {
    let version: String
    let route_id: String
    let strategy: String
    let primary_intent: String
    let depth: String
    let safety_level: String
    let subject_type: String
    let needs_literature: Bool
    let max_followups: Int
    let progress_steps: [String]
}

struct ChatResponse: Codable, Sendable {
    let summary: String?
    let analysis: String?
    let answer_markdown: String?
    let confidence: Double?
    let followups: [String]?
    let thread_id: String?
    let message_id: String?
    let response_state: String?
    let interaction_route: ChatInteractionRoute?
    let quality_flags: [String]?
    let citations: [Citation]?

    init(summary: String? = nil,
         analysis: String? = nil,
         answer_markdown: String? = nil,
         confidence: Double? = nil,
         followups: [String]? = nil,
         thread_id: String? = nil,
         message_id: String? = nil,
         response_state: String? = nil,
         interaction_route: ChatInteractionRoute? = nil,
         quality_flags: [String]? = nil,
         citations: [Citation]? = nil) {
        self.summary = summary
        self.analysis = analysis
        self.answer_markdown = answer_markdown
        self.confidence = confidence
        self.followups = followups
        self.thread_id = thread_id
        self.message_id = message_id
        self.response_state = response_state
        self.interaction_route = interaction_route
        self.quality_flags = quality_flags
        self.citations = citations
    }
}

enum ChatStreamEvent: Sendable {
    case route(ChatInteractionRoute)
    case progress(String)
    case token(String)
    case done(ChatResponse)
}

struct ChatStreamEnvelope: Decodable, Sendable {
    let type: String
    let route: ChatInteractionRoute?
    let step: String?
    let delta: String?
    let result: ChatResponse?
    let message: String?
    let retryable: Bool?
}

// MARK: - 授权

struct ConsentUpdate: Encodable {
    let allow_ai_chat: Bool
}

struct ConsentResponse: Decodable {
    let allow_ai_chat: Bool
    let allow_data_upload: Bool?
}
