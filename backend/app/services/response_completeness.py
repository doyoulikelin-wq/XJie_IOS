from __future__ import annotations

import re


_DANGLING_END_RE = re.compile(
    r"(?:但|但是|不过|然而|因为|由于|所以|从而|导致|形成|归因于|"
    r"包括|例如|比如|以及|而且|同时|主要是|意味着|表现为|相关于|"
    r"与|和|或|及|、|，|,|：|:|；|;|[-*])\s*$",
    re.IGNORECASE,
)
_MARKDOWN_RE = re.compile(r"[`#>*_\[\](){}|~-]+")
_SPACE_RE = re.compile(r"\s+")
_TRAILING_CITATION_OR_TERMINATOR_RE = re.compile(
    r"(?:(?:\[\s*\d+\s*\])|[。！？!?．.…])(?:\s*(?:(?:\[\s*\d+\s*\])|[。！？!?．.…]))*\s*$"
)
_COVERAGE_SENTENCE_SPLIT_RE = re.compile(r"[。！？!?；;\r\n]+|(?<=\.)\s+")
_COVERAGE_CLAUSE_SPLIT_RE = re.compile(r"[，,：:]+")
_DISMISSAL_PROTECTION_RE = re.compile(
    r"(?:不能|不可|不应|不该|不宜|不要)(?:跳过|略过|忽略)|"
    r"(?:不能|不可|不应|不该|不宜)(?:不(?:讨论|分析|展开|评估|解释|考虑|涉及|处理|覆盖))",
)
_DISMISSAL_RE = re.compile(
    r"(?:跳过|略过|忽略)|"
    r"(?:(?:暂时|暂且|先|本轮|这里|本文|本回答)?(?:不再|不予|不作|不做|不)"
    r"(?:进一步|详细)?(?:讨论|分析|展开|评估|解释|考虑|涉及|处理|覆盖))|"
    r"(?:无需|不用|不必)(?:进一步|详细)?(?:讨论|分析|展开|评估|解释|考虑|涉及|处理|覆盖)|"
    r"不纳入(?:讨论|分析|评估)|(?:仅|只)(?:提及|提到|点到为止)",
)
_ENGLISH_DISMISSAL_PROTECTION_RE = re.compile(
    r"\b(?:do\s+not|don't|must\s+not|should\s+not|cannot|can't)\s+(?:skip|omit|ignore)\b",
    re.IGNORECASE,
)
_ENGLISH_DISMISSAL_RE = re.compile(
    r"\b(?:skip|omit|ignore)\b|"
    r"\b(?:do\s+not|don't|will\s+not|won't|not\s+going\s+to)\s+"
    r"(?:discuss|analy[sz]e|address|cover)\b",
    re.IGNORECASE,
)
_DISMISSAL_PRONOUN_RE = re.compile(
    r"(?:它|其|这个(?:因素|问题|指标|概念|部分)?|这一(?:因素|问题|指标|概念|项|点|部分)?|"
    r"该(?:因素|问题|指标|概念|项|部分)|上述(?:因素|问题|指标|概念|内容)?|前者|后者)|"
    r"\b(?:it|this|that|the\s+(?:factor|topic|concept|metric))\b",
    re.IGNORECASE,
)


def response_incompleteness_reasons(
    parsed: dict,
    *,
    raw: str = "",
    finish_reason: str | None = None,
    depth: str = "standard",
    is_health: bool = True,
    expects_json: bool = True,
    delta_only: bool = False,
    required_concepts: list[dict] | None = None,
) -> list[str]:
    """Return stable reason codes when a provider response is unsafe to show."""

    reasons: list[str] = []
    finish = str(finish_reason or "").lower()
    if finish in {"length", "content_filter"}:
        reasons.append(f"finish_reason:{finish}")

    parse_status = str(parsed.get("_parse_status") or "")
    if parse_status == "invalid":
        reasons.append("invalid_payload")
    elif expects_json and parse_status in {"plain_text", "partial_repair"}:
        reasons.append(f"parse_status:{parse_status}")

    if expects_json and raw and parse_status not in {"valid", "repaired"} and _looks_like_unclosed_json(raw):
        reasons.append("unclosed_json")

    summary_text = str(parsed.get("summary") or "")
    analysis_text = str(parsed.get("analysis") or "")
    reasons.extend(
        visible_response_incompleteness(
            summary_text,
            analysis_text,
            depth=depth,
            is_health=is_health,
            delta_only=delta_only,
        )
    )
    reasons.extend(
        _causal_concept_coverage_reasons(
            summary_text,
            analysis_text,
            required_concepts or [],
        )
    )
    return list(dict.fromkeys(reasons))


