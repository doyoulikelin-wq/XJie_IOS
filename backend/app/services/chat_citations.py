from __future__ import annotations

import re
from dataclasses import dataclass

from app.schemas.literature import CitationBundle
from app.services.health_nlu import CONCEPT_CATALOG


_MARKER_RE = re.compile(r"\[(\d{1,2})\]")
_BOUNDARY_RE = re.compile(r"[。！？!?；;\n\r]|(?<!\d)\.(?!\d)")
_ASCII_TOKEN_RE = re.compile(r"[a-z][a-z0-9+.-]{2,}")
_CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]{2,}")
_SENTENCE_END_RE = re.compile(r"[。！？!?；;.]$")
_ASSOCIATION_CLAUSE_BOUNDARY_RE = re.compile(
    r"[，,。！？!?；;：:\n\r]|(?:但|但是|不过|然而)|\b(?:but|however|whereas)\b",
    re.IGNORECASE,
)
_CAUSAL_CLAUSE_BOUNDARY_RE = re.compile(
    r"[。！？!?；;：:\n\r]|(?:但|但是|不过|然而)|\b(?:but|however|whereas)\b",
    re.IGNORECASE,
)
_TRAILING_DECORATION_RE = re.compile(
    r"(?:\s+|\[\d{1,2}\]|[”\"’'）)\]}*_`~]+)+$"
)
_LEXICAL_PREFIX_RE = re.compile(
    r"^(?:(?:研究|证据|数据)(?:显示|发现|提示|表明)|"
    r"随机对照试验(?:中|显示|提示|表明)?|"
    r"(?:the\s+)?(?:study|evidence|data)\s+(?:shows?|finds?|suggests?|indicates?)|"
    r"(?:in\s+)?(?:a\s+)?randomi[sz]ed\s+controlled\s+trial)\s*",
    re.IGNORECASE,
)
_ASSOCIATION_NEGATION_RE = re.compile(
    r"(?:无关|没有(?:明显|显著)?(?:关系|关联)|不存在(?:明显|显著)?(?:关系|关联)|"
    r"不(?:明显|显著)?(?:相关|关联)|(?:未见|未发现).{0,30}(?:关系|关联)|"
    r"并无(?:明显|显著)?(?:关系|关联)|\bnot\s+(?:associated|correlated|linked)\b|"
    r"\bno\s+(?:association|correlation|relationship)\b|\bunrelated\b)",
    re.IGNORECASE,
)
_DOUBLE_NEGATED_ASSOCIATION_RE = re.compile(
    r"(?:并非|不是)不(?:相关|关联)|\bnot\s+unrelated\b",
    re.IGNORECASE,
)
_ASSOCIATION_CUE_RE = re.compile(
    r"(?:存在.{0,6}(?:关系|关联)|(?:相关|关联)(?:性|风险)?|风险(?:升高|增加|降低|减少)|"
    r"双向(?:关系|关联)|更容易|显著(?:升高|增加|降低|减少)|"
    r"\b(?:associated|association|correlated|correlation|linked|relationship)\b)",
    re.IGNORECASE,
)
_CAUSAL_NEGATION_RE = re.compile(
    r"(?:(?:不|未|没有|并未|不会|不能|无法|尚不能|尚无法).{0,8}(?:导致|造成|引起|诱发)|"
    r"\b(?:does|do|did|will|would|may|might|could)?\s*not\s+"
    r"(?:cause|causes|lead\s+to|result\s+in)\b|\b(?:cannot|can't)\s+"
    r"(?:cause|lead\s+to|result\s+in)\b|\bno\s+causal\s+(?:link|relationship)\b)",
    re.IGNORECASE,
)
_CAUSAL_CUE_RE = re.compile(
    r"(?:导致|造成|引起|诱发|促使|使得|\b(?:cause|causes|caused|causing)\b|"
    r"\b(?:lead|leads|led)\s+to\b|\b(?:result|results|resulted)\s+in\b)",
    re.IGNORECASE,
)
_PROOF_NEGATION_RE = re.compile(
    r"(?:(?:不|未|没有|不能|无法|尚不能|尚无法).{0,8}(?:证明|证实)|"
    r"\b(?:does|do|did|can|could)?\s*not\s+(?:prove|confirm|demonstrate)\b|"
    r"\b(?:cannot|can't)\s+(?:prove|confirm|demonstrate)\b)",
    re.IGNORECASE,
)
_PROOF_CUE_RE = re.compile(r"(?:证明|证实|\b(?:prove|proves|proved|confirm|confirms|confirmed|demonstrate|demonstrates|demonstrated)\b)", re.IGNORECASE)
_DIAGNOSIS_NEGATION_RE = re.compile(
    r"(?:(?:不|未|没有|不能|无法|尚不能|尚无法).{0,8}(?:确诊|诊断)|"
    r"\b(?:does|do|did|can|could)?\s*not\s+(?:diagnose|confirm\s+the\s+diagnosis)\b|"
    r"\b(?:cannot|can't)\s+(?:diagnose|confirm\s+the\s+diagnosis)\b)",
    re.IGNORECASE,
)
_DIAGNOSIS_CUE_RE = re.compile(r"(?:确诊|诊断为|\b(?:diagnose|diagnoses|diagnosed)\b)", re.IGNORECASE)
_UP_DIRECTION_RE = re.compile(
    r"(?:升高|增加|增大|上升|加快|提高|恶化|更高|\b(?:increase|increases|increased|raise|raises|raised|higher|worsen|worsens|worsened)\b)",
    re.IGNORECASE,
)
_DOWN_DIRECTION_RE = re.compile(
    r"(?:降低|减少|下降|减慢|改善|更低|\b(?:decrease|decreases|decreased|reduce|reduces|reduced|lower|lowers|lowered|improve|improves|improved)\b)",
    re.IGNORECASE,
)
_NEGATED_UP_RE = re.compile(
    r"(?:(?:不|未|没有|并未|不会).{0,5}(?:升高|增加|增大|上升|加快|提高)|"
    r"\b(?:does|do|did|will|would|may|might|could)?\s*not\s+"
    r"(?:increase|raise|be\s+higher|worsen)\b|\b(?:cannot|can't)\s+"
    r"(?:increase|raise|be\s+higher|worsen)\b|\bno\s+increase\b)",
    re.IGNORECASE,
)
_NEGATED_DOWN_RE = re.compile(
    r"(?:(?:不|未|没有|并未|不会).{0,5}(?:降低|减少|下降|减慢|改善)|"
    r"\b(?:does|do|did|will|would|may|might|could)?\s*not\s+"
    r"(?:decrease|reduce|lower|improve)\b|\b(?:cannot|can't)\s+"
    r"(?:decrease|reduce|lower|improve)\b|\bno\s+(?:decrease|reduction)\b)",
    re.IGNORECASE,
)
_CAUSAL_DESIGN_RE = re.compile(r"(?:randomi[sz]ed|controlled[_ -]?trial|intervention|experimental)")
_NON_CAUSAL_DESIGN_RE = re.compile(
    r"(?:observational|mechanistic|cohort|cross[_ -]?sectional|case[_ -]?(?:control|report|series)|"
    r"expert|guideline)"
)
_DIAGNOSTIC_DESIGN_RE = re.compile(r"(?:diagnostic|guideline)")


