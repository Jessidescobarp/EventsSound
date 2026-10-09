# Design: walking-skeleton-and-deploy (P0)

Inputs: `proposal.md` (same folder), `openspec/changes/tfm-phased-mvp/exploration.md`, `openspec/config.yaml`.
Scope: architecture and tooling for the empty-but-real system. No application code is written in this phase of SDD.

## 1. Technical Approach

One monorepo, two independently deployable apps (FastAPI backend as a Render Docker web service, Vite static frontend as a Render Static Site), one managed Postgres on Neon, Postgres in Docker Compose for local dev and CI parity. The backend follows a minimal hexagonal layout sized for P0: only the folders and the single wiring point that P1/P2 will extend. Migrations run at container start (free tier has no pre-deploy hook). CI is the source of truth for Windows dev friction.

Guiding rule: every directory created in P0 must be used by P0 code or be an explicit, documented extension point. No speculative abstractions (no repository base classes, no LlmProvider, no pgvector code).

## 2. Repo Layout

```
EventsSound/
  .gitattributes            # * text=auto eol=lf (+ binary overrides)
  .gitignore
  .editorconfig
  .env.example              # every variable documented, no secrets
  docker-compose.yml        # db (postgres) [+ optional backend profile]
  render.yaml               # Render Blueprint (both services)
  README.md
  .github/workflows/ci.yml
  backend/
    pyproject.toml          # deps, ruff, pytest config
    uv.lock
    Dockerfile
    .dockerignore
    alembic.ini
    migrations/             # env.py, script.py.mako, versions/0001_baseline.py
    src/eventssound/
      domain/               # pure, no framework imports (empty package in P0, __init__ only)
      application/          # use cases + ports (health check port only)
      adapters/
        db/                 # engine, session factory, DbHealthChecker
      entrypoints/
        api/                # FastAPI factory, routers, deps (composition root)
      config.py             # Pydantic Settings
    tests/
      unit/
      integration/
  frontend/
    package.json, package-lock.json
    vite.config.ts, tsconfig*.json, eslint config, index.html
    src/ (main.tsx, App.tsx, api/health.ts, env.ts, App.test.tsx)
    public/_redirects       # not needed on Render (handled in render.yaml routes)
```

Decision: `src/` layout for the backend package (`eventssound`) so tests import the installed package, not the CWD. Rejected: flat `app/` (accidental imports from CWD, harder to package for Docker).

### Hexagonal naming
Folders follow the proposal and `config.yaml` rule: `domain / application / adapters / entrypoints`. Mapping to the vocabulary in the brief: `infrastructure` = `adapters` (driven side: DB, later LLM), `api` = `entrypoints/api` (driving side). Rationale: `adapters` vs `entrypoints` distinguishes driven from driving adapters, which matters in P2 (LlmProvider adapters are driven, `/quote/chat` is driving). Layers-first now; bounded contexts (`catalog/`, `quoting/`) introduced in P1 only if real domain code demands it.

Dependency rule (enforced by review in P0, by an import-linter test or simple pytest AST check optionally in P1): `domain` imports nothing from the project; `application` imports `domain`; `adapters` and `entrypoints` import `application`/`domain`; only `entrypoints/api/container.py` (composition root) imports concrete adapters.

### What P0 puts in each layer
| Layer | P0 content | Why it exists now |
| ----- | ---------- | ----------------- |
| `domain/` | empty package | Boundary marker; P1 fills it |
| `application/` | `ports.py` with `DatabaseHealthPort` (Protocol), `health.py` use case `check_database()` | Proves port + use case + adapter + DI chain on the smallest real feature |
| `adapters/db/` | `session.py` (engine, `sessionmaker`), `health.py` (`SELECT 1` implementation of the port) | Proves SQLAlchemy 2.0 wiring and Neon connectivity |
| `entrypoints/api/` | `app.py` (`create_app(settings)`), `routes/health.py`, `container.py` (DI) | App-factory pattern so tests override dependencies |

## 3. Tooling and Dependency Choices

