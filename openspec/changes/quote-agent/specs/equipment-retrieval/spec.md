# Delta Spec: equipment-retrieval

Change: quote-agent. Port in `application/`; keyword adapter (pure Python over a `Catalog`) and vector adapter (pgvector) in `adapters/`. Read-only.

## ADDED Requirements

### Requirement: EquipmentSearch port
`application/` MUST define `EquipmentSearch.search(query: str, category: EquipmentCategory | None, limit: int) -> tuple[SearchHit, ...]` with `SearchHit(code, name, category, unit_price: Money, score: float, kind in {item, package})`. Hits MUST reference only codes present in the current `Catalog`. `limit` MUST be 1..10 (default 5); out-of-range values MUST raise a validation error. `query` MUST be 1..200 characters after normalization.

#### Scenario: Limit bound
- Given `limit=0` or `limit=11`
- When `search` is called
- Then a validation error is raised

#### Scenario: Only real codes
- Given any query
- When `search` returns hits
- Then every `code` exists in the catalog

### Requirement: Query normalization
Queries MUST be normalized before matching: Unicode NFKC, case-folded, accents stripped (so `parlante`, `Parlánte` and `PARLANTE` are equal, and `ñ` folds consistently on both sides), control and zero-width characters removed, whitespace collapsed. Catalog text MUST be normalized the same way.

#### Scenario: Accent and case folding
- Given an item named "Micrófono inalámbrico"
- When searching "microfono inalambrico" and "MICRÓFONO"
- Then the item is a hit in both

#### Scenario: Zero-width characters
- Given the query "par​lante"
- When normalized
- Then it equals "parlante"

### Requirement: Keyword adapter ranking
`KeywordEquipmentSearch` MUST score by token overlap (name and code tokens, with a small Spanish synonym map such as `bafle`/`parlante`/`altavoz`, `luces`/`iluminacion`, `humo`/`neblina`), then rank by descending score with ties broken by `code` ascending so output is deterministic. Items with score 0 MUST NOT be returned.

#### Scenario: Synonym match
- Given a catalog with "Parlante activo 15 pulgadas"
- When searching "bafle"
- Then that item is returned

#### Scenario: Deterministic ties
- Given two items with equal scores
- When searched repeatedly
- Then the order is by ascending `code` every time

### Requirement: Vector adapter ranking
`VectorEquipmentSearch` MUST embed the query through `EmbeddingProvider` (with the cache from `embeddings`), order by cosine distance computed in the database, convert to a score in [0, 1], drop hits below a settings minimum score, and break ties by `code`. It MUST apply the category filter and `limit` in the query, not after fetching.

#### Scenario: Semantic match
- Given the fake embedding provider and seeded embeddings
- When searching "equipo para mezclar musica en vivo"
- Then the top hits include DJ or mixer items ranked above unrelated effects

#### Scenario: Below threshold dropped
- Given a query unrelated to every row
- When searched
- Then the result is empty

### Requirement: Composite search with fallback
The wired `EquipmentSearch` MUST try the vector adapter first when embeddings are enabled and fall back to the keyword adapter on any error listed in `embeddings`. With embeddings disabled by settings, only the keyword adapter MUST run.

#### Scenario: Fallback keeps contract
- Given a failing embedding provider
- When searching "luces"
- Then keyword hits are returned with the same `SearchHit` shape

### Requirement: Category filter
When `category` is given, all hits MUST belong to it; an unknown category value MUST be rejected at the tool boundary, not silently ignored.

#### Scenario: Filter applied
- Given a query matching items in `sound` and `dj`
- When searched with category `dj`
- Then only `dj` hits are returned

### Requirement: Empty results and no invention
When nothing matches, the result MUST be an empty tuple. The retrieval layer MUST NOT fabricate codes, names or prices, and MUST NOT return nearest-neighbour items below the minimum score just to fill `limit`.

#### Scenario: No match
- Given the query "submarino nuclear"
- When searched
- Then an empty tuple is returned

### Requirement: Retrieval quality is measured
The eval suite MUST include a retrieval set of at least 15 (query, expected code) pairs in Spanish (with accents, without accents, with synonyms) and report recall@k (k=5) for the keyword and vector adapters separately. In replay mode with the fake embedder the keyword adapter MUST reach recall@5 >= 0.8 on the set.

#### Scenario: Recall report
- Given the retrieval set
- When the eval runs
- Then it prints recall@5 per adapter and fails CI if the keyword adapter is below 0.8
