# Deploy guide

Topology: backend (Docker web service) and frontend (static site) on Render, defined in [`render.yaml`](../render.yaml); database on Neon Postgres. Render Postgres is not used. Verified free-tier facts and sources: [apply-progress-pr4.md](../openspec/changes/walking-skeleton-and-deploy/apply-progress-pr4.md).

## Live URLs

| Component | URL |
| --------- | --- |
| Frontend | `https://eventssound-web.onrender.com` (placeholder until verified) |
| Backend | `https://eventssound-api.onrender.com` (placeholder until verified) |

If Render appends a suffix because a name is taken, update `CORS_ALLOWED_ORIGINS` and `VITE_API_BASE_URL` (in `render.yaml` and the dashboard) to the real URLs and redeploy both services.

## Variables (names only)

| Service | Variable | Where it is set |
| ------- | -------- | --------------- |
| api | `APP_ENV`, `LOG_LEVEL`, `CORS_ALLOWED_ORIGINS` | `render.yaml` (public values) |
| api | `DATABASE_URL` | Render dashboard only (`sync: false`), never in the repo |
| web | `VITE_API_BASE_URL`, `NODE_VERSION` | `render.yaml` (public values; `VITE_*` is baked in at build time) |

`CORS_ALLOWED_ORIGINS` is the web URL with scheme and no trailing slash. `DATABASE_URL` is the Neon DIRECT (non-pooled, no `-pooler` in the host) string with the scheme rewritten to `postgresql+psycopg://` (the backend also rewrites `postgres://` and `postgresql://` itself).

## Deploy order

1. Merge to `main` with green CI. Services deploy automatically only after CI checks pass (`autoDeployTrigger: checksPass`). If a merge does not deploy, check the service's Events tab and trigger a manual deploy (Render does not deploy when it detects no checks).
2. Create the Blueprint (manual steps below) and set `DATABASE_URL`.
3. The backend runs `alembic upgrade head` in `backend/start.sh` before serving (free instances have no `preDeployCommand`). A failing migration exits the container, so the new version never becomes healthy.
4. Run the smoke check, then open the frontend.

## Neon branch policy

The production branch is for the deployed app only. Never run tests, experiments or local development against it; use the local Docker Postgres (`docker compose up -d --wait db`) or a separate throwaway Neon branch.

## Cold start

Free web services spin down after 15 minutes without traffic and take about a minute to wake up; Neon also suspends after 5 minutes idle. The first request after idle can be slow. Warm the backend before a demo:

```powershell
scripts/smoke.ps1 -BackendUrl https://eventssound-api.onrender.com -FrontendUrl https://eventssound-web.onrender.com -Origin https://eventssound-web.onrender.com -TimeoutSec 30 -Retries 12 -RetryDelaySec 10
```

`-Origin` must be the exact web URL (the CORS checks compare against it). Exit code 0 means all checks passed. From Git Bash prefix with `powershell -NoProfile -ExecutionPolicy Bypass -File`.

## Rollback

Render dashboard, service, Deploys, "Rollback" on a previous successful deploy. This turns auto-deploy off for that service: re-enable it in Settings after fixing `main`. Alternatively `git revert` the bad commit and let CI and auto-deploy ship it. Database migrations are not rolled back automatically.

## Manual steps for the developer (T4.6-T4.9)

1. Neon: create a free project in the region closest to Render `oregon` (the Render region defaults to `oregon` and cannot be changed after creation; to use another region, set `region:` in `render.yaml` before the first deploy). In Connect, choose the DIRECT connection (pooling off, host without `-pooler`) and copy it. Replace the scheme with `postgresql+psycopg://` and keep `sslmode=require`. Do not paste it in chat, commits or files.
2. After this PR is merged and CI is green on `main`: in Render, workspace `EventsSoundDr`, New, Blueprint, select this repo. Render validates `render.yaml` here; fix any error it reports.
3. When prompted for `DATABASE_URL`, paste the Neon string (dashboard only). If a card is requested for verification, note it.
4. Check that the service URLs match the table above; if not, update both URL variables and redeploy.
5. Wait for the first deploy of both services to be live; check the api logs show `alembic upgrade head` succeeding. If the connection fails with `channel_binding`, remove that parameter from `DATABASE_URL` and redeploy.
6. Run the smoke command above (cold, then again warm) and expect all PASS.
7. Open the web URL in a browser: expect `Servicio operativo` and no CORS errors in the console.
8. In the Neon SQL editor run `select * from alembic_version;` and confirm the baseline revision.
9. Replace the placeholder URLs in this file and in the README with the verified ones (`docs: add live urls`).
10. Optional: confirm a failing migration blocks release (reason from `start.sh` instead of breaking the live deploy).