| Concern | Choice | Rationale / rejected |
| ------- | ------ | -------------------- |
| Python | 3.12 | Stable, wheels available for all planned deps (LangGraph, psycopg, pydantic-core). Rejected 3.13/3.14: higher wheel-gap risk for P2 libs with no benefit |
| Package manager | `uv` (pyproject + `uv.lock`) | Fast, reproducible lockfile, one tool for venv + run; works on Windows. Rejected pip+requirements: no lock semantics. Rejected Poetry: slower, heavier |
| Web | FastAPI + uvicorn | Per stack |
| Settings | `pydantic-settings` (Pydantic v2) | Typed env parsing, fails fast on missing vars |
| ORM / migrations | SQLAlchemy 2.0 (typed `DeclarativeBase`) + Alembic | Per stack |
| DB driver | `psycopg[binary]` v3, URL scheme `postgresql+psycopg://` | Modern driver, no compile step, good Neon/SSL support. Rejected asyncpg + async SQLAlchemy: adds async migration complexity; sync SQLAlchemy in FastAPI threadpool is adequate for load and for the agent in P2 |
| Lint/format | `ruff` (check + format), rules `E,F,I,UP,B,SIM` | One tool |
| Types | Deferred (mypy/pyright not in P0) | Time budget; revisit P1 |
| Tests | `pytest`, `httpx` (TestClient), `pytest-cov` | Per stack; coverage reported but no threshold yet |
| Frontend | Node 22 LTS, Vite, React 18/19, TypeScript, npm, ESLint, Vitest + Testing Library | npm chosen over pnpm to cut tool install friction in CI/Render |

### shadcn/ui
Deferred to P4 as scoped. P0 ships plain CSS (one small stylesheet), but Tailwind is NOT installed now: shadcn requires Tailwind, and adding it in P4 is a contained change. Rejected installing Tailwind now: speculative, adds config files and build surface to a 1.5-day phase.

### Settings contract (`config.py`)
| Variable | Required | Example / notes |
| -------- | -------- | --------------- |
| `APP_ENV` | no (default `local`) | `local` / `ci` / `production`; `production` forces `debug=False`, disables `/docs` |
| `DATABASE_URL` | yes | `postgresql+psycopg://user:pass@host:5432/db` (see section 6) |
| `CORS_ALLOWED_ORIGINS` | yes | comma-separated list; `http://localhost:5173` locally |
| `LOG_LEVEL` | no | default `INFO` |

Frontend: `VITE_API_BASE_URL` (build-time, public by definition; never a secret).

## 4. Database, Compose, Alembic

### Docker Compose
- `db`: `postgres:16-alpine` for now. Open point: P2 needs pgvector; local image should match Neon's pgvector support. Decision: use `pgvector/pgvector:pg16` from day one so local parity with Neon (which supports the `vector` extension) holds, but do NOT run `CREATE EXTENSION vector` in P0 (see section 11). Named volume `pgdata`, healthcheck via `pg_isready`, port `5432:5432`, creds from `.env` with safe local defaults in `.env.example`.
- `backend` service under `profiles: ["app"]` (opt-in) building `backend/Dockerfile`. Default workflow is `docker compose up -d db` + native `uv run uvicorn`, which avoids Windows bind-mount/file-watch slowness.
- Rejected: Compose including the frontend (Vite dev server runs natively; Compose adds no value).

### Alembic baseline
- `migrations/env.py` reads `DATABASE_URL` from `Settings` (not from `alembic.ini`), targets `Base.metadata` (empty in P0).
- One revision `0001_baseline` with empty `upgrade()`/`downgrade()`. It creates the `alembic_version` table, proving: Neon connectivity, SSL, permissions, and the deploy migration step.
- Naming convention for constraints set on `MetaData` now (`ix`, `uq`, `ck`, `fk`, `pk`) so P1 autogenerated migrations are deterministic.

### Neon connection and SSL
- Neon requires TLS. Connection string from the Neon dashboard is used with scheme rewritten to `postgresql+psycopg://` and `?sslmode=require` kept. `channel_binding=require` (present in some Neon strings) is supported by libpq/psycopg3; if it fails on Render, drop that param.
- Use the direct (non-pooled) endpoint for P0 and migrations. Rationale: Alembic and DDL behave badly through PgBouncer transaction pooling, and free-tier traffic is tiny. If the pooled `-pooler` host is adopted later, use it for the app only and keep a separate `MIGRATION_DATABASE_URL` (not introduced now).
- Engine: `pool_pre_ping=True`, `pool_recycle=300`, small pool (`pool_size=3`, `max_overflow=2`). Reason: Neon auto-suspends idle compute (~5 min on free tier, unverified) and drops connections; pre-ping avoids first-request errors after suspend.
- Local and CI use `sslmode=disable` implicitly (no param).

