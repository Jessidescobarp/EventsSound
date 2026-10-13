"""structured_call: parse + validate + one bounded repair, with meter and deadline."""

import time
from typing import Any

import pytest
from pydantic import BaseModel, Field, ValidationError

from eventssound.adapters.agent.structured import (
    DeadlineExceeded,
    StructuredOutputInvalid,
    structured_call,
)
from eventssound.adapters.llm.replay import ScriptedProvider
from eventssound.application.llm import (
    LlmMessage,
    LlmResponse,
    LlmTimeout,
    Role,
    TokenUsage,
)
from eventssound.application.quote_chat import AgentLimitExceeded, ChatLimits, UsageMeter

USAGE = TokenUsage(100, 50)
MESSAGES = (LlmMessage(Role.SYSTEM, "s"), LlmMessage(Role.USER, "u"))


class Mini(BaseModel):
    model_config = {"extra": "forbid"}
    intent: str = Field(min_length=1)
    note: str | None = None


def response(text: str, *, finish: str | None = "stop", usage: TokenUsage = USAGE) -> LlmResponse:
    return LlmResponse(text=text, usage=usage, model="replay-model", finish_reason=finish)


def call(provider, meter, **overrides):
    kwargs: dict[str, Any] = dict(
        provider=provider,
        node="understand",
        messages=MESSAGES,
        model_cls=Mini,
        meter=meter,
        limits=ChatLimits(),
        deadline_monotonic=time.monotonic() + 30,
        temperature=0.0,
        max_output_tokens=400,
    )
    kwargs.update(overrides)
    return structured_call(**kwargs)


class TestHappyPath:
    def test_valid_json_returns_a_model_and_updates_the_meter(self) -> None:
        provider = ScriptedProvider([response('{"intent": "quote"}')])
        meter = UsageMeter()
        model = call(provider, meter)
        assert isinstance(model, Mini)
        assert model.intent == "quote"
        assert meter.llm_calls == 1
        assert meter.prompt_tokens == 100
        assert meter.completion_tokens == 50
        assert meter.repairs == 0

    def test_code_fences_are_stripped(self) -> None:
        provider = ScriptedProvider([response('```json\n{"intent": "quote"}\n```')])
        assert call(provider, UsageMeter()).intent == "quote"

    def test_json_embedded_in_prose_is_extracted(self) -> None:
        provider = ScriptedProvider([response('Claro, aqui lo tienes: {"intent": "quote"} ok?')])
        assert call(provider, UsageMeter()).intent == "quote"

    def test_the_request_carries_node_schema_and_caps(self) -> None:
        provider = ScriptedProvider([response('{"intent": "quote"}')])
        call(provider, UsageMeter(), scenario="wedding.150")
        request = provider.calls[0]
        assert request.node == "understand"
        assert request.scenario == "wedding.150"
        assert request.response_format.value == "json"
        assert request.json_schema is not None
        assert request.json_schema.name == "understand"
        assert request.temperature == 0.0
        assert request.max_output_tokens == 400
        assert 0 < request.timeout_s <= 25

    def test_scenario_none_is_allowed(self) -> None:
        provider = ScriptedProvider([response('{"intent": "quote"}')])
        call(provider, UsageMeter())
        assert provider.calls[0].scenario is None


