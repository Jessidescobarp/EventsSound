# Proposal: walking-skeleton-and-deploy (P0)

Parent plan: `openspec/changes/tfm-phased-mvp/exploration.md` (phase P0, sections 4 and 8).

## Summary

Stand up an empty-but-real EventsSound system end to end: monorepo, hexagonal backend skeleton with `/health`, Postgres in Docker Compose, Alembic baseline, pytest + ruff, GitHub Actions CI, a Vite+React+TS shell, and a live deploy. No product features. The goal is to surface integration and deploy risk on day 1, not on Oct 24.

## Intent

**Problem.** The repo is greenfield (only `README.md`). The MVP must be live by 2026-10-25 (16 days, ~2-3 h/day). Deploying for the first time in P5 would concentrate the highest-uncertainty work (hosting, env vars, CORS, DB connectivity, cold starts) at the end of the schedule.

**Why now.** Every later phase (P1 domain, P2 agent, P3 evals, P4 UI) needs a working repo layout, test runner, CI, and a deploy target. Doing the walking skeleton first de-risks them all and enables Strict TDD from P1 onward.

**Success looks like.** CI is green on `main`, a live URL serves `GET /health` (backend) and the React shell (frontend), and `strict_tdd` is flipped to `true`.

## Scope

### In scope

| Area | Deliverable |
| ---- | ----------- |
| Monorepo | `backend/`, `frontend/`, root `docker-compose.yml`, `.gitignore`, `.env.example`, README run steps |
| Backend skeleton | FastAPI app factory, `GET /health`, hexagonal folders (`domain/`, `application/`, `adapters/`, `entrypoints/`), settings via env, DI wiring point |
| Database | Postgres service in Compose, SQLAlchemy 2.0 engine/session setup, Alembic initialised with an empty baseline revision |
| Quality | pytest (+ httpx/TestClient) with a `/health` test, ruff lint + format config |
| CI | GitHub Actions: backend lint + test (Postgres service container), frontend install + build + lint |
| Frontend skeleton | Vite + React + TypeScript shell (single page, layout, API base URL via env, calls `/health` to show status). Vitest configured with one smoke test |
| Deploy | Live deploy of backend, DB, and frontend skeleton; secrets only in host env vars |
| Config flip | Set `strict_tdd: true`, `testing.runner.command`, `apply.tdd`, `apply.test_command`, `verify.test_command` in `openspec/config.yaml` once pytest runs |

### Out of scope (explicitly deferred)

| Deferred | Phase |
| -------- | ----- |
| AI agent, LangGraph, `LlmProvider`, RAG, tools | P2 |
| Evals, golden set, LangSmith, injection guard, rate limit, cost cap | P3 |
| Auth, JWT, RBAC, seeded users, admin page | P4 |
| Service catalog models, seed data, pricing, availability, bookings | P1 |
| shadcn/ui, real pages (About, Portfolio, Chat) | P4 |
| Sentry, Ollama, Playwright, ElevenLabs, image generation | cut or stretch |
| Custom domain, TLS tuning, autoscaling, production-grade observability | post-MVP |

### Impact on agent and security

- **Agent (tools, prompts, evals):** none in this change. Only the hexagonal folder structure and DI point where P2 will plug the `LlmProvider` port.
- **Security (OWASP GenAI):** no LLM surface yet. Baseline hygiene only: no secrets in the repo (`.env` ignored, `.env.example` committed), secrets in host env vars, CORS restricted to the frontend origin, no debug mode in production.

## Approach

1. **Layout.** One repo, two apps. Backend uses hexagonal packages: `domain` (pure, no framework imports), `application` (use cases + ports), `adapters` (SQLAlchemy, HTTP), `entrypoints` (FastAPI routers, composition root). Rationale: matches the TFM architecture requirement and keeps P1/P2 additions additive.
2. **Backend first, tests first.** Write the `/health` test, then the endpoint. Keep the app factory pattern so tests build the app with overridden dependencies.
3. **Compose for local parity.** `docker-compose.yml` with `db` (Postgres) and optionally `backend`; developer can run `docker compose up db` and run the app natively.
4. **Alembic baseline.** Initialise Alembic wired to SQLAlchemy metadata with an empty initial revision, proving migrations run in CI and in deploy.
5. **CI.** Two jobs (backend, frontend) on PR and push to `main`. Backend job uses a Postgres service container and runs `ruff check`, `ruff format --check`, `alembic upgrade head`, `pytest`.
6. **Frontend shell.** Vite+React+TS, env-driven API URL, fetches `/health`, renders status. Minimal on purpose.
7. **Deploy.** Deploy backend + managed Postgres + static frontend. Provider choice is an open question (below). Prefer the option that gives a public URL fastest, with migrations run on release.
8. **Flip strict TDD.** After pytest passes locally and in CI, update `openspec/config.yaml` (`strict_tdd: true`, runner command `pytest`, `tdd: true`, test commands). From P1 onward `sdd-apply` and `sdd-verify` run in Strict TDD mode. Per exploration risk 6, apply strictly to domain and oracle code and relax for UI.

### Alternatives considered

