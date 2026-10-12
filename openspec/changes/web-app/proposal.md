# Proposal: web-app (P4 full frontend plus the backend support it needs)

## Intent
Ship the whole user-facing product by 2026-10-25: chat page for the quote agent, proposal view, static pages (about, portfolio, service catalog), minimal JWT login (client and admin) and an admin page listing quotes and bookings. Frontend scope is NOT reduced (developer decision; the old "drop auth/admin" fallback is withdrawn). Three backend pieces exist in no other plan and are owned here: authentication, quote persistence, admin read API. The public chat is a prompt-injection and cost target, so the UI is part of the defense: no HTML from model output, Spanish rate-limit and budget errors, and a quote breakdown rendered from the structured `quote`, never from LLM prose.

## Scope
### In
- FE: shell (router, layout, tokens, Spanish copy module, typed API client, cold-start warm-up), static pages, catalog page, chat page, proposal view, login, client "my quotes", admin quotes and bookings tables.
- BE: `POST /auth/login`, RBAC dependency, `users` table and guarded user seed, `quotes` table with automatic save, `GET /me/quotes`, `GET /admin/quotes`, `GET /admin/bookings`, optional client action `POST /quotes/{id}/booking-request`.
- Deploy config: CSP and security headers on the static site, Render env wiring, docs and ADRs.
### Out
Payments, calendar UI, CRUD admin, password reset, registration, refresh tokens, social login, i18n beyond Spanish, streaming chat, stored conversations, Playwright (see below), real branding assets.

## Capabilities
New (FE): `web-shell`, `static-pages`, `catalog-page`, `chat-ui`, `quote-breakdown-view`, `auth-ui`, `admin-ui`. New (BE): `user-auth`, `quote-persistence`, `admin-api`.
Modified (deltas against the quote-agent plan, not yet in `openspec/specs/`): `chat-endpoint` (additive `quote_id`, optional bearer token, `Retry-After` exposed via CORS); CORS config in `app.py`.

