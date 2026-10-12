# Roadmap

MVP target: **2026-10-25**. Plan source: [exploration](../openspec/changes/tfm-phased-mvp/exploration.md).

| Phase | Scope | Calendar |
| ----- | ----- | -------- |
| P0 | Walking skeleton: monorepo, hexagonal folders, `/health`, Alembic baseline, CI, Compose, first deploy | Oct 9-11 |
| P1 | Domain core: synthetic catalog, `calcular_precio`, `consultar_disponibilidad`, repositories | Oct 12-14 |
| P2 | Agent core: `LlmProvider` port, equipment search, LangGraph quote agent, `/quote/chat` | Oct 15-19 |
| P3 | Evals and hardening: golden set, price oracle, injection guard, rate limit, cost cap | Oct 20-21 |
| P4 | UI: chat page, proposal view, static pages, minimal JWT login and admin list | Oct 22-23 |
| P5 | Production deploy, README, public repo, slides, video | Oct 24-25 |

P0 is tracked in [tasks.md](../openspec/changes/walking-skeleton-and-deploy/tasks.md) as PR 1a, 1b, 2, 3 and 4.

## Scope

The AI quote agent, database persistence, RAG with embeddings and the full frontend (chat page, proposal view, static pages, login and admin quotes list) are all in scope. The earlier fallback that dropped auth and the admin page was withdrawn (2026-10-12). If the schedule slips, the levers are the number of catalog and pricing refinements and the size of the P3 golden set, not the P4 scope.
