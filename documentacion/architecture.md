# Architecture

## Hexagonal layers (backend)

```
entrypoints  ->  adapters  ->  application  ->  domain
(FastAPI)       (SQLAlchemy,    (use cases,      (pure rules)
                 LLM, ...)      ports)
```

- `domain`: pure rules, no framework imports.
- `application`: use cases and ports (Protocols), e.g. `DatabaseHealthPort`.
- `adapters`: port implementations (database session and health today; LLM providers later).
- `entrypoints`: FastAPI app factory, routes, and the composition root where adapters are wired.

The rule is checked by an AST-based architecture test. The composition root is the only place that constructs adapters, and the extension point for the future `LlmProvider`.

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
