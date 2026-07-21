from app.schemas.literature import CitationBundle
from app.services.chat_citations import select_citations_for_response


def _citation(
    index: int,
    claim_text: str,
    *,
    study_design: str | None = None,
    confidence: str = "high",
) -> CitationBundle:
    return CitationBundle(
        claim_id=index,
        literature_id=index,
        claim_text=claim_text,
        evidence_level="L1",
        short_ref=f"Medical Author {index}, 2026",
        study_design=study_design,
        confidence=confidence,
    )


def test_uncited_candidates_are_not_returned() -> None:
    selection = select_citations_for_response(
        summary="没有引用角标的摘要。",
        analysis="这是一段没有引用角标的完整分析。",
        answer_markdown="这是一段没有引用角标的完整回答。",
        candidates=[
            _citation(1, "高血压与心血管事件风险增加相关。"),
            _citation(2, "过敏性鼻炎与失眠风险增加相关。"),
        ],
    )

    assert selection.citations == []
    assert selection.removed_candidate_count == 2
    assert selection.removed_marker_count == 0


def test_sparse_markers_are_selected_and_compactly_renumbered_across_all_fields() -> None:
    candidates = [
        _citation(11, "连续血糖监测可用于评估血糖控制。"),
        _citation(12, "过敏性鼻炎与失眠和睡眠呼吸障碍风险增加相关。"),
        _citation(13, "严重胸椎脊柱侧弯在肺活量降低时可导致夜间低氧。"),
    ]

    selection = select_citations_for_response(
        summary="过敏性鼻炎与失眠风险增加相关[2]。",
        analysis=(
            "严重胸椎脊柱侧弯在肺活量降低时可能导致夜间低氧[3]。"
            "过敏性鼻炎与睡眠呼吸障碍风险增加相关[2]。"
        ),
        answer_markdown=(
            "过敏性鼻炎与睡眠呼吸障碍风险增加相关[2]；"
            "严重胸椎脊柱侧弯在肺活量降低时可能导致夜间低氧[3]。"
        ),
        candidates=candidates,
    )

    assert [item.claim_id for item in selection.citations] == [12, 13]
    assert selection.summary.endswith("相关[1]。")
    assert "低氧[2]" in selection.analysis
    assert "障碍风险增加相关[1]" in selection.analysis
    assert "相关[1]" in selection.answer_markdown
    assert "低氧[2]" in selection.answer_markdown
    assert "[3]" not in "\n".join(
        (selection.summary, selection.analysis, selection.answer_markdown)
    )


def test_wrong_marker_is_removed_instead_of_rebound_to_better_matching_paper() -> None:
    candidates = [
        _citation(21, "严重胸椎脊柱侧弯在肺活量降低时可导致夜间低氧。"),
        _citation(22, "过敏性鼻炎与失眠和睡眠呼吸障碍风险增加相关。"),
        _citation(23, "失眠与抑郁存在双向关联，二者可相互维持或加重。"),
    ]

    selection = select_citations_for_response(
        summary="",
        analysis="",
        answer_markdown=(
            "失眠与抑郁存在双向关联[1]。"
            "过敏性鼻炎与失眠和睡眠呼吸障碍风险增加相关[2]。"
        ),
        candidates=candidates,
    )

    assert [item.claim_id for item in selection.citations] == [22]
    assert "双向关联。" in selection.answer_markdown
    assert "双向关联[" not in selection.answer_markdown
    assert "风险增加相关[1]" in selection.answer_markdown
    assert selection.removed_marker_count == 1


def test_one_shared_concept_does_not_make_an_unrelated_claim_supportive() -> None:
    selection = select_citations_for_response(
        summary="失眠与抑郁可能相互维持[1]。",
        analysis="",
        answer_markdown="",
        candidates=[_citation(24, "失眠与胰岛素敏感性下降相关。")],
    )

    assert selection.citations == []
    assert selection.summary == "失眠与抑郁可能相互维持。"
    assert selection.removed_marker_count == 1


