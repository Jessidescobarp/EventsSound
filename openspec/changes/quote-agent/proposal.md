# Proposal: quote-agent (P2 agent core + P3 evals and hardening)

## Intent
Deliver the heart of the TFM: a public Spanish chat where an LLM agent turns a free-text event request into a validated, priced quote and a written proposal. Prices NEVER come from the LLM: `calculate_price` (quote-domain-core A3) is the source and the final answer is checked against it (decision 9). Why now: P2/P3 are scheduled Oct 15-21, the MVP deadline is 2026-10-25, and the chat is also the public attack and cost surface (OWASP GenAI), so hardening and evals ship in the same change, not after.

## Scope

### In
1. **`LlmProvider` port** (`application/`, dataclasses only: pydantic is forbidden in `application/` by `test_architecture.py`) returning text or JSON plus `TokenUsage` and model name. Adapters in `adapters/llm/`: `ReplayProvider` (hand-authored fixtures keyed by scenario and node, NOT by prompt hash, so prompt edits do not break CI), `OpenRouterProvider` (httpx, OpenAI-compatible; no LangChain provider packages), `build_llm_provider(settings)` in `container.py`. Ollama: OUT (optional later; the port allows it). Cost accounting: pure `usage -> cost` using a price table in config; free models cost 0 but still count against the token cap.
2. **Tools** as plain application functions with strict Pydantic argument schemas (`extra="forbid"`, bounded lengths) in `adapters/agent/`: `buscar_equipamiento(query, category?)`, `consultar_disponibilidad(request)`, `calcular_precio(request)`. Read-only, no side effects. Allowlist enforced by the graph, not by the model.
3. **Retrieval decision: keyword, no embeddings.** The catalog has 20 items and 4 packages. Accent-folded token match plus a small Spanish synonym map and category filter, behind an `EquipmentSearch` port so an embedding adapter can replace it. This drops a pgvector migration, an embedding provider and about 500-600 lines. UNVERIFIED (no network check possible here): Neon free pgvector support (taken from `decisions.md` #2) and whether OpenRouter serves an embeddings endpoint on a free model. Evals measure retrieval recall; reopen only if recall is poor.
4. **LangGraph quote agent** (`adapters/agent/`, behind a `QuoteAgent` port used by a `quote_chat` use case): `understand` (LLM -> structured request or clarification question) -> `resolve_items` (`buscar_equipamiento`; LLM may only pick codes present in results) -> `check_availability` -> `price` (deterministic) -> `draft` (LLM writes Spanish text from the validated `Quote`) -> `verify` (every peso amount in the text must equal a `Quote` amount, no URLs, length cap; on failure use a deterministic Spanish template rendered from the `Quote`). Fixed pipeline with one conditional edge (clarify or proceed), max 3 LLM calls and one JSON repair retry per request: bounded cost and robust on free models with weak tool calling. LangGraph is isolated in `adapters/`, so the application layer stays framework-free.
5. **`POST /quote/chat`**, public, non-streaming, Pydantic schemas, OpenAPI examples (contract below).
6. **Hardening**: caps (<= 16 messages, <= 1000 chars each, <= 4000 total, control chars stripped); system prompt with a delimited untrusted-data block and a canary token; schema-validated structured outputs; tool allowlist; per-IP rate limit; daily token/cost cap; kill switch; logs with request id, status, token counts, tool names and durations only (never message content, keys or IPs in clear).
7. **Evals**: golden set of 15-20 synthetic requests, oracle (`quoted total == calculate_price(expected request)` computed at test time, items valid and available), 6-8 injection cases, pytest in replay mode in CI; optional live run with LangSmith traces for slide screenshots.

### Out
Frontend chat page (P4, own change; contract below), auth/admin/JWT, voice, payments, streaming, Ollama, embeddings, persistence of conversations or quotes (see open questions), booking creation, multi-language.

## Approach and key decisions
- **Stateless conversation.** The client sends the last <= 16 messages. Stored conversations add a table, retention and a PII surface for no demo benefit. Tampering is harmless because assistant history is never trusted for numbers: the request is re-extracted and re-priced each turn, so a forged "the price was $1" cannot change a total.
- **Non-streaming first.** The `verify` gate needs the full text before showing it; streaming would show unverified output. P4 shows progress states. SSE can be added on a separate path later.
- **Rate limit in memory (per IP, sliding window); daily cap in the database.** Render free restarts on idle, so the in-memory limiter resets, which is acceptable for burst control. The money-relevant control must survive restarts: table `llm_usage_daily(day, tokens, cost_micro_usd)` with an atomic `UPDATE ... WHERE tokens + :n <= :cap` (reserve before the call, settle after). Persistence is mandatory anyway, so this is a second honest use of the database. Until that PR merges, an in-memory budget adapter sits behind the same port.
- **Kill switch**: `CHAT_ENABLED=false` returns 503 `chat_disabled`; changing it in the Render dashboard redeploys (minutes), so setting the DB cap to 0 is the instant lever.
- **Replay tests prove pipeline logic, not model quality.** Model quality is measured only by the live eval run.

## API contract for P4 (stable surface)
`POST /quote/chat` request: `{"messages": [{"role": "user"|"assistant", "content": str}]}`, last message must be `user`. 200 response: `{"request_id", "status": "clarification"|"quote"|"refused", "reply": str (Spanish), "quote": Quote.to_dict()|null, "event_request": object|null}`. Errors use `{"detail": code}` like the catalog API: 422 validation, 429 `rate_limited` (with `Retry-After`), 503 `chat_disabled` | `daily_budget_exhausted` | `llm_unavailable`. No stack traces, host or provider text.

## Affected areas
New: `application/{llm,quote_chat}.py`, `adapters/llm/`, `adapters/agent/`, `entrypoints/api/routes/quote.py`, `adapters/db` usage repository, migration `0003`, `backend/tests/{unit,integration,evals}`. Touched: `config.py` (`llm_provider`, `openrouter_api_key` SecretStr, model, caps), `container.py`, `app.py`, `pyproject.toml` (`langgraph`, `httpx`; check Render 512 MB RAM and image size), `test_architecture.py` (allow `adapters/llm|agent`; keep application/domain rules), `render.yaml` (`sync: false` for the key), docs. Agent impact: defines tools, prompts and evals. Security impact: first public LLM surface. Possible merge friction with the domain chain in `container.py`, `config.py` and `test_architecture.py`: rebase, never weaken the test.

## Rollback
Additive. Set `CHAT_ENABLED=false` or `LLM_PROVIDER=replay` without a code change; revert PRs in reverse order; `alembic downgrade 0002` drops `llm_usage_daily`. No existing route changes.

## Success criteria
Replay suite deterministic and green in CI; every golden case total equals the oracle; injection cases never change a total or leak the canary; live run oracle match >= 90% (exploration target); a request over cap, over rate or with the switch off gets the contracted error with no LLM call; each PR <= ~450 real lines; ruff and the architecture test green.

## Review Workload Forecast
Estimates INCLUDE tests (~55-60% of each PR, measured ratio from A1). Total ~3,150 lines in 9 PRs. This is above the exploration's P2+P3 guess; the cut ladder below is the lever, NOT the agent or persistence.

| PR | Branch | Content | Est. lines | Depends on |
| -- | ------ | ------- | ---------- | ---------- |
| Q1 | `feat/agent-llm-port` | Port, DTOs, Replay adapter, scripted fake, usage and cost | ~330 | main only |
| Q2 | `feat/agent-openrouter` | OpenRouter adapter, settings, `build_llm_provider`, error mapping (httpx `MockTransport`, no live call in CI) | ~300 | Q1 |
| Q3 | `feat/agent-tools` | Keyword search, 3 tool schemas and executors, allowlist | ~410 | A1-A4 |
| Q4 | `feat/agent-graph` | Graph: understand, clarify, resolve, availability, price; validated `Quote` | ~400 | Q1, Q3 |
| Q5 | `feat/agent-proposal` | Draft node, Spanish prompts, `verify`, template fallback | ~320 | Q4 |
| Q6 | `feat/quote-chat-endpoint` | Route, schemas, caps, kill switch, in-memory limiter and budget, log hygiene | ~420 | Q5, B2 |
| Q7 | `feat/quote-cost-cap` | `llm_usage_daily`, migration 0003, atomic reserve/settle, wiring | ~350 | Q6, B1 |
| Q8 | `feat/agent-evals` | Harness, golden set 15-20, injection cases, optional LangSmith runner | ~450 | Q5, A3, B3 |
| Q9 | `docs/agent-deploy` | `render.yaml` env, deploy/README/architecture/ADRs, eval report | ~170 | Q2, Q7, Q8 |

Merge order: Q1, Q2, Q3, Q4, Q5, Q6, Q7, Q8, Q9. Same stacked-to-main procedure as quote-domain-core (retarget the child to `main` before merging the parent; ancestry check after).

**Dependency map on quote-domain-core** (A1 done, A2 rules, A3 `calculate_price`, A4 availability, B1 schema, B2 ports and repositories, B3 seed, C catalog API):

| Needs | Unblocks |
| ----- | -------- |
| nothing | Q1, Q2: start NOW, in parallel with A2-A4 (branch from `main`) |
| A1 + A2 + A3 + A4 | Q3 (tools). Tools take a `Catalog` provider and a reservations provider whose signatures match B2's `get_catalog` and `find_reservations`; tests use in-memory values until B2 merges |
| Q3 | Q4, Q5 (pure agent logic on in-memory catalog; no DB) |
| B2 (ports, SQLAlchemy repos); B3 for data in Neon | Q6 real wiring. C's `make_*` factories are used if merged, otherwise `container.py` builds the B2 repos directly |
| B1 (0002 is `down_revision`) | Q7 |
| A3 + B3 (`seed_data.py` builds the eval catalog) | Q8 |

Calendar target: Q1-Q2 Oct 12-14; Q3-Q5 Oct 15-18; Q6-Q7 Oct 18-20; Q8 Oct 20-21; Q9 Oct 22. Roughly 16 reviews (9 here plus the remaining domain PRs) in 10 days: review time is the bottleneck.

**Likely overruns and cut ladder (apply in order, ask before each):** Q8 golden set 20 -> 15 and injection 8 -> 6; Q3 drop the synonym map (keep category and tokens); Q5 reduce the template fallback to total and lines only; Q7 slips behind Q9 (the in-memory budget from Q6 stays as a documented temporary state; do NOT deploy publicly without a cap); Q9 folds into Q8 as a docs commit. Measure each PR with `git diff --shortstat <base>...HEAD -- . ':!backend/uv.lock' ':!openspec'`; STOP and ask above 450.

## Risks
- Free OpenRouter models: rate limits, weak Spanish and unreliable structured output (limits UNVERIFIED here). Mitigation: JSON-schema prompt plus Pydantic validation plus one repair retry, template fallback, Replay for CI and the video.
- Client IP behind Render's proxy: how `X-Forwarded-For` is built is UNVERIFIED; a wrong choice lets attackers evade the limiter. The DB cap is the backstop.
- Cold start (~1 min Render, Neon wake) plus LLM latency may exceed browser timeouts: P4 needs a long timeout and a "warming up" state.
- `langgraph` dependency weight on Render free; fallback is a plain Python pipeline behind the same `QuoteAgent` port.
- LangSmith traces would carry user text: off by default in production, enabled only for the eval run with synthetic input.
- Schedule: 9 plus 7 PRs in ~10 days; see cut ladder.

## Open questions (recommended default in brackets; NOT decided)
1. LLM provider, model and monthly budget? [OpenRouter, one `:free` or cheapest Spanish-capable model chosen after a 20-minute trial in Q2; cap about 100k tokens/day; the key lives only in the Render dashboard]
2. Embeddings? **DECIDED by the developer (2026-10-12): YES.** Retrieval over the catalog uses embeddings stored in Postgres with pgvector (Neon free supports `CREATE EXTENSION vector`, documented; HNSW limit 2,000 dimensions; free plan limits: 100 CU-hours/month, scale-to-zero after 5 minutes, storage 0.5 or 1 GB depending on the source). Embedding provider candidate: OpenRouter's OpenAI-compatible `/embeddings` endpoint with the free `liquid/lfm-2.5-embedding-350m:free` model (1,024 dimensions, 512-token context; exact model id UNVERIFIED, daily free limits reported as 50-200 requests/day and UNVERIFIED, provider may retain data: acceptable because data is synthetic). Design requirements: an `EmbeddingProvider` port with a Replay/deterministic fake for CI, catalog embeddings computed at seed time (not per request), a query embedding per chat message with a cache and a graceful fallback to keyword search when the provider fails or the free limit is hit, the keyword retriever kept behind the same `EquipmentSearch` port, one extra PR (about 350 real lines) AFTER persistence (B) and before deploy. This is a must-ship item together with the AI agent and database persistence.
3. Conversation storage? [Stateless]
4. Proposal language? [Spanish; instructions in English, output and refusals in Spanish]
5. LangSmith wanted? [Optional live run only, off in production]
6. Persist final quotes (needed by the P4 admin list)? [Defer to the P4 change; `quote_chat` returns the data so a persistence hook is a one-function addition]
7. Does the "RAG" claim in the TFM require embeddings? **Resolved by decision 2: yes, the project ships vector retrieval (pgvector) so the RAG claim is defensible.**
