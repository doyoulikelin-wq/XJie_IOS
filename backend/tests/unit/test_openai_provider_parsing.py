from app.providers.openai_provider import _parse_structured_response


def test_smart_quote_json_is_repaired_without_exposing_serialized_object() -> None:
    raw = """
    {
      “summary”: “昨晚睡眠不足可以诱发头痛。”,
      “analysis”: “不能因否认胸痛就说已排除严重问题。”,
      “followups”: [“记录头痛持续时间”],
      "profile_extracted": {}
    }
    """

    parsed = _parse_structured_response(raw)

    assert parsed["_parse_status"] == "repaired"
    assert parsed["summary"] == "昨晚睡眠不足可以诱发头痛。"
    assert parsed["analysis"] == "不能因否认胸痛就说已排除严重问题。"
    assert parsed["followups"] == ["记录头痛持续时间"]
    assert not parsed["summary"].lstrip().startswith("{")


def test_smart_quote_repair_preserves_quoted_prose_inside_value() -> None:
    raw = "{“summary”: “不能得出“一周稳定”结论。”, “analysis”: “按实际样本回答。”, “followups”: []}"

    parsed = _parse_structured_response(raw)

    assert parsed["summary"] == "不能得出“一周稳定”结论。"
    assert parsed["_parse_status"] == "repaired"


def test_unrecoverable_object_returns_retry_contract_not_raw_json() -> None:
    raw = '{"summary": [broken], "analysis": ???}'

    parsed = _parse_structured_response(raw)

    assert parsed["_parse_status"] == "invalid"
    assert parsed["summary"] == "这次回答没有完整生成，请稍后重试。"
    assert raw not in parsed["summary"]


def test_plain_text_provider_response_remains_usable() -> None:
    parsed = _parse_structured_response("先补水并休息，持续加重时就医。")

    assert parsed["_parse_status"] == "plain_text"
    assert parsed["summary"] == "先补水并休息，持续加重时就医。"
