"""LLM port: one `complete` call, typed DTOs and the provider error taxonomy.

Stdlib only. The agent is a fixed pipeline, so the port carries no tool calling; structured
output is requested through `ResponseFormat` and an optional JSON schema. Provider errors never
carry provider text, URLs, headers or keys: messages are constants.
"""

import json
import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

MAX_MESSAGES = 50
MAX_MESSAGE_CHARS = 50_000
MAX_OUTPUT_TOKENS = 4096
MAX_TIMEOUT_S = 300
MAX_SCHEMA_CHARS = 20_000
MAX_TOKENS = 2**31
MAX_JSON_DEPTH = 32

_NODE = re.compile(r"[a-z][a-z0-9_]{0,31}")
# Dot-separated words, so ".", ".." and path-like names are refused; 1..64 characters.
_IDENTIFIER = re.compile(r"(?=.{1,64}\Z)[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*")


class LlmValidationError(ValueError):
    """A DTO was built with invalid data (a programming error, not a provider failure)."""


class LlmError(Exception):
    """Base of every failure a provider may raise. Messages are generic constants."""

    default_message = "LLM provider error"

    def __init__(self) -> None:
        super().__init__(self.default_message)


class LlmTimeout(LlmError):
    default_message = "LLM provider timed out"


class LlmUnavailable(LlmError):
    default_message = "LLM provider unavailable"


class LlmBadResponse(LlmError):
    default_message = "LLM provider returned an unusable response"


class LlmAuthError(LlmError):
    default_message = "LLM provider rejected the credentials"


class LlmRateLimited(LlmError):
    default_message = "LLM provider rate limit reached"

    def __init__(self, retry_after_s: int | None = None) -> None:
        if retry_after_s is not None:
            _int(retry_after_s, "retry_after_s", 0, 86_400)
        super().__init__()
        self.retry_after_s = retry_after_s


