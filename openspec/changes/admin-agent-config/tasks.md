# Tasks: admin-agent-config

## PR 1a: model, validation, fallback (feat/agent-config-model)

- [x] `AgentConfig`, `StoredAgentConfig`, ceilings and `validate_config` in the domain.
- [x] Shared `MODEL_ID_PATTERN` used by the OpenRouter adapter.
- [x] `Settings.llm_model_allowlist` and `allowed_llm_models`.
- [x] `AgentConfigRepository` port, `defaults_from_settings`, `load_active_config`.
- [x] Unit tests: text and ceiling validation, fallback.

## PR 1b: storage (feat/agent-config-storage, stacked on 1a)

- [x] Migration 0010 (`agent_settings`, `agent_settings_audit`) and the SQLAlchemy repository (validates on save, history skips corrupt rows).
- [x] DB tests: migration up/down, save, history, concurrency, atomic audit, note length.

## PR 2: chat, budget and rate limit read the active config

- [x] `ActiveConfigProvider` (TTL cache, invalidate, last-good, defaults on failure).

- [x] Wire it as `app.state.agent_config`; daily token and cost caps read per reserve (Postgres and in-memory budget).
- [x] Chat per-minute rate limit read per hit (limiter state is kept on a change).
- [x] LLM model: the agent is rebuilt once when the active model changes.

- [ ] Refusal and closing texts, `tone` (fixed prompt sentence per value) and `off_topic_policy` (fixed block limit per value): deferred to a follow-up PR (size budget).

## PR 3: admin endpoints

API contract: `api.md`.

### PR 3a: read and preview (feat/agent-config-api-read)

- [x] Confirmation token (HMAC, bound to user, base version and change; 5 minutes; single use).
- [x] GET config with ceilings, allowed models and the read-only model in use.
- [x] POST preview: validation (field names only), diff, risk warnings, `requires_password`, cost estimate, rollback preview; per-admin rate limit.

### PR 3b: apply, history, rollback (feat/agent-config-api-write)

- [x] PUT apply (recomputed diff, token, typed confirmation, password re-auth for technical params); rollback through the same flow (audit action `rollback`).
- [x] GET history from the audit table; rejected attempts recorded as security events (`config_rejected`, `config_reauth_failed`; no migration needed, `kind` is free text).
- [x] `AuthService.verify_password` and `UserRepository.by_id` for the re-auth.

## PR 4: frontend Agent tab

- [ ] Editing form plus read-only "model in use" card.

## PR 5: double confirmation UI, history, rollback

- [ ] Confirmation dialogs, version history, rollback.

## PR 6 (optional): public welcome message endpoint

- [ ] Unauthenticated read of the welcome message.
