import Foundation

// MARK: - 文献引用

/// 与后端 schemas/literature.py CitationBundle 对应
struct Citation: Codable, Identifiable, Hashable, Equatable {
    let claim_id: Int
    let literature_id: Int
    let claim_text: String
    let evidence_level: String      // L1 / L2 / L3 / L4
    let short_ref: String           // e.g. "Segal et al., Cell 2015"
    let journal: String?
    let year: Int?
    let sample_size: Int?
    let confidence: String          // high / medium / low
    let score: Double?

    var id: Int { claim_id }
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

struct ChatRequest: Encodable {
    let message: String
    let thread_id: String?
    let client_message_id: String?

    init(message: String, thread_id: String?, client_message_id: String? = nil) {
        self.message = message
        self.thread_id = thread_id
        self.client_message_id = client_message_id
    }
}

struct ChatResponse: Codable {
    let summary: String?
    let analysis: String?
    let answer_markdown: String?
    let confidence: Double?
    let followups: [String]?
    let thread_id: String?
    let citations: [Citation]?

    init(summary: String? = nil,
         analysis: String? = nil,
         answer_markdown: String? = nil,
         confidence: Double? = nil,
         followups: [String]? = nil,
         thread_id: String? = nil,
         citations: [Citation]? = nil) {
        self.summary = summary
        self.analysis = analysis
        self.answer_markdown = answer_markdown
        self.confidence = confidence
        self.followups = followups
        self.thread_id = thread_id
        self.citations = citations
    }
}

// MARK: - 授权

struct ConsentUpdate: Encodable {
    let allow_ai_chat: Bool
}

struct ConsentResponse: Decodable {
    let allow_ai_chat: Bool
    let allow_data_upload: Bool?
}
