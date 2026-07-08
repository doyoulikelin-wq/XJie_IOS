from __future__ import annotations

import copy
import json
import logging
import re
from typing import Iterator

from openai import OpenAI

from app.core.config import settings
from app.providers.base import ChatLLMResult, LLMProvider, MealVisionItem, MealVisionResult
from app.services.health_nlu import analyze_health_message

logger = logging.getLogger(__name__)

# ── Health/medical topic detection ────────────────────────────

_HEALTH_KEYWORDS = re.compile(
    r"血糖|血压|血脂|胆固醇|甘油三酯|糖化血红蛋白|BMI|体重|肥胖|脂肪肝|"
    r"糖尿病|胰岛素|代谢|尿酸|痛风|心血管|冠心病|高血压|低血糖|"
    r"HRV|心率变异|NT|颈项透明层|头疼|头痛|失眠|胃痛|腹泻|便秘|恶心|呕吐|发烧|咳嗽|"
    r"感冒|过敏|皮疹|水肿|疲劳|乏力|胸闷|心悸|头晕|"
    r"肝功能|肾功能|甲状腺|体检|报告|检查|化验|指标|异常|偏高|偏低|"
    r"组学|代谢组|蛋白组|基因|风险|健康|饮食|营养|热量|卡路里|"
    r"运动|锻炼|睡眠|作息|膳食|碳水|蛋白质|脂肪|维生素|"
    r"药|治疗|症状|诊断|病|医院|医生|处方",
    re.IGNORECASE,
)


def _is_health_query(user_query: str, history: list[dict] | None = None) -> bool:
    """Detect if the query is health/medical related."""
    try:
        if analyze_health_message(user_query, history=history).get("has_health_signal"):
            return True
    except Exception:  # noqa: BLE001
        logger.debug("health_nlu detection failed; falling back to regex", exc_info=True)
    if _HEALTH_KEYWORDS.search(user_query):
        return True
    # Check recent history for medical context
    if history:
        for msg in history[-4:]:
            if _HEALTH_KEYWORDS.search(msg.get("content", "")):
                return True
    return False

