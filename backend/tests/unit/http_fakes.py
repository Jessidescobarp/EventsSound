"""Shared fakes for the OpenRouter adapter tests: scripted MockTransport, clock and sleeper."""

import json
from collections.abc import Callable

import httpx

KEY = "sk-test-SENTINEL-9f3a"
BODY_SENTINEL = "SECRET-BODY-4417"

Scripted = httpx.Response | Exception | Callable[[httpx.Request], httpx.Response]


class FakeClock:
    """Monotonic clock that only moves when the adapter sleeps."""

    def __init__(self) -> None:
        self.now = 100.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class Script:
    """A MockTransport that answers from a queue and records every request it saw."""

    def __init__(self, *items: Scripted) -> None:
        self._items = list(items)
        self.requests: list[httpx.Request] = []

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert self._items, "the adapter made more requests than the test scripted"
        item = self._items.pop(0)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, httpx.Response):
            return item
        return item(request)

    @property
    def calls(self) -> int:
        return len(self.requests)

    def body(self, index: int = 0) -> dict[str, object]:
        return json.loads(self.requests[index].content)  # type: ignore[no-any-return]


def reply(payload: object, status: int = 200, **headers: str) -> httpx.Response:
    return httpx.Response(status, json=payload, headers=headers)


def raw(content: bytes, status: int = 200, **headers: str) -> httpx.Response:
    return httpx.Response(status, content=content, headers=headers)


def chat_ok(
    text: str = "hola",
    usage: object = None,
    model: object = "provider/model-x",
    finish_reason: object = "stop",
) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": "gen-1",
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": finish_reason,
            }
        ],
    }
    payload["usage"] = {"prompt_tokens": 410, "completion_tokens": 120} if usage is None else usage
    if usage == "omit":
        del payload["usage"]
    return payload
