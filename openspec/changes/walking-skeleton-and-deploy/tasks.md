# Tasks: walking-skeleton-and-deploy (P0)

Inputs: `proposal.md`, `design.md`, `specs/*/spec.md` (same folder), `openspec/config.yaml`.
Delivery strategy: chained/stacked PRs (resolved by the user), no `size:exception`, each PR targets 400 changed lines (lockfiles excluded). Decision (ask-on-risk resolved by the user): PR 1a and PR 1b are accepted at ~449 changed lines each, without `size:exception`, and all Docker files move to PR 3.

Legend:
- **[A]** agent-executable (sdd-apply).
- **[M]** manual action by the developer (accounts, dashboards, repo settings). The agent must stop and ask.
- **TDD**: write the failing test first, see it fail, then implement. The runner does not exist until T1.3, so tasks before it are "test after, same commit".
- Spec refs use `capability / Requirement name`.

## Review Workload Forecast

| Metric | Value |
| ------ | ----- |
| Estimated changed lines (excl. lockfiles) | ~830-1000 total across 5 PRs (1a, 1b, 2, 3, 4) |
| Chained PRs recommended | Yes (resolved: stacked PRs) |
| 400-line budget risk | PR 1a and PR 1b are ~449 lines each (measured, excl. `uv.lock`, openspec, docs); the user accepted this overage (ask-on-risk resolved). Low for PR 2-4 |
| Decision needed before apply | No. Delivery strategy already resolved (chained/stacked). Only pending item: confirm git repo and GitHub remote exist (T0.1) |

Docker move (decided by the user): `backend/Dockerfile`, `backend/start.sh` (with the bounded alembic retry loop), `backend/.dockerignore` (48 lines) and the pinned uv image (`ghcr.io/astral-sh/uv:0.11.6`) are NOT part of PR 1b. They live as clean commits on the local-only branch `wip/docker-for-pr3` (based on the PR 1b tip) and are cherry-picked into PR 3 together with the `docker build backend` CI step. The `feat/backend-db-docker` branch name is kept for traceability, but the branch no longer contains Docker.

### PR chain

| PR | Branch | Base branch | Est. lines | Depends on | Merge order |
| -- | ------ | ----------- | ---------- | ---------- | ----------- |
| 1a Backend core | `feat/backend-core` | `main` | ~449 (measured after review hardening, excl. `uv.lock` and openspec) | none | 1 |
| 1b Backend DB (no Docker) | `feat/backend-db-docker` | `feat/backend-core` (stacked; retarget to `main` once PR 1a merges) | ~449 (measured after moving Docker out, excl. `uv.lock` and openspec; accepted by the user) | PR 1a | 2 |
| 2 Frontend skeleton | `feat/frontend-skeleton` | `main` (independent of PR 1a/1b) | 180-250 | none | 3 |
| 3 CI + Compose + Docker | `feat/ci-compose` | `main` after PR 1a, PR 1b and PR 2 are merged (rebase if branched earlier) | ~230-270 (180-220 plus 48 Docker lines from `wip/docker-for-pr3`) | PR 1b, PR 2 | 4 |
| 4 Deploy config + TDD flip | `feat/deploy-config` | `main` after PR 3 is merged | 90-130 | PR 3 | 5 |

All branch names match `^(feat|fix|chore|...)/[a-z0-9._-]+$`. Stacked-to-main strategy; do not mix with a feature-branch chain. If PR 2 is opened before PR 1 merges, it still targets `main` (no shared files), so no polluted diff. PR 3 and PR 4 must NOT be opened until their dependencies are merged, otherwise the diff is polluted: retarget/rebase instead.

Each PR description must state: start, end, prior dependencies, follow-up, out-of-scope, and a dependency diagram marking the current PR:

```
PR1a core ─> PR1b db ─────────┐
              ├──> PR3 ci+compose ──> PR4 deploy+flip
PR2 frontend ─┘
```

### Work-unit commit boundaries

Conventional commits only. NO `Co-Authored-By`, NO AI attribution. Tests and docs live in the same commit as the behavior they verify. Each commit leaves the repo coherent.

