# Proposal: local-dev-workflow

## Intent

Give the developer one command to run the whole stack locally with hot reload, plus a smoke check reusable against deployed URLs.

## Scope

In:
- `scripts/dev.ps1` (start, `-Down`, `-Reset`, `-Smoke`, `-AllowRemoteDb`), idempotent. Written for Windows PowerShell 5.1 (the only version run); PowerShell 7 is unverified.
- `scripts/smoke.ps1`: health, db health, frontend mount point, CORS (simple, preflight, negative), retries for cold starts.
- `.gitignore` (`.dev/`), compose project pinned to `eventssound-dev`, README section, AGENTS.md commands, ADR 11.

Out:
- Bash equivalent (Windows-first; skipped, can be added later).
- Containerizing the frontend or bind-mounted hot reload.
- CI changes; deployment (separate change).

## Approach

Hybrid: only Postgres in Docker (`docker compose up -d --wait db`); backend and frontend run natively in background processes with logs and PIDs under `.dev/`. Each PID file also stores the process start time, and the command line is checked before the script trusts or kills a PID. Settings come from the process environment or the root `.env`; `.env.example` is copied only when neither exists. Migrations are refused unless the `DATABASE_URL` host is local. The frontend is served on `http://localhost:5173`, the origin allowed by `.env.example`. The full containerized stack remains the production-like check (`--profile app`).

## Risks

- Background processes can be orphaned if the shell is killed; `-Down` kills by recorded PID with children (`taskkill /T`).
- A PID reused by an unrelated process after a reboot is detected (start time and command line mismatch): the file is removed and nothing is killed.
- Callers that pipe the script output may wait for EOF until the children exit (they inherit handles); redirect to a file instead.
- Ports 8000/5173 taken: startup fails naming the port and owner, no auto port selection, nothing killed.
- Renaming the compose project to `eventssound-dev` orphans an older `eventssound_pgdata` volume (dev data only).
- Not verified: the `.env` auto-copy branch, a real root `.env`, PowerShell 7, and Vite HMR in a browser.
