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

- [ ] Wire `load_active_config` into the container; messages and caps come from the config.

## PR 3: admin endpoints

- [ ] GET config, preview, apply, history; confirmation token; password re-auth for technical params; audit.

## PR 4: frontend Agent tab

- [ ] Editing form plus read-only "model in use" card.

## PR 5: double confirmation UI, history, rollback

- [ ] Confirmation dialogs, version history, rollback.

## PR 6 (optional): public welcome message endpoint

- [ ] Unauthenticated read of the welcome message.