| Option | Verdict |
| ------ | ------- |
| Separate repos for frontend and backend | Rejected: doubles CI/PR overhead for a solo, 16-day project |
| Defer deploy to P5 | Rejected: concentrates the highest risk at the deadline |
| Skip Alembic until P1 | Rejected: baseline migration is cheap now and validates the deploy pipeline |
| Full folder-per-feature "screaming" layout now | Deferred: start with layer folders, introduce bounded contexts when P1 brings real domain code |

## Rollback Plan

Low risk: greenfield, no users, no data.

- Each PR is independently revertible (`git revert`); the repo returns to the README-only state at worst.
- Deploy: take down or delete the hosted services; no persistent data worth preserving. Alembic baseline is empty, so `alembic downgrade base` is a no-op.
- `openspec/config.yaml` flip: if the test runner proves unstable, revert the single commit and set `strict_tdd` back to `false`.
- Fallback if the chosen host blocks the schedule: switch to a single VM with Docker Compose (no code changes, only deploy config).

## Affected Areas

| Path | Change |
| ---- | ------ |
| `backend/` | New: app, hexagonal packages, Alembic, tests, `pyproject.toml`, Dockerfile |
| `frontend/` | New: Vite+React+TS app, Vitest config, Dockerfile or static build config |
| `docker-compose.yml`, `.env.example`, `.gitignore` | New |
| `.github/workflows/ci.yml` | New |
| `README.md` | Updated: stack, local run steps, live URL |
| `openspec/config.yaml` | Updated: Strict TDD flip and test commands |

## Success Criteria

- [ ] `docker compose up` brings up Postgres; backend connects to it
- [ ] `GET /health` returns 200 locally and on the live URL
- [ ] `alembic upgrade head` succeeds locally, in CI, and on deploy
- [ ] `pytest` and `ruff check` pass locally and in CI; CI is green on `main`
- [ ] Frontend builds in CI and the deployed shell displays backend health status
- [ ] No secrets committed; `.env.example` documents every variable
- [ ] `openspec/config.yaml` has `strict_tdd: true` with a working `test_command`
- [ ] Total effort within ~1.5 days (target finish Oct 11)

## Risks

| Risk | Likelihood | Mitigation |
| ---- | ---------- | ---------- |
| Hosting choice stalls the deploy | Medium | Decide host before apply starts; VM + Compose is the known-good fallback |
| Free-tier cold starts and limits (verify current limits, unverified) | Medium | Accept for skeleton; health-ping or paid tier decision before P5 |
| CORS / env misconfiguration between frontend and backend hosts | Medium | Env-driven API URL and allowed origin; verify on the live deploy, not only locally |
| Windows dev environment friction (Docker, line endings, paths) | Medium | `.gitattributes` for LF, document steps, CI as source of truth |
| Over-engineering the skeleton (time sink) | Medium | Hard stop: no features, no shadcn/ui, no auth; 1.5-day budget |
| Hexagonal layout too heavy for tiny code | Low | Keep folders minimal; add structure only when P1 needs it |
| Strict TDD slows pace | Low | Scope strict TDD to backend domain/oracle; relax for UI |

## Review Workload Forecast

| Metric | Estimate |
| ------ | -------- |
| Estimated changed lines | ~700-1000 total, of which ~300-400 are generated/lock/boilerplate (lockfiles excluded from the count) |
| Exceeds 400-line budget | Yes, as a single PR |
| Chained PRs recommended | Yes |
| Decision needed before apply | Yes (per `ask-on-risk`): chained/stacked PRs vs `size:exception` |

Suggested slicing (stacked to `main`, each reviewable in about 60 minutes, tests and docs stay with their unit):

| PR | Slice | Approx. lines | Depends on |
| -- | ----- | ------------- | ---------- |
| 1 | Backend skeleton: layout, `/health`, settings, SQLAlchemy session, Alembic baseline, pytest + ruff, Dockerfile | 250-350 | none |
| 2 | Frontend skeleton: Vite+React+TS shell, health call, Vitest smoke test | 150-250 (excluding lockfile) | none (independent of PR 1) |
| 3 | CI + Compose: `docker-compose.yml`, `.env.example`, GitHub Actions workflow, README run steps | 120-200 | PR 1, PR 2 |
| 4 (optional) | Deploy config + `openspec/config.yaml` Strict TDD flip | 50-120 | PR 3 |

Merge order: 1, 2, 3, 4. PR 4 can fold into PR 3 if the total stays under 400 lines.

## Decisions (resolved 2026-10-09)

1. **Backend host:** Render web service (free tier, no card). Accept cold starts (~1 min after 15 min idle); warm the service before demos/video.
2. **Frontend host:** Render Static Site (same workspace `EventsSoundDr`).
3. **Managed Postgres:** Neon free tier, NOT Render Postgres (free Render Postgres expires after 30 days). pgvector needed in P2. Free-tier limits not yet verified.
4. **UI language:** Spanish. Code, identifiers, docs and artifacts stay in English.

## Open Questions

1. **Delivery strategy for this change:** chained/stacked PRs (recommended) vs `size:exception`. Delivery strategy is `ask-on-risk`: decide when tasks are sliced.

## Next Step

Run `sdd-spec` and `sdd-design` in parallel once open questions 1-3 are answered (design depends on the hosting choice).
