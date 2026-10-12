"""Opt-in recorder that decorates a real provider and drafts a replay fixture.

OFF by default: with `enabled=False` it is a pure pass-through that stores nothing, and only
a real `True` enables it. Request messages and API keys are never stored; only node, text,
usage, model and finish reason are. WARNING: the response text can echo user text (a model may
quote the conversation), so use synthetic inputs only and review every recorded file before it
is committed. It is meant for a developer-run CLI, never for the app wiring.
"""

import json
import threading
from pathlib import Path

from eventssound.application.llm import (
    LlmProvider,
    LlmRequest,
    LlmResponse,
    LlmValidationError,
    check_scenario,
)


class RecordingProvider:
    def __init__(self, inner: LlmProvider, scenario: str, *, enabled: bool = False) -> None:
        if type(enabled) is not bool:
            raise LlmValidationError("enabled must be a bool")
        self._inner = inner
        self._scenario = check_scenario(scenario)
        self._enabled = enabled
        self._calls: dict[str, list[dict[str, object]]] = {}
        self._lock = threading.Lock()

    def complete(self, request: LlmRequest) -> LlmResponse:
        response = self._inner.complete(request)  # failures propagate and are not recorded
        if self._enabled:
            entry: dict[str, object] = {
                "text": response.text,
                "usage": {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                },
                "model": response.model,
                "finish_reason": response.finish_reason,
            }
            with self._lock:
                self._calls.setdefault(request.node, []).append(entry)
        return response

    def to_fixture(self) -> dict[str, object]:
        with self._lock:
            calls = {node: list(entries) for node, entries in self._calls.items()}
        return {"scenario": self._scenario, "description": "", "calls": calls}

    def write(self, path: Path) -> None:
        if not self._enabled:
            raise LlmValidationError("recording is disabled")
        path.write_text(
            json.dumps(self.to_fixture(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
