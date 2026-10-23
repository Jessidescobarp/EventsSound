# Roadmap

MVP target: **2026-10-25**. Plan source: [exploration](../openspec/changes/tfm-phased-mvp/exploration.md).

| Phase | Scope | Calendar | Status (2026-10-22) |
| ----- | ----- | -------- | ------------------- |
| P0 | Walking skeleton: monorepo, hexagonal folders, `/health`, Alembic baseline, CI, Compose, first deploy | Oct 9-11 | Done, deployed |
| P1 | Domain core: synthetic catalog, `calcular_precio`, availability, repositories | Oct 12-14 | Done |
| P2 | Agent core: `LlmProvider` port, hybrid equipment search (keyword + pgvector), LangGraph quote agent, `/quote/chat` | Oct 15-19 | Done, deployed |
| P3 | Evals and hardening: golden set (15 requests, 8 injection cases), price oracle, injection guard, rate limit, daily budget, security events | Oct 20-21 | Done |
| P4 | UI: chat page, static pages, JWT login, admin area (quotes, bookings, catalog, portfolio, security, agent configuration) | Oct 22-23 | Done |
| P5 | Production deploy, README, demo guide, public repo, slides, video | Oct 24-25 | README and demo guide done; slides and video are deliverables outside the repo |

Beyond the original plan, an admin "Agent configuration" tab was added ([admin-agent-config](../openspec/changes/admin-agent-config/proposal.md)), together with a per-model price table. Open items and limitations: see "Known limitations and future work" in the [README](../README.md).

P0 is tracked in [tasks.md](../openspec/changes/walking-skeleton-and-deploy/tasks.md) as PR 1a, 1b, 2, 3 and 4.

## Scope

The AI quote agent, database persistence, RAG with embeddings and the full frontend (chat page, proposal view, static pages, login and admin quotes list) are all in scope. The earlier fallback that dropped auth and the admin page was withdrawn (2026-10-12). If the schedule slips, the levers are the number of catalog and pricing refinements and the size of the P3 golden set, not the P4 scope.
