"""LLM port DTOs and error taxonomy: validation, immutability, hashability."""

import json
from dataclasses import FrozenInstanceError

import pytest

from eventssound.application.llm import (
    JsonSchemaSpec,
    LlmAuthError,
    LlmBadResponse,
    LlmError,
    LlmMessage,
    LlmRateLimited,
    LlmRequest,
    LlmResponse,
    LlmTimeout,
    LlmUnavailable,
    LlmValidationError,
    ResponseFormat,
    Role,
    TokenUsage,
)

USER = LlmMessage(Role.USER, "hola")


def make_request(**overrides: object) -> LlmRequest:
    fields: dict[str, object] = {"node": "understand", "messages": [USER]}
    fields.update(overrides)
    return LlmRequest(**fields)  # type: ignore[arg-type]


class TestLlmMessage:
    def test_valid_message_keeps_its_fields(self) -> None:
        message = LlmMessage(Role.SYSTEM, "be brief")

        assert (message.role, message.content) == (Role.SYSTEM, "be brief")

    @pytest.mark.parametrize("role", ["user", None, 1])
    def test_role_must_be_a_role_member(self, role: object) -> None:
        with pytest.raises(LlmValidationError, match="role"):
            LlmMessage(role, "x")  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "content",
        ["", b"x", None, 3, pytest.param("x" * 50_001, id="too-long")],
    )
    def test_content_must_be_a_bounded_non_empty_string(self, content: object) -> None:
        with pytest.raises(LlmValidationError, match="content"):
            LlmMessage(Role.USER, content)  # type: ignore[arg-type]

    def test_content_at_the_bound_is_accepted(self) -> None:
        assert len(LlmMessage(Role.USER, "x" * 50_000).content) == 50_000

    def test_message_is_frozen_and_hashable(self) -> None:
        message = LlmMessage(Role.USER, "x")

        with pytest.raises(FrozenInstanceError):
            message.content = "y"  # type: ignore[misc]
        assert hash(message) == hash(LlmMessage(Role.USER, "x"))


class TestJsonSchemaSpec:
    def test_from_schema_round_trips_and_is_hashable(self) -> None:
        spec = JsonSchemaSpec.from_schema("extraction", {"type": "object", "b": [1], "a": 2})

        assert spec.name == "extraction"
        assert spec.schema == {"type": "object", "b": [1], "a": 2}
        assert hash(spec) == hash(JsonSchemaSpec.from_schema("extraction", spec.schema))

    def test_returned_schema_is_a_copy(self) -> None:
        spec = JsonSchemaSpec.from_schema("s", {"a": {"b": 1}})

        spec.schema["a"]["b"] = 2

        assert spec.schema == {"a": {"b": 1}}

    @pytest.mark.parametrize("name", ["", "has space", "x" * 65, "ñ", "a\n", None, 3])
    def test_name_is_a_bounded_identifier(self, name: object) -> None:
        with pytest.raises(LlmValidationError, match="name"):
            JsonSchemaSpec.from_schema(name, {"type": "object"})  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "schema",
        [[], "x", None, {"a": object()}, {"a": float("nan")}, {1: "x"}, {"a": "x" * 20_001}],
        ids=["list", "str", "none", "not-json", "nan", "int-key", "too-large"],
    )
    def test_schema_must_be_a_bounded_json_object(self, schema: object) -> None:
        with pytest.raises(LlmValidationError, match="schema"):
            JsonSchemaSpec.from_schema("s", schema)  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "raw", ["not json", "[1]", '"x"', pytest.param("x" * 20_001, id="too-long")]
    )
    def test_direct_construction_validates_the_stored_json(self, raw: str) -> None:
        with pytest.raises(LlmValidationError, match="schema"):
            JsonSchemaSpec("s", raw)


