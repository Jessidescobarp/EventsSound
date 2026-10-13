"""structured_call: complete + parse + validate with exactly one bounded repair (D12).

The model text is untrusted. Only a parsed, size- and depth-capped JSON object is validated
against the pydantic model; a failure costs one repair completion that shows failing field
paths and error codes (never the offending values, which can be user-controlled). A second
failure raises `StructuredOutputInvalid`.
"""

import json
import time
from collections.abc import Sequence

from pydantic import BaseModel, ValidationError

from eventssound.adapters.llm.parsing import _is_safe
from eventssound.application.llm import (
    JsonSchemaSpec,
    LlmError,
    LlmMessage,
    LlmProvider,
    LlmRequest,
    ResponseFormat,
    Role,
)
from eventssound.application.quote_chat import AgentLimitExceeded, ChatLimits, UsageMeter

PER_CALL_TIMEOUT_S = 25.0
_MAX_JSON_CHARS = 200_000
_MAX_JSON_DEPTH = 32


class StructuredOutputInvalid(Exception):
    """The model produced unusable structured output even after the one repair."""


class DeadlineExceeded(LlmError):
    """Not enough time left in the request deadline for another LLM call."""

    default_message = "request deadline exceeded"


class _InvalidOutput(Exception):
    """Internal: the response text is not a usable JSON object."""


def _extract_json_object(text: str) -> dict[str, object]:
    if len(text) > _MAX_JSON_CHARS:
        raise _InvalidOutput
    # No explicit fence stripping: the balanced scan below extracts the object even inside
    # ```json fences, and trusting "starts with a fence" would be an extra way to be fooled.
    stripped = text.strip()
    start = stripped.find("{")
    if start < 0:
        raise _InvalidOutput
    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(stripped)):
        char = stripped[i]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                candidate = stripped[start : i + 1]
                try:
                    parsed = json.loads(candidate)
                except (ValueError, RecursionError):
                    raise _InvalidOutput from None
                if type(parsed) is not dict or not _is_safe(parsed):
                    raise _InvalidOutput
                return parsed
    raise _InvalidOutput


def _complete(
    provider: LlmProvider,
    messages: Sequence[LlmMessage],
    *,
    node: str,
    model_cls: type[BaseModel],
    meter: UsageMeter,
    limits: ChatLimits,
    deadline_monotonic: float,
    temperature: float,
    max_output_tokens: int,
    scenario: str | None,
) -> str:
    if meter.llm_calls >= limits.max_llm_calls:
        raise AgentLimitExceeded(f"llm call cap {limits.max_llm_calls} reached")
    remaining = deadline_monotonic - time.monotonic()
    if remaining <= 0:
        raise DeadlineExceeded()
    meter.llm_calls += 1
    response = provider.complete(
        LlmRequest(
            node=node,
            messages=tuple(messages),
            response_format=ResponseFormat.JSON,
            json_schema=JsonSchemaSpec.from_schema(node, model_cls.model_json_schema()),
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            timeout_s=min(PER_CALL_TIMEOUT_S, remaining),
            scenario=scenario,
        )
    )
    meter.prompt_tokens += response.usage.prompt_tokens
    meter.completion_tokens += response.usage.completion_tokens
    if response.finish_reason == "length":
        raise _InvalidOutput
    return response.text


def _failure_note(failure: _InvalidOutput | ValidationError) -> str:
    if isinstance(failure, _InvalidOutput):
        problems = "the text was not a JSON object"
    else:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['type']}"
            for error in failure.errors()
        )
    return (
        f"Your previous response was invalid. Problems: {problems}. "
        "Reply with a single JSON object and nothing else."
    )


def structured_call[M: BaseModel](
    *,
    provider: LlmProvider,
    node: str,
    messages: Sequence[LlmMessage],
    model_cls: type[M],
    meter: UsageMeter,
    limits: ChatLimits,
    deadline_monotonic: float,
    temperature: float = 0.0,
    max_output_tokens: int = 400,
    scenario: str | None = None,
) -> M:
    """One structured completion, plus at most one repair. LlmError propagates to the caller."""
    current_messages: tuple[LlmMessage, ...] = tuple(messages)
    text = ""
    for _attempt in (1, 2):
        try:
            text = _complete(
                provider,
                current_messages,
                node=node,
                model_cls=model_cls,
                meter=meter,
                limits=limits,
                deadline_monotonic=deadline_monotonic,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
                scenario=scenario,
            )
            return model_cls.model_validate(_extract_json_object(text))
        except _InvalidOutput as exc:
            failure: _InvalidOutput | ValidationError = exc
        except ValidationError as exc:
            failure = exc
        if meter.repairs >= 1:
            raise StructuredOutputInvalid() from failure
        meter.repairs += 1
        current_messages = current_messages + (
            LlmMessage(Role.ASSISTANT, text or "(no output)"),
            LlmMessage(Role.USER, _failure_note(failure)),
        )
    raise StructuredOutputInvalid()
