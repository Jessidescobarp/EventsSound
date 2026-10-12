# Delta Spec: quote-agent

Change: quote-agent. A `QuoteAgent` port and a `quote_chat` use case in `application/`; the LangGraph implementation lives in `adapters/agent/`. The pipeline is fixed: `understand -> clarify | resolve_items -> availability -> price -> draft -> verify`.

## ADDED Requirements

### Requirement: Framework isolation and fixed pipeline
`QuoteAgent.run(conversation) -> AgentResult` MUST be a port with no LangGraph types. The graph MUST have exactly the nodes above with one conditional edge after `understand` (clarify or proceed). The model MUST NOT choose the next node. If LangGraph is unavailable the same port MAY be implemented by a plain Python pipeline without changing callers.

#### Scenario: Application layer clean
- Given the architecture test
- When it scans `application/` and `domain/`
- Then no `langgraph` or `langchain` import exists

#### Scenario: Fixed topology
- Given the compiled graph
- When its nodes and edges are listed
- Then they match the pipeline with a single conditional branch

### Requirement: Structured extraction with validation
`understand` MUST ask the LLM for JSON matching a schema (`event_type`, `start`, `end`, `guest_count`, `distance_km`, `venue`, `items`/`packages` as free-text requests with quantities, plus `missing_fields`). The output MUST be validated against the schema and then against `EventRequest` bounds. Invalid JSON or schema MUST trigger exactly one repair retry (the retry prompt carries the validation error class, not user text); a second failure MUST yield a `clarification` reply asking the user to restate the request. Dates MUST be resolved to tz-aware values in `America/Bogota`; relative dates ("este sabado") MUST be resolved against an injected clock, never the system clock inside the graph.

#### Scenario: Valid extraction
- Given a replay fixture with a complete wedding request
- When `understand` runs
- Then a validated request object is produced with tz-aware datetimes

#### Scenario: Malformed JSON then repaired
- Given fixtures: first response not JSON, second valid
- When `understand` runs
- Then the request is produced after exactly 2 LLM calls in that node

#### Scenario: Repair fails
- Given two invalid responses
- When `understand` runs
- Then the result status is `clarification` and no tool is called

#### Scenario: Relative date with injected clock
- Given a fixed clock of 2026-10-12 and "el proximo sabado"
- When resolved
- Then the date is 2026-10-17

### Requirement: Clarification within a bounded number of turns
When required fields (`start`, `end`, `guest_count`, `distance_km` or `venue`, at least one item or package) are missing, the agent MUST return `status=clarification` with one Spanish question covering the missing fields (at most 3 fields per question). The conversation MUST be allowed at most 3 consecutive clarification turns (counted from assistant messages in the bounded history); after that the agent MUST return `refused` with a Spanish message asking the user to contact the company, instead of looping. No tool call and no price MUST occur on a clarification turn.

#### Scenario: Missing guests
- Given a request lacking `guest_count`
- When the agent runs
- Then `status=clarification`, the reply asks for the guest count in Spanish, and `quote` is null

#### Scenario: Turn bound
- Given a history with 3 prior clarification replies and still-missing fields
- When the agent runs
- Then `status=refused` with a Spanish message and no further question

### Requirement: Item resolution constrained to retrieved codes
`resolve_items` MUST call `buscar_equipamiento` for each requested free-text item and MUST map to catalog codes only from the returned hits. The LLM, if used to choose among hits, MUST return codes from the hit list only; any other code MUST be discarded. Ambiguous or empty results MUST produce a clarification naming the unresolved item text (truncated), not a guess.

#### Scenario: Invented code discarded
- Given hits `[sound_a, sound_b]` and a model choice `sound_zzz`
- When resolved
- Then `sound_zzz` is dropped and a clarification is requested for that item

#### Scenario: No hits
- Given a requested item with no retrieval hits
- When resolved
- Then the reply is a clarification and no price is computed

### Requirement: Availability then price, deterministic
After resolution the pipeline MUST call `consultar_disponibilidad`; if unavailable, `status=clarification` MUST list the short items (code names from the catalog) and quantities available, with no quote. If available it MUST call `calcular_precio` and keep the resulting `Quote` as the only monetary source. The tool order is fixed and each tool runs at most once per request (retries excluded).

