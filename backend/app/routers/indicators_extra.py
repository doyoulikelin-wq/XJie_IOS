"""User-side indicator extras: 手动录入指标值 + 知识库搜索 + 常见指标种子。

挂载在 /api/health-data 前缀下，与现有 indicators 端点共存。
"""

from __future__ import annotations

import math
import logging
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, delete, or_, select, update
from sqlalchemy.exc import IntegrityError
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


class DeviceIndicatorValueIn(BaseModel):
    indicator_name: str = Field(min_length=1, max_length=128)
    value: float
    unit: str | None = Field(default=None, max_length=32)
    measured_at: datetime
    source_metric: str | None = Field(default=None, max_length=64)
    source_id: str | None = Field(default=None, max_length=128)
    value_kind: Literal["numeric", "category"] = "numeric"
    display_value: str | None = Field(default=None, max_length=128)
    source_local_date: date | None = None
    timezone_offset_minutes: int | None = Field(default=None, ge=-840, le=840)
    notes: str | None = Field(default=None, max_length=500)


class DeviceIndicatorSyncIn(BaseModel):
    source: str = Field(default="apple_health", min_length=1, max_length=16)
    values: list[DeviceIndicatorValueIn] = Field(default_factory=list, max_length=200)


class DeviceIndicatorSyncIssue(BaseModel):
    index: int
    code: Literal[
        "invalid_indicator_name",
        "invalid_value",
        "future_measured_at",
        "source_id_conflict",
        "missing_display_value",
        "source_local_date_conflict",
    ]


class DeviceIndicatorSyncOut(BaseModel):
    total: int
    inserted: int
    updated: int
    unchanged: int
    rejected: int
    issues: list[DeviceIndicatorSyncIssue] = Field(default_factory=list)
    skipped: int


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