## 5. API Contracts

### `GET /health` (liveness)
- No dependencies, no DB access. Always 200 while the process is up.
- Response `200 application/json`: `{"status": "ok", "service": "eventssound-backend", "version": "<APP_VERSION or 'dev'>"}`.
- Used by Render health check and by the frontend shell.

### `GET /health/db` (readiness)
- Runs `SELECT 1` through `DatabaseHealthPort`.
- `200`: `{"status": "ok", "database": "ok"}`. `503`: `{"status": "degraded", "database": "unavailable"}` with no exception detail leaked (no connection strings, no stack).
- Kept separate from `/health` on purpose: Render's health check must not wake Neon from suspend every probe (burns free compute hours), and a DB blip must not restart the web service.
- Frontend shell calls both, shows two indicators ("Backend" and "Base de datos"), so the live demo proves end-to-end DB connectivity.

No auth, no pagination, no versioning prefix in P0. Routes mount at root; an `/api` prefix is not introduced (Render hosts are separate, no proxy needed). Revisit P4 if a same-origin proxy is adopted.

## 6. CORS and Environments

Two Render hosts: `https://<name>-web.onrender.com` (static) calls `https://<name>-api.onrender.com`. Different origins, so CORS is required.

- `CORSMiddleware` with `allow_origins=settings.cors_allowed_origins` (exact list, no `*`), `allow_methods=["GET","POST","OPTIONS"]` (extended in P2/P4), `allow_headers=["Authorization","Content-Type"]`, `allow_credentials=False` in P0 (JWT will use Authorization header, not cookies, so no credentialed CORS needed).
- Production value is set in Render env vars to the actual static site URL, including scheme, no trailing slash. A trailing-slash mismatch is the most common failure; covered by a unit test on settings parsing (strip trailing `/`).
- Because the static URL is known only after first deploy, order of operations: deploy backend with placeholder origin, deploy static site, update `CORS_ALLOWED_ORIGINS`, redeploy backend. Documented in README. Using predictable service names in `render.yaml` makes the URLs deterministic and avoids the loop where possible (unverified: name collisions on onrender.com would force a suffix).
- Local: Vite dev server `http://localhost:5173` -> backend `http://localhost:8000`.

## 7. Env Var and Secrets Strategy

- `.env` is git-ignored; `.env.example` is committed and lists every variable with a harmless placeholder and a one-line comment. Gitignore also covers `*.pem`, `.env.*` except `.env.example`.
- Production secrets (`DATABASE_URL`) live only in Render env vars, declared in `render.yaml` with `sync: false` so the value is never in the repo.
- CI uses fixed non-secret values (service container creds). No GitHub secrets needed in P0.
- Frontend `VITE_*` values are baked at build time and public; `.env.example` marks them as such. Future P2 secrets (OpenRouter key, LangSmith key) follow the same path: backend env only.
- `Settings` raises at startup if `DATABASE_URL` is missing, so a misconfigured deploy fails visibly.

## 8. Dockerfile (backend)

- Multi-stage: builder `python:3.12-slim` installs `uv`, runs `uv sync --frozen --no-dev` into `/app/.venv`; runtime `python:3.12-slim` copies `.venv` and `src/`, `migrations/`, `alembic.ini`. Non-root user. No compilers needed thanks to `psycopg[binary]`.
- `PORT`: Render injects `PORT`; start command binds `0.0.0.0:${PORT:-8000}`.
- Entry: a small `start.sh` (LF endings enforced by `.gitattributes`) runs `alembic upgrade head && exec uvicorn eventssound.entrypoints.api.app:create_app --factory --host 0.0.0.0 --port ${PORT:-8000}`.
- `.dockerignore` excludes `.venv`, `tests`, `.env*`, caches.