@dataclass(frozen=True)
class CitationSelection:
    summary: str
    analysis: str
    answer_markdown: str
    citations: list[CitationBundle]
    removed_candidate_count: int
    removed_marker_count: int


def select_citations_for_response(
    *,
    summary: str,
    analysis: str,
    answer_markdown: str,
    candidates: list[CitationBundle],
) -> CitationSelection:
    """Keep only markers supported by their original, immutable candidate.

    The provider-facing ``[N]`` indexes are an evidence contract.  We never
    guess that a marker was intended to point at another paper.  Unsupported
    or out-of-range markers are removed, then the surviving candidates are
    compactly renumbered across every user-visible response field.
    """

    fields = (summary or "", analysis or "", answer_markdown or "")
    selected_indexes: list[int] = []
    removed_marker_count = 0
    for text in fields:
        for match in _MARKER_RE.finditer(text):
            original_index = int(match.group(1))
            if not _marker_has_support(text, match, original_index, candidates):
                removed_marker_count += 1
                continue
            if original_index not in selected_indexes:
                selected_indexes.append(original_index)

    mapping = {
        original_index: compact_index
        for compact_index, original_index in enumerate(selected_indexes, start=1)
    }

    selected = [candidates[index - 1] for index in selected_indexes]
    return CitationSelection(
        summary=_rewrite_markers(summary, candidates, mapping),
        analysis=_rewrite_markers(analysis, candidates, mapping),
        answer_markdown=_rewrite_markers(answer_markdown, candidates, mapping),
        citations=selected,
        removed_candidate_count=max(0, len(candidates) - len(selected)),
        removed_marker_count=removed_marker_count,
    )