SYSTEM_PROMPT = """\
你是「小捷」，用户的私人代谢健康助手。你亲切、温暖，像一个懂医学的好朋友。

## 你的核心能力
- 代谢健康管理：血糖分析、饮食建议、体检报告解读、脂肪肝/糖尿病风险评估、代谢组学报告解读
- 日常健康咨询：感冒、头疼、胃痛、腹泻、失眠、皮疹、焦虑等常见问题，你会先筛红旗信号，再给观察窗口和可执行建议；只有在确实相关时才自然关联代谢健康，不强行转题
- 对话式了解用户：在聊天中主动、自然地了解用户的基本信息和生活习惯

## 对话风格
- 像朋友聊天，不要像医生看诊。用"你"而不是"您"
- 简洁直接，不说废话
- **绝对不要使用任何 emoji 符号**，全部用纯文字表达

## 用户消息结构与数据感知策略（极其重要 — 严格执行）
系统会提供 message_structure，里面包含 health_nlu、active_subject、intent、data_source_memory、session_memory 和 response_plan。你必须先执行这些结构化约束，再生成回答。

0. **先执行 health_nlu，再组织语言**
   - health_nlu.matched_concepts / concept_keys 是后端归一化后的医学概念，优先级高于用户缩写或口语字面意思。
   - health_nlu.primary_intent 决定本轮是数据源查询、报告状态、风险判断、趋势分析、家属病例、孕产问题、用药安全、急症分流还是普通咨询。
   - health_nlu.data_requirements 是回答需要核对的数据类型；已有数据用来源和时间，没有就说“暂无记录 / 待同步 / 待上传”，不能编数字。
   - health_nlu.safety_profile.level 为 medium/high/emergency 时，必须先处理安全边界，再给健康管理建议。
   - health_nlu.primary_intent = symptom_triage 时，先筛急症红旗和观察窗口，再给居家处理；不能把胸痛、呼吸困难、昏厥、卒中信号当普通症状。
   - health_nlu.primary_intent = lifestyle_coaching 时，把饮食、运动、饮水、酒精、咖啡因、吸烟和作息转成 1-3 个可执行动作，结合已有数据，不空泛说教。
   - health_nlu.primary_intent = mental_health_support 时，先回应压力/情绪，再筛自伤念头、惊恐发作和功能受损；出现危机信号必须建议立即求助。
   - response_plan.quality_gates 是硬性质量门槛，回答必须逐条满足。

1. **先判断主体，再用数据**
   - active_subject.type = self 时，才可以使用用户本人的健康指标、报告、用药和设备数据。
   - active_subject.type = relative / other_case 时，禁止使用用户本人的尿酸、血糖、TIR、报告、用药、Apple 健康等数据，除非用户明确要求“拿我的数据对比”。
   - 用户纠正“不是我 / 是我老婆 / 帮别人问”时，纠正优先级高于历史摘要。

2. **只使用 response_plan.allowed_context，不使用 blocked_context**
   - blocked_context 里的内容即使出现在历史对话或数据摘要中，也不能当成本轮事实。
   - 如果问题是家人/妻子/朋友，回答必须基于用户本轮提供的信息和通用医学知识，不能混入本人的健康结论。

3. **已知数据源不能反问**
   - data_source_memory.connected.apple_health = true 时，不得问“你是否戴 Apple Watch / 是否同步 Apple 健康 / 把 HRV 截图发给我”。
   - Apple 健康是聚合来源，不能自动说成 Apple Watch，除非系统明确提供设备型号。
   - 数据过期时，说明上次同步时间和需要刷新，不要反问用户是否有设备。

4. **有数据要讲来源和时间，无数据要讲暂无**
   - 引用指标时必须结合 source 和 measured_at。
   - 用户没有的指标显示“暂无记录 / 待上传 / 待同步”，不能编数字。
   - 过期数据必须说明“这是某日期的数据，不代表今天”。

5. **减少重复和过度追问**
   - session_memory.covered_facts 和 avoid_repeating 中的内容不要逐字重复。
   - session_memory.repetition_policy.mode = delta_only 时，用户是在连续追问；先回答新增点，只用一句话承接旧结论。
   - 用户问候时，只恢复上下文，不主动输出完整病史摘要。
   - 每轮最多一个追问；追问必须服务当前判断，不能泛泛问设备、生活习惯或让用户上传已同步的数据。

## 用户画像提取（每次对话都要做）
如果用户在消息中提到了个人信息，在 JSON 的 profile_extracted 字段中提取。只提取用户**明确说出**的信息，不要猜测。
可提取字段: sex（性别）、age（年龄）、height_cm（身高cm）、weight_kg（体重kg）、display_name（昵称/称呼）

## 输出格式 — 严格 JSON，不要输出任何其他文字:
```json
{
  "summary": "完整的回复总结（80-200字，必须包含三要素，不能截断）",
  "analysis": "详细分析（Markdown 格式，包含原因分析、具体建议、数据引用，300-800字）",
  "followups": ["用户可能想继续问的话1", "用户可能想继续问的话2"],
  "profile_extracted": {}
}
```

### summary 规范（极其重要）:
summary 是用户直接看到的主要回复内容，必须完整、不能截断。
必须同时包含三要素：
1. **是什么** — 简要说明原因或情况
2. **怎么办** — 给出 1-2 个具体可行建议
3. **继续引导** — 自然地引出下一个话题

示例:
- "头疼可能跟睡眠不足或压力有关，建议先喝杯温水、按压太阳穴缓解一下。跟我说说你最近的睡眠情况，我帮你排查原因"
- "你最近7天血糖波动偏大(TIR 65%)，可能和晚餐碳水偏高有关。试试把主食减少1/3，要不要我帮你看看哪顿饭影响最大？"

### followups 规则:
followups 是**用户的快捷回复选项**，必须站在用户角度写:
- 正确: "帮我看看哪顿饭影响血糖最大", "我最近睡眠不太好"
- 错误: "头疼是持续的还是间歇的？"（这是 AI 提问口吻，不可用）

### 绝对不要:
- 使用任何 emoji 符号
- 说"缺乏数据无法判断"、"建议补充数据"这类让用户扫兴的话
- summary 少于 80 字或内容被截断
- followups 写成 AI 提问的口吻
- 忽略 message_structure 的主体、禁止问题和 blocked_context
- 在家人/妻子问题中混入用户本人的健康指标
- 对已经同步的硬件/Apple 健康数据继续反问是否佩戴或是否同步
- 输出 JSON 以外的任何文字
"""


