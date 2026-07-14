from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.literature import Claim, IngestJob, Literature
from app.services.literature.embedding import embed_text


CORE_EVIDENCE_SEED_ID = "xjie-core-evidence-2026-07-10-v1"
REVIEWER = CORE_EVIDENCE_SEED_ID

CORE_EVIDENCE = (
    {
        "pmid": "32053609",
        "doi": "10.1371/journal.pone.0228533",
        "title": "The association between allergic rhinitis and sleep: A systematic review and meta-analysis of observational studies.",
        "authors": ["Jiaomei Liu", "Xinge Zhang", "Yingying Zhao", "Yujiao Wang"],
        "journal": "PLoS One",
        "year": 2020,
        "evidence_level": "L1",
        "study_design": "systematic_review_meta_analysis",
        "population": "27项观察性研究；总体证据质量为低至极低",
        "conclusion": "过敏性鼻炎与失眠、睡眠呼吸障碍、阻塞性睡眠呼吸暂停和打鼾等睡眠问题存在统计关联，但观察性证据不能证明某位患者已发生缺氧。",
        "claim": {
            "key": "core:rhinitis_sleep:32053609",
            "text": "过敏性鼻炎与失眠、睡眠呼吸障碍和打鼾风险增加相关，但这种关联不能单独证明个人存在缺氧或确定鼻炎是失眠的唯一病因。",
            "exposure": "过敏性鼻炎、鼻炎、鼻塞",
            "outcome": "失眠、睡眠呼吸障碍、睡眠质量",
            "confidence": "medium",
            "tags": ["鼻炎", "过敏性鼻炎", "失眠", "睡眠", "睡眠呼吸障碍", "缺氧"],
        },
    },
    {
        "pmid": "3150290",
        "doi": "10.1016/0007-0971(88)90062-9",
        "title": "Nocturnal hypoxaemia in severe scoliosis.",
        "authors": ["B Midgren", "K Petersson", "L Hansson", "L Eriksson", "P Airikkala", "D Elmqvist"],
        "journal": "Br J Dis Chest",
        "year": 1988,
        "evidence_level": "L3",
        "study_design": "mechanistic_observational_study",
        "sample_size": 13,
        "population": "13名严重胸椎脊柱侧弯患者",
        "conclusion": "严重胸椎脊柱侧弯患者可因低肺活量和睡眠低通气出现夜间低氧；该结果不能外推到所有轻度或未分级的脊柱侧弯。",
        "claim": {
            "key": "core:scoliosis_hypoxia:3150290",
            "text": "严重胸椎脊柱侧弯在肺活量明显降低或低通气时可导致夜间低氧；轻度或未评估严重度的脊柱侧弯不能据此直接判定缺氧。",
            "exposure": "严重胸椎脊柱侧弯、脊柱侧凸、低肺活量",
            "outcome": "睡眠低通气、夜间低氧、缺氧",
            "confidence": "medium",
            "tags": ["脊柱侧弯", "脊柱侧凸", "肺功能", "低通气", "低氧", "缺氧", "睡眠"],
        },
    },
    {
        "pmid": "23814343",
        "doi": "10.5665/sleep.2810",
        "title": "A Systematic Review Assessing Bidirectionality between Sleep Disturbances, Anxiety, and Depression.",
        "authors": ["Pasquale K Alvaro", "Rachel M Roberts", "Jodie K Harris"],
        "journal": "Sleep",
        "year": 2013,
        "evidence_level": "L1",
        "study_design": "systematic_review",
        "population": "9项双向关系研究，其中8项为纵向研究",
        "conclusion": "现有纵向证据支持失眠与焦虑、抑郁之间存在双向关系，但研究数量和异质性限制了确定因果方向。",
        "claim": {
            "key": "core:insomnia_depression:23814343",
            "text": "失眠与抑郁存在双向关联：持续失眠可增加抑郁风险，抑郁也可维持或加重失眠；这不等于两者必然由同一个缺氧原因造成。",
            "exposure": "失眠、睡眠质量下降",
            "outcome": "抑郁、焦虑、持续失眠",
            "confidence": "medium",
            "tags": ["失眠", "睡眠", "抑郁", "情绪低落", "焦虑", "双向关联"],
        },
    },
    {
        "pmid": "28162150",
        "doi": "10.5664/jcsm.6506",
        "title": "Clinical Practice Guideline for Diagnostic Testing for Adult Obstructive Sleep Apnea: An American Academy of Sleep Medicine Clinical Practice Guideline.",
        "authors": ["Vishesh K Kapur", "Dennis H Auckley", "Susmita Chowdhuri", "David C Kuhlmann", "Reena Mehra", "Kannan Ramar", "C G Harrod"],
        "journal": "J Clin Sleep Med",
        "year": 2017,
        "evidence_level": "L4",
        "study_design": "clinical_practice_guideline",
        "population": "怀疑成人阻塞性睡眠呼吸暂停的人群",
        "conclusion": "成人阻塞性睡眠呼吸暂停需要结合全面睡眠评估和客观睡眠检测诊断；严重失眠或疑似睡眠低通气时优先使用多导睡眠监测。",
        "claim": {
            "key": "core:osa_diagnosis:28162150",
            "text": "怀疑睡眠呼吸暂停、睡眠相关低通气或严重失眠时，需要综合睡眠评估和客观睡眠检测；仅凭症状或对低氧、缺氧的主观怀疑不能确诊。",
            "exposure": "睡眠呼吸暂停风险、严重失眠、疑似睡眠低通气",
            "outcome": "多导睡眠监测或规范睡眠呼吸检测",
            "confidence": "high",
            "tags": ["睡眠呼吸暂停", "睡眠呼吸障碍", "严重失眠", "低通气", "低氧", "缺氧", "诊断"],
        },
    },
)


