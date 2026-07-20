# Beijing Daily Diet Summary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate and expose an AI-assisted summary of the authenticated user's previous Beijing-calendar-day confirmed dietary records at 04:00 Asia/Shanghai, with a durable rule fallback and bounded automatic retries.

**Architecture:** A dedicated provider method returns a strictly validated nutrition-balance result. A Beijing-time Celery task discovers only users with confirmed records for the target date, commits a version-bound rule fallback before the model call, invokes the provider outside the database transaction, and conditionally writes the AI result. A separate sweep retries fallback summaries using retry metadata stored in the existing `DietaryDailySummary.evidence` JSONB.

**Tech Stack:** Python 3, FastAPI, Pydantic, SQLAlchemy, PostgreSQL JSONB, Celery Beat/Redis, pytest, OpenAI-compatible Chat Completions.

## Global Constraints

- The schedule is exactly `Asia/Shanghai` daily at `04:00`; the target date is the previous Beijing calendar date.
- Only non-deleted, confirmed `DietaryRecord` rows participate. Legacy `Meal`, drafts, pending confirmations, and deleted records never create a candidate.
- A single confirmed meal still creates a summary, but the output must state that the record is insufficient to represent the full day.
- Persist the rule fallback before calling the model. Never hold a database transaction or row lock across the model call.
- Retry delays are exactly 5 minutes, 15 minutes, 1 hour, 3 hours, and 6 hours; after five failed retry attempts the fallback becomes exhausted.
- The read API is `GET /api/dietary-records/daily-summary`, accepts no date/timezone/subject override, and is tenant-scoped to the authenticated user.
- The two required empty-state messages are exact: `还没有记录过饮食呢，快记录你的第一餐吧` and `昨天忘记记录饮食啦`.
- Do not add a database table, column, Alembic revision, dependency, iOS change, notification, or push behavior.
- Preserve the user's existing uncommitted edits in `backend/app/providers/openai_provider.py` and `backend/app/routers/meals.py`; stage only intentional files for each commit.
- Update `quality/change_impact.json` before behavior edits. Add meaningful named regression assertions before production code.
- During editing run `/usr/bin/python3 -I tools/run_regression_gate.py fast`. After the implementation is stable, run `/usr/bin/python3 -I tools/run_regression_gate.py impacted` exactly once before PR delivery.

---

### Task 1: Register the Real Change Impact Before Behavior Edits

**Files:**
- Modify: `quality/change_impact.json`

**Interfaces:**
- Consumes: behavior-domain and invariant mappings from `quality/regression_contracts.json`.
- Produces: a complete change-impact declaration used by every subsequent gate.

- [ ] **Step 1: Replace the previous release-only impact declaration**

Set the identity and scope fields to:

```json
{
  "schema_version": 1,
  "change_id": "2026-07-21-beijing-daily-diet-summary",
  "change_type": "feature",
  "current_scope": "后端仅为北京时间前一天存在已确认 DietaryRecord 的用户，在每日 04:00 生成规则保底与 AI 饮食总结，并提供本人读取接口；不读取旧 meals、草稿、其他健康数据，不修改数据库结构、iOS、推送或生产部署。",
  "current_root_cause": "现有 dietary-day completion 按每条记录时区轮询关闭，并明确使用固定模板且不调用 LLM；现有 dashboard 只暴露可空 summary，无法区分从未记录、昨日漏记和仍在生成。",
  "current_risk_hypothesis": "若候选查询、模型输入、写回版本或接口状态没有同时绑定 user_id、subject_user_id、北京时间目标日期和 record_version，任务可能跨用户泄露、为无昨日数据用户调用模型、用旧响应覆盖新记录，或把模型故障误报为无记录。",
  "summary": "新增北京时间 04:00 的确认饮食总结、规则降级、有限退避重试和三态空结果接口。",
  "root_cause": "现有每日总结只有按记录时区触发的固定规则路径，没有后台专用模型契约、持久化降级重试状态或精确空状态接口。",
  "risk_hypothesis": "后台 AI 调用必须在短事务之外进行，规则保底必须先提交，模型写回必须按记录版本和输入指纹比较后更新。",
  "impacted_domains": [
    "backend_core",
    "backend_chat_ai",
    "backend_health_sync",
    "test_suite_integrity"
  ],
  "regression_contracts": [
    "AI-EVIDENCE-001",
    "AI-SAFETY-001",
    "AI-SUBJECT-001",
    "BACKEND-CORE-001",
    "CHAT-SESSION-001",
    "HEALTH-ACCOUNT-001",
    "HEALTH-REGISTRY-001",
    "HEALTH-TRUST-001",
    "MEDICATION-TRUST-001",
    "TEST-SUITE-INTEGRITY-001"
  ]
}
```

Retain the schema-required arrays and fill them with these concrete entries:

