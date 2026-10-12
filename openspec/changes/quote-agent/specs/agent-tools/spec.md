# Delta Spec: agent-tools

Change: quote-agent. Tools are plain application use cases wrapped by thin `adapters/agent/` schemas (Pydantic, `extra="forbid"`). They are read-only, have no side effects and are invoked by the graph, never by free-form model output. Tool names stay in Spanish by design.

## ADDED Requirements

### Requirement: Tool registry and allowlist
There MUST be exactly three tools: `buscar_equipamiento`, `consultar_disponibilidad`, `calcular_precio`. The executor MUST dispatch only names in a fixed allowlist; any other name MUST return a `unknown_tool` tool error and MUST NOT execute anything. The graph, not the model, decides which tool runs at each node; a model-proposed tool name is data to be checked, never trusted.

#### Scenario: Unknown tool
- Given a model output requesting `borrar_catalogo`
- When the executor dispatches it
- Then a `unknown_tool` error is returned, nothing runs, and the event is logged with the tool name only

#### Scenario: Registry is exact
- Given the registry
- When its keys are listed
- Then they equal `{buscar_equipamiento, consultar_disponibilidad, calcular_precio}`

### Requirement: Strict argument validation
Each tool MUST validate arguments with a Pydantic model using `extra="forbid"`, strict types (no coercion of strings to ints or bools), and bounded values: `query` 1..200 chars; `category` one of the `EquipmentCategory` values; `limit` 1..10; request lines at most 100, quantities 1..10,000, `guest_count` 1..100,000, `distance_km` 0..5,000, tz-aware ISO-8601 datetimes with `end > start` and duration <= 31 days (the `EventRequest` bounds). Validation failure MUST NOT call the use case.

#### Scenario: Extra field smuggled
- Given arguments `{"query": "luces", "price_override": 1}`
- When `buscar_equipamiento` is validated
- Then validation fails with `invalid_arguments` and the use case is not called

#### Scenario: Type coercion refused
- Given `quantity: "3"` or `quantity: true`
- When `calcular_precio` is validated
- Then validation fails

#### Scenario: Out of bounds
- Given `guest_count: 0`, `distance_km: -1`, `end <= start`, a naive datetime, or 101 lines
- When validated
- Then each fails with `invalid_arguments`

### Requirement: buscar_equipamiento
It MUST call `EquipmentSearch.search(query, category, limit)` and return hits with `code`, `name`, `category`, `unit_price_cop`, `kind`. It MUST return only catalog data.

#### Scenario: Hits returned
- Given a catalog with a speaker item
- When called with `{"query": "parlante"}`
- Then the result contains that item's code and its catalog price

### Requirement: consultar_disponibilidad
It MUST build an `EventRequest` from validated arguments, call the existing `check_event_availability` use case and return `is_available` plus `shortages` (`item_code`, `requested`, `available`). Unknown codes MUST yield `unknown_code` naming the code.

#### Scenario: Shortage reported
- Given 3 speakers in stock and 2 reserved in the window
- When 2 are requested
- Then `is_available` is false and the shortage lists requested 2, available 1

#### Scenario: Unknown code
- Given a line with code `no_existe`
- When called
- Then a `unknown_code` tool error naming `no_existe` is returned

### Requirement: calcular_precio is the only source of money
`calcular_precio` MUST call the existing `price_quote` use case (which wraps `calculate_price`) and return `Quote.to_dict()` unmodified. No other tool, node or prompt template MAY compute, estimate, convert or format a monetary value that is later presented as a price. Tool arguments MUST NOT accept any price, discount, total or rate field.

#### Scenario: Result equals the oracle
- Given a valid request
- When `calcular_precio` runs
- Then its `total` equals `calculate_price(request, catalog, rules).total.amount`

#### Scenario: Price fields refused
- Given arguments containing `unit_price`, `total`, `discount_bps` or `rate`
- When validated
- Then `invalid_arguments` is returned

#### Scenario: Static guard
- Given the agent package
- When a test scans `adapters/agent/` for arithmetic on `Money`, `unit_price` or `amount` outside calls to the use case
- Then none is found

### Requirement: Tool errors are safe data
Tool failures MUST be returned to the graph as `ToolError(code, message)` with `code` in a closed set (`unknown_tool`, `invalid_arguments`, `unknown_code`, `unavailable`, `internal`) and a fixed generic English message. They MUST NOT include stack traces, SQL, hosts, exception text or user-supplied strings. `RepositoryUnavailable` MUST map to `unavailable`; any other exception MUST map to `internal` and be logged by class name only.

#### Scenario: Repository down
- Given a repository raising `RepositoryUnavailable("host db.internal refused")`
- When any tool runs
- Then the result is `ToolError("unavailable", ...)` whose message does not contain `db.internal`

#### Scenario: User text not echoed
- Given an invalid argument value `"<script>alert(1)</script>"`
- When validation fails
- Then the error payload does not contain that string

### Requirement: Tool call accounting
Each tool execution MUST be logged with tool name, outcome code and duration only (no arguments, no results) and MUST be bounded: a per-request maximum of tool calls (see `quote-agent`) MUST be enforced by the executor.

#### Scenario: Budget enforced
- Given a per-request limit of N tool calls
- When call N+1 is attempted
- Then a `tool_budget_exceeded` error stops the pipeline