#### Scenario: Shortage stops the pipeline
- Given a shortage on one item
- When the agent runs
- Then no `calcular_precio` call occurs and the reply names the shortage

#### Scenario: Quote total equals oracle
- Given a golden request
- When the agent returns `status=quote`
- Then `quote.total == calculate_price(expected_request).total`

### Requirement: Proposal text generated from the Quote and verified
`draft` MUST ask the LLM for a Spanish proposal text from the validated `Quote` (lines as data, amounts as integer pesos) and the request summary. `verify` MUST then check, deterministically: (1) every monetary amount in the text, parsed from common Spanish formats (`$539.000`, `539000`, `539.000 COP`, `$ 539,000`), belongs to the set of amounts in the Quote (line amounts, subtotal, total) ; (2) every item name or code mentioned is a Quote line label; (3) every date/time mentioned matches the request start or end (date and hour); (4) no URLs, emails, phone numbers or markdown links; (5) length <= a settings cap; (6) the total appears at least once. Any failure MUST replace the text with a deterministic Spanish template rendered from the Quote and request (lines, quantities, dates, total). The fallback MUST also be used when `draft` raises any LLM error. `status` stays `quote` in both cases; the response MUST NOT reveal which path ran except through a boolean `used_fallback` in logs.

#### Scenario: Faithful text passes
- Given a draft whose amounts, items and dates all appear in the Quote
- When verified
- Then the LLM text is returned

#### Scenario: Altered amount
- Given a draft stating "$450.000" while the total is 539000 and no line equals 450000
- When verified
- Then the template text is returned and contains "539.000"

#### Scenario: Invented item
- Given a draft mentioning "pantalla LED gigante" absent from the Quote
- When verified
- Then the template is used

#### Scenario: Wrong date
- Given a draft that places the event on a different date than the request
- When verified
- Then the template is used

#### Scenario: Link injected
- Given a draft containing "https://evil.example"
- When verified
- Then the template is used

#### Scenario: Draft LLM error
- Given the LLM raising `LlmTimeout` in `draft`
- When the pipeline runs
- Then a `quote` response with template text is returned

### Requirement: The LLM never produces prices
No prompt MUST instruct the LLM to compute or estimate prices; prompts for `understand` and `resolve_items` MUST NOT include prices; `draft` receives prices only as read-only data from the Quote. `AgentResult.quote` MUST be produced only by `calcular_precio`.

#### Scenario: Price in extraction ignored
- Given an extraction fixture that includes a `price` or `total` field
- When validated
- Then validation fails (extra fields forbidden) and the repair path runs

### Requirement: Bounds on steps, calls and time
A request MUST make at most 3 LLM calls in the happy path (understand, optional item choice, draft) plus at most 1 repair retry, and at most 1 call each to `consultar_disponibilidad` and `calcular_precio`. The graph MUST have a recursion/step limit and an overall wall-clock deadline from settings; each LLM call MUST receive the remaining time as its timeout. Exceeding the deadline MUST end the run with `llm_unavailable` (no partial quote text without a verified Quote; if a Quote already exists, the template quote MAY be returned).

#### Scenario: Call cap
- Given a scripted provider that would accept more calls
- When a request is processed
- Then the recorded calls never exceed the cap

#### Scenario: Deadline
- Given a provider that sleeps beyond the deadline
- When the agent runs
- Then the run ends within the deadline plus a small margin with `llm_unavailable`

### Requirement: quote_chat use case
`quote_chat(messages, agent, budget, clock)` MUST validate the conversation (last message from the user), reserve budget, run the agent, settle actual usage and return `{status in {clarification, quote, refused}, reply, quote, event_request}`. It MUST contain the persistence hook point as a pure function boundary but MUST NOT persist quotes or conversations in this change.

#### Scenario: Last message must be user
- Given messages ending with an assistant message
- When the use case runs
- Then a validation error is raised before any LLM call

#### Scenario: No persistence
- Given a completed quote
- When the use case returns
- Then no repository write occurred (fake repositories record zero writes)

### Requirement: Out-of-domain and unsafe requests
Messages unrelated to quoting sound/lights/DJ events, or attempting to change the assistant's role, MUST yield `status=refused` with a short Spanish reply and no tool call.

#### Scenario: Off-topic
- Given "dame una receta de arepas"
- When the agent runs
- Then `status=refused` and no tool was called