@router.post("/indicators/device-sync", response_model=DeviceIndicatorSyncOut)
def sync_device_indicators(
    body: DeviceIndicatorSyncIn,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """批量同步来自 Apple Health / 可穿戴设备的用户端指标。

    该接口复用 ``user_indicator_values``，因此同步后的数据会直接进入
    ``/api/health-data/indicators`` 和 ``/trend``，供用户端数据页与趋势页读取。

    - 有 ``source_id`` 时按用户 + 来源 + 样本 ID 精确幂等；跨日也不会重复。
    - 不同 ``source_id`` 始终保留为不同趋势样本。
    - 旧客户端没有 ``source_id`` 时才按其时间戳携带的本地日做兼容去重。
    - 设备同步绝不原地改写 ``manual`` 行。

    ``unchanged`` 表示服务器已有完全相同的样本，并不代表发生了更新；
    ``skipped`` 仅为旧客户端兼容字段，等于 ``unchanged + rejected``。
    """
    source = (body.source or "device").strip().lower()
    if source not in {"apple_health", "device", "cgm"}:
        raise HTTPException(status_code=400, detail="source 不支持")
    if not body.values:
        raise HTTPException(status_code=400, detail="values 不能为空")

    inserted = 0
    updated = 0
    unchanged = 0
    rejected = 0
    issues: list[DeviceIndicatorSyncIssue] = []
    now = datetime.now(timezone.utc)

    for index, item in enumerate(body.values):
        name = item.indicator_name.strip()
        if not name:
            rejected += 1
            issues.append(DeviceIndicatorSyncIssue(index=index, code="invalid_indicator_name"))
            continue
        if not math.isfinite(item.value):
            rejected += 1
            issues.append(DeviceIndicatorSyncIssue(index=index, code="invalid_value"))
            continue

        measured, day_start, day_end = _device_time_window(item.measured_at)
        if measured > now + timedelta(minutes=5):
            rejected += 1
            issues.append(DeviceIndicatorSyncIssue(index=index, code="future_measured_at"))
            continue

        source_metric = (item.source_metric or "").strip() or None
        source_id = (item.source_id or "").strip() or None
        value_kind = item.value_kind
        display_value = (item.display_value or "").strip() or None
        if value_kind == "category" and not display_value:
            rejected += 1
            issues.append(DeviceIndicatorSyncIssue(index=index, code="missing_display_value"))
            continue
        inferred_local_date = _daily_source_local_date(source_metric, source_id)
        if (
            item.source_local_date is not None
            and inferred_local_date is not None
            and item.source_local_date != inferred_local_date
        ):
            rejected += 1
            issues.append(
                DeviceIndicatorSyncIssue(index=index, code="source_local_date_conflict")
            )
            continue
        source_local_date = item.source_local_date or inferred_local_date
        timezone_offset_minutes = item.timezone_offset_minutes
        notes = (item.notes or "").strip() or None
        unit = (item.unit or "").strip() or None
        value = float(item.value)

        if source_id:
            existing = _find_source_sample(db, user_id, source, source_id)
            if existing is None:
                existing = _adopt_legacy_source_identity(
                    db,
                    user_id=user_id,
                    source=source,
                    indicator_name=name,
                    source_metric=source_metric,
                    measured_at=measured,
                    source_id=source_id,
                )
        else:
            # Legacy compatibility only: never select a first-class source sample or a
            # manual row, even if it shares the same metric and calendar date.
            legacy_day_clause = and_(
                UserIndicatorValue.measured_at >= day_start,
                UserIndicatorValue.measured_at < day_end,
            )
            if source_local_date is not None:
                legacy_day_clause = or_(
                    UserIndicatorValue.source_local_date == source_local_date,
                    and_(
                        UserIndicatorValue.source_local_date.is_(None),
                        legacy_day_clause,
                    ),
                )
            existing = db.execute(
                select(UserIndicatorValue)
                .where(
                    UserIndicatorValue.user_id == user_id,
                    UserIndicatorValue.indicator_name == name,
                    UserIndicatorValue.source == source,
                    UserIndicatorValue.source_id.is_(None),
                    legacy_day_clause,
                )
                .order_by(UserIndicatorValue.measured_at.desc(), UserIndicatorValue.id.desc())
            ).scalars().first()

        if existing:
            if source_id and _source_identity_conflicts(
                existing,
                name=name,
                source_metric=source_metric,
            ):
                rejected += 1
                issues.append(DeviceIndicatorSyncIssue(index=index, code="source_id_conflict"))
                continue
            if source_id and _is_uuid_source_id(source_metric, source_id):
                _delete_legacy_identity_duplicate(
                    db,
                    user_id=user_id,
                    source=source,
                    source_metric=source_metric,
                    measured_at=measured,
                    exact_row_id=existing.id,
                )
            if _update_device_row(
                existing,
                value=value,
                unit=unit,
                measured_at=measured,
                notes=notes,
                source_metric=source_metric,
                value_kind=value_kind,
                display_value=display_value,
                source_local_date=source_local_date,
                timezone_offset_minutes=timezone_offset_minutes,
                updated_at=datetime.now(timezone.utc),
            ):
                updated += 1
            else:
                unchanged += 1
            continue

        row = UserIndicatorValue(
            user_id=user_id,
            indicator_name=name,
            value=value,
            unit=unit,
            measured_at=measured,
            notes=notes,
            source=source,
            source_metric=source_metric,
            source_id=source_id,
            value_kind=value_kind,
            display_value=display_value,
            source_local_date=source_local_date,
            timezone_offset_minutes=timezone_offset_minutes,
        )
        if source_id:
            try:
                # The partial unique index is the concurrency authority. A savepoint
                # turns a racing insert into an idempotent update/unchanged result.
                with db.begin_nested():
                    db.add(row)
                    db.flush()
                inserted += 1
                if _is_uuid_source_id(source_metric, source_id):
                    _delete_legacy_identity_duplicate(
                        db,
                        user_id=user_id,
                        source=source,
                        source_metric=source_metric,
                        measured_at=measured,
                        exact_row_id=row.id,
                    )
            except IntegrityError:
                existing = _find_source_sample(db, user_id, source, source_id)
                if existing is None:
                    raise
                if _source_identity_conflicts(existing, name=name, source_metric=source_metric):
                    rejected += 1
                    issues.append(DeviceIndicatorSyncIssue(index=index, code="source_id_conflict"))
                else:
                    if _is_uuid_source_id(source_metric, source_id):
                        _delete_legacy_identity_duplicate(
                            db,
                            user_id=user_id,
                            source=source,
                            source_metric=source_metric,
                            measured_at=measured,
                            exact_row_id=existing.id,
                        )
                    changed = _update_device_row(
                        existing,
                        value=value,
                        unit=unit,
                        measured_at=measured,
                        notes=notes,
                        source_metric=source_metric,
                        value_kind=value_kind,
                        display_value=display_value,
                        source_local_date=source_local_date,
                        timezone_offset_minutes=timezone_offset_minutes,
                        updated_at=datetime.now(timezone.utc),
                    )
                    if changed:
                        updated += 1
                    else:
                        unchanged += 1
        else:
            db.add(row)
            inserted += 1

    skipped = unchanged + rejected
    if rejected == len(body.values):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "all_values_rejected",
                "message": "没有可写入的设备健康样本，请检查样本时间或数据格式。",
                "total": len(body.values),
                "inserted": 0,
                "updated": 0,
                "unchanged": 0,
                "rejected": rejected,
                "skipped": skipped,
                "issues": [issue.model_dump() for issue in issues],
            },
        )

    db.commit()
    logger.info(
        "Device indicator sync: user=%s source=%s total=%s inserted=%s updated=%s "
        "unchanged=%s rejected=%s",
        user_id, source, len(body.values), inserted, updated, unchanged, rejected,
    )
    return DeviceIndicatorSyncOut(
        total=len(body.values),
        inserted=inserted,
        updated=updated,
        unchanged=unchanged,
        rejected=rejected,
        issues=issues,
        skipped=skipped,
    )


