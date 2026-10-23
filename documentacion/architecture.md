# Architecture

## Hexagonal layers (backend)

```
entrypoints  ->  adapters  ->  application  ->  domain
(FastAPI)       (SQLAlchemy,    (use cases,      (pure rules)
                 LLM, ...)      ports)
```

- `domain`: pure rules, stdlib only: `Money`, catalog entities, `EventRequest`, pricing rules, `calculate_price` (the deterministic oracle), availability.
- `application`: use cases and ports (Protocols): `DatabaseHealthPort`, `CatalogRepository`, `BookingRepository`, `LlmProvider`, `EquipmentSearch` and the repositories for users, quotes, portfolio and agent configuration. Use cases are plain functions over ports (`list_catalog`, `price_quote`, `check_event_availability`, the quote chat).
- `adapters`: port implementations (SQLAlchemy repositories, search, LLM providers, the agent graph, evals).
- Vector retrieval: `adapters/db/vector.py` (a hand-written `vector(N)` column type, no `pgvector` package), `catalog_embeddings` (migration `0003`), `SqlAlchemyEmbeddingStore`, `VectorSearch` and `HybridSearch` (keywords always, vectors when configured, reciprocal rank fusion, keyword fallback with `degraded=True`). `refresh_embeddings` is idempotent and driven by the guarded `embed_catalog` CLI.
- Agent building blocks (P2): `application/search.py` (the `EquipmentSearch` port), `adapters/search/` (Spanish text folding, synonyms, `KeywordSearch`) and `adapters/agent/` (strict tool schemas and the `ToolExecutor` with the three allowlisted tools). Prices only ever come from `calcular_precio`, which calls the domain oracle; a test scans `adapters/agent/` for money arithmetic.
- Agent (P2-P3): a LangGraph pipeline in `adapters/agent/`. The agent is stateless: each request carries the conversation and every turn re-extracts the request. Code owns Spanish dates, clock time, duration and guest count (`application/spanish_dates.py`, `application/spanish_facts.py`); model JSON is parsed tolerantly (`adapters/llm/parsing.py`). `LlmProvider` has Replay (tests) and OpenRouter adapters. Prices come only from the oracle, and the proposal text is verified against the computed quote (`application/proposal_check.py`).
- Admin agent configuration: domain model, validation and hard ceilings in `domain/agent_config.py`; the per-model price table in `domain/model_prices.py`; versioned storage with an audit trail in `agent_settings` and `agent_settings_audit` (migration `0010`); `ActiveConfigProvider` (`application/agent_config.py`, short cache with last-good fallback) feeds the chat, budget and rate limit; the preview/apply flow and confirmation tokens are in `application/agent_config_admin.py` and `application/confirmation.py`.
- `entrypoints`: FastAPI app factory, routes and response schemas, and the composition root where adapters are wired. Routes never import adapters (checked by the architecture test). Swagger UI is public at `/docs`.

The rule is checked by an AST-based architecture test. The composition root is the only place that constructs adapters, and the extension point for the future `LlmProvider`.

Quote domain and catalog API: [quote-domain-core](../openspec/changes/quote-domain-core/design.md).

Spec: [hexagonal-layout](../openspec/changes/walking-skeleton-and-deploy/specs/hexagonal-layout/spec.md). Design: [design.md](../openspec/changes/walking-skeleton-and-deploy/design.md).

## Deployment topology

```
Browser -> Render static site (React) -> Render web service (FastAPI, Docker) -> Neon Postgres
```

- Backend: Render free web service built from `backend/Dockerfile`; migrations run at start (`alembic upgrade head`).
- Frontend: Render static site; reads the API URL from `VITE_API_BASE_URL`.
- Database: Neon free tier (not Render Postgres), with pgvector.
- Health: `/health` is liveness (no DB); `/health/db` is readiness.

Spec: [deployment](../openspec/changes/walking-skeleton-and-deploy/specs/deployment/spec.md).

## Stack

- Backend: Python 3.12, FastAPI, SQLAlchemy 2, Alembic, pydantic-settings, LangGraph, pytest, ruff, uv.
- Frontend: Vite, React, TypeScript, Vitest; Spanish UI copy in `frontend/src/copy/es.ts`.
- LLM and embeddings through OpenRouter (`bge-m3` embeddings, 1024 dimensions); a Replay provider for deterministic tests.
- Evals: a golden set with a price oracle, run in CI with a scripted provider; a manual live trial CLI (`model_trial`) for real models.
- CI: GitHub Actions (`.github/workflows/ci.yml`).
