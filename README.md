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

## Local development (hybrid)

Only Postgres runs in Docker; backend and frontend run natively with hot reload. Prerequisites: Docker Desktop, uv, Node 22+.

```powershell
scripts/dev.ps1           # start everything (idempotent); creates .env from .env.example if neither .env nor DATABASE_URL exists
scripts/dev.ps1 -Smoke    # start, then run the smoke check
scripts/smoke.ps1         # smoke check only; accepts -BackendUrl, -FrontendUrl, -Origin to target a deployed stack
scripts/dev.ps1 -Down     # stop backend, frontend and the db container (keeps data)
scripts/dev.ps1 -Reset    # stop and delete the db volume
```

Backend: http://127.0.0.1:8000, frontend: http://localhost:5173 (the origin allowed by `.env.example`; Vite binds `::1` on Windows, which `localhost` resolves to). Logs and PIDs are in `.dev/` (gitignored). The script refuses to run migrations against a `DATABASE_URL` whose host is not `127.0.0.1`/`localhost` unless you pass `-AllowRemoteDb`. The compose project is pinned to `eventssound-dev`, so the volume is `eventssound-dev_pgdata` (data from an older `eventssound_pgdata` volume is not migrated).

From Git Bash (Windows blocks unsigned scripts by default, hence the bypass):

```bash
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/dev.ps1
```

Smoke against a deployed stack (free-tier hosts can need 60-90 s to wake up):

```powershell
scripts/smoke.ps1 -BackendUrl https://<api> -FrontendUrl https://<app> -Origin https://<app> -TimeoutSec 30 -Retries 12 -RetryDelaySec 10
```

Verified on Windows PowerShell 5.1; PowerShell 7 and Vite HMR in a browser are unverified. Production-like check with everything in containers: `docker compose --profile app up --build`.

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

## Deploy

Backend (Docker) and frontend (static site) on Render via `render.yaml`; Postgres on Neon. Live URLs (placeholders until verified): frontend `https://eventssound-web.onrender.com`, backend `https://eventssound-api.onrender.com`. Required variable: `DATABASE_URL` (set in the Render dashboard only). Free instances sleep after 15 minutes idle and need about a minute to wake up. Deploy order, rollback and the manual setup steps are in [documentacion/deploy.md](documentacion/deploy.md).

## CI

GitHub Actions (`.github/workflows/ci.yml`) runs a `backend` job (ruff, migrations, pytest with coverage, Docker build) and a `frontend` job (lint, tests, build). Protect `main` by requiring both checks and pull requests.
