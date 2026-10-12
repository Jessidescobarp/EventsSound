"""OpenRouter embeddings adapter (OpenAI-compatible POST /embeddings) over httpx.

Model id and dimension are required constructor arguments: no model id is hard-coded here
because the candidate free model is unverified. Vectors of any other size are rejected.
"""

from collections.abc import Sequence
from types import TracebackType
from typing import Any

from eventssound.adapters.openrouter_http import OpenRouterHttp, check_int, check_model_id
from eventssound.application.embeddings import (
    MAX_DIMENSIONS,
    MAX_TEXT_CHARS,
    EmbeddingDimensionMismatch,
    EmbeddingResult,
    normalize_texts,
)
from eventssound.application.llm import (
    LlmBadResponse,
    TokenUsage,
    check_timeout,
    estimate_tokens,
    is_finite_number,
)

_MAX_TOKENS = 2**31


class OpenRouterEmbeddingProvider:
    def __init__(
        self,
        api_key: object,
        model: str,
        dimensions: int,
        *,
        max_input_chars: int = MAX_TEXT_CHARS,
        **http_options: Any,
    ) -> None:
        self._model = check_model_id(model)
        self._dimensions = check_int(dimensions, "dimensions", 1, MAX_DIMENSIONS)
        self._max_chars = check_int(max_input_chars, "max_input_chars", 1, 100_000)
        self._http = OpenRouterHttp(api_key, **http_options)

    def __repr__(self) -> str:
        return f"OpenRouterEmbeddingProvider(model={self._model!r}, dimensions={self._dimensions})"

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "OpenRouterEmbeddingProvider":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def embed(self, texts: Sequence[str], timeout_s: float = 10.0) -> EmbeddingResult:
        items = normalize_texts(texts, max_chars=self._max_chars)
        timeout = check_timeout(timeout_s)
        if not items:
            return EmbeddingResult((), TokenUsage(0, 0), self._model)
        data = self._http.post_json(
            "/embeddings",
            {"model": self._model, "input": list(items)},
            timeout_s=timeout,
            label="embeddings",
            model=self._model,
        )
        vectors = self._vectors(data.get("data"), len(items))
        chars = sum(len(item) for item in items)
        model = data.get("model")
        return EmbeddingResult(
            vectors=vectors,
            usage=_usage(data.get("usage"), chars),
            model=model if isinstance(model, str) and 0 < len(model) <= 200 else self._model,
        )

    def _vectors(self, data: object, expected: int) -> tuple[tuple[float, ...], ...]:
        if not isinstance(data, list) or len(data) != expected:
            raise LlmBadResponse()
        by_index: dict[int, tuple[float, ...]] = {}
        for item in data:
            index = item.get("index") if isinstance(item, dict) else None
            embedding = item.get("embedding") if isinstance(item, dict) else None
            if type(index) is not int or index in by_index or not 0 <= index < expected:
                raise LlmBadResponse()
            if not isinstance(embedding, list) or not all(is_finite_number(x) for x in embedding):
                raise LlmBadResponse()
            by_index[index] = tuple(float(x) for x in embedding)
        if any(len(vector) != self._dimensions for vector in by_index.values()):
            raise EmbeddingDimensionMismatch()
        return tuple(by_index[i] for i in range(expected))


def _usage(raw: object, chars: int) -> TokenUsage:
    prompt = raw.get("prompt_tokens") if isinstance(raw, dict) else None
    if type(prompt) is int and 0 <= prompt <= _MAX_TOKENS:
        return TokenUsage(prompt, 0)
    return TokenUsage(estimate_tokens(chars), 0, estimated=True)