## Approach and decisions
| Topic | Decision | Why / tradeoff |
| ----- | -------- | -------------- |
| UI stack | React Router (declarative) + Tailwind CSS v4 (`@tailwindcss/vite`) + ~8 hand-written primitives (Button, Card, Field, Alert, Spinner, Table, Badge, Layout). NOT shadcn/ui | shadcn needs CLI, Radix packages, aliases and copies hundreds of generated lines into the PR budget. Tailwind is a plugin plus one CSS file. Deviates from the "shadcn/ui" line in `config.yaml` and `architecture.md`; ADR records it. Alternative: CSS modules (zero deps, slower to write) |
| Data fetching | Own `apiFetch` (timeout, AbortController, typed error codes) plus a ~60-line `useRequest` hook. No TanStack Query | About 8 endpoints; the shell already holds the cold-start retry loop (`App.tsx`) to extract and reuse. Revisit only if the hook grows |
| Cold start | One `useBackendStatus` hook (extracted from the shell) drives a non-blocking banner ("servidor despertando, hasta 1 minuto"). Chat uses warm-then-send: wait for `/health` (90 s window), then ONE POST, never auto-retry a POST (double billing). GETs retry with backoff; every failure state has a "Reintentar" button | Render free ~1 min wake plus Neon wake |
| State | Auth in a React context; chat in `useReducer`, in memory only (server is stateless; client sends the last 8 messages, trims to 1000 chars each and 4000 total) | No localStorage of conversations (privacy) |
| i18n | Spanish only, every string in `src/copy/es.ts` (typed const), plus an error-code to message map (`rate_limited` with `Retry-After` seconds, `daily_budget_exhausted`, `chat_disabled`, `llm_unavailable`, `internal_error`, 422, `invalid_credentials`) | No i18n library; one module keeps copy reviewable |
| Safe rendering | Model text only as React text nodes (`white-space: pre-wrap`); no markdown, no `dangerouslySetInnerHTML` (eslint `react/no-danger` = error); money via `Intl.NumberFormat("es-CO")`; quote lines from `quote.lines` with a Spanish label map keyed by `kind`, unknown kind falls back to "Cargo"; unsupported `quote.version` shows only the text; runtime shape guard on responses | Tests feed `<img onerror>` and `<script>` in `reply` and assert text-only |
| A11y basics | Landmarks, skip link, visible focus, labelled fields, `role="status"/"alert"`, `aria-live="polite"` on the chat log, keyboard-only chat, contrast-checked tokens, `prefers-reduced-motion`; tests query by role. `eslint-plugin-jsx-a11y` only if it supports the pinned ESLint (UNVERIFIED) | Cheap, testable |
| Design tokens | `src/styles/tokens.css` via Tailwind `@theme`: neutral palette plus ONE brand variable, system font stack, spacing and radius scale. Logo is a text wordmark | Owner supplies assets later: swap is one file |
| Testing | vitest + Testing Library; `msw` in node for contract fixtures typed from the specs; no Playwright (config says e2e cut; ~2 min CI and browser install for ~150 lines). Instead: extend `scripts/smoke.ps1` (login negative case, `/docs`) and a manual end-to-end checklist for the video | Cheapest honest proof |
| Token storage | Bearer JWT in `Authorization`, kept in `sessionStorage`, 60 min TTL, no refresh token, logout discards it | Cookies are fragile here: web and api are cross-site (`onrender.com` is on the Public Suffix List), so `SameSite=None; Secure`, third-party-cookie blocking, `allow_credentials=True` and a CSRF token would all be needed. Bearer has no CSRF surface and keeps `allow_credentials=False`. Cost: any XSS can read the token (memory-only gives little extra protection, loses reload UX). Mitigation: no HTML rendering, CSP `default-src 'self'` with `connect-src` limited to the API, `frame-ancestors 'none'`, no third-party scripts, short TTL |
| Auth | HS256 via PyJWT with `algorithms=["HS256"]` pinned (constant, not a setting), claims `sub, role, iat, exp, iss`, `exp` required; argon2id via `argon2-cffi` (OWASP minimum cost, to protect the 512 MB instance; timing on free CPU UNVERIFIED); generic `invalid_credentials` 401 plus dummy hash verify for unknown emails (no enumeration); login limited per hashed IP and per email by reusing the quote-agent `RateLimiter`; `Depends(require_role(...))` is a deliberate exception to "routes read `app.state`", confined to auth; ports `PasswordHasher`, `TokenIssuer`, `UserRepository` in `application/` (dataclasses, no pydantic); role claim trusted until expiry (no revocation, documented) | Hexagonal rules intact |
| Seeded users | `python -m eventssound.entrypoints.cli.seed_users --confirm` reuses the catalog seed guard (dry run, remote refusal). Passwords come from `SEED_ADMIN_PASSWORD` and `SEED_CLIENT_PASSWORD` read via injected `environ` in the CLI (same pattern as `ALLOW_REMOTE_SEED`, NOT Settings), min 12 chars; only hashes reach the DB. The developer picks them and lists them in the README (TFM requires test credentials; accounts are synthetic) | No secret in the repo |
| Quote persistence | SAVE AUTOMATICALLY every `status=quote` result, server side, from the route via `record_quote(result, user_id\|None)` (best effort: failure is logged and the chat still answers). Saved: validated `Quote.to_dict()`, validated event fields, optional `user_id` from the bearer token, timestamps. NOT saved: message text, replies, IP, name, email | No public write endpoint to forge (a "save quote" POST would accept client-built JSON); rows are bounded by the chat rate limit and daily cap; admin sees real activity. PII: no contact field because the demo admin credentials are public in the README, so any free-text field would be exposed. Confirmation applies only to the booking request |
| Booking request | `POST /quotes/{id}/booking-request`, client or admin only, owner check, re-runs availability, then inserts pending rows into the flat `bookings` table (shared `booking_code`) | Anonymous creation of blocking rows would let anyone reserve all stock; authenticated plus rate limited is bounded to the demo client |
| Admin API | `GET /admin/quotes`, `/admin/bookings`: `limit` 1..100 (default 20), `offset`, stable order `created_at DESC, id DESC`, body `{items, total, limit, offset}`; 401 `not_authenticated`, 403 `forbidden`; public ids are UUIDs, DB ids never leave `adapters/db` | Offset is fine at demo volume |
| CORS | Origins unchanged, `allow_credentials=False`, add `expose_headers=["Retry-After","X-Request-ID"]` (without it browsers hide `Retry-After` on a cross-origin 429, breaking the Spanish countdown) | Needed by the chat error UX |
| Agent and security impact | No change to tools, prompts or evals. Adds `quote_id` to the chat response and an optional bearer. First write path from a public surface: bounded by existing rate limit and cap | OWASP GenAI: output handling in the UI is the new control |

