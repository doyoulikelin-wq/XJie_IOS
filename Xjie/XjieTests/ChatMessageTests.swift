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

    func testCitationDecodesStudyContext() throws {
        let json = """
        {
          "claim_id": 11,
          "literature_id": 21,
          "claim_text": "严重胸椎侧弯可能影响夜间血氧。",
          "evidence_level": "L3",
          "short_ref": "Example et al., 2024",
          "journal": "Example Journal",
          "year": 2024,
          "sample_size": 86,
          "population": "伴肺功能受限的成人胸椎侧弯患者",
          "study_design": "前瞻性队列研究",
          "confidence": "medium",
          "score": 0.82
        }
        """.data(using: .utf8)!

        let citation = try JSONDecoder().decode(Citation.self, from: json)

        XCTAssertEqual(citation.population, "伴肺功能受限的成人胸椎侧弯患者")
        XCTAssertEqual(citation.study_design, "前瞻性队列研究")
        XCTAssertEqual(citation.sample_size, 86)
        XCTAssertEqual(citation.year, 2024)
    }

    func testCitationDecodesLegacyPayloadWithoutStudyContext() throws {
        let json = """
        {
          "claim_id": 12,
          "literature_id": 22,
          "claim_text": "旧历史证据。",
          "evidence_level": "L2",
          "short_ref": "Legacy et al., 2020",
          "confidence": "high"
        }
        """.data(using: .utf8)!

        let citation = try JSONDecoder().decode(Citation.self, from: json)

        XCTAssertNil(citation.population)
        XCTAssertNil(citation.study_design)
        XCTAssertNil(citation.sample_size)
        XCTAssertNil(citation.year)
    }

    func testCitationLocalizesStudyDesignForUserDisplay() {
        func displayText(_ studyDesign: String?) -> String? {
            Citation(
                claim_id: 30,
                literature_id: 40,
                claim_text: "研究结论。",
                evidence_level: "L2",
                short_ref: "Example et al., 2026",
                journal: nil,
                year: 2026,
                sample_size: nil,
                study_design: studyDesign,
                confidence: "medium",
                score: nil
            ).studyDesignDisplayText
        }

        XCTAssertEqual(displayText("systematic_review_meta_analysis"), "系统综述与荟萃分析")
        XCTAssertEqual(displayText("systematic_review"), "系统综述")
        XCTAssertEqual(displayText("mechanistic_observational_study"), "机制性观察研究")
        XCTAssertEqual(displayText("clinical_practice_guideline"), "临床实践指南")
        XCTAssertEqual(displayText("RCT"), "随机对照试验")
        XCTAssertEqual(displayText("cohort_study"), "队列研究")
        XCTAssertEqual(displayText("prospective cohort study"), "前瞻性队列研究")
        XCTAssertEqual(displayText("retrospective_cohort"), "回顾性队列研究")
        XCTAssertEqual(displayText("case-control study"), "病例对照研究")
        XCTAssertEqual(displayText("cross_sectional_study"), "横断面研究")
        XCTAssertEqual(displayText("observational_study"), "观察性研究")
        XCTAssertEqual(displayText("前瞻性队列研究"), "前瞻性队列研究")
        XCTAssertEqual(displayText("unmapped_internal_design"), "其他研究设计")
        XCTAssertNil(displayText(nil))
    }

    func testRelevantCitationsHidesCandidateNotReferencedByAnswer() {
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

    func testRelevantCitationsKeepsCandidateReferencedByAnswer() {
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
            content: "近期血压偏高，可以结合饮食节律和体重管理降低高血压风险[1]。",
            analysis: nil,
            confidence: nil,
            followups: nil,
            citations: [citation]
        )

        XCTAssertEqual(message.relevantCitations, [citation])
    }

    func testRelevantCitationsSupportsNewTopicsWithoutClientVocabularyUpdate() {
        let citation = Citation(
            claim_id: 2,
            literature_id: 2,
            claim_text: "某种未归类干预可能改变一个未归类终点。",
            evidence_level: "L4",
            short_ref: "Unknown et al., 2026",
            journal: nil,
            year: 2026,
            sample_size: nil,
            confidence: "low",
            score: nil
        )
        let message = ChatMessageItem(
            role: "assistant",
            content: "这个新领域的结论由当前证据支持[1]。",
            analysis: nil,
            confidence: nil,
            followups: nil,
            citations: [citation]
        )

        XCTAssertEqual(message.relevantCitations, [citation])
    }

    func testRelevantCitationsDoesNotInferReferenceFromPartialTopicOverlap() {
        let citation = Citation(
            claim_id: 3,
            literature_id: 3,
            claim_text: "失眠与胰岛素敏感性之间未发现显著关联。",
            evidence_level: "L3",
            short_ref: "Tan et al., 2019",
            journal: "Sleep Medicine",
            year: 2019,
            sample_size: nil,
            confidence: "medium",
            score: nil
        )
        let message = ChatMessageItem(
            role: "assistant",
            content: "鼻炎、脊柱侧弯和失眠需要分别评估，不能直接证明缺氧。",
            analysis: "失眠与抑郁可能双向影响。",
            confidence: nil,
            followups: nil,
            citations: [citation]
        )

        XCTAssertTrue(message.relevantCitations.isEmpty)
    }

    func testRelevantCitationsKeepsCompoundCausalEvidence() {
        let citation = Citation(
            claim_id: 4,
            literature_id: 4,
            claim_text: "严重胸椎脊柱侧弯在肺活量降低时可导致夜间低氧。",
            evidence_level: "L3",
            short_ref: "Midgren et al., 1988",
            journal: "Br J Dis Chest",
            year: 1988,
            sample_size: 13,
            confidence: "medium",
            score: nil
        )
        let message = ChatMessageItem(
            role: "assistant",
            content: "严重脊柱侧弯伴肺功能下降时可能出现夜间低氧，但轻度侧弯不能直接判定缺氧[1]。",
            analysis: nil,
            confidence: nil,
            followups: nil,
            citations: [citation]
        )

        XCTAssertEqual(message.relevantCitations, [citation])
    }

    func testRelevantCitationsReadsMarkersFromDetailedAnalysis() {
        let first = Citation(
            claim_id: 5,
            literature_id: 5,
            claim_text: "第一条候选结论。",
            evidence_level: "L1",
            short_ref: "First et al., 2026",
            journal: nil,
            year: 2026,
            sample_size: nil,
            confidence: "high",
            score: nil
        )
        let second = Citation(
            claim_id: 6,
            literature_id: 6,
            claim_text: "第二条候选结论。",
            evidence_level: "L2",
            short_ref: "Second et al., 2026",
            journal: nil,
            year: 2026,
            sample_size: nil,
            confidence: "medium",
            score: nil
        )
        let message = ChatMessageItem(
            role: "assistant",
            content: "先给出简要结论。",
            analysis: "详细分析只引用第二条证据[2]。",
            confidence: nil,
            followups: nil,
            citations: [first, second]
        )

        XCTAssertEqual(message.relevantCitations, [second])
        XCTAssertEqual(message.relevantCitationReferences.map(\.number), [2])
        XCTAssertEqual(message.relevantCitationReferences.map(\.citation), [second])
    }

    func testRelevantCitationReferencesKeepsCompactedBackendNumbering() {
        let citation = Citation(
            claim_id: 8,
            literature_id: 8,
            claim_text: "后端已经筛选并压缩后的第一条证据。",
            evidence_level: "L1",
            short_ref: "Compacted et al., 2026",
            journal: nil,
            year: 2026,
            sample_size: nil,
            confidence: "high",
            score: nil
        )
        let message = ChatMessageItem(
            role: "assistant",
            content: "当前结论由筛选后的证据支持[1]。",
            analysis: nil,
            confidence: nil,
            followups: nil,
            citations: [citation]
        )

        XCTAssertEqual(message.relevantCitationReferences.map(\.number), [1])
        XCTAssertEqual(message.relevantCitations, [citation])
    }

    func testRelevantCitationsIgnoresOutOfRangeMarker() {
        let citation = Citation(
            claim_id: 7,
            literature_id: 7,
            claim_text: "唯一候选结论。",
            evidence_level: "L1",
            short_ref: "Only et al., 2026",
            journal: nil,
            year: 2026,
            sample_size: nil,
            confidence: "high",
            score: nil
        )
        let message = ChatMessageItem(
            role: "assistant",
            content: "错误编号不应映射到现有证据[2]。",
            analysis: nil,
            confidence: nil,
            followups: nil,
            citations: [citation]
        )

        XCTAssertTrue(message.relevantCitations.isEmpty)
    }

    func testDecodeChatRouteSSEEnvelope() throws {
        let json = """
        {
          "type": "route",
          "route": {
            "version": "2026-07-10",
            "route_id": "llm.health.deep",
            "strategy": "llm",
            "primary_intent": "trend_analysis",
            "depth": "deep",
            "safety_level": "low",
            "subject_type": "self",
            "needs_literature": true,
            "max_followups": 1,
            "progress_steps": ["已核对来源和时效", "正在检索医学证据"]
          }
        }
        """.data(using: .utf8)!

        let envelope = try JSONDecoder().decode(ChatStreamEnvelope.self, from: json)

        XCTAssertEqual(envelope.type, "route")
        XCTAssertEqual(envelope.route?.route_id, "llm.health.deep")
        XCTAssertEqual(envelope.route?.progress_steps.count, 2)
    }

    func testDecodeChatDoneSSEEnvelopeIgnoresBackendAuditFields() throws {
        let json = """
        {
          "type": "done",
          "result": {
            "summary": "已完成分析",
            "analysis": "详细内容",
            "answer_markdown": "详细内容",
            "confidence": 0.9,
            "followups": [],
            "safety_flags": [],
            "used_context": {"message_structure_version": "2026-07-10"},
            "thread_id": "9",
            "message_id": "18",
            "response_state": "completed",
            "quality_flags": [],
            "citations": []
          }
        }
        """.data(using: .utf8)!

        let envelope = try JSONDecoder().decode(ChatStreamEnvelope.self, from: json)

        XCTAssertEqual(envelope.result?.summary, "已完成分析")
        XCTAssertEqual(envelope.result?.thread_id, "9")
        XCTAssertEqual(envelope.result?.message_id, "18")
    }
}
