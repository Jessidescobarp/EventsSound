# Delta Spec: pricing

Change: quote-domain-core. Location: `domain/` (stdlib only). `calculate_price` is the deterministic eval oracle (prices never come from an LLM). The agent-facing alias `calcular_precio` is out of scope (P2).

## ADDED Requirements

### Requirement: calculate_price is a pure deterministic function
The domain MUST expose `calculate_price(request, catalog, rules) -> Quote`. It MUST NOT perform I/O, read the clock, use randomness, or depend on global state. The same inputs MUST always yield an equal `Quote`. Inputs MUST NOT be mutated.

#### Scenario: Same input, same output
- Given a request, a catalog and a rule set
- When `calculate_price` is called twice
- Then both `Quote` values are equal

#### Scenario: Unknown item or package
- Given a request referencing a code absent from the catalog
- When `calculate_price` is called
- Then a domain error naming the unknown code is raised

#### Scenario: Invalid request
- Given a request with quantity <= 0, guest count < 1, negative distance, `end <= start`, naive (timezone-less) datetimes, or no items and no packages
- When `calculate_price` is called
- Then a domain validation error is raised

### Requirement: Rule set is validated data
`PricingRules` MUST be a frozen data object containing: guest tiers, weekend multiplier, night window (start/end local time) and night surcharge, distance bands with flat surcharge in COP, package discount policy, rounding step, availability buffer, and an IANA timezone (default `America/Bogota`). Multipliers and surcharges MUST be integers in basis points (1 bp = 0.01%) or whole COP. Construction MUST reject: overlapping or unordered guest tiers/distance bands, gaps in tier coverage from 1 guest / 0 km, negative values, multipliers below 10000 bps, rounding step <= 0, unknown timezone, and equal night start/end. Synthetic defaults MUST exist in code; replacing the data MUST NOT require changing `calculate_price`. A holiday calendar (set of dates) MUST be injectable; the default is empty (weekends only).

#### Scenario: Overlapping bands rejected
- Given distance bands 0-20 km and 15-40 km
- When `PricingRules` is built
- Then a domain validation error is raised

#### Scenario: Default night window
- Given the default rules
- When the night window is read
- Then it is 22:00 to 06:00 local time in `America/Bogota` and crosses midnight

#### Scenario: Rules swapped without code change
- Given two rule sets differing only in the rounding step
- When `calculate_price` is called with each
- Then totals are rounded to the respective step

### Requirement: Base price and quantity
Each requested item line MUST cost `unit_price * quantity`. Each requested package line MUST cost the sum of its member items (`unit_price * member_quantity`), times package quantity, minus the package discount. Duplicate lines for the same code MUST be merged by summing quantities.

#### Scenario: Item line
- Given an item priced 100000 COP and quantity 3
- When the quote is calculated with neutral rules
- Then the line subtotal is 300000 COP

#### Scenario: Package discount
- Given a package of items worth 1000000 COP with a 10% discount (1000 bps)
- When one package is requested with otherwise neutral rules
- Then the package line is 900000 COP and the breakdown records the discount of 100000 COP

### Requirement: Order of application
Adjustments MUST be applied in this fixed order, using exact arithmetic (`int`/`Fraction`) throughout: (1) line subtotals with package discounts, summed into the subtotal; (2) guest-tier multiplier on the subtotal; (3) weekend/holiday multiplier; (4) night-hours multiplier; (5) flat distance surcharge added after multipliers (it is not multiplied); (6) rounding, applied exactly once, to the final exact total. Multipliers compose multiplicatively.

#### Scenario: Composition
- Given subtotal 1000000, guest tier 11000 bps, weekend 12000 bps, night 10500 bps and distance surcharge 80000
- When the quote is calculated
- Then the exact total is `1000000 * 1.10 * 1.20 * 1.05 + 80000 = 1466000` and the final total is 1466000 after rounding to 1000

#### Scenario: Rounding applied once
- Given any request
- When intermediate steps are inspected
- Then none of them is rounded, and only the final total is