def _build_messages(
    context: dict,
    user_query: str,
    history: list[dict] | None = None,
    skill_prompt: str = "",
) -> list[dict]:
    """Build the messages array for OpenAI Chat Completions."""
    base_prompt = SYSTEM_PROMPT
    if skill_prompt:
        base_prompt += "\n\n# 当前激活的专业技能\n" + skill_prompt
    messages: list[dict] = [{"role": "system", "content": base_prompt}]

    message_structure = context.get("message_structure") or {}
    response_plan = message_structure.get("response_plan") or {}
    allowed_context = set(response_plan.get("allowed_context") or [])
    blocked_context = set(response_plan.get("blocked_context") or [])
    allow_user_self_context = (
        "user_self_health_facts" in allowed_context
        and "user_self_health_facts" not in blocked_context
    )
    prompt_message_structure = _sanitize_message_structure_for_prompt(
        message_structure,
        allow_user_self_context=allow_user_self_context,
    )
    if message_structure:
        messages.append({
            "role": "system",
            "content": (
                "以下是后端已解析的用户消息结构。必须严格按 active_subject、intent、"
                "health_nlu、data_source_memory、session_memory 和 response_plan 回答；不得违反 "
                "forbidden_questions 与 blocked_context。\n"
                + json.dumps(prompt_message_structure, ensure_ascii=False, default=str)
            ),
        })
    if not allow_user_self_context:
        context = {
            **context,
            "glucose_summary": {},
            "glucose": {},
            "meals_today": [],
            "symptoms_last_7d": [],
            "agent_features": {},
            "user_profile_info": {},
            "health_report_text": "",
            "health_summary_text": "",
            "patient_history": {},
            "omics_analyses": [],
            "current_medications": [],
            "recent_conversation_summaries": [],
        }
        subject = (message_structure.get("active_subject") or {}).get("display", "他人")
        messages.append({
            "role": "system",
            "content": (
                f"本轮问题主体是{subject}，不是当前登录用户本人。"
                "后端已屏蔽本人健康数据；回答只能使用用户本轮提供的信息、"
                "会话纠正和通用医学知识。"
            ),
        })

    # Inject user context as a system message
    ctx_parts = []
    has_real_data = False

    # Glucose summary
    g = context.get("glucose_summary") or context.get("glucose") or {}
    for label, key in [("过去24h", "last_24h"), ("过去7天", "last_7d")]:
        d = g.get(key) or {}
        if d.get("avg") is not None:
            has_real_data = True
            ctx_parts.append(f"血糖({label}): 均值={d['avg']}mg/dL, TIR(70-180)={d.get('tir_70_180_pct')}%, 变异性={d.get('variability')}")

    # Daily calories
    dq = context.get("data_quality") or {}
    kcal = dq.get("kcal_today") if dq else context.get("kcal_today")
    if kcal and kcal > 0:
        has_real_data = True
        ctx_parts.append(f"今日热量: {kcal} kcal")

    if context.get("meals_today"):
        has_real_data = True
        meals = context["meals_today"]
        ctx_parts.append(f"今日进餐 {len(meals)} 次: " +
                         ", ".join(f"{m.get('kcal', '?')}kcal@{m.get('ts', '?')}" for m in meals))

    if context.get("symptoms_last_7d"):
        symptoms = context["symptoms_last_7d"]
        ctx_parts.append(f"近7天症状 {len(symptoms)} 条: " +
                         ", ".join(f"{s.get('text', '')}(严重度{s.get('severity', '?')})" for s in symptoms[:5]))

    if context.get("agent_features"):
        ctx_parts.append(f"Agent特征: {json.dumps(context['agent_features'], ensure_ascii=False)}")

    # User profile
    profile = context.get("user_profile_info") or {}
    if profile:
        ctx_parts.append(f"用户画像: {json.dumps(profile, ensure_ascii=False)}")

    # Health exam report data (Liver subjects)
    health_text = context.get("health_report_text", "")
    if health_text:
        has_real_data = True
        ctx_parts.append(f"体检报告数据:\n{health_text}")

    # AI health summary from uploaded health documents (体检报告)
    health_summary = context.get("health_summary_text", "")
    if health_summary:
        has_real_data = True
        ctx_parts.append(f"用户健康总结(基于历年体检报告):\n{health_summary}")

    # Omics analysis results
    omics = context.get("omics_analyses") or []
    if omics:
        has_real_data = True
        for o in omics:
            ctx_parts.append(
                f"代谢组学分析({o['type']}): 文件={o['file_name']}, "
                f"风险等级={o.get('risk_level', '未知')}, "
                f"摘要={o.get('summary', '')}"
            )

    # Current medications (用药提醒模块录入)
    meds = context.get("current_medications") or []
    if meds:
        has_real_data = True
        med_lines = []
        for m in meds[:20]:
            parts = [m["name"]]
            if m.get("dosage"):
                parts.append(f"剂量:{m['dosage']}")
            if m.get("frequency"):
                parts.append(f"频次:{m['frequency']}")
            if m.get("schedule_times"):
                parts.append("时间:" + "/".join(m["schedule_times"]))
            if m.get("course_start") or m.get("course_end"):
                parts.append(
                    f"疗程:{m.get('course_start') or '?'}~{m.get('course_end') or '?'}"
                )
            if m.get("instructions"):
                parts.append(f"备注:{m['instructions']}")
            med_lines.append(" | ".join(parts))
        ctx_parts.append(
            "当前用药 ("
            + str(len(meds))
            + " 项，回答时请结合药物相互作用、副作用、用药时机给出建议)：\n- "
            + "\n- ".join(med_lines)
        )

    # Build the data context message
    if ctx_parts:
        prefix = "以下是该用户的健康数据，回答时必须主动引用相关数据：" if has_real_data else "该用户暂无设备数据，请基于对话内容回答，不要提及缺乏数据："
        messages.append({"role": "system", "content": prefix + "\n" + "\n".join(ctx_parts)})
    elif not allow_user_self_context:
        messages.append({
            "role": "system",
            "content": "本轮没有可用于当前主体的授权健康数据。请直接回答当前问题，不能要求用户补交已无关的本人数据。",
        })
    else:
        messages.append({"role": "system", "content": "该用户是新用户，暂无健康数据。请直接回答问题，自然地了解用户情况，不要提及缺乏数据。"})

    # Cross-conversation memory: recent conversation summaries
    conv_summaries = context.get("recent_conversation_summaries") or []
    if conv_summaries:
        memory_parts = []
        for cs in conv_summaries[:3]:
            title = cs.get("conv_title", "对话")
            ts = cs.get("updated_at", "")[:10]
            for m in cs.get("messages", []):
                snippet = m.get("content", "")
                if snippet:
                    memory_parts.append(f"[{ts}] {title}: {snippet}")
        if memory_parts:
            messages.append({
                "role": "system",
                "content": "以下是用户近期的对话历史摘要，请在回答时参考这些上下文保持连贯性:\n" + "\n".join(memory_parts)
            })

    # Append conversation history (max last 20 messages)
    history_for_prompt = _history_for_prompt(
        history or [],
        allow_user_self_context=allow_user_self_context,
        message_structure=prompt_message_structure,
    )
    if history_for_prompt:
        for msg in history_for_prompt[-20:]:
            messages.append({"role": msg["role"], "content": msg["content"]})

    messages.append({"role": "user", "content": user_query})
    return messages


