"""Deterministic fake embedder using feature hashing (offline, stable across processes)."""

import hashlib
import math
import re
import unicodedata
from collections.abc import Mapping, Sequence

from eventssound.application.embeddings import (
    MAX_DIMENSIONS,
    EmbeddingResult,
    normalize_texts,
)
from eventssound.application.llm import LlmValidationError, TokenUsage

_TOKEN = re.compile(r"[a-z0-9]+")


def fold_tokens(text: str) -> list[str]:
    """Lowercase, strip accents, split on non-alphanumerics."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return _TOKEN.findall(stripped)


class FakeEmbeddingProvider:
    def __init__(
        self,
        dimensions: int = 1024,
        model: str = "fake-embedding",
        aliases: Mapping[str, str] | None = None,
    ) -> None:
        if type(dimensions) is not int or not 1 <= dimensions <= MAX_DIMENSIONS:
            raise LlmValidationError(f"dimensions must be an int within 1..{MAX_DIMENSIONS}")
        self._dimensions = dimensions
        self._model = model
        self._aliases = _aliases(aliases)

    def embed(self, texts: Sequence[str], timeout_s: float = 10.0) -> EmbeddingResult:
        items = normalize_texts(texts)
        tokens = [self._tokens(text) for text in items]
        return EmbeddingResult(
            vectors=tuple(self._vector(t) for t in tokens),
            usage=TokenUsage(sum(len(t) for t in tokens), 0, estimated=True),
            model=self._model,
        )

    def _tokens(self, text: str) -> list[str]:
        return [self._aliases.get(token, token) for token in fold_tokens(text)]

    def _vector(self, tokens: list[str]) -> tuple[float, ...]:
        values = [0.0] * self._dimensions
        for token in tokens:
            digest = int.from_bytes(hashlib.blake2b(token.encode(), digest_size=8).digest(), "big")
            values[digest % self._dimensions] += 1.0 if (digest >> 32) & 1 else -1.0
        norm = math.sqrt(sum(v * v for v in values))
        if norm == 0.0:  # no tokens, or a cancelling collision: pgvector rejects zero vectors
            return (1.0, *([0.0] * (self._dimensions - 1)))
        return tuple(v / norm for v in values)


def _aliases(aliases: Mapping[str, str] | None) -> dict[str, str]:
    if aliases is None:
        return {}
    if not isinstance(aliases, Mapping) or not all(
        isinstance(k, str) and k and isinstance(v, str) for k, v in aliases.items()
    ):
        raise LlmValidationError("aliases must map non-empty strings to strings")
    folded: dict[str, str] = {}
    for source, target in aliases.items():
        source_tokens, target_tokens = fold_tokens(source), fold_tokens(target)
        if len(source_tokens) != 1 or len(target_tokens) != 1:
            raise LlmValidationError("aliases must map one word to one word")
        folded[source_tokens[0]] = target_tokens[0]
    return folded