def test_shared_insomnia_outcome_cannot_borrow_a_rhinitis_relationship_claim() -> None:
    candidate = _citation(
        25,
        "过敏性鼻炎与失眠和睡眠呼吸障碍风险增加相关。",
    )

    for statement in (
        "焦虑与失眠风险增加相关[1]。",
        "抑郁与失眠风险增加相关[1]。",
        "脊柱侧弯与失眠风险增加相关[1]。",
        "焦虑、抑郁和脊柱侧弯与失眠风险增加相关[1]。",
    ):
        selection = select_citations_for_response(
            summary=statement,
            analysis="",
            answer_markdown="",
            candidates=[candidate],
        )

        assert selection.citations == []
        assert "[1]" not in selection.summary


def test_relation_concepts_must_belong_to_the_same_association_clause() -> None:
    selection = select_citations_for_response(
        summary="血压与心率相关[1]。",
        analysis="",
        answer_markdown="",
        candidates=[_citation(251, "血压与血糖相关，心率保持平稳。")],
    )

    assert selection.citations == []


def test_causal_concept_roles_cannot_be_reversed() -> None:
    selection = select_citations_for_response(
        summary="失眠导致抑郁[1]。",
        analysis="",
        answer_markdown="",
        candidates=[
            _citation(
                252,
                "抑郁导致失眠。",
                study_design="randomized_controlled_trial",
                confidence="high",
            )
        ],
    )

    assert selection.citations == []


def test_single_known_outcome_still_requires_the_same_exposure_wording() -> None:
    selection = select_citations_for_response(
        summary="锌补充与偏头痛发作频率降低相关[1]。",
        analysis="",
        answer_markdown="",
        candidates=[_citation(253, "镁补充与偏头痛发作频率降低相关。")],
    )

    assert selection.citations == []


def test_specific_concept_aliases_are_treated_as_one_clear_concept() -> None:
    resting_hr_candidate = _citation(254, "静息心率升高。")
    deep_sleep_candidate = _citation(255, "深睡减少。")
    resting_hr = select_citations_for_response(
        summary="RHR升高[1]。",
        analysis="",
        answer_markdown="",
        candidates=[resting_hr_candidate],
    )
    deep_sleep = select_citations_for_response(
        summary="deep sleep减少[1]。",
        analysis="",
        answer_markdown="",
        candidates=[deep_sleep_candidate],
    )

    assert resting_hr.citations == [resting_hr_candidate]
    assert deep_sleep.citations == [deep_sleep_candidate]


def test_unknown_domain_requires_strict_lexical_agreement() -> None:
    candidate = _citation(26, "辅酶QX与晨间活力评分改善相关。")
    exact = select_citations_for_response(
        summary="辅酶QX与晨间活力评分改善相关[1]。",
        analysis="",
        answer_markdown="",
        candidates=[candidate],
    )
    different_exposure = select_citations_for_response(
        summary="蓝藻素与晨间活力评分改善相关[1]。",
        analysis="",
        answer_markdown="",
        candidates=[candidate],
    )

    assert exact.citations == [candidate]
    assert different_exposure.citations == []


def test_valid_original_marker_is_never_replaced_by_a_more_specific_candidate() -> None:
    candidates = [
        _citation(31, "鼻炎与睡眠问题存在关联，但不能证明个人已经缺氧。"),
        _citation(32, "过敏性鼻炎与失眠和睡眠呼吸障碍风险增加相关。"),
    ]

    selection = select_citations_for_response(
        summary="鼻炎与睡眠问题存在关联，但不能证明个人已经缺氧[1]。",
        analysis="",
        answer_markdown="",
        candidates=candidates,
    )

    assert [item.claim_id for item in selection.citations] == [31]
    assert selection.summary.endswith("缺氧[1]。")
    assert selection.removed_marker_count == 0


def test_each_marker_occurrence_must_be_supported_even_if_same_candidate_is_valid_elsewhere() -> None:
    candidate = _citation(41, "高血压与心血管事件风险增加相关。")

    selection = select_citations_for_response(
        summary="研究已经证明这一点[1]。",
        analysis="高血压与心血管事件风险增加相关[1]。",
        answer_markdown="",
        candidates=[candidate],
    )

    assert selection.citations == [candidate]
    assert selection.summary == "研究已经证明这一点。"
    assert selection.analysis.endswith("相关[1]。")
    assert selection.removed_marker_count == 1