```json
{
  "same_class_scan": [
    "扫描 DietaryRecord、DietaryDay、DietaryDailySummary、dashboard、manual complete、stale recalculation、Celery Beat、provider factory、MockProvider 与 OpenAIProvider；确认旧 meals 与未确认 draft 是相邻但禁止进入的新路径。",
    "确认现有唯一约束 uq_dietary_summary_tenant_date_version 可承担版本幂等，无需数据库迁移。",
    "确认模型调用必须与数据库锁分离，并且旧模型结果必须由 record_version 与 model_input_fingerprint 双重拒绝。"
  ],
  "tests_added_or_updated": [
    "backend/tests/unit/test_dietary_records_contract.py",
    "backend/tests/unit/test_openai_provider_parsing.py",
    "quality/expected_python_tests.json",
    "tools/tests/test_python_test_gate.py",
    "tools/tests/test_run_regression_gate.py"
  ],
  "verification_plan": [
    "先运行新增 provider、定时汇总/重试和 daily-summary API 命名测试，确认旧代码按预期失败。",
    "实现后运行相同聚焦测试、backend_ai、backend_health、backend full 精确清单、fast，并在稳定树只运行一次 impacted。",
    "更新 backend 精确测试 ID 与数量常量，不删除、skip、重命名未登记测试。"
  ],
  "manual_checks": [
    "核对模型输入不含图片、草稿、聊天历史、其他健康数据或其他用户记录。",
    "核对凌晨 04:00 任务只选择北京时间昨天至少一条已确认记录的用户。",
    "核对两条空状态中文文案逐字一致。"
  ],
  "unresolved_risks": [
    "规则版和模型版均依赖用户确认记录的完整性；单餐不能证明全天真实摄入。",
    "evidence JSONB 证明状态与字节一致性，但不能证明模型建议在临床上适合所有个体。",
    "五次重试耗尽后保留规则总结，需要后续用户记录变更或运维干预才会产生新模型尝试。"
  ]
}
```

- [ ] **Step 2: Validate JSON and inspect the exact diff**

Run:

```bash
/usr/bin/python3 -I -m json.tool quality/change_impact.json >/dev/null
git diff --check -- quality/change_impact.json
git diff -- quality/change_impact.json
```

Expected: JSON parsing succeeds, whitespace check emits nothing, and only the intended impact declaration changes.

- [ ] **Step 3: Commit the impact declaration alone**

```bash
git add quality/change_impact.json
git commit -m "chore: register daily diet summary impact"
```

---

### Task 2: Add the Dedicated Provider Contract With TDD

**Files:**
- Modify: `backend/app/providers/base.py`
- Modify: `backend/app/providers/mock_provider.py`
- Modify: `backend/app/providers/openai_provider.py`
- Modify: `backend/tests/unit/test_openai_provider_parsing.py`

**Interfaces:**
- Consumes: normalized `dict[str, Any]` containing `diet_date`, `confirmed_meal_count`, and ordered `meals`.
- Produces: `LLMProvider.summarize_daily_diet(payload: dict[str, Any]) -> DailyDietSummaryResult`.

- [ ] **Step 1: Write the failing OpenAI-provider regression test**

Append this named test to `backend/tests/unit/test_openai_provider_parsing.py`:

```python
def test_daily_diet_summary_provider_uses_minimal_strict_payload_and_rejects_invalid_output() -> None:
    valid = json.dumps(
        {
            "balance_assessment": "insufficient_data",
            "conclusion": "昨天只确认了一餐，记录有限，无法代表全天。",
            "today_suggestion": "今天午餐增加一份深色蔬菜，并继续记录其他餐次。",
            "confidence": 0.78,
        },
        ensure_ascii=False,
    )
    completions = _FakeCompletions([_fake_response(valid, finish_reason="stop")])
    provider = OpenAIProvider.__new__(OpenAIProvider)
    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    result = provider.summarize_daily_diet(
        {
            "diet_date": "2026-07-20",
            "confirmed_meal_count": 1,
            "meals": [
                {
                    "meal_type": "lunch",
                    "food_items": [{"name": "米饭", "portion_text": "一碗"}],
                    "structure": {"staple": "present"},
                    "estimated_nutrition": {"energy_kcal_range": [200, 400]},
                    "confidence": 0.8,
                }
            ],
        }
    )

    assert result.balance_assessment == "insufficient_data"
    assert result.today_suggestion == "今天午餐增加一份深色蔬菜，并继续记录其他餐次。"
    assert len(completions.calls) == 1
    call = completions.calls[0]
    assert call["extra_body"] == {"thinking": {"type": "disabled"}}
    serialized_messages = json.dumps(call["messages"], ensure_ascii=False)
    assert "聊天历史" not in serialized_messages
    assert "原始图片" not in serialized_messages
    assert "单餐" in serialized_messages

    invalid = _FakeCompletions([
        _fake_response('{"balance_assessment":"certain","conclusion":"完整全天都均衡"}', finish_reason="stop")
    ])
    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=invalid))
    with pytest.raises(ValueError, match="daily diet summary"):
        provider.summarize_daily_diet({"diet_date": "2026-07-20", "confirmed_meal_count": 1, "meals": []})
```

