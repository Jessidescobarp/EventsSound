"""LLM port DTOs and error taxonomy: validation, immutability, hashability."""

import json
from collections.abc import Callable, Iterable
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
    is_finite_number,
)

USER = LlmMessage(Role.USER, "hola")


def make_request(**overrides: object) -> LlmRequest:
    fields: dict[str, object] = {"node": "understand", "messages": [USER]}
    fields.update(overrides)
    return LlmRequest(**fields)  # type: ignore[arg-type]


def assert_rejects(build: Callable[[object], object], field: str, values: Iterable[object]) -> None:
    """Every value must raise a LlmValidationError that names the field."""
    for value in values:
        with pytest.raises(LlmValidationError, match=field):
            build(value)


class TestLlmMessage:
    def test_valid_message_is_frozen_and_hashable(self) -> None:
        message = LlmMessage(Role.SYSTEM, "be brief")

        assert (message.role, message.content) == (Role.SYSTEM, "be brief")
        with pytest.raises(FrozenInstanceError):
            message.content = "y"  # type: ignore[misc]
        assert hash(message) == hash(LlmMessage(Role.SYSTEM, "be brief"))

    def test_role_and_content_are_validated(self) -> None:
        assert_rejects(lambda v: LlmMessage(v, "x"), "role", ["user", None])  # type: ignore[arg-type]
        contents = ["", b"x", None, "x" * 50_001]
        assert_rejects(lambda v: LlmMessage(Role.USER, v), "content", contents)  # type: ignore[arg-type]
        assert len(LlmMessage(Role.USER, "x" * 50_000).content) == 50_000


class TestJsonSchemaSpec:
    def test_from_schema_round_trips_hashes_and_returns_a_copy(self) -> None:
        spec = JsonSchemaSpec.from_schema("extraction", {"type": "object", "b": [1], "a": {"c": 1}})

        assert spec.name == "extraction"
        assert hash(spec) == hash(JsonSchemaSpec.from_schema("extraction", spec.schema))
        spec.schema["a"]["c"] = 2
        assert spec.schema["a"] == {"c": 1}

    def test_equality_ignores_key_order(self) -> None:
        a = JsonSchemaSpec.from_schema("s", {"a": 1, "b": 2})
        b = JsonSchemaSpec.from_schema("s", json.loads('{"b": 2, "a": 1}'))

        assert a == b

    def test_name_and_schema_are_validated(self) -> None:
        names = ["", "has space", "x" * 65, "ñ", None]
        assert_rejects(lambda v: JsonSchemaSpec.from_schema(v, {"type": "object"}), "name", names)  # type: ignore[arg-type]
        schemas = [[], None, {"a": object()}, {"a": float("nan")}, {1: "x"}, {"a": "x" * 20_001}]
        assert_rejects(lambda v: JsonSchemaSpec.from_schema("s", v), "schema", schemas)  # type: ignore[arg-type]

    def test_direct_construction_validates_the_stored_json(self) -> None:
        assert_rejects(
            lambda v: JsonSchemaSpec("s", v), "schema", ["not json", "[1]", "x" * 20_001]
        )  # type: ignore[arg-type]


class TestLlmRequest:
    def test_defaults_and_tuple_coercion(self) -> None:
        request = make_request()

        assert request.messages == (USER,)
        assert request.response_format is ResponseFormat.TEXT
        assert (request.json_schema, request.scenario) == (None, None)
        assert hash(request) == hash(make_request())

    def test_accepts_any_non_string_iterable_of_messages(self) -> None:
        request = make_request(messages=(m for m in [USER, LlmMessage(Role.ASSISTANT, "ok")]))

        assert [m.role for m in request.messages] == [Role.USER, Role.ASSISTANT]

    def test_messages_must_be_a_bounded_non_empty_collection_of_messages(self) -> None:
        bad = [[], "hola", None, ["hola"], [USER, None], [USER] * 51]
        assert_rejects(lambda v: make_request(messages=v), "messages", bad)

    def test_node_is_a_short_lowercase_identifier(self) -> None:
        bad = ["", "Understand", "has space", "a" * 33, "x\n", None]
        assert_rejects(lambda v: make_request(node=v), "node", bad)

    def test_scenario_is_a_bounded_path_safe_identifier(self) -> None:
        bad = ["", "a b", "x" * 65, "ok\n", 3, "..", "a..b", ".a", "a.", "../x", "a/b"]
        assert_rejects(lambda v: make_request(scenario=v), "scenario", bad)
        for scenario in ("boda_simple.v2", "a-b_c.d.e", "x" * 64):
            assert make_request(scenario=scenario).scenario == scenario

    def test_numeric_fields_reject_bad_values_and_accept_inclusive_bounds(self) -> None:
        tokens = [0, -1, 4097, 1.0, True, None]
        assert_rejects(lambda v: make_request(max_output_tokens=v), "max_output_tokens", tokens)
        timeouts = [0, -1, float("inf"), float("nan"), True, "5", 301]
        assert_rejects(lambda v: make_request(timeout_s=v), "timeout_s", timeouts)
        temperatures = [-0.1, 2.1, float("nan"), True, "0"]
        assert_rejects(lambda v: make_request(temperature=v), "temperature", temperatures)

        assert make_request(max_output_tokens=1).max_output_tokens == 1
        assert make_request(max_output_tokens=4096).max_output_tokens == 4096
        assert make_request(timeout_s=5).timeout_s == 5

    def test_response_format_and_json_schema_rules(self) -> None:
        assert_rejects(lambda v: make_request(response_format=v), "response_format", ["json", None])
        spec = JsonSchemaSpec.from_schema("s", {"type": "object"})

        with pytest.raises(LlmValidationError, match="json_schema"):
            make_request(json_schema=spec)  # TEXT format
        with pytest.raises(LlmValidationError, match="json_schema"):
            make_request(json_schema={"type": "object"}, response_format=ResponseFormat.JSON)
        request = make_request(json_schema=spec, response_format=ResponseFormat.JSON)
        assert request.json_schema == spec