def test_lexical_support_handles_topics_outside_health_concept_catalog() -> None:
    candidate = _citation(51, "镁补充与偏头痛发作频率降低相关。")

    selection = select_citations_for_response(
        summary="镁补充与偏头痛发作频率降低相关[1]。",
        analysis="",
        answer_markdown="",
        candidates=[candidate],
    )

    assert selection.citations == [candidate]
    assert selection.summary.endswith("相关[1]。")


def test_out_of_range_marker_is_removed_without_exposing_any_candidate() -> None:
    selection = select_citations_for_response(
        summary="高血压风险增加[9]。",
        analysis="",
        answer_markdown="",
        candidates=[_citation(61, "高血压与心血管事件风险增加相关。")],
    )

    assert selection.citations == []
    assert selection.summary == "高血压风险增加。"
    assert selection.removed_marker_count == 1


def test_positive_association_claim_cannot_support_no_association_statement() -> None:
    selection = select_citations_for_response(
        summary="血压升高与心率加快无关[1]。",
        analysis="",
        answer_markdown="",
        candidates=[_citation(71, "血压升高与心率加快相关。")],
    )

    assert selection.citations == []
    assert selection.summary == "血压升高与心率加快无关。"


def test_negative_association_claim_cannot_support_positive_association_statement() -> None:
    selection = select_citations_for_response(
        summary="失眠与胰岛素敏感性下降相关[1]。",
        analysis="",
        answer_markdown="",
        candidates=[_citation(72, "研究未见失眠与胰岛素敏感性下降存在显著关联。")],
    )

    assert selection.citations == []
    assert selection.summary == "失眠与胰岛素敏感性下降相关。"


def test_double_negation_is_positive_but_mixed_relation_polarity_is_removed() -> None:
    candidate = _citation(721, "鼻炎与失眠风险增加相关。")
    double_negative = select_citations_for_response(
        summary="鼻炎与失眠并非不相关[1]。",
        analysis="",
        answer_markdown="",
        candidates=[candidate],
    )
    mixed = select_citations_for_response(
        summary="鼻炎与年龄无关，但与失眠风险增加相关[1]。",
        analysis="",
        answer_markdown="",
        candidates=[candidate],
    )
    mixed_claim = select_citations_for_response(
        summary="鼻炎与失眠风险增加相关[1]。",
        analysis="",
        answer_markdown="",
        candidates=[_citation(722, "鼻炎与失眠无关，但与失眠风险增加相关。")],
    )

    assert double_negative.citations == [candidate]
    assert mixed.citations == []
    assert mixed_claim.citations == []


def test_mixed_causal_or_direction_polarity_is_removed_conservatively() -> None:
    causal = select_citations_for_response(
        summary="鼻炎不会导致焦虑，但可能导致失眠[1]。",
        analysis="",
        answer_markdown="",
        candidates=[
            _citation(
                724,
                "鼻炎可能导致失眠。",
                study_design="observational_study",
                confidence="medium",
            )
        ],
    )
    direction = select_citations_for_response(
        summary="该干预不增加心率，但增加血压[1]。",
        analysis="",
        answer_markdown="",
        candidates=[_citation(725, "该干预增加血压。")],
    )

    assert causal.citations == []
    assert direction.citations == []


def test_observational_association_cannot_support_unconditional_causal_statement() -> None:
    selection = select_citations_for_response(
        summary="过敏性鼻炎导致失眠[1]。",
        analysis="",
        answer_markdown="",
        candidates=[
            _citation(
                73,
                "过敏性鼻炎与失眠风险增加相关。",
                study_design="systematic_review_of_observational_studies",
                confidence="medium",
            )
        ],
    )

    assert selection.citations == []
    assert selection.summary == "过敏性鼻炎导致失眠。"