Also add `import pytest`. The provider test receives the typed result from the method and does not need to construct `DailyDietSummaryResult` directly.

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
backend/.venv/bin/python -I -m pytest backend/tests/unit/test_openai_provider_parsing.py::test_daily_diet_summary_provider_uses_minimal_strict_payload_and_rejects_invalid_output -q
```

Expected: FAIL with `AttributeError: 'OpenAIProvider' object has no attribute 'summarize_daily_diet'`.

- [ ] **Step 3: Add the strict result type and abstract provider method**

In `backend/app/providers/base.py`, import `ConfigDict` and add:

```python
class DailyDietSummaryResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    balance_assessment: Literal["balanced", "imbalanced", "insufficient_data"]
    conclusion: str = Field(min_length=1, max_length=240)
    today_suggestion: str = Field(min_length=1, max_length=240)
    confidence: float = Field(ge=0, le=1)
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
```

Add to `LLMProvider`:

```python
    @abstractmethod
    def summarize_daily_diet(self, payload: dict[str, Any]) -> DailyDietSummaryResult:
        raise NotImplementedError
```

- [ ] **Step 4: Implement deterministic MockProvider behavior**

In `backend/app/providers/mock_provider.py`, import `DailyDietSummaryResult` and add:

```python
    def summarize_daily_diet(self, payload: dict) -> DailyDietSummaryResult:
        meal_count = int(payload.get("confirmed_meal_count") or 0)
        if meal_count <= 1:
            return DailyDietSummaryResult(
                balance_assessment="insufficient_data",
                conclusion="昨天只确认了 1 餐，记录有限，无法完整代表全天饮食。",
                today_suggestion="今天继续记录各餐，并尽量包含主食、蛋白质和蔬菜。",
                confidence=0.45,
            )
        return DailyDietSummaryResult(
            balance_assessment="balanced",
            conclusion="昨天已确认餐食的主食、蛋白质和蔬菜结构较完整。",
            today_suggestion="今天继续保持多样化搭配并按实际份量记录。",
            confidence=0.72,
        )
```

- [ ] **Step 5: Implement strict OpenAIProvider generation**

In `backend/app/providers/openai_provider.py`, preserve the user's existing comments and import `DailyDietSummaryResult`. Add a method that serializes only the supplied payload and validates the response:

```python
    def summarize_daily_diet(self, payload: dict[str, Any]) -> DailyDietSummaryResult:
        try:
            response = self._client.chat.completions.create(
                model=self.text_model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "你是每日饮食结构总结器，只依据给定的已确认饮食记录返回严格 JSON。"
                            "不得补造食物、份量或营养数值，不得使用好食物/坏食物等道德化表达，"
                            "不得作诊断。只有一餐时必须使用 insufficient_data，并明确记录有限，"
                            "不能代表完整全天。格式："
                            '{"balance_assessment":"balanced|imbalanced|insufficient_data",'
                            '"conclusion":"不超过240字",'
                            '"today_suggestion":"不超过240字","confidence":0到1}'
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    },
                ],
                max_tokens=800,
                extra_body={"thinking": {"type": "disabled"}},
                **settings.llm_temperature_kwargs(self.text_model),
            )
            raw = response.choices[0].message.content or ""
            if "```" in raw:
                match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, re.DOTALL)
                if match:
                    raw = match.group(1)
            usage = getattr(response, "usage", None)
            data = json.loads(raw)
            return DailyDietSummaryResult(
                **data,
                prompt_tokens=getattr(usage, "prompt_tokens", None) if usage else None,
                completion_tokens=getattr(usage, "completion_tokens", None) if usage else None,
            )
        except Exception as exc:
            raise ValueError("daily diet summary provider output is invalid") from exc