class TestTokenUsage:
    def test_total_adds_both_sides_and_zero_is_allowed(self) -> None:
        assert TokenUsage(410, 120).total == 530
        assert TokenUsage(410, 120).estimated is False
        assert TokenUsage(0, 0).total == 0

    def test_token_counts_and_flag_are_validated(self) -> None:
        for side in ("prompt_tokens", "completion_tokens"):
            for value in (-1, 1.5, True, None, 2**40):
                fields: dict[str, object] = {
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    side: value,
                }
                with pytest.raises(LlmValidationError, match=side):
                    TokenUsage(**fields)  # type: ignore[arg-type]
        assert_rejects(lambda v: TokenUsage(1, 1, estimated=v), "estimated", [1, None])  # type: ignore[arg-type]


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

    def test_valid_response_is_hashable_and_copies_parsed(self) -> None:
        source = {"a": [1]}
        response = self.make(parsed=source)

        source["a"].append(2)

        assert response.parsed == {"a": [1]}
        assert hash(response) == hash(self.make(parsed={"a": [1]}))
        assert self.make(text="").text == ""  # empty text is fine at the DTO level

    def test_invalid_fields_are_rejected(self) -> None:
        cases: list[tuple[str, list[object]]] = [
            ("text", [None, b"x"]),
            ("usage", [(1, 2)]),
            ("model", ["", 3]),
            ("finish_reason", [3]),
            ("latency_ms", [-1, 1.5, True]),
            ("parsed", [[1], {"a": object()}]),
        ]
        for field, values in cases:
            assert_rejects(lambda v, f=field: self.make(**{f: v}), field, values)


class TestErrors:
    def test_every_error_is_an_llm_error_with_a_generic_message(self) -> None:
        for error in (LlmTimeout, LlmUnavailable, LlmBadResponse, LlmAuthError, LlmRateLimited):
            exc = error()

            assert isinstance(exc, LlmError)
            assert str(exc) and "http" not in str(exc).lower()

    def test_validation_errors_are_not_provider_errors(self) -> None:
        assert not issubclass(LlmValidationError, LlmError)
        assert issubclass(LlmValidationError, ValueError)

    def test_rate_limited_carries_and_validates_retry_after(self) -> None:
        assert LlmRateLimited(retry_after_s=7).retry_after_s == 7
        assert LlmRateLimited().retry_after_s is None
        bad = [-1, 1.5, True, "7"]
        assert_rejects(lambda v: LlmRateLimited(retry_after_s=v), "retry_after_s", bad)  # type: ignore[arg-type]


class TestHugeNumbers:
    """Python ints are unbounded: math.isfinite(1 << 1500) raises OverflowError."""

    def test_huge_integers_are_validation_errors_not_overflow_errors(self) -> None:
        for field in ("temperature", "timeout_s"):
            for huge in (1 << 1500, -(1 << 1500), 2**53):
                assert_rejects(lambda v, f=field: make_request(**{f: v}), field, [huge])

    def test_is_finite_number_boundaries(self) -> None:
        assert is_finite_number(2**53 - 1) and is_finite_number(-(2**53 - 1))
        assert is_finite_number(1.5) and is_finite_number(0)
        assert not is_finite_number(2**53)
        assert not is_finite_number(1 << 1500)
        assert not is_finite_number(float("nan")) and not is_finite_number(float("inf"))
        assert not is_finite_number(True) and not is_finite_number("1")
        assert not is_finite_number(None)
