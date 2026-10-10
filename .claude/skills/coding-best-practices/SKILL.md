---
name: coding-best-practices
description: "Trigger: coding standards, typing, error handling, logging, config, secrets, tests, TDD, commits, PR size, language rules. Apply project coding conventions."
license: Apache-2.0
metadata:
  author: eventssound
  version: "1.0"
---

## Activation Contract

Use for any code, test, config, commit, or PR work in this repo (backend Python, frontend React/TypeScript). Pair with `architecture-hexagonal` for placement and `database-conventions` for persistence.

## Hard Rules

Language
- Code, identifiers, comments, docs, commit messages: English.
- User-facing UI copy: Spanish (for example "Servicio operativo" in `frontend/src/App.tsx`). Domain terms already in Spanish by design (`calcular_precio`, `buscar_equipamiento`) stay as is.
- Paths in shell commands use forward slashes (Git Bash on Windows).

Typing and style
- Python 3.12, type hints on every public function; `X | None`, not `Optional`. Do not use 3.13+ features.
- ruff is the only linter/formatter: line length 100, rules `E,F,I,UP,B,SIM`. Run `uv run ruff check .` and `uv run ruff format --check .`.
- Frontend: TypeScript strict, ESLint clean, no `any` without a comment.
- Prefer small functions, early returns, and plain data (dataclasses, Pydantic models) over clever abstractions.

Errors
- Raise specific exceptions; never `except:` bare. Catch broad `Exception` only at a boundary and convert it, as `check_database` does (returns `False`).
- HTTP errors expose a stable shape and no internals: no stack traces, hosts, SQL, or prompts.
- Validate input at the edge (Pydantic models, `field_validator`) and fail fast at startup on bad config.

Config and secrets
- All settings live in `Settings` (`config.py`, pydantic-settings v2). No `os.environ` reads elsewhere.
- Secrets use `SecretStr`; unwrap only at the point of use. Production rejects unsafe values (wildcard CORS raises in `production`).
- `.env*` are git-ignored; only `.env.example` (placeholders) is committed. Never read, print, or commit a real secret.
- `VITE_*` variables are public by definition; never put a secret there.

Logging
- Use the `logging` module with `LOG_LEVEL`; no `print` in application code.
- Never log secrets, connection strings, API keys, full prompts with user data, or exception text that may embed them (the health-use-case test uses an error mentioning a host precisely to prove it is not echoed).
- Log identifiers and outcomes, not payloads.

AI agent code (planned)
- The LLM never computes prices; `calcular_precio` is deterministic and is the eval oracle.
- Treat user chat input and retrieved text as untrusted (OWASP GenAI: prompt injection, rate limit, cost cap). Validate tool arguments with schemas.
- Tests use the Replay `LlmProvider`; no network or paid calls in the default test run.

## Testing

- Test first: failing test, minimal code, refactor. Tests land in the same commit as the behavior.
- Layout: `backend/tests/unit` (no I/O, fakes for ports) and `backend/tests/integration` (app factory, real Postgres).
- Fakes over mocks: a small class implementing the Protocol (see `HealthyDatabase` / `BrokenDatabase`).
- Database tests: skip only when `DATABASE_URL_TEST` is unset; fail (never skip) when it is set but unreachable (`tests/conftest.py`). A silent skip would hide a broken CI service.
- Never run tests against the production database.
- Oracle-based evals (planned): compare agent quotes with `calcular_precio` on a golden set; assert on structure and numbers, not wording.
- Frontend: Vitest + Testing Library; mock `fetch`, cover loading, ok, and error states.

## Git and delivery

- Conventional commits (`feat:`, `fix:`, `docs:`, `test:`, `chore:`), one per work unit. No `Co-Authored-By`, no AI attribution.
- PRs stay under about 400 changed lines (lockfiles excluded). Larger work becomes chained PRs, each based on the previous one, merged in order (see `openspec/changes/walking-skeleton-and-deploy/tasks.md`).
- Do not mix refactors with behavior changes in one commit.
- Line endings are LF (`.gitattributes`); keep `core.autocrlf false`.

## Decision Gates

| Situation | Action |
| --------- | ------ |
| New env var | Add to `Settings` and `.env.example`, document, test parsing |
| Diff over 400 lines | Split into chained PRs |
| DB test needed | Use `database_url` fixture, never prod |
| Unsure where code goes | Use `architecture-hexagonal` |

## Execution Steps

1. Read the spec and task; write the failing test.
2. Implement the smallest change; keep types and lint clean.
3. Run backend: `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`. Frontend: `npm run lint`, `npm run test -- --run`, `npm run build`.
4. Check the diff for secrets, stray logs, and wording in the right language.
5. Commit with a conventional message, no attribution.

## Output Contract

Report: tests added or changed, commands run with results, and any rule intentionally bent (with reason).

## References

- `backend/pyproject.toml`, `backend/tests/conftest.py` (branch `feat/backend-db-docker`)
- `openspec/config.yaml`, `openspec/changes/walking-skeleton-and-deploy/design.md` (section 14)
