# Delta Spec: agent-evals

Change: quote-agent (P3). Evals prove two things separately: replay mode proves pipeline logic and the oracle, deterministic in CI; the optional live run measures model quality. All inputs are synthetic.

## ADDED Requirements

### Requirement: Golden set
There MUST be a versioned golden set of 15 to 20 synthetic Spanish requests (data file under `backend/tests/evals/`), each with: `id`, `messages`, `expected_request` (structured `EventRequest` data), `expected_status` (`quote` | `clarification` | `refused`), tags (`wedding`, `corporate`, `weekend`, `night`, `multi_day`, `package`, `shortage`, `ambiguous`, `accents`), and replay fixtures per node. The set MUST cover: packages and loose items, weekend, night, multi-day, each guest tier boundary, distance bands, at least 2 clarification cases, at least 1 shortage case and at least 1 off-topic case. The catalog and rules MUST come from the seed data and `default_pricing_rules()`.

#### Scenario: Set is well-formed
- Given the golden file
- When the loader validates it
- Then ids are unique, 15 <= count <= 20, every expected request is a valid `EventRequest` and every `quote`-status case has fixtures for all nodes it traverses

### Requirement: Deterministic oracle
For each `quote`-status case the oracle MUST compute `calculate_price(expected_request, catalog, rules)` at test time (no stored totals) and assert: the agent's `quote.total` equals the oracle total; the line codes and quantities equal the oracle lines; every item code exists in the catalog; availability for the request is positive in the test reservation set; and the reply passes `verify` (or the template is used). Assertions MUST be on structure and numbers, not wording.

#### Scenario: Total equals oracle
- Given each quote-status golden case in replay mode
- When the agent runs
- Then `quote.total == calculate_price(expected_request).total.amount`

#### Scenario: Items valid and available
- Given each returned quote
- When its lines are checked
- Then every line code is in the catalog and the availability check passes

#### Scenario: Wrong total detected
- Given a deliberately wrong fixture quote total (a mutated oracle test)
- When the oracle assertion runs
- Then the eval fails, proving the harness can fail

### Requirement: Replay-mode pytest in CI
The golden and injection suites MUST run in the default `pytest` run with `LLM_PROVIDER=replay` and the fake embedder, with no network and no secrets, in CI. Any missing fixture MUST fail the test (no silent skip). The suite MUST be deterministic: two consecutive runs yield identical reports.

#### Scenario: No network
- Given the socket guard
- When the eval suite runs
- Then it passes with zero outbound connections

#### Scenario: Determinism
- Given two runs
- When their report JSON is compared (excluding timestamps)
- Then they are equal

### Requirement: Injection cases in the eval
The eval suite MUST include 8 or more injection cases (the payload classes of `prompt-injection-defense`) as golden entries asserting: no total differs from the oracle, no canary or prompt leakage, no off-allowlist tool call, no URL in reply.

#### Scenario: Injection pass rate
- Given the injection cases
- When run in replay mode
- Then the pass rate is 100%

### Requirement: Eval report
The harness MUST emit a JSON and a Markdown report with: number of cases, `oracle_match_rate` (quote cases whose total equals the oracle), `status_accuracy`, item-level precision and recall (matched codes over returned / expected codes), `retrieval_recall_at_5` per adapter, `fallback_rate` (template used), `injection_pass_rate`, total tokens, estimated cost (micro-USD) and latency p50/p95 per case. Replay mode MUST report latency and token fields from fixtures and flag them as `replay`. The report MUST be written to a gitignored path and a curated copy MAY be committed under `documentacion/`.

#### Scenario: Report fields
- Given a completed run
- When the report is generated
- Then every listed metric is present with a numeric value and the mode (`replay` or `live`)

#### Scenario: Threshold gate in CI
- Given replay mode
- When `oracle_match_rate` < 1.0 or `injection_pass_rate` < 1.0
- Then the pytest run fails

### Requirement: Optional live run
A separate command (not collected by default, enabled by an explicit flag or marker and an API key from the environment) MUST run the golden set against the real provider and MAY send traces to LangSmith. Live mode MUST: use synthetic input only, respect the daily token cap, print the report, and target `oracle_match_rate` >= 0.90 as a goal (reported, not a CI gate). LangSmith tracing MUST be off by default and MUST be disabled in `APP_ENV=production`; startup in production with tracing enabled MUST refuse to enable it (log a WARNING). Screenshots for slides are a manual artifact and out of the automated suite.

#### Scenario: Live not collected by default
- Given `pytest backend/tests`
- When collected without the flag
- Then live tests are deselected and no key is required

#### Scenario: Tracing off in production
- Given `APP_ENV=production` and tracing variables set
- When the app starts
- Then tracing is not enabled and a warning is logged

#### Scenario: Live run respects budget
- Given a live run and an exhausted cap
- When the run starts
- Then it stops with a clear message and no provider call

### Requirement: Harness hygiene
Eval fixtures and reports MUST contain no secrets, real personal data or real hosts. Eval code MUST reuse the production pipeline through the same container wiring (replay provider injected), not a parallel implementation.

#### Scenario: Same pipeline
- Given the eval harness
- When it builds the agent
- Then it uses the production builder with `LLM_PROVIDER=replay`
