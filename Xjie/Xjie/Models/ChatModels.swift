import Foundation

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

    enum CodingKeys: String, CodingKey {
        case id, role, content, analysis, created_at
    }

    init(id: String = UUID().uuidString, role: String, content: String, analysis: String? = nil, created_at: String? = nil) {
        self.id = id
        self.role = role
        self.content = content
        self.analysis = analysis
        self.created_at = created_at
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        self.id = (try? container.decode(String.self, forKey: .id)) ?? UUID().uuidString
        self.role = try container.decode(String.self, forKey: .role)
        self.content = try container.decode(String.self, forKey: .content)
        self.analysis = try? container.decode(String.self, forKey: .analysis)
        self.created_at = try? container.decode(String.self, forKey: .created_at)
    }
}

struct ChatRequest: Encodable {
    let message: String
    let thread_id: String?
}

struct ChatResponse: Codable {
    let summary: String?
    let analysis: String?
    let answer_markdown: String?
    let confidence: Double?
    let followups: [String]?
    let thread_id: String?
}

// MARK: - 授权

struct ConsentUpdate: Encodable {
    let allow_ai_chat: Bool
}

struct ConsentResponse: Decodable {
    let allow_ai_chat: Bool
    let allow_data_upload: Bool?
}
