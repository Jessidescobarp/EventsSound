---
name: architecture-hexagonal
description: "Trigger: hexagonal, layers, ports, adapters, composition root, new use case, where does this code go. Place backend code in the right layer."
license: Apache-2.0
metadata:
  author: eventssound
  version: "1.0"
---

## Activation Contract

Use when adding or moving backend code under `backend/src/eventssound/`, creating a port or adapter, wiring dependencies, or reviewing a change that crosses layers.

## Hard Rules

Layers and what each owns:

| Layer | Owns | May import |
| ----- | ---- | ---------- |
| `domain/` | Pure business rules, entities, value objects, deterministic pricing (`calcular_precio`, planned) | stdlib only |
| `application/` | Use cases and ports (`typing.Protocol`) | `domain` |
| `adapters/` | Port implementations: SQLAlchemy (`adapters/db/`), LLM providers (`adapters/llm/`, planned) | `application`, `domain`, frameworks |
| `entrypoints/` | FastAPI app factory, routes, composition root | everything inward |

- Dependency rule: `domain <- application <- adapters <- entrypoints`. Imports point inward only.
- `domain` must not import FastAPI, SQLAlchemy, pydantic-settings, Alembic, or `eventssound.config`.
- `application` must not import `adapters` or `entrypoints`; it sees the outside world only through ports.
- `adapters` must not import `entrypoints`.
- Only the composition root, `entrypoints/api/container.py`, constructs concrete adapters and binds them to ports.
- `create_app(settings, ..., database_health=None)` accepts overrides so tests inject fakes; keep that seam for every new port.
- Routes stay thin: parse request, call a use case, map the result to HTTP. No business rules, no SQL.
- Never leak internals in responses: `/health/db` returns only `{"status": "degraded", "database": "unavailable"}` on failure.

## Decision Gates

| New thing | Goes in |
| --------- | ------- |
| Business rule, price calculation, validation of domain invariants | `domain/` |
| Orchestration of a user action (check readiness, build a quote) | `application/<use_case>.py` |
| Interface the core needs from the outside (DB, LLM, clock) | `application/ports.py` as a Protocol |
| SQLAlchemy model, query, engine, session | `adapters/db/` |
| LLM client (Replay, OpenRouter, Ollama) | `adapters/llm/` (planned) |
| HTTP route, request/response schema, dependency wiring | `entrypoints/api/` |
| Env var or secret | `config.py` (`Settings`), read only at the edges |
| Binding adapter to port | `entrypoints/api/container.py` |
| LangGraph agent graph | `application/` for nodes and use case, `adapters/` for tool implementations (planned) |

## How the rule is enforced

`backend/tests/unit/test_architecture.py` parses every `.py` file with `ast`, resolves relative imports, and fails if a layer imports a forbidden module (map `FORBIDDEN`). It also tests the scanner itself (leaky import detected, relative import detected, intra-layer import allowed).

- Adding a new framework dependency (for example `langgraph`)? Add it to `FRAMEWORKS` so `domain` stays free of it.
- Never weaken `FORBIDDEN` to make a change pass; move the code instead.

## Execution Steps

1. Write the failing test first (unit test with a fake for the port).
2. Define or reuse the port in `application/ports.py`:

```python
class DatabaseHealthPort(Protocol):
    def ping(self) -> None: ...
```

3. Write the use case against the port only (`application/health.py::check_database`).
4. Implement the adapter (`adapters/db/health.py::SqlAlchemyDatabaseHealth`), receiving its dependencies in `__init__`.
5. Bind it in `container.py` (`make_database_health(factory)`) and expose an override parameter in `create_app`.
6. Add the route; run `uv run pytest` (includes the architecture test) and `uv run ruff check .`.

## Anti-patterns

- A use case that imports `sqlalchemy.orm.Session` or `Settings` directly.
- A route that builds an adapter inline instead of reading it from `app.state`.
- ORM models used as domain entities across layers.
- A "base repository" or generic port created before two real implementations need it (P0 design forbids speculative abstractions).
- Importing `eventssound.config` from `domain`; pass plain values in.
- Business rules (price, discounts) inside a prompt or a route; prices come from `calcular_precio`, never from the LLM.

## Output Contract

Report: layer chosen per new file, ports added, container changes, and that the architecture test passes.

## References

- `docs/agents-and-documentation` branch: `documentacion/architecture.md` (planned location on main)
- `openspec/changes/walking-skeleton-and-deploy/design.md` (sections 2 and 12)
- `openspec/changes/walking-skeleton-and-deploy/specs/hexagonal-layout/spec.md`