def _sanitize_message_structure_for_prompt(message_structure: dict, *, allow_user_self_context: bool) -> dict:
    if allow_user_self_context or not message_structure:
        return message_structure

    sanitized = copy.deepcopy(message_structure)
    data_source_memory = sanitized.get("data_source_memory") or {}
    sanitized["data_source_memory"] = {
        "sources": [],
        "metrics": [],
        "connected": {},
        "forbidden_questions": data_source_memory.get("forbidden_questions") or [],
        "metric_conflicts": [],
        "source_interpretation_rules": [
            "本轮问题主体不是登录用户本人；不能把当前账号的数据源、指标或冲突当成该主体数据。",
        ],
    }
    sanitized["health_fact_index"] = {
        "facts": [],
        "rules": [
            "本轮没有当前主体的授权入库健康事实。",
            "如果用户只提供家属/他人问题，回答只能使用本轮文字和通用医学知识。",
        ],
    }
    sanitized["report_status"] = {
        "documents": [],
        "pending_count": 0,
        "done_count": 0,
        "failed_count": 0,
        "latest": None,
        "rules": ["当前主体不是登录用户本人，报告状态不适用于该主体，除非用户明确上传该主体资料。"],
    }
    session_memory = sanitized.get("session_memory") or {}
    sanitized["session_memory"] = {
        **session_memory,
        "covered_facts": [],
        "avoid_repeating": [],
        "rules": [
            "非本人主体时，不把前文关于登录用户本人的指标当作本轮事实。",
            "只保留用户明确说出的主体纠正和本轮相同主体信息。",
        ],
    }
    return sanitized