def _marker_has_support(
    text: str,
    match: re.Match[str],
    original_index: int,
    candidates: list[CitationBundle],
) -> bool:
    if not 1 <= original_index <= len(candidates):
        return False
    context = _citation_context(text, match)
    if not context:
        return False
    candidate = candidates[original_index - 1]
    return (
        _support_score(context, candidate.claim_text).supported
        and _known_relation_subjects_are_supported(context, candidate.claim_text)
        and _semantic_direction_is_supported(context, candidate)
    )


def _rewrite_markers(
    text: str,
    candidates: list[CitationBundle],
    mapping: dict[int, int],
) -> str:
    source = text or ""

    def replace(match: re.Match[str]) -> str:
        original_index = int(match.group(1))
        if not _marker_has_support(source, match, original_index, candidates):
            return ""
        replacement = mapping.get(original_index)
        return f"[{replacement}]" if replacement is not None else ""

    value = _MARKER_RE.sub(replace, source)
    value = re.sub(r"[ \t]{2,}", " ", value)
    value = re.sub(r"[ \t]+([，。！？；：,.!?;:])", r"\1", value)
    return value.strip()


@dataclass(frozen=True)
class _SupportScore:
    concept_overlap: int
    context_concept_count: int
    claim_concept_count: int
    shared_ngram_count: int
    lexical_recall: float
    shared_ascii_count: int
    single_concept_equivalent: bool
    strict_lexical_equivalent: bool

    @property
    def supported(self) -> bool:
        # A multi-concept medical claim describes a relationship, not merely
        # an outcome.  Lexical overlap on a shared outcome such as insomnia
        # must never let a different exposure borrow that claim's citation.
        if self.claim_concept_count >= 2:
            return self.concept_overlap >= 2

        # A catalogued single-concept claim may be expressed through an alias
        # (for example, blood pressure vs. BP) without exact wording overlap.
        if self.claim_concept_count == 1:
            return (
                self.concept_overlap == 1
                and self.context_concept_count == 1
                and self.single_concept_equivalent
            )

        # Unknown domains remain possible, but only through strict lexical
        # agreement.  Do not use this fallback when just one side contains a
        # known medical concept, because that would reintroduce relation drift.
        return self.context_concept_count == 0 and self.strict_lexical_equivalent


