# Proposal: admin-agent-config

## Intent

Let an admin tune the quote agent without a deploy: behavior and text (tone, off-topic policy, refusal, closing and welcome messages) and technical parameters (model, daily token and cost caps, chat rate limit), always inside hard ceilings set in code. Provider and API keys are never part of it.

## Scope

In:
- A versioned configuration store with an audit trail and optimistic concurrency.
- Strict validation: text 1..400 chars without markup, links, e-mail or phone; closed enums; numeric values within hard ceilings; model from an allowlist.
- Fallback to today's behavior (Settings plus static Spanish messages) when nothing is stored or the stored data is unusable.
- Admin API, admin UI, double confirmation, history and rollback (later PRs).

Out: changing provider or keys, per-user configs, editing prompts or pricing rules.

## Decisions

- Admin edits BOTH behavior/text and technical params, bounded by ceilings: `HARD_MAX_DAILY_TOKENS` = 1,000,000 and `HARD_MAX_DAILY_COST_MICRO_USD` = 10,000,000 (10x the Settings defaults), `HARD_MAX_RATE_LIMIT_PER_MINUTE` = 60.
- Model allowlist comes from the optional `LLM_MODEL_ALLOWLIST` (comma-separated); empty means only `LLM_MODEL`.
- The model-id pattern has one definition in the domain; the OpenRouter adapter imports it.
- Loading never raises: any failure logs the error class and serves the defaults.
- Technical params need password re-auth; every change needs a confirmation token (PR 3 onward).

## Delivery (chained PRs, each under 400 changed lines)

1. Store, domain model, validation, repository, fallback (migration 0010).
2. Chat, budget and rate limit read the active config.
3. Admin endpoints: GET config, preview, apply, history; confirmation token, re-auth, audit.
4. Frontend Agent tab with a read-only "model in use" card.
5. Double-confirmation UI, history, rollback.
6. Optional public welcome message endpoint.

## Risks

- A bad config degrades the chat: mitigated by validation, ceilings, fallback and rollback.
- Migration 0010 is on the critical path: reversible and tested up/down.
