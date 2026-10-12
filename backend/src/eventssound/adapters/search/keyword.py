"""Keyword search over a Catalog: pure, deterministic, no I/O. Also the evals baseline."""

import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from eventssound.adapters.search.synonyms import CATEGORY_ES
from eventssound.adapters.search.text import tokens
from eventssound.adapters.search.validation import check_search_args
from eventssound.application.search import SearchHit, SearchResult
from eventssound.domain.catalog import Catalog, EquipmentCategory


@dataclass(frozen=True, slots=True)
class _Document:
    kind: str
    code: str
    category: EquipmentCategory | None
    tokens: frozenset[str]


def _words(code: str) -> str:
    return code.replace("_", " ")


class KeywordSearch:
    """Score = sum of idf of the matched query tokens / sum of idf of all query tokens."""

    def __init__(self, catalog: Catalog) -> None:
        documents = [
            _Document(
                "item",
                item.code,
                item.category,
                frozenset(tokens(f"{item.name} {CATEGORY_ES[item.category]} {_words(item.code)}")),
            )
            for item in catalog.items
        ]
        for package in catalog.packages:
            members = " ".join(catalog.item(line.item_code).name for line in package.lines)
            documents.append(
                _Document(
                    "package",
                    package.code,
                    None,
                    frozenset(tokens(f"{package.name} {members} {_words(package.code)}")),
                )
            )
        self._documents = tuple(documents)
        frequency = Counter(token for doc in documents for token in doc.tokens)
        count = len(documents)
        self._idf = {token: math.log(1 + count / df) for token, df in frequency.items()}
        self._unknown_idf = math.log(1 + count)  # a token in no document counts as df = 1

    def search(
        self, queries: Sequence[str], category: EquipmentCategory | None, limit: int
    ) -> tuple[SearchResult, ...]:
        normalized = check_search_args(queries, category, limit)
        return tuple(self._one(query, category, limit) for query in normalized)

    def _one(self, query: str, category: EquipmentCategory | None, limit: int) -> SearchResult:
        wanted = sorted(set(tokens(query)))
        weights = {token: self._idf.get(token, self._unknown_idf) for token in wanted}
        total = sum(weights.values())
        scored: list[tuple[float, str, str]] = []
        for doc in self._documents:
            if category is not None and doc.category is not category:
                continue
            matched = sum(weights[token] for token in wanted if token in doc.tokens)
            if matched > 0:
                scored.append((round(matched / total, 9), doc.code, doc.kind))
        scored.sort(key=lambda row: (-row[0], row[2] != "item", row[1]))
        return SearchResult(
            tuple(
                SearchHit(kind, code, rank, keyword_score=score)  # type: ignore[arg-type]
                for rank, (score, code, kind) in enumerate(scored[:limit], start=1)
            )
        )
