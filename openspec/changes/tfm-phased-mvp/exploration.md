# Exploration: tfm-phased-mvp

## Summary
The repo is greenfield. A deployed MVP by 2026-10-25 gives 16 days at about 2-3 h/day (32-48 h total, roughly 12-15 focused days at best), so the full planned stack does not fit. Recommended approach: vertical slices. Ship a thin end-to-end quote agent early, with a deterministic price oracle and evals. Everything else is static or cut.

## 1. Minimum that keeps the AI quote agent as the heart
- **Domain core:** synthetic catalog (~25-40 items), `calcular_precio` as a pure function, `consultar_disponibilidad` over a small bookings table.
- **Tools:** `buscar_equipamiento` is RAG-lite over the catalog (pgvector or in-memory embeddings; no separate vector DB).
- **Agent:** LangGraph graph with 3 nodes (understand, call tools, draft proposal). Outputs a structured quote (Pydantic) plus proposal text.
- **LlmProvider port:** adapters for OpenRouter (or a free-tier API) and Replay (for tests). Ollama optional, last.
- **Evals:** golden set of 15-20 synthetic requests. The oracle checks the quoted price equals `calcular_precio(items)` and the items are valid and available. Pytest suite in replay mode; LangSmith as an optional live run.
- **Public chat hardening (minimum):** input length cap, "data not instructions" system prompt, schema-validated output, per-IP rate limit, daily token/cost cap. Prices never come from the LLM, so the oracle also guards against injection.

## 2. Cut or make static
| Area | Decision |
|---|---|
| About, portfolio | Static React pages with hardcoded synthetic content |
| Service catalog | Read-only list from DB seed, no CRUD UI |
| Bookings | A quote can create a "pending booking" row. No calendar UI, no payments |
| Auth/RBAC | Minimal JWT, 2 seeded users (client, admin). Admin = single page listing quotes and bookings. Post-MVP if time runs out |
| ElevenLabs, image generation | Cut (stretch) |
| Sentry | Only if time remains (~10 min SDK hookup) |
| Ollama | Optional, last |
| Playwright e2e | Cut; pytest plus manual smoke test |

## 3. Approaches compared
| | A. Vertical slice first (recommended) | B. Layer by layer | C. AI-only demo |
|---|---|---|---|
| Idea | Skeleton + deploy first, agent end-to-end, then widen | Foundation, backend, frontend, AI last | Agent plus minimal UI, no auth/bookings/admin |
| Pros | Live URL early, AI central, risk surfaced early | Clean architecture first | Lowest effort, strongest AI focus |
| Cons | Needs discipline to keep slices thin | AI lands last and is first to be cut; breaks "AI is the core" | Looks like a toy; weak "real app" |
| Effort | M | L (will not fit) | S |

**Recommendation: A.** Keep C as the fallback floor: if at day 10 the schedule is behind, drop auth/admin and ship the public chat only.

## 4. Phases
| # | Phase | Days | Deliverable | Exit criteria |
|---|---|---|---|---|
| P0 | Foundation and walking skeleton | 1.5 | Monorepo (`backend/`, `frontend/`), hexagonal folders, FastAPI `/health`, Postgres in Compose, Alembic baseline, pytest + ruff, GitHub Actions CI, Vite shell, skeleton deployed; flip `strict_tdd` to true | CI green; live URL serves /health and the shell |
| P1 | Domain core | 1.5 | Catalog models + seed, `calcular_precio`, `consultar_disponibilidad`, repositories (ports + SQLAlchemy adapters), read-only catalog API | Pricing/availability unit tests pass; seed loads |
| P2 | Agent core (heart) | 3 | `LlmProvider` port (Replay + OpenRouter), `buscar_equipamiento`, LangGraph quote agent, `/quote/chat` | End-to-end quote works locally; replay tests deterministic |
| P3 | Evals and hardening | 2 | Golden set + price oracle, LangSmith traces, injection guard, rate limit, cost cap, I/O validation | Eval pass rate reported (target >= 90% oracle match); injection and cost-cap tests pass |
| P4 | UI | 2 | Chat page (shadcn/ui), proposal view, static About/Portfolio/Catalog, minimal JWT login + admin quotes list | Demo flow clickable on localhost |
| **P5 (MVP, 2026-10-25)** | Deploy and deliverables | 2 | Production deploy, README (stack, run steps, test credentials), public repo, slides, video | Live URL runs the quote flow; README complete; slides and video URLs exist |
| Buffer | Slack | 1+ | Overflow | |

Suggested calendar at ~2.5 h/day: Oct 9-11 P0; Oct 12-14 P1; Oct 15-19 P2; Oct 20-21 P3; Oct 22-23 P4; Oct 24-25 P5. Record the video on Oct 24 against a staging deploy. Each phase should slice into 2-4 PRs under ~400 lines (P0: backend skeleton, frontend skeleton, CI + Compose; P2: provider port + adapters, tools, graph, endpoint; P3: oracle evals, guardrails).

## 5. Deployment and LLM cost control (unverified suggestions; check current free-tier limits)
- Frontend: Vercel or Cloudflare Pages.
- Backend: Render or Fly.io, or one small VM with Docker Compose. Expect cold starts.
- DB: Neon or Supabase free Postgres with pgvector.
- LLM: OpenRouter free models or a cheap model, hard daily budget cap via env var, per-IP rate limit, max output tokens. Pre-recorded replay fallback for the video.
- Secrets only in deployment env vars.

## 6. Risks
1. Time (high): availability unknown; plan assumes 2-3 h/day. Below ~25 h, fall back to approach C.
2. Stack breadth: hexagonal + LangGraph + RBAC + deploy at once. Mitigate by deploying the skeleton in P0.
3. LLM provider flakiness / free-tier rate limits: mitigate with replay mode.
4. Free-tier cold starts and limits during demo or grading.
5. Eval quality: oracle mismatches may need prompt iteration; P3 can slip.
6. Strict TDD slows pace: apply to domain core and oracle, relax for UI.
7. Scope creep (ElevenLabs, images, admin UI).

## 7. Open questions
1. Real hours per week/day available until Oct 25?
2. Is a deployed admin/JWT area required, or is public chat + quote list enough?
3. LLM provider and budget (OpenRouter key, dollar cap)?
4. Is the TFM deadline exactly Oct 25, and are slides and video included?
5. UI language: Spanish or English?
6. Preferred host: Render, Fly.io, or one VM?

## 8. Proposed first change
`walking-skeleton-and-deploy` (P0): monorepo, hexagonal skeleton, CI, Compose, `/health`, live deploy.
