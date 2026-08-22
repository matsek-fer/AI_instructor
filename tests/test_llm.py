import pytest

from ai_learner.errors import StructuredOutputError
from ai_learner.llm import parse_structured_text


def test_parse_valid_object():
    assert parse_structured_text('{"a": 1}') == {"a": 1}


def test_parse_rejects_invalid_json():
    with pytest.raises(StructuredOutputError, match="invalid JSON"):
        parse_structured_text("not json {")


def test_parse_rejects_non_object():
    with pytest.raises(StructuredOutputError, match="Expected a JSON object"):
        parse_structured_text("[1, 2, 3]")
