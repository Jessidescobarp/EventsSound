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
    pytest.param('{"a": NaN}', id="nan"),
    pytest.param('{"a": Infinity}', id="infinity"),
    pytest.param('{"a": -Infinity}', id="neg-infinity"),
    pytest.param('{"a": 1e999}', id="overflowing-float"),
    pytest.param('{"a": -1e999}', id="neg-overflowing-float"),
    pytest.param('{"a": [1, 2, NaN]}', id="nan-in-list"),
    pytest.param(nested(33), id="33-levels"),
    pytest.param('{"a":' + "[" * 40 + "1" + "]" * 40 + "}", id="40-list-levels"),
    pytest.param(nested(100_000), id="100k-levels"),
    pytest.param("[" * 100_000, id="100k-open-brackets"),
    pytest.param('{"a": ' + "9" * 5000 + "}", id="5000-digit-int"),
    pytest.param("not json", id="not-json"),
    pytest.param("[1]", id="list"),
    pytest.param("", id="empty"),
]


@pytest.mark.parametrize("text", HOSTILE)
def test_parse_json_object_raises_only_bad_response(text: str) -> None:
    with pytest.raises(LlmBadResponse):
        parse_json_object(text)


@pytest.mark.parametrize("levels", [1, 31, 32])
def test_nesting_up_to_the_limit_is_accepted(levels: int) -> None:
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


@pytest.mark.parametrize("text", HOSTILE)
def test_replay_provider_maps_hostile_json_text_to_bad_response(text: str) -> None:
    entry = ReplayEntry(text=text, usage=TokenUsage(1, 1))
    provider = ReplayProvider({"s": {"understand": [entry]}}, scenario="s")

    with pytest.raises(LlmBadResponse):
        provider.complete(request())


@pytest.mark.parametrize("text", HOSTILE)
def test_openrouter_provider_maps_hostile_json_text_to_bad_response(text: str) -> None:
    script = Script(reply(chat_ok(text)))
    provider = OpenRouterProvider(KEY, "vendor/model", transport=script.transport)

    with pytest.raises(LlmBadResponse):
        provider.complete(request())
