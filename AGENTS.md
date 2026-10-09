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
- `docker build backend`: build the production image (the Dockerfile arrives in PR 3).

Frontend commands (`npm ci`, `npm run lint`, `npm run test -- --run`, `npm run build`): added in PR 2.

## Conventions

- Conventional commits, one per work unit. No `Co-Authored-By` and no AI attribution.
- Code, identifiers, comments and docs in English. User-facing UI copy in Spanish.
- Use forward slashes in paths when running bash commands (Git Bash on Windows).
- Tests live in the same commit as the behavior they verify.

## SDD workflow

- Specs-driven development with the `openspec/` store. Current change: `openspec/changes/walking-skeleton-and-deploy/` (`proposal.md`, `specs/`, `design.md`, `tasks.md`).
- Delivery uses chained PRs, each under 400 changed lines (lockfiles excluded). Chain and merge order are in `tasks.md`.
- Strict TDD is enabled in PR 4 (`openspec/config.yaml`). Until then, write the test first where a runner exists.

## Security rules

- Never read, print or commit `.env.local`, `.neon`, `.env*` or any secret or connection string.
- The Neon production branch is not for development or tests. Use a throwaway local Postgres.
- DB tests must skip cleanly when `DATABASE_URL_TEST` is unset, and must fail (never skip) when it is set but the database is unreachable.
- Do not put real hosts, project IDs or credentials in docs or code.

## Roadmap

Phases P0-P5 with MVP target 2026-10-25: `documentacion/roadmap.md`.

## Known gotchas

- Corporate TLS interception breaks Node/npm: use `NODE_OPTIONS=--use-system-ca`. Never disable certificate verification.
- Local Python may be 3.14 while CI and Docker use 3.12. Do not rely on 3.13+ features.
- Line endings are LF (`.gitattributes`); keep `core.autocrlf false`.