def _support_score(context: str, claim: str) -> _SupportScore:
    context_concepts = _concept_keys(context)
    claim_concepts = _concept_keys(claim)
    shared_concepts = context_concepts & claim_concepts

    context_ngrams = _lexical_ngrams(context)
    claim_ngrams = _lexical_ngrams(claim)
    shared_ngrams = context_ngrams & claim_ngrams
    lexical_recall = len(shared_ngrams) / max(1, len(claim_ngrams))

    context_ascii = set(_ASCII_TOKEN_RE.findall(context.lower()))
    claim_ascii = set(_ASCII_TOKEN_RE.findall(claim.lower()))
    shared_ascii = context_ascii & claim_ascii
    shared_concept = next(iter(shared_concepts)) if len(shared_concepts) == 1 else None

    return _SupportScore(
        concept_overlap=len(shared_concepts),
        context_concept_count=len(context_concepts),
        claim_concept_count=len(claim_concepts),
        shared_ngram_count=len(shared_ngrams),
        lexical_recall=lexical_recall,
        shared_ascii_count=len(shared_ascii),
        single_concept_equivalent=bool(
            shared_concept
            and _strict_text_equivalent(
                _canonicalize_concept(context, shared_concept),
                _canonicalize_concept(claim, shared_concept),
            )
        ),
        strict_lexical_equivalent=_strict_text_equivalent(context, claim),
    )


def _known_relation_subjects_are_supported(context: str, claim: str) -> bool:
    claim_concepts = _concept_keys(claim)

    if _association_polarities(context):
        context_signatures = _association_signatures(context)
        claim_signatures = _association_signatures(claim)
        if context_signatures or claim_signatures:
            if len(context_signatures) != 1 or len(claim_signatures) != 1:
                return False
            context_signature = next(iter(context_signatures))
            claim_signature = next(iter(claim_signatures))
            if not context_signature.issubset(claim_signature):
                return False
            if len(claim_concepts) >= 2 and len(context_signature & claim_signature) < 2:
                return False

    if _relation_polarities(
        context,
        cue=_CAUSAL_CUE_RE,
        negation=_CAUSAL_NEGATION_RE,
    ):
        context_signatures = _causal_signatures(context)
        claim_signatures = _causal_signatures(claim)
        if context_signatures or claim_signatures:
            if len(context_signatures) != 1 or len(claim_signatures) != 1:
                return False
            context_left, context_right = next(iter(context_signatures))
            claim_left, claim_right = next(iter(claim_signatures))
            if not context_left.issubset(claim_left):
                return False
            if not context_right.issubset(claim_right):
                return False
            shared_roles = (context_left & claim_left) | (context_right & claim_right)
            if len(claim_concepts) >= 2 and len(shared_roles) < 2:
                return False

    # When no relation cue can identify subjects, the support score remains
    # the conservative fallback.  Known multi-concept relations above must be
    # attributable to a unique relation-bearing clause (and causal roles).
    return True


def _association_signatures(text: str) -> set[frozenset[str]]:
    signatures: set[frozenset[str]] = set()
    for clause in _relation_clauses(
        text,
        patterns=(_ASSOCIATION_CUE_RE, _ASSOCIATION_NEGATION_RE),
        boundary=_ASSOCIATION_CLAUSE_BOUNDARY_RE,
    ):
        concepts = frozenset(_concept_keys(clause))
        if concepts:
            signatures.add(concepts)
    return signatures


def _causal_signatures(text: str) -> set[tuple[frozenset[str], frozenset[str]]]:
    signatures: set[tuple[frozenset[str], frozenset[str]]] = set()
    for clause, cue_start, cue_end in _relation_clause_matches(
        text,
        pattern=_CAUSAL_CUE_RE,
        boundary=_CAUSAL_CLAUSE_BOUNDARY_RE,
    ):
        left = frozenset(_concept_keys(clause[:cue_start]))
        right = frozenset(_concept_keys(clause[cue_end:]))
        if left or right:
            signatures.add((left, right))
    return signatures


def _relation_clauses(
    text: str,
    *,
    patterns: tuple[re.Pattern[str], ...],
    boundary: re.Pattern[str],
) -> set[str]:
    clauses: set[str] = set()
    for pattern in patterns:
        for clause, _, _ in _relation_clause_matches(text, pattern=pattern, boundary=boundary):
            clauses.add(clause)
    return clauses