```

- [ ] **Step 6: Run provider tests and verify GREEN**

```bash
backend/.venv/bin/python -I -m pytest backend/tests/unit/test_openai_provider_parsing.py -q
```

Expected: all provider parsing tests pass, including the new named test.

- [ ] **Step 7: Commit provider contract and tests**

```bash
git add backend/app/providers/base.py backend/app/providers/mock_provider.py backend/app/providers/openai_provider.py backend/tests/unit/test_openai_provider_parsing.py
git commit -m "feat(backend): add daily diet summary provider"
```

---

### Task 3: Build the Version-Bound Fallback and AI Finalization Pipeline With TDD

**Files:**
- Modify: `backend/app/services/dietary_records_service.py`
- Modify: `backend/tests/unit/test_dietary_records_contract.py`

**Interfaces:**
- Consumes: `DailyDietSummaryResult`, authenticated tenant IDs, Beijing target date, and current UTC time.
- Produces: `discover_beijing_summary_candidates`, `prepare_daily_summary_attempt`, `finalize_daily_summary`, `record_daily_summary_failure`, and `discover_due_summary_retry_ids`.

- [ ] **Step 1: Rename and rewrite the existing completion regression around the new behavior**

Rename:

```python
test_auto_and_manual_completion_wait_for_pending_and_use_versioned_rules_without_llm
```

to:

```python
test_beijing_daily_summary_only_processes_confirmed_yesterday_users_and_retries_model_failure
```

Keep its existing tenant and 04:00 fixtures, then replace the old `openai not in source` assertions with meaningful assertions that:

```python
assert service.beijing_target_date(datetime.fromisoformat("2026-07-21T03:59:59+08:00")) == date(2026, 7, 20)
assert service.discover_beijing_summary_candidates(db, target_date=date(2026, 7, 16), limit=10) == [(1, 1)]

prepared = service.prepare_daily_summary_attempt(
    db,
    user_id=1,
    subject_user_id=1,
    target_date=date(2026, 7, 16),
    now=datetime.fromisoformat("2026-07-16T20:00:00+00:00"),
)
db.commit()
assert prepared is not None
assert prepared["summary"]["evidence"]["generation_status"] == "fallback_retryable"
assert prepared["summary"]["confirmed_meal_count"] == 1
assert "记录有限" in prepared["summary"]["conclusion"]
assert prepared["model_payload"]["confirmed_meal_count"] == 1
assert set(prepared["model_payload"]["meals"][0]) == {
    "meal_type", "food_items", "portion_text", "structure",
    "estimated_nutrition", "confidence"
}
```

Import `DailyDietSummaryResult` from `app.providers.base`, then add a stale-write assertion:

```python
result = DailyDietSummaryResult(
    balance_assessment="insufficient_data",
    conclusion="昨天只确认了一餐，无法代表全天。",
    today_suggestion="今天补充记录早餐和晚餐。",
    confidence=0.55,
)
assert service.finalize_daily_summary(
    db,
    summary_id=prepared["summary"]["summary_id"],
    expected_record_version=prepared["record_version"],
    expected_input_fingerprint=prepared["model_input_fingerprint"],
    result=result,
    now=datetime.fromisoformat("2026-07-16T20:01:00+00:00"),
) is True
```

Then create a second prepared summary, increment its day `record_version`, and assert the same call returns `False` without changing the summary text.

- [ ] **Step 2: Run the renamed test and verify RED**

```bash
backend/.venv/bin/python -I -m pytest backend/tests/unit/test_dietary_records_contract.py::test_beijing_daily_summary_only_processes_confirmed_yesterday_users_and_retries_model_failure -q
```

Expected: FAIL because `beijing_target_date` and the pipeline functions do not exist.

- [ ] **Step 3: Add Beijing date, normalized payload, and retry constants**

In `backend/app/services/dietary_records_service.py`, add:

```python
BEIJING_TIMEZONE = ZoneInfo("Asia/Shanghai")
SUMMARY_RETRY_DELAYS = (
    timedelta(minutes=5),
    timedelta(minutes=15),
    timedelta(hours=1),
    timedelta(hours=3),
    timedelta(hours=6),
)


def beijing_target_date(now: datetime | None = None) -> date:
    effective = _aware_utc(now or _now()).astimezone(BEIJING_TIMEZONE)
    return effective.date() - timedelta(days=1)
```

Build the model payload from `_active_records` in stable `eaten_at, id` order, exposing only the six approved meal fields. Compute `model_input_fingerprint` with the existing `_fingerprint` helper.

- [ ] **Step 4: Add candidate discovery and fallback preparation**

Implement candidate discovery with exact tenant pairs:

```python
def discover_beijing_summary_candidates(
    db: Session, *, target_date: date, limit: int
) -> list[tuple[int, int]]:
    rows = db.execute(
        select(DietaryRecord.user_id, DietaryRecord.subject_user_id)
        .where(
            DietaryRecord.diet_date == target_date,
            DietaryRecord.status != "deleted",
        )
        .distinct()
        .order_by(DietaryRecord.user_id, DietaryRecord.subject_user_id)
        .limit(max(1, min(limit, 500)))
    ).all()
    return [(int(user_id), int(subject_id)) for user_id, subject_id in rows]