### How migrations run on Render (key decision)
Render's `preDeployCommand` is documented as unavailable on free instances (verify at apply time). Decision: run `alembic upgrade head` in the container start script, before uvicorn. Tradeoffs:
- Pro: works on free tier, zero extra infra, migration failure keeps the new deploy from going live (health check fails, old instance stays).
- Con: every cold start re-runs a fast no-op check (adds ~1-2 s, plus Neon wake-up time); concurrent instances could race (not an issue: one free instance).
- Revisit if moving to a paid plan: switch to `preDeployCommand` and drop it from `start.sh`.
Rejected: running migrations from CI against Neon (requires storing the production DB URL as a GitHub secret and couples CI to prod).

## 9. CI (GitHub Actions)

`.github/workflows/ci.yml`, triggers: `pull_request` and `push` to `main`. Concurrency group cancels superseded runs. Two parallel jobs on `ubuntu-latest`:

**backend**
1. checkout; `astral-sh/setup-uv` with cache; Python 3.12 via uv.
2. Postgres service container (`pgvector/pgvector:pg16`, health-checked) with `DATABASE_URL` env.
3. `uv sync --frozen`
4. `uv run ruff check .` and `uv run ruff format --check .`
5. `uv run alembic upgrade head`
6. `uv run pytest --cov=eventssound`
7. `docker build backend` (build only, no push) to catch Dockerfile breakage.

**frontend**
1. checkout; `actions/setup-node` Node 22 with npm cache.
2. `npm ci`, `npm run lint`, `npm run test -- --run`, `npm run build`.

Both jobs have `defaults.run.working-directory`. Branch protection (require both jobs) recommended in README but is a repo setting, not code. Deploy is NOT triggered from CI: Render auto-deploys from `main` via its GitHub integration (simplest; no deploy hooks or secrets). Tradeoff: Render deploys even if CI fails on a push to `main`; mitigated by merging only through PRs with required checks.

## 10. Render Blueprint (`render.yaml`) outline

```yaml
services:
  - type: web
    name: eventssound-api
    runtime: docker
    plan: free
    rootDir: backend
    dockerfilePath: ./Dockerfile
    healthCheckPath: /health
    autoDeploy: true
    envVars:
      - key: APP_ENV
        value: production
      - key: DATABASE_URL
        sync: false            # set in dashboard (Neon string)
      - key: CORS_ALLOWED_ORIGINS
        sync: false            # set to the static site URL

  - type: web
    name: eventssound-web
    runtime: static
    rootDir: frontend
    buildCommand: npm ci && npm run build
    staticPublishPath: dist
    autoDeploy: true
    envVars:
      - key: VITE_API_BASE_URL
        sync: false            # https://eventssound-api.onrender.com
    routes:
      - type: rewrite
        source: /*
        destination: /index.html
```

Notes: no `databases:` block (Neon is external). Blueprint schema details (field names such as `runtime: static` vs `env: static`, static service `plan`) must be verified against current Render docs during apply; the outline is intent, not final syntax. Workspace is `EventsSoundDr`.

## 11. Free-Tier Caveats (all limits unverified; confirm at apply time)

| Item | Caveat | Handling |
| ---- | ------ | -------- |
| Render web free | Spins down after ~15 min idle; ~1 min cold start; instance hours are monthly-limited | Frontend shows a "waking up" state when `/health` takes more than a few seconds (Spanish copy: "El servidor se esta iniciando, puede tardar hasta un minuto."); warm before demos/video. Optional external pinger deferred to P5 decision |
| Render Docker on free | Slower builds than native runtime | Accept; layer caching via multi-stage |
| Render static | Free, global CDN, no cold start | none |
| Neon free | Compute auto-suspends; first query adds latency; storage/compute caps | `pool_pre_ping`; `/health` independent of DB |
| No card | Render and Neon free plans advertised as card-free | If either demands a card, fallback in proposal: VM + Compose |
| Cost control | No paid services in P0 | none |

## 12. Leaving Room for P2 (without building it)