| PR | Commit (in order) | Tasks |
| -- | ----------------- | ----- |
| 1a | `chore: add gitattributes, gitignore and editorconfig` | T1.1 |
| 1a | `build(backend): add python project with pytest and ruff` | T1.2, T1.3 |
| 1a | `feat(backend): add app factory, settings and health endpoint` | T1.4, T1.5 |
| 1b | `feat(backend): add sqlalchemy session and database readiness check` | T1.6 |
| 1b | `feat(backend): add alembic baseline migration` | T1.7 |
| 1a | `test(backend): enforce hexagonal dependency rule` | T1.8 (moved to PR 1a to balance size; it passes on the core code) |
| 1a/1b | `docs(sdd): ...` tasks.md progress updates | n/a |
| 2 | `feat(frontend): scaffold vite react typescript shell with vitest` | T2.1, T2.2 |
| 2 | `feat(frontend): show backend health status` | T2.3, T2.4 |
| 3 | `build(backend): add dockerfile and start script` | T1.9 (cherry-pick from `wip/docker-for-pr3`) |
| 3 | `fix(backend): retry migrations a bounded number of times on start` | T1.9 (cherry-pick) |
| 3 | `build(backend): pin uv image version` | T1.9 (cherry-pick) |
| 3 | `build: add docker compose with postgres and env example` | T3.1 |
| 3 | `ci: add github actions workflow for backend and frontend` | T3.2 |
| 3 | `docs: add local run steps and windows notes` | T3.3 |
| 4 | `build(deploy): add render blueprint` | T4.1 |
| 4 | `ci: add post-deploy smoke check script` | T4.2 |
| 4 | `docs: document live urls, env variables and deploy order` | T4.4 |
| 4 | `chore(openspec): enable strict tdd` | T4.5 |

---

## Phase 0: Preconditions (before PR 1)

- [x] **T0.1 [M/A]** Confirm `C:\Repos\EventsSound` is a git repo with a GitHub remote and `main` pushed. If not: developer runs `git init`/creates the GitHub repo (manual); agent never pushes. Satisfies: prerequisite for ci-pipeline / Triggers.
- [x] **T0.2 [A]** Check tool availability and record results in apply-progress: `uv`, Python 3.12, Node 22, `docker` / Docker Desktop (`docker info`). If Docker Desktop is missing, note fallback (Neon dev branch as local DB, same `DATABASE_URL`). Do not install anything without asking. Satisfies: de-risks database-migrations / Local Postgres service.
- [x] **T0.3 [A]** Create branch `feat/backend-skeleton` from `main`.

---

## PR 1a: Backend core (`feat/backend-core`, base `main`, ~449 lines) and PR 1b: Backend DB (`feat/backend-db-docker`, base `feat/backend-core`, ~449 lines, no Docker)

Split decided by the user. PR 1a = T1.1-T1.5 + T1.8. PR 1b = T1.6, T1.7. T1.9 (Docker) moved to PR 3. Merge order: 1a, then 1b (retarget 1b to `main` after 1a merges). The original local branch `feat/backend-skeleton` is kept as a backup only and is not pushed.