```

`prepare_daily_summary_attempt` must lock the existing day, call `_refresh_day_counts`, return `None` only when there are no active records, accept one confirmed meal, create or reuse the versioned fallback, and write this evidence shape:

```python
evidence = {
    "included_record_ids": [record.id for record in records],
    "excluded_pending_draft_ids": [draft.id for draft in pending],
    "pending_records_excluded": bool(pending),
    "natural_language_generated_by_model": False,
    "generation_status": "fallback_retryable",
    "retry_attempt_count": 0,
    "next_retry_at": _aware_utc(now).isoformat(),
    "last_error_code": None,
    "model_input_fingerprint": model_input_fingerprint,
}
```

For one meal, use the exact fallback conclusion `昨天只确认了 1 餐，记录有限，无法完整代表全天饮食。`.

- [ ] **Step 5: Add conditional success and durable failure updates**

Implement:

```python
def finalize_daily_summary(
    db: Session,
    *,
    summary_id: int,
    expected_record_version: int,
    expected_input_fingerprint: str,
    result: DailyDietSummaryResult,
    now: datetime,
) -> bool:
    summary = db.scalar(
        select(DietaryDailySummary)
        .where(DietaryDailySummary.id == summary_id)
        .with_for_update()
    )
    if summary is None or summary.record_version != expected_record_version:
        return False
    day = db.scalar(select(DietaryDay).where(DietaryDay.id == summary.day_id).with_for_update())
    evidence = dict(summary.evidence or {})
    if (
        day is None
        or day.record_version != expected_record_version
        or evidence.get("model_input_fingerprint") != expected_input_fingerprint
        or evidence.get("generation_status") != "fallback_retryable"
    ):
        return False
    summary.conclusion = result.conclusion
    summary.today_suggestion = result.today_suggestion
    summary.confidence = result.confidence
    summary.generated_at = _aware_utc(now)
    summary.evidence = {
        **evidence,
        "balance_assessment": result.balance_assessment,
        "generation_status": "ai_completed",
        "natural_language_generated_by_model": True,
        "retry_attempt_count": int(evidence.get("retry_attempt_count") or 0),
        "next_retry_at": None,
        "last_error_code": None,
        "prompt_tokens": result.prompt_tokens,
        "completion_tokens": result.completion_tokens,
    }
    db.add(summary)
    return True
```

`record_daily_summary_failure` must normalize the error to one of `provider_timeout`, `provider_invalid_output`, or `provider_error`. The initial 04:00 attempt failure leaves `retry_attempt_count=0` and schedules the 5-minute retry. Each retry failure increments the count and schedules 15 minutes, 1 hour, 3 hours, then 6 hours; the fifth failed retry changes the state to `fallback_exhausted`. Model this explicitly with `increment_retry_attempt: bool` so the initial failure and retry failures cannot be confused. It must never persist `str(exc)`, provider response bytes, credentials, or the model payload.

- [ ] **Step 6: Run the service regression and verify GREEN**

```bash
backend/.venv/bin/python -I -m pytest backend/tests/unit/test_dietary_records_contract.py::test_beijing_daily_summary_only_processes_confirmed_yesterday_users_and_retries_model_failure -q
```

Expected: PASS.

- [ ] **Step 7: Commit the service state machine and regression**

```bash
git add backend/app/services/dietary_records_service.py backend/tests/unit/test_dietary_records_contract.py
git commit -m "feat(backend): persist daily diet summary fallback"
```

---

### Task 4: Wire the 04:00 Task and Retry Sweep With TDD

**Files:**
- Modify: `backend/app/workers/celery_app.py`
- Modify: `backend/app/workers/dietary_tasks.py`
- Modify: `backend/tests/unit/test_dietary_records_contract.py`

**Interfaces:**
- Consumes: service preparation/finalization/failure functions and `get_provider()`.
- Produces: Celery tasks `generate_beijing_daily_diet_summaries` and `retry_daily_diet_summaries`.

- [ ] **Step 1: Extend the renamed regression with exact task assertions**

Add assertions before worker implementation:

```python
from celery.schedules import crontab
from app.workers import dietary_tasks
from app.workers.celery_app import celery_app

celery_app.loader.import_default_modules()
entry = celery_app.conf.beat_schedule["beijing-daily-diet-summary"]
assert entry["task"] == "generate_beijing_daily_diet_summaries"
assert isinstance(entry["schedule"], crontab)
assert str(entry["schedule"]._orig_hour) == "4"
assert str(entry["schedule"]._orig_minute) == "0"
assert "dietary-day-completion-sweep" not in celery_app.conf.beat_schedule
assert celery_app.conf.beat_schedule["daily-diet-summary-retry"]["task"] == "retry_daily_diet_summaries"
```

Inject a fake provider that fails once and succeeds once, run the main task and retry task, and assert the first result reports one fallback while the second changes the same summary to AI without adding another row.

- [ ] **Step 2: Run the worker regression and verify RED**

```bash
backend/.venv/bin/python -I -m pytest backend/tests/unit/test_dietary_records_contract.py::test_beijing_daily_summary_only_processes_confirmed_yesterday_users_and_retries_model_failure -q
```

Expected: FAIL because the new Beat entries and tasks do not exist.

- [ ] **Step 3: Replace the timezone-derived Beat sweep**

In `backend/app/workers/celery_app.py`, replace `dietary-day-completion-sweep` with:

```python
    "beijing-daily-diet-summary": {
        "task": "generate_beijing_daily_diet_summaries",
        "schedule": crontab(hour=4, minute=0),
    },
    "daily-diet-summary-retry": {
        "task": "retry_daily_diet_summaries",
        "schedule": 60.0,
    },