def visible_response_incompleteness(
    summary: str,
    analysis: str,
    *,
    depth: str,
    is_health: bool,
    delta_only: bool = False,
) -> list[str]:
    reasons: list[str] = []
    summary_text = (summary or "").strip()
    analysis_text = (analysis or "").strip()
    summary_length = _semantic_length(summary_text)
    analysis_length = _semantic_length(analysis_text)

    if not summary_text:
        reasons.append("empty_summary")
    if not analysis_text:
        reasons.append("empty_analysis")

    if summary_text and _has_dangling_end(summary_text):
        reasons.append("dangling_summary")
    if analysis_text and _has_dangling_end(analysis_text):
        reasons.append("dangling_analysis")
    if analysis_text.count("**") % 2:
        reasons.append("unbalanced_markdown_bold")

    # Delta-only turns intentionally contain just the new judgment or action.
    # Structural checks above still reject empty text, dangling clauses and
    # malformed Markdown; fixed length floors would turn valid follow-ups into
    # provider failures and encourage repetition of the previous answer.
    if is_health and delta_only:
        return reasons

    if is_health and depth == "deep":
        if summary_length < 45:
            reasons.append("deep_summary_too_short")
        if analysis_length < 160:
            reasons.append("deep_analysis_too_short")
        if _normalized(summary_text) == _normalized(analysis_text) and analysis_length < 220:
            reasons.append("deep_analysis_not_expanded")
    elif is_health:
        if summary_length < 24:
            reasons.append("health_summary_too_short")
        if analysis_length < 80:
            reasons.append("health_analysis_too_short")

    return reasons


