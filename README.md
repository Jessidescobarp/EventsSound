# EventsSound
Web que permite hacer reservas y cotizar eventos

## Stack

FastAPI + SQLAlchemy 2 + Alembic (Python 3.12, uv) on Postgres with pgvector; Vite + React + TypeScript (Node 22). Hexagonal backend, see `documentacion/architecture.md`.

## Local setup

Prerequisites: Docker Desktop, uv, Node 22. Run `git config core.autocrlf false` once (the repo enforces LF).

```bash
cp .env.example .env              # PowerShell: Copy-Item .env.example .env
docker compose up -d --wait db    # Postgres + pgvector on 127.0.0.1:5432

cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn eventssound.entrypoints.api.app:create_app --factory --reload

cd ../frontend                    # in another terminal
npm ci && npm run dev
```

There is a single `.env`, at the repo root. Compose, the backend (any working directory; real environment variables override the file) and the frontend (`envDir: ".."`, only `VITE_*` keys reach the browser bundle) all read it, so no other copies are needed. `frontend/.env.example` is no longer used; do not create `frontend/.env`.

The whole stack in containers is opt-in: `docker compose --profile app up --build`.

## Tests

```bash
# backend (DB tests run only when DATABASE_URL_TEST is set; if set and unreachable they FAIL)
cd backend
DATABASE_URL_TEST=postgresql+psycopg://eventssound:eventssound@127.0.0.1:5432/eventssound uv run pytest --cov=eventssound
uv run ruff check . && uv run ruff format --check .

# frontend
cd frontend && npm run lint && npm run test -- --run && npm run build
```

PowerShell: set the variable first with `$env:DATABASE_URL_TEST = "..."`.

## Windows notes

- Use `127.0.0.1`, not `localhost`, in database URLs: Docker Desktop publishes the port on IPv4 only and `localhost` can resolve to `::1` and hang.
- Port 5432 taken by a local Postgres? Set `POSTGRES_PORT` (for example `5433`) in `.env` and update the port in `DATABASE_URL` and `DATABASE_URL_TEST`.
- Behind corporate TLS interception, run npm with `NODE_OPTIONS=--use-system-ca`.

## CI

GitHub Actions (`.github/workflows/ci.yml`) runs a `backend` job (ruff, migrations, pytest with coverage, Docker build) and a `frontend` job (lint, tests, build). Protect `main` by requiring both checks and pull requests.