class TestLlmRequest:
    def test_defaults_and_tuple_coercion(self) -> None:
        request = make_request()

        assert request.messages == (USER,)
        assert isinstance(request.messages, tuple)
        assert request.response_format is ResponseFormat.TEXT
        assert request.json_schema is None
        assert request.scenario is None
        assert hash(request) == hash(make_request())

    def test_accepts_any_non_string_iterable_of_messages(self) -> None:
        request = make_request(messages=(m for m in [USER, LlmMessage(Role.ASSISTANT, "ok")]))

        assert [m.role for m in request.messages] == [Role.USER, Role.ASSISTANT]

    @pytest.mark.parametrize(
        "messages",
        [[], "hola", b"hola", 7, None, ["hola"], [USER, None], [USER] * 51],
        ids=["empty", "str", "bytes", "int", "none", "str-element", "none-element", "too-many"],
    )
    def test_messages_must_be_a_bounded_non_empty_collection_of_messages(
        self, messages: object
    ) -> None:
        with pytest.raises(LlmValidationError, match="messages"):
            make_request(messages=messages)

    @pytest.mark.parametrize("node", ["", "Understand", "has space", "a" * 33, "x\n", None, 1])
    def test_node_is_a_short_lowercase_identifier(self, node: object) -> None:
        with pytest.raises(LlmValidationError, match="node"):
            make_request(node=node)

    @pytest.mark.parametrize(
        "scenario",
        ["", "a b", "x" * 65, "ok\n", 3, "..", ".", "a..b", ".a", "a.", "../x", "a/b"],
    )
    def test_scenario_when_given_is_a_bounded_identifier(self, scenario: object) -> None:
        with pytest.raises(LlmValidationError, match="scenario"):
            make_request(scenario=scenario)

    @pytest.mark.parametrize("scenario", ["boda_simple.v2", "a", "a-b_c.d.e", "x" * 64])
    def test_valid_scenario_is_kept(self, scenario: str) -> None:
        assert make_request(scenario=scenario).scenario == scenario

    @pytest.mark.parametrize("tokens", [0, -1, 4097, 1.0, True, "10", None])
    def test_max_output_tokens_is_an_int_within_1_and_4096(self, tokens: object) -> None:
        with pytest.raises(LlmValidationError, match="max_output_tokens"):
            make_request(max_output_tokens=tokens)

    @pytest.mark.parametrize("tokens", [1, 4096])
    def test_max_output_tokens_bounds_are_inclusive(self, tokens: int) -> None:
        assert make_request(max_output_tokens=tokens).max_output_tokens == tokens

    @pytest.mark.parametrize(
        "seconds", [0, -1, 0.0, float("inf"), float("nan"), True, "5", None, 301]
    )
    def test_timeout_is_a_positive_finite_number_up_to_300(self, seconds: object) -> None:
        with pytest.raises(LlmValidationError, match="timeout_s"):
            make_request(timeout_s=seconds)

    def test_integer_timeout_is_accepted(self) -> None:
        assert make_request(timeout_s=5).timeout_s == 5

    @pytest.mark.parametrize("temperature", [-0.1, 2.1, float("nan"), True, "0", None])
    def test_temperature_is_a_finite_number_within_0_and_2(self, temperature: object) -> None:
        with pytest.raises(LlmValidationError, match="temperature"):
            make_request(temperature=temperature)

    @pytest.mark.parametrize("fmt", ["json", None, 1])
    def test_response_format_must_be_a_member(self, fmt: object) -> None:
        with pytest.raises(LlmValidationError, match="response_format"):
            make_request(response_format=fmt)

    def test_json_schema_requires_json_format(self) -> None:
        spec = JsonSchemaSpec.from_schema("s", {"type": "object"})

        with pytest.raises(LlmValidationError, match="json_schema"):
            make_request(json_schema=spec)  # TEXT format
        request = make_request(json_schema=spec, response_format=ResponseFormat.JSON)
        assert request.json_schema == spec

    def test_json_schema_must_be_a_spec(self) -> None:
        with pytest.raises(LlmValidationError, match="json_schema"):
            make_request(json_schema={"type": "object"}, response_format=ResponseFormat.JSON)


class TestTokenUsage:
    def test_total_adds_both_sides(self) -> None:
        usage = TokenUsage(410, 120)

        assert usage.total == 530
        assert usage.estimated is False

    @pytest.mark.parametrize("value", [-1, 1.5, True, "3", None, 2**40])
    @pytest.mark.parametrize("side", ["prompt_tokens", "completion_tokens"])
    def test_token_counts_are_bounded_non_negative_ints(self, side: str, value: object) -> None:
        fields: dict[str, object] = {"prompt_tokens": 1, "completion_tokens": 1, side: value}

        with pytest.raises(LlmValidationError, match=side):
            TokenUsage(**fields)  # type: ignore[arg-type]

    @pytest.mark.parametrize("flag", [1, "yes", None])
    def test_estimated_must_be_a_real_bool(self, flag: object) -> None:
        with pytest.raises(LlmValidationError, match="estimated"):
            TokenUsage(1, 1, estimated=flag)  # type: ignore[arg-type]

    def test_zero_tokens_are_allowed(self) -> None:
        assert TokenUsage(0, 0).total == 0