### Requirement: Guest tiers
Guest count MUST select exactly one tier from the closed-open ranges in the rule set; the tier supplies a multiplier in bps. Counts beyond the last tier MUST use an open-ended last tier or be rejected, as defined by the rules.

#### Scenario: Tier boundaries
- Given tiers `[1,100)`, `[100,300)`, `[300, inf)`
- When guest counts 99, 100 and 300 are priced
- Then they use tier 1, tier 2 and tier 3 respectively

### Requirement: Weekend multiplier
The weekend (or listed holiday) multiplier MUST apply when the event start date, converted to the rule-set timezone, is Saturday or Sunday or in the holiday calendar. Otherwise the factor is 10000 bps (neutral).

#### Scenario: UTC instant on Saturday night in Bogota
- Given a start of 2026-10-11T03:00Z (Saturday 2026-10-10 22:00 in Bogota, UTC-5)
- When priced
- Then the weekend multiplier applies because the local date is Saturday

#### Scenario: Weekday
- Given a start on a Wednesday local date
- When priced
- Then the weekend multiplier is neutral

### Requirement: Night-hours surcharge
The night multiplier MUST apply once (not per hour) when any part of the event interval `[start, end)` overlaps the night window in the rule-set timezone, including windows crossing midnight and multi-day events. The window MUST be rule-set data.

#### Scenario: Event fully in daytime
- Given an event 14:00-20:00 Bogota time
- When priced
- Then no night surcharge applies

#### Scenario: Event ends inside the window
- Given an event 18:00-23:00 Bogota time
- When priced
- Then the night surcharge applies

#### Scenario: Window boundary is half-open
- Given an event 16:00-22:00 Bogota time
- When priced
- Then no night surcharge applies because `[16:00, 22:00)` does not overlap `[22:00, 06:00)`

#### Scenario: Event starting at 05:00
- Given an event 05:00-08:00 Bogota time
- When priced
- Then the night surcharge applies

### Requirement: Distance surcharge tiers
Venue distance in km MUST select exactly one band from closed-open ranges in the rule set; each band carries a flat surcharge in whole COP (zero for the nearest band). Distances beyond the last band MUST use an open-ended band or be rejected, as defined by the rules.

#### Scenario: Band boundaries
- Given bands `[0,20)` surcharge 0 and `[20,60)` surcharge 80000
- When distances 19 and 20 km are priced
- Then surcharges are 0 and 80000

### Requirement: Quote value object and explainable breakdown
`Quote` MUST be a frozen value object with: ordered line items (code, kind item/package, quantity, unit price, line total, discount), an ordered breakdown of steps (rule key, human-readable English label, applied basis points or flat amount, resulting running amount in whole pesos), a `rounding_adjustment` (signed integer pesos), and `total` as `Money`. The sum of line totals, step deltas and rounding adjustment MUST equal `total`. Every adjustment that altered the price MUST appear in the breakdown; neutral steps MAY be omitted. Breakdown ordering MUST follow the order of application so that a downstream agent can explain the price without recomputing it.

#### Scenario: Total reconciles
- Given any valid request
- When the quote is built
- Then `total` equals the line subtotal plus every step delta plus `rounding_adjustment`

#### Scenario: Explainability
- Given a Saturday night event with a 25 km venue
- When the quote is built
- Then the breakdown contains the weekend, night and distance steps, in that relative order, each with its rule key and applied value

### Requirement: Pricing property-based invariants
Property-based tests (Hypothesis, dev dependency) MUST verify, over generated valid inputs and valid rule sets:
- Totals are non-negative and a multiple of the rounding step.
- Monotonic in quantity: increasing any line's quantity never decreases the total.
- Determinism: repeated evaluation yields equal quotes.
- Reconciliation: line totals plus step deltas plus rounding adjustment equal the total.
- Rounding idempotence: rounding the total again leaves it unchanged.
- Neutral rules (all multipliers 10000 bps, zero surcharges, no discount, step 1) yield the sum of `unit_price * quantity`.
- Permuting the order of requested lines does not change the total.

#### Scenario: Properties hold
- Given generated requests and rules
- When the property suite runs
- Then no counterexample is found and the suite is seeded or deterministic enough to be reproducible in CI