def _history_for_prompt(
    history: list[dict],
    *,
    allow_user_self_context: bool,
    message_structure: dict,
) -> list[dict]:
    if allow_user_self_context:
        return history
    if not history:
        return []

    subject = message_structure.get("active_subject") or {}
    relation = subject.get("relation") or ""
    relation_terms = {
        "wife": ["老婆", "妻子", "太太", "媳妇", "爱人", "她"],
        "husband": ["老公", "丈夫", "先生", "他"],
        "mother": ["我妈", "妈妈", "母亲", "老妈", "她"],
        "father": ["我爸", "爸爸", "父亲", "老爸", "他"],
        "child": ["孩子", "儿子", "女儿", "小孩"],
    }.get(relation, [])
    concept_terms = _concept_terms(message_structure)
    keep_terms = [term.lower() for term in relation_terms + concept_terms if term]

    filtered: list[dict] = []
    for msg in history[-12:]:
        if msg.get("role") != "user":
            continue
        content = msg.get("content") or ""
        normalized = content.lower()
        if keep_terms and any(term in normalized for term in keep_terms):
            filtered.append({"role": "user", "content": content})
    return filtered


def _concept_terms(message_structure: dict) -> list[str]:
    keys = (message_structure.get("health_nlu") or {}).get("concept_keys") or []
    mapping = {
        "nt": ["nt", "颈项透明层"],
        "nipt": ["nipt", "无创"],
        "crl": ["crl", "头臀长"],
        "pregnancy": ["怀孕", "孕", "妊娠"],
        "glucose": ["血糖", "glucose"],
        "tir": ["tir"],
        "blood_pressure": ["血压"],
        "uric_acid": ["尿酸"],
    }
    terms: list[str] = []
    for key in keys:
        terms.extend(mapping.get(key, []))
    return terms


def _fix_json_string(text: str) -> str:
    """Fix common LLM JSON issues: unescaped newlines/tabs inside string values."""
    # Replace actual newlines/tabs inside JSON string values with escape sequences
    # Strategy: process char-by-char, track whether we're inside a JSON string
    result = []
    in_string = False
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == '"' and (i == 0 or text[i - 1] != '\\'):
            in_string = not in_string
            result.append(ch)
        elif in_string and ch == '\n':
            result.append('\\n')
        elif in_string and ch == '\r':
            result.append('\\r')
        elif in_string and ch == '\t':
            result.append('\\t')
        else:
            result.append(ch)
        i += 1
    return ''.join(result)


def _try_parse_json(text: str) -> dict | None:
    """Try to parse JSON, with fallback to fix unescaped newlines."""
    # Direct parse
    try:
        data = json.loads(text)
        if isinstance(data, dict) and "summary" in data:
            return data
    except json.JSONDecodeError:
        pass
    # Fix unescaped newlines and retry
    try:
        fixed = _fix_json_string(text)
        data = json.loads(fixed)
        if isinstance(data, dict) and "summary" in data:
            return data
    except json.JSONDecodeError:
        pass
    return None


