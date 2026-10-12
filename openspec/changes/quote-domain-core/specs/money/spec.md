# Delta Spec: money

Change: quote-domain-core. Location: `domain/` (stdlib only).

## ADDED Requirements

### Requirement: Money is an immutable integer value object
`Money` MUST be a frozen value object holding an `int` amount in whole COP pesos and a currency code (default `COP`). The amount MUST NOT be a `float`, `Decimal` with fractional part, or any non-integer. `bool` MUST be rejected as an amount. Any sign is allowed (discount lines are negative; design D2).

#### Scenario: Construct valid money
- Given an integer amount 150000
- When `Money(150000)` is created
- Then `amount` is 150000 and `currency` is `COP`

#### Scenario: Float rejected
- Given the value 1500.5
- When `Money(1500.5)` is created
- Then a domain validation error is raised

#### Scenario: Negative allowed
- Given the value -1
- When `Money(-1)` is created
- Then it is a valid amount (discount and rounding lines can be negative)

#### Scenario: Immutability
- Given a `Money` instance
- When code attempts to assign to `amount`
- Then the assignment fails

### Requirement: Money arithmetic is exact and currency-safe
`Money` MUST support addition, subtraction and negation of `Money`, multiplication by an `int`, and comparison. Operations between different currencies MUST raise a domain error. Subtraction and negation MAY yield negative amounts. Multiplication by a `float` MUST be rejected. `Money.percent(bps)` MUST return the integer half-up percentage in basis points.

#### Scenario: Add and multiply
- Given `Money(1000)` and `Money(2500)`
- When they are added and `Money(1000)` is multiplied by 3
- Then the results are `Money(3500)` and `Money(3000)`

#### Scenario: Currency mismatch
- Given `Money(1000, "COP")` and `Money(1000, "USD")`
- When they are added
- Then a domain error is raised

#### Scenario: Subtraction below zero
- Given `Money(1000)` and `Money(2000)`
- When `Money(1000) - Money(2000)` is evaluated
- Then the result is `Money(-1000)`

### Requirement: Rounding is half-up to a configurable step
`Money.round_to(step)` MUST round an integer amount (any sign) to the nearest multiple of a positive integer step, with ties rounded toward positive infinity (`(2 * amount + step) // (2 * step) * step`). Implementation MUST use integer arithmetic only; floats, `Decimal` and `Fraction` MUST NOT appear anywhere in the money or pricing code path.

#### Scenario: Table of roundings (step 1000)
- Given the exact values 0, 499, 500, 1499, 1500, 1999, 2500
- When each is rounded with step 1000
- Then results are 0, 0, 1000, 1000, 2000, 2000, 3000

#### Scenario: Negative input
- Given the amounts -500 and -501
- When rounded with step 1000
- Then the results are 0 and -1000 (half rounds toward positive infinity)

#### Scenario: Invalid step
- Given a step of 0 or a negative step
- When rounding is requested
- Then a domain error is raised

#### Property: Rounding invariants
- For any integer `x` and step `s > 0`: the result is a multiple of `s`; `|result - x| <= s/2`; rounding an already rounded amount returns it unchanged (idempotence); and rounding is monotonic (`x <= y` implies `round(x) <= round(y)`). Hypothesis-based tests land with the pricing properties (A3b).