def _device_time_window(measured_at: datetime) -> tuple[datetime, datetime, datetime]:
    """Return UTC sample time plus the UTC bounds of its encoded local calendar day."""
    local = measured_at if measured_at.tzinfo is not None else measured_at.replace(tzinfo=timezone.utc)
    local_day_start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    local_day_end = local_day_start + timedelta(days=1)
    return (
        local.astimezone(timezone.utc),
        local_day_start.astimezone(timezone.utc),
        local_day_end.astimezone(timezone.utc),
    )


def _daily_source_local_date(
    source_metric: str | None,
    source_id: str | None,
) -> date | None:
    if not source_metric or not source_id:
        return None
    match = re.fullmatch(rf"{re.escape(source_metric)}-(\d{{8}})", source_id)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y%m%d").date()
    except ValueError:
        return None


def _is_uuid_source_id(source_metric: str | None, source_id: str) -> bool:
    if not source_metric or not source_id.startswith(f"{source_metric}-"):
        return False
    suffix = source_id.removeprefix(f"{source_metric}-")
    try:
        UUID(suffix)
    except ValueError:
        return False
    return True


def _adopt_legacy_source_identity(
    db: Session,
    *,
    user_id: int,
    source: str,
    indicator_name: str,
    source_metric: str | None,
    measured_at: datetime,
    source_id: str,
) -> UserIndicatorValue | None:
    """Atomically replace a 1.0(15) timestamp identity with its UUID identity."""
    if not _is_uuid_source_id(source_metric, source_id):
        return None
    legacy_source_id = f"{source_metric}-{int(measured_at.timestamp())}"
    candidates = db.execute(
        select(UserIndicatorValue).where(
            UserIndicatorValue.user_id == user_id,
            UserIndicatorValue.source == source,
            UserIndicatorValue.source_metric == source_metric,
            UserIndicatorValue.measured_at == measured_at,
            UserIndicatorValue.source_id == legacy_source_id,
        )
    ).scalars().all()
    if len(candidates) != 1:
        return None

    candidate = candidates[0]
    candidate_id = candidate.id
    candidate_updated_at = candidate.updated_at
    try:
        with db.begin_nested():
            adopted_id = db.execute(
                update(UserIndicatorValue)
                .where(
                    UserIndicatorValue.id == candidate_id,
                    UserIndicatorValue.source_id == legacy_source_id,
                )
                .values(
                    source_id=source_id,
                    indicator_name=indicator_name,
                    # Identity rollout is not a health-content update.
                    updated_at=candidate_updated_at,
                )
                .returning(UserIndicatorValue.id)
            ).scalar_one_or_none()
    except IntegrityError:
        adopted_id = None

    db.expire_all()
    if adopted_id is not None:
        return _find_source_sample(db, user_id, source, source_id)
    # A concurrent request may have adopted the UUID or inserted its new row
    # before this compare-and-swap. If it inserted, remove the now-redundant
    # timestamp-identity row before returning the UUID row.
    exact = _find_source_sample(db, user_id, source, source_id)
    if (
        exact is not None
        and exact.indicator_name == indicator_name
        and exact.source_metric == source_metric
        and _utc_timestamp(exact.measured_at) == measured_at
    ):
        db.execute(
            delete(UserIndicatorValue).where(
                UserIndicatorValue.id == candidate_id,
                UserIndicatorValue.source_id == legacy_source_id,
            )
        )
        db.flush()
    return exact


