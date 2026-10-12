"""Embedding index: the store port and the idempotent refresh use case. Stdlib only.

The text embedded for an entry covers only what a customer would search by (name, category,
package members), never prices or stock, so editing those does not trigger a re-embedding.
`content_hash` is `sha256(model + "\\n" + text)`: a model change or a text change re-embeds.
"""

import hashlib
import math
import re
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

from eventssound.application.embeddings import EmbeddingProvider
from eventssound.application.llm import LlmBadResponse
from eventssound.application.search import CATEGORY_ES
from eventssound.domain.catalog import Catalog, EquipmentItem, ServicePackage

MAX_BATCH = 64
MAX_MODEL_CHARS = 120
_CODE = re.compile(r"[a-z0-9_]{3,64}")
_HASH = re.compile(r"[0-9a-f]{64}")


def _check_model(model: object) -> str:
    if not isinstance(model, str) or not 1 <= len(model.strip()) <= MAX_MODEL_CHARS:
        raise ValueError(f"model must be a string of 1..{MAX_MODEL_CHARS} characters")
    return model


@dataclass(frozen=True, slots=True)
class StoredEmbedding:
    kind: Literal["item", "package"]
    code: str
    content_hash: str
    vector: tuple[float, ...]

    def __post_init__(self) -> None:
        if self.kind not in ("item", "package"):
            raise ValueError("kind must be 'item' or 'package'")
        if not isinstance(self.code, str) or not _CODE.fullmatch(self.code):
            raise ValueError("code must match [a-z0-9_]{3,64}")
        if not isinstance(self.content_hash, str) or not _HASH.fullmatch(self.content_hash):
            raise ValueError("content_hash must be 64 lowercase hex characters")
        vector = tuple(self.vector)
        try:
            finite = all(type(x) in (int, float) and math.isfinite(x) for x in vector)
        except OverflowError:
            finite = False
        if not vector or not finite:
            raise ValueError("vector must be a non-empty tuple of finite numbers")
        object.__setattr__(self, "vector", tuple(float(x) for x in vector))


@dataclass(frozen=True, slots=True)
class VectorMatch:
    """One nearest-neighbour row. `similarity` is cosine similarity clamped to [0, 1]."""

    kind: Literal["item", "package"]
    code: str
    similarity: float


@runtime_checkable
class EmbeddingStore(Protocol):
    """Persistent embeddings, one active model at a time. Storage errors raise
    RepositoryUnavailable; a vector of the wrong size raises EmbeddingDimensionMismatch."""

    def existing_hashes(self, model: str) -> dict[tuple[str, str], str]:
        """`(kind, code) -> content_hash` of the rows stored for `model`."""
        ...

    def upsert(self, model: str, rows: Sequence[StoredEmbedding]) -> None: ...

    def prune(self, model: str, keep: Collection[tuple[str, str]]) -> int:
        """Delete every row of another model and every row of `model` not in `keep`."""
        ...

    def nearest(self, model: str, vector: Sequence[float], limit: int) -> tuple[VectorMatch, ...]:
        """Rows of `model` by descending cosine similarity, ties by (kind, code)."""
        ...


@dataclass(frozen=True, slots=True)
class RefreshResult:
    embedded: int
    skipped: int
    deleted: int


def embedding_text(entry: EquipmentItem | ServicePackage, catalog: Catalog) -> str:
    if isinstance(entry, EquipmentItem):
        return f"{entry.name}. Categoria: {CATEGORY_ES[entry.category]}."
    members = ", ".join(catalog.item(line.item_code).name for line in entry.lines)
    return f"{entry.name}. Incluye: {members}."


def content_hash(model: str, text: str) -> str:
    return hashlib.sha256(f"{model}\n{text}".encode()).hexdigest()


def refresh_embeddings(
    catalog: Catalog,
    embedder: EmbeddingProvider,
    store: EmbeddingStore,
    model: str,
    batch_size: int = 16,
) -> RefreshResult:
    """Embed new or changed entries, then delete orphans and rows of other models.

    Batches are stored as they complete, so a failure midway keeps the finished batches and a
    rerun embeds only the rest. Orphans are deleted last: a failed run never leaves the store
    emptier than it found it.
    """
    _check_model(model)
    if type(batch_size) is not int or not 1 <= batch_size <= MAX_BATCH:
        raise ValueError(f"batch_size must be an int within 1..{MAX_BATCH}")
    entries: list[tuple[str, str, str, str]] = []  # kind, code, text, hash
    for item in catalog.items:
        text = embedding_text(item, catalog)
        entries.append(("item", item.code, text, content_hash(model, text)))
    for package in catalog.packages:
        text = embedding_text(package, catalog)
        entries.append(("package", package.code, text, content_hash(model, text)))

    existing = store.existing_hashes(model)
    pending = [e for e in entries if existing.get((e[0], e[1])) != e[3]]
    for start in range(0, len(pending), batch_size):
        batch = pending[start : start + batch_size]
        result = embedder.embed([entry[2] for entry in batch])
        if len(result.vectors) != len(batch):
            raise LlmBadResponse()
        store.upsert(
            model,
            [
                StoredEmbedding(kind, code, digest, vector)  # type: ignore[arg-type]
                for (kind, code, _text, digest), vector in zip(batch, result.vectors, strict=True)
            ],
        )
    deleted = store.prune(model, {(kind, code) for kind, code, _t, _h in entries})
    return RefreshResult(
        embedded=len(pending), skipped=len(entries) - len(pending), deleted=deleted
    )
