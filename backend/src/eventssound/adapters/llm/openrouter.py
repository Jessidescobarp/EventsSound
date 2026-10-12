"""OpenRouter chat adapter (OpenAI-compatible /chat/completions) over httpx.

The API key and model id are constructor arguments: this module reads no Settings and no
environment. The key is held in a masked `Secret` and only unwrapped when a request is sent.
"""

from types import TracebackType
from typing import Any

from eventssound.adapters.openrouter_http import (
    DEFAULT_BASE_URL,
    OpenRouterHttp,
    check_model_id,
)
from eventssound.application.llm import (
    LlmBadResponse,
    LlmRequest,
    LlmResponse,
    LlmValidationError,
    ResponseFormat,
    TokenUsage,
    estimate_tokens,
)

from .parsing import parse_json_object

__all__ = ["DEFAULT_BASE_URL", "OpenRouterProvider"]

_MAX_TOKENS = 2**31


class OpenRouterProvider:
    def __init__(self, api_key: object, model: str, **http_options: Any) -> None:
        self._model = check_model_id(model)
        self._http = OpenRouterHttp(api_key, **http_options)

    def __repr__(self) -> str:
        return f"OpenRouterProvider(model={self._model!r})"

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "OpenRouterProvider":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def complete(self, request: LlmRequest) -> LlmResponse:
        if not isinstance(request, LlmRequest):
            raise LlmValidationError("request must be an LlmRequest")
        started = self._http.now()
        data = self._http.post_json(
            "/chat/completions",
            self._body(request),
            timeout_s=request.timeout_s,
            label=request.node,
            model=self._model,
        )
        text, finish_reason = _first_choice(data)
        return LlmResponse(
            text=text,
            usage=_usage(data.get("usage"), request, text),
            model=_model_name(data.get("model"), self._model),
            finish_reason=finish_reason,
            latency_ms=int((self._http.now() - started) * 1000),
            parsed=parse_json_object(text)
            if request.response_format is ResponseFormat.JSON
            else None,
        )

    def _body(self, request: LlmRequest) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self._model,
            "messages": [{"role": m.role.value, "content": m.content} for m in request.messages],
            "temperature": request.temperature,
            "max_tokens": request.max_output_tokens,
            "stream": False,
        }
        if request.response_format is ResponseFormat.JSON:
            spec = request.json_schema
            body["response_format"] = (
                {"type": "json_object"}
                if spec is None
                else {
                    "type": "json_schema",
                    "json_schema": {"name": spec.name, "schema": spec.schema, "strict": True},
                }
            )
        return body


def _first_choice(data: dict[str, Any]) -> tuple[str, str | None]:
    choices = data.get("choices")
    choice = choices[0] if isinstance(choices, list) and choices else None
    message = choice.get("message") if isinstance(choice, dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise LlmBadResponse()
    finish = choice.get("finish_reason")
    return content, finish if isinstance(finish, str) and 0 < len(finish) <= 64 else None


def _model_name(value: object, configured: str) -> str:
    return value if isinstance(value, str) and 0 < len(value) <= 200 else configured


def _usage(raw: object, request: LlmRequest, text: str) -> TokenUsage:
    if isinstance(raw, dict):
        prompt, completion = raw.get("prompt_tokens"), raw.get("completion_tokens")
        if all(type(n) is int and 0 <= n <= _MAX_TOKENS for n in (prompt, completion)):
            return TokenUsage(prompt, completion)  # type: ignore[arg-type]
    chars = sum(len(message.content) for message in request.messages)
    return TokenUsage(estimate_tokens(chars), estimate_tokens(len(text)), estimated=True)