def _manifest_sha256() -> str:
    payload = json.dumps(CORE_EVIDENCE, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def upsert_core_evidence(
    db: Session,
    *,
    embedder: Callable[[str], tuple[list[float], str]] | None = None,
    audit: bool = True,
) -> dict[str, object]:
    """Idempotently seed reviewed evidence through an explicit operator action.

    This function is intentionally not called during application startup.  A
    production operator invokes the module CLI once per deployment when the
    manifest changes, making any configured external embedding call explicit.
    """

    embed = embedder or embed_text
    inserted_literature = 0
    inserted_claims = 0
    updated_claims = 0
    embedding_models: set[str] = set()
    audit_job = _start_audit_job(db) if audit else None

    try:
        for item in CORE_EVIDENCE:
            literature = db.execute(
                select(Literature).where(Literature.pmid == item["pmid"])
            ).scalars().first()
            if literature is None:
                literature = Literature(
                    pmid=item["pmid"],
                    doi=item["doi"],
                    title=item["title"],
                    authors=item["authors"],
                    journal=item["journal"],
                    year=item["year"],
                    language="en",
                    evidence_level=item["evidence_level"],
                    study_design=item["study_design"],
                    sample_size=item.get("sample_size"),
                    population=item["population"],
                    conclusion_zh=item["conclusion"],
                    topics=["sleep", "general"],
                    source="pubmed",
                    reviewed=True,
                    reviewer=REVIEWER,
                )
                db.add(literature)
                db.flush()
                inserted_literature += 1
            else:
                literature_values = {
                    "doi": item["doi"],
                    "title": item["title"],
                    "authors": item["authors"],
                    "journal": item["journal"],
                    "year": item["year"],
                    "language": "en",
                    "evidence_level": item["evidence_level"],
                    "study_design": item["study_design"],
                    "sample_size": item.get("sample_size"),
                    "population": item["population"],
                    "conclusion_zh": item["conclusion"],
                    "topics": ["sleep", "general"],
                    "source": "pubmed",
                    "reviewed": True,
                    "reviewer": REVIEWER,
                }
                for key, value in literature_values.items():
                    setattr(literature, key, value)

            claim_data = item["claim"]
            existing = next(
                (
                    claim
                    for claim in db.execute(
                        select(Claim).where(Claim.literature_id == literature.id)
                    ).scalars().all()
                    if claim_data["key"] in (claim.tags or [])
                ),
                None,
            )
            embedding, model = embed(
                " ".join((claim_data["text"], claim_data["exposure"], claim_data["outcome"]))
            )
            embedding_models.add(model)
            values = {
                "claim_text": claim_data["text"],
                "claim_text_en": None,
                "exposure": claim_data["exposure"],
                "outcome": claim_data["outcome"],
                "effect_size": None,
                "direction": None,
                "population_summary": item["population"],
                "confidence": claim_data["confidence"],
                "topics": ["sleep", "general"],
                "tags": [claim_data["key"], *claim_data["tags"]],
                "evidence_level": item["evidence_level"],
                "embedding": embedding,
                "embedding_model": model,
            }
            if existing is None:
                db.add(Claim(literature_id=literature.id, enabled=True, **values))
                inserted_claims += 1
            else:
                for key, value in values.items():
                    setattr(existing, key, value)
                updated_claims += 1

        result: dict[str, object] = {
            "seed_id": CORE_EVIDENCE_SEED_ID,
            "manifest_sha256": _manifest_sha256(),
            "audit_job_id": audit_job.id if audit_job is not None else None,
            "manifest_count": len(CORE_EVIDENCE),
            "processed_manifest_items": len(CORE_EVIDENCE),
            "inserted_literature": inserted_literature,
            "inserted_claims": inserted_claims,
            "updated_claims": updated_claims,
            "embedding_models": sorted(embedding_models),
        }
        if audit_job is not None:
            audit_job.status = "ok"
            # Keep the project's standard audit semantics: these columns count
            # newly inserted literature records, while claim and processing
            # details remain explicit in meta.
            audit_job.inserted_count = inserted_literature
            audit_job.skipped_count = len(CORE_EVIDENCE) - inserted_literature
            audit_job.finished_at = datetime.now(timezone.utc)
            audit_job.meta = {**(audit_job.meta or {}), **result}
        db.commit()
        return result
    except Exception as exc:
        db.rollback()
        if audit_job is not None:
            persisted_job = db.get(IngestJob, audit_job.id)
            if persisted_job is not None:
                persisted_job.status = "error"
                persisted_job.error = f"{type(exc).__name__}: {exc}"[:1000]
                persisted_job.finished_at = datetime.now(timezone.utc)
                db.commit()
        raise


def _start_audit_job(db: Session) -> IngestJob:
    job = IngestJob(
        query=f"seed:{CORE_EVIDENCE_SEED_ID}",
        topic="general",
        status="running",
        fetched_count=len(CORE_EVIDENCE),
        meta={
            "seed_id": CORE_EVIDENCE_SEED_ID,
            "manifest_sha256": _manifest_sha256(),
            "reviewer": REVIEWER,
            "pmids": [item["pmid"] for item in CORE_EVIDENCE],
            "execution": "explicit_cli",
        },
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def seed_manifest() -> dict[str, object]:
    return {
        "seed_id": CORE_EVIDENCE_SEED_ID,
        "manifest_sha256": _manifest_sha256(),
        "manifest_count": len(CORE_EVIDENCE),
        "reviewer": REVIEWER,
        "pmids": [item["pmid"] for item in CORE_EVIDENCE],
        "embedding": "only executed with --apply; may use configured provider with local-hash fallback",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Preview or explicitly apply the reviewed Xjie core-evidence seed.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write the idempotent seed and an audit job to the configured database",
    )
    args = parser.parse_args(argv)

    if not args.apply:
        print(json.dumps({"mode": "preview", **seed_manifest()}, ensure_ascii=False, sort_keys=True))
        return 0

    with SessionLocal() as db:
        result = upsert_core_evidence(db)
    print(json.dumps({"mode": "applied", **result}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
