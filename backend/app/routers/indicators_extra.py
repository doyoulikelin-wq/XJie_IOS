"""User-side indicator extras: 手动录入指标值 + 知识库搜索 + 常见指标种子。

挂载在 /api/health-data 前缀下，与现有 indicators 端点共存。
"""

from __future__ import annotations

import logging
import re
import unicodedata
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user_id, get_db
from app.models.health_document import IndicatorKnowledge
from app.models.user_indicator_value import UserIndicatorValue

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Schemas ──────────────────────────────────────────────────


class IndicatorSearchItem(BaseModel):
    name: str
    alias: str | None = None
    category: str | None = None
    brief: str | None = None
    normal_range: str | None = None
    unit: str | None = None
    score: float = 0.0


class IndicatorSearchOut(BaseModel):
    items: list[IndicatorSearchItem]


class ManualIndicatorIn(BaseModel):
    indicator_name: str = Field(min_length=1, max_length=128)
    value: float
    unit: str | None = Field(default=None, max_length=32)
    measured_at: datetime
    notes: str | None = Field(default=None, max_length=500)


class ManualIndicatorOut(BaseModel):
    id: int
    indicator_name: str
    value: float
    unit: str | None = None
    measured_at: datetime
    notes: str | None = None
    source: str = "manual"


class ManualIndicatorListOut(BaseModel):
    items: list[ManualIndicatorOut]


# ── Search helpers ───────────────────────────────────────────


def _normalize(s: str) -> str:
    """全/半角统一、去空格、转小写、NFKC。"""
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    return re.sub(r"\s+", "", s).lower()


