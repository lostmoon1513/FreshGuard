import json

import pytest

from app.engine.providers.errors import LLMOutputError
from app.engine.providers.llm_common import build_system_prompt, parse_model_json
from tests.unit.providers._helpers import Verdict

GOOD = {"answer": "yes", "score": 3}


def parse(text):
    return parse_model_json("t", text, Verdict)


def test_plain_json():
    assert parse(json.dumps(GOOD)) == Verdict(**GOOD)


@pytest.mark.parametrize(
    "text",
    [
        '```json\n{"answer": "yes", "score": 3}\n```',
        '```\n{"answer": "yes", "score": 3}\n```',
        '  \n{"answer": "yes", "score": 3}\n  ',
        'Here you go: {"answer": "yes", "score": 3} Hope that helps!',
    ],
)
def test_tolerated_wrappers(text):
    assert parse(text) == Verdict(**GOOD)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "not json",
        "{",
        "[1, 2]",
        '{"answer": "yes"}',
        '{"answer": "yes", "score": "many"}',
        "null",
    ],
)
def test_invalid_output_raises_and_is_never_repaired(text):
    with pytest.raises(LLMOutputError):
        parse(text)


def test_schema_error_names_the_field_not_the_content():
    with pytest.raises(LLMOutputError) as info:
        parse('{"answer": "TOPSECRET", "score": "x"}')
    assert "score" in str(info.value) and "TOPSECRET" not in str(info.value)


def test_system_prompt_contains_original_instruction_and_schema():
    prompt = build_system_prompt("  Extract claims.  ", Verdict)
    assert prompt.startswith("Extract claims.")
    assert "JSON" in prompt and '"score"' in prompt and "answer" in prompt