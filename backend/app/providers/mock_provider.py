from __future__ import annotations

import json
from typing import Iterator

from app.providers.base import ChatLLMResult, LLMProvider, MealVisionItem, MealVisionResult


class MockProvider(LLMProvider):
    provider_name = "mock"
    text_model = "mock-text"
    vision_model = "mock-vision"

    def analyze_image(self, image_url: str) -> MealVisionResult:
        _ = image_url
        items = [
            MealVisionItem(name="米饭", portion_text="1 碗", kcal=260),
            MealVisionItem(name="鸡胸肉", portion_text="100g", kcal=165),
            MealVisionItem(name="蔬菜", portion_text="1 份", kcal=80),
        ]
        total = sum(i.kcal for i in items)
        return MealVisionResult(items=items, total_kcal=total, confidence=0.72, notes="mock estimate")

    def _build_mock_response(self, context: dict, user_query: str) -> dict:
        """Build a mock structured response matching the JSON format GPT returns."""
        # Extract context data for realistic mock
        g = context.get("glucose_summary") or context.get("glucose") or {}
        dq = context.get("data_quality") or {}
        kcal = dq.get("kcal_today", 0) or context.get("kcal_today", 0)
        meals = context.get("meals_today", [])

        last_24h = g.get("last_24h", {})
        avg_glucose = last_24h.get("avg", "暂无")
        tir = last_24h.get("tir_70_180_pct", "暂无")

        summary = (
            f"根据你的血糖与饮食数据分析，今日已记录 {len(meals)} 餐共 {kcal} kcal，"
            f"近24h血糖均值 {avg_glucose} mg/dL、TIR {tir}%。"
            f"针对你的问题「{user_query[:20]}」，建议结合餐后血糖变化进一步观察。"
            f"告诉我更多细节，我会帮你做更深入的分析。"
        )

        analysis = (
            f"## 数据概览\n\n"
            f"- **今日进餐**: {len(meals)} 次，累计约 **{kcal} kcal**\n"
            f"- **近24h血糖均值**: {avg_glucose} mg/dL\n"
            f"- **TIR(70-180)**: {tir}%\n\n"
            f"## 问题分析\n\n"
            f"你问的是：**{user_query}**\n\n"
            f"基于当前数据，以下是初步分析：\n"
            f"1. 餐后血糖波动与碳水化合物摄入量密切相关\n"
            f"2. 建议关注高碳水餐次后 1-2 小时血糖变化\n"
            f"3. 如有不适症状，建议及时就医\n\n"
            f"## 建议\n\n"
            f"- 记录每餐后的主观感受，便于后续分析\n"
            f"- 保持均衡饮食，避免单次大量摄入碳水化合物\n\n"
            f"---\n"
            f"*（这是离线 Mock 响应，联网后将获得 AI 个性化分析）*\n\n"
            f"> 你可以继续问我：\n"
            f"> - 要不要我按今天每餐给出更细的建议？\n"
            f"> - 需要我比较 24h 和 7d 的波动差异吗？"
        )

        return {"summary": summary, "analysis": analysis}

    def generate_text(self, context: dict, user_query: str, *, history: list[dict] | None = None) -> ChatLLMResult:
        resp = self._build_mock_response(context, user_query)
        raw_json = json.dumps(resp, ensure_ascii=False)
        return ChatLLMResult(
            answer_markdown=raw_json,
            confidence=0.66,
            followups=["要不要我按今天每餐给出更细的建议？", "需要我比较 24h 和 7d 的波动差异吗？"],
            safety_flags=[],
            summary=resp["summary"],
            analysis=resp["analysis"],
        )

    def stream_text(self, context: dict, user_query: str, *, history: list[dict] | None = None) -> Iterator[str]:
        resp = self._build_mock_response(context, user_query)
        raw_json = json.dumps(resp, ensure_ascii=False)
        # Simulate streaming by yielding chunks
        chunk_size = 20
        for i in range(0, len(raw_json), chunk_size):
            yield raw_json[i:i + chunk_size]
