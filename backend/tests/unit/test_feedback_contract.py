import pytest
from pydantic import ValidationError

from app.schemas.feedback import FeedbackCreate


def test_feedback_contract_normalizes_text_before_length_validation() -> None:
    payload = FeedbackCreate(
        category="  bug  ",
        content="  页面无法打开  ",
        contact="   ",
        app_platform="  ios  ",
    )

    assert payload.category == "bug"
    assert payload.content == "页面无法打开"
    assert payload.contact is None
    assert payload.app_platform == "ios"

    with pytest.raises(ValidationError):
        FeedbackCreate(category="general", content="  a  ")


def test_feedback_contract_rejects_blank_category() -> None:
    with pytest.raises(ValidationError):
        FeedbackCreate(category="   ", content="可以提交")


def test_feedback_contract_rejects_blank_content() -> None:
    with pytest.raises(ValidationError):
        FeedbackCreate(category="general", content=" \n\t ")