def _relation_clause_matches(
    text: str,
    *,
    pattern: re.Pattern[str],
    boundary: re.Pattern[str],
) -> list[tuple[str, int, int]]:
    value = text or ""
    boundaries = list(boundary.finditer(value))
    results: list[tuple[str, int, int]] = []
    for match in pattern.finditer(value):
        start = 0
        end = len(value)
        for separator in boundaries:
            if separator.end() <= match.start():
                start = separator.end()
                continue
            if separator.start() >= match.end():
                end = separator.start()
                break
        clause = value[start:end].strip()
        if clause:
            leading_trim = len(value[start:end]) - len(value[start:end].lstrip())
            clause_start = start + leading_trim
            results.append(
                (
                    clause,
                    match.start() - clause_start,
                    match.end() - clause_start,
                )
            )
    return results


def _citation_context(text: str, match: re.Match[str]) -> str:
    before = _strip_trailing_citation_decorations(text[:match.start()])
    if not before:
        return ""
    if _SENTENCE_END_RE.search(before):
        sentence_without_end = before.rstrip("。！？!?；;.")
        previous_boundaries = list(_BOUNDARY_RE.finditer(sentence_without_end))
        start = (
            previous_boundaries[-1].end()
            if previous_boundaries
            else max(0, len(sentence_without_end) - 220)
        )
        return sentence_without_end[start:].strip()
    previous_boundaries = list(_BOUNDARY_RE.finditer(before))
    start = previous_boundaries[-1].end() if previous_boundaries else max(0, len(before) - 220)
    return before[start:].strip()


def _strip_trailing_citation_decorations(value: str) -> str:
    current = value.rstrip()
    while current:
        stripped = _TRAILING_DECORATION_RE.sub("", current).rstrip()
        if stripped == current:
            return current
        current = stripped
    return ""


def _semantic_direction_is_supported(context: str, candidate: CitationBundle) -> bool:
    claim = candidate.claim_text or ""
    context_association = _association_polarities(context)
    claim_association = _association_polarities(claim)
    if len(context_association) > 1 or len(claim_association) > 1:
        return False
    if context_association and context_association != claim_association:
        return False

    context_causal = _relation_polarities(
        context,
        cue=_CAUSAL_CUE_RE,
        negation=_CAUSAL_NEGATION_RE,
    )
    claim_causal = _relation_polarities(
        claim,
        cue=_CAUSAL_CUE_RE,
        negation=_CAUSAL_NEGATION_RE,
    )
    if context_causal:
        if len(context_causal) != 1 or len(claim_causal) != 1 or context_causal != claim_causal:
            return False
        if context_causal == {"affirmed"}:
            answer_strength = _causal_strength(context)
            claim_strength = _candidate_causal_strength(candidate)
            if answer_strength == 0 or answer_strength > claim_strength:
                return False

    context_proof = _relation_polarities(
        context,
        cue=_PROOF_CUE_RE,
        negation=_PROOF_NEGATION_RE,
    )
    if len(context_proof) > 1:
        return False
    if context_proof == {"affirmed"} and not _candidate_has_strong_experimental_support(candidate):
        return False
    context_diagnosis = _relation_polarities(
        context,
        cue=_DIAGNOSIS_CUE_RE,
        negation=_DIAGNOSIS_NEGATION_RE,
    )
    if len(context_diagnosis) > 1:
        return False
    if context_diagnosis == {"affirmed"} and not _candidate_supports_diagnosis(candidate):
        return False

    context_direction = _direction_profile(context)
    claim_direction = _direction_profile(claim)
    if _direction_is_ambiguous(context_direction) or _direction_is_ambiguous(claim_direction):
        return False
    if "up" in context_direction.denied and "up" in claim_direction.asserted:
        return False
    if "down" in context_direction.denied and "down" in claim_direction.asserted:
        return False
    if "up" in claim_direction.denied and "up" in context_direction.asserted:
        return False
    if "down" in claim_direction.denied and "down" in context_direction.asserted:
        return False
    if context_direction.asserted == {"up"} and claim_direction.asserted == {"down"}:
        return False
    if context_direction.asserted == {"down"} and claim_direction.asserted == {"up"}:
        return False
    return True


