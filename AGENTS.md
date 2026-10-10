# AGENTS.md

Guidance for AI coding agents and contributors working in this repository.

## Purpose

EventsSound is the final project (TFM) of the Master in AI-assisted Development (Máster en Desarrollo con IA). It is a web app with an AI quote agent for a sound, lights and DJ events company. The AI agent is the core of the product. All data is synthetic; never add real customer or personal data.

## Architecture

Backend uses hexagonal architecture under `backend/src/eventssound/`:

- `domain/`: pure business rules. No framework imports.
- `application/`: use cases and ports (Protocols).
- `adapters/`: implementations of ports (SQLAlchemy, later LLM providers).
- `entrypoints/`: FastAPI app factory, routes, composition root (`container.py`).

Dependency rule: domain <- application <- adapters <- entrypoints. It is enforced by `backend/tests/unit/test_architecture.py`. Details: `documentacion/architecture.md`.

## Repo layout

- `backend/`: FastAPI service (Python, uv, pytest, ruff, Alembic).
- `frontend/`: Vite + React + TypeScript shell (added in PR 2).
- `openspec/`: SDD artifacts (`config.yaml`, `specs/`, `changes/<name>/`).
- `documentacion/`: project documentation (English, ASCII folder name).

## Commands

Run from `backend/`:

- `uv sync`: install dependencies.
- `uv run pytest`: tests (DB tests skip when `DATABASE_URL_TEST` is unset and fail when it is set but the database is unreachable).
- `uv run ruff check .` and `uv run ruff format --check .`: lint and format.
- `uv run alembic upgrade head`: apply migrations (needs `DATABASE_URL`).

Run from the repo root:

- `scripts/dev.ps1` (`-Down`, `-Reset`, `-Smoke`): hybrid local stack (db in Docker, backend and frontend native with hot reload; logs in `.dev/`). `scripts/smoke.ps1 [-BackendUrl] [-FrontendUrl] [-Origin] [-Retries] [-RetryDelaySec]`: smoke check, also usable against deployed URLs. From Git Bash prefix with `powershell -NoProfile -ExecutionPolicy Bypass -File`.
- `docker compose up -d --wait db`: local Postgres (pgvector). Set `POSTGRES_PORT` if 5432 is taken. `docker compose down -v` wipes it. The compose project is pinned to `eventssound-dev` (volume `eventssound-dev_pgdata`).
- `docker compose --profile app up --build`: also run the backend container.
- `docker build backend`: build the production image.

Run from `frontend/`: `npm ci`, `npm run lint`, `npm run test -- --run`, `npm run build`.

Deploy: `render.yaml` Blueprint (Render + Neon), guide in `documentacion/deploy.md`. Never deploy, create services or touch Render/Neon from an agent without the developer asking.

CI (`.github/workflows/ci.yml`) runs all of the above on every PR and push to `main`.

## Conventions

- Conventional commits, one per work unit. No `Co-Authored-By` and no AI attribution.
- Code, identifiers, comments and docs in English. User-facing UI copy in Spanish.
- Use forward slashes in paths when running bash commands (Git Bash on Windows).
- Tests live in the same commit as the behavior they verify.
- Stacked PRs: retarget the dependent PR's base to `main` BEFORE merging the previous one; merging a stacked PR into its parent branch does not reach `main` (happened with #2 -> `feat/backend-core`, fixed by #6).

## SDD workflow

- Specs-driven development with the `openspec/` store. Current change: `openspec/changes/walking-skeleton-and-deploy/` (`proposal.md`, `specs/`, `design.md`, `tasks.md`).
- Delivery uses chained PRs, each under 400 changed lines (lockfiles excluded). Chain and merge order are in `tasks.md`.
- Strict TDD is enabled (`openspec/config.yaml`). Test command from the repo root: `uv run --project backend pytest backend/tests`. Write the failing test first.

## Security rules

- Never read, print or commit `.env.local`, `.neon`, `.env*` or any secret or connection string.
- The Neon production branch is not for development or tests. Use a throwaway local Postgres.
- DB tests must skip cleanly when `DATABASE_URL_TEST` is unset, and must fail (never skip) when it is set but the database is unreachable.
- Do not put real hosts, project IDs or credentials in docs or code.

## Roadmap

Phases P0-P5 with MVP target 2026-10-25: `documentacion/roadmap.md`.

## Known gotchas

- Corporate TLS interception breaks Node/npm: use `NODE_OPTIONS=--use-system-ca`. Never disable certificate verification.
- Image tags (`pgvector/pgvector:pg16`, `python:3.12-slim`) are floating by design for the MVP; pin digests if reproducibility starts to matter.
- Local Python may be 3.14 while CI and Docker use 3.12. Do not rely on 3.13+ features.
- On Windows use `127.0.0.1`, not `localhost`, in DB URLs: Docker publishes IPv4 only and `localhost` may resolve to `::1` and hang.
- Render free instances have no `preDeployCommand`; migrations run in `backend/start.sh`. Use the Neon DIRECT (non-pooled) string for `DATABASE_URL`.
- Line endings are LF (`.gitattributes`); keep `core.autocrlf false`.