class TestRepair:
    def test_one_repair_recovers_and_is_counted(self) -> None:
        provider = ScriptedProvider(
            [
                response('{"intent": "", "note": "HOSTILE-VALUE-12345"}'),
                response('{"intent": "quote"}'),
            ]
        )
        meter = UsageMeter()
        model = call(provider, meter)
        assert model.intent == "quote"
        assert meter.llm_calls == 2
        assert meter.repairs == 1
        repair_request = provider.calls[1]
        # The repair shows the offending path and code...
        repair_text = repair_request.messages[-1].content
        assert "intent" in repair_text
        # ...but never the offending (user-influenced) value.
        assert "HOSTILE-VALUE-12345" not in repair_text
        assert "Reply with a single JSON object" in repair_text

    def test_second_failure_raises_structured_invalid(self) -> None:
        provider = ScriptedProvider([response("no json at all"), response("still no json")])
        with pytest.raises(StructuredOutputInvalid):
            call(provider, UsageMeter())

    def test_repair_never_repair_repair(self) -> None:
        provider = ScriptedProvider([response("bad"), response("also bad")])
        meter = UsageMeter()
        with pytest.raises(StructuredOutputInvalid):
            call(provider, meter)
        assert meter.repairs == 1
        assert meter.llm_calls == 2


class TestInvalidOutput:
    @pytest.mark.parametrize(
        "text",
        [
            "[1, 2]",  # not an object
            '{"intent": 1}',  # type mismatch
            '{"intent": "quote", "extra": 1}',  # extra forbidden
            '{"intent": "a" * 1000}',  # not even JSON
            '{"nested": {"a": %s}}' % ("{" * 40),  # too deep
        ],
    )
    def test_invalid_outputs_go_to_repair_not_abort(self, text: str) -> None:
        provider = ScriptedProvider([response(text), response('{"intent": "quote"}')])
        assert call(provider, UsageMeter()).intent == "quote"

    def test_finish_reason_length_is_invalid(self) -> None:
        provider = ScriptedProvider(
            [response('{"intent": "quo"', finish="length"), response('{"intent": "quote"}')]
        )
        meter = UsageMeter()
        call(provider, meter)
        assert meter.repairs == 1

    def test_truncated_but_well_formed_json_is_still_invalid(self) -> None:
        # The provider truncated mid-stream; the JSON happens to be complete: still a repair.
        provider = ScriptedProvider(
            [response('{"intent": "quote"}', finish="length"), response('{"intent": "quote"}')]
        )
        meter = UsageMeter()
        call(provider, meter)
        assert meter.repairs == 1


class Deep(BaseModel):
    model_config = {"extra": "forbid"}
    intent: str = Field(min_length=1)
    tree: dict[str, object] | None = None


def test_deeper_than_the_json_depth_cap_is_invalid() -> None:
    import json

    deep = {"leaf": 1}
    for _ in range(40):
        deep = {"n": deep}
    provider = ScriptedProvider(
        [response(json.dumps({"intent": "quote", "tree": deep})), response('{"intent": "quote"}')]
    )
    meter = UsageMeter()
    assert call(provider, meter, model_cls=Deep).tree is None


class TestErrorRoutes:
    def test_provider_error_propagates_and_counts_the_call(self) -> None:
        provider = ScriptedProvider([LlmTimeout()])
        meter = UsageMeter()
        with pytest.raises(LlmTimeout):
            call(provider, meter)
        assert meter.llm_calls == 1

    def test_call_cap_raises_before_any_provider_call(self) -> None:
        provider = ScriptedProvider([response('{"intent": "quote"}')])
        meter = UsageMeter(llm_calls=3)
        with pytest.raises(AgentLimitExceeded):
            call(provider, meter)
        assert provider.calls == []

    def test_deadline_exhausted_raises_before_any_provider_call(self) -> None:
        provider = ScriptedProvider([response('{"intent": "quote"}')])
        with pytest.raises(DeadlineExceeded):
            call(provider, UsageMeter(), deadline_monotonic=time.monotonic() - 1)
        assert provider.calls == []

    def test_timeout_is_clipped_to_the_deadline(self) -> None:
        provider = ScriptedProvider([response('{"intent": "quote"}')])
        call(provider, UsageMeter(), deadline_monotonic=time.monotonic() + 3)
        assert provider.calls[0].timeout_s <= 3.1


def _unused_validation_error_guard() -> None:
    # ValidationError is raised internally and never escapes structured_call.
    assert issubclass(ValidationError, ValueError)