- [x] **T1.1 [A]** Repo hygiene FIRST commit: `.gitattributes` (`* text=auto eol=lf`, `*.sh text eol=lf`, binary overrides), `.gitignore` (`.env`, `.env.*` except `.env.example`, `*.pem`, `.venv`, `__pycache__`, `node_modules`, `dist`, coverage, caches), `.editorconfig` (`end_of_line = lf`). Satisfies: hexagonal-layout / Monorepo structure (`.env` ignored, LF). Test-first: none (config). Verify with `git check-ignore .env`.
- [x] **T1.2 [A]** `backend/pyproject.toml` (Python 3.12; deps fastapi, uvicorn, pydantic-settings, sqlalchemy>=2, alembic, `psycopg[binary]`; dev: pytest, pytest-cov, httpx, ruff; ruff rules `E,F,I,UP,B,SIM`; pytest config with `src` layout), `backend/uv.lock` via `uv lock` (lockfile excluded from line count). Create empty packages with `__init__.py`: `domain`, `application`, `adapters`, `entrypoints` under `backend/src/eventssound/`, plus `tests/unit`, `tests/integration`. Satisfies: hexagonal-layout / Backend layer packages.
- [x] **T1.3 [A]** Test runner smoke: `backend/tests/conftest.py` and a trivial import test for the four packages (`tests/unit/test_layout.py::test_packages_importable`). TDD: write test, run `uv run pytest` and confirm it fails before the `__init__.py` files/packaging are in place if sequencing allows; otherwise confirm red via a missing package name. Confirm `uv run pytest` and `uv run ruff check .` run on Windows. Satisfies: hexagonal-layout / Backend layer packages; enables later strict TDD.
- [x] **T1.4 [A]** Settings. TDD: write `tests/unit/test_settings.py` first (missing `DATABASE_URL` raises validation error naming `DATABASE_URL`; CORS list parsing splits on comma and strips trailing `/`; `APP_ENV=production` flag; `.env.example` completeness test that compares Settings fields to root `.env.example` keys, marked skip until T3.1 lands, or implemented against a checked-in file path and unskipped in PR 3). Then `backend/src/eventssound/config.py` (`APP_ENV`, `DATABASE_URL`, `CORS_ALLOWED_ORIGINS`, `LOG_LEVEL`). Satisfies: backend-health-api / Environment-driven settings.
  - Note: the `.env.example` completeness scenario cannot pass until PR 3 creates the file. Decision for apply: add the test in PR 3 (T3.1), not PR 1.
- [x] **T1.5 [A]** App factory + `/health` + CORS. TDD: write `tests/integration/test_health.py` first: factory builds independent apps with distinct settings; `GET /health` returns 200 `{"status": "ok"}` exactly; `/health` still 200 with an unreachable DB URL; allowed origin gets `Access-Control-Allow-Origin`; disallowed origin gets none; `production` gives `app.debug is False`. Then `entrypoints/api/app.py` (`create_app(settings=None, ...)` with overridable settings and session provider, `CORSMiddleware` exact origins, no credentials), `entrypoints/api/routes/health.py`, `entrypoints/api/container.py` (composition root, documented DI extension point for the future `LlmProvider`, no LLM code). Satisfies: backend-health-api / Application factory, Health endpoint, CORS restriction; hexagonal-layout / Composition root.
  - Spec/design conflict: design `/health` body adds `service` and `version`; spec requires exactly `{"status": "ok"}`. Follow the spec (exact body). Flag for the developer if they want the extra fields (would require a spec update).
