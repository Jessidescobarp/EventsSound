# Delta Spec: cost-cap

Change: quote-agent. `BudgetGate` port in `application/`; adapters: in-memory (stopgap, Q6) and SQLAlchemy over `llm_usage_daily` (Q7). Both satisfy the same contract tests.

## ADDED Requirements

### Requirement: BudgetGate port
`application/` MUST define `BudgetGate` with `reserve(estimated_tokens: int) -> Reservation` (raises `BudgetExhausted`) and `settle(reservation, actual_tokens: int, cost_micro_usd: int) -> None`, plus `release(reservation)` for runs that never reached the provider. The day key MUST be the UTC calendar date from an injected clock. Estimates MUST be conservative: per-request estimate = prompt size estimate + `max_output_tokens` of all planned calls, from settings, and MUST include embedding calls.

#### Scenario: Contract suite
- Given the same behavioural tests
- When run against the in-memory and the SQL adapters
- Then both pass

### Requirement: Table llm_usage_daily
A reversible Alembic revision (own revision, schema only, after the latest head) MUST create `llm_usage_daily(day DATE PRIMARY KEY, tokens BIGINT NOT NULL DEFAULT 0, cost_micro_usd BIGINT NOT NULL DEFAULT 0, updated_at TIMESTAMPTZ NOT NULL DEFAULT now())` with CHECK constraints `tokens >= 0` and `cost_micro_usd >= 0`, constraint names following `NAMING_CONVENTION`. `downgrade()` MUST drop the table. Tests run under `DATABASE_URL_TEST` including upgrade/downgrade/upgrade and a model-vs-migration drift check.

#### Scenario: Round trip
- Given a database at the previous head
- When the revision is upgraded, downgraded and upgraded
- Then the table exists, is absent, and exists again

#### Scenario: Negative rejected
- Given the table
- When inserting `tokens = -1`
- Then the CHECK constraint rejects it

### Requirement: Atomic reserve and settle
`reserve` MUST execute a single atomic statement equivalent to `INSERT ... ON CONFLICT (day) DO UPDATE SET tokens = tokens + :n WHERE llm_usage_daily.tokens + :n <= :cap RETURNING tokens`; zero rows returned MUST mean exhausted. No read-then-write in application code. `settle` MUST adjust `tokens` by `actual - estimated` (never below 0) and add `cost_micro_usd` in one statement. `release` MUST subtract the reserved amount. The cap MUST come from settings (`DAILY_TOKEN_CAP`, default 100000); cap 0 MUST reject every reserve.

#### Scenario: Cap respected under concurrency
- Given cap 1000, estimate 100 and 30 concurrent reserves against the real database
- When all complete
- Then exactly 10 succeed and `tokens` equals 1000

#### Scenario: Settle refunds overestimate
- Given a reservation of 500 and actual usage 300
- When settled
- Then `tokens` increased by 300 in total and cost recorded

#### Scenario: Settle overrun
- Given a reservation of 500 and actual usage 700
- When settled
- Then `tokens` increased by 700 (overrun recorded; the next reserve may fail)

#### Scenario: Release
- Given a reservation of 500 and no provider call
- When released
- Then `tokens` returns to its previous value

#### Scenario: Cap zero
- Given `DAILY_TOKEN_CAP=0`
- When reserving any positive estimate
- Then `BudgetExhausted` is raised

### Requirement: Behaviour at exhaustion
When exhausted, `/quote/chat` MUST return 503 `daily_budget_exhausted` with no LLM or embedding call and the response MUST NOT reveal the cap or remaining tokens. The day rolls over at 00:00 UTC (a new row), restoring capacity without a deploy.

#### Scenario: Exhausted then next day
- Given a full budget and an injected clock advancing past 00:00 UTC
- When posting again
- Then the request is served and a new row exists for the new day

### Requirement: Failure policy
If the budget store is unreachable the gate MUST fail closed: `reserve` raises `BudgetUnavailable`, the endpoint returns 503 `daily_budget_exhausted` (never an uncapped LLM call) and logs the error class only. A failing `settle` MUST NOT change the HTTP response of an already-produced answer; it MUST log a WARNING.

#### Scenario: Store down
- Given a gate whose database raises on reserve
- When posting
- Then 503 `daily_budget_exhausted` and zero provider calls

#### Scenario: Settle fails after answer
- Given a gate whose settle raises
- When the agent already produced a quote
- Then the response is still 200 and a warning is logged

### Requirement: In-memory stopgap behind the same port
The in-memory adapter MUST be thread-safe (lock), per-process and day-keyed, and MUST be the default only when no database budget is wired. Startup in `APP_ENV=production` with the in-memory adapter and a real provider (`LLM_PROVIDER` not `replay`) MUST log a WARNING and the docs MUST state the budget resets on restart; public deploy requires the SQL adapter.

#### Scenario: Thread safety
- Given cap 1000, estimate 100 and 30 threads on the in-memory adapter
- When all reserve
- Then exactly 10 succeed

#### Scenario: Production warning
- Given production settings, real provider and the in-memory gate
- When the container is built
- Then a warning is logged that the cap is not persistent
