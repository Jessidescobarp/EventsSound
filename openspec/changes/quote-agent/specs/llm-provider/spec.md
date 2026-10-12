# Delta Spec: llm-provider

Change: quote-agent. Port in `application/` (dataclasses only, no pydantic, no httpx), adapters in `adapters/llm/`. Tests never touch the network.

## ADDED Requirements

### Requirement: LlmProvider port and typed DTOs
`application/` MUST define an `LlmProvider` Protocol with one method `complete(request: LlmRequest) -> LlmResponse`. `LlmRequest` MUST carry `node` (str), `scenario` (str | None), `messages` (tuple of `LlmMessage(role in {system, user, assistant}, content)`), `response_format` (`text` | `json`), `max_output_tokens`, `timeout_s`. `LlmResponse` MUST carry `text`, `parsed` (dict | None, set only when JSON was requested and parsed), `usage: TokenUsage(prompt_tokens, completion_tokens)` and `model` (str). All DTOs MUST be frozen dataclasses with validated bounds (non-empty messages, `max_output_tokens` 1..4096, `timeout_s` > 0). The port MUST NOT expose tool-calling to the model: tool use is orchestrated by the graph (see `agent-tools`).

#### Scenario: Invalid request rejected
- Given an `LlmRequest` with no messages or `max_output_tokens` 0
- When it is constructed
- Then a validation error is raised and no provider is called

#### Scenario: Application layer stays framework-free
- Given the architecture test
- When it scans `application/`
- Then it finds no import of pydantic, httpx, langgraph or langchain

### Requirement: Typed error taxonomy
Providers MUST raise only: `LlmTimeout`, `LlmRateLimited` (optional `retry_after_s`), `LlmUnavailable`, `LlmBadResponse`, `LlmAuthError`. Messages MUST be generic and MUST NOT embed the provider body, URL, headers or key.

#### Scenario: Errors carry no provider text
- Given a provider failure whose upstream body contains the string `SECRET-BODY`
- When the adapter raises
- Then `str(exc)` and `repr(exc)` do not contain `SECRET-BODY`

### Requirement: Replay adapter keyed by scenario and node
`ReplayProvider` MUST resolve a response by `(request.scenario, request.node)` from hand-authored fixtures, NOT by hashing the prompt. Changing prompt wording MUST NOT change the lookup. A missing key MUST raise `ReplayMissing` naming scenario and node (no prompt text). Fixtures MAY define a sequence per key, consumed in order, to cover repair retries. Fixtures MUST include `usage` and `model`. A fixture marked `error` MUST raise the matching typed error.

#### Scenario: Prompt edit does not break replay
- Given a fixture for scenario `boda_simple`, node `understand`
- When the system prompt text changes and the provider is called with the same scenario and node
- Then the same fixture is returned

#### Scenario: Missing fixture
- Given no fixture for scenario `x`, node `draft`
- When the provider is called
- Then `ReplayMissing` is raised naming `x` and `draft`

#### Scenario: Sequenced fixtures
- Given two ordered fixtures for the same key
- When the provider is called three times
- Then the first two calls return them in order and the third raises `ReplayMissing`

### Requirement: Scripted fake
A `ScriptedProvider` test double MUST return queued responses or raise queued errors in call order and MUST record every `LlmRequest` it receives for assertions.

#### Scenario: Calls recorded
- Given a scripted provider with one queued response
- When called once
- Then `provider.calls` holds exactly that request

### Requirement: OpenRouter adapter
`OpenRouterProvider` MUST call the OpenAI-compatible `/chat/completions` endpoint through `httpx` (no LangChain or vendor SDK), with the API key sent only in the `Authorization` header, an explicit connect and total timeout taken from `request.timeout_s` (capped by a settings maximum), and no automatic redirects. The base URL and model MUST come from `Settings`. For `response_format=json` it MUST request JSON output and parse it into `parsed`; non-JSON content MUST raise `LlmBadResponse`.

#### Scenario: Success maps to LlmResponse
- Given an `httpx.MockTransport` returning a valid completion with usage
- When `complete` is called
- Then `text`, `usage` and `model` match the payload

#### Scenario: Error mapping
- Given mock responses 401, 429 (with `Retry-After: 7`), 500, 503, a timeout, a connection error, malformed JSON and an empty `choices`
- When `complete` is called for each
- Then they raise respectively `LlmAuthError`, `LlmRateLimited(retry_after_s=7)`, `LlmUnavailable`, `LlmUnavailable`, `LlmTimeout`, `LlmUnavailable`, `LlmBadResponse`, `LlmBadResponse`

#### Scenario: Key placement
- Given a configured key `sk-test-123`
- When a request is made through the mock transport
- Then the key appears only in the `Authorization` header, never in the URL or body

#### Scenario: Bounded response
- Given a mock response larger than the configured byte cap
- When `complete` is called
- Then `LlmBadResponse` is raised without reading the whole body

### Requirement: Token usage and cost accounting
A pure function `cost_micro_usd(usage, model, price_table)` MUST compute cost in integer micro-USD from a price table in settings/config. Unknown models MUST cost 0 but still count tokens. Free models cost 0. Missing `usage` in a provider response MUST be estimated conservatively from character counts (never 0 tokens).

#### Scenario: Priced model
- Given a price of 1,000,000 micro-USD per million prompt tokens and usage of 2,000 prompt tokens
- When cost is computed
- Then the cost is 2,000 micro-USD

#### Scenario: Free model counts toward the token cap
- Given a `:free` model with usage 500/100
- When accounted
- Then cost is 0 and tokens counted are 600

#### Scenario: Missing usage
- Given a provider response without `usage`
- When the adapter builds `TokenUsage`
- Then tokens are a positive estimate derived from text length

### Requirement: Provider selection and no live calls in CI
`build_llm_provider(settings)` in `container.py` MUST return `ReplayProvider` for `LLM_PROVIDER=replay` and `OpenRouterProvider` for `LLM_PROVIDER=openrouter`; `openrouter` without a key MUST fail fast at startup with a message that does not contain secrets. The default test run MUST NOT open network sockets: the suite MUST fail if a test attempts a real outbound connection (socket guard fixture).

#### Scenario: Unknown or incomplete configuration
- Given `LLM_PROVIDER=openrouter` and no key
- When the container is built
- Then startup fails with a configuration error that does not include any key material

#### Scenario: Socket guard
- Given the default test run
- When any test tries to connect to a non-loopback host
- Then the test fails with a clear "network disabled" error

### Requirement: The key is never logged
`OPENROUTER_API_KEY` MUST be a `SecretStr` in `Settings`, unwrapped only inside the adapter. The adapter and its logs MUST NOT emit the key, request bodies or response bodies; logs MUST contain only node, model, status class, duration and token counts.

#### Scenario: Log hygiene
- Given log capture at DEBUG and a call that fails with a 500 containing the key in its body
- When the adapter handles the failure
- Then no captured record contains the key or the body

#### Scenario: Settings repr
- Given `Settings(openrouter_api_key="sk-test-123")`
- When `repr(settings)` is rendered
- Then it does not contain `sk-test-123`
