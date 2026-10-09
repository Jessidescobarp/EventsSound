# Decisions

ADR-style log. Each entry: decision, reason. Full reasoning lives in the linked OpenSpec artifacts.

1. **Render for backend (Docker web service) and frontend (static site).** One provider, free tier, simple Blueprint. Fallback: a VM with Docker Compose. See [design.md](../openspec/changes/walking-skeleton-and-deploy/design.md).
2. **Neon Postgres, not Render Postgres.** Free Render Postgres expires after 30 days; Neon free tier supports pgvector.
3. **Spanish UI, English code and docs.** Target users are Spanish speakers; the codebase stays in English.
4. **Vertical-slice phasing.** Ship a thin end-to-end agent early and deploy the skeleton in P0, instead of building layer by layer. See [exploration](../openspec/changes/tfm-phased-mvp/exploration.md).
5. **Chained PRs under 400 lines.** Keeps reviews small. PR 1 was split into 1a and 1b. See [tasks.md](../openspec/changes/walking-skeleton-and-deploy/tasks.md).
6. **OpenSpec as the artifact store.** Artifacts are versioned in git under `openspec/`.
7. **Synthetic data only.** Avoids privacy issues and keeps the demo reproducible.
8. **Liveness vs readiness health.** `/health` never touches the DB (so Render does not restart on a database blip); `/health/db` checks connectivity.
9. **Prices computed by code, not by the LLM.** Makes quotes verifiable by an oracle and limits prompt-injection impact.
10. **Migrations run in the start script.** Free Render instances have no pre-deploy hook (to be verified in PR 4).