def _int(value: object, name: str, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise LlmValidationError(f"{name} must be an int within {low}..{high}")
    return value


def is_finite_number(value: object) -> bool:
    """A real int below 2**53 in magnitude, or a finite float. Never raises.

    Python ints are unbounded and `math.isfinite(1 << 1500)` raises OverflowError, so ints
    beyond what a float represents exactly are refused instead of converted.
    """
    if type(value) is int:
        return abs(value) < 2**53
    return type(value) is float and math.isfinite(value)


def _number(value: object, name: str, low: float, high: float, *, open_low: bool = False) -> float:
    if not is_finite_number(value):
        raise LlmValidationError(f"{name} must be a finite number")
    if value < low or value > high or (open_low and value == low):  # type: ignore[operator]
        raise LlmValidationError(f"{name} is out of range")
    return value  # type: ignore[return-value]


def _text(value: object, name: str, max_chars: int) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= max_chars:
        raise LlmValidationError(f"{name} must be a string of 1..{max_chars} characters")
    return value


def _json_copy(value: object, name: str, depth: int = 0) -> object:
    """Deep copy of a JSON value, rejecting anything json.loads could not have produced."""
    if depth > MAX_JSON_DEPTH:
        raise LlmValidationError(f"{name} is nested too deeply")
    if value is None or type(value) in (bool, str, int):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    if type(value) in (list, tuple):
        return [_json_copy(item, name, depth + 1) for item in value]  # type: ignore[attr-defined]
    if type(value) is dict:
        if not all(type(key) is str for key in value):
            raise LlmValidationError(f"{name} must only have string keys")
        return {key: _json_copy(item, name, depth + 1) for key, item in value.items()}
    raise LlmValidationError(f"{name} must be plain JSON data")


class Role(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class ResponseFormat(StrEnum):
    TEXT = "text"
    JSON = "json"


@dataclass(frozen=True, slots=True)
class LlmMessage:
    role: Role
    content: str

    def __post_init__(self) -> None:
        if not isinstance(self.role, Role):
            raise LlmValidationError("role must be a Role")
        _text(self.content, "content", MAX_MESSAGE_CHARS)


@dataclass(frozen=True, slots=True)
class JsonSchemaSpec:
    """A named JSON Schema, stored as canonical JSON text so the value stays hashable."""

    name: str
    schema_json: str

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not _IDENTIFIER.fullmatch(self.name):
            raise LlmValidationError("name must be dot-separated words, 1..64 chars")
        _text(self.schema_json, "schema", MAX_SCHEMA_CHARS)
        try:
            parsed = json.loads(self.schema_json)
        except (ValueError, RecursionError):
            raise LlmValidationError("schema must be valid JSON") from None
        if type(parsed) is not dict:
            raise LlmValidationError("schema must be a JSON object")

    @classmethod
    def from_schema(cls, name: str, schema: Mapping[str, object]) -> "JsonSchemaSpec":
        if type(schema) is not dict:
            raise LlmValidationError("schema must be a dict")
        plain = _json_copy(schema, "schema")
        return cls(name, json.dumps(plain, sort_keys=True, separators=(",", ":")))

    @property
    def schema(self) -> dict[str, object]:
        """A fresh copy on every access."""
        return json.loads(self.schema_json)  # type: ignore[no-any-return]


@dataclass(frozen=True, slots=True)
class LlmRequest:
    node: str
    messages: tuple[LlmMessage, ...]
    response_format: ResponseFormat = ResponseFormat.TEXT
    json_schema: JsonSchemaSpec | None = None
    temperature: float = 0.0
    max_output_tokens: int = 1024
    timeout_s: float = 30.0
    scenario: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "messages", _messages(self.messages))
        check_node(self.node)
        if self.scenario is not None:
            check_scenario(self.scenario)
        if not isinstance(self.response_format, ResponseFormat):
            raise LlmValidationError("response_format must be a ResponseFormat")
        if self.json_schema is not None and (
            not isinstance(self.json_schema, JsonSchemaSpec)
            or self.response_format is not ResponseFormat.JSON
        ):
            raise LlmValidationError("json_schema needs a JsonSchemaSpec and JSON response_format")
        _number(self.temperature, "temperature", 0, 2)
        _int(self.max_output_tokens, "max_output_tokens", 1, MAX_OUTPUT_TOKENS)
        _number(self.timeout_s, "timeout_s", 0, MAX_TIMEOUT_S, open_low=True)


def check_node(value: object) -> str:
    if not isinstance(value, str) or not _NODE.fullmatch(value):
        raise LlmValidationError("node must match [a-z][a-z0-9_]{0,31}")
    return value


def check_scenario(value: object) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise LlmValidationError("scenario must be dot-separated words, 1..64 chars")
    return value


def _messages(value: object) -> tuple[LlmMessage, ...]:
    """Coerce to a tuple; a string is never an iterable of messages."""
    if isinstance(value, str | bytes) or not isinstance(value, Iterable):
        raise LlmValidationError("messages must be a collection of LlmMessage")
    messages = tuple(value)
    if not 1 <= len(messages) <= MAX_MESSAGES:
        raise LlmValidationError(f"messages must hold 1..{MAX_MESSAGES} items")
    if not all(isinstance(message, LlmMessage) for message in messages):
        raise LlmValidationError("messages must contain only LlmMessage")
    return messages


@dataclass(frozen=True, slots=True)
class TokenUsage:
    prompt_tokens: int
    completion_tokens: int
    estimated: bool = False

    def __post_init__(self) -> None:
        _int(self.prompt_tokens, "prompt_tokens", 0, MAX_TOKENS)
        _int(self.completion_tokens, "completion_tokens", 0, MAX_TOKENS)
        if type(self.estimated) is not bool:
            raise LlmValidationError("estimated must be a bool")

    @property
    def total(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass(frozen=True, slots=True)
class LlmResponse:
    text: str
    usage: TokenUsage
    model: str
    finish_reason: str | None = None
    latency_ms: int = 0
    # Derived from `text` when JSON was requested; excluded from eq/hash (dicts are unhashable).
    parsed: dict[str, object] | None = field(default=None, compare=False, hash=False)

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise LlmValidationError("text must be a string")
        if not isinstance(self.usage, TokenUsage):
            raise LlmValidationError("usage must be a TokenUsage")
        _text(self.model, "model", 200)
        if self.finish_reason is not None:
            _text(self.finish_reason, "finish_reason", 64)
        _int(self.latency_ms, "latency_ms", 0, 86_400_000)
        if self.parsed is not None:
            if type(self.parsed) is not dict:
                raise LlmValidationError("parsed must be a dict")
            object.__setattr__(self, "parsed", _json_copy(self.parsed, "parsed"))


class LlmProvider(Protocol):
    def complete(self, request: LlmRequest) -> LlmResponse:
        """Return one completion or raise an `LlmError` subclass."""
        ...


def estimate_tokens(chars: int) -> int:
    """Conservative token estimate (ceil(chars / 4), never 0) for providers that omit usage."""
    _int(chars, "chars", 0, 2**40)
    return max(1, -(-chars // 4))


def estimate_cost_micro_usd(usage: TokenUsage, input_price: int, output_price: int) -> int:
    """Cost in micro-USD from prices in micro-USD per million tokens, rounded up per side."""
    if not isinstance(usage, TokenUsage):
        raise LlmValidationError("usage must be a TokenUsage")
    _int(input_price, "input_price", 0, 10**12)
    _int(output_price, "output_price", 0, 10**12)
    per_million = 1_000_000
    return (usage.prompt_tokens * input_price + per_million - 1) // per_million + (
        usage.completion_tokens * output_price + per_million - 1
    ) // per_million
