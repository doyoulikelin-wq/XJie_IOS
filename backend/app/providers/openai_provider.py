from __future__ import annotations

import copy
import json
import logging
import re
from typing import Iterator

from openai import OpenAI

from app.core.config import settings
from app.providers.base import (
    ChatLLMResult,
    LLMProvider,
    MealTextItem,
    MealTextResult,
    MealVisionItem,
    MealVisionResult,
)
from app.services.health_nlu import analyze_health_message, concept_alias_groups
from app.services.response_completeness import response_incompleteness_reasons

logger = logging.getLogger(__name__)

# ── Health/medical topic detection ────────────────────────────

_HEALTH_KEYWORDS = re.compile(
    r"血糖|血压|血脂|胆固醇|甘油三酯|糖化血红蛋白|BMI|体重|肥胖|脂肪肝|"
    r"糖尿病|胰岛素|代谢|尿酸|痛风|心血管|冠心病|高血压|低血糖|"
    r"HRV|心率变异|NT|颈项透明层|头疼|头痛|失眠|胃痛|腹泻|便秘|恶心|呕吐|发烧|咳嗽|"
    r"感冒|过敏|鼻炎|脊柱侧弯|缺氧|低氧|皮疹|水肿|疲劳|乏力|胸闷|心悸|头晕|"
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
        logger.debug(
            "health_nlu detection failed; falling back to regex", exc_info=True
        )
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
   - health_nlu.primary_intent = symptom_triage 时，先筛与该症状直接相关的急症红旗和观察窗口，再给居家处理；不能把胸痛、呼吸困难、昏厥、卒中信号当普通症状，也不能因少数红旗被否认就宣称“已排除严重问题”。
   - health_nlu.primary_intent = lifestyle_coaching 时，把饮食、运动、饮水、酒精、咖啡因、吸烟和作息转成 1-3 个可执行动作，结合已有数据，不空泛说教。
   - health_nlu.primary_intent = mental_health_support 时，先回应压力/情绪，再筛自伤念头、惊恐发作和功能受损；出现危机信号必须建议立即求助。
   - health_nlu.primary_intent = causal_assessment 时，必须覆盖 health_nlu.compound_assessment.concepts 中每个因素。先直接回答是否存在关联，再逐条区分“已有研究支持的关联”“生理上可能的机制”“该用户本人尚未证实的环节”；不能把相关性直接写成确定病因。
   - 只在 health_nlu.compound_assessment.hypoxia_boundary_required = true 时加入缺氧边界：明确现有信息不能确认已经缺氧，也不能把其他症状直接归因于尚未证实的缺氧。不得添加 health_nlu.compound_assessment.concepts 和 evaluation_requirements 中没有出现的疾病、指标或检查。
   - causal_assessment 的下一步必须按 health_nlu.compound_assessment.evaluation_requirements 选择能改变判断的客观记录或评估，并明确哪些结果支持或反对对应因果链；该列表由后端按本轮概念生成，不能添加未命中的疾病或检查。
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
   - response_plan.evidence_sufficiency 是纵向结论的硬门槛。status 不是 sufficient 时，禁止描述稳定、上升、下降、波动或“几天偏高/偏低”。
   - status = sufficient 时，也只能引用 recent_samples 和 computed_range 中实际存在的样本数、范围与首末变化，不能虚构未提供的日期或异常天数。

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
  "summary": "完整的主要回复（长度按 response_plan 和 interaction_route 控制，不能截断）",
  "analysis": "详细分析（Markdown 格式，按问题复杂度包含原因、建议和必要的数据引用）",
  "followups": ["用户可能想继续问的话1", "用户可能想继续问的话2"],
  "profile_extracted": {}
}
```

### summary 规范（极其重要）:
summary 是用户直接看到的主要回复内容，必须完整、不能截断。
除纯状态快答外，优先包含以下三要素：
1. **是什么** — 简要说明原因或情况
2. **怎么办** — 给出 1-2 个具体可行建议
3. **必要追问** — 只有缺失信息会改变判断时，提出一个具体问题；信息已经足够时直接结束，不使用邀请式套话

示例:
- "昨晚睡眠不足可以诱发头痛。先补水、进食并在安静环境休息；若突然出现一生最严重头痛、发热伴颈部僵硬、反复呕吐或神经症状，立即就医。"
- "已入库的7天数据中，晚餐后是主要波动时段，TIR 为 65%。先把晚餐主食减少约 1/3，并连续记录 3 天餐后 2 小时血糖，再比较变化。"

### followups 规则:
followups 是**用户的快捷回复选项**，必须站在用户角度写:
- 正确: "帮我看看哪顿饭影响血糖最大", "我最近睡眠不太好"
- 错误: "头疼是持续的还是间歇的？"（这是 AI 提问口吻，不可用）

### 绝对不要:
- 使用任何 emoji 符号
- 用"缺乏数据无法判断"、"建议补充数据"敷衍用户；数据不足时必须明确现有信息能判断什么、缺少哪一项、如何获得，不能编数字
- 为了显得完整而重复背景、建议或安全提示
- followups 写成 AI 提问的口吻
- 忽略 message_structure 的主体、禁止问题和 blocked_context
- 在家人/妻子问题中混入用户本人的健康指标
- 对已经同步的硬件/Apple 健康数据继续反问是否佩戴或是否同步
- 用“促进血液循环、排毒、调理”等无法由当前信息验证的机制包装建议
- 在正文没有使用 [N] 角标时展示或暗示对应文献；文献只支持其 claim_text 对应的具体结论，不能跨主题借用
- 因用户否认一两个红旗信号就宣称已排除严重疾病或绝对安全
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
    prompt_message_structure = _project_message_structure_for_prompt(
        prompt_message_structure
    )
    if message_structure:
        messages.append(
            {
                "role": "system",
                "content": (
                    "以下是后端已解析的用户消息结构。必须严格按 active_subject、intent、"
                    "health_nlu、data_source_memory、session_memory 和 response_plan 回答；不得违反 "
                    "forbidden_questions 与 blocked_context。\n"
                    + json.dumps(
                        prompt_message_structure, ensure_ascii=False, default=str
                    )
                ),
            }
        )
        route = message_structure.get("interaction_route") or {}
        repetition = (message_structure.get("session_memory") or {}).get(
            "repetition_policy"
        ) or {}
        if repetition.get("mode") == "delta_only":
            length_rule = "本轮是连续追问：summary 30-140 字，只回答新增判断；analysis 只补新增依据和下一步。"
        elif route.get("depth") == "deep":
            length_rule = "本轮是深度分析：summary 80-220 字；analysis 300-900 字，分层说明结论、依据和行动。"
        else:
            length_rule = "本轮是标准回答：summary 40-180 字；analysis 150-500 字，不重复用户已知背景。"
        messages.append({"role": "system", "content": length_rule})
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
            "trusted_health_context": {},
            "recent_conversation_summaries": [],
        }
        subject = (message_structure.get("active_subject") or {}).get("display", "他人")
        messages.append(
            {
                "role": "system",
                "content": (
                    f"本轮问题主体是{subject}，不是当前登录用户本人。"
                    "后端已屏蔽本人健康数据；回答只能使用用户本轮提供的信息、"
                    "会话纠正和通用医学知识。"
                ),
            }
        )

    context = _scope_context_for_prompt(context, prompt_message_structure)

    # Inject user context as a system message
    ctx_parts = []
    has_real_data = False

    # Glucose summary
    g = context.get("glucose_summary") or context.get("glucose") or {}
    for label, key in [("过去24h", "last_24h"), ("过去7天", "last_7d")]:
        d = g.get(key) or {}
        if d.get("avg") is not None:
            has_real_data = True
            ctx_parts.append(
                f"血糖({label}): 均值={d['avg']}mg/dL, TIR(70-180)={d.get('tir_70_180_pct')}%, 变异性={d.get('variability')}"
            )

    # Daily calories
    dq = context.get("data_quality") or {}
    kcal = dq.get("kcal_today") if dq else context.get("kcal_today")
    if kcal and kcal > 0:
        has_real_data = True
        ctx_parts.append(f"今日热量: {kcal} kcal")

    if context.get("meals_today"):
        has_real_data = True
        meals = context["meals_today"]
        ctx_parts.append(
            f"今日进餐 {len(meals)} 次: "
            + ", ".join(f"{m.get('kcal', '?')}kcal@{m.get('ts', '?')}" for m in meals)
        )

    if context.get("symptoms_last_7d"):
        symptoms = context["symptoms_last_7d"]
        ctx_parts.append(
            f"近7天症状 {len(symptoms)} 条: "
            + ", ".join(
                f"{s.get('text', '')}(严重度{s.get('severity', '?')})"
                for s in symptoms[:5]
            )
        )

    if context.get("agent_features"):
        ctx_parts.append(
            f"Agent特征: {json.dumps(context['agent_features'], ensure_ascii=False)}"
        )

    # User profile
    profile = context.get("user_profile_info") or {}
    if profile:
        ctx_parts.append(f"用户画像: {json.dumps(profile, ensure_ascii=False)}")

    trusted_health = context.get("trusted_health_context") or {}
    confirmed_facts = trusted_health.get("profile_facts") or []
    if confirmed_facts:
        has_real_data = True
        ctx_parts.append(
            "已确认健康画像事实:\n"
            + json.dumps(confirmed_facts[:60], ensure_ascii=False, default=str)
        )
    confirmed_goals = trusted_health.get("goals") or []
    if confirmed_goals:
        ctx_parts.append(
            "用户主动确认的健康目标:\n"
            + json.dumps(confirmed_goals[:20], ensure_ascii=False, default=str)
        )

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
        prefix = (
            "以下是该用户的健康数据，回答时必须主动引用相关数据："
            if has_real_data
            else "该用户暂无设备数据，请基于对话内容回答，不要提及缺乏数据："
        )
        messages.append(
            {"role": "system", "content": prefix + "\n" + "\n".join(ctx_parts)}
        )
    elif not allow_user_self_context:
        messages.append(
            {
                "role": "system",
                "content": "本轮没有可用于当前主体的授权健康数据。请直接回答当前问题，不能要求用户补交已无关的本人数据。",
            }
        )
    else:
        messages.append(
            {
                "role": "system",
                "content": "该用户是新用户，暂无健康数据。请直接回答问题，自然地了解用户情况，不要提及缺乏数据。",
            }
        )

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
            messages.append(
                {
                    "role": "system",
                    "content": "以下是用户近期的对话历史摘要，请在回答时参考这些上下文保持连贯性:\n"
                    + "\n".join(memory_parts),
                }
            )

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


_CATEGORY_METRIC_TERMS: dict[str, tuple[str, ...]] = {
    "cardiovascular_vitals": (
        "血压",
        "收缩压",
        "舒张压",
        "心率",
        "静息心率",
        "hrv",
        "心率变异",
        "血氧",
        "spo2",
        "呼吸率",
        "呼吸频率",
        "心电",
    ),
    "glucose_metabolic": ("血糖", "glucose", "tir", "糖化", "hba1c", "胰岛素"),
    "renal_uric": (
        "尿酸",
        "肌酐",
        "egfr",
        "胱抑素",
        "尿素",
        "尿蛋白",
        "白蛋白尿",
        "血尿",
    ),
    "liver_lipids": (
        "alt",
        "ast",
        "ggt",
        "胆红素",
        "脂肪肝",
        "甘油三酯",
        "ldl",
        "hdl",
        "胆固醇",
        "apob",
        "脂蛋白",
    ),
    "inflammation_immune": (
        "crp",
        "炎症",
        "白细胞",
        "中性粒",
        "淋巴",
        "nlr",
        "il-6",
        "il6",
        "铁蛋白",
    ),
    "sleep_recovery": (
        "睡眠",
        "深睡",
        "rem",
        "清醒",
        "恢复",
        "压力",
        "hrv",
        "静息心率",
        "体温",
        "腕温",
    ),
    "respiratory_sleep": (
        "鼻炎",
        "鼻塞",
        "睡眠呼吸",
        "呼吸暂停",
        "打鼾",
        "缺氧",
        "低氧",
        "血氧",
        "spo2",
    ),
    "musculoskeletal_respiratory": ("脊柱侧弯", "脊柱侧凸", "肺功能", "胸廓", "呼吸"),
    "mental_wellbeing": ("抑郁", "情绪低落", "焦虑", "情绪", "心理"),
    "body_activity": ("体重", "bmi", "体脂", "腰围", "步数", "运动", "活动能量", "vo2"),
    "endocrine_nutrition": ("tsh", "t3", "t4", "维生素", "叶酸", "贫血", "血红蛋白"),
}


def _project_message_structure_for_prompt(message_structure: dict) -> dict:
    if not message_structure:
        return {}
    projected = copy.deepcopy(message_structure)
    nlu = projected.get("health_nlu") or {}
    primary_intent = nlu.get("primary_intent") or "general_chat"
    categories = set(nlu.get("semantic_categories") or [])
    terms = _relevant_metric_terms(nlu)
    keep_all_facts = (
        primary_intent in {"report_summary", "medical_question"} and not terms
    )

    fact_index = projected.get("health_fact_index") or {}
    facts = fact_index.get("facts") or []
    fact_index["facts"] = [
        fact
        for fact in facts
        if keep_all_facts or _metric_matches_terms(fact.get("metric"), terms)
    ][:24]
    projected["health_fact_index"] = fact_index

    data_memory = projected.get("data_source_memory") or {}
    metrics = data_memory.get("metrics") or []
    data_memory["metrics"] = [
        metric
        for metric in metrics
        if keep_all_facts or _metric_matches_terms(metric.get("metric"), terms)
    ][:24]
    conflicts = data_memory.get("metric_conflicts") or []
    data_memory["metric_conflicts"] = [
        conflict
        for conflict in conflicts
        if keep_all_facts or _metric_matches_terms(conflict.get("metric"), terms)
    ][:6]
    for source in data_memory.get("sources") or []:
        available = source.get("available_metrics") or []
        source["available_metrics"] = [
            metric
            for metric in available
            if keep_all_facts or _metric_matches_terms(metric, terms)
        ][:12]
    projected["data_source_memory"] = data_memory

    report_status = projected.get("report_status") or {}
    if (
        primary_intent not in {"report_summary", "upload_intent", "report_status_query"}
        and "reports_tasks_devices" not in categories
    ):
        report_status["documents"] = []
        report_status["latest"] = None
    projected["report_status"] = report_status
    return projected


def _scope_context_for_prompt(context: dict, message_structure: dict) -> dict:
    scoped = dict(context)
    nlu = message_structure.get("health_nlu") or {}
    intent = message_structure.get("intent") or {}
    primary_intent = (
        nlu.get("primary_intent") or intent.get("semantic_intent") or "general_chat"
    )
    categories = set(nlu.get("semantic_categories") or [])
    concept_keys = set(nlu.get("concept_keys") or [])
    normalized_query = str(nlu.get("normalized_query") or "")

    uses_glucose = bool(
        categories.intersection({"glucose_metabolic"})
        or concept_keys.intersection({"glucose", "tir", "hba1c", "cgm"})
    )
    uses_daily_logs = primary_intent == "lifestyle_coaching" or bool(
        categories.intersection({"lifestyle_nutrition", "body_activity"})
    )
    uses_symptoms = primary_intent in {
        "symptom_triage",
        "mental_health_support",
        "causal_assessment",
        "emergency_triage",
    }
    uses_reports = primary_intent in {"report_summary", "upload_intent"}
    uses_omics = bool(
        re.search(r"组学|代谢组|蛋白组|基因", normalized_query, re.IGNORECASE)
    )

    if not uses_glucose:
        scoped["glucose_summary"] = {}
        scoped["glucose"] = {}
    if not uses_daily_logs:
        scoped["meals_today"] = []
        scoped["data_quality"] = {}
        scoped["kcal_today"] = 0
    if not uses_symptoms:
        scoped["symptoms_last_7d"] = []
    if not uses_reports:
        scoped["health_report_text"] = ""
        scoped["health_summary_text"] = ""
    if not uses_omics:
        scoped["omics_analyses"] = []

    scoped["recent_conversation_summaries"] = _relevant_conversation_summaries(
        scoped.get("recent_conversation_summaries") or [],
        terms=_relevant_metric_terms(nlu),
        keep_general=not bool(nlu.get("concept_keys")),
    )
    return scoped


def _relevant_metric_terms(nlu: dict) -> set[str]:
    terms: set[str] = set()
    for item in nlu.get("matched_concepts") or []:
        terms.add(str(item.get("display") or "").lower())
        terms.add(str(item.get("key") or "").lower())
        terms.update(str(alias).lower() for alias in item.get("matched_aliases") or [])
    for category in nlu.get("semantic_categories") or []:
        terms.update(term.lower() for term in _CATEGORY_METRIC_TERMS.get(category, ()))
    return {re.sub(r"\s+", "", term) for term in terms if term}


def _metric_matches_terms(metric: object, terms: set[str]) -> bool:
    if not terms:
        return False
    normalized = re.sub(r"\s+", "", str(metric or "").lower())
    return bool(
        normalized and any(term in normalized or normalized in term for term in terms)
    )


def _relevant_conversation_summaries(
    items: list[dict], *, terms: set[str], keep_general: bool
) -> list[dict]:
    if keep_general:
        return items[:2]
    result = []
    for conversation in items:
        messages = conversation.get("messages") or []
        text = re.sub(
            r"\s+",
            "",
            " ".join(str(message.get("content") or "") for message in messages).lower(),
        )
        if text and any(term in text for term in terms):
            result.append(conversation)
        if len(result) >= 2:
            break
    return result


def _sanitize_message_structure_for_prompt(
    message_structure: dict, *, allow_user_self_context: bool
) -> dict:
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
        "rules": [
            "当前主体不是登录用户本人，报告状态不适用于该主体，除非用户明确上传该主体资料。"
        ],
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
        if ch == '"' and (i == 0 or text[i - 1] != "\\"):
            in_string = not in_string
            result.append(ch)
        elif in_string and ch == "\n":
            result.append("\\n")
        elif in_string and ch == "\r":
            result.append("\\r")
        elif in_string and ch == "\t":
            result.append("\\t")
        else:
            result.append(ch)
        i += 1
    return "".join(result)


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


def _repair_smart_json_quotes(text: str) -> str:
    """Repair structural Chinese smart quotes without rewriting quoted prose."""

    repaired = re.sub(
        r"“([A-Za-z_][A-Za-z0-9_]*)”(?=\s*[:：])",
        lambda match: json.dumps(match.group(1), ensure_ascii=False),
        text,
    )
    repaired = re.sub(
        r"“([\s\S]*?)”(?=\s*(?:[,，}\]]))",
        lambda match: json.dumps(match.group(1), ensure_ascii=False),
        repaired,
    )
    repaired = re.sub(r'(?<=")\s*：', ":", repaired)
    repaired = re.sub(r'(?<=")\s*，(?=\s*["}])', ",", repaired)
    return repaired


def _normalize_parsed_payload(data: dict, *, parse_status: str) -> dict:
    summary = data.get("summary")
    analysis = data.get("analysis")
    followups = data.get("followups")
    profile = data.get("profile_extracted")
    return {
        "summary": str(summary).strip() if isinstance(summary, str) else "",
        "analysis": str(analysis).strip() if isinstance(analysis, str) else "",
        "followups": [str(item).strip() for item in followups if str(item).strip()]
        if isinstance(followups, list)
        else [],
        "profile_extracted": profile if isinstance(profile, dict) else {},
        "_parse_status": parse_status,
    }


def _parse_candidate(text: str) -> dict | None:
    result = _try_parse_json(text)
    if result:
        return _normalize_parsed_payload(result, parse_status="valid")
    repaired = _repair_smart_json_quotes(text)
    if repaired != text:
        result = _try_parse_json(repaired)
        if result:
            return _normalize_parsed_payload(result, parse_status="repaired")
    return None


def _parse_structured_response(raw: str) -> dict:
    """Parse GPT's JSON response into summary + analysis.

    Falls back gracefully if GPT doesn't follow the JSON format.
    """
    text = raw.strip()

    # Strategy 1: Direct JSON parse
    result = _parse_candidate(text)
    if result:
        return result

    # Strategy 2: Extract from markdown code block
    if "```" in text:
        try:
            block = (
                text.split("```json")[-1].split("```")[0].strip()
                if "```json" in text
                else text.split("```")[1].split("```")[0].strip()
            )
            result = _parse_candidate(block)
            if result:
                return result
        except IndexError:
            pass

    # Strategy 3: Find outermost JSON object
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        result = _parse_candidate(text[start : end + 1])
        if result:
            return result

    # Strategy 4: Regex extraction as last resort
    summary_m = re.search(r'"summary"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
    analysis_m = re.search(r'"analysis"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
    if summary_m:
        return {
            "summary": summary_m.group(1).replace("\\n", "\n").replace('\\"', '"'),
            "analysis": analysis_m.group(1).replace("\\n", "\n").replace('\\"', '"')
            if analysis_m
            else "",
            "followups": [],
            "profile_extracted": {},
            "_parse_status": "partial_repair",
        }

    smart_summary = re.search(
        r'[“"]summary[”"]\s*[:：]\s*“([\s\S]*?)”(?=\s*[,，}])', text
    )
    smart_analysis = re.search(
        r'[“"]analysis[”"]\s*[:：]\s*“([\s\S]*?)”(?=\s*[,，}])', text
    )
    if smart_summary:
        return {
            "summary": smart_summary.group(1).strip(),
            "analysis": smart_analysis.group(1).strip() if smart_analysis else "",
            "followups": [],
            "profile_extracted": {},
            "_parse_status": "partial_repair",
        }

    # Never surface a malformed serialized object as chat prose.
    if start != -1 or re.search(
        r'["“](?:summary|analysis|followups)["”]\s*[:：]', text
    ):
        return {
            "summary": "这次回答没有完整生成，请稍后重试。",
            "analysis": "模型返回格式异常，你的消息和当前会话已经保留。",
            "followups": ["重新生成这条回答"],
            "profile_extracted": {},
            "_parse_status": "invalid",
        }

    # Plain text remains usable when the provider ignores the JSON contract entirely.
    clean = re.sub(r"```json\s*", "", text)
    clean = re.sub(r"```\s*", "", clean)
    return {
        "summary": clean,
        "analysis": clean,
        "followups": [],
        "profile_extracted": {},
        "_parse_status": "plain_text",
    }


class OpenAIProvider(LLMProvider):
    provider_name = "openai"
    text_model = settings.OPENAI_MODEL_TEXT
    vision_model = settings.OPENAI_MODEL_VISION

    def __init__(self) -> None:
        kwargs: dict = {"api_key": settings.OPENAI_API_KEY}
        if settings.OPENAI_BASE_URL:
            kwargs["base_url"] = settings.OPENAI_BASE_URL
        self._client = OpenAI(**kwargs)

    def analyze_meal_text(self, raw_text: str) -> MealTextResult:
        """Extract an editable meal candidate without creating a formal record."""

        if not raw_text.strip():
            return MealTextResult(recognized=False, notes="manual entry required")
        try:
            response = self._client.chat.completions.create(
                model=self.text_model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "你是膳食记录结构化提取器，只返回严格 JSON。不得给健康建议，不得补写用户"
                            '没有说过的食物。格式：{"meal_type":"breakfast|lunch|dinner|snack|null",'
                            '"items":[{"name":"食物","portion_text":"份量或null",'
                            '"categories":["staple|protein|vegetable|fruit|dairy|beverage|other"],'
                            '"confidence":0到1}],"portion_text":null,"structure":{},'
                            '"estimated_nutrition":{"energy_kcal_range":[下限,上限],'
                            '"is_estimate":true},"field_confidences":{"food_items":0到1,'
                            '"portion_text":0到1,"meal_type":0到1},"confidence":0到1}。'
                            "无法识别时 items 返回空数组；所有营养只能是范围估算。"
                        ),
                    },
                    {"role": "user", "content": raw_text[:4000]},
                ],
                max_tokens=1200,
                extra_body={"thinking": {"type": "disabled"}},
                **settings.llm_temperature_kwargs(self.text_model),
            )
            usage = getattr(response, "usage", None)
            raw = response.choices[0].message.content or "{}"
            if "```" in raw:
                fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, re.DOTALL)
                if fenced:
                    raw = fenced.group(1)
            data = json.loads(raw)
            allowed_meal_types = {"breakfast", "lunch", "dinner", "snack"}
            meal_type = data.get("meal_type")
            if meal_type not in allowed_meal_types:
                meal_type = None

            items: list[MealTextItem] = []
            for candidate in (data.get("items") or [])[:64]:
                if not isinstance(candidate, dict):
                    continue
                name = str(candidate.get("name") or "").strip()
                if not name or len(name) > 160:
                    continue
                portion = candidate.get("portion_text")
                portion = str(portion).strip()[:160] if portion else None
                categories = [
                    str(value).strip()[:40]
                    for value in (candidate.get("categories") or [])[:12]
                    if str(value).strip()
                ]
                confidence = max(0.0, min(1.0, float(candidate.get("confidence") or 0)))
                items.append(
                    MealTextItem(
                        name=name,
                        portion_text=portion,
                        categories=categories,
                        confidence=confidence,
                    )
                )

            field_confidences = {
                str(key)[:80]: max(0.0, min(1.0, float(value)))
                for key, value in (data.get("field_confidences") or {}).items()
            }
            confidence = max(0.0, min(1.0, float(data.get("confidence") or 0)))
            return MealTextResult(
                items=items,
                meal_type=meal_type,
                portion_text=(
                    str(data.get("portion_text")).strip()[:256]
                    if data.get("portion_text")
                    else None
                ),
                structure=data.get("structure")
                if isinstance(data.get("structure"), dict)
                else {},
                estimated_nutrition=(
                    data.get("estimated_nutrition")
                    if isinstance(data.get("estimated_nutrition"), dict)
                    else {}
                ),
                field_confidences=field_confidences,
                confidence=confidence,
                recognized=bool(items),
                notes="" if items else "manual entry required",
                prompt_tokens=getattr(usage, "prompt_tokens", None) if usage else None,
                completion_tokens=getattr(usage, "completion_tokens", None)
                if usage
                else None,
            )
        except Exception:  # noqa: BLE001
            logger.exception("Meal text extraction failed")
            return MealTextResult(recognized=False, notes="manual entry required")

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
                    {
                        "role": "system",
                        "content": (
                            "你是食物识别器。仅返回严格 JSON，不要任何额外文字。\n"
                            '格式：{"name": "食物名称", "kcal": 整数}\n'
                            "如果图片不是食物（人/风景/物品/截图/文档等），返回："
                            '{"name": null, "kcal": 0}\n'
                            '名称要简洁中文，如："牛肉面"、"香蕉"、"拿铁哖东哥哦奥哦"；kcal 是总热量估计。'
                        ),
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": payload_url}},
                            {"type": "text", "text": "识别这张图片。"},
                        ],
                    },
                ],
                max_tokens=256,
                extra_body={"thinking": {"type": "disabled"}},
                **settings.llm_temperature_kwargs(settings.OPENAI_MODEL_VISION),
            )
            # Extract token usage
            usage = getattr(response, "usage", None)
            prompt_tokens = getattr(usage, "prompt_tokens", None) if usage else None
            completion_tokens = (
                getattr(usage, "completion_tokens", None) if usage else None
            )

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
                items = [
                    MealVisionItem(
                        name=str(name).strip(), portion_text="1 份", kcal=kcal
                    )
                ]
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
                items=[],
                total_kcal=0,
                confidence=0.0,
                notes=f"Vision error: {e}",
                is_food=False,
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

    def generate_text(
        self,
        context: dict,
        user_query: str,
        *,
        history: list[dict] | None = None,
        skill_prompt: str = "",
    ) -> ChatLLMResult:
        """Generate one complete structured response, retrying a truncated result once."""
        try:
            messages = _build_messages(
                context, user_query, history=history, skill_prompt=skill_prompt
            )
            is_health = _is_health_query(user_query, history)
            message_structure = context.get("message_structure") or {}
            route = message_structure.get("interaction_route") or {}
            repetition = (message_structure.get("session_memory") or {}).get(
                "repetition_policy"
            ) or {}
            if not repetition:
                repetition = (message_structure.get("response_plan") or {}).get(
                    "repetition_policy"
                ) or {}
            delta_only = repetition.get("mode") == "delta_only"
            required_concepts = _causal_coverage_requirements(
                message_structure,
                delta_only=delta_only,
            )
            depth = route.get("depth") or "standard"
            max_tokens = (
                5000 if is_health and depth == "deep" else (3400 if is_health else 1800)
            )
            prompt_tokens: int | None = None
            completion_tokens: int | None = None
            parsed: dict = {}
            safety_flags: list[str] = []
            incomplete_reasons: list[str] = []

            for attempt in range(2):
                attempt_messages = messages
                if attempt:
                    retry_scope = (
                        "这是连续追问，请保持增量回答，不重复旧结论；只需补全本轮新增判断、下一步和必要安全边界。"
                        if delta_only
                        else "深度健康问题要完整覆盖结论、各因素的证据边界、下一步评估和安全边界。"
                    )
                    if required_concepts:
                        retry_scope += (
                            "正文必须语义覆盖 health_nlu.compound_assessment 中本轮要求的每个核心概念，"
                            "缺失概念见失败原因。"
                        )
                    attempt_messages = messages + [
                        {
                            "role": "system",
                            "content": (
                                "上一轮输出未通过完整性校验。请从头重新回答，不要续写残片。"
                                "只返回一个闭合的严格 JSON 对象；summary 和 analysis 都必须以完整句子结束，"
                                f"{retry_scope}"
                                f"上轮失败原因：{', '.join(incomplete_reasons)}。"
                            ),
                        }
                    ]
                response = self._client.chat.completions.create(
                    model=self.text_model,
                    messages=attempt_messages,
                    max_tokens=max_tokens,
                    extra_body={"thinking": {"type": "disabled"}},
                    **settings.llm_temperature_kwargs(self.text_model),
                )
                usage = getattr(response, "usage", None)
                prompt_tokens = _add_usage(
                    prompt_tokens,
                    getattr(usage, "prompt_tokens", None) if usage else None,
                )
                completion_tokens = _add_usage(
                    completion_tokens,
                    getattr(usage, "completion_tokens", None) if usage else None,
                )

                choice = response.choices[0]
                raw = choice.message.content or ""
                parsed = _parse_structured_response(raw)
                incomplete_reasons = response_incompleteness_reasons(
                    parsed,
                    raw=raw,
                    finish_reason=getattr(choice, "finish_reason", None),
                    depth=depth,
                    is_health=is_health,
                    delta_only=delta_only,
                    required_concepts=required_concepts,
                )
                if not incomplete_reasons:
                    break
                logger.warning(
                    "OpenAI structured response incomplete on attempt %s: %s",
                    attempt + 1,
                    ",".join(incomplete_reasons),
                )
                if attempt == 0:
                    safety_flags.append("provider_incomplete_retried")

            if incomplete_reasons:
                return ChatLLMResult(
                    answer_markdown="这次回答没有完整生成，请稍后重试。",
                    confidence=0.0,
                    followups=["重新生成这条回答"],
                    safety_flags=list(
                        dict.fromkeys(
                            safety_flags + ["provider_error", "provider_incomplete"]
                        )
                    ),
                    summary="这次回答没有完整生成，请稍后重试。",
                    analysis="模型连续两次返回了不完整内容，你的消息和当前会话已经保留。",
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                )

            parse_status = parsed.get("_parse_status")
            if parse_status == "invalid":
                safety_flags.append("provider_error")
            elif parse_status == "repaired":
                safety_flags.append("provider_format_repaired")
            answer = parsed.get("analysis") or parsed.get("summary") or ""
            return ChatLLMResult(
                answer_markdown=answer,
                confidence=0.85,
                followups=parsed.get("followups", []),
                safety_flags=safety_flags,
                summary=parsed.get("summary", ""),
                analysis=parsed.get("analysis", ""),
                profile_extracted=parsed.get("profile_extracted", {}),
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )
        except Exception as e:
            logger.error("OpenAI generate_text failed: %s", e)
            return ChatLLMResult(
                answer_markdown="这次回答没有完整生成，请稍后重试。",
                confidence=0.0,
                followups=["请稍后再试"],
                safety_flags=["provider_error"],
                summary="这次回答没有完整生成，请稍后重试。",
                analysis="模型服务暂时不可用，你的消息和当前会话已经保留。",
            )

    def stream_text(
        self,
        context: dict,
        user_query: str,
        *,
        history: list[dict] | None = None,
        skill_prompt: str = "",
    ) -> Iterator[str]:
        """Stream text token-by-token with provider reasoning disabled."""
        try:
            messages = _build_messages(
                context, user_query, history=history, skill_prompt=skill_prompt
            )
            is_health = _is_health_query(user_query, history)
            route = (context.get("message_structure") or {}).get(
                "interaction_route"
            ) or {}
            depth = route.get("depth") or "standard"
            max_tokens = (
                5000 if is_health and depth == "deep" else (3400 if is_health else 1800)
            )

            stream = self._client.chat.completions.create(
                model=self.text_model,
                messages=messages,
                max_tokens=max_tokens,
                **settings.llm_temperature_kwargs(self.text_model),
                stream=True,
                extra_body={"thinking": {"type": "disabled"}},
            )
            for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta and delta.content:
                    yield delta.content
        except Exception as e:
            logger.error("OpenAI stream_text failed: %s", e)
            yield "这次回答没有完整生成，请稍后重试。"


def _causal_coverage_requirements(
    message_structure: dict,
    *,
    delta_only: bool,
) -> list[dict]:
    nlu = message_structure.get("health_nlu") or {}
    if nlu.get("primary_intent") != "causal_assessment":
        return []

    compound = nlu.get("compound_assessment") or {}
    concepts = list(compound.get("concepts") or nlu.get("matched_concepts") or [])
    if delta_only:
        current_keys = {
            str(item.get("key"))
            for item in (nlu.get("matched_concepts") or [])
            if item.get("key")
        }
        if not current_keys:
            return []
        concepts = [item for item in concepts if str(item.get("key")) in current_keys]

    keys = [str(item.get("key")) for item in concepts if item.get("key")]
    alias_groups = concept_alias_groups(keys)
    requirements: list[dict] = []
    seen: set[str] = set()
    for concept in concepts:
        key = str(concept.get("key") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        display = str(concept.get("display") or key)
        requirements.append(
            {
                "key": key,
                "display": display,
                "terms": alias_groups.get(key) or [display],
            }
        )
    return requirements


def _add_usage(current: int | None, value: object) -> int | None:
    if not isinstance(value, int):
        return current
    return value if current is None else current + value
