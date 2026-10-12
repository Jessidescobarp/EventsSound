# Architecture

## Hexagonal layers (backend)

```
entrypoints  ->  adapters  ->  application  ->  domain
(FastAPI)       (SQLAlchemy,    (use cases,      (pure rules)
                 LLM, ...)      ports)
```

- `domain`: pure rules, stdlib only: `Money`, catalog entities, `EventRequest`, pricing rules, `calculate_price` (the deterministic oracle), availability.
- `application`: use cases and ports (Protocols): `DatabaseHealthPort`, `CatalogRepository`, `BookingRepository`. Use cases are plain functions over ports (`list_catalog`, `price_quote`, `check_event_availability`).
- `adapters`: port implementations (database session and health today; LLM providers later).
- Agent building blocks (P2): `application/search.py` (the `EquipmentSearch` port), `adapters/search/` (Spanish text folding, synonyms, `KeywordSearch`) and `adapters/agent/` (strict tool schemas and the `ToolExecutor` with the three allowlisted tools). Prices only ever come from `calcular_precio`, which calls the domain oracle; a test scans `adapters/agent/` for money arithmetic.
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
- Database: Neon free tier (not Render Postgres). pgvector is needed from P2.
- Health: `/health` is liveness (no DB); `/health/db` is readiness.

Spec: [deployment](../openspec/changes/walking-skeleton-and-deploy/specs/deployment/spec.md).

## Planned stack

- Backend: Python, FastAPI, SQLAlchemy 2, Alembic, pydantic-settings, pytest, ruff, uv.
- Frontend: Vite, React, TypeScript, Vitest (shadcn/ui from P4).
- Agent (P2): LangGraph, `LlmProvider` port with Replay and OpenRouter adapters.
- Evals (P3): golden set with a price oracle; LangSmith optional.
- CI: GitHub Actions (PR 3).
