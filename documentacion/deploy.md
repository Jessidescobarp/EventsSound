# Deploy guide

Topology: backend (Docker web service) and frontend (static site) on Render, defined in [`render.yaml`](../render.yaml); database on Neon Postgres. Render Postgres is not used. Verified free-tier facts and sources: [apply-progress-pr4.md](../openspec/changes/walking-skeleton-and-deploy/apply-progress-pr4.md).

## Live URLs

| Component | URL |
| --------- | --- |
| Frontend | `https://eventsounddr-web.onrender.com` (smoke check passed 2026-10-12) |
| Backend | `https://eventsounddr-api.onrender.com` (smoke check passed 2026-10-12) |

Naming: the product and the Render services are `EventSoundDR` / `eventsounddr-*`. The GitHub repository and the internal Python package keep the name `eventssound` (as do the compose project and DB names); only user-visible and deployed names changed.

If Render appends a suffix because a name is taken, update `CORS_ALLOWED_ORIGINS` and `VITE_API_BASE_URL` (in `render.yaml` and the dashboard) to the real URLs and redeploy both services.

## Variables (names only)

| Service | Variable | Where it is set |
| ------- | -------- | --------------- |
| api | `APP_ENV`, `LOG_LEVEL`, `CORS_ALLOWED_ORIGINS` | `render.yaml` (public values) |
| api | `DATABASE_URL` | Render dashboard only (`sync: false`), never in the repo |
| web | `VITE_API_BASE_URL`, `NODE_VERSION` | `render.yaml` (public values; `VITE_*` is baked in at build time) |

`CORS_ALLOWED_ORIGINS` is the web URL with scheme and no trailing slash. `DATABASE_URL` is the Neon DIRECT (non-pooled, no `-pooler` in the host) string with the scheme rewritten to `postgresql+psycopg://` (the backend also rewrites `postgres://` and `postgresql://` itself).