```

- [ ] **Step 4: Implement per-user orchestration outside transactions**

In `backend/app/workers/dietary_tasks.py`, import `get_provider` and implement a shared `_run_summary_attempt(summary_id, ...)` that:

1. Opens and commits a preparation transaction.
2. Closes that session before `provider.summarize_daily_diet(model_payload)`.
3. Opens a fresh session to finalize or record failure and commits.
4. Returns one of `ai_completed`, `fallback_retryable`, `fallback_exhausted`, `stale`, or `skipped`.

The main task must derive the target with `beijing_target_date(effective_now)`, discover only candidate tenant pairs, isolate each candidate in `try/except`, and return counters:

```python
{
    "discovered": 1,
    "processed": 1,
    "ai_completed": 0,
    "fallback_retryable": 1,
    "fallback_exhausted": 0,
    "stale": 0,
    "skipped": 0,
    "failed": 0,
}
```

The retry task must call `discover_due_summary_retry_ids`, rebuild and fingerprint the current payload, skip stale versions, and never rediscover users merely because they have old records.

- [ ] **Step 5: Remove dashboard-triggered timezone auto-completion**

Delete the call to `auto_complete_due_days(...)` from `dashboard`. Keep manual completion and `_recalculate_if_stale`; background scheduling is now the only automatic creation trigger. Do not delete `derive_diet_date`, because record assignment still uses its existing dietary-day boundary.

- [ ] **Step 6: Run worker and full dietary contract tests**

```bash
backend/.venv/bin/python -I -m pytest backend/tests/unit/test_dietary_records_contract.py -q
```

Expected: all dietary contract tests pass; no test asserts per-record-timezone automatic closure.

- [ ] **Step 7: Commit scheduling and orchestration**

```bash
git add backend/app/workers/celery_app.py backend/app/workers/dietary_tasks.py backend/app/services/dietary_records_service.py backend/tests/unit/test_dietary_records_contract.py
git commit -m "feat(backend): schedule Beijing diet summaries"
```

---

### Task 5: Add the Authenticated Daily-Summary Read API With TDD

**Files:**
- Modify: `backend/app/schemas/dietary_records.py`
- Modify: `backend/app/services/dietary_records_service.py`
- Modify: `backend/app/routers/dietary_records.py`
- Modify: `backend/tests/unit/test_dietary_records_contract.py`

**Interfaces:**
- Consumes: authenticated `user_id`, database session, and server time.
- Produces: `GET /api/dietary-records/daily-summary -> DietaryDailySummaryStatusOut`.

- [ ] **Step 1: Write the failing four-state endpoint regression**

Add:

```python
def test_daily_summary_api_distinguishes_never_recorded_missed_yesterday_processing_and_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _models, _router, service, _migration = _contract_modules()
    client, factory, headers, other_headers = _client(monkeypatch)
    monkeypatch.setattr(
        service,
        "_now",
        lambda: datetime.fromisoformat("2026-07-21T05:00:00+08:00"),
    )

    never = client.get("/api/dietary-records/daily-summary", headers=headers)
    assert never.status_code == 200
    assert never.json() == {
        "status": "never_recorded",
        "target_date": "2026-07-20",
        "message": "还没有记录过饮食呢，快记录你的第一餐吧",
        "summary": None,
    }

    old = _create_draft(
        client, headers, event_id="old-meal", diet_date="2026-07-19",
        eaten_at="2026-07-19T12:00:00+08:00",
    )
    _confirm_draft(client, headers, old, event_id="old-meal-confirm")
    missed = client.get("/api/dietary-records/daily-summary", headers=headers)
    assert missed.json()["status"] == "no_yesterday_records"
    assert missed.json()["message"] == "昨天忘记记录饮食啦"

    yesterday = _create_draft(
        client, headers, event_id="yesterday-meal", diet_date="2026-07-20",
        eaten_at="2026-07-20T12:00:00+08:00",
    )
    _confirm_draft(client, headers, yesterday, event_id="yesterday-meal-confirm")
    processing = client.get("/api/dietary-records/daily-summary", headers=headers)
    assert processing.json()["status"] == "processing"
    assert processing.json()["summary"] is None

    with factory() as db:
        service.prepare_daily_summary_attempt(
            db,
            user_id=1,
            subject_user_id=1,
            target_date=date(2026, 7, 20),
            now=datetime.fromisoformat("2026-07-20T20:00:00+00:00"),
        )
        db.commit()

    available = client.get("/api/dietary-records/daily-summary", headers=headers)
    body = available.json()
    assert body["status"] == "available"
    assert body["message"] is None
    assert body["summary"]["generation_source"] == "rule_fallback"
    assert body["summary"]["retry_pending"] is True
    assert "记录有限" in body["summary"]["conclusion"]

    other = client.get("/api/dietary-records/daily-summary", headers=other_headers)
    assert other.json()["status"] == "never_recorded"