def _direction_is_ambiguous(profile: _DirectionProfile) -> bool:
    return bool(
        len(profile.asserted) > 1
        or len(profile.denied) > 1
        or profile.asserted & profile.denied
    )


def _relation_polarities(
    text: str,
    *,
    cue: re.Pattern[str],
    negation: re.Pattern[str],
) -> set[str]:
    value = text or ""
    polarities: set[str] = set()
    if negation.search(value):
        polarities.add("negated")
    without_negation = negation.sub(lambda match: " " * len(match.group(0)), value)
    if cue.search(without_negation):
        polarities.add("affirmed")
    return polarities


def _association_polarities(text: str) -> set[str]:
    value = _DOUBLE_NEGATED_ASSOCIATION_RE.sub("相关", text or "")
    return _relation_polarities(
        value,
        cue=_ASSOCIATION_CUE_RE,
        negation=_ASSOCIATION_NEGATION_RE,
    )


def _causal_strength(text: str) -> int:
    value = _CAUSAL_NEGATION_RE.sub(lambda match: " " * len(match.group(0)), text or "")
    strengths: list[int] = []
    for match in _CAUSAL_CUE_RE.finditer(value):
        prefix = value[max(0, match.start() - 32):match.start()]
        strengths.append(1 if _causal_cue_is_hedged(prefix) else 2)
    return max(strengths, default=0)


def _causal_cue_is_hedged(prefix: str) -> bool:
    return bool(
        re.search(r"(?:可能|也许|或许|或可|可以|可).{0,12}$", prefix)
        or re.search(r"(?:如果|若|假如).{0,24}$", prefix)
        or re.search(r"在.{0,16}(?:时|情况下).{0,8}$", prefix)
        or re.search(r"\b(?:may|might|could|can|possibly)\b(?:\W+\w+){0,6}\W*$", prefix, re.IGNORECASE)
        or re.search(r"\b(?:if|when)\b(?:\W+\w+){0,8}\W*$", prefix, re.IGNORECASE)
    )


def _candidate_causal_strength(candidate: CitationBundle) -> int:
    if _relation_polarities(
        candidate.claim_text,
        cue=_CAUSAL_CUE_RE,
        negation=_CAUSAL_NEGATION_RE,
    ) != {"affirmed"}:
        return 0
    claim_strength = _causal_strength(candidate.claim_text)
    if claim_strength < 2:
        return claim_strength
    return 2 if _candidate_has_strong_experimental_support(candidate) else 1


def _candidate_has_strong_experimental_support(candidate: CitationBundle) -> bool:
    design = (candidate.study_design or "").lower()
    if candidate.confidence != "high" or not design:
        return False
    if _NON_CAUSAL_DESIGN_RE.search(design) or not _CAUSAL_DESIGN_RE.search(design):
        return False
    return True


def _candidate_supports_diagnosis(candidate: CitationBundle) -> bool:
    design = (candidate.study_design or "").lower()
    claim_diagnosis = _relation_polarities(
        candidate.claim_text,
        cue=_DIAGNOSIS_CUE_RE,
        negation=_DIAGNOSIS_NEGATION_RE,
    )
    return (
        claim_diagnosis == {"affirmed"}
        and candidate.confidence == "high"
        and bool(_DIAGNOSTIC_DESIGN_RE.search(design))
    )


@dataclass(frozen=True)
class _DirectionProfile:
    asserted: set[str]
    denied: set[str]


def _direction_profile(text: str) -> _DirectionProfile:
    value = text or ""
    denied: set[str] = set()
    if _NEGATED_UP_RE.search(value):
        denied.add("up")
    if _NEGATED_DOWN_RE.search(value):
        denied.add("down")
    without_negated = _NEGATED_UP_RE.sub(lambda match: " " * len(match.group(0)), value)
    without_negated = _NEGATED_DOWN_RE.sub(
        lambda match: " " * len(match.group(0)),
        without_negated,
    )
    asserted: set[str] = set()
    if _UP_DIRECTION_RE.search(without_negated):
        asserted.add("up")
    if _DOWN_DIRECTION_RE.search(without_negated):
        asserted.add("down")
    return _DirectionProfile(asserted=asserted, denied=denied)


