"""Model-controlled JSON text must only ever raise LlmBadResponse, never ValueError."""

import pytest
from http_fakes import KEY, Script, chat_ok, reply

from eventssound.adapters.llm.openrouter import OpenRouterProvider
from eventssound.adapters.llm.parsing import parse_json_object
from eventssound.adapters.llm.replay import ReplayEntry, ReplayProvider
from eventssound.application.llm import (
    LlmBadResponse,
    LlmMessage,
    LlmRequest,
    ResponseFormat,
    Role,
    TokenUsage,
)


def nested(levels: int) -> str:
    return '{"a":' * levels + "1" + "}" * levels


HOSTILE = [
    '{"a": NaN}',
    '{"a": Infinity}',
    '{"a": -Infinity}',
    '{"a": 1e999}',
    '{"a": -1e999}',
    '{"a": [1, 2, NaN]}',
    nested(33),
    '{"a":' + "[" * 40 + "1" + "]" * 40 + "}",
    nested(100_000),
    "[" * 100_000,
    '{"a": ' + "9" * 5000 + "}",
    "not json",
    "[1]",
    "",
]


def test_parse_json_object_raises_only_bad_response() -> None:
    for text in HOSTILE:
        with pytest.raises(LlmBadResponse):
            parse_json_object(text)


def test_nesting_up_to_the_limit_is_accepted() -> None:
    for levels in (1, 32):
        parsed = parse_json_object(nested(levels))

        for _ in range(levels - 1):
            parsed = parsed["a"]  # type: ignore[assignment]
        assert parsed == {"a": 1}


def test_ordinary_documents_still_parse() -> None:
    text = ' {"intent": "quote", "n": [1, 2.5, null, true], "o": {"x": "ñ"}} '

    assert parse_json_object(text) == {
        "intent": "quote",
        "n": [1, 2.5, None, True],
        "o": {"x": "ñ"},
    }


def request() -> LlmRequest:
    return LlmRequest(
        node="understand",
        messages=[LlmMessage(Role.USER, "hola")],
        response_format=ResponseFormat.JSON,
    )


# The adapters share parse_json_object; a few classes prove the wiring, not every row.
WIRED = [HOSTILE[0], HOSTILE[6], HOSTILE[9], HOSTILE[10]]


def test_providers_map_hostile_json_text_to_bad_response() -> None:
    for text in WIRED:
        entry = ReplayEntry(text=text, usage=TokenUsage(1, 1))
        replay = ReplayProvider({"s": {"understand": [entry]}}, scenario="s")
        with pytest.raises(LlmBadResponse):
            replay.complete(request())

        script = Script(reply(chat_ok(text)))
        live = OpenRouterProvider(KEY, "vendor/model", transport=script.transport)
        with pytest.raises(LlmBadResponse):
            live.complete(request())


FENCED = '```json\n{"a": 1}\n```'
TOLERANT = [
    ('{"a": 1}', {"a": 1}),
    (FENCED, {"a": 1}),
    ('```\n{"a": 1}\n```', {"a": 1}),
    ('  ```JSON {"a": 1}```  ', {"a": 1}),
    ('Sure! Here it is:\n{"a": {"b": "x}{"}}\nHope it helps.', {"a": {"b": "x}{"}}),
    ('Here: ```json\n{"a": 1}\n``` done', {"a": 1}),
    ('{"a": "}"}', {"a": "}"}),
    ("", "empty_content"),
    ("[1]", "not_json"),
    ("42", "not_json"),
    ('text [{"a": 1}] text', "not_json"),
    ('{"a": 1} {"b": 2}', "not_json"),
    ('{"a": {"b": 1}', "not_json"),
    ("} {", "not_json"),
    ('prose {"a": NaN} prose', "not_json"),
    ('```json\n{"a": ' + "9" * 5000 + "}\n```", "not_json"),
    ("```json\n" + nested(33) + "\n```", "unsafe_json"),
    ('```json\n["a"]\n```', "not_json"),
]


@pytest.mark.parametrize(("text", "expected"), TOLERANT)
def test_parse_json_object_tolerates_fences_and_prose_but_nothing_unsafe(text, expected) -> None:
    if isinstance(expected, dict):
        assert parse_json_object(text) == expected
        return
    with pytest.raises(LlmBadResponse) as caught:
        parse_json_object(text)
    assert caught.value.reason == expected


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        (
            [{"type": "text", "text": '{"a":'}, {"type": "image"}, {"type": "text", "text": " 1}"}],
            {"a": 1},
        ),
        ([{"type": "text", "text": FENCED}], {"a": 1}),
        ([], "empty_content"),
        ([{"type": "text", "text": 5}, {"type": "refusal", "text": "x"}], "empty_content"),
        ("   ", "empty_content"),
        (None, "empty_content"),
        ({"a": 1}, "empty_content"),
        (FENCED, {"a": 1}),
    ],
)
def test_live_provider_reads_string_or_text_parts_content(content, expected) -> None:
    payload = chat_ok()
    payload["choices"][0]["message"]["content"] = content  # type: ignore[index]
    live = OpenRouterProvider(KEY, "vendor/model", transport=Script(reply(payload)).transport)
    if isinstance(expected, dict):
        assert live.complete(request()).parsed == expected
        return
    with pytest.raises(LlmBadResponse) as caught:
        live.complete(request())
    assert caught.value.reason == expected