## Affected areas
| Area | Impact | Description |
| ---- | ------ | ----------- |
| `frontend/` (`src/{app,pages,components,api,copy,styles,auth}`, `package.json`, `eslint.config.js`) | Modified | Replaces the single-screen shell; adds `react-router`, `tailwindcss`, `@tailwindcss/vite`, `msw` (dev) |
| `render.yaml` | Modified | Static-site `headers` (CSP etc.; syntax UNVERIFIED, check Blueprint docs); the SPA rewrite already exists; `JWT_SECRET` as `sync: false` |
| `backend/src/eventssound/{domain,application,adapters,entrypoints}` | New | `user`, `auth`, `quotes`, routes `auth`, `me`, `admin`; `security.py` |
| `backend/src/eventssound/config.py`, `.env.example` | Modified | Settings below (developer hand-edits `.env.example`) |
| `backend/migrations/versions/` | New | One revision `users` + `quotes` + nullable `bookings.quote_id`; number assigned at merge (0002 domain, 0003/0004 agent are planned, so likely 0005); `down_revision` fixed on rebase |
| `backend/pyproject.toml` | Modified | `pyjwt`, `argon2-cffi` (wheels for 3.12 and 3.14 UNVERIFIED) |
| `documentacion/` | Modified | ADRs (UI stack, bearer storage, auto-save, no PII), README credentials, deploy |

New Settings fields, exact lines for `.env.example` (placeholders only):
```
JWT_SECRET=
JWT_ACCESS_TTL_MINUTES=60
LOGIN_RATE_LIMIT_PER_MINUTE=5
```
`jwt_secret: SecretStr | None`; empty, under 32 chars or a placeholder counts as unset. Outside production an unset secret yields a random per-process one (local dev needs no setup). In production, unset means auth routes answer 503 `auth_not_configured` and the app still boots (a crash-loop would take down the live demo; the smoke check asserts login is not 503). The developer MUST set `JWT_SECRET` in the Render dashboard BEFORE merging the auth PR. Seed variables are not Settings fields, so `.env.example` needs nothing else.

## Rollback
All additive. FE: revert the PR (Render rollback) and the old shell returns. BE: unset `JWT_SECRET` to disable auth; revert in reverse order; `alembic downgrade` drops `quotes` and `users` and the `quote_id` column. Persistence failure never blocks the chat. Do not delete tables on Neon production without the developer.

## Success criteria
- [ ] Demo flow works on the deployed URLs from a cold start: warm-up banner, chat to quote breakdown, login as client and admin, admin lists quotes and bookings.
- [ ] Rendered chat text is inert for every injection fixture; rate-limit, budget, kill-switch and 422 errors show Spanish messages (with `Retry-After`).
- [ ] The breakdown total equals `quote.total` and the sum of `quote.lines`.
- [ ] Wrong password, unknown email, expired token, client token on `/admin/*` return the contracted errors; login is rate limited; no secret or hash in logs or responses.
- [ ] CI green (ruff, pytest, eslint, tsc, vitest, build); each PR independently reviewed and verified.

## Review Workload Forecast
Calibrated with the measured ratio (tests 55-60% of each PR; A1 was 649 real lines against 330 estimated). Few large PRs by the agreed process, each about 1,000-1,500 real lines (lockfiles and `openspec/` excluded).

