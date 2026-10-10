# Decisions

ADR-style log. Each entry: decision, reason. Full reasoning lives in the linked OpenSpec artifacts.

1. **Render for backend (Docker web service) and frontend (static site).** One provider, free tier, simple Blueprint. Fallback: a VM with Docker Compose. See [design.md](../openspec/changes/walking-skeleton-and-deploy/design.md).
2. **Neon Postgres, not Render Postgres.** As of 2026-10-09 (unverified; verify at deploy time): free Render Postgres expires after 30 days, while the Neon free tier supports pgvector and does not expire.
3. **Spanish UI, English code and docs.** Target users are Spanish speakers; the codebase stays in English.
4. **Vertical-slice phasing.** Ship a thin end-to-end agent early and deploy the skeleton in P0, instead of building layer by layer. See [exploration](../openspec/changes/tfm-phased-mvp/exploration.md).
5. **Chained PRs under 400 lines.** Keeps reviews small. PR 1 was split into 1a and 1b. See [tasks.md](../openspec/changes/walking-skeleton-and-deploy/tasks.md).
6. **OpenSpec as the artifact store.** Artifacts are versioned in git under `openspec/`.
7. **Synthetic data only.** Avoids privacy issues and keeps the demo reproducible.
8. **Liveness vs readiness health.** `/health` never touches the DB (so Render does not restart on a database blip); `/health/db` checks connectivity.
9. **Prices computed by code, not by the LLM.** Makes quotes verifiable by an oracle and limits prompt-injection impact.
10. **Migrations run in the start script.** Free Render instances have no pre-deploy hook (verified 2026-10-10, see [apply-progress-pr4.md](../openspec/changes/walking-skeleton-and-deploy/apply-progress-pr4.md)).
11. **Hybrid local development.** Only Postgres runs in Docker; backend (`uvicorn --reload`) and frontend (Vite) run natively for hot reload, driven by `scripts/dev.ps1`. The containerized stack (`docker compose --profile app up --build`) stays as the production-like check. Tradeoffs: requires uv and Node locally and the scripts are PowerShell-first (Windows target); in exchange, no image rebuilds per edit and no bind-mount file-watching issues on Docker Desktop. See [proposal](../openspec/changes/local-dev-workflow/proposal.md).