- [x] **T1.6 [A]** Database layer + readiness. TDD: write `tests/unit/test_health_usecase.py` (`check_database()` with a fake `DatabaseHealthPort`), integration tests for `GET /health/db` (200 with real Postgres, 503 with a failing fake injected through the factory, no detail leaked) and session-provider test (session yielded bound to the test URL, closed after use). Then `application/ports.py` (`DatabaseHealthPort` Protocol), `application/health.py`, `adapters/db/session.py` (SQLAlchemy 2.0 engine, `sessionmaker`, `Base` with naming convention, `pool_pre_ping=True`, `pool_recycle=300`, `pool_size=3`, `max_overflow=2`), `adapters/db/health.py` (`SELECT 1`), `/health/db` route wired in `container.py`. Needs a reachable Postgres: `docker compose up db` is not available until PR 3, so use a locally started container (for example `pgvector/pgvector:pg16` on port 55432 as `DATABASE_URL_TEST`) or a Neon dev branch for the local run; CI provides it in PR 3. Integration tests needing a real DB must skip cleanly (`pytest.mark` + env check) when no DB is reachable. Satisfies: database-migrations / SQLAlchemy 2.0 setup, Local Postgres service (scenario "Backend connects locally"); design section 5 (`/health/db`, not in spec).
- [x] **T1.7 [A]** Alembic baseline. TDD: write a migration test first (against real DB, skippable): `upgrade head` exits 0 and `alembic_version` holds the baseline id; second `upgrade head` is a no-op; `downgrade base` exits 0 with no application tables; `alembic heads` reports exactly one head. Then `backend/alembic.ini` (no credentials), `backend/migrations/env.py` (reads `DATABASE_URL` from `Settings`, targets `Base.metadata`), `script.py.mako`, `versions/0001_baseline.py` (empty up/down). Satisfies: database-migrations / Alembic baseline (all four scenarios).
- [x] **T1.8 [A]** Architecture test. TDD: write `tests/unit/test_architecture.py` first with `ast` import scanning: `domain` imports no project layer and no fastapi/sqlalchemy/pydantic_settings/alembic; `application` does not import `adapters` or `entrypoints`; `adapters` does not import `entrypoints`. Include a self-test proving a violation is detected (scan a synthetic module string/tmp file with `import sqlalchemy` and assert the failure names module and import). Fix any real violation in T1.5/T1.6 code. Satisfies: hexagonal-layout / Dependency rule, Composition root ("No adapter construction outside the root").
- [ ] **T1.9 [A] (MOVED to PR 3; code preserved on local branch `wip/docker-for-pr3`)** `backend/Dockerfile` (multi-stage, `python:3.12-slim`, `uv sync --frozen --no-dev`, non-root user, copies `src/`, `migrations/`, `alembic.ini`, `start.sh`), `backend/start.sh` (`alembic upgrade head && exec uvicorn eventssound.entrypoints.api.app:create_app --factory --host 0.0.0.0 --port ${PORT:-8000}`; LF enforced), `backend/.dockerignore`. Test-first note: none unit-level; verify by `docker build backend` and, if a DB is reachable, `docker run` hitting `/health`. If Docker Desktop is unavailable, mark verification as deferred to CI (PR 3 builds the image). Satisfies: deployment / Migrations on release (mechanism), design section 8. Final content (already implemented on `wip/docker-for-pr3`): pinned `ghcr.io/astral-sh/uv:0.11.6` image and a bounded `alembic upgrade head` retry loop in `start.sh` (5 attempts, 3 s apart, exit non-zero after the last so the platform restarts the service). The `start.sh`-related scenarios of deployment / Migrations on release (fresh database, failing migration blocks release) are verified in PR 3, not in PR 1b. Verified on the wip branch: `docker build backend` OK and the image applies migrations against a throwaway Postgres with `/health/db` OK.
- [x] **T1.10a [A]** PR 1a verification: from `backend/` run `uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest` on the `feat/backend-core` tip (no DB code present); open PR 1a (description per chained-pr template). Result: ruff clean, 25 passed. Review hardening added after the first pass: production rejects `*` in `CORS_ALLOWED_ORIGINS`; the architecture scanner resolves relative imports and `from pkg import module`; `.gitignore` covers `.neon` and `.env.local`.
- [x] **T1.10b [A]** PR 1b verification: same commands plus DB-dependent tests with `DATABASE_URL_TEST` (pgvector/pgvector:pg16 container) on the `feat/backend-db-docker` tip (no Docker files; `docker build` is verified in PR 3); open PR 1b stacked on PR 1a. Result: ruff clean, 41 passed with DB (100% coverage), 36 passed + 5 skipped without `DATABASE_URL_TEST` (96% coverage). Review hardening: `connect_timeout` in `migrations/env.py`, DB fixture fails (no skip) when `DATABASE_URL_TEST` is set but unreachable, DB-free head test, `postgres://` and `postgresql://` mapped to psycopg 3, `database_url` as `SecretStr`. Docker files (bounded migration retry in `start.sh`, uv image pinned to 0.11.6) moved to PR 3 via `wip/docker-for-pr3`, which brought PR 1b from ~497 to ~449 lines; the user accepted ~449 lines for both PR 1a and PR 1b.

### PR 1a / PR 1b verification checklist (items for 1b only apply once PR 1b is verified)
- [ ] First commit contains only `.gitattributes`, `.gitignore`, `.editorconfig`
- [ ] `git ls-files --eol` shows no CRLF in tracked files; `.gitattributes` enforces `eol=lf` for `*.sh` (`start.sh` itself lands in PR 3)
- [ ] `uv run pytest` green (DB-dependent tests skip cleanly or pass with a DB)
- [ ] `uv run ruff check .` and `ruff format --check .` clean
- [ ] `GET /health` returns exactly `{"status":"ok"}`; CORS allowed/disallowed scenarios pass
- [ ] `alembic upgrade head` / re-run / `downgrade base` / single head verified against a real Postgres
- [ ] Architecture test passes and its violation self-test fails as intended
- [ ] (PR 3 only) `docker build backend` succeeds; not applicable to PR 1a/1b
- [ ] No `.env`, secrets, or real connection strings in the diff; diff ~449 lines excluding `uv.lock` (accepted by the user)
- [ ] No `Co-Authored-By` or AI attribution in any commit

