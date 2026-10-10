# Proposal: local-dev-workflow

## Intent

Give the developer one command to run the whole stack locally with hot reload, plus a smoke check reusable against deployed URLs.

## Scope

In:
- `scripts/dev.ps1` (start, `-Down`, `-Reset`, `-Smoke`), idempotent, PowerShell 5.1/7.
- `scripts/smoke.ps1`: backend `/health` and `/health/db`, frontend mount point, CORS; parametrized base URLs.
- `.gitignore` (`.dev/`), README section, AGENTS.md commands, ADR 11.

Out:
- Bash equivalent (Windows-first; skipped, can be added later).
- Containerizing the frontend or bind-mounted hot reload.
- CI changes; deployment (separate change).

## Approach

Hybrid: only Postgres in Docker (`docker compose up -d --wait db`); backend and frontend run natively in background processes with logs and PIDs under `.dev/`. Settings come from the process environment or the root `.env`; `.env.example` is copied only when neither exists. The full containerized stack remains the production-like check (`--profile app`).

## Risks

- Background processes may be orphaned if the shell is killed: `-Down` kills by recorded PID with children (`taskkill /T`).
- Callers that pipe the script output may wait for EOF until the children exit (they inherit handles); redirect to a file instead.
- A stale PID file after a reboot is harmless: the script checks the process is alive.
- Ports 8000/5173 taken: startup fails with a log tail, no auto port selection.
- The `.env` auto-copy branch is not exercised in automated verification (cannot create `.env` in the agent sandbox).