def _delete_legacy_identity_duplicate(
    db: Session,
    *,
    user_id: int,
    source: str,
    source_metric: str | None,
    measured_at: datetime,
    exact_row_id: int,
) -> None:
    if not source_metric:
        return
    legacy_source_id = f"{source_metric}-{int(measured_at.timestamp())}"
    db.execute(
        delete(UserIndicatorValue).where(
            UserIndicatorValue.user_id == user_id,
            UserIndicatorValue.source == source,
            UserIndicatorValue.source_metric == source_metric,
            UserIndicatorValue.measured_at == measured_at,
            UserIndicatorValue.source_id == legacy_source_id,
            UserIndicatorValue.id != exact_row_id,
        )
    )


def _find_source_sample(
    db: Session,
    user_id: int,
    source: str,
    source_id: str,
) -> UserIndicatorValue | None:
    return db.execute(
        select(UserIndicatorValue).where(
            UserIndicatorValue.user_id == user_id,
            UserIndicatorValue.source == source,
            UserIndicatorValue.source_id == source_id,
        )
    ).scalars().first()


def _source_identity_conflicts(
    row: UserIndicatorValue,
    *,
    name: str,
    source_metric: str | None,
) -> bool:
    return row.indicator_name != name or bool(
        row.source_metric and source_metric and row.source_metric != source_metric
    )


def _utc_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _update_device_row(
    row: UserIndicatorValue,
    *,
    value: float,
    unit: str | None,
    measured_at: datetime,
    notes: str | None,
    source_metric: str | None,
    value_kind: Literal["numeric", "category"],
    display_value: str | None,
    source_local_date: date | None,
    timezone_offset_minutes: int | None,
    updated_at: datetime,
) -> bool:
    effective_source_metric = source_metric or row.source_metric
    content_changed = (
        row.value != value
        or row.unit != unit
        or row.notes != notes
        or row.source_metric != effective_source_metric
        or row.value_kind != value_kind
        or row.display_value != display_value
        or row.source_local_date != source_local_date
        or row.timezone_offset_minutes != timezone_offset_minutes
    )
    measured_at_changed = _utc_timestamp(row.measured_at) != measured_at
    is_daily_cumulative = _daily_source_local_date(
        effective_source_metric,
        row.source_id,
    ) is not None
    if not content_changed and (not measured_at_changed or is_daily_cumulative):
        return False
    row.value = value
    row.unit = unit
    row.measured_at = measured_at
    row.notes = notes
    row.source_metric = effective_source_metric
    row.value_kind = value_kind
    row.display_value = display_value
    row.source_local_date = source_local_date
    row.timezone_offset_minutes = timezone_offset_minutes
    row.updated_at = updated_at
    return True


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