---

## PR 2: Frontend skeleton (`feat/frontend-skeleton`, base `main`, ~180-250 lines)

- [x] **T2.0 [A]** Create branch `feat/frontend-skeleton` from `main` (independent of PR 1; do not branch from PR 1).
- [x] **T2.1 [A]** Scaffold `frontend/` manually (no generator boilerplate beyond need): `package.json` (Node 22, scripts `dev`, `build`, `lint`, `test`), `package-lock.json` (excluded from count), `vite.config.ts` (with Vitest config, jsdom), `tsconfig*.json`, `eslint.config.js`, `index.html` (`<html lang="es">`), `src/main.tsx`, `src/vite-env.d.ts`, `src/env.ts` (reads `VITE_API_BASE_URL`, no hardcoded host). Do not add Tailwind, shadcn, router, or auth. Satisfies: frontend-shell / Stack and build, Env-driven API URL.
- [x] **T2.2 [A]** Vitest + Testing Library setup and the first failing test: `src/App.test.tsx` "shell renders heading `EventsSound` and `document.documentElement.lang === 'es'`" (red), then minimal `App.tsx` + `App.css` (green). Satisfies: frontend-shell / Single-page shell, Smoke test.
- [x] **T2.3 [A]** Health call. TDD: extend `App.test.tsx` first with mocked `fetch`: pending shows `Cargando estado del servicio...`; 200 `{"status":"ok"}` shows `Servicio operativo`; rejection and 503 show `Servicio no disponible` without crashing; request URL equals `${VITE_API_BASE_URL}/health` (stub env, e.g. `https://api.example/health`). Then `src/api/health.ts` and wire into `App.tsx`. Satisfies: frontend-shell / Health status display, Env-driven API URL.
  - Spec/design conflict: design describes a second "Base de datos" indicator via `/health/db` and a "waking up" copy; spec requires only the single `/health` status line with three states. Follow the spec; the extra indicator is NOT built in P0 (log as follow-up).
- [x] **T2.4 [A]** Run `npm ci`, `npm run lint`, `npm run test -- --run`, `npm run build`; open PR 2.

### PR 2 verification checklist
- [x] `npm ci && npm run lint && npm run test -- --run && npm run build` all exit 0
- [x] Tests cover pending, ok, 503, network-error, URL, `lang="es"`
- [x] No hardcoded backend host (`rg "onrender|localhost:8000" frontend/src` returns nothing outside tests/docs)
- [x] No Tailwind/shadcn/router/auth dependencies in `package.json`
- [x] Lockfile committed; diff under 400 lines excluding `package-lock.json`
- [x] Spanish UI copy only in user-facing strings; code and identifiers in English

---

## PR 3: CI + Compose + Docker (`feat/ci-compose`, base `main` after PR 1a + PR 1b + PR 2 merged, ~230-270 lines)

