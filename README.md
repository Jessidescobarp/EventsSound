# EventSoundDR

Web app for a sound, lighting and DJ events company. Its core is an AI quote assistant; the project is the final work (TFM) of a master's in AI-assisted development. All data is synthetic.

## Project status (what exists today)

| Area | Status |
|---|---|
| Health checks (`/health`, `/health/db`) | Working, deployed |
| Catalog and packages API (`GET /catalog/items`, `/catalog/packages`) with public Swagger at `/docs` | Working, deployed. The deployed database has the tables but is empty until the guarded seed is run on purpose |
| Persistence (Postgres tables `equipment_items`, `service_packages`, `package_items`, `bookings`, `catalog_embeddings`, `llm_usage_daily`, `users`, `quotes`, `portfolio_events`; migrations 0001-0008; the catalog also has `staff` services: DJ, MC, sound technician, priced per event day) | Working, deployed |
| Pure domain: money, pricing oracle (`calculate_price`), availability | Working, covered by tests |
| RAG: hybrid search over the catalog (keyword + pgvector, fused with reciprocal rank fusion; `bge-m3` embeddings, 1024 dimensions, via OpenRouter) | Working, deployed. Admin edits re-embed the changed entries |
| Quote agent (LangGraph pipeline; the LLM only extracts the request and writes the Spanish proposal text, which is verified against the quote computed by `calculate_price`) | Working, deployed. Model `mistralai/mistral-small-3.2-24b-instruct` (see "Choosing the LLM model") |
| Quote chat endpoint (`POST /quote/chat`) with per-IP rate limit, persistent daily budget (Postgres `llm_usage_daily`) and kill switch | Working, deployed. Refuses off-topic requests (for example, asking for code) with a fixed text and no model call |
| Offline evaluation (15 golden requests, 8 injection cases) | Working, runs in CI |
| Authentication (JWT, argon2id, roles `client` and `admin`) | Working, deployed; two synthetic demo accounts (see "Demo accounts") |
| Saved quotes (`status=quote` answers, no personal data) | Working; own quotes at `GET /me/quotes`, all quotes for admins |
| Frontend: home, about, portfolio, services, quote chat, login | Working. Portfolio and catalog come from the API; if it is unreachable the pages show a graceful message. A demo-data mode exists for local use only (`scripts/dev.ps1 -Mocks`) |
| Admin area (`/admin`): saved quotes, bookings, catalog edits (equipment, staff services, packages), portfolio edits | Working, deployed |
| Admin users CRUD, editing a saved quote | Not built; see "Future work" |
| Bookings (creating reservations from the UI) | Not built; the `bookings` table only feeds availability |
| Payments, WhatsApp, voice | Out of scope |

Deployment: Render (API and static site) with Neon Postgres, see `documentacion/deploy.md`. Plans and status: `documentacion/roadmap.md`, `documentacion/requirements.md`, `documentacion/architecture.md`.

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
scripts/dev.ps1 -Mocks    # start with demo data (VITE_USE_MOCKS=true): fake catalog API and a "Datos de demostración" banner; run -Down first if already running
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

## API docs

The backend serves Swagger UI at `/docs` and the OpenAPI schema at `/openapi.json`, in every environment including production (on the live API once this version is deployed). It is public on purpose: the API is read-only and its data is synthetic. ReDoc is off. Catalog endpoints: `GET /catalog/items` and `GET /catalog/packages`.

Load the synthetic catalog into a LOCAL database (a dry run without `--confirm` exits 2 and changes nothing):

```bash
cd backend && uv run python -m eventssound.entrypoints.cli.seed_catalog --confirm
```

The CLI refuses non-local hosts and `APP_ENV=production` unless the environment variable `ALLOW_REMOTE_SEED` is exactly `1`. That variable is a one-off operator override of the CLI, not application configuration: never put it in `.env.example` or a deploy. On remote targets only the catalog is seeded, never the demo bookings.

### Demo accounts (login)

`POST /auth/login` needs `JWT_SECRET` (32+ random characters; in production set it in the Render dashboard, otherwise the auth routes answer 503 `auth_not_configured` and the rest of the app keeps working). Create the two synthetic accounts with passwords you choose (12+ characters), kept out of the repo:

```
SEED_ADMIN_PASSWORD=... SEED_CLIENT_PASSWORD=... uv run python -m eventssound.entrypoints.cli.seed_users --confirm
```

Accounts: `admin@eventsounddr.example` (admin) and `cliente@eventsounddr.example` (client). Passwords for the evaluators: see the delivery document (they protect synthetic accounts only and are not stored in the repo). The CLI has the same guard as the catalog seed (dry run without `--confirm`, remote or production targets need `ALLOW_REMOTE_SEED=1`) and stores only argon2id hashes.

### Saved quotes and admin lists

Every `status=quote` answer of `POST /quote/chat` is saved by the server (validated quote and event fields only: no message text, reply, address, name or email) and the response carries its `quote_id` (null if saving failed; the chat never fails because of it). With a bearer token the quote belongs to that user. Reads, all newest first with `limit` (1 to 100, default 20) and `offset`, answering `{items, total, limit, offset}`: `GET /me/quotes` (any logged-in user, own quotes), `GET /admin/quotes` and `GET /admin/bookings` (admin only: 401 `not_authenticated`, 403 `forbidden`).

### Catalog edits (admin)

An admin can create and edit equipment, staff services and packages: `POST /admin/catalog/items`, `PUT /admin/catalog/items/{code}`, `POST /admin/catalog/packages`, `PUT /admin/catalog/packages/{code}` (401/403 as above, 409 `code_taken`, 404 `not_found`, 422 `invalid_catalog_entry` or `unknown_item`, 503 `storage_unavailable`). A code never changes after creation, and nothing is deleted (bookings and packages point at items): stock 0 stops offering an item. Prices stay deterministic: a changed price only affects quotes made afterwards, since saved quotes keep their own breakdown. After each write the server re-embeds the entries whose name, category or members changed and rebuilds the agent's search index, so the quote agent sees the edit on its next request without a restart (best effort: if embeddings fail, keyword search still works).

### Portfolio (public page and admin edits)

The portfolio page reads `GET /portfolio` (public, visible events only, oldest first). Migration `0008` creates `portfolio_events` and seeds the six illustrative events the site used to show as fixed text. An admin lists everything with `GET /admin/portfolio` and creates or edits with `POST /admin/portfolio` and `PUT /admin/portfolio/{id}` (title, kind, description, up to 12 equipment names, `visible`). Nothing is deleted: `visible: false` hides an event. Pictures are illustrative placeholders; uploading images is out of scope.

## Vector search (embeddings)

Equipment search is keyword-only until embeddings are configured. Migration `0003` creates the `catalog_embeddings` table and runs `CREATE EXTENSION IF NOT EXISTS vector` (pgvector ships in the local `pgvector/pgvector:pg16` image and on Neon). To index the catalog into a LOCAL database for experiments (the `fake` provider is a deterministic hashing stand-in; a dry run without `--confirm` exits 2 and changes nothing):

```bash
cd backend
EMBEDDING_PROVIDER=fake uv run python -m eventssound.entrypoints.cli.embed_catalog --confirm
```

The CLI uses the same guard as the seed CLI (non-local or production targets need `ALLOW_REMOTE_SEED=1`) and never writes `fake` embeddings to a remote database. With `EMBEDDING_PROVIDER=openrouter` it needs `EMBEDDING_MODEL` and `OPENROUTER_API_KEY` in your shell; it deletes rows of any other embedding model (one active model), so use the model the deployed app uses; rerunning is idempotent and only re-embeds entries whose name, category or members changed.

## Choosing the LLM model

CI measures the agent offline: `backend/tests/unit/test_agent_evals.py` runs 15 golden Spanish requests and 8 injection cases (`adapters/evals/golden.py`) through the real pipeline with a scripted provider, and compares every quote with `calculate_price` of the expected request (never with anything a model said). To compare real models, run the live trial yourself; it spends YOUR OpenRouter quota and is never run by CI or the app.

