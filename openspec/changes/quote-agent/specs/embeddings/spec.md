# Delta Spec: embeddings

Change: quote-agent (decision 2: vector retrieval is IN). Port in `application/`, adapters in `adapters/llm/` (provider) and `adapters/db/` (vector column and index). Delivered as one extra PR after persistence and before deploy.

## ADDED Requirements

### Requirement: EmbeddingProvider port
`application/` MUST define `EmbeddingProvider.embed(texts: Sequence[str]) -> EmbeddingResult` where `EmbeddingResult` has `vectors: tuple[tuple[float, ...], ...]` (same order and length as input), `usage: TokenUsage` and `model`. Every vector MUST have exactly `settings.embedding_dimensions` components; a provider returning another size MUST raise `EmbeddingDimensionMismatch`. Errors reuse the typed taxonomy of `llm-provider` (`LlmTimeout`, `LlmRateLimited`, `LlmUnavailable`, `LlmBadResponse`, `LlmAuthError`). Empty input MUST return an empty result without a call.

#### Scenario: Dimension mismatch rejected
- Given a provider configured for 1024 dimensions that returns a 768-dimension vector
- When `embed` is called
- Then `EmbeddingDimensionMismatch` is raised and nothing is stored

#### Scenario: Empty input
- Given an empty list of texts
- When `embed` is called
- Then an empty result is returned and no request is made

### Requirement: Deterministic fake and replay provider
A `FakeEmbeddingProvider` MUST produce deterministic, unit-norm vectors of the configured dimension from the input text (stable across processes and platforms, no randomness, no network) such that equal texts give equal vectors and texts sharing tokens have higher cosine similarity than texts sharing none. A `ReplayEmbeddingProvider` MAY load precomputed vectors keyed by text id for golden scenarios; a missing key MUST raise a typed error naming the key, not the text.

#### Scenario: Determinism
- Given the fake provider
- When the same text is embedded twice in separate instances
- Then the vectors are identical

#### Scenario: Token overlap ranks higher
- Given texts "parlante activo 15 pulgadas", "parlante potente" and "maquina de humo"
- When embedded by the fake
- Then cosine(first, second) > cosine(first, third)

### Requirement: OpenRouter embeddings adapter
`OpenRouterEmbeddingProvider` MUST call the OpenAI-compatible `/embeddings` endpoint via `httpx` with the same key handling, timeouts, redirect policy, byte cap and error mapping as the chat adapter. Model id and dimensions MUST come from `Settings`. Inputs MUST be truncated or rejected before sending according to a settings token/char limit (512-token context for the candidate model). Tests MUST use `httpx.MockTransport` only.

#### Scenario: Success
- Given a mock response with one embedding of the configured dimension
- When `embed(["x"])` is called
- Then one vector and the reported usage are returned

#### Scenario: Error mapping
- Given mock responses 401, 429, 500, timeout and malformed JSON
- When `embed` is called
- Then the typed errors from `llm-provider` are raised and no key or body text appears in messages or logs

#### Scenario: Provider returns fewer vectors than inputs
- Given 3 inputs and a response with 2 embeddings
- When `embed` is called
- Then `LlmBadResponse` is raised

### Requirement: Catalog embeddings computed at seed time
The seed process MUST compute one embedding per catalog item (and per package) from a deterministic text built from name, category and code tokens, and store it in a pgvector column. The seed MUST be idempotent: re-running with unchanged text MUST NOT call the provider again (a stored content hash decides). A changed text MUST re-embed only that row. If the provider is unavailable the seed MUST still upsert catalog rows with a NULL embedding and report how many rows lack one; retrieval then uses keyword search for them. Embeddings MUST NOT be computed per chat request for catalog rows.

#### Scenario: Idempotent seed
- Given a seeded catalog with embeddings and the fake provider counting calls
- When the seed runs again with unchanged data
- Then the provider receives zero calls and row content is identical

#### Scenario: Edited item re-embeds only itself
- Given one item whose name changes
- When the seed runs
- Then exactly one text is embedded

#### Scenario: Provider down at seed time
- Given a provider raising `LlmUnavailable`
- When the seed runs
- Then catalog rows are upserted with NULL embeddings and the summary reports the missing count

### Requirement: pgvector storage, migration and index
A dedicated reversible Alembic revision (after the latest head, one concern: schema only) MUST execute `CREATE EXTENSION IF NOT EXISTS vector` and add a nullable `embedding vector(N)` column plus `embedding_hash` to the embedded tables, where N equals `settings.embedding_dimensions` at migration authoring time (a fixed literal in the revision, since revisions are frozen history). `downgrade()` MUST drop the columns and MUST NOT drop the extension (other objects may use it). With about 20 items an exact scan (no ANN index) MUST be used; no HNSW/IVFFlat index is created, and the decision is documented with the threshold (> ~1,000 rows or > 2,000 dims reopens it). Dimension at runtime and in the column MUST agree: startup or the first repository call MUST fail with a clear error if `settings.embedding_dimensions` differs from the column dimension. Migration tests MUST run against the `pgvector/pgvector:pg16` image under `DATABASE_URL_TEST` (skip only when unset, fail when unreachable).

#### Scenario: Upgrade, downgrade, upgrade
- Given a pgvector database at the previous head
- When the revision is upgraded, downgraded and upgraded again
- Then the extension exists, the column exists after upgrade, is absent after downgrade, and the extension remains

#### Scenario: Drift check
- Given the migrated database
- When metadata is compared with the models
- Then the diff is empty

#### Scenario: Wrong dimension stored
- Given a column of dimension N
- When a vector of another length is written through the repository
- Then `EmbeddingDimensionMismatch` is raised before the statement runs and the row is unchanged

#### Scenario: Settings and column disagree
- Given `EMBEDDING_DIMENSIONS` different from the column dimension
- When the app starts retrieval wiring
- Then a configuration error is raised that names both numbers

### Requirement: Query embedding with cache
Each chat message that needs retrieval MUST embed the normalized query once. A bounded in-process LRU cache keyed by the normalized query text (max entries and TTL from settings) MUST serve repeated queries without a provider call. Cached entries MUST NOT be shared across different model or dimension settings.

#### Scenario: Cache hit
- Given the same query twice within TTL
- When retrieval runs twice
- Then the provider receives one call

#### Scenario: Cache bound
- Given a cache of max 2 entries and 3 distinct queries
- When retrieval runs
- Then the oldest entry is evicted and size never exceeds 2

### Requirement: Graceful fallback to keyword retrieval
When the embedding provider raises `LlmTimeout`, `LlmRateLimited`, `LlmUnavailable`, `LlmBadResponse` or `LlmAuthError`, or the free-limit budget for embeddings is exhausted, retrieval MUST fall back to the keyword adapter for that call, return results in the same shape, and log one WARNING with the error class (no query text). The chat MUST NOT fail because embeddings failed. Embedding tokens MUST count toward the daily token cap (see `cost-cap`).

#### Scenario: Provider failure
- Given an embedding provider raising `LlmRateLimited`
- When a user asks for "parlantes para 150 personas"
- Then the keyword adapter answers, the response is a normal result, and one fallback warning is logged

#### Scenario: Rows without embeddings
- Given an item with NULL embedding
- When vector search runs
- Then the whole call falls back to the keyword adapter (one WARNING), so the item stays reachable and is never silently dropped