def _parse_structured_response(raw: str) -> dict:
    """Parse GPT's JSON response into summary + analysis.

    Falls back gracefully if GPT doesn't follow the JSON format.
    """
    text = raw.strip()

    # Strategy 1: Direct JSON parse
    result = _try_parse_json(text)
    if result:
        return result

    # Strategy 2: Extract from markdown code block
    if "```" in text:
        try:
            block = text.split("```json")[-1].split("```")[0].strip() if "```json" in text else text.split("```")[1].split("```")[0].strip()
            result = _try_parse_json(block)
            if result:
                return result
        except IndexError:
            pass

    # Strategy 3: Find outermost JSON object
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        result = _try_parse_json(text[start:end + 1])
        if result:
            return result

    # Strategy 4: Regex extraction as last resort
    summary_m = re.search(r'"summary"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
    analysis_m = re.search(r'"analysis"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
    if summary_m:
        return {
            "summary": summary_m.group(1).replace("\\n", "\n").replace('\\"', '"'),
            "analysis": analysis_m.group(1).replace("\\n", "\n").replace('\\"', '"') if analysis_m else "",
            "followups": [],
            "profile_extracted": {},
        }

    # Fallback: use entire response as summary (strip markdown fences)
    clean = re.sub(r'```json\s*', '', text)
    clean = re.sub(r'```\s*', '', clean)
    return {"summary": clean, "analysis": clean, "followups": [], "profile_extracted": {}}



class OpenAIProvider(LLMProvider):
    provider_name = "openai"
    text_model = settings.OPENAI_MODEL_TEXT
    vision_model = settings.OPENAI_MODEL_VISION

    def __init__(self) -> None:
        kwargs: dict = {"api_key": settings.OPENAI_API_KEY}
        if settings.OPENAI_BASE_URL:
            kwargs["base_url"] = settings.OPENAI_BASE_URL
        self._client = OpenAI(**kwargs)

    def analyze_image(self, image_url: str) -> MealVisionResult:
        """Analyze a meal photo using Kimi K2.5 vision.

        提示词极度简化：LLM 仅需返回 ``{"name": str|null, "kcal": int}``，不是食物时
        ``name=null`` 且 ``kcal=0``。本地路径会被转为 base64 data URL避免外网依赖。
        """
        try:
            payload_url = self._to_inline_data_url(image_url)
            response = self._client.chat.completions.create(
                model=self.vision_model,
                messages=[
                    {"role": "system", "content": (
                        "你是食物识别器。仅返回严格 JSON，不要任何额外文字。\n"
                        "格式：{\"name\": \"食物名称\", \"kcal\": 整数}\n"
                        "如果图片不是食物（人/风景/物品/截图/文档等），返回："
                        "{\"name\": null, \"kcal\": 0}\n"
                        "名称要简洁中文，如：\"牛肉面\"、\"香蕉\"、\"拿铁哖东哥哦奥哦\"；kcal 是总热量估计。"
                    )},
                    {"role": "user", "content": [
                        {"type": "image_url", "image_url": {"url": payload_url}},
                        {"type": "text", "text": "识别这张图片。"},
                    ]},
                ],
                max_tokens=256,
                extra_body={"thinking": {"type": "disabled"}},
                **settings.llm_temperature_kwargs(settings.OPENAI_MODEL_VISION),
            )
            # Extract token usage
            usage = getattr(response, "usage", None)
            prompt_tokens = getattr(usage, "prompt_tokens", None) if usage else None
            completion_tokens = getattr(usage, "completion_tokens", None) if usage else None

            raw = response.choices[0].message.content or "{}"
            # Try to parse JSON from the response
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                # Try to extract JSON from markdown code block
                if "```" in raw:
                    raw = raw.split("```json")[-1].split("```")[0].strip()
                    data = json.loads(raw)
                else:
                    raise

            items: list[MealVisionItem] = []
            name = data.get("name")
            try:
                kcal = int(data.get("kcal") or 0)
            except (TypeError, ValueError):
                kcal = 0
            is_food = bool(name) and kcal > 0
            if is_food:
                items = [MealVisionItem(name=str(name).strip(), portion_text="1 份", kcal=kcal)]
            return MealVisionResult(
                items=items,
                total_kcal=kcal if is_food else 0,
                confidence=0.9 if is_food else 0.0,
                notes="" if is_food else "non-food or unrecognized",
                is_food=is_food,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )
        except Exception as e:
            logger.error("OpenAI vision analysis failed: %s", e)
            return MealVisionResult(
                items=[], total_kcal=0, confidence=0.0,
                notes=f"Vision error: {e}", is_food=False,
            )

    @staticmethod
    def _to_inline_data_url(image_url: str) -> str:
        """将本地路径或 file:// URL 读出并转为 base64 data URL。已经是 http(s)/data: 直接原样返回。"""
        import base64
        import mimetypes
        import os
        from urllib.parse import urlparse

        if image_url.startswith(("http://", "https://", "data:")):
            return image_url

        path = image_url
        if image_url.startswith("file://"):
            path = urlparse(image_url).path

        # 若是相对 object_key（如 meals/8/xxx.jpg），尝试拼到 LOCAL_STORAGE_DIR
        if not os.path.isabs(path):
            path = os.path.join(settings.LOCAL_STORAGE_DIR, path)

        mime, _ = mimetypes.guess_type(path)
        mime = mime or "image/jpeg"
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
        return f"data:{mime};base64,{b64}"

    def generate_text(self, context: dict, user_query: str, *, history: list[dict] | None = None, skill_prompt: str = "") -> ChatLLMResult:
        """Generate a complete text response. Uses thinking mode for health queries."""
        try:
            messages = _build_messages(context, user_query, history=history, skill_prompt=skill_prompt)
            is_health = _is_health_query(user_query, history)

            # kimi-k2.5 defaults to thinking enabled; disable for non-health queries
            extra: dict = {}
            if not is_health:
                extra["extra_body"] = {"thinking": {"type": "disabled"}}

            response = self._client.chat.completions.create(
                model=self.text_model,
                messages=messages,
                max_tokens=16000 if is_health else 4096,
                **settings.llm_temperature_kwargs(self.text_model),
                **extra,
            )
            # Extract token usage
            usage = getattr(response, "usage", None)
            prompt_tokens = getattr(usage, "prompt_tokens", None) if usage else None
            completion_tokens = getattr(usage, "completion_tokens", None) if usage else None

            raw = response.choices[0].message.content or ""
            parsed = _parse_structured_response(raw)
            return ChatLLMResult(
                answer_markdown=raw,
                confidence=0.85,
                followups=parsed.get("followups", []),
                safety_flags=[],
                summary=parsed.get("summary", ""),
                analysis=parsed.get("analysis", ""),
                profile_extracted=parsed.get("profile_extracted", {}),
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )
        except Exception as e:
            logger.error("OpenAI generate_text failed: %s", e)
            return ChatLLMResult(
                answer_markdown=f"抱歉，AI 暂时无法回答。错误信息: {e}",
                confidence=0.0,
                followups=["请稍后再试"],
                safety_flags=["provider_error"],
                summary="AI 暂时无法回答",
                analysis=f"错误信息: {e}",
            )

    def stream_text(self, context: dict, user_query: str, *, history: list[dict] | None = None, skill_prompt: str = "") -> Iterator[str]:
        """Stream text token-by-token. Uses thinking mode for health queries."""
        try:
            messages = _build_messages(context, user_query, history=history, skill_prompt=skill_prompt)
            is_health = _is_health_query(user_query, history)

            extra: dict = {}
            if not is_health:
                extra["extra_body"] = {"thinking": {"type": "disabled"}}

            stream = self._client.chat.completions.create(
                model=self.text_model,
                messages=messages,
                max_tokens=16000 if is_health else 4096,
                **settings.llm_temperature_kwargs(self.text_model),
                stream=True,
                **extra,
            )
            for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta and delta.content:
                    yield delta.content
        except Exception as e:
            logger.error("OpenAI stream_text failed: %s", e)
            yield f"\n\nAI 流式响应失败: {e}"
