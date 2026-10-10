---
name: design-patterns
description: "Trigger: design pattern, repository, strategy, factory, facade, adapter, pipeline, LlmProvider, agent graph, over-engineering. Choose patterns only when justified."
license: Apache-2.0
metadata:
  author: eventssound
  version: "1.0"
---

## Activation Contract

Use when introducing an abstraction, a new port, a provider, or multiple interchangeable behaviors. Default to the simplest code; add a pattern only when a second real use exists or a test needs the seam.

## Hard Rules

- YAGNI first: the P0 design forbids base repositories, `LlmProvider`, or pgvector code before a feature needs them.
- A pattern needs a named problem in this codebase. "It might be useful later" is not one.
- Python favors `typing.Protocol`, plain functions, and dataclasses over deep class hierarchies.
- Patterns live inside the hexagonal layers (see `architecture-hexagonal`): ports in `application/`, implementations in `adapters/`, wiring in `container.py`.

## Patterns in this project

### Adapter (ports and adapters)
- Intent: let the core talk to a stable interface while the outside varies.
- Example: `DatabaseHealthPort` (`application/ports.py`) implemented by `SqlAlchemyDatabaseHealth` (`adapters/db/health.py`).
- Not when: wrapping a library that is already the interface you want and will never be swapped, inside an adapter.

### Repository
- Intent: give the core collection-like access to aggregates without exposing SQL.
- Example (planned, P1): `EquipmentRepository` Protocol in `application/ports.py`, `SqlAlchemyEquipmentRepository` in `adapters/db/`.
- Not when: a single query for one use case; a method on the adapter is enough. Never a generic `BaseRepository[T]` with CRUD for everything.

### Strategy
- Intent: swap an algorithm behind one interface at runtime or per environment.
- Example (planned, P2): `LlmProvider` port with Replay, OpenRouter, and Ollama adapters chosen from settings; tests use Replay for deterministic runs.
- Example (possible): pricing rules per service type behind a small `PricingRule` Protocol if rules truly vary.
- Not when: there is one implementation and no test needs a fake. Use a function.

### Factory
- Intent: centralize object construction that depends on configuration.
- Example: `create_app(settings, ...)` builds an isolated app (tests build many); `build_engine` and `build_session_factory` in `adapters/db/session.py`; `make_database_health` in `container.py`. Planned: `build_llm_provider(settings)` selecting the adapter.
- Not when: the constructor call is already one line with no branching.

### Facade
- Intent: a small entry point hiding a multi-step subsystem.
- Example (planned): a `QuoteService` use case that hides retrieval, tool calls, and price computation from the route.
- Not when: it only forwards calls one-to-one, or the route would be just as clear calling one function.

### Pipeline / graph
- Intent: model a flow as ordered steps with explicit state.
- Example (planned, P2): the LangGraph quote agent: understand request, retrieve catalog (RAG), call tools, `calcular_precio`, draft proposal. State is a typed dict; each node is a pure-ish function; tool implementations are adapters.
- Not when: a linear call chain of two steps; a LangGraph for it adds weight without benefit.

### Dependency injection (composition root)
- Intent: build the object graph in one place and pass dependencies in.
- Example: `container.py` plus overridable parameters in `create_app`. Constructor injection, no global singletons, no service locator.
- Not when: reaching for a DI framework; manual wiring is enough at this size.

## Decision Gates

| Need | Pattern | Check before adding |
| ---- | ------- | ------------------- |
| Isolate DB or LLM from core | Adapter via port | Does the core need a fake in tests? |
| Hide queries | Repository | At least two use cases share the access? |
| Interchangeable algorithms | Strategy | Two real implementations or a test double? |
| Config-dependent construction | Factory | Is there branching? |
| Simplify a route | Facade | Does it hide several steps? |
| Multi-step agent | Graph | Is state shared across steps? |

## Execution Steps

1. State the problem in one sentence.
2. Try the simplest solution (function, dataclass).
3. If it fails a concrete need (second implementation, test seam), introduce the pattern in the correct layer.
4. Add a test using a fake that implements the Protocol.
5. Wire in `container.py`; keep the architecture test green.

## Output Contract

Report: problem solved, pattern chosen, why the simpler option was rejected, and where it lives.

## References

- `backend/src/eventssound/application/ports.py`, `adapters/db/health.py`, `entrypoints/api/container.py` (branch `feat/backend-db-docker`)
- `openspec/changes/walking-skeleton-and-deploy/design.md` (sections 1 and 12)
