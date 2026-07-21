import json
from contextlib import nullcontext

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.literature import Claim, IngestJob, Literature
from app.schemas.literature import CitationBundle
from app.services.health_nlu import analyze_health_message, concept_alias_groups
from app.services.literature import retrieval
from app.services.literature import core_evidence


def test_compound_causal_retrieval_requires_two_concept_groups(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    relevant = _add_claim(
        db,
        pmid="1",
        title="Rhinitis and sleep",
        claim_text="过敏性鼻炎与失眠和睡眠呼吸障碍风险增加相关。",
        exposure="鼻炎",
        outcome="失眠",
    )
    _add_claim(
        db,
        pmid="2",
        title="Insomnia and insulin",
        claim_text="失眠与胰岛素敏感性未见显著关联。",
        exposure="失眠",
        outcome="胰岛素敏感性",
    )
    db.commit()
    monkeypatch.setattr(retrieval, "embed_text", lambda _text: ([1.0, 0.0], "local-hash-v1"))

    nlu = analyze_health_message("我的失眠抑郁是不是跟鼻炎脊柱侧弯导致缺氧有关系")
    citations = retrieval.retrieve_claims(
        db,
        query=nlu["normalized_query"],
        concept_groups=concept_alias_groups(nlu["concept_keys"]),
        min_concept_groups=2,
        threshold=0.0,
    )

    assert [item.claim_id for item in citations] == [relevant.id]
    assert all("胰岛素" not in item.claim_text for item in citations)


def test_ascii_concept_aliases_require_token_boundaries() -> None:
    groups = {
        "heart_rate": ["heart rate"],
        "rem_sleep": ["REM"],
    }

    assert retrieval._matched_concept_groups(
        "Heart rate measurements in adults.",
        groups,
    ) == 1
    assert retrieval._matched_concept_groups(
        "REM sleep was measured overnight.",
        groups,
    ) == 1
    assert retrieval._matched_concept_groups(
        "Heart rate and REM sleep were measured overnight.",
        groups,
    ) == 2


def test_core_evidence_upsert_is_idempotent(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    monkeypatch.setattr(core_evidence, "embed_text", lambda _text: ([1.0, 0.0], "local-hash-v1"))
    monkeypatch.setattr(retrieval, "embed_text", lambda _text: ([1.0, 0.0], "local-hash-v1"))

    first = core_evidence.upsert_core_evidence(db)
    db.query(Literature).filter(Literature.pmid == "32053609").one().title = "stale title"
    db.commit()
    second = core_evidence.upsert_core_evidence(db)

    assert first["seed_id"] == core_evidence.CORE_EVIDENCE_SEED_ID
    assert len(first["manifest_sha256"]) == 64
    assert first["inserted_literature"] == 4
    assert first["inserted_claims"] == 4
    assert first["updated_claims"] == 0
    assert first["processed_manifest_items"] == 4
    assert first["embedding_models"] == ["local-hash-v1"]
    assert second["inserted_literature"] == 0
    assert second["inserted_claims"] == 0
    assert second["updated_claims"] == 4
    assert db.query(Literature).count() == 4
    assert db.query(Claim).count() == 4
    jobs = db.query(IngestJob).order_by(IngestJob.id).all()
    assert len(jobs) == 2
    assert all(job.status == "ok" for job in jobs)
    assert jobs[0].meta["seed_id"] == core_evidence.CORE_EVIDENCE_SEED_ID
    assert jobs[0].meta["manifest_sha256"] == first["manifest_sha256"]
    assert jobs[0].meta["execution"] == "explicit_cli"
    assert jobs[0].inserted_count == 4
    assert jobs[0].skipped_count == 0
    assert jobs[1].inserted_count == 0
    assert jobs[1].skipped_count == 4
    assert jobs[1].meta["inserted_literature"] == 0
    assert jobs[1].meta["updated_claims"] == 4
    assert db.query(Literature).filter(Literature.pmid == "32053609").one().title.startswith(
        "The association between allergic rhinitis and sleep"
    )

    nlu = analyze_health_message("我的失眠抑郁是不是跟鼻炎脊柱侧弯导致缺氧有关系")
    citations = retrieval.retrieve_claims(
        db,
        query=nlu["normalized_query"],
        concept_groups=concept_alias_groups(nlu["concept_keys"]),
        min_concept_groups=2,
        threshold=0.0,
    )
    assert {item.claim_id for item in citations} == {
        claim.id for claim in db.query(Claim).all()
    }


def test_repeated_core_seed_preserves_manually_disabled_claim(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    monkeypatch.setattr(core_evidence, "embed_text", lambda _text: ([1.0], "local-hash-v1"))

    core_evidence.upsert_core_evidence(db)
    disabled = next(
        claim
        for claim in db.query(Claim).all()
        if "core:rhinitis_sleep:32053609" in (claim.tags or [])
    )
    disabled.enabled = False
    db.commit()

    second = core_evidence.upsert_core_evidence(db)
    db.refresh(disabled)

    assert second["updated_claims"] == 4
    assert disabled.enabled is False


def test_existing_literature_with_new_claims_keeps_standard_audit_counts(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    monkeypatch.setattr(core_evidence, "embed_text", lambda _text: ([1.0], "local-hash-v1"))
    for item in core_evidence.CORE_EVIDENCE:
        db.add(Literature(
            pmid=item["pmid"],
            title=f"stale {item['pmid']}",
            authors=[],
            language="en",
            evidence_level=item["evidence_level"],
            conclusion_zh="stale",
            topics=["general"],
            source="pubmed",
            reviewed=False,
        ))
    db.commit()

    result = core_evidence.upsert_core_evidence(db)

    assert result["inserted_literature"] == 0
    assert result["inserted_claims"] == 4
    assert result["updated_claims"] == 0
    assert db.query(Literature).count() == 4
    assert db.query(Claim).count() == 4
    job = db.query(IngestJob).one()
    assert job.inserted_count == 0
    assert job.skipped_count == 4
    assert job.meta["inserted_literature"] == 0
    assert job.meta["inserted_claims"] == 4
    assert job.meta["processed_manifest_items"] == 4


def test_build_citation_block_includes_population_confidence_and_boundaries() -> None:
    citations = [
        CitationBundle(
            claim_id=1,
            literature_id=1,
            claim_text="严重脊柱侧弯在肺活量降低时可导致夜间低氧。",
            evidence_level="L3",
            short_ref="Author et al., Journal 2020",
            population="13名严重胸椎脊柱侧弯患者",
            study_design="mechanistic_observational_study",
            sample_size=13,
            confidence="medium",
        ),
        CitationBundle(
            claim_id=2,
            literature_id=2,
            claim_text="成人睡眠呼吸暂停需要客观睡眠检测。",
            evidence_level="L4",
            short_ref="Guideline Group, Journal 2017",
            population="怀疑成人阻塞性睡眠呼吸暂停的人群",
            study_design="clinical_practice_guideline",
            sample_size=None,
            confidence="high",
        ),
    ]

    block = retrieval.build_citation_block(citations)

    assert block.index("[1]") < block.index("[2]")
    assert "适用人群：13名严重胸椎脊柱侧弯患者" in block
    assert "研究类型=mechanistic_observational_study" in block
    assert "样本量=13" in block
    assert "claim confidence=medium" in block
    assert "不能据此确认个体因果或诊断" in block
    assert "claim confidence=high" in block
    assert "样本量=未报告" in block
    assert "n=?" not in block


def test_core_evidence_cli_preview_is_read_only(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        core_evidence,
        "SessionLocal",
        lambda: (_ for _ in ()).throw(AssertionError("preview must not open a DB session")),
    )
    monkeypatch.setattr(
        core_evidence,
        "embed_text",
        lambda _text: (_ for _ in ()).throw(AssertionError("preview must not embed")),
    )

    assert core_evidence.main([]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "preview"
    assert payload["seed_id"] == core_evidence.CORE_EVIDENCE_SEED_ID
    assert len(payload["manifest_sha256"]) == 64
    assert payload["manifest_count"] == 4


def test_core_evidence_seed_failure_is_audited() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    with pytest.raises(RuntimeError, match="embedding unavailable"):
        core_evidence.upsert_core_evidence(
            db,
            embedder=lambda _text: (_ for _ in ()).throw(RuntimeError("embedding unavailable")),
        )

    jobs = db.query(IngestJob).all()
    assert len(jobs) == 1
    assert jobs[0].status == "error"
    assert jobs[0].meta["seed_id"] == core_evidence.CORE_EVIDENCE_SEED_ID
    assert "RuntimeError: embedding unavailable" in jobs[0].error
    assert db.query(Literature).count() == 0
    assert db.query(Claim).count() == 0


def test_core_evidence_cli_apply_uses_explicit_session(monkeypatch, capsys) -> None:
    db = object()
    expected = {
        "seed_id": core_evidence.CORE_EVIDENCE_SEED_ID,
        "audit_job_id": 9,
        "manifest_count": 4,
        "processed_manifest_items": 4,
        "inserted_literature": 4,
        "inserted_claims": 4,
        "updated_claims": 0,
        "embedding_models": ["local-hash-v1"],
    }
    monkeypatch.setattr(core_evidence, "SessionLocal", lambda: nullcontext(db))
    monkeypatch.setattr(
        core_evidence,
        "upsert_core_evidence",
        lambda session: expected if session is db else None,
    )

    assert core_evidence.main(["--apply"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"mode": "applied", **expected}


def _add_claim(
    db,
    *,
    pmid: str,
    title: str,
    claim_text: str,
    exposure: str,
    outcome: str,
) -> Claim:
    literature = Literature(
        pmid=pmid,
        title=title,
        authors=["Test Author"],
        journal="Test Journal",
        year=2026,
        language="en",
        evidence_level="L1",
        study_design="test",
        conclusion_zh=claim_text,
        topics=["sleep"],
        reviewed=True,
    )
    db.add(literature)
    db.flush()
    claim = Claim(
        literature_id=literature.id,
        claim_text=claim_text,
        exposure=exposure,
        outcome=outcome,
        confidence="high",
        topics=["sleep"],
        tags=[],
        evidence_level="L1",
        embedding=[1.0, 0.0],
        embedding_model="local-hash-v1",
        enabled=True,
    )
    db.add(claim)
    db.flush()
    return claim