```powershell
$secure = Read-Host "OpenRouter API key" -AsSecureString
$env:OPENROUTER_API_KEY = [System.Net.NetworkCredential]::new("", $secure).Password
cd backend
uv run python -m eventssound.entrypoints.cli.model_trial --model <openrouter-model-id> --count 10            # plan only, exit 2
uv run python -m eventssound.entrypoints.cli.model_trial --model <openrouter-model-id> --count 10 --confirm  # sends requests
Remove-Item Env:OPENROUTER_API_KEY
```

Never paste the key in a chat or a file. `LLM_MODEL` is not needed (the model comes from `--model`), neither is a database. The trial paces requests at 20 per minute, never retries, and stops at the first HTTP 429 (exit 4). `--count` is 1 to 30 (default 10; the set has 15 cases). `APP_ENV=production` is refused. Reading the table: `structured output valid` = the model returned parseable, schema-valid JSON; `extraction accuracy` = request fields (type, dates, guests, km, venue, items, packages) equal to the expected ones; `oracle match` = the quote equals the deterministic price of the expected request; `clarification correct` = it asked for the right missing fields or refused when it should. Prefer the cheapest model with 100% structured output and oracle match; the first 3 failures show the case id, field, expected and got. The same report (case ids only, no prompts, no keys) is saved to `.dev/model-trial-<model>-<timestamp>.json`.

Free OpenRouter models are reported to allow 20 requests/minute and 50 requests/day (1,000/day after buying 10 USD of credit). UNVERIFIED on the official page: check it before relying on it. A 10-case trial uses about 20 to 30 requests.

## Security

- The LLM never computes prices: `calculate_price` is the oracle, and the proposal text is rejected if it does not match the computed quote.
- The chat is scoped to quoting events: off-topic requests (including requests for code) get a fixed refusal before any model call. Injection cases are part of the offline evaluation.
- Cost controls: per-IP rate limit, global window, persistent daily budget, 16 KiB body cap and a kill switch (`CHAT_ENABLED=false`).
- Auth: argon2id hashes, HS256 JWT with expiry, role checks on every `/admin/*` route, login rate limit. Secrets live only in the Render dashboard.
- Review process: changes to pricing, availability, LLM adapters, secrets, the seed guard, auth, the chat endpoint, migrations and admin write endpoints get an independent read-only audit by the `eventsound-security-auditor` agent (`.claude/agents/`) before merging. Accepted low-severity findings are listed in the PR discussions.
- Abuse detection: the API records security events (`chat_refused` for off-topic or injection attempts, `chat_rate_limited`, `login_failed`, `chat_blocked`) in `security_events`. A client with 5 refusals in 10 minutes gets `429 temporarily_blocked` (`Retry-After: 600`) before any model call or budget use; the block ends by itself as the window slides. Clients are stored as a salted hash of the address (never the address, email, password or message text). If the event table is unavailable the check fails open: the rate limiter and the daily budget stay the hard caps. Admins read the events and 24-hour counts per kind at `GET /admin/security` (`limit`, `offset`).
- Known limits: admin writes are last-writer-wins and have no rate limit; the catalog hook that rebuilds the search index runs inside the request.

## Future work

- Users CRUD in the admin area (create, edit, deactivate).
- Editing a saved quote. The design: every edit goes through `calculate_price` again and the server stores the recomputed breakdown; hand-written totals are never accepted.
- Booking requests from the quote screen.
- Image uploads for the portfolio.

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

Backend (Docker) and frontend (static site) on Render via `render.yaml`; Postgres on Neon. Live URLs (smoke check passed 2026-10-12): frontend `https://eventsounddr-web.onrender.com`, backend `https://eventsounddr-api.onrender.com`. Variables set only in the Render dashboard: `DATABASE_URL`, `JWT_SECRET`, `OPENROUTER_API_KEY` (plus `LLM_PROVIDER`, `LLM_MODEL`, `EMBEDDING_PROVIDER`, `EMBEDDING_MODEL`). Migrations run on every start. Free instances sleep after 15 minutes idle and need about a minute to wake up. Deploy order, rollback and the manual setup steps are in [documentacion/deploy.md](documentacion/deploy.md).

## CI

GitHub Actions (`.github/workflows/ci.yml`) runs a `backend` job (ruff, migrations, pytest with coverage, Docker build) and a `frontend` job (lint, tests, build). Protect `main` by requiring both checks and pull requests.