- [x] **T3.0 [A]** Confirm PR 1 and PR 2 are merged into `main`; create `feat/ci-compose` from updated `main`. If not merged, STOP and report (do not stack on unmerged branches).
- [ ] **T3.0b [A]** Cherry-pick the three Docker commits from local branch `wip/docker-for-pr3` (`backend/Dockerfile`, `backend/start.sh` with bounded alembic retry loop, `backend/.dockerignore`, pinned uv image) as the first commits of PR 3 (T1.9). Re-run `docker build backend` and a container run against a throwaway Postgres (`/health/db` OK). Verify the `start.sh` scenarios of deployment / Migrations on release here.
- [x] **T3.1 [A]** (root `.env.example` was copied in manually by the developer because permission rules deny agent writes to `.env*`; completeness test passes) `docker-compose.yml`: `db` service `pgvector/pgvector:pg16`, named volume `pgdata`, `pg_isready` healthcheck, port `5432:5432`, creds from `.env`; `backend` service under `profiles: ["app"]` building `backend/Dockerfile`. Root `.env.example` documenting every variable (`APP_ENV`, `DATABASE_URL`, `CORS_ALLOWED_ORIGINS`, `LOG_LEVEL`, Postgres creds, `VITE_API_BASE_URL` marked public) with harmless placeholders. TDD: add the deferred `.env.example` completeness test (Settings fields vs `.env.example` keys, no real secret values) from T1.4 first, see it fail, then add the file. Verify `docker compose up -d db` and `uv run alembic upgrade head` against it (if Docker Desktop available). Satisfies: database-migrations / Local Postgres service; backend-health-api / Environment-driven settings (.env.example completeness); hexagonal-layout / Monorepo structure; frontend-shell / Env-driven API URL (documented).
- [x] **T3.2 [A]** `.github/workflows/ci.yml`: triggers `pull_request` and `push` to `main`; concurrency group; `backend` job (checkout, `astral-sh/setup-uv` with cache, Python 3.12, Postgres service container `pgvector/pgvector:pg16` with health check and throwaway literal creds, `uv sync --frozen`, `ruff check`, `ruff format --check`, `alembic upgrade head`, `pytest --cov=eventssound`, `docker build backend` without push); `frontend` job (setup-node 22 with npm cache, `npm ci`, `npm run lint`, `npm run test -- --run`, `npm run build`); `defaults.run.working-directory` per job; no secrets. Test-first note: validate YAML locally if a linter is available (actionlint is optional, ask before installing); the real test is the green run on the PR. Satisfies: ci-pipeline / Triggers, Backend job, Frontend job, No secrets in CI config.
- [x] **T3.3 [A]** README: stack, local run steps (PowerShell and POSIX where different), `git config core.autocrlf false` note, Windows notes, `docker compose up -d db` workflow, how to run tests, branch protection recommendation. Satisfies: proposal Affected Areas (README); hexagonal-layout / Monorepo structure.
- [ ] **T3.4 [M]** GitHub repo settings: after the first green CI run, enable branch protection on `main` requiring the `backend` and `frontend` checks, PRs only. Satisfies: design section 9 (mitigation for Render deploying on red CI).
- [ ] **T3.5 [A]** Open PR 3; confirm CI green on the PR, including intentionally verifying "lint violation fails at `ruff check`" is covered by workflow step ordering (inspection only, no deliberately broken commit pushed).

### PR 3 verification checklist
- [ ] CI run on the PR is green for both jobs
- [ ] Postgres service container migrations step passes (`alembic upgrade head`)
- [ ] Docker build step passes in CI (covers T1.9 if it was deferred)
- [ ] `.env.example` completeness test passes; no real secrets; `git ls-files` shows only `.env.example` as env file
- [ ] `docker compose config` validates; `docker compose up -d db` healthy (or documented as unverified locally)
- [ ] README commands work from a fresh checkout on Windows (PowerShell)
- [ ] Workflow contains no secrets; diff ~230-270 lines (includes the 48 Docker lines)

---

## PR 4: Deploy config + smoke check + strict TDD flip (`feat/deploy-config`, base `main` after PR 3 merged, ~90-130 lines)