def _score(query: str, name: str, alias: str | None) -> float:
    """简单模糊评分（中英文 + 别名 + 子串 + 字符交集）。"""
    q = _normalize(query)
    n = _normalize(name)
    a = _normalize(alias or "")
    if not q:
        return 0.0
    score = 0.0
    if q == n:
        score += 100.0
    elif n.startswith(q):
        score += 60.0
    elif q in n:
        score += 40.0
    # 别名命中
    if a:
        for token in re.split(r"[,，;；/\s]+", a):
            tn = _normalize(token)
            if not tn:
                continue
            if q == tn:
                score += 80.0
            elif tn.startswith(q):
                score += 50.0
            elif q in tn:
                score += 30.0
    # 字符交集（容错）
    if score < 30 and q:
        common = len(set(q) & set(n + a))
        if common >= max(2, len(q) // 2):
            score += common * 4.0
    return score


# ── Routes ───────────────────────────────────────────────────


@router.get("/indicators/search", response_model=IndicatorSearchOut)
def search_indicators(
    q: str = Query(..., min_length=1, max_length=64, description="关键词，中英文/别名/拼音/子串"),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """搜索指标知识库。

    支持中英文、别名（如 "ALT" 命中"谷丙转氨酶"），并对错别字做字符交集兜底。
    """
    qn = _normalize(q)
    if not qn:
        return IndicatorSearchOut(items=[])

    # 先做粗过滤再 Python 端打分（指标库行数有限，性能足够）。
    like = f"%{qn}%"
    candidates = db.execute(
        select(IndicatorKnowledge).where(
            or_(
                IndicatorKnowledge.name.ilike(like),
                IndicatorKnowledge.alias.ilike(like),
                # 关键词长度足够时，回退全表打分
                IndicatorKnowledge.name.isnot(None),
            )
        )
    ).scalars().all()

    scored: list[tuple[float, IndicatorKnowledge]] = []
    for ind in candidates:
        s = _score(q, ind.name, ind.alias)
        if s > 0:
            scored.append((s, ind))
    scored.sort(key=lambda x: -x[0])
    items = [
        IndicatorSearchItem(
            name=ind.name,
            alias=ind.alias,
            category=ind.category,
            brief=ind.brief or None,
            normal_range=ind.normal_range,
            unit=_extract_unit_from_range(ind.normal_range),
            score=round(s, 2),
        )
        for s, ind in scored[:limit]
    ]
    return IndicatorSearchOut(items=items)


def _extract_unit_from_range(rng: str | None) -> str | None:
    """从 "0-40 U/L" 之类抽出单位。"""
    if not rng:
        return None
    m = re.search(r"[A-Za-zμ%/\^\d.]+\s*$", rng.strip())
    if m:
        token = m.group(0).strip()
        # 去掉前面的纯数字/范围
        token = re.sub(r"^[-~–\d.]+", "", token).strip()
        if 1 <= len(token) <= 16 and any(c.isalpha() or c in "%μ" for c in token):
            return token
    return None


# ── Manual indicator values ──────────────────────────────────


@router.get("/indicators/manual", response_model=ManualIndicatorListOut)
def list_manual_indicators(
    indicator_name: str | None = Query(default=None, max_length=128),
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    q = select(UserIndicatorValue).where(UserIndicatorValue.user_id == user_id)
    if indicator_name:
        q = q.where(UserIndicatorValue.indicator_name == indicator_name)
    q = q.order_by(UserIndicatorValue.measured_at.desc())
    rows = db.execute(q).scalars().all()
    return ManualIndicatorListOut(items=[
        ManualIndicatorOut(
            id=r.id,
            indicator_name=r.indicator_name,
            value=r.value,
            unit=r.unit,
            measured_at=r.measured_at,
            notes=r.notes,
            source=r.source,
        ) for r in rows
    ])


@router.post("/indicators/manual", response_model=ManualIndicatorOut)
def create_manual_indicator(
    body: ManualIndicatorIn,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """手动录入一个指标数值。

    - 不强制要求 indicator_name 在知识库中存在（自由文本兜底）
    - 录入后会出现在 /api/health-data/indicators/trend 的趋势中
    """
    name = body.indicator_name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="indicator_name 不能为空")
    if body.value != body.value or body.value in (float("inf"), float("-inf")):
        raise HTTPException(status_code=400, detail="value 必须是有限数值")
    measured = body.measured_at
    if measured.tzinfo is None:
        measured = measured.replace(tzinfo=timezone.utc)
    if measured > datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="测量时间不能在未来")

    row = UserIndicatorValue(
        user_id=user_id,
        indicator_name=name,
        value=body.value,
        unit=(body.unit or None),
        measured_at=measured,
        notes=(body.notes or None),
        source="manual",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    logger.info("Manual indicator added: user=%s name=%s value=%s", user_id, name, body.value)
    return ManualIndicatorOut(
        id=row.id, indicator_name=row.indicator_name, value=row.value,
        unit=row.unit, measured_at=row.measured_at, notes=row.notes, source=row.source,
    )


@router.delete("/indicators/manual/{value_id}")
def delete_manual_indicator(
    value_id: int,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    row = db.execute(
        select(UserIndicatorValue).where(
            UserIndicatorValue.id == value_id,
            UserIndicatorValue.user_id == user_id,
        )
    ).scalars().first()
    if not row:
        raise HTTPException(status_code=404, detail="记录不存在")
    db.delete(row)
    db.commit()
    return {"ok": True}


# ── Seed common indicators (idempotent) ──────────────────────


_COMMON_INDICATORS: list[dict] = [
    # 血常规
    {"name": "白细胞", "alias": "WBC,白细胞计数", "category": "血常规",
     "brief": "反映机体免疫状态和感染情况", "normal_range": "4-10 ×10^9/L",
     "clinical_meaning": "升高常见于感染、白血病；降低见于病毒感染或免疫抑制。"},
    {"name": "红细胞", "alias": "RBC,红细胞计数", "category": "血常规",
     "brief": "携带氧气的主要细胞", "normal_range": "3.5-5.5 ×10^12/L",
     "clinical_meaning": "降低提示贫血；升高见于脱水、慢性缺氧。"},
    {"name": "血红蛋白", "alias": "HGB,Hb,血色素", "category": "血常规",
     "brief": "红细胞内运送氧气的蛋白", "normal_range": "110-160 g/L",
     "clinical_meaning": "降低 = 贫血；男性<120、女性<110 需关注。"},
    {"name": "血小板", "alias": "PLT,血小板计数", "category": "血常规",
     "brief": "参与凝血", "normal_range": "100-300 ×10^9/L",
     "clinical_meaning": "降低易出血；升高与炎症/血栓风险相关。"},
    # 肝功能
    {"name": "谷丙转氨酶", "alias": "ALT,GPT,丙氨酸氨基转移酶", "category": "肝功能",
     "brief": "反映肝细胞损伤", "normal_range": "0-40 U/L",
     "clinical_meaning": "升高见于肝炎、脂肪肝、药物性肝损。"},
    {"name": "谷草转氨酶", "alias": "AST,GOT,天冬氨酸氨基转移酶", "category": "肝功能",
     "brief": "肝细胞和心肌都含有", "normal_range": "0-40 U/L",
     "clinical_meaning": "升高见于肝炎、心肌炎、肌肉损伤。"},
    {"name": "总胆红素", "alias": "TBIL,T-BIL", "category": "肝功能",
     "brief": "胆红素总量，反映肝胆代谢", "normal_range": "3.4-20.5 μmol/L",
     "clinical_meaning": "升高见于黄疸、溶血、肝胆疾病。"},
    {"name": "白蛋白", "alias": "ALB,Albumin", "category": "肝功能",
     "brief": "肝脏合成的主要血浆蛋白", "normal_range": "35-55 g/L",
     "clinical_meaning": "降低见于慢性肝病、营养不良、肾病。"},
    {"name": "γ-谷氨酰转肽酶", "alias": "GGT,γ-GT,谷氨酰转肽酶", "category": "肝功能",
     "brief": "胆道损伤敏感指标", "normal_range": "0-50 U/L",
     "clinical_meaning": "升高见于胆道梗阻、酒精性肝病。"},
    # 肾功能
    {"name": "肌酐", "alias": "Cr,Crea,血肌酐", "category": "肾功能",
     "brief": "评估肾小球滤过", "normal_range": "53-106 μmol/L",
     "clinical_meaning": "升高提示肾功能下降。"},
    {"name": "尿素氮", "alias": "BUN,Urea", "category": "肾功能",
     "brief": "蛋白质代谢产物", "normal_range": "2.9-8.2 mmol/L",
     "clinical_meaning": "升高见于肾功能不全、脱水。"},
    {"name": "尿酸", "alias": "UA,Uric Acid", "category": "肾功能",
     "brief": "嘌呤代谢终产物", "normal_range": "208-428 μmol/L",
     "clinical_meaning": "升高与痛风、高嘌呤饮食相关。"},
    # 血脂
    {"name": "总胆固醇", "alias": "TC,TCHO,Cholesterol", "category": "血脂",
     "brief": "血脂总水平", "normal_range": "<5.18 mmol/L",
     "clinical_meaning": "升高增加心血管风险。"},
    {"name": "甘油三酯", "alias": "TG,Triglyceride", "category": "血脂",
     "brief": "中性脂肪", "normal_range": "<1.7 mmol/L",
     "clinical_meaning": "升高与脂肪肝、糖尿病、心血管疾病相关。"},
    {"name": "高密度脂蛋白", "alias": "HDL,HDL-C", "category": "血脂",
     "brief": "好胆固醇", "normal_range": ">1.04 mmol/L",
     "clinical_meaning": "升高有心血管保护作用。"},
    {"name": "低密度脂蛋白", "alias": "LDL,LDL-C", "category": "血脂",
     "brief": "坏胆固醇", "normal_range": "<3.37 mmol/L",
     "clinical_meaning": "升高显著增加动脉粥样硬化风险。"},
    # 血糖
    {"name": "空腹血糖", "alias": "FBG,GLU,葡萄糖", "category": "血糖",
     "brief": "空腹状态血糖水平", "normal_range": "3.9-6.1 mmol/L",
     "clinical_meaning": "≥7.0 提示糖尿病；6.1-7.0 为空腹血糖受损。"},
    {"name": "糖化血红蛋白", "alias": "HbA1c,A1C,糖化", "category": "血糖",
     "brief": "近3个月平均血糖", "normal_range": "4-6%",
     "clinical_meaning": "≥6.5% 提示糖尿病；糖尿病控制目标通常 <7%。"},
    {"name": "餐后2小时血糖", "alias": "2hPG,餐后血糖", "category": "血糖",
     "brief": "口服葡萄糖耐量试验后2小时血糖", "normal_range": "<7.8 mmol/L",
     "clinical_meaning": "≥11.1 提示糖尿病；7.8-11.1 为糖耐量异常。"},
    # 甲状腺
    {"name": "促甲状腺激素", "alias": "TSH", "category": "甲状腺",
     "brief": "垂体分泌，调节甲状腺", "normal_range": "0.27-4.2 mIU/L",
     "clinical_meaning": "升高提示甲减；降低提示甲亢。"},
    {"name": "游离T3", "alias": "FT3,游离三碘甲腺原氨酸", "category": "甲状腺",
     "brief": "活性甲状腺激素", "normal_range": "3.1-6.8 pmol/L",
     "clinical_meaning": "升高见于甲亢；降低见于甲减、严重疾病。"},
    {"name": "游离T4", "alias": "FT4,游离甲状腺素", "category": "甲状腺",
     "brief": "甲状腺激素前体", "normal_range": "12-22 pmol/L",
     "clinical_meaning": "升高见于甲亢；降低见于甲减。"},
    # 体格
    {"name": "收缩压", "alias": "SBP,高压", "category": "体格",
     "brief": "心脏收缩时血管压力", "normal_range": "90-139 mmHg",
     "clinical_meaning": "≥140 为高血压；<90 为低血压。"},
    {"name": "舒张压", "alias": "DBP,低压", "category": "体格",
     "brief": "心脏舒张时血管压力", "normal_range": "60-89 mmHg",
     "clinical_meaning": "≥90 为高血压；<60 为低血压。"},
    {"name": "心率", "alias": "HR,Pulse,脉搏", "category": "体格",
     "brief": "每分钟心跳次数", "normal_range": "60-100 次/分",
     "clinical_meaning": "<60 为窦缓；>100 为窦速。"},
    {"name": "BMI", "alias": "Body Mass Index,体质指数", "category": "体格",
     "brief": "体重(kg)/身高²(m²)", "normal_range": "18.5-23.9",
     "clinical_meaning": "≥24 超重；≥28 肥胖。"},
    {"name": "腰围", "alias": "Waist,WC", "category": "体格",
     "brief": "经脐水平腰围", "normal_range": "男<85 女<80 cm",
     "clinical_meaning": "中心性肥胖与代谢综合征相关。"},
]


@router.post("/indicators/seed-common", include_in_schema=False)
def seed_common_indicators(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """幂等：把常见指标写入 IndicatorKnowledge（如已存在则跳过）。

    任何登录用户都可触发（首次安装时 App 自动调用）。
    """
    added = 0
    for item in _COMMON_INDICATORS:
        existing = db.execute(
            select(IndicatorKnowledge).where(IndicatorKnowledge.name == item["name"])
        ).scalars().first()
        if existing:
            # 补充别名/分类
            updated = False
            if not existing.alias and item.get("alias"):
                existing.alias = item["alias"]
                updated = True
            if not existing.category and item.get("category"):
                existing.category = item["category"]
                updated = True
            if updated:
                db.commit()
            continue
        db.add(IndicatorKnowledge(
            name=item["name"],
            alias=item.get("alias"),
            category=item.get("category"),
            brief=item.get("brief", ""),
            detail="",
            normal_range=item.get("normal_range"),
            clinical_meaning=item.get("clinical_meaning"),
            source="seed",
        ))
        added += 1
    db.commit()
    logger.info("Seeded %d common indicators (triggered by user=%s)", added, user_id)
    return {"ok": True, "added": added, "total_seed": len(_COMMON_INDICATORS)}