@dataclass(frozen=True)
class _ConceptMatch:
    key: str
    start: int
    end: int
    display_match: bool


def _concept_keys(text: str) -> set[str]:
    matches = _concept_matches(text)
    keys: set[str] = set()
    for match in matches:
        if any(
            other.key != match.key
            and other.start <= match.start
            and other.end >= match.end
            and (other.start < match.start or other.end > match.end)
            for other in matches
        ):
            continue

        same_span = [
            other
            for other in matches
            if other.start == match.start and other.end == match.end
        ]
        exact_displays = {other.key for other in same_span if other.display_match}
        if exact_displays and match.key not in exact_displays:
            continue
        keys.add(match.key)
    return keys


def _concept_matches(text: str) -> list[_ConceptMatch]:
    normalized = _normalize(text)
    matches: dict[tuple[str, int, int], _ConceptMatch] = {}
    for concept in CONCEPT_CATALOG:
        display_normalized = _normalize(concept.display)
        for alias in (concept.display, *concept.aliases):
            alias_normalized = _normalize(alias)
            if not alias_normalized:
                continue
            pattern = _concept_alias_pattern(alias_normalized)
            for match in pattern.finditer(normalized):
                key = (concept.key, match.start(), match.end())
                candidate = _ConceptMatch(
                    key=concept.key,
                    start=match.start(),
                    end=match.end(),
                    display_match=alias_normalized == display_normalized,
                )
                current = matches.get(key)
                if current is None or candidate.display_match:
                    matches[key] = candidate
    return list(matches.values())


def _concept_alias_pattern(alias_normalized: str) -> re.Pattern[str]:
    parts = alias_normalized.split()
    contains_cjk = bool(re.search(r"[\u4e00-\u9fff]", alias_normalized))
    separator = r"\s*" if contains_cjk else r"\s+"
    body = separator.join(re.escape(part) for part in parts)
    if contains_cjk:
        return re.compile(body, re.IGNORECASE)
    return re.compile(rf"(?<![a-z0-9]){body}(?![a-z0-9])", re.IGNORECASE)


def _canonicalize_concept(text: str, concept_key: str) -> str:
    value = _comparison_text(text)
    concept = next(
        (item for item in CONCEPT_CATALOG if item.key == concept_key),
        None,
    )
    if concept is None:
        return value
    aliases = sorted(
        {_normalize(alias) for alias in (concept.display, *concept.aliases)},
        key=lambda alias: len(alias.replace(" ", "")),
        reverse=True,
    )
    placeholder = f" concept{concept.key.replace('_', '')} "
    for alias in aliases:
        if alias:
            value = _concept_alias_pattern(alias).sub(placeholder, value)
    return _comparison_text(value)


def _strict_text_equivalent(left: str, right: str) -> bool:
    return _comparison_text(left) == _comparison_text(right)


def _comparison_text(text: str) -> str:
    value = _normalize(text)
    value = re.sub(r"(?<!\d)\.(?!\d)", " ", value)
    previous = None
    while previous != value:
        previous = value
        value = _LEXICAL_PREFIX_RE.sub("", value).strip()
    return re.sub(r"\s+", " ", value).strip(" .-")


def _lexical_ngrams(text: str) -> set[str]:
    normalized = _normalize(text)
    ngrams: set[str] = set()
    for run in _CJK_RUN_RE.findall(normalized):
        for size in (2, 3):
            ngrams.update(run[index:index + size] for index in range(len(run) - size + 1))
    ngrams.update(_ASCII_TOKEN_RE.findall(normalized))
    return ngrams


def _normalize(value: object) -> str:
    return re.sub(r"[^a-z0-9+.\u4e00-\u9fff-]+", " ", str(value or "").lower()).strip()
