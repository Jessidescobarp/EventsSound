# Delta Spec: availability

Change: quote-domain-core. Pure function in `domain/`; the use case and repository port live in `application/`. Availability is NOT exposed over HTTP in this change.

## ADDED Requirements

### Requirement: Half-open timezone-aware intervals
Time ranges MUST be half-open `[start, end)` over timezone-aware datetimes. Naive datetimes and `end <= start` MUST be rejected with a domain error. Comparisons MUST be made on absolute instants, independent of the offset used to express them.

#### Scenario: Naive datetime rejected
- Given a naive start datetime
- When availability is checked
- Then a domain validation error is raised

#### Scenario: Equivalent instants in different offsets
- Given a booking expressed in UTC and a request for the same instant expressed in UTC-5
- When availability is checked
- Then they are treated as the same interval

### Requirement: Stock is consumed by overlapping bookings
`check_availability(item, start, end, bookings, buffer)` MUST return the remaining quantity of an item for the requested interval as `stock_quantity - sum(quantity of bookings of that item whose buffered interval overlaps the request)`, and MUST report available when the remaining quantity is >= the requested quantity. Only bookings for the same item count. Cancelled bookings MUST NOT consume stock. The result MUST be computed for the worst moment of the interval, i.e. concurrent bookings are summed only if they overlap one another within the requested window and, conservatively, MAY be summed whenever each overlaps the request.

#### Scenario: Free calendar
- Given an item with stock 4 and no bookings
- When 4 units are requested
- Then the item is available with 4 remaining

#### Scenario: Partial consumption
- Given stock 4 and an overlapping booking of 3
- When 2 units are requested
- Then the item is unavailable with 1 remaining

#### Scenario: Other item ignored
- Given a booking for a different item overlapping the interval
- When availability is checked
- Then remaining stock is unchanged

#### Scenario: Cancelled booking ignored
- Given an overlapping booking with status cancelled
- When availability is checked
- Then it does not consume stock

#### Scenario: Zero stock
- Given an item with stock 0
- When 1 unit is requested
- Then the item is unavailable with 0 remaining

#### Scenario: Invalid requested quantity
- Given a requested quantity <= 0
- When availability is checked
- Then a domain validation error is raised

### Requirement: Buffer around existing bookings
Each existing booking MUST be expanded by the buffer on both sides (`[start - buffer, end + buffer)`) before the overlap test against the requested interval. The buffer is rule-set data (default 2 hours) and MUST be a non-negative duration; buffer 0 gives pure interval overlap. The requested interval itself is NOT expanded.

#### Scenario: Back-to-back with zero buffer
- Given a booking `[10:00, 14:00)`, buffer 0, stock 1
- When `[14:00, 18:00)` is requested
- Then the item is available

#### Scenario: Back-to-back with default buffer
- Given a booking `[10:00, 14:00)`, buffer 2 hours, stock 1
- When `[14:00, 18:00)` is requested
- Then the item is unavailable

#### Scenario: Exactly the buffer apart
- Given a booking `[10:00, 14:00)`, buffer 2 hours, stock 1
- When `[16:00, 20:00)` is requested
- Then the item is available because the buffered end 16:00 equals the request start

#### Scenario: Inside the buffer
- Given the same booking and buffer
- When `[15:59, 20:00)` is requested
- Then the item is unavailable

#### Scenario: Same-day turnaround
- Given a morning booking `[08:00, 12:00)` of the only unit and a 2-hour buffer
- When `[14:00, 22:00)` is requested the same day
- Then the item is available; when `[13:00, 22:00)` is requested it is unavailable

### Requirement: Multi-day events
Bookings and requests spanning multiple days MUST be handled as single continuous intervals with no day-boundary special cases.

#### Scenario: Multi-day overlap
- Given a booking from Friday 18:00 to Sunday 02:00
- When a request for Saturday 10:00-14:00 is checked with stock 1
- Then the item is unavailable

#### Scenario: Multi-day, clear of buffer
- Given a booking from Friday 18:00 to Sunday 02:00 and a 2-hour buffer
- When a request starts Sunday 04:00
- Then the item is available

### Requirement: Package availability
A package MUST be available for quantity `q` over an interval only if every member item is available for `member_quantity * q` over that interval. The result MUST identify the limiting items (those that fail) and the remaining quantity per member. Requested items and packages in the same request that share a member item MUST have their quantities aggregated before the check.

#### Scenario: All members available
- Given a package of 2 speakers and 1 mixer, with ample stock
- When 1 package is requested
- Then it is available

#### Scenario: One member short
- Given the same package, speaker stock 3 and 2 already booked in the window
- When 1 package is requested
- Then it is unavailable and the speakers are reported as limiting with 1 remaining

#### Scenario: Shared member aggregation
- Given a request for 1 package that needs 2 speakers and 2 extra speakers, with speaker stock 3
- When the request is checked
- Then it is unavailable (4 needed, 3 in stock)

### Requirement: Availability property-based invariants
Property-based tests MUST verify: remaining quantity never exceeds stock; adding a booking never increases remaining quantity; a larger buffer never makes an unavailable request available; shifting all intervals by the same offset does not change the result; and a request entirely outside every buffered booking is available whenever stock >= quantity.

#### Scenario: Properties hold
- Given generated bookings, intervals and buffers
- When the property suite runs
- Then no counterexample is found

### Requirement: Availability use case and port
The `application/` layer MUST provide a use case that loads bookings through a repository port for the requested items and interval and delegates to the pure function. The domain function MUST NOT access the repository.

#### Scenario: Use case with fake repository
- Given an in-memory fake booking repository
- When the use case checks an item and interval
- Then the result equals the pure function applied to the fake's bookings