def _looks_like_unclosed_json(raw: str) -> bool:
    text = (raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    if start < 0:
        return False
    candidate = text[start:].strip()
    return not candidate.endswith("}") or candidate.count("{") != candidate.count("}")


def _has_dangling_end(text: str) -> bool:
    value = text.strip().rstrip("`*_#> ")
    # Citations can appear on either side of the final sentence mark. Remove
    # the whole trailing decoration before checking the last semantic token,
    # so both ``但[1]。`` and ``但。[1]`` remain detectable as fragments.
    value = _TRAILING_CITATION_OR_TERMINATOR_RE.sub("", value).rstrip()
    value = value.rstrip("`*_#> ")
    return bool(_DANGLING_END_RE.search(value))


def _semantic_length(text: str) -> int:
    return len(_SPACE_RE.sub("", _MARKDOWN_RE.sub("", text or "")))


def _normalized(text: str) -> str:
    return _SPACE_RE.sub("", _MARKDOWN_RE.sub("", text or "")).lower()


def _causal_concept_coverage_reasons(
    summary: str,
    analysis: str,
    required_concepts: list[dict],
) -> list[str]:
    if not required_concepts:
        return []
    sentences = _coverage_sentences(summary, analysis)
    reasons: list[str] = []
    for concept in required_concepts:
        key = str(concept.get("key") or "").strip().lower()
        terms = _concept_coverage_terms(concept)
        if terms and any(
            _sentence_has_substantive_mention(
                sentence,
                terms,
                following_sentence=sentences[index + 1] if index + 1 < len(sentences) else "",
            )
            for index, sentence in enumerate(sentences)
        ):
            continue
        stable_key = re.sub(r"[^a-z0-9_]+", "_", key).strip("_") or "unknown"
        reasons.append(f"missing_causal_concept:{stable_key}")
    return reasons


def _coverage_sentences(summary: str, analysis: str) -> list[str]:
    sentences: list[str] = []
    for part in (summary, analysis):
        sentences.extend(
            sentence.strip()
            for sentence in _COVERAGE_SENTENCE_SPLIT_RE.split(part or "")
            if sentence.strip()
        )
    return sentences


def _sentence_has_substantive_mention(
    sentence: str,
    terms: list[str],
    *,
    following_sentence: str = "",
) -> bool:
    clauses = [clause.strip() for clause in _COVERAGE_CLAUSE_SPLIT_RE.split(sentence) if clause.strip()]
    for index, clause in enumerate(clauses):
        if not _contains_any_coverage_term(clause, terms):
            continue
        if _is_dismissal(clause):
            continue

        # A framing clause such as "关于脊柱侧弯，本轮不讨论" carries
        # the concept in one clause and the dismissal in the next. Treat that
        # mention as dismissed, while allowing a different concept discussed
        # substantively elsewhere in the same sentence to count.
        adjacent = [
            clauses[position]
            for position in (index - 1, index + 1)
            if 0 <= position < len(clauses)
        ]
        if _is_concept_only_framing(clause, terms) and any(_is_dismissal(item) for item in adjacent):
            continue
        following_clauses = clauses[index + 1:index + 2]
        if not following_clauses and following_sentence:
            following_clauses.append(following_sentence)
        if (
            _is_concept_mention_framing(clause, terms)
            and any(_is_pronominal_dismissal(item) for item in following_clauses)
        ):
            continue
        return True
    return False


def _contains_any_coverage_term(text: str, terms: list[str]) -> bool:
    lowered = text.lower()
    compact = _compact_coverage_text(lowered)
    return any(_contains_coverage_term(lowered, compact, term) for term in terms)


def _is_dismissal(text: str) -> bool:
    compact = re.sub(r"\s+", "", text)
    compact = _DISMISSAL_PROTECTION_RE.sub("", compact)
    english = _ENGLISH_DISMISSAL_PROTECTION_RE.sub("", text)
    return bool(_DISMISSAL_RE.search(compact) or _ENGLISH_DISMISSAL_RE.search(english))


def _is_pronominal_dismissal(text: str) -> bool:
    return bool(_DISMISSAL_PRONOUN_RE.search(text) and _is_dismissal(text))


def _is_concept_only_framing(clause: str, terms: list[str]) -> bool:
    residue = _concept_framing_residue(clause, terms)
    for framing in (
        "关于", "至于", "对于", "本轮", "这里", "本文", "本回答", "上述", "这个", "这一",
        "该", "因素", "问题", "部分", "方面", "项目", "一项", "这项", "这一点", "而言", "来说",
        "about", "regarding", "asfor", "this", "factor", "topic",
    ):
        residue = residue.replace(framing, "")
    return not residue


def _is_concept_mention_framing(clause: str, terms: list[str]) -> bool:
    residue = _concept_framing_residue(clause, terms)
    for framing in (
        "这次问题", "这个问题", "问题中", "题目中", "用户问题", "用户", "题目", "问题", "内容",
        "还提到了", "也提到了", "提到了", "还提到", "也提到", "提到", "提及", "涉及", "说到", "谈到",
        "列出", "包含", "包括", "问到", "出现", "还", "也", "了", "中", "的", "这个", "这一", "该",
        "因素", "指标", "概念", "部分", "方面", "项目", "一项", "这项",
        "thequestion", "question", "prompt", "also", "mentions", "mentioned", "mention", "includes", "included",
        "include", "lists", "listed", "list", "the", "a", "an", "factor", "topic", "concept", "metric",
    ):
        residue = residue.replace(framing, "")
    return not residue


def _concept_framing_residue(clause: str, terms: list[str]) -> str:
    residue = _compact_coverage_text(clause.lower())
    compact_terms = sorted(
        {_compact_coverage_text(term.lower()) for term in terms if _compact_coverage_text(term.lower())},
        key=len,
        reverse=True,
    )
    for term in compact_terms:
        residue = residue.replace(term, "")
    return residue


def _concept_coverage_terms(concept: dict) -> list[str]:
    raw_terms = concept.get("terms") or concept.get("coverage_terms") or []
    if isinstance(raw_terms, str):
        raw_terms = [raw_terms]
    display = str(concept.get("display") or "").strip()
    values = [str(value).strip() for value in raw_terms if str(value).strip()]
    if display:
        values.append(display)
        values.extend(part for part in re.split(r"[/、()（）]+", display) if part.strip())
    return list(dict.fromkeys(values))


def _contains_coverage_term(text: str, compact_text: str, raw_term: str) -> bool:
    term = str(raw_term or "").strip().lower()
    if not term:
        return False
    if re.fullmatch(r"[a-z0-9][a-z0-9+.-]{1,}", term):
        return bool(re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", text))
    compact_term = _compact_coverage_text(term)
    if not compact_term:
        return False
    if len(compact_term) == 1 and "\u4e00" <= compact_term <= "\u9fff":
        return False
    return compact_term in compact_text


def _compact_coverage_text(text: str) -> str:
    return re.sub(r"[^a-z0-9+.一-鿿-]+", "", text)