```

- [ ] **Step 2: Run the endpoint test and verify RED**

```bash
backend/.venv/bin/python -I -m pytest backend/tests/unit/test_dietary_records_contract.py::test_daily_summary_api_distinguishes_never_recorded_missed_yesterday_processing_and_fallback -q
```

Expected: FAIL with HTTP 404 because the route does not exist.

- [ ] **Step 3: Add the response schemas**

In `backend/app/schemas/dietary_records.py` add:

```python
class DietaryDailySummaryDisplayOut(BaseModel):
    conclusion: str
    today_suggestion: str
    confirmed_meal_count: int
    confidence: float
    generation_source: Literal["ai", "rule_fallback"]
    retry_pending: bool
    generated_at: datetime


class DietaryDailySummaryStatusOut(BaseModel):
    status: Literal["available", "never_recorded", "no_yesterday_records", "processing"]
    target_date: date
    message: str | None
    summary: DietaryDailySummaryDisplayOut | None
```

- [ ] **Step 4: Implement exact state precedence**

In `dietary_records_service.py`, implement `daily_summary_status` using `exists()` queries scoped by both tenant IDs:

```python
NEVER_RECORDED_MESSAGE = "还没有记录过饮食呢，快记录你的第一餐吧"
NO_YESTERDAY_RECORDS_MESSAGE = "昨天忘记记录饮食啦"
```

State order must be:

1. No active confirmed record at any date: `never_recorded`.
2. No active confirmed record at the Beijing target date: `no_yesterday_records`.
3. No current-version summary for the target date: `processing`.
4. Summary exists: `available`.

Map evidence to display fields without exposing raw evidence:

```python
status = str((summary.evidence or {}).get("generation_status") or "fallback_retryable")
generation_source = "ai" if status == "ai_completed" else "rule_fallback"
retry_pending = status == "fallback_retryable"
```

- [ ] **Step 5: Add the parameterless authenticated route**

Import `DietaryDailySummaryStatusOut` in `backend/app/routers/dietary_records.py` and add:

```python
@router.get("/daily-summary", response_model=DietaryDailySummaryStatusOut)
def get_daily_dietary_summary(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> DietaryDailySummaryStatusOut:
    uid = int(user_id)
    return DietaryDailySummaryStatusOut(
        **dietary_service.daily_summary_status(
            db,
            user_id=uid,
            subject_user_id=uid,
        )
    )
```

- [ ] **Step 6: Run endpoint and dietary tests and verify GREEN**

```bash
backend/.venv/bin/python -I -m pytest backend/tests/unit/test_dietary_records_contract.py::test_daily_summary_api_distinguishes_never_recorded_missed_yesterday_processing_and_fallback -q
backend/.venv/bin/python -I -m pytest backend/tests/unit/test_dietary_records_contract.py -q
```

Expected: both commands pass.

- [ ] **Step 7: Commit the API and regression**

```bash
git add backend/app/schemas/dietary_records.py backend/app/services/dietary_records_service.py backend/app/routers/dietary_records.py backend/tests/unit/test_dietary_records_contract.py
git commit -m "feat(backend): expose yesterday diet summary"
```

---

### Task 6: Update Exact Test Inventories and Regression Contracts

**Files:**
- Modify: `quality/expected_python_tests.json`
- Modify: `quality/regression_contracts.json`
- Modify: `tools/python_test_gate.py`
- Modify: `tools/run_regression_gate.py`
- Modify: `tools/tests/test_python_test_gate.py`
- Modify: `tools/tests/test_run_regression_gate.py`
- Modify if required by pinned digests: `tools/regression_guard.py`
- Modify if required by an existing digest assertion: `tools/tests/test_regression_guard.py`

**Interfaces:**
- Consumes: the collected pytest IDs after Tasks 2–5.
- Produces: an exact backend inventory of 333 IDs, with 330 passing tests and the same three pinned integration skips.

- [ ] **Step 1: Collect and review the exact new IDs**

```bash
backend/.venv/bin/python -I -m pytest backend/tests --collect-only -q > /tmp/xjie-backend-collect.txt
grep 'test_daily_diet_summary_provider_uses_minimal_strict_payload_and_rejects_invalid_output' /tmp/xjie-backend-collect.txt
grep 'test_beijing_daily_summary_only_processes_confirmed_yesterday_users_and_retries_model_failure' /tmp/xjie-backend-collect.txt
grep 'test_daily_summary_api_distinguishes_never_recorded_missed_yesterday_processing_and_fallback' /tmp/xjie-backend-collect.txt
```

Expected: each new/renamed test ID appears exactly once. Total collected count is 333.

- [ ] **Step 2: Update the manifest and count constants**

In `quality/expected_python_tests.json`:

- Add the provider test ID.
- Replace the old `...use_versioned_rules_without_llm` ID with `...test_beijing_daily_summary_only_processes_confirmed_yesterday_users_and_retries_model_failure`.
- Add the daily-summary API test ID.
- Preserve all other IDs and the same three exact skip entries/reasons.

Change `CURRENT_BACKEND_FULL_TESTS = 331` to `333` in both `tools/python_test_gate.py` and `tools/run_regression_gate.py`. Change only the corresponding existing count assertions from `331` to `333` in `tools/tests/test_python_test_gate.py` and `tools/tests/test_run_regression_gate.py`. Do not add a tools test ID, so the tools inventory remains exactly 80.

- [ ] **Step 3: Strengthen the dietary regression contract anchors**

In `quality/regression_contracts.json`, replace the old dietary completion symbol with the renamed Beijing test and add the daily-summary API test as a `HEALTH-REGISTRY-001`/`HEALTH-ACCOUNT-001` anchor. Add the provider test under the existing AI provider anchors. Recompute only the registry/code-side hashes required by the existing guard; do not weaken domains, patterns, commands, or invariant text.

- [ ] **Step 4: Run the exact inventory and guard tests**

```bash
/usr/bin/python3 -I -m unittest tools.tests.test_python_test_gate tools.tests.test_run_regression_gate tools.tests.test_regression_guard
backend/.venv/bin/python -I tools/python_test_gate.py backend --profile focused --junitxml /tmp/xjie-backend-health.xml -- backend/tests/unit/test_dietary_records_contract.py backend/tests/unit/test_openai_provider_parsing.py -q
```

Expected: tools tests pass with no skips; the focused backend run contains exactly the requested registered IDs and passes.

- [ ] **Step 5: Commit inventory and contract changes**

```bash
git add quality/expected_python_tests.json quality/regression_contracts.json tools/python_test_gate.py tools/run_regression_gate.py tools/regression_guard.py tools/tests/test_python_test_gate.py tools/tests/test_run_regression_gate.py tools/tests/test_regression_guard.py
git commit -m "test: register daily diet summary regressions"
```

---

### Task 7: Run Required Gates and Review the Final Candidate

**Files:**
- Verify: all files changed in Tasks 1–6.
- Modify only if a required gate exposes a real defect; any fix must start with a reproducing regression assertion.

**Interfaces:**
- Consumes: the stable implementation and exact inventories.
- Produces: development feedback from `fast`, candidate evidence from one `impacted` run, and a clean intentional diff ready for PR delivery.

- [ ] **Step 1: Run focused provider and dietary regressions**

```bash
backend/.venv/bin/python -I -m pytest backend/tests/unit/test_openai_provider_parsing.py backend/tests/unit/test_dietary_records_contract.py -q
```

Expected: all selected tests pass with no warnings or skips.

- [ ] **Step 2: Run the normal editing gate**

```bash
/usr/bin/python3 -I tools/run_regression_gate.py fast
```

Expected: PASS with the explicit `NOT RELEASE EVIDENCE` development label. If it fails, preserve the failure, reproduce the trigger, add or strengthen the deterministic regression, fix the root cause, and rerun on a new exact commit.

- [ ] **Step 3: Inspect tenant, privacy, schedule, and diff boundaries**

```bash
git diff main...HEAD --check
git diff main...HEAD --stat
git status --short
rg -n "generate_beijing_daily_diet_summaries|retry_daily_diet_summaries|daily-summary|generation_status" backend/app backend/tests
```

Expected: no whitespace errors; no migration/iOS/push files; schedule and endpoint occur only in audited paths; the user's pre-existing uncommitted edits remain visible but are not accidentally staged.

- [ ] **Step 4: Run the affected candidate gate exactly once**

```bash
/usr/bin/python3 -I tools/run_regression_gate.py impacted
```

Expected: PASS for the stable exact candidate. This is affected-candidate evidence only, not TestFlight, deployment, or release evidence.

- [ ] **Step 5: Commit any gate-driven test-first fix, then verify commit scope**

If no fix was required, do not create an empty commit. If a gate exposes a defect, return to the task that owns that exact interface, add a named failing assertion in `backend/tests/unit/test_dietary_records_contract.py` or `backend/tests/unit/test_openai_provider_parsing.py`, run it to verify RED, patch only the owning production file listed in that task, run it to verify GREEN, then stage those exact changed paths and commit with `fix(backend): close daily summary regression`.

Then run:

```bash
git log --oneline main..HEAD
git diff --name-status main...HEAD
git status --short
```

Expected: all feature commits are present; no unrelated user-owned file was committed; only the known pre-existing working-tree edits remain unstaged.
