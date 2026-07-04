import XCTest
@testable import Xjie

/// ChatMessage 模型测试（BUG-01 回归测试）
final class ChatMessageTests: XCTestCase {

    func testDecodeWithServerId() throws {
        let json = """
        {"id": "server-123", "role": "user", "content": "hello"}
        """.data(using: .utf8)!

        let msg = try JSONDecoder().decode(ChatMessage.self, from: json)
        XCTAssertEqual(msg.id, "server-123")
        XCTAssertEqual(msg.role, "user")
        XCTAssertEqual(msg.content, "hello")
    }

    func testDecodeWithoutIdGeneratesUUID() throws {
        let json = """
        {"role": "assistant", "content": "hi"}
        """.data(using: .utf8)!

        let msg = try JSONDecoder().decode(ChatMessage.self, from: json)
        XCTAssertFalse(msg.id.isEmpty, "id 应自动生成 UUID")
        XCTAssertEqual(msg.role, "assistant")
    }

    /// BUG-01 回归：id 必须是存储属性，多次访问返回同一值
    func testIdIsStableAcrossAccesses() throws {
        let json = """
        {"role": "user", "content": "test"}
        """.data(using: .utf8)!

        let msg = try JSONDecoder().decode(ChatMessage.self, from: json)
        let id1 = msg.id
        let id2 = msg.id
        XCTAssertEqual(id1, id2, "BUG-01: id 必须是存储属性，多次访问应返回同一值")
    }

    func testDecodeMultipleMessagesHaveUniqueIds() throws {
        let json = """
        [
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "q2"}
        ]
        """.data(using: .utf8)!

        let msgs = try JSONDecoder().decode([ChatMessage].self, from: json)
        let ids = Set(msgs.map(\.id))
        XCTAssertEqual(ids.count, 3, "每条消息应有唯一 id")
    }

    func testRelevantCitationsFiltersUnrelatedHealthTopic() {
        let citation = Citation(
            claim_id: 1,
            literature_id: 1,
            claim_text: "早期限时进食可使高血压肥胖患者的舒张压降低4 mmHg。",
            evidence_level: "L3",
            short_ref: "Rehman et al., The Journal of nutrition 2026",
            journal: "The Journal of nutrition",
            year: 2026,
            sample_size: nil,
            confidence: "medium",
            score: nil
        )
        let message = ChatMessageItem(
            role: "assistant",
            content: "GGT 和 ALP 持续升高，提示胆道梗阻风险；空腹血糖已达到糖尿病诊断阈值。",
            analysis: "建议完善 MRCP，并复查肝功能、血糖和甘油三酯。",
            confidence: nil,
            followups: nil,
            citations: [citation]
        )

        XCTAssertTrue(message.relevantCitations.isEmpty)
    }

    func testRelevantCitationsKeepsMatchingHealthTopic() {
        let citation = Citation(
            claim_id: 1,
            literature_id: 1,
            claim_text: "早期限时进食可使高血压肥胖患者的舒张压降低4 mmHg。",
            evidence_level: "L3",
            short_ref: "Rehman et al., The Journal of nutrition 2026",
            journal: "The Journal of nutrition",
            year: 2026,
            sample_size: nil,
            confidence: "medium",
            score: nil
        )
        let message = ChatMessageItem(
            role: "assistant",
            content: "近期血压偏高，可以结合饮食节律和体重管理降低高血压风险。",
            analysis: nil,
            confidence: nil,
            followups: nil,
            citations: [citation]
        )

        XCTAssertEqual(message.relevantCitations, [citation])
    }
}
