from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Iterator, Literal

from pydantic import BaseModel, Field


class MealVisionItem(BaseModel):
    name: str
    portion_text: str
    kcal: int


class MealVisionResult(BaseModel):
    items: list[MealVisionItem]
    total_kcal: int
    confidence: float = Field(ge=0, le=1)
    notes: str = ""
    is_food: bool = True
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class MealTextItem(BaseModel):
    name: str
    portion_text: str | None = None
    categories: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)


class MealTextResult(BaseModel):
    items: list[MealTextItem] = Field(default_factory=list)
    meal_type: Literal["breakfast", "lunch", "dinner", "snack"] | None = None
    portion_text: str | None = None
    structure: dict[str, Any] = Field(default_factory=dict)
    estimated_nutrition: dict[str, Any] = Field(default_factory=dict)
    field_confidences: dict[str, float] = Field(default_factory=dict)
    confidence: float = Field(default=0, ge=0, le=1)
    recognized: bool = False
    notes: str = ""
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class ChatLLMResult(BaseModel):
    answer_markdown: str
    confidence: float = Field(ge=0, le=1)
    followups: list[str] = Field(default_factory=list)
    safety_flags: list[str] = Field(default_factory=list)
    summary: str = ""
    analysis: str = ""
    profile_extracted: dict = Field(default_factory=dict)
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class LLMProvider(ABC):
    provider_name: str
    text_model: str
    vision_model: str

    @abstractmethod
    def analyze_image(self, image_url: str) -> MealVisionResult:
        raise NotImplementedError

    @abstractmethod
    def analyze_meal_text(self, raw_text: str) -> MealTextResult:
        raise NotImplementedError

    @abstractmethod
    def generate_text(
        self,
        context: dict,
        user_query: str,
        *,
        history: list[dict] | None = None,
        skill_prompt: str = "",
    ) -> ChatLLMResult:
        raise NotImplementedError

    @abstractmethod
    def stream_text(
        self,
        context: dict,
        user_query: str,
        *,
        history: list[dict] | None = None,
        skill_prompt: str = "",
    ) -> Iterator[str]:
        raise NotImplementedError
