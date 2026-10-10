# Delta Spec: money

Change: quote-domain-core. Location: `domain/` (stdlib only).

## ADDED Requirements

### Requirement: Money is an immutable integer value object
`Money` MUST be a frozen value object holding an `int` amount in whole COP pesos and a currency code (default `COP`). The amount MUST NOT be a `float`, `Decimal` with fractional part, or any non-integer. `bool` MUST be rejected as an amount.

#### Scenario: Construct valid money
- Given an integer amount 150000
- When `Money(150000)` is created
- Then `amount` is 150000 and `currency` is `COP`

#### Scenario: Float rejected
- Given the value 1500.5
- When `Money(1500.5)` is created
- Then a domain validation error is raised

#### Scenario: Negative rejected
- Given the value -1
- When `Money(-1)` is created
- Then a domain validation error is raised

#### Scenario: Immutability
- Given a `Money` instance
- When code attempts to assign to `amount`
- Then the assignment fails

### Requirement: Money arithmetic is exact and currency-safe
`Money` MUST support addition of two `Money`, multiplication by a non-negative `int`, and comparison. Operations between different currencies MUST raise a domain error. Subtraction MUST raise if the result would be negative. Multiplication by a `float` MUST be rejected.

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
- Then a domain error is raised

### Requirement: Rounding is half-up to a configurable step
The domain MUST provide a rounding function that takes an exact non-negative value (`int` or `Fraction`) and a positive integer step (default 1000) and returns `Money` rounded to the nearest multiple of the step, with ties rounded up. Implementation MUST use integer or `Fraction` arithmetic only; floats MUST NOT appear anywhere in the money or pricing code path.

#### Scenario: Table of roundings (step 1000)
- Given the exact values 0, 499, 500, 1499, 1500, 1999, 2500
- When each is rounded with step 1000
- Then results are 0, 0, 1000, 1000, 2000, 2000, 3000

#### Scenario: Fractional input
- Given the exact value `Fraction(2999, 2)` (1499.5)
- When rounded with step 1000
- Then the result is `Money(1000)`

#### Scenario: Invalid step
- Given a step of 0 or a negative step
- When rounding is requested
- Then a domain error is raised

#### Property: Rounding invariants
- For any non-negative integer or Fraction `x` and step `s > 0`: the result is a multiple of `s`; `|result - x| <= s/2`; rounding an already rounded amount returns it unchanged (idempotence); and rounding is monotonic (`x <= y` implies `round(x) <= round(y)`).