- **pgvector:** local and CI Postgres images already ship the extension. P2 adds a migration `CREATE EXTENSION IF NOT EXISTS vector` and `Vector` columns (via `pgvector` Python package). Neon supports it; P0 does not touch it. Zero P0 code depends on it, so no rework.
- **LlmProvider port:** lives in `application/ports.py` in P2 beside `DatabaseHealthPort`, with adapters under `adapters/llm/` (OpenRouter, Replay). The composition root `container.py` is already where adapters bind to ports, and `create_app(settings)` already accepts overridable dependencies, which is the seam tests use for the Replay provider.
- **Agent endpoint:** new router under `entrypoints/api/routes/`, registered in `app.py`.
- **Config:** `Settings` extends with provider/key/budget variables; the `.env.example` + Render `sync: false` pattern applies unchanged.
- **Streaming/long requests:** sync workers are fine for P0; Render free request timeouts and SSE behavior to be checked in P2.

## 13. Architecture Decisions (ADR summary)

| # | Decision | Rationale | Rejected |
| - | -------- | --------- | -------- |
| D1 | Monorepo, `backend/` + `frontend/` | One PR flow, one CI, solo project | Two repos |
| D2 | Layer folders `domain/application/adapters/entrypoints` with `src/` layout | Matches TFM requirement; additive for P1/P2 | Feature-first now; flat `app/` |
| D3 | Python 3.12 + uv + ruff + pytest | Reproducible, fast, minimal tools | pip, Poetry, 3.13+ |
| D4 | Sync SQLAlchemy 2.0 + psycopg3 | Simpler migrations and tests | asyncpg/async engine |
| D5 | Migrations in container start script | Free tier lacks pre-deploy hook | CI-driven prod migrations |
| D6 | `/health` (no DB) + `/health/db` (DB) | Avoid waking Neon, avoid restart loops | Single health endpoint touching DB |
| D7 | Exact-origin CORS, no credentials | Meets security baseline, JWT via header | `*`, cookie auth |
| D8 | Render autodeploy from `main`, no CI deploy step | No secrets in GitHub | Deploy hooks from Actions |
| D9 | pgvector Postgres image locally from day one | Parity with Neon, no P2 surprise | Plain postgres then switch |
| D10 | Direct Neon endpoint, `pool_pre_ping` | DDL safe, handles suspend | Pooled endpoint now |
| D11 | No Tailwind/shadcn in P0 | Scope discipline; added P4 | Install now |
| D12 | UI copy Spanish, all code/docs English | Proposal decision 4 | n/a |

## 14. Testing Strategy (feeds Strict TDD flip)

| Layer | What | Tool |
| ----- | ---- | ---- |
| Unit | Settings parsing (CORS list, missing `DATABASE_URL`), `check_database()` with a fake port | pytest |
| Integration | `/health` 200 and shape; `/health/db` 200 with real Postgres (CI service/Compose) and 503 with a failing fake injected via the app factory | pytest + TestClient |
| Migration | `alembic upgrade head` then `alembic downgrade base` against the CI database | CI step |
| Frontend | `App` renders status from mocked `fetch` (ok and error and loading states) | Vitest + Testing Library |

TDD order for apply: write failing test, then code, for backend; frontend tests accompany the component. After pytest passes, flip `openspec/config.yaml` (`strict_tdd: true`, `testing.runner.command: "uv run pytest"` run from `backend`, `apply.tdd: true`, `apply.test_command`, `verify.test_command`, `verify.build_command`, `quality.linter`). Use a command that works from repo root, e.g. `uv run --project backend pytest backend/tests`.

## 15. Windows Dev Friction

- `.gitattributes` (`* text=auto eol=lf`, explicit `*.sh text eol=lf`, `*.bat text eol=crlf` if ever added, binaries marked) lands FIRST, before any other file, so no CRLF ever enters history. Shell scripts with CRLF break Docker `start.sh` (`bad interpreter`), so this is not cosmetic.
- `.editorconfig` with `end_of_line = lf`.
- Developer should set `git config core.autocrlf false` or rely on `.gitattributes`; documented in README.
- Default workflow avoids bind mounts: DB in Compose, backend and frontend native. Docker Desktop is only needed for `db`.
- All commands in README shown for PowerShell and POSIX where they differ; paths use forward slashes in config files.
- CI on Linux is the authority; "works on my machine" does not gate merges.

## 16. PR Slicing Plan

