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
`PricingRules` MUST be a frozen data object containing: guest tiers, weekend multiplier, night window (start/end local time) and night surcharge, distance bands with a marginal rate per km in COP, a package discount cap (`max_package_discount_bps`), rounding step, and a timezone (the availability buffer lives in `AvailabilityRules`, not here). The rules hold a `tzinfo` object (default `ZoneInfo("America/Bogota")`), never a zone name: an unknown IANA name fails earlier, when the caller builds the `ZoneInfo` (`ZoneInfoNotFoundError`), and `PricingRules` rejects anything that is not a `tzinfo`. Percentage surcharges MUST be integers in basis points (1 bp = 0.01%) and rates whole COP. Construction MUST reject: overlapping or unordered guest tiers/distance bands, a first tier not starting at 1 guest, decreasing tier surcharges, negative values, rounding step <= 0, a missing or non-`tzinfo` timezone, equal night start/end, and an empty weekend-day set. Collections are coerced to immutable types so rules stay hashable. Synthetic defaults MUST exist in code; replacing the data MUST NOT require changing `calculate_price`. A holiday calendar (set of dates) MUST be injectable; the default is empty (weekends only).

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
Each requested item line MUST cost `unit_price * quantity`. Each requested package line MUST cost the sum of its member items (`unit_price * member_quantity`), times package quantity, minus the package discount (`ServicePackage.discount_bps`, capped by `PricingRules.max_package_discount_bps`). Item and package amounts are multiplied by the rental days (`max(1, ceil((end - start) / 24h))`). Duplicate lines for the same code MUST be merged by summing quantities.

#### Scenario: Item line
- Given an item priced 100000 COP and quantity 3
- When the quote is calculated with neutral rules
- Then the line subtotal is 300000 COP

#### Scenario: Package discount
- Given a package of items worth 1000000 COP with a 10% discount (1000 bps)
- When one package is requested with otherwise neutral rules
- Then a `PACKAGE` line of 1000000 COP and a `PACKAGE_DISCOUNT` line of -100000 COP are emitted, and together they net to 900000 COP

### Requirement: Order of application
Adjustments MUST be applied in this fixed order, using integer arithmetic throughout (design section 5): (1) line subtotals with package discounts, summed into the equipment subtotal E; (2) guest-size, (3) weekend/holiday and (4) night percentages, each computed on E and ADDED (not compounded; each percentage line is rounded half-up to the peso); (5) marginal per-km distance lines, not multiplied; (6) rounding of the raw total to the step, applied exactly once and recorded as an explicit `ROUNDING` line.

#### Scenario: Composition
- Given default rules, 2 x speaker at 120000 and 1 x mixer at 79900, 150 guests, Saturday 20:00-23:30 Bogota, 45 km
- When the quote is calculated
- Then E is 319900, guest 10% is 31990, weekend 15% is 47985, night 20% is 63980, distance 25 km x 3000 is 75000, raw total 538855, total 539000 with a `ROUNDING` line of +145

#### Scenario: Rounding applied once
- Given any request
- When intermediate steps are inspected
- Then none of them is rounded, and only the final total is

### Requirement: Guest tiers
Guest count MUST select the last tier whose `min_guests` is <= the count; the tier supplies a surcharge in bps applied to E. The last tier is open-ended.

#### Scenario: Tier boundaries
- Given default tiers starting at 1, 101, 301 and 601 guests
- When guest counts 100, 101 and 300 are priced
- Then they use the 0%, 10% and 10% tiers respectively

### Requirement: Weekend multiplier
One flat weekend/holiday surcharge (percentage of E) MUST apply when ANY local date (rule-set timezone) touched by `[start, end)` (end exclusive) is a weekend day or in the holiday calendar. Otherwise no line is emitted.

#### Scenario: UTC instant on Saturday night in Bogota
- Given a start of 2026-10-11T03:00Z (Saturday 2026-10-10 22:00 in Bogota, UTC-5)
- When priced
- Then the weekend surcharge applies because the local date is Saturday

#### Scenario: Weekday
- Given a start on a Wednesday local date
- When priced
- Then no weekend line is emitted

### Requirement: Night-hours surcharge
The night surcharge MUST apply once (not per hour) when any part of the event interval `[start, end)` overlaps the night window instance of any touched local date, or of the previous evening, in the rule-set timezone, including windows crossing midnight and multi-day events. The window MUST be rule-set data.

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
Venue distance in km MUST be charged marginally per band: each band carries a rate per km in whole COP (zero for the nearest band) applied only to the km inside that band, producing one `DISTANCE` line per non-free band. The last band is open-ended. There are no cliffs between bands.

#### Scenario: Band boundaries
- Given default bands (20 km free, up to 60 km at 3000/km, beyond at 4500/km)
- When distances 19, 20 and 21 km are priced
- Then distance charges are 0, 0 and 3000

### Requirement: Quote value object and explainable breakdown
`Quote` MUST be a frozen value object with `schema_version`, `rules_version`, `currency`, `rental_days`, an ordered tuple of `QuoteLine` (kind, code, label, quantity, periods, unit_amount, rate_bps, basis, signed amount), `subtotal` (raw total) and `total` as `Money`, plus `to_dict()` emitting JSON primitives only. The sum of all line amounts, including the explicit `ROUNDING` line, MUST equal `total`. Every non-rounding line MUST be reproducible from its own fields. Neutral adjustments emit no line. Line order follows the order of application (items, packages with discount, guest, weekend, night, distance, rounding) so a downstream agent can explain the price without recomputing it.

#### Scenario: Total reconciles
- Given any valid request
- When the quote is built
- Then `total` equals the sum of all line amounts including the `ROUNDING` line

#### Scenario: Explainability
- Given a Saturday night event with a 25 km venue
- When the quote is built
- Then the lines contain the weekend, night and distance entries, in that relative order, each with its code and applied value

### Requirement: Pricing property-based invariants
Property-based tests (Hypothesis, dev dependency) MUST verify, over generated valid inputs and valid rule sets:
- Totals are non-negative and a multiple of the rounding step.
- Monotonic in quantity: increasing any line's quantity never decreases the total.
- Determinism: repeated evaluation yields equal quotes.
- Reconciliation: the sum of all line amounts equals the total.
- Rounding idempotence: rounding the total again leaves it unchanged.
- Neutral rules (all percentages 0 bps, zero rates, no discount, step 1) yield the sum of `unit_price * quantity`.
- Permuting the order of requested lines does not change the total.

#### Scenario: Properties hold
- Given generated requests and rules
- When the property suite runs
- Then no counterexample is found and the suite is seeded or deterministic enough to be reproducible in CI