| PR | Side | Branch | Content | Est. lines | Starts |
| -- | ---- | ------ | ------- | ---------- | ------ |
| W1 | FE | `feat/web-shell-static` | Tailwind, tokens, router, layout, copy, `apiFetch`, warm-up banner, about, portfolio, catalog page (msw from the catalog-api spec), CSP headers | 1,200-1,400 | NOW |
| W2 | FE | `feat/web-chat` | Chat reducer and UI, error map, caps, warm-then-send, quote breakdown and proposal view, XSS tests (msw from the chat-endpoint spec) | 1,300-1,500 | NOW |
| W3 | BE | `feat/auth-backend` | Domain/ports/adapters, users migration, login route, `require_role`, Settings, CORS `expose_headers`, login limiter, `seed_users` CLI | 1,200-1,400 | NOW (migration rebased last) |
| W4 | BE | `feat/quote-persistence-admin-api` | `quotes` migration, `record_quote` in the chat route, `quote_id`, `/me/quotes`, `/admin/*`, pagination, booking request | 1,300-1,500 | after Q6, B2, W3 |
| W5 | FE | `feat/web-auth-admin` | Auth context, login page, route guards, my quotes, booking-request action, admin tables with pagination, 401 handling, docs, README credentials, smoke extension | 1,200-1,400 | UI against msw NOW; verify after W4 |

Total about 6,200-7,200 lines in 5 PRs. Guard lines: Decision needed before apply: Yes. Chained PRs recommended: Yes. 400-line budget risk: High (every PR exceeds 400 by design; needs the developer's explicit `size:exception` acceptance for large PRs, per the agreed process).

Dependency map:
```
FE chain: W1 -> W2 -> W5        BE chain: W3 -> W4        (W5 needs W4; W2 final check needs Q6)
Other changes: C (catalog API) -> W1 live data    Q6 (chat endpoint) -> W2 live, W4
               B1/B2 (bookings table, repos) -> W4    Q6 limiter -> W3 (own in-memory copy if Q6 is late)
```
Merge order: W1, W3 (independent, can be reviewed first), then W2 after Q6, W4 after Q6 and W3, W5 last. Do not merge W1/W2 before C/Q6 are deployed unless the broken pages are hidden from the nav (the web auto-deploys on `frontend/**`). Stacked PRs follow the AGENTS.md retarget-before-merge procedure; one writer thread, fresh-context review before each PR.

Workload risk: remaining plans total roughly 3,250 (domain) + 7,800 (agent) + 6,700 (this) = ~17,700 lines in 13 days. This is unrealistic for one reviewer. Cut ladder for this change (ask before each): (1) drop `booking-request`; seed 3 synthetic bookings in `seed_users` so the admin bookings list is not empty (-300 BE, -120 FE); (2) portfolio 6 to 4 events and about page to one section; (3) admin rows without expandable breakdown; (4) a11y lint plugin. NEVER cut: chat, breakdown, safe rendering, login, admin lists.

## Risks
| Risk | Likelihood | Mitigation |
| ---- | ---------- | ---------- |
| Contracts drift (`Quote.to_dict` keys: design says `schema_version`, tasks say `version`; chat extras `availability`, `missing_fields`, `reply_source` unconfirmed) | High | Types come from the golden test and the final specs; runtime guard on `version`; confirm before W2 |
| Auth PR deployed without `JWT_SECRET` | Med | Soft-disable, smoke check, manual step in PR description |
| Migration numbering and merge friction with 3 changes | High | Create the migration last, rebase `down_revision` |
| Argon2 slow or heavy on Render free | Med | Minimum OWASP params, measure in W3 |
| Public demo credentials expose admin data | Med | Synthetic, no PII stored, documented |
| CSP blocks the app (Render header syntax unverified) | Med | Test on a preview deploy; roll back the header alone |
| Review capacity | High | Cut ladder, start FE now against msw |

## Open questions (recommended default in brackets; NOT decided)
1. Branding (logo, colours, typography)? [Owner provides later; neutral palette and text wordmark]
2. Seeded user emails and display names? [Placeholders `admin@eventsounddr.example`, `cliente@eventsounddr.example`; developer to confirm]
3. Does the client role have pages beyond "my quotes" and the booking request? [No]
4. Language of static content (about, portfolio)? [Spanish, synthetic text]
5. Keep the optional booking request or take cut (1)? [Keep until W4 measures over 1,500]
6. Retention of saved quotes? [No purge; synthetic data]
7. Add an optional contact name or email on quotes? [No, for the privacy reason above]
