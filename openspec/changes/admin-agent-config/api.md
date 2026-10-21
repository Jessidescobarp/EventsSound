# Admin agent configuration API (PR 3)

All routes are under `/admin`, tag "Agent configuration", admin only (401 no token, 403 client
token). Error bodies are `{detail: <code>, message: <Spanish>}`; 422 `invalid_config` adds
`fields: [<field names>]` and never echoes a value. Responses carry `Cache-Control: no-store`.

## GET /admin/agent-config

```
{ version,                       // 0 = environment defaults, nothing stored
  config: { tone, off_topic_policy, refusal_message, closing_message, welcome_message,
            llm_model, daily_token_cap, daily_cost_cap_micro_usd, chat_rate_limit_per_minute },
  ceilings: { max_daily_tokens, max_daily_cost_micro_usd, max_rate_limit_per_minute },
  allowed_models: [...],
  model_in_use: { provider, model, status: "active"|"disabled"|"replay",
                  input_price_per_mtok, output_price_per_mtok, cost_cap_applies },
  updated_at, updated_by }       // null while version is 0; updated_by is a user id
```

With version 0 the config comes from the environment and may sit outside the ceilings (for
example caps of 0 = unmetered): a form must not preload and resubmit those values blindly.

## POST /admin/agent-config/preview

Body: `{ changes: {<partial config>}, base_version }` or `{ rollback_to_version, base_version }`
(exactly one of `changes` / `rollback_to_version`). Returns

```
{ action: "save"|"rollback", base_version, diff: { <field>: [old, new] },
  warnings: [{ code, severity: "info"|"warning"|"danger", message_es }],
  requires_password,             // true when llm_model, a daily cap or the rate limit changes
  max_daily_cost_estimate_micro_usd,
  confirmation_token, expires_at }
```

Warning codes: `cap_raised`, `cap_raised_2x`, `model_changed`, `rate_limit_raised`,
`texts_changed`, `behavior_changed`, `cost_cap_not_binding`, `immediate_effect`.

Errors: 409 `version_conflict` (`base_version` is not the current one), 422 `invalid_config`,
`no_changes`, `unknown_version` (rollback target not among the last 200 versions), `invalid_request`
(malformed body), 429 `rate_limited` (10 preview+apply per minute per admin, `Retry-After`),
503 `confirmation_unavailable` (no JWT secret: fail closed) or `storage_unavailable`.

## Confirmation token

`base64url(json[user_id, base_version, sha256(canonical {action, diff}), expires_at, nonce])`
`.` `base64url(HMAC-SHA256(key, body))`, with `key = HMAC(JWT_SECRET, "agent-config-confirm")`.
Valid 5 minutes, bound to the user, the base version and the exact change, accepted once. The
used-nonce set is per process (single instance); the repository's `base_version` check is the
cross-instance backstop. Refusal codes: `token_invalid`, `token_expired`, `token_used`,
`token_mismatch`.
