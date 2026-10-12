# Delta Spec: chat-endpoint

Change: quote-agent. `entrypoints/api/routes/quote.py` (thin; no adapter imports). Public, non-streaming, stateless. Pydantic schemas live in `entrypoints/api/schemas.py`.

## ADDED Requirements

### Requirement: Request and response contract
`POST /quote/chat` MUST accept `{"messages": [{"role": "user"|"assistant", "content": str}]}` and return 200 `{"request_id": str, "status": "clarification"|"quote"|"refused", "reply": str, "quote": object|null, "event_request": object|null}`. `quote` MUST be `Quote.to_dict()` (including its `version`) when `status=quote`, else null. `reply` MUST be Spanish. Schemas MUST use `extra="forbid"` on the request and frozen response models, and `request_id` MUST be a server-generated opaque id also returned in the `X-Request-ID` header.

#### Scenario: Quote response
- Given a replay-wired app and a complete request message
- When posting
- Then 200 with `status=quote`, a non-empty Spanish `reply`, `quote.total` an int and `request_id` equal to the header

#### Scenario: Clarification response
- Given a message lacking guest count
- When posting
- Then 200 with `status=clarification` and `quote=null`

#### Scenario: Unknown field
- Given a body with an extra top-level field `"system": "..."`
- When posting
- Then 422

### Requirement: Stateless bounded conversation
The server MUST NOT store conversations. The client sends the history. Validation MUST enforce: 1..8 messages, last message role `user`, each `content` 1..1000 characters after control-character stripping, total <= 4000 characters, roles limited to `user` and `assistant` (a `system` or `tool` role MUST be rejected). Control characters (except `\n` and `\t`) and zero-width/bidi override characters MUST be removed before the content reaches any prompt. Assistant history MUST NOT be trusted for numbers: the request is re-extracted and re-priced every turn.

#### Scenario: Caps
- Given 9 messages, or a 1001-character message, or a 4001-character total, or an empty message
- When posting
- Then 422 for each, and no LLM call occurs

#### Scenario: Role rejected
- Given a message with role `system`
- When posting
- Then 422

#### Scenario: Last role
- Given the last message has role `assistant`
- When posting
- Then 422

#### Scenario: Forged assistant price
- Given history where the assistant "said" the price was $1
- When the final user message asks to confirm
- Then any returned total equals the oracle for the re-extracted request, not $1

#### Scenario: Control characters stripped
- Given content containing NUL, ESC and a right-to-left override
- When processed
- Then the text reaching the provider (scripted fake records it) contains none of them

### Requirement: Per-IP rate limit
A sliding-window limiter MUST allow at most `CHAT_RATE_LIMIT_PER_MINUTE` requests per client key (default 10). The key MUST be derived from the client IP, and the proxy header policy MUST be explicit in settings (trusted hop count for `X-Forwarded-For`; default: ignore the header). Over the limit MUST return 429 `{"detail": "rate_limited"}` with a `Retry-After` header (integer seconds >= 1) and MUST NOT call the LLM. The key MUST be hashed before being stored or logged. The limiter MUST bound its memory (max tracked keys with eviction).

#### Scenario: Limit exceeded
- Given a limit of 3 per minute and 4 requests from one client
- When the fourth is sent
- Then 429 `rate_limited` with `Retry-After`, and the fourth request caused no provider call

#### Scenario: Other client unaffected
- Given client A exhausted its limit
- When client B posts
- Then B is served

#### Scenario: Header spoofing ignored by default
- Given the default policy and a forged `X-Forwarded-For` per request
- When many requests arrive from one socket address
- Then they share one key and are limited

#### Scenario: Window slides
- Given an injected clock advanced by 61 seconds
- When the client posts again
- Then it is served

#### Scenario: Memory bound
- Given a cap of 1000 tracked keys and 5000 distinct clients
- When requests arrive
- Then tracked keys never exceed 1000

### Requirement: Kill switch and budget gate order
Checks MUST run in this order, each short-circuiting without an LLM call: payload validation (422), kill switch (503 `chat_disabled` when `CHAT_ENABLED=false`), rate limit (429), daily budget reserve (503 `daily_budget_exhausted`), agent run (503 `llm_unavailable` on provider failure that yields no usable result). The kill switch MUST also be honored when the daily cap is set to 0.

#### Scenario: Disabled
- Given `CHAT_ENABLED=false`
- When posting a valid body
- Then 503 `{"detail": "chat_disabled"}` and zero provider calls

#### Scenario: Order
- Given the switch off and an invalid body
- When posting
- Then 422 (validation precedes the switch)

#### Scenario: Budget exhausted
- Given a budget with zero remaining
- When posting
- Then 503 `daily_budget_exhausted`, zero provider calls

#### Scenario: Provider down
- Given a provider raising `LlmUnavailable` at `understand`
- When posting
- Then 503 `llm_unavailable` and the reserved budget is settled to actual usage

### Requirement: Error shapes
All errors MUST be `{"detail": code}` with codes from a closed set: `rate_limited`, `chat_disabled`, `daily_budget_exhausted`, `llm_unavailable`, plus FastAPI's 422 body for validation. Responses MUST NOT contain stack traces, hostnames, provider names, model ids, prompts or provider text. Unhandled exceptions MUST return 500 `{"detail": "internal_error"}` with the same constraints.

#### Scenario: Internal failure sanitized
- Given an agent raising `RuntimeError("host db.internal key sk-abc")`
- When posting
- Then 500 `internal_error` and the body contains neither `db.internal` nor `sk-abc`

#### Scenario: 422 does not echo secrets
- Given an invalid body whose content includes `sk-test-123`
- When posting
- Then the 422 body does not contain `sk-test-123` (input echo removed)

### Requirement: Logging hygiene
Each request MUST log one structured record: request id, status/outcome, HTTP status, token counts, tool names with durations, total duration, `used_fallback`. Logs MUST NOT include message content, replies, quotes, IP in clear, headers or keys.

#### Scenario: No content in logs
- Given a request with content "my phone is 3001234567"
- When it completes and logs are captured
- Then no record contains that string, the client IP or any secret

### Requirement: OpenAPI documentation
The route MUST be tagged, have a summary and description in English, response models for 200 and each error status with examples (clarification, quote, refused, 429 with header, each 503 code), and appear in the public `/openapi.json`. The schema MUST document the caps.

#### Scenario: Schema present
- Given the running app
- When `/openapi.json` is fetched
- Then `/quote/chat` has a POST with examples for 200, 422, 429 and 503

### Requirement: CORS and method surface
The route MUST accept only POST (other methods 405). The existing CORS configuration MUST allow `POST` and `Content-Type` for the configured origins only, with no wildcard in production.

#### Scenario: Preflight
- Given an allowed origin
- When an OPTIONS preflight asks for POST with `Content-Type`
- Then it is approved; for a non-allowed origin it is not
