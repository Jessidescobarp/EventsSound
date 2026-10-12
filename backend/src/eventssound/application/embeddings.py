"""Embedding port: `embed` returns one vector per text, errors reuse the LLM taxonomy.

Stdlib only. A provider that returns the wrong dimension raises `EmbeddingDimensionMismatch`,
which is an `LlmBadResponse`, so one `except LlmError` covers every provider failure.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Protocol

from .llm import LlmBadResponse, LlmValidationError, TokenUsage, is_finite_number

MAX_TEXTS = 64
MAX_TEXT_CHARS = 2_000
MAX_DIMENSIONS = 2_000


class EmbeddingDimensionMismatch(LlmBadResponse):
    default_message = "Embedding provider returned vectors of an unexpected dimension"


def _vectors(value: object) -> tuple[tuple[float, ...], ...]:
    if isinstance(value, str | bytes) or not isinstance(value, Iterable):
        raise LlmValidationError("vectors must be a collection of numeric vectors")
    vectors = []
    for raw in value:
        if isinstance(raw, str | bytes) or not isinstance(raw, Iterable):
            raise LlmValidationError("vectors must contain only numeric vectors")
        components = tuple(raw)
        valid = all(is_finite_number(x) for x in components)
        if not components or not valid:
            raise LlmValidationError("vectors must hold non-empty finite numbers")
        vectors.append(tuple(float(x) for x in components))
    if len({len(v) for v in vectors}) > 1:
        raise LlmValidationError("vectors must all have the same length")
    return tuple(vectors)


@dataclass(frozen=True, slots=True)
class EmbeddingResult:
    vectors: tuple[tuple[float, ...], ...]
    usage: TokenUsage
    model: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "vectors", _vectors(self.vectors))
        if not isinstance(self.usage, TokenUsage):
            raise LlmValidationError("usage must be a TokenUsage")
        if not isinstance(self.model, str) or not 1 <= len(self.model) <= 200:
            raise LlmValidationError("model must be a non-empty string")

    @property
    def dimensions(self) -> int:
        return len(self.vectors[0]) if self.vectors else 0


class EmbeddingProvider(Protocol):
    def embed(self, texts: Sequence[str], timeout_s: float = 10.0) -> EmbeddingResult:
        """One vector per text, in order. Empty input returns an empty result without a call."""
        ...


def normalize_texts(
    texts: object, *, max_texts: int = MAX_TEXTS, max_chars: int = MAX_TEXT_CHARS
) -> tuple[str, ...]:
    """Validate embedding inputs; a string is never an iterable of texts."""
    if isinstance(texts, str | bytes) or not isinstance(texts, Iterable):
        raise LlmValidationError("texts must be a collection of strings")
    items = tuple(texts)
    if len(items) > max_texts:
        raise LlmValidationError(f"texts must hold at most {max_texts} items")
    if not all(isinstance(item, str) for item in items):
        raise LlmValidationError("texts must contain only strings")
    if any(not item.strip() for item in items):
        raise LlmValidationError("texts must not contain blank strings")
    if any(len(item) > max_chars for item in items):
        raise LlmValidationError(f"each text must have at most {max_chars} characters")
    return items