class TestLlmResponse:
    def make(self, **overrides: object) -> LlmResponse:
        fields: dict[str, object] = {
            "text": "hola",
            "usage": TokenUsage(1, 2),
            "model": "m/free",
            "finish_reason": "stop",
            "latency_ms": 12,
        }
        fields.update(overrides)
        return LlmResponse(**fields)  # type: ignore[arg-type]

    def test_valid_response_is_a_hashable_value_object(self) -> None:
        response = self.make(parsed={"a": [1]})

        assert response.parsed == {"a": [1]}
        assert hash(response) == hash(self.make(parsed={"a": [1]}))

    def test_parsed_is_copied_so_caller_mutation_does_not_leak(self) -> None:
        source = {"a": [1]}
        response = self.make(parsed=source)

        source["a"].append(2)

        assert response.parsed == {"a": [1]}

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("text", None),
            ("text", b"x"),
            ("usage", (1, 2)),
            ("model", ""),
            ("model", 3),
            ("finish_reason", 3),
            ("latency_ms", -1),
            ("latency_ms", 1.5),
            ("latency_ms", True),
            ("parsed", [1]),
            ("parsed", "x"),
            ("parsed", {"a": object()}),
        ],
    )
    def test_invalid_fields_are_rejected(self, field: str, value: object) -> None:
        with pytest.raises(LlmValidationError, match=field):
            self.make(**{field: value})

    def test_empty_text_is_allowed_at_the_dto_level(self) -> None:
        assert self.make(text="").text == ""


class TestErrors:
    @pytest.mark.parametrize(
        "error",
        [LlmTimeout, LlmUnavailable, LlmBadResponse, LlmAuthError, LlmRateLimited],
    )
    def test_every_error_is_an_llm_error_with_a_generic_message(self, error: type) -> None:
        exc = error()

        assert isinstance(exc, LlmError)
        assert str(exc) and "http" not in str(exc).lower()

    def test_validation_errors_are_not_provider_errors(self) -> None:
        assert not issubclass(LlmValidationError, LlmError)
        assert issubclass(LlmValidationError, ValueError)

    def test_rate_limited_carries_retry_after(self) -> None:
        assert LlmRateLimited(retry_after_s=7).retry_after_s == 7
        assert LlmRateLimited().retry_after_s is None

    @pytest.mark.parametrize("value", [-1, 1.5, True, "7"])
    def test_rate_limited_rejects_bad_retry_after(self, value: object) -> None:
        with pytest.raises(LlmValidationError, match="retry_after_s"):
            LlmRateLimited(retry_after_s=value)  # type: ignore[arg-type]


def test_json_module_is_not_leaked_into_dto_equality() -> None:
    # Two specs built from differently ordered dicts are equal (canonical JSON).
    a = JsonSchemaSpec.from_schema("s", {"a": 1, "b": 2})
    b = JsonSchemaSpec.from_schema("s", json.loads('{"b": 2, "a": 1}'))

    assert a == b


class TestHugeNumbers:
    """Python ints are unbounded: math.isfinite(1 << 1500) raises OverflowError."""

    @pytest.mark.parametrize("field", ["temperature", "timeout_s"])
    @pytest.mark.parametrize("huge", [1 << 1500, -(1 << 1500), 2**53, 10**400])
    def test_huge_integers_are_validation_errors_not_overflow_errors(
        self, field: str, huge: int
    ) -> None:
        with pytest.raises(LlmValidationError, match=field):
            make_request(**{field: huge})

    def test_is_finite_number_boundaries(self) -> None:
        from eventssound.application.llm import is_finite_number

        assert is_finite_number(2**53 - 1) and is_finite_number(-(2**53 - 1))
        assert is_finite_number(1.5) and is_finite_number(0)
        assert not is_finite_number(2**53)
        assert not is_finite_number(1 << 1500)
        assert not is_finite_number(float("nan")) and not is_finite_number(float("inf"))
        assert not is_finite_number(True) and not is_finite_number("1")
        assert not is_finite_number(None)