- [x] **T4.0 [A]** Confirm PR 3 merged and CI green on `main`; create `feat/deploy-config` from `main`.
- [x] **T4.1 [A]** (deviations in apply-progress-pr4.md: no `rootDir`, public URL vars as plain values, `autoDeployTrigger: checksPass`; real validation happens at T4.7) `render.yaml` Blueprint per design section 10: `eventssound-api` (docker, free, `rootDir: backend`, `healthCheckPath: /health`, `APP_ENV=production`, `DATABASE_URL` and `CORS_ALLOWED_ORIGINS` with `sync: false`) and `eventssound-web` (static, `rootDir: frontend`, `npm ci && npm run build`, publish `dist`, `VITE_API_BASE_URL` `sync: false`, SPA rewrite). No `databases:` block. FIRST verify field names (`runtime` vs `env`, static plan, `rootDir`, `routes`) against current Render docs; the design outline is intent, not final syntax. Satisfies: deployment / Hosting topology, Secrets and configuration, Migrations on release. Test-first note: none; validate with Render's Blueprint validation when the Blueprint is created (T4.6).
- [x] **T4.2 [A]** Satisfied by the existing `scripts/smoke.ps1` (no second script). Deployed invocation: `scripts/smoke.ps1 -BackendUrl https://<api> -FrontendUrl https://<web> -Origin https://<web> -TimeoutSec 30 -Retries 12 -RetryDelaySec 10`; exit 0 = all PASS. Original text: smoke check script `scripts/smoke_check.py` (stdlib only, or `.sh`/`.ps1` equivalent matching the repo convention): `GET <url>/health`, retry up to 90 s, exit 0 on 200 `{"status":"ok"}`, exit non-zero printing last status or error. TDD: write `backend/tests/unit/test_smoke_check.py` first, with a local `http.server` fixture: passes when healthy, passes after initial failures, fails loudly after timeout (use a shortened timeout parameter), then implement. If placed outside `backend/`, keep it importable from tests via explicit path. Satisfies: deployment / Live backend health (both scenarios).
- [x] **T4.3 [A]** (recorded in apply-progress-pr4.md) Verify Render free-tier facts and record in apply-progress: no `preDeployCommand` on free instances (start-script migration stays), static site plan, card requirement, service-name availability, Neon free limits. Satisfies: design sections 11 and 17.
- [x] **T4.4 [A]** (README Deploy section and documentacion/deploy.md) README additions: live URLs (placeholders until T4.8), required variable names only, deploy order (backend with placeholder origin, static site, update `CORS_ALLOWED_ORIGINS`, redeploy backend), cold-start and warm-up note, rollback steps. Satisfies: deployment / Secrets and configuration (README documents URLs and variables).
- [x] **T4.5 [A]** (`rules.apply` became a mapping with a `rules` list; the old file was not valid YAML) Strict TDD flip in `openspec/config.yaml`: `strict_tdd: true` (top-level and under `testing`), `testing.runner.command` (a command that works from repo root, e.g. `uv run --project backend pytest backend/tests`; the spec says `pytest`, so the command MUST invoke pytest), `apply.tdd: true`, non-empty `apply.test_command` and `verify.test_command`, `verify.build_command`, update `quality.linter` (ruff) and frontend runner (vitest) notes. Execute `verify.test_command` from the repo root and confirm exit 0 BEFORE committing the flip; confirm CI passed on `main` first (done in T4.0). Satisfies: ci-pipeline / Strict TDD config flip.
- [ ] **T4.6 [M]** (steps in documentacion/deploy.md) Create Neon project (free tier), copy the DIRECT (non-pooled) connection string, rewrite scheme to `postgresql+psycopg://`, keep `sslmode=require`. Do not paste the string into any repo file or chat log. Satisfies: deployment / Hosting topology.
- [ ] **T4.7 [M]** In Render workspace `EventsSoundDr`: create the Blueprint from the repo (after PR 4 merges), then set `DATABASE_URL` (Neon string), `CORS_ALLOWED_ORIGINS` (static site URL, scheme included, no trailing slash) and `VITE_API_BASE_URL` (backend URL) in the dashboard; redeploy backend after the CORS value is known. If `channel_binding=require` fails, drop that parameter. Satisfies: deployment / Secrets and configuration, Migrations on release.
- [ ] **T4.8 [A after T4.7]** Run the smoke check against the live backend URL (cold and warm); manually (developer) load the live frontend and confirm `Servicio operativo` with no CORS errors in the console; confirm `alembic_version` in Neon contains the baseline id (Neon SQL editor, [M]). Fill the live URLs into the README in a small follow-up commit `docs: add live urls` (tiny, may be a direct PR to `main`). Satisfies: deployment / Live backend health, Live frontend and cross-origin integration, Migrations on release (fresh database scenario).
- [ ] **T4.9 [M]** Failure scenario check (optional but recommended): confirm a failing migration blocks release (behavior of start script plus health check). Can be reasoned from design D5 and documented instead of executed, to avoid breaking the live deploy. Satisfies: deployment / Migrations on release (failure scenario).