def test_conditional_causal_language_can_use_matching_observational_boundary() -> None:
    candidate = _citation(
        74,
        "严重胸椎脊柱侧弯在肺活量降低时可导致夜间低氧。",
        study_design="mechanistic_observational_study",
        confidence="medium",
    )
    selection = select_citations_for_response(
        summary="严重脊柱侧弯在肺活量降低时可能导致夜间低氧[1]。",
        analysis="",
        answer_markdown="",
        candidates=[candidate],
    )

    assert selection.citations == [candidate]
    assert selection.summary.endswith("低氧[1]。")


def test_high_confidence_randomized_causal_claim_can_support_matching_causal_statement() -> None:
    candidate = _citation(
        75,
        "随机对照试验显示该干预导致收缩压降低。",
        study_design="randomized_controlled_trial",
        confidence="high",
    )
    selection = select_citations_for_response(
        summary="随机对照试验中，该干预导致收缩压降低[1]。",
        analysis="",
        answer_markdown="",
        candidates=[candidate],
    )

    assert selection.citations == [candidate]
    assert selection.summary.endswith("降低[1]。")


def test_marker_after_sentence_punctuation_uses_the_previous_sentence() -> None:
    candidate = _citation(76, "高血压与心血管事件风险增加相关。")
    selection = select_citations_for_response(
        summary="高血压与心血管事件风险增加相关。\n[1]",
        analysis="",
        answer_markdown="",
        candidates=[candidate],
    )

    assert selection.citations == [candidate]
    assert selection.summary == "高血压与心血管事件风险增加相关。\n[1]"


def test_opposite_increase_decrease_direction_removes_marker() -> None:
    selection = select_citations_for_response(
        summary="该干预使血压升高[1]。",
        analysis="",
        answer_markdown="",
        candidates=[_citation(77, "该干预使血压降低。")],
    )

    assert selection.citations == []
    assert selection.summary == "该干预使血压升高。"


def test_negated_increase_and_decrease_do_not_use_opposite_direction_claims() -> None:
    increase = select_citations_for_response(
        summary="鼻炎不增加失眠风险[1]。",
        analysis="",
        answer_markdown="",
        candidates=[_citation(78, "鼻炎与失眠风险增加相关。")],
    )
    decrease = select_citations_for_response(
        summary="镁补充不降低偏头痛发作频率[1]。",
        analysis="",
        answer_markdown="",
        candidates=[_citation(79, "镁补充与偏头痛发作频率降低相关。")],
    )

    assert increase.citations == []
    assert decrease.citations == []


def test_negated_causality_requires_a_negated_causal_claim() -> None:
    selection = select_citations_for_response(
        summary="失眠不会导致抑郁[1]。",
        analysis="",
        answer_markdown="",
        candidates=[_citation(80, "长期失眠可导致抑郁症状加重。")],
    )

    assert selection.citations == []


def test_hedged_or_conditional_causality_cannot_upgrade_association_evidence() -> None:
    candidate = _citation(
        81,
        "失眠与抑郁风险增加相关。",
        study_design="observational_cohort",
        confidence="medium",
    )
    hedged = select_citations_for_response(
        summary="失眠可能导致抑郁[1]。",
        analysis="",
        answer_markdown="",
        candidates=[candidate],
    )
    conditional = select_citations_for_response(
        summary="如果失眠持续，可能会导致抑郁[1]。",
        analysis="",
        answer_markdown="",
        candidates=[candidate],
    )

    assert hedged.citations == []
    assert conditional.citations == []


def test_unconditional_proof_and_diagnosis_require_matching_strong_evidence() -> None:
    proof = select_citations_for_response(
        summary="研究证明失眠与抑郁相关[1]。",
        analysis="",
        answer_markdown="",
        candidates=[
            _citation(
                82,
                "观察性研究显示失眠与抑郁相关。",
                study_design="systematic_review_of_observational_studies",
                confidence="medium",
            )
        ],
    )
    diagnosis = select_citations_for_response(
        summary="这些症状已经确诊阻塞性睡眠呼吸暂停[1]。",
        analysis="",
        answer_markdown="",
        candidates=[
            _citation(
                83,
                "怀疑阻塞性睡眠呼吸暂停时需要客观睡眠检测。",
                study_design="clinical_practice_guideline",
                confidence="high",
            )
        ],
    )

    assert proof.citations == []
    assert diagnosis.citations == []


