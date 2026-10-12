"""Offline providers: Replay (scenario + node keyed fixtures) and a scripted test double.

Replay never hashes prompts, so editing a prompt cannot break CI. Entries for one
`(scenario, node)` are consumed in order, which models repair retries.
"""

import threading
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from eventssound.application.llm import (
    LlmAuthError,
    LlmBadResponse,
    LlmError,
    LlmRateLimited,
    LlmRequest,
    LlmResponse,
    LlmTimeout,
    LlmUnavailable,
    LlmValidationError,
    ResponseFormat,
    TokenUsage,
    check_node,
    check_scenario,
)

from .parsing import parse_json_object

DEFAULT_MODEL = "replay-model"
_ERRORS: dict[str, type[LlmError]] = {
    "timeout": LlmTimeout,
    "rate_limited": LlmRateLimited,
    "unavailable": LlmUnavailable,
    "auth": LlmAuthError,
    "bad_response": LlmBadResponse,
}
_NO_USAGE = TokenUsage(0, 0)


class ReplayMissing(Exception):
    """No entry left for `(scenario, node)`. A test failure, deliberately not an `LlmError`."""

    def __init__(self, scenario: str | None, node: str, index: int) -> None:
        super().__init__(f"no replay entry for scenario={scenario!r} node={node!r} index={index}")
        self.scenario = scenario
        self.node = node
        self.index = index


class ReplayNotConsumed(AssertionError):
    """A fixture entry was never used: the scenario is stale."""


class ScriptExhausted(AssertionError):
    """A `ScriptedProvider` was called more times than it was scripted for."""


@dataclass(frozen=True, slots=True)
class ReplayEntry:
    text: str = ""
    usage: TokenUsage = _NO_USAGE
    model: str = DEFAULT_MODEL
    finish_reason: str | None = "stop"
    error: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise LlmValidationError("text must be a string")
        if not isinstance(self.usage, TokenUsage):
            raise LlmValidationError("usage must be a TokenUsage")
        if not isinstance(self.model, str) or not self.model:
            raise LlmValidationError("model must be a non-empty string")
        if self.finish_reason is not None and not isinstance(self.finish_reason, str):
            raise LlmValidationError("finish_reason must be a string or None")
        if self.error is not None and (
            not isinstance(self.error, str) or self.error not in _ERRORS
        ):
            raise LlmValidationError(f"error must be one of {sorted(_ERRORS)}")


class ReplayProvider:
    def __init__(
        self,
        scripts: Mapping[str, Mapping[str, Sequence[ReplayEntry]]],
        *,
        scenario: str | None = None,
    ) -> None:
        if not isinstance(scripts, Mapping):
            raise LlmValidationError("scripts must be a mapping of scenario to node entries")
        self._scenario = None if scenario is None else check_scenario(scenario)
        self._entries: dict[tuple[str, str], tuple[ReplayEntry, ...]] = {}
        for scenario_name, nodes in scripts.items():
            check_scenario(scenario_name)
            if not isinstance(nodes, Mapping):
                raise LlmValidationError("scenario calls must be a mapping of node to entries")
            for node, entries in nodes.items():
                if isinstance(entries, str | bytes) or not isinstance(entries, Iterable):
                    raise LlmValidationError("entries must be a collection of ReplayEntry")
                items = tuple(entries)
                if not items or not all(isinstance(item, ReplayEntry) for item in items):
                    raise LlmValidationError("entries must be a non-empty tuple of ReplayEntry")
                self._entries[(scenario_name, check_node(node))] = items
        self._cursor: dict[tuple[str, str], int] = {}
        self._lock = threading.Lock()

    @classmethod
    def from_documents(
        cls, documents: Iterable[Mapping[str, object]], *, scenario: str | None = None
    ) -> "ReplayProvider":
        """Build from fixture documents (the JSON shape of the design, already parsed)."""
        if isinstance(documents, str | bytes | Mapping) or not isinstance(documents, Iterable):
            raise LlmValidationError("documents must be a list of fixture documents")
        scripts: dict[str, dict[str, list[ReplayEntry]]] = {}
        for document in documents:
            if not isinstance(document, Mapping):
                raise LlmValidationError("each document must be a mapping")
            name = check_scenario(document.get("scenario"))
            if name in scripts:
                raise LlmValidationError("duplicate scenario in documents")
            scripts[name] = _parse_calls(document)
        return cls(scripts, scenario=scenario)

    def complete(self, request: LlmRequest) -> LlmResponse:
        scenario = request.scenario if request.scenario is not None else self._scenario
        key = (scenario or "", request.node)
        with self._lock:
            entries = self._entries.get(key, ())
            index = self._cursor.get(key, 0)
            if index >= len(entries):
                raise ReplayMissing(scenario, request.node, index)
            self._cursor[key] = index + 1
        entry = entries[index]
        if entry.error is not None:
            raise _ERRORS[entry.error]()
        parsed = (
            parse_json_object(entry.text)
            if request.response_format is ResponseFormat.JSON
            else None
        )
        return LlmResponse(
            text=entry.text,
            usage=entry.usage,
            model=entry.model,
            finish_reason=entry.finish_reason,
            parsed=parsed,
        )

    def assert_all_consumed(self) -> None:
        with self._lock:
            stale = [
                f"{scenario}/{node}: {len(entries) - self._cursor.get((scenario, node), 0)} of "
                f"{len(entries)} unused"
                for (scenario, node), entries in sorted(self._entries.items())
                if self._cursor.get((scenario, node), 0) < len(entries)
            ]
        if stale:
            raise ReplayNotConsumed("; ".join(stale))