Quote chat (`POST /quote/chat`): `CHAT_ENABLED=false` is the kill switch (redeploy). In `APP_ENV=production` the chat answers 503 `chat_disabled` unless `LLM_PROVIDER=openrouter` with `LLM_MODEL` and `OPENROUTER_API_KEY` set (the replay provider never serves in production). `TRUSTED_PROXY_HOPS` is how many reverse proxies sit in front of the app: the default `0` ignores `X-Forwarded-For` (every client behind a proxy would share the proxy's address and one rate-limit bucket); behind Render set it to `1` (UNVERIFIED: confirm by checking that two different clients get different buckets, since a value too high lets a client choose its own key). Accepted limits of this first version: the rate limiter and the daily budget are in memory and reset on every restart, so the persistent usage cap table (`llm_usage_daily`) is still REQUIRED before a real public launch. The limiter tracks at most 10,000 client keys for up to 1 hour and fails closed (429) when full. The global window (30 requests per minute) can be exhausted by distributed abuse, which disables the chat for everyone until it slides. The request body is capped at 16 KiB (hardcoded). The uvicorn access log prints peer IPs; the chat code itself never logs them.

## Deploy order

1. Merge to `main` with green CI. Services deploy automatically only after CI checks pass (`autoDeployTrigger: checksPass`). If a merge does not deploy, check the service's Events tab and trigger a manual deploy (Render does not deploy when it detects no checks).
2. Create the Blueprint (manual steps below) and set `DATABASE_URL`.
3. The backend runs `alembic upgrade head` in `backend/start.sh` before serving (free instances have no `preDeployCommand`). A failing migration exits the container, so the new version never becomes healthy.
4. Run the smoke check, then open the frontend.

## Public API docs

Swagger UI (`/docs`) and the schema (`/openapi.json`) stay enabled when `APP_ENV=production`: the API is read-only with synthetic data, so they add no sensitive surface. `scripts/smoke.ps1` checks `/docs`. Deploying migration `0002` creates the four catalog and booking tables in Neon, empty; the catalog endpoints return empty lists until the guarded seed CLI is run deliberately (see the README).

## Migration 0004 (daily LLM budget)

Deploying migration `0004` creates the empty `llm_usage_daily` table in Neon automatically (a plain `CREATE TABLE`, no lock on existing data; downgrade drops it). The chat uses it as its persistent daily cap whenever the chat is active with the `openrouter` provider, in any `APP_ENV`.

## Migration 0003 (pgvector)

Deploying `0003` runs `CREATE EXTENSION IF NOT EXISTS vector` and creates the empty `catalog_embeddings` table. The extension was confirmed on a throwaway Neon branch first; a failure there would block the deploy (the start script exits) without corrupting data. Embeddings stay empty (search is keyword-only) until the developer runs `embed_catalog` with `ALLOW_REMOTE_SEED=1` against Neon from their machine. `EMBEDDING_PROVIDER` defaults to `off`, so nothing changes at runtime until a later PR wires the search into the agent.

## Neon branch policy

The production branch is for the deployed app only. Never run tests, experiments or local development against it; use the local Docker Postgres (`docker compose up -d --wait db`) or a separate throwaway Neon branch.

## Cold start

Free web services spin down after 15 minutes without traffic and take about a minute to wake up; Neon also suspends after 5 minutes idle. The first request after idle can be slow. Warm the backend before a demo:

```powershell
scripts/smoke.ps1 -BackendUrl https://eventsounddr-api.onrender.com -FrontendUrl https://eventsounddr-web.onrender.com -Origin https://eventsounddr-web.onrender.com -TimeoutSec 30 -Retries 12 -RetryDelaySec 10
```

`-Origin` must be the exact web URL (the CORS checks compare against it). Exit code 0 means all checks passed. From Git Bash prefix with `powershell -NoProfile -ExecutionPolicy Bypass -File`.

## Rollback

Render dashboard, service, Deploys, "Rollback" on a previous successful deploy. This turns auto-deploy off for that service: re-enable it in Settings after fixing `main`. Alternatively `git revert` the bad commit and let CI and auto-deploy ship it. Database migrations are not rolled back automatically.

## Renaming the Render services (transition)

Render matches Blueprint services by `name`. Inferred, not confirmed by the Render docs: a new name creates NEW services instead of renaming the existing ones, so the old `eventssound-api` and `eventssound-web` keep running until deleted. Recommended sequence:

1. Merge the rename PR and wait for green CI on `main`.
2. In the Render dashboard (workspace `EventsSoundDr`), accept the Blueprint sync. It creates `eventsounddr-api` and `eventsounddr-web`.
3. Paste `DATABASE_URL` (Neon DIRECT string) when prompted. Dashboard only.
4. Wait for both new services to be live, then run the smoke check against the new URLs:

```powershell
scripts/smoke.ps1 -BackendUrl https://eventsounddr-api.onrender.com -FrontendUrl https://eventsounddr-web.onrender.com -Origin https://eventsounddr-web.onrender.com -TimeoutSec 30 -Retries 12 -RetryDelaySec 10
```

5. ONLY after the smoke check passes, delete the old `eventssound-api` and `eventssound-web` services.

If the new `.onrender.com` names get a suffix, update the two URL values in `render.yaml` (`CORS_ALLOWED_ORIGINS` and `VITE_API_BASE_URL`) and redeploy.

## Manual steps for the developer (T4.6-T4.9)

1. Neon: create a free project in the region closest to Render `oregon` (the Render region defaults to `oregon` and cannot be changed after creation; to use another region, set `region:` in `render.yaml` before the first deploy). In Connect, choose the DIRECT connection (pooling off, host without `-pooler`) and copy it. Replace the scheme with `postgresql+psycopg://` and keep `sslmode=require`. Do not paste it in chat, commits or files.
2. After this PR is merged and CI is green on `main`: in Render, workspace `EventsSoundDr`, New, Blueprint, select this repo. Render validates `render.yaml` here; fix any error it reports.
3. When prompted for `DATABASE_URL`, paste the Neon string (dashboard only). If a card is requested for verification, note it.
4. Check that the service URLs match the table above; if not, update both URL variables and redeploy.
5. Wait for the first deploy of both services to be live; check the api logs show `alembic upgrade head` succeeding. If the connection fails with `channel_binding`, remove that parameter from `DATABASE_URL` and redeploy.
6. Run the smoke command above (cold, then again warm) and expect all PASS.
7. Open the web URL in a browser: expect `Servicio operativo` and no CORS errors in the console.
8. In the Neon SQL editor run `select * from alembic_version;` and confirm the baseline revision.
9. Done 2026-10-12: the URLs above are the verified ones. If Render ever appends a suffix to a service name, update `render.yaml` and these tables.
10. Optional: confirm a failing migration blocks release (reason from `start.sh` instead of breaking the live deploy).