### PR 4 verification checklist
- [ ] `render.yaml` matches current Render schema (verified against docs, not memory)
- [ ] Smoke check unit tests pass; script exits 0 on live backend and non-zero on a dead URL
- [ ] `verify.test_command` from `openspec/config.yaml` exits 0 from the repo root
- [ ] `openspec/config.yaml` has `strict_tdd: true`, `apply.tdd: true`, non-empty commands
- [ ] `git grep` for the Neon host/password finds nothing; `DATABASE_URL` only `sync: false`
- [ ] Live: backend `/health` 200 over HTTPS, frontend shows `Servicio operativo`, no CORS errors, Neon `alembic_version` populated
- [ ] README lists live URLs and variable names only; diff under 400 lines

---

## Dependency summary

| Task group | Parallel with | Sequential after |
| ---------- | ------------- | ---------------- |
| T0.x | none | none |
| PR 1 tasks | PR 2 tasks (independent branches) | T0.x; internally T1.1 -> T1.2 -> T1.3 -> T1.4/T1.5 -> T1.6 -> T1.7; T1.8 after T1.6; T1.9 anytime after T1.2 |
| PR 2 tasks | PR 1 tasks | T0.1; internally T2.1 -> T2.2 -> T2.3 -> T2.4 |
| PR 3 tasks | none | PR 1 and PR 2 merged |
| PR 4 tasks | T4.3 and T4.6 can start early (research and Neon account) | PR 3 merged; T4.7 after PR 4 merge; T4.8 after T4.7 |

Developer manual actions (summary): T0.1 (repo/remote), T3.4 (branch protection), T4.6 (Neon project), T4.7 (Render Blueprint + dashboard env vars), T4.8 (browser check, Neon SQL check), T4.9 (optional).

## Unverified assumptions to check during apply

| # | Assumption | Check at | Fallback |
| - | ---------- | -------- | -------- |
| A1 | Render free web services have no `preDeployCommand` | T4.3 | Migrations stay in `start.sh` (design D5); if a hook exists, still keep start-script approach for P0 |
| A2 | Render Blueprint field names for static services (`runtime: static` vs `env: static`, `routes`, plan) | T4.1 | Create services manually in the dashboard and keep `render.yaml` as documentation |
| A3 | Render and Neon free plans need no card; Neon free limits (storage, compute hours, auto-suspend ~5 min) | T4.3 / T4.6 | VM + Docker Compose fallback (proposal) |
| A4 | Neon with psycopg3: `sslmode=require` works; `channel_binding=require` works; direct endpoint is fine for Alembic | T4.7 / T4.8 | Drop `channel_binding`; use direct (non-pooled) host |
| A5 | Docker Desktop is available on the dev machine | T0.2 | Neon dev branch as local DB; DB tests skip locally; CI is the authority |
| A6 | `onrender.com` service names `eventssound-api` / `eventssound-web` are free | T4.7 | Names get a suffix; update CORS and `VITE_API_BASE_URL`, redeploy |
| A7 | `pgvector/pgvector:pg16` image works as CI service container and on Compose | T3.1 / T3.2 | Use `postgres:16-alpine` for P0 and switch in P2 |
| A8 | `uv`, Python 3.12, Node 22 installed locally; `uv sync --frozen` works on Windows | T0.2 | Ask the developer before installing anything |
| A9 | `verify.test_command` runnable from repo root with `uv run --project backend pytest backend/tests` and sdd-apply/verify can execute it | T4.5 | Use `cd backend && uv run pytest` style command wrapper that the agent runner supports |
| A10 | `git` repo and GitHub remote exist and `main` is the default branch | T0.1 | Developer initialises; PR flow cannot start otherwise |

## Open spec/design conflicts (resolved here in favor of the spec)

1. `/health` body: spec says exactly `{"status":"ok"}`; design adds `service` and `version`. Tasks follow the spec.
2. Frontend: spec has one status line with three states; design adds a second DB indicator and "waking up" copy. Tasks follow the spec; the DB indicator is deferred. `/health/db` is still built on the backend (design D6) but is not displayed.
3. `testing.runner.command`: spec says `pytest`; design suggests `uv run --project backend pytest backend/tests`. The task uses the latter because it contains `pytest` and runs from the repo root.
