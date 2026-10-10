---
name: solid-principles
description: "Trigger: SOLID, single responsibility, open closed, Liskov, interface segregation, dependency inversion, code review, refactor. Review designs against SOLID."
license: Apache-2.0
metadata:
  author: eventssound
  version: "1.0"
---

## Activation Contract

Use when designing a class or module, reviewing a diff, or deciding whether to split or abstract something. SOLID serves readability and testability here; it is not a reason to add layers.

## Hard Rules

### S: Single Responsibility
- One reason to change per module or class.
- Example: `check_database` only decides readiness; `SqlAlchemyDatabaseHealth` only talks to the DB; the route only maps to HTTP.
- Violation: a route that opens a session, runs SQL, and builds the JSON error body.

### O: Open/Closed
- Add behavior by adding code, not by editing a growing `if/elif`.
- Example (planned): a new LLM backend is a new class in `adapters/llm/` plus one branch in the factory in `container.py`; the agent use case is untouched.
- Violation: `if provider == "ollama": ... elif provider == "openrouter": ...` scattered through use cases.
- Balance: a factory with a small registry is fine; do not build plugin systems.

### L: Liskov Substitution
- Any implementation of a port must be usable wherever the port is expected, honoring its contract (inputs, outputs, errors).
- Example: `ping()` returns normally or raises; the test fakes `HealthyDatabase` and `BrokenDatabase` and the real adapter are interchangeable in `check_database`.
- Example (planned): Replay and OpenRouter providers return the same response type and raise the same error types, so tests with Replay predict production behavior.
- Violation: an adapter that returns `None` on failure when the port promises an exception, or ignores a required argument.

### I: Interface Segregation
- Small, role-specific ports; clients depend only on what they use.
- Example: `DatabaseHealthPort` has one method and is not merged into a general `Database` interface.
- Example (planned): separate `LlmProvider` (generate) and embedding port, since RAG and chat vary independently.
- Violation: a `Repository` Protocol with 15 methods where each use case needs two.

### D: Dependency Inversion
- High-level policy depends on abstractions; details depend on them too.
- Example: `application/health.py` imports `application/ports.py`, never SQLAlchemy; `container.py` is the only module that knows both sides; `test_architecture.py` enforces the direction.
- Violation: a use case doing `from eventssound.adapters.db.session import build_engine`, or reading `Settings` directly to pick a vendor.
- Inject through constructors or function parameters, not globals.

## Decision Gates

| Smell | Principle | Typical fix |
| ----- | --------- | ----------- |
| File changes for unrelated reasons | S | Split by responsibility |
| Adding a case edits many files | O | Introduce a port or strategy, if two cases exist |
| Subclass or fake needs special handling | L | Tighten the port contract, fix the adapter |
| Fake must stub unused methods | I | Split the Protocol |
| Core imports a framework | D | Move behind a port, inject in `container.py` |

## Execution Steps (review checklist)

1. Does each function and class have one stated purpose?
2. Do imports point inward only (architecture test green)?
3. Could a fake replace each dependency in a unit test without patching?
4. Is every new abstraction used by two implementations or one test double?
5. Are ports small and their error behavior documented in the docstring?
6. Is construction in `container.py`, not scattered?
7. Did the change avoid editing existing branches to add a variant?

## Output Contract

Report: principles checked, violations found with file and line, and the minimal fix. Say explicitly when a principle was deliberately not applied to avoid over-engineering.

## References

- `backend/src/eventssound/application/ports.py`, `application/health.py`, `backend/tests/unit/test_health_usecase.py` (branch `feat/backend-db-docker`)
- `backend/tests/unit/test_architecture.py` (branch `feat/backend-core`)