Delivery strategy resolution is pending (`ask-on-risk`); this plan assumes chained PRs (recommended). Stacked to `main`, work-unit commits, conventional commits, no AI attribution.

| PR | Branch intent | Files (approx. lines) | Total |
| -- | ------------- | --------------------- | ----- |
| 1. Backend skeleton | `feat/backend-skeleton` | `.gitattributes` (10), `.gitignore` (40), `.editorconfig` (12), `backend/pyproject.toml` (60), `backend/src/eventssound/{config.py (35), application/ports.py (10), application/health.py (15), adapters/db/session.py (30), adapters/db/health.py (15), entrypoints/api/{app.py (40), container.py (25), routes/health.py (35)}}`, `__init__.py` files (~10), `backend/alembic.ini` (15), `backend/migrations/{env.py (50), script.py.mako (25), versions/0001_baseline.py (15)}`, `backend/tests/{conftest.py (30), unit/test_settings.py (30), unit/test_health_usecase.py (20), integration/test_health.py (40)}`, `backend/Dockerfile` (30), `backend/start.sh` (8), `backend/.dockerignore` (10); `uv.lock` excluded | 300-380 |
| 2. Frontend skeleton | `feat/frontend-skeleton` | `frontend/package.json` (35), `vite.config.ts` (15), `tsconfig*.json` (45), `eslint.config.js` (25), `index.html` (12), `src/{main.tsx (10), App.tsx (60), api/health.ts (30), env.ts (10), App.css (30), App.test.tsx (50), vite-env.d.ts (2)}`, `frontend/.env.example`-style note in root `.env.example` (PR 3); lockfile excluded | 180-250 |
| 3. CI + Compose | `feat/ci-compose` | `docker-compose.yml` (35), `.env.example` (25), `.github/workflows/ci.yml` (90), `README.md` run steps and Windows notes (60) | 180-220 |
| 4. Deploy + TDD flip | `feat/deploy-config` | `render.yaml` (40), `README.md` live URL, env table, cold-start and CORS ordering (40), `openspec/config.yaml` flip (~10) | 90-130 |

Order and rationale:
1. PR 1 first: contains `.gitattributes`/`.gitignore`/`.editorconfig` as its first commit so line endings are fixed before any code. Backend is the highest-risk unit (Alembic + settings + SQLAlchemy) and unblocks the TDD flip.
2. PR 2 is independent; can be written while PR 1 is in review (separate branch off `main`, no stacking needed).
3. PR 3 after both, because CI needs both apps to exist and Compose/`.env.example` document both.
4. PR 4 last: deploy needs green CI and a Dockerfile on `main`. Manual deploy steps (create Neon project, create Render Blueprint, set env vars, update CORS, redeploy) are executed after PR 4 merges and recorded in README; they produce the live URL for the success criteria. Fold PR 4 into PR 3 only if combined size stays under 400 lines (currently ~270-350, feasible).

The config flip commit is deliberately in PR 4 (after CI proves pytest works on `main`), not PR 1.

## 17. Risks and Assumptions

| Risk / assumption | Note |
| ----------------- | ---- |
| Render free tier has no pre-deploy command | Assumed from docs memory; verify. Start-script migration is the design either way |
| Blueprint field names for static services | Verify against current schema before PR 4 |
| Neon `channel_binding` / pooled vs direct behaviour with psycopg3 | Validate with the real string during deploy; fallback is dropping the param |
| Neon + Render free-tier limits and card requirements | Unverified; VM + Compose fallback remains |
| CORS ordering loop (URL known only after deploy) | Deterministic service names; documented sequence |
| Docker Desktop on Windows for the `db` service | If unavailable, use a Neon dev branch as local DB (works with the same `DATABASE_URL`) |
| Hexagonal layout heavy for tiny code | Only health slice implemented; domain empty |
| Strict TDD flip depends on a command runnable from repo root | Define in PR 4; confirm sdd-apply can execute it |
| Cold start (~1 min) during grading | Warm-up before demo; decision on pinger/paid tier at P5 |

## 18. Rollback

Per proposal: each PR is revertible via `git revert`; delete Render services and Neon project to unwind deploy; `alembic downgrade base` is a no-op for the empty baseline; revert the single config commit to disable Strict TDD.
