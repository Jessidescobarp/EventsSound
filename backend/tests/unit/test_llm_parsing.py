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