def test_negated_proof_boundary_can_keep_the_same_boundary_claim() -> None:
    candidate = _citation(
        84,
        "现有观察性证据不能证明鼻炎已经造成缺氧。",
        study_design="observational_study",
        confidence="medium",
    )
    selection = select_citations_for_response(
        summary="现有观察性证据不能证明鼻炎已经造成缺氧[1]。",
        analysis="",
        answer_markdown="",
        candidates=[candidate],
    )

    assert selection.citations == [candidate]


def test_marker_context_handles_quotes_markdown_and_consecutive_markers() -> None:
    first = _citation(85, "高血压与心血管事件风险增加相关。")
    second = _citation(86, "高血压与心血管事件风险增加相关。")
    quoted = select_citations_for_response(
        summary="“高血压与心血管事件风险增加相关。”[1]",
        analysis="",
        answer_markdown="",
        candidates=[first],
    )
    markdown = select_citations_for_response(
        summary="**高血压与心血管事件风险增加相关。**[1]",
        analysis="",
        answer_markdown="",
        candidates=[first],
    )
    consecutive = select_citations_for_response(
        summary="高血压与心血管事件风险增加相关。[1][2]",
        analysis="",
        answer_markdown="",
        candidates=[first, second],
    )

    assert quoted.citations == [first]
    assert markdown.citations == [first]
    assert consecutive.citations == [first, second]


def test_marker_context_never_borrows_from_another_sentence_or_future_text() -> None:
    candidate = _citation(87, "高血压与心血管事件风险增加相关。")
    unrelated_current = select_citations_for_response(
        summary="高血压与心血管事件风险增加相关。今天天气很好[1]。",
        analysis="",
        answer_markdown="",
        candidates=[candidate],
    )
    future_only = select_citations_for_response(
        summary="[1]高血压与心血管事件风险增加相关。",
        analysis="",
        answer_markdown="",
        candidates=[candidate],
    )

    assert unrelated_current.citations == []
    assert future_only.citations == []


def test_english_polarity_direction_and_causal_strength_are_enforced() -> None:
    association = _citation(88, "Insomnia is associated with depression.")
    increase = _citation(89, "The intervention increases blood pressure.")
    causal = _citation(
        90,
        "Persistent insomnia may cause depression.",
        study_design="observational_study",
        confidence="medium",
    )

    assert select_citations_for_response(
        summary="Insomnia is not associated with depression[1].",
        analysis="",
        answer_markdown="",
        candidates=[association],
    ).citations == []
    assert select_citations_for_response(
        summary="The intervention does not increase blood pressure[1].",
        analysis="",
        answer_markdown="",
        candidates=[increase],
    ).citations == []
    assert select_citations_for_response(
        summary="The intervention decreases blood pressure[1].",
        analysis="",
        answer_markdown="",
        candidates=[increase],
    ).citations == []
    assert select_citations_for_response(
        summary="Persistent insomnia does not cause depression[1].",
        analysis="",
        answer_markdown="",
        candidates=[causal],
    ).citations == []
    assert select_citations_for_response(
        summary="Persistent insomnia may cause depression[1].",
        analysis="",
        answer_markdown="",
        candidates=[association],
    ).citations == []


def test_english_period_is_a_boundary_but_decimal_point_is_not() -> None:
    insomnia = _citation(91, "Insomnia is associated with depression.")
    magnesium = _citation(92, "Magnesium reduces migraine frequency by 3.5 points.")
    cross_sentence = select_citations_for_response(
        summary="Insomnia is associated with depression. Magnesium reduces migraine frequency[1].",
        analysis="",
        answer_markdown="",
        candidates=[insomnia],
    )
    decimal = select_citations_for_response(
        summary="Magnesium reduces migraine frequency by 3.5 points[1].",
        analysis="",
        answer_markdown="",
        candidates=[magnesium],
    )

    assert cross_sentence.citations == []
    assert decimal.citations == [magnesium]