def _parse_calls(document: Mapping[str, object]) -> dict[str, list[ReplayEntry]]:
    default_model = document.get("model", DEFAULT_MODEL)
    calls = document.get("calls")
    if not isinstance(calls, Mapping):
        raise LlmValidationError("calls must be a mapping of node to entries")
    parsed: dict[str, list[ReplayEntry]] = {}
    for node, raw_entries in calls.items():
        if isinstance(raw_entries, str | bytes) or not isinstance(raw_entries, Iterable):
            raise LlmValidationError("entries must be a list")
        parsed[node] = [_parse_entry(raw, default_model) for raw in raw_entries]
    return parsed


def _parse_entry(raw: object, default_model: object) -> ReplayEntry:
    if not isinstance(raw, Mapping):
        raise LlmValidationError("each entry must be a mapping")
    model = raw.get("model", default_model)
    if raw.get("error") is not None:
        return ReplayEntry(error=raw["error"], model=model)  # type: ignore[arg-type]
    usage = raw.get("usage")
    if not isinstance(usage, Mapping) or not {"prompt_tokens", "completion_tokens"} <= usage.keys():
        raise LlmValidationError("usage needs prompt_tokens and completion_tokens")
    return ReplayEntry(
        text=raw.get("text"),  # type: ignore[arg-type]
        usage=TokenUsage(usage["prompt_tokens"], usage["completion_tokens"]),
        model=model,  # type: ignore[arg-type]
        finish_reason=raw.get("finish_reason", "stop"),  # type: ignore[arg-type]
    )


class ScriptedProvider:
    """Test double: returns queued responses or raises queued errors, recording every request."""

    def __init__(self, script: Sequence[LlmResponse | LlmError]) -> None:
        if isinstance(script, str | bytes) or not isinstance(script, Iterable):
            raise LlmValidationError("script must be a sequence of responses or errors")
        items = tuple(script)
        if not all(isinstance(item, LlmResponse | LlmError) for item in items):
            raise LlmValidationError("script items must be LlmResponse or LlmError instances")
        self._queue = list(items)
        self.calls: list[LlmRequest] = []
        self._lock = threading.Lock()

    def complete(self, request: LlmRequest) -> LlmResponse:
        with self._lock:
            self.calls.append(request)
            if not self._queue:
                raise ScriptExhausted(
                    f"unscripted call {len(self.calls)} for node {request.node!r}"
                )
            item = self._queue.pop(0)
        if isinstance(item, LlmError):
            raise item
        return item
